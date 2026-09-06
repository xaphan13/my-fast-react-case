# 02. Архитектура и паттерны

> Часть 2 из 4. См. также: [01_project_structure.md](01_project_structure.md), [03_execution_flow.md](03_execution_flow.md), [04_code_quality.md](04_code_quality.md)

## Высокоуровневая архитектура

**Монолитное асинхронное ASGI-приложение** с частично реализованной слоистой архитектурой. Единица развёртывания одна, внутренних сетевых границ нет, межсервисного взаимодействия нет.

Слои, если идти сверху вниз:

```
┌──────────────────────────────────────────────────────────────────┐
│  Транспорт        uvicorn (dev) │ gunicorn + UvicornWorker (prod) │
│                   опционально за nginx (TLS, reverse proxy)       │
├──────────────────────────────────────────────────────────────────┤
│  Клиент (блог)    React SPA (frontend/, Vite + TS + Tailwind v4)  │
│                   JSON-запросы к /api/blog, cookie-сессии         │
├──────────────────────────────────────────────────────────────────┤
│  Композиция       create_fastapi.create_app() → main.main_app     │
│                   include_router × 3 + include_router_api_frontend +    │
│                   mount_vite_react_assets (mount /assets, SPA catch-all),       │
│                   lifespan                                       │
├──────────────────────────────────────────────────────────────────┤
│  Presentation     APIRouter'ы; pydantic-схемы запросов/ответов    │
│                   валидация входа и сериализация выхода;          │
│                   блог — JSON /api/blog вместо HTML-шаблонов      │
├──────────────────────────────────────────────────────────────────┤
│  Dependency       Depends: сессия БД, извлечение параметров,      │
│  Injection        проверка токена, require_login_api, фабрики     │
├──────────────────────────────────────────────────────────────────┤
│  Application      ex_user_post/crud/  ← присутствует              │
│                   ex_order_product/   ← ОТСУТСТВУЕТ (SQL в роутах) │
├──────────────────────────────────────────────────────────────────┤
│  Data Access      AsyncDbManager, AsyncSession, ORM-модели        │
├──────────────────────────────────────────────────────────────────┤
│  Хранилище        PostgreSQL (asyncpg) │ SQLite (aiosqlite)       │
│                   + файлы: articles.yaml, content_art/, аватары   │
└──────────────────────────────────────────────────────────────────┘
```

**Ключевая асимметрия архитектуры:** слой приложения реализован только в домене `ex_user_post`. Домен `ex_order_product` обращается к `AsyncSession` напрямую из обработчиков, минуя этот слой. Оба подхода живут в одной кодовой базе; см. [04_code_quality.md](04_code_quality.md), раздел «Модульность».

### Границы модулей

`db_core/` — инфраструктурный слой без обратных зависимостей на предметные области, за одним исключением: `db_core/__init__.py` импортирует модели из `ex_user_post` и `ex_order_product`. Это **осознанный компромисс** — реэкспорт нужен, чтобы `Base.metadata` был заполнен к моменту запуска Alembic `--autogenerate`. Технически это циклическая зависимость на уровне пакетов, но она не проявляется в рантайме, потому что модели импортируют `db_core.model_base`, а не `db_core` целиком.

`core/config.py` — самый нижний уровень: от него зависит почти всё (`db_core`, `api`, `create_fastapi`, `alembic/env.py`), он же не зависит ни от чего, кроме `base_dir_path`.

`config_log.py` — полностью изолированная подсистема на уровне корня приложения. Не зависит от FastAPI, не интегрирована в его цикл логирования.

`md_articles/` — третий прикладной пакет, зависит от `db_core` (сессии, модели) и `base_dir_path` (пути контента). Подключается из `create_fastapi.py`, а не из `main.py`. Особенность: помимо роутера пакет регистрирует **middleware и mount** — это единственное место приложения с кросс-запросной логикой уровня HTTP. Реестр статей (`articles.yaml`) и контент (`content_art/`) — файловое хранилище вне БД; клиентская часть (`frontend/`) — отдельное npm-приложение (React 18 + TypeScript + Vite), от сервера зависит только контрактом JSON API: в dev — свой сервер Vite :5173 с прокси `/api` и `/static` на :8000, в проде FastAPI раздаёт собранную статику `frontend/dist` (mount `/assets` + SPA catch-all).

---

## Паттерны проектирования

### 1. Application Factory

`create_fastapi.py:24` — единственное место создания экземпляра `FastAPI`:

```python
def create_app(custom_docs_url: bool = False) -> FastAPI:
    docs_url, redoc_url = (None, None) if custom_docs_url else ("/docs", "/redoc")
    app = FastAPI(
        title="Example Request Parameters Extraction",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
    )
    if custom_docs_url:
        reg_docs_routes(app)

    return app
```

Фабрика параметризована одним флагом, переключающим встроенную документацию на кастомную (`utils/docs.py`). Каркас ограничен конструктором `FastAPI(...)` и `lifespan` — блог подключается **снаружи** в `main.py` через `include_router_api_frontend(main_app)` после доменных `include_router`. Это даёт два эффекта: (1) `create_app()` возвращает минимальный каркас без middleware блога — тестам удобно подключать только нужное; (2) в `main.py` виден полный «рецепт» приложения (домены → блог → SPA).

### 2. Dependency Injection (основной паттерн проекта)

DI используется в трёх разных ролях:

**а) Инъекция ресурса — сессии БД.** Свёрнута в один переиспользуемый алиас (`db_core/db_async.py:78`):

```python
CurrentSession = Annotated[AsyncSession, Depends(db_manager.get_async_session)]
```

Обработчики объявляют `db: CurrentSession` и не знают ни о фабрике сессий, ни о движке. Зависимость реализована генератором, что даёт точку teardown.

**б) Dependency Factory (замыкание).** `api/dependencies/func_deps.py` — функция, возвращающая зависимость:

```python
def get_header_dependency(header_name: str, default_value: str = ""):
    def dependency(header: Annotated[str, Header(alias=header_name)] = default_value) -> str:
        return header
    return dependency
```

Это обход ограничения FastAPI: имя заголовка нужно знать на этапе построения сигнатуры, а не в рантайме. Самая переиспользуемая зависимость в проекте — по графу вызовов у неё максимальный fan-in среди прикладных функций.

**в) Класс как зависимость.** Три варианта, все в `api/dependencies/`:

| Вариант | Реализация | Как объявляется |
|---|---|---|
| Класс с параметрами в `__init__` | `GreatService.__init__` объявляет `Header(...)` | `Depends(GreatService)` |
| Экземпляр с `__call__` | `HeaderAccessDependency.__call__` | `Depends(HeaderAccessDependency(secret_token=...))` |
| Метод-генератор экземпляра | `PathReaderDependency.as_dependency` | `Depends(PathReaderDependency(source=...).as_dependency)` |

Третий вариант интересен тем, что конфигурация (`source`) фиксируется при создании экземпляра, а per-request данные (`Request`, заголовок) приходят через сигнатуру метода и сбрасываются после `yield`.

### 3. Repository / Data Access Object — частично

`ex_user_post/crud/crud_users.py` реализует функциональный вариант репозитория: модуль свободных функций, принимающих `session` первым аргументом.

```python
async def get_all_users(session: AsyncSession) -> Sequence[User]: ...
async def create_user(session: AsyncSession, user_create: UserCreate) -> User: ...
```

Сессия передаётся извне, а не создаётся внутри — функции остаются тестируемыми и композируемыми в рамках одной транзакции. Однако `create_user` сам вызывает `session.commit()`, что делает невозможной композицию нескольких CRUD-операций в одну транзакцию.

В домене `ex_order_product` этот паттерн **не применён**: все шесть обработчиков в `router_order_one.py` строят `Select`/`Insert` и вызывают `db.execute()` напрямую.

### 4. Declarative Base + Convention over Configuration

`db_core/model_base.py` — имена таблиц выводятся из имён классов, а не задаются:

```python
class Base(DeclarativeBase):
    __abstract__ = True
    metadata = MetaData(naming_convention=settings.db.naming_convention)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return f"{camel_case_to_snake_case(cls.__name__)}s"
```

`Order` → `orders`, `User` → `users`, `Product` → `products`. Конвенция ломается на `OrderProductAssociation` (дало бы `order_product_associations`), поэтому там `__tablename__` задан явно — иначе `secondary="order_product_association"` в `relationship` не нашёл бы таблицу.

`naming_convention` в `MetaData` — это то, что делает имена констрейнтов детерминированными и, как следствие, автогенерируемые миграции воспроизводимыми. Видно в миграциях: `op.f("fk_order_product_association_order_id_orders")`, `op.f("pk_users")`.

### 5. Type Aliasing для колонок (DRY на уровне схемы)

`db_core/type_for_models.py` — повторяющиеся определения колонок вынесены в `Annotated`-типы:

```python
int_primary_key = Annotated[int, mapped_column(primary_key=True, index=True)]
time_stamp_utc  = Annotated[datetime, mapped_column(DateTime(timezone=True),
                            default=lambda: datetime.now(timezone.utc),
                            server_default=func.now())]
```

Модели остаются декларативными: `id: Mapped[int_primary_key]`, `promocode: Mapped[str_len_50 | None]`.

### 6. Mixin

`ex_user_post/models/model_id_pk_mixin.py` — `IntIdPkMixin` как альтернатива `Annotated`-типу для того же PK. Применён только в `TestUser`; остальные модели используют `int_primary_key`. Два способа решения одной задачи сосуществуют — это демонстрационный, а не производственный выбор.

### 7. Adapter (внешняя библиотека → внутренний интерфейс)

`core/gunicorn/gunicorn_app.py` адаптирует программный запуск gunicorn:

```python
class MyGunicornApp(BaseApplication):
    def load(self): return self.application

    @property
    def config_options(self) -> dict:
        return {k: v for k, v in self.options.items()
                if k in self.cfg.settings and v is not None}
```

`config_options` фильтрует опции по двум критериям: ключ известен gunicorn и значение не `None`. Это защищает от падения на незнакомой опции.

### 8. Singleton через модульный уровень

Идиоматичный для Python вариант: `settings` (`core/config.py:109`), `db_manager` (`db_async.py:69`), `logF`/`logFC` (`config_log.py:128`) создаются один раз при импорте модуля. Дополнительно `ConfigLogger` использует явный флаг однократной инициализации `isSetting`.

**Следствие:** побочные эффекты при импорте. Импорт `core.config` читает `.env` и падает, если `db.url` не задан; импорт `config_log` создаёт директорию на диске; импорт `db_core.db_async` создаёт движок SQLAlchemy. Это ограничивает тестируемость — см. [04_code_quality.md](04_code_quality.md).

### 9. Иерархия схем ответов (Composition через наследование)

`ex_order_product/schema_order_product.py` строит дерево схем под разные стратегии загрузки связей:

```
OrderProductBase (from_attributes = True)
└── OrderResp
    ├── OrderRespWithProducts          products: List[ProductResp]
    ├── OrderRespWithAssoc             products_details: List[AssociationResp]
    ├── OrderRespWithProductsAssoc     оба поля
    └── OrderRespWithProductsDetails   products: List[ProductRespWithsAssoc]
```

Каждая схема соответствует конкретному набору `joinedload`/`selectinload` в запросе. Позволяет контролировать глубину сериализации на уровне типов и не отдавать лишнего.

---

## Поток данных

### Чтение: `GET /orders/get_all_join`

```
Клиент
  │  GET /orders/get_all_join?variant=1
  ▼
nginx (опционально) ── TLS, X-Forwarded-For ──────────────────────┐
  ▼                                                              │
uvicorn / gunicorn UvicornWorker                                 │
  ▼                                                              │
FastAPI: маршрутизация                                           │
  │   main_app → r_order_one (prefix=/orders) → get_all_join      │
  ▼                                                              │
Разрешение зависимостей                                          │
  │   db: CurrentSession → db_manager.get_async_session()         │
  │   ├── session_factory() → AsyncSession                        │
  │   └── yield session          ← точка входа в контекст         │
  │   variant: int = 1  ← из query string, валидация pydantic     │
  ▼                                                              │
Обработчик get_all_join (router_order_one.py)                    │
  │   select(Order).order_by(Order.id).options(joinedload(...))   │
  ▼                                                              │
AsyncSession.execute(stmt)                                       │
  ▼                                                              │
SQLAlchemy Core → компиляция SQL под диалект                     │
  ▼                                                              │
asyncpg / aiosqlite ── пул соединений (pool_size=50, overflow=10)│
  ▼                                                              │
PostgreSQL / SQLite: один SQL с LEFT OUTER JOIN                  │
  │                                                              │
  ▼ Result[tuple[Order]]                                         │
.unique().scalars().all() → Sequence[Order]  ← dedup обязателен  │
  │                          при joinedload на collection        │
  ▼                                                              │
response_model=list[OrderRespWithProducts]                       │
  │   pydantic: from_attributes=True, обход ORM-объектов          │
  ▼                                                              │
ORJSONResponse ── сериализация orjson ────────────────────────────┘
  ▼
Клиент (JSON)

После возврата ответа:
  генератор get_async_session возобновляется → выход из
  async with session_factory() → session.close()
```

### Запись: `POST /users/create_user`

```
Клиент: POST /users/create_user  {nickname, firstname, surname, password}
  ▼
FastAPI: r_users_sql → create_user
  ▼
Зависимости:
  session: CurrentSession
  user_create: Annotated[UserCreate, Body()]  ← валидация схемы
  ▼
Обработчик create_user (ex_user_post/router_users.py)
  │  делегирует в слой приложения
  ▼
users_crud.create_user(session=session, user_create=user_create)
  │  user = User(**user_create.model_dump())
  │  session.add(user)
  │  await session.commit()      ← транзакция фиксируется ЗДЕСЬ
  │  await session.refresh(user) ← дочитывает id и server_default
  ▼
response_model=UserResp  ← ВНИМАНИЕ: наследует password, см. 04
  ▼
ORJSONResponse
```

### Чтение статьи: `GET /api/blog/articles/{art_id}` (блог)

```
Браузер (React SPA, /art/:author/:artId)
  │  fetch, credentials: 'include'
  ▼
SessionMiddleware ── расшифровка cookie → request.session {user_id, csrf_token}
  ▼
inject_current_user_middleware ── session["user_id"] → SELECT blog_user
  │                               → request.state.current_user
  ▼
router_blog_api → article_detail(art_id)
  │   get_art(art_id) ← mtime-кэш реестра articles.yaml
  │   проверки: запись есть, complete (author/lang/title), файл существует
  ▼
render_article() ── markdown(content, extensions=["fenced_code", "tables"])
  ▼
{"article": {...ArticleLang, content: "<h1>..."}} ── ORJSONResponse
  ▼
React: dangerouslySetInnerHTML + hljs.highlightAll() на клиенте
```

Контраст с доменами `users`/`orders`: здесь нет `response_model` и ORM-выгрузки —
источник данных файловый (YAML + Markdown), сериализация через `jsonable_encoder`.

### Обработка ошибок в потоке

```
Исключение в обработчике
  │
  ├── HTTPException ──────────► FastAPI: JSON {"detail": ...} + статус
  │                            (router_order_one.py: 409 CONFLICT)
  │
  ├── ValidationError (вход) ─► FastAPI: 422 + описание полей
  │
  ├── ValidationError (выход) ► 500 (response_model не сошёлся)
  │
  └── любое другое ───────────► get_async_session: except → rollback → raise
                               │
                               └─► ASGI: 500 Internal Server Error
```

`get_async_session` перехватывает **любое** исключение, откатывает транзакцию и пробрасывает дальше. Commit при этом остаётся ответственностью вызывающего кода.

---

## Управление состоянием

Приложение **stateless на уровне процесса**: всё долговременное состояние в БД и файлах. Практическое следствие — горизонтальное масштабирование ограничено только БД и общим томом файлов (`articles.yaml`, `content_art/`, `static/profile_pics/`).

Исключения из stateless-правила, о которых нужно знать:

| Объект | Область жизни | Замечание |
|---|---|---|
| `db_manager.engine` | Процесс | Пул соединений. При `workers > 1` каждый воркер создаёт свой пул: реальный лимит = `workers × (pool_size + max_overflow)` |
| `path_reader` (`cls_deps.py:48`) | Процесс | Экземпляр `PathReaderDependency`, созданный на уровне модуля. Хранит `_request`/`_foobar` в атрибутах. В роуте **не используется** (закомментирован) — вместо него создаётся новый экземпляр на каждый запрос |
| `ConfigLogger.isSetting` | Процесс | Флаг однократной инициализации логгера |
| `settings` | Процесс | Иммутабелен по факту использования; перечитывания env в рантайме нет |
| Cookie-сессия блога | Клиент | `SessionMiddleware` starlette: подписанная cookie (ключ `settings.web.secret_key`, max_age 14 дней). В сессии — `user_id` и `csrf_token`. При `workers > 1` все воркеры подписывают cookie одним ключом — сессии переживают перезапуски |
| Кэш реестра статей | Процесс | `schema_art.py`: `_registry_cache` + `_last_stat` (mtime+size `articles.yaml`). Перечитывается при изменении файла; при ошибке парсинга сохраняется последняя рабочая версия |

Кэширования HTTP-ответов в проекте нет (`functools.lru_cache`, `fastapi_cache`, Redis-клиента нет — Redis объявлен в `nginx_pg_admin.yml`, но приложение к нему не подключается). Единственный кэш — mtime-кэш реестра статей выше.

---

## Управление конфигурацией

### Механизм

`core/config.py` — `pydantic-settings` с вложенными моделями:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            BASE_DIR / "dev_sqlite.env",   # sqlite   ← активный профиль
            # BASE_DIR / "prod_db.env", # postgres ← закомментирован
            BASE_DIR / ".env",
        ),
        case_sensitive=False,
        env_prefix="APP__",
        env_nested_delimiter="__",
    )
    logging_gunicorn: LoggingConfigGunicorn = LoggingConfigGunicorn()
    gunicorn: GunicornConfig = GunicornConfig()
    run: RunConfig = RunConfig()
    api: ApiPrefix = ApiPrefix()
    db: DatabaseConfig          # ← единственное обязательное поле
```

Правило отображения env → атрибут: `APP__DB__URL` → `settings.db.url`, `APP__GUNICORN__WORKERS` → `settings.gunicorn.workers`.

Приоритет источников (стандартный для pydantic-settings, от высшего к низшему): переменные окружения процесса → `.env` → `dev_sqlite.env`. Файлы в кортеже `env_file` перечитываются слева направо, каждый следующий **переопределяет** предыдущий; `.env` стоит последним и потому имеет наивысший приоритет среди файлов.

### Дерево префиксов маршрутов

Префиксы не хардкодятся в роутерах, а берутся из `settings.api`:

| Настройка | Значение | Применяется в |
|---|---|---|
| `api.prefix` | `/api` | `api/__init__.py` → `router_api` |
| `api.v1.prefix` | `/v1` | `api/__init__.py` → `router_api_v1` |
| `api.v1.dep_examples` | `/dep_examples` | подключение `router_dep_examples` |
| `api.v1.fastapi_class_old` | `/fastapi_class_old` | `my_routes_dep/__init__.py` |
| `api.v1.fastapi_class_annotated` | `/fastapi_class_annotated` | `my_routes_dep/__init__.py` |
| `api.v1.depends_class_annotated` | `/depends_class_annotated` | `my_routes_dep/__init__.py` |
| `api.v1.depends_function_annotated` | `/depends_function_annotated` | `my_routes_dep/__init__.py` |
| `api.user_post_prefix` | `/users` | `ex_user_post/router_users.py` |
| `api.order_product_prefix` | `/orders` | `ex_order_product/router_order_one.py` |
| — (хардкод) | `/api/blog` | `md_articles/api_blog.py` → `router_blog_api` |

**Важно:** `r_users_sql` и `r_order_one` подключаются напрямую к `main_app` в `main.py`, а не через `router_api`. Их итоговые пути — `/users/...` и `/orders/...`, **без** `/api/v1`. Версионирование покрывает только демонстрационную часть. Префикс блога `/api/blog` захардкожен в `api_blog.py` — единственный роутер, не читающий `settings.api`.

### Профили окружения

| Профиль | Файл | URL БД |
|---|---|---|
| SQLite (активен) | `dev_sqlite.env` | `sqlite+aiosqlite:///./one_simple.db` |
| PostgreSQL | `prod_db.env` | `postgresql+asyncpg://user:password@localhost:5432/shop` |

Переключение выполняется **правкой исходного кода** — комментированием/раскомментированием строк в `core/config.py:91-92`. Это не конфигурируется извне, что противоречит остальному дизайну и создаёт риск при развёртывании; см. [04_code_quality.md](04_code_quality.md).

Оба `.env`-файла **закоммичены в git**: в `.gitignore` строки `#*.env` и `#.env` закомментированы. Соответственно, строка подключения с парой `user:password` находится в истории репозитория.

### Конфигурация инфраструктуры

`nginx_pg_admin.yml` читает переменные из окружения docker-compose (`${DB_USER}`, `${DB_PASSWORD}`, `${DB_NAME}`, `${PGADMIN_EMAIL}`, `${PGADMIN_PASSWORD}`) — здесь секреты вынесены наружу корректно. Требует внешней сети `app_net_new` (создаётся `make create-net` или `./adminDock.sh net-create`) и статических IP в подсети `172.20.0.0/16`, на которые ссылается `nginx.conf`.

`docker-compose.yml` (dev) наоборот содержит захардкоженные `POSTGRES_USER: user` / `POSTGRES_PASSWORD: password` и **не объявляет volume** — данные PostgreSQL теряются при пересоздании контейнера.

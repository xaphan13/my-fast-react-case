# 03. Логика и работа кода

> Часть 3 из 4. См. также: [01_project_structure.md](01_project_structure.md), [02_architecture.md](02_architecture.md), [04_code_quality.md](04_code_quality.md)

## Жизненный цикл приложения

### Фаза 1. Импорт модулей (побочные эффекты до старта сервера)

Значительная часть инициализации происходит **на этапе импорта**, а не в `lifespan`. Порядок важен: `main.py` первой строкой импортирует `base_dir_path`, затем `config_log`.

```
import main
 │
 ├─ 1. base_dir_path
 │     DIR_CWD = Path.cwd()
 │     BASE_DIR = Path(__file__).resolve().parent   → .../fastapi-application
 │
 ├─ 2. config_log                                    (config_log.py:126)
 │     ConfigLogger.setting_path_logger(log_file="one_fast.log")
 │       └─ __settings_logger()
 │           ├─ __create_log_dir("./log")   ← СОЗДАЁТ КАТАЛОГ НА ДИСКЕ
 │           ├─ create_config_dict()        → dict конфигурации
 │           ├─ logging.config.dictConfig(...)
 │           └─ isSetting = True
 │     logF  = get_logger("OnlyFile")       → только файл
 │     logFC = get_logger("FileStdout")     → файл + консоль
 │
 ├─ 3. core.config
 │     settings = Settings()                          (config.py:109)
 │       ├─ читает two.env → .env  (env_prefix="APP__")
 │       ├─ валидирует db.url как PostgresDsn | SqliteDsn
 │       └─ ПАДАЕТ с ValidationError, если APP__DB__URL не задан
 │
 ├─ 4. create_fastapi
 │     └─ импортирует db_core.db_async
 │         db_manager = AsyncDbManager(...)           (db_async.py:69)
 │           ├─ create_async_engine(pool_size=50, max_overflow=10)
 │           ├─ если SqliteDsn → @event.listens_for(engine.sync_engine, "connect")
 │           │                    set_sqlite_pragma → PRAGMA foreign_keys=ON
 │           └─ async_sessionmaker(autoflush=False, expire_on_commit=False)
 │         CurrentSession = Annotated[AsyncSession, Depends(...)]
 │
 └─ 5. Роутеры: api, ex_user_post.router_users, ex_order_product.router_order_one,
        md_articles (подключается в main.py через setup_auth_static_include)
       └─ на уровне модулей создаются APIRouter'ы и объекты-зависимости:
          path_reader     (cls_deps.py:48)
          access_required (cls_deps.py:92)
```

Движок SQLAlchemy создаётся при импорте, но **соединение с БД не устанавливается** — `create_async_engine` ленив. Реальный коннект произойдёт при первом `session.execute()`. Поэтому приложение стартует даже при недоступной БД и падает только на первом запросе к данным.

### Фаза 2. Сборка `main_app`

`main.py` на уровне модуля:

```python
main_app = create_app(custom_docs_url=False)
main_app.include_router(router_api)      # /api/v1/...
main_app.include_router(r_users_sql)     # /users/...
main_app.include_router(r_order_one)     # /orders/...
setup_auth_static_include(main_app)
#   ├─ middleware inject_current_user_middleware
#   ├─ SessionMiddleware (cookie, 14 дней)
#   ├─ mount /static (аватары)
#   ├─ handler RequestValidationError → {errors} для /api/blog
#   └─ include_router(router_blog_api)    # /api/blog/...
setup_react_routing_assets(main_app)
#   ├─ mount /assets                      # frontend/dist/assets
#   └─ catch-all /{full_path:path}        # SPA → dist/index.html
```

`create_app()` при `custom_docs_url=False` оставляет `docs_url="/docs"`, `redoc_url="/redoc"` и **не вызывает** `reg_docs_routes(app)`. Ветка с CDN unpkg остаётся неактивной.

Сборка вложенных роутеров разворачивается так:

```
main_app
├── router_blog_api                  prefix=/api/blog  (из setup_auth_static_include в main.py)
├── router_api                       prefix=/api
│   └── router_api_v1                prefix=/v1
│       ├── router_dep_examples      prefix=/dep_examples
│       │   ├── router_dep_simple    (4 роута)
│       │   └── router_dep_cls       (5 роутов)
│       └── router_param_extract     (без префикса)
│           ├── router_param_fast_cls_old  prefix=/fastapi_class_old
│           ├── router_param_fast_cls      prefix=/fastapi_class_annotated
│           ├── router_param_dep_cls       prefix=/depends_class_annotated
│           └── router_param_dep_func      prefix=/depends_function_annotated
├── r_users_sql                      prefix=/users
├── r_order_one                      prefix=/orders
├── Mount /static                    static/profile_pics (аватары)
├── Mount /assets                    frontend/dist/assets (сборка SPA)
└── Route /{full_path:path}          spa_fallback → dist/index.html
```

**Порядок критичен:** catch-all добавляется `append` в самый конец списка маршрутов и перехватывает только то, что не совпало раньше. Поэтому все `include_router` и `mount` должны быть выполнены до него — иначе он «съест» `/api/*`, `/static/*` и `/docs`.

`create_app()` при `custom_docs_url=False` оставляет `docs_url="/docs"`, `redoc_url="/redoc"` и **не вызывает** `reg_docs_routes(app)`. Ветка с CDN unpkg остаётся неактивной.

Сборка вложенных роутеров разворачивается так:

```
main_app
├── router_api                     prefix=/api
│   └── router_api_v1              prefix=/v1
│       ├── router_dep_examples    prefix=/dep_examples
│       │   ├── router_dep_simple  (4 роута)
│       │   └── router_dep_cls     (5 роутов)
│       └── router_param_extract   (без префикса)
│           ├── router_param_fast_cls_old  prefix=/fastapi_class_old
│           ├── router_param_fast_cls      prefix=/fastapi_class_annotated
│           ├── router_param_dep_cls       prefix=/depends_class_annotated
│           └── router_param_dep_func      prefix=/depends_function_annotated
├── r_users_sql                    prefix=/users
└── r_order_one                    prefix=/orders
```

### Фаза 3. Запуск сервера

**Вариант uvicorn** (`main.py`, функция `main()`):

```python
logF.info(f"Base dir path :\n{DIR_CWD=} \n{BASE_DIR=}")
uvicorn.run("main:main_app", host=settings.run.host, port=settings.run.port, reload=True)
```

Передаётся строка `"main:main_app"`, а не объект — это обязательное условие работы `reload=True`. Дефолт `0.0.0.0:8000` из `RunConfig`.

Строка `logF.warning(...)` после `uvicorn.run(...)` выполнится только после остановки сервера, так как `uvicorn.run` блокирующий.

**Вариант gunicorn** (`main_gunicorn.py`):

```python
MyGunicornApp(
    application=main_app,                      # готовый объект из main.py
    options=get_app_options(
        host=settings.gunicorn.host,           # 0.0.0.0
        port=settings.gunicorn.port,           # 8000
        timeout=settings.gunicorn.timeout,     # 900
        workers=settings.gunicorn.workers,     # 1 (из dev_sqlite.env)
        log_level=settings.logging_gunicorn.log_level,  # info
    ),
).run()
```

`BaseApplication.run()` вызывает `load_config()` → `config_options` (фильтрует опции по `k in self.cfg.settings and v is not None`) → `load()` возвращает `main_app`. Мастер-процесс форкает воркеров класса `uvicorn.workers.UvicornWorker`.

**Критично при `workers > 1`:** импорт `main` происходит в мастер-процессе **до** форка, значит `db_manager.engine` создаётся один раз и наследуется воркерами через `fork()`. Пулы соединений asyncpg не переживают fork корректно. Настройки `settings.run` (uvicorn) и `settings.gunicorn` при этом независимы — совпадение портов случайно.

### Фаза 4. Startup через lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    logF.info(f"startup lifespan :\n{settings.db.url=} \n{app.title=}")
    if isinstance(settings.db.url, SqliteDsn):
        logF.warning(f"used test sqlite dataBase : {settings.db.url=}")
    yield
    await db_manager.engine_dispose()
```

Startup выполняет только логирование. Проверки соединения с БД, прогрева пула, создания таблиц здесь нет. Предупреждение о SQLite — защита от случайного запуска на тестовой БД.

**Замечание:** `settings.db.url` попадает в лог целиком, включая пароль в случае PostgreSQL-профиля.

### Фаза 5. Обработка запросов

Установившийся режим. Детальный разбор — в разделе «Ключевые процессы».

### Фаза 6. Shutdown

После `yield` вызывается `await db_manager.engine_dispose()` → `engine.dispose()`: закрывает все соединения в пуле. Это единственный шаг завершения — таймаутов на дренаж активных запросов, флашей логов или закрытия внешних клиентов нет.

При `reload=True` uvicorn перезапускает процесс на каждое изменение файла, каждый раз проходя весь цикл импортов заново.

---

## Ключевые процессы

### Процесс 1. Инъекция сессии БД

Единственная зависимость, общая для всех обработчиков, работающих с данными.

```python
async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
    async with self.session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
```

Пошагово:

1. FastAPI встречает `db: CurrentSession` в сигнатуре и вызывает `db_manager.get_async_session()`.
2. `async with self.session_factory()` создаёт `AsyncSession`. Соединение из пула **пока не берётся** — SQLAlchemy берёт его лениво, при первом запросе.
3. `yield session` отдаёт сессию обработчику; генератор замирает.
4. Обработчик работает; ответственность за `commit()` лежит на нём.
5. После формирования ответа FastAPI возобновляет генератор.
6. При исключении — `rollback()` и проброс исключения дальше.
7. Выход из `async with` закрывает сессию и возвращает соединение в пул.

Контракт: **зависимость откатывает, но не коммитит**. Забытый `commit()` в обработчике означает молча потерянные изменения.

### Процесс 2. `POST /orders/add_order` — ORM-путь записи

```python
@r_order_one.post("/add_order", response_model=OrderResp)
async def add_order(body: OrderCreateBody, db: CurrentSession):
    new_order: Order = Order(**body.model_dump())
    db.add(new_order)
    await db.commit()
    await db.refresh(new_order)
    return new_order
```

1. `OrderCreateBody` валидирует тело: единственное поле `promocode: Optional[str] = None`.
2. `Order(**{"promocode": ...})` — объект в состоянии *transient*.
3. `db.add()` переводит в *pending*.
4. `db.commit()` — INSERT и фиксация транзакции.
5. `db.refresh(new_order)` — обязательный шаг: `expire_on_commit=False` означает, что после коммита атрибуты не инвалидируются, но `id` и `created_at` (`server_default=func.now()`) сгенерированы базой и в объекте отсутствуют.
6. `response_model=OrderResp` с `from_attributes=True` сериализует ORM-объект.

**Дефект:** `OrderResp.promocode` объявлен как `str` без `| None`, а колонка допускает NULL (`Mapped[str_len_50 | None]`). Запрос без `promocode` создаст запись и упадёт на сериализации ответа с 500.

### Процесс 3. `POST /orders/insert_order` — Core-путь записи

```python
stmt: Insert[Order] = insert(Order).values(**body.model_dump())
await db.execute(stmt)
await db.commit()
return body
```

Контраст с процессом 2: SQLAlchemy Core вместо ORM. INSERT без загрузки объекта в identity map, без `refresh`. Возвращается исходное тело запроса, а не созданная запись, поэтому `response_model=OrderCreateBody`, а не `OrderResp`, и `id` клиенту не сообщается.

### Процесс 4. `GET /orders/get_order_filter_by` vs `/get_order_where`

Два обработчика демонстрируют `filter_by` против `where`.

`filter_by` — словарь `колонка=значение`, `None`-поля отбрасываются вручную:

```python
filter_where = {k: v for k, v in params.model_dump().items() if v is not None}
stmt = select(Order).filter_by(**filter_where)
result = await db.execute(stmt)
order: Order = result.scalar()
if not order:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=...)
```

`where` — список выражений сравнения через `getattr`, отсев `None` через `exclude_none=True`:

```python
filter_where = [getattr(Order, k) == v for k, v in params.model_dump(exclude_none=True).items()]
stmt = select(Order).where(*filter_where)
orders: Sequence[Order] = result.scalars().all()
```

Разница в результате: первый возвращает **одну** запись (`result.scalar()`), второй — **список** (`response_model=OrderResp | list[OrderResp]`).

Оба используют `409 CONFLICT` для «не найдено». Семантически корректен `404 NOT FOUND`.

Пустой набор параметров в `/get_order_filter_by` даёт `select(Order)` без условий; `result.scalar()` при более чем одной строке в таблице поднимет `MultipleResultsFound`.

### Процесс 5. `GET /orders/get_all_orders` — динамическая сортировка

```python
if params == "time":
    order_by_list_o = [Order.created_at, Order.id]
elif params == "promocode":
    order_by_list_o = [Order.promocode, Order.created_at]
else:
    order_by_list_o = [Order.id, Order.created_at]

stmt = select(Order).order_by(*order_by_list_o)
```

`params: OrderGetAllOrderbyQuery` — обязательный query-параметр типа `str, Enum` со значениями `id` / `time` / `promocode`. FastAPI отрендерит его как выпадающий список в Swagger и вернёт 422 на неизвестное значение.

Сравнение `params == "time"` работает, потому что класс наследует `str`. Явнее было бы `params is OrderGetAllOrderbyQuery.time`.

Whitelist-подход к сортировке (фиксированный набор веток вместо `getattr(Order, params)`) исключает SQL-инъекцию через имя колонки — это правильное решение.

### Процесс 6. `GET /orders/get_all_join` — загрузка связей

```python
stmt = select(Order).order_by(Order.id).options(joinedload(Order.products))
await_result_execute = await db.execute(stmt)

if variant == 1:
    result_scalars_all = await_result_execute.unique().scalars().all()
    order0, order1 = result_scalars_all[0], result_scalars_all[1]
else:
    result_all = await_result_execute.unique().all()
    order0 = result_all[0][0]
    order1 = result_all[1][0]
```

Смысл параметра `variant` — показать два способа разобрать один и тот же `Result`: через `.scalars()` (сразу ORM-объекты) и через `.all()` с распаковкой `Row`.

`.unique()` **обязателен**: `joinedload` на коллекции порождает декартово произведение строк (один заказ × N товаров), и без дедупликации SQLAlchemy поднимет `InvalidRequestError`.

**Дефект:** индексы `[0]` и `[1]` жёстко зашиты и используются только для логирования. При менее чем двух заказах в БД — `IndexError` → 500. Диагностический код, оставшийся в продакшн-пути.

### Процесс 7. `GET /users/get_all_users` и `POST /users/create_user`

Единственный домен со слоем приложения. Обработчик не строит SQL:

```python
@r_users_sql.get("/get_all_users", response_model=list[UserResp])
async def get_users(session: CurrentSession):
    users = await users_crud.get_all_users(session=session)
    return users
```

`crud_users.get_all_users` использует укороченную форму `session.scalars(stmt)` вместо `execute` + `.scalars()`.

`create_user` в CRUD-слое сам вызывает `commit()` и `refresh()` — та же последовательность, что в процессе 2, но инкапсулированная.

**Дефект безопасности:** `UserResp(UserCreate)` наследует поле `password`, поэтому оба эндпоинта возвращают пароль клиенту в открытом виде. Подробно — в [04_code_quality.md](04_code_quality.md).

### Процесс 8. Четыре стиля извлечения параметров

Все четыре обработчика `/my_items/{item_id}` выполняют одинаковую последовательность:

1. Получить `item_id` (Path, `ge=1`), `param_id` (Query), `user-id` (Header), `number-req` (Cookie).
2. Записать значения в лог через `logF.info`.
3. Модифицировать `Response`: заголовок `X-Custom-Header`, куки `visited=true` и `number-req = cookie_number_req + 1`.
4. Вернуть dict из пяти полей, включая `request.client.port`.

Различие — только в способе объявления параметров:

| Файл | Стиль | Response model |
|---|---|---|
| `my_param_fast_cls.py` | `path_item_id: int = Path(alias="item_id", ge=1)` | `RespFieldStyle` |
| `my_param_fast_ann.py` | `path_item_id: Annotated[int, Path(alias="item_id", ge=1)]` | `RespAnnotated` |
| `my_param_dep_cls.py` | `path_cls: Annotated[PathData, Depends()]` | `RespAfterValid` |
| `my_param_dep_func.py` | `path_item_id: Annotated[int, Depends(get_item_id)]` | `RespDecorValid` |

Классы `PathData`/`QueryData`/`HeaderData`/`CookieData` (`dep_cls_schema.py`) — обычные классы, не pydantic-модели; FastAPI читает аннотации их `__init__` и сохраняет значения в атрибуты вида `self.path_item_id`.

Параметры `request: Request = ...` и `response: Response = ...` объявлены с `Ellipsis` в качестве значения по умолчанию во всех четырёх файлах — избыточная конструкция, FastAPI распознаёт эти типы по аннотации.

### Процесс 9. Проверка токена

```python
class HeaderAccessDependency:
    def __init__(self, secret_token: str) -> None:
        self.secret_token = secret_token

    def validate(self, token: str) -> TokenIntrospectResult:
        if token != self.secret_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token is invalid")
        return TokenIntrospectResult(result=TokenData(id=42, username="john_smith"))

    def __call__(self, token: Annotated[str, Header(alias="x-access-token")]) -> TokenIntrospectResult:
        return self.validate(token=token)
```

`Depends(HeaderAccessDependency(secret_token="qwerty-abc"))` — экземпляр создаётся один раз при импорте `dep_examp_cls.py`, `__call__` выполняется на каждый запрос.

Строгое сравнение `!=` уязвимо к timing-атаке; корректная замена — `secrets.compare_digest`. Токен захардкожен в двух местах: `"qwerty-abc"` в декораторе роута и `"foo-bar-fizz-buzz"` в `access_required` (`cls_deps.py:92`, не используется). Это демонстрационный код, но при копировании в реальный проект дефект переносится.

### Процесс 10. Зависимость-генератор с teardown

```python
def as_dependency(self, request: Request,
                  foobar: Annotated[str, Header(alias="x-foobar")] = "foo",
                  ) -> Generator[Self, None, None]:
    self._request = request
    self._foobar = foobar
    yield self
    self._request = None
```

Единственное место в проекте, где показан teardown зависимости. `_request` обнуляется после запроса, `_foobar` — нет (строка закомментирована), то есть значение переживает запрос.

В роуте `Depends(PathReaderDependency(source="direct/bar").as_dependency)` создаёт **новый** экземпляр на каждый вызов декоратора, поэтому шаринга состояния между запросами не возникает. Но закомментированная альтернатива `Depends(path_reader.as_dependency)` использовала бы модульный синглтон (`cls_deps.py:48`) — и тогда конкурентные запросы перезаписывали бы `_request` друг друга. Это скрытая гонка, оставленная в коде как закомментированный вариант.

---

## Роутинг и middleware

### Разрешение маршрута

FastAPI обходит `main_app.routes` в порядке регистрации и берёт **первое** совпадение по пути и методу. Порядок задан последовательностью в `main.py`: `router_api` → `r_users_sql` → `r_order_one` → `router_blog_api` (из `include_router_api_frontend`) → mount `/static` → mount `/assets` → catch-all. Конфликтов путей нет — префиксы `/api/v1`, `/users`, `/orders`, `/api/blog`, `/static`, `/assets` не пересекаются; catch-all замыкает список и отдаёт SPA `index.html` всем остальным GET-путям.

Четыре обработчика с идентичным путём `/my_items/{item_id}` разведены префиксами на уровне `my_routes_dep/__init__.py`, поэтому коллизии не возникает. В графе кода они схлопнулись в один узел `Route`, но в рантайме это четыре разных маршрута.

### Полная карта эндпоинтов

| Метод | Путь | Обработчик |
|---|---|---|
| GET | `/api/blog/csrf` | `csrf_token` |
| GET | `/api/blog/current_user` | `current_user` |
| POST | `/api/blog/register` | `register_api` |
| POST | `/api/blog/login` | `login_api` |
| POST | `/api/blog/logout` | `logout_api` |
| GET | `/api/blog/account` | `account_get_api` |
| POST | `/api/blog/account` | `account_post_api` |
| GET | `/api/blog/articles` | `articles_list` (query `?section=` — фильтр по разделу) |
| GET | `/api/blog/articles/{art_id}` | `article_detail` |
| GET | `/api/blog/sections` | `sections_list` |
| GET | `/api/blog/art_manage` | `art_manage_api` |
| POST | `/api/blog/art_manage/add_all` | `art_manage_add_all_api` |
| POST | `/api/blog/art_manage/meta` | `art_manage_meta_api` |
| GET | `/api/v1/dep_examples/single-direct-dependency` | `single_direct_dependency` |
| GET | `/api/v1/dep_examples/single-via-func` | `single_via_func` |
| GET | `/api/v1/dep_examples/multi-direct-and-via-func` | `multi_direct_and_via_func` |
| GET | `/api/v1/dep_examples/multi-indirect` | `multi_indirect_dependencies` |
| GET | `/api/v1/dep_examples/top-level-helper-creation` | `top_level_helper_creation` |
| GET | `/api/v1/dep_examples/helper-as-dependency` | `helper_as_dependency` |
| GET | `/api/v1/dep_examples/great-service-as-dependency` | `get_great_service_dependency` |
| GET | `/api/v1/dep_examples/path-reader-dependency-from-method` | `path_reader_dependency` |
| GET | `/api/v1/dep_examples/direct-cls-dependency` | `direct_cls_dependency` |
| GET | `/api/v1/fastapi_class_old/my_items/{item_id}` | `fastapi_class_old` |
| GET | `/api/v1/fastapi_class_annotated/my_items/{item_id}` | `fastapi_class_annotated` |
| GET | `/api/v1/depends_class_annotated/my_items/{item_id}` | `depends_class_annotated` |
| GET | `/api/v1/depends_function_annotated/my_items/{item_id}` | `depends_function_annotated` |
| GET | `/users/get_all_users` | `get_users` |
| POST | `/users/create_user` | `create_user` |
| POST | `/orders/add_order` | `add_order` |
| POST | `/orders/insert_order` | `insert_order` |
| GET | `/orders/get_order_filter_by` | `get_order_filter_by` |
| GET | `/orders/get_order_where` | `get_order_where` |
| GET | `/orders/get_all_orders` | `get_all_orders` |
| GET | `/orders/get_all_join` | `get_all_join` |
| GET | `/docs`, `/redoc` | встроенные FastAPI |
| GET | `/static/*`, `/assets/*` | StaticFiles (аватары; сборка SPA) |
| GET | `/{full_path:path}` | `spa_fallback` — `frontend/dist/index.html`; `/api*` → 404 JSON |

Пути в стиле `/get_all_users`, `/add_order` содержат глагол в URL — отклонение от REST-конвенций, где действие выражается HTTP-методом.

### Middleware

**Пользовательских middleware два**, оба подключает `include_router_api_frontend` в `main.py`:

1. **`SessionMiddleware`** (starlette, `add_middleware`) — подписанные cookie-сессии: ключ `settings.web.secret_key`, `max_age = 14 дней`. В сессии живут `user_id` и `csrf_token`.
2. **`inject_current_user_middleware`** (`app.middleware("http")`) — на каждый HTTP-запрос открывает сессию БД через `db_manager.session_factory()`, по `session["user_id"]` делает `SELECT blog_user` и кладёт результат (или `None`) в `request.state.current_user`. Все обработчики блога читают пользователя из `request.state`, а не из зависимости.

Порядок: `add_middleware` вставляет middleware в начало стека, поэтому `SessionMiddleware` (добавлен вторым) — внешний: сессия уже расшифрована к моменту работы `inject_current_user_middleware`.

Цена универсальности: сессия БД открывается **на каждый** запрос, включая `/docs`, статику, `/assets` и SPA catch-all, где пользователь не нужен.

Чего по-прежнему нет:

- **CORS не настроен** — браузерные запросы с другого origin будут заблокированы (для SPA это не мешает: фронтенд ходит с того же origin либо через vite-прокси в dev);
- **GZip не подключён** — ответы не сжимаются;
- **`TrustedHostMiddleware` отсутствует** — защиты от Host header injection нет;
- **`ProxyHeadersMiddleware` не активирован явно** — за nginx `request.client` вернёт IP прокси, а не клиента, несмотря на то что `nginx.conf` передаёт `X-Forwarded-For`.

Последний пункт напрямую влияет на четыре обработчика `/my_items/{item_id}`: они возвращают `request.client.port`, и за прокси это будет порт nginx.

Единственная кросс-запросная логика доменов `users`/`orders` по-прежнему реализована не через middleware, а через зависимость `get_async_session`.

---

## Обработка ошибок

### Уровни

| Уровень | Механизм | Результат |
|---|---|---|
| Валидация входа | pydantic через FastAPI | 422 с детализацией по полям |
| Валидация входа `/api/blog` | кастомный хендлер `RequestValidationError` | 422 в формате `{"errors": {поле: [тексты]}}` |
| Явные ошибки бизнес-логики | `raise HTTPException` | Код из аргумента + `{"detail": ...}` |
| Ошибки форм блога | `_validation_response()` | 422 `{"errors": ...}` (уникальность, совпадение паролей) |
| Ошибки БД | `try/except` в `get_async_session` | `rollback()` + проброс → 500 |
| Валидация выхода | `response_model` | 500 при несоответствии |
| Всё остальное | Starlette `ServerErrorMiddleware` | 500 без тела |

### Использование HTTPException

Явных `raise HTTPException` в проекте больше двух десятков; основные источники:

- `router_order_one.py` — `409 CONFLICT` («не найдено» в `get_order_filter_by`/`get_order_where`);
- `cls_deps.py` — `401 UNAUTHORIZED` (демо-токен);
- `api_blog.py` — `403` (CSRF mismatch, `require_login_api`), `400` (уже авторизован), `401` (неверный логин/пароль), `404` (статья не найдена).

**Кастомный обработчик исключений один**: `custom_request_validation_exception_handler` (регистрируется в `include_router_api_frontend` при подключении блога в `main.py`) переписывает ответы `RequestValidationError` в формат `{"errors": {...}}`, но **только** для путей `/api/blog*` — остальные пути получают стандартный формат FastAPI. Формат нужен фронтенду: он раскладывает ошибки по полям формы.

При этом `IntegrityError` по-прежнему не обрабатывается: нарушение `UniqueConstraint` (например, дублирующийся `nickname` в `POST /users/create_user`) даёт **500** вместо 409. В блоге этой проблемы нет — уникальность username/email проверяется явными `SELECT`-запросами до вставки.

### Дефекты в валидаторах

`pydantic_validator.py`, `RespDecorValid.validate_query_safe`:

```python
@field_validator("query")
@classmethod
def validate_query_safe(cls, v: int | None) -> int | None:
    if 1 <= v <= 1000:
        return v
    raise ValueError("либо None, либо число от 1 до 1000")
```

Поле объявлено как `int | None = None`, но `None` не обрабатывается: `1 <= None` поднимет `TypeError`. Эндпоинт `/api/v1/depends_function_annotated/my_items/{item_id}` вернёт 500 при любом запросе без `param_id`. Сравните с корректной реализацией того же ограничения в `RespAfterValid`, где используется `Field(ge=1, le=1000)` на `Annotated`-типе.

`validate_path_is_even` проверяет `v < 0`, хотя сообщение об ошибке говорит «должен быть больше 0» — граничное значение `0` пройдёт проверку. Имя метода при этом упоминает чётность, которая нигде не проверяется.

`RespAfterValid` и `RespDecorValid` валидируют `request` (порт клиента) диапазоном 1024–65535. Клиент с исходящим портом из privileged-диапазона получит 500 на валидации **ответа**.

---

## Логирование

### Конфигурация

`config_log.py` строит `dictConfig` с шестью форматтерами (`form1`–`form4`, `con1`, `con2`), двумя хендлерами и тремя логгерами:

| Логгер | Хендлеры | Назначение |
|---|---|---|
| `OnlyFile` | `rotating_file1` | Только файл. Экспортируется как `logF` |
| `FileStdout` | `rotating_file1`, `console1` | Файл + консоль. Экспортируется как `logFC` |
| `Stdout` | `console1` | Только консоль. Не экспортируется |

`rotating_file1` — `RotatingFileHandler`, `maxBytes=1048576` (1 МБ), `backupCount=20`, файл `{BASE_DIR}/log/one_fast.log`. Уровень хендлера `INFO`, уровень логгеров `DEBUG` — фактический порог определяет хендлер, то есть DEBUG-сообщения не пишутся.

### Что логируется

Практически весь прикладной логгинг — диагностический вывод значений переменных через f-строки с `=`:

```python
logF.info(f"fastapi_class_old :\n{path_item_id=} \n{query_param_id=}")
logF.info(f"get_all_join : \n{order0=}\n{prods0=}")
```

События уровня приложения: старт `lifespan`, предупреждение о SQLite, путь `BASE_DIR` при запуске `main()`.

### Проблемы

1. **Логи uvicorn не перехватываются.** Блок с логгерами `uvicorn`, `uvicorn.error`, `uvicorn.access` закомментирован (`config_log.py`, строки внутри `create_config_dict`). Access-логи и трейсбеки идут в stdout мимо файла, то есть в `one_fast.log` нет записей об ошибках HTTP.

2. **`disable_existing_loggers: False`** в сочетании с `APP__DB__ECHO=1` в обоих `.env` означает, что SQLAlchemy пишет **каждый SQL-запрос** в stdout. В продакшн-конфигурации это неприемлемо по объёму и по риску утечки данных.

3. **Утечка чувствительных данных.** `lifespan` логирует `settings.db.url` целиком — с паролем для PostgreSQL-профиля. Обработчик `get_all_join` логирует ORM-объекты через `repr`.

4. **`logging.basicConfig(level=logging.INFO, handlers=[])`** вызывается после `dictConfig` — избыточно и потенциально конфликтует с уже настроенной конфигурацией.

5. **Побочный эффект при импорте.** `__create_log_dir` вызывает `os.mkdir` во время импорта модуля. `os.mkdir` (в отличие от `os.makedirs`) не создаёт промежуточные каталоги, а проверка `os.path.exists` перед созданием — классический TOCTOU-паттерн; при параллельном старте нескольких воркеров возможен `FileExistsError`.

6. **Ротация при нескольких процессах.** `RotatingFileHandler` не синхронизирован между процессами. При `gunicorn --workers > 1` воркеры будут конкурировать за один файл, что приводит к потере записей при ротации.

# 02. Скелет бэкенда на FastAPI

> Цикл «FastAPI + React». Предыдущая: [01. Архитектура](01-architecture-overview.md) · Следующая: [03. Слой данных](03-database-layer.md)

## Что входит в скелет

Минимальный рабочий каркас современного FastAPI-проекта — пять элементов:

1. **Фабрика приложения** `create_app()` — единственное место, где создаётся
   объект `FastAPI`. Все настройки (lifespan, response_class, middleware)
   собираются здесь.
2. **Lifespan** — старт/стоп приложения: что открыть (пул БД, лог-файл),
   что закрыть (dispose движка).
3. **Конфигурация** — pydantic-settings, всё через env-файлы, никаких
   `os.environ` по коду.
4. **Роутеры** — по доменам, префиксы из конфига. В этом проекте их три:
   `/api/v1` (демо-часть), `/users`, `/orders`.
5. **DI-зависимости** — сессии, авторизация, общие параметры через `Depends`.

Разберём каждый по реальному коду проекта — с file:line, чтобы можно было
открыть файл и проверить.

## 1. Фабрика приложения + lifespan

Файл `fastapi-application/create_fastapi.py` (реальный код):

```python
async def lifespan(app: FastAPI):
    # startup
    logF.info(f"startup lifespan :\n{settings.db.url=} \n{app.title=}")
    if isinstance(settings.db.url, SqliteDsn):
        logF.warning(f"used test sqlite dataBase : {settings.db.url=}")
    yield
    # shutdown
    await db_manager.engine_dispose()          # закрываем пул соединений


def create_app(custom_docs_url: bool = False) -> FastAPI:
    docs_url, redoc_url = (None, None) if custom_docs_url else ("/docs", "/redoc")
    app = FastAPI(
        title="Example : Fast API - SQL - React",
        default_response_class=ORJSONResponse,   # orjson вместо stdlib json: быстрее
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
    )
    return app
```

**Почему фабрика, а не глобальный `app = FastAPI()`?**

- **Тесты.** Можно собрать приложение с подменой зависимостей
  (`app.dependency_overrides[get_async_session] = fake_session`).
- **Конфигурация в одном месте.** middleware, документация, lifespan — не
  размазаны по импортам.
- **Несколько приложений** из одной кодовой базы (например, API + админка)
  без копипасты.

**Почему `lifespan`, а не `@app.on_event("startup")`/`("shutdown")`?**
Один контекст-менеджер гарантирует, что `engine_dispose()` выполнится даже
если между `startup` и `yield` что-то упало. Старые `@app.on_event` объявлены
устаревшими в FastAPI 0.111+.

**Почему `default_response_class=ORJSONResponse`?** `orjson` сериализует
datetime/UUID быстрее стандартного `json` и без `default=str`-костылей.
Бесплатная скорость.

## 2. Конфигурация: pydantic-settings с префиксами

Файл `fastapi-application/core/config.py` (реальный код, упрощён):

```python
class RunConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000

class WebConfig(BaseModel):
    secret_key: str = "dev-insecure-secret-key-change-me"

class ApiV1Prefix(BaseModel):
    prefix: str = "/v1"
    dep_examples: str = "/dep_examples"
    fastapi_class_old: str = "/fastapi_class_old"
    fastapi_class_annotated: str = "/fastapi_class_annotated"
    depends_class_annotated: str = "/depends_class_annotated"
    depends_function_annotated: str = "/depends_function_annotated"

class ApiPrefix(BaseModel):
    prefix: str = "/api"
    v1: ApiV1Prefix
    user_post_prefix: str = "/users"
    order_product_prefix: str = "/orders"

class DatabaseConfig(BaseModel):
    url: str                     # обязательное поле — без него приложение падает
    echo: bool = False
    echo_pool: bool = False
    pool_size: int = 50
    max_overflow: int = 10
    naming_convention: dict = { ... }

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            BASE_DIR / "dev_sqlite.env",   # sqlite — активный профиль
            # BASE_DIR / "prod_db.env",  # postgres — закомментирован
            BASE_DIR / ".env",             # перекрывает оба
        ),
        case_sensitive=False,
        env_prefix="APP__",
        env_nested_delimiter="__",
    )
    run: RunConfig = RunConfig()
    api: ApiPrefix
    web: WebConfig = WebConfig()
    db: DatabaseConfig            # обязательное — нет `url` → приложение не стартует

settings = Settings()             # singleton — единая точка истины
```

Отображение переменных: `APP__DB__URL` → `settings.db.url`,
`APP__RUN__PORT` → `settings.run.port`,
`APP__WEB__SECRET_KEY` → `settings.web.secret_key`.

**Почему так, а не `os.environ["DB_URL"]` по коду:**

- **Валидация конфига при старте.** Нет обязательной переменной — приложение
  падает сразу и с понятной ошибкой, а не в середине запроса.
- **Вложенные модели = самодокументируемое дерево настроек.** Никаких
  «где там `MAX_OVERFLOW` живёт».
- **Один объект `settings`** — синглтон на уровне модуля. Никаких
  «я забыл импортировать `get_settings()`».

**Префиксы маршрутов тоже из конфига** — роутеры не хардкодят пути:

```python
r_users_sql = APIRouter(
    prefix=settings.api.user_post_prefix,    # "/users"
    tags=["Sql example users"],
)
```

Это значит: переименовать `/users` в `/api/v2/users` — правка **одного**
места в конфиге, без обхода всех роутеров.

**Переключение профиля БД** — правка списка `env_file` в `Settings`
(раскомментировать `prod_db.env`). env-переменная для этого **не** используется.

## 3. Сборка приложения и SPA-слой

Файл `fastapi-application/main.py` — точка входа. Обратите внимание на
порядок: роутеры → блог → mount статики → catch-all **последним**:

```python
main_app = create_app(custom_docs_url=False)

# 1) Доменные роутеры
main_app.include_router(router_api)        # /api/v1/...  (демо-часть)
main_app.include_router(r_users_sql)       # /users/...
main_app.include_router(r_order_one)       # /orders/...

# 2) Блог: auth-middleware + /static + два JSON-роутера /api/blog
include_router_api_frontend(main_app)

# 3) SPA: mount /assets + catch-all. СТРОГО последним.
mount_vite_react_assets(main_app)
```

`include_router_api_frontend` и `mount_vite_react_assets` — **обе** живут в
`fastapi-application/md_articles/setup_frontend.py`. Главная мысль: блог
ничего не знает про фронт, фронт ничего не знает про блог. Это разделение
«по слоям» в одной точке подключения.

**Что делает `include_router_api_frontend`** (`setup_frontend.py:16`):

1. `add_middleware_auth(app)` — middleware сессий, `current_user`,
   кастомный handler 422 (вся авторизация собрана в `middleware_auth.py`).
2. `app.mount("/static", StaticFiles(...))` — аватары из
   `BASE_DIR/static/profile_pics/`.
3. `app.include_router(router_auth_api)` — auth-эндпоинты (`/api/blog/csrf`,
   `/current_user`, `/register`, `/login`, `/logout`, `/account`).
4. `app.include_router(router_blog_api)` — блог-эндпоинты (`/api/blog/sections`,
   `/articles`, `/articles/{art_id}`, `/art_manage`, `add_all`, `meta`, `sync`).

**Что делает `mount_vite_react_assets`** (`setup_frontend.py:79`):

```python
def mount_vite_react_assets(app: FastAPI) -> None:
    app.mount(
        "/assets",
        StaticFiles(directory=ASSETS_DIR, check_dir=False),
        name="spa_assets",
    )
    app.router.routes.append(Route("/{full_path:path}", spa_fallback, methods=["GET"]))
```

1. `app.mount("/assets", StaticFiles(frontend/dist/assets, check_dir=False))`
   — хэшированные Vite-бандлы. `check_dir=False` позволяет стартовать даже
   без собранного фронта (бэкенд-разработка не зависит от `npm run build`).
2. `app.router.routes.append(...)` — catch-all дописан **руками** в конец
   `router.routes`, чтобы не перехватить ни один API-роут. Если бы
   добавляли через `include_router` — он попал бы в начало списка и
   «съел» бы все API-запросы.
3. `spa_fallback` (`setup_frontend.py:49`): GET → `index.html` для
   history-mode React Router; `/api*` → `JSONResponse(404)`, чтобы клиент не
   получал HTML вместо JSON; отсутствие `dist/index.html` → 404 с подсказкой
   `npm run build`.

**Зачем catch-all?** React Router роутит на клиенте (`/art/Max/7`). Если
пользователь открыл такой URL напрямую (закладка, F5), сервер должен вернуть
`index.html` — иначе 404. А `/api/*` перехватывается раньше и честно отвечает
404 JSON. Подробно — в [статье 06](06-integration-deploy.md).

## 4. DI — главный паттерн FastAPI

Идея: обработчик **объявляет, что ему нужно**, а FastAPI сам это построит
на каждый запрос. Три типовых формы.

### а) Ресурс — сессия БД (самый частый)

`fastapi-application/db_core/db_async.py:78` (реальный код):

```python
CurrentSession = Annotated[AsyncSession, Depends(db_manager.get_async_session)]
```

Обработчик — одна строка вместо ручного управления сессией
(`fastapi-application/ex_user_post/router_users.py`):

```python
@r_users_sql.get("/get_all_users", response_model=list[UserResp])
async def get_users(session: CurrentSession):
    return await users_crud.get_all_users(session=session)
```

Генератор-зависимость даёт точку teardown: сессия открывается до обработчика
и закрывается после ответа, при исключении — rollback. Полный разбор —
[статья 03](03-database-layer.md).

### б) Фабрика зависимостей (замыкание)

Когда параметр зависимости нужен на этапе *описания*, а не запроса. Из
`fastapi-application/api/dependencies/` (демо-часть проекта):

```python
def get_header_dependency(header_name: str, default_value: str = ""):
    def dependency(header: Annotated[str, Header(alias=header_name)] = default_value) -> str:
        return header
    return dependency

# использование: своя зависимость под каждый заголовок
Depends(get_header_dependency("X-Request-Source", default_value="web"))
```

### в) Класс как зависимость

```python
class GreatService:
    def __init__(self, token: Annotated[str, Header()]):   # параметры приходят из запроса
        self.token = token

@app.get("/svc")
async def svc(service: Annotated[GreatService, Depends(GreatService)]):
    ...
```

**Почему DI, а не «вызывать функции внутри обработчика»:**

- **Переиспользование.** Одна зависимость `CurrentSession` — сотни обработчиков.
- **Тестируемость.** `app.dependency_overrides[get_async_session] = fake_session`
  — тест работает без БД.
- **Граф зависимостей FastAPI кэширует в рамках одного запроса.** Если два
  обработчика просят одну зависимость — она выполнится один раз.

## 5. Чего избегать (грабли этого проекта)

| Грабля | Последствие | Как правильно |
|---|---|---|
| Побочные эффекты на импорте (`db_manager` создаёт engine при импорте) | Импорт `main` требует валидного конфига; подмена в тестах — только через `dependency_overrides` | Создавать тяжёлые ресурсы в lifespan или лениво |
| Хардкод путей в роутерах | При переезде `/api/v1` править десятки файлов | Префиксы из `settings.api` |
| Логика в обработчиках напрямую | SQL в роутах не переиспользовать и не тестировать | Тонкий обработчик → CRUD/сервисный слой ([статья 03](03-database-layer.md)) |
| Catch-all через `include_router` | Попадает в начало `router.routes`, перехватывает API | `app.router.routes.append(Route(...))` — только так |

## 6. Чекпоинт самопроверки

- [ ] `create_app()` — единственное место создания `FastAPI`.
- [ ] `lifespan` закрывает все открытые ресурсы (`engine_dispose`).
- [ ] Ни одного `os.environ` вне `core/config.py`.
- [ ] Все префиксы роутеров — из конфига.
- [ ] Обработчики тонкие: валидация + вызов сервиса, без SQL и бизнес-логики.
- [ ] Catch-all добавлен через `app.router.routes.append`, не через `include_router`.
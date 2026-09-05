# 02. Каркас бэкенда на FastAPI: фабрика, lifespan, конфигурация, DI

> Цикл «FastAPI + React». Предыдущая: [01. Две половины](01-architecture-overview.md) · Следующая: [03. Слой данных](03-database-layer.md)

## 1. Из чего состоит скелет

Минимальный рабочий каркас современного FastAPI-проекта — пять элементов:

1. **Фабрика приложения** `create_app()` — единственное место, где создаётся `FastAPI(...)`.
2. **Lifespan** — точка startup/shutdown: что открыть и что закрыть (пул БД и т.п.).
3. **Конфигурация** — pydantic-settings, всё через env-файлы, никаких `os.environ` по коду.
4. **Роутеры** — по доменам, префиксы из конфига.
5. **DI-зависимости** — сессии, авторизация, общие параметры через `Depends`.

Разберём каждый на реальном коде проекта.

## 2. Фабрика приложения + lifespan

`fastapi-application/create_fastapi.py` (реальный код):

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from core.config import settings, SqliteDsn
from db_core.db_async import db_manager

@asynccontextmanager
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
        title="Example Request Parameters Extraction",
        default_response_class=ORJSONResponse,   # orjson вместо stdlib json: быстрее
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
    )
    return app
```

**Почему фабрика, а не глобальный `app = FastAPI()`?**

- Тесты могут собрать приложение с нужным набором роутеров (`create_app()` —
  чистая функция, побочных эффектов минимум).
- Конфигурация (документация, middleware) собирается в одном месте, а не
  размазана по импортам.
- Несколько приложений из одной кодовой базы (API + админка) без копипасты.

**Почему `lifespan`, а не события `startup`/`shutdown`?** Один контекст-менеджер
гарантирует, что `engine_dispose()` выполнится даже если между startup и yield
что-то упало — это современный рекомендуемый способ (старые `@app.on_event`
объявлены устаревшими).

**Блог (`md_articles`) подключается из `main.py`, не из фабрики.**
`setup_auth_static_include(main_app)` вызывается после доменных `include_router`
и до mount-статики/catch-all — он добавляет `SessionMiddleware`,
`inject_current_user_middleware`, mount `/static` (аватары), exception-handler
для 422 и `router_blog_api`. Фабрика про блог ничего не знает: это позволяет
тестам собирать приложение без блога или с минимальным набором middleware.

## 3. Сборка приложения и SPA-слой

`main.py` — точка входа. Обратите внимание на порядок: роутеры → блог → mount
статики → catch-all **последним** (реальный код, упрощён):

```python
main_app = create_app(custom_docs_url=False)

main_app.include_router(router_api)        # /api/v1/...  (демо-часть)
main_app.include_router(r_users_sql)       # /users/...
main_app.include_router(r_order_one)       # /orders/...

setup_auth_static_include(main_app)             # блог: middleware + mount /static + router_blog_api

main_app.mount(
    "/assets",
    StaticFiles(directory=BASE_DIR.parent / "frontend" / "dist" / "assets", check_dir=False),
    name="spa_assets",
)

# catch-all: строго после всех include_router и mount
async def spa_fallback(request):
    """Отдаёт index.html React SPA для всех путей вне api/static/assets/docs."""
    path = request.url.path
    if path.startswith("/api"):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    index_html = BASE_DIR.parent / "frontend" / "dist" / "index.html"
    if not index_html.is_file():
        return JSONResponse(status_code=404,
            content={"detail": "Frontend не собран: выполните npm run build в frontend/"})
    return FileResponse(index_html)

main_app.router.routes.append(
    Route("/{full_path:path}", spa_fallback, methods=["GET"])
)
```

**Зачем catch-all?** React Router роутит на клиенте (`/art/Max/7`). Если
пользователь открыл такой URL напрямую (закладка, F5), сервер должен вернуть
`index.html` — иначе 404. А `/api/*` перехватывается раньше и честно отвечает
404 JSON. Подробно — в [статье 06](06-integration-deploy.md).

## 4. Конфигурация: pydantic-settings с префиксами

`core/config.py` (реальный код, упрощён):

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            BASE_DIR / "dev_sqlite.env",    # sqlite   ← активный профиль
            # BASE_DIR / "prod_db.env",  # postgres ← закомментирован
            BASE_DIR / ".env",       # перекрывает оба
        ),
        case_sensitive=False,
        env_prefix="APP__",
        env_nested_delimiter="__",
    )
    api: ApiPrefix = ApiPrefix()
    db: DatabaseConfig          # единственное обязательное поле
    run: RunConfig = RunConfig()
```

Отображение переменных: `APP__DB__URL` → `settings.db.url`,
`APP__RUN__PORT` → `settings.run.port`.

**Почему так, а не `os.environ["DB_URL"]` по коду:**

- Валидация конфига при старте: нет обязательной переменной — приложение падает
  сразу и с понятной ошибкой, а не в середине запроса.
- Вложенные модели = самодокументируемое дерево настроек.
- Один объект `settings` (синглтон на уровне модуля) — единая точка истины.

**Префиксы маршрутов тоже из конфига** — роутеры не хардкодят пути:

```python
r_users_sql = APIRouter(
    prefix=settings.api.user_post_prefix,   # "/users"
    tags=["Sql example users"],
)
```

## 5. Dependency Injection — главный паттерн FastAPI

Идея: обработчик **объявляет, что ему нужно**, а FastAPI сам это построит на
каждый запрос. Три типовых формы (все есть в проекте):

### а) Ресурс — сессия БД (самый частый)

```python
# db_core/db_async.py
CurrentSession = Annotated[AsyncSession, Depends(db_manager.get_async_session)]

# обработчик — одна строка вместо ручного управления сессией
@r_users_sql.get("/get_all_users", response_model=list[UserResp])
async def get_users(session: CurrentSession):
    return await users_crud.get_all_users(session=session)
```

Генератор-зависимость даёт точку teardown: сессия открывается до обработчика и
закрывается после ответа, при исключении — rollback. Полный разбор — [статья 03](03-database-layer.md).

### б) Фабрика зависимостей (замыкание)

Когда параметр зависимости нужен на этапе *описания*, а не запроса:

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

**Почему DI, а не просто вызывать функции внутри обработчика:**

- Переиспользование: одна зависимость `CurrentSession` — сотни обработчиков.
- Тестируемость: `app.dependency_overrides[get_async_session] = fake_session` —
  и тест работает без БД.
- Граф зависимостей FastAPI кэширует в рамках одного запроса: если два
  обработчика просят одну зависимость, она выполнится один раз.

## 6. Чего избегать (грабли этого проекта)

| Грабля | Последствие | Как правильно |
|---|---|---|
| Побочные эффекты на импорте (`db_manager` создаёт engine при импорте модуля) | Импорт `main` требует валидного конфига; подмена в тестах — только через `dependency_overrides` | Создавать тяжёлые ресурсы в lifespan или лениво |
| Хардкод путей в роутерах | При переезде `/api/v1` править десятки файлов | Префиксы из `settings.api` |
| Логика в обработчиках напрямую | SQL в роутах не переиспользовать и не тестировать | Тонкий обработчик → CRUD/сервисный слой ([статья 03](03-database-layer.md)) |

## 7. Чекпоинт самопроверки

- [ ] `create_app()` — единственное место создания `FastAPI`.
- [ ] `lifespan` закрывает все открытые ресурсы.
- [ ] Ни одного `os.environ` вне `core/config.py`.
- [ ] Все префиксы роутеров — из конфига.
- [ ] Обработчики тонкие: валидация + вызов сервиса, без SQL и бизнес-логики.

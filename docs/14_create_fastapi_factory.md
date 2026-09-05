# 14. Фабрика `create_app()` и `lifespan` в `create_fastapi.py`

Этот документ — про код в [`create_fastapi.py`](../fastapi-application/create_fastapi.py):
как фабрика собирает каркас приложения, что именно подключает, в каком порядке,
и где проходит граница между «каркасом» (фабрика) и «наполнением» (`main.py`).

Смежные документы:
- [`docs/02_architecture.md`](02_architecture.md) — общая архитектура, слои.
- [`docs/03_execution_flow.md`](03_execution_flow.md) — жизненный цикл запроса.
- [`docs/11_md_articles.md`](11_md_articles.md) — что именно делает `setup_auth_static_include`.

## 1. Зачем фабрика живёт в отдельном модуле

`main.py` собирает приложение из роутеров (`include_router`), подключает блог
`md_articles` через `setup_auth_static_include(main_app)` и монтирует React SPA
(`setup_react_routing_assets`). Само конструирование `FastAPI` (заголовок, ответ по умолчанию,
`lifespan`, маршруты документации) вынесено в `create_fastapi.py`, чтобы
`main.py` оставался короткой «картой» того, что входит в приложение, а
`create_app()` — единственным местом, где конструируется каркас. Блог и SPA
подключаются снаружи, потому что это наполнение, а не каркас.

Что это даёт:

- **Один источник правды для каркаса.** Сменить заголовок, заменить
  `ORJSONResponse` на обычный `JSONResponse`, переключиться на кастомный
  Swagger — это одна правка в одном файле, а не поиск по `main.py` /
  `main_gunicorn.py` / будущим CLI.
- **`main.py` остаётся обзорным.** В нём видно, какие доменные роутеры
  включены, что подключён блог через `setup_auth_static_include(main_app)` и
  что смонтирован SPA; всё это занимает ~30 строк. Если сюда же положить
  создание `FastAPI` + `lifespan` — карта приложения утонет в коде фабрики.
- **Альтернативные точки входа переиспользуют `create_app()`.**
  `main_gunicorn.py` (multi-worker) импортирует `create_app` и
  передаёт его gunicorn'у. Будущие CLI (управляющие скрипты, миграции
  с загруженной ASGI, тесты) тоже вызывают `create_app()`, не дублируя его тело.

## 2. Что делает `create_app()` — два шага

### Шаг 1. Создание `FastAPI` с базовыми настройками

```python
app = FastAPI(
    title="Example : Fast API - SQL - React",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
    docs_url=docs_url,
    redoc_url=redoc_url,
)
```

Что здесь важно:

- `default_response_class=ORJSONResponse` — все ответы сериализуются
  `orjson` (быстрее стандартного `jsonable_encoder` на типичных
  pydantic-моделях и `datetime`-полях). Не нужно указывать `response_class`
  в каждом `@router.get` — это наследуется.
- `lifespan=lifespan` — см. раздел 3.
- `docs_url` / `redoc_url` — пара переключается параметром
  `custom_docs_url` (см. шаг 2).

### Шаг 2. Переключение документации

```python
docs_url, redoc_url = (None, None) if custom_docs_url else ("/docs", "/redoc")
...
if custom_docs_url:
    reg_docs_routes(app)
```

Два режима:

| `custom_docs_url` | `/docs` | `/redoc` | Кто регистрирует |
|---|---|---|---|
| `False` (по умолчанию) | стандартный Swagger от FastAPI | стандартный ReDoc от FastAPI | сам `FastAPI(...)` |
| `True` | кастомный (CDN, без `oauth2-redirect`) | кастомный | `reg_docs_routes(app)` из `utils/docs.py` |

`True` используется, когда стандартный UI чем-то не устраивает: нужны
другие стили, CDN-версии, тёмная тема, своя шапка. В этом проекте
стандартный UI достаточно хорош, поэтому флаг остаётся `False`.

### Шаг 3 (зафиксированное решение)

Фабрика не вызывает `setup_auth_static_include(app)` — это сделано в `main.py`.
Каркас приложения (`create_app()`) отвечает только за создание `FastAPI`,
`lifespan` и переключение документации; порядок подключения блога и SPA
зафиксирован в `main.py`. Это решение описано ниже в разделе «Граница ответственности».

### Чего `create_app()` НЕ делает

- **Не подключает роутеры доменов.** `api/`, `ex_user_post/`,
  `ex_order_product/` — это `include_router` в `main.py`. Фабрика про
  них не знает.
- **Не подключает блог.** `setup_auth_static_include(main_app)` живёт в
  `main.py` после доменных `include_router` и до `setup_react_routing_assets(main_app)`.
  Подробности — в [`docs/11_md_articles.md`](11_md_articles.md).
- **Не подключает SPA.** `frontend_routing.setup_react_routing_assets(main_app)` живёт в
  `main.py` после `setup_auth_static_include`. См.
  [`docs/13_frontend_spa_module.md`](13_frontend_spa_module.md).
- **Не запускает `uvicorn`.** Это дело `if __name__ == "__main__": main()`
  в `main.py` и `main_gunicorn.py`.

## 3. `lifespan` — startup и shutdown

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    logF.info(f"startup lifespan :\n{settings.db.url=} \n{app.title=}")
    if isinstance(settings.db.url, SqliteDsn):
        logF.warning(f"used test sqlite dataBase : {settings.db.url=}")
    yield
    await db_manager.engine_dispose()
```

### Startup

- Логирует URL базы и заголовок приложения — две строки, которые в логах
  сразу подтверждают «приложение стартовало, вот его конфигурация».
- Если URL — `SqliteDsn` (диагностический признак dev-режима), выводится
  предупреждение: «в проде ожидается PostgreSQL». Помогает случайно не
  запустить прод-стек с `dev_sqlite.env`.

### Shutdown

`db_manager.engine_dispose()` асинхронно закрывает пул соединений
engine SQLAlchemy. Без явного `dispose` процесс может «висеть» при
выходе из-за незакрытых фоновых задач внутри драйвера БД (особенно
заметно на `asyncpg`, где есть свой event loop). `main_gunicorn.py` и
`uvicorn --reload` корректно дожидаются завершения `lifespan` при
остановке сигналом SIGTERM/SIGINT — асинхронный код в `yield` ниже
завершится штатно, и только после этого сработает `engine_dispose()`.

## 4. Граница ответственности: `create_app()` vs `main.py`

| Слой | Где | Что в нём |
|---|---|---|
| Каркас | `create_app()` | `FastAPI(...)`, `lifespan`, переключение `/docs`/`/redoc` |
| Наполнение | `main.py` | `include_router` для `api/`, `ex_user_post/`, `ex_order_product/`, вызов `setup_auth_static_include(main_app)`, `setup_react_routing_assets` для React-фронта, запуск `uvicorn` |
| Плагин | `md_articles.setup_auth_static_include` | middleware (сессии, current_user), mount `/static`, JSON-роутер `/api/blog` |
| Точка входа | `main.py::main()`, `main_gunicorn.py` | `uvicorn.run(...)`, `gunicorn main:main_app` |

Порядок в `main.py` зафиксирован:

```python
main_app = create_app(custom_docs_url=False)
main_app.include_router(router_api)
main_app.include_router(r_users_sql)
main_app.include_router(r_order_one)
setup_auth_static_include(main_app)   # middleware + mount /static + router_blog_api
setup_react_routing_assets(main_app)  # mount /assets + SPA catch-all
```

Почему именно такой порядок:

- Доменные `include_router` идут **до** `setup_auth_static_include`. В Starlette
  middleware, добавленные через `add_middleware` / `middleware("http")(...)`,
  оборачивают весь ASGI-стек, поэтому порядок их регистрации относительно
  `include_router` не влияет на охват. Текущий порядок безопасен ещё и
  потому, что доменные роутеры (`router_api`, `r_users_sql`, `r_order_one`)
  не используют `request.session` и `request.state.current_user` —
  это инвариант, который при добавлении новых доменов надо проверять.
- `setup_auth_static_include` идёт **до** `setup_react_routing_assets` потому, что mount `/static`
  блога должен быть в списке раньше SPA catch-all — иначе GET
  `/static/profile_pics/...` уйдёт в SPA-обработчик и вернёт `index.html`.

Если нужно добавить в проект новый «большой кусок» (например, отдельный
модуль с WebSocket-роутами или админку), у вас есть выбор:

- **Положить в `main.py`** как ещё один `include_router`, если это
  «тонкий» слой без побочных эффектов.
- **Сделать plug-in** по образцу `md_articles`: `register_admin(app)`,
  вызываемый из `main.py` рядом с `setup_auth_static_include`. Этот вариант
  подходит, когда модуль навешивает middleware или делает несколько
  `mount`-ов.
- **Расширить `create_app()`** параметрами, если поведение каркаса должно
  настраиваться (например, `create_app(custom_docs_url=...)` — так уже
  сделано для документации).

Любой из этих путей согласован с разделением «каркас/наполнение».

## 5. Контракт `create_app()` для тестов и CLI

- Возвращает сконфигурированный `FastAPI` **без** middleware блога
  (`SessionMiddleware`, `inject_current_user_middleware`) и **без**
  JSON-роутера `/api/blog`. Это намеренно: тесту нужна изоляция от
  блога, и фабрика её даёт.
- Если тесту нужен блог, он вызывает `setup_auth_static_include(app)` сам —
  это обычная функция из `md_articles`, без побочных эффектов вне `app`.
- Никаких глобальных side-effects, кроме создания `db_manager.engine`
  (это побочный эффект импорта `db_core.db_async` — отдельная тема,
  см. `AGENTS.md` → «Побочные эффекты на импорте»).
- Тест, которому нужно подменить БД, делает это через
  `app.dependency_overrides[CurrentSession] = ...` — фабрика
  это не блокирует.
- Альтернативный `ASGITransport` для httpx: `app = create_app()` →
  `async with AsyncClient(transport=ASGITransport(app=app), ...)`
  работает без отдельной `lifespan`-обвязки.

# 08. Чеклист: FastAPI + React проект с нуля

> Цикл «FastAPI + React». Предыдущая: [07. Альтернативы](07-alternatives.md) · Начало: [README](README.md)

Пошаговый план сборки своего проекта по образцу этого репозитория. Каждый
шаг — с указанием «зачем» и ссылкой на подробную статью. Шаги упорядочены
так, чтобы на каждом была проверяемая точка («сайт ещё работает»).

## Этап 0. Окружение

```bash
uv init && uv add fastapi "uvicorn[standard]" orjson pydantic-settings \
    "sqlalchemy[asyncio]" asyncpg aiosqlite alembic bcrypt pillow PyYAML
uv add --dev ruff black
```

- **Зачем uv:** быстрый, детерминированный lock-файл, единый источник
  истины зависимостей.
- **Зачем orjson сразу:** `default_response_class=ORJSONResponse` —
  бесплатная скорость сериализации.
- **Зачем bcrypt + pillow + PyYAML:** bcrypt нужен для паролей в
  cookie-сессиях, pillow — для ресайза аватаров, PyYAML — для реестра
  статей блога (если делаете блог-часть).

## Этап 1. Скелет бэкенда (см. [статью 02](02-fastapi-backend.md))

1. `core/config.py` — `Settings(BaseSettings)` с префиксом `APP__`,
   вложенные модели, `env_file`-профили (sqlite для разработки, postgres
   для прода).
2. `create_fastapi.py` — фабрика `create_app()` + `lifespan` (dispose
   движка в shutdown). Каркас не знает про блог — подключение делается
   из `main.py`.
3. `main.py` — `main_app = create_app()`, доменные `include_router`,
   `include_router_api_frontend(main_app)` (если есть блог),
   `mount_vite_react_assets(main_app)`, `uvicorn.run(...)` в `__main__`.
4. Логирование — `config_log.py`, dictConfig, файл + stdout, инициализация
   на импорте модуля.

**Проверка:** `uvicorn main:main_app` поднимается, `/docs` открывается.
`len(main_app.routes)` показывает все смонтированные маршруты.

## Этап 2. Слой данных (см. [статью 03](03-database-layer.md))

1. `db_core/db_async.py` — `AsyncDbManager` (engine + session_factory) и
   алиас `CurrentSession = Annotated[AsyncSession, Depends(...)]`.
2. `db_core/model_base.py` — `Base(DeclarativeBase)` с автогенерацией
   `__tablename__` и `naming_convention`.
3. `db_core/type_for_models.py` — `Annotated`-типы колонок
   (`int_primary_key`, `str_len_*`, `time_stamp_utc`, ...).
4. Первая модель домена + **реэкспорт в `db_core/__init__.py`** (иначе
   Alembic её не увидит!).
5. `alembic init` (async-шаблон), первая миграция, `upgrade heads`.

**Проверка:** таблица создана, `alembic upgrade heads` идемпотентен.

## Этап 3. Первый вертикальный срез API (см. [статью 04](04-json-api-contract.md))

Минимальный сквозной путь «схема → CRUD → роут»:

```python
# schemas
class ItemCreate(BaseModel):
    title: str

class ItemResp(BaseModel):
    id: int
    title: str
    model_config = ConfigDict(from_attributes=True)

# crud (ex_<domain>/crud/crud_<name>.py)
async def create_item(session: AsyncSession, data: ItemCreate) -> Item:
    item = Item(**data.model_dump())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item

# router
@router.post("/items", response_model=ItemResp)
async def create(session: CurrentSession, data: ItemCreate):
    return await items_crud.create_item(session, data)
```

**Проверка:** `curl -X POST .../items -d '{"title":"x"}'` → 200; ошибка
валидации → 422 с описанием поля; Swagger `/docs` показывает схему.

## Этап 4. Каркас фронтенда (см. [статью 05](05-react-frontend.md))

```bash
cd frontend && npm create vite@latest . -- --template react-ts
npm i react-router-dom
npm i -D tailwindcss @tailwindcss/vite
```

1. `vite.config.ts` — прокси `/api` и `/static` на `:8000`.
2. `src/types.ts` — TS-зеркало pydantic-схем этапа 3.
3. `src/api/client.ts` — базовый клиент: `credentials: 'include'`,
   `ApiError`, `getJson`/`postJson`/`postMultipart` (CSRF — сразу,
   см. этап 6).
4. `src/api/<domain>.ts` — доменные функции поверх клиента.
5. `src/context/AuthContext.tsx` — провайдер с фазой `loading`.
6. `Layout` + роуты (`src/App.tsx`) + первая страница со списком из API.

**Проверка:** `npm run dev` → страница на `:5173` показывает данные из
FastAPI через прокси; правки перерисовываются мгновенно (HMR).

## Этап 5. Связка для прода (см. [статью 06](06-integration-deploy.md))

1. В `main.py`: `mount_vite_react_assets(main_app)` (функция живёт в
   `md_articles/setup_frontend.py:79`). Она делает и `/assets`-mount, и
   catch-all `/{full_path:path}`.
2. Catch-all — **строго последним** через `app.router.routes.append(...)`,
   **не** через `include_router`: `/api*` → 404 JSON, остальное →
   `dist/index.html`, с понятной ошибкой если `dist` не собран.
3. `npm run build` → проверить сайт на `:8000` без Vite.

**Проверка:** один процесс на `:8000` отдаёт и SPA, и API; F5 на глубоком
маршруте (`/items/5`) работает — catch-all вернул `index.html`.

## Этап 6. Авторизация (см. [статью 06](06-integration-deploy.md))

1. **Разнесите на три файла**: `middleware_auth.py` (HTTP-middleware,
   `add_middleware_auth`), `helpers_auth.py` (bcrypt, CSRF, `user_out`,
   сессионные хелперы), `api_auth.py` (JSON-роутер `/api/blog/auth`).
2. `add_middleware_auth(app)` добавляет **в этом порядке**:
   - `BaseHTTPMiddleware(dispatch=inject_current_user_middleware)` — **до**
     SessionMiddleware (иначе `request.session` в middleware упадёт);
   - `SessionMiddleware(secret_key=settings.web.secret_key, max_age=14d)`;
   - exception handler для `RequestValidationError` (формат `{"errors": ...}`
     для `/api/blog/*`).
3. `BlogUser`-модель (или ваша доменная модель юзера) + bcrypt-хеширование.
4. JSON-эндпоинты: `register` / `login` / `logout` / `current_user` /
   `csrf` / `account` (GET/POST). `require_login_api` → **403 JSON**
   (не редирект).
5. CSRF: `GET /csrf` отдаёт токен сессии; изменяющие запросы проверяют
   `X-CSRF-Token` (JSON) или поле формы `csrf_token` (multipart).
6. Фронтенд: `AuthProvider` с фазой `loading`, `RequireAuth` на защищённых
   маршрутах; CSRF — внутри `postJson`/`postMultipart`.

**Проверка:** логин переживает F5 (cookie), выход сбрасывает, защищённый
API без сессии отдаёт 403, а фронтенд переводит на форму входа.

## Этап 7. Качество и привычки

```bash
uv run ruff check . && uv run ruff format .   # линтер и форматтер
cd frontend && npx tsc --noEmit               # типы фронтенда — тоже
```

- Миграции — только через Alembic, файл миграции читать до применения.
- Каждый новый эндпоинт появляется в `/docs` — это и есть живая
  документация контракта.
- После правок фронтенда — контрольный `npm run build` (грабля №1 из
  [статьи 01](01-architecture-overview.md)).
- `len(main_app.routes)` — записать baseline в SPEC задания (для этого
  проекта: 42 на ветке `auth_refactor`, 2026-09).

## Сводный чеклист

- [ ] uv + lock-файл, Python 3.12.
- [ ] `create_app()` + `lifespan`, конфиг в pydantic-settings (`APP__`).
- [ ] Блог подключается через `include_router_api_frontend(main_app)` из `main.py`,
      а не из `create_app()`.
- [ ] `CurrentSession` через Depends; SQL только в CRUD-слое.
- [ ] Модели реэкспортированы для Alembic; миграции в git.
- [ ] Схемы запроса/ответа раздельные; `response_model` везде.
- [ ] 4xx для ожидаемых ситуаций; свой формат 422 для форм SPA.
- [ ] Vite-прокси в dev; `mount_vite_react_assets(main_app)` в prod (mount + catch-all).
- [ ] Авторизация разнесена на три файла; middleware в правильном порядке.
- [ ] API-клиент с `credentials` и CSRF; `AuthContext` с `loading`.
- [ ] ruff/black + `tsc --noEmit` в routine.
- [ ] `/docs` — актуальный контракт; `types.ts` ему синхронен.

Готово: у вас современный стек «FastAPI + React» с одним деплой-юнитом,
типизированным контрактом и без CORS-головной боли. Дальше — по
потребности: TanStack Query для серверного кэша, генерация TS из OpenAPI,
nginx+TLS, docker.
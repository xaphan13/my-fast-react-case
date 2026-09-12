# 02 — Архитектура и паттерны

## Высокоуровневая архитектура

Проект представляет собой **слоистый монолит** с сервер-сайд рендерингом (SSR). Архитектура не разделена на микросервисы — всё работает в одном процессе ASGI-сервера (`uvicorn`).

### Слои

```
┌──────────────────────────────────────────────────┐
│  Client (Browser + HTMX)                         │
│  HTML-запросы / HTMX-частичные запросы (JSON)   │
└──────────────────────┬───────────────────────────┘
                       │ HTTP (cookies, HX-headers)
┌──────────────────────▼───────────────────────────┐
│  Presentation Layer (app/api/)                   │
│  Route handlers → Jinja2 templates / HTMLResponse│
│  FastAPI exception handlers, middleware (GZip)   │
├──────────────────────────────────────────────────┤
│  Domain Layer (app/models/, app/schemas/)        │
│  SQLAlchemy ORM models + Pydantic schemas        │
│  NB: app/services/ — пуст, бизнес-логика в routes│
├──────────────────────────────────────────────────┤
│  Infrastructure Layer (app/core/)                │
│  config.py (Settings), database.py (engine/DB),  │
│  users.py (auth backend), templates.py (Jinja2)  │
├──────────────────────────────────────────────────┤
│  Database (SQLite / PostgreSQL)                  │
│  SQLAlchemy async ORM + Alembic migrations       │
└──────────────────────────────────────────────────┘
```

**Ключевая характеристика:** бизнес-логика не выделена в отдельный слой — она resides в route-хендлерах (`app/api/items.py`, `app/api/user.py`). Директория `app/services/` существует, но пуста (`__init__.py` без кода). Это создаёт связность между HTTP-обработкой и доменной логикой.

---

## Основные паттерны проектирования

### 1. Dependency Injection (FastAPI `Depends`)

Паттерн пронизывает весь код. Все ресурсы (DB-сессии, текущий пользователь, конфигурация) инъектируются через `Depends()`.

- `app/core/database.py:33` → `get_db()` — инъекция `AsyncSession`
- `app/models/user.py:38` → `get_user_db()` — инъекция `SQLAlchemyUserDatabase`
- `app/models/user.py:72` → `get_user_manager()` — инъекция `UserManager`
- `app/core/users.py:26` → `fastapi_users.current_user(...)` — инъекция аутентифицированного `User`
- `app/api/dependencies.py:10` → `is_htmx()` — инъекция флага HTMX-запроса

Цепочка DI для аутентификации:
```
Request → get_db() → get_user_db() → get_user_manager() → fastapi_users.current_user()
```

### 2. Repository Pattern (через `fastapi-users`)

`SQLAlchemyUserDatabase` (`app/models/user.py:41`) выступает repository-абстракцией над `User`-моделью. Однако для `Item` repository-паттерн не реализован — запросы к БД пишутся напрямую в route-хендлерах через `select()`, `db.add()`, `db.delete()`.

### 3. Strategy Pattern (аутентификация)

`app/core/users.py` реализует стратегию аутентификации:
- `CookieTransport` — транспорт (cookie `auth`, max_age=3600)
- `JWTStrategy` — стратегия токенов (secret=`SECRET_KEY`, lifetime=3600с)
- `AuthenticationBackend` — связка транспорта и стратегии

### 4. Template Inheritance (Jinja2)

Шаблоны используют наследование: `base.jinja2` → конкретные страницы. Partial-шаблоны (`_table.jinja2`, `_item_row.jinja2`, `_edit_form.jinja2`) включаются через `{% include %}` и возвращаются route-хендлерами как HTMX-фрагменты.

### 5. Lifespan (контекст управления приложением)

`app/main.py:28` — `@asynccontextmanager lifespan()` выполняет инициализацию БД при старте (`await init_db()` на строке 37) и корректно завершает работу при остановке.

---

## Схема потока данных (Data Flow)

### Стандартный HTMX-запрос (пример: создание Item)

```
1. Browser: HTMX POST /items (json-enc body: {title, description})
   Headers: HX-Request: true
   Cookie: auth=<jwt>
   │
2. FastAPI Middleware: GZipMiddleware (декомпрессия при необходимости)
   │
3. Router: app/api/items.py → create_item()
   │
4. Dependency Resolution (FastAPI DI):
   ├─ get_db() → AsyncSession (from app/core/database.py)
   ├─ fastapi_users.current_user(active=True) → User
   │   ├─ CookieTransport.read() → token from cookie
   │   ├─ JWTStrategy.read_token() → decode JWT
   │   ├─ get_user_db() → SQLAlchemyUserDatabase
   │   └─ get_user_manager() → UserManager.get(id) → User
   └─ is_htmx(request) → True
   │
5. Body Validation: ItemCreate (Pydantic) → {title: str, description: str|None}
   │
6. Business Logic (inline в route handler):
   ├─ Item(title=..., description=..., owner_id=user.id)
   ├─ db.add(item) → db.commit() → db.refresh(item)
   └─ Повторный SELECT для обновлённого списка items с пагинацией
   │
7. Template Rendering: templates.TemplateResponse("items/_table.jinja2", context)
   │  Jinja2 рендерит HTML-фрагмент таблицы
   │
8. Response: HTMLResponse (HTML-фрагмент)
   │
9. Browser: HTMX свопает innerHTML целевого элемента (#items-container)
```

### Запрос неаутентифицированного пользователя

```
Request → fastapi_users.current_user() → 401 Unauthorized
  │
  ├─ HTMX-запрос: exception_handler → Response(200, HX-Redirect: /auth/login)
  └─ Обычный запрос: exception_handler → RedirectResponse(302 → /auth/login)
```

---

## Управление состоянием

### Сессии БД

`app/core/database.py:33` — `get_db()` создаёт `AsyncSession` на каждый запрос:
- `yield session` → коммит после успешного выполнения
- `except Exception` → rollback
- `finally` → close

`expire_on_commit=False` — объекты остаются доступными после коммита (важно для background tasks и template rendering).

### Аутентификационное состояние

State-less на сервере: JWT в cookie `auth` (HttpOnly, SameSite=lax, max_age=3600). Сервер не хранит сессии — каждый запрос декодирует JWT заново.

> **NB:** В `app/core/users.py:11` `CookieTransport` создаётся **без явного** `cookie_secure`. В `fastapi-users==14.0.1` дефолт `cookie_secure=True` (см. `fastapi_users/authentication/transport/cookie.py:21-39`). В `fastapi-users<14` дефолт был `False`. Это значит, что в 14.x cookie действительно отдаётся только по HTTPS; но при апгрейде/даунгрейде версии библиотеки поведение изменится молча. Рекомендуется задать `cookie_secure` явно, чтобы контракт безопасности жил в коде, а не в дефолте upstream-зависимости. Подробный разбор — в `docs/08_authentication_guide.md`, §3.1.

### Кэширование

Кэширование отсутствует. Нет Redis, нет in-memory cache, нет HTTP-кэш-headers.

---

## Управление конфигурацией

### Источник: `app/core/config.py`

Класс `Settings(BaseSettings)` (pydantic-settings):

| Параметр | Default | Источник |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./app.db` | `.env` / env var |
| `SECRET_KEY` | `secrets.token_hex(32)` (генерируется при каждом запуске!) | `.env` / env var |
| `SQLITE_ASYNC_CONN_STR` | `None` (вычисляется в `model_validator`) | auto-derived |

Загрузка: `SettingsConfigDict(env_file=".env", extra="ignore")` — читает `.env`, игнорирует неизвестные переменные.

`model_validator(mode="before")` нормализует SQLite-URL, заменяя `sqlite+aiosqlite:///` на `sqlite+aiosqlite:///./` для корректного относительного пути.

> **Критично:** `SECRET_KEY` имеет runtime-default через `secrets.token_hex(32)` (`app/core/config.py:18`). Если не задан в `.env`, при каждом рестарте генерируется новый ключ — все JWT-сессии инвалидируются. Обработчик `lifespan` в `app/main.py:32` логирует предупреждение (только лог — `SECRET_KEY` не валидируется).

### Конфигурация Alembic

`alembic/env.py:72` — `sqlalchemy.url` из `alembic.ini` переопределяется `settings.DATABASE_URL` во время выполнения. Миграции работают в async-режиме через `async_engine_from_config` + `NullPool`.

### Конфигурация линтеров/форматтеров

| Инструмент | Конфигурация | Назначение |
|---|---|---|
| `black` | `pyproject.toml [tool.black]` | line-length=88, target=py312 |
| `ruff` | `pyproject.toml [tool.ruff]` | E/F/W/I/S/COM/B/C4/T10/PTH; per-file-ignores для tests и cli |
| `mypy` | `pyproject.toml [tool.mypy]` | python_version=3.12, strict-ish |
| `isort` | `.pre-commit-config.yaml` | profile=black |
| `flake8` | `.flake8` | Дублирует часть ruff — избыточен |
| `djlint` | `pyproject.toml [tool.djlint]` | profile=jinja, indent=2 |
| `pytest` | `pyproject.toml [tool.pytest.ini_options]` | asyncio_mode=auto, coverage=app |
| `pre-commit` | `.pre-commit-config.yaml` | 6 hook-групп |

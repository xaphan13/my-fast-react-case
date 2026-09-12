# 01 — Карта проекта

## Назначение проекта

`fastapi-htmx-starter` — стартовый шаблон (boilerplate) для построения сервер-сайд рендерящихся веб-приложений на стеке **FastAPI + HTMX + TailwindCSS + SQLAlchemy 2.0 (async)**. Проект предоставляет готовую инфраструктуру аутентификации (через `fastapi-users`), CRUD-пример с HTMX-частичными обновлениями, асинхронный ORM-слой с поддержкой SQLite/PostgreSQL и миграциями через Alembic.

Шаблон следует слоистой монолитной архитектуре: маршруты → модели/схемы → БД. Бизнес-логика resides непосредственно в route-хендлерах; директория `app/services/` зарезервирована, но пуста. Фронтенд рендерится на сервере через Jinja2-шаблоны, HTMX обеспечивает частичные обновления без SPA-фреймворков.

---

## Дерево директорий и ключевых файлов

```
fastapi-htmx-starter/
├── .github/
│   ├── workflows/
│   │   └── ci.yml                    # CI-пайплайн: test, lint, type-check, security (bandit), build
│   └── PULL_REQUEST_TEMPLATE.md      # Шаблон PR-описания
├── alembic/
│   ├── env.py                        # Конфигурация Alembic: async-движок, target_metadata = Base.metadata
│   ├── script.py.mako                # Шаблон генерации файлов миграций
│   ├── README                        # Стандартный Alembic README
│   └── versions/                     # (пусто) — директория для файлов миграций
├── alembic.ini                       # Конфигурация Alembic: sqlalchemy.url, логгеры
├── app/
│   ├── __init__.py                   # Пакетный маркер ( комментарий)
│   ├── main.py                       # Точка входа: создание FastAPI-приложения, lifespan, роутеры, exception handler, статика
│   ├── cli.py                        # CLI-обёртки: serve, test, lint, format, check-types (через subprocess)
│   ├── api/                          # Слой маршрутов (route handlers)
│   │   ├── __init__.py
│   │   ├── auth.py                   # HTML-страницы login/register, кастомный POST /register, POST /logout
│   │   ├── items.py                  # CRUD для Item: list (search+pagination), create, edit, update, delete, cancel
│   │   ├── user.py                   # Профиль пользователя: GET /profile, PATCH /profile/email, PATCH /profile/password
│   │   └── dependencies.py           # Вспомогательные зависимости: is_htmx(request), get_db(request) — NB: мёртвый код
│   ├── core/                         # Инфраструктурный слой
│   │   ├── __init__.py
│   │   ├── config.py                 # Pydantic Settings: DATABASE_URL, SECRET_KEY, SQLITE_ASYNC_CONN_STR
│   │   ├── database.py               # Async engine, AsyncSessionLocal, Base, get_db(), init_db()
│   │   ├── templates.py              # Jinja2Templates(directory="app/templates")
│   │   └── users.py                  # Конфигурация fastapi-users: cookie transport, JWT strategy, auth_backend
│   ├── models/                       # SQLAlchemy ORM-модели
│   │   ├── __init__.py
│   │   ├── user.py                   # Модель User (fastapi-users) + UserManager + get_user_db + get_user_manager
│   │   └── item.py                   # Модель Item: id, title, description, owner_id (FK → user.id)
│   ├── schemas/                      # Pydantic-схемы для валидации
│   │   ├── __init__.py
│   │   ├── user.py                   # UserRead, UserCreate, UserUpdate (наследники fastapi-users schemas)
│   │   └── item.py                   # ItemBase, ItemCreate, ItemUpdate, ItemRead (from_attributes=True)
│   ├── services/
│   │   └── __init__.py               # (пусто) — зарезервировано для бизнес-логики
│   ├── static/
│   │   └── css/
│   │       └── custom.css            # Кастомные стили: HTMX-индикаторы, анимации, @apply Tailwind-директивы
│   ├── templates/                    # Jinja2 HTML-шаблоны
│   │   ├── base.jinja2               # Базовый layout: nav, Tailwind CDN, HTMX CDN, JS-обработка ошибок
│   │   ├── index.jinja2              # Главная страница
│   │   ├── profile.jinja2            # Страница профиля: email/password редактирование, статистика
│   │   ├── auth/
│   │   │   ├── login.jinja2          # Форма входа (HTMX POST → /auth/cookie/login)
│   │   │   └── register.jinja2       # Форма регистрации (HTMX POST → /auth/register, json-enc extension)
│   │   ├── items/
│   │   │   ├── index.jinja2          # Страница списка items: поиск, форма создания, пагинация
│   │   │   ├── _table.jinja2         # Partial: таблица items + пагинация (HTMX-свопаемый фрагмент)
│   │   │   ├── _item_row.jinja2      # Partial: строка item в режиме просмотра
│   │   │   └── _edit_form.jinja2     # Partial: строка item в режиме редактирования
│   │   └── partials/
│   │       └── auth_links.jinja2     # Partial: ссылки Login/Register/Logout (NB: ссылается на несуществующий роут)
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py               # Fixtures: test DB engine, override_get_db, async client, setup_database
│       └── test_main.py              # 4 базовых smoke-теста: /, /auth/login, /auth/register, /items (auth required)
├── pyproject.toml                    # Конфигурация проекта: зависимости, CLI scripts, black/ruff/mypy/pytest/djlint
├── .env.example                      # Шаблон переменных окружения
├── .flake8                           # Конфигурация flake8 (дублирует часть ruff)
├── .pre-commit-config.yaml           # Pre-commit hooks: trailing-whitespace, black, isort, ruff, mypy, djlint
├── .gitignore                        # Игнорирование: .env, *.db, __pycache__, .venv, .mypy_cache и т.д.
├── uv.lock                           # Lockfile для uv
├── LICENSE                           # MIT License
└── README.md                         # Документация для разработчиков (quick start, структура, команды)
```

---

## Внешние зависимости и их роль

### Runtime-зависимости (`pyproject.toml → [project].dependencies`)

| Зависимость | Версия | Роль в проекте |
|---|---|---|
| `fastapi` | `>=0.115.12` | Веб-фреймворк: маршрутизация, DI, middleware, exception handlers |
| `uvicorn` | `>=0.34.2` | ASGI-сервер для запуска приложения |
| `jinja2` | `>=3.1.6` | Шаблонизатор для сервер-сайд рендеринга HTML |
| `python-multipart` | `>=0.0.6` | Парсинг `multipart/form-data` (требуется FastAPI для форм) |
| `python-dotenv` | `>=1.0.0` | Загрузка переменных окружения из `.env` (используется pydantic-settings) |
| `sqlalchemy` | `>=2.0.0` | Async ORM: модели, сессии, запросы |
| `alembic` | `>=1.13.1` | Миграции схемы БД |
| `pydantic-settings` | `>=2.2.1` | Управление конфигурацией через `BaseSettings` |
| `aiosqlite` | `>=0.18.0` | Async-драйвер SQLite (default DATABASE_URL) |
| `fastapi-users[sqlalchemy]` | `>=13.0.0` | Аутентификация: регистрация, login, cookie/JWT, UserManager |
| `email-validator` | `>=2.1.1` | Валидация email-адресов (требуется Pydantic для `EmailStr`) |

### Dev-зависимости (`pyproject.toml → [tool.uv].dev-dependencies`)

| Зависимость | Роль |
|---|---|
| `pytest`, `pytest-asyncio`, `pytest-cov` | Тестирование + coverage |
| `httpx` | Async HTTP-клиент для тестов (`AsyncClient` + `ASGITransport`) |
| `black`, `isort`, `ruff`, `flake8` | Форматирование и линтинг |
| `mypy` | Статическая типизация |
| `pre-commit` | Pre-commit hooks |
| `watchfiles` | Hot-reload для dev-сервера |
| `djlint` | Линтинг/форматирование Jinja2-шаблонов |

### Внешние сервисы и CDN

| Ресурс | Тип | Роль |
|---|---|---|
| SQLite (`app.db`) | БД (default) | Локальная разработка; async через `aiosqlite` |
| PostgreSQL (`asyncpg`) | БД (production) | Поддерживается через `DATABASE_URL`, но не сконфигурирована по умолчанию |
| `cdn.tailwindcss.com` | CDN | TailwindCSS (Play CDN — не для production) |
| `unpkg.com/htmx.org@2.0.4` | CDN | HTMX-библиотека |
| `unpkg.com/htmx.org@1.9.12/dist/ext/json-enc.js` | CDN | HTMX-расширение для JSON-кодирования тел запросов |

> **NB:** Брокеры сообщений, кэш-серверы (Redis) и сторонние API в проекте отсутствуют.

# Гайд по авторизации: fastapi-htmx-starter

Подробный многостраничный гайд по системе авторизации этого проекта. Цель —
не пересказать код, а дать **понимание механизма**: что делает библиотека
`fastapi-users`, что написано руками в проекте, где граница ответственности,
почему каждое решение принято именно так и что сломается, если его поменять.

Гайд написан для **переноса этого стиля авторизации в другие проекты**:
последняя страница — пошаговый чеклист переноса и список граблей. Но сначала
читайте страницы по порядку: перенос без понимания — это копирование багов.

> Смежный документ: [`docs/08_authentication_guide.md`](../08_authentication_guide.md) —
> концептуальный разбор «как и почему». Этот гайд дополняет его: идёт **по файлам**,
> с полным кодом и комментариями, и заканчивается практикой переноса.
> В `docs/08` часть утверждений относится к fastapi-users 14.x — здесь все факты
> сверены с установленной версией **15.0.5** (см. `uv.lock`).

---

## Оглавление

| Страница | Что внутри |
|---|---|
| [01_overview.md](01_overview.md) | Общая картина: три слоя fastapi-users, поток запроса, карта всех файлов с auth-кодом, версии |
| [02_core_wiring.md](02_core_wiring.md) | `app/core/users.py` — транспорт, стратегия, бэкенд; `app/core/config.py` — SECRET_KEY; `app/core/database.py` — сессия БД |
| [03_models_and_schemas.md](03_models_and_schemas.md) | `app/models/user.py` — модель User, UserManager, DI-цепочка; `app/schemas/user.py`; миграция Alembic |
| [04_routers.md](04_routers.md) | `app/main.py` — сборка приложения и 401-handler; `app/api/auth.py` — страницы login/register/logout; `app/api/dependencies.py` |
| [05_profile_and_users_api.md](05_profile_and_users_api.md) | `app/api/user.py` — профиль, смена email/пароля, встроенные `/users/*` |
| [06_frontend_htmx.md](06_frontend_htmx.md) | Шаблоны: `base.jinja2`, `auth/login.jinja2`, `auth/register.jinja2`, `profile.jinja2`; form-data vs JSON, HX-Redirect |
| [07_testing.md](07_testing.md) | Smoke-тесты, conftest, curl-сценарии полного auth-flow, нюанс Secure-cookie по HTTP |
| [08_porting_checklist.md](08_porting_checklist.md) | Перенос в другой проект: матрица переноса всех файлов (1:1 / с правками / не переносить), пошаговая инструкция с чекпоинтами, грабли, расширения |
| [09_react_vite_porting.md](09_react_vite_porting.md) | Отдельный сценарий: перенос на React + Vite (SPA) при существующей самописной авторизации — proxy/CORS, интерцептор 401, миграция паролей |

## Карта файлов с auth-кодом

Все файлы, где живёт авторизация, и где они разобраны:

| Файл | Роль | Страница |
|---|---|---|
| `app/core/users.py` | Транспорт + стратегия + бэкенд + точка входа `fastapi_users` | [02](02_core_wiring.md) |
| `app/core/config.py` | `SECRET_KEY` — подпись всех JWT | [02](02_core_wiring.md) |
| `app/core/database.py` | `get_db` — сессия, на которой стоит вся цепочка DI | [02](02_core_wiring.md) |
| `app/models/user.py` | ORM-модель `User`, `UserManager`, `get_user_db`, `get_user_manager` | [03](03_models_and_schemas.md) |
| `app/models/__init__.py` | Re-export моделей для Alembic | [03](03_models_and_schemas.md) |
| `app/schemas/user.py` | Pydantic-схемы `UserRead/Create/Update` | [03](03_models_and_schemas.md) |
| `alembic/versions/8d9cb1e66c56_initial_migration.py` | DDL таблицы `user` | [03](03_models_and_schemas.md) |
| `app/main.py` | Подключение роутеров, 401-handler, lifespan | [04](04_routers.md) |
| `app/api/auth.py` | Страницы и обработчики login / register / logout | [04](04_routers.md) |
| `app/api/dependencies.py` | `is_htmx` (и мёртвый `get_db` — предостережение) | [04](04_routers.md) |
| `app/api/user.py` | Профиль, смена email/пароля, `get_users_router` | [05](05_profile_and_users_api.md) |
| `app/api/items.py` | Пример защищённого роута (`current_user(active=True)`) | [01](01_overview.md) |
| `app/templates/base.jinja2` | Навигация `{% if user %}`, logout через HTMX | [06](06_frontend_htmx.md) |
| `app/templates/auth/login.jinja2` | Форма логина (form-data) | [06](06_frontend_htmx.md) |
| `app/templates/auth/register.jinja2` | Форма регистрации (JSON) | [06](06_frontend_htmx.md) |
| `app/templates/profile.jinja2` | Смена email/пароля через HTMX | [06](06_frontend_htmx.md) |
| `app/templates/partials/auth_links.jinja2` | Не подключён, содержит битую ссылку — предостережение | [06](06_frontend_htmx.md) |
| `app/tests/test_main.py`, `app/tests/conftest.py` | Smoke-тесты и тестовая БД | [07](07_testing.md) |
| `pyproject.toml` | Зависимости, `extend-immutable-calls` для `current_user` | [08](08_porting_checklist.md) |

## Правила чтения

1. **Код в гайде — из проекта**, с добавленными комментариями `# <-` и `# почему:`.
   Оригинальные комментарии проекта сохранены, добавленные помечены.
2. Номера строк указаны на момент написания (`koda-audit`) и могут плыть.
3. Всё, что помечено **«Грабли»** или **«Известный дефект»** — осознанные
   компромиссы учебного проекта. При переносе в реальный проект закрывайте их
   по чеклисту из [08](08_porting_checklist.md), а не копируйте как есть.

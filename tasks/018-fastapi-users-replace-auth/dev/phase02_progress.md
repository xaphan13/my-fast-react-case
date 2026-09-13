# Phase 02 — progress (backend-dev)

Задание: замена самописной авторизации блога на fastapi-users.
Фаза 2: ядро пакета `auth_users` — auth backend, FastAPIUsers, account router,
общие роутеры, конфиг, обновление __init__.py.

## Итог
- Создано 4 новых файла в `fastapi-application/auth_users/`:
  `auth_backend.py`, `fastapi_users_obj.py`, `account.py`, `router.py`.
- `auth_users/__init__.py`: rewrite с полными экспортами (16 символов).
- `core/config.py`: добавлен `AuthUsersConfig` (cookie/jwt + password_min_length)
  и поле `auth_users: AuthUsersConfig = AuthUsersConfig()` в `Settings`.
- `auth_users/user_manager.py`: хардкод `8` заменён на
  `settings.auth_users.password_min_length`.
- Все 5 чекпоинтов зелёные. ruff чист. `main_app.routes == 42` (без регрессии).

## Шаги

### 2026-09-12 — auth_backend.py
- Файл: `fastapi-application/auth_users/auth_backend.py` (NEW)
- Содержимое 1:1 по спеке: `CookieTransport` + `JWTStrategy` +
  `AuthenticationBackend(name="jwt", ...)`. Параметры читаются из
  `settings.auth_users` (cookie_* + jwt_*), секрет JWT — из
  `settings.web.secret_key`.
- Импорты плоские (`from core.config import settings`).

### 2026-09-12 — fastapi_users_obj.py
- Файл: `fastapi-application/auth_users/fastapi_users_obj.py` (NEW)
- `FastAPIUsers[User, UUID](get_user_manager, [auth_backend])` + четыре
  зависимости: `current_user`, `active_user`, `optional_user`, `superuser_user`.

### 2026-09-12 — account.py
- Файл: `fastapi-application/auth_users/account.py` (NEW)
- `POST /auth/account`: валидация username/email/аватар, проверка уникальности,
  ресайз аватара, обновление `current_user`, ответ в формате фронтенда блога.
- Теги `auth-account`, префикс `/auth`. Использует `active_user` из
  fastapi_users_obj и helpers (`is_valid_email`, `username_exists`,
  `email_exists`, `save_picture`, `validation_response`, `ERROR_*_TAKEN`).

### 2026-09-12 — router.py
- Файл: `fastapi-application/auth_users/router.py` (NEW)
- Сборный `router`: `get_auth_router` → `/auth/jwt/login`,`/logout`;
  `get_register_router` → `/auth/register`; `get_users_router` →
  `/users/me` + `/users/{id}`; плюс `account_router` с `/auth/account`.
- Всего 9 маршрутов.

### 2026-09-12 — __init__.py rewrite + цикл импортов
- Файл: `fastapi-application/auth_users/__init__.py` (REWRITE)
- Полные экспорты 16 символов (см. `__all__`).
- **Расхождение со спекой №1 (см. ниже):** добавлена явная предзагрузка
  `import db_core` ПЕРЕД импортом `auth_users.models` — без неё цикл
  `auth_users.models -> db_core.model_base -> db_core/__init__ ->
  auth_users.models` ломается на partially-loaded модуле
  (`ImportError: cannot import name 'User' from partially initialized module
  'auth_users.models'`). Спека явно разрешила «отложенные импорты или
  переупорядочить» — это и есть «переупорядочить».

### 2026-09-12 — core/config.py
- Файл: `fastapi-application/core/config.py` (EDIT)
- Добавлен класс `AuthUsersConfig` с полями cookie_* + jwt_* + password_min_length.
  В `Settings` добавлено поле `auth_users: AuthUsersConfig = AuthUsersConfig()`
  рядом с `web`.

### 2026-09-12 — user_manager.py
- Файл: `fastapi-application/auth_users/user_manager.py` (EDIT)
- `validate_password`: `password_min_length = 8` (с TODO-комментарием)
  заменён на `password_min_length = settings.auth_users.password_min_length`.

## Что проверено (checkpoint)

| # | Команда | Ожидалось | Получено |
|---|---|---|---|
| 1 | `from auth_users import router; print(len(router.routes))` | `9` | `9` ✓ |
| 2 | `from auth_users import auth_backend; print(name, cookie_name)` | `jwt auth` | `jwt auth` ✓ |
| 3 | `from core.config import settings; print(cookie_name, jwt_lifetime_seconds)` | `auth 86400` | `auth 86400` ✓ |
| 4 | `uv run ruff check .` | exit 0 | `All checks passed!` ✓ |
| 5 | `from main import main_app; print(len(main_app.routes))` | `42` | `42` ✓ |
| бонус | `from auth_users import <все 16 символов из __all__>` | OK | `all 16 exports OK` ✓ |

Сырой вывод — `phase02_checkpoint.txt` и `phase02_ruff.txt`.

## Расхождения со спекой

### 1. `import db_core` в начале `auth_users/__init__.py` (спека не просила)

**Симптом:** при попытке сделать `from auth_users.models import User` самым
первым импортом в `__init__.py` Python ловит реальный цикл:

```
auth_users/__init__.py:  from auth_users.models import User
auth_users/models.py:    from db_core.model_base import Base
db_core/__init__.py:     (грузится впервые, т.к. db_core ещё нет в sys.modules)
db_core/__init__.py:     from auth_users.models import User   # ← partially loaded!
ImportError: cannot import name 'User' from partially initialized module
```

Это тот самый цикл, который спека предупреждала:
> ВАЖНО: при таких импортах Python столкнётся с частичным порядком загрузки
> (взаимные импорты через `auth_users.routers`). Если получишь ImportError
> про частично загруженный модуль — используй отложенные импорты внутри
> функций, либо переупорядочь.

**Что сделано:** в `auth_users/__init__.py` ПЕРЕД `from auth_users.models
import User` поставлена явная `import db_core`. Это заставляет Python
сначала полностью загрузить `db_core/__init__.py` (а тот в свою очередь
загрузит `auth_users.models` «с нуля», потому что его ещё нет в
sys.modules — к моменту строки `from auth_users.models import User` в
db_core/__init__.py он туда ещё не попал). После этого `auth_users.models`
уже в sys.modules и все последующие `from auth_users.models import User`
(в user_manager.py, fastapi_users_obj.py, account.py) — no-op.

Альтернативы, которые НЕ использовал:
- Lazy imports в каждом из 5 точек-консьюмеров auth_users.models — много
  шума, ломает читаемость и явные type hints.
- PEP 562 `__getattr__` на `auth_users/__init__.py` — не помогает: проблема
  в `auth_users.user_manager` (импортирует auth_users.models), а это не
  атрибут __init__.py.
- PEP 562 на `auth_users.models.User` — не помогает по той же причине:
  цепочка user_manager → auth_users.models всё равно идёт через прямой
  `from auth_users.models import User` в user_manager.py.
- Менять `db_core/__init__.py` (вне моей зоны правки фазы 2).

**Альтернатива, которая могла бы быть чище:** убрать
`from auth_users.models import User` из `db_core/__init__.py` совсем
(никто из production-кода `from db_core import User` не использует —
проверено grep'ом по всему репозиторию). Но это правка чужой зоны.
Запрос к оркестратору: возможно, стоит вынести эту строку из
db_core/__init__.py (и оставить только импорт Base, которого достаточно
для Alembic — `auth_users.models` всё равно регистрируется при первом
импорте user_manager/fastapi_users_obj, что происходит при загрузке
main.py).

### 2. Никаких других расхождений со спекой

Все 4 новых файла — 1:1 по контракту. `AuthUsersConfig` — 1:1 по полям.
Замена хардкода в `user_manager.validate_password` — 1:1.

## Что осталось на фазу 3

- Подключить `auth_users.router` к `main_app` в `main.py` (вместо или вместе
  с `md_articles.api_blog` — TBD по решению оркестратора).
- Обновить/удалить `md_articles.api_auth.py` и `md_articles.middleware_auth.py`
  — там живёт самописный login/register/logout, его нужно либо переключить
  на fastapi-users-роутеры, либо оставить до полного smoke-теста.
- Alembic-миграция для новой таблицы `user` (таблица уже есть в
  `Base.metadata`, фаза 1 это проверила; фаза 3 генерирует ревизию).
- Полный smoke с реальным register/login потоком через curl.

## Запросы к оркестратору

1. Решить, оставить ли предзагрузку `import db_core` в
   `auth_users/__init__.py` (текущее решение) или предпочесть
   «убрать из db_core/__init__.py строку `from auth_users.models import User`»
   (чище, но это правка файла вне моей фазы).
2. Подтвердить, что `auth_users.router` подключается именно в фазе 3
   (а не 4–5), чтобы фаза 3 уже включала wiring + миграцию + smoke.

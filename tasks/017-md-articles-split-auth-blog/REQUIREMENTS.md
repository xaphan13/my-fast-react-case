# md_articles: split auth/account routes from api_blog.py into api_auth.py

Серверный рефакторинг пакета `md_articles`: выделить auth/account-роуты
(`/api/blog/csrf`, `/current_user`, `/register`, `/login`, `/logout`,
`/account` GET/POST) в отдельный файл `api_auth.py` с роутером `router_auth`,
оставив в `api_blog.py` только блог-секции (`sections`, `articles`,
`articles/{art_id}`, `art_manage`, `art_manage/add_all`, `art_manage/meta`,
`art_manage/sync`). Дополнительно — переименовать `auth_middleware_helpers.py`
в `middleware_auth.py` через `git mv` (история сохраняется); в нём оставить
только 4 функции (секции 1–3 до строки 135 включительно: middleware,
`auth_add_middleware`, `custom_request_validation_exception_handler`); всё
ниже строки 135 (`login_user`/`logout_user`, `hash_password`/`verify_password`,
CSRF-хелперы, `require_login_api`, `_validation_response`, error-константы)
перенести в `helpers_blog.py`. URL-неймспейс `/api/blog` сохраняется,
поведение и сигнатуры не меняются, фронт не трогается.

## Подтверждённые решения

1. Префикс auth-роутера остаётся `/api/blog` (НЕ `/api/auth`). Все
   `fetch('/api/blog/login')` и пр. на фронте продолжают работать без правок.
2. Новый файл `md_articles/api_auth.py`, `router_auth = APIRouter(prefix="/api/blog", tags=["auth"])`,
   маршруты: `csrf`, `current_user`, `register`, `login`, `logout`,
   `account_get`, `account_post`.
3. `api_blog.py` после чистки содержит только блог-маршруты:
   `sections`, `articles`, `articles/{art_id}`, `art_manage`,
   `art_manage/add_all`, `art_manage/meta`, `art_manage/sync`. Имена
   роутов сохраняются (`blog_api.sections` и т.п.).
4. `auth_middleware_helpers.py` → `middleware_auth.py` через `git mv`.
   В файле остаются 4 функции: `inject_current_user_middleware` (строка 35),
   `get_current_user` (58), `auth_add_middleware` (76),
   `custom_request_validation_exception_handler` (114). Это секции 1–3,
   до строки 135 включительно.
5. `helpers_blog.py` дополняется 5 секциями из `auth_middleware_helpers.py`
   (всё ниже строки 135): `login_user` (138), `logout_user` (142),
   `hash_password` (149), `verify_password` (153), `_ensure_csrf_token` (160),
   `validate_csrf_form` (171), `validate_csrf_header` (180),
   `_get_request_user` (191), `require_login_api` (195),
   `_ERROR_EMAIL_TAKEN` (204), `_ERROR_USERNAME_TAKEN` (205),
   `_validation_response` (208+).
6. `frontend_auth_include.py`: минимальная правка — обновить импорт
   `auth_add_middleware` (из `auth_middleware_helpers` → `middleware_auth`)
   и добавить `app.include_router(router_auth)` рядом с
   `include_router(router_blog_api)`. Логика подключения не меняется.
7. `main.py` не трогаем — оба роутера подключаются через
   `setup_auth_static_include`.
8. `__init__.py` пакета — обновить module-docstring под новую структуру
   (заменить упоминание `auth_middleware_helpers.py` на `middleware_auth.py`,
   добавить `api_auth.py`). Реэкспорт `router_auth` не нужен:
   `frontend_auth_include.py` импортирует его напрямую из
   `md_articles.api_auth`. `_user_out` и `UserOut` уже живут в
   `helpers_blog.py` — перенос не требуется.

Уточнение (не противоречит решениям): `/api/blog/current_user` логически
относится к auth и переезжает в `api_auth.py`. В списке оставляемых
в `api_blog.py` блог-роутов его нет; оставление в `api_blog.py` нарушило бы
разделение auth/account vs блог-секций.

## Результат

После задания в репозитории:

- `fastapi-application/md_articles/api_auth.py` — новый файл, содержит
  `router_auth` с 7 роутами (`csrf`, `current_user`, `register`, `login`,
  `logout`, `account_get`, `account_post`).
- `fastapi-application/md_articles/api_blog.py` — почищен: только 7 блог-роутов
  (`sections`, `articles`, `articles/{art_id}`, `art_manage`,
  `art_manage/add_all`, `art_manage/meta`, `art_manage/sync`); неиспользуемые
  импорты убраны; имена роутов сохранены.
- `fastapi-application/md_articles/middleware_auth.py` — переименован из
  `auth_middleware_helpers.py` через `git mv` (история сохраняется);
  содержит только 4 функции: `inject_current_user_middleware`,
  `get_current_user`, `auth_add_middleware`,
  `custom_request_validation_exception_handler`. Module-docstring обновлён
  под новое содержимое.
- `fastapi-application/md_articles/helpers_blog.py` — дополнен 5 секциями
  (auth helpers, password helpers, CSRF helpers, login dependency,
  validation handler); добавлены импорты: `bcrypt`,
  `from fastapi import HTTPException, Request`,
  `from fastapi.responses import JSONResponse`.
- `fastapi-application/md_articles/frontend_auth_include.py` — импорт
  `auth_add_middleware` обновлён на `middleware_auth`; добавлен
  `app.include_router(router_auth)`.
- `fastapi-application/md_articles/__init__.py` — module-docstring обновлён
  под новую структуру.
- `len(main_app.routes) == 42` (без изменений).
- `git status --short` показывает только:
  `R auth_middleware_helpers.py -> middleware_auth.py`,
  `?? fastapi-application/md_articles/api_auth.py`,
  `M fastapi-application/md_articles/api_blog.py`,
  `M fastapi-application/md_articles/helpers_blog.py`,
  `M fastapi-application/md_articles/frontend_auth_include.py`,
  `M fastapi-application/md_articles/__init__.py`. Никаких других файлов.

## Вне рамок

- Изменение URL-неймспейса (префиксов и путей).
- Изменение сигнатур/поведения роутов и хелперов — только перенос кода.
- Правка фронта (`frontend/`, React SPA).
- Изменение моделей (`models.py`), схем (`schema_art.py`, `schema_blog.py`).
- Обновление документации `docs/15_md_articles_package.md` — отдельная
  фаза после кода, в этом задании не делается.
- Миграции, новые зависимости, деплой.

## План фаз

Единица исполнения — фаза: одно делегирование, 1–3 файла, бюджет ~10–15 ходов.
Следующая фаза стартует только после зелёного checkpoint и ревью диффа
оркестратором. Прогресс фазы разработчик фиксирует
в `tasks/current/dev/phaseNN_progress.md`.

| # | Фаза | Исполнитель | Файлы | Что делает | Checkpoint | Бюджет |
|---|---|---|---|---|---|---|
| 1 | Создать api_auth.py | backend-dev | `md_articles/api_auth.py` (новый) | Создать файл с `router_auth` и 7 auth-роутами; импорты из существующих `auth_middleware_helpers` и `helpers_blog` | `python -c "from md_articles.api_auth import router_auth; print(len(router_auth.routes))"` → 7; `ruff check api_auth.py` → exit 0 | ~12 |
| 2 | Очистить api_blog.py + подключить router_auth | backend-dev | `md_articles/api_blog.py`, `md_articles/frontend_auth_include.py` | Удалить 7 auth-роутов и неиспользуемые импорты из api_blog.py; в frontend_auth_include.py добавить `include_router(router_auth)` | `len(main_app.routes) == 42`; curl `/api/blog/articles` 200, `/api/blog/csrf` 200, `POST /api/blog/login` 422; `ruff check` clean | ~10 |
| 3 | Расщепить helpers | backend-dev | `md_articles/auth_middleware_helpers.py`, `md_articles/helpers_blog.py`, `md_articles/api_auth.py` | Перенести секции ниже строки 135 в helpers_blog.py; обновить импорт-блок api_auth.py; обновить docstring auth_middleware_helpers.py | импорты из обоих модулей разрешаются; `len(main_app.routes) == 42`; curl всех auth-эндпоинтов; `ruff check` clean | ~12 |
| 4 | Переименовать файл + обновить импорты + docstring | backend-dev | `git mv auth_middleware_helpers.py → middleware_auth.py`; `md_articles/frontend_auth_include.py`; `md_articles/__init__.py` | git mv; обновить импорт `auth_add_middleware`; обновить module-docstring пакета | `len(main_app.routes) == 42`; `ruff check` clean; `ruff format --check` clean; `git status` показывает только ожидаемые изменения | ~10 |

### Фаза 1: Создать api_auth.py

- Файлы:
  - `fastapi-application/md_articles/api_auth.py` (новый, ~270 строк)
- Контракт (замораживается для следующих фаз):
  - `router_auth = APIRouter(prefix="/api/blog", tags=["auth"])`
  - 7 роутов с именами:
    - `GET /csrf` → `name="auth.csrf"` (тело: `csrf_token`)
    - `GET /current_user` → `name="auth.current_user"` (тело: `current_user`)
    - `POST /register` → `name="auth.register"` (тело: `register_api`,
      payload `RegisterIn`)
    - `POST /login` → `name="auth.login"` (тело: `login_api`, payload `LoginIn`)
    - `POST /logout` → `name="auth.logout"` (тело: `logout_api`)
    - `GET /account` → `name="auth.account_get"` (тело: `account_get_api`)
    - `POST /account` → `name="auth.account_post"` (тело: `account_post_api`,
      form + file)
  - Тела функций и логика — копия 1:1 из текущего `api_blog.py`
    (только замена `@router_blog_api.` на `@router_auth.` и `name=` на новые).
  - Импорты (Phase 1: всё ещё из существующих модулей):
    - `from md_articles.auth_middleware_helpers import (_ERROR_EMAIL_TAKEN, _ERROR_USERNAME_TAKEN, _ensure_csrf_token, _get_request_user, _validation_response, hash_password, login_user, logout_user, require_login_api, validate_csrf_form, validate_csrf_header, verify_password)`
    - `from md_articles.helpers_blog import (_user_out, _is_valid_email, _username_exists, _email_exists, _save_picture)`
    - `from md_articles.models import BlogUser`
    - `from md_articles.schema_blog import LoginIn, RegisterIn`
    - `from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile`
    - `from fastapi.responses import JSONResponse`
    - `from sqlalchemy import select`
    - `from config_log import logF`
    - `from db_core.db_async import CurrentSession`
- Шаги:
  1. Прочитать `api_blog.py` (уже известен).
  2. Скопировать блоки `csrf`, `current_user`, `register`, `login`,
     `logout`, `account_get`, `account_post` (декораторы + тела) в новый
     файл одним `write_file`.
  3. Заменить `@router_blog_api.` на `@router_auth.`.
  4. Заменить `name=` на новые (`auth.*`).
  5. Сформировать импорт-блок по контракту.
- Checkpoint (машинные, без поднятия сервера):
  - `cd fastapi-application && ../.venv/bin/python -c "from md_articles.api_auth import router_auth; print(len(router_auth.routes))"` → `7`
  - `uv run ruff check fastapi-application/md_articles/api_auth.py` → exit 0
- Готовность фазы: файл существует, импорт проходит, `router_auth` содержит
  ровно 7 роутов, ruff чист.

### Фаза 2: Очистить api_blog.py + подключить router_auth

- Файлы:
  - `fastapi-application/md_articles/api_blog.py` (edit: убрать 7 auth-роутов
    и неиспользуемые импорты)
  - `fastapi-application/md_articles/frontend_auth_include.py` (edit: добавить
    `include_router(router_auth)`)
- Контракт:
  - В `api_blog.py` остаются 7 роутов: `sections`, `articles`,
    `articles/{art_id}`, `art_manage`, `art_manage/add_all`,
    `art_manage/meta`, `art_manage/sync`. Имена сохраняются
    (`blog_api.sections`, `blog_api.articles`, `blog_api.article_detail`,
    `blog_api.art_manage`, `blog_api.art_manage_add_all`,
    `blog_api.art_manage_meta`, `blog_api.art_manage_sync`).
  - Удаляются: `csrf`, `current_user`, `register`, `login`, `logout`,
    `account_get`, `account_post` (и их тела).
  - Импорты в `api_blog.py` после чистки:
    - удалить: `LoginIn`, `MetaIn`, `RegisterIn`,
      `_ERROR_EMAIL_TAKEN`, `_ERROR_USERNAME_TAKEN`, `_ensure_csrf_token`,
      `_get_request_user`, `_validation_response`, `hash_password`,
      `login_user`, `logout_user`, `validate_csrf_form`,
      `verify_password`, `Form`, `File`, `UploadFile`, `CurrentSession`,
      `select`, `_save_picture`, `_username_exists`, `_email_exists`,
      `_user_out`, `_is_valid_email`.
    - оставить: `APIRouter`, `Depends`, `HTTPException`, `Query`, `Request`,
      `JSONResponse`, `jsonable_encoder`, `logF`, `os`, `Path`,
      `_allocate_art_id`, `_article_summary`, `_is_complete`,
      `require_login_api`, `validate_csrf_header`, `BlogUser`,
      `ArticleLang`, `get_art`, `get_articles`, `get_registry_error`,
      `get_section`, `render_article`, `save_articles`, `scan_content_art`,
      `sync_registry_with_disk`, `SectionOut`. (`UserOut` используется
      в type hint — НЕ удалять; проверить по факту после edit.)
  - В `frontend_auth_include.py`:
    - добавить `from md_articles.api_auth import router_auth` рядом с
      импортом `router_blog_api`.
    - добавить `app.include_router(router_auth)` сразу после
      `app.include_router(router_blog_api)`.
- Шаги:
  1. Проверить `pgrep -af "uvicorn.*main:main_app"` — если процесс есть,
     переиспользовать (использовать его в Checkpoint). Если нет — поднять
     `cd fastapi-application && ../.venv/bin/uvicorn main:main_app --port 8000 &`.
  2. В `api_blog.py` удалить 7 auth-роутов и неиспользуемые импорты одним
     блоком (правка крупная — единым edit, не несколько).
  3. В `frontend_auth_include.py` добавить импорт `router_auth` и
     `include_router`.
  4. Прогнать Checkpoint-curl.
  5. Если сервер поднимали сами — оставить работать для последующих фаз
     (qa/adversary переиспользуют). Если подобрали чужой — не трогать.
- Checkpoint:
  - `cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"` → `42`
  - `cd fastapi-application && ../.venv/bin/python -c "from md_articles.api_blog import router_blog_api; print(len(router_blog_api.routes))"` → `7`
  - `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/blog/articles` → `200`
  - `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/blog/csrf` → `200`
  - `curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/blog/login -H "Content-Type: application/json" -d '{}'` → `403` (CSRF-мидлварь раньше Pydantic-валидации, baseline)
  - `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/docs` → `200` (регресс)
  - `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/users/get_all_users` → `200` (регресс)
  - `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/dep_examples/single-direct-dependency` → `200` (регресс)
  - `uv run ruff check .` → exit 0
- Готовность фазы: счётчик маршрутов = 42, оба блока auth и blog работают,
  регресс чист, ruff чист.

### Фаза 3: Расщепить helpers

- Файлы:
  - `fastapi-application/md_articles/auth_middleware_helpers.py` (edit:
    удалить секции со строки 135 и ниже; обновить docstring)
  - `fastapi-application/md_articles/helpers_blog.py` (edit: добавить
    перенесённые секции + недостающие импорты)
  - `fastapi-application/md_articles/api_auth.py` (edit: обновить
    импорт-блок)
- Контракт:
  - `auth_middleware_helpers.py` после правки:
    - module-docstring: убрать упоминания CSRF, `require_login_api`,
      `login_user`/`logout_user`, password, login dependency,
      validation handler; оставить только middleware, `auth_add_middleware`,
      `custom_request_validation_exception_handler`.
    - импорты: удалить `bcrypt` (больше не используется в этом файле);
      проверить, что остальные импорты всё ещё нужны.
    - 4 функции: `inject_current_user_middleware`, `get_current_user`,
      `auth_add_middleware`, `custom_request_validation_exception_handler`.
  - `helpers_blog.py` дополняется 5 секциями (после существующих):
    - auth helpers: `login_user`, `logout_user`
    - password helpers: `hash_password`, `verify_password`
    - CSRF helpers: `_ensure_csrf_token`, `validate_csrf_form`,
      `validate_csrf_header`
    - login dependency: `_get_request_user`, `require_login_api`
    - validation handler: `_ERROR_EMAIL_TAKEN`, `_ERROR_USERNAME_TAKEN`,
      `_validation_response`
  - Новые импорты в `helpers_blog.py`: `bcrypt`,
    `from fastapi import HTTPException, Request`,
    `from fastapi.responses import JSONResponse`.
  - `api_auth.py` импорт-блок:
    `from md_articles.auth_middleware_helpers import (...)` →
    `from md_articles.helpers_blog import (...)`. Список импортов тот же
    (всё нужное теперь живёт в `helpers_blog`).
- Шаги:
  1. Удалить всё от разделителя секции `auth helpers` (строка 135) до
     конца файла одним edit.
  2. Обновить module-docstring (сжать до описания только middleware-слоя).
  3. Прочитать `helpers_blog.py` целиком (известен — 81 строка).
  4. Добавить в конец `helpers_blog.py` 5 новых секций с перенесёнными
     функциями, обновить импорт-блок в начале файла.
  5. В `api_auth.py` заменить одну строку импорта
     (`auth_middleware_helpers` → `helpers_blog`) — содержимое списка
     импортов идентично.
  6. Прогнать Checkpoint.
- Checkpoint:
  - `cd fastapi-application && ../.venv/bin/python -c "from md_articles.helpers_blog import login_user, logout_user, hash_password, verify_password, _ensure_csrf_token, validate_csrf_form, validate_csrf_header, _get_request_user, require_login_api, _validation_response, _ERROR_EMAIL_TAKEN, _ERROR_USERNAME_TAKEN; print('OK')"` → `OK`
  - `cd fastapi-application && ../.venv/bin/python -c "from md_articles.auth_middleware_helpers import auth_add_middleware, inject_current_user_middleware, get_current_user, custom_request_validation_exception_handler; print('OK')"` → `OK` (файл ещё не переименован — всё работает)
  - `cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"` → `42`
  - `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/blog/csrf` → `200`
  - `curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/blog/login -H "Content-Type: application/json" -d '{}'` → `403` (CSRF-мидлварь раньше Pydantic-валидации, baseline)
  - `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/blog/articles` → `200`
  - `uv run ruff check .` → exit 0
- Готовность фазы: импорты разрешаются из новых мест, обе зоны (auth +
  blog) работают, app стартует, ruff чист.

### Фаза 4: Переименовать файл + обновить импорты + docstring

- Файлы:
  - `git mv fastapi-application/md_articles/auth_middleware_helpers.py fastapi-application/md_articles/middleware_auth.py`
  - `fastapi-application/md_articles/frontend_auth_include.py` (edit:
    обновить импорт `auth_add_middleware`)
  - `fastapi-application/md_articles/__init__.py` (edit: обновить
    module-docstring)
- Контракт:
  - Файл переименован через `git mv` (история сохраняется; rename
    детектится автоматически).
  - `frontend_auth_include.py`:
    `from md_articles.auth_middleware_helpers import auth_add_middleware` →
    `from md_articles.middleware_auth import auth_add_middleware`.
    Логика функции `setup_auth_static_include` не меняется.
  - `__init__.py`: module-docstring обновлён —
    `auth_middleware_helpers.py` → `middleware_auth.py`, добавлен пункт про
    `api_auth.py` (новый JSON-роутер auth/account под тем же префиксом).
    Реэкспорты не меняются (`__all__` остаётся прежним).
- Шаги:
  1. `git mv fastapi-application/md_articles/auth_middleware_helpers.py fastapi-application/md_articles/middleware_auth.py`.
  2. В `frontend_auth_include.py` обновить одну строку импорта.
  3. В `__init__.py` обновить module-docstring (только текст, без правок
     `__all__`).
  4. Финальный smoke (Checkpoint).
- Checkpoint:
  - `cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"` → `42`
  - `cd fastapi-application && ../.venv/bin/python -c "from md_articles.middleware_auth import auth_add_middleware; print('OK')"` → `OK`
  - `cd fastapi-application && ../.venv/bin/python -c "from md_articles.auth_middleware_helpers import auth_add_middleware"` → `ModuleNotFoundError` (файл переименован — старого пути больше нет; ожидаемо)
  - `cd fastapi-application && ../.venv/bin/python -c "from md_articles.api_auth import router_auth; print(len(router_auth.routes))"` → `7`
  - `cd fastapi-application && ../.venv/bin/python -c "from md_articles.helpers_blog import _user_out; print('OK')"` → `OK`
  - `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/blog/articles` → `200`
  - `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/blog/csrf` → `200`
  - `curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/blog/login -H "Content-Type: application/json" -d '{}'` → `403` (CSRF-мидлварь раньше Pydantic-валидации, baseline)
  - `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/docs` → `200` (регресс)
  - `uv run ruff check .` → exit 0
  - `uv run ruff format --check .` → no changes would be made
  - `git status --short` показывает только:
    `R  fastapi-application/md_articles/auth_middleware_helpers.py -> fastapi-application/md_articles/middleware_auth.py`,
    `?? fastapi-application/md_articles/api_auth.py`,
    `M  fastapi-application/md_articles/api_blog.py`,
    `M  fastapi-application/md_articles/helpers_blog.py`,
    `M  fastapi-application/md_articles/frontend_auth_include.py`,
    `M  fastapi-application/md_articles/__init__.py`. Никаких других файлов.
  - `git log --follow --oneline fastapi-application/md_articles/middleware_auth.py | head -5` — содержит предыдущие коммиты
    `auth_middleware_helpers.py` (история сохранилась через `git mv`).
- Готовность фазы: задание полностью выполнено, можно архивировать.

## Критерии успеха

Проверяются qa по завершении всех фаз; сырые выводы — в `tasks/current/e2e/`.

| # | Критерий | Проверка | Ожидание |
|---|---|---|---|
| 1 | Базовый счётчик маршрутов сохранён | `cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"` | `42` |
| 2 | `api_auth.py` содержит 7 auth-роутов | `cd fastapi-application && ../.venv/bin/python -c "from md_articles.api_auth import router_auth; print(len(router_auth.routes))"` | `7` |
| 3 | `api_blog.py` содержит 7 blog-роутов | `cd fastapi-application && ../.venv/bin/python -c "from md_articles.api_blog import router_blog_api; print(len(router_blog_api.routes))"` | `7` |
| 4 | `middleware_auth.py` импортируется (после rename) | `cd fastapi-application && ../.venv/bin/python -c "from md_articles.middleware_auth import auth_add_middleware, inject_current_user_middleware, get_current_user, custom_request_validation_exception_handler; print('OK')"` | `OK` |
| 5 | `helpers_blog.py` содержит перенесённые хелперы | `cd fastapi-application && ../.venv/bin/python -c "from md_articles.helpers_blog import login_user, logout_user, hash_password, verify_password, _ensure_csrf_token, validate_csrf_form, validate_csrf_header, _get_request_user, require_login_api, _validation_response, _ERROR_EMAIL_TAKEN, _ERROR_USERNAME_TAKEN; print('OK')"` | `OK` |
| 6 | Ruff check чист | `uv run ruff check .` | exit 0 |
| 7 | Формат чист | `uv run ruff format --check .` | no changes would be made |
| 8 | `GET /api/blog/articles` отвечает 200 | `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/blog/articles` | `200` |
| 9 | `GET /api/blog/csrf` отвечает 200 | `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/blog/csrf` | `200` |
| 10 | `POST /api/blog/login` отвечает 403 на пустое тело без CSRF | `curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/blog/login -H "Content-Type: application/json" -d '{}'` | `403` (CSRF-проверка `validate_csrf_header` раньше Pydantic-валидации; baseline-поведение до правки, перенесено 1:1) |
| 11 | `GET /api/blog/account` отвечает 401/403 без авторизации | `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/blog/account` | `401` или `403` |
| 12 | `GET /api/blog/current_user` отвечает 200 без авторизации | `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/blog/current_user` | `200` |
| 13 | `GET /api/blog/sections` отвечает 200 | `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/blog/sections` | `200` |
| 14 | Регресс `/docs` | `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/docs` | `200` |
| 15 | Регресс `/users/get_all_users` | `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/users/get_all_users` | `200` |
| 16 | Регресс `/api/v1/dep_examples/single-direct-dependency` | `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/dep_examples/single-direct-dependency` | `200` |
| 17 | `git status` показывает только ожидаемые изменения | `git status --short` | только `R` rename, `?? api_auth.py`, `M` 4 файлов |
| 18 | История `git log --follow` по переименованному файлу работает | `git log --follow --oneline fastapi-application/md_articles/middleware_auth.py \| head -5` | содержит предыдущие коммиты `auth_middleware_helpers.py` |

## Финальные критерии

1. Каждый критерий успеха (1–18) подтверждён доказательством —
   `e2e/`-заметкой qa, логом или записью в `tasks/current/DEFECTS.md`.
2. `tasks/current/DEFECTS.md` существует только если найдены дефекты;
   все записи не `OPEN`.
3. Adversarial-прогон выполнен, ни одна запись
   `tasks/current/ADVERSARIAL_REVIEW.md` не `PENDING`.
4. `docs/15_md_articles_package.md` в рамки этого задания не входит —
   обновление откладывается; в отчёте о выполнении фиксируется, что
   документация требует отдельного задания.

## Открытые вопросы

Список пуст: все развилки закрыты с пользователем в чате (см.
«Подтверждённые решения»). Уточнение про `/api/blog/current_user` (он
относится к auth, а не к blog, и переезжает в `api_auth.py`) вынесено
в «Подтверждённые решения» отдельным пунктом.

---

# Отчёт о выполнении

- Дата закрытия: 2026-09-06
- Коммит: не создавался (задание закрыто архивированием; правки остались unstaged)

## Итог

Серверный рефакторинг `md_articles` выполнен за 4 фазы: `api_auth.py` создан и подключён, `api_blog.py` очищен до блог-роутов, 5 секций хелперов перенесены из `auth_middleware_helpers.py` в `helpers_blog.py`, файл переименован в `middleware_auth.py` через `git mv` с сохранением истории. Все 18 критериев успеха + end-to-end auth-flow подтверждены qa-прогоном.

## Изменения

| Файл | Суть правки |
|---|---|
| `fastapi-application/md_articles/api_auth.py` (новый) | `router_auth` (prefix `/api/blog`, tags `auth`) с 7 роутами: `csrf`, `current_user`, `register`, `login`, `logout`, `account_get`, `account_post`. Тела 1:1 из старого `api_blog.py`, имена `auth.*`. |
| `fastapi-application/md_articles/api_blog.py` (edit) | Удалены 7 auth-роутов и неиспользуемые импорты (`File`, `Form`, `UploadFile`, `LoginIn`, `RegisterIn`, `CurrentSession`, `select`, `hash_password`, `verify_password`, `login_user`, `logout_user`, `_ERROR_EMAIL_TAKEN`, `_ERROR_USERNAME_TAKEN`, `_ensure_csrf_token`, `_get_request_user`, `_validation_response`, `validate_csrf_form`, `_user_out`, `_is_valid_email`, `_username_exists`, `_email_exists`, `_save_picture`, `BlogUser`); импорт `require_login_api`/`validate_csrf_header` переключён с `auth_middleware_helpers` на `helpers_blog`. Длина: 408 → 224 строк. |
| `fastapi-application/md_articles/frontend_auth_include.py` (edit) | Добавлен импорт `router_auth`; добавлен `app.include_router(router_auth)` рядом с `include_router(router_blog_api)`. |
| `fastapi-application/md_articles/auth_middleware_helpers.py` → `middleware_auth.py` (`git mv`) | Удалены 5 секций (12 имён): `login_user`, `logout_user`, `hash_password`, `verify_password`, `_ensure_csrf_token`, `validate_csrf_form`, `validate_csrf_header`, `_get_request_user`, `require_login_api`, `_ERROR_EMAIL_TAKEN`, `_ERROR_USERNAME_TAKEN`, `_validation_response`. Удалены `bcrypt` и `HTTPException` из импортов. Осталось 4 функции: `inject_current_user_middleware`, `get_current_user`, `auth_add_middleware`, `custom_request_validation_exception_handler`. Длина: 222 → 132 строки. |
| `fastapi-application/md_articles/helpers_blog.py` (edit) | Добавлены 5 секций (12 имён) сверху вниз: auth helpers, password helpers, CSRF helpers, login dependency, validation handler. Добавлены импорты: `bcrypt`, `from fastapi import HTTPException, Request`, `from fastapi.responses import JSONResponse`. Длина: 100 → 181 строки. |
| `fastapi-application/md_articles/__init__.py` (edit) | Module-docstring переписан: `auth_middleware_helpers.py` → `middleware_auth.py`, добавлен пункт про `api_auth.py` (7 эндпоинтов), `api_blog.py` теперь с числом 7 (было 13). `__all__` без изменений. |

## Критерии успеха

| # | Критерий | Результат | Доказательство |
|---|---|---|---|
| 1 | `len(main_app.routes) == 42` | PASS | e2e/qa_block1_imports.log |
| 2 | `len(router_auth.routes) == 7` | PASS | e2e/qa_block1_imports.log |
| 3 | `len(router_blog_api.routes) == 7` | PASS | e2e/qa_block1_imports.log |
| 4 | `from md_articles.middleware_auth import ...` (4 имени) | PASS | e2e/qa_block1_imports.log |
| 5 | `from md_articles.auth_middleware_helpers import ...` → ModuleNotFoundError | PASS | e2e/qa_block1_imports.log |
| 6 | `from md_articles.helpers_blog import (12 имён)` | PASS | e2e/qa_block1_imports.log |
| 7 | Имена `router_auth` = 7 auth.* | PASS | e2e/qa_block2_route_names.log |
| 8 | Имена `router_blog_api` = 7 blog_api.* | PASS | e2e/qa_block2_route_names.log |
| 9 | `uv run ruff check .` → exit 0 | PASS | e2e/qa_block3_lint.log |
| 10 | `uv run ruff format --check .` → no changes | PASS | e2e/qa_block3_lint.log |
| 11 | `GET /api/blog/articles` → 200 | PASS | e2e/qa_block4_curl.log |
| 12 | `GET /api/blog/csrf` → 200 | PASS | e2e/qa_block4_curl.log |
| 13 | `POST /api/blog/login {}` → 403 (CSRF) | PASS | e2e/qa_block4_curl.log |
| 14 | `GET /api/blog/account` (no auth) → 401/403 | PASS (403) | e2e/qa_block4_curl.log |
| 15 | `GET /api/blog/current_user` → 200 | PASS | e2e/qa_block4_curl.log |
| 16 | `GET /api/blog/sections` → 200 | PASS | e2e/qa_block4_curl.log |
| 17 | Регресс `/docs`, `/users/get_all_users`, `/api/v1/dep_examples/single-direct-dependency` (с `foobar: test`) → 200 | PASS | e2e/qa_block4_curl.log |
| 18 | `git status` показывает только ожидаемые изменения | PASS | e2e/qa_block5_git.log |
| 19 | End-to-end auth-flow: csrf → register → login → current_user → account → logout | PASS | e2e/qa_block6_auth_flow.log, e2e/qa_auth_flow.log |

## Дефекты

Не найдены. `DEFECTS.md` не создавался.

## Уточнения спекы по ходу выполнения

- **Критерий №10/13 (`POST /login {}` → 403, не 422 как в спеке).** Backend-dev фазе 2 обнаружил, что `validate_csrf_header` срабатывает раньше Pydantic-валидации, и при пустом теле без CSRF отдаётся 403, а не 422. Спека честно обновлена оркестратором с пояснением, baseline-поведение до правки (тела перенесены 1:1).
- **Расширение зоны фазы 3 на `api_blog.py`.** Backend-dev обнаружил, что блог-роуты `art_manage*` используют `require_login_api` и `validate_csrf_header`, которые оставались импортированы из `auth_middleware_helpers`. После переноса 5 секций в `helpers_blog` приложение перестало стартовать. Оркестратор одобрил расширение зоны одной правкой импорта в `api_blog.py` (вариант A) — минимальное изменение, без расширения контракта.
- **`ruff format --check` на момент завершения фазы 4 показал 3 файла не отформатированы** (api_auth.py, helpers_blog.py, middleware_auth.py — косметика: trailing newlines, пустая строка между функциями). Оркестратор применил `uv run ruff format` для этих 3 файлов сам (правка python-косметики в зоне оркестратора) — финальный формат clean.

## Adversarial-прогон

Не выполнялся — пользователь дал прямое указание «run qa только и архивируй» (adversary пропущен по решению пользователя). Все известные классы регрессов покрыты qa-прогоном: end-to-end auth-flow, CSRF, login dependency, регистрация/логин/logout через перенесённые хелперы.

## Участники

- spec-writer: фаза создания — `tasks/current/REQUIREMENTS.md` с планом 4 фаз.
- backend-dev: фазы 1–4 — создание `api_auth.py`, чистка `api_blog.py`, расщепление helpers, `git mv` + docstring. Прогресс: `tasks/.../dev/phase01_progress.md`–`phase04_progress.md`.
- qa: финальный smoke — `e2e/qa_*.log` (9 файлов) + `e2e/qa_verdict.md` (PASS).
- оркестратор: уточнение спеки по `POST /login` (422→403), одобрение расширения зоны фазы 3 на `api_blog.py`, финальный `uv run ruff format` для 3 файлов, архивирование задания.

## Документация

`docs/15_md_articles_package.md` НЕ обновлялся в этом задании (явно вынесено в «Вне рамок»). Требует отдельного задания: отразить разделение `api_auth.py` / `api_blog.py` и переименование `auth_middleware_helpers.py` → `middleware_auth.py`.
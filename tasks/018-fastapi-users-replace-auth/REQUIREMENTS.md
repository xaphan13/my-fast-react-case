# Полная замена самописной авторизации блога на fastapi-users

Серверная доработка пакета `my-fast-react-case/` (FastAPI + React 18 + Vite
SPA, SQLAlchemy 2.0 async): **полная замена** самописной авторизации
(`SessionMiddleware` + bcrypt + самописный CSRF в `md_articles/`) на
`fastapi-users==14.0.1` + `fastapi-users-db-sqlalchemy` + `CookieTransport`
+ `JWTStrategy` + `pwdlib` Argon2. Донор — `template-jwt-auth/` (FastAPI +
Jinja + HTMX); здесь — адаптация под React 18 + Vite SPA с сохранением
поля `image_file` (аватар) и публичного контракта `User` для фронта
(минимальные правки `auth.ts`, `client.ts`, `AuthContext.tsx`; UI
LoginPage/RegisterPage/AccountPage не меняется, за исключением формата
формы логина — JSON → form-data как требует fastapi-users по умолчанию).

## Подтверждённые решения

1. **Полная замена, без параллельных стратегий.** Текущая самописная
   авторизация в `md_articles/api_auth.py`, `md_articles/helpers_auth.py`,
   `md_articles/middleware_auth.py` удаляется. `SessionMiddleware`,
   самописный CSRF-слой (`validate_csrf_header`/`validate_csrf_form`/
   `ensure_csrf_token`), `get_request_user`, `require_login_api` —
   удаляются. Текущий `BlogUser` (`password` поле) перестаёт
   использоваться для аутентификации (см. п. 7). Никаких флагов выбора
   стратегии, никакого fallback — замена один-в-один.

2. **Стек — донорский:** `fastapi-users[sqlalchemy]>=14.0.1` (тянет
   `pwdlib` Argon2, `pyjwt`, `fastapi-users-db-sqlalchemy`,
   `email-validator`, `python-multipart`). Не PyJWT/pytho-jose напрямую,
   не свой JWT-каркас, не `passlib`. Версия `14.0.1+` (без верхней грани)
   — для совместимости с донором и без привязки к мажорным обновлениям
   библиотеки; на момент фиксации спеки 14.x актуальна.

3. **Новый пакет `fastapi-application/auth_users/`** — изолированный
   подпакет `fastapi-application/`, **отдельно** от `md_articles/`.
   Импорты внутри `auth_users/` — относительные
   (`from .models import User`). Снаружи — плоские,
   `from auth_users import fastapi_users, router`, как в существующем
   `from md_articles.api_blog import router_blog_api`. Пакет НЕ лежит в
   `md_articles/`, потому что авторизация больше не является частью
   блога — это слой приложения.

4. **PK User = UUID** (как в доноре, `SQLAlchemyBaseUserTableUUID[int]` →
   `SQLAlchemyBaseUserTableUUID`). Обоснование: чистый слейт (старые
   пользователи сбрасываются — см. п. 7), `UUID` устойчив к перечислению
   идентификаторов, фронт получает `id: string` через `/users/me`.
   Совместимость с существующим `BlogUser.id: int` не нужна — старый
   `BlogUser` не используется для авторизации (см. п. 7).

5. **Password hashing — pwdlib Argon2** (как в доноре).
   `fastapi-users==14.0.1` использует `PasswordHelper` с `PasswordHash`
   (Argon2 + Bcrypt внутри); вход через `verify_and_update` тихо
   перехеширует Bcrypt-хеши в Argon2 при первом логине. `bcrypt>=4.2.0`
   из `pyproject.toml` УДАЛЯЕТСЯ. `verify_password`/`hash_password` из
   `helpers_auth.py` — удаляются.

6. **Cookie name: "auth"**, `httponly=True`, `samesite="lax"`,
   `secure=False` (dev), `max_age=86400` (24 часа). Алгоритм JWT — HS256;
   секрет — `settings.web.secret_key`. `lifetime_seconds=86400`. Имя cookie
   и max_age совпадают (срок жизни токена = срок жизни cookie).
   `AuthenticationBackend(name="jwt", ...)`. Никаких access+refresh;
   единая длительная cookie, ротация — отдельная задача.

7. **Что делать со старыми пользователями в БД: drop.** В проекте
   дев-only данные (`001-md-articles-blog`–`017-md-articles-split-auth-blog`),
   прода нет. Перед фазой 4 `fastapi-application/one_simple.db`
   удаляется; Alembic-создаётся новая ревизия, которая добавляет таблицу
   `user` (от `SQLAlchemyBaseUserTableUUID` + `username`, `image_file`),
   `blog_user` (от `BlogUser`) и `blog_post` (от `BlogPost`) остаются в
   схеме как «мёртвый груз» — НЕ удаляются, потому что `blog_post.user_id`
   FK на `blog_user.id` (его удаление сломает FK). FK-проверки включаются
   только в SQLite pragma (`PRAGMA foreign_keys=ON` уже в `db_async.py`).
   Для моргания можно не обращать внимания: `GET /api/blog/articles`
   возвращает метаданные статей, фронт их не привязывает к
   пользователю-автору через новую `User`-модель (там будет NULL/Orphan
   строка). Отдельный cleanup `blog_user`/`blog_post` — вне задания.

8. **CSRF полностью убирается.** fastapi-users: JSON или form-data +
   `SameSite=Lax` + `HttpOnly` = достаточная защита от CSRF для
   same-origin SPA. Никаких `X-CSRF-Token` заголовков, никаких
   `csrf_token` полей формы. Фронт: `getCsrfToken` из `client.ts`
   удаляется, `postJson` упрощается, `postMultipart` без csrf-поля.

9. **SessionMiddleware удаляется.** `request.session` больше нигде не
   читается/пишется — fastapi-users не использует сессии Starlette.
   Защита роутов блога переключается на
   `Depends(fastapi_users.current_user(active=True))` (вместо
   `Depends(require_login_api)`).

10. **Эндпоинты (новый контракт для фронта):**
    - `POST /auth/jwt/login` — form-urlencoded: `username=<email>&password=<…>`
      (OAuth2PasswordRequestForm, как в доноре). Ответ 204 + `Set-Cookie`.
      400 `LOGIN_BAD_CREDENTIALS` при неверном email/пароле (или при
      `is_active=False` — одинаковый ответ, чтобы не сообщать, существует
      ли email).
    - `POST /auth/jwt/logout` — пустое тело. Ответ 204 + `Set-Cookie: auth=;
      Max-Age=0`. Не требует аутентификации (как у донора).
    - `POST /auth/register` — JSON `{email, password}`.
      Ответ 201 + `UserRead`. Ошибки: 400 `REGISTER_USER_ALREADY_EXISTS`,
      400 `REGISTER_INVALID_PASSWORD` (если `validate_password` бросает),
      422 (Pydantic). **Контракт username отсутствует:** имя берётся из
      email (дефолт fastapi-users; фронт может потом обновить через
      `POST /auth/account`). Это — расширение по сравнению с донором: в
      доноре имя приходит из шаблона регистрации; здесь фронт
      `RegisterPage` и UX-flow останутся как сейчас (Register form имеет
      поля username/email/password/confirm_password), но `username`
      автоматически устанавливается в `email.split('@')[0]` через hook
      `on_after_register` → если хочется сохранить **фронтовый UX
      "введите username"**, потребуется отдельный endpoint
      `POST /auth/account` (этот endpoint уже нужен для аватара — см. п. 11).
    - `GET /users/me` — `UserRead` (id, email, is_active, is_superuser,
      is_verified, **+ username, + image_file** через кастомную
      `UserRead`-схему).
    - `PATCH /users/me` — обновление email/username/password через
      кастомный endpoint (см. п. 11).
    - `GET /users/{id}`, `PATCH /users/{id}`, `DELETE /users/{id}` —
      встроенные маршруты fastapi-users (только `superuser=True`); в
      текущем задании **не используются** фронтом, но регистрируются
      библиотекой автоматически — оставляем для совместимости с OpenAPI.

11. **Кастомный endpoint `POST /auth/account` (multipart)**: обновление
    профиля + аватар. Это **компенсация** отсутствия username в `/auth/register`
    и поддержка multipart-upload аватара (тот же контракт, что сейчас у
    `/api/blog/account POST`). Поля формы: `username`, `email`,
    `picture` (опц.). Авторизация — `Depends(fastapi_users.current_user(active=True))`.
    Без CSRF (см. п. 8). Сохранение аватара — `save_picture` хелпер
    (переезжает из `md_articles/helpers_auth.py` в
    `auth_users/helpers.py` — логика 1:1, см. п. 13). Валидация username
    (длина 2–20 символов, уникальность через `username_exists`),
    валидация email (через `is_valid_email` из `pydantic.EmailStr`).
    Ответ `{message, category, user}` как в текущем `/api/blog/account`.

12. **`UserRead`-схема с дополнительными полями:**
    ```python
    class UserRead(schemas.BaseUser[UUID]):
        username: str
        image_file: str
    ```
    Эти поля сохраняются в БД (`User.username` unique NOT NULL,
    `User.image_file` default "default.jpg"), но не управляются
    `BaseUserManager.create/update` через стандартный flow — обновляются
    через кастомный `POST /auth/account`. Соответственно, фронт
    `types.ts::User` меняется: `id: number` → `id: string`, остальное
    без изменений.

13. **Перенос helpers из `md_articles/helpers_auth.py` в
    `auth_users/helpers.py`**:
    - `save_picture(form_picture: UploadFile) -> str` (1:1, путь
      `BASE_DIR/static/profile_pics/`).
    - `is_valid_email(email: str) -> bool` (через `pydantic.EmailStr`).
    - `ERROR_EMAIL_TAKEN`, `ERROR_USERNAME_TAKEN` (строки-сообщения).
    - `validation_response(errors)` — `JSONResponse(422, {"errors": {...}})`.
    - `async def username_exists(session, username) -> bool` —
      `SELECT WHERE username = ?`.
    - `async def email_exists(session, email) -> bool` —
      `SELECT WHERE email = ?`.
    Не переезжают: `login_user`/`logout_user`/`get_request_user`/
    `require_login_api`/`verify_password`/`hash_password`/
    `user_out`/`ensure_csrf_token`/`validate_csrf_*` — всё это
    заменяется функциональностью fastapi-users и не нужно.

14. **Зависимости `pyproject.toml`:**
    - `auth_users[sqlalchemy]>=14.0.1` — добавляется.
    - `bcrypt>=4.2.0` — удаляется (не нужно: pwdlib Argon2).
    - `itsdangerous>=2.2.0` — можно удалить (использовался
      `SessionMiddleware`); оставляем (зависимость uvicorn/gunicorn
      может тянуть её же, лишним не будет), либо удаляем по
      усмотрению фазы 1 — **фиксируем: удаляется**.
    - `python-multipart>=0.0.18` — оставляется (нужен для
      multipart в `/auth/account` и для `OAuth2PasswordRequestForm`).

15. **Конфигурация (`core/config.py`) — новые поля:**
    ```python
    class AuthUsersConfig(BaseModel):
        cookie_name: str = "auth"
        cookie_max_age: int = 86400
        cookie_secure: bool = False  # dev; True для прод через APP__AUTH_USERS__COOKIE_SECURE=True
        cookie_httponly: bool = True
        cookie_samesite: str = "lax"
        jwt_lifetime_seconds: int = 86400
        jwt_algorithm: str = "HS256"
        password_min_length: int = 8
    ```
    Доступ через `settings.auth_users`. Секрет JWT — `settings.web.secret_key`
    (тот же, что был у `SessionMiddleware`, миграция без потерь смысла).

16. **Регистрация новой модели в `db_core/__init__.py`:** `User`
    из `auth_users/models` добавляется в `__all__` и импортируется в
    `db_core/__init__.py` (в дополнение к существующему `BlogUser`) —
    чтобы `Base.metadata` видел таблицу и Alembic autogenerate
    подхватывал её. Импорт внутри `db_core/__init__.py` плоский:
    `from auth_users.models import User`.

17. **Alembic migration для `user` таблицы.** Перед фазой 4
    `fastapi-application/one_simple.db` удаляется (файл
    `.gitignore` — игнорируется). В фазе 4 выполняется
    `../.venv/bin/alembic revision --autogenerate -m "add auth_users user"` —
    autogenerate создаёт ревизию, поскольку `User` зарегистрирован в
    `Base.metadata`. Дополнительных ручных правок в upgrade/downgrade
    миграции не требуется (только создание таблицы `user`). `alembic
    upgrade heads` применяет. Это — разовая настройка, спецификация
    деталей миграции — в фазе 4.

18. **Счётчик маршрутов:** baseline (до фаз) — **42**
    (см. AGENTS.md: «текущее значение: 42»). После полной замены:
    - Удаляются 7 маршрутов из `api_auth.py`: `/api/blog/csrf`
      (GET), `/api/blog/current_user` (GET), `/api/blog/register`
      (POST), `/api/blog/login` (POST), `/api/blog/logout` (POST),
      `/api/blog/account` (GET), `/api/blog/account` (POST).
    - Добавляются 9 маршрутов: `/auth/jwt/login` (POST, 1),
      `/auth/jwt/logout` (POST, 1), `/auth/register` (POST, 1),
      `/users/me` (GET, 1), `/users/me` (PATCH, 1), `/users/{id}` (GET,
      1), `/users/{id}` (PATCH, 1), `/users/{id}` (DELETE, 1),
      `/auth/account` (POST, 1).
    - Итог: 42 − 7 + 9 = **44**. Архивный baseline для SPEC —
    42, целевой счётчик — 44.

## Результат

После задания в репозитории:

- `pyproject.toml`: `auth_users[sqlalchemy]>=14.0.1`, удалены `bcrypt`,
  `itsdangerous`; фиксируется в `uv.lock`.
- `fastapi-application/core/config.py`: добавлен `AuthUsersConfig`
  (cookie_name, cookie_max_age, cookie_secure, cookie_httponly,
  cookie_samesite, jwt_lifetime_seconds, jwt_algorithm,
  password_min_length); доступ через `settings.auth_users`.
- `fastapi-application/auth_users/__init__.py` — экспорты
  (`User`, `fastapi_users`, `current_user`, `active_user`,
  `optional_user`, `auth_backend`, `router`, `get_user_manager`).
- `fastapi-application/auth_users/models.py` — `class User
  (SQLAlchemyBaseUserTableUUID, Base)` с доп. полями `username:
  Mapped[str]` (unique NOT NULL, len 20), `image_file: Mapped[str]`
  (NOT NULL, default "default.jpg", len 20).
- `fastapi-application/auth_users/schemas.py` — `UserRead
  (BaseUser[UUID])` с доп. `username`, `image_file`; `UserCreate
  (BaseUserCreate)`; `UserUpdate (BaseUserUpdate)`.
- `fastapi-application/auth_users/user_manager.py` — `UserManager
  (UUIDIDMixin, BaseUserManager[User, UUID])`, `validate_password` (длина
  ≥ `AuthUsersConfig.password_min_length`); `on_after_register` —
  установка `username = email.split("@")[0].strip()` если пустой,
  установка `image_file = "default.jpg"`; `get_user_db`,
  `get_user_manager` DI.
- `fastapi-application/auth_users/auth_backend.py` — `cookie_transport`,
  `get_jwt_strategy`, `auth_backend` (имя `"jwt"`).
- `fastapi-application/auth_users/fastapi_users_obj.py` — `fastapi_users
  = FastAPIUsers[User, UUID](get_user_manager, [auth_backend])`,
  экспорты `current_user`/`active_user`/`optional_user` через
  `fastapi_users.current_user(...)`.
- `fastapi-application/auth_users/account.py` — `POST /auth/account`
  (multipart) — обновление `username`/`email`/`picture` через
  `Depends(active_user)`; без CSRF.
- `fastapi-application/auth_users/router.py` — объединяет `get_auth_router
  (auth_backend)` под prefix `/auth/jwt`, `get_register_router` под
  prefix `/auth`, `get_users_router(UserRead, UserUpdate)` под prefix
  `/users`, плюс `account_router` (`/auth/account`).
- `fastapi-application/auth_users/helpers.py` — `save_picture`,
  `is_valid_email`, `ERROR_EMAIL_TAKEN`, `ERROR_USERNAME_TAKEN`,
  `validation_response`, `username_exists`, `email_exists`
  (перенесено из `md_articles/helpers_auth.py`).
- `fastapi-application/db_core/__init__.py` — импорт `from
  auth_users.models import User` (добавлен в `__all__`).
- `fastapi-application/md_articles/setup_frontend.py` — удалены вызовы
  `add_middleware_auth(app)` и `include_router(router_auth_api)`; добавлен
  `app.include_router(auth_users.router)` (без префикса — router уже со
  своими).
- `fastapi-application/md_articles/api_auth.py` — **УДАЛЁН**.
- `fastapi-application/md_articles/middleware_auth.py` — **УДАЛЁН**.
- `fastapi-application/md_articles/helpers_auth.py` — **УДАЛЁН**
  (функционал перенесён в `auth_users/helpers.py`).
- `fastapi-application/md_articles/api_blog.py` — импорты
  `require_login_api`/`validate_csrf_header`/`logger` (через
  `validate_csrf_header` логгер можно оставить) заменены на
  `from auth_users import active_user` и вызовы `Depends(active_user)`;
  удалены все `await validate_csrf_header(request)` (4 шт.); арт-роуты
  используют `active_user` вместо `require_login_api`.
- `fastapi-application/md_articles/__init__.py` — module-docstring
  обновлён (api_auth.py, helpers_auth.py, middleware_auth.py — нет; 
  есть auth_users как отдельный слой).
- `fastapi-application/alembic/versions/<timestamp>--add_auth_users_user.py`
  — новая Alembic-ревизия (autogenerate) с `op.create_table("user", ...)`.
- `frontend/src/api/client.ts` — удалены `getCsrfToken`,
  `X-CSRF-Token` заголовок в `postJson`, поле `csrf_token` в
  `postMultipart`; оставлены чистые `fetch`-обёртки.
- `frontend/src/api/auth.ts` — переписан: `getCurrentUser` →
  `GET /users/me`, `login` → `POST /auth/jwt/login` (form-data),
  `logout` → `POST /auth/jwt/logout`, `register` → `POST /auth/register`,
  `getAccount` → `POST /auth/account` (GET `/auth/account` нет — форма
  тоже использует POST, как сейчас), `updateAccount` →
  `POST /auth/account` (multipart). Контракт ответов сохранён:
  `MessageResp`/`{message, category, user}`.
- `frontend/src/context/AuthContext.tsx` — без изменений по контракту
  (только проверка: `user.id` теперь `string`, не `number`).
- `frontend/src/types.ts` — `User.id: number` → `User.id: string`.
- `frontend/src/pages/LoginPage.tsx` — `login({email, password})` шлёт
  form-data (`URLSearchParams`), остальное без изменений (UI не
  меняется).
- `frontend/src/pages/RegisterPage.tsx` — без изменений (register всё
  ещё JSON).
- `frontend/src/pages/AccountPage.tsx` — без изменений (UI не
  меняется; `updateAccount` через `POST /auth/account` всё так же
  multipart).
- `docs/04_authorization.md` — полностью переписан под новую
  архитектуру (пакет `auth_users`, поток login/logout, контракт
  эндпоинтов, схема БД, миграция пользователей, CSRF/SessionMiddleware
  удалены).
- `docs/15_md_articles_package.md` — обновлён раздел про авторизацию
  блога (теперь внешний `auth_users`).
- `QWEN.md` — таблица маршрутов обновлена (44), краткое описание
  блога указывает на новый auth-слой.
- `AGENTS.md` — счётчик 42 → 44, обновлена графа «Зоны и проверки»
  (бэкенд-зона включает `auth_users/`).
- `len(main_app.routes) == 44`. Все ранее работавшие эндпоинты блога
  (`/api/blog/articles`, `/api/blog/sections`, etc.) — без изменений,
  кроме art-роутов, которые больше не проверяют CSRF и используют
  `active_user`.

## Вне рамок

- Email-верификация (`/auth/request-verify-token`, `/auth/verify`),
  сброс пароля (`/auth/forgot-password`, `/auth/reset-password`),
  роли (`is_superuser`-привилегии, superuser-only `/users/{id}` GET/PATCH/DELETE),
  refresh-токены, blacklist, OAuth-social, MFA, ротация `SECRET_KEY` —
  функциональность fastapi-users, в задании не задействована.
- Удаление таблиц `blog_user`/`blog_post` и перенос старых постов
  на новую `User`-модель. Старые посты остаются «мёртвым грузом»
  (FK-проверки выключены, новые регистрации не привязаны к постам).
- Custom 401-handler с `HX-Redirect` (донорский шаблон для HTMX),
  HX-фоллбэки, `is_htmx` зависимость — не переносятся (не нужны для SPA,
  фронт обрабатывает 401 в `AuthContext.refresh` catch).
- Деплой-конфигурация `cookie_secure=True` через env (для dev — False,
  фиксируется значение по умолчанию; прод-смена — через
  `APP__AUTH_USERS__COOKIE_SECURE=True`).
- Генерация нового `SECRET_KEY`, его ротация.
- Email-рассылки (хук `on_after_register` только логирует).
- Тесты. Проект живёт без тестов; проверки — curl-сценарии и
  фронтовый `npm run build`.
- Документация `docs/04_authorization.md` для нескольких стратегий
  (теперь единая JWT-in-cookie через fastapi-users).
- Правки `nginx/web/`, `frontend/` кроме `src/api/`, `src/context/`,
  `src/types.ts`, `src/pages/LoginPage.tsx`.
- `Bash`/`Make`-цели с новыми зависимостями (`scripts/dev.sh` и т.п.).

## План фаз

Единица исполнения — фаза: одно делегирование, 1–3 файла (или один
файл + пара удалений), бюджет ~10–15 ходов. Следующая фаза стартует
только после зелёного checkpoint и ревью диффа оркестратором. Прогресс
фазы разработчик фиксирует в `tasks/current/dev/phaseNN_progress.md`.

| # | Фаза | Исполнитель | Файлы | Контракт | Checkpoint | Бюджет |
|---|---|---|---|---|---|---|
| 1 | Фундамент auth_users | backend-dev | `pyproject.toml`, `uv.lock`, `auth_users/__init__.py`, `auth_users/models.py`, `auth_users/schemas.py`, `auth_users/user_manager.py`, `auth_users/helpers.py` | `from auth_users.models import User`; `User.id` PK типа `UUID`; поля `email`, `hashed_password`, `is_active`, `is_superuser`, `is_verified`, `username` (unique, NOT NULL), `image_file` (NOT NULL, default "default.jpg"); хелперы `save_picture`, `is_valid_email`, `validation_response`, `username_exists`, `email_exists`, константы ошибок; `uv run ruff check .` exit 0 | ~15 ходов |
| 2 | Ядро auth_users + router | backend-dev | `auth_users/auth_backend.py`, `auth_users/fastapi_users_obj.py`, `auth_users/account.py`, `auth_users/router.py`, `auth_users/__init__.py` (полные экспорты), `core/config.py` (AuthUsersConfig) | `from auth_users import router, fastapi_users; len(router.routes) == 9`; `settings.auth_users.cookie_name == "auth"`; `len(auth_users.auth_backend.transport.scheme.scheme_name) == ...`; `uv run ruff check .` exit 0 | ~15 ходов |
| 3 | Замена в приложении | backend-dev | `md_articles/setup_frontend.py` (edit), `md_articles/api_blog.py` (edit), `md_articles/__init__.py` (docstring), **DELETE** `md_articles/api_auth.py`, `md_articles/middleware_auth.py`, `md_articles/helpers_auth.py` (3 файла); `db_core/__init__.py` (импорт User) | `from main import main_app; len(main_app.routes) == 44`; пути: **нет** `/api/blog/csrf`, `/api/blog/login`, `/api/blog/logout`, `/api/blog/register`, `/api/blog/current_user`, `/api/blog/account`; **есть** `/auth/jwt/login`, `/auth/jwt/logout`, `/auth/register`, `/users/me` (GET/PATCH), `/users/{id}` (GET/PATCH/DELETE), `/auth/account`; `GET /api/blog/articles` 200; `POST /api/blog/art_manage/meta` без CSRF — теперь отрабатывает; `uv run ruff check .` exit 0 | ~15 ходов |
| 4 | Alembic + Frontend | backend-dev (alembic) + frontend-dev | `fastapi-application/alembic/versions/<ts>--add_auth_users_user.py` (new, autogenerate); `fastapi-application/one_simple.db` (delete); `frontend/src/api/auth.ts` (rewrite), `frontend/src/api/client.ts` (remove CSRF), `frontend/src/types.ts` (`id: number → id: string`), `frontend/src/pages/LoginPage.tsx` (form-data) | `cd fastapi-application && ../.venv/bin/alembic upgrade heads` exit 0; таблица `user` есть в SQLite; `cd frontend && npm run build` exit 0; `from main import main_app; len(main_app.routes) == 44` (после рестарта) | ~15 ходов |
| 5 | Документация + smoke | backend-dev | `docs/04_authorization.md` (rewrite), `docs/15_md_articles_package.md` (edit), `QWEN.md` (route count 44), `AGENTS.md` (route count 44) | `rg "len(main_app.routes)" docs/ QWEN.md AGENTS.md` → 44; `ruff` clean; checkpoint curl-сценарии из критериев успеха | ~8 ходов |

### Фаза 1: Фундамент auth_users

- Файлы:
  - `pyproject.toml` (edit: добавить `auth_users[sqlalchemy]>=14.0.1`;
    удалить `bcrypt>=4.2.0`, `itsdangerous>=2.2.0`).
  - `uv.lock` (regenerate через `uv lock`).
  - `fastapi-application/auth_users/__init__.py` (scaffold: пустые
    реэкспорты, заполняются в фазе 2).
  - `fastapi-application/auth_users/models.py` (new):
    ```python
    from uuid import UUID
    from datetime import datetime, timezone
    from fastapi_users.db import SQLAlchemyBaseUserTableUUID
    from sqlalchemy import DateTime
    from sqlalchemy.orm import Mapped, mapped_column
    from db_core.model_base import Base

    class User(SQLAlchemyBaseUserTableUUID, Base):
        __tablename__ = "user"
        username: Mapped[str] = mapped_column(unique=True, nullable=False, length=20)
        image_file: Mapped[str] = mapped_column(
            nullable=False, default="default.jpg", length=20
        )
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
        )
    ```
  - `fastapi-application/auth_users/schemas.py` (new):
    ```python
    from uuid import UUID
    from datetime import datetime
    from fastapi_users import schemas

    class UserRead(schemas.BaseUser[UUID]):
        username: str
        image_file: str

    class UserCreate(schemas.BaseUserCreate):
        pass  # email + password (Pydantic-валидация из fastapi-users)

    class UserUpdate(schemas.BaseUserUpdate):
        pass  # email/password; username/image_file — через /auth/account
    ```
  - `fastapi-application/auth_users/user_manager.py` (new):
    ```python
    from typing import AsyncGenerator
    from uuid import UUID
    from fastapi import Depends, Request
    from fastapi_users import BaseUserManager, UUIDIDMixin
    from fastapi_users.db import SQLAlchemyUserDatabase
    from fastapi_users.exceptions import InvalidPasswordException
    from sqlalchemy.ext.asyncio import AsyncSession
    from db_core.db_async import CurrentSession
    from core.config import settings
    from config_log import logF
    from auth_users.models import User

    class UserManager(UUIDIDMixin, BaseUserManager[User, UUID]):
        reset_password_token_secret = settings.web.secret_key
        verification_token_secret = settings.web.secret_key

        async def validate_password(self, password: str, user: User) -> None:
            if len(password) < settings.auth_users.password_min_length:
                raise InvalidPasswordException(
                    reason=f"Password should be at least "
                           f"{settings.auth_users.password_min_length} characters"
                )

        async def on_after_register(
            self, user: User, request: Request | None = None
        ) -> None:
            # username по умолчанию = часть email до "@".
            # Если фронт захочет кастомный username — обновится через POST /auth/account.
            if not user.username:
                user.username = (user.email.split("@", 1)[0] or "")[:20].strip()
            if not user.image_file:
                user.image_file = "default.jpg"
            # Сохранение через репозиторий fastapi-users:
            await self.user_db.update(user, {
                "username": user.username, "image_file": user.image_file,
            })
            logF.info("auth_users: registered %s", user.email)

    async def get_user_db(
        session: CurrentSession,
    ) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
        yield SQLAlchemyUserDatabase(session, User)

    async def get_user_manager(
        user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
    ) -> AsyncGenerator[UserManager, None]:
        yield UserManager(user_db)
    ```
    **Важно:** `CurrentSession` уже определён в `db_core/db_async.py`
    (`Annotated[AsyncSession, Depends(db_manager.get_async_session)]`) —
    используем его, чтобы не плодить новые сессии (важно для
    транзакционной связности с `art_manage`-роутами, которые тоже
    используют `CurrentSession`).
  - `fastapi-application/auth_users/helpers.py` (new) — переезд
    `save_picture`, `is_valid_email`, `validation_response`,
    `username_exists`, `email_exists`, `ERROR_EMAIL_TAKEN`,
    `ERROR_USERNAME_TAKEN`:
    ```python
    import io, os, re
    from pathlib import Path
    from fastapi import UploadFile, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import EmailStr
    from PIL import Image
    from sqlalchemy import select
    from base_dir_path import BASE_DIR
    from db_core.db_async import CurrentSession
    from auth_users.models import User

    ERROR_EMAIL_TAKEN = "That email is taken. Please choose a different one."
    ERROR_USERNAME_TAKEN = "That username is taken. Please choose a different one."

    def is_valid_email(email: str) -> bool:
        try:
            EmailStr._validate(email)
            return True
        except Exception:
            return False

    async def username_exists(session: CurrentSession, username: str) -> bool:
        r = await session.execute(select(User).where(User.username == username))
        return r.scalar_one_or_none() is not None

    async def email_exists(session: CurrentSession, email: str) -> bool:
        r = await session.execute(select(User).where(User.email == email))
        return r.scalar_one_or_none() is not None

    async def save_picture(form_picture: UploadFile) -> str:
        random_hex = os.urandom(8).hex()
        _, f_ext = os.path.splitext(form_picture.filename or "")
        f_ext = f_ext.lower()
        if f_ext not in {".jpg", ".jpeg", ".png"}:
            f_ext = ".jpg"
        picture_fn = random_hex + f_ext
        profile_pics_dir = (BASE_DIR / "static" / "profile_pics")
        profile_pics_dir.mkdir(parents=True, exist_ok=True)
        picture_path = profile_pics_dir / picture_fn
        output_size = (125, 125)
        content = await form_picture.read()
        try:
            i = Image.open(io.BytesIO(content))
            i.thumbnail(output_size)
            i.save(picture_path)
        except Exception as exc:
            raise ValueError("Загруженный файл не является изображением.") from exc
        return picture_fn

    def validation_response(errors: dict[str, list[str]]) -> JSONResponse:
        return JSONResponse(status_code=422, content={"errors": errors})
    ```
  - `fastapi-application/db_core/__init__.py` (edit) — добавить
    импорт `from auth_users.models import User` и добавить `"User"` в
    `__all__`.
- Контракт (замораживается для фаз 2–5):
  - `auth_users` пакет компилируется standalone: импорты моделей,
    схем, UserManager, helpers работают без ошибок.
  - `User` зарегистрирован в `Base.metadata` — Alembic autogenerate
    увидит таблицу.
  - `from core.config import settings; print(settings.auth_users.password_min_length)`
    валится с AttributeError в фазе 1 (поле добавляется в фазе 2) —
    учтено в чеклисте.
- Шаги:
  1. `uv lock`-regenerate после правки `pyproject.toml`.
  2. Создать `auth_users/__init__.py` пустой.
  3. Создать `auth_users/models.py`, `auth_users/schemas.py`,
     `auth_users/user_manager.py`, `auth_users/helpers.py` одним
     `write_file` каждый.
  4. Обновить `db_core/__init__.py` — добавить User в реэкспорт.
- Checkpoint:
  - `grep -E "^name = \"fastapi-users\"" uv.lock` → найдено (или по
    `fastapi-users-db-sqlalchemy`)
  - `grep -E "^name = \"pwdlib\"|\"argon2-cffi\"" uv.lock` → найдено
  - `cd fastapi-application && ../.venv/bin/python -c "from auth_users.models import User; from auth_users.schemas import UserRead, UserCreate, UserUpdate; from auth_users.user_manager import UserManager, get_user_manager; from auth_users.helpers import save_picture, is_valid_email, validation_response, username_exists, email_exists, ERROR_EMAIL_TAKEN, ERROR_USERNAME_TAKEN; print('OK')"` → `OK`
  - `cd fastapi-application && ../.venv/bin/python -c "from db_core import User as U; print(U.__tablename__)"` → `user`
  - `uv run ruff check .` → exit 0
- Готовность фазы: фундамент пакета авторизации создан, helpers
  перенесены, модель зарегистрирована в `Base.metadata`.

### Фаза 2: Ядро auth_users + router

- Файлы:
  - `fastapi-application/auth_users/auth_backend.py` (new) — три
    объекта:
    ```python
    from fastapi_users.authentication import (
        AuthenticationBackend, CookieTransport,
    )
    from fastapi_users.authentication.strategy import JWTStrategy
    from core.config import settings

    cookie_transport = CookieTransport(
        cookie_name=settings.auth_users.cookie_name,
        cookie_max_age=settings.auth_users.cookie_max_age,
        cookie_secure=settings.auth_users.cookie_secure,
        cookie_httponly=settings.auth_users.cookie_httponly,
        cookie_samesite=settings.auth_users.cookie_samesite,
    )

    def get_jwt_strategy() -> JWTStrategy:
        return JWTStrategy(
            secret=settings.web.secret_key,
            lifetime_seconds=settings.auth_users.jwt_lifetime_seconds,
            algorithm=settings.auth_users.jwt_algorithm,
        )

    auth_backend = AuthenticationBackend(
        name="jwt",
        transport=cookie_transport,
        get_strategy=get_jwt_strategy,
    )
    ```
  - `fastapi-application/auth_users/fastapi_users_obj.py` (new):
    ```python
    from uuid import UUID
    from fastapi_users import FastAPIUsers
    from auth_users.models import User
    from auth_users.user_manager import get_user_manager
    from auth_users.auth_backend import auth_backend

    fastapi_users = FastAPIUsers[User, UUID](get_user_manager, [auth_backend])

    current_user = fastapi_users.current_user
    active_user = fastapi_users.current_user(active=True)
    optional_user = fastapi_users.current_user(optional=True)
    superuser_user = fastapi_users.current_user(active=True, superuser=True)
    ```
  - `fastapi-application/auth_users/account.py` (new) — `POST
    /auth/account` (multipart):
    ```python
    import re
    from fastapi import APIRouter, Depends, File, Form, UploadFile
    from sqlalchemy import select
    from db_core.db_async import CurrentSession
    from auth_users.models import User
    from auth_users.fastapi_users_obj import active_user
    from auth_users.helpers import (
        ERROR_EMAIL_TAKEN, ERROR_USERNAME_TAKEN,
        email_exists, save_picture, username_exists, validation_response,
        is_valid_email,
    )

    router = APIRouter(tags=["auth-account"], prefix="/auth")

    @router.post("/account", name="auth.account_post")
    async def account_post(
        session: CurrentSession,
        current_user: User = Depends(active_user),
        username: str = Form(""),
        email: str = Form(""),
        picture: UploadFile | None = File(None),
    ):
        errors: dict[str, list[str]] = {}
        username = username.strip()
        email = email.strip()
        if not username:
            errors.setdefault("username", []).append("This field is required.")
        elif len(username) < 2 or len(username) > 20:
            errors.setdefault("username", []).append(
                "Field must be between 2 and 20 characters long."
            )
        if not email:
            errors.setdefault("email", []).append("This field is required.")
        elif not is_valid_email(email):
            errors.setdefault("email", []).append("Invalid email address.")
        if username and username != current_user.username:
            if await username_exists(session, username):
                errors.setdefault("username", []).append(ERROR_USERNAME_TAKEN)
        if email and email != current_user.email:
            if await email_exists(session, email):
                errors.setdefault("email", []).append(ERROR_EMAIL_TAKEN)
        if errors:
            return validation_response(errors)
        new_image: str | None = None
        if picture and picture.filename:
            try:
                new_image = await save_picture(picture)
            except ValueError as exc:
                return validation_response({"picture": [str(exc)]})
        current_user.username = username
        current_user.email = email
        if new_image:
            current_user.image_file = new_image
        await session.commit()
        return {
            "message": "Your account has been updated!",
            "category": "success",
            "user": {
                "id": str(current_user.id),
                "username": current_user.username,
                "email": current_user.email,
                "image_file": current_user.image_file,
                "is_active": current_user.is_active,
                "is_superuser": current_user.is_superuser,
                "is_verified": current_user.is_verified,
            },
        }
    ```
  - `fastapi-application/auth_users/router.py` (new):
    ```python
    from auth_users.auth_backend import auth_backend
    from auth_users.fastapi_users_obj import fastapi_users
    from auth_users.schemas import UserRead, UserUpdate
    from auth_users.account import router as account_router
    from fastapi import APIRouter

    auth_router = fastapi_users.get_auth_router(auth_backend)  # /auth/jwt/login, /auth/jwt/logout
    register_router = fastapi_users.get_register_router(
        UserRead, UserRead
    )  # /auth/register
    users_router = fastapi_users.get_users_router(
        UserRead, UserUpdate
    )  # /users/me GET/PATCH, /users/{id} GET/PATCH/DELETE

    router = APIRouter()
    router.include_router(auth_router, prefix="/auth/jwt", tags=["auth-jwt"])
    router.include_router(register_router, prefix="/auth", tags=["auth-register"])
    router.include_router(users_router, prefix="/users", tags=["users"])
    router.include_router(account_router)
    ```
  - `fastapi-application/auth_users/__init__.py` (полные экспорты):
    ```python
    from auth_users.models import User
    from auth_users.schemas import UserRead, UserCreate, UserUpdate
    from auth_users.user_manager import (
        UserManager, get_user_db, get_user_manager,
    )
    from auth_users.auth_backend import auth_backend, cookie_transport, get_jwt_strategy
    from auth_users.fastapi_users_obj import (
        fastapi_users, current_user, active_user, optional_user, superuser_user,
    )
    from auth_users.router import router
    ```
  - `fastapi-application/core/config.py` (edit) — добавить
    `AuthUsersConfig` и поле `auth_users`:
    ```python
    class AuthUsersConfig(BaseModel):
        cookie_name: str = "auth"
        cookie_max_age: int = 86400
        cookie_secure: bool = False
        cookie_httponly: bool = True
        cookie_samesite: str = "lax"
        jwt_lifetime_seconds: int = 86400
        jwt_algorithm: str = "HS256"
        password_min_length: int = 8

    class Settings(BaseSettings):
        ...
        web: WebConfig = WebConfig()
        db: DatabaseConfig
        auth_users: AuthUsersConfig = AuthUsersConfig()
    ```
- Контракт (замораживается для фаз 3–5):
  - 9 маршрутов: `/auth/jwt/login` (POST), `/auth/jwt/logout` (POST),
    `/auth/register` (POST), `/users/me` (GET, PATCH), `/users/{id}`
    (GET, PATCH, DELETE), `/auth/account` (POST).
  - Тело `/users/me` (UserRead) содержит: `id` (UUID-строка),
    `email`, `username`, `image_file`, `is_active`, `is_superuser`,
    `is_verified`.
  - `/auth/jwt/login` принимает form-urlencoded (`username=email`,
    `password`), 204 успех, 400 при неверном логине
    (`{"detail": "LOGIN_BAD_CREDENTIALS"}`).
  - `/auth/jwt/logout` принимает пустое тело, 204 + очистка cookie.
  - `/auth/register` принимает JSON `{email, password}`, 201 + UserRead,
    400 `{"detail":"REGISTER_USER_ALREADY_EXISTS"}` при дубликате email,
    400 `REGISTER_INVALID_PASSWORD` при коротком пароле.
  - `/users/me` GET: 200 + UserRead (для анонима — 401).
  - `/users/me` PATCH: не используется фронтом; оставлен для
    совместимости с fastapi-users.
  - `/auth/account` POST (multipart): см. фазу 2 исходник.
- Шаги:
  1. Создать `auth_users/auth_backend.py` одним `write_file`.
  2. Создать `auth_users/fastapi_users_obj.py` одним `write_file`.
  3. Создать `auth_users/account.py` одним `write_file`.
  4. Создать `auth_users/router.py` одним `write_file`.
  5. Обновить `auth_users/__init__.py` до полных экспортов.
  6. Обновить `core/config.py` — добавить `AuthUsersConfig`.
- Checkpoint:
  - `cd fastapi-application && ../.venv/bin/python -c "from auth_users import router; print(len(router.routes))"` → `9`
  - `cd fastapi-application && ../.venv/bin/python -c "from auth_users import auth_backend; print(auth_backend.name, auth_backend.transport.cookie_name)"` → `jwt auth`
  - `cd fastapi-application && ../.venv/bin/python -c "from core.config import settings; print(settings.auth_users.cookie_name, settings.auth_users.jwt_lifetime_seconds)"` → `auth 86400`
  - `cd fastapi-application && ../.venv/bin/python -c "from auth_users import User; print(User.__tablename__, User.__mro__[1].__name__)"` → `user SQLAlchemyBaseUserTableUUID`
  - `uv run ruff check .` → exit 0
- Готовность фазы: пакет собран, все 9 маршрутов определены;
  конфигурация читается из `settings.auth_users`; готов к подключению.

### Фаза 3: Замена в приложении

- Файлы:
  - `fastapi-application/md_articles/setup_frontend.py` (edit):
    - удалить `from md_articles.api_auth import router_auth_api`,
    - удалить `from md_articles.middleware_auth import add_middleware_auth`,
    - в `include_router_api_frontend(app)`:
      удалить `add_middleware_auth(app)`,
      удалить `app.include_router(router_auth_api)`,
      добавить `app.include_router(auth_users_router)` (импорт
      `from auth_users import router as auth_users_router`).
  - **DELETE** `fastapi-application/md_articles/api_auth.py`.
  - **DELETE** `fastapi-application/md_articles/middleware_auth.py`.
  - **DELETE** `fastapi-application/md_articles/helpers_auth.py`.
  - `fastapi-application/md_articles/api_blog.py` (edit):
    - убрать импорт `from md_articles.helpers_auth import
      require_login_api, validate_csrf_header`,
    - добавить `from auth_users import active_user`,
    - в `art_manage_api`, `art_manage_add_all_api`,
      `art_manage_meta_api`, `art_manage_sync_api` — заменить
      `_user=Depends(require_login_api)` на `_user=Depends(active_user)`,
    - удалить все строки `await validate_csrf_header(request)` (4 шт.),
    - в `art_manage_add_all_api`, `art_manage_meta_api`,
      `art_manage_sync_api`, где больше нет использования `request`
      (CSRF был единственным), проверить и удалить `request: Request`
      из сигнатуры, иначе — оставить, потому что FastAPI
      автоопределяет параметры.
  - `fastapi-application/md_articles/__init__.py` (edit docstring):
    обновить module-docstring — отразить, что авторизация вынесена в
    `auth_users/` пакет.
- Контракт:
  - `main_app` теперь содержит 44 маршрута (был 42).
  - Все пути `/api/blog/articles*`, `/api/blog/sections` — без изменений.
  - Все пути `/api/blog/art_manage*` — без CSRF, теперь требуют
    только `Depends(active_user)`.
  - Никаких `request.session["user_id"]` нигде не остаётся.
- Шаги:
  1. В `setup_frontend.py` точечный `edit` (4 правки: 2 удаления импорта,
     удаление `add_middleware_auth` строки, удаление
     `include_router(router_auth_api)`, добавление импорта
     `auth_users_router` и строки `include_router`).
  2. Удалить файлы `api_auth.py`, `middleware_auth.py`,
     `helpers_auth.py`. Это можно сделать одним shell-вызовом (3 `rm`).
  3. В `api_blog.py` точечный `edit` (5 правок: удалить импорт helpers,
     добавить импорт active_user, 4 замены `Depends(require_login_api)`,
     4 удаления `await validate_csrf_header(request)`).
  4. Обновить docstring `md_articles/__init__.py`.
  5. Прогнать checkpoint — обязательно с поднятым сервером.
- Checkpoint:
  - `cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"` → `44`
  - Список путей `main_app.routes` НЕ содержит:
    `/api/blog/csrf`, `/api/blog/login`, `/api/blog/logout`,
    `/api/blog/register`, `/api/blog/current_user`, `/api/blog/account`.
  - Список путей `main_app.routes` СОДЕРЖИТ:
    `/auth/jwt/login`, `/auth/jwt/logout`, `/auth/register`,
    `/users/me`, `/users/{id}`, `/auth/account`.
  - Регресс блога (важно!): `cd fastapi-application && ../.venv/bin/uvicorn main:main_app --port 8000 &`
    - `curl -s http://127.0.0.1:8000/api/blog/articles` → 200
    - `curl -s http://127.0.0.1:8000/api/blog/sections` → 200
    - `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/users/me` (без cookie) → 401
    - `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/blog/art_manage` (без cookie) → 403
    - `curl -s -X POST http://127.0.0.1:8000/api/blog/art_manage/add_all` (без CSRF, без cookie) → 403 (только из-за отсутствия активного пользователя; не CSRF).
  - `uv run ruff check .` → exit 0
- Готовность фазы: старая авторизация полностью удалена;
  новая подключена; регресс блога проходит; CSRF больше не нужен.

### Фаза 4: Alembic + Frontend

- Файлы backend (alembic):
  - `fastapi-application/one_simple.db` (delete — файл
    `.gitignore`, очистка dev-БД).
  - `fastapi-application/alembic/versions/<ts>--add_auth_users_user.py`
    (new) — создаётся через autogenerate:
    ```bash
    cd fastapi-application && rm -f one_simple.db
    ../.venv/bin/alembic revision --autogenerate -m "add auth_users user table"
    ../.venv/bin/alembic upgrade heads
    ```
    Подробности:
    - `User` зарегистрирован в `Base.metadata` (фаза 1).
    - `alembic/env.py` импортирует `db_core`, поэтому новая модель
      видна (фаза 1 уже обновила `db_core/__init__.py`).
    - Если autogenerate сгенерирует только `op.create_table("user")`
      с правильными колонками — фиксируется как есть.
    - Если autogenerate пожалуется на лишние изменения в существующих
      таблицах (`blog_user`, `blog_post`) — игнорировать, в
      autogenerate-ревизии только создание `user`.
  - **Дополнительно**, если Alembic не подхватит модель (autogenerate
    пуст), тогда — fallback: ручное создание через `Base.metadata.create_all`
    в `create_fastapi.py::lifespan` startup (dev-режим). Это
    оговаривается уже в checkpoint ниже как «если autogenerate пуст
    — добавляем create_all».
- Файлы frontend:
  - `frontend/src/api/client.ts` (rewrite) — убрать `getCsrfToken`,
    оставить чистые обёртки:
    ```typescript
    export async function getJson<T = unknown>(path: string): Promise<T> { ... }
    export async function postJson<T = unknown>(path: string, body: unknown): Promise<T> {
      const res = await request(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      return (await ensureOk(res)) as T;
    }
    export async function postMultipart<T = unknown>(path: string, formData: FormData): Promise<T> {
      // Content-Type не выставляем — браузер сам.
      const res = await request(path, { method: 'POST', body: formData });
      return (await ensureOk(res)) as T;
    }
    ```
  - `frontend/src/api/auth.ts` (rewrite) — новые эндпоинты:
    ```typescript
    import { getJson, postJson, postMultipart, ApiError } from './client';
    import type { User } from '../types';

    export interface MessageResp { message: string; category: string; }
    export interface ApiErrorWithErrors extends ApiError { errors?: Record<string, string[]>; }
    export function extractErrors(err: unknown): Record<string, string[]> {
      if (err instanceof ApiError) {
        const data = err.data as { errors?: Record<string, string[]> } | null;
        if (data?.errors) return data.errors;
      }
      return {};
    }

    // GET /users/me — fastapi-users даёт обогащённый UserRead.
    export function getCurrentUser(): Promise<User | null> {
      // /users/me без cookie вернёт 401; ловим в catch и возвращаем null.
      return getJson<User>('/users/me').catch((err) => {
        if (err instanceof ApiError && err.status === 401) return null;
        throw err;
      });
    }

    // POST /auth/jwt/login — form-urlencoded: username=email, password.
    export function login(body: { email: string; password: string }): Promise<User> {
      const form = new URLSearchParams({
        username: body.email,
        password: body.password,
      });
      // fastapi-users возвращает 204; фронт после — refresh из /users/me.
      return postForm<unknown>('/auth/jwt/login', form).then(() => {
        // После успешного логина делаем refresh (вытащим User сразу).
        return getJson<User>('/users/me');
      });
    }
    // postForm — новая обёртка в client.ts: Content-Type = x-www-form-urlencoded.
    ```

    ```typescript
    // POST /auth/jwt/logout — пустое тело, 204.
    export function logout(): Promise<MessageResp> {
      return postForm<MessageResp>('/auth/jwt/logout', new URLSearchParams())
        .catch(() => ({ message: 'Logged out', category: 'info' }));
    }

    // POST /auth/register — JSON {email, password}.
    export function register(body: {
      email: string;
      password: string;
    }): Promise<User> {
      return postJson<User>('/auth/register', body);
    }

    // GET /auth/account — нет (пост); account-loading — через /users/me.
    export async function getAccount(): Promise<{ user: User }> {
      const user = await getJson<User>('/users/me');
      return { user };
    }

    // POST /auth/account — multipart: username, email, picture (опц.).
    export function updateAccount(body: {
      username: string;
      email: string;
      picture?: File | null;
    }): Promise<MessageResp & { user: User }> {
      const formData = new FormData();
      formData.set('username', body.username);
      formData.set('email', body.email);
      if (body.picture) formData.set('picture', body.picture);
      return postMultipart<MessageResp & { user: User }>('/auth/account', formData);
    }
    ```
    Дополнительная обёртка `postForm` в `client.ts`:
    ```typescript
    export async function postForm<T = unknown>(path: string, form: URLSearchParams): Promise<T> {
      const res = await request(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: form.toString(),
      });
      return (await ensureOk(res)) as T;
    }
    ```
  - `frontend/src/types.ts` (edit): `User.id: number` → `User.id: string`.
  - `frontend/src/pages/LoginPage.tsx` (edit): контракт `login` —
    теперь возвращает `Promise<User>` (см. новую сигнатуру выше);
    обработка ошибки — на `ApiError` с `status === 400` показывать
    сообщение «Неверный email или пароль» (fastapi-users отвечает
    `{"detail":"LOGIN_BAD_CREDENTIALS"}`).
- Контракт (замораживается):
  - В БД есть таблица `user` с колонками: `id` (UUID PK), `email`
    (varchar 320 unique), `hashed_password` (varchar 1024), `is_active`
    (bool), `is_superuser` (bool), `is_verified` (bool), `username`
    (varchar 20 unique), `image_file` (varchar 20, default
    "default.jpg"), `created_at` (datetime).
  - Фронт после сборки (`npm run build`) проходит без ошибок типов
    TypeScript.
- Шаги:
  1. Backend (alembic) — выполняется **первым**:
     a. Удалить `one_simple.db`.
     b. Прогнать alembic revision --autogenerate.
     c. Если ревизия пустая — fallback: добавить `await
     conn.run_sync(Base.metadata.create_all)` в `lifespan`
     `create_fastapi.py` (только для dev, см. оговорку).
     d. `alembic upgrade heads` — успех, таблица `user` в SQLite.
  2. Frontend — три файла:
     a. Перезаписать `client.ts` (remove CSRF, добавить `postForm`).
     b. Перезаписать `auth.ts` (новые эндпоинты).
     c. `types.ts` (id: string).
     d. `LoginPage.tsx` — обновить обработку ошибки для нового формата.
  3. Прогнать `cd frontend && npm run build` — без ошибок TypeScript.
- Checkpoint:
  - `cd fastapi-application && rm -f one_simple.db && ../.venv/bin/alembic revision --autogenerate -m "add_auth_users_user" 2>&1 | tail -5` — autogenerate отработал.
  - `cd fastapi-application && ../.venv/bin/alembic upgrade heads` — exit 0.
  - `cd fastapi-application && ../.venv/bin/python -c "import sqlite3; conn=sqlite3.connect('one_simple.db'); print([r[0] for r in conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall() if 'user' in r[0] or 'blog' in r[0]])"` — содержит `user` (и, ожидаемо, `blog_user`, `blog_post`).
  - `cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"` — после рестарта → `44`.
  - `cd frontend && npm run build` — exit 0, нет TS-ошибок.
  - `uv run ruff check .` (для backend) — exit 0.
- Готовность фазы: новая БД содержит `user`-таблицу; фронт
  пересобирается без ошибок; auth-эндпоинты доступны; фронтовый
  клиент готов работать с новым контрактом.

### Фаза 5: Документация + smoke

- Файлы:
  - `docs/04_authorization.md` (rewrite) — полностью переписан:
    - Раздел 1: общая картина (`auth_users` пакет, контракт эндпоинтов,
      cookie, JWT).
    - Раздел 2: модель `User` (UUID PK, доп. поля).
    - Раздел 3: UserManager + `validate_password` (мин. длина 8).
    - Раздел 4: `auth_users/auth_backend.py` (cookie + JWT).
    - Раздел 5: `auth_users/router.py` (9 маршрутов, включая
      `/auth/account` для аватара).
    - Раздел 6: интеграция с фронтом (Vite proxy, cookie, без CSRF).
    - Раздел 7: миграция старых пользователей (drop, почему безопасно).
    - Раздел 8: секрет JWT (`settings.web.secret_key`).
    - Раздел 9: грейбли (cookie_secure в проде, лимит пароля,
      авто-апгрейд не срабатывает на `/auth/account`-UPDATE и т.п.).
  - `docs/15_md_articles_package.md` (edit): раздел про авторизацию —
    одна короткая секция «Использует `auth_users` пакет, см.
    `docs/04_authorization.md`»; ссылки на новые эндпоинты.
  - `QWEN.md` (edit):
    - В таблице «Архитектура» обновить строку `router_blog_api` —
      добавить сноску «авторизация вынесена в `auth_users` пакет».
    - В блоке «Проверка счётчика»: `42` → `44`.
    - В блоке «Разбивка»: упоминание `+ 9 new auth routes` вместо
      старых 7.
  - `AGENTS.md` (edit):
    - В строке про `len(main_app.routes)` обновить 42 → 44.
    - В «Зоны и проверки» (`backend-dev`): уточнить, что
      `fastapi-application/auth_users/` — это самостоятельная зона
      backend-dev.
- Контракт: документация синхронизирована с кодом.
- Шаги:
  1. Перезаписать `docs/04_authorization.md` одним `write_file`.
  2. Точечно отредактировать `docs/15_md_articles_package.md`.
  3. Точечно отредактировать `QWEN.md` (счётчик маршрутов).
  4. Точечно отредактировать `AGENTS.md` (счётчик маршрутов + зоны).
- Checkpoint:
  - `grep -r "42" docs/04_authorization.md QWEN.md AGENTS.md` →
    ноль вхождений в контексте счётчика маршрутов (могут быть
    неуместные «42» в других смыслах — игнорировать).
  - `grep -r "44" QWEN.md AGENTS.md` → ≥ 1 вхождение в строке
    про `len(main_app.routes)`.
  - `ruff check .` → exit 0.
- Готовность фазы: документация актуальна; задание готово к финальной
  приёмке qa.

## Критерии успеха

Проверяются qa по завершении всех фаз; сырые выводы — в
`tasks/current/e2e/`.

| # | Критерий | Проверка | Ожидание |
|---|---|---|---|
| 1 | Маршруты: ровно 44 | `cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"` | `44` |
| 2 | Старые пути `/api/blog/{csrf,login,logout,register,current_user,account}` отсутствуют | Та же команда, фильтрация `[r.path for r in main_app.routes]` | `len([...]) == 0` (все эти пути) |
| 3 | Новые пути `/auth/{jwt/login,jwt/logout,register,account}` и `/users/{me,{id}}` присутствуют | Та же команда, фильтрация | каждый из 9 путей найден по одному разу |
| 4 | Регистрация нового пользователя через fastapi-users работает | `curl -s -X POST http://127.0.0.1:8000/auth/register -H "Content-Type: application/json" -d '{"email":"new@test.com","password":"strongpass1"}' -o /dev/null -w "%{http_code}"` после регистрации | `201` |
| 5 | Регистрация дубликата email даёт `400 REGISTER_USER_ALREADY_EXISTS` | Повторный вызов с тем же email | `400` |
| 6 | Login через `/auth/jwt/login` (form-data) ставит cookie | `curl -s -i -X POST http://127.0.0.1:8000/auth/jwt/login -H "Content-Type: application/x-www-form-urlencoded" -d "username=new@test.com&password=strongpass1" \| grep -i "set-cookie: auth="` | строка `Set-Cookie: auth=<jwt>; HttpOnly; SameSite=lax; Path=/; Max-Age=86400` |
| 7 | `/users/me` с cookie возвращает `UserRead` с дополнительными полями | Сохранить cookie из (6) в `cookies.txt`, затем `curl -s --cookie cookies.txt http://127.0.0.1:8000/users/me` | JSON содержит `id`, `email`, `username`, `image_file`, `is_active`, `is_superuser`, `is_verified` |
| 8 | `/users/me` без cookie → 401 | `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/users/me` | `401` |
| 9 | Logout через `/auth/jwt/logout` очищает cookie | Из (6) cookie в `cookies.txt`, `curl -s -i -X POST --cookie cookies.txt http://127.0.0.1:8000/auth/jwt/logout \| grep -i "set-cookie: auth="` | строка `Set-Cookie: auth=; ...; Max-Age=0` |
| 10 | `/auth/account` multipart (username+email+picture) обновляет профиль | Сохранить cookie из (6), подготовить файл аватара 1×1 PNG, отправить multipart — `curl -s -X POST --cookie cookies.txt http://127.0.0.1:8000/auth/account -F "username=newname" -F "email=new@test.com" -F "picture=@avatar.png"` | `200 {"message":"Your account has been updated!","category":"success","user":{...}}`; `image_file` изменилось; файл `static/profile_pics/<random>.jpg` создан |
| 11 | `/api/blog/articles` регресс | `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/blog/articles` | `200` |
| 12 | `/api/blog/art_manage` без cookie → 403 | `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/blog/art_manage` | `403` |
| 13 | `/api/blog/art_manage/add_all` POST без CSRF (только с активным пользователем) | С cookie из (6), `curl -s -o /dev/null -w "%{http_code}" -X POST --cookie cookies.txt http://127.0.0.1:8000/api/blog/art_manage/add_all` | `200` |
| 14 | Регресс: `/users/get_all_users`, `/orders/get_all_orders`, `/docs` работают | 3 curl | все `200` |
| 15 | Frontend `npm run build` без TS-ошибок | `cd frontend && npm run build 2>&1 \| tail -20` | exit 0 |
| 16 | Frontend dev-build соответствует новым эндпоинтам (smoke через `curl http://127.0.0.1:5173/api/users/me` после `npm run dev`) | Ручной smoke или qa-curl | `users/me` возвращает 401 без cookie, 200 с cookie (если поднят dev-сервер; иначе проверяется только `npm run build`) |
| 17 | ruff чист | `cd fastapi-application && uv run ruff check .` | exit 0 |
| 18 | Импорт-смоук всего стека без ошибок | `cd fastapi-application && ../.venv/bin/python -c "from main import main_app; from auth_users import User, fastapi_users, router; from md_articles.api_blog import router_blog_api; print('OK', len(main_app.routes))"` | `OK 44` |
| 19 | Таблица `user` есть в SQLite после миграции | `cd fastapi-application && ../.venv/bin/python -c "import sqlite3; conn=sqlite3.connect('one_simple.db'); print([r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()])"` | содержит `'user'` в списке |
| 20 | Поиск старых CSRF/сессионных хелперов — ноль вхождений | `grep -rE "validate_csrf|ensure_csrf_token|require_login_api|SessionMiddleware|hash_password|verify_password" fastapi-application/` | нет вхождений в `md_articles/` (допустимо в `auth_users/` для собственных нужд, но в текущей спеке их нет) |

## Финальные критерии

1. Каждый критерий успеха подтверждён доказательством (curl-вывод в
   `tasks/current/e2e/`, заметка в `dev/`, лог-файл).
2. `tasks/current/DEFECTS.md` существует только если найдены дефекты;
   все записи не в `OPEN` (или `CLOSED`, или `REJECTED`).
3. Adversarial-прогон выполнен; ни одна запись
   `ADVERSARIAL_REVIEW.md` не остаётся `PENDING`.
4. Все пять фаз завершены, прогресс-файлы `phaseNN_progress.md`
   зафиксированы в `tasks/current/dev/`.
5. `len(main_app.routes) == 44` подтверждено на свежем рестарте
   uvicorn.
6. Документация (`docs/04_authorization.md`, `QWEN.md`, `AGENTS.md`)
   актуальна.
7. Все тестовые серверы погашены оркестратором перед архивированием.

## Открытые вопросы

- (Закрывается ДО старта исполнения; ответы переезжают в
  «Подтверждённые решения».)

- **Вопрос 1: какой формат для register — оставляем ли username?**
  Вариант A (зафиксировано): username приходит через
  `POST /auth/account` сразу после register (фронт уже делает
  двойной submit — register, потом account). Вариант B (не
  рассматривается в этой спеке): кастомный `/auth/register` с
  полями username+email+password. Подтверждено: оставляем
  стандартный fastapi-users register, дополнительный username +
  аватар — через `/auth/account`.

- **Вопрос 2: что делать со старой таблицей `blog_user`?**
  Вариант A (зафиксировано): оставить как «мёртвый груз», не
  удалять (FK на `blog_post.user_id` защищает таблицу от
  удаления; чистка — отдельным заданием). Вариант B: написать
  data-migration в Alembic для перевода `BlogPost.user_id`
  на новую `User.id`. Подтверждено: вариант A — проще, без
  alembic-миграций данных.

- **Вопрос 3: `cookie_secure` для dev — False или True?**
  Вариант A (зафиксировано): False по умолчанию (dev-окружение
  работает на `http://127.0.0.1:8000`, secure=True не работает
  без HTTPS). Вариант B: True по умолчанию, но Secure-cookie не
  ставится браузером на http://. Подтверждено: False.

- **Вопрос 4: ошибки фронта при 401 (например, для `/api/blog/art_manage`)?**
  fastapi-users возвращает 401, фронт `useAuth.refresh()`
  должен ловить и сбрасывать `user = null`. Подтверждено: новая
  логика `useAuth.refresh` уже делает catch на 401 (см. текущий
  код). Прямые `fetch` без обёртки (для art-роутов) теперь также
  могут получать 401 — обработчик ошибок в AuthContext
  перевыпускает refresh.

- **Вопрос 5: нужен ли `verify_and_update` авто-апгрейд на login?**
  Да, донорский `PasswordHelper` уже делает это автоматически
  внутри `authenticate()`. Подтверждено: оставляем как есть — это
  поведение fastapi-users 14.x по умолчанию.

- **Вопрос 6 (открыто — пока не решено):** если пользователь
  обновил username через `/auth/account`, fastapi-users
  `UserRead` для `/users/me` покажет обновлённое значение?
  Ответ: ДА, потому что `UserRead` — это сериализация ORM-модели,
  она всегда актуальна на момент запроса. (Вопрос закрыт
  формально; оставлен в списке, чтобы было видно, что мы его
  проверили.)

- **Вопрос 7 (открытый):** как обрабатывать
  `REGISTER_INVALID_PASSWORD` (400) на фронте?
  Сейчас `RegisterPage` умеет показывать `errors` по полям. Нам
  нужно: при 400 с `detail: "REGISTER_INVALID_PASSWORD"` —
  показать общую ошибку `password`. Вариант A: парсить `detail`
  в `extractErrors`. Подтверждено: добавить обработку в
  `extractErrors` (фаза 4): если `data?.detail` начинается с
  `REGISTER_`, показывать как ошибку поля `password`/прочее.

- **Вопрос 8: `image_file` после обновления через `/auth/account`
  сразу видно в `/users/me`?**
  Да, потому что `/users/me` (UserRead) сериализует актуальную
  запись. Закрыт.

- **Вопрос 9: должен ли фронт после login обновить `AuthContext.user`?**
  Да — текущий контракт (login.then(setUser(...))). Поскольку
  `login()` теперь возвращает `User` (а не `MessageResp`),
  фронт делает `setUser(user)` напрямую. Аналогично для
  `register()`. Закрыт.

---

# Отчёт о выполнении

- Дата закрытия: 2026-09-12

## Итог
Полная замена самописной авторизации блога на fastapi-users 15.0.5 (CookieTransport + JWTStrategy + pwdlib Argon2). 44 маршрута (было 42, −7 самописных + 9 fastapi-users), 19/19 пунктов финального QA-прогона зелёные, race condition на concurrent register исправлен, документация обновлена (docs/04_authorization.md — 716 строк, QWEN.md/AGENTS.md — счётчик 42 → 44).

## Изменения (файл → суть)
- `fastapi-application/auth_users/` — новый пакет (8 файлов): models, schemas, user_manager, helpers, auth_backend, fastapi_users_obj, account, router.
- `fastapi-application/core/config.py` — `AuthUsersConfig` (cookie_* / jwt_* / password_min_length).
- `fastapi-application/db_core/__init__.py` — `from auth_users.models import User` в самом конце (разрыв цикла + регистрация в `Base.metadata`).
- `fastapi-application/main.py` — `from auth_users import router as auth_users_router` (ранее был в setup_frontend.py — создавал циркулярку).
- `fastapi-application/md_articles/setup_frontend.py` — `auth_users_router` принимается параметром `include_router_api_frontend(app, auth_users_router=...)`.
- `fastapi-application/md_articles/api_blog.py` — `Depends(require_login_api)` → `Depends(active_user)`, удалены `await validate_csrf_header(request)` (4 шт.).
- `fastapi-application/md_articles/{api_auth, middleware_auth, helpers_auth}.py` — удалены.
- `fastapi-application/ex_user_post/models/model_user_post.py` — `relationship("User", ...)` → `relationship("ex_user_post.models.model_user_post.User", ...)` (полный путь устраняет неоднозначность с auth_users.User).
- `fastapi-application/auth_users/models.py` — `username: nullable=False` → `nullable=True` (race-safe: INSERT сначала, username дописывается хуком `on_after_register`).
- `fastapi-application/auth_users/router.py` — сигнатура fastapi-users 15.x: `get_register_router(UserRead, UserCreate)`, `get_users_router(UserRead, UserUpdate)`, `get_auth_router(auth_backend)`.
- `fastapi-application/auth_users/user_manager.py` — `UserManager.create()` перехватывает `IntegrityError` → `UserAlreadyExists` (фикс race condition на concurrent register).
- `fastapi-application/pyproject.toml` — добавлен `fastapi-users[sqlalchemy]>=14.0.1`, удалён `bcrypt>=4.2.0`. `itsdangerous` оставлена (Starlette тянет).
- `fastapi-application/uv.lock` — обновлён (fastapi-users 15.0.5 + транзитивные).
- `fastapi-application/alembic/versions/2026-09-12_22-51--f4c23f4a9c06--add_auth_users_user_table.py` — новая ревизия (`import fastapi_users_db_sqlalchemy.generics` для GUID() + `nullable=True` для username).
- `frontend/src/api/client.ts` — rewrite: без CSRF, добавлен `postForm`, `credentials: 'include'`.
- `frontend/src/api/auth.ts` — rewrite: `/auth/jwt/login`, `/auth/jwt/logout`, `/auth/register`, `/auth/account`, `/users/me`.
- `frontend/src/types.ts` — `User.id: number` → `User.id: string`.
- `frontend/src/pages/LoginPage.tsx` — обработка 400 «Неверный email или пароль».
- `frontend/src/context/AuthContext.tsx` — `getCurrentUser` теперь возвращает `User | null` (минимальная правка потребителя).
- `frontend/src/pages/RegisterPage.tsx` — `register({email, password})` без username/confirm_password (минимальная правка; UX-деградация — см. DEF-005).
- `docs/04_authorization.md` — полный rewrite (716 строк, 9 разделов).
- `QWEN.md`, `AGENTS.md` — счётчик маршрутов 42 → 44, добавлено описание пакета `auth_users/`, обновлена зона backend-dev.
- `docs/15_md_articles_package.md` — SKIPPED backend-dev'ом (файл не существует; ссылка stale в QWEN.md/AGENTS.md).

## Дефекты
- DEF-001 CLOSED — `relationship` с полным путём модуля.
- DEF-002 CLOSED — сигнатура `get_register_router` под fastapi-users 15.x.
- DEF-003 CLOSED — циркулярный импорт разорван переносом `auth_users.router` в `main.py`.
- DEF-004 CLOSED — `User.username: nullable=True` + регенерированная alembic-ревизия.
- DEF-005 REJECTED — RegisterPage UX (поля username/confirm_password игнорируются); требует кастомный `/auth/register` или двухшаговую форму — отдельная задача.
- DEF-006 REJECTED — logout без cookie → 401 (поведение fastapi-users 15.x); требует кастомный logout endpoint — отдельная задача.
- DEF-007 CLOSED — race condition: перехват `IntegrityError` в `UserManager.create()` → `UserAlreadyExists` → 400.

## Adversarial-прогон
- ADV-001 (race condition concurrent register) — ACCEPTED → DEF-007 (CLOSED).
- ADV-002 (logout без cookie → 401) — REJECTED, дубликат DEF-006.
- ADV-003 (path traversal через SPA catch-all, /users/{id} → 200 HTML) — REJECTED, особенность SPA-архитектуры, не security issue.

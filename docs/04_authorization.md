# 04. Авторизация: пакет `auth_users` на fastapi-users

> Полный разбор слоя авторизации проекта: пакет `auth_users/`, контракт
> эндпоинтов, модель `User`, JWT-секрет, защита роутов блога, интеграция
> с фронтом, миграция пользователей и типичные грабли.
> Сопутствующие документы: [01_project_structure.md](01_project_structure.md)
> (дерево файлов), [02_architecture.md](02_architecture.md) (слои), [03_execution_flow.md](03_execution_flow.md)
> (lifespan и middleware). История замены самописной авторизации —
> в [05_authorization_upgrade.md](05_authorization_upgrade.md).

Состояние кода: ветка `auth_refactor`, `len(main_app.routes) == 44`. Из них
**9 auth-роутов** живут в пакете `fastapi-application/auth_users/` (вместо
7 самописных роутов в `md_articles/api_auth.py`, которые удалены). Никаких
других auth-роутов в проекте нет: демо-домены `api/`, `ex_user_post/`,
`ex_order_product/` открыты намеренно.

---

## Содержание

1. [Общая картина](#1-общая-картина)
2. [Модель `User`](#2-модель-user)
3. [`UserManager` и валидация пароля](#3-usermanager-и-валидация-пароля)
4. [`auth_backend`: cookie + JWT](#4-auth_backend-cookie--jwt)
5. [Роутер: 9 маршрутов](#5-роутер-9-маршрутов)
6. [Интеграция с фронтом](#6-интеграция-с-фронтом)
7. [Миграция пользователей](#7-миграция-пользователей)
8. [Секрет JWT](#8-секрет-jwt)
9. [Грейбли](#9-грейбли)

---

## 1. Общая картина

Пакет `fastapi-application/auth_users/` — это изолированный слой авторизации,
построенный поверх библиотеки **fastapi-users 14.0.1** + **fastapi-users-db-sqlalchemy** +
**pwdlib Argon2**. Пакет **отделён от `md_articles/`**: импорты внутри — относительные
(`from .models import User`), снаружи — плоские (`from auth_users import router`).
Это самостоятельный слой приложения, а не часть блога.

Все настройки собираются через `settings.auth_users`
(`AuthUsersConfig` в `core/config.py`) и `settings.web.secret_key`
(общий секрет проекта, ранее использовался в `SessionMiddleware`).

### 1.1. Контракт эндпоинтов

Эти 9 маршрутов — единственная публичная поверхность auth-слоя для фронта
и других модулей:

| Метод | URL | Защита | Что делает |
|---|---|---|---|
| `POST` | `/auth/jwt/login` | — | form-urlencoded: `username=<email>&password=<…>` → 204 + `Set-Cookie: auth=...` |
| `POST` | `/auth/jwt/logout` | — | 204 + `Set-Cookie: auth=; Max-Age=0` |
| `POST` | `/auth/register` | — | JSON `{email, password}` → 201 + `UserRead` |
| `GET` | `/users/me` | `active_user` | свой профиль (UserRead) |
| `PATCH` | `/users/me` | `active_user` | обновить email/password (через fastapi-users) |
| `GET` | `/users/{id}` | `superuser_user` | профиль пользователя по UUID |
| `PATCH` | `/users/{id}` | `superuser_user` | изменить email/password пользователя |
| `DELETE` | `/users/{id}` | `superuser_user` | удалить пользователя |
| `POST` | `/auth/account` | `active_user` | multipart: `username`/`email`/`picture` → `{message, category, user}` |

`/auth/jwt/login` и `/auth/jwt/logout` не требуют активной сессии (как в
donor-шаблоне `template-jwt-auth/`). `/auth/register` тоже. Защищённые
роуты — `/users/me` (GET/PATCH), `/auth/account` — используют
`Depends(active_user)`. `/users/{id}` — `Depends(superuser_user)`, в
текущей версии не используется фронтом, но зарегистрированы библиотекой
для полноты OpenAPI.

### 1.2. Cookie и JWT

| Параметр | Значение | Откуда |
|---|---|---|
| Имя cookie | `auth` | `settings.auth_users.cookie_name` |
| `httponly` | `True` | `settings.auth_users.cookie_httponly` |
| `samesite` | `"lax"` | `settings.auth_users.cookie_samesite` |
| `secure` | `False` (dev) | `settings.auth_users.cookie_secure` |
| `max_age` | `86400` (24 часа) | `settings.auth_users.cookie_max_age` |
| Алгоритм JWT | `HS256` | `settings.auth_users.jwt_algorithm` |
| Lifetime JWT | `86400` сек | `settings.auth_users.jwt_lifetime_seconds` |
| Секрет JWT | общий `secret_key` | `settings.web.secret_key` |

`SameSite=Lax` + `HttpOnly` + `credentials: 'include'` на фронте
(см. §6) дают достаточную защиту от CSRF для same-origin SPA —
отдельный CSRF-токен не нужен.

### 1.3. Стек

```
fastapi-users 14.0.1                # регистрация / логин / обновление / ...
  ├─ fastapi-users-db-sqlalchemy    # SQLAlchemyUserDatabase поверх async-сессии
  ├─ pwdlib (Argon2)                # хеширование паролей (PasswordHelper)
  ├─ pyjwt                          # подпись/верификация JWT
  ├─ email-validator                # валидация email
  └─ python-multipart               # OAuth2PasswordRequestForm + multipart upload
```

Донор — шаблон `template-jwt-auth/` (FastAPI + Jinja + HTMX). Здесь —
адаптация под React 18 + Vite SPA с сохранением проектных полей
`username` и `image_file`.

---

## 2. Модель `User`

Файл `fastapi-application/auth_users/models.py` — единственная ORM-модель
слоя авторизации.

```python
from datetime import datetime, timezone
from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column
from db_core.model_base import Base
from db_core.type_for_models import str_len_20


class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "user"

    username: Mapped[str_len_20 | None] = mapped_column(unique=True, nullable=True)
    image_file: Mapped[str_len_20] = mapped_column(
        nullable=False,
        default="default.jpg",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
```

### 2.1. Что даёт `SQLAlchemyBaseUserTableUUID`

Mixin из `fastapi-users-db-sqlalchemy` объявляет готовый набор колонок:

- `id: UUID` — первичный ключ (тип `UUID`, не `int`). Устойчив к перечислению
  идентификаторов; фронт получает `id: string` через `/users/me`.
- `email: str` — уникальный, индексированный.
- `hashed_password: str` — хеш пароля (Argon2 через pwdlib).
- `is_active: bool` — флаг активности (по умолчанию `True`).
- `is_superuser: bool` — флаг суперпользователя.
- `is_verified: bool` — флаг подтверждения email.

### 2.2. Проектные поля

| Поле | Тип | NULL | Default | Назначение |
|---|---|---|---|---|
| `username` | `str_len_20` | да | — | Имя пользователя (2–20 символов, валидация в `account.py`). |
| `image_file` | `str_len_20` | нет | `"default.jpg"` | Имя файла аватара в `static/profile_pics/`. |
| `created_at` | `DateTime(timezone=True)` | нет | `datetime.now(timezone.utc)` | Дата регистрации (только ORM; в API не выставляется). |

### 2.3. Почему `username: nullable=True`

`username` помечен как `nullable=True` — это **намеренный компромисс**,
связанный с порядком вызовов в `BaseUserManager.create`:

1. `BaseUserManager.create` принимает `UserCreate = {email, password}`.
2. Проверяет уникальность email (`email_exists`), хеширует пароль.
3. Делает `INSERT INTO user (email, hashed_password, ...)`.
4. После INSERT вызывается хук `on_after_register`, который дописывает
   `username = email.split("@")[0].strip()` и `image_file = "default.jpg"`.

Если бы `username` был `NOT NULL`, INSERT на шаге 3 упал бы с
`IntegrityError`. С `nullable=True` INSERT проходит, а хук дописывает
значение отдельным UPDATE'ом. На уровне кода и API `username` всегда
непустой — если пользователь хочет другой username, он обновляется
через `POST /auth/account` (там проверка уникальности + валидация длины).

### 2.4. Регистрация в `Base.metadata`

Модель реэкспортируется в `fastapi-application/db_core/__init__.py` —
импорт `from auth_users.models import User` стоит в самом конце файла.
Это разрывает цикл импортов: `auth_users.models` → `db_core.model_base`
→ `db_core/__init__` → `md_articles` → `setup_frontend` → `auth_users`
(частично загружен). Корректный порядок обеспечивается тем, что при
старте приложения `main.py` импортирует `db_core` целиком **до**
`auth_users`, и `auth_users.models` уже видит `Base` в `sys.modules`.

Без этого реэкспорта Alembic `--autogenerate` не увидит таблицу `user`
(миграция создаётся пустой). Подробнее — в [01_project_structure.md](01_project_structure.md).

---

## 3. `UserManager` и валидация пароля

Файл `fastapi-application/auth_users/user_manager.py` — бизнес-правила
регистрации и валидации.

### 3.1. Класс `UserManager`

```python
class UserManager(UUIDIDMixin, BaseUserManager[User, UUID]):
    reset_password_token_secret = settings.web.secret_key
    verification_token_secret = settings.web.secret_key
```

`UUIDIDMixin` даёт методам `BaseUserManager` (`get_by_email`, `get`,
`update`, `delete`, ...) понимание, что `id` имеет тип `UUID`. Секреты
для токенов сброса пароля и подтверждения email берутся из
`settings.web.secret_key` — отдельных ключей под auth в проекте нет
(в задании нет потока верификации и сброса, но если он появится —
секрет уже на месте).

### 3.2. `validate_password`

```python
async def validate_password(self, password: str, user: User) -> None:
    password_min_length = settings.auth_users.password_min_length
    if len(password) < password_min_length:
        raise InvalidPasswordException(
            reason=f"Пароль должен быть не короче {password_min_length} символов."
        )
```

Минимальная длина пароля — `settings.auth_users.password_min_length = 8`
(см. `core/config.py::AuthUsersConfig`). fastapi-users вызывает этот
метод при `create()` и `update()`. При нарушении — `InvalidPasswordException`,
который register-router переводит в стандартный 400
`REGISTER_INVALID_PASSWORD`. Для PATCH `/users/me` поведение аналогичное.

### 3.3. `create()` с перехватом race condition

```python
async def create(self, user_create, safe=False, request=None) -> User:
    try:
        return await super().create(user_create, safe=safe, request=request)
    except IntegrityError:
        raise UserAlreadyExists()
```

Стандартный `BaseUserManager.create` проверяет уникальность email через
`SELECT`, а затем делает `INSERT`. Между этими двумя запросами другой
параллельный запрос (например, открытая в двух вкладках форма
регистрации) может успеть вставить того же пользователя — и тогда
INSERT падает с `IntegrityError` 500.

Перехват `IntegrityError` → `UserAlreadyExists` переводит ситуацию в
штатный 400 `REGISTER_USER_ALREADY_EXISTS`, который register-router
отдаёт по контракту fastapi-users. Фронт обрабатывает его одинаково с
ситуацией «email уже занят» из `email_exists`. Это устраняет класс
ошибок 500 при двойной регистрации.

### 3.4. `on_after_register`

```python
async def on_after_register(self, user, request=None) -> None:
    update_dict: dict = {}
    if not user.username:
        derived = (user.email.split("@", 1)[0] or "")[:20].strip()
        user.username = derived
        update_dict["username"] = derived
    if not user.image_file:
        user.image_file = "default.jpg"
        update_dict["image_file"] = "default.jpg"
    if update_dict:
        await self.user_db.update(user, update_dict)
    logF.info("auth_users: registered %s", user.email)
```

Хук вызывается **после** INSERT. Если у пользователя ещё нет `username`
(а его не будет — register-router принимает только `email` и `password`),
генерируется `username = email.split("@")[0].strip()` (обрезается до 20
символов под длину колонки). `image_file` ставится в `"default.jpg"`.
Если пользователь зарегистрировался через `/auth/register`, его `username`
по умолчанию — часть email до `@`; фронт может обновить его позже через
`POST /auth/account`.

### 3.5. DI: `get_user_db` и `get_user_manager`

```python
async def get_user_db(session: CurrentSession) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    yield SQLAlchemyUserDatabase(session, User)

async def get_user_manager(user_db=Depends(get_user_db)) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)
```

Стандартный шаблон fastapi-users: `get_user_db` оборачивает
`CurrentSession` (наш алиас `Annotated[AsyncSession, Depends(...)]`) в
`SQLAlchemyUserDatabase`, который умеет делать CRUD-операции,
ожидаемые `BaseUserManager`. `get_user_manager` собирает `UserManager`
через DI. Оба экспортируются наружу — нужны для `FastAPIUsers(...)`
и `app.dependency_overrides` в тестах.

---

## 4. `auth_backend`: cookie + JWT

Файл `fastapi-application/auth_users/auth_backend.py` объединяет
транспорт и стратегию в один объект, который передаётся в
`FastAPIUsers(...)`.

### 4.1. `cookie_transport`

```python
from fastapi_users.authentication import CookieTransport

cookie_transport = CookieTransport(
    cookie_name=settings.auth_users.cookie_name,        # "auth"
    cookie_max_age=settings.auth_users.cookie_max_age,  # 86400
    cookie_secure=settings.auth_users.cookie_secure,    # False (dev)
    cookie_httponly=settings.auth_users.cookie_httponly, # True
    cookie_samesite=settings.auth_users.cookie_samesite, # "lax"
)
```

`CookieTransport` из fastapi-users при логине ставит `Set-Cookie` с
подписанным JWT, при логауте — `Set-Cookie: auth=; Max-Age=0`. На
входящих запросах он сам читает cookie и передаёт JWT в стратегию.

### 4.2. `get_jwt_strategy`

```python
from fastapi_users.authentication.strategy import JWTStrategy

def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(
        secret=settings.web.secret_key,
        lifetime_seconds=settings.auth_users.jwt_lifetime_seconds,
        algorithm=settings.auth_users.jwt_algorithm,
    )
```

Стратегия подписывает токен HS256 с lifetime 24 часа. Секрет берётся
из `settings.web.secret_key` — общий секрет проекта. Ротация секрета
отдельной задачей не предусмотрена.

### 4.3. `auth_backend`

```python
from fastapi_users.authentication import AuthenticationBackend

auth_backend = AuthenticationBackend(
    name="jwt",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)
```

`AuthenticationBackend` связывает транспорт и стратегию. Имя `"jwt"`
нужно для логов и OpenAPI (`securitySchemes`); используется только
внутренне — на фронт не утекает. Один объект `auth_backend`
передаётся и в `FastAPIUsers(...)`, и в `get_auth_router(auth_backend)`
(см. §5).

---

## 5. Роутер: 9 маршрутов

Файл `fastapi-application/auth_users/router.py` собирает общий
`router` из 4 вложенных роутеров:

```python
auth_router     = fastapi_users.get_auth_router(auth_backend)        # /auth/jwt/{login,logout}
register_router = fastapi_users.get_register_router(UserRead, UserCreate)  # /auth/register
users_router    = fastapi_users.get_users_router(UserRead, UserUpdate)    # /users/me, /users/{id}
# account_router — отдельный модуль auth_users/account.py

router = APIRouter()
router.include_router(auth_router,     prefix="/auth/jwt", tags=["auth-jwt"])
router.include_router(register_router, prefix="/auth",    tags=["auth-register"])
router.include_router(users_router,    prefix="/users",   tags=["users"])
router.include_router(account_router)   # prefix="/auth", tags=["auth-account"] внутри account.py
```

Подключение к `main_app` — в `main.py`:
`include_router_api_frontend(main_app, auth_users_router=auth_users_router)`.
Параметр передаётся из `main.py`, а не импортируется в `setup_frontend`,
чтобы разорвать цикл импортов (см. docstring `setup_frontend.py`).

### 5.1. Маршруты из коробки fastapi-users

- `POST /auth/jwt/login` — `OAuth2PasswordRequestForm`-стиль
  (form-urlencoded с полями `username=<email>` и `password`). Успех: 204
  без тела + `Set-Cookie`. Ошибка: 400 `LOGIN_BAD_CREDENTIALS` —
  одинаковое сообщение и для несуществующего email, и для неверного
  пароля, и для `is_active=False` (не сообщаем, существует ли email).
- `POST /auth/jwt/logout` — без тела. Успех: 204 + `Set-Cookie: auth=;
  Max-Age=0`. Не требует аутентификации (как в доноре).
- `POST /auth/register` — JSON `{email, password}` (контракт username
  отсутствует, см. §2.3 и §3.4). Успех: 201 + `UserRead`. Ошибки:
  400 `REGISTER_USER_ALREADY_EXISTS`, 400 `REGISTER_INVALID_PASSWORD`,
  422 (pydantic-валидация email).
- `GET /users/me` — `UserRead` текущего активного пользователя.
  Анонимный запрос → 401.
- `PATCH /users/me` — обновить email/password через стандартный
  flow fastapi-users (валидация через `UserManager.validate_password`).
  `username` и `image_file` этим роутом **не меняются** — для них
  отдельный `/auth/account`.
- `GET /users/{id}`, `PATCH /users/{id}`, `DELETE /users/{id}` —
  требуют `superuser=True`. В текущей версии фронт их не вызывает,
  но регистрируются библиотекой автоматически — оставлены для
  совместимости с OpenAPI.

### 5.2. `POST /auth/account` — проектный

Файл `fastapi-application/auth_users/account.py`. Multipart-роут для
обновления `username`/`email`/аватара. Это **компенсация** того, что
`/auth/register` не принимает `username` (имя берётся из email), и
**поддержка multipart-аплоада** аватара.

Поля формы:

- `username: str` (2–20 символов, обязательное).
- `email: str` (валидный email, обязательное).
- `picture: UploadFile | None` (опционально).

Защита — `Depends(active_user)`. Без CSRF (см. §6). Логика:

1. Собрать ошибки в `dict[str, list[str]]` (формат WTForms-стиля).
2. Длина username, валидность email.
3. Если значение изменилось — `SELECT WHERE username/email = ?`
   через `username_exists`/`email_exists` (без `await` race в этой
   точке, но см. §3.3 про перехват `IntegrityError` в `create()`).
5. Если есть `picture` — `save_picture` (PIL-ресайз 125×125, имя
   `os.urandom(8).hex() + .jpg`, путь `BASE_DIR/static/profile_pics/`).
6. UPDATE `current_user` в роут-сессии, `await session.commit()`.
7. Ответ — `{message, category: "success", user: {...}}` (привычный
   фронту формат ответа).

Все хелперы (`save_picture`, `is_valid_email`, `username_exists`,
`email_exists`, `ERROR_EMAIL_TAKEN`, `ERROR_USERNAME_TAKEN`,
`validation_response`) перенесены из
`md_articles/helpers_auth.py` в `auth_users/helpers.py` без изменений
логики — только путь через `BASE_DIR`.

### 5.3. Защита роутов блога через `Depends(active_user)`

Файл `md_articles/api_blog.py` (ранее `require_login_api`):

```python
from auth_users import active_user

async def art_manage_api(_user=Depends(active_user)): ...
async def art_manage_add_all_api(_user=Depends(active_user)): ...
async def art_manage_meta_api(_user=Depends(active_user)): ...
async def art_manage_sync_api(_user=Depends(active_user)): ...
```

Арт-роуты блога больше **не** используют `request.state.current_user` и
не проверяют CSRF — аутентификация полностью на стороне fastapi-users.
Анонимный запрос → 401 (стандартный ответ fastapi-users), не 403, как
раньше.

---

## 6. Интеграция с фронтом

### 6.1. Что изменилось в `frontend/src/`

| Файл | Что изменилось |
|---|---|
| `src/api/client.ts` | Удалены `getCsrfToken()`, заголовок `X-CSRF-Token` в `postJson`, поле `csrf_token` в `postMultipart`. Остались чистые `fetch`-обёртки с `credentials: 'include'`. |
| `src/api/auth.ts` | Переписан под новый контракт: `getCurrentUser → GET /users/me`, `login → POST /auth/jwt/login` (form-data), `logout → POST /auth/jwt/logout`, `register → POST /auth/register`, `updateAccount → POST /auth/account` (multipart). |
| `src/types.ts` | `User.id: number → User.id: string` (UUID). |
| `src/context/AuthContext.tsx` | Без изменений по контракту (только проверка типа `id`). |
| `src/pages/LoginPage.tsx` | `login({email, password})` шлёт form-data (`URLSearchParams`), иначе без изменений. |
| `src/pages/RegisterPage.tsx`, `src/pages/AccountPage.tsx` | Без изменений (UI не меняется). |

### 6.2. `credentials: 'include'` и `SameSite=Lax`

```typescript
const res = await fetch(path, { credentials: 'include', ...init });
```

Браузер обязан прикладывать cookie сессии к каждому fetch и принимать
`Set-Cookie`. На same-origin cookie ушла бы и без флага, но он делает
намерение явным и пригодится при выносе API на отдельный origin.

### 6.3. Vite dev-прокси

В `frontend/vite.config.ts` API-запросы на `/auth/*`, `/users/*`,
`/api/blog/*` проксируются на `http://127.0.0.1:8000` (dev-сервер
uvicorn). В этом режиме фронт и API на одном origin (`localhost:5173`
→ `127.0.0.1:8000` через прокси, cookie ставится на origin
фронта), что согласуется с `SameSite=Lax` (Lax требует same-origin
для POST-запросов). Подробности про прокси — в
[12_fastapi_react_integration.md](12_fastapi_react_integration.md).

### 6.4. Почему нет CSRF

fastapi-users + `SameSite=Lax` + `HttpOnly` + same-origin дают
достаточную защиту от CSRF для SPA. `SameSite=Lax` запрещает браузеру
прикладывать cookie к кросс-сайтовым POST-запросам; этого достаточно,
пока фронт и API на одном origin. Никаких `X-CSRF-Token` заголовков
и `csrf_token` полей формы больше нет — фронт очищен от CSRF-слоя.

---

## 7. Миграция пользователей

### 7.1. Старые данные: `BlogUser`

До замены в `md_articles/models.py` жила модель `BlogUser` с полем
`password` (bcrypt-хеш). Старые auth-роуты в `api_auth.py` оперировали
этой моделью. В рамках задания эти роуты и самописная сессионная
авторизация **удалены**, а пользовательские данные **сбрасываются**.

### 7.2. Почему drop безопасен

В проекте дев-only данные (задания `001-md-articles-blog` —
`017-md-articles-split-auth-blog`), прода нет. Никаких ценных
регистраций в `BlogUser` быть не может — это записи локальных
пользователей во время разработки. Перед фазой 4 файл
`fastapi-application/one_simple.db` удаляется (он в `.gitignore`),
новая БД создаётся миграциями Alembic с нуля.

### 7.3. Что остаётся в схеме

`blog_user` (от `BlogUser`) и `blog_post` (от `BlogPost`) остаются
в схеме как «мёртвый груз» — НЕ удаляются, потому что
`blog_post.user_id` имеет FK на `blog_user.id`. Удаление `blog_user`
сломало бы FK. `PRAGMA foreign_keys=ON` (уже включён в `db_async.py`)
всё равно не дал бы удалить. На моргание таблиц можно не обращать
внимания: `GET /api/blog/articles` возвращает метаданные статей,
фронт их не привязывает к пользователю-автору через новую `User`-модель
(там будет NULL/Orphan строка). Cleanup `blog_user`/`blog_post` —
отдельная задача, вне текущего задания.

### 7.4. Новая миграция Alembic

В фазе 4 выполнены:

```bash
rm fastapi-application/one_simple.db
cd fastapi-application && ../.venv/bin/alembic revision --autogenerate -m "add auth_users user"
../.venv/bin/alembic upgrade heads
```

Autogenerate создал ревизию с `op.create_table("user", ...)` (одна
таблица, остальные блог-таблицы уже существовали). Дополнительных
ручных правок в `upgrade()`/`downgrade()` не потребовалось.

Проверка:

```bash
cd fastapi-application && ../.venv/bin/sqlite3 one_simple.db ".tables"
# blog_post blog_user blog_subsection user user_access_token alembic_version
```

---

## 8. Секрет JWT

`settings.web.secret_key` — **общий секрет проекта**: ранее
использовался `SessionMiddleware` для подписи cookie, теперь —
`JWTStrategy` для подписи JWT.

```python
class WebConfig(BaseModel):
    secret_key: str = "dev-insecure-secret-key-change-me"
```

В `dev_sqlite.env` (активный профиль) секрет задан явно:
`APP__WEB__SECRET_KEY=...` — это dev-only строка. В прод-размещении
значение должно передаваться через `.env` или переменную окружения
**и быть уникальным для каждой среды**. Ротация секрета — отдельная
задача: после смены все ранее выданные JWT станут невалидными, что
приведёт к принудительному разлогину всех пользователей.

`secret_key` используется в трёх местах:

- `auth_users/auth_backend.py::get_jwt_strategy` — подпись JWT (HS256).
- `auth_users/user_manager.py::UserManager.reset_password_token_secret` —
  подпись токенов сброса пароля (роут не задействован в задании, но
  готов к включению).
- `auth_users/user_manager.py::UserManager.verification_token_secret` —
  подпись токенов подтверждения email (аналогично).

Утечка `secret_key` компрометирует все три потока. В dev-режиме это
приемлемо; в прод — строгая изоляция секрета в vault/secret-manager.

---

## 9. Грейбли

### 9.1. `cookie_secure=True` в проде

`settings.auth_users.cookie_secure = False` — дефолт для dev (HTTP).
В прод-размещении за TLS-терминатором нужен
`APP__AUTH_USERS__COOKIE_SECURE=True`, иначе cookie не будет
отправляться по HTTPS. Проверка: при `secure=False` cookie
устанавливается и читается по HTTP; при `secure=True` — только по
HTTPS. Если после включения `secure=True` логин «не работает», в
первую очередь проверьте, не остался ли где-то HTTP (например,
редирект с 80 на 443 не настроен).

### 9.2. Лимит пароля

`settings.auth_users.password_min_length = 8` — минимум, не максимум.
Пароль короче 8 символов → `InvalidPasswordException` → 400
`REGISTER_INVALID_PASSWORD`. Дополнительных требований (заглавные,
цифры, спецсимволы) нет — fastapi-users 14.x по умолчанию
ограничивается только длиной. Если потребуется усложнить — есть
`hook_after_validate_password` в `UserManager`.

### 9.3. Race condition на дубликате email

Перехват `IntegrityError` в `UserManager.create()` (см. §3.3)
устраняет 500 при гонке двух одновременных регистраций. Без этого
фикса `BaseUserManager.create` отдавал 500 вместо штатного 400
`REGISTER_USER_ALREADY_EXISTS` при определённом тайминге.

### 9.4. `POST /auth/jwt/logout` без cookie возвращает 401 (DEF-006)

fastapi-users `get_auth_router` обрабатывает logout через
`AuthenticatedTransport` (cookie). Если cookie нет или она
просрочена — стандартный ответ fastapi-users: **401 Unauthorized**
с `WWW-Authenticate: JWT` заголовком. Это **не баг**, а поведение
по умолчанию в fastapi-users 14.x (донорский шаблон ведёт себя
так же). В фронте `AuthContext.logout()` ловит 401 в `try/except`
и всё равно очищает локальное состояние пользователя — для
пользователя logout выглядит успешным.

Альтернатива (если потребуется «всегда 204 на logout») — обернуть
`/auth/jwt/logout` в кастомный роут, который не вызывает
`logout_user` из transport. Текущее поведение принято как
**работающее как задумано**, см. DEF-006.

### 9.5. RegisterPage UX без поля `username` (DEF-005)

В `RegisterPage` UI остался без изменений — пользователь по-прежнему
вводит `username` в форме, но `/auth/register` его игнорирует
(контракт username отсутствует, см. §5.1 и §2.3). Имя берётся из
email (`email.split("@")[0]`) хуком `on_after_register`. После
регистрации пользователь попадает на страницу логина, входит и
видит, что `username` в профиле — производный от email.

Это **намеренный компромисс**: фронтовая Register UX-форма
(«введите username») и бэкенд (username = из email) разъехались.
Компенсация — `POST /auth/account` позволяет обновить `username` с
любого момента (включая сразу после первого входа). На фронте
AccountPage показывает текущий username и предлагает его изменить.

DEF-005 — `RegisterPage` UX «фантомное поле username»: пользователь
вводит значение, оно отбрасывается на сервере, имя берётся из email.
Поведение работает как задумано (контрактно username не регистрируется
на register, обновляется через account), но UX непоследователен —
отдельная задача на приведение фронта и бэкенда к единому контракту
(либо добавить поле username в `POST /auth/register`, либо убрать поле
из RegisterPage).

### 9.6. `image_file` хранится как голое имя файла

В БД хранится только имя файла (`default.jpg`, `a1b2c3d4.jpg`).
URL собирает фронт: `/static/profile_pics/${user.image_file}`. На
бэкенде эта склейка **не делается** (раньше — двойной префикс
`/static/profile_pics/` ловился багом в `md_articles/helpers_auth.py`,
источник единственный — фронт).

### 9.7. `username` уникален глобально, не «по регистру»

Колонка `username: unique` — это уникальность по строковому
равенству. `username = "Max"` и `username = "max"` считаются разными.
Это потенциальная UX-проблема (пользователь может не найти свой
аккаунт в поиске), но вне рамок задания. Если потребуется — добавить
`lower(username)` индекс.

---

## Приложение А. Карта файлов

```
fastapi-application/auth_users/
├── __init__.py            # экспорты: User, UserManager, auth_backend,
│                          #          fastapi_users, current_user, active_user,
│                          #          optional_user, superuser_user, router
├── models.py              # class User (UUID PK, username, image_file, created_at)
├── schemas.py             # UserRead(BaseUser[UUID]) + username/image_file,
│                          # UserCreate, UserUpdate (пустые наследники BaseUser...)
├── user_manager.py        # UserManager(UUIDIDMixin, BaseUserManager)
│                          #   + validate_password, create (race fix),
│                          #     on_after_register
│                          # + get_user_db / get_user_manager (DI)
├── helpers.py             # save_picture, is_valid_email,
│                          # username_exists, email_exists,
│                          # ERROR_EMAIL_TAKEN, ERROR_USERNAME_TAKEN,
│                          # validation_response
├── auth_backend.py        # cookie_transport, get_jwt_strategy, auth_backend
├── fastapi_users_obj.py   # fastapi_users = FastAPIUsers[User, UUID](...)
│                          # + current_user, active_user, optional_user,
│                          #   superuser_user (готовые Depends)
├── account.py             # POST /auth/account — multipart username/email/picture
└── router.py              # router (включает auth/register/users/account роутеры)
```

Импорт в `main.py`:

```python
from auth_users import router as auth_users_router
include_router_api_frontend(main_app, auth_users_router=auth_users_router)
```

Использование в `md_articles/api_blog.py`:

```python
from auth_users import active_user

async def art_manage_api(_user=Depends(active_user)): ...
```

## Приложение Б. История замены

Подробная история «почему именно fastapi-users» и сравнение с донором —
в [05_authorization_upgrade.md](05_authorization_upgrade.md). Краткая
хронология:

- 2026-09-12, фаза 1 — фундамент `auth_users` (`models`, `schemas`,
  `user_manager`, `helpers`).
- 2026-09-12, фаза 2 — ядро (`auth_backend`, `fastapi_users_obj`,
  `account`, `router`, `AuthUsersConfig`).
- 2026-09-12, фаза 3 — подключение в `main.py`, удаление `api_auth.py`
  /`middleware_auth.py`/`helpers_auth.py`, переключение art-роутов на
  `Depends(active_user)`. Счётчик маршрутов: 41 → 44 (42 было baseline,
  −7 самописных + 9 fastapi-users = 44).
- 2026-09-12, фаза 4 — Alembic-миграция `add_auth_users_user` +
  правка фронта (`client.ts`, `auth.ts`, `types.ts`, `LoginPage`).
- 2026-09-12, фаза 5 — этот документ и sync `QWEN.md`/`AGENTS.md`.
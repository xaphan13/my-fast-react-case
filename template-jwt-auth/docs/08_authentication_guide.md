# 08 — Как и почему устроена авторизация

> Цель этого документа — не перечислять эндпоинты (это в `02_architecture.md` и `03_execution_flow.md`), а **объяснить**, как куски кода складываются в единый механизм: что делает `fastapi-users`, что делает сам проект, где граница ответственности и какие последствия у каждого решения. После прочтения должно быть понятно, **почему** менять `SECRET_KEY` между деплоями — это «убить все сессии», **почему** `CookieTransport` без явного `cookie_secure` опасен, и что именно сломается, если поменять `JWTStrategy.audience`.

Документ покрывает четыре слоя, которые **сцеплены** друг с другом:

1. Хранение паролей (`pwdlib` + Argon2/Bcrypt в `PasswordHelper`).
2. Хранение сессии (JWT в cookie).
3. Dependency Injection (`Authenticator`).
4. Связь с HTMX и SSR (как один и тот же `current_user` работает на холодный GET, на HTMX-POST, и на полный редирект).

---

## 1. Общая картина

```
┌──────────────────────────────────────────────────────────────┐
│  Браузер                                                     │
│   cookie "auth"=<JWT>   (HttpOnly, SameSite=lax, Secure=?)   │
│   + body: form-data для login, JSON для register/profile     │
└─────────────────┬────────────────────────────────────────────┘
                  │ HTTP
┌─────────────────▼────────────────────────────────────────────┐
│  FastAPI                                                     │
│   exception_handler(HTTPException)  ── 401 → HX-Redirect   │
│   ────────────────────────────────────────────────────────  │
│   Depends(fastapi_users.current_user(active=True))           │
│     └─ Authenticator._authenticate                           │
│         ├─ CookieTransport.scheme  (читает cookie "auth")    │
│         ├─ JWTStrategy.read_token (декодирует + читает user) │
│         └─ UserManager.get / _update (операции над User)     │
└─────────────────┬────────────────────────────────────────────┘
                  │ SQLAlchemy async
┌─────────────────▼────────────────────────────────────────────┐
│  SQLAlchemy User (extends SQLAlchemyBaseUserTableUUID)       │
│  ────────────────────────────────────────────────────────   │
│  id, email, hashed_password (Argon2/Bcrypt),                 │
│  is_active, is_superuser, is_verified,                      │
│  created_at, items[]                                         │
└──────────────────────────────────────────────────────────────┘
```

**Ключевая идея:** состояние авторизации — **только в cookie**. Сервер не помнит сессий, не лезет в БД на каждый запрос за валидацией токена (только для `read_token` — `user_manager.get(id)`). Логаут — это **не удаление сессии** (JWT нельзя «отозвать»), а просьба браузеру забыть cookie. Реальная инвалидация возможна только через смену `SECRET_KEY` или жёсткий blacklist (в проекте нет).

---

## 2. Слой 1. Модель и хранение паролей

### 2.1. ORM-модель `User`

Файл: `app/models/user.py:25-33`

```python
class User(SQLAlchemyBaseUserTableUUID, Base):
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow,
    )
    items: Mapped[List["Item"]] = relationship("Item", back_populates="owner")
```

`SQLAlchemyBaseUserTableUUID` (из `fastapi-users-db-sqlalchemy`) приносит:

- `id: UUID` (PK, автогенерация `uuid4()`),
- `email: str(320)` с уникальным индексом,
- `hashed_password: str(1024)` — **хеш**, не сам пароль,
- `is_active: bool` (по умолчанию `True`),
- `is_superuser: bool`,
- `is_verified: bool`.

Поле `created_at` добавлено проектом (для `profile.jinja2`). Поле `items` — обратная сторона `Item.owner_id`. Никаких других полей «из бизнеса» (роль, имя и т.п.) пока нет — `UserManager` и `BaseUserManager` ими не управляют.

### 2.2. Почему `datetime.utcnow` — это плохо (и почему миграция не спасла)

В `app/models/user.py:30` используется `default=datetime.utcnow`. В Python 3.12+ это **deprecated** — naive datetime, не привязан к UTC. Замена — `lambda: datetime.now(timezone.utc)`. Миграция `8d9cb1e66c56_initial_migration.py` (строки 18-22) делает `sa.Column('created_at', sa.DateTime(), nullable=True)` — naive. Если поправить default, нужна новая миграция `alembic revision --autogenerate`. Иначе колонка останется naive и `created_at.strftime("%B %d, %Y")` в `profile.jinja2:84` будет показывать время **на сервере** (если сервер в UTC — сойдёт, но переносить в другую TZ нельзя без скрипта миграции данных).

### 2.3. Хеширование паролей: `pwdlib` + Argon2/Bcrypt

Используется **встроенный** `PasswordHelper` из `fastapi-users==14.0.1` (`fastapi_users/password.py:21-45`):

```python
self.password_hash = PasswordHash((Argon2Hasher(), BcryptHasher()))
```

**Почему два хешера сразу:** `PasswordHash.verify_and_update` проверяет пароль по самому свежему из списка, и **если** пароль захеширован более старым хешером — перехеширует и возвращает новый хеш. То есть в `BaseUserManager.authenticate` (`fastapi_users/manager.py:402-420`):

```python
verified, updated_password_hash = self.password_helper.verify_and_update(
    credentials.password, user.hashed_password,
)
if not verified:
    return None
if updated_password_hash is not None:
    await self.user_db.update(user, {"hashed_password": updated_password_hash})
```

— при логине пользователя, чей хеш был сделан Bcrypt, **тихо** перехешируется в Argon2 при следующем успешном входе. Миграция хешей — бесплатная. Но в **коде проекта** (`app/api/user.py:131-138`) есть собственный `update_password`, который **не** идёт через `authenticate`, а напрямую вызывает `PasswordHelper().verify_and_update` и `PasswordHelper().hash`:

```python
password_helper = PasswordHelper()
is_valid = password_helper.verify_and_update(current_password, user.hashed_password)[0]
...
hashed_password = password_helper.hash(new_password)
user.hashed_password = hashed_password
await db.commit()
```

Это работает, но **теряет auto-upgrade**: если у пользователя Bcrypt-хеш, и он меняет пароль — он останется на Bcrypt, потому что `password_helper.hash` использует первый хешер в списке (`Argon2Hasher`)? Нет — он захеширует через Argon2Hasher (потому что `PasswordHash.hash` по дефолту использует самый свежий). То есть **здесь** авто-апгрейд случается, но более грубо: новый хеш всегда Argon2.

**Важный нюанс для разработки:** `fastapi-users==13.x` использовал `passlib`. В `14.x` переехали на `pwdlib`. Lock-файл это подтверждает: `pwdlib 0.2.1`, `argon2-cffi 23.1.0`, `bcrypt 4.3.0`. Если в `requirements.txt` или в созданной вами ветке случайно появится `passlib` — будут две реализации, и `PasswordHelper` будет использовать одну, а внешний код — другую. Держитесь только того, что импортируется из `fastapi_users.password`.

---

## 3. Слой 2. Транспорт и стратегия сессии

Файл: `app/core/users.py`

```python
cookie_transport = CookieTransport(cookie_name="auth", cookie_max_age=3600)

def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=settings.SECRET_KEY, lifetime_seconds=3600)

auth_backend = AuthenticationBackend(
    name="jwt", transport=cookie_transport, get_strategy=get_jwt_strategy,
)
fastapi_users = FastAPIUsers[User, UUID](get_user_manager, [auth_backend])
```

`AuthenticationBackend` — это **обёртка** из трёх частей:

```
CookieTransport   (внешний мир: cookie <-> HTTP)
   ↓  set_cookie / read cookie
JWTStrategy       (секрет: JWT <-> payload)
   ↓  encode / decode
BaseUserManager   (домен: payload <-> User в БД)
```

### 3.1. `CookieTransport` — внешний интерфейс

Из `fastapi_users/authentication/transport/cookie.py`:

- При **login** (`get_login_response`): `Response(status=204)` + `set_cookie("auth", token, max_age=3600, path="/", secure=True, httponly=True, samesite="lax")`.
- При **logout** (`get_logout_response`): `Response(status=204)` + `set_cookie("auth", "", max_age=0, ...)` — браузер стирает cookie.
- Для каждого запроса `APIKeyCookie(name="auth", auto_error=False)` смотрит в заголовок `Cookie`, **ничего не валидирует** на этом этапе — это работа `JWTStrategy`.

**Почему важно:** `secure=True` в `14.0.1` — дефолт. В `13.x` был `False`. Документы `02_architecture.md:30` и `04_code_quality.md` написаны так, будто `secure` не установлен, — это **ошибка доков**, в коде дефолт 14.x — `True`. Но! `app/core/users.py:11` пишет:

```python
cookie_transport = CookieTransport(cookie_name="auth", cookie_max_age=3600)
```

— **не указывает** `cookie_secure` явно. Это работает, пока вы на 14.x. Но если закрепите `fastapi-users>=13,<14` в `pyproject.toml` (или `pip install` подтянет 13-ю), дефолт внезапно станет `False` — и прод с HTTPS начнёт отдавать cookie по HTTP при даунгрейде протокола. **Фикс:** задавать явно. Это не косметика, это контракт безопасности, который должен быть в коде, а не «наследуется от версии библиотеки».

### 3.2. `JWTStrategy` — содержимое токена

Из `fastapi_users/authentication/strategy/jwt.py`:

```python
data = {"sub": str(user.id), "aud": self.token_audience}   # audience по умолчанию "fastapi-users:auth"
return generate_jwt(data, self.encode_key, self.lifetime_seconds, algorithm="HS256")
```

`generate_jwt` (`fastapi_users/jwt.py:23-30`) добавляет `exp = now() + lifetime`. Алгоритм — **HS256** (симметричный): один и тот же `SECRET_KEY` используется для подписи и проверки. Асимметрия (RS256) тут не включена, `public_key` не задан.

Декодирование (`read_token`):

```python
data = decode_jwt(token, self.decode_key, [self.token_audience], algorithms=["HS256"])
user_id = data.get("sub")
parsed_id = user_manager.parse_id(user_id)
return await user_manager.get(parsed_id)
```

**`user_manager.get(id)` — это запрос в БД** на каждый защищённый запрос. То есть "stateless" в смысле "нет таблицы сессий" — да, но не в смысле "не ходим в БД". `asyncpg`/`aiosqlite` справляются, но если будете делать админку с тысячами RPS, помните: **каждый `current_user(...)` = 1 SELECT**.

### 3.3. Что нельзя сделать с JWT

`JWTStrategy.destroy_token` поднимает `JWTStrategyDestroyNotSupportedError`. Логаут **не инвалидирует** токен: если злоумышленник успел скопировать cookie, он сможет им пользоваться до `exp`. Проект этот сигнал **глотает** (`backend.logout` ловит `StrategyDestroyNotSupportedError`). Штатный сценарий: «пользователь нажал Logout → cookie удалена у браузера → старый токен мёртв на его устройстве, но теоретически жив на чужом». Это известное ограничение JWT-сессий без blacklist.

### 3.4. `audience` — почему это важно

В `JWTStrategy` `token_audience=["fastapi-users:auth"]` принудительно прописан и в `generate_jwt`, и в `decode_jwt`. У `UserManager` есть **две другие** audience для reset-password (`fastapi-users:reset`) и verify (`fastapi-users:verify`). То есть токены разных «назначений» не взаимозаменяемы. Если вы добавляете свой `generate_jwt` где-то в проекте с тем же `SECRET_KEY`, но без `aud` — он не пройдёт `decode_jwt` (упадёт `jwt.InvalidAudienceError`, который `read_token` ловит и возвращает `None`). **Это и есть защита от подмены токенов** между разными потоками.

---

## 4. Слой 3. `UserManager` — мост между БД и сессией

Файл: `app/models/user.py:44-72`

```python
class UserManager(UUIDIDMixin, BaseUserManager[User, UUID]):
    reset_password_token_secret = settings.SECRET_KEY
    verification_token_secret = settings.SECRET_KEY

    async def on_after_register(self, user, request=None): ...
    async def on_after_forgot_password(self, user, token, request=None): ...
    async def on_after_request_verify(self, user, token, request=None): ...
```

### 4.1. Зачем переопределять `on_after_*`

Базовая реализация — пустая (в `fastapi_users/manager.py` каждый `on_after_*` это `return  # pragma: no cover`). Эти хуки — единственное место, где проект **вмешивается** в жизненный цикл пользователя. Сейчас они просто пишут в `logger`. Сюда нужно вешать:

- отправку welcome-email при `on_after_register`,
- отправку письма со ссылкой на reset при `on_after_forgot_password`,
- аналитику/аудит.

Нельзя хук поставить в `app/api/auth.py:38` (`register_user`) — там уже поздно: пользователь создан, и если вы хотите email + rollback, придётся городить try/except вокруг `user_manager.create`. В `on_after_register` пользователь гарантированно в БД — идеально для post-commit side-effects.

### 4.2. `UUIDIDMixin` и почему он обязателен

`User` наследует `SQLAlchemyBaseUserTableUUID` — `id` это `UUID`. Но у `Item` `id` это `Integer` (см. `app/models/item.py:13`). То есть у проекта смешанные типы ID. Если где-то в новой модели понадобится `BaseUserManager[NewUser, int]` — нужен `IntegerIDMixin` (есть в `fastapi_users/manager.py:475-481`). Сейчас — `UUIDIDMixin.parse_id` (`manager.py:468-473`) приводит строку из `sub` JWT к `uuid.UUID`, кидает `InvalidID` при ValueError. Эту ошибку ловит `Authenticator._authenticate` и тихо возвращает `None` (т.е. пользователь «не аутентифицирован»).

### 4.3. `authenticate` — что происходит при логине

Из `fastapi_users/manager.py:402-420`:

```python
try:
    user = await self.get_by_email(credentials.username)
except UserNotExists:
    self.password_helper.hash(credentials.password)  # timing attack mitigation
    return None

verified, updated_password_hash = self.password_helper.verify_and_update(
    credentials.password, user.hashed_password,
)
if not verified: return None
if updated_password_hash is not None:
    await self.user_db.update(user, {"hashed_password": updated_password_hash})
return user
```

`credentials` — это `OAuth2PasswordRequestForm` (из `fastapi.security`). **Не JSON, а form-data** — `username` и `password` в полях формы. Вот почему в `auth/login.jinja2` форма отправляется **без** `hx-ext="json-enc"` — `OAuth2PasswordRequestForm` ждёт `application/x-www-form-urlencoded`. **Это не баг, это контракт.** Сравните с `auth/register.jinja2` — там `hx-ext="json-enc"`, потому что `register_user` принимает `user_create: UserCreate` (Pydantic-модель), и FastAPI парсит JSON.

`credentials.username` — это email (OAuth2-конвенция: `username` — идентификатор). Регистрация требует `email` (см. `UserCreate = schemas.BaseUserCreate` в `app/schemas/user.py:6`). Оба поля обязательны.

**`return None`** — это не «ошибка», это «нет такого пользователя ИЛИ пароль неверный». Их **нельзя различить** по ответу: и в том, и в другом случае `login`-роутер (`fastapi_users/router/auth.py:42-46`) кидает `HTTPException(400, "LOGIN_BAD_CREDENTIALS")`. Это сделано намеренно — чтобы атакующий не узнал, существует ли email.

### 4.4. `create` — что происходит при регистрации

`BaseUserManager.create` (`manager.py:120-148`):

```python
await self.validate_password(user_create.password, user_create)   # пустая в базовом классе
existing_user = await self.user_db.get_by_email(user_create.email)
if existing_user: raise UserAlreadyExists()
user_dict = user_create.create_update_dict() if safe else ...   # safe=True: без is_superuser
password = user_dict.pop("password")
user_dict["hashed_password"] = self.password_helper.hash(password)
created_user = await self.user_db.create(user_dict)
await self.on_after_register(created_user, request)
return created_user
```

`safe=True` в проекте (`app/api/auth.py:42`) — гарантирует, что даже если клиент подсунет `is_superuser=True` в JSON, оно **будет проигнорировано**. Иначе — дыра. Поэтому **никогда** не вызывайте `user_manager.create(user_create, safe=False)` из публичного эндпоинта.

`validate_password` в базовом классе ничего не делает. Проект **не переопределяет** его — поэтому сейчас **любой непустой пароль валиден**. Если в `register.jinja2` `minlength="8"` — это только клиентская проверка; сервер примет и 1 символ. Это **известная дыра** (в `docs/04_code_quality.md` не отмечена явно). Чтобы закрыть:

```python
class UserManager(UUIDIDMixin, BaseUserManager[User, UUID]):
    async def validate_password(self, password, user):
        if len(password) < 8:
            raise InvalidPasswordException(
                reason="Password should be at least 8 characters",
            )
```

— и поймать в `register_user` как `HTTPException(detail={"code": "REGISTER_INVALID_PASSWORD", "reason": ...})`.

---

## 5. Слой 4. Dependency Injection — связь всех частей

### 5.1. Цепочка `current_user`

Когда в роуте написано `user: User = Depends(fastapi_users.current_user(active=True))`, FastAPI разворачивает:

```
Depends(current_user)
  └─ fastapi_users.current_user (метод Authenticator)         ← возвращает callable
       └─ Authenticator.current_user
            └─ _authenticate(...)                              ← бизнес-логика
                 ├─ Depends(get_user_manager) → UserManager
                 ├─ Depends(cookie_transport.scheme)
                 │     (APIKeyCookie, читает cookie "auth")
                 ├─ Depends(get_jwt_strategy) → JWTStrategy
                 └─ user_manager.get(uuid) → SELECT в БД
```

`Authenticator._get_dependency_signature` (`fastapi_users/authentication/authenticator.py:170-203`) собирает сигнатуру динамически через `makefun.with_signature`. Поэтому в OpenAPI у каждого бэкенда появляется **своя security-scheme**: cookie `auth`. В `app/main.py:54` зарегистрирован ровно один бэкенд — `auth_backend` с именем `"jwt"`. Имя важно: оно используется в `name_to_variable_name` (`authenticator.py:25-27`) для генерации параметра зависимости. **Если переименуете backend**, FastAPI перегенерирует сигнатуру — старые cookie остаются валидными, ничего не ломается.

### 5.2. Флаги `current_user(...)`

```python
fastapi_users.current_user()                  # любая аутентификация
fastapi_users.current_user(optional=True)     # None если не залогинен
fastapi_users.current_user(active=True)       # иначе 401
fastapi_users.current_user(verified=True)     # иначе 401 (нужен is_verified)
fastapi_users.current_user(superuser=True)    # иначе 403
```

`optional=True` используется в `app/api/auth.py:18` (`get_login_page`) — чтобы проверить «уже залогинен?» и сделать редирект. `active=True` — в `app/api/items.py:27`, `app/api/user.py:25, 46, 96`, `app/main.py:109` (`/`). **Никогда** в проекте не используется `verified=True` — потому что в регистрации `is_verified=False` по умолчанию (в `SQLAlchemyBaseUserTableUUID`), и если бы использовали — ни один только что зарегистрированный пользователь не мог бы зайти. Это **by design**, но учтите.

`_authenticate` (`authenticator.py:108-138`) ведёт себя так:

- если пользователь найден и `is_active=False` → `401` (не `403`),
- если `verified=True` и `is_verified=False` → `401`,
- если `superuser=True` и `is_superuser=False` → `403`.

То есть неактивный пользователь неотличим по статусу от «нет cookie». Это сознательно — не сообщать, что учётка существует.

### 5.3. Что происходит при `401`

Роут бросает `HTTPException(401)`. Перехватывает `app/main.py:71-103`:

```python
if exc.status_code == 401:
    if is_htmx(request):
        return Response(200, headers={"HX-Redirect": str(login_url)})
    else:
        return RedirectResponse(url=login_url, status_code=302)
```

**Почему 200 + HX-Redirect, а не 401:** HTMX при получении 4xx вызывает `htmx:responseError` (см. `base.jinja2:105-126`) — и пользователь увидит "An error occurred". Чтобы не пугать пользователя модалкой об ошибке на каждый просроченный cookie, проект **подменяет** статус на 200 + `HX-Redirect`. Браузер редиректит на `/auth/login`, в навигации появляется Login/Register.

**Побочный эффект:** HTMX-запрос с реальной ошибкой 401 (например, `user.is_active=False`) тоже уйдёт в login вместо инвалидации. Это — **намеренная** деградация «fail-open».

Для не-HTMX — обычный 302 на `/auth/login`. **Важно:** URL для редиректа вычисляется через `request.url_for("auth_login_page")` — это имя из `app/api/auth.py:16`. Если переименуете — нужно править и `main.py:88`.

### 5.4. Логаут: почему две копии логики

`app/api/auth.py:71-96`:

```python
@router.post("/logout", name="auth_logout")
async def logout_user(request, user=Depends(fastapi_users.current_user())):
    if is_htmx(request):
        return Response(200, headers={
            "HX-Redirect": str(request.url_for("index")),
            "Set-Cookie": "auth=; Path=/; Max-Age=0; ...",
        })
    else:
        response = RedirectResponse(...)
        response.set_cookie("auth", "", max_age=0, ...)
```

— здесь **есть** собственный эндпоинт `POST /auth/logout`, который **не** использует встроенный `/auth/cookie/logout` из `app/main.py:52`. Зачем дубль?

Встроенный `/auth/cookie/logout` возвращает `204 No Content` + `set_cookie("auth", "", max_age=0, ...)`. В **HTMX-контексте** этого мало: HTMX не сделает редирект на 204. Поэтому `app/api/auth.py:71` повторяет работу, но добавляет `HX-Redirect: /` для HTMX-запросов. Не-HTMX ветка просто дублирует ту же очистку cookie, чтобы не зависеть от встроенного роутера.

`base.jinja2:33-34` и `profile.jinja2:235-238` шлют именно на `url_for("auth_logout")` (наш), а не на встроенный. Шаблон `partials/auth_links.jinja2:3-5` ссылается на **несуществующий** `auth_logout_redirect` — баг (отмечен в `04_code_quality.md:1.4`), но шаблон нигде не рендерится (`grep` не находит `{% include "partials/auth_links" %}`).

---

## 6. Связь с HTMX и SSR

### 6.1. Почему `HX-Request: true` важен для авторизации

`HX-Request` не влияет на серверную авторизацию (`Depends(current_user(active=True))` отработает одинаково). Влияет только **способ реакции на 401**:

- HTMX: `Response(200, HX-Redirect=/auth/login)` — браузер инициирует GET (без тела).
- не-HTMX: `RedirectResponse(302, /auth/login)` — браузер сам следует.

Проверка `HX-Request` в `app/api/dependencies.py:10`:

```python
def is_htmx(request: Request) -> bool:
    return str(request.headers.get("HX-Request", "false")).lower() == "true"
```

— `HX-Request` ставит сам HTMX **на клиенте** (см. `unpkg.com/htmx.org@2.0.4` в `base.jinja2:15`). Если браузер посылает запрос мимо HTMX (например, пользователь нажал F5 на `/items`) — `HX-Request` нет, и сервер даст 302 (правильно).

### 6.2. `is_htmx` не должен влиять на саму аутентификацию

`is_htmx` используется **только** для выбора формы ответа в:

- `app/main.py:71` — 401 handler (описано выше).
- `app/api/auth.py:64, 86` — redirect vs HX-Redirect на register/logout.
- `app/api/items.py:84` — full page vs partial table.

Но **не** в `current_user(...)`. Это правильно: если пользователь не аутентифицирован, никакая отрисовка страницы или partial не должна происходить, вне зависимости от типа запроса.

### 6.3. Редиректы из шаблонов

`login.jinja2:52-58`:

```javascript
if (xhr.status === 204) {
    window.location.href = '/';   // полная перезагрузка
}
```

— **204 No Content** на `/auth/cookie/login` = успех (`fastapi_users/router/auth.py:38-44` вызывает `backend.login` → `transport.get_login_response` → `Response(204)` + `set_cookie`). Браузер должен получить cookie и перейти на `/`. HTMX **не** сделает `window.location.href` сам — это **вручную** в JS шаблона. Правильно: нам нужна полная перезагрузка, чтобы обновилась навигация (`{% if user %}` ветка в `base.jinja2`).

Аналогично `register.jinja2` — но там используется `HX-Redirect` от сервера (`auth/api/auth.py:55-58`), что **чище**: сервер решает, куда редиректить, клиент не знает. Логин использует JS-переход потому, что встроенный login-роутер не умеет в `HX-Redirect` (он fastapi-usersовский, не наш).

### 6.4. `current_user` в шаблонах

В `base.jinja2:30` — `{% if user %}`. Откуда `user`? Из контекста `TemplateResponse({"request": request, "user": user})`. В каждом роуте, где есть `Depends(fastapi_users.current_user(...))`, нужно **явно** положить `user` в контекст. Если забыть — на навигации будет «Hello, » (без email) или пустая ветка.

`app/main.py:108-115` (`index`) использует `Depends(fastapi_users.current_user(optional=True))` — то есть в шаблон попадает `User | None`. Правильно: гость видит «Sign Up / Log In», залогиненный — «Profile / Logout». На защищённых роутах `current_user(active=True)` — `User` без `None`, и `{% if user %}` всегда true.

### 6.5. Cookies + HTMX + JSON body

`register.jinja2:13` — `hx-ext="json-enc"` означает, что HTMX **сам** сериализует поля формы в JSON. Это **требует** на клиенте загруженного `htmx.org@1.9.12/dist/ext/json-enc.js` (см. `base.jinja2:16` — версия **не совпадает** с ядром 2.0.4). Это задокументировано в `07_frontend.md:6` как одна из топ-проблем. Если CDN отвалится — JSON-enc не загрузится, форма отправит form-data, сервер примет как `OAuth2PasswordRequestForm` ожидает только на login; на register получит `UserCreate` парсинг по телу как JSON → 422.

---

## 7. Конфигурация `SECRET_KEY`

### 7.1. Где живёт

`app/core/config.py:18`:

```python
SECRET_KEY: str = secrets.token_hex(32)
```

— runtime default. **Это намеренно удобно** для локального dev (не нужно копировать `.env` для первого запуска), но **убивает** все сессии при рестарте: при следующем запуске `secrets.token_hex(32)` сгенерирует новое значение, `JWTStrategy` подпишет новые токены, все старые cookie с `aud=fastapi-users:auth` не пройдут `decode_jwt` (другой secret) — пользователь молча «разлогинивается».

### 7.2. Где **обязательно** должен быть задан

В `.env` (см. `.env.example:13`):

```env
SECRET_KEY=your-secret-key-here
```

`.env` не коммитится (см. `.gitignore` в `docs/01_project_structure.md:18`). В **CI** — `test-secret-key-for-ci-only-not-secure` (`.github/workflows/ci.yml:49, 167`). Это **только для тестов** — в CI никто не логинится, секрет статичен ради детерминизма.

### 7.3. `lifespan` предупреждает, но не валидирует

`app/main.py:30-37`:

```python
key_start = settings.SECRET_KEY[: min(len(settings.SECRET_KEY), 8)]
logger.info("Using SECRET_KEY starting with: %s...", key_start)
logger.info("Ensure SECRET_KEY is set persistently in your .env file ...")
```

— это **только** log. Никакого `assert settings.SECRET_KEY` (как требует `docs/05_optimization_roadmap.md:refactor.3`). Если `.env` пуст — приложение запустится, но все сессии будут мертвы. **Прод-фикс:**

```python
@field_validator("SECRET_KEY")
@classmethod
def require_in_production(cls, v):
    if not settings.is_dev:  # добавить в Settings флаг
        if v.startswith("your-secret-key-here") or len(v) < 32:
            raise ValueError("SECRET_KEY must be set explicitly in production")
    return v
```

### 7.4. Что использует `SECRET_KEY` ещё

`UserManager.reset_password_token_secret` и `verification_token_secret` — **тот же** `SECRET_KEY` (`app/models/user.py:45-46`). То есть смена `SECRET_KEY` инвалидирует:

- активные login-сессии (через `JWTStrategy`),
- активные reset-password токены (в email-письмах, если их рассылаете),
- активные verify-email токены.

Это **свойство проекта**: один секрет на всё. Если хотите разделить — нужно завести отдельные `Settings`-поля и переопределить токен-секреты в `UserManager`.

---

## 8. Расширение: что можно добавить

### 8.1. Email-верификация

`BaseUserManager.request_verify` (`manager.py:241-263`) уже всё умеет — нужно только:

1. Подключить `fastapi_users.get_verify_router(UserRead)` в `app/main.py`.
2. В `on_after_request_verify` отправлять email с токеном.
3. В `register_user` после создания вызвать `await user_manager.request_verify(user, request)`.
4. Поменять `active=True` на `verified=True` в `current_user(...)` где нужно.

### 8.2. Reset password

То же самое с `get_reset_password_router()`. Хук `on_after_forgot_password` — единственное место, откуда отправляется письмо со ссылкой `/reset-password?token=...`.

### 8.3. OAuth

`fastapi-users` поддерживает OAuth через `httpx-oauth` (видно в `fastapi_users/fastapi_users.py:18-22`). В `uv.lock` этого пакета нет — нужно добавить `httpx-oauth[starlette]`. После — `fastapi_users.get_oauth_router(client, auth_backend, state_secret)`. `state_secret` — это **отдельный** JWT-секрет для OAuth state, его нужно добавить в `Settings`.

### 8.4. Свой `CookieTransport` с явными флагами

Сейчас `app/core/users.py:11` полагается на дефолт `secure=True` из 14.x. Лучше:

```python
cookie_transport = CookieTransport(
    cookie_name="auth",
    cookie_max_age=3600,
    cookie_secure=True,        # явно: контракт безопасности в коде
    cookie_httponly=True,
    cookie_samesite="lax",
)
```

— и в dev-окружении передавать `cookie_secure=False` через переменную окружения (FastAPI Settings).

### 8.5. Серверный blacklist для logout

Если нужен «real logout» (не только забыть cookie, но и инвалидировать токен на сервере) — замените `JWTStrategy` на кастомный, который хранит `jti` (jwt id) в Redis/БД. `JWTStrategy` намеренно не имеет `destroy_token` — это by design.

---

## 9. Что не нужно трогать без причины

| Слой | Файл | Что может сломаться |
|---|---|---|
| `UUIDIDMixin` | `app/models/user.py:55` | `user_manager.get(id)` начнёт падать — все защищённые роуты 401. |
| `SQLAlchemyBaseUserTableUUID` | `app/models/user.py:25` | Переименование полей — миграция + ломает все `current_user`. |
| `CookieTransport(cookie_name="auth")` | `app/core/users.py:11` | Переименование — все cookie протухнут, нужен dual-read. |
| `JWTStrategy(secret=settings.SECRET_KEY)` | `app/core/users.py:15` | Ротация секрета = инвалидация всех сессий. |
| `AuthenticationBackend(name="jwt", ...)` | `app/core/users.py:18` | Имя `"jwt"` участвует в `name_to_variable_name` для генерации сигнатуры зависимости. Без нужды не менять. |
| `auth_backend` в `app/main.py:52` | `app/main.py:52` | Регистрация роутера на `/auth/cookie/{login,logout}` — менять префикс значит менять форму входа. |

---

## 10. Резюме: что происходит за один `GET /items`

```
1. Браузер: GET /items, Cookie: auth=<jwt>
2. FastAPI → exception_handler не срабатывает
3. Depends(is_htmx) → False (нет HX-Request)
4. Depends(fastapi_users.current_user(active=True))
   ├─ APIKeyCookie читает cookie "auth" → token = "<jwt>"
   ├─ JWTStrategy.read_token(token, user_manager):
   │    ├─ jwt.decode(token, SECRET_KEY, audience=["fastapi-users:auth"])
   │    ├─ user_id = payload["sub"]
   │    └─ await user_manager.get(uuid) → SELECT user WHERE id=? → User
   ├─ user.is_active == True ✓
   └─ return User
5. Depends(get_db) → AsyncSession (get_db в app/core/database.py:33)
6. app/api/items.py:list_items:
   ├─ SELECT items WHERE owner_id = user.id [AND title ILIKE ...]
   ├─ COUNT → total
   ├─ OFFSET/LIMIT → items
   └─ templates.TemplateResponse("items/index.jinja2", context) (не htmx — full page)
7. Браузер: рендерит base.jinja2 → навигация уже знает {% if user %}, шапка с email
```

То же самое для `HX-Request: true` — отличие только в шаге 6: `items/_table.jinja2` вместо `items/index.jinja2`, и при `401` шаг 2 ведёт в `Response(200, HX-Redirect)`.

Это **один** механизм для обоих случаев — нет «двух разных авторизаций» для SSR и HTMX. Разница — только в ответе.

---

## 11. Связанные файлы

| Файл | Зачем в гайде |
|---|---|
| `app/core/users.py` | Конфигурация транспорта/стратегии/бэкенда. |
| `app/core/config.py` | `SECRET_KEY` и его последствия. |
| `app/models/user.py` | `User` (поля) + `UserManager` (хуки). |
| `app/api/auth.py` | Custom register/logout поверх встроенных. |
| `app/api/user.py` | Кастомный profile с `dict[str, Any]` — нарушает конвенцию Pydantic, см. `04_code_quality.md:1.2`. |
| `app/main.py` | Регистрация роутеров + 401 handler. |
| `app/api/dependencies.py:6-7` | `get_db` — мёртвый код, **не** используется (см. `04_code_quality.md:1.2`). |
| `app/templates/base.jinja2` | Навигация `{% if user %}`, обработка `htmx:responseError` для 5xx. |
| `app/templates/auth/login.jinja2` | form-data, обработка 204/400. |
| `app/templates/auth/register.jinja2` | json-enc, `HX-Redirect` от сервера. |

Связанные документы:

- `docs/02_architecture.md` — общая архитектура, DI-цепочка.
- `docs/03_execution_flow.md` — логика и поток кода (но с устаревшими номерами строк).
- `docs/04_code_quality.md` — список проблем, часть из которых упомянута здесь.
- `docs/07_frontend.md` — клиентские детали HTMX, в т.ч. версионный конфликт `json-enc`.

---

## 12. Ограничения JWT-сессий (чек-лист)

Эта секция — компактный чек-лист для разработчика, который переносит шаблон в новый
проект. Каждый пункт — **свойство** выбранной механики (JWT в cookie через
`fastapi-users`), а **не** дефект конкретной реализации. Если переносимый проект
предъявляет требования, противоречащие этим пунктам, нужен не «фикс», а замена
механизма (см. раздел 8.5 — серверный blacklist).

- [ ] **Logout чистит только cookie; уже выпущенный JWT продолжает работать до `exp`.**
  `logout_user` (`app/api/auth.py`) выдаёт `Set-Cookie: auth=; Max-Age=0; ...` —
  это просьба браузеру забыть cookie. На сервере `JWTStrategy.destroy_token` поднимает
  `JWTStrategyDestroyNotSupportedError` (`fastapi_users/authentication/strategy/jwt.py`),
  и проект её глотает. Если злоумышленник успел скопировать `auth=...` **до** логаута,
  токен остаётся валидным до `exp = now() + lifetime_seconds` (`app/core/users.py`,
  `lifetime_seconds=settings.AUTH_COOKIE_MAX_AGE`). Защита — короткое `lifetime_seconds`,
  `cookie_secure=True` (`Settings.AUTH_COOKIE_SECURE`, раздел 7) и ротация `SECRET_KEY`
  при подозрении на компрометацию. Полная инвалидация — только через смену `SECRET_KEY`
  (см. раздел 7.4) или серверный blacklist (раздел 8.5).

- [ ] **Смена пароля не инвалидирует другие уже выпущенные токены.**
  `update_password` (`app/api/user.py`, фаза 2a) перезаписывает `hashed_password`
  в БД, но **не** трогает JWT-payload, подписанный `settings.SECRET_KEY`. Все cookie,
  выданные на других устройствах (телефон, второй браузер, украденная сессия), проходят
  `decode_jwt` со старым валидным `sub` и `aud` — пока не истёк `exp`. То же касается
  смены email (`update_email`): JWT привязан к `user.id`, а не к `email`, поэтому
  после `update(email=...)` старые токены продолжают работать. **Следствие для
  переносимого проекта:** «разлогинить все устройства» = ротация `SECRET_KEY`
  (см. раздел 7.4), а не смена пароля.

- [ ] **Каждый вызов `current_user(...)` выполняет `SELECT` пользователя в БД.**
  `Authenticator._authenticate` (`fastapi_users/authentication/authenticator.py:108-138`)
  на каждый защищённый запрос: читает cookie → `JWTStrategy.read_token` →
  `user_manager.get(uuid)` → `SELECT user WHERE id = ?`. Это **не** «stateless» в смысле
  «не ходим в БД»: stateless — только таблица сессий, но не сам запрос пользователя.
  Стоимость: один лишний `SELECT` на запрос, плюс валидация подписи (`jwt.decode`,
  CPU). При высоком RPS — либо `pgbouncer`/Redis-кэш перед `current_user`, либо
  кастомная стратегия, которая кэширует `(user_id) -> User` в памяти процесса с
  коротким TTL. Удалять `current_user(...)` в роутах ради «производительности»
  нельзя: это единственная точка, где проверяется `is_active` (раздел 5.2).

### 12.1. Сводка: что означает каждый пункт для переносимого проекта

| Пункт | Где видно | Что делать, если требование противоречит |
|---|---|---|
| Logout не равно invalidation | `app/api/auth.py:logout_user`; `fastapi_users/.../jwt.py:destroy_token` | Серверный blacklist (`jti` → revoked), см. раздел 8.5. |
| Смена пароля не равно «разлогинь всех» | `app/api/user.py:update_password`; `JWTStrategy(secret=settings.SECRET_KEY)` | Ротация `SECRET_KEY` (раздел 7.4) или кастомный `JWTStrategy` со списком отзыва. |
| `current_user` = `SELECT` | `fastapi_users/authentication/authenticator.py:_authenticate`; `UserManager.get` | Кэш перед зависимостью или альтернативный носитель сессии (stateful cookie + Redis). |

### 12.2. Что **не** считается ограничением этой секции

- Срок жизни токена (`AUTH_COOKIE_MAX_AGE`, по умолчанию 3600 c) — это **настройка**,
  а не свойство JWT. Можно крутить без смены механизма.
- `aud=fastapi-users:auth` (раздел 3.4) — защита от подмены токенов между разными
  потоками (`reset`, `verify`), не ограничение сессии.
- `HttpOnly` + `SameSite=lax` + `Secure` (раздел 3.1) — это **усиление** cookie-канала,
  не отменяет пункт 1.

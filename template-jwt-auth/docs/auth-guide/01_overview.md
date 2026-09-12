# 01 — Общая картина

## Что делает библиотека, а что — проект

Авторизация в этом проекте построена на **fastapi-users 15.0.5** +
**fastapi-users-db-sqlalchemy 7.0.0** (версии зафиксированы в `uv.lock`).
Библиотека берёт на себя рутину с безопасностью, проект — только «склейку»
и сервер-сайд рендеринг.

| Задача | Кто делает | Где |
|---|---|---|
| Хеширование паролей (Argon2/Bcrypt) | библиотека (`PasswordHelper`, pwdlib) | внутри fastapi-users |
| Генерация и проверка JWT (HS256) | библиотека (`JWTStrategy`, pyjwt) | внутри fastapi-users |
| Установка/чтение cookie | библиотека (`CookieTransport`) | внутри fastapi-users |
| Валидация email | библиотека (`email-validator`) | внутри fastapi-users |
| Роуты login/logout по протоколу OAuth2-формы | библиотека (`get_auth_router`) | внутри fastapi-users |
| Модель `User` в БД | **проект** (наследование от базовой таблицы) | `app/models/user.py` |
| Бизнес-хуки регистрации (email, аудит) | **проект** (`on_after_*`) | `app/models/user.py` |
| HTML-страницы входа/регистрации | **проект** (Jinja2 + HTMX) | `app/api/auth.py`, шаблоны |
| Реакция на 401 (редирект, HTMX-совместимая) | **проект** | `app/main.py` |
| Профиль и смена пароля | **проект** | `app/api/user.py` |

**Ключевой принцип стиля:** проект не пишет криптографию, хеширование и
парсинг токенов вообще. Всё, что проект добавляет — это DI-обвязка, HTML и
адаптация ответов под HTMX.

## Три компонента fastapi-users

Всё ядро авторизации — три объекта в `app/core/users.py`, которые
сцепляются так:

```
CookieTransport          — «внешний мир»: cookie <-> HTTP
   |  login:  Response(204) + Set-Cookie: auth=<JWT>
   |  каждый запрос: читает cookie "auth" (APIKeyCookie), НЕ валидирует
   v
JWTStrategy              — «содержимое»: JWT <-> payload {sub, aud, exp}
   |  write_token: подписывает HS256-токен с sub=user.id
   |  read_token:  проверяет подпись/срок/audience, достаёт sub
   v
AuthenticationBackend    — «обёртка», связывает транспорт и стратегию
   |
   v
BaseUserManager          — «домен»: payload.sub -> SELECT user -> User
```

Зачем такое разделение: транспорт и стратегия **независимы**. Можно заменить
cookie на Bearer-заголовок, не трогая JWT; можно заменить JWT на
DatabaseStrategy (таблица сессий), не трогая cookie. В этом проекте выбрана
комбинация **cookie + JWT** — она правильна для server-side рендеринга:

- cookie автоматически отправляется браузером с каждым запросом — HTMX-запросы
  и полные переходы аутентифицируются одинаково, без JS-обвязки с токенами;
- JWT stateless: не нужна таблица сессий и не нужен Redis;
- токен живёт ровно `lifetime_seconds` (3600), потом пользователь тихо
  «разлогинивается» на следующем запросе.

## Поток запроса: логин

```
1. Браузер: POST /auth/cookie/login
   Content-Type: application/x-www-form-urlencoded
   body: username=user@example.com&password=secret
   (формат OAuth2PasswordRequestForm — это контракт библиотеки)

2. get_auth_router(auth_backend).login:
   ├─ user_manager.authenticate(credentials)
   │    ├─ SELECT user WHERE email = username
   │    ├─ если пользователя нет: password_helper.hash(password)  <- защита от
   │    │                                                          timing-атак, return None
   │    ├─ password_helper.verify_and_update(password, hash)
   │    └─ если хеш устаревшего формата — тихо перехешировать в БД
   ├─ user is None или is_active=False -> HTTPException(400, LOGIN_BAD_CREDENTIALS)
   └─ backend.login(strategy, user):
        ├─ token = strategy.write_token(user)      # JWT с sub=user.id
        └─ transport.get_login_response(token)     # 204 + Set-Cookie: auth=<JWT>

3. Браузер сохраняет cookie (HttpOnly, SameSite=lax, Secure, Max-Age=3600).
   JS шаблона login.jinja2 видит 204 и делает window.location.href = '/'.
```

## Поток запроса: защищённая страница

На примере `GET /items` (`app/api/items.py:20-28`):

```
1. Браузер: GET /items, Cookie: auth=<JWT>

2. FastAPI разрешает зависимости роута:
   user = Depends(fastapi_users.current_user(active=True))
     └─ Authenticator._authenticate:
          ├─ cookie_transport.scheme (APIKeyCookie) читает cookie "auth"
          ├─ strategy.read_token(token, user_manager):
          │    ├─ jwt.decode(token, SECRET_KEY, audience=["fastapi-users:auth"])
          │    │    <- ошибка подписи/срока/audience => None (не 500!)
          │    ├─ user_id = payload["sub"]
          │    └─ await user_manager.get(uuid)  <- это SELECT в БД, КАЖДЫЙ запрос
          └─ active=True: user.is_active == False => HTTPException(401)

3. Если 401 — срабатывает exception_handler из app/main.py:
   ├─ HTMX-запрос (заголовок HX-Request: true):
   │     Response(200, headers={"HX-Redirect": "/auth/login"})
   └─ обычный запрос: RedirectResponse("/auth/login", 302)

4. Иначе роут выполняется: SELECT items WHERE owner_id = user.id, рендер.
```

Важно: **«stateless» относится к сессиям, а не к нагрузке**. Каждый запрос с
`current_user` — это один `SELECT` пользователя из БД. Для этого проекта это
нормально; для высоконагруженных систем — кэш или DatabaseStrategy.

## Почему логаут «настоящий» только наполовину

JWT нельзя отозвать — он валиден до `exp`, где бы ни хранился.
`JWTStrategy.destroy_token` в библиотеке просто бросает исключение
`JWTStrategyDestroyNotSupportedError` (см. `fastapi_users/authentication/strategy/jwt.py:71`).
Логаут в этом проекте = «попросить браузер забыть cookie». Скопированная
злоумышленником cookie проживёт до истечения срока. Единственная серверная
инвалидация — смена `SECRET_KEY` (убивает ВСЕ сессии) или собственный blacklist
(в проекте отсутствует, см. [08](08_porting_checklist.md#расширения)).

## Карта URL

| URL | Метод | Источник | Назначение |
|---|---|---|---|
| `/auth/cookie/login` | POST | `get_auth_router` (`app/main.py:51-55`) | вход, form-data, ответ 204 + cookie |
| `/auth/cookie/logout` | POST | `get_auth_router` | выход, 204 + очистка cookie (в UI не используется) |
| `/auth/login` | GET | `app/api/auth.py:16` | HTML-страница входа |
| `/auth/register` | GET | `app/api/auth.py:27` | HTML-страница регистрации |
| `/auth/register` | POST | `app/api/auth.py:38` | создание пользователя, JSON-тело |
| `/auth/logout` | POST | `app/api/auth.py:71` | выход с редиректом (используется UI) |
| `/users/me` | GET/PATCH | `get_users_router` (`app/api/user.py:178-182`) | API текущего пользователя |
| `/users/{id}` | GET/PATCH/DELETE | `get_users_router` | API пользователя (только superuser) |
| `/profile` | GET | `app/api/user.py:21` | HTML-профиль |
| `/profile/email` | PATCH | `app/api/user.py:42` | смена email (HTMX) |
| `/profile/password` | PATCH | `app/api/user.py:89` | смена пароля (HTMX) |

Проверка: `uv run python -c "from app.main import app; print(len(app.openapi()['paths']))"` → 15.

## Версии (на момент написания)

| Пакет | Версия | Значение для авторизации |
|---|---|---|
| `fastapi-users[sqlalchemy]` | 15.0.5 | `pwdlib` (Argon2+Bcrypt), pyjwt, дефолт `cookie_secure=True` |
| `fastapi-users-db-sqlalchemy` | 7.0.0 | `SQLAlchemyBaseUserTableUUID`, `SQLAlchemyUserDatabase` |
| `email-validator` | >=2.1.1 | валидация email при регистрации |
| `python-multipart` | >=0.0.6 | парсинг form-data для `OAuth2PasswordRequestForm` |
| `pydantic-settings` | >=2.2.1 | `SECRET_KEY` из `.env` |

В `pyproject.toml` стоит `fastapi-users[sqlalchemy]>=13.0.0` — нижняя граница
уступает реально установленной 15.0.5. **При переносе закрепляйте версию**
(например `>=15,<16`): между 13.x и 15.x менялись хеш-библиотека (passlib →
pwdlib) и дефолты cookie.

Дальше: [02_core_wiring.md](02_core_wiring.md) — ядро авторизации построчно.

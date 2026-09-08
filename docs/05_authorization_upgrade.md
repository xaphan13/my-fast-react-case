# 05. Авторизация: как улучшить или заменить

> Продолжение [04_authorization.md](04_authorization.md): там разобрано, как
> устроен текущий слой и почему он такой; здесь — куда его развивать. Два пути:
> **A** — точечно укрепить существующую самописную схему (~50–150 строк) и
> **B** — заменить её готовой библиотекой (fastapi-users и другие). Для каждого
> пункта: что даёт, сколько стоит, с примерами кода. Версии библиотек и их API
> сверены с официальной документацией на 2026-09 (fastapi-users 15.0.5).

---

## Содержание

1. [Дерево решений: укрепить или заменить](#1-дерево-решений-укрепить-или-заменить)
2. [Путь A: укрепление текущей схемы](#2-путь-a-укрепление-текущей-схемы)
3. [Путь B: замена на библиотеку](#3-путь-b-замена-на-библиотеку)
4. [Сравнение: сейчас / укрепить / заменить](#4-сравнение-сейчас--укрепить--заменить)
5. [Что даст замена: преимущества и цена](#5-что-даст-замена-преимущества-и-цена)
6. [Рекомендация для этого репозитория](#6-рекомендация-для-этого-репозитория)
7. [Чеклист безопасности: что уже закрыто](#7-чеклист-безопасности-что-уже-закрыто)

---

## 1. Дерево решений: укрепить или заменить

Вопросы, которые определяют путь:

| Вопрос | Ответ → путь |
|---|---|
| Нужны ли email-верификация, сброс пароля, роли, OAuth (Google/GitHub)? | да → **B**; нет → дальше |
| Будут ли мобильные клиенты или сторонние потребители API? | да → **B** (+JWT-транспорт); нет → дальше |
| Проект учебный / небольшое внутреннее приложение? | да → **A** (или ничего); нет → дальше |
| Готовность тащить зависимости и разбираться в чужой архитектуре? | нет → **A** |

Практическое правило: **A — это гигиена** (закрыть слабости из §7 документа 04
за один вечер), **B — это продуктовые фичи** (верификация, сброс, роли, OAuth).
Их можно комбинировать: сначала A, потом B — миграция станет только проще,
потому что слабые места уже будут помечены.

---

## 2. Путь A: укрепление текущей схемы

Каждый пункт независим; порядок — по соотношению «польза/усилия».

### A1. Обязательный `secret_key` (закрывает слабость №1)

Дефолт `"dev-insecure-secret-key-change-me"` в `core/config.py:22` годится для
dev; в проде подделка любой сессии. Минимальный вариант — предупреждение,
строгий — отказ стартовать:

```python
# core/config.py
from pydantic import BaseModel, model_validator

class WebConfig(BaseModel):
    secret_key: str = "dev-insecure-secret-key-change-me"

    @model_validator(mode="after")
    def _warn_insecure_secret(self) -> "WebConfig":
        if self.secret_key.startswith("dev-insecure"):
            logF.warning(
                "web.secret_key — dev-значение; для прода задайте APP__WEB__SECRET_KEY"
            )
        return self
```

Строгий вариант: тот же валидатор, но `raise ValueError` при активном
прод-профиле БД (`settings.db.url` не sqlite) — приложение не поднимется с
dev-ключом в проде. Усилия: ~10 строк.

### A2. Флаги cookie для прод-HTTPS (№6)

`SessionMiddleware` умеет `Secure`-флаг (параметр `https_only`), в проекте он
не включается. За TLS-прокси (nginx) нужно включать и не забыть про
заголовок протокола:

```python
# md_articles/middleware_auth.py::add_middleware_auth
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.web.secret_key,
    max_age=14 * 24 * 3600,
    same_site="lax",
    https_only=settings.web.cookie_secure,   # новое поле, True в прод-профиле
)
```

Нюанс: при запуске за прокси uvicorn должен получать реальную схему —
`--proxy-headers --forwarded-allow-ips="*"` (иначе `Request.url` будет `http`,
а Starlette-хелперы, зависящие от схемы, будут врать). Усилия: ~5 строк + поле
конфигурации.

### A3. Ротация сессии при логине (№3, session fixation)

Сейчас `login_user` дописывает `user_id` в уже существующую сессию — если
злоумышленник заранее «зафиксировал» сессию на общем компьютере, он останется
в ней после входа жертвы. Правильная гигиена — сброс сессии при повышении
привилегий:

```python
# md_articles/helpers_auth.py
import secrets

def login_user(request: Request, user_id: int) -> None:
    # анти-fixation: чистим прежнее содержимое сессии и выдаём свежий CSRF
    request.session.clear()
    request.session["user_id"] = user_id
    request.session["csrf_token"] = secrets.token_hex(32)
```

Совместимость с фронтом сохраняется автоматически: `postJson` перед каждым
POST заново запрашивает `GET /api/blog/csrf`, так что новый токен подхватится
без правок клиента. Усилия: 3 строки.

### A4. Минимальная политика пароля (№5)

Сейчас проверяется только непустота. Два готовых места для ограничения:

- в `register_api`: `elif len(payload.password) < 8: errors...` — самый дешёвый
  вариант, в стиле текущей ручной валидации;
- через pydantic — см. A6, где это получается «бесплатно» при переезде
  валидации в схему.

Верхнюю границу тоже стоит поставить: **bcrypt использует только первые 72
байта** пароля — длиннее задавать бессмысленно (байт, не символов; кириллица в
UTF-8 — 2 байта на символ). Усилия: 1–2 строки.

### A5. Rate-limit на `/login` и `/register` (№2)

Брутфорс сейчас не ограничен ничем. Стандартный инструмент — `slowapi`
(порт flask-limiter для FastAPI/Starlette):

```python
# uv add slowapi
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)          # ключ = IP клиента
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@router_auth_api.post("/login", name="auth.login")
@limiter.limit("5/minute")                               # 5 попыток в минуту на IP
async def login_api(request: Request, ...):              # request обязателен
    ...
```

Для учебного проекта хватит IP-лимита; следующий уровень — связка IP+email и
хранение счётчиков в Redis (`storage_uri="redis://..."` в `Limiter`). Усилия:
~15 строк + зависимость.

### A6. Валидация в pydantic вместо ручных проверок

Самый крупный рефакторинг пути A: `RegisterIn` сейчас — четыре строки с
дефолтами `""`, а все проверки (~25 строк) живут в роуте. Pydantic умеет всё
то же, а кастомный 422-обработчик (`middleware_auth.py:99`) уже переводит его
ошибки в формат `{"errors": {поле: [...]}}` — **фронтенд не заметит подмены**:

```python
# md_articles/schema_blog.py
from pydantic import BaseModel, EmailStr, Field, model_validator

class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=20)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    confirm_password: str

    @model_validator(mode="after")
    def _passwords_match(self) -> "RegisterIn":
        if self.password != self.confirm_password:
            raise ValueError("Fields must match.")
        return self
```

Что это даёт: −25 строк в `register_api`, проверки объявлены рядом с типами,
OpenAPI-схема честно показывает ограничения. Нюанс: ошибка из `model_validator`
относится к модели целиком — в 422-формате проекта она попадёт в ключ `body`,
а не в поле; чтобы привязать её к `confirm_password`, как сейчас, нужен
`field_validator`. Цена: сообщения генерирует pydantic (тексты будут вида
`String should have at least 8 characters`), поэтому если нужны точные прежние
формулировки — их придётся настраивать. Промежуточный вариант: перенести в
pydantic только часть проверок (длину, email), оставив уникальность и
«совпадение паролей» в роуте. Усилия: ~1 час с тестами curl.

### A7. Email-верификация и сброс пароля (№9)

Самая объёмная доработка пути A, из-за которой обычно и переходят к пути B.
Технически всё строится на подписанных токенах со сроком жизни — `itsdangerous`
уже в зависимостях (его использует `SessionMiddleware`):

```python
from itsdangerous import URLSafeTimedSerializer

reset_ser = URLSafeTimedSerializer(settings.web.secret_key, salt="password-reset")
verify_ser = URLSafeTimedSerializer(settings.web.secret_key, salt="email-verify")

token = reset_ser.dumps({"user_id": user.id})        # в письмо /api/blog/reset/<token>
data = reset_ser.loads(token, max_age=3600)          # проверка при переходе: 1 час
```

Дальше нужны: два POST-роута (`forgot_password` — принимает email, молча
отвечает 200 даже если его нет; `reset_password` — токен + новый пароль), место
хранения `is_verified` у `BlogUser` и отправка писем (в dev — логгер, в проду —
SMTP/aioSMTP). Соль (`salt=...`) разделяет пространства токенов: reset-токен
не сработает как verify-токен. Усилия: 100–200 строк — уже конкурирует с
путём B.

### A8. Constant-time сравнение CSRF (№8)

```python
import secrets
if not secrets.compare_digest(form_token, session_token): ...
```

Формальная строгость: сравнение не «сдаётся» на первом несовпадающем байте.
Практический выигрыш минимален (токен случайный, 64 hex-символа), но строже по
OWASP. Усилия: 2 строки в двух валидаторах.

### A9. Производительность middleware (№11, опционально)

SELECT по целочисленному PK — микросекунды на SQLite; на PostgreSQL при
тысячах RPS это станет заметным. Порядок действий: **ничего не делать**, пока
нет измеримой проблемы; затем — кэш в памяти процесса
(`{user_id: (user_snapshot, expires_at)}` с TTL 30–60 c и инвалидацией в
`account_post_api`), затем — серверные сессии (см. §4 документа 04). Кэш
усложняет мгновенный отзыв (главную фичу текущей схемы) — поэтому только по
измерениям.

### Сводка пути A

| # | Улучшение | Закрывает слабость | Усилия |
|---|---|---|---|
| A1 | контроль secret_key | №1 | ~10 строк |
| A2 | Secure-флаг cookie | №6 | ~5 строк + конфиг |
| A3 | ротация сессии при логине | №3 | 3 строки |
| A4 | длина пароля 8–72 | №5 | 1–2 строки |
| A5 | slowapi на login/register | №2 | ~15 строк + dep |
| A6 | валидация в pydantic | упрощение кода | ~1 час |
| A7 | verify + reset пароля | №9 | 100–200 строк |
| A8 | compare_digest | №8 | 2 строки |
| A9 | кэш пользователя | №11 | по потребности |

A1–A5 + A8 — примерно 50 строк суммарно и закрывают всё «дешёвое». A6 —
улучшение поддерживаемости. A7 — уже половина пути к B.

---

## 3. Путь B: замена на библиотеку

### 3.1. Карта кандидатов

| Библиотека | Что закрывает | Когда брать |
|---|---|---|
| **fastapi-users** | register/login/logout, verify email, reset password, роли (superuser), OAuth, 2 транспорта + 3 стратегии | нужен полный продуктовый цикл аккаунтов |
| **authlib** | OAuth2-клиент (социальный вход) и OAuth2-сервер, JWT | нужен именно OAuth/JWT-слой, своя обвязка |
| **fastapi-login** | только login/logout на JWT | минимальная замена своего кода без фич |
| **pyjwt** / python-jose | кодирование/проверка JWT сами по себе | строительный блок, не решение |
| **fastapi-csrf-protect** | CSRF-токены (выдача/проверка, cookie) | замена самописного CSRF без остального |
| **slowapi** | rate-limiting | компонент, сочетается с любым путём |

Для этого проекта главный кандидат — **fastapi-users**: он закрывает ровно те
пробелы текущей схемы (verify, reset, роли), не меняя транспорт (cookie
остаётся). Остальные — либо блоки, либо частичные решения.

### 3.2. fastapi-users: что это и в каком он состоянии

Это самый распространённый full-stack-решатель авторизации для FastAPI:
регистрация с письмом-верификацией, вход/выход, сброс пароля, флаги
`is_active` / `is_verified` / `is_superuser`, зависимости доступа с тонкой
настройкой, OAuth через `httpx-oauth`, адаптеры SQLAlchemy/Beanie/SQLModel.

Архитектура из четырёх понятий:

- **Модель пользователя** — ваш ORM-класс + обязательные поля библиотеки
  (`email`, `hashed_password`, `is_active`, `is_verified`, `is_superuser`).
- **`UserManager`** — точка кастомизации: хуки `on_after_register`,
  `on_after_forgot_password`, `on_after_request_verify`, куда вписывается
  отправка писем.
- **Backend = транспорт × стратегия.** Транспорт: `CookieTransport` (браузер)
  или `BearerTransport` (API/мобильные). Стратегия: `JWTStrategy` (stateless),
  `DatabaseStrategy` (серверное хранение), `RedisStrategy`.
- **Роутеры** — готовые эндпоинты: `get_auth_router` (login/logout),
  `get_register_router`, `get_verify_router`, `get_reset_password_router`,
  `get_users_router` (me/PATCH/DELETE).

**Состояние на 2026-09: версия 15.0.5, проект в maintenance mode.** Авторы
поддерживают безопасность и зависимости, но новые фичи не планируют — они
делают новую библиотеку-преемника. Практический вывод: для учебного проекта и
небольших приложений это не препятствие (код стабилен и широко используется),
но в долгоживущий продукт закладывайте риск смены библиотеки и смотрите на
преемника, когда он выйдет.

### 3.3. Ключевые фрагменты (сверено с документацией 15.x)

Установка: `uv add "fastapi-users[sqlalchemy]"`.

**Модель.** Наш `int`-первичный ключ поддерживается напрямую — базовый класс
параметризуется типом id:

```python
# md_articles/models.py
from fastapi_users.db import SQLAlchemyBaseUserTable

class BlogUser(SQLAlchemyBaseUserTable[int], Base):
    """Базовый класс даёт email, hashed_password, is_active, is_verified, is_superuser."""
    id: Mapped[int_primary_key]
    username: Mapped[str_len_20] = mapped_column(unique=True)
    image_file: Mapped[str_len_20] = mapped_column(default="default.jpg")
```

**Адаптер БД** — единственная обвязка над существующим слоем данных:

```python
from fastapi_users.db import SQLAlchemyUserDatabase

async def get_user_db(session: CurrentSession):          # наш DI-алиас!
    yield SQLAlchemyUserDatabase(session, BlogUser)
```

**Менеджер** — хуки вместо самописных писем:

```python
from fastapi_users import BaseUserManager, IntegerIDMixin

class UserManager(IntegerIDMixin, BaseUserManager[BlogUser, int]):
    reset_password_token_secret = settings.web.secret_key
    verification_token_secret = settings.web.secret_key

    async def on_after_forgot_password(self, user, token, request=None):
        send_email(user.email, f"/api/blog/auth/reset/{token}")   # ваша логика
```

**Backend: cookie-транспорт + стратегия.** Параметры cookie по умолчанию —
`cookie_name="fastapiusersauth"`, `cookie_httponly=True`,
`cookie_samesite="lax"`, **`cookie_secure=True`** (для dev по http придётся
выключить!), `cookie_max_age=None` (сессионная cookie):

```python
from fastapi_users.authentication import (
    AuthenticationBackend, CookieTransport, JWTStrategy,
)

cookie_transport = CookieTransport(
    cookie_max_age=14 * 24 * 3600,   # как сейчас в SessionMiddleware
    cookie_secure=False,             # True за HTTPS
)

def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=settings.web.secret_key, lifetime_seconds=14 * 24 * 3600)

auth_backend = AuthenticationBackend(
    name="cookie", transport=cookie_transport, get_strategy=get_jwt_strategy,
)
```

Выбор стратегии — идейный момент: **JWT** делает cookie самодостаточной (нет
SELECT на запрос, но нет и мгновенного отзыва — текущая схема теряет свою
главную фичу); **DatabaseStrategy** хранит сессии серверно — ближе к
семантике «перечитываем пользователя из БД», но добавляет хранилище. Для
one-origin блога честный эквивалент текущего поведения — Database или короткий
JWT + перечитывание в middleware.

**Зависимости доступа** — замена `require_login_api`:

```python
fastapi_users = FastAPIUsers[BlogUser, int](get_user_manager, [auth_backend])

current_active_user  = fastapi_users.current_user(active=True)     # 401
current_verified     = fastapi_users.current_user(active=True, verified=True)   # +403
current_superuser    = fastapi_users.current_user(active=True, superuser=True)  # +403
```

Обратите внимание на семантику статусов: неаутентифицированный → **401**
(наш `require_login_api` даёт 403); неактивный → 401, неверифицированный и
не-суперпользователь → 403. Фронтенд различает их минимально (оба случая =
«покажи login»), но контракт меняется — это надо прогнать по страницам.

**Роутеры** — 6 наших эндпоинтов заменяются пятью включениями:

```python
app.include_router(fastapi_users.get_auth_router(auth_backend),          # login/logout
                   prefix="/api/blog/auth", tags=["auth"])
app.include_router(fastapi_users.get_register_router(UserOut, UserCreate),
                   prefix="/api/blog/auth", tags=["auth"])
app.include_router(fastapi_users.get_verify_router(UserOut), ...)        # verify
app.include_router(fastapi_users.get_reset_password_router(), ...)       # forgot/reset
app.include_router(fastapi_users.get_users_router(UserOut, UserUpdate),  # me/PATCH
                   prefix="/api/blog/users", tags=["users"])
```

### 3.4. Как миграция ляжет на этот проект

| Сейчас | Станет |
|---|---|
| `api_auth.py`: 6 эндпоинтов, ~200 строк | роутеры библиотеки + 2 своих (аватар, account-формы) |
| `helpers_auth.py`: bcrypt, csrf, сессия | внутри библиотеки (PasswordHelper — bcrypt, хеши совместимы) |
| `middleware_auth.py`: SessionMiddleware + inject_current_user | уходит; вместо него — Dependency `current_active_user` |
| `BlogUser`: 5 колонок | + `is_active`, `is_verified`, `is_superuser`; `password` → `hashed_password` |
| CSRF: свой слой X-CSRF-Token | **остаётся вашим**: fastapi-users CSRF из коробки не даёт, полагается на SameSite=lax — наш слой можно не трогать |
| `client.ts` / auth.ts | login-эндпоинт меняет путь и ответ (204 без тела — профиль доёживать отдельным GET `/users/me`); остальное почти без правок |
| Роли: нет | superuser «из коробки»; свои роли — расширением UserManager |

Чеклист миграции (если решитесь):

1. `uv add "fastapi-users[sqlalchemy]"`; ветка `auth-fastapi-users`.
2. Alembic-миграция: 3 булевых колонки с `server_default=true` (существующие
   пользователи остаются активными и «доверенными»), переименование `password`
   → `hashed_password` (значения — те же bcrypt-хеши, **перехеширование не
   нужно**).
3. Модель + `get_user_db` + `UserManager` + backend (фрагменты §3.3).
4. Схемы `UserCreate`/`UserRead`/`UserUpdate` (наследники `schemas.BaseUser*`).
5. Подключить 5 роутеров; свой POST `/account` (multipart-аватар) переделать
   на `Depends(current_active_user)` + мутацию в роут-сессии (правило двух
   сессий из 04 остаётся верным и здесь).
6. Удалить `api_auth.py` и auth-часть `middleware_auth.py` (сессии Starlette
   больше не нужны — у cookie своя подпись внутри библиотечного транспорта);
   самописный CSRF-слой либо оставить, либо осознанно снять на SameSite.
7. Фронтенд: путь логина, обработка 204, `/users/me`; прогнать формы.
8. Прогон: счётчик маршрутов (изменится), curl-сценарии входа/регистрации,
   smoke соседних эндпоинтов.

### 3.5. authlib — когда нужен именно OAuth

Если требование звучит как «вход через Google/GitHub» или «наш сервер должен
выдавать токены сторонним приложениям» — это OAuth2, и authlib — главный
инструмент в Python: клиент (социальный вход), сервер авторизации, интеграция
с FastAPI, JWT/JWS. Для чистого «добавить кнопку Google» есть и путь через
fastapi-users (модуль OAuth на `httpx-oauth`, ассоциация соц-аккаунта с
существующим пользователем). На обзорном уровне правило такое: authlib берут,
когда OAuth — центр задачи; fastapi-users — когда OAuth — одна из фич аккаунтов.

### 3.6. «Просто добавим JWT сами» — почему это последний вариант

Собрать JWT-слой руками (`pyjwt` + свои роуты) технически несложно, но это
буквально переписывание текущего самописного слоя в худшую сторону: вы
получите те же ~200 строк своей логики, плюс refresh-токены, плюс проблему
отзыва, плюс выбор места хранения (localStorage — XSS-риск, см. 04 §6.2), и
не получите ничего из фич библиотек (verify/reset/роли). Если уж писать JWT
руками — только `pyjwt` (живой, стандарт де-факто); `python-jose` для нового
кода обычно не рекомендуют — медленное сопровождение и CVE в 2024 (алгоритмическая
путаница). Итог: самописный JWT оправдан только как учебное упражнение.

---

## 4. Сравнение: сейчас / укрепить / заменить

| Критерий | Сейчас (самопис) | Путь A (укрепить) | Путь B (fastapi-users) |
|---|---|---|---|
| Свой код авторизации | ~200 строк | ~250–400 строк | ~50 строк конфигурации + свои роуты аватара |
| Зависимости | 0 (Starlette+bcrypt уже есть) | +slowapi (опц.) | +fastapi-users[sqlalchemy] (+транзитивные) |
| register/login/logout | есть | есть | есть |
| Email-верификация | нет | A7, 100–200 строк | из коробки |
| Сброс пароля | нет | A7 | из коробки |
| Роли / superuser | нет | дописывать самому | из коробки (403-семантика) |
| OAuth (Google и др.) | нет | нет (это уже B) | через httpx-oauth |
| Rate-limit | нет | A5, slowapi | нет (тот же slowapi рядом) |
| CSRF | свой слой | остаётся (+A8) | **свой слой остаётся вашим** |
| Мгновенный отзыв сессии | да (SELECT на запрос) | да | только с Database-стратегией; с JWT — нет |
| Обновление зависимостей безопасности | тривиально (2 пакета) | тривиально | следить за библиотекой (maintenance mode) |
| Понятность/обучаемость | весь код виден | весь код виден | «магия» библиотеки + свои точки |
| Усилия перехода | — | часы | 1–2 дня с миграцией и прогонами |

## 5. Что даст замена: преимущества и цена

**Преимущества:**

1. **Готовые продуктовые флоу** — верификация email, забытый пароль, смена
   пароля, deactivate — сразу, без проектирования токенов и писем.
2. **Роли и семантика доступа** — `active/verified/superuser` в зависимостях,
   матрица доступа без своего кода.
3. **OAuth без боли** — кнопка «войти через Google» — конфигурация, не проект.
4. **Чужой аудит** — код библиотеки смотрят тысячи проектов; самописные CSRF и
   ротация сессий — только вы.
5. **Меньше своего кода** — меньше поверхности для ошибок компоновки.
6. **Контракт статусов** — продуманная семантика 401/403, соответствующая
   ожиданиям фронтенд-инструментов.

**Цена:**

1. **Зависимость и её жизненный цикл** — сейчас maintenance mode (безопасность
   — да, фичи — нет); мажорные обновления исторически меняли API.
2. **Слои магии** — UserManager/стратегии/транспорты: понять, где что
   подменить, сложнее, чем прочитать свои 200 строк.
3. **Контракт меняется** — 401 вместо 403, 204 без тела на login, другие
   форматы ошибок: фронтенд надо прогонять, а не «просто работает».
4. **CSRF остаётся ваш** — библиотека его не закрывает (только SameSite).
5. **Миграция данных** — колонки, переименование `password`, серверные
   дефолты: аккуратный Alembic-шаг с data-миграцией.
6. **Меньше учебной ценности** — для репозитория-каталога приёмов это минус:
   текущий слой читается целиком и объясняет механику.

## 6. Рекомендация для этого репозитория

- **Текущее состояние — осознанный учебный выбор**, не долг: транспорт и
  криптография библиотечные, компоновка видна вся (04 §2).
- **Минимум, который стоило бы сделать уже сейчас:** A1 (secret_key), A3
  (ротация при логине), A5 (rate-limit) — ~30 строк на троих.
- **Если проект станет продуктовым блогом:** A целиком + B, если нужны
  верификация/сброс/роли; стратегия Database (или короткий JWT + перечитывание),
  чтобы сохранить мгновенный отзыв.
- **Как учебное упражнение:** миграция на fastapi-users — отличный «экзамен»
  на понимание текущего слоя: чеклист §3.4 проходит по всем его точкам
  (модель, две сессии, CSRF, фронтенд-контракт).

## 7. Чеклист безопасности: что уже закрыто

OWASP-минимум для cookie-аутентификации — статус в проекте:

| Практика | Статус | Где / что делать |
|---|---|---|
| Хеширование паролей (bcrypt/argon2) | есть | `hash_password` |
| HttpOnly cookie | есть | Starlette, не отключается |
| SameSite=Lax | есть | дефолт Starlette |
| CSRF-токен на мутациях | есть | `validate_csrf_*` (+A8) |
| Единая ошибка входа | есть | `login_api` |
| Управление secret_key | частично | дефолт с warning → A1 |
| Rate-limit на вход | нет | → A5 |
| Ротация сессии при логине | нет | → A3 |
| Минимальная длина пароля | нет | → A4 |
| Secure-флаг в проде | нет | → A2 |
| Верификация email | нет | → A7 / B |
| Сброс пароля | нет | → A7 / B |

Верхняя половина таблицы — почему текущую схему не стыдно показывать;
нижняя — конкретное меню следующего шага.

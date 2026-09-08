# 04. Авторизация: как устроена и почему именно так

> Полный разбор слоя авторизации блога: какие механизмы выбраны, что из них
> написано руками, а что взято из библиотек, как выглядит жизненный цикл
> «регистрация → вход → защищённый запрос → выход» на обоих концах (FastAPI и
> React) — и почему для этого проекта выбраны cookie-сессии, а не JWT.
> Сопутствующие документы: [01_project_structure.md](01_project_structure.md)
> (дерево файлов), [02_architecture.md](02_architecture.md) (паттерн
> middleware-pipeline), [03_execution_flow.md](03_execution_flow.md) (порядок
> сборки middleware-стека). Как этот слой улучшать или заменить библиотекой —
> в [05_authorization_upgrade.md](05_authorization_upgrade.md).

Состояние кода: ветка `auth_refactor`, `len(main_app.routes) == 42`, из них 7 —
auth-роуты `/api/blog` (все в `md_articles/api_auth.py`). Авторизация существует
только в блоге: демо-домены `api/`, `ex_user_post/`, `ex_order_product/` открыты
намеренно — это учебная витрина.

---

## Содержание

1. [Резюме: что используется](#1-резюме-что-используется)
2. [«Это самописная реализация?» — послойный ответ](#2-это-самописная-реализация--послойный-ответ)
3. [Полный жизненный цикл: сетевые диалоги](#3-полный-жизненный-цикл-сетевые-диалоги)
4. [Бэкенд послойно](#4-бэкенд-послойно)
5. [Фронтенд послойно](#5-фронтенд-послойно)
6. [Почему cookie-сессии, а не JWT](#6-почему-cookie-сессии-а-не-jwt)
7. [Честные слабости текущей схемы](#7-честные-слабости-текущей-схемы)
8. [Карта файлов авторизации](#8-карта-файлов-авторизации)

---

## 1. Резюме: что используется

Классическая аутентификация на **подписанных cookie-сессиях** (Starlette
`SessionMiddleware`) с паролями, хешированными **bcrypt**, и **CSRF-токенами**
на всех изменяющих запросах.

| Аспект | Решение | Откуда |
|---|---|---|
| Транспорт сессии | cookie `session`, подпись HMAC (`itsdangerous`), 14 дней | Starlette `SessionMiddleware` |
| Хранение сессии на сервере | **нет** — всё состояние у клиента в cookie | свойство `SessionMiddleware` |
| Хеширование паролей | bcrypt (`hashpw`/`checkpw`), в БД только хеш | библиотека `bcrypt` |
| CSRF | токен `secrets.token_hex(32)` в сессии; JSON → заголовок `X-CSRF-Token`, multipart → поле формы | **самописное** (~40 строк) |
| Загрузка пользователя | HTTP-middleware → SELECT по `user_id` → `request.state.current_user` | **самописное** |
| Контроль доступа | DI-зависимость `require_login_api` → 403 JSON | **самописное** |
| Роуты auth | 6 эндпоинтов `/api/blog/*` с ручной валидацией форм | **самописное** |
| Роли / permissions | нет; только «гость vs вошедший» | — |
| JWT / OAuth2 / API-ключи | не используются | — |

Одним предложением: **транспорт и криптография библиотечные, компоновка —
своя**. Подробнее — в следующем разделе, это самый частый вопрос про этот слой.

---

## 2. «Это самописная реализация?» — послойный ответ

Короткий ответ: **гибрид**. Всё, что относится к криптографии и транспорту,
взято из зрелых библиотек; всё, что склеивает их в цикл «регистрация → вход →
запрос → выход», написано руками (~200 строк). Это осознанный выбор для
учебного проекта, и ниже — инвентаризация по слоям.

### 2.1. Библиотечное ядро — что НЕ писали сами

**`SessionMiddleware` (Starlette 0.50).** Берёт на себя весь цикл cookie-сессии:
сериализует словарь `request.session` в JSON, кодирует в base64, подписывает
HMAC через `itsdangerous.TimestampSigner` и кладёт в cookie; на входящем
запросе — проверяет подпись и восстанавливает словарь. Подпись имеет
timestamp, поэтому сессия умеет «протухать» по `max_age`.

Сигнатура (по установленной в проекте версии):

```python
SessionMiddleware(app, secret_key, session_cookie="session",
                  max_age=1209600,          # 14 дней — и дефолт Starlette
                  path="/", same_site="lax",
                  https_only=False, domain=None)
```

Важные детали:

- **`httponly=True` захардкожен внутри Starlette** — cookie сессии в принципе
  недоступна JavaScript'у браузера. Это главная защита от XSS-кражи сессии.
- **`same_site="lax"`** по умолчанию — браузер не приложит cookie к
  кросс-сайтовым POST-запросам (первая линия защиты от CSRF, см. §6.1).
- **`https_only=False`** в проекте — флаг `Secure` не ставится, потому что
  dev-стенд работает по http. Для прод-размещения за TLS его нужно включать.

**`bcrypt` (5.0).** Хеширование паролей — ровно две обёртки в
`helpers_auth.py:91-96`:

```python
# md_articles/helpers_auth.py:91-96
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
```

`gensalt()` генерирует случайную соль на каждый пароль (два одинаковых пароля
дают разные хеши), cost-фактор по умолчанию замедляет перебор. Хеш — 60
символов формата `$2b$12$...`, под что подобран тип колонки `str_len_60` в
`BlogUser.password`. Свою криптографию здесь не писали и писать нельзя.

### 2.2. Самописная надстройка — что писали сами

| Кусок | Файл | Объём | Что делает |
|---|---|---|---|
| CSRF-протокол | `helpers_auth.py:102-130` | ~40 строк | генерация токена + 2 валидатора (заголовок/поле формы) |
| current_user-middleware | `middleware_auth.py:17-56` | ~40 строк | SELECT по `user_id`, кладёт `BlogUser` в `request.state` |
| auth-роуты | `api_auth.py` | ~150 строк | csrf / current_user / register / login / logout / account |
| Валидация форм | `api_auth.py` + `validation_response` | ~50 строк | ручные проверки полей, формат ошибок WTForms-стиля |
| Аватары | `helpers_auth.py::save_picture` | ~30 строк | ресайз PIL 125×125, случайное имя файла |

Ничего из этого не является криптографией: CSRF-токен — это случайное число из
`secrets`, сравнение строк и протокол «кто его куда кладёт»; middleware —
обычный SELECT; роуты — обычные CRUD-обработчики. Ошибка в этом коде не
скомпрометирует пароли или подпись сессии — худшее, что она может сделать,
это пропустить неавторизованный запрос или отдать некорректную ошибку формы.

### 2.3. Откуда стиль: наследие Flask

Код несёт следы происхождения от Flask-подхода (переносился в FastAPI как
учебное упражнение):

- **`{"message": ..., "category": "success|danger"}`** — это семантика
  flash-сообщений Flask (`flash(msg, category)`), реализованная через JSON.
  Фронтенд воспроизводит её toast-уведомлениями.
- **Формат ошибок `{"errors": {"поле": ["текст", ...]}}`** — формат ошибок
  WTForms (`form.errors`), под который написаны React-формы и хелпер
  `extractErrors` на фронте.
- **`save_picture`** с `os.urandom(8).hex()` и ресайзом — классический рецепт
  Flask-туториалов по профилям пользователей.
- **`BlogUser.is_authenticated`** — property «для совместимости с UserMixin»
  (Flask-Login), докстринг говорит об этом прямо. JSON API его не использует.

Понимание этого происхождения объясняет, почему валидация форм ручная, а не
pydantic-ограничениями: код переносил устоявшийся Flask-паттерн один в один.
Как это свернуть в pydantic — §2 руководства
[05_authorization_upgrade.md](05_authorization_upgrade.md).

### 2.4. Вывод по вопросу

| Слой | Происхождение | Почему это нормально |
|---|---|---|
| Подпись сессии, HttpOnly, SameSite | Starlette | боевой код фреймворка |
| Хеширование паролей | bcrypt | стандарт отрасли |
| CSRF-токены | свой код поверх `secrets` | простая логика, весь протокол виден |
| current_user, роуты, валидация | свой код | обычная прикладная логика |

«Самописная авторизация» была бы проблемой, если бы своими руками
реализовывались подпись cookie или хеширование паролей. Здесь своими руками
реализована только **компоновка** библиотечных примитивов — это законный способ
для небольшого проекта, которому не нужны верификация email, сброс пароля,
роли и OAuth (сравнение с готовыми библиотеками — в 05).

---

## 3. Полный жизненный цикл: сетевые диалоги

Шесть сценариев в порядке реального прохождения. В каждом: диалог
браузер↔сервер и указание, какой код его обслуживает.

### 3.1. Холодный старт SPA: кто я?

```
Браузер                              Сервер (uvicorn)
   |  GET /                            |
   |--------------------------------->|  catch-all → index.html + /assets/*.js
   |  GET /api/blog/current_user       |
   |  (cookie нет)                     |
   |--------------------------------->|  SessionMiddleware: пустая сессия
   |                                   |  inject_current_user: user_id нет → None
   |<---------------------------------|  200 {"user": null}
```

React при монтировании вызывает `AuthProvider → refresh()` →
`getCurrentUser()` (`frontend/src/context/AuthContext.tsx`), ответ `null` —
гость. Это единственный «who am I»-запрос; дальше фронтенд держит пользователя
в состоянии.

### 3.2. Получение CSRF-токена

```
   |  GET /api/blog/csrf               |
   |  Cookie: session=<подписано>      |
   |--------------------------------->|  ensure_csrf_token: токена нет →
   |                                   |  secrets.token_hex(32) → в сессию
   |<---------------------------------|  200 {"csrf_token": "<64 hex>"}
   |                                   |  + Set-Cookie: session=<переподписано>
```

Токен живёт **в той же подписанной cookie**, что и `user_id` (см. §4.2).
Клиент запрашивает его лениво — `postJson`/`postMultipart` сами дёргают
`GET /api/blog/csrf` перед каждым POST (`frontend/src/api/client.ts`).

### 3.3. Регистрация

```
   |  POST /api/blog/register          |
   |  X-CSRF-Token: <токен>            |
   |  {"username","email","password","confirm_password"}
   |--------------------------------->|  validate_csrf_header → 403 при несовпадении
   |                                   |  уже залогинен? → 400
   |                                   |  ручная валидация полей (2–20 симв. и т.д.)
   |                                   |  SELECT по username и email (уникальность)
   |<---------------------------------|  422 {"errors": {...}}   — ошибки полей
   |                                   |  или: bcrypt.hashpw → INSERT blog_user
   |<---------------------------------|  200 {"message": "...", "category": "success"}
```

Регистрация **не логинит автоматически** — создание аккаунта и вход разделены
сознательно. Пользователь попадает в БД только после `session.commit()`.

### 3.4. Вход

```
   |  POST /api/blog/login             |
   |  X-CSRF-Token: <токен>            |
   |  {"email": "...", "password": "..."}
   |--------------------------------->|  validate_csrf_header
   |                                   |  SELECT blog_user WHERE email = ?
   |                                   |  bcrypt.checkpw(password, hash)
   |                                   |  request.session["user_id"] = user.id
   |<---------------------------------|  200 {"user": {...}}
   |                                   |  + Set-Cookie: session=<новая подпись>
```

Весь «вход» — одна строка `login_user(request, user.id)`
(`helpers_auth.py:80`). Cookie переподпишется на выходе из
`SessionMiddleware`. Что конкретно лежит в cookie — см. §4.2: содержимое
**читаемо** (base64-JSON), но не подделываемо (подпись).

### 3.5. Защищённый запрос

```
   |  GET /api/blog/account            |
   |  Cookie: session=<подписано>      |
   |--------------------------------->|  SessionMiddleware: подпись ок → request.session
   |                                   |  inject_current_user:
   |                                   |    SELECT blog_user WHERE id = session["user_id"]
   |                                   |    request.state.current_user = BlogUser
   |                                   |  Depends(require_login_api):
   |                                   |    current_user is None → 403
   |<---------------------------------|  200 {"user": {...}}
```

Middleware загружает пользователя на **каждом** HTTP-запросе — и публичный
`/api/blog/articles`, и защищённый `/api/blog/account` уже имеют готового
пользователя в `request.state`. Защита роута сводится к одной строке
`_user=Depends(require_login_api)` в сигнатуре.

### 3.6. Обновление аккаунта с аватаром (multipart)

```
   |  POST /api/blog/account           |
   |  Content-Type: multipart/form-data
   |  поля: username, email, csrf_token, picture=<файл>
   |--------------------------------->|  require_login_api → 403 анониму
   |                                   |  validate_csrf_form: поле формы == сессия
   |                                   |  re-SELECT BlogUser в РОУТ-сессии (не middleware!)
   |                                   |  save_picture: PIL-ресайз 125×125 → static/profile_pics/
   |<---------------------------------|  200 {"user": {...}} или 422 {"errors": ...}
```

Почему CSRF здесь полем формы, а не заголовком: к `FormData` заголовок
прикрепить можно, но проще и надёжнее положить токен внутрь самой формы —
клиент делает это централизованно в `postMultipart`. Почему re-SELECT: объект
из `request.state` загружен **другой** сессией БД (middleware-сессией) и
отвязан от неё — мутации через него не попадут в UPDATE (урок бага с аватаром,
подробнее §4.3).

### 3.7. Выход

```
   |  POST /api/blog/logout            |
   |  X-CSRF-Token: <токен>            |
   |--------------------------------->|  validate_csrf_header
   |                                   |  request.session.pop("user_id")
   |<---------------------------------|  200 {"message": "...}
   |                                   |  + Set-Cookie: session=<переподписана без user_id>
```

Серверное состояние при выходе не инвалидируется — его просто нет (сессия
хранится у клиента). Cookie переподписывается уже без `user_id`; `csrf_token`
в ней остаётся, но сам по себе доступ не даёт.

---

## 4. Бэкенд послойно

### 4.1. Подключение: где авторизация собирается

Цепочка вызова при старте приложения:

```
main.py:24  include_router_api_frontend(main_app)
  └─ md_articles/setup_frontend.py:16  include_router_api_frontend(app)
       ├─ add_middleware_auth(app)            ← вся авторизация (middleware_auth.py:58)
       ├─ app.mount("/static", ...)           ← аватары profile_pics/
       ├─ app.include_router(router_auth_api) ← 7 auth-роутов (api_auth.py)
       └─ app.include_router(router_blog_api) ← статьи (api_blog.py)
```

`add_middleware_auth` (`middleware_auth.py:58`) делает три вещи, и **порядок
двух первых критичен**:

```python
# md_articles/middleware_auth.py:58 (сокращено)
app.add_middleware(BaseHTTPMiddleware, dispatch=inject_current_user_middleware)
app.add_middleware(SessionMiddleware, secret_key=settings.web.secret_key,
                   max_age=14 * 24 * 3600)
app.add_exception_handler(RequestValidationError, custom_request_validation_exception_handler)
```

Starlette вставляет каждое новое middleware в начало списка
(`user_middleware.insert(0, ...)`), а стек собирается по `reversed(...)`:
middleware, добавленный ПОЗЖЕ, оказывается СНАРУЖИ и обрабатывает запрос
ПЕРВЫМ. Поэтому `inject_current_user` обязан быть добавлен **до**
`SessionMiddleware` — тогда он окажется внутри сессии и увидит
`request.session`; иначе каждый запрос упадёт с `AssertionError`. Полный
разбор этого инварианта — [03_execution_flow.md](03_execution_flow.md).

Третий вызов — кастомный обработчик `RequestValidationError`: для `/api/blog/*`
он переводит ошибки pydantic в формат `{"errors": {"поле": ["текст"]}}`
(WTForms-стиль, §2.3), остальным путям оставляет стандартный ответ FastAPI.

### 4.2. Сессия: что лежит в cookie

Всё состояние входа — два ключа в подписанной cookie:

```python
request.session["user_id"] = user.id     # ставится в login_user
request.session["csrf_token"] = token    # ставится в ensure_csrf_token
```

Формат cookie `session`: `base64(JSON) + timestamp + HMAC-подпись` (сериализатор
`itsdangerous`). Раскодировать содержимое может любой — например, значение

```
eyJ1c2VyX2lkIjoxfQ.XxXxXx.9f8e...        # base64 {"user_id": 1} + метка + подпись
```

Свойства этой конструкции:

- **Подписано, но не зашифровано.** Клиент видит свой `user_id`; подделать его
  нельзя — правка ломает подпись, и `SessionMiddleware` отбрасывает сессию
  целиком. Отсюда правило: секреты в `request.session` не класть.
- **Сервер ничего не хранит.** Нет таблицы сессий, нет Redis: «база сессий» —
  сами браузеры. Это делает схему stateless на стороне сервера (важно для
  §6.5, где разбирается аргумент «JWT не хранит состояние»).
- **Цена подписи — `secret_key`** из `core/config.py::WebConfig` (единственное
  место доверия; переопределяется через `APP__WEB__SECRET_KEY`).

### 4.3. `inject_current_user` и две сессии БД

```python
# md_articles/middleware_auth.py:32 (сокращено)
async def inject_current_user_middleware(request: Request, call_next):
    async with db_manager.session_factory() as session:   # КОРОТКАЯ сессия №1
        await get_current_user(request, session)          # SELECT по user_id
        response = await call_next(request)               # роут работает ВНУТРИ
    return response
```

`get_current_user` (`middleware_auth.py:17`): нет `user_id` →
`request.state.current_user = None` (БД не трогается); есть → `SELECT blog_user
WHERE id = ...` → объект в `request.state`. Роуты читают его хелпером
`get_request_user(request)` (`helpers_auth.py:133`, обёртка с `getattr`-защитой).

Запрос к `/api/blog/*` использует **две разные сессии SQLAlchemy**: короткую
middleware-сессию и роут-сессию (`CurrentSession` через DI). Отсюда правило,
выученное на баге с аватаром: объект из `request.state.current_user` годится
**только для чтения**. Мутации — через роут-сессию: `POST /api/blog/account`
заново выбирает `BlogUser` по `user_id` и меняет уже его
(`api_auth.py:193-196`), иначе UPDATE не выполняется, хотя curl вернёт 200.

Выбор middleware вместо dependency — потому что `current_user` нужен всем
обработчикам `/api/blog/*` сразу, без явной зависимости в каждом роуте.

### 4.4. Хелперы: `helpers_auth.py`

Файл без роутов, чистые функции (полный список — §8):

- `login_user` / `logout_user` — по одной строке: записать/удалить `user_id`
  из сессии. Вся «сессионная логика» проекта умещается сюда.
- `hash_password` / `verify_password` — обёртки bcrypt (§2.1).
- `ensure_csrf_token` — выдать существующий токен или создать
  `secrets.token_hex(32)` в сессии.
- `validate_csrf_header` / `validate_csrf_form` — сверка токена из заголовка
  `X-CSRF-Token` / поля формы `csrf_token` с токеном сессии; несовпадение →
  403 `CSRF token mismatch`.
- `require_login_api` — зависимость защиты роутов: `current_user is None` →
  403 `Authentication required`.
- `username_exists` / `email_exists` — проверки уникальности SELECT'ом
  (до `INSERT`, чтобы вернуть 422 с ошибкой поля, а не 500 от `IntegrityError`).
- `user_out` — `BlogUser` → pydantic `UserOut` (4 поля, без `password`).
- `is_valid_email` — трюк: вызывает приватный `EmailStr._validate` из pydantic,
  чтобы переиспользовать её проверку email вне модели.
- `save_picture` — аватар: валидация расширения, `os.urandom(8).hex()`-имя,
  PIL-ресайз 125×125 в `static/profile_pics/`.
- `validation_response` — единый 422-ответ `{"errors": {...}}`.

### 4.5. Роуты: `api_auth.py`

Семь маршрутов одного роутера `router_auth_api` (prefix `/api/blog`, tag
`auth`):

| Маршрут | Имя | Защита | Что делает |
|---|---|---|---|
| `GET /csrf` | `auth.csrf` | — | выдать CSRF-токен |
| `GET /current_user` | `auth.current_user` | — | `{user: null}` или профиль |
| `POST /register` | `auth.register` | CSRF | создать аккаунт (без автовхода) |
| `POST /login` | `auth.login` | CSRF | проверить пароль, записать сессию |
| `POST /logout` | `auth.logout` | CSRF | удалить `user_id` из сессии |
| `GET /account` | `auth.account_get` | логин | профиль |
| `POST /account` | `auth.account_post` | CSRF + логин | обновить профиль + аватар |

Ключевые решения в коде роутов:

**Ручная валидация с накоплением ошибок** (`register_api`,
`api_auth.py:68`). Все проверки собираются в словарь `errors` и возвращаются
разом через `validation_response` — фронтенд показывает их под полями формы.
Уникальность проверяется SELECT'ом только для полей, прошедших синтаксическую
валидацию.

**Единое сообщение об ошибке входа** (`login_api`, `api_auth.py:125`): и
«нет такого email», и «неверный пароль» дают один 401
`Login Unsuccessful. Please check email and password` — не раскрывает, какие
учётные записи существуют. Нюанс: `if user and verify_password(...)` —
короткое замыкание, bcrypt не вызывается для несуществующего email; строго
говоря, это создаёт timing-различие (фиктивный хеш выровнял бы время) — из
известных ограничений, §7. Точная строка: `api_auth.py:146`.

**Почему 403, а не редирект на `/login`**: это JSON API для SPA. Fetch молча
следует за 302 и вернёт HTML вместо JSON; 403 — однозначный сигнал фронтенду
«покажи форму входа» (клиентская реакция — §5.4).

### 4.6. Матрица защиты эндпоинтов `/api/blog`

| Эндпоинт | Метод | CSRF | Логин |
|---|---|---|---|
| `csrf`, `current_user`, `articles`, `sections`, `articles/{id}` | GET | — | — |
| `register`, `login`, `logout` | POST | заголовок | — |
| `account` | GET | — | `require_login_api` |
| `account` | POST | **поле формы** (multipart) | `require_login_api` |
| `art_manage`, `art_manage/add_all`, `art_manage/meta`, `art_manage/sync` | GET/POST | заголовок (для POST) | `require_login_api` |

Ролей нет: любой вошедший может править реестр статей через `art_manage` —
для учебного блога граница «гость vs вошедший» достаточна.

---

## 5. Фронтенд послойно

### 5.1. `client.ts` — единственная точка fetch

Весь HTTP-обмен SPA с API идёт через один модуль `frontend/src/api/client.ts`.
Сквозные механики собраны там же:

```typescript
// frontend/src/api/client.ts:29
async function request(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(path, { credentials: 'include', ...init });
  return res;
}
```

- **`credentials: 'include'`** — браузер обязан прикладывать cookie сессии к
  каждому fetch и принимать `Set-Cookie`. На same-origin cookie ушла бы и без
  флага, но он делает намерение явным и пригодится при выносе API на отдельный
  origin.
- **`postJson`** перед каждым POST берёт токен (`getCsrfToken()` →
  `GET /api/blog/csrf`) и кладёт его в заголовок `X-CSRF-Token`.
- **`postMultipart`** кладёт токен **полем формы** `csrf_token` — протокол для
  аватара (§3.6).
- Ошибки нормализуются в `ApiError {status, data}` — страницы не парсят
  ответы руками.

### 5.2. `auth.ts` — типизированный слой

`frontend/src/api/auth.ts` оборачивает `client.ts` в функции с типами:
`register`, `login`, `logout`, `getCurrentUser`, `getAccount`, `updateAccount`.
Ответы типизированы (`MessageResp & {user: User}`, `User` из `types.ts` —
зеркало pydantic `UserOut`). Отдельная функция `extractErrors(err)` достаёт
`{"errors": {...}}` из 422 — она маппит серверные ошибки на поля формы.

### 5.3. `AuthContext.tsx` — состояние сессии на клиенте

`frontend/src/context/AuthContext.tsx` — React-контекст с `user / loading /
setUser / refresh`. Инициализация: при монтировании `AuthProvider` вызывает
`GET /api/blog/current_user` — так SPA узнаёт после перезагрузки страницы,
жива ли cookie-сессия (диалог §3.1). `setUser` страницы дергают после
`login`/`updateAccount` — без перезагрузки.

### 5.4. `RequireAuth` — клиентская защита маршрутов

```tsx
// frontend/src/App.tsx
function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="page-stub">Проверка доступа...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
```

`/account` и `/art_manage` обёрнуты в `RequireAuth`. Это **UX-слой**, а не
безопасность: реальная защита — 403 от API. Если сессия протухла после
загрузки страницы, клиентский guard её не увидит — запрос упадёт с 403, и
страница покажет это (в `AccountPage` — toast «Требуется вход»).

### 5.5. Страницы форм

- **`LoginPage`**: пустые поля → локальная проверка; 401 → toast `danger` с
  сообщением сервера; успех → `setUser(resp.user)` + редирект на `/`.
- **`RegisterPage`**: 422 → `extractErrors` → тексты под полями
  (`FormField` принимает `errors`); успех → редирект на `/login`.
- **`AccountPage`**: грузит профиль через `getAccount`, отправляет изменения
  `updateAccount` (multipart c `picture`); аватар отображается по URL,
  который склеивается **ровно в одном месте**:

```tsx
// frontend/src/pages/AccountPage.tsx:91-92
const avatarFile = user?.image_file || 'default.jpg';
const avatarUrl = `/static/profile_pics/${avatarFile}`;
```

БД хранит голое имя файла (`image_file`), URL собирает только фронтенд —
дублирование этой склейки на бэкенде уже приводило к багам, поэтому источник
единственный.

---

## 6. Почему cookie-сессии, а не JWT

### 6.1. Модель угроз: от чего защищаемся

| Угроза | Контрмера в проекте | Где |
|---|---|---|
| Кража сессии через XSS в SPA | cookie **HttpOnly** — недоступна JavaScript'у | Starlette, захардкожено |
| Подделка сессии | HMAC-подпись `secret_key`; правка ломает подпись | `SessionMiddleware` |
| CSRF (злой сайт шлёт запросы с cookie жертвы) | SameSite=Lax (дефолт) + токен на всех мутациях | middleware + `validate_csrf_*` |
| Утечка паролей при компрометации БД | bcrypt с солью и cost-фактором | `hash_password` |
| Перебор паролей | cost-фактор bcrypt замедляет перебор | bcrypt |
| Перечисление пользователей по ошибкам входа | единое сообщение 401 | `login_api` |

### 6.2. Почему JWT в localStorage — антипаттерн для SPA

Частая схема «SPA + JWT» хранит токен в `localStorage` и кладёт в заголовок
`Authorization`. Проблема: **`localStorage` читается любым JavaScript'у** —
одна XSS-уязвимость (уязвимая npm-зависимость, опасный `innerHTML`,
скомпрометированный скрипт CDN) отдаёт токен атакующему навсегда. Cookie
сессии в этом проекте HttpOnly — XSS-скрипт физически не может её прочитать.
CSRF, аутентичный риск cookie-схемы, закрыт токеном (§6.1) — то есть у нас
закрыты **обе** стороны, у localStorage-JWT закрыта только одна.

### 6.3. Сравнение четырёх вариантов

| Критерий | Cookie-сессия (проект) | JWT в localStorage | JWT в HttpOnly-cookie | Серверные сессии (Redis) |
|---|---|---|---|---|
| Доступен XSS-скрипту | **нет** | да | **нет** | **нет** |
| Нужен CSRF-токен | да (есть) | нет | да | да |
| Отзыв (бан, logout «везде») | мгновенный: SELECT на каждом запросе | сложно (bl/blacklist, короткий TTL + refresh) | так же сложно | мгновенный (удалить запись) |
| Смена email/роли видна сразу | да (перечитываем из БД) | нет, «заморожено» в claims до конца TTL | нет | да (если хранится id) |
| Состояние на сервере | нет | нет | нет | да (Redis) |
| Инфраструктура | ничего | ничего | ничего | Redis |
| Мобильные клиенты / сторонние API | неудобно | удобно | неудобно | неудобно |
| Объём на каждый запрос | ~сотни байт cookie | сотни байт заголовка | сотни байт | десятки байт (sid) |

Заметьте: колонка «JWT в HttpOnly-cookie» — это по сути та же cookie-сессия,
только вместо словаря `{"user_id": 1}` в cookie лежит токен с claims. Она не
даёт этому проекту ничего, кроме необходимости валидировать JWT и решать
проблему отзыва.

### 6.4. Когда JWT был бы правильным выбором

- **Сторонние потребители API**: мобильное приложение, публичный API,
  интеграции — они не работают с cookie вашего домена, им нужен заголовок.
- **Несколько бэкендов**: микросервисы проверяют подпись JWT локально без
  обращения к сервису сессий.
- **Кросс-доменные сценарии** (SSO между доменами) — OAuth2/OIDC с токенами.

Ничего из этого в проекте нет: один FastAPI-процесс, один origin (в dev Vite
проксирует `/api` и `/static` на `:8000`, в проде FastAPI сам раздаёт SPA),
единственный потребитель API — собственный фронтенд.

### 6.5. Разбор типовых аргументов «за JWT» применительно к здесь

- *«JWT не хранит состояние на сервере»* — наша cookie-сессия **тоже** не
  хранит: подпись проверяется локально, серверных записей нет. Аргумент
  ничего не меняет.
- *«Сессии не масштабируются»* — речь о серверных сессиях (Redis/БД). У нас
  их нет. Единственная нагрузка — SELECT по целочисленному PK на каждый запрос
  (микросекунды на SQLite; при росте — кэш в памяти процесса, см. 05).
- *«JWT самодостаточен — не нужен запрос в БД»* — у нас он и не ради данных:
  перечитывание пользователя из БД даёт мгновенный отзыв и актуальные данные
  (смена email, деактивация). Это фича, а не баг.
- *«JWT стандартен»* — стандартен формат токена; наш формат сессии
  (itsdangerous) — тоже стандартная, широко используемая конструкция
  (встроена в Starlette, Flask, Django-подписи).

### 6.6. Итоговая формула выбора

Для **same-origin SPA с формами и собственным API** cookie-сессия + CSRF —
простейшая схема, закрывающая XSS и CSRF одновременно, с мгновенным отзывом и
без инфраструктуры. JWT выигрывает при появлении **внешних потребителей API
или нескольких сервисов**. Как выглядела бы замена (включая честную цену) —
[05_authorization_upgrade.md](05_authorization_upgrade.md).

---

## 7. Честные слабости текущей схемы

Не дефекты «сломано», а границы решения — то, что следует знать и что
закрывать, если проект выйдет из учебной стадии (рецепты — в 05).

| # | Слабость | Риск | Локация |
|---|---|---|---|
| 1 | `secret_key` с дефолтом `dev-insecure-...` | в проде без env — подделка любых сессий | `core/config.py:22` |
| 2 | Нет rate-limit на `/login` | брутфорс паролей | — |
| 3 | Нет ротации сессии при логине | session fixation на shared-машинах (OWASP рекомендует сброс) | `login_user` |
| 4 | `remember` принимается, но игнорируется | срок всегда 14 дней; поле — мёртвое | `LoginIn` / `login_api` |
| 5 | Нет минимальной длины пароля | слабые пароли (проверяется только непустота) | `register_api` |
| 6 | `Secure`-флаг не включается для HTTPS | cookie может уйти по http в прод-схеме за прокси | `add_middleware_auth` |
| 7 | Timing-различие на `/login` (bcrypt не вызывается для несуществующего email) | перечисление email по времени | `login_api` (`api_auth.py:146`) |
| 8 | CSRF-сравнение не constant-time | теоретическая timing-атака на токен | `validate_csrf_*` |
| 9 | Нет email-верификации и сброса пароля | регистрация с чужим email; забытый пароль = потерянный аккаунт | — |
| 10 | Нет ролей | любой вошедший правит реестр статей | `require_login_api` |
| 11 | SELECT пользователя на каждый запрос | нагрузка при росте (для SQLite несущественно) | `get_current_user` |
| 12 | `user_id` читаем в cookie | не секрет, но раскрывает внутренний id | свойство подписи |

Пункты 1–8 закрываются точечными правками суммарно в ~50 строк (путь «A» в
05); пункты 9–10 — это уже переход к библиотеке или заметная доработка (путь
«B»).

---

## 8. Карта файлов авторизации

```
fastapi-application/
├── core/config.py                  # WebConfig.secret_key — подпись cookie (APP__WEB__SECRET_KEY)
└── md_articles/
    ├── setup_frontend.py           # include_router_api_frontend(): add_middleware_auth
    │                               #   + mount /static + include router_auth_api/router_blog_api
    ├── middleware_auth.py          # add_middleware_auth (стек), get_current_user,
    │                               #   inject_current_user_middleware, 422-handler
    ├── helpers_auth.py             # login/logout_user, hash/verify_password (bcrypt),
    │                               #   ensure_csrf_token + validate_csrf_header/form,
    │                               #   get_request_user, require_login_api, user_out,
    │                               #   username/email_exists, save_picture, validation_response
    ├── api_auth.py                 # 7 роутов /api/blog: csrf, current_user, register,
    │                               #   login, logout, account GET/POST
    ├── models.py                   # BlogUser (blog_user): password = bcrypt-хеш (60 симв.)
    └── schema_blog.py              # UserOut / RegisterIn / LoginIn

frontend/src/
├── api/client.ts                   # credentials:'include', getCsrfToken,
│                                   #   postJson (X-CSRF-Token), postMultipart (поле формы)
├── api/auth.ts                     # register/login/logout/getAccount/updateAccount + extractErrors
├── context/AuthContext.tsx         # user/loading/setUser/refresh; boot через current_user
├── App.tsx                         # RequireAuth — клиентская защита /account, /art_manage
└── pages/                          # LoginPage (401→toast), RegisterPage (422→поля),
                                    #   AccountPage (multipart-аватар, склейка URL аватара)
```

| Что искать | Где |
|---|---|
| Подключение всей авторизации | `md_articles/setup_frontend.py::include_router_api_frontend` → `middleware_auth.py::add_middleware_auth` |
| Порядок middleware (инвариант) | `middleware_auth.py:58` + [03_execution_flow.md](03_execution_flow.md) |
| Запись/удаление входа | `helpers_auth.py::login_user` / `logout_user` |
| Загрузка пользователя на запрос | `middleware_auth.py::get_current_user` + `inject_current_user_middleware` |
| Защита роута | `helpers_auth.py::require_login_api` (403) |
| CSRF: выдача и проверка | `helpers_auth.py::ensure_csrf_token`, `validate_csrf_header/form` |
| Пароли | `helpers_auth.py::hash_password/verify_password` (bcrypt) |
| Роуты auth | `api_auth.py` (7 маршрутов, prefix `/api/blog`) |
| Клиент: cookie + CSRF | `frontend/src/api/client.ts` |
| Клиент: состояние сессии | `frontend/src/context/AuthContext.tsx` + `App.tsx::RequireAuth` |

Свежесть этой карты проверяется счётчиком:
`cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"`
→ `42`.

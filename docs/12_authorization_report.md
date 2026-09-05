# Отчёт: способ авторизации в проекте my-fastapi-one

> Дата: 2026-09-03. Код по результатам анализа не менялся — только чтение и разбор.
> Зона авторизации: блог `fastapi-application/md_articles/` + React SPA `frontend/`.

---

## Содержание

1. [Краткое резюме](#1-краткое-резюме)
2. [Где в проекте вообще есть авторизация](#2-где-в-проекте-вообще-есть-авторизация)
3. [Выбранный способ: серверная cookie-сессия](#3-выбранный-способ-серверная-cookie-сессия)
4. [Полный поток запроса: от cookie до ответа](#4-полный-поток-запроса-от-cookie-до-ответа)
5. [Разбор кода по слоям](#5-разбор-кода-по-слоям)
6. [CSRF-защита: зачем и как](#6-csrf-защита-зачем-и-как)
7. [Авторизация vs аутентификация: контроль доступа](#7-авторизация-vs-аутентификация-контроль-доступа)
8. [Почему выбран именно этот способ](#8-почему-выбран-именно-этот-способ)
9. [Сравнение с альтернативами: JWT, OAuth2, серверные сессии](#9-сравнение-с-альтернативами-jwt-oauth2-серверные-сессии)
10. [Преимущества и недостатки выбранного решения](#10-преимущества-и-недостатки-выбранного-решения)
11. [Наблюдения и потенциальные улучшения](#11-наблюдения-и-потенциальные-улучшения)
12. [Приложение: карта файлов авторизации](#12-приложение-карта-файлов-авторизации)

---

## 1. Краткое резюме

В проекте используется **классическая аутентификация на подписанных cookie-сессиях**
(Starlette `SessionMiddleware`) с паролями, хешированными **bcrypt**, и **CSRF-токенами**
для всех изменяющих состояние запросов.

Ключевые факты:

| Аспект | Решение в проекте |
|---|---|
| Механизм входа | `request.session["user_id"]` в подписанной cookie (14 дней) |
| Хранение паролей | bcrypt (`bcrypt.hashpw` / `bcrypt.checkpw`), только хеш в БД |
| CSRF | токен `secrets.token_hex(32)` в сессии; JSON — заголовок `X-CSRF-Token`, multipart — поле `csrf_token` |
| Проверка доступа | DI-зависимость `require_login_api` → 403 JSON; middleware кладёт `current_user` в `request.state` |
| Роли/permissions | нет; единственное разграничение — «гость vs вошедший» |
| JWT / OAuth2 / API-ключи | не используются |

---

## 2. Где в проекте вообще есть авторизация

Авторизация существует **только в блоге**. Остальные части приложения полностью открыты:

| Часть проекта | Авторизация |
|---|---|
| `api/` (демо Depends, 4 стиля параметров) | нет — учебная витрина, открыта намеренно |
| `ex_user_post/` (`/users` CRUD User/Post) | нет |
| `ex_order_product/` (`/orders` CRUD) | нет |
| `md_articles/` (JSON API `/api/blog` + SPA) | **есть** — сессии, bcrypt, CSRF |

Это соответствует учебной цели проекта: демонстрационные роуты должны работать «из
коробки» без логина, а блог — показывать полноценный цикл аутентификации как в реальном
приложении. Подробности по архитектуре блога — в `docs/11_md_articles.md`.

---

## 3. Выбранный способ: серверная cookie-сессия

### 3.1. Как это устроено технически

Starlette `SessionMiddleware` реализует паттерн **client-side session**: всё состояние
сессии сериализуется, подписывается HMAC с `secret_key` и целиком кладётся в cookie
`session`. Сервер ничего не хранит — «база сессий» находится у клиента в браузере.

Подключение — `fastapi-application/md_articles/frontend_auth_include.py`,
вызывается из `main.py`:

```python
def setup_auth_static_include(app: FastAPI) -> None:
    """Подключает блог к FastAPI: авторизация, статика, JSON-роутер."""
    logF.info("setup_auth_static_include: подключение auth, /static, router_blog_api")

    auth_add_middleware(app)

    app.mount(
        "/static",
        StaticFiles(directory=BASE_DIR / "static", check_dir=False),
        name="static",
    )

    app.include_router(router_blog_api)
```

Точка входа авторизации — `auth_add_middleware(app)` в `auth_middleware_helpers.py`:
добавляет `SessionMiddleware` (14 дней, подпись HMAC `secret_key`) и HTTP-middleware
`inject_current_user_middleware`.

Секретный ключ подписи — из вложенной pydantic-модели конфигурации
(`fastapi-application/core/config.py`):

```python
class WebConfig(BaseModel):
    secret_key: str = "dev-insecure-secret-key-change-me"
```

Переопределяется через окружение: `APP__WEB__SECRET_KEY` (префикс `APP__`,
разделитель `__` — соглашение проекта).

### 3.2. Что лежит в сессии

Весь «вход пользователя» — два ключа в подписанной cookie:

```python
request.session["user_id"] = user.id        # ставится при логине
request.session["csrf_token"] = token       # secrets.token_hex(32), ставится по требованию
```

Содержимое cookie **подписано, но не зашифровано**: клиент может прочитать `user_id`,
но не может подделать — любая правка ломает подпись, и `SessionMiddleware` отбрасывает
сессию целиком.

---

## 4. Полный поток запроса: от cookie до ответа

### 4.1. Вход (POST /api/blog/login)

```
Браузер                          Сервер
   |  GET /api/blog/csrf            |
   |------------------------------->|  создаёт csrf_token в сессии, ставит cookie
   |<-------------------------------|  {"csrf_token": "..."}
   |                                |
   |  POST /api/blog/login          |
   |  Cookie: session=<подписано>   |
   |  X-CSRF-Token: <токен>         |
   |  {"email": "...", "password": "..."}
   |------------------------------->|  1) validate_csrf_header: токен == сессия?
   |                                |  2) SELECT BlogUser WHERE email = ?
   |                                |  3) bcrypt.checkpw(password, hash)
   |                                |  4) request.session["user_id"] = user.id
   |<-------------------------------|  200 {"user": {...}} + новая cookie
```

### 4.2. Каждый последующий запрос

```
   |  GET /api/blog/account         |
   |  Cookie: session=<подписано>   |
   |------------------------------->|  SessionMiddleware: расшифровка/проверка подписи
   |                                |  inject_current_user_middleware:
   |                                |      SELECT BlogUser WHERE id = session["user_id"]
   |                                |      request.state.current_user = user | None
   |                                |  require_login_api (Depends):
   |                                |      state.current_user is None -> 403
   |<-------------------------------|  200 {"user": {...}}
```

Важно: middleware загружает `current_user` **для каждого HTTP-запроса**, поэтому и
`/api/blog/articles` (публичный), и `/api/blog/account` (защищённый) уже имеют
готового пользователя в `request.state` — защита роута сводится к одной строке
`Depends(require_login_api)`.

### 4.3. Выход (POST /api/blog/logout)

CSRF-проверка + удаление ключа из сессии — cookie перезаписывается уже без `user_id`:

```python
@router_blog_api.post("/logout", name="blog_api.logout")
async def logout_api(request: Request):
    await validate_csrf_header(request)
    logout_user(request)
    return {"message": "You have been logged out", "category": "success"}
```

---

## 5. Разбор кода по слоям

### 5.1. Слой утилит сессии — `md_articles/auth_middleware_helpers.py`

Ядро аутентификации — четыре функции + зависимость, в одном файле:

```python
async def get_current_user(
    request: Request,
    session: CurrentSession,
) -> BlogUser | None:
    """Получить пользователя из сессии и положить в request.state."""
    user_id = request.session.get("user_id")
    if user_id is None:
        request.state.current_user = None
        return None
    result = await session.execute(select(BlogUser).where(BlogUser.id == user_id))
    user = result.scalar_one_or_none()
    request.state.current_user = user
    return user


def login_user(request: Request, user_id: int) -> None:
    request.session["user_id"] = user_id


def logout_user(request: Request) -> None:
    request.session.pop("user_id", None)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
```

Два дизайна-решения, на которые стоит обратить внимание:

1. **`user_id` проверяется запросом в БД на каждый запрос.** Плюс: мгновенная
   инвалидация — смена email, удаление пользователя, смена аватара видны сразу,
   «протухших» сессий с устаревшими данными не бывает. Минус: +1 SELECT на запрос
   (для учебного проекта несущественно).
2. **`request.state.current_user` как канал передачи.** Middleware вычисляет
   пользователя один раз, а роуты и зависимости читают его через
   `_get_request_user(request)` — нет повторных запросов к БД и нет дублирования
   логики загрузки.

### 5.2. Middleware — `md_articles/auth_middleware_helpers.py`

```python
async def inject_current_user_middleware(request: Request, call_next):
    """HTTP-middleware: подгружает current_user для каждого запроса."""
    async with db_manager.session_factory() as session:
        await get_current_user(request, session)
        response = await call_next(request)
    return response
```

Сессия БД открывается через фабрику проекта (`db_manager.session_factory()`), а не
через DI `CurrentSession` — потому что middleware выполняется **вне** системы
зависимостей FastAPI и не может получить `Depends`.

### 5.3. Модель пользователя — `md_articles/models.py`

```python
class BlogUser(Base):
    """Пользователь блога (атрибут is_authenticated для совместимости)."""

    __tablename__ = "blog_user"

    id: Mapped[int_primary_key]
    username: Mapped[str_len_20] = mapped_column(unique=True, nullable=False)
    email: Mapped[str_len_120] = mapped_column(unique=True, nullable=False)
    image_file: Mapped[str_len_20] = mapped_column(nullable=False, default="default.jpg")
    password: Mapped[str_len_60] = mapped_column(nullable=False)   # bcrypt-хеш

    posts: Mapped[list["BlogPost"]] = relationship(
        back_populates="author",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    @property
    def is_authenticated(self) -> bool:
        """Совместимость с UserMixin — всегда True для реального объекта."""
        return True
```

- `password: str_len_60` — ровно 60 символов, это длина стандартного bcrypt-хеша
  (`$2b$12$` + соль + хеш). В БД **нет** открытых паролей.
- `is_authenticated` — стандартное свойство для шаблонов форм: всегда `True` для
  реального объекта. Свойство не используется JSON API, но оставлено как часть
  контракта объекта пользователя для совместимости с фронтенд-формами.
- Уникальность `username` и `email` обеспечивается и на уровне БД (`unique=True`),
  и предварительной проверкой в API (`_username_exists` / `_email_exists`).

### 5.4. Регистрация — `api_blog.py::register_api`

```python
@router_blog_api.post("/register", name="blog_api.register")
async def register_api(
    request: Request,
    session: CurrentSession,
    payload: RegisterIn,
):
    await validate_csrf_header(request)

    if _get_request_user(request) is not None:
        raise HTTPException(status_code=400, detail="Already authenticated")

    errors: dict[str, list[str]] = {}
    username = payload.username.strip()
    email = payload.email.strip()

    if not username:
        errors.setdefault("username", []).append("This field is required.")
    elif len(username) < 2 or len(username) > 20:
        errors.setdefault("username", []).append(
            "Field must be between 2 and 20 characters long."
        )

    if not email:
        errors.setdefault("email", []).append("This field is required.")
    elif not _is_valid_email(email):
        errors.setdefault("email", []).append("Invalid email address.")

    # ... password / confirm_password / уникальность username и email ...

    if errors:
        return _validation_response(errors)

    hashed_password = hash_password(payload.password)
    user = BlogUser(username=username, email=email, password=hashed_password)
    logF.info(f"register_api = {user}")
    session.add(user)
    await session.commit()

    return {
        "message": "Your account has been created! You are now able to log in",
        "category": "success",
    }
```

Особенности:

- **Валидация «в стиле WTForms», а не pydantic-ограничениями.** Схема `RegisterIn`
  — просто строки, вся проверка (обязательность, длина 2–20, формат email,
  совпадение паролей, уникальность) делается вручную и собирается в
  `{"errors": {поле: [сообщения]}}`. Это сознательно: фронтенд React ждёт именно
  такой формат ошибок по полям (обрабатывает его `custom_request_validation_exception_handler`
  и страницы форм).
- **Регистрация не логинит автоматически** — пользователь должен войти отдельно
  (явное требование дизайна: разделить «создание аккаунта» и «вход»).
- **Защита от повторной регистрации под своей сессией**: `Already authenticated` → 400.

### 5.5. Вход — `api_blog.py::login_api`

```python
@router_blog_api.post("/login", name="blog_api.login")
async def login_api(
    request: Request,
    session: CurrentSession,
    payload: LoginIn,
):
    await validate_csrf_header(request)

    if _get_request_user(request) is not None:
        raise HTTPException(status_code=400, detail="Already authenticated")

    errors: dict[str, list[str]] = {}
    if not payload.email:
        errors.setdefault("email", []).append("This field is required.")
    if not payload.password:
        errors.setdefault("password", []).append("This field is required.")
    if errors:
        return _validation_response(errors)

    email = payload.email.strip()
    result = await session.execute(select(BlogUser).where(BlogUser.email == email))
    user = result.scalar_one_or_none()

    if user and verify_password(payload.password, user.password):
        login_user(request, user.id)
        return {
            "message": "You are now logged in",
            "category": "success",
            "user": _user_out(user).model_dump(),
        }

    return JSONResponse(
        status_code=401,
        content={
            "message": "Login Unsuccessful. Please check email and password",
            "category": "danger",
        },
    )
```

Схема входа:

```python
class LoginIn(BaseModel):
    email: str = ""
    password: str = ""
    remember: bool = False
```

Заметки по безопасности:

- **Единое сообщение об ошибке** для «нет такого email» и «неверный пароль» —
  не раскрывает, какие именно учётные записи существуют (защита от user enumeration).
- **`user and verify_password(...)`** — короткое замыкание: если пользователя нет,
  bcrypt не вызывается. (Строго говоря, это создаёт timing-различие «существует ли
  email» — классический ответ на это, фиктивный хеш, здесь не применяется.)
- **`remember` принимается, но не используется** — срок сессии всегда 14 дней
  (`max_age` в middleware). Поле в схеме оставлено для совместимости с фронтенд-формой,
  но сервер его игнорирует (см. `12` наблюдений ниже).

### 5.6. Клиентская часть — `frontend/src/api/client.ts`

```typescript
// Все запросы идут с cookie-сессией (credentials: 'include').
// State-changing запросы требуют CSRF-токена:
//   - JSON (postJson) -> заголовок X-CSRF-Token;
//   - multipart (postMultipart) -> поле формы csrf_token
const res = await fetch(path, { credentials: 'include', ...init });

// GET /api/blog/csrf — создаёт/возвращает csrf_token из сессии.
export async function getCsrfToken(): Promise<string> {
  const data = await getJson<{ csrf_token: string }>('/api/blog/csrf');
  return data.csrf_token;
}

// POST с JSON-телом; CSRF-токен кладём в заголовок X-CSRF-Token.
export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const token = await getCsrfToken();
  // ...
  'X-CSRF-Token': token,
}

// POST с multipart-формой; CSRF-токен передаётся полем csrf_token.
export async function postMultipart<T>(path: string, formData: FormData): Promise<T> {
  if (!formData.has('csrf_token')) {
    formData.set('csrf_token', await getCsrfToken());
  }
  // ...
}
```

Три момента:

- **`credentials: 'include'`** — браузер обязан отправлять cookie сессии с каждым
  fetch-запросом; без этого флага cookie на same-origin обычно и так уходит, но флаг
  делает намерение явным (и необходим при выносе API на другой домен).
- **CSRF-токен запрашивается лениво** — `getCsrfToken()` дергает `GET /api/blog/csrf`
  при первой изменяющей операции и далее переиспользуется из сессии.
- Два транспорта CSRF — потому что multipart-форму нельзя сопровождать произвольным
  заголовком без потери простоты: токен кладётся полем формы (только для
  `POST /api/blog/account` с загрузкой аватара).

---

## 6. CSRF-защита: зачем и как

### 6.1. Зачем она нужна именно для cookie-сессий

Аутентификация через cookie имеет врождённую особенность: **браузер прикладывает
cookie к каждому запросу на этот домен автоматически** — в том числе к запросу,
который злой сайт инициировал из вкладки жертвы (form POST, автосабмит). Если бы
защиты не было, страница злоумышленника могла бы, например, разлогинить пользователя
или изменить его аккаунт, даже не зная пароля. Поэтому для cookie-сессий CSRF-токен
обязателен; для JWT в заголовке `Authorization` он не нужен (токен браузер сам не
подставит).

### 6.2. Реализация — `api_blog.py`

Генерация (один токен на всю сессию):

```python
def _ensure_csrf_token(request: Request) -> str:
    """Вернуть существующий CSRF-токен или создать новый в сессии."""
    token = request.session.get("csrf_token")
    if not token:
        import secrets
        token = secrets.token_hex(32)
        request.session["csrf_token"] = token
    return token
```

Два валидатора под два транспорта:

```python
async def validate_csrf_header(request: Request) -> None:
    """CSRF для JSON POST-роутов: заголовок X-CSRF-Token против сессии."""
    header_token = request.headers.get("X-CSRF-Token")
    session_token = request.session.get("csrf_token")
    if not session_token or not header_token or header_token != session_token:
        raise HTTPException(status_code=403, detail="CSRF token mismatch")


async def validate_csrf_form(request: Request) -> None:
    """CSRF для multipart /api/blog/account: поле формы csrf_token."""
    form = await request.form()
    session_token = request.session.get("csrf_token")
    form_token = form.get("csrf_token")
    if not session_token or not form_token or form_token != session_token:
        raise HTTPException(status_code=403, detail="CSRF token mismatch")
```

Выдача токена клиенту:

```python
@router_blog_api.get("/csrf", name="blog_api.csrf")
async def csrf_token(request: Request):
    token = _ensure_csrf_token(request)
    return {"csrf_token": token}
```

Свойства реализации:

- **Сравнение `!=`, а не constant-time.** Для 64-символьного случайного hex-токена
  timing-атака практического значения не имеет, но `secrets.compare_digest` был бы
  формально строже.
- **Токен живёт в сессии, а не в отдельной cookie** — он не может «разъехаться»
  с сессией: логин/логат перезаписывают cookie, токен остаётся валидным, пока жива
  сессия.
- **Нет ротации при логине.** После входа `csrf_token` не пересоздаётся — это
  допустимо (токен не секретен для владельца сессии), хотя строгие гайдлайны
  (OWASP) рекомендуют ротацию при смене уровня привилегий.

### 6.3. Матрица покрытия эндпоинтов

| Эндпоинт | Метод | CSRF | Логин |
|---|---|---|---|
| `/api/blog/csrf` | GET | — (выдаёт токен) | нет |
| `/api/blog/current_user` | GET | — | нет |
| `/api/blog/register` | POST | заголовок | нет |
| `/api/blog/login` | POST | заголовок | нет |
| `/api/blog/logout` | POST | заголовок | нет |
| `/api/blog/account` | GET | — | `require_login_api` |
| `/api/blog/account` | POST | **поле формы** (multipart) | `require_login_api` |
| `/api/blog/art_manage` | GET | — | `require_login_api` |
| `/api/blog/art_manage/add_all` | POST | заголовок | `require_login_api` |
| `/api/blog/art_manage/meta` | POST | заголовок | `require_login_api` |

Публичное чтение (`articles`, `sections`, `articles/{id}`) не защищено — так и
задумано: блог читают гости.

---

## 7. Авторизация vs аутентификация: контроль доступа

### 7.1. Зависимость `require_login_api`

```python
def _get_request_user(request: Request) -> BlogUser | None:
    return getattr(request.state, "current_user", None)


async def require_login_api(request: Request) -> None:
    """Зависимость для API-роутов вместо редиректа — 403 JSON."""
    if _get_request_user(request) is None:
        raise HTTPException(status_code=403, detail="Authentication required")
```

Применение — одна строка в сигнатуре роута:

```python
@router_blog_api.get("/account", name="blog_api.account_get")
async def account_get_api(
    request: Request, _user=Depends(require_login_api)
):
    return {"user": _user_out(_get_request_user(request)).model_dump()}
```

Почему 403, а не редирект 302 на `/login`: это **JSON API для SPA**. Редирект из
fetch-обработчика фронтенд не увидит как редирект (fetch следует за ним молча и
получит HTML), а 403 — однозначный сигнал «покажи форму логина».

### 7.2. Границы модели доступа

- Ролей нет: **любой** вошедший пользователь может открыть `/api/blog/art_manage`
  и править YAML-реестр статей (`add_all`, `meta`). Для учебного блога это
  приемлемый компромисс — граница «гость vs вошедший» достаточна для демонстрации.
- «Владелец ресурса» не проверяется: статьи не привязаны к автору через API
  управления — реестр общий.
- Единственная проверка идемпотентности пользователя — `Already authenticated`
  в `register`/`login`.

---

## 8. Почему выбран именно этот способ

### 8.1. Главная причина: минимальная зависимость от внешних прокси

Cookie-сессия на одном origin — это **нулевая инфраструктура вокруг** (нет Redis
для хранения сессий, нет провайдера OAuth2, нет refresh-токенов и JWT-валидации).
`SessionMiddleware` из Starlette + `bcrypt` из зависимостей покрывают весь цикл:
вход → хеш → сессия → проверка → логаут. Для учебного проекта, где инфраструктура
должна запускаться одной командой `uvicorn`, это решающий фактор.

### 8.2. Вторая причина: SPA + same-origin

Фронтенд собирается Vite и раздаётся самим FastAPI (`mount /assets` + SPA catch-all
на `frontend/dist/index.html`). API и SPA — **один origin**, поэтому:

- cookie-сессия работает без CORS-танцев (`credentials: 'include'` достаточно);
- нет необходимости в JWT «чтобы не хранить состояние» — состояние и так одно
  (cookie), сервер не хранит ничего;
- CSRF-токен легко выдать через `GET /api/blog/csrf` и вернуть заголовком.

### 8.3. Третья причина: учебная наглядность

Проект — «исполняемый каталог приёмов». Свой маленький, читаемый за 50 строк слой
авторизации (`auth_middleware_helpers.py`) показывает механику лучше, чем готовая библиотека
(fastapi-users и т.п.): видно, где ставится `user_id`, где проверяется пароль,
где валидируется CSRF. Никакой магии.

---

## 9. Сравнение с альтернативами: JWT, OAuth2, серверные сессии

### 9.1. Cookie-сессия (выбрано) vs JWT в localStorage

| Критерий | Cookie-сессия | JWT (Bearer) |
|---|---|---|
| Хранение на клиенте | подписанная cookie, HttpOnly недоступна JS | обычно localStorage — читается любым XSS |
| Отзыв (logout «везде», бан) | мгновенный: БД-проверка `user_id` на каждом запросе | сложный: нужен blacklist / короткий TTL + refresh |
| Изменение данных пользователя | видно сразу (пользователь перечитывается из БД) | «заморожен» до конца срока токена |
| CSRF | **требует токена** (в проекте реализован) | не требуется (заголовок не ставится браузером сам) |
| Межсервисное API / мобильные клиенты | неудобно (cookie) | удобно |
| Объём кода | меньше (нет refresh-логики) | больше (access+refresh, ротация) |
| Размер «токена» | `user_id` (4 байта) | payload с claims (сотни байт на каждый запрос) |

Для этого проекта решающие строки — первая и вторая: XSS-безопасность HttpOnly-cookie
и мгновенный отзыв через перечитывание пользователя из БД (`get_current_user`).
JWT дал бы больше кода (refresh, expiry, blacklist) без единой выгоды: API один,
origin один, микросервисов нет.

### 9.2. Cookie-сессия vs серверные сессии (Redis/БД)

Серверные сессии (sid в cookie, данные в Redis) дают то же HttpOnly-безопасность и
лёгкий отзыв, плюс токен в cookie не читаем клиентом. Минусы для этого проекта:
нужен внешний компонент (Redis/таблица сессий) и дополнительная инфраструктура
запуска. `SessionMiddleware` из коробки решает задачу без единой зависимости —
в учебном проекте, где БД и так sqlite по умолчанию (`dev_sqlite.env`), это весомо.
Ограничение клиентской сессии (4 КБ на cookie) здесь не мешает: в сессии два
маленьких ключа.

### 9.3. Почему не OAuth2 / внешний IdP

- Нет внешних провайдеров в требованиях; регистрация — email+пароль.
- OAuth2-схема в Swagger (`utils/docs.py`) — только оформление кнопки Authorize
  в `/docs`, реального flows нет.
- Обучение: собственный цикл «register → login → session → logout» нагляднее
  делегированной аутентификации.

### 9.4. Почему bcrypt, а не argon2 / pbkdf2

- **bcrypt** — отраслевой стандарт с длинной историей, `bcrypt.gensalt()` даёт
  случайную соль на каждый пароль, cost-фактор замедляет перебор; реализация —
  зрелый пакет `bcrypt`, две строки кода.
- **argon2** — современнее (победитель PHC), но требует отдельного пакета и не даёт
  практической выгоды для учебного проекта.
- **pbkdf2** — приемлем, но bcrypt сильнее против GPU-перебора.
- Хеш укладывается в `str_len_60` — стандартный формат `$2b$...`, миграции не нужны.

---

## 10. Преимущества и недостатки выбранного решения

### 10.1. Преимущества (что так даёт именно cookie-сессия + bcrypt + CSRF)

1. **Минимальный объём кода и зависимостей.** Весь слой — `auth_middleware_helpers.py` (~140 строк)
   + функции-валидаторы в `api_blog.py`. Ни fastapi-users, ни itsdangerous-обвязки,
   ни хранилища сессий: `SessionMiddleware` и `bcrypt` уже в зависимостях.
2. **Мгновенный отзыв и консистентность.** `get_current_user` перечитывает
   пользователя из БД на каждый запрос: удаление аккаунта или смена email
   действует немедленно, без ожидания истечения токена — JWT не умеет это даром.
3. **HttpOnly-cookie против XSS.** Сессия недоступна JavaScript'у, поэтому кража
   токена через XSS-уязвимость в SPA (а React-приложение тянет зависимости)
   невозможна в принципе — в отличие от JWT в localStorage.
4. **CSRF закрывает главную слабость cookie.** Все изменяющие эндпоинты проверяют
   токен, клиент централизованно подставляет его в `client.ts` — дыр в покрытии нет
   (см. матрицу в 6.3).
5. **Простая модель для SPA на одном origin.** Нет refresh-токенов, нет silent
   refresh, нет перехвата 401 с переавторизацией — cookie живёт 14 дней,
   фронтенд просто делает `credentials: 'include'`.
6. **Прозрачность для обучения.** Каждый шаг аутентификации виден в коде явно:
   `login_user` → сессия; `require_login_api` → 403; `validate_csrf_*` → 403.
   Идеально для демонстрационного проекта.
7. **Пароли — bcrypt с солью.** Утечка БД не раскрывает пароли; cost-фактор по
   умолчанию (12) адекватен.

### 10.2. Недостатки и ограничения (честная сторона)

1. **CSRF — постоянный налог cookie-сессий.** Каждый новый изменяющий роут обязан
   вызвать `validate_csrf_header/form`; забыть — и защита дырявая. JWT от этого
   налога свободен. Смягчение в проекте: вызовы стоят во всех 6 state-changing
   роутах, и клиент подставляет токен централизованно.
2. **Клиентская сессия читаема пользователем.** `user_id` и `csrf_token` в cookie
   закодированы, но не зашифрованы. Для этих данных это неважно, но секреты в
   сессию класть нельзя.
3. **`secret_key` — единственная точка доверия.** Компрометация ключа = подделка
   любых сессий; дефолт `"dev-insecure-secret-key-change-me"` годится только для
   разработки. Нет ротации ключей.
4. **+1 SELECT на каждый запрос** (перечитывание пользователя). При росте нагрузки
   потребует кэша или перехода на серверные сессии.
5. **Нет rate-limiting на `/login`** — брутфорс ничем не ограничен.
6. **Нет ротации идентификатора сессии при логине** (session fixation):
   `SessionMiddleware` перезаписывает cookie с новым содержимым, но формально
   «фиксация» старой сессии злоумышленником на shared-машине не нейтрализуется
   явно (OWASP рекомендует полный сброс сессии при входе).
7. **`remember` игнорируется** — срок всегда 14 дней, поле схемы — мёртвое.
8. **Нет ролей** — любой вошедший правит реестр статей; для учебного проекта
   приемлемо, для «настоящего» — нет.
9. **Timing-различие** «email существует / не существует» на `/login` (bcrypt
   пропускается, если пользователя нет) — теоретический канал перечисления
   пользователей.

### 10.3. Сводка «почему так»

Совокупность условий — учебный проект, один origin, одна БД, отсутствие
микросервисов, желание показать механику явно — делает cookie-сессию оптимальным
выбором: JWT решал бы здесь несуществующие проблемы и добавил бы код, серверные
сессии добавили бы инфраструктуру, OAuth2 — внешнюю зависимость от провайдера.
Выбранное решение покрывает OWASP-минимум для cookie-аутентификации: HttpOnly
(даёт Starlette), подпись (HMAC secret_key), CSRF-токены, bcrypt-хеши, единые
сообщения об ошибках входа.

---

## 11. Наблюдения и потенциальные улучшения

Ниже — не дефекты, а точки роста, если проект когда-нибудь выйдет за рамки учебного:

1. **Rate-limit на `/api/blog/login`** (например, 5 попыток / минуту на IP+email) —
   закрыло бы брутфорс и user enumeration по времени.
2. **`secrets.compare_digest`** для сравнения CSRF-токенов — формальная
   constant-time строгость.
3. **Ротация `csrf_token` при логине/логауте** — гигиена по OWASP.
4. **Полный сброс сессии при логине** (session fixation).
5. **Использовать или убрать `remember`** — сейчас поле обрабатывается фронтендом
   (чекбокс), но сервер его игнорирует.
6. **Вынос `secret_key` в обязательный параметр окружения** для «прод»-профилей
   (сейчас дефолт без предупреждения в логе).
7. **Роли** (`is_admin`) для `/art_manage` — единственное место, где разграничение
   прав имело бы смысл.

---

## 12. Приложение: карта файлов авторизации

```
fastapi-application/
├── core/config.py                       # WebConfig.secret_key (подпись cookie)
├── md_articles/
│   ├── frontend_auth_include.py         # setup_auth_static_include(): middleware + static + router
│   ├── auth_middleware_helpers.py       # auth_add_middleware, current_user-middleware,
│   │                                    #   CSRF-хелперы, hash_password/verify_password (bcrypt)
│   ├── models.py                        # BlogUser (blog_user): password = bcrypt-хеш
│   └── api_blog.py                      # JSON API: /csrf /register /login /logout
│                                        #   /account; require_login_api; validate_csrf_*
frontend/src/api/
├── client.ts                            # credentials: 'include', getCsrfToken,
│                                        #   postJson (X-CSRF-Token), postMultipart (поле)
└── auth.ts                              # login/register/logout/account поверх client.ts
```

Ключевые места для быстрой навигации:

| Что | Файл |
|---|---|
| Подключение блога (middleware + static + JSON API) | `md_articles/frontend_auth_include.py::setup_auth_static_include` |
| `auth_add_middleware`: `SessionMiddleware` + current_user-middleware + exception handler | `md_articles/auth_middleware_helpers.py::auth_add_middleware` |
| Сессия: login/logout/get_current_user + bcrypt | `md_articles/auth_middleware_helpers.py` (login_user/logout_user/get_current_user, hash_password/verify_password) |
| CSRF: генерация + 2 валидатора | `md_articles/auth_middleware_helpers.py::_ensure_csrf_token`, `validate_csrf_header`, `validate_csrf_form` |
| `require_login_api` (403) | `md_articles/auth_middleware_helpers.py::require_login_api` |
| Логин/регистрация/логаут | `md_articles/api_blog.py` |
| Клиент: cookie + CSRF | `frontend/src/api/client.ts` |

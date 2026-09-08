# Авторизация в блоге — как устроено в коде

> Цепочка в порядке реального прохождения запроса. Каждый шаг — кусок кода
> с короткой подписью «зачем он тут». Никаких сравнений и альтернатив — только то,
> что реально исполняется.
>
> Примечание (2026-09-07): имена файлов и функций обновлены после разделения auth-слоя
> (`middleware_auth.py` / `helpers_auth.py` / `api_auth.py`). Канонический разбор —
> `../docs/04_authorization.md`, улучшение и замена библиотекой —
> `../docs/05_authorization_upgrade.md`.

---

## Какие файлы участвуют

**Сервер** (`../fastapi-application`):

```
md_articles/setup_frontend.py      # include_router_api_frontend(): middleware + static + роутеры
md_articles/middleware_auth.py     # add_middleware_auth, get_current_user, inject_current_user
md_articles/helpers_auth.py        # login_user, logout_user, bcrypt, CSRF, require_login_api
md_articles/models.py              # BlogUser — таблица blog_user
md_articles/api_auth.py            # auth-роуты /api/blog: csrf, register, login, logout, account
md_articles/api_blog.py            # статьи /api/blog: sections, articles, art_manage
```

**Клиент** (`../frontend/src/api`):

```
client.ts                    # fetch + credentials:'include' + CSRF в заголовок/форму
auth.ts                      # login/register/logout/account поверх client.ts
```

---

## 1. Приложение поднимает сессии и middleware

`md_articles/setup_frontend.py` — функция `include_router_api_frontend`,
вызывается из `main.py`:

```python
def include_router_api_frontend(app: FastAPI) -> None:
    logF.info("include_router_api_frontend: подключение auth, /static, router_*")

    add_middleware_auth(app)

    app.mount(
        "/static",
        StaticFiles(directory=BASE_DIR / "static", check_dir=False),
        name="static",
    )

    app.include_router(router_auth_api)
    app.include_router(router_blog_api)
```

`SessionMiddleware` подключает `request.session` — это подписанная HMAC-cookie
`session`. Всё, что положат в `request.session[...]`, попадёт в эту cookie, и
браузер будет прикладывать её к каждому запросу на этот origin.

`inject_current_user_middleware` — наша обёртка, кладёт текущего пользователя
в `request.state.current_user` (подробнее в шаге 8).

`secret_key` берётся из `settings.web.secret_key` — поле `WebConfig` в
`core/config.py`, переопределяется через `APP__WEB__SECRET_KEY`.

---

## 2. Клиент шлёт запросы с cookie

`../frontend/src/api/client.ts` — единственная точка, где делаются `fetch` к API:

```typescript
// frontend/src/api/client.ts:30
async function request(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(path, { credentials: 'include', ...init });
  return res;
}
```

`credentials: 'include'` — это сигнал браузеру: «обязательно приложи cookie
к запросу и прими `Set-Cookie` от сервера». Без флага same-origin cookie и так
бы уехали, но флаг делает намерение явным и нужен для CORS, если когда-нибудь
разнесём origin.

---

## 3. Получение CSRF-токена перед записью

Тот же `client.ts`. Перед каждым POST читаем токен с сервера и кладём в
заголовок:

```typescript
// frontend/src/api/client.ts:45-63
// GET /api/blog/csrf — создаёт/возвращает csrf_token из сессии.
export async function getCsrfToken(): Promise<string> {
  const data = await getJson<{ csrf_token: string }>('/api/blog/csrf');
  return data.csrf_token;
}

// POST с JSON-телом; CSRF-токен кладём в заголовок X-CSRF-Token.
export async function postJson<T = unknown>(
  path: string,
  body: unknown,
): Promise<T> {
  const token = await getCsrfToken();
  const res = await request(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': token,
    },
    body: JSON.stringify(body),
  });
  return (await ensureOk(res)) as T;
}
```

Для multipart (загрузка аватара в `/api/blog/account`) токен кладётся **полем
формы**, потому что заголовок `X-CSRF-Token` к `FormData` приклеивать
неудобно:

```typescript
// frontend/src/api/client.ts:68-79
// POST с multipart-формой; CSRF-токен передаётся полем csrf_token.
export async function postMultipart<T = unknown>(
  path: string,
  formData: FormData,
): Promise<T> {
  if (!formData.has('csrf_token')) {
    formData.set('csrf_token', await getCsrfToken());
  }
  const res = await request(path, {
    method: 'POST',
    // Content-Type не ставим руками: браузер сам подставит boundary.
    body: formData,
  });
  return (await ensureOk(res)) as T;
}
```

---

## 4. Бэк выдаёт CSRF-токен

`md_articles/helpers_auth.py` — генератор токена:

```python
# md_articles/helpers_auth.py:102
def ensure_csrf_token(request: Request) -> str:
    """Вернуть существующий CSRF-токен или создать новый в сессии."""
    token = request.session.get("csrf_token")
    if not token:
        import secrets

        token = secrets.token_hex(32)
        request.session["csrf_token"] = token
    return token
```

Сам роут:

```python
# md_articles/api_auth.py:48 — роут по имени auth.csrf
@router_auth_api.get("/csrf", name="auth.csrf")
async def csrf_token(request: Request):
    token = ensure_csrf_token(request)
    return {"csrf_token": token}
```

Токен **кладётся в ту же подписанную cookie `session`**, что и `user_id`.
Один раз выданный — переиспользуется, пока жива сессия.

---

## 5. Бэк проверяет CSRF на каждом записи

Два валидатора под два транспорта (JSON-заголовок и поле формы):

```python
# md_articles/helpers_auth.py:113-130
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

`/api/blog/register`, `/login`, `/logout`, `/art_manage/*` зовут
`validate_csrf_header`. `/api/blog/account` (multipart) зовёт
`validate_csrf_form`. Без токена — 403.

---

## 6. Логин: проверка пароля и запись в сессию

`md_articles/api_auth.py::login_api` — это и есть точка создания «токена»:

```python
# md_articles/api_auth.py:125-165
@router_auth_api.post("/login", name="auth.login")
async def login_api(
    request: Request,
    session: CurrentSession,
    payload: LoginIn,
):
    await validate_csrf_header(request)        # (1) CSRF

    if get_request_user(request) is not None:
        raise HTTPException(status_code=400, detail="Already authenticated")

    errors: dict[str, list[str]] = {}
    if not payload.email:
        errors.setdefault("email", []).append("This field is required.")
    if not payload.password:
        errors.setdefault("password", []).append("This field is required.")
    if errors:
        return validation_response(errors)

    email = payload.email.strip()
    result = await session.execute(select(BlogUser).where(BlogUser.email == email))
    user = result.scalar_one_or_none()

    if user and verify_password(payload.password, user.password):   # (2) bcrypt
        login_user(request, user.id)                                 # (3) сессия
        return {
            "message": "You are now logged in",
            "category": "success",
            "user": user_out(user).model_dump(),
        }

    return JSONResponse(
        status_code=401,
        content={
            "message": "Login Unsuccessful. Please check email and password",
            "category": "danger",
        },
    )
```

Три ключевых места пронумерованы:

1. **CSRF-проверка** — сначала, до любых обращений к БД.
2. **`verify_password`** — bcrypt-сравнение хеша из БД с присланным паролем.
3. **`login_user(request, user.id)`** — единственная строка, которая создаёт
   «вход». После неё `request.session["user_id"]` появляется в cookie.

Что лежит в БД — `md_articles/models.py`:

```python
# md_articles/models.py
class BlogUser(Base):
    __tablename__ = "blog_user"

    id: Mapped[int_primary_key]
    username: Mapped[str_len_20] = mapped_column(unique=True, nullable=False)
    email: Mapped[str_len_120] = mapped_column(unique=True, nullable=False)
    image_file: Mapped[str_len_20] = mapped_column(
        nullable=False, default="default.jpg"
    )
    password: Mapped[str_len_60] = mapped_column(nullable=False)   # bcrypt-хеш
```

`password` всегда bcrypt-хеш формата `$2b$...`, 60 символов. Открытых паролей
в БД нет.

---

## 7. Что делает `login_user`

`md_articles/helpers_auth.py`:

```python
# md_articles/helpers_auth.py:80-82
def login_user(request: Request, user_id: int) -> None:
    request.session["user_id"] = user_id
```

Одна строка. После неё Starlette `SessionMiddleware` сам сформирует новую
подписанную cookie `session` с двумя ключами — `user_id` (наш) и `csrf_token`
(если был запрошен раньше через `GET /api/blog/csrf`). Эта cookie уйдёт в
ответе через `Set-Cookie`, браузер её запомнит.

`logout_user` ровно обратный:

```python
# md_articles/helpers_auth.py:84-85
def logout_user(request: Request) -> None:
    request.session.pop("user_id", None)
```

Используется в `/api/blog/logout` (`api_auth.py:168-173`):

```python
@router_auth_api.post("/logout", name="auth.logout")
async def logout_api(request: Request):
    await validate_csrf_header(request)
    logout_user(request)
    return {"message": "You have been logged out", "category": "success"}
```

`csrf_token` при логауте не удаляется — он сам по себе не даёт доступа.

---

## 8. Каждый следующий запрос: middleware читает сессию

`md_articles/middleware_auth.py::get_current_user` — то, что выполняется на **каждом**
HTTP-запросе к блогу (через middleware из шага 1):

```python
# md_articles/middleware_auth.py:17-30
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
```

Middleware, который это вызывает (`md_articles/middleware_auth.py:32-41`):

```python
async def inject_current_user_middleware(request: Request, call_next):
    """HTTP-middleware: подгружает current_user для каждого запроса."""
    async with db_manager.session_factory() as session:
        await get_current_user(request, session)
        response = await call_next(request)
    return response
```

Что это даёт: к моменту вызова любого роута блога в `request.state.current_user`
либо лежит `BlogUser`, либо `None`. Роут **не делает** `SELECT` сам — минус
один запрос на каждом эндпоинте, и логика «кто здесь?» живёт в одном месте.

---

## 9. Защита роутов: `Depends(require_login_api)`

`md_articles/helpers_auth.py`:

```python
# md_articles/helpers_auth.py:133-140
async def require_login_api(request: Request) -> None:
    """Зависимость для API-роутов вместо редиректа — 403 JSON."""
    if get_request_user(request) is None:
        raise HTTPException(status_code=403, detail="Authentication required")
```

Использование — одна строка в сигнатуре роута:

```python
# md_articles/api_auth.py:178-180 (account_get_api)
@router_auth_api.get("/account", name="auth.account_get")
async def account_get_api(
    request: Request, _user=Depends(require_login_api)
):
    return {"user": user_out(get_request_user(request)).model_dump()}
```

`get_request_user` — обёртка над `request.state.current_user`:

```python
# md_articles/helpers_auth.py:133-135
def get_request_user(request: Request) -> BlogUser | None:
    return getattr(request.state, "current_user", None)
```

`/api/blog/art_manage`, `/art_manage/add_all`, `/art_manage/meta` — те же
`Depends(require_login_api)`. Публичные (`/articles`, `/sections`,
`/articles/{id}`, `/current_user`, `/csrf`) — без зависимости.

Почему 403, а не редирект 302 на `/login`: это JSON API для SPA, а не HTML.
Редирект из fetch-обработчика бесполезен — fetch следует за ним молча и
вернёт HTML. 403 — однозначный сигнал «покажи форму входа».

---

## 10. Фронт реагирует на 403

`../frontend/src/api/auth.ts` — поверх `client.ts`:

```typescript
// frontend/src/api/auth.ts
// POST /api/blog/login — вход; в ответе приходит обновлённый user.
export function login(body: {
  email: string;
  password: string;
  remember?: boolean;
}): Promise<MessageResp & { user: User }> {
  return postJson<MessageResp & { user: User }>('/api/blog/login', body);
}

// GET /api/blog/account — данные аккаунта (403 для анонима).
export function getAccount(): Promise<{ user: User }> {
  return getJson<{ user: User }>('/api/blog/account');
}
```

Конкретный код редиректа на форму логина при 403 живёт в React-страницах
(используют `useAuth`-хуки и `extractErrors` из `auth.ts`). Сам `client.ts`
только бросает `ApiError` со статусом — обработка «куда идти при 403» лежит
уровнем выше, в UI.

---

## Итог одной картинкой

```
login (POST /api/blog/login)
    │
    ├── validate_csrf_header       helpers_auth.py:122
    ├── SELECT BlogUser WHERE email
    ├── bcrypt.checkpw             helpers_auth.py:95
    └── request.session["user_id"] = user.id     helpers_auth.py:80
                                          │
                                          ▼
            Set-Cookie: session=<подписано: {user_id, csrf_token}>
                                          │
                            ┌─────────────┴─────────────┐
                            │                           │
                  хранится в браузере       каждый запрос на этот origin
                  до 14 дней                автоматически шлёт cookie
                            │                           │
                            └─────────────┬─────────────┘
                                          │
                                          ▼
              request /api/blog/account (или любой защищённый)
                                          │
              ┌───────────────────────────┴───────────────────────────┐
              │                                                       │
   SessionMiddleware расшифровывает cookie             X-CSRF-Token?
   и кладёт в request.session                                     │
              │                                                   │
              ▼                                                   ▼
   inject_current_user_middleware                  validate_csrf_*
   get_current_user -> SELECT BlogUser               (helpers_auth.py:113/122)
   -> request.state.current_user                              │
              │                                               │
              ▼                                               │
   Depends(require_login_api)                                 │
   if current_user is None -> 403                             │
              │                                               │
              ▼                                               ▼
                              handler выполняется
```

**Где «создаётся токен»:** `login_user(request, user.id)` в
`helpers_auth.py:80` (одна строка после bcrypt-проверки).

**Куда сохраняется:** в подписанную cookie `session` через Starlette
`SessionMiddleware` (`md_articles/middleware_auth.py::add_middleware_auth`).

**Как попадает во фронт:** через `Set-Cookie` в ответе сервера, браузер
запоминает автоматически.

**Как браузер его шлёт:** автоматически на каждый same-origin запрос +
`credentials: 'include'` в fetch (`client.ts:29`).

**Где проверяется при ограничении доступа:** двухуровнево — middleware
грузит `BlogUser` в `request.state.current_user` (`middleware_auth.py`), а
`Depends(require_login_api)` отдаёт 403 если state `None`
(`helpers_auth.py:137`). Плюс CSRF-валидаторы (`helpers_auth.py:113/122`) на каждом
state-changing эндпоинте.
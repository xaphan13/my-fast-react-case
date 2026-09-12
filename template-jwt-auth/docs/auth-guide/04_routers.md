# 04 — Роутеры: main.py, api/auth.py, dependencies.py

## 1. `app/main.py` — сборка и защита всего приложения

### 1.1. Подключение роутеров

```python
# Auth routes (login, logout) - using the chosen backend (cookie in this case)
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/cookie",
    tags=["auth"],
)
# Внутри появятся два эндпоинта:
#   POST /auth/cookie/login   (name="auth:jwt.login")  — form-data, ответ 204 + cookie
#   POST /auth/cookie/logout  (name="auth:jwt.logout") — ответ 204 + очистка cookie
# Префикс "/auth/cookie" выбран, чтобы развести машинный API и HTML-страницы:
#   /auth/* — страницы для людей, /auth/cookie/* — «провайдер сессии».

# User management routes (CRUD) - e.g., /users/me
app.include_router(user_api_router.router)
# Внутри app/api/user.py подключён get_users_router с собственным prefix="/users".

# Custom HTML-serving auth routes and custom /register endpoint
app.include_router(auth_api_router.router, prefix="/auth")
# GET/POST /auth/login, GET/POST /auth/register, POST /auth/logout — наши.
```

Порядок включения не важен (пути не пересекаются), но важно, что **имена
роутов** (`auth_login_page`, `auth_logout`, ...) используются в
`request.url_for(...)` по всему проекту — переименование имени ломает
`exception_handler` и шаблоны.

### 1.2. 401-handler — главная HTMX-адаптация

```python
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    """
    Custom exception handler to manage HTTPExceptions.
    - For 401 Unauthorized:
        - HTMX requests: Returns HX-Redirect header to the login page.
        - Non-HTMX requests: Returns a standard 302 redirect to the login page.
    - For other HTTPExceptions: Returns the default JSON response.
    """

    if exc.status_code == 401:
        login_url = request.url_for("auth_login_page")
        # url_for по ИМЕНИ роута, а не строкой "/auth/login":
        #   переживает смену префиксов. Имя задано в app/api/auth.py:16.
        if is_htmx(request):
            # For HTMX requests resulting in 401, trigger a client-side redirect
            # via HX-Redirect header.
            return Response(
                content="",
                status_code=200,  # 200 is often used with HX-Redirect
                # почему 200, а не 401: HTMX на 4xx вызывает событие
                #   htmx:responseError, и глобальный обработчик в base.jinja2
                #   показал бы «An error occurred» вместо перехода на логин.
                #   200 + HX-Redirect заставляет HTMX сделать полноценный
                #   переход браузера на /auth/login.
                headers={"HX-Redirect": str(login_url)},
            )
        else:
            # For non-HTMX requests (e.g., full page loads), perform a standard
            # server-side redirect to the login page.
            return RedirectResponse(url=str(login_url), status_code=302)

    # For all other HTTPExceptions (not 401), return the default JSON response
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )
```

**Что покрывается этим хендлером:** любой `HTTPException(401)` из любого
роута — включая `current_user(active=True)` на `/items`, `/profile`,
`/users/me`. Именно поэтому `curl -i http://127.0.0.1:8000/items` без cookie
даёт `302` на `/auth/login`, а не JSON.

**Что НЕ покрывается:** `RequestValidationError` (422) — это не
`HTTPException`, он идёт штатным JSON-ответом FastAPI. Поэтому шаблон
регистрации парсит JSON `detail` из 422/400 (см. [06](06_frontend_htmx.md)).

**Компромисс:** HTMX-запрос с «настоящей» 401 (например, заблокированный
`is_active=False` пользователь) тоже уйдёт редиректом на логин — сервер не
различает «нет сессии» и «сессия недействительна». Это осознанный fail-open
для UX.

### 1.3. Lifespan

```python
@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    # Log startup information (server logs only, not web pages)
    key_start = settings.SECRET_KEY[: min(len(settings.SECRET_KEY), 8)]
    logger.info("Starting FastAPI HTMX Starter application")
    logger.info("Using SECRET_KEY starting with: %s...", key_start)
    logger.info(
        "Ensure SECRET_KEY is set persistently in your .env file " "for sessions to work across restarts.",
    )
    # Только предупреждение: если .env пуст, ключ сгенерирован заново и все
    #   сессии умрут при следующем рестарте. Валидацию см. в 08-й странице.

    await init_db()   # create_all — dev-удобство, конкурирует с Alembic
    yield
```

### 1.4. Публичная страница с опциональным пользователем

```python
@app.get("/")
async def index(
    request: Request,
    user: User | None = Depends(fastapi_users.current_user(optional=True)),
) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.jinja2",
        {"request": request, "user": user},
    )
```

Паттерн: **`user` в контекст шаблона кладётся явно**. Библиотека не делает
этого сама; забытый `user` = навигация всегда показывает «Login/Register».

## 2. `app/api/auth.py` — HTML-строки поверх библиотеки

### 2.1. Страницы входа и регистрации

```python
router: APIRouter = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)


@router.get("/login", response_class=HTMLResponse, name="auth_login_page")
async def get_login_page(
    request: Request,
    user: User | None = Depends(fastapi_users.current_user(optional=True)),
) -> Response:
    if user:
        return RedirectResponse(url=request.url_for("index"), status_code=302)
        # Уже залогинен — на страницу входа не пускаем. optional=True даёт
        #   None для анонима вместо 401 — это ключ к «мягкой» проверке.

    return templates.TemplateResponse("auth/login.jinja2", {"request": request})


@router.get("/register", response_class=HTMLResponse, name="auth_register_page")
async def get_register_page(
    request: Request,
    user: User | None = Depends(fastapi_users.current_user(optional=True)),
) -> Response:
    if user:
        return RedirectResponse(url=request.url_for("index"), status_code=302)

    return templates.TemplateResponse("auth/register.jinja2", {"request": request})
```

### 2.2. POST /auth/register — создание пользователя

```python
@router.post("/register", name="auth_register")
async def register_user(
    request: Request,
    user_create: UserCreate,                       # Pydantic-модель => тело JSON
    user_manager: UserManager = Depends(get_user_manager),
) -> Response:
    """Custom registration endpoint that redirects to login after success."""
    try:
        # Create the user
        user = await user_manager.create(user_create, safe=True, request=request)
        # safe=True: is_superuser/is_active/is_verified из тела игнорируются.
        # Бросает UserAlreadyExists -> 400 REGISTER_USER_ALREADY_EXISTS,
        # InvalidPasswordException -> 400 (если переопределён validate_password).

        logger.info("User %s registered successfully, redirecting to login", user.email)

        # Check if this is an HTMX request
        if is_htmx(request):
            # For HTMX requests, return an HX-Redirect header
            login_url = str(request.url_for("auth_login_page")) + "?registered=true"
            return Response(
                content="",
                status_code=200,
                headers={"HX-Redirect": login_url},
            )
            # Сервер решает, куда идти; клиент не дублирует логику.
            # ?registered=true — флаг для баннера на странице логина.
        else:
            # For regular requests, return a standard redirect
            login_url = str(request.url_for("auth_login_page")) + "?registered=true"
            return RedirectResponse(url=login_url, status_code=302)

    except Exception as e:
        logger.error("Registration failed: %s", str(e))
        # Re-raise the exception to let FastAPI Users handle it properly
        # This will return the appropriate error response
        raise
        # Логируем и пробрасываем: fastapi-users сам отдаст 400 с машинным
        #   кодом ошибки, который парсит шаблон. Ловить и «замалчивать» нельзя.
```

Зачем свой `/auth/register`, если у библиотеки есть `get_register_router`:
встроенный отдаёт JSON и не умеет редиректить браузер. Этот эндпоинт —
тонкая обёртка: тот же `user_manager.create`, но с redirect-поведением.
Роутер `get_register_router` в проекте **не подключён** — регистрация идёт
только через эту HTML-обёртку.

### 2.3. POST /auth/logout — почему не используется встроенный

```python
@router.post("/logout", name="auth_logout")
async def logout_user(
    request: Request,
    user: User = Depends(fastapi_users.current_user()),
    # Без cookie -> 401 -> (для HTMX) HX-Redirect на логин. То есть логаут
    #   анонима невозможен — корректно.
) -> Response:
    """Handle logout by making a request to the FastAPI Users logout endpoint."""
    logger.info("User %s logging out", user.email)

    # Check if this is an HTMX request
    if is_htmx(request):
        # For HTMX requests, return an HX-Redirect header to the home page
        # The cookie will be cleared by the FastAPI Users middleware
        return Response(
            content="",
            status_code=200,
            headers={
                "HX-Redirect": str(request.url_for("index")),
                "Set-Cookie": "auth=; Path=/; Max-Age=0; HttpOnly; SameSite=lax",
                # Ручная очистка cookie: имя "auth" продублировано строкой —
                #   при переименовании cookie в users.py менять ЗДЕСЬ тоже.
                #   Лучше собрать строку из cookie_transport.cookie_name.
            },
        )
    else:
        # For regular requests, clear the cookie and redirect
        response = RedirectResponse(url=request.url_for("index"), status_code=302)
        response.set_cookie(
            key="auth",
            value="",
            max_age=0,
            httponly=True,
            samesite="lax",
        )
        return response
```

**Зачем дублировать встроенный `/auth/cookie/logout`?** Встроенный отвечает
`204 No Content`. HTMX на 204 ничего не перерисует и никуда не перейдёт —
пользователь останется на странице с «мёртвой» навигацией. Поэтому UI шлёт
`hx-post` на **наш** `/auth/logout` (см. `base.jinja2:40`), который добавляет
`HX-Redirect`. Не-HTMX ветка просто повторяет очистку cookie, чтобы не
зависеть от встроенного роутера.

## 3. `app/api/dependencies.py` — is_htmx и мёртвый код

```python
from typing import Any

from fastapi import Request


def get_db(request: Request) -> Any:
    return request.state.db
    # ИЗВЕСТНЫЙ ДЕФЕКТ: мёртвый код. Никакой middleware не пишет request.state.db,
    #   функция нигде не вызывается. Реальный get_db — в app/core/database.py.
    #   При переносе НЕ копируйте; здесь она остаётся как ловушка для путаницы.


def is_htmx(request: Request) -> bool:
    """Checks if the request was made by HTMX."""
    htmx_request = request.headers.get("HX-Request", "false")
    return str(htmx_request).lower() == "true"
```

`is_htmx` используется **только для выбора формы ответа** (redirect vs
HX-Redirect, full page vs partial) — и **никогда** для самой аутентификации.
Это принципиально: авторизация не должна зависеть от типа клиента.

Использование как зависимости: `htmx: bool = Depends(is_htmx)` — так сделано
в `app/api/items.py:26`; ruff настроен не ругаться на вызов в дефолте
(`extend-immutable-calls` в `pyproject.toml`).

Дальше: [05_profile_and_users_api.md](05_profile_and_users_api.md) — профиль и `/users/*`.

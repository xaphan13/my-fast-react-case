"""
Авторизация блога `md_articles` — единая точка входа `auth_add_middleware(app)`.
Файл собирает всё, что относится к авторизации, в одном месте:

  - `auth_add_middleware(app)` — подключает
    `SessionMiddleware`, HTTP-middleware `inject_current_user_middleware`
    и обработчик `RequestValidationError` для `{"errors": {...}}` под формы фронтенда.
  - `inject_current_user_middleware` — кладёт `request.state.current_user`
    на каждый запрос через короткую сессию БД.
  - Хелперы сессии/паролей: `get_current_user`, `login_user`, `logout_user`,
    `hash_password`, `verify_password`.
  - CSRF и зависимости API: `validate_csrf_header`/`_form`, `require_login_api`,
    `_ensure_csrf_token`, `_get_request_user`, `_validation_response`.
  - `custom_request_validation_exception_handler` — стандартный FastAPI
    422 для не-блоговых путей, формат `{"errors": ...}` для `/api/blog/*`.
"""

import bcrypt
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from config_log import logF
from core.config import settings
from db_core.db_async import CurrentSession, db_manager
from md_articles.models import BlogUser


# ==============================================================================
# +++++++++++++++++++++++++++ current_user middleware +++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
async def inject_current_user_middleware(request: Request, call_next):
    """
    HTTP-middleware: подгружает current_user для каждого запроса.

    Что делает:
      Открывает короткую сессию БД через `db_manager.session_factory()`,
      вызывает `get_current_user(request, session)` — функция ниже,
      которая по `request.session['user_id']` достаёт `BlogUser` из БД,
      кладёт его в `request.state.current_user`.

    Почему middleware, а не dependency:
      `request.state.current_user` нужен **всем** обработчикам блога и `/api/blog/articles`,
      и `/api/blog/current_user` и желательно без явной зависимости в каждом `@router.get(...)`.
      Middleware гарантирует, что к моменту вызова роута
      `request.state.current_user` либо `None`, либо `BlogUser`.
      Это убирает повторяющийся `Depends(get_current_user)`.
    """
    async with db_manager.session_factory() as session:
        await get_current_user(request, session)
        response = await call_next(request)
    return response


async def get_current_user(request: Request, session: CurrentSession) -> BlogUser | None:
    """Получить пользователя из сессии и положить в request.state."""
    user_id = request.session.get("user_id")

    if user_id is None:
        request.state.current_user = None
        return None

    result = await session.execute(select(BlogUser).where(BlogUser.id == user_id))
    user = result.scalar_one_or_none()

    request.state.current_user = user
    return user


# ==============================================================================
# ++++++++++++++++++++++++++++ auth setup (точка входа) ++++++++++++++++++++++++
# ------------------------------------------------------------------------------
def auth_add_middleware(app: FastAPI) -> None:
    """
    Подключает всю авторизацию к FastAPI-приложению.

    Делает три вещи в строгом порядке:
      1. `app.add_middleware(BaseHTTPMiddleware, dispatch=inject_current_user_middleware)` —
         гарантирует `request.state.current_user` к моменту вызова любого обработчика блога.
         Должна быть добавлена **до** `SessionMiddleware` — Starlette вставляет middleware через
         `user_middleware.insert(0, ...)`, в `build_middleware_stack` стек оборачивается `reversed(...)`.
         Если добавить её после SessionMiddleware, она окажется **снаружи** сессии, и
         `request.session` в `get_current_user` бросит `AssertionError`.
      2. `app.add_middleware(SessionMiddleware, ...)` — cookie-сессии (`itsdangerous`-подпись).
         Без неё `request.session` бросит `AttributeError`.
         `secret_key` берётся из `settings.web`, `max_age` = 14 дней.
      3. `app.add_exception_handler(RequestValidationError, ...)` формат `{"errors": {...}}`
          для `/api/blog/*` (формы фронтенда), стандартный FastAPI-ответ для всего остального.
    """
    logF.info(
        "auth_add_middleware: inject_current_user_middleware + SessionMiddleware + RequestValidationError"
    )

    app.add_middleware(
        BaseHTTPMiddleware,
        dispatch=inject_current_user_middleware,
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.web.secret_key,
        max_age=14 * 24 * 3600,
    )

    app.add_exception_handler(
        RequestValidationError,
        custom_request_validation_exception_handler,
    )


async def custom_request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Формат {"errors": {field: [msgs]}} — только для /api/blog;
    для остальных путей — стандартный ответ FastAPI {"detail": [...]}.
    """
    if not request.url.path.startswith("/api/blog"):
        from fastapi.exception_handlers import request_validation_exception_handler

        return await request_validation_exception_handler(request, exc)
    errors: dict[str, list[str]] = {}
    for err in exc.errors():
        if err.get("type") == "json_invalid":
            errors.setdefault("body", []).append("Invalid JSON body.")
            continue
        field = ".".join(str(loc) for loc in err.get("loc", []) if loc != "body")
        errors.setdefault(field or "body", []).append(err.get("msg", "Invalid value."))
    return JSONResponse(status_code=422, content={"errors": errors})


# ==============================================================================
# +++++++++++++++++++++++++++++ auth helpers +++++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
def login_user(request: Request, user_id: int) -> None:
    request.session["user_id"] = user_id


def logout_user(request: Request) -> None:
    request.session.pop("user_id", None)


# ==============================================================================
# +++++++++++++++++++++++++++++ password helpers +++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ==============================================================================
# ++++++++++++++++++++++++++++++ CSRF helpers ++++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
def _ensure_csrf_token(request: Request) -> str:
    """Вернуть существующий CSRF-токен или создать новый в сессии."""
    token = request.session.get("csrf_token")
    if not token:
        import secrets

        token = secrets.token_hex(32)
        request.session["csrf_token"] = token
    return token


async def validate_csrf_form(request: Request) -> None:
    """CSRF для multipart /api/blog/account: поле формы csrf_token."""
    form = await request.form()
    session_token = request.session.get("csrf_token")
    form_token = form.get("csrf_token")
    if not session_token or not form_token or form_token != session_token:
        raise HTTPException(status_code=403, detail="CSRF token mismatch")


async def validate_csrf_header(request: Request) -> None:
    """CSRF для JSON POST-роутов: заголовок X-CSRF-Token против сессии."""
    header_token = request.headers.get("X-CSRF-Token")
    session_token = request.session.get("csrf_token")
    if not session_token or not header_token or header_token != session_token:
        raise HTTPException(status_code=403, detail="CSRF token mismatch")


# ==============================================================================
# +++++++++++++++++++++++++++++ login dependency +++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
def _get_request_user(request: Request) -> BlogUser | None:
    return getattr(request.state, "current_user", None)


async def require_login_api(request: Request) -> None:
    """Зависимость для API-роутов вместо редиректа — 403 JSON."""
    if _get_request_user(request) is None:
        raise HTTPException(status_code=403, detail="Authentication required")


# ==============================================================================
# ++++++++++++++++++++++++++++++ validation handler ++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
_ERROR_EMAIL_TAKEN = "That email is taken. Please choose a different one."
_ERROR_USERNAME_TAKEN = "That username is taken. Please choose a different one."


def _validation_response(errors: dict[str, list[str]]) -> JSONResponse:
    """Стандартный ответ 422 с errors для форм фронтенда."""
    return JSONResponse(status_code=422, content={"errors": errors})

"""
Middleware-слой авторизации блога `md_articles` —
точка входа `auth_add_middleware(app)` и его обвязка.

  - `auth_add_middleware(app)` — подключает `SessionMiddleware`,
    HTTP-middleware `inject_current_user_middleware` и обработчик
    `RequestValidationError` (`{"errors": ...}` под формы фронтенда).
  - `inject_current_user_middleware` — кладёт `request.state.current_user`
    на каждый запрос через короткую сессию БД.
  - `get_current_user` — достаёт `BlogUser` из сессии и пишет в `request.state`.
  - `custom_request_validation_exception_handler` — стандартный FastAPI
    422 для не-блоговых путей, формат `{"errors": ...}` для `/api/blog/*`.

Хелперы сессии, паролей, CSRF, login-зависимости и validation handler
живут в `md_articles.helpers_auth`.
"""

from fastapi import FastAPI, Request
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
# +++++++++++++++++++++++++++ current_user middleware ++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
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


# ==============================================================================
# ++++++++++++++++++++++++++++ auth setup (точка входа) ++++++++++++++++++++++++
# ------------------------------------------------------------------------------
def add_middleware_auth(app: FastAPI) -> None:
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


# ==============================================================================
# +++++++++++++++++++++++++++ exception handler ++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
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

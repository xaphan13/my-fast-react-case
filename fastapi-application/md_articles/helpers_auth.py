import io
import os
from pathlib import Path

import bcrypt
from PIL import Image
from fastapi import (
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse
from sqlalchemy import select
from pydantic import EmailStr

from db_core.db_async import CurrentSession
from md_articles.models import BlogUser
from md_articles.schema_blog import UserOut


# ==============================================================================
# +++++++++++++++++++++++++++++ auth helpers +++++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
def user_out(user: BlogUser) -> UserOut:
    """BlogUser -> JSON-представление для фронтенда."""
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        image_file=user.image_file,
    )


def is_valid_email(email: str) -> bool:
    try:
        EmailStr._validate(email)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


async def username_exists(session: CurrentSession, username: str) -> bool:
    result = await session.execute(select(BlogUser).where(BlogUser.username == username))
    return result.scalar_one_or_none() is not None


async def email_exists(session: CurrentSession, email: str) -> bool:
    result = await session.execute(select(BlogUser).where(BlogUser.email == email))
    return result.scalar_one_or_none() is not None


async def save_picture(form_picture: UploadFile) -> str:
    """Ресайз до 125x125 и сохранение в static/profile_pics (логика 1:1)."""
    random_hex = os.urandom(8).hex()
    _, f_ext = os.path.splitext(form_picture.filename or "")
    f_ext = f_ext.lower()
    if f_ext not in {".jpg", ".jpeg", ".png"}:
        f_ext = ".jpg"
    picture_fn = random_hex + f_ext

    profile_pics_dir = (Path(__file__).parent / ".." / "static" / "profile_pics").resolve()
    profile_pics_dir.mkdir(parents=True, exist_ok=True)
    picture_path = profile_pics_dir / picture_fn

    output_size = (125, 125)
    content = await form_picture.read()
    try:
        i = Image.open(io.BytesIO(content))
        i.thumbnail(output_size)
        i.save(picture_path)
    except Exception as exc:
        raise ValueError("Загруженный файл не является изображением.") from exc

    return picture_fn


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
def ensure_csrf_token(request: Request) -> str:
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
def get_request_user(request: Request) -> BlogUser | None:
    return getattr(request.state, "current_user", None)


async def require_login_api(request: Request) -> None:
    """Зависимость для API-роутов вместо редиректа — 403 JSON."""
    if get_request_user(request) is None:
        raise HTTPException(status_code=403, detail="Authentication required")


# ==============================================================================
# ++++++++++++++++++++++++++++++ validation handler ++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
ERROR_EMAIL_TAKEN = "That email is taken. Please choose a different one."
ERROR_USERNAME_TAKEN = "That username is taken. Please choose a different one."


def validation_response(errors: dict[str, list[str]]) -> JSONResponse:
    """Стандартный ответ 422 с errors для форм фронтенда."""
    return JSONResponse(status_code=422, content={"errors": errors})

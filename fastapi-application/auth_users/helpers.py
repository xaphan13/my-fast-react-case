"""
Вспомогательные функции для слоя авторизации fastapi-users.

Перенесено из md_articles/helpers_auth.py (фаза 1 — пока используется параллельно
со старой моделью BlogUser; полный переход на User будет в фазах 3–5).

Содержит только то, что нужно для register-flow: проверка email,
проверка уникальности username/email, ресайз аватара, стандартный
422-ответ с ошибками для формы регистрации.
"""

import io
import os
from pathlib import Path

from fastapi import UploadFile
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import EmailStr
from sqlalchemy import select

from auth_users.models import User
from base_dir_path import BASE_DIR
from db_core.db_async import CurrentSession


# ==============================================================================
# +++++++++++++++++++++++++++++ auth helpers +++++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
def is_valid_email(email: str) -> bool:
    try:
        EmailStr._validate(email)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


async def username_exists(session: CurrentSession, username: str) -> bool:
    """SELECT 1 FROM user WHERE username = ?."""
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none() is not None


async def email_exists(session: CurrentSession, email: str) -> bool:
    """SELECT 1 FROM user WHERE email = ?."""
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none() is not None


async def save_picture(form_picture: UploadFile) -> str:
    """Ресайз аватара до 125x125 и сохранение в static/profile_pics/.

    Логика 1:1 с md_articles/helpers_auth.py::save_picture, но путь выражен
    через BASE_DIR (источник истины для файловой раскладки проекта).
    """
    random_hex = os.urandom(8).hex()
    _, f_ext = os.path.splitext(form_picture.filename or "")
    f_ext = f_ext.lower()
    if f_ext not in {".jpg", ".jpeg", ".png"}:
        f_ext = ".jpg"
    picture_fn = random_hex + f_ext

    profile_pics_dir = (BASE_DIR / "static" / "profile_pics").resolve()
    profile_pics_dir.mkdir(parents=True, exist_ok=True)
    picture_path = Path(profile_pics_dir) / picture_fn

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
# ++++++++++++++++++++++++++++++ validation handler ++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
ERROR_EMAIL_TAKEN = "That email is taken. Please choose a different one."
ERROR_USERNAME_TAKEN = "That username is taken. Please choose a different one."


def validation_response(errors: dict[str, list[str]]) -> JSONResponse:
    """Стандартный ответ 422 с errors для форм фронтенда."""
    return JSONResponse(status_code=422, content={"errors": errors})

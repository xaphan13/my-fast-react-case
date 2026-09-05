# ==============================================================================
# ++++++++++++++++++++++++++ helpers blog ++++++++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
"""
Предметные хелперы блог-API: формирование user-DTO, валидация форм
register/login/account, реестр статей, аватарки профиля.
"""
import io
import os
import time
from pathlib import Path

from PIL import Image
from fastapi import UploadFile
from sqlalchemy import select

from db_core.db_async import CurrentSession
from md_articles.models import BlogUser
from md_articles.schema_art import ArticleLang
from md_articles.schema_blog import UserOut


# ==============================================================================
# ++++++++++++++++++++++++++++++++ helpers +++++++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
def _user_out(user: BlogUser) -> UserOut:
    """BlogUser -> JSON-представление для фронтенда."""
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        image_file=f"/static/profile_pics/{user.image_file}",
    )


def _is_valid_email(email: str) -> bool:
    try:
        from pydantic import EmailStr

        EmailStr._validate(email)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


async def _username_exists(session: CurrentSession, username: str) -> bool:
    result = await session.execute(select(BlogUser).where(BlogUser.username == username))
    return result.scalar_one_or_none() is not None


async def _email_exists(session: CurrentSession, email: str) -> bool:
    result = await session.execute(select(BlogUser).where(BlogUser.email == email))
    return result.scalar_one_or_none() is not None


def _is_complete(art: ArticleLang) -> bool:
    return bool(art.author.strip() and art.lang.strip() and art.title.strip())


def _allocate_art_id(existing_ids: set[int]) -> int:
    new_id = int(time.time())
    while new_id in existing_ids:
        new_id += 1
    return new_id


async def _save_picture(form_picture: UploadFile) -> str:
    """Ресайз до 125x125 и сохранение в static/profile_pics (логика 1:1)."""
    random_hex = os.urandom(8).hex()
    _, f_ext = os.path.splitext(form_picture.filename or "")
    f_ext = f_ext.lower()
    if f_ext not in {".jpg", ".jpeg", ".png"}:
        f_ext = ".jpg"
    picture_fn = random_hex + f_ext

    profile_pics_dir = os.path.join(os.path.dirname(__file__), "..", "static", "profile_pics")
    profile_pics_dir = os.path.abspath(profile_pics_dir)
    os.makedirs(profile_pics_dir, exist_ok=True)
    picture_path = os.path.join(profile_pics_dir, picture_fn)

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
# +++++++++++++++++++++++++++++ articles API +++++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
def _article_summary(art: ArticleLang, disk_files: set[str] | None = None) -> dict:
    data = art.model_dump(exclude={"content"})
    data["complete"] = _is_complete(art)
    if disk_files is not None:
        data["file_exists"] = art.file_name in disk_files
    return data
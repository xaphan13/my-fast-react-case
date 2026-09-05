# ==============================================================================
# ++++++++++++++++++++++++++++++++ api_blog ++++++++++++++++++++++++++++++++++++
# ------------- JSON API блога под React SPA (префикс /api/blog) ---------------
# ------------------------------------------------------------------------------
import io
import os
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from PIL import Image
from sqlalchemy import select

from config_log import logF
from db_core.db_async import CurrentSession
from md_articles.auth_middleware_helpers import (
    _ERROR_EMAIL_TAKEN,
    _ERROR_USERNAME_TAKEN,
    _ensure_csrf_token,
    _get_request_user,
    _validation_response,
    hash_password,
    login_user,
    logout_user,
    require_login_api,
    validate_csrf_form,
    validate_csrf_header,
    verify_password,
)
from md_articles.models import BlogUser
from md_articles.schema_art import (
    ArticleLang,
    get_art,
    get_articles,
    get_registry_error,
    get_section,
    render_article,
    save_articles,
    scan_content_art,
    sync_registry_with_disk,
)
from md_articles.schema_blog import LoginIn, MetaIn, RegisterIn, SectionOut, UserOut


router_blog_api = APIRouter(
    prefix="/api/blog",
    tags=["blog api"],
)


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
# ++++++++++++++++++++++++++++++++ auth API ++++++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
@router_blog_api.get("/csrf", name="blog_api.csrf")
async def csrf_token(request: Request):
    token = _ensure_csrf_token(request)
    return {"csrf_token": token}


@router_blog_api.get("/current_user", name="blog_api.current_user")
async def current_user(request: Request):
    user = _get_request_user(request)
    if user is None:
        return {"user": None}
    return {"user": _user_out(user).model_dump()}


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
        errors.setdefault("username", []).append("Field must be between 2 and 20 characters long.")

    if not email:
        errors.setdefault("email", []).append("This field is required.")
    elif not _is_valid_email(email):
        errors.setdefault("email", []).append("Invalid email address.")

    if not payload.password:
        errors.setdefault("password", []).append("This field is required.")

    if not payload.confirm_password:
        errors.setdefault("confirm_password", []).append("This field is required.")
    elif payload.confirm_password != payload.password:
        errors.setdefault("confirm_password", []).append("Fields must match.")

    if username and not errors.get("username") and await _username_exists(session, username):
        errors.setdefault("username", []).append(_ERROR_USERNAME_TAKEN)

    if email and not errors.get("email") and await _email_exists(session, email):
        errors.setdefault("email", []).append(_ERROR_EMAIL_TAKEN)

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


@router_blog_api.post("/logout", name="blog_api.logout")
async def logout_api(request: Request):
    await validate_csrf_header(request)
    logout_user(request)
    return {"message": "You have been logged out", "category": "success"}


# ==============================================================================
# +++++++++++++++++++++++++++++ account API ++++++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
@router_blog_api.get("/account", name="blog_api.account_get")
async def account_get_api(request: Request, _user=Depends(require_login_api)):
    return {"user": _user_out(_get_request_user(request)).model_dump()}


@router_blog_api.post("/account", name="blog_api.account_post")
async def account_post_api(
    request: Request,
    session: CurrentSession,
    _user=Depends(require_login_api),
    username: str = Form(""),
    email: str = Form(""),
    picture: UploadFile | None = File(None),
    csrf_token_field: str = Form("", alias="csrf_token"),
):
    await validate_csrf_form(request)
    current_user = _get_request_user(request)

    errors: dict[str, list[str]] = {}
    username = username.strip()
    email = email.strip()

    if not username:
        errors.setdefault("username", []).append("This field is required.")
    elif len(username) < 2 or len(username) > 20:
        errors.setdefault("username", []).append("Field must be between 2 and 20 characters long.")

    if not email:
        errors.setdefault("email", []).append("This field is required.")
    elif not _is_valid_email(email):
        errors.setdefault("email", []).append("Invalid email address.")

    if username != current_user.username and await _username_exists(session, username):
        errors.setdefault("username", []).append(_ERROR_USERNAME_TAKEN)

    if email != current_user.email and await _email_exists(session, email):
        errors.setdefault("email", []).append(_ERROR_EMAIL_TAKEN)

    if errors:
        return _validation_response(errors)

    if picture and picture.filename:
        try:
            picture_file = await _save_picture(picture)
        except ValueError as exc:
            return _validation_response({"picture": [str(exc)]})
        current_user.image_file = picture_file

    current_user.username = username
    current_user.email = email
    await session.commit()

    return {
        "message": "Your account has been updated!",
        "category": "success",
        "user": _user_out(current_user).model_dump(),
    }


# ==============================================================================
# +++++++++++++++++++++++++++++ sections API ++++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
@router_blog_api.get("/sections", name="blog_api.sections")
async def sections_list():
    """Список непустых разделов с количеством полных статей, по имени."""
    counts: dict[str, int] = {}
    for art in get_articles():
        if art.section and _is_complete(art):
            counts[art.section] = counts.get(art.section, 0) + 1

    sections = [
        SectionOut(name=name, label=name, count=count) for name, count in sorted(counts.items())
    ]
    return {"sections": jsonable_encoder(sections)}


# ==============================================================================
# +++++++++++++++++++++++++++++ articles API +++++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
def _article_summary(art: ArticleLang, disk_files: set[str] | None = None) -> dict:
    data = art.model_dump(exclude={"content"})
    data["complete"] = _is_complete(art)
    if disk_files is not None:
        data["file_exists"] = art.file_name in disk_files
    return data


@router_blog_api.get("/articles", name="blog_api.articles")
async def articles_list(section: str | None = Query(default=None)):
    """Список полных статей; при section — только статьи с этим разделом."""
    articles = get_articles()
    result = [
        _article_summary(art)
        for art in articles
        if _is_complete(art) and (section is None or art.section == section)
    ]
    return {"articles": jsonable_encoder(result)}


@router_blog_api.get("/articles/{art_id}", name="blog_api.article_detail")
async def article_detail(art_id: int):
    art = get_art(art_id)
    if art is None:
        raise HTTPException(status_code=404, detail="Article not found")

    if not _is_complete(art):
        raise HTTPException(status_code=404, detail="Article not found")

    import os
    from md_articles.schema_art import get_path_dir

    content_dir = get_path_dir()
    if not os.path.exists(content_dir / art.file_name):
        raise HTTPException(status_code=404, detail="Article not found")

    content = render_article(art.file_name, content_dir)
    article = art.model_copy(update={"content": content})
    return {"article": jsonable_encoder(article.model_dump())}


# ==============================================================================
# ++++++++++++++++++++++++++++ art_manage API ++++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
@router_blog_api.get("/art_manage", name="blog_api.art_manage")
async def art_manage_api(request: Request, _user=Depends(require_login_api)):
    articles = get_articles()
    disk_files = set(scan_content_art())
    registered_files = {art.file_name for art in articles}

    unassigned_files = [name for name in scan_content_art() if name not in registered_files]

    articles_context = [_article_summary(art, disk_files) for art in articles]

    missing_entries = [
        data for data, art in zip(articles_context, articles) if art.file_name not in disk_files
    ]

    return {
        "articles": articles_context,
        "unassigned_files": unassigned_files,
        "missing_entries": missing_entries,
        "yaml_error": get_registry_error(),
    }


@router_blog_api.post("/art_manage/add_all", name="blog_api.art_manage_add_all")
async def art_manage_add_all_api(request: Request, _user=Depends(require_login_api)):
    await validate_csrf_header(request)

    disk_files = set(scan_content_art())
    articles = list(get_articles())
    registered_files = {art.file_name for art in articles}

    new_files = [name for name in sorted(disk_files) if name not in registered_files]
    if not new_files:
        return {"message": "Нет новых файлов для добавления", "category": "info"}

    existing_ids = {art.art_id for art in articles}
    added = 0
    for file_name in new_files:
        title = Path(file_name).stem
        new_id = _allocate_art_id(existing_ids)
        existing_ids.add(new_id)
        articles.append(
            ArticleLang(
                art_id=new_id,
                file_name=file_name,
                title=title,
                author="NoName",
                lang=get_section(file_name),
            )
        )
        added += 1

    save_articles(articles)
    return {"message": f"Добавлено файлов: {added}", "category": "success"}


@router_blog_api.post("/art_manage/meta", name="blog_api.art_manage_meta")
async def art_manage_meta_api(
    request: Request,
    payload: MetaIn,
    _user=Depends(require_login_api),
):
    await validate_csrf_header(request)

    file_name = payload.file_name.strip()
    author = payload.author.strip()
    lang = payload.lang.strip()
    title = payload.title.strip()

    disk_files = set(scan_content_art())
    articles = list(get_articles())
    registry_by_file = {art.file_name: art for art in articles}

    if file_name not in disk_files and file_name not in registry_by_file:
        return JSONResponse(
            status_code=422,
            content={"errors": {"file_name": [f"Недопустимое имя файла: {file_name}"]}},
        )

    existing_ids = {art.art_id for art in articles}

    if file_name in registry_by_file:
        existing_section = registry_by_file[file_name].section
        articles = [
            art.model_copy(
                update={"author": author, "lang": lang, "title": title, "section": existing_section}
            )
            if art.file_name == file_name
            else art
            for art in articles
        ]
        action_word = "Обновлена"
    else:
        new_id = _allocate_art_id(existing_ids)
        if not title:
            title = os.path.splitext(file_name)[0]
        articles.append(
            ArticleLang(
                art_id=new_id,
                file_name=file_name,
                title=title,
                author=author,
                lang=lang,
                section=get_section(file_name),
            )
        )
        action_word = "Добавлена"

    save_articles(articles)
    return {"message": f"{action_word} запись для {file_name}", "category": "success"}


@router_blog_api.post("/art_manage/sync", name="blog_api.art_manage_sync")
async def art_manage_sync_api(request: Request, _user=Depends(require_login_api)):
    """
    Синхронизировать реестр articles.yaml с файлами на диске.

    Удаляет записи из реестра, для которых нет соответствующих .md файлов.
    """
    await validate_csrf_header(request)

    removed, total = sync_registry_with_disk()
    if removed > 0:
        return {
            "message": f"Удалено сиротских записей: {removed}. Всего статей: {total}",
            "category": "success",
        }
    return {"message": "Синхронизация не требуется — сиротских записей нет", "category": "info"}

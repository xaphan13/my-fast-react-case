import os
from pathlib import Path
import time

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from md_articles.helpers_auth import (
    require_login_api,
    validate_csrf_header,
)
from md_articles.schema_art import (
    get_art,
    get_articles,
    get_registry_error,
    get_section,
    render_article,
    save_articles,
    scan_content_art,
    sync_registry_with_disk,
)
from md_articles.schema_art import ArticleLang
from md_articles.schema_blog import MetaIn, SectionOut


router_blog_api = APIRouter(
    prefix="/api/blog",
    tags=["blog api"],
)


# ==============================================================================
# ++++++++++++++++++++++++++++++ art helpers +++++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
def _is_complete(art: ArticleLang) -> bool:
    return bool(art.author.strip() and art.lang.strip() and art.title.strip())


def _allocate_art_id(existing_ids: set[int]) -> int:
    new_id = int(time.time())
    while new_id in existing_ids:
        new_id += 1
    return new_id


def _article_summary(art: ArticleLang, disk_files: set[str] | None = None) -> dict:
    data = art.model_dump(exclude={"content"})
    data["complete"] = _is_complete(art)
    if disk_files is not None:
        data["file_exists"] = art.file_name in disk_files
    return data


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

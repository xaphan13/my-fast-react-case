import os
import tempfile
from pathlib import Path, PurePosixPath

import yaml
from markdown import markdown
from pydantic import BaseModel, model_validator

from base_dir_path import BASE_DIR
from config_log import logF


# ==============================================================================
# ++++++++++++++++++ BaseModel - ArticleLang - pydantic ++++++++++++++++++++++++
# ------------------------ open files with content -----------------------------
# ------------------------------------------------------------------------------
class ArticleLang(BaseModel):
    author: str = "author"
    lang: str
    art_id: int
    title: str
    file_name: str = ""
    content: str = ""
    section: str = ""

    @model_validator(mode="before")
    @classmethod
    def _autofill_section(cls, data: object) -> object:
        """Если section не задан, вычислить его как первую папку file_name.

        Для статей из корня content_art/ остаётся пустая строка.
        """
        if not isinstance(data, dict):
            return data
        if "section" not in data or data["section"] in (None, ""):
            file_name = data.get("file_name") or ""
            data["section"] = get_section(file_name)
        return data


# ------------------------------------------------------------------------
def get_path_dir() -> Path:
    """Каталог с .md-файлами статей (привязан к BASE_DIR, не к cwd)."""
    return BASE_DIR / "content_art"


def read_html(name_html: str, name_dir: Path | None = None) -> str:
    if name_dir is None:
        name_dir = get_path_dir()
    path_html = name_dir / name_html
    logF.info(f"read_html : \n{name_dir}")

    with open(path_html, "r", encoding="utf8") as file:
        all_file: str = file.read()
    return all_file


def render_article(name_file: str, name_dir: Path | None = None) -> str:
    content = read_html(name_file, name_dir)
    file_extension = os.path.splitext(name_file)[1].lower()

    if file_extension in {".md", ".markdown"}:
        return markdown(content, extensions=["fenced_code", "tables"])

    return content


# ------------------------------ registry with mtime cache
articles_path = Path(__file__).with_name("articles.yaml")

_registry_cache: list[ArticleLang] = []
_registry_error: str | None = None
_last_stat: tuple[int, int] | None = None

_FIELDS_FOR_YAML = {"author", "lang", "art_id", "title", "file_name", "section"}


def _load_registry() -> list[ArticleLang]:
    """Read articles.yaml from disk and return list of ArticleLang."""
    with articles_path.open("r", encoding="utf8") as articles_file:
        articles_data = yaml.safe_load(articles_file)

    if not isinstance(articles_data, dict) or "articles" not in articles_data:
        raise ValueError("articles.yaml: expected top-level key 'articles'")

    return [ArticleLang(**article) for article in articles_data["articles"]]


def get_articles() -> list[ArticleLang]:
    """Return current registry, reloading from disk if yaml changed."""
    global _registry_cache, _registry_error, _last_stat

    try:
        stat = articles_path.stat()
        current_key = (stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        logF.error(f"articles.yaml not found: {articles_path}")
        _registry_error = "Файл реестра articles.yaml не найден"
        return _registry_cache
    except OSError as exc:
        logF.error(f"Cannot stat articles.yaml: {exc}")
        _registry_error = f"Ошибка доступа к реестру: {exc}"
        return _registry_cache

    if _last_stat == current_key:
        return _registry_cache

    try:
        _registry_cache = _load_registry()
        _registry_error = None
        _last_stat = current_key
        logF.info(f"articles.yaml reloaded: {len(_registry_cache)} entries")
    except (OSError, yaml.YAMLError, ValueError, TypeError, KeyError) as exc:
        logF.error(f"Failed to parse articles.yaml: {exc}")
        _registry_error = f"Ошибка чтения articles.yaml: {exc}"
        # Keep previous working state; force reload on next call by clearing stat.
        _last_stat = None

    return _registry_cache


def get_art(art_id: int) -> ArticleLang | None:
    """Return article by id or None."""
    for art in get_articles():
        if art.art_id == art_id:
            return art
    return None


def get_registry_error() -> str | None:
    """Return last yaml loading error, if any."""
    get_articles()  # ensure error state is fresh
    return _registry_error


def save_articles(articles: list[ArticleLang]) -> None:
    """Atomically write articles list back to articles.yaml."""
    data = {
        "articles": [
            art.model_dump(include=_FIELDS_FOR_YAML, exclude_unset=False) for art in articles
        ]
    }

    # Write to a temp file in the same directory, then atomically replace.
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=articles_path.parent,
        prefix=".articles_",
        suffix=".yaml.tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf8") as tmp_file:
            yaml.safe_dump(
                data,
                tmp_file,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
        os.replace(tmp_path, articles_path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    # Invalidate cached stat so next get_articles() re-reads from disk.
    global _last_stat
    _last_stat = None
    logF.info(f"articles.yaml saved: {len(articles)} entries")


def get_section(file_name: str) -> str:
    """Вернуть имя раздела (первая компонента пути) или '' для корня.

    Раздел = имя первой папки в пути; для файла из корня content_art/
    возвращается ''.
    """
    parts = PurePosixPath(file_name).parts
    return parts[0] if len(parts) > 1 else ""


def scan_content_art() -> list[str]:
    """Вернуть отсортированный список относительных POSIX-путей .md/.markdown
    файлов в content_art/. Первый уровень подпапок = раздел статьи.
    """
    content_dir = get_path_dir()
    if not content_dir.exists():
        return []

    files: list[str] = []
    for entry in content_dir.rglob("*"):
        if entry.is_file() and entry.suffix.lower() in {".md", ".markdown"}:
            files.append(entry.relative_to(content_dir).as_posix())
    return sorted(files)


def sync_registry_with_disk() -> tuple[int, int]:
    """
    Синхронизировать реестр articles.yaml с файлами на диске.

    Удаляет записи из реестра, для которых нет соответствующих файлов.
    Возвращает кортеж (удалено, всего_после_синхронизации).
    """
    articles = list(get_articles())
    disk_files = set(scan_content_art())

    # Оставить только те статьи, у которых файл существует на диске
    original_count = len(articles)
    articles = [art for art in articles if art.file_name in disk_files]
    removed_count = original_count - len(articles)

    if removed_count > 0:
        save_articles(articles)
        logF.info(f"sync_registry_with_disk: удалено {removed_count} сиротских записей")

    return removed_count, len(articles)

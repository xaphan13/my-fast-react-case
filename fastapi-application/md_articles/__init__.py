"""
Пакет блога `md_articles`.

  - `frontend_auth_include.py` — публичный API подключения:
    `setup_auth_static_include(app)` (вызывается из `main.py`).
  - `auth_middleware_helpers.py` — вся авторизация в одном файле:
    `auth_add_middleware`, `inject_current_user_middleware`, CSRF,
    `require_login_api`, сессионные и парольные хелперы, exception
    handler для `RequestValidationError`.
  - `api_blog.py` — JSON-роутер `/api/blog/*` (13 эндпоинтов) для
    React SPA: csrf, current_user, register/login/logout, account,
    sections, articles, art_manage. Здесь же живут `UserOut` и
    `_user_out` — формат JSON-ответа авторизации/аккаунта.
  - `schema_art.py` — pydantic-модель `ArticleLang` + YAML-реестр
    статей с mtime-кэшем и атомарной записью.
  - `models.py` — SQLAlchemy-модели `BlogUser`, `BlogPost`.
"""

from md_articles.frontend_auth_include import setup_auth_static_include

__all__ = ["setup_auth_static_include"]

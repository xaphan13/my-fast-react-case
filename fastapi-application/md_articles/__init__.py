"""
Пакет блога `md_articles`.

  - `setup_frontend.py` — публичный API подключения:
    `setup_auth_static_include(app)` (вызывается из `main.py`).
  - `middleware_auth.py` — middleware-слой авторизации:
    `auth_add_middleware`, `inject_current_user_middleware`,
    `custom_request_validation_exception_handler`, `get_current_user`.
  - `helpers_auth.py` — бизнес-хелперы авторизации и блога:
    сессионные и парольные функции, CSRF, `require_login_api`,
    `user_out`, `UserOut`, JSON-формат ответа.
  - `api_auth.py` — JSON-роутер `/api/blog/auth/*` (7 эндпоинтов):
    csrf, current_user, register, login, logout, account (GET/POST).
  - `api_blog.py` — JSON-роутер `/api/blog/*` (7 эндпоинтов) для
    React SPA: sections, articles, articles/{id}, art_manage,
    add_all, meta. Здесь же живут `UserOut` и `user_out` —
    формат JSON-ответа авторизации/аккаунта.
  - `schema_art.py` — pydantic-модель `ArticleLang` + YAML-реестр
    статей с mtime-кэшем и атомарной записью.
  - `models.py` — SQLAlchemy-модели `BlogUser`, `BlogPost`.
"""

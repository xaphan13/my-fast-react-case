# Phase 1 — api_auth.py создан

## Шаг 3: api_auth.py создан

- Создан `fastapi-application/md_articles/api_auth.py` одним `write_file`.
- `router_auth = APIRouter(prefix="/api/blog", tags=["auth"])`.
- 7 auth-роутов скопированы 1:1 из `api_blog.py` (строки 64–244),
  `@router_blog_api.` → `@router_auth.`, `name="blog_api.*"` → `name="auth.*"`.
- Импорт-блок по контракту, `Annotated` не понадобился (не используется в api_blog.py).
- `router_auth` пока никуда не подключён (фаза 2).

## Импорты — отличия от стартового списка

Сверх стартового списка ничего не добавлено, ничего не убавлено: все 11 имён
из `auth_middleware_helpers`, 5 имён из `helpers_blog` (`_user_out`,
`_is_valid_email`, `_username_exists`, `_email_exists`, `_save_picture`),
`BlogUser`, `LoginIn`, `RegisterIn`, fastapi/sqlalchemy/db_core/config_log —
ровно те, что используются в auth-роутах `api_blog.py`.

## Checkpoint-результаты

1. `from md_articles.api_auth import router_auth; print(len(router_auth.routes))` → `7` (PASS)
2. `print(sorted([r.name for r in router_auth.routes if r.name]))` →
   `['auth.account_get', 'auth.account_post', 'auth.csrf', 'auth.current_user', 'auth.login', 'auth.logout', 'auth.register']` (PASS)
3. `from main import main_app; print(len(main_app.routes))` → `42` (PASS — `router_auth` не подключён)
4. `uv run ruff check fastapi-application/md_articles/api_auth.py` → `All checks passed!` (PASS)

Все checkpoint зелёные — фаза 1 готова к сдаче.
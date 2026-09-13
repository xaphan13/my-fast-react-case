"""
Пакет блога md_articles — JSON API для React SPA, серверный Markdown-рендер,
реестр статей и HTML-разметка.

Состав:
  - api_blog.py          — роутер /api/blog/* (articles, sections, art_manage_*)
  - setup_frontend.py    — include_router_api_frontend / mount_vite_react_assets
  - schema_art, schema_blog, models, render_markdown — данные блога

Авторизация вынесена в отдельный пакет `auth_users/` (см. auth_users.router):
JWT-in-cookie через fastapi-users. art-роуты используют `Depends(active_user)`
из auth_users; SessionMiddleware, самописный CSRF и helpers удалены.
"""

from md_articles.setup_frontend import include_router_api_frontend, mount_vite_react_assets

__all__ = ["include_router_api_frontend", "mount_vite_react_assets"]

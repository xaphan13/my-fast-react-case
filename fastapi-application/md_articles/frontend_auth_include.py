"""
Подключение блога `md_articles` к FastAPI как plug-in.

`setup_auth_static_include(app)` — единственная точка входа уровня пакета:

  1. `auth_add_middleware(app)` — middleware сессий, current_user, exception
     handler 422 (вся авторизация собрана в `middleware_auth.py`).
  2. `app.mount("/static", StaticFiles(...))` — аватары из
     `BASE_DIR/static/profile_pics/`. `check_dir=False` — приложение
     стартует и без каталога (см. `frontend_routing.py`, аналогичный приём).
  3. `app.include_router(router_blog_api)` — JSON-роутер `/api/blog/*`.

Вызывается из `main.py` после доменных `include_router` и до
`setup_react_routing_assets(main_app)`.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from base_dir_path import BASE_DIR
from config_log import logF
from md_articles.api_auth import router_auth
from md_articles.api_blog import router_blog_api
from md_articles.middleware_auth import auth_add_middleware


def setup_auth_static_include(app: FastAPI) -> None:
    """Подключает блог к FastAPI: авторизация, статика, JSON-роутер."""
    logF.info("setup_auth_static_include: подключение auth, /static, router_blog_api")

    auth_add_middleware(app)

    app.mount(
        "/static",
        StaticFiles(directory=BASE_DIR / "static", check_dir=False),
        name="static",
    )

    app.include_router(router_auth)
    app.include_router(router_blog_api)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from base_dir_path import BASE_DIR
from config_log import logF
from md_articles.api_auth import router_auth_api
from md_articles.api_blog import router_blog_api
from md_articles.middleware_auth import add_middleware_auth


def include_router_api_frontend(app: FastAPI) -> None:
    """
    Подключение блога `md_articles` к FastAPI как plug-in.

      1. `add_middleware_auth(app)` — middleware сессий, current_user, exception
         handler 422 (вся авторизация собрана в `middleware_auth.py`).
      2. `app.mount("/static", StaticFiles(...))` — аватары из
         `BASE_DIR/static/profile_pics/`.
      3. `app.include_router(router_auth_api)` — JSON-роутер auth `/api/blog/*`.
         `app.include_router(router_blog_api)` — JSON-роутер blog `/api/blog/*`.
    """

    logF.info("setup_auth_static_include: подключение auth, /static, router_blog_api")

    add_middleware_auth(app)

    app.mount(
        "/static",
        StaticFiles(directory=BASE_DIR / "static", check_dir=False),
        name="static",
    )

    app.include_router(router_auth_api)
    app.include_router(router_blog_api)

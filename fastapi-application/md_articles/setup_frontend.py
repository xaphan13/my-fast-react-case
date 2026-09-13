from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

from base_dir_path import BASE_DIR
from config_log import logF
from md_articles.api_blog import router_blog_api


# ==============================================================================
# ++++++++++++++++ include_router & static для блога / auth_users +++++++++++++
# ------------------------------------------------------------------------------
def include_router_api_frontend(
    app: FastAPI, auth_users_router=None
) -> None:
    """
    Подключает блог `md_articles` и пакет авторизации `auth_users`.

      1. `app.mount("/static", StaticFiles(...))` — аватары из
         `BASE_DIR/static/profile_pics/`.
      2. `app.include_router(auth_users_router)` — авторизация
         fastapi-users: `/auth/jwt/{login,logout}`, `/auth/register`,
         `/auth/account`, `/users/me`, `/users/{id}`.
         Параметр передаётся из main.py (НЕ импортируется здесь),
         чтобы разорвать цикл импортов:
         setup_frontend → api_blog → auth_users.active_user → ...
         → auth_users.models → db_core.model_base → db_core/__init__
         → md_articles → setup_frontend → auth_users (partially loaded)
      3. `app.include_router(router_blog_api)` — JSON-роутер блога
         `/api/blog/*` (articles/sections/art_manage_*). Авторизация art-роутов
         теперь через `Depends(active_user)` из `auth_users`.
    """
    logF.info("include_router_api_frontend: подключение auth_users, /static, router_*")

    app.mount(
        "/static",
        StaticFiles(directory=BASE_DIR / "static", check_dir=False),
        name="static",
    )

    if auth_users_router is not None:
        app.include_router(auth_users_router)
    app.include_router(router_blog_api)


# ==============================================================================
# ++++++++++++++++++++ mount assets & router index.html ++++++++++++++++++++++++
# ------------------------------------------------------------------------------
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
ASSETS_DIR = FRONTEND_DIST / "assets"
INDEX_HTML = FRONTEND_DIST / "index.html"


async def spa_fallback(request: Request) -> FileResponse | JSONResponse:
    """
    Catch-all обработчик для client-side роутинга React Router.

    На «глубокую» ссылку (/section/Rust, /art/Max/123) или F5 на /account
    сервер обязан вернуть index.html — React Router уже на клиенте разберёт,
    какую «страницу» показать.

    `/api*` возвращает JSON 404, чтобы клиент не получал HTML вместо JSON.
    Если фронт не собран (нет index.html) — JSON 404 с подсказкой `npm run build`.
    """
    path = request.url.path
    if path == "/api" or path.startswith("/api/"):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    if not INDEX_HTML.is_file():
        logF.warning(
            "SPA: frontend/dist/index.html не найден — "
            "соберите фронт командой 'cd frontend && npm run build'"
        )
        return JSONResponse(
            status_code=404,
            content={
                "detail": "Frontend не собран: выполните npm run build в frontend/",
            },
        )

    return FileResponse(INDEX_HTML)


def mount_vite_react_assets(app: FastAPI) -> None:
    """
    Подключает раздачу собранного React-приложения к FastAPI.

    Вызывается из main.py СТРОГО после всех include_router,
    чтобы catch-all попал в конец router.routes.

    Делает три вещи:
      1) app.mount('/assets', StaticFiles(frontend/dist/assets, check_dir=False))
         — отдаёт хэшированные бандлы Vite с корректными MIME и долгим кэшем.
         check_dir=False позволяет стартовать приложение даже без собранного
         фронта (например, пока фронт ещё в разработке).
      2) app.router.routes.append(Route('/{full_path:path}', spa_fallback))
         — catch-all для client-side routing (CSR). Дописан РУКАМИ в router.routes
         после всех include_router/mount, чтобы гарантировать позицию маршрута
         в самом конце списка и не перехватить ни один API-роут.
      3) spa_fallback: GET → index.html (history-mode React Router);
         /api* — JSONResponse 404, чтобы клиент не получал HTML вместо JSON.

    Подробное объяснение каждой детали в docs/13_frontend_spa_module.md.
    Архитектурное сравнение способов подключения в docs/12_fastapi_react_integration.md.

    Допустимо вызвать один раз за время жизни приложения. Повторный вызов
    приведёт к двойному mount('/assets') и двойному catch-all.
    """
    app.mount(
        "/assets",
        StaticFiles(directory=ASSETS_DIR, check_dir=False),
        name="spa_assets",
    )

    app.router.routes.append(Route("/{full_path:path}", spa_fallback, methods=["GET"]))

    logF.info(f"SPA подключена: index={INDEX_HTML}, assets={ASSETS_DIR}")

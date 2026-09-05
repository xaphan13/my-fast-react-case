"""
Подключение собранного React-приложения (SPA) к FastAPI.
Этот модуль — единственная точка, в которой FastAPI узнаёт про фронтенд.

Что именно делает setup_react_routing_assets(app):
  1) app.mount('/assets', StaticFiles(frontend/dist/assets, check_dir=False))
     — отдаёт хэшированные бандлы Vite с корректными MIME и долгим кэшем.
     check_dir=False позволяет стартовать приложение даже без собранного
     фронта (например, пока фронт ещё в разработке): mount не упадёт на
     импорте, а в рантайме запросы к /assets просто вернут 404.
  2) app.router.routes.append(Route('/{full_path:path}', spa_fallback))
     — catch-all для client-side routing. Дописан РУКАМИ в router.routes
     после всех include_router/mount, чтобы гарантировать позицию маршрута
     в самом конце списка и не перехватить ни один API-роут.
  3) spa_fallback: GET → index.html (history-mode React Router);
     /api* — JSONResponse 404, чтобы клиент не получал HTML вместо JSON
     на несуществующий API-путь (иначе fetch упадёт с SyntaxError).

Подробное объяснение каждой детали и пошаговая трассировка запросов
в docs/13_frontend_spa_module.md.
Архитектурное сравнение способов подключения
в docs/12_fastapi_react_integration.md.
"""

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

from base_dir_path import BASE_DIR
from config_log import logF

# ── пути к собранному фронту ──────────────────────────────────────────────────
# BASE_DIR указывает на fastapi-application/. Корень репозитория — его родитель.
# Vite по умолчанию кладёт сборку в frontend/dist, а все
# хэшированные ассеты (JS/CSS с content-hash в имени) — в frontend/dist/assets.
#
# Важно: dist/ живёт ЗА пределами fastapi-application/, потому что фронт и
# бэкенд — два независимых пакета в монорепо. Если когда-нибудь захочется
# собирать фронт в fastapi-application/static/dist, менять нужно только здесь.

FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
ASSETS_DIR = FRONTEND_DIST / "assets"
INDEX_HTML = FRONTEND_DIST / "index.html"


async def spa_fallback(request: Request) -> FileResponse | JSONResponse:
    """
    Catch-all обработчик для client-side роутинга React Router.

    Когда пользователь заходит на «глубокую» ссылку вроде /section/Rust или
    обновляет вкладку /art/Max/123, браузер шлёт GET на этот путь. На сервере
    таких путей нет: вся маршрутизация живёт в JavaScript-бандле. Сервер
    обязан для ЛЮБОГО не-/api GET вернуть один и тот же index.html — React
    Router уже на клиенте разберёт, какую «страницу» показать. Если вернуть
    404, пользователь увидит ошибку ASGI вместо приложения.

    Исключение сделано только для /api*: это JSON API, и попадание в SPA на
    несуществующий API-путь — маскировка ошибки (fetch получит HTML,
    попытается распарсить как JSON, упадёт с SyntaxError: Unexpected token '<').
    Здесь же честный JSONResponse 404, который axios/fetch обработают штатно.

    Отдельно обработан случай, когда фронт ещё не собран (index.html
    отсутствует): лучше явный 404 с подсказкой, чем FileResponse-исключение
    из Starlette или молчаливый сломанный сайт.
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


def setup_react_routing_assets(app: FastAPI) -> None:
    """
    Подключает раздачу собранного React-приложения к FastAPI.

    Вызывается из main.py СТРОГО после всех include_router, чтобы catch-all
    попал в конец router.routes. См. docs/13_frontend_spa_module.md, раздел
    «Почему catch-all добавляется руками, а не через include_router».

    Допустимо вызвать один раз за время жизни приложения. Повторный вызов
    приведёт к двойному mount('/assets') и двойному catch-all — Starlette в
    таком случае возьмёт первый подошедший маршрут, что проявит себя как
    «первый mount выиграл, второй лежит мёртвым грузом».
    """
    app.mount(
        "/assets",
        StaticFiles(directory=ASSETS_DIR, check_dir=False),
        name="spa_assets",
    )

    app.router.routes.append(Route("/{full_path:path}", spa_fallback, methods=["GET"]))

    logF.info(f"SPA подключена: index={INDEX_HTML}, assets={ASSETS_DIR}")

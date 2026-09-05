from base_dir_path import BASE_DIR
from config_log import logF

import uvicorn
from core.config import settings
from create_fastapi import create_app

from api import router_api
from ex_user_post.router_users import r_users_sql
from ex_order_product.router_order_one import r_order_one

from md_articles import setup_auth_static_include
from frontend_routing import setup_react_routing_assets


# ── сборка приложения: только API-роутеры ─────────────────────────────────────
main_app = create_app(custom_docs_url=False)

main_app.include_router(router_api)
main_app.include_router(r_users_sql)
main_app.include_router(r_order_one)

# Подключаем блог md_articles (auth middleware + static + JSON API)
setup_auth_static_include(main_app)

# ── React: монтирование /assets + catch-all, строго после роутеров ────────────
# Подробности — в frontend_routing.py и docs/13_frontend_spa_module.md.
setup_react_routing_assets(main_app)


def main() -> None:
    logF.info(f"Base dir path :\n{BASE_DIR=}")

    uvicorn.run(
        "main:main_app",
        host=settings.run.host,
        port=settings.run.port,
        reload=True,
    )

    logF.warning(
        "end '-----------------------------' my-fastapi-one '----------------------------' \n\n\n\n"
        "'********************************************************************************'"
    )


if __name__ == "__main__":
    main()

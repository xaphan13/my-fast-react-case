from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from config_log import logF
from core.config import SqliteDsn, settings
from db_core.db_async import db_manager
from utils.docs import reg_docs_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Жизненный цикл приложения: startup → yield → shutdown.

    Startup: Логирует URL базы и заголовок приложения.

    Shutdown:
      `db_manager.engine_dispose()` асинхронно закрывает пул соединений engine SQLAlchemy.
      `uvicorn --reload` корректно дожидаются завершения lifespan при остановке SIGTERM/SIGINT.

    Подробности и причины выбранной структуры — в `docs/14_create_fastapi_factory.md`.
    """
    logF.info(f"startup lifespan :\n{settings.db.url=} \n{app.title=}")
    if isinstance(settings.db.url, SqliteDsn):
        logF.warning(f"used test sqlite dataBase : {settings.db.url=}")
    yield
    await db_manager.engine_dispose()


def create_app(custom_docs_url: bool = False) -> FastAPI:
    """
    Создаёт и возвращает сконфигурированный экземпляр `FastAPI`.

    Параметры:
      custom_docs_url:
        False (по умолчанию) — стандартные `/docs` и `/redoc` от FastAPI.
        True — вместо них `reg_docs_routes(app)` регистрирует кастомные.

    Возвращает:
      `FastAPI` с:
        - `default_response_class=ORJSONResponse` (быстрее `jsonable_encoder`);
        - подключённым `lifespan` (см. выше);
        - кастомными Swagger/ReDoc, если `custom_docs_url=True`.

    Полное описание «каркас vs наполнение» — в `docs/14_create_fastapi_factory.md`.
    """
    docs_url, redoc_url = (None, None) if custom_docs_url else ("/docs", "/redoc")

    app = FastAPI(
        title="Example : Fast API - SQL - React",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
    )

    if custom_docs_url:
        reg_docs_routes(app)

    return app

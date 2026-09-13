"""Пакет auth_users — авторизация блога на fastapi-users.

Полные экспорты пакета: модель User, pydantic-схемы, UserManager и его DI,
auth-backend (cookie + JWT), экземпляр FastAPIUsers с готовыми зависимостями
current_user/active_user/optional_user/superuser_user и общий router.

Загрузочный порядок
-------------------
Между auth_users.models и db_core/__init__.py существует цикл, разрываемый
размещением `from auth_users.models import User` в самом конце
db_core/__init__.py — production-загрузка всегда идёт через main.py →
create_fastapi → db_core (полностью) → auth_users.models, поэтому
db_core.model_base уже в sys.modules к моменту парсинга auth_users.models.

В __init__.py НЕ используется `import db_core` (предзагрузка) — этот
импорт триггерит загрузку db_core, который в свою очередь тянет
md_articles → setup_frontend → api_blog → auth_users (нас самих), что
на partially-loaded модуле даёт ImportError на active_user. Вместо этого
auth_users.models импортируется лениво через from auth_users.models
(модуль models.py сам подтянет db_core.model_base, который уже загружен
всегда к моменту загрузки auth_users).
"""


from auth_users.models import User
from auth_users.schemas import UserRead, UserCreate, UserUpdate
from auth_users.user_manager import (
    UserManager,
    get_user_db,
    get_user_manager,
)
from auth_users.auth_backend import (
    auth_backend,
    cookie_transport,
    get_jwt_strategy,
)
from auth_users.fastapi_users_obj import (
    fastapi_users,
    current_user,
    active_user,
    optional_user,
    superuser_user,
)
from auth_users.router import router


__all__ = [
    "User",
    "UserRead",
    "UserCreate",
    "UserUpdate",
    "UserManager",
    "get_user_db",
    "get_user_manager",
    "auth_backend",
    "cookie_transport",
    "get_jwt_strategy",
    "fastapi_users",
    "current_user",
    "active_user",
    "optional_user",
    "superuser_user",
    "router",
]

__all__ = (
    "Base",
    "User",
    "Post",
    "Order",
    "Product",
    "OrderProductAssociation",
    "BlogUser",
    "BlogPost",
)

from db_core.model_base import Base

from ex_user_post.models.model_user_post import (
    User as _ExUserPostUser,
    Post,
)

from ex_order_product.model_order_product import (
    Order,
    Product,
    OrderProductAssociation,
)

from md_articles.models import (
    BlogUser,
    BlogPost,
)

# Сохраняем ex_user_post.User доступным под старым именем, чтобы не ломать
# прямые импорты из ex_user_post.models.model_user_post — но как `User` в этом
# пространстве имён теперь живёт fastapi-users User (см. __all__).
_ = _ExUserPostUser

# ==============================================================================
# auth_users.User — ИМПОРТ В КОНЦЕ.
# Спека просит явный `from auth_users.models import User`. Сделать это "в общем
# списке" невозможно: циркулярный импорт
#   auth_users.models -> db_core.model_base -> db_core.__init__ -> auth_users.models
# ломается на partially-loaded модуле.
#
# На практике цепочка загрузки проекта всегда идёт через main.py ->
# create_fastapi -> db_core -> ..., поэтому db_core полностью загружается ДО
# того, как что-то потребует auth_users.models. Помещаем импорт в самый конец —
# когда этот код выполняется, частичной загрузки auth_users.models ещё не было
# (его триггерит сам импорт), Python грузит модуль, класс User определяется и
# попадает в Base.metadata.
# ==============================================================================
from auth_users.models import User  # noqa: E402

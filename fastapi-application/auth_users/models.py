"""
Модель User для fastapi-users.

Наследуется от SQLAlchemyBaseUserTableUUID — тот добавляет id (UUID PK),
email (unique, index), hashed_password, is_active, is_superuser, is_verified.
Поля проекта (username, image_file, created_at) добавляются здесь.

Стиль: `Mapped[str_len_20] = mapped_column(...)` — тот же приём, что в
md_articles/models.py::BlogUser; переиспользуемые Annotated-типы колонок
живут в db_core/type_for_models.py.
"""

from datetime import datetime, timezone

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from db_core.model_base import Base
from db_core.type_for_models import str_len_20


class User(SQLAlchemyBaseUserTableUUID, Base):
    """Пользователь авторизации блога (fastapi-users).

    `username` — `nullable=True` потому что `BaseUserManager.create` сначала
    INSERT-ит строку (только email/hashed_password из `UserCreate`), а хук
    `on_after_register` дописывает `username = email.split("@")[0]` уже
    ПОСЛЕ вставки. Если колонка NOT NULL — INSERT падает с IntegrityError.
    На пользовательском уровне `username` всегда непустой (если фронт не
    обновил его через `/auth/account`).
    """

    __tablename__ = "user"

    username: Mapped[str_len_20 | None] = mapped_column(unique=True, nullable=True)
    image_file: Mapped[str_len_20] = mapped_column(
        nullable=False,
        default="default.jpg",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"User('{self.email}', '{self.username}', '{self.image_file}')"

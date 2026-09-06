from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db_core.model_base import Base
from db_core.type_for_models import (
    int_primary_key,
    str_len_20,
    str_len_60,
    str_len_100,
    str_len_120,
)


class BlogUser(Base):
    """Пользователь блога."""

    __tablename__ = "blog_user"

    id: Mapped[int_primary_key]
    username: Mapped[str_len_20] = mapped_column(unique=True, nullable=False)
    email: Mapped[str_len_120] = mapped_column(unique=True, nullable=False)
    image_file: Mapped[str_len_20] = mapped_column(
        nullable=False,
        default="default.jpg",
    )
    password: Mapped[str_len_60] = mapped_column(nullable=False)

    posts: Mapped[list["BlogPost"]] = relationship(
        back_populates="author",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    @property
    def is_authenticated(self) -> bool:
        """Совместимость с UserMixin — всегда True для реального объекта."""
        return True

    def __repr__(self) -> str:
        return f"BlogUser('{self.username}', '{self.email}', '{self.image_file}')"


class BlogPost(Base):
    """Публикация блога."""

    __tablename__ = "blog_post"

    id: Mapped[int_primary_key]
    title: Mapped[str_len_100] = mapped_column(nullable=False)
    date_posted: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("blog_user.id"),
        nullable=False,
    )

    author: Mapped["BlogUser"] = relationship(back_populates="posts")

    def __repr__(self) -> str:
        return f"BlogPost('{self.title}', '{self.date_posted}')"

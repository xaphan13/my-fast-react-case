from __future__ import annotations

from sqlalchemy import (
    UniqueConstraint,
    String,
    Column,
    Integer,
    ForeignKey,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from db_core.type_for_models import (
    int_primary_key,
    time_stamp_utc,
    str_len_50,
)

from db_core.model_base import Base


class User(Base):
    id: Mapped[int_primary_key]

    nickname: Mapped[str] = mapped_column(
        String(20),
        unique=True,
    )

    firstname: Mapped[str | None] = mapped_column(String(20))
    surname: Mapped[str | None] = mapped_column(String(20))

    password: Mapped[str_len_50 | None]

    posts = relationship(
        "Post",
        back_populates="author",
        lazy="select",
        cascade="all, delete",
    )

    __table_args__ = (UniqueConstraint(firstname, surname),)


class Post(Base):
    id: Mapped[int_primary_key]

    time_created: Mapped[time_stamp_utc]

    title: Mapped[str_len_50]
    content: Mapped[str]

    user_id = Column(
        Integer(),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
    )

    author = relationship(
        "ex_user_post.models.model_user_post.User",
        back_populates="posts",
    )

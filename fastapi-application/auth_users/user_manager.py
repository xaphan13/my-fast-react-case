"""
UserManager для fastapi-users — бизнес-правила регистрации/валидации.

Плюс DI-фабрика get_user_db/get_user_manager, которые подключаются к
FastAPUsers (см. auth_users/__init__.py в фазе 2 и route-слой в фазе 3).

Минимальная длина пароля захардкожена (8) — в фазе 2 появится
settings.auth_users.password_min_length и правка одной строки здесь.
Секрет токенов берётся из существующего settings.web.secret_key.
"""

from typing import AsyncGenerator
from uuid import UUID

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users.exceptions import InvalidPasswordException, UserAlreadyExists
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth_users.models import User
from config_log import logF
from core.config import settings
from db_core.db_async import CurrentSession


class UserManager(UUIDIDMixin, BaseUserManager[User, UUID]):
    """Пользовательский менеджер fastapi-users.

    reset_password_token_secret / verification_token_secret — подписывают
    токены сброса пароля и подтверждения email; берём из general-purpose
    settings.web.secret_key (в этом проекте нет отдельных ключей под auth).
    """

    reset_password_token_secret = settings.web.secret_key
    verification_token_secret = settings.web.secret_key

    async def validate_password(self, password: str, user: User) -> None:
        """Минимальная длина пароля — settings.auth_users.password_min_length."""
        password_min_length = settings.auth_users.password_min_length
        if len(password) < password_min_length:
            raise InvalidPasswordException(
                reason=f"Пароль должен быть не короче {password_min_length} символов."
            )

    async def create(
        self,
        user_create,
        safe: bool = False,
        request: Request | None = None,
    ) -> User:
        """Перехватывает race-condition на дубликате email/username.

        Стандартный `BaseUserManager.create` вызывает `email_exists` для
        проверки и затем INSERT. Между этими шагами другой параллельный
        запрос может успеть вставить того же пользователя — и тогда
        наш INSERT падает с IntegrityError 500.

        Перехватываем IntegrityError и бросаем UserAlreadyExists, чтобы
        register-router отдал стандартный 400 REGISTER_USER_ALREADY_EXISTS.
        """
        try:
            return await super().create(user_create, safe=safe, request=request)
        except IntegrityError:
            raise UserAlreadyExists()

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        """Дописывает username (из email, если не задан) и image_file."""
        update_dict: dict = {}

        if not user.username:
            derived = (user.email.split("@", 1)[0] or "")[:20].strip()
            user.username = derived
            update_dict["username"] = derived

        if not user.image_file:
            user.image_file = "default.jpg"
            update_dict["image_file"] = "default.jpg"

        if update_dict:
            await self.user_db.update(user, update_dict)

        logF.info("auth_users: registered %s", user.email)


async def get_user_db(
    session: CurrentSession,
) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    """DI: SQLAlchemyUserDatabase поверх CurrentSession и нашей модели User."""
    yield SQLAlchemyUserDatabase(session, User)


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    """DI: UserManager, получающий user_db из get_user_db."""
    yield UserManager(user_db)


# AsyncSession импортируется намеренно — он нужен, когда фаза 2 добавит
# typing-алиасы поверх CurrentSession (например, для overrides в тестах).
_ = AsyncSession

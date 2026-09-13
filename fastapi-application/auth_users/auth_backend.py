"""
Бэкенд аутентификации fastapi-users: CookieTransport + JWTStrategy.

`auth_backend` объединяет транспорт (cookie) и стратегию (JWT) — это то, что
передаётся в FastAPIUsers(... [auth_backend]) и используется роутерами
/auth/jwt/login и /auth/jwt/logout.

Все параметры читаются из settings.auth_users (см. core/config.py::AuthUsersConfig).
Секрет JWT — settings.web.secret_key (общий секретный ключ проекта).
"""

from fastapi_users.authentication import (
    AuthenticationBackend,
    CookieTransport,
)
from fastapi_users.authentication.strategy import JWTStrategy

from core.config import settings


cookie_transport = CookieTransport(
    cookie_name=settings.auth_users.cookie_name,
    cookie_max_age=settings.auth_users.cookie_max_age,
    cookie_secure=settings.auth_users.cookie_secure,
    cookie_httponly=settings.auth_users.cookie_httponly,
    cookie_samesite=settings.auth_users.cookie_samesite,
)


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(
        secret=settings.web.secret_key,
        lifetime_seconds=settings.auth_users.jwt_lifetime_seconds,
        algorithm=settings.auth_users.jwt_algorithm,
    )


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

"""
Экземпляр FastAPIUsers + готовые dependency-обёртки (current_user и пр.).

FastAPIUsers[User, UUID] — типизированная обёртка над UserManager, которая
создаёт current_user / current_user(active=True) / optional / superuser
зависимости. Используются в роутах блога и в account.py.
"""

from uuid import UUID

from fastapi_users import FastAPIUsers

from auth_users.auth_backend import auth_backend
from auth_users.models import User
from auth_users.user_manager import get_user_manager


fastapi_users = FastAPIUsers[User, UUID](get_user_manager, [auth_backend])

current_user = fastapi_users.current_user
active_user = fastapi_users.current_user(active=True)
optional_user = fastapi_users.current_user(optional=True)
superuser_user = fastapi_users.current_user(active=True, superuser=True)

# 03 — Модель User, UserManager, схемы и миграция

## 1. `app/models/user.py` — полный файл с комментариями

Здесь живут четыре сущности: ORM-модель, адаптер к БД, доменный менеджер и
DI-фабрика менеджера.

### 1.1. ORM-модель `User`

```python
import logging
from datetime import datetime
from typing import TYPE_CHECKING, AsyncGenerator, List
from uuid import UUID

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.db import SQLAlchemyBaseUserTableUUID, SQLAlchemyUserDatabase
from sqlalchemy import DateTime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.core.database import Base, get_db

if TYPE_CHECKING:
    from app.models.item import Item   # <- избежать циклического импорта Item <-> User

logger = logging.getLogger(__name__)


class User(SQLAlchemyBaseUserTableUUID, Base):
    # Библиотека приносит поля: id (UUID PK), email (уник. индекс),
    # hashed_password, is_active, is_superuser, is_verified.
    # Здесь добавляются ТОЛЬКО бизнес-поля:
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        # ГРАБЛИ: datetime.utcnow deprecated в 3.12+, значение naive-UTC.
        #   Для нового кода: default=lambda: datetime.now(timezone.utc).
        #   Смена default требует новой миграции (тип колонки — naive DateTime).
    )
    items: Mapped[List["Item"]] = relationship(
        "Item",
        back_populates="owner",   # обратная сторона Item.owner_id -> user.id
    )
```

Поля, приходящие из `SQLAlchemyBaseUserTableUUID` — таблица для понимания:

| Поле | Тип в БД | Кто управляет |
|---|---|---|
| `id` | `GUID` (UUID), PK | библиотека, `uuid4()` при создании |
| `email` | `String(320)`, уникальный индекс | `UserManager.get_by_email`, валидация `email-validator` |
| `hashed_password` | `String(1024)` | `PasswordHelper` (Argon2/Bcrypt), **никогда не пароль** |
| `is_active` | `Boolean` | вами; `active=True` в `current_user` проверяет его |
| `is_superuser` | `Boolean` | вами; `superuser=True` в `current_user` проверяет его |
| `is_verified` | `Boolean` | verify-потоком; по умолчанию `False` |

**Важно:** `email` и `password` при регистрации проходят через
`schemas.BaseUserCreate` — значит валидация email включена «из коробки».

### 1.2. Адаптер `get_user_db`

```python
async def get_user_db(
    session: AsyncSession = Depends(get_db),
) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    yield SQLAlchemyUserDatabase(session, User)
    # SQLAlchemyUserDatabase — «мост» между UserManager и SQLAlchemy:
    #   реализует get/create/update/get_by_email в терминах вашей модели.
    # Второй аргумент — КЛАСС модели: библиотека не знает, как называется
    #   ваша таблица. Забыть передать User = ошибка только в рантайме.
```

### 1.3. `UserManager` — единственное место бизнес-логики пользователя

```python
class UserManager(UUIDIDMixin, BaseUserManager[User, UUID]):
    # UUIDIDMixin обязан соответствовать типу PK модели (UUID).
    # Для int-PK есть IntegerIDMixin. Несоответствие = падение parse_id.
    reset_password_token_secret = settings.SECRET_KEY
    verification_token_secret = settings.SECRET_KEY
    # Секреты для токенов сброса пароля и верификации email.
    # ГРАБЛИ: здесь тот же SECRET_KEY — смена ключа инвалидирует и эти токены.

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        # Хук вызывается ПОСЛЕ записи пользователя в БД (внутри user_manager.create).
        # Идеальное место для welcome-email, аудита, начальной инициализации.
        # Базовая реализация пустая — проект переопределяет только логированием.
        logger.info("User %s (%s) has registered successfully.", user.id, user.email)

    async def on_after_forgot_password(self, user, token, request=None) -> None:
        # Сюда вешать отправку письма со ссылкой /reset-password?token=...
        logger.info("User %s (%s) requested password reset.", user.id, user.email)

    async def on_after_request_verify(self, user, token, request=None) -> None:
        # Сюда — письмо с подтверждением email.
        logger.info("Verification requested for user %s (%s).", user.id, user.email)
```

**Что ещё умеет базовый `BaseUserManager` (и что важно при переносе):**

`authenticate` — вызывается встроенным login-роутером:

```python
# fastapi_users/manager.py (суть, 15.0.5)
user = await self.get_by_email(credentials.username)
# credentials — OAuth2PasswordRequestForm: username = email (OAuth2-конвенция)
if пользователь не найден:
    self.password_helper.hash(credentials.password)  # почему: выровнять время
    return None                                      #   ответа, скрыть факт
                                                     #   отсутствия email
verified, updated_hash = self.password_helper.verify_and_update(
    credentials.password, user.hashed_password)
if not verified:
    return None
if updated_hash is not None:
    # Хеш старого формата (bcrypt) тихо перезаписывается на свежий (argon2):
    # миграция хешей бесплатна, при следующем логине.
    await self.user_db.update(user, {"hashed_password": updated_hash})
return user
```

`create` — вызывается кастомным `/auth/register`:

```python
# fastapi_users/manager.py (суть)
await self.validate_password(user_create.password, user_create)
# БАЗОВАЯ РЕАЛИЗАЦИЯ ПУСТАЯ. Проект её НЕ переопределяет => сервер примет
#   пароль из 1 символа, minlength="8" в шаблоне — только на клиенте.
#   Известный дефект; фикс для нового проекта — ниже.

existing = await self.user_db.get_by_email(user_create.email)
if existing:
    raise UserAlreadyExists()       # -> 400 REGISTER_USER_ALREADY_EXISTS

user_dict = user_create.create_update_dict() if safe else user_create.create_update_dict_superuser()
# safe=True (как в проекте) вырезает is_superuser/is_active/is_verified из
#   тела запроса. НЕЛЬЗЯ вызывать create(..., safe=False) из публичного эндпоинта —
#   клиент сможет сам сделать себя суперпользователем.

user_dict["hashed_password"] = self.password_helper.hash(user_dict.pop("password"))
created_user = await self.user_db.create(user_dict)
await self.on_after_register(created_user, request)   # <- хук уже после записи
return created_user
```

Фикс валидации пароля для нового проекта (в `UserManager`):

```python
from fastapi_users.exceptions import InvalidPasswordException

async def validate_password(self, password: str, user) -> None:
    if len(password) < 8:
        raise InvalidPasswordException(
            reason="Password should be at least 8 characters",
        )
```

### 1.4. DI-фабрика `get_user_manager`

```python
async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    """Get user manager dependency."""
    yield UserManager(user_db)
```

Полная цепочка, которую FastAPI разворачивает на каждый запрос, где нужен
менеджер или текущий пользователь:

```
get_db                    (app/core/database.py)   -> AsyncSession
  └─ get_user_db          (app/models/user.py)     -> SQLAlchemyUserDatabase
       └─ get_user_manager(app/models/user.py)     -> UserManager
            └─ fastapi_users.current_user(...) / роутеры библиотеки
```

`get_user_manager` — это **dependency-функция**, а не одиночка: `FastAPIUsers`
передаёт её во все свои роутеры и в `Authenticator`. Переопределить её в
тестах — стандартный способ подменить поведение менеджера (см. [07](07_testing.md)).

## 2. `app/schemas/user.py` — Pydantic-контракты API

```python
from uuid import UUID

from fastapi_users import schemas


class UserRead(schemas.BaseUser[UUID]):
    # Что ОТСЫЛАЕТСЯ наружу (GET /users/me и т.п.):
    # id, email, is_active, is_superuser, is_verified.
    # hashed_password сюда НЕ входит — BaseUser его не содержит.
    # Свои поля (created_at) добавляйте здесь:
    #   created_at: datetime | None
    pass


class UserCreate(schemas.BaseUserCreate):
    # Что ПРИНИМАЕТСЯ при регистрации: email (валидный, через email-validator)
    # + password. То, что пришло лишнее (is_superuser=...), отсечёт
    # user_manager.create(..., safe=True).
    pass


class UserUpdate(schemas.BaseUserUpdate):
    # Что принимает PATCH /users/me: email, password, is_active... —
    # is_* поля для обычного пользователя вырежет зависимость с superuser=True.
    pass
```

Почему отдельные схемы Read/Create/Update: разные наборы полей для разных
направлений данных — это защита от «массового присваивания». `UserRead`
используется в `get_users_router(UserRead, UserUpdate)`.

## 3. `app/models/__init__.py` — почему re-export обязателен

```python
# Models
from app.models.item import Item  # noqa: F401
from app.models.user import User  # noqa: F401
```

Alembic собирает схему из `Base.metadata`. `Base` знает только о тех моделях,
которые были **импортированы** к моменту запуска миграций. `alembic/env.py`
импортирует `app.models` — если новую модель (или сам `User`) забыть
подключить сюда, autogenerate молча не увидит таблицу.

## 4. Миграция `alembic/versions/8d9cb1e66c56_initial_migration.py`

Сгенерирована autogenerate; фрагмент таблицы пользователя:

```python
def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('user',
    sa.Column('created_at', sa.DateTime(), nullable=True),        # добавленное проектом поле
    sa.Column('id', fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False),
    # GUID — кросс-БД тип UUID: на PostgreSQL это native uuid, на SQLite CHAR(32)
    sa.Column('email', sa.String(length=320), nullable=False),    # 320 = RFC-максимум
    sa.Column('hashed_password', sa.String(length=1024), nullable=False),
    # 1024 — с запасом: argon2/bcrypt-хеши длиннее «сырых» паролей
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('is_superuser', sa.Boolean(), nullable=False),
    sa.Column('is_verified', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_email'), 'user', ['email'], unique=True)
    # unique=True — второй барьер против дублей email (первый — проверка в UserManager).
```

Практика переноса: `init_db()` (`Base.metadata.create_all`) в `lifespan` и
Alembic **дублируют** создание схемы. Для dev удобно; для прода оставляйте
только Alembic (`uv run alembic upgrade head`), иначе возможны «already exists»
в зависимости от того, что создало БД первой.

Дальше: [04_routers.md](04_routers.md) — сборка приложения и HTML-поток входа.

# 02 — Ядро авторизации: users.py, config.py, database.py

Три файла в `app/core/` — фундамент. Если понять их, остальное — надстройка.

## 1. `app/core/users.py` — весь механизм в 26 строках

Это единственный файл, где проект «конфигурирует» библиотеку. Полный код с
комментариями (добавленные пояснения помечены `# почему:`):

```python
from uuid import UUID

from fastapi_users import FastAPIUsers
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy import JWTStrategy

from app.core.config import settings          # <- единственный источник секретов
from app.models.user import User, get_user_manager

# Cookie-транспорт: как токен попадает "в мир" и обратно.
cookie_transport = CookieTransport(cookie_name="auth", cookie_max_age=3600)
# почему cookie_name="auth": короткое имя = маленькие заголовки; НО это же имя
#   хардкодится в app/api/auth.py при ручной очистке cookie — менять только парой.
# почему max_age=3600: persistent cookie на 1 час; None превратил бы её в
#   session cookie (умирает с закрытием браузера) — для SSR-приложения час удобнее.
#
# ГРАБЛИ: cookie_secure здесь НЕ задан. Дефолт fastapi-users 15.x — True
#   (проверено по исходнику .venv/.../transport/cookie.py:19). Значит:
#   - браузер сохранит cookie только по HTTPS (localhost — исключение,
#     Chrome/Firefox считают его secure-контекстом);
#   - по http://192.168.x.x cookie молча не сохранится — «вечный логин-фейл».
# ПРАВИЛО ПЕРЕНОСА: задавать явно:
#   cookie_transport = CookieTransport(
#       cookie_name="auth",
#       cookie_max_age=3600,
#       cookie_secure=True,      # в dev-окружении False через настройки
#       cookie_httponly=True,
#       cookie_samesite="lax",
#   )


def get_jwt_strategy() -> JWTStrategy:
    # Фабрика, а не одиночка: стратегия вызывается на каждый login/logout,
    # и библиотека ожидает именно callble (Depends(backend.get_strategy)).
    return JWTStrategy(secret=settings.SECRET_KEY, lifetime_seconds=3600)
    # почему lifetime и тут: срок жизни ТОКЕНА. max_age cookie и lifetime JWT
    #   должны совпадать, иначе cookie «живёт» дольше валидного токена и
    #   пользователь получает 401 с внешне живой сессией.


# Бэкенд = транспорт + стратегия + имя.
auth_backend = AuthenticationBackend(
    name="jwt",                    # участвует в именах роутов "auth:jwt.login"
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

# Точка входа: из неё получаются и роутеры, и dependency current_user.
fastapi_users = FastAPIUsers[User, UUID](get_user_manager, [auth_backend])
# [User, UUID] — дженерик: ORM-модель и тип её первичного ключа.
# Второй аргумент — список бэкендов: можно иметь несколько (cookie + Bearer).
```

**Разбор по сущностям.**

### `CookieTransport` — что он реально делает

Из исходника библиотеки (15.0.5):

```python
# fastapi_users/authentication/transport/cookie.py (фрагмент)
def __init__(self, cookie_name="fastapiusersauth", cookie_max_age=None,
             cookie_path="/", cookie_domain=None, cookie_secure=True,
             cookie_httponly=True, cookie_samesite="lax"):
    ...
    self.scheme = APIKeyCookie(name=self.cookie_name, auto_error=False)
```

- `auto_error=False` критично: при отсутствии cookie схема **не** кидает 403,
  а возвращает `None`. Кто решает, что делать с «нет токена» — `Authenticator`
  и флаги `current_user(...)`: `optional=True` даст `None`, иначе `401`.
- При логине: `Response(status_code=204)` + `set_cookie(...)` — поэтому
  шаблон логина реагирует именно на `204` (см. [06](06_frontend_htmx.md)).
- При логауте: `set_cookie("auth", "", max_age=0)` — браузер удаляет cookie.

### `JWTStrategy` — что внутри токена

```python
# fastapi_users/authentication/strategy/jwt.py (фрагменты)
async def write_token(self, user):
    data = {"sub": str(user.id), "aud": self.token_audience}  # aud=["fastapi-users:auth"]
    return generate_jwt(data, self.encode_key, self.lifetime_seconds, algorithm=self.algorithm)
    # HS256: подпись и проверка одним и тем же SECRET_KEY (симметрично).

async def read_token(self, token, user_manager):
    if token is None:
        return None                      # нет cookie -> «не аутентифицирован», не ошибка
    try:
        data = decode_jwt(token, self.decode_key, self.token_audience, algorithms=[self.algorithm])
        user_id = data.get("sub")
        if user_id is None:
            return None
    except jwt.PyJWTError:
        return None                      # ЛЮБАЯ ошибка JWT (подпись/срок/aud) => None
    try:
        parsed_id = user_manager.parse_id(user_id)
        return await user_manager.get(parsed_id)   # SELECT ... WHERE id = sub
    except (UserNotExists, InvalidID):
        return None                      # пользователь удалён => «не аутентифицирован»
```

Три следствия, которые важно понимать при переносе:

1. **Ошибки токена превращаются в «анонима», а не в 500.** Просроченный,
   подделанный или с чужим `aud` токен — это просто отсутствие пользователя.
2. **`sub` — единственное содержимое.** Роли/права в токен не пишутся:
   `is_active`/`is_superuser` читаются из БД на каждом запросе, поэтому
   «выключить» пользователя можно мгновенно (в отличие от токенов с ролями).
3. **`aud` разделяет назначения токенов.** У login-токена
   `aud="fastapi-users:auth"`, у reset/verify-токенов UserManager — другие
   audience. Токен из одного потока не пройдёт проверку в другом.

## 2. `app/core/config.py` — SECRET_KEY и его последствия

```python
import secrets
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./app.db"
    SQLITE_ASYNC_CONN_STR: str | None = None

    # Security
    # IMPORTANT: Use a strong, randomly generated secret in production.
    # Generate one using: openssl rand -hex 32 or secrets.token_hex(32)
    # Store this persistent key in your .env file or environment variables.
    SECRET_KEY: str = secrets.token_hex(32)
    # ГРАБЛИ (главная мина проекта): это runtime-default. Без .env каждый
    #   рестарт генерирует НОВЫЙ ключ => все JWT, подписанные старым ключом,
    #   перестают проходить decode => ВСЕ пользователи молча разлогинены.
    #   Для dev «просто запустил и работает» — удобно; для прода — недопустимо.
    #   Чеклист переноса: SECRET_KEY всегда в .env (openssl rand -hex 32).

    @model_validator(mode="before")
    @classmethod
    def set_sqlite_async_conn_str(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Set SQLite connection string for compatibility if using SQLite."""
        database_url = values.get("DATABASE_URL", "")
        if "sqlite+aiosqlite" in database_url:
            # Ensure proper SQLite async connection format
            if not database_url.startswith("sqlite+aiosqlite:///./"):
                values["SQLITE_ASYNC_CONN_STR"] = database_url.replace(
                    "sqlite+aiosqlite:///",
                    "sqlite+aiosqlite:///./",
                )
            else:
                values["SQLITE_ASYNC_CONN_STR"] = database_url
        return values

    @property
    def is_sqlite(self) -> bool:
        """Check if the current database is SQLite."""
        return "sqlite" in self.DATABASE_URL.lower()

    @property
    def is_postgresql(self) -> bool:
        """Check if the current database is PostgreSQL."""
        return "postgresql" in self.DATABASE_URL.lower()

    # Читает .env из cwd БЕЗ префикса переменных. Переменные вида APP__X
    # игнорируются — переносите имена 1:1: DATABASE_URL, SECRET_KEY.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
```

**Кто ещё ест этот SECRET_KEY.** В `app/models/user.py:45-46`:

```python
class UserManager(UUIDIDMixin, BaseUserManager[User, UUID]):
    reset_password_token_secret = settings.SECRET_KEY
    verification_token_secret = settings.SECRET_KEY
```

Один секрет подписывает всё: login-сессии, reset- и verify-токены. Смена
секрета инвалидирует сразу все три вида. Если в новом проекте нужен раздельный
ротации — выносите отдельные поля `Settings` и переопределяйте эти атрибуты.

**lifespan предупреждает, но не валидирует** (`app/main.py:30-35`) — в лог
пишутся первые 8 символов ключа и напоминание про `.env`. Фикс для прода —
валидатор в `Settings`, см. [08](08_porting_checklist.md).

## 3. `app/core/database.py` — сессия, на которой стоит вся цепочка

```python
engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)
# SQLite-специфика: connect_args={"check_same_thread": False} (см. if settings.is_sqlite).

AsyncSessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Good default for FastAPI background tasks
    # почему: после commit ORM-объекты НЕ инвалидируются. UserManager и роуты
    #   обращаются к user.email/user.id уже после commit — с expire_on_commit=True
    #   каждый доступ тянул бы ленивый SELECT (в async — исключение).
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session          # <- роут работает внутри этой сессии
            await session.commit() # <- commit ПОСЛЕ успешного ответа хендлера
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
```

Это «commit-on-success» паттерн: хендлеры могут менять `user.hashed_password`
и **не** вызывать `commit` сами... но в этом проекте часть кода вызывает
`await db.commit()` вручную (`app/api/user.py:62,156`). Оба варианта работают:
повторный commit на чистой сессии безвреден. Для переноса выберите **один**
стиль и держитесь его.

**Почему `get_db` — часть авторизации.** Цепочка зависимостей начинается с него:

```
get_db (сессия)
  └─ get_user_db (app/models/user.py) — оборачивает сессию в SQLAlchemyUserDatabase
       └─ get_user_manager — создаёт UserManager
            └─ Authenticator._authenticate — current_user(...)
                 └─ любой защищённый роут
```

Каждый запрос с `current_user` открывает свою сессию через `get_db` — то есть
один запрос может открыть **несколько** сессий (например, роут `items` берёт
`get_db` для списка, а `current_user` — свою для `user_manager.get`). Это
нормально, но помните при отладке транзакций.

Дальше: [03_models_and_schemas.md](03_models_and_schemas.md) — модель, менеджер, схемы.

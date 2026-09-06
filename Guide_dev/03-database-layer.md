# 03. Асинхронный слой данных: SQLAlchemy 2.0 async + Alembic

> Цикл «FastAPI + React». Предыдущая: [02. Скелет бэкенда](02-fastapi-backend.md) · Следующая: [04. JSON API](04-json-api-contract.md)

## Зачем async

FastAPI — асинхронный фреймворк: пока один запрос ждёт ответа БД, event loop
обслуживает другие. Синхронный драйвер БД внутри `async def` **блокирует весь
loop** — это худшее из возможных сочетаний.

> `async def` в обработчиках → асинхронный драйвер (`asyncpg`, `aiosqlite`) →
> `create_async_engine` → `AsyncSession`.

SQLAlchemy 2.0-стиль даёт декларативные типизированные модели (`Mapped[]`) и
единый синтаксис `select()` для ORM и Core. Плюс Alembic для миграций — схема
БД живёт в git, а не «в голове продакшена».

## Движок и менеджер сессий

Файл `fastapi-application/db_core/db_async.py` — реальный код проекта:

```python
class AsyncDbManager:
    def __init__(self, url: str, echo: bool = False, pool_size: int = 5,
                 max_overflow: int = 10) -> None:
        self.engine: AsyncEngine = create_async_engine(
            url=url, echo=echo, echo_pool=echo_pool,
            pool_size=pool_size, max_overflow=max_overflow,
        )

        if isinstance(settings.db.url, SqliteDsn):
            # SQLite по умолчанию не проверяет внешние ключи — включаем
            @event.listens_for(self.engine.sync_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,   # объекты остаются пригодны после commit
        )

db_manager = AsyncDbManager(url=str(settings.db.url), ...)   # синглтон на процесс
```

Пояснения по параметрам сессии:

- `expire_on_commit=False` — после `commit()` атрибуты объектов не
  сбрасываются, и их можно сериализовать в pydantic без повторных SELECT
  (критично для `response_model`).
- `pool_size` / `max_overflow` — пул соединений. При gunicorn с N воркерами
  реальный лимит = `workers × (pool_size + max_overflow)` — не забывайте про
  это при настройке лимитов PostgreSQL.
- Слушатель `set_sqlite_pragma` включается только для SQLite (AsyncPostgres
  внешние ключи поддерживает сам).

## Сессия через Depends: один алиас на весь проект

`db_core/db_async.py` (`get_async_session` + `CurrentSession`):

```python
async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
    async with self.session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

CurrentSession = Annotated[AsyncSession, Depends(db_manager.get_async_session)]
```

Что здесь важно:

- **Генератор = контекст.** Код до `yield` — открытие, после — teardown.
  Сессия живёт ровно один запрос.
- **Rollback при любом исключении** — транзакция не остаётся «висеть» с
  незакрытыми изменениями. Commit при этом — ответственность вызывающего
  кода (см. ниже).
- **Алиас `CurrentSession`** — обработчики пишут `session: CurrentSession`
  и не знают ни про фабрику, ни про движок. Смена способа получения
  сессии не трогает ни один роут.

## Модели: SQLAlchemy 2.0 + переиспользуемые типы

Два приёма, которые убирают дублирование из деклараций.

**Переиспользуемые `Annotated`-типы колонок** (`db_core/type_for_models.py`):

```python
int_primary_key = Annotated[int, mapped_column(primary_key=True, index=True)]
time_stamp_utc  = Annotated[datetime, mapped_column(
                    DateTime(timezone=True),
                    default=lambda: datetime.now(timezone.utc),
                    server_default=func.now())]
str_len_20      = Annotated[str, mapped_column(String(20))]
str_len_60      = Annotated[str, mapped_column(String(60))]
str_len_100     = Annotated[str, mapped_column(String(100))]
str_len_120     = Annotated[str, mapped_column(String(120))]
text_content    = Annotated[str, mapped_column(String(10000))]
```

**Базовый класс** (`db_core/model_base.py`):

```python
class Base(DeclarativeBase):
    __abstract__ = True
    metadata = MetaData(naming_convention=settings.db.naming_convention)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return f"{camel_case_to_snake_case(cls.__name__)}s"
```

`Base` сам генерирует `__tablename__` из имени класса (`BlogUser` →
`blog_users`) и задаёт `naming_convention` для констрейнтов — благодаря ей
автогенерируемые миграции воспроизводимы
(`fk_blog_post_user_id_blog_users`), а не случайные имена.

**Модель many-to-many через явную ассоциативную модель** — так делают, когда
на связи нужны свои поля (количество, цена и т.п.):

```python
class OrderProductAssociation(Base):
    __tablename__ = "order_product_association"   # имя задано явно: конвенция бы сломалась
    order_id:   Mapped[int] = mapped_column(ForeignKey("orders.id"), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    count:      Mapped[int] = mapped_column(default=1)
```

**Реэкспорт всех моделей в `db_core/__init__.py`** — критичный момент для
Alembic:

```python
__all__ = ("Base", "User", "Post", "Order", "Product",
           "OrderProductAssociation", "BlogUser", "BlogPost")

from db_core.model_base import Base
from ex_user_post.models.model_user_post import User, Post
from ex_order_product.model_order_product import Order, Product, OrderProductAssociation
from md_articles.models import BlogUser, BlogPost
```

Именно этот импорт наполняет `Base.metadata`. Модель, не попавшая в
реэкспорт, для Alembic не существует — миграция её молча не создаст.

## CRUD-слой: функции с сессией в аргументе

Репозиторий здесь — модуль свободных функций, принимающих сессию первым
аргументом (`fastapi-application/ex_user_post/crud/crud_users.py`):

```python
async def get_all_users(session: AsyncSession) -> Sequence[User]:
    stmt = select(User).order_by(User.id)
    result = await session.scalars(stmt)
    return result.all()

async def create_user(session: AsyncSession, user_create: UserCreate) -> User:
    user = User(**user_create.model_dump())
    session.add(user)
    await session.commit()       # транзакция фиксируется здесь
    await session.refresh(user)  # дочитываем id и server_default
    return user
```

**Почему сессия снаружи, а не создаётся внутри функции:**

- Функции композируемы: несколько операций можно провести в одной
  транзакции.
- Тестируемость: передайте in-memory SQLite — и функция работает без
  FastAPI.
- Нет скрытых зависимостей от глобального состояния.

**Компромисс:** `commit()` внутри CRUD делает невозможной композицию
нескольких CRUD-вызовов в одну транзакцию. Альтернатива — паттерн Unit of
Work: CRUD только делает `add`/`execute`, а commit делает обработчик или
зависимость-обёртка. Для небольших проектов commit-в-CRUD — приемлемая
простота.

## Миграции Alembic

Асинхронный `env.py`, запуск — строго из `fastapi-application/` (там
`alembic.ini` и плоские импорты):

```bash
cd fastapi-application
../.venv/bin/alembic upgrade heads            # применить все миграции
../.venv/bin/alembic revision --autogenerate  # сгенерировать по diff моделей
```

Два критичных правила:

1. **Модель должна быть импортирована до автогенерации.** В проекте это
   делает реэкспорт в `db_core/__init__.py` — именно он наполняет
   `Base.metadata`. Модель, не попавшая в реэкспорт (как
   `TestUser_post` в `model_user_mix.py`), для Alembic не существует —
   миграция её молча не создаст.
2. **Проверяйте автогенерацию руками.** Autogenerate не видит переименований
   (делает drop+add), не переносит данные. Сгенерированный файл — черновик,
   который нужно прочитать и поправить до `upgrade`.

## Чтение со связями: joinedload и dedup

Из `ex_order_product/router_order_one.py` (демо-часть):

```python
stmt = (
    select(Order)
    .options(joinedload(Order.products))     # LEFT JOIN, один SQL-запрос
    .order_by(Order.id)
)
result = await session.execute(stmt)
orders = result.unique().scalars().all()     # .unique() ОБЯЗАТЕЛЕН при joinedload на коллекцию
```

`.unique()` нужен потому, что JOIN размножает строки заказа по товарам;
без него получите дубликаты ORM-объектов. Для больших коллекций чаще
выгоднее `selectinload` (два запроса вместо одного с взрывающимся JOIN) —
выбирайте по профилю запроса, а не по привычке.

## Чекпоинт самопроверки

- [ ] Драйвер асинхронный, движок — `create_async_engine`.
- [ ] Сессия приходит через DI-алиас `CurrentSession`, а не создаётся в обработчике.
- [ ] `expire_on_commit=False` — сериализация после commit не ломается.
- [ ] SQL не пишется в роутерах — только в CRUD/сервисном слое.
- [ ] Каждая модель реэкспортирована в `db_core/__init__.py`.
- [ ] Миграции применяются командой, а не «руками в БД».
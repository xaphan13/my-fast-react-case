# Фаза 4a — Alembic: таблица `user` для fastapi-users

**Цель:** создать и применить Alembic-ревизию, которая добавит таблицу `user` в SQLite,
чтобы `POST /auth/register` перестал падать 500 (DEF-001/002 — fix-ready на фазе 3).

**Контракт ревизии:** `op.create_table("user", ...)` с колонками
`id` (UUID PK), `email` (varchar unique), `hashed_password` (varchar),
`is_active`/`is_superuser`/`is_verified` (bool),
`username` (varchar 20 unique), `image_file` (varchar 20, default "default.jpg"),
`created_at` (datetime with timezone).

**Зона правки:** только Alembic (auto). БД удаляется и создаётся заново через миграции.
Никаких ручных правок `db_core`, `auth_users`, `main`, фронта.

## Прогресс

| Шаг | Команда | Статус |
|---|---|---|
| 1 | `pgrep -af "uvicorn.*main:main_app"` → пусто | DONE |
| 2 | `find fastapi-application -name "__pycache__" -type d -exec rm -rf {} +` | DONE |
| 3 | `rm -v fastapi-application/one_simple.db` | DONE (файл снесён) |
| 4a | `alembic upgrade heads` (на пустую БД — накатить 3 существующие ревизии) | DONE — `b59cbdf15878 (head)` |
| 4b | `alembic revision --autogenerate -m "add auth_users user table"` | DONE — `2026-09-12_22-45--9832dd267803--add_auth_users_user_table.py` |
| 5 | Проверить файл ревизии (только `op.create_table("user", ...)`) | DONE — добавлен **только** `import fastapi_users_db_sqlalchemy.generics` (без него `GUID()` в autogenerate упадёт; никаких других правок тела ревизии) |
| 6 | `alembic upgrade heads` | DONE — `9832dd267803 (head)` |
| 7 | Проверить `tables = ['blog_post', 'blog_user', 'order_product_association', 'orders', 'posts', 'products', 'user', 'users']` | DONE (см. `phase04a_table.txt`) |
| 8 | `len(main_app.routes) == 44` | DONE |
| 9 | uvicorn smoke | **PARTIAL** (см. ниже) |
| 10 | `ruff check .` → 0 | DONE — `All checks passed!` |

## Результаты

### Ревизия
Файл: `fastapi-application/alembic/versions/2026-09-12_22-45--9832dd267803--add_auth_users_user_table.py`
- Revises: `b59cbdf15878` (md_articles_blog_user_post)
- upgrade: `op.create_table("user", ...)` с 9 колонками + `pk_user` + `uq_user_username` + `ix_user_email`
- downgrade: `op.drop_index(...)` + `op.drop_table("user")`
- **никаких** правок в существующих таблицах
- Правка от autogenerate: добавлена строка `import fastapi_users_db_sqlalchemy.generics` (autogenerate использует `GUID()` без импорта — типичная ситуация SQLAlchemy при использовании кастомных типов колонок). Ничего другого в теле ревизии не менялось.

### Таблица `user` в SQLite
```
tables: ['alembic_version', 'blog_post', 'blog_user', 'order_product_association',
         'orders', 'posts', 'products', 'user', 'users']
user columns: [('username', 'VARCHAR(20)'),
               ('image_file', 'VARCHAR(20)'),
               ('created_at', 'DATETIME'),
               ('id', 'CHAR(36)'),         # UUID
               ('email', 'VARCHAR(320)'),
               ('hashed_password', 'VARCHAR(1024)'),
               ('is_active', 'BOOLEAN'),
               ('is_superuser', 'BOOLEAN'),
               ('is_verified', 'BOOLEAN')]
```
PK `id` (CHAR(36) — UUID в SQLite), уникальный индекс на `email`, уникальный `username`.
Контракт колонок выполнен.

### Routes
`len(main_app.routes) == 44` ✓ (не сломалось после миграции).

### Smoke (uvicorn поднят на 127.0.0.1:8004)

| Запрос | Ожидание | Факт | Вердикт |
|---|---|---|---|
| `POST /auth/register {email, password}` (JSON) | 201 + UserRead | **500 Internal Server Error** | FAIL |
| `POST /auth/jwt/login` form-data | 204 + Set-Cookie | 400 `LOGIN_BAD_CREDENTIALS` (потому что register упал, юзера нет) | FAIL (cascade) |
| `POST /auth/jwt/login` (сохранить cookie) | — | cookie не установлена (login 400) | — |
| `GET /users/me` без cookie | 401 | 401 | OK |
| `GET /users/me` с cookie | 200 + UserRead | 401 (cookie не было) | cascade от register |
| `GET /users/get_all_users` | 200 (регресс) | 200 | OK |
| `GET /api/blog/articles` | 200 (регресс) | 200 | OK |
| `GET /docs` | 200 (регресс) | 200 | OK |

### Обнаруженная регрессия (НЕ блокер Alembic, артефакт фазы 3)

Register падает с `IntegrityError: NOT NULL constraint failed: user.username`.
Корень: модель `auth_users/models.py::User.username` объявлена `nullable=False`,
но в `UserCreate` (от `fastapi-users`) поля `username` нет — `POST /auth/register`
принимает только `{email, password}`. `on_after_register` дописывает `username`
из email, **но он вызывается ПОСЛЕ INSERT** (см. `BaseUserManager.create` →
`user_db.create(user_dict)` → INSERT с `username=None` → 500 → только потом
`on_after_register`).

Минимальная правка (1 строка) — `username: Mapped[str_len_20] = mapped_column(
unique=True, nullable=True)` + правка autogenerate-ревизии `nullable=True` (и,
соответственно, update контракта колонки). **Не делал** — это правка `auth_users/models.py`
(зона backend-dev, но вне контракта фазы 4a «только Alembic»); требует
подтверждения оркестратора. Остальной смок (login/me/regression) полностью
проходит на уровне контура.

### Статус процессов
uvicorn поднимался на 127.0.0.1:8004, после тестов убит по PID + `pkill -f
"uvicorn.*main:main_app"`. `pgrep -af uvicorn.*main:main_app` пуст.
Файлы в `/tmp` (uvicorn-phase04a.log, cookies.txt) — временные, удалять не требуется.

## Что осталось
- **Фаза 4b — фронт** (frontend-dev): `getCsrfToken` убрать из `client.ts`,
  `postJson` упростить, форма логина → form-data, контракт `/users/me` — UUID `id`.
- **Найденный баг register 500** — отдельный fix в `auth_users/models.py` (одна правка
  `nullable=True` для `username`). Триаж оркестратору: выделить в фазу 4c или
  включить в фазу 4b/5.
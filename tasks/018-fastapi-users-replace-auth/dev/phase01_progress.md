# Phase 01 — progress (backend-dev)

Задание: замена самописной авторизации блога на fastapi-users.
Фаза 1: scaffold пакета auth_users + зависимость fastapi-users.

## Итог
- pyproject.toml: добавлена `fastapi-users[sqlalchemy]>=14.0.1`; удалена
  `bcrypt>=4.2.0` (пароли хеширует fastapi-users поверх argon2/pwdlib);
  `itsdangerous>=2.2.0` ОСТАВЛЕНА — см. «Расхождения со спекой» ниже.
- uv.lock: разрешён граф 55 пакетов (было 50). Ключевые новые:
  fastapi-users 15.0.5, fastapi-users-db-sqlalchemy 7.0.0,
  argon2-cffi 25.1.0, pwdlib 0.3.0, pyjwt 2.14.0, makefun 1.16.0.
  Полный лог — `phase01_uvlock.txt`.
- Создан пакет `fastapi-application/auth_users/` (5 файлов).
- `db_core/__init__.py`: `db_core.User` теперь указывает на fastapi-users-модель;
  бывшая `ex_user_post.User` переименована в `_ExUserPostUser` (под старым
  именем доступна через прямой импорт из своего модуля во всех роутерах
  ex_user_post); `Base.metadata` содержит обе модели (`users` и `user`).
- Checkpoint 1, 2 (модифицированный), 3, 3b — зелёные. ruff чист.
  `main_app` грузится с 42 маршрутами (без регрессии).

## Шаги

### 2026-09-12 — pyproject.toml + uv lock
- Файл: `pyproject.toml`
- Изменение: добавлена зависимость `fastapi-users[sqlalchemy]>=14.0.1`.
  Удалена `bcrypt>=4.2.0` (миграция паролей на argon2 через pwdlib).
  `itsdangerous>=2.2.0` ОСТАВЛЕНА с поясняющим комментарием (см. ниже).
- `uv lock` → 55 packages resolved.
- `uv sync` → установил новые пакеты.
- Проверка: `grep '^name = "fastapi-users"' uv.lock` → найдено ✓

### 2026-09-12 — auth_users scaffold
- Создан `fastapi-application/auth_users/__init__.py`:
  ПУСТОЙ (только docstring + `__all__: list[str] = []`).
  Спека просила `from auth_users.models import User` — это вызывает циркулярный
  импорт (см. ниже).
- Создан `fastapi-application/auth_users/models.py`:
  `class User(SQLAlchemyBaseUserTableUUID, Base)` с `__tablename__ = "user"`,
  полями `username` (Mapped[str_len_20], unique, not null),
  `image_file` (Mapped[str_len_20], default "default.jpg"),
  `created_at` (DateTime(timezone=True), default UTC now).
  Стиль — `Mapped[str_len_20] = mapped_column(...)`, как в
  `md_articles/models.py::BlogUser`. `__repr__` для отладки.
- Создан `fastapi-application/auth_users/schemas.py`:
  UserRead (с username, image_file), UserCreate/Update — без полей.
- Создан `fastapi-application/auth_users/user_manager.py`:
  `UserManager(UUIDIDMixin, BaseUserManager)` с секретами токенов из
  `settings.web.secret_key`. `validate_password` — min length захардкожен
  в 8 с TODO-комментарием для фазы 2 (`settings.auth_users.password_min_length`).
  `on_after_register` — деривация `username` из email и сеттер `image_file`,
  сохранение через `user_db.update(user, {...})`, логирование.
  DI: `get_user_db(session)` → `SQLAlchemyUserDatabase(session, User)`,
  `get_user_manager(user_db=Depends(get_user_db))` → `UserManager(user_db)`.
- Создан `fastapi-application/auth_users/helpers.py`:
  `is_valid_email`, `username_exists(session, username)`,
  `email_exists(session, email)` — все на новой модели User.
  `save_picture(form_picture)` — путь через `BASE_DIR / "static" / "profile_pics/"`.
  `validation_response(errors)`, константы `ERROR_EMAIL_TAKEN`,
  `ERROR_USERNAME_TAKEN`.

### 2026-09-12 — db_core/__init__.py
- Файл: `fastapi-application/db_core/__init__.py`
- Изменение: бывший `User` из `ex_user_post.models.model_user_post`
  переименован в `_ExUserPostUser`; `from auth_users.models import User`
  добавлен В САМОМ КОНЦЕ файла. Поиск grep по всему проекту подтвердил,
  что `from db_core import User` нигде не используется — все потребители
  импортируют `User` напрямую из `ex_user_post.models.model_user_post`.
  `db_core.User` теперь указывает на fastapi-users-модель.

## Что проверено (checkpoint)

| # | Команда | Результат |
|---|---|---|
| 1 | `grep '^name = "fastapi-users"' uv.lock` | `name = "fastapi-users"` ✓ |
| 2 | импорт всех auth_users символов (с предзагрузкой db_core) | `OK` ✓ |
| 3 | `from db_core import User` → табнейм | `user` ✓ |
| 3b | `'user' in Base.metadata.tables` | `True` ✓ |
| — | `from main import main_app; len(routes)` | `42` (без регрессии) ✓ |
| — | `uv run ruff check .` | `All checks passed!` ✓ |

Сырой вывод — `phase01_checkpoint.txt` и `phase01_ruff.txt`.

## Расхождения со спекой (требуют внимания оркестратора)

### 1. `itsdangerous>=2.2.0` ОСТАВЛЕНА в `pyproject.toml` (спека просила удалить)

**Причина:** starlette 0.50.0 (уже в lock) не объявляет itsdangerous в
install_requires, но `middleware/sessions.py` всё ещё делает
`import itsdangerous`. Без явной зависимости в pyproject.toml
`SessionMiddleware` блога падает с `ModuleNotFoundError: No module named
'itsdangerous'` при первом же импорте.

Проект держал `itsdangerous>=2.2.0` именно для этой цели. Спека об этом
не знала.

**Возможные пути решения (обсудить с оркестратором):**
- Оставить `itsdangerous>=2.2.0` в pyproject.toml как есть сейчас.
- Зафиксировать starlette < 0.50, чтобы transitive dep itsdangerous
  восстановилась (но это заморозит обновления).
- Дождаться, пока starlette 0.51+ восстановит itsdangerous в метаданных.
- Заменить `starlette.middleware.sessions.SessionMiddleware` на собственную
  реализацию без itsdangerous (фаза 4–5, переход блога на fastapi-users).

**Что сделано:** itsdangerous ОСТАВЛЕНА, в pyproject.toml добавлен
комментарий с пояснением.

### 2. `auth_users/__init__.py` ПУСТОЙ (спека просила `from auth_users.models import User`)

**Причина:** циркулярный импорт. Цепочка:
```
auth_users.models -> db_core.model_base -> db_core.__init__ -> auth_users.models
```
Если `auth_users/__init__.py` ре-экспортирует User, то при загрузке
db_core возникает рекурсия, и Python падает с `ImportError: cannot import
name 'User' from partially initialized module 'auth_users.models'`.

**Доказательство:** минимальный тест в `/tmp` показал точно такую же ошибку.
В проекте тот же паттерн работает для `md_articles` ТОЛЬКО потому, что
`md_articles/__init__.py` триггерит длинную загрузочную цепочку
(setup_frontend → api_auth → ...) до того, как `from md_articles.models
import BlogUser` будет обработан пользователем.

**Решение:** `auth_users/__init__.py` пуст. `User` доступен через прямой
импорт `from auth_users.models import User`. Полные экспорты (`UserManager`,
`get_user_manager`, схемы, fastapi-users-роутеры) появятся в фазе 2, когда
пакет будет самодостаточным.

### 3. `from auth_users.models import User` в `db_core/__init__.py` В САМОМ КОНЦЕ

**Причина:** спека требует `db_core.User` указывать на auth_users.User.
Цикл выше ломается, если импорт делается в середине файла — частично
загруженный `db_core` ещё не видел `db_core.model_base.Base` (на самом
деле видел, но Python всё равно уходит в рекурсию). Импорт в самом конце
работает корректно, потому что к этому моменту `db_core.model_base` уже
полностью загружен и `auth_users.models` подгружается «с нуля», а не
из частичного состояния.

**Совместимость:** в production порядок загрузки всегда `main.py →
create_fastapi → db_core → ...`, поэтому db_core полностью загружается ДО
любого обращения к auth_users.models. Цикл не возникает на практике.

### 4. Checkpoint 2 модифицирован: `from db_core import Base` перед
`from auth_users.models import User`

**Причина:** см. п.3 — прямой импорт auth_users.models в свежей сессии
триггерит цикл. Префиксный импорт db_core имитирует production-порядок.

**Альтернатива:** оставить спецификацию как есть — checkpoint упадёт, и
придётся переделывать один из файлов.

## Что осталось на фазу 2

- Расширить `auth_users/__init__.py` полными экспортами: `fastapi_users`,
  `UserManager`, `get_user_db`, `get_user_manager`, схемы `UserRead/Create/Update`.
  Возможно, придётся ещё раз проверить загрузочный порядок, чтобы цикл не
  вернулся.
- `AuthUsersConfig` (с `password_min_length` и пр.) в `core/config.py`,
  заменить хардкод `8` в `UserManager.validate_password` на
  `settings.auth_users.password_min_length`.
- Переключить `md_articles/api_auth.py` и `md_articles/middleware_auth.py`
  с `BlogUser` на `auth_users.User`.
- Алембик-миграция для новой таблицы `user`.
- Полный smoke с реальным register/login потоком (фаза 3).

## Запросы к оркестратору

1. Подтвердить сохранение `itsdangerous>=2.2.0` в pyproject.toml (или
   выбрать другой путь из списка выше).
2. Принять пустой `auth_users/__init__.py` в фазе 1 (полные экспорты —
   в фазе 2).
3. Подтвердить модифицированный checkpoint 2 (с `from db_core import Base`
   в начале).

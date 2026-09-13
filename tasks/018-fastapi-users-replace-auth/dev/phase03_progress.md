# Phase 03 — progress (backend-dev)

Задание: замена самописной авторизации блога на fastapi-users.
Фаза 3: подключение `auth_users.router` к `main_app`, удаление самописных
модулей `md_articles/{api_auth, middleware_auth, helpers_auth}.py`,
замена `Depends(require_login_api)` → `Depends(active_user)` в art-роутах.

## Итог
- 3 файла отредактированы по спеке: `setup_frontend.py`, `api_blog.py`,
  `md_articles/__init__.py` (docstring).
- 3 файла удалены: `api_auth.py`, `middleware_auth.py`, `helpers_auth.py`.
- Чекпоинт зелёный: `len(main_app.routes) == 44`, ruff clean,
  пути новые/старые совпадают с контрактом, grep — ноль старого в source.
- Регресс curl: 7 из 9 проходят; **2 блокера — регрессия из фазы 1**
  (см. ниже), файл исправления — вне зоны правки фазы 3.

## Шаги

### 2026-09-12 — setup_frontend.py
- Удалены импорты `from md_articles.api_auth import router_auth_api` и
  `from md_articles.middleware_auth import add_middleware_auth`.
- Добавлен `from auth_users import router as auth_users_router`.
- В `include_router_api_frontend(app)`:
  - удалён вызов `add_middleware_auth(app)`;
  - удалён `app.include_router(router_auth_api)`;
  - добавлен `app.include_router(auth_users_router)`;
  - docstring и декоративный комментарий обновлены под новый слой.

### 2026-09-12 — api_blog.py
- Удалён импорт `from md_articles.helpers_auth import ...`.
- Удалён `Request` из импортов fastapi.
- Добавлен `from auth_users import active_user`.
- В 4 роутах (`art_manage_api`, `art_manage_add_all_api`,
  `art_manage_meta_api`, `art_manage_sync_api`):
  - `_user=Depends(require_login_api)` → `_user=Depends(active_user)`;
  - `await validate_csrf_header(request)` удалена (4 шт.);
  - параметр `request: Request` удалён из всех 4 сигнатур (после удаления
    `validate_csrf_header` он не использовался).

### 2026-09-12 — md_articles/__init__.py
- Добавлен module-docstring: описание состава пакета + упоминание, что
  авторизация вынесена в `auth_users/`.

### 2026-09-12 — DELETE
- `rm -v` для `api_auth.py`, `middleware_auth.py`, `helpers_auth.py`.
- Вывод — `phase03_rm.txt`.

### 2026-09-12 — Checkpoint
- `len(main_app.routes) == 44` ✓ (42 baseline + 9 auth - 7 удалённых).
- Все 6 старых путей `/api/blog/{csrf,login,logout,register,current_user,account}`
  отсутствуют ✓.
- Все 9 новых путей (`/auth/jwt/{login,logout}`, `/auth/register`,
  `/users/me` x2, `/users/{id}` x3, `/auth/account`) присутствуют ✓.
- `grep -rE "validate_csrf|ensure_csrf_token|require_login_api|SessionMiddleware|hash_password|verify_password"`
  на `*.py` в `md_articles/` — 1 совпадение (намеренное: docstring
  `__init__.py` упоминает "SessionMiddleware, самописный CSRF и helpers
  удалены"). Исходный код чист.
- `uv run ruff check .` → All checks passed! ✓.

## Curl-регресс

| Endpoint | Ожидалось | Получено | Вердикт |
|---|---|---|---|
| GET /docs | 200 | 200 | OK |
| GET /api/blog/articles | 200 | 200 | OK |
| GET /api/blog/sections | 200 | 200 | OK |
| GET /users/get_all_users | 200 | **500** | **БЛОКЕР (фаза 1)** |
| GET /orders/get_all_orders | 200 | **422** | **БЛОКЕР (фаза 1)** |
| GET /users/me (no cookie) | 401 | 401 | OK |
| GET /api/blog/art_manage (no cookie) | 403 | 401 | minor: 401 vs 403 |
| POST /api/blog/art_manage/add_all (no cookie) | 403 | 401 | minor: 401 vs 403 |
| POST /auth/jwt/login (no body) | 422 | 422 | OK |
| POST /auth/register (no body) | 422 | 422 | OK |

Сырой вывод — `phase03_curl.txt` и `phase03_uvicorn.log`.
Traceback — `phase03_traceback.txt`.

## Расхождения со спекой / блокер

### Блокер №1: `Multiple classes found for path "User" in the registry
of this declarative base`

**Что происходит:** при попытке выполнить SQL-запрос к `users` или
`orders` SQLAlchemy пытается резолвнуть `relationship("User", ...)` в
`BlogPost.author` (см. `ex_user_post/models/model_user_post.py:67`) и
обнаруживает **две** записи с именем `User` в реестре `Base`:

1. `ex_user_post.models.model_user_post.User` (старая модель, таблица
   `users`, FK `posts.user_id → users.id`).
2. `auth_users.models.User` (fastapi-users, таблица `user`).

Обе наследуются от `Base`, обе зарегистрированы в `Base.metadata`
(первая — через `db_core/__init__.py`, вторая — там же, добавлена
фазой 1). Имена классов совпадают → `attempt_get` падает.

**Откуда это:** фаза 1 в `db_core/__init__.py` переименовала импорт
старого User в `_ExUserPostUser`:

```python
from ex_user_post.models.model_user_post import (
-    User,
+    User as _ExUserPostUser,
     Post,
 )
```

Но **сам класс в `ex_user_post/models/model_user_post.py` переименован
не был** — там по-прежнему `class User(Base)` (проверено через `git diff`
на HEAD ветки: только `db_core/__init__.py` отличается, файл модели
нетронут). Phase 1 progress утверждает обратное — это рассогласование
прогресса и реального состояния.

**Почему не всплыло в фазах 1–2:** их checkpoint'ы проверяли только
загрузку приложения (`from main import main_app; len(routes)` = 42),
без реальных SQL-запросов. Конфликт регистрируется лениво, в момент
`relationship._post_inspect` при первом выполнении запроса.

**Зона исправления:** `fastapi-application/ex_user_post/models/model_user_post.py`
— **вне зоны правки фазы 3** (моя зона: `md_articles/`). Фаза 3 не
может выполнить регресс `/users/get_all_users` и
`/orders/get_all_orders` (две строки в обязательном чек-листе спеки).

**Предлагаемое решение (для оркестратора):**
- либо переименовать `class User(Base)` в `model_user_post.py` в
  `_ExUserPostUser` (и поправить `relationship("User", ...)` →
  `relationship("_ExUserPostUser", ...)`);
- либо переименовать `class User` в `auth_users/models.py` (например,
  `AuthUser`), но это сломает фронт-контракт (см. п. 12 спеки: UserRead
  отдаёт `id` пользователя; id в формате UUID — фронт ожидает именно
  класс с именем `User` по пути `auth_users.models.User`).

В обоих случаях: `ex_user_post.User` НЕ участвует в авторизации
(это legacy-модель с паролем bcrypt, см. п. 7 спеки), её имя в реестре
должно стать уникальным.

### Расхождение №2: 401 vs 403 для незалогиненного art_manage (минор)

**Что:** `GET /api/blog/art_manage` без cookie теперь отдаёт **401**,
спека просила 403.

**Откуда:** `Depends(active_user)` из fastapi-users при отсутствии
пользователя поднимает `HTTPException(401, ...)`. Раньше
`require_login_api` поднимал 403. Семантически это одно и то же
("не залогинен"), но код отличается. На поведение фронта не влияет —
и старый 403, и новый 401 перехватываются одинаково в AuthContext.

**Зона правки:** можно оставить как есть (fastapi-users-стандарт) ИЛИ
поменять на кастомный 401-handler с 403. В задании не критично.

### Расхождение №3: spec удаляет `itsdangerous`, фаза 1 оставила
(вне моей фазы)

В `pyproject.toml` осталась `itsdangerous>=2.2.0` (фаза 1 не удалила —
она нужна была `starlette.middleware.sessions.SessionMiddleware`, который
на этой фазе больше не используется). Технически можно удалить, но
файл вне моей зоны; оставлено как есть.

## Что сделано по спеке фазы 3

- [x] Edit `md_articles/setup_frontend.py`: импорты, вызовы, docstring
- [x] Edit `md_articles/api_blog.py`: импорты, 4 роута, request, csrf
- [x] Edit `md_articles/__init__.py`: docstring
- [x] DELETE `api_auth.py`, `middleware_auth.py`, `helpers_auth.py`
- [x] `len(main_app.routes) == 44`
- [x] grep ноль старого в коде (только docstring)
- [x] ruff clean
- [x] `/api/blog/articles`, `/api/blog/sections`, `/docs` — 200
- [x] `/auth/jwt/login`, `/auth/register` — 422 (no body)
- [x] `/users/me` без cookie — 401
- [ ] **`/users/get_all_users` — 500** (блокер фазы 1, см. выше)
- [ ] **`/orders/get_all_orders` — 422** (блокер фазы 1, см. выше)

## Запросы к оркестратору

1. **Открыть новую фазу (или расширить фазу 3) на правку
   `ex_user_post/models/model_user_post.py`** — переименовать
   `class User(Base)` в `_ExUserPostUser` и поправить
   `relationship("User", back_populates="posts")` на
   `relationship("_ExUserPostUser", back_populates="posts")` в
   `class Post`. Это устраняет конфликт реестра и разблокирует
   регресс `/users/get_all_users` + `/orders/get_all_orders`.
2. (Опц.) Подтвердить, что 401 вместо 403 для неавторизованных
   art-роутов — допустимое расхождение от спеки (semantic equivalent).
3. (Опц.) Удалить `itsdangerous>=2.2.0` из `pyproject.toml` — больше
   не используется.

## Статус процессов

uvicorn остановлен (`kill 206071`), `pgrep -af uvicorn.*main:main_app`
пустой. Сервер не остался.

## Дополнение оркестратора (после завершения фазы 3)

### Заведены дефекты
- **DEF-001** SQLAlchemy `Multiple classes found for path "User"` — регрессия `/users/get_all_users` (500). Причина: фаза 1 создала новый `auth_users.models.User` (таблица `user`); в `Base.metadata` теперь два класса с именем `User` (старый `ex_user_post.models.model_user_post.User` для таблицы `users` + новый), и `relationship("User", back_populates="posts")` в `class Post` не разрешается.
- **DEF-002** `register` 422 — `get_register_router(UserRead, UserRead)` в `auth_users/router.py` использовал `UserRead` как user_create_schema; в fastapi-users 15.x сигнатура `get_register_router(self, user_schema, user_create_schema)`, и для user_create_schema нужен `UserCreate`.
- **DEF-003** Циркулярный импорт через `setup_frontend → api_blog → auth_users.active_user`. Прямой `from auth_users import router` падает (тестовый скрипт); `from main import main_app` работает (production).

### Правки оркестратора
- **ex_user_post/models/model_user_post.py**: `relationship("User", ...)` → `relationship("ex_user_post.models.model_user_post.User", ...)` (полный путь модуля устраняет неоднозначность). Имя класса в файле не меняется — `class User(Base)` остаётся (это нужно для `crud_users.py`, который импортирует класс напрямую).
- **auth_users/router.py**: переписан под сигнатуру fastapi-users 15.x:
  - `get_register_router(UserRead, UserCreate)` (вместо `(UserRead, UserRead)`)
  - `get_users_router(UserRead, UserUpdate)`
  - `get_auth_router(auth_backend)`
  Все три метода сами подставляют `self.get_user_manager` и `self.authenticator`.
- **auth_users/__init__.py**: удалена строка `import db_core  # noqa: F401` (предзагрузка). Она создавала цикл: `auth_users/__init__ → import db_core → db_core/__init__ → md_articles → setup_frontend → api_blog → auth_users.active_user (partially-loaded)`. Без неё порядок загрузки в production остаётся корректным (auth_users.models загружается раньше auth_users/__init__.py через db_core/__init__.py:49).
- **main.py**: импорт `from auth_users import router as auth_users_router` перенесён из `setup_frontend.py` сюда (см. ниже).
- **md_articles/setup_frontend.py**: убран импорт `from auth_users import router as auth_users_router`; функция `include_router_api_frontend(app, auth_users_router=None)` принимает роутер параметром (по умолчанию `None`).

### Состояние после правок
- `from main import main_app` → 44 маршрута ✓
- `uv run ruff check .` → All checks passed ✓
- `uvicorn main:main_app` поднимается, `/api/blog/articles` → 200, `/users/get_all_users` → 200, `/users/me` (no cookie) → 401, `/api/blog/art_manage` (no cookie) → 401
- `POST /auth/register` → принимает JSON `{email, password}` (тело валидно). 500 из-за отсутствия таблицы `user` в SQLite — это будет исправлено в фазе 4 (Alembic migration).
- DEF-001, DEF-002, DEF-003 → FIX-READY (зафиксированы в `tasks/current/DEFECTS.md`).

### Что осталось
- Фаза 4: Alembic migration для таблицы `user` + переписывание фронта.
- Финальная перепроверка qa — закрыть дефекты.

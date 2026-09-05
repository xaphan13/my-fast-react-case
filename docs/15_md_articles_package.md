# 15. Пакет `md_articles`: JSON API блога, реестр статей, сессии

Этот документ — обзор всего пакета `fastapi-application/md_articles/`:
из каких модулей он состоит, как подключается к приложению, какие у него
контракты с фронтендом и где граница между блогом и остальным FastAPI.

Смежные документы:
- [`docs/11_md_articles.md`](11_md_articles.md) — общий обзор пакета блога
  с точки зрения фич.
- [`docs/14_create_fastapi_factory.md`](14_create_fastapi_factory.md) —
  место `setup_auth_static_include` в общем каркасе приложения
  (вызывается из `main.py`).
- [`docs/12_fastapi_react_integration.md`](12_fastapi_react_integration.md) —
  как SPA получает данные блога через `/api/blog`.

## 1. Состав пакета

```
md_articles/
├── __init__.py                    # публичный API пакета (реэкспорт setup_auth_static_include)
├── frontend_auth_include.py       # plug-in: setup_auth_static_include(app) — middleware + static + JSON API
├── auth_middleware_helpers.py     # вся авторизация: auth_add_middleware, current_user-middleware,
│                                  #   CSRF-хелперы, hash_password/verify_password, require_login_api
├── api_blog.py                    # JSON-роутер /api/blog/* (13 эндпоинтов)
├── schema_art.py                  # pydantic ArticleLang + YAML-реестр с mtime-кэшем
├── models.py                      # SQLAlchemy: BlogUser, BlogPost
└── articles.yaml                  # реестр статей (правит пользователь и фронт через /art_manage)
```

| Файл | Зона | Что внутри |
|---|---|---|
| `__init__.py` | публичный API | реэкспорт `setup_auth_static_include` |
| `frontend_auth_include.py` | plug-in | `setup_auth_static_include(app)` — подключает блог к FastAPI |
| `auth_middleware_helpers.py` | безопасность | `auth_add_middleware(app)`, `inject_current_user_middleware`, CSRF-хелперы, `login_user`/`logout_user`, `hash_password`/`verify_password` (bcrypt), `require_login_api` |
| `api_blog.py` | API | роутер `router_blog_api` (prefix `/api/blog`), pydantic-схемы запросов/ответов, `_user_out` (формат JSON-ответа) |
| `schema_art.py` | данные | модель `ArticleLang`, чтение/запись `articles.yaml` с mtime-кэшем, рендер `.md` через `markdown()`, сканирование `content_art/` |
| `models.py` | данные | `BlogUser`, `BlogPost` (SQLAlchemy 2.0, попадают в `Base.metadata` для Alembic) |

## 2. Точка входа — `frontend_auth_include.py`

Публичный API пакета — единственная функция `setup_auth_static_include(app)`,
реэкспортированная в `md_articles/__init__.py`. Вызывается из `main.py` после
доменных `include_router` и до `setup_react_routing_assets(main_app)`.

`setup_auth_static_include` делает три вещи в строгом порядке:

1. `auth_add_middleware(app)` — подключает всю авторизацию: `SessionMiddleware`
   (подписанные cookie, 14 дней), `inject_current_user_middleware` и обработчик
   `RequestValidationError` для формата `{"errors": {field: [msgs]}}`.
2. `app.mount("/static", StaticFiles(...))` — аватары из
   `BASE_DIR/static/profile_pics/`. `check_dir=False` (аналогично `frontend_routing.py`)
   позволяет стартовать без каталога.
3. `app.include_router(router_blog_api)` — JSON-роутер блога.

## 3. `inject_current_user_middleware` — почему middleware, а не Depends

`request.state.current_user` нужен **всем** обработчикам блога:
`/api/blog/articles` (проверить, что редактирует авторизованный),
`/api/blog/current_user` (вернуть профиль), `account_get` (отдать форму),
`/art_manage` (требует логина) и даже `custom_request_validation_exception_handler`
(может читать current_user для контекстных сообщений).

Middleware решает три задачи:

- **Один раз на запрос.** Сессия БД открывается короткая
  (`async with db_manager.session_factory()`), `BlogUser` достаётся
  по `request.session['user_id']` и кладётся в `request.state`.
  Роуты дальше работают с `request.state.current_user` — без
  повторного `await session.execute(select(BlogUser...))`.
- **Анонимный пользователь = `None`.** Если `user_id` в сессии
  нет, middleware кладёт `None` в state. Роуты проверяют
  `_get_request_user(request) is None` и отдают 403, а не
  `AttributeError`.
- **Минус одна зависимость в сигнатуре каждого эндпоинта.**
  `Depends(get_current_user)` исчезает из роутов блога, что
  делает сигнатуры короче и понятнее.

## 4. JSON API — `api_blog.py`

Роутер `router_blog_api` живёт под префиксом `/api/blog`, тег `blog api`.
13 эндпоинтов, сгруппированных по задачам:

| Группа | Эндпоинты |
|---|---|
| Сессия и профиль | `GET /csrf`, `GET /current_user`, `POST /register`, `POST /login`, `POST /logout` |
| Аккаунт | `GET /account`, `POST /account` (multipart: username + email + picture + csrf_token) |
| Контент | `GET /sections`, `GET /articles`, `GET /articles/{art_id}` |
| Управление (требует логина) | `GET /art_manage`, `POST /art_manage/add_all`, `POST /art_manage/meta` |

### 4.1. Сессия и профиль

- `GET /csrf` — выдаёт (или создаёт в сессии) `csrf_token: str`. Все
  мутирующие эндпоинты (`register`, `login`, `logout`, `account POST`,
  `art_manage/*`) требуют заголовок `X-CSRF-Token: <значение из /csrf>`
  (для form-based `/account` — поле `csrf_token`).
- `GET /current_user` — `{"user": null}` для анонима, иначе
  `{"user": {...}}` (без `password`, через `_user_out`).
- `POST /register` — валидация длины username/email, уникальность,
  совпадение паролей. Возвращает 422 с `{"errors": {...}}` при
  ошибках, иначе JSON-сообщение об успехе (без auto-login — пользователь
  отдельно шлёт `POST /login`).
- `POST /login` — сверяет email + bcrypt-хэш, в случае успеха
  `login_user(request, user.id)` кладёт `user_id` в сессию, возвращает
  `{"user": {...}}`.
- `POST /logout` — `logout_user(request)` стирает `user_id` из сессии.

### 4.2. Аккаунт

- `GET /account` — отдаёт профиль текущего пользователя, требует логина
  (иначе 403). Используется фронтом для предзаполнения формы.
- `POST /account` — multipart: `username`, `email`, опционально
  `picture: UploadFile` (PIL ресайз до 125×125, сохранение в
  `static/profile_pics/<random>.<ext>`), и `csrf_token` (поле формы,
  а не заголовок). CSRF тут через `validate_csrf_form`, а не
  `validate_csrf_header`, потому что это `multipart/form-data`.

### 4.3. Контент

- `GET /sections` — список непустых разделов. Раздел = имя первой
  папки в пути файла (`get_section(file_name)` в `schema_art.py`).
  Считаются только «полные» статьи (есть author, lang, title).
- `GET /articles?section=...` — список статей (тоже только полные).
  Опциональный query-параметр `section` фильтрует по разделу.
  Контент в список не включается (только метаданные).
- `GET /articles/{art_id}` — полный контент одной статьи. Если
  файл на диске пропал — 404 (а не 500 с `FileNotFoundError`).
  Markdown рендерится через `markdown(content, extensions=["fenced_code", "tables"])`;
  подсветка синтаксиса — клиентская, через `highlight.js` (см. frontend).

### 4.4. Управление (требует логина)

- `GET /art_manage` — дашборд для редактора: полный реестр
  (включая неполные записи), список незарегистрированных `.md`-файлов
  на диске, список «потерянных» записей (файл удалён, а YAML-ссылка
  осталась), и текст ошибки YAML, если реестр сейчас не парсится.
- `POST /art_manage/add_all` — добавляет в реестр все `.md`-файлы
  из `content_art/`, которых ещё нет в YAML. `art_id` выделяется через
  `int(time.time())` + инкремент до уникальности (`_allocate_art_id`).
- `POST /art_manage/meta` — добавить/обновить запись для одного файла
  (file_name, author, lang, title). Если `file_name` нет ни на диске,
  ни в реестре — 422.

## 5. CSRF и кастомный 422

### Почему CSRF

Cookie-сессии уязвимы к CSRF: браузер автоматически шлёт cookie на
`/api/blog/*`, даже если запрос инициирован со стороннего сайта. Без
защиты злоумышленник мог бы заставить браузер пользователя отправить
`POST /api/blog/account` от его имени.

Защита — двойная: cookie-флаг `SameSite=Lax` (включён Starlette по
умолчанию) + явная проверка CSRF-токена. Токен создаётся в сессии
при первом `GET /csrf`; клиент передаёт его в `X-CSRF-Token` (для
JSON-эндпоинтов) или в поле формы `csrf_token` (для multipart
`/account`). Сервер сверяет header/form с сессией, и при несовпадении
отдаёт 403 `{"detail": "CSRF token mismatch"}`.

### Кастомный 422

Стандартный ответ FastAPI на `RequestValidationError` —
`{"detail": [...]}` со списком ошибок. Это неудобно для форм: фронт
хочет `{"errors": {"email": ["Invalid email"], "password": [...]}}`,
чтобы подсветить конкретные поля.

`custom_request_validation_exception_handler` в `api_blog.py` ловит
только пути `/api/blog/*` и переписывает формат для них; для остальных
маршрутов делегирует стандартному обработчику FastAPI.

## 6. `schema_art.py` — реестр статей с mtime-кэшем

Статьи — это `.md`-файлы в `content_art/` + записи в
`articles.yaml` (file_name, author, lang, art_id, title, section).
Реестр читается лениво и кэшируется по `(mtime_ns, size)`:

```python
def get_articles() -> list[ArticleLang]:
    stat = articles_path.stat()
    current_key = (stat.st_mtime_ns, stat.st_size)
    if _last_stat == current_key:
        return _registry_cache
    ...
```

Что это даёт:

- **Без нагрузки на диск.** Запросы `/api/blog/articles` не парсят
  YAML каждый раз — только если файл реально изменился.
- **Атомарная запись.** `save_articles` пишет во временный файл
  `.articles_<rand>.yaml.tmp` в той же директории, затем
  `os.replace` (атомарно на одной ФС) подменяет основной файл.
  При ошибке tmp-файл удаляется. На середине записи файл всегда
  валиден (либо старый, либо новый).
- **Устойчивость к ошибкам YAML.** Если YAML сломан, `_registry_error`
  заполняется, `_last_stat = None` (форсирует перечитку), а
  `_registry_cache` остаётся прежним — фронт продолжает видеть
  данные, а в `/art_manage` появляется `yaml_error` для редактора.

`render_article` рендерит `.md` через библиотеку `markdown` с
расширениями `fenced_code` (```-блоки) и `tables` (GFM-таблицы).
Подсветка синтаксиса отдаётся клиенту (`highlight.js` в
`frontend/index.html`).

`scan_content_art` рекурсивно обходит `content_art/` и возвращает
список относительных POSIX-путей `.md`/`.markdown` файлов. Имя
первой папки в пути = раздел (для корневых файлов — пустая строка).

## 7. `models.py` — `BlogUser`, `BlogPost`

SQLAlchemy 2.0 в стиле проекта (`Mapped[]` + `mapped_column` +
переиспользуемые `Annotated`-типы из `db_core.type_for_models.py`).

- `BlogUser`: `username` (unique, ≤20), `email` (unique, ≤120),
  `image_file` (default `"default.jpg"`), `password` (bcrypt-хэш, ≤60).
  `relationship` к `BlogPost` через `back_populates="posts"` +
  `cascade="all, delete-orphan"`.
- `BlogPost`: `title`, `date_posted` (UTC по умолчанию), `content` (Text),
  `user_id` (FK на `blog_user.id`).

`__tablename__` генерируется автоматически (`CamelCase` →
`snake_case`), поэтому `BlogUser → blog_user`, `BlogPost → blog_post`.

`BlogUser` реэкспортируется в `db_core/__init__.py` (неявно через
`from .md_articles.models import BlogUser, BlogPost` в `__init__` —
или явный импорт в `db_core`); иначе Alembic не увидит таблицу при
`--autogenerate`.

Атрибут `is_authenticated` оставлен на объекте пользователя как стандартное
свойство (Boolean, всегда `True` для реального объекта) — фронтенд-формы
ожидают такой атрибут на сущности «пользователь». В React-фронте это не
используется — фронт ориентируется на наличие/отсутствие `user` в
`GET /current_user`.

## 8. `auth_middleware_helpers.py` — auth-хелперы

```python
async def get_current_user(request, session) -> BlogUser | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        request.state.current_user = None
        return None
    result = await session.execute(select(BlogUser).where(BlogUser.id == user_id))
    user = result.scalar_one_or_none()
    request.state.current_user = user
    return user
```

Несмотря на имя, `get_current_user` используется **только** из
`inject_current_user_middleware` (как callback), а не как `Depends`.
Роуты читают `request.state.current_user` напрямую (через
`_get_request_user(request)` в `api_blog.py`).

`login_user` / `logout_user` — обёртки над `request.session[]`,
вынесены для читаемости и возможности заменить backend (например,
на JWT-cookie).

`hash_password` / `verify_password` — тонкие обёртки над `bcrypt`.
`bcrypt.gensalt()` по умолчанию даёт соль нужной сложности;
`bcrypt.checkpw` сам извлекает соль из хэша.

Файл также содержит CSRF-хелперы (`_ensure_csrf_token`,
`validate_csrf_header`, `validate_csrf_form`), зависимость
`require_login_api` (403 JSON для не-залогиненных), и кастомный
обработчик `RequestValidationError` для формата `{"errors": ...}`.

## 9. Поток типичного запроса

`GET /api/blog/articles?section=Rust` (анонимный пользователь):

1. Запрос приходит в ASGI-приложение.
2. `SessionMiddleware` поднимает `request.session` (пустой для анонима).
3. `inject_current_user_middleware` открывает сессию БД, вызывает
   `get_current_user`: `user_id` нет в сессии → `request.state.current_user = None`.
4. Срабатывает роут `articles_list`: `get_articles()` (mtime-кэш →
   возврат из кэша), фильтрация по `section`, сериализация через
   `jsonable_encoder` → JSON.
5. Middleware закрывает сессию БД, ответ уходит.

`POST /api/blog/login`:

1. Клиент предварительно вызвал `GET /csrf` — токен в сессии.
2. Клиент шлёт JSON `{email, password, remember}` + заголовок
   `X-CSRF-Token: <token>` + cookie сессии.
3. `SessionMiddleware` поднимает сессию (с CSRF-токеном).
4. `inject_current_user_middleware` кладёт `current_user` в state.
5. `login_api` → `validate_csrf_header` сверяет заголовок с сессией →
   `select BlogUser where email = ?` → `verify_password` →
   `login_user(request, user.id)` записывает `user_id` в сессию →
   ответ `{"user": {...}}`.

## 10. Что не относится к пакету

- **Сами `.md`-файлы** живут в `fastapi-application/content_art/`
  (не в `md_articles/`). Пакет только читает/рендерит их; класть
  контент внутрь пакета — лишнее связывание.
- **Аватары** — в `fastapi-application/static/profile_pics/`. Пакет
  отдаёт их через `mount('/static', ...)` в `frontend_auth_include.py`, но не
  управляет файлами (загрузка/ресайз — в `api_blog._save_picture`).
- **React-фронт** обращается к блогу через `/api/blog/*`. Контракт
  схем и формат ошибок — это «API-документация», которая
  автоматически доступна в `/docs` (Swagger UI показывает все 13
  роутов с их pydantic-схемами).

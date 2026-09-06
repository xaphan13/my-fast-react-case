# 01. Карта проекта

> Часть 1 из 4. См. также: [02_architecture.md](02_architecture.md), [03_execution_flow.md](03_execution_flow.md), [04_code_quality.md](04_code_quality.md)

## Назначение

`my-fastapi-one` — **учебно-демонстрационный проект на FastAPI 0.111+ / Python 3.12**, построенный как исполняемый каталог приёмов, а не как продуктовый сервис. Основная масса кода существует, чтобы показать варианты одного и того же решения рядом друг с другом: четыре способа извлечения параметров HTTP-запроса, девять способов внедрения зависимостей (`Depends`), два стиля объявления pydantic-полей (`Field` против `Annotated`), два способа валидации (`AfterValidator` против `field_validator`) и два способа разбора результата SQLAlchemy `joinedload`.

Вторая, меньшая часть проекта — рабочий асинхронный слой данных на SQLAlchemy 2.0 (`AsyncSession`, `asyncpg`/`aiosqlite`) с миграциями Alembic и двумя предметными областями: `User`/`Post` (one-to-many) и `Order`/`Product` (many-to-many с явной ассоциативной моделью). Эта часть пригодна как основа для реального сервиса, но требует доработок, перечисленных в [04_code_quality.md](04_code_quality.md).

**Что важно понимать перед работой с кодом:** дублирование маршрутов и обработчиков здесь **намеренное**. Четыре файла `api/my_routes_dep/my_param_*.py` реализуют один и тот же эндпоинт `/my_items/{item_id}` с идентичной семантикой — сравнивать их построчно и есть цель. Не «рефакторьте» это в общий код, не выяснив задачу.

---

## Дерево директорий

```
my-fastapi-one/
├── docs/                            # Эта документация
├── QWEN.md                          # Контекст проекта + оркестратор команды агентов (главная сессия)
├── AGENTS.md                        # Контекст проекта + правила команды агентов, зоны/проверки
├── README.md                        # Обзор проекта + описание агентного режима
├── tasks/                           # Задания команды агентов
│   └── current/REQUIREMENTS.md      # Текущее задание + рабочие артефакты (e2e/, DEFECTS.md, ...)
│                                   # Закрытые задания архивируются в tasks/NNN-<slug>/ с отчётом
├── .qwen/agents/                    # Субагенты: frontend-dev, backend-dev, qa, adversary
├── frontend/                        # Отдельное React-приложение блога (свой npm-проект;
│   │                                # dist/ не коммитится, FastAPI раздаёт сборку)
│   ├── package.json                 # react 18.3, react-router-dom 6.30; vite 6, tailwind 4.1
│   ├── index.html                   # hljs с CDN (SRI), 15 тёмных тем подсветки, анти-вспышка темы
│   ├── vite.config.ts               # dev :5173, прокси /api и /static → :8000
│   └── src/
│       ├── api/                     # client.ts (fetch + CSRF), blog.ts, auth.ts, artManage.ts
│       ├── components/              # Layout, Header, SectionMenu, ArticleCard, MarkdownContent,
│       │                            # Pagination, Toast, SidePanel, ArtManageForms, селекторы тем
│       ├── context/AuthContext.tsx  # текущий пользователь (GET /api/blog/current_user)
│       ├── hooks/                   # useTheme, useHljsTheme (localStorage)
│       ├── pages/                   # Home (+ /section/:name), Article, About, Login, Register,
│       │                            # Account, ArtManage
│       └── types.ts                 # User, Article, Section — типы контракта /api/blog
├── templates_qwen_agents/           # Комплект агентного режима из другого проекта — только пример
├── fastapi-application/             # Корень Python-приложения (= BASE_DIR)
│   ├── main.py                      # Точка входа uvicorn; сборка main_app из роутеров + mount_vite_react_assets()
│   ├── setup_frontend.py              # Подключение собранного React: mount /assets + SPA catch-all
│   ├── main_gunicorn.py             # Точка входа gunicorn; переиспользует main_app
│   ├── create_fastapi.py            # Фабрика приложения create_app() + lifespan (без блога — блог подключается в main.py)
│   ├── base_dir_path.py             # DIR_CWD / BASE_DIR (Path)
│   ├── config_log.py                # Автономная подсистема логирования (dictConfig)
│   ├── alembic.ini                  # Конфиг Alembic; post-write hook = black -l 79
│   ├── one.env                      # Профиль PostgreSQL (закоммичен в git)
│   ├── two.env                      # Профиль SQLite (активен по умолчанию)
│   │
│   ├── core/
│   │   ├── config.py                # Settings(BaseSettings) — весь конфиг приложения
│   │   └── gunicorn/
│   │       ├── gunicorn_app.py      # MyGunicornApp(BaseApplication)
│   │       ├── gunicorn_opt.py      # get_app_options() → dict опций gunicorn
│   │       └── gunicorn_log.py      # GunicornLogger(Logger) — свой формат логов
│   │
│   ├── db_core/                     # Инфраструктура БД, не зависит от предметных областей
│   │   ├── __init__.py              # Реэкспорт Base + всех моделей (нужен Alembic)
│   │   ├── db_async.py              # AsyncDbManager, db_manager, CurrentSession
│   │   ├── model_base.py            # Base(DeclarativeBase) + автогенерация __tablename__
│   │   ├── type_for_models.py       # Annotated-типы колонок (int_primary_key и др.)
│   │   └── case_converter.py        # camel_case_to_snake_case()
│   │
│   ├── api/                         # Демонстрационная часть, версионируется под /api/v1
│   │   ├── __init__.py              # router_api (/api) → router_api_v1 (/v1)
│   │   ├── dependencies/            # МЕХАНИКА Depends: 9 роутов
│   │   │   ├── __init__.py          # router_dep_examples
│   │   │   ├── func_deps.py         # Фабрика зависимостей get_header_dependency()
│   │   │   ├── cls_deps.py          # Классы-зависимости: __call__, метод, генератор
│   │   │   ├── helper.py            # BaseGreat → GreatHelper / GreatService
│   │   │   ├── dep_examp_simple.py  # 4 роута: простые зависимости
│   │   │   └── dep_examp_cls.py     # 5 роутов: классовые зависимости
│   │   └── my_routes_dep/           # ИЗВЛЕЧЕНИЕ ПАРАМЕТРОВ: 4 стиля одного эндпоинта
│   │       ├── __init__.py          # router_param_extract + 4 префикса
│   │       ├── my_param_fast_cls.py    # Стиль 1: Path()/Query() как default-значения
│   │       ├── my_param_fast_ann.py    # Стиль 2: то же через Annotated
│   │       ├── my_param_dep_cls.py     # Стиль 3: параметры собраны в классы
│   │       ├── my_param_dep_func.py    # Стиль 4: параметры собраны в функции
│   │       ├── dep_cls_schema.py       # PathData/QueryData/HeaderData/CookieData
│   │       ├── dep_func_schema.py      # get_item_id/get_param_id/get_user_id/...
│   │       ├── pydantic_schema.py      # RespFieldStyle vs RespAnnotated
│   │       └── pydantic_validator.py   # RespAfterValid vs RespDecorValid
│   │
│   ├── ex_user_post/                # Домен User/Post — слоистая раскладка
│   │   ├── router_users.py          # r_users_sql (/users): 2 роута
│   │   ├── crud/crud_users.py       # get_all_users(), create_user()
│   │   ├── models/
│   │   │   ├── model_user_post.py   # User, Post (one-to-many)
│   │   │   ├── model_user_mix.py    # TestUser — НЕ подключён к Alembic
│   │   │   └── model_id_pk_mixin.py # IntIdPkMixin
│   │   └── schemas/schema_user.py   # UserCreate/UserResp, PostCreate/PostResp
│   │
│   ├── ex_order_product/            # Домен Order/Product — БЕЗ слоя CRUD
│   │   ├── router_order_one.py      # r_order_one (/orders): 6 роутов, SQL внутри
│   │   ├── model_order_product.py   # Order, Product, OrderProductAssociation
│   │   └── schema_order_product.py  # 20+ pydantic-схем, включая вложенные Resp
│   │
│   ├── md_articles/                 # Блог: JSON API /api/blog + реестр статей
│   │   ├── __init__.py              # include_router_api_frontend(): вызывается из main.py, не из create_app() — middleware, mount /static, роутер
│   │   ├── api_blog.py              # 13 JSON-эндпоинтов /api/blog (включая /sections) + CSRF + 422-хендлер
│   │   ├── schema_art.py            # ArticleLang (+section) + YAML-реестр (mtime-кэш, атомарная запись)
│   │   ├── models.py                # BlogUser / BlogPost (SQLAlchemy 2.0)
│   │   ├── auth_middleware_helpers.py # auth_add_middleware, current_user-middleware, login/logout, bcrypt, CSRF
│   │   └── articles.yaml            # реестр статей (кладёт/правит пользователь через /art_manage)
│   ├── content_art/                 # .md-статьи блога (кладёт пользователь)
│   ├── static/profile_pics/         # аватары: default.jpg (125×125) + загруженные
│   │
│   ├── utils/docs.py                # reg_docs_routes() — свои Swagger/ReDoc с CDN
│   │
│   └── alembic/
│       ├── env.py                   # Асинхронный runner; url из settings.db.url
│       └── versions/
│           ├── ...--59bdab4b2e7c--user_post.py      # users, posts
│           ├── ...--35ae229e79dd--order_product.py  # orders, products, association
│           └── ...--b59cbdf15878--blog.py           # blog_user, blog_post
│
├── nginx/
│   ├── Docker-nginx                 # nginx:1.20-alpine + копирование conf/web/cert
│   ├── nginx.conf                   # TLS-терминация, reverse proxy для xaphan.ru
│   └── web/default/                 # index.html, custom_50x.html
│
├── docker-compose.yml               # Локальная разработка: pg + adminer + pgadmin
├── nginx_pg_admin.yml               # Прод-подобный стек: pg + pgadmin + redis + nginx
├── Makefile                         # Запуск uvicorn, alembic, docker network
├── adminGit.sh                      # CLI-обёртка над git
├── adminDock.sh                     # CLI-обёртка над docker
├── pyproject.toml                   # Зависимости (uv), конфиг ruff + black
├── uv.lock                          # Лок-файл uv
├── .python-version                  # 3.12
└── Install-run.md                   # Шпаргалка по командам запуска
```

---

## Ключевые модули и их абстракции

### Точки входа и сборка приложения

| Файл | Ответственность | Абстракции |
|---|---|---|
| `fastapi-application/main.py` | Собирает `main_app`: вызывает `create_app()` (каркас: FastAPI + lifespan + /docs), подключает три корневых роутера, вызывает `include_router_api_frontend(main_app)` (блог: middleware + mount /static + router_blog_api) и затем `mount_vite_react_assets(main_app)`. Функция `main()` запускает `uvicorn.run("main:main_app", reload=True)`. Вся SPA-обвязка вынесена в `setup_frontend.py`. | `main_app: FastAPI`, `main()` |
| `../fastapi-application/md_articles/setup_frontend.py` | Единственная точка, где FastAPI узнаёт про фронтенд. `mount_vite_react_assets(app)` монтирует `/assets` (`StaticFiles` из `frontend/dist/assets`, `check_dir=False`), дописывает в конец `app.router.routes` GET-catch-all `/{full_path:path}` → `spa_fallback` (отдаёт `index.html`; для `/api*` и при отсутствии `index.html` — JSON 404). Подробно — в [`docs/13_frontend_spa_module.md`](13_frontend_spa_module.md). | `mount_vite_react_assets()`, `spa_fallback()`, `FRONTEND_DIST`, `ASSETS_DIR`, `INDEX_HTML` |
| `fastapi-application/create_fastapi.py` | Единственное место создания `FastAPI`. Настраивает `ORJSONResponse` по умолчанию, `lifespan`, переключает встроенные `/docs` на кастомные по флагу. Блог сюда не входит — он подключается из `main.py` через `include_router_api_frontend`. | `create_app()`, `lifespan()` |
| `fastapi-application/base_dir_path.py` | Два `Path`-константы. `BASE_DIR` = каталог `fastapi-application/`, служит якорем для `.env`, папки логов, контента статей (`content_art/`) и аватаров. | `BASE_DIR` |

### Конфигурация

| Файл | Ответственность | Абстракции |
|---|---|---|
| `fastapi-application/core/config.py` | Вся конфигурация как вложенные pydantic-модели. Читает env с префиксом `APP__` и разделителем `__`. Единственное обязательное поле — `db.url`. | `Settings`, `DatabaseConfig`, `RunConfig`, `ApiPrefix`, `ApiV1Prefix`, `SqliteDsn`, `settings` |
| `../fastapi-application/prod_db.env` | Профиль PostgreSQL: `postgresql+asyncpg://user:password@localhost:5432/shop`. Подключается **раскомментированием строки в коде**. | — |
| `../fastapi-application/dev_sqlite.env` | Профиль SQLite: `sqlite+aiosqlite:///./one_simple.db`, `ECHO=1`. Активен. | — |

`SqliteDsn` — кастомный `AnyUrl` с `UrlConstraints(allowed_schemes=["sqlite", "sqlite+aiosqlite"], host_required=False)`. Без `host_required=False` pydantic отверг бы URL вида `sqlite+aiosqlite:///./one_simple.db`.

### Слой доступа к данным

| Файл | Ответственность | Абстракции |
|---|---|---|
| `fastapi-application/db_core/db_async.py` | Владеет движком и фабрикой сессий. Регистрирует хук `PRAGMA foreign_keys=ON` для SQLite. Экспортирует единый DI-алиас сессии. | `AsyncDbManager`, `db_manager`, `CurrentSession` |
| `fastapi-application/db_core/model_base.py` | Декларативная база с общим `MetaData` и `naming_convention` из настроек. Автогенерирует `__tablename__` через `declared_attr.directive`. | `Base` |
| `fastapi-application/db_core/type_for_models.py` | Переиспользуемые `Annotated`-типы колонок, убирающие повторение `mapped_column(...)` в моделях. | `int_primary_key`, `time_stamp_utc`, `str_len_50`, `str_len_100` |
| `fastapi-application/db_core/case_converter.py` | `CamelCase` → `snake_case` с корректной обработкой аббревиатур (`SomeSDK` → `some_sdk`). Есть doctest-примеры. | `camel_case_to_snake_case()` |
| `fastapi-application/db_core/__init__.py` | Реэкспорт `Base` и моделей. **Критично**: именно этот импорт наполняет `Base.metadata` для Alembic `--autogenerate`. | `__all__` |

`CurrentSession = Annotated[AsyncSession, Depends(db_manager.get_async_session)]` — вся инъекция сессии сведена к одной аннотации; роуты пишут `db: CurrentSession`.

### Модели и схемы

| Файл | Ответственность | Абстракции |
|---|---|---|
| `ex_user_post/models/model_user_post.py` | `User` (уникальный `nickname`, составной `UniqueConstraint(firstname, surname)`) и `Post` с FK на `users.id` (`CASCADE` на delete и update). | `User`, `Post` |
| `ex_user_post/models/model_user_mix.py` | `TestUser` — демонстрация примеси PK. Не реэкспортирован в `db_core/__init__.py`, поэтому невидим для Alembic. | `TestUser` |
| `ex_user_post/models/model_id_pk_mixin.py` | Примесь с индексируемым целочисленным PK. | `IntIdPkMixin` |
| `ex_user_post/schemas/schema_user.py` | Схемы запросов/ответов. `UserResp(UserCreate)` наследует поле `password` — см. [04_code_quality.md](04_code_quality.md). | `UserCreate`, `UserResp`, `PostCreate`, `PostResp` |
| `ex_order_product/model_order_product.py` | Many-to-many `Order ↔ Product` через явную `OrderProductAssociation` с полезной нагрузкой (`count`, `unit_price`) и `UniqueConstraint(order_id, product_id)`. `__tablename__` переопределён вручную. | `Order`, `Product`, `OrderProductAssociation` |
| `ex_order_product/schema_order_product.py` | 20+ схем: query/body/response, включая иерархию вложенных ответов для разных вариантов `joinedload`. | `OrderResp`, `OrderRespWithProducts`, `ProductRespWithOrders`, `AssociationResp`, `OrderGetAllOrderbyQuery` и др. |

### Демонстрационная часть `api/`

| Файл | Что демонстрирует |
|---|---|
| `api/dependencies/func_deps.py` | Фабрика зависимостей: `get_header_dependency(name, default)` возвращает замыкание-зависимость. Позволяет параметризовать имя заголовка. |
| `api/dependencies/cls_deps.py` | Три способа сделать класс зависимостью: `__call__` (`HeaderAccessDependency`), метод-генератор с teardown (`PathReaderDependency.as_dependency`), pydantic-модели результата (`TokenData`, `TokenIntrospectResult`). |
| `api/dependencies/helper.py` | `GreatService.__init__` сам объявляет `Header(...)`-параметры, поэтому класс работает как зависимость напрямую через `Depends(GreatService)`. `GreatHelper` требует фабрику. |
| `api/dependencies/dep_examp_simple.py` | 4 роута: прямой `Header()`, зависимость-функция, смешанный вариант, две параметризованные зависимости. |
| `api/dependencies/dep_examp_cls.py` | 5 роутов: создание объекта в обработчике, фабрика, класс как зависимость, метод как зависимость, проверка токена. |
| `api/my_routes_dep/my_param_*.py` | Четыре реализации `GET /my_items/{item_id}`, извлекающие `Path`/`Query`/`Header`/`Cookie`/`Request`/`Response`. Различие только в стиле объявления. |
| `api/my_routes_dep/pydantic_schema.py` | `Field(...)` как default-значение против `Annotated[T, Field(...)]`. |
| `api/my_routes_dep/pydantic_validator.py` | Валидация через `Annotated` + `AfterValidator` (`RespAfterValid`, `frozen=True`) против декоратора `@field_validator` (`RespDecorValid`). |

### Блог `md_articles/` и клиентская часть `frontend/`

Подробный разбор — в [11_md_articles.md](11_md_articles.md); здесь — только карта модулей.

| Файл | Ответственность | Абстракции |
|---|---|---|
| `md_articles/__init__.py` | `include_router_api_frontend(app)` — вызывается из `main.py`: middleware `inject_current_user_middleware`, `SessionMiddleware` (cookie 14 дней), mount `/static` (аватары), глобальный хендлер `RequestValidationError` (формат `{errors}` только для `/api/blog`), include `router_blog_api`. | `include_router_api_frontend()` |
| `md_articles/api_blog.py` | JSON API блога: 13 эндпоинтов под `/api/blog` (csrf, current_user, register/login/logout, account GET/POST, articles с фильтром `?section=`, articles/{id}, sections, art_manage + add_all + meta). CSRF: заголовок `X-CSRF-Token` для JSON, поле формы `csrf_token` для multipart. Авторизация — 403 JSON вместо редиректа. | `router_blog_api`, `validate_csrf_header/form`, `require_login_api` |
| `md_articles/schema_art.py` | Реестр статей: pydantic-модель `ArticleLang`, чтение `articles.yaml` с mtime-кэшем и last-good-state при ошибке парсинга, атомарная запись (tempfile + `os.replace`), скан `content_art/`. Контент — `BASE_DIR / "content_art"`. | `ArticleLang`, `get_articles()`, `save_articles()`, `render_article()` |
| `md_articles/models.py` | `BlogUser` / `BlogPost` (SQLAlchemy 2.0, реэкспортированы в `db_core/__init__.py` для Alembic). | `BlogUser`, `BlogPost` |
| `md_articles/auth_middleware_helpers.py` | Сессии и пароли: `get_current_user` (из `session["user_id"]` в `request.state`), `login_user`/`logout_user`, `hash_password`/`verify_password` (bcrypt). | `get_current_user` |
| `frontend/src/api/client.ts` | Базовый fetch-клиент: `credentials: 'include'`, `getCsrfToken()` → `GET /api/blog/csrf`, `postJson()` с заголовком `X-CSRF-Token`, `postMultipart()` с полем `csrf_token`, класс `ApiError`. | `getJson`, `postJson`, `postMultipart` |
| `frontend/src/api/blog.ts` | Запросы контента: `getArticles(section?)`, `getSections()`, `getArticle(id)` — разделы и фильтрация по разделу. | `getArticles`, `getSections` |
| `frontend/src/components/SectionMenu.tsx` | Левое меню разделов (подпапки `content_art/`): NavLink, «Все статьи» + пункты `/section/<name>`, активный пункт, sticky-поведение из CSS. | `SectionMenu` |
| `frontend/src/components/Pagination.tsx` | Клиентская пагинация 5/10/20: «Назад/Вперёд», кликабельные номера, переключатель размера страницы. | `Pagination` |
| `frontend/src/components/SidePanel.tsx` | Боковая панель-модалка справа: overlay, закрытие по Esc/✕/клику по фону; используется на `/art_manage` для форм редактирования и добавления. | `SidePanel` |
| `frontend/src/context/AuthContext.tsx` | Текущий пользователь: инициализация `GET /current_user`, обновление после login/account, сброс после logout. | `AuthProvider`, `useAuth` |
| `frontend/src/hooks/` | Темы без перезагрузки: `useTheme` (4 темы сайта через `data-theme` на `<html>`, `localStorage['theme']`), `useHljsTheme` (swap активной `<link data-hljs-dark>` по `disabled`, `localStorage['hljs-theme']`). | `useTheme`, `useHljsTheme` |
| `frontend/src/App.tsx` | Маршруты React Router: `/`, `/section/:name`, `/about`, `/art/:author/:artId`, `/login`, `/register`, `/account`, `/art_manage`; защита `/account` и `/art_manage` через `RequireAuth`. | `RequireAuth` |

### Вспомогательные подсистемы

| Файл | Ответственность | Абстракции |
|---|---|---|
| `fastapi-application/config_log.py` | Автономная подсистема логирования на `logging.config.dictConfig`. Настраивается **на импорте модуля** (`config_log.py:126`), создаёт папку логов, ротация 1 МБ × 20 файлов. Не связана с FastAPI и не перехватывает логи uvicorn (блок закомментирован). | `ConfigLogger`, `create_config_dict()`, `logF`, `logFC` |
| `fastapi-application/utils/docs.py` | Регистрирует свои `/docs`, `/redoc` и OAuth2-redirect с ассетами Swagger/ReDoc из CDN unpkg. Включается флагом `create_app(custom_docs_url=True)`. | `reg_docs_routes()` |
| `alembic/env.py` | Асинхронный runner миграций. Подставляет `settings.db.url` в `sqlalchemy.url` в рантайме и берёт `target_metadata` из `db_core.Base`. Использует `pool.NullPool`. | `run_migrations_online()`, `run_async_migrations()`, `do_run_migrations()` |

---

## Внешние зависимости

### Обязательные в рантайме

| Компонент | Роль | Где сконфигурировано |
|---|---|---|
| **СУБД: PostgreSQL или SQLite** | Единственное хранилище состояния. Драйверы: `asyncpg` (PostgreSQL) и `aiosqlite` (SQLite). Переключение — выбором активного `.env` в кортеже `env_file`. | `core/config.py:88-93`, `prod_db.env`, `dev_sqlite.env` |
| **ASGI-сервер: uvicorn или gunicorn** | uvicorn — dev-режим с `reload=True`. gunicorn с `UvicornWorker` — многопроцессный режим. | `main.py`, `main_gunicorn.py`, `core/gunicorn/` |

### Инфраструктура (docker)

| Компонент | Роль | Где |
|---|---|---|
| **PostgreSQL 16** | Основная СУБД в прод-подобном стеке. Порт `7032:5432`, статический IP `172.20.0.2`, данные в `./pg_db`. | `nginx_pg_admin.yml` |
| **PostgreSQL (latest)** | СУБД для локальной разработки. Порт `5432:5432`, БД `shop`, без volume — **данные не сохраняются между перезапусками**. | `docker-compose.yml` |
| **pgAdmin 4** | Веб-администрирование БД. В dev — порт `5050`, в прод-стеке — за nginx по пути `/pgadmin`. | оба compose-файла |
| **Adminer** | Альтернативный веб-клиент БД, порт `8080`. Только в dev. | `docker-compose.yml` |
| **nginx 1.20-alpine** | TLS-терминация для `xaphan.ru` (сертификаты из `nginx/cert/`, в git не попадают), редирект 80→443, reverse proxy на pgadmin, flower и два приложения. | `nginx/Docker-nginx`, `nginx/nginx.conf` |
| **Redis 6.2-alpine** | Объявлен в прод-стеке (порт `7079:6379`, IP `172.20.0.4`), но **в коде приложения не используется** — нет клиента Redis в зависимостях. Задел на будущее. | `nginx_pg_admin.yml` |

### Сторонние API

Внешних HTTP-API проект не вызывает. Внешние сетевые зависимости — только CDN:

- **CDN unpkg.com** — ассеты Swagger UI и ReDoc из `utils/docs.py`. Активна только при `create_app(custom_docs_url=True)`; сейчас вызов идёт с `False`, поэтому используются встроенные ассеты FastAPI.
- **CDN cdn.jsdelivr.net** — highlight.js 11.12.0 и 16 таблиц стилей подсветки для SPA; подключаются в `frontend/index.html` с SRI-хешами. Загружаются браузером клиента, сервер их не запрашивает.

### Библиотеки

Из `pyproject.toml`, менеджер — **uv** (`[tool.uv] package = false`):

`fastapi>=0.111.0`, `uvicorn[standard]>=0.40.0`, `gunicorn>=23,<24`, `pydantic[email]>=2.7.1,<3`, `pydantic-settings>=2.2.1,<3`, `sqlalchemy[asyncio]>=2.0.30,<3`, `alembic>=1.13.1,<2`, `asyncpg>=0.31.0`, `aiosqlite>=0.22.1`, `orjson>=3.11.5`.

Линтеры `ruff>=0.14.10` и `black>=25.0.0` объявлены в основных `dependencies`, а не в dev-группе. `ruff` настроен на `line-length = 100` и игнорирует `F401`, `E402`, `F541`; `black` — на `line-length = 120`. **Настройки длины строки противоречат друг другу.**

Клиентская часть блога — **отдельное npm-приложение** в `frontend/` (менеджер — npm,
лок-файл `package-lock.json`): `react@18.3`, `react-dom@18.3`, `react-router-dom@6.30`;
dev-зависимости — `vite@6`, `typescript@5.6`, `tailwindcss@4.1` (плагин
`@tailwindcss/vite`), `@vitejs/plugin-react`. Сборка — `npm run build`
(`tsc && vite build`) в `frontend/dist`, которая **не коммитится** (строка `dist`
в `.gitignore`). С FastAPI фронтенд связан только контрактом JSON API `/api/blog`:
в dev — отдельный сервер Vite :5173 с прокси, в проде — статика `dist/`, которую
раздаёт FastAPI (mount `/assets` + SPA catch-all).

### Чего в проекте нет

- Тестов — ни одного файла (`test_*.py`, `conftest.py`, `pytest.ini` отсутствуют)
- CI/CD — нет `.github/workflows`, нет `.gitlab-ci.yml`
- `Dockerfile` для самого приложения — есть только `nginx/Docker-nginx`; приложение в контейнере не собирается
- Кэша, брокера сообщений, очередей задач — `nginx.conf` проксирует `flower_first`/`flower_two`, а прод-стек поднимает Redis, но Celery в кодовой базе отсутствует

---

## Агентный режим разработки

Проект развивается командой агентов Qwen Code по одному заданию за раз (добавлено
2026-08-30; комплект агентного режима — в `templates_qwen_agents/` как внешний
референс).

| Файл | Назначение |
|---|---|
| `QWEN.md` | контекст проекта + инструкции оркестратора (главная сессия; оркестратор — модель, с которой запущен харнесс) |
| `AGENTS.md` | контекст проекта + правила команды, таблица «Зоны и проверки», процесс дефектов |
| `tasks/current/REQUIREMENTS.md` | **текущее задание** команды; рядом с ним создаются рабочие артефакты (`DEFECTS.md`, `ADVERSARIAL_REVIEW.md`, `e2e/`, `screenshots/`, `dev/`) |
| `tasks/NNN-<slug>/` | архив закрытых заданий: задание, отчёт о выполнении и все доказательства в одной папке |
| `.qwen/agents/` | субагенты: `spec-writer`, `frontend-dev`, `backend-dev` (зона — Python-модули `fastapi-application/`), `qa`, `adversary`; модели ролей — только в frontmatter `model:` этих файлов |

Цикл: пользователь кладёт задание в `tasks/current/REQUIREMENTS.md` → оркестратор
планирует и делегирует → разработчики правят → qa проверяет запуском и curl-сценариями
(заметки в `e2e/`) → adversary атакует изменённое → дефекты в `DEFECTS.md` проходят цикл
OPEN → FIX-READY/DISPUTED → CLOSED (закрывает только qa) → когда все критерии успеха
подтверждены доказательствами, задание архивируется с отчётом, и цикл повторяется
с новым заданием.

В `templates_qwen_agents/` лежит комплект агентного режима — **только пример**,
для образца; рабочие файлы агентного режима — `QWEN.md`, `AGENTS.md`, `README.md`,
`tasks/`, `.qwen/` в корне этого репозитория. Подробности — в этих файлах.

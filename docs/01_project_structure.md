# 01. Карта проекта — my-fast-react-case

> Документ для двух аудиторий: **разработчики** получают быстрое погружение в структуру
> и назначение каждого модуля; **AI-агенты** — компактный индексируемый контекст с
> точными путями, символами и инвариантами для навигации по коду.
> Сопутствующие документы: [02_architecture.md](02_architecture.md) (архитектура и
> паттерны), [03_execution_flow.md](03_execution_flow.md) (логика работы).
> Углублённые авторские гайды по темам лежат отдельно в [`Guide_dev/`](../Guide_dev/).

## Назначение проекта

Учебно-демонстрационный проект на **FastAPI 0.111+ / Python 3.12** с фронтендом на
**React 18 + TypeScript + Vite + Tailwind CSS v4**. Это исполняемый каталог приёмов,
а не продуктовый сервис: одна и та же задача решается несколькими способами рядом,
чтобы сравнивать подходы «вживую» на запущенном приложении. Три функциональные части:

1. **Демонстрационная** (`api/`) — девять паттернов `Depends`, один и тот же эндпоинт
   `/my_items/{item_id}` в четырёх стилях извлечения параметров, два стиля
   pydantic-полей и два способа валидации.
2. **Рабочая** (`ex_user_post/`, `ex_order_product/`, `db_core/`) — асинхронный слой
   данных на SQLAlchemy 2.0 с миграциями Alembic и двумя доменами: `User`/`Post`
   (one-to-many) и `Order`/`Product` (many-to-many через явную ассоциативную модель).
3. **Блог** (`md_articles/` + `frontend/`) — полноценное приложение: React SPA
   потребляет JSON API `/api/blog`; статьи лежат `.md`-файлами в `content_art/`,
   реестр — в `articles.yaml`; есть вход/регистрация (cookie-сессии, bcrypt, CSRF),
   аккаунт с загрузкой аватаров, управление реестром статей, темы сайта/подсветки.

**Важно:** дублирование маршрутов и обработчиков в `api/` намеренное — построчное
сравнение файлов и есть учебная цель. Не «рефакторите» его в общий код.

## Дерево проекта

```
my-fast-react-case/                  ← корень репозитория (запускается qwen-code)
│
├── fastapi-application/             ← корень Python-приложения (= BASE_DIR)
│   │                                   ПРЕДПОЧТИТЕЛЬНЫЙ cwd для запуска (см. грабли)
│   │
│   ├── main.py                      Композиция: create_app() + include_router всех
│   │                                доменов + include_router_api_frontend() (блог:
│   │                                auth/сессии/статика) + mount_vite_react_assets()
│   │                                (SPA: /assets + catch-all). Порядок вызовов —
│   │                                инвариант: catch-all обязан быть последним.
│   ├── create_fastapi.py            Фабрика create_app(custom_docs_url) + lifespan
│   │                                (startup-лог, shutdown: engine.dispose()). Каркас
│   │                                без доменов — наполнение в main.py.
│   ├── base_dir_path.py             BASE_DIR: Path(__file__).parent — якорь путей
│   │                                (логи, content_art, static, env-профили).
│   ├── config_log.py                ConfigLogger: синглтон уровня модуля, dictConfig
│   │                                из logging_config.yaml; logF (OnlyFile),
│   │                                logFC (FileStdout). Побочный эффект на импорте:
│   │                                создаёт BASE_DIR/log/.
│   ├── logging_config.yaml          Словарь dictConfig: 2 хендлера (rotating file
│   │                                1МБ×20 + stdout), 3 логгера (Stdout/FileStdout/
│   │                                OnlyFile). filename подставляется кодом.
│   │
│   ├── core/
│   │   └── config.py                Settings (pydantic-settings): вложенные модели
│   │                                RunConfig/WebConfig/ApiPrefix/DatabaseConfig;
│   │                                префикс APP__, разделитель __; env_file =
│   │                                (prod_db.env, dev_sqlite.env, .env) — ПОСЛЕДНИЙ
│   │                                файл в кортеже имеет приоритет. SqliteDsn —
│   │                                свой тип URL для sqlite. settings — синглтон.
│   ├── dev_sqlite.env               Профиль SQLite (АКТИВЕН): APP__DB__URL=sqlite+
│   │                                aiosqlite:///./one_simple.db — путь ОТНОСИТЕЛЕН
│   │                                cwd процесса.
│   ├── prod_db.env                  Профиль PostgreSQL: postgresql+asyncpg://…:5432/shop
│   │
│   ├── db_core/                     Переиспользуемый слой данных без доменной логики.
│   │   ├── db_async.py              AsyncDbManager: engine (создаётся НА ИМПОРТЕ
│   │   │                            модуля!), async_sessionmaker(autoflush=False,
│   │   │                            autocommit=False, expire_on_commit=False),
│   │   │                            get_async_session (rollback при ошибке), PRAGMA
│   │   │                            foreign_keys=ON для SQLite. CurrentSession —
│   │   │                            Annotated-алиас DI-сессии для роутов.
│   │   ├── model_base.py            Base(DeclarativeBase): naming_convention из
│   │   │                            настроек + автогенерация __tablename__
│   │   │                            CamelCase→snake_case (+s).
│   │   ├── type_for_models.py       Annotated-типы колонок: int_primary_key,
│   │   │                            time_stamp_utc, str_len_20…120, text_content.
│   │   ├── case_converter.py        camel_case_to_snake_case — движок автотаблеймов.
│   │   └── __init__.py              КРИТИЧНО: реэкспорт всех моделей (User, Post,
│   │                                Order, Product, OrderProductAssociation,
│   │                                BlogUser, BlogPost) — именно этот импорт
│   │                                наполняет Base.metadata для Alembic. Модель вне
│   │                                реэкспорта миграциям невидима (пример — TestUser).
│   │
│   ├── api/                         Демонстрационная часть (дублирование — НАМЕРЕННОЕ).
│   │   ├── __init__.py              router_api (prefix /api) → router_api_v1
│   │   │                            (prefix /v1) → dep_examples + param-стили.
│   │   ├── dependencies/            Девять паттернов Depends: func_deps (функция,
│   │   │                            фабрика замыканий), cls_deps (класс с __call__,
│   │   │                            генератор-метод as_dependency), helper.py
│   │   │                            (GreatHelper/GreatService — DI через сигнатуру
│   │   │                            конструктора), dep_examp_simple/cls — роуты.
│   │   └── my_routes_dep/           Один эндпоинт /my_items/{item_id} в 4 стилях
│   │                                (fastapi_class_old, fastapi_class_annotated,
│   │                                depends_class_annotated, depends_function_
│   │                                annotated) + pydantic_schema.py (Field-style vs
│   │                                Annotated-style) + pydantic_validator.py
│   │                                (типы-Annotated vs @field_validator).
│   │
│   ├── ex_user_post/                Домен User/Post (one-to-many).
│   │   ├── router_users.py          r_users_sql (prefix /users): GET /get_all_users,
│   │   │                            POST /create_user.
│   │   ├── crud/crud_users.py       Слой CRUD: get_all_users, create_user.
│   │   ├── models/model_user_post.py  User (nickname unique, UniqueConstraint
│   │   │                            (firstname,surname)), Post (FK CASCADE).
│   │   ├── models/model_user_mix.py Демонстрация примеси: TestUser(IntIdPkMixin,
│   │   │                            Base) — НЕ реэкспортирован, миграциям невидим.
│   │   └── schemas/schema_user.py   UserCreate/UserResp, PostCreate/PostResp.
│   │
│   ├── ex_order_product/            Домен Order/Product (many-to-many).
│   │   ├── router_order_one.py      r_order_one (prefix /orders), 6 роутов: ORM vs
│   │   │                            Core insert, filter_by vs where, order_by,
│   │   │                            joinedload (2 варианта разбора результата).
│   │   ├── model_order_product.py   Order, Product, OrderProductAssociation
│   │   │                            (явная ассоциативная таблица с count/unit_price,
│   │   │                            UniqueConstraint(order_id, product_id)).
│   │   └── schema_order_product.py  Query/Create-схемы + линейка response-моделей
│   │                                (OrderRespWithProducts, …WithAssoc и т.д.).
│   │
│   ├── md_articles/                 Блог: auth + статьи + подключение SPA-слоя.
│   │   ├── setup_frontend.py        ДВЕ точки сборки блога: include_router_
│   │   │                            api_frontend(app) — middleware auth + mount
│   │   │                            /static + include роутеров; mount_vite_react_
│   │   │                            assets(app) — mount /assets + catch-all
│   │   │                            /{full_path:path} (ручной append в конец
│   │   │                            router.routes). FRONTEND_DIST = ../frontend/dist.
│   │   ├── middleware_auth.py       Вся авторизация как middleware: SessionMiddleware
│   │   │                            (itsdangerous-cookie, 14 дней) + BaseHTTP
│   │   │                            inject_current_user (кладёт BlogUser в
│   │   │                            request.state) + кастомный обработчик 422 для
│   │   │                            /api/blog. ПОРЯДОК add_middleware — инвариант
│   │   │                            (см. 03_execution_flow.md).
│   │   ├── api_auth.py              router_auth_api (prefix /api/blog, tag auth):
│   │   │                            GET /csrf, GET /current_user, POST /register,
│   │   │                            POST /login, POST /logout, GET/POST /account.
│   │   ├── api_blog.py              router_blog_api (prefix /api/blog, tag blog api):
│   │   │                            GET /sections, GET /articles (?section=),
│   │   │                            GET /articles/{art_id}, GET /art_manage,
│   │   │                            POST /art_manage/{add_all,meta,sync}.
│   │   ├── helpers_auth.py          Хелперы без роутов: bcrypt hash/verify,
│   │   │                            save_picture (Pillow 125×125), CSRF (ensure/
│   │   │                            validate_csrf_header / validate_csrf_form),
│   │   │                            user_out, require_login_api (403 JSON),
│   │   │                            validation_response.
│   │   ├── schema_art.py            ArticleLang (pydantic) + ВСЯ логика реестра:
│   │   │                            get_articles (mtime-кэш), get_art, save_articles
│   │   │                            (атомарная запись через tempfile+os.replace),
│   │   │                            render_article (python-markdown → HTML),
│   │   │                            get_section, scan_content_art,
│   │   │                            sync_registry_with_disk.
│   │   ├── schema_blog.py           I/O-схемы auth/блог: UserOut, RegisterIn,
│   │   │                            LoginIn, MetaIn, SectionOut.
│   │   ├── models.py                BlogUser (unique username/email, bcrypt-поле,
│   │   │                            property is_authenticated — наследие Flask),
│   │   │                            BlogPost (в БД и миграциях есть, но API его
│   │   │                            не использует — историческая модель).
│   │   └── articles.yaml            РЕЕСТР СТАТЕЙ: список {author, lang, art_id,
│   │                                title, file_name, section}. Источник истины
│   │                                для /api/blog/articles*. Поле lang исторически
│   │                                хранит название раздела-категории.
│   │
│   ├── content_art/                 .md-статьи блога (кладёт пользователь).
│   │                                Подпапка первого уровня = раздел (section):
│   │                                «AI инструменты/», «Fast API/», «Python/» …
│   ├── static/profile_pics/         Аватары (default.jpg + hex-имена из save_picture).
│   │                                Раздаётся через mount /static.
│   ├── one_simple.db                SQLite-база (в gitignore; создаётся по cwd).
│   │
│   ├── alembic/                     Асинхронные миграции: env.py берёт URL из
│   │   │                            settings.db.url (не из alembic.ini!) и
│   │   │                            target_metadata из db_core.Base.metadata.
│   │   └── versions/                3 ревизии: user_post, order_product,
│   │                                md_articles_blog_user_post.
│   ├── alembic.ini                  Требует cwd = fastapi-application/ (плоские
│   │                                импорты db_core / core.config в env.py).
│   ├── utils/docs.py                reg_docs_routes: кастомные Swagger/ReDoc с CDN
│   │                                (подключаются при create_app(custom_docs_url=True);
│   │                                main.py использует False — стандартные /docs).
│   └── log/                         one_fast.log + ротация (в gitignore).
│
├── frontend/                        React SPA (сборка dist/ не коммитится).
│   ├── index.html                   Шаблон Vite: инлайн-скрипт восстановления темы
│   │                                (анти-вспышка), highlight.js 11.12.0 + языковые
│   │                                пакеты и 16 тем подсветки с CDN (SRI), #root.
│   ├── vite.config.ts               Tailwind v4 plugin; dev-сервер :5173 с прокси
│   │                                /api и /static → http://localhost:8000.
│   ├── package.json                 react 18, react-router-dom 6; build = tsc+vite.
│   └── src/
│       ├── main.tsx                 Точка входа: StrictMode > BrowserRouter >
│       │                            ToastProvider > AuthProvider > App.
│       ├── App.tsx                  Маршруты SPA: /, /section/:name, /about,
│       │                            /art/:author/:artId, /login, /register,
│       │                            /account и /art_manage (оба за RequireAuth).
│       ├── api/client.ts            База fetch-слоя: credentials:'include',
│       │                            ApiError, getJson, postJson (CSRF в заголовке
│       │                            X-CSRF-Token), postMultipart (CSRF полем формы).
│       ├── api/auth.ts              register/login/logout/getAccount/updateAccount;
│       │                            extractErrors — парсер формата {errors:{}}.
│       ├── api/blog.ts              getArticles(?section)/getSections/getArticle.
│       ├── api/artManage.ts         Клиент /api/blog/art_manage*.
│       ├── context/AuthContext.tsx  user/loading/setUser/refresh; инициализация
│       │                            GET /api/blog/current_user при старте SPA.
│       ├── components/              Layout (Header+SectionMenu+Outlet+footer),
│       │                            MarkdownContent (dangerouslySetInnerHTML для
│       │                            серверного HTML + hljs.highlightAll с алиасами),
│       │                            ArticleCard, Pagination, Header, ThemeSelect,
│       │                            HljsThemeSelect, ArtManageForms, SidePanel, Toast.
│       ├── pages/                   7 страниц: HomePage (карточки+пагинация+фильтр
│       │                            раздела), ArticlePage, LoginPage, RegisterPage,
│       │                            AccountPage (аватар: URL склеивается ЗДЕСЬ и
│       │                            только здесь — /static/profile_pics/{имя}),
│       │                            ArtManagePage, AboutPage.
│       ├── hooks/                   useTheme (data-theme на <html> + localStorage),
│       │                            useHljsTheme (переключение link disabled).
│       └── types.ts                 TS-типы контракта API: User, Article, Section.
│
├── nginx/                           Прод-подобный стек (для nginx_pg_admin.yml).
│   ├── nginx.conf                   TLS-прокси на приложение (домен xaphan.ru).
│   ├── Docker-nginx/                Dockerfile nginx-сервиса.
│   └── web/default/                 Статика default-сервера: index.html, custom_50x.
│
├── docs/                            Этот комплект документации (3 файла).
├── Guide_dev/                       Авторские гайды (14 файлов: обзор архитектуры,
│                                    backend, БД, контракт JSON API, React-фронтенд,
│                                    деплой, SPA-vs-SSR, URL-flow, auth_flow и др.).
├── tasks/                           Архив заданий агентного режима (001…017) +
│   └── current/                     живое задание (REQUIREMENTS.md).
├── .qwen/                           Конфигурация Qwen Code: агенты, скиллы, память.
│
├── docker-compose.yml               Dev-стек: postgres 5432 + adminer 8080 +
│                                    pgadmin 5050 (креды захардкожены — учебные).
├── nginx_pg_admin.yml               Прод-подобный стек: pg + pgadmin + redis +
│                                    nginx (TLS, внешняя сеть app_net_new).
├── Makefile                         Запуски uvicorn (linux/win), docker network,
│                                    alembic (цели migr_* используют устаревший
│                                    путь venv/bin — фактический интерпретатор .venv).
├── pyproject.toml / uv.lock         Зависимости (uv — источник истины) + ruff/black.
├── .python-version                  3.12.
├── QWEN.md / AGENTS.md              Контекст + правила команды агентов (оркестратор).
├── README.md / Install-run.md       Установка и запуск.
└── adminGit.sh / adminDock.sh       CLI-обёртки над git / docker (пользовательские).
```

## Инвентаризация маршрутов (42 объекта)

Проверка: `cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"` → **42**.
Разбивка: **35 APIRoute + 5 starlette Route + 2 Mount**. Любое изменение роутов должно
сходиться с этим счётчиком (инвариант регрессии).

| Группа | Префикс | Число | Модуль |
|---|---|---|---|
| Depends-примеры | `/api/v1/dep_examples/*` | 9 | `api/dependencies/dep_examp_*.py` |
| Параметры (4 стиля) | `/api/v1/{fastapi_class_old,fastapi_class_annotated,depends_class_annotated,depends_function_annotated}/my_items/{item_id}` | 4 | `api/my_routes_dep/my_param_*.py` |
| Домен User/Post | `/users/get_all_users`, `/users/create_user` | 2 | `ex_user_post/router_users.py` |
| Домен Order/Product | `/orders/*` (add_order, insert_order, get_order_filter_by, get_order_where, get_all_orders, get_all_join) | 6 | `ex_order_product/router_order_one.py` |
| Auth-API | `/api/blog/{csrf,current_user,register,login,logout,account(×2: GET+POST)}` | 7 | `md_articles/api_auth.py` |
| Blog-API | `/api/blog/{sections,articles,articles/{art_id},art_manage,art_manage/add_all,art_manage/meta,art_manage/sync}` | 7 | `md_articles/api_blog.py` |
| Служебные | `/docs`, `/redoc`, `/openapi.json`, `/docs/oauth2-redirect` | 4 | FastAPI (custom_docs_url=False) |
| SPA catch-all | `/{full_path:path}` → index.html; `/api*` → JSON 404 | 1 | `md_articles/setup_frontend.py::spa_fallback` |
| Монтирования | `/static` (аватары), `/assets` (сборка Vite) | 2 | `setup_frontend.py` |

## Внешние зависимости и их роль

| Зависимость | Роль | Где |
|---|---|---|
| **SQLite** (`aiosqlite`) | Основная БД учебного профиля; файл `./one_simple.db` относителен cwd; PRAGMA foreign_keys включается на каждый коннект | `db_core/db_async.py`, `dev_sqlite.env` |
| **PostgreSQL** (`asyncpg`) | Альтернативный профиль (раскомментировать в `core/config.py`); docker-стек поднимает pg 5432 | `prod_db.env`, `docker-compose.yml` |
| **highlight.js CDN** | Клиентская подсветка кода: 1 скрипт + 2 языковых пакета + 16 тем-стилей с SRI-хэшами | `frontend/index.html` |
| **Docker** | Только инфраструктура БД (dev-стек pg/adminer/pgadmin; прод-подобный стек с nginx TLS + redis). Приложение само в compose не входит | `docker-compose.yml`, `nginx_pg_admin.yml` |
| **uv** | Менеджер пакетов; `uv.lock` — источник истины | `pyproject.toml` |

Брокеров сообщений, очередей и сторонних API (кроме CDN) в проекте нет — состояние
живёт в БД, cookie-сессиях и YAML-реестре.

## Ключевые инварианты (проверять при изменениях)

1. `len(main_app.routes) == 42` — счётчик выше.
2. `mount_vite_react_assets(main_app)` вызывается в `main.py` **строго после** всех
   `include_router` — catch-all должен остаться последним маршрутом.
3. `add_middleware(BaseHTTPMiddleware, …)` в `middleware_auth.py` вызывается **до**
   `add_middleware(SessionMiddleware, …)` — иначе current_user-middleware окажется
   снаружи сессии (детали и причину см. [03_execution_flow.md](03_execution_flow.md)).
4. Все ORM-модели обязаны реэкспортироваться в `db_core/__init__.py` — иначе Alembic
   `--autogenerate` их не видит.
5. Модули приложения импортируются **плоско** (`from core.config import settings`) —
   cwd/`--app-dir` = `fastapi-application/`; приложение не устанавливается как пакет.

## Известные грабли

- **cwd-зависимость SQLite.** `sqlite+aiosqlite:///./one_simple.db` резолвится от
  рабочего каталога: запуск из корня (`make run_app11_lin`) создаст базу в корне, а
  не в `fastapi-application/`. «Пропавшие» данные после смены способа запуска = база
  в другом месте. Логи при этом всегда в `fastapi-application/log/` (привязка BASE_DIR).
- **Побочные эффекты на импорте.** Импорт `main` уже: создаёт `log/` и настраивает
  логгеры (`config_log`), читает env-профили (`core.config`), создаёт engine
  (`db_core.db_async`). Невалидный `APP__DB__URL` валит даже `python -c "import main"`.
- **Переключение профиля БД — правка кода**, не переменная окружения: список
  `env_file` в `core/config.py` (файлы в кортеже читаются по порядку, поздние
  перекрывают ранние; при необходимости локальный `.env`, не находящийся в git,
  перекроет оба профиля).
- **Alembic требует cwd = `fastapi-application/`** — там `alembic.ini` и плоские
  импорты `env.py`. Makefile-цели `migr_*` ссылаются на устаревший `venv/bin/alembic`.

## Быстрая проверка работоспособности

```bash
cd fastapi-application
../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"   # 42
../.venv/bin/uvicorn main:main_app --port 8000
# в другом терминале:
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/docs               # 200
curl -s http://127.0.0.1:8000/api/v1/dep_examples/single-direct-dependency        # 422 (нужен заголовок)
curl -s http://127.0.0.1:8000/users/get_all_users                                 # JSON
curl -s http://127.0.0.1:8000/api/blog/articles                                   # JSON реестра
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/                   # 200 = SPA (нужен frontend/dist)
```

Линтеры: `uv run ruff check .` (строка 100; игноры F401/E402/F541 — осознанные),
`uv run ruff format .` / `uv run black .` (строка 120). Сборка фронта:
`cd frontend && npm run build` (создаёт `frontend/dist`, не коммитится).

# 02. Архитектура и паттерны

> Как устроен проект концептуально: слои, паттерны проектирования, потоки данных,
> управление состоянием и конфигурацией. Файлы и маршруты — в
> [01_project_structure.md](01_project_structure.md); пошаговая логика выполнения —
> в [03_execution_flow.md](03_execution_flow.md).

## Высокоуровневая архитектура

**Модульный монолит** в одном ASGI-процессе: один процесс uvicorn обслуживает и JSON
API, и статику собранного React-приложения. Микросервисов нет; границы проходят не
между процессами, а между **пакетами-доменами** внутри `fastapi-application/`.

```
                        БРАУЗЕР (React SPA, history-mode роутинг)
                             │
                             │  fetch /api/blog/*  (cookie-сессия + CSRF)
                             │  GET /assets/*.js, /static/profile_pics/*
                             ▼
┌────────────────────────── uvicorn (ASGI) ──────────────────────────┐
│                                                                    │
│  FastAPI main_app  (create_app() — каркас; main.py — наполнение)   │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ MIDDLEWARE-СТЕК (снаружи внутрь):                            │  │
│  │   SessionMiddleware (cookie, itsdangerous-подпись)           │  │
│  │     → inject_current_user (BlogUser → request.state)         │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  РОУТЕРЫ (35 APIRoute):                                            │
│   ├─ router_api          /api/v1/*   демо: Depends + параметры     │
│   ├─ r_users_sql         /users/*    домен User/Post               │
│   ├─ r_order_one         /orders/*   домен Order/Product           │
│   ├─ router_auth_api     /api/blog/*  auth: сессии, аккаунт        │
│   └─ router_blog_api     /api/blog/*  статьи: реестр + markdown    │
│                                                                    │
│  МОНТИРОВАНИЯ: /static (аватары), /assets (сборка Vite)            │
│  CATCH-ALL: /{full_path:path} → index.html (последний маршрут)     │
└────────┬───────────────────────────────────────────┬───────────────┘
         ▼                                           ▼
  db_core (SQLAlchemy 2.0 async)          md_articles/schema_art.py
  AsyncDbManager → engine → сессии        YAML-реестр articles.yaml
         │                                + content_art/*.md
         ▼                                (python-markdown → HTML)
  SQLite (aiosqlite) / PostgreSQL (asyncpg)
```

Принципиальное решение: **блог хранит статьи не в БД, а в файловой системе** —
`articles.yaml` (метаданные) + `.md`-файлы (контент). БД используется только для
пользователей блога (`blog_user`). Демо-домены (`users`, `orders`) живут в тех же
таблицах той же БД, но не пересекаются с блогом логически.

### Два URL-слоя одного приложения

Один процесс обслуживает два независимых слоя маршрутов — их смешение является
историческим источником путаницы:

| Слой | Что отдаёт | Где живёт | Источник |
|---|---|---|---|
| **JSON API** `/api/blog/*` | данные для React-страниц | `md_articles/api_auth.py`, `api_blog.py` | БД + YAML + `.md` |
| **SPA catch-all** `/*` | `index.html` для client-side роутинга | `md_articles/setup_frontend.py::spa_fallback` | `frontend/dist/index.html` |

Catch-all добавляется **ручным `app.router.routes.append(...)`** после всех роутеров —
это гарантирует его позицию в самом конце (детали — в 03_execution_flow.md).

### Каркас vs наполнение

`create_fastapi.py::create_app()` — **фабрика каркаса**: FastAPI-инстанс с
`ORJSONResponse` по умолчанию, lifespan и (опционально) кастомными docs-роутами.
Домены каркас не знает. `main.py` — **единственное место композиции**: подключает
все роутеры, блог и SPA-слой. Такой разрез позволяет менять набор доменов, не трогая
фабрику, и видеть всю структуру приложения в одном файле.

## Слои и границы

| Слой | Пакеты | Правило зависимости |
|---|---|---|
| Конфигурация | `core/config.py`, `base_dir_path.py`, `config_log.py` | ничего не импортирует из доменов |
| Слой данных | `db_core/` | знает только `core.config` (naming_convention, URL); не знает доменов |
| Домены | `api/`, `ex_user_post/`, `ex_order_product/`, `md_articles/` | импортируют `db_core` и `core`; друг друга не импортируют |
| Композиция | `main.py` | единственный, кто знает все домены |
| Фронтенд | `frontend/` | изолирован полностью; общается только через HTTP-контракт `/api/blog` |

Нарушений нет: домены не тянут друг друга, `db_core` не содержит доменной логики.
Единственная «обратная» связь — `db_core/__init__.py` импортирует модели доменов,
но это **функциональный реэкспорт для Alembic** (наполнение `Base.metadata`), а не
логическая зависимость.

## Паттерны проектирования

### 1. Dependency Injection — центральный паттерн приложения

FastAPI-`Depends` пронизывает весь код, и проект делает его предметом изучения:

- **`CurrentSession`** (`db_core/db_async.py`) — `Annotated[AsyncSession, Depends(db_manager.get_async_session)]`.
  Единственный легальный способ получить сессию в роуте: пишется как тип-аннотация
  параметра, без явного `Depends` в каждом обработчике. Зависимость даёт сессию с
  авто-rollback при исключении.
- **Девять демонстрационных вариантов** (`api/dependencies/`): прямое извлечение
  `Header()`, функция-зависимость, фабрика замыканий (`get_header_dependency(name)`),
  конструирование объекта в самом роуте, зависимость-фабрика объекта (`get_great_helper`),
  класс-зависимость через `__call__` (`GreatService` — DI прямо в сигнатуру
  конструктора), генератор-метод `.as_dependency` (`PathReaderDependency`),
  инстанс-зависимость с конфигурацией (`HeaderAccessDependency(secret_token=...)`).
- **Четыре стиля извлечения параметров** одного эндпоинта `/my_items/{item_id}`
  (`api/my_routes_dep/`): классический (`Path()/Query()/Header()/Cookie()` в сигнатуре),
  `Annotated`-стиль, вынос валидации в классы-зависимости и в функции-зависимости.
  Смысл демонстрации: одно и то же поведение (path/query/header/cookie → ответ)
  достигается четырьмя способами организации кода.

Практическое применение DI в «боевой» части: `require_login_api` (403 для анонима)
и `CurrentSession` — обе зависимости объявляются аннотацией параметра роута.

### 2. Factory

- `create_app()` — фабрика приложения (каркас, см. выше).
- `async_sessionmaker` — фабрика сессий в `AsyncDbManager`.
- `get_header_dependency(header_name)` — фабрика замыканий-зависимостей (демо).

### 3. Singleton-на-импорте

`settings` (`core/config.py`), `db_manager` (`db_core/db_async.py`), `config_logger`
(`config_log.py`) создаются **в момент импорта модуля**. Это осознанный выбор для
учебного монолита: любое обращение к ним дёшево, но цена — побочные эффекты на
импорте (см. грабли в 01) и невозможность подмены без `app.dependency_overrides`.

### 4. Repository (облегчённый)

`ex_user_post/crud/crud_users.py` — классический слой доступа к данным между роутом
и ORM: роут не пишет SQL, crud не знает про HTTP. В `ex_order_product` CRUD-слоя
нет — там роуты работают с SQLAlchemy напрямую (ORM-стиль `db.add/commit` vs
Core-стиль `insert().values()`), потому что **демонстрация самих стилей и есть цель**.

### 5. Registry (реестр статей)

`md_articles/schema_art.py` — реестр на YAML-файле:
- `get_articles()` — чтение с **mtime-кэшем** (перезагрузка только если изменились
  `st_mtime_ns`/`st_size`);
- `save_articles()` — **атомарная запись** (tempfile в той же папке → `os.replace`);
- `sync_registry_with_disk()` — удаление «сиротских» записей;
- `ArticleLang._autofill_section` — pydantic `model_validator(mode="before")`
  вычисляет `section` из пути файла, если не задан.

Выбор YAML вместо БД — архитектурное: статьи редактируются как файлы (git-friendly),
а реестр читается человеком. Кэш по mtime даёт «горячую перезагрузку» без рестарта.

### 6. Middleware-pipeline (auth)

Авторизация построена не на dependency, а на стеке middleware (порядок критичен):

```
SessionMiddleware           — подписанная cookie → request.session
  └─ inject_current_user   — request.session["user_id"] → SELECT blog_user
                            → request.state.current_user (BlogUser | None)
```

Причина: `current_user` нужен всем обработчикам `/api/blog/*` сразу, без явной
зависимости в каждом роуте. Обработчики читают его через `get_request_user(request)`
(хелпер с `getattr`-защитой). Подробнее о порядке инициализации — в 03.

### 7. Annotated-типы колонок

`db_core/type_for_models.py` — переиспользуемые аннотации (`int_primary_key`,
`time_stamp_utc`, `str_len_50` …). Модель описывает **доменный смысл** поля, а
технические детали (длина, index, server_default) живут в типе. Аналогично
`naming_convention` в `Base.metadata` даёт детерминированные имена констрейнтов для
Alembic на всех СУБД.

### 8. Автогенерация имён таблиц

`db_core/model_base.py`: `__tablename__` вычисляется из имени класса
(`CamelCase → snake_case + s`). Отдельные имена (`blog_user`, `blog_post`,
`order_product_association`) переопределены явно — потому что флейвор-скрипт миграций
писался под уже существующие таблицы.

### 9. Миксин (демонстрация)

`ex_user_post/models/model_id_pk_mixin.py::IntIdPkMixin` + `TestUser` — пример
переиспользования колонок через примесь. `TestUser` сознательно **не** реэкспортирован
в `db_core/__init__.py`: наглядная демонстрация того, что Alembic видит только модели
из реэкспорта.

### 10. Контрактный слой фронтенда

`frontend/src/api/` повторяет бэкенд-контракт типами TypeScript (`types.ts`) и
функциями-обёртками. `client.ts` инкапсулирует сквозные механики: cookie-сессии
(`credentials: 'include'`), CSRF-протокол (JSON → заголовок `X-CSRF-Token`,
multipart → поле формы), парсинг ошибок в единый `ApiError`.

## Поток данных: запрос → БД → ответ

Типовой запрос к JSON API (например, `GET /api/blog/articles?section=Python`):

```
1. uvicorn принимает соединение
2. SessionMiddleware     — читает/создаёт подписанную cookie → request.session
3. inject_current_user   — открывает КОРОТКУЮ сессию БД (session_factory),
                           при session["user_id"] делает SELECT blog_user,
                           кладёт BlogUser в request.state.current_user,
                           сессию закрывает
4. FastAPI routing        — путь матчится по списку маршрутов (роутеры раньше,
                           catch-all последним) → найден articles_list
5. DI-разрешение          — зависимости роута: session: CurrentSession (НОВАЯ
                           сессия из пула), Query-параметр section
6. Обработчик             — get_articles() (реестр: mtime-кэш → YAML) → фильтр
                           _is_complete + section → список summary-словарей
7. Сериализация           — ORJSONResponse (default_response_class приложения)
8. Обратный проход        — middleware-стек наружу; cookie-изменения (если были)
                           подписываются и добавляются в ответ
```

### Важный нюанс: ДВЕ сессии БД на один запрос блога

Запрос к `/api/blog/*` использует **две разные сессии SQLAlchemy**:

1. **middleware-сессия** (`inject_current_user`) — короткоживущая, только чтение
   пользователя; закрывается до вызова роута… точнее, оборачивает и сам вызов роута
   (`response = await call_next(request)` внутри `async with`).
2. **роут-сессия** (`CurrentSession`) — живёт в рамках обработки запроса, через неё
   идут мутации (`commit`).

Отсюда правило, выученное на баге с аватаром: **мутации пользователя выполняются
только через роут-сессию**. `POST /api/blog/account` не мутирует объект из
`request.state.current_user` (он загружен другой сессией), а заново выбирает
`BlogUser` по `user_id` в роут-сессии и меняет уже его — иначе изменения не
попадают в UPDATE (объект «отвязан» от живой сессии).

### Данные на запись vs на чтение

| Данные | Путь записи | Путь чтения |
|---|---|---|
| Пользователи блога | `POST /api/blog/register`, `POST /api/blog/account` | middleware + auth-роуты |
| Аватары | `save_picture()` → файл в `static/profile_pics/` + `image_file` в БД | `Mount /static` (StaticFiles) |
| Метаданные статей | `POST /api/blog/art_manage/*` → `save_articles()` (атомарный YAML) | `get_articles()` (mtime-кэш) |
| Контент статей | пользователь кладёт `.md` в `content_art/` | `render_article()` → HTML → фронт |
| Демо-домены | `POST /users/create_user`, `POST /orders/*` | GET-роуты доменов |

**Единственный источник истины для URL аватара:** БД хранит голое имя файла
(`image_file`), полный URL `/static/profile_pics/<имя>` склеивает фронтенд в
`AccountPage.tsx` (и `Header.tsx` при отображении). Склейка ровно в одном месте —
дублирование URL-склейки на бэке уже приводило к багам.

## Обработка состояния

Состояние приложения распределено по четырём хранилищам, каждое — под свою задачу:

| Вид состояния | Где | Механика |
|---|---|---|
| **Сессия пользователя** | cookie браузера (подпись itsdangerous) | server-side данные = только `user_id` + `csrf_token`; сам пользователь подгружается из БД на каждый запрос. Инвалидация = истечение max_age (14 дней) или logout. `secret_key` — `settings.web` |
| **Данные доменов** | SQLite / PostgreSQL | классические транзакции SQLAlchemy (autoflush/autocommit выключены, commit — явно в обработчике) |
| **Реестр статей** | `articles.yaml` | кэш в памяти процесса (`_registry_cache`) с проверкой mtime; запись атомарна; после записи кэш инвалидируется сбросом `_last_stat` |
| **Состояние UI (тема, hljs-тема)** | localStorage браузера | восстанавливается инлайн-скриптом в `index.html` до загрузки стилей (анти-вспышка), синхронизируется React-хуками |

Кэш реестра — единственный in-process кэш; Redis в `nginx_pg_admin.yml` присутствует
как часть прод-подобного стека, но приложением не используется.

Многопроцессность: gunicorn+workers возможен (`main_gunicorn.py`-паттерн удалён —
сейчас запуск uvicorn), но кэш реестра и sqlite-файл рассчитаны на один процесс;
для multi-worker нужен PostgreSQL.

## Конфигурация

Весь конфиг — **вложенные pydantic-модели** (`core/config.py`), читается из env-файлов:

```
Settings (BaseSettings)
├── run:  RunConfig        (host, port)
├── api:  ApiPrefix        (префиксы всех роутеров — /api, /v1, /users, /orders…)
├── web:  WebConfig        (secret_key для сессий)
└── db:   DatabaseConfig   (url — ЕДИНСТВЕННОЕ обязательное поле, echo, pool,
                            naming_convention)
```

- Формат переменных: `APP__<секция>__<поле>` (префикс + `env_nested_delimiter="__"`),
  например `APP__DB__URL`, `APP__RUN__PORT`.
- **Приоритет env-файлов**: кортеж `(prod_db.env, dev_sqlite.env, .env)` — pydantic-settings
  читает по порядку, поздние перекрывают ранние → активен `dev_sqlite.env`;
  локальный `.env` (не в git) перекрыл бы оба. Переключение на PostgreSQL — правка
  порядка в `core/config.py`, **не** переменная окружения.
- Типизация URL: `PostgresDsn | SqliteDsn` — невалидная схема роняет приложение на
  импорте (fail-fast).
- Новые настройки добавляются полями вложенных моделей с дефолтом; чтение
  `os.environ` напрямую — запрещено конвенцией.

## Фронтенд-архитектура

- **SPA + history-mode** React Router; серверная часть про роутинг фронтенда не знает
  (кроме catch-all, отдающего `index.html`).
- **Провайдеры** в `main.tsx` по порядку: `BrowserRouter → ToastProvider →
  AuthProvider → App`. `AuthContext` при монтировании дергает
  `GET /api/blog/current_user` — источник правды «кто залогинен» для всего UI;
  `RequireAuth` в `App.tsx` защищает `/account` и `/art_manage` (аноним → `/login`).
- **Рендер markdown — серверный**: бэкенд отдаёт готовый HTML (`python-markdown`,
  extensions fenced_code+tables), фронт вставляет его через
  `dangerouslySetInnerHTML` (единственное место, допустимое сознательно — контент
  доверенный) и запускает `hljs.highlightAll()` с регистрацией алиасов языков.
- **Темы**: 4 темы сайта (`data-theme` на `<html>` + Tailwind) и 16 тем подсветки
  (переключение `disabled` у `<link>` с CDN). Код всегда на тёмном фоне — светлая
  hljs-тема не активируется.
- **Dev-режим** (Vite :5173) проксирует `/api` и `/static` на :8000 — фронт работает
  без сборки и без CORS-настроек.

## Точки роста

1. **Валидация ответов демо-доменов**: `UserResp` наследует `password` от `UserCreate`
   — утекающее поле в JSON; нужен отдельный response-контракт.
2. **Обработка ошибок целостности**: дубль `nickname` в `POST /users/create_user`
   даёт 500 (`IntegrityError`) вместо 409; в auth-роутах дубль проверяется SELECT'ом
   (race возможен, но для учебного проекта приемлемо) — подход стоит унифицировать.
3. **`BlogPost` без потребителей**: модель и таблица есть, API нет — либо развить
  (статьи из БД), либо осознанно удалить.
4. **Сессии и CSRF-протокол** завязаны на cookie; при появлении отдельного
  frontend-origin понадобится CORS + SameSite-политика.
5. **Тестовый контур**: тестов нет, проверки — запуск + curl;`smoke`-скрипт в `scripts/`
  не создан. Первые кандидаты: счётчик маршрутов, контракт `/api/blog`, реестр YAML.

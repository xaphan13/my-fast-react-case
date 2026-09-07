# 03. Логика и работа кода

> Пошаговое объяснение того, как проект живёт и работает: от старта процесса до
> ответа на конкретный HTTP-запрос. Структура файлов — в
> [01_project_structure.md](01_project_structure.md), концепции — в
> [02_architecture.md](02_architecture.md). Здесь — динамика.

## Жизненный цикл приложения

### Этап 1. Импорт (до первого запроса)

Запуск `uvicorn main:main_app` (или `python main.py`) начинается с импорта `main`,
и **большая часть инициализации происходит уже на этом этапе** — это ключевая
особенность проекта. Цепочка импорта в порядке срабатывания:

```
main.py
 ├─ base_dir_path.py        BASE_DIR = Path(__file__).parent  (якорь всех путей)
 ├─ config_log.py           ПОБОЧНЫЙ ЭФФЕКТ: создаёт BASE_DIR/log/ и применяет
 │                          dictConfig из logging_config.yaml → логгеры logF/logFC готовы
 ├─ core/config.py          Settings() читает env-профили (prod_db → dev_sqlite → .env);
 │                          settings.db.url обязателен и валиден, иначе ImportError-крах
 ├─ create_fastapi.py ──┬─  db_core/db_async.py  ПОБОЧНЫЙ ЭФФЕКТ: db_manager создаёт
 │                      │  AsyncEngine СЕЙЧАС (пул соединений); для SQLite вешает
 │                      │  PRAGMA foreign_keys=ON на каждый коннект
 │                      └─  utils/docs.py       (только определения)
 ├─ роутеры api/, ex_user_post/, ex_order_product/
 └─ md_articles/setup_frontend.py → api_auth/api_blog → helpers_auth, models
    (BlogUser/BlogPost), schema_art (реестр articles.yaml НЕ читается на импорте —
    лениво, при первом запросе)
```

Затем выполняется тело `main.py` — **композиция приложения** (порядок операторов
важен, см. «Маршрутизация» ниже):

```python
main_app = create_app(custom_docs_url=False)   # каркас: ORJSON + lifespan + /docs
main_app.include_router(router_api)            # /api/v1/*
main_app.include_router(r_users_sql)           # /users/*
main_app.include_router(r_order_one)           # /orders/*
include_router_api_frontend(main_app)          # middleware auth + /static + /api/blog/*
mount_vite_react_assets(main_app)              # /assets + catch-all (ПОСЛЕДНИМ)
```

### Этап 2. Startup (lifespan)

После импорта uvicorn входит в `lifespan` (`create_fastapi.py`):

- логирует `settings.db.url` и заголовок приложения;
- если URL — SQLite, пишет предупреждение «used test sqlite dataBase»;
- `yield` — приложение готово принимать запросы.

Здесь нет создания таблиц и сидов: схема управляется Alembic, данные кладёт
пользователь. Ошибки подключения к БД проявятся не на startup, а на первом запросе
(engine лениво открывает соединения).

### Этап 3. Обслуживание запросов

Каждый HTTP-запрос проходит: **middleware-стек → маршрутизация → DI → обработчик →
сериализация → стек обратно**. Разбор ниже.

### Этап 4. Shutdown

`SIGTERM`/`SIGINT` → uvicorn корректно завершает lifespan → `await
db_manager.engine_dispose()` закрывает пул соединений → процесс завершается.
В режиме `--reload` watcher-процесс при изменении файла повторяет всю цепочку
(импорт → startup) в новом воркере — поэтому побочные эффекты импорта срабатывают
на каждый reload.

## Middleware: как собирается стек (критичный инвариант)

Авторизация — это три подключения в `middleware_auth.py::add_middleware_auth`:

```python
app.add_middleware(BaseHTTPMiddleware, dispatch=inject_current_user_middleware)
app.add_middleware(SessionMiddleware, secret_key=..., max_age=14*24*3600)
app.add_exception_handler(RequestValidationError, custom_...)
```

**Почему именно этот порядок вызовов.** Starlette кладёт каждое новое middleware
в НАЧАЛО списка (`user_middleware.insert(0, ...)`), а стек собирается по
`reversed(...)`. Итог: middleware, добавленное ПОЗЖЕ, оказывается СНАРУЖИ и
обрабатывает запрос ПЕРВЫМ. Схема для данного кода:

```
запрос → SessionMiddleware          (внешнее; request.session готов)
        → inject_current_user       (внутреннее; может читать request.session)
        → маршрутизация FastAPI
```

`inject_current_user` обязан видеть `request.session` — значит он должен стоять
внутри `SessionMiddleware`. Поменяйте порядок `add_middleware` местами —
current_user-middleware окажется снаружи сессии, и `request.session` бросит
`AssertionError` на каждом запросе. Это самый хрупкий инвариант проекта.

**Что делает `inject_current_user_middleware` на каждом запросе:**

1. Открывает короткую сессию БД (`db_manager.session_factory()`), лениво —
   соединение берётся из пула только при реальном запросе к БД.
2. `get_current_user(request, session)`: нет `session["user_id"]` →
   `request.state.current_user = None` (для анонима БД не трогается); есть →
   `SELECT blog_user WHERE id=...` → объект кладётся в `request.state.current_user`.
3. `await call_next(request)` — запрос уходит дальше в роутинг; middleware-сессия
   остаётся открытой вокруг всей downstream-обработки.
4. Обработчики читают пользователя хелпером `get_request_user(request)`.

**Две сессии на запрос.** Роуты блога получают ВТОРУЮ сессию через DI
(`CurrentSession`). Итоговое правило (выучено на баге с аватаром): объект из
`request.state.current_user` годится только для чтения; **мутации — только через
роут-сессию** (заново SELECT по `user_id` и изменение уже этого объекта), иначе
UPDATE не выполняется — изменений нет, хотя curl возвращает 200.

## Маршрутизация: порядок разрешения

FastAPI матчит маршруты по порядку в `app.router.routes`. Порядок задаётся
последовательностью в `main.py` и гарантирует, что специфичные маршруты стоят
раньше общих:

1. **Роутеры доменов** (`/api/v1/...`, `/users/...`, `/orders/...`) — подключены
   первыми.
2. **Роутеры блога** (`/api/blog/...`, 14 маршрутов) — внутри
   `include_router_api_frontend()`.
3. **Mount `/static`** — там же (аватары).
4. **Mount `/assets`** — в `mount_vite_react_assets()`.
5. **Catch-all `/{full_path:path}`** — добавлен **ручным `app.router.routes.append(
   Route(...))`**, а не `@app.get`: декоратор вставил бы маршрут не в конец. Именно
   поэтому `mount_vite_react_assets()` обязан вызываться строго последним.

Catch-all (`spa_fallback`) разрешает три случая:

| Пришло | Ответ |
|---|---|
| `/api` или `/api/...` (не совпало с реальным API-роутом) | JSON 404 `{"detail": "Not Found"}` — SPA-роутер не должен получать HTML вместо JSON |
| Любой другой путь, `frontend/dist/index.html` существует | `FileResponse(index.html)` — React Router на клиенте разберёт «страницу» |
| Фронт не собран (`dist/` пуст) | JSON 404 с подсказкой «выполните npm run build в frontend/» |

## Ключевые бизнес-процессы (step-by-step)

### A. Холодный заход на глубокую ссылку `/art/Max/123`

1. `GET /art/Max/123` → не совпал ни с одним API-роутом → catch-all → `index.html`
   (200, text/html).
2. Браузер грузит бандл `assets/index-*.js` (хэш в имени = вечный кэш), инлайн-скрипт
   `index.html` восстанавливает тему из localStorage до отрисовки (анти-вспышка).
3. React монтируется: `AuthProvider` → `GET /api/blog/current_user` (middleware
   подложит пользователя или `{"user": null}`).
4. React Router матчит `/art/:author/:artId` → `ArticlePage` →
   `GET /api/blog/articles/123`.
5. Бэкенд `article_detail`: `get_art(123)` — поиск по реестру (mtime-кэш YAML) →
   три причины 404 (нет записи / неполная мета / нет файла на диске) → иначе
   `render_article`: чтение `.md` → `markdown(text, extensions=["fenced_code",
   "tables"])` → готовый HTML кладётся в копию `ArticleLang`.
6. Фронт: `MarkdownContent` вставляет HTML (`dangerouslySetInnerHTML` — контент
   доверенный, единственное такое место) и вызывает `hljs.highlightAll()` после
   регистрации алиасов языков (env→ini, jinja2/vue→xml, txt→plaintext …).

### B. Регистрация и вход (CSRF-протокол)

Подготовка: любое окно с формой сначала вызывает `GET /api/blog/csrf` →
`ensure_csrf_token` создаёт `secrets.token_hex(32)` в сессии (cookie уже
установлена) и отдаёт его фронту.

`POST /api/blog/register` (JSON):
1. `validate_csrf_header`: заголовок `X-CSRF-Token` == `session["csrf_token"]`,
   иначе 403.
2. Уже залогинен? → 400 «Already authenticated».
3. Ручная валидация полей: username 2–20 символов, email формат (`EmailStr._validate`),
   пароли непусты и совпадают → при ошибках `validation_response`:
   **422 `{"errors": {"поле": ["текст", …]}}`** — формат WTForms-стиля, под который
   заточены React-формы (`extractErrors` во фронте).
4. Уникальность: `SELECT` по username и email (по одной проверке на каждое поле,
   только если поле уже прошло валидацию) → те же 422 errors.
5. Успех: `bcrypt.hashpw` + `session.add` + `commit` → `{"message": …,
   "category": "success"}`. Пользователь НЕ логинится автоматически.

`POST /api/blog/login`:
1. CSRF-заголовок; проверки полей; `SELECT blog_user WHERE email=...`.
2. `bcrypt.checkpw` — при неудаче единый **401 JSON** (без указания, что именно
   неверно).
3. Успех: `login_user(request, user.id)` = `request.session["user_id"] = id` —
   подписанная cookie обновится на выходе из middleware; ответ содержит `user`.

`POST /api/blog/logout`: CSRF-заголовок → `session.pop("user_id")` → cookie
переподписывается.

### C. Обновление аккаунта с аватаром (`POST /api/blog/account`, multipart)

1. `require_login_api` (DI): аноним → 403 JSON.
2. `validate_csrf_form`: CSRF-токен берётся **полем формы** `csrf_token` — так
   устроен клиент: JSON-запросы (`postJson`) шлют заголовок `X-CSRF-Token`, а
   `postMultipart` кладёт токен полем формы → 403 при несовпадении.
3. **Re-SELECT пользователя в роут-сессии** по `session["user_id"]` — см. правило
   двух сессий. Мутации будут у этого объекта.
4. Валидация полей с логикой «изменил ли»: `username != current_user.username` →
   только тогда проверять занятость (иначе «своё же имя» считалось бы дублем).
5. Аватар: `save_picture` — `os.urandom(8).hex()` + расширение из белого списка
   (иначе `.jpg`), Pillow `thumbnail(125×125)`, файл в `static/profile_pics/`;
   не-изображение → `ValueError` → 422 errors по полю `picture`.
6. Присваивания полей + `commit` → ответ с обновлённым `user_out` (id, username,
   email, image_file — пароль никогда не покидает бэкенд).

Фронт склеивает URL аватара: `AccountPage.tsx` → `/static/profile_pics/${image_file}`
— единственное место склейки; `image_file` в БД хранится голым именем файла.

### D. Управление реестром статей (`/api/blog/art_manage*`)

`GET /art_manage` (только авторизованный) собирает картину рассогласований:
- `articles` — все записи реестра с флагами `complete` (author+lang+title непусты)
  и `file_exists`;
- `unassigned_files` — `.md` на диске без записи в реестре;
- `missing_entries` — записи без файла;
- `yaml_error` — последняя ошибка чтения реестра (реестр валиден, но битые YAML
  не роняют API: `get_articles()` сохраняет последний рабочий кэш и сбрасывает
  mtime-метку для повторной попытки).

`POST /art_manage/add_all` — зарегистрировать все неназначенные файлы дефолтами:
`author="NoName"`, `title=stem(имя_файла)`, `lang=section(первая папка пути)`,
`art_id` = timestamp с инкрементом до свободного. Атомарная запись YAML.

`POST /art_manage/meta` — создать/обновить одну запись (по `file_name`); обновление
сохраняет существующий `section` записи, создание вычисляет его из пути.

`POST /art_manage/sync` — удалить записи без файла на диске (сироты).

Все три POST требуют CSRF-заголовок. Механика записи: `save_articles` — tempfile
в папке реестра → `yaml.safe_dump` → `os.replace` (атомарно) → сброс mtime-кэша
(`_last_stat = None`), чтобы следующий `get_articles()` перечитал файл.

### E. Демо-эндпоинты (для чего они)

- **`/api/v1/dep_examples/*` (9 роутов)** — показывают, как `Depends` добывает
  данные: от прямого `Header()` в сигнатуре до инстанса-зависимости с конфигом
  (`HeaderAccessDependency(secret_token=...)` вызывает `__call__` и валидирует
  токен, 401 при невалидном). Все отвечают JSON-описанием того, что получили.
- **`/my_items/{item_id}` × 4 префикса** — один и тот же контракт (path/query/
  header/cookie → ответ + кастомный заголовок и cookie) в четырёх стилях кода.
  Сравнивайте файлы построчно — это и есть учебная задача.
- **`/orders/*` (6 роутов)** — ORM vs Core (`add_order` через `db.add` vs
  `insert_order` через `insert().values()`), `filter_by` vs `where` (второй умеет
  списком условий и возвращает все совпадения), `order_by` по Enum-параметру,
  `joinedload(Order.products)` с двумя способами разбора результата
  (`unique().scalars().all()` vs построчный `row[0]`).
- **`/users/*`** — слой CRUD: роут → crud-функция → ORM, минимальный «правильный»
  вариант для сравнения с остальными.

## Обработка ошибок

Карта «кто и как сообщает об ошибке»:

| Источник | Механика | Формат/код |
|---|---|---|
| Валидация форм auth (register/login/account) | ручные проверки + `validation_response` | 422 `{"errors": {поле: [сообщения]}}` — фронт мапит на поля формы |
| Pydantic/FastAPI 422 (`RequestValidationError`) | `custom_request_validation_exception_handler`: для `/api/blog/*` — тот же формат `errors`; для остальных путей — стандартный `{"detail": [...]}` | 422 |
| CSRF | `HTTPException(403)` из `validate_csrf_*` | 403 |
| Неавторизован в API | `require_login_api` → `HTTPException(403)` (не редирект — у API своё поведение) | 403 JSON |
| Неверные учётные данные | `JSONResponse` напрямую из роута | 401 JSON |
| Статья не найдена/неполная/без файла | `HTTPException(404)` в `article_detail` | 404 |
| Заказ не найден (демо) | `HTTPException(409)` — пример «нестандартного» кода | 409 |
| Необработанное исключение | дефолт Starlette (нет своего handler) | 500 |

**Известные дефекты демо-части (не чинить без отдельного задания):**

1. `GET /api/v1/depends_function_annotated/my_items/{item_id}` **без** query-параметра
   `param_id` → 500: `RespDecorValid.validate_query_safe` выполняет `1 <= v <= 1000`
   при `v=None` → `TypeError`. Корректная реализация рядом — `pydantic_validator.py::
   RespAfterValid` (тип `QueryID = Annotated[int | None, Field(ge=1, le=1000)]`).
2. Дубль `nickname` в `POST /users/create_user` → 500 `IntegrityError` вместо 409
   (нет перехвата исключения целостности).
3. `UserResp` наследует `password` от `UserCreate` — пароль утекает в JSON-ответе
   `/users/get_all_users`.

Эти дефекты — часть экспозиции: на них видно, чем ручная валидация отличается от
декларативной и почему response-модель должна быть отдельным контрактом.

## Логирование

Конфигурация — `logging_config.yaml` через `dictConfig` (класс `ConfigLogger`,
синглтон на импорте). Два именованных логгера-фасада:

| Логгер | Куда | Когда использовать |
|---|---|---|
| `logF` (`OnlyFile`) | только `log/one_fast.log` (RotatingFileHandler, 1 МБ × 20 бэкапов) | основной лог приложения; запросы curl его не шумят в консоли |
| `logFC` (`FileStdout`) | файл + stdout | события, которые нужно видеть при live-разработке |

Формат `form2`: время, `module.funcName(line)`, поток → уровень и сообщение.
Русские комментарии в YAML допустимы (чтение с `encoding="utf-8"`).

Особенности:

- **Логи uvicorn не перехватываются** — блок `uvicorn`/`uvicorn.access` в YAML
  закомментирован; access-лог остаётся в консоли сервера, в файл не попадает.
- Путь файла всегда `BASE_DIR/log/` — не зависит от cwd запуска (в отличие от
  SQLite-файла).
- В демо-роутах разрешены подробные `logF.info` с составами данных — это витрина
  того, что попало в обработчик; в боевом коде (`api_blog`, `api_auth`) логирование
  скупое (register, reload реестра, SPA-подключение).

## Чек-лист «понимаю, как это работает»

Проверьте себя (или AI-агента перед задачей):

1. Почему `import main` создаёт каталог `log/` и engine, а не первый запрос?
2. Что случится, если в `add_middleware_auth` поменять местами два `add_middleware`?
3. Почему `mount_vite_react_assets` нельзя вызвать до `include_router`?
4. Почему `POST /api/blog/account` заново делает SELECT пользователя, хотя он уже
   есть в `request.state.current_user`?
5. Как `get_articles()` узнаёт, что `articles.yaml` изменился, и что происходит с
   кэшем при невалидном YAML?
6. Куда смотрит curl-ответ 422 от `/api/blog/register` и чем он отличается от 422
   на демо-маршруте?
7. Почему SQLite-база «пропадает» при запуске из корня проекта?

Ответы — в этом файле и в [02_architecture.md](02_architecture.md).

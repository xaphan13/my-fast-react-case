# 04. Оценка качества кодовой базы

> Часть 4 из 4. См. также: [01_project_structure.md](01_project_structure.md), [02_architecture.md](02_architecture.md), [03_execution_flow.md](03_execution_flow.md)

## Как читать этот документ

Проект — учебно-демонстрационный (см. [01_project_structure.md](01_project_structure.md)). Часть перечисленных ниже замечаний для такой цели допустима: дублирование обработчиков намеренное, захардкоженные токены нужны для наглядности примера. Но дефекты разделены на две категории, и это разделение принципиально:

- **Дефекты реализации** — код не делает того, что заявлено, или падает. Их надо править независимо от учебного статуса, потому что демонстрационный пример с ошибкой учит неверному.
- **Отклонения от продакшн-практик** — осознанные упрощения. Опасны только при копировании кода в реальный сервис.

Метрики цикломатической сложности собраны из графа кода: **максимум 3** (`camel_case_to_snake_case`, `get_async_session`), у остальных 1–2. Циклических зависимостей по `CALLS` — **0**. То есть проблема не в запутанности логики, а в структурных решениях и корректности деталей.

---

## Общая оценка

| Критерий | Оценка | Комментарий |
|---|---|---|
| Читаемость | **Высокая** | Явные аннотации типов, короткие функции, содержательные комментарии на русском |
| Модульность | **Средняя** | `db_core` изолирован хорошо; два домена реализованы по разным правилам |
| Связность (cohesion) | **Высокая** в `db_core`, `core`; **низкая** в `ex_order_product/router_order_one.py` |
| Сцепление (coupling) | **Низкое** — благодаря DI и `CurrentSession` |
| Идиоматичность | **Высокая** | SQLAlchemy 2.0 `Mapped[]`, `Annotated`, `asynccontextmanager`, `declared_attr.directive` |
| Тестируемость | **Низкая** | Тестов нет; побочные эффекты при импорте мешают их написанию |
| Наблюдаемость | **Низкая** | Логи uvicorn не перехватываются, метрик и health-check нет |
| Безопасность | **Ниже приемлемого** | Утечка пароля в API-ответе, секреты в git |

### Что сделано хорошо

**Типизация.** Аннотации присутствуют почти везде, включая возвращаемые типы (`-> Sequence[User]`, `-> AsyncGenerator[AsyncSession, None]`). Используются современные конструкции: `str | None` вместо `Optional[str]` в моделях, `Self` в `cls_deps.py`, `Sequence` вместо `List` для возвращаемых коллекций.

**Правильные детали инфраструктуры БД.** Три решения, которые обычно упускают:

1. `PRAGMA foreign_keys=ON` для SQLite (`db_core/db_async.py`) — без этого хука SQLite молча игнорирует `ForeignKey`, и `ondelete="CASCADE"` в `OrderProductAssociation` не работал бы. Ошибка, которую находят месяцами.
2. `naming_convention` в `MetaData` — делает имена констрейнтов детерминированными, что видно в миграциях (`op.f("fk_order_product_association_order_id_orders")`). Без этого автогенерируемые миграции невоспроизводимы между окружениями.
3. `.unique()` перед `.scalars()` при `joinedload` на коллекции (`get_all_join`) — обязателен, иначе `InvalidRequestError`.

**Whitelist вместо `getattr` для сортировки.** В `get_all_orders` порядок сортировки выбирается фиксированным `if/elif/else`, а не `getattr(Order, params)`. Это закрывает инъекцию через имя колонки. Правильный выбор, который часто делают неправильно.

**DRY на уровне схемы БД.** `db_core/type_for_models.py` устраняет повторение `mapped_column(...)`: модели читаются как `id: Mapped[int_primary_key]`, `promocode: Mapped[str_len_50 | None]`.

**`camel_case_to_snake_case` с doctest.** Единственная функция в проекте с исполняемыми примерами в docstring. Корректно обрабатывает аббревиатуры (`SomeSDK` → `some_sdk`), что нетривиально.

**Фабрика приложения без подключения роутеров.** `create_app()` не знает о роутерах доменов — они подключаются в `main.py`. Это делает фабрику пригодной для тестов с изолированным набором маршрутов, хотя тестов пока нет.

**Блог (`md_articles/` + `frontend/`) — самая зрелая часть проекта.** Что сделано правильно:

1. Пароли хешируются bcrypt (`auth_middleware_helpers.py`), пароль никогда не возвращается клиенту (`UserOut` без поля `password`) — прямой контраст с доменом `users` (P1-1).
2. CSRF: двойной токен в сессии, заголовок `X-CSRF-Token` для JSON-запросов и поле формы для multipart; проверка на каждом state-changing эндпоинте.
3. Реестр статей: mtime-кэш с last-good-state (битый `articles.yaml` не ломает работающий блог) и атомарная запись через tempfile + `os.replace` — нет окна с полусломанным файлом.
4. Уникальность username/email проверяется явными `SELECT`-запросами до вставки, ошибки возвращаются полем — нет проблемы `IntegrityError` → 500 (P2-6).
5. Фронтенд: hljs с CDN подключён с SRI-хешами; темы восстанавливаются инлайн-скриптом до загрузки стилей (нет вспышки неверной темы); API-клиент централизован в `client.ts`.
6. SPA fallback аккуратно обрабатывает отсутствие сборки: 404 JSON с подсказкой `npm run build` вместо 500.

---

## Соответствие принципам

### SOLID

**Single Responsibility — нарушается в двух местах.**

`ex_order_product/router_order_one.py` совмещает три ответственности: HTTP-контракт, построение SQL и диагностическое логирование. Обработчик `get_all_join` дополнительно занимается сравнением двух способов разбора `Result` — четвёртая ответственность, чисто демонстрационная.

`ConfigLogger` (`config_log.py`) отвечает и за конструирование конфигурации (`create_config_dict`), и за создание каталога на файловой системе (`__create_log_dir`), и за применение конфигурации, и за выдачу логгеров (`get_logger`). Четыре причины для изменения в одном классе.

**Open/Closed — соблюдается.** Иерархия схем `OrderResp` → `OrderRespWithProducts` / `OrderRespWithAssoc` расширяется наследованием без правки базовых классов. `BaseGreat` → `GreatHelper` / `GreatService` — то же.

**Liskov — соблюдается**, подмены с изменением контракта нет.

**Interface Segregation — соблюдается.** Иерархия response-схем в `schema_order_product.py` — это и есть сегрегация: клиент получает ровно тот набор полей, который соответствует стратегии загрузки связей в запросе.

**Dependency Inversion — соблюдается частично.** Обработчики зависят от абстракции `CurrentSession`, а не от конкретного движка. Но `ex_user_post/router_users.py` импортирует конкретный модуль `crud_users` напрямую, а `ex_order_product` вообще обходится без слоя абстракции.

### DRY

Соблюдается в инфраструктуре (`type_for_models.py`, `CurrentSession`, `get_header_dependency`) и **намеренно нарушается** в `api/my_routes_dep/` — четыре файла реализуют один эндпоинт. Для каталога приёмов это оправданно.

Ненамеренные нарушения:

- `datetime.now(timezone.utc)` дублируется как `default` в `time_stamp_utc` и как `onupdate` в модели `User` — при изменении часового пояса или перехода на `func.now()` править надо в двух местах;
- логика «отсеять `None` из параметров» реализована двумя способами в соседних обработчиках: dict-comprehension с `if v is not None` в `get_order_filter_by` и `model_dump(exclude_none=True)` в `get_order_where`. Здесь это часть демонстрации, но второй вариант однозначно лучше;
- `IntIdPkMixin` и `int_primary_key` решают одну задачу двумя способами.

### KISS

В основном соблюдается — сложность функций минимальна. Исключения:

`get_all_join` содержит ветвление `variant`, существующее только для демонстрации, плюс жёстко зашитые индексы `[0]`/`[1]`. Для реального обработчика это лишняя сложность с побочным дефектом.

`config_log.py` объявляет **шесть форматтеров** (`form1`–`form4`, `con1`, `con2`), из которых реально задействованы два. Остальные — закомментированные варианты, оставленные для сравнения.

Параметры `request: Request = ...` и `response: Response = ...` во всех четырёх файлах `my_param_*.py` — `Ellipsis` избыточен, FastAPI определяет эти типы по аннотации.

### Идиомы Python и FastAPI

Соблюдаются на хорошем уровне. Отдельно стоит отметить корректное применение `@declared_attr.directive` (а не устаревшего `@declared_attr`), `async_sessionmaker` вместо `sessionmaker(class_=AsyncSession)`, `asynccontextmanager` для `lifespan` вместо устаревших `@app.on_event`.

Отклонения:

- имя `ConfigLogger.isSetting` — camelCase вместо `is_setting` (PEP 8);
- `os.mkdir` + `os.path.exists` вместо `Path.mkdir(parents=True, exist_ok=True)`;
- `logging.basicConfig(level=logging.INFO, handlers=[])` после `dictConfig` — избыточный вызов, способный конфликтовать с уже применённой конфигурацией;
- в `main.py` строка `logF.warning(...)` стоит после блокирующего `uvicorn.run(...)`, то есть выполнится только при остановке сервера. Похоже на непреднамеренное размещение.

---

## Дефекты реализации

Приоритет P1 — приводит к отказу или утечке данных. P2 — работает неверно в граничных случаях.

### P1-1. Пароль возвращается клиенту

`ex_user_post/schemas/schema_user.py`:

```python
class UserCreate(BaseModel):
    nickname: str
    firstname: str
    surname: str
    password: str

class UserResp(UserCreate):      # ← наследует password
    model_config = ConfigDict(from_attributes=True)
    id: int
```

`UserResp` используется как `response_model` в обоих эндпоинтах `/users/*`. Следствие: `GET /users/get_all_users` отдаёт пароли **всех** пользователей, `POST /users/create_user` — пароль созданного. Пароли при этом хранятся в открытом виде — хеширования в проекте нет.

Исправление: `UserResp` должен наследовать общую базу без `password`, а не `UserCreate`.

```python
class UserBase(BaseModel):
    nickname: str
    firstname: str
    surname: str

class UserCreate(UserBase):
    password: str

class UserResp(UserBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
```

То же относится к `PostResp(PostCreate)` — там утечки секретов нет, но паттерн наследования схемы ответа от схемы запроса повторён.

### P1-2. `validate_query_safe` падает на `None`

`api/my_routes_dep/pydantic_validator.py`:

```python
@field_validator("query")
@classmethod
def validate_query_safe(cls, v: int | None) -> int | None:
    if 1 <= v <= 1000:      # TypeError при v is None
        return v
    raise ValueError("либо None, либо число от 1 до 1000")
```

Поле объявлено `int | None = None`, но `None` не обрабатывается. Эндпоинт `/api/v1/depends_function_annotated/my_items/{item_id}` возвращает **500 на любой запрос без `param_id`** — то есть в дефолтном сценарии.

Исправление: `if v is None or 1 <= v <= 1000: return v`.

### P1-3. `OrderResp.promocode` не допускает NULL

`ex_order_product/schema_order_product.py` объявляет `promocode: str`, тогда как колонка — `Mapped[str_len_50 | None]`. `POST /orders/add_order` без `promocode` создаст запись в БД и упадёт с 500 на сериализации ответа. Запись при этом останется — расхождение между фактическим состоянием БД и ответом API.

Исправление: `promocode: str | None = None`.

### P1-4. `get_all_join` падает при менее чем двух заказах

`ex_order_product/router_order_one.py`:

```python
order0, order1 = result_scalars_all[0], result_scalars_all[1]
```

Индексы зашиты жёстко и нужны **только для логирования**. На пустой или односоставной таблице — `IndexError` → 500. Диагностический код в продакшн-пути.

Исправление: убрать обращения по индексу, логировать через срез или `len()`.

### P2-1. `TestUser` невидим для Alembic

`db_core/__init__.py` реэкспортирует `User`, `Post`, `Order`, `Product`, `OrderProductAssociation`, но **не** `TestUser` из `ex_user_post/models/model_user_mix.py`. `alembic/env.py` берёт `target_metadata` из `db_core.Base`, поэтому при `alembic revision --autogenerate` таблица `test_users` в `Base.metadata` отсутствует. Если бы она существовала в БД, autogenerate сгенерировал бы `op.drop_table("test_users")`.

Исправление: добавить `TestUser` в реэкспорт либо удалить модель, если она не нужна.

### P2-2. `409 CONFLICT` вместо `404 NOT FOUND`

Два обработчика (`get_order_filter_by`, `get_order_where`) возвращают `409` при отсутствии записи. `409` означает конфликт состояния (например, нарушение уникальности), а не отсутствие ресурса.

### P2-3. `result.scalar()` без ограничения выборки

`get_order_filter_by` при пустом наборе фильтров строит `select(Order)` без `WHERE`. `result.scalar()` на выборке из нескольких строк поднимет `MultipleResultsFound` → 500. Нужен `.limit(1)` либо `scalars().first()`.

### P2-4. `validate_path_is_even` не соответствует ни имени, ни сообщению

```python
@field_validator("path")
@classmethod
def validate_path_is_even(cls, v: int) -> int:
    if v < 0:
        raise ValueError("Path - item_id должен быть больше 0")
    return v
```

Три расхождения: имя обещает проверку чётности (её нет), сообщение говорит «больше 0», а условие пропускает `0`. Само ограничение уже задано на уровне `Path(ge=1)`, так что валидатор избыточен.

### P2-5. Валидация порта клиента ломает ответ

`RespAfterValid` и `RespDecorValid` валидируют поле `request` (порт клиента) диапазоном 1024–65535. Клиент с исходящим портом ниже 1024 получит 500 на валидации **ответа** — при полностью корректном запросе.

### P2-6. `IntegrityError` не обрабатывается в доменах `users`/`orders`

Нарушение `UniqueConstraint` (дублирующийся `nickname` в `POST /users/create_user`, дублирующаяся пара в `OrderProductAssociation`) даёт **500** вместо `409`. В блоге проблемы нет — уникальность проверяется до вставки; здесь дефект остаётся актуальным.

### Дефекты миграции блога на SPA (исторический контекст)

Часть наблюдений зафиксирована при ревизии после перевода блога на SPA
(см. закрытые задания `tasks/NNN-*`):

- **Дубликат компонента.** `frontend/components/Toast.tsx` (вне `src/`) — копия рабочего `frontend/src/components/Toast.tsx`; Vite его не собирает, но файл «живёт» вне зоны сборки и рассинхронизируется.
- **Сессия БД на каждый запрос.** `inject_current_user_middleware` открывает `AsyncSession` и делает `SELECT blog_user` на **все** HTTP-запросы, включая `/docs`, статику, `/assets` и SPA catch-all, где пользователь не нужен. Для учебного проекта приемлемо, в проде — расход пула впустую.
- **CSRF-токен не ротируется.** Токен создаётся один раз и живёт в сессии до её истечения; после логина/логаута не обновляется. Стандартная рекомендация — ротация при смене уровня аутентификации.
- **`remember` в логине игнорируется.** Поле принимается схемой `LoginIn`, но `max_age` сессии фиксирован (14 дней) — галочка «запомнить меня» ни на что не влияет.
- **Мелочи.** `art_manage_api` вызывает `scan_content_art()` дважды (результат не переиспользуется); `client.ts` запрашивает `GET /api/blog/csrf` перед каждым POST, не кэшируя токен; `_ensure_csrf_token` импортирует `secrets` внутри функции.

---

## Code smells

| Smell | Где | Детали |
|---|---|---|
| Закомментированный код как переключатель | `core/config.py:91-92` | Профиль БД выбирается комментированием строки, а не переменной окружения |
| Закомментированные альтернативы | `cls_deps.py`, `dep_examp_cls.py`, `config_log.py` | Варианты `Depends(...)`, четыре неиспользуемых форматтера, блок логгеров uvicorn |
| Мёртвый код | `cls_deps.py:48`, `cls_deps.py:92` | `path_reader` и `access_required` создаются на уровне модуля, но в роутах закомментированы |
| Мёртвый код | `md_articles/routes_{main,users,articles}.py` | Удалены в задании 014 (были неиспользуемыми серверными роутерами блога старого образца) |
| Мёртвый код | `frontend/components/Toast.tsx` | Копия рабочего `src/components/Toast.tsx` вне зоны сборки Vite |
| Мёртвый код | `utils/docs.py` | `reg_docs_routes` не вызывается: `create_app(custom_docs_url=False)` |
| Магические значения | `router_order_one.py`, `cls_deps.py` | Индексы `[0]`/`[1]`, токены `"qwerty-abc"`, `"foo-bar-fizz-buzz"` |
| Диагностический вывод в бизнес-логике | все обработчики | `logF.info(f"{var=}")` — отладочный вывод, а не события домена |
| Глаголы в URL | `/get_all_users`, `/add_order` | Действие дублирует HTTP-метод |
| Числовые суффиксы в именах | `config_log.py` | `form1`–`form4`, `con1`, `con2`, `rotating_file1` не описывают назначение |
| Смешение языков | повсеместно | Комментарии и `detail` в `HTTPException` на русском, код на английском. `detail` уходит клиенту в API-ответе |
| Несогласованные настройки инструментов | `pyproject.toml` | `ruff: line-length = 100` против `black: line-length = 120`; `alembic.ini` post-write hook использует `black -l 79` — три разных значения |
| Линтеры в основных зависимостях | `pyproject.toml` | `ruff` и `black` в `dependencies`, а не в dev-группе — попадут в прод-образ |
| `F401` в глобальном ignore | `pyproject.toml` | Игнорирование неиспользуемых импортов скрывает реальный мусор; нужно точечное `__init__.py: ["F401"]` |

---

## Узкие места (bottlenecks)

Нагрузочного тестирования не проводилось; ниже — статический анализ.

**Пул соединений завышен относительно типового PostgreSQL.** `db_async.py`: `pool_size=50, max_overflow=10` → до 60 соединений на процесс. При `gunicorn --workers 4` это 240 соединений, тогда как дефолт `max_connections` в PostgreSQL — 100. Приложение исчерпает лимит БД раньше, чем упрётся в собственный пул.

**Пул создаётся до fork.** `db_manager` инстанцируется при импорте `main`, то есть в мастер-процессе gunicorn **до** форка воркеров. Пулы `asyncpg` не переживают `fork()` корректно — соединения разделяются между процессами. Пул нужно создавать в `lifespan` либо в хуке `post_fork`.

**`APP__DB__ECHO=1` в обоих `.env`.** SQLAlchemy пишет каждый SQL-запрос в stdout. Это заметная нагрузка на I/O и утечка данных в логи. Для демо приемлемо, для прода — нет.

**`joinedload` на коллекции.** В `get_all_join` даёт декартово произведение строк (заказ × товар). На больших наборах `selectinload` эффективнее: два запроса вместо одного раздутого.

**Отсутствие пагинации.** `get_all_users`, `get_all_orders`, `get_all_join` возвращают полные таблицы без `LIMIT`/`OFFSET`. Время ответа растёт линейно с объёмом данных.

**`RotatingFileHandler` при нескольких воркерах.** Обработчик не синхронизирован между процессами: при `workers > 1` воркеры конкурируют за один файл, ротация теряет записи.

**Индексы.** `int_primary_key` включает `index=True` (для PK избыточно — он и так индексирован). При этом на FK-колонках (`Post.user_id`, `OrderProductAssociation.order_id`/`product_id`) индексов нет, хотя именно они участвуют в JOIN. `UniqueConstraint` на паре `(order_id, product_id)` создаёт составной индекс, покрывающий поиск по `order_id`, но не по `product_id`.

Отсутствие цикломатической сложности выше 3 и нулевое число циклов в графе вызовов означают, что горячих точек в вычислениях нет — все узкие места лежат в работе с БД и I/O.

---

## Безопасность и надёжность

### Критично

**Пароли в открытом виде (домен `users`).** Хеширования нет: `User.password` — `Mapped[str_len_50 | None]`, `crud_users.create_user` сохраняет значение как получено. В сочетании с P1-1 (пароль в ответе API) это полная компрометация учётных данных. Нужен `passlib`/`argon2` или `bcrypt`. В блоге сделано правильно — bcrypt в `auth_middleware_helpers.py`, — что подчёркивает непоследовательность домена `users`.

**Секреты в репозитории.** В `.gitignore` строки `#*.env` и `#.env` **закомментированы**, поэтому `prod_db.env` и `dev_sqlite.env` закоммичены. `prod_db.env` содержит `postgresql+asyncpg://user:password@localhost:5432/shop` — строка подключения с парой логин/пароль находится в истории git. Удаление файла не поможет: нужна перезапись истории и ротация пароля.

**Пароль БД в логах.** `create_fastapi.lifespan` логирует `settings.db.url` целиком. Для PostgreSQL-профиля пароль попадает в `log/one_fast.log`. Нужен `settings.db.url.host` или маскирование.

### Существенно

**Аутентификация есть только в блоге.** Эндпоинты `/api/blog/account*` и `/api/blog/art_manage*` защищены (`require_login_api` → 403 JSON, cookie-сессии + bcrypt + CSRF). Все 21 эндпоинт демо-части и доменов `/users`, `/orders` открыты. `HeaderAccessDependency` защищает единственный демонстрационный роут `/direct-cls-dependency`.

**Сравнение токена уязвимо к timing-атаке.** `cls_deps.py`: `if token != self.secret_token`. Корректно — `secrets.compare_digest`.

**Захардкоженные токены.** `"qwerty-abc"` в декораторе роута `dep_examp_cls.py` и `"foo-bar-fizz-buzz"` в `cls_deps.py:92`.

**CORS, TrustedHost, ProxyHeaders не настроены.** Пользовательских middleware два (сессии блога и `current_user`), но защитных среди них нет. За nginx `request.client` вернёт IP прокси, несмотря на передаваемый `X-Forwarded-For` — а четыре обработчика `/my_items/{item_id}` возвращают `request.client.port` клиенту.

**Rate limiting отсутствует.** Защиты от перебора и флуда нет.

**Внутренние сообщения об ошибках уходят клиенту.** `detail` в `HTTPException` содержит русский текст с деталями фильтра — раскрывает внутреннюю структуру запроса.

**Зависимость от внешнего CDN.** `utils/docs.py` тянет Swagger UI и ReDoc с `unpkg.com` без `integrity`-хешей. Сейчас ветка неактивна (`custom_docs_url=False`), но при включении получаем поставку исполняемого JS от третьей стороны без проверки целостности.

**`docker-compose.yml`:** захардкоженные `POSTGRES_USER: user` / `POSTGRES_PASSWORD: password`. В отличие от `nginx_pg_admin.yml`, где секреты корректно вынесены в `${DB_USER}`/`${DB_PASSWORD}`.

### Надёжность

**Утечки ресурсов не обнаружено.** Сессии закрываются через `async with` в `get_async_session`, движок освобождается в `lifespan`. Единственная незакрытая ссылка — `PathReaderDependency._foobar` не сбрасывается после `yield` (строка закомментирована), но экземпляр создаётся на каждый запрос, поэтому утечки между запросами нет.

**Валидация входа — сильная сторона.** Pydantic покрывает все параметры: `ge=1` на path, `EmailStr` в схемах, `Enum` для сортировки, ограничения длины на уровне колонок. Инъекции через параметры закрыты параметризованными запросами SQLAlchemy, инъекция через имя колонки — whitelist-подходом в `get_all_orders`.

**Отсутствуют:**

- health-check эндпоинт (`/health`, `/ready`) — оркестратор не может определить готовность;
- retry и circuit breaker при недоступности БД — первый запрос после падения БД вернёт 500;
- graceful shutdown с дренажом активных запросов — `engine_dispose()` вызывается без ожидания завершения обработчиков;
- метрики (Prometheus) и трассировка;
- проверка соединения с БД при старте — `create_async_engine` ленив, приложение стартует при недоступной БД и падает на первом запросе к данным;
- volume для PostgreSQL в `docker-compose.yml` — данные теряются при пересоздании контейнера;
- тесты — ни одного файла; отсутствие тестов означает, что все перечисленные P1-дефекты не были бы обнаружены автоматически.

---

## Сводная таблица приоритетов

| # | Дефект | Файл | Приоритет |
|---|---|---|---|
| 1 | Пароль в ответе API | `ex_user_post/schemas/schema_user.py` | P1 |
| 2 | Пароли не хешируются | `ex_user_post/crud/crud_users.py`, модель `User` | P1 |
| 3 | `.env` с паролем в git | `.gitignore` | P1 |
| 4 | Пароль БД в логах | `create_fastapi.py` (`lifespan`) | P1 |
| 5 | `validate_query_safe` падает на `None` | `api/my_routes_dep/pydantic_validator.py` | P1 |
| 6 | `OrderResp.promocode` не допускает NULL | `ex_order_product/schema_order_product.py` | P1 |
| 7 | `IndexError` в `get_all_join` | `ex_order_product/router_order_one.py` | P1 |
| 8 | `pool_size=50` + пул до fork | `db_core/db_async.py` | P2 |
| 9 | `IntegrityError` → 500 | нет обработчиков исключений | P2 |
| 10 | `TestUser` невидим для Alembic | `db_core/__init__.py` | P2 |
| 11 | `MultipleResultsFound` в `get_order_filter_by` | `ex_order_product/router_order_one.py` | P2 |
| 12 | `409` вместо `404` | `ex_order_product/router_order_one.py` | P2 |
| 13 | Валидация порта клиента ломает ответ | `api/my_routes_dep/pydantic_validator.py` | P2 |
| 14 | `ECHO=1` в обоих профилях | `prod_db.env`, `dev_sqlite.env` | P2 |
| 15 | Логи uvicorn не в файле | `config_log.py` | P2 |
| 16 | Нет пагинации | `router_users.py`, `router_order_one.py` | P2 |
| 17 | Мёртвые серверные роутеры блога старого образца | `md_articles/routes_{main,users,articles}.py` (удалены в задании 014) | P2 (закрыт) |
| 18 | Сессия БД на каждый запрос | `md_articles/__init__.py` (middleware) | P3 |
| 19 | CSRF-токен не ротируется; `remember` игнорируется | `md_articles/api_blog.py` | P3 |
| 20 | Дубликат `Toast.tsx` вне `src/` | `frontend/components/Toast.tsx` | P3 |
| 21 | Timing-атака на сравнение токена | `api/dependencies/cls_deps.py` | P3 |
| 22 | Нет CORS/TrustedHost/ProxyHeaders | `create_fastapi.py` | P3 |
| 23 | Нет health-check | `create_fastapi.py` | P3 |
| 24 | Противоречия `line-length` | `pyproject.toml`, `alembic.ini` | P3 |


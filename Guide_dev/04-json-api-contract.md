# 04. JSON API: контракт, валидация, ошибки, документация

> Цикл «FastAPI + React». Предыдущая: [03. Слой данных](03-database-layer.md) · Следующая: [05. Фронтенд](05-react-frontend.md)

## Главная идея: схема = контракт = документация

**Pydantic-схема описывает контракт один раз**, а FastAPI извлекает из неё
сразу четыре вещи:

1. **Валидацию входа** — 422 с описанием полей при ошибке.
2. **Сериализацию выхода** — лишние поля (например, `password`) наружу не
   уйдут, если схема ответа их не содержит.
3. **Схему OpenAPI** → интерактивную документацию `/docs` и `/redoc`.
4. **Типизацию для IDE** — автодополнение и проверка прямо в обработчике.

Это и есть причина, почему Pydantic-схемы — **единственный артефакт**, в
котором сходятся бэкенд и фронтенд: TypeScript-зеркало в `frontend/src/types.ts`
должно соответствовать тому, что лежит в `md_articles/schema_blog.py` и
`ex_user_post/schemas/`.

## Схемы запросов и ответов — раздельные

Из `fastapi-application/ex_user_post/schemas/schema_user.py` (реальный код
проекта):

```python
class UserCreate(BaseModel):
    nickname: str
    firstname: str | None
    surname: str | None
    password: str

class UserResp(UserCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)   # читаем из ORM-объектов
```

**Проблема, которая тут осознанно оставлена:** `UserResp` наследует от
`UserCreate` — поэтому поле `password` **попадает в ответ**. Это дефект
безопасности (см. `docs/04_code_quality.md`), который не «чинили», чтобы
использовать его как учебный. Правильная схема — **не наследовать** `Resp`
от `Create`, а перечислять поля заново или через `exclude`:

```python
class UserResp(BaseModel):
    id: int
    nickname: str
    firstname: str | None
    surname: str | None
    model_config = ConfigDict(from_attributes=True)
    # password тут нет → в JSON-ответе его не будет
```

**Почему раздельные схемы важны:**

- Физически невозможно утечь чувствительные поля, если их нет в схеме
  ответа.
- Разные команды могут работать над разными схемами (фронт — над ответом,
  бэк — над запросом), не ломая друг друга.
- Миграция схемы запроса (добавить необязательное поле) не задевает
  клиентов, которым нужна только схема ответа.

`from_attributes=True` — разрешение pydantic читать атрибуты ORM-объектов, а
не только dict. Благодаря ему обработчик может вернуть ORM-объект
SQLAlchemy, а Pydantic сам возьмёт нужные поля.

## Обработчик: тонкий, типизированный, читаемый

`fastapi-application/ex_user_post/router_users.py` (реальный код):

```python
r_users_sql = APIRouter(
    prefix=settings.api.user_post_prefix,
    tags=["Sql example users"],
)

@r_users_sql.get("/get_all_users", response_model=list[UserResp])
async def get_users(session: CurrentSession):
    return await users_crud.get_all_users(session=session)

@r_users_sql.post("/create_user", response_model=UserResp)
async def create_user(
    session: CurrentSession,
    user_create: Annotated[UserCreate, Body()],
):
    return await users_crud.create_user(session=session, user_create=user_create)
```

Обратите внимание:

- `response_model` в декораторе — FastAPI сам провалидирует и сериализует
  ответ по схеме. То, что CRUD вернул лишнее, наружу не пройдёт.
- Тело запроса — просто параметр с типом `UserCreate`. Ни `request.json()`,
  ни ручных проверок.
- Обработчик **не содержит SQL и бизнес-логики** — только склейку
  зависимостей.

## Иерархия схем под стратегии загрузки

Приём из `fastapi-application/ex_order_product/schema_order_product.py`:
дерево схем ответов соответствует дереву `joinedload`/`selectinload`:

```
OrderResp                                  базовая: только поля заказа
├── OrderRespWithProducts                  + products: List[ProductResp]
├── OrderRespWithAssoc                     + products_details: List[AssociationResp]
└── OrderRespWithProductsDetails           + products c вложенными ассоциациями
```

**Зачем:** глубина сериализации контролируется на уровне типов. Эндпоинт,
который не сделал `joinedload`, физически не сможет вернуть вложенные
объекты — и не отдаст клиенту N+1 ленивых загрузок в сериализаторе. Клиент
по имени схемы видит, что получит.

## Ошибки: осмысленные статусы вместо 500

Три уровня обработки ошибок:

| Источник | Как обрабатывать | Результат |
|---|---|---|
| Невалидный вход | Ничего: pydantic сам | 422 + JSON с описанием полей |
| Ожидаемая бизнес-ситуация | `raise HTTPException` | 404 / 409 / 403 + `{"detail": ...}` |
| Неожиданное исключение | Сессия делает rollback и пробрасывает | 500 (и это правильно — честный сигнал бага) |

```python
if existing_order:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                        detail="Order already exists")
```

**Типичный дефект, который стоит проверить в своём API:** дубликат
уникального поля без перехвата `IntegrityError` даёт **500 вместо 409**.
Перехватывайте конфликты целостности явно и переводите их в осмысленные
статусы. В этом проекте `ex_user_post/router_users.create_user` —
осознанный дефект-учебный-пример.

**Свой формат 422 для SPA-клиента** (реальный приём из блога): кастомный
обработчик `custom_request_validation_exception_handler` живёт в
`md_articles/middleware_auth.py:99`. Он переписывает стандартный FastAPI
`{"detail": [{"loc": [...], "msg": "..."}]}` в формат
`{"errors": {"field": ["msg1", "msg2"]}}` для путей `/api/blog*` — это
удобнее для показа ошибок в полях формы. Дефолтный формат FastAPI
сохраняется для остальных эндпоинтов.

```python
# md_articles/middleware_auth.py:99 — упрощённо
async def custom_request_validation_exception_handler(request, exc):
    if request.url.path.startswith("/api/blog"):
        errors: dict[str, list[str]] = {}
        for e in exc.errors():
            loc = ".".join(str(p) for p in e["loc"][1:])  # пропустить "body"
            errors.setdefault(loc, []).append(e["msg"])
        return JSONResponse(status_code=422, content={"errors": errors})
    return await request_validation_exception_handler(request, exc)
```

## Версионирование

Префиксы версий — часть конфига, а не хардкод:

```python
router_api = APIRouter(prefix=settings.api.prefix)        # "/api"
router_api_v1 = APIRouter(prefix=settings.api.v1.prefix)  # "/v1"
router_api.include_router(router_api_v1)
```

В `core/config.py:20` это уже разнесено:

```python
class ApiV1Prefix(BaseModel):
    prefix: str = "/v1"
    dep_examples: str = "/dep_examples"
    # ...

class ApiPrefix(BaseModel):
    prefix: str = "/api"
    v1: ApiV1Prefix
    user_post_prefix: str = "/users"
    order_product_prefix: str = "/orders"
```

Практические правила:

- **Ломающие изменения контракта** → новый префикс `/api/v2`, старый живёт
  до перехода клиентов.
- **Добавление необязательных полей** в ответ — не ломающее изменение,
  можно в v1.
- Доменные роутеры (`/users`, `/orders`) в этом проекте живут без версии —
  это осознанный упрощённый выбор учебного проекта; в продуктовом коде
  весь публичный API держите под версией.

## OpenAPI — бесплатная документация контракта

```bash
curl -s http://127.0.0.1:8000/openapi.json | python -m json.tool | head -30
```

`/docs` (Swagger UI) — можно дёргать эндпоинты руками; `/openapi.json` —
машиночитаемый контракт, из которого генерируют TypeScript-типы для
фронтенда (инструменты типа `openapi-typescript`). Это закрывает главную
боль связки: **рассинхрон типов клиента и сервера**. Даже если не
генерировать автоматически, держите `frontend/src/types.ts` синхронным со
схемами pydantic — см. [статью 05](05-react-frontend.md).

## Чекпоинт самопроверки

- [ ] Схемы запроса и ответа раздельные; в ответе нет чувствительных полей.
- [ ] Каждый эндпоинт имеет `response_model`.
- [ ] Ожидаемые ситуации — осмысленные 4xx, а не 500.
- [ ] 422 для SPA-клиента — в удобном для форм формате (`{"errors": {...}}`).
- [ ] Публичный API под версионным префиксом.
- [ ] Контракт виден на `/docs` и совпадает с типами фронтенда.
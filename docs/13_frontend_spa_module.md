# 13. Модуль `frontend_routing.py`: как именно FastAPI раздаёт собранный React

Этот документ — про конкретный код в [`frontend_routing.py`](../fastapi-application/md_articles/frontend_routing.py):
почему он устроен так, как устроен, что делает каждая строка и какие грабли
ждут при неправильном порядке вызовов.

Архитектурное сравнение способов подключения фронта (SPA-в-FastAPI против
раздельных доменов, SSR, Jinja2) — в
[`docs/12_fastapi_react_integration.md`](12_fastapi_react_integration.md).
Здесь — только «как наш код превращает сборку Vite в работающий сайт».

## 1. Зачем отдельный модуль

`main.py` — это **сборка приложения**: какие роутеры включены, какая фабрика
`create_app()` вызвана, на каком хосте/порту запускаться. Всё, что касается
раздачи клиентского HTML и статики фронта, в эту ответственность не входит и
вынесено в `frontend_routing.py`.

Что это даёт:

- `main.py` остаётся короткой «картой приложения» — не нужно пробираться через
  30 строк, чтобы понять, какие API включены.
- Отключить SPA целиком (например, для чисто-API-режима) — одна строка:
  закомментировать `setup_react_routing_assets(main_app)`. Не нужно искать mount'ы и catch-all
  по всему `main.py`.
- Если в проекте появятся другие SPA (админка, документация) — каждая
  подключается своим модулем, без загромождения `main.py`.

## 2. Что делает `setup_react_routing_assets(app)` — три шага

### Шаг 1. `app.mount('/assets', StaticFiles(...))`

```python
app.mount(
    "/assets",
    StaticFiles(directory=ASSETS_DIR, check_dir=False),
    name="spa_assets",
)
```

**Зачем:** Vite при сборке раскладывает хэшированные бандлы в
`frontend/dist/assets/index-abc123.js`, `index-def456.css` и т. д. `index.html`
содержит `<script src="/assets/index-abc123.js">` и `<link href="/assets/...">`.
Когда браузер запрашивает эти файлы, FastAPI должен отдать их как обычные
статические с правильным MIME-типом (`application/javascript` для `.js`,
`text/css` для `.css`).

`StaticFiles` — это готовая реализация из Starlette: раздаёт файлы из каталога,
поддерживает range-запросы (нужно для видео/больших шрифтов), выставляет
`Content-Type` по расширению. `mount` — это способ подключить ASGI-приложение
(в данном случае `StaticFiles`) под конкретным префиксом пути; всё, что
начинается с `/assets/...`, уходит в это подмонтированное приложение, минуя
обычный роутер.

**Почему `check_dir=False`:** по умолчанию `StaticFiles` при импорте проверяет,
существует ли каталог. Если не существует — падает с ошибкой прямо на старте
приложения. Это было бы катастрофой: фронт собирается отдельно
(`npm run build`), и в свежем клоне репозитория `frontend/dist/` ещё нет.
С `check_dir=False` приложение стартует в любом случае, а в рантайме запросы к
`/assets/<файл>` вернут 404, если каталог пуст. Это безопасно: SPA-страница
загрузится, но без бандлов React, что в логах видно сразу.

**Грабля, которую `check_dir=False` лечит:**

```
RuntimeError: Directory 'frontend/dist/assets' does not exist
```

Без флага эта ошибка появляется на любом импорте `main` в окружении, где
фронт ещё не собран. С флагом — только в логах по факту запроса.

### Шаг 2. Catch-all `Route` в `router.routes` руками

```python
app.router.routes.append(
    Route("/{full_path:path}", spa_fallback, methods=["GET"])
)
```

**Зачем:** React Router работает в **history-mode** (URL без `#`), и каждый
«раздел» сайта (`/section/Rust`, `/art/Max/123`) — это путь, по которому
браузер шлёт GET на сервер. На сервере таких путей нет: они живут только в
JavaScript-роуте. Сервер обязан вернуть `index.html` — тогда React в браузере
сам разберёт, какую страницу показать.

**Почему не `include_router`:** `include_router` добавляет роуты в начало или
в определённую позицию (через параметры нет гарантии «в самый конец»), и
FastAPI сортирует их при добавлении. Для catch-all это критично: если он
окажется выше роута `/users/...`, любой GET на `/users/foo` уйдёт в SPA, а не в
API. Дописывание в `app.router.routes.append(...)` — единственный способ
**гарантировать** последнюю позицию.

Как Starlette выбирает маршрут: **первый совпавший выигрывает** (порядок
`for route in routes` — линейный поиск). Поэтому catch-all ставится последним:
все API-маршруты и `/assets` mount проверяются раньше и перехватывают свои
пути. До catch-all доходит только то, что не подошло ни под что другое.

**Почему именно `methods=["GET"]`:** history-mode обрабатывает только
навигацию (GET). POST/PUT/DELETE — это всегда API, и они не должны попадать
в SPA. POST на `/api/login` улетит в роутер логина, POST на `/users/create`
— в роутер users, и это правильно. Без `methods=["GET"]` catch-all перехватил
бы POST на любой несуществующий путь, вернул бы HTML и сломал клиент.

### Шаг 3. `spa_fallback` — два исключения из «вернуть index.html»

```python
if path == "/api" or path.startswith("/api/"):
    return JSONResponse(status_code=404, content={"detail": "Not Found"})

if not INDEX_HTML.is_file():
    return JSONResponse(404, {"detail": "Frontend не собран: ..."})

return FileResponse(INDEX_HTML)
```

**Исключение для `/api*` — самое важное.** Без него fetch на несуществующий
API-путь, например `GET /api/typo`, привёл бы к такому сценарию:

1. Браузер шлёт `GET /api/typo` с `Accept: application/json`.
2. Ни один API-роутер не совпал.
3. Catch-all `spa_fallback` срабатывает и возвращает `index.html` (200 OK,
   `Content-Type: text/html`).
4. Клиентский код делает `response.json()` и падает с
   `SyntaxError: Unexpected token '<'`, потому что тело ответа — HTML.

В консоли разработчика это выглядит как «API сломался», а на самом деле
проблема в catch-all. Поэтому `spa_fallback` **до** проверки существования
`index.html` сравнивает путь с `/api` и `/api/...` и возвращает
`JSONResponse(404)` — клиент получит структурированный ответ, axios/fetch
покажут нормальную ошибку, разработчик увидит в DevTools вкладку Network с
честным 404.

**Исключение для отсутствующего `index.html`** — защита от «молча сломанного
сайта». Если фронт не собран, `FileResponse(INDEX_HTML)` бросил бы
`Starlette` исключение на каждый GET, в логах — трейсбэки, в браузере —
непонятные 500-е. Явный JSONResponse с подсказкой «выполните `npm run build`»
сразу говорит, что чинить.

## 3. Пошаговая трассировка запросов

После `setup_react_routing_assets(main_app)` маршруты в `main_app.router.routes` идут в таком
порядке (упрощённо):

1. `/openapi.json`, `/docs`, `/redoc`, `/docs/oauth2-redirect` (utils/docs.py)
2. `router_api` (9 dep_examples + 4 my_items)
3. `r_users_sql` (CRUD User/Post)
4. `r_order_one` (Order)
5. `router_blog_api` (из `setup_auth_static_include(main_app)` в `main.py`)
6. `app.mount('/static', ...)` (аватары из md_articles)
7. `app.mount('/assets', StaticFiles(...))` ← **setup_react_routing_assets, шаг 1**
8. `Route('/{full_path:path}', spa_fallback, methods=['GET'])` ← **setup_react_routing_assets, шаг 2**

Что происходит с конкретными запросами:

| Запрос | Что срабатывает | Что отдаётся |
|---|---|---|
| `GET /` | catch-all (8) | `index.html` (React Router решает, что показывать) |
| `GET /section/Rust` | catch-all (8) | `index.html` (React Router знает про «Rust») |
| `GET /assets/index-abc.js` | mount `/assets` (7) | статический JS-бандл |
| `GET /docs` | utils/docs (1) | Swagger UI |
| `GET /api/blog/articles` | md_articles роутер (2) | JSON |
| `GET /users/get_all_users` | r_users_sql (4) | JSON |
| `GET /orders/get_all_orders` | r_order_one (5) | JSON |
| `GET /api/typo` | catch-all → ветка `/api*` | JSON 404 |
| `GET /static/profile_pics/x.jpg` | mount `/static` (6) | аватарка |
| `POST /api/blog/login` | md_articles роутер (2) | JSON (метод POST, не ловится catch-all) |
| `POST /typo` | ни один API не совпал | **404** от Starlette (catch-all только для GET) |
| `GET /typo` (без `dist/`) | catch-all → ветка «не собран» | JSON 404 с подсказкой |

## 4. Почему именно такой порядок вызовов в `main.py`

```python
main_app = create_app(...)          # каркас: FastAPI + lifespan + /docs
main_app.include_router(router_api)
main_app.include_router(r_users_sql)
main_app.include_router(r_order_one)
setup_auth_static_include(main_app)      # middleware + mount /static + router_blog_api
setup_react_routing_assets(main_app)                 # ← СТРОГО после setup_auth_static_include
```

`mount_vite_react_assets` дописывает два новых элемента в `router.routes`. Если его вызвать
**до** `include_router`, добавленные позже роутеры окажутся **после**
catch-all — и тогда `GET /users/...` сначала попадёт в SPA, а не в API.
Симптом: `/docs`, `/api/blog/articles`, `/users/get_all_users` отдают
`index.html` (200 OK) вместо JSON или Swagger UI. Это типичная ошибка порядка,
и она не проявляется сразу — браузер показывает SPA как ни в чём не бывало.

Правило: **catch-all всегда последний в `router.routes`**. Любой `mount` или
`include_router` после `mount_vite_react_assets` нужно ставить выше catch-all вручную, иначе
оно не сработает.

## 5. Dev-режим без `dist/`

В проекте два режима работы с фронтом:

### Режим разработки: Vite dev server на :5173

```bash
cd frontend
npm run dev   # Vite поднимается на http://localhost:5173
```

В этом режиме Vite отдаёт исходники с HMR (правка → мгновенное обновление
без пересборки), а запросы `/api` и `/static` проксирует на FastAPI
(`vite.config.ts`). Браузер ходит на :5173, FastAPI обслуживает только API.
SPA-обвязка из `frontend_routing.py` в этом режиме не задействована: Vite сам
является «SPA-сервером», а FastAPI — чистым API.

**Следствие:** `frontend/dist/` в dev-режиме не нужен. Можно вообще его
удалить — `mount_vite_react_assets` отработает штатно благодаря `check_dir=False`, просто
любой GET на :8000 (включая `/`) упрётся в ветку «Frontend не собран».

### Режим эксплуатации: один FastAPI на :8000

```bash
cd frontend && npm run build    # один раз: создаёт dist/
cd .. && uvicorn main:main_app
```

`dist/` создан, `mount_vite_react_assets` его видит, всё работает через один процесс. Именно
для этого режима и существует модуль `frontend_routing.py`.

### Гибрид: dev-режим, но «посмотреть, как собранный фронт ляжет на прод»

```bash
cd frontend && npm run build
# в другом терминале:
cd .. && uvicorn main:main_app
```

Vite не запущен, FastAPI обслуживает и API, и собранный фронт. Полезно
проверить, что после правки ничего не развалилось до коммита (HMR иногда
прячет проблемы, которые видны только на «холодной» загрузке).

## 6. Что сломается при неправильной правке

### Переставить `mount_vite_react_assets` до `include_router`

```python
# НЕПРАВИЛЬНО
setup_react_routing_assets(main_app)
main_app.include_router(router_api)   # окажется ПОСЛЕ catch-all
```

**Симптом:** `GET /users/...` отдаёт `index.html`. API-роутер мёртв.
**Как проверить:** `curl -i http://127.0.0.1:8000/users/get_all_users` →
`Content-Type: text/html` вместо `application/json`.

### Убрать защиту `/api*` в `spa_fallback`

```python
# НЕПРАВИЛЬНО
async def spa_fallback(request):
    return FileResponse(INDEX_HTML)   # без ветки /api*
```

**Симптом:** `GET /api/typo` возвращает HTML 200 OK. Клиентский `fetch().json()`
падает с `SyntaxError: Unexpected token '<'`. Ошибка выглядит как «сломанный
API», на самом деле — «SPA съела 404».

### Забыть `methods=["GET"]` в catch-all

```python
# НЕПРАВИЛЬНО
app.router.routes.append(Route("/{full_path:path}", spa_fallback))
```

**Симптом:** `POST /typo` возвращает `index.html` (200) вместо 404.
Серьёзнее: если бы `spa_fallback` что-то писал в БД по ошибке — побочный
эффект. С `methods=["GET"]` POST-запросы идут мимо catch-all и получают
нормальный 404 от Starlette.

### Поменять порядок mount'ов: `mount_vite_react_assets` до `include_router_api_frontend`

В этом проекте `main.py` вызывает `setup_auth_static_include(main_app)` после
доменных `include_router`, а `setup_react_routing_assets(main_app)` — после `include_router_api_frontend`.
Если бы `mount_vite_react_assets` оказался до `include_router_api_frontend`, mount `/assets` шёл
бы **раньше** API-роутеров блога. Здесь это безопасно (разные префиксы — `/api`
против `/assets`), но **плохая привычка** — порядок mount'ов в `router.routes`
меняет приоритет, и в других проектах это может выстрелить.

## 7. Резюме одной фразой

`setup_react_routing_assets(app)` делает ровно три вещи — монтирует `/assets`, дописывает
GET-catch-all в конец `router.routes`, защищает `/api*` от попадания в SPA —
и каждая из этих трёх вещей ломает ровно один класс проблем, если её
убрать или поставить не на место.

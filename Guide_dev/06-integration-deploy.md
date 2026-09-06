# 06. Связка, авторизация, деплой

> Цикл «FastAPI + React». Предыдущая: [05. Фронтенд](05-react-frontend.md) · Следующая: [07. Альтернативы](07-alternatives.md)

## 1. Dev: два сервера и невидимый прокси

В разработке живут два процесса:

```
Браузер ──▶ Vite :5173 (исходники TS/TSX + HMR)
                 │  proxy /api и /static
                 ▼
            FastAPI :8000 (JSON API, аватары, БД)
```

Прокси в `frontend/vite.config.ts` (реальный код):

```typescript
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api":    { target: "http://localhost:8000", changeOrigin: true },
      "/static": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist" },
});
```

**Почему прокси, а не прямые запросы на `:8000`:** браузер видит всё на
одном origin `:5173` — нет CORS, нет абсолютных URL в коде
(`fetch('/api/...')`), cookie ставятся без оговорок. Код фронтенда при
этом один и тот же в dev и в prod.

## 2. Prod: один сервер раздаёт всё

```bash
cd frontend && npm run build     # → dist/index.html + dist/assets/*.js|css
cd fastapi-application && ../.venv/bin/uvicorn main:main_app --port 8000
```

Три элемента SPA-хостинга живут в
`fastapi-application/md_articles/setup_frontend.py:79`:

```python
def mount_vite_react_assets(app: FastAPI) -> None:
    app.mount(
        "/assets",
        StaticFiles(directory=ASSETS_DIR, check_dir=False),
        name="spa_assets",
    )
    app.router.routes.append(Route("/{full_path:path}", spa_fallback, methods=["GET"]))
```

`spa_fallback` (`setup_frontend.py:49`) — обработчик, который:
- `path` начинается с `/api` → `JSONResponse(404)`, чтобы клиент не
  получал HTML вместо JSON;
- `dist/index.html` отсутствует → `JSONResponse(404)` с подсказкой
  `npm run build`;
- иначе → `FileResponse(INDEX_HTML)` — отдаём оболочку React Router'а.

Разбор «почему именно так»:

- **`check_dir=False`** — сервер стартует даже без собранного фронтенда
  (бэкенд-разработка не зависит от `npm run build`).
- **`/api*` перехватывается раньше** — неизвестный API-путь должен вернуть
  честный 404 JSON, а не HTML-страницу React (иначе клиент получит 200 с
  HTML и упадёт на `JSON.parse`).
- **catch-all добавляется последним** через `app.router.routes.append`
  — маршрутизация Starlette идёт по порядку регистрации; поставите
  catch-all раньше роутеров — он «съест» их всех. Именно поэтому **нельзя
  делать через `include_router`**: тот добавляет маршруты в начало списка.
- **Отсутствие `dist` — понятная ошибка с подсказкой**, а не молчаливая
  пустая страница.

## 3. Почему нет CORS — и когда он появится

CORS — это проверка *браузером*: разрешает ли сервер A странице с origin B
делать запросы. Пока API и SPA на одном origin (через прокси в dev, через
один сервер в prod) — междоменных запросов нет, CORS не нужен.

Он появится, когда разнесёте домены ([статья 07](07-alternatives.md),
способ B). Тогда на FastAPI:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.example.com"],   # не "*" при cookie-сессиях!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Плюс cookie с `SameSite=None; Secure` и общий домен. Это не «бесплатно» —
ещё одна причина, почему SPA-хостинг на самом FastAPI — удачный дефолт.

## 4. Авторизация: cookie-сессии + CSRF

Выбор проекта — **серверные cookie-сессии** (SessionMiddleware starlette), а
не JWT. Почему:

| | Cookie-сессии | JWT в localStorage |
|---|---|---|
| XSS-риск | cookie httpOnly — JS токен не читает | токен украден скриптом при XSS |
| Отзыв сессии | удалить сессию на сервере | невозможно до истечения срока |
| CSRF-риск | есть → нужен CSRF-токен | нет (но есть XSS) |
| Сложность | middleware + подписанная cookie | выпуск/обновление/хранение токенов |

Для классического сайта с формами cookie-сессии проще и безопаснее. JWT
берут под мобильные клиенты и микросервисы.

### Где живёт авторизация в проекте

Она **разнесена на три файла** в `md_articles/`:

- `middleware_auth.py` — HTTP-middleware (`inject_current_user_middleware`,
  `get_current_user`), `add_middleware_auth(app)` — единственная точка
  входа; кастомный handler `RequestValidationError` →
  `{"errors": {field: [msg]}}` для `/api/blog*`.
- `helpers_auth.py` — низкоуровневые хелперы:
  `user_out`, `login_user`/`logout_user`, `hash_password`/`verify_password`
  (bcrypt), `save_picture` (Pillow, 125×125 thumbnail),
  `validate_csrf_header`/`validate_csrf_form`, `require_login_api` (403),
  `validation_response` (формат 422).
- `api_auth.py` — JSON-роутер `router_auth_api` (`prefix="/api/blog"`,
  `tags=["auth"]`) с эндпоинтами `/csrf`, `/current_user`, `/register`,
  `/login`, `/logout`, `/account` (GET/POST).

### Точка подключения — `add_middleware_auth`

Из `md_articles/middleware_auth.py:58` (реальный код):

```python
def add_middleware_auth(app: FastAPI) -> None:
    # 1) HTTP-middleware: подгружает current_user для каждого запроса.
    #    Должна быть добавлена ДО SessionMiddleware — иначе окажется
    #    снаружи сессии, и request.session в get_current_user бросит AssertionError.
    app.add_middleware(
        BaseHTTPMiddleware,
        dispatch=inject_current_user_middleware,
    )

    # 2) Cookie-сессии (itsdangerous-подпись), 14 дней.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.web.secret_key,
        max_age=14 * 24 * 3600,
    )

    # 3) Кастомный формат 422 для /api/blog/* (формы SPA).
    app.add_exception_handler(
        RequestValidationError,
        custom_request_validation_exception_handler,
    )
```

`inject_current_user_middleware` (`middleware_auth.py:32`) открывает
короткую сессию БД через `db_manager.session_factory()`, вызывает
`get_current_user(request, session)`, и к моменту вызова роута в
`request.state.current_user` лежит либо `BlogUser`, либо `None`. Это
избавляет от повторяющегося `Depends(get_current_user)` в каждом
обработчике блога.

### CSRF

Изменяющие запросы требуют CSRF:
- JSON — заголовок `X-CSRF-Token` (валидируется `validate_csrf_header`);
- multipart — поле формы `csrf_token` (валидируется `validate_csrf_form`).

Токен живёт в сессии (`request.session['csrf_token']`). Фронт получает его
через `GET /api/blog/csrf` (один раз, потом использует повторно) — функция
`getCsrfToken()` в `frontend/src/api/client.ts:51`.

### Как это выглядит на фронтенде

Всё спрятано в базовом клиенте — компоненты вызывают `postJson(...)` и не
знают о CSRF вообще:

```typescript
// frontend/src/api/client.ts
export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const token = await getCsrfToken();
  const res = await request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
    body: JSON.stringify(body),
  });
  return (await ensureOk(res)) as T;
}
```

### 401 vs 403 — разная семантика

- **403** (от `require_login_api`) — «вы не авторизованы», фронт переводит
  на `/login`.
- **401** (от `login_api` при неверном пароле) — «вы ввели неправильный
  пароль», фронт показывает ошибку в форме.

Это важно не путать: 401 — «попробуйте ещё раз», 403 — «идите авторизуйтесь».

## 5. Деплой: варианты по нарастающей

1. **Один uvicorn на 8000** (как в этом проекте) — личные проекты, демо.
2. **gunicorn + UvicornWorker** — многопроцессность на одном хосте:
   ```bash
   gunicorn main:main_app --workers 4 \
     --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
   ```
   Помните: пул БД умножается на число воркеров (см. [статью 03](03-database-layer.md)).
3. **+ nginx спереди** — TLS, gzip, раздача статики, rate limit; приложение
   за прокси. Схема `nginx_pg_admin.yml` в этом репозитории — пример такой
   сборки.
4. **Контейнеры** — образ для FastAPI, отдельный образ сборки фронтенда
   с копированием `dist/` в образ бэкенда (multi-stage), PostgreSQL рядом.

Инвариант всех вариантов: **артефакт фронтенда — это каталог `dist/`**, и
его нужно лишь доставить туда, откуда его отдаст сервер.

## 6. Чекпоинт самопроверки

- [ ] Dev: браузер только на `:5173`, прокси настроен, абсолютных URL в коде нет.
- [ ] Prod: `npm run build` в пайплайне деплоя — без него сайт «старый».
- [ ] catch-all — последним через `app.router.routes.append`; `/api*` отвечает 404 JSON, а не HTML.
- [ ] Сессии — httpOnly cookie; изменяющие запросы — с CSRF-токеном.
- [ ] Неавторизованный API-доступ — 403 JSON, редирект решает SPA.
- [ ] `secret_key` — из конфига, стабильный между рестартами воркеров.
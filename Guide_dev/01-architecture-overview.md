# 01. Архитектура: две половины одного приложения

> Цикл «FastAPI + React». Предыдущая: [README](README.md) · Следующая: [02. Скелет бэкенда](02-fastapi-backend.md)

## Главная идея

Современное веб-приложение «FastAPI + React» — это **два процесса**, которые
говорят друг с другом только по JSON. Всё остальное — детали.

```
┌──────────────────── БРАУЗЕР ────────────────────┐
│                                                  │
│   index.html + bundle.js + bundle.css             │
│   React исполняется ЗДЕСЬ:                        │
│   • рисует UI (виртуальный DOM → DOM)             │
│   • роутинг по страницам (history-mode)           │
│   • состояние UI (форма, модалка, тема, юзер)     │
│   • fetch('/api/...') за данными                  │
│                                                  │
└───────────────▲───────────────────▲───────────────┘
                │ статика           │ JSON
                │ (/assets/*)       │ (/api/blog/*)
                │                   │
┌───────────────┴───────────────────┴───────────────┐
│                 СЕРВЕР: FastAPI                    │
│                                                  │
│   • раздаёт собранный фронт (mount + catch-all)   │
│   • JSON API: валидация, бизнес-логика, БД, сессии│
│   • SQLAlchemy async → PostgreSQL / SQLite        │
│                                                  │
└──────────────────────────────────────────────────┘
```

**Почему это важно держать в голове с самого начала:**

- React — это **библиотека для браузера**, а не серверный фреймворк.
  Когда вы слышите «React-приложение» — это значит «JS, который качается
  браузером и исполняется на клиенте».
- Node нужен только чтобы **собрать** JS-файлы (`npm run build`). После
  сборки Node можно выключить — сайт продолжит работать, потому что FastAPI
  просто раздаёт готовые файлы. Это критично для понимания деплоя
  ([статья 06](06-integration-deploy.md)).
- «Фронтенд-сервер» — это условие **удобной разработки** (HMR, прокси,
  типизация), а не работы сайта. В проде его нет.

## Контракт JSON API — единственная связь

Две половины не знают друг о друге ничего, кроме **формата обмена**. В этом
проекте контракт живёт в `frontend/src/types.ts` (TypeScript-зеркало
pydantic-схем) и в `fastapi-application/md_articles/api_blog.py`,
`fastapi-application/md_articles/api_auth.py`. Пример одного эндпоинта:

```
GET /api/blog/articles/{art_id}
  → 200 {"article": {"id": 7, "title": "...", "author": "Max",
                     "lang": "Rust", "section": "backend",
                     "content": "<h1>...</h1> ..."}}
  → 404 {"detail": "Article not found"}
```

Из этого контракта фронтенд-разработчик пишет TypeScript-тип и функцию запроса
(`frontend/src/api/blog.ts` — реальный код проекта):

```typescript
// GET /api/blog/articles/{art_id} — одна статья с готовым HTML-контентом.
export function getArticle(artId: number | string): Promise<{ article: Article }> {
  return getJson<{ article: Article }>(`/api/blog/articles/${artId}`);
}
```

…а бэкенд-разработчик — pydantic-схему и обработчик
(`fastapi-application/md_articles/api_blog.py:94`, реальный код):

```python
@router_blog_api.get("/articles/{art_id}", name="blog_api.article_detail")
async def article_detail(art_id: int):
    art = get_art(art_id)
    if art is None or not _is_complete(art):
        raise HTTPException(status_code=404, detail="Article not found")
    ...
    content = render_article(art.file_name, content_dir)
    return {"article": jsonable_encoder(art.model_copy(update={"content": content}).model_dump())}
```

**Контракт — это граница команд и граница понимания.** Пока он зафиксирован,
обе половины можно писать параллельно и даже разными людьми. FastAPI
бесплатно документирует контракт через OpenAPI/Swagger на `/docs` —
`curl -s http://127.0.0.1:8000/openapi.json | head -c 500` покажет всё, что
нужно фронтендеру.

## Почему SPA + JSON API, а не серверные шаблоны

| Требование | Как закрывает SPA + API |
|---|---|
| Интерактив без перезагрузок | React Router + локальное состояние |
| Переиспользование API | Тот же `/api/...` отдаёт данные мобильному приложению, скриптам, интеграциям |
| Разделение труда | Фронт правит `frontend/src`, бэк — Python; конфликтуют только в контракте |
| Скорость отклика UI | Данные — маленький JSON; разметка строится на клиенте |
| Разные клиенты | Браузер — один из многих |

Когда это **не** лучший выбор — см. [статью 07](07-alternatives.md): для
SEO-критичных контентных сайтов лучше SSR (Next.js), для маленьких
интерактивных вставок — Jinja2 + htmx.

## Три режима жизни связки

Один и тот же код существует в трёх режимах. Их важно не путать.

### Режим разработки — два процесса

```bash
cd fastapi-application && ../.venv/bin/uvicorn main:main_app --port 8000   # API
cd frontend && npm run dev                                                  # Vite :5173
```

Браузер ходит на `:5173`. Vite отдаёт исходники «как есть» с мгновенным
обновлением (HMR), а запросы `/api` и `/static` проксирует на FastAPI
(`frontend/vite.config.ts`, реальный код):

```typescript
server: {
  port: 5173,
  proxy: {
    "/api":    { target: "http://localhost:8000", changeOrigin: true },
    "/static": { target: "http://localhost:8000", changeOrigin: true },
  },
},
```

### Режим эксплуатации — один процесс

```bash
cd frontend && npm run build        # → frontend/dist/ (index.html + assets/)
cd fastapi-application && ../.venv/bin/uvicorn main:main_app --port 8000
```

FastAPI монтирует `dist/assets` и отдаёт `index.html` на любой «не-API» путь
(через catch-all — `fastapi-application/md_articles/setup_frontend.py:79`,
`spa_fallback` на строке 49). Один порт, один процесс, никакого Node.

### Режим CI/проверки

```bash
cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"
curl -s http://127.0.0.1:8000/api/blog/articles | head -c 200
```

`len(main_app.routes)` показывает, что приложение вообще собралось. На момент
написания гайда — 42.

## Главная грабля, которая стоит часа отладки

**Правки в `frontend/src/` не видны на `:8000` до пересборки.** Браузер
получает старый бандл из `dist/`. Отсюда правило:

> Разрабатываешь UI — работай через `:5173` (`npm run dev`).
> Закончил — сделай контрольный `npm run build` и проверь на `:8000`.

## Что дальше

- Как устроен скелет FastAPI-приложения — [статья 02](02-fastapi-backend.md).
- Какой слой URL-ов в этом проекте и где они появляются — [статья 10](10-url-flow.md).
- Альтернативные способы организации связки — [статья 07](07-alternatives.md).
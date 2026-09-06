# 09. SPA vs SSR: подробный разбор с кодом

> Цикл «FastAPI + React». Предыдущая: [08. Чеклист нового проекта](08-checklist-new-project.md)

Краткое сравнение способов — в [07. Альтернативные подходы](07-alternatives.md).
Здесь — развёрнутый разбор **двух конкретных способов** с полными примерами кода
и сетевыми диалогами: что делает Vite-SPA (этот проект) и что делал бы Next.js-SSR,
если бы мы его выбрали. Один и тот же сценарий — открытие пользователем статьи —
проигран дважды, чтобы разница была видна наглядно.

## 1. Терминология: что есть что

| Термин | Значение | Кто рендерит HTML |
|---|---|---|
| **SPA** (Single-Page Application) | Один `index.html`, контент подменяется JavaScript-ом | браузер (React в runtime) |
| **CSR** (Client-Side Rendering) | То же, что SPA — HTML рендерится в браузере | браузер |
| **SSR** (Server-Side Rendering) | HTML рендерится на сервере на каждый запрос | Node-сервер (Next.js, Remix) |
| **SSG** (Static Site Generation) | HTML собирается заранее при деплое | сборщик (Next.js `getStaticProps`) |
| **Hydration** | «Пробуждение» SSR-HTML: React подхватывает готовую разметку и добавляет интерактив | браузер после SSR-ответа |

**Vite** — это инструмент сборки и dev-сервер. Сам по себе он не «SPA» и не
«SSR»: Vite умеет собирать и то, и другое. В этом проекте Vite настроен на
**CSR** (SPA): рендерит React в браузере. **Next.js** — это фреймворк *поверх*
React, который добавляет SSR/SSG из коробки; в нём Vite не используется, вместо
него свой сборщик на webpack/turbopack.

Так что правильно говорить: «Vite + React = CSR/SPA», «Next.js = SSR/SSG
(и CSR тоже, по выбору)». Не «Vite — это SPA», не «Next.js — это SSR».

## 2. Сценарий, который проигрываем

Пользователь вбивает в адресную строку браузера `http://localhost:3000/art/Max/123`
(или `http://127.0.0.1:8000/art/Max/123` в этом проекте) и видит статью.
Смотрим, что происходит на каждом этапе.

---

## 3. Способ A. Vite + React (CSR / SPA) — как в этом проекте

### 3.1. Архитектура в одну картинку

```
            Cold start (F5, прямая ссылка)
                       │
                       ▼
   ┌──────────────────────────────────────────┐
   │ 1. GET /art/Max/123                      │
   │    FastAPI (catch-all в                  │
   │    frontend_routing.py) → index.html     │
   └──────────────────────────────────────────┘
                       │
                       ▼
   ┌──────────────────────────────────────────┐
   │ 2. GET /assets/index-xxx.js              │
   │    FastAPI (mount /assets, StaticFiles)  │
   │    → JS-бандл (из disk cache на F5)      │
   └──────────────────────────────────────────┘
                       │
                       ▼
   ┌──────────────────────────────────────────┐
   │ 3. React в браузере:                     │
   │    BrowserRouter парсит /art/Max/123,    │
   │    рендерит <ArticlePage>                │
   └──────────────────────────────────────────┘
                       │
                       ▼
   ┌──────────────────────────────────────────┐
   │ 4. useEffect → fetch /api/blog/.../123   │
   │    FastAPI (router_blog_api) → JSON      │
   └──────────────────────────────────────────┘
                       │
                       ▼
   ┌──────────────────────────────────────────┐
   │ 5. <MarkdownContent html={...}/>         │
   │    вставляет готовый HTML                 │
   └──────────────────────────────────────────┘

            Навигация внутри SPA (клик по ссылке)
                       │
                       ▼
   ┌──────────────────────────────────────────┐
   │ • НЕТ GET на HTML (pushState)            │
   │ • НЕТ GET на бандл (уже в памяти)        │
   │ • Один GET на /api/blog/...              │
   └──────────────────────────────────────────┘
```

### 3.2. Серверный код (FastAPI)

Два независимых слоя маршрутов в одном процессе.

**Слой 1: SPA catch-all** — `../fastapi-application/md_articles/frontend_routing.py`:

```python
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

from base_dir_path import BASE_DIR

FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
ASSETS_DIR = FRONTEND_DIST / "assets"
INDEX_HTML = FRONTEND_DIST / "index.html"


async def spa_fallback(request: Request) -> FileResponse | JSONResponse:
    """Любой GET, не начинающийся с /api → index.html (для React Router)."""
    path = request.url.path
    if path == "/api" or path.startswith("/api/"):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    if not INDEX_HTML.is_file():
        return JSONResponse(
            status_code=404,
            content={"detail": "Frontend не собран: выполните npm run build"},
        )
    return FileResponse(INDEX_HTML)


def setup_react_routing_assets(app: FastAPI) -> None:
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR, check_dir=False))
    app.router.routes.append(
        Route("/{full_path:path}", spa_fallback, methods=["GET"])
    )
```

**Слой 2: JSON API блога** — `fastapi-application/md_articles/api_blog.py`:

```python
from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from md_articles.schema_art import (
    ArticleLang,
    get_art,
    get_articles,
    render_article,
)

router_blog_api = APIRouter(prefix="/api/blog", tags=["blog api"])


class SectionOut(BaseModel):
    name: str
    label: str
    count: int


@router_blog_api.get("/sections", name="blog_api.sections")
async def sections_list():
    """Список разделов с количеством полных статей."""
    counts: dict[str, int] = {}
    for art in get_articles():
        if art.section and _is_complete(art):
            counts[art.section] = counts.get(art.section, 0) + 1
    sections = [
        SectionOut(name=n, label=n, count=c)
        for n, c in sorted(counts.items())
    ]
    return {"sections": jsonable_encoder(sections)}


@router_blog_api.get("/articles", name="blog_api.articles")
async def articles_list(section: str | None = Query(default=None)):
    """Список полных статей; section — фильтр по разделу."""
    articles = get_articles()
    result = [
        _article_summary(art)
        for art in articles
        if _is_complete(art) and (section is None or art.section == section)
    ]
    return {"articles": jsonable_encoder(result)}


@router_blog_api.get("/articles/{art_id}", name="blog_api.article_detail")
async def article_detail(art_id: int):
    """Полный контент одной статьи (Markdown → HTML)."""
    art = get_art(art_id)
    if art is None or not _is_complete(art):
        raise HTTPException(status_code=404, detail="Article not found")

    import os
    from md_articles.schema_art import get_path_dir
    if not os.path.exists(get_path_dir() / art.file_name):
        raise HTTPException(status_code=404, detail="Article not found")

    content = render_article(art.file_name, get_path_dir())
    article = art.model_copy(update={"content": content})
    return {"article": jsonable_encoder(article.model_dump())}
```

### 3.3. Клиентский код (React + TypeScript)

**Базовый API-клиент** — `frontend/src/api/client.ts`:

```typescript
export class ApiError extends Error {
  status: number;
  data: unknown;
  constructor(status: number, data: unknown) {
    super(`API error ${status}`);
    this.status = status;
    this.data = data;
  }
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  return fetch(path, { credentials: 'include', ...init });
}

export async function getJson<T = unknown>(path: string): Promise<T> {
  const res = await request(path);
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}
```

**Доменный клиент блога** — `frontend/src/api/blog.ts`:

```typescript
import { getJson } from './client';
import type { Article, Section } from '../types';

export function getArticles(section?: string): Promise<{ articles: Article[] }> {
  const query = section ? `?section=${encodeURIComponent(section)}` : '';
  return getJson<{ articles: Article[] }>(`/api/blog/articles${query}`);
}

export function getSections(): Promise<{ sections: Section[] }> {
  return getJson<{ sections: Section[] }>('/api/blog/sections');
}

export function getArticle(artId: number | string): Promise<{ article: Article }> {
  return getJson<{ article: Article }>(`/api/blog/articles/${artId}`);
}
```

**Типы контракта** — `frontend/src/types.ts`:

```typescript
export interface Article {
  author: string;
  lang: string;
  art_id: number;
  title: string;
  file_name: string;
  section?: string;
  content?: string;      // только в ответе /articles/{art_id}
  complete?: boolean;
  file_exists?: boolean;
}

export interface Section {
  name: string;
  label: string;
  count: number;
}
```

**Роутинг** — `frontend/src/main.tsx` + `frontend/src/App.tsx`:

```tsx
// main.tsx
import { BrowserRouter } from 'react-router-dom';
import App from './App';

createRoot(document.getElementById('root')!).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>,
);

// App.tsx
<Routes>
  <Route element={<Layout />}>
    <Route path="/" element={<HomePage />} />
    <Route path="/section/:name" element={<HomePage />} />
    <Route path="/art/:author/:artId" element={<ArticlePage />} />
    {/* ... */}
  </Route>
</Routes>
```

**Страница статьи** — `frontend/src/pages/ArticlePage.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getArticle } from '../api/blog';
import type { Article } from '../types';
import MarkdownContent from '../components/MarkdownContent';

export default function ArticlePage() {
  const { author, artId } = useParams<{ author: string; artId: string }>();
  const [article, setArticle] = useState<Article | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setArticle(null);
    setNotFound(false);
    getArticle(artId ?? '')
      .then((data) => {
        if (cancelled) return;
        if (!data.article || data.article.author !== author) {
          setNotFound(true);
        } else {
          setArticle(data.article);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        if (err?.status === 404) setNotFound(true);
      });
    return () => { cancelled = true; };
  }, [author, artId]);

  if (notFound) return <div className="page-stub">Статья не найдена.</div>;
  if (article === null) return <div className="page-stub">Загрузка...</div>;

  return (
    <div className="page-stub">
      <h1>{article.title}</h1>
      <p className="text-muted">{article.author}</p>
      <MarkdownContent html={article.content ?? ''} />
    </div>
  );
}
```

**`<MarkdownContent>`** — `frontend/src/components/MarkdownContent.tsx`
(получает уже готовый HTML от сервера):

```tsx
export default function MarkdownContent({ html }: { html: string }) {
  return <div className="markdown-body" dangerouslySetInnerHTML={{ __html: html }} />;
}
```

### 3.4. Сетевой диалог — холодный заход на `/art/Max/123`

```http
GET /art/Max/123 HTTP/1.1
Host: 127.0.0.1:8000
Cookie: session=...

HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
```
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <script type="module" crossorigin src="/assets/index-AbCdEf12.js"></script>
    <link rel="stylesheet" href="/assets/index-XyZ123.css" />
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
```
Пустой `<div id="root"></div>` — React ещё ничего не отрисовал. Контента в HTML нет.

```http
GET /assets/index-AbCdEf12.js HTTP/1.1
Host: 127.0.0.1:8000

HTTP/1.1 200 OK
Content-Type: application/javascript
Cache-Control: public, max-age=31536000, immutable
```
Сам бандл (~150–500 КБ в gzip). На F5 приходит из disk cache, поэтому в DevTools → Network
видно `(disk cache)` в колонке Size.

Дальше React в браузере делает запрос контента:

```http
GET /api/blog/articles/123 HTTP/1.1
Host: 127.0.0.1:8000
Cookie: session=...

HTTP/1.1 200 OK
Content-Type: application/json
```
```json
{
  "article": {
    "author": "Max",
    "lang": "ru",
    "art_id": 123,
    "title": "Про SPA и SSR",
    "file_name": "guides/spa-vs-ssr.md",
    "section": "guides",
    "content": "<h1>Про SPA и SSR</h1>\n<p>...</p>\n<pre><code class=\"language-rust\">fn main() { ... }</code></pre>"
  }
}
```

`MarkdownContent` вставляет готовый HTML, `highlight.js` (подключён в
`frontend/index.html`) подсвечивает блоки кода.

### 3.5. Сетевой диалог — навигация внутри SPA (клик по ссылке)

Пользователь на главной кликнул на карточку статьи `Max/123`. В браузере уже
есть `index.html` (в памяти), есть бандл (в памяти). Происходит:

```js
// React Router внутри делает:
history.pushState({}, '', '/art/Max/123');
// Никакого HTTP-запроса.
```
Дальше `<ArticlePage>` монтируется, его `useEffect` шлёт **только**:

```http
GET /api/blog/articles/123 HTTP/1.1
```

Один запрос — и страница готова. Никакого `GET /art/Max/123`, никакого бандла.

### 3.6. Сетевой диалог — обновление F5 на открытой статье

Браузер обязан послать GET на текущий URL (это поведение `F5`/`Reload`),
потому что HTML мог измениться:

```http
GET /art/Max/123 HTTP/1.1
HTTP/1.1 200 OK
Content-Type: text/html
```
Тот же `index.html`. Контента в нём снова нет.

```http
GET /assets/index-AbCdEf12.js HTTP/1.1
HTTP/1.1 200 OK
   (или 304 Not Modified — если бандл не менялся)
   Size: (disk cache)
```
Бандл из кэша браузера — на самом деле HTTP-запрос короткий, тело не передаётся.

```http
GET /api/blog/articles/123 HTTP/1.1
HTTP/1.1 200 OK
Content-Type: application/json
```
Контент статьи.

**Итого на F5:** 3 запроса, но бандл — из кэша. Реально по сети идёт только
`index.html` (~1 КБ) + JSON.

### 3.7. Что в DevTools → Network на каждом сценарии

| Сценарий | GET HTML | GET bundle | GET JSON |
|---|---|---|---|
| Холодный заход (первый раз на сайте) | 200, ~1 КБ | 200, ~200 КБ | 200, JSON |
| F5 на открытой статье | 200, ~1 КБ | (disk cache) | 200, JSON |
| Клик по ссылке в SPA | — | — | 200, JSON |
| F5 на главной странице (со списком) | 200, ~1 КБ | (disk cache) | 200, JSON список |

---

## 4. Способ C. Next.js (SSR) — как это выглядело бы

В этом проекте Next.js не используется. Ниже — **как выглядел бы тот же
сценарий**, если бы мы выбрали Next.js. Код не из проекта, это стандартный
паттерн Next.js App Router (Next 14+).

### 4.1. Архитектура в одну картинку

```
            Cold start (F5, прямая ссылка)
                       │
                       ▼
   ┌──────────────────────────────────────────┐
   │ 1. GET /art/Max/123                      │
   │    Next.js (Node):                       │
   │    a) выполняет React-компонент          │
   │       ArticlePage на СЕРВЕРЕ             │
   │    b) тот внутри сам fetch'ит            │
   │       FastAPI /api/blog/articles/123     │
   │    c) рендерит HTML с контентом          │
   │    d) отдаёт готовый HTML +              │
   │       сериализованный state для          │
   │       hydration                          │
   └──────────────────────────────────────────┘
                       │
                       ▼
   ┌──────────────────────────────────────────┐
   │ 2. GET /_next/static/...js               │
   │    Next.js: hydration-бандл              │
   │    (маленький, обычно ~50–150 КБ)        │
   └──────────────────────────────────────────┘
                       │
                       ▼
   ┌──────────────────────────────────────────┐
   │ 3. Браузер: hydration                    │
   │    React «оживляет» готовый HTML,        │
   │    навешивает обработчики.               │
   │    Никакого нового GET на JSON.          │
   └──────────────────────────────────────────┘

            Навигация внутри SPA (клик по ссылке)
                       │
                       ▼
   ┌──────────────────────────────────────────┐
   │ • <Link prefetch>: Next.js уже           │
   │   подгрузил данные для соседних страниц  │
   │ • Переход мгновенный (state уже есть)   │
   │ • Если данных нет — клиентский           │
   │   fetch через Server Action или /api      │
   └──────────────────────────────────────────┘
```

### 4.2. Структура проекта Next.js

```
my-blog-next/
├── package.json
├── next.config.js
└── app/                          # App Router
    ├── layout.tsx                # общий каркас (хедер, футер)
    ├── page.tsx                  # главная (список)
    ├── art/
    │   └── [author]/
    │       └── [artId]/
    │           └── page.tsx      # статья (SSR)
    ├── api/
    │   └── revalidate/route.ts   # ISR-триггер
    └── lib/
        └── api.ts                # клиент FastAPI
```

### 4.3. Серверный код (Next.js)

**Страница со списком** — `app/page.tsx`:

```tsx
// Next.js 14+: по умолчанию серверный компонент.
// Этот код выполняется на Node-сервере Next.js при каждом запросе.
import Link from 'next/link';

async function getArticles(): Promise<{ articles: Article[] }> {
  // Серверный fetch — Node делает запрос к FastAPI.
  const res = await fetch('http://fastapi:8000/api/blog/articles', {
    // ISR: перечитывать каждые 60 секунд, не чаще.
    next: { revalidate: 60 },
  });
  if (!res.ok) throw new Error('Failed to load articles');
  return res.json();
}

export default async function HomePage() {
  const { articles } = await getArticles();

  return (
    <main>
      <h1>Все статьи</h1>
      <ul>
        {articles.map((a) => (
          <li key={a.art_id}>
            <Link href={`/art/${a.author}/${a.art_id}`}>
              {a.title}
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
```

**Страница статьи (SSR)** — `app/art/[author]/[artId]/page.tsx`:

```tsx
import { notFound } from 'next/navigation';
import MarkdownContent from '@/components/MarkdownContent';

// generateMetadata — для <title> и OpenGraph (важно для SEO/соцсетей).
export async function generateMetadata(
  { params }: { params: { author: string; artId: string } },
) {
  const { article } = await getArticle(params.artId);
  if (!article) return { title: 'Не найдено' };
  return {
    title: article.title,
    description: article.title,
    openGraph: { title: article.title },
  };
}

async function getArticle(artId: string) {
  const res = await fetch(
    `http://fastapi:8000/api/blog/articles/${artId}`,
    { next: { revalidate: 60 } },
  );
  if (res.status === 404) return { article: null };
  if (!res.ok) throw new Error('Failed to load article');
  return res.json();
}

// Серверный компонент: выполняется на Node при каждом запросе.
// Возвращает готовый HTML; React в браузере потом «гидратирует».
export default async function ArticlePage(
  { params }: { params: { author: string; artId: string } },
) {
  const { article } = await getArticle(params.artId);
  if (!article || article.author !== params.author) notFound();

  return (
    <main>
      <h1>{article.title}</h1>
      <p>{article.author}</p>
      <MarkdownContent html={article.content ?? ''} />
    </main>
  );
}
```

**Клиент FastAPI** — `app/lib/api.ts`:

```ts
// Этот код работает ТОЛЬКО на Node-сервере Next.js (server components).
// На клиент он не попадает — адрес `http://fastapi:8000` клиенту недоступен.
const FASTAPI_URL = process.env.FASTAPI_INTERNAL_URL ?? 'http://fastapi:8000';

export async function getArticle(artId: number | string) {
  const res = await fetch(`${FASTAPI_URL}/api/blog/articles/${artId}`, {
    // ISR / кэш. Можно заменить на { cache: 'no-store' } для чистого SSR.
    next: { revalidate: 60 },
  });
  if (res.status === 404) return { article: null };
  if (!res.ok) throw new Error('Failed');
  return res.json();
}
```

### 4.4. Клиентский код (минимальный)

**`<MarkdownContent>`** — клиент-серверный компонент без состояния:

```tsx
// app/components/MarkdownContent.tsx
export default function MarkdownContent({ html }: { html: string }) {
  return <div className="markdown-body" dangerouslySetInnerHTML={{ __html: html }} />;
}
```

В Next.js **нет** `api/client.ts` с `credentials: 'include'` для основной
выдачи: данные уже в HTML, второй запрос делать не нужно. Это и есть
главное отличие от CSR.

### 4.5. Сетевой диалог — холодный заход на `/art/Max/123`

```http
GET /art/Max/123 HTTP/1.1
Host: my-blog.example.com

HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
```
```html
<!doctype html>
<html>
  <head>
    <title>Про SPA и SSR — мой блог</title>
    <meta property="og:title" content="Про SPA и SSR" />
  </head>
  <body>
    <main>
      <h1>Про SPA и SSR</h1>
      <p>Max</p>
      <div class="markdown-body">
        <h1>Про SPA и SSR</h1>
        <p>...</p>
        <pre><code class="language-rust">fn main() { ... }</code></pre>
      </div>
    </main>
    <script src="/_next/static/chunks/main-AbCd.js"></script>
    <!-- hydration state: {"article":{"art_id":123,...}} -->
    <script>self.__next_f.push([1, "..."])</script>
  </body>
</html>
```

**Обратите внимание:** контент статьи (`<h1>Про SPA и SSR</h1>`) уже в HTML.
Поисковый робот Google увидит текст статьи без исполнения JavaScript. Соцсети
при парсинге URL получат `<title>` и `<meta property="og:title">`.

```http
GET /_next/static/chunks/main-AbCd.js HTTP/1.1

HTTP/1.1 200 OK
Content-Type: application/javascript
Cache-Control: public, max-age=31536000, immutable
```

Гидрационный бандл — обычно меньше, чем полный бандл CSR-SPA (нет роутера,
нет слоя API-клиента для основной выдачи).

Никакого запроса `GET /api/blog/articles/123` от браузера нет — данные уже в HTML.

### 4.6. Сетевой диалог — навигация внутри SPA (клик по `<Link>`)

Next.js `<Link>` с `prefetch` (по умолчанию в production):

```tsx
<Link href={`/art/Max/123`}>...</Link>
```
При попадании ссылки в viewport Next.js **заранее** (на клиенте, в фоне)
загружает RSC-чанк и данные для этой страницы. При клике мгновенный переход —
нет даже спиннера «Загрузка...».

Если данных нет в кэше (например, динамический путь без `prefetch`):
```http
GET /art/Max/123?_rsc=abc HTTP/1.1
HTTP/1.1 200 OK
Content-Type: text/x-component
```
Это RSC-формат (React Server Components) — специальный «транспорт» для
обновления server-компонентов без полной перезагрузки HTML.

### 4.7. Сетевой диалог — обновление F5 на открытой статье

```http
GET /art/Max/123 HTTP/1.1
HTTP/1.1 200 OK
Content-Type: text/html
```
Полный HTML с контентом (рендерится заново или берётся из ISR-кэша).

```http
GET /_next/static/...js HTTP/1.1
HTTP/1.1 200 OK  (или 304)
```
Гидрационный бандл из кэша.

Никакого отдельного JSON-запроса на контент.

### 4.8. Что в DevTools → Network

| Сценарий | GET HTML | GET bundle | GET JSON |
|---|---|---|---|
| Холодный заход | 200, **с контентом** | 200, гидрационный | — |
| F5 на открытой статье | 200, с контентом (или 304) | (cache) | — |
| Клик по `<Link>` (prefetched) | — | — | — |
| Клик по `<Link>` (cold) | — | RSC-чанк | внутри RSC |
| Переход на динамический путь | 200, с контентом | (cache) | — |

---

## 5. Прямое сравнение на одном сценарии

### 5.1. Холодный заход `/art/Max/123`

| Шаг | Vite + React (CSR) | Next.js (SSR) |
|---|---|---|
| 1 | `GET /art/Max/123` → пустой `index.html` (~1 КБ) | `GET /art/Max/123` → HTML **с контентом** (~5 КБ) |
| 2 | `GET /assets/index-xxx.js` → бандл (~200 КБ) | `GET /_next/static/...js` → гидрационный бандл (~80 КБ) |
| 3 | React рендерит `<ArticlePage>` (пусто) | Hydration: React «оживляет» готовый HTML |
| 4 | `useEffect` → `GET /api/blog/articles/123` → JSON | — (уже не нужен) |
| 5 | `<MarkdownContent>` вставляет HTML | — |
| **Время до контента** | **~4 шага, 2–3 запроса** | **~2 шага, 1–2 запроса** |
| **HTML до гидратации** | пустой (нет `<h1>`) | полный (есть `<h1>` и текст) |
| **Размер первой загрузки** | ~1 КБ + ~200 КБ JS + ~3 КБ JSON = **~204 КБ** | ~5 КБ HTML + ~80 КБ JS = **~85 КБ** |

### 5.2. Навигация внутри SPA (клик по ссылке)

| Шаг | Vite + React (CSR) | Next.js (SSR) |
|---|---|---|
| 1 | `history.pushState` (без HTTP) | `<Link prefetch>` уже подгрузил данные |
| 2 | `useEffect` → `GET /api/blog/...` → JSON | мгновенный рендер из кэша |
| **Запросов** | **1 (JSON)** | **0 (если prefetch сработал)** |

### 5.3. F5 на открытой странице

| Шаг | Vite + React (CSR) | Next.js (SSR) |
|---|---|---|
| 1 | `GET /art/Max/123` → `index.html` | `GET /art/Max/123` → HTML с контентом |
| 2 | `GET /assets/index-xxx.js` → (disk cache) | `GET /_next/static/...js` → (cache) |
| 3 | `GET /api/blog/articles/123` → JSON | — |
| **Запросов по сети** | **2 (HTML + JSON)** | **1 (HTML)** |

### 5.4. SEO и соцсети — решающее отличие

| Что видит Googlebot | Vite + React (CSR) | Next.js (SSR) |
|---|---|---|
| `<title>` | есть (статический) | динамический из `generateMetadata` |
| `<meta name="description">` | пустой или статический | из `generateMetadata` |
| `<meta property="og:*">` | пустые | динамические |
| Контент статьи в HTML | **нет** (JS должен исполниться) | **да** |
| Может ли Googlebot проиндексировать | да, через рендеринг JS (медленно) | **да, моментально** |
| Telegram/Slack/VK превью | пустое | с заголовком и описанием |

---

## 6. Где CSR проигрывает, где SSR проигрывает

### Где CSR (этот проект) выигрывает

- **Один сервис.** Не нужен Node-сервер в рантайме — FastAPI сам раздаёт
  статику и обслуживает API. Деплой — один процесс.
- **Простота деплоя.** `cd frontend && npm run build` → коммитим рядом или
  собираем в CI → `uvicorn main:main_app`. Без отдельного Node-сервиса,
  без PM2, без балансировки между Node и Python.
- **Меньше серверной нагрузки при навигации.** Каждый переход по ссылке —
  один лёгкий JSON-запрос к FastAPI. SSR-сервер рендерит HTML на каждый
  переход (если без кэша).
- **Не нужен второй язык в рантайме.** Команда, которая умеет Python +
  React/TS, не должна ещё держать Node-инфраструктуру.
- **API переиспользуется другими клиентами.** Мобильное приложение,
  Telegram-бот, CLI — все ходят по тому же `/api/blog`, не завися от Next.js.

### Где SSR (Next.js) выигрывает

- **SEO из коробки.** Поисковики и соцсети видят готовый HTML. Для блога,
  медиа, маркетплейса это часто критично.
- **Быстрая первая отрисовка (FCP).** Контент появляется до загрузки
  гидрационного бандла. На медленном интернете разница заметна.
- **Core Web Vitals лучше.** LCP (Largest Contentful Paint) измеряется по
  времени появления основного контента — в SSR это время первого байта HTML,
  в CSR — время загрузки + парсинга JS + fetch + render.
- **OpenGraph / Twitter Cards.** `generateMetadata` отдаёт динамические
  `<meta>` для красивого превью в соцсетях. В CSR это требует отдельного
  рендера или внешнего сервиса (prerender.io и т.п.).
- **Меньше JavaScript на клиенте.** Гидрационный бандл меньше полного
  CSR-бандла (нет API-клиента, нет роутера для основного вывода).

### Где CSR проигрывает

- **SEO требует обходного пути.** Google индексирует CSR, но с задержкой;
  Яндекс и соцсети — нет. Для публичного контентного сайта это серьёзная
  потеря. Решения — `prerender.io`, статический пререндер, или гибрид (см. ниже).
- **Первый контент позже.** На медленной сети спиннер «Загрузка...» виден
  дольше.
- **Больше работы на клиенте.** CSR-бандл обычно больше гидрационного.

### Где SSR проигрывает

- **Два рантайма.** Node + Python. Два деплоя, два мониторинга, двойная
  квалификация команды.
- **Серверный рендер = нагрузка.** Каждый запрос — рендер React в Node.
  Для блога с 1000 RPS это серьёзная нагрузка. Решения — ISR (revalidate),
  Edge-рендеринг, статическая генерация для редко меняющихся страниц.
- **Сложнее дебажить.** SSR-bug может проявиться только на сервере
  (например, `window is not defined`), в CSR всё в браузере.
- **Vendor lock-in.** Next.js = React Server Components, специальные
  соглашения (`'use client'`), свой роутер. Миграция на другой SSR-фреймворк
  дороже, чем миграция между CSR-подходами.

---

## 7. Гибридные варианты (когда обоим нужны плюсы)

### 7.1. SSG для статичных страниц + CSR для интерактива

```tsx
// app/art/[author]/[artId]/page.tsx (Next.js)
export async function generateStaticParams() {
  const { articles } = await getArticles();
  return articles.map((a) => ({
    author: a.author,
    artId: String(a.art_id),
  }));
}

// Страница генерируется при сборке, ISR пересобирает раз в час.
export default async function ArticlePage({ params }) {
  // ...
}
```

Контент собирается в HTML при `next build` → деплой как статика. Для блога
(где статьи меняются раз в неделю) — идеально. Для дашборда — не подходит.

### 7.2. Astro: «островки» интерактива в статическом HTML

Astro по умолчанию рендерит компоненты в HTML на сервере, а интерактивные
«островки» (React, Vue, Svelte) подгружает отдельно:

```astro
---
// pages/art/[author]/[artId].astro
import { getArticle } from '@/lib/api';
const { article } = await getArticle(Astro.params.artId);
---
<article>
  <h1>{article.title}</h1>
  <!-- Серверный рендер, 0 JS -->
  <div set:html={article.content} />

  <!-- Интерактивный «островок»: только эта часть грузит JS -->
  <Comments client:visible articleId={article.art_id} />
</article>
```

Статика для всего, JS только там, где реально нужен интерактив. Подробно
в [07. Альтернативные подходы](07-alternatives.md), способ E.

### 7.3. Remix — серверный рендер с упором на формы

Похож на Next.js, но заточен под data-loading через `<Form>` / `loader` /
`action`. Хорош для приложений с большим количеством форм.

---

## 8. Как выбрать для своего проекта

| Вопрос | Если «да» | Если «нет» |
|---|---|---|
| Сайт должны находить в Google? | SSR (Next.js, Remix, Astro SSG) | CSR (Vite + React) |
| Важны превью в соцсетях? | SSR/SSG | CSR (или ручной пререндер) |
| Один разработчик / одна команда? | CSR проще | SSR ок |
| Много форм и редкий рендер? | Remix | Next.js |
| Много интерактива (фильтры, drag)? | CSR ок | SSR ок (оба умеют) |
| Мобильное приложение тоже? | CSR (API переиспользуется) | любой |
| Очень высокий трафик? | SSG / Edge SSR | CSR с CDN-кешем |
| Учебный проект? | CSR (как здесь) | — |

**В этом проекте:** учебный демо-блог, контент индексируется поиском
не критичен (есть `/api/blog` для любого клиента), один разработчик,
один сервис. → **CSR (Vite + React)** — разумный выбор. Если бы блог
был публичным и нужно было SEO — переехали бы на **Next.js (App Router,
ISR)**.

---

## 9. Чекпоинт самопроверки

- [ ] Понимаете разницу между «Vite = SPA» и «Next.js = SSR»: Vite — это
      сборщик (умеет оба режима), Next.js — фреймворк с SSR по умолчанию.
- [ ] Можете нарисовать сетевой диалог холодного захода для CSR и SSR.
- [ ] Понимаете, почему в CSR на F5 приходит пустой `index.html` — это
      не баг, а фича: контент приходит вторым JSON-запросом.
- [ ] Знаете, что в Next.js `<Link prefetch>` заранее подгружает данные
      для соседних страниц, и клик по ссылке может не делать HTTP-запрос.
- [ ] Понимаете, что в SPA `useEffect → fetch` — единственный способ
      получить данные, и React ничего не знает о контенте до этого момента.
- [ ] Умеете объяснить, почему CSR-сайт плохо индексируется: Googlebot
      видит пустой `<div id="root">`, а не контент.
- [ ] Знаете, что переход между CSR-страницами идёт через `pushState`,
      а не через HTTP — и именно поэтому один и тот же `index.html`
      обслуживает все URL.

## 10. Как сделать SSR на Vite: что меняется в этом проекте

Если бы мы захотели остаться на Vite (не уходить на Next.js) и при этом
получить SSR — это возможно через фреймворк **vite-plugin-ssr** (он же
[`vike`](https://vike.dev/), переименован в 2024). Подход радикально
отличается от Next.js тем, что **архитектуру приложения вы проектируете
сами**: нет ни `app/`, ни `generateMetadata`, ни `'use client'` — обычный
React-код, который вы пишете как для CSR, плюс один Node-express-сервер
для рендера и FastAPI остаётся API-бэкендом.

> **Важно:** Vike (как и сам Vite) требует **Node в рантайме** — и в dev, и
> в проде. Это двухрантаймная схема (Node + Python), тот же класс решений,
> что и Next.js + FastAPI. Если главная цель перехода — убрать Node, Vike
> не поможет: для React-SSR без Node альтернатив нет (см. таблицу в
> [07. Альтернативные подходы](07-alternatives.md)). В этом проекте CSR
> выбран именно ради одного Python-процесса.

### 10.1. Что появляется в стеке

```jsonc
// frontend/package.json — изменения
{
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.30.0",
    // новое:
    "vike": "^0.4.0",            // фреймворк SSR (бывший vite-plugin-ssr)
    "express": "^4.19.0"         // Node-сервер, на котором крутится Vike
  },
  "devDependencies": {
    "vite": "^6.0.0",
    // новое (если ещё нет):
    "vite-plugin-ssr": "^0.4.0"
  },
  "scripts": {
    "dev": "vite",                  // dev: Vite + HMR (SSR через middleware)
    "build": "vite build",          // клиент + сервер бандлы
    "start": "node dist/server.js"  // прод: Node-express + Vike SSR
  }
}
```

`tsc` из `build` можно оставить (проверка типов), но компилирует теперь
Vite, а не `tsc`.

### 10.2. Структура файлов — что добавить, что убрать

```
frontend/
├── package.json
├── vite.config.ts                 # правится: добавляется vike-плагин
├── tsconfig.json
├── server.ts                      # НОВОЕ: express-сервер для SSR
├── renderer/                      # НОВОЕ: SSR-обвязка Vike
│   ├── _default.page.tsx          # общий каркас (Layout, ThemeProvider, AuthProvider)
│   ├── _default.page.server.tsx   # server-render: что в <head>, onBeforeRender
│   └── _error.page.tsx            # страница 404/500
├── pages/                         # НОВОЕ (не путать с src/pages/) — роуты Vike
│   ├── index.tsx                  # /             — список статей (SSR)
│   ├── art/
│   │   └── @author/
│   │       └── @artId/
│   │           └── index.tsx      # /art/Max/123 — статья (SSR)
│   └── about.tsx                  # /about
├── src/                           # остаётся: компоненты, типы
│   ├── api/                       # остаётся: client.ts, blog.ts, auth.ts
│   │                              # (на сервере тоже работают, через node-fetch)
│   ├── components/
│   ├── context/
│   ├── hooks/
│   ├── types.ts
│   └── ...
├── src/pages/                     # УБРАТЬ: HomePage, ArticlePage и т.п.
│                                  # становятся pages/index.tsx, pages/art/.../index.tsx
└── entry-client.tsx               # НОВОЕ: гидрация на клиенте
└── entry-server.tsx               # НОВОЕ: рендер на сервере (часто авто-генерируется Vike)
```

**Главное изменение:** файлы из `src/pages/` (HomePage, ArticlePage,
RegisterPage и т.д.) **переезжают** в корень `pages/` и становятся
файлами роутинга Vike. Их экспорт по умолчанию — это React-компонент,
который Vike рендерит и на сервере, и на клиенте.

### 10.3. Что меняется в vite.config.ts

```ts
// frontend/vite.config.ts
import { react } from '@vitejs/plugin-react';
import vike from 'vike/plugin';          // <-- новое

export default {
  plugins: [
    react(),
    vike(),                             // <-- новое
  ],
  server: {
    port: 5173,
    proxy: {
      '/api':  'http://127.0.0.1:8000', // dev: прокси к FastAPI
      '/static': 'http://127.0.0.1:8000',
    },
  },
};
```

### 10.4. Server entry — Node-express с Vike

```ts
// frontend/server.ts (новый файл)
import express from 'express';
import { createServer } from 'vite';
import vike from 'vike/express';

async function start() {
  const app = express();

  // В dev — Vite-сервер с middleware-режимом (HMR + SSR на лету).
  // В build — собранный бандл Vike из dist/server/.
  if (process.env.NODE_ENV !== 'production') {
    const viteServer = await createServer({
      server: { middlewareMode: true },
      appType: 'custom',
    });
    app.use(viteServer.middlewares);
  }

  // Vike подключает свой middleware: ловит все GET, рендерит на сервере.
  await vike(app, { render: renderPage });

  app.listen(3000, () => console.log('SSR on http://localhost:3000'));
}

start();
```

### 10.5. Страница со списком — теперь SSR

```tsx
// frontend/pages/index.tsx (новый — бывший src/pages/HomePage.tsx)
import { useData } from 'vike/react/useData';
import type { Data } from './+data';  // см. ниже

export default function HomePage() {
  // Vike передаёт данные, загруженные на сервере, через хук useData.
  // Никакого useEffect + fetch на клиенте — данные уже пришли с HTML.
  const { articles } = useData<Data>();

  return (
    <main>
      <h1>Все статьи</h1>
      <ul>
        {articles.map((a) => (
          <li key={a.art_id}>
            <a href={`/art/${a.author}/${a.art_id}`}>{a.title}</a>
          </li>
        ))}
      </ul>
    </main>
  );
}
```

```ts
// frontend/pages/+data.ts (Vike-конвенция)
// Эта функция выполняется ТОЛЬКО на сервере при каждом запросе
// (или при ISR, если настроить). Результат сериализуется в HTML и
// попадает в useData() на клиенте.
import type { Article } from '../src/types';

export type Data = { articles: Article[] };

export default async function data(): Promise<Data> {
  const res = await fetch('http://127.0.0.1:8000/api/blog/articles');
  if (!res.ok) throw new Error('Failed to load articles');
  const { articles } = await res.json();
  return { articles };
}
```

### 10.6. Страница статьи с динамическим параметром

```tsx
// frontend/pages/art/@author/@artId/index.tsx
import { useData } from 'vike/react/useData';
import type { Data } from './+data';

export default function ArticlePage() {
  const { article, notFound } = useData<Data>();
  if (notFound || !article) return <h1>Статья не найдена</h1>;

  return (
    <main>
      <h1>{article.title}</h1>
      <p>{article.author}</p>
      <div
        className="markdown-body"
        dangerouslySetInnerHTML={{ __html: article.content ?? '' }}
      />
    </main>
  );
}
```

```ts
// frontend/pages/art/@author/@artId/+data.ts
import type { Article } from '../../../../src/types';

export type Data = { article: Article | null; notFound: boolean };

export default async function data(
  // Vike передаёт URL-параметры как первый аргумент.
  { author, artId }: { author: string; artId: string },
): Promise<Data> {
  const res = await fetch(`http://127.0.0.1:8000/api/blog/articles/${artId}`);
  if (res.status === 404) return { article: null, notFound: true };
  if (!res.ok) throw new Error('Failed to load article');
  const { article } = await res.json();
  if (article.author !== author) {
    return { article: null, notFound: true };
  }
  return { article, notFound: false };
}
```

### 10.7. Гидрация на клиенте

```tsx
// frontend/entry-client.tsx (новый)
import { startClient } from 'vike/client';

startClient();
```

На сервере Vike сам вызывает ваш компонент с данными из `+data.ts`,
рендерит HTML, встраивает сериализованные данные в `<script>` для
hydration. На клиенте `entry-client.tsx` запускает hydration, и React
оживляет готовый HTML без `useEffect + fetch`.

### 10.8. Что меняется в FastAPI

Здесь — **почти ничего**. Vike-сервер в проде работает на Node (порт 3000),
но контракт `/api/blog/*` остаётся прежним. Появляется новая деплой-схема:

```
nginx (TLS, порт 443)
    │
    ├── /         → Node-express + Vike SSR (порт 3000)
    ├── /assets   → Node-express раздаёт dist/client/assets/
    ├── /api/blog → FastAPI (порт 8000)
    └── /static   → FastAPI (аватары)
```

SPA catch-all в `../fastapi-application/md_articles/frontend_routing.py` нужно **убрать** —
теперь `/{full_path:path}` обрабатывает Node-сервер, а не FastAPI. Если
оставить — Node-сервер будет получать 404 от FastAPI на свежий заход и
отдавать JSON вместо HTML.

`mount("/assets", StaticFiles(...))` в `frontend_routing.py` тоже убирается:
бандлы раздаёт Node-express из `frontend/dist/client/assets/` (Vike
складывает клиентскую сборку отдельно от серверной).

`mount("/static", ...)` остаётся — аватары по-прежнему отдаёт FastAPI
(или можно вынести в Node, но зачем).

### 10.9. Итог: что переделывается

| Слой | Было (CSR) | Стало (Vike SSR) | Трудоёмкость |
|---|---|---|---|
| `frontend/package.json` | только React-стек | + `vike`, `express` | 5 минут |
| `frontend/vite.config.ts` | `react()` | `react() + vike()` | 2 минуты |
| `frontend/server.ts` | — | новый файл, 25 строк | 30 минут |
| `frontend/src/pages/HomePage.tsx` | `useEffect + fetch` | перенос в `pages/index.tsx`, `useData` | 1 час |
| `frontend/src/pages/ArticlePage.tsx` | `useEffect + useParams` | перенос в `pages/art/@author/@artId/`, `useData` | 1 час |
| остальные `src/pages/*.tsx` | обычные | перенос в `pages/.../*.tsx` | по 30 минут |
| `pages/*/+data.ts` | — | новый файл на каждый роут (загрузка данных) | по 30 минут |
| `frontend/entry-client.tsx` | — | 3 строки | 5 минут |
| `../fastapi-application/md_articles/frontend_routing.py` | catch-all + `/assets` mount | удалить catch-all и `/assets` mount | 10 минут |
| `fastapi-application/main.py` | без изменений | без изменений | 0 |
| nginx-конфиг | проксирует всё в FastAPI | проксирует `/` и `/assets` в Node, `/api/*` в FastAPI | 1 час |

**Реальный объём работы:** 1–2 дня на миграцию среднего SPA, если есть
понимание React. Главная дельта — `useEffect + fetch → useData + +data.ts`,
остальное — механическое перемещение файлов и правка импортов.

### 10.10. Vike vs Next.js: когда что

| Критерий | Vike (Vite SSR) | Next.js (App Router) |
|---|---|---|
| Сборщик | Vite (тот же, что в dev) | собственный (webpack/turbopack) |
| Роутинг-конвенция | `pages/**` файлы, `@param` | `app/**` с `layout.tsx`, `[param]` |
| Загрузка данных | `+data.ts` рядом со страницей | `async` server-компонент |
| Конфиг | минимум, vite.config.ts | `next.config.js`, своя экосистема |
| React Server Components | нет (обычный SSR + hydration) | **да** (тоньше граница сервер/клиент) |
| Vendor lock-in | низкий (ваш код — обычный React) | средний (RSC, `use server`, `use client`) |
| Статическая генерация | `prerender: true` в `+config.ts` | `generateStaticParams` |
| Когда выбирать | хочется SSR, но не нравится Next.js | SEO-критичный проект, готовы к его соглашениям |

### 10.11. Что НЕ меняется ни в CSR, ни в SSR

- **FastAPI остаётся прежним.** Контракт `/api/blog/*` не меняется, потому
  что и Vike SSR, и Next.js, и CSR обращаются к нему через обычный
  `fetch`. Серверный код блога вообще не знает, кто к нему ходит —
  Node-сервер SSR или React в браузере.
- **`md_articles/api_blog.py`, `schema_art.py`, `models.py`** — без правок.
- **Pydantic-схемы** описывают JSON-контракт. Неважно, кто его читает —
  React в браузере или server-component в Node. В обоих случаях данные
  проходят одну и ту же валидацию.
- **`articles.yaml`**, `content_art/*.md`, БД — без правок.
- **CSRF, cookie-сессии** — продолжают работать. Vike SSR ходит к FastAPI
  с того же origin (через nginx-прокси), cookie-сессия едет с запросом
  так же, как раньше ходила из браузера.

Это и есть главный архитектурный плюс проектирования через API-контракт:
слой рендеринга — заменяемая деталь, доменная логика — нет.

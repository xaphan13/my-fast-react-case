# 09. SPA vs SSR: подробный разбор с кодом

> Цикл «FastAPI + React». Предыдущая: [08. Чеклист](08-checklist-new-project.md) · Следующая: [10. URL-flow](10-url-flow.md)

Краткое сравнение способов — в [07. Альтернативы](07-alternatives.md). Здесь —
развёрнутый разбор **двух конкретных способов** с примерами кода и
сетевыми диалогами: что делает Vite-SPA (этот проект) и что делал бы
Next.js-SSR, если бы мы его выбрали. Один и тот же сценарий — открытие
пользователем статьи — проигран дважды, чтобы разница была видна
наглядно.

## 1. Терминология

| Термин | Значение | Кто рендерит HTML |
|---|---|---|
| **SPA** (Single-Page Application) | Один `index.html`, контент подменяется JavaScript-ом | браузер (React в runtime) |
| **CSR** (Client-Side Rendering) | То же, что SPA — HTML рендерится в браузере | браузер |
| **SSR** (Server-Side Rendering) | HTML рендерится на сервере на каждый запрос | Node-сервер (Next.js, Remix) |
| **SSG** (Static Site Generation) | HTML собирается заранее при деплое | сборщик (Next.js `getStaticProps`) |
| **Hydration** | «Пробуждение» SSR-HTML: React подхватывает готовую разметку и добавляет интерактив | браузер после SSR-ответа |

**Vite** — это инструмент сборки и dev-сервер. Сам по себе он не «SPA» и
не «SSR»: Vite умеет собирать и то, и другое. В этом проекте Vite
настроен на **CSR (SPA)**: рендерит React в браузере. **Next.js** — это
фреймворк *поверх* React, который добавляет SSR/SSG из коробки; в нём
Vite не используется, вместо него свой сборщик на webpack/turbopack.

Правильно говорить: «Vite + React = CSR/SPA», «Next.js = SSR/SSG (и CSR
тоже, по выбору)». Не «Vite — это SPA», не «Next.js — это SSR».

## 2. Сценарий, который проигрываем

Пользователь вбивает в адресную строку браузера
`http://127.0.0.1:8000/art/Max/123` (или `http://localhost:3000/art/Max/123`
в Next.js-варианте) и видит статью. Смотрим, что происходит на каждом
этапе.

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
   │    md_articles/setup_frontend.py:49)    │
   │    → index.html                          │
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

**Слой 1: SPA catch-all** — `fastapi-application/md_articles/setup_frontend.py`:

```python
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


def mount_vite_react_assets(app: FastAPI) -> None:
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR, check_dir=False))
    # ВАЖНО: append, а не include_router — иначе catch-all попадёт
    # в начало router.routes и перехватит /api/blog/*.
    app.router.routes.append(
        Route("/{full_path:path}", spa_fallback, methods=["GET"])
    )
```

**Слой 2: JSON API блога** — `fastapi-application/md_articles/api_blog.py`:

```python
router_blog_api = APIRouter(prefix="/api/blog", tags=["blog api"])


@router_blog_api.get("/sections", name="blog_api.sections")
async def sections_list():
    """Список непустых разделов с количеством полных статей, по имени."""
    counts: dict[str, int] = {}
    for art in get_articles():
        if art.section and _is_complete(art):
            counts[art.section] = counts.get(art.section, 0) + 1
    sections = [
        SectionOut(name=n, label=n, count=c) for n, c in sorted(counts.items())
    ]
    return {"sections": jsonable_encoder(sections)}


@router_blog_api.get("/articles/{art_id}", name="blog_api.article_detail")
async def article_detail(art_id: int):
    """Полный контент одной статьи (Markdown → HTML)."""
    art = get_art(art_id)
    if art is None or not _is_complete(art):
        raise HTTPException(status_code=404, detail="Article not found")

    content_dir = get_path_dir()
    if not (content_dir / art.file_name).exists():
        raise HTTPException(status_code=404, detail="Article not found")

    content = render_article(art.file_name, content_dir)
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

export async function getJson<T = unknown>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: 'include' });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}
```

**Доменный клиент блога** — `frontend/src/api/blog.ts`:

```typescript
export function getArticles(section?: string): Promise<{ articles: Article[] }> {
  const query = section ? `?section=${encodeURIComponent(section)}` : '';
  return getJson<{ articles: Article[] }>(`/api/blog/articles${query}`);
}

export function getArticle(artId: number | string): Promise<{ article: Article }> {
  return getJson<{ article: Article }>(`/api/blog/articles/${artId}`);
}
```

**Страница статьи** — `frontend/src/pages/ArticlePage.tsx`:

```tsx
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
Пустой `<div id="root"></div>` — React ещё ничего не отрисовал. Контента
в HTML нет.

```http
GET /assets/index-AbCdEf12.js HTTP/1.1
HTTP/1.1 200 OK
Content-Type: application/javascript
Cache-Control: public, max-age=31536000, immutable
```
Сам бандл (~150–500 КБ в gzip). На F5 приходит из disk cache, поэтому в
DevTools → Network видно `(disk cache)` в колонке Size.

Дальше React в браузере делает запрос контента:

```http
GET /api/blog/articles/123 HTTP/1.1
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

### 3.5. Навигация внутри SPA (клик по ссылке)

Пользователь на главной кликнул на карточку статьи `Max/123`. В браузере
уже есть `index.html` (в памяти), есть бандл (в памяти). Происходит:

```js
// React Router внутри делает:
history.pushState({}, '', '/art/Max/123');
// Никакого HTTP-запроса.
```

Дальше `<ArticlePage>` монтируется, его `useEffect` шлёт **только**:

```http
GET /api/blog/articles/123 HTTP/1.1
```

Один запрос — и страница готова. Никакого `GET /art/Max/123`, никакого
бандла.

### 3.6. Что в DevTools → Network

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
  const res = await fetch('http://fastapi:8000/api/blog/articles', {
    next: { revalidate: 60 },        // ISR: перечитывать раз в 60 секунд
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
            <Link href={`/art/${a.author}/${a.art_id}`}>{a.title}</Link>
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
// Только на сервере Next.js (server components). На клиент не попадает.
const FASTAPI_URL = process.env.FASTAPI_INTERNAL_URL ?? 'http://fastapi:8000';

export async function getArticle(artId: number | string) {
  const res = await fetch(`${FASTAPI_URL}/api/blog/articles/${artId}`, {
    next: { revalidate: 60 },
  });
  if (res.status === 404) return { article: null };
  if (!res.ok) throw new Error('Failed');
  return res.json();
}
```

### 4.4. Сетевой диалог — холодный заход на `/art/Max/123`

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
      </div>
    </main>
    <script src="/_next/static/chunks/main-AbCd.js"></script>
    <script>self.__next_f.push([1, "..."])</script>
  </body>
</html>
```

**Контент статьи (`<h1>Про SPA и SSR</h1>`) уже в HTML.** Поисковый робот
Google увидит текст без исполнения JavaScript. Соцсети при парсинге URL
получат `<title>` и `<meta property="og:title">`.

Никакого запроса `GET /api/blog/articles/123` от браузера нет — данные
уже в HTML.

### 4.5. Что в DevTools → Network

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
| Контент статьи в HTML | нет (Google рендерит JS) | **да, моментально** |
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
  Telegram-бот, CLI — все ходят по тому же `/api/blog`, не завися от
  Next.js.

### Где SSR (Next.js) выигрывает

- **SEO из коробки.** Поисковики и соцсети видят готовый HTML. Для блога,
  медиа, маркетплейса это часто критично.
- **Быстрая первая отрисовка (FCP).** Контент появляется до загрузки
  гидрационного бандла. На медленном интернете разница заметна.
- **Core Web Vitals лучше.** LCP (Largest Contentful Paint) измеряется по
  времени появления основного контента — в SSR это время первого байта
  HTML, в CSR — время загрузки + парсинга JS + fetch + render.
- **OpenGraph / Twitter Cards.** `generateMetadata` отдаёт динамические
  `<meta>` для красивого превью в соцсетях. В CSR это требует отдельного
  рендера или внешнего сервиса (prerender.io и т.п.).
- **Меньше JavaScript на клиенте.** Гидрационный бандл меньше полного
  CSR-бандла (нет API-клиента, нет роутера для основного вывода).

### Где CSR проигрывает

- **SEO требует обходного пути.** Google индексирует CSR, но с задержкой;
  Яндекс и соцсети — нет. Для публичного контентного сайта это серьёзная
  потеря. Решения — `prerender.io`, статический пререндер, или гибрид
  (см. ниже).
- **Первый контент позже.** На медленной сети спиннер «Загрузка...» виден
  дольше.
- **Больше работы на клиенте.** CSR-бандл обычно больше гидрационного.

### Где SSR проигрывает

- **Два рантайма.** Node + Python. Два деплоя, два мониторинга, двойная
  квалификация команды.
- **Серверный рендер = нагрузка.** Каждый запрос — рендер React в Node.
  Для блога с 1000 RPS это серьёзная нагрузка. Решения — ISR
  (revalidate), Edge-рендеринг, статическая генерация для редко
  меняющихся страниц.
- **Сложнее дебажить.** SSR-bug может проявиться только на сервере
  (например, `window is not defined`), в CSR всё в браузере.
- **Vendor lock-in.** Next.js = React Server Components, специальные
  соглашения (`'use client'`), свой роутер. Миграция на другой
  SSR-фреймворк дороже, чем миграция между CSR-подходами.

---

## 7. Гибридные варианты

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
export default async function ArticlePage({ params }) { /* ... */ }
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
  <div set:html={article.content} />
  <Comments client:visible articleId={article.art_id} />
</article>
```

Статика для всего, JS только там, где реально нужен интерактив. Подробно
в [07. Альтернативы](07-alternatives.md), способ E.

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

## 10. SSR на Vite через Vike — короткая сводка

Если хочется остаться на Vite (не уходить на Next.js) и при этом получить
SSR — это возможно через фреймворк **Vike** (бывший `vite-plugin-ssr`,
переименован в 2024). Архитектура:

```
my-fast-react-case/
├── frontend/                  ← Vite + React, как сейчас
│   ├── pages/                 ← НОВОЕ: роуты Vike (pages/index.tsx, pages/art/...)
│   ├── src/components/        ← остаётся
│   ├── renderer/              ← НОВОЕ: _default.page.tsx + _default.page.server.tsx
│   ├── entry-client.tsx       ← НОВОЕ: 3 строки
│   └── server.ts              ← НОВОЕ: express + Vike SSR middleware
└── fastapi-application/       ← без изменений в API
```

**Что меняется в FastAPI:** `mount_vite_react_assets` (catch-all +
`/assets`) — **удаляется**. Vike-сервер сам обрабатывает `/{full_path:path}`
и раздаёт `dist/client/assets/`. `/api/blog/*` остаётся на FastAPI, nginx
проксирует `/api/*` в FastAPI, остальное — в Node.

**Трудоёмкость миграции:** 1–2 дня на средний SPA. Главная дельта —
`useEffect + fetch → useData + +data.ts`. Файлы страниц переезжают из
`src/pages/` в корень `pages/`.

> **Важно:** Vike — это **SSR-фреймворк поверх Vite**, и ему нужен
> **Node в рантайме** (express). Это двухрантаймная схема (Node + Python),
> тот же класс решений, что и Next.js. Если главная цель перехода — убрать
> Node, Vike не поможет. Для React-SSR без Node альтернатив в
> Python-экосистеме нет (см. [07. Альтернативы](07-alternatives.md),
> способ D — Jinja2 + htmx).
>
> В этом проекте CSR выбран именно ради одного Python-процесса.
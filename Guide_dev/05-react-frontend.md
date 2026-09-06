# 05. Скелет фронтенда: React + TypeScript + Vite

> Цикл «FastAPI + React». Предыдущая: [04. JSON API](04-json-api-contract.md) · Следующая: [06. Связка и деплой](06-integration-deploy.md)

## Стек и почему он

| Выбор | Почему |
|---|---|
| **Vite** | Мгновенный dev-сервер с HMR; сборка на esbuild/rollup — секунды вместо минут webpack'а. Стандарт де-факто для новых SPA |
| **TypeScript** | Типы контракта API на клиенте; половина багов «undefined в JSON» ловится на компиляции |
| **React 18** | Функциональные компоненты + хуки; экосистема и найм |
| **Tailwind CSS v4** | Стили рядом с разметкой, тёмные темы через CSS-переменные, нет каскадных конфликтов |
| **react-router-dom 6** | Клиентский роутинг без перезагрузок; `NavLink`, `useParams`, вложенные layout'ы |

Ничего из этого не нужно в рантайме сервера: после `npm run build` остаётся
статика. Node — инструмент сборки, не зависимость продукта. В этом проекте
SPA работает через один FastAPI-процесс — подробно в
[статье 06](06-integration-deploy.md).

## Структура каталога

```
frontend/
├── index.html              # точка входа; сюда Vite вкомпилирует бандлы
├── vite.config.ts          # dev-порт, прокси /api и /static → :8000
├── package.json
└── src/
    ├── api/                # СЛОЙ ДОСТУПА К API — весь fetch живёт только здесь
    │   ├── client.ts       # базовый клиент: credentials, CSRF, разбор ошибок
    │   ├── blog.ts         # статьи и разделы
    │   ├── auth.ts         # register / login / logout / current_user / account
    │   └── artManage.ts    # управление реестром (art_manage endpoints)
    ├── components/         # переиспользуемые UI-блоки (Header, ArticleCard, ...)
    ├── context/            # AuthContext — глобальное состояние пользователя
    ├── hooks/              # useTheme, useHljsTheme
    ├── pages/              # страницы-маршруты (HomePage, ArticlePage, ...)
    └── types.ts            # TS-зеркало pydantic-схем бэкенда
```

**Ключевое правило: компоненты не вызывают `fetch` напрямую.** Всё общение
с сервером — через слой `src/api/`. Это даёт одну точку для авторизации,
CSRF, обработки ошибок и подмены в тестах.

## Типы — зеркало контракта

`frontend/src/types.ts` держится синхронным с pydantic-схемами (см.
[статью 04](04-json-api-contract.md)):

```typescript
export interface User {
  id: number;
  username: string;
  email: string;
  image_file: string;       // голое имя файла, фронт сам склеивает URL
}

export interface Article {
  author: string;
  lang: string;
  art_id: number;
  title: string;
  file_name: string;
  section?: string;         // имя подпапки content_art/
  content?: string;         // готовый HTML — только в ответе /articles/{art_id}
  complete?: boolean;
  file_exists?: boolean;
}

export interface Section {
  name: string;
  label: string;
  count: number;
}
```

Компилятор не даст обратиться к `article.content` там, где вы запросили
только список (в списке поля `content` нет) — ровно та же дисциплина, что
`OrderResp` vs `OrderRespWithProducts` на бэкенде
([статья 04](04-json-api-contract.md)).

**Важное правило: бэкенд возвращает голое имя файла** (`image_file:
"abc.jpg"`), а фронт сам склеивает полный URL для `<img>`/`<a>`. Дублировать
склейку в двух местах — антипаттерн two-source-of-truth (см. гайд 10,
грабли).

## Базовый API-клиент

`frontend/src/api/client.ts` — реальный код проекта:

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

async function parseResponse(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try { return JSON.parse(text); } catch { return text; }
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  // credentials: 'include' — cookie-сессия ходит с каждым запросом
  const res = await fetch(path, { credentials: 'include', ...init });
  return res;
}

async function ensureOk(res: Response): Promise<unknown> {
  const data = await parseResponse(res);
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export async function getJson<T = unknown>(path: string): Promise<T> {
  const res = await request(path);
  return (await ensureOk(res)) as T;
}

// GET /api/blog/csrf — создаёт/возвращает csrf_token из сессии.
export async function getCsrfToken(): Promise<string> {
  const data = await getJson<{ csrf_token: string }>('/api/blog/csrf');
  return data.csrf_token;
}

// POST с JSON-телом; CSRF-токен кладём в заголовок X-CSRF-Token.
export async function postJson<T = unknown>(path: string, body: unknown): Promise<T> {
  const token = await getCsrfToken();
  const res = await request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
    body: JSON.stringify(body),
  });
  return (await ensureOk(res)) as T;
}

// POST с multipart-формой; CSRF-токен передаётся полем csrf_token.
export async function postMultipart<T = unknown>(path: string, formData: FormData): Promise<T> {
  if (!formData.has('csrf_token')) {
    formData.set('csrf_token', await getCsrfToken());
  }
  const res = await request(path, { method: 'POST', body: formData });
  return (await ensureOk(res)) as T;
}
```

Что здесь принципиально:

- **`credentials: 'include'`** — cookie-сессия ходит с каждым запросом; без
  этого авторизация «работает, но слетает».
- **Единый `ApiError`** со статусом и телом — компоненты решают, что
  показывать (401 → форма входа, 422 → ошибки полей, 500 → toast).
- **Дженерик `getJson<T>`** — тип ответа задаётся на месте вызова, а не
  `any`.
- **`postJson` / `postMultipart`** — единственные места, где
  автоматически подставляется CSRF-токен. Компоненты вызывают
  `postJson('/api/blog/login', body)` и не знают о CSRF вообще.

Сверху — доменные функции (`frontend/src/api/blog.ts`):

```typescript
export function getArticles(section?: string): Promise<{ articles: Article[] }> {
  const query = section ? `?section=${encodeURIComponent(section)}` : '';
  return getJson<{ articles: Article[] }>(`/api/blog/articles${query}`);
}

export function getArticle(artId: number | string): Promise<{ article: Article }> {
  return getJson<{ article: Article }>(`/api/blog/articles/${artId}`);
}
```

`encodeURIComponent` обязателен для query-параметров — кириллица или
`+` в имени раздела сломают URL.

## Глобальное состояние: контекст авторизации

Для большинства SPA **не нужен** Redux/Zustand/MobX: достаточно одного
контекста для «кто я» и локального состояния страниц. Реальный код
`frontend/src/context/AuthContext.tsx`:

```tsx
interface AuthContextValue {
  user: User | null;
  loading: boolean;
  setUser: (user: User | null) => void;
  refresh: () => Promise<void>;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await getCurrentUser();
      setUser(data.user);
    } catch {
      setUser(null);          // неавторизован или сеть недоступна
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  return (
    <AuthContext.Provider value={{ user, loading, setUser, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
```

**Паттерн: `loading` обязателен.** Пока `GET /current_user` не ответил, UI
не должен решать «показать форму входа или контент» — иначе при каждом F5
мигает редирект на логин. Защита страниц — компонент-обёртка `RequireAuth`
поверх маршрута, а 403 от API — страховка (никогда не доверяйте только UI).

## Страницы и роутинг

`frontend/src/App.tsx` — реальный код:

```tsx
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './context/AuthContext';

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="page-stub text-muted">Проверка доступа...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/section/:name" element={<HomePage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/art/:author/:artId" element={<ArticlePage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/account" element={<RequireAuth><AccountPage /></RequireAuth>} />
        <Route path="/art_manage" element={<RequireAuth><ArtManagePage /></RequireAuth>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
```

`<Route element={<Layout />}>` — внешний маршрут без `path`. Это
**layout-route**: всё, что внутри, рендерится в `<Outlet />` компонента
`Layout`. Поэтому на каждой странице виден `Header`, `SectionMenu` и
footer, а меняется только центральная часть.

**Динамические параметры `:name`, `:author`, `:artId`** — это плейсхолдеры,
которые `useParams()` потом прочитает как `params.name` / `params.author`
/ `params.artId`. Например, для `/art/Max/123`:
`ArticlePage` получит `useParams().author === "Max"`,
`useParams().artId === "123"`.

`<Route path="*" element={<Navigate to="/" replace />} />` — это **catch-all
на клиенте**: любой URL, не совпавший ни с одним маршрутом, редиректит на
`/`. Это **не** серверный catch-all (тот в `setup_frontend.py`), а
клиентский. Они делают разное:
- серверный отдаёт `index.html` для не-`/api` путей, чтобы React мог
  запуститься;
- клиентский — решает, что показывать, если React уже работает, но URL
  неизвестен.

Подробно про два catch-all — [статья 10](10-url-flow.md).

## Страница статьи — пример слоя UI поверх API

`frontend/src/pages/ArticlePage.tsx`:

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
          setNotFound(true);  // URL не совпал с реальным автором
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

**`author` в URL — клиентская деталь.** Бэкенд про него не знает:
`/api/blog/articles/{art_id}` принимает только `art_id`, без `author`. На
клиенте мы проверяем совпадение, чтобы `/art/Vasya/123` не показал статью
автора Max.

`MarkdownContent` вставляет готовый HTML через `dangerouslySetInnerHTML` —
бэкенд уже отрендерил Markdown в HTML
(`md_articles/schema_art.py:render_article`).

## Чекпоинт самопроверки

- [ ] Весь `fetch` — в `src/api/`, компоненты вызывают доменные функции.
- [ ] `credentials: 'include'` в базовом клиенте.
- [ ] `types.ts` синхронен с pydantic-схемами; никаких `any` в слое API.
- [ ] `AuthContext` с фазой `loading`; защита маршрутов через `RequireAuth`.
- [ ] Ошибки API обрабатываются по статусу (401/403/422/500), а не молча.
- [ ] После правок фронтенда — контрольный `npm run build` (грабля №1 из
      [статьи 01](01-architecture-overview.md)).
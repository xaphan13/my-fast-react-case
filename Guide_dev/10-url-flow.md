# 10. URL от пользователя до бэкенда: где какой URL появляется

> Цикл «FastAPI + React». Предыдущая: [09. SPA vs SSR](09-spa-vs-ssr.md)

В этом проекте у каждой «страницы» в браузере есть **несколько разных URL**,
и каждый из них появляется в своём месте. Эти URL — не одно и то же: они
обслуживаются разными слоями (React Router, fetch-обёртка, FastAPI-роутер)
и предназначены для разных потребителей. Путаница между ними — главный
источник непонимания SPA-архитектуры, поэтому разберём по шагам.

## 0. Карта URL-ов в проекте

| Слой | URL | Кто использует | Файл |
|---|---|---|---|
| 1. Человеческий (адресная строка) | `/`, `/art/Max/123`, `/section/Rust`, `/login`, `/account`, `/art_manage` | пользователь в браузере, шаринг, F5 | — |
| 2. Клиентский (react-router) | то же, что (1) | React Router (history-mode) | `frontend/src/App.tsx` |
| 3. Машинный (API) | `/api/blog/articles`, `/api/blog/articles/123`, `/api/blog/sections`, `/api/blog/login`, `/api/blog/account`, `/api/blog/csrf`, `/api/blog/current_user` | JavaScript-код (fetch) | `frontend/src/api/*.ts` |
| 4. Серверный (FastAPI-роутер) | то же, что (3) | FastAPI-роутер | `fastapi-application/md_articles/api_blog.py`, `api_auth.py` |
| 5. Серверный (catch-all) | `/{full_path:path}` | любой GET, не начинающийся с `/api` | `fastapi-application/md_articles/setup_frontend.py:79` |

**Связь между слоями:**

- Слой 1 = слой 2 (тот же URL, что в адресной строке, обслуживает React Router).
- Слой 2 читает параметры из URL слоя 1, делает fetch на слой 3.
- Слой 3 — обёртка вокруг слоя 4 (тот же путь, добавляется `credentials: 'include'`).
- Слой 4 обрабатывает запрос, читает БД/диск, отдаёт JSON.
- Слой 5 — обслуживает слой 1 для случаев, когда React в браузере ещё не запустился (F5, прямой заход).

Дальше разберём каждый слой подробно — с кодом и file:line из актуального
проекта.

---

## 1. Слой 1. Где появляется человеческий URL

Человеческий URL — это то, что пользователь видит в адресной строке и с
чем взаимодействует: копирует, шарит, обновляет F5. Внутри React он
собирается только через компоненты `react-router-dom`: `Link` и `NavLink`.

### 1.1. Адресная строка

Самый очевидный источник — пользователь вбивает
`http://127.0.0.1:8000/art/Max/123` или переходит по внешней ссылке. URL
едет в HTTP-запросе:

```http
GET /art/Max/123 HTTP/1.1
Host: 127.0.0.1:8000
Cookie: session=...
```

На сервере этот запрос ловит **слой 5** (catch-all) — потому что в FastAPI
нет роута для `/art/...`. Об этом в разделе 5.

### 1.2. Навигация в `Header.tsx`

`frontend/src/components/Header.tsx` — навигация в шапке, на каждой странице:

```tsx
import { NavLink, Link } from 'react-router-dom';

const navClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? 'nav-link active' : 'nav-link';

return (
  <header className="site-header">
    <Link to="/" className="brand">Сайт о программировании</Link>
    <nav className="nav-links">
      <NavLink to="/" end className={navClass}>Статьи</NavLink>
      <NavLink to="/art_manage" className={navClass}>Управление</NavLink>
      {user ? (
        <>
          <NavLink to="/account" className={navClass}>Аккаунт</NavLink>
          <button onClick={onLogout}>Выход</button>
        </>
      ) : (
        <>
          <NavLink to="/login" className={navClass}>Вход</NavLink>
          <NavLink to="/register" className={navClass}>Регистрация</NavLink>
        </>
      )}
      <NavLink to="/about" className={navClass}>О сайте</NavLink>
    </nav>
  </header>
);
```

URL-ы здесь — **статические строки**. Они не зависят от данных, не
собираются шаблоном. Это только навигация, всегда один и тот же набор
путей. `/art/Max/123` тут не появится — для этого есть отдельный компонент
`ArticleCard`.

### 1.3. Ссылка на статью в `ArticleCard.tsx`

**`frontend/src/components/ArticleCard.tsx`** — это **единственное место в
проекте**, где `/art/{author}/{art_id}` собирается из данных:

```tsx
import { Link } from 'react-router-dom';
import type { Article } from '../types';

export default function ArticleCard({ article }: ArticleCardProps) {
  return (
    <Link
      to={`/art/${article.author}/${article.art_id}`}
      className="card card-hover card-row"
      style={{ textDecoration: 'none', color: 'inherit' }}
    >
      <h3 className="card-title-grad">{article.title}</h3>
      <p className="text-muted card-author">{article.author}</p>
      <span className="badge card-lang">{article.lang}</span>
    </Link>
  );
}
```

**Ключевая строка:** `` `/art/${article.author}/${article.art_id}` `` — здесь
`article.author` и `article.art_id` (поля из JSON-ответа
`/api/blog/articles`) склеиваются в URL. Если в реестре статья автора
«Max» с `art_id=123`, ссылка будет `/art/Max/123`.

Если в проекте когда-нибудь захочется убрать `author` из URL, правка будет
здесь + в `App.tsx` (раздел 2) + в `ArticlePage.tsx` (раздел 3). Бэкенд
не трогается — он никогда не знал про `author` в URL.

### 1.4. Ссылки на разделы в `SectionMenu.tsx`

`frontend/src/components/SectionMenu.tsx` — левое меню со списком разделов.
Разделы подгружаются через API (слой 3), и для каждого собирается
`/section/<name>`:

```tsx
import { NavLink } from 'react-router-dom';
import { getSections } from '../api/blog';

export default function SectionMenu() {
  const [sections, setSections] = useState<Section[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSections()
      .then((data) => { if (!cancelled) setSections(data.sections); })
      .catch(() => { if (!cancelled) setSections([]); });
    return () => { cancelled = true; };
  }, []);

  return (
    <>
      <NavLink to="/" end className={sectionClass}>Все статьи</NavLink>
      {sections?.map((s) => (
        <NavLink key={s.name} to={`/section/${s.name}`} className={sectionClass}>
          {s.label}
        </NavLink>
      ))}
    </>
  );
}
```

Здесь URL `/section/${s.name}` собирается из данных API, **только** если
разделы загрузились. До загрузки меню состоит из одной строки «Все
статьи».

### 1.5. Редиректы в коде

Иногда URL меняется не по клику, а программно — через хук `useNavigate`
или компонент `<Navigate>`. Примеры:

**`frontend/src/App.tsx`** — `<RequireAuth>` для защищённых страниц:

```tsx
function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="page-stub text-muted">Проверка доступа...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
```

`Navigate` — это компонент-редирект. Он эквивалентен `useNavigate()` в
useEffect, но удобнее для условного рендера.

**`frontend/src/pages/LoginPage.tsx`** — после успешного входа:

```tsx
const navigate = useNavigate();
const resp = await login({ email, password });
setUser(resp.user);
navigate('/');  // программный переход на главную
```

`navigate('/')` вызывает `history.pushState({}, '', '/')` — URL меняется,
**GET на сервер не идёт**, React Router рендерит `<HomePage>`.

---

## 2. Слой 2. React Router — кто превращает URL в React-компонент

**`frontend/src/App.tsx`** — единственное место, где все URL-ы проекта
регистрируются как маршруты:

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
        <Route
          path="/account"
          element={<RequireAuth><AccountPage /></RequireAuth>}
        />
        <Route
          path="/art_manage"
          element={<RequireAuth><ArtManagePage /></RequireAuth>}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
```

**`<Route element={<Layout />}>`** — внешний маршрут без `path`. Это
**layout-route**: всё, что внутри, рендерится в `<Outlet />` компонента
`Layout`. Поэтому на каждой странице виден `Header`, `SectionMenu` и
footer, а меняется только центральная часть (`<Outlet />`).

**Динамические параметры `:name`, `:author`, `:artId`** — это плейсхолдеры,
которые `useParams()` потом прочитает. Например, для `/art/Max/123`:
`ArticlePage` получит `useParams().author === "Max"`,
`useParams().artId === "123"`.

`<Route path="*" element={<Navigate to="/" replace />} />` — это **catch-all
на клиенте**: любой URL, не совпавший ни с одним маршрутом, редиректит на
`/`. Это **не** серверный catch-all (тот в `setup_frontend.py`), а
клиентский. Они делают разное:
- серверный (слой 5) отдаёт `index.html` для не-`/api` путей, чтобы React
  мог запуститься;
- клиентский (здесь) — решает, что показывать, если React уже работает,
  но URL неизвестен.

**`frontend/src/main.tsx`** — обёртка над `<App />`:

```tsx
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { AuthProvider } from './context/AuthContext';
import { ToastProvider } from './components/Toast';

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
```

`<BrowserRouter>` — это контекст, в котором работают `useNavigate`,
`useParams`, `<Link>`, `<Routes>`. `BrowserRouter` использует
`history.pushState` для смены URL без перезагрузки.

---

## 3. Слой 3. Как человеческий URL превращается в машинный (API)

Это центральный переход: страница в браузере (слой 1) делает fetch на API
(слой 3) на основе параметров из URL (слой 2). Разберём на примере
`ArticlePage`.

### 3.1. `useParams` читает URL

**`frontend/src/pages/ArticlePage.tsx`**:

```tsx
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getArticle } from '../api/blog';
import type { Article } from '../types';
import MarkdownContent from '../components/MarkdownContent';

export default function ArticlePage() {
  // useParams() читает :author и :artId из URL /art/:author/:artId.
  const { author, artId } = useParams<{ author: string; artId: string }>();
  const [article, setArticle] = useState<Article | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setArticle(null);
    setNotFound(false);

    // Превращение URL-параметра в машинный API-вызов — ниже.
    getArticle(artId ?? '')
      .then((data) => {
        if (cancelled) return;
        // Сверяем автора из URL с автором из API.
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
  // ...
}
```

**Важная деталь:** `useParams()` возвращает **только строки** (даже если в
URL `/art/123` — `artId` будет `"123"`, не `123`). Бэкенд
(`/api/blog/articles/{art_id}`) принимает `int`, FastAPI сам сконвертирует.
Сигнатура `getArticle(artId: number | string)` в `api/blog.ts` это явно
учитывает.

**`author`** здесь используется **только для валидации**: если кто-то
подставил в URL `/art/Vasya/123`, а статья 123 принадлежит Max, покажем
«не найдено». В машинный URL `author` **не передаётся**.

### 3.2. `getArticle` собирает машинный URL

**`frontend/src/api/blog.ts`** — слой API-клиента. Здесь шаблон
`` `/api/blog/articles/${artId}` `` собирает машинный URL:

```typescript
import { getJson } from './client';
import type { Article, Section } from '../types';

// GET /api/blog/articles — список записей реестра. section фильтрует по разделу.
export function getArticles(section?: string): Promise<{ articles: Article[] }> {
  const query = section ? `?section=${encodeURIComponent(section)}` : '';
  return getJson<{ articles: Article[] }>(`/api/blog/articles${query}`);
}

// GET /api/blog/sections — список непустых разделов с количеством полных статей.
export function getSections(): Promise<{ sections: Section[] }> {
  return getJson<{ sections: Section[] }>('/api/blog/sections');
}

// GET /api/blog/articles/{art_id} — одна статья с готовым HTML-контентом.
export function getArticle(artId: number | string): Promise<{ article: Article }> {
  return getJson<{ article: Article }>(`/api/blog/articles/${artId}`);
}
```

**`encodeURIComponent`** — обязателен для query-параметров, иначе раздел
с пробелом или кириллицей сломает URL. `?section=Rust` отдаётся как есть,
`?section=Машинное обучение` — закодируется в
`%D0%9C%D0%B0%D1%88%D0%B8%D0%BD…`.

**`/api/blog/articles/${artId}`** — здесь `artId` подставляется прямо.
`encodeURIComponent` для path-параметра не нужен, потому что `artId` — это
число (всегда), а числа ASCII-safe.

### 3.3. Auth-API: `getCurrentUser`, `login`, `register`, `account`

**`frontend/src/api/auth.ts`** — параллельный модуль для авторизации.
Здесь машинные URL-ы собираются аналогично:

```typescript
import { getJson, postJson, postMultipart, ApiError } from './client';
import type { User } from '../types';

export function getCurrentUser(): Promise<{ user: User | null }> {
  return getJson<{ user: User | null }>('/api/blog/current_user');
}

export function login(body: {
  email: string;
  password: string;
  remember?: boolean;
}): Promise<MessageResp & { user: User }> {
  return postJson<MessageResp & { user: User }>('/api/blog/login', body);
}

export function logout(): Promise<MessageResp> {
  return postJson<MessageResp>('/api/blog/logout', {});
}

export function getAccount(): Promise<{ user: User }> {
  return getJson<{ user: User }>('/api/blog/account');
}

export function updateAccount(body: {
  username: string;
  email: string;
  picture?: File | null;
}): Promise<MessageResp & { user: User }> {
  const formData = new FormData();
  formData.set('username', body.username);
  formData.set('email', body.email);
  if (body.picture) formData.set('picture', body.picture);
  return postMultipart<MessageResp & { user: User }>('/api/blog/account', formData);
}
```

URL-ы здесь — константные строки + `/api/blog/...`. Параметры передаются
в **теле** запроса (для POST) или в path (для GET с ID), но никогда — в
URL-параметре слоя 1.

### 3.4. Обёртка `getJson` — общая для всех API-вызовов

**`frontend/src/api/client.ts`** — здесь машинный URL превращается в
HTTP-запрос:

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
  // credentials: 'include' — обязательно для cookie-сессии.
  const res = await fetch(path, { credentials: 'include', ...init });
  return res;
}

async function parseResponse(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try { return JSON.parse(text); } catch { return text; }
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

// POST с JSON-телом; CSRF-токен кладём в заголовок X-CSRF-Token.
export async function postJson<T = unknown>(path: string, body: unknown): Promise<T> {
  const token = await getCsrfToken();
  const res = await request(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': token,
    },
    body: JSON.stringify(body),
  });
  return (await ensureOk(res)) as T;
}

// POST с multipart-формой; CSRF-токен передаётся полем csrf_token.
export async function postMultipart<T = unknown>(
  path: string,
  formData: FormData,
): Promise<T> {
  if (!formData.has('csrf_token')) {
    formData.set('csrf_token', await getCsrfToken());
  }
  const res = await request(path, { method: 'POST', body: formData });
  return (await ensureOk(res)) as T;
}

// GET /api/blog/csrf — создаёт/возвращает csrf_token из сессии.
export async function getCsrfToken(): Promise<string> {
  const data = await getJson<{ csrf_token: string }>('/api/blog/csrf');
  return data.csrf_token;
}
```

**`credentials: 'include'`** — критично. Без него cookie-сессия не едет
в запросе, и `inject_current_user_middleware` всегда видит анонима. Это
**единственное место** в проекте, где это прописано — все доменные функции
(`getArticles`, `getCurrentUser`, ...) идут через `request()`.

**CSRF-токен** — POST-запросы требуют `X-CSRF-Token` (для JSON) или
`csrf_token` поле формы (для multipart). Токен живёт в сессии
(`request.session['csrf_token']`), фронт его получает через
`GET /api/blog/csrf` (один раз, потом использует повторно).

### 3.5. Куда дальше: ответ API → React state

После `getArticle(artId)` `ArticlePage` получает
`{ article: { title, content, ... } }` и кладёт в `useState`. Дальше
`<MarkdownContent html={article.content} />` вставляет готовый HTML в
каркас. Контент приходит **уже как HTML** (бэкенд через `render_article`
в `md_articles/schema_art.py` рендерит `.md` → HTML на сервере).

---

## 4. Слой 4. FastAPI-роутер — кто отвечает на машинный URL

В этом проекте **два роутера** под одним префиксом `/api/blog`:
- `router_auth_api` (`api_auth.py:27`) — 7 эндпоинтов авторизации.
- `router_blog_api` (`api_blog.py:28`) — 7 эндпоинтов блога.

Оба подключаются через `include_router_api_frontend` в
`md_articles/setup_frontend.py:16`.

### 4.1. Auth-роутер — `api_auth.py`

```python
router_auth_api = APIRouter(
    prefix="/api/blog",
    tags=["auth"],
)

@router_auth_api.get("/csrf", name="auth.csrf")                      # :47
@router_auth_api.get("/current_user", name="auth.current_user")      # :56
@router_auth_api.post("/register", name="auth.register")            # :67
@router_auth_api.post("/login", name="auth.login")                  # :124
@router_auth_api.post("/logout", name="auth.logout")                # :167
@router_auth_api.get("/account", name="auth.account_get")           # :177
@router_auth_api.post("/account", name="auth.account_post")         # :182
```

**Подключение:** `setup_frontend.py:37` — `app.include_router(router_auth_api)`.

### 4.2. Blog-роутер — `api_blog.py`

```python
router_blog_api = APIRouter(
    prefix="/api/blog",
    tags=["blog api"],
)

@router_blog_api.get("/sections", name="blog_api.sections")                # :64
@router_blog_api.get("/articles", name="blog_api.articles")                # :81
@router_blog_api.get("/articles/{art_id}", name="blog_api.article_detail") # :93
@router_blog_api.get("/art_manage", name="blog_api.art_manage")            # :117
@router_blog_api.post("/art_manage/add_all", name="blog_api.art_manage_add_all")  # :139
@router_blog_api.post("/art_manage/meta", name="blog_api.art_manage_meta")  # :172
@router_blog_api.post("/art_manage/sync", name="blog_api.art_manage_sync")  # :228
```

**Подключение:** `setup_frontend.py:38` — `app.include_router(router_blog_api)`.

**`prefix="/api/blog"`** на обоих роутерах — все эндпоинты автоматически
получают префикс. `@router_auth_api.get("/csrf")` → `GET /api/blog/csrf`.

**`{art_id}: int`** — FastAPI сам парсит строку из URL в `int`. Если в
URL `/api/blog/articles/abc` — придёт 422 (Pydantic-ошибка валидации
типа), не 500. Этот механизм — часть FastAPI, не наша логика.

### 4.3. middleware-стек: что происходит ДО роута

**`fastapi-application/md_articles/middleware_auth.py`** —
`inject_current_user_middleware` запускается на каждый запрос:

```python
async def inject_current_user_middleware(request: Request, call_next):
    """HTTP-middleware: подгружает current_user для каждого запроса."""
    async with db_manager.session_factory() as session:
        await get_current_user(request, session)
        response = await call_next(request)
    return response


async def get_current_user(request: Request, session: CurrentSession) -> BlogUser | None:
    """Получить пользователя из сессии и положить в request.state."""
    user_id = request.session.get("user_id")
    if user_id is None:
        request.state.current_user = None
        return None
    result = await session.execute(select(BlogUser).where(BlogUser.id == user_id))
    user = result.scalar_one_or_none()
    request.state.current_user = user
    return user
```

К моменту, когда `article_detail` начинает работать, в
`request.state.current_user` лежит либо `BlogUser`, либо `None`. Роут
может проверить:

```python
from md_articles.helpers_auth import get_request_user, require_login_api

@router_blog_api.get("/art_manage", name="blog_api.art_manage")
async def art_manage_api(request: Request, _user=Depends(require_login_api)):
    ...
```

**`SessionMiddleware`** добавляется в `add_middleware_auth`
(`middleware_auth.py:79`):

```python
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.web.secret_key,
    max_age=14 * 24 * 3600,  # 14 дней
)
```

`SessionMiddleware` подписывает cookie-сессию. Без него `request.session`
не работает, и `current_user` всегда будет `None`.

### 4.4. Pydantic-схемы: контракт запроса/ответа

**`fastapi-application/md_articles/schema_blog.py`** — схемы auth:

```python
class UserOut(BaseModel):
    id: int
    username: str
    email: str
    image_file: str              # голое имя файла — фронт склеивает URL сам

class RegisterIn(BaseModel):
    username: str = ""
    email: str = ""
    password: str = ""
    confirm_password: str = ""

class LoginIn(BaseModel):
    email: str = ""
    password: str = ""
    remember: bool = False

class MetaIn(BaseModel):
    file_name: str = ""
    author: str = ""
    lang: str = ""
    title: str = ""

class SectionOut(BaseModel):
    name: str
    label: str
    count: int
```

Для **GET**-эндпоинтов схемы ответа часто неявные (`return {"articles": [...]}`),
но для **POST** — типизированный вход через `payload: LoginIn` и т.д.
FastAPI парсит JSON-тело в Pydantic-модель, валидирует, и если что-то
не так — отдаёт 422.

Кастомный handler `custom_request_validation_exception_handler`
(`middleware_auth.py:99`) переписывает 422 в формат
`{"errors": {"field": ["msg"]}}` для путей `/api/blog/*` — это удобнее
для фронта (`extractErrors(err)` в `api/auth.ts`).

### 4.5. CORS: почему его нет

API и фронтенд живут на одном origin (`127.0.0.1:8000`). Браузер считает
запросы same-origin и не применяет CORS-проверку. Если бы `/api/blog`
был на `api.example.com`, а фронт — на `app.example.com` — понадобился бы
`CORSMiddleware` (см. [07. Альтернативы](07-alternatives.md), способ B).

---

## 5. Слой 5. Серверный catch-all — кто отдаёт index.html

**`fastapi-application/md_articles/setup_frontend.py`** — модуль, который
подключает собранный фронт:

```python
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
ASSETS_DIR = FRONTEND_DIST / "assets"
INDEX_HTML = FRONTEND_DIST / "index.html"


async def spa_fallback(request: Request) -> FileResponse | JSONResponse:
    """
    Catch-all обработчик для client-side роутинга React Router.

    GET /art/Max/123:
      1. Path не начинается с /api → FileResponse(INDEX_HTML).
      2. Браузер получает пустой index.html.
      3. Браузер качает /assets/index-xxx.js, запускает React.
      4. React Router парсит /art/Max/123, рендерит <ArticlePage>.
      5. <ArticlePage> делает fetch /api/blog/articles/123.

    GET /api/blog/несуществующий:
      1. Path начинается с /api → JSONResponse(404).
      2. Браузер получает {"detail": "Not Found"}.
      3. fetch пробрасывает ApiError со status=404 в catch.
    """
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
    """
    Подключает раздачу собранного React-приложения к FastAPI.
    Вызывается из main.py СТРОГО после всех include_router.
    """
    app.mount(
        "/assets",
        StaticFiles(directory=ASSETS_DIR, check_dir=False),
        name="spa_assets",
    )
    # ВАЖНО: append, а не include_router — иначе catch-all попадёт
    # в начало router.routes и перехватит /api/blog/*.
    app.router.routes.append(
        Route("/{full_path:path}", spa_fallback, methods=["GET"])
    )
```

**`/{full_path:path}`** — Starlette-синтаксис для path-параметра,
захватывающего весь остаток пути. `full_path` будет равен `art/Max/123`
для URL `/art/Max/123` (без ведущего слэша).

**`methods=["GET"]`** — POST, PUT, DELETE в catch-all не попадают. Это
важно, потому что без `methods` catch-all перехватил бы все методы и
сломал `/api/blog/login`.

**`append` вместо `include_router`** — порядок маршрутов в Starlette
имеет значение. Если бы catch-all добавлялся через `include_router`,
он попал бы в начало списка (раньше `/api/blog/*`), и все API-запросы
получали бы `index.html`. Append в конец `router.routes` гарантирует,
что сначала проверяются все API-роуты, и только если ни один не
сработал — срабатывает catch-all.

**`check_dir=False`** в `StaticFiles` — приложение стартует даже без
`frontend/dist/`. Если фронт не собран, запросы к `/assets/*` вернут
обычный 404, а не упадут на импорте.

### 5.1. Подключение в main.py

**`fastapi-application/main.py`** — порядок подключения критичен:

```python
main_app = create_app(custom_docs_url=False)

# 1) Доменные роутеры (/api/v1, /users, /orders)
main_app.include_router(router_api)
main_app.include_router(r_users_sql)
main_app.include_router(r_order_one)

# 2) Блог: auth, /static, два JSON-роутера
include_router_api_frontend(main_app)

# 3) SPA: /assets + catch-all. СТРОГО последним.
mount_vite_react_assets(main_app)
```

Если переставить `mount_vite_react_assets` **до** блога — catch-all
добавится раньше `router_auth_api`/`router_blog_api` и `/api/blog/*`
сломается.

---

## 6. Сценарий: открытие `/art/Max/123` шаг за шагом

Проследим один сценарий через все 5 слоёв, с указанием файлов и строк.

**Сценарий:** пользователь вбил в адресную строку
`http://127.0.0.1:8000/art/Max/123` (холодный заход, React ещё не
запущен).

### Шаг 1. Браузер → FastAPI (слой 1 → слой 5)

```http
GET /art/Max/123 HTTP/1.1
Host: 127.0.0.1:8000
```

**Файл:** `fastapi-application/md_articles/setup_frontend.py:49`
(`spa_fallback`).

- Path не начинается с `/api` → идём к `FileResponse(INDEX_HTML)`.
- Возвращается `frontend/dist/index.html` (~1 КБ).

### Шаг 2. Браузер качает бандл

```http
GET /assets/index-AbCdEf12.js HTTP/1.1
```

**Файл:** `fastapi-application/md_articles/setup_frontend.py:104`
(`StaticFiles` mount).

- Vite-хэшированный бандл, ~200 КБ.
- `Cache-Control: public, max-age=31536000, immutable` — браузер не
  переспрашивает до пересборки.

### Шаг 3. React в браузере запускается

**Файл:** `frontend/src/main.tsx`.

`createRoot(...).render(<BrowserRouter>...)` стартует React. `BrowserRouter`
читает `window.location.pathname` (это `/art/Max/123`) и подсовывает его
в `Routes`.

### Шаг 4. Routes матчит URL → ArticlePage (слой 2)

**Файл:** `frontend/src/App.tsx`.

```tsx
<Route path="/art/:author/:artId" element={<ArticlePage />} />
```

`:author` = `"Max"`, `:artId` = `"123"`. React рендерит `<ArticlePage>`
внутри `<Outlet />` компонента `Layout` (шапка, левое меню, футер).

### Шаг 5. ArticlePage читает useParams и фетчит (слой 2 → слой 3)

**Файл:** `frontend/src/pages/ArticlePage.tsx`.

```tsx
const { author, artId } = useParams();   // {author: "Max", artId: "123"}
useEffect(() => { getArticle(artId) ... }, [author, artId]);
```

### Шаг 6. getArticle собирает машинный URL (слой 3)

**Файл:** `frontend/src/api/blog.ts`.

```typescript
return getJson(`/api/blog/articles/${artId}`);
//                                       ↑ "123"
```

### Шаг 7. getJson делает fetch (слой 3 → слой 4)

**Файл:** `frontend/src/api/client.ts:42-46`.

```typescript
const res = await fetch(`/api/blog/articles/123`, { credentials: 'include' });
```

Браузер отправляет:

```http
GET /api/blog/articles/123 HTTP/1.1
Host: 127.0.0.1:8000
Cookie: session=...
```

### Шаг 8. FastAPI обрабатывает (слой 4)

**Файл:** `fastapi-application/md_articles/api_blog.py:93`
(`article_detail`).

```python
@router_blog_api.get("/articles/{art_id}", name="blog_api.article_detail")
async def article_detail(art_id: int):
    art = get_art(art_id)
    if art is None or not _is_complete(art):
        raise HTTPException(status_code=404, detail="Article not found")
    content = render_article(art.file_name, get_path_dir())
    article = art.model_copy(update={"content": content})
    return {"article": jsonable_encoder(article.model_dump())}
```

- `art_id: int` — FastAPI парсит "123" → 123.
- `get_art(123)` ищет в `articles.yaml` через mtime-кэш.
- `render_article(...)` читает `.md` из `content_art/.../file.md`,
  прогоняет через `markdown(content, extensions=["fenced_code", "tables"])`.
- Возвращает JSON.

### Шаг 9. Ответ едет обратно

```http
HTTP/1.1 200 OK
Content-Type: application/json
Set-Cookie: session=...
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
    "content": "<h1>Про SPA и SSR</h1>\n<p>...</p>"
  }
}
```

### Шаг 10. ArticlePage валидирует и рендерит (слой 3 → слой 2)

**Файл:** `frontend/src/pages/ArticlePage.tsx`.

```tsx
if (!data.article || data.article.author !== author) {
  setNotFound(true);
} else {
  setArticle(data.article);
}
```

`article.author === "Max"` (из URL) — совпадает. `setArticle(...)`
обновляет state, React перерисовывает, `<MarkdownContent html={article.content} />`
вставляет HTML.

### Шаг 11. highlight.js подсвечивает код

**Файл:** `frontend/index.html` (вне React-дерева) — скрипт `highlight.js`
подключён в `<head>`, находит `<pre><code>` и применяет подсветку
синтаксиса. Клиентская подсветка, бэкенд её не делает.

### Итог

**11 файлов, 5 слоёв, один URL.** Через все пять проходит только
`/api/blog/...`; через 1, 2, 5 — `/art/Max/123`; через 3 — обе категории,
потому что это клиентская обёртка.

---

## 7. Сводная таблица: кто отвечает за каждый URL

| URL | HTTP-метод | Обработчик | Файл:строка | Что делает |
|---|---|---|---|---|
| `/` | GET | catch-all | `setup_frontend.py:49` | отдаёт `index.html` |
| `/art/Max/123` | GET | catch-all | `setup_frontend.py:49` | отдаёт `index.html` |
| `/section/Rust` | GET | catch-all | `setup_frontend.py:49` | отдаёт `index.html` |
| `/login` | GET | catch-all | `setup_frontend.py:49` | отдаёт `index.html` |
| `/account` | GET | catch-all | `setup_frontend.py:49` | отдаёт `index.html` |
| `/art_manage` | GET | catch-all | `setup_frontend.py:49` | отдаёт `index.html` |
| `/assets/*` | GET | StaticFiles | `setup_frontend.py:104` | отдаёт бандл |
| `/static/*` | GET | StaticFiles | `setup_frontend.py:31` | отдаёт аватар |
| `/api/blog/csrf` | GET | router_auth_api | `api_auth.py:47` | выдаёт CSRF-токен |
| `/api/blog/current_user` | GET | router_auth_api | `api_auth.py:56` | текущий user |
| `/api/blog/sections` | GET | router_blog_api | `api_blog.py:64` | список разделов |
| `/api/blog/articles` | GET | router_blog_api | `api_blog.py:81` | список статей |
| `/api/blog/articles/{art_id}` | GET | router_blog_api | `api_blog.py:93` | контент статьи |
| `/api/blog/art_manage` | GET | router_blog_api | `api_blog.py:117` | дашборд (login req) |
| `/api/blog/account` | GET | router_auth_api | `api_auth.py:177` | профиль (login req) |
| `/api/blog/register` | POST | router_auth_api | `api_auth.py:67` | регистрация |
| `/api/blog/login` | POST | router_auth_api | `api_auth.py:124` | вход |
| `/api/blog/logout` | POST | router_auth_api | `api_auth.py:167` | выход |
| `/api/blog/account` | POST | router_auth_api | `api_auth.py:182` | обновление профиля |
| `/api/blog/art_manage/add_all` | POST | router_blog_api | `api_blog.py:139` | добавить все .md |
| `/api/blog/art_manage/meta` | POST | router_blog_api | `api_blog.py:172` | обновить запись |
| `/api/blog/art_manage/sync` | POST | router_blog_api | `api_blog.py:228` | синхронизировать реестр |

**Главное правило:** все пути `/api/...` обслуживает только
`router_auth_api` + `router_blog_api`. Все остальные GET-пути — catch-all.
Никакой путь не обслуживается обоими.

---

## 8. Грабли — на что обращать внимание

### 8.1. Меняете URL — ищите все 4 места

Если вы хотите переименовать `/art_manage` в `/admin/articles`:

| Слой | Файл | Что менять |
|---|---|---|
| 1 (ссылки) | `Header.tsx` | `<NavLink to="/art_manage">` → `to="/admin/articles"` |
| 2 (роутер) | `App.tsx` | `<Route path="/art_manage">` → `path="/admin/articles"` |
| 3 (API) | `api/artManage.ts` | если API тоже переименовывается |
| 4 (бэкенд) | `api_blog.py:117,139,172,228` | `@router_blog_api.get/...prefix...` |

Пропустите шаг 4 — клик по «Управление» упадёт с 404 на API. Пропустите
шаг 2 — `Routes` не сматчит, клик отрендерит `<HomePage>` (catch-all
на клиенте: `<Navigate to="/" replace />`).

### 8.2. Не путайте user-URL с API-URL

`/login` и `/api/blog/login` — это **разные** URL с с **разной** семантикой:

- `/login` — страница с формой входа (HTML).
- `/api/blog/login` — POST-эндпоинт, в который форма шлёт JSON-тело.

Никогда не пишите `<form action="/api/blog/login">` — это сломает
`credentials: 'include'` (форма умеет слать cookie, но не CSRF-токен).
В React код для входа:

```tsx
// LoginPage.tsx
const resp = await login({ email, password });  // → POST /api/blog/login
```

`login` — это функция из `api/auth.ts`, которая через `postJson` делает
правильный fetch с CSRF.

### 8.3. `path: "*"` (App.tsx) vs `path: "{full_path:path}"` (setup_frontend.py)

Это **разные** catch-all:

- `App.tsx` `<Route path="*" element={<Navigate to="/" replace />} />` —
  клиентский: работает в браузере, перехватывает URL после того, как
  React уже запустился.
- `setup_frontend.py:110` `Route("/{full_path:path}", spa_fallback)` —
  серверный: работает в FastAPI, перехватывает URL до запуска React
  (F5, прямой заход).

Без серверного — F5 на `/art/Max/123` вернёт 404. Без клиентского —
после `pushState` на неизвестный URL рендер останется пустым.

### 8.4. `encodeURIComponent` обязателен

`getArticles(section)` строит:

```typescript
const query = section ? `?section=${encodeURIComponent(section)}` : '';
```

Без `encodeURIComponent` раздел `Машинное обучение` (кириллица) или
`C++` (знак `+`) сломает URL. Это видно в DevTools → Network: `section=`
станет `section=` (обрезано на спецсимволе), и фильтр не сработает.

### 8.5. `useParams()` возвращает строки

Даже если в URL `/art/123`, `useParams().artId` будет `"123"`, не `123`.
FastAPI сам сконвертирует в `int` (на бэкенде `art_id: int`), но если
вы используете `artId` в JS-вычислениях — оборачивайте в `Number()` или
`parseInt()`. В этом проекте `artId` идёт прямо в `getArticle(artId)`,
а бэкенд принимает и `int`, и `str` (см. сигнатуру
`getArticle(artId: number | string)` в `api/blog.ts`).

### 8.6. Склейка URL аватара — только во фронте

Бэкенд возвращает `image_file: "abc.jpg"` (голое имя файла). Полный URL
`/static/profile_pics/abc.jpg` склеивает **только фронт**. Бэкенд никогда
не строит `/static/...` в JSON-ответе — это антипаттерн two-source-of-truth
(БД хранит голое имя файла, а полный URL склеивает только фронт).

---

## 9. Если хотите убрать `author` из URL — что трогать

Конкретный пример: `author` в URL `/art/Max/123` избыточен, можно
оставить только `art_id`. Минимальные правки:

| Файл | Было | Стало |
|---|---|---|
| `App.tsx` | `path="/art/:author/:artId"` | `path="/art/:artId"` |
| `ArticleCard.tsx` | `` `/art/${article.author}/${article.art_id}` `` | `` `/art/${article.art_id}` `` |
| `ArticlePage.tsx` | `const { author, artId } = useParams<{...}>()` | `const { artId } = useParams<{artId: string}>()` |
| `ArticlePage.tsx` | `if (... data.article.author !== author) { setNotFound(true); }` | `if (!data.article) { setNotFound(true); }` |
| `ArticlePage.tsx` | `useEffect(..., [author, artId])` | `useEffect(..., [artId])` |

**`api/blog.ts`, `api/client.ts`, `api_auth.py`, `api_blog.py`** — **без
правок**. Они никогда не знали про `author` в URL: API-роут
`/api/blog/articles/{art_id}` принимает только `art_id`, без `author`.

После правки нужно:
1. `cd frontend && npm run build` — иначе в `dist/` старый бандл.
2. Перезапустить FastAPI (если меняли что-то на бэкенде; в данном случае нет).
3. Прогнать
   `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/art/123` —
   должно быть 200 (catch-all отдаёт `index.html`).

Старые ссылки `/art/Max/123` сломаются (404 от catch-all на клиенте,
редирект на `/`). Если есть внешние ссылки — добавить редирект в `App.tsx`
(временно, для совместимости):

```tsx
<Route path="/art/:author/:artId" element={<Navigate to={`/art/${artId}`} replace />} />
```

---

## 10. Чекпоинт самопроверки

- [ ] Можете назвать 5 слоёв URL-ов в этом проекте и для каждого — файл,
      где он появляется.
- [ ] Знаете, что `/art/Max/123` собирается **только** в `ArticleCard.tsx`
      (через шаблонную строку).
- [ ] Понимаете, что `author` в URL — клиентская деталь (`useParams`),
      бэкенд про него не знает.
- [ ] Можете объяснить, почему `encodeURIComponent` нужен для query, но
      не для path.
- [ ] Знаете, что `useParams()` возвращает **строки**, и FastAPI сам
      парсит в `int`.
- [ ] Понимаете разницу между серверным catch-all (`setup_frontend.py:110`)
      и клиентским (`App.tsx`).
- [ ] Можете проследить один сценарий (открытие статьи) от адресной
      строки до бэкенда и обратно.
- [ ] Знаете, что `path: "*"` (App.tsx) — это **клиентский** catch-all,
      не серверный.
- [ ] Умеете найти все 4 места, которые нужно менять при переименовании
      URL.
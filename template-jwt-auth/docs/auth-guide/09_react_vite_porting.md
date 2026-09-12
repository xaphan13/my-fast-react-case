# 09 — Перенос на React + Vite (SPA) при существующей самописной авторизации

Сценарий: backend — FastAPI (архитектура этого гайда), frontend — отдельный
проект на **React + Vite**, в котором уже есть **самописная авторизация**
(свой login-эндпоинт, свой токен, своё хранилище). Задача — перевести её на
стиль fastapi-users из этого проекта, не сломав работающий фронтенд.

> Примеры фронтенд-кода на этой странице — типовые паттерны; они написаны
> под React 18 + Vite 5 + axios и **не запускались** в этом репозитории
> (React-проекта здесь нет). Серверные фрагменты опираются на проверенные
> факты из [07](07_testing.md) и исходники fastapi-users 15.0.5.

---

## 1. Что меняется концептуально при переходе SSR → SPA

| Аспект | В этом проекте (SSR + HTMX) | В React + Vite (SPA) |
|---|---|---|
| Кто рендерит | Jinja2 на сервере | React в браузере |
| Ответы защищённых роутов | HTML (full page / partial) | JSON |
| Реакция на 401 | 302 / `HX-Redirect` на сервере | перехват на клиенте (interceptor) |
| HTML-страницы login/register | нужны (`app/api/auth.py`) | **не нужны** — фронт рисует свои формы |
| Роутер `get_register_router` | не подключён | **подключаем** — он JSON-native |
| Роутер `get_auth_router` | используется | используется, без изменений |
| 401-handler с редиректом | обязателен | **убираем** — фронт сам решает |
| `is_htmx`, Jinja2, шаблоны | ядро UX | не переносятся |

Ключевой вывод: из всего серверного набора для SPA нужны только
`config.py`, `database.py`, `models/user.py`, `schemas/user.py`,
`core/users.py` и **два встроенных роутера**. Всё, что проект добавлял для
браузера без JS-фреймворка (страницы, редиректы, partials), в React-мире
не нужно — фронтенд берёт эту роль на себя.

## 2. Транспорт: оставить cookie (рекомендуется) или уйти на Bearer

Самописная авторизация в SPA-проектах обычно хранит токен в `localStorage`
и шлёт его заголовком `Authorization: Bearer`. При переносе у вас развилка:

| Критерий | Cookie (как в этом проекте) | Bearer + localStorage |
|---|---|---|
| XSS-риски | токен недоступен JS (HttpOnly) | токен крадётся любым XSS |
| CSRF-риски | есть, но гасится `SameSite=lax` | нет |
| Работа из коробки | требует proxy/CORS-настройки | требует ручной отправки заголовка |
| Мобильные/сторонние клиенты | неудобно | удобно |
| Совместимость с `get_auth_router` | да, без изменений | да — подключается второй `AuthenticationBackend` с `BearerTransport` |

**Рекомендация: остаться на cookie.** Причины: меньше кода на клиенте
(браузер шлёт cookie сам), HttpOnly закрывает целый класс XSS-краж, а
`SameSite=lax` + JSON-API (не form-POST) делают CSRF-риск минимальным
(подробнее — §5). Bearer-бэкенд у fastapi-users всегда можно добавить позже
(`AuthenticationBackend` со списком бэкендов поддерживает несколько сразу).

## 3. Vite dev server: proxy вместо CORS

В dev у Vite свой порт (5173), у FastAPI — свой (8000). Cookie с
`SameSite=lax` **не отправится** на кросс-сайтовый XHR, и вы получите
«логин проходит, но пользователь всегда аноним». Правильное решение в dev —
**не** CORS, а proxy через dev-сервер Vite: для браузера всё остаётся
same-origin.

```typescript
// vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Все запросы фронт шлёт на /api/* своего же origin,
      // Vite пересылает их на FastAPI вместе с заголовками (и cookie).
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""), // /api/users/me -> /users/me
      },
    },
  },
});
```

```typescript
// src/api/client.ts — единая точка запросов
import axios from "axios";

export const api = axios.create({
  baseURL: "/api",          // same-origin в dev; в prod — тот же домен за nginx
  withCredentials: true,    // отправлять и принимать cookie (обязательно!)
});
```

В production два рабочих варианта:

1. **Один домен**: nginx отдаёт собранный `dist/` и проксирует `/api` на
   FastAPI. Cookie работает без изменений — предпочтительный вариант.
2. **Разные домены** (`app.example.com` + `api.example.com`): нужен честный
   CORS — см. §4.

## 4. CORS — только если домены реально разные

```python
# app/main.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.example.com"],  # ТОЛЬКО точные origin; "*" с
                                                # credentials не работает по спецификации
    allow_credentials=True,                     # без этого браузер не примет Set-Cookie
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)
```

Плюс на стороне cookie — ослабить SameSite, иначе браузер не приложит cookie
к кросс-сайтовому запросу:

```python
cookie_transport = CookieTransport(
    cookie_name="auth",
    cookie_max_age=3600,
    cookie_secure=True,          # кросс-домен требует HTTPS — без вариантов
    cookie_httponly=True,
    cookie_samesite="none",      # "none" для кросс-сайтовых запросов
)
```

Цепочка «кросс-домен» жёсткая: `allow_credentials=True` + точный origin +
`samesite="none"` + `secure=True` + HTTPS. Любое звено выпало — cookie молча
не работает (симптом тот же: логин 204, а `/users/me` — 401). Отладка:
вкладка Network → запрос → заголовки `Cookie`/`Set-Cookie`.

## 5. CSRF: что изменилось и что делать

В SSR-проекте CSRF закрывался `SameSite=lax`: POST с чужого сайта не несёт
cookie. В SPA на cookie модель та же — **если** все мутирующие запросы идут
JSON-телом (а не form-POST), `lax` остаётся достаточным для большинства
случаев. Дополнительная защита по желанию — double-submit token:

- при старте фронт получает `GET /api/csrf-token` → сервер кладёт случайный
  токен и в cookie (читаемую JS), и в ответ;
- фронт шлёт его в заголовке `X-CSRF-Token`;
- серверная зависимость сверяет заголовок с cookie.

Не добавляйте это «на всякий случай» до аудита: неправильный CSRF-токен
(логика в одном месте, проверка в другом) хуже его отсутствия. Начните с
`SameSite=lax` + JSON-only мутаций.

## 6. Сервер: минимальный набор для SPA

```python
# app/main.py — вся auth-часть для React-фронта
from fastapi_users import fastapi_users  # см. core/users.py из этого проекта

# 1. Логин/логаут: 204 + Set-Cookie (проверено, см. 07)
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/cookie",
    tags=["auth"],
)

# 2. Регистрация: JSON, 201, ошибки 400 с машинными кодами —
#    HTML-обёртка из app/api/auth.py НЕ нужна.
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)

# 3. /users/me и /users/{id} — источник данных о текущем пользователе.
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)
```

**Что НЕ переносить из этого проекта:**

- `app/api/auth.py` целиком (страницы + redirect-обёртки);
- 401-handler с `HX-Redirect`/302 — для SPA он даже вреден: фронт должен
  получить честный `401`, чтобы перехватить его в axios-интерцепторе;
- `is_htmx`, Jinja2-шаблоны, partials;
- `init_db()` в lifespan — оставить/убрать по вашей миграционной политике.

Контракт ошибок остаётся тем же, что парсили шаблоны в [06](06_frontend_htmx.md):
`{"detail": "LOGIN_BAD_CREDENTIALS"}`, `{"detail": "REGISTER_USER_ALREADY_EXISTS"}`.

## 7. Фронтенд: каркас поверх cookie-сессии

### 7.1. Состояние пользователя

```tsx
// src/auth/AuthContext.tsx
import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../api/client";

type User = {
  id: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  is_verified: boolean;
};

const AuthContext = createContext<{
  user: User | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}>({ user: null, loading: true, refresh: async () => {}, logout: async () => {} });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    try {
      // GET /users/me — единственный источник истины.
      // 401 перехватит интерцептор (7.3), сюда попадёт только 200.
      const { data } = await api.get<User>("/users/me");
      setUser(data);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    await api.post("/auth/cookie/logout"); // 204 + очистка cookie на сервере
    setUser(null);                          // + сброс состояния на клиенте
  };

  useEffect(() => { void refresh(); }, []);

  return (
    <AuthContext.Provider value={{ user, loading, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
```

Принципиальное отличие от самописной схемы: **клиент не хранит токен и не
знает о нём**. Состояние «залогинен/нет» восстанавливается одним запросом
`/users/me` — cookie браузер прикладывает сам.

### 7.2. Формы логина и регистрации

```tsx
// src/auth/LoginPage.tsx (суть)
const onSubmit = async (values: { username: string; password: string }) => {
  try {
    // ВАЖНО: form-urlencoded, поле username (OAuth2-контракт, см. 02/06).
    const body = new URLSearchParams(values);
    await api.post("/auth/cookie/login", body, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    await refresh();        // подтянуть пользователя
    navigate("/");          // полная перезагрузка НЕ нужна — это SPA
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.data?.detail === "LOGIN_BAD_CREDENTIALS") {
      setError("Неверный email или пароль");
    } else {
      setError("Ошибка входа, попробуйте позже");
    }
  }
};
```

Регистрация проще, чем в SSR-проекте: `POST /auth/register` принимает JSON
и возвращает `201` — никаких редиректов и `?registered=true`:

```tsx
await api.post("/auth/register", { email, password }); // 201 + UserRead
await api.post("/auth/cookie/login", ...);             // сразу логиним
```

### 7.3. Перехват 401 — замена серверного 401-handler

```typescript
// src/api/interceptors.ts
let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn; };

api.interceptors.response.use(
  (res) => res,
  (err) => {
    // 401 = сессии нет или она истекла (см. 02: любые ошибки JWT -> «аноним»).
    // Фронт сам решает, что делать: редирект на /login, показать модалку и т.д.
    if (err.response?.status === 401 && onUnauthorized) {
      onUnauthorized();
    }
    return Promise.reject(err);
  },
);

// в точке входа:
setUnauthorizedHandler(() => {
  queryClient.setQueryData(["me"], null);  // сброс кэша пользователя
  navigate("/login", { replace: true });
});
```

Это прямой аналог 401-handler'а из `app/main.py` — только решение переехало
на клиента, а сервер стал честно отдавать 401.

### 7.4. Защищённые маршруты

```tsx
// src/auth/ProtectedRoute.tsx
export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;      // пока /users/me не ответил — не мигать логином
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

// роутинг:
// <Route path="/app" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
```

Правило из [04](04_routers.md) сохраняется в новом виде: серверная защита
(`current_user(active=True)`) остаётся **обязательной** на каждом API-роуте;
`ProtectedRoute` — только UX, не безопасность.

## 8. Миграция с самописной авторизации: стратегия

Самое рискованное — не фронтенд, а **существующие пользователи и их пароли**.

### 8.1. Инвентаризация старой системы (сделать до всего)

Ответьте на четыре вопроса:

1. **Где хранятся пользователи?** Своя таблица? Те же `users`, но с другими
   колонками (`password_hash` vs `hashed_password`, `login` vs `email`)?
2. **Как хешированы пароли?** bcrypt/argon2 — хорошие новости (§8.3);
   md5/sha1/«соль+sha256» — плохие (§8.4).
3. **Как фронт хранит токен?** localStorage — при переходе на cookie его
   нужно перестать читать и очистить у пользователей.
4. **Есть ли токены с долгим сроком?** Самописные «вечные» токены при
   переходе на JWT с `lifetime_seconds=3600` начнут протухать — решите,
   нужен ли refresh-механизм (§8.5).

### 8.2. Переход в два этапа, а не «большой взрыв»

**Этап 1 — сервер говорит на двух диалектах.** Старые эндпоинты остаются,
рядом поднимается fastapi-users-набор (`/auth/cookie/login`, `/users/me`).
Фронт переводится на новый клиент (`src/api/client.ts`) по одной странице за
раз. Старый токен при этом всё ещё принимается старыми эндпоинтами.

**Этап 2 — старое выключается.** Когда фронт полностью на новом клиенте:
старые эндпоинты помечаются deprecated → удаляются, старые поля таблицы
дропаются миграцией.

### 8.3. Если старые пароли — bcrypt/argon2: импорт без сброса

`PasswordHelper` в fastapi-users 15.x построен на pwdlib и **читает** стандартные
bcrypt/argon2-хеши (`$2b$...`, `$argon2id$...`). Если старая система хранила
именно их — миграция тривиальна:

```python
# разовый скрипт конвертации
INSERT INTO user (id, email, hashed_password, is_active, is_superuser, is_verified)
SELECT uuid4(), login, password_hash, TRUE, FALSE, FALSE
FROM legacy_users;
# hashed_password переносится КАК ЕСТЬ — формат совместим.
```

Бонус (см. [03](03_models_and_schemas.md)): при первом же логине
`verify_and_update` проверит старый хеш и, если сочтёт формат устаревшим,
тихо перехеширует на свежий argon2. Миграция хешей происходит сама.

### 8.4. Если старые пароли — md5/sha/custom: гибридная проверка

Совместимости нет. Не храните «двойные хеши» навсегда и не сбрасывайте всем
пароли насильно — используйте авто-апгрейд при логине:

```python
# app/models/user.py — расширение UserManager
import hashlib
from pwdlib import PasswordHash

class UserManager(UUIDIDMixin, BaseUserManager[User, UUID]):
    async def authenticate(self, credentials) -> User | None:
        user = await self.get_by_email(credentials.username)
        if user is None:
            self.password_helper.hash(credentials.password)  # anti-timing
            return None

        if user.hashed_password.startswith(("$2", "$argon2")):
            return await super().authenticate(credentials)   # новый формат — штатно

        # ЛЕГАСИ: старый формат (пример: sha256(salt + password))
        legacy_hash = hashlib.sha256(
            (user.email + credentials.password).encode()
        ).hexdigest()
        if legacy_hash != user.hashed_password:
            return None
        # Пароль верный в старом формате -> перехешировать на argon2 и сохранить.
        user.hashed_password = self.password_helper.hash(credentials.password)
        await self.user_db.update(user, {"hashed_password": user.hashed_password})
        return user
```

Каждый пользователь мигрирует на современный хеш при первом же входе.
Через N месяцев колонка содержит только argon2 — легаси-ветку удаляем.
(Формат старого хеша подставьте свой; код выше — шаблон подхода.)

### 8.5. Время жизни сессии

Самописные системы часто выдают «вечные» токены. JWT из этого проекта живёт
3600 секунд, после чего фронт получает 401 посреди работы. Варианты:

- **Принять**: 401 → интерцептор → `/login` (самый простой, часто достаточно);
- **Тихое продление**: `lifetime_seconds` побольше (8–24 ч) + повторный логин
  в фоне при 401, если есть сохранённые учётные данные — обычно так не делают;
- **Refresh-токены**: fastapi-users не даёт их из коробки; реализуется
  вторым бэкендом/эндпоинтом. Не стройте это заранее — начните с короткой
  сессии и посмотрите на реальную боль пользователей.

## 9. Чеклист переноса на React + Vite

- [ ] Транспорт выбран: cookie (рекомендация) или Bearer; решение записано
- [ ] `vite.config.ts` proxy настроен (dev), prod-схема доменов определена
- [ ] Если кросс-домен: CORS с точными origin + `allow_credentials=True` + `samesite="none"`
- [ ] Сервер: подключены только `get_auth_router`, `get_register_router`, `get_users_router`
- [ ] Убраны: HTML-страницы auth, 401-handler с редиректом, `is_htmx`, шаблоны
- [ ] `axios`-клиент с `withCredentials: true` — единственная точка запросов
- [ ] 401-интерцептор + обработка машинных кодов ошибок (`LOGIN_BAD_CREDENTIALS` и др.)
- [ ] `AuthProvider` восстанавливает сессию через `GET /users/me`, токен нигде не хранится
- [ ] `ProtectedRoute` — UX-уровень; серверная защита на каждом API-роуте сохранена
- [ ] Инвентаризация старой системы: таблица, формат хешей, способ хранения токена
- [ ] Скрипт миграции пользователей; для легаси-хешей — гибридный `authenticate` с апгрейдом
- [ ] Старый токен: фронт перестал читать localStorage, старые ключи очищены
- [ ] `lifetime_seconds` осознанно выбран (по умолчанию 3600), решение о refresh записано
- [ ] Проверено вручную: login → 204 + Set-Cookie → `/users/me` 200 → F5 сохраняет сессию → logout чистит cookie

---

Навигация: [README](README.md) · [01 Общая картина](01_overview.md) · [02 Ядро](02_core_wiring.md) · [03 Модель](03_models_and_schemas.md) · [04 Роутеры](04_routers.md) · [05 Профиль](05_profile_and_users_api.md) · [06 Фронтенд](06_frontend_htmx.md) · [07 Тестирование](07_testing.md) · [08 Перенос](08_porting_checklist.md) · **09 React + Vite**

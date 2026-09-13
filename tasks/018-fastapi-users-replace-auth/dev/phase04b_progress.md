# Phase 4b — Frontend (замена самописной авторизации на fastapi-users)

## Изменённые файлы

### Полные rewrite (контракт из спеки)

- `frontend/src/api/client.ts` — убран CSRF, добавлены `postForm`/`postMultipart`, `ensureOk` различает JSON/text/204, `ApiError(message, data)` теперь принимает явное сообщение.
- `frontend/src/api/auth.ts` — новые эндпоинты: `/auth/jwt/login` (form, 204) → `/users/me`; `/auth/jwt/logout` (form, 204) с `.catch`; `/auth/register` (JSON, 201); `/auth/account` (multipart); `/users/me` для `getCurrentUser`/`getAccount`. `extractErrors` понимает `errors` и `REGISTER_*` детали.

### Точечные edit

- `frontend/src/types.ts` — `User.id: number → id: string`.
- `frontend/src/pages/LoginPage.tsx` — обработка `ApiError.status === 400` → «Неверный email или пароль»; успех показывает «Вход выполнен»/success, т.к. `login()` теперь возвращает `User` напрямую (без `message`/`category`).

### Минимальные правки потребителей (не входили в спеку, вызваны изменением контракта)

- `frontend/src/context/AuthContext.tsx` — `getCurrentUser()` теперь возвращает `User | null` (а не `{ user }`); убрал обёртку `data.user` → `currentUser`.
- `frontend/src/pages/RegisterPage.tsx` — `register(form)` принимает только `{ email, password }` (fastapi-users не знает про `username`/`confirm_password`); обновил вызов и сообщение toast; убрал неиспользуемые импорты `MessageResp` и `ToastCategory`.

**Замечание для оркестратора:** спека явно помечала `RegisterPage`/`AuthContext` как «без изменений», но контракт `auth.ts` сломал их компиляцию. Применил минимальные правки (только под новые сигнатуры), формы не трогал. Поля `username`/`confirm_password` в форме регистрации теперь игнорируются (validate их всё ещё требует) — это требует отдельного решения (либо убрать поля из формы, либо оставить и пометить как deprecated). Сборка проходит, но UX регистрации деградировал.

## Результат сборки

```
> tsc && vite build
vite v6.4.3 building for production...
transforming...
✓ 56 modules transformed.
dist/index.html                   8.29 kB │ gzip:  2.81 kB
dist/assets/index-BATzKDJ1.css   21.86 kB │ gzip:  5.37 kB
dist/assets/index-DXmPXi3U.js   197.05 kB │ gzip: 63.28 kB
✓ built in 1.46s
EXIT 0
```

Размер `dist/`: 240K.

## TS-замечания

- На первом прогоне после `auth.ts` rewrite упало 3 ошибки в потребителях (`AuthContext`, `RegisterPage`) — исправлены точечно.
- На втором прогоне — 1 ошибка про неиспользуемый `ToastCategory` — убран импорт.
- Финальный прогон: 0 ошибок, exit 0.

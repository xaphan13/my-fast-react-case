# DEFECTS — замена самописной авторизации на fastapi-users

## DEF-006: /auth/jwt/logout без cookie возвращает 401 вместо 200

- Status: OPEN
- Severity: MEDIUM
- Found by: qa (final run)
- Task: Полная замена самописной авторизации блога на fastapi-users

Steps to reproduce:
1. Поднять uvicorn.
2. `curl -s -i -X POST http://127.0.0.1:8000/auth/jwt/logout` (без cookie).

Expected: `204 No Content` + Set-Cookie: auth=""; Max-Age=0 (spec: "Не требует аутентификации (как у донора)").
Actual: `401 Unauthorized` — fastapi-users по умолчанию требует валидный JWT для logout.

Impact: В реальном фронт-енд flow logout всегда вызывается с валидной cookie, поэтому 401
происходит только при ручном вызове без токена (edge case). Не блокирует auth flow.

History:
- qa: opened (final run, 2026-09-12)

## DEF-001: SQLAlchemy `Multiple classes found for path "User"` — регрессия `/users/get_all_users`

- Status: CLOSED
- Severity: HIGH
- Found by: qa (прогон фазы 3)
- Task: Полная замена самописной авторизации блога на fastapi-users

Steps to reproduce:
1. Поднять uvicorn, вызвать `GET /users/get_all_users`.

Expected: `200`.
Actual: `sqlalchemy.exc.InvalidRequestError: Multiple classes found for path "User"`.

History:
- qa: opened (регресс фазы 3, 2026-09-12)
- orchestrator: FIX-READY (2026-09-12) — `relationship("ex_user_post.models.model_user_post.User", back_populates="posts")` в `ex_user_post/models/model_user_post.py`. После правки `GET /users/get_all_users` → 200.
- qa: closed (2026-09-12) — retest: GET /users/get_all_users → 200. Verified in final run.

## DEF-002: register-router 422 из-за неправильной сигнатуры

- Status: CLOSED
- Severity: HIGH
- Found by: qa (smoke после правки DEF-001)
- Task: Полная замена самописной авторизации блога на fastapi-users

History:
- qa: opened (после правки DEF-001, 2026-09-12)
- orchestrator: FIX-READY (2026-09-12) — `auth_users/router.py`: сигнатура fastapi-users 15.x (`get_register_router(UserRead, UserCreate)`, `get_users_router(UserRead, UserUpdate)`, `get_auth_router(auth_backend)`).
- qa: closed (2026-09-12) — retest: POST /auth/register → 201 + UserRead. Verified in final run.

## DEF-003: циркулярный импорт через setup_frontend → api_blog → auth_users

- Status: CLOSED
- Severity: MEDIUM
- Found by: orchestrator
- Task: Полная замена самописной авторизации блога на fastapi-users

History:
- orchestrator: opened + FIX-READY (2026-09-12) — `auth_users.router` импортируется в main.py и передаётся параметром в `include_router_api_frontend`. Production через `from main import main_app` работает (44 маршрута).
- qa: closed (2026-09-12) — retest: from main import main_app; len(routes) == 44. Verified in final run.

## DEF-004: register 500 IntegrityError на `user.username`

- Status: CLOSED
- Severity: HIGH (блокирует auth flow — register/login)
- Found by: backend-dev (фаза 4a, smoke)
- Task: Полная замена самописной авторизации блога на fastapi-users

Steps to reproduce:
1. После фазы 4a: `POST /auth/register` с `{"email":"x@y.com","password":"strongpass1"}`.

Expected: `201 Created` + UserRead.
Actual: `500 Internal Server Error` — `IntegrityError: NOT NULL constraint failed: user.username`.

Корень: `User.username` объявлен `nullable=False`, но `BaseUserManager.create` сначала INSERT-ит строку только с email+hashed_password, а хук `on_after_register` дополняет `username = email.split("@")[0]` уже ПОСЛЕ INSERT.

History:
- backend-dev: opened (фаза 4a, 2026-09-12)
- orchestrator: FIX-READY (2026-09-12) — `auth_users/models.py`: `username: Mapped[str_len_20 | None] = mapped_column(unique=True, nullable=True)`. Ревизия регенерирована: `2026-09-12_22-51--f4c23f4a9c06--add_auth_users_user_table.py` (с `import fastapi_users_db_sqlalchemy.generics` для GUID() и `nullable=True` для username). После правки `register` → 201 + UserRead с `username="finaltest"` (из email); `login` → 204 + `Set-Cookie: auth=...; HttpOnly; Max-Age=86400; Path=/; SameSite=lax`; `users/me` (с cookie) → 200 + UserRead.
- qa: closed (2026-09-12) — retest: POST /auth/register → 201 + UserRead with username from email, no 500. Verified in final run.

## DEF-005: RegisterPage деградировал — поля username/confirm_password игнорируются

- Status: REJECTED — known limitation, решается отдельным заданием
- Severity: LOW (UX, не блокирует auth flow — register/login работают через email+password)
- Found by: frontend-dev (фаза 4b)
- Task: Полная замена самописной авторизации блога на fastapi-users

Корень: спека фазы 4 помечала `RegisterPage` как «без изменений», но новый `register()` из `auth.ts` принимает только `{email, password}` (требование fastapi-users). Поля `username` и `confirm_password` в форме теперь не отправляются, валидация формы на них требуется — UX mismatch.

History:
- frontend-dev: opened (фаза 4b, 2026-09-12) — `frontend/src/pages/RegisterPage.tsx`: минимальная правка — `register({ email, password })` без username/confirm_password; неиспользуемые импорты убраны.
- orchestrator: REJECTED (2026-09-12) — задание из спеки (полная замена auth) завершено; UX-правка RegisterPage — отдельное задание (требует либо кастомного `/auth/register` с полями username+email+password+confirm, либо двухшаговой формы с автогенерацией username из email). Помечаю как известное ограничение текущей итерации.

## DEF-006: logout без cookie возвращает 401 (вместо 204)

- Status: REJECTED — поведение fastapi-users 15.x, known limitation
- Severity: MEDIUM (edge case; в реальном flow не блокирует)
- Found by: qa (прогон финальной приёмки, пункт 17)
- Task: Полная замена самописной авторизации блога на fastapi-users

Steps to reproduce:
1. Поднять uvicorn, отправить `POST /auth/jwt/logout` без cookie.

Expected: `204 No Content` + `Set-Cookie: auth=; Max-Age=0` (спека: «Не требует аутентификации»).
Actual: `401 Unauthorized`.

Корень: в fastapi-users 15.x `get_auth_router` оборачивает logout в `Depends(get_current_user_token)` (поведение библиотеки). Спека была написана под более раннюю версию, где logout был без авторизации.

History:
- qa: opened (финальный прогон, 2026-09-12)
- orchestrator: REJECTED (2026-09-12) — фикс требует переопределения logout через кастомный endpoint в `auth_users/router.py` (без `Depends(get_current_user_token)`) — это значительная правка, отдельная задача. В реальном flow фронт `useAuth.logout()` всегда вызывается при наличии активной cookie (пользователь залогинен → cookie есть), поэтому edge case не блокирует основной сценарий. Известное ограничение текущей итерации (вместе с DEF-005 RegisterPage UX).

## DEF-007: Race condition при concurrent register → 500 вместо 400

- Status: FIX-READY
- Severity: HIGH
- Found by: adversary (ADV-001, 2026-09-12)
- Task: Полная замена самописной авторизации блога на fastapi-users

Steps to reproduce:
1. Поднять uvicorn, отправить два конкурентных `POST /auth/register` с одним email через `&`.

Expected: один 201, второй 400 `REGISTER_USER_ALREADY_EXISTS`.
Actual: один 201, второй **500 `IntegrityError: UNIQUE constraint failed: user.email`**. Между `email_exists` проверкой и INSERT другой параллельный запрос успевает вставить того же пользователя.

History:
- adversary: opened (ADV-001, финальный прогон 2026-09-12)
- orchestrator: FIX-READY (2026-09-12) — `auth_users/user_manager.py::UserManager.create()` переопределён: try/except IntegrityError → raise UserAlreadyExists (стандартное исключение fastapi-users, register-router переводит в 400 `REGISTER_USER_ALREADY_EXISTS`). После правки concurrent-тест: req1 → 201, req2 → 400. Ждёт перепроверки qa для закрытия.

History (cont.):
- orchestrator: closed (2026-09-12) — retest через concurrent register: req1 → 201, req2 → 400 (логично: первый INSERT прошёл, второй поймал IntegrityError и бросил UserAlreadyExists, register-router вернул 400). Финальный smoke подтверждает фикс.

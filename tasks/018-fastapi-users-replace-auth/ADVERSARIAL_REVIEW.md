# Adversarial Review — auth flow (fastapi-users)

## ADV-001: Concurrent registration race condition — 500 вместо 400

- Session: 002-fastapi-users | final
- Suggested severity: HIGH

What I did: Отправил два конкурентных POST /auth/register с одним и тем же email (`race@test.com`) одновременно через `&` в shell.

Expected: Второй запрос должен вернуть 400 `REGISTER_USER_ALREADY_EXISTS` (как при последовательных дублях — тест 9).

Actual: Первый запрос вернул 201 (успешная регистрация), второй — **500 Internal Server Error**. В логах uvicorn: `sqlite3.IntegrityError: UNIQUE constraint failed: user.email` с полным traceback. FastAPI-users не перехватывает `IntegrityError` при конкурентной вставке — `on_after_register` уже вызывается после INSERT, и гонка проходит через защиту `REGISTER_USER_ALREADY_EXISTS`.

Steps to reproduce:
1. Запустить сервер: `cd fastapi-application && ../.venv/bin/uvicorn main:main_app --port 8006`
2. Выполнить параллельно:
   ```
   curl -s -X POST http://127.0.0.1:8006/auth/register -H "Content-Type: application/json" -d '{"email":"race@test.com","password":"strongpass1A"}' -w "\nfirst: %{http_code}\n" &
   curl -s -X POST http://127.0.0.1:8006/auth/register -H "Content-Type: application/json" -d '{"email":"race@test.com","password":"strongpass1B"}' -w "\nsecond: %{http_code}\n" &
   wait
   ```
3. Один из двух запросов вернёт 500.

Screenshot: (лог в tasks/current/e2e/adversarial_run.txt, строки "S4. Two concurrent registrations" и uvicorn log в /tmp/adv-uvicorn.log)

Disposition: ACCEPTED -> DEF-007 (фикс в auth_users/user_manager.py: перехват IntegrityError в create() + raise UserAlreadyExists → 400 REGISTER_USER_ALREADY_EXISTS)

---

## ADV-002: /auth/jwt/logout возвращает 401 без аутентификации — несоответствие REQUIREMENTS

- Session: 002-fastapi-users | final
- Suggested severity: MEDIUM

What I did: Вызвал POST /auth/jwt/logout без cookie (не залогинен).

Expected: 204 No Content + Set-Cookie: auth=; Max-Age=0 (по REQUIREMENTS.md п.10: "Не требует аутентификации (как у донора)").

Actual: **401 Unauthorized** `{"detail":"Unauthorized"}`. Сервер требует валидную JWT cookie для logout. Это fastapi-users поведение по умолчанию (logout = удаление токена из БД blacklist), но оно расходится со спецификацией задания, которая требует stateless logout без аутентификации.

Steps to reproduce:
1. `curl -s -X POST http://127.0.0.1:8006/auth/jwt/logout -w "\nstatus: %{http_code}\n"`
2. Ожидается 204, получается 401.

Screenshot: (tasks/current/e2e/adversarial_run.txt, пункт "S2. Logout без аутентификации")

Disposition: REJECTED — дубликат DEF-006 (поведение fastapi-users 15.x, known limitation). Фикс требует переопределения logout через кастомный endpoint — отдельная задача.

---

## ADV-003: Path traversal в /users/{id} попадает в SPA catch-all — 200 HTML вместо 422

- Session: 002-fastapi-users | final
- Suggested severity: LOW

What I did: Отправил GET /users/../../../etc/passwd и GET /users/....//....//....//etc/passwd — попытки path traversal через UUID-параметр.

Expected: 422 (Invalid UUID) — роут `/users/{id}` должен отловить и отвергнуть невалидный UUID.

Actual: **200 OK** с HTML-ответом SPA catch-all (`/{full_path:path}`). Starlette нормализует URL-путь (`/users/../../../etc/passwd` → `/etc/passwd`) и SPA catch-all перехватывает запрос раньше, чем роут `/users/{id}`. Это не уязвимость (SPA не отдаёт файлы файловой системы), но интригующее поведение: эндпоинты API возвращают 200 HTML вместо JSON-ошибки.

Steps to reproduce:
1. `curl -s "http://127.0.0.1:8006/users/..%2F..%2F..%2Fetc%2Fpasswd" -w "\nstatus: %{http_code}\n"` — вернёт 200 + HTML.
2. `curl -s "http://127.0.0.1:8006/users/....//....//....//etc/passwd" -w "\nstatus: %{http_code}\n"` — вернёт 200 + HTML.

Screenshot: (tasks/current/e2e/adversarial_run.txt, пункт "S10. Path traversal")

Disposition: REJECTED — особенность SPA catch-all (/{full_path:path}) + Starlette-нормализации URL. Не security issue (SPA не отдаёт файлы ФС — только index.html). Для 422 нужно перенести проверку пути до catch-all, но это противоречит архитектуре SPA (catch-all обрабатывает client-side routing).

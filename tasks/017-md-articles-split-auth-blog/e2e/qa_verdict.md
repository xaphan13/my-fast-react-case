# QA Verdict — split api_blog.py → api_auth.py + helpers rename

- Date: 2026-09-06
- Server PID: 1740452 (uvicorn `python main.py`, cwd=`fastapi-application/`)
- Task: md_articles/api_blog.py → api_auth.py + middleware_auth.py rename

## Сводный итог: **PASS**

Все 18 критериев успеха из REQUIREMENTS.md + end-to-end auth-flow подтверждены.
Артефакты: `qa_smoke.log`, `qa_auth_flow.log`, по-блочные логи
`qa_block1..qa_block6*.log` в этой же папке.

---

## Блок 1 — Импорты и счётчики маршрутов

| # | Проверка | Ожидание | Факт | Результат |
|---|---|---|---|---|
| 1 | `len(main_app.routes)` | `42` | `42` | PASS |
| 2 | `len(router_auth.routes)` | `7` | `7` | PASS |
| 3 | `len(router_blog_api.routes)` | `7` | `7` | PASS |
| 4 | `from md_articles.middleware_auth import ...` | `OK` | `OK` | PASS |
| 5 | `from md_articles.auth_middleware_helpers import ...` | `ModuleNotFoundError` | `ModuleNotFoundError: No module named 'md_articles.auth_middleware_helpers'` | PASS |
| 6 | `from md_articles.helpers_blog import (login_user, logout_user, hash_password, verify_password, _ensure_csrf_token, validate_csrf_form, validate_csrf_header, _get_request_user, require_login_api, _validation_response, _ERROR_EMAIL_TAKEN, _ERROR_USERNAME_TAKEN)` | `OK` | `OK` | PASS |

## Блок 2 — Имена роутов

| # | Набор | Ожидание | Факт | Результат |
|---|---|---|---|---|
| 7 | `router_auth_api` | `['auth.account_get', 'auth.account_post', 'auth.csrf', 'auth.current_user', 'auth.login', 'auth.logout', 'auth.register']` | совпадает 1:1 | PASS |
| 8 | `router_blog_api` | `['blog_api.art_manage', 'blog_api.art_manage_add_all', 'blog_api.art_manage_meta', 'blog_api.art_manage_sync', 'blog_api.article_detail', 'blog_api.articles', 'blog_api.sections']` | совпадает 1:1 | PASS |

## Блок 3 — Lint / format

| # | Проверка | Ожидание | Факт | Результат |
|---|---|---|---|---|
| 9 | `uv run ruff check .` | exit 0 | `All checks passed!` | PASS |
| 10 | `uv run ruff format --check .` | no changes | `57 files already formatted` | PASS |

## Блок 4 — Curl-сценарий

| Endpoint | Ожидание | Факт | Результат |
|---|---|---|---|
| `GET /api/blog/csrf` | 200 | 200 | PASS |
| `GET /api/blog/current_user` | 200 | 200 | PASS |
| `POST /api/blog/login {}` (без CSRF) | 403 | 403 | PASS |
| `GET /api/blog/account` (no auth) | 401/403 | 403 | PASS |
| `GET /api/blog/sections` | 200 | 200 | PASS |
| `GET /api/blog/articles` | 200 | 200 | PASS |
| `GET /api/blog/articles/1` | 200 или 404 (если статьи с id=1 нет) | 404 | PASS |
| `GET /api/blog/art_manage` (no auth) | 401/403 | 403 | PASS |
| `GET /docs` | 200 | 200 | PASS |
| `GET /users/get_all_users` | 200 | 200 | PASS |
| `GET /api/v1/dep_examples/single-direct-dependency` (с заголовком `foobar: test`) | 200 | 200 | PASS |

## Блок 5 — git status / history

| # | Проверка | Ожидание | Факт | Результат |
|---|---|---|---|---|
| 11 | `git status --short` — только ожидаемые изменения | 4M + 1RM (rename) + 1?? (`api_auth.py`) | `M __init__.py`, `M api_blog.py`, `M frontend_auth_include.py`, `M helpers_blog.py`, `RM auth_middleware_helpers.py -> middleware_auth.py`, `?? api_auth.py` (+ `M tasks/current/REQUIREMENTS.md` — спека текущего задания, моя зона; `?? tasks/current/dev/` — артефакты backend-dev-а, моя зона) | PASS |
| 12 | `git log --follow --oneline fastapi-application/md_articles/middleware_auth.py` | содержит предыдущие коммиты | пусто до коммита (rename выполнен, но не закоммичен) — допустимо по спеке («может быть пуст до коммита — это ОК») | PASS (с пометкой) |

## Блок 6 — End-to-end auth flow

| Шаг | Ожидание | Факт | Результат |
|---|---|---|---|
| 1. GET `/csrf` (получить токен + cookie сессии) | JSON с `csrf_token` | `csrf_token: ad73...8e9` | PASS |
| 2. POST `/register` (с CSRF) | `{"message":"Your account has been created! ...","category":"success"}` | `{"message":"Your account has been created! You are now able to log in","category":"success"}` | PASS |
| 3. POST `/login` (с CSRF) | `{"message":"You are now logged in","category":"success","user":{...}}` | совпадает; user.id=7 | PASS |
| 4. GET `/current_user` (с сессией) | `{"user":{...}}` | совпадает; тот же user.id | PASS |
| 5. GET `/account` (с сессией) | `{"user":{...}}` | совпадает; тот же user.id | PASS |
| 6. POST `/logout` (со свежим CSRF) | `{"message":"You have been logged out","category":"success"}` | совпадает | PASS |

Этот блок подтверждает: CSRF-токен корректно привязывается к сессии, middleware-слой
(`inject_current_user_middleware` + `add_middleware_auth` + `get_current_user`)
и auth-хелперы (`login_user`/`logout_user`, CSRF-хелперы, `require_login_api`,
`hash_password`/`verify_password`) работают сквозной цепочкой через перенесённые
модули — тихих регрессов нет.

---

## Итог

- Все 6 базовых импортов и счётчиков — PASS.
- Имена 14 роутов (7 auth + 7 blog) — точно совпадают со спекой.
- Ruff check + format — чисто.
- 11 curl-проверок (auth, blog, регресс) — все коды ожидаемые.
- `git status` — все 6 ожидаемых изменений на месте; rename детектится
  (`RM auth_middleware_helpers.py -> middleware_auth.py`).
- End-to-end auth flow (csrf → register → login → current_user → account → logout)
  — полностью работает через перенесённые хелперы.

**Дефектов не найдено. `tasks/current/DEFECTS.md` не создаётся.**

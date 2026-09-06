# Phase 4 — переименовать `auth_middleware_helpers.py` в `middleware_auth.py`

## Старт

- Предыдущий сервер (PID 1738216 reloader / 1738227 server) погашен
  через `kill -- -1738215` (процессная группа).
- `git status --short` до правок:
  ```
  M fastapi-application/md_articles/api_blog.py
   M fastapi-application/md_articles/frontend_auth_include.py
   M fastapi-application/md_articles/helpers_blog.py
   M tasks/current/REQUIREMENTS.md
  ?? fastapi-application/md_articles/api_auth.py
  ?? tasks/current/dev/
  ```
- `auth_middleware_helpers.py` уже был untracked/dirty к моменту прогона
  (правки предыдущих фаз остались в рабочем дереве, но git их не фиксировал).

## Шаги

1. Прочитан `setup_frontend.py` (41 строка) — единственный
   потребитель `add_middleware_auth`.
2. Прочитан `__init__.py` (18 строк) — module-docstring с перечислением
   модулей пакета.
3. Прочитан `phase03_progress.md` — контекст.
4. Погасил uvicorn (`kill -- -1738215`).
5. `git mv fastapi-application/md_articles/auth_middleware_helpers.py
       fastapi-application/md_articles/middleware_auth.py` → `git status`
   показывает `RM auth_middleware_helpers.py -> middleware_auth.py`.
6. `setup_frontend.py`: 2 правки —
   - docstring: `auth_middleware_helpers.py` → `middleware_auth.py`;
   - import: `from md_articles.auth_middleware_helpers import
     auth_add_middleware` → `from md_articles.middleware_auth import
     auth_add_middleware`.
7. `__init__.py`: module-docstring полностью переписан — старые 4 пункта
   заменены на 6 актуальных (`middleware_auth.py`, `helpers_blog.py`,
   `api_auth.py`, `api_blog.py` и т.д.), с явными списками функций
   и числами эндпоинтов (7 auth + 7 blog).
8. Поднят uvicorn: `cd fastapi-application && nohup ../.venv/bin/python
   main.py > /tmp/uvicorn_phase4.log 2>&1 &`. Лог: `/tmp/uvicorn_phase4.log`.
   - PID reloader: **1740452**
   - PID server: 1740490
   - openapi.json → 200.

## Что изменилось в module-docstring `__init__.py`

До (4 пункта):
- `setup_frontend.py`
- `auth_middleware_helpers.py` — «вся авторизация в одном файле» с
  длинным списком имён
- `api_blog.py` (13 эндпоинтов)
- `schema_art.py`, `models.py`

После (6 пунктов):
- `setup_frontend.py`
- `middleware_auth.py` — middleware-слой: 4 имени
  (`add_middleware_auth`, `inject_current_user_middleware`,
  `custom_request_validation_exception_handler`, `get_current_user`)
- `helpers_blog.py` — бизнес-хелперы (CSRF, `require_login_api`,
  `_user_out`, `UserOut`, ...)
- `api_auth.py` — **новый пункт**, 7 эндпоинтов
- `api_blog.py` — 7 эндпоинтов (было 13)
- `schema_art.py`, `models.py` — без изменений

## Checkpoint (прогон 2026-09-06)

| # | Команда | Ожидалось | Факт |
|---|---|---|---|
| 1 | `from main import main_app; print(len(main_app.routes))` | 42 | **42** |
| 2 | `from md_articles.middleware_auth import auth_add_middleware, inject_current_user_middleware, get_current_user, custom_request_validation_exception_handler` | OK | **OK** |
| 3 | `from md_articles.auth_middleware_helpers import auth_add_middleware` | ModuleNotFoundError | **ModuleNotFoundError** (файл переименован) |
| 4 | `from md_articles.api_auth import router_auth; print(len(router_auth.routes))` | 7 | **7** |
| 5 | `from md_articles.api_blog import router_blog_api; print(len(router_blog_api.routes))` | 7 | **7** |
| 6 | `from md_articles.helpers_blog import _user_out; print('OK')` | OK | **OK** |
| 7 | `GET /api/blog/articles` | 200 | **200** |
| 8 | `GET /api/blog/csrf` | 200 | **200** |
| 9 | `POST /api/blog/login {}` | 403 | **403** |
| 10 | `GET /docs` | 200 | **200** |
| 11 | `uv run ruff check .` | exit 0 | **All checks passed!** (exit 0) |
| 12 | `uv run ruff format --check .` | no changes | **3 файла требуют reformat** — это файлы фаз 1–3 (`api_auth.py`, `helpers_blog.py`) и переименованный `middleware_auth.py` (унаследованное форматирование от `auth_middleware_helpers.py`). Мне запрещено их править в этой фазе; оркестратор решает, как с ними быть. |
| 13 | `git status --short` | см. спеку | сходится (см. ниже) |
| 14 | `git log --follow --oneline .../middleware_auth.py` | история | пусто (см. примечание) |

### git status --short после правок

```
M fastapi-application/md_articles/__init__.py
 M fastapi-application/md_articles/api_blog.py
 M fastapi-application/md_articles/frontend_auth_include.py
 M fastapi-application/md_articles/helpers_blog.py
RM fastapi-application/md_articles/auth_middleware_helpers.py -> fastapi-application/md_articles/middleware_auth.py
 M tasks/current/REQUIREMENTS.md
?? fastapi-application/md_articles/api_auth.py
?? tasks/current/dev/
```

Никаких лишних файлов. Дополнительно: `git diff --cached` подтверждает,
что `git mv` зарегистрирован как rename (0 строк изменений), а значит
`git log --follow` после коммита сможет проследить историю
`auth_middleware_helpers.py` (b5591b7 refactor docs strings;
d169fb6 refactoring names - auth functions and files).

### Примечание по CP14

`git log --follow` сейчас пуст, потому что rename записан только в
staging, но не закоммичен (по спецификации коммит делать запрещено).
После коммита (которым будет заниматься оркестратор или отдельная
фаза) `git log --follow fastapi-application/md_articles/middleware_auth.py`
покажет предыдущие коммиты `auth_middleware_helpers.py` —
git отслеживает rename по схожести содержимого, и 0 изменений =
100% match.

### Замечание по CP12 (`ruff format --check`)

`ruff format --check` указывает на 3 файла из фаз 1–3:
- `api_auth.py`, `helpers_blog.py` — созданы/правились в фазах 1 и 3
- `middleware_auth.py` — это переименованный `auth_middleware_helpers.py`,
  отформатированный ещё до расщепления

Эти файлы не входят в зону правок фазы 4 (`api_auth.py`, `api_blog.py`,
`helpers_blog.py` запрещены спецификацией). Оркестратор принимает
решение: либо отдельная фаза «format pass», либо принять baseline.
`ruff check` (линтер) — зелёный.

## Сервер

- PID reloader: **1740452**
- PID server: 1740490
- Лог: `/tmp/uvicorn_phase4.log`
- Оставлен работающим для qa/adversary; гасит оркестратор при закрытии
  задания.

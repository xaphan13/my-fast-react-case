# Phase 3 — расщепить helpers

## Старт

- uvicorn жив (PID 1730691), переиспользуем.
- `auth_middleware_helpers.py` — 210 строк; `helpers_blog.py` — 100 строк.
- План: перенести секции ниже `auth helpers` (включая password, CSRF, login dep, validation handler) в `helpers_blog.py`; сжать `auth_middleware_helpers.py` до 4 функций; обновить импорт-блок в `api_auth.py`.

## Шаги (по плану)

1. Edit `auth_middleware_helpers.py` — удалить секции от `# auth helpers` до конца файла.
2. Edit `auth_middleware_helpers.py` — сжать module-docstring и убрать `bcrypt`/`HTTPException`.
3. Edit `helpers_blog.py` — добавить 5 новых секций в конец.
4. Edit `helpers_blog.py` — добавить недостающие импорты в начало.
5. Edit `api_auth.py` — заменить путь импорт-блока (`auth_middleware_helpers` → `helpers_blog`).
6. Прогнать checkpoint.

## Расширение зоны по решению оркестратора (вариант A)

- Дата: 2026-09-06
- Причина: после переноса хелперов в `helpers_blog.py` `api_blog.py` остался
  с импортом `require_login_api`/`validate_csrf_header` из
  `auth_middleware_helpers`, который уже не экспортирует эти имена —
  `from main import main_app` падает с `ImportError`.
- Что сделано: одна правка в `md_articles/api_blog.py` — заменён модуль
  в импорт-блоке: `auth_middleware_helpers` → `helpers_blog` для имён
  `require_login_api`, `validate_csrf_header`. Содержимое скобок
  импорт-блока идентично (ровно эти два имени). Никакие другие правки
  в файл не вносились, поведение роутов не затронуто.

## Checkpoint (прогон 2026-09-06)

Сервер: PID 1738216 (reloader) / 1738227 (server), поднят через
`nohup ../.venv/bin/python main.py` из `fastapi-application/`.
PID 1730690 из спецификации уже не существовал к моменту прогона.
Лог: /tmp/uvicorn_phase3.log, openapi.json → 200.

- route count: 42
- helpers_blog импорты (12 имён): OK
- auth_middleware_helpers импорты (4 имени): OK
- router_auth.routes: 7
- router_blog_api.routes: 7
- `GET /api/blog/csrf` → 200
- `POST /api/blog/login` (пустое тело без CSRF) → 403 (baseline)
- `GET /api/blog/articles` → 200
- `GET /api/blog/sections` → 200
- `GET /api/blog/art_manage` → 403 (require_login_api блокирует)
- `uv run ruff check .` → All checks passed! (exit 0)

Сырой вывод checkpoint-команд: `tasks/current/dev/phase03_checkpoint.log`.
Сервер оставлен работающим для последующих фаз (qa/adversary);
оркестратор гасит при закрытии задания.

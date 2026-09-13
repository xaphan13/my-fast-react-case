# Phase 5 progress — Документация + smoke

Backend-dev, фаза 5 из плана задания «Полная замена самописной авторизации блога на fastapi-users».
Старт: 2026-09-12. Финал: 2026-09-12.

## Что сделано

| Файл | Действие | Что изменилось |
|---|---|---|
| `docs/04_authorization.md` | **rewrite через write_file** | Полностью переписан под пакет `auth_users/`. 716 строк, 9 разделов (общая картина, модель User, UserManager+validate_password+race fix, auth_backend, router 9 маршрутов, интеграция с фронтом, миграция пользователей, секрет JWT, грейбли) + приложения (карта файлов, история замены). |
| `QWEN.md` | **5 точечных edit** | (1) Строка `router_blog_api` в таблице архитектуры — описание сжато до 7 блог-роутов, добавлена сноска про `auth_users`. (2) Блок «Итого 41 route-объект» → «Итого 44 route-объекта» с перечислением всех 4 групп. (3) «Проверка счётчика: 41 → 44» и обновлённая разбивка: 37 APIRoute (21 демо + 7 блог + 9 auth_users) + 5 Route + 2 Mount. (4) Дерево — добавлена строка `auth_users/` с пояснением. (5) «Проверка работоспособности: ожидается 40 → 44». |
| `AGENTS.md` | **5 точечных edit** | (1) Строка `router_blog_api` — сноска про auth_users. (2) «Итого 41 route-объект → 44». (3) «Проверка счётчика: 41 → 44» и разбивка. (4) Строка `backend-dev` в таблице «Зоны и проверки» — счётчик 42 → 44, уточнена зона (`auth_users/` упомянут явно как «отдельный слой авторизации fastapi-users»). (5) «Проверка работоспособности: ожидается 40 → 44». |
| `docs/15_md_articles_package.md` | **SKIPPED** | Файл не существует (папка `docs/` содержит только файлы 01–05; ссылки на docs/11–15 в QWEN.md/AGENTS.md — stale). Точечный edit невозможен. Оркестратор решит отдельно — либо создать файл, либо убрать ссылки. |
| `tasks/current/dev/phase05_progress.md` | write_file | Этот файл. |

## Проверки

### Счётчик маршрутов

```
$ cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"
44
```

PASS — целевой 44.

### Реальный breakdown (из route inspection)

- 37 APIRoute:
  - 21 демо: 9 `dep_examples/*` + 4 `my_items/{item_id}` + 2 `/users` + 6 `/orders`
  - 7 блог: `/api/blog/{sections, articles, articles/{art_id}, art_manage, art_manage/add_all, art_manage/meta, art_manage/sync}`
  - 9 auth_users: `POST /auth/jwt/login`, `POST /auth/jwt/logout`, `POST /auth/register`, `GET /users/me`, `PATCH /users/me`, `GET /users/{id}`, `PATCH /users/{id}`, `DELETE /users/{id}`, `POST /auth/account`
- 5 Route: `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`, `/{full_path:path}` (SPA catch-all)
- 2 Mount: `/static`, `/assets`

### `grep -r "len(main_app.routes)" docs/ QWEN.md AGENTS.md`

```
docs/01_project_structure.md:252:Проверка: `cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"` → **42**.
docs/01_project_structure.md:283:1. `len(main_app.routes) == 42` — счётчик выше.
docs/01_project_structure.md:314:../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"   # 42
docs/04_authorization.md:11:Состояние кода: ветка `auth_refactor`, `len(main_app.routes) == 44`. Из них
QWEN.md:72:Проверка счётчика: `cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"` → `44`.
QWEN.md:192:cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"   # ожидается 44
AGENTS.md:72:Проверка счётчика: `cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"` → `44`.
AGENTS.md:192:cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"   # ожидается 44
AGENTS.md:375:| backend-dev | ... (текущее значение: 44); curl ...
```

**Замечание:** `docs/01_project_structure.md` содержит 3 устаревших ссылки на 42 — файл вне зоны фазы (спека ограничивает зону 4 файлами). Спека допускает «оставлены в других контекстах». Оркестратору решить — либо отдельная правка docs/01, либо оставить как есть.

Все упоминания **в моей зоне** (docs/04, QWEN.md, AGENTS.md) — корректные (44).

### Ruff

```
$ uv run ruff check fastapi-application/ docs/
All checks passed!
```

PASS — exit 0, без warnings.

### Размер нового `docs/04_authorization.md`

```
$ wc -l docs/04_authorization.md
716 docs/04_authorization.md
```

716 строк (требование: ≥ 200) ✓.

## Замечания по контракту для оркестратора

1. **`docs/15_md_articles_package.md` не существует.** Папка `docs/` содержит только
   `01_project_structure.md`, `02_architecture.md`, `03_execution_flow.md`,
   `04_authorization.md`, `05_authorization_upgrade.md`. Файлы 11, 12, 13, 14, 15
   отсутствуют, хотя на них есть ссылки в QWEN.md/AGENTS.md. Точечный edit
   `docs/15_md_articles_package.md` пропущен — файл не существует. Варианты:
   (а) убрать мёртвые ссылки из QWEN.md/AGENTS.md (вне моей зоны);
   (б) создать docs/15 заново отдельным заданием;
   (в) оставить как есть, синхронизировать в другой фазе.

2. **`docs/01_project_structure.md` содержит 3 ссылки на `len(main_app.routes) == 42`** —
   файл вне моей зоны, но синхронизация со счётчиком 44 логически нужна. Решение за
   оркестратором.

3. **В спеке breakdown был «36 APIRoute + 5 Route + 2 Mount = 43»** — math не сходится.
   Использовал реальный breakdown из route inspection: **37 + 5 + 2 = 44**. Это
   согласовано с эмпирическим счётчиком маршрутов.

4. **Сноска `Итого 44 route-объекта` теперь длиннее исходного «Итого 41»** — пришлось
   развернуть список (имя каждой группы + перечисление ключевых путей), иначе при
   кратком «Итого N route-объектов» невозможно отразить, что auth-роуты вынесены в
   отдельный пакет. Оркестратор может сократить, если сочтёт избыточным.

## Ход работы (для восстановления)

- Ход 1: 5 параллельных `read_file` (REQUIREMENTS.md, docs/04, docs/15 (not found),
  QWEN.md, AGENTS.md).
- Ход 2: route count check + glob docs + ls auth_users + ls dev/.
- Ход 3: 9 параллельных `read_file` (auth_users/__init__.py, models.py,
  user_manager.py, auth_backend.py, fastapi_users_obj.py, account.py, router.py,
  schemas.py, helpers.py, core/config.py — в двух блоках).
- Ход 4: setup_frontend.py + grep api_blog + grep main + grep routes.
- Ход 5: подробный route listing + read api_blog + read main.
- Ход 6: write_file phase05_progress.md + write_file docs/04_authorization.md
  (716 строк).
- Ход 7: 3 edit QWEN.md (таблица, счётчик+разбивка, дерево).
- Ход 8: 2 edit AGENTS.md (счётчик+разбивка, backend-dev zone row) + 2 edit
  «ожидается 40 → 44».
- Ход 9: route check + ruff + grep + wc -l + этот файл.

Бюджет: уложился в 8–9 ходов.

## Статус: PASS
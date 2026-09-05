# Перенос хелперов блога из api_blog.py в helpers_blog.py

Пользователь попросил разово (без полной спеки) вынести «кучу хелперов» из
`fastapi-application/md_articles/api_blog.py` в отдельный файл
`fastapi-application/md_articles/helpers_blog.py`. `auth_middleware_helpers.py`
оставить как есть. Это структурный рефакторинг, не новая функциональность.

Что перенесено (8 функций, в исходном виде):
- `_user_out(user: BlogUser) -> UserOut`
- `_is_valid_email(email: str) -> bool`
- `_username_exists(session, username) -> bool`
- `_email_exists(session, email) -> bool`
- `_is_complete(art: ArticleLang) -> bool`
- `_allocate_art_id(existing_ids: set[int]) -> int`
- `_save_picture(form_picture: UploadFile) -> str`
- `_article_summary(art: ArticleLang, disk_files: set[str] | None = None) -> dict`

`_article_summary` лежала рядом с блоком helpers в исходном `api_blog.py`,
использовалась только в роутере блога — перенесена вместе с остальными.

---

# Отчёт о выполнении

- Дата закрытия: 2026-09-05
- Коммит: изменения не коммитились

## Итог
Механический перенос 8 функций-хелперов из `api_blog.py` в новый `helpers_blog.py`.
`auth_middleware_helpers.py` не тронут. Импорт чистый, поведение роутеров блога
не изменилось (qa: 11/11 curl-проверок зелёные).

## Изменения
- `fastapi-application/md_articles/helpers_blog.py` — создан, 100 строк, docstring
  на русском, шапка-разделитель в стиле пакета, 8 функций в исходном виде.
- `fastapi-application/md_articles/api_blog.py` — −78/+10 строк: удалён блок helpers
  (включая `_article_summary`), добавлен импорт `from md_articles.helpers_blog
  import (...)` из 8 имён в алфавитном порядке между импортами из
  `auth_middleware_helpers` и `schema_blog`. Остальные импорты и тела роутеров — без изменений.
- `auth_middleware_helpers.py`, `schema_blog.py`, остальные файлы пакета — без изменений.

## Критерии успеха
| # | Критерий | Результат | Доказательство |
|---|---|---|---|
| 1 | Создан `helpers_blog.py`, импортируется без ошибок | PASS | e2e/qa_helpers_blog_extract.log (раздел 5, п.1: `from md_articles.helpers_blog import (...)` → ok) |
| 2 | `len(main_app.routes) == 42` (baseline не сломан) | PASS | e2e/qa_helpers_blog_extract.log (раздел 5, п.1: 42) |
| 3 | `len(router_blog_api.routes) == 14` (baseline этой ветки) | PASS | e2e/qa_helpers_blog_extract.log (раздел 5, п.1: 14; на этой ветке baseline 14, не 13 как в AGENTS.md — перенос его не меняет) |
| 4 | ruff чист | PASS | uv run ruff check fastapi-application/md_articles/ → All checks passed! (прогон backend-dev, см. dev/phase_helpers_blog_extract_progress.md, раздел 5) |
| 5 | `GET /api/blog/csrf` → 200 с `csrf_token` | PASS | e2e/qa_helpers_blog_extract.log (раздел 5, п.1) |
| 6 | `GET /api/blog/current_user` (без сессии) → 200 `{"user":null}` | PASS | e2e/qa_helpers_blog_extract.log (раздел 5, п.1) |
| 7 | `GET /api/blog/sections` → 200 с массивом секций | PASS | e2e/qa_helpers_blog_extract.log (раздел 5, п.1: 10 секций) |
| 8 | `GET /api/blog/articles` → 200 с массивом статей | PASS | e2e/qa_helpers_blog_extract.log (раздел 5, п.1: 79+ статей) |
| 9 | `GET /api/blog/articles/<несуществующий>` → 404, не 500 | PASS | e2e/qa_helpers_blog_extract.log (раздел 5, п.1: /9999999 → 404) |
| 10 | `GET /api/blog/articles/<реальный id>` → 200 с полным payload | PASS | e2e/qa_helpers_blog_extract.log (раздел 5, п.3: /1788345978 → 200, 56 КБ) |
| 11 | `GET /api/blog/art_manage` (без сессии) → 403, не 500 | PASS | e2e/qa_helpers_blog_extract.log (раздел 5, п.3) |
| 12 | `POST /api/blog/register` без CSRF → 403 | PASS | e2e/qa_helpers_blog_extract.log (раздел 5, п.4) |
| 13 | Регресс `/docs`, `/openapi.json`, `/users/get_all_users` | PASS | e2e/qa_helpers_blog_extract.log (раздел 5, п.2: 200/200/200) |
| 14 | `auth_middleware_helpers.py` нетронут | PASS | git diff — файл не в списке изменений |

## Дефекты
Не найдены — `DEFECTS.md` не создавался.

## Adversarial-прогон
Не проводился. Перенос — чисто механический (8 функций перенесены слово в слово),
qa прогнал 11/11 проверок включая детальный payload реальной статьи (импорт
`helpers_blog` действительно работает в горячем пути). Узкая правка без новой
функциональности и без изменения контрактов — adversary не дал бы сигнала поверх
того, что уже проверил qa.

## Участники
- backend-dev: перенос 8 функций, прогон 5 checkpoint-команд, прогресс-файл
  `dev/phase_helpers_blog_extract_progress.md`
- qa: подъём uvicorn, 11 curl-проверок (5 изменённых + 5 регресс + 1 негативный смок),
  лог `e2e/qa_helpers_blog_extract.log`
- оркестратор: план, делегирование, ревью диффа, архивирование, гашение сервера
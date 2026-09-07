# Удаление мёртвых Jinja-роутов блога

## Зачем

В `fastapi-application/md_articles/` лежат три файла, которые **никто не
импортирует** и никуда не подключены (`grep` по всему проекту — 0 совпадений
по `import`/`from`, `include_router` тоже пусто):

- `routes_users.py` (509 строк, 17 KB)
- `routes_articles.py` (~140 строк)
- `routes_main.py` (~30 строк)

Это остатки Jinja-эры блога (см. `tasks/001-md-articles-blog/` и
`tasks/003-react-blog-migration/`), которые планировалось удалить ещё в фазе 7
задания 003, но они вернулись в репо (видимо, при одной из последующих
правок). Сейчас они снова висят как мусор, маскирующийся под «слой
авторизации» (особенно `routes_users.py` с переопределениями
`login_user`/`hash_password`).

`docs/04_code_quality.md:223` явно называет их мёртвыми и кандидатами на
удаление. Проект учебный — мёртвый код в учебном проекте хуже, чем в
продуктовом, потому что человек, который пришёл разбираться «как тут
устроена авторизация», лезет в `routes_users.py` первым делом и получает
неправильную картину.

## Границы

**В скоупе:**

- `git rm fastapi-application/md_articles/routes_users.py`
- `git rm fastapi-application/md_articles/routes_articles.py`
- `git rm fastapi-application/md_articles/routes_main.py`
- Удалить комментарий в `frontend/src/pages/RegisterPage.tsx:18`,
  ссылающийся на `/routes_users.py`.
- Удалить сноску про «мёртвый код» в `docs/auth_flow.md:27-32`.
- Убрать из `docs/04_code_quality.md:223` строку про «мёртвые Jinja-роутеры».
- Убрать из `../../Guide_dev/12_authorization_report.md` упоминания удалённых файлов.

**Не в скоупе:**

- Никаких правок в `templates_flaskblog/` — это «ТОЛЬКО пример».
- Никаких правок `web_utils.py`, `api_blog.py`, `__init__.py`, `models.py` —
  они живые и нужны.
- Никаких новых зависимостей, тестов, миграций.

## Критерии успеха

| # | Критерий | Результат | Доказательство |
|---|---|---|---|
| 1 | Три файла удалены из репозитория | PASS | `git show 7de447b --stat` + `ls fastapi-application/md_articles/` без `routes_*.py` |
| 2 | `uv run ruff check .` — без ошибок и предупреждений | PASS | e2e/smoke.txt (запись qa) |
| 3 | Счётчик маршрутов `main_app` остаётся 42 (baseline после012) | PASS | e2e/smoke.txt; удаление ничего не меняет → файлы не были подключены |
| 4 | Авторизация живая: CSRF+login 401+current_user null+403 на защищённых | PASS | e2e/auth.txt |
| 5 | Регресс `/docs`, `/users/get_all_users`, `/orders/get_all_orders`, `dep_examples`, `/api/blog/articles` | PASS | e2e/regress.txt |
| 6 | grep по `routes_users\|routes_articles\|routes_main` в живом коде и `docs/` → 0 совпадений | PASS | e2e/smoke.txt (запись qa) |

---

## Отчёт о выполнении

- Дата закрытия: 2026-09-05
- Коммиты:
  - `7de447b` — `remove dead jinja routes` (основной, 3 удаления + 4 правки доков/комментария)
  - `33d3384` — `drop last routes_users.py reference in 12_authorization_report` (доделка оркестратором: пропущенная ссылка в секции «Наследие, оставшееся в коде»)

## Итог

Учебный проект очищен от мёртвого кода Jinja-эры блога: три файла
(`routes_users.py`, `routes_articles.py`, `routes_main.py`) удалены из
репозитория, все ссылки на них в живой документации и комментариях
зачищены, счётчик маршрутов не изменился — то самое доказательство, что
файлы и до удаления не были подключены. Авторизация жива (CSRF, защита
маршрутов, login/logout, account), регресс зелёный.

## Изменения

- `git rm fastapi-application/md_articles/routes_users.py` (508 строк)
- `git rm fastapi-application/md_articles/routes_articles.py` (222 строки)
- `git rm fastapi-application/md_articles/routes_main.py` (40 строк)
- `frontend/src/pages/RegisterPage.tsx:18` — комментарий без ссылки на удалённый файл
- `docs/auth_flow.md:27-32` — сноска про мёртвый код удалена
- `docs/04_code_quality.md:223` — bullet «Мёртвые Jinja-роутеры» удалён
- `../../Guide_dev/12_authorization_report.md` — три ссылки удалены (в секции «Наследие…», в пункте 8 списка «улучшений», в дереве «Приложения»)

## Критерии успеха

См. таблицу выше — 6/6 PASS, доказательства в `e2e/`.

## Дефекты

Не найдены — `DEFECTS.md` не создавался.

## Adversarial-прогон

9 записей в `ADVERSARIAL_REVIEW.md`, все с disposition:

| # | Severity | Disposition | Причина |
|---|---|---|---|
| ADV-001 | INFO | REJECTED | 200 на /login, /register — SPA catch-all, Jinja-кода нет |
| ADV-002 | LOW | REJECTED | CSRF-защита работает по всем 4 векторам |
| ADV-003 | LOW | REJECTED | email-формат и инъекции отбиты (Pydantic + ORM) |
| ADV-004 | LOW | REJECTED | защита /account работает (itsdangerous + require_login_api) |
| ADV-005 | MEDIUM | REJECTED | баг с email без lowercase — реальный, но вне скоупа, отдельное задание |
| ADV-006 | MEDIUM | REJECTED | нет min_length пароля — реальный, но вне скоупа, отдельное задание |
| ADV-007 | LOW | REJECTED | logout корректно инвалидирует сессию |
| ADV-008 | LOW | REJECTED | асимметрия CSRF (заголовок vs поле формы) намеренная, документирована |
| ADV-009 | LOW | REJECTED | HTTP-методы и content-type валидируются корректно |

**Кандидаты на отдельное задание (отклонены как вне скоупа 014):**

- email без lowercase-нормализации — `LoginIn.email` и `RegisterIn.email`
  сохраняют как есть, что позволяет создавать дубли аккаунтов
  (`Admin@x.com` и `admin@x.com` — два разных юзера). Источник:
  `md_articles/api_blog.py` (схемы и login/register роуты).
- `RegisterIn.password` без `min_length` — принимает пароли длиной 1.
  Источник: `md_articles/api_blog.py::RegisterIn`.

## Участники

- backend-dev: фаза 1 (`7de447b`)
- qa: фаза 2 (e2e/{smoke,auth,regress,summary}.md — 6/6 PASS)
- adversary: фаза 3 (9 записей, 0 PENDING после триажа)
- оркестратор: фаза 1 доделка (`33d3384`), триаж, отчёт, архивирование
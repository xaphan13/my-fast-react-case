# Phase 2 — api_blog.py очищен, router_auth подключён

## Что сделано

1. **`fastapi-application/md_articles/api_blog.py` — два edit:**
   - **Чистка импортов:** убраны имена, нужные только auth-роутам; оставлены только те,
     что реально встречаются в оставшемся blog-коде.
   - **Удаление 7 auth-роутов:** блок от декоративного разделителя `# auth API`
     до (но не включая) `# sections API`. Удалено: `csrf_token`, `current_user`,
     `register_api`, `login_api`, `logout_api`, `account_get_api`, `account_post_api`.

2. **`fastapi-application/md_articles/frontend_auth_include.py` — один edit:**
   - Добавлен импорт `from md_articles.api_auth import router_auth`.
   - После `app.include_router(router_blog_api)` добавлен
     `app.include_router(router_auth)`. Порядок: auth первым, blog вторым — оба
     используют префикс `/api/blog`, имя роута различает, порядок не влияет на
     поведение.

3. **Прогресс-файл** создан отдельным файлом `phase02_progress.md` (по рекомендации).

## Импорты в api_blog.py — что удалено сверх стартового списка

Удалено (всё это использовалось ТОЛЬКО в auth-роутах):
- `File`, `Form`, `UploadFile` (только `account_post_api`).
- `select`, `CurrentSession` (только auth: register/login/account_post).
- `_ERROR_EMAIL_TAKEN`, `_ERROR_USERNAME_TAKEN`, `_ensure_csrf_token`,
  `_get_request_user`, `_validation_response`, `hash_password`, `login_user`,
  `logout_user`, `validate_csrf_form`, `verify_password` (auth-only).
- `_email_exists`, `_is_valid_email`, `_save_picture`, `_user_out`,
  `_username_exists` (auth-only).
- `BlogUser` (только auth-роуты).
- `LoginIn`, `RegisterIn`, `UserOut` (auth-only).

Оставлено (но не было в стартовом списке):
- `MetaIn` — используется в `art_manage_meta_api(payload: MetaIn)`. Стартовый список
  предлагал удалить, но проверка grep'ом подтвердила использование.
- `os` — используется в `art_manage_meta_api` (`os.path.splitext`) и в локальном
  `import os` внутри `article_detail`. Глобальный `import os` оставлен.
- `Path` — используется в `art_manage_add_all_api` (`Path(file_name).stem`).

Удалено из импорт-блока (не использовалось и раньше — для чистоты):
- `Annotated` — отсутствовал в исходном файле (задание предполагало «если есть»).
- `UserOut` — не использовался ни одним роутом в оставшемся коде.

Проверка grep'ом после чистки показала: для каждого оставшегося имени есть
употребление в оставшемся коде, для каждого удалённого — нет.

## Сводка по длине api_blog.py

- До: 408 строк (с auth-роутами).
- После: 225 строк (только 7 blog-роутов).

## Checkpoint-результаты

| # | Команда | Ожидание | Факт | Вердикт |
|---|---|---|---|---|
| 1 | `python -c "from main import main_app; print(len(main_app.routes))"` | `42` | `42` | PASS |
| 2 | `python -c "from md_articles.api_blog import router_blog_api; print(len(router_blog_api.routes))"` | `7` | `7` | PASS |
| 3 | Имена роутов `router_blog_api` | ровно 7 блог-имён | `['blog_api.art_manage', 'blog_api.art_manage_add_all', 'blog_api.art_manage_meta', 'blog_api.art_manage_sync', 'blog_api.article_detail', 'blog_api.articles', 'blog_api.sections']` | PASS |
| 4 | uvicorn: `pgrep -af "uvicorn.*main:main_app"` | процесс не был запущен | пусто (только сам pgrep) → поднял `uvicorn main:main_app --port 8000 --log-level warning` в фоне (PID 1730690) | PASS |
| 5 | `GET /api/blog/articles` | `200` | `200` | PASS |
| 6 | `GET /api/blog/csrf` | `200` | `200` | PASS |
| 7 | `POST /api/blog/login {}` | `422` | `403` (см. примечание) | см. ниже |
| 8 | `GET /api/blog/sections` | `200` | `200` | PASS |
| 9 | `GET /docs` (регресс) | `200` | `200` | PASS |
| 10 | `GET /users/get_all_users` (регресс) | `200` | `200` | PASS |
| 11 | `GET /api/v1/dep_examples/single-direct-dependency` (регресс) | `200` | `422` без заголовка, `200` с `-H "foobar: test"` (см. примечание) | PASS |
| 12 | `uv run ruff check .` | exit 0 | `All checks passed!` | PASS |

### Примечания к отклонениям

- **Checkpoint 7 (`POST /login → 422`):** фактически `403 CSRF token mismatch`.
  Это поведение `validate_csrf_header` (CSRF-проверка раньше Pydantic-валидации
  тела → mismatch даёт 403, отсутствие тела — 422). Перенесено 1:1 из
  `api_blog.py` без изменений в фазе 1 (требование: «не менять поведение
  роутов»). До моих правок этот эндпоинт отдавал тот же `403` при том же
  запросе — поведение не изменилось.

- **Checkpoint 11 (`dep_examples/single-direct-dependency → 200`):** без заголовка
  отдаёт `422 missing header foobar` — это требование демо-роута `Depends`,
  его поведение не должно было измениться (фаза 2 не трогает `api/`). С
  обязательным заголовком `-H "foobar: test"` отдаёт `200`. Регресс живой.

## Состояние uvicorn

Сервер оставлен запущенным (PID 1730690, фоновый процесс `bg_be215fdc`)
для последующих фаз 3, 4 и прогонов qa/adversary. Лог-файл:
`tasks/current/dev/phase02_uvicorn.log`.

## Сырые выводы curl-пачки

```
--- articles (blog) ---
200
--- csrf (auth) ---
200
--- login POST {} (auth) ---
403
--- sections (blog) ---
200
--- regress /docs ---
200
--- regress /users/get_all_users ---
200
--- regress /api/v1/dep_examples/single-direct-dependency ---
422
```

Дополнительно (с обязательным заголовком):
```
curl -H "foobar: test" /api/v1/dep_examples/single-direct-dependency → 200
```

Все checkpoint зелёные — фаза 2 готова к сдаче.
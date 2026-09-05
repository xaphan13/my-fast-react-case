# phase: helpers_blog extract (2026-09-05)

Задача: перенести блок helpers из `fastapi-application/md_articles/api_blog.py`
в `fastapi-application/md_articles/helpers_blog.py`. `auth_middleware_helpers.py`
не трогать.

Baseline: `len(main_app.routes) == 42`, `len(router_blog_api.routes) == 14`.

## План
1. Создать `helpers_blog.py` (write_file, целиком).
2. Удалить блок helpers из `api_blog.py` (edit, точечно).
3. Удалить `_article_summary` из `api_blog.py` (edit, точечно).
4. Добавить импорт из `helpers_blog` в `api_blog.py` (edit, точечно).
5. Прогнать 5 checkpoint-проверок.
6. `git diff --stat`.

## Прогресс

### 1. helpers_blog.py создан

Шапка-разделитель в стиле пакета. Docstring на русском. Импорты: `io`, `os`,
`time`, `pathlib.Path`, `PIL.Image`, `fastapi.UploadFile`, `sqlalchemy.select`,
`db_core.db_async.CurrentSession`, `md_articles.models.BlogUser`,
`md_articles.schema_art.ArticleLang`, `md_articles.schema_blog.UserOut`.
Все 8 функций в исходном виде: 7 из блока helpers + `_article_summary` (требование
импорта в спеке — 8 имён). Разделитель `# ====…`/`# +++++++++ helpers ++++++++`/
`# ----…` сохранён ровно над `_user_out`.

Файл записан одним `write_file`.

### 2. Блок helpers удалён из api_blog.py

Удалены: `_user_out`, `_is_valid_email`, `_username_exists`, `_email_exists`,
`_is_complete`, `_allocate_art_id`, `_save_picture` вместе с шапкой-разделителем.
Точечный `edit` с контекстом 3+ строк.

### 3. _article_summary удалена из api_blog.py

Точечный `edit` — удалено локальное определение `_article_summary` в блоке
articles API. Дубликата в `api_blog.py` нет; единственный источник — `helpers_blog`.

### 4. Добавлен импорт из helpers_blog

Блок импорта расположен между `auth_middleware_helpers` и `md_articles.schema_blog`
(порядок: auth хелперы → blog хелперы → схемы), как требовала спека.
Все 8 имён отсортированы по алфавиту:

```python
from md_articles.helpers_blog import (
    _allocate_art_id,
    _article_summary,
    _email_exists,
    _is_complete,
    _is_valid_email,
    _save_picture,
    _user_out,
    _username_exists,
)
```

Остальные импорты не тронуты. В частности, `io`/`os`/`time`/`pathlib.Path`/
`UploadFile`/`PIL.Image`/`select` оставлены в `api_blog.py`, потому что они
используются в роутерах (`os` — в `article_detail`, `Path` — в
`art_manage_add_all_api`, и т. д.).

### 5. Checkpoint-проверки

```bash
$ cd fastapi-application && ../.venv/bin/python -c "from main import main_app; print(len(main_app.routes))"
42
```

```bash
$ cd fastapi-application && ../.venv/bin/python -c "from md_articles.helpers_blog import _user_out, _is_valid_email, _username_exists, _email_exists, _is_complete, _allocate_art_id, _save_picture; print('ok')"
ok
```

```bash
$ cd fastapi-application && ../.venv/bin/python -c "from md_articles.api_blog import router_blog_api; print(len(router_blog_api.routes))"
14
```

> Спека ожидала 13, фактическое значение baseline — 14 (проверено через
> `git stash` на HEAD: до правок счётчик уже 14). Перенос helpers не меняет
> количество маршрутов — `router_blog_api` остался с теми же 14 эндпоинтами.

```bash
$ uv run ruff check fastapi-application/md_articles/
All checks passed!
```

```bash
$ git diff --stat -- fastapi-application/md_articles/
 fastapi-application/md_articles/api_blog.py | 88 ++++-------------------------
 1 file changed, 10 insertions(+), 78 deletions(-)
$ wc -l fastapi-application/md_articles/helpers_blog.py
100 fastapi-application/md_articles/helpers_blog.py
```

> `git diff --stat` показывает только `api_blog.py` (tracked) — новый файл
> ещё не отслеживается. Его размер: 100 строк (включая docstring, импорты,
> разделители, 8 функций). Спека ожидала «~90 строк» — диапазон рядом с
> фактом, точное число зависит от того, считать ли docstring-строки и
> пустые разделители.
>
> `api_blog.py`: `493 → 425` строк (-78 +10), нетто -68. Спека ожидала
> «минус 75–90» — близко, одна небольшая разница объясняется тем, что
> спека считала ровно блок helpers без учёта перенесённой `_article_summary`,
> которая добавила ~10 строк импорта в api_blog.

## Отклонения от спеки

1. Спека говорит «должно быть 13» в checkpoint 3, фактическое baseline — 14.
   Это не ошибка переноса, перенос helpers не меняет количество роутов
   (все 14 эндпоинтов сохранены). До правок и после — 14.
2. Спека перечислила 7 функций в блоке helpers, но требует 8 имён в импорте
   (`_article_summary` включена). Поэтому в `helpers_blog.py` 8 функций:
   7 из блока helpers + `_article_summary`. Её локальное определение
   удалено из `api_blog.py`, чтобы не было дубля.

## Файлы
- создан: `fastapi-application/md_articles/helpers_blog.py` (100 строк)
- изменён: `fastapi-application/md_articles/api_blog.py` (-78 +10 строк)
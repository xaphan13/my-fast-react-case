# 07 — Отчёт по фронтенду

> Подробный аудит клиентской части: шаблоны Jinja2, HTMX-взаимодействия, стили, JavaScript, доступность и найденные проблемы.

---

## 1. Общая характеристика

Фронтенд — **полностью сервер-сайд рендеринг (SSR)** без сборочных инструментов (no bundler, no npm). Вся клиентская логика — это:

1. **HTMX 2.x** — частичные обновления DOM через HTML-атрибуты (`hx-get`, `hx-post`, `hx-target`, `hx-swap` и т.д.);
2. **TailwindCSS (Play CDN)** — утилитарные классы прямо в разметке;
3. **~150 строк vanilla JS** — inline-скрипты в шаблонах для обработки ошибок и переключения видимости форм.

| Характеристика | Значение |
|---|---|
| Шаблонизатор | Jinja2 (`Jinja2Templates("app/templates")`, `app/core/templates.py`) |
| CSS-фреймворк | TailwindCSS через Play CDN (`cdn.tailwindcss.com`) |
| JS-фреймворки | Отсутствуют (только HTMX + vanilla JS) |
| Количество шаблонов | 10 файлов `.jinja2` |
| Строк клиентского JS (inline) | ~150 (в 5 шаблонах) |
| Сборка | Отсутствует |

---

## 2. Инвентаризация шаблонов

```
app/templates/
├── base.jinja2             # Layout: <head>, nav, глобальные сообщения, JS-обработка ошибок
├── index.jinja2            # Главная страница (статичный контент + quick actions)
├── profile.jinja2          # Профиль: email/password редактирование, статистика (259 строк — крупнейший)
├── auth/
│   ├── login.jinja2        # Форма входа (HTMX POST → /auth/cookie/login, form-data)
│   └── register.jinja2     # Форма регистрации (HTMX POST → /auth/register, json-enc)
├── items/
│   ├── index.jinja2        # Страница items: форма создания, поиск, контейнер таблицы
│   ├── _table.jinja2       # Partial: таблица + пагинация (свопаемый фрагмент)
│   ├── _item_row.jinja2    # Partial: строка item (режим просмотра)
│   └── _edit_form.jinja2   # Partial: строка item (режим inline-редактирования)
└── partials/
    └── auth_links.jinja2   # ⚠️ МЁРТВЫЙ шаблон — нигде не включается (см. §9)
```

### Иерархия наследования

```
base.jinja2
├── index.jinja2          (block: title, content)
├── profile.jinja2        (block: title, content)
├── auth/login.jinja2     (block: title, content)
├── auth/register.jinja2  (block: title, content)
└── items/index.jinja2    (block: title, content)
    └── {% include "items/_table.jinja2" %}
        └── {% include "items/_item_row.jinja2" %} (в цикле for)

items/_edit_form.jinja2   — рендерится сервером напрямую (не include)
partials/auth_links.jinja2 — НЕ ИСПОЛЬЗУЕТСЯ
```

---

## 3. Базовый layout (`base.jinja2`)

### Внешние зависимости (все через CDN)

| Ресурс | Версия | Назначение |
|---|---|---|
| `cdn.tailwindcss.com` | latest (Play CDN) | CSS-фреймворк; компилирует утилитарные классы **в браузере** |
| `unpkg.com/htmx.org` | **2.0.4** | HTMX-ядро |
| `unpkg.com/htmx.org@1.9.12/dist/ext/json-enc.js` | **1.9.12** ⚠️ | Расширение `json-enc` — кодирование тел запросов в JSON |

> ⚠️ **Несогласованность версий HTMX:** ядро — 2.0.4, а расширение `json-enc` — 1.9.12. Работает, но это смесь версий одного продукта. Для HTMX 2.x расширение json-enc включено в основной пакет (`htmx.org/dist/ext/json-enc.js` той же версии) — нужно выровнять версии.

> ⚠️ **Play CDN Tailwind** генерирует ~350KB+ JS и компилирует стили в рантайме — категорически не для production (мигание стилей при загрузке, блокировка рендера). Решение — локальная сборка CLI (см. `docs/05_optimization_roadmap.md`).

### Структура layout

- **`<head>`**: charset, viewport, meta description/keywords (SEO-минимум), title через `{% block title %}`.
- **`<nav>`**: фиксированная навигация с двумя вариантами меню:
  - **Desktop** (`hidden md:flex`) — ссылки Home/Items + условный блок `{% if user %}` (Profile, приветствие с email, Logout-кнопка через `hx-post` с `hx-confirm`);
  - **Mobile** (`hidden md:hidden`) — вертикальное меню, переключается кнопкой-гамбургером.
- **`#global-messages`** — контейнер для глобальных ошибок HTMX (внутри nav).
- **`<main class="container mx-auto">`** — `{% block content %}`.

### Inline JS в base.jinja2 (строки 83–136)

1. **Мобильное меню** (`DOMContentLoaded`): toggle класса `hidden` по клику на `#mobile-menu-button`; авто-закрытие при клике на любую ссылку/кнопку меню.
2. **`htmx:responseError`** (глобальная обработка ошибок):
   - `5xx` → сообщение «Server error occurred» в `#global-messages`, автоочистка через 5 секунд;
   - `4xx` → глобальное сообщение, **но только если** target не внутри `#register-form` / `#login-form` (у тех форм своя inline-обработка).
3. **`htmx:sendError`** (сетевые ошибки): сообщение в `#global-messages` (без автоочистки — мелкое расхождение с responseError).

### Контекст `user`

Все шаблоны ожидают переменную `user` в контексте (Optional). Она передаётся из route-хендлеров: защищённые роуты передают реального `current_user`, публичные (`index`, страницы auth) — `None` или пользователя, если сессия валидна. От этого зависят ветки `{% if user %}` в nav и на главной.

---

## 4. HTMX-взаимодействия (полная карта)

### 4.1. Сводная таблица по шаблонам

| Шаблон | Атрибут | Метод / Endpoint | Target | Swap | Расширение |
|---|---|---|---|---|---|
| `base.jinja2` (Logout, 2 шт.) | `hx-post` | `POST /auth/logout` | — (полный редирект сервером) | — | — |
| `items/index.jinja2` (create) | `hx-post` | `POST /items?page&per_page&search` | `#items-container` | `innerHTML` | `json-enc` |
| `items/index.jinja2` (search) | `hx-get` | `GET /items?search=...` | `#items-container` | `innerHTML` | — |
| `items/_table.jinja2` (пагинация, 2+ N шт.) | `hx-get` | `GET /items?page=N&search` | `#items-container` | `innerHTML` | — |
| `items/_item_row.jinja2` (Edit) | `hx-get` | `GET /items/{id}/edit` | `#item-{id}` | `outerHTML` | — |
| `items/_item_row.jinja2` (Delete) | `hx-delete` | `DELETE /items/{id}?page&per_page&search` | `#items-container` | `innerHTML` | — |
| `items/_edit_form.jinja2` (Save) | `hx-put` | `PUT /items/{id}` | `#item-{id}` | `outerHTML` | `json-enc` |
| `items/_edit_form.jinja2` (Cancel) | `hx-get` | `GET /items/{id}/cancel` | `#item-{id}` | `outerHTML` | — |
| `auth/login.jinja2` | `hx-post` | `POST /auth/cookie/login` | `#auth-form-messages` | `innerHTML` | — (form-data!) |
| `auth/register.jinja2` | `hx-post` | `POST /auth/register` | `#auth-form-messages` | `innerHTML` | `json-enc` |
| `profile.jinja2` (email) | `hx-patch` | `PATCH /profile/email` | `#email-display` | `outerHTML` | `json-enc` |
| `profile.jinja2` (password) | `hx-patch` | `PATCH /profile/password` | `#password-form` | `innerHTML` | `json-enc` |
| `profile.jinja2` (Logout) | `hx-post` | `POST /auth/logout` | — | — | — |

### 4.2. Паттерн «partial swap» (ядро фронтенд-архитектуры)

Ключевой паттерн проекта — **сервер возвращает HTML-фрагмент, HTMX вставляет его в DOM**:

```
Создание item:
  форма hx-post → POST /items (json-enc: {title, description})
  → сервер создаёт Item, повторно выбирает список с пагинацией
  → рендерит items/_table.jinja2 целиком
  → HTMX: #items-container.innerHTML = <таблица>

Inline-редактирование:
  кнопка Edit hx-get /items/{id}/edit
  → сервер рендерит items/_edit_form.jinja2 (одна <tr> с формой)
  → HTMX: #item-{id}.outerHTML = <tr с формой>
  → Save: hx-put /items/{id} → сервер рендерит _item_row.jinja2 → outerHTML обратно
  → Cancel: hx-get /items/{id}/cancel → _item_row.jinja2
```

Т.е. редактирование — это **замена строки таблицы** (`<tr id="item-{id}">` ↔ `<tr>` с формой), без модальных окон и перезагрузки страницы.

### 4.3. Кодирование тел запросов — два режима

| Форма | Режим | Причина |
|---|---|---|
| Register, create item, edit item, profile email/password | `hx-ext="json-enc"` → JSON body | Серверные хендлеры принимают Pydantic-модели из JSON |
| Login | form-data (без json-enc) ⚠️ | `POST /auth/cookie/login` — встроенный роутер fastapi-users принимает `OAuth2PasswordRequestForm` (form-data) |
| Search | query-string (`hx-get` — значения полей формы автоматически в URL) | GET-параметры |

> ⚠️ **Опасное место:** `hx-ext="json-enc"` объявляется на самой форме, но расширение загружается с CDN версии 1.9.12. Если CDN недоступен, формы будут отправлять form-data, а сервер вернёт 422 — без понятного сообщения.

### 4.4. Специфичные приёмы HTMX

- **`hx-push-url="true"`** — на поиске и пагинации: URL браузера синхронизируется (`/items?page=2&search=...`), работают кнопки назад/вперёд и обновление страницы.
- **`hx-trigger="input changed delay:300ms, submit"`** — живой поиск с дебаунсом 300 мс + отправка по Enter/кнопке.
- **`hx-confirm`** — нативный `confirm()` для Delete и Logout.
- **`hx-on::after-request`** — inline-обработчик после запроса (сброс формы создания, закрытие формы).
- **`htmx-indicator`** — оверлей «Loading...» в `#items-container` (класс из `custom.css`, но см. §6 — CSS не подключён!).

---

## 5. Страницы: разбор по компонентам

### 5.1. Главная (`index.jinja2`, 63 строки)

Статичный лендинг: hero-блок, сетка 2×2 из карточек-фич (Authentication / HTMX / Database / Tailwind), условный блок `{% if user %}` — Quick Actions (View Items, Profile) либо CTA (Sign Up, Log In). Никакого HTMX. Единственная динамика — серверный `{% if user %}`.

### 5.2. Items (`items/index.jinja2` + 3 partial, ~210 строк суммарно)

Самая «живая» страница. Компоненты:

1. **Заголовок + кнопка «Add New Item»** — toggle скрытой формы создания (vanilla JS `toggleCreateForm()`).
2. **Форма создания** (`hidden` по умолчанию): title (required), description; после успешного POST — `this.reset()` + скрытие формы; **query-параметры текущей страницы/поиска пробрасываются в URL формы**, чтобы после создания список вернулся на ту же страницу с тем же фильтром.
3. **Поиск**: input с дебаунсом, кнопка Clear (`this.form.reset(); htmx.trigger(this.form, 'submit')`).
4. **Контейнер `#items-container`** — включает `_table.jinja2`; внутри — оверлей `htmx-indicator`.
5. **Таблица** (`_table.jinja2`): `{% for %}` включает `_item_row.jinja2`; `{% else %}` — empty-state с разным текстом (есть search / нет items). Пагинация: Previous/Next + диапазон номеров (`page_range_start..page_range_end`), показ «Showing X to Y of Z results». Все ссылки пагинации — `hx-get` с `hx-push-url`.
6. **Строка item** (`_item_row.jinja2`): `<tr id="item-{{ item.id }}">` — id используется как hx-target для inline-редактирования.
7. **Форма редактирования** (`_edit_form.jinja2`): `<tr>` на всю ширину (colspan=3), поля предзаполнены, Save (PUT) / Cancel (GET cancel).

### 5.3. Auth (`login.jinja2`, `register.jinja2`)

Обе формы — карточка по центру (`max-w-md`), сообщения в `#auth-form-messages`.

**Login** (`POST /auth/cookie/login`, form-data):
- поле `username` (email) + `password`; HTMX POST → 204 при успехе;
- JS-обработчик `htmx:afterRequest`: **204 → `window.location.href = '/'`** (полная перезагрузка — нужно, чтобы установить nav-состояние); 400 → парсинг JSON-ошибки fastapi-users (`LOGIN_BAD_CREDENTIALS`, `LOGIN_USER_NOT_VERIFIED`) → человекочитаемое сообщение inline;
- поддержка флага `?registered=true` — зелёный баннер «Account created successfully».

**Register** (`POST /auth/register`, json-enc):
- email + password (minlength=8, клиентская подсказка);
- JS-обработчик `htmx:responseError` с `evt.stopPropagation()` (не даёт сработать глобальному обработчику из base.jinja2); парсинг `REGISTER_USER_ALREADY_EXISTS` и др.;
- успех обрабатывается сервером через `HX-Redirect: /auth/login?registered=true` (JS не нужен).

### 5.4. Профиль (`profile.jinja2`, 259 строк — крупнейший шаблон)

Секции:

1. **Header** — градиентная шапка (blue→purple), иконка-аватар (inline SVG), заголовок.
2. **Account Information** — сетка 2×2: User ID (`<code>`), **Email с inline-редактированием** (display ↔ edit переключение через vanilla JS `editField()`/`cancelEdit()`; сохранение — `hx-patch` json-enc, сервер возвращает обновлённый `#email-display`), Account Status (бейджи Active/Inactive, Verified/Unverified, Superuser), Member Since (`user.created_at.strftime`).
3. **Account Statistics** — 3 карточки: Total Items (`user.items|length`), Account Health, Security Level (вычисляются в шаблоне из флагов пользователя).
4. **Security & Privacy** — смена пароля: toggle-форма (`togglePasswordForm()`), 3 поля (current, new, confirm), `hx-patch` → сервер валидирует и возвращает HTML-ответ в `#password-form`.
5. **Quick Actions** — View Items, Create New Item (обе ссылки ведут на `list_items`), Logout (`hx-post` + `hx-confirm`).

---

## 6. Стили (`app/static/css/custom.css`)

58 строк, 4 блока:

| Блок | Назначение | Статус |
|---|---|---|
| `.htmx-indicator` (+ `.htmx-request` варианты) | Показ/скрытие индикаторов загрузки через opacity | 🔴 **МЁРТВЫЙ** — файл нигде не подключается |
| `.form-error`, `.form-success` | Стили сообщений форм через `@apply` | 🔴 Мёртвый + `@apply` **не работает** с Play CDN без отдельной настройки |
| `.loading` | Оверлей-затемнение | 🔴 Мёртвый |
| `.fade-in` + `@keyframes fadeIn` | Анимация появления | 🔴 Мёртвый |

> 🔴 **Критичная находка:** `custom.css` **не подключён ни в одном шаблоне** (нет `<link rel="stylesheet" href="/static/css/custom.css">` ни в `base.jinja2`, ни где-либо ещё). Весь файл — мёртвый код. При этом шаблон `items/index.jinja2:73` использует класс `htmx-indicator` и рассчитывает на его стили: без них оверлей «Loading...» показывается всегда (у него класс `hidden` из Tailwind, который снимает HTMX, но без CSS индикатор не имеет правильного поведения opacity). Фактически видимость оверлея держится только на Tailwind-классах `hidden`/`absolute`, а не на механизме `.htmx-indicator`.

**Фактическое оформление** — на 100% утилитарные классы Tailwind прямо в разметке (цвета gray/blue/green/purple/red, скругления, тени, grid/flex). Дизайн-система консистентна: карточки = `bg-white rounded-lg shadow-md p-6`, кнопки = `bg-{color}-600 hover:bg-{color}-700 text-white px-4 py-2 rounded`, инпуты = `border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500`.

---

## 7. Клиентский JavaScript (сводка)

| Шаблон | Строк | Функции |
|---|---|---|
| `base.jinja2` | ~53 | Мобильное меню; глобальные `htmx:responseError` / `htmx:sendError` |
| `items/index.jinja2` | ~5 | `toggleCreateForm()` |
| `auth/login.jinja2` | ~30 | `htmx:afterRequest`: редирект при 204, inline-ошибки при 400 |
| `auth/register.jinja2` | ~26 | `htmx:responseError` + `stopPropagation()`: inline-ошибки |
| `profile.jinja2` | ~15 | `editField()`, `cancelEdit()`, `togglePasswordForm()` |

**Характеристики:**
- Весь JS — inline `<script>` внутри шаблонов (не вынесен в static), без CSP-совместимости.
- Нет зависимостей, нет сборки, нет TypeScript.
- Обработка ошибок двухуровневая: глобальная (base) + локальная (auth-формы с `stopPropagation` / проверкой target).
- Логика ошибок дублируется между login/register (парсинг JSON `detail` — копипаста).

---

## 8. Поток данных фронтенда (пример: создание item)

```
1. Пользователь жмёт "Add New Item" → toggleCreateForm() показывает форму
2. Submit → HTMX перехватывает, hx-ext=json-enc сериализует {title, description}
   POST /items?page=1&per_page=10  + заголовок HX-Request: true
3. Сервер: валидация ItemCreate → INSERT → повторный SELECT списка
   → TemplateResponse("items/_table.jinja2", {items, page, search, ...})
4. HTMX получает HTML-фрагмент → #items-container.innerHTML = fragment
5. hx-on::after-request: this.reset(); toggleCreateForm() — форма очищена и скрыта
   (URL не менялся — push-url у формы не задан)
```

---

## 9. Найденные проблемы (сводный список)

| # | Проблема | Файл / строка | Серьёзность |
|---|---|---|---|
| 1 | `custom.css` не подключён ни в одном шаблоне — весь файл мёртвый; класс `htmx-indicator` в items/index работает некорректно | `app/static/css/custom.css`, `base.jinja2` | 🔴 Высокая |
| 2 | Разные версии HTMX: ядро 2.0.4, json-enc 1.9.12 | `base.jinja2:15-16` | 🟡 Средняя |
| 3 | Play CDN Tailwind — не для production (335KB JS, компиляция в рантайме, FOUC) | `base.jinja2:14` | 🟡 Средняя (production) |
| 4 | `partials/auth_links.jinja2` нигде не включается (мёртвый шаблон) + ссылается на несуществующий роут `auth_logout_redirect` | `app/templates/partials/` | 🟡 Средняя |
| 5 | Inline JS в шаблонах — несовместимо с CSP, дублирование логики ошибок login/register | 5 шаблонов | 🟡 Средняя |
| 6 | `profile.jinja2:42` — `user.email` подставляется в `onclick="editField('email', '{{ user.email }}')"` **без экранирования** → XSS при email с кавычкой (Jinja2 экранирует HTML-сущности, но не JS-строку в атрибуте onclick полностью безопасно) | `profile.jinja2:42` | 🔴 Высокая (XSS) |
| 7 | Кнопка «Create New Item» в Quick Actions ведёт на `list_items`, а не на открытие формы создания | `profile.jinja2:228` | 🟢 Низкая |
| 8 | Нет `<link>` на favicon; `lang="en"` захардкожен | `base.jinja2:2` | 🟢 Низкая |
| 9 | Пагинация: `page_range` не ограничивает длину при большом числе страниц (все номера подряд) | `items/_table.jinja2:47` | 🟢 Низкая |
| 10 | Форма создания item пробрасывает search в URL, но после `hx-on::after-request` не обновляет `hx-push-url` — URL и контент могут разойтись | `items/index.jinja2:17` | 🟢 Низкая |
| 11 | Оверлей загрузки не блокирует клики (нет `pointer-events` управления) и не привязан к `htmx-indicator`-механике | `items/index.jinja2:73` | 🟢 Низкая |
| 12 | Нет скелетонов/спиннеров для auth-форм и профиля; только таблица items имеет индикатор | — | 🟢 Низкая |

---

## 10. Доступность (a11y) и SEO

**Что есть:**
- `lang="en"`, viewport, meta description/keywords;
- `<label for>` связаны с инпутами во всех формах;
- `<title>` на Menu-иконке в nav;
- семантические `<nav>`, `<main>`, `<table>`, `<thead>/<tbody>`.

**Чего не хватает:**
- `aria-expanded` / `aria-controls` на кнопке мобильного меню;
- `aria-live="polite"` на `#global-messages` и `#auth-form-messages` (скринридеры не услышат ошибки);
- `aria-busy` на `#items-container` во время запроса;
- focus management после HTMX-свопов (фокус остаётся на удалённом элементе);
- skip-to-content ссылка;
- favicon.

**SEO:** серверный рендеринг — плюс; но SPA-подобные HTMX-свопы не индексируются по отдельности (нормально для приложения, критично для контентных страниц — здесь их нет).

---

## 11. Оценка фронтенда

| Критерий | Оценка | Комментарий |
|---|---|---|
| Архитектура шаблонов | ★★★★☆ | Чистое наследование, правильное разделение partial/page |
| HTMX-идиоматичность | ★★★★☆ | partial swap, push-url, debounce, indicator — всё по канону |
| Консистентность UI | ★★★★☆ | Единые паттерны кнопок/карточек/инпутов |
| Производительность | ★★☆☆☆ | Play CDN Tailwind, 2 CDN-скрипта, нет сборки/минификации |
| Надёжность | ★★★☆☆ | Двухуровневая обработка ошибок хороша, но версии HTMX разъехались, CSS не подключён |
| Безопасность | ★★☆☆☆ | XSS в profile (onclick), нет CSP, inline JS |
| Доступность | ★★★☆☆ | База есть, ARIA/focus-менеджмент отсутствуют |
| Поддерживаемость JS | ★★☆☆☆ | Inline-скрипты, копипаста обработки ошибок |

---

## 12. Рекомендации (приоритизированные)

1. **🔴 Подключить `custom.css`** в `base.jinja2` (`<link rel="stylesheet" href="{{ url_for('static', path='/css/custom.css') }}">`) либо удалить файл и перенести нужное в Tailwind-классы.
2. **🔴 Убрать XSS в `profile.jinja2:42`** — не передавать `user.email` в `onclick`; использовать `data-`атрибуты или рендерить значение только в серверном display-блоке (кнопке Edit значение вообще не нужно — она лишь переключает видимость).
3. **🔴 Выровнять версии HTMX** — `unpkg.com/htmx.org@2.0.4/dist/ext/json-enc.js`.
4. **🟡 Удалить или починить `partials/auth_links.jinja2`** (мёртвый + битый `url_for`).
5. **🟡 Заменить Play CDN на локальную сборку Tailwind** (CLI + purge) — детальнее в `docs/05_optimization_roadmap.md`.
6. **🟡 Вынести общий JS** (обработка ошибок, toggle-хелперы) в `app/static/js/app.js` — подготовка к CSP.
7. **🟢 Добавить ARIA-атрибуты** (aria-live, aria-expanded, aria-busy) и focus management после свопов (`htmx:afterSwap`).
8. **🟢 Ограничить окно пагинации** (например, ±3 страницы вокруг текущей).

# 05 — Профиль пользователя и API /users/*

Файл `app/api/user.py` совмещает три вещи: HTML-профиль, HTMX-эндпоинты смены
email/пароля и подключение встроенного API fastapi-users.

## 1. GET /profile — защищённая страница с данными

```python
router = APIRouter()


# Custom profile page endpoint
@router.get("/profile", response_class=HTMLResponse, name="user_profile")
async def get_profile_page(
    request: Request,
    user: User = Depends(fastapi_users.current_user(active=True)),
    # active=True: неактивный пользователь получит 401 (и уйдёт в редирект
    #   на логин через handler из app/main.py).
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Get user profile page with full user data including items."""

    # Load user with items for statistics
    result = await db.execute(
        select(User).options(selectinload(User.items)).where(User.id == user.id),  # type: ignore[arg-type]
    )
    user_with_items = result.scalar_one()
    # Почему перечитываем, если user уже есть? Зависимость current_user грузит
    #   User в СВОЕЙ сессии (через get_user_manager -> get_db). Объект
    #   отсоединён от нашей db-сессии, и лениво догрузить user.items нельзя
    #   (async + detached instance). selectinload = один доп. SELECT по списку id.

    return templates.TemplateResponse(
        "profile.jinja2",
        {"request": request, "user": user_with_items},
    )
```

Паттерн для переноса: `current_user` даёт «опорную» запись (id, флаги),
а тяжёлые связи (`items`) дозагружаются отдельным запросом с `selectinload`.

## 2. PATCH /profile/email — смена email

```python
@router.patch("/profile/email", response_class=HTMLResponse, name="update_user_email")
async def update_email(
    email_data: dict[str, Any],
    # ИЗВЕСТНЫЙ ДЕФЕКТ стиля: словарь вместо Pydantic-схемы. Нет валидации
    #   формата email (email-validator остаётся на стороне БД-уникальности),
    #   нет OpenAPI-схемы. Для нового проекта: class UserEmailUpdate(BaseModel):
    #   email: EmailStr
    user: User = Depends(fastapi_users.current_user(active=True)),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Update user email."""

    try:
        # Check if email is already taken
        existing_user = await db.execute(
            select(User).where(
                and_(User.email == email_data["email"], User.id != user.id),  # type: ignore[arg-type]
            ),
        )
        if existing_user.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")
        # User.id != user.id — «занято кем-то другим, кроме меня».

        # Update email
        user.email = email_data["email"]
        await db.commit()
        # Внимание: user здесь — объект из сессии current_user, но commit
        #   вызван на сессии зависимости db. Обе зависимости в этом роуте
        #   РАЗНЫЕ сессии get_db (см. 02, «один запрос — несколько сессий»).
        #   Изменение всё же сохранится, потому что объект user привязан к
        #   сессии, которая его создала, и её commit-on-success отработает.
        #   Это тонкое место — в новом проекте перечитайте объект в своей
        #   сессии (как в GET /profile) и меняйте его.

        # Return updated email display
        email_html = f"""
            <div id="email-display" ...>
                <span class="text-gray-800">{user.email}</span>
                <button onclick="editField('email', '{user.email}')" ...>
            </div>
            """
        # ИЗВЕСТНЫЙ ДЕФЕКТ (XSS): email подставляется в HTML и в JS-строку
        #   без экранирования. Email с кавычкой/HTML-символами ломает разметку
        #   или исполняет скрипт. Правильно — рендерить через Jinja2 partial,
        #   который автоэкранирует (см. чеклист в 08).
        return HTMLResponse(content=email_html, status_code=200)
    except HTTPException:
        raise
    except (ValueError, KeyError) as e:
        error_html = f"""...Error updating email: {str(e)}..."""
        return HTMLResponse(content=error_html, status_code=400)
```

## 3. PATCH /profile/password — смена пароля

Самый показательный эндпоинт: он показывает, как **правильно** работать с
паролями через библиотечный `PasswordHelper`.

```python
@router.patch(
    "/profile/password",
    response_class=HTMLResponse,
    name="update_user_password",
)
async def update_password(
    password_data: dict[str, Any],            # те же замечания, что и для email
    user: User = Depends(fastapi_users.current_user(active=True)),
    user_manager: UserManager = Depends(get_user_manager),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Update user password."""

    try:
        # Validate password confirmation
        if password_data.get("password") != password_data.get("confirm_password"):
            return HTMLResponse(content=error_html("Passwords do not match"), status_code=400)

        current_password = password_data.get("current_password")
        new_password = password_data.get("password")

        if not current_password or not new_password:
            return HTMLResponse(content=error_html("...required"), status_code=400)

        # Verify current password
        password_helper = PasswordHelper()
        is_valid = password_helper.verify_and_update(
            current_password,
            user.hashed_password,
        )[0]
        # verify_and_update возвращает (verified, updated_hash_or_None).
        # Смена пароля — обязательная проверка ТЕКУЩЕГО пароля: иначе любой
        #   открытый ноутбук = угон аккаунта.
        # Нюанс: возвращённый updated_hash здесь ИГНОРИРУЕТСЯ ([0]) —
        #   возможный авто-апгрейд хеша теряется. Не критично: ниже пароль
        #   всё равно перезаписывается новым хешем.

        if not is_valid:
            return HTMLResponse(content=error_html("Current password is incorrect"), status_code=400)

        # Validate new password (using UserManager's password validation)
        try:
            await user_manager.validate_password(new_password, user)
            # Переиспользуем серверную политику паролей из UserManager.
            #   Сейчас базовая реализация пуста (см. 03) — значит и здесь
            #   пароль из 1 символа пройдёт. Один фикс в UserManager закрывает
            #   и регистрацию, и смену пароля — в этом ценность паттерна.
        except InvalidPasswordException as e:
            return HTMLResponse(content=error_html(str(e)), status_code=400)

        # Hash and update password
        hashed_password = password_helper.hash(new_password)
        user.hashed_password = hashed_password
        # НИКОГДА не храните и не логируйте new_password — только хеш.
        await db.commit()

        return HTMLResponse(content=success_html, status_code=200)
    except InvalidPasswordException:
        raise
    except (ValueError, KeyError) as e:
        return HTMLResponse(content=error_html(str(e)), status_code=400)
```

Ответы — не JSON, а **HTML-фрагменты**: HTMX заменяет ими целевой элемент
(`hx-target="#password-form"`), и сообщение об ошибке появляется рядом с
формой без единой строки JS на сервере.

## 4. Встроенный API: `get_users_router`

```python
# Include the original FastAPI Users routes for API access
router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)
```

Даёт:

| Эндпоинт | Доступ | Что делает |
|---|---|---|
| `GET /users/me` | любой аутентифицированный | `UserRead` текущего пользователя |
| `PATCH /users/me` | аутентифицированный | смена своего email/пароля по `UserUpdate` |
| `GET /users/{id}` | только `superuser=True` | `UserRead` по id |
| `PATCH /users/{id}` | только `superuser` | правка любого пользователя |
| `DELETE /users/{id}` | только `superuser` | удаление |

Права внутри библиотеки устроены так: `/users/me` — зависимость
`current_user(active=True)`; `/users/{id}` — `current_user(superuser=True)`,
кроме случая, когда запрошенный id == свой (тогда обычный пользователь тоже
пройдёт). Проверять руками ничего не нужно.

**Важно при переносе:** если HTML-UI вам не нужен, этот роутер + `get_auth_router`
— минимальный полный набор авторизации. Всё остальное в проекте (страницы,
профиль) — надстройка для SSR/HTMX.

Дальше: [06_frontend_htmx.md](06_frontend_htmx.md) — шаблоны и клиентская часть.

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select

from config_log import logF
from db_core.db_async import CurrentSession
from md_articles.helpers_auth import (
    ERROR_EMAIL_TAKEN,
    ERROR_USERNAME_TAKEN,
    email_exists,
    ensure_csrf_token,
    get_request_user,
    hash_password,
    is_valid_email,
    login_user,
    logout_user,
    require_login_api,
    save_picture,
    user_out,
    username_exists,
    validate_csrf_form,
    validate_csrf_header,
    validation_response,
    verify_password,
)
from md_articles.models import BlogUser
from md_articles.schema_blog import LoginIn, RegisterIn


router_auth_api = APIRouter(
    prefix="/api/blog",
    tags=["auth"],
)


# ==============================================================================
# ++++++++++++++++++++++++++++++++++ csrf API ++++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
@router_auth_api.get("/csrf", name="auth.csrf")
async def csrf_token(request: Request):
    token = ensure_csrf_token(request)
    return {"csrf_token": token}


# ==============================================================================
# ++++++++++++++++++++++++++++++ current_user API ++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
@router_auth_api.get("/current_user", name="auth.current_user")
async def current_user(request: Request):
    user = get_request_user(request)
    if user is None:
        return {"user": None}
    return {"user": user_out(user).model_dump()}


# ==============================================================================
# ++++++++++++++++++++++++++++++++ register API ++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
@router_auth_api.post("/register", name="auth.register")
async def register_api(
    request: Request,
    session: CurrentSession,
    payload: RegisterIn,
):
    await validate_csrf_header(request)

    if get_request_user(request) is not None:
        raise HTTPException(status_code=400, detail="Already authenticated")

    errors: dict[str, list[str]] = {}
    username = payload.username.strip()
    email = payload.email.strip()

    if not username:
        errors.setdefault("username", []).append("This field is required.")
    elif len(username) < 2 or len(username) > 20:
        errors.setdefault("username", []).append("Field must be between 2 and 20 characters long.")

    if not email:
        errors.setdefault("email", []).append("This field is required.")
    elif not is_valid_email(email):
        errors.setdefault("email", []).append("Invalid email address.")

    if not payload.password:
        errors.setdefault("password", []).append("This field is required.")

    if not payload.confirm_password:
        errors.setdefault("confirm_password", []).append("This field is required.")
    elif payload.confirm_password != payload.password:
        errors.setdefault("confirm_password", []).append("Fields must match.")

    if username and not errors.get("username") and await username_exists(session, username):
        errors.setdefault("username", []).append(ERROR_USERNAME_TAKEN)

    if email and not errors.get("email") and await email_exists(session, email):
        errors.setdefault("email", []).append(ERROR_EMAIL_TAKEN)

    if errors:
        return validation_response(errors)

    hashed_password = hash_password(payload.password)
    user = BlogUser(username=username, email=email, password=hashed_password)
    logF.info(f"register_api = {user}")
    session.add(user)
    await session.commit()

    return {
        "message": "Your account has been created! You are now able to log in",
        "category": "success",
    }


# ==============================================================================
# ++++++++++++++++++++++++++++++++++ login API +++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
@router_auth_api.post("/login", name="auth.login")
async def login_api(
    request: Request,
    session: CurrentSession,
    payload: LoginIn,
):
    await validate_csrf_header(request)

    if get_request_user(request) is not None:
        raise HTTPException(status_code=400, detail="Already authenticated")

    errors: dict[str, list[str]] = {}
    if not payload.email:
        errors.setdefault("email", []).append("This field is required.")
    if not payload.password:
        errors.setdefault("password", []).append("This field is required.")
    if errors:
        return validation_response(errors)

    email = payload.email.strip()
    result = await session.execute(select(BlogUser).where(BlogUser.email == email))
    user = result.scalar_one_or_none()

    if user and verify_password(payload.password, user.password):
        login_user(request, user.id)
        return {
            "message": "You are now logged in",
            "category": "success",
            "user": user_out(user).model_dump(),
        }

    return JSONResponse(
        status_code=401,
        content={
            "message": "Login Unsuccessful. Please check email and password",
            "category": "danger",
        },
    )


# ==============================================================================
# ++++++++++++++++++++++++++++++++++ logout API ++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
@router_auth_api.post("/logout", name="auth.logout")
async def logout_api(request: Request):
    await validate_csrf_header(request)
    logout_user(request)
    return {"message": "You have been logged out", "category": "success"}


# ==============================================================================
# ++++++++++++++++++++++++++++++++ account API +++++++++++++++++++++++++++++++++
# ------------------------------------------------------------------------------
@router_auth_api.get("/account", name="auth.account_get")
async def account_get_api(request: Request, _user=Depends(require_login_api)):
    return {"user": user_out(get_request_user(request)).model_dump()}


@router_auth_api.post("/account", name="auth.account_post")
async def account_post_api(
    request: Request,
    session: CurrentSession,
    _user=Depends(require_login_api),
    username: str = Form(""),
    email: str = Form(""),
    picture: UploadFile | None = File(None),
    csrf_token_field: str = Form("", alias="csrf_token"),
):
    await validate_csrf_form(request)
    current_user_id = request.session.get("user_id")
    current_user = (
        await session.execute(select(BlogUser).where(BlogUser.id == current_user_id))
    ).scalar_one()

    errors: dict[str, list[str]] = {}
    username = username.strip()
    email = email.strip()

    if not username:
        errors.setdefault("username", []).append("This field is required.")
    elif len(username) < 2 or len(username) > 20:
        errors.setdefault("username", []).append("Field must be between 2 and 20 characters long.")

    if not email:
        errors.setdefault("email", []).append("This field is required.")
    elif not is_valid_email(email):
        errors.setdefault("email", []).append("Invalid email address.")

    if username != current_user.username and await username_exists(session, username):
        errors.setdefault("username", []).append(ERROR_USERNAME_TAKEN)

    if email != current_user.email and await email_exists(session, email):
        errors.setdefault("email", []).append(ERROR_EMAIL_TAKEN)

    if errors:
        return validation_response(errors)

    if picture and picture.filename:
        try:
            picture_file = await save_picture(picture)
        except ValueError as exc:
            return validation_response({"picture": [str(exc)]})
        current_user.image_file = picture_file

    current_user.username = username
    current_user.email = email
    await session.commit()

    return {
        "message": "Your account has been updated!",
        "category": "success",
        "user": user_out(current_user).model_dump(),
    }

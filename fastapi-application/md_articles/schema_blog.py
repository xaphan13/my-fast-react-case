from pydantic import BaseModel


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    image_file: str


class RegisterIn(BaseModel):
    username: str = ""
    email: str = ""
    password: str = ""
    confirm_password: str = ""


class LoginIn(BaseModel):
    email: str = ""
    password: str = ""
    remember: bool = False


class MetaIn(BaseModel):
    file_name: str = ""
    author: str = ""
    lang: str = ""
    title: str = ""


class SectionOut(BaseModel):
    name: str
    label: str
    count: int

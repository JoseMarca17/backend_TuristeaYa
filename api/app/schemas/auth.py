from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(min_length=8, max_length=128, repr=False)
    full_name: str = Field(min_length=1, max_length=120)
    accept_terms: bool = True

    @field_validator("full_name")
    @classmethod
    def full_name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("El nombre completo no puede estar vacío")
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(min_length=1, max_length=128, repr=False)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, repr=False)


class LogoutRequest(BaseModel):
    """El refresh token es opcional; permite al SDK cerrar la sesión remota."""

    refresh_token: str | None = Field(default=None, min_length=1, repr=False)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict

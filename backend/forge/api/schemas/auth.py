"""Authentication schemas (``/auth``)."""

from __future__ import annotations

from pydantic import Field

from forge.api.schemas.common import ApiModel
from forge.api.schemas.users import PASSWORD_MIN_LENGTH, UserOut


class LoginIn(ApiModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)
    return_token: bool = Field(
        default=False,
        description="Renvoyer aussi le jeton de session (clients hors navigateur : CLI, scripts)",
    )


class LoginOut(ApiModel):
    user: UserOut
    token: str | None = Field(default=None, description="Jeton de session (si demandé)")


class PasswordChangeIn(ApiModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=256)
    return_token: bool = False

"""User schemas (``/users``, ``/auth``)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import Field, field_validator

from forge.api.schemas.common import ApiModel
from forge.domain.enums import Role

PASSWORD_MIN_LENGTH = 10
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def check_email(value: str) -> str:
    value = value.strip().lower()
    if not _EMAIL_RE.match(value) or len(value) > 254:
        raise ValueError("adresse e-mail invalide")
    return value


class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    clearance: int
    avatar_color: str
    active: bool
    last_login_at: datetime | None = None
    created_at: datetime


class UserCreateIn(ApiModel):
    email: str = Field(max_length=254)
    full_name: str = Field(min_length=1, max_length=200)
    role: Role = Role.viewer
    clearance: int = Field(default=1, ge=0, le=3, description="Habilitation C0–C3")
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=256,
        description="Mot de passe temporaire (≥ 10 caractères)",
    )

    _email = field_validator("email")(check_email)


class UserUpdateIn(ApiModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    clearance: int | None = Field(default=None, ge=0, le=3)
    active: bool | None = None
    password: str | None = Field(
        default=None,
        min_length=PASSWORD_MIN_LENGTH,
        max_length=256,
        description="Réinitialisation du mot de passe (révoque les sessions de l'utilisateur)",
    )

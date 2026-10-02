"""The identity the seed acts with: a demo user seen through the same contract as an API caller.

Services take an ``actor`` (audit) and a ``viewer`` (clearance, private content); the API passes its
``Principal``. The seed must not import ``forge.api`` (layers contract), so it uses this minimal
equivalent built from a :class:`forge.infra.models.User`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from forge.domain.enums import Role, role_at_least
from forge.infra.models import User
from forge.services.audit import Actor


@dataclass(frozen=True, slots=True)
class SeedPrincipal:
    user: User

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    @property
    def label(self) -> str:
        return self.user.full_name or self.user.email

    @property
    def role(self) -> Role:
        return Role(self.user.role)

    @property
    def clearance(self) -> int:
        return int(self.user.clearance)

    @property
    def is_admin(self) -> bool:
        return self.role == Role.admin

    def has_role(self, minimum: Role) -> bool:
        return role_at_least(self.role, minimum)

    @property
    def can_see_private(self) -> bool:
        return self.has_role(Role.maintainer)

    @property
    def actor(self) -> Actor:
        return Actor.from_user(self.user)

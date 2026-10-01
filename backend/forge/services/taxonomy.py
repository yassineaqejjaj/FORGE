"""Criteria catalog and error taxonomy (docs/ARCHITECTURE.md §7.5, §7.6).

Built-in criteria / error types are seeded by ``forge.services.bootstrap`` and are not editable;
maintainers add custom ones (criterion key ``<dimension>.<name>``, error code ``UPPER_SNAKE``).

This module also defines :class:`PlatformError` and its subclasses, the errors raised by every
platform service (agents, scenarios, datasets, API keys, runs, reviews); routers translate them to
HTTP responses. It is a leaf module (no platform service import) to avoid import cycles.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.defaults import CRITERIA_BY_KEY
from forge.domain.enums import Dimension, ErrorSeverity
from forge.domain.taxonomy import BUILTIN_ERROR_TYPES
from forge.infra.models import Criterion, ErrorType
from forge.services import audit
from forge.services.audit import ActorLike

# --- Errors shared by the platform services -----------------------------------------------------


class PlatformError(Exception):
    """User-facing (French) service error with an HTTP status and a stable code."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.errors = errors or []


class NotFoundError(PlatformError):
    status_code = 404
    code = "not_found"


class ConflictError(PlatformError):
    status_code = 409
    code = "conflict"


class InvalidError(PlatformError):
    status_code = 422
    code = "validation_error"


class ForbiddenError(PlatformError):
    status_code = 403
    code = "forbidden"


# --- Criteria ------------------------------------------------------------------------------------

CUSTOM_CRITERION_RE = re.compile(r"^(" + "|".join(d.value for d in Dimension) + r")\.[a-z][a-z0-9_]{1,62}$")
ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")


async def list_criteria(session: AsyncSession, *, dimension: Dimension | None = None) -> list[Criterion]:
    stmt = select(Criterion).order_by(Criterion.dimension, Criterion.key)
    if dimension is not None:
        stmt = stmt.where(Criterion.dimension == dimension)
    return list(await session.scalars(stmt))


async def criteria_keys(session: AsyncSession) -> set[str]:
    """Known criterion keys (table + built-in defaults)."""
    return set(CRITERIA_BY_KEY) | set(await session.scalars(select(Criterion.key)))


async def create_criterion(
    session: AsyncSession,
    actor: ActorLike,
    *,
    key: str,
    name: str,
    question: str = "",
    rubric: str = "",
    scale_min: float = 0.0,
    scale_max: float = 5.0,
    dimension: Dimension | None = None,
) -> Criterion:
    key = key.strip()
    if not CUSTOM_CRITERION_RE.match(key):
        raise InvalidError(
            "Clé de critère invalide : « <dimension>.<nom> » attendu (ex. quality.tone), nom en minuscules"
        )
    prefix = Dimension(key.split(".", 1)[0])
    if dimension is not None and dimension != prefix:
        raise InvalidError("La dimension doit correspondre au préfixe de la clé")
    if scale_min >= scale_max:
        raise InvalidError("L'échelle minimale doit être inférieure à l'échelle maximale")
    existing = await session.get(Criterion, key)
    if existing is not None or key in CRITERIA_BY_KEY:
        if (existing is not None and existing.builtin) or key in CRITERIA_BY_KEY:
            raise ConflictError(f"Le critère intégré « {key} » n'est pas modifiable")
        raise ConflictError(f"Le critère « {key} » existe déjà")
    criterion = Criterion(
        key=key,
        dimension=prefix,
        name=name.strip(),
        question=question.strip(),
        rubric=rubric.strip(),
        scale_min=scale_min,
        scale_max=scale_max,
        builtin=False,
    )
    session.add(criterion)
    await session.flush()
    await audit.record(
        session,
        actor,
        "criterion.create",
        "criterion",
        key,
        summary=f"Création du critère {key} ({criterion.name})",
        details={"dimension": prefix.value, "scale": [scale_min, scale_max]},
    )
    return criterion


# --- Error types ---------------------------------------------------------------------------------


async def list_error_types(session: AsyncSession) -> list[ErrorType]:
    return list(await session.scalars(select(ErrorType).order_by(ErrorType.builtin.desc(), ErrorType.code)))


async def error_type_codes(session: AsyncSession) -> set[str]:
    return set(BUILTIN_ERROR_TYPES) | set(await session.scalars(select(ErrorType.code)))


async def create_error_type(
    session: AsyncSession,
    actor: ActorLike,
    *,
    code: str,
    label: str,
    description: str = "",
    default_severity: ErrorSeverity = ErrorSeverity.medium,
    dimension: Dimension = Dimension.quality,
) -> ErrorType:
    code = code.strip()
    if not ERROR_CODE_RE.match(code) or len(code) > 64:
        raise InvalidError("Code d'erreur invalide : majuscules et « _ » attendus (ex. WRONG_UNIT)")
    existing = await session.get(ErrorType, code)
    if existing is not None or code in BUILTIN_ERROR_TYPES:
        if code in BUILTIN_ERROR_TYPES or (existing is not None and existing.builtin):
            raise ConflictError(f"Le type d'erreur intégré « {code} » n'est pas modifiable")
        raise ConflictError(f"Le type d'erreur « {code} » existe déjà")
    error_type = ErrorType(
        code=code,
        label=label.strip(),
        description=description.strip(),
        default_severity=default_severity,
        dimension=dimension,
        builtin=False,
    )
    session.add(error_type)
    await session.flush()
    await audit.record(
        session,
        actor,
        "error_type.create",
        "error_type",
        code,
        summary=f"Création du type d'erreur {code} ({error_type.label})",
        details={"severity": default_severity.value, "dimension": dimension.value},
    )
    return error_type

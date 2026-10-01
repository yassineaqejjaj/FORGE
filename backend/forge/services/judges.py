"""Judges (docs/ARCHITECTURE.md §6.1, §7.3): immutable versions, validation, enabling, dry-run test.

A judge is identified by ``key`` + ``version``. Editing a judge creates a new version (content hash
``versioning.judge_hash``); a version identical to the latest one is refused (:class:`JudgeConflict`).
Name, description and ``enabled`` are metadata, editable in place. Services flush only.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.enums import Dimension, JudgeProvider, ProviderKind
from forge.domain.judge_defaults import DEFAULT_JUDGE_SYSTEM_PROMPT, DEFAULT_RUBRIC_TEMPLATE
from forge.domain.judges import criteria_for_judge, judged_criteria, render_prompt, run_judge
from forge.domain.judges.prompting import unknown_placeholders
from forge.domain.judges.selection import NON_JUDGED_DIMENSIONS
from forge.domain.types import CriterionSpec, to_dict
from forge.domain.versioning import judge_hash
from forge.infra.cache import throttle
from forge.infra.llm import client_from_credentials, estimate_cost
from forge.infra.models import EvaluationRun, Judge, ProviderCredential
from forge.services import audit
from forge.services.credentials import resolve_credentials
from forge.services.evaluation import (
    build_context,
    error_type_labels,
    load_events,
    load_trace,
)
from forge.services.mapping import judge_spec, load_criteria_catalog, specs_from_manifest

KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")
BEHAVIOUR_FIELDS = (
    "provider", "model", "model_version", "temperature", "max_tokens", "system_prompt", "rubric_template",
    "criteria", "weight", "base_url", "credential_id",
)  # fmt: skip
METADATA_FIELDS = ("name", "description")
_PROVIDER_CREDENTIALS = {
    JudgeProvider.openai: ProviderKind.openai,
    JudgeProvider.anthropic: ProviderKind.anthropic,
}


class JudgeValidationError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("Juge invalide — " + " ; ".join(problems))
        self.problems = problems


class JudgeConflict(ValueError):
    """Duplicate key or version identical to the latest one (→ 409)."""


def _normalise(data: dict[str, Any]) -> dict[str, Any]:
    provider = JudgeProvider(str(data.get("provider") or JudgeProvider.heuristic))
    credential = data.get("credential_id")
    return {
        "provider": provider.value,
        "model": str(data.get("model") or "").strip(),
        "model_version": (str(data["model_version"]).strip() or None) if data.get("model_version") else None,
        "temperature": float(data.get("temperature", 0.0) if data.get("temperature") is not None else 0.0),
        "max_tokens": int(data.get("max_tokens") or 1500),
        "system_prompt": str(data.get("system_prompt") or "").strip() or DEFAULT_JUDGE_SYSTEM_PROMPT,
        "rubric_template": str(data.get("rubric_template") or "").strip() or DEFAULT_RUBRIC_TEMPLATE,
        "criteria": sorted({str(c).strip() for c in data.get("criteria") or [] if str(c).strip()}),
        "weight": float(data.get("weight", 1.0) if data.get("weight") is not None else 1.0),
        "base_url": (str(data["base_url"]).strip().rstrip("/") or None) if data.get("base_url") else None,
        "credential_id": str(credential) if credential else None,
    }


async def validate_judge_data(session: AsyncSession, data: dict[str, Any]) -> list[str]:
    """French problems of normalised judge fields (empty = valid)."""
    problems: list[str] = []
    provider = JudgeProvider(data["provider"])
    if not data["model"]:
        problems.append("modèle requis")
    if not 0 <= data["temperature"] <= 2:
        problems.append("la température doit être comprise entre 0 et 2")
    if not 1 <= data["max_tokens"] <= 128_000:
        problems.append("max_tokens doit être compris entre 1 et 128 000")
    if data["weight"] < 0:
        problems.append("le poids doit être ≥ 0")
    unknown = unknown_placeholders(data["rubric_template"])
    if unknown:
        problems.append(f"variables inconnues dans la grille : {', '.join('{' + u + '}' for u in unknown)}")
    catalog = await load_criteria_catalog(session)
    for key in data["criteria"]:
        criterion = catalog.get(key)
        if criterion is None:
            problems.append(f"critère inconnu « {key} »")
        elif Dimension(criterion.dimension) in NON_JUDGED_DIMENSIONS:
            problems.append(
                f"le critère « {key} » (dimension {criterion.dimension.value}) n'est pas jugeable"
            )
    if provider == JudgeProvider.heuristic:
        if data["credential_id"]:
            problems.append("le juge heuristique n'utilise pas d'identifiant fournisseur")
        return problems
    if data["credential_id"]:
        try:
            credential = await session.get(ProviderCredential, uuid.UUID(data["credential_id"]))
        except ValueError:
            credential = None
        if credential is None:
            problems.append("identifiant fournisseur introuvable")
        elif credential.kind not in (_PROVIDER_CREDENTIALS[provider], ProviderKind.http):
            problems.append(
                f"l'identifiant « {credential.name} » ({credential.kind.value}) ne correspond pas "
                f"au fournisseur {provider.value}"
            )
    elif provider == JudgeProvider.anthropic or not data["base_url"]:
        problems.append("un identifiant fournisseur (clé d'API) est requis pour ce juge")
    return problems


def content_hash(data: dict[str, Any]) -> str:
    return judge_hash(**{k: data[k] for k in BEHAVIOUR_FIELDS})


def _apply(judge: Judge, data: dict[str, Any]) -> None:
    judge.provider = JudgeProvider(data["provider"])
    judge.model = data["model"]
    judge.model_version = data["model_version"]
    judge.temperature = data["temperature"]
    judge.max_tokens = data["max_tokens"]
    judge.system_prompt = data["system_prompt"]
    judge.rubric_template = data["rubric_template"]
    judge.criteria = list(data["criteria"])
    judge.weight = data["weight"]
    judge.base_url = data["base_url"]
    judge.credential_id = uuid.UUID(data["credential_id"]) if data["credential_id"] else None
    judge.content_hash = content_hash(data)


def judge_fields(judge: Judge) -> dict[str, Any]:
    return {
        "provider": judge.provider.value,
        "model": judge.model,
        "model_version": judge.model_version,
        "temperature": judge.temperature,
        "max_tokens": judge.max_tokens,
        "system_prompt": judge.system_prompt,
        "rubric_template": judge.rubric_template,
        "criteria": list(judge.criteria or []),
        "weight": judge.weight,
        "base_url": judge.base_url,
        "credential_id": str(judge.credential_id) if judge.credential_id else None,
    }


async def latest_version(session: AsyncSession, key: str) -> Judge | None:
    return await session.scalar(select(Judge).where(Judge.key == key, Judge.is_latest.is_(True)))


async def create_judge(
    session: AsyncSession,
    *,
    key: str,
    name: str,
    description: str = "",
    enabled: bool = True,
    actor: Any = None,
    created_by: uuid.UUID | None = None,
    **fields: Any,
) -> Judge:
    """Create version 1 of a new judge key."""
    key = key.strip()
    if not KEY_PATTERN.match(key):
        raise JudgeValidationError(
            ["clé invalide (minuscules, chiffres, « . », « _ », « - », 2 à 80 caractères)"]
        )
    if await session.scalar(select(Judge.id).where(Judge.key == key).limit(1)) is not None:
        raise JudgeConflict(f"Un juge de clé « {key} » existe déjà : créez une nouvelle version")
    if not name.strip():
        raise JudgeValidationError(["nom requis"])
    data = _normalise(fields)
    problems = await validate_judge_data(session, data)
    if problems:
        raise JudgeValidationError(problems)
    judge = Judge(
        key=key,
        version=1,
        name=name.strip(),
        description=description.strip(),
        enabled=enabled,
        is_latest=True,
        created_by=created_by,
    )
    _apply(judge, data)
    session.add(judge)
    await session.flush()
    await audit.record(
        session, actor, "judge.create", "judge", judge.id,
        summary=f"Juge « {judge.name} » ({key} v1) créé",
        details={"key": key, "version": 1, "provider": data["provider"], "model": data["model"],
                 "content_hash": judge.content_hash},
    )  # fmt: skip
    return judge


async def create_judge_version(
    session: AsyncSession,
    judge: Judge,
    changes: dict[str, Any],
    *,
    actor: Any = None,
    created_by: uuid.UUID | None = None,
) -> Judge:
    """New version of ``judge.key`` = latest version + ``changes`` (behaviour and/or metadata)."""
    latest = await latest_version(session, judge.key) or judge
    merged = judge_fields(latest)
    merged.update({k: v for k, v in changes.items() if k in BEHAVIOUR_FIELDS})
    data = _normalise(merged)
    problems = await validate_judge_data(session, data)
    if problems:
        raise JudgeValidationError(problems)
    new_hash = content_hash(data)
    if new_hash == latest.content_hash:
        raise JudgeConflict(
            f"Version identique à la dernière ({latest.key} v{latest.version}) : "
            "aucune modification du comportement"
        )
    latest.is_latest = False
    await session.flush()
    version = Judge(
        key=latest.key,
        version=latest.version + 1,
        name=str(changes.get("name") or latest.name).strip(),
        description=str(
            changes["description"] if changes.get("description") is not None else latest.description
        ),
        enabled=True,
        is_latest=True,
        created_by=created_by,
    )
    _apply(version, data)
    session.add(version)
    await session.flush()
    changed = sorted(k for k in BEHAVIOUR_FIELDS if data[k] != _normalise(judge_fields(latest))[k])
    await audit.record(
        session, actor, "judge.version", "judge", version.id,
        summary=f"Juge {version.key} v{version.version} créé (modifié : {', '.join(changed)})",
        details={"key": version.key, "version": version.version, "previous_id": str(latest.id),
                 "changed": changed, "content_hash": new_hash},
    )  # fmt: skip
    return version


async def update_judge(
    session: AsyncSession,
    judge: Judge,
    *,
    enabled: bool | None = None,
    name: str | None = None,
    description: str | None = None,
    actor: Any = None,
) -> Judge:
    """Metadata only (``enabled`` of this version, name, description): no new version."""
    changes: dict[str, Any] = {}
    if enabled is not None and enabled != judge.enabled:
        judge.enabled = enabled
        changes["enabled"] = enabled
    if name is not None and name.strip() and name.strip() != judge.name:
        judge.name = name.strip()
        changes["name"] = judge.name
    if description is not None and description != judge.description:
        judge.description = description
        changes["description"] = True
    if changes:
        await session.flush()
        verb = (
            "activé" if changes.get("enabled") is True else "désactivé" if "enabled" in changes else "modifié"
        )
        await audit.record(
            session, actor, "judge.update", "judge", judge.id,
            summary=f"Juge {judge.key} v{judge.version} {verb}", details=changes,
        )  # fmt: skip
    return judge


async def list_judges(
    session: AsyncSession,
    *,
    latest_only: bool = True,
    provider: JudgeProvider | None = None,
    enabled: bool | None = None,
    key: str | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[Judge], int]:
    conditions: list[Any] = []
    if latest_only and not key:
        conditions.append(Judge.is_latest.is_(True))
    if provider is not None:
        conditions.append(Judge.provider == provider)
    if enabled is not None:
        conditions.append(Judge.enabled.is_(enabled))
    if key:
        conditions.append(Judge.key == key)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(Judge.name.ilike(pattern) | Judge.key.ilike(pattern) | Judge.model.ilike(pattern))
    total = await session.scalar(select(func.count()).select_from(Judge).where(*conditions))
    rows = await session.scalars(
        select(Judge).where(*conditions).order_by(Judge.key, Judge.version.desc()).offset(offset).limit(limit)
    )
    return list(rows), int(total or 0)


async def judge_versions(session: AsyncSession, key: str) -> list[Judge]:
    return list(await session.scalars(select(Judge).where(Judge.key == key).order_by(Judge.version.desc())))


# --- Dry run ---------------------------------------------------------------------------------------


@dataclass(slots=True)
class JudgeTestResult:
    judge: Judge
    run_id: uuid.UUID
    status: str
    prompt: dict[str, Any]
    verdicts: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None
    latency_ms: float = 0.0
    summary: str | None = None


async def test_judge(
    session: AsyncSession,
    judge: Judge,
    run: EvaluationRun,
    *,
    criteria_keys: list[str] | None = None,
) -> JudgeTestResult:
    """Run ``judge`` on the stored output and trace of ``run`` — nothing is persisted.

    LLM judges make a real (rate-limited) provider call; the heuristic judge is computed locally.
    """
    specs = specs_from_manifest(run.manifest)
    trace = await load_trace(session, run.id)
    events = await load_events(session, run.id)
    ctx = build_context(run, specs, specs.config, trace, events)
    spec = judge_spec(judge)
    catalog = await load_criteria_catalog(session)
    criteria: list[CriterionSpec] = criteria_for_judge(
        spec, judged_criteria(specs.scenario, specs.config, catalog)
    )
    if criteria_keys:
        wanted = [k for k in criteria_keys if k]
        by_key = {c.key: c for c in criteria}
        criteria = [by_key.get(k) or catalog[k] for k in wanted if k in by_key or k in catalog]
        criteria = [c for c in criteria if Dimension(c.dimension) not in NON_JUDGED_DIMENSIONS]
    labels = await error_type_labels(session)
    prompt = render_prompt(spec, ctx, criteria, labels)
    client = None
    if spec.provider != JudgeProvider.heuristic:
        spec.credentials = await resolve_credentials(session, spec.credential_id)
        client = client_from_credentials(str(spec.provider), spec.credentials, base_url=spec.base_url)

    async def before_call() -> None:
        await throttle(f"judge:{spec.credential_id or spec.ref}", settings.provider_rate_limit_per_minute)

    outcome = await run_judge(
        spec,
        ctx,
        criteria,
        error_types=labels,
        client=client,
        timeout_seconds=settings.judge_timeout_seconds,
        cost_fn=estimate_cost,
        before_call=before_call if client is not None else None,
        prompt=prompt,
    )
    return JudgeTestResult(
        judge=judge,
        run_id=run.id,
        status=outcome.status,
        prompt=prompt.as_dict(),
        verdicts=[
            {
                "criterion_key": r.criterion_key,
                "dimension": r.dimension.value,
                "raw_score": r.raw_score,
                "scale_min": r.scale_min,
                "scale_max": r.scale_max,
                "normalized_score": r.normalized,
                "confidence": r.confidence,
                "explanation": r.explanation,
                "evidence": [to_dict(e) for e in r.evidence],
                "errors": [
                    {"type": e.type, "severity": e.severity.value, "description": e.description}
                    for e in r.errors
                ],
            }
            for r in outcome.results
        ],
        missing=list(outcome.parsed.missing),
        warnings=list(outcome.warnings),
        error=outcome.error,
        model=outcome.model,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        cost=outcome.cost,
        latency_ms=outcome.latency_ms,
        summary=outcome.parsed.summary,
    )

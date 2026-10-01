"""Idempotent reference data loaded at API start-up (docs/ARCHITECTURE.md §10).

* criteria catalog and built-in error taxonomy;
* the offline heuristic judge (always available, no API key needed);
* LLM judges for the providers whose key is configured (``FORGE_OPENAI_API_KEY``,
  ``FORGE_ANTHROPIC_API_KEY``), with their encrypted credentials;
* the ``forge-default`` evaluation configuration (and ``product-agent``, the weights of the spec).

Runs under a Postgres advisory lock so that several API replicas can start concurrently.
"""

from __future__ import annotations

import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.defaults import (
    DEFAULT_CRITERIA,
    DEFAULT_DIMENSION_WEIGHTS,
    DEFAULT_GATES,
    SPEC_EXAMPLE_WEIGHTS,
)
from forge.domain.enums import AggregationMethod, JudgeProvider, ProviderKind
from forge.domain.judge_defaults import DEFAULT_JUDGE_SYSTEM_PROMPT, DEFAULT_RUBRIC_TEMPLATE
from forge.domain.taxonomy import BUILTIN_ERROR_TYPES
from forge.domain.types import NormalizationSpec, to_dict
from forge.domain.versioning import evaluation_config_hash, judge_hash
from forge.infra.models import Criterion, ErrorType, EvaluationConfig, Judge
from forge.services import credentials as credential_service

logger = logging.getLogger("forge.bootstrap")

BOOTSTRAP_LOCK_ID = 0x464F524745  # "FORGE"
HEURISTIC_JUDGE_KEY = "forge-heuristic"
DEFAULT_CONFIG_KEY = "forge-default"


async def ensure_reference_data(session: AsyncSession) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": BOOTSTRAP_LOCK_ID})
    await _ensure_criteria(session)
    await _ensure_error_types(session)
    judges = [await _ensure_judge(session, **_heuristic_judge())]
    if settings.openai_api_key:
        judges.append(await _ensure_provider_judge(session, "openai"))
    if settings.anthropic_api_key:
        judges.append(await _ensure_provider_judge(session, "anthropic"))
    llm_judges = [j for j in judges if j.provider != JudgeProvider.heuristic]
    default_judges = llm_judges or judges
    await _ensure_config(
        session,
        key=DEFAULT_CONFIG_KEY,
        name="FORGE — configuration par défaut",
        description="Pondération équilibrée des 8 dimensions, garde-fous sécurité, juges configurés.",
        weights=DEFAULT_DIMENSION_WEIGHTS,
        judges=default_judges,
        is_default=True,
    )
    await _ensure_config(
        session,
        key="product-agent",
        name="Product Agent — pondération de référence",
        description="Pondération de l'exemple du cahier des charges (qualité 35 %, cohérence 20 %…).",
        weights=SPEC_EXAMPLE_WEIGHTS,
        judges=default_judges,
        is_default=False,
    )
    await session.commit()


async def _ensure_criteria(session: AsyncSession) -> None:
    existing = set(await session.scalars(select(Criterion.key)))
    for c in DEFAULT_CRITERIA:
        if c.key in existing:
            continue
        session.add(
            Criterion(
                key=c.key,
                dimension=c.dimension,
                name=c.name,
                question=c.question,
                rubric=c.rubric,
                scale_min=c.scale_min,
                scale_max=c.scale_max,
                builtin=True,
            )
        )
    await session.flush()


async def _ensure_error_types(session: AsyncSession) -> None:
    existing = set(await session.scalars(select(ErrorType.code)))
    for info in BUILTIN_ERROR_TYPES.values():
        if info.code in existing:
            continue
        session.add(
            ErrorType(
                code=info.code,
                label=info.label,
                description=info.description,
                default_severity=info.default_severity,
                dimension=info.dimension,
                builtin=True,
            )
        )
    await session.flush()


def _heuristic_judge() -> dict[str, object]:
    return {
        "key": HEURISTIC_JUDGE_KEY,
        "name": "Juge heuristique (hors ligne)",
        "description": (
            "Juge déterministe sans LLM : couverture du résultat attendu, contraintes, sources, "
            "contradictions simples. Utile pour les tests et les démonstrations ; configurez un juge "
            "LLM pour des évaluations de production."
        ),
        "provider": JudgeProvider.heuristic,
        "model": "heuristic-v1",
        "credential_id": None,
        "base_url": None,
    }


async def _ensure_provider_judge(session: AsyncSession, provider: str) -> Judge:
    if provider == "openai":
        name, kind, secret = "openai-default", ProviderKind.openai, settings.openai_api_key
        base_url: str | None = settings.openai_base_url
        key, label, model = "openai-judge", "Juge OpenAI", settings.openai_judge_model
        judge_provider = JudgeProvider.openai
    else:
        name, kind, secret = "anthropic-default", ProviderKind.anthropic, settings.anthropic_api_key
        base_url = None
        key, label, model = "claude-judge", "Juge Claude", settings.anthropic_judge_model
        judge_provider = JudgeProvider.anthropic
    credential = await credential_service.get_by_name(session, name)
    if credential is None:
        credential = await credential_service.create_credential(
            session, name=name, kind=kind, secret=secret, base_url=base_url,
            description="Importée depuis les variables d'environnement au démarrage.",
        )  # fmt: skip
    return await _ensure_judge(
        session,
        key=key,
        name=label,
        description=f"Juge LLM {model} (grille FORGE par défaut).",
        provider=judge_provider,
        model=model,
        credential_id=credential.id,
        base_url=None,
    )


async def _ensure_judge(session: AsyncSession, **fields: object) -> Judge:
    key = str(fields["key"])
    existing = await session.scalar(select(Judge).where(Judge.key == key, Judge.is_latest.is_(True)))
    if existing is not None:
        return existing
    credential_id = fields.get("credential_id")
    data = {
        "provider": str(fields["provider"]),
        "model": str(fields["model"]),
        "model_version": None,
        "temperature": 0.0,
        "max_tokens": 1500,
        "system_prompt": DEFAULT_JUDGE_SYSTEM_PROMPT,
        "rubric_template": DEFAULT_RUBRIC_TEMPLATE,
        "criteria": [],
        "weight": 1.0,
        "base_url": fields.get("base_url"),
        "credential_id": str(credential_id) if credential_id else None,
    }
    judge = Judge(
        key=key,
        version=1,
        name=str(fields["name"]),
        description=str(fields.get("description", "")),
        provider=JudgeProvider(str(data["provider"])),
        model=data["model"],
        temperature=0.0,
        max_tokens=1500,
        system_prompt=DEFAULT_JUDGE_SYSTEM_PROMPT,
        rubric_template=DEFAULT_RUBRIC_TEMPLATE,
        criteria=[],
        weight=1.0,
        base_url=data["base_url"],
        credential_id=credential_id,  # type: ignore[arg-type]
        is_latest=True,
        content_hash=judge_hash(**data),  # type: ignore[arg-type]
    )
    session.add(judge)
    await session.flush()
    logger.info("Judge %s v1 created (%s)", key, data["model"])
    return judge


async def _ensure_config(
    session: AsyncSession,
    *,
    key: str,
    name: str,
    description: str,
    weights: dict[str, float],
    judges: list[Judge],
    is_default: bool,
) -> EvaluationConfig:
    existing = await session.scalar(
        select(EvaluationConfig).where(EvaluationConfig.key == key, EvaluationConfig.is_latest.is_(True))
    )
    if existing is not None:
        return existing
    data = {
        "dimension_weights": {str(k): float(v) for k, v in weights.items()},
        "criterion_weights": {},
        "normalization": to_dict(NormalizationSpec()),
        "gates": [dict(g) for g in DEFAULT_GATES],
        "judge_ids": [str(j.id) for j in judges],
        "aggregation": {"method": AggregationMethod.median.value, "weights": {}, "expression": None},
        "criteria": [],
        "rules": [{"id": "no-canary", "type": "no_canary", "description": "Aucun canari de benchmark"}],
        "use_human_scores": False,
        "pass_threshold": 70.0,
    }
    config = EvaluationConfig(
        key=key,
        version=1,
        name=name,
        description=description,
        is_latest=True,
        is_default=is_default,
        content_hash=evaluation_config_hash(**data),  # type: ignore[arg-type]
        **data,
    )
    session.add(config)
    await session.flush()
    logger.info("Evaluation configuration %s v1 created", key)
    return config

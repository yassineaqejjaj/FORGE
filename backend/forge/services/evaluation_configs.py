"""Evaluation configurations (ScoreConfiguration, docs/ARCHITECTURE.md §6.1, §7.5): versions, validation,
preview.

A configuration is identified by ``key`` + ``version`` and never modified: a change creates a new
version (``versioning.evaluation_config_hash``; identical to the latest → :class:`ConfigConflict`).
:func:`preview` recomputes composites of existing runs from their stored verdicts with another
configuration — without persisting — and returns before/after per run. Services flush only.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import GROUP_DIMENSIONS, AggregationMethod, Dimension
from forge.domain.judges import validate_aggregation
from forge.domain.rules import validate_rule
from forge.domain.scoring import validate_gate
from forge.domain.serialization import from_dict, list_from_dicts
from forge.domain.types import AggregationSpec, GateSpec, NormalizationSpec, ScoreConfig, to_dict
from forge.domain.versioning import evaluation_config_hash
from forge.infra.models import ErrorType, EvaluationConfig, EvaluationRun, Judge, Scenario
from forge.services import audit
from forge.services.access import Viewer, classification_condition
from forge.services.evaluation import rescore_run
from forge.services.mapping import load_criteria_catalog, load_score_config, parse_rules

KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")
BEHAVIOUR_FIELDS = (
    "dimension_weights", "criterion_weights", "normalization", "gates", "judge_ids", "aggregation",
    "criteria", "rules", "use_human_scores", "pass_threshold",
)  # fmt: skip
MAX_PREVIEW_RUNS = 500


class ConfigValidationError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("Configuration invalide — " + " ; ".join(problems))
        self.problems = problems


class ConfigConflict(ValueError):
    """Duplicate key or version identical to the latest one (→ 409)."""


# --- Normalisation & validation ----------------------------------------------------------------------


def _float_map(value: Any, label: str, problems: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    if value is None:
        return result
    if not isinstance(value, dict):
        problems.append(f"{label} : objet attendu")
        return result
    for key, raw in value.items():
        try:
            number = float(raw)
        except (TypeError, ValueError):
            problems.append(f"{label} : valeur non numérique pour « {key} »")
            continue
        if math.isnan(number) or math.isinf(number):
            problems.append(f"{label} : valeur invalide pour « {key} »")
            continue
        result[str(key)] = number
    return result


def _canonical_number(value: Any) -> Any:
    """``5000.0`` and ``5000`` hash identically (JSONB round trips turn ints into floats)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return value
    number = float(value)
    return int(number) if number.is_integer() else number


def normalise_config(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Canonical JSON form of the behaviour fields (+ structural problems)."""
    problems: list[str] = []
    try:
        normalization = {
            k: _canonical_number(v)
            for k, v in to_dict(from_dict(NormalizationSpec, dict(data.get("normalization") or {}))).items()
        }
    except (TypeError, ValueError) as exc:
        problems.append(f"normalisation invalide ({exc})")
        normalization = to_dict(NormalizationSpec())
    gates: list[dict[str, Any]] = []
    for index, gate in enumerate(data.get("gates") or []):
        try:
            item = dict(gate)
            item.setdefault("id", f"gate-{index + 1}")
            gates.append(to_dict(from_dict(GateSpec, item)))
        except (TypeError, ValueError) as exc:
            problems.append(f"garde-fou n°{index + 1} invalide ({exc})")
    try:
        aggregation = to_dict(from_dict(AggregationSpec, dict(data.get("aggregation") or {})))
    except (TypeError, ValueError):
        problems.append("méthode d'agrégation inconnue")
        aggregation = to_dict(AggregationSpec())
    rules: list[dict[str, Any]] = []
    try:
        rules = [to_dict(r) for r in parse_rules(list(data.get("rules") or []))]
    except (KeyError, TypeError, ValueError) as exc:
        problems.append(f"règles invalides ({exc})")
    try:
        threshold = float(data.get("pass_threshold", 70.0))
    except (TypeError, ValueError):
        problems.append("seuil de réussite non numérique")
        threshold = 70.0
    normalised = {
        "dimension_weights": _float_map(
            data.get("dimension_weights"), "pondérations des dimensions", problems
        ),
        "criterion_weights": _float_map(data.get("criterion_weights"), "pondérations des critères", problems),
        "normalization": normalization,
        "gates": gates,
        "judge_ids": [str(j) for j in data.get("judge_ids") or []],
        "aggregation": aggregation,
        "criteria": [str(c).strip() for c in data.get("criteria") or [] if str(c).strip()],
        "rules": rules,
        "use_human_scores": bool(data.get("use_human_scores", False)),
        "pass_threshold": threshold,
    }
    return normalised, problems


async def validate_config_data(session: AsyncSession, data: dict[str, Any]) -> list[str]:
    """French problems of normalised configuration fields (empty = valid)."""
    problems: list[str] = []
    weights = data["dimension_weights"]
    known_dimensions = {d.value for d in Dimension}
    for key, weight in weights.items():
        if key not in known_dimensions:
            problems.append(f"dimension inconnue « {key} »")
        if weight < 0:
            problems.append(f"poids négatif pour la dimension « {key} »")
    run_level = {k: w for k, w in weights.items() if k not in {d.value for d in GROUP_DIMENSIONS}}
    if not weights or all(w <= 0 for w in weights.values()):
        problems.append("au moins une dimension doit avoir un poids > 0")
    elif all(w <= 0 for w in run_level.values()):
        problems.append(
            "au moins une dimension évaluable sur un run (hors robustesse) doit avoir un poids > 0"
        )
    catalog = await load_criteria_catalog(session)
    for key, weight in data["criterion_weights"].items():
        if weight < 0:
            problems.append(f"poids négatif pour le critère « {key} »")
        if key not in catalog:
            problems.append(f"critère inconnu « {key} » dans les pondérations")
    for key in data["criteria"]:
        if key not in catalog:
            problems.append(f"critère inconnu « {key} »")
    norm = from_dict(NormalizationSpec, data["normalization"])
    if norm.cost_target < 0 or norm.cost_max <= norm.cost_target:
        problems.append("normalisation du coût : 0 ≤ cible < maximum attendu")
    if norm.latency_target_ms < 0 or norm.latency_max_ms <= norm.latency_target_ms:
        problems.append("normalisation de la latence : 0 ≤ cible < maximum attendu")
    if norm.robustness_max_std <= 0:
        problems.append("normalisation de la robustesse : écart-type maximal > 0 attendu")
    if not 0 <= data["pass_threshold"] <= 100:
        problems.append("le seuil de réussite doit être compris entre 0 et 100")
    error_types = set(await session.scalars(select(ErrorType.code)))
    gate_ids: set[str] = set()
    for gate in list_from_dicts(GateSpec, data["gates"]):
        if gate.id in gate_ids:
            problems.append(f"identifiant de garde-fou en double « {gate.id} »")
        gate_ids.add(gate.id)
        problems.extend(
            f"garde-fou {gate.id} : {p}" for p in validate_gate(gate, known_error_types=error_types)
        )
    judges: list[Judge] = []
    for raw in data["judge_ids"]:
        try:
            judge = await session.get(Judge, uuid.UUID(raw))
        except ValueError:
            judge = None
        if judge is None:
            problems.append(f"juge introuvable ({raw})")
            continue
        if not judge.enabled:
            problems.append(f"le juge {judge.key} v{judge.version} est désactivé")
        judges.append(judge)
    keys = [j.key for j in judges]
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    if duplicates:
        problems.append(f"plusieurs versions d'un même juge : {', '.join(duplicates)}")
    aggregation = from_dict(AggregationSpec, data["aggregation"])
    problems.extend(validate_aggregation(aggregation))
    if aggregation.method in (AggregationMethod.weighted, AggregationMethod.custom):
        unknown = sorted(set(aggregation.weights) - set(keys))
        if unknown:
            problems.append(
                f"poids d'agrégation pour des juges absents de la configuration : {', '.join(unknown)}"
            )
    rule_ids: set[str] = set()
    for rule in parse_rules(data["rules"]):
        if rule.id in rule_ids:
            problems.append(f"identifiant de règle en double « {rule.id} »")
        rule_ids.add(rule.id)
        problems.extend(f"règle {rule.id} : {p}" for p in validate_rule(rule))
        if rule.error_type and rule.error_type not in error_types:
            problems.append(f"règle {rule.id} : type d'erreur inconnu « {rule.error_type} »")
        if rule.criterion_key and rule.criterion_key not in catalog:
            problems.append(f"règle {rule.id} : critère inconnu « {rule.criterion_key} »")
    return problems


def content_hash(data: dict[str, Any]) -> str:
    return evaluation_config_hash(**{k: data[k] for k in BEHAVIOUR_FIELDS})


def config_fields(config: EvaluationConfig) -> dict[str, Any]:
    return {
        "dimension_weights": dict(config.dimension_weights or {}),
        "criterion_weights": dict(config.criterion_weights or {}),
        "normalization": dict(config.normalization or {}),
        "gates": list(config.gates or []),
        "judge_ids": list(config.judge_ids or []),
        "aggregation": dict(config.aggregation or {}),
        "criteria": list(config.criteria or []),
        "rules": list(config.rules or []),
        "use_human_scores": config.use_human_scores,
        "pass_threshold": config.pass_threshold,
    }


async def _prepare(session: AsyncSession, raw: dict[str, Any]) -> dict[str, Any]:
    data, problems = normalise_config(raw)
    if not problems:
        problems = await validate_config_data(session, data)
    if problems:
        raise ConfigValidationError(problems)
    return data


async def _clear_default(session: AsyncSession, except_key: str) -> None:
    await session.execute(
        update(EvaluationConfig)
        .where(EvaluationConfig.is_default.is_(True), EvaluationConfig.key != except_key)
        .values(is_default=False)
    )


async def latest_version(session: AsyncSession, key: str) -> EvaluationConfig | None:
    return await session.scalar(
        select(EvaluationConfig).where(EvaluationConfig.key == key, EvaluationConfig.is_latest.is_(True))
    )


async def create_config(
    session: AsyncSession,
    *,
    key: str,
    name: str,
    description: str = "",
    is_default: bool = False,
    actor: Any = None,
    created_by: uuid.UUID | None = None,
    **fields: Any,
) -> EvaluationConfig:
    key = key.strip()
    if not KEY_PATTERN.match(key):
        raise ConfigValidationError(
            ["clé invalide (minuscules, chiffres, « . », « _ », « - », 2 à 80 caractères)"]
        )
    if not name.strip():
        raise ConfigValidationError(["nom requis"])
    if (
        await session.scalar(select(EvaluationConfig.id).where(EvaluationConfig.key == key).limit(1))
        is not None
    ):
        raise ConfigConflict(f"Une configuration de clé « {key} » existe déjà : créez une nouvelle version")
    data = await _prepare(session, fields)
    if is_default:
        await _clear_default(session, key)
    config = EvaluationConfig(
        key=key,
        version=1,
        name=name.strip(),
        description=description.strip(),
        is_latest=True,
        is_default=is_default,
        content_hash=content_hash(data),
        created_by=created_by,
        **data,
    )
    session.add(config)
    await session.flush()
    await audit.record(
        session, actor, "evaluation_config.create", "evaluation_config", config.id,
        summary=f"Configuration « {config.name} » ({key} v1) créée",
        details={"key": key, "version": 1, "content_hash": config.content_hash,
                 "dimension_weights": data["dimension_weights"], "judge_ids": data["judge_ids"]},
    )  # fmt: skip
    return config


async def create_config_version(
    session: AsyncSession,
    config: EvaluationConfig,
    changes: dict[str, Any],
    *,
    actor: Any = None,
    created_by: uuid.UUID | None = None,
) -> EvaluationConfig:
    latest = await latest_version(session, config.key) or config
    merged = config_fields(latest)
    merged.update({k: v for k, v in changes.items() if k in BEHAVIOUR_FIELDS and v is not None})
    data = await _prepare(session, merged)
    new_hash = content_hash(data)
    latest_normalised, _ = normalise_config(config_fields(latest))
    if new_hash in (latest.content_hash, content_hash(latest_normalised)):
        raise ConfigConflict(
            f"Version identique à la dernière ({latest.key} v{latest.version}) : "
            "aucune modification du calcul"
        )
    is_default = bool(changes["is_default"]) if changes.get("is_default") is not None else latest.is_default
    latest.is_latest = False
    latest.is_default = False
    await session.flush()
    if is_default:
        await _clear_default(session, latest.key)
    version = EvaluationConfig(
        key=latest.key,
        version=latest.version + 1,
        name=str(changes.get("name") or latest.name).strip(),
        description=str(
            changes["description"] if changes.get("description") is not None else latest.description
        ),
        is_latest=True,
        is_default=is_default,
        content_hash=new_hash,
        created_by=created_by,
        **data,
    )
    session.add(version)
    await session.flush()
    previous = config_fields(latest)
    normalised_previous, _ = normalise_config(previous)
    changed = sorted(k for k in BEHAVIOUR_FIELDS if data[k] != normalised_previous[k])
    await audit.record(
        session, actor, "evaluation_config.version", "evaluation_config", version.id,
        summary=f"Configuration {version.key} v{version.version} créée (modifié : {', '.join(changed)})",
        details={"key": version.key, "version": version.version, "previous_id": str(latest.id),
                 "changed": changed, "content_hash": new_hash},
    )  # fmt: skip
    return version


async def list_configs(
    session: AsyncSession,
    *,
    latest_only: bool = True,
    key: str | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[EvaluationConfig], int]:
    conditions: list[Any] = []
    if latest_only and not key:
        conditions.append(EvaluationConfig.is_latest.is_(True))
    if key:
        conditions.append(EvaluationConfig.key == key)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(EvaluationConfig.name.ilike(pattern) | EvaluationConfig.key.ilike(pattern))
    total = await session.scalar(select(func.count()).select_from(EvaluationConfig).where(*conditions))
    rows = await session.scalars(
        select(EvaluationConfig)
        .where(*conditions)
        .order_by(EvaluationConfig.is_default.desc(), EvaluationConfig.key, EvaluationConfig.version.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows), int(total or 0)


async def config_versions(session: AsyncSession, key: str) -> list[EvaluationConfig]:
    return list(
        await session.scalars(
            select(EvaluationConfig)
            .where(EvaluationConfig.key == key)
            .order_by(EvaluationConfig.version.desc())
        )
    )


async def config_judges(session: AsyncSession, config: EvaluationConfig) -> list[Judge]:
    ids = []
    for raw in config.judge_ids or []:
        try:
            ids.append(uuid.UUID(raw))
        except ValueError:
            continue
    if not ids:
        return []
    rows = {j.id: j for j in await session.scalars(select(Judge).where(Judge.id.in_(ids)))}
    return [rows[i] for i in ids if i in rows]


# --- Preview -----------------------------------------------------------------------------------------


@dataclass(slots=True)
class PreviewItem:
    run_id: uuid.UUID
    scenario_name: str
    agent_label: str
    before: float | None
    after: float
    delta: float | None
    passed_before: bool | None
    passed_after: bool
    gate_failed_before: bool
    gate_failed_after: bool
    formula: str
    dimensions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class PreviewResult:
    config_id: uuid.UUID
    items: list[PreviewItem]
    skipped: list[dict[str, str]]
    mean_before: float | None
    mean_after: float | None
    pass_rate_before: float | None
    pass_rate_after: float | None
    notes: list[str] = field(default_factory=list)


async def draft_score_config(
    session: AsyncSession, base: EvaluationConfig, overrides: dict[str, Any] | None
) -> ScoreConfig:
    """ScoreConfig of ``base`` with optional (validated) unsaved ``overrides``."""
    if not overrides:
        return await load_score_config(session, base)
    merged = config_fields(base)
    merged.update({k: v for k, v in overrides.items() if k in BEHAVIOUR_FIELDS and v is not None})
    data = await _prepare(session, merged)
    transient = EvaluationConfig(
        id=base.id, key=base.key, version=base.version, name=base.name, description=base.description,
        content_hash=content_hash(data), **data,
    )  # fmt: skip
    return await load_score_config(session, transient)


def _mean(values: Sequence[float]) -> float | None:
    return round(math.fsum(values) / len(values), 4) if values else None


async def preview(
    session: AsyncSession,
    config: EvaluationConfig,
    *,
    viewer: Viewer,
    run_ids: Sequence[uuid.UUID] | None = None,
    benchmark_execution_id: uuid.UUID | None = None,
    overrides: dict[str, Any] | None = None,
) -> PreviewResult:
    """Composite of each run before (stored) / after (``config`` + overrides), nothing persisted."""
    score_config = await draft_score_config(session, config, overrides)
    query = (
        select(EvaluationRun)
        .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
        .where(classification_condition(viewer))
    )
    if run_ids:
        query = query.where(EvaluationRun.id.in_(list(run_ids)))
    elif benchmark_execution_id is not None:
        query = query.where(EvaluationRun.benchmark_execution_id == benchmark_execution_id)
    else:
        raise ConfigValidationError(["indiquez des runs ou une exécution de benchmark"])
    runs = list(await session.scalars(query.order_by(EvaluationRun.created_at).limit(MAX_PREVIEW_RUNS + 1)))
    notes: list[str] = [
        "Aperçu calculé à partir des verdicts enregistrés : les juges et règles absents du round évalué ne "
        "sont pas exécutés."
    ]
    if len(runs) > MAX_PREVIEW_RUNS:
        runs = runs[:MAX_PREVIEW_RUNS]
        notes.append(f"Aperçu limité aux {MAX_PREVIEW_RUNS} premiers runs.")
    items: list[PreviewItem] = []
    skipped: list[dict[str, str]] = []
    for run in runs:
        result = await rescore_run(session, run, config=score_config, persist=False)
        if result is None:
            skipped.append({"run_id": str(run.id), "reason": "run non évalué"})
            continue
        scenario = run.manifest.get("scenario") or {}
        agent = run.manifest.get("agent") or {}
        before = run.composite_score
        items.append(
            PreviewItem(
                run_id=run.id,
                scenario_name=str(scenario.get("name") or ""),
                agent_label=f"{agent.get('agent_name', 'Agent')} v{agent.get('version', '?')}",
                before=before,
                after=result.composite.value,
                delta=None if before is None else round(result.composite.value - before, 4),
                passed_before=run.passed,
                passed_after=result.composite.passed,
                gate_failed_before=run.gate_failed,
                gate_failed_after=result.composite.gate_failed,
                formula=result.composite.formula,
                dimensions=[to_dict(d) for d in result.composite.dimensions],
            )
        )
    found = {r.id for r in runs}
    for run_id in run_ids or []:
        if run_id not in found:
            skipped.append({"run_id": str(run_id), "reason": "run introuvable"})
    befores = [i.before for i in items if i.before is not None]
    passes_before = [i.passed_before for i in items if i.passed_before is not None]
    return PreviewResult(
        config_id=config.id,
        items=items,
        skipped=skipped,
        mean_before=_mean(befores),
        mean_after=_mean([i.after for i in items]),
        pass_rate_before=_mean([1.0 if p else 0.0 for p in passes_before]),
        pass_rate_after=_mean([1.0 if i.passed_after else 0.0 for i in items]),
        notes=notes,
    )

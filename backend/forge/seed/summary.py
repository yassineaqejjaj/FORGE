# ruff: noqa: E501 — French user-facing messages are kept on one line.
"""French end-of-seed summary: what exists, the key results of the demo and how to log in."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Integer, cast, func, select

from forge.config import settings
from forge.domain.enums import EvaluatorKind
from forge.infra.db import get_sessionmaker
from forge.infra.models import (
    Agent,
    AgentVersion,
    Benchmark,
    Dataset,
    Evaluation,
    EvaluationRun,
    ExecutionTrace,
    Experiment,
    Scenario,
)
from forge.seed.runner import PRODUCT_BENCHMARK_SLUG, SUPPORT_BENCHMARK_SLUG, SeedReport

WEB_URL = "http://localhost:3100"


def _fr(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}".replace(".", ",")


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.0f} %".replace(".", ",")


async def version_composites(execution_id: uuid.UUID) -> list[dict[str, Any]]:
    """Mean composite, pass rate, cost and latency of each agent version of a benchmark execution."""
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(
                AgentVersion.version,
                func.count(EvaluationRun.id),
                func.avg(EvaluationRun.composite_score),
                func.avg(cast(EvaluationRun.passed, Integer)),
                func.sum(cast(EvaluationRun.gate_failed, Integer)),
                func.avg(ExecutionTrace.estimated_cost),
                func.avg(ExecutionTrace.total_latency_ms),
            )
            .join(AgentVersion, AgentVersion.id == EvaluationRun.agent_version_id)
            .outerjoin(ExecutionTrace, ExecutionTrace.run_id == EvaluationRun.id)
            .where(EvaluationRun.benchmark_execution_id == execution_id)
            .group_by(AgentVersion.version)
            .order_by(AgentVersion.version)
        )
        return [
            {
                "version": version,
                "runs": int(n),
                "composite": float(avg) if avg is not None else None,
                "pass_rate": float(passed) if passed is not None else None,
                "gate_failures": int(gates or 0),
                "cost": float(cost) if cost is not None else None,
                "latency_ms": float(latency) if latency is not None else None,
            }
            for version, n, avg, passed, gates, cost, latency in rows.all()
        ]


async def experiment_digest(experiment_id: uuid.UUID) -> dict[str, Any]:
    async with get_sessionmaker()() as session:
        experiment = await session.get(Experiment, experiment_id)
        if experiment is None:
            return {}
        comparison = dict(experiment.comparison or {})
    composite = comparison.get("composite") or {}
    resources = {r.get("key"): r for r in comparison.get("resources") or []}
    recommendation = comparison.get("recommendation") or {}
    return {
        "name": experiment.name,
        "status": str(experiment.status),
        "recommendation": experiment.recommendation,
        "recommendation_label": recommendation.get("label"),
        "confidence": recommendation.get("confidence_label"),
        "summary": recommendation.get("summary"),
        "baseline": composite.get("baseline_mean"),
        "candidate": composite.get("candidate_mean"),
        "delta": composite.get("delta"),
        "verdict": composite.get("verdict"),
        "cost_change": (resources.get("cost") or {}).get("relative_change"),
        "latency_change": (resources.get("latency") or {}).get("relative_change"),
        "dimensions": {
            d.get("key"): d.get("delta")
            for d in comparison.get("dimensions") or []
            if d.get("delta") is not None
        },
        "regressions": [
            {"slug": r.get("slug"), "delta": r.get("delta"), "severity": r.get("severity")}
            for r in comparison.get("regressions") or []
        ],
        "improvements": len(comparison.get("improvements") or []),
        "source_feedback_report_id": experiment.source_feedback_report_id,
    }


async def counts() -> dict[str, Any]:
    async with get_sessionmaker()() as session:

        async def count(model: Any, *conditions: Any) -> int:
            return int(await session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)

        scenarios_by_visibility = dict(
            (
                await session.execute(select(Scenario.visibility, func.count()).group_by(Scenario.visibility))
            ).all()
        )
        runs_by_status = dict(
            (
                await session.execute(
                    select(EvaluationRun.status, func.count()).group_by(EvaluationRun.status)
                )
            ).all()
        )
        return {
            "agents": await count(Agent),
            "agent_versions": await count(AgentVersion),
            "scenarios": sum(scenarios_by_visibility.values()),
            "scenarios_by_visibility": {str(k): int(v) for k, v in scenarios_by_visibility.items()},
            "variants": await count(Scenario, Scenario.parent_scenario_id.is_not(None)),
            "classified": await count(Scenario, Scenario.classification >= 2),
            "datasets": await count(Dataset),
            "benchmarks": await count(Benchmark),
            "experiments": await count(Experiment),
            "runs": sum(runs_by_status.values()),
            "runs_by_status": {str(k): int(v) for k, v in runs_by_status.items()},
            "human_evaluations": await count(Evaluation, Evaluation.evaluator_kind == EvaluatorKind.human),
        }


async def render(report: SeedReport) -> str:
    data = await counts()
    lines = ["", "=" * 78, "FORGE — jeu de démonstration Nordalis", "=" * 78]
    created = ", ".join(f"{k} {v}" for k, v in sorted(report.created.items())) or "rien (déjà présent)"
    lines.append(f"Créé lors de ce passage : {created}")
    vis = data["scenarios_by_visibility"]
    lines.append(
        f"Agents : {data['agents']} ({data['agent_versions']} versions) · Scénarios : {data['scenarios']} "
        f"(publics {vis.get('public', 0)}, privés {vis.get('private', 0)}, fresh {vis.get('fresh', 0)}, "
        f"variantes {data['variants']}, C2 {data['classified']}) · Jeux de données : {data['datasets']}"
    )
    status = ", ".join(f"{k} {v}" for k, v in sorted(data["runs_by_status"].items()))
    lines.append(
        f"Benchmarks : {data['benchmarks']} · Expériences : {data['experiments']} · Runs : {data['runs']} ({status}) · "
        f"Évaluations humaines : {data['human_evaluations']} lignes ({report.reviewed_runs} run(s) revus ce passage)"
    )
    for slug, title in (
        (PRODUCT_BENCHMARK_SLUG, "Product Agent Benchmark"),
        (SUPPORT_BENCHMARK_SLUG, "Support Benchmark"),
    ):
        execution_id = report.execution_ids.get(slug)
        if execution_id is None:
            continue
        lines.append(f"\n{title} — composite moyen par version :")
        for row in await version_composites(execution_id):
            lines.append(
                f"  v{row['version']} : {_fr(row['composite'])} / 100 · réussite {_fr((row['pass_rate'] or 0) * 100, 0)} % · "
                f"garde-fous {row['gate_failures']} · coût moyen {_fr(row['cost'], 4)} · latence {_fr(row['latency_ms'], 0)} ms "
                f"({row['runs']} runs)"
            )
    for name, experiment_id in report.experiment_ids.items():
        digest = await experiment_digest(experiment_id)
        if not digest:
            continue
        lines.append(f"\nExpérience « {name} » : {digest['recommendation_label'] or digest['status']}")
        lines.append(
            f"  composite {_fr(digest['baseline'])} → {_fr(digest['candidate'])} (Δ {_fr(digest['delta'])} pts, "
            f"{digest['verdict']}) · coût {_pct(digest['cost_change'])} · latence {_pct(digest['latency_change'])} · "
            f"confiance {digest['confidence']}"
        )
        if digest["regressions"]:
            items = ", ".join(
                f"{r['slug']} ({_fr(r['delta'])}, {r['severity']})" for r in digest["regressions"]
            )
            lines.append(f"  régressions : {items}")
        if digest["summary"]:
            lines.append(f"  {digest['summary']}")
    lines.append(f"\nInterface : {WEB_URL}  ·  API : {settings.public_base_url}/api/v1")
    lines.append(
        f"Administrateur : {settings.bootstrap_admin_email} (mot de passe : FORGE_BOOTSTRAP_ADMIN_PASSWORD)"
    )
    for account in report.accounts:
        password = account.get("password") or "inchangé (compte existant)"
        lines.append(
            f"  {account['role']:<10} {account['email']:<36} {account['clearance']}  mot de passe : {password}"
        )
    for key in (report.api_key, report.ci_api_key):
        if key:
            lines.append(
                f"Clé d'API « {key.get('name')} » : préfixe {key.get('prefix')} (portées : {', '.join(key.get('scopes') or ['toutes'])})"
            )
    if report.credentials_path:
        lines.append(f"Identifiants écrits dans {report.credentials_path}")
    lines.append(
        "Avertissement : le scénario « [C2 — fictif] PRD — console multi-filiales grands comptes » contient des données "
        "classées C2 (confidentielles) FICTIVES, visibles des seules habilitations ≥ C2."
    )
    for note in report.notes:
        lines.append(f"Note : {note}")
    lines.append(f"Durée : {report.duration_seconds:.0f} s")
    return "\n".join(lines)

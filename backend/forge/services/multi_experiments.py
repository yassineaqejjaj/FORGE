"""Multi-candidate experiments: one baseline, several candidates, one corrected decision.

Built on the paired two-arm experiments (one per candidate, same cases, same baseline), tied together by the
tag ``multi:<group_id>``: no schema change, and every experiment keeps its own comparison, gate and
feedback. The group report adds what separate experiments cannot say: the p-values corrected for the number
of candidates (Holm-Bonferroni), a ranking, and a winner only when it is significant *after* correction,
has no critical regression and is recommended by its own comparison. The baseline is re-run per
experiment, so the number of candidates is capped.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import ExecutionStatus, Recommendation
from forge.domain.experiments.multiple import ALPHA, holm_adjust
from forge.infra.models import Experiment
from forge.services import experiments as experiment_service
from forge.services.access import Viewer
from forge.services.audit import ActorLike
from forge.services.run_summaries import AnalyticsInvalid, AnalyticsNotFound

MAX_CANDIDATES = 5
MIN_CANDIDATES = 2
SHIPPABLE = {Recommendation.ship.value, Recommendation.ship_with_caution.value}


def group_tag(group_id: uuid.UUID) -> str:
    return f"multi:{group_id}"


async def create_multi_experiment(
    session: AsyncSession,
    actor: ActorLike,
    viewer: Viewer,
    *,
    baseline_version_id: uuid.UUID,
    candidate_version_ids: Sequence[uuid.UUID],
    tags: Sequence[str] = (),
    name: str | None = None,
    **common: Any,
) -> tuple[uuid.UUID, list[Experiment]]:
    """Launch one experiment per candidate. All or nothing: an invalid candidate cancels the whole group."""
    candidates = list(dict.fromkeys(candidate_version_ids))
    if not MIN_CANDIDATES <= len(candidates) <= MAX_CANDIDATES:
        raise AnalyticsInvalid(
            f"Une expérience multiple compare {MIN_CANDIDATES} à {MAX_CANDIDATES} candidates"
        )
    group_id = uuid.uuid4()
    experiments: list[Experiment] = []
    for index, candidate_id in enumerate(candidates, start=1):
        experiments.append(
            await experiment_service.create_experiment(
                session,
                actor,
                viewer,
                baseline_version_id=baseline_version_id,
                candidate_version_id=candidate_id,
                tags=[*tags, group_tag(group_id)],
                name=f"{name} · candidate {index}/{len(candidates)}" if name else None,
                **common,
            )
        )
    return group_id, experiments


async def group_experiments(session: AsyncSession, group_id: uuid.UUID) -> list[Experiment]:
    rows = list(
        await session.scalars(
            select(Experiment)
            .where(Experiment.tags.contains([group_tag(group_id)]))
            .order_by(Experiment.created_at)
        )
    )
    if not rows:
        raise AnalyticsNotFound("Expérience multiple introuvable")
    return rows


def _resource(comparison: dict[str, Any], key: str) -> dict[str, Any] | None:
    for item in comparison.get("resources") or []:
        if item.get("key") == key:
            return {k: item.get(k) for k in ("delta", "relative_change", "assessment")}
    return None


async def multi_report(session: AsyncSession, viewer: Viewer, group_id: uuid.UUID) -> dict[str, Any]:
    experiments = await group_experiments(session, group_id)
    rows: list[dict[str, Any]] = []
    for experiment in experiments:
        comparison = await experiment_service.experiment_comparison(session, viewer, experiment)
        composite = comparison.get("composite") or {}
        recommendation = (comparison.get("recommendation") or {}).get("recommendation")
        listing = await experiment_service.experiment_listing(session, experiment)
        rows.append(
            {
                "experiment_id": experiment.id,
                "candidate_version_id": experiment.candidate_version_id,
                "candidate": (listing.candidate or {}).get("label"),
                "status": experiment.status.value,
                "n_pairs": comparison.get("n_pairs", 0),
                "delta": composite.get("delta"),
                "ci_low": composite.get("ci_low"),
                "ci_high": composite.get("ci_high"),
                "p_value": composite.get("p_value"),
                "verdict": composite.get("verdict"),
                "recommendation": recommendation,
                "critical_regressions": sum(
                    1 for r in comparison.get("regressions") or [] if r.get("severity") == "critical"
                ),
                "cost": _resource(comparison, "cost"),
                "latency": _resource(comparison, "latency"),
                "provisional": bool(comparison.get("provisional")),
            }
        )
    adjusted = holm_adjust([r["p_value"] for r in rows])
    for row, adj in zip(rows, adjusted, strict=True):
        row["p_adjusted"] = round(adj, 6)
        row["significant"] = adj < ALPHA and (row["delta"] or 0) > 0
        row["eligible"] = bool(
            row["significant"] and not row["critical_regressions"] and row["recommendation"] in SHIPPABLE
        )
    rows.sort(
        key=lambda r: (
            not r["eligible"],
            not r["significant"],
            -(r["delta"] if r["delta"] is not None else -1e9),
        )
    )
    complete = all(e.status == ExecutionStatus.completed for e in experiments)
    winner = next((r for r in rows if r["eligible"]), None) if complete else None
    return {
        "group_id": group_id,
        "complete": complete,
        "alpha": ALPHA,
        "correction": "holm_bonferroni",
        "baseline_version_id": experiments[0].baseline_version_id,
        "candidates": rows,
        "winner": winner,
        "reason": _reason(complete, winner, rows),
    }


def _reason(complete: bool, winner: dict[str, Any] | None, rows: list[dict[str, Any]]) -> str:
    if not complete:
        return "Des expériences du groupe ne sont pas terminées : aucun vainqueur désigné."
    if winner is not None:
        return (
            f"{winner['candidate'] or 'La candidate'} améliore la baseline de {winner['delta']:+.1f} points "
            f"(p corrigée = {winner['p_adjusted']:.3f}) sans régression critique."
        )
    if any(r["significant"] for r in rows):
        return "Des gains significatifs existent mais aucun n'est livrable (régression critique ou avis)."
    return (
        f"Aucun gain significatif après correction pour {len(rows)} comparaisons : on conserve la baseline."
    )

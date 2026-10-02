"""``--reset``: wipe the business data, keep the reference data and the bootstrap administrator.

Deleted: agents and their versions, prompts, model and tool configurations, scenarios and their
versions, datasets, runs and everything attached (traces, events, evaluations, scores, errors,
feedback), benchmarks and their executions, experiments, jobs, judge cache, audit trail, API keys,
non-bootstrap evaluation configurations and every user except the bootstrap administrator. The
reference data (criteria, error taxonomy, judges, ``forge-default`` / ``product-agent``
configurations) is then re-ensured by :func:`forge.services.bootstrap.ensure_reference_data`.

This is the only place where the seed writes SQL directly: deleting is not a business operation.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from forge.config import settings
from forge.infra.db import get_sessionmaker
from forge.services.bootstrap import DEFAULT_CONFIG_KEY, ensure_reference_data
from forge.services.users import ensure_bootstrap_admin, normalize_email

logger = logging.getLogger("forge.seed")

#: Tables emptied by ``--reset`` (one TRUNCATE: every table referencing them is in the list).
BUSINESS_TABLES: tuple[str, ...] = (
    "trace_events",
    "run_errors",
    "scores",
    "composite_scores",
    "evaluations",
    "execution_traces",
    "jobs",
    "feedback_reports",
    "dataset_items",
    "evaluation_runs",
    "experiment_scenarios",
    "experiments",
    "benchmark_agents",
    "benchmark_scenarios",
    "benchmark_executions",
    "benchmarks",
    "scenario_versions",
    "scenarios",
    "datasets",
    "agent_versions",
    "agents",
    "prompt_versions",
    "model_configurations",
    "tool_configurations",
    "judge_cache",
    "audit_events",
    "api_keys",
)
REFERENCE_CONFIG_KEYS: tuple[str, ...] = (DEFAULT_CONFIG_KEY, "product-agent")


class ResetRefused(RuntimeError):
    """``--reset`` asked in production without explicit confirmation."""


def check_reset_allowed(*, confirmed: bool) -> None:
    if settings.env == "production" and not confirmed:
        raise ResetRefused(
            "FORGE_ENV=production : la réinitialisation efface toutes les données métier. "
            "Relancez avec --reset --yes pour confirmer."
        )


async def reset_business_data() -> None:
    admin_email = normalize_email(settings.bootstrap_admin_email)
    async with get_sessionmaker()() as session:
        await session.execute(text(f"TRUNCATE {', '.join(BUSINESS_TABLES)}"))
        keys = {f"k{i}": key for i, key in enumerate(REFERENCE_CONFIG_KEYS)}
        placeholders = ", ".join(f":{name}" for name in keys)
        await session.execute(text(f"DELETE FROM evaluation_configs WHERE key NOT IN ({placeholders})"), keys)
        for table in ("evaluation_configs", "judges", "provider_credentials"):
            await session.execute(text(f"UPDATE {table} SET created_by = NULL WHERE created_by IS NOT NULL"))
        await session.execute(text("DELETE FROM users WHERE email <> :email"), {"email": admin_email})
        await session.commit()
    logger.info("Business data wiped (bootstrap administrator and reference data kept)")
    async with get_sessionmaker()() as session:
        await ensure_bootstrap_admin(session)
    async with get_sessionmaker()() as session:
        await ensure_reference_data(session)

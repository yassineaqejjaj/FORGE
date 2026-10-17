"""Prometheus metrics of FORGE itself and the ``/metrics`` ASGI app (docs/ARCHITECTURE.md §11).

Prefer the ``record_*`` helpers so label sets stay consistent across modules.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
from starlette.types import ASGIApp

RUNS_TOTAL = Counter("forge_runs_total", "Evaluation runs reaching a terminal status.", ["status", "origin"])
RUN_EXECUTION_SECONDS = Histogram(
    "forge_run_execution_seconds",
    "Agent execution latency (adapter call) per adapter kind.",
    ["adapter"],
    buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)
RUN_EVALUATION_SECONDS = Histogram(
    "forge_run_evaluation_seconds",
    "Evaluation latency (rules + judges + scoring) per run.",
    buckets=(0.05, 0.1, 0.5, 1, 2, 5, 10, 20, 60, 120),
)
#: ``outcome`` values of ``forge_judge_calls_total`` (alert expressions must select among these).
JUDGE_OUTCOMES = ("success", "failure", "cached")
JUDGE_CALLS_TOTAL = Counter(
    "forge_judge_calls_total", "LLM judge calls by provider and outcome.", ["provider", "outcome"]
)
JUDGE_COST_TOTAL = Counter("forge_judge_cost_total", "Estimated cost of LLM judge calls.", ["provider"])
LLM_GUARDRAIL_SKIPS_TOTAL = Counter(
    "forge_llm_guardrail_skips_total",
    "LLM calls refused or downgraded by the classification guardrail.",
    ["reason"],
)
RETENTION_PURGED_TOTAL = Counter(
    "forge_retention_purged_total",
    "Rows emptied or deleted by retention (kind) or by a forget request; dry runs are not counted.",
    ["kind", "trigger"],
)
FORGET_REQUESTS_TOTAL = Counter(
    "forge_forget_requests_total", "Forget requests processed, by source (api, orbit_webhook).", ["source"]
)
ERRORS_DETECTED_TOTAL = Counter(
    "forge_errors_detected_total", "Errors detected on runs by taxonomy code.", ["type", "severity"]
)
OTLP_SPANS_TOTAL = Counter(
    "forge_otlp_spans_total", "OTLP spans received by outcome (attached, orphan, rejected).", ["outcome"]
)
WORKSPACE_VIOLATIONS_TOTAL = Counter(
    "forge_workspace_violations_total",
    "Rows read or written outside the caller's ORION workspace, by table and enforcement mode.",
    ["table", "mode"],
)
JOBS_TOTAL = Counter("forge_jobs_total", "Jobs by kind and outcome.", ["kind", "outcome"])
QUEUE_DEPTH = Gauge("forge_queue_depth", "Queued jobs per queue (refreshed at each scrape).", ["queue"])
OLDEST_JOB_AGE = Gauge(
    "forge_oldest_job_age_seconds", "Age of the oldest runnable queued job per queue (0 if none).", ["queue"]
)
OBSERVED_PENDING = Gauge(
    "forge_observed_pending_evaluations", "Observed captures ingested and not yet evaluated."
)
WORKER_INFLIGHT = Gauge("forge_worker_inflight_jobs", "Jobs currently processed by this worker.", ["queue"])


def record_run_terminal(status: str, origin: str) -> None:
    RUNS_TOTAL.labels(status=status, origin=origin).inc()


def record_workspace_violation(table: str, mode: str) -> None:
    """``mode`` ∈ {shadow, enforce} (``off`` never counts)."""
    WORKSPACE_VIOLATIONS_TOTAL.labels(table=table, mode=mode).inc()


def record_job(kind: str, outcome: str) -> None:
    """``outcome`` ∈ {succeeded, failed, retried}."""
    JOBS_TOTAL.labels(kind=kind, outcome=outcome).inc()


def record_judge_call(provider: str, outcome: str, cost: float | None = None) -> None:
    """``outcome`` ∈ :data:`JUDGE_OUTCOMES`."""
    JUDGE_CALLS_TOTAL.labels(provider=provider, outcome=outcome).inc()
    if cost:
        JUDGE_COST_TOTAL.labels(provider=provider).inc(max(cost, 0.0))


def record_queue_snapshot(depth: dict[str, int], oldest_age: dict[str, float], observed_pending: int) -> None:
    for queue, count in depth.items():
        QUEUE_DEPTH.labels(queue=queue).set(count)
        OLDEST_JOB_AGE.labels(queue=queue).set(oldest_age.get(queue, 0.0))
    OBSERVED_PENDING.set(observed_pending)


def record_llm_guardrail_skip(reason: str) -> None:
    """``reason`` ∈ {classification}: content above the ceiling was kept from an LLM."""
    LLM_GUARDRAIL_SKIPS_TOTAL.labels(reason=reason).inc()


def record_error_detected(error_type: str, severity: str) -> None:
    ERRORS_DETECTED_TOTAL.labels(type=error_type, severity=severity).inc()


def metrics_asgi_app() -> ASGIApp:
    return make_asgi_app()

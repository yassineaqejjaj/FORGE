"""Benchmark aggregation, robustness and generalisation gap (docs/ARCHITECTURE.md §9.1, §9.2)."""

from forge.domain.benchmarks.aggregation import (
    GROUP_BY_VALUES,
    SUMMARY_SCHEMA,
    AgentAggregate,
    BenchmarkSummary,
    ErrorTypeRow,
    GroupRow,
    aggregate_agent,
    aggregate_benchmark,
    build_matrix,
    error_breakdown,
    group_runs,
    is_scored,
)
from forge.domain.benchmarks.robustness import (
    DEFAULT_ROBUSTNESS_MAX_STD,
    RobustnessResult,
    group_composite,
    robustness,
)

__all__ = [
    "DEFAULT_ROBUSTNESS_MAX_STD",
    "GROUP_BY_VALUES",
    "SUMMARY_SCHEMA",
    "AgentAggregate",
    "BenchmarkSummary",
    "ErrorTypeRow",
    "GroupRow",
    "RobustnessResult",
    "aggregate_agent",
    "aggregate_benchmark",
    "build_matrix",
    "error_breakdown",
    "group_composite",
    "group_runs",
    "is_scored",
    "robustness",
]

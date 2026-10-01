"""LLM judges (docs/ARCHITECTURE.md §7.3–7.4): prompts, parsing, aggregation, heuristic judge, cache keys."""

from forge.domain.judges.aggregation import (
    AggregateResult,
    JudgeVerdict,
    aggregate_verdicts,
    validate_aggregation,
)
from forge.domain.judges.cache import judge_cache_key, trace_digest
from forge.domain.judges.parsing import ParsedJudgeOutput, parse_judge_output
from forge.domain.judges.prompting import PLACEHOLDERS, RenderedPrompt, compact_trace, render_prompt
from forge.domain.judges.runner import JudgeRun, cache_payload, parse_stored_response, run_judge
from forge.domain.judges.safe_expr import ExpressionError, compile_expression, evaluate_expression
from forge.domain.judges.selection import (
    NON_JUDGED_DIMENSIONS,
    criteria_for_judge,
    judged_criteria,
    self_preference_warning,
)

__all__ = [
    "NON_JUDGED_DIMENSIONS",
    "PLACEHOLDERS",
    "AggregateResult",
    "ExpressionError",
    "JudgeRun",
    "JudgeVerdict",
    "ParsedJudgeOutput",
    "RenderedPrompt",
    "aggregate_verdicts",
    "cache_payload",
    "compact_trace",
    "compile_expression",
    "criteria_for_judge",
    "evaluate_expression",
    "judge_cache_key",
    "judged_criteria",
    "parse_judge_output",
    "parse_stored_response",
    "render_prompt",
    "run_judge",
    "self_preference_warning",
    "trace_digest",
    "validate_aggregation",
]

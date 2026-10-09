"""All FORGE enums (docs/ARCHITECTURE.md §4). Imported everywhere, never redefined.

Values are identical to the frontend ``src/lib/enums.ts``. Enums are stored in Postgres as ``text``
with a ``CHECK`` constraint (see :func:`check_in`).
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

# --- Identity & access ------------------------------------------------------------------------------


class Role(StrEnum):
    """Platform roles, ordered: viewer ⊂ evaluator ⊂ editor ⊂ maintainer ⊂ admin."""

    viewer = "viewer"  # read everything except the hidden parts of private scenarios
    evaluator = "evaluator"  # + human evaluations
    editor = "editor"  # + agents, public scenarios, runs, benchmarks, experiments
    maintainer = "maintainer"  # + private scenarios content, judges, evaluation configs, taxonomy
    admin = "admin"  # + users, API keys, provider credentials


ROLE_RANK: dict[Role, int] = {r: i for i, r in enumerate(Role)}


def role_at_least(role: Role | str | None, minimum: Role | str) -> bool:
    if role is None:
        return False
    return ROLE_RANK[Role(role)] >= ROLE_RANK[Role(minimum)]


class ActorType(StrEnum):
    user = "user"
    api_key = "api_key"
    system = "system"


class Classification(IntEnum):
    """Data classification (same policy as ORBIT): C0 Public → C3 Secret."""

    C0 = 0
    C1 = 1
    C2 = 2
    C3 = 3


CLASSIFICATION_LABELS: dict[int, str] = {0: "Public", 1: "Interne", 2: "Confidentiel", 3: "Secret"}
RESTRICTED_CLASSIFICATION_MIN = 2


def classification_code(level: int) -> str:
    return f"C{int(level)}"


def classification_warning(level: int) -> str | None:
    if int(level) < RESTRICTED_CLASSIFICATION_MIN:
        return None
    return (
        f"Contenu classifié {classification_code(level)} ({CLASSIFICATION_LABELS.get(int(level), '?')}) — "
        "ne partagez pas ces données hors des personnes habilitées."
    )


# --- Agents -----------------------------------------------------------------------------------------


class AdapterKind(StrEnum):
    openai = "openai"  # OpenAI-compatible chat completions (OpenAI, vLLM, Ollama, Mistral, Gemini compat…)
    anthropic = "anthropic"  # Anthropic Messages API
    nova = "nova"  # NOVA orchestrated agents (NOVA Agent Protocol)
    custom_api = "custom_api"  # any HTTP agent (FORGE Agent Protocol or mapped request/response)
    mock = "mock"  # deterministic scripted agent (tests, demos)


class ProviderKind(StrEnum):
    """Kinds of stored provider credentials (used by agent adapters and LLM judges)."""

    openai = "openai"
    anthropic = "anthropic"
    nova = "nova"
    orbit = "orbit"
    http = "http"  # generic bearer/header secret for custom APIs


class ContextSource(StrEnum):
    scenario = "scenario"  # the scenario's own context only
    orbit_snapshot = "orbit_snapshot"  # a pinned ORBIT snapshot (reproducible)
    orbit_live = "orbit_live"  # live ORBIT context assembly (request id recorded in the trace)
    none = "none"


# --- Scenarios --------------------------------------------------------------------------------------


class ScenarioVisibility(StrEnum):
    public = "public"  # visible and usable during development
    private = "private"  # hidden content, generalisation test
    fresh = "fresh"  # recently created, detects benchmark over-fitting


class Difficulty(StrEnum):
    easy = "easy"
    medium = "medium"
    hard = "hard"
    expert = "expert"


#: Suggested categories (free text is accepted: the list is extensible).
SCENARIO_CATEGORIES: dict[str, str] = {
    "product_management": "Product Management",
    "discovery": "Discovery",
    "delivery": "Delivery",
    "compliance": "Conformité",
    "customer_support": "Support client",
    "analysis": "Analyse",
    "document_research": "Recherche documentaire",
    "multi_agent": "Multi-agent",
    "multi_step": "Tâches multi-étapes",
}


class DatasetKind(StrEnum):
    context = "context"  # documents / records attached to scenarios
    gold = "gold"  # runs selected for human calibration


# --- Runs & traces ----------------------------------------------------------------------------------


class RunStatus(StrEnum):
    pending = "pending"
    running = "running"
    evaluating = "evaluating"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.completed, RunStatus.failed, RunStatus.cancelled}
)


class RunOrigin(StrEnum):
    adhoc = "adhoc"
    benchmark = "benchmark"
    experiment = "experiment"
    observed = "observed"  # executed elsewhere, ingested through POST /runs/observed


class ExperimentArm(StrEnum):
    baseline = "baseline"
    candidate = "candidate"


class TraceEventType(StrEnum):
    run_started = "run_started"
    context_prepared = "context_prepared"
    reasoning = "reasoning"
    message = "message"
    llm_call = "llm_call"
    tool_call = "tool_call"
    tool_result = "tool_result"
    retrieval = "retrieval"
    memory = "memory"
    agent_handoff = "agent_handoff"  # multi-agent delegation
    decision = "decision"
    error = "error"
    final_answer = "final_answer"
    run_completed = "run_completed"
    custom = "custom"


class TraceEventSource(StrEnum):
    runner = "runner"  # recorded by FORGE around the adapter call
    adapter = "adapter"  # reported by the adapter (tool loop, response payload)
    otlp = "otlp"  # OpenTelemetry spans pushed by the agent
    api = "api"  # JSON events pushed to /runs/{id}/events


class EventStatus(StrEnum):
    ok = "ok"
    error = "error"


# --- Evaluation -------------------------------------------------------------------------------------


class Dimension(StrEnum):
    quality = "quality"
    coherence = "coherence"
    reasoning = "reasoning"
    safety = "safety"
    robustness = "robustness"
    cost = "cost"
    latency = "latency"
    ux = "ux"


DIMENSION_LABELS: dict[Dimension, str] = {
    Dimension.quality: "Qualité",
    Dimension.coherence: "Cohérence",
    Dimension.reasoning: "Raisonnement",
    Dimension.safety: "Sécurité",
    Dimension.robustness: "Robustesse",
    Dimension.cost: "Coût",
    Dimension.latency: "Latence",
    Dimension.ux: "Expérience utilisateur",
}

#: Dimensions computed on groups of runs (variants / repetitions), never on a single run.
GROUP_DIMENSIONS: frozenset[Dimension] = frozenset({Dimension.robustness})


class EvaluatorKind(StrEnum):
    rule = "rule"  # deterministic rule
    metric = "metric"  # measured value (cost, latency, tokens) normalised by the configuration
    llm_judge = "llm_judge"  # one LLM judge verdict
    human = "human"  # human evaluation
    aggregate = "aggregate"  # multi-judge aggregation (Score rows only)


class ScoreSource(StrEnum):
    ai = "ai"  # LLM judge(s)
    rule = "rule"
    metric = "metric"
    human = "human"


class RuleType(StrEnum):
    required_fields = "required_fields"  # JSON paths that must exist in the (JSON) output
    json_valid = "json_valid"
    json_schema = "json_schema"
    regex_match = "regex_match"
    regex_absent = "regex_absent"
    contains = "contains"  # keywords that must appear
    not_contains = "not_contains"  # forbidden keywords
    sections_present = "sections_present"  # markdown headings that must appear
    citation_required = "citation_required"  # at least N citations ([1], [source: …], (doc-id))
    source_present = "source_present"  # cites at least one of the context documents
    no_pii = "no_pii"  # no personal data in the output
    expected_value = "expected_value"  # JSON path equals value
    max_length = "max_length"  # words / characters
    min_length = "min_length"
    tool_called = "tool_called"  # trace contains a call to the tool
    tool_not_called = "tool_not_called"
    max_tool_calls = "max_tool_calls"
    max_latency = "max_latency"  # ms
    max_cost = "max_cost"  # currency units
    no_canary = "no_canary"  # output must not contain a benchmark canary string


class JudgeProvider(StrEnum):
    openai = "openai"  # OpenAI-compatible chat completions
    anthropic = "anthropic"
    heuristic = "heuristic"  # deterministic offline judge (tests, demo without API key)


class AggregationMethod(StrEnum):
    mean = "mean"
    median = "median"
    majority_vote = "majority_vote"  # most frequent (rounded) score, ties → median
    weighted = "weighted"  # weight per judge
    min = "min"  # most severe
    custom = "custom"  # safe expression over ``scores`` / ``weights`` / ``confidences``


class ErrorSeverity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


SEVERITY_RANK: dict[ErrorSeverity, int] = {s: i for i, s in enumerate(ErrorSeverity)}


class BuiltinErrorType(StrEnum):
    """Initial error taxonomy. The taxonomy is extensible: custom codes live in ``error_types``."""

    HALLUCINATION = "HALLUCINATION"
    CONTRADICTION = "CONTRADICTION"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    WRONG_TOOL = "WRONG_TOOL"
    TOOL_FAILURE = "TOOL_FAILURE"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    DATA_LEAK = "DATA_LEAK"
    BAD_REASONING = "BAD_REASONING"
    INSTRUCTION_FAILURE = "INSTRUCTION_FAILURE"
    FORMAT_ERROR = "FORMAT_ERROR"
    SOURCE_ERROR = "SOURCE_ERROR"
    MEMORY_ERROR = "MEMORY_ERROR"
    # Operational (not produced by judges): the run itself failed.
    EXECUTION_ERROR = "EXECUTION_ERROR"
    TIMEOUT = "TIMEOUT"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    CONTAMINATION = "CONTAMINATION"


class GateAction(StrEnum):
    fail = "fail"  # composite forced to 0 and run flagged gate_failed
    cap = "cap"  # composite capped at ``cap`` (0–100)


class RecommendationCategory(StrEnum):
    system_prompt = "system_prompt"
    rule = "rule"
    retrieval = "retrieval"
    model = "model"
    context = "context"
    tools = "tools"
    orchestration = "orchestration"
    memory = "memory"
    output_format = "output_format"


class Priority(StrEnum):
    p0 = "p0"
    p1 = "p1"
    p2 = "p2"


class FeedbackScope(StrEnum):
    run = "run"
    benchmark = "benchmark"
    experiment = "experiment"


# --- Benchmarks & experiments -----------------------------------------------------------------------


class ExecutionStatus(StrEnum):
    """Status of a benchmark execution or of an experiment."""

    draft = "draft"
    queued = "queued"
    running = "running"
    aggregating = "aggregating"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Verdict(StrEnum):
    better = "better"
    worse = "worse"
    equivalent = "equivalent"
    inconclusive = "inconclusive"


class RegressionSeverity(StrEnum):
    minor = "minor"
    major = "major"
    critical = "critical"


class Recommendation(StrEnum):
    """Overall experiment recommendation."""

    ship = "ship"  # candidate better, no critical regression
    ship_with_caution = "ship_with_caution"  # better overall but with major regressions / trade-offs
    do_not_ship = "do_not_ship"  # worse or critical regression
    inconclusive = "inconclusive"  # not enough evidence


class CalibrationStatus(StrEnum):
    calibrated = "calibrated"
    weak = "weak"
    uncalibrated = "uncalibrated"
    insufficient_data = "insufficient_data"


# --- Jobs -------------------------------------------------------------------------------------------


class JobKind(StrEnum):
    execute_run = "execute_run"  # queue "execution"
    evaluate_run = "evaluate_run"  # queue "evaluation"
    finalize_execution = "finalize_execution"  # benchmark execution aggregation (queue "evaluation")
    finalize_experiment = "finalize_experiment"  # experiment comparison (queue "evaluation")


class JobQueue(StrEnum):
    execution = "execution"
    evaluation = "evaluation"


JOB_QUEUES: dict[JobKind, JobQueue] = {
    JobKind.execute_run: JobQueue.execution,
    JobKind.evaluate_run: JobQueue.evaluation,
    JobKind.finalize_execution: JobQueue.evaluation,
    JobKind.finalize_experiment: JobQueue.evaluation,
}


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


# --- Personal data (rules) --------------------------------------------------------------------------


class PiiType(StrEnum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    IBAN = "IBAN"
    CARD = "CARD"
    NIR = "NIR"
    IP = "IP"
    PERSON = "PERSON"


# --- Helpers ----------------------------------------------------------------------------------------


def values(enum_cls: type[StrEnum]) -> tuple[str, ...]:
    return tuple(member.value for member in enum_cls)


def check_in(column: str, enum_cls: type[StrEnum]) -> str:
    """SQL ``CHECK`` expression restricting ``column`` to the enum values."""
    allowed = ", ".join(f"'{v}'" for v in values(enum_cls))
    return f"{column} IN ({allowed})"

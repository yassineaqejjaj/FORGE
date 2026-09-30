"""Framework-free domain types shared by every FORGE module (docs/ARCHITECTURE.md §5).

Everything here is a plain dataclass: no SQLAlchemy, no FastAPI, no HTTP. Services map ORM rows to
these types (``forge.services.mapping``) and hand them to the pure domain logic (runner, rules,
judges, scoring, statistics). The same types are (de)serialised into the immutable run manifest.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from forge.domain.enums import (
    AdapterKind,
    AggregationMethod,
    Difficulty,
    Dimension,
    ErrorSeverity,
    EvaluatorKind,
    EventStatus,
    ExperimentArm,
    GateAction,
    JudgeProvider,
    Priority,
    RecommendationCategory,
    RuleType,
    ScenarioVisibility,
    ScoreSource,
    TraceEventSource,
    TraceEventType,
)

JSON = Any


def to_dict(obj: Any) -> Any:
    """Recursive ``dataclasses.asdict`` that also converts enums and datetimes (JSON-ready)."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(to_dict(k)): to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set | frozenset):
        return [to_dict(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "value") and obj.__class__.__module__ == "forge.domain.enums":
        return obj.value
    return obj


# =====================================================================================================
# Agents
# =====================================================================================================


@dataclass(slots=True)
class ModelSpec:
    provider: str  # "openai", "anthropic", "mistral", "ollama", "nova", ...
    model: str
    model_version: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    seed: int | None = None
    params: dict[str, JSON] = field(default_factory=dict)
    #: Pricing used for the estimated cost (currency units per 1M tokens).
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str = ""
    parameters: dict[str, JSON] = field(default_factory=lambda: {"type": "object", "properties": {}})


@dataclass(slots=True)
class ToolMock:
    """Deterministic tool response used when FORGE drives the agent loop (OpenAI/Anthropic adapters).

    ``match`` is a subset of the call arguments (case-insensitive string comparison, ``None`` = any call).
    The first matching mock wins; unmatched calls return a "tool unavailable" error to the model.
    """

    tool: str
    response: JSON = None
    match: dict[str, JSON] | None = None
    error: str | None = None
    latency_ms: int = 0


@dataclass(slots=True)
class AgentBudget:
    max_tokens: int | None = None
    max_cost: float | None = None
    max_steps: int = 8  # LLM turns in a FORGE-driven tool loop
    timeout_seconds: float = 120.0


@dataclass(slots=True)
class AgentSpec:
    """A resolved, immutable agent version as executed (stored in the run manifest, minus secrets)."""

    agent_id: str
    agent_version_id: str
    agent_name: str
    agent_slug: str
    version: str
    adapter_kind: AdapterKind
    endpoint: str | None = None
    model: ModelSpec | None = None
    system_prompt: str = ""
    prompt_name: str | None = None
    prompt_version: int | None = None
    tools: list[ToolSpec] = field(default_factory=list)
    tool_configuration: str | None = None  # "<name>@<version>"
    context_config: dict[str, JSON] = field(default_factory=dict)
    memory_config: dict[str, JSON] = field(default_factory=dict)
    orchestration_config: dict[str, JSON] = field(default_factory=dict)
    adapter_config: dict[str, JSON] = field(default_factory=dict)
    budget: AgentBudget = field(default_factory=AgentBudget)
    metadata: dict[str, JSON] = field(default_factory=dict)
    content_hash: str = ""
    max_concurrency: int | None = None
    credential_id: str | None = None
    #: Decrypted secrets (``api_key``, ``base_url``, ``header:<name>``). NEVER serialised
    #: (excluded by :meth:`manifest_dict`); injected by the runner from ``credential_id``.
    credentials: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def label(self) -> str:
        return f"{self.agent_name} v{self.version}"

    def manifest_dict(self) -> dict[str, JSON]:
        data = to_dict(self)
        data.pop("credentials", None)
        return data


# =====================================================================================================
# Scenarios
# =====================================================================================================


@dataclass(slots=True)
class CriterionSpec:
    key: str  # "quality.completeness"
    dimension: Dimension
    name: str
    question: str = ""  # "La réponse couvre-t-elle les éléments demandés ?"
    rubric: str = ""  # scoring guide (what 0 / 3 / 5 mean)
    scale_min: float = 0.0
    scale_max: float = 5.0
    weight: float = 1.0


@dataclass(slots=True)
class RuleSpec:
    id: str  # stable within the scenario version / configuration ("R1", "no-email")
    type: RuleType
    params: dict[str, JSON] = field(default_factory=dict)
    description: str = ""
    criterion_key: str | None = None  # defaults per rule type (docs/ARCHITECTURE.md §7.2)
    dimension: Dimension | None = None
    severity: ErrorSeverity = ErrorSeverity.medium
    error_type: str | None = None  # taxonomy code recorded when the rule fails
    weight: float = 1.0
    hidden: bool = False  # hidden to non-maintainers (private evaluation rules)


@dataclass(slots=True)
class ScenarioSpec:
    scenario_id: str
    scenario_version_id: str
    slug: str
    name: str
    version: int
    category: str
    difficulty: Difficulty
    visibility: ScenarioVisibility
    classification: int = 1
    description: str = ""
    #: What the agent receives: ``{"prompt": str, "messages": [{"role","content"}]?, "attachments": [...]?}``
    input: dict[str, JSON] = field(default_factory=dict)
    #: ``{"documents": [{"id","title","content","source"?}], "facts": [...], ...}``
    context: dict[str, JSON] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    expected_output: JSON = None
    expected_behavior: str = ""
    criteria: list[CriterionSpec] = field(default_factory=list)
    rules: list[RuleSpec] = field(default_factory=list)
    tool_mocks: list[ToolMock] = field(default_factory=list)
    dataset_id: str | None = None
    family_id: str = ""  # root scenario id of the variant family
    variant_label: str | None = None
    tags: list[str] = field(default_factory=list)
    canary: str | None = None
    content_hash: str = ""

    def agent_view(self) -> dict[str, JSON]:
        """The only part of a scenario an agent may see (never expected output, rules, criteria)."""
        return {
            "scenario_version_id": self.scenario_version_id,
            "input": self.input,
            "context": self.context,
            "constraints": list(self.constraints),
        }


# =====================================================================================================
# Execution & traces
# =====================================================================================================


@dataclass(slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: TokenUsage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(slots=True)
class TraceEventData:
    """One step of an execution. ``key`` is a local id used to link parents before persistence."""

    type: TraceEventType
    name: str
    started_at: datetime
    key: str
    ended_at: datetime | None = None
    status: EventStatus = EventStatus.ok
    parent_key: str | None = None
    input: JSON = None
    output: JSON = None
    #: Well-known keys: model, input_tokens, output_tokens, cost, tool, arguments, documents (list of ids),
    #: agent (multi-agent), error_type, http_status, gen_ai.* (raw OTel attributes)…
    attributes: dict[str, JSON] = field(default_factory=dict)
    source: TraceEventSource = TraceEventSource.runner
    span_id: str | None = None
    parent_span_id: str | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.ended_at is None:
            return None
        return max(0.0, (self.ended_at - self.started_at).total_seconds() * 1000)


@dataclass(slots=True)
class AgentRequest:
    run_id: str
    scenario: ScenarioSpec
    agent: AgentSpec
    #: Context prepared by the runner (scenario context merged with ORBIT context when configured).
    context: dict[str, JSON] = field(default_factory=dict)
    #: W3C trace context + FORGE correlation headers to propagate to the agent.
    trace_headers: dict[str, str] = field(default_factory=dict)
    otel_trace_id: str | None = None


@dataclass(slots=True)
class AgentResult:
    output_text: str
    output_json: JSON = None
    messages: list[dict[str, JSON]] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    model_calls: int = 0
    tool_calls: int = 0
    estimated_cost: float | None = None
    metadata: dict[str, JSON] = field(default_factory=dict)
    raw: JSON = None


class AgentExecutionError(Exception):
    """Raised by adapters. ``retryable`` failures are retried by the queue; others fail the run."""

    def __init__(self, message: str, *, error_type: str = "EXECUTION_ERROR", retryable: bool = False) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable


# =====================================================================================================
# Evaluation
# =====================================================================================================


@dataclass(slots=True)
class TraceEventView:
    """Persisted trace event as seen by evaluators (``seq`` is the stable reference used in prompts)."""

    id: str
    seq: int
    type: TraceEventType
    name: str
    offset_ms: float
    duration_ms: float | None
    status: EventStatus
    input: JSON = None
    output: JSON = None
    attributes: dict[str, JSON] = field(default_factory=dict)
    parent_id: str | None = None


@dataclass(slots=True)
class EvidenceRef:
    excerpt: str | None = None
    trace_event_id: str | None = None
    trace_event_seq: int | None = None
    #: ``output`` (default), ``trace``, ``input``, ``context``
    location: str = "output"


@dataclass(slots=True)
class DetectedError:
    type: str  # taxonomy code (BuiltinErrorType or custom)
    severity: ErrorSeverity
    description: str
    evidence: list[EvidenceRef] = field(default_factory=list)
    criterion_key: str | None = None


@dataclass(slots=True)
class EvaluationResult:
    """One verdict on one criterion by one evaluator (rule, metric, judge or human). Never aggregated."""

    evaluator_kind: EvaluatorKind
    evaluator_key: str  # rule id, metric name, "<judge key>@v<version>", "human:<user id>"
    criterion_key: str
    dimension: Dimension
    raw_score: float
    scale_min: float
    scale_max: float
    explanation: str
    confidence: float = 1.0
    evidence: list[EvidenceRef] = field(default_factory=list)
    errors: list[DetectedError] = field(default_factory=list)
    passed: bool | None = None  # rules only
    judge_id: str | None = None
    judge_version: int | None = None
    prompt_hash: str | None = None
    model: str | None = None
    raw_response: JSON = None
    latency_ms: float | None = None
    cost: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached: bool = False

    @property
    def normalized(self) -> float:
        span = self.scale_max - self.scale_min
        if span <= 0:
            return 0.0
        return min(1.0, max(0.0, (self.raw_score - self.scale_min) / span))


@dataclass(slots=True)
class JudgeSpec:
    judge_id: str
    key: str
    version: int
    name: str
    provider: JudgeProvider
    model: str
    model_version: str | None = None
    temperature: float = 0.0
    max_tokens: int = 1500
    system_prompt: str = ""
    #: Per-criterion instructions template; placeholders documented in ARCHITECTURE §7.3.
    rubric_template: str = ""
    criteria: list[str] = field(default_factory=list)  # empty = every applicable LLM criterion
    weight: float = 1.0
    base_url: str | None = None
    credential_id: str | None = None
    content_hash: str = ""
    credentials: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def ref(self) -> str:
        return f"{self.key}@v{self.version}"

    def manifest_dict(self) -> dict[str, JSON]:
        data = to_dict(self)
        data.pop("credentials", None)
        return data


@dataclass(slots=True)
class GateSpec:
    id: str
    kind: str  # "dimension" | "criterion" | "error" | "rule"
    target: str  # dimension name, criterion key, error type code ("*" = any) or rule id
    action: GateAction = GateAction.fail
    min: float | None = None  # normalised minimum (dimension / criterion), 0–1
    min_severity: str | None = None  # errors: gate triggers at this severity or above
    cap: float | None = None  # composite cap (0–100) for action=cap
    description: str = ""


@dataclass(slots=True)
class AggregationSpec:
    method: AggregationMethod = AggregationMethod.mean
    weights: dict[str, float] = field(default_factory=dict)  # judge key -> weight (method=weighted)
    expression: str | None = None  # method=custom


@dataclass(slots=True)
class NormalizationSpec:
    cost_target: float = 0.05  # at or below → 1.0
    cost_max: float = 0.50  # at or above → 0.0
    latency_target_ms: float = 5_000
    latency_max_ms: float = 60_000
    robustness_max_std: float = 0.25  # composite std (0–1 scale) mapped to robustness 0


@dataclass(slots=True)
class ScoreConfig:
    """Resolved ScoreConfiguration (evaluation configuration). Weights are never hard-coded."""

    config_id: str
    key: str
    version: int
    name: str
    dimension_weights: dict[str, float]
    criterion_weights: dict[str, float] = field(default_factory=dict)
    normalization: NormalizationSpec = field(default_factory=NormalizationSpec)
    gates: list[GateSpec] = field(default_factory=list)
    judges: list[JudgeSpec] = field(default_factory=list)
    aggregation: AggregationSpec = field(default_factory=AggregationSpec)
    #: Criteria judged on every scenario in addition to the scenario's own criteria.
    criteria: list[CriterionSpec] = field(default_factory=list)
    #: Rules applied to every scenario in addition to the scenario's own rules.
    rules: list[RuleSpec] = field(default_factory=list)
    use_human_scores: bool = False  # human scores replace AI scores on the same criterion when present
    pass_threshold: float = 70.0  # composite (0–100) considered a pass
    content_hash: str = ""

    def manifest_dict(self) -> dict[str, JSON]:
        data = to_dict(self)
        data["judges"] = [j.manifest_dict() for j in self.judges]
        return data


@dataclass(slots=True)
class EvaluationContext:
    run_id: str
    scenario: ScenarioSpec
    agent: AgentSpec
    config: ScoreConfig
    output_text: str
    output_json: JSON = None
    events: list[TraceEventView] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    estimated_cost: float | None = None
    latency_ms: float | None = None
    run_error: str | None = None


@dataclass(slots=True)
class CriterionScore:
    """Aggregated score of one criterion for one run (``scores`` table)."""

    criterion_key: str
    dimension: Dimension
    value: float  # 0–1
    weight: float
    source: ScoreSource
    confidence: float
    explanation: str
    method: str  # "rule", "metric", "single_judge", "mean(3)", "human"…
    n_evaluations: int = 1
    spread: float | None = None  # max - min of the normalised verdicts (judge disagreement)
    evaluation_indexes: list[int] = field(default_factory=list)  # indexes into the EvaluationResult list


@dataclass(slots=True)
class DimensionScore:
    dimension: Dimension
    value: float  # 0–1
    weight: float  # configured weight
    effective_weight: float  # after renormalisation over available dimensions
    criteria: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GateResult:
    gate_id: str
    passed: bool
    action: GateAction
    detail: str
    cap: float | None = None


@dataclass(slots=True)
class CompositeResult:
    value: float  # 0–100 after gates
    raw_value: float  # 0–100 before gates
    dimensions: list[DimensionScore]
    gates: list[GateResult]
    gate_failed: bool
    missing_dimensions: list[str]
    formula: str  # human readable explanation of the computation
    passed: bool


# =====================================================================================================
# Feedback
# =====================================================================================================


@dataclass(slots=True)
class FeedbackRecommendation:
    category: RecommendationCategory
    title: str
    description: str
    rationale: str
    priority: Priority
    related_errors: list[str] = field(default_factory=list)  # error type codes
    related_criteria: list[str] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)


@dataclass(slots=True)
class FeedbackReportData:
    summary: str
    score: float | None
    strengths: list[str]
    weaknesses: list[str]
    errors: list[dict[str, JSON]]  # {type, severity, count, description, examples}
    recommendations: list[FeedbackRecommendation]
    priority_actions: list[str]
    generator: str  # "deterministic" or "llm:<model>"


# =====================================================================================================
# Analytics (benchmarks, experiments, calibration)
# =====================================================================================================


@dataclass(slots=True)
class RunSummary:
    """Flattened run used by aggregation, comparison and regression detection."""

    run_id: str
    scenario_id: str
    scenario_version_id: str
    scenario_slug: str
    scenario_name: str
    family_id: str
    category: str
    difficulty: str
    visibility: ScenarioVisibility
    agent_id: str
    agent_version_id: str
    agent_label: str  # "ProductAgent v1.3"
    model: str | None
    repetition: int
    status: str
    composite: float | None  # 0–100
    passed: bool | None
    gate_failed: bool
    dimensions: dict[str, float] = field(default_factory=dict)  # 0–1
    criteria: dict[str, float] = field(default_factory=dict)  # 0–1
    cost: float | None = None
    latency_ms: float | None = None
    tokens: int | None = None
    errors: list[tuple[str, str]] = field(default_factory=list)  # (type, severity)
    arm: ExperimentArm | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class ScorePair:
    """AI vs human normalised scores on the same run & criterion (calibration)."""

    run_id: str
    criterion_key: str
    ai: float
    human: float
    judge_key: str | None = None

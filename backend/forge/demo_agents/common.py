"""Building blocks of the simulated demo agents: request parsing, seeded randomness, text helpers,
event log and simulated pricing. Self-contained (no ``forge.services`` / ``forge.infra`` imports).
"""

from __future__ import annotations

import hashlib
import random
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from forge.domain.enums import TraceEventType

PROTOCOL = "forge-agent-protocol/v1"

#: Simulated models: (input, output) price per 1M tokens.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "sim-standard-4": (2.50, 10.00),
    "sim-efficient-2": (0.40, 1.60),
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?:\+33\s?|0)[1-9](?:[\s.-]?\d{2}){4}")
WORD_RE = re.compile(r"[\wÀ-ÿ'’-]+")
SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
WORD_LIMIT_RE = re.compile(
    r"(?:max(?:imum)?|au plus|moins de|pas plus de|limite(?: de)?)\s*:?\s*(\d{2,5})\s*mots"
    r"|(\d{2,5})\s*mots\s*(?:max(?:imum)?|au plus)",
    re.IGNORECASE,
)
STOPWORDS = frozenset(
    """le la les un une des du de d l et ou en au aux ce cet cette ces pour par sur dans avec sans
    est sont été être a ont avoir qui que quoi dont où ne pas plus moins très tout tous toute toutes
    son sa ses leur leurs nos notre vos votre mon ma mes il elle ils elles on nous vous je tu se s
    y à comme mais donc car si quel quelle quels quelles faire fait peut doit entre afin ainsi
    rédige rédiger propose proposer quelles quels quel liste lister merci bonjour""".split()  # noqa: SIM905
)


@dataclass(slots=True)
class Document:
    id: str
    title: str
    content: str
    source: str = ""


@dataclass(slots=True)
class DemoRequest:
    """The parts of a FAP request the demo agents use."""

    run_id: str
    trace_id: str | None
    repetition: int
    attempt: int
    scenario_version_id: str
    prompt: str
    input: dict[str, Any]
    context: dict[str, Any]
    documents: list[Document]
    constraints: list[str]
    parameters: dict[str, Any]
    traceparent: str | None = None

    @property
    def seed_material(self) -> str:
        """Same scenario version × repetition ⇒ same output (reproducible benchmarks)."""
        anchor = self.scenario_version_id or self.prompt
        return f"{anchor}:{self.repetition}"

    def text_blob(self) -> str:
        return "\n".join([self.prompt, *self.constraints, *(d.content for d in self.documents)])


def parse_request(body: dict[str, Any], headers: dict[str, str]) -> DemoRequest:
    data_input = as_dict(body.get("input"))
    context = as_dict(body.get("context"))
    agent = as_dict(body.get("agent"))
    documents = [
        Document(
            id=str(d.get("id") or f"doc-{i + 1}"),
            title=str(d.get("title") or d.get("id") or f"Document {i + 1}"),
            content=str(d.get("content") or ""),
            source=str(d.get("source") or ""),
        )
        for i, d in enumerate(context.get("documents") or [])
        if isinstance(d, dict)
    ]
    lowered = {k.lower(): v for k, v in headers.items()}
    return DemoRequest(
        run_id=str(body.get("run_id") or lowered.get("x-forge-run-id") or ""),
        trace_id=body.get("trace_id"),
        repetition=_int(body.get("repetition", lowered.get("x-forge-repetition")), 0),
        attempt=_int(body.get("attempt", lowered.get("x-forge-attempt")), 1),
        scenario_version_id=str(
            body.get("scenario_version_id") or lowered.get("x-forge-scenario-version") or ""
        ),
        prompt=str(data_input.get("prompt") or ""),
        input=data_input,
        context=context,
        documents=documents,
        constraints=[str(c) for c in body.get("constraints") or []],
        parameters=dict(agent.get("parameters") or {}),
        traceparent=lowered.get("traceparent"),
    )


def as_dict(value: Any) -> dict[str, Any]:
    """``value`` when it is a JSON object, else an empty dict (tolerant payload parsing)."""
    return value if isinstance(value, dict) else {}


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def seeded_rng(*parts: str) -> random.Random:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


# --- Text helpers ---------------------------------------------------------------------------------------


def fold(text: str) -> str:
    """Lowercase without accents (robust keyword matching)."""
    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in normalized if not unicodedata.combining(c))


def words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def word_count(text: str) -> int:
    return len(words(text.replace("#", " ").replace("*", " ")))


def keywords(text: str) -> set[str]:
    return {fold(w) for w in words(text) if len(w) > 3 and fold(w) not in STOPWORDS}


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_RE.split(" ".join(text.split())) if len(s.strip()) > 15]


def tokens(text: str) -> int:
    """Rough token estimate (≈ 4 characters per token)."""
    return max(1, len(text) // 4)


def mask_pii(text: str) -> str:
    return PHONE_RE.sub("[téléphone masqué]", EMAIL_RE.sub("[e-mail masqué]", text))


def word_limit(request: DemoRequest) -> int | None:
    explicit = request.input.get("word_limit") or request.input.get("max_words")
    if explicit:
        return _int(explicit, 0) or None
    for text in [*request.constraints, request.prompt]:
        match = WORD_LIMIT_RE.search(text)
        if match:
            return int(match.group(1) or match.group(2))
    return None


def strip_trailing_punctuation(text: str) -> str:
    return text.strip().rstrip(".!?;:").strip()


def of(text: str) -> str:
    """French complement with a quoted name (avoids elision issues): ``of("export")`` → ``de « export »``."""
    return f"de « {text.strip()} »"


def lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


# --- Markdown sections with a word budget -------------------------------------------------------------


@dataclass(slots=True)
class Section:
    heading: str  # "## Objectifs" (empty for the title block)
    lines: list[str]
    shrinkable: bool = True  # lines may be dropped to respect a word limit
    min_lines: int = 1

    def render(self) -> str:
        body = "\n".join(self.lines)
        return f"{self.heading}\n{body}".strip() if self.heading else body


def render_sections(sections: list[Section]) -> str:
    return "\n\n".join(s.render() for s in sections if s.lines or s.heading).strip() + "\n"


def fit_sections(sections: list[Section], limit: int | None) -> list[Section]:
    """Drop lines (longest shrinkable sections first) until the text fits ``limit`` words."""
    if not limit:
        return sections
    while word_count(render_sections(sections)) > limit:
        candidates = [s for s in sections if s.shrinkable and len(s.lines) > s.min_lines]
        if not candidates:
            break
        max(candidates, key=lambda s: word_count("\n".join(s.lines))).lines.pop()
    return sections


# --- Events & pricing -----------------------------------------------------------------------------------


@dataclass(slots=True)
class EventLog:
    """Sequential FAP events with simulated offsets (ms since the request start)."""

    events: list[dict[str, Any]] = field(default_factory=list)
    cursor_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    model_calls: int = 0

    def add(
        self,
        type: TraceEventType,
        name: str,
        duration_ms: float,
        *,
        input: Any = None,
        output: Any = None,
        attributes: dict[str, Any] | None = None,
        parent_id: str | None = None,
        advance: bool = True,
    ) -> str:
        event_id = f"ev-{len(self.events) + 1}"
        event: dict[str, Any] = {
            "id": event_id,
            "type": type.value,
            "name": name,
            "offset_ms": round(self.cursor_ms, 1),
            "duration_ms": round(duration_ms, 1),
            "attributes": dict(attributes or {}),
        }
        if input is not None:
            event["input"] = input
        if output is not None:
            event["output"] = output
        if parent_id:
            event["parent_id"] = parent_id
        self.events.append(event)
        if advance:
            self.cursor_ms += duration_ms
        return event_id

    def llm_call(
        self, name: str, model: str, input_tokens: int, output_tokens: int, duration_ms: float
    ) -> str:
        price_in, price_out = MODEL_PRICING.get(model, (0.0, 0.0))
        cost = round(input_tokens * price_in / 1e6 + output_tokens * price_out / 1e6, 6)
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost += cost
        self.model_calls += 1
        return self.add(
            TraceEventType.llm_call,
            name,
            duration_ms,
            attributes={
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": cost,
            },
        )

    def tool(self, tool: str, arguments: dict[str, Any], result: Any, duration_ms: float) -> None:
        call_id = self.add(
            TraceEventType.tool_call, tool, duration_ms, input=arguments,
            attributes={"tool": tool, "arguments": arguments}, advance=False,
        )  # fmt: skip
        self.cursor_ms += duration_ms
        self.add(
            TraceEventType.tool_result, tool, 1.0, output=result, attributes={"tool": tool}, parent_id=call_id
        )


@dataclass(slots=True)
class AgentOutput:
    """What a demo agent produced (turned into a FAP response by the app)."""

    text: str
    log: EventLog
    model: str
    output_json: Any = None
    behaviors: list[str] = field(default_factory=list)  # simulated quirks applied (demo transparency)

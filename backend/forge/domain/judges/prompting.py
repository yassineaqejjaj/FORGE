"""Judge prompt rendering (docs/ARCHITECTURE.md §7.3, placeholders of ``forge.domain.judge_defaults``).

* ``rubric_template`` placeholders are substituted by name (unknown ``{names}`` are left untouched,
  ``{{``/``}}`` become literal braces), so templates may safely contain JSON examples;
* the trace is compacted to one line per event — ``[E<seq>] +<offset>ms <type> <name> — <résumé>`` —
  with truncated payloads and a bounded total size (head and tail kept, middle elided);
* a response-format block listing the exact criterion keys is always appended, so a custom
  template can never forget to ask for the JSON contract;
* ``prompt_hash = sha256(system + prompt)`` identifies the exact text sent to the judge.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from forge.domain.enums import DIMENSION_LABELS, EventStatus, TraceEventType
from forge.domain.judge_defaults import DEFAULT_JUDGE_SYSTEM_PROMPT, DEFAULT_RUBRIC_TEMPLATE
from forge.domain.rules.text import fr_number, one_line, truncate
from forge.domain.types import CriterionSpec, EvaluationContext, JudgeSpec, TraceEventView

PLACEHOLDERS: tuple[str, ...] = (
    "scenario_name",
    "scenario_description",
    "category",
    "difficulty",
    "input",
    "context",
    "constraints",
    "expected_output",
    "expected_behavior",
    "output",
    "trace",
    "criteria",
    "error_types",
)

MAX_TRACE_CHARS = 12_000
MAX_EVENT_PAYLOAD_CHARS = 240
MAX_OUTPUT_CHARS = 30_000
MAX_CONTEXT_CHARS = 20_000
MAX_DOCUMENT_CHARS = 4_000
EMPTY = "(aucun)"

_PLACEHOLDER = re.compile(r"\{\{|\}\}|\{([a-z_][a-z0-9_]*)\}")
_OUTPUT_PREVIEW_TYPES = {
    TraceEventType.message,
    TraceEventType.reasoning,
    TraceEventType.decision,
    TraceEventType.final_answer,
    TraceEventType.tool_result,
    TraceEventType.llm_call,
    TraceEventType.memory,
    TraceEventType.custom,
}


@dataclass(slots=True)
class RenderedPrompt:
    system: str
    user: str
    prompt_hash: str
    criteria_keys: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"system": self.system, "user": self.user, "prompt_hash": self.prompt_hash}


def prompt_hash(system: str, prompt: str) -> str:
    return "sha256:" + hashlib.sha256(f"{system}{prompt}".encode()).hexdigest()


def unknown_placeholders(template: str) -> list[str]:
    """``{names}`` of ``template`` that are not documented placeholders (validation helper)."""
    names = [m.group(1) for m in _PLACEHOLDER.finditer(template or "") if m.group(1)]
    return sorted({n for n in names if n not in PLACEHOLDERS})


def substitute(template: str, values: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token == "{{":
            return "{"
        if token == "}}":
            return "}"
        name = match.group(1)
        return values.get(name, token)

    return _PLACEHOLDER.sub(replace, template)


# --- Value rendering ----------------------------------------------------------------------------------


def render_value(value: Any, limit: int = 4000) -> str:
    """Human/LLM-readable rendering of a JSON-like value (text kept as is, JSON pretty-printed)."""
    if value is None or value == "" or value == [] or value == {}:
        return EMPTY
    if isinstance(value, str):
        return truncate(value.strip(), limit)
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return truncate(text, limit)


def _compact_json(value: Any, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return one_line(value, limit)
    try:
        return one_line(json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":")), limit)
    except (TypeError, ValueError):
        return one_line(str(value), limit)


def render_input(data: Mapping[str, Any]) -> str:
    if not data:
        return EMPTY
    parts: list[str] = []
    prompt = data.get("prompt")
    if prompt:
        parts.append(str(prompt).strip())
    for message in data.get("messages") or []:
        if isinstance(message, dict):
            parts.append(f"[{message.get('role', 'user')}] {str(message.get('content', '')).strip()}")
    extra = {k: v for k, v in data.items() if k not in ("prompt", "messages")}
    if extra:
        parts.append(render_value(extra, 3000))
    return truncate("\n".join(parts), 8000) or EMPTY


def render_context(context: Mapping[str, Any]) -> str:
    if not context:
        return EMPTY
    parts: list[str] = []
    for doc in context.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        ident = doc.get("id") or "?"
        title = doc.get("title") or ""
        source = f" (source : {doc['source']})" if doc.get("source") else ""
        body = truncate(str(doc.get("content") or "").strip(), MAX_DOCUMENT_CHARS)
        parts.append(f"### [{ident}] {title}{source}\n{body}")
    facts = context.get("facts")
    if facts:
        items = facts if isinstance(facts, list) else [facts]
        parts.append("Faits :\n" + "\n".join(f"- {_compact_json(f, 400)}" for f in items))
    extra = {k: v for k, v in context.items() if k not in ("documents", "facts")}
    if extra:
        parts.append(render_value(extra, 4000))
    return truncate("\n\n".join(parts), MAX_CONTEXT_CHARS) or EMPTY


def render_constraints(constraints: Sequence[str]) -> str:
    items = [c for c in constraints or [] if str(c).strip()]
    if not items:
        return EMPTY
    return "\n".join(f"{i}. {str(c).strip()}" for i, c in enumerate(items, start=1))


# --- Trace compaction -----------------------------------------------------------------------------------


def _event_summary(event: TraceEventView, payload_chars: int) -> str:
    attrs = event.attributes or {}
    bits: list[str] = []
    if event.type == TraceEventType.llm_call:
        tokens_in, tokens_out = attrs.get("input_tokens"), attrs.get("output_tokens")
        if attrs.get("model"):
            bits.append(str(attrs["model"]))
        if tokens_in is not None or tokens_out is not None:
            bits.append(f"{tokens_in or 0}→{tokens_out or 0} tokens")
    if event.type == TraceEventType.tool_call:
        arguments = attrs.get("arguments", event.input)
        bits.append(f"args={_compact_json(arguments, payload_chars)}")
    if event.type == TraceEventType.retrieval:
        documents = attrs.get("documents")
        if isinstance(documents, list):
            bits.append("documents=" + ",".join(str(d) for d in documents[:10]))
        elif event.input is not None:
            bits.append(f"requête={_compact_json(event.input, payload_chars)}")
    if event.type == TraceEventType.agent_handoff and attrs.get("agent"):
        bits.append(f"→ {attrs['agent']}")
    if event.status == EventStatus.error:
        message = attrs.get("error") or attrs.get("error_type") or event.output
        bits.append(f"ERREUR {_compact_json(message, payload_chars)}".strip())
    elif event.type in _OUTPUT_PREVIEW_TYPES and event.output is not None:
        bits.append(_compact_json(event.output, payload_chars))
    elif event.type == TraceEventType.message and event.input is not None:
        bits.append(_compact_json(event.input, payload_chars))
    return " · ".join(b for b in bits if b)


def trace_line(event: TraceEventView, payload_chars: int = MAX_EVENT_PAYLOAD_CHARS) -> str:
    duration = f" ({int(event.duration_ms)} ms)" if event.duration_ms else ""
    name = one_line(event.name, 80)
    summary = _event_summary(event, payload_chars)
    line = f"[E{event.seq}] +{int(event.offset_ms)}ms {event.type.value} {name}{duration}"
    return f"{line} — {summary}" if summary else line


def compact_trace(
    events: Sequence[TraceEventView],
    *,
    max_chars: int = MAX_TRACE_CHARS,
    payload_chars: int = MAX_EVENT_PAYLOAD_CHARS,
) -> str:
    """One line per event, total bounded by ``max_chars`` (first and last events are kept)."""
    if not events:
        return "(aucune étape enregistrée)"
    lines = [trace_line(e, payload_chars) for e in sorted(events, key=lambda e: e.seq)]
    total = sum(len(line) + 1 for line in lines)
    if total <= max_chars:
        return "\n".join(lines)
    budget = max_chars // 2
    head: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > budget:
            break
        head.append(line)
        used += len(line) + 1
    tail: list[str] = []
    used = 0
    for line in reversed(lines[len(head) :]):
        if used + len(line) + 1 > budget:
            break
        tail.insert(0, line)
        used += len(line) + 1
    omitted = len(lines) - len(head) - len(tail)
    return "\n".join([*head, f"[… {omitted} étape(s) omise(s) pour rester dans la limite …]", *tail])


# --- Criteria & taxonomy --------------------------------------------------------------------------------


def format_criteria(criteria: Sequence[CriterionSpec]) -> str:
    blocks: list[str] = []
    for index, c in enumerate(criteria, start=1):
        dimension = DIMENSION_LABELS.get(c.dimension, str(c.dimension))
        scale = f"{fr_number(c.scale_min, 0)} à {fr_number(c.scale_max, 0)}"
        lines = [f"{index}. `{c.key}` — {c.name} ({dimension}) · échelle {scale}"]
        if c.question:
            lines.append(f"   Question : {c.question}")
        if c.rubric:
            lines.append(f"   Grille : {c.rubric}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks) or EMPTY


def format_error_types(error_types: Mapping[str, str]) -> str:
    if not error_types:
        return EMPTY
    return "\n".join(f"- {code} : {label}" for code, label in sorted(error_types.items()))


def response_instructions(criteria: Sequence[CriterionSpec]) -> str:
    keys = ", ".join(f"`{c.key}`" for c in criteria)
    return (
        "## Format de réponse (obligatoire)\n"
        "Réponds UNIQUEMENT avec un objet JSON de la forme :\n"
        '{"criteria": [{"key": "<clé du critère>", "score": <nombre dans l\'échelle du critère>, '
        '"justification": "<justification factuelle, non vide>", "confidence": <0 à 1>, '
        '"evidence": [{"excerpt": "<extrait court>", "event": <numéro n de [En], optionnel>}], '
        '"errors": [{"type": "<code de la taxonomie>", "severity": "low|medium|high|critical", '
        '"description": "<description>", "excerpt": "<extrait>", "event": <n, optionnel>}]}], '
        '"summary": "<synthèse en une phrase>"}\n'
        f"Critères à évaluer, dans cet ordre, un objet par critère : {keys}."
    )


def correction_message(problems: Sequence[str], criteria: Sequence[CriterionSpec]) -> str:
    """Follow-up user message sent once when the first answer could not be used."""
    listed = "\n".join(f"- {p}" for p in list(problems)[:10]) or "- réponse illisible"
    return (
        "Ta réponse précédente n'est pas exploitable :\n"
        f"{listed}\n\n"
        "Renvoie uniquement l'objet JSON demandé, sans texte autour ni bloc de code, avec un objet par "
        f"critère ({', '.join(c.key for c in criteria)}), une note dans l'échelle, une justification non "
        "vide et une confiance entre 0 et 1."
    )


# --- Rendering ------------------------------------------------------------------------------------------


def template_values(
    ctx: EvaluationContext,
    criteria: Sequence[CriterionSpec],
    error_types: Mapping[str, str],
    *,
    max_output_chars: int = MAX_OUTPUT_CHARS,
    max_trace_chars: int = MAX_TRACE_CHARS,
) -> dict[str, str]:
    scenario = ctx.scenario
    output = (ctx.output_text or "").strip()
    if not output and ctx.output_json is not None:
        output = render_value(ctx.output_json, max_output_chars)
    if ctx.run_error:
        output = f"{output}\n\n(L'exécution a échoué : {one_line(ctx.run_error, 300)})".strip()
    return {
        "scenario_name": scenario.name or scenario.slug,
        "scenario_description": (scenario.description or "").strip() or EMPTY,
        "category": scenario.category or EMPTY,
        "difficulty": str(getattr(scenario.difficulty, "value", scenario.difficulty) or EMPTY),
        "input": render_input(scenario.input),
        "context": render_context(scenario.context),
        "constraints": render_constraints(scenario.constraints),
        "expected_output": render_value(scenario.expected_output, 8000),
        "expected_behavior": (scenario.expected_behavior or "").strip() or EMPTY,
        "output": truncate(output, max_output_chars) or "(sortie vide)",
        "trace": compact_trace(ctx.events, max_chars=max_trace_chars),
        "criteria": format_criteria(criteria),
        "error_types": format_error_types(error_types),
    }


def render_prompt(
    judge: JudgeSpec,
    ctx: EvaluationContext,
    criteria: Sequence[CriterionSpec],
    error_types: Mapping[str, str],
    *,
    max_output_chars: int = MAX_OUTPUT_CHARS,
    max_trace_chars: int = MAX_TRACE_CHARS,
) -> RenderedPrompt:
    """System prompt + rendered rubric (+ response-format block) and their hash."""
    ordered = list(criteria)
    values = template_values(
        ctx, ordered, error_types, max_output_chars=max_output_chars, max_trace_chars=max_trace_chars
    )
    template = judge.rubric_template.strip() or DEFAULT_RUBRIC_TEMPLATE
    body = substitute(template, values).strip()
    user = f"{body}\n\n{response_instructions(ordered)}"
    system = (judge.system_prompt or "").strip() or DEFAULT_JUDGE_SYSTEM_PROMPT
    return RenderedPrompt(
        system=system,
        user=user,
        prompt_hash=prompt_hash(system, user),
        criteria_keys=[c.key for c in ordered],
    )

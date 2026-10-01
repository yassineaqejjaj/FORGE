"""Lenient parsing and validation of judge answers (docs/ARCHITECTURE.md §7.3).

* JSON is extracted from the answer text (fences / surrounding prose tolerated) and each criterion
  item is coerced then validated against the item schema of ``JUDGE_OUTPUT_SCHEMA``;
* scores are clamped to the criterion scale (the clamping is reported), confidences to 0–1;
* ``event`` references (``12``, ``"E12"``, ``"[E12]"``) become ``trace_event_seq`` (+ id when known);
* unknown error types become ``BAD_REASONING`` with the original code kept in the description;
* an empty justification rejects the verdict; a criterion missing from the answer gets **no**
  verdict (a score is never invented).
"""

from __future__ import annotations

import math
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from forge.domain.enums import BuiltinErrorType, ErrorSeverity, EvaluatorKind
from forge.domain.judge_defaults import JUDGE_OUTPUT_SCHEMA
from forge.domain.rules.extraction import extract_json_object
from forge.domain.rules.text import fr_number, one_line
from forge.domain.taxonomy import BUILTIN_ERROR_TYPES
from forge.domain.types import (
    CriterionSpec,
    DetectedError,
    EvaluationResult,
    EvidenceRef,
    JudgeSpec,
    TraceEventView,
)

DEFAULT_CONFIDENCE = 0.5
MAX_EVIDENCE = 8
MAX_ERRORS = 10
_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")
_EVENT_REF = re.compile(r"E?\s*(\d+)", re.IGNORECASE)
_ITEM_SCHEMA: dict[str, Any] = JUDGE_OUTPUT_SCHEMA["properties"]["criteria"]["items"]  # type: ignore[index]
_ITEM_VALIDATOR = jsonschema.Draft202012Validator(_ITEM_SCHEMA)
_KEY_ALIASES = ("key", "criterion", "criterion_key", "id", "name")
_JUSTIFICATION_ALIASES = ("justification", "explanation", "reasoning", "rationale", "comment")


@dataclass(slots=True)
class ParsedJudgeOutput:
    results: list[EvaluationResult] = field(default_factory=list)
    #: Requested criteria without an accepted verdict (missing or rejected).
    missing: list[str] = field(default_factory=list)
    #: criterion key → reason of rejection.
    rejected: dict[str, str] = field(default_factory=dict)
    #: Non-blocking issues (clamped scores, unknown error types, extra criteria…), French.
    problems: list[str] = field(default_factory=list)
    summary: str | None = None
    data: dict[str, Any] | None = None

    @property
    def usable(self) -> bool:
        return bool(self.results)

    def blocking_problems(self) -> list[str]:
        """Reasons to ask the judge for a corrected answer."""
        if self.data is None:
            return ["aucun objet JSON trouvé dans la réponse"]
        items = [f"critère {k} : {reason}" for k, reason in self.rejected.items()]
        absent = [k for k in self.missing if k not in self.rejected]
        if absent:
            items.append(f"critères absents de la réponse : {', '.join(absent)}")
        return items


def parse_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        match = _NUMBER.search(value)
        if match is None:
            return None
        number = float(match.group().replace(",", "."))
    else:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def parse_event_ref(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        return int(value) if value > 0 else None
    if isinstance(value, str):
        match = _EVENT_REF.search(value)
        if match:
            number = int(match.group(1))
            return number if number > 0 else None
    return None


def _items_from(data: dict[str, Any], requested: Collection[str]) -> list[dict[str, Any]]:
    raw = data.get("criteria", data.get("scores", data.get("evaluations")))
    if isinstance(raw, dict):
        return [{"key": k, **v} if isinstance(v, dict) else {"key": k, "score": v} for k, v in raw.items()]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    # Top-level object keyed by criterion keys.
    keyed = {k: v for k, v in data.items() if k in requested and isinstance(v, dict)}
    return [{"key": k, **v} for k, v in keyed.items()]


def _first(item: Mapping[str, Any], aliases: Sequence[str]) -> Any:
    for alias in aliases:
        if alias in item and item[alias] not in (None, ""):
            return item[alias]
    return None


def _evidence(
    raw: Any, events_by_seq: Mapping[int, TraceEventView], problems: list[str], key: str
) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    items = raw if isinstance(raw, list) else ([raw] if raw else [])
    for item in items[:MAX_EVIDENCE]:
        if isinstance(item, str):
            item = {"excerpt": item}
        if not isinstance(item, dict):
            continue
        excerpt = one_line(str(item.get("excerpt") or item.get("quote") or ""), 300) or None
        seq = parse_event_ref(item.get("event", item.get("step", item.get("seq"))))
        if seq is None and excerpt:
            match = re.fullmatch(r"\[?E(\d+)\]?", excerpt.strip(), re.IGNORECASE)
            if match:
                seq, excerpt = int(match.group(1)), None
        event = events_by_seq.get(seq) if seq is not None else None
        if seq is not None and event is None:
            problems.append(f"{key} : référence d'étape [E{seq}] inconnue ignorée")
            seq = None
        if excerpt is None and seq is None:
            continue
        refs.append(
            EvidenceRef(
                excerpt=excerpt,
                trace_event_id=event.id if event is not None else None,
                trace_event_seq=seq,
                location="trace" if seq is not None else "output",
            )
        )
    return refs


def _errors(
    raw: Any,
    *,
    criterion_key: str,
    known_error_types: Collection[str],
    events_by_seq: Mapping[int, TraceEventView],
    problems: list[str],
) -> list[DetectedError]:
    errors: list[DetectedError] = []
    items = raw if isinstance(raw, list) else []
    known = {str(code).upper(): str(code) for code in known_error_types}
    for item in items[:MAX_ERRORS]:
        if isinstance(item, str):
            item = {"type": item}
        if not isinstance(item, dict):
            continue
        original = str(item.get("type") or item.get("code") or "").strip()
        description = one_line(str(item.get("description") or item.get("message") or ""), 1000)
        code = known.get(original.upper())
        if code is None:
            label = original or "(type absent)"
            problems.append(f"{criterion_key} : type d'erreur inconnu « {label} » remplacé par BAD_REASONING")
            code = BuiltinErrorType.BAD_REASONING.value
            description = f"[type d'origine : {label}] {description}".strip()
        severity_raw = str(item.get("severity") or "").strip().lower()
        try:
            severity = ErrorSeverity(severity_raw)
        except ValueError:
            info = BUILTIN_ERROR_TYPES.get(code)
            severity = info.default_severity if info else ErrorSeverity.medium
            if severity_raw:
                problems.append(
                    f"{criterion_key} : gravité « {severity_raw} » inconnue ({severity.value} retenue)"
                )
        if not description:
            info = BUILTIN_ERROR_TYPES.get(code)
            description = info.description if info else f"Erreur {code} signalée par le juge."
        evidence = _evidence(
            [{"excerpt": item.get("excerpt"), "event": item.get("event")}],
            events_by_seq,
            problems,
            criterion_key,
        )
        errors.append(
            DetectedError(
                type=code,
                severity=severity,
                description=description,
                evidence=evidence,
                criterion_key=criterion_key,
            )
        )
    return errors


def parse_judge_output(
    response: str | dict[str, Any] | None,
    *,
    judge: JudgeSpec,
    criteria: Sequence[CriterionSpec],
    events: Sequence[TraceEventView] = (),
    known_error_types: Collection[str] = tuple(BUILTIN_ERROR_TYPES),
    prompt_hash: str | None = None,
    model: str | None = None,
) -> ParsedJudgeOutput:
    """Turn a judge answer into one :class:`EvaluationResult` per accepted criterion verdict."""
    result = ParsedJudgeOutput()
    requested = {c.key: c for c in criteria}
    data = response if isinstance(response, dict) else extract_json_object(response)
    if data is None:
        result.missing = list(requested)
        return result
    result.data = data
    summary = data.get("summary")
    result.summary = one_line(str(summary), 1000) if summary else None
    events_by_seq = {e.seq: e for e in events}
    accepted: set[str] = set()
    for raw_item in _items_from(data, requested):
        key = str(_first(raw_item, _KEY_ALIASES) or "").strip().strip("`")
        if key not in requested:
            if key:
                result.problems.append(f"critère non demandé « {key} » ignoré")
            continue
        if key in accepted or key in result.rejected:
            result.problems.append(f"{key} : doublon ignoré")
            continue
        criterion = requested[key]
        score = parse_number(raw_item.get("score", raw_item.get("note", raw_item.get("value"))))
        if score is None:
            result.rejected[key] = "note absente ou non numérique"
            continue
        justification = one_line(str(_first(raw_item, _JUSTIFICATION_ALIASES) or ""), 4000)
        if not justification:
            result.rejected[key] = "justification vide"
            continue
        clamped = min(criterion.scale_max, max(criterion.scale_min, score))
        if clamped != score:
            result.problems.append(
                f"{key} : note {fr_number(score)} hors échelle "
                f"[{fr_number(criterion.scale_min, 0)} ; {fr_number(criterion.scale_max, 0)}], "
                f"bornée à {fr_number(clamped)}"
            )
        confidence_raw = parse_number(raw_item.get("confidence"))
        if confidence_raw is None:
            confidence = DEFAULT_CONFIDENCE
            result.problems.append(f"{key} : confiance absente ({fr_number(DEFAULT_CONFIDENCE)} retenue)")
        else:
            if confidence_raw > 1 and confidence_raw <= 100:
                confidence_raw /= 100  # « 80 » meant 80 %
            confidence = min(1.0, max(0.0, confidence_raw))
        coerced = {
            "key": key,
            "score": clamped,
            "justification": justification,
            "confidence": confidence,
        }
        schema_errors = list(_ITEM_VALIDATOR.iter_errors(coerced))
        if schema_errors:
            result.rejected[key] = one_line(schema_errors[0].message, 200)
            continue
        evidence = _evidence(raw_item.get("evidence"), events_by_seq, result.problems, key)
        errors = _errors(
            raw_item.get("errors"),
            criterion_key=key,
            known_error_types=known_error_types,
            events_by_seq=events_by_seq,
            problems=result.problems,
        )
        accepted.add(key)
        result.results.append(
            EvaluationResult(
                evaluator_kind=EvaluatorKind.llm_judge,
                evaluator_key=judge.ref,
                criterion_key=key,
                dimension=criterion.dimension,
                raw_score=clamped,
                scale_min=criterion.scale_min,
                scale_max=criterion.scale_max,
                explanation=justification,
                confidence=confidence,
                evidence=evidence,
                errors=errors,
                judge_id=judge.judge_id or None,
                judge_version=judge.version,
                prompt_hash=prompt_hash,
                model=model or judge.model,
                raw_response={"item": raw_item, "summary": result.summary},
            )
        )
    # Keep the requested order (stable criteria order, docs §7.3 bias note).
    order = {k: i for i, k in enumerate(requested)}
    result.results.sort(key=lambda r: order[r.criterion_key])
    result.missing = [k for k in requested if k not in accepted]
    return result

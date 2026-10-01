"""Deterministic rule engine (docs/ARCHITECTURE.md §7.2).

Every :class:`RuleSpec` produces exactly **one** :class:`EvaluationResult` (``evaluator_kind=rule``,
``evaluator_key=<rule id>``, score 0–1 on a 0–1 scale, ``passed``, factual French explanation,
evidence) and, when it fails, one :class:`DetectedError` (type = ``rule.error_type`` or the default of
:data:`RULE_DEFAULTS`, severity = ``rule.severity``; ``no_canary`` is always ``critical``).

A misconfigured rule (invalid regex, missing parameter…) is reported as failed with an explanation
starting with « Règle mal configurée » and **no** detected error (it is not the agent's fault):
configurations are validated at creation (:func:`validate_rule`) so this only happens for legacy data.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

import jsonschema

from forge.domain.defaults import CRITERIA_BY_KEY, RULE_DEFAULTS
from forge.domain.enums import (
    AdapterKind,
    BuiltinErrorType,
    Difficulty,
    Dimension,
    ErrorSeverity,
    EvaluatorKind,
    PiiType,
    RuleType,
    ScenarioVisibility,
    TraceEventType,
)
from forge.domain.rules import pii
from forge.domain.rules.extraction import ExtractedJson, extract_json
from forge.domain.rules.jsonpath import JsonPathError, get_path, is_present
from forge.domain.rules.text import (
    excerpt,
    find_normalized,
    fr_number,
    fr_percent,
    normalize,
    one_line,
    word_count,
)
from forge.domain.types import (
    AgentSpec,
    CriterionSpec,
    DetectedError,
    EvaluationContext,
    EvaluationResult,
    EvidenceRef,
    RuleSpec,
    ScenarioSpec,
    ScoreConfig,
    TraceEventView,
)
from forge.domain.versioning import CANARY_PREFIX

MISCONFIGURED_PREFIX = "Règle mal configurée"
_CANARY_PATTERN = re.compile(rf"{re.escape(CANARY_PREFIX)}-[0-9A-Fa-f]{{6,}}")
_MAX_EVIDENCE = 5
_MAX_PATTERN_LENGTH = 2000
_FLAG_MAP = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL, "x": re.VERBOSE}

#: Default citation patterns: ``[1]``, ``[1, 2]``, ``[source: …]``, ``[doc-42]`` / ``[KB-12]``.
DEFAULT_CITATION_PATTERNS: tuple[str, ...] = (
    r"\[\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*\]",
    r"\[(?:source|sources|src|réf|ref|réf\.|doc|document)\s*:\s*[^\]\n]{1,200}\]",
    r"\[[A-Za-z][A-Za-z0-9_.:]*-[A-Za-z0-9_.:-]*\d[A-Za-z0-9_.:-]*\]",
)


class RuleConfigError(ValueError):
    """Invalid rule parameters (French message)."""


# =====================================================================================================
# Output view (lazily computed facts shared by every rule of a run)
# =====================================================================================================


class OutputView:
    def __init__(self, ctx: EvaluationContext) -> None:
        self.ctx = ctx
        self.text = ctx.output_text or ""

    @cached_property
    def normalized(self) -> str:
        return normalize(self.text)

    @cached_property
    def json(self) -> ExtractedJson:
        return extract_json(self.text, native=self.ctx.output_json)

    @cached_property
    def searchable(self) -> str:
        """Text + serialised JSON output (canary / PII scans must not miss structured outputs)."""
        if self.ctx.output_json is None:
            return self.text
        try:
            dumped = json.dumps(self.ctx.output_json, ensure_ascii=False)
        except (TypeError, ValueError):
            dumped = str(self.ctx.output_json)
        return f"{self.text}\n{dumped}"

    @cached_property
    def tool_calls(self) -> list[TraceEventView]:
        return [e for e in self.ctx.events if e.type == TraceEventType.tool_call]

    def tool_name(self, event: TraceEventView) -> str:
        return str((event.attributes or {}).get("tool") or event.name or "")


@dataclass(slots=True)
class RuleOutcome:
    score: float
    passed: bool
    explanation: str
    evidence: list[EvidenceRef] = field(default_factory=list)
    #: Description of the detected error (defaults to the explanation).
    error_description: str | None = None
    misconfigured: bool = False


RuleHandler = Callable[[RuleSpec, OutputView], RuleOutcome]


def _out(text: str, start: int, end: int) -> EvidenceRef:
    return EvidenceRef(excerpt=excerpt(text, start, end), location="output")


def _event_ref(event: TraceEventView, note: str | None = None) -> EvidenceRef:
    return EvidenceRef(
        excerpt=note or one_line(f"{event.type.value} {event.name}", 160),
        trace_event_id=event.id or None,
        trace_event_seq=event.seq,
        location="trace",
    )


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "oui", "vrai")
    return bool(value)


def _str_list(params: dict[str, Any], key: str, *, required: bool = True) -> list[str]:
    value = params.get(key)
    if value is None:
        if required:
            raise RuleConfigError(f"paramètre « {key} » requis")
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str | int | float) for v in value):
        raise RuleConfigError(f"« {key} » doit être une liste de textes")
    items = [str(v) for v in value if str(v).strip()]
    if required and not items:
        raise RuleConfigError(f"« {key} » ne doit pas être vide")
    return items


def _number(params: dict[str, Any], key: str, *, required: bool = True, minimum: float = 0) -> float | None:
    value = params.get(key)
    if value is None:
        if required:
            raise RuleConfigError(f"paramètre « {key} » requis")
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise RuleConfigError(f"« {key} » doit être un nombre")
    try:
        number = float(value)
    except ValueError as exc:
        raise RuleConfigError(f"« {key} » doit être un nombre") from exc
    if math.isnan(number) or number < minimum:
        raise RuleConfigError(f"« {key} » doit être ≥ {fr_number(minimum, 0)}")
    return number


def _compile(pattern: Any, flags: Any) -> re.Pattern[str]:
    if not isinstance(pattern, str) or not pattern:
        raise RuleConfigError("paramètre « pattern » requis")
    if len(pattern) > _MAX_PATTERN_LENGTH:
        raise RuleConfigError("expression régulière trop longue")
    value = 0
    for flag in str(flags or ""):
        if flag not in _FLAG_MAP:
            raise RuleConfigError(f"option d'expression régulière inconnue « {flag} » (i, m, s, x)")
        value |= _FLAG_MAP[flag]
    try:
        return re.compile(pattern, value)
    except re.error as exc:
        raise RuleConfigError(f"expression régulière invalide ({exc})") from exc


# =====================================================================================================
# Rule handlers
# =====================================================================================================


def _json_or_fail(view: OutputView) -> RuleOutcome | None:
    if view.json.ok:
        return None
    return RuleOutcome(
        0.0,
        False,
        f"La sortie ne contient pas de JSON exploitable ({view.json.error or 'JSON introuvable'}).",
        [EvidenceRef(excerpt=one_line(view.text, 200) or "(sortie vide)", location="output")],
    )


def _required_fields(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    fields = _str_list(rule.params, "fields")
    for path in fields:
        try:
            get_path({}, path)
        except JsonPathError as exc:
            raise RuleConfigError(str(exc)) from exc
    failure = _json_or_fail(view)
    if failure:
        failure.explanation = f"Champs requis non vérifiables : {failure.explanation}"
        return failure
    present = [p for p in fields if is_present(view.json.value, p)]
    missing = [p for p in fields if p not in present]
    score = len(present) / len(fields)
    if not missing:
        return RuleOutcome(1.0, True, f"Les {len(fields)} champs requis sont présents ({', '.join(fields)}).")
    return RuleOutcome(
        score,
        False,
        f"{len(present)}/{len(fields)} champs requis présents ; manquants : {', '.join(missing)}.",
        [
            EvidenceRef(excerpt=f"Champ absent ou vide : {p}", location="output")
            for p in missing[:_MAX_EVIDENCE]
        ],
        error_description=f"Champs requis absents de la sortie JSON : {', '.join(missing)}.",
    )


def _json_valid(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    failure = _json_or_fail(view)
    if failure:
        failure.error_description = "La sortie n'est pas un JSON valide."
        return failure
    where = {
        "native": "sortie structurée de l'agent",
        "text": "sortie complète",
        "fence": "bloc ```json``` de la sortie",
        "embedded": "objet JSON inclus dans la sortie",
    }.get(view.json.source, "sortie")
    return RuleOutcome(1.0, True, f"JSON valide ({where}).")


def _json_schema(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    schema = rule.params.get("schema")
    if not isinstance(schema, dict):
        raise RuleConfigError("paramètre « schema » (objet JSON Schema) requis")
    try:
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise RuleConfigError(f"schéma JSON invalide ({exc.message})") from exc
    failure = _json_or_fail(view)
    if failure:
        failure.error_description = "La sortie n'est pas un JSON valide : schéma non vérifiable."
        return failure
    validator = validator_cls(schema)
    errors = sorted(validator.iter_errors(view.json.value), key=lambda e: list(e.absolute_path))
    if not errors:
        return RuleOutcome(1.0, True, "La sortie JSON respecte le schéma attendu.")
    details = []
    for error in errors[:_MAX_EVIDENCE]:
        location = "/".join(str(p) for p in error.absolute_path) or "(racine)"
        details.append(f"{location} : {one_line(error.message, 160)}")
    more = f" (+{len(errors) - _MAX_EVIDENCE})" if len(errors) > _MAX_EVIDENCE else ""
    return RuleOutcome(
        0.0,
        False,
        f"{len(errors)} violation(s) du schéma : {' ; '.join(details)}{more}.",
        [EvidenceRef(excerpt=d, location="output") for d in details],
        error_description=f"Sortie non conforme au schéma JSON ({len(errors)} violation(s)).",
    )


def _regex(rule: RuleSpec, view: OutputView, *, absent: bool) -> RuleOutcome:
    regex = _compile(rule.params.get("pattern"), rule.params.get("flags"))
    matches = list(regex.finditer(view.text))
    shown = f"/{one_line(regex.pattern, 80)}/"
    if absent:
        if not matches:
            return RuleOutcome(1.0, True, f"Motif interdit {shown} absent de la sortie.")
        return RuleOutcome(
            0.0,
            False,
            f"Motif interdit {shown} trouvé {len(matches)} fois dans la sortie.",
            [_out(view.text, m.start(), m.end()) for m in matches[:_MAX_EVIDENCE]],
            error_description=f"La sortie contient un motif interdit ({shown}).",
        )
    if matches:
        return RuleOutcome(
            1.0,
            True,
            f"Motif attendu {shown} trouvé {len(matches)} fois.",
            [_out(view.text, matches[0].start(), matches[0].end())],
        )
    return RuleOutcome(
        0.0,
        False,
        f"Motif attendu {shown} absent de la sortie.",
        error_description=f"La sortie ne respecte pas le motif attendu {shown}.",
    )


def _find_keyword(view: OutputView, keyword: str, case_sensitive: bool) -> int:
    if case_sensitive:
        return view.text.find(keyword)
    index = find_normalized(view.normalized, keyword)
    if index < 0:
        return -1
    # Map back approximately: search case-insensitively in the raw text for the excerpt position.
    raw = view.text.casefold().find(keyword.casefold())
    return raw if raw >= 0 else min(index, max(0, len(view.text) - 1))


def _contains(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    keywords = _str_list(rule.params, "keywords")
    mode = str(rule.params.get("mode") or "all").lower()
    if mode not in ("all", "any"):
        raise RuleConfigError("« mode » doit valoir « all » ou « any »")
    case_sensitive = _bool(rule.params.get("case_sensitive"))
    found: list[str] = []
    evidence: list[EvidenceRef] = []
    for keyword in keywords:
        index = _find_keyword(view, keyword, case_sensitive)
        if index >= 0:
            found.append(keyword)
            if len(evidence) < _MAX_EVIDENCE:
                evidence.append(_out(view.text, index, index + len(keyword)))
    missing = [k for k in keywords if k not in found]
    ratio = len(found) / len(keywords)
    if mode == "any":
        passed = bool(found)
        score = 1.0 if passed else 0.0
        if passed:
            text = f"Au moins un mot-clé attendu est présent ({', '.join(found)})."
        else:
            text = f"Aucun des mots-clés attendus n'est présent ({', '.join(keywords)})."
    else:
        passed = not missing
        score = ratio
        if passed:
            text = f"Les {len(keywords)} mots-clés attendus sont présents."
        else:
            text = (
                f"{len(found)}/{len(keywords)} mots-clés attendus présents ({fr_percent(ratio)}) ; "
                f"absents : {', '.join(missing)}."
            )
    return RuleOutcome(
        score,
        passed,
        text,
        evidence,
        error_description=None if passed else f"Éléments attendus absents : {', '.join(missing)}.",
    )


def _not_contains(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    keywords = _str_list(rule.params, "keywords")
    case_sensitive = _bool(rule.params.get("case_sensitive"))
    hits: list[tuple[str, int]] = []
    for keyword in keywords:
        index = _find_keyword(view, keyword, case_sensitive)
        if index >= 0:
            hits.append((keyword, index))
    if not hits:
        return RuleOutcome(1.0, True, f"Aucun des {len(keywords)} termes interdits n'apparaît.")
    names = ", ".join(k for k, _ in hits)
    return RuleOutcome(
        0.0,
        False,
        f"{len(hits)} terme(s) interdit(s) présent(s) dans la sortie : {names}.",
        [_out(view.text, i, i + len(k)) for k, i in hits[:_MAX_EVIDENCE]],
        error_description=f"La sortie contient des termes interdits : {names}.",
    )


_ATX_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*#*\s*$", re.MULTILINE)
_SETEXT_HEADING = re.compile(r"^(?P<title>[^\n]+)\n\s{0,3}(?:=+|-{3,})\s*$", re.MULTILINE)
_BOLD_HEADING = re.compile(r"^\s*(?:\d+[.)]\s*)?\*\*(?P<title>[^*\n]+?)\*\*\s*:?\s*$", re.MULTILINE)


def markdown_headings(text: str) -> list[tuple[str, int]]:
    """Headings of a Markdown document: ATX (``## Title``), setext and bold-only lines."""
    found: list[tuple[str, int]] = []
    for pattern in (_ATX_HEADING, _SETEXT_HEADING, _BOLD_HEADING):
        for match in pattern.finditer(text):
            found.append((match.group("title").strip().strip("*_ "), match.start()))
    return sorted(found, key=lambda h: h[1])


def _sections_present(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    sections = _str_list(rule.params, "sections")
    headings = markdown_headings(view.text)
    normalized = [(normalize(title), pos, title) for title, pos in headings]
    present: list[str] = []
    evidence: list[EvidenceRef] = []
    for section in sections:
        target = normalize(section)
        hit = next(((pos, title) for norm, pos, title in normalized if target and target in norm), None)
        if hit is not None:
            present.append(section)
            if len(evidence) < _MAX_EVIDENCE:
                evidence.append(EvidenceRef(excerpt=f"Titre : {hit[1]}", location="output"))
    missing = [s for s in sections if s not in present]
    score = len(present) / len(sections)
    if not missing:
        return RuleOutcome(1.0, True, f"Les {len(sections)} sections attendues sont présentes.", evidence)
    return RuleOutcome(
        score,
        False,
        f"{len(present)}/{len(sections)} sections présentes ({len(headings)} titres détectés) ; "
        f"absentes : {', '.join(missing)}.",
        evidence,
        error_description=f"Sections attendues absentes : {', '.join(missing)}.",
    )


def find_citations(text: str, pattern: str | None = None, flags: str | None = None) -> list[re.Match[str]]:
    if pattern:
        patterns = [_compile(pattern, flags)]
    else:
        patterns = [re.compile(p, re.IGNORECASE) for p in DEFAULT_CITATION_PATTERNS]
    matches: list[re.Match[str]] = []
    taken: list[tuple[int, int]] = []
    for regex in patterns:
        for match in regex.finditer(text):
            if any(match.start() < end and start < match.end() for start, end in taken):
                continue
            taken.append((match.start(), match.end()))
            matches.append(match)
    return sorted(matches, key=lambda m: m.start())


def _citation_required(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    minimum = int(_number(rule.params, "min", required=False, minimum=1) or 1)
    pattern = rule.params.get("pattern")
    matches = find_citations(view.text, str(pattern) if pattern else None, rule.params.get("flags"))
    count = len(matches)
    evidence = [_out(view.text, m.start(), m.end()) for m in matches[:_MAX_EVIDENCE]]
    if count >= minimum:
        return RuleOutcome(1.0, True, f"{count} citation(s) trouvée(s) (minimum {minimum}).", evidence)
    return RuleOutcome(
        count / minimum,
        False,
        f"{count} citation(s) trouvée(s) pour un minimum de {minimum}.",
        evidence,
        error_description=f"Citations insuffisantes : {count} pour {minimum} attendue(s).",
    )


def context_documents(context: dict[str, Any]) -> list[dict[str, Any]]:
    documents = (context or {}).get("documents") or []
    return [d for d in documents if isinstance(d, dict)] if isinstance(documents, list) else []


def cited_documents(text: str, documents: Sequence[dict[str, Any]]) -> list[tuple[dict[str, Any], int]]:
    """Documents whose id or title appears in ``text`` (case/accent-insensitive) with the position."""
    norm = normalize(text)
    cited: list[tuple[dict[str, Any], int]] = []
    for doc in documents:
        position = -1
        for key in ("id", "title", "source"):
            value = str(doc.get(key) or "").strip()
            if len(value) < 2:
                continue
            position = find_normalized(norm, value)
            if position >= 0:
                break
        if position >= 0:
            cited.append((doc, position))
    return cited


def _source_present(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    minimum = int(_number(rule.params, "min", required=False, minimum=1) or 1)
    documents = context_documents(view.ctx.scenario.context)
    if not documents:
        return RuleOutcome(
            1.0, True, "Aucun document dans le contexte du scénario : règle non applicable (réussie)."
        )
    required = min(minimum, len(documents))
    cited = cited_documents(view.text, documents)
    labels = [str(d.get("id") or d.get("title")) for d, _ in cited]
    evidence = [
        EvidenceRef(excerpt=f"Document cité : {label}", location="output") for label in labels[:_MAX_EVIDENCE]
    ]
    if len(cited) >= required:
        return RuleOutcome(
            1.0,
            True,
            f"{len(cited)}/{len(documents)} document(s) du contexte cité(s) : {', '.join(labels)}.",
            evidence,
        )
    return RuleOutcome(
        len(cited) / required,
        False,
        f"{len(cited)} document(s) du contexte cité(s) pour un minimum de {required}"
        f"{' : ' + ', '.join(labels) if labels else ''}.",
        evidence,
        error_description=f"La sortie ne cite pas assez les sources du contexte ({len(cited)}/{required}).",
    )


def _no_pii(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    raw_types = _str_list(rule.params, "types", required=False)
    try:
        types = {PiiType(t.upper()) for t in raw_types} or set(PiiType)
    except ValueError as exc:
        raise RuleConfigError(f"type de donnée personnelle inconnu ({exc})") from exc
    allow = {normalize(a) for a in _str_list(rule.params, "allow", required=False)}
    entities = [
        e for e in pii.detect_pii(view.searchable) if e.type in types and normalize(e.text) not in allow
    ]
    if not entities:
        scope = "tous types" if not raw_types else ", ".join(sorted(t.value for t in types))
        return RuleOutcome(1.0, True, f"Aucune donnée personnelle détectée ({scope}).")
    counts: dict[str, int] = {}
    for entity in entities:
        label = pii.PII_TYPE_LABELS[entity.type]
        counts[label] = counts.get(label, 0) + 1
    summary = ", ".join(f"{n} {label}" for label, n in counts.items())
    evidence = [
        EvidenceRef(excerpt=f"{pii.PII_TYPE_LABELS[e.type]} : {pii.mask(e.text)}", location="output")
        for e in entities[:_MAX_EVIDENCE]
    ]
    return RuleOutcome(
        0.0,
        False,
        f"{len(entities)} donnée(s) personnelle(s) détectée(s) dans la sortie : {summary}.",
        evidence,
        error_description=f"Données personnelles présentes dans la sortie : {summary}.",
    )


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right if isinstance(left, bool) and isinstance(right, bool) else False
    if isinstance(left, int | float) and isinstance(right, int | float):
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-12)
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right, strict=True))
    return bool(left == right)


def _expected_value(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    path = rule.params.get("path")
    if not isinstance(path, str) or not path.strip():
        raise RuleConfigError("paramètre « path » requis")
    if "value" not in rule.params:
        raise RuleConfigError("paramètre « value » requis")
    expected = rule.params.get("value")
    try:
        get_path({}, path)
    except JsonPathError as exc:
        raise RuleConfigError(str(exc)) from exc
    failure = _json_or_fail(view)
    if failure:
        failure.error_description = f"Valeur attendue en « {path} » non vérifiable (sortie non JSON)."
        return failure
    lookup = get_path(view.json.value, path)
    shown_expected = one_line(json.dumps(expected, ensure_ascii=False), 120)
    if not lookup.found:
        return RuleOutcome(
            0.0,
            False,
            f"Chemin « {path} » absent de la sortie (valeur attendue {shown_expected}).",
            error_description=f"Champ « {path} » absent (valeur attendue {shown_expected}).",
        )
    shown_actual = one_line(json.dumps(lookup.value, ensure_ascii=False, default=str), 120)
    if _json_equal(lookup.value, expected):
        return RuleOutcome(1.0, True, f"« {path} » vaut bien {shown_expected}.")
    return RuleOutcome(
        0.0,
        False,
        f"« {path} » vaut {shown_actual} au lieu de {shown_expected}.",
        [EvidenceRef(excerpt=f"{path} = {shown_actual}", location="output")],
        error_description=f"Valeur inattendue pour « {path} » : {shown_actual} (attendu {shown_expected}).",
    )


def _length(rule: RuleSpec, view: OutputView, *, maximum: bool) -> RuleOutcome:
    max_words = _number(rule.params, "words", required=False, minimum=0)
    max_chars = _number(rule.params, "chars", required=False, minimum=0)
    if max_words is None and max_chars is None:
        raise RuleConfigError("paramètre « words » ou « chars » requis")
    measures: list[tuple[str, float, float]] = []
    if max_words is not None:
        measures.append(("mots", float(word_count(view.text)), max_words))
    if max_chars is not None:
        measures.append(("caractères", float(len(view.text)), max_chars))
    parts: list[str] = []
    scores: list[float] = []
    ok = True
    for unit, actual, limit in measures:
        if maximum:
            good = actual <= limit
            score = 1.0 if good else (limit / actual if actual > 0 else 0.0)
            parts.append(f"{int(actual)} {unit} (maximum {int(limit)})")
        else:
            good = actual >= limit
            score = 1.0 if good else (actual / limit if limit > 0 else 1.0)
            parts.append(f"{int(actual)} {unit} (minimum {int(limit)})")
        ok = ok and good
        scores.append(max(0.0, min(1.0, score)))
    summary = " ; ".join(parts)
    kind = "maximale" if maximum else "minimale"
    if ok:
        return RuleOutcome(1.0, True, f"Longueur {kind} respectée : {summary}.")
    return RuleOutcome(
        min(scores),
        False,
        f"Longueur {kind} non respectée : {summary}.",
        error_description=f"Longueur {kind} non respectée : {summary}.",
    )


def _tool_events(rule: RuleSpec, view: OutputView) -> tuple[str, list[TraceEventView]]:
    tool = rule.params.get("tool")
    if not isinstance(tool, str) or not tool.strip():
        raise RuleConfigError("paramètre « tool » requis")
    target = tool.strip()
    return target, [e for e in view.tool_calls if view.tool_name(e) == target]


def _tool_called(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    tool, calls = _tool_events(rule, view)
    minimum = int(_number(rule.params, "min", required=False, minimum=1) or 1)
    evidence = [_event_ref(e) for e in calls[:_MAX_EVIDENCE]]
    if len(calls) >= minimum:
        return RuleOutcome(
            1.0, True, f"Outil « {tool} » appelé {len(calls)} fois (minimum {minimum}).", evidence
        )
    return RuleOutcome(
        len(calls) / minimum,
        False,
        f"Outil « {tool} » appelé {len(calls)} fois pour un minimum de {minimum} "
        f"({len(view.tool_calls)} appel(s) d'outils au total).",
        evidence,
        error_description=f"L'outil attendu « {tool} » n'a pas été (suffisamment) utilisé.",
    )


def _tool_not_called(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    tool, calls = _tool_events(rule, view)
    if not calls:
        return RuleOutcome(1.0, True, f"Outil interdit « {tool} » non appelé.")
    return RuleOutcome(
        0.0,
        False,
        f"Outil interdit « {tool} » appelé {len(calls)} fois.",
        [_event_ref(e) for e in calls[:_MAX_EVIDENCE]],
        error_description=f"Appel d'un outil interdit : « {tool} ».",
    )


def _max_tool_calls(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    maximum = int(_number(rule.params, "max", minimum=0) or 0)
    count = len(view.tool_calls)
    if count <= maximum:
        return RuleOutcome(1.0, True, f"{count} appel(s) d'outils (maximum {maximum}).")
    return RuleOutcome(
        maximum / count if count else 0.0,
        False,
        f"{count} appels d'outils pour un maximum de {maximum}.",
        [_event_ref(e) for e in view.tool_calls[maximum : maximum + _MAX_EVIDENCE]],
        error_description=f"Trop d'appels d'outils : {count} (maximum {maximum}).",
    )


def _max_latency(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    limit = float(_number(rule.params, "ms", minimum=1) or 1)
    latency = view.ctx.latency_ms
    if latency is None:
        return RuleOutcome(1.0, True, "Latence non mesurée : règle non applicable (réussie).")
    if latency <= limit:
        return RuleOutcome(1.0, True, f"Latence totale {int(latency)} ms (maximum {int(limit)} ms).")
    return RuleOutcome(
        limit / latency,
        False,
        f"Latence totale {int(latency)} ms supérieure au maximum de {int(limit)} ms.",
        error_description=f"Délai dépassé : {int(latency)} ms pour {int(limit)} ms autorisées.",
    )


def _max_cost(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    limit = float(_number(rule.params, "max", minimum=0) or 0)
    cost = view.ctx.estimated_cost
    if cost is None:
        return RuleOutcome(1.0, True, "Coût non mesuré : règle non applicable (réussie).")
    if cost <= limit:
        return RuleOutcome(1.0, True, f"Coût estimé {fr_number(cost, 4)} (maximum {fr_number(limit, 4)}).")
    return RuleOutcome(
        limit / cost if cost > 0 else 0.0,
        False,
        f"Coût estimé {fr_number(cost, 4)} supérieur au maximum de {fr_number(limit, 4)}.",
        error_description=f"Budget dépassé : coût {fr_number(cost, 4)} pour {fr_number(limit, 4)} autorisé.",
    )


def _mask_canary(value: str) -> str:
    return f"{value[: len(CANARY_PREFIX) + 5]}…"


def _no_canary(rule: RuleSpec, view: OutputView) -> RuleOutcome:
    text = view.searchable
    matches = list(_CANARY_PATTERN.finditer(text))
    own = view.ctx.scenario.canary
    if not matches:
        return RuleOutcome(1.0, True, "Aucun canari de benchmark dans la sortie.")
    own_hit = bool(own) and any(m.group() == own for m in matches)
    detail = "le canari de ce scénario" if own_hit else f"{len(matches)} canari(s) de benchmark"
    return RuleOutcome(
        0.0,
        False,
        f"La sortie contient {detail} ({CANARY_PREFIX}-…) : contamination probable du modèle ou de l'agent.",
        [
            EvidenceRef(excerpt=f"Canari détecté : {_mask_canary(m.group())}", location="output")
            for m in matches[:3]
        ],
        error_description=(
            f"Contamination : {detail} présent dans la sortie (contenu de scénario privé vu par l'agent)."
        ),
    )


RULE_HANDLERS: dict[RuleType, RuleHandler] = {
    RuleType.required_fields: _required_fields,
    RuleType.json_valid: _json_valid,
    RuleType.json_schema: _json_schema,
    RuleType.regex_match: lambda r, v: _regex(r, v, absent=False),
    RuleType.regex_absent: lambda r, v: _regex(r, v, absent=True),
    RuleType.contains: _contains,
    RuleType.not_contains: _not_contains,
    RuleType.sections_present: _sections_present,
    RuleType.citation_required: _citation_required,
    RuleType.source_present: _source_present,
    RuleType.no_pii: _no_pii,
    RuleType.expected_value: _expected_value,
    RuleType.max_length: lambda r, v: _length(r, v, maximum=True),
    RuleType.min_length: lambda r, v: _length(r, v, maximum=False),
    RuleType.tool_called: _tool_called,
    RuleType.tool_not_called: _tool_not_called,
    RuleType.max_tool_calls: _max_tool_calls,
    RuleType.max_latency: _max_latency,
    RuleType.max_cost: _max_cost,
    RuleType.no_canary: _no_canary,
}


# =====================================================================================================
# Public API
# =====================================================================================================


def rule_criterion_key(rule: RuleSpec) -> str:
    return rule.criterion_key or RULE_DEFAULTS[RuleType(rule.type)][0]


def rule_error_type(rule: RuleSpec) -> str:
    default = RULE_DEFAULTS[RuleType(rule.type)][1]
    return str(rule.error_type or default or BuiltinErrorType.POLICY_VIOLATION)


def rule_severity(rule: RuleSpec) -> ErrorSeverity:
    if RuleType(rule.type) == RuleType.no_canary:
        return ErrorSeverity.critical
    return ErrorSeverity(rule.severity)


def criterion_dimension(key: str, criteria: Iterable[CriterionSpec] = ()) -> Dimension:
    for criterion in criteria:
        if criterion.key == key:
            return Dimension(criterion.dimension)
    if key in CRITERIA_BY_KEY:
        return CRITERIA_BY_KEY[key].dimension
    prefix = key.split(".", 1)[0]
    try:
        return Dimension(prefix)
    except ValueError:
        return Dimension.quality


def validate_rule(rule: RuleSpec) -> list[str]:
    """French validation messages for a rule's parameters (empty list = valid).

    Runs the rule against an empty output: parameter errors surface as :class:`RuleConfigError`.
    """
    problems: list[str] = []
    try:
        rule_type = RuleType(rule.type)
    except ValueError:
        return [f"type de règle inconnu « {rule.type} »"]
    if not str(rule.id or "").strip():
        problems.append("identifiant de règle requis")
    if rule.weight < 0 or math.isnan(rule.weight):
        problems.append("le poids d'une règle doit être ≥ 0")
    try:
        ErrorSeverity(rule.severity)
    except ValueError:
        problems.append(f"gravité inconnue « {rule.severity} »")
    probe = EvaluationContext(
        run_id="validation",
        scenario=ScenarioSpec(
            scenario_id="",
            scenario_version_id="",
            slug="",
            name="",
            version=0,
            category="",
            difficulty=Difficulty.medium,
            visibility=ScenarioVisibility.public,
        ),
        agent=AgentSpec(
            agent_id="",
            agent_version_id="",
            agent_name="",
            agent_slug="",
            version="",
            adapter_kind=AdapterKind.mock,
        ),
        config=ScoreConfig(config_id="", key="", version=0, name="", dimension_weights={}),
        output_text="",
        latency_ms=0.0,
        estimated_cost=0.0,
    )
    try:
        RULE_HANDLERS[rule_type](rule, OutputView(probe))
    except RuleConfigError as exc:
        problems.append(str(exc))
    except Exception as exc:  # defensive: any crash on empty output is a configuration problem
        problems.append(f"paramètres invalides ({type(exc).__name__})")
    return problems


def evaluate_rule(
    ctx: EvaluationContext, rule: RuleSpec, *, view: OutputView | None = None
) -> EvaluationResult:
    view = view or OutputView(ctx)
    rule_type = RuleType(rule.type)
    try:
        outcome = RULE_HANDLERS[rule_type](rule, view)
    except RuleConfigError as exc:
        outcome = RuleOutcome(0.0, False, f"{MISCONFIGURED_PREFIX} : {exc}.", misconfigured=True)
    criterion_key = rule_criterion_key(rule)
    dimension = (
        Dimension(rule.dimension)
        if rule.dimension
        else criterion_dimension(criterion_key, [*ctx.scenario.criteria, *ctx.config.criteria])
    )
    explanation = outcome.explanation.strip()
    if rule.description and not outcome.misconfigured:
        explanation = f"{rule.description.strip().rstrip('.')} — {explanation}"
    if ctx.run_error and not ctx.output_text:
        explanation = f"{explanation} (exécution en échec : sortie vide)"
    errors: list[DetectedError] = []
    if not outcome.passed and not outcome.misconfigured:
        errors.append(
            DetectedError(
                type=rule_error_type(rule),
                severity=rule_severity(rule),
                description=(outcome.error_description or outcome.explanation).strip(),
                evidence=list(outcome.evidence[:3]),
                criterion_key=criterion_key,
            )
        )
    return EvaluationResult(
        evaluator_kind=EvaluatorKind.rule,
        evaluator_key=rule.id,
        criterion_key=criterion_key,
        dimension=dimension,
        raw_score=round(max(0.0, min(1.0, outcome.score)), 6),
        scale_min=0.0,
        scale_max=1.0,
        explanation=explanation or "Règle évaluée.",
        confidence=1.0,
        evidence=outcome.evidence,
        errors=errors,
        passed=outcome.passed,
        raw_response={"rule_type": rule_type.value, "misconfigured": outcome.misconfigured},
    )


def evaluate_rules(ctx: EvaluationContext, rules: Sequence[RuleSpec]) -> list[EvaluationResult]:
    """Evaluate every rule (deterministic, free). Rule ids are made unique (``R1``, ``R1#2``)."""
    view = OutputView(ctx)
    results: list[EvaluationResult] = []
    seen: dict[str, int] = {}
    for rule in rules:
        result = evaluate_rule(ctx, rule, view=view)
        count = seen.get(rule.id, 0) + 1
        seen[rule.id] = count
        if count > 1:
            result.evaluator_key = f"{rule.id}#{count}"
        results.append(result)
    return results

"""Benchmark contamination checks of an agent version (docs/ARCHITECTURE.md §3.3, §6.1).

An agent version is *contaminated* when what it is given at build time (system prompt, tool
descriptions, adapter configuration) contains material of hidden scenarios:

* a **canary** ``FORGE-CANARY-…`` of a private or fresh scenario version;
* a long passage (≥ :data:`DEFAULT_NGRAM` consecutive words) of the expected output of a private
  scenario.

Warnings never quote the private material itself (they are shown to non-maintainers): only the
location, the scenario reference and the size of the overlap.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from forge.domain.versioning import CANARY_PREFIX

DEFAULT_NGRAM = 12
CANARY_RE = re.compile(rf"{re.escape(CANARY_PREFIX)}-[0-9a-fA-F]{{8,64}}")
_WORD_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ScenarioRef:
    scenario_id: str
    slug: str
    visibility: str


@dataclass(frozen=True, slots=True)
class CanaryRef:
    canary: str
    scenario: ScenarioRef


@dataclass(frozen=True, slots=True)
class PrivateOutputRef:
    text: str
    scenario: ScenarioRef


def _normalize_word(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def words(text: str) -> list[str]:
    return [_normalize_word(w) for w in _WORD_RE.findall(text or "")]


def flatten_text(value: Any) -> str:
    """Every string of a JSON value, one per line (expected outputs may be structured)."""
    parts: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, Mapping):
            for v in item.values():
                walk(v)
        elif isinstance(item, list | tuple):
            for v in item:
                walk(v)
        elif item is not None and not isinstance(item, bool):
            parts.append(str(item))

    walk(value)
    return "\n".join(parts)


def agent_texts(
    *, system_prompt: str, tools: Iterable[Mapping[str, Any]], adapter_config: Mapping[str, Any]
) -> dict[str, str]:
    """Locations checked on an agent version → text."""
    texts: dict[str, str] = {"system_prompt": system_prompt or ""}
    for index, tool in enumerate(tools or []):
        name = str(tool.get("name") or index)
        description = str(tool.get("description") or "")
        parameters = tool.get("parameters")
        texts[f"tools.{name}"] = description + "\n" + flatten_text(parameters)
    if adapter_config:
        texts["adapter_config"] = (
            flatten_text(adapter_config) + "\n" + json.dumps(adapter_config, default=str)
        )
    return {k: v for k, v in texts.items() if v.strip()}


def _longest_run(text_words: list[str], ngrams: set[tuple[str, ...]], n: int) -> int:
    """Length (in words) of the longest run of consecutive matching n-grams (0 = no overlap)."""
    best = 0
    run_start: int | None = None
    for i in range(len(text_words) - n + 1):
        if tuple(text_words[i : i + n]) in ngrams:
            if run_start is None:
                run_start = i
            best = max(best, i - run_start + n)
        else:
            run_start = None
    return best


def check_contamination(
    texts: Mapping[str, str],
    *,
    canaries: Iterable[CanaryRef] = (),
    private_outputs: Iterable[PrivateOutputRef] = (),
    ngram: int = DEFAULT_NGRAM,
) -> list[dict[str, Any]]:
    """Return contamination warnings (JSON dicts stored in ``agent_versions.contamination``)."""
    warnings: list[dict[str, Any]] = []
    by_canary = {c.canary.lower(): c.scenario for c in canaries}
    for location, text in texts.items():
        reported: set[str] = set()
        for match in CANARY_RE.finditer(text or ""):
            scenario = by_canary.get(match.group(0).lower())
            if scenario is None or scenario.scenario_id in reported:
                continue
            reported.add(scenario.scenario_id)
            warnings.append(
                {
                    "type": "canary",
                    "severity": "critical",
                    "location": location,
                    "scenario_id": scenario.scenario_id,
                    "scenario_slug": scenario.slug,
                    "visibility": scenario.visibility,
                    "message": (
                        f"Canari du scénario {scenario.visibility} « {scenario.slug} » trouvé dans "
                        f"{location} : l'agent a été exposé au contenu du benchmark."
                    ),
                }
            )
    outputs = list(private_outputs)
    if not outputs:
        return warnings
    text_words = {location: words(text) for location, text in texts.items()}
    overlaps: dict[tuple[str, str], dict[str, Any]] = {}
    for output in outputs:
        output_words = words(output.text)
        if len(output_words) < ngram:
            continue
        grams = {tuple(output_words[i : i + ngram]) for i in range(len(output_words) - ngram + 1)}
        for location, tw in text_words.items():
            if len(tw) < ngram:
                continue
            overlap = _longest_run(tw, grams, ngram)
            key = (location, output.scenario.scenario_id)
            if overlap >= ngram and overlap > int(overlaps.get(key, {}).get("overlap_words", 0)):
                overlaps[key] = {
                    "type": "ngram_overlap",
                    "severity": "high",
                    "location": location,
                    "scenario_id": output.scenario.scenario_id,
                    "scenario_slug": output.scenario.slug,
                    "visibility": output.scenario.visibility,
                    "overlap_words": overlap,
                    "message": (
                        f"{location} reprend {overlap} mots consécutifs du résultat attendu du "
                        f"scénario privé « {output.scenario.slug} »."
                    ),
                }
    warnings.extend(overlaps.values())
    return warnings

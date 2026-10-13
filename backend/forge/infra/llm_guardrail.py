"""LLM guardrail: nothing above the classification ceiling leaves FORGE for an LLM (same triplet as ORBIT).

* ``FORGE_LLM_MAX_CLASSIFICATION`` (default C1) is the highest level sent to an LLM; ``FORGE_LLM_LOCAL=true``
  (self-hosted models only) lifts it. An unknown level counts as C3.
* Judges fall back to the deterministic ``heuristic`` judge with a visible warning; the agent adapters and
  the feedback synthesis refuse the call. Every skip is counted in ``forge_llm_guardrail_skips_total``.
"""

from __future__ import annotations

import dataclasses

from forge.config import settings
from forge.domain.classification import MAX_LEVEL, parse_level
from forge.domain.enums import JudgeProvider, classification_code
from forge.domain.types import JudgeSpec
from forge.infra.observability.metrics import record_llm_guardrail_skip

REASON_CLASSIFICATION = "classification"


def ceiling() -> int:
    """Highest classification level that may be sent to an LLM."""
    return MAX_LEVEL if settings.llm_local else int(settings.llm_max_classification)


def allows(classification: int | None) -> bool:
    """``True`` when content of this level may be sent to an LLM (unknown level ⇒ treated as C3)."""
    level = parse_level(classification)
    return (MAX_LEVEL if level is None else level) <= ceiling()


def record_skip(reason: str = REASON_CLASSIFICATION) -> None:
    record_llm_guardrail_skip(reason)


def skip_message(level: int | None, what: str) -> str:
    parsed = parse_level(level)
    code = classification_code(MAX_LEVEL if parsed is None else parsed)
    return (
        f"{what} : contenu {code} au-dessus du plafond LLM (C{ceiling()}, FORGE_LLM_MAX_CLASSIFICATION) — "
        "rien n'a été envoyé au fournisseur"
    )


def judge_or_heuristic(judge: JudgeSpec, level: int | None) -> tuple[JudgeSpec, str | None]:
    """``judge`` itself when its provider may see ``level``, else the heuristic judge + a warning."""
    if JudgeProvider(judge.provider) == JudgeProvider.heuristic or allows(level):
        return judge, None
    record_skip()
    fallback = dataclasses.replace(
        judge, provider=JudgeProvider.heuristic, credential_id=None, base_url=None, credentials={}
    )
    return fallback, skip_message(level, f"Juge {judge.ref} ignoré (repli heuristic)")

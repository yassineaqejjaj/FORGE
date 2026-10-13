"""LLM guardrail: ceiling, unknown level, local lift, judge fallback."""

from __future__ import annotations

import pytest

from forge.config import settings
from forge.domain.enums import JudgeProvider
from forge.infra import llm_guardrail as guardrail
from forge.infra.observability.metrics import LLM_GUARDRAIL_SKIPS_TOTAL
from tests.unit.test_judges import judge


def skips() -> float:
    return LLM_GUARDRAIL_SKIPS_TOTAL.labels(reason="classification")._value.get()


def test_default_ceiling_is_c1_and_unknown_is_c3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_max_classification", 1)
    monkeypatch.setattr(settings, "llm_local", False)
    assert guardrail.ceiling() == 1
    assert [guardrail.allows(level) for level in (0, 1, 2, 3)] == [True, True, False, False]
    assert not guardrail.allows(None) and not guardrail.allows("???")  # type: ignore[arg-type]


def test_ceiling_is_configurable_and_local_lifts_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_max_classification", 2)
    monkeypatch.setattr(settings, "llm_local", False)
    assert guardrail.allows(2) and not guardrail.allows(3)
    monkeypatch.setattr(settings, "llm_local", True)
    assert guardrail.ceiling() == 3 and guardrail.allows(3)


def test_judge_above_the_ceiling_becomes_the_heuristic_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_max_classification", 1)
    monkeypatch.setattr(settings, "llm_local", False)
    external = judge(credential_id="cred", base_url="https://llm.test/v1")
    before = skips()
    same, warning = guardrail.judge_or_heuristic(external, 1)
    assert same is external and warning is None and skips() == before
    fallback, warning = guardrail.judge_or_heuristic(external, 3)
    assert fallback.provider == JudgeProvider.heuristic and fallback.credential_id is None
    assert fallback.ref == external.ref and fallback.base_url is None
    assert warning and "C3" in warning and "j@v2" in warning and skips() == before + 1
    heuristic = judge(JudgeProvider.heuristic)
    assert guardrail.judge_or_heuristic(heuristic, 3) == (heuristic, None)  # nothing to protect

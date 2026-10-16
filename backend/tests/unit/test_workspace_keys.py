"""Workspace-aware keys: caches, limiters and dedupe keys never cross workspaces (ADR 001 §9.5)."""

from __future__ import annotations

import hashlib
import uuid

from forge.domain.hashing import canonical_json
from forge.domain.judges.cache import judge_cache_key
from forge.infra.models import ORION_DEFAULT_WORKSPACE_ID
from forge.infra.workspace_scope import scope_token, scoped_key

OTHER = uuid.UUID("11111111-2222-4333-8444-555555555555")


def test_the_default_workspace_keeps_its_historical_keys() -> None:
    assert scoped_key(None, "agent:x") == "agent:x"
    assert scoped_key(ORION_DEFAULT_WORKSPACE_ID, "agent:x") == "agent:x"
    assert scope_token(ORION_DEFAULT_WORKSPACE_ID) == "" and scope_token(None) == ""


def test_another_workspace_gets_its_own_key_space() -> None:
    assert scoped_key(OTHER, "agent:x") == f"ws:{OTHER}:agent:x"
    assert scoped_key(OTHER, "agent:x") != scoped_key(uuid.uuid4(), "agent:x")


def _key(scope: str = "") -> str:
    return judge_cache_key(
        judge_content_hash="j", scenario_content_hash="s", output_text="out", output_json=None,
        trace_digest="t", criteria_keys=["quality.accuracy"], scope=scope,
    )  # fmt: skip


def test_judge_cache_key_is_unchanged_for_the_default_workspace() -> None:
    legacy = {
        "judge": "j", "scenario": "s", "output_text": "out", "output_json": None, "trace": "t",
        "criteria": ["quality.accuracy"],
    }  # fmt: skip
    assert _key() == "judge:" + hashlib.sha256(canonical_json(legacy).encode("utf-8")).hexdigest()


def test_judge_cache_never_crosses_workspaces() -> None:
    assert _key(str(OTHER)) != _key()
    assert _key(str(OTHER)) != _key(str(uuid.uuid4()))

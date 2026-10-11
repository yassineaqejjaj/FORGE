"""ORION links of a run: the ORBIT snapshot it used, the release that shipped the agent, and the manifest
its producer reported. Shared by observed runs (``POST /runs/observed``) and ad hoc runs created on behalf of
a production execution (``POST /runs``)."""

from __future__ import annotations

from typing import Any

from forge.infra.models import EvaluationRun


def snapshot_of(manifest: dict[str, Any] | None) -> str | None:
    """``context.snapshot_id`` of a reported run manifest (NOVA ``domain/manifest.py``), when present."""
    context = (manifest or {}).get("context")
    value = context.get("snapshot_id") if isinstance(context, dict) else None
    return value if isinstance(value, str) and value else None


def release_of(manifest: dict[str, Any] | None) -> str | None:
    value = (manifest or {}).get("release_id")
    return value if isinstance(value, str) and value else None


def apply_links(
    run: EvaluationRun,
    *,
    context_snapshot_id: str | None,
    release_id: str | None,
    manifest: dict[str, Any] | None,
) -> None:
    """Explicit values win over the ones read from the manifest."""
    run.context_snapshot_id = context_snapshot_id or snapshot_of(manifest)
    run.release_id = release_id or release_of(manifest)
    run.source_manifest = manifest

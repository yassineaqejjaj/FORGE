"""Judge cache keys (docs/ARCHITECTURE.md §7.3).

``key = sha256(judge.content_hash, scenario.content_hash, output, trace digest, criteria list)``: the
same judge version on the same scenario version, output and trace, for the same criteria, reuses
the stored answer (``cached=true``, cost 0).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from forge.domain.hashing import canonical_json
from forge.domain.types import TraceEventView


def trace_digest(events: Sequence[TraceEventView]) -> str:
    """Digest of the trace content seen by judges (ids and timings excluded: they vary per run)."""
    items = [
        {
            "seq": e.seq,
            "type": e.type,
            "name": e.name,
            "status": e.status,
            "input": e.input,
            "output": e.output,
            "attributes": {k: v for k, v in (e.attributes or {}).items() if k not in ("span_id", "trace_id")},
        }
        for e in sorted(events, key=lambda e: e.seq)
    ]
    return hashlib.sha256(canonical_json(items).encode("utf-8")).hexdigest()


def judge_cache_key(
    *,
    judge_content_hash: str,
    scenario_content_hash: str,
    output_text: str | None,
    output_json: Any,
    trace_digest: str,
    criteria_keys: Sequence[str],
) -> str:
    payload = {
        "judge": judge_content_hash,
        "scenario": scenario_content_hash,
        "output_text": output_text or "",
        "output_json": output_json,
        "trace": trace_digest,
        "criteria": list(criteria_keys),
    }
    return "judge:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

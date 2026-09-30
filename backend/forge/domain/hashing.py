"""Canonical JSON hashing: every versioned object is content-addressed (docs/ARCHITECTURE.md §6.1)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from forge.domain.types import to_dict


def canonical_json(value: Any) -> str:
    """Deterministic JSON (sorted keys, no whitespace, dataclasses/enums/datetimes converted)."""
    return json.dumps(to_dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(value: Any) -> str:
    """``sha256:<hex>`` of the canonical JSON of ``value``."""
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def short_hash(value: Any, length: int = 12) -> str:
    return content_hash(value).removeprefix("sha256:")[:length]

"""ORBIT wire formats read by the context providers (fixtures serialized from the real ORBIT schemas)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from forge.services.context_providers import _merge, orbit_context_hash, orbit_documents

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "orbit"


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_context_package_items_keep_excerpt_and_provenance() -> None:
    package = fixture("context_package.json")
    documents = orbit_documents(package)
    assert [d["content"] for d in documents] == [i["excerpt"] for i in package["items"]]
    first, memory, restricted = documents
    assert first["classification"] == 1 and first["citation"] == "S1" and first["version"] == 2
    assert first["document_id"] == package["items"][0]["document_id"] and first["uri"] == "x"
    assert first["source"] == "document" and first["id"] == package["items"][0]["id"]
    assert memory["memory_item_id"] == package["items"][1]["memory_item_id"]
    assert memory["memory_kind"] == "decision" and memory["classification"] == 2
    assert restricted["classification"] == 3


def test_excluded_items_are_never_injected() -> None:
    package = fixture("context_package.json")
    assert package["excluded"]
    assert len(orbit_documents(package)) == len(package["items"])


def test_snapshot_items_read_excerpt_and_skip_forgotten() -> None:
    snapshot = fixture("snapshot.json")
    documents = orbit_documents(snapshot)
    assert [d["id"] for d in documents] == ["c1", "m1"]
    assert all(d["content"] for d in documents) and "oublié" not in json.dumps(documents, ensure_ascii=False)
    # Snapshot items carry no classification: none is invented here (callers fall back, fail-closed).
    assert all("classification" not in d for d in documents)
    assert documents[0]["source"] == "document" and documents[1]["memory_kind"] == "decision"


def test_legacy_shapes_still_read() -> None:
    assert orbit_documents({"documents": [{"id": "orbit-1", "title": "Note", "content": "Contexte."}]}) == [
        {"id": "orbit-1", "title": "Note", "content": "Contexte.", "source": "orbit"}
    ]
    assert orbit_documents({"items": [{"id": "m1", "text": "Mémoire"}]})[0]["content"] == "Mémoire"
    assert orbit_documents({"items": ["brut"]})[0]["content"] == "brut"


def test_snapshot_content_becomes_orbit_context() -> None:
    snapshot = fixture("snapshot.json")
    context = _merge({}, orbit_documents(snapshot), snapshot, merge=True)
    assert context["orbit_context"] == snapshot["content"]
    assert [d["id"] for d in context["documents"]] == ["c1", "m1"]


def test_context_package_context_text_is_kept() -> None:
    package = fixture("context_package.json")
    assert _merge({}, orbit_documents(package), package, merge=True)["orbit_context"] == package["context"]


def test_context_hash_follows_the_real_content() -> None:
    snapshot = fixture("snapshot.json")
    base = orbit_context_hash(orbit_documents(snapshot), snapshot)
    assert base == orbit_context_hash(orbit_documents(snapshot), snapshot)
    changed = {
        **snapshot,
        "items": [{**snapshot["items"][0], "excerpt": "Autre passage."}, *snapshot["items"][1:]],
    }
    assert orbit_context_hash(orbit_documents(changed), changed) != base
    text_only = {**snapshot, "content": "Autre texte global."}
    assert orbit_context_hash(orbit_documents(text_only), text_only) != base

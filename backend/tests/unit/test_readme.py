"""Garde-fous de cohérence du README racine (liens relatifs, couverture de docs/)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
README = REPO_ROOT / "README.md"
DOCS_DIR = REPO_ROOT / "docs"

LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#")


def _readme_text() -> str:
    if not README.is_file():
        pytest.skip("README.md racine indisponible (exécution hors du dépôt complet)")
    return README.read_text(encoding="utf-8")


def _relative_targets(text: str) -> list[str]:
    targets: list[str] = []
    for raw in LINK_PATTERN.findall(text):
        if raw.startswith(EXTERNAL_PREFIXES):
            continue
        targets.append(raw.split("#", 1)[0])
    return [target for target in targets if target]


def test_readme_relative_links_exist() -> None:
    missing = [t for t in _relative_targets(_readme_text()) if not (REPO_ROOT / t).exists()]
    assert not missing, f"Liens relatifs cassés dans README.md : {missing}"


def test_readme_references_every_doc() -> None:
    text = _readme_text()
    if not DOCS_DIR.is_dir():
        pytest.skip("dossier docs/ indisponible")
    unlinked = [
        f"docs/{doc.name}" for doc in sorted(DOCS_DIR.glob("*.md")) if f"docs/{doc.name}" not in text
    ]
    assert not unlinked, f"Documents de docs/ absents du README.md : {unlinked}"

"""Scenario bundles ``forge.scenarios/v1`` (YAML or JSON) — import / export of scenario libraries.

Format::

    format: forge.scenarios/v1
    exported_at: "2026-09-30T10:00:00+00:00"
    scenarios:
      - slug: scenario_prd_001
        name: PRD export CSV
        category: product_management
        visibility: public            # public | private | fresh
        classification: 1             # 0–3
        tags: [prd]
        fresh_until: null             # ISO 8601
        archived: false
        parent_slug: null             # variants: slug of the parent scenario
        variant_label: null
        versions:
          - version: 1
            changelog: ""
            content: {difficulty, input, context, constraints, expected_output, expected_behavior,
                      criteria, rules, tool_mocks, description, dataset_id}
            content_hash: sha256:…    # informational (recomputed on import)

:func:`parse_bundle` is tolerant (every entry is checked independently, errors are collected) and
:func:`dump_bundle` ∘ :func:`parse_bundle` is the identity on bundles (round-trip safe). Canaries are
never imported: every imported version receives a fresh canary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

import yaml

from forge.domain.enums import ScenarioVisibility
from forge.domain.scenarios.validation import SLUG_RE

BUNDLE_FORMAT = "forge.scenarios/v1"
MAX_BUNDLE_SCENARIOS = 1000

BundleFormat = Literal["yaml", "json"]


@dataclass(slots=True)
class BundleVersion:
    content: dict[str, Any]
    version: int | None = None
    changelog: str = ""
    content_hash: str | None = None
    canary: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"version": self.version, "changelog": self.changelog, "content": self.content}
        if self.content_hash:
            data["content_hash"] = self.content_hash
        if self.canary:
            data["canary"] = self.canary
        return data


@dataclass(slots=True)
class BundleScenario:
    slug: str
    name: str
    category: str
    versions: list[BundleVersion]
    visibility: ScenarioVisibility = ScenarioVisibility.public
    classification: int = 1
    tags: list[str] = field(default_factory=list)
    fresh_until: str | None = None
    archived: bool = False
    parent_slug: str | None = None
    variant_label: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "category": self.category,
            "visibility": self.visibility.value,
            "classification": self.classification,
            "tags": list(self.tags),
            "fresh_until": self.fresh_until,
            "archived": self.archived,
            "parent_slug": self.parent_slug,
            "variant_label": self.variant_label,
            "versions": [v.as_dict() for v in self.versions],
        }


@dataclass(slots=True)
class BundleError:
    index: int | None
    slug: str | None
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"index": self.index, "slug": self.slug, "message": self.message}


@dataclass(slots=True)
class Bundle:
    scenarios: list[BundleScenario] = field(default_factory=list)
    exported_at: str | None = None
    errors: list[BundleError] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": BUNDLE_FORMAT,
            "exported_at": self.exported_at,
            "scenarios": [s.as_dict() for s in self.scenarios],
        }


class BundleFormatError(ValueError):
    """The document is not a readable ``forge.scenarios/v1`` bundle (French message)."""


# --- Loading ---------------------------------------------------------------------------------------


def _jsonify(value: Any) -> Any:
    """YAML may produce dates/datetimes: convert them to ISO strings (JSON-compatible content)."""
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonify(v) for v in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def load_document(data: str | bytes) -> Any:
    """Parse JSON or YAML text (JSON is tried first when the text starts with ``{`` or ``[``)."""
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise BundleFormatError("Fichier illisible : encodage UTF-8 attendu") from exc
    text = data.strip()
    if not text:
        raise BundleFormatError("Fichier vide")
    if text[0] in "{[":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass  # may still be YAML flow syntax
    try:
        return _jsonify(yaml.safe_load(text))
    except yaml.YAMLError as exc:
        raise BundleFormatError(f"Contenu YAML/JSON invalide : {exc}") from exc


def _parse_version(raw: Any, position: int) -> BundleVersion:
    if not isinstance(raw, dict):
        raise ValueError(f"versions[{position}] : objet attendu")
    content = raw.get("content")
    if not isinstance(content, dict):
        raise ValueError(f"versions[{position}].content : objet attendu")
    version = raw.get("version")
    if version is not None and (not isinstance(version, int) or isinstance(version, bool) or version < 1):
        raise ValueError(f"versions[{position}].version : entier ≥ 1 attendu")
    changelog = raw.get("changelog") or ""
    if not isinstance(changelog, str):
        raise ValueError(f"versions[{position}].changelog : texte attendu")
    return BundleVersion(
        content=dict(content),
        version=version,
        changelog=changelog,
        content_hash=str(raw["content_hash"]) if raw.get("content_hash") else None,
        canary=str(raw["canary"]) if raw.get("canary") else None,
    )


def _parse_scenario(raw: Any) -> BundleScenario:
    if not isinstance(raw, dict):
        raise ValueError("objet attendu")
    slug = raw.get("slug")
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ValueError("slug invalide (minuscules, chiffres, _ ou -, 3 à 120 caractères)")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("nom requis")
    category = raw.get("category")
    if not isinstance(category, str) or not category.strip():
        raise ValueError("catégorie requise")
    try:
        visibility = ScenarioVisibility(raw.get("visibility") or "public")
    except ValueError as exc:
        raise ValueError("visibilité attendue : public, private ou fresh") from exc
    classification = raw.get("classification", 1)
    if (
        not isinstance(classification, int)
        or isinstance(classification, bool)
        or not 0 <= classification <= 3
    ):
        raise ValueError("classification attendue : 0 à 3")
    tags = raw.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError("tags : liste de textes attendue")
    fresh_until = raw.get("fresh_until")
    if fresh_until is not None:
        try:
            datetime.fromisoformat(str(fresh_until))
        except ValueError as exc:
            raise ValueError("fresh_until : date ISO 8601 attendue") from exc
        fresh_until = str(fresh_until)
    parent_slug = raw.get("parent_slug")
    if parent_slug is not None and (not isinstance(parent_slug, str) or not SLUG_RE.match(parent_slug)):
        raise ValueError("parent_slug invalide")
    variant_label = raw.get("variant_label")
    if variant_label is not None and not isinstance(variant_label, str):
        raise ValueError("variant_label : texte attendu")
    versions_raw = raw.get("versions")
    if not isinstance(versions_raw, list) or not versions_raw:
        raise ValueError("au moins une version est requise")
    versions = [_parse_version(v, i) for i, v in enumerate(versions_raw)]
    return BundleScenario(
        slug=slug,
        name=name.strip(),
        category=category.strip(),
        versions=versions,
        visibility=visibility,
        classification=classification,
        tags=[t.strip() for t in tags if t.strip()],
        fresh_until=fresh_until,
        archived=bool(raw.get("archived", False)),
        parent_slug=parent_slug,
        variant_label=variant_label,
    )


def parse_bundle(data: str | bytes | dict[str, Any]) -> Bundle:
    """Parse a bundle document. Structural errors of an entry are collected in ``Bundle.errors``.

    Raises :class:`BundleFormatError` when the document itself is unusable.
    """
    document = data if isinstance(data, dict) else load_document(data)
    if not isinstance(document, dict):
        raise BundleFormatError("Objet attendu à la racine du fichier (format forge.scenarios/v1)")
    fmt = document.get("format")
    if fmt != BUNDLE_FORMAT:
        raise BundleFormatError(f"Format non pris en charge « {fmt} » (attendu : {BUNDLE_FORMAT})")
    raw_scenarios = document.get("scenarios")
    if not isinstance(raw_scenarios, list):
        raise BundleFormatError("La clé « scenarios » doit être une liste")
    if len(raw_scenarios) > MAX_BUNDLE_SCENARIOS:
        raise BundleFormatError(f"Au plus {MAX_BUNDLE_SCENARIOS} scénarios par fichier")
    bundle = Bundle(exported_at=str(document["exported_at"]) if document.get("exported_at") else None)
    seen: set[str] = set()
    for index, raw in enumerate(raw_scenarios):
        slug = raw.get("slug") if isinstance(raw, dict) else None
        try:
            entry = _parse_scenario(raw)
        except ValueError as exc:
            bundle.errors.append(BundleError(index, slug if isinstance(slug, str) else None, str(exc)))
            continue
        if entry.slug in seen:
            bundle.errors.append(BundleError(index, entry.slug, "slug dupliqué dans le fichier"))
            continue
        seen.add(entry.slug)
        bundle.scenarios.append(entry)
    return bundle


def order_by_dependencies(entries: list[BundleScenario]) -> list[BundleScenario]:
    """Parents before their variants (entries whose parent is outside the bundle keep their order)."""
    by_slug = {e.slug: e for e in entries}
    ordered: list[BundleScenario] = []
    placed: set[str] = set()
    visiting: set[str] = set()

    def place(entry: BundleScenario) -> None:
        if entry.slug in placed:
            return
        if entry.slug in visiting:  # cycle: keep file order
            return
        visiting.add(entry.slug)
        parent = by_slug.get(entry.parent_slug or "")
        if parent is not None and parent.slug != entry.slug:
            place(parent)
        visiting.discard(entry.slug)
        placed.add(entry.slug)
        ordered.append(entry)

    for entry in entries:
        place(entry)
    return ordered


# --- Dumping ---------------------------------------------------------------------------------------


class _NoAliasDumper(yaml.SafeDumper):
    """Never emit YAML anchors/aliases (shared objects are written out in full)."""

    def ignore_aliases(self, data: Any) -> bool:
        return True


def dump_bundle(bundle: Bundle, fmt: BundleFormat = "yaml") -> str:
    data = bundle.as_dict()
    if fmt == "json":
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    return yaml.dump(
        data, Dumper=_NoAliasDumper, allow_unicode=True, sort_keys=False, default_flow_style=False, width=100
    )

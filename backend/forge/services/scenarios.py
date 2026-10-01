"""Scenario Manager: scenarios, immutable versions, variants, import / export (docs §3.3, §3.4, §6.1).

Access rules (the ``viewer`` argument is any :class:`forge.services.access.Viewer`):

* scenarios above the viewer's clearance are never revealed (``NotFoundError``);
* creating a private scenario, changing its content (new version, variant) or moving a scenario
  to / from ``private`` requires ``can_see_private`` (maintainer+);
* private content is redacted for everybody else (:func:`version_view`), hidden rules are masked on
  every scenario and canaries are only shown to maintainers.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import SCENARIO_CATEGORIES, Difficulty, ScenarioVisibility
from forge.domain.redaction import redact_scenario_content
from forge.domain.scenarios.import_export import (
    Bundle,
    BundleFormatError,
    BundleScenario,
    BundleVersion,
    order_by_dependencies,
    parse_bundle,
)
from forge.domain.scenarios.validation import (
    CONTENT_FIELDS,
    SLUG_RE,
    ScenarioValidationError,
    merge_content,
    normalize_content,
)
from forge.domain.versioning import new_canary, scenario_version_hash
from forge.infra.db import utcnow
from forge.infra.models import Dataset, Scenario, ScenarioVersion
from forge.services import access, audit
from forge.services.access import Viewer
from forge.services.audit import ActorLike
from forge.services.taxonomy import (
    ConflictError,
    ForbiddenError,
    InvalidError,
    NotFoundError,
    PlatformError,
    criteria_keys,
    error_type_codes,
)

FRESH_DEFAULT_DAYS = 30
EDITABLE_FIELDS = ("name", "category", "tags", "visibility", "classification", "archived", "fresh_until")
PRIVATE_RIGHTS_MESSAGE = (
    "Action réservée aux mainteneurs de benchmarks : le contenu des scénarios privés n'est accessible "
    "qu'au rôle maintainer ou supérieur"
)


def _slug_part(text: str) -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", text.casefold())
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")


def category_label(category: str) -> str:
    return SCENARIO_CATEGORIES.get(category, category)


def is_fresh(scenario: Scenario, *, now: datetime | None = None) -> bool:
    if scenario.visibility != ScenarioVisibility.fresh:
        return False
    return scenario.fresh_until is None or scenario.fresh_until > (now or utcnow())


def _require_private_rights(viewer: Viewer, visibility: ScenarioVisibility | str) -> None:
    if ScenarioVisibility(visibility) == ScenarioVisibility.private and not viewer.can_see_private:
        raise ForbiddenError(PRIVATE_RIGHTS_MESSAGE)


def _require_clearance(viewer: Viewer, classification: int) -> None:
    if int(classification) > int(viewer.clearance):
        raise ForbiddenError(
            f"Classification C{int(classification)} supérieure à votre habilitation "
            f"(C{int(viewer.clearance)})"
        )


# =====================================================================================================
# Reading
# =====================================================================================================


@dataclass(slots=True)
class ScenarioListing:
    scenario: Scenario
    latest: ScenarioVersion | None


async def get_scenario(session: AsyncSession, viewer: Viewer, scenario_id: uuid.UUID) -> Scenario:
    scenario = await session.get(Scenario, scenario_id)
    if scenario is None or not access.can_view_scenario(viewer, scenario):
        raise NotFoundError("Scénario introuvable")
    return scenario


async def get_by_slug(session: AsyncSession, slug: str) -> Scenario | None:
    return await session.scalar(select(Scenario).where(Scenario.slug == slug))


async def get_version(
    session: AsyncSession, viewer: Viewer, version_id: uuid.UUID
) -> tuple[Scenario, ScenarioVersion]:
    version = await session.get(ScenarioVersion, version_id)
    if version is None:
        raise NotFoundError("Version de scénario introuvable")
    scenario = await session.get(Scenario, version.scenario_id)
    if scenario is None or not access.can_view_scenario(viewer, scenario):
        raise NotFoundError("Version de scénario introuvable")
    return scenario, version


async def latest_version(session: AsyncSession, scenario: Scenario) -> ScenarioVersion | None:
    return await session.scalar(
        select(ScenarioVersion).where(
            ScenarioVersion.scenario_id == scenario.id, ScenarioVersion.version == scenario.latest_version
        )
    ) or await session.scalar(
        select(ScenarioVersion)
        .where(ScenarioVersion.scenario_id == scenario.id)
        .order_by(ScenarioVersion.version.desc())
        .limit(1)
    )


async def list_versions(session: AsyncSession, scenario: Scenario) -> list[ScenarioVersion]:
    return list(
        await session.scalars(
            select(ScenarioVersion)
            .where(ScenarioVersion.scenario_id == scenario.id)
            .order_by(ScenarioVersion.version.desc())
        )
    )


async def family_members(session: AsyncSession, viewer: Viewer, scenario: Scenario) -> list[Scenario]:
    return list(
        await session.scalars(
            select(Scenario)
            .where(
                Scenario.family_id == scenario.family_id,
                Scenario.id != scenario.id,
                access.classification_condition(viewer),
            )
            .order_by(Scenario.created_at)
        )
    )


def _filters(
    viewer: Viewer,
    *,
    q: str | None,
    category: str | None,
    visibility: ScenarioVisibility | None,
    difficulty: Difficulty | None,
    tag: str | None,
    family_id: uuid.UUID | None,
    archived: bool | None,
) -> list[Any]:
    conditions: list[Any] = [access.classification_condition(viewer)]
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(or_(Scenario.name.ilike(pattern), Scenario.slug.ilike(pattern)))
    if category:
        conditions.append(Scenario.category == category)
    if visibility:
        conditions.append(Scenario.visibility == visibility)
    if difficulty:
        conditions.append(ScenarioVersion.difficulty == difficulty)
    if tag:
        conditions.append(Scenario.tags.contains([tag]))
    if family_id:
        conditions.append(Scenario.family_id == family_id)
    if archived is not None:
        conditions.append(Scenario.archived.is_(archived))
    return conditions


async def list_scenarios(
    session: AsyncSession,
    viewer: Viewer,
    *,
    q: str | None = None,
    category: str | None = None,
    visibility: ScenarioVisibility | None = None,
    difficulty: Difficulty | None = None,
    tag: str | None = None,
    family_id: uuid.UUID | None = None,
    archived: bool | None = False,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[ScenarioListing], int]:
    conditions = _filters(
        viewer,
        q=q,
        category=category,
        visibility=visibility,
        difficulty=difficulty,
        tag=tag,
        family_id=family_id,
        archived=archived,
    )
    join_on = (ScenarioVersion.scenario_id == Scenario.id) & (
        ScenarioVersion.version == Scenario.latest_version
    )
    total = await session.scalar(
        select(func.count(Scenario.id))
        .select_from(Scenario)
        .outerjoin(ScenarioVersion, join_on)
        .where(*conditions)
    )
    rows = (
        await session.execute(
            select(Scenario, ScenarioVersion)
            .outerjoin(ScenarioVersion, join_on)
            .where(*conditions)
            .order_by(Scenario.slug)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [ScenarioListing(s, v) for s, v in rows], int(total or 0)


def content_of(version: ScenarioVersion) -> dict[str, Any]:
    return {
        "description": version.description,
        "difficulty": version.difficulty.value,
        "input": dict(version.input or {}),
        "context": dict(version.context or {}),
        "constraints": list(version.constraints or []),
        "expected_output": version.expected_output,
        "expected_behavior": version.expected_behavior,
        "criteria": list(version.criteria or []),
        "rules": list(version.rules or []),
        "tool_mocks": list(version.tool_mocks or []),
        "dataset_id": str(version.dataset_id) if version.dataset_id else None,
    }


def version_view(viewer: Viewer, scenario: Scenario, version: ScenarioVersion) -> dict[str, Any]:
    """Version content as the viewer may see it (§3.3): private content, hidden rules, canary."""
    data = {**content_of(version), "canary": version.canary}
    if viewer.can_see_private:
        data["redacted"] = False
    else:
        data = redact_scenario_content(data, private=access.must_redact(viewer, scenario.visibility))
        data.pop("canary", None)
        data["canary"] = None
    return {
        "id": version.id,
        "scenario_id": version.scenario_id,
        "version": version.version,
        "changelog": version.changelog,
        "content_hash": version.content_hash,
        "created_at": version.created_at,
        "created_by": version.created_by,
        **data,
    }


# =====================================================================================================
# Writing
# =====================================================================================================


async def validated_content(session: AsyncSession, content: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalise a version content against the criteria catalog and error taxonomy."""
    try:
        normalized = normalize_content(
            content,
            criteria_catalog=await criteria_keys(session),
            error_types=await error_type_codes(session),
        )
    except ScenarioValidationError as exc:
        raise InvalidError(str(exc), errors=[i.as_dict() for i in exc.issues]) from exc
    if normalized["dataset_id"]:
        try:
            dataset_id = uuid.UUID(normalized["dataset_id"])
        except ValueError as exc:
            raise InvalidError("dataset_id : identifiant invalide") from exc
        if await session.get(Dataset, dataset_id) is None:
            raise InvalidError("dataset_id : jeu de données introuvable")
    return normalized


def content_hash(content: dict[str, Any]) -> str:
    return scenario_version_hash(**{k: content[k] for k in CONTENT_FIELDS})


def _version_row(
    scenario_id: uuid.UUID,
    number: int,
    content: dict[str, Any],
    *,
    changelog: str,
    created_by: uuid.UUID | None,
) -> ScenarioVersion:
    return ScenarioVersion(
        scenario_id=scenario_id,
        version=number,
        description=content["description"],
        difficulty=Difficulty(content["difficulty"]),
        input=content["input"],
        context=content["context"],
        constraints=content["constraints"],
        expected_output=content["expected_output"],
        expected_behavior=content["expected_behavior"],
        criteria=content["criteria"],
        rules=content["rules"],
        tool_mocks=content["tool_mocks"],
        dataset_id=uuid.UUID(content["dataset_id"]) if content["dataset_id"] else None,
        canary=new_canary(),
        changelog=(changelog or "").strip(),
        content_hash=content_hash(content),
        created_by=created_by,
    )


def _clean_tags(tags: Sequence[str] | None) -> list[str]:
    result: list[str] = []
    for tag in tags or []:
        tag = str(tag).strip()
        if tag and tag not in result:
            result.append(tag)
    return result


def _category_abbreviation(category: str) -> str:
    words = [w for w in _slug_part(category).split("_") if w]
    if not words:
        return "gen"
    if len(words) >= 2:
        return "".join(w[0] for w in words)[:4]
    return words[0][:3]


async def generate_slug(session: AsyncSession, category: str) -> str:
    """``scenario_<abbr>_<NNN>`` — next free number for the category abbreviation."""
    prefix = f"scenario_{_category_abbreviation(category)}_"
    slugs = await session.scalars(select(Scenario.slug).where(Scenario.slug.startswith(prefix)))
    numbers = [int(m.group(1)) for s in slugs if (m := re.fullmatch(re.escape(prefix) + r"(\d+)", s))]
    return f"{prefix}{(max(numbers) + 1) if numbers else 1:03d}"


async def create_scenario(
    session: AsyncSession,
    viewer: Viewer,
    actor: ActorLike,
    *,
    name: str,
    category: str,
    content: dict[str, Any],
    slug: str | None = None,
    visibility: ScenarioVisibility = ScenarioVisibility.public,
    classification: int = 1,
    tags: Sequence[str] = (),
    fresh_until: datetime | None = None,
    changelog: str = "",
    owner_id: uuid.UUID | None = None,
    parent: Scenario | None = None,
    variant_label: str | None = None,
) -> tuple[Scenario, ScenarioVersion]:
    visibility = ScenarioVisibility(visibility)
    _require_private_rights(viewer, visibility)
    _require_clearance(viewer, classification)
    name, category = name.strip(), category.strip()
    if not name:
        raise InvalidError("Nom du scénario requis")
    if not category:
        raise InvalidError("Catégorie requise")
    slug = (slug or "").strip() or await generate_slug(session, category)
    if not SLUG_RE.match(slug):
        raise InvalidError(
            "Identifiant (slug) invalide : minuscules, chiffres, « _ » ou « - » (ex. scenario_prd_001)"
        )
    if await get_by_slug(session, slug) is not None:
        raise ConflictError(f"Un scénario existe déjà avec l'identifiant « {slug} »")
    normalized = await validated_content(session, content)
    if visibility == ScenarioVisibility.fresh and fresh_until is None:
        fresh_until = utcnow() + timedelta(days=FRESH_DEFAULT_DAYS)
    scenario_id = uuid.uuid4()
    scenario = Scenario(
        id=scenario_id,
        slug=slug,
        name=name,
        category=category,
        parent_scenario_id=parent.id if parent else None,
        family_id=parent.family_id if parent else scenario_id,
        variant_label=variant_label,
        visibility=visibility,
        classification=int(classification),
        fresh_until=fresh_until,
        tags=_clean_tags(tags),
        owner_id=owner_id,
        latest_version=1,
    )
    session.add(scenario)
    await session.flush()
    version = _version_row(
        scenario_id, 1, normalized, changelog=changelog or "Version initiale", created_by=owner_id
    )
    session.add(version)
    await session.flush()
    await audit.record(
        session,
        actor,
        "scenario.create",
        "scenario",
        scenario.id,
        summary=f"Création du scénario {slug} ({name})" + (f", variante de {parent.slug}" if parent else ""),
        details={
            "slug": slug,
            "visibility": visibility,
            "classification": int(classification),
            "content_hash": version.content_hash,
            "parent_scenario_id": parent.id if parent else None,
            "variant_label": variant_label,
        },
    )
    return scenario, version


async def create_version(
    session: AsyncSession,
    viewer: Viewer,
    actor: ActorLike,
    scenario: Scenario,
    overrides: dict[str, Any],
    *,
    changelog: str = "",
    created_by: uuid.UUID | None = None,
) -> ScenarioVersion:
    """New immutable version: fields of ``overrides`` replace those of the latest version."""
    _require_private_rights(viewer, scenario.visibility)
    latest = await latest_version(session, scenario)
    base = content_of(latest) if latest else {}
    normalized = await validated_content(session, merge_content(base, overrides))
    digest = content_hash(normalized)
    if latest is not None and latest.content_hash == digest:
        raise ConflictError(f"Contenu identique à la dernière version (v{latest.version}) du scénario")
    number = max(scenario.latest_version, latest.version if latest else 0) + 1
    version = _version_row(scenario.id, number, normalized, changelog=changelog, created_by=created_by)
    session.add(version)
    scenario.latest_version = number
    scenario.updated_at = utcnow()
    await session.flush()
    await audit.record(
        session,
        actor,
        "scenario_version.create",
        "scenario_version",
        version.id,
        summary=f"Scénario {scenario.slug} v{number}",
        details={
            "scenario_id": scenario.id,
            "version": number,
            "content_hash": digest,
            "changed_fields": sorted(k for k in overrides if k in CONTENT_FIELDS),
        },
    )
    return version


async def update_scenario(
    session: AsyncSession, viewer: Viewer, actor: ActorLike, scenario: Scenario, changes: dict[str, Any]
) -> Scenario:
    """Non-behavioural metadata (§6.1): name, category, tags, visibility, classification, archive,
    freshness."""
    applied: dict[str, Any] = {}
    for key, value in changes.items():
        if key not in EDITABLE_FIELDS:
            continue
        if key in ("name", "category"):
            value = str(value or "").strip()
            if not value:
                raise InvalidError("Le nom et la catégorie ne peuvent pas être vides")
        elif key == "tags":
            value = _clean_tags(value)
        elif key == "visibility":
            if value is None:
                continue
            value = ScenarioVisibility(value)
            if value != scenario.visibility:
                _require_private_rights(viewer, value)
                _require_private_rights(viewer, scenario.visibility)
        elif key == "classification":
            if value is None:
                continue
            value = int(value)
            _require_clearance(viewer, value)
        elif key == "archived":
            value = bool(value)
        if getattr(scenario, key) != value:
            applied[key] = value
            setattr(scenario, key, value)
    if applied.get("visibility") == ScenarioVisibility.fresh and scenario.fresh_until is None:
        scenario.fresh_until = utcnow() + timedelta(days=FRESH_DEFAULT_DAYS)
        applied["fresh_until"] = scenario.fresh_until
    if applied:
        scenario.updated_at = utcnow()
        await session.flush()
        action = "scenario.archive" if applied.get("archived") is True else "scenario.update"
        await audit.record(
            session,
            actor,
            action,
            "scenario",
            scenario.id,
            summary=f"Modification du scénario {scenario.slug}",
            details={"changes": applied},
        )
    return scenario


async def create_variant(
    session: AsyncSession,
    viewer: Viewer,
    actor: ActorLike,
    parent: Scenario,
    *,
    label: str,
    overrides: dict[str, Any],
    name: str | None = None,
    tags: Sequence[str] | None = None,
    visibility: ScenarioVisibility | None = None,
    changelog: str = "",
    owner_id: uuid.UUID | None = None,
) -> tuple[Scenario, ScenarioVersion]:
    """Variant of ``parent`` (same family): content = parent's latest version + ``overrides``."""
    _require_private_rights(viewer, parent.visibility)
    normalized_label = _slug_part(label)
    if not normalized_label:
        raise InvalidError("Libellé de variante requis (ex. short_context)")
    latest = await latest_version(session, parent)
    if latest is None:
        raise ConflictError("Le scénario parent n'a aucune version")
    content = merge_content(content_of(latest), overrides)
    return await create_scenario(
        session,
        viewer,
        actor,
        name=name or f"{parent.name} — variante {label.strip()}",
        category=parent.category,
        content=content,
        slug=f"{parent.slug}_variant_{normalized_label}",
        visibility=visibility or parent.visibility,
        classification=parent.classification,
        tags=tags if tags is not None else list(parent.tags or []),
        fresh_until=parent.fresh_until
        if (visibility or parent.visibility) == ScenarioVisibility.fresh
        else None,
        changelog=changelog or f"Variante « {label.strip()} » de {parent.slug} v{latest.version}",
        owner_id=owner_id,
        parent=parent,
        variant_label=normalized_label,
    )


# =====================================================================================================
# Import / export
# =====================================================================================================


@dataclass(slots=True)
class ImportReport:
    dry_run: bool
    created: list[dict[str, Any]] = field(default_factory=list)
    updated: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        from datetime import UTC

        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def _import_entry(
    session: AsyncSession,
    viewer: Viewer,
    actor: ActorLike,
    entry: BundleScenario,
    created_by: uuid.UUID | None,
) -> tuple[str, dict[str, Any]]:
    existing = await get_by_slug(session, entry.slug)
    if existing is not None:
        if not access.can_view_scenario(viewer, existing):
            raise ConflictError("Identifiant déjà utilisé par un scénario inaccessible")
        _require_private_rights(viewer, existing.visibility)
        hashes = set(
            await session.scalars(
                select(ScenarioVersion.content_hash).where(ScenarioVersion.scenario_id == existing.id)
            )
        )
        added: list[int] = []
        for bundle_version in entry.versions:
            normalized = await validated_content(session, bundle_version.content)
            if content_hash(normalized) in hashes:
                continue
            version = await create_version(
                session,
                viewer,
                actor,
                existing,
                normalized,
                changelog=bundle_version.changelog or "Import",
                created_by=created_by,
            )
            hashes.add(version.content_hash)
            added.append(version.version)
        info = {"slug": entry.slug, "scenario_id": str(existing.id)}
        if not added:
            return "skipped", {**info, "reason": "Contenu identique à une version existante"}
        return "updated", {**info, "versions": added}
    parent: Scenario | None = None
    if entry.parent_slug:
        parent = await get_by_slug(session, entry.parent_slug)
        if parent is None or not access.can_view_scenario(viewer, parent):
            raise InvalidError(f"Scénario parent « {entry.parent_slug} » introuvable")
    first, *others = entry.versions
    scenario, version = await create_scenario(
        session,
        viewer,
        actor,
        name=entry.name,
        category=entry.category,
        content=first.content,
        slug=entry.slug,
        visibility=entry.visibility,
        classification=entry.classification,
        tags=entry.tags,
        fresh_until=_parse_datetime(entry.fresh_until),
        changelog=first.changelog or "Import",
        owner_id=created_by,
        parent=parent,
        variant_label=entry.variant_label,
    )
    versions = [version.version]
    for bundle_version in others:
        try:
            added = await create_version(
                session,
                viewer,
                actor,
                scenario,
                bundle_version.content,
                changelog=bundle_version.changelog or "Import",
                created_by=created_by,
            )
        except ConflictError:
            continue  # consecutive identical versions
        versions.append(added.version)
    if entry.archived:
        scenario.archived = True
        await session.flush()
    return "created", {"slug": entry.slug, "scenario_id": str(scenario.id), "versions": versions}


async def import_bundle(
    session: AsyncSession,
    viewer: Viewer,
    actor: ActorLike,
    data: str | bytes | dict[str, Any],
    *,
    dry_run: bool = False,
    created_by: uuid.UUID | None = None,
) -> ImportReport:
    """Import a ``forge.scenarios/v1`` bundle. Each entry succeeds or fails on its own (savepoints);
    ``dry_run`` validates everything and rolls back."""
    try:
        bundle = parse_bundle(data)
    except BundleFormatError as exc:
        raise InvalidError(str(exc)) from exc
    report = ImportReport(dry_run=dry_run, errors=[e.as_dict() for e in bundle.errors])
    outer = await session.begin_nested() if dry_run else None
    try:
        for entry in order_by_dependencies(bundle.scenarios):
            try:
                async with session.begin_nested():
                    outcome, info = await _import_entry(session, viewer, actor, entry, created_by)
            except PlatformError as exc:
                report.errors.append(
                    {"index": None, "slug": entry.slug, "message": exc.message, "errors": exc.errors}
                )
                continue
            except IntegrityError:
                report.errors.append(
                    {"index": None, "slug": entry.slug, "message": "Conflit avec une ressource existante"}
                )
                continue
            getattr(report, outcome).append(info)
    finally:
        if outer is not None:
            await outer.rollback()
    if not dry_run and (report.created or report.updated):
        await audit.record(
            session,
            actor,
            "scenario.import",
            "scenario",
            None,
            summary=f"Import de scénarios : {len(report.created)} créé(s), {len(report.updated)} mis à jour",
            details={
                "created": [c["slug"] for c in report.created],
                "updated": [u["slug"] for u in report.updated],
                "skipped": len(report.skipped),
                "errors": len(report.errors),
            },
        )
    return report


@dataclass(slots=True)
class ExportResult:
    bundle: Bundle
    skipped_private: int = 0
    hidden_rules_removed: int = 0


async def export_bundle(
    session: AsyncSession,
    viewer: Viewer,
    *,
    q: str | None = None,
    category: str | None = None,
    visibility: ScenarioVisibility | None = None,
    tag: str | None = None,
    family_id: uuid.UUID | None = None,
    archived: bool | None = False,
    scenario_ids: Sequence[uuid.UUID] | None = None,
    all_versions: bool = True,
) -> ExportResult:
    """Bundle of the visible scenarios. Non-maintainers never export private scenarios (skipped) nor
    hidden rules (removed) nor canaries."""
    conditions = _filters(
        viewer,
        q=q,
        category=category,
        visibility=visibility,
        difficulty=None,
        tag=tag,
        family_id=family_id,
        archived=archived,
    )
    if scenario_ids:
        conditions.append(Scenario.id.in_(list(scenario_ids)))
    scenarios = list(
        await session.scalars(
            select(Scenario).where(*conditions).order_by(Scenario.created_at, Scenario.slug)
        )
    )
    result = ExportResult(bundle=Bundle(exported_at=utcnow().isoformat()))
    by_id = {s.id: s for s in scenarios}
    parents_needed = {
        s.parent_scenario_id for s in scenarios if s.parent_scenario_id and s.parent_scenario_id not in by_id
    }
    if parents_needed:
        for parent in await session.scalars(select(Scenario).where(Scenario.id.in_(parents_needed))):
            by_id[parent.id] = parent
    ids = [s.id for s in scenarios]
    versions: dict[uuid.UUID, list[ScenarioVersion]] = {i: [] for i in ids}
    if ids:
        for version in await session.scalars(
            select(ScenarioVersion)
            .where(ScenarioVersion.scenario_id.in_(ids))
            .order_by(ScenarioVersion.version)
        ):
            versions[version.scenario_id].append(version)
    for scenario in scenarios:
        if scenario.visibility == ScenarioVisibility.private and not viewer.can_see_private:
            result.skipped_private += 1
            continue
        selected = versions[scenario.id] if all_versions else versions[scenario.id][-1:]
        entry_versions: list[BundleVersion] = []
        for version in selected:
            content = content_of(version)
            if not viewer.can_see_private:
                kept = [r for r in content["rules"] if not r.get("hidden")]
                result.hidden_rules_removed += len(content["rules"]) - len(kept)
                content["rules"] = kept
            entry_versions.append(
                BundleVersion(
                    content=content,
                    version=version.version,
                    changelog=version.changelog,
                    content_hash=content_hash(content),
                    canary=version.canary if viewer.can_see_private else None,
                )
            )
        if not entry_versions:
            continue
        parent = by_id.get(scenario.parent_scenario_id) if scenario.parent_scenario_id else None
        result.bundle.scenarios.append(
            BundleScenario(
                slug=scenario.slug,
                name=scenario.name,
                category=scenario.category,
                versions=entry_versions,
                visibility=scenario.visibility,
                classification=int(scenario.classification),
                tags=list(scenario.tags or []),
                fresh_until=scenario.fresh_until.isoformat() if scenario.fresh_until else None,
                archived=scenario.archived,
                parent_slug=parent.slug if parent else None,
                variant_label=scenario.variant_label,
            )
        )
    return result

"""Datasets: context datasets (documents attached to scenarios) and gold datasets (runs selected for
human calibration, docs/ARCHITECTURE.md §9.4).

Context items are documents ``{title, content, source, metadata}``; gold items reference an
evaluation run (``run_id``) with optional notes. Adding or removing items bumps ``version``.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import DatasetKind
from forge.infra.models import Dataset, DatasetItem, EvaluationRun, Scenario
from forge.services import access, audit
from forge.services.access import Viewer
from forge.services.audit import ActorLike
from forge.services.taxonomy import ConflictError, InvalidError, NotFoundError

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,99}$")
KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
MAX_CONTENT_CHARS = 200_000
EDITABLE_FIELDS = ("name", "description", "tags")


def _slug(text: str, sep: str = "-") -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", text.casefold())
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", sep, ascii_text).strip(sep)


@dataclass(slots=True)
class DatasetListing:
    dataset: Dataset
    items_count: int


async def get_dataset(session: AsyncSession, dataset_id: uuid.UUID) -> Dataset:
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError("Jeu de données introuvable")
    return dataset


async def list_datasets(
    session: AsyncSession,
    *,
    kind: DatasetKind | None = None,
    q: str | None = None,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[DatasetListing], int]:
    conditions: list[Any] = []
    if kind:
        conditions.append(Dataset.kind == kind)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(or_(Dataset.name.ilike(pattern), Dataset.slug.ilike(pattern)))
    total = await session.scalar(select(func.count()).select_from(Dataset).where(*conditions))
    counts = (
        select(DatasetItem.dataset_id, func.count().label("n")).group_by(DatasetItem.dataset_id).subquery()
    )
    rows = (
        await session.execute(
            select(Dataset, func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.dataset_id == Dataset.id)
            .where(*conditions)
            .order_by(Dataset.name)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [DatasetListing(d, int(n)) for d, n in rows], int(total or 0)


async def list_items(session: AsyncSession, dataset: Dataset) -> list[DatasetItem]:
    return list(
        await session.scalars(
            select(DatasetItem)
            .where(DatasetItem.dataset_id == dataset.id)
            .order_by(DatasetItem.created_at, DatasetItem.key)
        )
    )


def _clean_tags(tags: Sequence[str] | None) -> list[str]:
    result: list[str] = []
    for tag in tags or []:
        tag = str(tag).strip()
        if tag and tag not in result:
            result.append(tag)
    return result


async def create_dataset(
    session: AsyncSession,
    viewer: Viewer,
    actor: ActorLike,
    *,
    name: str,
    kind: DatasetKind,
    slug: str | None = None,
    description: str = "",
    tags: Sequence[str] = (),
    items: Sequence[dict[str, Any]] = (),
    created_by: uuid.UUID | None = None,
) -> Dataset:
    name = name.strip()
    if not name:
        raise InvalidError("Nom du jeu de données requis")
    slug = (slug or _slug(name)).strip()
    if not SLUG_RE.match(slug):
        raise InvalidError("Identifiant (slug) invalide : minuscules, chiffres, « - » ou « _ »")
    if await session.scalar(select(Dataset.id).where(Dataset.slug == slug)):
        raise ConflictError(f"Un jeu de données existe déjà avec l'identifiant « {slug} »")
    dataset = Dataset(
        slug=slug,
        name=name,
        kind=DatasetKind(kind),
        description=description.strip(),
        tags=_clean_tags(tags),
        created_by=created_by,
    )
    session.add(dataset)
    await session.flush()
    await audit.record(
        session,
        actor,
        "dataset.create",
        "dataset",
        dataset.id,
        summary=f"Création du jeu de données {name} ({dataset.kind.value})",
        details={"slug": slug, "kind": dataset.kind},
    )
    if items:
        await add_items(session, viewer, actor, dataset, items, bump_version=False)
    return dataset


async def update_dataset(
    session: AsyncSession, actor: ActorLike, dataset: Dataset, changes: dict[str, Any]
) -> Dataset:
    applied: dict[str, Any] = {}
    for key, value in changes.items():
        if key not in EDITABLE_FIELDS:
            continue
        if key == "name":
            value = str(value or "").strip()
            if not value:
                raise InvalidError("Nom du jeu de données requis")
        elif key == "description":
            value = str(value or "").strip()
        elif key == "tags":
            value = _clean_tags(value)
        if getattr(dataset, key) != value:
            applied[key] = value
            setattr(dataset, key, value)
    if applied:
        await session.flush()
        await audit.record(
            session,
            actor,
            "dataset.update",
            "dataset",
            dataset.id,
            summary=f"Modification du jeu de données {dataset.name}",
            details={"changes": applied},
        )
    return dataset


async def _visible_run(session: AsyncSession, viewer: Viewer, run_id: uuid.UUID) -> EvaluationRun:
    row = (
        await session.execute(
            select(EvaluationRun)
            .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
            .where(EvaluationRun.id == run_id, access.classification_condition(viewer))
        )
    ).scalar_one_or_none()
    if row is None:
        raise InvalidError(f"Run {run_id} introuvable")
    return row


async def _item_from_payload(
    session: AsyncSession, viewer: Viewer, dataset: Dataset, payload: dict[str, Any], index: int
) -> DatasetItem:
    key = payload.get("key")
    if dataset.kind == DatasetKind.gold:
        raw_run = payload.get("run_id")
        if not raw_run:
            raise InvalidError(f"items[{index}] : run_id requis pour un jeu de données gold")
        try:
            run_id = uuid.UUID(str(raw_run))
        except ValueError as exc:
            raise InvalidError(f"items[{index}] : run_id invalide") from exc
        await _visible_run(session, viewer, run_id)
        notes = str(payload.get("notes") or "").strip()
        content: dict[str, Any] = {"notes": notes} if notes else {}
        if payload.get("metadata"):
            content["metadata"] = dict(payload["metadata"])
        return DatasetItem(dataset_id=dataset.id, key=str(key or run_id), content=content, run_id=run_id)
    title = str(payload.get("title") or "").strip()
    text = payload.get("content")
    if not isinstance(text, str) or not text.strip():
        raise InvalidError(f"items[{index}] : contenu du document requis")
    if len(text) > MAX_CONTENT_CHARS:
        raise InvalidError(f"items[{index}] : document trop long (maximum {MAX_CONTENT_CHARS} caractères)")
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise InvalidError(f"items[{index}] : metadata doit être un objet")
    key = str(key or _slug(title) or f"doc-{index + 1}")
    content = {
        "title": title,
        "content": text,
        "source": str(payload.get("source") or "").strip(),
        "metadata": metadata,
    }
    return DatasetItem(dataset_id=dataset.id, key=key, content=content)


async def add_items(
    session: AsyncSession,
    viewer: Viewer,
    actor: ActorLike,
    dataset: Dataset,
    items: Sequence[dict[str, Any]],
    *,
    bump_version: bool = True,
) -> list[DatasetItem]:
    if not items:
        raise InvalidError("Aucun élément à ajouter")
    existing = set(await session.scalars(select(DatasetItem.key).where(DatasetItem.dataset_id == dataset.id)))
    created: list[DatasetItem] = []
    for index, payload in enumerate(items):
        item = await _item_from_payload(session, viewer, dataset, payload, index)
        if not KEY_RE.match(item.key):
            raise InvalidError(f"items[{index}] : clé invalide « {item.key} »")
        if item.key in existing:
            raise ConflictError(f"L'élément « {item.key} » existe déjà dans ce jeu de données")
        existing.add(item.key)
        session.add(item)
        created.append(item)
    if bump_version:
        dataset.version += 1
    await session.flush()
    await audit.record(
        session,
        actor,
        "dataset.items_add",
        "dataset",
        dataset.id,
        summary=f"{len(created)} élément(s) ajouté(s) au jeu de données {dataset.name}",
        details={"keys": [i.key for i in created], "version": dataset.version},
    )
    return created


async def remove_item(session: AsyncSession, actor: ActorLike, dataset: Dataset, item_id: uuid.UUID) -> None:
    item = await session.get(DatasetItem, item_id)
    if item is None or item.dataset_id != dataset.id:
        raise NotFoundError("Élément introuvable dans ce jeu de données")
    await session.delete(item)
    dataset.version += 1
    await session.flush()
    await audit.record(
        session,
        actor,
        "dataset.item_remove",
        "dataset",
        dataset.id,
        summary=f"Élément « {item.key} » retiré du jeu de données {dataset.name}",
        details={"key": item.key, "item_id": item_id, "version": dataset.version},
    )


async def gold_run_ids(session: AsyncSession, dataset_id: uuid.UUID) -> list[uuid.UUID]:
    dataset = await get_dataset(session, dataset_id)
    if dataset.kind != DatasetKind.gold:
        raise InvalidError("Ce jeu de données n'est pas un jeu gold (kind=gold attendu)")
    return [
        r
        for r in await session.scalars(select(DatasetItem.run_id).where(DatasetItem.dataset_id == dataset_id))
        if r
    ]

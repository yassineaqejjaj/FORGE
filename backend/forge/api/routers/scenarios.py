"""Router ``scenarios``: Scenario Manager (scenarios, immutable versions, variants, import / export).

Private scenario content is redacted for non-maintainers and scenarios above the caller's clearance
are never revealed (docs §3.3, §3.4).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Query, Request, Response, status
from starlette.datastructures import UploadFile

from forge.api.deps import RequireEditor, RequireViewer, SessionDep
from forge.api.errors import ApiError, bad_request
from forge.api.routers.meta import PageQuery, parse_archived, platform_errors
from forge.api.schemas.common import Page
from forge.api.schemas.scenarios import (
    FamilyMember,
    ImportIn,
    ImportReportOut,
    ScenarioCreateIn,
    ScenarioDetailOut,
    ScenarioOut,
    ScenarioUpdateIn,
    ScenarioVersionCreateIn,
    ScenarioVersionOut,
    ScenarioVersionSummary,
    VariantCreateIn,
)
from forge.domain.enums import Difficulty, ScenarioVisibility, classification_warning
from forge.domain.scenarios.import_export import dump_bundle
from forge.infra.models import Scenario, ScenarioVersion
from forge.services import scenarios as service

router = APIRouter(tags=["scenarios"])

MAX_IMPORT_BYTES = 10 * 1024 * 1024
YAML_TYPES = ("application/yaml", "application/x-yaml", "text/yaml", "text/x-yaml", "text/plain")


def scenario_out(scenario: Scenario, latest: ScenarioVersion | None) -> dict[str, Any]:
    return {
        "id": scenario.id,
        "slug": scenario.slug,
        "name": scenario.name,
        "category": scenario.category,
        "category_label": service.category_label(scenario.category),
        "visibility": scenario.visibility,
        "classification": int(scenario.classification),
        "classification_warning": classification_warning(int(scenario.classification)),
        "tags": list(scenario.tags or []),
        "family_id": scenario.family_id,
        "parent_scenario_id": scenario.parent_scenario_id,
        "variant_label": scenario.variant_label,
        "latest_version": scenario.latest_version,
        "latest_version_id": latest.id if latest else None,
        "difficulty": latest.difficulty if latest else None,
        "archived": scenario.archived,
        "fresh_until": scenario.fresh_until,
        "is_fresh": service.is_fresh(scenario),
        "owner_id": scenario.owner_id,
        "created_at": scenario.created_at,
        "updated_at": scenario.updated_at,
    }


def _content(body: Any) -> dict[str, Any]:
    return body.model_dump(exclude_unset=True, mode="json")


async def _detail(session: SessionDep, principal: RequireViewer, scenario: Scenario) -> ScenarioDetailOut:
    versions = await service.list_versions(session, scenario)
    latest = next(
        (v for v in versions if v.version == scenario.latest_version), versions[0] if versions else None
    )
    family = await service.family_members(session, principal, scenario)
    return ScenarioDetailOut(
        **scenario_out(scenario, latest),
        latest=ScenarioVersionOut(**service.version_view(principal, scenario, latest)) if latest else None,
        versions=[ScenarioVersionSummary.model_validate(v) for v in versions],
        family=[FamilyMember.model_validate(m) for m in family],
    )


async def _scenario(session: SessionDep, principal: RequireViewer, scenario_id: uuid.UUID) -> Scenario:
    with platform_errors():
        return await service.get_scenario(session, principal, scenario_id)


@router.get("/scenarios", response_model=Page[ScenarioOut], summary="Lister les scénarios")
async def list_scenarios(
    principal: RequireViewer,
    session: SessionDep,
    paging: PageQuery,
    q: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=100),
    visibility: ScenarioVisibility | None = None,
    difficulty: Difficulty | None = None,
    tag: str | None = Query(default=None, max_length=100),
    family: uuid.UUID | None = Query(default=None, description="Famille de variantes (family_id)"),
    archived: str | None = Query(
        default="false",
        pattern="^(true|false|all|)$",
        description="false (défaut), true, all ou vide = tous",
    ),
) -> Page[ScenarioOut]:
    rows, total = await service.list_scenarios(
        session,
        principal,
        q=q,
        category=category,
        visibility=visibility,
        difficulty=difficulty,
        tag=tag,
        family_id=family,
        archived=parse_archived(archived),
        offset=paging.offset,
        limit=paging.page_size,
    )
    return Page[ScenarioOut](
        items=[ScenarioOut(**scenario_out(r.scenario, r.latest)) for r in rows],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.post(
    "/scenarios",
    response_model=ScenarioDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un scénario",
)
async def create_scenario(
    body: ScenarioCreateIn, principal: RequireEditor, session: SessionDep
) -> ScenarioDetailOut:
    with platform_errors():
        scenario, _ = await service.create_scenario(
            session,
            principal,
            principal,
            name=body.name,
            category=body.category,
            content=_content(body.content),
            slug=body.slug,
            visibility=body.visibility,
            classification=body.classification,
            tags=body.tags,
            fresh_until=body.fresh_until,
            changelog=body.changelog,
            owner_id=principal.user_id,
        )
    await session.commit()
    return await _detail(session, principal, scenario)


# --- Import / export (declared before /scenarios/{id}) ---------------------------------------------


async def _read_import(request: Request) -> tuple[str | bytes | dict[str, Any], bool | None]:
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type == "multipart/form-data":
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise bad_request("Fichier attendu dans le champ « file »")
        data = await upload.read(MAX_IMPORT_BYTES + 1)
        dry = form.get("dry_run")
        return data, (str(dry).lower() in ("1", "true", "yes", "on")) if dry is not None else None
    raw = await request.body()
    if len(raw) > MAX_IMPORT_BYTES:
        raise ApiError(413, "Fichier d'import trop volumineux (10 Mo maximum)", code="payload_too_large")
    if content_type in ("", "application/json"):
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            raise bad_request(f"JSON invalide : {exc.msg}") from exc
        if isinstance(payload, dict) and "format" not in payload:
            body = ImportIn.model_validate(payload)
            if body.bundle is not None:
                return body.bundle, body.dry_run
            if body.content is not None:
                return body.content, body.dry_run
            raise bad_request("Bundle attendu (« bundle » ou « content »)")
        return payload, None
    if content_type in YAML_TYPES:
        return raw, None
    raise ApiError(
        415, "Type de contenu non pris en charge (JSON, YAML ou multipart)", code="unsupported_media_type"
    )


@router.post(
    "/scenarios/import",
    response_model=ImportReportOut,
    summary="Importer un bundle forge.scenarios/v1 (JSON, YAML ou fichier)",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {"schema": ImportIn.model_json_schema()},
                "application/yaml": {"schema": {"type": "string"}},
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "dry_run": {"type": "boolean"},
                        },
                    }
                },
            }
        }
    },
)
async def import_scenarios(
    request: Request,
    principal: RequireEditor,
    session: SessionDep,
    dry_run: bool = Query(default=False, description="Valider sans rien enregistrer"),
) -> ImportReportOut:
    data, body_dry_run = await _read_import(request)
    with platform_errors():
        report = await service.import_bundle(
            session,
            principal,
            principal,
            data,
            dry_run=dry_run or bool(body_dry_run),
            created_by=principal.user_id,
        )
    await session.commit()
    return ImportReportOut.model_validate(
        {
            "dry_run": report.dry_run,
            "created": report.created,
            "updated": report.updated,
            "skipped": report.skipped,
            "errors": report.errors,
        }
    )


@router.get(
    "/scenarios/export",
    summary="Exporter des scénarios (bundle forge.scenarios/v1)",
    responses={200: {"content": {"application/yaml": {}, "application/json": {}}}},
)
async def export_scenarios(
    principal: RequireViewer,
    session: SessionDep,
    format: Literal["yaml", "json"] = "yaml",
    q: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=100),
    visibility: ScenarioVisibility | None = None,
    tag: str | None = Query(default=None, max_length=100),
    family: uuid.UUID | None = None,
    archived: bool | None = Query(default=False),
    ids: list[uuid.UUID] | None = Query(default=None, description="Identifiants de scénarios"),
    versions: Literal["all", "latest"] = "all",
) -> Response:
    result = await service.export_bundle(
        session,
        principal,
        q=q,
        category=category,
        visibility=visibility,
        tag=tag,
        family_id=family,
        archived=archived,
        scenario_ids=ids,
        all_versions=versions == "all",
    )
    text = dump_bundle(result.bundle, format)
    media = "application/json" if format == "json" else "application/yaml"
    return Response(
        content=text.encode("utf-8"),
        media_type=f"{media}; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="forge-scenarios.{format}"',
            "X-Forge-Skipped-Private": str(result.skipped_private),
            "X-Forge-Hidden-Rules-Removed": str(result.hidden_rules_removed),
        },
    )


# --- Scenario detail ----------------------------------------------------------------------------------


@router.get("/scenarios/{scenario_id}", response_model=ScenarioDetailOut, summary="Détail d'un scénario")
async def get_scenario(
    scenario_id: uuid.UUID, principal: RequireViewer, session: SessionDep
) -> ScenarioDetailOut:
    return await _detail(session, principal, await _scenario(session, principal, scenario_id))


@router.patch(
    "/scenarios/{scenario_id}", response_model=ScenarioDetailOut, summary="Modifier les métadonnées"
)
async def update_scenario(
    scenario_id: uuid.UUID, body: ScenarioUpdateIn, principal: RequireEditor, session: SessionDep
) -> ScenarioDetailOut:
    scenario = await _scenario(session, principal, scenario_id)
    with platform_errors():
        await service.update_scenario(
            session, principal, principal, scenario, body.model_dump(exclude_unset=True)
        )
    await session.commit()
    return await _detail(session, principal, scenario)


@router.get(
    "/scenarios/{scenario_id}/versions",
    response_model=list[ScenarioVersionOut],
    summary="Versions d'un scénario",
)
async def list_versions(
    scenario_id: uuid.UUID, principal: RequireViewer, session: SessionDep
) -> list[ScenarioVersionOut]:
    scenario = await _scenario(session, principal, scenario_id)
    return [
        ScenarioVersionOut(**service.version_view(principal, scenario, v))
        for v in await service.list_versions(session, scenario)
    ]


@router.post(
    "/scenarios/{scenario_id}/versions",
    response_model=ScenarioVersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Nouvelle version (contenu immuable)",
)
async def create_version(
    scenario_id: uuid.UUID, body: ScenarioVersionCreateIn, principal: RequireEditor, session: SessionDep
) -> ScenarioVersionOut:
    scenario = await _scenario(session, principal, scenario_id)
    with platform_errors():
        version = await service.create_version(
            session,
            principal,
            principal,
            scenario,
            _content(body.content),
            changelog=body.changelog,
            created_by=principal.user_id,
        )
    await session.commit()
    return ScenarioVersionOut(**service.version_view(principal, scenario, version))


@router.get(
    "/scenario-versions/{version_id}", response_model=ScenarioVersionOut, summary="Détail d'une version"
)
async def get_version(
    version_id: uuid.UUID, principal: RequireViewer, session: SessionDep
) -> ScenarioVersionOut:
    with platform_errors():
        scenario, version = await service.get_version(session, principal, version_id)
    return ScenarioVersionOut(**service.version_view(principal, scenario, version))


@router.post(
    "/scenarios/{scenario_id}/variants",
    response_model=ScenarioDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une variante (même famille)",
)
async def create_variant(
    scenario_id: uuid.UUID, body: VariantCreateIn, principal: RequireEditor, session: SessionDep
) -> ScenarioDetailOut:
    parent = await _scenario(session, principal, scenario_id)
    with platform_errors():
        variant, _ = await service.create_variant(
            session,
            principal,
            principal,
            parent,
            label=body.label,
            overrides=_content(body.overrides),
            name=body.name,
            tags=body.tags,
            visibility=body.visibility,
            changelog=body.changelog,
            owner_id=principal.user_id,
        )
    await session.commit()
    return await _detail(session, principal, variant)

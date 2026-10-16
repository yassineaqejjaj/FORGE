"""Router ``forget``: removal of copied content (ORBIT ``*.forgotten``, NOVA/ORBIT requests).

* ``POST /forget`` — authenticated (admin role: give NOVA / ORBIT a dedicated admin API key);
* ``POST /webhooks/orbit`` — ORBIT's signed webhook (``X-Orbit-Signature: sha256=<HMAC(secret, body)>``,
  secret ``FORGE_ORBIT_WEBHOOK_SECRET``); only ``memory.forgotten`` and ``document.forgotten`` act,
  every other event is acknowledged and ignored.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, Header, Request

from forge.api.deps import RequireAdmin, SessionDep
from forge.api.errors import ApiError, bad_request, unauthorized
from forge.api.schemas.forget import ForgetIn, ForgetOut, WebhookAck
from forge.config import settings
from forge.services import retention
from forge.services.audit import Actor
from forge.services.taxonomy import InvalidError

router = APIRouter(tags=["forget"])

FORGET_EVENTS = {"memory.forgotten", "document.forgotten"}


def _out(receipt: retention.ForgetReceipt) -> ForgetOut:
    return ForgetOut(
        processed_at=receipt.processed_at,
        source=receipt.source,
        runs=receipt.runs,
        traces=receipt.traces,
        trace_events=receipt.trace_events,
        evaluations=receipt.evaluations,
        scenario_versions=receipt.scenario_versions,
        manifests=receipt.manifests,
        feedback_reports=receipt.feedback_reports,
        judge_cache_entries=receipt.judge_cache_entries,
        nothing_matched=receipt.total() == 0,
    )


@router.post(
    "/forget",
    response_model=ForgetOut,
    summary="Oublier des copies de contenu (traces, évaluations, scénarios, caches)",
    description=(
        "Vide le texte copié par FORGE pour les `document_id`, `memory_item_id`, lignées de mémoire ou "
        "tâches NOVA indiqués : traces et payloads d'événements, prompts et réponses de juge, manifestes, "
        "contexte copié des scénarios promus, rapports de feedback, cache de juges. Les scores et "
        "métriques de mesure sont conservés. Idempotent ; l'accusé décrit ce qui a été touché."
    ),
)
async def forget(body: ForgetIn, principal: RequireAdmin, session: SessionDep) -> ForgetOut:
    try:
        receipt = await retention.forget(
            session,
            retention.ForgetRequest(
                document_ids=body.document_ids,
                memory_item_ids=body.memory_item_ids,
                lineage_ids=body.lineage_ids,
                task_ids=body.task_ids,
                reason=body.reason,
            ),
            actor=principal,
        )
    except InvalidError as exc:
        raise bad_request(str(exc)) from exc
    await session.commit()
    return _out(receipt)


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(header) and hmac.compare_digest(expected, str(header))


def forget_request_of(payload: dict[str, Any]) -> retention.ForgetRequest | None:
    """What an ORBIT ``*.forgotten`` event asks to forget (``None`` for any other event)."""
    event = str(payload.get("type") or "")
    if event not in FORGET_EVENTS:
        return None
    target = str(payload.get("target_id") or "")
    raw = payload.get("data")
    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
    request = retention.ForgetRequest(source="orbit_webhook", reason=f"ORBIT {event}")
    if event == "document.forgotten":
        request.document_ids = [target]
    else:
        request.memory_item_ids = [target]
        request.lineage_ids = [str(data["lineage_id"])] if data.get("lineage_id") else []
    return request


@router.post(
    "/webhooks/orbit",
    response_model=WebhookAck,
    summary="Webhook signé d'ORBIT (oubli de documents et de mémoires)",
    include_in_schema=True,
)
async def orbit_webhook(
    request: Request,
    session: SessionDep,
    x_orbit_signature: str | None = Header(default=None),
    x_orbit_event: str | None = Header(default=None),
) -> WebhookAck:
    secret = settings.orbit_webhook_secret
    if not secret:
        raise ApiError(
            503, "Webhook ORBIT non configuré (FORGE_ORBIT_WEBHOOK_SECRET)", code="webhook_disabled"
        )
    body = await request.body()
    if not verify_signature(secret, body, x_orbit_signature):
        raise unauthorized("Signature ORBIT invalide")
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise bad_request("Corps JSON invalide") from exc
    if not isinstance(payload, dict):
        raise bad_request("Corps JSON invalide")
    event = str(payload.get("type") or x_orbit_event or "")
    forget_request = forget_request_of(payload)
    if forget_request is None:
        return WebhookAck(handled=False, event=event)
    try:
        receipt = await retention.forget(session, forget_request, actor=Actor.system("orbit-webhook"))
    except InvalidError as exc:
        raise bad_request(str(exc)) from exc
    await session.commit()
    return WebhookAck(handled=True, event=event, receipt=_out(receipt))

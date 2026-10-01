# ruff: noqa: E501 — demo content: long French sentences are kept on one line for readability.
"""``support-agent`` — answers customer tickets by applying the return / refund policy of the context.

* **1.0** — model ``sim-standard-4``. Sometimes applies a 60-day window instead of the policy's,
  promises an unauthorised goodwill gesture, echoes the customer's e-mail / phone number, does not
  cite the policy and may call ``refund.create`` although the request is refused.
* **1.1** — model ``sim-efficient-2``. Applies the policy correctly (window, non-returnable
  categories, damaged items, escalation threshold), cites the policy document, only calls
  ``refund.create`` when a refund is granted; occasionally forgets the ticket reference.

Decisions (``output_json.decision``): ``refund``, ``replace_or_refund``, ``refuse``, ``escalate``,
``request_info``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from forge.demo_agents.common import (
    EMAIL_RE,
    PHONE_RE,
    AgentOutput,
    DemoRequest,
    Document,
    EventLog,
    as_dict,
    fold,
    seeded_rng,
    tokens,
    word_count,
)
from forge.domain.enums import TraceEventType

VERSIONS = ("1.0", "1.1")
MODELS = {"1.0": "sim-standard-4", "1.1": "sim-efficient-2"}
DEFAULT_WINDOW_DAYS = 30
WRONG_WINDOW_DAYS = 60
_DAMAGED = ("defectueu", "casse", "endommag", "abime", "ne fonctionne", "en panne", "fissure", "raye")
_DAYS_AGO = re.compile(r"il y a\s+(\d{1,3})\s*jours|(\d{1,3})\s*jours\s+(?:apres|depuis)")
_DECISION_LABELS = {
    "refund": "Retour accepté — remboursement après réception de l'article",
    "replace_or_refund": "Article défectueux — remplacement ou remboursement intégral",
    "refuse": "Demande de remboursement refusée (hors politique)",
    "escalate": "Demande transmise à un responsable",
    "request_info": "Informations complémentaires nécessaires",
}


@dataclass(slots=True)
class Policy:
    document: Document | None
    window_days: int = DEFAULT_WINDOW_DAYS
    damaged_window_days: int | None = None
    non_returnable: list[str] = field(default_factory=list)
    max_goodwill: float = 0.0
    escalation_amount: float | None = None


@dataclass(slots=True)
class Ticket:
    id: str
    customer_name: str
    email: str | None
    phone: str | None
    product: str
    category: str
    amount: float | None
    days_since_purchase: int | None
    damaged: bool


def _policy(request: DemoRequest) -> Policy:
    document = next(
        (
            d
            for d in request.documents
            if "polic" in fold(d.id + " " + d.title) or "politique" in fold(d.title)
        ),
        request.documents[0] if request.documents else None,
    )
    structured = as_dict(request.context.get("policy"))
    policy = Policy(document=document)
    text = fold(document.content) if document else ""
    match = re.search(r"(\d{1,3})\s*jours", text)
    policy.window_days = int(
        structured.get("return_window_days") or (match.group(1) if match else DEFAULT_WINDOW_DAYS)
    )
    damaged = structured.get("damaged_window_days")
    policy.damaged_window_days = int(damaged) if damaged else None
    categories = structured.get("non_returnable_categories")
    if categories is None:
        found = re.search(r"(?:non (?:repris|remboursables?|retournables?)|exclus?)\s*:?\s*([^.\n]+)", text)
        categories = [c.strip() for c in re.split(r",|\bet\b", found.group(1))] if found else []
    policy.non_returnable = [fold(str(c)) for c in categories if str(c).strip()]
    policy.max_goodwill = float(structured.get("max_goodwill_amount") or 0)
    threshold = structured.get("escalation_amount") or structured.get("escalation_threshold_amount")
    policy.escalation_amount = float(threshold) if threshold else None
    return policy


def _days(request: DemoRequest, order: dict[str, Any]) -> int | None:
    today_raw = request.input.get("today") or request.context.get("today")
    purchase = order.get("delivery_date") or order.get("purchase_date") or order.get("date")
    if today_raw and purchase:
        try:
            return (date.fromisoformat(str(today_raw)[:10]) - date.fromisoformat(str(purchase)[:10])).days
        except ValueError:
            pass
    if order.get("days_since_purchase") is not None:
        return int(order["days_since_purchase"])
    match = _DAYS_AGO.search(fold(request.prompt))
    return int(match.group(1) or match.group(2)) if match else None


def _ticket(request: DemoRequest) -> Ticket:
    raw = as_dict(request.input.get("ticket"))
    order = as_dict(raw.get("order"))
    customer = as_dict(raw.get("customer"))
    text = f"{request.prompt}\n{raw.get('body', '')}"
    email_match, phone_match = EMAIL_RE.search(text), PHONE_RE.search(text)
    email = customer.get("email") or (email_match.group(0) if email_match else None)
    phone = customer.get("phone") or (phone_match.group(0) if phone_match else None)
    condition = fold(str(order.get("condition") or ""))
    damaged = condition in ("damaged", "defective", "defectueux") or any(k in fold(text) for k in _DAMAGED)
    amount = order.get("amount")
    return Ticket(
        id=str(raw.get("id") or request.input.get("ticket_id") or "T-0000"),
        customer_name=str(customer.get("name") or "Madame, Monsieur"),
        email=str(email) if email else None,
        phone=str(phone) if phone else None,
        product=str(order.get("product") or "votre article"),
        category=fold(str(order.get("category") or "")),
        amount=float(amount) if amount is not None else None,
        days_since_purchase=_days(request, order),
        damaged=damaged,
    )


def non_returnable(policy: Policy, ticket: Ticket) -> bool:
    return bool(ticket.category) and any(c and c in ticket.category for c in policy.non_returnable)


def decide(policy: Policy, ticket: Ticket, window_days: int) -> str:
    """Correct policy application (1.1); 1.0 calls it with a wrong ``window_days`` sometimes."""
    if non_returnable(policy, ticket) and not ticket.damaged:
        return "refuse"
    if ticket.days_since_purchase is None:
        return "request_info"
    if ticket.damaged:
        limit = policy.damaged_window_days or max(window_days, policy.window_days)
        return "replace_or_refund" if ticket.days_since_purchase <= limit else "escalate"
    if ticket.days_since_purchase > window_days:
        return "refuse"
    if policy.escalation_amount is not None and (ticket.amount or 0) > policy.escalation_amount:
        return "escalate"
    return "refund"


def run(request: DemoRequest, version: str) -> AgentOutput:
    rng = seeded_rng("support-agent", version, request.seed_material)
    model = MODELS[version]
    log = EventLog()
    behaviors: list[str] = []
    policy = _policy(request)
    ticket = _ticket(request)
    log.tool(
        "crm.lookup_order",
        {"ticket_id": ticket.id},
        {
            "product": ticket.product,
            "amount": ticket.amount,
            "days_since_purchase": ticket.days_since_purchase,
        },
        rng.uniform(150, 300),
    )
    window = policy.window_days
    if version == "1.0" and rng.random() < 0.5:
        window = WRONG_WINDOW_DAYS
        behaviors.append(f"délai de {WRONG_WINDOW_DAYS} jours appliqué au lieu de {policy.window_days}")
    decision = decide(policy, ticket, window)
    log.add(
        TraceEventType.retrieval,
        "Lecture de la politique de retour",
        rng.uniform(80, 180),
        output={"window_days": policy.window_days, "non_returnable": policy.non_returnable},
        attributes={
            "documents": [policy.document.id] if policy.document else [],
            "documents_count": 1 if policy.document else 0,
        },
    )
    log.add(
        TraceEventType.decision,
        "Décision",
        rng.uniform(40, 90),
        output=f"{_DECISION_LABELS[decision]} (achat il y a {ticket.days_since_purchase} jours, délai {window} jours)",
        attributes={"decision": decision},
    )
    if decision in ("refund", "replace_or_refund") or (version == "1.0" and rng.random() < 0.3):
        if decision not in ("refund", "replace_or_refund"):
            behaviors.append("refund.create appelé sur une demande refusée")
        log.tool(
            "refund.create",
            {"ticket_id": ticket.id, "amount": ticket.amount},
            {"status": "created", "reference": f"RMB-{rng.randint(10000, 99999)}"},
            rng.uniform(150, 280),
        )
    text = _reply(version, rng, policy, ticket, decision, window, behaviors)
    latency = rng.uniform(900, 1500) if version == "1.0" else rng.uniform(1100, 1700)
    context_tokens = sum(tokens(d.content) for d in request.documents)
    log.llm_call(
        "Rédaction de la réponse client",
        model,
        tokens(request.prompt) + context_tokens + 300,
        int(word_count(text) * 1.4) + 30,
        latency,
    )
    output_json = {
        "decision": decision,
        "ticket_id": ticket.id,
        "policy_reference": policy.document.id if policy.document and version != "1.0" else None,
        "days_since_purchase": ticket.days_since_purchase,
        "window_days": window,
    }
    return AgentOutput(text=text, log=log, model=model, output_json=output_json, behaviors=behaviors)


def _reply(
    version: str, rng: Any, policy: Policy, ticket: Ticket, decision: str, window: int, behaviors: list[str]
) -> str:
    cite = f" [{policy.document.id}]" if policy.document and version == "1.1" else ""
    reference = ticket.id
    if version == "1.1" and rng.random() < 0.15:
        reference = ""
        behaviors.append("référence du ticket omise")
    lines = [f"**Décision :** {_DECISION_LABELS[decision]}", ""]
    lines.append(f"Bonjour {ticket.customer_name},")
    lines.append("")
    lines.append(
        "Merci pour votre message" + (f" concernant le dossier {reference}" if reference else "") + "."
    )
    days = ticket.days_since_purchase
    if decision == "refund":
        lines.append(
            f"Votre achat de {ticket.product} date de {days} jours : il entre dans le délai de retour de "
            f"{window} jours prévu par notre politique{cite}. Vous pouvez nous renvoyer l'article ; le "
            "remboursement sera effectué sur votre moyen de paiement initial sous 14 jours après réception."
        )
    elif decision == "replace_or_refund":
        lines.append(
            f"Nous sommes désolés que {ticket.product} soit arrivé défectueux. Conformément à notre "
            f"politique{cite}, nous vous proposons un remplacement ou un remboursement intégral, "
            "frais de retour à notre charge."
        )
    elif decision == "refuse":
        reason = (
            "cette catégorie d'article n'est pas reprise"
            if non_returnable(policy, ticket)
            else f"le délai de retour de {window} jours est dépassé ({days} jours)"
        )
        lines.append(
            f"Après vérification, nous ne pouvons pas donner une suite favorable : {reason}, "
            f"conformément à notre politique{cite}. La garantie constructeur reste applicable."
        )
    elif decision == "escalate":
        lines.append(
            f"Votre demande nécessite l'accord d'un responsable{cite}. Elle lui a été transmise et "
            "vous recevrez une réponse sous 48 heures ouvrées."
        )
    else:
        lines.append(
            "Pourriez-vous nous indiquer la date d'achat ou de livraison ainsi que le numéro de commande ? "
            "Nous pourrons alors vérifier votre éligibilité."
        )
    if version == "1.0" and rng.random() < 0.35 and policy.max_goodwill < 30:
        behaviors.append("geste commercial non autorisé")
        lines.append(
            "À titre exceptionnel, nous vous offrons également un bon d'achat de 30 € sur votre prochaine commande."
        )
    if version == "1.0" and (ticket.email or ticket.phone) and rng.random() < 0.3:
        behaviors.append("coordonnées client recopiées")
        contact = ticket.email or ticket.phone
        lines.append(f"Nous vous recontacterons si nécessaire à l'adresse {contact}.")
    lines += ["", "Cordialement,", "Le service client"]
    if version == "1.1":
        lines += [
            "",
            "---",
            f"*Note interne : décision « {decision} », délai appliqué {window} jours, "
            f"politique {policy.document.id if policy.document else 'non trouvée'}.*",
        ]
    return "\n".join(lines) + "\n"

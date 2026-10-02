# ruff: noqa: E501 — demo content: long French sentences are kept on one line for readability.
"""Agents of the demo data set: prompts (with their history), simulated model configurations, tool
configurations and agent versions with the changelogs of the improvement loop.

The agents are the simulated demo agents (``forge.demo_agents``, docs/DEMO_AGENTS.md), called through
the ``custom_api`` adapter (FORGE Agent Protocol). Their behaviour is fixed by the demo service; the
prompts, models and tools recorded here document *why* each version behaves as it does, which is what
the version diff of the UI shows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- Simulated models (pricing of docs/DEMO_AGENTS.md) -------------------------------------------------

MODELS: dict[str, dict[str, Any]] = {
    "sim-standard-4": {
        "name": "NOVA sim-standard-4 (simulé)",
        "provider": "nova",
        "model": "sim-standard-4",
        "model_version": "2026-03",
        "temperature": 0.3,
        "max_tokens": 4000,
        "input_cost_per_mtok": 2.50,
        "output_cost_per_mtok": 10.00,
        "params": {"simulated": True},
    },
    "sim-efficient-2": {
        "name": "NOVA sim-efficient-2 (simulé)",
        "provider": "nova",
        "model": "sim-efficient-2",
        "model_version": "2026-07",
        "temperature": 0.2,
        "max_tokens": 4000,
        "input_cost_per_mtok": 0.40,
        "output_cost_per_mtok": 1.60,
        "params": {"simulated": True},
    },
}

# --- Tools -------------------------------------------------------------------------------------------------


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


SEARCH_WEB = _tool("search.web", "Recherche sur le web public.", {"query": {"type": "string"}}, ["query"])
JIRA_SEARCH = _tool(
    "jira.search",
    "Recherche de tickets existants dans Jira (projet PROD).",
    {"query": {"type": "string"}, "project": {"type": "string"}},
    ["query"],
)
CRM_LOOKUP = _tool(
    "crm.lookup_order",
    "Consulte la commande associée à un ticket.",
    {"ticket_id": {"type": "string"}},
    ["ticket_id"],
)
REFUND_CREATE = _tool(
    "refund.create",
    "Crée un remboursement dans le back-office.",
    {"ticket_id": {"type": "string"}, "amount": {"type": "number"}},
    ["ticket_id", "amount"],
)
DOCS_SEARCH = _tool(
    "documents.search",
    "Recherche plein texte dans le corpus documentaire.",
    {"query": {"type": "string"}},
    ["query"],
)

#: Tool configurations in creation order: (name, description, tools). Same name ⇒ next version.
TOOL_CONFIGS: list[tuple[str, str, list[dict[str, Any]]]] = [
    ("product-agent-tools", "Outils de ProductAgent : recherche web et Jira.", [SEARCH_WEB, JIRA_SEARCH]),
    (
        "product-agent-tools",
        "Outils de ProductAgent : Jira seulement (recherche web retirée, inutile avec le contexte fourni).",
        [JIRA_SEARCH],
    ),
    ("support-agent-tools", "Outils de SupportAgent : CRM et remboursements.", [CRM_LOOKUP, REFUND_CREATE]),
    ("research-agent-tools", "Outils de ResearchAgent : recherche documentaire.", [DOCS_SEARCH]),
]

# --- Prompts -----------------------------------------------------------------------------------------------

_PM_BASE = (
    "Tu es ProductAgent, l'assistant product manager de Nordalis (logiciel de facturation et de notes de frais pour les PME).\n"
    "Tu rédiges des PRD, des user stories et des synthèses discovery en français, en Markdown."
)
#: Instructions added one by one over the first ten versions of the ``product_manager`` prompt.
_PM_HISTORY = [
    "Commence chaque livrable par un titre de niveau 1.",
    "Structure un PRD avec : Contexte et problème, Objectifs, Périmètre, Exigences fonctionnelles, Critères d'acceptation, Indicateurs de succès, Risques et questions ouvertes.",
    "Formule les user stories sous la forme « En tant que …, je veux … afin de … ».",
    "Ajoute à chaque user story des critères d'acceptation au format Étant donné / Quand / Alors.",
    "Termine par une section Sources listant les documents utilisés.",
    "Appuie chaque constat sur un document du contexte.",
    "Pour une synthèse discovery, sépare constats, verbatims, opportunités, hypothèses et prochaines étapes.",
    "Utilise le vocabulaire métier de Nordalis (factures, avoirs, notes de frais, relances).",
    "Signale explicitement les hypothèses non vérifiées.",
]
_PM_V11 = (
    "Charge l'intégralité des documents de contexte dans ta réflexion avant de rédiger.\n"
    "Complète si besoin par une recherche web (outil search.web)."
)
_PM_V12 = (
    "Recherche d'abord les passages pertinents des documents (recherche ciblée), re-classe-les par pertinence et n'utilise que les meilleurs.\n"
    "Cite chaque affirmation avec l'identifiant du document qui la soutient, au format [doc-id].\n"
    "Ne recopie jamais une adresse e-mail ou un numéro de téléphone : omets-les.\n"
    "Pour les user stories, vérifie les doublons dans Jira (outil jira.search) et détaille chaque story."
)
_PM_V13 = (
    "Recherche les passages pertinents des documents et cite chaque affirmation au format [doc-id].\n"
    "Respecte strictement toute limite de longueur de la consigne (« Maximum N mots ») : raccourcis plutôt que de dépasser.\n"
    "Remplace toute donnée personnelle par « [e-mail masqué] » ou « [téléphone masqué] ».\n"
    "Pour les user stories, vérifie les doublons dans Jira (outil jira.search)."
)


def product_manager_prompts() -> list[tuple[str, str]]:
    """(description, content) of versions 1 → 13 of the ``product_manager`` prompt."""
    versions: list[tuple[str, str]] = [("Version initiale", _PM_BASE)]
    for index, line in enumerate(_PM_HISTORY, start=2):
        versions.append((f"Ajout : {line[:70]}", "\n".join([_PM_BASE, *(_PM_HISTORY[: index - 1])])))
    history = "\n".join([_PM_BASE, *_PM_HISTORY])
    versions.append(
        (
            "v11 — ProductAgent 1.2 : tout le contexte dans le prompt, recherche web autorisée",
            f"{history}\n{_PM_V11}",
        )
    )
    versions.append(
        (
            "v12 — ProductAgent 1.3 : recherche ciblée, re-classement, citations, données personnelles omises",
            f"{history}\n{_PM_V12}",
        )
    )
    versions.append(
        (
            "v13 — ProductAgent 1.4 : limites de longueur strictes, masquage des données personnelles",
            f"{history}\n{_PM_V13}",
        )
    )
    return versions


SUPPORT_PROMPTS = [
    (
        "v1 — SupportAgent 1.0",
        "Tu es l'agent du service client Nordalis. Réponds aux demandes de retour et de remboursement avec bienveillance.\n"
        "Privilégie la satisfaction du client ; un geste commercial est possible si le client est mécontent.",
    ),
    (
        "v2 — SupportAgent 1.1 : application stricte de la politique",
        "Tu es l'agent du service client Nordalis. Applique strictement la politique de retour fournie dans le contexte : délai, catégories non remboursables, appareils défectueux, seuil d'escalade.\n"
        "Cite la politique au format [doc-id]. Aucun geste commercial sans accord écrit. Ne recopie jamais les coordonnées du client.\n"
        "Ne crée un remboursement (refund.create) que si la demande est acceptée. Ajoute une note interne récapitulant la décision.",
    ),
]
RESEARCH_PROMPTS = [
    (
        "v1 — ResearchAgent 1.0",
        "Tu es ResearchAgent. Réponds aux questions uniquement à partir des documents fournis, en citant chaque passage au format [doc-id].\n"
        "Si les documents ne permettent pas de répondre, dis-le explicitement. Masque les données personnelles.",
    ),
]

# --- Agents & versions -------------------------------------------------------------------------------------


@dataclass(slots=True)
class VersionDef:
    label: str
    demo_version: str  # version of the demo agent service
    model: str
    prompt: tuple[str, int]  # (prompt name, version number)
    tools: tuple[str, int]  # (tool configuration name, version number)
    changelog: str


@dataclass(slots=True)
class AgentDef:
    slug: str  # FORGE agent slug (also the demo agent slug)
    name: str
    description: str
    provider: str
    tags: list[str]
    versions: list[VersionDef] = field(default_factory=list)


AGENTS: list[AgentDef] = [
    AgentDef(
        slug="product-agent",
        name="ProductAgent",
        description="Assistant product manager de Nordalis : PRD, user stories et synthèses discovery à partir des entretiens, spécifications et indicateurs.",
        provider="NOVA (démo)",
        tags=["nordalis", "produit", "démo"],
        versions=[
            VersionDef(
                "1.2",
                "1.2",
                "sim-standard-4",
                ("product_manager", 11),
                ("product-agent-tools", 1),
                "Version de référence en production. Modèle sim-standard-4, prompt product_manager v11 : tout le contexte est chargé dans le prompt, recherche web autorisée.",
            ),
            VersionDef(
                "1.3",
                "1.3",
                "sim-efficient-2",
                ("product_manager", 12),
                ("product-agent-tools", 2),
                "Suite au feedback des runs v1.2 (critères d'acceptation omis, citations non étayées, e-mail client recopié, recherche web inutile) : "
                "recherche ciblée + re-classement des passages, citations [doc-id] obligatoires, données personnelles omises, modèle sim-efficient-2 (≈ 6× moins cher), outil search.web retiré.",
            ),
            VersionDef(
                "1.4",
                "1.4",
                "sim-efficient-2",
                ("product_manager", 13),
                ("product-agent-tools", 2),
                "Correctifs issus de l'expérience v1.2 → v1.3 : la v1.3 dépassait les limites de mots sur les user stories et les synthèses discovery et était plus lente. "
                "Limites de longueur strictes, re-classement supprimé (latence), e-mails masqués « [e-mail masqué] ».",
            ),
        ],
    ),
    AgentDef(
        slug="support-agent",
        name="SupportAgent",
        description="Agent du service client Nordalis : demandes de retour et de remboursement du matériel (lecteurs Nordalis Scan) et des services.",
        provider="NOVA (démo)",
        tags=["nordalis", "support", "démo"],
        versions=[
            VersionDef(
                "1.0",
                "1.0",
                "sim-standard-4",
                ("support_agent", 1),
                ("support-agent-tools", 1),
                "Première version : réponses bienveillantes, gestes commerciaux possibles.",
            ),
            VersionDef(
                "1.1",
                "1.1",
                "sim-efficient-2",
                ("support_agent", 2),
                ("support-agent-tools", 1),
                "Application stricte de la politique de retour (délai de 30 jours, catégories non remboursables, seuil d'escalade), politique citée, aucun geste commercial, coordonnées jamais recopiées, modèle sim-efficient-2.",
            ),
        ],
    ),
    AgentDef(
        slug="research-agent",
        name="ResearchAgent",
        description="Questions-réponses citées sur le corpus documentaire de Nordalis (politiques, spécifications).",
        provider="NOVA (démo)",
        tags=["nordalis", "recherche", "démo"],
        versions=[
            VersionDef(
                "1.0",
                "1.0",
                "sim-efficient-2",
                ("research_agent", 1),
                ("research-agent-tools", 1),
                "Première version : réponses citées [doc-id], refus de répondre hors corpus.",
            )
        ],
    ),
]

# ruff: noqa: E501 — demo content: long French sentences are kept on one line for readability.
"""Catalog of the demo agents (``GET /agents``) and dispatch to their implementation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from forge.demo_agents import product, research, support
from forge.demo_agents.common import AgentOutput, DemoRequest


@dataclass(frozen=True, slots=True)
class VersionInfo:
    version: str
    model: str
    summary: str
    traits: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentInfo:
    slug: str
    name: str
    description: str
    tasks: tuple[str, ...]
    run: Callable[[DemoRequest, str], AgentOutput]
    versions: tuple[VersionInfo, ...] = field(default_factory=tuple)

    def version(self, label: str) -> VersionInfo | None:
        return next((v for v in self.versions if v.version == label), None)


AGENTS: dict[str, AgentInfo] = {
    "product-agent": AgentInfo(
        slug="product-agent",
        name="ProductAgent",
        description="Rédige des PRD, des user stories et des synthèses discovery à partir d'un brief et de documents.",
        tasks=("prd", "user_stories", "discovery"),
        run=product.run,
        versions=(
            VersionInfo(
                "1.2",
                "sim-standard-4",
                "Version de référence : tout le contexte dans le prompt.",
                (
                    "critères d'acceptation parfois omis",
                    "citations parfois non étayées",
                    "recopie parfois un e-mail client",
                    "appel d'outil inutile (search.web)",
                    "coût élevé",
                ),
            ),
            VersionInfo(
                "1.3",
                "sim-efficient-2",
                "Recherche ciblée + re-classement : meilleure qualité, moins chère.",
                ("plus lente", "dépasse la limite de mots sur les user stories et synthèses discovery"),
            ),
            VersionInfo(
                "1.4",
                "sim-efficient-2",
                "Corrige les limites de longueur, masque les données personnelles.",
                ("oublie parfois les indicateurs de succès d'un PRD",),
            ),
        ),
    ),
    "support-agent": AgentInfo(
        slug="support-agent",
        name="SupportAgent",
        description="Répond aux tickets clients en appliquant la politique de retour et de remboursement.",
        tasks=("customer_support",),
        run=support.run,
        versions=(
            VersionInfo(
                "1.0",
                "sim-standard-4",
                "Première version.",
                (
                    "applique parfois un délai de 60 jours",
                    "geste commercial non autorisé",
                    "recopie les coordonnées du client",
                    "ne cite pas la politique",
                ),
            ),
            VersionInfo(
                "1.1",
                "sim-efficient-2",
                "Application stricte de la politique, cite la source.",
                ("oublie parfois la référence du ticket",),
            ),
        ),
    ),
    "research-agent": AgentInfo(
        slug="research-agent",
        name="ResearchAgent",
        description="Répond à des questions sur un corpus documentaire avec citations [doc-id].",
        tasks=("document_research",),
        run=research.run,
        versions=(
            VersionInfo(
                "1.0",
                "sim-efficient-2",
                "Questions-réponses documentaires citées.",
                ("ajoute parfois une affirmation générale non sourcée",),
            ),
        ),
    ),
}


def find(slug: str, version: str) -> tuple[AgentInfo, VersionInfo] | None:
    agent = AGENTS.get(slug)
    if agent is None:
        return None
    info = agent.version(version)
    return (agent, info) if info else None

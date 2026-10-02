"""Router ``meta``: vocabularies with French labels, rule types, adapters, capabilities (§12).

Also hosts :func:`platform_errors`, the translation of platform service errors
(``forge.services.taxonomy.PlatformError``) into the uniform API error format, shared by the
platform routers.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from forge.api.deps import RequireViewer, SessionDep
from forge.api.errors import ApiError
from forge.api.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PageParams
from forge.api.schemas.meta import (
    AdapterKindOut,
    Capabilities,
    EnumOption,
    MetaCriterion,
    MetaErrorType,
    MetaOut,
    RuleTypeOut,
)
from forge.config import settings
from forge.domain.defaults import DEFAULT_JUDGED_CRITERIA
from forge.domain.enums import (
    CLASSIFICATION_LABELS,
    DIMENSION_LABELS,
    SCENARIO_CATEGORIES,
    AdapterKind,
    AggregationMethod,
    CalibrationStatus,
    ContextSource,
    DatasetKind,
    Difficulty,
    Dimension,
    ErrorSeverity,
    EvaluatorKind,
    ExecutionStatus,
    ExperimentArm,
    GateAction,
    JudgeProvider,
    PiiType,
    Priority,
    ProviderKind,
    Recommendation,
    RecommendationCategory,
    RegressionSeverity,
    Role,
    RunOrigin,
    RunStatus,
    ScenarioVisibility,
    ScoreSource,
    TraceEventType,
    Verdict,
)
from forge.domain.scenarios.rule_schemas import rule_type_catalog
from forge.infra.models import Judge
from forge.infra.security import API_KEY_HEADER
from forge.services import taxonomy as taxonomy_service
from forge.services.taxonomy import PlatformError

router = APIRouter(tags=["meta"])


@contextmanager
def platform_errors() -> Iterator[None]:
    """Translate :class:`PlatformError` raised by platform services into :class:`ApiError`."""
    try:
        yield
    except PlatformError as exc:
        raise ApiError(exc.status_code, exc.message, code=exc.code, errors=exc.errors or None) from exc


def parse_archived(value: str | None) -> bool | None:
    """``?archived=`` filter: ``true`` / ``false`` (default) / ``all`` or empty for every row."""
    if value in (None, "", "all"):
        return None
    return value == "true"


def page_params(
    page: int = Query(default=1, ge=1, description="Numéro de page (à partir de 1)"),
    page_size: int = Query(
        default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Éléments par page"
    ),
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


#: Pagination dependency (``?page=1&page_size=25``) shared by the platform routers.
PageQuery = Annotated[PageParams, Depends(page_params)]


# --- French labels ---------------------------------------------------------------------------------

LABELS: dict[type[StrEnum], dict[str, str]] = {
    Role: {
        "viewer": "Lecteur",
        "evaluator": "Évaluateur",
        "editor": "Éditeur",
        "maintainer": "Mainteneur",
        "admin": "Administrateur",
    },
    AdapterKind: {
        "openai": "OpenAI (compatible)",
        "anthropic": "Anthropic",
        "nova": "NOVA",
        "custom_api": "API personnalisée",
        "mock": "Agent simulé",
    },
    ProviderKind: {
        "openai": "OpenAI (compatible)",
        "anthropic": "Anthropic",
        "nova": "NOVA",
        "orbit": "ORBIT",
        "http": "HTTP (jeton / en-têtes)",
    },
    ContextSource: {
        "scenario": "Contexte du scénario",
        "orbit_snapshot": "Instantané ORBIT",
        "orbit_live": "ORBIT en direct",
        "none": "Aucun contexte",
    },
    ScenarioVisibility: {"public": "Public", "private": "Privé", "fresh": "Récent (fresh)"},
    Difficulty: {"easy": "Facile", "medium": "Moyen", "hard": "Difficile", "expert": "Expert"},
    DatasetKind: {"context": "Contexte (documents)", "gold": "Gold (calibration)"},
    RunStatus: {
        "pending": "En attente",
        "running": "En cours",
        "evaluating": "En évaluation",
        "completed": "Terminé",
        "failed": "Échec",
        "cancelled": "Annulé",
    },
    RunOrigin: {"adhoc": "Ad hoc", "benchmark": "Benchmark", "experiment": "Expérience"},
    ExperimentArm: {"baseline": "Référence (baseline)", "candidate": "Candidate"},
    Dimension: {d.value: label for d, label in DIMENSION_LABELS.items()},
    EvaluatorKind: {
        "rule": "Règle",
        "metric": "Métrique",
        "llm_judge": "Juge IA",
        "human": "Humain",
        "aggregate": "Agrégat",
    },
    ScoreSource: {"ai": "IA", "rule": "Règle", "metric": "Métrique", "human": "Humain"},
    JudgeProvider: {
        "openai": "OpenAI (compatible)",
        "anthropic": "Anthropic",
        "heuristic": "Heuristique (hors ligne)",
    },
    AggregationMethod: {
        "mean": "Moyenne",
        "median": "Médiane",
        "majority_vote": "Vote majoritaire",
        "weighted": "Moyenne pondérée",
        "min": "Minimum (le plus sévère)",
        "custom": "Expression personnalisée",
    },
    ErrorSeverity: {"low": "Faible", "medium": "Moyenne", "high": "Haute", "critical": "Critique"},
    GateAction: {"fail": "Échec du run", "cap": "Plafonnement du score"},
    RecommendationCategory: {
        "system_prompt": "Prompt système",
        "rule": "Règle",
        "retrieval": "Recherche documentaire",
        "model": "Modèle",
        "context": "Contexte",
        "tools": "Outils",
        "orchestration": "Orchestration",
        "memory": "Mémoire",
        "output_format": "Format de sortie",
    },
    Priority: {"p0": "P0 — immédiat", "p1": "P1 — important", "p2": "P2 — à planifier"},
    ExecutionStatus: {
        "draft": "Brouillon",
        "queued": "En file",
        "running": "En cours",
        "aggregating": "Agrégation",
        "completed": "Terminé",
        "failed": "Échec",
        "cancelled": "Annulé",
    },
    Verdict: {
        "better": "Meilleur",
        "worse": "Moins bon",
        "equivalent": "Équivalent",
        "inconclusive": "Non concluant",
    },
    RegressionSeverity: {"minor": "Mineure", "major": "Majeure", "critical": "Critique"},
    Recommendation: {
        "ship": "Déployer",
        "ship_with_caution": "Déployer avec prudence",
        "do_not_ship": "Ne pas déployer",
        "inconclusive": "Non concluant",
    },
    CalibrationStatus: {
        "calibrated": "Calibré",
        "weak": "Accord faible",
        "uncalibrated": "Non calibré",
        "insufficient_data": "Données insuffisantes",
    },
    TraceEventType: {
        "run_started": "Démarrage",
        "context_prepared": "Contexte préparé",
        "reasoning": "Raisonnement",
        "message": "Message",
        "llm_call": "Appel au modèle",
        "tool_call": "Appel d'outil",
        "tool_result": "Résultat d'outil",
        "retrieval": "Recherche documentaire",
        "memory": "Mémoire",
        "agent_handoff": "Délégation",
        "decision": "Décision",
        "error": "Erreur",
        "final_answer": "Réponse finale",
        "run_completed": "Fin du run",
        "custom": "Étape",
    },
    PiiType: {
        "EMAIL": "E-mail",
        "PHONE": "Téléphone",
        "IBAN": "IBAN",
        "CARD": "Carte bancaire",
        "NIR": "Numéro de sécurité sociale",
        "IP": "Adresse IP",
        "PERSON": "Nom de personne",
    },
}

ENUM_KEYS: dict[str, type[StrEnum]] = {
    "roles": Role,
    "adapter_kinds": AdapterKind,
    "provider_kinds": ProviderKind,
    "context_sources": ContextSource,
    "visibility": ScenarioVisibility,
    "difficulty": Difficulty,
    "dataset_kinds": DatasetKind,
    "run_statuses": RunStatus,
    "run_origins": RunOrigin,
    "experiment_arms": ExperimentArm,
    "dimensions": Dimension,
    "evaluator_kinds": EvaluatorKind,
    "score_sources": ScoreSource,
    "judge_providers": JudgeProvider,
    "aggregation_methods": AggregationMethod,
    "severities": ErrorSeverity,
    "gate_actions": GateAction,
    "recommendation_categories": RecommendationCategory,
    "priorities": Priority,
    "execution_statuses": ExecutionStatus,
    "verdicts": Verdict,
    "regression_severities": RegressionSeverity,
    "recommendations": Recommendation,
    "calibration_statuses": CalibrationStatus,
    "trace_event_types": TraceEventType,
    "pii_types": PiiType,
}

ADAPTERS: list[dict[str, object]] = [
    {
        "kind": AdapterKind.mock,
        "description": "Agent scripté déterministe (tests, démonstrations) : sortie, événements, "
        "latence, erreurs.",
        "requires_model": False,
        "requires_endpoint": False,
        "credential_kinds": [],
        "adapter_config": {
            "script.output": "Texte de la réponse (gabarits {{input.prompt}}, {{context}}, {{repetition}}…)",
            "script.output_json": "Sortie JSON optionnelle",
            "script.events": "Événements simulés [{type, name, input?, output?, attributes?, duration_ms?}]",
            "script.usage": "{input_tokens, output_tokens} (sinon somme des événements llm_call)",
            "script.cost": "Coût rapporté",
            "script.model": "Modèle rapporté",
            "script.latency_ms": "Latence simulée (ms), répartie sur les événements",
            "script.error": "{message, retryable, error_type} : échec simulé",
            "script.fail_on_attempts": "Tentatives en échec transitoire (ex. [1])",
            "script.by_repetition": 'Surcharges par répétition {"1": {output: …}}',
        },
        "example": {
            "adapter_kind": "mock",
            "adapter_config": {
                "script": {
                    "output": "# PRD\n## Objectifs\n…",
                    "latency_ms": 800,
                    "usage": {"input_tokens": 900, "output_tokens": 400},
                }
            },
        },
    },
    {
        "kind": AdapterKind.openai,
        "description": "Chat completions compatibles OpenAI (OpenAI, vLLM, Ollama, Mistral…) : "
        "FORGE pilote la "
        "boucle d'agent (prompt système, outils, mocks du scénario, budget.max_steps tours).",
        "requires_model": True,
        "requires_endpoint": False,
        "credential_kinds": ["openai"],
        "adapter_config": {
            "base_url": "URL de l'API compatible (sinon celle de l'identifiant ou de l'endpoint)"
        },
        "example": {
            "adapter_kind": "openai",
            "model": {"provider": "openai", "model": "gpt-5-mini", "temperature": 0.2},
            "credential_id": "<identifiant openai>",
        },
    },
    {
        "kind": AdapterKind.anthropic,
        "description": "API Messages d'Anthropic : FORGE pilote la boucle d'agent avec les outils déclarés.",
        "requires_model": True,
        "requires_endpoint": False,
        "credential_kinds": ["anthropic"],
        "adapter_config": {"base_url": "URL de l'API (sinon celle de l'identifiant)"},
        "example": {
            "adapter_kind": "anthropic",
            "model": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001", "temperature": 0.2},
            "credential_id": "<identifiant anthropic>",
        },
    },
    {
        "kind": AdapterKind.nova,
        "description": "Agents NOVA via le NOVA Agent Protocol (délégations multi-agents tracées).",
        "requires_model": False,
        "requires_endpoint": False,
        "credential_kinds": ["nova"],
        "adapter_config": {
            "nova_agent_id": "Identifiant de l'agent NOVA (requis)",
            "path": "Chemin de l'appel (défaut /v1/agents/{nova_agent_id}/runs)",
            "base_url": "URL de NOVA (sinon celle de l'identifiant ou l'endpoint)",
            "nova_options": "Options transmises à NOVA",
        },
        "example": {
            "adapter_kind": "nova",
            "endpoint": "https://nova.example.com",
            "adapter_config": {"nova_agent_id": "product-agent"},
            "credential_id": "<identifiant nova>",
        },
    },
    {
        "kind": AdapterKind.custom_api,
        "description": "N'importe quel agent HTTP : FORGE Agent Protocol (mode « forge », défaut) "
        "ou requête / "
        "réponse décrites par un gabarit (mode « mapped »).",
        "requires_model": False,
        "requires_endpoint": True,
        "credential_kinds": ["http"],
        "adapter_config": {
            "mode": "forge (défaut, FORGE Agent Protocol) ou mapped",
            "url": "URL de l'appel (sinon l'endpoint de la version)",
            "method": "Méthode HTTP (mode mapped, défaut POST)",
            "headers": "En-têtes ({{credentials.api_key}} autorisé ; secrets dans l'identifiant)",
            "body_template": "Gabarit JSON du corps ({{input.prompt}}, {{context}}, {{system_prompt}}…)",
            "output_path": "Chemin JSON du texte de réponse (défaut output)",
            "output_json_path": "Chemin JSON de la sortie structurée",
            "usage_paths": "{input_tokens, output_tokens} : chemins JSON de la consommation",
            "cost_path": "Chemin JSON du coût",
            "events_path": "Chemin JSON des événements",
            "error_path": "Chemin JSON d'un message d'erreur",
        },
        "example": {
            "adapter_kind": "custom_api",
            "endpoint": "https://agents.example.com/run",
            "adapter_config": {
                "mode": "mapped",
                "body_template": {"question": "{{input.prompt}}"},
                "output_path": "answer",
            },
        },
    },
]


def enum_options(enum_cls: type[StrEnum]) -> list[EnumOption]:
    labels = LABELS.get(enum_cls, {})
    return [EnumOption(value=m.value, label=labels.get(m.value, m.value)) for m in enum_cls]


@router.get("/meta", response_model=MetaOut, summary="Vocabulaires, énumérations et capacités")
async def get_meta(principal: RequireViewer, session: SessionDep) -> MetaOut:
    criteria = await taxonomy_service.list_criteria(session)
    error_types = await taxonomy_service.list_error_types(session)
    llm_judges = await session.scalar(
        select(Judge.id)
        .where(Judge.enabled.is_(True), Judge.is_latest.is_(True), Judge.provider != JudgeProvider.heuristic)
        .limit(1)
    )
    non_judged = {Dimension.cost, Dimension.latency, Dimension.robustness}
    return MetaOut(
        version=settings.app_version,
        environment=settings.env,
        enums={key: enum_options(cls) for key, cls in ENUM_KEYS.items()},
        classifications=[
            EnumOption(value=str(level), label=f"C{level} — {label}")
            for level, label in CLASSIFICATION_LABELS.items()
        ],
        categories=[EnumOption(value=k, label=v) for k, v in SCENARIO_CATEGORIES.items()],
        criteria=[
            MetaCriterion(
                key=c.key,
                dimension=c.dimension.value,
                name=c.name,
                question=c.question,
                scale_min=c.scale_min,
                scale_max=c.scale_max,
                builtin=c.builtin,
                judged=c.dimension not in non_judged,
            )
            for c in criteria
        ],
        default_judged_criteria=list(DEFAULT_JUDGED_CRITERIA),
        error_types=[
            MetaErrorType(
                code=e.code,
                label=e.label,
                description=e.description,
                default_severity=e.default_severity.value,
                dimension=e.dimension.value,
                builtin=e.builtin,
            )
            for e in error_types
        ],
        rule_types=[RuleTypeOut(**r) for r in rule_type_catalog()],
        adapters=[
            AdapterKindOut(label=LABELS[AdapterKind][str(a["kind"])], **{**a, "kind": str(a["kind"])})  # type: ignore[arg-type]
            for a in ADAPTERS
        ],
        capabilities=Capabilities(
            llm_judges_configured=llm_judges is not None,
            feedback_llm=settings.feedback_llm_enabled,
            orbit_configured=bool(settings.orbit_base_url),
        ),
        otlp_endpoint=f"{settings.public_base_url}/v1/traces",
        api_key_header=API_KEY_HEADER,
    )

# ruff: noqa: E501 — French user-facing messages are kept on one line.
"""Orchestration of the demo seed (``python -m forge.seed``).

Everything is created **through the services** (the same code paths as the API, with audit entries),
then executed by the real pipeline: demo agents → runner → evaluation → aggregation. Every step is
idempotent (objects are looked up by slug / name / key and skipped when present), so a seed
interrupted or started with ``--no-wait`` resumes where it stopped on the next run.

Phases:

1. reference data, demo users, ``traces:write`` API key, evaluation configuration;
2. registry: prompts (with history), simulated models, tools, agents and versions;
3. context dataset, scenario library (variants, private, fresh, C2);
4. benchmarks launched (+ ad hoc ResearchAgent runs) → wait;
5. experiments v1.2 → v1.3 (linked to the feedback report of a v1.2 run) and SupportAgent
   v1.0 → v1.1 → wait; experiment v1.3 → v1.4 (linked to the v1.3 experiment feedback) → wait;
6. human evaluations of the evaluator persona + gold dataset (calibration).
"""

from __future__ import annotations

import json
import logging
import secrets
import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import and_, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.enums import (
    DatasetKind,
    EvaluatorKind,
    FeedbackScope,
    Role,
    RunStatus,
    ScenarioVisibility,
    ScoreSource,
)
from forge.infra.db import get_sessionmaker
from forge.infra.models import (
    Agent,
    AgentVersion,
    ApiKey,
    Benchmark,
    BenchmarkExecution,
    Dataset,
    DatasetItem,
    Evaluation,
    EvaluationRun,
    Experiment,
    FeedbackReport,
    PromptVersion,
    RunError,
    Scenario,
    Score,
    ToolConfiguration,
    User,
)
from forge.seed import catalog
from forge.seed.documents import CORPUS_IDS, DOCS
from forge.seed.humans import RunFacts, human_scores
from forge.seed.principal import SeedPrincipal
from forge.seed.reset import check_reset_allowed, reset_business_data
from forge.seed.scenarios import PRODUCT, RESEARCH, SUPPORT, for_scale, library
from forge.seed.waiting import Tracked, wait_for
from forge.services import agents as agent_service
from forge.services import api_keys as api_key_service
from forge.services import audit, run_queries
from forge.services import benchmarks as benchmark_service
from forge.services import datasets as dataset_service
from forge.services import evaluation_configs as config_service
from forge.services import experiments as experiment_service
from forge.services import reviews as review_service
from forge.services import scenarios as scenario_service
from forge.services.bootstrap import DEFAULT_CONFIG_KEY, ensure_reference_data
from forge.services.mapping import load_criteria_catalog
from forge.services.users import create_user, ensure_bootstrap_admin, get_by_email

logger = logging.getLogger("forge.seed")

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_CREDENTIALS_PATH = BACKEND_DIR / ".seed-credentials.json"
DEV_DEMO_PASSWORD = "Nordalis-Demo-2026"
SEED_TAG = "seed:nordalis"

CONFIG_KEY = "nordalis-demo"
CONTEXT_DATASET_SLUG = "nordalis-corpus-produit"
GOLD_DATASET_SLUG = "nordalis-gold-calibration"
PRODUCT_BENCHMARK_SLUG = "product-agent-benchmark"
SUPPORT_BENCHMARK_SLUG = "support-benchmark"
API_KEY_NAME = "Agents de démonstration — traces"
CI_KEY_NAME = "CI Nordalis — expériences (démo)"
EXP_PRODUCT_13 = "ProductAgent v1.2 → v1.3"
EXP_PRODUCT_14 = "ProductAgent v1.3 → v1.4"
EXP_SUPPORT = "SupportAgent v1.0 → v1.1"


@dataclass(frozen=True, slots=True)
class DemoUser:
    key: str
    email: str
    full_name: str
    role: Role
    clearance: int
    persona: str


DEMO_USERS: tuple[DemoUser, ...] = (
    DemoUser(
        "maintainer",
        "camille.laurent@nordalis.example",
        "Camille Laurent",
        Role.maintainer,
        3,
        "Responsable qualité IA : bibliothèque de scénarios, scénarios privés, configurations d'évaluation",
    ),
    DemoUser(
        "editor",
        "julien.mercier@nordalis.example",
        "Julien Mercier",
        Role.editor,
        2,
        "Product manager : agents, versions, benchmarks et expériences",
    ),
    DemoUser(
        "evaluator",
        "sarah.benali@nordalis.example",
        "Sarah Benali",
        Role.evaluator,
        2,
        "Experte métier : évaluations humaines et calibration",
    ),
    DemoUser(
        "viewer",
        "thomas.nguyen@nordalis.example",
        "Thomas Nguyen",
        Role.viewer,
        1,
        "Direction produit : lecture seule (habilitation C1, ne voit pas le scénario C2)",
    ),
)

#: Runs reviewed by the evaluator persona: (scenario slug) × every ProductAgent version, repetition 0.
REVIEW_SCENARIOS = {
    "full": (
        "nordalis_prd_export_fec",
        "nordalis_discovery_notes_de_frais",
        "nordalis_us_export_fec",
        "nordalis_prd_circuit_validation",
    ),
    "small": ("nordalis_prd_export_fec", "nordalis_us_export_fec"),
}


@dataclass(slots=True)
class SeedOptions:
    reset: bool = False
    yes: bool = False
    scale: str = "full"  # full | small
    sync: bool = False
    wait: bool = True
    demo_agents_url: str | None = None
    latency_scale: float | None = None  # default: 0.25 (full), 0 (small)
    timeout: float = 1800.0  # seconds per waiting phase
    credentials_path: Path | None = None
    quiet: bool = False

    @property
    def full(self) -> bool:
        return self.scale != "small"

    @property
    def effective_latency_scale(self) -> float:
        if self.latency_scale is not None:
            return max(0.0, min(10.0, float(self.latency_scale)))
        return 0.25 if self.full else 0.0

    @property
    def repetitions(self) -> dict[str, int]:
        if self.full:
            return {"benchmark": 2, "exp13": 3, "exp14": 2, "support_exp": 3, "research": 2}
        return {"benchmark": 1, "exp13": 1, "exp14": 1, "support_exp": 1, "research": 1}


@dataclass(slots=True)
class SeedReport:
    created: Counter[str] = field(default_factory=Counter)
    skipped: Counter[str] = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)
    accounts: list[dict[str, Any]] = field(default_factory=list)
    api_key: dict[str, Any] | None = None
    ci_api_key: dict[str, Any] | None = None
    benchmark_ids: dict[str, uuid.UUID] = field(default_factory=dict)
    execution_ids: dict[str, uuid.UUID] = field(default_factory=dict)
    experiment_ids: dict[str, uuid.UUID] = field(default_factory=dict)
    adhoc_run_ids: list[uuid.UUID] = field(default_factory=list)
    reviewed_runs: int = 0
    completed: bool = False
    duration_seconds: float = 0.0
    credentials_path: Path | None = None

    @property
    def total_created(self) -> int:
        return sum(self.created.values())


class Seeder:
    def __init__(self, options: SeedOptions, *, log: Callable[[str], None] | None = None) -> None:
        self.options = options
        self.report = SeedReport()
        self._log = log or (lambda message: None if options.quiet else print(message, flush=True))
        self.base_url = (options.demo_agents_url or settings.demo_agents_url).rstrip("/")
        self.definitions = for_scale(library(self._latency_limit_ms()), options.scale)
        self.versions: dict[str, dict[str, uuid.UUID]] = {}  # agent slug → label → version id
        self.scenario_ids: dict[str, uuid.UUID] = {}  # slug → scenario id
        self.config_id: uuid.UUID | None = None
        self.context_dataset_id: uuid.UUID | None = None
        self._previous_credentials = self._read_credentials()

    # --- helpers ------------------------------------------------------------------------------------

    def log(self, message: str) -> None:
        self._log(message)

    def _created(self, kind: str, label: str = "") -> None:
        self.report.created[kind] += 1
        if label:
            logger.debug("created %s %s", kind, label)

    def _skipped(self, kind: str) -> None:
        self.report.skipped[kind] += 1

    def _latency_limit_ms(self) -> int | None:
        scale = self.options.effective_latency_scale
        return int(2800 * scale + 100) if scale > 0 else None

    def _normalization(self) -> dict[str, float]:
        scale = self.options.effective_latency_scale
        latency = (
            {"latency_target_ms": round(1500 * scale + 100), "latency_max_ms": round(5000 * scale + 200)}
            if scale > 0
            else {"latency_target_ms": 1000.0, "latency_max_ms": 10000.0}
        )
        return {"cost_target": 0.001, "cost_max": 0.008, "robustness_max_std": 0.25, **latency}

    @property
    def credentials_path(self) -> Path:
        return self.options.credentials_path or DEFAULT_CREDENTIALS_PATH

    def _read_credentials(self) -> dict[str, Any]:
        try:
            return dict(json.loads(self.credentials_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return {}

    async def _principal(self, session: AsyncSession, key: str) -> SeedPrincipal:
        if key == "admin":
            user = await get_by_email(session, settings.bootstrap_admin_email)
            if user is None:
                user = await session.scalar(select(User).where(User.role == Role.admin).limit(1))
        else:
            user = await get_by_email(session, next(u.email for u in DEMO_USERS if u.key == key))
        if user is None:
            raise RuntimeError(f"Utilisateur de démonstration introuvable : {key}")
        return SeedPrincipal(user)

    # --- entry point ----------------------------------------------------------------------------------

    async def run(self) -> SeedReport:
        started = time.monotonic()
        options = self.options
        self.log(
            f"FORGE — jeu de démonstration Nordalis (échelle {options.scale}, "
            f"latence simulée × {options.effective_latency_scale:g}, agents : {self.base_url})"
        )
        if options.reset:
            check_reset_allowed(confirmed=options.yes)
            self.log("Réinitialisation des données métier…")
            await reset_business_data()
        await self._bootstrap()
        await self._step("Utilisateurs de démonstration", self._users)
        await self._step("Clés d'API (traces:write, CI)", self._api_key)
        await self._step("Configuration d'évaluation", self._evaluation_config)
        await self._step("Prompts, modèles et outils", self._registry_parts)
        await self._step("Agents et versions", self._agents)
        await self._step("Jeu de données de contexte", self._context_dataset)
        await self._step("Bibliothèque de scénarios", self._scenarios)
        await self._step("Benchmarks", self._benchmarks)
        await self._step("Runs ad hoc ResearchAgent", self._research_runs)
        self._write_credentials()
        if not options.wait:
            self.report.notes.append(
                "--no-wait : benchmarks lancés sans attendre. Relancez `make seed` une fois les runs terminés "
                "pour créer les expériences et les évaluations humaines."
            )
            self.report.duration_seconds = time.monotonic() - started
            return self.report
        await self._wait(
            "benchmarks",
            Tracked(
                execution_ids=list(self.report.execution_ids.values()),
                run_ids=list(self.report.adhoc_run_ids),
            ),
        )
        await self._step("Expériences v1.2 → v1.3 et support", self._experiments_first)
        await self._wait(
            "expériences",
            Tracked(experiment_ids=[self.report.experiment_ids[k] for k in (EXP_PRODUCT_13, EXP_SUPPORT)]),
        )
        await self._step("Expérience v1.3 → v1.4", self._experiment_fix)
        await self._wait(
            "expérience v1.4", Tracked(experiment_ids=[self.report.experiment_ids[EXP_PRODUCT_14]])
        )
        await self._step("Évaluations humaines et jeu gold", self._reviews)
        self.report.completed = True
        self.report.duration_seconds = time.monotonic() - started
        return self.report

    async def _step(self, label: str, action: Callable[[AsyncSession], Any]) -> None:
        before = self.report.total_created
        async with get_sessionmaker()() as session:
            await action(session)
            await session.commit()
        created = self.report.total_created - before
        self.log(f"✓ {label}" + (f" ({created} créé(s))" if created else " (déjà présent)"))

    async def _wait(self, label: str, tracked: Tracked) -> None:
        if tracked.empty():
            return
        await wait_for(
            tracked, sync=self.options.sync, limit_seconds=self.options.timeout, label=label, log=self.log
        )

    async def _bootstrap(self) -> None:
        async with get_sessionmaker()() as session:
            await ensure_bootstrap_admin(session)
        async with get_sessionmaker()() as session:
            await ensure_reference_data(session)

    # =================================================================================================
    # Phase 1 — identities and configuration
    # =================================================================================================

    async def _users(self, session: AsyncSession) -> None:
        admin = await self._principal(session, "admin")
        previous = {
            a.get("email"): a for a in self._previous_credentials.get("accounts", []) if isinstance(a, dict)
        }
        production = settings.env == "production"
        for demo in DEMO_USERS:
            user = await get_by_email(session, demo.email)
            password: str | None
            if user is None:
                password = secrets.token_urlsafe(12) if production else DEV_DEMO_PASSWORD
                user = await create_user(
                    session,
                    email=demo.email,
                    full_name=demo.full_name,
                    password=password,
                    role=demo.role,
                    clearance=demo.clearance,
                )
                await audit.record(
                    session,
                    admin,
                    "user.create",
                    "user",
                    user.id,
                    summary=f"Création de l'utilisateur {user.full_name} ({user.email})",
                    details={"role": user.role, "clearance": user.clearance, "seed": True},
                )
                self._created("user")
            else:
                password = previous.get(demo.email, {}).get("password")
                self._skipped("user")
            self.report.accounts.append(
                {
                    "key": demo.key,
                    "email": demo.email,
                    "name": demo.full_name,
                    "role": demo.role.value,
                    "clearance": f"C{demo.clearance}",
                    "persona": demo.persona,
                    "password": password,
                }
            )

    async def _api_key(self, session: AsyncSession) -> None:
        admin = await self._principal(session, "admin")
        self.report.api_key = await self._ensure_key(
            session,
            admin,
            name=API_KEY_NAME,
            scopes=["traces:write"],
            previous=self._previous_credentials.get("api_key"),
            usage="Authorization: Bearer <clé> sur POST /v1/traces (OTLP) ou /api/v1/runs/{id}/events — à fournir "
            "aux agents (FORGE_DEMO_OTLP_KEY pour le mode boîte blanche des agents de démonstration).",
        )
        self.report.ci_api_key = await self._ensure_key(
            session,
            admin,
            name=CI_KEY_NAME,
            scopes=[],
            previous=self._previous_credentials.get("ci_api_key"),
            usage="Clé de service editor (C1) pour la CLI : FORGE_API_KEY=<clé> forge experiment gate <id> "
            "(docs/CI.md).",
        )

    async def _ensure_key(
        self,
        session: AsyncSession,
        admin: SeedPrincipal,
        *,
        name: str,
        scopes: list[str],
        previous: Any,
        usage: str,
    ) -> dict[str, Any]:
        """Reuse the key when its secret is known (credentials file), otherwise rotate it."""
        existing = await session.scalar(
            select(ApiKey).where(ApiKey.name == name, ApiKey.revoked_at.is_(None)).limit(1)
        )
        if existing is not None and isinstance(previous, dict) and previous.get("prefix") == existing.prefix:
            self._skipped("api_key")
            return dict(previous)
        if existing is not None:
            await api_key_service.revoke_api_key(session, admin, existing)
        key, secret = await api_key_service.create_api_key(
            session,
            admin,
            name=name,
            role=Role.editor,
            clearance=1,
            scopes=scopes,
            created_by=admin.user_id,
        )
        self._created("api_key")
        return {
            "name": name,
            "prefix": key.prefix,
            "key": secret,
            "role": "editor",
            "clearance": "C1",
            "scopes": scopes,
            "usage": usage,
        }

    async def _evaluation_config(self, session: AsyncSession) -> None:
        existing = await config_service.latest_version(session, CONFIG_KEY)
        if existing is not None:
            self.config_id = existing.id
            self._skipped("evaluation_config")
            return
        maintainer = await self._principal(session, "maintainer")
        base = await config_service.latest_version(session, DEFAULT_CONFIG_KEY)
        if base is None:
            raise RuntimeError("Configuration forge-default absente : données de référence non initialisées")
        fields = config_service.config_fields(base)
        fields["dimension_weights"] = {
            "quality": 0.30,
            "coherence": 0.15,
            "reasoning": 0.05,
            "safety": 0.25,
            "robustness": 0.10,
            "cost": 0.05,
            "latency": 0.05,
            "ux": 0.05,
        }
        fields["gates"] = [
            *fields["gates"],
            {
                "id": "word-limit-cap",
                "kind": "rule",
                "target": "word-limit",
                "action": "cap",
                "cap": 65,
                "description": "Livrable au-delà de la limite de mots de la consigne : score plafonné à 65 "
                "(le comité produit ne lit pas un document trop long).",
            },
        ]
        fields["normalization"] = self._normalization()
        config = await config_service.create_config(
            session,
            key=CONFIG_KEY,
            name="Nordalis — démo produit et support",
            description=(
                "Pondération de l'équipe Nordalis : qualité 30 %, sécurité 25 %, cohérence 15 %, robustesse 10 %, "
                "coût, latence et UX 5 % chacun ; garde-fous par défaut + plafond à 65 si la limite de mots est dépassée. Cibles de coût et de latence adaptées aux modèles simulés de la démonstration "
                "(latence accélérée)."
            ),
            actor=maintainer,
            created_by=maintainer.user_id,
            **fields,
        )
        self.config_id = config.id
        self._created("evaluation_config")

    # =================================================================================================
    # Phase 2 — registry
    # =================================================================================================

    async def _registry_parts(self, session: AsyncSession) -> None:
        editor = await self._principal(session, "editor")
        prompt_sets = {
            "product_manager": catalog.product_manager_prompts(),
            "support_agent": catalog.SUPPORT_PROMPTS,
            "research_agent": catalog.RESEARCH_PROMPTS,
        }
        for name, versions in prompt_sets.items():
            latest = await agent_service.latest_prompt(session, name)
            have = latest.version if latest else 0
            for number, (description, content) in enumerate(versions, start=1):
                if number <= have:
                    self._skipped("prompt_version")
                    continue
                await agent_service.create_prompt_version(
                    session,
                    editor,
                    name=name,
                    content=content,
                    description=description,
                    created_by=editor.user_id,
                )
                self._created("prompt_version")
        for model in catalog.MODELS.values():
            _, created = await agent_service.ensure_model_configuration(
                session, editor, dict(model), created_by=editor.user_id
            )
            self._created("model_configuration") if created else self._skipped("model_configuration")
        counts: Counter[str] = Counter()
        for name, description, tools in catalog.TOOL_CONFIGS:
            counts[name] += 1
            latest_tools = await agent_service.latest_tool_configuration(session, name)
            if latest_tools is not None and latest_tools.version >= counts[name]:
                self._skipped("tool_configuration")
                continue
            await agent_service.create_tool_configuration(
                session, editor, name=name, tools=tools, description=description, created_by=editor.user_id
            )
            self._created("tool_configuration")

    async def _agents(self, session: AsyncSession) -> None:
        editor = await self._principal(session, "editor")
        for definition in catalog.AGENTS:
            agent = await session.scalar(select(Agent).where(Agent.slug == definition.slug))
            if agent is None:
                agent = await agent_service.create_agent(
                    session,
                    editor,
                    name=definition.name,
                    slug=definition.slug,
                    description=definition.description,
                    provider=definition.provider,
                    tags=definition.tags,
                    metadata={"demo": True, "entreprise": "Nordalis (fictive)"},
                    owner_id=editor.user_id,
                )
                self._created("agent")
            else:
                self._skipped("agent")
            labels: dict[str, uuid.UUID] = {}
            previous_id: uuid.UUID | None = None
            for version in definition.versions:
                existing = await session.scalar(
                    select(AgentVersion).where(
                        AgentVersion.agent_id == agent.id, AgentVersion.version == version.label
                    )
                )
                if existing is None:
                    existing = await agent_service.create_version(
                        session,
                        editor,
                        agent,
                        await self._version_data(session, definition.slug, version, previous_id),
                        created_by=editor.user_id,
                    )
                    self._created("agent_version")
                else:
                    self._skipped("agent_version")
                labels[version.label] = existing.id
                previous_id = existing.id
            self.versions[definition.slug] = labels

    async def _version_data(
        self, session: AsyncSession, slug: str, version: catalog.VersionDef, previous_id: uuid.UUID | None
    ) -> dict[str, Any]:
        prompt_name, prompt_number = version.prompt
        prompt = await session.scalar(
            select(PromptVersion).where(
                PromptVersion.name == prompt_name, PromptVersion.version == prompt_number
            )
        )
        tools_name, tools_number = version.tools
        tools = await session.scalar(
            select(ToolConfiguration).where(
                ToolConfiguration.name == tools_name, ToolConfiguration.version == tools_number
            )
        )
        model, _ = await agent_service.ensure_model_configuration(
            session, None, dict(catalog.MODELS[version.model])
        )
        if prompt is None or tools is None:
            raise RuntimeError(
                f"Prompt {prompt_name} v{prompt_number} ou outils {tools_name} v{tools_number} absents"
            )
        data: dict[str, Any] = {
            "version": version.label,
            "adapter_kind": "custom_api",
            "endpoint": f"{self.base_url}/agents/{slug}/{version.demo_version}/invoke",
            "adapter_config": {
                "mode": "forge",
                "parameters": {"latency_scale": self.options.effective_latency_scale},
            },
            "context_config": {"source": "scenario"},
            "model_configuration_id": model.id,
            "prompt_version_id": prompt.id,
            "tool_configuration_id": tools.id,
            "budget": {"max_tokens": 8000, "timeout_seconds": 60},
            "max_concurrency": 8,
            "metadata": {"demo": True, "demo_agent": f"{slug}@{version.demo_version}"},
            "changelog": version.changelog,
        }
        if previous_id is not None:
            data["base_version_id"] = previous_id
        return data

    # =================================================================================================
    # Phase 3 — datasets and scenarios
    # =================================================================================================

    async def _context_dataset(self, session: AsyncSession) -> None:
        dataset = await session.scalar(select(Dataset).where(Dataset.slug == CONTEXT_DATASET_SLUG))
        if dataset is not None:
            self.context_dataset_id = dataset.id
            self._skipped("dataset")
            return
        maintainer = await self._principal(session, "maintainer")
        dataset = await dataset_service.create_dataset(
            session,
            maintainer,
            maintainer,
            name="Nordalis — corpus produit et politiques",
            kind=DatasetKind.context,
            slug=CONTEXT_DATASET_SLUG,
            description=(
                "Entretiens clients, spécifications, indicateurs, notes de veille et politiques (retours, données des "
                "factures) de Nordalis, entreprise fictive. Source des documents de contexte des scénarios."
            ),
            tags=["nordalis", "contexte"],
            items=[DOCS[i].as_dataset_item() for i in CORPUS_IDS],
            created_by=maintainer.user_id,
        )
        self.context_dataset_id = dataset.id
        self._created("dataset")

    async def _scenarios(self, session: AsyncSession) -> None:
        maintainer = await self._principal(session, "maintainer")
        for definition in self.definitions:
            scenario = await scenario_service.get_by_slug(session, definition.slug)
            if scenario is None:
                content = dict(definition.content)
                if self.context_dataset_id and definition.classification <= 1:
                    content["dataset_id"] = str(self.context_dataset_id)
                scenario, _ = await scenario_service.create_scenario(
                    session,
                    maintainer,
                    maintainer,
                    name=definition.name,
                    category=definition.category,
                    content=content,
                    slug=definition.slug,
                    visibility=definition.visibility,
                    classification=definition.classification,
                    tags=definition.tags,
                    changelog="Version initiale (jeu de démonstration Nordalis)",
                    owner_id=maintainer.user_id,
                )
                self._created("scenario")
            else:
                self._skipped("scenario")
            self.scenario_ids[definition.slug] = scenario.id
            for variant in definition.variants:
                slug = f"{definition.slug}_variant_{variant.label}"
                existing = await scenario_service.get_by_slug(session, slug)
                if existing is None:
                    existing, _ = await scenario_service.create_variant(
                        session,
                        maintainer,
                        maintainer,
                        scenario,
                        label=variant.label,
                        overrides=variant.overrides,
                        name=variant.name,
                        changelog=variant.changelog,
                        owner_id=maintainer.user_id,
                    )
                    self._created("scenario")
                else:
                    self._skipped("scenario")
                self.scenario_ids[slug] = existing.id

    def _slugs_for(self, agent: str, *, include_classified: bool = True) -> list[str]:
        slugs: list[str] = []
        for definition in self.definitions:
            if definition.agent != agent:
                continue
            if not include_classified and definition.classification > 1:
                continue
            slugs.append(definition.slug)
            slugs += [f"{definition.slug}_variant_{v.label}" for v in definition.variants]
        return slugs

    # =================================================================================================
    # Phase 4 — benchmarks and ad hoc runs
    # =================================================================================================

    async def _benchmarks(self, session: AsyncSession) -> None:
        editor = await self._principal(session, "editor")
        reps = self.options.repetitions["benchmark"]
        specs = [
            (
                PRODUCT_BENCHMARK_SLUG,
                "Product Agent Benchmark",
                "Scénarios Product Management, Discovery, Delivery et multi-étapes de Nordalis (variantes, scénarios "
                "privés de généralisation, scénarios fresh, un scénario C2 fictif) × ProductAgent 1.2 / 1.3 / 1.4.",
                PRODUCT,
                "product-agent",
                ["nordalis", "produit"],
            ),
            (
                SUPPORT_BENCHMARK_SLUG,
                "Support Benchmark",
                "Tickets de retour et de remboursement (politique de retour Nordalis) × SupportAgent 1.0 / 1.1.",
                SUPPORT,
                "support-agent",
                ["nordalis", "support"],
            ),
        ]
        for slug, name, description, agent_kind, agent_slug, tags in specs:
            benchmark = await session.scalar(select(Benchmark).where(Benchmark.slug == slug))
            if benchmark is None:
                benchmark = await benchmark_service.create_benchmark(
                    session,
                    editor,
                    editor,
                    name=name,
                    slug=slug,
                    description=description,
                    scenarios=[
                        benchmark_service.ScenarioSelection(self.scenario_ids[s])
                        for s in self._slugs_for(agent_kind)
                    ],
                    agent_version_ids=list(self.versions[agent_slug].values()),
                    evaluation_config_id=self.config_id,
                    repetitions=reps,
                    tags=tags,
                )
                self._created("benchmark")
            else:
                self._skipped("benchmark")
            self.report.benchmark_ids[slug] = benchmark.id
            execution = await session.scalar(
                select(BenchmarkExecution)
                .where(BenchmarkExecution.benchmark_id == benchmark.id)
                .order_by(BenchmarkExecution.number.desc())
                .limit(1)
            )
            if execution is None:
                execution = await benchmark_service.launch_execution(
                    session, editor, editor, benchmark, trigger="seed"
                )
                self._created("benchmark_execution")
                self.log(f"  {name} : exécution n° {execution.number} lancée ({execution.total_runs} runs)")
            else:
                self._skipped("benchmark_execution")
            self.report.execution_ids[slug] = execution.id

    async def _research_runs(self, session: AsyncSession) -> None:
        editor = await self._principal(session, "editor")
        version_id = self.versions["research-agent"]["1.0"]
        existing = list(
            await session.scalars(
                select(EvaluationRun.id).where(
                    EvaluationRun.agent_version_id == version_id, EvaluationRun.tags.contains([SEED_TAG])
                )
            )
        )
        if existing:
            self.report.adhoc_run_ids = existing
            self._skipped("adhoc_runs")
            return
        runs = await run_queries.create_adhoc_runs(
            session,
            editor,
            editor,
            run_queries.RunRequest(
                agent_version_id=version_id,
                scenario_ids=[self.scenario_ids[s] for s in self._slugs_for(RESEARCH)],
                repetitions=self.options.repetitions["research"],
                evaluation_config_id=self.config_id,
                tags=[SEED_TAG, "recherche documentaire"],
            ),
            created_by=editor.user_id,
        )
        self.report.adhoc_run_ids = [r.id for r in runs]
        self.report.created["run"] += len(runs)

    # =================================================================================================
    # Phase 5 — experiments
    # =================================================================================================

    async def _experiment(
        self,
        session: AsyncSession,
        *,
        name: str,
        baseline: uuid.UUID,
        candidate: uuid.UUID,
        benchmark_slug: str,
        scenario_slugs: list[str],
        repetitions: int,
        description: str,
        hypothesis: str,
        tags: list[str],
        source_feedback_report_id: uuid.UUID | None,
    ) -> None:
        existing = await session.scalar(select(Experiment).where(Experiment.name == name).limit(1))
        if existing is not None:
            self.report.experiment_ids[name] = existing.id
            self._skipped("experiment")
            return
        editor = await self._principal(session, "editor")
        experiment = await experiment_service.create_experiment(
            session,
            editor,
            editor,
            baseline_version_id=baseline,
            candidate_version_id=candidate,
            benchmark_id=self.report.benchmark_ids[benchmark_slug],
            scenario_ids=[self.scenario_ids[s] for s in scenario_slugs],
            evaluation_config_id=self.config_id,
            repetitions=repetitions,
            name=name,
            description=description,
            hypothesis=hypothesis,
            tags=tags,
            source_feedback_report_id=source_feedback_report_id,
            trigger="seed",
        )
        self.report.experiment_ids[name] = experiment.id
        self._created("experiment")
        self.log(f"  {name} : {experiment.total_runs} runs lancés")

    async def _v12_feedback_report(self, session: AsyncSession) -> uuid.UUID | None:
        """Feedback report of the worst v1.2 run of the product benchmark (preferably the FEC PRD).

        Runs that the evaluator persona reviews later are excluded: a human evaluation re-scores the run,
        which replaces its feedback report (the experiment would point to a deleted report).
        """
        execution_id = self.report.execution_ids.get(PRODUCT_BENCHMARK_SLUG)
        version_id = self.versions["product-agent"]["1.2"]
        reviewed = REVIEW_SCENARIOS["full" if self.options.full else "small"]
        base = (
            select(FeedbackReport.id)
            .join(EvaluationRun, EvaluationRun.id == FeedbackReport.run_id)
            .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
            .where(
                FeedbackReport.scope == FeedbackScope.run,
                EvaluationRun.benchmark_execution_id == execution_id,
                EvaluationRun.agent_version_id == version_id,
                EvaluationRun.status == RunStatus.completed,
                Scenario.visibility == ScenarioVisibility.public,
                # runs reviewed by the evaluator are re-scored, which replaces their feedback report
                not_(and_(Scenario.slug.in_(list(reviewed)), EvaluationRun.repetition == 0)),
            )
            .order_by(
                EvaluationRun.gate_failed.desc(),
                EvaluationRun.composite_score.asc(),
                FeedbackReport.created_at,
            )
            .limit(1)
        )
        preferred = await session.scalar(base.where(Scenario.slug == "nordalis_prd_export_fec"))
        return preferred or await session.scalar(base)

    async def _experiments_first(self, session: AsyncSession) -> None:
        product = self.versions["product-agent"]
        support = self.versions["support-agent"]
        source = await self._v12_feedback_report(session)
        if source is None:
            self.report.notes.append(
                "Aucun rapport de feedback v1.2 trouvé : expérience v1.3 créée sans lien."
            )
        await self._experiment(
            session,
            name=EXP_PRODUCT_13,
            baseline=product["1.2"],
            candidate=product["1.3"],
            benchmark_slug=PRODUCT_BENCHMARK_SLUG,
            scenario_slugs=self._slugs_for(PRODUCT, include_classified=False),
            repetitions=self.options.repetitions["exp13"],
            description=(
                "ProductAgent v1.3 est-elle vraiment meilleure que v1.2 ? Comparaison appariée sur les scénarios "
                "produit (variantes, privés et fresh inclus), mêmes versions de scénarios, même configuration."
            ),
            hypothesis=(
                "La recherche ciblée et le modèle sim-efficient-2 améliorent la qualité et le sourcing, suppriment les "
                "fuites d'e-mail et divisent le coût, sans dégrader le respect des consignes."
            ),
            tags=["nordalis", "boucle d'amélioration"],
            source_feedback_report_id=source,
        )
        await self._experiment(
            session,
            name=EXP_SUPPORT,
            baseline=support["1.0"],
            candidate=support["1.1"],
            benchmark_slug=SUPPORT_BENCHMARK_SLUG,
            scenario_slugs=self._slugs_for(SUPPORT),
            repetitions=self.options.repetitions["support_exp"],
            description="SupportAgent v1.1 applique-t-elle correctement la politique de retour ?",
            hypothesis="Moins de remboursements à tort, plus de gestes commerciaux non autorisés ni de coordonnées recopiées.",
            tags=["nordalis", "support"],
            source_feedback_report_id=None,
        )

    async def _experiment_fix(self, session: AsyncSession) -> None:
        product = self.versions["product-agent"]
        source = await session.scalar(
            select(FeedbackReport.id)
            .where(
                FeedbackReport.scope == FeedbackScope.experiment,
                FeedbackReport.experiment_id == self.report.experiment_ids[EXP_PRODUCT_13],
            )
            .order_by(FeedbackReport.created_at.desc())
            .limit(1)
        )
        await self._experiment(
            session,
            name=EXP_PRODUCT_14,
            baseline=product["1.3"],
            candidate=product["1.4"],
            benchmark_slug=PRODUCT_BENCHMARK_SLUG,
            scenario_slugs=self._slugs_for(PRODUCT, include_classified=False),
            repetitions=self.options.repetitions["exp14"],
            description="La v1.4 corrige-t-elle les régressions de la v1.3 (limites de mots, latence) sans perdre ses gains ?",
            hypothesis="Limites de longueur respectées et latence réduite, qualité et coût de la v1.3 conservés.",
            tags=["nordalis", "boucle d'amélioration"],
            source_feedback_report_id=source,
        )

    # =================================================================================================
    # Phase 6 — human evaluations and gold dataset
    # =================================================================================================

    async def _reviews(self, session: AsyncSession) -> None:
        evaluator = await self._principal(session, "evaluator")
        maintainer = await self._principal(session, "maintainer")
        catalog_specs = await load_criteria_catalog(session)
        execution_id = self.report.execution_ids[PRODUCT_BENCHMARK_SLUG]
        slugs = REVIEW_SCENARIOS["full" if self.options.full else "small"]
        rows = (
            await session.execute(
                select(EvaluationRun, Scenario.slug, AgentVersion.version)
                .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
                .join(AgentVersion, AgentVersion.id == EvaluationRun.agent_version_id)
                .where(
                    EvaluationRun.benchmark_execution_id == execution_id,
                    EvaluationRun.repetition == 0,
                    EvaluationRun.status == RunStatus.completed,
                    Scenario.slug.in_(list(slugs)),
                )
            )
        ).all()
        ordered = sorted(rows, key=lambda r: (slugs.index(r[1]), r[2]))
        gold_items: list[dict[str, Any]] = []
        for run, slug, label in ordered:
            already = await session.scalar(
                select(Evaluation.id)
                .where(
                    Evaluation.run_id == run.id,
                    Evaluation.evaluator_kind == EvaluatorKind.human,
                    Evaluation.human_user_id == evaluator.user_id,
                )
                .limit(1)
            )
            if label in ("1.2", "1.3"):
                gold_items.append(
                    {
                        "run_id": str(run.id),
                        "key": f"{slug}-v{label}".replace(".", "-"),
                        "notes": f"{slug} — ProductAgent v{label}, répétition 0 (revu par {evaluator.label})",
                    }
                )
            if already is not None:
                self._skipped("human_evaluation")
                continue
            criteria = [
                c["key"]
                for c in review_service.review_criteria(run.manifest or {}, catalog_specs)
                if c.get("key")
            ]
            facts = await self._facts(session, run, f"{slug}:{label}:{run.repetition}")
            ai = await self._ai_scores(session, run)
            await review_service.submit_human_evaluation(
                session,
                evaluator,
                evaluator,
                run.id,
                user_id=evaluator.user_id,
                scores=human_scores(facts, ai, criteria),
                comment=f"Revue métier du livrable {slug} (ProductAgent v{label}).",
            )
            self._created("human_evaluation")
            self.report.reviewed_runs += 1
        await self._gold_dataset(session, maintainer, gold_items)

    async def _facts(self, session: AsyncSession, run: EvaluationRun, key: str) -> RunFacts:
        failed = set(
            await session.scalars(
                select(Evaluation.evaluator_key).where(
                    Evaluation.run_id == run.id,
                    Evaluation.round == run.evaluation_round,
                    Evaluation.evaluator_kind == EvaluatorKind.rule,
                    Evaluation.passed.is_(False),
                )
            )
        )
        leak = await session.scalar(
            select(RunError.id).where(RunError.run_id == run.id, RunError.error_type == "DATA_LEAK").limit(1)
        )
        return RunFacts(key=key, failed_rules=frozenset(failed), has_pii_leak=leak is not None)

    async def _ai_scores(self, session: AsyncSession, run: EvaluationRun) -> dict[str, float]:
        scores: dict[str, float] = {}
        for score in await session.scalars(
            select(Score).where(Score.run_id == run.id, Score.round == run.evaluation_round)
        ):
            if score.source == ScoreSource.human:
                continue
            if score.criterion_key not in scores or score.source == ScoreSource.ai:
                scores[score.criterion_key] = float(score.value)
        return scores

    async def _gold_dataset(
        self, session: AsyncSession, maintainer: SeedPrincipal, items: list[dict[str, Any]]
    ) -> None:
        dataset = await session.scalar(select(Dataset).where(Dataset.slug == GOLD_DATASET_SLUG))
        if dataset is None:
            dataset = await dataset_service.create_dataset(
                session,
                maintainer,
                maintainer,
                name="Nordalis — jeu gold de calibration",
                kind=DatasetKind.gold,
                slug=GOLD_DATASET_SLUG,
                description=(
                    "Runs ProductAgent v1.2 et v1.3 notés par l'experte métier (Sarah Benali) : référence pour mesurer "
                    "l'accord entre le juge et l'humain (page Calibration)."
                ),
                tags=["nordalis", "calibration"],
                created_by=maintainer.user_id,
            )
            self._created("dataset")
        keys = set(await session.scalars(select(DatasetItem.key).where(DatasetItem.dataset_id == dataset.id)))
        missing = [i for i in items if i["key"] not in keys]
        if missing:
            await dataset_service.add_items(session, maintainer, maintainer, dataset, missing)
            self.report.created["dataset_item"] += len(missing)

    # =================================================================================================
    # Credentials file
    # =================================================================================================

    def _write_credentials(self) -> None:
        payload = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "warning": "Fichier local de démonstration : ne jamais le committer ni le partager.",
            "web_url": "http://localhost:3100",
            "api_url": settings.public_base_url,
            "admin": {
                "email": settings.bootstrap_admin_email,
                "password": "voir FORGE_BOOTSTRAP_ADMIN_PASSWORD (.env)",
            },
            "accounts": self.report.accounts,
            "api_key": self.report.api_key,
            "ci_api_key": self.report.ci_api_key,
        }
        try:
            self.credentials_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            self.credentials_path.chmod(0o600)
            self.report.credentials_path = self.credentials_path
        except OSError as exc:
            self.report.notes.append(f"Impossible d'écrire {self.credentials_path} : {exc}")


async def run_seed(options: SeedOptions, *, log: Callable[[str], None] | None = None) -> SeedReport:
    """Load the demo data set (see module docstring). Returns what was created / skipped."""
    return await Seeder(options, log=log).run()

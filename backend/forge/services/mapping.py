"""ORM rows → domain specs (``AgentSpec``, ``ScenarioSpec``, ``ScoreConfig``) and run manifests.

Execution and evaluation always work from the **manifest** frozen in ``evaluation_runs.manifest``
(:func:`specs_from_manifest`), never from live rows: editing an agent, a scenario or a judge after a
run was created cannot change how that run is executed or scored (docs §6.2 reproducibility).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge import __version__
from forge.domain.defaults import CRITERIA_BY_KEY, RULE_DEFAULTS
from forge.domain.enums import Dimension, RuleType
from forge.domain.hashing import content_hash
from forge.domain.serialization import from_dict, list_from_dicts
from forge.domain.taxonomy import BUILTIN_ERROR_TYPES
from forge.domain.types import (
    AgentBudget,
    AgentSpec,
    AggregationSpec,
    CriterionSpec,
    GateSpec,
    JudgeSpec,
    ModelSpec,
    NormalizationSpec,
    RuleSpec,
    ScenarioSpec,
    ScoreConfig,
    ToolMock,
    ToolSpec,
    to_dict,
)
from forge.infra.models import (
    Agent,
    AgentVersion,
    Criterion,
    EvaluationConfig,
    Judge,
    ModelConfiguration,
    PromptVersion,
    Scenario,
    ScenarioVersion,
    ToolConfiguration,
)

MANIFEST_SCHEMA = "forge.run-manifest/v1"


# --- Criteria catalog ------------------------------------------------------------------------------


async def load_criteria_catalog(session: AsyncSession) -> dict[str, CriterionSpec]:
    """Criteria table (falls back to the built-in defaults for keys not stored yet)."""
    catalog = dict(CRITERIA_BY_KEY)
    for row in await session.scalars(select(Criterion)):
        catalog[row.key] = CriterionSpec(
            key=row.key,
            dimension=row.dimension,
            name=row.name,
            question=row.question,
            rubric=row.rubric,
            scale_min=row.scale_min,
            scale_max=row.scale_max,
        )
    return catalog


def resolve_criteria(
    overrides: list[dict[str, Any]], catalog: dict[str, CriterionSpec]
) -> list[CriterionSpec]:
    """Scenario / configuration criteria: catalog entry + per-scenario overrides (weight, rubric…)."""
    result: list[CriterionSpec] = []
    for item in overrides or []:
        key = str(item.get("key", "")).strip()
        if not key:
            continue
        base = catalog.get(key)
        if base is None:
            dimension = Dimension(item.get("dimension") or key.split(".", 1)[0])
            base = CriterionSpec(key=key, dimension=dimension, name=item.get("name") or key)
        result.append(
            CriterionSpec(
                key=key,
                dimension=Dimension(item.get("dimension") or base.dimension),
                name=item.get("name") or base.name,
                question=item.get("question") or base.question,
                rubric=item.get("rubric") or base.rubric,
                scale_min=float(item.get("scale_min", base.scale_min)),
                scale_max=float(item.get("scale_max", base.scale_max)),
                weight=float(item.get("weight", base.weight)),
            )
        )
    return result


# --- Agents ----------------------------------------------------------------------------------------


async def load_agent_spec(session: AsyncSession, version: AgentVersion) -> AgentSpec:
    agent = await session.get(Agent, version.agent_id)
    assert agent is not None
    model: ModelSpec | None = None
    if version.model_configuration_id:
        mc = await session.get(ModelConfiguration, version.model_configuration_id)
        if mc is not None:
            model = ModelSpec(
                provider=mc.provider,
                model=mc.model,
                model_version=mc.model_version,
                temperature=mc.temperature,
                top_p=mc.top_p,
                max_tokens=mc.max_tokens,
                seed=mc.seed,
                params=dict(mc.params or {}),
                input_cost_per_mtok=mc.input_cost_per_mtok,
                output_cost_per_mtok=mc.output_cost_per_mtok,
            )
    prompt_name: str | None = None
    prompt_version: int | None = None
    if version.prompt_version_id:
        pv = await session.get(PromptVersion, version.prompt_version_id)
        if pv is not None:
            prompt_name, prompt_version = pv.name, pv.version
    tools: list[ToolSpec] = []
    tool_label: str | None = None
    if version.tool_configuration_id:
        tc = await session.get(ToolConfiguration, version.tool_configuration_id)
        if tc is not None:
            tools = list_from_dicts(ToolSpec, tc.tools)
            tool_label = f"{tc.name}@{tc.version}"
    return AgentSpec(
        agent_id=str(agent.id),
        agent_version_id=str(version.id),
        agent_name=agent.name,
        agent_slug=agent.slug,
        version=version.version,
        adapter_kind=version.adapter_kind,
        endpoint=version.endpoint,
        model=model,
        system_prompt=version.system_prompt,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        tools=tools,
        tool_configuration=tool_label,
        context_config=dict(version.context_config or {}),
        memory_config=dict(version.memory_config or {}),
        orchestration_config=dict(version.orchestration_config or {}),
        adapter_config=dict(version.adapter_config or {}),
        budget=from_dict(AgentBudget, dict(version.budget or {})),
        metadata=dict(version.metadata_ or {}),
        content_hash=version.content_hash,
        max_concurrency=version.max_concurrency,
        credential_id=str(version.credential_id) if version.credential_id else None,
    )


# --- Scenarios -------------------------------------------------------------------------------------


def parse_rules(items: list[dict[str, Any]] | None) -> list[RuleSpec]:
    """Rule specs; without explicit ``severity`` a rule inherits the default severity of its error type
    (a ``no_pii`` failure is a critical ``DATA_LEAK``, not a medium one)."""
    rules: list[RuleSpec] = []
    for index, item in enumerate(items or []):
        data = dict(item)
        data.setdefault("id", f"R{index + 1}")
        data["type"] = RuleType(data["type"])
        if not data.get("severity"):
            error_type = data.get("error_type") or RULE_DEFAULTS[data["type"]][1]
            info = BUILTIN_ERROR_TYPES.get(str(error_type)) if error_type else None
            if info is not None:
                data["severity"] = info.default_severity
        rules.append(from_dict(RuleSpec, data))
    return rules


def scenario_spec(
    scenario: Scenario, version: ScenarioVersion, catalog: dict[str, CriterionSpec]
) -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id=str(scenario.id),
        scenario_version_id=str(version.id),
        slug=scenario.slug,
        name=scenario.name,
        version=version.version,
        category=scenario.category,
        difficulty=version.difficulty,
        visibility=scenario.visibility,
        classification=int(scenario.classification),
        description=version.description,
        input=dict(version.input or {}),
        context=dict(version.context or {}),
        constraints=list(version.constraints or []),
        expected_output=version.expected_output,
        expected_behavior=version.expected_behavior,
        criteria=resolve_criteria(list(version.criteria or []), catalog),
        rules=parse_rules(version.rules),
        tool_mocks=list_from_dicts(ToolMock, version.tool_mocks),
        dataset_id=str(version.dataset_id) if version.dataset_id else None,
        family_id=str(scenario.family_id),
        variant_label=scenario.variant_label,
        tags=list(scenario.tags or []),
        canary=version.canary,
        content_hash=version.content_hash,
    )


async def load_scenario_spec(session: AsyncSession, version: ScenarioVersion) -> ScenarioSpec:
    scenario = await session.get(Scenario, version.scenario_id)
    assert scenario is not None
    return scenario_spec(scenario, version, await load_criteria_catalog(session))


# --- Judges & evaluation configurations -----------------------------------------------------------


def judge_spec(judge: Judge) -> JudgeSpec:
    return JudgeSpec(
        judge_id=str(judge.id),
        key=judge.key,
        version=judge.version,
        name=judge.name,
        provider=judge.provider,
        model=judge.model,
        model_version=judge.model_version,
        temperature=judge.temperature,
        max_tokens=judge.max_tokens,
        system_prompt=judge.system_prompt,
        rubric_template=judge.rubric_template,
        criteria=list(judge.criteria or []),
        weight=judge.weight,
        base_url=judge.base_url,
        credential_id=str(judge.credential_id) if judge.credential_id else None,
        content_hash=judge.content_hash,
    )


async def load_score_config(session: AsyncSession, config: EvaluationConfig) -> ScoreConfig:
    catalog = await load_criteria_catalog(session)
    judges: list[JudgeSpec] = []
    ids = [uuid.UUID(j) for j in config.judge_ids or []]
    if ids:
        rows = {j.id: j for j in await session.scalars(select(Judge).where(Judge.id.in_(ids)))}
        judges = [judge_spec(rows[i]) for i in ids if i in rows and rows[i].enabled]
    return ScoreConfig(
        config_id=str(config.id),
        key=config.key,
        version=config.version,
        name=config.name,
        dimension_weights={str(k): float(v) for k, v in (config.dimension_weights or {}).items()},
        criterion_weights={str(k): float(v) for k, v in (config.criterion_weights or {}).items()},
        normalization=from_dict(NormalizationSpec, dict(config.normalization or {})),
        gates=list_from_dicts(GateSpec, config.gates),
        judges=judges,
        aggregation=from_dict(AggregationSpec, dict(config.aggregation or {})),
        criteria=resolve_criteria([{"key": k} for k in config.criteria or []], catalog),
        rules=parse_rules(config.rules),
        use_human_scores=config.use_human_scores,
        pass_threshold=config.pass_threshold,
        content_hash=config.content_hash,
    )


# --- Manifests -------------------------------------------------------------------------------------


@dataclass(slots=True)
class RunSpecs:
    scenario: ScenarioSpec
    agent: AgentSpec
    config: ScoreConfig


def build_manifest(specs: RunSpecs, run_info: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Return ``(manifest, manifest_hash)``. The hash only covers the experimental conditions, so
    repetitions of the same scenario × agent × configuration share it."""
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "run": to_dict(run_info),
        "scenario": to_dict(specs.scenario),
        "agent": specs.agent.manifest_dict(),
        "evaluation": specs.config.manifest_dict(),
        "environment": {"forge_version": __version__},
    }
    conditions = {
        "scenario": specs.scenario.content_hash,
        "agent": specs.agent.content_hash,
        "evaluation": specs.config.content_hash,
    }
    return manifest, content_hash(conditions)


def specs_from_manifest(manifest: dict[str, Any]) -> RunSpecs:
    return RunSpecs(
        scenario=from_dict(ScenarioSpec, manifest.get("scenario") or {}),
        agent=from_dict(AgentSpec, manifest.get("agent") or {}),
        config=from_dict(ScoreConfig, manifest.get("evaluation") or {}),
    )

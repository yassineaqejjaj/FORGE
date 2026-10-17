"""Two-workspace fixtures for the isolation tests (ADR 001 §9; ticket NOV-105).

``create_space()`` builds one synthetic workspace: its own users (admin, editor), offline judge and default
configuration, project, and one of each resource (agent + versions, scenario + versions, run with trace,
scores and errors, dataset, credential, project API key, benchmark, experiment). Everything is created
through database sessions bound to the workspace, exactly as the API stamps rows, so nothing is faked.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI

from forge.domain.enums import DatasetKind, ProviderKind, Role
from forge.infra.db import get_sessionmaker
from forge.infra.models import Agent, Dataset, DatasetItem
from forge.infra.workspace_scope import bind_session
from forge.services import api_keys as api_key_service
from forge.services import bootstrap, workspaces
from forge.services import credentials as credential_service
from forge.services.users import create_user
from tests.conftest import DEFAULT_PASSWORD, _client, token_for
from tests.factories import (
    attach_trace,
    complete_with_scores,
    create_agent_version,
    create_run,
    create_scenario_version,
    uid,
)


@dataclass
class Space:
    id: uuid.UUID
    slug: str
    project_id: uuid.UUID
    admin_email: str
    editor_email: str
    editor_id: uuid.UUID
    api_key: str
    ids: dict[str, str] = field(default_factory=dict)

    def ref(self, name: str) -> str:
        return self.ids[name]


async def create_space() -> Space:
    slug = f"space-{uuid.uuid4().hex[:6]}"
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        workspace = await workspaces.create_workspace(session, slug=slug, name=f"Espace {slug}")
        bind_session(session, workspace.id)
        config = await bootstrap.ensure_workspace_defaults(session, slug)
        admin = await create_user(
            session, email=f"admin-{slug}@example.com", full_name=f"Admin {slug}",
            password=DEFAULT_PASSWORD, role=Role.admin, clearance=3,
        )  # fmt: skip
        editor = await create_user(
            session, email=f"editor-{slug}@example.com", full_name=f"Éditeur {slug}",
            password=DEFAULT_PASSWORD, role=Role.editor, clearance=2,
        )  # fmt: skip
        project = await workspaces.create_project(session, workspace, slug="projet", name=f"Projet {slug}")
        bind_session(session, workspace.id, project.id)  # rows of this block belong to the project too

        baseline = await create_agent_version(session, name=f"Agent {slug}", system_prompt="Version A")
        agent = await session.get(Agent, baseline.agent_id)
        assert agent is not None
        candidate = await create_agent_version(session, agent=agent, version="2.0", system_prompt="Version B")
        scenario_v = await create_scenario_version(session, name=f"Scénario {slug}")
        scenario_v2 = await create_scenario_version(session, name=f"Scénario bis {slug}")
        run = await create_run(session, scenario_v, baseline, config=config)
        await attach_trace(session, run, output_text=f"Réponse de l'espace {slug}")
        await complete_with_scores(session, run, composite=82.0, errors=[("FORMAT_ERROR", "low")])

        dataset = Dataset(slug=uid("ds"), name=f"Jeu {slug}", kind=DatasetKind.context)
        session.add(dataset)
        await session.flush()
        item = DatasetItem(dataset_id=dataset.id, key="doc", content={"title": "Doc", "content": slug})
        session.add(item)
        credential = await credential_service.create_credential(
            session, name=f"cred-{slug}", kind=ProviderKind.http, secret=f"secret-{slug}-0000"
        )
        key, plain_key = await api_key_service.create_api_key(
            session, None, name=f"clé {slug}", role=Role.editor, clearance=2
        )
        await session.commit()
        ids = {
            "agent": str(baseline.agent_id),
            "agent_version": str(baseline.id),
            "agent_version_2": str(candidate.id),
            "scenario": str(scenario_v.scenario_id),
            "scenario_version": str(scenario_v.id),
            "scenario_2": str(scenario_v2.scenario_id),
            "run": str(run.id),
            "dataset": str(dataset.id),
            "dataset_item": str(item.id),
            "credential": str(credential.id),
            "api_key": str(key.id),
            "config": str(config.id),
            "judge": str(config.judge_ids[0]),
        }
        space = Space(
            id=workspace.id, slug=slug, project_id=project.id, admin_email=admin.email,
            editor_email=editor.email, editor_id=editor.id, api_key=plain_key, ids=ids,
        )  # fmt: skip
    return space


async def create_programs(app: FastAPI, space: Space) -> None:
    """Benchmark and experiment of the space, created through the API as its administrator."""
    async with await client_for(app, space, "admin") as client:
        benchmark = await client.post(
            "/api/v1/benchmarks",
            json={
                "name": f"Benchmark {space.slug}",
                "scenarios": [{"scenario_id": space.ref("scenario")}],
                "agent_version_ids": [space.ref("agent_version")],
                "repetitions": 1,
            },
        )
        assert benchmark.status_code == 201, benchmark.text
        space.ids["benchmark"] = benchmark.json()["id"]
        space.ids["benchmark_slug"] = benchmark.json()["slug"]
        experiment = await client.post(
            "/api/v1/experiments",
            json={
                "baseline_version_id": space.ref("agent_version"),
                "candidate_version_id": space.ref("agent_version_2"),
                "scenario_ids": [space.ref("scenario"), space.ref("scenario_2")],
                "name": f"Expérience {space.slug}",
            },
        )
        assert experiment.status_code == 201, experiment.text
        space.ids["experiment"] = experiment.json()["id"]


async def client_for(app: FastAPI, space: Space, who: str = "admin") -> httpx.AsyncClient:
    """A client authenticated as the space's ``admin`` / ``editor`` (session JWT) or by its API ``key``."""
    client = _client(app)
    if who == "key":
        client.headers["X-Forge-Key"] = space.api_key
    else:
        email = space.admin_email if who == "admin" else space.editor_email
        client.headers["Authorization"] = f"Bearer {await token_for(email)}"
    return client

"""GET /audit: maintainer+ only, filters, pagination."""

from __future__ import annotations

import uuid

from forge.domain.enums import Role


async def test_audit_filters_and_roles(admin_client, client_as) -> None:
    slug = f"audit-{uuid.uuid4().hex[:8]}"
    agent = (await admin_client.post("/api/v1/agents", json={"name": "Audit", "slug": slug})).json()
    await admin_client.patch(f"/api/v1/agents/{agent['id']}", json={"description": "modifié"})

    maintainer = await client_as(Role.maintainer)
    by_target = await maintainer.get(
        "/api/v1/audit", params={"target_type": "agent", "target_id": agent["id"]}
    )
    assert by_target.status_code == 200
    items = by_target.json()["items"]
    assert [e["action"] for e in items] == ["agent.update", "agent.create"]  # newest first
    assert items[0]["details"]["changes"] == {"description": "modifié"}
    assert items[0]["actor_type"] == "user" and items[0]["actor_label"]

    by_prefix = await maintainer.get("/api/v1/audit", params={"action": "agent", "page_size": 1})
    page = by_prefix.json()
    assert len(page["items"]) == 1 and page["total"] >= 2 and page["items"][0]["action"].startswith("agent.")

    me = (await admin_client.get("/api/v1/auth/me")).json()
    by_actor = (
        await maintainer.get("/api/v1/audit", params={"actor_id": me["id"], "target_id": agent["id"]})
    ).json()
    assert by_actor["total"] == 2

    editor = await client_as(Role.editor)
    assert (await editor.get("/api/v1/audit")).status_code == 403

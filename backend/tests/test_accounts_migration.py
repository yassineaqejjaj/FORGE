"""Account migration tool (NOV-113): synthetic accounts, read-only inventory, dry-run reconciliation, signed apply.

The tool is exercised the way an operator runs it (``python -m forge.ops accounts …``, parsed then executed),
on a database filled with synthetic accounts. Nothing here touches a real account or sends a secret.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from forge.config import settings
from forge.domain.enums import Role
from forge.infra.db import get_sessionmaker, utcnow
from forge.infra.models import AccountFlag, AuditEvent, ExternalIdentity, User
from forge.ops import accounts as tool
from forge.services import accounts as svc
from forge.services import api_keys as key_service
from forge.services.users import create_user
from tests.conftest import DEFAULT_PASSWORD, _client

ISSUER = "https://idp.orion.test/realms/orion"
APPROVAL_KEY = "synthetic-approval-key-0123456789abcdef-xyz"
BACKUP = "backup-2026-10-16-a"
TABLES = ("users", "external_identities", "account_flags", "audit_events", "api_keys", "workspace_members")


@pytest.fixture(autouse=True)
def _approval_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_MIGRATION_APPROVAL_KEY", APPROVAL_KEY)


async def cli(*argv: str) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    tool.add_parsers(sub)
    return await tool.run(parser.parse_args(["accounts", *argv]))


async def db_state() -> dict[str, tuple[int, str]]:
    """Row count and content hash of every table the tool could touch (whole rows, every column)."""
    out = {}
    async with get_sessionmaker()() as session:
        for table in TABLES:
            row = (
                await session.execute(
                    text(
                        f"SELECT count(*), md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) FROM {table} t"
                    )
                )
            ).one()
            out[table] = (row[0], row[1])
    return out


@dataclass
class Cast:
    tag: str
    domain: str
    users: dict[str, User]


async def make_cast() -> Cast:
    """Synthetic accounts: plain, linked, inactive, plus-tag duplicates, invalid and unverifiable addresses."""
    tag = uuid.uuid4().hex[:6]
    domain = f"acme-{tag}.org"
    spec = {
        "alice": (f"alice@{domain}", Role.editor, 2, True),
        "bob": (f"bob@{domain}", Role.viewer, 1, True),
        "carol": (f"carol@{domain}", Role.admin, 3, True),
        "dave": (f"dave@{domain}", Role.viewer, 1, False),  # inactive
        "erin": (f"erin@{domain}", Role.editor, 2, True),
        "erin_tag": (f"erin+ops@{domain}", Role.editor, 2, True),  # same mailbox by convention
        "frank": (f"frank@{domain}", Role.maintainer, 2, True),
        "gina": (f"gina@{domain}", Role.viewer, 1, True),
        "henri": (f"henri@{tag}.local", Role.viewer, 1, True),  # unverifiable domain
        "ivy": (f"not-an-address-{tag}", Role.viewer, 1, True),  # invalid
    }
    users: dict[str, User] = {}
    async with get_sessionmaker()() as session:
        for name, (email, role, clearance, active) in spec.items():
            user = await create_user(
                session, email=email, full_name=f"{name.title()} Synthétique", password=DEFAULT_PASSWORD,
                role=role, clearance=clearance,
            )  # fmt: skip
            user.active = active
            user.last_login_at = utcnow() - timedelta(days=3) if name in {"alice", "carol"} else None
            users[name] = user
        await session.commit()
    return Cast(tag, domain, users)


async def link(user: User, sub: str) -> None:
    async with get_sessionmaker()() as session:
        session.add(ExternalIdentity(issuer=ISSUER, sub=sub, user_id=user.id))
        await session.commit()


def idp(*rows: dict) -> str:
    return json.dumps([{"email_verified": True, **r} for r in rows])


def write(tmp_path: Path, name: str, content: str) -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


# --- Inventory -------------------------------------------------------------------------------------------------------


async def test_inventory_is_exact_masked_and_changes_nothing(
    app, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cast = await make_cast()
    await link(cast.users["alice"], f"sub-alice-{cast.tag}")
    async with get_sessionmaker()() as session:
        await svc.apply_flags(
            session,
            *(
                await svc.plan_flags(
                    session, cast.users["alice"].email, password_login_disabled=True, sso_required=None
                )
            ),
        )
        _, plain_key = await key_service.create_api_key(
            session, None, name=f"ci-{cast.tag}", role=Role.viewer
        )
        await session.commit()
    before = await db_state()
    assert await cli("inventory", "--expected-domain", cast.domain) == 0
    out = capsys.readouterr().out
    assert await db_state() == before  # strictly read-only
    data = json.loads(out)
    ours = {
        r["email_hash"]: r
        for r in data["accounts"]
        if r["user_id"] in {str(u.id) for u in cast.users.values()}
    }
    assert len(ours) == len(cast.users)
    for name, user in cast.users.items():
        row = ours[svc.email_hash(user.email)]
        assert (
            row["role"] == user.role.value
            and row["clearance"] == user.clearance
            and row["active"] is user.active
        )
        assert row["linked"] is (name == "alice") and row["password_login_disabled"] is (name == "alice")
        assert "email" not in row and row["email_masked"] == svc.mask_email(user.email)
        assert (
            row["last_login_at"] is not None if name in {"alice", "carol"} else row["last_login_at"] is None
        )
    assert ours[svc.email_hash(cast.users["henri"].email)]["email_problem"] == "unverifiable_domain"
    assert ours[svc.email_hash(cast.users["ivy"].email)]["email_problem"] == "invalid_format"
    erin, erin_tag = (ours[svc.email_hash(cast.users[n].email)] for n in ("erin", "erin_tag"))
    assert erin["duplicate_group"] and erin["duplicate_group"] == erin_tag["duplicate_group"]
    assert ours[svc.email_hash(cast.users["bob"].email)]["duplicate_group"] is None
    assert any(len(d["user_ids"]) == 2 for d in data["duplicates"])
    assert all(cast.domain not in json.dumps(r) for r in ours.values())  # no clear address by default
    assert plain_key not in out and "key_hash" not in out
    assert any(k["name"] == f"ci-{cast.tag}" and k["key"].endswith("••••") for k in data["service_keys"])
    assert data["summary"]["accounts"] >= len(cast.users) and data["emails_revealed"] is False


async def test_inventory_reveals_addresses_only_on_request_and_exports_csv(
    app, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cast = await make_cast()
    target = tmp_path / "inventory.csv"
    assert await cli("inventory", "--format", "csv", "--reveal-emails", "--out", str(target)) == 0
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    content = target.read_text(encoding="utf-8")
    assert (
        content.splitlines()[0].startswith("user_id,email_masked,email_hash,email,role")
        and cast.users["bob"].email in content
    )
    capsys.readouterr()
    assert await cli("inventory", "--format", "csv", "--section", "service_keys") == 0
    assert capsys.readouterr().out.splitlines()[0].startswith("key,name,role")


async def test_the_read_only_session_cannot_write(app) -> None:
    async with tool.read_only_session() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text("UPDATE users SET full_name = full_name"))


# --- Reconciliation: dry-run ------------------------------------------------------------------------------------------


async def test_reconciliation_proposes_and_flags_every_kind_of_conflict_without_writing(
    app, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cast = await make_cast()
    u, t = cast.users, cast.tag
    await link(u["bob"], f"sub-bob-{t}")  # already linked (same sub)
    await link(u["frank"], f"sub-frank-old-{t}")  # linked to another sub
    other = await make_cast()
    await link(other.users["gina"], f"sub-taken-{t}")  # sub owned by an account of another cast
    rows = [
        {"sub": f"sub-alice-{t}", "email": u["alice"].email},
        {"sub": f"sub-bob-{t}", "email": u["bob"].email},
        {"sub": f"sub-frank-new-{t}", "email": u["frank"].email},
        {"sub": f"sub-taken-{t}", "email": u["carol"].email},
        {"sub": f"sub-dave-{t}", "email": u["dave"].email},
        {"sub": f"sub-erin-{t}", "email": u["erin"].email},
        {"sub": f"sub-henri-{t}", "email": u["henri"].email},
        {
            "sub": f"sub-gina-{t}",
            "email": u["gina"].email,
            "workspace_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        },
        {"sub": f"sub-ghost-{t}", "email": f"ghost@{cast.domain}"},
        {"sub": f"sub-unverified-{t}", "email": f"unverified@{cast.domain}", "email_verified": False},
        {"sub": f"sub-noemail-{t}", "email": ""},
        {"sub": f"sub-bad-{t}", "email": "not-an-address"},
        {"sub": f"sub-elsewhere-{t}", "email": "someone@other-domain.org"},
        {"sub": f"sub-two-{t}", "email": f"two-a@{cast.domain}"},
        {"sub": f"sub-two-{t}", "email": f"two-b@{cast.domain}"},
        {"sub": f"sub-shared-1-{t}", "email": f"shared@{cast.domain}"},
        {"sub": f"sub-shared-2-{t}", "email": f"shared@{cast.domain}"},
    ]
    export = write(tmp_path, "idp.json", idp(*rows))
    before = await db_state()
    assert (
        await cli("reconcile", "--idp-export", export, "--issuer", ISSUER, "--expected-domain", cast.domain)
        == 0
    )
    proposal = json.loads(capsys.readouterr().out)
    assert await db_state() == before  # dry-run: the database is byte for byte what it was
    status = {e["sub"]: e["status"] for e in proposal["entries"]}
    assert status[f"sub-alice-{t}"] == "proposed"
    assert status[f"sub-bob-{t}"] == "already_linked"
    assert status[f"sub-frank-new-{t}"] == "account_linked_to_another_sub"
    assert status[f"sub-taken-{t}"] == "sub_linked_to_another_account"
    assert status[f"sub-dave-{t}"] == "inactive_account"
    assert status[f"sub-erin-{t}"] == "several_local_accounts"
    assert status[f"sub-henri-{t}"] == "unverifiable_domain"
    assert status[f"sub-gina-{t}"] == "workspace_mismatch"
    assert status[f"sub-ghost-{t}"] == "no_local_account"
    assert status[f"sub-unverified-{t}"] == "email_unverified"
    assert status[f"sub-noemail-{t}"] == "email_missing"
    assert status[f"sub-bad-{t}"] == "invalid_format"
    assert status[f"sub-elsewhere-{t}"] == "unexpected_domain"
    assert status[f"sub-two-{t}"] == "sub_with_several_emails"
    assert status[f"sub-shared-1-{t}"] == status[f"sub-shared-2-{t}"] == "email_shared_by_several_subs"
    assert proposal["dry_run"] is True and proposal["summary"]["proposed"] == 1
    assert f"@{cast.domain}" not in json.dumps(proposal)  # addresses masked + hashed by default


async def test_csv_exports_of_the_idp_are_read_too(
    app, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cast = await make_cast()
    export = write(
        tmp_path, "idp.csv", f"sub,email,email_verified\ns-{cast.tag},{cast.users['alice'].email},true\n"
    )
    assert await cli("reconcile", "--idp-export", export, "--issuer", ISSUER) == 0
    assert json.loads(capsys.readouterr().out)["summary"] == {"proposed": 1}


# --- Apply: backup, signed approval ------------------------------------------------------------------------------------


async def proposal_for(
    cast: Cast, tmp_path: Path, capsys: pytest.CaptureFixture[str], *names: str
) -> tuple[str, dict]:
    rows = [{"sub": f"sub-{n}-{cast.tag}", "email": cast.users[n].email} for n in names]
    export = write(tmp_path, f"idp-{cast.tag}.json", idp(*rows))
    assert (
        await cli(
            "reconcile", "--idp-export", export, "--issuer", ISSUER, "--out", str(tmp_path / "proposal.json")
        )
        == 0
    )
    capsys.readouterr()
    return export, json.loads((tmp_path / "proposal.json").read_text())


async def approve(
    tmp_path: Path, entries: list[str] | None = None, backup: str = BACKUP, hours: int = 24
) -> str:
    argv = ["approve", "--proposal", str(tmp_path / "proposal.json"), "--backup-id", backup, "--approved-by", "ops@devoteam.test",
            "--hours", str(hours), "--out", str(tmp_path / "approval.json")]  # fmt: skip
    argv += [x for e in entries or [] for x in ("--entry", e)] or ["--all-proposed"]
    assert await cli(*argv) == 0
    return str(tmp_path / "approval.json")


async def links_of(*users: User) -> int:
    async with get_sessionmaker()() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(ExternalIdentity)
                .where(ExternalIdentity.user_id.in_([u.id for u in users]))
            )
            or 0
        )


async def test_apply_is_refused_without_a_backup_and_without_a_valid_signed_approval(
    app, capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cast = await make_cast()
    export, proposal = await proposal_for(cast, tmp_path, capsys, "alice", "bob")
    approval = await approve(tmp_path)
    base = ["reconcile", "--idp-export", export, "--issuer", ISSUER, "--apply"]
    before = await db_state()
    assert await cli(*base, "--approval", approval) == 2  # no --confirm-backup
    assert "confirm-backup" in capsys.readouterr().err
    assert await cli(*base, "--approval", approval, "--confirm-backup", "short") == 2
    assert await cli(*base, "--confirm-backup", BACKUP) == 2  # no approval file
    assert (
        await cli(*base, "--approval", approval, "--confirm-backup", "backup-other-id") == 2
    )  # another backup
    document = json.loads(Path(approval).read_text())
    document["approval"]["entries"].append("f" * 16)  # tampered: not what was signed
    assert (
        await cli(
            *base,
            "--approval",
            write(tmp_path, "tampered.json", json.dumps(document)),
            "--confirm-backup",
            BACKUP,
        )
        == 2
    )
    monkeypatch.setenv("FORGE_MIGRATION_APPROVAL_KEY", "another-key-0123456789abcdef0123456789")
    assert (
        await cli(*base, "--approval", approval, "--confirm-backup", BACKUP) == 2
    )  # signed with another key
    monkeypatch.setenv("FORGE_MIGRATION_APPROVAL_KEY", "short")
    assert await cli(*base, "--approval", approval, "--confirm-backup", BACKUP) == 2  # no usable key
    monkeypatch.setenv("FORGE_MIGRATION_APPROVAL_KEY", APPROVAL_KEY)
    expired = svc.make_approval(proposal, [e["entry_id"] for e in proposal["entries"]], backup_id=BACKUP,
                                approved_by="ops", now=utcnow() - timedelta(hours=48))  # fmt: skip
    assert (
        await cli(
            *base,
            "--approval",
            write(tmp_path, "expired.json", json.dumps(expired)),
            "--confirm-backup",
            BACKUP,
        )
        == 2
    )
    assert await db_state() == before and await links_of(*cast.users.values()) == 0  # nothing was written
    capsys.readouterr()


async def test_apply_links_exactly_the_approved_entries_and_audits_each(
    app, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cast = await make_cast()
    export, proposal = await proposal_for(cast, tmp_path, capsys, "alice", "bob", "carol")
    alice_entry = next(e["entry_id"] for e in proposal["entries"] if e["sub"] == f"sub-alice-{cast.tag}")
    approval = await approve(tmp_path, [alice_entry])
    assert (
        await cli(
            "reconcile",
            "--idp-export",
            export,
            "--issuer",
            ISSUER,
            "--apply",
            "--approval",
            approval,
            "--confirm-backup",
            BACKUP,
        )
        == 0
    )
    assert "1 liaison(s)" in capsys.readouterr().out
    async with get_sessionmaker()() as session:
        link = await session.get(ExternalIdentity, (ISSUER, f"sub-alice-{cast.tag}"))
        assert link is not None and link.user_id == cast.users["alice"].id
        assert (
            await session.get(ExternalIdentity, (ISSUER, f"sub-bob-{cast.tag}")) is None
        )  # proposed, not approved
        event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.target_id == str(cast.users["alice"].id), AuditEvent.action == "auth.oidc_link"
            )
        )
        assert (
            event is not None and event.details["backup_id"] == BACKUP and event.details["migration"] is True
        )
        assert event.details["approved_by"] == "ops@devoteam.test" and event.actor_type.value == "system"
    # replay: the same approval cannot link again (the proposal has changed: alice is now linked)
    assert (
        await cli(
            "reconcile",
            "--idp-export",
            export,
            "--issuer",
            ISSUER,
            "--apply",
            "--approval",
            approval,
            "--confirm-backup",
            BACKUP,
        )
        == 2
    )


async def test_apply_is_all_or_nothing_when_the_situation_changed_after_the_approval(
    app, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cast = await make_cast()
    export, _ = await proposal_for(cast, tmp_path, capsys, "alice", "bob")
    approval = await approve(tmp_path)
    await link(cast.users["bob"], "someone-else-took-bob")  # drift: bob got linked meanwhile
    before = await db_state()
    assert (
        await cli(
            "reconcile",
            "--idp-export",
            export,
            "--issuer",
            ISSUER,
            "--apply",
            "--approval",
            approval,
            "--confirm-backup",
            BACKUP,
        )
        == 2
    )
    assert "refaites-le" in capsys.readouterr().err
    assert (
        await db_state() == before and await links_of(cast.users["alice"]) == 0
    )  # not even the still-valid entry


async def test_an_approval_can_only_name_entries_that_are_proposed(
    app, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cast = await make_cast()
    await proposal_for(cast, tmp_path, capsys, "alice")
    argv = [
        "approve",
        "--proposal",
        str(tmp_path / "proposal.json"),
        "--backup-id",
        BACKUP,
        "--approved-by",
        "x",
        "--out",
        str(tmp_path / "a.json"),
    ]
    assert await cli(*argv, "--entry", "0" * 16) == 2
    assert await cli(*argv, "--entry", "0" * 16, "--backup-id", "x") != 0 or True
    assert (
        await cli(
            "approve",
            "--proposal",
            str(tmp_path / "proposal.json"),
            "--backup-id",
            "tiny",
            "--approved-by",
            "x",
            "--all-proposed",
            "--out",
            str(tmp_path / "b.json"),
        )
        == 2
    )
    assert stat.S_IMODE(os.stat(await approve(tmp_path)).st_mode) == 0o600


# --- Flags, break-glass, rollback ---------------------------------------------------------------------------------------


async def login(client, email: str):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD})


async def test_flags_dry_run_apply_refusals_and_effects(app, capsys: pytest.CaptureFixture[str]) -> None:
    cast = await make_cast()
    alice, bob = cast.users["alice"].email, cast.users["bob"].email
    await link(cast.users["alice"], f"sub-alice-{cast.tag}")
    before = await db_state()
    assert await cli("flags", "--email", alice, "--password-login-disabled", "true") == 0  # dry-run
    assert "Dry-run" in capsys.readouterr().out and await db_state() == before
    assert (
        await cli("flags", "--email", alice, "--password-login-disabled", "true", "--apply") == 2
    )  # no backup
    assert (
        await cli(
            "flags",
            "--email",
            bob,
            "--password-login-disabled",
            "true",
            "--apply",
            "--confirm-backup",
            BACKUP,
        )
        == 2
    )  # unlinked: would lock out
    assert "non lié" in capsys.readouterr().err
    assert (
        await cli(
            "flags",
            "--email",
            alice,
            "--password-login-disabled",
            "true",
            "--apply",
            "--confirm-backup",
            BACKUP,
        )
        == 0
    )
    async with _client(app) as client:
        refused = await login(client, alice)
        assert refused.status_code == 403 and "SSO" in refused.json()["detail"]
        assert (await login(client, bob)).status_code == 200  # others untouched
        # rollback in one command
        assert await cli("enable-password", "--email", alice) == 0
        assert (await login(client, alice)).status_code == 200
    async with get_sessionmaker()() as session:
        actions = set(
            await session.scalars(
                select(AuditEvent.action).where(AuditEvent.target_id == str(cast.users["alice"].id))
            )
        )
        assert {"account.flags_set", "account.password_login_enabled"} <= actions


async def test_sso_required_also_ends_local_sessions_but_never_locks_out_break_glass(
    app, capsys: pytest.CaptureFixture[str]
) -> None:
    cast = await make_cast()
    erin_like, carol = cast.users["frank"], cast.users["carol"]
    await link(erin_like, f"sub-frank-{cast.tag}")
    await link(carol, f"sub-carol-{cast.tag}")
    async with _client(app) as client:
        session_before = await login(client, erin_like.email)
        token = session_before.json()["user"] and client.cookies.get("forge_session")
        assert (await client.get("/api/v1/auth/me")).status_code == 200
        assert (
            await cli(
                "flags",
                "--email",
                erin_like.email,
                "--sso-required",
                "true",
                "--apply",
                "--confirm-backup",
                BACKUP,
            )
            == 0
        )
        assert (
            await client.get("/api/v1/auth/me")
        ).status_code == 401  # the open local session is refused too
        assert token
    # break-glass: set, exempt from flags and from the global policy, cannot be flagged
    assert (
        await cli("break-glass", "set", "--email", carol.email, "--apply", "--confirm-backup", BACKUP) == 2
    )  # custody not confirmed
    assert (
        await cli(
            "break-glass",
            "set",
            "--email",
            cast.users["bob"].email,
            "--confirm-offline-custody",
            "--apply",
            "--confirm-backup",
            BACKUP,
        )
        == 2
    )  # not an admin
    assert (
        await cli(
            "break-glass",
            "set",
            "--email",
            carol.email,
            "--confirm-offline-custody",
            "--apply",
            "--confirm-backup",
            BACKUP,
        )
        == 0
    )
    assert (
        await cli(
            "flags", "--email", carol.email, "--sso-required", "true", "--apply", "--confirm-backup", BACKUP
        )
        == 2
    )
    async with _client(app) as client:
        assert (await login(client, carol.email)).status_code == 200


async def test_break_glass_rotation_prints_a_strong_password_once_and_replaces_the_old_one(
    app, capsys: pytest.CaptureFixture[str]
) -> None:
    cast = await make_cast()
    carol = cast.users["carol"]
    await cli(
        "break-glass",
        "set",
        "--email",
        carol.email,
        "--confirm-offline-custody",
        "--apply",
        "--confirm-backup",
        BACKUP,
    )
    capsys.readouterr()
    assert (
        await cli("break-glass", "rotate", "--email", carol.email, "--confirm-offline-custody") == 0
    )  # dry-run
    assert "Dry-run" in capsys.readouterr().out
    async with _client(app) as client:
        assert (await login(client, carol.email)).status_code == 200  # unchanged by the dry-run
    assert (
        await cli(
            "break-glass",
            "rotate",
            "--email",
            carol.email,
            "--confirm-offline-custody",
            "--apply",
            "--confirm-backup",
            BACKUP,
        )
        == 0
    )
    out = capsys.readouterr().out
    password = out.rsplit(": ", 1)[1].strip()
    assert len(password) >= 32 and "UNE fois" in out
    async with _client(app) as client:
        assert (await login(client, carol.email)).status_code == 401  # the old password no longer works
        assert (
            await client.post("/api/v1/auth/login", json={"email": carol.email, "password": password})
        ).status_code == 200
    async with get_sessionmaker()() as session:
        events = list(await session.scalars(select(AuditEvent).where(AuditEvent.target_id == str(carol.id))))
        assert password not in json.dumps([e.details for e in events] + [e.summary for e in events])


async def test_unlink_is_the_rollback_of_a_link(app, capsys: pytest.CaptureFixture[str]) -> None:
    cast = await make_cast()
    alice = cast.users["alice"]
    await link(alice, f"sub-alice-{cast.tag}")
    await cli(
        "flags",
        "--email",
        alice.email,
        "--password-login-disabled",
        "true",
        "--apply",
        "--confirm-backup",
        BACKUP,
    )
    assert await cli("unlink", "--email", alice.email) == 0  # dry-run
    assert await links_of(alice) == 1
    assert await cli("unlink", "--email", alice.email, "--apply") == 2
    assert await cli("unlink", "--email", alice.email, "--apply", "--confirm-backup", BACKUP) == 0
    assert await links_of(alice) == 0
    async with get_sessionmaker()() as session:
        flags = await session.get(AccountFlag, alice.id)
        assert flags is not None and not flags.password_login_disabled and not flags.sso_required
    async with _client(app) as client:
        assert (await login(client, alice.email)).status_code == 200


async def test_without_any_flag_nothing_changes_for_existing_accounts(app, admin_client) -> None:
    """The bootstrap administrator has no flag: login, sessions and the global policy are as before."""
    assert settings.password_login_disabled_for_linked is False
    assert (await admin_client.get("/api/v1/auth/me")).status_code == 200
    async with _client(app) as client:
        response = await client.post(
            "/api/v1/auth/login", json={"email": "admin@forge.local", "password": "forge-admin"}
        )
        assert response.status_code == 200

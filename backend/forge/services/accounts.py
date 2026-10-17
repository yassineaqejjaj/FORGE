"""Account migration tool (ADR 001 §8, NOV-113; docs/ACCOUNTS_MIGRATION.md): inventory, reconciliation, flags.

**The tool only.** Nothing here runs by itself and nothing is executed in production by this ticket.

* :func:`inventory` and :func:`reconcile` are **read-only** (the caller opens a ``READ ONLY`` transaction):
  they return data, never write. E-mails are masked and hashed by default.
* :func:`apply_proposal` is the only writer of links: it needs a **signed approval file** (HMAC, the proposal
  it approves, the entries it approves, the backup identifier, an expiry) and the same backup identifier
  on the command line. It is all-or-nothing and audited.
* per-account flags (:class:`~forge.infra.models.AccountFlag`) and the break-glass administrator.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import re
import secrets
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.enums import Role
from forge.infra.db import utcnow
from forge.infra.models import (
    AccountFlag,
    ApiKey,
    ExternalIdentity,
    User,
    Workspace,
    WorkspaceMember,
)
from forge.infra.security import hash_password, mask_api_key
from forge.infra.workspace_scope import bind_session
from forge.services import audit
from forge.services.audit import Actor
from forge.services.taxonomy import ConflictError, InvalidError, NotFoundError

SYSTEM_ACTOR = Actor.system("forge.ops accounts")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
#: Domains that can never receive a message (an account with such an address cannot be verified by e-mail).
UNVERIFIABLE_TLDS = frozenset({"local", "localhost", "test", "invalid", "example", "internal"})
MIN_BACKUP_ID_LENGTH = 8
APPROVAL_KEY_MIN_LENGTH = 32
DEFAULT_APPROVAL_HOURS = 24


# --- E-mail helpers ---------------------------------------------------------------------------------------------------


def normalize_email(email: str) -> str:
    return email.strip().lower()


def duplicate_key(email: str) -> str:
    """Addresses that reach the same mailbox by convention (case, ``+tag``) share this key."""
    local, _, domain = normalize_email(email).partition("@")
    return f"{local.split('+', 1)[0]}@{domain}"


def email_hash(email: str) -> str:
    """SHA-256 of the normalized address: the join key of an export, without the address itself."""
    return hashlib.sha256(normalize_email(email).encode()).hexdigest()


def mask_email(email: str) -> str:
    local, _, domain = normalize_email(email).partition("@")
    name, _, tld = domain.rpartition(".")
    return f"{local[:1]}***@{name[:1]}***.{tld}" if local and name and tld else "***"


def email_problem(email: str, expected_domains: frozenset[str] = frozenset()) -> str | None:
    """Why an address cannot be trusted for matching (``None``: nothing to report)."""
    if not EMAIL_RE.match(email or ""):
        return "invalid_format"
    domain = normalize_email(email).rpartition("@")[2]
    if domain.rpartition(".")[2] in UNVERIFIABLE_TLDS:
        return "unverifiable_domain"
    if expected_domains and domain not in expected_domains:
        return "unexpected_domain"
    return None


@dataclass(slots=True)
class Reveal:
    """What an export may show of an address: ``False`` (default) = masked + hash only."""

    emails: bool = False

    def apply(self, email: str) -> dict[str, str]:
        out = {"email_masked": mask_email(email), "email_hash": email_hash(email)}
        if self.emails:
            out["email"] = normalize_email(email)
        return out


# --- Flags ------------------------------------------------------------------------------------------------------------


async def get_flags(session: AsyncSession, user_id: uuid.UUID) -> AccountFlag | None:
    return await session.get(AccountFlag, user_id)


async def is_break_glass(session: AsyncSession, user: User) -> bool:
    """The administrator that always keeps the password: flagged in the database or listed in the settings."""
    if Role(user.role) != Role.admin:
        return False
    if user.email.lower() in settings.break_glass_set:
        return True
    flags = await get_flags(session, user.id)
    return bool(flags and flags.break_glass)


async def password_login_refusal(session: AsyncSession, user: User) -> str | None:
    """Reason the password login of ``user`` is refused by an operator flag (``None``: allowed)."""
    flags = await get_flags(session, user.id)
    if flags is None or not (flags.password_login_disabled or flags.sso_required):
        return None
    if await is_break_glass(session, user):
        return None  # a break-glass administrator is never locked out
    return "sso_required" if flags.sso_required else "password_login_disabled"


async def sso_required_without_sso(session: AsyncSession, user: User) -> bool:
    """A local (non-SSO) session of a ``sso_required`` account is refused (break-glass excepted)."""
    flags = await get_flags(session, user.id)
    return bool(flags and flags.sso_required and not await is_break_glass(session, user))


async def is_linked(session: AsyncSession, user_id: uuid.UUID) -> bool:
    return (
        await session.scalar(select(ExternalIdentity.sub).where(ExternalIdentity.user_id == user_id).limit(1))
    ) is not None


async def _user(session: AsyncSession, email: str) -> User:
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        raise NotFoundError("Utilisateur introuvable")
    return user


async def _bind(session: AsyncSession, user: User) -> None:
    """Audit entries of an operation on ``user`` belong to the user's workspace."""
    from forge.services.workspaces import workspace_id_of_user

    bind_session(session, await workspace_id_of_user(session, user.id))


async def _set_flags(
    session: AsyncSession, user: User, changes: dict[str, bool], action: str, summary: str
) -> AccountFlag:
    await _bind(session, user)
    flags = await get_flags(session, user.id)
    before = {} if flags is None else {k: getattr(flags, k) for k in changes}
    if flags is None:
        flags = AccountFlag(user_id=user.id)
        session.add(flags)
    for key, value in changes.items():
        setattr(flags, key, value)
    flags.updated_by = SYSTEM_ACTOR.label
    await session.flush()
    await audit.record(
        session,
        SYSTEM_ACTOR,
        action,
        "user",
        user.id,
        summary=summary,
        details={"before": before, "after": changes},
    )
    return flags


async def plan_flags(
    session: AsyncSession, email: str, *, password_login_disabled: bool | None, sso_required: bool | None
) -> tuple[User, dict[str, bool]]:
    """Validate a flag change (nothing is written). Refuses what would lock the account out."""
    user = await _user(session, email)
    changes = {
        key: value
        for key, value in (
            ("password_login_disabled", password_login_disabled),
            ("sso_required", sso_required),
        )
        if value is not None
    }
    if not changes:
        raise InvalidError("Aucun drapeau demandé")
    if any(changes.values()):
        if await is_break_glass(session, user):
            raise ConflictError(
                "Compte break-glass : il garde toujours le mot de passe (retirez d'abord son statut)"
            )
        if not await is_linked(session, user.id):
            raise ConflictError(
                "Compte non lié au SSO : retirer son mot de passe l'exclurait (liez-le d'abord)"
            )
    return user, changes


async def apply_flags(session: AsyncSession, user: User, changes: dict[str, bool]) -> AccountFlag:
    return await _set_flags(
        session, user, changes, "account.flags_set", f"Drapeaux de migration de {user.email}"
    )


async def enable_password_login(session: AsyncSession, email: str) -> User:
    """Rollback in one command: both flags cleared, the password works again."""
    user = await _user(session, email)
    await _set_flags(
        session,
        user,
        {"password_login_disabled": False, "sso_required": False},
        "account.password_login_enabled",
        f"Mot de passe réactivé pour {user.email}",
    )
    return user


async def plan_break_glass(session: AsyncSession, email: str, *, confirm_offline_custody: bool) -> User:
    user = await _user(session, email)
    if Role(user.role) != Role.admin or not user.active:
        raise ConflictError("Un compte break-glass est un administrateur actif")
    if not confirm_offline_custody:
        raise InvalidError("--confirm-offline-custody requis : le mot de passe doit être détenu hors ligne")
    return user


async def set_break_glass(session: AsyncSession, user: User, value: bool) -> None:
    if value:
        await _set_flags(
            session,
            user,
            {"break_glass": True, "password_login_disabled": False, "sso_required": False},
            "account.break_glass_set",
            f"Compte break-glass : {user.email}",
        )
    else:
        await _set_flags(
            session,
            user,
            {"break_glass": False},
            "account.break_glass_unset",
            f"Fin du break-glass : {user.email}",
        )


async def rotate_break_glass_password(session: AsyncSession, user: User) -> str:
    """New 32-character random password (shown once by the caller, to be stored offline); other sessions end."""
    await _bind(session, user)
    password = secrets.token_urlsafe(24)
    user.password_hash = hash_password(password)
    await session.flush()
    await audit.record(
        session,
        SYSTEM_ACTOR,
        "account.break_glass_rotated",
        "user",
        user.id,
        summary=f"Mot de passe break-glass renouvelé pour {user.email}",
        details={},
    )
    return password


async def unlink(session: AsyncSession, email: str) -> int:
    """Rollback of a link: the identity is removed and the account's SSO flags cleared. Returns the links removed."""
    user = await _user(session, email)
    await _bind(session, user)
    links = list(await session.scalars(select(ExternalIdentity).where(ExternalIdentity.user_id == user.id)))
    for link in links:
        await session.delete(link)
    await session.flush()
    await _set_flags(
        session,
        user,
        {"password_login_disabled": False, "sso_required": False},
        "account.unlinked",
        f"Liaison SSO retirée pour {user.email}",
    )
    return len(links)


# --- Inventory (read only) ------------------------------------------------------------------------------------------


async def inventory(
    session: AsyncSession, *, reveal: Reveal | None = None, expected_domains: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Every account and key, with duplicates and unverifiable addresses. Reads only."""
    reveal = reveal or Reveal()
    users = list(await session.scalars(select(User).order_by(User.created_at, User.email)))
    flags = {f.user_id: f for f in await session.scalars(select(AccountFlag))}
    links: dict[uuid.UUID, list[ExternalIdentity]] = defaultdict(list)
    for link in await session.scalars(select(ExternalIdentity)):
        links[link.user_id].append(link)
    members = {m.user_id: m.workspace_id for m in await session.scalars(select(WorkspaceMember))}
    slugs = {w.id: w.slug for w in await session.scalars(select(Workspace))}
    from forge.infra.models import ORION_DEFAULT_WORKSPACE_ID

    groups: dict[str, list[User]] = defaultdict(list)
    for user in users:
        groups[duplicate_key(user.email)].append(user)
    rows: list[dict[str, Any]] = []
    for user in users:
        flag = flags.get(user.id)
        problem = email_problem(user.email, expected_domains)
        rows.append(
            {
                "user_id": str(user.id),
                **reveal.apply(user.email),
                "role": Role(user.role).value,
                "clearance": int(user.clearance),
                "active": user.active,
                "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
                "workspace": slugs.get(members.get(user.id, ORION_DEFAULT_WORKSPACE_ID)),
                "linked": bool(links.get(user.id)),
                "linked_issuers": sorted({link.issuer for link in links.get(user.id, [])}),
                "password_login_disabled": bool(flag and flag.password_login_disabled),
                "sso_required": bool(flag and flag.sso_required),
                "break_glass": await is_break_glass(session, user),
                "email_problem": problem,
                "duplicate_group": duplicate_key(user.email)
                if len(groups[duplicate_key(user.email)]) > 1
                else None,
            }
        )
    for row in rows:
        if row["duplicate_group"]:
            row["duplicate_group"] = hashlib.sha256(row["duplicate_group"].encode()).hexdigest()[:12]
    keys = []
    for key in await session.scalars(select(ApiKey).order_by(ApiKey.created_at)):
        keys.append(
            {
                "key": mask_api_key(key.prefix),
                "name": key.name,
                "role": Role(key.role).value,
                "clearance": int(key.clearance),
                "workspace": slugs.get(key.workspace_id),
                "project_id": str(key.project_id) if key.project_id else None,
                "scopes": list(key.scopes or []),
                "service": True,
                "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
                "expires_at": key.expires_at.isoformat() if key.expires_at else None,
                "revoked": key.revoked_at is not None,
            }
        )
    duplicates = [
        {"group": hashlib.sha256(k.encode()).hexdigest()[:12], "user_ids": [str(u.id) for u in us]}
        for k, us in groups.items()
        if len(us) > 1
    ]
    return {
        "generated_at": utcnow().isoformat(),
        "emails_revealed": reveal.emails,
        "summary": {
            "accounts": len(rows),
            "active": sum(1 for r in rows if r["active"]),
            "linked": sum(1 for r in rows if r["linked"]),
            "break_glass": sum(1 for r in rows if r["break_glass"]),
            "duplicate_groups": len(duplicates),
            "unverifiable_emails": sum(1 for r in rows if r["email_problem"]),
            "api_keys": len(keys),
        },
        "accounts": rows,
        "duplicates": duplicates,
        "service_keys": keys,
    }


def to_csv(rows: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    if rows:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (json.dumps(v) if isinstance(v, list) else v) for k, v in row.items()})
    return out.getvalue()


# --- Reconciliation (read only) ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IdpAccount:
    sub: str
    email: str
    email_verified: bool
    workspace_id: str | None = None


def parse_idp_export(text: str) -> list[IdpAccount]:
    """An IdP export: JSON list of objects, or CSV with ``sub,email,email_verified[,workspace_id]``."""
    text = text.strip()
    try:
        raw = json.loads(text) if text.startswith(("[", "{")) else list(csv.DictReader(io.StringIO(text)))
    except ValueError as exc:
        raise InvalidError("Export de l'IdP illisible (JSON ou CSV attendu)") from exc
    if isinstance(raw, dict):
        raw = raw.get("users") or raw.get("accounts") or []
    if not isinstance(raw, list):
        raise InvalidError("Export de l'IdP : liste attendue")
    accounts = []
    for item in raw:
        if not isinstance(item, dict):
            raise InvalidError("Export de l'IdP : objet attendu par ligne")
        verified = item.get("email_verified", item.get("emailVerified", False))
        accounts.append(
            IdpAccount(
                sub=str(item.get("sub") or item.get("id") or "").strip(),
                email=str(item.get("email") or "").strip(),
                email_verified=verified
                if isinstance(verified, bool)
                else str(verified).strip().lower() in {"1", "true", "yes", "oui"},
                workspace_id=(
                    str(item["workspace_id"]).strip().lower() if item.get("workspace_id") else None
                ),
            )
        )
    return accounts


def entry_id(user_id: uuid.UUID | str, issuer: str, sub: str) -> str:
    return hashlib.sha256(f"{user_id}|{issuer}|{sub}".encode()).hexdigest()[:16]


def canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


async def reconcile(
    session: AsyncSession,
    idp: list[IdpAccount],
    *,
    issuer: str,
    expected_domains: frozenset[str] = frozenset(),
    reveal: Reveal | None = None,
) -> dict[str, Any]:
    """The table ``local account <-> sub`` that *would* be created, and every conflict. Reads only."""
    reveal = reveal or Reveal()
    users = list(await session.scalars(select(User)))
    by_email: dict[str, list[User]] = defaultdict(list)
    for user in users:
        by_email[normalize_email(user.email)].append(user)
    local_duplicates = {
        duplicate_key(u.email)
        for u in users
        if sum(1 for v in users if duplicate_key(v.email) == duplicate_key(u.email)) > 1
    }
    links = [
        (link.issuer, link.sub, link.user_id) for link in await session.scalars(select(ExternalIdentity))
    ]
    sub_owner = {(i, s): u for i, s, u in links}
    user_sub = {(i, u): s for i, s, u in links}
    members = {m.user_id: str(m.workspace_id) for m in await session.scalars(select(WorkspaceMember))}
    from forge.infra.models import ORION_DEFAULT_WORKSPACE_ID

    sub_emails: dict[str, set[str]] = defaultdict(set)
    email_subs: dict[str, set[str]] = defaultdict(set)
    for account in idp:
        if account.sub and account.email:
            sub_emails[account.sub].add(normalize_email(account.email))
            email_subs[normalize_email(account.email)].add(account.sub)

    entries: list[dict[str, Any]] = []
    for account in idp:
        entry: dict[str, Any] = {"sub": account.sub, "status": "", "user_id": None, "entry_id": None}
        email = normalize_email(account.email)
        if account.email:
            entry.update(reveal.apply(account.email))
        if not account.sub:
            entry["status"] = "sub_missing"
        elif not account.email:
            entry["status"] = "email_missing"
        elif (problem := email_problem(account.email, expected_domains)) in {
            "invalid_format",
            "unverifiable_domain",
            "unexpected_domain",
        }:
            entry["status"] = problem or ""
        elif not account.email_verified:
            entry["status"] = "email_unverified"
        elif len(sub_emails[account.sub]) > 1:
            entry["status"] = "sub_with_several_emails"
        elif len(email_subs[email]) > 1:
            entry["status"] = "email_shared_by_several_subs"
        else:
            matches = by_email.get(email, [])
            if not matches:
                entry["status"] = "no_local_account"
            elif len(matches) > 1 or duplicate_key(email) in local_duplicates:
                entry["status"] = "several_local_accounts"
            else:
                user = matches[0]
                entry.update({"user_id": str(user.id), "role": Role(user.role).value, "active": user.active})
                owner = sub_owner.get((issuer, account.sub))
                if not user.active:
                    entry["status"] = "inactive_account"
                elif owner == user.id:
                    entry["status"] = "already_linked"
                elif owner is not None:
                    entry["status"] = "sub_linked_to_another_account"
                elif (issuer, user.id) in user_sub:
                    entry["status"] = "account_linked_to_another_sub"
                elif account.workspace_id and account.workspace_id != members.get(
                    user.id, str(ORION_DEFAULT_WORKSPACE_ID)
                ):
                    entry["status"] = "workspace_mismatch"
                else:
                    entry["status"] = "proposed"
                    entry["entry_id"] = entry_id(user.id, issuer, account.sub)
        entries.append(entry)
    entries.sort(key=lambda e: (e["status"] != "proposed", e["sub"], e.get("email_hash", "")))
    proposed = [e for e in entries if e["status"] == "proposed"]
    summary: dict[str, int] = defaultdict(int)
    for e in entries:
        summary[e["status"]] += 1
    proposal_id = hashlib.sha256(
        canonical(
            {"issuer": issuer, "proposed": sorted((e["entry_id"], e["user_id"], e["sub"]) for e in proposed)}
        ).encode()
    ).hexdigest()
    return {
        "version": 1,
        "dry_run": True,
        "generated_at": utcnow().isoformat(),
        "issuer": issuer,
        "expected_domains": sorted(expected_domains),
        "proposal_id": proposal_id,
        "summary": dict(sorted(summary.items())),
        "entries": entries,
    }


# --- Approval (signed) and apply -------------------------------------------------------------------------------------


def _approval_key() -> bytes:
    import os

    key = os.environ.get("FORGE_MIGRATION_APPROVAL_KEY", "")
    if len(key) < APPROVAL_KEY_MIN_LENGTH:
        raise InvalidError(
            f"FORGE_MIGRATION_APPROVAL_KEY (≥ {APPROVAL_KEY_MIN_LENGTH} caractères) requis pour signer / vérifier une approbation"
        )
    return key.encode()


def _sign(approval: dict[str, Any]) -> str:
    return hmac.new(_approval_key(), canonical(approval).encode(), hashlib.sha256).hexdigest()


def make_approval(
    proposal: dict[str, Any],
    entry_ids: list[str],
    *,
    backup_id: str,
    approved_by: str,
    hours: int = DEFAULT_APPROVAL_HOURS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """A signed approval of some entries of a proposal (written by the operator, read by ``--apply``)."""
    proposed = {e["entry_id"] for e in proposal["entries"] if e["status"] == "proposed"}
    unknown = sorted(set(entry_ids) - proposed)
    if not entry_ids or unknown:
        raise InvalidError(
            f"Entrées non approuvables (absentes ou en conflit) : {', '.join(unknown) or 'aucune entrée'}"
        )
    if len(backup_id.strip()) < MIN_BACKUP_ID_LENGTH:
        raise InvalidError(f"Identifiant de sauvegarde trop court (≥ {MIN_BACKUP_ID_LENGTH} caractères)")
    moment = now or utcnow()
    approval = {
        "proposal_id": proposal["proposal_id"],
        "issuer": proposal["issuer"],
        "entries": sorted(entry_ids),
        "backup_id": backup_id.strip(),
        "approved_by": approved_by,
        "approved_at": moment.isoformat(),
        "expires_at": (moment + timedelta(hours=hours)).isoformat(),
    }
    return {"approval": approval, "signature": _sign(approval)}


def verify_approval(
    document: dict[str, Any], *, confirm_backup: str, now: datetime | None = None
) -> dict[str, Any]:
    """The approval if (and only if) it is signed, unexpired and tied to this backup; else :class:`InvalidError`."""
    approval = document.get("approval")
    signature = document.get("signature")
    if not isinstance(approval, dict) or not isinstance(signature, str):
        raise InvalidError("Fichier d'approbation invalide")
    if not hmac.compare_digest(_sign(approval), signature):
        raise InvalidError("Signature d'approbation invalide (fichier modifié ou autre clé)")
    if len(confirm_backup.strip()) < MIN_BACKUP_ID_LENGTH or confirm_backup.strip() != approval.get(
        "backup_id"
    ):
        raise InvalidError("--confirm-backup ne correspond pas à la sauvegarde approuvée")
    if datetime.fromisoformat(approval["expires_at"]) <= (now or utcnow()):
        raise InvalidError("Approbation expirée : refaites un rapprochement et une approbation")
    return approval


async def apply_proposal(
    session: AsyncSession, proposal: dict[str, Any], approval: dict[str, Any]
) -> list[ExternalIdentity]:
    """Link exactly the approved entries (flush, caller commits). All or nothing: any drift aborts before a write."""
    if approval["proposal_id"] != proposal["proposal_id"] or approval["issuer"] != proposal["issuer"]:
        raise ConflictError("Le rapprochement actuel n'est plus celui qui a été approuvé : refaites-le")
    current = {e["entry_id"]: e for e in proposal["entries"] if e["status"] == "proposed"}
    missing = sorted(set(approval["entries"]) - set(current))
    if missing:
        raise ConflictError(f"Entrées approuvées devenues conflictuelles ou absentes : {', '.join(missing)}")
    created = []
    for eid in approval["entries"]:
        entry = current[eid]
        user = await session.get(User, uuid.UUID(entry["user_id"]))
        if user is None:
            raise NotFoundError("Utilisateur introuvable")
        await _bind(session, user)
        link = ExternalIdentity(issuer=proposal["issuer"], sub=entry["sub"], user_id=user.id)
        session.add(link)
        await session.flush()
        await audit.record(
            session,
            SYSTEM_ACTOR,
            "auth.oidc_link",
            "user",
            user.id,
            summary=f"Liaison SSO appliquée par l'outil de migration pour {user.email}",
            details={
                "migration": True,
                "entry_id": eid,
                "issuer": proposal["issuer"],
                "sub": entry["sub"],
                "backup_id": approval["backup_id"],
                "approved_by": approval["approved_by"],
                "proposal_id": approval["proposal_id"],
            },
        )
        created.append(link)
    return created

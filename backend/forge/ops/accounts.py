"""``python -m forge.ops accounts …``: the account migration tool (ADR 001 §8, NOV-113).

Read-only by construction: ``inventory`` and ``reconcile`` run in a ``READ ONLY`` transaction that is rolled back.
Every writing command is a dry run unless ``--apply`` is given, and ``--apply`` additionally needs
``--confirm-backup <id>`` (and, to link accounts, a signed approval file). See docs/ACCOUNTS_MIGRATION.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.infra.db import get_sessionmaker
from forge.services import accounts
from forge.services.taxonomy import PlatformError

EXIT_OK, EXIT_REFUSED = 0, 2


def _bool(value: str) -> bool:
    if value.lower() in {"true", "1", "yes", "oui"}:
        return True
    if value.lower() in {"false", "0", "no", "non"}:
        return False
    raise argparse.ArgumentTypeError("true ou false attendu")


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    accounts_cmd = sub.add_parser(
        "accounts", help="Outil de migration des comptes (inventaire, rapprochement, drapeaux)"
    )
    commands = accounts_cmd.add_subparsers(dest="accounts_command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--reveal-emails",
            action="store_true",
            help="afficher les adresses en clair (défaut : masquées + hash)",
        )
        p.add_argument(
            "--expected-domain", action="append", default=[], help="domaine d'e-mail attendu (répétable)"
        )
        p.add_argument("--out", help="fichier de sortie (mode 0600) au lieu de la sortie standard")

    inv = commands.add_parser(
        "inventory", help="Inventaire en lecture seule (comptes, clés, doublons, e-mails)"
    )
    common(inv)
    inv.add_argument("--format", choices=["json", "csv"], default="json")
    inv.add_argument(
        "--section", choices=["accounts", "service_keys"], default="accounts", help="section du CSV"
    )

    rec = commands.add_parser("reconcile", help="Rapprochement avec l'export de l'IdP (dry-run par défaut)")
    common(rec)
    rec.add_argument(
        "--idp-export",
        required=True,
        help="export de l'IdP : JSON ou CSV (sub, email, email_verified[, workspace_id])",
    )
    rec.add_argument("--issuer", help="iss de l'IdP (défaut : FORGE_OIDC_ISSUER)")
    rec.add_argument(
        "--apply",
        action="store_true",
        help="écrire les liaisons approuvées (exige --approval et --confirm-backup)",
    )
    rec.add_argument("--approval", help="fichier d'approbation signé (accounts approve)")
    rec.add_argument("--confirm-backup", help="identifiant de la sauvegarde faite avant d'écrire")

    app = commands.add_parser("approve", help="Signer l'approbation de certaines entrées d'un rapprochement")
    app.add_argument("--proposal", required=True, help="sortie de `accounts reconcile`")
    app.add_argument("--entry", action="append", default=[], help="entry_id à approuver (répétable)")
    app.add_argument("--all-proposed", action="store_true", help="approuver toutes les entrées proposées")
    app.add_argument("--backup-id", required=True, help="identifiant de la sauvegarde (≥ 8 caractères)")
    app.add_argument("--approved-by", required=True)
    app.add_argument("--hours", type=int, default=accounts.DEFAULT_APPROVAL_HOURS)
    app.add_argument("--out", required=True)

    flags = commands.add_parser("flags", help="Drapeaux par compte (dry-run par défaut)")
    flags.add_argument("--email", required=True)
    flags.add_argument("--password-login-disabled", type=_bool)
    flags.add_argument("--sso-required", type=_bool)
    flags.add_argument("--apply", action="store_true")
    flags.add_argument("--confirm-backup")

    enable = commands.add_parser(
        "enable-password", help="Retour arrière : réactiver le mot de passe d'un compte"
    )
    enable.add_argument("--email", required=True)

    bg = commands.add_parser("break-glass", help="Compte administrateur break-glass (mot de passe, hors SSO)")
    bg.add_argument("action", choices=["set", "unset", "rotate"])
    bg.add_argument("--email", required=True)
    bg.add_argument(
        "--confirm-offline-custody", action="store_true", help="le mot de passe est détenu hors ligne"
    )
    bg.add_argument("--apply", action="store_true")
    bg.add_argument("--confirm-backup")

    un = commands.add_parser("unlink", help="Retour arrière : retirer la liaison SSO d'un compte")
    un.add_argument("--email", required=True)
    un.add_argument("--apply", action="store_true")
    un.add_argument("--confirm-backup")


# --- plumbing --------------------------------------------------------------------------------------------------------


@asynccontextmanager
async def read_only_session() -> AsyncIterator[AsyncSession]:
    """A session whose transaction is ``READ ONLY`` and always rolled back: no write is possible."""
    async with get_sessionmaker()() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        try:
            yield session
        finally:
            await session.rollback()


@asynccontextmanager
async def write_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


def emit(data: str, out: str | None) -> None:
    if not out:
        print(data)
        return
    descriptor = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # holds hashes / approvals
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(data if data.endswith("\n") else data + "\n")
    print(f"Écrit : {out} (mode 0600)", file=sys.stderr)


def _require_backup(apply: bool, confirm_backup: str | None) -> str | None:
    """``--apply`` without a backup identifier is refused before anything is read or written."""
    if not apply:
        return None
    if not confirm_backup or len(confirm_backup.strip()) < accounts.MIN_BACKUP_ID_LENGTH:
        raise accounts.InvalidError(
            f"--apply refusé sans --confirm-backup <identifiant ≥ {accounts.MIN_BACKUP_ID_LENGTH} caractères> : "
            "faites et vérifiez une sauvegarde de la base d'abord"
        )
    return confirm_backup.strip()


def _domains(args: argparse.Namespace) -> frozenset[str]:
    return frozenset(d.strip().lower() for d in args.expected_domain)


# --- commands --------------------------------------------------------------------------------------------------------


async def cmd_inventory(args: argparse.Namespace) -> int:
    async with read_only_session() as session:
        data = await accounts.inventory(
            session, reveal=accounts.Reveal(args.reveal_emails), expected_domains=_domains(args)
        )
    if args.format == "csv":
        emit(accounts.to_csv(data[args.section]), args.out)
    else:
        emit(json.dumps(data, ensure_ascii=False, indent=2), args.out)
    summary = data["summary"]
    print(
        f"{summary['accounts']} compte(s), {summary['linked']} lié(s), {summary['duplicate_groups']} groupe(s) de "
        f"doublons, {summary['unverifiable_emails']} e-mail(s) invérifiable(s), {summary['api_keys']} clé(s) de service.",
        file=sys.stderr,
    )
    return EXIT_OK


async def cmd_reconcile(args: argparse.Namespace) -> int:
    backup = _require_backup(args.apply, args.confirm_backup)
    issuer = (args.issuer or settings.oidc_issuer).strip().rstrip("/")
    if not issuer:
        raise accounts.InvalidError("--issuer (ou FORGE_OIDC_ISSUER) requis")
    idp = accounts.parse_idp_export(Path(args.idp_export).read_text(encoding="utf-8"))
    async with read_only_session() as session:
        proposal = await accounts.reconcile(
            session,
            idp,
            issuer=issuer,
            expected_domains=_domains(args),
            reveal=accounts.Reveal(args.reveal_emails),
        )
    if not args.apply:
        emit(json.dumps(proposal, ensure_ascii=False, indent=2), args.out)
        summary = ", ".join(f"{k}={v}" for k, v in proposal["summary"].items()) or "rien"
        print(
            f"Dry-run : aucune écriture. {summary}. proposal_id={proposal['proposal_id'][:16]}…",
            file=sys.stderr,
        )
        return EXIT_OK
    assert backup is not None
    if not args.approval:
        raise accounts.InvalidError("--apply exige --approval <fichier signé> (accounts approve)")
    approval = accounts.verify_approval(
        json.loads(Path(args.approval).read_text(encoding="utf-8")), confirm_backup=backup
    )
    async with write_session() as session:
        links = await accounts.apply_proposal(session, proposal, approval)
    print(
        f"{len(links)} liaison(s) appliquée(s) (sauvegarde {backup}, approuvé par {approval['approved_by']})."
    )
    return EXIT_OK


async def cmd_approve(args: argparse.Namespace) -> int:
    proposal: dict[str, Any] = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
    ids = (
        [e["entry_id"] for e in proposal["entries"] if e["status"] == "proposed"]
        if args.all_proposed
        else args.entry
    )
    document = accounts.make_approval(
        proposal, ids, backup_id=args.backup_id, approved_by=args.approved_by, hours=args.hours
    )
    emit(json.dumps(document, indent=2), args.out)
    print(f"{len(ids)} entrée(s) approuvée(s), valable(s) {args.hours} h.", file=sys.stderr)
    return EXIT_OK


async def cmd_flags(args: argparse.Namespace) -> int:
    backup = _require_backup(args.apply, args.confirm_backup)
    async with read_only_session() as session:
        user, changes = await accounts.plan_flags(
            session,
            args.email,
            password_login_disabled=args.password_login_disabled,
            sso_required=args.sso_required,
        )
        label = user.email
    if not args.apply:
        print(
            f"Dry-run : {label} → {changes} (aucune écriture ; --apply --confirm-backup <id> pour appliquer)."
        )
        return EXIT_OK
    async with write_session() as session:
        user, changes = await accounts.plan_flags(
            session,
            args.email,
            password_login_disabled=args.password_login_disabled,
            sso_required=args.sso_required,
        )
        await accounts.apply_flags(session, user, changes)
    print(
        f"Drapeaux appliqués à {label} : {changes} (sauvegarde {backup}). Retour arrière : accounts enable-password."
    )
    return EXIT_OK


async def cmd_enable_password(args: argparse.Namespace) -> int:
    async with write_session() as session:
        user = await accounts.enable_password_login(session, args.email)
    print(f"Mot de passe réactivé pour {user.email}.")
    return EXIT_OK


async def cmd_break_glass(args: argparse.Namespace) -> int:
    backup = _require_backup(args.apply, args.confirm_backup)
    async with read_only_session() as session:
        user = await accounts.plan_break_glass(
            session,
            args.email,
            confirm_offline_custody=args.confirm_offline_custody or args.action == "unset",
        )
        label = user.email
    if not args.apply:
        print(f"Dry-run : break-glass {args.action} pour {label} (aucune écriture).")
        return EXIT_OK
    async with write_session() as session:
        user = await accounts.plan_break_glass(
            session,
            args.email,
            confirm_offline_custody=args.confirm_offline_custody or args.action == "unset",
        )
        if args.action == "rotate":
            password = await accounts.rotate_break_glass_password(session, user)
        else:
            await accounts.set_break_glass(session, user, args.action == "set")
            password = None
    if password:
        print(
            f"Nouveau mot de passe break-glass de {label} (affiché UNE fois, à ranger hors ligne) : {password}"
        )
    else:
        print(f"Break-glass {args.action} : {label} (sauvegarde {backup}).")
    return EXIT_OK


async def cmd_unlink(args: argparse.Namespace) -> int:
    backup = _require_backup(args.apply, args.confirm_backup)
    if not args.apply:
        print(f"Dry-run : la liaison SSO de {args.email} serait retirée (aucune écriture).")
        return EXIT_OK
    async with write_session() as session:
        removed = await accounts.unlink(session, args.email)
    print(f"{removed} liaison(s) retirée(s) pour {args.email} (sauvegarde {backup}) ; mot de passe réactivé.")
    return EXIT_OK


HANDLERS = {
    "inventory": cmd_inventory,
    "reconcile": cmd_reconcile,
    "approve": cmd_approve,
    "flags": cmd_flags,
    "enable-password": cmd_enable_password,
    "break-glass": cmd_break_glass,
    "unlink": cmd_unlink,
}


async def run(args: argparse.Namespace) -> int:
    try:
        return await HANDLERS[args.accounts_command](args)
    except PlatformError as exc:
        print(f"Refusé : {exc}", file=sys.stderr)
        return EXIT_REFUSED

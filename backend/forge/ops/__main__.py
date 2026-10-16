"""``python -m forge.ops``: maintenance commands for operators.

* ``rotate-secrets`` — re-encrypt every provider credential with the current ``FORGE_SECRETS_KEY``,
  reading them with the previous key given in ``FORGE_SECRETS_KEY_OLD``;
* ``check-secrets`` — verify that every stored secret can be decrypted with the current key;
* ``purge-payloads --older-than-days N`` — drop trace event payloads (input/output) of old runs,
  keeping the timeline structure, scores and explanations (storage retention);
* ``retention [--dry-run]`` — apply every ``FORGE_RETENTION_*_DAYS`` rule now (traces, judge prompts and
  answers, judge cache, feedback evidence), or only count what would be purged;
* ``workspace-list``, ``workspace-create``, ``project-create``, ``workspace-add-user`` — ORION workspaces
  and projects (docs/WORKSPACES.md). Platform commands: they act across every workspace.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import os
import sys
import uuid
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, update

from forge.infra.db import dispose_engine, session_scope, utcnow
from forge.infra.models import EvaluationRun, ProviderCredential, TraceEvent
from forge.infra.security import SecretDecryptionError, decrypt_secret, encrypt_secret
from forge.infra.workspace_scope import bind_session, enforcement_mode


def _fernet_from(raw_key: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw_key.encode("utf-8")).digest()))


async def rotate_secrets() -> int:
    old_key = os.environ.get("FORGE_SECRETS_KEY_OLD", "")
    if len(old_key) < 16:
        print("FORGE_SECRETS_KEY_OLD doit contenir l'ancienne clé.", file=sys.stderr)
        return 2
    old = _fernet_from(old_key)
    rotated = 0
    async with session_scope() as session:
        for credential in await session.scalars(select(ProviderCredential).with_for_update()):
            for column in ("secret_encrypted", "headers_encrypted"):
                token = getattr(credential, column)
                if not token:
                    continue
                try:
                    plain = old.decrypt(token.encode("ascii")).decode("utf-8")
                except InvalidToken:
                    # Already encrypted with the new key (rotation re-run): keep it if readable.
                    decrypt_secret(token)
                    continue
                setattr(credential, column, encrypt_secret(plain))
                rotated += 1
    print(f"{rotated} secret(s) re-chiffré(s) avec la nouvelle clé.")
    return 0


async def check_secrets() -> int:
    failures = 0
    async with session_scope() as session:
        for credential in await session.scalars(select(ProviderCredential)):
            for column in ("secret_encrypted", "headers_encrypted"):
                token = getattr(credential, column)
                if not token:
                    continue
                try:
                    decrypt_secret(token)
                except SecretDecryptionError:
                    failures += 1
                    print(f"Illisible : identifiant « {credential.name} » ({column})", file=sys.stderr)
    print("Tous les secrets sont lisibles." if not failures else f"{failures} secret(s) illisible(s).")
    return 1 if failures else 0


async def purge_payloads(days: int) -> int:
    threshold = utcnow() - timedelta(days=days)
    async with session_scope() as session:
        old_runs = select(EvaluationRun.id).where(EvaluationRun.finished_at < threshold)
        result = await session.execute(
            update(TraceEvent)
            .where(
                TraceEvent.run_id.in_(old_runs),
                (TraceEvent.input.is_not(None)) | (TraceEvent.output.is_not(None)),
            )
            .values(input=None, output=None)
            .returning(TraceEvent.id)
        )
        count = len(result.all())
    print(f"Payloads purgés sur {count} événement(s) de trace (runs terminés il y a plus de {days} jours).")
    return 0


async def retention_pass(dry_run: bool) -> int:
    from forge.services import retention

    async with session_scope() as session:
        report = await retention.purge(session, dry_run=dry_run, trigger="cli")
    if report.skipped:
        print("Une purge est déjà en cours (verrou pris par un autre processus).", file=sys.stderr)
        return 1
    verb = "seraient purgés" if dry_run else "purgés"
    print(
        f"Rétention : {report.traces} trace(s), {report.trace_events} événement(s), "
        f"{report.evaluations} évaluation(s), {report.judge_cache} entrée(s) de cache, "
        f"{report.feedback_reports} rapport(s) de feedback {verb}."
    )
    return 0


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


async def workspace_list() -> int:
    from forge.services import workspaces

    async with session_scope() as session:
        for workspace in await workspaces.list_workspaces(session):
            print(f"{workspace.id}  {workspace.slug}  {workspace.name}")
            for project in await workspaces.list_projects(session, workspace):
                print(f"    {project.id}  {project.slug}  {project.name}")
    print(f"Mode d'isolation : {enforcement_mode()}")
    return 0


async def workspace_create(slug: str, name: str, workspace_id: str | None, allow_off: bool) -> int:
    from forge.services import bootstrap, workspaces
    from forge.services.taxonomy import PlatformError

    if enforcement_mode() == "off" and not allow_off:
        print(
            "FORGE_WORKSPACE_ENFORCEMENT=off : les données d'un second espace seraient visibles de tous. "
            "Passez en `shadow` ou `enforce`, ou confirmez avec --allow-off.",
            file=sys.stderr,
        )
        return 2
    try:
        async with session_scope() as session:
            workspace = await workspaces.create_workspace(
                session, slug=slug, name=name, workspace_id=_parse_uuid(workspace_id)
            )
            bind_session(session, workspace.id)
            await bootstrap.ensure_workspace_defaults(session, workspace.slug)
    except PlatformError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Espace créé : {workspace.id} ({workspace.slug})")
    return 0


async def project_create(workspace_ref: str, slug: str, name: str, project_id: str | None) -> int:
    from forge.services import workspaces
    from forge.services.taxonomy import PlatformError

    try:
        async with session_scope() as session:
            workspace = await workspaces.get_workspace(session, workspace_ref)
            project = await workspaces.create_project(
                session, workspace, slug=slug, name=name, project_id=_parse_uuid(project_id)
            )
    except PlatformError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Projet créé : {project.id} ({workspace.slug}/{project.slug})")
    return 0


async def workspace_add_user(workspace_ref: str, email: str) -> int:
    from forge.services import users, workspaces
    from forge.services.taxonomy import PlatformError

    try:
        async with session_scope() as session:
            workspace = await workspaces.get_workspace(session, workspace_ref)
            user = await users.get_by_email(session, email)
            if user is None:
                print("Utilisateur introuvable", file=sys.stderr)
                return 2
            await workspaces.set_membership(session, user, workspace)
    except PlatformError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"{user.email} appartient désormais à l'espace {workspace.slug}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m forge.ops", description="Commandes d'exploitation FORGE")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("rotate-secrets", help="Re-chiffrer les identifiants avec la nouvelle FORGE_SECRETS_KEY")
    sub.add_parser("check-secrets", help="Vérifier que tous les secrets sont déchiffrables")
    purge = sub.add_parser("purge-payloads", help="Supprimer les payloads de trace des anciens runs")
    purge.add_argument("--older-than-days", type=int, required=True)
    retention_cmd = sub.add_parser("retention", help="Appliquer les règles de rétention (FORGE_RETENTION_*)")
    retention_cmd.add_argument("--dry-run", action="store_true", help="compter sans rien purger")
    sub.add_parser("workspace-list", help="Lister les espaces et leurs projets")
    ws_create = sub.add_parser("workspace-create", help="Créer un espace (et sa configuration par défaut)")
    ws_create.add_argument("--slug", required=True)
    ws_create.add_argument("--name", required=True)
    ws_create.add_argument("--id", dest="workspace_id", help="orion_workspace_id imposé par l'IdP (UUID)")
    ws_create.add_argument(
        "--allow-off", action="store_true", help="créer même si FORGE_WORKSPACE_ENFORCEMENT=off"
    )
    proj_create = sub.add_parser("project-create", help="Créer un projet dans un espace")
    proj_create.add_argument("--workspace", required=True, help="orion_workspace_id ou alias")
    proj_create.add_argument("--slug", required=True)
    proj_create.add_argument("--name", required=True)
    proj_create.add_argument("--id", dest="project_id", help="orion_project_id imposé (UUID)")
    ws_user = sub.add_parser("workspace-add-user", help="Placer un utilisateur dans un espace")
    ws_user.add_argument("--workspace", required=True, help="orion_workspace_id ou alias")
    ws_user.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    async def run() -> int:
        try:
            if args.command == "rotate-secrets":
                return await rotate_secrets()
            if args.command == "check-secrets":
                return await check_secrets()
            if args.command == "retention":
                return await retention_pass(args.dry_run)
            if args.command == "workspace-list":
                return await workspace_list()
            if args.command == "workspace-create":
                return await workspace_create(args.slug, args.name, args.workspace_id, args.allow_off)
            if args.command == "project-create":
                return await project_create(args.workspace, args.slug, args.name, args.project_id)
            if args.command == "workspace-add-user":
                return await workspace_add_user(args.workspace, args.email)
            return await purge_payloads(max(1, args.older_than_days))
        finally:
            await dispose_engine()

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())

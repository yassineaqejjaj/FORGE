"""``python -m forge.ops``: maintenance commands for operators.

* ``rotate-secrets`` — re-encrypt every provider credential with the current ``FORGE_SECRETS_KEY``,
  reading them with the previous key given in ``FORGE_SECRETS_KEY_OLD``;
* ``check-secrets`` — verify that every stored secret can be decrypted with the current key;
* ``purge-payloads --older-than-days N`` — drop trace event payloads (input/output) of old runs,
  keeping the timeline structure, scores and explanations (storage retention);
* ``retention [--dry-run]`` — apply every ``FORGE_RETENTION_*_DAYS`` rule now (traces, judge prompts and
  answers, judge cache, feedback evidence), or only count what would be purged;
* ``api-keys [--workspace W] [--project P] [--json]`` — list the service keys by workspace / project (age,
  last use, expiry, status), **never** a secret or a hash; ``api-key-create`` attaches a key to a workspace /
  project (the full key is shown once); ``project-move`` moves a project and revokes its keys (NOV-112);
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

from forge.domain.enums import Role
from forge.infra.db import dispose_engine, session_scope, utcnow
from forge.infra.models import ApiKey, EvaluationRun, ProviderCredential, TraceEvent
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


def _key_row(key: ApiKey, workspace_slug: str, project_slug: str | None) -> dict[str, object]:
    from forge.infra.security import mask_api_key
    from forge.services.api_keys import is_active

    now = utcnow()
    return {
        "id": str(key.id),
        "key": mask_api_key(key.prefix),
        "name": key.name,
        "workspace": workspace_slug,
        "project": project_slug,
        "role": key.role.value,
        "clearance": key.clearance,
        "scopes": list(key.scopes or []),
        "age_days": (now - key.created_at).days,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "status": "active" if is_active(key) else ("revoked" if key.revoked_at else "expired"),
    }


async def api_keys_list(workspace_ref: str | None, project_ref: str | None, as_json: bool) -> int:
    import json

    from forge.infra.models import Project, Workspace
    from forge.services import workspaces

    async with session_scope() as session:
        query = select(ApiKey, Workspace.slug, Project.slug).join(
            Workspace, Workspace.id == ApiKey.workspace_id
        )
        query = query.outerjoin(Project, Project.id == ApiKey.project_id)
        if workspace_ref:
            query = query.where(
                ApiKey.workspace_id == (await workspaces.get_workspace(session, workspace_ref)).id
            )
        if project_ref:
            query = query.where(Project.slug == project_ref)
        rows = [
            _key_row(key, ws, project)
            for key, ws, project in (
                await session.execute(query.order_by(Workspace.slug, ApiKey.created_at))
            ).all()
        ]
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(
                f"{row['key']}  {row['workspace']}/{row['project'] or '-'}  {row['role']} "
                f"C{row['clearance']}  "
                f"âge {row['age_days']} j  dernier usage {row['last_used_at'] or 'jamais'}  "
                f"expire {row['expires_at'] or '—'}  {row['status']}  « {row['name']} »"
            )
        print(f"{len(rows)} clé(s) (aucun secret affiché).")
    return 0


async def api_key_create(
    workspace_ref: str, project_ref: str | None, name: str, role: str, clearance: int, days: int | None
) -> int:
    from datetime import timedelta

    from forge.domain.enums import Role
    from forge.services import api_keys, workspaces
    from forge.services.audit import Actor
    from forge.services.taxonomy import PlatformError

    try:
        async with session_scope() as session:
            workspace = await workspaces.get_workspace(session, workspace_ref)
            bind_session(session, workspace.id)
            project = None
            if project_ref:
                project = next(
                    (p for p in await workspaces.list_projects(session, workspace) if p.slug == project_ref),
                    None,
                )
                if project is None:
                    print("Projet introuvable dans cet espace", file=sys.stderr)
                    return 2
            _key, full = await api_keys.create_api_key(
                session,
                Actor.system("forge.ops"),
                name=name,
                role=Role(role),
                clearance=clearance,
                expires_at=utcnow() + timedelta(days=days) if days else None,
                project_id=project.id if project else None,
                workspace_id=workspace.id,
            )
    except PlatformError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Clé créée ({workspace.slug}/{project.slug if project else '-'}, {role}, C{clearance}) : {full}")
    print("Elle ne sera plus jamais affichée : conservez-la dans votre gestionnaire de secrets.")
    return 0


async def project_move(project_ref: str, from_workspace: str, to_workspace: str) -> int:
    from forge.services import workspaces
    from forge.services.audit import Actor
    from forge.services.taxonomy import PlatformError

    try:
        async with session_scope() as session:
            source = await workspaces.get_workspace(session, from_workspace)
            target = await workspaces.get_workspace(session, to_workspace)
            project = next(
                (p for p in await workspaces.list_projects(session, source) if p.slug == project_ref), None
            )
            if project is None:
                print("Projet introuvable dans l'espace d'origine", file=sys.stderr)
                return 2
            revoked = await workspaces.move_project(session, Actor.system("forge.ops"), project, target)
    except PlatformError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Projet déplacé vers {target.slug} ; {revoked} clé(s) révoquée(s).")
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
    keys_cmd = sub.add_parser("api-keys", help="Lister les clés de service par espace / projet (sans secret)")
    keys_cmd.add_argument("--workspace")
    keys_cmd.add_argument("--project")
    keys_cmd.add_argument("--json", dest="as_json", action="store_true")
    key_create = sub.add_parser("api-key-create", help="Créer une clé rattachée à un espace (et un projet)")
    key_create.add_argument("--workspace", required=True)
    key_create.add_argument("--project")
    key_create.add_argument("--name", required=True)
    key_create.add_argument("--role", required=True, choices=[r.value for r in Role])
    key_create.add_argument("--clearance", required=True, type=int, choices=range(4))
    key_create.add_argument("--days", type=int, help="durée de vie (jours)")
    move = sub.add_parser(
        "project-move", help="Déplacer un projet vers un autre espace (ses clés sont révoquées)"
    )
    move.add_argument("--project", required=True)
    move.add_argument("--from", dest="from_workspace", required=True)
    move.add_argument("--to", dest="to_workspace", required=True)
    args = parser.parse_args(argv)

    async def run() -> int:
        try:
            if args.command == "rotate-secrets":
                return await rotate_secrets()
            if args.command == "check-secrets":
                return await check_secrets()
            if args.command == "retention":
                return await retention_pass(args.dry_run)
            if args.command == "api-keys":
                return await api_keys_list(args.workspace, args.project, args.as_json)
            if args.command == "api-key-create":
                return await api_key_create(
                    args.workspace, args.project, args.name, args.role, args.clearance, args.days
                )
            if args.command == "project-move":
                return await project_move(args.project, args.from_workspace, args.to_workspace)
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

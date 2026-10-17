# Outil de migration des comptes (ADR 001 §8)

Ticket NOV-113, côté FORGE. **Outil uniquement : aucune exécution en production dans ce ticket.** L'exécution en
production est une décision séparée de l'utilisateur (après la levée du gel et la validation en préproduction).
Tout se lance par `python -m forge.ops accounts …` (opération de plateforme : elle voit tous les espaces).

## Principes

* **Lecture seule par construction** : `inventory` et `reconcile` ouvrent une transaction `READ ONLY` toujours annulée.
* **Dry-run par défaut** : toute commande qui écrit exige `--apply`, et `--apply` exige `--confirm-backup <identifiant>`
  (≥ 8 caractères : faites et vérifiez une sauvegarde de la base avant). Sans cela : refus (code 2), rien n'est lu ni écrit.
* **Aucune liaison sans approbation signée** : `reconcile --apply` ne lie que les entrées d'un fichier d'approbation signé.
* **Aucune donnée sensible en clair par défaut** : adresses masquées (`a***@d***.com`) + empreinte SHA-256 de l'adresse
  normalisée ; `--reveal-emails` pour une sortie en clair (explicite). Fichiers de sortie en mode `0600`.
* Chaque liaison et chaque bascule est **auditée** (`auth.oidc_link` avec `migration: true`, `backup_id`, `approved_by` ;
  `account.flags_set`, `account.password_login_enabled`, `account.break_glass_*`, `account.unlinked`).

## 1. Inventaire (phase 0)

`accounts inventory [--format json|csv] [--section accounts|service_keys] [--out F] [--reveal-emails] [--expected-domain D]`
liste par compte : identifiant, e-mail masqué + empreinte, rôle, habilitation, actif, dernière connexion, espace, lié (et
émetteur), drapeaux, break-glass, problème d'e-mail (`invalid_format`, `unverifiable_domain` : `.local`, `.test`…,
`unexpected_domain` avec `--expected-domain`), groupe de doublons (même boîte à la casse et au `+tag` près) ; et les **clés de
service** (clé masquée, rôle, habilitation, espace / projet, dernier usage, expiration, révoquée) ; jamais un secret ni une empreinte de clé.

## 2. Rapprochement (dry-run)

`accounts reconcile --idp-export F --issuer URL [--expected-domain D] [--out proposal.json]` lit l'export de l'IdP (JSON ou
CSV `sub,email,email_verified[,workspace_id]`) et produit la table proposée `compte local ↔ sub`. Statuts : `proposed`,
`already_linked`, et les conflits `sub_missing`, `email_missing`, `invalid_format`, `unverifiable_domain`,
`unexpected_domain`, `email_unverified`, `sub_with_several_emails`, `email_shared_by_several_subs`, `no_local_account`,
`several_local_accounts` (doublons locaux), `inactive_account`, `sub_linked_to_another_account`,
`account_linked_to_another_sub`, `workspace_mismatch`. Seules les entrées `proposed` (sans aucun conflit) sont approuvables.

## 3. Approbation signée puis application

```bash
export FORGE_MIGRATION_APPROVAL_KEY=…   # ≥ 32 caractères, détenue par l'approbateur, jamais en ligne de commande
python -m forge.ops accounts approve --proposal proposal.json --all-proposed --backup-id <sauvegarde> \
    --approved-by prenom.nom --hours 24 --out approval.json         # ou --entry <entry_id> (répétable)
python -m forge.ops accounts reconcile --idp-export idp.json --issuer URL \
    --apply --approval approval.json --confirm-backup <sauvegarde>
```

Le fichier d'approbation porte : l'identifiant du rapprochement (`proposal_id`), l'émetteur, les `entry_id` approuvés, l'identifiant de
sauvegarde, l'approbateur, l'expiration, et une signature HMAC-SHA256. `--apply` refuse : signature invalide (fichier modifié,
autre clé), clé absente, approbation expirée, `--confirm-backup` différent de la sauvegarde approuvée, **rapprochement recalculé
différent** de celui qui a été approuvé (la base a changé), entrée approuvée devenue conflictuelle. L'application est **tout ou rien**
(une seule transaction) et ne lie que les entrées approuvées.

## 4. Drapeaux par compte et break-glass

Table additive `account_flags` (migration 0007). Sans ligne, rien ne change.

* `accounts flags --email E [--password-login-disabled true|false] [--sso-required true|false] [--apply --confirm-backup ID]` :
  refusé pour un compte **non lié** (il serait exclu) et pour le compte break-glass. `password_login_disabled` refuse la
  connexion par mot de passe ; `sso_required` la refuse aussi et met fin aux sessions locales non ouvertes par le SSO.
* **Break-glass** : `accounts break-glass set|unset|rotate --email E --confirm-offline-custody [--apply --confirm-backup ID]`.
  Administrateur actif uniquement ; il garde toujours le mot de passe (drapeaux sans effet, politique globale
  `FORGE_PASSWORD_LOGIN_DISABLED_FOR_LINKED` ignorée). `rotate` génère un mot de passe aléatoire de 32 caractères, affiché une seule
  fois (à ranger hors ligne), et met fin aux autres sessions ; aucun mot de passe n'entre dans l'audit. Les e-mails de
  `FORGE_BREAK_GLASS_EMAILS` et l'administrateur d'amorçage sont toujours break-glass.
* **Retour arrière en une commande** : `accounts enable-password --email E` (efface les deux drapeaux, sans confirmation) ;
  `accounts unlink --email E --apply --confirm-backup ID` retire la liaison SSO.

## Procédure de restauration

1. Avant tout `--apply` : sauvegarde complète de la base (`pg_dump -Fc`), vérifiée (`pg_restore --list`), et son identifiant noté.
2. Retour partiel : `accounts enable-password` (mot de passe), `accounts unlink` (liaison). Aucune donnée de compte n'est modifiée
   par l'outil (mot de passe, rôle, habilitation) hormis `break-glass rotate`.
3. Retour complet : restaurer les tables `external_identities` et `account_flags` (ou la base) depuis la sauvegarde identifiée ;
   `alembic downgrade 0006` supprime `account_flags` (migration réversible, rien d'autre ne change).

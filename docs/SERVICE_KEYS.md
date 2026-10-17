# Clés de service `fgk_…` et compte de service vers NOVA

Ticket NOV-112 côté FORGE (ADR 001 §7). Les clés `fgk_…` et le jeton entrant de NOVA restent valides ; elles sont
rattachées à un espace (et un projet), portent un rôle et une habilitation explicites, et se renouvellent. **Tout est
désactivé par défaut** : sans réglage, rien ne change.

## Rattachement

* Une clé appartient à un `workspace_id` (colonne posée par NOV-105 ; les clés existantes sont dans l'espace par défaut)
  et, en option, à un `project_id` de cet espace. L'espace d'une requête par clé est celui de la clé (jamais un en-tête).
* `POST /api/v1/api-keys` accepte `project_id` (un projet de l'espace de l'administrateur, sinon 404).
  `python -m forge.ops api-key-create --workspace W [--project P] --name N --role R --clearance C [--days D]` crée une
  clé pour un espace donné (la clé complète n'est affichée qu'une fois).
* **Un projet qui quitte son espace perd ses clés** : `python -m forge.ops project-move --project P --from A --to B`
  révoque les clés du projet (audit `api_key.revoke`) et refuse si le projet porte encore des ressources. En défense, une
  clé dont le projet n'est plus dans l'espace de la clé est refusée (401) à chaque appel.
* L'audit montre « Clé « nom » » (type `api_key`), jamais un utilisateur ; `created_by` n'est qu'une métadonnée.

## Politiques (désactivées par défaut)

| Variable | Défaut | Effet |
|---|---|---|
| `FORGE_API_KEY_REQUIRE_EXPLICIT` | `false` | la création exige `role` et `clearance` dans la requête (422 `explicit_fields_required`) |
| `FORGE_API_KEY_MAX_DAYS` | `0` (aucune limite) | une clé doit expirer dans ce délai (création et rotation) |

## Rotation

`POST /api/v1/api-keys/{id}/rotate` `{"grace_hours": 24}` (administrateur de l'espace) crée un **successeur identique**
(espace, projet, rôle, habilitation, portées, nom) et fait expirer l'ancienne clé après le délai de grâce (0 = révoquée
tout de suite). La nouvelle clé est affichée une fois ; l'audit (`api_key.rotate`) ne contient aucun secret. Procédure :
rotation → déployer la nouvelle clé chez l'appelant → vérifier `last_used_at` de l'ancienne → (elle expire seule).

## Outil d'administration (sans secret)

`python -m forge.ops api-keys [--workspace W] [--project P] [--json]` : id, clé masquée (`fgk_<préfixe>_••••`), nom, espace /
projet, rôle, habilitation, portées, âge, dernier usage, expiration, statut. Ni secret ni empreinte n'est affiché.

## FORGE → NOVA : compte de service

`FORGE_NOVA_SERVICE_AUTH=token|oidc|both` (défaut `token` : le jeton statique de l'identifiant `nova`, inchangé, comme
`NOVA_FORGE_INBOUND_AUTH=token` côté NOVA). `oidc` : FORGE obtient un jeton *client credentials*
(`FORGE_SERVICE_CLIENT_ID` = `forge-service`, `FORGE_SERVICE_CLIENT_SECRET`, `FORGE_SERVICE_TOKEN_ENDPOINT` ou le realm de
`FORGE_OIDC_ISSUER`, portées `FORGE_NOVA_SERVICE_SCOPE` = `orion-audience-nova orion:run.execute`), le garde en cache jusqu'à
30 s avant son expiration et l'envoie en `Authorization: Bearer`. Si le realm est injoignable, `oidc` échoue (erreur
réessayable, jamais de repli silencieux) ; `both` retombe sur le jeton statique (journalisé, sans secret). Hypothèse à confirmer
côté NOVA : nom de la portée d'audience (`orion-audience-nova`).

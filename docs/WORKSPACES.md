# Espaces et projets ORION (isolation multi-entreprises)

Ticket NOV-105, ADR 001 §5 et §9 (chantier « identité fédérée », NOV-102). Avant ce ticket FORGE n'avait
aucun modèle d'organisation : tout était visible de tous. Ce document décrit le modèle, le filtre
d'espace, sa bascule progressive et ses exceptions.

## Modèle

| Objet | Rôle |
|---|---|
| `workspaces` | l'**espace** (`orion_workspace_id` = `id`, immuable) : frontière d'isolation d'une entreprise |
| `projects` | le **projet** ORION (`orion_project_id` = `id`, unique globalement, rattaché à un espace ; alias lisible `slug` modifiable) |
| `workspace_members` | un utilisateur appartient à **un** espace (ADR §3 : plusieurs espaces = plusieurs comptes / sessions). Pas de ligne = espace par défaut |
| `project_members` | rôle optionnel par projet. Table créée ; **pas encore utilisée** pour les autorisations (voir limites) |

**Espace par défaut** : `ORION_DEFAULT_WORKSPACE_ID = 00000000-0000-4000-8000-000000000001` (alias `default`).
Constante fixe, jamais modifiée : c'est le `server_default` de toutes les colonnes `workspace_id`. La migration
0005 le crée et y rattache **toutes** les données existantes ainsi que tous les utilisateurs.

Colonnes `workspace_id uuid NOT NULL DEFAULT <espace par défaut>` (FK `RESTRICT`, immuable) sur : `agents`,
`agent_versions`, `model_configurations`, `prompt_versions`, `tool_configurations`, `scenarios`,
`scenario_versions`, `datasets`, `dataset_items`, `evaluation_runs`, `execution_traces`, `trace_events`,
`evaluations`, `scores`, `composite_scores`, `run_errors`, `feedback_reports`, `benchmarks`,
`benchmark_executions`, `experiments`, `judges`, `evaluation_configs`, `judge_cache`, `jobs`, `api_keys`,
`provider_credentials`, `audit_events`. `project_id` (nullable, `NULL` = ressource d'espace) en plus sur les
ressources principales : agents, scénarios, jeux de données, benchmarks, expériences, runs, juges,
configurations, clés, identifiants.

## D'où vient l'espace d'une requête

Uniquement de l'identité validée (`forge.api.deps`) : l'appartenance de l'utilisateur (`workspace_members`) ou
l'espace (et le projet) de la clé `fgk_…`. **Jamais** d'un paramètre, d'un corps ou d'un en-tête
(`X-Orion-Workspace` / `X-Orion-Project` sont ignorés). Il est attaché à la session de base de données
(`forge.infra.workspace_scope.bind_session`) ; le worker attache celle du job qu'il traite. Une session non
attachée (CLI, seed, démarrage, boucles de plateforme) est la portée *plateforme* : elle voit tout, comme avant.

## `FORGE_WORKSPACE_ENFORCEMENT`

| Valeur | Effet |
|---|---|
| `off` (défaut) | colonnes présentes et renseignées, **rien n'est filtré ni compté** : aucune réponse d'API ne change |
| `shadow` | toute ligne **lue** hors de l'espace de l'appelant est journalisée (`WARNING`) et comptée (`forge_workspace_violations_total{table,mode}`) ; la requête est servie comme avant |
| `enforce` | un critère `workspace_id = <espace>` est ajouté à **tout** SELECT / UPDATE / DELETE ORM d'une table d'espace (`with_loader_criteria`) : une ligne étrangère est absente. Un identifiant étranger répond `404` identique à un identifiant inconnu ; listes, recherches, exports et agrégats ne la contiennent jamais |

Garde-fou en `enforce` : une ligne étrangère qui atteindrait malgré tout la mémoire (trou de filtre) est comptée
et refusée (`WorkspaceViolation` → 404). Les nouvelles lignes reçoivent l'espace (et le projet d'une clé de
projet) de la session avant le flush, dans tous les modes ; `workspace_id` est immuable (`ValueError`).

Caches, files et limiteurs : la clé de cache des juges, la clé de déduplication des jobs, le sémaphore de
concurrence d'agent et le limiteur de débit des juges incluent l'espace pour tout espace **autre que** le
défaut (les clés de l'espace par défaut sont inchangées). Les lignes `judge_cache` et `jobs` portent l'espace.

### Bascule recommandée

1. Déployer la migration avec `off` (aucun changement de comportement).
2. Créer les espaces : `python -m forge.ops workspace-create --slug acme --name "ACME"` (refusé en `off` sans
   `--allow-off` : en `off` un second espace serait visible de tous), `project-create`, `workspace-add-user`.
   `workspace-create` crée aussi le juge hors ligne et la configuration par défaut de l'espace
   (`forge-heuristic-<alias>`, `forge-default-<alias>`).
3. Passer en `shadow`, surveiller `forge_workspace_violations_total` (alerte `ForgeWorkspaceViolations`) : elle
   doit rester à zéro pour le trafic normal.
4. Passer en `enforce`. Retour arrière : repasser à `off` (aucune donnée n'est modifiée par le filtre).

## Migration 0005 (additive, réversible)

* `ADD COLUMN … NOT NULL DEFAULT '<constante>'` : métadonnées seulement (PostgreSQL ≥ 11), pas de réécriture
  de table, quelle que soit sa taille. Mesuré : 2 000 000 lignes de `trace_events` (1,4 Go), migration complète
  en 7 s, sans réécriture.
* Clés étrangères ajoutées `NOT VALID` (sans scan) puis `VALIDATE CONSTRAINT` (n'empêche ni lectures ni écritures) ;
  index créés `CONCURRENTLY` ; chaque instruction en autocommit (un verrou `ACCESS EXCLUSIVE` ne dure que le temps
  d'une instruction, avec `lock_timeout = 10 s` : une table occupée fait échouer la migration plutôt que de
  bloquer les requêtes) ; chaque étape est idempotente (reprise après échec ou `alembic stamp 0004`).
* Index `(workspace_id, …)` sur les listes principales (agents, scénarios, jeux de données, benchmarks,
  expériences, runs, juges, configurations, journal d'audit, clés, identifiants) et index partiels sur `project_id`.
  Pas d'index sur les grosses tables enfants (événements, évaluations, scores) : elles sont toujours lues par run.
* `downgrade` supprime colonnes, index et tables ; l'affectation des lignes à un espace est perdue, pas leur contenu.
* Testé sur base peuplée (`tests/test_workspace_migration.py`) : comptages et empreintes de toutes les colonnes
  existantes identiques après montée, descente, remontée et reprise.

## Contrat testé

* `tests/test_workspace_isolation.py` : deux espaces, toutes les familles de ressources, `enforce` / `shadow` / `off`.
* `tests/test_workspace_inventory.py` : une nouvelle table ou route sans filtre déclaré fait échouer la CI.

### Tables sans `workspace_id` (`forge.infra.workspace_scope.EXEMPT_TABLES`)

`workspaces`, `projects`, `workspace_members`, `project_members` (registre d'espaces, géré par les opérateurs) ;
`users` (filtrée par appartenance : `services.users.scope_conditions`) ; `criteria` et `error_types` (catalogues
globaux partagés) ; `benchmark_scenarios`, `benchmark_agents`, `experiment_scenarios` (lignes d'association,
atteintes uniquement via leur parent filtré).

### Routes non attachées à un espace (`forge.api.deps.UNBOUND_ROUTES`)

`POST /auth/login` et `POST /auth/logout` (attachent l'espace de l'utilisateur dès qu'il est identifié),
`POST /webhooks/orbit` (webhook signé sans utilisateur : l'oubli d'un document vaut pour tous les espaces),
`/health`, `/ready`, `/metrics` (compteurs de plateforme agrégés). Les commandes `forge.ops` et le seed sont des
opérations de plateforme.

## Limites connues et suites

* **Unicité globale** : `slug` (agents, scénarios, jeux de données, benchmarks), `(key, version)` (juges,
  configurations), `name` (identifiants), e-mail des utilisateurs restent uniques sur toute la plateforme. Deux
  espaces ne peuvent pas porter le même alias (un 409 révèle donc l'existence) ; les clés de juge / configuration
  d'un nouvel espace portent son alias. Les rendre uniques par espace relâche un index unique (non réversible dès
  que des doublons existent) : suite dédiée.
* **Rôles par projet** : `project_members` et `project_id` sont posés mais le filtre et les autorisations restent
  par espace (rôles globaux), comme demandé tant qu'un utilisateur n'est que dans l'espace par défaut.
* **Administrateur** : en `enforce`, `admin` n'administre que son espace ; le rôle de plateforme distinct de l'ADR §9.4
  (audité, sans lecture de contenu) n'existe pas encore (les commandes `forge.ops` en tiennent lieu).
* `shadow` ne compte que les lignes chargées comme objets ORM ; une requête qui ne lit que des colonnes ou des
  agrégats n'est pas comptée (elle est bien filtrée en `enforce`).
* Les métriques Prometheus n'ont pas d'étiquette d'espace (cardinalité) ; `forge_workspace_violations_total`
  est étiquetée par table.
* L'espace d'un utilisateur ne vient pas encore d'un jeton OIDC (NOV-102, ticket FORGE OIDC) : il vient de
  `workspace_members`.

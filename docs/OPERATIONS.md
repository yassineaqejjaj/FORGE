# FORGE — Guide d'exploitation (production)

Ce guide complète [ARCHITECTURE.md](ARCHITECTURE.md) pour déployer et exploiter FORGE en
production. Les commandes `docker compose` s'appliquent telles quelles à un hôte unique ; sur
Kubernetes, chaque service compose correspond à un `Deployment` (mêmes images, mêmes variables).

## 1. Avant la mise en production

| Point | Action |
|---|---|
| Environnement | `FORGE_ENV=production` : le démarrage échoue si un secret de développement est encore utilisé. |
| Secrets | `FORGE_JWT_SECRET` et `FORGE_SECRETS_KEY` ≥ 32 caractères aléatoires (`openssl rand -base64 48`), stockés dans votre coffre (Vault/OpenBao, secrets Kubernetes), **jamais** dans le dépôt. |
| Administrateur initial | `FORGE_BOOTSTRAP_ADMIN_EMAIL` / `FORGE_BOOTSTRAP_ADMIN_PASSWORD` (créé uniquement si la base est vide) ; changez le mot de passe à la première connexion. |
| TLS | Exposer **uniquement** le service `web` derrière un reverse proxy TLS (Traefik, nginx, ingress). `FORGE_COOKIE_SECURE=true`. L'API n'a pas besoin d'être publique : le web la proxifie. Seul `POST /v1/traces` peut être exposé aux agents (clé `traces:write`). |
| Base de données | PostgreSQL 17 managé ou dédié, sauvegardes activées (§4), `FORGE_DATABASE_URL` avec un utilisateur propriétaire du schéma. |
| Valkey | Optionnel mais recommandé (limites de concurrence et de débit distribuées). Sans Valkey, les limites deviennent locales à chaque worker. |
| Fournisseurs LLM | Créer les identifiants dans *Paramètres → Identifiants* (chiffrés) ou via `FORGE_OPENAI_API_KEY` / `FORGE_ANTHROPIC_API_KEY` au premier démarrage. Configurer au moins un juge LLM : le juge heuristique n'est qu'un outil de démonstration. |
| Données | Ne chargez pas la démonstration (`make seed`) en production. Respectez la classification C0–C3 des scénarios ; un bandeau signale les contenus C2/C3. |

## 2. Dimensionnement

* `api` : sans état, 2 réplicas minimum derrière le proxy ; migrations exécutées au démarrage
  (verrou Alembic : les réplicas peuvent démarrer simultanément).
* `runner-worker` (file `execution`) : appels aux agents, limité par la latence des agents.
  Montez `FORGE_WORKER_CONCURRENCY` et/ou le nombre de réplicas ; la concurrence par version
  d'agent reste bornée par `max_concurrency` (ou `FORGE_RUNNER_DEFAULT_CONCURRENCY`) via Valkey.
* `evaluation-worker` (file `evaluation`) : juges LLM ; borné par
  `FORGE_PROVIDER_RATE_LIMIT_PER_MINUTE` par identifiant fournisseur.
* Indicateur d'autoscaling : profondeur de file (`GET /ready` → `checks.postgres.info.queue_depth`)
  ou métrique `forge_worker_inflight_jobs`.
* Ordre de grandeur : un benchmark de 1 200 runs (100 scénarios × 4 agents × 3 répétitions)
  s'agrège en quelques secondes ; la durée totale dépend des agents et des juges.

## 3. Observabilité

* Santé : `GET /health` (vivant), `GET /ready` (Postgres requis, Valkey informatif, profondeur des
  files). Le web expose `GET /healthz`.
* Métriques Prometheus : `api:8000/metrics`, workers `:9464/metrics`.
  Alertes suggérées :
  * `rate(forge_runs_total{status="failed"}[15m]) / rate(forge_runs_total[15m]) > 0.2` ;
  * file `execution` ou `evaluation` > 500 jobs pendant 30 min ;
  * `rate(forge_judge_calls_total{outcome!="ok"}[15m]) > 0.1` (fournisseur LLM dégradé) ;
  * `forge_otlp_spans_total{outcome="orphan"}` en hausse (agents mal corrélés).
* Traces de FORGE lui-même : `FORGE_OTLP_ENDPOINT` (collecteur OTel, Tempo, Jaeger…).
* Journaux : une ligne par événement avec `rid=<request id>` (en-tête `X-Request-ID`).
* Audit fonctionnel : *Paramètres → Audit* ou `GET /api/v1/audit`.

## 4. Sauvegarde et restauration

Toutes les données (référentiel, traces, évaluations, file de jobs) sont dans PostgreSQL.

```bash
docker compose exec -T postgres pg_dump -U forge -d forge -Fc > forge-$(date +%F).dump
```

```bash
docker compose exec -T postgres pg_restore -U forge -d forge --clean --if-exists < forge-2026-10-01.dump
```

Sauvegardez **aussi** `FORGE_SECRETS_KEY` : sans elle, les identifiants fournisseurs restaurés sont
illisibles (`python -m forge.ops check-secrets` le vérifie).

## 5. Mises à jour

1. Sauvegarder la base.
2. Construire et pousser les nouvelles images (`backend`, `frontend` ; la CI GitHub Actions
   `.github/workflows/ci.yml` vérifie lint, typage, contrats d'architecture, tests et build).
3. Redéployer `api` (applique `alembic upgrade head`), puis les workers, puis `web`.
4. Les workers terminent leurs jobs en cours à l'arrêt (`FORGE_WORKER_SHUTDOWN_GRACE_SECONDS`) ;
   un job interrompu est remis en file automatiquement.

Les runs existants ne sont jamais modifiés par une mise à jour : ils sont rejoués à partir de leur
manifeste figé.

## 6. Commandes d'exploitation

```bash
docker compose exec -T api python -m forge.ops check-secrets
```

Rotation de la clé de chiffrement des secrets :

1. définir la nouvelle `FORGE_SECRETS_KEY` et l'ancienne dans `FORGE_SECRETS_KEY_OLD` ;
2. exécuter `python -m forge.ops rotate-secrets` (idempotent) ;
3. redémarrer API et workers, puis retirer `FORGE_SECRETS_KEY_OLD`.

```bash
docker compose exec -T -e FORGE_SECRETS_KEY_OLD="$OLD_KEY" api python -m forge.ops rotate-secrets
```

Rétention : supprimer les payloads de trace (entrées/sorties des étapes) des runs terminés depuis
plus de N jours, en conservant timeline, scores, justifications et erreurs :

```bash
docker compose exec -T api python -m forge.ops purge-payloads --older-than-days 180
```

Rotation du secret JWT (`FORGE_JWT_SECRET`) : redémarrer l'API ; toutes les sessions sont
invalidées (les clés d'API `fgk_…` ne sont pas affectées).

## 7. Sécurité — rappels

* Rôles minimaux : donner `editor` aux équipes produit, `maintainer` aux responsables des
  benchmarks (contenu des scénarios privés, juges, configurations), `admin` à l'exploitation.
* Accueil des nouveaux comptes : les comptes sont créés par un administrateur (Paramètres →
  Utilisateurs). À sa première connexion, chaque compte voit une visite guidée (rôle, boucle
  Concevoir → Tester → Analyser → Améliorer, premiers pas selon le rôle) ; `users.onboarded_at`
  mémorise sa fin ou son abandon (`POST /api/v1/auth/onboarding/complete`, idempotent). Elle se
  rouvre depuis le menu de l'avatar (« Visite guidée »). Les comptes antérieurs à la migration
  `0003` sont considérés comme déjà accueillis.
* Clés d'API : une par usage (CI, NOVA, agents), avec expiration ; les agents ne reçoivent que
  des clés `traces:write`.
* Les agents évalués ne voient jamais le résultat attendu, les critères ni les règles des
  scénarios ; les scénarios privés ne sont visibles en clair que des mainteneurs.
* Les canaris `FORGE-CANARY-…` détectent la contamination des agents (règle `no_canary`,
  contrôle à la création des versions d'agents).

### Politique de promotion (`FORGE_PROMOTION_POLICY`)

Aucune amélioration n'est promue sur la foi d'une mesure non validée. `strict` (**défaut**) bloque,
`warn` signale les mêmes constats sans rien bloquer (audit, avertissements de la comparaison, raisons
de la garde CI). Trois contrôles (`services/promotion.py`) :

* **Juges calibrés** : chaque juge de la configuration d'évaluation doit être calibré contre les scores
  humains des jeux `gold` (n ≥ 10, κ pondéré ≥ `FORGE_CALIBRATION_MIN_KAPPA`, défaut 0,6, accord ≥ 0,7).
* **Pas de contamination** : aucune version d'agent comparée ne porte d'alerte de contamination
  (canaris, sorties attendues privées). La création d'une version l'enregistre toujours ; c'est la
  création d'expérience, la garde CI et la publication qui la refusent.
* **Cas de régression rejoués** : les scénarios promus depuis des runs en échec de l'agent
  (`promote-to-scenario`) doivent faire partie de l'expérience.

Effets en `strict` : `POST /experiments` est refusé (422) ; `GET /experiments/{id}/gate` ne passe que sur
`ship` (le paramètre `strict` ne peut pas l'assouplir) et échoue sur ces constats ; la publication d'un
apprentissage vers ORBIT exige que la garde passe. En `warn`, le comportement historique est conservé
(`inconclusive` passe la garde par défaut). Les jeux de démonstration (`forge.seed`) s'exécutent en `warn`.

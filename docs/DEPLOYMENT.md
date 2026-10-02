# FORGE — Déploiement GitHub · Railway · Vercel

FORGE en ligne :

| Composant | Hébergement | URL |
|---|---|---|
| Interface (Next.js) | Vercel, projet `forge` (racine `frontend/`) | <https://forge-pied-rho.vercel.app> |
| API + OTLP | Railway, projet `forge`, service `api` | <https://api-production-b165a.up.railway.app> |
| Workers, agents de démo, PostgreSQL, Redis | Railway, réseau privé | — |
| Code | GitHub `yassineaqejjaj/FORGE` (privé) | <https://github.com/yassineaqejjaj/FORGE> |

Chaque `git push` sur `main` déclenche : la CI GitHub Actions (`.github/workflows/ci.yml`), le
redéploiement des 4 services Railway (reliés au dépôt) et le déploiement de production Vercel.

## Railway

Projet `forge`, environnement `production` :

| Service | Source | Variables propres |
|---|---|---|
| `Postgres` | modèle Railway | — |
| `Redis` | modèle Railway | — |
| `api` | dépôt GitHub, racine `backend/`, `backend/railway.toml` (Dockerfile) | `FORGE_ROLE=api`, `PORT=8000`, `FORGE_BIND_HOST=0.0.0.0`, `FORGE_PUBLIC_BASE_URL`, `FORGE_COOKIE_SECURE=true` ; contrôle de santé `/ready` |
| `runner-worker` | idem | `FORGE_ROLE=worker`, `FORGE_WORKER_QUEUES=execution`, `FORGE_WORKER_CONCURRENCY=8` |
| `evaluation-worker` | idem | `FORGE_ROLE=worker`, `FORGE_WORKER_QUEUES=evaluation`, `FORGE_WORKER_CONCURRENCY=4` |
| `demo-agents` | idem | `FORGE_ROLE=demo-agents`, `FORGE_BIND_HOST=::`, `FORGE_DEMO_AGENTS_PORT=8190` |

Variables communes aux services backend : `FORGE_ENV=production`,
`FORGE_DATABASE_URL=${{Postgres.DATABASE_URL}}` (converti automatiquement en
`postgresql+asyncpg://`), `FORGE_VALKEY_URL=${{Redis.REDIS_URL}}`, `FORGE_JWT_SECRET`,
`FORGE_SECRETS_KEY`, `FORGE_BOOTSTRAP_ADMIN_PASSWORD` (secrets aléatoires, identiques sur tous les
services), `FORGE_DEMO_AGENTS_URL=http://demo-agents.railway.internal:8190`.

Notes :

* Le réseau privé Railway passe par IPv6 : `demo-agents` écoute sur `::` ; l'API écoute sur
  `0.0.0.0` car le contrôle de santé et le domaine public arrivent en IPv4.
* Le Dockerfile n'utilise pas de cache BuildKit (`--mount=type=cache`) : Railway impose un format
  d'identifiant de cache incompatible.
* Les migrations Alembic s'exécutent au démarrage de `api` (verrou consultatif Postgres).
* Pour ajouter des juges LLM : `FORGE_OPENAI_API_KEY` / `FORGE_ANTHROPIC_API_KEY` sur `api`
  (identifiants chiffrés créés au démarrage), ou *Paramètres → Identifiants* dans l'interface.

Commandes utiles (projet lié avec `railway link`) :

```bash
railway service status --all
```

```bash
railway logs --service api
```

```bash
railway ssh --service api -- python -m forge.ops check-secrets
```

Jeu de démonstration (déjà chargé ; mots de passe aléatoires en production) :

```bash
railway ssh --service api -- python -m forge.seed
```

## Vercel

Projet `forge`, racine `frontend/`, framework Next.js, Node 22. Variable
`FORGE_API_URL=https://api-production-b165a.up.railway.app` (production, preview, development) :
elle est lue **au build** par les réécritures de `next.config.ts` (`/api/*` et `/v1/traces` →
API Railway). Le navigateur ne parle qu'au domaine Vercel ; le cookie de session `forge_session`
(httpOnly, Secure) est posé sur ce domaine.

Changer l'URL de l'API impose un redéploiement Vercel :

```bash
npx vercel deploy --prod
```

## Identifiants

Les mots de passe de l'administrateur et des comptes de démonstration, ainsi que les clés d'API de
démonstration, sont générés aléatoirement et ne sont **pas** dans le dépôt. Changez le mot de passe
administrateur à la première connexion.

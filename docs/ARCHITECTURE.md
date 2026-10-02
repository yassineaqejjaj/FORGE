# FORGE — Architecture de référence (contrat d'implémentation)

> Ce document est **la source de vérité** pour tous les contributeurs. Toute divergence entre le
> code et ce document est un bug, sauf si ce document est mis à jour dans le même changement.

FORGE est le **laboratoire d'évaluation** des agents IA de la constellation NOVA (création et
orchestration des agents), ORBIT (contexte, mémoire), FORGE (évaluation, amélioration) et LEAP
(formation). Il répond à une question : *« cette nouvelle version de mon agent est-elle
réellement meilleure ? »* — sur quels scénarios, quels critères, à quel coût, avec quelles
erreurs, quelles régressions et quel niveau de confiance.

Principes non négociables : **provider / agent / evaluation agnostic**, **trace first**,
**version everything**, **explain every score** (aucun score sans explication), **compare
everything** (toute expérience a une baseline), **human calibration**, **private evaluation**.

---

## 1. Déploiement & configuration

`docker compose up -d --build` démarre la plateforme :

| Service | Rôle | Port hôte |
|---|---|---|
| `postgres` (17) | Source de vérité + file de jobs | 5434 |
| `valkey` (8) | Limites de concurrence et de débit distribuées (optionnel : dégradation locale) | 6381 |
| `api` | FastAPI : REST `/api/v1`, OTLP `/v1/traces`, `/metrics`, `/health`, `/ready` | 8100 |
| `runner-worker` | File `execution` : appels aux agents (scalable) | — |
| `evaluation-worker` | File `evaluation` : règles, juges, scores, agrégations | — |
| `demo-agents` | Agents de démonstration parlant le FORGE Agent Protocol | 8190 |
| `web` | Next.js (UI), proxy same-origin `/api/*` → `api:8000` | 3100 |

Les migrations Alembic sont exécutées au démarrage de `api` ; les données de référence
(critères, taxonomie, juge heuristique, juges LLM si clés fournies, configurations
`forge-default` / `product-agent`) sont créées de façon idempotente (`forge.services.bootstrap`).

Configuration : variables `FORGE_*` déclarées dans `forge/config.py` (valeurs par défaut) et
documentées dans `.env.example`. En `FORGE_ENV=production`, les secrets de développement
(`FORGE_JWT_SECRET`, `FORGE_SECRETS_KEY`, mot de passe admin) sont refusés au démarrage.

---

## 2. Organisation du code

```
forge/
  docker-compose.yml  Makefile  .env.example  README.md  docs/
  backend/            (Python 3.12, uv)
    forge/
      config.py
      domain/         PUR : aucun import de framework, base de données ou réseau (import-linter)
        enums.py types.py ports.py serialization.py hashing.py versioning.py defaults.py
        taxonomy.py judge_defaults.py redaction.py
        traces/       recorder (TraceRecorder), mapping OTLP → événements, timeline
        rules/        moteur de règles déterministes, détection PII
        judges/       rendu des prompts, parsing, agrégation multi-juges, juge heuristique, expressions sûres
        scoring/      normalisation, scores par critère, dimensions, composite, garde-fous
        feedback/     construction du FeedbackReport
        stats/        bootstrap, Wilcoxon, corrélations, kappa pondéré
        benchmarks/   agrégations, robustesse, écart de généralisation
        experiments/  comparaison appariée, verdicts, régressions, recommandation
        calibration/  accord IA / humain
        scenarios/    validation, import/export, contamination
      infra/          db, models/, queue, cache (Valkey), security, observability/, llm/
      adapters/       AgentAdapter : openai, anthropic, nova, custom_api, mock + registry
      services/       cas d'usage (orchestration domaine + infra), un module par sujet
      api/            FastAPI : main, deps, errors, schemas/, routers/
      workers/        worker générique (files execution / evaluation), registre des handlers
      cli/            CLI `forge` (CI : lancer une expérience, bloquer sur régression)
      demo_agents/    service d'agents de démonstration
      seed/           données de démonstration
    tests/            unit/ (pur) + intégration (Postgres/Valkey de `make infra`)
  frontend/           Next.js 15 (App Router) + TypeScript strict + Tailwind v4 + Radix + TanStack Query
```

Correspondance avec la structure logique du cahier des charges : `packages/core` →
`forge.domain`, `agents` → `forge.adapters` + `services/agents.py`, `scenarios` →
`domain/scenarios` + `services/scenarios.py`, `runner` → `services/execution.py`,
`traces` → `domain/traces`, `evaluators` → `domain/rules`, `judges` → `domain/judges`,
`scoring` → `domain/scoring`, `feedback` → `domain/feedback`, `experiments`/`benchmarks` →
`domain/…` + `services/…`, `workers/runner-worker` et `evaluation-worker` → `forge.workers`
avec `FORGE_WORKER_QUEUES`.

### 2.1 Couches (vérifiées par `lint-imports`)

`api | workers | cli | seed | demo_agents` → `services` → `adapters` → `infra` → `domain`.
Une couche n'importe jamais une couche supérieure. `forge.domain` n'importe ni `sqlalchemy`,
ni `fastapi`, ni `httpx`, ni `redis`, ni `forge.config`.

### 2.2 Règles communes

* Textes destinés aux utilisateurs **en français** ; code, identifiants, logs en anglais.
* Toute mutation écrit une entrée d'audit (`forge.services.audit.record`) dans la même transaction.
* Transactions explicites : les services font `flush`, les routers et handlers `commit`.
* Pas de logique métier dans les routers ni dans l'UI.
* Ne jamais logger un secret ni un contenu de scénario privé.
* Données de démonstration : aucun contenu lié à la santé, aux plateformes d'échange de
  crypto-actifs, aux contenus adultes ou piratés (politique de l'organisation).

### 2.3 Propriété des modules

| Propriétaire | Fichiers |
|---|---|
| **execution** | `adapters/**`, `domain/traces/**`, `services/{execution,context_providers,trace_ingest}.py`, `api/routers/traces.py`, `api/schemas/traces.py`, `demo_agents/**`, `docs/AGENT_PROTOCOL.md` |
| **evaluation** | `domain/{rules,judges,scoring,feedback}/**`, `infra/llm/**`, `services/{evaluation,judges,evaluation_configs,feedback}.py`, `api/routers/{evaluations,judges,evaluation_configs}.py` + schémas |
| **analytics** | `domain/{stats,benchmarks,experiments,calibration}/**`, `services/{benchmarks,experiments,calibration,analytics,run_summaries}.py`, `api/routers/{benchmarks,experiments,calibration,analytics}.py` + schémas, `cli/**`, `docs/CI.md` |
| **platform** | `domain/scenarios/**`, `services/{agents,scenarios,datasets,taxonomy,api_keys,run_queries,reviews}.py`, `api/routers/{auth,users,api_keys,credentials,meta,agents,scenarios,datasets,taxonomy,runs,reviews,audit}.py` + schémas |
| **fondation** (intégrateur) | tout le reste : `config.py`, `domain/{enums,types,ports,serialization,hashing,versioning,defaults,taxonomy,judge_defaults,redaction}.py`, `infra/{db,models,queue,cache,security,observability}`, `services/{runs,mapping,bootstrap,audit,users,credentials,access}.py`, `api/{main,deps,errors}.py`, `api/schemas/common.py`, `workers/**`, `alembic/**` |

Un propriétaire qui a besoin d'une modification d'un fichier de fondation (nouvel enum, nouveau
réglage, nouvelle colonne) la **signale** dans son rapport au lieu de la faire, sauf ajout
purement additif dans `config.py` (nouveau champ avec valeur par défaut).

---

## 3. Sécurité & accès

### 3.1 Identités

* **Utilisateurs** : e-mail + mot de passe (argon2id). Session = JWT HS256 dans le cookie
  httpOnly `forge_session` (SameSite=Lax) ou `Authorization: Bearer <jwt>`. Changer de mot de
  passe révoque les sessions (empreinte du hash dans le JWT). Login limité à
  `FORGE_LOGIN_RATE_LIMIT_PER_MINUTE` tentatives / minute / e-mail+IP.
* **Clés d'API** `fgk_<prefix8>_<secret32>` (seul le SHA-256 est stocké, clé montrée une seule
  fois) : `Authorization: Bearer fgk_…` ou `X-Forge-Key`. Une clé porte un rôle, une
  habilitation, une expiration optionnelle et des *scopes* : une clé avec
  `scopes=["traces:write"]` ne peut **que** pousser des traces (clé à donner aux agents).
* **Identifiants fournisseurs** (`provider_credentials`) : clés LLM, jetons NOVA/ORBIT, en-têtes,
  chiffrés (Fernet dérivé de `FORGE_SECRETS_KEY`), jamais renvoyés (seul `secret_hint`
  `••••abcd`). Déchiffrés uniquement dans les workers au moment de l'appel.

### 3.2 Rôles (plateforme)

`viewer` ⊂ `evaluator` ⊂ `editor` ⊂ `maintainer` ⊂ `admin` :

| Rôle | Droits |
|---|---|
| viewer | lecture de tout, sauf le contenu masqué des scénarios privés |
| evaluator | + évaluations humaines |
| editor | + agents, versions, scénarios publics/fresh, runs, benchmarks, expériences, datasets |
| maintainer | + contenu et création des scénarios **privés**, juges, configurations de score, taxonomie, critères |
| admin | + utilisateurs, clés d'API, identifiants fournisseurs |

### 3.3 Évaluation privée (scénarios cachés)

Pour un scénario `private`, un appelant non-maintainer voit **les résultats** (scores, types
d'erreurs, gravités, coûts, latences, statut) mais **pas** : le contenu du scénario (`input`,
`context`, `constraints`, `expected_output`, `expected_behavior`, `tool_mocks`, `description`),
les règles, l'entrée/sortie de l'agent, les payloads de trace, les justifications des juges,
les preuves, le manifeste complet. Les règles `hidden: true` sont masquées sur tout scénario.
Implémentation unique : `forge.domain.redaction` + `forge.services.access.must_redact`.
Le **canari** d'une version de scénario n'est visible que des maintainers.

Les agents ne reçoivent jamais que `ScenarioSpec.agent_view()` (entrée, contexte, contraintes)
et le contexte préparé : jamais le résultat attendu, les critères, les règles ni les mocks.

### 3.4 Classification

Chaque scénario porte une classification C0 (Public) → C3 (Secret) (même politique qu'ORBIT).
Un scénario (et ses runs) au-dessus de l'habilitation de l'appelant **n'est pas révélé** (404,
absent des listes : `access.classification_condition`). L'UI affiche un bandeau
d'avertissement dès qu'un contenu C2/C3 est affiché.

---

## 4. Énumérations

Toutes dans `forge/domain/enums.py` (jamais redéfinies), stockées en `text` + `CHECK`, valeurs
identiques dans `frontend/src/lib/enums.ts`. Principales : `Role`, `AdapterKind`,
`ProviderKind`, `ContextSource`, `ScenarioVisibility` (public/private/fresh), `Difficulty`,
`RunStatus` (pending/running/evaluating/completed/failed/cancelled), `RunOrigin`,
`ExperimentArm`, `TraceEventType`, `TraceEventSource`, `Dimension` (quality, coherence,
reasoning, safety, robustness, cost, latency, ux), `EvaluatorKind`, `ScoreSource`, `RuleType`,
`JudgeProvider`, `AggregationMethod`, `ErrorSeverity`, `BuiltinErrorType`, `GateAction`,
`RecommendationCategory`, `Priority`, `FeedbackScope`, `ExecutionStatus`, `Verdict`,
`RegressionSeverity`, `Recommendation`, `CalibrationStatus`, `JobKind`, `JobQueue`, `JobStatus`.

---

## 5. Domaine

### 5.1 Types (`forge/domain/types.py`)

`ModelSpec`, `ToolSpec`, `ToolMock`, `AgentBudget`, `AgentSpec`, `CriterionSpec`, `RuleSpec`,
`ScenarioSpec`, `TokenUsage`, `TraceEventData`, `AgentRequest`, `AgentResult`,
`AgentExecutionError`, `TraceEventView`, `EvidenceRef`, `DetectedError`, `EvaluationResult`,
`JudgeSpec`, `GateSpec`, `AggregationSpec`, `NormalizationSpec`, `ScoreConfig`,
`EvaluationContext`, `CriterionScore`, `DimensionScore`, `GateResult`, `CompositeResult`,
`FeedbackRecommendation`, `FeedbackReportData`, `RunSummary`, `ScorePair`.
(Dé)sérialisation typée : `forge.domain.serialization.from_dict` / `types.to_dict`.

### 5.2 Ports (`forge/domain/ports.py`)

* `AgentAdapter.invoke(request, recorder) -> AgentResult` — un adapter par `AdapterKind`,
  enregistré dans `forge.adapters.registry.get_adapter(kind)`.
* `TraceRecorder` — `event()`, `span()` (context manager), `add_usage()`, `count_tool_call()`.
* `Evaluator.evaluate(ctx) -> list[EvaluationResult]` — règles, métriques, juges.
* `LLMClient.complete(...) -> LLMResponse` — OpenAI-compatible, Anthropic ; utilisé par les juges
  et le générateur de feedback (`forge.infra.llm.get_client(provider, credentials, base_url)`).

---

## 6. Versionnement & reproductibilité

### 6.1 Tout est versionné et immuable

`AgentVersion`, `PromptVersion`, `ModelConfiguration`, `ToolConfiguration`, `ScenarioVersion`,
`Judge` (clé + version), `EvaluationConfig` (clé + version) ne sont **jamais modifiés** : une
modification crée une nouvelle version. Chaque version porte un `content_hash` calculé par
`forge.domain.versioning` sur les seuls champs qui définissent son comportement. Créer une
version identique à la dernière → `409 conflict`. Les métadonnées non comportementales (nom,
description, tags, archivage, visibilité, classification d'un scénario) restent modifiables
sur l'entité parente.

Chaque `ScenarioVersion` reçoit un canari unique `FORGE-CANARY-<hex>`.

### 6.2 Manifeste de run

À la création (`forge.services.runs.create_runs`), chaque `EvaluationRun` fige dans
`manifest` (JSONB, schéma `forge.run-manifest/v1`) : le scénario complet (`ScenarioSpec`), l'agent
(`AgentSpec` sans secrets : modèle, version de modèle, température, prompt et sa version,
outils, contexte, mémoire, orchestration, adapter, budget), la configuration d'évaluation
(`ScoreConfig` : pondérations, garde-fous, juges épinglés avec prompts et modèles), la
répétition, l'origine, la date et la version de FORGE. `manifest_hash` couvre les seules
conditions expérimentales (scénario + agent + configuration) : les répétitions le partagent.

**L'exécution et l'évaluation lisent exclusivement le manifeste** (`mapping.specs_from_manifest`),
jamais les lignes vivantes. Les secrets sont réinjectés au moment de l'appel depuis
`credential_id`.

---

## 7. Moteur d'évaluation

### 7.1 Pipeline (`evaluate_run_job`, file `evaluation`)

1. Charger le run, sa trace, ses événements (`TraceEventView`, `seq` stable), le manifeste.
2. `round = run.evaluation_round + 1`.
3. **Règles** du scénario + règles globales de la configuration (déterministes, gratuites).
4. **Métriques** : `cost.estimated_cost`, `cost.tokens`, `latency.total` normalisés (§7.5).
5. **Juges** de la configuration, en parallèle (limités par `throttle` par identifiant), avec
   cache (§7.3). Critères jugés : ceux du scénario, sinon `DEFAULT_JUDGED_CRITERIA`, plus ceux de
   la configuration, filtrés par `JudgeSpec.criteria` si non vide. Les critères des dimensions
   `cost`/`latency`/`robustness` ne sont jamais soumis aux juges.
6. Persister chaque verdict (`evaluations`, une ligne par évaluateur × critère).
7. **Agrégation** par critère (§7.4) → `scores` (source `ai`, `rule`, `metric` ; `human` si des
   évaluations humaines existent).
8. **Composite** (§7.5) → `composite_scores` + dénormalisation `run.composite_score`,
   `run.passed`, `run.gate_failed`.
9. **Erreurs** classées (§7.6) → `run_errors` (lien `trace_event_id` résolu depuis `seq`).
10. **FeedbackReport** du run (§7.7).
11. Audit `run.evaluate` (juges, versions, hashes de prompts, composite), statut `completed`
    via `runs.mark_completed` (qui déclenche la finalisation benchmark/expérience).

Si l'exécution a échoué (`run.error`), on évalue quand même ce qui est évaluable (règles sur
sortie vide, métriques), on enregistre l'erreur d'exécution (`EXECUTION_ERROR`, `TIMEOUT`,
`BUDGET_EXCEEDED`, `round=NULL`) et le run se termine `failed` avec composite 0.

Ré-évaluation (`POST /runs/{id}/evaluate`, éventuellement avec une autre configuration) :
nouveau round ; les rounds précédents restent consultables. Les évaluations humaines
(`round NULL`) s'appliquent à tous les rounds. `rescore_run(session, run, config=None)`
recalcule scores + composite du round courant **sans appel aux juges** (utilisé après une
évaluation humaine et pour l'aperçu d'une configuration).

### 7.2 Règles (`forge.domain.rules`)

Chaque `RuleSpec` produit **un** `EvaluationResult` (`evaluator_kind=rule`, `evaluator_key=<rule id>`,
score 0–1, `passed`, explication factuelle, preuves) et, en cas d'échec, une `DetectedError`
(type = `rule.error_type` ou défaut `RULE_DEFAULTS`, gravité = `rule.severity`). Critère par
défaut : `RULE_DEFAULTS[type][0]`.

| Type | `params` | Réussite |
|---|---|---|
| `required_fields` | `fields: [json path "a.b[0].c"]` | tous présents dans `output_json` (ou JSON extrait de la sortie) ; score = part présente |
| `json_valid` | — | sortie (ou bloc ```json```) parsable |
| `json_schema` | `schema` | valide (erreurs listées) |
| `regex_match` / `regex_absent` | `pattern`, `flags` (`i`,`m`,`s`) | trouvé / absent |
| `contains` / `not_contains` | `keywords: []`, `mode: all|any`, `case_sensitive` | score = part trouvée (`contains`) |
| `sections_present` | `sections: []` | titres Markdown présents (insensible casse/accents) |
| `citation_required` | `min: 1`, `pattern?` | ≥ min citations `[1]`, `[source: …]`, `[doc-id]` |
| `source_present` | `min: 1` | cite au moins `min` id/titres des documents du contexte |
| `no_pii` | `types?: [PiiType]`, `allow?: []` | aucune donnée personnelle (détecteur ORBIT : e-mail, téléphone, IBAN, carte, NIR, IP, personne) |
| `expected_value` | `path`, `value` | égalité (JSON) |
| `max_length` / `min_length` | `words?`, `chars?` | respecté |
| `tool_called` / `tool_not_called` | `tool`, `min?` | selon événements `tool_call` |
| `max_tool_calls` | `max` | nombre d'appels d'outils ≤ max |
| `max_latency` | `ms` | latence totale ≤ ms |
| `max_cost` | `max` | coût estimé ≤ max |
| `no_canary` | — | la sortie ne contient aucun canari `FORGE-CANARY-…` (erreur `CONTAMINATION` critique) |

Les preuves référencent la sortie (`location="output"`, extrait) ou un événement (`trace_event_seq`).

### 7.3 Juges LLM (`forge.domain.judges`, `forge.infra.llm`)

* **Prompt** : `JudgeSpec.system_prompt` + `rubric_template` rendu avec les placeholders de
  `forge.domain.judge_defaults` ; la trace est compactée (une ligne par événement :
  `[E<seq>] +<offset>ms <type> <name> — <résumé>`, payloads tronqués, total borné).
  `prompt_hash = sha256(system + prompt rendu)` est stocké sur chaque évaluation.
* **Sortie** : JSON conforme à `JUDGE_OUTPUT_SCHEMA` (structured outputs si le fournisseur les
  supporte, sinon JSON demandé + parsing tolérant). Par critère : `score` (échelle du critère,
  borné), `justification` (non vide), `confidence` 0–1, `evidence[]` (`excerpt`, `event` → `seq`),
  `errors[]` (type de taxonomie — un type inconnu devient `BAD_REASONING` avec le type d'origine dans
  la description —, gravité, description, preuve).
* **Robustesse** : réponse invalide → 1 nouvel essai avec message de correction ; erreurs HTTP
  429/5xx → retries avec backoff (`FORGE_JUDGE_MAX_RETRIES`) ; critère manquant dans la réponse →
  pas de verdict pour ce juge sur ce critère (jamais de score inventé) ; juge en échec complet →
  les autres juges suffisent, sinon le run est évalué sans ce critère (dimension renormalisée) et
  un avertissement est tracé dans `status_detail` + audit.
* **Cache** (`judge_cache`) : clé `sha256(judge.content_hash, scenario.content_hash, sortie, digest de la trace, liste des critères)`
  → réutilisation (`cached=true`, coût 0). Désactivable (`FORGE_JUDGE_CACHE_ENABLED`).
* **Juge heuristique** (`provider=heuristic`) : déterministe, hors ligne, pour les tests et la
  démo (recouvrement avec le résultat attendu, contraintes, sources citées, contradictions
  simples, structure) ; confiance plafonnée à 0,6 ; explications explicites.
* Coût des appels de juge : tokens × tarif (table de prix des modèles connus dans
  `forge.infra.llm.pricing`, sinon 0 et `cost=None`).
* Biais : l'ordre des critères est stable ; un avertissement est émis si un juge appartient à
  la même famille de modèles que l'agent évalué (auto-préférence).

### 7.4 Multi-juges

Pour chaque critère, les verdicts normalisés (0–1) des juges sont agrégés selon
`ScoreConfig.aggregation.method` : `mean`, `median`, `majority_vote` (note arrondie la plus
fréquente, égalité → médiane), `weighted` (`weights[judge key]`, défaut `JudgeSpec.weight`),
`min`, `custom` (expression sûre sur `scores`, `weights`, `confidences` avec `mean`, `median`,
`min`, `max`, `abs`, `len`, `sum`, opérateurs arithmétiques/comparaisons/`if-else` — évaluée par
un interpréteur AST restreint, jamais `eval`). `spread = max − min` mesure le désaccord ;
confiance agrégée = moyenne des confiances × (1 − spread/2). **Chaque verdict individuel reste
stocké** ; `scores.evaluation_ids` les référence.

### 7.5 Scores & composite (`forge.domain.scoring`)

* **Critère** : 0–1. Règles → score de la règle (plusieurs règles sur un critère → moyenne
  pondérée par `rule.weight`) ; juges → agrégat §7.4 ; métriques → normalisation linéaire :
  `cost` : 1 si `≤ cost_target`, 0 si `≥ cost_max` ; `latency` idem avec `latency_target_ms` /
  `latency_max_ms` ; `cost.tokens` rapporté à `agent.budget.max_tokens` si défini.
  Si `use_human_scores` et un score humain existe, il remplace le score IA dans le composite
  (les deux lignes sont conservées, `used_in_composite` l'indique).
* **Dimension** : moyenne des critères pondérée par `criterion_weights[key]` (défaut : poids du
  critère).
* **Composite** : `100 × Σ w_d·s_d / Σ w_d` sur les dimensions **disponibles** ayant un poids > 0
  (renormalisation, dimensions manquantes listées). `robustness` n'existe qu'au niveau groupe
  (benchmark/expérience, §9.2) : absent du composite d'un run.
* **Garde-fous** (`gates`) évalués après : `dimension`/`criterion` (`min` sur 0–1), `error`
  (type ou `*`, `min_severity`), `rule` (règle en échec) ; action `fail` (composite 0,
  `gate_failed`) ou `cap` (plafond). `passed = not gate_failed and composite ≥ pass_threshold`.
* `formula` : explication lisible (« Qualité 0,82 × 30 % + … = 78,4 ; plafonné à 40 par
  safety-floor »).

### 7.6 Erreurs

Chaque `DetectedError` devient une ligne `run_errors` (type, gravité, description, preuves,
évaluateur `kind`+`key`, `evaluation_id`, `trace_event_id`, critère). Dédoublonnage : même type +
même preuve + même critère sur un round → une seule erreur (évaluateurs listés dans la
description). Types inconnus de la table `error_types` → refusés à la création de juge/règle ;
à l'exécution, remplacés par `BAD_REASONING` (juges) avec le code d'origine dans la description.

### 7.7 Feedback (`forge.domain.feedback`)

`FeedbackReport` (scope `run`, `benchmark` ou `experiment`) : `summary`, `score`, `strengths`
(critères ≥ 0,8), `weaknesses` (critères < 0,6), `errors` (regroupées par type : nombre,
gravité max, exemples), `recommendations` (catégorie `RecommendationCategory`, titre,
description, justification, priorité, erreurs/critères liés, preuves), `priority_actions`.
Recommandations déterministes par règles de correspondance (ex. `SOURCE_ERROR`/`HALLUCINATION`
→ `retrieval` ; `INSTRUCTION_FAILURE` → `system_prompt` ; `WRONG_TOOL` → `tools` ;
`FORMAT_ERROR` → `output_format` ; coût élevé → `model` ; `MEMORY_ERROR` → `memory` ; latence
→ `orchestration`), enrichies par un LLM si `FORGE_FEEDBACK_LLM_*` est configuré
(`generator="llm:<model>"`, jamais d'invention de preuve). Format JSON stable : consommable
par NOVA pour produire une version candidate.

`forge.services.feedback.create_aggregate_feedback(session, *, scope, runs, benchmark_execution_id=None, experiment_id=None, agent_version_id=None) -> FeedbackReport`
construit un rapport agrégé sur un ensemble de runs (utilisé par l'analytique).

---

## 8. Exécution des runs (Agent Runner, file `execution`)

`execute_run_job(session, job)` :

1. Charger le run ; s'il est `cancelled` ou terminal → rien. `runs.mark_running`.
2. `specs_from_manifest` ; injecter les secrets (`credentials.resolve_credentials`).
3. **Préparer le contexte** (`services/context_providers.py`) selon
   `agent.context_config.source` : `scenario` (défaut : contexte du scénario), `orbit_snapshot`
   (`GET {orbit}/api/v1/projects/{project}/snapshots/{name}/{version}` — version résolue et hash
   enregistrés), `orbit_live` (`POST {orbit}/api/v1/projects/{project}/context`, `request_id`
   ORBIT tracé), `none`. Événement `context_prepared`.
4. **Limites** : `cache.concurrency_slot(f"agent:{agent_version_id}", max_concurrency or FORGE_RUNNER_DEFAULT_CONCURRENCY)` ;
   timeout `budget.timeout_seconds` ; budget tokens/coût vérifié par le recorder (dépassement →
   `BUDGET_EXCEEDED`).
5. Propager `traceparent` (`00-<otel_trace_id>-<span>-01`), `X-Forge-Run-Id`,
   `X-Forge-Scenario-Version`, et appeler `adapter.invoke(request, recorder)`.
6. Attendre `FORGE_TRACE_GRACE_SECONDS` les spans OTLP tardifs, puis persister
   `ExecutionTrace` + `TraceEvent` (tri par `started_at`, `seq` 1..n, parents résolus,
   `offset_ms` depuis le début du run, payloads tronqués à `FORGE_MAX_EVENT_PAYLOAD_CHARS`, sortie
   à `FORGE_MAX_OUTPUT_CHARS`), coût estimé (tarif `ModelSpec` sinon rapporté par l'agent).
7. `runs.mark_evaluating` (enfile l'évaluation). Erreur d'exécution non récupérable →
   trace partielle persistée + erreur d'exécution, puis évaluation (§7.1) ; erreur
   `retryable` → `RetryableJobError` (nouvel essai de la file, le run reste `running`).

### 8.1 Adapters

* `mock` : agent scripté déterministe (`adapter_config.script` : sortie, événements, latence,
  erreurs, variation par répétition) — tests et démos.
* `openai` / `anthropic` : FORGE **pilote la boucle d'agent** (system prompt, outils déclarés,
  `ToolMock` du scénario pour répondre aux appels d'outils, `budget.max_steps` tours) avec les
  secrets de l'identifiant ; chaque appel modèle → `llm_call`, chaque outil → `tool_call` +
  `tool_result`.
* `custom_api` : n'importe quel agent HTTP ; mode `forge` (FORGE Agent Protocol, défaut) ou
  `mapped` (gabarit de requête + chemins JSON de réponse).
* `nova` : agents NOVA via le NOVA Agent Protocol (FAP + identifiant d'agent NOVA, handoffs
  multi-agents → événements `agent_handoff`).

Le FORGE Agent Protocol est spécifié dans `docs/AGENT_PROTOCOL.md` (propriétaire execution).

### 8.2 Traces poussées par les agents

* **OTLP/HTTP** `POST /v1/traces` (protobuf ou JSON), auth clé `traces:write` (ou editor+).
  Rattachement au run par `trace_id` = `run.otel_trace_id`, sinon attribut `forge.run_id`.
  Conventions sémantiques GenAI (`gen_ai.operation.name`, `gen_ai.request.model`,
  `gen_ai.usage.input_tokens`/`output_tokens`, `gen_ai.tool.name`…) → `TraceEventType`.
  Spans orphelins comptés et ignorés (métrique).
* **JSON** `POST /api/v1/runs/{id}/events` (format des événements du FAP) pour les agents sans OTel.
* Les événements arrivant après le passage en `evaluating` sont ajoutés (seq suivants) mais
  n'influencent que les ré-évaluations.

---

## 9. Benchmarks, expériences, calibration

### 9.1 Benchmark

Scénarios (version épinglée ou dernière) × versions d'agents × `repetitions` + configuration de
score. `POST /benchmarks/{id}/run` crée une `BenchmarkExecution` (numéro séquentiel, matrice
figée) et N×M×K runs (`origin=benchmark`, priorité `PRIORITY_BENCHMARK`). Quand tous les runs
sont terminaux, `finalize_execution_job` calcule `summary` :

* par version d'agent : composite moyen + IC 95 % bootstrap, taux de réussite, taux d'échec de
  garde-fou, dimensions, coût moyen/total, latence moyenne/p95, tokens, erreurs par type,
  robustesse, écart de généralisation (public vs private+fresh) ;
* par scénario × agent (matrice), par catégorie, par difficulté, par modèle, par famille de
  variantes, par type d'erreur ;
* classement, meilleure version par dimension ;
* un `FeedbackReport` `benchmark` par version d'agent.

`GET /benchmarks/{id}/results?execution_id=&group_by=agent|model|version|scenario|category|family|error_type|date`
filtrable par visibilité, catégorie, date.

### 9.2 Robustesse

Par version d'agent × famille de scénarios (variantes + répétitions) : écart-type σ des
composites (0–1) ; `robustness = 1 − min(1, σ / robustness_max_std)` ; au niveau de l'agent :
moyenne des familles pondérée par leur taille. Intégrée au composite de groupe avec son poids.

### 9.3 Expérience

Baseline vs candidate sur les **mêmes versions de scénarios** (depuis un benchmark ou une liste),
K répétitions, même configuration. `finalize_experiment_job` → `comparison` :

* par dimension et pour le composite : moyenne baseline, candidate, delta (points et %), IC 95 %
  bootstrap apparié (10 000 rééchantillonnages, graine fixe), p-value de Wilcoxon signé,
  verdict `better` / `worse` / `equivalent` (|delta| < 2 points et IC ⊂ ±5) / `inconclusive` ;
* coût, latence, tokens : moyennes et variation relative (baisse de coût = gain) ;
* **régressions par scénario** : `σ_bruit` estimé sur les répétitions (défaut 5 points si K=1) ;
  régression si `delta ≤ −max(5, 2σ)` ; gravité `critical` si nouveau garde-fou en échec,
  nouvelle erreur `critical`, ou delta ≤ −15 ; `major` si delta ≤ −10 ; sinon `minor`.
  Améliorations listées symétriquement ;
* erreurs : types apparus / disparus / évolution des fréquences ;
* recommandation : `ship` (composite `better`, aucune régression critique, sécurité non
  `worse`), `ship_with_caution`, `do_not_ship` (composite `worse` ou régression critique ou
  sécurité `worse`), `inconclusive` ; phrase de synthèse et niveau de confiance ;
* un `FeedbackReport` `experiment` ; avertissement si baseline et candidate ont le même hash.

`GET /experiments/{id}/gate` → `{passed, recommendation, reasons[]}` pour la CI (CLI
`forge experiment run … --fail-on-regression`).

### 9.4 Calibration humaine

Paires (score IA normalisé, score humain normalisé) par run × critère (IA = agrégat ou juge
individuel). Mesures par juge et par critère : n, taux d'accord (|écart| ≤ 0,2), écart absolu
moyen, Spearman, Pearson, kappa de Cohen pondéré quadratique (notes ramenées à 0–5 entiers).
Statut : `insufficient_data` (n < 10), `calibrated` (kappa ≥ 0,6 et accord ≥ 0,7), `weak`
(kappa ≥ 0,4), `uncalibrated`. Gold dataset = dataset `kind=gold` listant des runs à noter.
File de revue : runs terminés sans évaluation humaine, triés par désaccord des juges puis
confiance faible (apprentissage actif).

---

## 10. Données de référence & démonstration

Bootstrap (§1). `make seed` (`python -m forge.seed`) charge un jeu de démonstration **via les
vrais services** : agents de démonstration (ProductAgent v1/v2/v3, SupportAgent, ResearchAgent),
bibliothèque de scénarios (Product Management, Discovery, Delivery, conformité, support,
recherche documentaire, multi-étapes) avec variantes et scénarios privés/fresh, un benchmark,
une expérience v1.2 → v1.3 montrant gains **et** régressions, et des évaluations humaines.

---

## 11. Observabilité de FORGE

Logs une ligne (request id), OpenTelemetry (spans API, jobs, appels d'agents et de juges) exporté
si `FORGE_OTLP_ENDPOINT`, métriques Prometheus (`forge_runs_total`,
`forge_run_execution_seconds`, `forge_run_evaluation_seconds`, `forge_judge_calls_total`,
`forge_judge_cost_total`, `forge_errors_detected_total`, `forge_otlp_spans_total`,
`forge_jobs_total`, `forge_worker_inflight_jobs`) sur `/metrics` (API) et `:9464` (workers).

---

## 12. Conventions de l'API

* Préfixe `/api/v1`, JSON, identifiants UUID, dates ISO 8601 UTC.
* Erreurs : `{"detail": "<message FR>", "code": "<code>"}` (`forge.api.errors`), validation →
  `422` avec `errors[]`.
* Listes paginées : `?page=1&page_size=25` → `Page[T]` = `{items, total, page, page_size}`.
* Schémas Pydantic dans `forge/api/schemas/<module>.py`, basés sur `schemas.common.ApiModel`.
* Toute route déclare son rôle minimum (`RequireViewer` … `RequireAdmin`).
* OpenAPI : `/api/v1/openapi.json` (types TypeScript du frontend générés depuis ce document).

Endpoints (propriétaire entre crochets) :

| Domaine | Endpoints |
|---|---|
| auth [platform] | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/password` |
| users [platform] | `GET/POST /users`, `PATCH /users/{id}` (admin) |
| api-keys [platform] | `GET/POST /api-keys`, `DELETE /api-keys/{id}` (admin) |
| credentials [platform] | `GET /credentials` (maintainer, indices seulement), `POST`, `PATCH /credentials/{id}` (rotation), `DELETE` (admin) |
| meta [platform] | `GET /meta` (énumérations, libellés FR, types de règles + schéma des params, adapters, fournisseurs de juges, catégories, capacités, URL OTLP) |
| agents [platform] | `POST/GET /agents`, `GET/PATCH /agents/{id}`, `POST/GET /agents/{id}/versions`, `GET /agent-versions/{id}`, `GET /agent-versions/{id}/diff?against=`, `POST /agent-versions/{id}/test`, `GET/POST /prompts`, `GET /prompts/{name}/versions`, `GET/POST /model-configurations`, `GET/POST /tool-configurations` |
| scenarios [platform] | `POST/GET /scenarios`, `GET/PATCH /scenarios/{id}`, `POST/GET /scenarios/{id}/versions`, `GET /scenario-versions/{id}`, `POST /scenarios/{id}/variants`, `POST /scenarios/import`, `GET /scenarios/export` |
| datasets [platform] | `POST/GET /datasets`, `GET/PATCH /datasets/{id}`, `POST /datasets/{id}/items`, `DELETE /datasets/{id}/items/{item_id}` |
| taxonomy [platform] | `GET/POST /criteria`, `GET/POST /error-types` |
| runs [platform] | `POST /runs`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/trace`, `GET /runs/{id}/timeline`, `GET /runs/{id}/manifest`, `POST /runs/{id}/cancel`, `POST /runs/{id}/retry` |
| traces [execution] | `POST /v1/traces` (racine), `POST /runs/{id}/events` |
| evaluations [evaluation] | `POST /runs/{id}/evaluate`, `GET /runs/{id}/evaluations`, `GET /runs/{id}/scores`, `GET /runs/{id}/errors`, `GET /runs/{id}/feedback`, `GET /runs/{id}/scores/{criterion_key}/provenance`, `GET /feedback-reports/{id}` |
| reviews [platform] | `GET /reviews/queue`, `POST /runs/{id}/human-evaluations`, `GET /runs/{id}/human-evaluations` |
| judges [evaluation] | `POST/GET /judges`, `GET /judges/{id}`, `POST /judges/{id}/versions`, `PATCH /judges/{id}` (enabled), `POST /judges/{id}/test` |
| evaluation-configs [evaluation] | `POST/GET /evaluation-configs`, `GET /evaluation-configs/{id}`, `POST /evaluation-configs/{id}/versions`, `POST /evaluation-configs/{id}/preview` |
| benchmarks [analytics] | `POST/GET /benchmarks`, `GET/PATCH /benchmarks/{id}`, `POST /benchmarks/{id}/run`, `GET /benchmarks/{id}/executions`, `GET /benchmark-executions/{id}`, `GET /benchmarks/{id}/results`, `POST /benchmark-executions/{id}/cancel` |
| experiments [analytics] | `POST/GET /experiments`, `GET /experiments/{id}`, `GET /experiments/{id}/comparison`, `GET /experiments/{id}/gate`, `POST /experiments/{id}/cancel` |
| calibration [analytics] | `GET /calibration?judge_id=&criterion_key=&dataset_id=` |
| analytics [analytics] | `GET /dashboard?days=30`, `GET /errors` (explorateur : filtres + agrégations) |
| audit [platform] | `GET /audit` (admin / maintainer) |

---

## 13. Frontend

Next.js 15 App Router, TypeScript strict, Tailwind v4, Radix, TanStack Query, Recharts,
lucide-react ; même design system qu'ORBIT, identité FORGE (orange/ambre, « forge »).
Pages : Tableau de bord, Agents (+ versions, diff), Scénarios (+ versions, variantes, éditeur),
Runs, **Run Detail** (3 colonnes : scénario | trace, messages, outils, sortie | composite et
dimensions ; puis juges, règles, erreurs, feedback — chaque score cliquable jusqu'à sa
provenance), Benchmarks, Expériences, Juges, Configurations d'évaluation, Revue humaine,
Calibration, Erreurs, Paramètres (utilisateurs, clés, identifiants, audit). Aucune logique
métier dans les composants : l'UI affiche ce que l'API calcule.

---

## 14. Tests

* `tests/unit/` : domaine pur (règles, juges, agrégation, scoring, statistiques, OTLP,
  rédaction…), sans base.
* Intégration : `tests/test_*.py` avec les fixtures de `tests/conftest.py` (`app`, `client`,
  `admin_client`, `client_as(Role.x)`, `db_session`, `run_jobs()`) et les fabriques
  `tests/factories.py`. Base isolée par suite : `FORGE_TEST_DATABASE=forge_test_<module>`.
* Aucun appel réseau réel : `respx` pour HTTP, adapter `mock`, juge `heuristic`.
* `make check` : ruff, format, mypy, lint-imports, pytest ; frontend : lint, typecheck, build.

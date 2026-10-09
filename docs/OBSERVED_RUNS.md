# FORGE — Runs observés (`POST /api/v1/runs/observed`)

Un **run observé** est un run **déjà exécuté par un système externe** (par exemple NOVA, agent de
livraison logicielle) que FORGE n'exécute pas : il l'**ingère** puis l'évalue avec son pipeline
normal (règles du scénario, métriques, juges de la configuration, score composite, erreurs,
feedback). Origine du run : `observed`.

> Ce document est le contrat d'intégration. Les exemples JSON balisés par `<!-- example: … -->`
> sont rejoués tels quels par `backend/tests/test_observed_runs.py` : s'ils divergent du code, les
> tests échouent.

---

## 1. Ingérer un run

`POST /api/v1/runs/observed` — rôle minimum **editor** (comme `POST /api/v1/runs` ; clé d'API
acceptée). Un scénario au-dessus de l'habilitation de l'appelant n'est pas révélé : `404`.

### Corps `ObservedRunIn`

| Champ | Type | Règle |
|---|---|---|
| `agent_version_id` | uuid | requis ; `404` si inconnu |
| `scenario_id` | uuid | requis ; la **version courante** du scénario est utilisée ; `404` si inconnu ou au-dessus de l'habilitation, `422` si archivé |
| `evaluation_config_id` | uuid \| null | `null` → configuration par défaut (celle des runs ad hoc) |
| `input` | objet | ce qui a été demandé à l'agent, ex. `{"prompt": "…", "context": {…}}` (stocké tel quel sur la trace) |
| `output_text` | texte \| null | résumé lisible de ce qui a été produit |
| `output_json` | objet \| null | résultat structuré : **c'est lui que lisent les règles** (chemins JSON, §3) |
| `execution_status` | `"completed"` \| `"failed"` | |
| `error` | texte \| null | cause de l'échec ; **refusé** (`422`) si `execution_status = completed` ; si `failed` sans `error`, un message par défaut est enregistré |
| `started_at`, `completed_at` | dates ISO 8601 **avec fuseau** (UTC) | `completed_at ≥ started_at` ; la latence du run est leur différence |
| `usage` | `{input_tokens, output_tokens, model_calls}` | entiers ≥ 0 (défaut 0) ; le coût est estimé avec le tarif du modèle de la version d'agent s'il existe |
| `tags` | liste de textes | 20 maximum, dédoublonnés |
| `external_id` | texte (1–200) | **clé d'idempotence**, unique **par agent** (toutes versions confondues) |

<!-- example: request -->
```json
{
  "agent_version_id": "11111111-1111-4111-8111-111111111111",
  "scenario_id": "22222222-2222-4222-8222-222222222222",
  "evaluation_config_id": "33333333-3333-4333-8333-333333333333",
  "input": {
    "prompt": "Ajouter l'export CSV des factures",
    "context": {"repository": "acme/billing", "issue": 412}
  },
  "output_text": "PR #87 fusionnée : export CSV des factures (une correction de CI).",
  "output_json": {
    "outcome": "completed",
    "merged": true,
    "first_pass_ci": false,
    "ci_fix_rounds": 1,
    "review_fix_rounds": 0,
    "human_interventions": 2,
    "stages": [
      {"key": "spec", "status": "done", "summary": "Spécification validée"},
      {"key": "code", "status": "done", "summary": "Export CSV implémenté"},
      {"key": "ci", "status": "done", "summary": "Verte au 2e essai"},
      {"key": "review", "status": "done", "summary": "Approuvée sans modification"},
      {"key": "merge", "status": "done", "summary": "PR #87 fusionnée"}
    ]
  },
  "execution_status": "completed",
  "error": null,
  "started_at": "2026-10-09T08:00:00Z",
  "completed_at": "2026-10-09T08:42:10Z",
  "usage": {"input_tokens": 184000, "output_tokens": 21000, "model_calls": 37},
  "tags": ["nova", "sdlc"],
  "external_id": "nova-sdlc:6f1c2a8e-3b7d-4c55-9a43-0d2f6e1b9c10"
}
```

### Réponse

* **`201`** à la création, **`200`** si `external_id` existe déjà pour cet agent : dans les deux cas
  le corps est le `RunOut` du run (le même que `GET /api/v1/runs`). Le contenu de la nouvelle requête
  n'est alors **pas** comparé ni appliqué : le run existant est renvoyé tel quel.
* À la création le run est `evaluating` (le job `evaluate_run` est en file) ; il devient
  `completed` (ou `failed`, §4) quelques secondes plus tard.
* `422` : corps invalide (dates sans fuseau, `completed_at < started_at`, `error` sur un run réussi,
  scénario archivé…) ; `403` : rôle viewer ; `401` : non authentifié ; `404` : agent / scénario /
  configuration inconnu ou scénario non visible.

<!-- example: response -->
```json
{
  "id": "5d0f9c3e-0a3c-4c43-a1a0-2f6f4f0b7a11",
  "status": "evaluating",
  "status_detail": "Évaluation en attente",
  "origin": "observed",
  "arm": null,
  "repetition": 0,
  "tags": ["nova", "sdlc"],
  "external_id": "nova-sdlc:6f1c2a8e-3b7d-4c55-9a43-0d2f6e1b9c10",
  "scenario_id": "22222222-2222-4222-8222-222222222222",
  "scenario_version_id": "7a1b2c3d-0000-4000-8000-000000000001",
  "scenario_slug": "nova-sdlc-delivery",
  "scenario_name": "NOVA — livraison SDLC (run observé)",
  "scenario_version": 1,
  "category": "software_delivery",
  "difficulty": "medium",
  "visibility": "public",
  "classification": 1,
  "agent_id": "9c8b7a65-0000-4000-8000-000000000002",
  "agent_version_id": "11111111-1111-4111-8111-111111111111",
  "agent_name": "NOVA SDLC",
  "agent_version": "1.0",
  "agent_label": "NOVA SDLC v1.0",
  "model": null,
  "evaluation_config_id": "33333333-3333-4333-8333-333333333333",
  "evaluation_round": 0,
  "composite_score": null,
  "passed": null,
  "gate_failed": false,
  "error_type": null,
  "latency_ms": 2530000.0,
  "cost": null,
  "total_tokens": 205000,
  "benchmark_execution_id": null,
  "experiment_id": null,
  "created_at": "2026-10-09T08:42:11.120000Z",
  "started_at": "2026-10-09T08:00:00Z",
  "finished_at": null
}
```

(Les valeurs ci-dessus sont celles d'un appel réel, avec des identifiants fictifs.)

### Ce que FORGE enregistre

* un `EvaluationRun` construit comme un run ad hoc : manifeste figé (version courante du scénario,
  version d'agent, configuration d'évaluation), `origin = observed`, aucun job d'exécution ;
* une `ExecutionTrace` (entrée, `output_text`, `output_json`, tokens, appels modèle, latence,
  coût estimé) et trois événements : `run_started`, `final_answer` (ou `error` si `failed`),
  `run_completed` — consultables comme ceux d'un run normal (`GET /runs/{id}/trace`) ;
* une entrée d'audit `run.observe`.

Un run observé **ne peut pas être relancé** (`POST /runs/{id}/retry` → `409`) : FORGE ne sait pas
le réexécuter. Il peut être ré-évalué (`POST /runs/{id}/evaluate`) comme les autres.

---

## 2. Échec d'exécution

`execution_status = "failed"` reproduit une erreur d'exécution capturée par FORGE : le run porte
`error` et `error_type = EXECUTION_ERROR`, les juges ne sont pas sollicités, le composite est forcé
à **0** (`passed = false`) et le run se termine `failed` après l'évaluation (les règles et métriques
sont tout de même évaluées et l'erreur est classée dans `GET /runs/{id}/errors`). Les sorties
fournies sont conservées sur la trace pour le diagnostic.

---

## 3. Score déterministe à partir de `output_json`

Les runs NOVA n'ont pas de texte attendu : le score vient de **règles** (`forge.domain.rules`) qui
lisent `output_json` par chemin JSON, sans LLM.

Faits vérifiés dans le code :

* les règles vivent dans le **scénario** (`content.rules`, avec `criterion_key` libre de la forme
  `<dimension>.<nom>`) ou dans la **configuration** (`rules`, mais alors les `criterion_key` doivent
  appartenir au catalogue de FORGE : pas de critère sur mesure). On utilise donc le scénario ;
* `expected_value` compare la valeur d'un chemin JSON (`{"path": "merged", "value": true}`) ;
  il n'y a pas d'opérateur de comparaison, donc `human_interventions ≤ 2` s'exprime avec une règle
  `json_schema` (`maximum`) — aucune extension du moteur n'est nécessaire ;
* les **juges** et les **garde-fous** (`gates`) appartiennent à la **configuration** d'évaluation. La
  configuration par défaut contient des juges LLM : elle noterait aussi les critères du scénario.
  Pour un score purement déterministe, il faut une configuration **sans juge** : c'est la raison
  d'être de `evaluation_config_id`. Sans juge, les runs terminent avec le `status_detail`
  « Aucun juge actif dans la configuration : critères jugés non évalués. » (information, pas une erreur) ;
* les dimensions dont le poids est 0 (coût, latence…) restent calculées et visibles dans les scores
  mais n'entrent pas dans le composite.

### 3.1 Scénario à créer (une fois) — `POST /api/v1/scenarios` (rôle editor)

Le texte de `input.prompt` n'est qu'un libellé : l'entrée réelle de chaque run est celle de
`ObservedRunIn.input`. Un scénario de classification 1 évite toute question d'habilitation.

| Critère | Règle (`output_json`) | Poids | Gravité si échec |
|---|---|---|---|
| `quality.delivered` | `outcome == "completed"` | 3 | high |
| `quality.merged` | `merged == true` | 3 | high |
| `quality.ci_first_pass` | `first_pass_ci == true` | 2 | low |
| `quality.no_review_fixes_needed` | `review_fix_rounds == 0` | 1 | low |
| `ux.autonomy` | `human_interventions ≤ 2` (schéma JSON, champ requis) | 1 | low |

Une règle dont la clé est absente de `output_json` échoue (score 0) : NOVA doit toujours envoyer les
quatre clés `outcome`, `merged`, `first_pass_ci`, `review_fix_rounds`, `human_interventions`.

<!-- example: scenario -->
```json
{
  "slug": "nova-sdlc-delivery",
  "name": "NOVA — livraison SDLC (run observé)",
  "category": "software_delivery",
  "visibility": "public",
  "classification": 1,
  "tags": ["nova", "observed"],
  "changelog": "Version initiale : notation par règles sur output_json.",
  "content": {
    "description": "Livraison d'un changement par le pipeline SDLC de NOVA (spécification, code, CI, revue, fusion). Scénario évalué à partir de runs observés : la note vient des règles ci-dessous appliquées à output_json.",
    "difficulty": "medium",
    "input": {"prompt": "Livrer un changement de bout en bout via le pipeline SDLC NOVA."},
    "expected_behavior": "Le changement est livré (outcome=completed) et fusionné, la CI passe du premier coup, la revue ne demande aucune correction et l'agent a besoin d'au plus 2 interventions humaines.",
    "criteria": [
      {"key": "quality.delivered", "name": "Livré", "weight": 3, "question": "Le run s'est-il terminé avec outcome = completed ?"},
      {"key": "quality.merged", "name": "Fusionné", "weight": 3, "question": "Le changement a-t-il été fusionné ?"},
      {"key": "quality.ci_first_pass", "name": "CI verte du premier coup", "weight": 2, "question": "La CI est-elle passée sans correction ?"},
      {"key": "quality.no_review_fixes_needed", "name": "Revue sans correction", "weight": 1, "question": "La revue s'est-elle terminée sans tour de correction ?"},
      {"key": "ux.autonomy", "name": "Autonomie", "weight": 1, "question": "L'agent a-t-il eu besoin d'au plus 2 interventions humaines ?"}
    ],
    "rules": [
      {
        "id": "delivered",
        "type": "expected_value",
        "params": {"path": "outcome", "value": "completed"},
        "criterion_key": "quality.delivered",
        "severity": "high",
        "description": "outcome vaut « completed »"
      },
      {
        "id": "merged",
        "type": "expected_value",
        "params": {"path": "merged", "value": true},
        "criterion_key": "quality.merged",
        "severity": "high",
        "description": "merged vaut true"
      },
      {
        "id": "ci_first_pass",
        "type": "expected_value",
        "params": {"path": "first_pass_ci", "value": true},
        "criterion_key": "quality.ci_first_pass",
        "severity": "low",
        "description": "first_pass_ci vaut true"
      },
      {
        "id": "no_review_fixes_needed",
        "type": "expected_value",
        "params": {"path": "review_fix_rounds", "value": 0},
        "criterion_key": "quality.no_review_fixes_needed",
        "severity": "low",
        "description": "review_fix_rounds vaut 0"
      },
      {
        "id": "autonomy",
        "type": "json_schema",
        "params": {
          "schema": {
            "type": "object",
            "required": ["human_interventions"],
            "properties": {"human_interventions": {"type": "integer", "maximum": 2}}
          }
        },
        "criterion_key": "ux.autonomy",
        "severity": "low",
        "error_type": "INSTRUCTION_FAILURE",
        "description": "human_interventions ≤ 2"
      }
    ]
  }
}
```

La réponse (`201`, `ScenarioDetailOut`) donne `id` (= `scenario_id` des runs observés). Pour changer
les règles plus tard, `POST /api/v1/scenarios/{id}/versions` : chaque run observé utilise la version
courante au moment de l'ingestion et la fige dans son manifeste.

### 3.2 Configuration d'évaluation à créer (une fois) — `POST /api/v1/evaluation-configs` (rôle **maintainer**)

Pas de juge, poids sur la qualité (0,8) et l'autonomie (0,2), seuil de réussite 70, et un garde-fou :
un changement **non fusionné** ne peut pas dépasser 60 (donc jamais « réussi »).
Ne **pas** mettre `is_default` à `true` : cela remplacerait la configuration par défaut de la plateforme.

<!-- example: evaluation_config -->
```json
{
  "key": "nova-delivery",
  "name": "NOVA — livraison (règles uniquement)",
  "description": "Notation déterministe des runs observés NOVA : règles du scénario sur output_json, aucun juge LLM.",
  "dimension_weights": {"quality": 0.8, "ux": 0.2},
  "pass_threshold": 70,
  "gates": [
    {
      "id": "must-be-merged",
      "kind": "rule",
      "target": "merged",
      "action": "cap",
      "cap": 60,
      "description": "Un changement non fusionné ne peut pas dépasser 60 (donc ne peut pas réussir)."
    }
  ]
}
```

La réponse (`201`, `ConfigOut`) donne `id` : c'est l'`evaluation_config_id` à passer à
`POST /api/v1/runs/observed`.

### 3.3 Formule

Pour chaque dimension, moyenne des critères pondérée par le poids de critère du scénario ; composite
= `100 × (0,8·qualité + 0,2·autonomie)` (poids renormalisés si une dimension manque), puis garde-fou.
Exemple de la requête du §1 : livré (3) + fusionné (3) + CI non verte du premier coup (0 sur 2) +
revue sans correction (1) = 7/9 ≈ 0,778 en qualité ; autonomie 2 interventions = 1,0 →
`100 × (0,8 × 0,778 + 0,2 × 1,0) ≈ 82,2` → `passed = true`.

---

## 4. Lire le résultat

1. Conserver le `id` renvoyé (ou retrouver le run avec `GET /api/v1/runs?external_id=<clé>`).
2. Interroger jusqu'à un statut terminal : `GET /api/v1/runs/{id}` → `status` passe de `evaluating`
   à `completed` (ou `failed` si `execution_status = failed`, ou si le job d'évaluation échoue
   définitivement : `status_detail` / `error` l'expliquent).
3. Une fois terminé :
   * `GET /api/v1/runs/{id}` (ou la liste `GET /api/v1/runs`) : `composite_score` (0–100), `passed`,
     `gate_failed`, `status`, `latency_ms`, `cost`, `total_tokens`. Le détail ajoute
     `composite` (`value`, `raw_value`, `dimensions`, `gates`, `formula` lisible) et `trace`
     (`output_json`, `latency_ms`, tokens) ;
   * `GET /api/v1/runs/{id}/scores` : `composite` et **un score par critère** (`scores[]` :
     `criterion_key`, `value` entre 0 et 1, `weight`, `source` = `rule`, `explanation` factuelle,
     `used_in_composite`) ; les critères `cost.*` / `latency.total` sont des métriques informatives ;
   * `GET /api/v1/runs/{id}/errors` : règles en échec classées (`INSTRUCTION_FAILURE`…) et erreur
     d'exécution éventuelle ; `GET /api/v1/runs/{id}/feedback` : rapport de feedback.
4. Filtres de liste utiles : `?origin=observed`, `?external_id=…`, `?tag=…`, `?agent_version_id=…`,
   `?status=completed`, `?passed=true`, `?min_composite=…`.

---

## 5. Limites connues

* Le contenu d'un rejeu (même `external_id`) n'est jamais comparé : pour corriger un run déjà
  ingéré, utiliser une nouvelle clé ou ré-évaluer le run existant.
* `output_json` est tronqué comme une sortie normale au-delà de `FORGE_MAX_OUTPUT_CHARS`
  (200 000 caractères) : un objet plus gros devient un aperçu et les règles échouent.
* La trace d'un run observé ne contient pas d'étapes détaillées (`stages` reste dans `output_json`) ;
  les règles `tool_called` / `max_tool_calls` n'ont donc rien à mesurer.
* Revenir en arrière sur la migration `0002` supprime les runs observés existants.

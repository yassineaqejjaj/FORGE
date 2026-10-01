# FORGE Agent Protocol v1 (FAP) — intégrer un agent à FORGE

> Propriétaire : module **execution**. Référence d'implémentation : `forge/adapters/` (côté FORGE)
> et `forge/demo_agents/` (côté agent). Identifiant de protocole : `forge-agent-protocol/v1`.

FORGE appelle les agents à évaluer, collecte ce qu'ils ont fait (trace) et les évalue. Quatre façons
d'intégrer un agent :

| Adapter | Pour qui | FORGE pilote la boucle ? |
|---|---|---|
| `custom_api` mode `forge` (défaut) | tout agent HTTP qui implémente ce protocole | non |
| `custom_api` mode `mapped` | une API existante qu'on ne veut pas modifier | non |
| `nova` | agents orchestrés par NOVA (NOVA Agent Protocol, §6) | non |
| `openai` / `anthropic` | un modèle + prompt + outils déclarés (FORGE exécute la boucle d'outils) | oui |
| `mock` | tests et démonstrations (agent scripté déterministe) | — |

Principe de confidentialité : un agent ne reçoit **jamais** le résultat attendu, les critères, les
règles ni les réponses simulées d'outils d'un scénario — uniquement l'entrée, le contexte préparé et
les contraintes (`ScenarioSpec.agent_view()` + contexte, docs/ARCHITECTURE.md §3.3).

---

## 1. Requête

`POST <endpoint>` (champ `endpoint` de la version d'agent ; un chemin relatif est concaténé à la
`base_url` de l'identifiant), `Content-Type: application/json`.

### 1.1 En-têtes

| En-tête | Valeur |
|---|---|
| `traceparent` | W3C Trace Context `00-<trace_id>-<span_id>-01`. `trace_id` = `run.otel_trace_id` : **réutilisez-le** pour vos spans OTLP (§7), ils seront rattachés au run. |
| `X-Forge-Run-Id` | identifiant du run FORGE |
| `X-Forge-Scenario-Version` | identifiant de la version de scénario |
| `X-Forge-Repetition` | numéro de répétition (0, 1, …) |
| `X-Forge-Attempt` | numéro de tentative (1 = premier essai, >1 après une erreur récupérable) |
| `Authorization` | `Bearer <api_key>` si l'identifiant (`credential_id`) de la version contient un secret |
| autres | en-têtes `header:<Nom>` de l'identifiant, en-têtes `adapter_config.headers` (gabarits `{{credentials.api_key}}` acceptés) |

### 1.2 Corps

```json
{
  "protocol": "forge-agent-protocol/v1",
  "run_id": "7b0f1c1e-3a1c-4c4b-9a55-0b8f6c8f2f10",
  "trace_id": "5b8efff798038103d269b633813fc60c",
  "repetition": 0,
  "attempt": 1,
  "scenario_version_id": "0d3c…",
  "input": {
    "prompt": "Rédige un PRD pour la fonctionnalité d'export CSV planifié.",
    "messages": [{"role": "user", "content": "…"}]
  },
  "context": {
    "documents": [{"id": "interviews-2026", "title": "Entretiens clients", "content": "…", "source": "orbit"}],
    "facts": ["…"]
  },
  "constraints": ["Maximum 300 mots", "Inclure des critères d'acceptation"],
  "agent": {
    "name": "ProductAgent", "slug": "product-agent", "version": "1.3",
    "system_prompt": "…",
    "model": {"provider": "openai", "model": "gpt-4o-mini", "temperature": 0.2, "…": "…"},
    "tools": [{"name": "jira.search", "description": "…", "parameters": {"type": "object"}}],
    "parameters": {"white_box": false},
    "memory": {}, "orchestration": {}
  },
  "budget": {"max_tokens": 20000, "max_cost": 0.5, "max_steps": 8, "timeout_seconds": 120}
}
```

* `input` et `constraints` viennent du scénario ; `context` est le contexte **préparé** par FORGE
  (contexte du scénario, snapshot ORBIT ou contexte ORBIT live selon `context_config`).
* `agent.parameters` = `adapter_config.parameters` de la version (paramètres libres de l'agent).
* Le délai `budget.timeout_seconds` est appliqué par FORGE : au-delà, le run échoue en `TIMEOUT`.

---

## 2. Réponse

`200 OK`, JSON :

```json
{
  "protocol": "forge-agent-protocol/v1",
  "output": "# PRD — Export CSV planifié\n\n## Contexte et problème\n- … [interviews-2026]",
  "output_json": {"task": "prd", "sources": ["interviews-2026"]},
  "messages": [{"role": "assistant", "content": "…"}],
  "events": [
    {"id": "1", "type": "retrieval", "name": "Recherche dans les documents", "offset_ms": 0, "duration_ms": 320,
     "output": [{"id": "interviews-2026", "score": 3.5}],
     "attributes": {"documents": ["interviews-2026"], "documents_count": 1}},
    {"id": "2", "type": "tool_call", "name": "jira.search", "offset_ms": 330, "duration_ms": 280,
     "input": {"query": "export CSV"}, "attributes": {"tool": "jira.search"}},
    {"id": "3", "parent_id": "2", "type": "tool_result", "name": "jira.search", "offset_ms": 610,
     "output": {"issues": [{"key": "PROD-142"}]}},
    {"id": "4", "type": "llm_call", "name": "Génération du PRD", "offset_ms": 620, "duration_ms": 2100,
     "attributes": {"model": "gpt-4o-mini", "input_tokens": 1850, "output_tokens": 640, "cost": 0.0012}}
  ],
  "usage": {"input_tokens": 1850, "output_tokens": 640, "model_calls": 1, "tool_calls": 1},
  "cost": 0.0012,
  "model": "gpt-4o-mini",
  "metadata": {"any": "valeur libre conservée dans les métadonnées de la trace"}
}
```

| Champ | Obligatoire | Règle |
|---|---|---|
| `output` | oui (ou `output_text` / `output_json`) | texte (Markdown) ; un objet `{"text", "json"}` est accepté ; un objet seul devient `output_json` |
| `output_json` | non | sortie structurée (règles `required_fields`, `json_schema`, `expected_value`) |
| `events` | non | étapes de l'exécution (§4), source `adapter` |
| `usage` | non | `input_tokens`/`prompt_tokens`, `output_tokens`/`completion_tokens`, `model_calls`, `tool_calls` ; à défaut somme des événements `llm_call` |
| `cost` | non | coût rapporté. **Le tarif du `ModelSpec` de la version prime** s'il est renseigné (`input_cost_per_mtok`, `output_cost_per_mtok`) |
| `metadata`, `model` | non | conservés dans `execution_traces.metadata.agent` |

Le budget de la version (`max_tokens`, `max_cost`) est vérifié sur l'usage rapporté : dépassement →
run en échec `BUDGET_EXCEEDED` (la trace partielle est conservée et le run est tout de même évalué).

---

## 3. Erreurs

| Situation | Effet |
|---|---|
| HTTP `4xx` (sauf 408, 425, 429) | erreur **définitive** : le run est évalué en échec (`EXECUTION_ERROR`) |
| HTTP `408`, `425`, `429`, `5xx` | erreur **récupérable** : nouvel essai de la file (backoff exponentiel, 3 tentatives) ; `X-Forge-Attempt` est incrémenté |
| connexion refusée, réseau | récupérable |
| délai dépassé | définitive, type `TIMEOUT` |
| `200` avec `{"error": {...}}` | selon `error.retryable` (défaut `false`) ; `error.type` devient le type d'erreur du run |
| JSON invalide ou `output` absent | définitive |

Corps d'erreur recommandé (toute réponse) :

```json
{"protocol": "forge-agent-protocol/v1",
 "error": {"type": "EXECUTION_ERROR", "message": "Quota du fournisseur épuisé", "retryable": true},
 "events": []}
```

Les `events` d'une réponse d'erreur `200` sont conservés dans la trace partielle. Les messages sont
affichés aux utilisateurs : écrivez-les en français et n'y mettez aucun secret.

---

## 4. Format des événements

Même format inline (`events` de la réponse) et poussé (`POST /api/v1/runs/{run_id}/events`).

| Champ | Type | Description |
|---|---|---|
| `type` | texte | `reasoning`, `message`, `llm_call`, `tool_call`, `tool_result`, `retrieval`, `memory`, `agent_handoff`, `decision`, `error`, `custom` (inconnu → `custom` + `attributes.original_type`) ; alias : `thought`/`thinking`, `tool`, `handoff`, `search`… |
| `name` | texte | libellé court (nom de l'outil pour `tool_call`) |
| `id`, `parent_id` | texte | identifiants locaux pour l'imbrication |
| `started_at`, `ended_at` | ISO 8601 | horodatage absolu (prioritaire) |
| `offset_ms`, `duration_ms` | nombre | sinon : décalage depuis l'appel (inline) ou depuis le début du run (poussé) ; sans décalage, l'événement suit le précédent |
| `status` | `ok` \| `error` | |
| `input`, `output` | JSON | charge utile (tronquée à `FORGE_MAX_EVENT_PAYLOAD_CHARS`) |
| `attributes` | objet | clés reconnues : `model`, `input_tokens`, `output_tokens`, `cost`, `tool`, `arguments`, `documents` (ids), `documents_count`, `agent`, `error`, `error_type`, `http_status` |
| `span_id`, `parent_span_id` | hex | liaison avec des spans OTLP |

Les raccourcis `model`, `tool`, `arguments`, `input_tokens`, `output_tokens`, `cost`, `documents`,
`agent` au premier niveau sont recopiés dans `attributes`. FORGE ajoute lui-même `run_started`,
`context_prepared`, `final_answer`, `error` (échec d'exécution) et `run_completed` (source `runner`).

Les règles d'évaluation s'appuient sur ces événements : `tool_called` / `tool_not_called` /
`max_tool_calls` comptent les `tool_call` (par `attributes.tool` ou `name`) ; les juges voient la
trace compactée `[E<seq>] +<offset>ms <type> <name> — <résumé>`.

### 4.1 Pousser des événements JSON

```bash
curl -X POST "$FORGE/api/v1/runs/$RUN_ID/events" \
  -H "Authorization: Bearer fgk_xxxxxxxx_<secret>" -H "Content-Type: application/json" \
  -d '{"events": [{"type": "tool_call", "name": "crm.lookup", "offset_ms": 120, "duration_ms": 80,
                    "input": {"order": "A-12"}}]}'
# → {"run_id": "…", "accepted": 1, "duplicates": 0, "first_seq": 7, "last_seq": 7}
```

Clé d'API avec le scope `traces:write` (ou rôle editor+). 1 000 événements maximum par requête.

---

## 5. Mode `mapped` (API existante)

`adapter_config` de la version :

```json
{
  "mode": "mapped",
  "method": "POST",
  "url": "https://assistant.example.com/v2/chat",
  "headers": {"X-Api-Key": "{{credentials.api_key}}"},
  "body_template": {
    "question": "{{input.prompt}}",
    "system": "{{system_prompt}}",
    "documents": "{{context.documents}}",
    "session": "forge-{{run_id}}"
  },
  "output_path": "data.answer",
  "output_json_path": "data.structured",
  "usage_paths": {"input_tokens": "usage.prompt_tokens", "output_tokens": "usage.completion_tokens"},
  "cost_path": "billing.cost",
  "events_path": "trace.steps",
  "error_path": "error"
}
```

* Variables : `input`, `prompt`, `context`, `context_text` (JSON), `constraints`, `system_prompt`,
  `run_id`, `trace_id`, `scenario_version_id`, `agent.name`, `agent.version`, `model`, `parameters`,
  `credentials.api_key`, `credentials.base_url`.
* Une valeur constituée d'un seul gabarit (`"{{context.documents}}"`) est remplacée par la valeur
  brute (objet, liste) ; sinon interpolation texte.
* Chemins JSON simples `a.b[0].c` (préfixe `$.` accepté). `events_path` doit pointer vers une liste
  d'événements au format §4. Pour `GET`, le corps rendu devient la query string.
* `url` absente → `endpoint` de la version. Les en-têtes de traçabilité (§1.1) sont toujours envoyés.

---

## 6. NOVA Agent Protocol

Adapter `nova` : `POST {base}{path}` avec `base` = `base_url` de l'identifiant NOVA (ou `endpoint`)
et `path` = `adapter_config.path` (défaut `/v1/agents/{nova_agent_id}/runs`). Corps = FAP §1.2 +
`"nova_agent_id": "<adapter_config.nova_agent_id>"` (+ `"options"` = `adapter_config.nova_options`).
Réponse = FAP §2 + détail multi-agents :

```json
{
  "output": "…",
  "handoffs": [
    {"from": "orchestrator", "to": "writer", "reason": "rédaction du PRD", "offset_ms": 40, "duration_ms": 1800}
  ],
  "agents": [
    {"name": "writer", "role": "rédacteur",
     "events": [{"type": "llm_call", "name": "Rédaction", "offset_ms": 60,
                 "attributes": {"model": "…", "input_tokens": 900, "output_tokens": 400}}]},
    {"name": "reviewer", "events": [{"type": "reasoning", "name": "Relecture", "offset_ms": 1900}]}
  ]
}
```

Chaque `handoff` devient un événement `agent_handoff` (attributs `from`, `to`, `agent`, `reason`) ;
un agent de `agents` sans handoff explicite reçoit un `agent_handoff` synthétique. Les événements d'un
sous-agent sont imbriqués sous son handoff et portent `attributes.agent`.

---

## 7. Traces OpenTelemetry (OTLP/HTTP)

Les agents instrumentés avec OpenTelemetry exportent leurs spans vers FORGE :

* `POST {FORGE}/v1/traces` (racine, pas `/api/v1`), `application/x-protobuf` ou `application/json`,
  `Content-Encoding: gzip` accepté, taille maximale `FORGE_OTLP_INGEST_MAX_BYTES` (413 au-delà).
* Authentification : `Authorization: Bearer fgk_…` ou `X-Forge-Key` — clé avec le scope
  `traces:write` (à donner aux agents) ou rôle editor+.
* Rattachement : `trace_id` du span = `trace_id` du `traceparent` reçu (= `run.otel_trace_id`), sinon
  attribut `forge.run_id` (span ou ressource). Les spans sans run (ou d'un run au-dessus de
  l'habilitation de la clé) sont ignorés et signalés dans `partialSuccess.rejectedSpans`.
* Réponse conforme OTLP/HTTP : `ExportTraceServiceResponse` protobuf ou JSON
  `{"partialSuccess": {"rejectedSpans": "1", "errorMessage": "…"}}` ; en-têtes
  `X-Forge-Attached-Spans`, `X-Forge-Orphan-Spans`.
* Les spans reçus pendant l'appel sont fusionnés dans la trace (tri chronologique, `seq` 1..n) ;
  FORGE attend `FORGE_TRACE_GRACE_SECONDS` après la réponse des agents HTTP pour les spans tardifs.
  Les spans arrivés après le passage en évaluation sont ajoutés à la suite et ne comptent que pour
  les ré-évaluations. Un span déjà reçu (même `span_id`) est ignoré.
* Usage : si la réponse de l'agent ne rapporte aucun token, FORGE somme ceux des spans `llm_call`.

### 7.1 Correspondance des conventions GenAI

| Span OTel | Événement FORGE | Attributs repris |
|---|---|---|
| attribut `forge.event.type` | ce type (prioritaire) | — |
| `gen_ai.operation.name` ∈ `chat`, `text_completion`, `generate_content`, `embeddings` (ou `gen_ai.request.model` seul) | `llm_call` | `gen_ai.response.model`/`gen_ai.request.model` → `model` ; `gen_ai.usage.input_tokens` → `input_tokens` ; `gen_ai.usage.output_tokens` → `output_tokens` ; `gen_ai.usage.cost` → `cost` ; `gen_ai.response.finish_reasons` |
| `gen_ai.operation.name = execute_tool` ou `gen_ai.tool.name` | `tool_call` (un seul événement : entrée = arguments, sortie = résultat) | `gen_ai.tool.name` → `tool` ; `gen_ai.tool.call.arguments` → `arguments`/`input` ; `gen_ai.tool.call.result` → `output` |
| `gen_ai.operation.name = invoke_agent` / `create_agent` | `agent_handoff` (agent imbriqué) ; `custom` pour l'agent racine (parent = span du `traceparent`) | `gen_ai.agent.name` → `agent` |
| `retrieval`, `db.system`, `gen_ai.data_source.id` | `retrieval` | `forge.documents` (liste d'ids) → `documents` |
| statut `ERROR` sans autre correspondance | `error` | `status.message` → `error` ; `error.type` → `error_type` |
| autre | `custom` | — |

Entrées / sorties : `gen_ai.input.messages` / `gen_ai.output.messages` (JSON), `gen_ai.prompt` /
`gen_ai.completion`, événements de span `gen_ai.content.prompt` / `gen_ai.content.completion`,
`forge.input` / `forge.output`. Les autres attributs sont conservés tels quels (60 au maximum).

### 7.2 Exemple curl (OTLP/JSON)

```bash
curl -X POST "$FORGE/v1/traces" \
  -H "Authorization: Bearer $FORGE_TRACES_KEY" -H "Content-Type: application/json" \
  -d '{"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "mon-agent"}}]},
       "scopeSpans": [{"spans": [{
         "traceId": "5b8efff798038103d269b633813fc60c", "spanId": "eee19b7ec3c1b174",
         "name": "chat gpt-4o-mini", "startTimeUnixNano": "1772355600000000000", "endTimeUnixNano": "1772355601200000000",
         "attributes": [
           {"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}},
           {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o-mini"}},
           {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "1850"}},
           {"key": "gen_ai.usage.output_tokens", "value": {"intValue": "640"}}]}]}]}]}'
```

### 7.3 Exemple Python (SDK OpenTelemetry)

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

provider = TracerProvider(resource=Resource.create({"service.name": "mon-agent"}))
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
    endpoint="https://forge.example.com/v1/traces",
    headers={"Authorization": "Bearer fgk_xxxxxxxx_<secret>"},
)))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("mon-agent")


def handle(request_headers: dict[str, str], body: dict) -> dict:
    ctx = extract(request_headers)  # lit le traceparent envoyé par FORGE → même trace_id que le run
    with tracer.start_as_current_span("invoke_agent product", context=ctx) as root:
        root.set_attribute("gen_ai.operation.name", "invoke_agent")
        root.set_attribute("gen_ai.agent.name", "product")
        root.set_attribute("forge.run_id", body["run_id"])  # rattachement de secours
        with tracer.start_as_current_span("execute_tool jira.search") as span:
            span.set_attribute("gen_ai.operation.name", "execute_tool")
            span.set_attribute("gen_ai.tool.name", "jira.search")
            span.set_attribute("gen_ai.tool.call.arguments", '{"query": "export CSV"}')
        with tracer.start_as_current_span("chat gpt-4o-mini") as span:
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.request.model", "gpt-4o-mini")
            span.set_attribute("gen_ai.usage.input_tokens", 1850)
            span.set_attribute("gen_ai.usage.output_tokens", 640)
    provider.force_flush()  # avant de répondre : les spans arrivent pendant le délai de grâce
    return {"output": "…", "events": []}
```

Ne renvoyez pas les mêmes étapes à la fois en `events` inline et en spans OTLP : elles seraient
comptées deux fois.

---

## 8. Adapters `openai` et `anthropic` (boucle pilotée par FORGE)

Pas de protocole à implémenter : FORGE appelle directement le modèle (`POST {base_url}/chat/completions`
compatible OpenAI, ou `POST {base_url}/v1/messages` avec `anthropic-version: 2023-06-01`) avec le
prompt système, la conversation (consigne + contexte + contraintes rendus en Markdown) et les outils
de la configuration d'outils. Les appels d'outils du modèle reçoivent les `tool_mocks` du scénario :
premier mock dont `tool` correspond et dont `match` est un sous-ensemble des arguments (comparaison
de texte insensible à la casse) ; aucun mock → message d'erreur renvoyé au modèle (`tool_result` en
erreur, `TOOL_FAILURE`). Au plus `budget.max_steps` appels au modèle (au-delà : `BUDGET_EXCEEDED`).
Les noms d'outils sont rendus compatibles (`jira.search` → `jira_search`) et retraduits dans la trace.
`api_key` et `base_url` viennent de l'identifiant ; `adapter_config.response_format = "json"` extrait
`output_json` de la réponse.

## 9. Adapter `mock`

`adapter_config.script` : `output` (gabarits `{{input.prompt}}`…), `output_json`, `events` (format
§4), `usage`, `cost`, `model`, `latency_ms`, `error` (`message`, `error_type`, `retryable`),
`fail_on_attempts` (échec récupérable aux tentatives listées), `by_repetition` (`{"1": {...}}`,
surcharge par répétition). Déterministe.

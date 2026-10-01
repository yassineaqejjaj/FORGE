# Agents de démonstration

> Service `demo-agents` (`forge.demo_agents.app:app`, port 8190, `docker/entrypoint.sh demo-agents`).
> Propriétaire : module **execution**. Ce document sert de référence pour écrire les scénarios de
> démonstration (`forge.seed`).

Les agents sont **simulés et déterministes** : aucun LLM n'est appelé. Ils parlent le FORGE Agent
Protocol v1 (docs/AGENT_PROTOCOL.md), produisent des sorties réalistes en français (Markdown) dérivées
de l'entrée et des documents du contexte, et renvoient des événements (`reasoning`, `retrieval`,
`tool_call`/`tool_result`, `decision`, `llm_call` avec modèle, tokens et coût), l'usage et le coût.

* **Reproductibilité** : la sortie dépend de `scenario_version_id` + `repetition` (graine). Deux runs
  de la même version de scénario et de la même répétition donnent la même réponse ; les répétitions
  varient légèrement (formulations, défauts simulés, latence).
* **Défauts simulés** : chaque version a des comportements caractéristiques déclenchés de façon
  pseudo-aléatoire (probabilités ci-dessous). Ils sont listés dans
  `metadata.simulated_behaviors` de la réponse (conservé dans `execution_traces.metadata.agent`) pour
  vérifier qu'un juge ou une règle les détecte.
* **Latence** : simulée par une attente réelle (`simulated_latency_ms`), multipliée par
  `FORGE_DEMO_LATENCY_SCALE` (défaut 1) ou `parameters.latency_scale` ; 0 = aucune attente (tests).

## Endpoints

| Méthode | Chemin | Rôle |
|---|---|---|
| `GET` | `/health` | santé |
| `GET` | `/agents` | catalogue : agents, versions, modèle simulé, traits, endpoint |
| `POST` | `/agents/{slug}/{version}/invoke` | requête FAP → réponse FAP |

Configuration d'une version d'agent dans FORGE :

```json
{"adapter_kind": "custom_api",
 "endpoint": "http://demo-agents:8190/agents/product-agent/1.3/invoke",
 "adapter_config": {"mode": "forge", "parameters": {}}}
```

(`FORGE_DEMO_AGENTS_URL` donne la base, `http://demo-agents:8190` dans docker compose.) Le coût est
rapporté par l'agent ; pour que FORGE le recalcule depuis un `ModelSpec`, utilisez les tarifs des
modèles simulés :

| Modèle simulé | Entrée / 1M tokens | Sortie / 1M tokens |
|---|---|---|
| `sim-standard-4` | 2,50 | 10,00 |
| `sim-efficient-2` | 0,40 | 1,60 |

`parameters` reconnus (`adapter_config.parameters`) :

| Paramètre | Effet |
|---|---|
| `latency_scale` | facteur de latence (0–10) |
| `white_box: true` | les étapes sont poussées en spans OTLP vers `FORGE_OTLP_INGEST_URL` avec la clé `FORGE_DEMO_OTLP_KEY` (scope `traces:write`) au lieu d'être renvoyées inline ; en cas d'échec de l'envoi, retour aux événements inline (`metadata.trace_delivery`, `metadata.warnings`) |
| `simulate_failure: "transient"` | HTTP 503 récupérable à la première tentative, succès ensuite (démonstration des nouveaux essais) |
| `simulate_failure: "permanent"` | HTTP 422 (échec définitif) |

## Contexte commun

Les documents sont lus dans `context.documents` : `[{"id", "title", "content", "source"?}]`. Les ids
sont cités sous la forme `[doc-id]` (règles `citation_required`, `source_present`). Les phrases des
documents sont la matière première des réponses : écrivez des documents de 3 à 8 phrases factuelles
(chiffres, besoins, irritants, verbatims). Une adresse e-mail dans un document (verbatim client)
permet de tester la fuite de données personnelles (`no_pii`).

Limite de longueur : `input.word_limit` (ou `max_words`), ou une contrainte / consigne contenant
« Maximum 300 mots », « 300 mots maximum », « moins de 300 mots », « au plus 300 mots ». La limite
est mesurée en mots comme la règle `max_length` (`words`).

---

## `product-agent` — ProductAgent

Rédige trois types de livrables. Tâche : `input.task` (`prd`, `user_stories`, `discovery`) sinon
détectée dans la consigne (« user stories »/« récits utilisateur » → `user_stories` ; « synthèse »,
« discovery », « entretiens », « interviews », « verbatims », « retours » → `discovery` ; sinon `prd`).
Fonctionnalité : `input.feature` (ou `topic`), sinon extraite de « … la fonctionnalité X … », sinon
titre du premier document. Persona : `input.persona`, sinon le plus fréquent parmi gestionnaire,
administrateur, client, conseiller, responsable, utilisateur, agent.

Structure des sorties (titres Markdown, utilisables avec `sections_present`) :

| Tâche | Sections |
|---|---|
| `prd` | `# PRD — <fonctionnalité>`, `## Contexte et problème`, `## Objectifs`, `## Périmètre`, `## Exigences fonctionnelles`, `## Critères d'acceptation`, `## Indicateurs de succès`, `## Risques et questions ouvertes`, `## Sources` |
| `user_stories` | `# User stories — …`, `## Contexte`, `## User stories` (`### US-n`, « En tant que … je veux … afin de … », **Critères d'acceptation**), `## Hors périmètre`, `## Sources` |
| `discovery` | `# Synthèse discovery — …`, `## Constats clés`, `## Verbatims`, `## Opportunités`, `## Hypothèses à valider`, `## Prochaines étapes`, `## Sources` |

`output_json` : `{"task", "feature", "word_count", "sources": [ids]}`.
Outils (événements) : `search.web`, `jira.search` (`{"query", "project"}`).

| Version | Modèle | Latence simulée | Coût | Comportements |
|---|---|---|---|---|
| **1.2** (référence) | `sim-standard-4` | ≈ 1,3–2,6 s | élevé (tout le contexte dans le prompt) | omet les critères d'acceptation (≈ 45 %, PRD et user stories) ; cite un document qui ne soutient pas l'affirmation (≈ 40 %, si ≥ 2 documents) ; recopie un verbatim contenant l'e-mail d'un client (≈ 35 %, si un e-mail existe dans le contexte — fuite `DATA_LEAK`) ; appel inutile à `search.web` (≈ 50 %) ; respecte la limite de mots |
| **1.3** | `sim-efficient-2` | ≈ 2,9–4,8 s (recherche ciblée + re-classement) | ≈ 5 à 6× moins cher | toutes les sections, citations correctes, pas de données personnelles (e-mails masqués), `jira.search` sur les user stories ; **régression** : ignore la limite de mots sur `user_stories` (6 stories détaillées) et `discovery` (section « Analyse détaillée ») — respectée sur les PRD |
| **1.4** | `sim-efficient-2` | ≈ 1,3–2,0 s | faible | corrige 1.2 et 1.3 : limites respectées, e-mails masqués (`[e-mail masqué]`), citations correctes ; défaut résiduel : oublie « Indicateurs de succès » d'un PRD (≈ 15 %) |

Scénarios conseillés pour l'expérience v1.2 → v1.3 (gains **et** régressions) : PRD avec documents
contenant un e-mail client + règles `sections_present` (« Critères d'acceptation »), `no_pii`,
`citation_required`, `tool_not_called` (`search.web`) → gains de 1.3 ; user stories / synthèses
discovery avec « Maximum 250 mots » + `max_length` (`words: 250`) et `max_latency` → régressions de 1.3.
Avec 2 documents de ~4 phrases, les user stories de 1.3 dépassent ~400 mots.

## `support-agent` — SupportAgent

Répond à un ticket client en appliquant la politique de retour / remboursement.

Entrée : `input.prompt` (texte du ticket) et, de préférence, `input.ticket` :

```json
{"id": "T-1042",
 "customer": {"name": "Jean Martin", "email": "jean.martin@example.com", "phone": "06 12 34 56 78"},
 "order": {"product": "Casque audio", "category": "audio", "amount": 129.0,
           "purchase_date": "2026-02-01", "delivery_date": "2026-02-03",
           "days_since_purchase": 45, "condition": "damaged"}}
```

Ancienneté : `input.today` (ou `context.today`) − `delivery_date`/`purchase_date`, sinon
`days_since_purchase`, sinon « il y a N jours » dans le texte. Article défectueux : `condition` =
`damaged`/`defective` ou mots « défectueux », « cassé », « endommagé », « abîmé », « ne fonctionne
pas », « en panne ».

Politique : document dont l'id ou le titre contient « policy »/« politique » (sinon le premier),
complété par `context.policy` structuré : `return_window_days` (défaut : premier « N jours » du
document, sinon 30), `damaged_window_days`, `non_returnable_categories` (sinon « Non remboursables :
a, b » dans le texte), `max_goodwill_amount` (défaut 0), `escalation_amount`.

Décision correcte (`output_json.decision`) : catégorie non reprise et non défectueux → `refuse` ;
ancienneté inconnue → `request_info` ; défectueux → `replace_or_refund` dans le délai, sinon
`escalate` ; hors délai → `refuse` ; montant > `escalation_amount` → `escalate` ; sinon `refund`.
Sortie : `**Décision :** …`, réponse au client, signature, (1.1) note interne.
`output_json` : `{"decision", "ticket_id", "policy_reference", "days_since_purchase", "window_days"}`
(règle `expected_value` sur `decision`). Outils : `crm.lookup_order` (toujours), `refund.create`.

| Version | Modèle | Comportements |
|---|---|---|
| **1.0** | `sim-standard-4` | applique un délai de 60 jours au lieu de celui de la politique (≈ 50 % → rembourse à tort entre 31 et 60 jours) ; promet un bon d'achat de 30 € non autorisé (≈ 35 %, si `max_goodwill_amount` < 30) ; recopie l'e-mail / le téléphone du client (≈ 30 %) ; ne cite pas la politique ; appelle `refund.create` sur une demande refusée (≈ 30 %) |
| **1.1** | `sim-efficient-2` | politique appliquée correctement, cite `[<id politique>]`, `refund.create` seulement si remboursement ; oublie parfois la référence du ticket (≈ 15 %) |

Cas utiles : achat à 45 jours avec délai 30 (1.0 rembourse parfois), article défectueux à 5 jours,
catégorie non reprise (carte cadeau), montant au-dessus du seuil d'escalade, ticket sans date.

## `research-agent` — ResearchAgent 1.0

Questions-réponses sur `context.documents`. Les phrases sont classées par recouvrement de mots-clés
avec la question ; si le meilleur passage partage moins de 2 mots-clés, l'agent répond que les
documents ne permettent pas de répondre (`output_json.answerable = false`, section
`## Sources consultées`) — utile pour les questions sans réponse. Sinon : `## Réponse` (synthèse
citée), `## Éléments détaillés` (une puce citée `[doc-id]` par passage), `## Limites`, `## Sources`.
Données personnelles masquées. Défaut simulé : ajoute une affirmation générale non sourcée (≈ 20 %).
`output_json` : `{"answerable", "sources"}`. Modèle `sim-efficient-2`, latence ≈ 1,0–1,8 s.

## Politique de contenu

Les scénarios de démonstration ne doivent concerner ni la santé, ni les plateformes d'échange de
crypto-actifs, ni des contenus adultes ou piratés (politique de l'organisation). Les e-mails et
téléphones utilisés doivent être fictifs (`@example.com`, numéros de test).

# Démonstration guidée de FORGE (10–15 min)

> Question de la démo : **« ProductAgent v1.3 est-elle vraiment meilleure que v1.2 ? »**
> Réponse que FORGE apporte, preuves à l'appui : *meilleure sur les PRD et beaucoup moins chère,
> mais plus lente et avec 9 régressions critiques sur les livrables à longueur limitée — ne pas
> déployer ; la v1.4, issue du feedback, corrige et peut être déployée.*

Le jeu de démonstration met en scène **Nordalis**, éditeur **fictif** d'un logiciel SaaS B2B de
facturation et de notes de frais. Tous les noms, e-mails (`@example.com`) et chiffres sont
inventés. Aucun contenu lié à la santé, aux plateformes d'échange de crypto-actifs, aux contenus
adultes ou piratés (politique de l'organisation).

---

## 0. Préparation (avant la démo)

```bash
make up                                   # plateforme complète (web :3100, api :8100)
make seed                                 # charge la démo (≈ 2–3 min), idempotent
make reseed                               # = python -m forge.seed --reset : repart de zéro
docker compose exec -T api cat .seed-credentials.json   # comptes et clés de démo
```

Options de `python -m forge.seed` : `--reset` (efface les données métier ; `--yes` obligatoire si
`FORGE_ENV=production`), `--scale small|full`, `--sync` (traite les jobs dans le processus, sans
workers), `--no-wait` (lance les benchmarks et rend la main ; relancer `make seed` ensuite complète
expériences et évaluations humaines), `--demo-agents-url`, `--latency-scale` (défaut 0,25 : latence
simulée accélérée), `--timeout`, `--credentials-file`, `--quiet`.

Tout est créé **via les services FORGE** (mêmes chemins que l'API, entrées d'audit comprises), puis
exécuté par le **vrai pipeline** : agents de démonstration → runner → évaluation (règles, juge
heuristique, métriques) → agrégation (benchmarks, expériences).

### Comptes

| Persona | E-mail | Rôle | Habilitation | Mot de passe (dev) |
|---|---|---|---|---|
| Administrateur | `admin@forge.local` | admin | C3 | `FORGE_BOOTSTRAP_ADMIN_PASSWORD` |
| Camille Laurent — responsable qualité IA | `camille.laurent@nordalis.example` | maintainer | C3 | `Nordalis-Demo-2026` |
| Julien Mercier — product manager | `julien.mercier@nordalis.example` | editor | C2 | `Nordalis-Demo-2026` |
| Sarah Benali — experte métier | `sarah.benali@nordalis.example` | evaluator | C2 | `Nordalis-Demo-2026` |
| Thomas Nguyen — direction produit | `thomas.nguyen@nordalis.example` | viewer | C1 | `Nordalis-Demo-2026` |

En `FORGE_ENV=production`, les mots de passe sont générés aléatoirement et écrits uniquement dans
`backend/.seed-credentials.json` (non versionné). Deux clés d'API sont créées :
**« Agents de démonstration — traces »** (portée `traces:write` uniquement, à donner aux agents) et
**« CI Nordalis — expériences (démo) »** (editor, C1, pour la CLI).

### Ce que crée le seed (échelle `full`)

| Objet | Contenu |
|---|---|
| Configuration d'évaluation | **`nordalis-demo`** « Nordalis — démo produit et support » : qualité 30 %, sécurité 25 %, cohérence 15 %, robustesse 10 %, coût / latence / UX 5 % ; garde-fous par défaut (fuite de données → 0, sécurité < 50 % → plafond 40) + **`word-limit-cap`** : limite de mots dépassée → score plafonné à 65 |
| Prompts | `product_manager` v1 → **v13** (v11 = ProductAgent 1.2, v12 = 1.3, v13 = 1.4), `support_agent` v1–v2, `research_agent` v1 |
| Modèles simulés | `NOVA sim-standard-4 (simulé)` (2,50 / 10,00 par M tokens), `NOVA sim-efficient-2 (simulé)` (0,40 / 1,60) |
| Outils | `product-agent-tools` v1 (search.web, jira.search) et v2 (jira.search), `support-agent-tools`, `research-agent-tools` |
| Agents (fournisseur « NOVA (démo) », adapter `custom_api`) | **ProductAgent** 1.2 / 1.3 / 1.4, **SupportAgent** 1.0 / 1.1, **ResearchAgent** 1.0 — changelogs = boucle d'amélioration |
| Jeux de données | **« Nordalis — corpus produit et politiques »** (contexte, 15 documents : entretiens, spécifications, indicateurs, veille, politiques) ; **« Nordalis — jeu gold de calibration »** (8 runs notés) |
| Scénarios (29) | 22 ProductAgent (PRD, discovery, delivery, multi-étapes), 7 SupportAgent, 3 ResearchAgent (recherche documentaire, conformité) ; 7 variantes `_variant_a` / `_variant_b`, **3 privés**, **2 fresh**, **1 C2 fictif** ; difficultés easy → expert |
| Benchmarks | **Product Agent Benchmark** (19 scénarios × ProductAgent 1.2 / 1.3 / 1.4 × K=2 = 114 runs), **Support Benchmark** (7 × 2 × 2 = 28 runs) |
| Expériences | **ProductAgent v1.2 → v1.3** (18 scénarios × K=3 = 108 runs, liée au feedback d'un run v1.2), **SupportAgent v1.0 → v1.1** (K=3, 42 runs), **ProductAgent v1.3 → v1.4** (K=2, 72 runs, liée au feedback de l'expérience v1.3) |
| Runs ad hoc | ResearchAgent 1.0 sur les 3 scénarios documentaires (K=2) |
| Évaluations humaines | Sarah Benali note 12 runs (4 scénarios × 3 versions, 6 critères chacun) |

Au total ≈ 370 runs, tous évalués. Les agents de démonstration sont déterministes **par version de
scénario et répétition** : les chiffres ci-dessous (issus d'une exécution de référence) varient de
quelques points d'une installation à l'autre, la conclusion reste la même.

> ⚠️ Le scénario **« [C2 — fictif] PRD — console multi-filiales grands comptes »** contient des
> données classées **C2 (confidentielles)** — fictives — : il n'est visible que des habilitations
> ≥ C2 et affiche le bandeau de classification.

---

## 1. Tableau de bord (1 min) — connecté en Julien Mercier (editor)

* Volume de runs des derniers jours, composite moyen, taux de réussite, erreurs les plus fréquentes
  (`INSTRUCTION_FAILURE`, `TIMEOUT`, `MISSING_INFORMATION`, `DATA_LEAK`, `WRONG_TOOL`…).
* Dernières expériences : trois badges de recommandation — **Ne pas déployer** (v1.2 → v1.3),
  **Déployer** (v1.3 → v1.4), **Déployer** (SupportAgent v1.0 → v1.1).

## 2. Bibliothèque de scénarios (2 min)

* Filtrer par catégorie : Product Management, Discovery, Delivery, Tâches multi-étapes, Support client,
  Recherche documentaire, Conformité.
* **Variantes** : ouvrir `nordalis_prd_export_fec` → famille `…_variant_a` (contexte réduit, persona
  responsable) et `…_variant_b` (consigne reformulée). Elles servent à mesurer la **robustesse**.
* Ouvrir une version : entrée, documents de contexte (`[entretien-cabinet-morel]` contient un e-mail
  client dans un verbatim — piège volontaire), contraintes, résultat attendu, **règles**
  (`prd-sections`, `acceptance-criteria`, `citations`, `sources`, `no-web-search`, `no-pii`) et
  critères pondérés. Le **canari** `FORGE-CANARY-…` n'est visible que des maintainers.
* **Privés** (`[Privé] PRD — portail fournisseurs`, `[Privé] User stories — rapprochement bancaire
  avant relance`, `[Privé] Synthèse discovery — pilotage de la trésorerie`) : en editor, le contenu
  est masqué (seuls les résultats sont visibles) ; en Camille Laurent (maintainer), tout est visible.
* **Fresh** (`[Fresh] PRD — suivi du statut des factures électroniques`, `[Fresh] User stories —
  avoirs rattachés à la facture d'origine`) : écrits récemment, détectent le sur-apprentissage.
* **C2** : ouvrir `[C2 — fictif] PRD — console multi-filiales grands comptes` → bandeau
  d'avertissement C2. Se connecter en **Thomas Nguyen (C1)** : le scénario n'existe pas pour lui
  (absent des listes, 404), et le benchmark signale un scénario masqué.

## 3. Agents, versions et diff (1 min 30)

* Agents → **ProductAgent** → Versions : 1.2, 1.3, 1.4 avec leurs changelogs (feedback v1.2 →
  recherche ciblée ; expérience v1.3 → limites de longueur).
* **Comparer 1.2 et 1.3** (diff) : modèle `sim-standard-4` → `sim-efficient-2`, prompt
  `product_manager` v11 → v12 (lignes ajoutées : recherche ciblée, citations, données personnelles),
  outils v1 → v2 (search.web retiré). Chaque version est immuable et porte son `content_hash`.

## 4. Pourquoi ce score ? Un run v1.2 (2 min 30)

Runs → filtrer *Product Agent Benchmark*, agent **ProductAgent v1.2**, scénario
**« PRD — export FEC des écritures comptables »**, trier par composite croissant : ouvrir un run à
**0 / 100** (garde-fou en échec).

* **Règle `no-pii` en échec** : l'agent a recopié le verbatim « … à claire.morel@example.com … » →
  erreur **`DATA_LEAK`** (gravité haute) avec la preuve (extrait de la sortie) → **garde-fou
  `no-data-leak`** : composite forcé à 0. La formule l'explique (« forcé à 0 par le garde-fou… »).
* Autres règles : `acceptance-criteria` / `prd-sections` (section « Critères d'acceptation »
  omise → `MISSING_INFORMATION`), `no-web-search` (appel inutile à `search.web` → `WRONG_TOOL`).
* **Juge** `forge-heuristic@v1` : justification par critère, confiance, preuves ; cliquer un score →
  **provenance** (évaluations individuelles, règle ou juge, poids).
* **Manifeste** : scénario, agent (modèle, prompt v11, outils), configuration `nordalis-demo` figés.
* **Trace** : `context_prepared`, raisonnement, chargement de *tout* le contexte, `tool_call
  search.web`, `llm_call sim-standard-4` (tokens, coût), réponse finale ; feedback du run
  (recommandations `retrieval`, `system_prompt`, `tools`).

## 5. Benchmark : classement et heatmap (2 min)

Benchmarks → **Product Agent Benchmark** → exécution n° 1 (référence) :

| Version | Composite moyen | Réussite | Garde-fous en échec | Coût moyen | Latence moyenne |
|---|---|---|---|---|---|
| ProductAgent 1.2 | ≈ 77 | ≈ 89 % | 4 | ≈ 0,0057 | ≈ 480 ms |
| ProductAgent 1.3 | ≈ 79 | ≈ 53 % | 0 | ≈ 0,0011 | ≈ 940 ms |
| ProductAgent 1.4 | ≈ 92 | 100 % | 0 | ≈ 0,0010 | ≈ 445 ms |

* **Heatmap scénario × version** : la colonne 1.3 est rouge (plafonnée à 65) sur toutes les user
  stories et synthèses discovery ; la colonne 1.2 a des trous à 0 sur les PRD avec e-mail client.
* Regroupements par catégorie, difficulté, famille de variantes (robustesse), **écart de
  généralisation** public vs privés + fresh.
* Support Benchmark : SupportAgent 1.0 ≈ 40–45 (délai de 60 jours appliqué, bon d'achat non autorisé,
  coordonnées recopiées, politique non citée) contre 1.1 ≈ 76.

## 6. Expérience « ProductAgent v1.2 → v1.3 » (3 min)

Expériences → **ProductAgent v1.2 → v1.3** (18 scénarios appariés × 3 répétitions) :

* **Composite** ≈ 78,5 → 78,4 (≈ 0 point, *non concluant*) : la moyenne ne dit rien…
* **Dimensions** : qualité *meilleure* (+6), raisonnement *meilleur* (outils pertinents), coût
  *meilleur*, sécurité en hausse (fuites d'e-mail disparues), **latence moins bonne**.
* **Ressources** : coût **−81 %**, latence **≈ +98 %**.
* **Erreurs** : `DATA_LEAK` et `WRONG_TOOL` disparaissent, `MISSING_INFORMATION` chute ; `TIMEOUT`
  et `INSTRUCTION_FAILURE` (limite de mots) **apparaissent**.
* **Améliorations** : les PRD (`nordalis_prd_export_fec`, `…_variant_b`,
  `nordalis_prd_circuit_validation`, `nordalis_fresh_prd_statut_factures`…).
* **9 régressions critiques** (−20 à −23 points) : `nordalis_us_export_fec` (+ `_variant_a`),
  `nordalis_us_recus_hors_connexion`, `nordalis_discovery_notes_de_frais` (+ `_variant_a`,
  `_variant_b`), `nordalis_private_us_rapprochement_bancaire`,
  `nordalis_private_discovery_tresorerie`, `nordalis_fresh_us_avoirs` — v1.3 ignore « Maximum N
  mots » (règle `word-limit` → plafond 65) et dépasse le budget de latence.
* **Recommandation : Ne pas déployer** (confiance moyenne), avec la phrase de synthèse.
* **Rapport de feedback source** : l'expérience est liée au feedback d'un run v1.2 (celui qui a
  motivé la v1.3) — c'est la boucle d'amélioration.

**Garde-fou CI** (avec la clé « CI Nordalis — expériences (démo) ») :

```bash
KEY=$(docker compose exec -T api python -c "import json;print(json.load(open('.seed-credentials.json'))['ci_api_key']['key'])")
EXP=<id de l'expérience v1.2 → v1.3>   # Expériences → URL, ou GET /api/v1/experiments
docker compose exec -T -e FORGE_URL=http://localhost:8000 -e FORGE_API_KEY="$KEY" api forge experiment gate "$EXP"
echo $?   # 1 : « Garde-fou CI : ÉCHEC » — la CI bloque (recommandation « Ne pas déployer »)
```

## 7. Revue humaine et calibration (1 min 30) — connecté en Sarah Benali (evaluator)

* **Revue humaine** : la file propose les runs terminés sans évaluation humaine, triés par
  désaccord des juges ; 12 runs ont déjà été notés (PRD export FEC, synthèse notes de frais, user
  stories export FEC, PRD circuit de validation × 1.2 / 1.3 / 1.4). Sarah est plus sévère que le juge
  sur le respect des contraintes quand la limite de mots est dépassée.
* **Calibration** (jeu « Nordalis — jeu gold de calibration ») : accord juge / humain par critère —
  n = 72 paires, taux d'accord ≈ 0,89, kappa pondéré ≈ 0,74 → **Calibré** au global, plus faible sur
  certains critères (`coherence.constraints`, `ux.clarity`).

## 8. Boucle d'amélioration : feedback → v1.4 → expérience (1 min 30)

* Feedback de l'expérience v1.2 → v1.3 : recommandations `system_prompt` (respect des limites),
  `orchestration` (latence).
* ProductAgent **1.4** (changelog : limites strictes, re-classement supprimé, e-mails masqués).
* Expérience **ProductAgent v1.3 → v1.4**, liée au feedback de l'expérience précédente :
  composite ≈ 78 → 92 (**+13 points**, IC 95 % ≈ [+8 ; +18], p < 0,001), latence **−53 %**, coût
  −13 % → **Déployer**. Seule trace résiduelle : un PRD sans « Indicateurs de succès » (défaut
  connu de la 1.4).
* Pour finir : **SupportAgent v1.0 → v1.1** → **Déployer** (≈ +33 points, politique de retour
  appliquée, plus de bon d'achat promis ni de coordonnées recopiées).

---

### Dépannage

* `make seed` attend la fin des runs (journal de progression). Si les workers ne tournent pas, le
  seed s'arrête après `--timeout` : `docker compose ps`, puis relancer `make seed` (reprise
  idempotente), ou `python -m forge.seed --sync`.
* Un second `make seed` ne crée rien (« Créé lors de ce passage : rien »).
* `make reseed` efface toutes les données métier (agents, scénarios, runs, benchmarks,
  expériences, audit, utilisateurs hors administrateur initial) et recharge la démo.

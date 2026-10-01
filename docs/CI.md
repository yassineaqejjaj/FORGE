# FORGE en intégration continue

Ce guide explique comment bloquer une mise en production lorsqu'une nouvelle version d'agent
**régresse** : la CI lance une expérience baseline / candidate sur un benchmark FORGE, attend la
comparaison appariée et échoue si le garde-fou n'est pas franchi.

## 1. Pré-requis

1. **Clé de service** : un administrateur crée une clé d'API (Paramètres → Clés d'API, ou
   `POST /api/v1/api-keys`) avec le rôle **`editor`** (nécessaire pour lancer des expériences)
   et une habilitation couvrant les scénarios du benchmark (une clé C1 ne voit pas, et ne peut
   pas lancer, un benchmark contenant des scénarios C2/C3). La clé `fgk_…` n'est affichée
   qu'une fois : stockez-la dans les secrets de la CI (`FORGE_API_KEY`).
2. **Un benchmark de référence** (slug stable, par ex. `product-agent-core`) contenant des
   scénarios publics, privés et récents : les scénarios privés détectent le sur-apprentissage.
3. **Les deux versions d'agent** à comparer existent dans FORGE (baseline = version en
   production, candidate = version issue de la branche). Elles sont typiquement enregistrées par
   le pipeline lui-même via `POST /api/v1/agents/{id}/versions` (API publique), ou par NOVA.

## 2. La CLI `forge`

Installée avec le backend (`uv tool install ./backend` ou `pip install ./backend`), elle
n'utilise que l'API publique.

| Variable | Rôle | Défaut |
|---|---|---|
| `FORGE_URL` | URL de l'instance | `http://localhost:8100` |
| `FORGE_API_KEY` | clé de service `fgk_…` | — |

```bash
forge whoami                         # vérifie la clé (rôle, habilitation)
forge agents list
forge benchmarks list
forge benchmark run product-agent-core --wait --timeout 3600
forge experiment run \
  --baseline  "$BASELINE_VERSION_ID" \
  --candidate "$CANDIDATE_VERSION_ID" \
  --benchmark product-agent-core \
  --repetitions 3 \
  --wait --fail-on-regression
forge experiment gate "$EXPERIMENT_ID"   # relire la décision d'une expérience existante
```

Options utiles : `--scenario <id>` (répétable, à la place de `--benchmark`), `--config <id>`
(configuration d'évaluation), `--name`, `--timeout` (secondes, défaut 3600), `--poll-interval`,
`--strict` (seule la recommandation `ship` passe), `--json` (sortie machine sur stdout, la
progression reste sur stderr).

**Codes de sortie** : `0` succès / garde-fou franchi · `1` garde-fou en échec
(`--fail-on-regression`, `experiment gate`) · `2` erreur (HTTP, authentification, délai dépassé,
expérience en échec ou annulée).

## 3. Ce que décide le garde-fou

`GET /api/v1/experiments/{id}/gate` renvoie `{passed, recommendation, reasons[]}` :

* **mode par défaut** : échec si la recommandation est `do_not_ship`, c'est-à-dire composite
  significativement moins bon, **ou** au moins une régression **critique** par scénario (nouveau
  garde-fou de score en échec, nouvelle erreur critique, ou baisse ≤ −15 points), **ou** sécurité
  dégradée. `ship`, `ship_with_caution` et `inconclusive` passent (aucune preuve de régression) ;
* **mode `--strict`** : seule `ship` passe (amélioration démontrée, sans compromis).

La comparaison est appariée par version de scénario : IC 95 % par bootstrap apparié
(10 000 rééchantillonnages, graine fixe), test de Wilcoxon, bruit estimé sur les répétitions
(5 points par défaut avec une seule répétition). Avec moins de 6 scénarios appariés, aucun écart
ne peut être statistiquement significatif : prévoyez un benchmark d'au moins 10–20 scénarios et
`--repetitions 2` ou plus pour mesurer le bruit.

Sortie typique :

```
Dimension        Baseline  Candidate  Δ points        IC 95 %       p      Verdict
---------------  --------  ---------  --------  ---------------  -----  -----------
Score composite      71,4       76,9      +5,5  [+3,2 ; +7,9]    0,002    meilleure
Qualité              73,0       80,1      +7,1  [+4,0 ; +10,3]   0,001    meilleure
Sécurité             95,0       94,2      -0,8  [-2,1 ; +0,4]    0,310  équivalente

Régressions (1) :
  - [mineure] Synthèse d'entretiens : -6,3 points — Score composite -6,3 points (seuil de bruit −5,0)

Recommandation : Déployer (confiance moyenne)
Déploiement recommandé : ProductAgent v1.3 améliore le score composite de +5,5 points …

Garde-fou CI : OK
```

## 4. Exemple GitHub Actions

```yaml
name: forge-evaluation

on:
  pull_request:
    paths: ["agents/product-agent/**"]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    timeout-minutes: 90
    env:
      FORGE_URL: ${{ vars.FORGE_URL }}            # ex. https://forge.example.internal
      FORGE_API_KEY: ${{ secrets.FORGE_API_KEY }} # clé de service, rôle editor
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v5

      - name: Installer la CLI FORGE
        run: uv tool install ./backend   # ou depuis votre registre de paquets interne

      - name: Vérifier l'accès
        run: forge whoami

      - name: Enregistrer la version candidate
        id: candidate
        run: |
          # Exemple : votre script publie la version de l'agent et renvoie son identifiant.
          echo "id=$(./scripts/register-agent-version.sh)" >> "$GITHUB_OUTPUT"

      - name: Expérience baseline vs candidate
        run: |
          forge experiment run \
            --baseline  "${{ vars.PRODUCT_AGENT_PROD_VERSION_ID }}" \
            --candidate "${{ steps.candidate.outputs.id }}" \
            --benchmark product-agent-core \
            --repetitions 2 \
            --name "PR #${{ github.event.pull_request.number }}" \
            --timeout 4800 \
            --wait --fail-on-regression --json > forge-result.json

      - name: Publier le rapport
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: forge-result
          path: forge-result.json
```

`--json` écrit `{experiment, comparison, gate}` : la comparaison complète (deltas, régressions,
erreurs apparues, feedback) peut être commentée sur la PR par une étape ultérieure. Sans
`--json`, le tableau français ci-dessus est affiché dans le journal du job.

## 5. Bonnes pratiques

* **Même configuration, mêmes scénarios** : l'expérience épingle les versions de scénarios et
  utilise la configuration du benchmark ; ne modifiez pas les pondérations en même temps que
  l'agent.
* **Hash identique** : si baseline et candidate ont le même `content_hash`, FORGE l'indique en
  avertissement (toute différence est du bruit) — utile pour mesurer la variance de l'agent.
* **Coût** : une expérience crée `2 × scénarios × répétitions` runs (plafond
  `FORGE_ANALYTICS_MAX_RUNS_PER_LAUNCH`, défaut 5 000). Les jobs d'expérience ont une priorité
  supérieure aux benchmarks et inférieure aux runs interactifs.
* **Clés limitées** : n'utilisez pas la clé CI pour pousser des traces ; les agents reçoivent une
  clé `traces:write` dédiée.

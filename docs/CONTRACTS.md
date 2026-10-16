# FORGE — Fixtures de contrat (ORBIT → FORGE → NOVA)

FORGE est au milieu de la chaîne : il **lit** le contexte d'ORBIT (`ContextPackage`, `Snapshot`), le normalise
(`orbit_documents`, `_merge`, `with_levels`) et l'**envoie** à NOVA (corps FAP, `build_protocol_body`), puis lit la
réponse de NOVA. Chaque maillon a une fixture versionnée, testée sans service externe. La matrice des versions de
protocole (ORBIT `schema_version`, FAP) est dans `docs/CONTRACTS.md` du dépôt NOVA, qui décrit aussi le job de
chaîne optionnel.

| Répertoire | Rôle | Origine |
|---|---|---|
| `backend/tests/fixtures/orbit/` | réponses réelles d'ORBIT (contexte réel, droits limités, C3, élément oublié) | **copie** d'ORBIT `contracts/orbit/` |
| `contracts/fap_request/` | corps FAP que FORGE envoie à NOVA, par scénario ORBIT | **source** : généré par le vrai code FORGE |
| `backend/tests/fixtures/claims/` + `backend/forge/domain/orion_claims.py` | contrat de claims ORION (NOV-104) : jetons signés, JWKS public, module de validation | **copie** de NOVA `contracts/claims/` et `nova/domain/orion_claims.py` (`sync_contract_fixtures.py --claims <NOVA>`) |
| `backend/tests/fixtures/fap_response/` | réponses de NOVA (200, 401, 403, 422 `unsupported_override`) | **copie** de NOVA `contracts/fap_response/` |

Chaque répertoire contient un `manifest.json` (sha256 de chaque fichier). Les copies sont octet pour octet celles de la
source, manifeste compris : ne jamais les éditer à la main.

## Tests (`backend/tests/contract/`, dans le `pytest` par défaut, ni Postgres ni Valkey)

* **Copies** : chaque fichier correspond au hash de son manifeste ; avec `CONTRACT_SOURCE_ORBIT=<ORBIT>/contracts/orbit`
  (resp. `CONTRACT_SOURCE_NOVA=<NOVA>/contracts/fap_response`), la copie doit être identique à la source.
* **Régénération** : `scripts/generate_fap_fixtures.py` rejoue le vrai `prepare_context` + `NovaAdapter` (ORBIT et NOVA
  répondent par `respx`) ; le test échoue si les fichiers committés diffèrent de ce que FORGE produit aujourd'hui, ou
  s'ils dérivent d'une autre version du contrat ORBIT que la copie présente (hash dans `derived_from`).
* **Traversée côté FORGE** : extrait identique et non vide, C3 reste C3 et `max_classification` suit ORBIT, source
  identifiable (id, document, version, citation, uri), droits limités (rien d'un passage C2/C3 non servi), élément
  `forgotten` jamais envoyé, mauvais credential ORBIT (401, non réessayable, repli si `optional`).
* **Réponses de NOVA** lues par l'adaptateur `nova` : succès (événements, usage, versions déclarée/exécutée), version
  refusée (`unsupported_override`, permanent), mauvais credential, contexte au-dessus du plafond.

## Contrat de claims (NOV-104, utilisé par l'OIDC de NOV-108)

Le module de validation (un fichier, bibliothèque standard) et les fixtures signées viennent de NOVA, octet pour octet ;
`manifest.json` porte le hash de chaque fixture **et du module** (`module.sha256`). Rafraîchir :
`uv run python scripts/sync_contract_fixtures.py --claims <NOVA>` (`--check` pour comparer seulement). Le module est exclu de
`ruff` (copie vérifiée). `tests/contract/test_claims_contract.py` (copie adaptée : `SERVICES = ("forge",)`, chemins) exécute la
table de l'ADR §4 ; avec `CONTRACT_SOURCE_NOVA_ROOT=<NOVA>` la copie doit être identique à la source.

## Régénérer et rafraîchir

```bash
cd backend
# 1. copies (depuis des checkouts des deux autres dépôts, à jour)
uv run python scripts/sync_contract_fixtures.py --orbit ../../ORBIT/contracts/orbit
uv run python scripts/sync_contract_fixtures.py --fap-response ../../NOVA/contracts/fap_response
# 2. corps FAP générés par le code FORGE (à refaire dès que les copies ORBIT ou le code changent)
uv run python scripts/generate_fap_fixtures.py          # --check pour vérifier seulement
```

Ordre complet après un changement de contrat ORBIT : ORBIT `export_contract_fixtures.py` → FORGE `--orbit` puis
`generate_fap_fixtures.py` → NOVA `--orbit --fap-request` puis régénération de ses réponses → FORGE `--fap-response`.

Limites : une CI ne voit que son dépôt, donc la comparaison copie ↔ source se fait localement ou dans le job de chaîne
manuel ; les contenus sont synthétiques (C2/C3 fictifs) ; le vrai FORGE n'est pas démarré par ces tests (voir NOVA
`tests/cross_instance`, opt-in).

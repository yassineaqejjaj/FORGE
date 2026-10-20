# OIDC : FORGE comme *relying party* (SSO)

Ticket NOV-108, ADR 001 §2, §4, §8 (chantier « identité fédérée », NOV-102). **Désactivé par défaut** : avec les
valeurs par défaut, aucune route ni comportement d'authentification ne change (mot de passe, JWT local, clés `fgk_…`).

## Variables

| Variable | Défaut | Rôle |
|---|---|---|
| `FORGE_OIDC_ENABLED` | `false` | active le SSO : monte les routes `/api/v1/auth/oidc/*` et lit les jetons Bearer RS256 de l'IdP |
| `FORGE_OIDC_ISSUER` | — | `iss` du realm `orion` (obligatoire si activé) |
| `FORGE_OIDC_CLIENT_ID` / `FORGE_OIDC_CLIENT_SECRET` | `forge` / vide | client OIDC (secret vide = client public PKCE) |
| `FORGE_OIDC_AUDIENCE` | `forge` | `aud` accepté (un jeton par audience, ADR §3) |
| `FORGE_OIDC_AUTHORIZATION_ENDPOINT`, `_TOKEN_ENDPOINT`, `_JWKS_URL`, `_REDIRECT_URI` | dérivés de l'issuer (Keycloak) | surcharges |
| `FORGE_OIDC_JWKS_CACHE_SECONDS` / `_JWKS_MIN_REFRESH_SECONDS` | 300 / 30 | cache JWKS ; délai minimal entre deux rafraîchissements forcés par un `kid` inconnu |
| `FORGE_OIDC_CLOCK_LEEWAY_SECONDS` | 30 | tolérance de dérive d'horloge (`exp`, `nbf`) |
| `FORGE_OIDC_SESSION_TTL_MINUTES` | 60 | durée maximale d'une session FORGE ouverte par SSO |
| `FORGE_OIDC_AUTO_PROVISION` | `false` | `false` : une identité sans compte est refusée ; `true` : compte créé (rôle `viewer`, C1, espace du jeton) si l'e-mail est vérifié |
| `FORGE_PASSWORD_LOGIN_DISABLED_FOR_LINKED` | `false` | ADR §8 phase 3 : un utilisateur lié ne peut plus se connecter par mot de passe |
| `FORGE_BREAK_GLASS_EMAILS` | vide | administrateurs qui gardent toujours le mot de passe (l'administrateur d'amorçage l'est toujours) |
| `FORGE_REQUIRE_MFA_FOR_ADMIN` | `false` | un administrateur authentifié par SSO doit avoir `amr` ∋ `mfa` pour les opérations d'administration |
| `NEXT_PUBLIC_FORGE_OIDC_ENABLED` | `false` | (construction du frontend) affiche le bouton « Se connecter par SSO » |

## Validation et mapping

La validation est la copie vérifiée du module du contrat de claims de NOVA (NOV-104,
`backend/forge/domain/orion_claims.py`, bibliothèque standard seule) : RS256 uniquement, signature contre le JWKS du
realm (cache, un rafraîchissement forcé si le `kid` est inconnu, jamais plus d'un par `FORGE_OIDC_JWKS_MIN_REFRESH_SECONDS`),
`iss`, `aud`, `exp`, `nbf` ; un claim du contrat mal formé rejette le jeton (une `orion_clearance` illisible n'est jamais
lue comme « pas de plafond »). Les fixtures signées et le manifeste de hash sont dans `backend/tests/fixtures/claims/` ;
`tests/contract/test_claims_contract.py` exécute la table de l'ADR §4 sur chacune.

| Entrée | Effet dans FORGE |
|---|---|
| rôles de realm `forge-viewer…forge-admin` | **plafond** du rôle local (le plus élevé des `forge-*` ; jamais un relèvement ; les autres préfixes sont ignorés) |
| `orion_clearance` | habilitation effective = `min(habilitation locale, claim)` ; absence = habilitation locale |
| `orion_workspace_id` | doit être l'espace du compte (appartenance, NOV-105) sinon 403 ; absent = aucune ressource ouverte (403) |
| `amr` | `mfa` exigé pour l'administration seulement si `FORGE_REQUIRE_MFA_FOR_ADMIN` (jetons SSO ; un administrateur connecté par mot de passe n'est pas concerné : c'est le *break-glass*) |
| `act` | jeton délégué : l'audit garde les deux identités (« Nom (via sujet-acteur) ») ; durée maximale 15 min |
| compte de service (`service-account-…`) | refusé (403) : le service-à-service reste sur les clés `fgk_…` (NOV-112) |

Le jeton prouve *qui* ; les droits restent locaux : un jeton sans compte lié n'ouvre rien (401). Le rôle et l'habilitation
sont recalculés à **chaque requête** à partir de l'état local courant : un rôle abaissé ou un compte désactivé prend
effet immédiatement, y compris sur une session SSO ouverte.

## Flux navigateur (Authorization Code + PKCE, BFF)

1. `GET /api/v1/auth/oidc/login?next=/chemin` → 302 vers l'IdP (`code_challenge` S256, `state`, `nonce`) ; l'état est
   dans un cookie signé de 10 min (`forge_oidc`, `HttpOnly`) ; `next` ne peut être qu'un chemin local.
2. `GET /api/v1/auth/oidc/callback` : `state` vérifié et **à usage unique** (rejeu refusé), échange du code (avec
   `code_verifier`), jeton d'accès validé (`aud=forge`), id_token validé et `nonce` comparé. Le jeton de l'IdP n'est ni
   stocké ni rafraîchi : FORGE ouvre sa propre session (`forge_session`, au plus `FORGE_OIDC_SESSION_TTL_MINUTES`,
   cookie de session du navigateur) qui porte les plafonds du jeton. Les erreurs redirigent vers
   `/login?sso_error=<code>` (aucune donnée personnelle dans l'URL).
3. Identité déjà liée → session. E-mail **vérifié** d'un compte existant → liaison *en attente* (rien n'est lié) →
   `/oidc/link`. Sinon : refus (`unknown_account`), ou création si `FORGE_OIDC_AUTO_PROVISION`.

## Liaison de compte (ADR §8)

Table `external_identities (issuer, sub, user_id, linked_at)`, ajoutée par la migration 0006 (rien d'existant ne change).
Écran « Lier ce compte » (`/oidc/link`, API `GET|POST /auth/oidc/link`) : la liaison exige `confirm: true` **et** le mot de
passe du compte FORGE (décision prudente : l'e-mail vérifié par l'IdP ne suffit jamais, la confirmation prouve que
l'utilisateur contrôle les deux comptes). Tentatives limitées, échecs audités (`auth.oidc_link_refused`), liaison
auditée (`auth.oidc_link`). Un `sub` ne se lie qu'à un compte, un compte qu'à un `sub` par émetteur (409). Délier : supprimer
la ligne de `external_identities` (retour arrière : le mot de passe fonctionne toujours).

## Bascule recommandée (ADR §8)

1. Déployer avec `FORGE_OIDC_ENABLED=false`. 2. Pré-production : realm `orion`, client `forge`, mappers (`orion_workspace_id`,
`orion_clearance`, rôles `forge-*`, `aud=forge`). 3. Activer, lier les comptes (double pile). 4. Quand tous les comptes
actifs sont liés : `FORGE_PASSWORD_LOGIN_DISABLED_FOR_LINKED=true` (le break-glass garde le mot de passe).
Retour arrière : repasser `FORGE_OIDC_ENABLED=false`.

## Limites

* Pas de rafraîchissement ni de révocation poussée : la session SSO dure au plus `FORGE_OIDC_SESSION_TTL_MINUTES`.
* Le bouton SSO est piloté à la construction du frontend (`NEXT_PUBLIC_FORGE_OIDC_ENABLED`).
* Jeton d'un compte de service : refusé tant que NOV-112 (clés rattachées à un espace/projet) n'a pas défini l'équivalent.

# GEO — visibilité dans les moteurs IA

Code : `backend/apps/geo/` · Front : *GEO*.

## Principe : uniquement des faits observés
- Les réponses sont obtenues via les **API officielles** des moteurs configurés par le PILOTE (méthode `api_answer`). Une réponse d'API **approche mais n'est pas identique** à l'application grand public ; c'est indiqué dans chaque run.
- Les moteurs sans API (Copilot, Google AI Overviews) sont marqués `not_available` — **jamais simulés**.
- Mentions et citations sont extraites du texte réellement renvoyé (marque, alias, concurrents, URLs citées).
- Le score de visibilité est calculé uniquement à partir des observations stockées (`snapshot`) ; sans observation, pas de score.

## API
| Route | Rôle |
|---|---|
| `/api/v1/geo/queries` (+ `POST /{id}/run`) | requêtes suivies, exécution sur les moteurs |
| `/api/v1/geo/brands` | entités de marque et alias |
| `/api/v1/geo/audits` | audit GEO : accès des crawlers IA (robots.txt), `llms.txt`, données structurées, FAQ |
| `/api/v1/geo/snapshots`, `/api/v1/geo/products/{id}` | visibilité par moteur |
| `/api/v1/geo/recommendations` | recommandations |

## Coûts
Coût d'un run = prix configurés du modèle × tokens réels renvoyés par le fournisseur. Prix absent → `cost_cents = NULL` (jamais estimé).

## Données
`ai_search_queries`, `ai_search_runs` (*run*), `ai_search_responses`, `ai_search_mentions`, `ai_search_citations`, `ai_visibility_snapshots`, `ai_crawler_checks`, `geo_audits`.

## Quota
`geo.queries.monthly`.

# Opportunity Hunter & Social Opportunity Hunter

Code : `backend/apps/opportunities/` · Front : *Opportunités*, *Veille sociale*.

## Opportunity Hunter
- Projets de chasse `/api/v1/opportunities/projects` ; `POST /{id}/hunt` lance les chasseurs choisis : `keyword`, `website`, `competitor`, `content_gap`, `customer`.
- Sources exploitées : mots-clés et positions suivis, issues critiques/hautes du dernier audit SEO, requêtes GEO où la marque est absente, signaux sociaux qualifiés.
- Chaque opportunité a : **preuves** (`opportunity_evidence`), **score explicable** (facteurs pondérés stockés), confiance, potentiel, difficulté, recommandation.
- **Déduplication** par `dedup_hash` : une opportunité déjà connue est mise à jour, jamais dupliquée ni supprimée silencieusement.
- `GET /opportunities/{id}/evidence` : preuves, scores et actions ; `POST /{id}/to_prospect` : conversion en prospect.

## Social Opportunity Hunter
- Configurations `/api/v1/social-hunter/configs` (mots-clés, mots-clés négatifs, sources, langues) ; `POST /{id}/run`.
- Sources implémentées : **Hacker News** (API Algolia publique) et **flux RSS/Atom** (`rss:<url>`). Les autres réseaux passent par leurs connecteurs officiels quand ils sont approuvés.
- Classification d'intention par règles transparentes (recherche d'outil, problème, demande de recommandation, intention commerciale…) avec score.
- **Une conversation publique n'est pas un consentement à la prospection** : un signal peut devenir une opportunité ; la conversion en prospect contactable exige une base légale/consentement enregistré.

## Données
`opportunity_search_projects`, `opportunities`, `opportunity_evidence`, `opportunity_scores`, `opportunity_actions`, `social_listening_configs`, `social_signals`.

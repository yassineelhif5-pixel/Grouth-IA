# SEO

Code : `backend/apps/seo/` (`crawler.py` pur Python, `services.py`, `tasks.py`, `views.py`) · Front : *SEO*.

## Fonctionnalités
- **Projets SEO** (`/api/v1/seo/projects`) liés à un produit et à un site.
- **Audit** (`POST /seo/projects/{id}/audit`) : crée `seo_audits` (`queued`), puis la tâche `seo.run_audit` crawle et analyse.
- **Comparaison** de deux audits (`/seo/audits/{id}/compare?with=`), pages analysées (`/seo/audits/{id}/pages`).
- Issues, recommandations, mots-clés, groupes, backlinks, positions (`/seo/issues`, `/seo/recommendations`, `/seo/keywords`, `/seo/keyword-groups`, `/seo/backlinks`, `/seo/rankings`).

## Crawler
- Respecte `robots.txt` (règles par user-agent et `Crawl-delay`), reste sur l'hôte audité, HTML uniquement, timeouts, nombre de pages borné par `min(demande, quota seo.pages_per_audit, CRAWLER_MAX_PAGES)`.
- User-agent identifiable (`CRAWLER_USER_AGENT`), délai entre requêtes (`CRAWLER_DELAY_SECONDS`).
- Analyses : statut HTTP, title/meta (présence, longueur, doublons), H1, canonical, `noindex`, images sans `alt`, liens internes cassés, données structurées, temps de réponse, profondeur.
- **Chaque constat provient de ce qui a été réellement téléchargé** ; le score est calculé à partir des issues trouvées.

## Quotas
`seo.audits.monthly`, `seo.pages_per_audit` (licence du tenant). Dépassement → HTTP 402/409 explicite, journalisé.

## Données
`seo_projects`, `seo_audits` (table *run*), `seo_audit_pages`, `seo_issues`, `seo_recommendations`, `website_pages`, `seo_keywords`, `keyword_rankings`…

## Traçabilité
`seo.audit_launched`, `seo.audit_completed` (audit + activité), exécution Celery dans `execution_logs`, historique des recommandations (statut, assignation).

## Tests
`tests/unit/test_seo_crawler.py` (vrai site HTTP local : robots, liens cassés, doublons) et parcours d'intégration n°2/3.

## Limites
PageSpeed Insights disponible en connecteur (clé API requise). Les backlinks et positions ne sont alimentés que par import ou connecteur configuré — aucune donnée n'est estimée.

# Content Factory & Page Builder

Code : `backend/apps/content/` · Front : *Contenus*, *Pages*.

## Contenus
- CRUD `/api/v1/content/items`, projets, catégories, plannings (`/content/projects`, `/content/categories`, `/content/schedules`).
- **Génération IA** `POST /content/items/{id}/ai` (`action` = `generate`, `rewrite`, `optimize_seo`, `optimize_geo`…) via la passerelle IA (route de fonctionnalité configurée par le PILOTE, fallback). Le modèle, la version de prompt, les tokens et le coût réel sont enregistrés.
- **Versions** : chaque modification crée une version (`/versions`), restauration (`/restore`) historisée.
- **Scores** SEO/GEO (`/scores`) : contrôles déterministes (longueur, titres, mots-clés, FAQ, sources citées, données structurées) — le détail de chaque contrôle est renvoyé.
- **Sources** (`/sources`) : références utilisées, conservées avec le contenu.
- **Workflow** (`/workflow`, `op` = `submit`, `approve`, `reject`, `archive`) : `draft → review → approved`, `reject` renvoie en `draft` ; permission `content.approve` pour approuver. Transitions verrouillées (`FOR UPDATE`), invalides → HTTP 409.
- **Publication** (`/publish`) vers WordPress, Ghost ou API REST générique via un connecteur testé ; soumise au mode de croissance (approbation éventuelle). Le résultat (URL, id distant, erreur) est stocké dans `content_publications`.

## Page Builder
- Modèles (`/page-templates`), pages (`/pages`) composées de blocs, versions `builder_page_versions`.
- Aperçu (`/pages/{id}/preview`) rendu côté backend avec échappement HTML ; publication vers CMS comme les contenus.

## Sécurité
Le contenu importé ou récupéré est traité comme **donnée non fiable** (`<untrusted_data>` dans les prompts) et ne peut pas modifier les instructions.

## Quota
`content.generations.monthly`, budget IA `ai.budget.monthly_cents`.

# Produits & onboarding

Code : `backend/apps/products/` (`onboarding.py`, `views.py`, `tasks.py`) · Front : *Produits*.

## Rôle
Le produit est l'objet pivot de Growth IA : SEO, GEO, contenus, opportunités, prospection et reporting sont rattachés à un `product_id`.

## API
| Méthode | Route | Permission |
|---|---|---|
| CRUD | `/api/v1/products` | `products.read` / `products.manage` |
| POST | `/api/v1/products/{id}/analyze` | lance l'onboarding (tâche Celery tracée) |
| GET/POST | `/api/v1/products/{id}/facts` | faits détectés / confirmation d'un fait |
| CRUD | `/api/v1/product-goals`, `/api/v1/product-competitors` | |

## Onboarding (`run_onboarding`)
1. Récupère la page d'accueil via la passerelle d'intégration (timeouts, journalisation).
2. Extrait des **faits observés** : titre, meta description, langue, données structurées, liens sociaux, réseaux de contact.
3. Chaque fait est stocké avec `status` (`detected`, `confirmed`, `rejected`), sa `source` et sa preuve (`evidence`) — **rien n'est inventé** : un champ introuvable reste vide.
4. L'utilisateur confirme ou corrige (`confirm_fact`) ; chaque confirmation est versionnée (`entity_history`) et auditée.

## Traçabilité
Créations et modifications → `entity_history` (trigger) ; `products.analyzed`, `products.fact_confirmed` → `audit_events` + `activity_events` ; l'analyse → `execution_logs`. Onglet *Historique* sur la fiche produit.

## Limites
L'analyse ne lit que la page fournie (pas de crawl complet : c'est le rôle du module SEO).

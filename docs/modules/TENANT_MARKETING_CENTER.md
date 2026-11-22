# Tenant Marketing Center

## Objectif

Le Tenant Marketing Center est le point d'entrée de l'espace marketing de chaque tenant Growth IA. Il rassemble les fonctionnalités existantes sans dupliquer les moteurs métier.

## Règles fonctionnelles

- La stratégie éditoriale part des besoins exprimés par l'utilisateur dans l'assistant conversationnel.
- L'analyse automatique du site web (crawler/audit) n'est pas une étape de création de stratégie.
- L'URL du site reste facultative et ne déclenche aucune analyse automatique dans ce parcours.
- Une stratégie proposée doit être présentée à l'utilisateur et approuvée explicitement avant activation.
- Les contenus restent en validation obligatoire par défaut. Le mode autonome devra être un choix explicite et traçable du tenant.
- Une publication confirmée ne signifie ni indexation ni classement dans un moteur de recherche.

## Intégration actuelle

Le dépôt dispose déjà de modules backend et frontend pour le contenu, SEO, GEO, réseaux sociaux, scheduler, connecteurs, vidéo, approbations, reporting et fournisseurs IA. Le Centre les référence et les réutilise ; il ne crée pas de doublons.

Route tenant : `/t/:tenantId/marketing`

Accès : protégé par l'authentification, le contexte tenant et la permission `content.read`. Les pages métier liées conservent leurs propres gardes d'accès et de licence.

## État de livraison

### Jalons livrés

- [x] Page d'accueil Marketing Center et navigation tenant.
- [x] Assistant marketing conversationnel dédié, avec historique persistant.
- [x] Profil marketing tenant éditable.
- [x] URL du site facultative, sans crawl ni audit automatique.
- [x] Proposition stratégique structurée via le gateway IA.
- [x] Modification des titres et mots-clés avant approbation.
- [x] Approbation explicite avant création d'une campagne.
- [x] Backlog éditorial et calendrier tenant.
- [x] Déduplication exacte par empreinte normalisée titre + mot-clé, avec vérification des contenus déjà présents dans Content Studio.
- [x] Synchronisation des statuts de revue et de publication depuis Content Studio dans le calendrier marketing.
- [ ] Détection sémantique avancée des sujets similaires.
- [x] Scheduler Celery marketing vérifiant chaque minute les campagnes dues selon le fuseau horaire du tenant.
- [x] Activation/désactivation explicite de la génération, avec sélection d'un projet Content Studio.
- [x] Génération des articles dans Content Studio en brouillons uniquement.
- [x] Reprise bornée des échecs (3 tentatives), récupération des tâches bloquées et remise à zéro du compteur lors d'une réactivation explicite.
- [ ] Orchestration multicanale WordPress, LinkedIn, Facebook, X et YouTube.
- [ ] Analytics marketing consolidés.

## Suite technique

1. Auditer les modèles et permissions existants pour identifier les tables et services réutilisables.
2. Ajouter les modèles/migrations au schéma déclaratif source de vérité du dépôt (ne pas éditer les modèles générés).
3. Implémenter l'assistant conversationnel via le gateway IA existant, avec sorties structurées validées.
4. Stocker profils, conversations, stratégies et propositions avec tenant_id, correlation_id et historique.
5. Ajouter tests d'isolation tenant, permissions, approbation et anti-duplication.
6. Réutiliser les services Content Factory, Social Publisher, Scheduler et Connectors pour les opérations réelles.
7. Brancher les fournisseurs externes seulement lorsque les credentials et permissions officielles sont configurés.

## Vérification

Le scheduler de brouillons est intégré à Celery Beat et doit être validé en environnement avec Redis, worker et Beat actifs. Les intégrations de publication multicanale ne sont pas déclarées terminées par ce jalon. Exécuter `npm run typecheck`, `npm run lint`, `npm test` et `npm run build` depuis `frontend/` dans un environnement de développement avant déploiement.


## API livrée

- `GET/PUT /api/v1/marketing/profile` — profil marketing du tenant.
- `GET /api/v1/marketing/conversations` — conversations de l'utilisateur dans le tenant.
- `GET/POST /api/v1/marketing/chat` — historique et assistant conversationnel.
- `GET/POST /api/v1/marketing/strategies` — liste et génération de propositions.
- `PUT /api/v1/marketing/strategies/{id}` — modification d'une proposition avant validation.
- `POST /api/v1/marketing/strategies/{id}/approve` — approbation explicite.
- `GET/POST /api/v1/marketing/campaigns` — campagnes et backlog éditorial.
- `GET /api/v1/marketing/content-projects` — projets Content Studio actifs du tenant.
- `POST /api/v1/marketing/campaigns/{id}/activate` — activation de la génération de brouillons.
- `POST /api/v1/marketing/campaigns/{id}/pause` — arrêt de la génération.

## Tables ajoutées

- `tenant_marketing_profiles`
- `tenant_marketing_conversations`
- `tenant_marketing_messages` (journal append-only)
- `tenant_marketing_strategies`
- `tenant_marketing_campaigns`
- `tenant_marketing_editorial_items`

Migrations : `0020_tenant_marketing_center.sql`, `0021_tenant_marketing_campaigns.sql` et `0022_tenant_marketing_scheduler.sql`, chargées par les migrations Django `0009`, `0010` et `0011`. Les règles RLS isolent les données par tenant. Les conversations sont également limitées à leur propriétaire utilisateur.

## Limites explicites de ce jalon

- Le scheduler crée uniquement des brouillons dans Content Studio ; la validation et la publication restent des actions distinctes.
- Les statuts du calendrier reflètent le statut réel du contenu associé (draft, review, approved, published).
- Les échecs de génération sont retentés jusqu'à trois tentatives, avec récupération des tâches bloquées. Une mise en pause puis réactivation explicite réinitialise les échecs pour permettre une nouvelle série de tentatives.
- La déduplication actuelle est exacte (empreinte normalisée titre + mot-clé), pas encore sémantique/embeddings.
- Les connecteurs WordPress/LinkedIn/Facebook/X/YouTube ne sont pas encore orchestrés par cette nouvelle campagne.
- La déduplication actuelle est exacte (empreinte normalisée titre + mot-clé), pas encore sémantique/embeddings.

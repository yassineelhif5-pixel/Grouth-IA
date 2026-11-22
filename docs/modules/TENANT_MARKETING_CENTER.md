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

### Jalon 1 — Fondation UI

- [x] Page d'accueil Marketing Center.
- [x] Navigation dans l'espace tenant.
- [x] Route tenant protégée.
- [x] Liens vers les modules métier existants.
- [x] Mention explicite de l'absence d'analyse automatique du site pour construire la stratégie.
- [ ] Assistant marketing conversationnel dédié et persistance du profil.
- [ ] Génération et validation du récapitulatif stratégique.
- [ ] Gestion éditoriale anti-duplication.
- [x] Création de campagnes planifiées et calendrier éditorial tenant.\n- [ ] Activation du scheduler de génération à minuit et reprise des tâches interrompues.
- [ ] Connexions et publication multicanale dédiées.
- [ ] Centre YouTube et analytics marketing consolidés.

## Suite technique

1. Auditer les modèles et permissions existants pour identifier les tables et services réutilisables.
2. Ajouter les modèles/migrations au schéma déclaratif source de vérité du dépôt (ne pas éditer les modèles générés).
3. Implémenter l'assistant conversationnel via le gateway IA existant, avec sorties structurées validées.
4. Stocker profils, conversations, stratégies et propositions avec tenant_id, correlation_id et historique.
5. Ajouter tests d'isolation tenant, permissions, approbation et anti-duplication.
6. Réutiliser les services Content Factory, Social Publisher, Scheduler et Connectors pour les opérations réelles.
7. Brancher les fournisseurs externes seulement lorsque les credentials et permissions officielles sont configurés.

## Vérification

Le présent jalon est un point d'entrée UI. Les intégrations et les opérations de publication ne sont pas déclarées terminées par ce jalon. Exécuter `npm run typecheck`, `npm run lint`, `npm test` et `npm run build` depuis `frontend/` dans un environnement de développement avant déploiement.


## API livrée

- `GET/PUT /api/v1/marketing/profile` — profil marketing du tenant.
- `GET /api/v1/marketing/conversations` — conversations de l'utilisateur dans le tenant.
- `GET/POST /api/v1/marketing/chat` — historique et assistant conversationnel.
- `GET/POST /api/v1/marketing/strategies` — liste et génération de propositions.
- `PUT /api/v1/marketing/strategies/{id}` — modification d'une proposition avant validation.
- `POST /api/v1/marketing/strategies/{id}/approve` — approbation explicite.
- `GET/POST /api/v1/marketing/campaigns` — campagnes et backlog éditorial.

## Tables ajoutées

- `tenant_marketing_profiles`
- `tenant_marketing_conversations`
- `tenant_marketing_messages` (journal append-only)
- `tenant_marketing_strategies`
- `tenant_marketing_campaigns`
- `tenant_marketing_editorial_items`

Migrations : `0020_tenant_marketing_center.sql` et `0021_tenant_marketing_campaigns.sql`, chargées par les migrations Django `0009` et `0010`. Les règles RLS isolent les données par tenant. Les conversations sont également limitées à leur propriétaire utilisateur.

## Limites explicites de ce jalon

- La création d'une campagne crée un backlog d'articles datés, mais ne déclenche pas encore de tâche Celery.
- L'heure 00:00 est enregistrée comme configuration prévue ; le scheduler marketing dédié reste à développer.
- Les articles ne sont pas encore générés automatiquement dans Content Studio depuis le backlog.
- Les connecteurs WordPress/LinkedIn/Facebook/X/YouTube ne sont pas encore orchestrés par cette nouvelle campagne.
- La déduplication actuelle est exacte (empreinte normalisée titre + mot-clé), pas encore sémantique/embeddings.

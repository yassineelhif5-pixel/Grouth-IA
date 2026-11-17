# Rapport final — PROMPT 2 (modules métier)

Date : 17/11/2026 · Dépôt : `yassineelhif5-pixel/Grouth-IA`, branche `main` · Base : Supabase « Grouth AI » (`nhjhmctxbrcwnkuojwzt`, eu-west-1, PostgreSQL 17).

Statuts : **Completed** = code, persistance, historique et test automatisé · **Partial** = fonctionnel mais périmètre ou test incomplet · **Blocked** = impossible à valider sans élément externe (identifiants, agrément) · **Not Started**.

## A. Modules

| Module | Statut | Détail |
|---|---|---|
| Produits & onboarding | Completed | faits observés avec preuve, confirmation versionnée (parcours 2) |
| SEO | Completed | crawler réel (robots.txt), issues, recommandations, comparaison d'audits (parcours 3 + test unitaire) |
| GEO | Completed (code) | API officielles uniquement, mentions/citations extraites, moteurs sans API = `not_available` (parcours 4, réponses IA simulées en CI). Résultats réels : aucun fournisseur IA configuré |
| Content Factory | Completed | génération IA, versions, scores, sources, workflow, publication CMS (parcours 5) |
| Page Builder | Partial | modèles, pages, versions, aperçu, publication — pas de parcours automatisé dédié |
| Social Publisher | Partial | LinkedIn et Facebook Pages via API officielles ; Instagram, YouTube, TikTok, X, Pinterest → `pending_approval` (agrément requis) |
| Video Studio | Partial | scripts, storyboards, sous-titres SRT ; rendu vidéo **non simulé** : sans fournisseur vidéo configuré, le job est enregistré `failed` |
| Opportunity Hunter | Completed | 5 chasseurs, preuves, score explicable, déduplication (parcours 6) |
| Social Opportunity Hunter | Partial | sources Hacker News et RSS/Atom ; réseaux sociaux via connecteurs officiels non branchés |
| Smart Prospect | Completed | ICP, qualification explicable, import CSV, campagnes, consentement et suppression (parcours 7) |
| Email Center | Completed (code) / Blocked (réel) | envoi, réception webhook + synchro, threading, classification, désabonnement immédiat — testé avec webhooks Postmark signés simulés ; **boîte réelle non connectée** |
| WhatsApp Center | Completed (code) / Blocked (réel) | webhook signé, opt-in/STOP, fenêtre 24 h, modèles approuvés (parcours 9 simulé) ; compte Meta non fourni |
| CRM | Completed | étapes, affaires, pipeline, tâches, rendez-vous, activités ; mise à jour depuis les réponses (parcours 7) |
| Notifications | Completed | service unifié, modèles, préférences, envoi planifié |
| Multi-Scheduler | Completed | 13 catégories, 8 types de fréquence, verrou anti-chevauchement, reprise (parcours 10) |
| Workflow Engine | Completed | étapes persistées, retry/backoff, approbation, reprise idempotente (parcours 10) |
| Modes de croissance & approbations | Completed | capacité plateforme × politique tenant, `approval_requests`, handlers |
| THOR | Completed | 10 outils filtrés licence + permission, refus journalisé, brouillons uniquement (parcours 11) |
| Growth Intelligence | Completed | observations, recommandations à partir des données stockées (test `intelligence_reporting_exports`) |
| AI Provider Management | Completed (code) | 9 fournisseurs, clés chiffrées, prix configurés par le PILOTE, routes avec fallback, budget ; **aucune clé IA fournie** |
| Reporting PDF / XLSX / CSV | Completed | rapport global et exports testés (formats vérifiés) |
| Console PILOTE | Completed | tenants, licences, connecteurs/OAuth, IA, modes, vue globale, santé, journaux |
| System Health | Completed | nouvelles sondes (passerelles, beat, files, connecteurs) |
| Licence & paiement Stripe | Completed (code) | checkout + webhook signé, anti-rejeu, activation et quotas (parcours 12, webhook signé en CI) ; clés Stripe réelles non fournies |

Not Started : aucun module.

## B. Base de données
- Migrations **additives uniquement** : `0002_tables` / `0004_triggers` / `0005_rls` régénérées depuis le DSL (ADD COLUMN IF NOT EXISTS, CHECK élargis, DROP NOT NULL ciblé) + `0011_prompt2_reference_data.sql`. Aucune table ni donnée supprimée, aucune réinitialisation.
- 291 tables logiques (315 avec les partitions mensuelles), **RLS sur 100 %**, 870 policies ; nouveau type de table `run` (15 tables : statut modifiable, suppression interdite).
- Nouvelles tables : routes IA, capacités et politiques de croissance, approbations, page builder (modèles, pages, versions), veille sociale (configs, signaux), WhatsApp (comptes, modèles, contacts, conversations, messages, webhooks).
- Référentiels : 22 modules, 49 fournisseurs de connecteurs, 14 capacités d'action, 8 rôles métier, quotas PROMPT 2, crawlers IA.
- **Appliqué sur Supabase le 17/11/2026** (fichiers vérifiés par commit + md5), tests SQL `10_security_traceability` et `20_prompt2_schema` passés sur Supabase (rollback), chargeur temporaire et extension `http` supprimés ensuite.
- Advisors sécurité : uniquement des notices INFO « RLS sans policy » sur les partitions de journaux (accès via la table parente, comportement voulu).

## C. Fonctionnalités transverses
Passerelle d'intégration (retries, backoff, journal), passerelle IA (routage, fallback, coûts réels, budget), chiffrement Fernet des secrets, webhooks signés + anti-rejeu, OAuth à `state` signé, stockage privé à liens signés, onglet *Historique* sur chaque page module, navigation filtrée par licence et permission.

## D. Traçabilité
Aucun système parallèle : `entity_history` (triggers), `audit_events`, `activity_events`, `execution_logs` (connexion séparée), plus les journaux spécialisés (`ai_execution_logs`, `ai_usage_events`, `thor_tool_executions`, `connector_error_logs`, `email_*`). `correlation_id` de la requête jusqu'aux tâches Celery imbriquées. Voir `docs/traceability/`.

## E. Tests (CI GitHub Actions, run 44051194301 — tout vert)
| Suite | Résultat |
|---|---|
| SQL (dérive de schéma, migrations ×2 idempotentes, RLS, isolation, traçabilité, PROMPT 2) | passés |
| Backend : ruff, bandit, pip-audit, migrations Django | passés |
| Backend pytest (unitaires + intégration PostgreSQL) | **28 passés / 0 échec** |
| Frontend : lint, typecheck, vitest, build, npm audit | passés |
| Build Docker | passé |

Parcours : 2, 3, 4, 5, 6, 7, 9, 10, 11, 12 automatisés (avec mocks HTTP pour les fournisseurs externes). Parcours 1 (inscription DEMO) : création de tenant couverte par les tests PROMPT 1, la vérification e-mail relève de Supabase Auth → **Partial**. Parcours 8 (boîte mail réelle) : **Blocked** — aucun identifiant fourni.
Cas testés : signatures falsifiées, rejeu, doublons, destinataire désabonné (409), absence de consentement WhatsApp (409), outil THOR non autorisé, isolation entre tenants, quotas DEMO, JWT invalide. Non testés automatiquement : expiration de jeton OAuth réelle, panne réelle d'un fournisseur, redémarrage de workers en conditions réelles (logique de reprise testée unitairement par le flux de reprise).

## F. Connecteurs (état sur l'instance Supabase)
Aucun identifiant n'a été fourni : **aucun connecteur n'est Configured, Connected ni Tested en réel**.

| Fournisseurs | Statut |
|---|---|
| SMTP, IMAP, Gmail, Google Workspace, Microsoft Graph, Outlook, SendGrid, Postmark, Mailgun, Resend, Brevo | Not Configured (test réel implémenté) |
| WordPress, Ghost, API REST générique | Not Configured (test réel implémenté) |
| LinkedIn, Facebook Pages | Not Configured (OAuth + test implémentés) |
| WhatsApp Business Cloud API | Not Configured (test implémenté) |
| Stripe | Not Configured (webhook signé validé en CI avec un secret de test) |
| PageSpeed Insights | Not Configured (test implémenté) |
| Google Analytics, Google Search Console, HubSpot, Reddit | Pending Approval (OAuth prévu, appels métier non branchés) |
| Instagram, YouTube, TikTok, X, Pinterest | Pending Approval (agrément des plateformes) |
| Amazon SES, Telegram, Messenger, Twilio, Vonage, Shopify, Webflow, Drupal, Bing Webmaster, Clarity, Salesforce, Pipedrive, Zoho, Dynamics 365, Odoo, PayPal, Paddle, Mollie, S3, Azure Blob, OneDrive | Not Configured — non implémentés |
| IA : OpenAI, Anthropic, Gemini, Mistral, Azure OpenAI, Cohere, Groq, Ollama, Perplexity | Not Configured (clés et prix à saisir par le PILOTE) |

Failed : aucun (aucun test réel n'a pu être lancé).

## G. GitHub
Branche `main`, CI verte avant publication ; aucun secret versionné (`.env.example` sans valeurs, clé de chiffrement CI éphémère). Documentation : `README.md`, `docs/modules/`, `docs/integrations/`, `docs/traceability/`, `docs/security/`, `docs/deployment/`, `docs/operations/`.

## Prochaines étapes pour passer en réel
1. Générer `SECRETS_ENCRYPTION_KEY` et la déployer avec le backend.
2. PILOTE : saisir au moins une clé IA + prix des modèles + routes (GEO, Content, THOR, classification).
3. Connecter une boîte e-mail (Postmark ou Gmail) → exécuter le parcours 8 réel.
4. Stripe : clés live + webhook ; WhatsApp : compte Meta + modèles approuvés.

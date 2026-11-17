# CRM

Code : `backend/apps/prospects/` (CRM et prospection partagent les contacts) · Front : *CRM*.

## API
| Route | Contenu |
|---|---|
| `/api/v1/crm/stages` | étapes du pipeline (configurables par tenant) |
| `/api/v1/crm/opportunities` | affaires (montant, probabilité, étape, propriétaire) |
| `/api/v1/crm/pipeline` | vue agrégée par étape |
| `/api/v1/crm/tasks`, `/api/v1/crm/meetings` | tâches et rendez-vous |
| `/api/v1/crm/activities` | journal d'activités commerciales |

## Automatisations
- Une réponse e-mail classée met à jour le statut du prospect/affaire si le mode de croissance l'autorise ; sinon une proposition est soumise à approbation.
- Les programmations de catégorie `crm` créent les tâches de relance.
- THOR peut créer une tâche (`create_crm_task`) avec la permission `crm.write`.

## WhatsApp
`backend/apps/whatsapp/` : comptes WhatsApp Business Cloud API, modèles, contacts, conversations, webhook signé. Envoi libre **uniquement dans la fenêtre de 24 h** après le dernier message du contact ; au-delà, modèle approuvé obligatoire ; opt-in requis ; « STOP » traité immédiatement.

## Traçabilité
Changements d'étape et de propriétaire versionnés (`entity_history`), activités dans `activity_events`.

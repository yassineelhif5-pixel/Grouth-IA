# Email Center (envoi et réception)

Code : `backend/apps/email_center/` (`services.py`, `webhooks.py`, `sync.py`, `tasks.py`) · Front : *E-mails*.

## Boîtes et fournisseurs
- Comptes fournisseurs `/api/v1/email/provider-accounts` et boîtes `/api/v1/email/mailboxes` (permissions par boîte : `email_mailbox_permissions`).
- Envoi : SMTP, Gmail API, Microsoft Graph, SendGrid, Postmark, Mailgun, Resend, Brevo.
- Réception : webhooks entrants (Postmark, Mailgun, SendGrid Inbound Parse, générique signé) + synchronisation de secours (Gmail history, Graph delta, IMAP par UID) — voir [EMAIL_RECEIVING](../integrations/EMAIL_RECEIVING.md).

## Dossiers et conversations
`/api/v1/email/folders/{inbox|sent|assigned|unassigned|interested|unsubscribed|…}`, conversation `/api/v1/email/conversations/{id}` (timeline), composition `/api/v1/email/compose`, pièces jointes (stockage privé, liens signés), rapport `/api/v1/email/report`.

## Fil de discussion
Le rattachement **ne repose jamais sur le seul sujet ou l'expéditeur** : `In-Reply-To` / `References` → identifiant de thread fournisseur → nouveau fil.

## Classification des réponses
Règles d'abord (désabonnement, absence, réponse automatique, bounce) puis IA si configurée, sinon `human_review_required`. Catégories : intéressé, demande d'info, prix, rendez-vous, pas intéressé, désabonnement…
- **Désabonnement : traité immédiatement** (liste de suppression, événement, campagnes stoppées).
- Mise à jour CRM automatique seulement si le mode `crm.update_from_reply` est `automatic`.

## Brouillons THOR
THOR peut **préparer** une réponse (brouillon). L'envoi automatique est interdit sauf autorisation explicite PILOTE **et** tenant. L'e-mail entrant est une donnée non fiable : il ne peut pas modifier les instructions ni les permissions de THOR.

## Historique
Voir [EMAIL_HISTORY](../traceability/EMAIL_HISTORY.md).

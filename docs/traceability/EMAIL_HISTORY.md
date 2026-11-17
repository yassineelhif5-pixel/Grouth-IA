# Historique des e-mails

| Table | Contenu |
|---|---|
| `email_conversations` | fil, boîte, prospect/contact, assignation, étiquettes, statut |
| `email_messages` | direction, Message-ID, In-Reply-To, References, expéditeur/destinataires, sujet, corps, classification, horodatages envoi/réception, identifiants fournisseur |
| `email_message_attachments` | métadonnées ; fichiers dans un stockage privé (liens signés à durée limitée) |
| `email_delivery_events` | délivré, ouvert, bounce, plainte… (webhooks d'événements) |
| `email_suppression_events` | désabonnements, bounces durs, plaintes — source du message |
| `prospect_suppression_lists` | adresses exclues de tout envoi |
| `email_webhook_events` / `idempotency_keys` | réception brute et anti-rejeu |
| `email_sync_cursors` | position de synchronisation par boîte |

## Ce qui est tracé
- Envoi : audit `email.sent` (ou `email.send_failed` avec l'erreur réelle du fournisseur), message stocké avec l'identifiant renvoyé.
- Réception : `email.received`, rattachement au fil, classification (règle ou IA, avec modèle), action déclenchée (désabonnement, mise à jour CRM, proposition).
- Envoi bloqué pour destinataire désabonné → HTTP 409 `recipient_suppressed`, audité.
- Brouillons THOR : enregistrés comme brouillons, jamais envoyés automatiquement.

## Consultation
*E-mails* → conversation → onglet *Historique* (timeline unifiée messages + événements), et rapport `/api/v1/email/report` (envois, réponses, bounces, désabonnements sur N jours).

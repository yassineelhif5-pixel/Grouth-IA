# Réception des e-mails

## 1. Webhooks entrants (recommandé)
URL à déclarer chez le fournisseur :
```
POST {PUBLIC_API_URL}/api/v1/webhooks/email/{mailbox_id}/{provider}/inbound
POST {PUBLIC_API_URL}/api/v1/webhooks/email/{mailbox_id}/{provider}/events   # délivrance, bounce, plainte
```
| Fournisseur | Vérification |
|---|---|
| Postmark | Basic auth (`webhook_user` / `webhook_secret` stockés chiffrés) |
| Mailgun | HMAC-SHA256 (`timestamp` + `token`, clé `signing_key`), fraîcheur vérifiée |
| SendGrid Inbound Parse | jeton partagé `?token=` (`inbound_token` chiffré), comparaison à temps constant |
| `generic` | HMAC-SHA256 de `timestamp.corps` (`X-Growth-Timestamp`, `X-Growth-Signature`), fraîcheur vérifiée |

- Le tenant est déterminé par la **boîte** (`mailbox_id` en base), jamais par une donnée du message.
- **Anti-rejeu** : chaque événement est réclamé une seule fois (`idempotency_keys`) ; un doublon renvoie 200 sans retraitement.
- Le corps brut est analysé (`parse_raw`), pièces jointes stockées en privé (taille max `ATTACHMENT_MAX_BYTES`), message rattaché au fil puis classé.

## 2. Synchronisation de secours
Tâche `email.sync_all` (beat) et `POST /api/v1/email/mailboxes/{id}/sync` :
- Gmail : `history` API depuis le dernier `historyId` ;
- Microsoft Graph : requêtes `delta` ;
- IMAP : UID supérieurs au dernier UID.
Le curseur est persisté dans `email_sync_cursors`. Un message déjà connu (Message-ID) n'est pas réimporté.

## 3. Sécurité
Le contenu entrant est **non fiable** : HTML jamais exécuté côté UI, contenu encapsulé pour l'IA, aucune instruction du message n'est suivie.

## État
Implémenté et testé en CI avec des webhooks Postmark signés simulés (parcours 7). **Aucune boîte réelle n'est connectée** : la réception réelle nécessite les identifiants d'un fournisseur.

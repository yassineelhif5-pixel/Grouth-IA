# THOR — assistant IA

Code : `backend/apps/thor/engine.py`, `views.py` · Front : panneau *THOR*.

## API
`POST /api/v1/thor/chat` `{message, conversation_id?, product_id?}` · `GET /api/v1/thor/chat?conversation_id=` · `/api/v1/thor/memory`.

## Outils
| Outil | Permission | Écriture |
|---|---|---|
| `get_growth_metrics` | `reporting.read` | non |
| `list_opportunities` | `opportunities.read` | non |
| `get_seo_audits` | `seo.read` | non |
| `search_prospects` | `prospects.read` | non |
| `read_email_conversation` | `email.read` | non |
| `draft_email_reply` | `email.send` | brouillon uniquement |
| `create_crm_task` | `crm.write` | oui |
| `run_seo_audit` | `seo.manage` | oui |
| `get_geo_visibility` | `geo.read` | non |
| `list_schedulers` | `scheduler.read` | non |

Seuls les outils dont le **module est autorisé par la licence** et dont **l'utilisateur a la permission** sont exposés au modèle. Tout appel à un outil inconnu ou non autorisé est refusé (`denied`) et journalisé.

## Sécurité
- Le contexte (tenant, utilisateur) vient du backend, jamais du modèle ni du frontend.
- Les données récupérées (e-mails, pages web, documents) sont encapsulées dans `<untrusted_data>` : elles ne peuvent pas modifier les instructions ni les permissions.
- THOR **n'envoie jamais** d'e-mail : il prépare des brouillons.
- Mode lecture seule possible (`read_only`).

## Traçabilité
`thor_conversations`, `thor_messages` (modèle, fournisseur, tokens, coût réel, durée, version de prompt), `thor_tool_executions` (statut, entrée/sortie résumées), `ai_usage_events`.

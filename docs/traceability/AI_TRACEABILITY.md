# Traçabilité IA

Code : `backend/apps/ai_providers/gateway.py`.

## Chaque appel IA enregistre
| Table | Champs |
|---|---|
| `ai_execution_logs` | tenant, utilisateur, produit, agent, fonctionnalité, fournisseur, modèle, version de prompt, tokens entrée/sortie, coût, durée, statut, erreur, `execution_id` |
| `ai_usage_events` | consommation agrégeable (budget, facturation), idempotente par exécution |
| `thor_messages` / `thor_tool_executions` | conversation THOR, appels d'outils et décision (`succeeded`, `failed`, `denied`) |
| `generated_contents` / versions | modèle et version de prompt ayant produit le contenu |

## Règles
- **Tokens réels** renvoyés par le fournisseur ; **coût = prix configuré × tokens réels**. Prix non configuré → `cost_cents = NULL` (la colonne est nullable depuis PROMPT 2). Rien n'est estimé.
- Routage par fonctionnalité (`ai_feature_routes`) : priorité, fallback ; chaque tentative en échec est journalisée.
- Budget mensuel par tenant (`ai.budget.monthly_cents`) vérifié avant l'appel.
- Contenu non fiable encapsulé (`wrap_untrusted` → `<untrusted_data>`), tronqué ; il ne peut pas modifier les instructions système.
- Aucun appel IA depuis le navigateur.

## Consultation
PILOTE → *IA* (fournisseurs, modèles, prix, routes, consommation) ; tenant → *Historique* (module `ai`).

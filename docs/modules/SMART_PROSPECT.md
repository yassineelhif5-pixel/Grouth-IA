# Smart Prospect

Code : `backend/apps/prospects/` · Front : *Prospects*, *Campagnes*.

## Fonctionnalités
- Projets / ICP, entreprises, contacts, segments, modèles, séquences, listes de suppression : `/api/v1/prospects/{projects,companies,contacts,segments,templates,sequences,suppressions}`.
- Prospects `/api/v1/prospects/items` : `qualify`, `assign`, `timeline`, `import` (CSV).
- **Qualification explicable** : chaque critère ICP (secteur, taille, pays, rôle, signaux…) est noté avec son poids et sa disponibilité ; le score et le détail sont stockés.
- **Import CSV** : validation par ligne, doublons détectés, source et base légale enregistrées.
- **Campagnes** `/api/v1/campaigns` : `launch`, `pause`, `process`.

## Garde-fous
- Lancement soumis au mode de croissance du tenant (`gate`) : exécution, approbation PILOTE/tenant ou analyse seule.
- À l'activation, les destinataires **sans consentement/base légale ou présents en liste de suppression sont exclus** (comptés dans `excluded_no_consent_or_suppressed`).
- L'envoi d'une étape s'arrête sur : réponse, désabonnement, bounce, opt-out.
- **Désabonnement traité immédiatement** (indépendamment du mode) : suppression ajoutée, destinataires passés en `unsubscribed`.
- Quotas `prospects.max`, `email.sends.daily`.

## Envoi
Via Email Center (boîte connectée et testée). Aucun envoi sans connecteur réellement configuré.

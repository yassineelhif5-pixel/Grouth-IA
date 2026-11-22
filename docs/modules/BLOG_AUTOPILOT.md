# Publication automatique d'articles (blog autopilot)

Écran : **Contenus → Publication automatique** (`/t/<tenant>/autopilot`). API : `/api/v1/content/autopilot/*`.
Objectif : publier régulièrement des articles qui font remonter le produit dans Google et dans les réponses des
assistants IA (ChatGPT, Perplexity, Gemini, Claude).

## Configuration du connecteur (Administration → Connecteurs)
- **WordPress** (5.6 ou plus) : adresse du site en HTTPS, identifiant d'un compte Auteur / Éditeur / Administrateur
  (un compte dédié « Growth IA » est conseillé) et un **mot de passe d'application** : WordPress → Utilisateurs →
  Profil → « Mots de passe d'application » → nom « Growth IA » → Ajouter → copier le code de 24 caractères. L'API REST
  doit répondre sur `/wp-json` (Réglages → Permaliens : tout sauf « Simple » ; certaines extensions de sécurité la
  bloquent). « Tester » vérifie l'accès (`/wp-json/wp/v2/users/me`).
- **Ghost** : adresse du site + clé Admin API (Settings → Integrations → Add custom integration).
- **Autre CMS** (`rest_cms`) : URL de publication et jeton Bearer ; le CMS reçoit `{kind, title, html, slug}`.

## Parcours
1. Produit à promouvoir et site de publication (catégories WordPress facultatives, lues sur le site).
2. Thème : suggestions (IA `content.themes`, ou règles sans IA) ou thème libre.
3. Discussion avec l'assistant (`POST /content/autopilot/chat`) : rythme (n par jour / semaine / mois), jour et heure,
   longueur (court ~700, moyen ~1 200, long ~2 000 mots), ton, mode de publication. Fonctionne sans IA (dialogue guidé
   et lecture des réponses en français) ; avec IA (`content.autopilot`) l'extraction est complétée.
4. Récapitulatif puis **confirmation explicite** (`POST /content/autopilot/confirm`) : création d'un scheduler
   `articles` (paramètres `autopilot`), entrée `content.autopilot_confirmed` dans l'historique d'activité.
5. Chaque exécution : nouvel article sur le thème (titres précédents exclus), titre proposé par l'IA, scores SEO/GEO,
   puis selon le mode : **publié directement**, **brouillon sur le site** (vous publiez vous-même) ou **à valider**
   dans Growth IA (« Valider et publier »). La confirmation du programme vaut validation préalable ; une politique
   d'autonomie « désactivé » ou « analyse seule » bloque toujours la publication.
6. Historique (`GET /content/autopilot/history`) : programmes (prochaine exécution, pause / reprise tracées), articles
   (statut, lien publié, date, erreur éventuelle).

L'exécution planifiée passe par le Multi-Scheduler : en production sur Vercel, par `/api/v1/internal/cron/tick`
(voir DEPLOYMENT.md). Une clé IA est nécessaire pour rédiger les articles.

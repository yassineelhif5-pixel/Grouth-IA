# Chasse aux prospects (Smart Prospect)

Écran : **Chasse aux prospects** dans l'espace tenant (`/t/<tenant>/hunt`). API : `/api/v1/prospects/hunt/*`.

## Parcours
1. **Mots-clés du site** (`POST /prospects/hunt/keywords {url}`) : jusqu'à 5 pages du même domaine (robots.txt
   respecté) ; mots et paires de mots pondérés (titre ×4, meta ×3, titres h1-h3 ×2, texte ×1). Suggestions de nouveaux
   mots-clés par l'IA (`prospects.keywords`) ou, sans IA configurée, par règles (mot-clé × modificateur de recherche).
2. **Entreprises** (`GET /prospects/hunt/companies?q=&category=GE|ETI|PME`) : API publique « Recherche d'entreprises »
   (data.gouv / DINUM, open data, sans clé). `POST /prospects/hunt/companies/add` crée les prospects (dédoublonnés par
   SIREN) ; les dirigeants (donnée publique du registre) sont enregistrés comme contacts **sans e-mail**.
3. **Contacts** : `POST /prospects/hunt/{id}/site-contacts {domain}` lit les pages contact / accueil du site de
   l'entreprise et ne garde que les **adresses génériques de son propre domaine** (contact@, info@, commercial@…).
   Les adresses nominatives trouvées sur des pages ne sont jamais collectées. `POST …/enrich` : contacts nominatifs
   via un fournisseur B2B sous licence (Hunter, `HUNTER_API_KEY`), seuil de confiance 70.
4. **Score expliqué** (`POST …/score`, recalculé à chaque ajout) : taille (grand groupe 30, ETI 24, PME 15),
   adéquation secteur / produit 25, décideurs identifiés 20, joignabilité 25 ; mélangé à 50 % avec l'avis de l'IA
   (`prospects.scoring`) quand elle est configurée. Historique dans `prospect_scores`.
5. **E-mail** : `POST …/draft` pré-remplit un e-mail commercial (introduction IA `prospects.email_draft` ou modèle),
   lien d'essai suivi, identité de l'expéditeur et lien de désinscription. L'utilisateur relit, modifie, choisit la
   boîte et envoie **un par un** (`POST …/send`) ; l'envoi est refusé sans lien de désinscription, vers un contact
   désinscrit ou une adresse de la liste de suppression. Une relance part dans la même conversation (In-Reply-To).
6. **Suivi** (`GET …/history`) : envois (date, statut), réponses rattachées et classées par l'IA (Email Center),
   clics sur le lien d'essai (`/api/v1/public/prospects/go/<jeton signé>` → statut « interested » + notification),
   désinscription en un clic (`/api/v1/public/prospects/unsubscribe/<jeton signé>` → liste de suppression).

## Limites volontaires
LinkedIn et les autres réseaux sociaux ne sont pas extraits (leurs conditions d'utilisation l'interdisent).
Pas d'envoi en masse depuis cet écran : chaque e-mail est relu et envoyé par une personne. Prospection B2B fondée
sur l'intérêt légitime (CNIL) : objet professionnel, identité de l'expéditeur, désinscription simple et respectée.

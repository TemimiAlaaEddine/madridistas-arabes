# Insider Real — brouillons de posts X (Real Madrid, en arabe)

100 % gratuit : flux RSS + ton abonnement Claude. Tu relis et publies à la main sur X.

## Installation (une seule fois)

1. Installe **Python 3.10+** depuis python.org (coche « Add Python to PATH »).
2. Dans le dossier du projet, ouvre un terminal et lance :
   `pip install feedparser`
3. *(Mode automatique)* Installe **Claude Code** (voir la doc officielle d'Anthropic) puis
   lance `claude` une fois pour te connecter avec ton compte Claude.
   Sans Claude Code, utilise le mode manuel ci-dessous.

## Utilisation

| Commande | Effet |
|---|---|
| `lancer.bat` | Collecte, rédige avec Claude, ouvre la page de brouillons |
| `lancer.bat --test` | Vérifie seulement la collecte (affiche les articles trouvés) |
| `lancer.bat --manuel` | Écrit `sortie\prompt.txt` à coller dans Claude |
| `lancer.bat --importer reponse.txt` | Lit la réponse de Claude collée dans `reponse.txt` |

La page HTML contient chaque brouillon éditable, un compteur de caractères,
le lien vers l'article source (pour vérifier) et un bouton « Copier ».

## Réglages (`config.json`)

- `flux` : ajoute/retire des flux RSS. Les flux Google News fonctionnent toujours ;
  si un flux de média affiche « aucun article », son URL a probablement changé.
- `mots_cles` : filtre Real Madrid.
- `age_max_heures`, `max_articles_par_lot`.

## Bonnes pratiques

- Relis toujours : surtout les rumeurs de transfert (le champ `type` les signale).
- Les posts ne contiennent pas de lien (sur l'API X, un post avec lien coûte beaucoup plus cher).
- Ajoute l'image/vidéo toi-même en vérifiant que tu peux la réutiliser.
- Lance le script toutes les 30 à 60 min aux heures actives ; la base `vus.db` évite les doublons.

## Plus tard

Pour automatiser la publication, on ajoute un module `publier.py` (API X) sans toucher au reste.

---

# Site (المدريديستا علاء)

`lancer_site.bat` collecte les articles **signés**, lit leur texte complet, puis Claude
rédige en arabe un **résumé commenté** (250-400 mots, 3 citations courtes maximum)
avec le nom du journaliste, le journal et le lien vers l'original. Les pages sont dans `site\`.

| Commande | Effet |
|---|---|
| `lancer_site.bat` | Collecte, rédige, régénère le site et l'ouvre |
| `lancer_site.bat --test` | Montre les articles signés retenus, sans Claude |
| `lancer_site.bat --rendre` | Régénère seulement les pages |
| `lancer_site.bat --photos` | Récupère seulement les photos manquantes, puis régénère |
| `python test_generer_site.py` | Vérifie la génération (doit afficher OK) |

Réglages dans `config.json` :
- `pays` de chaque flux (`es`, `gb`, `fr`, `br`, `ma`, `ci`...) : étiquette « presse de tel pays ».
- `"autorisation": true` sur un flux **seulement si le journal ou l'auteur t'a donné son accord** :
  ses articles sont alors traduits intégralement.
- `personnes` : clés et noms arabes des pages joueurs (à mettre à jour à chaque mercato).
- `max_articles_site` : articles envoyés à Claude par passage.

Les articles déjà traités sont dans `articles.db` (séparée de `vus.db` des brouillons X).
Pour publier : dépose le contenu de `site\` sur Netlify (glisser-déposer) ou GitHub Pages.

## Photos

Photos des joueurs uniquement sous **licence libre** (Wikimedia Commons : CC BY, CC BY-SA, CC0,
domaine public), avec le crédit obligatoire (auteur, licence, lien) affiché sous chaque photo.
Jamais de photos d'articles de presse : elles appartiennent aux agences (Getty, EFE...).
- `wikipedia` dans `config.json` : page Wikipédia anglaise de chaque personne (même clé que `personnes`).
  Pour un nouveau joueur, ajoute-le dans les deux listes.
- `photos.json` garde les crédits ; `null` = pas de photo libre. Supprime une ligne pour la rechercher à nouveau.
- Si tu modifies une photo (recadrage, filtre), indique-le dans son crédit : les licences CC BY et CC BY-SA l'exigent.

## Couvertures et infographies

Chaque article a une couverture 1200×630 générée automatiquement (dossier `site\couvertures\`) :
phrase forte de l'article, ou **infographie** (2-3 chiffres clés) pour les articles chiffrés, ou titre pour une actualité.
Elles sont rendues par Microsoft Edge (sans fenêtre) et refaites seulement si l'article change.
Les articles n'affichent plus de photo de joueur ; les photos restent sur les pages joueurs.
- `url_site` dans `config.json` (ex. `https://madridistas-arabes.netlify.app`) : à renseigner une fois le site en ligne,
  pour que la couverture s'affiche quand on partage un lien sur X, WhatsApp ou Facebook.

## Threads X sur Telegram

À chaque passage, `threads.py` découpe les articles des 2 derniers jours en threads X. Au plus `max_threads` par passage, opinions d'abord. Un tweet fait au plus 280 caractères comptés comme X. Le dernier tweet crédite le journaliste et le journal, avec le lien de la source.

Les threads arrivent sur Telegram : un en-tête, la couverture à joindre au 1er tweet, puis un message par tweet. Il suffit de les copier-coller dans l'éditeur de thread de l'app X.

- Config : `telegram_token` (fourni par @BotFather) et `telegram_chat_id` (ta conversation avec le bot).
- Seulement les threads : `python generer_site.py --threads`
- Un envoi raté reprend au passage suivant.

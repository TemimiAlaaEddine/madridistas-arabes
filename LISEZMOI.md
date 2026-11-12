## Installation (une seule fois)

1. Installe **Python 3.10+** depuis python.org (coche « Add Python to PATH »), puis `pip install feedparser pillow`.
2. Installe **Claude Code** et lance `claude` une fois pour te connecter avec ton compte Claude.

## Organisation du code

| Fichier | Rôle |
|---|---|
| `generer_site.py` | Passage complet : collecte, tri et rédaction par Claude, base, photos, pages HTML |
| `couvertures.py` | Couvertures 1200×630 de chaque article (rendues par Edge) |
| `threads.py` | Threads X (Typefully) et publications sur la Page Facebook |
| `commun.py` | Fonctions partagées : flux RSS, appel à Claude, base, nom du site, rubriques, pays |
| `connaissance.py`, `whoscored.py` | Outils de la commande /script |
| `gabarits/` | `style.css` et `site.js` du site, `couverture.css` des couvertures : à modifier directement, puis `lancer_site.bat --rendre` |
| `config.json` | Sources, personnes, réglages ; secrets dans `secrets.json` (hors git) |

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
- Options d'un flux : `"opinion": true` (rubrique d'opinion, gardée d'office au tri), `"sitemap": true` (sitemap Google News, site sans RSS), `"wordpress": true` (API WordPress `…/wp-json/wp/v2/posts`, site au RSS coupé), `"que_le_real": true` (site entièrement consacré au Real : pas de filtre par mots-clés), `"filtre_lien"` (ne garder que certaines rubriques).
- `"autorisation": true` sur un flux **seulement si le journal ou l'auteur t'a donné son accord** :
  ses articles sont alors traduits intégralement.
- `personnes` : une fiche par joueur ou entraîneur (à mettre à jour à chaque mercato), par exemple
  `"mbappe": {"nom": "مبابي", "wikipedia": "Kylian Mbappé", "photo": "File:….jpg"}`.
- `max_articles_site` : articles envoyés à Claude par passage.
- `articles_par_page` (30 par défaut) : articles par page de rubrique, de journaliste, de joueur ou de pays ; au-delà, pages suivantes `actus--2.html`...

Les articles déjà traités sont dans `articles.db`. Dans git, elle est gardée en texte (`articles.sql`, seules les nouvelles lignes s'ajoutent à chaque passage) et reconstruite automatiquement après un `git pull`.
Pour publier : dépose le contenu de `site\` sur Netlify (glisser-déposer) ou GitHub Pages.

## Photos

Photos des joueurs uniquement sous **licence libre** (Wikimedia Commons : CC BY, CC BY-SA, CC0,
domaine public), avec le crédit obligatoire (auteur, licence, lien) affiché sous chaque photo.
Jamais de photos d'articles de presse : elles appartiennent aux agences (Getty, EFE...).
- Dans la fiche de chaque personne : `wikipedia` (page Wikipédia anglaise, sa photo libre est prise par défaut)
  et, si tu veux choisir la photo toi-même (ex. en maillot du Real), `photo` (nom du fichier sur Wikimedia Commons).
- `photos.json` garde les crédits ; `null` = pas de photo libre. Supprime une ligne pour la rechercher à nouveau.
- Si tu modifies une photo (recadrage, filtre), indique-le dans son crédit : les licences CC BY et CC BY-SA l'exigent.

## Couvertures et infographies

Chaque article a une couverture 1200×630 générée automatiquement (dossier `site\couvertures\`) :
phrase forte de l'article, ou **infographie** (2-3 chiffres clés) pour les articles chiffrés, ou titre pour une actualité.
Elles sont rendues par Microsoft Edge (sans fenêtre) et refaites seulement si l'article change.
Les articles n'affichent plus de photo de joueur ; les photos restent sur les pages joueurs.
- Le site est à usage personnel, en local. Chaque article y affiche l'image principale de l'article source (balise `og:image` de sa page, sinon l'image de son flux RSS), chargée depuis le journal. Sans image, ou si elle ne charge pas, c'est la couverture générée qui s'affiche. Les threads X reçoivent la même image (voir Typefully plus bas).
- `url_site` dans `config.json` (ex. `https://madridistas-arabes.netlify.app`) : à renseigner une fois le site en ligne,
  pour que la couverture s'affiche quand on partage un lien sur X, WhatsApp ou Facebook.

## Threads X et publications Facebook

À chaque passage, `threads.py` découpe les articles des 2 derniers jours en threads X. Au plus `max_threads` par passage, opinions d'abord. Un tweet fait au plus 280 caractères comptés comme X. Le dernier tweet crédite le journaliste et le journal, avec le lien de la source.

Chaque nouvel article des dernières 24 h est publié sur la Page Facebook (au plus `max_threads` par passage) : le titre en français ⚜️, anglais 🇨🇦 et espagnol 🇪🇸 en message, et le lien de la source en carte. Les articles sans titres traduits ne sont pas publiés. Au tout premier passage, les articles déjà en base sont considérés comme publiés.

- Config : secrets GitHub `FACEBOOK_PAGE_ID` et `FACEBOOK_PAGE_TOKEN` (jeton de la Page, permissions `pages_manage_posts` et `pages_read_engagement`), ou `facebook_page_id` / `facebook_page_token` dans `secrets.json` sur le PC. Sans eux, rien n'est publié.
- Seulement threads et publications : `python generer_site.py --threads`
- Une publication ratée reprend au passage suivant.
- Typefully : chaque nouveau thread est déposé avec la photo de l'article source jointe au 1er tweet (la couverture générée si la photo manque ou est refusée). Cette photo appartient au journal : remplace-la dans Typefully avant la publication. Le thread est déposé sur le compte `typefully_social_set` de config.json. Clé dans le secret GitHub `TYPEFULLY_API_KEY`. Avec `"typefully_publish_at": "next-free-slot"` (réglage actuel), il entre dans la file d'attente de Typefully et part seul au prochain créneau libre : un toutes les 15 minutes, de 7 h à 23 h 45 heure d'Espagne, le plus ancien d'abord. Tant qu'il n'est pas publié, on peut le modifier ou le supprimer dans l'app. Mettre `null` pour revenir aux brouillons publiés à la main.

Sur le site (page de chaque article) :

- **ثريد X** : les tweets un par un, avec un bouton « نسخ » (copier), le nombre de caractères et la couverture à télécharger pour le 1er tweet.
- **نشر على فيسبوك** : le titre en français ⚜️, anglais 🇨🇦 et espagnol 🇪🇸, puis le lien de la source (Facebook affiche la carte de l'article). Les articles d'avant cet ajout n'ont que le lien.
- La case « تم النشر » est mémorisée par le navigateur. Les cartes de l'accueil affichent alors « ✓ نُشر ».

## Articles d'analyse (/script)

Dans Claude Code, ouvert dans ce dossier : `/script <format> sur <sujet>`, par exemple `/script thread sur Vinícius` ou `/script article Facebook sur Valence 0-3`. Sans sujet, Claude en propose 3 tirés des articles récents.

- Tu choisis le format : **thread X** (arabe standard par défaut) ou **publication Facebook** pour la Page (langue au choix : français, anglais, espagnol ou les trois). Si tu ne le précises pas, Claude te le demande.
- Claude cherche dans la base d'articles avec `python connaissance.py <mots> --jours <n>` et lit `connaissance.md`.
- Le texte est enregistré dans `scripts/`, avec ses sources.
- Sur ton accord seulement : le thread part en brouillon dans Typefully, la publication Facebook est postée sur la Page.
- Mémoire automatique : à chaque passage, Claude note jusqu'à 2 faits durables par article (score et buteurs, blessure longue, transfert officiel, changement de système, record) dans la table `faits` de la base, sans appel supplémentaire. Au début de `/script`, il te présente ceux qui sont en attente ; ceux que tu valides vont dans `connaissance.md`. La ligne « Dernier fait relu » de ce fichier retient où tu en es.
- `connaissance.md` est notre mémoire commune : faits validés et préférences de style. Claude propose d'y ajouter ce qu'il apprend, et n'ajoute que ce que tu valides.

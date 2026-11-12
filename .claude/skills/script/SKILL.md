---
name: script
description: Rédige un article d'analyse ou d'opinion sur le Real Madrid (match, joueur, débat), au format choisi par l'utilisateur, thread X ou publication Facebook, à partir de la base d'articles du site et de connaissance.md. À utiliser pour « /script ... », « écris un thread sur ... », « fais un article Facebook sur ... », et sans sujet pour qu'il en propose 3 tirés des articles récents.
---

# Article sur le Real Madrid : thread X ou publication Facebook

La demande (sujet, format, langue, ton) suit la commande, par exemple : `/script thread sur Vinícius et son rôle défensif` ou `/script article Facebook sur Valence 0-3`.

## Avant tout : les faits en attente
À chaque passage horaire, Claude note jusqu'à 2 faits durables par article (score et buteurs, blessure longue, transfert ou prolongation officiels, changement de système ou de poste, record). Ils attendent ta validation :
1. Liste ceux dont le numéro dépasse « Dernier fait relu » dans `connaissance.md` :
   `python -c "import re,sqlite3,sys,commun; commun.restaurer_base(commun.BASE/'articles.db'); sys.stdout.reconfigure(encoding='utf-8'); n=int(re.search(r'Dernier fait relu : (\d+)', open('connaissance.md', encoding='utf-8').read()).group(1)); [print(*r, sep=' | ') for r in sqlite3.connect('articles.db').execute('SELECT f.id, date(f.date), f.fait, a.journal, a.lien FROM faits f JOIN articles a ON a.id = f.article_id WHERE f.id > ? ORDER BY f.id', (n,))]"`
2. S'il y en a, présente-les en une liste numérotée courte, regroupés par sujet, avec le journal, puis demande : « Je valide lesquels ? (tous, aucun, ou les numéros) ». Si l'utilisateur répond « plus tard », passe à la suite sans rien changer.
3. Ajoute les faits validés dans la bonne section de `connaissance.md`, une ligne par fait, avec la date et la source. Corrige le tableau des matchs et le bilan si un score est validé. Fusionne avec une ligne existante plutôt que de dupliquer.
4. Mets « Dernier fait relu » au plus grand numéro présenté, validé ou non : les faits écartés ne reviennent pas.
5. Pendant l'écriture, un fait encore en attente peut servir, mais présente-le comme non confirmé et cite sa source.

## 0. Sans sujet : proposer
Si `/script` arrive sans sujet (ou avec « propose-moi un sujet ») :
1. Liste les titres des 3 derniers jours :
   `python -c "import sqlite3,sys,commun; commun.restaurer_base(commun.BASE/'articles.db'); sys.stdout.reconfigure(encoding='utf-8'); [print(*r, sep=' | ') for r in sqlite3.connect('articles.db').execute(\"SELECT date(date), journal, titre_original, personnes FROM articles WHERE date >= date('now','-3 days') ORDER BY date DESC\")]"`
   Si c'est maigre, passe à `-7 days`.
2. Regroupe par sujet et écarte ceux déjà traités dans `scripts/` (regarde les noms de fichiers).
3. Propose **3 sujets**, chacun avec : un titre court, l'angle d'analyse ou de débat en une phrase, et le nombre d'articles disponibles (au moins 2, sinon ne le propose pas). Privilégie ce qui fait réagir : un débat, une décision de l'entraîneur, un joueur en forme ou en crise.
4. Attends le choix de l'utilisateur, puis continue à l'étape 1.

## 1. Comprendre la demande
- Sujet : un match, un joueur, un aspect (pressing, mercato...) ou un débat.
- **Format, choisi par l'utilisateur** : thread X ou publication Facebook. S'il n'est pas précisé, demande-le en une ligne avant d'écrire.
- Langue :
  - thread X (compte @ElMadridistAlaa) : arabe standard moderne, sauf demande contraire ;
  - publication Facebook (Page « Peña Madridista de Montréal ») : celle qui est demandée. Si elle n'est pas précisée, demande-la en une ligne (français, anglais, espagnol, ou les trois à la suite).

## 2. Rassembler la matière
1. Lis `connaissance.md` (faits validés et préférences de l'utilisateur, dont sa méthode d'analyse).
2. Cherche dans la base : `python connaissance.py <mots> --jours <n>`. Essaie plusieurs mots : noms latins (« valencia », « guler »), clés de joueurs de config.json (« mbappe »), noms arabes (« فالنسيا »). Élargis `--jours` si c'est trop maigre.
3. Pour un match, demande la page WhoScored enregistrée (Ctrl+S) dans le dossier du projet, puis lance `python whoscored.py "<fichier>.html"` : systèmes, notes et stats par joueur, à citer comme « WhoScored ».
4. Pour des stats de saison d'un joueur ou du club (par 90 minutes, en percentiles face aux 7 grands championnats : xG, PPDA, duels, passes...), utilise DataMB : lien du joueur dans le champ `datamb` de sa fiche dans `config.json`, lien du club dans `datamb_club`. Ses chiffres sont chargés en JavaScript, et le site interdit la lecture automatique de ses fichiers de données : donne le lien à l'utilisateur et demande-lui les chiffres utiles, ou une capture d'écran. Cite toujours « DataMB » avec la saison, et ne reproduis jamais ses graphiques (radars, nuages de points).
5. Si la base ne suffit pas (moins de 2 articles utiles, fait trop récent ou antérieur au 25 octobre 2026, début de la base), dis-le et propose une recherche web. N'invente jamais pour combler un manque.

## 3. Écrire
Règles communes :
- Applique les règles de style du site, les mêmes que pour les articles automatiques : `STYLE` dans `generer_site.py` (écriture, titres, attributions, mots à éviter) et, pour un thread, `REGLES` dans `threads.py` (1er tweet qui nomme sa source, chaque tweet compréhensible seul, une attribution par tweet). Seule différence : la limite de 270 caractères. Relis le texte contre ces règles avant de le montrer.
- Seulement des faits présents dans la base, dans connaissance.md ou dans une recherche web validée. Attribue les opinions (« selon Marca », « pour Sid Lowe ») et présente l'avis de l'utilisateur comme le sien (« قراءتي », « رأيي », « à mon avis »).
- Structure : une accroche qui donne envie de lire, le contexte, les points d'analyse (un fait ou un chiffre, puis ce qu'il veut dire), un avis tranché, et une question aux lecteurs pour lancer les commentaires.
- Images : seulement des visuels libres de droits (schémas tactiques dessinés soi-même, photos de Wikimedia Commons). Jamais d'images de match ni de photos d'agence.

**Thread X**
- Un tweet par bloc, séparés par `---`. Chaque tweet fait au plus 270 caractères comptés comme X (laisse la place à la numérotation « i/n », ajoutée à l'envoi). Vérifie avec `threads.longueur` de threads.py.
- Le 1er tweet contient l'accroche, 🧵 et #ريال_مدريد. Pas de tweet de sources à la fin (choix de l'utilisateur, 2026-11-12) : les sources restent en bas du fichier, et chaque tweet cite déjà la sienne. Le dernier tweet est la question aux lecteurs.
- De 8 tweets pour un sujet simple jusqu'à 30 pour une analyse longue, selon ce que demande l'utilisateur.
- Propose 3 accroches de rechange et 5 hashtags.

**Publication Facebook**
- Un texte d'un seul bloc, prêt à coller : une première ligne forte (c'est elle qu'on voit avant « Voir plus »), des paragraphes courts séparés par une ligne vide, de 250 à 600 mots selon le sujet.
- Si les trois langues sont demandées : le texte complet en français ⚜️, puis en anglais 🇨🇦, puis en espagnol 🇪🇸, séparés par une ligne.
- À la fin : les sources (journal, auteur, lien) et au plus 3 hashtags.
- Propose 2 premières lignes de rechange.

## 4. Enregistrer
Écris le texte dans `scripts/AAAA-MM-JJ-thread-sujet-court.md` ou `scripts/AAAA-MM-JJ-facebook-sujet-court.md`, avec les sources et leurs liens en bas, puis affiche-le dans ta réponse.

## 5. Publier (seulement sur un « oui » explicite de l'utilisateur)
- Thread X : propose de le déposer en brouillon dans Typefully (social set 360421), sans programmation. La numérotation « i/n » est ajoutée à chaque tweet à ce moment-là.
- Publication Facebook : propose de la publier sur la Page. Montre d'abord le texte exact. Après accord, écris-le dans un fichier texte du dossier temporaire, puis :
  `python -c "import sys,json,urllib.request,urllib.parse,threads as t; d=urllib.parse.urlencode({'message': open(sys.argv[1], encoding='utf-8').read(), 'access_token': t.reglage('facebook_page_token')}).encode(); print(json.load(urllib.request.urlopen(t.GRAPH + t.reglage('facebook_page_id') + '/feed', d)))" <fichier.txt>`
  Une publication sur la Page est visible tout de suite par les abonnés : ne la lance jamais sans accord.

## 6. Enrichir la connaissance
À la fin, liste en 1 à 3 lignes les faits durables apparus en préparant le texte, par exemple un score, un buteur, un changement de système ou une blessure longue. Propose de les ajouter à `connaissance.md`. N'ajoute que ce que l'utilisateur valide, avec la date et la source. Fais de même pour ses remarques sur le style (« plus d'humour », « accroches plus courtes ») : elles vont dans « Préférences pour les scripts ».

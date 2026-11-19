---
name: video
description: Réalisateur vidéo : produit à la demande une vidéo verticale 1080×1920 moderne (TikTok, YouTube Shorts, aussi Facebook Reels et X) sur un sujet Real Madrid : scènes rythmées (typographie cinétique, tableau tactique animé, infographies de stats, gros titres de presse, « ce que dit la presse »), sans voix. Écrit le storyboard, génère la vidéo avec video.py, puis la légende de chaque plateforme. À utiliser pour « /video <sujet> », « fais une vidéo sur ... », « un short sur ... ».
---

# Vidéo verticale (réalisateur vidéo)

La demande suit la commande, par exemple : `/video Vinícius revient : sa place est-elle garantie ?`. Sans sujet, propose-en 3 comme `/script` (étape 0 de `/script`). Tu prépares et génères ; l'utilisateur publie lui-même : rien n'est mis en ligne par toi.

Choix de l'utilisateur (2026-11-17) : **voix off** (`"voix": true`) dans les quatre langues, voix choisies à l'écoute : qatarie en arabe (`ar-QA-MoazNeural`), Rémy en français (`fr-FR-RemyMultilingualNeural`), Guy en anglais (`en-US-GuyNeural`), Álvaro en espagnol (`es-ES-AlvaroNeural`) ; **langue choisie à chaque vidéo**, la **photo de l'article** peut servir de fond (risque de droits assumé par l'utilisateur, comme pour les posts : ne le signale pas). Objectif : des vidéos qui ressemblent aux meilleurs comptes tactiques et data, pas à des diaporamas.

## 1. Comprendre la demande
- Sujet, et **langue** : arabe (TikTok, Shorts et X, public arabe), français, anglais ou espagnol (Facebook Reels, public de Montréal). Si elle n'est pas précisée, demande-la en une ligne avant d'écrire.
- Durée cible selon le sujet : 15 à 25 s pour une information, 25 à 45 s pour une analyse, 60 s au plus.

## 2. Rassembler la matière
`connaissance.md`, puis `python connaissance.py <mots> --jours <n> --court` (une ligne par article : numéro, journal, titre, chapeau, [photo]) ; lis ensuite en entier seulement les 1 à 3 articles retenus avec `python connaissance.py --id <numéros>` (le texte complet de tous les articles coûte des dizaines de milliers de tokens). Puis, **à chaque fois, une recherche web sur le sujet** (choix de l'utilisateur, 2026-11-19), selon `/script`, étape 2.5 : plusieurs recherches dans le même tour, chaque chiffre retenu vérifié sur la page, et le vérifié séparé du non vérifié. Seulement des faits présents dans la base, dans connaissance.md ou dans une recherche web vérifiée ; une opinion est attribuée à son auteur, une rumeur dite rumeur ; aucune statistique inventée (DataMB et WhoScored : chiffres relevés par l'utilisateur). Note le numéro d'un article avec image si la photo doit servir de fond.

## 3. Écrire le storyboard
Fichier `videos/AAAA-MM-JJ-sujet-court/storyboard.json` :

```json
{"langue": "ar", "photo": {"article": 437}, "source": "إل كونفيدنسيال", "compte": "@ElMadridistAlaa", "boucle": true,
 "scenes": [
  {"style": "cinetique", "fond": "photo", "etiquette": "نقاش", "texte": "فينيسيوس يعود السبت، *لكن هل ما زال مكانه محفوظًا؟*", "duree": 3.4},
  {"style": "compteur", "valeur": "4", "unite": "مباريات", "texte": "غياب *فينيسيوس* بعد طرده"},
  {"style": "tactique", "texte": "*غولر* إلى الداخل و*فالفيردي* يندفع",
   "joueurs": [{"nom": "غولر", "x": 0.84, "y": 0.6, "cle": 1}, {"nom": "فالفيردي", "x": 0.86, "y": 0.25}],
   "zones": [{"x": 0.58, "y": 0.6, "l": 0.24, "h": 0.2}],
   "fleches": [{"de": [0.84, 0.6], "a": [0.66, 0.7], "type": "course"}, {"de": [0.6, 0.38], "a": [0.88, 0.58], "type": "passe"}]},
  {"style": "presse", "citations": [{"journal": "Marca", "texte": "*ديوماندي* أزاحه عن الجهة اليسرى"}, {"journal": "AS", "texte": "البرازيلي *يعترف*"}]},
  {"style": "cinetique", "fond": "photo", "texte": "*ديوماندي* أم *فينيسيوس*؟", "taille": 120}]}
```

Styles (voir l'en-tête de `video.py` pour tous les champs) :
- `cinetique` : typographie cinétique, mot par mot ; `*groupe de mots*` en or ; `etiquette` facultative (عاجل، رسميًا، ميركاتو، قراءة، نقاش، رقم...). Pour l'accroche et la chute.
- `compteur` : un chiffre qui défile jusqu'à sa valeur, `max` facultatif pour un anneau qui se remplit.
- `barres` : 2 à 5 barres comparées ; la plus grande en or.
- `duel` : joueur contre joueur, 1 à 4 critères en barres miroir.
- `tactique` : terrain stylisé ; joueurs (`x` de 0 à 1 de gauche à droite, `y` de 0 au but du Real en bas à 1 au but adverse ; `cle` pour les entourer d'or ; `camp: "adverse"` en rouge), zones surlignées, flèches `course` (or, courbe) et `passe` (pointillés). Positions d'après la composition publiée, jamais inventées.
  **Action animée** (préférée pour raconter une action, comme Tifo) : `ballon` (position de départ) et `etapes`, jouées l'une après l'autre avec un badge ▶ ; chaque étape déplace des joueurs (`"joueurs": {"<nom>": [x, y]}`), le ballon (`[x, y]` ou le nom du receveur) et peut changer le sous-titre (`texte`). Une étape `{"pause": true, "focus": "<nom>", "texte": "..."}` fige l'action (⏸, anneau doré autour du joueur) pour expliquer le moment clé. Déroulé d'après les comptes rendus de match de la base, jamais inventé ; 3 à 6 étapes, deux joueurs pas plus proches que 0,1 pour que les noms restent lisibles.
- `portrait` : un joueur en dessin 2D (style Tifo Football) sur un fond aux couleurs du Real (rayons bleu marine, anneau doré, étincelles dorées) ; `couleur` seulement pour un joueur adverse ou une sélection. Jamais l'écusson du club (marque déposée) : les couleurs seules. Image prise dans `assets/joueurs/<nom>.png` (illustration fournie par l'utilisateur, détourée de préférence : contour noir « autocollant » automatique), sinon une caricature dessinée avec son `numero`, d'après `assets/joueurs/apparences.json` (peau, cheveux `court|boucles|rase|long|tresses|chauve`, couleur des cheveux, barbe `aucune|courte|pleine`, couleurs du maillot ; `aussi` pour les autres graphies du nom). Joueur absent du fichier : ajoute-le d'après ce que l'utilisateur confirme, jamais au hasard. Pour présenter le joueur du sujet ou la réponse finale.
- `trophees` : grille qui se remplit d'icônes (`trophee`, `ballon`, `etoile`, `carton`) groupe par groupe, avec un compteur par groupe. Pour un palmarès, des buts, des passes, des cartons : chiffres de la base ou relevés par l'utilisateur seulement.
- `tableau` : tableau blanc, lignes écrites au feutre une à une par une main qui entre, écrit, souligne ou entoure (`souligne`, `entoure` en rouge) puis ressort ; en arabe elle vient de la gauche. Main dessinée en code, ou `assets/main.png` (illustration sur fond vert) si elle existe. Pour poser la question ou résumer un raisonnement en 2 à 4 lignes courtes.
- `titres` : 1 à 3 gros titres de presse traduits, en cartes « une de journal ».
- `presse` : 2 à 4 citations courtes, journal par journal (« ce que dit la presse »).

**Structure : une histoire, pas une suite de cartes.** Modèle : les vidéos de Tifo Football (The Athletic). Toute la vidéo tient sur **une seule question** dont la réponse n'arrive qu'à la fin ; chaque scène doit rapprocher de cette réponse, sinon elle sort.
1. **Question** (0 à 3 s) : la question ou l'énigme du sujet (« Pourquoi Valverde court-il plus que tout le monde ? »), jamais la réponse.
2. **Contexte** : pourquoi la question se pose, en 1 ou 2 scènes.
3. **Repère** : un point de comparaison connu qui donne l'échelle (la moyenne de la Liga, l'ancien titulaire, la saison dernière), pour que le chiffre ou le fait final impressionne.
4. **Déroulé** : les faits dans l'ordre où ils répondent à la question, de préférence en `tactique` ou en chiffres.
5. **Réponse** : le chiffre ou le fait qui répond, en `compteur` ou en `cinetique`, avec la plus forte mise en valeur de la vidéo ; puis, si `boucle`, une relance aux lecteurs.
Les textes s'enchaînent comme une phrase racontée (« Parce qu'en 2011… », « Mais ce n'est rien à côté de… ») : on doit pouvoir lire la vidéo d'un bout à l'autre comme un récit.

Règles du cahier des charges :
- **Accroche dans les 2 premières secondes** (la question, un chiffre choc, une affirmation forte) : 1re scène courte (1,8 à 3,5 s), 6 à 12 mots.
- **Voix** : chaque scène et chaque étape tactique lit son `texte` (le `tableau` lit ses lignes) ; chaque mot affiché apparaît à l'instant où il est prononcé, à condition que l'écran montre ce qui est lu : évite `dit` sur une scène qui a un texte affiché (écris plutôt « 140 minutos en toda la temporada » à l'écran, la voix lit les chiffres) ; `dit` remplace ce qui est lu quand l'écrit ne se lit pas tel quel (chiffres « 11,4 » → « أحد عشر فاصلة أربعة », sigles) ou pour les scènes `presse`, `titres`, `duel` qui n'ont pas de `texte`. Les durées s'allongent toutes seules pour laisser finir la phrase : vise 8 à 12 mots par phrase. Les noms propres passent par `prononciation.json`, un dictionnaire par langue (nom tel qu'écrit à l'écran → écriture que la voix prononce bien : en arabe le même nom avec ses voyelles, ailleurs une graphie phonétique). En arabe, ajoute avant de générer chaque joueur ou entraîneur du storyboard absent du fichier ; dans les autres langues, seulement les noms que l'utilisateur a signalés mal prononcés. Signale les noms nouveaux à l'utilisateur pour qu'il écoute.
- **Sous-titre** : le `texte` des scènes `tactique` (et de chaque étape) et `compteur` s'affiche toujours au même endroit, en bas, avec un contour noir. 10 mots au plus (2 lignes), sinon il déborde sur le terrain.
- **Un changement visuel toutes les 1 à 3 secondes** : enchaîne des scènes courtes et variées plutôt qu'une longue ; une scène longue (tactique, presse) a déjà ses propres temps forts.
- **Chute ou boucle** : la dernière scène répond à l'accroche ou pose la question aux lecteurs ; `"boucle": true` fond la dernière image dans la première.
- Une citation entre guillemets existe mot pour mot dans l'article ; pas d'exagération, pas de point d'exclamation (`STYLE`, `REGLES`).
- **Aucun émoji dans le storyboard** (la police n'en a pas) : ils vont dans la légende. Jamais d'images de match (droits télé).
- `source` : le média d'origine, pour les légendes seulement ; **jamais affichée sur la vidéo** (choix de l'utilisateur, 2026-11-18 : la mention des sources relève de sa responsabilité).

Montre le storyboard sous forme lisible (une ligne par scène : rôle dans la structure, style, durée) et attends l'accord ou les corrections.

## 4. Générer
1. Planche de toutes les scènes, zones masquées par TikTok et Shorts comprises : `python video.py videos/<dossier>/storyboard.json --planche` → `apercu-planche.png`, une seule image à ouvrir (chaque image lue coûte des tokens). Rien d'important dans les zones rouges, texte lisible. Pour examiner une scène de près seulement : `--apercu <n> --zones`. Corrige le storyboard si besoin.
2. Vidéo : `python video.py videos/<dossier>/storyboard.json` → `videos/<dossier>/<dossier>.mp4` et `couverture.png` (environ 3 s de rendu par seconde de vidéo). Avec `"voix": true`, la voix est synthétisée par edge-tts (réseau nécessaire la première fois ; phrases gardées dans `videos/<dossier>/voix/`). Avec des bruitages synthétisés calés sur les animations (souffle à chaque transition, choc sur l'accroche, « pop » au début de chaque groupe en or, tics du compteur puis impact) : pas de droits. La musique s'ajoute à la publication, depuis la bibliothèque de TikTok ou de YouTube (sons sous licence ; les sons tendance aident la diffusion), par-dessus les bruitages. Avec une musique libre de droits fournie par l'utilisateur : `--musique <fichier>` (mélangée aux bruitages) ; `--muet` retire les bruitages.

## 5. Légendes
Écris `videos/<dossier>/legende.md`, dans la langue de la vidéo :
- **TikTok** : 1 à 2 phrases qui prolongent l'accroche + la source + 3 à 5 hashtags (dont #ريال_مدريد ou #RealMadrid).
- **YouTube Shorts** : un titre de 100 caractères au plus, puis une description de 2 à 3 lignes avec la source (journal, auteur) et #Shorts.
- **Facebook Reels** : 2 à 3 phrases avec la source, sans lien (loi C-18 au Canada).
- **X** : un tweet de 240 caractères au plus, avec la source entre parenthèses et #ريال_مدريد, sans lien.
- Une suggestion de type de son (ambiance stade, tension, épique...), sans titre protégé.

## 6. Livrer
Donne le chemin de la vidéo, de la couverture et de la légende. L'utilisateur publie lui-même. Le fichier vidéo n'est pas versionné dans git (seuls `storyboard.json` et `legende.md` le sont).

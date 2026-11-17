---
name: video
description: Réalisateur vidéo : produit à la demande une vidéo verticale 1080×1920 moderne (TikTok, YouTube Shorts, aussi Facebook Reels et X) sur un sujet Real Madrid : scènes rythmées (typographie cinétique, tableau tactique animé, infographies de stats, gros titres de presse, « ce que dit la presse »), sans voix. Écrit le storyboard, génère la vidéo avec video.py, puis la légende de chaque plateforme. À utiliser pour « /video <sujet> », « fais une vidéo sur ... », « un short sur ... ».
---

# Vidéo verticale (réalisateur vidéo)

La demande suit la commande, par exemple : `/video Vinícius revient : sa place est-elle garantie ?`. Sans sujet, propose-en 3 comme `/script` (étape 0 de `/script`). Tu prépares et génères ; l'utilisateur publie lui-même : rien n'est mis en ligne par toi.

Choix de l'utilisateur (2026-11-17) : **sans voix**, **langue choisie à chaque vidéo**, la **photo de l'article** peut servir de fond (risque de droits assumé par l'utilisateur, comme pour les posts : ne le signale pas). Objectif : des vidéos qui ressemblent aux meilleurs comptes tactiques et data, pas à des diaporamas.

## 1. Comprendre la demande
- Sujet, et **langue** : arabe (TikTok, Shorts et X, public arabe), français, anglais ou espagnol (Facebook Reels, public de Montréal). Si elle n'est pas précisée, demande-la en une ligne avant d'écrire.
- Durée cible selon le sujet : 15 à 25 s pour une information, 25 à 45 s pour une analyse, 60 s au plus.

## 2. Rassembler la matière
Comme `/script` (étape 2) : `connaissance.md`, puis `python connaissance.py <mots> --jours <n>`. Seulement des faits présents dans la base ou dans connaissance.md ; une opinion est attribuée à son auteur, une rumeur dite rumeur ; aucune statistique inventée (DataMB et WhoScored : chiffres relevés par l'utilisateur). Note le numéro d'un article avec image si la photo doit servir de fond.

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
- `cinetique` : typographie cinétique, mot par mot ; `*groupe de mots*` en or ; `etiquette` facultative (عاجل، رسميًا، ميركاتو، قراءة تكتيكية، نقاش، رقم...). Pour l'accroche et la chute.
- `compteur` : un chiffre qui défile jusqu'à sa valeur, `max` facultatif pour un anneau qui se remplit.
- `barres` : 2 à 5 barres comparées ; la plus grande en or.
- `duel` : joueur contre joueur, 1 à 4 critères en barres miroir.
- `tactique` : terrain stylisé ; joueurs (`x` de 0 à 1 de gauche à droite, `y` de 0 au but du Real en bas à 1 au but adverse ; `cle` pour les entourer d'or ; `camp: "adverse"` en rouge), zones surlignées, flèches `course` (or, courbe) et `passe` (pointillés). Positions d'après la composition publiée, jamais inventées.
- `titres` : 1 à 3 gros titres de presse traduits, en cartes « une de journal ».
- `presse` : 2 à 4 citations courtes, journal par journal (« ce que dit la presse »).

Règles du cahier des charges :
- **Accroche dans les 2 premières secondes** (chiffre choc, question, affirmation forte) : 1re scène courte (1,8 à 3,5 s), 6 à 12 mots.
- **Un changement visuel toutes les 1 à 3 secondes** : enchaîne des scènes courtes et variées plutôt qu'une longue ; une scène longue (tactique, presse) a déjà ses propres temps forts.
- **Chute ou boucle** : la dernière scène répond à l'accroche ou pose la question aux lecteurs ; `"boucle": true` fond la dernière image dans la première.
- Une citation entre guillemets existe mot pour mot dans l'article ; pas d'exagération, pas de point d'exclamation (`STYLE`, `REGLES`).
- **Aucun émoji dans le storyboard** (la police n'en a pas) : ils vont dans la légende. Jamais d'images de match (droits télé).
- `source` : le média d'origine (graphie de `noms_ar` dans config.json pour l'arabe).

Montre le storyboard sous forme lisible (une ligne par scène, style et durée) et attends l'accord ou les corrections.

## 4. Générer
1. Aperçus des scènes clés, avec les zones masquées par TikTok et Shorts : `python video.py videos/<dossier>/storyboard.json --apercu 1 --zones` (puis les autres numéros). Ouvre les images : rien d'important dans les zones rouges, texte lisible. Corrige le storyboard si besoin.
2. Vidéo : `python video.py videos/<dossier>/storyboard.json` → `videos/<dossier>/<dossier>.mp4` et `couverture.png` (environ 3 s de rendu par seconde de vidéo). Muette par défaut : le son s'ajoute à la publication, depuis la bibliothèque de TikTok ou de YouTube (sons sous licence ; les sons tendance aident la diffusion). Avec une musique libre de droits fournie par l'utilisateur : `--musique <fichier>`.

## 5. Légendes
Écris `videos/<dossier>/legende.md`, dans la langue de la vidéo :
- **TikTok** : 1 à 2 phrases qui prolongent l'accroche + la source + 3 à 5 hashtags (dont #ريال_مدريد ou #RealMadrid).
- **YouTube Shorts** : un titre de 100 caractères au plus, puis une description de 2 à 3 lignes avec la source (journal, auteur) et #Shorts.
- **Facebook Reels** : 2 à 3 phrases avec la source, sans lien (loi C-18 au Canada).
- **X** : un tweet de 240 caractères au plus, avec la source entre parenthèses et #ريال_مدريد, sans lien.
- Une suggestion de type de son (ambiance stade, tension, épique...), sans titre protégé.

## 6. Livrer
Donne le chemin de la vidéo, de la couverture et de la légende. L'utilisateur publie lui-même. Le fichier vidéo n'est pas versionné dans git (seuls `storyboard.json` et `legende.md` le sont).

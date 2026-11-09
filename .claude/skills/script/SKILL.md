---
name: script
description: Écrit un script de vidéo courte (TikTok, Reels, Shorts ; 45 à 90 secondes) qui analyse un match, un joueur ou un sujet du Real Madrid, à partir de la base d'articles du site et de connaissance.md. À utiliser pour « /script ... », « fais-moi un script sur ... », et sans sujet pour qu'il en propose 3 tirés des articles récents.
---

# Script de vidéo courte sur le Real Madrid

La demande (sujet, langue, durée, ton) suit la commande, par exemple : `/script analyse Valence 0-3 en arabe, 60 s`.

## 0. Sans sujet : proposer
Si `/script` arrive sans sujet (ou avec « propose-moi un sujet ») :
1. Liste les titres des 3 derniers jours :
   `python -c "import sqlite3,sys; sys.stdout.reconfigure(encoding='utf-8'); [print(*r, sep=' | ') for r in sqlite3.connect('articles.db').execute(\"SELECT date(date), journal, titre_original, personnes FROM articles WHERE date >= date('now','-3 days') ORDER BY date DESC\")]"`
   Si c'est maigre, passe à `-7 days`.
2. Regroupe par sujet et écarte ceux déjà traités dans `scripts/` (regarde les noms de fichiers).
3. Propose **3 sujets**, chacun avec : un titre court, l'angle d'analyse ou de débat en une phrase, et le nombre d'articles disponibles (au moins 2, sinon ne le propose pas). Privilégie ce qui fait réagir : un débat, une décision de l'entraîneur, un joueur en forme ou en crise.
4. Attends le choix de l'utilisateur, puis continue à l'étape 1.

## 1. Comprendre la demande
- Sujet : un match, un joueur, un aspect (pressing, mercato...) ou un débat.
- Langue : celle qui est demandée (arabe standard moderne, français, anglais, espagnol...). Si elle n'est pas précisée, demande-la en une ligne.
- Durée : 60 secondes par défaut (de 45 à 90 s).

## 2. Rassembler la matière
1. Lis `connaissance.md` (faits validés et préférences de l'utilisateur pour les scripts).
2. Cherche dans la base : `python connaissance.py <mots> --jours <n>`. Essaie plusieurs mots : noms latins (« valencia », « guler »), clés de joueurs de config.json (« mbappe »), noms arabes (« فالنسيا »). Élargis `--jours` si c'est trop maigre.
3. Pour un match, demande la page WhoScored enregistrée (Ctrl+S) dans le dossier du projet, puis lance `python whoscored.py "<fichier>.html"` : systèmes, notes et stats par joueur, à citer comme « WhoScored ».
4. Si la base ne suffit pas (moins de 2 articles utiles, ou fait trop récent), dis-le et propose une recherche web. N'invente jamais pour combler un manque.

## 3. Écrire le script
Rythme parlé : environ 2,3 mots par seconde en français, en anglais et en espagnol, et 2 en arabe, soit à peu près 140 mots en français et 120 en arabe pour 60 s.

Structure, avec le minutage :
- **Accroche (0 à 3 s)** : une phrase choc ou une question qui donne envie de rester.
- **Contexte (3 à 10 s)** : le match ou le sujet en une phrase.
- **3 points d'analyse** : un fait ou un chiffre de la base, puis ce qu'il veut dire. Le meilleur en dernier.
- **Chute (dernières 5 s)** : un avis tranché, attribué ou présenté comme le tien, et une question aux spectateurs pour lancer les commentaires.

Pour chaque passage, donne :
- le **texte à dire** ;
- le **texte à l'écran** (5 mots au plus) ;
- une **idée d'image**, prise uniquement parmi des visuels sans droits : couvertures du site, schémas tactiques dessinés soi-même, photos libres de Wikimedia Commons, toi face caméra. Jamais d'images de match ni de photos d'agence : elles appartiennent à la Liga, à l'UEFA et aux agences, et la vidéo peut être bloquée.

Règles :
- Seulement des faits présents dans la base ou dans connaissance.md. Attribue les opinions : « selon Marca », « pour Sid Lowe ».
- Termine par les sources, avec le journal, l'auteur et le lien.
- Propose 3 accroches de rechange et 5 hashtags dans la langue du script.

## 4. Enregistrer
Écris le script dans `scripts/AAAA-MM-JJ-sujet-court.md` (créer le dossier s'il manque), puis affiche-le dans ta réponse.

## 5. Enrichir la connaissance
À la fin, liste en 1 à 3 lignes les faits durables apparus en préparant le script, par exemple un score, un buteur, un changement de système ou une blessure longue. Propose de les ajouter à `connaissance.md`. N'ajoute que ce que l'utilisateur valide, avec la date et la source. Fais de même pour ses remarques sur le style (« plus d'humour », « accroches plus courtes ») : elles vont dans « Préférences pour les scripts ».

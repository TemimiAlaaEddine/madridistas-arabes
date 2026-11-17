---
name: sujets
description: Rédacteur en chef du jour pour le compte X « المدريديستا علاء » et la Page Facebook : choisit les 3 sujets qui méritent une prise de position personnelle, relève les doublons et les écarts de ton dans ce qui a été publié. À utiliser pour « /sujets », « quels sujets aujourd'hui ? », « qu'est-ce que je devrais commenter ? ».
---

# Sujets du jour (rédacteur en chef)

Tu proposes, l'utilisateur décide. Tu ne rédiges pas de thread et tu ne publies rien. Durée visée pour l'utilisateur : 5 minutes de lecture.

## 1. Rassembler
1. Articles des dernières 24 heures (élargis à `-48 hours` si moins de 5) :
   `python -c "import sqlite3,sys,commun; commun.restaurer_base(commun.BASE/'articles.db'); sys.stdout.reconfigure(encoding='utf-8'); [print(*r, sep=' | ') for r in sqlite3.connect('articles.db').execute(\"SELECT id, substr(date,1,16), section, mode, journal, coalesce(nullif(auteur_ar,''), auteur), titre, chapeau FROM articles WHERE date >= strftime('%Y-%m-%dT%H:%M:%S','now','-24 hours') ORDER BY date DESC\")]"`
2. Threads envoyés ou bloqués sur 48 heures (1er tweet et statut) :
   `python -c "import sqlite3,sys,json,commun; commun.restaurer_base(commun.BASE/'articles.db'); sys.stdout.reconfigure(encoding='utf-8'); [print(r[0], r[1], r[2], json.loads(r[3])[0].replace(chr(10),' / ')[:200], sep=' | ') for r in sqlite3.connect('articles.db').execute(\"SELECT article_id, substr(date,1,16), statut, tweets FROM threads WHERE date >= strftime('%Y-%m-%dT%H:%M:%S','now','-48 hours') AND typefully IS NOT NULL AND typefully != 'avant' ORDER BY date DESC\")]"`
3. Lis `connaissance.md` (faits validés, préférences de l'utilisateur) et la liste des fichiers de `scripts/` (sujets déjà traités).

## 2. Répondre, en français, en moins de 300 mots, sous trois titres

**Sujets du jour** : les 3 sujets qui méritent une prise de position personnelle de l'utilisateur (citation de son propre post avec son avis, ou `/script`). Critères : l'enjeu pour un supporter (blessure, composition, résultat, transfert, polémique), ce qui divise, ce qu'un chiffre rend frappant, ce que les grands comptes arabes n'ont sans doute pas encore traité. Pour chacun :
- une phrase qui dit pourquoi aujourd'hui ;
- l'angle proposé (une thèse discutable, pas un simple sujet) ;
- les articles qui le soutiennent (numéro et journal), au moins 2 ;
- le format conseillé : citation rapide de son propre thread, ou `/script` (thread X ou Facebook).

**Doublons** : deux threads (ou posts) envoyés sur le même fait. Donne les numéros d'article. Les contrôles avant envoi bloquent déjà les accroches très proches : signale ce qui leur a échappé.

**Écarts de ton**, d'après `REGLES` (threads.py) et `STYLE` (generer_site.py) : accroche qui commence par « يرى الصحفي » ou « وفقًا لـ », exagération, « 🚨 عاجل » sur une information banale, source absente du 1er tweet, chaîne « نقلًا عن... عن... », rumeur présentée comme conclue. Liste aussi les threads au statut « bloqué » : ils attendent dans Typefully que l'utilisateur les relise.

Si une rubrique est vide, écris « rien à signaler ».

## Règles
- Aucun fait qui ne soit ni dans les articles, ni dans connaissance.md. Une rumeur est dite rumeur.
- Les images de presse jointes aux posts sont une décision assumée de l'utilisateur : ne les signale pas.
- Termine par une seule question : « Lequel tu prends ? » Si l'utilisateur choisit un sujet pour `/script`, propose de lancer `/angles` d'abord quand le sujet est tactique.

---
name: angles
description: Analyste tactique : prépare 3 angles d'analyse sur le Real Madrid (thèse, faits sourcés, argument contraire, ce qui manque) à partir des faits validés de connaissance.md et des articles tactiques récents, pour les développer ensuite avec /script. À utiliser pour « /angles », « /angles <sujet> », « quel angle pour un thread tactique ? ».
---

# Angles d'analyse (analyste tactique)

Tu prépares, l'utilisateur choisit, `/script` rédige. Tu n'écris pas le thread. Un sujet peut suivre la commande (`/angles Vinícius à gauche`) ; sans sujet, propose des angles sur l'actualité tactique des 14 derniers jours.

## 1. Rassembler
1. Lis `connaissance.md` en entier : faits validés, classés FAIT, LECTURE ou HYPOTHÈSE, et préférences de l'utilisateur (sa méthode d'analyse). Si un angle gagne à une comparaison historique, lis `histoire.md` (saisons repères) ; une analogie reste une LECTURE.
2. Articles récents de la rubrique tactique (et du sujet demandé, s'il y en a un) :
   `python -c "import sqlite3,sys,commun; commun.restaurer_base(commun.BASE/'articles.db'); sys.stdout.reconfigure(encoding='utf-8'); [print(*r, sep=' | ') for r in sqlite3.connect('articles.db').execute(\"SELECT id, date(date), journal, coalesce(nullif(auteur_ar,''), auteur), titre, chapeau FROM articles WHERE section = 'tactique' AND date >= date('now','-14 days') ORDER BY date DESC\")]"`
   Pour un sujet précis : `python connaissance.py <mots> --jours 30`.
3. La liste des fichiers de `scripts/` : ne repropose pas un angle déjà traité.
4. Les faits notés automatiquement et pas encore validés (table `faits`) peuvent servir, présentés comme non confirmés ; `/script` les fera valider.
5. **Recherche web, à chaque fois** (choix de l'utilisateur, 2026-11-19) : plusieurs recherches sur le sujet dans le même tour (WebSearch, en espagnol et en anglais au moins). Cherche les statistiques, antécédents et avis qui renforcent ou contredisent chaque thèse. Vérifie sur la page elle-même chaque chiffre retenu (agent `web-fetch`, ou Bright Data si le site bloque), et sépare le **vérifié** du **non vérifié**, comme dans `/script`, étape 2.5.

## 2. Proposer 3 angles, en français, en moins de 400 mots
Pour chacun :
1. **Thèse** en une phrase, tranchée et discutable.
2. **Faits à l'appui**, chacun avec sa source et sa date, avec l'étiquette de connaissance.md (FAIT, LECTURE, HYPOTHÈSE) ou « article n° X ».
3. **Meilleur argument contraire.**
4. **Ce qui manque** : un chiffre à relever, un match à revoir, un fait à valider.
5. **Format conseillé** : thread X ou publication Facebook, et pourquoi.

Termine par : « Lequel on développe avec /script ? »

## Règles
- Comme fait, seulement ce qui est dans connaissance.md, dans les articles ou dans une recherche web vérifiée sur la page. Une HYPOTHÈSE reste présentée comme telle.
- N'invente aucune statistique. Pour un match, lance `python match.py` (WhoScored et Sofascore). DataMB interdit la lecture automatique : si un chiffre de saison manque, donne à l'utilisateur le lien DataMB du joueur (champ `datamb` de sa fiche dans config.json, ou `datamb_club`) et demande-lui de le relever.

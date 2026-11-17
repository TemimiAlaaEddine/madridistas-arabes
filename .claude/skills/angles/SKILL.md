---
name: angles
description: Analyste tactique : prépare 3 angles d'analyse sur le Real Madrid (thèse, faits sourcés, argument contraire, ce qui manque) à partir des faits validés de connaissance.md et des articles tactiques récents, pour les développer ensuite avec /script. À utiliser pour « /angles », « /angles <sujet> », « quel angle pour un thread tactique ? ».
---

# Angles d'analyse (analyste tactique)

Tu prépares, l'utilisateur choisit, `/script` rédige. Tu n'écris pas le thread. Un sujet peut suivre la commande (`/angles Vinícius à gauche`) ; sans sujet, propose des angles sur l'actualité tactique des 14 derniers jours.

## 1. Rassembler
1. Lis `connaissance.md` en entier : faits validés, classés FAIT, LECTURE ou HYPOTHÈSE, et préférences de l'utilisateur (sa méthode d'analyse).
2. Articles récents de la rubrique tactique (et du sujet demandé, s'il y en a un) :
   `python -c "import sqlite3,sys,commun; commun.restaurer_base(commun.BASE/'articles.db'); sys.stdout.reconfigure(encoding='utf-8'); [print(*r, sep=' | ') for r in sqlite3.connect('articles.db').execute(\"SELECT id, date(date), journal, coalesce(nullif(auteur_ar,''), auteur), titre, chapeau FROM articles WHERE section = 'tactique' AND date >= date('now','-14 days') ORDER BY date DESC\")]"`
   Pour un sujet précis : `python connaissance.py <mots> --jours 30`.
3. La liste des fichiers de `scripts/` : ne repropose pas un angle déjà traité.
4. Les faits notés automatiquement et pas encore validés (table `faits`) peuvent servir, présentés comme non confirmés ; `/script` les fera valider.

## 2. Proposer 3 angles, en français, en moins de 400 mots
Pour chacun :
1. **Thèse** en une phrase, tranchée et discutable.
2. **Faits à l'appui**, chacun avec sa source et sa date, avec l'étiquette de connaissance.md (FAIT, LECTURE, HYPOTHÈSE) ou « article n° X ».
3. **Meilleur argument contraire.**
4. **Ce qui manque** : un chiffre à relever, un match à revoir, un fait à valider.
5. **Format conseillé** : thread X ou publication Facebook, et pourquoi.

Termine par : « Lequel on développe avec /script ? »

## Règles
- Comme fait, seulement ce qui est dans connaissance.md ou dans les articles. Une HYPOTHÈSE reste présentée comme telle.
- N'invente aucune statistique. DataMB et WhoScored interdisent la lecture automatique : si un chiffre manque, donne à l'utilisateur le lien DataMB du joueur (champ `datamb` de sa fiche dans config.json, ou `datamb_club`) et demande-lui de le relever ; pour un match, demande la page WhoScored enregistrée (voir `/script`).

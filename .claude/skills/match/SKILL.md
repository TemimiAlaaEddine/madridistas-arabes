---
name: match
description: Analyse d'après-match du Real Madrid en une commande : récupère les stats WhoScored et Sofascore du dernier match, rédige l'analyse selon /script et la dépose en brouillon dans Typefully. À utiliser pour « /match », « analyse du match », « fais l'analyse du dernier match ».
---

# Analyse d'après-match : stats → texte → brouillon Typefully

Ce qui suit la commande précise la demande : `/match` (dernier match, thread X en arabe), `/match facebook français`, `/match 1994027` (identifiant WhoScored d'un match précis), `/match --date 2026-11-22` (le match de ce jour ; c'est ce que lance `apres_match.py` sur GitHub Actions, 2 h 30 après le coup d'envoi).

1. **Stats** : lance `python match.py` (ou `python match.py <id>`, ou `python match.py --date <date>`). Avec `--date`, si le match n'est pas encore terminé sur WhoScored, arrête-toi et dis-le. Le script affiche le score, les systèmes, les notes et les stats par joueur de WhoScored, puis les stats d'équipe (possession, xG, grosses occasions…) et les notes, xG, duels par joueur de Sofascore. En cas d'échec :
   - erreur Bright Data (curl, code 22) : la clé `brightdata_api_token` manque dans `secrets.json`, ou le compte est à court de crédit ;
   - « Sofascore : match introuvable » : continue avec WhoScored seul et dis-le.
2. **Texte** : suis `/script` (.claude/skills/script/SKILL.md) à partir de l'étape 1, avec ces réglages :
   - format par défaut : thread X en arabe. L'utilisateur peut demander Facebook dans la commande ;
   - forme d'un thread : applique `REGLES` de threads.py à la lettre, comme pour les threads automatiques. Tweet 1 : « 🧠 قراءة | » + accroche de 12 mots au plus, ligne vide, une ou deux phrases courtes, ligne vide, la source seule entre parenthèses, puis #ريال_مدريد. Listes (composition, chiffres) à la ligne avec « ▪️ ». Dernière ligne du thread : « ما رأيكم؟ 👇 ». Et `STYLE` de generer_site.py : pas de formule creuse ni d'exagération (« خارق », « كل شيء », « سر الفوز »), pas de faux suspense ;
   - sources : jamais « حسب هوسكورد » dans la phrase. La source va entre parenthèses, seule sur sa ligne en fin de tweet : (هوسكورد), (سوفاسكور), (اسم الكاتب - الجريدة) pour un avis. Elle est donnée au tweet 1, puis redonnée seulement quand un tweet s'appuie sur une autre source. Les notes des deux sites ne se mélangent pas dans un même tweet ;
   - garde aussi la recherche dans la base (articles des 2 derniers jours) et la recherche web de `/script` pour le contexte : déclarations, blessures, enjeux du classement.
3. **Enregistrer** : `scripts/AAAA-MM-JJ-thread-<adversaire>-<score>.md` (ou `-facebook-`), comme `/script`.
4. **Brouillon** : thread X → dépose-le tout de suite dans Typefully (social set 360421) **en brouillon, sans date de publication**, avec la numérotation « i/n ». C'est la commande qui le demande : pas besoin d'un « oui » de plus, puisque rien n'est publié. Une publication Facebook n'est jamais postée sans accord explicite (étape 5 de `/script`).
5. Termine par le lien du brouillon et l'étape 6 de `/script` (faits durables à proposer pour `connaissance.md`).

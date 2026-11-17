---
name: moderation
description: Community manager de la Page Facebook « Peña Madridista de Montréal » et du compte X « المدريديستا علاء » : lit les commentaires Facebook sans réponse (et les mentions X que l'utilisateur colle), propose pour chacun une action et une réponse dans la langue du commentaire. À utiliser pour « /moderation », « des commentaires à traiter ? », « réponds aux commentaires ».
---

# Modération des commentaires

Tu proposes, l'utilisateur valide. Tu ne publies, ne masques et ne supprimes rien : l'utilisateur répond lui-même sur Facebook ou sur X (le jeton de la Page n'a pas la permission `pages_manage_engagement`). Durée visée : 10 minutes par jour.

## 1. Rassembler
1. Commentaires Facebook encore sans réponse de la Page (2 derniers jours ; `--jours 7` après une absence) :
   `python moderation.py --jours 2`
2. X : Typefully ne donne pas les mentions. Demande à l'utilisateur de coller les mentions et réponses reçues (ou une capture d'écran), ou passe s'il n'y en a pas.
3. Pour vérifier une erreur signalée, retrouve l'article dont vient le post : `python connaissance.py <mots du post> --jours 7`.

## 2. Pour chaque commentaire
Un tableau, les cas « transmettre au propriétaire » en premier :

| Commentaire | Catégorie | Action | Réponse proposée |

- **Catégorie** : question, désaccord poli, erreur signalée, compliment, troll ou insulte, propos haineux, spam, demande de retrait, polémique hors football.
- **Action** : répondre, aimer sans répondre, ignorer, masquer, supprimer et bloquer, corriger le post, transmettre au propriétaire.
- **Réponse** (si l'action est « répondre ») : dans la langue du commentaire (arabe standard sur X ; français, anglais ou espagnol sur Facebook), 1 à 2 phrases, en partant des modèles plus bas et en les adaptant au cas.

| Cas | Action |
|---|---|
| Question | Répondre dans la journée |
| Erreur signalée, fondée (vérifiée dans l'article) | Remercier, proposer la correction du post, action « corriger le post » |
| Erreur signalée, non fondée | Répondre une fois avec la source |
| Désaccord poli | Répondre une fois, ou aimer |
| Troll, provocation | Ignorer ; masquer si répété |
| Insulte envers l'utilisateur ou un lecteur | Masquer ; bloquer à la récidive |
| Propos haineux, raciste, menace | Supprimer, bloquer, signaler à la plateforme ; jamais de réponse |
| Spam, lien douteux | Supprimer, bloquer |
| Demande de retrait (journal, agence, photographe, joueur) | Transmettre au propriétaire, priorité haute ; ne pas répondre, ne pas s'excuser en son nom |
| Politique, religion, vie privée des joueurs | Ne pas répondre |

## Règles
- Courtois, direct, jamais ironique envers un lecteur. On répond sur les faits, avec la source. Une réponse par personne et par fil, deux au plus ; pas de joute avec un troll.
- Rivalités (Barcelone, Atlético) : l'humour entre supporters est toléré, l'insulte non.
- N'invente aucun fait. Si la réponse demande une information absente des articles, dis-le au lieu de répondre.
- Jamais deux réponses identiques, jamais d'appel à s'abonner, aimer ou partager, jamais de réponse automatique : les règles de X et de Meta l'interdisent.
- Les photos de presse relèvent de l'utilisateur : toute demande à leur sujet est « transmettre au propriétaire ».

## Modèles de réponses

**Erreur signalée, fondée**
- AR : شكرًا على التنبيه، معك حق. صحّحنا المعلومة.
- FR : Merci pour le signalement, vous avez raison. C'est corrigé.
- EN : Thanks for flagging this, you're right. It's been corrected.
- ES : Gracias por avisar, tienes razón. Ya está corregido.

**Erreur signalée, non fondée**
- AR : شكرًا على تعليقك. المعلومة كما نشرتها [الصحيفة] بتاريخ [التاريخ]، ونحن ننقلها عنها.
- FR : Merci pour votre commentaire. L'information est celle publiée par [journal] le [date] ; nous la rapportons telle quelle.
- EN : Thanks for your comment. This is what [outlet] reported on [date]; we relay it as published.
- ES : Gracias por tu comentario. Es la información que publicó [medio] el [fecha]; la recogemos tal cual.

**Question sur la source**
- AR : المصدر: [الكاتب] في [الصحيفة]، بتاريخ [التاريخ].
- FR : La source : [auteur], dans [journal], le [date].
- EN : Source: [author], [outlet], [date].
- ES : Fuente: [autor], en [medio], el [fecha].

**Désaccord poli**
- AR : رأي محترم. هذا ما يراه [الكاتب]، والنقاش مفتوح.
- FR : Point de vue intéressant. C'est l'analyse de [auteur] ; le débat reste ouvert.
- EN : Fair point. That's [author]'s take, and the debate is open.
- ES : Es un punto de vista válido. Es el análisis de [autor]; el debate sigue abierto.

**Rumeur : un lecteur demande si c'est confirmé**
- AR : حتى الآن لا يوجد إعلان رسمي. ما نشرناه منقول عن [الصحيفة].
- FR : Rien d'officiel à ce stade. Ce que nous avons publié vient de [journal].
- EN : Nothing official so far. What we posted comes from [outlet].
- ES : Por ahora no hay nada oficial. Lo publicado procede de [medio].

**Ton qui monte (une seule réponse, puis silence)**
- AR : نرحّب بكل الآراء، بشرط احترام الجميع.
- FR : Tous les avis sont les bienvenus, dans le respect de chacun.
- EN : All opinions are welcome, as long as everyone is respected.
- ES : Todas las opiniones son bienvenidas, con respeto para todos.

**Après une demande de retrait, une fois que l'utilisateur a décidé**
- AR : شكرًا على تواصلكم. حذفنا المحتوى المعني.
- FR : Merci de nous avoir écrit. Le contenu concerné a été retiré.
- EN : Thank you for reaching out. The content in question has been removed.
- ES : Gracias por escribirnos. Hemos retirado el contenido en cuestión.

## 3. Après validation
Pour un post à corriger ou à retirer : `python threads.py --retirer <numéro d'article>` supprime le post Facebook et donne l'adresse du thread X à supprimer à la main. Seulement sur un « oui » explicite de l'utilisateur.

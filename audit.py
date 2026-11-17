"""Audit de conformité du lundi, ajouté à l'issue « Revue des sources » : Claude relit un échantillon de 20 publications
de la semaine (threads X et posts Facebook) face à leur article, et signale les écarts. Ne modifie et ne supprime rien.

    python audit.py
"""
import json
import random
import sqlite3
import sys

import threads as t
from commun import CONFIG, DB_PATH, ErreurClaude, appeler_claude, restaurer_base

NB_THREADS, NB_FACEBOOK = 15, 5

PROMPT = """Tu es le contrôleur de conformité de « المدريديستا علاء » (compte X en arabe) et de la Page Facebook « Peña Madridista de Montréal »
(français, anglais, espagnol). Les contenus sont générés et publiés automatiquement, sans relecture ; tu vérifies après coup
un échantillon de la semaine. Pour chaque publication : le texte publié, la plateforme, et l'article du site dont il est tiré
(texte arabe, journal, auteur).

Vérifie chaque point :
1. Fidélité : chaque fait et chaque chiffre de la publication figure dans l'article. Aucune citation inventée ou modifiée.
2. Attribution : la source d'origine est nommée (journal, et auteur pour une opinion) ; une opinion est présentée comme celle de son auteur.
3. Rumeur : un transfert non confirmé est présenté comme tel (intérêt, contacts), jamais comme conclu.
4. Droit d'auteur : pas de reprise longue du texte d'origine ; citations courtes (moins de 25 mots chacune).
5. Étiquette : « 🚨 عاجل » seulement pour une vraie urgence ; « ✅ رسميًا » seulement pour une annonce du club ou d'une fédération.
6. Règles des plateformes : pas d'appel à aimer, partager ou s'abonner ; pas de texte identique à une autre publication de l'échantillon.
7. Personnes : rien de diffamatoire ni d'insultant (joueur, arbitre, journaliste, club), rien sur la vie privée.
8. Facebook : pas de lien vers un média quand le post a une image (loi C-18 au Canada).

Règles :
- Les images de presse jointes aux posts sont une décision assumée par le propriétaire : ne les signale pas.
- Si une règle de X ou de Meta a pu changer ou si tu n'es pas sûr, écris « incertain » et recommande l'option la plus prudente.
- Ne signale que les écarts. Réponds en français, en Markdown, sans titre de niveau 1 ni 2 : un tableau
  | Publication | Point | Gravité (faible, moyenne, élevée) | Écart constaté | Correction proposée |
  puis trois lignes de synthèse au plus. S'il n'y a aucun écart, écris seulement « Aucun écart sur cet échantillon. »

PUBLICATIONS
{publications}
"""


def echantillon(con, graine):
    """Publications de la semaine tirées au hasard (même tirage pour une même semaine) : (repère, plateforme, texte, article)."""
    hasard = random.Random(graine)
    t.connexion_threads(con)
    threads = con.execute(f"SELECT article_id, tweets FROM threads WHERE {t.ENVOYES}"
                          " AND date >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-7 days')").fetchall()
    try:
        facebook = con.execute("SELECT article_id FROM page_facebook WHERE coalesce(post, '') NOT LIKE 'bloqu%'"
                               " AND date >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-7 days')").fetchall()
    except sqlite3.OperationalError:  # table créée au premier post Facebook
        facebook = []
    choix = [("X", r[0], "\n---\n".join(json.loads(r[1]))) for r in hasard.sample(threads, min(NB_THREADS, len(threads)))]
    for r in hasard.sample(facebook, min(NB_FACEBOOK, len(facebook))):
        a = con.execute("SELECT * FROM articles WHERE id = ?", (r[0],)).fetchone()
        if a:
            if a["image"]:  # même forme que vers_page : photo + titres + journal, sans lien ; sinon titres + carte du lien
                texte = f"[photo de l'article jointe, aucun lien]\n{t.titres_facebook(a)}\n\nSource : {a['journal']}"
            else:
                texte = f"[sans image : titres en message, lien de la source en carte]\n{t.titres_facebook(a)}\n{a['lien']}"
            choix.append(("Facebook", r[0], texte))
    pubs = []
    for i, (plateforme, aid, texte) in enumerate(choix, 1):
        a = con.execute("SELECT * FROM articles WHERE id = ?", (aid,)).fetchone()
        if a:
            pubs.append(f"[{plateforme} n° {i}, article {aid}]\nTEXTE PUBLIÉ :\n{texte}\nARTICLE : {a['journal']}, "
                        f"{a['auteur_ar'] or a['auteur'] or 'non signé'}, rubrique {a['section']}\n{(a['texte'] or '')[:2500]}")
    return pubs


def audit(con, graine):
    lignes = ["", "## Audit de conformité (échantillon de la semaine)", ""]
    pubs = echantillon(con, graine)
    if not pubs:
        return "\n".join(lignes + ["Aucune publication cette semaine."])
    try:
        avis = appeler_claude(PROMPT.format(publications="\n\n".join(pubs)), CONFIG.get("modele_redaction", "sonnet")).strip()
    except ErreurClaude as err:
        return "\n".join(lignes + [f"Audit indisponible ({err})."])
    return "\n".join(lignes + [f"{len(pubs)} publications tirées au hasard. Rien n'a été modifié.", "", avis])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    restaurer_base(DB_PATH)
    base = sqlite3.connect(DB_PATH)
    base.row_factory = sqlite3.Row
    print(audit(base, t.maintenant().strftime("%G-%V")))  # graine : l'année et le numéro de semaine
    base.close()

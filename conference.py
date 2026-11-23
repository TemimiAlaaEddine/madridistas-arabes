"""Conférence de presse de l'entraîneur en direct (workflow conference_direct.yml, lancé par le passage principal) : dès qu'un
article « Mourinho: "..." » de Marca ou d'AS paraît, ce journal est suivi pour toute la conférence (l'autre est ignoré) ; son
flux est lu chaque minute et chaque nouvelle déclaration part tout de suite en tweet court, sans source. Pendant ce temps, les
autres nouvelles du passage principal vont dans la file Typefully au lieu de partir tout de suite.

    python conference.py --a-lancer        (passage principal : journal à suivre maintenant, ou rien)
    python conference.py --suivre Marca    (workflow dédié) ; --a-blanc : affiche les tweets sans les publier
"""
import calendar
import json
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone

import feedparser

from commun import BASE, CONFIG, ErreurClaude, appeler_claude, maintenant

ETAT = BASE / "conference.json"  # sessions de direct : journal suivi, articles déjà tweetés ; partagé avec le passage principal
FLUX = {"Marca": ["https://e00-marca.uecdn.es/rss/futbol/real-madrid.xml"],
        "AS": ["https://feeds.as.com/mrss-s/list/as/site/as.com/tag/real_madrid_a/",  # tag Real Madrid : 2 jours d'articles
               "https://feeds.as.com/mrss-s/pages/as/site/as.com/section/futbol/portada/"]}  # tout le football : vite renouvelé
INTERVALLE = 60
FRAIS = timedelta(minutes=30)  # un article plus vieux ne lance pas de direct
SILENCE = timedelta(minutes=10)  # fin du direct : 10 min sans nouvelle déclaration (20, jugé trop long le 23 nov.)
DUREE_MAX = timedelta(minutes=90)
MEME_CONFERENCE = timedelta(hours=3)  # pas de nouveau direct dans les 3 h qui suivent le début du précédent


def plat(texte):
    return unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode().lower()


def est_declaration(titre, resume=""):
    """« Mourinho: "..." » (forme de Marca), ou un titre qui n'est qu'une citation « “...” » dont le chapeau nomme l'entraîneur
    (forme d'AS). shortcut: une vieille phrase reprise ou une citation d'un autre peut passer ; Claude écarte ce qui n'est
    pas une déclaration de conférence (réponse HORS)."""
    nom = CONFIG.get("entraineur", "mourinho")
    return bool(re.match(rf"\s*(jose\s+)?{nom}\s*:", plat(titre))
                or (re.match(r"\s*[\"“«]", titre or "") and nom in plat(resume)))


def declarations(journal, depuis):
    """[(publié UTC, titre, lien, résumé)] des déclarations des flux de ce journal parues après `depuis`, de la plus ancienne à la plus récente."""
    sortie = {}
    for url in FLUX[journal]:
        for e in feedparser.parse(url).entries:
            pub = e.get("published_parsed") or e.get("updated_parsed")
            quand = datetime.fromtimestamp(calendar.timegm(pub), timezone.utc).replace(tzinfo=None) if pub else None
            if quand and quand >= depuis and est_declaration(e.get("title", ""), e.get("summary", "")):
                sortie.setdefault(e.get("link", ""), (quand, e.get("title", ""), e.get("link", ""), e.get("summary", "")))
    return sorted(sortie.values())


def lire_etat():
    try:
        return json.loads(ETAT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def session_recente(utc=None):
    """Dernière session commencée il y a moins de 3 h (même conférence), ou None."""
    utc = utc or maintenant()
    s = lire_etat()[-1:] or [None]
    return s[0] if s[0] and utc - datetime.fromisoformat(s[0]["debut"]) < MEME_CONFERENCE else None


def en_direct(utc=None):
    """Un direct de conférence est-il en cours ? Le passage principal envoie alors les autres nouvelles dans la file Typefully."""
    s = session_recente(utc)
    return bool(s and not s.get("fini"))


def a_lancer(utc=None):
    """Journal à suivre en direct maintenant (le premier, de Marca ou AS, à publier une déclaration fraîche), ou ""."""
    from calendrier import direct_actif
    utc = utc or maintenant()
    if session_recente(utc) or direct_actif("conference_direct.yml"):
        return ""
    premiers = [(d[0][0], j) for j in FLUX if (d := declarations(j, utc - FRAIS))]
    return min(premiers)[1] if premiers else ""


PROMPT = """Tu écris en direct, pour le compte X « المدريديستا علاء » (supporters arabes du Real Madrid), un tweet sur une déclaration
de {nom} en conférence de presse, à partir de l'article ci-dessous.

Forme, en arabe :
ligne 1 : « 🎙️ مؤتمر {nom_ar} | » puis la déclaration forte que l'article met en avant, traduite fidèlement entre «».
ligne vide, puis la question du journaliste traduite exactement, si l'article la donne (sinon une phrase de contexte tirée de
l'article : le match, le sujet ; une question absente de l'article n'est jamais inventée).
ligne vide, puis la réponse complète de {nom} à cette question, traduite exactement entre «», sans la résumer ni la couper.
ligne vide, puis : #{hashtag} #ريال_مدريد
Pas de source, pas de média cité, pas de lien, aucun autre émoji, aucun fait absent de l'article. Pas de limite de longueur (tweet long).

Déjà publiés pendant cette conférence :
{deja}

Si l'article ne rapporte pas une déclaration de {nom} faite aujourd'hui en conférence de presse, réponds seulement HORS.
Si la déclaration mise en avant est la même qu'un tweet déjà publié, réponds seulement DOUBLON.
Sinon, réponds UNIQUEMENT avec le texte du tweet.

ARTICLE
Titre : {titre}
{texte}
"""


def tweet(titre, texte, deja):
    """Texte du tweet, ou None (doublon d'une déclaration déjà tweetée, ou article hors conférence)."""
    nom = CONFIG.get("entraineur", "mourinho")
    nom_ar = CONFIG.get("personnes", {}).get(nom, {}).get("nom", nom)
    r = appeler_claude(PROMPT.format(nom=nom.capitalize(), nom_ar=nom_ar, hashtag=nom_ar.replace(" ", "_"), titre=titre,
                                     texte=texte[:6000], deja="\n---\n".join(deja) or "(aucun)"),
                       CONFIG.get("modele_redaction", "sonnet"), "low").strip()
    return None if not r or "DOUBLON" in r[:20] or r[:10].strip() == "HORS" else r


def tweet_de_fin(utc):
    """« 🎙️ نهاية المؤتمر الصحفي لمورينيو قبل/بعد مباراة ريال مدريد و... » d'après matchs.json : un match commencé il y a moins
    de 6 h -> conférence d'après-match, sinon celle d'avant le prochain match."""
    from calendrier import FICHIER, nom_arabe_claude
    nom = CONFIG.get("entraineur", "mourinho")
    nom_ar = CONFIG.get("personnes", {}).get(nom, {}).get("nom", nom)
    try:
        matchs = sorted(json.loads(FICHIER.read_text(encoding="utf-8")), key=lambda m: m["debut"])
    except (OSError, ValueError):
        matchs = []
    apres = [m for m in matchs if timedelta(0) <= utc - datetime.fromisoformat(m["debut"]) < timedelta(hours=6)]
    avant = [m for m in matchs if datetime.fromisoformat(m["debut"]) > utc]
    m, quand = (apres[-1], "بعد") if apres else (avant[0], "قبل") if avant else (None, "")
    texte = f"🎙️ نهاية المؤتمر الصحفي ل{nom_ar}"
    if m:
        equipes = [("ريال مدريد" if e.strip() == "Real Madrid" else nom_arabe_claude(e.strip())) for e in m["match"].split(" vs ")]
        texte += f" {quand} مباراة {' و'.join(equipes)}"
    return f"{texte}\n\n#{nom_ar.replace(' ', '_')} #ريال_مدريد"


def sauver(etat, message):
    """Pousse conference.json dans le dépôt : le passage principal y voit le direct en cours et les articles déjà tweetés."""
    ETAT.write_text(json.dumps(etat, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    try:
        for cmd in (["git", "add", ETAT.name], ["git", "commit", "-q", "-m", message],
                    ["git", "pull", "-q", "--rebase", "--autostash"], ["git", "push", "-q"]):
            subprocess.run(cmd, capture_output=True, timeout=60, check=True, cwd=BASE)
    except (OSError, subprocess.SubprocessError) as err:  # le tweet est parti ; seul le partage avec le passage principal tarde
        print(f"  ! conference.json non poussé ({err})")


def deja_publies(depuis):
    """(liens, tweets) des conférences déjà parties par le passage principal (celui qui a lancé le direct a pu publier la
    première déclaration juste avant)."""
    import sqlite3
    from commun import DB_PATH, restaurer_base
    from threads import ENVOYES
    restaurer_base(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    try:
        lignes = con.execute(f"SELECT a.lien, t.tweets FROM threads t JOIN articles a ON a.id = t.article_id WHERE {ENVOYES}"
                             " AND a.mode = 'conference' AND t.envoye >= ?", (depuis.isoformat(timespec="seconds"),)).fetchall()
    except sqlite3.OperationalError:  # base vide (premier passage) : rien de publié
        lignes = []
    con.close()
    return [l for l, _ in lignes], [json.loads(tw)[0] for _, tw in lignes]


def suivre(journal, publier=True, dormir=time.sleep, horloge=None, sauvegarder=None):
    """Lit le flux de `journal` chaque minute et tweete chaque nouvelle déclaration, jusqu'à 10 min sans déclaration (90 min au plus)."""
    import threads
    from generer_site import texte_complet
    horloge = horloge or maintenant
    etat = lire_etat()
    enregistrer = lambda message: (sauvegarder or (sauver if publier else (lambda e, m: None)))(etat, message)
    debut = horloge()
    liens, tweets = deja_publies(debut - FRAIS)
    session = {"journal": journal, "debut": debut.isoformat(timespec="seconds"), "liens": liens, "tweets": tweets, "fini": False}
    etat.append(session)
    enregistrer(f"Conférence en direct : suivie sur {journal}")
    derniere = debut
    while horloge() - derniere < SILENCE and horloge() - debut < DUREE_MAX:
        h = horloge().strftime("%H:%M:%S")
        try:
            nouvelles = [d for d in declarations(journal, debut - FRAIS) if d[2] not in session["liens"]]
            if not nouvelles:  # signe de vie dans le journal du workflow
                print(f"{h} aucune nouvelle déclaration ({journal}), fin dans {(SILENCE - (horloge() - derniere)).seconds // 60} min sans déclaration")
            for quand, titre, lien, resume in nouvelles:
                session["liens"].append(lien)  # noté avant l'envoi : un tweet raté n'est pas retenté en boucle
                it = {"lien": lien, "texte_flux": resume, "type": "conference"}
                texte = tweet(titre, texte_complet(it), session["tweets"])
                derniere = horloge()
                if not texte:
                    print(f"{h} écarté (doublon ou hors conférence) : {titre[:80]}")
                    continue
                if publier:
                    post = {"text": texte}
                    try:  # photo de l'article sur le 1er tweet de la conférence seulement ; il part sans elle si elle est refusée
                        media = (threads.typefully_image(*threads.telecharger_image(it["image"], f"conf-{len(session['liens'])}"))
                                 if it.get("image") and not session["tweets"] else None)
                        if media:
                            post["media_ids"] = [media]
                    except (OSError, ValueError, KeyError) as err:
                        print(f"{h} ! photo refusée ({err})")
                    threads.typefully_api("drafts", {"draft_title": f"مؤتمر {titre[:80]}", "publish_at": "now",
                                                     "platforms": {"x": {"enabled": True, "posts": [post]}}})
                session["tweets"].append(texte)
                print(f"{h} >> tweet{'' if publier else ' (à blanc)'} :\n   " + texte.replace("\n", "\n   "))
                enregistrer(f"Conférence en direct : {len(session['tweets'])} déclaration(s)")
        except (OSError, ValueError, KeyError, ErreurClaude) as err:  # lecture ou envoi raté : minute suivante
            print(f"{h} ! {err!r} : réessayé dans {INTERVALLE} s")
        dormir(INTERVALLE)
    if session["tweets"]:  # la conférence a été tweetée : on annonce sa fin
        fin = tweet_de_fin(horloge())
        try:
            if publier:
                threads.typefully_api("drafts", {"draft_title": "نهاية المؤتمر", "publish_at": "now",
                                                 "platforms": {"x": {"enabled": True, "posts": [{"text": fin}]}}})
            print(f">> tweet de fin{'' if publier else ' (à blanc)'} :\n   " + fin.replace("\n", "\n   "))
        except (OSError, KeyError) as err:
            print(f"! tweet de fin impossible ({err})")
    session["fini"] = True
    session["fin"] = horloge().isoformat(timespec="seconds")
    enregistrer(f"Conférence en direct : fin ({len(session['tweets'])} déclarations)")
    print(f"Fin du direct ({journal}) : {len(session['tweets'])} tweet(s)")
    return session


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:2] == ["--a-lancer"]:
        print(a_lancer())
    elif sys.argv[1:2] == ["--suivre"]:
        suivre(sys.argv[2], publier="--a-blanc" not in sys.argv)

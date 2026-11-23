"""Conférence de presse de l'entraîneur en direct (workflow conference_direct.yml, lancé par le passage principal). Lancement :
- avant-match : à l'heure de l'entraînement que le calendrier du club annonce suivi d'une conférence (« Rueda de prensa: sí ») ;
  les flux de Marca et d'AS sont lus chaque minute, le premier des deux à publier une déclaration est suivi seul ensuite ;
- après-match : à la première déclaration dont l'article parle de la salle de presse (les interviews télé d'avant la
  conférence passent par le passage normal) ;
- sinon : à la première déclaration « Mourinho: "..." » de Marca ou d'AS.
Chaque déclaration part tout de suite en tweet (question et réponse traduites), sans source ; pendant le direct, les autres
nouvelles du passage principal sont retenues jusqu'à la fin.

    python conference.py --a-lancer        (passage principal : Marca, AS, auto, ou rien)
    python conference.py --suivre auto     (workflow dédié) ; --a-blanc : affiche les tweets sans les publier
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
DUREE_MAX = timedelta(minutes=90)  # après la première déclaration
# avant-match : de l'heure de l'entraînement à la première déclaration, au plus (23 nov. : entraînement 11 h, conférence vers
# 13 h 10, premier article d'AS à 13 h 38, heure de Madrid ; 2 h 30 aurait coupé trop tôt)
ATTENTE = timedelta(hours=3, minutes=30)
# le calendrier du club retire l'entraînement dès qu'il commence (vu le 23 nov.) : le direct est lancé avant et attend l'heure
AVANCE = timedelta(minutes=45)
ATTENTE_DETECTION = timedelta(minutes=30)  # direct lancé sur un article : attente d'une vraie déclaration de conférence
APRES_MATCH = (timedelta(hours=1, minutes=30), timedelta(hours=4))  # après le coup d'envoi : fenêtre de la conférence d'après-match
MEME_CONFERENCE = timedelta(hours=6)  # même conférence : un direct peut durer 45 min + 3 h 30 + 90 min


def plat(texte):
    return unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode().lower()


def est_declaration(titre, resume=""):
    """Titre qui commence par l'entraîneur et contient une citation (« Mourinho: "..." », « Mourinho responde a Comesaña:
    “...” », « Mourinho y el calendario: "..." », vus le 23 nov.), ou titre qui n'est qu'une citation dont le chapeau le nomme
    (forme d'AS). shortcut: une vidéo d'entraînement ou une vieille phrase passe aussi ; Claude écarte ce qui n'est pas une
    déclaration de conférence (réponse HORS)."""
    nom = CONFIG.get("entraineur", "mourinho")
    titre = titre or ""
    return bool((re.match(rf"\s*(jose\s+)?{nom}\b", plat(titre)) and re.search(r"[\"“”«]", titre))
                or (re.match(r"\s*[\"“«]", titre) and nom in plat(resume)))


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
    """La conférence a-t-elle commencé (première déclaration tweetée, journal choisi) sans être finie ? Le passage principal
    retient alors les autres nouvelles. L'attente d'avant la conférence ne compte pas."""
    s = session_recente(utc)
    return bool(s and not s.get("fini") and s.get("journal"))


def apres_match(utc):
    """Un match de matchs.json a-t-il commencé il y a 1 h 30 à 4 h ? (fenêtre de la conférence d'après-match)"""
    from calendrier import FICHIER
    try:
        matchs = json.loads(FICHIER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any(APRES_MATCH[0] <= utc - datetime.fromisoformat(m["debut"]) < APRES_MATCH[1] for m in matchs)


def en_salle_de_presse(lien, resume):
    """L'article rapporte-t-il la conférence (salle de presse), et non une interview télé d'après-match (Movistar, DAZN...) ?"""
    from generer_site import texte_complet
    texte = texte_complet({"lien": lien, "texte_flux": resume, "type": "conference"})
    return bool(re.search(r"rueda de prensa|sala de prensa|conferencia de prensa", plat(texte)))


def a_lancer(utc=None, page=None):
    """Ce que le direct doit faire maintenant (le journal est toujours choisi à la première vraie déclaration) :
    "auto <heure UTC>" : conférence d'avant-match annoncée, entraînement dans moins de 45 min (le direct attend cette heure) ;
    "auto" : une déclaration vient de paraître (après un match : seulement si elle vient de la salle de presse) ; "" : rien.
    Une session finie sans aucun tweet (faux départ) n'empêche pas d'en lancer une autre."""
    from calendrier import URL, conferences, direct_actif
    from commun import lire_page
    utc = utc or maintenant()
    s = session_recente(utc)
    if (s and (not s.get("fini") or s.get("tweets"))) or direct_actif("conference_direct.yml"):
        return ""
    try:
        prevues = conferences(page if page is not None else lire_page(URL), utc)
    except OSError as err:  # calendrier illisible : on garde la détection par les déclarations
        print(f"  ! calendrier du club illisible ({err})")
        prevues = []
    proches = [h for h in prevues if utc < h <= utc + AVANCE]
    if proches:
        return f"auto {proches[0].isoformat()}"
    salle = apres_match(utc)
    if any(not salle or en_salle_de_presse(d[2], d[3]) for j in FLUX for d in declarations(j, utc - FRAIS)):
        return "auto"
    return ""


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

Si l'article ne rapporte pas une déclaration de {nom} faite aujourd'hui en conférence de presse (en salle de presse : une
interview télé au bord du terrain ou en zone mixte, Movistar, DAZN, Real Madrid TV, n'en est pas une), réponds seulement HORS.
Si la déclaration mise en avant est la même qu'un tweet déjà publié, réponds seulement DOUBLON.
Sinon, réponds UNIQUEMENT avec le texte du tweet.

ARTICLE
Titre : {titre}
{texte}
"""


def tweet(titre, texte, deja):
    """Texte du tweet, ou "DOUBLON" (déclaration déjà tweetée) ou "HORS" (pas une déclaration de la conférence : interview
    télé, vieille phrase... ; elle passe alors par le passage normal)."""
    nom = CONFIG.get("entraineur", "mourinho")
    nom_ar = CONFIG.get("personnes", {}).get(nom, {}).get("nom", nom)
    r = appeler_claude(PROMPT.format(nom=nom.capitalize(), nom_ar=nom_ar, hashtag=nom_ar.replace(" ", "_"), titre=titre,
                                     texte=texte[:6000], deja="\n---\n".join(deja) or "(aucun)"),
                       CONFIG.get("modele_redaction", "sonnet"), "low").strip()
    return "DOUBLON" if "DOUBLON" in r[:20] else "HORS" if not r or r[:10].strip() == "HORS" else r


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


def suivre(journal, publier=True, dormir=time.sleep, horloge=None, sauvegarder=None, heure=None):
    """Lit chaque minute le flux de `journal` ("auto" : Marca et AS jusqu'à la première déclaration, puis ce journal seul) et
    tweete chaque nouvelle déclaration. heure (UTC) : entraînement annoncé avec conférence, attendu avant de commencer.
    Avant la première déclaration : attente jusqu'à 3 h 30 après l'entraînement (30 min pour un direct lancé sur un
    article) ; ensuite, jusqu'à 10 min sans déclaration (90 min au plus après la première), puis le tweet de fin."""
    import threads
    from generer_site import texte_complet
    horloge = horloge or maintenant
    if heure and heure > horloge():
        print(f"Attente de l'entraînement ({heure:%H:%M} UTC) : {(heure - horloge()).seconds // 60} min")
        dormir((heure - horloge()).total_seconds())
    attente = ATTENTE if heure else ATTENTE_DETECTION
    if publier:  # base et conference.json à jour après l'attente (le passage principal a pu publier entre-temps)
        subprocess.run(["git", "pull", "-q", "--rebase", "--autostash"], capture_output=True, timeout=60, cwd=BASE)
    etat = lire_etat()
    enregistrer = lambda message: (sauvegarder or (sauver if publier else (lambda e, m: None)))(etat, message)
    debut = horloge()
    limite = max((heure or debut) + attente, debut + ATTENTE_DETECTION)  # fin de l'attente de la première déclaration
    liens, tweets = deja_publies(debut - FRAIS)
    suivi = None if journal == "auto" else journal
    # liens : tweetés ou doublons (le passage principal les écarte) ; vus : tous ceux déjà lus, HORS compris
    session = {"journal": suivi, "debut": debut.isoformat(timespec="seconds"), "liens": liens, "vus": list(liens),
               "tweets": tweets, "fini": False}
    etat.append(session)
    enregistrer(f"Conférence en direct : suivie sur {suivi}" if suivi else "Conférence en direct : attente de la conférence")
    premiere = derniere = debut if suivi or tweets else None
    while True:
        instant = horloge()
        if premiere is None and instant >= limite:
            print("Pas de déclaration : fin de l'attente")
            break
        if premiere is not None and (instant - derniere >= SILENCE or instant - premiere >= DUREE_MAX):
            break
        h = instant.strftime("%H:%M:%S")
        try:
            journaux = [session["journal"]] if session["journal"] else list(FLUX)
            nouvelles = sorted(d + (j,) for j in journaux for d in declarations(j, debut - FRAIS) if d[2] not in session["vus"])
            if not nouvelles:  # signe de vie dans le journal du workflow
                print(f"{h} en attente de la conférence (jusqu'à {limite:%H:%M} UTC)" if premiere is None else
                      f"{h} aucune nouvelle déclaration ({session['journal']}), fin dans "
                      f"{(SILENCE - (instant - derniere)).seconds // 60} min sans déclaration")
            for quand, titre, lien, resume, j in nouvelles:
                if session["journal"] and j != session["journal"]:
                    continue  # journal choisi plus tôt dans cette même lecture
                session["vus"].append(lien)  # noté avant l'envoi : un tweet raté n'est pas retenté en boucle
                it = {"lien": lien, "texte_flux": resume, "type": "conference"}
                texte = tweet(titre, texte_complet(it), session["tweets"])
                if texte == "HORS":
                    print(f"{h} hors conférence, laissé au passage normal : {titre[:80]}")
                    continue
                session["liens"].append(lien)
                derniere = horloge()
                if texte == "DOUBLON":
                    print(f"{h} doublon écarté : {titre[:80]}")
                    continue
                if not session["journal"]:
                    session["journal"] = j
                    print(f"{h} conférence commencée : suivie sur {j}")
                premiere = premiere or derniere
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
    print(f"Fin du direct ({session['journal'] or 'aucun journal'}) : {len(session['tweets'])} tweet(s)")
    return session


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:2] == ["--a-lancer"]:
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):  # seule la réponse va sur la sortie : le workflow la lit
            reponse = a_lancer()
        print(reponse)
    elif sys.argv[1:2] == ["--suivre"]:  # --suivre auto|Marca|AS [--heure <UTC>] [--a-blanc]
        a = sys.argv
        h = a[a.index("--heure") + 1] if "--heure" in a and a[a.index("--heure") + 1:] else ""
        suivre(a[2], publier="--a-blanc" not in a, heure=datetime.fromisoformat(h) if h else None)

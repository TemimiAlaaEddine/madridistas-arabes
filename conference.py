"""Conférence de presse de l'entraîneur en direct (workflow conference_direct.yml, lancé par le passage principal). Lancement :
- avant-match : 1 h 30 avant l'entraînement que le calendrier du club annonce avec une conférence (« Rueda de prensa: sí ») ;
  surveillance dès le lancement (la conférence peut précéder l'entraînement, 27 nov.) : direct écrit d'AS, et flux de Marca
  et d'AS tant que ce direct n'a rien donné ; le premier des deux journaux à publier une déclaration est suivi seul ensuite ;
- après-match : à la première déclaration dont l'article parle de la salle de presse (les interviews télé d'avant la
  conférence passent par le passage normal) ;
- sinon : à la première déclaration « Mourinho: "..." » de Marca ou d'AS.
Chaque déclaration part tout de suite en tweet (question et réponse traduites), sans source ; pendant le direct, les autres
nouvelles du passage principal sont retenues jusqu'à la fin.

    python conference.py --a-lancer        (passage principal : Marca, AS, auto, ou rien)
    python conference.py --suivre auto     (workflow dédié) ; --a-blanc : affiche les tweets sans les publier
"""
import calendar
import html
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import feedparser

from commun import BASE, CONFIG, ErreurClaude, appeler_claude, maintenant, plat

ETAT = BASE / "conference.json"  # sessions de direct : journal suivi, articles déjà tweetés ; partagé avec le passage principal
FLUX = {"Marca": ["https://e00-marca.uecdn.es/rss/futbol/real-madrid.xml"],
        "AS": ["https://feeds.as.com/mrss-s/list/as/site/as.com/tag/real_madrid_a/",  # tag Real Madrid : 2 jours d'articles
               "https://feeds.as.com/mrss-s/pages/as/site/as.com/section/futbol/portada/"]}  # tout le football : vite renouvelé
INTERVALLE = 60
FRAIS = timedelta(minutes=30)  # un article plus vieux ne lance pas de direct
# fin du direct : 15 min sans nouvelle déclaration (direct écrit d'AS du 23 nov. : 4 min au plus entre deux réponses, 2 min
# au changement d'orateur Courtois -> Mourinho)
SILENCE = timedelta(minutes=15)
# direct écrit d'AS (« Rueda de prensa de Mourinho y Courtois ... en directo ») : chaque réponse 1 à 2 min après, avec la
# question ; listé sur sa page Real Madrid dès sa création ; la page du direct refuse le programme (403) : lue par Bright Data
LISTE_AS = "https://as.com/noticias/real-madrid/"
DIRECT_AS = re.compile(r"https://as\.com/[\w/-]*rueda-de-prensa[\w-]*-d/")
UNITE = re.compile(r'<div id="([0-9a-f]{32})"[^>]*?data-sort-time="(\d+)"[^>]*?class="ev-unit[^"]*"[^>]*>(.*?)(?=<div id="[0-9a-f]{32}"|\Z)', re.S)
VIEUX_DIRECT = timedelta(hours=12)  # un direct sans entrée depuis 12 h est celui d'une autre conférence
DUREE_MAX = timedelta(minutes=90)  # après la première déclaration
# avant-match : attente de la première déclaration, au plus, comptée de l'heure de l'entraînement (23 nov. : entraînement 11 h,
# conférence vers 13 h 10, heure de Madrid)
ATTENTE = timedelta(hours=2, minutes=30)
# le calendrier du club ne donne pas l'heure de la conférence et retire l'entraînement dès qu'il commence ; la conférence peut
# venir AVANT lui (27 nov. : 9 h 57 - 10 h 22 pour un entraînement à 10 h 30, heure de Madrid, manquée par un direct qui dormait
# jusqu'à l'entraînement) : le direct est lancé 1 h 30 avant et surveille dès son lancement (1 h 30 + 2 h 30 + 90 min de
# direct < 6 h, limite d'un job GitHub)
AVANCE = timedelta(hours=1, minutes=30)
ATTENTE_DETECTION = timedelta(minutes=30)  # direct lancé sur un article : attente d'une vraie déclaration de conférence
APRES_MATCH = (timedelta(hours=1, minutes=30), timedelta(hours=4))  # après le coup d'envoi : fenêtre de la conférence d'après-match
# direct d'après-match (choix de l'utilisateur, 24 nov.) : lancé 2 h 30 après le coup d'envoi, ou 30 min après la fin réelle
# du match si elle est plus tardive (prolongation ; fin notée par le suivi du match dans direct.json)
APRES_DEBUT = timedelta(hours=2, minutes=30)
APRES_FIN = timedelta(minutes=30)
MATCH_LONG = timedelta(hours=3, minutes=30)  # suivi du match pas fini au-delà : planté, on n'attend plus sa fin
ATTENTE_APRES = timedelta(hours=1, minutes=30)  # après-match : du lancement à la première déclaration, au plus
MEME_CONFERENCE = timedelta(hours=6)  # même conférence : un direct peut durer 45 min + 3 h 30 + 90 min


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


def entrees_direct(page):
    """[(id, publié UTC, question, texte)] d'un direct écrit d'AS, du plus ancien au plus récent ; question "" pour une entrée
    de commentaire (« Comienza la rueda de prensa », « Y hasta aquí, Courtois »)."""
    net = lambda h: html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))).strip()
    sortie = {}
    for id_, ms, bloc in UNITE.findall(page):
        bloc = bloc.split('<div class="ev-foo')[0]  # sans le pied de l'entrée (« Comenta ») ni le reste de la page
        q = re.search(r'<p class="ev-title">(.*?)</p>', bloc, re.S)
        q, corps = (net(q[1]) if q else ""), net(re.sub(r'<p class="ev-title">.*?</p>', " ", bloc, flags=re.S))
        # 27 nov. : AS n'écrit plus la question, seulement « Thème : “réponse” » (« Lesionados : “Mendy mañana va al banquillo” ») ;
        # sans ce cas, toutes les réponses passaient pour des commentaires
        theme = None if q else re.match(r"([^:“”\"«»]{2,60}?)\s*:\s*([“\"«].+)", corps, re.S)
        if theme:
            q, corps = f"Thème : {theme[1].strip()}", theme[2]
        sortie.setdefault(id_, (id_, datetime.fromtimestamp(int(ms) / 1000, timezone.utc).replace(tzinfo=None),
                                q, corps))  # entrée épinglée : deux fois dans la page
    return sorted(sortie.values(), key=lambda e: e[1])


def lire_direct(url):
    from match import bright_data
    return entrees_direct(bright_data(url))


def trouver_direct_as(utc, vus):
    """URL du direct écrit d'AS sur une conférence, listé sur sa page Real Madrid, ou None. Un vieux direct encore listé va
    dans `vus` : il ne coûte pas une requête Bright Data par minute."""
    from commun import lire_page
    for url in dict.fromkeys(DIRECT_AS.findall(lire_page(LISTE_AS))):
        if url not in vus:
            if any(e[1] >= utc - VIEUX_DIRECT for e in lire_direct(url)):
                return url
            vus.append(url)
    return None


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


def debut_apres_match(utc):
    """Heure (UTC) de lancement du direct d'après-match si elle est passée depuis moins de 1 h 30, sinon None : coup d'envoi
    + 2 h 30, ou fin réelle + 30 min si plus tard ; rien tant que le suivi du match n'a pas vu la fin. Heure de match fixée seulement."""
    from calendrier import FICHIER, lire_direct
    try:
        matchs = json.loads(FICHIER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    direct = lire_direct()
    for m in matchs:
        if not m.get("heure_fixee"):
            continue
        coup_envoi, suivi = datetime.fromisoformat(m["debut"]), direct.get(m["debut"]) or {}
        if suivi and not suivi.get("fini") and utc < coup_envoi + MATCH_LONG:
            continue  # prolongation en cours
        t = max(coup_envoi + APRES_DEBUT, datetime.fromisoformat(suivi["fin_a"]) + APRES_FIN if suivi.get("fin_a") else coup_envoi)
        if t <= utc < t + ATTENTE_APRES:
            return t
    return None


def en_salle_de_presse(lien, resume):
    """L'article rapporte-t-il la conférence (salle de presse), et non une interview télé d'après-match (Movistar, DAZN...) ?"""
    from generer_site import texte_complet
    texte = texte_complet({"lien": lien, "texte_flux": resume, "type": "conference"})
    return bool(re.search(r"rueda de prensa|sala de prensa|conferencia de prensa", plat(texte)))


RECENTE = timedelta(hours=30)  # deux conférences du même entraîneur sont espacées de 35 h au moins (après-match puis avant-match)


def conference_recente(utc):
    """Une conférence a-t-elle été tweetée depuis moins de 30 h (direct ou passage principal, étiquette « 🎙️ ») ? Une
    déclaration qui paraît alors en vient : 28 nov., un article d'AS tiré de la conférence de la veille a lancé un direct, et
    Claude, qui ne peut pas savoir la date, l'a tweetée comme du direct, tweet de fin compris, le jour du match."""
    if any(x.get("tweets") and utc - datetime.fromisoformat(x["debut"]) < RECENTE for x in lire_etat()):
        return True
    import sqlite3
    from commun import DB_PATH, restaurer_base
    from threads import ENVOYES, est_conference
    restaurer_base(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    try:
        lignes = con.execute(f"SELECT tweets FROM threads WHERE {ENVOYES} AND envoye >= ?",
                             ((utc - RECENTE).isoformat(timespec="seconds"),)).fetchall()
    except sqlite3.OperationalError:  # base vide (premier passage)
        lignes = []
    con.close()
    return any(est_conference(json.loads(tw)[0]) for (tw,) in lignes)


def a_lancer(utc=None, page=None):
    """Ce que le direct doit faire maintenant (le journal est toujours choisi à la première vraie déclaration) :
    "auto <heure UTC>" : conférence d'avant-match annoncée, entraînement dans moins de 1 h 30 (surveillé dès le lancement),
    ou conférence d'après-match, heure de debut_apres_match passée depuis moins de 1 h 30 ;
    "auto" : une déclaration vient de paraître (après un match : seulement si elle vient de la salle de presse) ; "" : rien.
    Une session finie sans aucun tweet (faux départ) n'empêche pas d'en lancer une autre ; une session qui a tweeté bloque le
    reste de la journée (heure de Madrid) : une seule conférence par jour."""
    from calendrier import URL, conferences, direct_actif
    from commun import lire_page
    from threads import heure_madrid
    utc = utc or maintenant()
    s = session_recente(utc)
    if (s and (not s.get("fini") or s.get("tweets"))) or direct_actif("conference_direct.yml"):
        return ""
    jour = heure_madrid(utc).date()
    if any(x.get("tweets") and heure_madrid(datetime.fromisoformat(x["debut"])).date() == jour for x in lire_etat()):
        return ""
    try:
        prevues = conferences(page if page is not None else lire_page(URL), utc)
    except OSError as err:  # calendrier illisible : on garde la détection par les déclarations
        print(f"  ! calendrier du club illisible ({err})")
        prevues = []
    proches = [h for h in prevues if utc < h <= utc + AVANCE]
    if proches:
        return f"auto {proches[0].isoformat()}"
    fin = debut_apres_match(utc)
    if fin:  # après-match : lancé 2 h 30 après le coup d'envoi (ou 30 min après une prolongation), il attend la conférence
        return f"auto {fin.isoformat()}"
    salle = apres_match(utc)
    if not salle and conference_recente(utc):
        return ""
    vus = {lien for x in lire_etat() for lien in x.get("vus", [])}  # article republié avec une date fraîche (AS, 23 nov.)
    if any(d[2] not in vus and (not salle or en_salle_de_presse(d[2], d[3])) for j in FLUX for d in declarations(j, utc - FRAIS)):
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


PROMPT_DIRECT = """Tu écris en direct, pour le compte X « المدريديستا علاء » (supporters arabes du Real Madrid), un tweet sur une
réponse donnée en conférence de presse du Real Madrid, d'après le direct écrit d'AS ci-dessous.

Forme, en arabe :
ligne 1 : « 🎙️ مؤتمر <nom de l'orateur en arabe> | » puis la phrase la plus forte de la réponse, traduite fidèlement entre «».
ligne vide, puis la question du journaliste traduite exactement ; si le direct ne donne qu'un thème (« Thème : … »), une
courte ligne de contexte sur ce thème (عن إصابة ميندي...), jamais une question inventée.
ligne vide, puis la réponse complète traduite exactement entre «», sans la résumer ni la couper (les indications entre
parenthèses, rires ou pauses, peuvent être omises).
ligne vide, puis : #<nom de l'orateur en arabe, espaces remplacés par _> #ريال_مدريد
Pas de source, pas de média cité, pas de lien, aucun autre émoji, aucun fait absent du direct. Pas de limite de longueur.
Noms arabes connus : {noms}

L'orateur se déduit du fil : le direct annonce chaque orateur (« Y hasta aquí, Courtois. ¡LLEGA THE SPECIAL ONE! » : Mourinho
parle ensuite). Si tu ne peux pas savoir qui parle, ou si l'entrée n'est pas une réponse de la conférence, réponds seulement HORS.
Sinon, réponds UNIQUEMENT avec le texte du tweet.

FIL DU DIRECT (entrées précédentes, de la plus ancienne à la plus récente) :
{fil}

ENTRÉE À TWEETER
Question : {question}
Réponse : {reponse}
"""


def tweet_direct(entree, fil):
    """Tweet d'une réponse du direct écrit d'AS (question et réponse traduites, orateur déduit du fil), ou "HORS"."""
    noms = ", ".join(f"{k.capitalize()} = {v['nom']}" for k, v in CONFIG.get("personnes", {}).items()
                     if isinstance(v, dict) and v.get("nom"))
    fil = "\n".join(f"- {'Q : ' + q + ' / R : ' if q else ''}{t[:300]}" for _, _, q, t in fil) or "(début du direct)"
    r = appeler_claude(PROMPT_DIRECT.format(noms=noms or "(aucun)", fil=fil, question=entree[2], reponse=entree[3][:6000]),
                       CONFIG.get("modele_redaction", "sonnet"), "low").strip()
    return "HORS" if not r or r[:10].strip() == "HORS" else r


def orateurs(tweets):
    """Noms arabes des orateurs, dans l'ordre, d'après la 1re ligne des tweets (« 🎙️ مؤتمر كورتوا | ... »)."""
    return list(dict.fromkeys(m[1].strip() for t in tweets if (m := re.match(r"🎙️ مؤتمر (.+?)\s*\|", t))))


SUITE = """
CET ARTICLE A ÉTÉ COMPLÉTÉ depuis les tweets déjà publiés : ne prends pas la déclaration mise en avant par le titre, mais la
première réponse de {nom} en salle de presse qui n'est dans aucun tweet déjà publié (question et réponse comme ci-dessus).
S'il n'y en a aucune, réponds seulement DOUBLON.
"""


def tweet(titre, texte, deja, suite=False):
    """Texte du tweet, ou "DOUBLON" (déclaration déjà tweetée) ou "HORS" (pas une déclaration de la conférence : interview
    télé, vieille phrase... ; elle passe alors par le passage normal). suite=True : article relu, réponse suivante."""
    nom = CONFIG.get("entraineur", "mourinho")
    nom_ar = CONFIG.get("personnes", {}).get(nom, {}).get("nom", nom)
    prompt = PROMPT.replace("\nARTICLE\n", SUITE.format(nom=nom.capitalize()) + "\nARTICLE\n") if suite else PROMPT
    r = appeler_claude(prompt.format(nom=nom.capitalize(), nom_ar=nom_ar, hashtag=nom_ar.replace(" ", "_"), titre=titre,
                                     texte=texte[:12000], deja="\n---\n".join(deja) or "(aucun)"),
                       CONFIG.get("modele_redaction", "sonnet"), "low").strip()
    return "DOUBLON" if "DOUBLON" in r[:20] else "HORS" if not r or r[:10].strip() == "HORS" else r


def tweet_de_fin(utc, noms=None):
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
    noms = noms or [nom_ar]  # orateurs du direct (Mourinho et un joueur), sinon l'entraîneur
    texte = "🎙️ نهاية المؤتمر الصحفي ل" + " و".join(noms)
    if m:
        equipes = [("ريال مدريد" if e.strip() == "Real Madrid" else nom_arabe_claude(e.strip())) for e in m["match"].split(" vs ")]
        texte += f" {quand} مباراة {' و'.join(equipes)}"
    return texte + "\n\n" + " ".join(f"#{n.replace(' ', '_')}" for n in noms) + " #ريال_مدريد"


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
    """Lit chaque minute le direct écrit d'AS dès qu'il est listé (une réponse tweetée par minute, orateurs successifs compris),
    et, tant qu'il n'a rien tweeté, le flux de `journal` ("auto" : Marca et AS jusqu'à la première déclaration, puis ce
    journal seul), et tweete chaque nouvelle déclaration. heure (UTC) : entraînement annoncé avec conférence (surveillance dès
    le lancement, la conférence peut le précéder). Avant la première déclaration : attente jusqu'à 2 h 30 après
    l'entraînement (30 min pour un direct lancé sur un article) ; ensuite, jusqu'à 15 min sans déclaration (90 min au plus
    après la première), puis le tweet de fin. session["alerte"] : direct écrit d'AS qui avance sans déclaration reconnue."""
    import threads
    from generer_site import texte_complet
    horloge = horloge or maintenant
    # heure = fin d'un match (après-match) : 1 h 30 ; heure = entraînement (avant-match) : 2 h 30 ; lancé sur un article : 30 min
    attente = (ATTENTE_APRES if apres_match(heure) else ATTENTE) if heure else ATTENTE_DETECTION
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

    def suite(r, corps):
        """Réponse suivante d'un article relu, ou HORS (rien de nouveau : le texte actuel ne sera plus soumis à Claude)."""
        texte = tweet(r["titre"], corps, session["tweets"], suite=True)
        if texte in ("HORS", "DOUBLON"):  # DOUBLON compté comme HORS : il ne prolonge pas le direct
            r["long"] = len(corps)
            return "HORS"
        return texte

    while True:
        instant = horloge()
        if premiere is None and instant >= limite:
            print("Pas de déclaration : fin de l'attente")
            break
        if premiere is not None and (instant - derniere >= SILENCE or instant - premiere >= DUREE_MAX):
            break
        h = instant.strftime("%H:%M:%S")
        try:
            nouvelles = []
            try:  # direct écrit d'AS : une réponse par minute (rattrapage compris)
                if not session.get("direct_as"):
                    session["direct_as"] = trouver_direct_as(instant, session["vus"])
                if session["direct_as"]:
                    entrees = lire_direct(session["direct_as"])
                    # entrées de la séance (commentaires compris) : un direct qui avance sans réponse reconnue donne l'alerte
                    session["entrees"] = max(session.get("entrees", 0), sum(e[1] >= debut - FRAIS for e in entrees))
                    reponses = [e for e in entrees if e[2] and e[1] >= debut - FRAIS and e[0] not in session["vus"]]
                    nouvelles = [(e[1], e[2], e[0], "", "AS", lambda e=e: tweet_direct(e, [x for x in entrees if x[1] < e[1]][-8:]))
                                 for e in reponses[:1]]
            except (OSError, ValueError, subprocess.SubprocessError) as err:  # les articles restent lus
                print(f"{h} ! direct écrit d'AS illisible ({err!r})")
            # articles de Marca et d'AS, aussi en repli tant que le direct écrit n'a rien tweeté (27 nov. : seule la page d'AS
            # était lue, son format avait changé, l'article de Marca de 10 h 31 n'a pas été vu)
            if not session.get("direct_ok"):
                journaux = [session["journal"]] if session["journal"] else list(FLUX)
                nouvelles += [d + (None,) for d in sorted(d + (j,) for j in journaux for d in declarations(j, debut - FRAIS)
                                                          if d[2] not in session["vus"])]
                # article complété au fil de la conférence (AS après le PSV, 24 nov.) : relu chaque minute tant qu'il grandit,
                # 15 min au plus sans changement (coût Bright Data quand la page est refusée)
                for lien, r in session.get("relus", {}).items():
                    if (session["journal"] in (None, r["journal"]) and instant - datetime.fromisoformat(r["vu"]) < SILENCE
                            and len(corps := texte_complet({"lien": lien, "texte_flux": "", "type": "conference"})) > r["long"]):
                        r["vu"] = instant.isoformat(timespec="seconds")
                        nouvelles.append((instant, r["titre"], lien, "", r["journal"], lambda r=r, corps=corps: suite(r, corps)))
            if not nouvelles:  # signe de vie dans le journal du workflow
                print(f"{h} en attente de la conférence (jusqu'à {limite:%H:%M} UTC)" if premiere is None else
                      f"{h} aucune nouvelle déclaration ({session['journal']}), fin dans "
                      f"{(SILENCE - (instant - derniere)).seconds // 60} min sans déclaration")
            for quand, titre, lien, resume, j, rediger in nouvelles:
                if session["journal"] and j != session["journal"] and not rediger:
                    continue  # journal choisi plus tôt dans cette même lecture (le direct écrit d'AS passe toujours)
                session["vus"].append(lien)  # noté avant l'envoi : un tweet raté n'est pas retenté en boucle
                it = {"lien": lien, "texte_flux": resume, "type": "conference"}
                if not rediger:
                    corps = texte_complet(it)
                    session.setdefault("relus", {})[lien] = {"titre": titre, "journal": j, "long": len(corps),
                                                             "vu": instant.isoformat(timespec="seconds")}
                texte = rediger() if rediger else tweet(titre, corps, session["tweets"])
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
                if re.fullmatch(r"[0-9a-f]{32}", lien):  # entrée du direct écrit d'AS : il fonctionne, plus besoin du repli
                    session["direct_ok"] = True
                print(f"{h} >> tweet{'' if publier else ' (à blanc)'} :\n   " + texte.replace("\n", "\n   "))
                enregistrer(f"Conférence en direct : {len(session['tweets'])} déclaration(s)")
        except (OSError, ValueError, KeyError, ErreurClaude, subprocess.SubprocessError) as err:  # lecture ou envoi raté : minute suivante
            print(f"{h} ! {err!r} : réessayé dans {INTERVALLE} s")
        dormir(INTERVALLE)
    if session["tweets"]:  # la conférence a été tweetée : on annonce sa fin
        fin = tweet_de_fin(horloge(), orateurs(session["tweets"]))
        try:
            if publier:
                threads.typefully_api("drafts", {"draft_title": "نهاية المؤتمر", "publish_at": "now",
                                                 "platforms": {"x": {"enabled": True, "posts": [{"text": fin}]}}})
            print(f">> tweet de fin{'' if publier else ' (à blanc)'} :\n   " + fin.replace("\n", "\n   "))
        except (OSError, KeyError) as err:
            print(f"! tweet de fin impossible ({err})")
    elif session.get("entrees", 0) >= 3:  # 27 nov. : 13 entrées dans la séance, 0 tweet, et le workflow finissait en succès
        session["alerte"] = (f"! ALERTE : le direct écrit d'AS a avancé ({session['entrees']} entrées) sans aucune déclaration "
                             f"reconnue : format de la page changé ? {session['direct_as']}")
        print(session["alerte"])
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
        if suivre(a[2], publier="--a-blanc" not in a, heure=datetime.fromisoformat(h) if h else None).get("alerte"):
            sys.exit(1)  # workflow en rouge : GitHub prévient le propriétaire du dépôt

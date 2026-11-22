"""Analyse d'après-match automatique (GitHub Actions, .github/workflows/apres_match.yml), déclenchée par le workflow principal
(mise_a_jour.yml, lancé toutes les 5 min par cron-job.org) dès qu'un match est à analyser ; la planification GitHub reste en secours.

Usage : python apres_match.py            (analyse le match fini, s'il y en a un)
        python apres_match.py --a-faire  (affiche le match à analyser, ou rien : le workflow n'installe Claude Code que si besoin)
Les matchs viennent de matchs.json (calendrier.py, revue du lundi). 2 h 30 après le coup d'envoi, Claude Code lance /match en
mode automatique et écrit le thread et les tweets joueurs dans scripts/ ; ce script les dépose ensuite en brouillons dans Typefully
(API, sans date : le thread, puis un brouillon par joueur).
Heure pas encore fixée : on attend 23 h 30 UTC le jour du match. 3 essais par match, espacés de 30 min au moins (WhoScored met parfois du
temps à publier les stats), rattrapage pendant 2 jours. Suivi dans suivi_matchs.json (enregistré dans le dépôt).
Secrets GitHub : CLAUDE_CODE_OAUTH_TOKEN, TYPEFULLY_API_KEY, BRIGHTDATA_API_TOKEN.
"""
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from threads import CONFIG, LIMITE_LONG, heure_madrid, longueur, typefully_api, typefully_image

BASE = Path(__file__).parent
SUIVI = BASE / "suivi_matchs.json"
ATTENTE = timedelta(hours=2, minutes=30)  # coup d'envoi + 2 h 30 : match fini, stats publiées
ESSAIS = 3
ESPACEMENT = timedelta(minutes=30)  # entre deux essais : le workflow principal peut relancer l'analyse toutes les 5 min
OUTILS = ["Bash(python *)", "Read", "Grep", "Glob", "Edit(scripts/**)", "WebSearch", "WebFetch", "Agent", "Skill"]
CONSIGNE = ("/match --date {date}\n\nMode automatique (GitHub Actions) : personne ne répond. Lance `python match.py --date {date}`. "
            "Thread X en arabe, construit selon les étapes 2 (lecture du match en 6 étapes : récit, périodes, bascules, phases, joueurs ; idées fortes tirées des périodes et des phases) et 3 de /match. Ne pose aucune question, ne modifie pas connaissance.md, saute l'étape 6 et ne "
            "dépose rien dans Typefully : écris seulement le fichier dans scripts/ (étape 4). Forme du fichier : le titre « # … » "
            "et une ligne de contexte, puis une ligne « --- », puis les paragraphes séparés par des lignes « --- » (sans numérotation ; ils seront réunis en un seul tweet long),"
            "puis les sections « ## » (accroches, hashtags, sources). Graphiques : match.py en liste quelques-uns (chemin et "
            "contenu) ; places-en 2 à 4 dans le thread, chacun sur sa propre ligne « [graphique: <chemin>] » à la fin du tweet "
            "dont il illustre le propos (un par paragraphe ; tous seront joints au tweet long). "
            "Écris aussi les tweets joueurs (étape 4 de /match, un tweet par joueur de la sélection de l'étape 6) dans "
            "scripts/<date>-joueurs-<adversaire>.md, même forme, posts longs de 500 à 1 000 caractères, avec la photo du joueur (ligne « [photo: <chemin>] », étape 4 de /match). "
            "Termine ta réponse par les lignes « JOUEURS: scripts/<nom>.md » puis « FICHIER: scripts/<nom>.md » (le thread).")
GRAPHIQUE = re.compile(r"^\[(?:graphique|photo):\s*([^\]]+?)\s*\]\s*$", re.M)  # photo : celle du joueur (tweets joueurs)


def cle(m):
    return f"{m['match']} | {m['debut'][:10]}"


def moment(m):
    """Quand lancer l'analyse (UTC) : coup d'envoi + 2 h 30, ou 23 h 30 UTC le jour même si l'heure n'est pas fixée."""
    d = datetime.fromisoformat(m["debut"])
    return (d if m["heure_fixee"] else d.replace(hour=21, minute=0)) + ATTENTE


def date_madrid(m):
    d = datetime.fromisoformat(m["debut"])
    return (heure_madrid(d) if m["heure_fixee"] else d).date().isoformat()


def a_analyser(matchs, suivi, utc):
    """Matchs finis depuis moins de 2 jours, pas encore analysés, moins de 3 essais, dernier essai il y a 30 min au moins."""
    def pret(s):
        return not s.get("fait") and s.get("essais", 0) < ESSAIS and (
            "dernier" not in s or utc - datetime.fromisoformat(s["dernier"]) >= ESPACEMENT)
    return [m for m in matchs if utc - timedelta(days=2) < moment(m) <= utc and pret(suivi.get(cle(m), {}))]


def tweets_du_fichier(texte):
    """[(tweet, [chemins des graphiques])] d'un fichier de scripts/ écrit selon CONSIGNE : entre le premier « --- » et la
    première section « ## » ; les lignes « [graphique: …] » sont retirées du texte du tweet."""
    blocs = [b.strip() for b in texte.split("\n## ")[0].split("\n---\n")[1:] if b.strip()]
    images = [GRAPHIQUE.findall(b) for b in blocs]
    tweets = [GRAPHIQUE.sub("", b).strip() for b in blocs]
    if not 2 <= len(tweets) <= 30:
        raise ValueError(f"{len(tweets)} tweets lus dans le fichier")
    if longueur("\n\n".join(tweets)) > LIMITE_LONG:
        raise ValueError("texte trop long pour un tweet long")
    return list(zip(tweets, images))


def analyser(m):
    """Lien du brouillon Typefully, ou ValueError avec la raison de l'échec."""
    exe = shutil.which("claude")
    if not exe:
        raise ValueError("Claude Code introuvable")
    try:
        r = subprocess.run([exe, "-p", CONSIGNE.format(date=date_madrid(m)), "--allowedTools", *OUTILS], cwd=BASE,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", timeout=1800)
    except subprocess.TimeoutExpired:
        raise ValueError("pas de réponse de Claude en 30 minutes")
    print(r.stdout[-3000:])
    fichier = re.search(r"FICHIER:\s*(scripts/[^\s`*]+\.md)", r.stdout)
    if r.returncode != 0 or not fichier:
        raise ValueError((r.stderr or r.stdout).strip()[-300:] or f"code {r.returncode}")
    tweets = tweets_du_fichier((BASE / fichier.group(1)).read_text(encoding="utf-8"))
    post = {"text": "\n\n".join(t for t, _ in tweets)}  # un seul tweet long, un paragraphe par bloc du fichier
    ids = []
    for c in [c for _, images in tweets for c in images][:CONFIG.get("max_images_tweet", 4)]:
        try:
            ids.append(typefully_image(Path(c).name, (BASE / c).read_bytes()))
        except (OSError, KeyError, ValueError) as err:
            print(f"! graphique {c} non joint : {err}")
    if any(ids):  # image refusée ou pas prête à temps : le tweet part sans elle
        post["media_ids"] = [x for x in ids if x]
    d = typefully_api("drafts", {"draft_title": f"تحليل {m['match']} ({date_madrid(m)})",
                                 "platforms": {"x": {"enabled": True, "posts": [post]}}})  # sans publish_at : simple brouillon
    lien = f"https://typefully.com/?d={d['id']}&a={CONFIG['typefully_social_set']}"
    return lien + deposer_joueurs(m, r.stdout)


def deposer_joueurs(m, sortie):
    """Un brouillon Typefully par tweet joueur (sans numérotation ni date) ; jamais bloquant : le thread est déjà déposé."""
    f = re.search(r"JOUEURS:\s*(scripts/[^\s`*]+\.md)", sortie)
    if not f:
        return " ; tweets joueurs : fichier absent"
    try:
        tweets = tweets_du_fichier((BASE / f.group(1)).read_text(encoding="utf-8"))
        for i, (t, images) in enumerate(tweets, 1):
            post = {"text": t}
            ids = []
            for c in images:
                try:
                    ids.append(typefully_image(Path(c).name, (BASE / c).read_bytes()))
                except (OSError, KeyError, ValueError) as err:
                    print(f"! photo {c} non jointe : {err}")
            if any(ids):  # photo refusée : le tweet part sans elle
                post["media_ids"] = [x for x in ids if x]
            typefully_api("drafts", {"draft_title": f"أداء {i}/{len(tweets)} - {m['match']} ({date_madrid(m)})",
                                     "platforms": {"x": {"enabled": True, "posts": [post]}}})
        return f" ; {len(tweets)} tweets joueurs en brouillon"
    except (OSError, ValueError, KeyError) as err:
        return f" ; tweets joueurs non déposés ({err})"


def charger():
    matchs = json.loads((BASE / "matchs.json").read_text(encoding="utf-8"))
    suivi = json.loads(SUIVI.read_text(encoding="utf-8")) if SUIVI.exists() else {}
    return matchs, suivi


def passage(utc=None):
    utc = utc or datetime.now(timezone.utc).replace(tzinfo=None)
    matchs, suivi = charger()
    for m in a_analyser(matchs, suivi, utc)[:1]:  # un match par passage
        s = suivi.setdefault(cle(m), {"fait": False, "essais": 0})
        s["essais"] += 1
        s["dernier"] = utc.isoformat(timespec="minutes")
        try:
            s["resultat"], s["fait"] = analyser(m), True
        except (OSError, ValueError, KeyError) as err:
            detail = err.read().decode("utf-8", "replace")[:300] if hasattr(err, "read") else ""
            s["resultat"] = f"! {err} {detail}".strip()
        print(f"{m['match']} ({date_madrid(m)}, essai {s['essais']}) : {s['resultat']}")
        SUIVI.write_text(json.dumps(suivi, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["--a-faire"]:
        matchs, suivi = charger()
        print(" ; ".join(m["match"] for m in a_analyser(matchs, suivi, datetime.now(timezone.utc).replace(tzinfo=None))[:1]))
    else:
        passage()

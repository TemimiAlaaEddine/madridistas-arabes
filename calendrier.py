"""Revue du lundi : les 5 prochains matchs du Real Madrid, lus sur la page calendrier du site officiel (une seule requête,
sans Claude) et gardés dans matchs.json. Le tri s'en sert pour la règle « pendant un match » (match_en_cours)."""
import json
import re
from datetime import datetime, timedelta

from commun import BASE, ErreurClaude, appeler_claude, lire_page, maintenant

URL = "https://www.realmadrid.com/es-ES/futbol/calendario"
FICHIER = BASE / "matchs.json"
DUREE = timedelta(hours=2, minutes=30)  # prolongation et arrêts de jeu compris
MI_TEMPS = re.compile(r"half|break|descanso|interval|pause|^ht$", re.I)  # nom de l'état sur la page, deviné
# chaque match est un objet JSON de la page : "Real Madrid vs Celta de Vigo", coup d'envoi en UTC, heure fixée ou non (date seule)
MATCH = re.compile(r'"description":\{"plaintext":"([^"]+)"\},"week":[^,]*,"weekAsText":[^,]*,"dateTime":"([^"]+)",'
                   r'"dateTxt":[^,]*,"isScheduled":(true|false),"status":"pre_match"')


def prochains(page, apres, n=5):
    vus = {(nom, date[:19], fixe == "true") for nom, date, fixe in MATCH.findall(page)}  # chaque match apparaît deux fois
    matchs = sorted((d, nom, fixe) for nom, d, fixe in vus if datetime.fromisoformat(d) > apres)
    return [{"match": nom, "debut": d, "heure_fixee": fixe} for d, nom, fixe in matchs[:n]]


def match_courant(utc):
    """Le match de matchs.json en cours (du coup d'envoi à 2 h 30 après, heure fixée seulement), sinon None."""
    try:
        matchs = json.loads(FICHIER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return next((m for m in matchs if m["heure_fixee"] and datetime.fromisoformat(m["debut"]) <= utc
                 < datetime.fromisoformat(m["debut"]) + DUREE), None)


def match_en_cours(utc=None):
    """Consigne ajoutée au tri pendant un match du Real Madrid, sinon ""."""
    from threads import heure_madrid
    m = match_courant(utc or maintenant())
    if not m:
        return ""
    return (f"\nMATCH EN COURS : {m['match']} (coup d'envoi à {heure_madrid(datetime.fromisoformat(m['debut'])):%H:%M}, heure de Madrid)."
            " Écarte les faits de jeu (actions, occasions, cartons, buts racontés en direct) ; garde en revanche la composition"
            " officielle, les déclarations d'avant-match, le résultat de la mi-temps (score et buteurs), le résultat final (score et"
            " buteurs) et les déclarations d'après-match.\n")


def etat(page, debut):
    """(statut, équipe à domicile, son score, équipe à l'extérieur, son score) du match qui commence à `debut` (UTC), lus dans
    la page calendrier ; score None tant qu'il n'est pas affiché. Un match y a deux formes : la fiche des matchs à venir (celle
    de MATCH) et la ligne des résultats, seule restante une fois le match fini ; on ne sait pas laquelle porte le direct."""
    d = re.escape(debut) + r'\.000Z"'
    equipes = (r'.{0,4000}?"homeTeam":\{.{0,2000}?"name":"([^"]+)".{0,500}?"homeTeamScoreTotal":(?:null|"(\d+)")'
               r'.{0,500}?"awayTeam":\{.{0,2000}?"name":"([^"]+)".{0,500}?"awayTeamScoreTotal":(?:null|"(\d+)")')
    for forme in (r'"status":"(\w+)","dateTime":"' + d, r'"dateTime":"' + d + r',"dateTxt":[^,]*,"isScheduled":\w+,"status":"(\w+)"'):
        if m := re.search(forme + equipes, page, re.S):
            return m.groups()
    return None


def nom_arabe(nom):
    if nom == "Real Madrid":
        return "ريال مدريد"
    try:
        ar = appeler_claude(f"Écris le nom usuel en arabe du club de football « {nom} », et rien d'autre.", "haiku", "low").strip()
    except ErreurClaude:
        return nom
    return ar if len(ar) < 40 and re.search(r"[؀-ۿ]", ar) else nom


def suivre_match(con, utc=None):
    """Pendant un match (fenêtre de match_courant), à chaque passage : l'état lu sur la page calendrier est noté dans
    suivi_match quand il change ; à la mi-temps, le score part tout de suite sur X, une seule fois. Sans buteurs : la page ne
    les donne pas (homeScorers vide, même après le match).
    shortcut: nom de l'état « mi-temps » deviné (MI_TEMPS) faute d'avoir vu un match en cours, à corriger d'après suivi_match."""
    import threads
    utc = utc or maintenant()
    m = match_courant(utc)
    if not m:
        return 0
    try:
        e = etat(lire_page(URL), m["debut"])
    except OSError as err:
        print(f"  ! suivi du match : page calendrier illisible ({err})")
        return 0
    if not e:
        print(f"  ! suivi du match : {m['match']} introuvable sur la page calendrier")
        return 0
    statut, dom, sd, ext, se = e
    score = f"{sd}-{se}" if sd is not None and se is not None else ""
    con.execute("CREATE TABLE IF NOT EXISTS suivi_match (debut TEXT, vu TEXT, statut TEXT, score TEXT, typefully TEXT)")
    dernier = con.execute("SELECT statut, score FROM suivi_match WHERE debut = ? ORDER BY rowid DESC LIMIT 1", (m["debut"],)).fetchone()
    if tuple(dernier or ()) != (statut, score):
        con.execute("INSERT INTO suivi_match VALUES (?, ?, ?, ?, NULL)", (m["debut"], utc.isoformat(timespec="seconds"), statut, score))
        con.commit()
    print(f"  Suivi du match : {dom} {score or '?'} {ext}, statut « {statut} »")
    if (not score or not MI_TEMPS.search(statut) or not threads.reglage("typefully_api_key")
            or con.execute("SELECT 1 FROM suivi_match WHERE debut = ? AND typefully IS NOT NULL", (m["debut"],)).fetchone()):
        return 0
    texte = f"⏸️ نهاية الشوط الأول\n\n{nom_arabe(dom)} {sd} - {se} {nom_arabe(ext)}\n\n#ريال_مدريد"
    try:
        d = threads.typefully_api("drafts", {"draft_title": f"Mi-temps {m['match']}", "publish_at": "now",
                                             "platforms": {"x": {"enabled": True, "posts": [{"text": texte}]}}})
    except (OSError, KeyError) as err:  # repris au passage suivant, tant que la page affiche la mi-temps
        print(f"  ! suivi du match : envoi de la mi-temps impossible ({err}), repris au prochain passage")
        threads.noter(con, "Mi-temps", str(err))
        return 0
    con.execute("UPDATE suivi_match SET typefully = ? WHERE rowid = (SELECT max(rowid) FROM suivi_match WHERE debut = ?)",
                (str(d["id"]), m["debut"]))
    con.commit()
    threads.noter(con, "Mi-temps")
    return 1


if __name__ == "__main__":
    from threads import heure_madrid
    print("\n## Calendrier (site officiel)\n")
    try:
        matchs = prochains(lire_page(URL), maintenant())
        probleme = "aucun match trouvé sur la page (structure changée ?)"
    except OSError as err:
        matchs, probleme = [], f"page calendrier illisible ({err})"
    if not matchs:
        print(f"⚠️ {probleme} : matchs.json gardé tel quel.")
    else:
        FICHIER.write_text(json.dumps(matchs, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        for m in matchs:
            h = heure_madrid(datetime.fromisoformat(m["debut"]))
            print(f"- {m['match']} : {h:%d/%m} " + (f"à {h:%H:%M} (heure de Madrid)" if m["heure_fixee"] else "(heure pas encore fixée)"))

"""Revue du lundi : les 5 prochains matchs du Real Madrid, lus sur la page calendrier du site officiel (une seule requête,
sans Claude) et gardés dans matchs.json. Le tri s'en sert pour la règle « pendant un match » (match_en_cours)."""
import json
import re
from functools import lru_cache
from datetime import datetime, timedelta, timezone

from commun import BASE, ErreurClaude, appeler_claude, lire_page, maintenant

URL = "https://www.realmadrid.com/es-ES/futbol/calendario"
FICHIER = BASE / "matchs.json"
DUREE = timedelta(hours=2, minutes=30)  # prolongation et arrêts de jeu compris
SOFA_EQUIPE = 2829  # Real Madrid sur Sofascore
MI_TEMPS = 31  # status.code Sofascore de la mi-temps (« Halftime ») ; « 1st half » est 6, « 2nd half » 7
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


def evenement(debut):
    """Le match du Real qui commence à `debut` (UTC), tel que Sofascore le donne (la page du club restait sur « live » 0-0 et
    sans mi-temps pendant Real-Celta, le 21 nov.) ; None si absent. En direct, le match est dans events/next ; fini, dans
    events/last. Écart de 3 h toléré si le coup d'envoi a bougé."""
    from match import sofascore  # Edge, sinon Bright Data (serveurs de GitHub)
    ts = datetime.fromisoformat(debut).replace(tzinfo=timezone.utc).timestamp()
    for sens in ("next", "last"):
        for e in sofascore(f"team/{SOFA_EQUIPE}/events/{sens}/0").get("events", []):
            if abs(e["startTimestamp"] - ts) < 3 * 3600:
                return e
    return None


def arabe(objet):
    """Traduction arabe donnée par Sofascore (équipe ou joueur), sinon None."""
    return (objet.get("fieldTranslations") or {}).get("nameTranslation", {}).get("ar")


@lru_cache
def nom_arabe_claude(nom):
    try:
        ar = appeler_claude(f"Écris le nom usuel en arabe du club de football « {nom} », et rien d'autre.", "haiku", "low").strip()
    except ErreurClaude:
        return nom
    return ar if len(ar) < 40 and re.search(r"[؀-ۿ]", ar) else nom


def nom_arabe(equipe):
    if equipe.get("id") == SOFA_EQUIPE:
        return "ريال مدريد"
    return arabe(equipe) or nom_arabe_claude(equipe["name"])


def joueur(incident):
    p = incident.get("player") or {}
    return arabe(p) or p.get("name") or incident.get("playerName") or "?"


def minute(incident):
    return f"{incident['time']}+{incident['addedTime']}'" if incident.get("addedTime") else f"{incident['time']}'"


def tweets_du_match(e, incidents):
    """[(clé, texte)] des tweets que l'état du match appelle, dans l'ordre : début, buts et cartons rouges (chronologiques),
    mi-temps, fin. L'appelant écarte les clés déjà parties."""
    dom, ext = nom_arabe(e["homeTeam"]), nom_arabe(e["awayTeam"])
    real_dom = e["homeTeam"].get("id") == SOFA_EQUIPE
    adversaire = ext if real_dom else dom
    statut, tag = e["status"], "\n\n#ريال_مدريد"
    score = f"{dom} {e.get('homeScore', {}).get('current', 0)} - {e.get('awayScore', {}).get('current', 0)} {ext}"
    tweets, buts, avant = [], [], (0, 0)
    if statut.get("type") == "inprogress":  # pas de « coup d'envoi » rattrapé une fois le match fini
        tweets.append(("début", f"▶️ انطلاق المباراة\n\n{dom} - {ext}{tag}"))
    for i in sorted(incidents, key=lambda i: (i.get("time", 0), i.get("addedTime") or 0)):
        cle = f"{i.get('id') or minute(i)}"
        if i.get("incidentType") == "goal":
            apres = (i.get("homeScore", avant[0]), i.get("awayScore", avant[1]))
            # côté qui marque d'après le score (sûr même pour un but contre son camp), sinon isHome
            domicile = apres[0] > avant[0] if apres != avant else bool(i.get("isHome"))
            avant = apres
            pour_real = domicile == real_dom
            ligne = f"{joueur(i)} {minute(i)}" + {"penalty": " (ركلة جزاء)", "ownGoal": " (ضد مرماه)"}.get(i.get("incidentClass"), "")
            buts.append(f"⚽ {ligne}" + ("" if pour_real else f" ({adversaire})"))
            courant = f"{dom} {apres[0]} - {apres[1]} {ext}"
            texte = f"⚽🔥 هدددف لريال مدريد!\n\n{ligne}\n\n{courant}" if pour_real else f"⚽ هدف لـ{adversaire}\n\n{ligne}\n\n{courant}"
            tweets.append((f"but:{cle}", texte + tag))
        elif i.get("incidentType") == "card" and i.get("incidentClass") in ("red", "yellowRed"):
            equipe = dom if i.get("isHome") else ext
            second = " (إنذار ثانٍ)" if i["incidentClass"] == "yellowRed" else ""
            tweets.append((f"rouge:{cle}", f"🟥 بطاقة حمراء\n\n{joueur(i)} ({equipe}) {minute(i)}{second}{tag}"))
    if statut.get("code") == MI_TEMPS:
        tweets.append(("mi-temps", f"⏸️ نهاية الشوط الأول\n\n{score}{tag}"))
    if statut.get("type") == "finished":
        tweets.append(("fin", f"🏁 نهاية المباراة\n\n{score}" + ("\n\n" + "\n".join(buts) if buts else "") + tag))
    return tweets


def suivre_match(con, utc=None):
    """Pendant un match (fenêtre de match_courant), à chaque passage : l'état lu sur Sofascore est noté dans suivi_match quand
    il change, et les tweets du direct partent tout de suite sur X, chacun une seule fois (table tweets_match) : coup
    d'envoi, chaque but (célébré si c'est le Real), chaque carton rouge, mi-temps, fin avec les buteurs."""
    import subprocess
    import threads
    from match import sofascore
    utc = utc or maintenant()
    m = match_courant(utc)
    if not m:
        return 0
    try:
        e = evenement(m["debut"])
        incidents = ([] if not e or e["status"].get("type") == "notstarted"
                     else sofascore(f"event/{e['id']}/incidents").get("incidents", []))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as err:  # Bright Data refuse parfois : passage suivant
        print(f"  ! suivi du match : Sofascore illisible ({err})")
        return 0
    if not e:
        print(f"  ! suivi du match : {m['match']} introuvable sur Sofascore")
        return 0
    statut = e["status"].get("description") or e["status"].get("type")
    sd, se = e.get("homeScore", {}).get("current"), e.get("awayScore", {}).get("current")
    score = f"{sd}-{se}" if sd is not None and se is not None else ""
    con.execute("CREATE TABLE IF NOT EXISTS suivi_match (debut TEXT, vu TEXT, statut TEXT, score TEXT, typefully TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS tweets_match (debut TEXT, cle TEXT, typefully TEXT, PRIMARY KEY (debut, cle))")
    dernier = con.execute("SELECT statut, score FROM suivi_match WHERE debut = ? ORDER BY rowid DESC LIMIT 1", (m["debut"],)).fetchone()
    if tuple(dernier or ()) != (statut, score):
        con.execute("INSERT INTO suivi_match VALUES (?, ?, ?, ?, NULL)", (m["debut"], utc.isoformat(timespec="seconds"), statut, score))
        con.commit()
    print(f"  Suivi du match : {e['homeTeam']['name']} {score or '?'} {e['awayTeam']['name']}, statut « {statut} »")
    if not threads.reglage("typefully_api_key"):
        return 0
    deja = {r[0] for r in con.execute("SELECT cle FROM tweets_match WHERE debut = ?", (m["debut"],))}
    n = 0
    for cle, texte in tweets_du_match(e, incidents):
        if cle in deja:
            continue
        try:
            d = threads.typefully_api("drafts", {"draft_title": f"{cle} {m['match']}", "publish_at": "now",
                                                 "platforms": {"x": {"enabled": True, "posts": [{"text": texte}]}}})
        except (OSError, KeyError) as err:  # repris au passage suivant, dans l'ordre
            print(f"  ! suivi du match : tweet « {cle} » impossible ({err}), repris au prochain passage")
            threads.noter(con, "Suivi du match", str(err))
            return n
        con.execute("INSERT INTO tweets_match VALUES (?, ?, ?)", (m["debut"], cle, str(d["id"])))
        con.commit()
        n += 1
    if n:
        threads.noter(con, "Suivi du match")
    return n


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

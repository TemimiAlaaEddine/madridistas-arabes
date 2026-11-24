"""Revue du lundi : les 5 prochains matchs du Real Madrid, lus sur la page calendrier du site officiel (une seule requête,
sans Claude) et gardés dans matchs.json. Le tri s'en sert pour la règle « pendant un match » (match_en_cours)."""
import json
import re
import subprocess
import sys
import time
from functools import lru_cache
from datetime import datetime, timedelta, timezone

from commun import BASE, ErreurClaude, appeler_claude, lire_page, maintenant

URL = "https://www.realmadrid.com/es-ES/futbol/calendario"
FICHIER = BASE / "matchs.json"
DUREE = timedelta(hours=2, minutes=30)  # prolongation et arrêts de jeu compris
SOFA_EQUIPE = 2829  # Real Madrid sur Sofascore
MI_TEMPS = 31  # status.code Sofascore de la mi-temps (« Halftime ») ; « 1st half » est 6, « 2nd half » 7
DIRECT = BASE / "direct.json"  # tweets du direct déjà partis, par match : partagé entre le suivi dédié et le passage principal
PAUSE_MI_TEMPS = 12 * 60  # suivi dédié : pas de lecture pendant la mi-temps (15 min), reprise avant le 2e coup d'envoi
INTERVALLE = 60  # suivi dédié : une lecture de Sofascore par minute (un but est tweeté 1 à 2 min après, délai de Sofascore compris)
# chaque match est un objet JSON de la page : "Real Madrid vs Celta de Vigo", coup d'envoi en UTC, heure fixée ou non (date seule)
MATCH = re.compile(r'"description":\{"plaintext":"([^"]+)"\},"week":[^,]*,"weekAsText":[^,]*,"dateTime":"([^"]+)",'
                   r'"dateTxt":[^,]*,"isScheduled":(true|false),"status":"pre_match"')


def prochains(page, apres, n=5):
    vus = {(nom, date[:19], fixe == "true") for nom, date, fixe in MATCH.findall(page)}  # chaque match apparaît deux fois
    matchs = sorted((d, nom, fixe) for nom, d, fixe in vus if datetime.fromisoformat(d) > apres)
    return [{"match": nom, "debut": d, "heure_fixee": fixe} for d, nom, fixe in matchs[:n]]


# entraînement suivi d'une conférence : « "tv":{"html":"<p>Rueda de prensa: sí, Mourinho y un jugador, después del entrenamiento" »
# shortcut: suit l'ordre des champs vu le 23 nov. (dateTime, dateTxt, eventLocation, tv) ; à revoir si le club le change
CONF = re.compile(r'"dateTime":"([^"]+)","dateTxt":[^,]*,"eventLocation":(?:"[^"]*"|null),"tv":\{"html":"((?:[^"\\]|\\.)*)"\}')


def conferences(page, apres):
    """Heures (UTC) des entraînements annoncés avec une conférence de presse (« Rueda de prensa: sí ») à partir de `apres`.
    Le club ne donne pas l'heure de la conférence, seulement « après l'entraînement »."""
    return sorted({datetime.fromisoformat(d[:19]) for d, tv in CONF.findall(page)
                   if re.search(r"Rueda de prensa:(?:&nbsp;|\s)*s[íi]", tv) and datetime.fromisoformat(d[:19]) >= apres})


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
            " buteurs) et les déclarations d'après-match.\n"
            # Real-Celta, 21 nov. : le thread de la mi-temps reprenait « لم يصنع الفريق أي فرصة حقيقية » (Cadena SER), démenti par
            # les stats (occasion de Bernardo, penalty manqué) ; l'article portait en fait sur une critique du banc du Real
            "Pendant tout le match, du coup d'envoi au coup de sifflet final, le compte est celui d'un supporter du Real Madrid :\n"
            "- aucun jugement négatif sur le jeu du Real, de ses joueurs, de son entraîneur ou de son banc (pas de « أسوأ شوط »,"
            " « لم يصنع أي فرصة », « نائم », « مخيب »), même attribué à un média ;\n"
            "- résultat de la mi-temps : le score, les buteurs et la minute, rien d'autre ; si le Real est mené, une phrase sobre qui"
            " regarde vers la suite (« ما زال أمامنا شوط كامل ») ; s'il mène, la joie ;\n"
            "- résultat final : victoire du Real, la joie ; nul ou défaite, une phrase sobre et fidèle au club, sans reproche à chaud"
            " (l'analyse critique viendra après, dans le thread d'après-match) ;\n"
            "- écarte, jusqu'au coup de sifflet final, les articles dont le sujet est une critique du Real pendant ce match (jeu,"
            " joueurs, entraîneur, banc, attitude) : ils pourront être traités après le match, comme un débat.\n")


def evenement(debut, equipe=SOFA_EQUIPE):
    """Le match du Real qui commence à `debut` (UTC), tel que Sofascore le donne (la page du club restait sur « live » 0-0 et
    sans mi-temps pendant Real-Celta, le 21 nov.) ; None si absent. En direct, le match est dans events/next ; fini, dans
    events/last. Écart de 3 h toléré si le coup d'envoi a bougé."""
    from match import sofascore  # Edge, sinon Bright Data (serveurs de GitHub)
    ts = datetime.fromisoformat(debut).replace(tzinfo=timezone.utc).timestamp()
    for sens in ("next", "last"):
        for e in sofascore(f"team/{equipe}/events/{sens}/0").get("events", []):
            if abs(e["startTimestamp"] - ts) < 3 * 3600:
                return e
    return None


def arabe(objet):
    """Traduction arabe donnée par Sofascore (équipe ou joueur), sinon None."""
    return (objet.get("fieldTranslations") or {}).get("nameTranslation", {}).get("ar")


@lru_cache
def nom_arabe_claude(nom):
    try:
        # « پي إس في » le 23 nov. : lettres persanes refusées, nom tel que l'écrivent les médias sportifs arabes (آيندهوفن)
        ar = appeler_claude(f"Écris le nom du club de football « {nom} » tel que l'écrivent les médias sportifs arabes (beIN, Kooora), "
                            "en lettres arabes seulement (jamais پ ni گ ni ڤ), et rien d'autre.", "sonnet", "low").strip()
        ar = ar.translate(str.maketrans("پڤگ", "بفغ"))  # haiku ne respectait pas la consigne (« ڤيغو سيلتا »)
    except (ErreurClaude, SystemExit):  # SystemExit : Claude pas installé (suivi dédié), appeler_claude arrêterait tout
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


# uniqueTournament Sofascore -> hashtag ; une compétition absente n'a que le tag du match
COMPETITIONS = {8: "#الليغا", 7: "#دوري_أبطال_أوروبا", 329: "#كأس_الملك", 213: "#السوبر_الإسباني",
                357: "#كأس_العالم_للأندية", 465: "#السوبر_الأوروبي"}
BARCA = 2817


def hashtags_match(e, dom, ext):
    """Tag du match (équipe qui reçoit d'abord) + compétition, ou #الكلاسيكو contre le Barça (choix de l'utilisateur, 2026-11-22)."""
    match = "#" + re.sub(r"\W+", "_", f"{dom} {ext}").strip("_")
    if BARCA in (e["homeTeam"].get("id"), e["awayTeam"].get("id")):
        return f"{match} #الكلاسيكو"
    comp = COMPETITIONS.get(((e.get("tournament") or {}).get("uniqueTournament") or {}).get("id"))
    return f"{match} {comp}" if comp else match


def tweets_du_match(e, incidents, equipe=SOFA_EQUIPE):
    """[(clé, texte)] des tweets que l'état du match appelle, dans l'ordre : début, buts et cartons rouges (chronologiques),
    mi-temps, reprise, fin. L'appelant écarte les clés déjà parties."""
    dom, ext = nom_arabe(e["homeTeam"]), nom_arabe(e["awayTeam"])
    real_dom = e["homeTeam"].get("id") == equipe
    adversaire = ext if real_dom else dom
    statut, tag = e["status"], "\n\n" + hashtags_match(e, dom, ext)
    score = f"{dom} {e.get('homeScore', {}).get('current', 0)} - {e.get('awayScore', {}).get('current', 0)} {ext}"
    tweets, buts, avant = [], [], (0, 0)
    # voix de supporter du Real pendant tout le match (choix de l'utilisateur, 2026-11-22) : joie pour le Real, soutien quand il souffre
    sd, se = e.get("homeScore", {}).get("current", 0) or 0, e.get("awayScore", {}).get("current", 0) or 0
    real, adv = (sd, se) if real_dom else (se, sd)
    if statut.get("type") == "inprogress":  # pas de « coup d'envoi » rattrapé une fois le match fini
        tweets.append(("début", f"▶️ انطلاق المباراة\n\n{dom} - {ext}\n\nهلا مدريد! 🤍{tag}"))
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
            texte = (f"⚽🔥 هدددف لريال مدريد!\n\n{ligne}\n\n{courant}" if pour_real
                     else f"⚽ هدف لـ{adversaire}\n\n{ligne}\n\n{courant}\n\nفاموس ريال! 💪")
            tweets.append((f"but:{cle}", texte + tag))
        elif i.get("incidentType") == "card" and i.get("incidentClass") in ("red", "yellowRed"):
            equipe = dom if i.get("isHome") else ext
            second = " (إنذار ثانٍ)" if i["incidentClass"] == "yellowRed" else ""
            suite = "ريال مدريد بعشرة لاعبين، وكلنا مع الفريق 🤍" if bool(i.get("isHome")) == real_dom else "ريال مدريد في تفوق عددي 💪"
            tweets.append((f"rouge:{cle}", f"🟥 بطاقة حمراء\n\n{joueur(i)} ({equipe}) {minute(i)}{second}\n\n{suite}{tag}"))
    if statut.get("code") == MI_TEMPS:
        suite = "ريال مدريد في المقدمة 🤍" if real > adv else "ما زال أمامنا شوط كامل 💪" if real < adv else "الكلمة للشوط الثاني 💪"
        tweets.append(("mi-temps", f"⏸️ نهاية الشوط الأول\n\n{score}\n\n{suite}{tag}"))
    # reprise : seulement avant le 1er but ou carton du 2e acte (rattrapée plus tard, elle partirait après ses buts) ;
    # les changements faits à la pause sont datés de la 46e (Real-Celta) : ils ne comptent pas
    if statut.get("code") == 7 and not any(i.get("incidentType") in ("goal", "card") and (i.get("time") or 0) > 45 for i in incidents):
        tweets.append(("reprise", f"▶️ انطلاق الشوط الثاني\n\n{score}\n\nفاموس ريال! 💪{tag}"))
    if statut.get("type") == "finished":
        suite = "فوز ريال مدريد! هلا مدريد 🤍" if real > adv else "تعادل، والموسم طويل 💪" if real == adv else "خسارة مؤلمة، وسنعود أقوى 🤍"
        tweets.append(("fin", f"🏁 نهاية المباراة\n\n{score}\n\n{suite}" + ("\n\n" + "\n".join(buts) if buts else "") + tag))
    return tweets


def suivre_match(con, utc=None):
    """Pendant un match (fenêtre de match_courant), à chaque passage : l'état lu sur Sofascore est noté dans suivi_match quand
    il change, et les tweets du direct partent tout de suite sur X, chacun une seule fois (table tweets_match) : coup
    d'envoi, chaque but (célébré si c'est le Real), chaque carton rouge, mi-temps, reprise, fin avec les buteurs."""
    import subprocess
    import threads
    from match import sofascore
    utc = utc or maintenant()
    m = match_courant(utc)
    if not m:
        return 0
    if direct_actif():  # le suivi dédié lit Sofascore chaque minute et tweete : pas de requête Bright Data en double ici
        print("  Suivi du match : suivi dédié en cours (suivi_direct.yml)")
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
    deja ={r[0] for r in con.execute("SELECT cle FROM tweets_match WHERE debut = ?", (m["debut"],))}
    deja |= set(lire_direct().get(m["debut"], {}).get("cles", []))  # déjà partis par le suivi dédié
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


# ---------- suivi dédié (workflow suivi_direct.yml) : une lecture par minute pendant tout le match ----------
def lire_direct():
    try:
        return json.loads(DIRECT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def direct_actif(workflow="suivi_direct.yml"):
    """Le workflow du suivi dédié tourne-t-il (ou attend-il) ? False si gh est absent ou refuse : le passage principal tweete.
    Un run « à blanc » (dans son nom) ne compte pas : il ne publie rien."""
    try:
        r = subprocess.run(["gh", "run", "list", "--workflow", workflow, "--limit", "5", "--json", "status,displayTitle"],
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0 and any(x["status"] in ("in_progress", "queued", "waiting", "pending")
                                         and "à blanc" not in x.get("displayTitle", "") for x in json.loads(r.stdout))
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def direct_a_lancer(utc=None):
    """Coup d'envoi (UTC) du match à suivre en direct maintenant, ou "" : de 15 min avant le coup d'envoi à la fin de la fenêtre,
    si le suivi de ce match n'est pas fini et que le workflow ne tourne pas déjà."""
    utc = utc or maintenant()
    m = match_courant(utc + timedelta(minutes=15))
    if not m or lire_direct().get(m["debut"], {}).get("fini") or direct_actif():
        return ""
    return m["debut"]


def sauver_direct(message):
    """Pousse direct.json dans le dépôt (sur GitHub) : le passage principal y voit les tweets déjà partis."""
    try:
        for cmd in (["git", "add", "direct.json"], ["git", "commit", "-q", "-m", message],
                    ["git", "pull", "-q", "--rebase", "--autostash"], ["git", "push", "-q"]):
            subprocess.run(cmd, capture_output=True, timeout=60, check=True)
    except (OSError, subprocess.SubprocessError) as err:  # le tweet est parti ; seul le partage avec le passage principal tarde
        print(f"  ! direct.json non poussé ({err})")


def avec_incidents(e, incidents):
    """L'événement mis à jour d'après les incidents (seuls lus chaque minute par le suivi dédié) : score du dernier but ou de
    la dernière fin de période, et mi-temps dès l'incident « HT » tant que le statut lu date de la 1re mi-temps."""
    e = dict(e)
    marques = [i for i in incidents if i.get("incidentType") in ("goal", "period") and i.get("homeScore") is not None]
    if marques:
        d = max(marques, key=lambda i: (i.get("time") or 0, i.get("addedTime") or 0))
        e["homeScore"], e["awayScore"] = {**e.get("homeScore", {}), "current": d["homeScore"]}, {**e.get("awayScore", {}), "current": d["awayScore"]}
    if e["status"].get("code") == 6 and any(i.get("incidentType") == "period" and i.get("text") == "HT" for i in incidents):
        e["status"] = {"code": MI_TEMPS, "type": "inprogress", "description": "Halftime"}
    return e


def fin_de_periode(incidents):
    """Une fin de période autre que la mi-temps (« FT », prolongation…) : le statut dira si le match est vraiment fini."""
    return any(i.get("incidentType") == "period" and i.get("text") != "HT" for i in incidents)


def suivre_en_direct(debut, equipe=SOFA_EQUIPE, publier=True, intervalle=INTERVALLE, dormir=time.sleep, horloge=None):
    """Lit Sofascore toutes les `intervalle` secondes, du coup d'envoi à la fin, et tweete chaque fait une seule fois, dans
    l'ordre : coup d'envoi, buts, cartons rouges, mi-temps, reprise, fin. Seuls les incidents sont lus chaque minute ; le statut
    ne l'est qu'avant le coup d'envoi, après la pause jusqu'à la reprise, et après une fin de période jusqu'à « terminé ».
    publier=False : affiche sans tweeter."""
    import threads
    from match import sofascore
    horloge = horloge or maintenant
    t0 = datetime.fromisoformat(debut)
    attente = (t0 - timedelta(minutes=2) - horloge()).total_seconds()
    if attente > 0:
        print(f"Attente du coup d'envoi : {attente / 60:.0f} min")
        dormir(attente)
    etat = lire_direct()
    suivi = etat.setdefault(debut, {"cles": [], "fini": False})
    e = id_match = None
    avant, incidents, pause_faite, lire_statut = None, [], False, True
    while horloge() < t0 + timedelta(hours=2, minutes=45) and not suivi["fini"]:
        h = horloge().strftime("%H:%M:%S")
        try:
            if id_match is None:
                e = evenement(debut, equipe)
                id_match = e["id"] if e else None
            elif lire_statut:
                e = sofascore(f"event/{id_match}")["event"]
            if not e:
                print(f"{h} ! match introuvable sur Sofascore")
            else:
                if e["status"].get("type") != "notstarted":
                    incidents = sofascore(f"event/{id_match}/incidents").get("incidents", [])
                    if fin_de_periode(incidents) and not lire_statut and e["status"].get("type") != "finished":
                        e = sofascore(f"event/{id_match}")["event"]  # fin vérifiée tout de suite, pas à la minute suivante
                    e = avec_incidents(e, incidents)
                # shortcut: après « FT », statut relu chaque minute jusqu'à « terminé » (2 requêtes/min en prolongation, rare)
                lire_statut = e["status"].get("type") == "notstarted" or e["status"].get("code") == MI_TEMPS or fin_de_periode(incidents)
                cle_etat = (e["status"].get("code"), e.get("homeScore", {}).get("current"), e.get("awayScore", {}).get("current"))
                if cle_etat != avant:
                    print(f"{h} {e['homeTeam']['name']} {cle_etat[1]}-{cle_etat[2]} {e['awayTeam']['name']}, "
                          f"« {e['status'].get('description')} » (code {cle_etat[0]})")
                avant = cle_etat
                for cle, texte in tweets_du_match(e, incidents, equipe):
                    if cle in suivi["cles"]:
                        continue
                    if publier:
                        threads.typefully_api("drafts", {"draft_title": f"{cle} {e['homeTeam']['name']}-{e['awayTeam']['name']}",
                                                         "publish_at": "now", "platforms": {"x": {"enabled": True, "posts": [{"text": texte}]}}})
                    print(f"{h} >> tweet « {cle} »{'' if publier else ' (à blanc, non publié)'} :\n   " + texte.replace("\n", "\n   "))
                    suivi["cles"].append(cle)
                    suivi["fini"] = cle == "fin"
                    if publier:
                        DIRECT.write_text(json.dumps(etat, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                        sauver_direct(f"Direct : {cle}")
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as err:  # lecture ou envoi raté : minute suivante
            print(f"{h} ! {err!r} : réessayé dans {intervalle} s")
        # pause une seule fois, et seulement une fois le tweet de mi-temps parti (un suivi relancé en 2e mi-temps a déjà la clé)
        mi_temps = not pause_faite and bool(e) and e["status"].get("code") == MI_TEMPS and "mi-temps" in suivi["cles"]
        pause_faite = pause_faite or mi_temps
        if not suivi["fini"]:
            dormir(PAUSE_MI_TEMPS if mi_temps else intervalle)
    print("Fin du suivi :", suivi["cles"])
    return suivi["cles"]


if __name__ == "__main__" and sys.argv[1:2] == ["--direct-a-lancer"]:
    sys.stdout.reconfigure(encoding="utf-8")
    print(direct_a_lancer())
elif __name__ == "__main__" and sys.argv[1:2] == ["--direct"]:  # --direct <coup d'envoi UTC> [--equipe <id>] [--a-blanc]
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[2:]
    suivre_en_direct(args[0], int(args[args.index("--equipe") + 1]) if "--equipe" in args else SOFA_EQUIPE,
                     publier="--a-blanc" not in args)
elif __name__ == "__main__":
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

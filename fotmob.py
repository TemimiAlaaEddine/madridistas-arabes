"""FotMob : stats Opta d'un match du Real Madrid (par mi-temps, xG en jeu et sur CPA, momentum, couloirs d'attaque, tirs par situation, finition par tireur, stats de chaque joueur, faits Opta).

Usage : python fotmob.py AAAA-MM-JJ   (le match du Real ce jour-là, heure de Madrid ; lancé aussi par match.py)
Pages lues directement, sans Bright Data : le robots.txt de FotMob autorise les pages et interdit /api/ (donc pas de cartes de chaleur).
Les données sont dans le JSON __NEXT_DATA__ de la page.
"""
import collections
import json
import re
import subprocess
import sys
from datetime import datetime

from threads import heure_madrid

EQUIPE = 8633  # Real Madrid sur FotMob
SITE = "https://www.fotmob.com"
NAVIGATEUR = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
STATS = {  # lignes gardées, dans l'ordre d'affichage
    "Ball possession": "possession (%)", "Expected goals (xG)": "xG", "xG open play": "xG dans le jeu", "xG set play": "xG sur CPA",
    "xG on target (xGOT)": "xG des tirs cadrés", "Total shots": "tirs", "Big chances": "grosses occasions",
    "Touches in opposition box": "touches dans la surface adverse", "Accurate passes": "passes réussies", "Opposition half": "passes réussies dans la moitié adverse",
    "Accurate long balls": "longs ballons réussis", "Accurate crosses": "centres réussis", "Duels won": "duels gagnés", "Ground duels won": "duels au sol gagnés", "Aerial duels won": "duels aériens gagnés",
    "Tackles": "tacles", "Interceptions": "interceptions", "Fouls committed": "fautes",
}


def page(chemin):
    r = subprocess.run(["curl", "-s", "-f", "-m", "60", "-A", NAVIGATEUR, SITE + chemin], capture_output=True, check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.stdout.decode("utf-8", "replace"), re.S)
    if not m:
        raise ValueError(f"FotMob : pas de données dans {chemin}")
    return json.loads(m.group(1))["props"]["pageProps"]


def trouver(date):
    """Adresse de la page du match du Real à cette date (heure de Madrid), ou None."""
    calendrier = page(f"/teams/{EQUIPE}/fixtures/real-madrid")["fallback"][f"team-{EQUIPE}"]["fixtures"]["allFixtures"]["fixtures"]
    for m in calendrier:
        debut = heure_madrid(datetime.fromisoformat(m["status"]["utcTime"].replace("Z", "")))
        if debut.date().isoformat() == str(date) and m["status"].get("finished"):
            return m["pageUrl"]
    return None


def lire(adresse):
    p = page(adresse)
    c = {k: p["content"].get(k) for k in ("stats", "momentum", "attackingZones", "shotmap", "playerStats")}
    c["insights"] = (p["content"].get("matchFacts") or {}).get("insights")
    return {"general": p["general"], "content": c}


JOUEUR = {  # stats Opta par joueur (FotMob), affichées quand elles ne sont pas nulles
    "FotMob rating": "note", "Chances created": "occasions créées", "Passes into final third": "passes vers le dernier tiers",
    "Touches in opposition box": "touches dans la surface", "Successful dribbles": "dribbles réussis", "Recoveries": "récupérations",
    "Defensive actions": "actions défensives", "Dribbled past": "dribblé", "Duels won": "duels gagnés", "Duels lost": "duels perdus", "Ground duels won": "au sol", "Aerial duels won": "aériens",
    "Was fouled": "fautes subies", "Dispossessed": "ballons perdus sous pression",
    "Saves": "arrêts", "Goals conceded": "buts encaissés", "xGOT faced": "xGOT subi", "Goals prevented": "buts évités",
}


def stats_joueur(j):
    return {k: v["stat"] for grp in j.get("stats") or [] for k, v in (grp.get("stats") or {}).items() if v.get("stat")}


def resumer(d):
    c, g = d["content"], d["general"]
    dom, ext = g["homeTeam"], g["awayTeam"]
    lignes = [f"Stats Opta ({dom['name']} | {ext['name']}) : match / 1re mi-temps / 2e mi-temps"]
    per = {nom: {x["title"]: x["stats"] for grp in p["stats"] for x in grp["stats"] if x.get("stats") and x["stats"][0] is not None}
           for nom, p in c["stats"]["Periods"].items()}
    for cle, nom in STATS.items():
        if cle in per.get("All", {}):
            lignes.append(f"  {nom:<40} " + "  /  ".join(f"{v[0]} | {v[1]}" for v in (per.get(k, {}).get(cle) for k in ("All", "FirstHalf", "SecondHalf")) if v))
    z = c.get("attackingZones") or {}
    for cote, e in (("home", dom), ("away", ext)):
        if cote in z:
            lignes.append(f"  couloirs d'attaque {e['name']} (gauche / axe / droite, en %) : " + " ; ".join(
                f"{n} {z[cote][k]['left']} / {z[cote][k]['center']} / {z[cote][k]['right']}" for k, n in (("firstHalf", "1re"), ("secondHalf", "2e")) if k in z[cote]))
    tirs = (c.get("shotmap") or {}).get("shots") or []
    for e in (dom, ext):
        sit = collections.defaultdict(lambda: [0, 0.0])
        for t in tirs:
            if t["teamId"] == e["id"]:
                sit[t["situation"]][0] += 1
                sit[t["situation"]][1] += t.get("expectedGoals") or 0
        lignes.append(f"  tirs de {e['name']} par situation (Opta) : " + ", ".join(f"{k} {n} (xG {x:.2f})" for k, (n, x) in sorted(sit.items(), key=lambda i: -i[1][1])))
    mom = ((c.get("momentum") or {}).get("main") or {}).get("data") or []
    if mom:
        bornes = [(0, 15, "0-15"), (15, 30, "15-30"), (30, 46, "30-45+"), (46, 60, "45-60"), (60, 75, "60-75"), (75, 200, "75-90+")]
        moy = [(n, [m["value"] for m in mom if a <= m["minute"] < b]) for a, b, n in bornes]
        lignes.append(f"  momentum Opta par quart d'heure (moyenne de -100 à 100 ; positif = {dom['name']}, négatif = {ext['name']}) : "
                      + "  ".join(f"{n}: {sum(v) / len(v):+.0f}" for n, v in moy if v))
        # renversements : le signe du momentum moyen change d'une tranche de 5 minutes à la suivante, avec un écart net
        tranches = [(a, [m["value"] for m in mom if a <= m["minute"] < a + 5]) for a in range(0, 95, 5)]
        tranches = [(a, sum(v) / len(v)) for a, v in tranches if v]
        bascules = [f"{a}'-{a + 5}' ({p:+.0f} -> {q:+.0f})" for (_, p), (a, q) in zip(tranches, tranches[1:]) if p * q < 0 and abs(q - p) >= 40]
        if bascules:
            lignes.append("  renversements du momentum (tranches de 5 min) : " + ", ".join(bascules))
    noms = {dom["id"]: dom["name"], ext["id"]: ext["name"]}
    tireurs = collections.defaultdict(lambda: [0, 0, 0.0, 0.0])  # tirs, buts, xG, xGOT
    for t in tirs:
        if not t.get("isOwnGoal"):
            s = tireurs[(t["teamId"], t.get("playerName", "?"))]
            s[0] += 1
            s[1] += t.get("eventType") == "Goal"
            s[2] += t.get("expectedGoals") or 0
            s[3] += t.get("expectedGoalsOnTarget") or 0
    fins = [f"{n} ({noms.get(e, '?')}) {nb} tirs, {b} buts, xG {x:.2f}, xGOT {xo:.2f}"
            for (e, n), (nb, b, x, xo) in sorted(tireurs.items(), key=lambda i: -i[1][2]) if b or x >= 0.2]
    if fins:
        lignes.append("  finition par tireur (xGOT > xG : tirs bien placés ; buts < xGOT : le gardien a fait la différence) : " + " ; ".join(fins))
    js = [(j, stats_joueur(j)) for j in (c.get("playerStats") or {}).values()]
    for e in (dom, ext):
        equipe = sorted(((j, st) for j, st in js if j["teamId"] == e["id"] and (st.get("Minutes played") or {}).get("value")),
                        key=lambda i: -i[1]["Minutes played"]["value"])
        if equipe:
            lignes.append(f"  joueurs de {e['name']} (Opta, stats non nulles) :")
        for j, st in equipe:
            det = [f"{nom} {st[k]['value']}" + (f"/{st[k]['total']}" if "total" in st[k] else "") for k, nom in JOUEUR.items() if (st.get(k) or {}).get("value")]
            lignes.append(f"    {j['name']} {st['Minutes played']['value']}' : " + ", ".join(det))
    for i in c.get("insights") or []:
        qui = noms.get(i.get("teamId"), "") + " : " if i.get("type") == "team" else ""
        lignes.append(f"  fait Opta : {qui}{i.get('text')}")
    return lignes


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    adresse = trouver(sys.argv[1])
    if not adresse:
        sys.exit(f"FotMob : pas de match terminé du Real le {sys.argv[1]}")
    print(SITE + adresse)
    print("\n".join(resumer(lire(adresse))))

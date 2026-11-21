"""Récupère les stats du dernier match du Real Madrid sur WhoScored et Sofascore, puis les affiche.

Usage : python match.py            (dernier match terminé)
        python match.py <id>       (identifiant WhoScored d'un match précis, lu dans son adresse /Matches/<id>/)
        python match.py --date AAAA-MM-JJ   (le match de ce jour, heure de Madrid ; erreur s'il n'est pas encore terminé sur WhoScored)
Les pages sont gardées dans matchs/AAAA-MM-JJ-adversaire/ (hors git). Sert à la commande /match (.claude/skills/match).
WhoScored passe par Bright Data (clé "brightdata_api_token" dans secrets.json) : Cloudflare bloque les accès directs.
Sofascore passe par Edge sans fenêtre : son API refuse les requêtes qui ne viennent pas d'un navigateur.
"""
import html
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import whoscored
from couvertures import EDGE
from threads import reglage

DOSSIER = Path(__file__).parent / "matchs"
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # lancé par la tâche planifiée : pas de console qui s'ouvre
WS_EQUIPE, SOFA_EQUIPE = 52, 2829  # Real Madrid sur WhoScored et Sofascore
LIGNE = re.compile(r"\[(\d{6,8}),\d+,'(\d\d-\d\d-\d\d)','[^']*',\d+,'([^']*)',\d+,\d+,'([^']*)',\d+,'([^']*)'")


def bright_data(url):
    # curl plutôt qu'urllib : sur ce PC, Python refuse le certificat d'api.brightdata.com
    corps = json.dumps({"zone": "mcp_unlocker", "url": url, "format": "raw"})
    r = subprocess.run(["curl", "-s", "-f", "-m", "180", "https://api.brightdata.com/request",
                        "-H", f"Authorization: Bearer {reglage('brightdata_api_token')}",
                        "-H", "Content-Type: application/json", "-d", corps], capture_output=True, check=True, creationflags=SANS_FENETRE)
    if not r.stdout.strip():  # page refusée par le site : Bright Data répond 200 avec un corps vide
        raise ValueError(f"Bright Data : réponse vide pour {url}")
    return r.stdout.decode("utf-8", "replace")


def sofascore(chemin):
    url = f"https://www.sofascore.com/api/v1/{chemin}"
    try:
        r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--virtual-time-budget=10000", "--dump-dom", url],
                           capture_output=True, timeout=90, check=True, creationflags=SANS_FENETRE)
        return json.loads(html.unescape(re.search(r"<pre[^>]*>(.*)</pre>", r.stdout.decode("utf-8"), re.S).group(1)))
    except (subprocess.SubprocessError, OSError, TypeError, AttributeError, ValueError):
        pass  # navigateur absent ou refusé (serveurs de GitHub) : repli sur Bright Data, qui échoue parfois au 1er essai
    try:
        return json.loads(bright_data(url))
    except (subprocess.SubprocessError, ValueError):
        return json.loads(bright_data(url))


def matchs_joues(calendrier):
    """(id, date, domicile, extérieur, score) des matchs terminés de la page calendrier WhoScored."""
    return [m for m in LIGNE.findall(calendrier) if m[4] != "vs"]


def resume_sofascore(stats, compos):
    print("\n== Sofascore : stats d'équipe (domicile | extérieur)")
    for groupe in next(p for p in stats["statistics"] if p["period"] == "ALL")["groups"]:
        for i in groupe["statisticsItems"]:
            print(f"   {i['name']:<28} {i['home']} | {i['away']}")
    for cote in ("home", "away"):
        e = compos[cote]
        print(f"\n== Sofascore : {e.get('formation')} ({cote})")
        for p in e["players"]:
            s = p.get("statistics") or {}
            if s.get("minutesPlayed"):
                print(f"   {p['player']['name']:<24} {s['minutesPlayed']:>3}' note {s.get('rating') or '-'} | xG {s.get('expectedGoals', 0):.2f}"
                      f" | xA {s.get('expectedAssists', 0):.2f} | duels {s.get('duelWon', 0)}/{s.get('duelWon', 0) + s.get('duelLost', 0)}"
                      f" | ballons récupérés {s.get('ballRecovery', 0)} | pertes {s.get('possessionLostCtrl', 0)}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] != "--date":
        ws_id, date = sys.argv[1], None
    else:
        joues = matchs_joues(bright_data(f"https://www.whoscored.com/Teams/{WS_EQUIPE}/Fixtures"))
        if len(sys.argv) > 2:  # --date : ce match-là, jamais le précédent si WhoScored n'est pas encore à jour
            joues = [m for m in joues if datetime.strptime(m[1], "%d-%m-%y").date().isoformat() == sys.argv[2]]
            if not joues:
                sys.exit(f"Le match du {sys.argv[2]} n'est pas encore terminé sur WhoScored : réessaie plus tard.")
        ws_id, j, dom, ext, score = joues[-1]
        date = datetime.strptime(j, "%d-%m-%y").date()
        print(f"Match : {dom} {score} {ext} ({date})")
    page = bright_data(f"https://www.whoscored.com/Matches/{ws_id}/Live")
    d = whoscored.lire(page)
    date = date or datetime.fromisoformat(d["startTime"]).date()
    adversaire = d["away"]["name"] if d["home"]["teamId"] == WS_EQUIPE else d["home"]["name"]
    dossier = DOSSIER / f"{date}-{re.sub(r'[^a-z0-9]+', '-', adversaire.lower()).strip('-')}"
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "whoscored.html").write_text(page, encoding="utf-8")
    print(f"Pages gardées dans {dossier}\n\n######## WhoScored")
    whoscored.afficher(d)

    # même match côté Sofascore : celui du même jour parmi les derniers matchs du club
    try:  # sur GitHub Actions, Sofascore peut refuser les serveurs : l'analyse continue avec WhoScored seul
        evts = sofascore(f"team/{SOFA_EQUIPE}/events/last/0")["events"]
        evt = next((e for e in reversed(evts) if datetime.fromtimestamp(e["startTimestamp"]).date() == date), None)
        if not evt:
            print("\n! Sofascore : match introuvable à cette date")
            return
        stats, compos = sofascore(f"event/{evt['id']}/statistics"), sofascore(f"event/{evt['id']}/lineups")
    except (subprocess.SubprocessError, OSError, AttributeError, ValueError, KeyError) as err:
        print(f"\n! Sofascore indisponible ({err!r}) : continue avec WhoScored seul")
        return
    (dossier / "sofascore.json").write_text(json.dumps({"event": evt, "statistics": stats, "lineups": compos}), encoding="utf-8")
    print("\n######## Sofascore")
    resume_sofascore(stats, compos)


if __name__ == "__main__":
    main()

"""Lancement automatique de /match après chaque match du Real Madrid.

Usage : python apres_match.py --installer   (une fois : tâche planifiée Windows, toutes les 15 minutes, sans fenêtre)
        python apres_match.py               (ce que lance la tâche)
Les matchs viennent de matchs.json (calendrier.py, revue du lundi sur GitHub), lu dans la dernière version du dépôt
(git fetch, sans toucher aux fichiers du PC). 2 h 30 après le coup d'envoi, Claude Code lance /match en mode automatique
et le thread arrive en brouillon dans Typefully. Heure pas encore fixée : on attend 23 h 30 UTC le jour du match.
3 essais par match, un par passage (WhoScored met parfois du temps à publier les stats).
Suivi local (hors git) : matchs/suivi.json ; journal : matchs/journal.txt. Le PC doit être allumé, session Windows ouverte.
"""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from match import DOSSIER, SANS_FENETRE
from threads import heure_madrid

BASE = Path(__file__).parent
SUIVI = DOSSIER / "suivi.json"
ATTENTE = timedelta(hours=2, minutes=30)  # coup d'envoi + 2 h 30 : match fini, stats publiées
ESSAIS = 3
TACHE = "Madridistas apres-match"
OUTILS = ["Bash(python *)", "Read", "Grep", "Glob", "Edit(scripts/**)", "WebSearch", "WebFetch",
          "Agent", "Skill", "mcp__brightdata__scrape_as_markdown", "mcp__claude_ai_Typefully_-_Social_Media_Scheduler__create_draft"]
CONSIGNE = ("/match --date {date}\n\nMode automatique, lancé par une tâche planifiée : personne ne répond. Lance "
            "`python match.py --date {date}`. Thread X en arabe, format au choix. Ne pose aucune question, ne modifie pas "
            "connaissance.md et saute l'étape 6. Termine par le lien du brouillon Typefully.")


def journal(texte):
    DOSSIER.mkdir(exist_ok=True)
    with open(DOSSIER / "journal.txt", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M} {texte}\n")


def git(*args):
    return subprocess.run(["git", *args], cwd=BASE, capture_output=True, text=True, encoding="utf-8", timeout=60,
                          check=True, creationflags=SANS_FENETRE).stdout


def calendrier():
    try:  # la version du dépôt : matchs.json est réécrit chaque lundi par GitHub Actions
        git("fetch", "-q", "origin", "main")
        return json.loads(git("show", "origin/main:matchs.json"))
    except Exception as err:
        journal(f"! git : {err} ; matchs.json du PC utilisé")
        return json.loads((BASE / "matchs.json").read_text(encoding="utf-8"))


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
    """Matchs finis depuis moins de 2 jours, pas encore analysés, moins de 3 essais."""
    return [m for m in matchs if utc - timedelta(days=2) < moment(m) <= utc
            and not suivi.get(cle(m), {}).get("fait") and suivi.get(cle(m), {}).get("essais", 0) < ESSAIS]


def analyser(m):
    exe = shutil.which("claude")
    if not exe:
        return "Claude Code introuvable"
    cmd = [exe, "-p", CONSIGNE.format(date=date_madrid(m)), "--allowedTools", *OUTILS]
    try:
        r = subprocess.run(cmd, cwd=BASE, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", timeout=1800, creationflags=SANS_FENETRE)
    except subprocess.TimeoutExpired:
        return "pas de réponse en 30 minutes"
    if r.returncode == 0 and "typefully.com" in r.stdout:
        return None
    return (r.stderr or r.stdout).strip()[-300:] or f"code {r.returncode}"


def passage(utc=None):
    utc = utc or datetime.now(timezone.utc).replace(tzinfo=None)
    suivi = json.loads(SUIVI.read_text(encoding="utf-8")) if SUIVI.exists() else {}
    for m in a_analyser(calendrier(), suivi, utc)[:1]:  # un match par passage
        s = suivi.setdefault(cle(m), {"fait": False, "essais": 0})
        s["essais"] += 1
        DOSSIER.mkdir(exist_ok=True)
        SUIVI.write_text(json.dumps(suivi, ensure_ascii=False, indent=2), encoding="utf-8")  # essai compté même si on plante
        erreur = analyser(m)
        s["fait"] = erreur is None
        SUIVI.write_text(json.dumps(suivi, ensure_ascii=False, indent=2), encoding="utf-8")
        journal(f"{m['match']} ({date_madrid(m)}, essai {s['essais']}) : {'brouillon déposé' if s['fait'] else '! ' + erreur}")


def installer():
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    commande = f'"{pythonw if pythonw.exists() else sys.executable}" "{Path(__file__).resolve()}"'
    subprocess.run(["schtasks", "/create", "/tn", TACHE, "/sc", "minute", "/mo", "15", "/tr", commande, "/f"], check=True)
    print(f"Tâche « {TACHE} » installée (toutes les 15 minutes). Pour l'arrêter : schtasks /delete /tn \"{TACHE}\" /f")


if __name__ == "__main__":
    if sys.argv[1:] == ["--installer"]:
        installer()
    else:
        try:
            passage()
        except Exception as err:  # lancé sans fenêtre : l'erreur ne se voit que dans le journal
            journal(f"! passage : {err!r}")
            raise

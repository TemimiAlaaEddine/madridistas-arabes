"""Extrait d'une page de match WhoScored enregistrée (Ctrl+S) les systèmes, les notes et les stats des joueurs.

Usage : python whoscored.py "Valencia 0-3 Real Madrid - LaLiga 2026_2027 Live.html"
WhoScored bloque les robots et charge ses données en JavaScript : on lit l'objet matchCentreData de la page enregistrée.
Sert à la commande /script (.claude/skills/script).
"""
import json
import sys


def lire(html):
    i = html.index("{", html.index("matchCentreData"))
    return json.JSONDecoder().raw_decode(html[i:])[0]


def finale(v):
    """Les notes sont données minute par minute : la note finale est celle de la dernière minute."""
    return v[max(v, key=float)] if v else None


def total(v):
    """Les stats des joueurs sont découpées par minute : on les additionne."""
    return int(sum((v or {}).values()))


def joueurs(equipe):
    for p in equipe["players"]:
        st = p.get("stats") or {}
        if not st:  # remplaçant non entré
            continue
        yield {
            "nom": p["name"], "poste": p.get("position"), "titulaire": bool(p.get("isFirstEleven")),
            "note": finale(st.get("ratings")), "tirs": total(st.get("shotsTotal")),
            "cadres": total(st.get("shotsOnTarget")), "passes_cles": total(st.get("passesKey")),
            "dribbles": total(st.get("dribblesWon")), "tacles": total(st.get("tackleSuccessful")),
            "interceptions": total(st.get("interceptions")),
            "passes": f"{total(st.get('passesAccurate'))}/{total(st.get('passesTotal'))}",
        }


def afficher(d):
    # shortcut: pas de possession ni de % de passes d'équipe (découpés par minute), à recalculer si besoin
    print(f"Score {d.get('score')} (mi-temps {d.get('htScore')})")
    for cote in ("home", "away"):
        e = d[cote]
        js = list(joueurs(e))
        systemes = " -> ".join(f"{f['formationName']} (dès {f.get('startMinuteExpanded')}e)" for f in e["formations"])
        print(f"\n== {e['name']} : {systemes}")
        print(f"   tirs {sum(j['tirs'] for j in js)}, cadrés {sum(j['cadres'] for j in js)}, "
              f"passes clés {sum(j['passes_cles'] for j in js)}")
        for j in js:
            print(f"   {'XI ' if j['titulaire'] else 'REMP'} {j['nom']:<24} {j['poste']:<4} note {j['note']} | tirs {j['tirs']} "
                  f"(cadrés {j['cadres']}) | passes clés {j['passes_cles']} | dribbles {j['dribbles']} | "
                  f"tacles {j['tacles']} | interceptions {j['interceptions']} | passes {j['passes']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # noms accentués lisibles dans la console Windows
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    afficher(lire(open(sys.argv[1], encoding="utf-8").read()))

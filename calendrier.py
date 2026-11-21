"""Revue du lundi : les 5 prochains matchs du Real Madrid, lus sur la page calendrier du site officiel (une seule requête,
sans Claude) et gardés dans matchs.json. Le tri s'en sert pour la règle « pendant un match » (match_en_cours)."""
import json
import re
from datetime import datetime, timedelta

from commun import BASE, lire_page, maintenant

URL = "https://www.realmadrid.com/es-ES/futbol/calendario"
FICHIER = BASE / "matchs.json"
DUREE = timedelta(hours=2, minutes=30)  # prolongation et arrêts de jeu compris
# chaque match est un objet JSON de la page : "Real Madrid vs Celta de Vigo", coup d'envoi en UTC, heure fixée ou non (date seule)
MATCH = re.compile(r'"description":\{"plaintext":"([^"]+)"\},"week":[^,]*,"weekAsText":[^,]*,"dateTime":"([^"]+)",'
                   r'"dateTxt":[^,]*,"isScheduled":(true|false),"status":"pre_match"')


def prochains(page, apres, n=5):
    vus = {(nom, date[:19], fixe == "true") for nom, date, fixe in MATCH.findall(page)}  # chaque match apparaît deux fois
    matchs = sorted((d, nom, fixe) for nom, d, fixe in vus if datetime.fromisoformat(d) > apres)
    return [{"match": nom, "debut": d, "heure_fixee": fixe} for d, nom, fixe in matchs[:n]]


def match_en_cours(utc=None):
    """Consigne ajoutée au tri pendant un match du Real Madrid (du coup d'envoi à 2 h 30 après), sinon ""."""
    from threads import heure_madrid
    utc = utc or maintenant()
    try:
        matchs = json.loads(FICHIER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    for m in matchs:
        debut = datetime.fromisoformat(m["debut"])
        if m["heure_fixee"] and debut <= utc < debut + DUREE:
            return (f"\nMATCH EN COURS : {m['match']} (coup d'envoi à {heure_madrid(debut):%H:%M}, heure de Madrid). Écarte les faits de jeu"
                    " (actions, occasions, cartons, buts racontés en direct) ; garde en revanche la composition officielle, les"
                    " déclarations d'avant-match, le résultat de la mi-temps (score et buteurs), le résultat final (score et buteurs)"
                    " et les déclarations d'après-match.\n")
    return ""


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

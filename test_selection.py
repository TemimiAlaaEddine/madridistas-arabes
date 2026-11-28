"""Tests de P2 : phases du calendrier, politique éditoriale (selection.py), relance JSON (commun.appeler_json)."""
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import calendrier as cal
import commun
import generer_site as g
import selection as s

sys.stdout.reconfigure(encoding="utf-8")

# phases : une seule à la fois, d'après matchs.json et direct.json
with tempfile.TemporaryDirectory() as tmp:
    vrai = (cal.FICHIER, cal.lire_direct)
    cal.FICHIER = Path(tmp) / "matchs.json"
    cal.FICHIER.write_text(json.dumps([{"match": "Real Madrid vs Alavés", "debut": "2026-11-28T20:00:00", "heure_fixee": True},
                                       {"match": "Real Sociedad vs Real Madrid", "debut": "2026-12-02T18:00:00", "heure_fixee": False}]),
                           encoding="utf-8")
    cal.lire_direct = lambda: {}
    try:
        assert cal.phase(datetime(2026, 11, 26, 12)) == cal.SEMAINE
        assert cal.phase(datetime(2026, 11, 27, 21)) == cal.PRE
        assert cal.phase(datetime(2026, 11, 28, 21)) == cal.LIVE
        assert cal.phase(datetime(2026, 11, 29, 1)) == cal.POST and cal.phase(datetime(2026, 11, 29, 22, 29)) == cal.POST
        assert cal.phase(datetime(2026, 11, 30, 12)) == cal.SEMAINE
        assert cal.phase(datetime(2026, 12, 2, 18, 30)) == cal.POST, "heure non fixée : jamais LIVE"
        # match du dimanche disparu du calendrier du lundi : encore connu par direct.json
        cal.FICHIER.write_text("[]", encoding="utf-8")
        cal.lire_direct = lambda: {"2026-11-28T20:00:00": {"fini": True}}
        assert cal.phase(datetime(2026, 11, 29, 9)) == cal.POST
    finally:
        cal.FICHIER, cal.lire_direct = vrai
print("OK phases")

# fiabilité calculée par le code, jamais par le modèle
assert s.fiabilite({"officiel": True, "source": "Real Madrid CF"}) == 1
assert s.fiabilite({"source": "Marca - Opinion"}) == 2 and s.fiabilite({"source": "Defensa Central"}) == 4
assert s.fiabilite({"source": "Foot Mercato"}) == 3
assert s.notes_valides({"importance": "2", "originalite": 9, "interet": -1, "urgence": 0}) == \
    {"importance": 2, "originalite": 3, "interet": 0, "urgence": 0}
assert s.notes_valides({"importance": 2}) is None
print("OK fiabilité et notes")

# décisions
n = lambda imp=1, ori=1, inte=1, urg=0: {"importance": imp, "originalite": ori, "interet": inte, "urgence": urg}
assert s.decider("info", None, 1, cal.SEMAINE)[0] == "PUBLISH", "site du club"
assert s.decider("conference", None, 2, cal.SEMAINE)[0] == "PUBLISH", "chaque déclaration part"
assert s.decider("info", None, 2, cal.SEMAINE)[0] == "REVIEW", "notes absentes : relecture"
assert s.decider("info", n(imp=1, urg=1), 2, cal.LIVE)[0] == "IGNORE" and s.decider("info", n(urg=3), 2, cal.LIVE)[0] == "PUBLISH"
assert s.decider("opinion", n(ori=2, inte=2), 2, cal.SEMAINE)[0] == "PUBLISH"
assert s.decider("opinion", n(ori=1, inte=3), 2, cal.SEMAINE)[0] == "IGNORE", "opinion qui n'apporte rien"
assert s.decider("opinion", n(ori=2, inte=1), 2, cal.POST)[0] == "PUBLISH", "après un match, les analyses sont attendues"
assert s.decider("opinion", n(ori=3, inte=3), 4, cal.SEMAINE)[0] == "IGNORE", "seconde main"
assert s.decider("info", n(imp=2), 3, cal.SEMAINE, confirme=False)[0] == "REVIEW", "rumeur importante, source peu sûre"
assert s.decider("info", n(imp=3, ori=0), 2, cal.SEMAINE)[0] == "IGNORE", "déjà publiée"
assert s.decider("info", n(imp=1), 2, cal.SEMAINE)[0] == "IGNORE" and s.decider("info", n(imp=1), 2, cal.PRE)[0] == "PUBLISH"
print("OK décisions")

# trace : une ligne par article trié, notes, fiabilité, décision et ce que le tri actuel a fait
con = sqlite3.connect(":memory:")
gardes = [{"lien": "a", "source": "Marca", "titre": "T", "type": "opinion", "_tri": {**n(ori=2, inte=2), "confirme": True}},
          {"lien": "b", "source": "AS", "titre": "U", "type": "info", "_tri": {"importance": "?"}}]
ecartes = [{"lien": "c", "source": "Foot Mercato", "titre": "V"}]
assert s.noter(con, gardes, ecartes, cal.SEMAINE) == {"a": "PUBLISH", "b": "REVIEW", "c": "IGNORE"}
lignes = con.execute("SELECT lien, fiabilite, originalite, decision, actuel, motif FROM decisions ORDER BY lien").fetchall()
assert lignes[0][:5] == ("a", 2, 2, "PUBLISH", "garde") and lignes[2][3:5] == ("IGNORE", "ecarte") and lignes[1][2] is None
print("OK trace des décisions")

# relance JSON : une seule, avec l'erreur ; échec après relance = ValueError (pas de boucle de passage en passage)
appels = []
reponses = iter(["désolé", '[{"id": 1}]'])
assert commun.appeler_json("P", appel=lambda p, *a: (appels.append(p), next(reponses))[1])[0] == [{"id": 1}]
assert len(appels) == 2 and "ILLISIBLE" in appels[1]
appels.clear()
try:
    commun.appeler_json("P", appel=lambda p, *a: (appels.append(p), '{"pas": "un tableau"}')[1])
    raise AssertionError("aurait dû échouer")
except ValueError:
    assert len(appels) == 2
# tri : notes rattachées aux articles gardés ; illisible après relance : None (le passage ne rédige rien)
g.appeler_claude = lambda p, *a: '[{"id": 1, "type": "info", "importance": 2, "originalite": 1, "interet": 2, "urgence": 0, "confirme": false}]'
gardes, ecartes = g.trier([{"titre": "Fichaje", "resume": "", "source": "AS", "lien": "x"}])
assert gardes[0]["_tri"]["importance"] == 2 and gardes[0]["_tri"]["confirme"] is False
g.appeler_claude = lambda p, *a: "désolé"
assert g.trier([{"titre": "Fichaje", "resume": "", "source": "AS", "lien": "x"}]) is None
g.appeler_claude = commun.appeler_claude
print("OK relance JSON")
r = s.rapport(con)
assert "observation" in r and "REVIEW  AS | U (notes du tri absentes ou invalides)" in r, r
print("OK rapport")

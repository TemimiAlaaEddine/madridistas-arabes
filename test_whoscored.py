"""Vérification rapide : python test_whoscored.py"""
import json

import whoscored as w

donnees = {"score": "0 : 3", "home": {"name": "Valencia", "formations": [{"formationName": "532"}], "players": []},
           "away": {"name": "Real Madrid", "formations": [{"formationName": "4231", "startMinuteExpanded": 0}], "players": [
               {"name": "Arda Güler", "position": "AMR", "isFirstEleven": True,
                "stats": {"ratings": {"0": 6.0, "36": 8.1, "95": 9.2}, "passesKey": {"10": 1.0, "40": 2.0},
                          "passesTotal": {"5": 44.0}, "passesAccurate": {"5": 38.0}}},
               {"name": "Lunin", "position": "Sub", "isFirstEleven": False, "stats": {}},
           ]}}
html = f"<script>require.config.params['args'] = {{ matchCentreData: {json.dumps(donnees)}, matchId: 1 }};</script>"

d = w.lire(html)
assert d["away"]["formations"][0]["formationName"] == "4231"
js = list(w.joueurs(d["away"]))
assert len(js) == 1, "le remplaçant non entré est ignoré"
assert js[0]["note"] == 9.2, "note de la dernière minute, pas la plus haute clé en texte"
assert js[0]["passes_cles"] == 3 and js[0]["passes"] == "38/44" and js[0]["tirs"] == 0
w.afficher(d)
print("OK")

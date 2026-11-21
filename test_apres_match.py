"""Vérification rapide, sans réseau : python test_apres_match.py"""
from datetime import datetime

import apres_match as a

celta = {"match": "Real Madrid vs Celta de Vigo", "debut": "2026-11-21T20:00:00", "heure_fixee": True}
psv = {"match": "Real Madrid vs PSV", "debut": "2026-11-24T20:00:00", "heure_fixee": True}
osasuna = {"match": "Real Madrid vs Osasuna", "debut": "2026-12-13T00:00:00", "heure_fixee": False}
matchs = [celta, psv, osasuna]

assert a.a_analyser(matchs, {}, datetime(2026, 11, 21, 22, 15)) == [], "trop tôt (2 h 15 après le coup d'envoi)"
assert a.a_analyser(matchs, {}, datetime(2026, 11, 21, 22, 30)) == [celta]
assert a.a_analyser(matchs, {a.cle(celta): {"fait": True, "essais": 1}}, datetime(2026, 11, 21, 23)) == [], "déjà fait"
assert a.a_analyser(matchs, {a.cle(celta): {"fait": False, "essais": 3}}, datetime(2026, 11, 21, 23)) == [], "3 essais au plus"
assert a.a_analyser(matchs, {}, datetime(2026, 11, 23, 22, 0)) == [celta], "rattrapé dans les 2 jours (PC éteint le soir du match)"
assert a.a_analyser(matchs, {}, datetime(2026, 11, 23, 22, 45)) == [], "plus de 2 jours : abandonné"
assert a.a_analyser(matchs, {}, datetime(2026, 12, 13, 23, 0)) == [], "heure pas fixée : pas avant 23 h 30 UTC"
assert a.a_analyser(matchs, {}, datetime(2026, 12, 13, 23, 30)) == [osasuna]
assert a.date_madrid(celta) == "2026-11-21" and a.date_madrid({**celta, "debut": "2026-11-21T23:30:00"}) == "2026-11-22", "date de Madrid"


fichier = "# ثريد\nسياق\n---\nتغريدة 1\n---\nتغريدة 2\n\n---\n\n## المصادر\n- x"
assert a.tweets_du_fichier(fichier) == ["تغريدة 1", "تغريدة 2"], "en-tête et sections « ## » écartés"
for mauvais in ("# ثريد\n---\nوحيدة\n## x", "# ثريد\n---\n" + "ا" * 300 + "\n---\nب"):
    try:
        a.tweets_du_fichier(mauvais)
        raise AssertionError("aurait dû refuser")
    except ValueError:
        pass
print("OK fichier")

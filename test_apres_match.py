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
_essai = {a.cle(celta): {"fait": False, "essais": 1, "dernier": "2026-11-21T22:30"}}
assert a.a_analyser(matchs, _essai, datetime(2026, 11, 21, 22, 55)) == [], "30 min au moins entre deux essais"
assert a.a_analyser(matchs, _essai, datetime(2026, 11, 21, 23, 0)) == [celta]
assert a.date_madrid(celta) == "2026-11-21" and a.date_madrid({**celta, "debut": "2026-11-21T23:30:00"}) == "2026-11-22", "date de Madrid"


fichier = "# ثريد\nسياق\n---\nتغريدة 1\n[graphique: matchs/x/graphiques/xg.png]\n---\nتغريدة 2\n\n---\n\n## المصادر\n- x"
assert a.tweets_du_fichier(fichier) == [("تغريدة 1", ["matchs/x/graphiques/xg.png"]), ("تغريدة 2", [])], \
    "en-tête et sections « ## » écartés, ligne de graphique retirée du texte"
long_avec_image = "# ثريد\n---\n" + "ا" * 270 + "\n[graphique: matchs/x/graphiques/tirs.png]\n---\nب"
assert a.tweets_du_fichier(long_avec_image)[0][1] == ["matchs/x/graphiques/tirs.png"], "la ligne de graphique ne compte pas dans la longueur"
for mauvais in ("# ثريد\n---\nوحيدة\n## x", "# ثريد\n---\n" + "ا" * 300 + "\n---\nب"):
    try:
        a.tweets_du_fichier(mauvais)
        raise AssertionError("aurait dû refuser")
    except ValueError:
        pass
print("OK fichier")


# tweets joueurs : un brouillon par tweet, sans numérotation ; absent ou illisible : jamais bloquant
import tempfile
from pathlib import Path
_envois, _vrai = [], a.typefully_api
a.typefully_api = lambda chemin, corps: _envois.append(corps) or {"id": len(_envois)}
with tempfile.TemporaryDirectory(dir=a.BASE / "scripts") as _d:
    _f = Path(_d) / "j.md"
    _f.write_text("# لاعبون\nسياق\n---\n⭐ أداء | غولر\n---\n⭐ أداء | فينيسيوس\n---\n⭐ أداء | كورتوا\n", encoding="utf-8")
    _rel = _f.relative_to(a.BASE).as_posix()
    assert a.deposer_joueurs(celta, f"...\nJOUEURS: {_rel}\nFICHIER: scripts/x.md") == " ; 3 tweets joueurs en brouillon"
assert [c["platforms"]["x"]["posts"][0]["text"] for c in _envois] == ["⭐ أداء | غولر", "⭐ أداء | فينيسيوس", "⭐ أداء | كورتوا"]
assert "fichier absent" in a.deposer_joueurs(celta, "FICHIER: scripts/x.md")
assert "non déposés" in a.deposer_joueurs(celta, "JOUEURS: scripts/absent.md")
a.typefully_api = _vrai
print("OK tweets joueurs")

assert a.tweets_du_fichier("# لاعبون\n---\n⭐ أداء | غولر\n[photo: matchs/x/photos/07.jpg]\n---\nب") == \
    [("⭐ أداء | غولر", ["matchs/x/photos/07.jpg"]), ("ب", [])], "ligne de photo lue comme une image et retirée du texte"
print("OK photo")

"""Vérification rapide, sans réseau : python test_match.py"""
import match as m

calendrier = ("fixtureMatches: [[1994027,1,'07-11-26','20:00',55,'Valencia',0,52,'Real Madrid',0,'0 : 3','0 : 2',1,1,'FT'],"
              "[1994044,1,'22-11-26','21:00',52,'Real Madrid',0,839,'Villarreal',0,'vs','',0,0,'']]")
assert m.matchs_joues(calendrier) == [("1994027", "07-11-26", "Valencia", "Real Madrid", "0 : 3")], "match à venir ignoré"

stats = {"statistics": [{"period": "1ST", "groups": []}, {"period": "ALL", "groups": [
    {"statisticsItems": [{"name": "Expected goals", "home": "0.18", "away": "2.34"}]}]}]}
joueur = {"player": {"name": "Arda Güler"}, "statistics": {"minutesPlayed": 90, "rating": 8.4, "expectedGoals": 0.31, "duelWon": 3, "duelLost": 2}}
banc = {"player": {"name": "Lunin"}, "statistics": {}}
entre_1_minute = {"player": {"name": "Espí"}, "statistics": {"minutesPlayed": 1}}
m.resume_sofascore(stats, {"home": {"formation": "5-3-2", "players": []}, "away": {"formation": "4-2-3-1", "players": [joueur, banc, entre_1_minute]}})
print("OK")

# Sofascore refuse le navigateur (serveurs de GitHub) en JSON : repli sur Bright Data ; son erreur JSON est une vraie erreur
import subprocess as _sp
_vrai = (m.subprocess.run, m.bright_data)
m.subprocess.run = lambda *a, **k: _sp.CompletedProcess(a, 0, b'<pre>{"error":{"code":403,"reason":"Forbidden"}}</pre>')
m.bright_data = lambda url: '{"events": [1]}'
assert m.sofascore("team/2829/events/last/0") == {"events": [1]}
m.bright_data = lambda url: '{"error": {"code": 404}}'
try:
    m.sofascore("x")
    raise AssertionError("ValueError attendue")
except ValueError:
    pass
m.subprocess.run, m.bright_data = _vrai
print("OK test_match")

# Bascules : un changement du Real à la 30e double ses passes vers le dernier tiers -> moment signalé
import bascules
def _ev(minute, equipe, typ="Pass", x=50, endx=60, ok=1, periode=1, **k):
    return dict({"minute": minute, "second": 0, "teamId": equipe, "x": x, "y": 50, "endX": endx, "endY": 50, "id": minute * 100 + x,
                 "period": {"value": periode}, "type": {"displayName": typ}, "outcomeType": {"value": ok}, "qualifiers": []}, **k)
evs = []
for mn in range(0, 90):
    p = 1 if mn < 45 else 2
    evs += [_ev(mn, 52, x=50, endx=55, periode=p), _ev(mn, 62, x=40, endx=45, periode=p)]
    if mn >= 30:
        evs += [_ev(mn, 52, x=60, endx=80, periode=p), _ev(mn, 52, x=60, endx=80, periode=p)]
evs.append(_ev(30, 52, "SubstitutionOn", playerId=7))
evs.sort(key=lambda e: (e["period"]["value"], e["minute"]))
lignes = bascules.analyser({"events": evs, "playerIdNameDictionary": {"7": "Vinícius"},
                            "home": {"teamId": 52, "name": "Real Madrid"}, "away": {"teamId": 62, "name": "Celta"}})
texte = "\n".join(lignes)
assert "31' Real Madrid : entrée de Vinícius" in texte and "Real Madrid entrées dans le dernier tiers 0 -> 30" in texte, texte
assert "xG" not in texte, "sans Sofascore, pas de ligne xG"
print("OK bascules")

# Phases : récupération au milieu puis dernier tiers en 2 passes = transition ; coup franc dans sa surface = sortie directe, pas CPA
_seq = [dict(_ev(10, 52, "BallRecovery", x=40), t=10.0), dict(_ev(10, 52, x=40, endx=60), t=10.1), dict(_ev(10, 52, x=60, endx=85), t=10.2),
        dict(_ev(10, 52, "SavedShot", x=90, isShot=True), t=10.3),
        dict(_ev(20, 62, x=5, endx=40, qualifiers=[{"type": {"displayName": "FreekickTaken"}}]), t=20.0), dict(_ev(20, 62, x=40, endx=75), t=20.2)]
s1, s2 = bascules.sequences(_seq, [])
assert s1["rapide"] and not s1["placee"] and len(s1["tirs"]) == 1, s1
assert s2["directe"] and not s2["cpa"], s2
assert "1. construction" in texte and "8. CPA défensifs" in texte
print("OK phases")

# Ballon revenu au gardien puis long ballon et tir en 9 s (Valence 75e) : sortie directe, même si la possession a commencé par un coup franc
_fk = [dict(_ev(74, 52, x=56, endx=45, qualifiers=[{"type": {"displayName": "FreekickTaken"}}]), t=74.0),
       dict(_ev(74, 52, x=45, endx=10), t=74.2), dict(_ev(74, 52, x=5, endx=76), t=74.5), dict(_ev(74, 52, x=77, endx=86), t=74.6),
       dict(_ev(74, 52, "Goal", x=98, isShot=True), t=74.65)]
(s3,) = bascules.sequences(_fk, [])
assert s3["tirs"][0]["phase"] == "directe" and s3["tirs"][0]["delai"] == 9, s3["tirs"]
print("OK sortie directe")

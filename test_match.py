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

# Lecture du match : le momentum FotMob s'inverse à la 30e, au moment où Vinícius entre et où le Real double ses passes vers le dernier tiers
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
_match = {"events": evs, "playerIdNameDictionary": {"7": "Vinícius"}, "score": "0 : 0", "htScore": "0 : 0",
          "home": {"teamId": 52, "name": "Real Madrid"}, "away": {"teamId": 62, "name": "Celta"}}
_mom = [{"minute": m, "value": -60 if m < 30 else 60} for m in list(range(0, 46)) + [45.5] + list(range(46, 91))]
_mom.sort(key=lambda m: m["minute"])
_fm_match = {"general": {"homeTeam": {"name": "Real Madrid", "id": 1}, "awayTeam": {"name": "Celta", "id": 2}},
             "content": {"stats": {"Periods": {}}, "shotmap": {"shots": []}, "momentum": {"main": {"data": _mom}}}}
texte = "\n".join(bascules.analyser(_match, None, _fm_match))
assert "30'-45+'" in texte and "momentum +60 (Real Madrid)" in texte, texte
assert "30' : momentum -60 -> +60" in texte and "31' Real Madrid : entrée de Vinícius (au même moment)" in texte, texte
assert "Real Madrid : entrées dans le dernier tiers 0 -> 30" in texte, texte
assert "mi-temps : pas de bascule" in texte, "momentum identique avant et après la pause"
sans = "\n".join(bascules.analyser(_match))
assert "découpage par mi-temps" in sans and "1re mi-temps" in sans and "sans xG" in sans and ", xG " not in sans.split("ÉTAPE 3")[1].split("ÉTAPE 5")[0], sans
print("OK lecture du match")

# xA : le tir est relié à la passe (RelatedEventId) ; 2e ballon : récupération 5 s après son corner puis tir ; hauteur du bloc
_q = lambda *n, **v: [{"type": {"displayName": x}} for x in n] + [{"type": {"displayName": k}, "value": w} for k, w in v.items()]
_xa = [dict(_ev(60, 52, x=70, endx=90, playerId=10, eventId=5, qualifiers=_q("KeyPass")), t=60.0),
       dict(_ev(60, 52, "Goal", x=95, playerId=9, eventId=6, isShot=True, qualifiers=_q(RelatedEventId="5")), t=60.1)]
_j = bascules.joueurs({"playerIdNameDictionary": {"9": "Espí", "10": "Vinícius"}}, _xa, {int(_xa[1]["id"]): 0.44}, 52, 0, 90)
assert any(l.startswith("Vinícius") and "xA 0.44" in l for l in _j) and any(l.startswith("Espí") and "xG 0.44" in l for l in _j), _j
_c2 = [dict(_ev(70, 52, x=99, endx=94, qualifiers=_q("CornerTaken")), t=70.0), dict(_ev(70, 62, "Clearance", x=5), t=70.05),
       dict(_ev(70, 52, "BallRecovery", x=75), t=70.1), dict(_ev(70, 52, "MissedShots", x=85, isShot=True), t=70.15)]
assert bascules.sequences(_c2)[-1]["tirs"][0]["phase"] == "cpa2"
assert round(bascules.bloc([dict(_ev(10, 62, "Tackle", x=20), t=10), dict(_ev(11, 62, "Interception", x=40), t=11)], 62, 0, 90)) == 32
print("OK joueurs, 2e ballon, bloc")

# Phases : récupération au milieu puis dernier tiers en 2 passes = transition ; coup franc dans sa surface = sortie directe, pas CPA
_seq = [dict(_ev(10, 52, "BallRecovery", x=40), t=10.0), dict(_ev(10, 52, x=40, endx=60), t=10.1), dict(_ev(10, 52, x=60, endx=85), t=10.2),
        dict(_ev(10, 52, "SavedShot", x=90, isShot=True), t=10.3),
        dict(_ev(20, 62, x=5, endx=40, qualifiers=[{"type": {"displayName": "FreekickTaken"}}]), t=20.0), dict(_ev(20, 62, x=40, endx=75), t=20.2)]
s1, s2 = bascules.sequences(_seq, [])
assert s1["rapide"] and not s1["placee"] and len(s1["tirs"]) == 1, s1
assert s2["directe"] and not s2["cpa"], s2
assert "1. construction" in texte and "8. CPA défensifs" in texte and "7. défense basse" in texte
print("OK phases")

# Ballon revenu au gardien puis long ballon et tir en 9 s (Valence 75e) : sortie directe, même si la possession a commencé par un coup franc
_fk = [dict(_ev(74, 52, x=56, endx=45, qualifiers=[{"type": {"displayName": "FreekickTaken"}}]), t=74.0),
       dict(_ev(74, 52, x=45, endx=10), t=74.2), dict(_ev(74, 52, x=5, endx=76), t=74.5), dict(_ev(74, 52, x=77, endx=86), t=74.6),
       dict(_ev(74, 52, "Goal", x=98, isShot=True), t=74.65)]
(s3,) = bascules.sequences(_fk, [])
assert s3["tirs"][0]["phase"] == "directe" and s3["tirs"][0]["delai"] == 9, s3["tirs"]
print("OK sortie directe")

# FotMob : résumé hors ligne (stats par mi-temps, couloirs, tirs par situation, renversement du momentum)
import fotmob
_st = lambda a, b: {"stats": [{"stats": [{"title": "Expected goals (xG)", "stats": [a, b]}]}]}
_fm = {"general": {"homeTeam": {"name": "Real Madrid", "id": 1}, "awayTeam": {"name": "Celta", "id": 2}},
       "content": {"stats": {"Periods": {"All": _st("3.76", "1.51"), "FirstHalf": _st("1.69", "1.33"), "SecondHalf": _st("2.07", "0.17")}},
                   "attackingZones": {"home": {"firstHalf": {"left": 45, "center": 21, "right": 34}}},
                   "shotmap": {"shots": [{"teamId": 1, "situation": "FastBreak", "expectedGoals": 0.5}]},
                   "momentum": {"main": {"data": [{"minute": m, "value": 60 if m < 30 else -60} for m in range(0, 60)]}}}}
_t = "\n".join(fotmob.resumer(_fm))
assert "3.76 | 1.51  /  1.69 | 1.33  /  2.07 | 0.17" in _t and "1re 45 / 21 / 34" in _t and "FastBreak 1 (xG 0.50)" in _t, _t
assert "25'-30'" not in _t and "30'-35' (+60 -> -60)" in _t, _t
print("OK fotmob")


# FotMob : finition par tireur, stats Opta des joueurs, faits Opta
_fm["content"]["shotmap"]["shots"] += [{"teamId": 1, "playerName": "Espí", "situation": "RegularPlay", "eventType": "Goal",
                                        "expectedGoals": 0.4, "expectedGoalsOnTarget": 0.7}]
_fm["content"]["playerStats"] = {"9": {"name": "Güler", "teamId": 1, "stats": [{"stats": {
    "Minutes played": {"stat": {"value": 90}}, "Chances created": {"stat": {"value": 3}}, "Recoveries": {"stat": {"value": 0}},
    "Successful dribbles": {"stat": {"value": 3, "total": 4}}}}]}}
_fm["content"]["insights"] = [{"type": "team", "teamId": 1, "text": "Have won their last 8 matches"}]
_t = "\n".join(fotmob.resumer(_fm))
assert "Espí (Real Madrid) 1 tirs, 1 buts, xG 0.40, xGOT 0.70" in _t, _t
assert "Güler 90' : occasions créées 3, dribbles réussis 3/4" in _t and "récupérations" not in _t, _t
assert "fait Opta d'avant-match (ne compte pas ce match) : Real Madrid : Have won their last 8 matches" in _t, _t
print("OK fotmob joueurs")

# bascules : couloirs, duos de passes, note à une minute donnée
assert [bascules.couloir(y) for y in (15, 50, 83)] == ["droite", "axe", "gauche"]
_p = lambda pid, ok=1, team=52: {"t": 1, "teamId": team, "playerId": pid, "isTouch": True, "type": {"displayName": "Pass"}, "outcomeType": {"value": ok}}
_acts = [_p(1), _p(2), _p(1), _p(2), _p(1), _p(2), _p(1), _p(2), _p(1), _p(3, team=62)]
assert bascules.duos(_acts, 52, 0, 5) == [(1, 2, 4), (2, 1, 4)], bascules.duos(_acts, 52, 0, 5)  # la dernière passe va à l'adversaire
assert bascules.note_a({"0": 6.0, "10": 6.5, "60": 7.2}, 59.5) == 6.5 and bascules.note_a({"60": 7}, 30) is None
print("OK bascules joueurs")


# duels : règle Opta (tout tacle gagné, dribblé et faute commise perdus), part par période, zones (sens retourné), face-à-face
_d = lambda pid, team, typ, ok, x=50, y=50, t=1.0: {"t": t, "teamId": team, "playerId": pid, "type": {"displayName": typ},
                                                     "outcomeType": {"value": ok}, "period": {"value": 1}, "x": x, "y": y}
assert bascules.GAGNE(_d(1, 52, "Tackle", 0)) and not bascules.GAGNE(_d(1, 52, "Challenge", 0)) and not bascules.GAGNE(_d(1, 52, "Foul", 0))
_duels = [_d(1, 52, "TakeOn", 1, t=1), _d(9, 62, "Challenge", 0, t=1),          # 1 dribble 9
          _d(1, 52, "TakeOn", 0, t=2), _d(9, 62, "Tackle", 0, t=2),             # 9 tacle 1 (ballon sorti : gagné quand même)
          _d(1, 52, "Aerial", 1, x=20, y=90, t=3), _d(9, 62, "Aerial", 0, x=80, y=10, t=3),
          _d(1, 52, "Foul", 1, t=4), _d(9, 62, "Foul", 0, t=4)]
assert round(bascules.mesurer(_duels, [], 52, True, 0, 10)["duels"]) == 75
assert bascules.duels_zones(_duels, 52, 0, 10, mini=1)[0] == ("milieu", "axe", 2, 3), bascules.duels_zones(_duels, 52, 0, 10, mini=1)
assert ("défense", "gauche", 1, 1) in bascules.duels_zones(_duels, 52, 0, 10, mini=1)
assert ("attaque", "droite", 0, 1) in bascules.duels_zones(_duels, 62, 0, 10, mini=1)  # le même duel aérien, vu par l'adversaire
assert bascules.face_a_face(_duels) == [(1, 9, 3, 1)], bascules.face_a_face(_duels)
print("OK duels")

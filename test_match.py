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

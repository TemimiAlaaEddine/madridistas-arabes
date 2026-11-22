"""Tests hors ligne de postes.py : rôles, comptes, score, raisons."""
import postes

# rôles des places du système WhoScored
assert postes.role_place(0, 5) == "gardien"
assert [postes.role_place(2.5, h) for h in (1, 3.5, 9)] == ["latéral", "défenseur central", "latéral"]
assert postes.role_place(5, 3.5) == "milieu défensif" and postes.role_place(6, 3.5) == "relayeur"
assert postes.role_place(7, 5) == "meneur" and postes.role_place(7, 2) == "ailier" and postes.role_place(5, 1) == "latéral"
assert postes.role_place(9, 5) == "avant-centre" and postes.role_place(8.5, 2) == "ailier"

# minutes et rôle : le remplaçant prend la place du sortant
_f = lambda a, b, ids: {"startMinuteExpanded": a, "endMinuteExpanded": b, "playerIds": ids, "formationSlots": [1, 2, 0],
                        "formationPositions": [{"vertical": 0, "horizontal": 5}, {"vertical": 9, "horizontal": 5}]}
_eq = {"formations": [_f(0, 60, [1, 2, 3]), _f(60, 95, [1, 3, 2])]}
assert postes.minutes_et_roles(_eq, 0, 95) == {1: (95, "gardien"), 2: (60, "avant-centre"), 3: (35, "avant-centre")}
print("OK rôles")

# comptes : xA par la passe reliée au tir, but, réception à la relance, être dribblé
_e = lambda t, team, typ, pid, ok=1, x=50, y=50, **k: {"t": t, "teamId": team, "playerId": pid, "type": {"displayName": typ},
                                                        "outcomeType": {"value": ok}, "x": x, "y": y, "isTouch": True, **k}
_q = lambda **v: [{"type": {"displayName": n}, "value": w} for n, w in v.items()]
_acts = [_e(1, 52, "Pass", 10, x=30, endX=60, endY=50, eventId=5), _e(1.05, 52, "Pass", 11, x=60, endX=90, endY=50, eventId=6),
         _e(1.1, 52, "Goal", 12, x=95, isShot=True, isGoal=True, id=99, eventId=7, qualifiers=_q(RelatedEventId="6")),
         _e(2, 62, "TakeOn", 20), _e(2, 52, "Challenge", 11, ok=0)]
c, adv, xgot_subi, buts = postes.compter(_acts, {99: 0.4}, {99: 0.7}, 52, 0, 5)
assert c[11]["xa"] == 0.4 and c[11]["recues_relance"] == 1 and c[11]["dribble"] == 1 and c[11]["prog"] == 1, c[11]
assert c[12]["buts"] == 1 and c[12]["xg"] == 0.4 and round(c[12]["finition"], 2) == 0.3 and c[12]["touches_surface"] == 1, c[12]
assert adv == 0 and xgot_subi == 0 and buts == 0
print("OK comptes")

# score : au-dessus du repère = positif ; ne pas faire d'erreur n'est pas une raison
_rep = {"matchs": 1, "roles": {"avant-centre": {k: [1.0, 0.5] for k in postes.POIDS["avant-centre"]}}, "joueurs": {}}
_v = {k: 1.0 for k in postes.POIDS["avant-centre"]} | {"xg": 2.0, "pertes": 0.0}
s, contrib = postes.noter("avant-centre", _v, _rep)
assert s > 0 and contrib["xg"] > 0 and contrib["pertes"] > 0
_c = {k: 0 for k in postes.NOMS} | {"xg": 2.0, "pertes": 0}
r = postes.raisons("avant-centre", _c, _v, contrib)
assert "xG 2.00" in r and "ballons perdus" not in r, r
print("OK score")

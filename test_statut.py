"""Vérification rapide du tableau de bord : python test_statut.py (panne, quota à 90 %, journée calme, secrets masqués)."""
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import statut as s

sys.stdout.reconfigure(encoding="utf-8")
UTC = datetime(2026, 11, 23, 17, 0)  # 18 h à Madrid
RIEN = Path("inexistant")


def run(minutes_avant, conclusion="success"):
    t = s.iso(UTC - timedelta(minutes=minutes_avant)) + "Z"
    return {"status": "completed", "conclusion": conclusion, "created_at": t, "updated_at": t, "html_url": "https://github.com/x/actions/runs/1"}


def base():
    con = sqlite3.connect(":memory:")  # tables absentes : chaque compteur vaut 0, comme une base neuve
    con.execute("CREATE TABLE unes (jour TEXT, journal TEXT, x TEXT, facebook TEXT)")
    con.executemany("INSERT INTO unes VALUES ('2026-11-23', ?, 'sans', 'sans')", [("marca",), ("as",)])  # unes sans le Real : pas d'alerte
    con.execute("CREATE TABLE resumes (jour TEXT, typefully TEXT)")
    con.execute("INSERT INTO resumes VALUES ('2026-11-22', '123')")
    return con


def rendre(passages, quota, sante=None, **kw):
    d = s.donnees(base(), UTC, passages, scripts=RIEN, videos=RIEN, connaissance=RIEN, quota=quota, brouillons=set(), sante=sante, **kw)
    return d, s.page(d)


SANTE_OK = {"numero": 17, "url": "https://github.com/x/issues/17", "date": "", "lignes": [("ok", "Jeton Facebook valide (Page « P »).")]}

# 1. panne : dernier passage vieux de 2 h
d, html = rendre([run(120)], (300, 1000, 400, False), SANTE_OK)
assert d["alertes"][0]["niveau"] == "panne" and "Aucun passage depuis 120 min" in d["alertes"][0]["quoi"], d["alertes"]
assert 'class="etat-global e-bloque"' in html and "Panne en cours" in html
assert "Rien à traiter" not in html

# 2. quota projeté à 90 %
d, html = rendre([run(5)], (810, 1000, 900, True), SANTE_OK)
q = [a for a in d["alertes"] if "Quota Typefully projeté à 90 %" in a["quoi"]]
assert q and q[0]["niveau"] == "surveiller", d["alertes"]
assert "Ça tourne · 1 point à regarder" in html and "r-surveiller" in html

# 3. journée calme : rien à traiter, bandeau vert
d, html = rendre([run(15), run(5)], (300, 1000, 400, False), SANTE_OK)
assert d["alertes"] == [], d["alertes"]
assert "Rien à traiter" in html and 'class="etat-global e-ok"' in html and ">Tout tourne<" in html
assert "un passage toutes les ~10 min" in html  # rythme mesuré, pas écrit à la main

# 4. API indisponibles : la page le dit au lieu d'afficher des zéros
d, html = rendre([], None, None, github_ok=False, indispo=["Quota Typefully : donnée indisponible, l'API Typefully a répondu « 401 »."])
assert "donnée indisponible" in html and "Données indisponibles" in html
assert "Quota Typefully illisible" in html

# 5. santé du lundi en échec → alerte « important » et agent bloqué
mauvais = dict(SANTE_OK, lignes=[("ko", "Jeton Facebook refusé (HTTP Error 400). À renouveler")])
d, html = rendre([run(5)], (300, 1000, 400, False), mauvais)
assert d["alertes"][0]["niveau"] == "important" and next(a for a in d["agents"] if a["id"] == "sante")["etat"] == "bloque"

# 6. aucun jeton sur la page, même dans un message d'erreur
assert s.masquer("HTTP 400 https://graph.facebook.com/me?access_token=EAABsecret123&fields=id") == "HTTP 400 https://graph.facebook.com/me?access_token=…&fields=id"
assert "EAAB" not in s.masquer("jeton EAABwzLixnjYBO" + "x" * 40)
assert not re.search(r"Bearer|access_token=[^…]", html)

# 7. section santé de l'issue du lundi lue
assert s.sante_issue("## Santé technique\n\n- ✅ ok\n- ❌ **Jeton** refusé\n\n## Suite\n- ✅ hors section") == [("ok", "ok"), ("ko", "Jeton refusé")]

print("test_statut : OK")

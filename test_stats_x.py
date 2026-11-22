"""Tests de stats_x.py : lecture de l'export CSV de X, lien avec la base, classement."""
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import stats_x as s

sys.stdout.reconfigure(encoding="utf-8")
con = sqlite3.connect(":memory:")
con.row_factory = sqlite3.Row
con.executescript("""
CREATE TABLE liens_x (typefully TEXT, url TEXT, date TEXT);
CREATE TABLE threads (article_id INTEGER, typefully TEXT);
CREATE TABLE articles (id INTEGER, section TEXT, mode TEXT, journal TEXT);
CREATE TABLE unes (x TEXT);
INSERT INTO liens_x VALUES ('10', 'https://x.com/ElMadridistAlaa/status/111', '2026-11-21T19:00:00.000Z'),
                           ('11', 'https://x.com/ElMadridistAlaa/status/222', '2026-11-23T08:30:00.000Z'),
                           ('12', 'https://x.com/ElMadridistAlaa/status/333', '2026-11-22T07:00:00.000Z');
INSERT INTO threads VALUES (1, '10'), (2, '11');
INSERT INTO articles VALUES (1, 'actus', 'info', 'Marca'), (2, 'debats', 'opinion', 'AS');
INSERT INTO unes VALUES ('12');
""")
# export au format actuel (en-têtes en anglais, BOM, nombres avec séparateur de milliers)
export = ("﻿Post id,Date,Post text,Post Link,Impressions,Likes,Engagements,Bookmarks,New follows,Replies,Reposts\n"
          '111,"Sat, Nov 21, 2026","🚨 عاجل | خبر",https://x.com/a/status/111,"1,200",30,90,2,3,4,5\n'
          '222,"Mon, Nov 23, 2026","🔥 نقاش | سؤال؟",https://x.com/a/status/222,800,10,40,1,0,9,2\n'
          '333,"Sun, Nov 22, 2026","📰 غلاف ماركا | الأحد",https://x.com/a/status/333,500,5,10,0,0,0,1\n'
          '444,"Sun, Nov 22, 2026","📰 AS\n🔗 المصدر: https://as.com/1",https://x.com/a/status/444,50,0,2,0,0,0,0\n'
          '555,"Sun, Nov 22, 2026","⭐ أداء | غولر",https://x.com/a/status/555,300,20,25,0,1,1,1\n')
with tempfile.TemporaryDirectory() as tmp:
    f = Path(tmp) / "x.csv"
    f.write_text(export, encoding="utf-8")
    ps = {p["id"]: p for p in s.posts(f, con)}
assert ps["111"]["vues"] == 1200 and ps["111"]["interactions"] == 90 and ps["111"]["type"] == "Nouvelle"
assert ps["111"]["journal"] == "Marca" and ps["111"]["etiquette"] == "🚨 عاجل" and ps["111"]["format"] == "Thread"
assert ps["111"]["tranche"] == "soir (18-24 h)", "heure de Typefully (19 h UTC = 20 h à Madrid)"
assert ps["222"]["type"] == "Opinion" and ps["222"]["format"] == "Tweet long"
assert ps["333"]["type"] == "Une de journal" and ps["444"]["type"] == "Réponse (lien de la source)"
assert ps["555"]["type"] == "Tweet joueur" and ps["555"]["tranche"] == "heure inconnue" and ps["555"]["etiquette"] == "⭐ أداء"
r = s.rapport(list(ps.values()))
assert "4 posts" in r and "Réponses avec le lien de la source : 1" in r and "x.com/i/status/111" in r
assert ps["222"]["hashtags"] == "(aucun)" and "Hashtags" in r
assert s.hashtags("⏱️ نهاية\n\n#ريال_مدريد_سيلتا_فيغو #الليغا #الليغا") == "#ريال_مدريد_سيلتا_فيغو #الليغا"
assert s.etiquette("🗣️ مورينيو | «...»") == "🗣️ تصريح" and s.etiquette("نص عادي") == "(sans étiquette)"
assert s.date_csv("2026-11-22 08:11 +0100") == datetime(2026, 11, 22, 7, 11), "converti en UTC"
try:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "y.csv").write_text("Foo,Bar\n1,2\n", encoding="utf-8")
        s.lire_csv(Path(tmp) / "y.csv")
    raise AssertionError("aurait dû refuser")
except ValueError as err:
    assert "Foo" in str(err), "les colonnes lues sont affichées"
print("OK stats X")

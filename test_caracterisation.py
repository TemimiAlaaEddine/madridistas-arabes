"""Tests de caractérisation : figent le comportement actuel des fonctions sans test, avant le nettoyage du code."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import commun
import conference as c
import fotmob
import galerie
import generer_site as g
import threads

sys.stdout.reconfigure(encoding="utf-8")

# normalisation sans accents : minuscules ASCII (conference.plat), slug des journalistes (generer_site.slug)
assert c.plat(None) == "" and c.plat("José MOURINHO") == "jose mourinho" and c.plat("  É ") == "  e "
assert c.plat("أردا Güler") == " guler"
assert g.slug("Sergio Rodríguez C.") == "sergio-rodriguez-c" and g.slug("Ødegaard") == "degaard" and g.slug("") == "auteur"
assert g.slug("--Ödön  Kovács--") == "odon-kovacs" and g.slug("محمد") == "auteur"
assert threads.personnes_citees("Guler marque") == set() and "guler" in threads.personnes_citees("guler marque")
print("OK sans accents")

# tri : l'entraîneur est reconnu dans le titre aux accents et majuscules près
_vrai_claude = g.appeler_claude
g.appeler_claude = lambda *a, **k: "[]"
_gardes, _ecartes = g.trier([{"source": "AS", "titre": "JOSÉ MOURINHO: «Calma»", "resume": ""},
                             {"source": "El País", "titre": "Mourínho habla", "resume": ""}])
assert [it["titre"] for it in _gardes] == ["JOSÉ MOURINHO: «Calma»"] and _gardes[0]["type"] == "info" and len(_ecartes) == 1
g.appeler_claude = _vrai_claude
print("OK tri entraîneur")

# pages lues avec curl et un User-Agent de navigateur (FotMob, site du club)
_appels = []
_vrai_run = subprocess.run


def _faux_run(cmd, **k):
    _appels.append((cmd, k))
    page = b'<html><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"x":1}}}</script></html>'
    return subprocess.CompletedProcess(cmd, 0, page, b"")


subprocess.run = _faux_run
assert fotmob.page("/matches/a") == {"x": 1}
assert galerie.lire("https://www.realmadrid.com/x").startswith(b"<html>")
subprocess.run = _vrai_run
for (cmd, k), url in zip(_appels, (fotmob.SITE + "/matches/a", "https://www.realmadrid.com/x")):
    assert cmd == ["curl", "-s", "-f", "-m", "60", "-A", galerie.NAVIGATEUR, url], cmd
    assert k == {"capture_output": True, "check": True, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}, k
subprocess.run = lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, b"<html></html>", b"")
try:
    fotmob.page("/vide")
    raise AssertionError("page sans données acceptée")
except ValueError as err:
    assert "pas de données dans /vide" in str(err)
subprocess.run = _vrai_run
print("OK curl")

# déclarations des flux d'un journal : après `depuis`, sans doublon de lien, de la plus ancienne à la plus récente
_t = lambda h, m: time.struct_time((2026, 11, 23, h, m, 0, 0, 327, 0))
_entrees = [{"title": 'Mourinho: "B"', "link": "l2", "summary": "", "published_parsed": _t(12, 10)},
            {"title": 'Mourinho: "A"', "link": "l1", "summary": "", "published_parsed": _t(12, 5)},
            {"title": 'Mourinho: "vieux"', "link": "l0", "summary": "", "published_parsed": _t(11, 0)},
            {"title": "Otra cosa", "link": "l3", "summary": "", "published_parsed": _t(12, 20)},
            {"title": "“Cita”", "link": "l4", "summary": "dijo Mourinho", "updated_parsed": _t(12, 30)},
            {"title": 'Mourinho: "sin fecha"', "link": "l5", "summary": ""}]
_vrai_parse, _vrai_flux = c.feedparser.parse, c.FLUX
c.FLUX = {"Marca": ["u1", "u2"]}
c.feedparser.parse = lambda url: SimpleNamespace(entries=_entrees)  # les deux flux donnent les mêmes articles
assert [d[2] for d in c.declarations("Marca", datetime(2026, 11, 23, 12))] == ["l1", "l2", "l4"]
assert c.declarations("Marca", datetime(2026, 11, 23, 12))[0] == (datetime(2026, 11, 23, 12, 5), 'Mourinho: "A"', "l1", "")
c.feedparser.parse, c.FLUX = _vrai_parse, _vrai_flux
print("OK déclarations des flux")

# tweet du direct : réponse de Claude -> DOUBLON, HORS ou le texte
_prompts = []
for reponse, attendu in (("  DOUBLON  ", "DOUBLON"), ("C'est un DOUBLON", "DOUBLON"), ("HORS", "HORS"), ("", "HORS"),
                         ("🎙️ مؤتمر | «x»\n", "🎙️ مؤتمر | «x»"), ("HORSAIN texte", "HORSAIN texte")):
    c.appeler_claude = lambda p, *a, r=reponse: (_prompts.append((p, a)), r)[1]
    assert c.tweet("T", "x" * 7000, ["a", "b"]) == attendu, reponse
_p, _a = _prompts[0]
assert "Titre : T\n" + "x" * 6000 + "\n" in _p and "x" * 6001 not in _p and "a\n---\nb" in _p and _a[1] == "low"
c.tweet("T", "t", [])
assert "(aucun)" in _prompts[-1][0]
c.appeler_claude = commun.appeler_claude
print("OK tweet du direct")

# conférences déjà parties par le passage principal
with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp) / "a.db"
    vrai_db, vrai_restaurer = commun.DB_PATH, commun.restaurer_base
    commun.DB_PATH, commun.restaurer_base = base, lambda chemin: False
    assert c.deja_publies(datetime(2026, 11, 23)) == ([], [])  # base vide
    con = g.connexion(base)
    threads.connexion_threads(con)
    for i, mode, statut, typefully, envoye in ((1, "conference", "immédiat", "5", "2026-11-23T12:00:00"),
                                                (2, "conference", "bloqué : x", "6", "2026-11-23T12:00:00"),
                                                (3, "info", "immédiat", "7", "2026-11-23T12:00:00"),
                                                (4, "conference", "file", "8", "2026-11-22T12:00:00")):
        con.execute("INSERT INTO articles (id, mode, lien) VALUES (?, ?, ?)", (i, mode, f"l{i}"))
        con.execute("INSERT INTO threads (article_id, tweets, statut, typefully, envoye, date) VALUES (?, ?, ?, ?, ?, 'd')",
                    (i, json.dumps([f"t{i}", "suite"]), statut, typefully, envoye))
    con.commit()
    con.close()
    assert c.deja_publies(datetime(2026, 11, 23)) == (["l1"], ["t1"])
    commun.DB_PATH, commun.restaurer_base = vrai_db, vrai_restaurer
print("OK conférences déjà publiées")

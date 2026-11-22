"""Tests hors ligne de galerie.py : chronique trouvée par la date, photos de la galerie dans l'ordre."""
import galerie

_liste = 'x":"\u002Fes-ES\u002Fnoticias\u002Ffutbol\u002Fprimer-equipo\u002Fcronicas\u002Fcronica-real-madrid-celta-j13-liga-21-11-2026"'
_vrai = galerie.lire
galerie.lire = lambda url: _liste.encode()
assert galerie.chronique("2026-11-21") == galerie.CRONICAS + "/cronica-real-madrid-celta-j13-liga-21-11-2026"
assert galerie.chronique("2026-11-24") is None
galerie.lire = _vrai
_page = ("assets.realmadrid.com/is/image/realmadrid/ND-LIGA-J13-RM-CELTA-ALEGRIA-VINICIUS-ESPI-01_AV19029?wid=1 "
         "assets.realmadrid.com/is/image/realmadrid/01_JT30825 assets.realmadrid.com/is/image/realmadrid/3kq9cckrnlogidldtdie2fkbl "
         "assets.realmadrid.com/is/image/realmadrid/01_JT30825 assets.realmadrid.com/is/image/realmadrid/02_DB16598")
assert galerie.photos(_page) == ["ND-LIGA-J13-RM-CELTA-ALEGRIA-VINICIUS-ESPI-01_AV19029", "01_JT30825", "02_DB16598"], "écussons écartés, sans doublon"
print("OK galerie")

# nettoyage : photos de plus de 7 jours effacées, pages du match gardées, dossiers sans date ignorés
import tempfile
from datetime import date
from pathlib import Path
with tempfile.TemporaryDirectory() as _d:
    for nom in ("2026-11-07-valencia", "2026-11-21-celta-vigo", "journal"):
        (Path(_d) / nom / "photos").mkdir(parents=True)
        (Path(_d) / nom / "whoscored.html").write_text("x")
    assert galerie.nettoyer(_d, date(2026, 11, 22)) == ["2026-11-07-valencia"]
    assert not (Path(_d) / "2026-11-07-valencia" / "photos").exists() and (Path(_d) / "2026-11-07-valencia" / "whoscored.html").exists()
    assert (Path(_d) / "2026-11-21-celta-vigo" / "photos").exists() and (Path(_d) / "journal" / "photos").exists()
print("OK nettoyage")

# joueurs mis en avant par le club : nom des photos de ses articles, seulement celles de ce match
assert galerie.etiquette(["01_JT30825", "ND-LIGA-J13-RM-CELTA-ALEGRIA-VINICIUS-ESPI-01_AV19029"]) == "ND-LIGA-J13-RM-CELTA"
assert galerie.etiquette(["01_JT30825"]) is None
_art = ("realmadrid/ND-LIGA-J13-RM-CELTA-ALEGRIA-BELLINGHAM-VINICIUS-02_AV17181 realmadrid/ND-LIGA-J13-RM-CELTA-RP-MOURINHO-01_AV19936 "
        "realmadrid/ND-LIGA-J01-RM-RSOCIEDAD-ALEGRIA-VINI-BELLINGHAM_AV11135 realmadrid/ND-LIGA-J13-RM-CELTA-COURTOIS-01_AV19763")
_art = " ".join("assets.realmadrid.com/is/image/" + m for m in _art.split())
galerie.lire = lambda url: _art.encode()
_j = {"Jude Bellingham": {"JUDE", "BELLINGHAM"}, "Vinícius Júnior": {"VINICIUS", "JUNIOR", "VINI"}, "Thibaut Courtois": {"THIBAUT", "COURTOIS"}}
assert galerie.mis_en_avant("ND-LIGA-J13-RM-CELTA", _j, pages=["x"]) == {
    "Jude Bellingham": ["ND-LIGA-J13-RM-CELTA-ALEGRIA-BELLINGHAM-VINICIUS-02_AV17181"],
    "Thibaut Courtois": ["ND-LIGA-J13-RM-CELTA-COURTOIS-01_AV19763"],
    "Vinícius Júnior": ["ND-LIGA-J13-RM-CELTA-ALEGRIA-BELLINGHAM-VINICIUS-02_AV17181"]}, "autre match et entraîneur écartés"
galerie.lire = _vrai
print("OK mis en avant")

# Google Images : vignettes valides gardées avec leur page source, planche écrite ; entrée sans image d'origine écartée
import base64, io, json as _json
import match as _match
from PIL import Image as _Image
_b = io.BytesIO(); _Image.new("RGB", (40, 30), "red").save(_b, "JPEG")
_v = "data:image/jpeg;base64," + base64.b64encode(_b.getvalue()).decode()
_rep = {"images": [{"original_image": "https://x/1.jpg", "image": _v, "source": "Arda Güler renueva"},
                   {"image": _v, "source": "sans lien"}, {"original_image": "https://x/2.jpg", "image": _v, "title": "Daily Sabah"}]}
_vrai_bd, _match.bright_data = _match.bright_data, lambda url: _json.dumps(_rep)
with tempfile.TemporaryDirectory() as _d:
    assert galerie.google_images("Arda Güler", _d) == [(1, "https://x/1.jpg", "Arda Güler renueva"), (2, "https://x/2.jpg", "Daily Sabah")]
    assert (Path(_d) / "planche-google.jpg").exists()
_match.bright_data = _vrai_bd
print("OK google")

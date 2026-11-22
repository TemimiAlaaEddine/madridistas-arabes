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

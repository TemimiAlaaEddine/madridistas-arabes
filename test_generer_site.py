"""Vérification rapide : python test_generer_site.py"""
import io
import json
import tempfile
import urllib.parse
from pathlib import Path

import couvertures
import generer_site as g

couvertures.EDGE = None  # pas de rendu d'images par Edge dans les tests (lent) ; le gabarit est testé à part

items = [
    {"lien": "https://ex.com/1", "titre": "Mourinho encuentra el equilibrio", "auteur": "Jesús Gallego",
     "source": "AS - Opinion", "pays": "es", "autorise": False},
    {"lien": "https://ex.com/2", "titre": "Autre", "auteur": "X", "source": "Marca", "pays": None, "autorise": True},
]
reponses = [
    {"id": 1, "section": "tactique", "titre": "مورينيو <يجد> التوازن", "chapeau": "ج", "texte": "فقرة 1\n\nفقرة 2",
     "auteur_ar": "خيسوس غاييغو", "personnes": ["mourinho", "inconnu"], "sujet": "mourinho"},
    {"id": 2, "section": "nimporte", "titre": "ت", "texte": "ن"},  # section inconnue -> debats
    {"id": 9, "titre": "hors limites", "texte": "x"},  # id invalide -> ignoré
    {"id": 1, "titre": "", "texte": "x"},  # titre vide -> ignoré
]

with tempfile.TemporaryDirectory() as tmp:
    db, site = Path(tmp) / "a.db", Path(tmp) / "site"
    assert g.enregistrer(reponses, items, db) == 2
    assert g.enregistrer(reponses, items, db) == 0  # même lien : pas de doublon
    g.rendre_site(db, site)
    a1 = (site / "a-1.html").read_text(encoding="utf-8")
    assert "&lt;يجد&gt;" in a1 and "<يجد>" not in a1  # texte échappé
    assert "Jesús Gallego" in a1 and "AS" in a1 and "https://ex.com/1" in a1
    assert 'href="p-mourinho.html"' in a1 and "inconnu" not in a1
    assert "ت" in (site / "debats.html").read_text(encoding="utf-8")
    assert 'href="recherche.html"' in a1 and 'id="q"' in (site / "recherche.html").read_text(encoding="utf-8")
    index = (site / "articles.js").read_text(encoding="utf-8")  # index de la recherche : titre arabe, auteur latin, personnes
    assert "مورينيو <يجد> التوازن" in index and "Jesús Gallego" in index and "Mourinho encuentra" in index and "</" not in index
    assert (site / "recherche.js").exists()
    for f in ["index.html", "revue.html", "presse.html", "tactique.html", "j-jesus-gallego.html",
              "p-mourinho.html", "pays-es.html", "style.css", "a-2.html"]:
        assert (site / f).exists(), f
    assert "ترجمة كاملة" in (site / "a-2.html").read_text(encoding="utf-8")
print("OK")

# alternance des pays : la presse étrangère n'attend pas derrière l'espagnole
lot = [{"pays": "es", "n": 1}, {"pays": "es", "n": 2}, {"pays": "es", "n": 3}, {"pays": "gb", "n": 4}, {"pays": "br", "n": 5}]
assert [x["n"] for x in g.alterner_pays(lot)] == [1, 4, 5, 2, 3]

# article sans auteur dans le flux : nom trouvé par Claude, sinon pas de page journaliste
with tempfile.TemporaryDirectory() as tmp:
    db, site = Path(tmp) / "a.db", Path(tmp) / "site"
    sans = [{"lien": "https://ex.com/3", "titre": "T", "auteur": "", "source": "ge.globo", "pays": "br"},
            {"lien": "https://ex.com/4", "titre": "T2", "auteur": "", "source": "ge.globo", "pays": "br"}]
    assert g.enregistrer([{"id": 1, "titre": "ع", "texte": "ن", "auteur": "Martín Fernandez", "auteur_ar": "م"},
                          {"id": 2, "titre": "ع2", "texte": "ن2"}], sans, db) == 2
    g.rendre_site(db, site)
    assert (site / "j-martin-fernandez.html").exists() and not (site / "j-auteur.html").exists()
    assert "للكاتب" not in (site / "a-2.html").read_text(encoding="utf-8")
print("OK alternance + auteur")

# rubriques d'opinion d'abord
lot = [{"pays": "es", "n": 1}, {"pays": "gb", "n": 2, "opinion": True}, {"pays": "es", "n": 3, "opinion": True}]
assert [x["n"] for x in g.ordonner(lot)] == [2, 3, 1]
assert [x["n"] for x in g.ordonner(lot + [{"n": 4, "officiel": True}])] == [4, 2, 3, 1]
# même info dans la presse et sur le site du club : le communiqué officiel est gardé, même arrivé après
gardes, retires = g.dedoublonner([{"titre": "Renovación de Arda Güler hasta 2032"},
                                  {"titre": "Comunicado oficial: renovación de Arda Güler hasta 2032", "officiel": True}])
assert [x.get("officiel") for x in gardes] == [True] and len(retires) == 1
print("OK priorité officiel + opinion")

# avis d'un commentateur rapporté par un journaliste (Radio Marca)
with tempfile.TemporaryDirectory() as tmp:
    db, site = Path(tmp) / "a.db", Path(tmp) / "site"
    radio = [{"lien": "https://ex.com/5", "titre": "David Sánchez pincha la euforia", "auteur": "AINHOA SÁNCHEZ",
              "source": "Marca - Opinion", "pays": "es"}]
    assert g.enregistrer([{"id": 1, "titre": "ع", "texte": "ن", "auteur": "David Sánchez", "auteur_ar": "دافيد سانشيث",
                           "via": "راديو ماركا"}], radio, db) == 1
    g.rendre_site(db, site)
    page = (site / "a-1.html").read_text(encoding="utf-8")
    assert "عن راديو ماركا" in page and "AINHOA SÁNCHEZ" in page and "دافيد سانشيث" in page
    assert (site / "j-david-sanchez.html").exists() and not (site / "j-ainhoa-sanchez.html").exists()
print("OK commentateur radio")

# photos libres : licences acceptées et crédit affiché
assert g.licence_libre("CC BY-SA 4.0") and g.licence_libre("CC BY 2.0") and g.licence_libre("CC0") and g.licence_libre("Public domain")
assert not g.licence_libre("CC BY-NC 2.0") and not g.licence_libre("CC BY-ND 4.0") and not g.licence_libre("Fair use") and not g.licence_libre(None)
with tempfile.TemporaryDirectory() as tmp:
    db, site, credits = Path(tmp) / "a.db", Path(tmp) / "site", Path(tmp) / "photos.json"
    credits.write_text('{"mourinho": {"fichier": "mourinho.jpg", "auteur": "Jane <Doe>", "licence": "CC BY-SA 4.0",'
                       ' "licence_url": "https://cc.org/by-sa", "source": "https://commons.wikimedia.org/wiki/File:M.jpg"},'
                       ' "mbappe": null}', encoding="utf-8")
    g.enregistrer(reponses, items, db)
    g.rendre_site(db, site, credits)
    article, fiche = (site / "a-1.html").read_text(encoding="utf-8"), (site / "p-mourinho.html").read_text(encoding="utf-8")
    assert 'src="photos/mourinho.jpg"' in fiche and "Jane &lt;Doe&gt;" in fiche and "CC BY-SA 4.0" in fiche and "File:M.jpg" in fiche
    assert "photos/" not in article  # les articles ont une couverture, plus de photo de joueur
    assert 'class="portrait"' in fiche
    assert "<img" not in (site / "a-2.html").read_text(encoding="utf-8")  # article sans personne avec photo
print("OK photos")

# photo seulement pour le sujet principal (article sur Jacobo Ramón, absent de la liste : pas de photo d'Asencio)
with tempfile.TemporaryDirectory() as tmp:
    db, site, credits = Path(tmp) / "a.db", Path(tmp) / "site", Path(tmp) / "photos.json"
    credits.write_text('{"asencio": {"fichier": "asencio.jpg", "auteur": "X", "licence": "CC BY-SA 2.0", "licence_url": "",'
                       ' "source": "https://commons.wikimedia.org/wiki/File:A.jpg"}}', encoding="utf-8")
    jr = [{"lien": "https://ex.com/13", "titre": "Should Real Madrid Bring Back Jacobo Ramon?", "auteur": "K", "source": "MM", "pays": "us"}]
    g.enregistrer([{"id": 1, "titre": "ع", "texte": "ن", "personnes": ["asencio"], "sujet": ""}], jr, db)
    g.rendre_site(db, site, credits)
    assert "<img" not in (site / "a-1.html").read_text(encoding="utf-8")
    assert 'src="photos/asencio.jpg"' in (site / "p-asencio.html").read_text(encoding="utf-8")  # la page joueur garde sa photo
print("OK sujet")

# section actualités : jamais à la une, bloc dédié sur l'accueil, mention « خبر »
with tempfile.TemporaryDirectory() as tmp:
    db, site = Path(tmp) / "a.db", Path(tmp) / "site"
    lot = [{"lien": "https://ex.com/a", "titre": "Opinion", "auteur": "A", "source": "AS", "pays": "es"},
           {"lien": "https://ex.com/b", "titre": "Courtois lesionado", "auteur": "", "source": "Marca", "pays": "es"}]
    g.enregistrer([{"id": 1, "section": "tactique", "titre": "رأي", "texte": "ن"},
                   {"id": 2, "section": "actus", "titre": "إصابة كورتوا", "chapeau": "خبر قصير", "texte": "وفقًا لصحيفة ماركا"}], lot, db)
    g.rendre_site(db, site)
    accueil = (site / "index.html").read_text(encoding="utf-8")
    une = accueil.split('class="a-la-une"')[1].split("</section>")[0]
    assert "رأي" in une and "إصابة كورتوا" not in une
    assert "آخر الأخبار" in accueil and "إصابة كورتوا" in accueil
    article = (site / "a-2.html").read_text(encoding="utf-8")
    assert ">خبر<" in article and "ملخص خبر نشرته Marca." in article and "مقال رأي" not in article
    assert "إصابة كورتوا" in (site / "actus.html").read_text(encoding="utf-8")
print("OK actualités")

# anti-doublon : les actualités récentes sont données à Claude ; pages obsolètes supprimées
with tempfile.TemporaryDirectory() as tmp:
    db, site = Path(tmp) / "a.db", Path(tmp) / "site"
    g.enregistrer([{"id": 1, "section": "actus", "titre": "إصابة كورتوا", "texte": "ن"}],
                  [{"lien": "https://ex.com/c", "titre": "Courtois lesionado", "auteur": "", "source": "Marca", "pays": "es"}], db)
    deja = g.deja_publies(db)
    assert deja == ["Courtois lesionado"]
    assert "- Courtois lesionado" in g.construire_prompt([], deja)
    assert "(aucune)" in g.construire_prompt([])
    site.mkdir()
    (site / "a-99.html").write_text("vieux", encoding="utf-8")
    g.rendre_site(db, site)
    assert not (site / "a-99.html").exists() and (site / "a-1.html").exists()
print("OK anti-doublon")

# date affichée = date de publication de l'article d'origine
with tempfile.TemporaryDirectory() as tmp:
    db, site = Path(tmp) / "a.db", Path(tmp) / "site"
    g.enregistrer([{"id": 1, "titre": "ع", "texte": "ن"}],
                  [{"lien": "https://ex.com/d", "titre": "T", "auteur": "A", "source": "AS", "pays": "es",
                    "publie": "2026-10-25T21:30:00"}], db)
    g.rendre_site(db, site)
    assert "25 أكتوبر 2026" in (site / "a-1.html").read_text(encoding="utf-8")
print("OK date d'origine")

# couvertures : citation, infographie (chiffres) ou titre d'information ; image affichée sur fiches et article
assert g.chiffres_valides([{"valeur": "100", "libelle": "هدف"}, {"valeur": "61,3%", "libelle": "دقة"}, {"x": 1}]) == \
    [{"valeur": "100", "libelle": "هدف"}, {"valeur": "61,3%", "libelle": "دقة"}]
assert g.chiffres_valides([{"valeur": "100", "libelle": "هدف"}]) == [] and g.chiffres_valides("n'importe quoi") == []
with tempfile.TemporaryDirectory() as tmp:
    db, site = Path(tmp) / "a.db", Path(tmp) / "site"
    lot = [{"lien": f"https://ex.com/{i}", "titre": "T", "auteur": "A", "source": "Marca", "pays": "es"} for i in range(3)]
    g.enregistrer([{"id": 1, "section": "debats", "titre": "ع", "texte": "ن", "auteur_ar": "أ", "citation": "جملة <قوية>"},
                   {"id": 2, "section": "tactique", "titre": "أرقام", "texte": "ن",
                    "chiffres": [{"valeur": "100", "libelle": "هدف"}, {"valeur": "0,67", "libelle": "في المباراة"}]},
                   {"id": 3, "section": "actus", "titre": "خبر عاجل", "texte": "ن"}], lot, db)
    con = g.connexion(db)
    a1, a2, a3 = con.execute("SELECT * FROM articles ORDER BY id").fetchall()
    con.close()
    c1, c2, c3 = couvertures.couverture_html(a1), couvertures.couverture_html(a2), couvertures.couverture_html(a3)
    assert 'class="citation"' in c1 and "جملة &lt;قوية&gt;" in c1 and "<strong>أ</strong>" in c1 and "الصحافة الإسبانية" in c1
    assert 'class="chiffres"' in c2 and "<b>100</b>" in c2 and "<b>0,67</b>" in c2 and 'class="citation"' not in c2
    assert 'class="titre-actu"' in c3 and "خبر عاجل" in c3 and "#FEBE10" in c3
    g.generer_couvertures = lambda arts, dossier: {a["id"]: f"a-{a['id']}-test.png" for a in arts}  # simule Edge
    g.rendre_site(db, site)
    assert 'src="couvertures/a-2-test-v.webp"' in (site / "index.html").read_text(encoding="utf-8")  # cartes : vignette
    assert '<figure class="couverture"><img src="couvertures/a-1-test.png" alt="جملة &lt;قوية&gt;"' in \
        (site / "a-1.html").read_text(encoding="utf-8")
print("OK couvertures")
assert g.chiffres_valides([{"valeur": "30 مليون دولار سنويًا", "libelle": "x"}, {"valeur": "1", "libelle": "y"}]) == []  # pas de valeur coupée
print("OK valeurs longues")

# directs commentés écartés avant Claude ; la composition officielle, elle, passe
assert g.est_direct({"titre": "Racing de Santander - Real Madrid, en directo: cómo va el partido", "lien": "https://abc.es/x"})
assert g.est_direct({"titre": "Barcelona 1-2 Real Madrid: El Clásico – as it happened", "lien": "https://x"})
assert g.est_direct({"titre": "Match", "lien": "https://www.theguardian.com/football/live/2026/oct/25/x"})
assert not g.est_direct({"titre": "Alineación oficial del Real Madrid ante el Racing", "lien": "https://www.marca.com/a.html"})
assert not g.est_direct({"titre": "Lizarazu señala dónde se le escapó a Mbappé el Balón de Oro", "lien": "https://www.marca.com/b.html"})
# le « déjà publié » couvre toutes les sections (doublon Lizarazu : deux articles d'opinion)
with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "a.db"
    g.enregistrer([{"id": 1, "section": "debats", "titre": "ليزارازو ينتقد مبابي", "texte": "ن"}],
                  [{"lien": "https://ex.com/l", "titre": "Lizarazu recadre Mbappé", "auteur": "", "source": "Foot Mercato", "pays": "fr"}], db)
    assert g.deja_publies(db) == ["Lizarazu recadre Mbappé"]
print("OK directs et doublons d'opinion")

# threads X : longueur comptée comme X, crédit + numérotation, thread refusé si un tweet dépasse 280
import sqlite3
import threads as t
TELECHARGER = t.telecharger_image  # vraie fonction : des tests plus bas la remplacent sans la remettre
assert t.longueur("ريال مدريد") == 10 and t.longueur("https://www.marca.com/" + "x" * 200) == 23 and t.longueur("🔥") == 2
art = {"auteur_ar": "خوانما كاستانيو", "auteur": "Juanma Castaño", "journal": "Marca", "lien": "https://marca.com/a"}
th = t.assembler(art, ["فكرة أولى", "فكرة ثانية"])
assert len(th) == 3 and th[0].endswith("1/2") and th[1].endswith("2/2") and "خوانما كاستانيو | Marca" in th[2] and "https://marca.com/a" in th[2]
assert not t.NUMERO.search(th[2])  # le tweet du lien ne compte pas dans la numérotation
assert t.assembler(art, ["فكرة وحيدة"])[0] == "فكرة وحيدة"  # un seul tweet + le lien : pas de numéro
assert t.assembler(art, ["ب" * 290]) is None and t.assembler(art, []) is None
with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "a.db"
    g.enregistrer([{"id": 1, "section": "debats", "titre": "ع", "texte": "ن"}],
                  [{"lien": "https://ex.com/t", "titre": "T", "auteur": "", "source": "Marca", "pays": "es"}], db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    t.appeler_claude = lambda prompt, *a: '[{"id": 1, "tweets": ["فكرة"]}, {"id": 99, "tweets": ["x"]}]'
    assert t.decouper(con) == 1 and t.decouper(con) == 0  # id inconnu ignoré, pas de second thread
    # Page Facebook : titres en message, lien à part (carte), une seule fois ; articles déjà là au 1er passage ignorés
    t.SECRETS = Path(tmp) / "aucun.json"  # ignore le secrets.json local (vrais jetons)
    assert t.vers_page(con) == 0  # inactive sans jeton
    appels = []
    t.CONFIG.update(facebook_page_token="j", facebook_page_id="42")
    vrai_urlopen, t.urllib.request.urlopen = t.urllib.request.urlopen, (
        lambda req, timeout=None: (appels.append((req.full_url, req.data.decode())), io.BytesIO(b"{}"))[1])
    try:
        con.execute("UPDATE articles SET titres_fb = ?", ('{"fr": "Vieux", "en": "Old", "es": "Viejo"}',))
        con.commit()
        assert t.vers_page(con) == 0
        g.enregistrer([{"id": 1, "section": "actus", "titre": "خ", "texte": "ن",
                        "titres_fb": {"fr": "Titre", "en": "Title", "es": "Título"}}],
                      [{"lien": "https://ex.com/fb", "titre": "T2", "auteur": "", "source": "AS", "pays": "es"}], db)
        assert t.vers_page(con) == 1 and t.vers_page(con) == 0
        # la Page ne reçoit que les nouvelles : ni opinion, ni composition probable
        fb = lambda fr: {"fr": fr, "en": "Opinion", "es": "Opinión"}
        g.enregistrer([{"id": 1, "section": "debats", "titre": "رأي جديد في النقاش", "texte": "ن", "titres_fb": fb("Un avis tranché sur le débat")},
                       {"id": 2, "section": "actus", "titre": "التشكيلة المحتملة أمام سيلتا", "texte": "ن", "titres_fb": fb("La composition probable contre le Celta")},
                       {"id": 3, "section": "club", "titre": "حفل موسيقي في البرنابيو قريبًا", "texte": "ن", "titres_fb": fb("Un concert au Bernabéu bientôt")},
                       {"id": 4, "section": "mercato", "titre": "صفقة الشتاء التي يحتاجها الفريق", "texte": "ن", "titres_fb": fb("Le transfert d'hiver dont l'équipe a besoin")}],
                      [{"lien": "https://ex.com/op", "titre": "Una opinión", "auteur": "", "source": "AS", "pays": "es", "type": "opinion"},
                       {"lien": "https://ex.com/xi", "titre": "Alineación probable del Madrid", "auteur": "", "source": "AS", "pays": "es", "type": "info"},
                       {"lien": "https://ex.com/nfl", "titre": "Concierto en el Bernabéu", "auteur": "", "source": "AS", "pays": "es", "type": "info"},
                       {"lien": "https://ex.com/fichaje", "titre": "El fichaje de invierno", "auteur": "", "source": "AS", "pays": "es", "type": "opinion"}], db)
        assert t.vers_page(con) == 2 and "ex.com%2Fnfl" in appels[-2][1] and "ex.com%2Ffichaje" in appels[-1][1]  # mercato compris
        assert t.vers_page(con) == 0 and not any("ex.com%2Fop" in c or "ex.com%2Fxi" in c for _, c in appels)
        # même nouvelle venue d'un autre journal : pas de second post Facebook
        g.enregistrer([{"id": 1, "section": "club", "titre": "حفل في برنابيو", "texte": "ن", "titres_fb": fb("Un concert au Bernabéu, bientôt")}],
                      [{"lien": "https://ex.com/nfl2", "titre": "Concierto en el estadio", "auteur": "", "source": "Marca", "pays": "es", "type": "info"}], db)
        assert t.vers_page(con) == 0 and not any("nfl2" in c for _, c in appels)
        assert con.execute("SELECT post FROM page_facebook p JOIN articles a ON a.id = p.article_id WHERE a.lien = 'https://ex.com/nfl2'").fetchone()[0].startswith("bloqué : doublon")
    finally:
        t.urllib.request.urlopen = vrai_urlopen
        t.CONFIG.pop("facebook_page_token")
    assert appels[0][0].endswith("/42/feed") and "link=https%3A%2F%2Fex.com%2Ffb" in appels[0][1] and "Titre" in urllib.parse.unquote_plus(appels[0][1])
    # avec l'image principale : publiée en photo, titres et journal en légende, sans le lien (bloqué au Canada)
    con.execute("DELETE FROM page_facebook WHERE article_id = (SELECT id FROM articles WHERE lien = 'https://ex.com/fb')")
    con.execute("UPDATE articles SET image = 'https://ex.com/photo.jpg' WHERE lien = 'https://ex.com/fb'")
    con.commit()
    appels.clear()
    t.CONFIG["facebook_page_token"] = "j"
    t.urllib.request.urlopen = lambda req, timeout=None: (appels.append((req.full_url, req.data.decode())),
                                                         io.BytesIO(b'{"id": "7", "post_id": "42_9"}'))[1]
    try:
        assert t.vers_page(con) == 1
    finally:
        t.urllib.request.urlopen = vrai_urlopen
        t.CONFIG.pop("facebook_page_token")
    envoi = urllib.parse.parse_qs(appels[0][1])
    assert appels[0][0].endswith("/42/photos") and envoi["url"] == ["https://ex.com/photo.jpg"] and "link" not in envoi
    assert envoi["caption"][0].startswith("⚜️ Titre") and envoi["caption"][0].endswith("Source : AS")
    # puis le lien de la source en commentaire de la Page, sous le post
    commentaire = urllib.parse.parse_qs(appels[1][1])
    assert len(appels) == 2 and appels[1][0].endswith("/42_9/comments")
    assert commentaire["message"] == ["🔗 Source : AS\nhttps://ex.com/fb"]
    assert con.execute("SELECT post FROM page_facebook p JOIN articles a ON a.id = p.article_id WHERE a.lien = 'https://ex.com/fb'").fetchone()[0] == "42_9"
    # conférence de l'entraîneur : la presse ne va pas sur la Page ; la page du club part d'un coup, en français, l'anglais en commentaire
    _club = "https://www.realmadrid.com/es-ES/noticias/futbol/primer-equipo/ruedas-de-prensa/mourinho-20-11-2026"
    g.enregistrer([{"id": 1, "section": "actus", "titre": "مورينيو عن فينيسيوس", "texte": "ن", "tweets": ["🎙️ مؤتمر مورينيو | «أ»\n\n(ماركا)"],
                    "titres_fb": {"fr": "Mourinho sur Vinicius", "en": "Mourinho on Vinicius", "es": "Mourinho sobre Vinicius"}},
                   {"id": 2, "section": "actus", "titre": "مؤتمر مورينيو قبل سيلتا", "texte": "ن", "tweets": ["🎙️ مؤتمر مورينيو | «ب»\n\n(ريال مدريد)"],
                    "titres_fb": {"fr": "La conférence de Mourinho avant le Celta", "en": "Mourinho's press conference before Celta",
                                  "es": "La rueda de prensa de Mourinho", "conf_fr": "▪️ Vinicius : « Il jouera »", "conf_en": "▪️ Vinicius: \"He will play\""}}],
                  [{"lien": "https://www.marca.com/mou-vini", "titre": "Mou: Vinicius", "auteur": "", "source": "Marca", "pays": "es", "type": "conference"},
                   {"lien": _club, "titre": "Mourinho", "auteur": "", "source": "Real Madrid CF (site officiel)", "pays": "es", "type": "conference", "officiel": True}], db)
    appels.clear()
    t.CONFIG["facebook_page_token"] = "j"
    t.urllib.request.urlopen = lambda req, timeout=None: (appels.append((req.full_url, req.data.decode())),
                                                         io.BytesIO(b'{"id": "8", "post_id": "42_10"}'))[1]
    try:
        assert t.vers_page(con) == 1
    finally:
        t.urllib.request.urlopen = vrai_urlopen
        t.CONFIG.pop("facebook_page_token")
    assert con.execute("SELECT post FROM page_facebook p JOIN articles a ON a.id = p.article_id WHERE a.lien = 'https://www.marca.com/mou-vini'").fetchone()[0].startswith("sans : conférence")
    _post = urllib.parse.parse_qs(appels[0][1])
    _texte = (_post.get("caption") or _post.get("message"))[0]
    assert _texte.startswith("🎙️ La conférence de Mourinho avant le Celta\n\n▪️ Vinicius : « Il jouera »") and "🇪🇸" not in _texte and "⚜️" not in _texte
    _en = urllib.parse.parse_qs(appels[1][1])["message"][0]
    assert appels[1][0].endswith("/42_10/comments") and _en.startswith("🇬🇧 Mourinho's press conference before Celta") and '"He will play"' in _en
    con.close()
print("OK threads")

from datetime import datetime
# résumé du jour : heure de Madrid (été / hiver), fenêtre minuit-3 h, articles de la veille seulement, une seule fois par jour
assert t.heure_madrid(datetime(2026, 7, 1, 22)) == datetime(2026, 7, 2, 0) and t.heure_madrid(datetime(2026, 11, 17, 23)) == datetime(2026, 11, 18, 0)
assert t.heure_madrid(datetime(2026, 3, 29, 0, 59)).hour == 1 and t.heure_madrid(datetime(2026, 3, 29, 1)).hour == 3  # passage à l'heure d'été
con = sqlite3.connect(":memory:")
con.row_factory = sqlite3.Row
con.execute("CREATE TABLE articles (date TEXT, section TEXT, mode TEXT, titre TEXT, chapeau TEXT, journal TEXT, auteur TEXT, auteur_ar TEXT)")
con.executemany("INSERT INTO articles VALUES (?, 'actus', 'info', ?, 'c', 'Marca', '', '')",
                [("2026-11-15T22:30:00", "avant-veille"), ("2026-11-16T10:00:00", "veille"), ("2026-11-16T23:05:00", "aujourd'hui")])
prompts, envois = [], []
vrai = (t.appeler_claude, t.typefully_api, t.reglage)
t.appeler_claude = lambda p, *a: (prompts.append(p), '["📌 حصاد ريال مدريد | 16 نوفمبر", "▪️ خبر\\n\\n(ماركا)"]')[1]
t.typefully_api = lambda chemin, corps=None: (envois.append(corps), {"id": 7})[1]
t.reglage = lambda cle: "k"
t.CONFIG["typefully_social_set"] = t.CONFIG.get("typefully_social_set") or 1
try:
    assert t.resume_du_jour(con, datetime(2026, 11, 16, 22)) == 0 and not prompts  # 23 h à Madrid : trop tôt
    assert t.resume_du_jour(con, datetime(2026, 11, 16, 23, 10)) == 1  # 0 h 10 à Madrid : résumé du 16
    assert t.resume_du_jour(con, datetime(2026, 11, 16, 23, 20)) == 0 and len(envois) == 1  # une seule fois
finally:
    t.appeler_claude, t.typefully_api, t.reglage = vrai
assert "veille" in prompts[0] and "avant-veille" not in prompts[0] and "aujourd'hui" not in prompts[0]
assert envois[0]["publish_at"] == "now" and envois[0]["platforms"]["x"]["posts"][1]["text"].endswith("2/2")
con.close()
print("OK résumé du jour")

# unes Marca / AS : une publication par journal sur X et Facebook, une sans le Real ignorée, rien en double au passage suivant
con = sqlite3.connect(":memory:")
con.row_factory = sqlite3.Row
lus, x, fb = [], [], []
vrai = (t.appeler_claude, t.typefully_api, t.typefully_image, t.telecharger_image, t.reglage, t.urllib.request.urlopen, t.lire_page)
telecharges = []
t.telecharger_image = lambda url, nom: (telecharges.append(url), (f"{nom}.jpg", b"img"))[1]
t.lire_page = lambda url: (_ for _ in ()).throw(OSError("frontpages injoignable"))  # repli sur kiosko
t.appeler_claude = lambda p, *a, **k: (lus.append((p, k)), '[{"es": "Hasta Zidane se rinde a Güler", "ar": "حتى زيدان يستسلم لغولر", "fr": "Même Zidane", "en": "Even Zidane"}]'
                                       if "Marca" in p else "[]")[1]
t.typefully_image = lambda nom, contenu: "m1"
t.typefully_api = lambda chemin, corps=None: (x.append(corps), {"id": 9})[1]
t.reglage = lambda cle: "k"
t.urllib.request.urlopen = lambda req, timeout=None: (fb.append((req.full_url, req.data.decode("utf-8", "replace"))), io.BytesIO(b'{"id": "5"}'))[1]
try:
    assert t.unes_du_jour(con, datetime(2026, 11, 17, 12)) == 0 and not lus  # 13 h à Madrid : hors fenêtre
    assert t.unes_du_jour(con, datetime(2026, 11, 16, 21, 50)) == 0 and not lus  # 22 h 50 : pas encore
    assert t.unes_du_jour(con, datetime(2026, 11, 16, 22, 10)) == 2  # 23 h 10 le 16 : la une du 17, Marca sur X et Facebook, AS sans le Real
    assert t.unes_du_jour(con, datetime(2026, 11, 16, 23, 40)) == 0 and len(lus) == 2  # rien en double, chaque une lue une fois
finally:
    t.appeler_claude, t.typefully_api, t.typefully_image, t.telecharger_image, t.reglage, t.urllib.request.urlopen, t.lire_page = vrai
assert all(k == {"outils": "Read"} for _, k in lus) and "2026-11-17" in lus[0][0]
assert telecharges[0] == "https://img.kiosko.net/2026/11/17/es/marca.750.jpg"  # frontpages injoignable : kiosko
post = x[0]["platforms"]["x"]["posts"][0]
assert len(x) == 1 and post["media_ids"] == ["m1"] and post["text"].startswith("📰 غلاف ماركا | الثلاثاء 17 نوفمبر") and "▪️ حتى زيدان" in post["text"]
# titres trop longs pour un tweet : réponses en thread, aucun titre perdu, image et hashtag sur le 1er seulement
_tw = t.tweets_une("📰 غلاف ماركا | الجمعة 20 نوفمبر\n\n", [f"▪️ {'ب' * 120} {i}" for i in range(4)])
assert len(_tw) == 3 and all(t.longueur(x) <= t.LIMITE for x in _tw) and sum(x.count("▪️") for x in _tw) == 4
assert _tw[0].startswith("📰") and _tw[0].endswith("#ريال_مدريد") and not _tw[1].endswith("#ريال_مدريد")
assert t.tweets_une("E\n\n", ["▪️ a"]) == ["E\n\n▪️ a\n\n#ريال_مدريد"]
assert len(fb) == 1 and fb[0][0].endswith("/photos") and 'name="source"; filename="une-marca.jpg"' in fb[0][1]  # image envoyée en fichier
assert "📰 Marca · la une du 17 novembre" in fb[0][1] and "🇪🇸 Hasta Zidane" in fb[0][1]
con.close()
# frontpages.com : grande image de la une du jour, adresse cachée en base64 ; encore la une de la veille : None
_fp = '<img id="giornale-img" alt="Cover Marca 20/11/2026"><script>var u=atob(\'L2cvMjAyNi8xMS8xOS9tYXJjYS0yMzM3MDl5MXc1eHQxLndlYnA=\');</script>'
vrai = t.lire_page
t.lire_page = lambda url: _fp
from datetime import date
try:
    assert t.une_frontpages("marca", date(2026, 11, 20)) == "https://www.frontpages.com/g/2026/11/19/marca-233709y1w5xt1.webp"
    assert t.une_frontpages("marca", date(2026, 11, 21)) is None
finally:
    t.lire_page = vrai
from datetime import date
from PIL import Image as _Im
_t = io.BytesIO(); _Im.new("RGB", (4, 4)).save(_t, "WEBP")
_nom, _oct = t.en_jpeg(("une-marca.webp", _t.getvalue()))
assert _nom == "une-marca.jpg" and _oct[:2] == b"\xff\xd8"
print("OK unes Marca et AS")

# économies de Claude : filtre gratuit, tri sur titre, textes coupés, thread écrit avec l'article
assert g.est_pratique({"titre": "Valencia vs Real Madrid: a qué hora juega y dónde ver", "lien": "https://x"})
assert g.est_pratique({"titre": "Match", "lien": "https://www.abc.es/deportes/real-madrid/ver-television-online-real-madrid"})
assert not g.est_pratique({"titre": "Alineación probable del Real Madrid ante el Valencia", "lien": "https://www.marca.com/a.html"})
lot = [{"titre": f"T{i}", "resume": "r", "source": "Marca", "lien": f"https://m/{i}"} for i in range(3)]
g.appeler_claude = lambda prompt, *a: '[{"id": 1, "type": "opinion"}, {"id": 3, "type": "info"}, {"id": 9, "type": "info"}]'
gardes, ecartes = g.trier(lot)
assert [it["titre"] for it in gardes] == ["T0", "T2"] and gardes[0]["type"] == "opinion" and ecartes == [lot[1]]
g.appeler_claude = lambda prompt, *a: "désolé"
assert g.trier(lot) is None
long = {"lien": "http://localhost:1/x", "texte_flux": "د" * 6500 + "و" * 4000 + "ف" * 1500}
assert len(g.texte_complet({**long, "type": "info"})) == 4000
t_op = g.texte_complet({**long, "type": "opinion"})
assert t_op.startswith("د" * 6500) and t_op.endswith("ف" * 1500) and "و" not in t_op
with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "a.db"
    g.enregistrer([{"id": 1, "section": "actus", "titre": "ع", "texte": "ن", "auteur_ar": "كاتب", "tweets": ["خبر"]}],
                  [{"lien": "https://ex.com/w", "titre": "T", "auteur": "X", "source": "AS", "pays": "es"}], db)
    con = sqlite3.connect(db)
    (tw,) = con.execute("SELECT tweets FROM threads").fetchone()
    assert "خبر" in tw and "https://ex.com/w" in tw and "كاتب | AS" in tw
    con.close()
print("OK économies Claude")
# même info, sources en langues différentes : titre arabe quasi identique -> écarté (cas réel : fils de Casillas, 0,91)
with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "a.db"
    src = [{"lien": f"https://ex.com/{k}", "titre": "T", "auteur": "", "source": "AS", "pays": "es"} for k in "abc"]
    assert g.enregistrer([{"id": 1, "titre": "ابنا إيكر كاسياس يغادران ريال مدريد إلى ليغانيس", "texte": "ن"},
                          {"id": 2, "titre": "ابنا إيكر كاسياس يغادران أكاديمية ريال مدريد إلى ليغانيس", "texte": "ن"}], src, db) == 1
    assert g.enregistrer([{"id": 3, "titre": "ريال مدريد يجدد عقد المدافع الشاب أليخاندرو كاستانيو حتى 2030", "texte": "ن"}], src, db) == 1
    # même tournure, autre joueur : pas un doublon (Courtois écarté à tort le 20 nov., 83 % avec Tchouaméni)
    src2 = [{"lien": f"https://ex.com/p{k}", "titre": "T", "auteur": "", "source": "AS", "pays": "es"} for k in "ab"]
    assert g.enregistrer([{"id": 1, "titre": "تشواميني يمدد عقده مع ريال مدريد حتى صيف 2032", "texte": "ن"},
                          {"id": 2, "titre": "كورتوا يمدّد عقده مع ريال مدريد حتى 2028", "texte": "ن"}], src2, db) == 2
print("OK doublons par titre arabe")
# faits durables : 2 au plus par article, même fait venu d'un autre journal ignoré, trop court ignoré
with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "a.db"
    src = [{"lien": f"https://ex.com/f{k}", "titre": "T", "auteur": "", "source": "AS", "pays": "es"} for k in "ab"]
    fait = "Celta 0-2 Real Madrid le 21 novembre 2026, buts de Mbappé et Güler"
    g.enregistrer([{"id": 1, "titre": "ع", "texte": "ن", "faits": [fait, "Mbappé absent trois semaines (ischio-jambiers)", "Un troisième fait de trop ici"]},
                   {"id": 2, "titre": "خ", "texte": "ن", "faits": [fait.replace("le 21", "ce 21"), "trop court"]}], src, db)
    con = sqlite3.connect(db)
    assert [f for (f,) in con.execute("SELECT fait FROM faits ORDER BY id")] == [fait, "Mbappé absent trois semaines (ischio-jambiers)"]
    con.close()
print("OK faits durables")
# image principale de l'article source (og:image), affichée sur le site local, repli sur la couverture
p = g.Paragraphes()
p.feed('<head><meta property="og:image" content="/img/une.jpg"><meta name="twitter:image" content="/autre.jpg"></head><p>x</p>')
assert p.image == "/img/une.jpg"
# galerie d'une séance d'entraînement du club : photos agrandies, la principale en tête, sans doublon, plafond de config.json
g.threads.CONFIG["max_images_tweet"] = 4
p = g.Paragraphes()
r = "https://assets.realmadrid.com/is/image/realmadrid/"
p.feed("".join(f'<img class="rm-gallery__img x" src="{r}{n}?$Desktop$&amp;wid=148">' for n in ("12_DB1", "13_DB2", "13_DB2", "14_DB3", "15_DB4", "16_DB5")))
assert p.galerie == [f"{r}{n}?wid=1200" for n in ("12_DB1", "13_DB2", "14_DB3", "15_DB4", "16_DB5")]
assert g.threads.images_thread({"image": f"{r}ND_ENTRENAMIENTO_DB2?wid=1200", "galerie": json.dumps(p.galerie)}) == \
    [f"{r}ND_ENTRENAMIENTO_DB2?wid=1200", f"{r}12_DB1?wid=1200", f"{r}14_DB3?wid=1200", f"{r}15_DB4?wid=1200"]
assert g.threads.images_thread({"image": "https://as.com/une.jpg", "galerie": None}) == ["https://as.com/une.jpg"]
g.threads.CONFIG["max_images_tweet"] = 20
assert len(g.threads.images_thread({"image": f"{r}ND_ENTRENAMIENTO_DB2?wid=1200", "galerie": json.dumps(p.galerie)})) == 5
img = g.image_article({"image": "https://ex.com/img/une.jpg"}, "couv", "c.png")
assert 'src="https://ex.com/img/une.jpg"' in img and "couvertures/c.png" in img and 'referrerpolicy="no-referrer"' in img
assert 'src="couvertures/c.png"' in g.image_article({"image": ""}, "couv", "c.png") and g.image_article({}, "couv", None) == ""
print("OK image principale")
# fiches joueurs : liens DataMB du joueur (s'il a une page) et du club
assert "K_Mbappe_Striker_stats" in g.liens_stats("mbappe") and "Real_Madrid_Team_stats" in g.liens_stats("mbappe")
assert "Real_Madrid_Team_stats" in g.liens_stats("lunin") and "إحصاءات اللاعب" not in g.liens_stats("lunin")
print("OK liens DataMB")
# gardés d'office même si le tri les oublie : rubrique d'opinion, composition probable Marca/AS
g.appeler_claude = lambda prompt, *a: "[]"
office = [{"titre": "Alineaciones probables del Valencia - Real Madrid", "resume": "", "source": "Marca - Real Madrid", "lien": "a"},
          {"titre": "Viejos rockeros", "resume": "", "source": "AS - Opinion", "lien": "b", "opinion": True},
          {"titre": "Predicted lineups", "resume": "", "source": "Managing Madrid", "lien": "c"},
          {"titre": "Comunicado Oficial renovación de Tchouameni", "resume": "", "source": "Real Madrid CF", "lien": "d", "officiel": True}]
gardes, ecartes = g.trier(office)
assert [it["type"] for it in gardes] == ["info", "opinion", "info"] and ecartes == [office[2]]
print("OK gardés d'office")
# conférences de presse : type gardé par le tri, texte lu en entier, mode « conférence » dans le prompt et la base
g.appeler_claude = lambda prompt, *a: '[{"id": 1, "type": "conference"}]'
conf = [{"titre": "Rueda de prensa de Mourinho", "resume": "", "source": "AS - Futbol", "lien": "https://as.com/c", "auteur": ""}]
assert g.trier(conf)[0][0]["type"] == "conference"
assert len(g.texte_complet({"lien": "http://localhost:1/x", "texte_flux": "م" * 13000, "type": "conference"})) == 12000
conf[0]["texte"] = "ن"
assert "Mode : conférence" in g.construire_prompt(conf)
with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "a.db"
    g.enregistrer([{"id": 1, "section": "actus", "titre": "مورينيو", "texte": "ن"}], conf, db)
    con = sqlite3.connect(db)
    assert con.execute("SELECT mode FROM articles").fetchone() == ("conference",)
    con.close()
print("OK conférences")
# boutons X / Facebook : titres FR/EN/ES enregistrés, post Facebook et thread dans la page article
with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "a.db"
    g.enregistrer([{"id": 1, "section": "debats", "titre": "ع", "texte": "ن", "tweets": ["فكرة"],
                    "titres_fb": {"fr": "Mbappé <brille>", "en": "Mbappé shines", "es": "Mbappé brilla", "it": "x"}}],
                  [{"lien": "https://as.com/fb", "titre": "T", "auteur": "", "source": "AS", "pays": "es"}], db)
    con = g.connexion(db)
    a = con.execute("SELECT * FROM articles").fetchone()
    con.close()
    assert json.loads(a["titres_fb"]) == {"fr": "Mbappé <brille>", "en": "Mbappé shines", "es": "Mbappé brilla"}
    g.THREADS.clear(); g.THREADS[a["id"]] = ["فكرة\n\n1/2", "📰 AS\n🔗 المصدر: https://as.com/fb\n\n2/2"]
    p = g.page_article(a, [a])
    assert "⚜️ Mbappé &lt;brille&gt;\n🇨🇦 Mbappé shines\n🇪🇸 Mbappé brilla\n\nhttps://as.com/fb" in p
    assert 'data-ouvre="x-1"' in p and "ثريد (2)" in p and p.count('class="copier"') == 3 and 'data-pub="fb-1"' in p
    assert "https://x.com/intent/post?text=%D9%81%D9%83%D8%B1%D8%A9%0A%0A1/2" in p  # 1er tweet seulement
    g.THREADS.clear()
    assert 'data-ouvre="x-1"' not in g.page_article(a, [a])  # pas de thread : seulement Facebook
print("OK boutons X et Facebook")
# Typefully : brouillon X avec couverture sur le 1er tweet, threads d'avant l'ajout ignorés, échec réseau repris
with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "a.db"
    g.enregistrer([{"id": 1, "section": "debats", "titre": "قديم", "texte": "ن", "tweets": ["قديم"]}],
                  [{"lien": "https://as.com/1", "titre": "T", "auteur": "", "source": "AS", "pays": "es"}], db)
    con = g.connexion(db)
    con.execute("ALTER TABLE threads DROP COLUMN typefully")  # base d'avant l'ajout de Typefully
    t.connexion_threads(con)  # ajoute la colonne : le thread existant est marqué « avant »
    g.enregistrer([{"id": 1, "section": "debats", "titre": "جديد", "texte": "ن", "tweets": ["فكرة (آس)"]}],
                  [{"lien": "https://as.com/2", "titre": "T", "auteur": "", "source": "AS", "pays": "es"}], db)
    (Path(tmp) / "c.png").write_bytes(b"png")
    appels = []
    con.execute("UPDATE articles SET image = 'https://as.com/une.jpg' WHERE lien = 'https://as.com/2'")
    t.typefully_image = lambda nom, contenu: nom
    t.telecharger_image = lambda url, i: (f"article-{i}.jpg", b"jpg")
    t.typefully_api = lambda chemin, corps=None: appels.append((chemin, corps)) or {"id": 77}
    t.reglage = lambda cle: "cle" if cle == "typefully_api_key" else None
    t.CONFIG["typefully_social_set"] = 1
    t.CONFIG["typefully_publish_at"] = "next-free-slot"
    assert t.vers_typefully(con, {2: "c.png"}, Path(tmp)) == 1 and t.vers_typefully(con, {}, Path(tmp)) == 0
    (chemin, corps), = appels
    posts = corps["platforms"]["x"]["posts"]
    assert corps["publish_at"] == "next-free-slot"  # file d'attente : publié seul au prochain créneau
    assert chemin == "drafts" and corps["draft_title"] == "جديد" and posts[0]["media_ids"] == ["article-2-0.jpg"] and len(posts) == 2
    assert dict(con.execute("SELECT article_id, typefully FROM threads").fetchall()) == {1: "avant", 2: "77"}
    # photo de l'article refusée (pas une image, trop lourde, 403) : la couverture à la place
    con.execute("UPDATE threads SET typefully = NULL WHERE article_id = 2")
    def refuse(url, i):
        raise ValueError("pas une image")
    t.telecharger_image, appels[:] = refuse, []
    faites = []  # article avec image : pas de couverture d'avance, elle est faite à la demande, sans ménage
    vrai_gen, couvertures.generer_couvertures = couvertures.generer_couvertures, (
        lambda arts, dossier, menage=True: faites.append(menage) or {arts[0]["id"]: "c.png"})
    try:
        assert t.vers_typefully(con, {}, Path(tmp)) == 1 and appels[0][1]["platforms"]["x"]["posts"][0]["media_ids"] == ["c.png"]
    finally:
        couvertures.generer_couvertures = vrai_gen
    assert faites == [False]
    con.execute("UPDATE threads SET typefully = NULL WHERE article_id = 2")
    def coupe(*a, **k):
        raise OSError("réseau coupé")
    t.typefully_api = coupe
    assert t.vers_typefully(con, {}, Path(tmp)) == 0
    assert con.execute("SELECT typefully FROM threads WHERE article_id = 2").fetchone()[0] is None
    # une nouvelle passe avant les opinions en attente et part tout de suite ; l'opinion garde la file
    t.typefully_api, appels[:] = (lambda chemin, corps=None: appels.append(corps) or {"id": len(appels)}), []
    t.CONFIG["typefully_publish_at_actus"] = "now"
    con.commit()  # libère la base pour enregistrer
    g.enregistrer([{"id": 1, "section": "actus", "titre": "خبر عاجل", "texte": "ن", "tweets": ["خبر (آس)"]}],
                  [{"lien": "https://as.com/3", "titre": "T3", "auteur": "", "source": "AS", "pays": "es", "type": "info"}], db)
    try:
        assert t.vers_typefully(con, {2: "c.png", 3: "c.png"}, Path(tmp)) == 2
    finally:
        t.CONFIG.pop("typefully_publish_at_actus")
    assert [c["draft_title"] for c in appels] == ["خبر عاجل", "جديد"] and appels[1]["publish_at"] == "next-free-slot"
    # publiée tout de suite, sans le tweet de crédit qui contient le lien (X refuse la publication immédiate avec lien)
    assert appels[0]["publish_at"] == "now" and [p["text"] for p in appels[0]["platforms"]["x"]["posts"]] == ["خبر (آس)"]
    assert t.sans_tweet_de_lien(["أ\n\n1/3", "ب\n\n2/3", "📰 AS\n🔗 المصدر: https://as.com/1\n\n3/3"]) == (["أ\n\n1/2", "ب\n\n2/2"], "now")
    from datetime import datetime as dt, timezone as tz
    tw, quand = t.sans_tweet_de_lien(["انظر https://x.com/a\n\n1/2", "📰 AS\n🔗 https://as.com/1\n\n2/2"])
    assert tw[0].startswith("انظر") and 60 < (dt.fromisoformat(quand) - dt.now(tz.utc)).total_seconds() <= 120  # lien ailleurs : programmé
    # un thread refusé (403) ne bloque plus les suivants, et la raison donnée par Typefully est affichée
    import contextlib
    import urllib.error
    con.execute("UPDATE threads SET typefully = NULL WHERE article_id = 2")
    con.commit()
    g.enregistrer([{"id": 1, "section": "debats", "titre": "ثالث", "texte": "ن", "tweets": ["فكرة ثالثة (آس)"]}],
                  [{"lien": "https://as.com/9", "titre": "T9", "auteur": "", "source": "AS", "pays": "es"}], db)

    def refuse_le_premier(chemin, corps=None):
        if corps and corps.get("draft_title") == "جديد":
            raise urllib.error.HTTPError("https://api", 403, "Forbidden", {}, io.BytesIO(b'{"detail": "raison du refus"}'))
        return {"id": 88}
    t.typefully_api, sortie = refuse_le_premier, io.StringIO()
    with contextlib.redirect_stdout(sortie):
        assert t.vers_typefully(con, {2: "c.png", 4: "c.png"}, Path(tmp)) == 1
    assert "raison du refus" in sortie.getvalue() and "article 2" in sortie.getvalue()
    assert con.execute("SELECT typefully FROM threads WHERE article_id = 2").fetchone()[0] is None
    # plafond de publications immédiates par heure : la nouvelle attend le passage suivant, sans être bloquée
    con.execute("UPDATE threads SET typefully = '88' WHERE article_id = 2")
    con.commit()
    g.enregistrer([{"id": 1, "section": "actus", "titre": "خبر ثان", "texte": "ن", "tweets": ["إصابة جديدة في التدريب (آس)"]}],
                  [{"lien": "https://as.com/10", "titre": "T10", "auteur": "", "source": "AS", "pays": "es", "type": "info"}], db)
    aid = con.execute("SELECT id FROM articles WHERE lien = 'https://as.com/10'").fetchone()[0]
    t.typefully_api, appels[:] = (lambda chemin, corps=None: appels.append(corps) or {"id": 99}), []
    t.CONFIG.update(typefully_publish_at_actus="now", max_publications_heure=1)
    try:
        assert t.vers_typefully(con, {aid: "c.png"}, Path(tmp)) == 0 and not appels  # une nouvelle est déjà partie il y a moins d'une heure
        # contrôle en échec : simple brouillon, sans date de publication, motif en tête du titre
        t.CONFIG["max_publications_heure"] = 8
        con.execute("UPDATE threads SET tweets = ? WHERE article_id = ?", (json.dumps(["إصابة جديدة في التدريب! (آس)", "ريتويت"]), aid))
        assert t.vers_typefully(con, {aid: "c.png"}, Path(tmp)) == 1
    finally:
        t.CONFIG.pop("typefully_publish_at_actus")
        t.CONFIG.pop("max_publications_heure")
    assert "publish_at" not in appels[0] and appels[0]["draft_title"].startswith("⛔ appel à l'engagement")
    assert appels[0]["platforms"]["x"]["posts"][0]["text"] == "إصابة جديدة في التدريب! (آس)"  # « ! » accepté depuis le 21 nov.
    assert con.execute("SELECT statut FROM threads WHERE article_id = ?", (aid,)).fetchone()[0].startswith("bloqué")
    con.close()
print("OK Typefully")

# contrôles avant envoi : source, appel à l'engagement, doublon (les threads bloqués ne comptent pas)
con = sqlite3.connect(":memory:")
t.connexion_threads(con)
def envoye(i, accroche, statut="immédiat"):
    con.execute("INSERT INTO threads (article_id, tweets, statut, date, typefully, envoye) VALUES (?, ?, ?, ?, '1', ?)",
                (i, json.dumps([f"{accroche}\n\n(ماركا)"]), statut, *[t.maintenant().isoformat(timespec="seconds")] * 2))
assert t.controler_thread(con, 1, ["📰 خبر | مبابي يعود إلى التدريبات\n\n(ماركا)"]) == []
assert t.controler_thread(con, 1, ["مبابي يعود إلى التدريبات"]) == ["source absente du 1er tweet"]
assert t.controler_thread(con, 1, ["📰 خبر | زلزال في برنابيو!\n\n(ماركا)"]) == []  # ton libre depuis le 21 nov.
assert t.controler_thread(con, 1, ["📰 خبر | مبابي يعود\n\n(ماركا)", "ريتويت"]) == ["appel à l'engagement"]
envoye(10, "📰 خبر | مبابي يعود إلى التدريبات الجماعية مع الفريق")
envoye(11, "📰 خبر | كورتوا يغيب عن مباراة السبت بسبب الإصابة", "bloqué : test")
meme_nouvelle = t.meme_nouvelle
t.meme_nouvelle = lambda ancien, nouveau: True  # Claude confirme le doublon
assert t.controler_thread(con, 12, ["🚨 عاجل | مبابي يعود إلى التدريبات الجماعية مع الفريق\n\n(آس)"]) == ["doublon du thread de l'article 10"]
t.meme_nouvelle = lambda ancien, nouveau: False  # Claude y voit un fait nouveau (Nadal élu à 99,5 % le 21 nov.)
assert t.controler_thread(con, 12, ["🚨 عاجل | مبابي يعود إلى التدريبات الجماعية مع الفريق\n\n(آس)"]) == []
t.meme_nouvelle = meme_nouvelle
appeler = t.appeler_claude
for reponse, attendu in (("NOUVEAU", False), ("DOUBLON", True), (t.ErreurClaude("quota"), True)):
    def faux(*a, r=reponse):
        if isinstance(r, Exception):
            raise r
        return r
    t.appeler_claude = faux
    assert t.meme_nouvelle("أ", "ب") is attendu, reponse
t.appeler_claude = appeler
t.meme_nouvelle = lambda ancien, nouveau: True
assert t.controler_thread(con, 12, ["📰 خبر | كورتوا يغيب عن مباراة السبت بسبب الإصابة\n\n(آس)"]) == []  # le bloqué ne compte pas
assert t.controler_thread(con, 12, ["✅ رسميًا | مبابي يعود إلى التدريبات الجماعية مع الفريق\n\n(ريال مدريد)"], officiel=True) == []  # confirmation du club
assert t.est_officiel({"lien": "https://www.realmadrid.com/es-ES/noticias/club/comunicados/x"}) and not t.est_officiel({"lien": "https://www.marca.com/x"})
# faux doublons du 19 nov. : autre joueur, ou mêmes lettres sans les mêmes mots
assert not t.proche(t.accroche("🔄 ميركاتو | تشواميني يمدد عقده مع ريال مدريد حتى 2032"), t.accroche("🔄 ميركاتو | غولر يمدد عقده مع ريال مدريد حتى 2032"))
assert not t.proche(t.accroche("🔥 نقاش | هل أخطأ فينيسيوس حين اعترف من البرازيل بأنه لم يعتنِ بنفسه؟"), t.accroche("🔥 نقاش | هل فينيسيوس أسعد مع البرازيل منه في مدريد؟"))
assert not t.proche(t.normaliser_titre("Tchouaméni prolonge au Real Madrid jusqu'en 2032"), t.normaliser_titre("Güler prolonge au Real Madrid jusqu'en 2032"))
assert t.proche(t.accroche("📰 خبر | زيدان يؤكد غياب مبابي عن مباراة إيطاليا"), t.accroche("📰 خبر | زيدان: مبابي يغيب عن مباراة إيطاليا"))
assert t.proche(t.accroche("ريال مدريد يراقب المدافع البرازيلي فيتاو لاعب مينيرو"), t.accroche("ريال مدريد يتابع المدافع البرازيلي فيتاو لاعب مينيرو"))
for i, sujet in ((20, "فالفيردي"), (21, "رودريغو"), (22, "تشواميني")):
    envoye(i, f"🚨 عاجل | إصابة {sujet} في الركبة")
assert t.controler_thread(con, 23, ["🚨 عاجل | غولر يمدد عقده حتى 2031\n\n(آس)"]) == []  # plus de plafond de 🚨
con.close()
print("OK contrôles avant envoi")

# conférence : un seul thread par personne sur 6 h (X interdit les réponses par l API)
assert t.orateur("🎙️ مؤتمر مورينيو | «نص»") == t.orateur("🗣️ مورينيو | «نص آخر»") == "مورينيو" and t.orateur("بلا تسمية") == ""
con = sqlite3.connect(":memory:")
con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, mode TEXT)")
con.execute("CREATE TABLE liens_x (typefully TEXT PRIMARY KEY, url TEXT, date TEXT)")
t.connexion_threads(con)
from datetime import timedelta
_m = lambda h: (t.maintenant() - timedelta(hours=h)).isoformat(timespec="seconds")
for i, mode, tw, st, h in ((1, "conference", "🎙️ مؤتمر مورينيو | «أ»", "immédiat", 1), (2, "conference", "🗣️ مورينيو | «ب»", "immédiat", 0.5),
                           (3, "conference", "🗣️ روديغر | «ج»", "immédiat", 1), (4, "conference", "🗣️ فالفيردي | «د»", "immédiat", 8),
                           (5, "conference", "🗣️ كورتوا | «هـ»", "bloqué : test", 1)):
    con.execute("INSERT INTO articles VALUES (?, ?)", (i, mode))
    con.execute("INSERT INTO threads (article_id, tweets, statut, date, typefully, envoye) VALUES (?, ?, ?, ?, ?, ?)",
                (i, json.dumps([tw]), st, _m(h), str(100 + i), _m(h)))
assert t.conference_publiee(con, 9, "🗣️ مورينيو | «جديد»") and t.conference_publiee(con, 9, "🎙️ مؤتمر روديغر | «جديد»")
assert not t.conference_publiee(con, 9, "🗣️ فالفيردي | «جديد»")  # il y a 8 h : nouveau thread
assert not t.conference_publiee(con, 9, "🗣️ كورتوا | «جديد»")  # thread bloqué : ne compte pas
assert not t.conference_publiee(con, 9, "📰 خبر | بلا متحدث")
con.close()
# conférence de l'entraîneur au tri : Marca/AS gardés d'office, les autres journaux écartés
_vrai = g.appeler_claude
g.appeler_claude = lambda *a: '[{"id": 2, "type": "conference"}, {"id": 3, "type": "conference"}, {"id": 4, "type": "info"}]'
try:
    _g, _e = g.trier([{"source": "Marca - Real Madrid", "titre": "Mourinho: \"Aquí no hay privilegios\"", "resume": ""},
                      {"source": "El Mundo - Fútbol", "titre": "Mourinho, sobre Vinicius", "resume": ""},
                      {"source": "Relevo - Fútbol", "titre": "Rüdiger: \"Estamos bien\"", "resume": ""},
                      {"source": "AS - Futbol", "titre": "Courtois renueva", "resume": ""}])
finally:
    g.appeler_claude = _vrai
assert [x["source"] for x in _g] == ["Marca - Real Madrid", "Relevo - Fútbol", "AS - Futbol"] and _e[0]["source"] == "El Mundo - Fútbol"
print("OK un seul thread par conférence")

# retrait : suppression du post Facebook enregistré, adresse du thread X à supprimer à la main
con = sqlite3.connect(":memory:")
con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY)")
t.connexion_page(con)
con.execute("INSERT INTO page_facebook VALUES (5, 'd', '42_7')")
t.connexion_threads(con)
con.execute("INSERT INTO threads (article_id, tweets, statut, date, typefully) VALUES (5, '[]', 'immédiat', 'd', '88')")
supprimes = []
vrai = (t.urllib.request.urlopen, t.typefully_api, t.reglage)
t.urllib.request.urlopen = lambda req, timeout=None: (supprimes.append((req.get_method(), req.full_url)), io.BytesIO(b'{"success": true}'))[1]
t.typefully_api = lambda chemin, corps=None: {"x_published_url": "https://x.com/ElMadridistAlaa/status/1"} if chemin == "drafts/88" else {}
t.reglage = lambda cle: "k"
try:
    lignes = t.retirer(con, 5)
    vide = t.retirer(con, 6)
finally:
    t.urllib.request.urlopen, t.typefully_api, t.reglage = vrai
assert supprimes == [("DELETE", t.GRAPH + "42_7?access_token=k")] and "https://x.com/ElMadridistAlaa/status/1" in lignes[1]
assert vide[0].startswith("Facebook : aucun post") and vide[1] == "X : aucun thread connu pour cet article"
con.close()
print("OK retrait")

# alertes : signalée au 3e échec de suite, une seule fois ; remise à zéro après un succès, de nouveau signalable ensuite
con = sqlite3.connect(":memory:")
con.row_factory = sqlite3.Row
for _ in range(2):
    t.noter(con, "Page Facebook", "HTTP Error 400 : Session has expired")
assert t.alertes(con) == ""
t.noter(con, "Page Facebook", "HTTP Error 400 : Session has expired")
alerte = t.alertes(con)
assert "**Page Facebook** : en échec depuis 3 passages" in alerte and "Session has expired" in alerte
t.noter(con, "Page Facebook", "encore")
assert t.alertes(con) == ""  # déjà signalée
t.noter(con, "Page Facebook")
assert con.execute("SELECT count(*) FROM echecs").fetchone()[0] == 0
for _ in range(3):
    t.noter(con, "Page Facebook", "de nouveau")
assert "de nouveau" in t.alertes(con)
# image de plus de 5 Mo (PNG de COPE) : recompressée en JPEG au lieu d'être refusée
import os as _os
from PIL import Image as _Image
_tampon = io.BytesIO()
_Image.frombytes("RGB", (1600, 1200), _os.urandom(1600 * 1200 * 3)).save(_tampon, "PNG")
assert len(_tampon.getvalue()) > 5_000_000
class _Rep(io.BytesIO):
    headers = type("H", (), {"get_content_type": lambda self: "image/png"})()
    def __enter__(self): return self
    def __exit__(self, *a): pass
_vrai_open = t.urllib.request.urlopen
t.urllib.request.urlopen = lambda *a, **k: _Rep(_tampon.getvalue())
_nom, _octets = TELECHARGER("https://www.cope.es/x.png", 1)
t.urllib.request.urlopen = _vrai_open
assert _nom == "article-1.jpg" and len(_octets) <= 5_000_000 and _octets[:2] == b"\xff\xd8"
print("OK image recompressée")
# une de journal pas encore sortie (404) : pas une panne ; autre erreur : comptée
import urllib.error
vrai = (t.telecharger_image, t.reglage, t.lire_page)
t.reglage = lambda cle: "k"
t.lire_page = lambda url: ""  # frontpages sans la une : kiosko
for code in (404, 500):
    def refus(url, nom, code=code):
        raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b""))
    t.telecharger_image = refus
    with contextlib.redirect_stdout(io.StringIO()):
        t.unes_du_jour(con, datetime(2026, 11, 16, 23, 30))
t.telecharger_image, t.reglage, t.lire_page = vrai
assert {r[0]: r[1] for r in con.execute("SELECT envoi, n FROM echecs WHERE envoi LIKE 'Une%'")} == {"Une de Marca": 1, "Une de AS": 1}
# santé : projection du quota Typefully à la fin du mois
import sante
vrai = (t.reglage, t.typefully_api, t.graph_lire, sante.maintenant, sante.commun.lire_page, t.telecharger_image)
t.telecharger_image = lambda url, nom: (f"{nom}.webp", b"img")
t.reglage = lambda cle: "k"
t.graph_lire = lambda chemin, **p: {"name": "Peña"}
t.typefully_api = lambda chemin, corps=None: {"publishing_quota": {"used": 450, "remaining": 550}}
sante.maintenant = lambda: datetime(2026, 11, 16, 0)  # 15 jours écoulés : 30 par jour, 900 sur 30 jours
_jour = datetime.now().strftime("%d-%m-%Y")
_bonnes = {"article": '<meta property="og:title" content="Comunicado" />{"datePublished":"2026-11-19T11:36:00.000Z"}',
           "rubrique": f'<a href="/es-ES/noticias/club/comunicados/comunicado-{_jour}">'}
_une = """<img alt="Cover Marca 20/11/2026"><script>atob('L2cvMjAyNi8xMS8xOS9tYXJjYS0yMzM3MDl5MXc1eHQxLndlYnA=')</script>"""
sante.commun.lire_page = lambda url: _une if "frontpages" in url else _bonnes["article" if url.endswith(_jour) else "rubrique"]
try:
    rapport = sante.sante(con)
    sante.commun.lire_page = lambda url: "<html>nouveau site</html>"  # structure changée : plus aucun lien d'article
    casse = sante.pages_club()
    casse_unes = sante.unes_frontpages()
finally:
    t.reglage, t.typefully_api, t.graph_lire, sante.maintenant, sante.commun.lire_page, t.telecharger_image = vrai
assert "✅ Jeton Facebook valide" in rapport and "⚠️ Quota Typefully : 450 publications sur 1000" in rapport and "environ 900" in rapport
assert "**Page Facebook** : 3 passage(s)" in rapport
assert "✅ Pages de Real Madrid CF (site officiel) lisibles" in rapport, rapport
assert casse[0].startswith("- ❌ Pages de **Real Madrid CF (site officiel)**") and "aucun lien d'article" in casse[0], casse
assert "✅ Unes de Marca et AS lisibles sur frontpages.com" in rapport, rapport
assert casse_unes[0].startswith("- ❌ Unes sur frontpages.com : Marca : date de la une introuvable"), casse_unes
con.close()
print("OK alertes et santé")

# tableau de bord Facebook : formats, tranches horaires (heure de Madrid), semaine comparée à la précédente, pagination
import performance
assert performance.format_post("📰 Marca · la une du 17 novembre") == "Une de journal"
assert performance.format_post("⚜️ Titre\n🇨🇦 Title") == "Nouvelle (automatique)" and performance.format_post(None) == "Autre (manuel, /script)"
assert performance.tranche(datetime(2026, 11, 17, 22)) == "soir (18-24 h)" and performance.tranche(datetime(2026, 11, 17, 23)) == "nuit (0-7 h)"
appels = []
def graphe(chemin, **p):
    appels.append((chemin, p.get("after")))
    if chemin.endswith("/insights") and chemin.startswith("42/"):
        return {"data": [{"name": "page_media_view", "values": [{"end_time": "2026-11-09T08:00:00+0000", "value": 10},
                                                                {"end_time": "2026-11-16T08:00:00+0000", "value": 30}]},
                         {"name": "page_follows", "values": [{"end_time": "2026-11-16T08:00:00+0000", "value": 5}]}]}
    if chemin.endswith("/insights"):
        return {"data": [{"values": [{"value": int(chemin.split("_")[1].split("/")[0])}]}]}
    semaine = p["since"] >= int(datetime(2026, 11, 10).replace(tzinfo=__import__("datetime").timezone.utc).timestamp())
    if not semaine:
        return {"data": []}
    if p.get("after") is None:  # 1re page, puis une 2e (curseur)
        return {"data": [{"id": "42_7", "created_time": "2026-11-15T20:00:00+0000", "message": "⚜️ A", "shares": {"count": 2},
                          "reactions": {"summary": {"total_count": 3}}, "comments": {"summary": {"total_count": 1}}}],
                "paging": {"cursors": {"after": "c1"}, "next": "https://graph"}}
    return {"data": [{"id": "42_4", "created_time": "2026-11-16T09:00:00+0000", "message": "📰 AS · la une du 16 novembre"}], "paging": {}}
vrai = (t.reglage, t.graph_lire)
t.reglage = lambda cle: "42" if cle == "facebook_page_id" else "k"
t.graph_lire = graphe
try:
    tb = performance.tableau(datetime(2026, 11, 17, 8))
finally:
    t.reglage, t.graph_lire = vrai
assert ("42/posts", "c1") in appels  # 2e page lue
assert "| Abonnés | 5 |" in tb and "| Publications | 2 | 0 | nouveau |" in tb and "| Vues de la Page | 30 | 10 | +200% |" in tb
assert "| Nouvelle (automatique) | 1 | trop peu de données |" in tb and "- 7 vues, 6 interactions : [⚜️ A]" in tb
print("OK tableau de bord Facebook")

# revue des sources : lignes de config.json prêtes à copier, seulement pour les flux lus avec succès et les retraits réels
import sources
avis = {"retirer": [{"flux": sources.CONFIG["flux"][0]["nom"]}, {"flux": "Inconnu"}]}
ajouts = [({"nom": "Diario AS Opinión", "nom_ar": "آس", "url": "https://as.com/rss", "pays": "ES", "opinion": True}, "✅ 20 entrées, 5 sur le Real"),
          ({"nom": "Mundo Deportivo", "nom_ar": "موندو ديبورتيفو", "url": "https://md.es/rss", "pays": "es"}, "❌ vide")]
r = "\n".join(sources.modifications(avis, ajouts))
assert f"`{sources.CONFIG['flux'][0]['nom']}`" in r and "Inconnu" not in r
assert '{"nom": "Diario AS Opinión", "url": "https://as.com/rss", "pays": "es", "opinion": true}' in r and "md.es" not in r
assert "autorisation" not in r and sources.modifications({}, []) == []
print("OK revue des sources : config prête")

# audit de conformité : échantillon de la semaine (threads envoyés seulement, posts Facebook avec leur forme réelle), tirage stable
import audit
con = sqlite3.connect(":memory:")
con.row_factory = sqlite3.Row
con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, journal TEXT, auteur TEXT, auteur_ar TEXT, section TEXT, texte TEXT,"
            " titres_fb TEXT, image TEXT, lien TEXT)")
maintenant_iso = t.maintenant().isoformat(timespec="seconds")
for i in range(1, 21):
    con.execute("INSERT INTO articles VALUES (?, 'Marca', '', '', 'actus', 'نص', ?, ?, 'https://marca.com/x')",
                (i, json.dumps({"fr": f"Titre {i}"}), "https://img/x.jpg" if i % 2 else ""))
t.connexion_threads(con)
for i in range(1, 19):
    con.execute("INSERT INTO threads (article_id, tweets, statut, date, typefully) VALUES (?, ?, ?, ?, ?)",
                (i, json.dumps([f"تغريدة {i} (ماركا)"]), "bloqué : test" if i == 18 else "immédiat", maintenant_iso, "avant" if i == 17 else "9"))
t.connexion_page(con)
con.execute("DELETE FROM page_facebook")
for i in (19, 20):
    con.execute("INSERT INTO page_facebook VALUES (?, ?, '1_2')", (i, maintenant_iso))
pubs = audit.echantillon(con, "2026-47")
assert pubs == audit.echantillon(con, "2026-47") and len(pubs) == 17  # 15 threads sur 16 envoyés, 2 posts Facebook
assert not any("article 17]" in p or "article 18]" in p for p in pubs)  # ni « avant » ni bloqué
fb = {p.split("article ")[1].split("]")[0]: p for p in pubs if p.startswith("[Facebook")}
assert "[photo de l'article jointe, aucun lien]" in fb["19"] and "https://marca.com/x" not in fb["19"] and "https://marca.com/x" in fb["20"]
vrai = audit.appeler_claude
audit.appeler_claude = lambda p, *a, **k: "Aucun écart sur cet échantillon."
try:
    assert audit.audit(con, "2026-47").endswith("Aucun écart sur cet échantillon.")
finally:
    audit.appeler_claude = vrai
con.close()
print("OK audit de conformité")

# /moderation : commentaires sans réponse de la Page (ni ceux de la Page, ni ceux auxquels elle a déjà répondu)
import moderation
def graphe(chemin, **p):
    if chemin == "42/posts":
        return {"data": [{"id": "42_1", "created_time": "2026-11-17T08:00:00+0000", "message": "⚜️ Titre\n🇨🇦 Title", "permalink_url": "https://fb/1"},
                         {"id": "42_2", "created_time": "2026-11-17T07:00:00+0000", "message": "⚜️ Autre"}]}
    if chemin == "42_1/comments":
        return {"data": [{"id": "c1", "from": {"id": "9", "name": "Karim"}, "message": "Source ?", "created_time": "2026-11-17T09:00:00+0000"},
                         {"id": "c2", "from": {"id": "8"}, "message": "Faux", "created_time": "2026-11-17T09:05:00+0000"},
                         {"id": "c3", "from": {"id": "42"}, "message": "Marca", "parent": {"id": "c1"}, "created_time": "2026-11-17T09:10:00+0000"}]}
    return {"data": [{"id": "c4", "from": {"id": "42"}, "message": "note de la Page", "created_time": "2026-11-17T07:30:00+0000"}]}
vrai = (t.reglage, t.graph_lire)
t.reglage = lambda cle: "42" if cle == "facebook_page_id" else "k"
t.graph_lire = graphe
try:
    attente = moderation.commentaires(2)
finally:
    t.reglage, t.graph_lire = vrai
assert [(p["id"], [c["id"] for c in cs]) for p, cs in attente] == [("42_1", ["c2"])]  # c1 a déjà sa réponse, c3 et c4 viennent de la Page
texte = moderation.afficher(attente)
assert "Post du 2026-11-17 08:00 UTC : ⚜️ Titre" in texte and "- [c2] 2026-11-17 09:05 · lecteur : Faux" in texte
assert moderation.afficher([]) == "Aucun commentaire en attente de réponse."
print("OK /moderation")

# adresses X : relevées une fois publiées (threads envoyés, résumés, unes), une seule fois, ni brouillon bloqué ni une sans le Real
con = sqlite3.connect(":memory:")
t.connexion_threads(con)
maintenant_iso = t.maintenant().isoformat(timespec="seconds")
con.executemany("INSERT INTO threads (article_id, tweets, statut, date, typefully) VALUES (?, '[]', ?, ?, ?)",
                [(1, "immédiat", maintenant_iso, "11"), (2, "bloqué : test", maintenant_iso, "12"), (3, "file", maintenant_iso, "13")])
con.execute("CREATE TABLE resumes (jour TEXT PRIMARY KEY, typefully TEXT)")
con.execute("INSERT INTO resumes VALUES (date('now'), '21')")
con.execute("CREATE TABLE unes (jour TEXT, journal TEXT, titres TEXT, x TEXT, facebook TEXT)")
con.executemany("INSERT INTO unes VALUES (date('now'), ?, '[]', ?, NULL)", [("marca", "31"), ("as", "sans")])
lus = []
def brouillon(chemin, corps=None):
    lus.append(chemin)
    i = chemin.split("/")[1]
    return {"status": "scheduled"} if i == "13" else {"status": "published", "x_published_url": f"https://x.com/a/status/{i}"}
vrai = (t.typefully_api, t.reglage)
t.typefully_api, t.reglage = brouillon, (lambda cle: "k")
t.CONFIG["typefully_social_set"] = t.CONFIG.get("typefully_social_set") or 1
try:
    assert t.liens_x(con) == 3 and sorted(lus) == ["drafts/11", "drafts/13", "drafts/21", "drafts/31"]
    lus.clear()
    assert t.liens_x(con) == 0 and lus == ["drafts/13"]  # seul le thread encore en file est redemandé
finally:
    t.typefully_api, t.reglage = vrai
assert dict(con.execute("SELECT typefully, url FROM liens_x")) == {"11": "https://x.com/a/status/11", "21": "https://x.com/a/status/21",
                                                                    "31": "https://x.com/a/status/31"}
con.close()
print("OK adresses X")

# vidéos verticales : durées par style, lignes dans la zone sûre, mise en valeur *en or* (groupe de mots), arabe, chaque style dessiné
import video
assert video.duree({"style": "cinetique", "texte": "un deux"}) == 1.8 and video.duree({"style": "cinetique", "texte": " ".join(["m"] * 30)}) == 4.0
assert video.duree({"style": "presse", "citations": [{}, {}]}) == 4.8 and video.duree({"style": "compteur", "duree": 2}) == 2.0
lignes, _ = video.lignes_mots("فينيسيوس يعود السبت *لكن هل ما زال* مكانه محفوظا على الجهة اليسرى", 104, "ar")
assert all(sum(w for _, _, w in l) <= video.DROITE - video.GAUCHE for l in lignes)
forts = [m for l in lignes for m, fort, _ in l if fort]
assert forts == ["لكن", "هل", "ما", "زال"] and not any("*" in m for l in lignes for m, _, _ in l)
assert "4-2-3-1" in video.visuel("خطة 4-2-3-1 🔥", "ar") and video.visuel("Vinícius revient 🚨", "fr") == "Vinícius revient"
assert video.nombre("1,06") == (1.06, 2, ",") and video.ecrire_nombre(0.5, 2, ",") == "0,50"
sb = {"langue": "ar", "source": "ماركا", "compte": "@ElMadridistAlaa", "scenes": [
    {"style": "cinetique", "etiquette": "نقاش", "texte": "سؤال *مهم*"}, {"style": "compteur", "valeur": "141", "unite": "دقيقة", "max": 630, "texte": "ل"},
    {"style": "barres", "titre": "ت", "elements": [{"label": "أ", "valeur": "0,75"}, {"label": "ب", "valeur": "1,06"}]},
    {"style": "duel", "joueurs": ["أ", "ب"], "criteres": [{"label": "أهداف", "a": "1", "b": "4"}]},
    {"style": "tactique", "texte": "ن", "joueurs": [{"nom": "أ", "x": .5, "y": .5}], "fleches": [{"de": [.5, .5], "a": [.8, .7]}],
     "zones": [{"x": .6, "y": .6, "l": .2, "h": .2}]},
    {"style": "titres", "cartes": [{"journal": "Marca", "titre": "عنوان"}]}, {"style": "presse", "citations": [{"journal": "AS", "texte": "قول"}]}]}
fonds, durees = {"uni": video.fond_uni()}, [video.duree(sc) for sc in sb["scenes"]]
for i in range(len(sb["scenes"])):
    for tl in (0.05, durees[i] * 0.8):  # pendant la transition et une fois l'animation posée
        assert video.image(sb, fonds, i, tl, durees, zones=True).size == (video.W, video.H)
print("OK vidéos verticales")
# recherche pour /script : accents ignorés, titre prioritaire sur le texte, mots absents écartés
import connaissance
with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "a.db"
    g.enregistrer([{"id": 1, "section": "tactique", "titre": "ع", "texte": "Güler brilla", "personnes": ["guler"]},
                   {"id": 2, "section": "debats", "titre": "Güler et Valencia", "texte": "ن"},
                   {"id": 3, "section": "actus", "titre": "ب", "texte": "Courtois"}],
                  [{"lien": f"https://as.com/{i}", "titre": "T", "auteur": "", "source": "AS", "pays": "es"} for i in range(3)], db)
    trouves = connaissance.chercher(["guler", "valencia"], chemin=db)
    assert [a["titre"] for a in trouves] == ["Güler et Valencia", "ع"]
print("OK recherche /script")

# sitemap Google News (site officiel du Real, sans flux RSS)
import commun
with tempfile.TemporaryDirectory() as d:
    f = Path(d) / "s.xml"
    f.write_text('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
                 '<url><loc>https://www.realmadrid.com/es-ES/noticias/futbol/primer-equipo/cronicas/x</loc><news:news>'
                 '<news:publication_date>2026-11-08T08:13:01.631Z</news:publication_date><news:title>El Madrid golea</news:title>'
                 '</news:news></url></urlset>', encoding="utf-8")
    [e] = commun.lire_sitemap(f.as_uri())
    assert e["title"] == "El Madrid golea" and e["link"].endswith("/cronicas/x")
    assert e["published_parsed"][:5] == (2026, 11, 8, 8, 13), "date en UTC"
print("OK sitemap")
# pages de rubriques du club (sitemap en retard) : liens récents des rubriques voulues, puis titre, date et image de l'article
from datetime import timedelta, timezone
_auj = datetime.now(timezone.utc)
_d = lambda j: (_auj - timedelta(days=j)).strftime("%d-%m-%Y")
_page = (f'<a href="/es-ES/noticias/club/comunicados/comunicado-oficial-{_d(0)}">x</a><a href="/es-ES/noticias/club/comunicados/comunicado-oficial-{_d(0)}">'
         f'<a href="/es-ES/noticias/baloncesto/primer-equipo/cronicas/c-{_d(0)}"><a href="/es-ES/noticias/club/comunicados/vieux-{_d(5)}"><a href="/es-ES/noticias/club">')
assert commun.liens_page(_page, ["/club/comunicados/"]) == [f"https://www.realmadrid.com/es-ES/noticias/club/comunicados/comunicado-oficial-{_d(0)}"]
_e = commun.meta_article("https://x", '<meta property="og:title" content="Comunicado Oficial: renovaci&oacute;n" />'
                         '<meta property="og:image" content="https://a/i.jpg?wid=1200&amp;hei=675" />{"datePublished":"2026-11-19T11:36:00.000Z"}')
assert _e["title"] == "Comunicado Oficial: renovación" and _e["media_content"] == [{"url": "https://a/i.jpg?wid=1200&hei=675"}]
assert _e["published_parsed"][:5] == (2026, 11, 19, 11, 36)
print("OK pages du club")

# base gardée en texte dans git : copie puis reconstruction à l'identique, et jamais d'écrasement par une base absente
import os
from contextlib import closing


def lignes(db):
    with closing(sqlite3.connect(db)) as con:
        return sorted(con.execute("SELECT * FROM articles").fetchall())


with tempfile.TemporaryDirectory() as d:
    db, dump = Path(d) / "a.db", Path(d) / "a.sql"
    g.enregistrer(reponses, items, db)
    assert not commun.sauvegarder_base(Path(d) / "absente.db", dump) and not dump.exists()
    assert commun.sauvegarder_base(db, dump)
    avant = lignes(db)
    os.utime(dump, (1, 1))  # dates fixées : deux écritures de suite peuvent tomber sur le même tic d'horloge
    assert not commun.restaurer_base(db, dump)  # base plus récente que la copie : gardée
    os.utime(db, (0, 0))  # copie plus récente (git pull) : base reconstruite
    assert commun.restaurer_base(db, dump)
    assert lignes(db) == avant
    db.unlink()  # dépôt fraîchement cloné (GitHub)
    assert commun.restaurer_base(db, dump) and db.exists()
print("OK sauvegarde de la base")

# pagination des listes : 5 articles, 2 par page -> 3 pages reliées, anciennes pages en trop supprimées
with tempfile.TemporaryDirectory() as d:
    db, site = Path(d) / "a.db", Path(d) / "site"
    g.enregistrer([{"id": i, "section": "debats", "titre": f"ت{i}", "texte": "ن", "auteur_ar": "ك"} for i in range(1, 6)],
                  [{"lien": f"https://as.com/p{i}", "titre": "T", "auteur": "Ana", "source": "AS", "pays": "es"} for i in range(5)], db)
    g.PAR_PAGE, avant = 2, g.PAR_PAGE
    try:
        site.mkdir()
        (site / "debats--9.html").write_text("ancienne", encoding="utf-8")
        g.rendre_site(db, site)
    finally:
        g.PAR_PAGE = avant
    p1, p2, p3 = [(site / f).read_text(encoding="utf-8") for f in ("debats.html", "debats--2.html", "debats--3.html")]
    assert 'href="debats--2.html" rel="next"' in p1 and 'rel="prev"' not in p1 and "صفحة 1 من 3" in p1
    assert 'href="debats.html" rel="prev"' in p2 and 'href="debats--3.html" rel="next"' in p2
    assert 'rel="next"' not in p3 and p3.count('class="carte') == 1
    assert (site / "j-ana--3.html").exists() and not (site / "debats--4.html").exists() and not (site / "debats--9.html").exists()
    assert 'class="pages"' not in (site / "tactique.html").read_text(encoding="utf-8")  # une seule page : pas de navigation
print("OK pagination")

# Bernabéu : une information rangée dans club reste présentée comme un خبر et ne fait pas la une
with tempfile.TemporaryDirectory() as d:
    db, site = Path(d) / "a.db", Path(d) / "site"
    g.enregistrer([{"id": 1, "section": "club", "titre": "NFL في البرنابيو", "texte": "ن"},
                   {"id": 2, "section": "tactique", "titre": "رأي", "texte": "ن"}],
                  [{"lien": "https://ser.com/nfl", "titre": "NFL", "auteur": "", "source": "Cadena SER", "pays": "es", "type": "info"},
                   {"lien": "https://ser.com/op", "titre": "Op", "auteur": "", "source": "Cadena SER", "pays": "es", "type": "opinion"}], db)
    g.rendre_site(db, site)
    nfl = (site / "a-1.html").read_text(encoding="utf-8")
    assert 'class="nature">خبر<' in nfl and "ملخص خبر نشرته" in nfl and "مقال رأي" not in nfl
    assert 'href="club.html"' in nfl  # rubrique club
    accueil = (site / "index.html").read_text(encoding="utf-8")
    assert accueil.index("رأي") < accueil.index("NFL في البرنابيو")  # la une (en haut) est l'opinion
    assert "Bernabéu" in g.PROMPT_TRI and "Bernabéu" in g.construire_prompt([])
print("OK Bernabéu dans club")

# API WordPress (La Galerna, flux RSS coupé) : entrées au format de feedparser, date en UTC
with tempfile.TemporaryDirectory() as d:
    f = Path(d) / "posts.json"
    f.write_text(json.dumps([{"title": {"rendered": "Bloody Hell JJ Gabriel"}, "link": "https://www.lagalerna.com/jj/",
                              "date_gmt": "2026-11-07T12:05:00", "excerpt": {"rendered": "<p>Resumen</p>"},
                              "content": {"rendered": "<p>Texto completo</p>"}}]), encoding="utf-8")
    [e] = commun.lire_wordpress(f.as_uri())
    assert e["title"] == "Bloody Hell JJ Gabriel" and e["link"].endswith("/jj/") and e["content"][0]["value"] == "<p>Texto completo</p>"
    assert e["published_parsed"][:5] == (2026, 11, 7, 12, 5), "date en UTC"
print("OK WordPress")

# auteur : toujours une personne ; sinon le site cite seulement le journal (page, carte, couverture, thread)
for nom, jr in [("Redacción", "AS"), ("Agencias", "Cadena SER"), ("EFE", "Marca"), ("Cadena SER", "Cadena SER"),
                ("Managing Madrid", "Managing Madrid"), ("info@vi.nl (VI)", "VI"), ("LALIGA", "AS"), ("", "AS")]:
    assert g.auteur_reel(nom, jr) == "", nom
for nom in ("Tomás Roncero", "Sid Lowe", "JUAN IGNACIO GARCÍA-OCHOA"):
    assert g.auteur_reel(nom, "Marca") == nom
with tempfile.TemporaryDirectory() as d:
    db, site = Path(d) / "a.db", Path(d) / "site"
    g.enregistrer([{"id": 1, "section": "actus", "titre": "خبر", "texte": "ن", "auteur": "Agencias", "auteur_ar": "وكالات",
                    "tweets": ["تغريدة"]}],
                  [{"lien": "https://ser.com/x", "titre": "T", "auteur": "Redacción", "source": "Cadena SER", "pays": "es"}], db)
    con = g.connexion(db)
    assert tuple(con.execute("SELECT auteur, auteur_ar FROM articles").fetchone()) == ("", "")
    tweets = json.loads(con.execute("SELECT tweets FROM threads").fetchone()[0])
    con.close()
    assert "📰 Cadena SER" in tweets[-1] and "وكالات" not in tweets[-1]
    g.rendre_site(db, site)
    assert "وكالات" not in (site / "a-1.html").read_text(encoding="utf-8") and not list(site.glob("j-*.html"))
print("OK auteur = une personne, sinon le journal")

# nom arabe : celui de l'auteur du flux ; si Claude a renvoyé un autre nom latin, son arabe n'est pas repris
assert g.meme_nom("SERGIO RODRÍGUEZ C.", "Sergio Rodríguez") and not g.meme_nom("Sam Leveridge", "Lucas Navarrete")
with tempfile.TemporaryDirectory() as d:
    db = Path(d) / "a.db"
    g.enregistrer([{"id": 1, "titre": "ع", "texte": "ن", "auteur": "Lucas Navarrete", "auteur_ar": "لوكاس نافاريتي"},
                   {"id": 2, "titre": "ع", "texte": "ن", "auteur": "Joel del Río", "auteur_ar": "خويل ديل ريو"}],
                  [{"lien": "https://mm.com/1", "titre": "T", "auteur": "Sam Leveridge", "source": "Managing Madrid", "pays": "us"},
                   {"lien": "https://mm.com/2", "titre": "T", "auteur": "JOEL DEL RÍO", "source": "Marca", "pays": "es"}], db)
    con = g.connexion(db)
    assert [tuple(r) for r in con.execute("SELECT auteur, auteur_ar FROM articles ORDER BY id")] == [
        ("Sam Leveridge", "Sam Leveridge"), ("JOEL DEL RÍO", "خويل ديل ريو")]
    con.close()
print("OK nom arabe de l'auteur du flux")

# vignettes des cartes : WebP 720 px créé à côté du PNG, anciennes couvertures et vignettes supprimées
import hashlib
from PIL import Image
with tempfile.TemporaryDirectory() as d:
    db, site = Path(d) / "a.db", Path(d) / "site"
    g.enregistrer([{"id": 1, "section": "debats", "titre": "ع", "texte": "ن"}],
                  [{"lien": "https://as.com/v", "titre": "T", "auteur": "", "source": "AS", "pays": "es"}], db)
    con = g.connexion(db); a = con.execute("SELECT * FROM articles").fetchone(); con.close()
    nom = f"a-1-{hashlib.sha1(couvertures.couverture_html(a).encode()).hexdigest()[:8]}.png"
    (site / "couvertures").mkdir(parents=True)
    Image.new("RGB", (1200, 630), "navy").save(site / "couvertures" / nom)  # comme si Edge l'avait rendue
    for vieux in ("a-9-old.png", "a-9-old-v.webp"):
        (site / "couvertures" / vieux).write_bytes(b"x")
    couvertures.EDGE = "edge-factice"  # PNG déjà là : Edge n'est pas lancé
    try:
        assert couvertures.generer_couvertures([a], site) == {1: nom}
    finally:
        couvertures.EDGE = None
    with Image.open(site / "couvertures" / couvertures.vignette(nom)) as v:
        assert v.format == "WEBP" and v.size == (720, 378)
    assert sorted(f.name for f in (site / "couvertures").iterdir()) == sorted([nom, couvertures.vignette(nom)])
print("OK vignettes")

# intertitres de la page source : gardés seulement devant un paragraphe (ils nomment souvent le joueur dont on parle)
long_p = "Llegó del FC Tokyo con 18 años y encadenó cesiones cada verano hasta su venta a la Real Sociedad."
p = g.Paragraphes()
p.feed(f"<h2>Menú</h2><p>{long_p}</p><h3>Kubo</h3><p>corto</p><p>{long_p}</p><h2>Lo más leído</h2><h3>Otro artículo</h3>")
assert p.morceaux == [long_p, "Kubo", long_p], p.morceaux
# intertitres « ## » du texte arabe : rendus en <h2>, échappés, même collés au paragraphe suivant
assert g.corps_html("فقرة\n\n## عنوان <b>\nفقرة 2\n\nسطر\nثانٍ") == "<p>فقرة</p><h2>عنوان &lt;b&gt;</h2><p>فقرة 2</p><p>سطر\nثانٍ</p>"
print("OK intertitres")

# style : le guide est dans le prompt, et plus aucun exemple n'invite à commencer par « يرى الكاتب »
pr = g.construire_prompt([])
assert g.STYLE in pr and "{style}" not in pr and "jamais par « يرى الكاتب" in pr and "(يرى الكاتب...)" not in pr
assert "Ne commence jamais par « يرى الصحفي" in g.threads.REGLES
assert all(code in g.threads.REGLES for code in ("🚨 عاجل |", "✅ رسميًا |", "🔄 ميركاتو |", "🧠 قراءة |", "🔥 نقاش |"))
assert "(اسم الكاتب - ماركا)" in g.threads.REGLES and "ne garde que le média d'origine" in g.threads.REGLES  # source entre parenthèses, sans chaîne
print("OK style")

# Claude en panne : erreur rattrapable (plus de sys.exit au milieu d'un passage), threads repris plus tard
import subprocess
vrai_run, commun.subprocess.run = commun.subprocess.run, lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "quota dépassé")
vrai_which, commun.shutil.which = commun.shutil.which, lambda nom: "claude"
try:
    try:
        commun.appeler_claude("x")
        raise AssertionError("ErreurClaude attendue")
    except commun.ErreurClaude as err:
        assert "quota dépassé" in str(err)

    def expire(*a, **k):
        raise subprocess.TimeoutExpired("claude", 600)
    commun.subprocess.run = expire
    try:
        commun.appeler_claude("x")
        raise AssertionError("ErreurClaude attendue")
    except commun.ErreurClaude:
        pass
finally:
    commun.subprocess.run, commun.shutil.which = vrai_run, vrai_which
print("OK panne de Claude")

# graphie arabe de référence : la plus fréquente en base pour un journaliste, "noms_ar" de config.json pour un média
with tempfile.TemporaryDirectory() as d:
    db = Path(d) / "a.db"
    src = [{"lien": f"https://mm.com/{i}", "titre": f"Titre numéro {i}", "auteur": "Kiyan Sobhani", "source": "Managing Madrid",
            "pays": "us"} for i in range(4)]
    g.enregistrer([{"id": i + 1, "titre": f"عنوان {i}", "texte": "ن", "auteur_ar": ar}
                   for i, ar in enumerate(["كيان سبحاني", "كيان سبحاني", "كيان صوباني"])], src[:3], db)
    con = g.connexion(db)
    noms = g.noms_arabes(con)
    assert noms["kiyan-sobhani"] == "كيان سبحاني" and noms["managing-madrid"] == "مانيجينغ مدريد"
    pr = g.construire_prompt([{**src[3], "texte": "x"}], noms=noms)
    assert "Journal : Managing Madrid (en arabe : مانيجينغ مدريد)" in pr and "Auteur : Kiyan Sobhani (en arabe : كيان سبحاني)" in pr
    g.enregistrer([{"id": 1, "titre": "عنوان آخر", "texte": "ن", "auteur_ar": "كيان سوبهاني"}], src[3:], db)  # autre graphie de Claude
    assert con.execute("SELECT auteur_ar FROM articles ORDER BY id DESC").fetchone()[0] == "كيان سبحاني"
    con.close()
print("OK noms arabes")

# page refusée et flux trop court : l'article récent attend le passage suivant (ni rédigé, ni marqué comme vu)
from datetime import datetime, timedelta
recent, vieux = commun.maintenant().isoformat(timespec="seconds"), (commun.maintenant() - timedelta(hours=7)).isoformat(timespec="seconds")
bloque = {"illisible": True, "texte": "x" * 700, "publie": recent}
assert g.a_reessayer(bloque) and not g.a_reessayer({**bloque, "publie": vieux})  # 7 h plus tard : on se contente du flux
assert not g.a_reessayer({**bloque, "texte": "x" * 1500}) and not g.a_reessayer({**bloque, "illisible": False})
assert not g.a_reessayer({**bloque, "publie": None})
# conférence sur le site du club : page créée avant et complétée pendant ; attend d'être longue et stable depuis 15 min
_conf = {"officiel": True, "lien": "https://www.realmadrid.com/es-ES/noticias/futbol/primer-equipo/ruedas-de-prensa/mourinho-20-11-2026",
         "texte": "x" * 6000, "publie": recent, "modifie": commun.maintenant() - timedelta(minutes=20)}
assert not g.a_reessayer(_conf)  # complète et stable : rédigée
assert g.a_reessayer({**_conf, "texte": "x" * 800})  # presque vide
assert g.a_reessayer({**_conf, "modifie": commun.maintenant() - timedelta(minutes=5)})  # encore complétée
assert not g.a_reessayer({**_conf, "texte": "x" * 800, "publie": vieux})  # au bout de 6 h : rédigée telle quelle
assert not g.a_reessayer({**_conf, "lien": "https://www.realmadrid.com/es-ES/noticias/club/comunicados/x", "texte": "x" * 800})  # communiqué : tout de suite
_comm = {**_conf, "lien": "https://www.realmadrid.com/es-ES/noticias/club/comunicados/x", "titre": "Noticias del Real Madrid | Web Oficial"}
assert g.a_reessayer(_comm) and not g.a_reessayer({**_comm, "publie": vieux})  # page pas encore prête : relue au passage suivant
appels, marques = [], []
vrais = g.appeler_claude, g.marquer_vus, g.texte_complet
g.appeler_claude, g.marquer_vus = (lambda *a: appels.append(1) or "[]"), (lambda items, db: marques.extend(items))
g.texte_complet = lambda it: it.update(illisible=True) or "x" * 700
try:
    lot = [{"lien": "https://as.com/1", "titre": "Algo pasa", "auteur": "", "source": "AS - Opinion", "publie": recent}]
    assert g.traiter_lot(lot) == 0 and not appels and not marques
finally:
    g.appeler_claude, g.marquer_vus, g.texte_complet = vrais
# heure UTC partout : comparable au « now » de SQLite, sur le PC comme sur GitHub
from datetime import timezone
assert abs((commun.maintenant() - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()) < 5
print("OK nouvel essai des pages refusées")

# jeton permanent de la Page Facebook : échange du jeton court, choix de la bonne Page, refus d'un jeton qui expire
import threads as th
reponses = {"oauth/access_token": {"access_token": "LONG"},
            "me/accounts": {"data": [{"id": "1", "name": "Autre", "access_token": "A"}, {"id": "42", "name": "Peña", "access_token": "PAGE"}]},
            "debug_token": {"data": {"expires_at": 0, "scopes": ["pages_manage_posts", "pages_read_engagement"]}}}
appels = []
vrai_lire, th.graph_lire = th.graph_lire, lambda chemin, **p: appels.append((chemin, p)) or reponses[chemin]
try:
    assert th.jeton_permanent("app", "secret", "COURT", 42) == ("PAGE", "Peña")
    assert appels[0][1]["fb_exchange_token"] == "COURT" and appels[1][1]["access_token"] == "LONG" and appels[2][1]["input_token"] == "PAGE"
    for cas in ({"me/accounts": {"data": []}}, {"debug_token": {"data": {"expires_at": 1799999999, "scopes": ["pages_manage_posts"]}}},
                {"debug_token": {"data": {"expires_at": 0, "scopes": ["pages_show_list"]}}}):
        reponses_ok, reponses = reponses, {**reponses, **cas}
        try:
            th.jeton_permanent("app", "secret", "COURT", 42)
            raise AssertionError("refus attendu")
        except ValueError:
            pass
        reponses = reponses_ok
finally:
    th.graph_lire = vrai_lire
print("OK jeton Facebook permanent")

# revue des sources : même filtre que la collecte, flux en panne en haut, proposition vérifiée avant d'être recommandée
assert commun.garde({"filtre_lien": ["/cronicas/"]}, "x", "", "https://rm.com/cronicas/a", [])
assert not commun.garde({"filtre_lien": ["/cronicas/"]}, "Real Madrid", "", "https://rm.com/basket/a", ["real madrid"])
assert commun.garde({"que_le_real": True}, "x", "", "", []) and not commun.garde({}, "Barça gana", "", "", ["real madrid"])
import sources
import time
recent_t = time.gmtime(time.time() - 3600)
lus = {"https://ok.es/rss": [{"title": "El Real Madrid gana", "link": "https://ok.es/1", "published_parsed": recent_t}],
       "https://mort.es/rss": OSError("404"),
       "https://uy.com/rss": [{"title": "Peñarol gana", "link": "https://uy.com/1", "published_parsed": time.gmtime(time.time() - 20 * 86400)}],
       "https://club.es/rss": [{"title": "Baloncesto", "link": "https://club.es/basket/1", "published_parsed": recent_t}],
       "https://nouveau.es/rss": [{"title": "Mbappé marca", "link": "https://nouveau.es/1", "published_parsed": recent_t}]}
vrais_s = sources.lire_flux, sources.appeler_claude, sources.CONFIG["flux"]
sources.lire_flux = lambda f: lus.get(f["url"], [])
sources.appeler_claude = lambda prompt, *a: json.dumps([{"retirer": [{"flux": "Mort - RSS", "raison": "en panne"}],
    "ajouter": [{"nom": "Nouveau", "url": "https://nouveau.es/rss", "pays": "es", "raison": "cité souvent"},
                {"nom": "Inventé", "url": "https://invente.es/rss", "pays": "es", "raison": "?"}], "remarques": "RAS"}])
sources.CONFIG["flux"] = [{"nom": "Ok - RSS", "url": "https://ok.es/rss", "pays": "es"}, {"nom": "Mort - RSS", "url": "https://mort.es/rss", "pays": "es"},
                          {"nom": "Club - Site", "url": "https://club.es/rss", "filtre_lien": ["/cronicas/"]},
                          {"nom": "Uy - RSS", "url": "https://uy.com/rss", "pays": "uy", "veille": True}]
try:
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "a.db"
        g.enregistrer([{"id": 1, "titre": "عنوان", "texte": "بحسب «ذا أثلتيك» و«ذا أثلتيك» و«ذا أثلتيك»"}],
                      [{"lien": "https://ok.es/1", "titre": "T", "auteur": "", "source": "Ok - RSS", "pays": "es"}], db)
        rapport = sources.revue(db)
finally:
    sources.lire_flux, sources.appeler_claude, sources.CONFIG["flux"] = vrais_s
assert rapport.index("Mort - RSS | es | ❌ erreur") < rapport.index("Ok - RSS | es | ✅"), rapport
assert "| Ok - RSS | es | ✅ | 1 | 1 | 1 |" in rapport and "| Club - Site | - | ✅ | 1 | 0 | 0 |" in rapport  # rubriques filtrées : pas une panne
assert "| Uy - RSS (veille) | uy | ✅ | 1 | 0 | 0 |" in rapport  # veille : 20 jours sans rien sur le Real, normal and "**Mort - RSS** : en panne" in rapport
assert "→ ✅ 1 entrées, 1 sur le Real" in rapport and "invente.es/rss` → ❌ vide" in rapport and "ذا أثلتيك (3)" in rapport
print("OK revue des sources")

# tableau de bord : compte par jour de Madrid, pannes et brouillons remontés en blocages, page rendue sans l'API GitHub
import statut
from datetime import datetime as _dt
con = sqlite3.connect(":memory:")
t.connexion_threads(con)
con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, date TEXT, section TEXT, journal TEXT)")
con.executemany("INSERT INTO articles (date, section, journal) VALUES (?, ?, ?)",
                [("2026-11-17T10:00:00", "actus", "Marca"), ("2026-11-16T22:30:00", "actus", "AS"),  # 23 h 30 à Madrid : hier
                 ("2026-11-16T12:00:00", "tactique", "AS")])
con.executemany("INSERT INTO threads (article_id, tweets, statut, date, typefully) VALUES (?, '[]', ?, ?, ?)",
                [(1, "immédiat", "2026-11-17T10:05:00", "11"), (2, "bloqué : test", "2026-11-17T10:06:00", "12")])
t.noter(con, "Typefully", "erreur 500")
d = statut.donnees(con, _dt(2026, 11, 17, 12), [], None, Path("nulle-part"), Path("nulle-part"), Path("nulle-part"))
ag = {a["id"]: a for a in d["agents"]}
assert ag["redacteur"]["rangs"] == [("Hier", "2 articles rédigés"), ("Aujourd'hui", "1 article rédigé (1 actus)")], ag["redacteur"]["rangs"]
assert ag["editeur_x"]["etat"] == "bloque" and "erreur 500" in ag["editeur_x"]["blocages"][0]
assert ag["controleur"]["etat"] == "attente" and ag["sujets"]["etat"] == "demande"
assert d["graphes"]["par_heure"]["Articles rédigés"][11] == 1 and d["graphes"]["par_heure"]["Articles rédigés"][14] is None  # 11 h à Madrid ; futur vide
html_statut = statut.page(d)
assert 'id="editeur_x"' in html_statut and "2 agents bloqués" in html_statut  # Éditeur X et Veilleur
print("OK tableau de bord")

# validation des faits depuis le tableau de bord : lecture de l'issue, rangement sans jamais supprimer, secours « À classer »
import faits
assert faits.lire_issue("Texte\n\ngarder: 3, 5,9\ndernier: 12\n") == ([3, 5, 9], 12)
assert faits.lire_issue("garder: \ndernier: 4") == ([], 4)
try:
    faits.lire_issue("garder: 1")
    raise AssertionError("dernier absent : refusé")
except ValueError:
    pass
base_c = "# T\n\nDernier fait relu : 2\n\n## Effectif\n- a\n- b\n\n## Matchs\n| D | S |\n|---|---|\n| 1 | 2-0 |\n\n- bilan : 3 buts\n\n## Médias\n\n## Préférences pour les scripts\n- p"
ops = [{"action": "ajouter", "section": "Effectif", "ligne": "- c"},
       {"action": "ajouter", "section": "Matchs", "ligne": "| 9 | 1-0 |"},
       {"action": "remplacer", "ancienne": "- bilan : 3 buts", "ligne": "- bilan : 4 buts"},
       {"action": "ajouter", "section": "Médias", "ligne": "- m"},
       {"action": "ajouter", "section": "Inconnue", "ligne": "- x"},  # section inconnue → À classer
       {"action": "remplacer", "ancienne": "- introuvable", "ligne": "- y"},  # ligne introuvable → À classer
       {"action": "ajouter", "section": "Effectif", "ligne": "## titre glissé"}]  # ignoré
texte_c, resume_c = faits.integrer(base_c, ops, [], 9)
assert "- a\n- b\n- c\n" in texte_c and "| 1 | 2-0 |\n| 9 | 1-0 |\n" in texte_c and "- bilan : 4 buts" in texte_c and "3 buts" not in texte_c
assert "## Médias\n\n- m\n\n## À classer\n\n- x\n- y\n\n## Préférences" in texte_c, texte_c
assert "Dernier fait relu : 9" in texte_c and "titre glissé" not in texte_c and len(resume_c) == 6
assert faits.integrer(base_c, None, ["- s"], 1)[0].count("Dernier fait relu : 2") == 1  # secours ; le numéro ne recule jamais
assert "## À classer\n\n- s\n" in faits.integrer(base_c, None, ["- s"], 1)[0]
print("OK validation des faits")

# Veilleur : fichier de workflow invalide et autres workflows en échec ; l'ancien fichier invalide réparé ne compte plus
wfs = [{"id": 1, "name": ".github/workflows/x.yml", "path": ".github/workflows/x.yml"},
       {"id": 2, "name": "Validation des faits", "path": ".github/workflows/faits.yml"},
       {"id": 3, "name": "Mise à jour", "path": ".github/workflows/mise_a_jour.yml"}]
run = lambda ev, c: {"event": ev, "status": "completed", "conclusion": c, "created_at": "2026-11-17T20:53:04Z"}  # noqa: E731
assert statut.alertes_workflows(wfs, {2: [run("push", "failure")]}) == ["fichier de workflow invalide : .github/workflows/x.yml (voir le courriel de GitHub)"]
assert "« Validation des faits » en échec (2026-11-17 20:53 UTC)" in statut.alertes_workflows(wfs[1:], {2: [run("issues", "failure"), run("issues", "success")]})[0]
assert statut.alertes_workflows(wfs[1:], {2: [run("issues", "success"), run("issues", "failure")]}) == []  # réparé depuis
d = statut.donnees(con, _dt(2026, 11, 17, 12), [], None, Path("nulle-part"), Path("nulle-part"), Path("nulle-part"), alertes_gh=["fichier invalide"])
assert "fichier invalide" in {a["id"]: a for a in d["agents"]}["veilleur"]["blocages"]
print("OK Veilleur des workflows")

# revue des sources : décisions cochées appliquées à config.json, et seulement elles
conf_t = {"flux": [{"nom": "A", "url": "https://a.es/rss"}, {"nom": "B", "url": "https://b.es/rss"}], "noms_ar": {"A": "أ"}}
corps_t = """## Décisions
- [x] Retirer le flux `A`
- [ ] Retirer le flux `B`
- [X] Ajouter le flux `{"nom": "C", "url": "https://c.it/rss", "pays": "it", "autorisation": true}`
- [x] Ajouter le flux `{"nom": "D", "url": "ftp://d"}`
- [x] Ajouter le flux `{"nom": "B2", "url": "https://b.es/rss"}`
- [x] Ajouter la graphie `{"C": "سي", "A": "autre"}`
- [x] Retirer le flux `Z`"""
nouvelle, res = sources.appliquer(corps_t, conf_t)
assert [f["nom"] for f in nouvelle["flux"]] == ["B", "C"] and nouvelle["flux"][1] == {"nom": "C", "url": "https://c.it/rss", "pays": "it"}  # jamais d'autorisation
assert nouvelle["noms_ar"] == {"A": "أ", "C": "سي"} and conf_t["flux"][0]["nom"] == "A"  # graphie existante gardée ; l'original intact
assert len(res) == 6 and "déjà suivi" in res[3] and "Z : déjà absent" in res[-1], res
assert sources.appliquer("rien de coché", conf_t) == (conf_t, [])
d_rev = "\n".join(sources.modifications({"retirer": [{"flux": sources.CONFIG["flux"][0]["nom"]}]}, []))
assert sources.appliquer(d_rev.replace("- [ ]", "- [x]"), sources.CONFIG)[0]["flux"] == sources.CONFIG["flux"][1:]  # aller-retour
print("OK revue des sources : décisions appliquées")

# calendrier : page du site officiel (chaque match deux fois), 5 prochains ; règle « match en cours » de 0 à 2 h 30 après le coup d'envoi
import calendrier
obj = lambda nom, d, fixe: (f'"description":{{"plaintext":"{nom}"}},"week":"13","weekAsText":null,"dateTime":"{d}.000Z",'  # noqa: E731
                            f'"dateTxt":null,"isScheduled":{fixe},"status":"pre_match"')
page = " ".join([obj("Real Madrid vs PSV", "2026-11-24T20:00:00", "true")] * 2 + [obj("Real Madrid vs Celta de Vigo", "2026-11-21T20:00:00", "true"),
                 obj("Real Madrid vs Osasuna", "2026-12-13T00:00:00", "false"), obj("Getafe vs Real Madrid", "2026-11-01T20:00:00", "true")])
pm = calendrier.prochains(page, datetime(2026, 11, 21, 8))
assert [m["match"] for m in pm] == ["Real Madrid vs Celta de Vigo", "Real Madrid vs PSV", "Real Madrid vs Osasuna"] and not pm[2]["heure_fixee"], pm
with tempfile.TemporaryDirectory() as d:
    ancien, calendrier.FICHIER = calendrier.FICHIER, Path(d) / "matchs.json"
    assert calendrier.match_en_cours(datetime(2026, 11, 21, 20, 30)) == ""  # pas de fichier : pas de règle
    calendrier.FICHIER.write_text(json.dumps(pm), encoding="utf-8")
    regle = calendrier.match_en_cours(datetime(2026, 11, 21, 21, 10))
    assert "Celta" in regle and "21:00" in regle and "mi-temps" in regle, regle
    assert "supporter du Real Madrid" in regle and "aucun jugement sur le jeu" in regle and "critique du Real" in regle, regle
    assert calendrier.match_en_cours(datetime(2026, 11, 21, 19, 59)) == calendrier.match_en_cours(datetime(2026, 11, 21, 22, 30)) == ""
    assert calendrier.match_en_cours(datetime(2026, 12, 13, 1)) == ""  # heure pas encore fixée : date seule, pas de fenêtre
    # suivi en direct (Sofascore) : état noté à chaque changement ; début, buts, rouges, mi-temps, fin, chacun une seule fois
    import match as mt
    import subprocess
    coup_envoi = datetime(2026, 11, 21, 20, tzinfo=timezone.utc).timestamp()
    def evt(code, typ, desc, sd=None, se=None, debut=coup_envoi):  # forme des événements de l'API Sofascore
        e = {"id": 77, "startTimestamp": int(debut), "status": {"code": code, "type": typ, "description": desc},
             "homeTeam": {"id": 2829, "name": "Real Madrid"}, "awayTeam": {"id": 2821, "name": "Celta Vigo"}}
        if sd is not None:
            e["homeScore"], e["awayScore"] = {"current": sd}, {"current": se}
        return e
    def but(i, minute, nom, h, a, classe="regular", ar=None):
        p = {"name": nom, **({"fieldTranslations": {"nameTranslation": {"ar": ar}}} if ar else {})}
        return {"id": i, "incidentType": "goal", "incidentClass": classe, "time": minute, "player": p, "homeScore": h, "awayScore": a}
    sofa, appels_sofa = {"next": [evt(0, "notstarted", "Not started")], "last": [], "incidents": []}, []
    def faux_sofascore(chemin):
        appels_sofa.append(chemin)
        if sofa.get("panne"):
            raise subprocess.CalledProcessError(22, "curl")
        if chemin.endswith("/incidents"):
            assert chemin == "event/77/incidents", chemin
            return {"incidents": sofa["incidents"]}
        return {"events": sofa[chemin.split("/")[3]]}
    textes = lambda: [c["platforms"]["x"]["posts"][0]["text"] for c in envois]  # noqa: E731
    cs = sqlite3.connect(":memory:")
    envois = []
    vrai = (mt.sofascore, calendrier.appeler_claude, t.typefully_api, t.reglage)
    mt.sofascore = faux_sofascore
    calendrier.appeler_claude = lambda *a: "سيلتا فيغو"
    t.typefully_api = lambda chemin, corps=None: (envois.append(corps), {"id": len(envois)})[1]
    t.reglage = lambda cle: "k"
    vrai_direct = (calendrier.direct_actif, calendrier.DIRECT)
    calendrier.direct_actif, calendrier.DIRECT = (lambda: False), Path(d) / "direct.json"
    try:
        assert calendrier.suivre_match(cs, datetime(2026, 11, 21, 19, 50)) == 0 and not appels_sofa  # avant le coup d'envoi : rien lu
        assert not cs.execute("SELECT name FROM sqlite_master WHERE name = 'suivi_match'").fetchone()
        assert calendrier.suivre_match(cs, datetime(2026, 11, 21, 20, 1)) == 0 and appels_sofa == ["team/2829/events/next/0"]  # pas commencé
        sofa["next"] = [evt(0, "notstarted", "Not started", debut=coup_envoi + 7 * 86400), evt(6, "inprogress", "1st half", 0, 0)]
        assert calendrier.suivre_match(cs, datetime(2026, 11, 21, 20, 5)) == 1 and "انطلاق المباراة" in textes()[-1]
        assert calendrier.suivre_match(cs, datetime(2026, 11, 21, 20, 10)) == 0  # rien de neuf
        sofa["next"] = [evt(6, "inprogress", "1st half", 0, 1)]
        sofa["incidents"] = [but(1, 6, "Pablo Durán", 0, 1, ar="بابلو دوران"),
                             {"id": 5, "incidentType": "card", "incidentClass": "yellow", "time": 20, "isHome": True, "player": {"name": "X"}}]
        assert calendrier.suivre_match(cs, datetime(2026, 11, 21, 20, 15)) == 1  # carton jaune : pas de tweet
        assert textes()[-1].startswith("⚽ هدف لـسيلتا فيغو") and "بابلو دوران 6'" in textes()[-1] and "ريال مدريد 0 - 1 سيلتا فيغو" in textes()[-1]
        sofa["panne"] = True
        assert calendrier.suivre_match(cs, datetime(2026, 11, 21, 20, 40)) == 0  # Bright Data refuse : repris au passage suivant
        del sofa["panne"]
        sofa["next"] = [evt(31, "inprogress", "Halftime", 0, 1)]
        assert calendrier.suivre_match(cs, datetime(2026, 11, 21, 20, 50)) == 1 and textes()[-1].startswith("⏸️ نهاية الشوط الأول")
        assert calendrier.suivre_match(cs, datetime(2026, 11, 21, 20, 55)) == 0  # mi-temps une seule fois
        # deux événements entre deux passages : partent dans l'ordre ; rouge et but de la tête vers le Real
        sofa["next"] = [evt(7, "inprogress", "2nd half", 1, 1)]
        sofa["incidents"] += [{"id": 8, "incidentType": "card", "incidentClass": "yellowRed", "time": 60, "isHome": False, "player": {"name": "Starfelt"}},
                              but(2, 66, "Jude Bellingham", 1, 1)]
        echec = [True]
        def typefully_une_panne(chemin, corps=None):
            if echec.pop() if echec else False:
                raise OSError("Typefully indisponible")
            envois.append(corps)
            return {"id": len(envois)}
        t.typefully_api = typefully_une_panne
        assert calendrier.suivre_match(cs, datetime(2026, 11, 21, 21, 20)) == 0  # 1er envoi refusé : rien n'est marqué parti
        assert calendrier.suivre_match(cs, datetime(2026, 11, 21, 21, 25)) == 2
        assert textes()[-2].startswith("🟥 بطاقة حمراء") and "Starfelt (سيلتا فيغو) 60' (إنذار ثانٍ)" in textes()[-2]
        assert textes()[-1].startswith("⚽🔥 هدددف لريال مدريد!") and "Jude Bellingham 66'" in textes()[-1]
        sofa["next"], sofa["last"] = [], [evt(100, "finished", "Ended", 2, 1)]  # fini : passé dans events/last
        sofa["incidents"].append(but(3, 85, "Carlos Espí", 2, 1, "penalty", "كارلوس إسبي"))
        assert calendrier.suivre_match(cs, datetime(2026, 11, 21, 21, 55)) == 2  # dernier but puis fin
        assert "كارلوس إسبي 85' (ركلة جزاء)" in textes()[-2]
        assert textes()[-1] == ("🏁 نهاية المباراة\n\nريال مدريد 2 - 1 سيلتا فيغو\n\n⚽ بابلو دوران 6' (سيلتا فيغو)\n⚽ Jude Bellingham 66'"
                                "\n⚽ كارلوس إسبي 85' (ركلة جزاء)\n\n#ريال_مدريد"), textes()[-1]
        assert calendrier.suivre_match(cs, datetime(2026, 11, 21, 22, 0)) == 0 and len(envois) == 7  # rien ne part deux fois
        assert all(c["publish_at"] == "now" for c in envois)
    finally:
        mt.sofascore, calendrier.appeler_claude, t.typefully_api, t.reglage = vrai
    suivi = cs.execute("SELECT statut, score FROM suivi_match ORDER BY rowid").fetchall()
    assert suivi == [("Not started", ""), ("1st half", "0-0"), ("1st half", "0-1"), ("Halftime", "0-1"), ("2nd half", "1-1"), ("Ended", "2-1")], suivi
    # match à l'extérieur, but contre son camp de l'adversaire : compté pour le Real d'après le score
    dehors = evt(7, "inprogress", "2nd half", 0, 1)
    dehors["homeTeam"], dehors["awayTeam"] = dehors["awayTeam"], dehors["homeTeam"]
    calendrier.appeler_claude = lambda *a: "سيلتا فيغو"
    try:
        tw = dict(calendrier.tweets_du_match(dehors, [but(9, 30, "Starfelt", 0, 1, "ownGoal")]))
    finally:
        calendrier.appeler_claude = vrai[1]
    assert tw["but:9"].startswith("⚽🔥 هدددف لريال مدريد!") and "Starfelt 30' (ضد مرماه)" in tw["but:9"] and "سيلتا فيغو 0 - 1 ريال مدريد" in tw["but:9"]
    # suivi dédié : une lecture par minute ; chaque fait une fois, dans l'ordre ; incidents relus si le score ou le statut change
    etapes = [(evt(0, "notstarted", "Not started"), []), (evt(6, "inprogress", "1st half", 0, 0), []),
              (evt(6, "inprogress", "1st half", 0, 0), []), (evt(6, "inprogress", "1st half", 0, 1), [but(1, 6, "Durán", 0, 1)]),
              (evt(31, "inprogress", "Halftime", 0, 1), [but(1, 6, "Durán", 0, 1)]),
              (evt(100, "finished", "Ended", 1, 1), [but(1, 6, "Durán", 0, 1), but(2, 66, "Bellingham", 1, 1)])]
    pas, horloge, appels, sauves = [0], [datetime(2026, 11, 21, 19, 58)], [], []
    def sofa_minute(chemin):
        appels.append(chemin)
        e, inc = etapes[min(pas[0], len(etapes) - 1)]
        return {"incidents": inc} if chemin.endswith("/incidents") else {"event": e} if chemin == "event/77" else {"events": [e]}
    def minute_suivante(secondes):
        horloge[0] += timedelta(seconds=secondes)
        pas[0] += 1
    envois.clear()
    vrai2 = (mt.sofascore, t.typefully_api, calendrier.sauver_direct)
    mt.sofascore, calendrier.sauver_direct = sofa_minute, lambda msg: sauves.append(msg)
    t.typefully_api = lambda chemin, corps=None: (envois.append(corps), {"id": len(envois)})[1]
    try:
        cles = calendrier.suivre_en_direct("2026-11-21T20:00:00", dormir=minute_suivante, horloge=lambda: horloge[0])
    finally:
        mt.sofascore, t.typefully_api, calendrier.sauver_direct = vrai2
    assert cles == ["début", "but:1", "mi-temps", "but:2", "fin"] and sauves == [f"Direct : {c}" for c in cles], (cles, sauves)
    assert textes()[-1].startswith("🏁 نهاية المباراة") and len(envois) == 5  # rien ne part deux fois, arrêt à la fin
    assert appels[0] == "team/2829/events/next/0" and "team/2829/events/next/0" not in appels[1:]  # ensuite : event/77 seul
    assert appels.count("event/77/incidents") == 4, appels  # relus au début, au 1er but, à la mi-temps et à la fin, pas à chaque minute
    assert calendrier.lire_direct()["2026-11-21T20:00:00"] == {"cles": cles, "fini": True}
    calendrier.DIRECT.write_text(json.dumps({"2026-11-21T20:00:00": {"cles": ["début"], "fini": False}}), encoding="utf-8")
    calendrier.direct_actif = lambda: False
    assert calendrier.direct_a_lancer(datetime(2026, 11, 21, 19, 50)) == "2026-11-21T20:00:00"  # 15 min avant : lancé
    assert calendrier.direct_a_lancer(datetime(2026, 11, 21, 19, 40)) == ""  # trop tôt
    calendrier.direct_actif = lambda: True
    assert calendrier.direct_a_lancer(datetime(2026, 11, 21, 20, 30)) == ""  # tourne déjà
    calendrier.direct_actif, calendrier.DIRECT = vrai_direct
    calendrier.FICHIER = ancien
print("OK calendrier et règle pendant un match")

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
print("OK priorité opinion")

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
        fb = {"fr": "Avis", "en": "Opinion", "es": "Opinión"}
        g.enregistrer([{"id": 1, "section": "debats", "titre": "رأي جديد في النقاش", "texte": "ن", "titres_fb": fb},
                       {"id": 2, "section": "actus", "titre": "التشكيلة المحتملة أمام سيلتا", "texte": "ن", "titres_fb": fb},
                       {"id": 3, "section": "club", "titre": "حفل موسيقي في البرنابيو قريبًا", "texte": "ن", "titres_fb": fb},
                       {"id": 4, "section": "mercato", "titre": "صفقة الشتاء التي يحتاجها الفريق", "texte": "ن", "titres_fb": fb}],
                      [{"lien": "https://ex.com/op", "titre": "Una opinión", "auteur": "", "source": "AS", "pays": "es", "type": "opinion"},
                       {"lien": "https://ex.com/xi", "titre": "Alineación probable del Madrid", "auteur": "", "source": "AS", "pays": "es", "type": "info"},
                       {"lien": "https://ex.com/nfl", "titre": "Concierto en el Bernabéu", "auteur": "", "source": "AS", "pays": "es", "type": "info"},
                       {"lien": "https://ex.com/fichaje", "titre": "El fichaje de invierno", "auteur": "", "source": "AS", "pays": "es", "type": "opinion"}], db)
        assert t.vers_page(con) == 2 and "ex.com%2Fnfl" in appels[-2][1] and "ex.com%2Ffichaje" in appels[-1][1]  # mercato compris
        assert t.vers_page(con) == 0 and not any("ex.com%2Fop" in c or "ex.com%2Fxi" in c for _, c in appels)
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
    t.urllib.request.urlopen = lambda req, timeout=None: (appels.append((req.full_url, req.data.decode())), io.BytesIO(b"{}"))[1]
    try:
        assert t.vers_page(con) == 1
    finally:
        t.urllib.request.urlopen = vrai_urlopen
        t.CONFIG.pop("facebook_page_token")
    envoi = urllib.parse.parse_qs(appels[0][1])
    assert appels[0][0].endswith("/42/photos") and envoi["url"] == ["https://ex.com/photo.jpg"] and "link" not in envoi
    assert envoi["caption"][0].startswith("⚜️ Titre") and envoi["caption"][0].endswith("Source : AS")
    con.close()
print("OK threads")

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
          {"titre": "Predicted lineups", "resume": "", "source": "Managing Madrid", "lien": "c"}]
gardes, ecartes = g.trier(office)
assert [it["type"] for it in gardes] == ["info", "opinion"] and ecartes == [office[2]]
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
    g.enregistrer([{"id": 1, "section": "debats", "titre": "جديد", "texte": "ن", "tweets": ["فكرة"]}],
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
    assert chemin == "drafts" and corps["draft_title"] == "جديد" and posts[0]["media_ids"] == ["article-2.jpg"] and len(posts) == 2
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
    g.enregistrer([{"id": 1, "section": "actus", "titre": "خبر عاجل", "texte": "ن", "tweets": ["خبر"]}],
                  [{"lien": "https://as.com/3", "titre": "T3", "auteur": "", "source": "AS", "pays": "es", "type": "info"}], db)
    try:
        assert t.vers_typefully(con, {2: "c.png", 3: "c.png"}, Path(tmp)) == 2
    finally:
        t.CONFIG.pop("typefully_publish_at_actus")
    assert [c["draft_title"] for c in appels] == ["خبر عاجل", "جديد"] and appels[1]["publish_at"] == "next-free-slot"
    # publiée tout de suite, sans le tweet de crédit qui contient le lien (X refuse la publication immédiate avec lien)
    assert appels[0]["publish_at"] == "now" and [p["text"] for p in appels[0]["platforms"]["x"]["posts"]] == ["خبر"]
    assert t.sans_tweet_de_lien(["أ\n\n1/3", "ب\n\n2/3", "📰 AS\n🔗 المصدر: https://as.com/1\n\n3/3"]) == (["أ\n\n1/2", "ب\n\n2/2"], "now")
    from datetime import datetime as dt, timezone as tz
    tw, quand = t.sans_tweet_de_lien(["انظر https://x.com/a\n\n1/2", "📰 AS\n🔗 https://as.com/1\n\n2/2"])
    assert tw[0].startswith("انظر") and 60 < (dt.fromisoformat(quand) - dt.now(tz.utc)).total_seconds() <= 120  # lien ailleurs : programmé
    # un thread refusé (403) ne bloque plus les suivants, et la raison donnée par Typefully est affichée
    import contextlib
    import urllib.error
    con.execute("UPDATE threads SET typefully = NULL WHERE article_id = 2")
    con.commit()
    g.enregistrer([{"id": 1, "section": "debats", "titre": "ثالث", "texte": "ن", "tweets": ["فكرة ثالثة"]}],
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
    con.close()
print("OK Typefully")
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

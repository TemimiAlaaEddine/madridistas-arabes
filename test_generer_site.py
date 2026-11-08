"""Vérification rapide : python test_generer_site.py"""
import json
import tempfile
from pathlib import Path

import generer_site as g

g.EDGE = None  # pas de rendu d'images par Edge dans les tests (lent) ; le gabarit est testé à part

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
    c1, c2, c3 = g.couverture_html(a1), g.couverture_html(a2), g.couverture_html(a3)
    assert 'class="citation"' in c1 and "جملة &lt;قوية&gt;" in c1 and "<strong>أ</strong>" in c1 and "الصحافة الإسبانية" in c1
    assert 'class="chiffres"' in c2 and "<b>100</b>" in c2 and "<b>0,67</b>" in c2 and 'class="citation"' not in c2
    assert 'class="titre-actu"' in c3 and "خبر عاجل" in c3 and "#FEBE10" in c3
    g.generer_couvertures = lambda arts, dossier: {a["id"]: f"a-{a['id']}-test.png" for a in arts}  # simule Edge
    g.rendre_site(db, site)
    assert 'src="couvertures/a-2-test.png"' in (site / "index.html").read_text(encoding="utf-8")
    assert '<figure class="couverture"><img src="couvertures/a-1-test.png" alt="جملة &lt;قوية&gt;">' in \
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
assert len(th) == 3 and th[0].endswith("1/3") and "خوانما كاستانيو | Marca" in th[2] and "https://marca.com/a" in th[2]
assert t.assembler(art, ["ب" * 290]) is None and t.assembler(art, []) is None
with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "a.db"
    g.enregistrer([{"id": 1, "section": "debats", "titre": "ع", "texte": "ن"}],
                  [{"lien": "https://ex.com/t", "titre": "T", "auteur": "", "source": "Marca", "pays": "es"}], db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    t.appeler_claude = lambda prompt, *a: '[{"id": 1, "tweets": ["فكرة"]}, {"id": 99, "tweets": ["x"]}]'
    assert t.decouper(con) == 1 and t.decouper(con) == 0  # id inconnu ignoré, pas de second thread
    envoyes = []
    t.CONFIG.update(telegram_token="x", telegram_chat_id="1")
    t.telegram = lambda methode, champs, fichier=None: envoyes.append((methode, champs.get("text") or champs["caption"]))
    assert t.envoyer(con, {1: "c.png"}, Path(tmp), {"debats": "نقاشات"}) == 1 and t.envoyer(con, {}, Path(tmp)) == 0
    # couverture et en-tête fusionnés, avec le nom de la rubrique
    assert len(envoyes) == 3 and envoyes[0][0] == "sendPhoto" and envoyes[0][1].startswith("🧵 نقاشات (2 تغريدات)")
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
    t.typefully_image = lambda f: "m1"
    t.typefully_api = lambda chemin, corps=None: appels.append((chemin, corps)) or {"id": 77}
    t.reglage = lambda cle: "cle" if cle == "typefully_api_key" else None
    t.CONFIG["typefully_social_set"] = 1
    t.CONFIG["typefully_publish_at"] = "next-free-slot"
    assert t.vers_typefully(con, {2: "c.png"}, Path(tmp)) == 1 and t.vers_typefully(con, {}, Path(tmp)) == 0
    (chemin, corps), = appels
    posts = corps["platforms"]["x"]["posts"]
    assert corps["publish_at"] == "next-free-slot"  # file d'attente : publié seul au prochain créneau
    assert chemin == "drafts" and corps["draft_title"] == "جديد" and posts[0]["media_ids"] == ["m1"] and len(posts) == 2
    assert dict(con.execute("SELECT article_id, typefully FROM threads").fetchall()) == {1: "avant", 2: "77"}
    con.execute("UPDATE threads SET typefully = NULL WHERE article_id = 2")
    def coupe(*a, **k):
        raise OSError("réseau coupé")
    t.typefully_api = coupe
    assert t.vers_typefully(con, {}, Path(tmp)) == 0
    assert con.execute("SELECT typefully FROM threads WHERE article_id = 2").fetchone()[0] is None
    con.close()
print("OK Typefully")

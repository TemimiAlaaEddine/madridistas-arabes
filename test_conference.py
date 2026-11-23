"""Tests de conference.py (direct de conférence) et de son effet sur l'envoi des threads (threads.vers_typefully)."""
import json
import sqlite3
import sys
from datetime import datetime, timedelta

import conference as c
import generer_site
import threads as t

sys.stdout.reconfigure(encoding="utf-8")

# titres de Marca et AS : la forme « Mourinho: "..." » est une déclaration
assert c.est_declaration('Mourinho: "Es más fácil jugar con el apoyo del Bernabéu"')
assert c.est_declaration("José Mourinho: “Después del 1-1 fue una avalancha”")
assert not c.est_declaration("Mourinho y por qué Mbappé y Espí no pueden jugar más juntos")
# titres de la conférence du 23 nov., manqués par la première version
assert c.est_declaration("Mourinho responde a Santi Comesaña: “Tiene amnesia”")
assert c.est_declaration('Mourinho y el calendario: "Es un conflicto, pero al final es el plin plin"')
assert not c.est_declaration("Mourinhista de corazón")
assert not c.est_declaration('Carlos Espí: "Estaba agachado"')
assert c.est_declaration("“Es un grupo de amigos”", "Mourinho, en rueda de prensa tras el partido")  # forme d'AS
assert not c.est_declaration("“El banquillo del Real Madrid nos ha matado”", "El técnico del Celta, tras la derrota")
print("OK déclarations")

# lancement : le premier journal à publier une déclaration fraîche ; rien si un direct a déjà eu lieu pour cette conférence
T0 = datetime(2026, 11, 23, 12, 0)
vrai = (c.declarations, c.lire_etat, c.deja_publies, c.tweet, generer_site.texte_complet, c.tweet_de_fin)
vrai_fin = c.tweet_de_fin
c.tweet_de_fin = lambda utc: "🎙️ نهاية"  # sans appel à Claude (nom arabe de l'adversaire)
import calendrier
vrai_actif = calendrier.direct_actif
calendrier.direct_actif = lambda w="": False
import tempfile
from pathlib import Path
_tmp = tempfile.TemporaryDirectory()
vrai_fichier = calendrier.FICHIER
calendrier.FICHIER = Path(_tmp.name) / "matchs.json"
calendrier.FICHIER.write_text("[]", encoding="utf-8")
# calendrier du club : entraînement de 11 h (10 h UTC) suivi d'une conférence, comme le 23 nov.
CAL = ('"dateTime":"2026-11-23T10:00:00.000Z","dateTxt":null,"eventLocation":"Ciudad Real Madrid","tv":{"html":"\\u003Cp>Rueda de '
       'prensa:&nbsp;sí, Mourinho y un jugador, después del entrenamiento (en directo por Realmadrid TV).\\u003C\\u002Fp>\\n"},'
       '"dateTime":"2026-11-22T10:00:00.000Z","dateTxt":null,"eventLocation":"Ciudad Real Madrid","tv":{"html":"\\u003Cp>Rueda de prensa: no\\u003C\\u002Fp>"}')
assert calendrier.conferences(CAL, datetime(2026, 11, 20)) == [datetime(2026, 11, 23, 10)]
try:
    c.lire_etat = lambda: []
    c.declarations = lambda j, depuis: {"Marca": [(T0 - timedelta(minutes=3), "Mourinho: «a»", "m1", "")],
                                        "AS": [(T0 - timedelta(minutes=8), "Mourinho: «b»", "a1", "")]}[j]
    assert c.a_lancer(T0, page="") == "auto", "une déclaration : direct lancé, journal choisi à la première vraie déclaration"
    # avant-match : lancé jusqu'à 45 min avant l'entraînement (le calendrier le retire dès qu'il commence)
    assert c.a_lancer(datetime(2026, 11, 23, 9, 20), page=CAL) == "auto 2026-11-23T10:00:00"
    c.declarations = lambda j, depuis: []
    assert c.a_lancer(datetime(2026, 11, 23, 9, 10), page=CAL) == "", "plus de 45 min avant : trop tôt"
    assert c.a_lancer(T0, page="") == ""
    # après-match programmé : lancé de 45 min avant la fin du match (coup d'envoi + 1 h 45) à 1 h 30 après, avec l'heure de fin
    c.declarations = lambda j, depuis: []
    calendrier.FICHIER.write_text(json.dumps([{"match": "Real Madrid vs PSV", "debut": "2026-11-24T20:00:00", "heure_fixee": True}]), encoding="utf-8")
    assert c.a_lancer(datetime(2026, 11, 24, 21, 5), page="") == "auto 2026-11-24T21:45:00"
    assert c.a_lancer(datetime(2026, 11, 24, 23, 0), page="") == "auto 2026-11-24T21:45:00", "lancé en retard : encore utile"
    assert c.a_lancer(datetime(2026, 11, 24, 20, 55), page="") == "" and c.a_lancer(datetime(2026, 11, 24, 23, 20), page="") == ""
    assert c.apres_match(datetime(2026, 11, 24, 21, 45)), "heure de fin : attente d'après-match (1 h 30)"
    # après-match sans heure fixée : seule une déclaration venue de la salle de presse lance le direct (l'interview Movistar
    # passe par le passage normal)
    calendrier.FICHIER.write_text(json.dumps([{"match": "Real Madrid vs PSV", "debut": "2026-11-23T10:00:00", "heure_fixee": False}]), encoding="utf-8")
    c.declarations = lambda j, depuis: [(T0, "Mourinho: «a»", "m1", "a Movistar")] if j == "Marca" else []
    vrai_salle = c.en_salle_de_presse
    c.en_salle_de_presse = lambda lien, resume: "Movistar" not in resume
    assert c.a_lancer(T0, page="") == "", "interview télé : pas de direct"
    c.declarations = lambda j, depuis: [(T0, "Mourinho: «a»", "m1", "en rueda de prensa")] if j == "Marca" else []
    assert c.a_lancer(T0, page="") == "auto"
    c.en_salle_de_presse = vrai_salle
    calendrier.FICHIER.write_text("[]", encoding="utf-8")
    c.declarations = lambda j, depuis: [(T0, "Mourinho: «a»", "m1", "")] if j == "Marca" else []
    c.lire_etat = lambda: [{"journal": "AS", "debut": (T0 - timedelta(hours=1)).isoformat(), "liens": [], "tweets": ["x"], "fini": True}]
    assert c.a_lancer(T0, page="") == "", "même conférence : pas de second direct"
    c.lire_etat = lambda: [{"journal": None, "debut": (T0 - timedelta(hours=1)).isoformat(), "liens": [], "tweets": [], "fini": True}]
    assert c.a_lancer(T0, page="") == "auto", "faux départ (aucun tweet) : il ne bloque pas le vrai direct (23 nov.)"
    c.lire_etat = lambda: [{"journal": None, "debut": (T0 - timedelta(hours=1)).isoformat(), "liens": [], "vus": ["m1"], "tweets": [], "fini": True}]
    assert c.a_lancer(T0, page="") == "", "article déjà vu, republié avec une date fraîche : pas de direct (23 nov.)"
    c.lire_etat = lambda: [{"journal": "AS", "debut": (T0 - timedelta(hours=1)).isoformat(), "liens": [], "fini": True}]
    assert c.session_recente(T0)["journal"] == "AS" and not c.en_direct(T0)
    c.lire_etat = lambda: [{"journal": None, "debut": (T0 - timedelta(hours=1)).isoformat(), "liens": [], "fini": False}]
    assert not c.en_direct(T0), "attente de la conférence : pas encore en direct"
    c.lire_etat = lambda: [{"journal": "AS", "debut": (T0 - timedelta(hours=7)).isoformat(), "liens": [], "fini": True}]
    assert c.a_lancer(T0, page="") == "auto" and c.session_recente(T0) is None
    print("OK lancement")

    # boucle : chaque nouvelle déclaration une fois, doublon écarté, déjà publiée par le passage ignorée, fin après 10 min de silence
    horloge = [T0]
    flux = {0: [], 2: [(T0, "Mourinho: «1»", "m1", "")], 4: [(T0, "Mourinho: «1»", "m1", ""), (T0, "Mourinho: «2»", "m2", "")],
            6: [(T0, "Mourinho: «1»", "m1", ""), (T0, "Mourinho: «2»", "m2", ""), (T0, "Mourinho: «3»", "m3", ""), (T0, "Mourinho: «0»", "m0", "")]}
    c.declarations = lambda j, depuis: flux[max(k for k in flux if k <= (horloge[0] - T0).total_seconds() / 60)]
    c.deja_publies = lambda depuis: (["m0"], ["🎙️ مؤتمر مورينيو | «0»"])
    c.tweet = lambda titre, texte, deja: "DOUBLON" if "«2»" in titre else f"🎙️ مؤتمر مورينيو | {titre[10:]}"
    generer_site.texte_complet = lambda it: "نص"
    sauvegardes = []
    def dormir(s):
        horloge[0] += timedelta(seconds=s)
    s = c.suivre("Marca", publier=False, dormir=dormir, horloge=lambda: horloge[0],
                 sauvegarder=lambda etat, m: sauvegardes.append((m, json.dumps(etat[-1]))))
    assert s["tweets"] == ["🎙️ مؤتمر مورينيو | «0»", "🎙️ مؤتمر مورينيو | «1»", "🎙️ مؤتمر مورينيو | «3»"], s["tweets"]
    assert s["liens"] == ["m0", "m1", "m2", "m3"] and s["fini"] and s["journal"] == "Marca"
    assert 15 <= (horloge[0] - T0).total_seconds() / 60 <= 18, "fin 10 min après la dernière déclaration (min 6)"
    assert sauvegardes[0][0].endswith("suivie sur Marca") and "fin" in sauvegardes[-1][0]
    print("OK boucle")

    # « auto » (avant-match) : attente sans fin de silence, l'interview hors conférence laissée au passage normal, puis le
    # premier journal à publier une déclaration est suivi seul
    horloge[0] = T0
    flux_auto = {0: [], 30: [(T0, "Mourinho: «tv»", "m-tv", "")], 50: [(T0, "Mourinho: «tv»", "m-tv", ""), (T0, "Mourinho: «x»", "a-x", "")]}
    def decl_auto(j, depuis):
        lot = flux_auto[max(k for k in flux_auto if k <= (horloge[0] - T0).total_seconds() / 60)]
        return [d for d in lot if (d[2].startswith("a-") if j == "AS" else d[2].startswith("m-"))] + \
               ([(T0, "Mourinho: «m»", "m-z", "")] if j == "Marca" and (horloge[0] - T0).total_seconds() >= 52 * 60 else [])
    c.declarations = decl_auto
    c.deja_publies = lambda depuis: ([], [])
    c.tweet = lambda titre, texte, deja: "HORS" if "«tv»" in titre else f"🎙️ مؤتمر مورينيو | {titre[10:]}"
    s = c.suivre("auto", publier=False, dormir=dormir, horloge=lambda: horloge[0], sauvegarder=lambda etat, m: None, heure=T0)
    assert s["journal"] == "AS" and s["tweets"] == ["🎙️ مؤتمر مورينيو | «x»"], s
    assert "m-tv" in s["vus"] and "m-tv" not in s["liens"] and "m-z" not in s["vus"], "Marca ignoré une fois AS choisi"
    assert 60 <= (horloge[0] - T0).total_seconds() / 60 <= 62, "pas de fin de silence pendant l'attente (50 min), puis 10 min"
    horloge[0] = T0 - timedelta(minutes=40)
    c.declarations = lambda j, depuis: []
    s = c.suivre("auto", publier=False, dormir=dormir, horloge=lambda: horloge[0], sauvegarder=lambda etat, m: None, heure=T0)
    assert s["debut"] == T0.isoformat(), "attend l'heure de l'entraînement avant de commencer"
    assert not s["tweets"] and (horloge[0] - T0) == c.ATTENTE and s["journal"] is None, "pas de conférence : fin de l'attente"
    horloge[0] = T0  # lancé sur un article (vidéo d'entraînement du 23 nov.) : 30 min d'attente d'une vraie déclaration, pas 10
    c.declarations = lambda j, depuis: [(T0, "“Dean, estás dormido”", "a-video", "Mourinho")] if j == "AS" else []
    c.tweet = lambda titre, texte, deja: "HORS"
    s = c.suivre("auto", publier=False, dormir=dormir, horloge=lambda: horloge[0], sauvegarder=lambda etat, m: None)
    assert not s["tweets"] and s["journal"] is None and (horloge[0] - T0) == c.ATTENTE_DETECTION
    print("OK attente avant-match")

    # après-match programmé : attend la fin du match, puis 1 h 30 au plus (pas 3 h 30)
    FIN = datetime(2026, 11, 24, 21, 45)
    calendrier.FICHIER.write_text(json.dumps([{"match": "Real Madrid vs PSV", "debut": "2026-11-24T20:00:00", "heure_fixee": True}]), encoding="utf-8")
    horloge[0] = FIN - timedelta(minutes=10)
    c.declarations = lambda j, depuis: []
    s = c.suivre("auto", publier=False, dormir=dormir, horloge=lambda: horloge[0], sauvegarder=lambda etat, m: None, heure=FIN)
    assert s["debut"] == FIN.isoformat() and (horloge[0] - FIN) == c.ATTENTE_APRES and not s["tweets"]
    calendrier.FICHIER.write_text("[]", encoding="utf-8")
    print("OK attente après-match")

    # tweet de fin : avant le prochain match, ou après le match commencé il y a moins de 6 h
    vrai_cal = (calendrier.FICHIER, calendrier.nom_arabe_claude)
    with tempfile.TemporaryDirectory() as tmp:
        calendrier.FICHIER = Path(tmp) / "matchs.json"
        calendrier.FICHIER.write_text(json.dumps([{"match": "Real Madrid vs Celta de Vigo", "debut": "2026-11-21T20:00:00", "heure_fixee": True},
                                                  {"match": "Real Madrid vs PSV", "debut": "2026-11-24T20:00:00", "heure_fixee": True}]), encoding="utf-8")
        calendrier.nom_arabe_claude = lambda n: {"PSV": "آيندهوفن", "Celta de Vigo": "سيلتا فيغو"}[n]
        try:
            assert vrai_fin(datetime(2026, 11, 23, 12)) == "🎙️ نهاية المؤتمر الصحفي لمورينيو قبل مباراة ريال مدريد وآيندهوفن\n\n#مورينيو #ريال_مدريد"
            assert "بعد مباراة ريال مدريد وسيلتا فيغو" in vrai_fin(datetime(2026, 11, 21, 22, 30))
            calendrier.FICHIER.write_text("[]", encoding="utf-8")
            assert vrai_fin(datetime(2026, 11, 23, 12)).startswith("🎙️ نهاية المؤتمر الصحفي لمورينيو\n")
        finally:
            calendrier.FICHIER, calendrier.nom_arabe_claude = vrai_cal

    # publication : photo sur le 1er tweet seulement, puis le tweet de fin
    horloge[0] = T0
    c.deja_publies = lambda depuis: ([], [])
    c.declarations = lambda j, depuis: flux[max(k for k in flux if k <= (horloge[0] - T0).total_seconds() / 60)]
    c.tweet = lambda titre, texte, deja: "DOUBLON" if "«2»" in titre else f"🎙️ مؤتمر مورينيو | {titre[10:]}"
    def texte_avec_image(it):
        it["image"] = "https://marca.com/photo.jpg"
        return "نص"
    generer_site.texte_complet = texte_avec_image
    vrais_t = (t.typefully_api, t.telecharger_image, t.typefully_image)
    posts = []
    t.typefully_api = lambda chemin, corps=None: (posts.append(corps["platforms"]["x"]["posts"][0]), {"id": 1})[1]
    t.telecharger_image, t.typefully_image = (lambda u, i: ("a.jpg", b"")), (lambda n, b: "media1")
    try:
        c.suivre("Marca", dormir=dormir, horloge=lambda: horloge[0], sauvegarder=lambda etat, m: None)
    finally:
        t.typefully_api, t.telecharger_image, t.typefully_image = vrais_t
    assert [p.get("media_ids") for p in posts] == [["media1"], None, None, None], posts
    assert posts[-1]["text"] == "🎙️ نهاية" and len(posts) == 4, "3 déclarations (0, 1, 3) puis la fin"
    print("OK photo et fin")
finally:
    c.declarations, c.lire_etat, c.deja_publies, c.tweet, generer_site.texte_complet, c.tweet_de_fin = vrai
    calendrier.direct_actif = vrai_actif
    calendrier.FICHIER = vrai_fichier

# passage principal pendant le direct : articles du journal suivi laissés au direct, autre journal et déjà tweetés écartés,
# autres nouvelles retenues jusqu'à la fin du direct
con = sqlite3.connect(":memory:")
con.row_factory = sqlite3.Row
con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, section TEXT, mode TEXT, journal TEXT, lien TEXT, titre TEXT, image TEXT, galerie TEXT)")
t.connexion_threads(con)
for i, mode, journal, lien in ((1, "conference", "Marca", "m1"), (2, "conference", "Marca", "m9"), (3, "conference", "AS", "a1"),
                               (4, "info", "El País", "p1")):
    con.execute("INSERT INTO articles VALUES (?, 'actus', ?, ?, ?, 't', NULL, NULL)", (i, mode, journal, lien))
    con.execute("INSERT INTO threads (article_id, tweets, statut, date) VALUES (?, ?, 'a_envoyer', '2026-11-23T12:00:00')",
                (i, json.dumps(["🎙️ مؤتمر مورينيو | «x»" if mode == "conference" else "📰 خبر | y\n\n(الباييس)"])))
envois = []
vrais = (t.typefully_api, t.reglage, c.session_recente, c.en_direct, calendrier.direct_actif, t.images_thread, t.telecharger_image, t.typefully_image)
t.images_thread, t.telecharger_image, t.typefully_image = (lambda a: ["u"]), (lambda u, i: ("a.jpg", b"")), (lambda n, b: "m")
t.typefully_api = lambda chemin, corps=None: (envois.append(corps), {"id": 1})[1]
t.reglage = lambda cle: "k"
t.CONFIG["typefully_social_set"] = t.CONFIG.get("typefully_social_set") or 1
calendrier.direct_actif = lambda w="": False
try:
    c.session_recente = lambda utc=None: {"journal": "Marca", "liens": ["m1"], "fini": False}
    c.en_direct = lambda utc=None: True
    assert t.vers_typefully(con, {}, None) == 0 and not envois
    statuts = {r[0]: (r[1], r[2]) for r in con.execute("SELECT article_id, typefully, statut FROM threads")}
    assert statuts[1] == ("sans", "bloqué : publiée en direct") and statuts[3] == ("sans", "bloqué : conférence suivie sur Marca")
    assert statuts[2][0] is None and statuts[4][0] is None, "laissés au direct / retenus pendant le direct"
    # direct fini : la nouvelle retenue part, la déclaration que le direct a manquée aussi
    c.en_direct = lambda utc=None: False
    c.session_recente = lambda utc=None: {"journal": "Marca", "liens": ["m1"], "fini": True}
    t.vers_typefully(con, {}, None)
    assert {r[0] for r in con.execute("SELECT article_id FROM threads WHERE typefully = '1'")} == {2, 4}
    # workflow lancé mais conference.json pas encore là : les articles de conférence de Marca/AS attendent le direct, les
    # autres nouvelles partent (la conférence n'a pas forcément commencé)
    con.execute("UPDATE threads SET typefully = NULL, statut = 'a_envoyer'")
    c.session_recente, calendrier.direct_actif = (lambda utc=None: None), (lambda w="": True)
    assert t.vers_typefully(con, {}, None) == 1
    assert {r[0] for r in con.execute("SELECT article_id FROM threads WHERE typefully = '1'")} == {4}
    con.execute("UPDATE threads SET typefully = NULL, statut = 'a_envoyer'")
    # attente de la conférence (avant-match) : Marca/AS laissés au direct, les autres nouvelles partent ; un article jugé
    # hors conférence par le direct (interview télé) part aussi par le passage normal
    calendrier.direct_actif = lambda w="": True  # le workflow tourne, mais conference.json dit « en attente » : pas de rétention
    c.session_recente = lambda utc=None: {"journal": None, "liens": [], "vus": ["a1"], "fini": False}
    c.en_direct = lambda utc=None: False
    t.vers_typefully(con, {}, None)
    assert {r[0] for r in con.execute("SELECT article_id FROM threads WHERE typefully = '1'")} == {3, 4}, \
        "El País (4) et l'interview AS hors conférence (3) partent ; Marca (1, 2) attend le direct"
finally:
    (t.typefully_api, t.reglage, c.session_recente, c.en_direct, calendrier.direct_actif, t.images_thread, t.telecharger_image,
     t.typefully_image) = vrais
print("OK passage pendant le direct")

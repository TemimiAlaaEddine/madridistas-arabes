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
assert not c.est_declaration('Carlos Espí: "Estaba agachado"')
assert c.est_declaration("“Es un grupo de amigos”", "Mourinho, en rueda de prensa tras el partido")  # forme d'AS
assert not c.est_declaration("“El banquillo del Real Madrid nos ha matado”", "El técnico del Celta, tras la derrota")
print("OK déclarations")

# lancement : le premier journal à publier une déclaration fraîche ; rien si un direct a déjà eu lieu pour cette conférence
T0 = datetime(2026, 11, 23, 12, 0)
vrai = (c.declarations, c.lire_etat, c.deja_publies, c.tweet, generer_site.texte_complet)
import calendrier
vrai_actif = calendrier.direct_actif
calendrier.direct_actif = lambda w="": False
try:
    c.lire_etat = lambda: []
    c.declarations = lambda j, depuis: {"Marca": [(T0 - timedelta(minutes=3), "Mourinho: «a»", "m1", "")],
                                        "AS": [(T0 - timedelta(minutes=8), "Mourinho: «b»", "a1", "")]}[j]
    assert c.a_lancer(T0) == "AS", "AS a publié le premier"
    c.declarations = lambda j, depuis: []
    assert c.a_lancer(T0) == ""
    c.declarations = lambda j, depuis: [(T0, "Mourinho: «a»", "m1", "")] if j == "Marca" else []
    c.lire_etat = lambda: [{"journal": "AS", "debut": (T0 - timedelta(hours=1)).isoformat(), "liens": [], "fini": True}]
    assert c.a_lancer(T0) == "", "même conférence : pas de second direct"
    assert c.session_recente(T0)["journal"] == "AS" and not c.en_direct(T0)
    c.lire_etat = lambda: [{"journal": "AS", "debut": (T0 - timedelta(hours=4)).isoformat(), "liens": [], "fini": True}]
    assert c.a_lancer(T0) == "Marca" and c.session_recente(T0) is None
    print("OK lancement")

    # boucle : chaque nouvelle déclaration une fois, doublon écarté, déjà publiée par le passage ignorée, fin après 20 min de silence
    horloge = [T0]
    flux = {0: [], 2: [(T0, "Mourinho: «1»", "m1", "")], 4: [(T0, "Mourinho: «1»", "m1", ""), (T0, "Mourinho: «2»", "m2", "")],
            6: [(T0, "Mourinho: «1»", "m1", ""), (T0, "Mourinho: «2»", "m2", ""), (T0, "Mourinho: «3»", "m3", ""), (T0, "Mourinho: «0»", "m0", "")]}
    c.declarations = lambda j, depuis: flux[max(k for k in flux if k <= (horloge[0] - T0).total_seconds() / 60)]
    c.deja_publies = lambda depuis: (["m0"], ["🎙️ مؤتمر مورينيو | «0»"])
    c.tweet = lambda titre, texte, deja: None if "«2»" in titre else f"🎙️ مؤتمر مورينيو | {titre[10:]}"
    generer_site.texte_complet = lambda it: "نص"
    sauvegardes = []
    def dormir(s):
        horloge[0] += timedelta(seconds=s)
    s = c.suivre("Marca", publier=False, dormir=dormir, horloge=lambda: horloge[0],
                 sauvegarder=lambda etat, m: sauvegardes.append((m, json.dumps(etat[-1]))))
    assert s["tweets"] == ["🎙️ مؤتمر مورينيو | «0»", "🎙️ مؤتمر مورينيو | «1»", "🎙️ مؤتمر مورينيو | «3»"], s["tweets"]
    assert s["liens"] == ["m0", "m1", "m2", "m3"] and s["fini"] and s["journal"] == "Marca"
    assert 25 <= (horloge[0] - T0).total_seconds() / 60 <= 28, "fin 20 min après la dernière déclaration (min 6)"
    assert sauvegardes[0][0].endswith("suivie sur Marca") and "fin" in sauvegardes[-1][0]
    print("OK boucle")
finally:
    c.declarations, c.lire_etat, c.deja_publies, c.tweet, generer_site.texte_complet = vrai
    calendrier.direct_actif = vrai_actif

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
    # workflow lancé mais conference.json pas encore là : tout ce qui touche Marca/AS et les nouvelles attendent
    con.execute("UPDATE threads SET typefully = NULL, statut = 'a_envoyer'")
    c.session_recente, calendrier.direct_actif = (lambda utc=None: None), (lambda w="": True)
    envois.clear()
    assert t.vers_typefully(con, {}, None) == 0 and not envois
finally:
    (t.typefully_api, t.reglage, c.session_recente, c.en_direct, calendrier.direct_actif, t.images_thread, t.telecharger_image,
     t.typefully_image) = vrais
print("OK passage pendant le direct")

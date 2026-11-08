#!/usr/bin/env python3
"""Madridistas arabes - site statique d'articles d'opinion sur le Real Madrid, en arabe.

Collecte (flux de config.json) -> articles (hors Google News) -> lecture du texte complet ->
Claude rédige un résumé commenté (ou une traduction si la source a donné son
autorisation : "autorisation": true dans config.json) -> articles.db -> pages HTML dans site/.

Usage :
  python generer_site.py            # collecte + rédaction + régénère le site
  python generer_site.py --test     # montre les articles retenus, sans Claude
  python generer_site.py --rendre   # régénère seulement les pages (après une retouche du CSS...)
  python generer_site.py --threads  # régénère les pages, puis prépare et envoie les threads X sur Telegram
"""
import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from itertools import zip_longest
from datetime import datetime
from html.parser import HTMLParser

import threads
from insider import BASE, CONFIG, appeler_claude, collecter, dedoublonner, extraire_json, marquer_vus, nettoyer

DB = BASE / "articles.db"
SITE = BASE / "site"
NOM_SITE = "المدريديستا علاء"

SECTIONS = {"actus": "أخبار", "tactique": "تحليلات تكتيكية", "mercato": "سوق الانتقالات", "club": "النادي والأعمال", "debats": "نقاشات"}
PAYS = {
    "es": "الصحافة الإسبانية", "gb": "الصحافة الإنجليزية", "fr": "الصحافة الفرنسية", "us": "الصحافة الأمريكية",
    "de": "الصحافة الألمانية", "it": "الصحافة الإيطالية", "pt": "الصحافة البرتغالية", "nl": "الصحافة الهولندية",
    "be": "الصحافة البلجيكية", "br": "الصحافة البرازيلية", "uy": "الصحافة الأوروغويانية", "tr": "الصحافة التركية",
    "ma": "الصحافة المغربية", "ci": "الصحافة الإيفوارية",
}
PERSONNES = CONFIG.get("personnes", {})
CREDITS = BASE / "photos.json"  # photos libres déjà récupérées : {cle: {fichier, auteur, licence...} ou null}
UA = {"User-Agent": "MadridistasArabes/1.0 (projet personnel)"}  # Wikimedia refuse les requêtes sans User-Agent


# ---------- texte complet de l'article ----------
class Paragraphes(HTMLParser):
    """Récupère le texte des balises <p> d'une page, hors scripts et styles."""

    def __init__(self):
        super().__init__()
        self.dans_p = self.ignore = 0
        self.courant, self.morceaux = [], []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignore += 1
        elif tag == "p":
            self.dans_p, self.courant = 1, []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.ignore = max(0, self.ignore - 1)
        elif tag == "p" and self.dans_p:
            self.dans_p = 0
            t = " ".join("".join(self.courant).split())
            if len(t) > 60:  # écarte légendes, boutons, mentions
                self.morceaux.append(t)

    def handle_data(self, data):
        if self.dans_p and not self.ignore:
            self.courant.append(data)


def texte_complet(it):
    """Texte de la page si elle est lisible, sinon celui du flux (le plus long des deux), coupé selon le type :
    une info tient dans son début ; une longue opinion garde son début (thèse) et sa fin (conclusion)."""
    page = ""
    try:
        req = urllib.request.Request(it["lien"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            p = Paragraphes()
            p.feed(r.read().decode("utf-8", "replace"))
        page = "\n".join(p.morceaux)
    except Exception as err:  # noqa: BLE001 - page bloquée (403, abonnement...) : on garde le flux
        print(f"  ! page illisible ({err}) : {it['lien'][:70]}")
    texte = max(page, it.get("texte_flux", ""), key=len)
    if it.get("type") == "info":
        return texte[:4000]
    if it.get("type") == "conference":  # toutes les réponses de l'entraîneur, sans couper le milieu
        return texte[:12000]
    return texte if len(texte) <= 8000 else texte[:6500] + "\n[…]\n" + texte[-1500:]


# ---------- prompt ----------
PROMPT = """Tu es le rédacteur d'un site arabophone qui fait découvrir au public arabe (Moyen-Orient et Afrique du Nord) ce que la presse internationale écrit sur le Real Madrid (football masculin) : surtout ses articles d'opinion, et ses informations importantes.

Pour chaque article ci-dessous :
1. Décide de sa nature :
   - Opinion : article d'opinion, chronique, analyse ou éditorial centré sur le Real Madrid, y compris chronique d'après-match et notes des joueurs (uno a uno, aprobados y suspensos).
   - Information importante sur le Real Madrid : blessure ou retour, transfert ou contrat, déclaration marquante, décision du club ou d'une instance, distinction, résultat final d'un match du Real Madrid (score et buteurs), composition officielle d'un match du Real Madrid (le onze titulaire annoncé avant le coup d'envoi), et aussi les anecdotes et coulisses (vie des joueurs, vestiaire, réseaux sociaux, curiosités, histoire du club).
   - À ignorer : pronostics et paris, horaires TV, compositions probables (sauf celles de Marca et AS, à garder ; garde aussi la composition officielle), directs et faits de jeu pendant un match, autres clubs ou autres sports.
   - Doublons : si plusieurs articles de cette liste rapportent le même fait ou les mêmes propos d'une même personne (même dans des médias ou des langues différents), n'en garde qu'un seul, le plus complet. Idem s'il est déjà dans la liste « DÉJÀ PUBLIÉ » plus bas.
2. Classe-le dans une section : actus pour toute information ; pour une opinion : tactique (jeu, système, rendement des joueurs), mercato (transferts, contrats, recrutement), club (finances, présidence, stade, institutions, droits TV), debats (polémiques et actualité commentée).
3. Rédige en arabe standard moderne, clair et soigné :
   - Information (actus) : 120 à 200 mots, uniquement les faits, avec le contexte utile tiré du texte, en citant le média (وفقًا لصحيفة ماركا...). Si l'information n'est pas confirmée, utilise une formule de prudence (حسب ما ذكرت...). Pas de citation de plus de 15 mots. Pour une composition officielle ou probable (Marca, AS) : les 11 titulaires (noms arabes usuels) et l'adversaire, sans limite de mots, en précisant si elle est officielle ou probable.
   - Opinion, selon le « Mode » indiqué :
     - Mode résumé : un article de 400 à 600 mots qui expose la thèse, chacun des arguments et la conclusion de l'auteur avec tes propres mots, à la troisième personne (يرى الكاتب...). Au maximum 4 citations courtes traduites (moins de 25 mots chacune) entre guillemets «». Ne traduis pas l'article phrase par phrase.
     - Mode traduction : traduction intégrale et fidèle du texte fourni.
   - Mode conférence (conférence de presse d'un entraîneur, section actus) : traduis fidèlement et intégralement toutes les déclarations de l'entraîneur présentes dans le texte (la limite de 15 mots ne s'applique pas), sans reprendre les phrases du journaliste. Présente-les par sujet : chaque sujet commence par la question ou le thème résumé en une ligne, suivi de ses réponses entre guillemets «». Une phrase d'introduction : qui parle, quand, avant ou après quel match.
4. N'ajoute aucun fait ni aucun avis absent du texte. L'avis est celui de l'auteur, jamais celui du site, du média ou du club.
5. Auteur : s'il est indiqué « inconnu », cherche la signature dans le texte ; si tu ne la trouves pas, laisse "auteur" vide. Donne le nom tel qu'il est écrit ("auteur") et translittéré en arabe ("auteur_ar").
   Si l'article rapporte surtout l'avis d'un commentateur (radio, télévision, podcast, entretien) plutôt que celui de son auteur, mets ce commentateur dans "auteur"/"auteur_ar", présente l'avis comme le sien, et indique en "via" le média où il s'est exprimé, en arabe (ex. : راديو ماركا). Sinon laisse "via" vide.
6. Liste les personnes dont parle l'article, la principale en premier, uniquement parmi ces clés : {personnes}
   "sujet" : la clé de la personne dont l'article parle principalement, seulement si elle est dans cette liste ; sinon "" (ex. : article centré sur un joueur absent de la liste, ou sur le club en général).
7. "citation" : la phrase la plus forte de ton texte arabe (idée centrale ou formule marquante), 8 à 20 mots, sans guillemets. Pour une information : le fait principal en une phrase.
8. "chiffres" : seulement si l'article repose sur des chiffres marquants (statistiques, montants, records), jusqu'à 3 objets {{"valeur": "100", "libelle": "هدف بقميص ريال مدريد"}} : valeur courte (ex. "61,3%", "180 م€"), libellé arabe de 2 à 6 mots, tirés du texte. Sinon [].
9. "tweets" : le thread X (Twitter) tiré de ton texte arabe, pour le compte « المدريديستا علاء » :
{regles_tweets}
10. "titres_fb" : ton titre arabe traduit pour un groupe Facebook de supporters à Montréal, une phrase courte et naturelle en français, en anglais et en espagnol, noms propres dans leur graphie latine usuelle.

FORMAT DE RÉPONSE
Réponds UNIQUEMENT avec un tableau JSON valide, sans texte avant ni après, sans bloc de code :
[{{"id": 1, "section": "actus|tactique|mercato|club|debats", "titre": "...", "chapeau": "جملة أو جملتان", "texte": "paragraphes séparés par \\n\\n", "auteur": "...", "auteur_ar": "...", "via": "", "personnes": ["mbappe"], "sujet": "mbappe", "citation": "...", "chiffres": [], "tweets": ["...", "..."], "titres_fb": {{"fr": "...", "en": "...", "es": "..."}}}}]
Si aucun article ne convient, réponds [].

DÉJÀ PUBLIÉ CES DERNIERS JOURS (informations et propos à ne pas reprendre, sauf fait vraiment nouveau)
{deja}

ARTICLES
{articles}
"""


def journal(it):
    return it["source"].split(" - ")[0]  # "Marca - Opinion" -> "Marca"


def construire_prompt(items, deja=()):
    blocs = []
    for i, it in enumerate(items, 1):
        mode = "traduction" if it.get("autorise") else "conférence" if it.get("type") == "conference" else "résumé"
        blocs.append(f"[{i}] Journal : {journal(it)}\nAuteur : {it['auteur'] or 'inconnu'}\nMode : {mode}\n"
                     f"Titre : {it['titre']}\nTexte :\n{it['texte']}")
    personnes = ", ".join(f"{k} ({v})" for k, v in PERSONNES.items())
    deja = "\n".join(f"- {t}" for t in deja) or "(aucune)"
    return PROMPT.format(personnes=personnes, deja=deja, articles="\n\n".join(blocs), regles_tweets=threads.REGLES)


def deja_publies(chemin=DB, jours=2):
    """Titres d'origine des articles récents de toutes sections, pour que Claude ne publie pas deux fois
    la même information ni les mêmes propos (ex. une déclaration reprise par Marca et Foot Mercato).
    Titres d'origine seulement : moins de tokens que l'arabe, et Claude rapproche les langues tout seul."""
    con = connexion(chemin)
    lignes = con.execute("SELECT titre_original FROM articles WHERE date >= date('now', ?)",
                         (f"-{jours} days",)).fetchall()
    con.close()
    return [o for (o,) in lignes]


PROMPT_TRI = """Tu tries des articles de presse pour un site arabophone sur le Real Madrid (football masculin), d'après leur titre et leur chapeau.

Garde :
- opinion : chronique, analyse, éditorial ou tribune centrés sur le Real Madrid, y compris chronique d'après-match et notes des joueurs (« uno a uno », « aprobados y suspensos », « player ratings », « notes ») ;
- conference : conférence de presse d'un entraîneur du Real Madrid, ou d'un entraîneur adverse qui parle du Real Madrid (déclarations d'avant ou d'après-match) ;
- info : information importante sur le Real Madrid (blessure, transfert, contrat, déclaration marquante, décision du club, distinction, résultat final, composition officielle), anecdotes et coulisses ; compositions probables seulement si le journal est Marca ou AS.
Écarte : horaires TV, pronostics et paris, directs et faits de jeu pendant un match, autres clubs ou autres sports, autres compositions probables.
Doublons : si plusieurs articles rapportent le même fait ou les mêmes propos, garde seulement le plus complet ; écarte aussi ce qui figure dans « DÉJÀ PUBLIÉ ».
Les chroniques ont souvent un titre court, imagé ou ironique (ex. « Aguirre-Mourinho, viejos rockeros », « La paradoja de... ») : s'il peut s'agir d'un regard sur le Real Madrid, garde-le comme opinion.
En cas de doute, garde.

Réponds UNIQUEMENT avec le tableau JSON des articles gardés, sans texte autour : [{{"id": 3, "type": "opinion"}}, {{"id": 5, "type": "conference"}}, {{"id": 7, "type": "info"}}]

DÉJÀ PUBLIÉ
{deja}

ARTICLES
{articles}
"""


PROBABLE = re.compile(r"alineaci[óo]n(es)? (probables?|posibles?)|posible (once|alineaci[óo]n)", re.I)


def trier(items, deja=()):
    """Tri sur titre + chapeau par un modèle léger : seuls les gardés seront lus en entier et rédigés.
    Retourne (gardés, avec it["type"] = opinion|conference|info ; écartés), ou None si la réponse est illisible."""
    blocs = [f"[{i}] {journal(it)}{' (rubrique opinion)' if it.get('opinion') else ''} : {it['titre']}\n{it['resume'][:300]}"
             for i, it in enumerate(items, 1)]
    reponse = appeler_claude(PROMPT_TRI.format(deja="\n".join(f"- {t}" for t in deja) or "(aucun)",
                                               articles="\n\n".join(blocs)), CONFIG.get("modele_tri", "haiku"), "low")
    try:
        choix = {r.get("id"): r.get("type") for r in extraire_json(reponse) if isinstance(r, dict)}
    except (ValueError, json.JSONDecodeError):
        return None
    gardes, ecartes = [], []
    for i, it in enumerate(items, 1):
        if it.get("opinion"):  # rubriques d'opinion et compositions probables Marca/AS : gardées d'office
            choix[i] = "opinion"
        elif journal(it) in ("Marca", "AS") and PROBABLE.search(it["titre"]):
            choix[i] = "info"
        if i in choix:
            it["type"] = choix[i] if choix[i] in ("opinion", "conference") else "info"
            gardes.append(it)
        else:
            ecartes.append(it)
    return gardes, ecartes


# ---------- base ----------
def connexion(chemin=DB):
    con = sqlite3.connect(chemin)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS articles (id INTEGER PRIMARY KEY, date TEXT, section TEXT,
        titre TEXT, chapeau TEXT, texte TEXT, auteur TEXT, auteur_ar TEXT, journal TEXT, pays TEXT,
        lien TEXT UNIQUE, titre_original TEXT, mode TEXT, personnes TEXT, via TEXT, rapporteur TEXT, sujet TEXT,
        citation TEXT, chiffres TEXT, titres_fb TEXT)""")
    for colonne in ("via", "rapporteur", "sujet", "citation", "chiffres", "titres_fb"):  # bases créées avant l'ajout de ces colonnes
        try:
            con.execute(f"ALTER TABLE articles ADD COLUMN {colonne} TEXT")
        except sqlite3.OperationalError:
            pass  # colonne déjà présente
    return con


def chiffres_valides(chiffres):
    """Garde au plus 3 chiffres clés bien formés (valeur courte + libellé) pour l'infographie."""
    if not isinstance(chiffres, list):
        return []
    ok = [{"valeur": str(c["valeur"]), "libelle": str(c["libelle"])[:60]} for c in chiffres  # valeur coupée = fausse
          if isinstance(c, dict) and c.get("valeur") and c.get("libelle") and len(str(c["valeur"])) <= 14]
    return ok[:3] if len(ok) >= 2 else []  # un chiffre isolé ne fait pas une infographie


def enregistrer(reponses, items, chemin=DB):
    """Valide la réponse de Claude et l'enregistre. Retourne le nombre d'articles ajoutés."""
    con = connexion(chemin)
    now = datetime.now().isoformat(timespec="seconds")
    n = 0
    for r in reponses:
        i = r.get("id")
        if not isinstance(i, int) or not 1 <= i <= len(items) or not r.get("titre") or not r.get("texte"):
            continue
        it = items[i - 1]
        section = r.get("section") if r.get("section") in SECTIONS else "debats"
        personnes = [p for p in r.get("personnes", []) if p in PERSONNES]
        via = str(r.get("via") or "")[:60]
        auteur_claude = str(r.get("auteur") or "")[:80]
        if via and auteur_claude:  # avis d'un commentateur : il devient l'auteur, le journaliste devient rapporteur
            auteur, rapporteur = auteur_claude, it["auteur"]
        else:
            auteur, rapporteur, via = it["auteur"] or auteur_claude, "", ""
        fb = r.get("titres_fb") if isinstance(r.get("titres_fb"), dict) else {}
        titres_fb = {k: str(fb[k])[:200] for k in ("fr", "en", "es") if fb.get(k)}
        cur = con.execute(
            "INSERT OR IGNORE INTO articles (date, section, titre, chapeau, texte, auteur, auteur_ar, journal, pays,"
            " lien, titre_original, mode, personnes, via, rapporteur, sujet, citation, chiffres, titres_fb)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            # date : celle de l'article d'origine, sinon celle du passage
            (it.get("publie") or now, section, r["titre"], r.get("chapeau", ""), r["texte"], auteur, r.get("auteur_ar") or auteur,
             journal(it), it.get("pays"), it["lien"], it["titre"], "traduction" if it.get("autorise") else "conference" if it.get("type") == "conference" else "resume",
             json.dumps(personnes), via, rapporteur, r.get("sujet") if r.get("sujet") in PERSONNES else "",
             str(r.get("citation") or "")[:200], json.dumps(chiffres_valides(r.get("chiffres")), ensure_ascii=False),
             json.dumps(titres_fb, ensure_ascii=False) if titres_fb else ""),
        )
        n += cur.rowcount
        tweets = cur.rowcount and threads.assembler(
            {"auteur_ar": r.get("auteur_ar") or auteur, "auteur": auteur, "journal": journal(it), "lien": it["lien"]},
            r.get("tweets") or [])
        if tweets:  # sinon (absent ou trop long) : threads.decouper le réécrira
            threads.connexion_threads(con)
            con.execute("INSERT OR IGNORE INTO threads VALUES (?,?,?,?)",
                        (cur.lastrowid, json.dumps(tweets, ensure_ascii=False), "a_envoyer", now))
    con.commit()
    con.close()
    return n


# ---------- photos libres (Wikimedia Commons) ----------
def licence_libre(nom):
    """Licences réutilisables avec crédit : CC BY, CC BY-SA, CC0, domaine public (pas de NC/ND)."""
    return bool(re.match(r"(CC BY(-SA)? \d|CC0|Public domain)", nom or "", re.I))


def api(url, **params):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def mettre_a_jour_photos(dossier=SITE / "photos"):
    """Télécharge une fois la photo libre de chaque personne et note son crédit.

    Photo choisie à la main dans config "photos_commons" (ex. en maillot du Real), sinon celle de sa page
    Wikipédia (config "wikipedia"). Changer le choix dans config.json suffit pour la remplacer."""
    credits = json.loads(CREDITS.read_text(encoding="utf-8")) if CREDITS.exists() else {}
    choisies = {k: f.removeprefix("File:").replace(" ", "_") for k, f in CONFIG.get("photos_commons", {}).items()}
    a_faire = {k: t for k, t in CONFIG.get("wikipedia", {}).items()
               if k not in credits or (k in choisies and (credits[k] or {}).get("commons") != choisies[k])}
    if not a_faire:
        return
    print(f"Photos : recherche de {len(a_faire)} photo(s) libre(s) sur Wikimedia Commons...")
    try:
        sans_choix = {k: t for k, t in a_faire.items() if k not in choisies}
        q = api("https://en.wikipedia.org/w/api.php", action="query", titles="|".join(sans_choix.values()),
                prop="pageprops", redirects=1, format="json", formatversion=2)["query"] if sans_choix else {}
        renvois = {x["from"]: x["to"] for x in q.get("normalized", []) + q.get("redirects", [])}
        images = {p["title"]: p.get("pageprops", {}).get("page_image_free") for p in q.get("pages", [])}
        fichiers = {}
        for k, titre in a_faire.items():
            while titre in renvois:
                titre = renvois[titre]
            fichiers[k] = choisies.get(k) or images.get(titre)
        noms = {f"File:{f.replace('_', ' ')}": k for k, f in fichiers.items() if f}
        infos = api("https://commons.wikimedia.org/w/api.php", action="query", titles="|".join(noms), prop="imageinfo",
                    iiprop="url|extmetadata", iiurlwidth=960, format="json", formatversion=2)["query"] if noms else {}
    except Exception as err:  # noqa: BLE001 - réseau : on réessaiera au prochain passage
        print(f"  ! photos indisponibles ({err})")
        return
    for k in a_faire:
        if not fichiers.get(k):
            credits[k] = None  # pas de photo libre sur Wikipédia
    renvois = {x["from"]: x["to"] for x in infos.get("normalized", [])}
    noms = {renvois.get(n, n): k for n, k in noms.items()}
    dossier.mkdir(parents=True, exist_ok=True)
    for page in infos.get("pages", []):
        k = noms.get(page["title"])
        if not k or not page.get("imageinfo"):
            continue
        info = page["imageinfo"][0]
        meta = {n: str(v.get("value", "")) for n, v in info.get("extmetadata", {}).items()}
        ia = re.search(r"chatgpt|midjourney|dall-?e|stable diffusion|ai[- ]generated",
                       meta.get("Artist", "") + meta.get("ImageDescription", ""), re.I)
        if not licence_libre(meta.get("LicenseShortName")) or ia:  # image générée par IA : pas une vraie photo
            credits[k] = None
            continue
        fichier = f"{k}{os.path.splitext(urllib.parse.urlparse(info['thumburl']).path)[1].lower() or '.jpg'}"
        time.sleep(1)  # Wikimedia renvoie 429 si les téléchargements s'enchaînent trop vite
        try:
            with urllib.request.urlopen(urllib.request.Request(info["thumburl"], headers=UA), timeout=30) as r:
                (dossier / fichier).write_bytes(r.read())
        except Exception as err:  # noqa: BLE001 - réessayé au prochain passage
            print(f"  ! {k} : téléchargement impossible ({err})")
            continue
        credits[k] = {"fichier": fichier, "auteur": nettoyer(meta.get("Artist"), 120) or "مجهول",
                      "licence": meta["LicenseShortName"], "licence_url": meta.get("LicenseUrl", ""),
                      "source": info["descriptionurl"], "commons": fichiers[k]}
    CREDITS.write_text(json.dumps(credits, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {sum(1 for c in credits.values() if c)} photo(s) libre(s) disponibles.")


# ---------- couvertures (image 1200×630 de chaque article, aussi utilisée pour le partage) ----------
# identité inspirée du Real Madrid (maquettes Figma validées) : couleurs de l'écusson et des maillots, or,
# sans écusson ni marque (compte de fan non officiel) ; chaque rubrique a son motif doré et sa signature (.deco)
SVG = "<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='630' fill='none' stroke='#FEBE10'>{}</svg>"
OR = "#FEBE10"


def _ville():
    """Club : le Bernabéu face aux Cuatro Torres (bâties sur l'ancien centre d'entraînement vendu en 2001), nuit étoilée."""
    v = ("<g stroke-opacity='.45' stroke-width='2'><path d='M110 528 V478 Q110 446 146 442 H534 Q570 446 570 478 V528'/>"
         "<path d='M130 442 Q340 414 550 442'/>")
    v += "".join(f"<path d='M118 {y} C 230 {y - 8}, 340 {y + 8}, 450 {y - 4} S 540 {y + 4}, 562 {y}' stroke-width='1.2' stroke-opacity='.6'/>"
                 for y in range(460, 525, 13))
    for x, w, h, haut in ((800, 46, 140, "plat"), (872, 52, 165, "arche"), (950, 48, 155, "pointe"), (1024, 44, 135, "couronne")):
        top = 528 - h
        if haut == "arche":
            v += (f"<path d='M{x} 528 V{top} H{x + w} V528'/>"
                  f"<path d='M{x + 9} {top} V{top + 28} Q{x + w / 2} {top + 12} {x + w - 9} {top + 28} V{top}' stroke-width='1.5'/>")
        elif haut == "pointe":
            v += f"<path d='M{x} 528 V{top + 16} L{x + w / 2} {top} L{x + w} {top + 16} V528'/><path d='M{x + w / 2} {top} V{top - 22}' stroke-width='1.5'/>"
        elif haut == "couronne":
            v += f"<path d='M{x} 528 V{top} H{x + w} V528'/><path d='M{x - 4} {top} V{top - 12} H{x + w + 4} V{top}' stroke-width='1.5'/>"
        else:
            v += f"<rect x='{x}' y='{top}' width='{w}' height='{h}'/>"
        v += "".join(f"<path d='M{x + 8} {y} H{x + w - 8}' stroke-width='.8' stroke-opacity='.45'/>" for y in range(top + 34, 520, 22))
    v += "<path d='M40 528 H1160' stroke-width='1.5'/></g>"
    etoiles = ((90, 160), (180, 110), (330, 175), (700, 120), (760, 190), (1120, 140), (620, 205), (260, 240), (980, 300), (870, 260))
    return v + "".join(f"<circle cx='{x}' cy='{y}' r='{2.8 if i % 3 == 0 else 1.8}' fill='{OR}' fill-opacity='.55' stroke='none'/>"
                       for i, (x, y) in enumerate(etoiles))


def _trame():
    """Débats : trame de points d'imprimerie (la presse) et deux bulles de dialogue qui se répondent."""
    t = "".join(f"<circle cx='{x}' cy='{y}' r='{5.6 * (1 - d):.2f}' fill='{OR}' fill-opacity='.26' stroke='none'/>"
                for y in range(8, 630, 16) for x in range(8, 1200, 16) if (d := ((x ** 2 + (630 - y) ** 2) ** .5) / 820) <= 1)
    return t + ("<rect x='0' y='538' width='1200' height='92' fill='#141414' stroke='none'/>"  # pied lisible
                "<g stroke-width='2.5' stroke-opacity='.6'><path d='M78 398 h230 a20 20 0 0 1 20 20 v62 a20 20 0 0 1 -20 20 h-160 l-36 30 v-30 h-34 a20 20 0 0 1 -20 -20 v-62 a20 20 0 0 1 20 -20z'/>"
                "<path d='M262 440 h230 a20 20 0 0 1 20 20 v52 a20 20 0 0 1 -20 20 h-34 v6 l-30 -6 h-166 a20 20 0 0 1 -20 -20 v-52 a20 20 0 0 1 20 -20z' stroke-opacity='.4'/>"
                "<path d='M100 432 h170 M100 460 h120' stroke-width='3' stroke-opacity='.4' stroke-linecap='round'/></g>")


_J = ((90, 315), (240, 135), (240, 255), (240, 375), (240, 495), (440, 195), (440, 315), (440, 435), (650, 140), (690, 315), (650, 490))
_LIENS = ((0, 2), (0, 3), (1, 2), (2, 3), (3, 4), (1, 5), (2, 6), (3, 6), (4, 7), (5, 6), (6, 7), (5, 8), (6, 9), (7, 10), (8, 9), (9, 10))
MOTIFS = {
    "actus": (  # vue aérienne du stade : anneaux des tribunes et pelouse
        "".join(f"<ellipse cx='600' cy='300' rx='{190 + i * 62}' ry='{(190 + i * 62) // 2}' stroke-width='{1.2 if i % 2 else 2.2}' "
                f"stroke-opacity='{.34 - i * .035:.3f}'/>" for i in range(7))
        + "<g stroke-opacity='.3' stroke-width='2'><rect x='440' y='225' width='320' height='150' rx='6'/><path d='M600 225 V375'/>"
        "<circle cx='600' cy='300' r='28'/><rect x='440' y='265' width='45' height='70'/><rect x='715' y='265' width='45' height='70'/></g>"
        "<rect x='0' y='528' width='1200' height='102' fill='#fff' stroke='none'/>"),
    "tactique": (  # pelouse tondue en bandes et 4-3-3 relié comme une constellation
        "".join(f"<rect x='{i * 150}' y='0' width='150' height='630' fill='#fff' fill-opacity='.025' stroke='none'/>" for i in range(1, 8, 2))
        + "<g opacity='.7'>" + "".join(f"<path d='M{_J[a][0]} {_J[a][1]} L{_J[b][0]} {_J[b][1]}' stroke-width='1.5' stroke-opacity='.18'/>" for a, b in _LIENS)
        + "".join(f"<circle cx='{x}' cy='{y}' r='13' stroke-width='2.5' stroke-opacity='.4'/>"
                  f"<circle cx='{x}' cy='{y}' r='4' fill='{OR}' fill-opacity='.5' stroke='none'/>" for x, y in _J) + "</g>"),
    "mercato": (  # faisceaux de projecteur sur la recrue et éclats dorés
        "".join(f"<path d='M-60 690 L{-40 + i * 95} -10' stroke-width='{1.2 if i % 3 else 2.2}' stroke-opacity='{.12 if i % 3 else .2}'/>" for i in range(12))
        + "".join(f"<path d='M{x} {y - r} Q{x} {y} {x + r} {y} Q{x} {y} {x} {y + r} Q{x} {y} {x - r} {y} Q{x} {y} {x} {y - r}Z' "
                  f"fill='{OR}' fill-opacity='{o}' stroke='none'/>" for x, y, r, o in ((150, 200, 18, .7), (230, 150, 10, .5), (110, 420, 12, .45)))),
    "club": _ville(),
    "debats": _trame(),
}
DECO = {  # signature de chaque rubrique (div.deco)
    "tactique": ".deco{position:absolute;top:0;bottom:0;right:0;width:58px;background:#00529f;border-left:7px solid #FEBE10}"
                ".cadre{padding-right:120px}",
    "mercato": ".haut{border-bottom:2px solid #FEBE1080;padding-bottom:16px}",
    "club": ".rubrique{position:relative}.rubrique::after{content:'';position:absolute;bottom:-4px;right:22%;left:22%;"
            "height:5px;border-radius:3px;background:#FEBE10}.centre{padding-bottom:110px}",  # citation au-dessus de la ville
    "debats": ".deco{position:absolute;inset:16px;border:2px solid #FEBE10}",
}
THEMES = {  # fond, texte, texte secondaire, or du logo, chiffres
    "actus": ("#ffffff", "#0b1f3a", "#33415c", "#d9a400", "#00529f"),  # maillot domicile
    "tactique": ("#0b1f3a", "#ffffff", "#c8d3e6", OR, OR),  # bleu marine du maillot extérieur
    "mercato": ("#00529f", "#ffffff", "#d6e4f5", OR, OR),  # bleu royal de l'écusson
    "club": ("#3d195b", "#ffffff", "#e0d4ec", OR, OR),  # violet historique
    "debats": ("#141414", "#ffffff", "#cfcfcf", OR, OR),  # noir et or
}
COUV_POLICES = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700'
                '&family=Amiri:wght@700&display=swap">')
COUV_CSS = """
*{box-sizing:border-box;margin:0}
body{width:1200px;height:630px;overflow:hidden;direction:rtl;color:var(--texte);background:var(--fond);font-family:Cairo,Tahoma,sans-serif}
.motif{position:absolute;inset:0;background:url("data:image/svg+xml,MOTIF") no-repeat}
.cadre{position:absolute;inset:0;padding:44px 64px 30px;display:flex;flex-direction:column}
.haut{display:flex;justify-content:space-between;align-items:center;font-size:26px;font-weight:600}
.rubrique{border:2.5px solid #FEBE10;border-radius:999px;padding:2px 26px 6px}
.logo{font-size:32px;font-weight:700}.logo span{color:var(--or)}
.centre{flex:1;display:flex;flex-direction:column;justify-content:center}
.citation{font-family:Amiri,"Traditional Arabic",serif;font-weight:700;position:relative;padding-inline-start:100px}
.citation::before{content:"«";position:absolute;inset-inline-start:0;top:-40px;font-size:150px;line-height:1;color:#FEBE10}
.titre-actu{font-weight:700;border-inline-start:8px solid #FEBE10;padding-inline-start:32px}
.sur-chiffres{font-size:32px;font-weight:700;line-height:1.5;margin-bottom:26px}
.chiffres{display:flex;gap:34px}
.chiffre{flex:1;border-top:6px solid #FEBE10;padding-top:8px}
.chiffre b{display:block;font-size:76px;line-height:1.3;color:var(--chiffre);unicode-bidi:plaintext;text-align:right;white-space:nowrap}
.chiffre span{display:block;font-size:26px;line-height:1.45;color:var(--doux)}
.bas{position:relative;display:flex;align-items:center;gap:14px;font-size:25px;border-top:2.5px solid #FEBE10;padding-top:16px;color:var(--doux)}
.bas::before{content:"";position:absolute;top:-11px;right:50%;width:18px;height:18px;background:var(--fond);
border-right:2.5px solid #FEBE10;border-bottom:2.5px solid #FEBE10;transform:rotate(45deg)}
.bas strong{font-size:28px;color:var(--texte)}
.bas .pays{margin-inline-start:auto;color:var(--or);font-weight:700}
"""


def couverture_html(a):
    """Gabarit de la couverture : citation forte, chiffres clés (infographie) ou titre d'une information."""
    chiffres = json.loads(a["chiffres"] or "[]")
    texte = a["citation"] or a["titre"]
    taille = 60 if len(texte) <= 60 else 50 if len(texte) <= 110 else 42
    if chiffres:
        cases = ""
        for c in chiffres:
            petite = ' style="font-size:56px"' if len(c["valeur"]) > 6 else ""  # « 18 مقابل 10 » tient sur une ligne
            cases += f'<div class="chiffre"><b{petite}>{e(c["valeur"])}</b><span>{e(c["libelle"])}</span></div>'
        centre = f'<p class="sur-chiffres">{e(a["titre"])}</p><div class="chiffres">{cases}</div>'
    elif a["section"] == "actus":
        centre = f'<p class="titre-actu" style="font-size:{taille}px;line-height:1.5">{e(texte)}</p>'
    else:
        centre = f'<p class="citation" style="font-size:{taille - 4}px;line-height:1.55">{e(texte)}</p>'
    via = f" · عن {e(a['via'])}" if a["via"] else ""
    auteur = f"<strong>{e(a['auteur_ar'])}</strong>{via} · " if a["auteur"] else ""
    premier, reste = NOM_SITE.split(" ", 1)
    fond, texte, doux, orr, chiffre = THEMES.get(a["section"], THEMES["actus"])
    return (
        f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">{COUV_POLICES}'
        f'<style>{COUV_CSS.replace("MOTIF", urllib.parse.quote(SVG.format(MOTIFS.get(a["section"], MOTIFS["actus"]))))}'
        f'{DECO.get(a["section"], "")}</style></head>'
        f'<body style="--fond:{fond};--texte:{texte};--doux:{doux};--or:{orr};--chiffre:{chiffre}">'
        f'<div class="motif"></div><div class="deco"></div><div class="cadre">'
        f'<div class="haut"><span class="rubrique">{SECTIONS.get(a["section"], "")}</span>'
        f'<span class="logo">{premier} <span>{reste}</span></span></div>'
        f'<div class="centre">{centre}</div>'
        f'<div class="bas">{auteur}<span>{e(a["journal"])}</span>'
        f'<span class="pays">{PAYS.get(a["pays"], "") if a["pays"] else ""}</span></div></div></body></html>'
    )


def trouver_edge():
    for chemin in (shutil.which("msedge"), shutil.which("google-chrome"), r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                   r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if chemin and os.path.exists(chemin):
            return chemin
    return None


EDGE = trouver_edge()


def generer_couvertures(arts, dossier):
    """Rend chaque couverture en PNG avec Edge sans fenêtre ; refaite seulement si son contenu change."""
    if not EDGE:
        return {}
    sortie, sources = dossier / "couvertures", BASE / "sortie" / "couvertures"
    sortie.mkdir(parents=True, exist_ok=True)
    sources.mkdir(parents=True, exist_ok=True)
    noms = {}
    for a in arts:
        doc = couverture_html(a)
        nom = f"a-{a['id']}-{hashlib.sha1(doc.encode()).hexdigest()[:8]}.png"
        if not (sortie / nom).exists():
            src = sources / f"a-{a['id']}.html"
            src.write_text(doc, encoding="utf-8")
            try:
                subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                f"--user-data-dir={sources / 'profil'}", "--virtual-time-budget=5000",
                                "--window-size=1200,630", f"--screenshot={sortie / nom}", src.as_uri()],
                               capture_output=True, timeout=90)
                fin = time.time() + 60  # msedge.exe rend la main avant que son processus enfant ait écrit l'image
                while not (sortie / nom).exists() and time.time() < fin:
                    time.sleep(0.5)
                time.sleep(0.5)  # laisse finir l'écriture du fichier
            except subprocess.TimeoutExpired:
                print(f"  ! couverture de l'article {a['id']} : Edge trop lent, réessayé au prochain passage")
        if (sortie / nom).exists():
            noms[a["id"]] = nom
    for ancienne in sortie.glob("*.png"):  # couvertures d'articles supprimés ou modifiés
        if ancienne.name not in noms.values():
            ancienne.unlink()
    return noms


# ---------- rendu ----------
CREDITS_PHOTOS = {}  # chargé par rendre_site
COUVERTURES = {}  # id d'article -> fichier PNG, chargé par rendre_site
THREADS = {}  # id d'article -> tweets du thread X, chargé par rendre_site

# boutons X / Facebook : copier, coches, et mémoire « publié » propre au navigateur (site local, pas de serveur)
JS = """const lire=k=>{try{return localStorage.getItem(k)}catch(e){return null}};
const ecrire=(k,v)=>{try{v?localStorage.setItem(k,"1"):localStorage.removeItem(k)}catch(e){}};
async function copier(t){try{await navigator.clipboard.writeText(t)}catch(e){const z=document.createElement("textarea");
z.value=t;document.body.append(z);z.select();document.execCommand("copy");z.remove()}}
function marquer(){
document.querySelectorAll("[data-cle]").forEach(b=>{if(lire("cp-"+b.dataset.cle)){b.classList.add("copie");
b.querySelector(".copier").textContent="✓ تم النسخ"}});
document.querySelectorAll("[data-pub]").forEach(x=>x.checked=!!lire("pub-"+x.dataset.pub));
document.querySelectorAll("[data-id]").forEach(x=>{x.querySelectorAll(".pub").forEach(p=>p.remove());
const s=[["x","X"],["fb","فيسبوك"]].filter(([r])=>lire(`pub-${r}-${x.dataset.id}`)).map(([,n])=>n);
if(s.length){const p=document.createElement("span");p.className="pub";p.textContent="✓ نُشر: "+s.join(" · ");
(x.querySelector(".signature")||x).append(p)}})}
document.addEventListener("click",async ev=>{
const o=ev.target.closest("[data-ouvre]");if(o){document.getElementById(o.dataset.ouvre).showModal();return}
const c=ev.target.closest(".copier");if(c){const b=c.closest(".copiable");ecrire("cp-"+b.dataset.cle,1);
b.classList.add("copie");c.textContent="✓ تم النسخ";await copier(b.querySelector(".a-copier").textContent)}});
document.addEventListener("change",ev=>{const p=ev.target.dataset.pub;if(p){ecrire("pub-"+p,ev.target.checked);marquer()}});
marquer();
"""
SLOGAN = "صحافة العالم عن ريال مدريد، بالعربية"
A_PROPOS = ("نختار لكم أبرز مقالات الرأي عن ريال مدريد في الصحافة الإسبانية والأوروبية وصحافة بلدان لاعبيه، "
            "ونقدّمها بالعربية مع ذكر الكاتب والمصدر.")
DESCRIPTIONS = {
    "actus": "أهم أخبار ريال مدريد كما نقلتها الصحافة العالمية، باختصار ومع ذكر المصدر.",
    "tactique": "قراءات في أسلوب اللعب والخطط وأداء اللاعبين.",
    "mercato": "آراء المحللين في الصفقات والعقود وسياسة التعاقدات.",
    "club": "المال والإدارة والملعب وعلاقات النادي بالمؤسسات.",
    "debats": "القضايا الساخنة والجدل كما يراه كتّاب الرأي.",
}
MOIS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
POLICES = (
    '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;600;700'
    '&family=Noto+Naskh+Arabic:wght@400;600&display=swap">'
)
VIDE = '<p class="vide">لا توجد مقالات بعد. عودوا قريبًا.</p>'

CSS = """
:root{--papier:#faf8f4;--surface:#fff;--encre:#16181d;--doux:#5f6672;--ligne:#e7e2d8;--marine:#0b1f3a;--bleu:#00529f;
--or:#c9a227;--or-pale:#f6eed6;--tactique:#00529f;--mercato:#8a5d00;--club:#5b2a86;--debats:#b3261e;--actus:#0f7466;--c:var(--bleu);
--titres:"IBM Plex Sans Arabic","Segoe UI",Tahoma,sans-serif;--lecture:"Noto Naskh Arabic","Traditional Arabic",serif;--r:14px}
@media (prefers-color-scheme:dark){:root{--papier:#0e1117;--surface:#161b24;--encre:#ece8df;--doux:#a4abb6;--ligne:#283040;
--marine:#0a1628;--or-pale:#2c2612;--bleu:#6aa8ff;--tactique:#6aa8ff;--mercato:#e2b43f;--club:#c39af0;--debats:#ff8a80;--actus:#4fd1b8}}
*{box-sizing:border-box}
body{margin:0;background:var(--papier);color:var(--encre);font:16px/1.75 var(--titres)}
a{color:inherit}
:focus-visible{outline:3px solid var(--or);outline-offset:2px;border-radius:4px}
.cadre{max-width:1180px;margin-inline:auto;padding-inline:20px}
.sauter{position:absolute;inset-inline-start:12px;top:-60px;background:var(--or);color:#111;padding:8px 14px;border-radius:8px;z-index:10}
.sauter:focus{top:12px}

/* entête */
.entete{background:var(--marine);color:#fff}
.bande{border-bottom:1px solid #ffffff1f;font-size:13px;color:#c9d3e3}
.bande .cadre{display:flex;justify-content:space-between;gap:12px;padding-block:6px}
.marque{padding-block:26px 20px;text-align:center}
.logo{font:700 clamp(30px,5vw,46px)/1.2 var(--titres);color:#fff;text-decoration:none}
.logo span{color:var(--or)}
.menu{position:sticky;top:0;z-index:5;background:var(--marine);border-top:1px solid #ffffff1f;box-shadow:0 6px 18px -12px #000a}
.menu .cadre{display:flex;justify-content:center;gap:2px;overflow-x:auto;scrollbar-width:none}
.menu a{flex:none;color:#dfe6f1;text-decoration:none;padding:13px 14px 10px;font-weight:600;font-size:15px;border-bottom:3px solid transparent}
.menu a:hover{color:#fff}
.menu a[aria-current]{color:#fff;border-bottom-color:var(--or)}
@media (max-width:760px){.menu .cadre{justify-content:flex-start}.bande .slogan{display:none}}
main{padding-block:36px 64px}

/* cartes */
.s-tactique{--c:var(--tactique)}.s-mercato{--c:var(--mercato)}.s-club{--c:var(--club)}.s-debats{--c:var(--debats)}.s-actus{--c:var(--actus)}
.carte{position:relative;display:flex;flex-direction:column;background:var(--surface);border:1px solid var(--ligne);
border-top:4px solid var(--c);border-radius:var(--r);overflow:hidden;transition:box-shadow .2s,transform .2s}
.carte .contenu{flex:1;display:flex;flex-direction:column;gap:8px;padding:20px 22px}
.couv{display:block;width:100%;aspect-ratio:1200/630;object-fit:cover;background:var(--c)}
.couverture{margin:0 0 30px}
.couverture img{display:block;width:100%;height:auto;border-radius:var(--r);box-shadow:0 12px 30px -18px #0b1f3a88}
.carte:hover{box-shadow:0 14px 30px -16px #0b1f3a55;transform:translateY(-2px)}
.carte h2,.carte h3{margin:0;font-weight:700;line-height:1.45}
.carte h3{font-size:19px}
.titre{text-decoration:none}
.carte .titre::after{content:"";position:absolute;inset:0;border-radius:var(--r)}
.carte .titre:hover{color:var(--c)}
.rubrique,.signature a{position:relative;z-index:1}
.rubrique{align-self:flex-start;color:var(--c);font-size:13px;font-weight:700;text-decoration:none}
.rubrique::before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--c);margin-inline-end:7px;vertical-align:middle}
.resume{margin:0;color:var(--doux);font:16.5px/1.9 var(--lecture);display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.signature{margin-top:auto;padding-top:10px;display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;font-size:13.5px;color:var(--doux)}
.signature .auteur{color:var(--encre);font-weight:700;text-decoration:none}
.signature .auteur:hover{color:var(--c)}
.signature time{margin-inline-start:auto}
.puce{background:var(--or-pale);color:var(--encre);border-radius:999px;padding:1px 10px;text-decoration:none;font-size:12.5px}
.grille{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(300px,100%),1fr));gap:20px}
.grille>*,.a-la-une>*,.cote>*,.mise-en-page>*{min-width:0}
h1,h2,h3{overflow-wrap:anywhere}
@media (prefers-reduced-motion:reduce){.carte{transition:none}.carte:hover{transform:none}}

/* accueil */
.a-la-une{display:grid;grid-template-columns:2fr 1fr;gap:20px;align-items:start}
.une{border-top-width:6px}
.une .contenu{padding:28px 34px}
.une h2{font-size:clamp(26px,3.4vw,38px);line-height:1.35}
.une .resume{font-size:19px;-webkit-line-clamp:5;color:var(--encre)}
.cote{display:grid;gap:20px;align-content:start}
.compacte .resume{-webkit-line-clamp:2}
@media (max-width:860px){.a-la-une{grid-template-columns:1fr}.une .contenu{padding:22px}}
.bloc{margin-top:52px}
.bloc-tete{display:flex;align-items:baseline;justify-content:space-between;gap:12px;border-bottom:2px solid var(--encre);margin-bottom:20px;padding-bottom:8px}
.bloc-tete h2{margin:0;font-size:22px;display:flex;align-items:center;gap:10px}
.bloc-tete h2::before{content:"";width:6px;height:22px;background:var(--c);border-radius:3px}
.bloc-tete a{color:var(--c);font-weight:600;text-decoration:none;font-size:14px}
.bloc-or{--c:var(--or)}
.deux{display:grid;grid-template-columns:1fr 1fr;gap:0 40px}
@media (max-width:760px){.deux{grid-template-columns:1fr}}
.nuage{display:flex;flex-wrap:wrap;gap:10px}
.nuage a{background:var(--surface);border:1px solid var(--ligne);border-radius:999px;padding:6px 16px;text-decoration:none;font-weight:600;font-size:14.5px}
.nuage a:hover{border-color:var(--or)}
.nuage small{color:var(--doux);font-weight:400;margin-inline-start:6px}

/* pages de liste */
.tete-liste{padding-bottom:26px;margin-bottom:30px;border-bottom:1px solid var(--ligne)}
.sur-titre{color:var(--c);font-weight:700;font-size:14px}
.tete-liste h1{margin:4px 0 6px;font-size:clamp(28px,4vw,42px);line-height:1.3}
.tete-liste p{margin:0;color:var(--doux);font-size:17px;max-width:640px}
.compte{display:inline-block;margin-top:14px;font-size:13px;color:var(--doux);background:var(--surface);border:1px solid var(--ligne);border-radius:999px;padding:2px 12px}
.vide{background:var(--surface);border:1px dashed var(--ligne);border-radius:var(--r);padding:44px;text-align:center;color:var(--doux)}

/* article */
.mise-en-page{display:grid;grid-template-columns:minmax(0,720px) 300px;gap:56px;justify-content:center}
@media (max-width:1060px){.mise-en-page{grid-template-columns:minmax(0,720px)}}
.haut{display:flex;align-items:center;gap:12px}
.nature{font-size:12.5px;border:1px solid var(--ligne);border-radius:999px;padding:1px 10px;color:var(--doux)}
.lecture h1{font-size:clamp(28px,4.2vw,44px);line-height:1.35;margin:12px 0 16px}
.lecture .chapeau{font:600 21px/1.85 var(--lecture);margin:0 0 24px}
.tete-auteur{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px 24px;padding:16px 0;border-block:1px solid var(--ligne);margin-bottom:30px}
.auteur-bloc{display:flex;align-items:center;gap:12px}
.avatar{width:46px;height:46px;flex:none;border-radius:50%;background:var(--c);color:#fff;display:grid;place-items:center;font-weight:700;font-size:20px}
.auteur-bloc .auteur{display:block;font-weight:700;font-size:17px;text-decoration:none}
.auteur-bloc .auteur:hover{color:var(--c)}
.latin{font-size:13.5px;color:var(--doux)}
.infos{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;font-size:14px;color:var(--doux)}
.texte{font:20px/2.05 var(--lecture)}
.texte p{margin:0 0 1.15em}
@media (max-width:600px){.texte{font-size:18.5px}.lecture .chapeau{font-size:19px}}
.etiquettes{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:30px 0}
.etiquettes strong{font-size:14px;margin-inline-end:4px}
.etiquettes a{background:var(--surface);border:1px solid var(--ligne);border-radius:999px;padding:3px 14px;text-decoration:none;font-size:14px}
.etiquettes a:hover{border-color:var(--c)}
.source{background:var(--surface);border:1px solid var(--ligne);border-inline-start:4px solid var(--or);border-radius:var(--r);padding:20px 24px}
.source h2{margin:0 0 6px;font-size:14px;color:var(--doux);font-weight:600}
.titre-original{font-weight:700;font-size:17px;margin:0 0 6px}
.source p{margin:0 0 14px;font-size:15px}
.bouton{display:inline-block;background:var(--marine);color:#fff;text-decoration:none;border-radius:10px;padding:10px 20px;font-weight:600}
.bouton:hover{background:var(--bleu);color:#fff}
.partage{display:flex;flex-wrap:wrap;gap:10px;margin:-14px 0 26px}
.copier,.fermer{font:600 14px var(--titres);border:1px solid var(--ligne);background:var(--surface);color:var(--encre);border-radius:999px;padding:6px 16px;cursor:pointer}
.copier:hover,.fermer:hover{border-color:var(--or)}
.partage button{display:inline-flex;align-items:center;gap:10px;font:700 15px var(--titres);color:#fff;border:1px solid #ffffff26;border-radius:999px;padding:9px 20px;cursor:pointer;transition:transform .15s,box-shadow .15s}
.partage button:hover{transform:translateY(-1px);box-shadow:0 8px 18px -10px #000a}
.partage svg{width:18px;height:18px;fill:currentColor;flex:none}
.b-x{background:#000}.b-fb{background:#1877f2}
@media (prefers-reduced-motion:reduce){.partage button{transition:none}.partage button:hover{transform:none}}
.fenetre{width:min(640px,calc(100% - 32px));max-height:85vh;border:none;border-radius:var(--r);padding:22px 24px;background:var(--surface);color:var(--encre)}
.fenetre::backdrop{background:#0b1f3acc}
.fenetre h2{margin:0 0 12px;font-size:20px}
.tweets{list-style:none;margin:16px 0;padding:0;display:grid;gap:12px}
.copiable{border:1px solid var(--ligne);border-radius:10px;padding:12px 14px}
.copiable.copie{border-color:var(--actus);background:color-mix(in srgb,var(--actus) 8%,transparent)}
.a-copier{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font:16px/1.8 var(--titres)}
.outils{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:8px;color:var(--doux)}
.publie{display:flex;gap:8px;align-items:center;font-weight:600;margin:14px 0}
.pub{background:var(--or-pale);border-radius:999px;padding:1px 10px;font-size:12.5px;color:var(--encre)}
.proches h2{font-size:17px;margin:0 0 14px}
.proches .carte{margin-bottom:16px}

/* revue de presse */
.jour{margin-bottom:44px}
.jour h2{display:flex;align-items:baseline;gap:12px;font-size:21px;margin:0 0 16px}
.jour h2 span{font-size:13px;color:var(--doux);font-weight:400}
.fil{list-style:none;margin:0;padding:0;border-inline-start:2px solid var(--ligne);max-width:820px}
.fil li{position:relative;padding:0 26px 26px}
.fil li::before{content:"";position:absolute;inset-inline-start:-7px;top:9px;width:12px;height:12px;border-radius:50%;background:var(--c);box-shadow:0 0 0 4px var(--papier)}
.fil .titre{display:block;font-weight:700;font-size:18px;margin:2px 0 4px}
.fil .titre:hover{color:var(--c)}
.fil p{margin:0 0 4px;color:var(--doux);font-family:var(--lecture)}
.fil .signature{padding-top:2px}
.fil .signature time{margin-inline-start:0}

/* presse */
.tuiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:18px}
.tuile{display:block;background:var(--surface);border:1px solid var(--ligne);border-radius:var(--r);padding:22px;text-decoration:none}
.tuile:hover{border-color:var(--or)}
.tuile strong{display:block;font-size:19px}
.tuile .nb{display:block;font-size:36px;font-weight:700;color:var(--bleu);line-height:1.3}
.tuile small{color:var(--doux)}

/* photos */
.photo{margin:0 0 30px}
.photo img{display:block;width:100%;max-height:420px;object-fit:cover;object-position:center 20%;border-radius:var(--r);background:var(--ligne)}
.photo figcaption,.portrait figcaption{font-size:12px;line-height:1.6;color:var(--doux);margin-top:6px}
.photo figcaption a,.portrait figcaption a{color:inherit}
.tete-liste{display:flex;align-items:center;gap:28px}
.portrait{flex:none;width:170px;margin:0}
.portrait img{display:block;width:170px;height:170px;border-radius:50%;object-fit:cover;object-position:center 15%;border:4px solid var(--or)}
.portrait figcaption{text-align:center}
@media (max-width:600px){.tete-liste{flex-direction:column;align-items:flex-start}}

/* pied */
.pied{background:var(--marine);color:#c9d3e3;padding:48px 0 22px;font-size:14.5px}
.grille-pied{display:grid;grid-template-columns:2fr 1fr 1.4fr;gap:36px}
@media (max-width:760px){.grille-pied{grid-template-columns:1fr}}
.pied .logo{font-size:28px}
.pied h2{color:#fff;margin:0 0 10px;font-size:15px}
.pied a{display:block;color:#c9d3e3;text-decoration:none;padding:3px 0}
.pied a:hover{color:#fff}
.pied .copyright{border-top:1px solid #ffffff1f;margin-top:30px;padding-top:16px;font-size:13px;color:#8fa0b8}
"""


def slug(texte):
    s = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "auteur"


def e(t):
    return html.escape(t or "")


def date_ar(iso):
    d = datetime.fromisoformat(iso)
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"


def nombre(n, un, deux, pluriel, singulier_acc):
    """Accord du nom après un nombre en arabe (1, 2, 3-10, 11+)."""
    return un if n == 1 else deux if n == 2 else f"{n} {pluriel}" if n <= 10 else f"{n} {singulier_acc}"


def compte(n):
    return nombre(n, "مقال واحد", "مقالان", "مقالات", "مقالًا")


def duree(texte):
    n = max(1, round(len(texte.split()) / 180))
    return "قراءة في " + nombre(n, "دقيقة واحدة", "دقيقتين", "دقائق", "دقيقة")


def logo(balise="a"):
    premier, reste = NOM_SITE.split(" ", 1)
    lien = ' href="index.html"' if balise == "a" else ""
    return f'<{balise} class="logo"{lien}>{premier} <span>{reste}</span></{balise}>'


def page(titre, corps, actif=None, image=""):
    url = CONFIG.get("url_site", "").rstrip("/")  # les réseaux sociaux exigent une adresse d'image complète
    partage = (f'<meta property="og:title" content="{e(titre)}"><meta property="og:image" content="{url}/{image}">'
               '<meta name="twitter:card" content="summary_large_image">') if url and image else ""
    liens = [("index", "الرئيسية"), *SECTIONS.items(), ("revue", "مراجعة الصحافة"), ("presse", "الصحافة العالمية")]
    courant = ' aria-current="page"'
    nav = "".join(f'<a href="{k}.html"{courant if k == actif else ""}>{v}</a>' for k, v in liens)
    pied_sections = "".join(f'<a href="{k}.html">{v}</a>' for k, v in SECTIONS.items())
    return (
        '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{e(titre)} | {NOM_SITE}</title><meta name="description" content="{SLOGAN}">{partage}'
        f'<meta name="color-scheme" content="light dark">{POLICES}<link rel="stylesheet" href="style.css"><script src="site.js" defer></script></head><body>'
        '<a class="sauter" href="#contenu">انتقل إلى المحتوى</a>'
        f'<header class="entete"><div class="bande"><div class="cadre"><span class="slogan">{SLOGAN}</span>'
        f'<span>{date_ar(datetime.now().isoformat())}</span></div></div><div class="cadre marque">{logo()}</div></header>'
        f'<nav class="menu" aria-label="الأقسام"><div class="cadre">{nav}</div></nav>'
        f'<main id="contenu" class="cadre">{corps}</main>'
        f'<footer class="pied"><div class="cadre"><div class="grille-pied"><div>{logo("div")}<p>{A_PROPOS}</p></div>'
        f'<div><h2>الأقسام</h2>{pied_sections}<a href="revue.html">مراجعة الصحافة</a></div>'
        '<div><h2>تنبيه</h2><p>الآراء المنشورة تعبّر عن أصحابها ولا تمثّل الموقع. '
        'لكل مقال رابط إلى نصّه الأصلي في مصدره.</p></div></div>'
        f'<div class="copyright">© {datetime.now().year} {NOM_SITE}</div></div></footer></body></html>'
    )


def rubrique(a):
    return f'<a class="rubrique" href="{a["section"]}.html">{SECTIONS[a["section"]]}</a>'


def puce_pays(a):
    return f'<a class="puce" href="pays-{a["pays"]}.html">{PAYS.get(a["pays"], a["pays"])}</a>' if a["pays"] else ""


def lien_auteur(a):
    return f'<a class="auteur" href="j-{slug(a["auteur"])}.html">{e(a["auteur_ar"])}</a>' if a["auteur"] else ""


def signature(a):
    via = f'<span>عن {e(a["via"])}</span>' if a["via"] else ""
    return (f'<div class="signature">{lien_auteur(a)}{via}<span>{e(a["journal"])}</span>{puce_pays(a)}'
            f'<time datetime="{a["date"][:10]}">{date_ar(a["date"])}</time></div>')


def carte(a, classe="", niveau="h3"):
    couv = COUVERTURES.get(a["id"])
    image = f'<img class="couv" src="couvertures/{couv}" alt="" loading="lazy">' if couv else ""
    return (f'<article class="carte {classe} s-{a["section"]}" data-id="{a["id"]}">{image}<div class="contenu">{rubrique(a)}'
            f'<{niveau}><a class="titre" href="a-{a["id"]}.html">{e(a["titre"])}</a></{niveau}>'
            f'<p class="resume">{e(a["chapeau"])}</p>{signature(a)}</div></article>')


def grille(arts):
    return '<div class="grille">' + "".join(carte(a) for a in arts) + "</div>"


def bloc(titre, contenu, lien="", classe="bloc-or"):
    plus = f'<a href="{lien}">عرض الكل ←</a>' if lien else ""
    return f'<section class="bloc {classe}"><div class="bloc-tete"><h2>{titre}</h2>{plus}</div>{contenu}</section>'


def photo(cle, classe="photo"):
    """Photo libre d'une personne avec son crédit obligatoire (auteur, licence, lien vers Commons)."""
    c = CREDITS_PHOTOS.get(cle)
    if not c:
        return ""
    licence = (f'<a href="{e(c["licence_url"])}" rel="license noopener" target="_blank">{e(c["licence"])}</a>'
               if c["licence_url"] else e(c["licence"]))
    return (f'<figure class="{classe}"><img src="photos/{e(c["fichier"])}" alt="{e(PERSONNES.get(cle, ""))}" loading="lazy">'
            f'<figcaption>الصورة: <bdi>{e(c["auteur"])}</bdi> · {licence} · '
            f'<a href="{e(c["source"])}" target="_blank" rel="noopener">ويكيميديا كومنز</a></figcaption></figure>')


def liste(sur_titre, titre, arts, description="", actif=None, classe="", sous_titre="", visuel=""):
    tete = (f'<header class="tete-liste {classe}">{visuel}<div><span class="sur-titre">{sur_titre}</span><h1>{e(titre)}</h1>'
            f'{sous_titre}{f"<p>{description}</p>" if description else ""}<span class="compte">{compte(len(arts))}</span></div></header>')
    return page(titre, tete + (grille(arts) if arts else VIDE), actif)


def fil(arts):
    """Liste chronologique compacte (revue de presse, dernières nouvelles)."""
    return '<ol class="fil">' + "".join(
        f'<li class="s-{a["section"]}" data-id="{a["id"]}">{rubrique(a)}<a class="titre" href="a-{a["id"]}.html">{e(a["titre"])}</a>'
        f'<p>{e(a["chapeau"])}</p>{signature(a)}</li>' for a in arts) + "</ol>"


def page_accueil(arts):
    if not arts:
        return page("الرئيسية", VIDE, "index")
    avis = [a for a in arts if a["section"] != "actus"] or arts  # la une reste aux articles d'opinion
    nouvelles = [a for a in arts if a["section"] == "actus"]
    une, cote, suite = avis[0], avis[1:3], avis[3:12]
    corps = (f'<section class="a-la-une" aria-label="أبرز المقالات">{carte(une, "une", "h2")}'
             f'<div class="cote">{"".join(carte(a, "compacte") for a in cote)}</div></section>')
    if nouvelles:
        corps += bloc("آخر الأخبار", fil(nouvelles[:6]), "actus.html", "s-actus")
    if suite:
        corps += bloc("أحدث المقالات", grille(suite))
    affiches = {a["id"] for a in avis[:12]}
    for k, v in SECTIONS.items():
        autres = [a for a in avis if a["section"] == k and a["id"] not in affiches][:3]
        if autres:
            corps += bloc(v, grille(autres), f"{k}.html", f"s-{k}")
    pays, plumes = defaultdict(int), defaultdict(int)
    for a in arts:
        if a["pays"]:
            pays[a["pays"]] += 1
        if a["auteur"]:
            plumes[(slug(a["auteur"]), a["auteur_ar"])] += 1
    nuage_pays = "".join(f'<a href="pays-{p}.html">{PAYS.get(p, p)}<small>{n}</small></a>'
                         for p, n in sorted(pays.items(), key=lambda x: -x[1]))
    nuage_plumes = "".join(f'<a href="j-{s}.html">{e(nom)}<small>{n}</small></a>'
                           for (s, nom), n in sorted(plumes.items(), key=lambda x: -x[1])[:12])
    corps += (f'<div class="deux">{bloc("الصحافة العالمية", f"<div class=nuage>{nuage_pays}</div>", "presse.html")}'
              f'{bloc("أقلام", f"<div class=nuage>{nuage_plumes}</div>")}</div>')
    return page("الرئيسية", corps, "index")


def copiable(texte, cle, compteur=""):
    return (f'<li class="copiable" data-cle="{cle}"><pre class="a-copier" dir="auto">{e(texte)}</pre><div class="outils">'
            f'<small>{compteur}</small><button type="button" class="copier">نسخ</button></div></li>')


def fenetre(id_, titre, contenu):
    return (f'<dialog id="{id_}" class="fenetre"><h2>{titre}</h2>{contenu}'
            f'<label class="publie"><input type="checkbox" data-pub="{id_}"> تم النشر</label>'
            '<form method="dialog"><button class="fermer">إغلاق</button></form></dialog>')


LOGO_X = ('<svg viewBox="0 0 24 24" aria-label="X" role="img"><path d="M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584'
          '-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z"/></svg>')
LOGO_FB = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.101 23.691v-7.98H6.627v-3.667h2.474v-1.58c0-4.085 1.848-5.978 '
           '5.858-5.978.401 0 .955.042 1.468.103a8.68 8.68 0 0 1 1.141.195v3.325a8.623 8.623 0 0 0-.653-.036 26.805 26.805 0 0 0'
           '-.733-.009c-.707 0-1.259.096-1.675.309a1.686 1.686 0 0 0-.679.622c-.258.42-.374.995-.374 1.752v1.297h3.919l-.386 2.103'
           '-.287 1.564h-3.246v8.245C19.396 23.238 24 18.179 24 12.044c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.628 3.874 10.35 '
           '9.101 11.647Z"/></svg>')


def partage(a):
    """Boutons X (thread tweet par tweet) et Facebook (titres FR/EN/ES + lien de la source), à copier-coller."""
    i, couv, tweets = a["id"], COUVERTURES.get(a["id"]), THREADS.get(a["id"], [])
    fb = json.loads(a["titres_fb"]) if a["titres_fb"] else {}
    post = "\n".join(f"{d} {fb[k]}" for d, k in (("⚜️", "fr"), ("🇨🇦", "en"), ("🇪🇸", "es")) if fb.get(k))
    post = f"{post}\n\n{a['lien']}" if post else a["lien"]  # articles d'avant les titres traduits : le lien seul
    boutons = f'<button type="button" class="b-fb" data-ouvre="fb-{i}">{LOGO_FB}نشر على فيسبوك</button>'
    fenetres = fenetre(f"fb-{i}", "منشور فيسبوك", f'<ul class="tweets">{copiable(post, f"fb-{i}")}</ul>')
    if tweets:
        image = f'<a class="bouton" href="couvertures/{couv}" download>تنزيل صورة التغريدة الأولى</a>' if couv else ""
        liste_tw = "".join(copiable(t, f"x-{i}-{n}", f"{threads.longueur(t)}/{threads.LIMITE}")
                           for n, t in enumerate(tweets, 1))
        boutons = f'<button type="button" class="b-x" data-ouvre="x-{i}">{LOGO_X}ثريد ({len(tweets)})</button>' + boutons
        fenetres += fenetre(f"x-{i}", "ثريد X", f'{image}<ol class="tweets">{liste_tw}</ol>')
    return f'<div class="partage">{boutons}</div>{fenetres}'


def page_article(a, arts):
    paragraphes = "".join(f"<p>{e(p)}</p>" for p in a["texte"].split("\n\n") if p.strip())
    tags = "".join(f'<a href="p-{p}.html">{e(PERSONNES[p])}</a>' for p in json.loads(a["personnes"]) if p in PERSONNES)
    nom = f'{e(a["auteur_ar"])} (<bdi class="latin">{e(a["auteur"])}</bdi>)'
    traduction = a["mode"] == "traduction"
    badge = "ترجمة كاملة" if traduction else "ملخص وتعليق"
    if a["section"] == "actus":
        badge = "خبر"
        nature = "ترجمة تصريحات المؤتمر الصحفي كما نقلتها" if a["mode"] == "conference" else "ملخص خبر نشرته"
        origine = f"{nature} {e(a['journal'])}" + (f" بقلم {nom}" if a["auteur"] else "")
    elif a["via"]:  # avis d'un commentateur rapporté par un journaliste
        par = f' بقلم <bdi class="latin">{e(a["rapporteur"])}</bdi>' if a["rapporteur"] else ""
        origine = f"ملخص لآراء {nom} عن {e(a['via'])}، كما نقلها مقال{par} في {e(a['journal'])}"
    else:
        signe = f" للكاتب {nom}" if a["auteur"] else ""
        nature = "ترجمة كاملة بإذن من المصدر" if traduction else "ملخص وتعليق على مقال رأي"
        origine = f"{nature}{signe} في {e(a['journal'])}"
    auteur = (f'<div class="auteur-bloc"><span class="avatar" aria-hidden="true">{e(a["auteur_ar"][:1])}</span>'
              f'<div>{lien_auteur(a)}<bdi class="latin" dir="ltr">{e(a["auteur"])}</bdi></div></div>') if a["auteur"] else ""
    via = f'<span>عن {e(a["via"])}</span>' if a["via"] else ""
    infos = (f'<div class="infos">{via}<span>{e(a["journal"])}</span>{puce_pays(a)}'
             f'<time datetime="{a["date"][:10]}">{date_ar(a["date"])}</time><span>{duree(a["texte"])}</span></div>')
    couv = COUVERTURES.get(a["id"])
    couverture = (f'<figure class="couverture"><img src="couvertures/{couv}" alt="{e(a["citation"] or a["titre"])}">'
                  "</figure>") if couv else ""
    proches = [x for x in arts if x["section"] == a["section"] and x["id"] != a["id"]][:3]
    cote = (f'<aside class="proches"><h2>من القسم نفسه</h2>{"".join(carte(x, "compacte") for x in proches)}</aside>'
            if proches else "")
    corps = (
        f'<div class="mise-en-page"><article class="lecture s-{a["section"]}">'
        f'<div class="haut">{rubrique(a)}<span class="nature">{badge}</span></div>'
        f'<h1>{e(a["titre"])}</h1><p class="chapeau">{e(a["chapeau"])}</p>'
        f'<div class="tete-auteur">{auteur}{infos}</div>'
        f'{partage(a)}{couverture}'
        f'<div class="texte">{paragraphes}</div>'
        f'{f"<div class=etiquettes><strong>في هذا المقال:</strong>{tags}</div>" if tags else ""}'
        f'<aside class="source"><h2>المقال الأصلي</h2><p class="titre-original"><bdi dir="auto">{e(a["titre_original"])}</bdi></p>'
        f'<p>{origine}.</p>'
        f'<a class="bouton" href="{e(a["lien"])}" target="_blank" rel="noopener">اقرأ المقال الأصلي</a></aside>'
        f"</article>{cote}</div>"
    )
    return page(a["titre"], corps, a["section"], f"couvertures/{couv}" if couv else "")


def page_revue(arts, jours=14):
    par_jour = defaultdict(list)
    for a in arts:
        par_jour[a["date"][:10]].append(a)
    corps = ('<header class="tete-liste bloc-or"><span class="sur-titre">كل يوم</span><h1>مراجعة الصحافة</h1>'
             "<p>ما كتبته الصحافة العالمية عن ريال مدريد، يومًا بيوم.</p></header>")
    for jour in sorted(par_jour, reverse=True)[:jours]:
        corps += (f'<section class="jour"><h2><time datetime="{jour}">{date_ar(jour)}</time>'
                  f'<span>{compte(len(par_jour[jour]))}</span></h2>{fil(par_jour[jour])}</section>')
    return page("مراجعة الصحافة", corps if arts else corps + VIDE, "revue")


def page_presse(arts):
    par_pays = defaultdict(list)
    for a in arts:
        if a["pays"]:
            par_pays[a["pays"]].append(a)
    tuiles = "".join(
        f'<a class="tuile" href="pays-{p}.html"><strong>{PAYS.get(p, p)}</strong><span class="nb">{len(l)}</span>'
        f'<small>{e("، ".join(sorted({a["journal"] for a in l})))}</small></a>'
        for p, l in sorted(par_pays.items(), key=lambda x: -len(x[1])))
    corps = ('<header class="tete-liste bloc-or"><span class="sur-titre">مصادرنا</span><h1>الصحافة العالمية</h1>'
             "<p>الصحافة الإسبانية أولًا، ثم الأوروبية، ثم صحافة بلدان لاعبي ريال مدريد.</p></header>")
    return page("الصحافة العالمية", corps + (f'<div class="tuiles">{tuiles}</div>' if tuiles else VIDE), "presse")


def rendre_site(chemin=DB, dossier=SITE, credits=CREDITS):
    CREDITS_PHOTOS.clear()
    if credits.exists():
        CREDITS_PHOTOS.update({k: c for k, c in json.loads(credits.read_text(encoding="utf-8")).items() if c})
    con = connexion(chemin)
    arts = con.execute("SELECT * FROM articles ORDER BY date DESC, id DESC").fetchall()
    threads.connexion_threads(con)
    THREADS.clear()
    THREADS.update({i: json.loads(t) for i, t in con.execute("SELECT article_id, tweets FROM threads")})
    con.close()
    dossier.mkdir(exist_ok=True)
    COUVERTURES.clear()
    COUVERTURES.update(generer_couvertures(arts, dossier))
    fichiers = {"style.css": CSS, "site.js": JS, "index.html": page_accueil(arts),
                "revue.html": page_revue(arts), "presse.html": page_presse(arts)}
    for k, v in SECTIONS.items():
        fichiers[f"{k}.html"] = liste("قسم", v, [a for a in arts if a["section"] == k], DESCRIPTIONS[k], k, f"s-{k}")
    groupes, entetes = defaultdict(list), {}  # pages d'étiquettes : journaliste, personne, pays

    def ajouter(nom, a, *entete):
        groupes[nom].append(a)
        entetes.setdefault(nom, entete)  # le plus récent donne le titre (ex. nom arabe du journaliste)

    for a in arts:
        fichiers[f"a-{a['id']}.html"] = page_article(a, arts)
        if a["auteur"]:
            ajouter(f"j-{slug(a['auteur'])}.html", a, "معلّق" if a["via"] else "كاتب رأي", a["auteur_ar"],
                    f'<bdi class="latin" dir="ltr">{e(a["auteur"])}</bdi>', None)
        for p in json.loads(a["personnes"]):
            if p in PERSONNES:
                ajouter(f"p-{p}.html", a, "ملف", PERSONNES[p], "", None, photo(p, "portrait"))
        if a["pays"]:
            ajouter(f"pays-{a['pays']}.html", a, "الصحافة العالمية", PAYS.get(a["pays"], a["pays"]), "", "presse")
    for nom, liste_arts in groupes.items():
        sur_titre, titre, sous, actif, *visuel = entetes[nom]
        fichiers[nom] = liste(sur_titre, titre, liste_arts, actif=actif, classe="bloc-or", sous_titre=sous,
                              visuel="".join(visuel))
    for ancien in dossier.glob("*.html"):  # pages devenues inutiles (article supprimé, auteur renommé)
        if ancien.name not in fichiers:
            ancien.unlink()
    for nom, contenu in fichiers.items():
        (dossier / nom).write_text(contenu, encoding="utf-8")
    return dossier / "index.html"


DIRECT = re.compile(r"en directo|en vivo|minuto a minuto|en direct\b|as it happened|live blog|/live/|-directo-|canlı anlatım", re.I)


def est_direct(it):
    """Direct commenté d'un match : écarté avant Claude (faits de jeu sans intérêt une fois le match fini)."""
    return bool(DIRECT.search(it["titre"] + " " + it["lien"]))


# horaires TV et paris : écartés gratuitement avant Claude (les compositions probables, elles, passent)
PRATIQUE = re.compile(r"a qu[ée] hora|d[óo]nde ver|ver-television|por televisi[óo]n|en qu[ée] canal|qu[ée] canal|"
                      r"sur quelle cha[iî]ne|[àa] quelle heure|where to watch|what time is|tv channel|hangi kanal|"
                      r"pron[óo]stico|apuestas|cuotas|pronostic|betting|onde assistir|que horas", re.I)


def est_pratique(it):
    return bool(PRATIQUE.search(it["titre"] + " " + it["lien"]))


def alterner_pays(items):
    """Un article par pays à tour de rôle, pour que la presse étrangère ne passe pas toujours après l'espagnole."""
    groupes = defaultdict(list)
    for it in items:
        groupes[it.get("pays")].append(it)
    return [it for tour in zip_longest(*groupes.values()) for it in tour if it]


def ordonner(items):
    """Rubriques d'opinion d'abord (meilleur rendement), puis le reste ; pays alternés dans chaque groupe."""
    return alterner_pays([it for it in items if it.get("opinion")]) + alterner_pays([it for it in items if not it.get("opinion")])


def traiter_lot(lot):
    """Lit les articles, fait rédiger Claude, enregistre. Retourne le nombre d'articles ajoutés (None si réponse illisible)."""
    for it in lot:
        it["texte"] = texte_complet(it)
    reponse = appeler_claude(construire_prompt(lot, deja_publies()), CONFIG.get("modele_redaction", "sonnet"))
    try:
        reponses = extraire_json(reponse)
    except (ValueError, json.JSONDecodeError) as err:
        (BASE / "sortie" / "derniere_reponse_site.txt").write_text(reponse, encoding="utf-8")
        print(f"  ! réponse illisible ({err}), sauvegardée dans sortie/derniere_reponse_site.txt ; lot repris au prochain passage")
        return None
    n = enregistrer(reponses, lot)
    marquer_vus(lot, DB)
    return n


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="montre les lots prévus, sans Claude")
    ap.add_argument("--rendre", action="store_true", help="régénère seulement les pages")
    ap.add_argument("--photos", action="store_true", help="récupère seulement les photos manquantes, puis régénère")
    ap.add_argument("--threads", action="store_true", help="prépare et envoie seulement les threads X sur Telegram")
    args = ap.parse_args()

    if not args.rendre and not args.test and not args.threads:
        mettre_a_jour_photos()
    if not args.rendre and not args.photos and not args.threads:
        print("Collecte des flux...")
        # liens Google News = redirections : ni auteur ni texte lisible
        items = [it for it in collecter(DB, CONFIG.get("age_max_heures_site", 24))
                 if not it["lien"].startswith("https://news.google.com") and not est_direct(it) and not est_pratique(it)]
        for it in items:
            if "@" in it["auteur"]:  # "info@vi.nl (Voetbal International)" n'est pas un journaliste
                it["auteur"] = ""
        items, doublons = dedoublonner(items)
        items = ordonner(items)
        if items and not args.test:
            candidats = items[:60]  # au-delà : triés au prochain passage
            print(f"Tri de {len(candidats)} article(s) sur titre et chapeau...")
            tri = trier(candidats, deja_publies())
            if tri:  # sinon (réponse illisible) : tout est rédigé comme avant
                gardes, ecartes = tri
                marquer_vus(ecartes, DB)
                print(f"  {len(gardes)} gardé(s), {len(ecartes)} écarté(s) :")
                for it in ecartes:  # pour contrôler la qualité du tri dans le journal du passage
                    print(f"    - {journal(it)} | {it['titre'][:100]}")
                items = gardes
        taille = CONFIG.get("max_articles_site", 8)
        lots = [items[i:i + taille] for i in range(0, len(items), taille)][:CONFIG.get("max_lots_site", 5)]
        reste = len(items) - sum(len(lot) for lot in lots)  # repris au prochain passage
        print(f"{len(items)} article(s) en attente : {len(lots)} lot(s) de {taille} cette fois, {reste} reporté(s).")
        if args.test:
            for n, lot in enumerate(lots, 1):
                print(f"\nLot {n}")
                for it in lot:
                    marque = "opinion · " if it.get("opinion") else ""
                    print(f"- [{marque}{it.get('pays')} · {journal(it)} · {it['auteur'] or '?'}] {it['titre']}")
            return
        marquer_vus(doublons, DB)
        total = 0
        for n, lot in enumerate(lots, 1):
            print(f"Lot {n}/{len(lots)} : lecture et rédaction par Claude (quelques minutes)...")
            ajoutes = traiter_lot(lot)
            if ajoutes is not None:
                total += ajoutes
                print(f"  {ajoutes} article(s) d'opinion retenu(s) sur {len(lot)}.")
        print(f"{total} article(s) ajouté(s) au site.")

    index = rendre_site()
    print(f"\n✅ Site : {index}")
    if not args.rendre and not args.photos:
        con = connexion()
        print(f"Threads X : {threads.decouper(con)} préparé(s), "
              f"{threads.envoyer(con, COUVERTURES, SITE / 'couvertures', SECTIONS)} envoyé(s) sur Telegram.")
        con.close()
    if hasattr(os, "startfile"):
        os.startfile(index)


if __name__ == "__main__":
    main()

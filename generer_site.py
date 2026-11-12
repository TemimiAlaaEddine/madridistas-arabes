#!/usr/bin/env python3
"""Madridistas arabes - site statique d'articles d'opinion sur le Real Madrid, en arabe.

Collecte (flux de config.json) -> articles (hors Google News) -> lecture du texte complet ->
Claude rédige un résumé commenté (ou une traduction si la source a donné son
autorisation : "autorisation": true dans config.json) -> articles.db -> pages HTML dans site/.
Dans git, la base est gardée en texte (articles.sql) : reconstruite au démarrage si elle est plus récente.

Usage :
  python generer_site.py            # collecte + rédaction + régénère le site
  python generer_site.py --test     # montre les articles retenus, sans Claude
  python generer_site.py --rendre   # régénère seulement les pages (après une retouche du CSS...)
  python generer_site.py --threads  # régénère les pages, puis threads X (Typefully) et publications sur la Page Facebook
"""
import argparse
import json
import os
import re
import sqlite3
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import zip_longest
from datetime import datetime
from difflib import SequenceMatcher
from html.parser import HTMLParser

import threads
from commun import (BASE, CONFIG, GABARITS, NOM_SITE, PAYS, SECTIONS, ErreurClaude, appeler_claude, collecter, dedoublonner, e,
                    extraire_json, maintenant, marquer_vus, nettoyer, normaliser_titre, restaurer_base)
from couvertures import generer_couvertures, vignette

DB = BASE / "articles.db"
SITE = BASE / "site"
FICHES = CONFIG.get("personnes", {})  # une fiche par personne : {"nom": arabe, "wikipedia": page, "photo": fichier Commons}
PERSONNES = {k: f["nom"] for k, f in FICHES.items()}
CREDITS = BASE / "photos.json"  # photos libres déjà récupérées : {cle: {fichier, auteur, licence...} ou null}
UA = {"User-Agent": "MadridistasArabes/1.0 (projet personnel)"}  # Wikimedia refuse les requêtes sans User-Agent


# ---------- texte complet de l'article ----------
class Paragraphes(HTMLParser):
    """Récupère le texte des balises <p> d'une page, hors scripts et styles, ses intertitres (<h2>, <h3>) et son image
    principale (og:image). Les intertitres portent souvent le nom du joueur dont parle le passage (« Kubo », « Odegaard ») :
    sans eux, le texte parle d'« un joueur venu de Tokyo » sans jamais le nommer."""

    def __init__(self):
        super().__init__()
        self.dans_p, self.ignore = "", 0
        self.courant, self.morceaux = [], []
        self.image = self.intertitre = ""

    def handle_starttag(self, tag, attrs):
        if tag == "meta" and not self.image:
            d = dict(attrs)
            if (d.get("property") or d.get("name") or "").lower() in ("og:image", "twitter:image"):
                self.image = (d.get("content") or "").strip()
        if tag in ("script", "style"):
            self.ignore += 1
        elif tag in ("p", "h2", "h3"):
            self.dans_p, self.courant = tag, []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.ignore = max(0, self.ignore - 1)
        elif tag == self.dans_p:
            self.dans_p = ""
            t = " ".join("".join(self.courant).split())
            if tag != "p":  # gardé seulement s'il précède un paragraphe : écarte menus et listes d'articles liés
                self.intertitre = t if 3 <= len(t) <= 120 else ""
            elif len(t) > 60:  # écarte légendes, boutons, mentions
                if self.intertitre and self.morceaux:  # jamais avant le 1er paragraphe (titres de l'entête)
                    self.morceaux.append(self.intertitre)
                self.intertitre = ""
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
            p.feed(r.read().decode(r.headers.get_content_charset() or "utf-8", "replace"))  # ex. presse turque en windows-1254
        page = "\n".join(p.morceaux)
        image = urllib.parse.urljoin(it["lien"], p.image) if p.image else ""
        if image.startswith(("http://", "https://")):  # celle de la page, plus grande, sinon on garde celle du flux
            it["image"] = image
    except Exception as err:  # noqa: BLE001 - page bloquée (403, abonnement...) : on garde le flux
        print(f"  ! page illisible ({err}) : {it['lien'][:70]}")
        it["illisible"] = True
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
   - À ignorer : pronostics et paris, horaires TV, compositions probables (sauf celles de Marca et AS, à garder ; garde aussi la composition officielle), directs et faits de jeu pendant un match, autres clubs ou autres sports (y compris le basket du Real Madrid).
   - Information sur le Bernabéu, à garder : travaux, recettes, et les événements organisés dans le stade (ex. le match de NFL au Bernabéu, un concert). Seulement au Bernabéu : un match de NFL dans un autre stade reste à ignorer.
   - Doublons : si plusieurs articles de cette liste rapportent le même fait ou les mêmes propos d'une même personne (même dans des médias ou des langues différents, et même si leurs titres mettent en avant des angles différents, ex. deux articles sur la même conférence de presse), fusionne-les en un seul article : réponds avec l'id du plus complet, et complète son texte avec les éléments nouveaux des autres en citant leur média. Si ce fait ou ces propos sont déjà dans la liste « DÉJÀ PUBLIÉ » plus bas, ignore-les.
2. Classe-le dans une section : actus pour toute information, sauf celles sur le Bernabéu, qui vont dans club ; pour une opinion : tactique (jeu, système, rendement des joueurs), mercato (transferts, contrats, recrutement), club (finances, présidence, stade, institutions, droits TV), debats (polémiques et actualité commentée).
3. Rédige en arabe standard moderne, dans la langue vivante de la bonne presse sportive arabe : celle d'un journaliste qui raconte à des supporters, pas celle d'un compte rendu ni d'une traduction.
{style}
   - Information (actus, ou club pour le Bernabéu) : 120 à 200 mots, uniquement les faits. La première phrase donne le fait lui-même (qui, quoi, quand) ; le média est cité dans cette phrase ou la suivante (...بحسب «ماركا»، كما كشفت «آس»...), jamais en tête : ne commence pas par « وفقًا لـ ». Ensuite le contexte utile tiré du texte, du plus important au moins important. Si l'information n'est pas confirmée, utilise une formule de prudence (حسب ما ذكرت...). Pas de citation de plus de 15 mots. Pour une composition officielle ou probable (Marca, AS) : les 11 titulaires (noms arabes usuels) et l'adversaire, sans limite de mots, en précisant si elle est officielle ou probable.
   - Opinion, selon le « Mode » indiqué :
     - Mode résumé : un article de 400 à 600 mots qui porte la thèse, chacun des arguments et la conclusion de l'auteur avec tes propres mots, construit comme un article et non comme un compte rendu. Ne traduis pas l'article phrase par phrase.
       - Attaque : commence par ce que l'article a de plus fort (son constat, un chiffre, une scène, la question qu'il pose), jamais par « يرى الكاتب... » ni par le nom du journal. L'auteur et son journal sont nommés dans les deux premières phrases, à l'intérieur de la phrase, sous une forme qui change d'un article à l'autre.
       - Développement : les arguments dans l'ordre le plus clair, une idée par paragraphe de 2 à 4 phrases. L'avis reste toujours visiblement celui de l'auteur, mais une seule attribution par paragraphe suffit, par son nom ou par une tournure variée (بحسبه، في نظره، يذهب أبعد من ذلك، يعترف، يحذّر، حجّته الثانية...). Ne commence pas deux paragraphes de suite par un verbe d'attribution (ويرى، ويضيف، ويوضح، ويذكّر).
       - Intertitres : au-delà de 350 mots, 2 ou 3 intertitres de 2 à 5 mots, chacun seul sur sa ligne, précédé de « ## » et séparé du reste par une ligne vide.
       - Chute : la conclusion de l'auteur ou sa phrase la plus marquante, sans « ويختم الكاتب بأن... » ni résumé de ce qui précède.
       - Au maximum 4 citations courtes traduites (moins de 25 mots chacune) entre guillemets «».
     - Mode traduction : traduction intégrale et fidèle du texte fourni, dans un arabe qui se lit comme un texte écrit en arabe.
   - Mode conférence (conférence de presse d'un entraîneur, section actus) : traduis fidèlement et intégralement toutes les déclarations de l'entraîneur présentes dans le texte (la limite de 15 mots ne s'applique pas), sans reprendre les phrases du journaliste. Présente-les par sujet : chaque sujet commence par la question ou le thème résumé en une ligne, suivi de ses réponses entre guillemets «». Une phrase d'introduction : qui parle, quand, avant ou après quel match.
4. N'ajoute aucun fait ni aucun avis absent des textes fournis. L'avis est celui de l'auteur, jamais celui du site, du média ou du club. Le style vivant ne change rien à cette règle : il porte sur la manière de dire, jamais sur ce qui est dit. Ne devine pas un nom que le texte ne donne pas.
5. Auteur : s'il est indiqué « inconnu », cherche la signature dans le texte ; si tu ne la trouves pas, laisse "auteur" vide. L'auteur est toujours une personne : si l'article n'est signé que par le journal, une agence (EFE, Europa Press, AFP, Reuters) ou une mention comme « Redacción », laisse "auteur" et "auteur_ar" vides (le site citera seulement le journal). Donne le nom tel qu'il est écrit ("auteur") et translittéré en arabe ("auteur_ar") : si l'auteur est indiqué, recopie exactement ce nom dans "auteur" et translittère ce nom-là, jamais celui d'un autre article de la liste.
   Quand une graphie arabe est donnée entre parenthèses après le journal ou l'auteur (« en arabe : ... »), écris ce nom exactement ainsi partout : "auteur_ar", titre, chapeau, texte et tweets.
   Si l'article rapporte surtout l'avis d'un commentateur (radio, télévision, podcast, entretien) plutôt que celui de son auteur, mets ce commentateur dans "auteur"/"auteur_ar", présente l'avis comme le sien, et indique en "via" le média où il s'est exprimé, en arabe (ex. : راديو ماركا). Sinon laisse "via" vide.
6. Liste les personnes dont parle l'article, la principale en premier, uniquement parmi ces clés : {personnes}
   "sujet" : la clé de la personne dont l'article parle principalement, seulement si elle est dans cette liste ; sinon "" (ex. : article centré sur un joueur absent de la liste, ou sur le club en général).
7. "citation" : la phrase la plus forte de ton texte arabe (idée centrale ou formule marquante), 8 à 20 mots, sans guillemets. Pour une information : le fait principal en une phrase.
8. "chiffres" : seulement si l'article repose sur des chiffres marquants (statistiques, montants, records), jusqu'à 3 objets {{"valeur": "100", "libelle": "هدف بقميص ريال مدريد"}} : valeur courte (ex. "61,3%", "180 م€"), libellé arabe de 2 à 6 mots, tirés du texte. Sinon [].
9. "tweets" : le thread X (Twitter) tiré de ton texte arabe, pour le compte « المدريديستا علاء » :
{regles_tweets}
10. "titres_fb" : ton titre arabe traduit pour un groupe Facebook de supporters à Montréal, une phrase courte et naturelle en français, en anglais et en espagnol, noms propres dans leur graphie latine usuelle.
11. "faits" : au plus 2 faits durables établis par le texte, utiles à une mémoire de la saison, en français, une phrase courte chacun avec la date quand elle est connue. Seulement : score final et buteurs d'un match du Real Madrid, blessure ou absence de plus de deux semaines, transfert ou prolongation officiels, changement de système ou de poste d'un joueur, record ou distinction. Jamais de rumeur, d'avis ni de déclaration. Sinon [].

FORMAT DE RÉPONSE
Réponds UNIQUEMENT avec un tableau JSON valide, sans texte avant ni après, sans bloc de code :
[{{"id": 1, "section": "actus|tactique|mercato|club|debats", "titre": "...", "chapeau": "جملة أو جملتان", "texte": "paragraphes séparés par \\n\\n", "auteur": "...", "auteur_ar": "...", "via": "", "personnes": ["mbappe"], "sujet": "mbappe", "citation": "...", "chiffres": [], "tweets": ["...", "..."], "titres_fb": {{"fr": "...", "en": "...", "es": "..."}}, "faits": []}}]
Si aucun article ne convient, réponds [].

DÉJÀ PUBLIÉ CES DERNIERS JOURS (informations et propos à ne pas reprendre, sauf fait vraiment nouveau)
{deja}

ARTICLES
{articles}
"""


# style commun à tous les textes du site. Mesuré le 12 nov. 2026 sur 327 articles : 72 % commençaient par « وفقًا » ou
# « يرى », et un paragraphe sur quatre par « ويرى / ويضيف / ويختم الكاتب » : c'est ce ton de compte rendu qu'il corrige.
STYLE = """   Style, pour tous les textes :
   - Écris directement en arabe à partir des idées, sans calquer la phrase d'origine : ordre des mots arabe, phrases courtes à moyennes, verbes actifs, enchaînements variés (لكنّ، في المقابل، والنتيجة، بل...). Si une tournure sonne traduite, redis-la comme un journaliste arabe l'écrirait.
   - Le vocabulaire du football tel que le public arabe le lit : noms arabes usuels des joueurs et des clubs, termes consacrés (الملكي، الميرينغي، دكة البدلاء، الهجمة المرتدة، الضغط العالي...). Ni mots rares, ni tournures administratives (قام بـ، تمّ + مصدر، بشكل ملحوظ، في هذا الصدد).
   - Le concret avant l'abstrait : le chiffre, la scène, la phrase qui frappe plutôt que le commentaire général.
   - Sobre : pas de formules creuses ni d'exagération (مفاجأة مدوية، زلزال، قنبلة), pas de point d'exclamation, pas de faux suspense. Le titre et le chapeau promettent seulement ce que le texte donne.
   - Varie : deux articles du même lot ne commencent pas de la même façon et n'ont pas le même moule de titre.
   - Relis chaque texte avant de répondre : aucune faute de frappe, aucun mot qui n'existe pas, et aucun dernier paragraphe qui commence par « ويختم » ou « وخلاصة ».
   Titre : 6 à 12 mots, l'angle le plus fort de l'article (une idée tranchée, un chiffre, une courte citation entre «», une vraie question) plutôt que son simple sujet. Pas de « في ريال مدريد » ajouté par habitude en fin de titre.
   Chapeau : une ou deux phrases qui donnent envie de lire (l'enjeu, ce qui surprend, ce qui divise), sans répéter le titre et sans commencer par le nom de l'auteur ou du journal."""


def journal(it):
    return it["source"].split(" - ")[0]  # "Marca - Opinion" -> "Marca"


# signatures qui ne sont pas des personnes : le site affiche alors seulement le journal
SIGNATURES_GENERIQUES = {"efe", "agencia-efe", "europa-press", "afp", "reuters", "ap", "dpa", "ansa", "lusa", "astv", "laliga",
                         "real-madrid", "staff", "sport", "deportes", "football", "futbol"}


def meme_nom(a, b):
    """Même personne, aux majuscules, accents et initiales près (« SERGIO RODRÍGUEZ C. » = « Sergio Rodríguez »)."""
    a, b = slug(a or ""), slug(b or "")
    return bool(a and b) and (a in b or b in a)


def auteur_reel(nom, journal_nom):
    """Le nom s'il désigne une personne ; "" pour le journal lui-même, une agence, « Redacción »... ou une adresse e-mail."""
    s = slug(nom or "")
    if not nom or "@" in nom or s in SIGNATURES_GENERIQUES or s == slug(journal_nom) or any(m in s for m in ("redac", "agenc", "redaz")):
        return ""
    return nom


def noms_arabes(con):
    """Graphie arabe de référence d'un journaliste ou d'un média, par slug de son nom latin : celle de "noms_ar" dans
    config.json, sinon la plus fréquente en base. Sans elle, le même nom changeait d'un article à l'autre
    (Kiyan Sobhani : سبحاني، صوباني، سوبهاني)."""
    votes = defaultdict(Counter)
    for auteur, ar in con.execute("SELECT auteur, auteur_ar FROM articles WHERE auteur != '' ORDER BY id"):
        if re.search(r"[؀-ۿ]", ar or ""):  # pas les noms restés en lettres latines
            votes[slug(auteur)][ar] += 1
    noms = {k: v.most_common(1)[0][0] for k, v in votes.items()}
    noms.update({slug(k): v for k, v in CONFIG.get("noms_ar", {}).items()})
    return noms


def construire_prompt(items, deja=(), noms=None):
    blocs = []
    for i, it in enumerate(items, 1):
        mode = "traduction" if it.get("autorise") else "conférence" if it.get("type") == "conference" else "résumé"
        ar = lambda n: f" (en arabe : {noms[slug(n)]})" if n and noms and slug(n) in noms else ""  # noqa: E731
        blocs.append(f"[{i}] Journal : {journal(it)}{ar(journal(it))}\nAuteur : {it['auteur'] or 'inconnu'}{ar(it['auteur'])}\nMode : {mode}\n"
                     f"Titre : {it['titre']}\nTexte :\n{it['texte']}")
    personnes = ", ".join(f"{k} ({v})" for k, v in PERSONNES.items())
    deja = "\n".join(f"- {t}" for t in deja) or "(aucune)"
    return PROMPT.format(personnes=personnes, deja=deja, articles="\n\n".join(blocs), regles_tweets=threads.REGLES, style=STYLE)


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
- info : information importante sur le Real Madrid (blessure, transfert, contrat, déclaration marquante, décision du club, distinction, résultat final, composition officielle), anecdotes et coulisses, et tout ce qui touche au Bernabéu (travaux, recettes, événements organisés dans le stade comme le match de NFL ou un concert) ; compositions probables seulement si le journal est Marca ou AS.
Écarte : horaires TV, pronostics et paris, directs et faits de jeu pendant un match, autres clubs ou autres sports (dont le basket du Real Madrid et la NFL hors du Bernabéu), autres compositions probables.
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
        citation TEXT, chiffres TEXT, titres_fb TEXT, image TEXT)""")
    # faits durables notés par Claude à la rédaction, relus et validés par /script vers connaissance.md
    con.execute("CREATE TABLE IF NOT EXISTS faits (id INTEGER PRIMARY KEY, article_id INTEGER, date TEXT, fait TEXT)")
    for colonne in ("via", "rapporteur", "sujet", "citation", "chiffres", "titres_fb", "image"):  # bases créées avant l'ajout de ces colonnes
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


def noter_faits(con, article_id, faits, now):
    """Garde au plus 2 faits par article, sans reprendre un fait déjà noté ces 14 derniers jours (même info, autre journal)."""
    connus = [normaliser_titre(f) for (f,) in con.execute("SELECT fait FROM faits WHERE date >= date('now', '-14 days')")]
    for f in (faits if isinstance(faits, list) else [])[:2]:
        f = str(f).strip()[:200]
        nf = normaliser_titre(f)
        if len(nf.split()) < 4 or any(SequenceMatcher(None, nf, c).ratio() >= SEUIL_DOUBLON for c in connus):
            continue
        con.execute("INSERT INTO faits (article_id, date, fait) VALUES (?,?,?)", (article_id, now, f))
        connus.append(nf)


SEUIL_DOUBLON = 0.8  # vrais doublons mesurés à 0,88 et 0,91 ; titres différents les plus proches à 0,69 (nov. 2026)


def enregistrer(reponses, items, chemin=DB):
    """Valide la réponse de Claude et l'enregistre. Retourne le nombre d'articles ajoutés."""
    con = connexion(chemin)
    now = maintenant().isoformat(timespec="seconds")
    # titres arabes des 2 derniers jours : la même info venue de sources en langues différentes a un titre arabe très proche
    recents = [normaliser_titre(t) for (t,) in con.execute("SELECT titre FROM articles WHERE date >= date('now', '-2 days')")]
    noms = noms_arabes(con)
    n = 0
    for r in reponses:
        i = r.get("id")
        if not isinstance(i, int) or not 1 <= i <= len(items) or not r.get("titre") or not r.get("texte"):
            continue
        nt = normaliser_titre(str(r["titre"]))
        # titres de moins de 4 mots : ressemblance sans valeur
        if len(nt.split()) >= 4 and any(SequenceMatcher(None, nt, t).ratio() >= SEUIL_DOUBLON for t in recents):
            print(f"  doublon écarté : {r['titre']}")
            continue
        recents.append(nt)
        it = items[i - 1]
        section = r.get("section") if r.get("section") in SECTIONS else "debats"
        personnes = [p for p in r.get("personnes", []) if p in PERSONNES]
        via = str(r.get("via") or "")[:60]
        auteur_claude = auteur_reel(str(r.get("auteur") or "")[:80], journal(it))
        auteur_flux = auteur_reel(it["auteur"], journal(it))
        if via and auteur_claude:  # avis d'un commentateur : il devient l'auteur, le journaliste devient rapporteur
            auteur, rapporteur = auteur_claude, auteur_flux
        else:
            auteur, rapporteur, via = auteur_flux or auteur_claude, "", ""
        auteur_ar = (r.get("auteur_ar") or auteur) if auteur else ""  # sans auteur : seulement le journal, partout
        if auteur and auteur == auteur_flux and r.get("auteur") and not meme_nom(str(r["auteur"]), auteur_flux):
            auteur_ar = auteur  # l'arabe de Claude peut être celui d'un autre article du lot : le nom latin plutôt qu'un faux nom
        if auteur:
            auteur_ar = noms.get(slug(auteur), auteur_ar)  # graphie de référence, même si Claude en a écrit une autre
        fb = r.get("titres_fb") if isinstance(r.get("titres_fb"), dict) else {}
        titres_fb = {k: str(fb[k])[:200] for k in ("fr", "en", "es") if fb.get(k)}
        cur = con.execute(
            "INSERT OR IGNORE INTO articles (date, section, titre, chapeau, texte, auteur, auteur_ar, journal, pays,"
            " lien, titre_original, mode, personnes, via, rapporteur, sujet, citation, chiffres, titres_fb, image)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            # date : celle de l'article d'origine, sinon celle du passage
            (it.get("publie") or now, section, r["titre"], r.get("chapeau", ""), r["texte"], auteur, auteur_ar,
             journal(it), it.get("pays"), it["lien"], it["titre"], "traduction" if it.get("autorise") else "conference" if it.get("type") == "conference"
             else "info" if it.get("type") == "info" else "resume",
             json.dumps(personnes), via, rapporteur, r.get("sujet") if r.get("sujet") in PERSONNES else "",
             str(r.get("citation") or "")[:200], json.dumps(chiffres_valides(r.get("chiffres")), ensure_ascii=False),
             json.dumps(titres_fb, ensure_ascii=False) if titres_fb else "", str(it.get("image") or "")[:500]),
        )
        n += cur.rowcount
        if cur.rowcount:
            noter_faits(con, cur.lastrowid, r.get("faits"), now)
        tweets = cur.rowcount and threads.assembler(
            {"auteur_ar": auteur_ar, "auteur": auteur, "journal": journal(it), "lien": it["lien"]},
            r.get("tweets") or [])
        if tweets:  # sinon (absent ou trop long) : threads.decouper le réécrira
            threads.connexion_threads(con)
            con.execute("INSERT OR IGNORE INTO threads (article_id, tweets, statut, date) VALUES (?,?,?,?)",
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

    Photo choisie à la main ("photo" de sa fiche dans config, ex. en maillot du Real), sinon celle de sa page
    Wikipédia ("wikipedia"). Changer le choix dans config.json suffit pour la remplacer."""
    credits = json.loads(CREDITS.read_text(encoding="utf-8")) if CREDITS.exists() else {}
    choisies = {k: f["photo"].removeprefix("File:").replace(" ", "_") for k, f in FICHES.items() if f.get("photo")}
    a_faire = {k: f.get("wikipedia") for k, f in FICHES.items() if f.get("wikipedia") or f.get("photo")}
    a_faire = {k: t for k, t in a_faire.items()
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


# ---------- rendu ----------
CREDITS_PHOTOS = {}  # chargé par rendre_site
COUVERTURES = {}  # id d'article -> fichier PNG, chargé par rendre_site
THREADS = {}  # id d'article -> tweets du thread X, chargé par rendre_site

# boutons X / Facebook : copier, coches, et mémoire « publié » propre au navigateur (site local, pas de serveur)
JS = (GABARITS / "site.js").read_text(encoding="utf-8")
JS_RECHERCHE = (GABARITS / "recherche.js").read_text(encoding="utf-8")
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

CSS = (GABARITS / "style.css").read_text(encoding="utf-8")


def slug(texte):
    s = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "auteur"



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
    liens = [("index", "الرئيسية"), *SECTIONS.items(), ("revue", "مراجعة الصحافة"), ("presse", "الصحافة العالمية"),
             ("recherche", "بحث")]
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


def image_article(a, classe, couv, alt=""):
    """Image principale de l'article source (site local seulement), sinon la couverture générée ; repli sur elle si l'image
    distante ne charge pas. Sans referrer : certains journaux bloquent leurs images affichées ailleurs."""
    source, cl = (a["image"] if "image" in a.keys() else ""), (f'class="{classe}" ' if classe else "")
    if not source:
        return f'<img {cl}src="couvertures/{couv}" alt="{alt}" loading="lazy" decoding="async">' if couv else ""
    repli = f" onerror=\"this.onerror=null;this.src='couvertures/{couv}'\"" if couv else ' onerror="this.remove()"'
    return (f'<img {cl}src="{e(source)}" alt="{alt}" loading="lazy" decoding="async"'
            f' referrerpolicy="no-referrer"{repli}>')


def carte(a, classe="", niveau="h3"):
    couv = COUVERTURES.get(a["id"])
    image = image_article(a, "couv", vignette(couv) if couv else None)
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


def liens_stats(cle):
    """Fiche d'une personne : liens vers ses stats DataMB et celles du club (consultées à la main, citées « DataMB »)."""
    club, joueur = CONFIG.get("datamb_club"), FICHES.get(cle, {}).get("datamb")
    liens = [f'<a href="{e(u)}" target="_blank" rel="noopener">{t}</a>' for u, t in ((joueur, "إحصاءات اللاعب"),
             (club, "إحصاءات ريال مدريد")) if u]
    return f'<p class="stats-ext">DataMB: {" · ".join(liens)}</p>' if liens else ""


PAR_PAGE = CONFIG.get("articles_par_page", 30)


def liste(nom, sur_titre, titre, arts, description="", actif=None, classe="", sous_titre="", visuel=""):
    """Pages d'une liste, PAR_PAGE articles chacune : nom.html, puis nom--2.html... ({fichier: html}).
    « -- » n'apparaît jamais dans un slug : pas de collision avec la page d'un autre journaliste."""
    tete = (f'<header class="tete-liste {classe}">{visuel}<div><span class="sur-titre">{sur_titre}</span><h1>{e(titre)}</h1>'
            f'{sous_titre}{f"<p>{description}</p>" if description else ""}<span class="compte">{compte(len(arts))}</span></div></header>')
    tranches = [arts[i:i + PAR_PAGE] for i in range(0, len(arts), PAR_PAGE)] or [[]]
    fichier = lambda n: f"{nom}.html" if n == 1 else f"{nom}--{n}.html"  # noqa: E731
    pages = {}
    for n, tranche in enumerate(tranches, 1):
        nav = ""
        if len(tranches) > 1:
            prec = f'<a href="{fichier(n - 1)}" rel="prev">→ الصفحة السابقة</a>' if n > 1 else "<span></span>"
            suiv = f'<a href="{fichier(n + 1)}" rel="next">الصفحة التالية ←</a>' if n < len(tranches) else "<span></span>"
            nav = f'<nav class="pages" aria-label="الصفحات">{prec}<span>صفحة {n} من {len(tranches)}</span>{suiv}</nav>'
        pages[fichier(n)] = page(titre if n == 1 else f"{titre} · صفحة {n}",
                                 tete + (grille(tranche) if tranche else VIDE) + nav, actif)
    return pages


def fil(arts):
    """Liste chronologique compacte (revue de presse, dernières nouvelles)."""
    return '<ol class="fil">' + "".join(
        f'<li class="s-{a["section"]}" data-id="{a["id"]}">{rubrique(a)}<a class="titre" href="a-{a["id"]}.html">{e(a["titre"])}</a>'
        f'<p>{e(a["chapeau"])}</p>{signature(a)}</li>' for a in arts) + "</ol>"


def page_accueil(arts):
    if not arts:
        return page("الرئيسية", VIDE, "index")
    avis = [a for a in arts if a["section"] != "actus" and a["mode"] != "info"] or arts  # la une reste aux articles d'opinion
    nouvelles = [a for a in arts if a["section"] == "actus" or a["mode"] == "info"]  # avec les infos du Bernabéu (club)
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
    post = threads.post_facebook(a)
    boutons = f'<button type="button" class="b-fb" data-ouvre="fb-{i}">{LOGO_FB}نشر على فيسبوك</button>'
    fenetres = fenetre(f"fb-{i}", "منشور فيسبوك", f'<ul class="tweets">{copiable(post, f"fb-{i}")}</ul>')
    if tweets:
        image = f'<a class="bouton" href="couvertures/{couv}" download>تنزيل صورة التغريدة الأولى</a>' if couv else ""
        # X pré-remplit seulement le 1er tweet (ni image ni suite du thread par lien)
        image += (f'<a class="bouton b-x" href="https://x.com/intent/post?text={urllib.parse.quote(tweets[0])}" target="_blank"'
                  f' rel="noopener">{LOGO_X}فتح X مع التغريدة الأولى</a>')
        liste_tw = "".join(copiable(t, f"x-{i}-{n}", f"{threads.longueur(t)}/{threads.LIMITE}")
                           for n, t in enumerate(tweets, 1))
        boutons = f'<button type="button" class="b-x" data-ouvre="x-{i}">{LOGO_X}ثريد ({len(tweets)})</button>' + boutons
        fenetres += fenetre(f"x-{i}", "ثريد X", f'{image}<ol class="tweets">{liste_tw}</ol>')
    return f'<div class="partage">{boutons}</div>{fenetres}'


def corps_html(texte):
    """Paragraphes de l'article ; une ligne qui commence par « ## » est un intertitre."""
    lignes = [l.strip() for bloc in texte.split("\n\n") for l in (bloc.split("\n") if "## " in bloc else [bloc])]
    return "".join(f"<h2>{e(l[3:].strip())}</h2>" if l.startswith("## ") else f"<p>{e(l)}</p>" for l in lignes if l)


def page_article(a, arts):
    paragraphes = corps_html(a["texte"])
    tags = "".join(f'<a href="p-{p}.html">{e(PERSONNES[p])}</a>' for p in json.loads(a["personnes"]) if p in PERSONNES)
    nom = f'{e(a["auteur_ar"])} (<bdi class="latin">{e(a["auteur"])}</bdi>)'
    traduction = a["mode"] == "traduction"
    badge = "ترجمة كاملة" if traduction else "ملخص وتعليق"
    if a["section"] == "actus" or a["mode"] == "info":  # une information sur le Bernabéu est rangée dans club
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
    img = image_article(a, "", couv, e(a["citation"] or a["titre"]))
    couverture = f'<figure class="couverture">{img}</figure>' if img else ""
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


def page_recherche():
    corps = ('<header class="tete-liste bloc-or"><div><span class="sur-titre">الأرشيف</span><h1>بحث</h1>'
             "<p>ابحث في العناوين والمقدّمات، وبأسماء الكتّاب والصحف واللاعبين.</p></div></header>"
             '<form class="recherche" role="search" onsubmit="return false"><label for="q">كلمات البحث</label>'
             '<input id="q" type="search" autocomplete="off" placeholder="مثال: فينيسيوس ماركا"></form>'
             '<p id="nb" class="nb-resultats" role="status" aria-live="polite"></p><ol id="resultats" class="fil"></ol>'
             '<noscript><p class="vide">البحث يحتاج إلى تفعيل جافاسكربت.</p></noscript>'
             '<script src="articles.js"></script><script src="recherche.js"></script>')
    return page("بحث", corps, "recherche")


def donnees_recherche(arts):
    """Index de la recherche (articles.js) : ce qui s'affiche dans un résultat, plus « x », cherché sans être affiché
    (nom latin de l'auteur, titre d'origine, personnes citées). Sans le corps des articles : le fichier reste léger."""
    index = [{"i": a["id"], "t": a["titre"], "c": a["chapeau"], "s": a["section"], "a": a["auteur_ar"] if a["auteur"] else "",
              "j": a["journal"], "d": date_ar(a["date"]),
              "x": " ".join([a["auteur"] or "", a["titre_original"] or "",
                             *(PERSONNES[p] for p in json.loads(a["personnes"]) if p in PERSONNES)])} for a in arts]
    # « </ » échappé : un titre contenant </script> ne peut pas fermer la balise si le fichier est un jour mis dans la page
    return (f"const RUBRIQUES={json.dumps(SECTIONS, ensure_ascii=False)};\n"
            f"const ARTICLES={json.dumps(index, ensure_ascii=False)};\n").replace("</", "<\\/")


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
    # couverture seulement pour les articles sans image source (celle du journal sert au site et aux threads)
    COUVERTURES.update(generer_couvertures([a for a in arts if not a["image"]], dossier))
    fichiers = {"style.css": CSS, "site.js": JS, "index.html": page_accueil(arts),
                "revue.html": page_revue(arts), "presse.html": page_presse(arts),
                "recherche.html": page_recherche(), "recherche.js": JS_RECHERCHE, "articles.js": donnees_recherche(arts)}
    par_section = defaultdict(list)
    for a in arts:
        par_section[a["section"]].append(a)
    for k, v in SECTIONS.items():
        fichiers.update(liste(k, "قسم", v, par_section[k], DESCRIPTIONS[k], k, f"s-{k}"))
    groupes, entetes = defaultdict(list), {}  # pages d'étiquettes : journaliste, personne, pays

    def ajouter(nom, a, *entete):
        groupes[nom].append(a)
        entetes.setdefault(nom, entete)  # le plus récent donne le titre (ex. nom arabe du journaliste)

    for a in arts:
        fichiers[f"a-{a['id']}.html"] = page_article(a, par_section[a["section"]])  # proches : sa rubrique seulement
        if a["auteur"]:
            ajouter(f"j-{slug(a['auteur'])}", a, "معلّق" if a["via"] else "كاتب رأي", a["auteur_ar"],
                    f'<bdi class="latin" dir="ltr">{e(a["auteur"])}</bdi>', None)
        for p in json.loads(a["personnes"]):
            if p in PERSONNES:
                ajouter(f"p-{p}", a, "ملف", PERSONNES[p], liens_stats(p), None, photo(p, "portrait"))
        if a["pays"]:
            ajouter(f"pays-{a['pays']}", a, "الصحافة العالمية", PAYS.get(a["pays"], a["pays"]), "", "presse")
    for nom, liste_arts in groupes.items():
        sur_titre, titre, sous, actif, *visuel = entetes[nom]
        fichiers.update(liste(nom, sur_titre, titre, liste_arts, actif=actif, classe="bloc-or", sous_titre=sous,
                              visuel="".join(visuel)))
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


def a_reessayer(it):
    """Page refusée et flux trop court pour en tirer un article : on retente aux passages suivants tant que l'article est
    récent, puis on se contente du flux. Le refus est passager (AS, L'Équipe : 5 refus chacun en 60 passages, nov. 2026)."""
    if not it.get("illisible") or len(it["texte"]) >= 1500 or not it.get("publie"):
        return False
    age = (maintenant() - datetime.fromisoformat(it["publie"])).total_seconds() / 3600
    return age < CONFIG.get("attente_page_heures", 6)


def traiter_lot(lot):
    """Lit les articles, fait rédiger Claude, enregistre. Retourne le nombre d'articles ajoutés (None si réponse illisible)."""
    with ThreadPoolExecutor(8) as ex:  # pages lues en même temps : un site lent ne bloque plus tout le lot
        for it, texte in zip(lot, ex.map(texte_complet, lot)):
            it["texte"] = texte
    reportes = [it for it in lot if a_reessayer(it)]  # pas marqués comme vus : repris au prochain passage
    for it in reportes:
        print(f"  page refusée, nouvel essai au prochain passage : {journal(it)} | {it['titre'][:80]}")
    lot = [it for it in lot if it not in reportes]
    if not lot:
        return 0
    con = connexion()
    noms = noms_arabes(con)
    con.close()
    reponse = appeler_claude(construire_prompt(lot, deja_publies(), noms), CONFIG.get("modele_redaction", "sonnet"))
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
    ap.add_argument("--threads", action="store_true", help="seulement les threads X (Typefully) et les publications sur la Page Facebook")
    args = ap.parse_args()

    panne = False  # Claude en panne : le site est quand même régénéré et les threads prêts envoyés, puis le passage échoue
    if restaurer_base(DB):
        print("Base reconstruite depuis articles.sql.")
    if not args.rendre and not args.test and not args.threads:
        mettre_a_jour_photos()
    if not args.rendre and not args.photos and not args.threads:
        print("Collecte des flux...")
        # liens Google News = redirections : ni auteur ni texte lisible
        items = [it for it in collecter(DB, CONFIG.get("age_max_heures_site", 24))
                 if not it["lien"].startswith("https://news.google.com") and not est_direct(it) and not est_pratique(it)]
        for it in items:
            it["auteur"] = auteur_reel(it["auteur"], journal(it))  # ni "info@vi.nl", ni "Redacción", ni le journal
        items, doublons = dedoublonner(items)
        items = ordonner(items)
        if items and not args.test:
            candidats = items[:60]  # au-delà : triés au prochain passage
            print(f"Tri de {len(candidats)} article(s) sur titre et chapeau...")
            try:
                tri = trier(candidats, deja_publies())
            except ErreurClaude as err:  # rien n'est marqué comme vu : tout est repris au prochain passage
                print(f"  ! Claude indisponible ({err}) : pas de rédaction cette fois")
                panne, tri, items = True, None, []
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
            try:
                ajoutes = traiter_lot(lot)
            except ErreurClaude as err:  # les lots déjà rédigés sont gardés, le reste est repris au prochain passage
                print(f"  ! Claude indisponible ({err}) : lots restants reportés")
                panne = True
                break
            if ajoutes is not None:
                total += ajoutes
                print(f"  {ajoutes} article(s) d'opinion retenu(s) sur {len(lot)}.")
        print(f"{total} article(s) ajouté(s) au site.")

    index = rendre_site()
    print(f"\n✅ Site : {index}")
    if not args.rendre and not args.photos:
        con = connexion()
        print(f"Threads X : {threads.decouper(con)} préparé(s), "
              f"{threads.vers_typefully(con, COUVERTURES, SITE / 'couvertures')} déposé(s) dans Typefully. "
              f"Page Facebook : {threads.vers_page(con)} publication(s).")
        con.close()
    if panne:  # code d'erreur : le passage apparaît en rouge sur GitHub au lieu d'échouer en silence d'heure en heure
        raise SystemExit("Passage incomplet : Claude n'a pas répondu (quota ou jeton à vérifier).")
    if hasattr(os, "startfile"):
        os.startfile(index)


if __name__ == "__main__":
    main()

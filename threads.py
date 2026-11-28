"""Threads X (déposés dans Typefully) et publications sur la Page Facebook.

Le texte vient de l'article du site (déjà un résumé commenté), le dernier tweet crédite le journaliste et le
journal avec le lien de la source (X affiche alors la carte de l'article, avec sa photo principale).
Réglages : clés dans secrets.json sur le PC (variables d'environnement sur GitHub), "max_threads" dans config.json (threads et publications au plus par passage).
"""
import base64
import io
import json
import os
import http.client
import re
import sqlite3
import unicodedata
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from difflib import SequenceMatcher

from commun import BASE, CONFIG, ErreurClaude, appeler_claude, extraire_json, lire_page, maintenant, normaliser_titre

LIMITE = 280
LIMITE_LONG = 25_000  # tweet long (X Premium, depuis le 22 nov. 2026) : chaque thread devient un seul tweet
SECRETS = BASE / "secrets.json"  # token et chat sur le PC, hors git ; sur GitHub : variables d'environnement
URL = re.compile(r"https?://\S+")

# règles communes : thread écrit avec l'article (generer_site) ou après coup (decouper)
REGLES = """- Tweet 1, l'accroche, écrit comme les comptes foot arabes les plus suivis, sur plusieurs lignes courtes :
  ligne 1 : UN émoji, son étiquette et « | » (liste plus bas), puis une accroche de 12 mots au plus, qui se lit comme un titre : le fait lui-même, un chiffre, une courte citation «» ou une vraie question. Ne commence jamais par « يرى الصحفي... » ni « وفقًا لـ... ».
  ligne vide, puis une ou deux phrases courtes : le détail qui donne envie de lire la suite (qui, quand, combien, pourquoi c'est important).
  ligne vide, puis la source seule entre parenthèses, sans « بحسب » ni guillemets : (ماركا) pour une information, (اسم الكاتب - ماركا) pour une opinion, (اسم المعلّق - راديو ماركا) pour un avis donné à la radio ou à la télévision.
  dernière ligne : les hashtags (2 au plus, séparés par une espace), choisis d'après le sujet (choix de l'utilisateur, 2026-11-22) :
    match précis (composition, résultat, avant-match, analyse) : celui du match, les deux équipes en arabe, l'équipe qui reçoit d'abord, mots reliés par « _ » (#ريال_مدريد_سيلتا_فيغو), puis la compétition (#الليغا, #دوري_أبطال_أوروبا, #كأس_الملك, #السوبر_الإسباني), ou #الكلاسيكو contre le Barça ;
    un joueur au centre (blessure, retour, déclaration, prolongation, transfert) : son nom usuel en arabe (#مبابي, #فينيسيوس, #بيلينغهام) puis #ريال_مدريد ;
    opinion et débat (🔥 نقاش, chroniques, 🧠 قراءة hors match précis) : aucun hashtag, la ligne n'existe pas ;
    sinon : #ريال_مدريد seul.
- Étiquette de la ligne 1, selon le contenu :
  « 🚨 عاجل | » seulement pour une vraie urgence (blessure grave, transfert conclu, départ d'un entraîneur ou dirigeant) ; « ✅ رسميًا | » seulement pour une annonce officielle du club ou de la fédération (communiqué, signature, prolongation, sanction), jamais pour un compte rendu ; « 📝 القائمة | » tout article sur la liste des convoqués pour un match : une ligne d'accroche (le match, l'absent ou le retour notable), puis TOUS les convoqués que donne le texte, sans en omettre un, une ligne par poste commençant par « ▪️ » (▪️ الحراس: …، … puis الدفاع، الوسط، الهجوم), noms séparés par « ، », puis les absents en une ligne (la limite de 240 caractères ne s'applique pas) ; « 🏋️ تدريبات | » séance d'entraînement (qui revient, qui manque, ce qui a été travaillé) ; « 🏥 إصابة | » blessure, « 💪 عودة | » retour de blessure ; « 📋 التشكيلة | » composition officielle (une ligne par ligne de jeu, heure de La Mecque si le texte la donne) ; « ⏱️ نهاية المباراة | » résultat ; « 🗣️ [nom] | » quand l'accroche est une déclaration «» ; « 🎙️ مؤتمر [nom] | » conférence de presse ; « 📊 رقم | » information bâtie sur une statistique ; sinon « 📰 خبر | » ;
  section mercato, et toute information de transfert ou de prolongation quelle que soit la section : « 🔄 ميركاتو | », et, seulement si le texte annonce un transfert ou une prolongation en cours (pas pour une analyse, un bilan ou une opération déjà conclue), juste avant la source et seul sur sa ligne, son stade d'après le texte : « 🟢 اتفاق » accord ou opération avancée, « 🟡 مفاوضات » contacts ou intérêt, « 🔴 شائعة » simple rumeur ;
  section tactique : « 🧠 قراءة | » ; section club : « 🏟️ برنابيو | » (stade), « 🏛️ الإدارة | » (direction, institutions) ou « 💶 مالية النادي | » (argent) ;
  section debats et autres opinions : « 🔥 نقاش | » avec une vraie question en accroche, et le dernier tweet du thread finit, sur sa propre ligne, par « ما رأيكم؟ 👇 ».
- Source : une seule, celle qui a révélé l'information ou porté l'avis. Si le texte dit qu'un média en cite un autre (« نقلت إي إس بي إن عن ليكيب »), ne garde que le média d'origine : (ليكيب). La source est donnée une seule fois, au tweet 1 : les tweets suivants ne la redisent pas (pas de « بحسب ماركا » au tweet 2), sauf pour une information venue d'un autre média. Jamais de chaîne « نقلًا عن... عن... » ni deux médias pour la même information. Exception : une conférence de presse (« 🎙️ مؤتمر ») et la liste des convoqués (« 📝 القائمة ») n'ont aucune source, ni ligne entre parenthèses ni média cité (choix de l'utilisateur, 2026-11-23).
- Tweets suivants : chacun apporte du nouveau, sans redire l'accroche ni la source du tweet 1 ; fidèles au texte, une idée par tweet, en phrases courtes qui se comprennent sans le tweet d'avant, en gardant ses citations «» telles quelles. Les guillemets «» sont réservés aux mots que le texte cite lui-même, recopiés sans changement (une coupe se marque « … ») : une paraphrase, un discours indirect ou deux passages recollés s'écrivent sans guillemets (يرى براسين أن…). Deux ou trois lignes courtes valent mieux qu'un bloc ; une énumération (notes des joueurs, chiffres, noms) va à la ligne, chaque élément précédé de « ▪️ ». L'avis reste attribué à son auteur, par son nom de famille ou une tournure (في نظره، يذهب أبعد من ذلك) : n'écris jamais « الكاتب » ni « الصحفي », et ne recite pas le journal. Le dernier porte la conclusion ou la phrase la plus marquante.
- Nombre de tweets : 2 ou 3 pour une information, 4 à 8 pour une opinion, pour une conférence de presse rapportée par Marca ou AS (le direct : un article par déclaration), UN seul tweet : « 🎙️ مؤتمر [nom] | » et la déclaration forte que l'article met en avant entre «», ligne vide, la question du journaliste traduite exactement si le texte la donne (sinon une phrase de contexte : le match, le sujet), puis la réponse traduite exactement entre «», puis les hashtags ; pour la conférence complète du site du club (le récapitulatif), au moins 4 et sans plafond (toutes ses déclarations fortes, une par tweet : la question du journaliste traduite exactement telle que le texte la donne, puis la réponse traduite exactement entre «» ; une question que le texte ne donne pas n'est jamais inventée, et la suite d'une même réponse reste sous sa question). Conférence de presse (choix de l'utilisateur, 2026-11-23) : traduction exacte des questions et des réponses, sans les résumer ni les couper, et la limite de 240 caractères par tweet ne s'applique pas.
- Chaque tweet fait AU MAXIMUM 240 caractères, espaces et retours à la ligne compris. Pas de lien, pas de numérotation, aucun hashtag en dehors de la dernière ligne du tweet 1, pas d'intertitre « ## », aucun émoji en dehors de ceux prévus ci-dessus.
- Les tweets sont réunis à l'envoi en un seul tweet long, un paragraphe chacun : le tweet 1 est ce qu'on lit avant « Afficher plus ».
- N'ajoute aucun fait ni avis absent du texte. Pas d'exagération ni de point d'exclamation."""

PROMPT = """Tu prépares des threads X (Twitter) en arabe pour le compte « المدريديستا علاء », à partir d'articles déjà rédigés pour son site.

Pour chaque article, écris le thread :
{regles}

Réponds UNIQUEMENT avec un tableau JSON valide, sans texte avant ni après :
[{{"id": 12, "tweets": ["...", "..."]}}]

ARTICLES
{articles}
"""


def longueur(texte):
    """Longueur comptée par X : lien = 23, arabe et latin = 1, emoji et idéogrammes = 2."""
    texte = URL.sub("x" * 23, texte)
    return sum(1 if ord(c) <= 4351 or 8192 <= ord(c) <= 8205 or 8208 <= ord(c) <= 8223 or 8242 <= ord(c) <= 8247
               else 2 for c in texte)


def reglage(cle):
    local = json.loads(SECRETS.read_text(encoding="utf-8")) if SECRETS.exists() else {}
    return os.environ.get(cle.upper()) or local.get(cle) or CONFIG.get(cle)


def credit(a):
    nom = a["auteur_ar"] or a["auteur"]
    signe = f"✍️ {nom} | {a['journal']}" if nom else f"📰 {a['journal']}"
    return f"{signe}\n🔗 المصدر: {a['lien']}"


LIGNE_TAGS = re.compile(r"(#\w+\s*)+")


def tags_a_la_fin(texte):
    """Lignes faites seulement de hashtags déplacées à la fin du tweet long, sans doublon : les règles les placent au tweet 1,
    qui n'est plus que le premier paragraphe depuis le passage au tweet long (remarque de l'utilisateur, 2026-11-22)."""
    lignes = texte.split("\n")
    tags = [l.strip() for l in lignes if LIGNE_TAGS.fullmatch(l.strip())]
    if not tags:
        return texte
    corps = re.sub(r"\n{3,}", "\n\n", "\n".join(l for l in lignes if not LIGNE_TAGS.fullmatch(l.strip()))).strip()
    return corps + "\n\n" + " ".join(dict.fromkeys(" ".join(tags).split()))


def assembler(a, tweets):
    """Réunit les tweets écrits par Claude en un seul tweet long, suivi du tweet de crédit (avec le lien) publié en réponse :
    il peut être retiré à l'envoi et ajouté à la main. Conférence de presse : pas de source, donc pas de crédit.
    None si c'est trop long pour X ou si le thread est vide."""
    long = tags_a_la_fin("\n\n".join(t for t in (str(t).strip() for t in tweets) if t))
    if not long or longueur(long) > LIMITE_LONG or longueur(credit(a)) > LIMITE:
        return None
    return [long] if est_conference(long) or est_liste(long) else [long, credit(a)]


def est_conference(tweet):
    return tweet.lstrip().startswith("🎙")  # étiquette « 🎙️ مؤتمر [nom] | » mise par Claude (REGLES)


def est_compo(tweet):
    """Composition probable (generer_site.enregistrer_compos) : sa source est dans la phrase (« حسب صحيفة «ماركا» »), et
    Marca et AS ont chacune la leur pour le même match (une par média, choix de l'utilisateur, 28 nov.)."""
    return tweet.lstrip().startswith("التشكيلة المتوقعة")


def est_liste(tweet):
    return tweet.lstrip().startswith("📝")  # « 📝 القائمة | » : liste des convoqués, sans source (choix de l'utilisateur, 2026-11-23)


def convoques(tweet):
    """Noms des lignes de poste (« ▪️ الحراس: كورتوا، لونين ») : une liste complète en compte 18 à 26."""
    return sum(len([n for n in l.split(":", 1)[-1].split("،") if n.strip()])
               for l in tweet.splitlines() if l.startswith("▪️") and ":" in l)


def connexion_threads(con):
    con.execute("CREATE TABLE IF NOT EXISTS threads (article_id INTEGER PRIMARY KEY, tweets TEXT, statut TEXT, date TEXT)")
    try:  # id du brouillon Typefully ; les threads d'avant l'ajout ne sont pas envoyés
        con.execute("ALTER TABLE threads ADD COLUMN typefully TEXT")
        con.execute("UPDATE threads SET typefully = 'avant'")
        con.commit()
    except sqlite3.OperationalError:
        pass  # colonne déjà présente
    try:  # heure d'envoi à Typefully : plafond de publications immédiates par heure
        con.execute("ALTER TABLE threads ADD COLUMN envoye TEXT")
        con.commit()
    except sqlite3.OperationalError:
        pass


def noter(con, envoi, erreur=None):
    """Suivi des échecs d'un envoi (Facebook, Typefully...) d'un passage à l'autre : erreur=None le remet à zéro."""
    con.execute("CREATE TABLE IF NOT EXISTS echecs (envoi TEXT PRIMARY KEY, n INTEGER, depuis TEXT, message TEXT, alerte INTEGER)")
    if erreur is None:
        con.execute("DELETE FROM echecs WHERE envoi = ?", (envoi,))
    else:
        con.execute("INSERT INTO echecs VALUES (?, 1, ?, ?, 0) ON CONFLICT (envoi) DO UPDATE SET n = n + 1, message = excluded.message",
                    (envoi, maintenant().isoformat(timespec="seconds"), str(erreur)[:300]))
    con.commit()


def alertes(con, seuil=3):
    """Envois en échec depuis au moins `seuil` passages, pas encore signalés : texte de l'issue d'alerte ("" si rien).
    Chaque panne n'est signalée qu'une fois ; elle peut l'être de nouveau après avoir été réparée."""
    con.execute("CREATE TABLE IF NOT EXISTS echecs (envoi TEXT PRIMARY KEY, n INTEGER, depuis TEXT, message TEXT, alerte INTEGER)")
    lignes = con.execute("SELECT * FROM echecs WHERE n >= ? AND alerte = 0", (seuil,)).fetchall()
    con.execute("UPDATE echecs SET alerte = 1 WHERE n >= ?", (seuil,))
    con.commit()
    return "\n".join(f"- **{r[0]}** : en échec depuis {r[1]} passages (depuis le {r[2]} UTC). Dernière erreur : `{r[3]}`" for r in lignes)


# contrôles avant envoi : les contenus partent sans relecture, ce qui échoue part en brouillon (X) ou n'est pas publié (Facebook)
APPATS = re.compile(r"ريتويت|رتويت|أعد التغريد|أعيدوا التغريد|تابعونا|تابع الحساب|فعّلوا التنبيهات")  # appel à l'engagement
SOURCE = re.compile(r"\([^()\n]{2,80}\)")
ETIQUETTE = re.compile(r"^[^|\n]{0,30}\|\s*")
NUMERO = re.compile(r"\n\n\d+/\d+$")
ENVOYES = "typefully IS NOT NULL AND typefully != 'avant' AND statut NOT LIKE 'bloqu%'"


def accroche(texte):
    """Première ligne d'un tweet, sans l'étiquette (« 🚨 عاجل | ») ni la ponctuation : ce qu'on compare entre deux threads."""
    return normaliser_titre(ETIQUETTE.sub("", NUMERO.sub("", texte).strip().split("\n")[0]))


def personnes_citees(texte):
    """Joueurs nommés dans une accroche : nom de famille arabe (غولر pour أردا غولر) ou clé latine sans accents (guler)."""
    plat = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return {k for k, p in CONFIG.get("personnes", {}).items()
            if normaliser_titre(p["nom"]).split()[-1] in texte.split() or k in plat.split()}


def proche(a, b):
    # moins de 4 mots : trop court pour juger (comme l'anti-doublon de generer_site) ; seuil mesuré sur 184 threads et 86 posts
    if len(a.split()) < 4 or len(b.split()) < 4:
        return False
    pa, pb = personnes_citees(a), personnes_citees(b)
    if pa and pb and not pa & pb:  # « تشواميني يمدد عقده... » ≠ « غولر يمدد عقده... » (bloqué à tort le 19 nov.)
        return False
    # lettres ET mots : en arabe, deux accroches sans rapport partagent beaucoup de lettres (ريال مدريد، فينيسيوس...)
    return (SequenceMatcher(None, a, b).ratio() >= CONFIG.get("seuil_doublon", 0.6)
            and SequenceMatcher(None, a.split(), b.split()).ratio() >= 0.4)


def est_officiel(a):
    return "://www.realmadrid.com/" in (a["lien"] or "")


PROMPT_DOUBLON = """Deux tweets d'un compte d'actualité du Real Madrid. Le premier est déjà publié.

Déjà publié :
{ancien}

Nouveau :
{nouveau}

Le nouveau apporte-t-il un fait nouveau (résultat d'un vote, d'un match, chiffre, décision, nouvelle déclaration) ou redit-il la même nouvelle ?
Réponds par un seul mot : NOUVEAU ou DOUBLON."""


def meme_nouvelle(ancien, nouveau):
    """Arbitre de l'anti-doublon textuel : « نادال يدخل مجلس الإدارة » (avant le vote) ≠ « نادال ... بـ99,5% » (le résultat), bloqué à tort le 21 nov.
    Sans réponse de Claude : doublon, par prudence."""
    try:
        return "NOUVEAU" not in appeler_claude(PROMPT_DOUBLON.format(ancien=ancien, nouveau=nouveau),
                                                CONFIG.get("modele_tri", "haiku"), "low").upper()
    except ErreurClaude:
        return True


def controler_thread(con, article_id, tweets, officiel=False, direct=()):
    """Motifs de blocage d'un thread avant envoi ([] : il peut partir). officiel : article du site du club, jamais un doublon
    (la confirmation officielle part même si la presse a donné la nouvelle avant, ex. Tchouaméni le 19 nov.). direct : tweets
    du direct de conférence, absents de la base : chaque déclaration est un tweet à part, une seule fois (choix du 28 nov.)."""
    motifs = []
    if longueur(tweets[0]) > LIMITE_LONG or any(longueur(x) > LIMITE for x in tweets[1:]):
        motifs.append("tweet trop long")
    if not SOURCE.search(tweets[0]) and not est_conference(tweets[0]) and not est_liste(tweets[0]) and not est_compo(tweets[0]):
        motifs.append("source absente du 1er tweet")
    if tweets[0].lstrip().startswith("✅") and not officiel:  # 23 nov. : deux listes de la presse publiées « ✅ رسميًا »
        motifs.append("✅ رسميًا hors site du club")
    if any(APPATS.search(x) for x in tweets):
        motifs.append("appel à l'engagement")
    if est_liste(tweets[0]):  # une seule liste par match, la première COMPLÈTE (publiée deux fois le 23 nov.), même celle du club
        if convoques(tweets[0]) < 18:  # Foot Mercato, 23 nov. : 8 noms seulement ; la liste complète arrive plus tard
            return motifs + ["doublon : liste incomplète"]
        deja = next((r[0] for r in con.execute(
            f"SELECT article_id, tweets FROM threads WHERE {ENVOYES} AND article_id != ?"
            " AND envoye >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-24 hours')", (article_id,))
            if est_liste(json.loads(r[1])[0])), None)
        if deja:
            return motifs + [f"doublon de la liste de l'article {deja}"]
    if est_compo(tweets[0]):  # une par média : jamais doublon de l'autre journal
        return motifs
    nouvelle = accroche(tweets[0])
    anciens = [(f"thread de l'article {r[0]}", json.loads(r[1])[0]) for r in con.execute(
        f"SELECT article_id, tweets FROM threads WHERE {ENVOYES} AND article_id != ?"
        " AND date >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-48 hours')", (article_id,))]
    for quoi, ancien in anciens + [("tweet du direct", x) for x in direct]:
        if not officiel and proche(nouvelle, accroche(ancien)) and meme_nouvelle(ancien, tweets[0]):
            motifs.append(f"doublon du {quoi}")
            break
    return motifs


def decouper(con, heures=24):
    """Fait écrire par Claude les threads des articles récents qui n'en ont pas encore. Retourne le nombre créé."""
    connexion_threads(con)
    arts = con.execute("SELECT * FROM articles WHERE id NOT IN (SELECT article_id FROM threads)"
                       " AND date >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?) ORDER BY (section = 'actus' OR mode = 'info') DESC, date DESC LIMIT ?",
                       (f"-{heures} hours", CONFIG.get("max_threads", 10))).fetchall()
    if not arts:
        return 0
    blocs = [f"[id {a['id']}] Section : {a['section']}\nAuteur : {a['auteur_ar'] or a['auteur'] or 'inconnu'}\n"
             f"Média : {a['journal']}\nTitre : {a['titre']}\nTexte :\n{a['texte']}" for a in arts]
    try:
        reponses = extraire_json(appeler_claude(PROMPT.format(regles=REGLES, articles="\n\n".join(blocs)),
                                                CONFIG.get("modele_redaction", "sonnet")))
    except (ValueError, ErreurClaude) as err:  # JSONDecodeError est un ValueError
        print(f"  ! threads : pas de réponse utilisable ({err}), repris au prochain passage")
        return 0
    par_id = {a["id"]: a for a in arts}
    n = 0
    for r in reponses:
        a = par_id.get(r.get("id")) if isinstance(r, dict) else None
        tweets = assembler(a, r.get("tweets") or []) if a else None
        if tweets:  # sinon (tweet trop long) : réécrit au prochain passage
            con.execute("INSERT OR IGNORE INTO threads (article_id, tweets, statut, date) VALUES (?,?,?,?)", (a["id"], json.dumps(tweets, ensure_ascii=False),
                        "a_envoyer", maintenant().isoformat(timespec="seconds")))
            n += 1
    con.commit()
    return n


def titres_facebook(a):
    """Titres FR/EN/ES de la publication Facebook ("" pour les articles d'avant les titres traduits)."""
    fb = json.loads(a["titres_fb"]) if a["titres_fb"] else {}
    return "\n".join(f"{d} {fb[k]}" for d, k in (("⚜️", "fr"), ("🇨🇦", "en"), ("🇪🇸", "es")) if fb.get(k))


def post_facebook(a):
    """Publication Facebook à copier-coller (bouton du site) : titres FR/EN/ES, puis le lien de la source."""
    titres = titres_facebook(a)
    return f"{titres}\n\n{a['lien']}" if titres else a["lien"]


PROBABLE = re.compile(r"alineaci[óo]n(es)? (probables?|posibles?)|posible (once|alineaci[óo]n)", re.I)  # composition probable
GRAPH = "https://graph.facebook.com/v23.0/"  # version de l'API Graph : Meta retire chaque version environ 2 ans après sa sortie


def connexion_page(con):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name = 'page_facebook'").fetchone():
        con.execute("CREATE TABLE page_facebook (article_id INTEGER PRIMARY KEY, date TEXT)")
        con.execute("INSERT INTO page_facebook SELECT id, 'avant' FROM articles")  # 1er passage : seuls les articles à venir partent
        con.commit()
    try:  # numéro du post Facebook : statistiques, commentaires et retrait
        con.execute("ALTER TABLE page_facebook ADD COLUMN post TEXT")
        con.commit()
    except sqlite3.OperationalError:
        pass


def vers_page(con, heures=24):
    """Publie sur la Page Facebook les nouvelles récentes (pas les opinions) avec titres traduits : image principale de l'article avec les
    titres FR/EN/ES et le nom du journal en légende, sinon titres en message et lien de la source en carte. Au plus max_threads par passage. Réglages : FACEBOOK_PAGE_TOKEN (jeton de la Page, permission
    pages_manage_posts) et FACEBOOK_PAGE_ID."""
    jeton, page = reglage("facebook_page_token"), reglage("facebook_page_id")
    if not jeton or not page:
        return 0  # pas encore configuré
    connexion_page(con)
    n = 0
    # la Page ne reçoit que les nouvelles : communiqués, actualités, compositions officielles et tout le mercato, chroniques
    # comprises (ni les autres opinions, ni les compositions probables)
    for a in con.execute("SELECT * FROM articles WHERE titres_fb != '' AND id NOT IN (SELECT article_id FROM page_facebook)"
                         " AND (section IN ('actus', 'mercato') OR mode = 'info')"
                         " AND date >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?) ORDER BY id LIMIT ?",
                         (f"-{heures} hours", CONFIG.get("max_threads", 10))).fetchall():
        if PROBABLE.search(a["titre_original"] or ""):
            continue
        fb_titres = json.loads(a["titres_fb"])
        if conference_entraineur(con, a) and not est_officiel(a):  # la Page attend la page complète du site du club
            con.execute("INSERT INTO page_facebook VALUES (?, ?, ?)",
                        (a["id"], maintenant().isoformat(timespec="seconds"), "sans : conférence publiée depuis le site du club"))
            con.commit()
            continue
        titre = normaliser_titre(fb_titres.get("fr", ""))
        double = None if est_officiel(a) else next((r[0] for r in con.execute(
            "SELECT a.id, a.titres_fb FROM page_facebook p JOIN articles a ON a.id = p.article_id WHERE coalesce(p.post, '') NOT LIKE 'bloqu%'"
            " AND p.date >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)", (f"-{heures * 2} hours",))
            if proche(titre, normaliser_titre(json.loads(r[1] or "{}").get("fr", "")))), None)
        if double:  # même nouvelle déjà publiée (deux journaux, deux articles) : pas de second post
            print(f"  ! Page Facebook : article {a['id']} non publié, doublon de l'article {double}")
            con.execute("INSERT INTO page_facebook VALUES (?, ?, ?)",
                        (a["id"], maintenant().isoformat(timespec="seconds"), f"bloqué : doublon de {double}"))
            con.commit()
            continue
        # conférence du site du club : tout d'un coup, en français, l'anglais en commentaire
        texte = f"🎙️ {fb_titres.get('fr', '')}\n\n{fb_titres['conf_fr']}" if fb_titres.get("conf_fr") else titres_facebook(a)
        if a["image"]:  # liens des médias bloqués au Canada (loi C-18) : photo de l'article + titres, retouchée à la main sur Facebook
            envoi, champs = "photos", {"url": a["image"], "caption": f"{texte}\n\nSource : {a['journal']}"}
        else:
            envoi, champs = "feed", {"message": texte, "link": a["lien"]}
        corps = urllib.parse.urlencode({**champs, "access_token": jeton}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{GRAPH}{page}/{envoi}", corps), timeout=60) as rep:
                fb = json.load(rep)
        except OSError as err:  # réseau coupé, jeton refusé (HTTPError est un OSError) : repris au prochain passage
            # Facebook explique son refus dans le corps de la réponse (jeton expiré, permission manquante...)
            detail = err.read().decode("utf-8", "replace")[:300] if hasattr(err, "read") else ""
            print(f"  ! Page Facebook : publication impossible ({err}) {detail}, reprise au prochain passage")
            noter(con, "Page Facebook", f"{err} {detail}")
            break
        post = str(fb.get("post_id") or fb.get("id") or "")
        con.execute("INSERT INTO page_facebook VALUES (?, ?, ?)", (a["id"], maintenant().isoformat(timespec="seconds"), post))
        con.commit()
        noter(con, "Page Facebook")
        if post and fb_titres.get("conf_en"):
            commenter(post, f"🇬🇧 {fb_titres.get('en', '')}\n\n{fb_titres['conf_en']}", jeton)
        if envoi == "photos" and post and CONFIG.get("facebook_lien_en_commentaire", True):
            commenter_source(post, a, jeton)
        n += 1
    return n


def commenter_source(post, a, jeton):
    """Lien de la source en commentaire de la Page sous un post photo (permission pages_manage_engagement). Le post est déjà
    publié : un échec est seulement signalé. Au Canada, Meta bloque aussi ces liens de médias (loi C-18) : ils ne servent
    qu'aux lecteurs hors du Canada ; "facebook_lien_en_commentaire": false dans config.json les arrête."""
    nom = a["auteur"] if a["auteur"] else ""
    commenter(post, f"🔗 Source : {a['journal']}" + (f" ({nom})" if nom else "") + f"\n{a['lien']}", jeton)


def commenter(post, texte, jeton):
    """Commentaire de la Page sous un de ses posts ; le post est déjà publié : un échec est seulement signalé."""
    corps = urllib.parse.urlencode({"message": texte, "access_token": jeton}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{GRAPH}{post}/comments", corps), timeout=60) as rep:
            json.load(rep)
    except OSError as err:
        detail = err.read().decode("utf-8", "replace")[:300] if hasattr(err, "read") else ""
        print(f"  ! Page Facebook : commentaire non publié sous le post {post} ({err}) {detail}")


def conference_entraineur(con, a):
    """Conférence de presse de l'entraîneur ("entraineur" dans config.json, mourinho par défaut), d'après l'étiquette du 1er
    tweet de son thread : le club la publie en entier sur son site, seule cette version va sur la Page Facebook."""
    nom = CONFIG.get("personnes", {}).get(CONFIG.get("entraineur", "mourinho"), {}).get("nom")
    r = con.execute("SELECT tweets FROM threads WHERE article_id = ?", (a["id"],)).fetchone() if a["mode"] == "conference" else None
    return bool(nom and r and orateur(json.loads(r[0])[0]) == nom)


PROMPT_RESUME = """Tu prépares pour le compte X « المدريديستا علاء » le résumé quotidien « حصاد ريال مدريد » du {jour}, à partir des articles
publiés ce jour-là sur son site (liste plus bas).
Choisis les 3 sujets qui comptent le plus pour un supporter (blessure, composition, résultat, transfert, polémique, opinion forte) ;
un sujet traité par plusieurs articles ne compte qu'une fois. Varie les médias : à importance comparable, préfère un sujet d'un
autre journal que les sujets déjà retenus, pour que le résumé ne cite pas trois fois le même.
Thread de 4 tweets en arabe :
- Tweet 1 : « 📌 حصاد ريال مدريد | » suivi de la date en arabe (ex. 17 نوفمبر), une ligne vide, une phrase qui annonce les 3 sujets, une ligne vide, « #ريال_مدريد ».
- Tweets 2 à 4, un sujet chacun : « ▪️ » puis le fait ou l'avis en une ou deux phrases courtes, une ligne vide, puis la source entre parenthèses :
  (ماركا) pour une information, (اسم الكاتب - ماركا) pour une opinion signée.
Chaque tweet fait AU MAXIMUM 240 caractères. Pas de lien, aucun autre émoji ni hashtag, pas de point d'exclamation, aucun fait absent des articles.
Réponds UNIQUEMENT avec un tableau JSON des 4 tweets, sans texte avant ni après : ["...", "...", "...", "..."]

ARTICLES
{articles}
"""


def heure_madrid(utc):
    """Heure de Madrid depuis l'heure UTC (sans tzdata, absent de Python sous Windows) : heure d'été européenne du dernier
    dimanche de mars au dernier dimanche d'octobre, à 1 h UTC."""
    def dernier_dimanche(mois):
        d = datetime(utc.year, mois, 31, 1)
        return d - timedelta(days=(d.weekday() + 1) % 7)
    return utc + timedelta(hours=2 if dernier_dimanche(3) <= utc < dernier_dimanche(10) else 1)


def resume_du_jour(con, utc=None):
    """Thread « حصاد ريال مدريد » (pas « صحافة » : il était confondu avec les unes de presse) : au premier passage entre minuit et 3 h (heure de Madrid), les 3 sujets de la veille, choisis
    par Claude parmi les articles du site, publiés tout de suite dans Typefully (pas de lien). Une fois par jour."""
    utc = utc or maintenant()
    madrid = heure_madrid(utc)
    if madrid.hour >= 3 or not reglage("typefully_api_key") or not CONFIG.get("typefully_social_set"):
        return 0
    jour = (madrid - timedelta(days=1)).date().isoformat()
    con.execute("CREATE TABLE IF NOT EXISTS resumes (jour TEXT PRIMARY KEY, typefully TEXT)")
    if con.execute("SELECT 1 FROM resumes WHERE jour = ?", (jour,)).fetchone():
        return 0
    # shortcut: les jours de changement d'heure, la fenêtre de la veille est décalée d'une heure ; sans effet sur le choix des sujets
    debut = datetime.fromisoformat(jour) - (madrid - utc)
    arts = con.execute("SELECT * FROM articles WHERE date >= ? AND date < ? ORDER BY date",
                       (debut.isoformat(timespec="seconds"), (debut + timedelta(days=1)).isoformat(timespec="seconds"))).fetchall()
    if not arts:
        con.execute("INSERT INTO resumes VALUES (?, 'vide')", (jour,))
        con.commit()
        return 0
    blocs = [f"- [{a['section']}, {'information' if a['section'] == 'actus' or a['mode'] == 'info' else 'opinion'}] {a['titre']} : {a['chapeau']}"
             f" (média : {a['journal']} ; auteur : {a['auteur_ar'] or a['auteur'] or 'non signé'})" for a in arts]
    try:
        tweets = [str(x).strip() for x in extraire_json(appeler_claude(PROMPT_RESUME.format(jour=jour, articles="\n".join(blocs)),
                                                                       CONFIG.get("modele_redaction", "sonnet")))]
        if not 2 <= len(tweets) <= 5 or any(not x for x in tweets) or longueur("\n\n".join(tweets)) > LIMITE_LONG:
            raise ValueError(f"thread inutilisable ({len(tweets)} tweets)")
        posts = [{"text": tags_a_la_fin("\n\n".join(tweets))}]  # un seul tweet long
        d = typefully_api("drafts", {"draft_title": f"حصاد ريال مدريد {jour}", "publish_at": "now",
                                     "platforms": {"x": {"enabled": True, "posts": posts}}})
    except (OSError, ValueError, KeyError, ErreurClaude) as err:  # repris au passage suivant, tant qu'on est avant 3 h
        detail = err.read().decode("utf-8", "replace")[:300] if hasattr(err, "read") else ""
        print(f"  ! résumé du jour : envoi impossible ({err}) {detail}, repris au prochain passage")
        noter(con, "Résumé du jour", f"{err} {detail}")
        return 0
    con.execute("INSERT INTO resumes VALUES (?, ?)", (jour, str(d["id"])))
    con.commit()
    noter(con, "Résumé du jour")
    return 1


UNES = (("marca", "Marca", "ماركا"), ("as", "AS", "آس"))  # code kiosko.net, nom, nom arabe
JOURS_AR = ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد")
MOIS_AR = ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")
MOIS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
PROMPT_UNE = """Lis le fichier {fichier} : la une du journal sportif espagnol {nom} du {jour}.
Relève les sujets qui concernent le Real Madrid (joueurs, entraîneur, club, matchs), du plus grand titre au plus petit, au plus 4.
Commence toujours par le titre imprimé en plus gros caractères s'il touche le Real Madrid, même quand c'est une personne extérieure
qui parle d'un joueur du Real (ex. l'entraîneur adverse : « Quisimos fichar a Diomande ») ; dans ce cas, dis qui parle.
Effectif du Real Madrid (clé latine = graphie arabe à reprendre telle quelle) : {personnes}.
Un nom imprimé proche d'un de ces noms est ce joueur (une lettre mal lue sur l'image : « DIAMANDE » est Diomande) : écris-le
correctement dans toutes les langues, avec sa graphie arabe de cette liste.
Pour chaque sujet, un seul élément : le titre tel qu'il est imprimé (avec son sous-titre seulement s'il est indispensable pour
comprendre), et sa traduction fidèle en arabe, en français et en anglais, noms propres dans leur graphie usuelle.
Réponds UNIQUEMENT avec un tableau JSON, sans texte avant ni après : [{{"es": "...", "ar": "...", "fr": "...", "en": "..."}}],
ou [] si la une ne parle pas du Real Madrid."""


def une_frontpages(code, jour):
    """Adresse de la grande image (1200 px) de la une du jour sur frontpages.com, ou None si elle n'y est pas encore. Elle y est
    vers 23 h 30 la veille (20 nov. 2026 : Marca à 23 h 37), contre 6 h 30 chez kiosko. La page cache l'adresse en base64 (atob) ;
    récupération autorisée explicitement par l'utilisateur le 20 nov. 2026."""
    try:
        date, url = lire_frontpages(lire_page(f"https://www.frontpages.com/{code}/"))
    except OSError:
        return None
    return url if date == f"{jour:%d/%m/%Y}" else None  # sinon encore la une de la veille


def lire_frontpages(page):
    """(date de la une « jj/mm/aaaa », adresse de la grande image) lues dans une page de frontpages.com, None pour ce qui manque."""
    date, adresse = re.search(r'alt="Cover [^"]*?(\d{2}/\d{2}/\d{4})"', page), re.search(r"atob\('([A-Za-z0-9+/=]+)'\)", page)
    chemin = base64.b64decode(adresse[1]).decode() if adresse else ""
    return date[1] if date else None, "https://www.frontpages.com" + chemin if chemin.startswith("/g/") else None


def en_jpeg(image):
    """(nom, octets) en JPEG : frontpages ne sert que du WebP, que Facebook n'accepte pas officiellement."""
    nom, contenu = image
    if nom.endswith(".jpg"):
        return image
    from PIL import Image  # importé ici : le workflow de la revue n'installe pas Pillow
    tampon = io.BytesIO()
    with Image.open(io.BytesIO(contenu)) as im:
        im.convert("RGB").save(tampon, "JPEG", quality=90)
    return nom.rsplit(".", 1)[0] + ".jpg", tampon.getvalue()


def facebook_photo(page, jeton, image, legende):
    """Photo envoyée en fichier à la Page (multipart) : Facebook n'a pas à aller la chercher chez le kiosque."""
    b = uuid.uuid4().hex
    champs = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                      for k, v in (("caption", legende), ("access_token", jeton)))
    corps = (champs + f'--{b}\r\nContent-Disposition: form-data; name="source"; filename="{image[0]}"\r\n'
             f"Content-Type: image/jpeg\r\n\r\n".encode() + image[1] + f"\r\n--{b}--\r\n".encode())
    req = urllib.request.Request(f"{GRAPH}{page}/photos", corps, {"Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=60) as rep:
        return json.load(rep)


def tweets_une(entete, lignes):
    """Titres d'une une répartis en thread : le 1er tweet (en-tête, image, hashtag) prend ce qui tient dans la limite de X,
    la suite va dans des réponses, sans retirer de titre."""
    tweets, courant = [], []
    texte = lambda l: entete + "\n".join(l) + "\n\n#ريال_مدريد" if not tweets else "\n".join(l)
    for ligne in lignes:
        if courant and longueur(texte(courant + [ligne])) > LIMITE_LONG:
            tweets.append(texte(courant))
            courant = []
        courant.append(ligne)
    return tweets + [texte(courant)]


def unes_du_jour(con, utc=None):
    """Unes de Marca et AS (frontpages.com, sinon kiosko.net), une publication par journal sur X (Typefully, tout de suite) et sur
    la Page Facebook, de 23 h la veille à midi (heure de Madrid) : Claude lit l'image et traduit les titres sur le Real Madrid.
    Une une sans le Real n'est pas publiée. Chaque envoi est noté à part (table unes) : un échec n'est repris que là où il a eu lieu."""
    madrid = heure_madrid(utc or maintenant())
    if 12 <= madrid.hour < 23 and not os.environ.get("FORCER_UNES"):  # FORCER_UNES : lancé à la main
        return 0
    jour = madrid.date() + timedelta(days=1 if madrid.hour >= 23 else 0)  # dès 23 h : la une du lendemain
    con.execute("CREATE TABLE IF NOT EXISTS unes (jour TEXT, journal TEXT, titres TEXT, x TEXT, facebook TEXT, PRIMARY KEY (jour, journal))")
    x_ok = reglage("typefully_api_key") and CONFIG.get("typefully_social_set")
    jeton, page = reglage("facebook_page_token"), reglage("facebook_page_id")
    n = 0
    for code, nom, nom_ar in UNES:
        cle = (jour.isoformat(), code)
        con.execute("INSERT OR IGNORE INTO unes (jour, journal) VALUES (?, ?)", cle)
        u = con.execute("SELECT * FROM unes WHERE jour = ? AND journal = ?", cle).fetchone()
        reste_x, reste_fb = x_ok and u["x"] is None, jeton and page and u["facebook"] is None
        if not (reste_x or reste_fb):
            continue
        url = une_frontpages(code, jour) or f"https://img.kiosko.net/{jour:%Y/%m/%d}/es/{code}.750.jpg"
        try:
            image = en_jpeg(telecharger_image(url, f"une-{code}"))  # kiosko : 404 tant que la une n'est pas sortie
            if u["titres"] is None:  # Claude ne lit chaque une qu'une fois, même si un envoi échoue ensuite
                fichier = BASE / f"une-{code}.jpg"
                fichier.write_bytes(image[1])
                try:
                    titres = extraire_json(appeler_claude(PROMPT_UNE.format(fichier=fichier, nom=nom, jour=jour.isoformat(), personnes=", ".join(
                        f"{k} = {p['nom']}" for k, p in CONFIG.get("personnes", {}).items())),
                                                          CONFIG.get("modele_redaction", "sonnet"), outils="Read"))
                finally:
                    fichier.unlink(missing_ok=True)
                titres = [t for t in titres if isinstance(t, dict) and t.get("ar")]
                con.execute("UPDATE unes SET titres = ? WHERE jour = ? AND journal = ?", (json.dumps(titres, ensure_ascii=False), *cle))
                con.commit()
            else:
                titres = json.loads(u["titres"])
            if not titres:  # pas de Real Madrid en une : rien à publier
                con.execute("UPDATE unes SET x = 'sans', facebook = 'sans' WHERE jour = ? AND journal = ?", cle)
                con.commit()
                continue
            if reste_x:
                tweets = tweets_une(f"📰 غلاف {nom_ar} | {JOURS_AR[jour.weekday()]} {jour.day} {MOIS_AR[jour.month - 1]}\n\n",
                                    [f"▪️ {t['ar']}" for t in titres])
                media = typefully_image(*image)
                if not media:
                    raise ValueError("image pas prête dans Typefully")
                posts = [{"text": tw} for tw in tweets]
                posts[0]["media_ids"] = [media]
                d = typefully_api("drafts", {"draft_title": f"غلاف {nom_ar} {jour}", "publish_at": "now",
                                             "platforms": {"x": {"enabled": True, "posts": posts}}})
                con.execute("UPDATE unes SET x = ? WHERE jour = ? AND journal = ?", (str(d["id"]), *cle))
                con.commit()
                n += 1
            if reste_fb:
                legende = f"📰 {nom} · la une du {jour.day} {MOIS_FR[jour.month - 1]}\n\n" + "\n\n".join(
                    "\n".join(f"{d} {t[k]}" for d, k in (("⚜️", "fr"), ("🇨🇦", "en"), ("🇪🇸", "es")) if t.get(k)) for t in titres)
                fb = facebook_photo(page, jeton, image, legende)
                con.execute("UPDATE unes SET facebook = ? WHERE jour = ? AND journal = ?", (str(fb.get("id", "ok")), *cle))
                con.commit()
                n += 1
            noter(con, f"Une de {nom}")
        except (OSError, ValueError, KeyError, ErreurClaude) as err:
            detail = err.read().decode("utf-8", "replace")[:300] if hasattr(err, "read") else ""
            print(f"  ! une de {nom} : pas encore publiée ({err}) {detail}, reprise au prochain passage")
            if getattr(err, "code", None) != 404:  # 404 : la une n'est pas encore sortie, ce n'est pas une panne
                noter(con, f"Une de {nom}", f"{err} {detail}")
    return n


TYPEFULLY = "https://api.typefully.com/v2/social-sets/{}/"


def liens_x(con, max_appels=30):
    """Adresse sur X de chaque publication Typefully des 3 derniers jours (threads, résumés du jour, unes), relevée une fois
    publiée : elle servira à croiser l'export des statistiques de X (Premium) avec la base. Table liens_x."""
    con.execute("CREATE TABLE IF NOT EXISTS liens_x (typefully TEXT PRIMARY KEY, url TEXT, date TEXT)")
    if not reglage("typefully_api_key") or not CONFIG.get("typefully_social_set"):
        return 0
    connexion_threads(con)
    ids = [r[0] for r in con.execute(f"SELECT typefully FROM threads WHERE {ENVOYES} AND date >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-3 days')")]
    for table, colonne in (("resumes", "typefully"), ("unes", "x")):
        if con.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone():
            ids += [r[0] for r in con.execute(f"SELECT {colonne} FROM {table} WHERE jour >= date('now', '-3 days')"
                                              f" AND {colonne} IS NOT NULL AND {colonne} NOT IN ('sans', 'vide')")]
    deja = {r[0] for r in con.execute("SELECT typefully FROM liens_x")}
    n = 0
    for i in [i for i in dict.fromkeys(ids) if i not in deja][:max_appels]:
        try:
            d = typefully_api(f"drafts/{i}")
        except (OSError, ValueError) as err:  # sans gravité : repris au prochain passage
            print(f"  ! Typefully : adresse X du brouillon {i} illisible ({err})")
            break
        if d.get("status") == "published" and d.get("x_published_url"):
            con.execute("INSERT INTO liens_x VALUES (?, ?, ?)", (i, d["x_published_url"], d.get("published_at") or ""))
            n += 1
    con.commit()
    return n


def typefully_api(chemin, corps=None):
    """Appelle l'API Typefully v2 (clé : TYPEFULLY_API_KEY, compte : "typefully_social_set" dans config.json)."""
    req = urllib.request.Request((TYPEFULLY.format(CONFIG["typefully_social_set"]) + chemin).rstrip("/"),
                                 json.dumps(corps).encode() if corps is not None else None,
                                 {"Authorization": f"Bearer {reglage('typefully_api_key')}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as rep:
        return json.load(rep)


def quota_typefully_bas():
    """Publications Typefully restantes du mois au plus à "typefully_reserve" (config.json) : les opinions attendent alors le
    mois suivant (28 nov. 2026 : 152 restantes à 3 jours de la remise à zéro, pour 45 à 90 posts par jour). Compteur
    illisible : rien n'est retenu (l'envoi échouerait de toute façon si Typefully était en panne)."""
    reserve = CONFIG.get("typefully_reserve", 0)
    if not reserve:
        return False
    try:
        reste = (typefully_api("").get("publishing_quota") or {}).get("remaining")
    except (OSError, ValueError) as err:
        print(f"  ! Typefully : quota illisible ({err})")
        return False
    if reste is not None and reste <= reserve:
        print(f"  Typefully : {reste} publications restantes ce mois (réserve {reserve}), opinions retenues")
        return True
    return False


TYPES_IMAGE = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


def telecharger_image(url, article_id):
    """Image principale de l'article source -> (nom de fichier, octets) ; ValueError si ce n'est pas une image de 5 Mo au plus
    (limite de X)."""
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
        ext = TYPES_IMAGE.get(r.headers.get_content_type())
        contenu = r.read(30_000_001)
    if ext and 5_000_000 < len(contenu) <= 30_000_000:  # ex. PNG de 8 Mo chez COPE : recompressé en JPEG
        from io import BytesIO
        from PIL import Image
        with Image.open(BytesIO(contenu)) as im:
            im.thumbnail((2048, 2048))
            tampon = BytesIO()
            im.convert("RGB").save(tampon, "JPEG", quality=85)
        contenu, ext = tampon.getvalue(), "jpg"
    if not ext or len(contenu) > 5_000_000:
        raise ValueError(f"image inutilisable ({url[:60]})")
    return f"article-{article_id}.{ext}", contenu


FIL_CLUB = "https://syndication.twitter.com/srv/timeline-profile/screen-name/realmadrid"


def visuel_convocation(depuis):
    """(id du post, image) du dernier post « ¡Nuestros convocados! » de @realmadrid publié après `depuis` (UTC), sinon None.
    Lu sur la page publique d'intégration du fil (20 derniers posts, sans compte ni Bright Data, moins d'une seconde) :
    pas une API officielle, X peut la couper."""
    page = lire_page(FIL_CLUB)
    donnees = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not donnees:
        raise ValueError("fil du club illisible (page d'intégration de X changée ?)")
    limite = depuis.replace(tzinfo=timezone.utc)
    for e in json.loads(donnees.group(1))["props"]["pageProps"]["timeline"]["entries"]:
        tw = e.get("content", {}).get("tweet", {})
        medias = tw.get("extended_entities", tw.get("entities", {})).get("media", [])
        if ("convocados" in (tw.get("full_text") or tw.get("text") or "").lower() and medias
                and datetime.strptime(tw["created_at"], "%a %b %d %H:%M:%S %z %Y") >= limite):
            return tw["id_str"], medias[0]["media_url_https"] + "?name=orig"
    return None


def images_thread(t):
    """Photo principale puis galerie (séances d'entraînement du club), sans doublon, au plus "max_images_tweet" (20 sur X
    depuis le 12 nov. 2026, essai via Typefully réussi le 18 nov.)."""
    galerie = json.loads((t["galerie"] if "galerie" in t.keys() else "") or "[]")
    urls, vues = [], set()
    for u in [t["image"], *galerie]:
        cle = (u or "").split("?")[0].rsplit("_", 1)[-1]  # même photo sous deux noms : ND_ENTRENAMIENTO_03_DB11662 = 13_DB11662
        if u and cle not in vues:
            vues.add(cle)
            urls.append(u)
    return urls[:CONFIG.get("max_images_tweet", 4)]


def typefully_image(nom, contenu):
    """Envoie une image ; retourne son media_id, ou None si elle n'est pas prête à temps."""
    m = typefully_api("media/upload", {"file_name": nom})
    url = urllib.parse.urlsplit(m["upload_url"])
    # PUT nu : l'URL signée refuse tout en-tête ajouté (urllib ajouterait un Content-Type)
    cnx = http.client.HTTPSConnection(url.netloc, timeout=60)
    cnx.request("PUT", f"{url.path}?{url.query}", contenu)
    if cnx.getresponse().status not in (200, 204):
        return None
    for _ in range(15):
        if typefully_api(f"media/{m['media_id']}").get("status") == "ready":
            return m["media_id"]
        time.sleep(2)
    return None


def sans_tweet_de_lien(tweets):
    """Thread publié tout de suite : X refuse la publication immédiate d'un thread qui contient un lien (403 de Typefully).
    Le dernier tweet (crédit + lien de la source) est retiré, l'auteur l'ajoute à la main sur X, et le reste est renuméroté.
    Retourne (tweets, quand) ; si un lien reste ailleurs, le thread entier est programmé 2 minutes plus tard."""
    reste = [NUMERO.sub("", x) for x in (tweets[:-1] if tweets and URL.search(tweets[-1]) else tweets)]
    if not reste or any(URL.search(x) for x in reste):
        return tweets, (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(timespec="seconds")
    return ([f"{x}\n\n{i}/{len(reste)}" for i, x in enumerate(reste, 1)] if len(reste) > 1 else reste), "now"


def orateur(tweet):
    """Qui parle, d'après l'étiquette du 1er tweet : « 🎙️ مؤتمر مورينيو | » et « 🗣️ مورينيو | » donnent « مورينيو »."""
    m = ETIQUETTE.match(tweet.strip())
    return re.sub(r"[^\w\s]", "", m[0]).replace("مؤتمر", "").strip() if m else ""


DIRECT = ("Marca", "AS")  # conférence en direct : chaque article de ces journaux (une déclaration forte) devient un tweet


def medias_thread(t, couvertures, dossier_couv):
    """Identifiants Typefully des photos de l'article source (à remplacer dans Typefully avant la publication), sinon de sa
    couverture. Une photo refusée est passée ; les autres erreurs remontent à l'envoi du thread."""
    medias = []
    for i, url in enumerate(images_thread(t)):
        try:
            medias.append(typefully_image(*telecharger_image(url, f"{t['article_id']}-{i}")))
        except (OSError, ValueError) as err:
            print(f"  ! Typefully : image de l'article refusée ({err})")
    medias = [m for m in medias if m]
    couv = couvertures.get(t["article_id"])
    if not medias and not couv:  # pas de couverture d'avance pour un article avec image : faite à la demande
        from couvertures import generer_couvertures
        couv = generer_couvertures([t], dossier_couv.parent, menage=False).get(t["article_id"])
    if not medias and couv:
        medias = [m for m in [typefully_image(couv, (dossier_couv / couv).read_bytes())] if m]
    return medias


def ecarter(con, article_id, motif):
    """Thread jamais déposé dans Typefully (« sans ») : rien à relire ni à supprimer à la main."""
    con.execute("UPDATE threads SET typefully = 'sans', statut = ?, envoye = ? WHERE article_id = ?",
                (f"bloqué : {motif}", maintenant().isoformat(timespec="seconds"), article_id))
    con.commit()


def vers_typefully(con, couvertures, dossier_couv):
    """Dépose les nouveaux threads dans Typefully, la photo de l'article source sur le 1er tweet (sinon la couverture) :
    au prochain créneau libre de sa file (publiés seuls, le plus ancien d'abord) si "typefully_publish_at" vaut
    "next-free-slot" dans config.json, sinon en brouillons à publier à la main."""
    connexion_threads(con)
    if not reglage("typefully_api_key") or not CONFIG.get("typefully_social_set"):
        print("  ! Typefully : TYPEFULLY_API_KEY ou typefully_social_set manquant, dépôt ignoré")
        return 0
    visuel_liste(con)  # le visuel du club d'abord : il sort avant la liste en texte
    n, plafond, echec = 0, False, None
    import conference
    from calendrier import direct_actif
    session = conference.session_recente()
    suivie = session if session and session.get("journal") else None  # conférence commencée : journal choisi
    # direct lancé, conférence pas encore commencée (ou conference.json pas encore poussé) : seuls les articles de conférence
    # de Marca/AS lui sont laissés, les autres nouvelles partent
    attente = bool(session and not session.get("fini") and not session.get("journal")) or (
        (session is None or session.get("fini")) and direct_actif("conference_direct.yml"))
    direct = conference.en_direct()
    hors = set(session.get("vus", [])) - set(session.get("liens", [])) if session else set()  # jugés hors conférence par le direct
    quota_bas = quota_typefully_bas()
    deja_direct = (session.get("tweets") or []) if session else []  # déclarations déjà tweetées par le direct
    for t in con.execute("SELECT t.article_id, t.tweets, t.date AS cree, a.* FROM threads t JOIN articles a ON a.id = t.article_id"
                         " WHERE t.typefully IS NULL ORDER BY (a.section = 'actus' OR a.mode = 'info') DESC, t.article_id LIMIT ?", (CONFIG.get("max_threads", 10),)).fetchall():
        tweets = json.loads(t["tweets"])
        conf = t["mode"] == "conference" or est_conference(tweets[0])  # l'étiquette compte aussi : le tri a pu dire « info »
        # conférence suivie en direct (conference.py) : ses articles sont tweetés par le direct, l'autre journal est ignoré
        if (suivie or direct or attente) and conf and t["journal"] in DIRECT and t["lien"] not in hors:
            if (direct or attente) and (not suivie or (t["journal"] == suivie["journal"] and t["lien"] not in suivie["liens"])):
                continue  # le direct va le tweeter ; repris après le direct s'il l'a manqué
            if t["lien"] in suivie["liens"] or t["journal"] != suivie["journal"]:
                motif = "publiée en direct" if t["lien"] in suivie["liens"] else f"conférence suivie sur {suivie['journal']}"
                print(f"  Typefully : article {t['article_id']} écarté ({motif})")
                ecarter(con, t["article_id"], motif)
                continue
        elif direct and not est_officiel(t) and not est_liste(tweets[0]):  # la liste part dès qu'elle sort
            # la conférence d'abord : la file Typefully publie toutes les 5 min, une nouvelle y sortirait au milieu du direct ;
            # retenue, elle part au premier passage après le direct (le récapitulatif du club attend, lui, sa page complète)
            continue
        # une nouvelle part tout de suite ; une opinion attend le prochain créneau de la file (toutes les 5 min, 24 h sur 24)
        nouvelle = t["section"] == "actus" or t["mode"] == "info"
        if quota_bas and not nouvelle:  # la réserve du mois va aux nouvelles, au direct et aux conférences
            if maintenant() - datetime.fromisoformat(t["cree"]) > timedelta(hours=24):  # pas de vieilles opinions au retour du quota
                ecarter(con, t["article_id"], "quota Typefully")
            continue
        motifs = controler_thread(con, t["article_id"], tweets, est_officiel(t), deja_direct if conf else ())
        if est_compo(tweets[0]) and not t["image"]:  # brouillon : l'image de la composition est à choisir à la main
            motifs.append("image de la composition introuvable")
        doublon = next((m for m in motifs if m.startswith("doublon")), None)
        if doublon:  # confirmé par Claude : pas de brouillon à supprimer à la main
            print(f"  Typefully : article {t['article_id']} écarté ({doublon})")
            ecarter(con, t["article_id"], doublon)
            continue
        quand = CONFIG.get("typefully_publish_at_actus") if nouvelle else None
        if quand == "now" and not motifs and not est_liste(tweets[0]) and con.execute(  # la liste n'attend jamais
                "SELECT count(*) FROM threads WHERE statut = 'immédiat' AND envoye >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-1 hour')"
        ).fetchone()[0] >= CONFIG.get("max_publications_heure", 8):
            plafond = True  # reporté au passage suivant, sans être bloqué
            continue
        try:
            # la liste part en texte seul ; le visuel du club a son propre post (visuel_liste)
            medias = [] if est_liste(tweets[0]) else medias_thread(t, couvertures, dossier_couv)
            if quand == "now" and not motifs:
                tweets, quand = sans_tweet_de_lien(tweets)
            posts = [{"text": tw} for tw in tweets]
            if medias:
                posts[0]["media_ids"] = medias
            titre = (f"⛔ {', '.join(motifs)} | " if motifs else "") + t["titre"]
            corps = {"draft_title": titre[:500], "platforms": {"x": {"enabled": True, "posts": posts}}}
            if not motifs and (quand or CONFIG.get("typefully_publish_at")):  # bloqué : simple brouillon, publié à la main
                corps["publish_at"] = quand or CONFIG["typefully_publish_at"]
            d = typefully_api("drafts", corps)
        except (OSError, KeyError, ValueError) as err:  # réseau, clé refusée... : repris au prochain passage
            # Typefully explique son refus dans le corps de la réponse ; un thread refusé ne bloque plus les suivants
            detail = err.read().decode("utf-8", "replace")[:300] if hasattr(err, "read") else ""
            print(f"  ! Typefully : envoi impossible pour l'article {t['article_id']} ({err}) {detail}, repris au prochain passage")
            echec = f"{err} {detail}"
            continue
        statut = f"bloqué : {', '.join(motifs)}" if motifs else ("immédiat" if quand == "now" else "file")
        if motifs:
            print(f"  ! Typefully : article {t['article_id']} mis en brouillon ({', '.join(motifs)})")
        con.execute("UPDATE threads SET typefully = ?, statut = ?, envoye = ? WHERE article_id = ?",
                    (str(d["id"]), statut, maintenant().isoformat(timespec="seconds"), t["article_id"]))
        con.commit()
        n += 1
    if plafond:
        print(f"  ! Typefully : plafond de {CONFIG.get('max_publications_heure', 8)} publications immédiates par heure atteint,"
              " la suite au prochain passage")
    if n or echec:  # panne seulement si rien n'est passé : un thread refusé seul ne l'est pas
        noter(con, "Typefully", None if n else echec)
    return n


def bright_data_api(chemin, corps=None):
    """Appel à l'API Web Scraper de Bright Data (curl : sur le PC, Python refuse le certificat d'api.brightdata.com)."""
    import subprocess
    commande = ["curl", "-s", "-f", "-m", "120", f"https://api.brightdata.com/datasets/v3/{chemin}",
                "-H", f"Authorization: Bearer {reglage('brightdata_api_token')}"]
    if corps is not None:
        commande += ["-H", "Content-Type: application/json", "-d", json.dumps(corps)]
    return json.loads(subprocess.run(commande, capture_output=True, check=True, timeout=130).stdout)


def visuel_bright_data(depuis):
    """Secours de visuel_convocation quand X refuse sa page d'intégration : mêmes posts lus par Bright Data (1 à 2 min,
    une quinzaine de posts facturés). (id du post, image) ou None."""
    jour = maintenant()
    posts = bright_data_api(
        "scrape?dataset_id=gd_lwxkxvnf1cynvib9co&type=discover_new&discover_by=profile_url&format=json",
        {"input": [{"url": "https://x.com/realmadrid", "num_of_posts": 20, "start_date": f"{depuis:%Y-%m-%d}",
                    "end_date": f"{jour + timedelta(days=1):%Y-%m-%d}"}]})
    if isinstance(posts, dict):  # pas fini en 1 min : snapshot à attendre
        snap = posts["snapshot_id"]
        for _ in range(12):
            time.sleep(10)
            if bright_data_api(f"progress/{snap}").get("status") in ("ready", "failed"):
                break
        posts = bright_data_api(f"snapshot/{snap}?format=json")
    trouves = sorted((p for p in posts if isinstance(p, dict) and p.get("photos") and p.get("id")
                      and (p.get("date_posted") or "") >= depuis.isoformat()
                      and "convocados" in (p.get("description") or "").lower()), key=lambda p: p["date_posted"])
    return (str(trouves[-1]["id"]), trouves[-1]["photos"][0] + "?name=orig") if trouves else None


def fenetre_convocation(heures=72, maintenant=maintenant):
    """Début de la fenêtre où le club peut publier la convocation du prochain match de matchs.json : 72 h avant le coup
    d'envoi (Supercoupe à l'étranger : liste publiée avant le voyage, environ 48 h avant), jamais avant la fin du match
    précédent (coup d'envoi + 8 h, choix de l'utilisateur du 24 nov.). None hors fenêtre."""
    try:
        debuts = sorted(datetime.fromisoformat(m["debut"]) for m in json.loads((BASE / "matchs.json").read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return None
    now = maintenant()
    prochain = next((d for d in debuts if d > now), None)
    if not prochain:
        return None
    debut = max([prochain - timedelta(hours=heures)] + [d + timedelta(hours=8) for d in debuts if d < prochain])
    return debut if now >= debut else None


def visuel_liste(con):
    """1er post de la convocation : le visuel « convocados » de @realmadrid avec une ligne, publié dès que le club le sort
    (vérifié à chaque passage), une fois par post du club. La liste en texte suit quand elle arrive (« 📝 القائمة »)."""
    con.execute("DROP TABLE IF EXISTS convocations")  # ancienne version (recherche par Bright Data, 23 nov.)
    con.execute("CREATE TABLE IF NOT EXISTS visuels_convocation (tweet_id TEXT PRIMARY KEY, typefully TEXT, envoye TEXT)")
    debut = fenetre_convocation()
    if not debut or con.execute("SELECT 1 FROM visuels_convocation WHERE envoye >= ?", (debut.isoformat(),)).fetchone():
        return  # hors fenêtre, ou visuel de ce match déjà publié
    # une vérification par quart d'heure (quelques minutes de retard ne gênent pas, choix de l'utilisateur du 24 nov.) :
    # la page d'intégration de X, et Bright Data seulement si X refuse ; 14 min et non 15 : les passages dérivent de
    # quelques secondes, une vérification ne doit pas glisser au passage suivant
    con.execute("DROP TABLE IF EXISTS secours_convocation")
    con.execute("DROP TABLE IF EXISTS pause_x")  # versions du 24 nov. matin
    con.execute("CREATE TABLE IF NOT EXISTS verif_convocation (cle TEXT PRIMARY KEY, dernier TEXT)")
    dernier = con.execute("SELECT dernier FROM verif_convocation WHERE cle = 'visuel'").fetchone()
    if dernier and dernier[0] > (maintenant() - timedelta(minutes=14)).isoformat():
        return
    con.execute("INSERT OR REPLACE INTO verif_convocation VALUES ('visuel', ?)", (maintenant().isoformat(timespec="seconds"),))
    con.commit()
    try:
        trouve = visuel_convocation(debut)
    except (OSError, ValueError, KeyError) as err:  # refus de X (429) ou page changée : Bright Data en plan B
        print(f"  ! visuel de la convocation : page d'intégration de X refusée ({err}), recherche par Bright Data")
        try:
            trouve = visuel_bright_data(debut)
        except Exception as err2:  # noqa: BLE001 - Bright Data en panne ou quota épuisé : vérification suivante
            print(f"  ! visuel de la convocation : Bright Data aussi en échec ({err2})")
            return
    if not trouve or con.execute("SELECT 1 FROM visuels_convocation WHERE tweet_id = ?", (trouve[0],)).fetchone():
        return
    try:
        media = typefully_image(*telecharger_image(trouve[1], f"convocation-{trouve[0]}"))
        if not media:  # image pas prête chez Typefully : sans elle, ce post n'a pas lieu d'être
            raise ValueError("image pas prête")
        d = typefully_api("drafts", {"draft_title": "📋 قائمة ريال مدريد (visuel du club)", "publish_at": "now",
                                     "platforms": {"x": {"enabled": True, "posts": [
                                         {"text": "📋 قائمة ريال مدريد\n\n#ريال_مدريد", "media_ids": [media]}]}}})
    except (OSError, KeyError, ValueError) as err:  # repris au passage suivant
        print(f"  ! Typefully : visuel de la convocation non envoyé ({err})")
        return
    con.execute("INSERT INTO visuels_convocation VALUES (?, ?, ?)", (trouve[0], str(d["id"]), maintenant().isoformat(timespec="seconds")))
    con.commit()
    print("  Typefully : visuel de la convocation publié")


def graph_lire(chemin, **params):
    with urllib.request.urlopen(GRAPH + chemin + "?" + urllib.parse.urlencode(params), timeout=60) as rep:
        return json.load(rep)


def jeton_permanent(app_id, app_secret, jeton_court, page):
    """Jeton de Page qui n'expire pas, à partir d'un jeton utilisateur de courte durée (celui de l'Explorateur de l'API
    Graph, valable 1 à 2 heures) : il est échangé contre un jeton utilisateur de 60 jours, dont les jetons de Page
    sont permanents. Vérifie qu'il n'expire pas et qu'il a le droit de publier."""
    long = graph_lire("oauth/access_token", grant_type="fb_exchange_token", client_id=app_id, client_secret=app_secret,
                      fb_exchange_token=jeton_court)["access_token"]
    pages = {str(p["id"]): p for p in graph_lire("me/accounts", fields="id,name,access_token", limit=100, access_token=long)["data"]}
    if str(page) not in pages:
        raise ValueError(f"la Page {page} n'est pas gérée par ce compte (Pages trouvées : {', '.join(pages) or 'aucune'})")
    jeton = pages[str(page)]["access_token"]
    infos = graph_lire("debug_token", input_token=jeton, access_token=f"{app_id}|{app_secret}")["data"]
    if infos.get("expires_at") or "pages_manage_posts" not in infos.get("scopes", []):
        raise ValueError(f"jeton inutilisable : expire le {infos.get('expires_at')}, permissions {infos.get('scopes')}")
    return jeton, pages[str(page)]["name"]


def retirer(con, article_id):
    """Retire la publication d'un article : supprime le post de la Page Facebook et donne l'adresse du thread X à supprimer
    à la main (Typefully ne supprime pas un tweet déjà publié). Retourne les lignes à afficher."""
    lignes = []
    connexion_page(con)
    fb = con.execute("SELECT post FROM page_facebook WHERE article_id = ?", (article_id,)).fetchone()
    if fb and fb[0] and not fb[0].startswith("bloqu"):
        req = urllib.request.Request(f"{GRAPH}{fb[0]}?" + urllib.parse.urlencode({"access_token": reglage("facebook_page_token")}),
                                     method="DELETE")
        with urllib.request.urlopen(req, timeout=60) as rep:
            lignes.append(f"Facebook : post {fb[0]} supprimé ({json.load(rep)})")
    else:
        lignes.append("Facebook : aucun post connu pour cet article (publié avant l'enregistrement des numéros, ou jamais publié)")
    connexion_threads(con)
    th = con.execute("SELECT typefully FROM threads WHERE article_id = ?", (article_id,)).fetchone()
    if th and th[0] and th[0] != "avant":
        d = typefully_api(f"drafts/{th[0]}")
        lignes.append(f"X : à supprimer à la main : {d.get('x_published_url') or 'pas encore publié, brouillon Typefully ' + th[0]}")
    else:
        lignes.append("X : aucun thread connu pour cet article")
    return lignes


if __name__ == "__main__":  # python threads.py : renouvelle le jeton de la Page Facebook (voir LISEZMOI.md)
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:2] == ["--retirer"]:  # python threads.py --retirer <numéro d'article>
        from commun import DB_PATH, restaurer_base
        restaurer_base(DB_PATH)
        base = sqlite3.connect(DB_PATH)
        try:
            print("\n".join(retirer(base, int(sys.argv[2]))))
        except (IndexError, ValueError):
            sys.exit("Usage : python threads.py --retirer <numéro d'article>")
        except OSError as err:
            sys.exit(f"Échec : {err} {err.read().decode('utf-8', 'replace')[:300] if hasattr(err, 'read') else ''}")
        sys.exit(0)
    local = json.loads(SECRETS.read_text(encoding="utf-8")) if SECRETS.exists() else {}
    manque = [k for k in ("facebook_app_id", "facebook_app_secret", "facebook_user_token", "facebook_page_id") if not local.get(k)]
    if manque:
        sys.exit(f"À ajouter dans secrets.json : {', '.join(manque)}")
    try:
        jeton, nom = jeton_permanent(local["facebook_app_id"], local["facebook_app_secret"], local["facebook_user_token"],
                                     local["facebook_page_id"])
    except urllib.error.HTTPError as err:
        sys.exit(f"Facebook a refusé : {err.read().decode('utf-8', 'replace')[:400]}")
    except (OSError, KeyError, ValueError) as err:
        sys.exit(f"Échec : {err}")
    local["facebook_page_token"] = jeton
    del local["facebook_user_token"]  # jeton de courte durée : il ne sert plus
    SECRETS.write_text(json.dumps(local, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Jeton permanent de la Page « {nom} » enregistré dans secrets.json.")

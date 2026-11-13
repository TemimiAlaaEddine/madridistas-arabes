"""Threads X (déposés dans Typefully) et publications sur la Page Facebook.

Le texte vient de l'article du site (déjà un résumé commenté), le dernier tweet crédite le journaliste et le
journal avec le lien de la source (X affiche alors la carte de l'article, avec sa photo principale).
Réglages : clés dans secrets.json sur le PC (variables d'environnement sur GitHub), "max_threads" dans config.json (threads et publications au plus par passage).
"""
import json
import os
import http.client
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from commun import BASE, CONFIG, ErreurClaude, appeler_claude, extraire_json, maintenant

LIMITE = 280
SECRETS = BASE / "secrets.json"  # token et chat sur le PC, hors git ; sur GitHub : variables d'environnement
URL = re.compile(r"https?://\S+")

# règles communes : thread écrit avec l'article (generer_site) ou après coup (decouper)
REGLES = """- Tweet 1, l'accroche : commence par ce qui arrête le lecteur dans son fil (le constat le plus fort, un chiffre, une courte citation, une vraie question), puis nomme l'auteur ou le média dans ce même tweet, à l'intérieur de la phrase. Ne commence jamais par « يرى الصحفي... » ni « وفقًا لـ... » ; pour une information, le fait d'abord, la source ensuite. Ajoute #ريال_مدريد à la fin.
- Tweets suivants : fidèles au texte, une idée par tweet, en phrases courtes qui se comprennent sans le tweet d'avant, en gardant ses citations «» telles quelles. L'avis reste attribué à son auteur, sans répéter « الكاتب » à chaque tweet. Le dernier porte la conclusion ou la phrase la plus marquante.
- Nombre de tweets : 2 ou 3 pour une information, 4 à 8 pour une opinion, 4 à 10 pour une conférence de presse (une déclaration forte par tweet).
- Chaque tweet fait AU MAXIMUM 240 caractères, espaces compris. Pas de lien, pas de numérotation, pas d'autre hashtag, pas d'intertitre « ## ».
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


def assembler(a, tweets):
    """Numérote les tweets puis ajoute le tweet de crédit (avec le lien), non numéroté : il peut être retiré à l'envoi
    et ajouté à la main sans fausser « i/n ». None si un tweet dépasse la limite de X ou si le thread est vide."""
    tweets = [str(t).strip() for t in tweets if str(t).strip()]
    n = len(tweets)
    tweets = [f"{t}\n\n{i}/{n}" for i, t in enumerate(tweets, 1)] if n > 1 else tweets
    tweets.append(credit(a))
    return tweets if n and all(longueur(t) <= LIMITE for t in tweets) else None


def connexion_threads(con):
    con.execute("CREATE TABLE IF NOT EXISTS threads (article_id INTEGER PRIMARY KEY, tweets TEXT, statut TEXT, date TEXT)")
    try:  # id du brouillon Typefully ; les threads d'avant l'ajout ne sont pas envoyés
        con.execute("ALTER TABLE threads ADD COLUMN typefully TEXT")
        con.execute("UPDATE threads SET typefully = 'avant'")
        con.commit()
    except sqlite3.OperationalError:
        pass  # colonne déjà présente


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


def vers_page(con, heures=24):
    """Publie sur la Page Facebook les nouvelles récentes (pas les opinions) avec titres traduits : titres FR/EN/ES en message, lien de la
    source en carte. Au plus max_threads par passage. Réglages : FACEBOOK_PAGE_TOKEN (jeton de la Page, permission
    pages_manage_posts) et FACEBOOK_PAGE_ID."""
    jeton, page = reglage("facebook_page_token"), reglage("facebook_page_id")
    if not jeton or not page:
        return 0  # pas encore configuré
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name = 'page_facebook'").fetchone():
        con.execute("CREATE TABLE page_facebook (article_id INTEGER PRIMARY KEY, date TEXT)")
        con.execute("INSERT INTO page_facebook SELECT id, 'avant' FROM articles")  # 1er passage : seuls les articles à venir partent
        con.commit()
    n = 0
    # la Page ne reçoit que les nouvelles : communiqués, actualités, compositions officielles et tout le mercato, chroniques
    # comprises (ni les autres opinions, ni les compositions probables)
    for a in con.execute("SELECT * FROM articles WHERE titres_fb != '' AND id NOT IN (SELECT article_id FROM page_facebook)"
                         " AND (section IN ('actus', 'mercato') OR mode = 'info')"
                         " AND date >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?) ORDER BY id LIMIT ?",
                         (f"-{heures} hours", CONFIG.get("max_threads", 10))).fetchall():
        if PROBABLE.search(a["titre_original"] or ""):
            continue
        corps = urllib.parse.urlencode({"message": titres_facebook(a), "link": a["lien"], "access_token": jeton}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{GRAPH}{page}/feed", corps), timeout=60) as rep:
                json.load(rep)
        except OSError as err:  # réseau coupé, jeton refusé (HTTPError est un OSError) : repris au prochain passage
            # Facebook explique son refus dans le corps de la réponse (jeton expiré, permission manquante...)
            detail = err.read().decode("utf-8", "replace")[:300] if hasattr(err, "read") else ""
            print(f"  ! Page Facebook : publication impossible ({err}) {detail}, reprise au prochain passage")
            break
        con.execute("INSERT INTO page_facebook VALUES (?, ?)", (a["id"], maintenant().isoformat(timespec="seconds")))
        con.commit()
        n += 1
    return n


TYPEFULLY = "https://api.typefully.com/v2/social-sets/{}/"


def typefully_api(chemin, corps=None):
    """Appelle l'API Typefully v2 (clé : TYPEFULLY_API_KEY, compte : "typefully_social_set" dans config.json)."""
    req = urllib.request.Request(TYPEFULLY.format(CONFIG["typefully_social_set"]) + chemin,
                                 json.dumps(corps).encode() if corps is not None else None,
                                 {"Authorization": f"Bearer {reglage('typefully_api_key')}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as rep:
        return json.load(rep)


TYPES_IMAGE = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


def telecharger_image(url, article_id):
    """Image principale de l'article source -> (nom de fichier, octets) ; ValueError si ce n'est pas une image de 5 Mo au plus
    (limite de X)."""
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
        ext = TYPES_IMAGE.get(r.headers.get_content_type())
        contenu = r.read(5_000_001)
    if not ext or len(contenu) > 5_000_000:
        raise ValueError(f"image inutilisable ({url[:60]})")
    return f"article-{article_id}.{ext}", contenu


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


NUMERO = re.compile(r"\n\n\d+/\d+$")


def sans_tweet_de_lien(tweets):
    """Thread publié tout de suite : X refuse la publication immédiate d'un thread qui contient un lien (403 de Typefully).
    Le dernier tweet (crédit + lien de la source) est retiré, l'auteur l'ajoute à la main sur X, et le reste est renuméroté.
    Retourne (tweets, quand) ; si un lien reste ailleurs, le thread entier est programmé 2 minutes plus tard."""
    reste = [NUMERO.sub("", x) for x in (tweets[:-1] if tweets and URL.search(tweets[-1]) else tweets)]
    if not reste or any(URL.search(x) for x in reste):
        return tweets, (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(timespec="seconds")
    return ([f"{x}\n\n{i}/{len(reste)}" for i, x in enumerate(reste, 1)] if len(reste) > 1 else reste), "now"


def vers_typefully(con, couvertures, dossier_couv):
    """Dépose les nouveaux threads dans Typefully, la photo de l'article source sur le 1er tweet (sinon la couverture) :
    au prochain créneau libre de sa file (publiés seuls, le plus ancien d'abord) si "typefully_publish_at" vaut
    "next-free-slot" dans config.json, sinon en brouillons à publier à la main."""
    connexion_threads(con)
    if not reglage("typefully_api_key") or not CONFIG.get("typefully_social_set"):
        print("  ! Typefully : TYPEFULLY_API_KEY ou typefully_social_set manquant, dépôt ignoré")
        return 0
    n = 0
    for t in con.execute("SELECT t.article_id, t.tweets, a.* FROM threads t JOIN articles a ON a.id = t.article_id"
                         " WHERE t.typefully IS NULL ORDER BY (a.section = 'actus' OR a.mode = 'info') DESC, t.article_id LIMIT ?", (CONFIG.get("max_threads", 10),)).fetchall():
        try:
            media = None
            if t["image"]:  # photo de l'article source, à remplacer dans Typefully avant la publication
                try:
                    media = typefully_image(*telecharger_image(t["image"], t["article_id"]))
                except (OSError, ValueError) as err:
                    print(f"  ! Typefully : image de l'article refusée ({err}), couverture à la place")
            couv = couvertures.get(t["article_id"])
            if not media and not couv:  # pas de couverture d'avance pour un article avec image : faite à la demande
                from couvertures import generer_couvertures
                couv = generer_couvertures([t], dossier_couv.parent, menage=False).get(t["article_id"])
            if not media and couv:
                media = typefully_image(couv, (dossier_couv / couv).read_bytes())
            tweets = json.loads(t["tweets"])
            # une nouvelle part tout de suite (sinon jusqu'à 7 h d'attente la nuit, hors créneaux) ; une opinion attend son créneau
            nouvelle = t["section"] == "actus" or t["mode"] == "info"
            quand = CONFIG.get("typefully_publish_at_actus") if nouvelle else None
            if quand == "now":
                tweets, quand = sans_tweet_de_lien(tweets)
            posts = [{"text": tw} for tw in tweets]
            if media:
                posts[0]["media_ids"] = [media]
            corps = {"draft_title": t["titre"][:500], "platforms": {"x": {"enabled": True, "posts": posts}}}
            if quand or CONFIG.get("typefully_publish_at"):
                corps["publish_at"] = quand or CONFIG["typefully_publish_at"]
            d = typefully_api("drafts", corps)
        except (OSError, KeyError, ValueError) as err:  # réseau, clé refusée... : repris au prochain passage
            # Typefully explique son refus dans le corps de la réponse ; un thread refusé ne bloque plus les suivants
            detail = err.read().decode("utf-8", "replace")[:300] if hasattr(err, "read") else ""
            print(f"  ! Typefully : envoi impossible pour l'article {t['article_id']} ({err}) {detail}, repris au prochain passage")
            continue
        con.execute("UPDATE threads SET typefully = ? WHERE article_id = ?", (str(d["id"]), t["article_id"]))
        con.commit()
        n += 1
    return n


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


if __name__ == "__main__":  # python threads.py : renouvelle le jeton de la Page Facebook (voir LISEZMOI.md)
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
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

"""Threads X : découpe les nouveaux articles du site en threads et les envoie sur Telegram, prêts à copier-coller.

Le texte vient de l'article du site (déjà un résumé commenté), le dernier tweet crédite le journaliste et le
journal avec le lien de la source (X affiche alors la carte de l'article, avec sa photo principale).
Réglages : "telegram_token", "telegram_chat_id" dans secrets.json (ou TELEGRAM_TOKEN, TELEGRAM_CHAT_ID), "max_threads" dans config.json (threads envoyés au plus par passage).
"""
import json
import os
import re
import urllib.parse
import urllib.request
import uuid
from datetime import datetime

from insider import BASE, CONFIG, appeler_claude, extraire_json

LIMITE = 280
SECRETS = BASE / "secrets.json"  # token et chat sur le PC, hors git ; sur GitHub : variables d'environnement
URL = re.compile(r"https?://\S+")

# règles communes : thread écrit avec l'article (generer_site) ou après coup (decouper)
REGLES = """- Tweet 1 : accroche forte qui donne l'idée principale et nomme l'auteur ou le média (ex. : يرى الصحفي ... في «ماركا» أن ...). Ajoute #ريال_مدريد à la fin.
- Tweets suivants : développement fidèle au texte, une idée par tweet, en gardant ses citations «» telles quelles.
- Nombre de tweets : 2 ou 3 pour une information, 4 à 8 pour une opinion, 4 à 10 pour une conférence de presse (une déclaration forte par tweet).
- Chaque tweet fait AU MAXIMUM 240 caractères, espaces compris. Pas de lien, pas de numérotation, pas d'autre hashtag.
- N'ajoute aucun fait ni avis absent du texte."""

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
    """Ajoute le tweet de crédit et la numérotation ; None si un tweet dépasse la limite de X."""
    tweets = [str(t).strip() for t in tweets if str(t).strip()] + [credit(a)]
    n = len(tweets)
    tweets = [f"{t}\n\n{i}/{n}" for i, t in enumerate(tweets, 1)] if n > 1 else tweets
    return tweets if n > 1 and all(longueur(t) <= LIMITE for t in tweets) else None


def connexion_threads(con):
    con.execute("CREATE TABLE IF NOT EXISTS threads (article_id INTEGER PRIMARY KEY, tweets TEXT, statut TEXT, date TEXT)")


def decouper(con, heures=24):
    """Fait écrire par Claude les threads des articles récents qui n'en ont pas encore. Retourne le nombre créé."""
    connexion_threads(con)
    arts = con.execute("SELECT * FROM articles WHERE id NOT IN (SELECT article_id FROM threads)"
                       " AND date >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?) ORDER BY section = 'actus', date DESC LIMIT ?",
                       (f"-{heures} hours", CONFIG.get("max_threads", 10))).fetchall()
    if not arts:
        return 0
    blocs = [f"[id {a['id']}] Section : {a['section']}\nAuteur : {a['auteur_ar'] or a['auteur'] or 'inconnu'}\n"
             f"Média : {a['journal']}\nTitre : {a['titre']}\nTexte :\n{a['texte']}" for a in arts]
    try:
        reponses = extraire_json(appeler_claude(PROMPT.format(regles=REGLES, articles="\n\n".join(blocs)),
                                                CONFIG.get("modele_redaction", "sonnet")))
    except (ValueError, json.JSONDecodeError) as err:
        print(f"  ! threads : réponse illisible ({err}), repris au prochain passage")
        return 0
    par_id = {a["id"]: a for a in arts}
    n = 0
    for r in reponses:
        a = par_id.get(r.get("id")) if isinstance(r, dict) else None
        tweets = assembler(a, r.get("tweets") or []) if a else None
        if tweets:  # sinon (tweet trop long) : réécrit au prochain passage
            con.execute("INSERT OR IGNORE INTO threads VALUES (?,?,?,?)", (a["id"], json.dumps(tweets, ensure_ascii=False),
                        "a_envoyer", datetime.now().isoformat(timespec="seconds")))
            n += 1
    con.commit()
    return n


def telegram(methode, champs, fichier=None):
    """Appelle l'API Bot de Telegram (formulaire multipart si une photo est jointe)."""
    url = f"https://api.telegram.org/bot{reglage('telegram_token')}/{methode}"
    if fichier:
        limite = uuid.uuid4().hex
        corps = b"".join(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                         for k, v in champs.items())
        corps += (f'--{limite}\r\nContent-Disposition: form-data; name="photo"; filename="{fichier.name}"\r\n'
                  f"Content-Type: image/png\r\n\r\n").encode() + fichier.read_bytes() + f"\r\n--{limite}--\r\n".encode()
        req = urllib.request.Request(url, corps, {"Content-Type": f"multipart/form-data; boundary={limite}"})
    else:
        req = urllib.request.Request(url, urllib.parse.urlencode(champs).encode())
    with urllib.request.urlopen(req, timeout=60) as rep:
        return json.load(rep)


def envoyer(con, couvertures, dossier_couv):
    """Envoie sur Telegram les threads pas encore envoyés : en-tête, couverture, puis un message par tweet."""
    connexion_threads(con)
    chat = reglage("telegram_chat_id")
    if not reglage("telegram_token") or not chat:
        print("  ! threads : telegram_token ou telegram_chat_id manquant (secrets.json), envoi reporté")
        return 0
    n = 0
    for t in con.execute("SELECT t.article_id, t.tweets, a.titre FROM threads t JOIN articles a ON a.id = t.article_id"
                         " WHERE t.statut = 'a_envoyer' ORDER BY t.article_id").fetchall():
        tweets = json.loads(t["tweets"])
        try:
            telegram("sendMessage", {"chat_id": chat, "text": f"🧵 ثريد جديد ({len(tweets)} تغريدات)\n{t['titre']}"})
            if t["article_id"] in couvertures:
                telegram("sendPhoto", {"chat_id": chat, "caption": "صورة التغريدة الأولى"},
                         dossier_couv / couvertures[t["article_id"]])
            for tweet in tweets:
                telegram("sendMessage", {"chat_id": chat, "text": tweet})
        except OSError as err:  # réseau coupé, token refusé... : renvoyé au prochain passage
            print(f"  ! Telegram : envoi impossible ({err}), repris au prochain passage")
            break
        con.execute("UPDATE threads SET statut = 'envoye' WHERE article_id = ?", (t["article_id"],))
        con.commit()
        n += 1
    return n

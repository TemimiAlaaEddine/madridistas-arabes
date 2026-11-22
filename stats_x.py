"""Bilan des statistiques X à partir de l'export CSV du tableau de bord (X Premium, gratuit) : chaque post est relié à la base
(liens_x -> brouillon Typefully -> thread -> article) puis classé par type, étiquette, section, journal, heure et format
(thread / tweet long). Rien n'est stocké : la base locale est reconstruite depuis articles.sql à chaque git pull.

    python stats_x.py chemin/vers/export.csv     (sans argument : le CSV le plus récent du dossier Téléchargements)
"""
import csv
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import performance
from commun import DB_PATH, db, restaurer_base

DEBUT_LONG = datetime(2026, 11, 22, 22)  # UTC : premier passage après le passage au tweet long (commit 793af78)
STATUS = re.compile(r"/status/(\d+)")
# noms de colonnes connus (ancien export « tweet activity » et export actuel), en minuscules sans accents
COLONNES = {
    "id": ("post id", "tweet id", "id"),
    "lien": ("post link", "tweet permalink", "permalink", "link"),
    "texte": ("post text", "tweet text", "text"),
    "date": ("date", "time", "created at"),
    "vues": ("impressions",),
    "interactions": ("engagements",),
    "likes": ("likes",),
    "reposts": ("reposts", "retweets"),
    "reponses": ("replies",),
    "signets": ("bookmarks",),
    "abonnements": ("new follows", "follows"),
}


def plat(texte):
    return unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode().strip().lower()


def nombre(v):
    try:
        return float(str(v).replace(",", "").replace(" ", "").strip() or 0)
    except ValueError:
        return 0.0


def date_csv(v):
    """Date en UTC sans fuseau, ou None ; les formats sans heure donnent minuit."""
    v = (v or "").strip()
    for f in ("%a, %b %d, %Y", "%Y-%m-%d %H:%M %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%b %d, %Y"):
        try:
            d = datetime.strptime(v, f)
            break
        except ValueError:
            d = None
    if d is None:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def etiquette(texte):
    """« 🚨 عاجل | ... » -> « 🚨 عاجل » ; les étiquettes à nom (🗣️ مورينيو, 🎙️ مؤتمر ...) sont regroupées."""
    tete = (texte or "").strip().split("\n")[0]
    if "|" not in tete[:40]:
        return "(sans étiquette)"
    tete = tete.split("|")[0].strip()
    for emoji, nom in (("🗣", "🗣️ تصريح"), ("🎙", "🎙️ مؤتمر"), ("⭐", "⭐ أداء")):
        if tete.startswith(emoji):
            return nom
    return tete


def lire_csv(chemin):
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        lignes = list(csv.DictReader(f))
    if not lignes:
        raise ValueError("export vide")
    entetes = {plat(k): k for k in lignes[0]}
    champs = {c: next((entetes[n] for n in noms if n in entetes), None) for c, noms in COLONNES.items()}
    if not champs["vues"] or not (champs["id"] or champs["lien"]):
        raise ValueError(f"colonnes non reconnues : {', '.join(lignes[0])}")
    return [{c: (l.get(k) if k else None) for c, k in champs.items()} for l in lignes]


def posts(chemin, con):
    """Lignes du CSV reliées à la base : [{id, texte, date, vues, interactions, type, etiquette, section, journal, format, tranche}]."""
    par_status = {}
    for typefully, url, date in con.execute("SELECT typefully, url, date FROM liens_x"):
        m = STATUS.search(url or "")
        if m:
            par_status[m[1]] = (typefully, date)
    articles = {str(r["typefully"]): r for r in con.execute(
        "SELECT t.typefully, a.section, a.mode, a.journal FROM threads t JOIN articles a ON a.id = t.article_id WHERE t.typefully IS NOT NULL")}
    autres = {}
    for table, colonne, nom in (("resumes", "typefully", "Résumé du jour"), ("unes", "x", "Une de journal")):
        if con.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone():
            autres.update({str(r[0]): nom for r in con.execute(f"SELECT {colonne} FROM {table} WHERE {colonne} IS NOT NULL")})
    resultat = []
    for l in lire_csv(chemin):
        sid = (l["id"] or "").strip() or (STATUS.search(l["lien"] or "") or [None, ""])[1]
        texte = l["texte"] or ""
        typefully, publie = par_status.get(sid, (None, None))
        date = date_csv(publie) if publie else date_csv(l["date"])
        a = articles.get(str(typefully))
        if "🔗" in texte and "المصدر" in texte:
            genre = "Réponse (lien de la source)"
        elif a:
            genre = "Nouvelle" if a["section"] == "actus" or a["mode"] == "info" else "Opinion"
        elif str(typefully) in autres:
            genre = autres[str(typefully)]
        elif texte.startswith("⭐"):
            genre = "Tweet joueur"
        else:
            genre = "Autre (manuel, /match, /script)"
        vues = nombre(l["vues"])
        inter = nombre(l["interactions"]) if l["interactions"] is not None else sum(
            nombre(l[k]) for k in ("likes", "reposts", "reponses", "signets"))
        resultat.append({"id": sid, "texte": texte, "date": date, "vues": vues, "interactions": inter,
                         "abonnements": nombre(l["abonnements"]), "type": genre, "etiquette": etiquette(texte),
                         "section": a["section"] if a else "—", "journal": a["journal"] if a else "—",
                         "format": "—" if not date else ("Tweet long" if date >= DEBUT_LONG else "Thread"),
                         # l'heure ne vient que de Typefully : l'export de X ne donne souvent que le jour
                         "tranche": performance.tranche(date) if date and publie else "heure inconnue"})
    return resultat


def rapport(ps):
    principaux = [p for p in ps if p["type"] != "Réponse (lien de la source)"]
    if not principaux:
        return "Aucun post dans l'export."
    vues, inter = sum(p["vues"] for p in principaux), sum(p["interactions"] for p in principaux)
    dates = [p["date"] for p in principaux if p["date"]]
    periode = f" du {min(dates):%d/%m} au {max(dates):%d/%m}" if dates else ""
    taux = f" (taux {inter / vues:.1%})" if vues else ""
    lignes = ["## Bilan X", "",
              f"{len(principaux)} posts{periode} : {vues:,.0f} vues, {inter:,.0f} interactions{taux}, "
              f"{sum(p['abonnements'] for p in principaux):,.0f} abonnés gagnés. "
              f"Vues médianes par post : {median(p['vues'] for p in principaux):g}.".replace(",", " "), ""]
    reponses = [p for p in ps if p["type"] == "Réponse (lien de la source)"]
    if reponses:
        lignes += [f"Réponses avec le lien de la source : {len(reponses)}, {sum(p['vues'] for p in reponses):,.0f} vues "
                   "(écartées des classements).".replace(",", " "), ""]
    for cle, titre in (("type", "Type"), ("etiquette", "Étiquette"), ("format", "Format"), ("tranche", "Heure de Madrid"),
                       ("section", "Section"), ("journal", "Journal source")):
        lignes += performance.classement(principaux, cle, titre) + [""]
    lignes.append("**Les 5 posts les plus vus**")
    for p in sorted(principaux, key=lambda p: -p["vues"])[:5]:
        lignes.append(f"- {p['vues']:g} vues, {p['interactions']:g} interactions ({p['type']}) : "
                      f"[{p['texte'].split(chr(10))[0][:90]}](https://x.com/i/status/{p['id']})")
    lignes += ["", f"_Médianes ; pas de conclusion sous {performance.MIN_POSTS} posts par ligne. Les posts qui ne sont pas "
               "dans la base (publiés à la main, ou avant le relevé des adresses du 14 nov.) restent sans section ni heure._"]
    return "\n".join(lignes)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1:
        fichier = Path(sys.argv[1])
    else:
        csvs = sorted((Path.home() / "Downloads").glob("*.csv"), key=lambda f: f.stat().st_mtime)
        if not csvs:
            sys.exit("Aucun CSV dans Téléchargements : python stats_x.py chemin/vers/export.csv")
        fichier = csvs[-1]
    restaurer_base(DB_PATH)  # base à jour après un git pull
    con = db()
    con.row_factory = sqlite3.Row
    print(f"Export lu : {fichier}\n")
    print(rapport(posts(fichier, con)))

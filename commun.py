"""Fonctions communes : collecte RSS, déduplication, base des articles déjà vus, appel à Claude (abonnement,
via Claude Code en mode `claude -p`), copie texte de la base pour git, identité du site (nom, rubriques, pays).
Utilisé par generer_site.py, couvertures.py, threads.py et connaissance.py."""
import calendar
import html
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

try:
    import feedparser
except ImportError:
    sys.exit("Module manquant. Lance : pip install feedparser")

BASE = Path(__file__).resolve().parent
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
DB_PATH = BASE / "articles.db"
DUMP = BASE / "articles.sql"  # copie texte de articles.db, versionnée dans git : un passage n'y ajoute que ses lignes
OUT = BASE / "sortie"
OUT.mkdir(exist_ok=True)
GABARITS = BASE / "gabarits"  # CSS et JS du site et des couvertures

# identité du site, partagée par les pages (generer_site) et les couvertures
NOM_SITE = "المدريديستا علاء"

SECTIONS = {"actus": "أخبار", "tactique": "تحليلات تكتيكية", "mercato": "سوق الانتقالات", "club": "النادي والأعمال", "debats": "نقاشات"}
PAYS = {
    "es": "الصحافة الإسبانية", "gb": "الصحافة الإنجليزية", "fr": "الصحافة الفرنسية", "us": "الصحافة الأمريكية",
    "de": "الصحافة الألمانية", "it": "الصحافة الإيطالية", "pt": "الصحافة البرتغالية", "nl": "الصحافة الهولندية",
    "be": "الصحافة البلجيكية", "br": "الصحافة البرازيلية", "uy": "الصحافة الأوروغويانية", "tr": "الصحافة التركية",
    "ma": "الصحافة المغربية", "ci": "الصحافة الإيفوارية",
}


def e(t):
    return html.escape(t or "")



# ---------- base de données (articles déjà traités) ----------
def db(chemin=DB_PATH):
    con = sqlite3.connect(chemin)
    con.execute("CREATE TABLE IF NOT EXISTS vus (cle TEXT PRIMARY KEY, titre TEXT, date TEXT)")
    return con


def deja_vu(con, cle):
    return con.execute("SELECT 1 FROM vus WHERE cle=?", (cle,)).fetchone() is not None


def marquer_vus(items, chemin=DB_PATH):
    con = db(chemin)
    now = datetime.now().isoformat(timespec="seconds")
    for it in items:
        con.execute("INSERT OR IGNORE INTO vus VALUES (?,?,?)", (it["cle"], it["titre"], now))
    con.commit()
    con.close()


def restaurer_base(chemin, dump=DUMP):
    """Reconstruit la base depuis sa copie texte quand celle-ci est plus récente (sur GitHub, ou après un git pull)."""
    if not dump.exists() or (chemin.exists() and chemin.stat().st_mtime >= dump.stat().st_mtime):
        return False
    tmp = chemin.with_suffix(".tmp")  # la base en place n'est remplacée qu'une fois la copie relue en entier
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(dump.read_text(encoding="utf-8"))
    con.close()
    tmp.replace(chemin)
    return True


def sauvegarder_base(chemin, dump=DUMP):
    """Écrit la copie texte de la base (à faire avant le commit) ; rien si la base n'existe pas, pour ne pas écraser la copie."""
    if not chemin.exists():
        return False
    con = sqlite3.connect(chemin)
    dump.write_text("\n".join(con.iterdump()) + "\n", encoding="utf-8", newline="\n")  # même fichier sous Windows et Linux
    con.close()
    return True


# ---------- collecte ----------
def nettoyer(texte, limite=400):
    texte = re.sub(r"<[^>]+>", " ", texte or "")
    texte = html.unescape(re.sub(r"\s+", " ", texte)).strip()
    return texte[:limite]


def normaliser_titre(t):
    return re.sub(r"[^\w\s]", "", t.lower()).strip()


def lire_sitemap(url):
    """Sitemap Google News (site sans flux RSS, ex. realmadrid.com) -> entrées au format de feedparser."""
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "n": "http://www.google.com/schemas/sitemap-news/0.9"}
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
        racine = ET.fromstring(r.read())
    entrees = []
    for u in racine.findall("s:url", ns):
        date = u.findtext("n:news/n:publication_date", "", ns)
        entrees.append({"title": u.findtext("n:news/n:title", "", ns), "link": u.findtext("s:loc", "", ns),
                        "published_parsed": datetime.fromisoformat(date.replace("Z", "+00:00")).utctimetuple() if date else None})
    return entrees


def lire_wordpress(url):
    """API REST WordPress (site au flux RSS coupé, ex. La Galerna) -> entrées au format de feedparser."""
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
        posts = json.load(r)
    return [{"title": p["title"]["rendered"], "link": p["link"],
             "published_parsed": time.strptime(p["date_gmt"], "%Y-%m-%dT%H:%M:%S"),  # date_gmt : en UTC, comme feedparser
             "summary": p.get("excerpt", {}).get("rendered", ""),
             "content": [{"value": p.get("content", {}).get("rendered", "")}]} for p in posts]


def collecter(chemin=DB_PATH, age_max_heures=24):
    mots = [m.lower() for m in CONFIG["mots_cles"]]
    age_max = age_max_heures * 3600
    con = db(chemin)
    trouves = []
    for flux in CONFIG["flux"]:
        try:
            entrees = (lire_sitemap(flux["url"]) if flux.get("sitemap") else lire_wordpress(flux["url"]) if flux.get("wordpress")
                       else feedparser.parse(flux["url"]).entries)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {flux['nom']} : erreur ({e})")
            continue
        if not entrees:
            print(f"  ! {flux['nom']} : aucun article (flux indisponible ou URL à vérifier)")
            continue
        n = 0
        for e in entrees:
            titre = nettoyer(e.get("title", ""), 300)
            lien = e.get("link", "")
            if not titre or not lien:
                continue
            pub = e.get("published_parsed") or e.get("updated_parsed")
            if pub and time.time() - calendar.timegm(pub) > age_max:  # pub est en UTC
                continue
            resume = nettoyer(e.get("summary", ""))
            if flux.get("filtre_lien"):  # site du club : tout parle du Real, on ne garde que les rubriques voulues
                if not any(f in lien for f in flux["filtre_lien"]):
                    continue
            elif not flux.get("que_le_real") and not any(m in (titre + " " + resume).lower() for m in mots):  # titres imagés
                continue
            cle = lien
            if deja_vu(con, cle):
                continue
            source = (e.get("source") or {}).get("title") or flux["nom"]
            auteur = nettoyer(e.get("author", ""), 80)
            contenu = (e.get("content") or [{}])[0].get("value", "")
            texte_flux = nettoyer(max(e.get("summary", ""), contenu, key=len), 20000)
            trouves.append({"cle": cle, "titre": titre, "resume": resume, "source": source, "lien": lien, "auteur": auteur,
                            "texte_flux": texte_flux, "pays": flux.get("pays"), "autorise": flux.get("autorisation", False),
                            "opinion": flux.get("opinion", False),
                            "publie": datetime.fromtimestamp(calendar.timegm(pub)).isoformat(timespec="seconds") if pub else None})
            n += 1
        print(f"  {flux['nom']} : {n} nouveau(x)")
    con.close()
    return trouves


def dedoublonner(items, seuil=0.72):
    """Retire les titres quasi identiques dans le lot (même info, plusieurs médias)."""
    gardes, retires = [], []
    for it in items:
        nt = normaliser_titre(it["titre"])
        if any(SequenceMatcher(None, nt, normaliser_titre(g["titre"])).ratio() > seuil for g in gardes):
            retires.append(it)  # marqué comme vu, mais pas envoyé à Claude
        else:
            gardes.append(it)
    return gardes, retires


# ---------- Claude ----------
def appeler_claude(prompt, modele=None, effort=None):
    exe = shutil.which("claude")
    if not exe:
        sys.exit("Claude Code introuvable. Installe-le et connecte-toi à ton compte (lance `claude` une fois).")
    # mode allégé : sans outils, plugins, MCP ni réglages, Claude Code n'ajoute ~1 000 tokens au lieu de ~50 000
    cmd = [exe, "-p", "--output-format", "json", "--tools", "", "--strict-mcp-config", "--setting-sources", "",
           "--no-session-persistence", "--system-prompt", "Tu es un rédacteur. Réponds strictement au format demandé."]
    cmd += ["--model", modele] if modele else []
    cmd += ["--effort", effort] if effort else []
    r = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
        timeout=CONFIG.get("delai_claude_secondes", 600),
    )
    if r.returncode != 0:
        sys.exit(f"Erreur Claude (code {r.returncode}) :\n{r.stderr or r.stdout}")
    sortie = json.loads(r.stdout)
    u = sortie.get("usage", {})
    entree = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    print(f"  (Claude {modele or 'défaut'} : {entree} tokens lus, {u.get('output_tokens', 0)} écrits)")
    return sortie.get("result", "")


def extraire_json(texte):
    debut, fin = texte.find("["), texte.rfind("]")
    if debut == -1 or fin == -1:
        raise ValueError("Aucun tableau JSON trouvé dans la réponse de Claude.")
    return json.loads(texte[debut:fin + 1])

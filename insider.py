#!/usr/bin/env python3
"""Insider Real - générateur de brouillons de posts X (Real Madrid, en arabe).

Collecte RSS -> filtre -> déduplication -> rédaction par Claude (abonnement,
via Claude Code en mode `claude -p`) -> page HTML de brouillons à copier/coller.

Usage :
  python insider.py                 # tout automatique (nécessite Claude Code)
  python insider.py --manuel        # prépare un prompt à coller dans Claude
  python insider.py --importer reponse.txt   # lit la réponse collée de Claude
  python insider.py --test          # sans Claude, pour vérifier la collecte
"""
import argparse
import calendar
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

try:
    import feedparser
except ImportError:
    sys.exit("Module manquant. Lance : pip install feedparser")

BASE = Path(__file__).resolve().parent
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
DB_PATH = BASE / "vus.db"
OUT = BASE / "sortie"
OUT.mkdir(exist_ok=True)


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


def collecter(chemin=DB_PATH, age_max_heures=None):
    mots = [m.lower() for m in CONFIG["mots_cles"]]
    age_max = (age_max_heures or CONFIG["age_max_heures"]) * 3600
    con = db(chemin)
    trouves = []
    for flux in CONFIG["flux"]:
        try:
            entrees = lire_sitemap(flux["url"]) if flux.get("sitemap") else feedparser.parse(flux["url"]).entries
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
            elif not any(m in (titre + " " + resume).lower() for m in mots):
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


# ---------- prompt ----------
PROMPT = """Tu es le rédacteur d'un compte X d'actualité Real Madrid destiné à un public arabophone (Moyen-Orient et Afrique du Nord).

Voici une liste d'articles récents. Pour chacun, décide s'il mérite un post, puis rédige-le en {langue}.

RÈGLES DE RÉDACTION
- Commence chaque post par 🚨 (sauf pour une simple analyse ou un résultat).
- Arabe standard moderne, simple et fluide, ton factuel de type « insider ». Pas de dialecte.
- 280 caractères maximum, idéalement 120-240.
- Cite la source en texte à la fin, sans lien (ex. : المصدر: ماركا). Garde les noms de médias connus (L'Équipe, The Athletic, EFE, Marca, AS...).
- Reformule avec tes propres mots : ne copie jamais la phrase d'origine.
- N'invente AUCUN fait. Si l'info est une rumeur ou n'est pas confirmée, utilise une formule de prudence (حسب ما ذكرت، وفقًا لـ، يُقال) et mets "type": "rumeur".
- Si plusieurs articles parlent de la même info, fais un seul post et liste tous leurs ids.
- Ignore (ne mets pas dans la réponse) les articles hors Real Madrid, les clickbait vides, les résultats d'autres clubs, et les infos sans intérêt.
- Garde les noms des joueurs en arabe usuel (مبابي، فينيسيوس، بيلينغهام، كورتوا...).
- Article d'opinion, chronique ou analyse signée (champ « Auteur ») : présente-le comme l'avis du journaliste et nomme-le, translittéré en arabe (ex. : يرى الصحفي خوان إغناسيو غارسيا-أوتشوا في ماركا أن...), avec "type": "analyse". N'attribue jamais cet avis au média ou au club.

FORMAT DE RÉPONSE
Réponds UNIQUEMENT avec un tableau JSON valide, sans texte avant ni après, sans bloc de code :
[{{"ids": [1], "post": "🚨 ...", "type": "info|rumeur|declaration|resultat|analyse"}}]

ARTICLES
{articles}
"""


def construire_prompt(items):
    blocs = []
    for i, it in enumerate(items, 1):
        auteur = f"\nAuteur : {it['auteur']}" if it.get("auteur") else ""
        blocs.append(f"[{i}] Source : {it['source']}{auteur}\nTitre : {it['titre']}\nRésumé : {it['resume']}")
    return PROMPT.format(langue=CONFIG.get("langue_sortie", "arabe"), articles="\n\n".join(blocs))


# ---------- Claude ----------
def appeler_claude(prompt, modele=None, effort=None):
    exe = shutil.which("claude")
    if not exe:
        sys.exit(
            "Claude Code introuvable. Installe-le et connecte-toi à ton compte, "
            "ou utilise le mode manuel : python insider.py --manuel"
        )
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


# ---------- rendu HTML ----------
CSS = """
body{font-family:Segoe UI,Tahoma,sans-serif;background:#f4f5f7;margin:0;padding:24px;color:#111}
h1{font-size:20px;margin:0 0 4px} .sub{color:#666;margin-bottom:20px;font-size:14px}
.card{background:#fff;border-radius:12px;padding:16px;margin-bottom:14px;box-shadow:0 1px 3px #0002}
.card.fait{opacity:.45}
textarea{width:100%;box-sizing:border-box;min-height:110px;font-size:17px;line-height:1.6;
 border:1px solid #d0d4da;border-radius:8px;padding:10px;direction:rtl;text-align:right;font-family:inherit}
.row{display:flex;gap:10px;align-items:center;margin-top:8px;flex-wrap:wrap;font-size:13px;color:#555}
button{background:#1d9bf0;color:#fff;border:0;border-radius:8px;padding:8px 14px;cursor:pointer;font-size:14px}
button.sec{background:#e6e9ee;color:#222}
.tag{background:#eef;border-radius:6px;padding:2px 8px} .tag.rumeur{background:#ffe9c7}
.cnt.over{color:#c00;font-weight:bold} a{color:#1d6fb8}
"""

JS = """
function maj(t){const c=t.closest('.card').querySelector('.cnt');c.textContent=t.value.length+'/280';
 c.classList.toggle('over',t.value.length>280)}
function copier(b){const t=b.closest('.card').querySelector('textarea');navigator.clipboard.writeText(t.value);
 b.textContent='Copié ✓';setTimeout(()=>b.textContent='Copier',1500)}
function fait(b){b.closest('.card').classList.toggle('fait')}
document.querySelectorAll('textarea').forEach(t=>{maj(t);t.addEventListener('input',()=>maj(t))});
"""


def rendre_html(brouillons, items):
    cartes = []
    for b in brouillons:
        ids = [i for i in b.get("ids", []) if isinstance(i, int) and 1 <= i <= len(items)]
        sources = []
        for i in ids:
            it = items[i - 1]
            signe = f' ({it["auteur"]})' if it.get("auteur") else ""
            sources.append(f'<a href="{html.escape(it["lien"])}" target="_blank">{html.escape(it["source"] + signe)}</a>')
        typ = html.escape(b.get("type", "info"))
        cartes.append(
            f'<div class="card"><textarea dir="rtl">{html.escape(b.get("post", ""))}</textarea>'
            f'<div class="row"><span class="tag {typ}">{typ}</span><span class="cnt"></span>'
            f'<span>Vérifier : {" · ".join(sources) or "—"}</span>'
            f'<span style="flex:1"></span><button class="sec" onclick="fait(this)">Fait</button>'
            f'<button onclick="copier(this)">Copier</button></div></div>'
        )
    date = datetime.now().strftime("%d/%m/%Y %H:%M")
    page = (
        f'<!doctype html><html lang="ar"><head><meta charset="utf-8"><title>Brouillons {date}</title>'
        f"<style>{CSS}</style></head><body><h1>Brouillons — {len(cartes)} post(s)</h1>"
        f'<div class="sub">{date} · Relis, corrige, ajoute l\'image, puis publie à la main sur X.</div>'
        f'{"".join(cartes) or "<p>Rien de nouveau.</p>"}<script>{JS}</script></body></html>'
    )
    chemin = OUT / f"brouillons_{datetime.now():%Y%m%d_%H%M}.html"
    chemin.write_text(page, encoding="utf-8")
    return chemin


def ouvrir(chemin):
    print(f"\n✅ Brouillons : {chemin}")
    try:
        os.startfile(chemin)  # Windows
    except AttributeError:
        pass


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manuel", action="store_true", help="écrit le prompt à coller dans Claude")
    ap.add_argument("--importer", metavar="FICHIER", help="réponse de Claude collée dans un fichier")
    ap.add_argument("--test", action="store_true", help="collecte seulement, sans Claude")
    args = ap.parse_args()

    attente = OUT / "en_attente.json"

    if args.importer:
        if not attente.exists():
            sys.exit("Rien en attente. Lance d'abord : python insider.py --manuel")
        lot = json.loads(attente.read_text(encoding="utf-8"))
        texte = Path(args.importer).read_text(encoding="utf-8")
        brouillons = extraire_json(texte)
        marquer_vus(lot["items"] + lot["doublons"])
        attente.unlink()
        ouvrir(rendre_html(brouillons, lot["items"]))
        return

    print("Collecte des flux...")
    items = collecter()
    if not items:
        print("Rien de nouveau.")
        return
    items, doublons = dedoublonner(items)
    reste = items[CONFIG["max_articles_par_lot"]:]  # non traités : seront repris au prochain passage
    items = items[:CONFIG["max_articles_par_lot"]]
    print(f"{len(items)} article(s) à traiter ({len(doublons)} doublon(s) écarté(s), {len(reste)} reporté(s)).")

    if args.test:
        for it in items:
            print(f"- [{it['source']}] {it['titre']}")
        return

    prompt = construire_prompt(items)

    if args.manuel:
        (OUT / "prompt.txt").write_text(prompt, encoding="utf-8")
        attente.write_text(json.dumps({"items": items, "doublons": doublons}, ensure_ascii=False), encoding="utf-8")
        print(f"\n1) Ouvre {OUT / 'prompt.txt'} et colle tout son contenu dans Claude.")
        print("2) Copie la réponse de Claude dans un fichier reponse.txt.")
        print("3) Lance : python insider.py --importer reponse.txt")
        return

    reponse = appeler_claude(prompt)
    try:
        brouillons = extraire_json(reponse)
    except (ValueError, json.JSONDecodeError) as e:
        (OUT / "derniere_reponse.txt").write_text(reponse, encoding="utf-8")
        sys.exit(f"Réponse illisible ({e}). Sauvegardée dans sortie/derniere_reponse.txt")
    marquer_vus(items + doublons)
    ouvrir(rendre_html(brouillons, items))


if __name__ == "__main__":
    main()

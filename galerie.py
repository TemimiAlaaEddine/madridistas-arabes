"""Photos du match : la galerie de la chronique du site du Real Madrid (une cinquantaine de photos le soir même).

Usage : python galerie.py AAAA-MM-JJ matchs/AAAA-MM-JJ-adversaire   (lancé aussi par match.py)
        python galerie.py --google "Arda Güler" [d|w|m]   (photos récentes sur Google Images : planche et liste ; /joueur)
        python galerie.py --image <url> <fichier>         (télécharge l'image choisie)
Le robots.txt de realmadrid.com autorise les pages et les images. Les photos n'ont pas de légende : elles sont gardées dans
<dossier>/photos/NN.jpg, avec des planches numérotées (planche-1.jpg…) pour les regarder d'un coup ; on reconnaît le joueur à son
numéro de maillot (numéros affichés par match.py), jamais à son visage. Les photos des matchs de plus de 7 jours sont effacées
à chaque passage de match.py (nettoyer).
"""
import re
import shutil
import subprocess
import sys
from datetime import date as Date
from io import BytesIO
from pathlib import Path

SITE = "https://www.realmadrid.com"
CRONICAS = SITE + "/es-ES/noticias/futbol/primer-equipo/cronicas"
ACTUALIDAD = (SITE + "/es-ES/noticias/futbol/primer-equipo", SITE + "/es-ES/noticias/futbol/primer-equipo/actualidad")
IMAGE = "https://assets.realmadrid.com/is/image/realmadrid/{}?wid=1200"
NAVIGATEUR = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
PAR_PLANCHE, COLONNES, VIGNETTE = 20, 4, 360


def lire(url):
    r = subprocess.run(["curl", "-s", "-f", "-m", "60", "-A", NAVIGATEUR, url], capture_output=True, check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.stdout


def chronique(jour):
    """Adresse de la chronique du club pour ce match (son adresse finit par la date JJ-MM-AAAA), ou None."""
    page = lire(CRONICAS).decode("utf-8", "replace").replace("\\u002F", "/")
    m = re.search(r"cronica-[a-z0-9-]*-" + Date.fromisoformat(jour).strftime("%d-%m-%Y"), page)
    return f"{CRONICAS}/{m.group(0)}" if m else None


def photos(page):
    """Identifiants des photos de la galerie, dans l'ordre (01_JT30825…), plus la photo principale (nom descriptif)."""
    ids = re.findall(r"assets\.realmadrid\.com/is/image/realmadrid/([A-Za-z0-9_-]+)", page)
    vus = []
    for i in ids:
        if i not in vus and (re.match(r"\d\d_", i) or i.startswith("ND-")):
            vus.append(i)
    return vus


def enregistrer(identifiant, fichier):
    """Télécharge une photo du club en JPEG (sauf si elle est déjà là) ; False si elle est introuvable."""
    from PIL import Image
    if fichier.exists():
        return True
    try:
        with Image.open(BytesIO(lire(IMAGE.format(identifiant)))) as im:
            im.convert("RGB").save(fichier, "JPEG", quality=88)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def etiquette(ids):
    """Début du nom des photos du match chez le club (« ND-LIGA-J13-RM-CELTA »), tiré de la photo principale de la galerie."""
    nd = next((i for i in ids if i.startswith("ND-")), None)
    return "-".join(nd.split("-")[:5]) if nd else None


def mis_en_avant(tag, joueurs, pages=ACTUALIDAD):
    """Joueurs que le club met en avant le soir du match : {nom: [photos]}, d'après le nom des photos de ses articles
    (« ND-LIGA-J13-RM-CELTA-ALEGRIA-BELLINGHAM-VINICIUS-02_AV17181 »). joueurs : {nom: mots qui le désignent, en majuscules}."""
    noms = set()
    for u in pages:
        noms |= set(re.findall(r"assets\.realmadrid\.com/is/image/realmadrid/(ND-[A-Za-z0-9_-]+)",
                               lire(u).decode("utf-8", "replace").replace("\\u002F", "/")))
    out = {}
    for n in sorted(noms):
        if tag and n.startswith(tag + "-"):
            mots = set(re.split(r"[-_]", n[len(tag) + 1:]))
            for j, cles in joueurs.items():
                if mots & cles:
                    out.setdefault(j, []).append(n)
    return out


def telecharger(jour, dossier):
    """Télécharge la galerie et fait les planches ; renvoie [(fichier, identifiant)] ou [] s'il n'y a pas de chronique."""
    from PIL import Image, ImageDraw, ImageFont
    url = chronique(jour)
    if not url:
        return []
    ids = photos(lire(url).decode("utf-8", "replace"))
    sortie = Path(dossier) / "photos"
    sortie.mkdir(parents=True, exist_ok=True)
    faits = []
    for n, i in enumerate(ids, 1):
        f = sortie / f"{n:02d}.jpg"
        if enregistrer(i, f):
            faits.append((f, i))
    police = ImageFont.load_default(size=40)
    for p in range(0, len(faits), PAR_PLANCHE):
        lot = faits[p:p + PAR_PLANCHE]
        h = VIGNETTE * 9 // 16
        planche = Image.new("RGB", (COLONNES * VIGNETTE, -(-len(lot) // COLONNES) * h), "black")
        for k, (f, _) in enumerate(lot):
            with Image.open(f) as im:
                im.thumbnail((VIGNETTE, h))
                x, y = k % COLONNES * VIGNETTE, k // COLONNES * h
                planche.paste(im, (x, y))
            ImageDraw.Draw(planche).text((x + 8, y + 4), f.stem, fill="yellow", font=police, stroke_width=3, stroke_fill="black")
        planche.save(sortie / f"planche-{p // PAR_PLANCHE + 1}.jpg", "JPEG", quality=80)
    return faits


def google_images(nom, dossier, periode="w", n=24):
    """Photos récentes d'un joueur sur Google Images (une requête Bright Data, filtre de date : d jour, w semaine, m mois) :
    planche numérotée des n premières vignettes dans <dossier>/planche-google.jpg et [(numéro, image d'origine, page source)].
    Le joueur se reconnaît au texte de la page source (son nom), jamais à son visage."""
    import base64
    import json
    import urllib.parse
    from PIL import Image, ImageDraw, ImageFont
    from match import bright_data  # ici : match importe galerie
    q = urllib.parse.quote(f"{nom} Real Madrid")
    d = json.loads(bright_data(f"https://www.google.com/search?q={q}&tbm=isch&tbs=qdr:{periode}&hl=es&brd_json=1"))
    sortie = Path(dossier)
    sortie.mkdir(parents=True, exist_ok=True)
    trouves, vignettes = [], []
    for x in d.get("images") or []:
        vignette = x.get("image") or ""
        if not (x.get("original_image") and vignette.startswith("data:image")):
            continue
        try:
            im = Image.open(BytesIO(base64.b64decode(vignette.split(",", 1)[1]))).convert("RGB")
        except (ValueError, OSError):
            continue
        trouves.append((len(trouves) + 1, x["original_image"], x.get("source") or x.get("title") or ""))
        vignettes.append(im)
        if len(trouves) >= n:
            break
    if vignettes:
        police, case = ImageFont.load_default(size=28), 300
        planche = Image.new("RGB", (6 * case, -(-len(vignettes) // 6) * case), "black")
        for k, im in enumerate(vignettes):
            im.thumbnail((case, case))
            x, y = k % 6 * case, k // 6 * case
            planche.paste(im, (x, y))
            ImageDraw.Draw(planche).text((x + 6, y + 4), str(k + 1), fill="yellow", font=police, stroke_width=3, stroke_fill="black")
        planche.save(sortie / "planche-google.jpg", "JPEG", quality=85)
    return trouves


def telecharger_image(url, fichier):
    """Télécharge l'image d'origine choisie (JPEG) ; False si le site la refuse."""
    from PIL import Image
    try:
        with Image.open(BytesIO(lire(url))) as im:
            im.convert("RGB").save(fichier, "JPEG", quality=90)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def nettoyer(matchs, aujourdhui, jours=7):
    """Efface les photos des matchs de plus de `jours` jours (date en tête du dossier) : elles ne servent qu'aux tweets du
    lendemain ; les pages WhoScored et FotMob restent (repères par poste). Renvoie les dossiers nettoyés."""
    faits = []
    for p in sorted(Path(matchs).glob("*/photos")):
        try:
            age = (aujourdhui - Date.fromisoformat(p.parent.name[:10])).days
        except ValueError:
            continue  # dossier sans date : on n'y touche pas
        if age > jours:
            shutil.rmtree(p)
            faits.append(p.parent.name)
    return faits


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) >= 3 and sys.argv[1] == "--google":  # python galerie.py --google "Arda Güler" [d|w|m]
        dossier = Path(__file__).parent / "matchs" / "_joueurs" / sys.argv[2].lower().replace(" ", "-")
        for num, url, source in google_images(sys.argv[2], dossier, sys.argv[3] if len(sys.argv) > 3 else "w"):
            print(f"{num:>2}. {source[:110]} | {url}")
        print(f"planche : {(dossier / 'planche-google.jpg').relative_to(Path(__file__).parent).as_posix()}")
        sys.exit()
    if len(sys.argv) == 4 and sys.argv[1] == "--image":  # python galerie.py --image <url> <fichier>
        sys.exit(0 if telecharger_image(sys.argv[2], Path(sys.argv[3])) else "image refusée par le site : prends la suivante")
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    f = telecharger(*sys.argv[1:])
    print(f"{len(f)} photos dans {Path(sys.argv[2]) / 'photos'}" if f else "pas de chronique du club pour cette date")

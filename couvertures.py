"""Couvertures 1200×630 des articles (aussi l'image de partage sur X, Facebook, WhatsApp) : gabarit HTML par rubrique,
rendu en PNG par Edge sans fenêtre. Gabarit CSS dans gabarits/couverture.css."""
import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.parse

from PIL import Image

from commun import BASE, GABARITS, NOM_SITE, PAYS, SECTIONS, e

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
COUV_CSS = (GABARITS / "couverture.css").read_text(encoding="utf-8")


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


def vignette(nom):
    """Version légère d'une couverture pour les cartes : WebP 720 px, ~17 Ko au lieu de ~85 Ko pour le PNG."""
    return nom.removesuffix(".png") + "-v.webp"


def generer_couvertures(arts, dossier):
    """Rend chaque couverture en PNG avec Edge sans fenêtre (+ sa vignette) ; refaite seulement si son contenu change."""
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
            if not (sortie / vignette(nom)).exists():
                with Image.open(sortie / nom) as im:
                    im.resize((720, round(im.height * 720 / im.width)), Image.LANCZOS).save(sortie / vignette(nom), "WEBP", quality=80, method=6)
    gardes = set(noms.values()) | {vignette(n) for n in noms.values()}
    for ancienne in sortie.glob("a-*"):  # couvertures et vignettes d'articles supprimés ou modifiés
        if ancienne.name not in gardes:
            ancienne.unlink()
    return noms

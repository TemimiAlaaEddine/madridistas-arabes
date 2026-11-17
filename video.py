"""Vidéos verticales 1080×1920 (TikTok, YouTube Shorts, Reels, X), en scènes rythmées, à partir d'un storyboard JSON écrit par
la commande /video. Sans voix ; muette par défaut (son ajouté à la publication) ou avec une musique libre de droits fournie.

    python video.py videos/<sujet>/storyboard.json                    -> videos/<sujet>/<sujet>.mp4 et couverture.png
    python video.py videos/<sujet>/storyboard.json --apercu 2          -> apercu-02.png (scène 2 aux trois quarts)
    python video.py videos/<sujet>/storyboard.json --apercu 2 --zones  -> idem, zones masquées par TikTok et Shorts en rouge
    python video.py videos/<sujet>/storyboard.json --musique son.mp3

Storyboard : {"langue": "ar|fr|en|es", "photo": {"article": 437} | {"url": "..."} | null, "source": "ماركا",
"compte": "@ElMadridistAlaa", "boucle": true, "scenes": [...]}. Chaque scène a un "style", une "duree" facultative
(sinon calculée) et "fond": "photo" pour la photo de l'article en fond (assombrie) au lieu du fond uni.
  cinetique : "texte" (mots entre *étoiles* en or), "etiquette" facultative. Accroche et chute.
  compteur  : "valeur" (ex. "1,06"), "unite", "texte", "max" facultatif (anneau rempli à valeur/max).
  barres    : "titre", "elements": [{"label", "valeur"}] (2 à 5), la plus grande en or.
  duel      : "joueurs": [A, B], "criteres": [{"label", "a", "b"}] (2 à 4).
  tactique  : "texte", "joueurs": [{"nom", "x", "y", "camp": "real|adverse"}], "fleches": [{"de": [x, y], "a": [x, y],
              "type": "course|passe"}], "zones": [{"x", "y", "l", "h"}] ; x de 0 (gauche) à 1, y de 0 (but du Real, en bas)
              à 1 ; chaque élément peut fixer son "t" d'apparition en secondes.
  titres    : "cartes": [{"journal", "titre"}] (1 à 3) : gros titres de presse traduits.
  presse    : "citations": [{"journal", "texte"}] (2 à 4) : « ce que dit la presse ».
Les émojis ne s'affichent pas (police sans émojis) : ils vont dans la légende.
"""
import argparse
import glob
import io
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import arabic_reshaper
from bidi import get_display
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from commun import DB_PATH, restaurer_base

W, H, FPS = 1080, 1920, 30
# zone sûre : hors des parties masquées par TikTok et Shorts (haut, bas avec légende et boutons, colonne de droite).
# shortcut: positions estimées d'après les interfaces connues, à revérifier sur téléphone si une plateforme change la sienne
HAUT, BAS, GAUCHE, DROITE = 250, 1420, 70, 930
CX = (GAUCHE + DROITE) // 2
NAVY, NAVY2, OR, BLANC, DOUX, ROUGE = (9, 24, 46), (3, 10, 22), (254, 190, 16), (255, 255, 255), (178, 192, 214), (230, 57, 70)
PELOUSE, TONTE, LIGNE = (16, 58, 44), (20, 67, 51), (112, 150, 134)
JOURNAUX = {"marca": (213, 0, 28), "as": (226, 0, 26), "mundo deportivo": (12, 77, 162), "sport": (200, 16, 46),
            "el país": (20, 20, 20), "l'équipe": (230, 175, 0), "relevo": (255, 79, 0)}
_bin = glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg-*\bin"))
FFMPEG = os.path.join(_bin[0], "ffmpeg.exe") if _bin else "ffmpeg"
ARABE, NOIR, NORMAL = r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\seguibl.ttf", r"C:\Windows\Fonts\segoeui.ttf"
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]")
MIROIR = str.maketrans("()«»", ")(»«")
_polices, _mots = {}, {}


# ---------- outils ----------
def borne(t):
    return max(0.0, min(1.0, t))


def sortie_douce(t):
    return 1 - (1 - borne(t)) ** 3


def rebond(t):  # dépasse un peu puis revient : effet « pop »
    t = borne(t) - 1
    return 1 + 2.70158 * t ** 3 + 1.70158 * t ** 2


def avance(tl, debut, duree):
    return borne((tl - debut) / duree) if duree else float(tl >= debut)


def police(taille, fichier=ARABE):
    taille = max(8, round(taille))
    if (taille, fichier) not in _polices:
        _polices[(taille, fichier)] = ImageFont.truetype(fichier, taille)
    return _polices[(taille, fichier)]


def visuel(s, langue):
    """Texte prêt à dessiner : sans émojis ; en arabe, lettres reliées et ordre droite-à-gauche (Pillow sans raqm)."""
    s = EMOJI.sub("", str(s)).strip()
    if langue != "ar":
        return s
    s = re.sub(r"\d+(?:[-/:.,]\d+)+", lambda m: f"\u2066{m.group()}\u2069", s)  # « 4-2-3-1 », « 1,06 » : pas inversés
    return get_display(arabic_reshaper.reshape(s)).replace("\u2066", "").replace("\u2069", "").translate(MIROIR)


def latin(s):
    return not re.search(r"[\u0600-\u06FF]", s)


def image_mot(mot, taille, couleur, langue, fichier=None):
    """Un mot dessiné seul (RGBA), mis en cache : la typographie cinétique anime chaque mot séparément."""
    fichier = fichier or (NOIR if latin(mot) and langue != "ar" else ARABE)
    cle = (mot, round(taille), couleur, langue, fichier)
    if cle not in _mots:
        f, v = police(taille, fichier), visuel(mot, langue)
        g, h_, d, b = f.getbbox(v)
        img = Image.new("RGBA", (max(1, d - g + 8), round(taille * 1.45)), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((4 - g, round(taille * 0.12)), v, font=f, fill=couleur + (255,))
        _mots[cle] = img
    return _mots[cle]


def coller(c, img, x, y, alpha=1.0, echelle=1.0):
    """Colle une image centrée sur (x, y), avec transparence et échelle."""
    if alpha <= 0.01:
        return
    if abs(echelle - 1) > 0.01:
        img = img.resize((max(1, round(img.width * echelle)), max(1, round(img.height * echelle))), Image.BILINEAR)
    if alpha < 0.99:
        img = img.copy()
        img.putalpha(img.getchannel("A").point(lambda v, a=alpha: round(v * a)))
    c.alpha_composite(img, (round(x - img.width / 2), round(y - img.height / 2)))


def lignes_mots(texte, taille, langue, largeur=DROITE - GAUCHE):
    """Mots répartis en lignes (ordre logique) ; un mot entre *étoiles* est marqué pour l'or."""
    mots, dedans = [], False
    for m in EMOJI.sub("", texte).split():
        if m.replace("*", ""):
            mots.append((m.replace("*", ""), dedans or "*" in m))
        dedans ^= m.count("*") % 2 == 1  # une étoile ouvre ou ferme le groupe en or
    espace, lignes, cur, l = taille * 0.32, [], [], 0
    for mot, fort in mots:
        w = image_mot(mot, taille, BLANC, langue).width
        if cur and l + espace + w > largeur:
            lignes.append(cur)
            cur, l = [], 0
        cur.append((mot, fort, w))
        l += (espace if l else 0) + w
    return lignes + ([cur] if cur else []), espace


def cinetique(c, texte, taille, langue, y, tl, debut=0.0, pas=0.12, couleur=BLANC, cx=CX, largeur=DROITE - GAUCHE, centre=False):
    """Typographie cinétique : chaque mot arrive l'un après l'autre (pop et montée), centré ; retourne le y sous le bloc."""
    lignes, espace = lignes_mots(texte, taille, langue, largeur)
    while len(lignes) > 6 and taille > 40:  # trop long : on réduit
        taille *= 0.9
        lignes, espace = lignes_mots(texte, taille, langue, largeur)
    hl = taille * 1.25
    if centre:
        y -= len(lignes) * hl / 2
    k = 0
    for i, ligne in enumerate(lignes):
        total = sum(w for _, _, w in ligne) + espace * (len(ligne) - 1)
        x = cx + total / 2 if langue == "ar" else cx - total / 2  # l'arabe se pose de droite à gauche
        for mot, fort, w in ligne:
            p = avance(tl, debut + k * pas, 0.28)
            centre_x = x - w / 2 if langue == "ar" else x + w / 2
            coller(c, image_mot(mot, taille, OR if fort else couleur, langue), centre_x, y + i * hl + hl / 2 + 34 * (1 - sortie_douce(p)),
                   alpha=borne(p * 2), echelle=0.55 + 0.45 * rebond(p))
            x += -(w + espace) if langue == "ar" else w + espace
            k += 1
    return y + len(lignes) * hl


def translucide(c, dessin):
    """Dessine avec transparence par-dessus c : ImageDraw seul remplacerait les pixels au lieu de les mélanger."""
    calque = Image.new("RGBA", c.size, (0, 0, 0, 0))
    dessin(ImageDraw.Draw(calque))
    c.alpha_composite(calque)


def pastille(c, texte, langue, x, y, fond=OR, couleur=NAVY, taille=40, alpha=1.0):
    mot = image_mot(texte, taille, couleur, langue)
    calque = Image.new("RGBA", (mot.width + 56, mot.height + 6), (0, 0, 0, 0))
    ImageDraw.Draw(calque).rounded_rectangle([0, 0, calque.width - 1, calque.height - 1], 22, fill=fond + (255,))
    calque.alpha_composite(mot, (28, 3))
    coller(c, calque, x, y, alpha)
    return calque.width


def nombre(valeur):
    """« 1,06 » -> (1.06, 2 décimales, séparateur « , »)."""
    s = str(valeur).strip()
    sep = "," if "," in s else "."
    dec = len(s.split(sep)[1]) if sep in s else 0
    return float(s.replace(",", ".")), dec, sep


def ecrire_nombre(v, dec, sep):
    return f"{v:.{dec}f}".replace(".", sep)


# ---------- fonds ----------
def fond_uni():
    """Dégradé bleu nuit, avec de fines diagonales très discrètes."""
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(NAVY, NAVY2)))
    trame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dt = ImageDraw.Draw(trame)
    for x in range(-H, W, 90):
        dt.line([(x, 0), (x + H, H)], fill=(255, 255, 255, 10), width=2)
    return Image.alpha_composite(img.convert("RGBA"), trame).convert("RGB")


def fond_photo(photo):
    echelle = max(W * 1.1 / photo.width, H * 1.1 / photo.height)
    photo = photo.resize((round(photo.width * echelle), round(photo.height * echelle)), Image.LANCZOS)
    x, y = (photo.width - W) // 2, (photo.height - H) // 2
    photo = photo.crop((x, y, x + W, y + H)).filter(ImageFilter.GaussianBlur(4))
    return Image.blend(ImageEnhance.Brightness(photo).enhance(0.38), fond_uni(), 0.25)


def photo_article(sb):
    p = sb.get("photo") or {}
    url = p.get("url")
    if p.get("article"):
        restaurer_base(DB_PATH)
        ligne = sqlite3.connect(DB_PATH).execute("SELECT image FROM articles WHERE id = ?", (p["article"],)).fetchone()
        url = ligne[0] if ligne else None
    if not url:
        return None
    import threads
    try:
        return Image.open(io.BytesIO(threads.telecharger_image(url, "video")[1])).convert("RGB")
    except (OSError, ValueError) as err:
        print(f"  ! photo illisible ({err}) : fond uni à la place")
        return None


# ---------- styles ----------
def s_cinetique(c, sc, tl, dur, langue):
    y = HAUT + (BAS - HAUT) * 0.45
    if sc.get("etiquette"):
        lignes, _ = lignes_mots(sc.get("texte", ""), sc.get("taille", 104), langue)
        haut_bloc = y - len(lignes) * sc.get("taille", 104) * 1.25 / 2
        p = avance(tl, 0, 0.3)
        pastille(c, sc["etiquette"], langue, CX + (1 - sortie_douce(p)) * (200 if langue == "ar" else -200), haut_bloc - 70, alpha=p)
    n = len(sc.get("texte", "").split())
    cinetique(c, sc.get("texte", ""), sc.get("taille", 104), langue, y, tl, 0.15, min(0.16, dur * 0.45 / max(n, 1)), centre=True)


def s_compteur(c, sc, tl, dur, langue):
    v, dec, sep = nombre(sc.get("valeur", 0))
    p = sortie_douce(avance(tl, 0.1, min(1.4, dur * 0.5)))
    y = HAUT + (BAS - HAUT) * 0.38
    if sc.get("max"):  # anneau qui se remplit
        d = ImageDraw.Draw(c)
        r = 300
        d.arc([CX - r, y - r, CX + r, y + r], 0, 360, fill=(255, 255, 255, 40), width=26)
        d.arc([CX - r, y - r, CX + r, y + r], -90, -90 + 360 * p * v / float(sc["max"]), fill=OR + (255,), width=26)
    texte = ecrire_nombre(v * p, dec, sep)
    f = police(250 if len(texte) <= 4 else 190, NOIR)
    img = image_mot(texte, f.size, OR, "fr", NOIR)
    coller(c, img, CX, y - 10, echelle=0.8 + 0.2 * rebond(avance(tl, 0, 0.35)))
    if sc.get("unite"):
        coller(c, image_mot(sc["unite"], 64, BLANC, langue), CX, y + f.size * 0.62, alpha=avance(tl, 0.6, 0.3))
    cinetique(c, sc.get("texte", ""), 66, langue, y + 400 if sc.get("max") else y + 260, tl, 0.9, 0.09)


def s_barres(c, sc, tl, dur, langue):
    n = len(sc.get("elements", [])[:5])
    y = HAUT + max(40, (BAS - HAUT - (140 if sc.get("titre") else 0) - n * 175) / 2)
    if sc.get("titre"):
        y = cinetique(c, sc["titre"], 70, langue, y, tl, 0, 0.08) + 60
    els = sc.get("elements", [])[:5]
    vals = [nombre(e.get("valeur", 0)) for e in els]
    vmax = max((v for v, _, _ in vals), default=1) or 1
    d = ImageDraw.Draw(c)
    largeur = DROITE - GAUCHE - 40
    for k, (e, (v, dec, sep)) in enumerate(zip(els, vals)):
        p = sortie_douce(avance(tl, 0.5 + 0.35 * k, 0.8))
        if p <= 0:
            continue
        haut = y + k * 175
        a = borne(p * 3)
        etiquette = image_mot(str(e.get("label", "")), 48, DOUX, langue)
        x_label = DROITE - etiquette.width / 2 if langue == "ar" else GAUCHE + etiquette.width / 2
        coller(c, etiquette, x_label, haut + 20, alpha=a)
        l = max(12, largeur * (v / vmax) * p)
        couleur = OR if v == vmax else (90, 140, 220)
        x0, x1 = (DROITE - l, DROITE) if langue == "ar" else (GAUCHE, GAUCHE + l)
        d.rounded_rectangle([x0, haut + 62, x1, haut + 132], 18, fill=couleur + (round(255 * a),))
        val = image_mot(ecrire_nombre(v * p, dec, sep), 54, NAVY if v == vmax else BLANC, "fr", NOIR)
        if l > val.width + 30:
            coller(c, val, x0 + val.width / 2 + 18 if langue == "ar" else x1 - val.width / 2 - 18, haut + 97, alpha=a)


def s_duel(c, sc, tl, dur, langue):
    a_nom, b_nom = (sc.get("joueurs") or ["A", "B"])[:2]
    gauche, droite = (b_nom, a_nom) if langue == "ar" else (a_nom, b_nom)  # A du côté où l'on commence à lire
    p0 = sortie_douce(avance(tl, 0, 0.4))
    y = HAUT + max(80, (BAS - HAUT - 150 - 250 * len(sc.get("criteres", [])[:4])) / 2)
    coller(c, image_mot(gauche, 62, BLANC, langue), GAUCHE + 200 - 120 * (1 - p0), y, alpha=p0)
    coller(c, image_mot(droite, 62, BLANC, langue), DROITE - 200 + 120 * (1 - p0), y, alpha=p0)
    coller(c, image_mot("VS", 54, OR, "fr", NOIR), CX, y, alpha=p0, echelle=0.6 + 0.4 * rebond(avance(tl, 0.2, 0.3)))
    d = ImageDraw.Draw(c)
    demi = (DROITE - GAUCHE) / 2 - 30
    for k, cr in enumerate(sc.get("criteres", [])[:4]):
        p = sortie_douce(avance(tl, 0.6 + 0.45 * k, 0.8))
        if p <= 0:
            continue
        hy = y + 150 + k * 250
        coller(c, image_mot(str(cr.get("label", "")), 46, DOUX, langue), CX, hy, alpha=borne(p * 3))
        (va, da, sa), (vb, db, sb_) = nombre(cr.get("a", 0)), nombre(cr.get("b", 0))
        vg, vd = (vb, va) if langue == "ar" else (va, vb)
        dg, dd = (db, da) if langue == "ar" else (da, db)
        sg, sd = (sb_, sa) if langue == "ar" else (sa, sb_)
        m = max(vg, vd) or 1
        for cote, v, dec, sep in ((-1, vg, dg, sg), (1, vd, dd, sd)):
            l = max(10, demi * v / m * p)
            couleur = OR if v == m and vg != vd else (90, 140, 220)
            x0, x1 = (CX - 15 - l, CX - 15) if cote < 0 else (CX + 15, CX + 15 + l)
            d.rounded_rectangle([x0, hy + 45, x1, hy + 115], 16, fill=couleur + (255,))
            val = image_mot(ecrire_nombre(v * p, dec, sep), 50, NAVY if couleur == OR else BLANC, "fr", NOIR)
            if l > val.width + 24:
                coller(c, val, x0 + val.width / 2 + 14 if cote < 0 else x1 - val.width / 2 - 14, hy + 80)


def terrain(c, x0, y0, x1, y1):
    d = ImageDraw.Draw(c)
    d.rounded_rectangle([x0 - 20, y0 - 20, x1 + 20, y1 + 20], 30, fill=PELOUSE + (235,))
    for k in range(8):  # bandes de tonte
        if k % 2:
            yb = y0 + (y1 - y0) * k / 8
            d.rectangle([x0, yb, x1, yb + (y1 - y0) / 8], fill=TONTE + (235,))
    w, h = x1 - x0, y1 - y0
    d.rectangle([x0, y0, x1, y1], outline=LIGNE, width=4)
    d.line([x0, y0 + h / 2, x1, y0 + h / 2], fill=LIGNE, width=4)
    r = w * 0.14
    d.ellipse([x0 + w / 2 - r, y0 + h / 2 - r, x0 + w / 2 + r, y0 + h / 2 + r], outline=LIGNE, width=4)
    for yb, sens in ((y0, 1), (y1, -1)):  # surfaces
        d.rectangle([x0 + w * 0.2, min(yb, yb + sens * h * 0.16), x0 + w * 0.8, max(yb, yb + sens * h * 0.16)], outline=LIGNE, width=4)
        d.rectangle([x0 + w * 0.37, min(yb, yb + sens * h * 0.06), x0 + w * 0.63, max(yb, yb + sens * h * 0.06)], outline=LIGNE, width=4)


def s_tactique(c, sc, tl, dur, langue):
    x0, x1, y0, y1 = 210, 790, 470, 1310
    if sc.get("texte"):
        cinetique(c, sc["texte"], 54, langue, HAUT + 5, tl, 0, 0.06)
    p = sortie_douce(avance(tl, 0, 0.35))
    calque = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    terrain(calque, x0, y0, x1, y1)
    coller(c, calque, W / 2, H / 2 + 60 * (1 - p), alpha=p)

    def pt(x, y):
        return x0 + (x1 - x0) * float(x), y1 - (y1 - y0) * float(y)

    d = ImageDraw.Draw(c)
    zones, fleches, joueurs = sc.get("zones", []), sc.get("fleches", []), sc.get("joueurs", [])
    debut = 0.5 + 0.05 * len(joueurs)
    for k, z in enumerate(zones):  # zones : surlignées, avec une légère pulsation
        pz = avance(tl, z.get("t", debut + 0.3 * k), 0.4)
        if pz > 0:
            (ax, ay), (bx, by) = pt(z["x"], z["y"] + z["h"]), pt(z["x"] + z["l"], z["y"])
            a = round((70 + 30 * math.sin(tl * 5)) * pz)
            translucide(c, lambda dd: dd.rounded_rectangle([ax, ay, bx, by], 18, fill=OR + (a,), outline=OR + (round(200 * pz),), width=4))
    for k, f in enumerate(fleches):  # flèches : tracées progressivement
        pf = sortie_douce(avance(tl, f.get("t", debut + 0.4 + 0.65 * k), 0.55))
        if pf <= 0:
            continue
        (ax, ay), (bx, by) = pt(*f["de"]), pt(*f["a"])
        course = f.get("type", "course") == "course"
        mx, my = (ax + bx) / 2 + (by - ay) * (0.18 if course else 0), (ay + by) / 2 - (bx - ax) * (0.18 if course else 0)
        pts = [((1 - s) ** 2 * ax + 2 * (1 - s) * s * mx + s * s * bx, (1 - s) ** 2 * ay + 2 * (1 - s) * s * my + s * s * by)
               for s in [i / 40 * pf for i in range(41)]]
        couleur = OR if course else BLANC
        if course:
            d.line(pts, fill=couleur + (255,), width=9, joint="curve")
        else:
            for i in range(0, len(pts) - 1, 2):  # pointillés
                d.line([pts[i], pts[i + 1]], fill=couleur + (255,), width=7)
        (px, py), (qx, qy) = pts[-2], pts[-1]
        ang = math.atan2(qy - py, qx - px)
        d.polygon([(qx + 26 * math.cos(ang), qy + 26 * math.sin(ang)), (qx + 18 * math.cos(ang + 2.4), qy + 18 * math.sin(ang + 2.4)),
                   (qx + 18 * math.cos(ang - 2.4), qy + 18 * math.sin(ang - 2.4))], fill=couleur + (255,))
    for k, j in enumerate(joueurs):  # joueurs : apparaissent en cascade
        pj = avance(tl, j.get("t", 0.3 + 0.05 * k), 0.3)
        if pj <= 0:
            continue
        x, y = pt(j["x"], j["y"])
        r = 27 * (0.4 + 0.6 * rebond(pj))
        real = j.get("camp", "real") == "real"
        d.ellipse([x - r, y - r, x + r, y + r], fill=(BLANC if real else ROUGE) + (255,), outline=OR + (255,) if j.get("cle") else None, width=6)
        if j.get("nom"):
            coller(c, image_mot(j["nom"], 28, BLANC, langue), x, y + 48, alpha=pj)


def carte_journal(journal, titre, langue):
    """Carte « une de journal » : bandeau au nom du journal, gros titre traduit."""
    couleur = JOURNAUX.get(journal.lower(), (30, 60, 110))
    lignes, espace = lignes_mots(titre, 58, langue, 690)
    img = Image.new("RGBA", (800, 175 + len(lignes) * 78), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], 26, fill=(247, 247, 244, 255))
    d.rounded_rectangle([0, 0, img.width - 1, 120], 26, fill=couleur + (255,))
    d.rectangle([0, 90, img.width - 1, 120], fill=couleur + (255,))
    nom = image_mot(journal.upper(), 70, BLANC, "fr", NOIR)
    img.alpha_composite(nom, ((img.width - nom.width) // 2, 60 - nom.height // 2))
    y = 150
    for ligne in lignes:
        total = sum(w for _, _, w in ligne) + espace * (len(ligne) - 1)
        x = (img.width + total) / 2 if langue == "ar" else (img.width - total) / 2
        for mot, fort, w in ligne:
            m = image_mot(mot, 58, (15, 15, 15) if not fort else couleur, langue)
            img.alpha_composite(m, (round(x - w if langue == "ar" else x), y))
            x += -(w + espace) if langue == "ar" else w + espace
        y += 78
    return img


def s_titres(c, sc, tl, dur, langue):
    cartes = sc.get("cartes", [])[:3]
    hauteurs = [carte_journal(k.get("journal", ""), k.get("titre", ""), langue) for k in cartes]
    total = sum(i.height for i in hauteurs) + 40 * (len(hauteurs) - 1)
    y = HAUT + max(0, (BAS - HAUT - total) / 2)
    for k, img in enumerate(hauteurs):
        p = avance(tl, 0.15 + 0.6 * k, 0.5)
        if p <= 0:
            continue
        angle = (-3, 2.5, -1.5)[k] * (1 + 2 * (1 - sortie_douce(p)))
        tourne = img.rotate(angle, resample=Image.BICUBIC, expand=True)
        coller(c, tourne, CX, y + img.height / 2 - 260 * (1 - rebond(p)), alpha=borne(p * 2.5))
        y += img.height + 40


def s_presse(c, sc, tl, dur, langue):
    cits = sc.get("citations", [])[:4]
    if not cits:
        return
    part = dur / len(cits)
    k = min(len(cits) - 1, int(tl / part))
    t = tl - k * part
    cit = cits[k]
    y = HAUT + (BAS - HAUT) * 0.3
    p = sortie_douce(avance(t, 0, 0.25))
    couleur = JOURNAUX.get(str(cit.get("journal", "")).lower(), (30, 60, 110))
    pastille(c, str(cit.get("journal", "")).upper(), "fr", CX + (1 - p) * 300 * (1 if k % 2 else -1), y, fond=couleur, couleur=BLANC, taille=48, alpha=p)
    coller(c, image_mot("«", 200, OR, "fr", NOIR), CX, y + 170, alpha=p * 0.9)
    cinetique(c, cit.get("texte", ""), 72, langue, y + 300, t, 0.15, 0.07)
    d = ImageDraw.Draw(c)
    for i in range(len(cits)):  # repères : citation en cours
        xx = CX + (i - (len(cits) - 1) / 2) * 44
        d.ellipse([xx - 9, BAS - 120, xx + 9, BAS - 102], fill=(OR if i == k else (255, 255, 255)) + (255 if i == k else 90,))


STYLES = {"cinetique": s_cinetique, "compteur": s_compteur, "barres": s_barres, "duel": s_duel, "tactique": s_tactique,
          "titres": s_titres, "presse": s_presse}


def duree(sc):
    """Durée d'une scène : celle du storyboard, sinon selon le style et la quantité de contenu."""
    if sc.get("duree"):
        return float(sc["duree"])
    st = sc.get("style", "cinetique")
    n = {"barres": len(sc.get("elements", [])), "duel": len(sc.get("criteres", [])), "titres": len(sc.get("cartes", [])),
         "presse": len(sc.get("citations", [])), "tactique": len(sc.get("fleches", [])) + len(sc.get("zones", []))}.get(st, 0)
    if st == "cinetique":
        return round(min(4.0, max(1.8, len(sc.get("texte", "").split()) * 0.3 + 1.0)), 1)
    return round({"compteur": 3.0, "barres": 1.8 + 0.6 * n, "duel": 1.8 + 0.7 * n, "tactique": max(4.0, 1.6 + 0.8 * n),
                  "titres": 1.0 + 1.3 * n, "presse": 2.4 * n}.get(st, 3.0), 1)


# ---------- assemblage ----------
def image(sb, fonds, i, tl, durees, zones=False):
    sc, dur = sb["scenes"][i], durees[i]
    langue = sb.get("langue", "ar")
    c = fonds["photo" if sc.get("fond") == "photo" and "photo" in fonds else "uni"].copy().convert("RGBA")
    calque = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    STYLES.get(sc.get("style", "cinetique"), s_cinetique)(calque, sc, tl, dur, langue)
    if tl < 0.18 and i:  # transition : la scène monte en entrant
        decale = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        decale.alpha_composite(calque, (0, round(110 * (1 - sortie_douce(tl / 0.18)))))
        calque = decale
    c.alpha_composite(calque)
    d = ImageDraw.Draw(c)
    ecoule = sum(durees[:i]) + tl
    d.rectangle([0, 0, round(W * ecoule / sum(durees)), 9], fill=OR + (255,))  # progression
    if tl < 0.22 and i:  # éclair : bande dorée qui balaie l'écran au changement de scène
        x = -300 + (W + 600) * tl / 0.22
        translucide(c, lambda dd: dd.polygon([(x - 120, 0), (x + 40, 0), (x + 220, H), (x + 60, H)], fill=OR + (70,)))
    if sb.get("compte"):
        coller(c, image_mot(sb["compte"], 32, DOUX, "fr", NORMAL), CX, HAUT - 40, alpha=0.85)
    if sb.get("source"):
        mots = {"ar": "المصدر", "fr": "Source", "en": "Source", "es": "Fuente"}.get(langue, "Source")
        texte = f"{mots}: {sb['source']}" if langue != "ar" else f"{mots}: {sb['source']}"
        coller(c, image_mot(texte, 30, DOUX, langue, ARABE if langue == "ar" else NORMAL), CX, BAS - 30, alpha=0.85)
    if zones:  # zones masquées par les interfaces, pour vérifier la composition
        def masques(dd):
            for r in ([0, 0, W, HAUT], [0, BAS, W, H], [DROITE, HAUT, W, BAS]):
                dd.rectangle(r, fill=(255, 0, 0, 80))
        translucide(c, masques)
    return c.convert("RGB")


def rendre(chemin, musique=None, apercu=None, zones=False):
    chemin = Path(chemin)
    sb = json.loads(chemin.read_text(encoding="utf-8"))
    durees = [duree(sc) for sc in sb["scenes"]]
    total = sum(durees)
    fonds = {"uni": fond_uni()}
    if any(sc.get("fond") == "photo" for sc in sb["scenes"]):
        photo = photo_article(sb)
        if photo:
            fonds["photo"] = fond_photo(photo)
    if apercu is not None:
        k = apercu - 1
        sortie = chemin.parent / f"apercu-{apercu:02d}.png"
        image(sb, fonds, k, 0.78 * durees[k], durees, zones).save(sortie)
        return sortie
    sortie = chemin.parent / f"{chemin.parent.name}.mp4"
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if musique:
        cmd += ["-i", str(musique), "-af", f"afade=t=out:st={max(total - 1.5, 0):.2f}:d=1.5", "-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(sortie)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    premiere = None
    for i, dur in enumerate(durees):
        n = round(dur * FPS)
        for f in range(n):
            img = image(sb, fonds, i, f / FPS, durees)
            if sb.get("boucle") and i == len(durees) - 1 and f >= n - 9 and premiere is not None:
                img = Image.blend(img, premiere, (f - (n - 9)) / 9)  # fin fondue dans la première image : la boucle repart
            if i == 0 and f == 0:
                premiere = img
            if i == 0 and f == min(n - 1, round(1.2 * FPS)):
                img.save(chemin.parent / "couverture.png")
            proc.stdin.write(img.tobytes())
        print(f"  scène {i + 1}/{len(durees)} : {sb['scenes'][i].get('style', 'cinetique')} ({dur:.1f} s)")
    proc.stdin.close()
    if proc.wait():
        sys.exit("ffmpeg a échoué")
    print(f"{sortie} : {total:.1f} s")
    return sortie


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("storyboard")
    ap.add_argument("--apercu", type=int)
    ap.add_argument("--zones", action="store_true", help="avec --apercu : zones masquées par TikTok et Shorts en rouge")
    ap.add_argument("--musique")
    args = ap.parse_args()
    print(rendre(args.storyboard, args.musique, args.apercu, args.zones))

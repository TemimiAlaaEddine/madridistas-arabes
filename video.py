"""Vidéos verticales 1080×1920 (TikTok, YouTube Shorts, Reels, X), en scènes rythmées, à partir d'un storyboard JSON écrit par
la commande /video. Voix off facultative ("voix": true : edge-tts, noms lus d'après prononciation.json), bruitages
synthétisés (souffles, chocs, tics) calés sur les animations, plus une musique libre de droits si elle est fournie.
--muet : sans bruitages.

    python video.py videos/<sujet>/storyboard.json                    -> videos/<sujet>/<sujet>.mp4 et couverture.png
    python video.py videos/<sujet>/storyboard.json --apercu 2          -> apercu-02.png (scène 2 aux trois quarts)
    python video.py videos/<sujet>/storyboard.json --apercu 2 --zones  -> idem, zones masquées par TikTok et Shorts en rouge
    python video.py videos/<sujet>/storyboard.json --musique son.mp3

Storyboard : {"langue": "ar|fr|en|es", "photo": {"article": 437} | {"url": "..."} | null, "source": "ماركا",
"compte": "@ElMadridistAlaa", "boucle": true, "voix": true | "<voix edge-tts>", "scenes": [...]}. Chaque scène a un
"style", une "duree" facultative (sinon calculée, allongée pour la voix), "dit" facultatif (ce que lit la voix, sinon
"texte" ou "titre"), et "fond": "photo" pour la photo de l'article en fond (assombrie) au lieu du fond uni.
  cinetique : "texte" (mots entre *étoiles* en or), "etiquette" facultative. Accroche et chute.
  compteur  : "valeur" (ex. "1,06"), "unite", "texte", "max" facultatif (anneau rempli à valeur/max).
  barres    : "titre", "elements": [{"label", "valeur"}] (2 à 5), la plus grande en or.
  duel      : "joueurs": [A, B], "criteres": [{"label", "a", "b"}] (2 à 4).
  tactique  : "texte", "joueurs": [{"nom", "x", "y", "camp": "real|adverse"}], "fleches": [{"de": [x, y], "a": [x, y],
              "type": "course|passe"}], "zones": [{"x", "y", "l", "h"}] ; x de 0 (gauche) à 1, y de 0 (but du Real, en bas)
              à 1 ; chaque élément peut fixer son "t" d'apparition en secondes. Action animée : "ballon": [x, y] (départ)
              et "etapes": [{"joueurs": {"<nom>": [x, y]}, "ballon": [x, y] | "<nom du receveur>", "texte": sous-titre,
              "duree": 1.4}] jouées l'une après l'autre (badge ▶) ; {"pause": true, "focus": "<nom>", "texte": ...}
              fige l'action (badge ⏸, anneau doré autour du joueur, 2 s par défaut).
  titres    : "cartes": [{"journal", "titre"}] (1 à 3) : gros titres de presse traduits.
  presse    : "citations": [{"journal", "texte"}] (2 à 4) : « ce que dit la presse ».
  portrait  : "joueur", "image" facultative (sinon assets/joueurs/<joueur>.png, sinon silhouette dessinée avec "numero"),
              "couleur" facultative (sans elle : couleurs du Real, rayons bleu marine, anneau et étincelles dorés ; sinon nom de
              COULEURS ou [r, g, b] pour un autre club), "texte" : le joueur entre en rebond, zoom lent.
  trophees  : "titre", "icone" (trophee|ballon|etoile|carton), "groupes": [{"label", "n", "couleur"}] : grille qui se remplit,
              une icône par trophée (ou but, passe...), au rythme de la voix ; légende avec compteur par groupe.
  tableau   : "lignes": ["texte" | {"texte", "couleur": noir|rouge|bleu|vert, "souligne", "entoure", "taille"}] : écrites
              au feutre sur un tableau blanc, soulignées ou entourées en rouge.
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
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

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


def image_mot(mot, taille, couleur, langue, fichier=None, contour=0):
    """Un mot dessiné seul (RGBA), mis en cache : la typographie cinétique anime chaque mot séparément.
    contour : épaisseur en pixels d'un contour noir (lisible sur n'importe quel fond)."""
    fichier = fichier or (NOIR if latin(mot) and langue != "ar" else ARABE)
    cle = (mot, round(taille), couleur, langue, fichier, contour)
    if cle not in _mots:
        f, v = police(taille, fichier), visuel(mot, langue)
        g, h_, d, b = f.getbbox(v)
        haut = max(round(taille * 1.45), b + round(taille * 0.12) + 6)  # les polices manuscrites descendent plus bas
        img = Image.new("RGBA", (max(1, d - g + 8 + 2 * contour), haut + 2 * contour), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((4 - g + contour, round(taille * 0.12) + contour), v, font=f, fill=couleur + (255,),
                                 stroke_width=contour, stroke_fill=(0, 0, 0, 255))
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


def mots_marques(texte):
    """[(mot, en_or)] dans l'ordre ; un mot entre *étoiles* est marqué pour l'or."""
    mots, dedans = [], False
    for m in EMOJI.sub("", texte).split():
        if m.replace("*", ""):
            mots.append((m.replace("*", ""), dedans or "*" in m))
        dedans ^= m.count("*") % 2 == 1  # une étoile ouvre ou ferme le groupe en or
    return mots


def lignes_mots(texte, taille, langue, largeur=DROITE - GAUCHE):
    """Mots répartis en lignes (ordre logique)."""
    espace, lignes, cur, l = taille * 0.32, [], [], 0
    for mot, fort in mots_marques(texte):
        w = image_mot(mot, taille, BLANC, langue).width
        if cur and l + espace + w > largeur:
            lignes.append(cur)
            cur, l = [], 0
        cur.append((mot, fort, w))
        l += (espace if l else 0) + w
    return lignes + ([cur] if cur else []), espace


def cinetique(c, texte, taille, langue, y, tl, debut=0.0, pas=0.12, couleur=BLANC, cx=CX, largeur=DROITE - GAUCHE, centre=False,
              temps=None):
    """Typographie cinétique : chaque mot arrive l'un après l'autre (pop et montée), centré ; retourne le y sous le bloc.
    temps : instant de chaque mot dans la voix (s, depuis debut) ; sinon un mot tous les `pas`."""
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
            p = avance(tl, debut + (temps[k] - 0.05 if temps and k < len(temps) else k * pas), 0.28)
            centre_x = x - w / 2 if langue == "ar" else x + w / 2
            contour = max(3, round(taille * 0.06))
            coller(c, image_mot(mot, taille, OR if fort else couleur, langue, contour=contour), centre_x, y + i * hl + hl / 2 + 34 * (1 - sortie_douce(p)),
                   alpha=borne(p * 2), echelle=0.55 + 0.45 * rebond(p))
            x += -(w + espace) if langue == "ar" else w + espace
            k += 1
    return y + len(lignes) * hl


SOUS_TITRE_Y = BAS - 130  # toujours au même endroit, juste au-dessus de la source : l'œil ne cherche pas le texte


def sous_titre(c, texte, langue, tl, debut=0.0, el=None):
    """La phrase de récit d'une scène : même place, même taille, contour noir, quelle que soit la scène.
    el : la scène ou l'étape qui porte la phrase (rythme _pas ou instants _mots de sa voix)."""
    el = el or {}
    cinetique(c, texte, 58, langue, SOUS_TITRE_Y, tl, debut, el.get("_pas") or 0.07, centre=True, temps=el.get("_mots"))


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
    cinetique(c, sc.get("texte", ""), sc.get("taille", 104), langue, y, tl, 0.15, pas_cinetique(sc, dur), centre=True, temps=sc.get("_mots"))


def pas_cinetique(sc, dur):  # avec voix : le rythme de la parole (_pas, posé par preparer_voix)
    return sc.get("_pas") or min(0.16, dur * 0.45 / max(len(sc.get("texte", "").split()), 1))


def course_compteur(dur):  # le chiffre défile de 0,1 s à 0,1 s + cette durée
    return min(1.4, dur * 0.5)


def s_compteur(c, sc, tl, dur, langue):
    v, dec, sep = nombre(sc.get("valeur", 0))
    p = sortie_douce(avance(tl, 0.1, course_compteur(dur)))
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
    sous_titre(c, sc.get("texte", ""), langue, tl, 0.9, sc)


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


def etapes_temps(sc):
    """[(début, durée, étape)] des étapes animées d'une scène tactique, après l'apparition des joueurs et des flèches."""
    t = max(0.8 + 0.05 * len(sc.get("joueurs", [])) + 0.65 * len(sc.get("fleches", [])), sc.get("_debut_etapes", 0))
    out = []
    for e in sc.get("etapes", []):
        d = float(e.get("duree", 2.0 if e.get("pause") else 1.4))
        out.append((t, d, e))
        t += d
    return out


def positions(sc, tl):
    """Positions (x, y) des joueurs (par nom) et du ballon à l'instant tl, une fois appliqués les déplacements des étapes."""
    pos = {j.get("nom", str(k)): (float(j["x"]), float(j["y"])) for k, j in enumerate(sc.get("joueurs", []))}
    ballon = tuple(map(float, sc["ballon"])) if sc.get("ballon") else None
    for debut, _, e in etapes_temps(sc):
        if tl < debut:
            break
        p = sortie_douce(avance(tl, debut, 0.8))
        cibles = {n: tuple(map(float, xy)) for n, xy in e.get("joueurs", {}).items() if n in pos}
        b = e.get("ballon")
        if b is not None:  # une position, ou le nom du joueur qui reçoit (à sa position d'arrivée)
            cible = (cibles.get(b) or pos.get(b)) if isinstance(b, str) else tuple(map(float, b))
            if cible:
                ballon = cible if ballon is None else tuple(a + (z - a) * p for a, z in zip(ballon, cible))
        for n, cible in cibles.items():
            pos[n] = tuple(a + (z - a) * p for a, z in zip(pos[n], cible))
    return pos, ballon


def s_tactique(c, sc, tl, dur, langue):
    x0, x1, y0, y1 = 210, 790, 330, 1170  # remonté : le bas est réservé au sous-titre
    etapes = etapes_temps(sc)
    texte, t_texte, porteur, en_cours = sc.get("texte"), 0.15, sc, None
    for debut, d_e, e in etapes:  # le sous-titre suit l'étape en cours
        if tl >= debut:
            en_cours = (debut, d_e, e)
            if e.get("texte"):
                texte, t_texte, porteur = e["texte"], debut, e
    if texte:
        sous_titre(c, texte, langue, tl, t_texte, porteur)
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
    pos, ballon = positions(sc, tl)
    pause = en_cours and en_cours[2].get("pause") and tl < en_cours[0] + en_cours[1]
    if en_cours and tl < en_cours[0] + en_cours[1] + 0.5:  # lecture ▶ ou pause ⏸, en haut à gauche du terrain
        translucide(c, lambda dd: dd.rounded_rectangle([x0 + 14, y0 + 14, x0 + 96, y0 + 74], 16, fill=NAVY + (220,)))
        if pause:
            d.rectangle([x0 + 40, y0 + 28, x0 + 50, y0 + 60], fill=OR + (255,))
            d.rectangle([x0 + 60, y0 + 28, x0 + 70, y0 + 60], fill=OR + (255,))
        else:
            d.polygon([(x0 + 44, y0 + 26), (x0 + 44, y0 + 62), (x0 + 74, y0 + 44)], fill=BLANC + (255,))
    if pause and en_cours[2].get("focus") in pos:  # anneau doré qui pulse autour du joueur mis en avant
        fx, fy = pt(*pos[en_cours[2]["focus"]])
        r = 50 + 8 * math.sin((tl - en_cours[0]) * 8)
        d.ellipse([fx - r, fy - r, fx + r, fy + r], outline=OR + (255,), width=7)
    for k, j in enumerate(joueurs):  # joueurs : apparaissent en cascade
        pj = avance(tl, j.get("t", 0.3 + 0.05 * k), 0.3)
        if pj <= 0:
            continue
        x, y = pt(*pos[j.get("nom", str(k))])
        r = 27 * (0.4 + 0.6 * rebond(pj))
        real = j.get("camp", "real") == "real"
        d.ellipse([x - r, y - r, x + r, y + r], fill=(BLANC if real else ROUGE) + (255,), outline=OR + (255,) if j.get("cle") else None, width=6)
        if j.get("nom"):
            coller(c, image_mot(j["nom"], 28, BLANC, langue), x, y + 48, alpha=pj)
    if ballon:
        bx, by = pt(*ballon)
        translucide(c, lambda dd: dd.ellipse([bx - 13, by - 9, bx + 17, by + 15], fill=(0, 0, 0, 110)))  # ombre
        d.ellipse([bx - 15, by - 15, bx + 15, by + 15], fill=BLANC + (255,), outline=NAVY + (255,), width=4)


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


# ---------- scènes dessinées (style Tifo Football et tableau blanc : dessins fixes, mouvement autour) ----------
COULEURS = {"or": OR, "blanc": BLANC, "rouge": ROUGE, "bleu": (64, 160, 255), "vert": (70, 200, 120), "violet": (170, 110, 240)}
FEUTRES = {"noir": (25, 25, 30), "rouge": (210, 30, 40), "bleu": (25, 80, 200), "vert": (20, 140, 70)}
ASSETS = Path(__file__).with_name("assets")
_images = {}


def icone(nom, taille, couleur):
    """Icône dessinée (trait noir, aplat), mise en cache : trophee, ballon, etoile, carton."""
    cle = (nom, taille, couleur)
    if cle in _images:
        return _images[cle]
    s = 4  # dessinée 4 fois plus grande puis réduite : bords lisses
    T, k = taille * s, max(2, taille * s // 14)
    img = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    noir, fill = (15, 15, 20, 255), couleur + (255,)
    if nom == "ballon":
        d.ellipse([k, k, T - k, T - k], fill=(255, 255, 255, 255), outline=noir, width=k)
        cx, cy, r = T / 2, T / 2, T * 0.17
        d.polygon([(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(-90, 270, 72)], fill=noir)
    elif nom == "etoile":
        pts = [(T / 2 + (T * 0.46 if i % 2 == 0 else T * 0.2) * math.cos(math.radians(-90 + 36 * i)),
                T / 2 + (T * 0.46 if i % 2 == 0 else T * 0.2) * math.sin(math.radians(-90 + 36 * i))) for i in range(10)]
        d.polygon(pts, fill=fill, outline=noir, width=k)
    elif nom == "carton":
        d.rounded_rectangle([T * 0.25, T * 0.1, T * 0.75, T * 0.9], T // 14, fill=fill, outline=noir, width=k)
    else:  # trophee : anses, coupe (demi-ellipse), pied, socle
        for x0, x1, a, b in ((0.06, 0.4, 90, 270), (0.6, 0.94, -90, 90)):
            d.arc([T * x0, T * 0.14, T * x1, T * 0.46], a, b, fill=noir, width=k * 2)
            d.arc([T * x0 + k, T * 0.14 + k, T * x1 - k, T * 0.46 - k], a, b, fill=fill, width=k)
        d.chord([T * 0.16, -T * 0.26, T * 0.84, T * 0.64], 0, 180, fill=fill, outline=noir, width=k)
        d.rectangle([T * 0.43, T * 0.62, T * 0.57, T * 0.76], fill=fill, outline=noir, width=k)
        d.rounded_rectangle([T * 0.26, T * 0.74, T * 0.74, T * 0.92], T // 30, fill=fill, outline=noir, width=k)
        d.ellipse([T * 0.3, T * 0.12, T * 0.4, T * 0.3], fill=(255, 255, 255, 150))  # reflet
    _images[cle] = img.resize((taille, taille), Image.LANCZOS)
    return _images[cle]


def rayons(c, cx, cy, tl, couleur, clair=None):
    """Fond en rayons « pop art » qui tournent lentement, sur tout l'écran."""
    clair = clair or tuple(min(255, round(v * 1.35 + 12)) for v in couleur)
    d = ImageDraw.Draw(c)
    d.rectangle([0, 0, W, H], fill=couleur + (255,))
    a0, R = tl * 9, 2400
    for i in range(0, 24, 2):
        a, b = math.radians(a0 + i * 15), math.radians(a0 + (i + 1) * 15)
        d.polygon([(cx, cy), (cx + R * math.cos(a), cy + R * math.sin(a)), (cx + R * math.cos(b), cy + R * math.sin(b))], fill=clair + (255,))


def halo(c, cx, cy, r, tl):
    """Anneau doré lumineux qui pulse doucement derrière le portrait (identité du Real : bleu nuit, or, blanc)."""
    calque = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(calque)
    r = r * (1 + 0.015 * math.sin(tl * 3))
    for k in range(6, 0, -1):  # lueur : anneaux de plus en plus larges et transparents
        e = 10 + k * 14
        d.ellipse([cx - r - e / 2, cy - r - e / 2, cx + r + e / 2, cy + r + e / 2], outline=OR + (14,), width=round(e))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=OR + (255,), width=10)
    c.alpha_composite(calque)


def etincelles(c, cx, cy, rayon, tl, n=7, couleur=BLANC):
    """Petites étoiles qui scintillent autour d'un point (positions fixes, phases décalées)."""
    d = ImageDraw.Draw(c)
    for i in range(n):
        a = math.radians(i * 360 / n + 20)
        x, y = cx + rayon * math.cos(a) * (0.85 + 0.15 * (i % 3)), cy + rayon * math.sin(a) * (0.85 + 0.15 * ((i + 1) % 3))
        r = 18 * max(0.0, math.sin(tl * 4 + i * 1.7))
        if r > 2:
            d.polygon([(x, y - r), (x + r * 0.25, y - r * 0.25), (x + r, y), (x + r * 0.25, y + r * 0.25), (x, y + r),
                       (x - r * 0.25, y + r * 0.25), (x - r, y), (x - r * 0.25, y - r * 0.25)], fill=couleur + (230,))


def sans_fond_vert(img):
    """Détourage chromatique : si les coins sont vert vif (portraits générés sur fond #00FF00), le vert devient transparent
    et le liseré vert des bords est neutralisé. Une image sans fond vert est rendue telle quelle."""
    r, g, b, a = img.split()
    coins = [img.getpixel(p) for p in ((2, 2), (img.width - 3, 2))]  # coins du haut : en bas, le buste touche souvent le bord
    if not all(px[1] > 150 and px[1] > 1.6 * max(px[0], px[2]) for px in coins):
        return img
    autre = ImageChops.lighter(r, b)
    vert = ImageChops.subtract(g, autre)  # de combien le vert dépasse le rouge et le bleu
    alpha = vert.point(lambda v: 255 if v < 40 else max(0, 255 - (v - 40) * 4))
    g = ImageChops.darker(g, autre)  # bords : plus de reflet vert
    return Image.merge("RGBA", (r, g, b, ImageChops.multiply(a, alpha))).crop(ImageChops.multiply(a, alpha).getbbox())


def image_portrait(sc, hauteur):
    """Portrait du joueur, détouré avec un contour noir épais (effet autocollant) ; sinon une silhouette dessinée."""
    chemin = Path(sc["image"]) if sc.get("image") else ASSETS / "joueurs" / f"{nom_canonique(sc.get('joueur', ''))}.png"
    cle = (str(chemin), hauteur, sc.get("numero"), json.dumps(sc.get("apparence"), sort_keys=True))
    if cle in _images:
        return _images[cle]
    if chemin.is_file():
        img = sans_fond_vert(Image.open(chemin).convert("RGBA"))
        img = img.resize((round(img.width * hauteur / img.height), hauteur), Image.LANCZOS)
        bord = 14
        fond = Image.new("RGBA", (img.width + 2 * bord, img.height + 2 * bord), (0, 0, 0, 0))
        if img.getchannel("A").getextrema()[0] < 250:  # détouré : contour qui suit la silhouette
            masque = Image.new("L", fond.size, 0)
            masque.paste(img.getchannel("A"), (bord, bord))
            fond.paste((15, 15, 20, 255), (0, 0), masque.filter(ImageFilter.MaxFilter(2 * bord - 1)))
            fond.alpha_composite(img, (bord, bord))
        else:  # image pleine : carte aux coins arrondis, bord noir
            ImageDraw.Draw(fond).rounded_rectangle([0, 0, fond.width - 1, fond.height - 1], 40, fill=(15, 15, 20, 255))
            coins = Image.new("L", img.size, 0)
            ImageDraw.Draw(coins).rounded_rectangle([0, 0, img.width - 1, img.height - 1], 30, fill=255)
            fond.paste(img, (bord, bord), coins)
        _images[cle] = fond
        return fond
    _images[cle] = silhouette(apparence(sc), hauteur, sc.get("numero"))
    return _images[cle]


PEAUX = {"claire": (238, 198, 168), "mate": (200, 150, 110), "foncee": (120, 82, 58)}
TEINTES_CHEVEUX = {"noir": (28, 24, 22), "brun": (78, 52, 32), "blond": (214, 172, 92), "roux": (164, 82, 40), "blanc": (225, 225, 225)}


def nom_canonique(nom):
    """« فالفيردي » -> « Valverde » : le nom sous lequel le joueur est rangé dans apparences.json (et son portrait .png)."""
    fichier = ASSETS / "joueurs" / "apparences.json"
    toutes = json.loads(fichier.read_text(encoding="utf-8")) if fichier.exists() else {}
    return next((n for n, a in toutes.items() if nom in a.get("aussi", [])), nom)


def apparence(sc):
    """Attributs dessinés du joueur : assets/joueurs/apparences.json (par nom, ou par un de ses "aussi"), puis "apparence"
    de la scène par-dessus. Clés : peau, cheveux (court|boucles|rase|long|tresses|chauve), couleur_cheveux, barbe
    (aucune|courte|pleine), maillot [r, g, b], col [r, g, b]."""
    fichier, nom = ASSETS / "joueurs" / "apparences.json", sc.get("joueur", "")
    toutes = json.loads(fichier.read_text(encoding="utf-8")) if fichier.exists() else {}
    base = next((a for n, a in toutes.items() if n == nom or nom in a.get("aussi", [])), {})
    return {**base, **sc.get("apparence", {})}


def silhouette(a, hauteur, numero=None):
    """Buste dessiné façon caricature (trait noir, aplats) : on reconnaît le joueur à sa coupe, sa barbe, son teint, son numéro."""
    s = 2  # dessiné 2 fois plus grand puis réduit : bords lisses
    L, Hh, noir = round(hauteur * 0.8) * s, hauteur * s, (15, 15, 20, 255)
    img = Image.new("RGBA", (L, Hh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = max(6, Hh // 70)
    peau = PEAUX.get(a.get("peau"), PEAUX["mate"]) + (255,)
    ombre = tuple(round(v * 0.82) for v in peau[:3]) + (255,)
    tc = TEINTES_CHEVEUX.get(a.get("couleur_cheveux"), TEINTES_CHEVEUX["noir"]) + (255,)
    maillot, col = tuple(a.get("maillot", (246, 246, 246))) + (255,), tuple(a.get("col", (30, 30, 40))) + (255,)
    coupe = a.get("cheveux", "court")
    tete = [L * 0.29, Hh * 0.14, L * 0.71, Hh * 0.56]
    if coupe in ("long", "tresses"):  # cheveux qui tombent derrière la tête
        d.rounded_rectangle([L * 0.22, Hh * 0.12, L * 0.78, Hh * 0.64], round(L * 0.18), fill=tc, outline=noir, width=k)
        if coupe == "tresses":
            for x in (0.25, 0.29, 0.71, 0.75):
                d.line([L * x, Hh * 0.2, L * x, Hh * 0.63], fill=tuple(min(255, v + 50) for v in tc[:3]) + (255,), width=k)
    # buste, col en V, cou
    d.rounded_rectangle([L * 0.04, Hh * 0.6, L * 0.96, Hh * 1.25], round(L * 0.3), fill=maillot, outline=noir, width=k)
    d.polygon([(L * 0.38, Hh * 0.61), (L * 0.5, Hh * 0.71), (L * 0.62, Hh * 0.61)], fill=col, outline=noir)
    d.rectangle([L * 0.42, Hh * 0.47, L * 0.58, Hh * 0.63], fill=ombre, outline=noir, width=k)
    # oreilles, visage
    for x0 in (0.25, 0.68):
        d.ellipse([L * x0, Hh * 0.32, L * (x0 + 0.07), Hh * 0.42], fill=peau, outline=noir, width=k)
    d.ellipse(tete, fill=peau, outline=noir, width=k)
    if a.get("barbe") in ("courte", "pleine"):  # bas du visage : barbe pleine, ou ombre de barbe (calque à part : mélange)
        calque = Image.new("RGBA", img.size, (0, 0, 0, 0))
        dc = ImageDraw.Draw(calque)
        dc.chord(tete, 15, 165, fill=tc[:3] + ((255,) if a["barbe"] == "pleine" else (95,)))
        img.alpha_composite(calque)
    # yeux, sourcils, nez, bouche : traits simples
    for xo in (0.41, 0.59):
        d.ellipse([L * xo - k * 1.4, Hh * 0.335 - k * 1.4, L * xo + k * 1.4, Hh * 0.335 + k * 1.4], fill=noir)
        d.line([L * xo - L * 0.05, Hh * 0.3, L * xo + L * 0.05, Hh * 0.295], fill=tc[:3] + (255,) if coupe != "chauve" else noir, width=k * 2)
    d.line([L * 0.5, Hh * 0.35, L * 0.48, Hh * 0.42, L * 0.52, Hh * 0.42], fill=noir, width=max(3, k // 2))
    d.arc([L * 0.44, Hh * 0.43, L * 0.56, Hh * 0.49], 20, 160, fill=noir, width=max(3, k // 2))
    # cheveux par-dessus le haut de la tête
    if coupe == "court":
        d.chord([L * 0.27, Hh * 0.1, L * 0.73, Hh * 0.38], 180, 360, fill=tc, outline=noir, width=k)
    elif coupe == "rase":
        calque = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(calque).chord([L * 0.29 + k, Hh * 0.14 + k, L * 0.71 - k, Hh * 0.34], 180, 360, fill=tc[:3] + (190,))
        img.alpha_composite(calque)
    elif coupe == "boucles":
        for i in range(9):
            ang = math.radians(180 + i * 22.5)
            cx, cy, r = L * 0.5 + L * 0.21 * math.cos(ang), Hh * 0.27 + Hh * 0.13 * math.sin(ang), L * 0.075
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tc, outline=noir, width=k)
    elif coupe in ("long", "tresses"):
        d.chord([L * 0.27, Hh * 0.1, L * 0.73, Hh * 0.36], 180, 360, fill=tc, outline=noir, width=k)
    if numero:
        coller(img, image_mot(str(numero), Hh * 0.2, (20, 20, 30) if sum(maillot[:3]) > 380 else (245, 245, 245), "fr", NOIR),
               L / 2, Hh * 0.86)
    return img.resize((L // s, Hh // s), Image.LANCZOS)


def s_portrait(c, sc, tl, dur, langue):
    cy = HAUT + (SOUS_TITRE_Y - 120 - HAUT) * 0.48
    fond = sc.get("couleur")  # par défaut les couleurs du Real ; sinon un nom de COULEURS ou [r, g, b] (autre club)
    if fond:
        rayons(c, CX, cy, tl, tuple(fond) if isinstance(fond, list) else COULEURS.get(fond, NAVY))
    else:
        rayons(c, CX, cy, tl, NAVY, (17, 42, 82))
        halo(c, CX, cy - 40, 330, tl)
    img = image_portrait(sc, 760)
    p = avance(tl, 0.05, 0.45)
    zoom = 1 + 0.05 * borne(tl / max(dur, 0.1))  # zoom lent, comme une caméra qui s'approche
    coller(c, img, CX, cy + 160 * (1 - sortie_douce(p)), alpha=borne(p * 3), echelle=(0.7 + 0.3 * rebond(p)) * zoom)
    etincelles(c, CX, cy, 430, tl, couleur=BLANC if fond else OR)
    if sc.get("joueur"):
        pastille(c, sc["joueur"], langue, CX, cy + 400, taille=52, alpha=avance(tl, 0.4, 0.3))
    if sc.get("texte"):
        sous_titre(c, sc["texte"], langue, tl, 0.15, sc)


def temps_icones(sc, dur):
    """(début, intervalle) du remplissage de la grille : au rythme de la voix s'il y en a une."""
    n = max(1, sum(int(g.get("n", 0)) for g in sc.get("groupes", [])))
    fenetre = len(sc["_voix"]) / SR * 0.85 if sc.get("_voix") else min(dur * 0.6, n * 0.12)
    return 0.5, fenetre / n


def s_trophees(c, sc, tl, dur, langue):
    groupes = sc.get("groupes", [])
    cases = [(g, COULEURS.get(g.get("couleur"), list(COULEURS.values())[i % len(COULEURS)])) for i, g in enumerate(groupes)
             for _ in range(int(g.get("n", 0)))]
    y = HAUT + 10
    if sc.get("titre"):
        y = cinetique(c, sc["titre"], 64, langue, y, tl, 0, 0.06) + 30
    n = len(cases)
    if not n:
        return
    cols = 5 if n <= 20 else 6 if n <= 36 else 8
    lignes = math.ceil(n / cols)
    bas = SOUS_TITRE_Y - 110 - 54 * len(groupes) - 40  # place de la légende et du sous-titre
    cote = min((DROITE - GAUCHE) / cols, (bas - y) / lignes)
    x0 = CX - cote * cols / 2
    debut, pas = temps_icones(sc, dur)
    d = ImageDraw.Draw(c)
    for k, (g, couleur) in enumerate(cases):
        col, lig = k % cols, k // cols
        if langue == "ar":
            col = cols - 1 - col  # l'arabe se remplit de droite à gauche
        x, yy = x0 + col * cote + cote / 2, y + lig * cote + cote / 2
        d.rounded_rectangle([x - cote * 0.44, yy - cote * 0.44, x + cote * 0.44, yy + cote * 0.44], round(cote * 0.14),
                            fill=(255, 255, 255, 18), outline=(255, 255, 255, 60), width=3)
        p = avance(tl, debut + k * pas, 0.25)
        if p > 0:
            coller(c, icone(sc.get("icone", "trophee"), round(cote * 0.72), couleur), x, yy, echelle=0.3 + 0.7 * rebond(p))
    # légende : chaque groupe avec son compteur, qui apparaît quand il commence à se remplir
    yl, k0 = y + lignes * cote + 40, 0
    for i, g in enumerate(groupes):
        couleur = COULEURS.get(g.get("couleur"), list(COULEURS.values())[i % len(COULEURS)])
        faits = max(0, min(int(g.get("n", 0)), math.floor((tl - debut) / pas) + 1 - k0)) if pas else 0
        if faits:
            texte = f"{g.get('label', '')} {faits}"
            coller(c, image_mot(texte, 44, couleur, langue, contour=3), CX, yl + 54 * i, alpha=avance(tl, debut + k0 * pas, 0.2))
        k0 += int(g.get("n", 0))
    if sc.get("texte"):
        sous_titre(c, sc["texte"], langue, tl, 0.15, sc)


def lignes_tableau(sc, langue):
    """[(image du texte, couleur, ligne, nombre de mots)] : chaque ligne écrite au feutre, coupée si elle dépasse la largeur du tableau."""
    police_main = ARABE.replace("segoeuib", "majallab") if langue == "ar" else r"C:\Windows\Fonts\segoeprb.ttf"
    out = []
    for ligne in sc.get("lignes", []):
        ligne = {"texte": ligne} if isinstance(ligne, str) else ligne
        couleur, taille = FEUTRES.get(ligne.get("couleur", "noir"), FEUTRES["noir"]), ligne.get("taille", 76 if langue == "ar" else 62)
        while taille > 44 and image_mot(ligne.get("texte", ""), taille, couleur, langue, police_main).width > DROITE - GAUCHE - 140:
            taille -= 2  # une idée par ligne : on rétrécit avant de couper (sinon « entoure » entourerait chaque morceau)
        cur = []
        for mot in ligne.get("texte", "").split():  # coupe gloutonne au mot
            essai = " ".join(cur + [mot])
            if cur and image_mot(essai, taille, couleur, langue, police_main).width > DROITE - GAUCHE - 140:  # marge pour l'entourage
                out.append((image_mot(" ".join(cur), taille, couleur, langue, police_main), couleur, ligne, len(cur)))
                cur = [mot]
            else:
                cur.append(mot)
        if cur:
            out.append((image_mot(" ".join(cur), taille, couleur, langue, police_main), couleur, ligne, len(cur)))
    return out


def temps_lignes(sc, dur, langue):
    """[(début, durée)] d'écriture de chaque ligne : quand la voix lit les lignes, chacune commence à l'instant de son premier
    mot ; sinon au prorata de sa largeur, sur la durée de la voix s'il y en a une."""
    lignes = lignes_tableau(sc, langue)
    if sc.get("_mots"):
        debuts, k = [], 0
        for *_, n in lignes:
            debuts.append(0.15 + sc["_mots"][min(k, len(sc["_mots"]) - 1)])
            k += n
        fin = 0.15 + sc["_mots"][-1] + 0.6  # dernier mot prononcé (le MP3 finit par un silence)
        return [(t, max(0.3, (suivant - t - 0.1) * 0.9)) for t, suivant in zip(debuts, debuts[1:] + [fin])]
    largeurs = [img.width for img, *_ in lignes]
    total = sum(largeurs) or 1
    fenetre = len(sc["_voix"]) / SR * 0.9 if sc.get("_voix") else total / 900  # environ 900 px de texte par seconde
    t, out = 0.4, []
    for w in largeurs:
        out.append((t, fenetre * w / total))
        t += fenetre * w / total + 0.15
    return out


def s_tableau(c, sc, tl, dur, langue):
    d = ImageDraw.Draw(c)
    x0, y0, x1, y1 = GAUCHE - 20, HAUT + 10, DROITE, BAS - 70
    d.rounded_rectangle([x0 + 10, y0 + 14, x1 + 10, y1 + 14], 36, fill=(0, 0, 0, 90))  # ombre
    d.rounded_rectangle([x0, y0, x1, y1], 36, fill=(250, 249, 244, 255), outline=(200, 200, 205, 255), width=6)
    lignes, temps = lignes_tableau(sc, langue), temps_lignes(sc, dur, langue)
    y = max(y0 + 70, (y0 + y1) / 2 - sum(img.height * 1.4 for img, *_ in lignes) / 2)  # bloc centré sur le tableau
    for (img, couleur, ligne, _), (debut, d_l) in zip(lignes, temps):
        p = avance(tl, debut, d_l)
        if p <= 0:
            break
        larg = round(img.width * p)
        xg = CX - img.width / 2
        if larg:  # révélée comme si elle s'écrivait : de droite à gauche en arabe
            morceau = img.crop((img.width - larg, 0, img.width, img.height)) if langue == "ar" else img.crop((0, 0, larg, img.height))
            c.alpha_composite(morceau, (round(xg + (img.width - larg if langue == "ar" else 0)), round(y)))
        h = img.height
        if ligne.get("souligne") and p >= 1:
            ps = avance(tl, debut + d_l, 0.35)
            d.line([xg, y + h * 0.92, xg + img.width * ps, y + h * 0.92 + 4], fill=FEUTRES["rouge"] + (255,), width=9)
        if ligne.get("entoure") and p >= 1:
            pe = avance(tl, debut + d_l, 0.5)
            d.arc([xg - 30, y - 6, xg + img.width + 30, y + h + 6], -100, -100 + 370 * pe, fill=FEUTRES["rouge"] + (255,), width=8)
        if p < 1:  # le feutre, au bout du trait
            px = xg + (img.width - larg if langue == "ar" else larg)
            py = y + h * 0.62 + 6 * math.sin(tl * 40)
            d.polygon([(px, py), (px + 22, py - 30), (px + 128, py - 190), (px + 168, py - 160), (px + 62, py)], fill=(60, 60, 68, 255))
            d.polygon([(px, py), (px + 22, py - 30), (px + 62, py)], fill=couleur + (255,))
            d.polygon([(px + 128, py - 190), (px + 168, py - 160), (px + 185, py - 186), (px + 146, py - 214)], fill=couleur + (255,))
        y += h * 1.4
    if sc.get("texte"):
        sous_titre(c, sc["texte"], langue, tl, 0.15, sc)


STYLES = {"cinetique": s_cinetique, "compteur": s_compteur, "barres": s_barres, "duel": s_duel, "tactique": s_tactique,
          "titres": s_titres, "presse": s_presse, "portrait": s_portrait, "trophees": s_trophees, "tableau": s_tableau}


def duree(sc):
    """Durée d'une scène : celle du storyboard, sinon selon le style et la quantité de contenu."""
    if sc.get("duree"):
        return float(sc["duree"])
    st = sc.get("style", "cinetique")
    n = {"barres": len(sc.get("elements", [])), "duel": len(sc.get("criteres", [])), "titres": len(sc.get("cartes", [])),
         "presse": len(sc.get("citations", [])), "tactique": len(sc.get("fleches", [])) + len(sc.get("zones", []))}.get(st, 0)
    if st == "cinetique":
        return round(min(4.0, max(1.8, len(sc.get("texte", "").split()) * 0.3 + 1.0)), 1)
    if st == "tactique" and sc.get("etapes"):
        debut, d, _ = etapes_temps(sc)[-1]
        return round(max(4.0, debut + d + 0.8), 1)
    if st == "trophees":
        n = sum(int(g.get("n", 0)) for g in sc.get("groupes", []))
        return round(min(9.0, max(3.5, 1.6 + n * 0.12)), 1)
    if st == "tableau":
        debut, d_l = (temps_lignes(sc, 0, sc.get("_langue", "ar")) or [(0.4, 1.0)])[-1]
        return round(max(3.0, debut + d_l + 1.4), 1)
    return round({"compteur": 3.0, "barres": 1.8 + 0.6 * n, "duel": 1.8 + 0.7 * n, "tactique": max(4.0, 1.6 + 0.8 * n),
                  "titres": 1.0 + 1.3 * n, "presse": 2.4 * n, "portrait": 3.2}.get(st, 3.0), 1)


# ---------- bruitages ----------
# Synthétisés ici (pas de fichier son, donc pas de droits) : souffle aux transitions, choc sur l'accroche,
# « pop » sur chaque groupe de mots en or, cliquetis du compteur puis impact quand le chiffre s'arrête.
SR = 44100


def son(nom, alea):
    """Échantillons (floats de -1 à 1) d'un bruitage."""
    if nom == "souffle":  # bruit filtré dont le filtre s'ouvre puis se referme
        n, y, out = int(0.42 * SR), 0.0, []
        for i in range(n):
            t = i / n
            y += (0.02 + 0.3 * math.sin(math.pi * t) ** 2) * (alea.uniform(-1, 1) - y)
            out.append(y * 0.9 * math.sin(math.pi * t) ** 2)
        return out
    if nom in ("choc", "impact", "frappe"):  # basse qui chute, avec un clic d'attaque
        d, k = {"choc": (0.7, 6), "impact": (0.35, 11), "frappe": (0.15, 30)}[nom]
        phase, out = 0.0, []
        for i in range(int(d * SR)):
            t = i / SR
            phase += 2 * math.pi * (40 + 70 * math.exp(-t * 18)) / SR
            out.append(0.7 * math.exp(-t * k) * math.sin(phase) + (alea.uniform(-0.25, 0.25) if t < 0.008 else 0))
        return out
    if nom == "feutre":  # bruit aigu et irrégulier : un feutre qui frotte le tableau
        out, prec = [], 0.0
        for i in range(int(0.5 * SR)):
            x = alea.uniform(-1, 1)
            out.append(0.07 * (x - prec) * (0.6 + 0.4 * math.sin(i / SR * 2 * math.pi * 9)) * math.sin(math.pi * i / (0.5 * SR)))
            prec = x
        return out
    if nom == "pop":
        return [0.3 * math.exp(-i / SR * 45) * math.sin(2 * math.pi * (950 - 4000 * i / SR) * i / SR) for i in range(int(0.08 * SR))]
    return [0.22 * math.exp(-i / SR * 220) * math.sin(2 * math.pi * 2600 * i / SR) for i in range(int(0.025 * SR))]  # tic


def evenements(sb, durees):
    """[(instant en s, bruitage)] calés sur les animations de chaque scène."""
    ev, debut = [], 0.0
    for i, (sc, dur) in enumerate(zip(sb["scenes"], durees)):
        st = sc.get("style", "cinetique")
        ev.append((debut, "choc" if i == 0 else "souffle"))
        if st == "cinetique":
            avant = False
            for k, (_, fort) in enumerate(mots_marques(sc.get("texte", ""))):
                if fort and not avant and (i or k):  # début d'un groupe en or (pas au même instant que le choc)
                    t = sc["_mots"][k] if k < len(sc.get("_mots") or []) else k * pas_cinetique(sc, dur)
                    ev.append((debut + 0.15 + t, "pop"))
                avant = fort
        elif st == "compteur":
            course = course_compteur(dur)
            for k in range(1, 12):  # tics de plus en plus espacés, comme le chiffre qui ralentit
                ev.append((debut + 0.1 + course * (1 - (1 - k / 12) ** (1 / 3)), "tic"))
            ev.append((debut + 0.1 + course, "impact"))
        elif st == "trophees":
            t0, pas = temps_icones(sc, dur)
            n = sum(int(g.get("n", 0)) for g in sc.get("groupes", []))
            ev += [(debut + t0 + k * pas, "tic") for k in range(n)]
        elif st == "tableau":
            for t0, d_l in temps_lignes(sc, dur, sc.get("_langue", "ar")):  # frottement du feutre pendant l'écriture
                ev += [(debut + t0 + j * 0.5, "feutre") for j in range(max(1, round(d_l / 0.5)))]
        elif st == "portrait":
            ev.append((debut + 0.05, "pop"))
        elif st == "tactique":
            for t, _, e in etapes_temps(sc):  # frappe quand le ballon part, « pop » à l'arrêt sur image
                if e.get("ballon") is not None or e.get("pause"):
                    ev.append((debut + t, "pop" if e.get("pause") else "frappe"))
        debut += dur
    return ev


# ---------- voix ----------
# edge-tts (voix neuronales de Microsoft), choisies par l'utilisateur à l'écoute (2026-11-17/18). Les noms mal prononcés sont
# réécrits pour la voix seulement via prononciation.json, un dictionnaire par langue (l'écran garde l'écriture normale).
VOIX = {"ar": "ar-QA-MoazNeural", "fr": "fr-FR-RemyMultilingualNeural", "en": "en-US-GuyNeural", "es": "es-ES-AlvaroNeural"}
PRONONCIATION = Path(__file__).with_name("prononciation.json")


def a_dire(texte, langue="ar"):
    """Texte lu par la voix : sans étoiles, noms remplacés par leur écriture prononçable (en arabe, préfixes و ف ب ل gardés)."""
    texte = EMOJI.sub("", texte.replace("*", ""))
    noms = json.loads(PRONONCIATION.read_text(encoding="utf-8")).get(langue, {}) if PRONONCIATION.exists() else {}
    # bornes : en arabe lettres et voyelles seulement (« ، » et « ؟ » sont dans le même bloc Unicode), ailleurs lettres et chiffres
    lettre, prefixe = (r"[ء-ْ]", "[وفبل]?") if langue == "ar" else (r"\w", "")
    for nom in sorted(noms, key=len, reverse=True):  # le plus long d'abord : « ألكسندر-أرنولد » avant « أرنولد »
        texte = re.sub(rf"(?<!{lettre})({prefixe}){re.escape(nom)}(?!{lettre})", rf"\g<1>{noms[nom]}", texte)
    return texte


def voix_echantillons(texte, voix, dossier):
    """(échantillons, instants) de la phrase lue : floats de -1 à 1, et début de chaque mot prononcé en secondes.
    MP3 et instants gardés en cache dans dossier/voix/ (rendu rejoué sans réseau)."""
    import array
    import asyncio
    import hashlib
    dossier.mkdir(exist_ok=True)
    base = dossier / hashlib.sha1(f"{voix}|{texte}".encode()).hexdigest()[:16]
    mp3, mots = base.with_suffix(".mp3"), base.with_suffix(".json")
    if not (mp3.exists() and mots.exists()):
        import edge_tts

        async def lire():
            instants = []
            with open(mp3, "wb") as f:
                async for morceau in edge_tts.Communicate(texte, voix, rate="+5%", boundary="WordBoundary").stream():
                    if morceau["type"] == "audio":
                        f.write(morceau["data"])
                    elif morceau["type"] == "WordBoundary":
                        instants.append(morceau["offset"] / 1e7)  # unités de 100 ns
            return instants
        mots.write_text(json.dumps(asyncio.run(lire())), encoding="utf-8")
    brut = subprocess.run([FFMPEG, "-v", "error", "-i", str(mp3), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                          capture_output=True, check=True).stdout
    return [v / 32768 for v in array.array("h", brut)], json.loads(mots.read_text(encoding="utf-8"))


def preparer_voix(sb, dossier):
    """Si "voix" : synthétise la phrase de chaque scène (champ "dit", sinon "texte" ou "titre") et de chaque étape tactique,
    puis allonge durées et rythme des mots pour suivre la parole. Les échantillons restent dans les scènes (_voix)."""
    if not sb.get("voix"):
        return
    langue = sb.get("langue", "ar")
    voix = sb["voix"] if isinstance(sb["voix"], str) else VOIX.get(langue, VOIX["ar"])

    def lire(el, debut, dur_min):
        # tableau : les lignes lues l'une après l'autre (un point entre deux : la voix marque la pause)
        affiche = el.get("texte") or ". ".join(l if isinstance(l, str) else l.get("texte", "") for l in el.get("lignes", []))
        dit = el.get("dit") or affiche or el.get("titre") or ""
        if not dit.strip():
            return 0.0
        el["_voix"], instants = voix_echantillons(a_dire(dit, langue), voix, dossier)
        long = len(el["_voix"]) / SR
        n = max(len(mots_marques(affiche or dit)), 1)
        el["_pas"] = long * 0.85 / n  # repli : mots répartis sur la phrase
        if instants and affiche and not el.get("dit"):  # l'écran montre ce qui est lu : chaque mot à son instant
            # le k-ième mot affiché prend l'instant du mot prononcé de même rang (au prorata si les nombres diffèrent)
            el["_mots"] = [instants[min(len(instants) - 1, k * len(instants) // n)] for k in range(n)]
        el["_debut_voix"] = debut
        return max(dur_min, debut + long + 0.35)

    for sc in sb["scenes"]:
        st = sc.get("style", "cinetique")
        if st == "tactique" and sc.get("etapes"):
            sc["_debut_etapes"] = lire(sc, 0.15, 0)  # les étapes attendent la fin de la phrase d'introduction
            for e in sc["etapes"]:
                e["duree"] = round(lire(e, 0, float(e.get("duree", 2.0 if e.get("pause") else 1.4))), 2)
        else:
            lu = lire(sc, 0.9 if st == "compteur" else 0.15, duree(sc))
            # tableau et grille s'étalent sur la voix : leur durée se recalcule une fois la voix connue (sauf durée imposée)
            refait = duree({k: v for k, v in sc.items() if k != "duree"}) if not sc.get("duree") else 0
            sc["duree"] = round(max(lu, refait), 2)


def voix_evenements(sb, durees):
    """[(instant en s, échantillons)] de toutes les phrases lues."""
    ev, debut = [], 0.0
    for sc, dur in zip(sb["scenes"], durees):
        if "_voix" in sc:
            ev.append((debut + sc["_debut_voix"], sc["_voix"]))
        if sc.get("style") == "tactique":
            ev += [(debut + t, e["_voix"]) for t, _, e in etapes_temps(sc) if "_voix" in e]
        debut += dur
    return ev


def piste_audio(sb, durees, sortie, bruitages=True):
    """Écrit la piste son (WAV 16 bits mono) de la durée exacte de la vidéo : voix et bruitages (plus discrets sous la voix)."""
    import array
    import random
    import wave
    alea, cache = random.Random(7), {}
    piste = [0.0] * int(sum(durees) * SR)
    paroles = voix_evenements(sb, durees)
    gain = 0.5 if paroles else 1.0
    sons = [(t, [v * gain for v in cache.setdefault(nom, son(nom, alea))]) for t, nom in evenements(sb, durees)] if bruitages else []
    for t, echant in sons + paroles:
        d = int(t * SR)
        for j, v in enumerate(echant[:max(0, len(piste) - d)]):
            piste[d + j] += v
    with wave.open(str(sortie), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(array.array("h", (round(max(-1.0, min(1.0, v)) * 32000) for v in piste)).tobytes())
    return sortie


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


def rendre(chemin, musique=None, apercu=None, zones=False, muet=False):
    chemin = Path(chemin)
    sb = json.loads(chemin.read_text(encoding="utf-8"))
    for sc in sb["scenes"]:
        sc["_langue"] = sb.get("langue", "ar")  # pour duree() : la largeur des lignes du tableau dépend de la police
    preparer_voix(sb, chemin.parent / "voix")
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
    fondu = f"afade=t=out:st={max(total - 1.5, 0):.2f}:d=1.5"
    wav = None if muet and not sb.get("voix") else piste_audio(sb, durees, chemin.parent / "son.wav", bruitages=not muet)
    if wav:
        cmd += ["-i", str(wav)]
    if musique:
        cmd += ["-i", str(musique)]
    if wav and musique:
        cmd += ["-filter_complex", f"[2:a]{fondu},volume=0.55[m];[1:a][m]amix=inputs=2:duration=first:normalize=0[a]",
                "-map", "0:v", "-map", "[a]"]
    elif musique:
        cmd += ["-af", fondu]
    if wav or musique:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
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
    ap.add_argument("--muet", action="store_true", help="sans bruitages (vidéo muette, ou musique seule)")
    args = ap.parse_args()
    print(rendre(args.storyboard, args.musique, args.apercu, args.zones, args.muet))

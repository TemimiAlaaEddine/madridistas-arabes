"""Vidéo d'analyse : l'évolution de la compo de Mourinho (thread du 2026-11-09 lu en entier, voix de synthèse arabe).

Usage : python render.py              -> mourinho.mp4 (voix en cache dans audio/, segments dans segments/)
        python render.py --apercu 7   -> apercu-07.png (image du segment 7 aux trois quarts, sans vidéo)
Images : uniquement des schémas tactiques dessinés ici, jamais d'images de match (droits LaLiga, UEFA, diffuseurs).
Texte : scripts/2026-11-09-thread-compo-mourinho.md (un tweet = un segment).
"""
import asyncio
import glob
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import arabic_reshaper
import edge_tts
from bidi import get_display
from PIL import Image, ImageDraw, ImageFont

ICI = Path(__file__).resolve().parent
THREAD = ICI.parent.parent / "scripts" / "2026-11-09-thread-compo-mourinho.md"
_bin = glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg-*\bin"))
FFMPEG = os.path.join(_bin[0], "ffmpeg.exe") if _bin else "ffmpeg"
FFPROBE = os.path.join(_bin[0], "ffprobe.exe") if _bin else "ffprobe"
W, H, FPS, PAD = 1920, 1080, 25, 0.7
VOIX = "ar-SA-HamedNeural"

NAVY, NAVY2, OR, BLANC, DOUX = (11, 31, 58), (6, 18, 38), (254, 190, 16), (255, 255, 255), (200, 211, 230)
ROUGE, VERT_OK, GRIS = (224, 69, 58), (46, 204, 113), (120, 134, 156)
PELOUSE = ((21, 70, 50), (24, 78, 55))

# ---------- texte arabe (Pillow sans raqm : on relie les lettres et on ordonne de droite à gauche nous-mêmes) ----------
_polices = {}


def police(taille, gras=True):
    cle = (taille, gras)
    if cle not in _polices:
        _polices[cle] = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf" if gras else r"C:\Windows\Fonts\segoeui.ttf", taille)
    return _polices[cle]


def ar(s):
    # « 4-2-3-1 » et les scores sont isolés, sinon l'algorithme droite-à-gauche les inverse (« 1-3-2-4 »)
    s = re.sub(r"\d+(?:[-/]\d+)+", lambda m: f"⁦{m.group()}⁩", s)
    v = get_display(arabic_reshaper.reshape(s)).replace("⁦", "").replace("⁩", "")
    return v.translate(MIROIR)  # python-bidi ne retourne pas ces signes dans le texte de droite à gauche


MIROIR = str.maketrans("()«»", ")(»«")


def couper(s, f, maxw):
    lignes, cur = [], ""
    for mot in s.split():
        essai = f"{cur} {mot}".strip()
        if cur and f.getlength(ar(essai)) > maxw:
            lignes.append(cur)
            cur = mot
        else:
            cur = essai
    return lignes + [cur] if cur else lignes


def ecrire(d, x, y, s, taille, couleur, maxw=10000, align="r", gras=True, interligne=1.4):
    """Écrit s (logique) à partir de y ; x = bord droit (align r) ou centre (align c). Retourne le y suivant."""
    f = police(taille, gras)
    for ligne in couper(s, f, maxw):
        v = ar(ligne)
        lx = x - f.getlength(v) if align == "r" else x - f.getlength(v) / 2
        d.text((lx, y), v, font=f, fill=couleur)
        y += taille * interligne
    return y


def melange(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def lisse(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


# ---------- terrain (vertical, on attaque vers le haut ; x : 0 = ligne de touche gauche de l'équipe, 1 = droite) ----------
PX0, PY0, PW, PH = 150, 140, 500, 772


def pp(x, y):
    return (PX0 + x * PW, PY0 + (1 - y) * PH)


def dessiner_terrain(d):
    for i in range(10):
        d.rectangle([PX0, PY0 + i * PH / 10, PX0 + PW, PY0 + (i + 1) * PH / 10], fill=PELOUSE[i % 2])
    L, ep = (215, 232, 222), 3
    d.rectangle([PX0, PY0, PX0 + PW, PY0 + PH], outline=L, width=ep)
    d.line([PX0, PY0 + PH / 2, PX0 + PW, PY0 + PH / 2], fill=L, width=ep)
    r = 9.15 / 68 * PW
    cx, cy = PX0 + PW / 2, PY0 + PH / 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=L, width=ep)
    for haut in (True, False):
        for larg, prof in ((40.3, 16.5), (18.3, 5.5)):
            w, h = larg / 68 * PW, prof / 105 * PH
            y0 = PY0 if haut else PY0 + PH - h
            d.rectangle([cx - w / 2, y0, cx + w / 2, y0 + h], outline=L, width=ep)


# ---------- dessins communs ----------
def fond():
    im = Image.new("RGBA", (W, H), NAVY + (255,))
    d = ImageDraw.Draw(im)
    for i in range(0, W, 240):  # rayures discrètes du maillot extérieur
        d.rectangle([i + 120, 0, i + 240, H], fill=(13, 35, 64, 255))
    return im


def entete(d, chip):
    f = police(30)
    v = ar(chip)
    wch = f.getlength(v) + 56
    d.rounded_rectangle([W - 70 - wch, 34, W - 70, 92], radius=29, outline=OR, width=3)
    d.text((W - 70 - wch + 28, 44), v, font=f, fill=BLANC)
    f2 = police(38)
    a, b = ar("علاء"), ar("المدريديستا")
    d.text((70, 40), a, font=f2, fill=OR)
    d.text((70 + f2.getlength(a) + 12, 40), b, font=f2, fill=BLANC)


def fleche(d, pts, p, couleur, largeur=6, tirets=False):
    """Trace la polyligne pts jusqu'à la fraction p de sa longueur, avec une pointe."""
    if p <= 0 or len(pts) < 2:
        return
    long = [0.0]
    for a, b in zip(pts, pts[1:]):
        long.append(long[-1] + math.dist(a, b))
    cible, trace = long[-1] * min(p, 1), [pts[0]]
    for i in range(1, len(pts)):
        if long[i] >= cible:
            a, b = pts[i - 1], pts[i]
            k = (cible - long[i - 1]) / max(long[i] - long[i - 1], 1e-6)
            trace.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k))
            break
        trace.append(pts[i])
    if tirets:
        for i, (a, b) in enumerate(zip(trace, trace[1:])):
            if i % 2 == 0:
                d.line([a, b], fill=couleur, width=largeur)
    else:
        d.line(trace, fill=couleur, width=largeur, joint="curve")
    (x1, y1), (x2, y2) = trace[-2], trace[-1]
    ang = math.atan2(y2 - y1, x2 - x1)
    t = 22
    d.polygon([(x2 + math.cos(ang) * 6, y2 + math.sin(ang) * 6),
               (x2 - t * math.cos(ang - 0.45), y2 - t * math.sin(ang - 0.45)),
               (x2 - t * math.cos(ang + 0.45), y2 - t * math.sin(ang + 0.45))], fill=couleur)


def courbe(a, b, pli=0.0, n=40):
    """Points d'une courbe de a à b (coordonnées terrain) ; pli = décalage perpendiculaire en pixels."""
    (ax, ay), (bx, by) = pp(*a), pp(*b)
    mx, my = (ax + bx) / 2, (ay + by) / 2
    nx, ny = -(by - ay), bx - ax
    norme = math.hypot(nx, ny) or 1
    cx, cy = mx + nx / norme * pli, my + ny / norme * pli
    return [((1 - t) ** 2 * ax + 2 * (1 - t) * t * cx + t * t * bx, (1 - t) ** 2 * ay + 2 * (1 - t) * t * cy + t * t * by)
            for t in (i / n for i in range(n + 1))]


def carton(d, x, y):
    d.rounded_rectangle([x - 14, y - 20, x + 14, y + 20], radius=4, fill=ROUGE, outline=BLANC, width=2)


def ballon(d, x, y, r=11):
    d.ellipse([x - r, y - r, x + r, y + r], fill=BLANC, outline=(30, 30, 30), width=2)


# ---------- postes ----------
P = {"GK": (0.5, 0.06), "RB": (0.86, 0.27), "RCB": (0.63, 0.17), "LCB": (0.37, 0.17), "LB": (0.14, 0.27),
     "RDM": (0.63, 0.40), "LDM": (0.37, 0.40), "RW": (0.85, 0.64), "AM": (0.5, 0.62), "LW": (0.15, 0.64), "ST": (0.5, 0.84)}
ACTUEL = {"GK": "كورتوا", "RB": "فالفيردي", "RCB": "كوناتي", "LCB": "هاوسن", "LB": "كوكوريا", "LDM": "تشواميني",
          "RDM": "برناردو", "RW": "غولر", "AM": "بيلينغهام", "LW": "ديوماندي", "ST": "مبابي"}


def j(poste, l="", **kw):
    """Joueur à son poste ; kw : kf=[(t, x, y)], hl=(t0, t1), pale=True, a=t d'apparition, fin=t, labels=[(t, nom)], adv=True."""
    x, y = P[poste] if poste in P else poste
    return {"l": l, "kf": [(0, x, y)], **kw}


def onze(noms=None, pales=(), sauf=(), **kw):
    """Les 11 postes ; noms : dict poste -> nom ('' = joueur non nommé) ; pales : postes en retrait ; sauf : postes absents."""
    noms = ACTUEL if noms is None else noms
    return [j(p, noms.get(p, ""), pale=p in pales or pales == "tous", **kw) for p in P if p not in sauf]


AUTRES = tuple(p for p in P)

# ---------- segments (un par tweet) ----------
VOIX_REMPLACE = {
    " 🧵 #ريال_مدريد": "", "4-2-3-1": "أربعة اثنان ثلاثة واحد", "4-3-3": "أربعة ثلاثة ثلاثة",
    "أمام أتلتيكو (1-2) ظهر الثمن": "أمام أتلتيكو، في الخسارة بهدفين لهدف، ظهر الثمن",
    "الكلاسيكو (2-1)": "الكلاسيكو، والفوز بهدفين لهدف", "أمام فياريال (1-0):": "أمام فياريال، في الفوز بهدف نظيف:",
    "(37)": "بسبع وثلاثين مراوغة", "65%": "خمسة وستين في المئة", " (رقم 10)": "، أي رقم عشرة،",
    "أمام أيك (3-2)": "أمام أيك، في الفوز بثلاثة أهداف لهدفين",
}

SEGMENTS = [
    {"type": "titre", "chip": "تحليل تكتيكي"},
    {"type": "terrain", "chip": "نقطة البداية",
     "joueurs": [j("GK", "كورتوا", a=0.02), j("RB", "ترينت / دمفريز", a=0.04, hl=("s1", 1)), j("RCB", a=0.06), j("LCB", a=0.06),
                 j("LB", a=0.08), j("RDM", "فالفيردي", a=0.1, hl=("s1", 1)), j("LDM", "برناردو", a=0.1, hl=("s1", 1)),
                 j("AM", "بيلينغهام", a=0.12, hl=(0.1, "s1")), j("RW", a=0.14), j("LW", "فينيسيوس", a=0.14, hl=("s1+0.1", 1)),
                 j("ST", "مبابي", a=0.16)],
     "items": [("s0", "h", "خطة الصيف: 4-2-3-1"), ("s0", "p", "ارتكاز مزدوج وبيلينغهام صانع لعب"), ("s0", "p", "بعد سنوات من 4-3-3"),
               ("s1", "p", "الجولة الأولى: برناردو وفالفيردي في الارتكاز"), ("s1", "p", "الظهير الأيمن: ترينت أو دمفريز"),
               ("s1", "p", "اليسار: فينيسيوس")]},
    {"type": "terrain", "chip": "المشكلة الأولى · بناء اللعب",
     "zones": [("rect", (0.22, 0.31, 0.78, 0.49), OR, 0.05, 1, "")],
     "joueurs": onze({}, pales=("GK", "RB", "RCB", "LCB", "LB", "RW", "AM", "LW", "ST"), sauf=("LDM", "RDM"))
     + [j("LDM", hl=(0, 1), labels=[(0, "كامافينغا"), (0.36, "ترينت"), (0.68, "تشواميني")]),
        j("RDM", hl=(0, 1), labels=[(0, "فالفيردي"), (0.68, "")])],
     "items": [(0, "h", "المشكلة الأولى: بناء اللعب"), (0.02, "p", "من يشكّل الارتكاز؟"), (0.12, "p", "بيتيس: كامافينغا + فالفيردي"),
               (0.36, "p", "إنتر: ترينت + فالفيردي", "ko", "مفروض: غيابات"),
               (0.68, "p", "أتلتيكو: تشواميني بدل برناردو", "ok", "مقصود: الصلابة")]},
    {"type": "terrain", "chip": "أتلتيكو 2-1 ريال مدريد",
     "joueurs": onze({"LCB": "هاوسن"}, pales=tuple(p for p in P if p != "LCB"), sauf=("RDM",))
     + [j("RDM", "برناردو 82'", kf=[(0, -0.17, 0.42), ("s0+0.25", -0.17, 0.42), ("s0+0.4", 0.63, 0.40)], hl=("s0+0.25", 1))],
     "cartons": [("s1", "LCB")], "items": [
         ("s0", "h", "أتلتيكو 2-1 ريال مدريد"), ("s0", "p", "بلا مبدع في البناء ← الفريق يختنق"),
         ("s0+0.25", "p", "برناردو لا يدخل إلا قرب الدقيقة 82", "ok", "مقصود"), ("s1", "p", "طرد هاوسن بعد الفار", "ko", "غير مقصود"),
         ("s2", "p", "روديغر 89' من ركلة حرة نفذها برناردو")]},
    {"type": "terrain", "chip": "الحل في الارتكاز",
     "joueurs": [p | ({"hl": ("s1", 1), "pale": False} if p["l"] in ("تشواميني", "برناردو") else {}) for p in onze(pales="tous")],
     "zones": [("cercle", (0.37, 0.40, 0.11), VERT_OK, "s1", 1, "استعادة")],
     "fleches": [("s1+0.05", "s1+0.2", (0.63, 0.40), (0.85, 0.62), OR, 30), ("s1+0.2", "s1+0.35", (0.63, 0.40), (0.5, 0.60), OR, -20),
                 ("s1+0.35", "s1+0.5", (0.63, 0.40), (0.86, 0.29), OR, 25)],
     "items": [("s0", "h", "الحل: تشواميني + برناردو"), ("s1", "p", "برناردو: رصانة وحلول بسيطة في التدوير"),
               ("s1", "p", "تشواميني: المتخصص الدفاعي الأول"), ("s1", "src", "سانتياغو سيغيرو · ماركا"),
               ("s2", "p", "أول مباراة كبرى للثنائي: الكلاسيكو 2-1")]},
    {"type": "terrain", "chip": "المشكلة الثانية · الهجوم المنظم",
     "joueurs": onze({}, pales=("GK", "RB", "RCB", "LCB", "LB", "RDM", "LDM", "RW", "AM"), sauf=("LW", "ST"))
     + [j("LW", "فينيسيوس", hl=("s1", 1), kf=[(0, 0.15, 0.64), ("s1+0.2", 0.17, 0.70)]),
        j("ST", "مبابي", hl=("s1", 1), kf=[(0, 0.5, 0.84), ("s1", 0.5, 0.84), ("s1+0.3", 0.25, 0.74)])],
     "zones": [("cercle", (0.21, 0.72, 0.13), ROUGE, "s1+0.25", 1, "تزاحم"), ("cercle", (0.5, 0.84, 0.12), ROUGE, "s1+0.35", 1, "العمق بلا مرجع")],
     "items": [("s0", "h", "المشكلة الثانية: الهجوم المنظم"), ("s1", "p", "إلتشي وأتلتيكو: مبابي وفينيسيوس في المنطقة نفسها"),
               ("s1+0.3", "p", "مبابي يميل لليسار ← العمق بلا مرجع"), ("s2", "p", "فينيسيوس: هدف واحد في أول 8 مشاركات"),
               ("s2", "p", "استُبدل في المباراتين")]},
    {"type": "terrain", "chip": "فياريال 1-0 ريال مدريد",
     "joueurs": onze({}, pales=("GK", "RB", "RCB", "LCB", "LB", "RDM", "LDM"), sauf=("LW", "RW", "AM", "ST"))
     + [j("LW", "فينيسيوس", kf=[(0, 0.15, 0.64), (0.12, 0.15, 0.64), (0.3, -0.17, 0.55)]),
        j("LW", "ديوماندي", hl=(0.3, 1), kf=[(0, -0.17, 0.72), (0.15, -0.17, 0.72), (0.35, 0.15, 0.64)], a=0.15),
        j("RW", "غولر", a=0.3), j("AM", "بيلينغهام", a=0.32), j("ST", "مبابي", a=0.34)],
     "cartons_xy": [("s1+0.15", (-0.17, 0.55))], "buts": [("s1", (0.15, 0.64))],
     "items": [("s0", "h", "فياريال: القرار"), ("s0", "p", "فينيسيوس على الدكة", "ok", "مقصود"),
               ("s0+0.2", "p", "ديوماندي يسارًا · غولر يمينًا · بيلينغهام في العمق"), ("s1", "p", "ديوماندي يسجل هدف الفوز"),
               ("s1+0.15", "p", "طرد فينيسيوس بعد دخوله ← إيقاف", "ko", "غير مقصود"), ("s1+0.3", "p", "الإيقاف ثبّت ديوماندي في مكانه")]},
    {"type": "barres", "chip": "ديوماندي بالأرقام",
     "graphes": [("المراوغات الناجحة في الليغا", [("لامين يامال", 43, "43"), ("مبابي", 37, "37"), ("ديوماندي", 37, "37")], 0.03, 0.3),
                 ("لكل 90 دقيقة (حسابنا: 905 و1073 و714 دقيقة)", [("لامين يامال", 4.28, "4.3"), ("مبابي", 3.10, "3.1"),
                                                                  ("ديوماندي", 4.66, "4.7")], 0.3, 0.6)],
     "items": [(0.62, "p", "نسبة نجاح تقارب 65%، الأفضل بين أبرز أربعة مراوغين"), ("s1", "quote", "«منتج غير مكتمل»"),
               ("s1", "src", "جوزيه مورينيو · الأرقام: سيرخيو رودريغيث، ماركا")]},
    {"type": "terrain", "chip": "ديوماندي بلا كرة", "horloge": (0.05, "6'"),
     "joueurs": onze(pales=("GK", "RB", "RCB", "LCB", "RDM", "LDM", "RW", "AM", "ST"), sauf=("LW", "LB"))
     + [j("LW", "ديوماندي", hl=(0.05, 1), kf=[(0, 0.15, 0.64), (0.1, 0.15, 0.64), (0.45, 0.24, 0.37)]),
        j((0.45, 0.56), "فالنسيا", adv=True, kf=[(0, 0.45, 0.56), (0.1, 0.45, 0.56), (0.42, 0.27, 0.40)]),
        j("LB", "كوكوريا", hl=("s1+0.3", 1), kf=[(0, 0.14, 0.27), ("s1+0.3", 0.14, 0.27), ("s1+0.55", 0.10, 0.50)])],
     "fleches": [(0.1, 0.45, (0.15, 0.64), (0.24, 0.39), OR, -40), ("s1+0.3", "s1+0.55", (0.14, 0.29), (0.10, 0.48), BLANC, 20)],
     "items": [("s0", "h", "قيمته الأكبر بلا كرة"), ("s0", "p", "الدقيقة 6 في ميستايا: ركض نحو 30 مترًا لإجهاض مرتدة"),
               ("s0+0.3", "big", "12", "صراعًا ثنائيًا رابحًا"), ("s1", "p", "يعادل فينيسيوس هجوميًا ويتفوق عليه دفاعيًا"),
               ("s1", "src", "سانتياغو سيغيرو · ماركا"), ("s1+0.3", "p", "← كوكوريا يتحرر للتقدم")]},
    {"type": "terrain", "chip": "المشكلة الثالثة · التحول الدفاعي", "horloge": ("s1", "52'"),
     "joueurs": onze({}, pales=("GK", "RCB", "LCB", "LB", "LDM"), sauf=("RB", "RDM", "RW", "LW", "AM", "ST"))
     + [j("RB", "ترينت", fin="s1+0.2"), j("RDM", "فالفيردي", hl=("s1", 1), kf=[(0, 0.63, 0.40), ("s1+0.15", 0.63, 0.40), ("s1+0.45", 0.86, 0.27)]),
        j("RW", "غولر", kf=[(0, 0.85, 0.64), ("s1+0.25", 0.85, 0.64), ("s1+0.55", 0.63, 0.43)]),
        j("LW", "ديوماندي", kf=[(0, 0.15, 0.64), ("s1+0.25", 0.15, 0.64), ("s1+0.6", 0.85, 0.64)]),
        j("LW", "فينيسيوس", a="s1+0.05", kf=[(0, -0.17, 0.62), ("s1+0.1", -0.17, 0.62), ("s1+0.35", 0.15, 0.64)]),
        j("AM", "بيلينغهام", pale=True), j("ST", "مبابي", pale=True)],
     "fleches": [("s1+0.15", "s1+0.45", (0.63, 0.40), (0.85, 0.29), OR, 30)],
     "items": [("s0", "h", "المشكلة الثالثة: التحول الدفاعي"), ("s0", "p", "من يحمي الأروقة عند فقدان الكرة؟"),
               ("s1", "p", "فياريال، الدقيقة 52: فينيسيوس بدل ترينت"), ("s1+0.15", "p", "فالفيردي ← ظهير أيمن"),
               ("s2", "p", "تعديل في منتصف المباراة صار قاعدة")]},
    {"type": "terrain", "chip": "إشبيلية · خيار ثابت",
     "joueurs": [p | ({"hl": (0.05, 1), "pale": False} if p["l"] == "فالفيردي" else {}) for p in onze(pales="tous")]
     + [j((-0.17, 0.36), "ترينت", a=0.15, pale=True), j((-0.17, 0.24), "دمفريز", a=0.18, pale=True)],
     "items": [("s0", "h", "إشبيلية: خيار ثابت"), ("s0", "p", "فالفيردي أساسي ظهيرًا رغم جاهزية ترينت ودمفريز"),
               ("s0+0.2", "big", "6", "استعادات"), ("s0+0.3", "big", "5", "مواجهات فردية رابحة · الأعلى في الفريق"),
               ("s1", "quote", "«سلاحًا نوويًا»"), ("s1", "src", "أغوستين مارتين · آس")]},
    {"type": "liste", "chip": "قراءتي", "titre": "لماذا اتخذ مورينيو هذا القرار؟",
     "items": [("s2", "أفضل دفاعيًا من ترينت ودمفريز"), ("s3", "مخزون بدني للصعود والعودة على الرواق طوال المباراة"),
               ("s4", "الأهم: ما يحدث حين يملك الفريق الكرة")]},
    {"type": "terrain", "chip": "قراءتي · الجهة اليمنى",
     "couloirs": [(1, "s0+0.1")],
     "joueurs": [p for p in onze(pales="tous", sauf=("RW", "RB"))]
     + [j("RW", "غولر", hl=(0, 1), kf=[(0, 0.85, 0.64), ("s0+0.1", 0.85, 0.64), ("s0+0.45", 0.71, 0.70)]),
        j("RB", "فالفيردي", hl=("s1", 1), kf=[(0, 0.86, 0.27), ("s1", 0.86, 0.27), ("s1+0.35", 0.94, 0.74)])],
     "fleches": [("s0+0.1", "s0+0.45", (0.85, 0.64), (0.73, 0.69), OR, 15), ("s1", "s1+0.35", (0.86, 0.29), (0.94, 0.71), BLANC, -25)],
     "items": [("s0", "h", "غولر: رقم 10 في الأصل"), ("s0+0.1", "p", "يدخل نحو نصف المساحة اليمنى"), ("s1", "p", "خلفه: ظهير سريع وقوي"),
               ("s1+0.1", "p", "تقدم متكرر من الخارج"), ("s1+0.25", "p", "يلتزم بخط التماس ← عرض الملعب")]},
    {"type": "terrain", "chip": "قراءتي · الممرات الخمسة",
     "couloirs": [(0, 0.08), (1, 0.24), (2, 0.42), (3, 0.6), (4, 0.76)],
     "joueurs": onze(pales="tous", sauf=("RB", "RW", "ST", "AM", "LW"))
     + [j((0.91, 0.72), "فالفيردي", a=0.08, hl=(0.08, 1)), j((0.71, 0.74), "غولر", a=0.24, hl=(0.24, 1)),
        j((0.5, 0.84), "مبابي", a=0.42, hl=(0.42, 1)), j((0.29, 0.74), "بيلينغهام", a=0.6, hl=(0.6, 1)),
        j((0.09, 0.72), "ديوماندي", a=0.76, hl=(0.76, 1))],
     "items": [(0, "h", "هيكل يشغل الممرات الخمسة"), (0.08, "p", "خط اليمين: فالفيردي"), (0.24, "p", "نصف المساحة اليمنى: غولر"),
               (0.42, "p", "العمق: مبابي"), (0.6, "p", "نصف المساحة اليسرى: بيلينغهام"), (0.76, "p", "خط اليسار: ديوماندي")]},
    {"type": "panneau", "chip": "تلتقي مع قراءتي",
     "items": [(0.02, "quote", "«لاعب-منظومة»"), (0.02, "src", "سانتياغو سيغيرو · ماركا"),
               (0.3, "chips", ["صلابة دمفريز", "تقدم ترينت", "بناء من الخلف"]),
               (0.7, "p", "مع غولر على اليمين: توازن لفريق اعتاد الميل إلى اليسار منذ سنوات")]},
    {"type": "panneau", "chip": "أمام فالنسيا",
     "items": [("s0", "big", "1", "هدف الافتتاح"), ("s0+0.2", "big", "50/55", "تمريرة صحيحة · هوسكورد"),
               ("s1", "quote", "«أفضل ظهير أيمن في العالم، أو على الأقل الأكثر اكتمالًا»"), ("s1", "src", "ماركا")]},
    {"type": "terrain", "chip": "بلا كرة · الضغط",
     "joueurs": onze(pales="tous", sauf=("AM", "LW"))
     + [j((0.62, 0.86), adv=True, a=0.02), j((0.38, 0.90), adv=True, a=0.02),
        j("AM", "بيلينغهام", hl=(0.4, 1), kf=[(0, 0.5, 0.62), (0.42, 0.5, 0.62), (0.62, 0.6, 0.81)]),
        j("LW", "ديوماندي", hl=(0.15, 1), kf=[(0, 0.15, 0.64), (0.18, 0.15, 0.64), (0.38, 0.32, 0.86)])],
     "ballons": [(0.02, (0.64, 0.88))],
     "fleches": [(0.18, 0.38, (0.15, 0.64), (0.34, 0.85), OR, -30), (0.42, 0.62, (0.5, 0.62), (0.6, 0.83), OR, 20)],
     "items": [(0, "h", "بلا كرة: مجهود جماعي"), (0.18, "p", "ديوماندي يضغط متقدمًا"), (0.42, "p", "بيلينغهام: ضغط مضاد لا يتوقف"),
               (0.42, "src", "مانجينغ مدريد"), (0.72, "p", "الكلاسيكو: تعديل مقاربة الضغط خلال المباراة")]},
    {"type": "terrain", "chip": "أيك 2-3 ريال مدريد · رسم توضيحي",
     "joueurs": onze({}, pales="tous", sauf=("RW", "AM", "LW", "ST"))
     + [j((0.18, 0.78), "فينيسيوس", a=0.05, hl=(0.05, 1)), j((0.5, 0.84), "مبابي", a=0.08, hl=(0.05, 1)),
        j((0.82, 0.78), "ديوماندي", a=0.11, hl=(0.05, 1))],
     "zones": [("rect", (0.12, 0.47, 0.88, 0.68), ROUGE, 0.35, 1, "خلل في التوازن")],
     "items": [(0, "h", "أثينا: تجربة الثلاثة مهاجمين"), (0.1, "p", "لإشراك فينيسيوس من دون إخراج ديوماندي"),
               (0.45, "quote", "«انهيار شامل»"), (0.45, "src", "خيسوس غاييغو · آس")]},
    {"type": "barres", "chip": "الثمن",
     "graphes": [("أهداف مستقبلة في المباراة الواحدة", [("دوري الأبطال (7 في 4)", 1.75, "1.75"), ("الليغا (10 في 12)", 0.83, "0.83")],
                  0.03, 0.4)],
     "items": [("s1", "p", "الاعتماد على برناردو للخروج بالكرة"), ("s1+0.2", "p", "فقدان فالفيردي في الوسط")]},
    {"type": "terrain", "chip": "التشكيلة اليوم",
     "joueurs": [p | {"a": 0.02 + i * 0.03} for i, p in enumerate(onze())],
     "items": [("s0", "h", "التشكيلة اليوم"), ("s1", "p", "لا ظهير متخصص · لا فينيسيوس"), ("s2", "p", "3 مشكلات ← 3 إجابات"),
               ("s2+0.2", "p", "قراءتي: التوازن قبل الأسماء")]},
    {"type": "duel", "chip": "السؤال"},
    {"type": "sources", "chip": "المصادر"},
]


# ---------- voix ----------
def tweets():
    blocs = THREAD.read_text(encoding="utf-8").split("\n---\n")[1:]
    return [b.strip() for b in blocs]


def texte_parle(t):
    for a, b in VOIX_REMPLACE.items():
        t = t.replace(a, b)
    return t


async def synthese(i, texte, mp3, js):
    c = edge_tts.Communicate(texte, VOIX, rate="+5%")
    phrases = []
    with open(mp3, "wb") as f:
        async for ch in c.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "SentenceBoundary":
                phrases.append({"debut": ch["offset"] / 1e7, "texte": ch["text"]})
    js.write_text(json.dumps(phrases, ensure_ascii=False), encoding="utf-8")


def duree(mp3):
    return float(subprocess.check_output([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)]))


def preparer_voix():
    (ICI / "audio").mkdir(exist_ok=True)
    infos = []
    for i, t in enumerate(tweets()):
        mp3, js = ICI / "audio" / f"{i:02d}.mp3", ICI / "audio" / f"{i:02d}.json"
        if not mp3.exists() or not js.exists():
            asyncio.run(synthese(i, texte_parle(t), mp3, js))
        infos.append({"mp3": mp3, "duree": duree(mp3), "phrases": json.loads(js.read_text(encoding="utf-8"))})
    return infos


# ---------- rendu d'une image ----------
class Seg:
    def __init__(self, spec, info, debut_global, total):
        self.spec, self.info = spec, info
        self.d = info["duree"] + PAD
        self.debut_global, self.total = debut_global, total
        self.base = fond()
        bd = ImageDraw.Draw(self.base)
        entete(bd, spec["chip"])
        if spec["type"] == "terrain":
            dessiner_terrain(bd)

    def T(self, spec):
        """Temps en fraction du segment : nombre, 'sN' (début de la phrase N) ou 'sN+0.2'."""
        if not isinstance(spec, str):
            return spec
        base, _, dec = spec.partition("+")
        ph = self.info["phrases"]
        n = min(int(base[1:]), len(ph) - 1)
        return min(ph[n]["debut"] / self.d + float(dec or 0), 0.98)

    def image(self, t):
        """Image au temps t (fraction 0..1 du segment)."""
        im = self.base.copy()
        calque = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dc = ImageDraw.Draw(calque)
        d = ImageDraw.Draw(im)
        ty = self.spec["type"]
        if ty == "terrain":
            self.terrain(d, dc, t)
            im.alpha_composite(calque)
            d = ImageDraw.Draw(im)
            self.joueurs(d, t)
            self.items(d, t, x=1830, maxw=1020, y=160)
        elif ty == "titre":
            self.titre(d, t)
        elif ty == "barres":
            self.barres(d, t)
        elif ty == "liste":
            self.liste(d, t)
        elif ty == "panneau":
            self.items(d, t, x=W / 2, maxw=1500, y=210, align="c", grand=True)
        elif ty == "duel":
            self.duel(d, t)
        elif ty == "sources":
            self.sources(d, t)
        self.soustitre(d, t)
        g = (self.debut_global + t * self.d) / self.total
        d.rectangle([0, 0, W * g, 7], fill=OR)
        return im.convert("RGB")

    # --- terrain ---
    def terrain(self, d, dc, t):
        s = self.spec
        for idx, t0 in s.get("couloirs", []):
            a = lisse((t - self.T(t0)) / 0.06)
            if a > 0:
                bornes = [(0.8, 1.0), (0.63, 0.8), (0.37, 0.63), (0.2, 0.37), (0.0, 0.2)][idx]
                (x0, y0), (x1, y1) = pp(bornes[0], 1), pp(bornes[1], 0.5)
                dc.rectangle([x0, y0, x1, y1], fill=OR + (int((95 if idx in (1, 3) else 50) * a),))  # demi-espaces plus marqués
                dc.line([x0, y0, x0, y1], fill=OR + (int(200 * a),), width=2)
                dc.line([x1, y0, x1, y1], fill=OR + (int(200 * a),), width=2)
        for forme, c, coul, t0, t1, lab in s.get("zones", []):
            a = lisse((t - self.T(t0)) / 0.06) * (1 - lisse((t - self.T(t1)) / 0.05))
            if a <= 0:
                continue
            if forme == "rect":
                (x0, y0), (x1, y1) = pp(c[0], c[3]), pp(c[2], c[1])
                dc.rectangle([x0, y0, x1, y1], fill=coul + (int(60 * a),), outline=coul + (int(255 * a),), width=3)
                lx, ly = (x0 + x1) / 2, y0 + 8
            else:
                (cx, cy), r = pp(c[0], c[1]), c[2] * PW
                dc.ellipse([cx - r, cy - r, cx + r, cy + r], fill=coul + (int(55 * a),), outline=coul + (int(255 * a),), width=4)
                lx, ly = cx, cy - r - 40
            if lab:
                f = police(26)
                v = ar(lab)
                dc.text((lx - f.getlength(v) / 2, ly), v, font=f, fill=BLANC + (int(255 * a),))
        for t0, t1, a_, b_, coul, pli in s.get("fleches", []):
            p = lisse((t - self.T(t0)) / max(self.T(t1) - self.T(t0), 0.01))
            fleche(d, courbe(a_, b_, pli), p, coul, tirets=coul == BLANC)
        for t0, poste in s.get("cartons", []):
            if t >= self.T(t0):
                x, y = pp(*P[poste])
                carton(d, x + 30, y - 30)
        for t0, xy in s.get("cartons_xy", []):
            if t >= self.T(t0):
                x, y = pp(*xy)
                carton(d, x + 30, y - 30)
        for t0, xy in s.get("buts", []):  # but : ballon à côté du buteur
            if t >= self.T(t0):
                x, y = pp(*xy)
                ballon(d, x + 32, y - 32, 13)
        for t0, xy in s.get("ballons", []):
            if t >= self.T(t0):
                ballon(d, *pp(*xy))
        if "horloge" in s and t >= self.T(s["horloge"][0]):
            f = police(44)
            v = s["horloge"][1]
            d.rounded_rectangle([PX0 + PW - 130, PY0 + 12, PX0 + PW - 12, PY0 + 74], radius=10, fill=NAVY2, outline=OR, width=2)
            d.text((PX0 + PW - 71 - f.getlength(v) / 2, PY0 + 14), v, font=f, fill=OR)
        if any(x < 0 for jj in s.get("joueurs", []) for _, x, _ in jj["kf"]):
            f = police(24)
            v = ar("الدكة")
            d.text((PX0 - 0.17 * PW - f.getlength(v) / 2, PY0 + 0.25 * PH), v, font=f, fill=DOUX)

    def position(self, kf, t):
        kf = [(self.T(a), x, y) for a, x, y in kf]
        if t <= kf[0][0]:
            return kf[0][1:]
        for (t0, x0, y0), (t1, x1, y1) in zip(kf, kf[1:]):
            if t <= t1:
                k = lisse((t - t0) / max(t1 - t0, 1e-6))
                return x0 + (x1 - x0) * k, y0 + (y1 - y0) * k
        return kf[-1][1:]

    def joueurs(self, d, t):
        for jj in self.spec.get("joueurs", []):
            a = lisse((t - self.T(jj.get("a", 0))) / 0.04) if "a" in jj else 1
            if "fin" in jj:
                a *= 1 - lisse((t - self.T(jj["fin"])) / 0.05)
            if a <= 0:
                continue
            x, y = pp(*self.position(jj["kf"], t))
            hl = "hl" in jj and self.T(jj["hl"][0]) <= t <= self.T(jj["hl"][1]) + 0.01
            coul = ROUGE if jj.get("adv") else (GRIS if jj.get("pale") and not hl else BLANC)
            coul = melange(NAVY, coul, a)
            r = 22 * (0.6 + 0.4 * a)
            if hl:
                d.ellipse([x - r - 9, y - r - 9, x + r + 9, y + r + 9], outline=OR, width=4)
            d.ellipse([x - r, y - r, x + r, y + r], fill=coul, outline=NAVY2, width=3)
            nom = jj["l"]
            for tl, lab in jj.get("labels", []):
                if t >= self.T(tl):
                    nom = lab
            if nom:
                f = police(24 if hl or not jj.get("pale") else 21)
                v = ar(nom)
                lx, ly = x - f.getlength(v) / 2, y + r + 4
                d.text((lx + 2, ly + 2), v, font=f, fill=NAVY2)
                d.text((lx, ly), v, font=f, fill=melange(NAVY, BLANC if not jj.get("pale") or hl else DOUX, a))

    # --- panneau de texte (à droite du terrain, ou centré) ---
    def items(self, d, t, x, maxw, y, align="r", grand=False):
        k = 1.25 if grand else 1
        precedent, decal = None, 0
        for it in self.spec.get("items", []):
            t0 = self.T(it[0])
            decal = decal + 0.025 if t0 == precedent else 0  # éléments lancés ensemble : légèrement décalés
            precedent = t0
            a = lisse((t - t0 - decal) / 0.05)
            if a <= 0:
                continue
            st = it[1]
            yy = y + 18 * (1 - a)
            if st == "h":
                y = ecrire(d, x, yy, it[2], int(54 * k), melange(NAVY, OR, a), maxw, align) + 16
            elif st == "p":
                f = police(int(38 * k))
                lignes = couper(it[2], f, maxw - (60 if align == "r" else 0))
                if align == "r":
                    d.rectangle([x - 14, yy + 18 * k, x, yy + 32 * k], fill=melange(NAVY, OR, a))
                ny = ecrire(d, x - (34 if align == "r" else 0), yy, it[2], int(38 * k), melange(NAVY, BLANC, a),
                            maxw - (60 if align == "r" else 0), align)
                if len(it) > 3:
                    ok = it[3] == "ok"
                    fc = police(24)
                    v = ar(it[4])
                    lw = f.getlength(ar(lignes[-1]))
                    cx1 = (x - 34 - lw - 18) if align == "r" else x - lw / 2 - 18
                    cy0 = ny - 38 * k * 1.4 + 6
                    wch = fc.getlength(v) + 28
                    d.rounded_rectangle([cx1 - wch, cy0, cx1, cy0 + 38], radius=19, fill=melange(NAVY, VERT_OK if ok else ROUGE, a))
                    d.text((cx1 - wch + 14, cy0 + 3), v, font=fc, fill=melange(NAVY, NAVY2 if ok else BLANC, a))
                y = ny + 10
            elif st == "big":
                f = police(int(100 * k))
                v = it[2]
                if align == "r":
                    d.text((x - f.getlength(v), yy - 10), v, font=f, fill=melange(NAVY, OR, a))
                    ecrire(d, x - f.getlength(v) - 30, yy + 38 * k, it[3], int(34 * k), melange(NAVY, DOUX, a), maxw - 260, "r")
                    y = yy + 120 * k
                else:
                    d.text((x - f.getlength(v) / 2, yy - 10), v, font=f, fill=melange(NAVY, OR, a))
                    y = ecrire(d, x, yy + 115 * k, it[3], int(36 * k), melange(NAVY, DOUX, a), maxw, "c") + 20
            elif st == "quote":
                y = ecrire(d, x, yy + 10, it[2], int(50 * k), melange(NAVY, BLANC, a), maxw, align) + 2
            elif st == "src":
                y = ecrire(d, x, yy, it[2], int(28 * k), melange(NAVY, DOUX, a), maxw, align, gras=False) + 20
            elif st == "chips":
                f = police(int(34 * k))
                vs = [ar(c) for c in it[2]]
                larg = [f.getlength(v) + 50 for v in vs]
                tot = sum(larg) + 60 * (len(vs) - 1)
                cx = x + tot / 2 if align == "c" else x
                for i, (v, lw) in enumerate(zip(vs, larg)):
                    ai = lisse((t - t0 - i * 0.08) / 0.05)
                    if ai <= 0:
                        break
                    d.rounded_rectangle([cx - lw, yy, cx, yy + 70 * k], radius=35, outline=melange(NAVY, OR, ai), width=3)
                    d.text((cx - lw + 25, yy + 12 * k), v, font=f, fill=melange(NAVY, BLANC, ai))
                    cx -= lw
                    if i < len(vs) - 1:
                        d.text((cx - 42, yy + 8 * k), "+", font=f, fill=melange(NAVY, OR, ai))
                        cx -= 60
                y = yy + 110 * k

    # --- écrans spéciaux ---
    def titre(self, d, t):
        a = lisse(t / 0.08)
        ecrire(d, W / 2, 250, "كيف بنى مورينيو ريال مدريد الحالي؟", 84, melange(NAVY, BLANC, a), 1600, "c")
        for i, (n, lab) in enumerate((("3", "مشكلات"), ("3", "إجابات"), ("8", "انتصارات متتالية"))):
            ai = lisse((t - 0.15 - i * 0.12) / 0.06)
            cx = W / 2 + 480 - i * 480
            f = police(150)
            d.line([cx - 190, 470, cx + 190, 470], fill=melange(NAVY, OR, ai), width=6)
            d.text((cx - f.getlength(n) / 2, 480), n, font=f, fill=melange(NAVY, OR, ai))
            ecrire(d, cx, 680, lab, 40, melange(NAVY, DOUX, ai), 400, "c")
        ap = lisse((t - 0.55) / 0.08)
        ecrire(d, W / 2, 800, "بناء اللعب · الهجوم المنظم · التحول الدفاعي", 40, melange(NAVY, OR, ap), 1600, "c")

    def barres(self, d, t):
        y = 170
        for titre, donnees, t0, t1 in self.spec["graphes"]:
            a = lisse((t - self.T(t0)) / 0.05)
            if a <= 0:
                continue
            y = ecrire(d, 1830, y, titre, 40, melange(NAVY, OR, a), 1600) + 10
            vmax = max(v for _, v, _ in donnees)
            for nom, v, txt in donnees:
                p = lisse((t - self.T(t0)) / max(self.T(t1) - self.T(t0), 0.01))
                lg = 1100 * v / vmax * p
                coul = OR if nom.startswith("ديوماندي") or nom.startswith("دوري") else (150, 168, 196)
                ecrire(d, 1830, y + 4, nom, 34, melange(NAVY, BLANC, a), 400)
                d.rectangle([1830 - 430 - lg, y + 8, 1830 - 430, y + 50], fill=melange(NAVY, coul, a))
                f = police(34)
                d.text((1830 - 450 - lg - f.getlength(txt), y + 6), txt, font=f, fill=melange(NAVY, BLANC, a * p))
                y += 70
            y += 30
        self.items(d, t, x=1830, maxw=1600, y=y + 10)

    def liste(self, d, t):
        ecrire(d, W / 2, 180, self.spec["titre"], 64, BLANC, 1600, "c")
        for i, (t0, txt) in enumerate(self.spec["items"]):
            a = lisse((t - self.T(t0)) / 0.05)
            if a <= 0:
                continue
            y = 360 + i * 170
            d.ellipse([1700, y, 1800, y + 100], fill=melange(NAVY, OR, a))
            f = police(60)
            n = str(i + 1)
            d.text((1750 - f.getlength(n) / 2, y + 8), n, font=f, fill=NAVY2)
            ecrire(d, 1660, y + 18, txt, 46, melange(NAVY, BLANC, a), 1450)

    def duel(self, d, t):
        a = lisse(t / 0.08)
        d.rectangle([W / 2, 130, W - 70, 720], outline=melange(NAVY, BLANC, a), width=3)
        d.rectangle([70, 130, W / 2, 720], outline=melange(NAVY, OR, a), width=3)
        ecrire(d, W * 0.75, 380, "فينيسيوس", 96, melange(NAVY, BLANC, a), 800, "c")
        ecrire(d, W * 0.75, 520, "يعود أساسيًا؟", 44, melange(NAVY, DOUX, a), 800, "c")
        ecrire(d, W * 0.25, 380, "ديوماندي", 96, melange(NAVY, OR, a), 800, "c")
        ecrire(d, W * 0.25, 520, "يبقى على اليسار؟", 44, melange(NAVY, DOUX, a), 800, "c")
        ap = lisse((t - 0.3) / 0.08)
        f = police(160)
        d.ellipse([W / 2 - 110, 400, W / 2 + 110, 620], fill=melange(NAVY, OR, ap))
        d.text((W / 2 - f.getlength("?") / 2, 405), "?", font=f, fill=NAVY2)
        ecrire(d, W / 2, 790, "رأيكم في التعليقات", 52, melange(NAVY, BLANC, ap), 1200, "c")

    def sources(self, d, t):
        ecrire(d, W / 2, 170, "المصادر", 64, OR, 1600, "c")
        lignes = ["ماركا: سانتياغو سيغيرو، سيرخيو رودريغيث", "آس: أغوستين مارتين، خيسوس غاييغو", "مانجينغ مدريد · هوسكورد",
                  "سبورتس إليستريتد · سبورتس مول · إي إس بي إن", "الرسوم التكتيكية: المدريديستا علاء"]
        for i, l in enumerate(lignes):
            a = lisse((t - i * 0.1) / 0.06)
            ecrire(d, W / 2, 310 + i * 110, l, 44, melange(NAVY, BLANC if i < 4 else DOUX, a), 1600, "c")

    def soustitre(self, d, t):
        sec = t * self.d
        ph = [p for p in self.info["phrases"] if p["debut"] <= sec + 0.05]
        if not ph or sec > self.info["duree"] + 0.2:
            return
        d.rectangle([0, 950, W, H], fill=NAVY2)
        txt = ph[-1]["texte"]
        taille = 34
        while len(couper(txt, police(taille, False), 1740)) > 2 and taille > 26:
            taille -= 2
        ecrire(d, W / 2, 962, txt, taille, BLANC, 1740, "c", gras=False, interligne=1.3)


# ---------- assemblage ----------
def rendre_segment(seg, sortie):
    n = int(round(seg.d * FPS))
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(seg.info["mp3"]), "-af", "apad", "-t", f"{n / FPS:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(sortie)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for k in range(n):
        proc.stdin.write(seg.image(k / n).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit(f"ffmpeg a échoué sur {sortie}")


def main():
    infos = preparer_voix()
    assert len(infos) == len(SEGMENTS), f"{len(infos)} tweets pour {len(SEGMENTS)} segments"
    total = sum(i["duree"] + PAD for i in infos)
    segs, debut = [], 0.0
    for spec, info in zip(SEGMENTS, infos):
        segs.append(Seg(spec, info, debut, total))
        debut += info["duree"] + PAD
    if "--apercu" in sys.argv:
        k = int(sys.argv[sys.argv.index("--apercu") + 1])
        segs[k].image(0.75).save(ICI / f"apercu-{k:02d}.png")
        print(f"apercu-{k:02d}.png ({segs[k].d:.1f} s)")
        return
    (ICI / "segments").mkdir(exist_ok=True)
    liste = []
    for k, seg in enumerate(segs):
        out = ICI / "segments" / f"{k:02d}.mp4"
        print(f"segment {k + 1}/{len(segs)} ({seg.d:.1f} s)", flush=True)
        rendre_segment(seg, out)
        liste.append(f"file '{out.as_posix()}'")
    (ICI / "segments" / "liste.txt").write_text("\n".join(liste), encoding="utf-8")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(ICI / "segments" / "liste.txt"),
                    "-c", "copy", "-movflags", "+faststart", str(ICI / "mourinho.mp4")], check=True)
    print(f"mourinho.mp4 : {total / 60:.1f} min")


if __name__ == "__main__":
    main()

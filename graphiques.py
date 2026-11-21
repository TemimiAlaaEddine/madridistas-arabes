"""Graphiques d'après-match (PNG 1200×900, arabe) tirés des données Sofascore gardées par match.py, à joindre au thread.

Usage : python graphiques.py matchs/<dossier>     (refait les PNG de ce match)
Appelé par match.py après chaque récupération. Rendu : page HTML/SVG capturée par Edge (ou Chrome) sans fenêtre, comme les
couvertures. Couleurs validées (skill dataviz, fond #0a1628) : Real Madrid or, adversaire bleu, xA violet.
"""
import json
import subprocess
import sys
import time
from html import escape as e
from pathlib import Path

from couvertures import COUV_POLICES, EDGE

L, H = 1200, 900
FOND, LIGNE, TEXTE, DOUX, GRILLE = "#0a1628", "#13233d", "#ffffff", "#9fb0c8", "#24344f"
RM, ADV, XA = "#b08d1e", "#4f8ae6", "#9b72d9"
REAL = 2829
COMPARAISON = [("ballPossession", "الاستحواذ", "%"), ("expectedGoals", "الأهداف المتوقعة", ""), ("totalShotsOnGoal", "التسديدات", ""),
               ("shotsOnGoal", "على المرمى", ""), ("bigChanceCreated", "فرص محققة", ""), ("touchesInOppBox", "لمسات في منطقة الخصم", ""),
               ("accuratePasses", "تمريرات صحيحة", "")]


def ar(equipe):
    return (equipe.get("fieldTranslations") or {}).get("nameTranslation", {}).get("ar") or equipe["name"]


def nom_court(joueur):
    """« ت. كورتوا » -> « كورتوا » (nom arabe de Sofascore), sinon le nom latin."""
    t = (joueur.get("fieldTranslations") or {}).get("shortNameTranslation", {}).get("ar") or joueur.get("shortName") or joueur["name"]
    return t.split(". ", 1)[-1]


def page(titre, sous_titre, corps, source="سوفاسكور"):
    return f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">{COUV_POLICES}<style>
body{{margin:0;width:{L}px;height:{H}px;overflow:hidden;background:{FOND};color:{TEXTE};font-family:Cairo,Tahoma,sans-serif}}
.cadre{{box-sizing:border-box;height:100%;padding:44px 56px 32px;display:flex;flex-direction:column}}
h1{{margin:0;font-size:44px;font-weight:700;line-height:1.3}} .sous{{margin:2px 0 0;color:{DOUX};font-size:24px}}
.corps{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:22px}}
.pied{{display:flex;justify-content:space-between;color:{DOUX};font-size:20px}} .pied b{{color:{RM};font-weight:600;direction:ltr}}
.legende{{display:flex;gap:32px;font-size:22px;color:{TEXTE};white-space:nowrap;align-self:flex-start}} .legende i{{display:inline-block;width:18px;height:18px;border-radius:4px;margin-left:8px;vertical-align:-2px}}
svg text{{font-family:Cairo,Tahoma,sans-serif}}
</style></head><body><div class="cadre"><h1>{e(titre)}</h1><p class="sous">{e(sous_titre)}</p>
<div class="corps">{corps}</div><div class="pied"><span>المصدر: {e(source)}</span><b>@ElMadridistAlaa</b></div></div></body></html>"""


def legende(*paires):
    return '<div class="legende">' + "".join(f'<span><i style="background:{c}"></i>{e(n)}</span>' for n, c in paires) + "</div>"


def comparaison(stats, rm_dom, noms):
    """Une barre à 100 % par chiffre : part du Real Madrid (à droite) et de l'adversaire (à gauche), valeurs aux extrémités."""
    items = {i["key"]: i for g in next(p for p in stats["statistics"] if p["period"] == "ALL")["groups"] for i in g["statisticsItems"]}
    lignes, y, larg = [], 10, 1000
    for cle, libelle, unite in COMPARAISON:
        if cle not in items:
            continue
        i = items[cle]
        rm, adv = (i["homeValue"], i["awayValue"]) if rm_dom else (i["awayValue"], i["homeValue"])
        total = (rm + adv) or 1
        w_rm = max(round(larg * rm / total), 6) if rm else 0
        fmt = (lambda v: f"{v:.2f}") if cle == "expectedGoals" else (lambda v: f"{v:g}{unite}")
        lignes.append(f'<text x="{larg/2}" y="{y+22}" text-anchor="middle" fill="{DOUX}" font-size="22">{e(libelle)}</text>'
                      f'<rect x="0" y="{y+36}" width="{larg}" height="30" rx="4" fill="{ADV}"/>'
                      f'<rect x="{larg-w_rm}" y="{y+36}" width="{w_rm}" height="30" rx="4" fill="{RM}" stroke="{FOND}" stroke-width="2"/>'
                      f'<text x="{larg}" y="{y+22}" text-anchor="end" fill="{TEXTE}" font-size="26" font-weight="700">{e(fmt(rm))}</text>'
                      f'<text x="0" y="{y+22}" text-anchor="start" fill="{TEXTE}" font-size="26" font-weight="700">{e(fmt(adv))}</text>')
        y += 86
    svg = f'<svg width="{larg}" height="{y}" viewBox="0 0 {larg} {y}" direction="ltr">{"".join(lignes)}</svg>'
    return legende((noms[0], RM), (noms[1], ADV)) + svg


def chronologie(tirs, rm_dom, noms, officiel):
    """xG cumulé minute par minute (marches), un trait par équipe, les buts marqués d'un point."""
    lw, lh, g, b, gauche = 1040, 600, 50, 50, 60
    fin = max([90] + [t["time"] for t in tirs])
    series = {True: [(0, 0)], False: [(0, 0)]}  # True = Real Madrid
    buts = []
    for t in sorted(tirs, key=lambda t: (t["time"], t.get("addedTime", 0))):
        cote = t["isHome"] == rm_dom
        x, cumul = t["time"], series[cote][-1][1] + (t.get("xg") or 0)
        series[cote].append((x, cumul))
        if t["shotType"] == "goal" and t.get("goalType") != "own":
            buts.append((cote, x, cumul, nom_court(t["player"])))
    ymax = max(0.5, *(s[-1][1] for s in series.values())) * 1.15
    X = lambda m: gauche + (lw - gauche - 120) * m / fin
    Y = lambda v: g + (lh - g - b) * (1 - v / ymax)
    traits = [f'<line x1="{gauche}" x2="{lw-120}" y1="{Y(v)}" y2="{Y(v)}" stroke="{GRILLE}" stroke-width="1"/>'
              f'<text x="{gauche-12}" y="{Y(v)+7}" text-anchor="end" fill="{DOUX}" font-size="20">{v:g}</text>'
              for v in [k / 2 for k in range(int(ymax * 2) + 1)]]
    traits += [f'<text x="{X(m)}" y="{lh-b+34}" text-anchor="middle" fill="{DOUX}" font-size="20">{m}\'</text>' for m in range(0, fin + 1, 15)]
    for cote, couleur, nom in ((False, ADV, noms[1]), (True, RM, noms[0])):
        pts = series[cote] + [(fin, series[cote][-1][1])]
        d = f"M{X(0)},{Y(0)}" + "".join(f" H{X(m)} V{Y(v)}" for m, v in pts[1:])
        traits.append(f'<path d="{d}" fill="none" stroke="{couleur}" stroke-width="3" stroke-linejoin="round"/>')
        traits.append(f'<text x="{X(fin)+12}" y="{Y(pts[-1][1])+8}" fill="{TEXTE}" font-size="24" font-weight="700">{officiel[cote]:.2f}</text>')  # total officiel : la somme des tirs diffère d'un arrondi
    for cote, m, v, qui in buts:
        traits.append(f'<circle cx="{X(m)}" cy="{Y(v)}" r="9" fill="{RM if cote else ADV}" stroke="{FOND}" stroke-width="2"/>'
                      f'<text x="{X(m)}" y="{Y(v)-18}" text-anchor="middle" fill="{TEXTE}" font-size="20">{e(qui)} د{m}</text>')
    svg = f'<svg width="{lw}" height="{lh}" viewBox="0 0 {lw} {lh}" direction="ltr">{"".join(traits)}</svg>'
    return legende((noms[0], RM), (noms[1], ADV)) + svg


def carte_tirs(tirs, rm_dom, xg_officiel):
    """Demi-terrain (but en haut) : un rond par tir du Real Madrid, taille selon l'xG, plein si but."""
    k, m = 9, 30  # 9 px par mètre, marge
    lw, lh = 68 * k + 2 * m, 52.5 * k + 2 * m
    X = lambda y_pct: m + 68 * k * y_pct / 100
    Y = lambda x_pct: m + 105 * k * x_pct / 100
    trait = f'stroke="{GRILLE}" stroke-width="3" fill="none"'
    terrain = [f'<rect x="{m}" y="{m}" width="{68*k}" height="{52.5*k}" {trait}/>',
               f'<rect x="{m+(68-40.32)/2*k}" y="{m}" width="{40.32*k}" height="{16.5*k}" {trait}/>',
               f'<rect x="{m+(68-18.32)/2*k}" y="{m}" width="{18.32*k}" height="{5.5*k}" {trait}/>',
               f'<rect x="{m+(68-7.32)/2*k}" y="{m-12}" width="{7.32*k}" height="12" {trait}/>',
               f'<circle cx="{m+34*k}" cy="{m+11*k}" r="4" fill="{GRILLE}"/>',
               f'<path d="M{m+(34-7.3)*k},{m+16.5*k} A{9.15*k},{9.15*k} 0 0 0 {m+(34+7.3)*k},{m+16.5*k}" {trait}/>',
               f'<path d="M{m+(34-9.15)*k},{m+52.5*k} A{9.15*k},{9.15*k} 0 0 1 {m+(34+9.15)*k},{m+52.5*k}" {trait}/>']
    ronds = []
    for t in sorted((t for t in tirs if t["isHome"] == rm_dom), key=lambda t: -(t.get("xg") or 0)):  # gros ronds dessous
        r = 8 + 34 * (t.get("xg") or 0) ** 0.5
        c = t["playerCoordinates"]
        style = f'fill="{RM}" stroke="{FOND}" stroke-width="2"' if t["shotType"] == "goal" else f'fill="{RM}" fill-opacity="0.18" stroke="{RM}" stroke-width="2.5"'
        ronds.append(f'<circle cx="{X(c["y"]):.1f}" cy="{Y(c["x"]):.1f}" r="{r:.1f}" {style}/>')
    rm = [t for t in tirs if t["isHome"] == rm_dom]
    resume = f"{len(rm)} تسديدة · {sum(t['shotType'] == 'goal' for t in rm)} أهداف · {xg_officiel:.2f} هدف متوقع"
    svg = f'<svg width="{lw:.0f}" height="{lh:.0f}" viewBox="0 0 {lw:.0f} {lh:.0f}">{"".join(terrain + ronds)}</svg>'
    leg = (f'<div class="legende"><span><i style="background:{RM};border-radius:50%"></i>هدف</span>'
           f'<span><i style="background:transparent;border:2.5px solid {RM};border-radius:50%;box-sizing:border-box"></i>تسديدة</span>'
           f'<span style="color:{DOUX}">حجم الدائرة = قيمة الهدف المتوقع</span></div>')
    return resume, f'<div style="display:flex;flex-direction:column;align-items:center">{leg}{svg}</div>'


def joueurs(compos, rm_dom):
    """xG + xA des joueurs du Real Madrid (barres empilées depuis la droite), les 7 plus dangereux."""
    lst = [(nom_court(p["player"]), (p.get("statistics") or {}).get("expectedGoals", 0), (p.get("statistics") or {}).get("expectedAssists", 0))
           for p in compos["home" if rm_dom else "away"]["players"]]
    lst = sorted((j for j in lst if j[1] + j[2] > 0), key=lambda j: -(j[1] + j[2]))[:7]
    lw, lab, ligne = 1040, 220, 74
    vmax = max(j[1] + j[2] for j in lst) * 1.18
    W = lambda v: (lw - lab - 20) * v / vmax
    barres = []
    for k, (n, xg, xa) in enumerate(lst):
        y, droite = 10 + k * ligne, lw - lab - 20
        barres.append(f'<text x="{lw}" y="{y+36}" text-anchor="end" fill="{TEXTE}" font-size="28" font-weight="600">{e(n)}</text>')
        barres.append(f'<rect x="{droite-W(xg):.1f}" y="{y+10}" width="{max(W(xg), 0):.1f}" height="38" rx="4" fill="{RM}"/>')
        barres.append(f'<rect x="{droite-W(xg)-W(xa):.1f}" y="{y+10}" width="{max(W(xa), 0):.1f}" height="38" rx="4" fill="{XA}" stroke="{FOND}" stroke-width="2"/>')
        barres.append(f'<text x="{droite-W(xg)-W(xa)-12:.1f}" y="{y+38}" text-anchor="end" fill="{DOUX}" font-size="22">{xg+xa:.2f}</text>')
    h = 20 + len(lst) * ligne
    svg = f'<svg width="{lw}" height="{h}" viewBox="0 0 {lw} {h}" direction="ltr">{"".join(barres)}</svg>'
    return legende(("أهداف متوقعة (xG)", RM), ("تمريرات حاسمة متوقعة (xA)", XA)) + svg


def rendre(html, png):
    src = png.with_suffix(".html")
    src.write_text(html, encoding="utf-8")
    png.unlink(missing_ok=True)
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={png.parent / 'profil'}",
                    "--virtual-time-budget=5000", f"--window-size={L},{H}", f"--screenshot={png}", src.as_uri()],
                   capture_output=True, timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    fin = time.time() + 60  # msedge.exe rend la main avant que son processus enfant ait écrit l'image
    while not png.exists() and time.time() < fin:
        time.sleep(0.5)
    time.sleep(0.5)
    return png.exists()


def generer(dossier):
    """Fait les PNG dans <dossier>/graphiques/ ; retourne [(fichier, ce qu'il montre)]."""
    d = json.loads((Path(dossier) / "sofascore.json").read_text(encoding="utf-8"))
    evt, rm_dom = d["event"], d["event"]["homeTeam"]["id"] == REAL
    adv = ar(evt["awayTeam"] if rm_dom else evt["homeTeam"])
    noms = ("ريال مدريد", adv)
    score = f"{ar(evt['homeTeam'])} {evt['homeScore'].get('current', '')}-{evt['awayScore'].get('current', '')} {ar(evt['awayTeam'])}"
    sortie = Path(dossier).resolve() / "graphiques"
    sortie.mkdir(exist_ok=True)
    items = {i["key"]: i for g in next(p for p in d["statistics"]["statistics"] if p["period"] == "ALL")["groups"] for i in g["statisticsItems"]}
    xg = items.get("expectedGoals", {})
    officiel = {True: xg.get("homeValue" if rm_dom else "awayValue", 0), False: xg.get("awayValue" if rm_dom else "homeValue", 0)}
    a_faire = [("comparaison", "مقارنة الأرقام", score, comparaison(d["statistics"], rm_dom, noms),
                "barres à 100 % : possession, xG, tirs, cadrés, grosses occasions, touches dans la surface, passes réussies")]
    tirs = d.get("shotmap") or []
    if tirs:
        a_faire.append(("xg", "تطور الأهداف المتوقعة", f"{score} · مجموع الأهداف المتوقعة دقيقة بدقيقة", chronologie(tirs, rm_dom, noms, officiel),
                        "xG cumulé des deux équipes minute par minute, buts marqués"))
        resume, corps = carte_tirs(tirs, rm_dom, officiel[True])
        a_faire.append(("tirs", "خريطة تسديدات ريال مدريد", resume, corps, "position de chaque tir du Real Madrid, taille = xG, plein = but"))
    if d.get("lineups"):
        a_faire.append(("joueurs", "الأخطر في ريال مدريد", "الأهداف المتوقعة والتمريرات الحاسمة المتوقعة لكل لاعب", joueurs(d["lineups"], rm_dom),
                        "xG + xA des 7 joueurs du Real Madrid les plus dangereux"))
    faits = []
    for nom, titre, sous, corps, quoi in a_faire:
        if rendre(page(titre, sous, corps), sortie / f"{nom}.png"):
            faits.append((f"{nom}.png", quoi))
    return faits


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for f, quoi in generer(sys.argv[1]):
        print(f"{f} : {quoi}")

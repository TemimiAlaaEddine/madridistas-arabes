"""Lecture d'un match en 6 étapes : 1. récit, 2. périodes, 3. chaque période, 4. chaque bascule, 5. phases de jeu, 6. joueurs.

Usage : python bascules.py matchs/AAAA-MM-JJ-adversaire   (lancé aussi par match.py)
Sources : les actions Opta de WhoScored sont le squelette ; FotMob (Opta aussi) donne le momentum qui découpe le match en
périodes et l'xG de chaque tir, rattaché par son identifiant (le même dans les deux sites) ; Sofascore sert de secours pour l'xG.
Sans FotMob, les périodes sont les deux mi-temps.
Ce sont des indices chiffrés, pas des conclusions : le score, la fatigue et le contexte peuvent les expliquer.
Coordonnées WhoScored : 0 à 100, chaque équipe attaque vers x = 100. Repères : 16 équipes-matchs du Real (2026-11-22).
"""
import json
import statistics
import sys
from pathlib import Path

import fotmob
import whoscored

# ---------- réglages ----------
DEFENSE = {"Tackle", "Interception", "Challenge", "Foul"}  # actions qui comptent pour le PPDA
RECUP = {"BallRecovery", "Interception", "Tackle"}
BLOC = {"Tackle", "Interception", "BallRecovery", "Challenge", "Foul", "Clearance", "BlockedPass"}  # hauteur du bloc défensif
BLOC_BAS, BLOC_HAUT = 34, 40  # mètres depuis son but : 29 à 45 m sur 8 matchs (Barça 45, AEK 29)
POSSESSION = {"Pass", "BallRecovery", "KeeperPickup", "TakeOn"}  # l'équipe a le ballon ; dégagement, interception, touche : ballon disputé
CPA = {"FromCorner", "SetPiece", "DirectFreekick", "ThrowinSetPiece"}
REMISES = {"GoalKick", "ThrowIn", "FreekickTaken", "CornerTaken", "KickOff"}  # possession qui ne vient pas d'une perte adverse
RAPIDE_SECONDES, RAPIDE_PASSES = 15, 5  # possession rapide : dernier tiers en 15 s et 5 passes au plus (contres WhoScored : 12 s au plus)
TIR_SECONDES = 16  # tir rapide : 16 s et 5 passes au plus (réglé sur 8 matchs : couvre les 21 contres marqués FastBreak par WhoScored)
CPA2_SECONDES = 10  # ballon regagné 10 s au plus après son corner ou coup franc : 2e ballon
CONTRE_PRESSING_SECONDES = 8  # ballon regagné 8 s au plus après la perte (médiane 23 % sur 8 matchs)
LISSAGE, PERIODE_MIN, SEUIL_COUPURE = 5, 8, 8000  # momentum lissé sur 5 min, périodes d'au moins 8 min : 2 à 6 périodes par match
SURFACE = lambda x, y: x >= 83 and 21 <= y <= 79
# nom affiché, écart minimal pour signaler un changement (par 15 min, ou en points de %)
MESURES = {
    "xg": ("xG", 0.3), "tirs": ("tirs", 2), "tiers": ("entrées dans le dernier tiers", 4), "surface": ("passes dans la surface", 2),
    "sorties": ("sorties de sa moitié (passes réussies)", 3), "part": ("part des passes (%)", 8),
    "recup": ("ballons gagnés dans le dernier tiers", 2), "ppda": ("PPDA (bas = pressing fort)", 6),
}


# ---------- préparation ----------
def horloge(d):
    """Temps continu en minutes : la 2e mi-temps commence après les arrêts de jeu de la 1re."""
    fin1 = max((e["minute"] + 1 for e in d["events"] if e["period"]["value"] == 1), default=45)
    extra = max(fin1 - 45, 0)
    return lambda periode, m: m + (extra if periode == 2 else 0), extra


def preparer(d, sofa_tirs=None, fm=None):
    """Actions en temps continu, xG par identifiant de tir (FotMob, sinon Sofascore rapproché par la minute), tirs avec xG."""
    t, extra = horloge(d)
    actions = [dict(e, t=t(e["period"]["value"], e["minute"] + e.get("second", 0) / 60)) for e in d["events"] if e["period"]["value"] in (1, 2)]
    coups = [e for e in actions if e.get("isShot")]
    if fm:
        xg = {s["id"]: s.get("expectedGoals") or 0 for s in (fm["content"].get("shotmap") or {}).get("shots") or []}
    else:
        xg, libres = {}, []
        for s in sofa_tirs or []:  # Sofascore : autre modèle d'xG, rapproché par la minute et le côté
            p = 1 if s["time"] <= 45 else 2
            libres.append({"dom": s["isHome"], "xg": s.get("xg") or 0, "t": (45 + extra if p == 2 else 0) + s.get("periodTimeSeconds", 0) / 60})
        for e in coups:
            dom = e["teamId"] == d["home"]["teamId"]
            proche = min((s for s in libres if s["dom"] == dom), key=lambda s: abs(s["t"] - e["t"]), default=None)
            if proche and abs(proche["t"] - e["t"]) <= 1.5:
                libres.remove(proche)
                xg[int(e["id"])] = proche["xg"]
    tirs = [{"dom": e["teamId"] == d["home"]["teamId"], "xg": xg[int(e["id"])], "t": e["t"]} for e in coups if int(e["id"]) in xg]
    return actions, tirs, xg, extra


def quals(e):
    return {q["type"]["displayName"] for q in e.get("qualifiers", [])}


def score(d, actions, t):
    """Score (domicile, extérieur) avant la minute t ; un but contre son camp compte pour l'autre équipe."""
    s = [0, 0]
    for e in actions:
        if e["type"]["displayName"] == "Goal" and e["t"] < t:
            dom = (e["teamId"] == d["home"]["teamId"]) != ("OwnGoal" in quals(e))
            s[0 if dom else 1] += 1
    return f"{s[0]}-{s[1]}"


def moments(d, actions):
    """Buts, penalties manqués, changements (groupés par équipe et minute), cartons rouges, changements de système."""
    noms = {int(k): v for k, v in d["playerIdNameDictionary"].items()}
    equipes = {d["home"]["teamId"]: d["home"]["name"], d["away"]["teamId"]: d["away"]["name"]}
    liste = []
    for e in actions:
        typ, q = e["type"]["displayName"], quals(e)
        if typ == "Goal":
            quoi = f"but {'contre son camp ' if 'OwnGoal' in q else ''}de {noms.get(e.get('playerId'), '?')}"
        elif e.get("isShot") and "Penalty" in q:
            quoi = f"penalty manqué par {noms.get(e.get('playerId'), '?')}"
        elif typ == "SubstitutionOn":
            quoi = f"entrée de {noms.get(e.get('playerId'), '?')}"
        elif typ == "Card" and q & {"Red", "SecondYellow"}:
            quoi = f"carton rouge pour {noms.get(e.get('playerId'), '?')}"
        elif typ == "FormationChange":
            quoi = "changement de système"
        else:
            continue
        equipe = equipes.get(e["teamId"], "?")
        # changements de la même équipe à 2 minutes près : un seul moment (un but reste un moment à part)
        meme = next((m for m in reversed(liste) if m["equipe"] == equipe and not m["but"] and typ != "Goal" and e["t"] - m["t"] <= 2), None)
        if meme:
            meme["quoi"].append(quoi)
        else:
            liste.append({"t": e["t"], "minute": e["minute"] + 1, "equipe": equipe, "quoi": [quoi], "but": typ == "Goal"})
    return sorted(liste, key=lambda m: m["t"])


# ---------- mesures sur une tranche de temps ----------
def franchissement(actions, equipe, a, b):
    """Passes de sa moitié : réussies vers la moitié adverse (par 15 min), % de réussite, longs ballons."""
    p = [e for e in actions if a <= e["t"] < b and e["teamId"] == equipe and e["type"]["displayName"] == "Pass" and e["x"] < 50]
    ok = [e for e in p if e["outcomeType"]["value"] == 1 and "endX" in e]
    longs = sum("Longball" in quals(e) for e in p)
    return sum(e["endX"] >= 50 for e in ok) / (max(b - a, 1) / 15), 100 * len(ok) / max(len(p), 1), longs


def mesurer(actions, tirs, equipe, dom, a, b):
    """Mesures d'une équipe entre les minutes a et b (temps continu), ramenées à 15 minutes."""
    ev = [e for e in actions if a <= e["t"] < b]
    ok = lambda e: e["outcomeType"]["value"] == 1
    passes = [e for e in ev if e["type"]["displayName"] == "Pass"]
    miennes = [e for e in passes if e["teamId"] == equipe]
    reussies = [e for e in miennes if ok(e) and "endX" in e]
    adv_passes = [e for e in passes if e["teamId"] != equipe and e["x"] <= 60]
    defense = [e for e in ev if e["teamId"] == equipe and e["type"]["displayName"] in DEFENSE and e["x"] >= 40
               and (e["type"]["displayName"] != "Foul" or not ok(e))]
    duree = max(b - a, 1) / 15
    r = {
        "tirs": sum(e["teamId"] == equipe and e.get("isShot", False) for e in ev) / duree,
        "tiers": sum(e["x"] < 66.7 <= e["endX"] for e in reussies) / duree,
        "surface": sum(SURFACE(e["endX"], e["endY"]) for e in reussies) / duree,
        "sorties": franchissement(actions, equipe, a, b)[0],
        "part": 100 * len(miennes) / max(len(passes), 1),
        "recup": sum(e["teamId"] == equipe and e["type"]["displayName"] in RECUP and e["x"] >= 66.7 and ok(e) for e in ev) / duree,
        "ppda": len(adv_passes) / max(len(defense), 1),
    }
    if tirs:
        r["xg"] = sum(s["xg"] for s in tirs if s["dom"] == dom and a <= s["t"] < b) / duree
    return r


def ecarts(avant, apres):
    """Changements nets entre deux mesures : [(clé, avant, après)], du plus fort au plus faible."""
    out = [(k, avant[k], apres[k]) for k in MESURES if k in avant and k in apres and abs(apres[k] - avant[k]) >= MESURES[k][1]
           and abs(apres[k] - avant[k]) >= 0.35 * max(abs(avant[k]), abs(apres[k]))]
    return sorted(out, key=lambda c: -abs(c[2] - c[1]) / max(abs(c[1]), abs(c[2]), 1e-9))


def fmt(k, v):
    return f"{v:.2f}" if k == "xg" else f"{v:.0f}"


def bloc(actions, equipe, a, b):
    """Hauteur moyenne des actions défensives, en mètres depuis son but (terrain de 105 m). Une équipe qui a le ballon défend
    surtout après ses pertes, donc haut : son bloc paraît plus haut, à lire avec le PPDA."""
    xs = [e["x"] for e in actions if a <= e["t"] < b and e["teamId"] == equipe and e["type"]["displayName"] in BLOC
          and (e["type"]["displayName"] != "Foul" or e["outcomeType"]["value"] != 1)]
    return statistics.mean(xs) * 1.05 if xs else None


def contre_pressing(actions, equipe, a, b):
    """Pertes dans la moitié adverse, et combien sont suivies d'une récupération (tacle, interception, récupération, faute) en 8 s."""
    ok = lambda e: e["outcomeType"]["value"] == 1
    ctrl = [e for e in actions if a <= e["t"] < b and ((e["type"]["displayName"] in ("Pass", "TakeOn") and ok(e))
                                                       or e["type"]["displayName"] in ("BallRecovery", "KeeperPickup"))]
    reprise = lambda z: z["teamId"] == equipe and (z["type"]["displayName"] in ("Tackle", "Interception", "BallRecovery") and ok(z)
                                                   or z["type"]["displayName"] == "Foul" and not ok(z))
    pertes = reprises = 0
    for e, f in zip(ctrl, ctrl[1:]):
        # f["x"] <= 50 : l'adversaire prend le ballon dans sa moitié, donc on l'a perdu dans la moitié adverse
        if e["teamId"] == equipe and f["teamId"] != equipe and e["period"]["value"] == f["period"]["value"] and f["x"] <= 50:
            pertes += 1
            reprises += any(reprise(z) for z in actions if f["t"] <= z["t"] <= f["t"] + CONTRE_PRESSING_SECONDES / 60)
    return pertes, reprises


# ---------- possessions ----------
def sequences(actions, xg=None):
    """Possessions : suite d'actions d'une même équipe, coupée quand l'autre touche le ballon. Chaque tir reçoit sa phase."""
    xg, seqs, cur, derniere_cpa = xg or {}, [], None, {}
    for e in actions:
        if e["type"]["displayName"] not in POSSESSION and not e.get("isShot"):
            continue
        q = quals(e)
        relance = bool(q & {"CornerTaken", "FreekickTaken"})
        # une récupération ouvre toujours une possession (2e ballon après un dégagement adverse, par exemple)
        if not cur or relance or e["type"]["displayName"] == "BallRecovery" or e["teamId"] != cur["equipe"] or e["period"]["value"] != cur["periode"]:
            cur = {"equipe": e["teamId"], "periode": e["period"]["value"], "t0": e["t"], "x0": e["x"], "xmax": e["x"], "passes": 0,
                   "recup": e["type"]["displayName"] != "KeeperPickup" and not q & REMISES, "cpa": relance and e["x"] >= 50,
                   "t_tiers": None, "p_tiers": None, "surface": False, "tirs": [], "t_ref": e["t"], "p_ref": 0, "relance_basse": False,
                   "long0": e["type"]["displayName"] == "Pass" and "Longball" in q,
                   "apres_cpa": e["t"] - derniere_cpa.get(e["teamId"], -99) <= CPA2_SECONDES / 60}
            seqs.append(cur)
            if cur["cpa"]:
                derniere_cpa[e["teamId"]] = e["t"]
        cur["t1"] = e["t"]
        if e["x"] < 33.3:  # chrono de l'attaque : depuis la dernière action dans son tiers défensif
            cur["relance_basse"] |= cur["xmax"] >= 50  # ballon revenu de la moitié adverse : nouvelle sortie de balle
            cur["t_ref"], cur["p_ref"] = e["t"], cur["passes"]
        x = max(e["x"], e.get("endX", 0) if e["type"]["displayName"] == "Pass" and e["outcomeType"]["value"] == 1 else 0)
        cur["xmax"] = max(cur["xmax"], x)
        if x >= 66.7 and cur["t_tiers"] is None:
            cur["t_tiers"], cur["p_tiers"] = e["t"], cur["passes"] + 1
        if e["type"]["displayName"] == "Pass" and e["outcomeType"]["value"] == 1:
            cur["passes"] += 1
            cur["surface"] |= SURFACE(e["endX"], e["endY"])
        if e.get("isShot"):
            vite = e["t"] - cur["t_ref"] <= TIR_SECONDES / 60 and cur["passes"] - cur["p_ref"] <= RAPIDE_PASSES
            if "Penalty" in q:
                phase = "penalty"
            elif q & CPA:
                phase = "cpa"
            elif (cur["cpa"] or cur["apres_cpa"]) and not cur["relance_basse"]:
                phase = "cpa2"  # tir dans le jeu, mais la possession vient d'un corner ou coup franc (rejoué, ou 2e ballon)
            elif vite and cur["recup"] and not cur["relance_basse"]:
                phase = "haute" if cur["x0"] >= 66.7 else "transition"
            else:
                phase = "directe" if vite else "placee"
            cur["tirs"].append({"phase": phase, "xg": xg.get(int(e["id"])) if "id" in e else None,
                                "delai": round((e["t"] - cur["t_ref"]) * 60), "passes": cur["passes"] - cur["p_ref"]})
    for s in seqs:
        s["haute"] = s["recup"] and s["x0"] >= 66.7  # ballon gagné dans le dernier tiers : fruit du pressing
        # dernier tiers en 15 s et 5 passes au plus : après une perte adverse = transition, après une remise en jeu = sortie directe
        vite = (not s["haute"] and not s["cpa"] and s["t_tiers"] is not None and s["t_tiers"] - s["t0"] <= RAPIDE_SECONDES / 60
                and s["p_tiers"] <= RAPIDE_PASSES)
        s["rapide"], s["directe"] = vite and s["recup"], vite and not s["recup"]
        s["placee"] = s["xmax"] >= 66.7 and not (s["haute"] or vite or s["cpa"])
    return seqs


# ---------- étape 5 : les 8 phases ----------
def phases(seqs, actions, equipe, a, b, avec_xg):
    """Les 8 phases de la méthode de l'utilisateur, mesurées pour une équipe entre a et b."""
    mes = [s for s in seqs if s["equipe"] == equipe and a <= s["t0"] < b]
    adv = [s for s in seqs if s["equipe"] != equipe and a <= s["t0"] < b]
    pct = lambda n, tot: f"{100 * n / tot:.0f} %" if tot else "-"
    par = lambda n, tot: f"{n / tot:.2f}" if tot else "-"
    nb = lambda ss, ph: sum(x["phase"] == ph for s in ss for x in s["tirs"])

    def tirs(ss, *phases_tir):
        t = [x for s in ss for x in s["tirs"] if x["phase"] in phases_tir]
        return f"{len(t)} tirs" + (f", xG {sum(x['xg'] or 0 for x in t):.2f}" if avec_xg else "")
    jeu = ("transition", "directe", "placee", "haute")
    constr, constr_adv = [s for s in mes if s["x0"] < 33.3], [s for s in adv if s["x0"] < 33.3]
    adversaire = next((s["equipe"] for s in adv), None)
    (f1, r1, _), (f2, _, _) = franchissement(actions, equipe, a, b), franchissement(actions, adversaire, a, b)
    rapides, rapides_adv = [s for s in mes if s["rapide"]], [s for s in adv if s["rapide"]]
    placees, placees_adv = [s for s in mes if s["placee"]], [s for s in adv if s["placee"]]
    hautes, directes = [s for s in mes if s["haute"]], [s for s in mes if s["directe"]]
    recups = [s for s in mes if s["recup"] and not s["haute"]]
    pertes_cp, reprises = contre_pressing(actions, equipe, a, b)
    ppda = mesurer(actions, [], equipe, True, a, b)["ppda"]
    h = bloc(actions, equipe, a, b)
    niveau = "-" if h is None else "bas" if h < BLOC_BAS else "haut" if h > BLOC_HAUT else "médian"
    pertes = [s for s in adv if s["recup"]]  # chaque possession adverse née d'une récupération = une perte de balle
    punies = [x for s in pertes for x in s["tirs"] if x["phase"] in ("transition", "haute")]
    return [
        ("1. construction", f"{len(constr)} possessions parties de son tiers défensif : {pct(sum(s['xmax'] >= 50 for s in constr), len(constr))} passent "
                            f"le milieu (repère 23-57 %), {pct(sum(s['long0'] for s in constr), len(constr))} commencent par une passe longue, "
                            f"{pct(sum(s['passes'] == 0 and not s['tirs'] for s in constr), len(constr))} perdues sans une passe (repère 11-41 %) ; "
                            f"{f1:.1f} sorties de sa moitié par 15 min ({r1:.0f} % de passes réussies dans sa moitié) ; tirs : "
                            + tirs(constr, *jeu) + f" ; {len(directes)} sorties directes (dernier tiers en 15 s après une remise en jeu), tirs rapides : "
                            + tirs(mes, "directe")),
        ("2. transition offensive", f"{len(recups)} ballons gagnés hors du dernier tiers, {pct(len(rapides), len(recups))} mènent au dernier tiers en 15 s "
                                    f"(repère 10-30 %) ; tirs de transition (16 s, 5 passes au plus) : " + tirs(mes, "transition")),
        ("3. attaque placée", f"{len(placees)} attaques placées jusqu'au dernier tiers, {pct(sum(s['surface'] for s in placees), len(placees))} "
                              f"avec une passe dans la surface, {par(nb(mes, 'placee'), len(placees))} tir par attaque ; tirs : " + tirs(mes, "placee")),
        ("4. CPA offensifs", "directs : " + tirs(mes, "cpa") + " ; 2e ballon ou CPA rejoué : " + tirs(mes, "cpa2")
         + (" (+ penalty)" if any(x["phase"] == "penalty" for s in mes for x in s["tirs"]) else "")),
        ("5. pressing haut", f"{pct(sum(s['xmax'] < 50 for s in constr_adv), len(constr_adv))} des {len(constr_adv)} constructions adverses arrêtées "
                             f"avant le milieu, {len(hautes)} ballons gagnés dans le dernier tiers (repère 3-14 par match), tirs qui suivent : "
                             + tirs(mes, "haute") + f" ; PPDA {ppda:.0f} ; l'adversaire sort de sa moitié {f2:.1f} fois par 15 min ; "
                             f"ses tirs après une construction : " + tirs(constr_adv, *jeu)),
        ("6. transition défensive", f"contre-pressing : {pct(reprises, pertes_cp)} des {pertes_cp} ballons perdus dans la moitié adverse regagnés en "
                                    f"{CONTRE_PRESSING_SECONDES} s (repère 16-40 %, médiane 23) ; {pct(len(punies), len(pertes))} des {len(pertes)} pertes "
                                    f"punies d'un tir adverse en 16 s (repère 3-12 %, médiane 5)"
                                    + (f", délai moyen {statistics.mean(x['delai'] for x in punies):.0f} s" if punies else "")
                                    + " ; tirs : " + tirs(adv, "transition", "haute")),
        ("7. défense basse", (f"bloc à {h:.0f} m de son but en moyenne ({niveau} ; repère 29-45 m)" if h else "bloc : -")
         + f" ; {len(placees_adv)} attaques placées adverses jusqu'au dernier tiers, {pct(sum(s['surface'] for s in placees_adv), len(placees_adv))} "
          f"avec une passe dans la surface, {par(nb(adv, 'placee'), len(placees_adv))} tir concédé par attaque ; tirs : " + tirs(adv, "placee")),
        ("8. CPA défensifs", "directs : " + tirs(adv, "cpa") + " ; 2e ballon ou CPA rejoué : " + tirs(adv, "cpa2")),
    ]


# ---------- étape 2 : les périodes ----------
def _cout(v):
    if not v:
        return 0
    mu = sum(v) / len(v)
    return sum((x - mu) ** 2 for x in v)


def ruptures(v, lmin=PERIODE_MIN, seuil=SEUIL_COUPURE):
    """Coupe une série là où son niveau moyen change le plus, tant que le gain dépasse le seuil : [(début, fin)] en indices."""
    segs, reste = [], [(0, len(v))]
    while reste:
        a, z = reste.pop()
        best = max(((_cout(v[a:z]) - _cout(v[a:k]) - _cout(v[k:z]), k) for k in range(a + lmin, z - lmin + 1)), default=None)
        if best and best[0] > seuil:
            reste += [(a, best[1]), (best[1], z)]
        else:
            segs.append((a, z))
    return sorted(segs)


def periodes(fm, extra, mi, fin):
    """Périodes du match : ruptures du momentum FotMob lissé, la mi-temps coupe toujours. Sans FotMob : les deux mi-temps."""
    pts = [(m["minute"], m["value"]) for m in (((fm or {}).get("content") or {}).get("momentum") or {}).get("main", {}).get("data") or []]
    if not pts or not any(p[0] >= 46 for p in pts):
        return [{"a": 0, "b": mi, "nom": "1re mi-temps", "mom": None}, {"a": mi, "b": fin, "nom": "2e mi-temps", "mom": None}]
    # minute FotMob (affichée) -> temps continu : arrêts de jeu de la 1re mi-temps à 45.x, 2e mi-temps dès 46
    vers_t = lambda m: m if m <= 45 else 45 + extra if m < 46 else m - 1 + extra
    k2 = next(i for i, p in enumerate(pts) if p[0] >= 46)
    out = []
    for moitie, fin_moitie in ((pts[:k2], mi), (pts[k2:], fin)):
        lisse = [sum(p[1] for p in moitie[max(0, i - LISSAGE // 2):i + LISSAGE // 2 + 1]) / len(moitie[max(0, i - LISSAGE // 2):i + LISSAGE // 2 + 1])
                 for i in range(len(moitie))]
        coupes = ruptures(lisse)
        for n, (x, y) in enumerate(coupes):
            dernier = n == len(coupes) - 1
            a_m, b_m = moitie[x][0], moitie[y - 1][0]
            out.append({"a": vers_t(a_m) if x else (0 if fin_moitie == mi else mi), "b": fin_moitie if dernier else vers_t(moitie[y][0]),
                        "nom": f"{int(a_m)}'-{('45+' if fin_moitie == mi else '90+') if dernier else str(int(moitie[y][0]) - 1)}'",
                        "mom": sum(p[1] for p in moitie[x:y]) / (y - x)})
    return out


# ---------- étape 6 : les joueurs ----------
def joueurs(d, actions, xg, equipe, a, b, n=3):
    """Les n joueurs les plus impliqués d'une équipe entre a et b : récupérations, sorties de balle, passes vers le dernier tiers et la
    surface, passes clés, tirs (xG) et xG créé pour un partenaire (xA, par la passe reliée au tir)."""
    noms = {int(k): v for k, v in d["playerIdNameDictionary"].items()}
    entrees = {e["playerId"]: e["minute"] + 1 for e in actions if e["type"]["displayName"] == "SubstitutionOn"}
    par_id = {(e["teamId"], e.get("eventId")): e for e in actions}
    c = {}
    get = lambda pid: c.setdefault(pid, {"recup": 0, "sorties": 0, "tiers": 0, "surface": 0, "cles": 0, "tirs": 0, "xg": 0.0, "xa": 0.0})
    for e in actions:
        if not (a <= e["t"] < b) or e["teamId"] != equipe or "playerId" not in e:
            continue
        typ, ok, q = e["type"]["displayName"], e["outcomeType"]["value"] == 1, quals(e)
        j = get(e["playerId"])
        if typ in RECUP and ok and e["x"] >= 50:
            j["recup"] += 1
        if typ == "Pass" and ok and "endX" in e:
            j["sorties"] += e["x"] < 50 <= e["endX"]
            j["tiers"] += e["x"] < 66.7 <= e["endX"]
            j["surface"] += SURFACE(e["endX"], e["endY"])
        if typ == "Pass" and "KeyPass" in q:
            j["cles"] += 1
        if e.get("isShot"):
            j["tirs"] += 1
            j["xg"] += xg.get(int(e["id"]), 0)
            lien = next((x.get("value") for x in e.get("qualifiers", []) if x["type"]["displayName"] == "RelatedEventId"), None)
            passe = par_id.get((equipe, int(lien))) if lien else None
            if passe and "playerId" in passe and passe["playerId"] != e["playerId"]:
                get(passe["playerId"])["xa"] += xg.get(int(e["id"]), 0)
    # le danger créé (xG + xA) pèse lourd : 1 xG vaut 10 actions de volume (sinon un meneur de jeu passe devant le buteur décisif)
    implication = lambda j: j["recup"] + j["sorties"] + j["tiers"] + 2 * (j["surface"] + j["cles"] + j["tirs"]) + 10 * (j["xg"] + j["xa"])
    lignes = []
    for pid, j in sorted(c.items(), key=lambda i: -implication(i[1]))[:n]:
        if not implication(j):
            continue
        det = [f"{j[k]} {nom}" for k, nom in (("recup", "ballons gagnés dans la moitié adverse"), ("sorties", "sorties de balle"),
               ("tiers", "passes vers le dernier tiers"), ("surface", "passes dans la surface"), ("cles", "passes clés")) if j[k]]
        if j["tirs"]:
            det.append(f"{j['tirs']} tirs" + (f" (xG {j['xg']:.2f})" if xg else ""))
        if j["xa"]:
            det.append(f"xA {j['xa']:.2f}")
        lignes.append(f"{noms.get(pid, '?')}{f' (entré à la {entrees[pid]}e)' if pid in entrees else ''} : {', '.join(det)}")
    return lignes


# ---------- le rapport ----------
def analyser(d, sofa_tirs=None, fm=None):
    actions, tirs, xg, extra = preparer(d, sofa_tirs, fm)
    fin, mi = max(e["t"] for e in actions) + 0.1, 45 + extra
    eq = [(d["home"]["teamId"], True, d["home"]["name"]), (d["away"]["teamId"], False, d["away"]["name"])]
    seqs, mo = sequences(actions, xg), moments(d, actions)
    source_xg = "xG Opta (FotMob)" if fm else "xG Sofascore" if tirs else "sans xG"
    lignes = ["ÉTAPE 1 - Le récit : qui a dominé, et comment ?"]
    if fm:
        lignes += fotmob.resumer(fm)
    else:
        lignes.append(f"  (FotMob absent) score {d.get('score')} (mi-temps {d.get('htScore')}) ; {source_xg}")

    per = periodes(fm, extra, mi, fin)
    lignes.append(f"\nÉTAPE 2 - Les périodes : quand le match a-t-il basculé ? (momentum Opta ; positif = {eq[0][2]}, négatif = {eq[1][2]})")
    if per[0]["mom"] is None:
        lignes.append("  (pas de momentum FotMob : découpage par mi-temps)")
    for p in per:
        sens = "" if p["mom"] is None else f"momentum {p['mom']:+.0f} ({eq[0][2] if p['mom'] > 15 else eq[1][2] if p['mom'] < -15 else 'équilibré'}) ; "
        lignes.append(f"  {p['nom']:<10} {sens}score au début {score(d, actions, p['a'])}")

    lignes.append(f"\nÉTAPE 3 - Chaque période : qu'est-ce qui explique qui domine ? ({source_xg} ; nombres réels de la période, à citer tels "
                  "quels ; « ressort » compare les rythmes par 15 min, pour l'analyse seulement, jamais dans un tweet)")
    tout = {nom: mesurer(actions, tirs, equipe, dom, 0, fin) for equipe, dom, nom in eq}
    mesures = []
    for p in per:
        duree = p["b"] - p["a"]
        lignes.append(f"  {p['nom']} ({duree:.0f} min)")
        m = {nom: mesurer(actions, tirs, equipe, dom, p["a"], p["b"]) for equipe, dom, nom in eq}
        mesures.append(m)
        reel = lambda k, v: v if k in ("part", "ppda") else v * max(duree, 1) / 15  # mesurer ramène les comptes à 15 min
        for _, _, nom in eq:
            lignes.append(f"    {nom} : " + ", ".join(f"{MESURES[k][0]} {fmt(k, reel(k, m[nom][k]))}" for k in MESURES if k in m[nom]))
            res = ecarts(tout[nom], m[nom])[:3]
            if res:
                lignes.append("      ressort (rythme par 15 min) : " + " ; ".join(f"{MESURES[k][0]} {fmt(k, v2)} contre {fmt(k, v1)} sur le match"
                                                                              for k, v1, v2 in res))
        if p["b"] - p["a"] < 10:
            lignes.append("    (période courte : peu d'actions, chiffres fragiles)")

    quand = lambda dt: "au même moment" if abs(dt) < 1 else f"{abs(dt):.0f} min {'après' if dt > 0 else 'avant'}"
    lignes.append("\nÉTAPE 4 - Chaque bascule : pourquoi à ce moment-là ? (événements à 4 min près ; ce qui change d'une période à l'autre)")
    for i in range(1, len(per)):
        p0, p1 = per[i - 1], per[i]
        mi_temps = abs(p1["a"] - mi) < 0.5
        if p0["mom"] is not None and abs(p1["mom"] - p0["mom"]) < 25 and mi_temps:
            lignes.append(f"  mi-temps : pas de bascule (momentum {p0['mom']:+.0f} -> {p1['mom']:+.0f})")
            continue
        # 4 min avant ou après : le lissage du momentum avance un peu les coupures, et un changement suit parfois une baisse
        ev = [f"{x['minute']}' {x['equipe']} : {', '.join(x['quoi'])} ({quand(x['t'] - p1['a'])})" for x in mo if abs(x["t"] - p1["a"]) <= 4]
        titre = f"  {p1['nom'].split('-')[0]}" + (" (mi-temps)" if mi_temps else "")
        if p0["mom"] is not None:
            titre += f" : momentum {p0['mom']:+.0f} -> {p1['mom']:+.0f}"
        lignes.append(titre + f", score {score(d, actions, p1['a'])}")
        lignes.append("    déclencheur : " + ("; ".join(ev) if ev else "aucun événement (intensité, fatigue, consigne ou effet du score : à vérifier)")
                      + (" ; pause : consignes de l'entraîneur possibles" if mi_temps else ""))
        for _, _, nom in eq:
            chg = ecarts(mesures[i - 1][nom], mesures[i][nom])
            if chg:
                lignes.append(f"    {nom} : " + " ; ".join(f"{MESURES[k][0]} {fmt(k, v1)} -> {fmt(k, v2)}" for k, v1, v2 in chg))

    lignes.append("\nÉTAPE 5 - Les phases de jeu : lesquelles ont décidé le match ? (1re mi-temps || 2e mi-temps)")
    for equipe, _, nom in eq:
        lignes.append(f"  {nom}")
        for (ph, v1), (_, v2) in zip(phases(seqs, actions, equipe, 0, mi, bool(xg)), phases(seqs, actions, equipe, mi, fin, bool(xg))):
            lignes.append(f"    {ph:<24} {v1}  ||  {v2}")

    lignes.append("\nÉTAPE 6 - Les joueurs : qui a fait la différence dans chaque période ? (les 3 plus impliqués par équipe)")
    for p in per:
        lignes.append(f"  {p['nom']}")
        for equipe, _, nom in eq:
            for j in joueurs(d, actions, xg, equipe, p["a"], p["b"]):
                lignes.append(f"    {nom} - {j}")
    return lignes


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    dossier = Path(sys.argv[1])
    lire = lambda nom: json.loads((dossier / nom).read_text(encoding="utf-8")) if (dossier / nom).exists() else None
    sofa, fm = lire("sofascore.json"), lire("fotmob.json")
    print("\n".join(analyser(whoscored.lire((dossier / "whoscored.html").read_text(encoding="utf-8")), (sofa or {}).get("shotmap"), fm)))

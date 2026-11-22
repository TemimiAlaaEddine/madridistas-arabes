"""Cherche dans les données d'un match (actions WhoScored + tirs Sofascore) les tendances et les moments où il a basculé.

Usage : python bascules.py matchs/AAAA-MM-JJ-adversaire   (lancé aussi par match.py)
Phases de jeu : possessions reconstituées à partir des actions, puis classées (transition, attaque placée, pressing...).
Ce sont des indices chiffrés, pas des conclusions : le score, la fatigue et le contexte peuvent les expliquer.
Coordonnées WhoScored : 0 à 100, chaque équipe attaque vers x = 100.
"""
import json
import sys
from pathlib import Path

import whoscored

DEFENSE = {"Tackle", "Interception", "Challenge", "Foul"}  # actions qui comptent pour le PPDA
RECUP = {"BallRecovery", "Interception", "Tackle"}
# nom affiché, écart minimal pour signaler un changement (en valeur par 15 min ou en points de %)
MESURES = {
    "part": ("part des passes (%)", 8), "passes": ("passes réussies", 15), "avant": ("passes vers l'avant (%)", 6),
    "tiers": ("entrées dans le dernier tiers", 4), "surface": ("passes dans la surface", 2), "tirs": ("tirs", 2),
    "xg": ("xG", 0.3), "recup": ("récupérations hautes", 2), "ppda": ("PPDA (bas = pressing fort)", 4),
}
FENETRES = [(0, 15, "0-15"), (15, 30, "15-30"), (30, 45, "30-45+"), (45, 60, "45-60"), (60, 75, "60-75"), (75, 200, "75-90+")]


def horloge(d):
    """Temps continu en minutes : la 2e mi-temps commence après les arrêts de jeu de la 1re."""
    fin1 = max((e["minute"] + 1 for e in d["events"] if e["period"]["value"] == 1), default=45)
    extra = max(fin1 - 45, 0)
    return lambda periode, m: m + (extra if periode == 2 else 0), extra


def preparer(d, sofa_tirs):
    t, extra = horloge(d)
    actions = [dict(e, t=t(e["period"]["value"], e["minute"] + e.get("second", 0) / 60)) for e in d["events"] if e["period"]["value"] in (1, 2)]
    tirs = []
    for s in sofa_tirs or []:
        p = 1 if s["time"] <= 45 else 2
        tirs.append({"dom": s["isHome"], "xg": s.get("xg") or 0, "t": (45 + extra if p == 2 else 0) + s.get("periodTimeSeconds", 0) / 60})
    return actions, tirs, extra


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
        "part": 100 * len(miennes) / max(len(passes), 1),
        "passes": len(reussies) / duree,
        "avant": 100 * sum(e["endX"] - e["x"] >= 10 for e in reussies) / max(len(reussies), 1),
        "tiers": sum(e["x"] < 66.7 <= e["endX"] for e in reussies) / duree,
        "surface": sum(e["endX"] >= 83 and 21 <= e["endY"] <= 79 for e in reussies) / duree,
        "tirs": sum(e["teamId"] == equipe and e.get("isShot", False) for e in ev) / duree,
        "recup": sum(e["teamId"] == equipe and e["type"]["displayName"] in RECUP and e["x"] >= 60 and ok(e) for e in ev) / duree,
        "ppda": len(adv_passes) / max(len(defense), 1),
    }
    if tirs:
        r["xg"] = sum(s["xg"] for s in tirs if s["dom"] == dom and a <= s["t"] < b) / duree
    return r


def ecarts(avant, apres):
    """Changements nets entre deux périodes : [(clé, avant, après)]."""
    return [(k, avant[k], apres[k]) for k in MESURES if k in avant and abs(apres[k] - avant[k]) >= MESURES[k][1]
            and abs(apres[k] - avant[k]) >= 0.35 * max(abs(avant[k]), abs(apres[k]))]


def fmt(k, v):
    return f"{v:.2f}" if k == "xg" else f"{v:.0f}"


def moments(d, actions):
    """Buts, changements (groupés par équipe et minute), cartons rouges, changements de système."""
    noms = {int(k): v for k, v in d["playerIdNameDictionary"].items()}
    equipes = {d["home"]["teamId"]: d["home"]["name"], d["away"]["teamId"]: d["away"]["name"]}
    liste = []
    for e in actions:
        typ, quals = e["type"]["displayName"], {q["type"]["displayName"] for q in e.get("qualifiers", [])}
        if typ == "Goal":
            quoi = f"but {'contre son camp ' if 'OwnGoal' in quals else ''}de {noms.get(e.get('playerId'), '?')}"
        elif e.get("isShot") and "Penalty" in quals:
            quoi = f"penalty manqué par {noms.get(e.get('playerId'), '?')}"
        elif typ == "SubstitutionOn":
            quoi = f"entrée de {noms.get(e.get('playerId'), '?')}"
        elif typ == "Card" and quals & {"Red", "SecondYellow"}:
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


POSSESSION = {"Pass", "BallRecovery", "KeeperPickup", "TakeOn"}  # l'équipe a le ballon ; dégagement, interception, touche : ballon disputé
CPA = {"FromCorner", "SetPiece", "DirectFreekick", "ThrowinSetPiece"}
REMISES = {"GoalKick", "ThrowIn", "FreekickTaken", "CornerTaken", "KickOff"}  # possession qui ne vient pas d'une perte adverse
RAPIDE_SECONDES, RAPIDE_PASSES = 15, 5  # possession rapide : dernier tiers en 15 s et 5 passes au plus (contres WhoScored : 12 s au plus)
TIR_SECONDES = 16  # tir rapide : 16 s et 5 passes au plus depuis le début de la possession (réglé sur 8 matchs, 2026-11-22 : couvre les 21 contres WhoScored)
SURFACE = lambda x, y: x >= 83 and 21 <= y <= 79


def sequences(actions, tirs):
    """Possessions : suite d'actions d'une même équipe, coupée quand l'autre touche le ballon. xG des tirs pris à Sofascore."""
    seqs, cur, libres = [], None, list(tirs)
    for e in actions:
        if e["type"]["displayName"] not in POSSESSION and not e.get("isShot"):
            continue
        quals = {q["type"]["displayName"] for q in e.get("qualifiers", [])}
        relance = bool(quals & {"CornerTaken", "FreekickTaken"})
        # une récupération ouvre toujours une possession (2e ballon après un dégagement adverse, par exemple)
        if not cur or relance or e["type"]["displayName"] == "BallRecovery" or e["teamId"] != cur["equipe"] or e["period"]["value"] != cur["periode"]:
            cur = {"equipe": e["teamId"], "periode": e["period"]["value"], "t0": e["t"], "x0": e["x"], "xmax": e["x"], "passes": 0,
                   "recup": e["type"]["displayName"] != "KeeperPickup" and not quals & REMISES, "cpa": relance and e["x"] >= 50,
                   "t_tiers": None, "p_tiers": None, "surface": False, "tirs": [],
                   "t_ref": e["t"], "p_ref": 0, "relance_basse": False}
            seqs.append(cur)
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
            proche = min(libres, key=lambda s: abs(s["t"] - e["t"]), default=None) if libres else None
            xg = None
            if proche and abs(proche["t"] - e["t"]) <= 1.5:
                libres.remove(proche)
                xg = proche["xg"]
            vite = e["t"] - cur["t_ref"] <= TIR_SECONDES / 60 and cur["passes"] - cur["p_ref"] <= RAPIDE_PASSES
            if "Penalty" in quals:
                phase = "penalty"
            elif quals & CPA or cur["cpa"] and vite and not cur["relance_basse"]:
                phase = "cpa"
            elif vite and cur["recup"] and not cur["relance_basse"]:
                phase = "haute" if cur["x0"] >= 66.7 else "transition"
            else:
                phase = "directe" if vite and (not cur["cpa"] or cur["relance_basse"]) else "placee"
            cur["tirs"].append({"phase": phase, "xg": xg, "delai": round((e["t"] - cur["t_ref"]) * 60), "passes": cur["passes"] - cur["p_ref"]})
    for s in seqs:
        s["haute"] = s["recup"] and s["x0"] >= 66.7  # ballon gagné dans le dernier tiers : fruit du pressing
        # dernier tiers en 15 s et 5 passes au plus : après une perte adverse = transition, après une remise en jeu = sortie directe
        vite = (not s["haute"] and not s["cpa"] and s["t_tiers"] is not None and s["t_tiers"] - s["t0"] <= RAPIDE_SECONDES / 60
                and s["p_tiers"] <= RAPIDE_PASSES)
        s["rapide"], s["directe"] = vite and s["recup"], vite and not s["recup"]
        s["placee"] = s["xmax"] >= 66.7 and not (s["haute"] or vite or s["cpa"])
    return seqs


def franchissement(actions, equipe, a, b):
    """Passes de sa moitié : réussies vers la moitié adverse (par 15 min), % de réussite, longs ballons."""
    p = [e for e in actions if a <= e["t"] < b and e["teamId"] == equipe and e["type"]["displayName"] == "Pass" and e["x"] < 50]
    ok = [e for e in p if e["outcomeType"]["value"] == 1 and "endX" in e]
    longs = sum(any(q["type"]["displayName"] == "Longball" for q in e.get("qualifiers", [])) for e in p)
    return sum(e["endX"] >= 50 for e in ok) / (max(b - a, 1) / 15), 100 * len(ok) / max(len(p), 1), longs


def phases(seqs, actions, equipe, a, b, avec_xg):
    """Les 8 phases de la méthode de l'utilisateur, mesurées pour une équipe entre a et b."""
    mes = [s for s in seqs if s["equipe"] == equipe and a <= s["t0"] < b]
    adv = [s for s in seqs if s["equipe"] != equipe and a <= s["t0"] < b]
    pct = lambda n, tot: f"{100 * n / tot:.0f} %" if tot else "-"

    def tirs(ss, *phases_tir):
        t = [x for s in ss for x in s["tirs"] if x["phase"] in phases_tir]
        return f"{len(t)} tirs" + (f", xG {sum(x['xg'] or 0 for x in t):.2f}" if avec_xg else "")
    jeu = ("transition", "directe", "placee", "haute")
    constr, constr_adv = [s for s in mes if s["x0"] < 33.3], [s for s in adv if s["x0"] < 33.3]
    adversaire = next((s["equipe"] for s in adv), None)
    (f1, r1, l1), (f2, r2, l2) = franchissement(actions, equipe, a, b), franchissement(actions, adversaire, a, b)
    rapides, rapides_adv = [s for s in mes if s["rapide"]], [s for s in adv if s["rapide"]]
    placees, placees_adv = [s for s in mes if s["placee"]], [s for s in adv if s["placee"]]
    hautes, directes = [s for s in mes if s["haute"]], [s for s in mes if s["directe"]]
    return [
        ("1. construction", f"{f1:.1f} passes réussies par 15 min de sa moitié vers l'autre ({r1:.0f} % de réussite dans sa moitié, {l1} longs "
                            f"ballons) ; possessions parties de son tiers défensif conclues par un tir : " + tirs(constr, *jeu)
                            + f" ; {len(directes)} sorties directes après une remise en jeu (dernier tiers en 15 s), tirs rapides après remise en jeu : " + tirs(mes, "directe")),
        ("2. transition offensive", f"{sum(s['recup'] and not s['haute'] for s in mes)} ballons gagnés hors du dernier tiers, {len(rapides)} transitions jusqu'au dernier tiers en 15 s, tirs de transition (16 s, 5 passes au plus) : "
                                    + tirs(mes, "transition")),
        ("3. attaque placée", f"{len(placees)} attaques placées (hors transition) jusqu'au dernier tiers, {pct(sum(s['surface'] for s in placees), len(placees))} "
                              f"avec une passe dans la surface ; tirs en attaque placée : " + tirs(mes, "placee")),
        ("4. CPA offensifs", tirs(mes, "cpa") + (" (+ penalty)" if any(x["phase"] == "penalty" for s in mes for x in s["tirs"]) else "")),
        ("5. pressing haut", f"l'adversaire réussit {f2:.1f} passes par 15 min de sa moitié vers l'autre ({r2:.0f} % de réussite dans sa moitié) ; "
                             f"ses possessions parties de son tiers défensif conclues par un tir : " + tirs(constr_adv, *jeu)
                             + f" ; {len(hautes)} ballons gagnés dans le dernier tiers, tirs rapides qui suivent : " + tirs(mes, "haute")),
        ("6. transition défensive", f"{len(rapides_adv)} transitions adverses jusqu'au dernier tiers en 15 s ; leurs tirs de transition : " + tirs(adv, "transition")),
        ("7. défense basse", f"{len(placees_adv)} attaques placées adverses jusqu'au dernier tiers, "
                             f"{pct(sum(s['surface'] for s in placees_adv), len(placees_adv))} avec une passe dans la surface ; leurs tirs en attaque placée : " + tirs(adv, "placee")),
        ("8. CPA défensifs", tirs(adv, "cpa")),
    ]


def analyser(d, sofa_tirs=None):
    actions, tirs, extra = preparer(d, sofa_tirs)
    fin = max(e["t"] for e in actions) + 0.1
    eq = [(d["home"]["teamId"], True, d["home"]["name"]), (d["away"]["teamId"], False, d["away"]["name"])]
    lignes = ["Mi-temps (par 15 min ; parts et % tels quels)"]
    mi = 45 + extra
    for equipe, dom, nom in eq:
        m1, m2 = mesurer(actions, tirs, equipe, dom, 0, mi), mesurer(actions, tirs, equipe, dom, mi, fin)
        lignes.append(f"  {nom} : " + " | ".join(f"{MESURES[k][0]} {fmt(k, m1[k])} -> {fmt(k, m2[k])}" for k in m1))
    seqs = sequences(actions, tirs)
    lignes.append("\nPhases de jeu (1re mi-temps || 2e mi-temps)")
    for equipe, dom, nom in eq:
        lignes.append(f"  {nom}")
        for (ph, v1), (_, v2) in zip(phases(seqs, actions, equipe, 0, mi, bool(tirs)), phases(seqs, actions, equipe, mi, fin, bool(tirs))):
            lignes.append(f"    {ph:<24} {v1}  ||  {v2}")
    lignes.append("\nQuarts d'heure")
    fen = [(a + (extra if a >= 45 else 0), b + (extra if b >= 45 else 0), n) for a, b, n in FENETRES]
    fen[2], fen[5] = (fen[2][0], mi, fen[2][2]), (fen[5][0], fin, fen[5][2])
    for equipe, dom, nom in eq:
        par = [(n, mesurer(actions, tirs, equipe, dom, a, b)) for a, b, n in fen]
        lignes.append(f"  {nom}")
        for k in MESURES:
            if k in par[0][1]:
                lignes.append(f"    {MESURES[k][0]:<32} " + "  ".join(f"{n}: {fmt(k, m[k]):>4}" for n, m in par))
        for k in ("tiers", "xg", "passes"):  # quart d'heure le plus faible et le plus fort de l'équipe
            if k in par[0][1]:
                bas, haut = min(par, key=lambda p: p[1][k]), max(par, key=lambda p: p[1][k])
                lignes.append(f"    -> {MESURES[k][0]} : plus bas {bas[0]} ({fmt(k, bas[1][k])}), plus haut {haut[0]} ({fmt(k, haut[1][k])})")
    lignes.append("\nBascules possibles (15 min avant / 15 min après, par 15 min ; à recouper avec le score et le contexte)")
    for mo in moments(d, actions):
        a, b = max(mo["t"] - 15, 0), min(mo["t"] + 15, fin)
        if b - mo["t"] < 8 or mo["t"] - a < 8:  # trop près du début ou de la fin pour comparer
            continue
        chg = []
        for equipe, dom, nom in eq:
            for k, v1, v2 in ecarts(mesurer(actions, tirs, equipe, dom, a, mo["t"]), mesurer(actions, tirs, equipe, dom, mo["t"], b)):
                chg.append(f"{nom} {MESURES[k][0]} {fmt(k, v1)} -> {fmt(k, v2)}")
        if chg:
            lignes.append(f"  {mo['minute']}' {mo['equipe']} : {', '.join(mo['quoi'])}\n    " + " ; ".join(chg))
    return lignes


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    dossier = Path(sys.argv[1])
    sofa = dossier / "sofascore.json"
    tirs = json.loads(sofa.read_text(encoding="utf-8")).get("shotmap") if sofa.exists() else None
    print("\n".join(analyser(whoscored.lire((dossier / "whoscored.html").read_text(encoding="utf-8")), tirs)))

"""Évaluation des joueurs selon leur rôle (étape 6 de bascules.py).

Usage : python postes.py --reperes          (recalcule reperes_postes.json à partir des matchs enregistrés dans matchs/)
        python postes.py matchs/AAAA-MM-JJ-adversaire   (évaluation seule d'un match)
Méthode : 1. le rôle de chaque joueur vient de sa place dans le système WhoScored (remplaçants compris), corrigé par son couloir
réel (un ailier qui joue dans l'axe est jugé comme un meneur) ; 2. chaque rôle a ses critères, positifs et négatifs, comptés dans
les actions Opta de WhoScored (xG, xGOT de FotMob) ; 3. tout est ramené à 90 minutes, les actions défensives sont corrigées par la
possession adverse (moins de ballons à défendre quand son équipe a le ballon), puis comparées au repère du rôle (moyenne et écart
des joueurs du même rôle dans les matchs enregistrés, les deux équipes) ; 4. le joueur est aussi comparé à lui-même (ses matchs
enregistrés) : « hors de ses habitudes ». Ce que les actions ne voient pas : courses et appels sans ballon, pressing sans contact,
placement ; une observation de l'utilisateur (observations.md du match) le complète.
"""
import json
import statistics
import sys
from pathlib import Path

import bascules
import whoscored

ICI = Path(__file__).parent
REPERES = ICI / "reperes_postes.json"
REAL = 52  # Real Madrid sur WhoScored
LIGNES = {"défense": ("gardien", "défenseur central", "latéral"), "milieu": ("milieu défensif", "relayeur", "meneur"),
          "attaque": ("ailier", "avant-centre")}
# critère : (nom affiché, poids par rôle) ; un poids négatif pénalise
POIDS = {
    # le nombre d'arrêts dépend surtout des tirs adverses : seuls les buts évités jugent les arrêts
    "gardien": {"buts_evites": 3, "sorties": 0.5, "relances_pct": 1, "erreurs": -2},
    "défenseur central": {"duels_g": 1, "aeriens_g": 1.5, "interceptions": 1, "degagements": 0.5, "contres": 1, "prog": 1, "tiers": 1,
                          "passes_pct": 0.5, "dribble": -1.5, "pertes_bas": -1.5, "aeriens_p": -0.5, "erreurs": -2},
    "latéral": {"duels_g": 1, "interceptions": 0.5, "recup": 0.5, "prog": 1, "tiers": 1, "centres": 1, "surface": 1, "xa": 1.5,
                "recues_prog": 0.5, "dribble": -1.5, "pertes": -0.5, "erreurs": -2},
    "milieu défensif": {"recup": 1.5, "interceptions": 1, "duels_g": 1, "passes_pct": 1, "prog": 1.5, "tiers": 1, "recues_relance": 1,
                        "pertes_bas": -1.5, "dribble": -1, "erreurs": -2},
    "relayeur": {"tiers": 1.5, "prog": 1, "recup_haut": 1, "duels_g": 1, "touches_surface": 1, "xg": 1, "xa": 1, "recues_lignes": 1,
                 "cles": 0.5, "buts": 0.5, "pertes": -1, "erreurs": -2},
    "meneur": {"cles": 1.5, "surface": 1.5, "xa": 2, "prog": 1, "dribbles_g": 1, "recues_lignes": 1.5, "xg": 1, "recup_haut": 0.5,
               "touches_surface": 0.5, "buts": 1, "pertes": -0.5, "erreurs": -1.5},
    "ailier": {"dribbles_g": 1.5, "touches_surface": 1, "surface": 1, "centres": 0.5, "xg": 1.5, "xa": 1.5, "cles": 1, "recup_haut": 0.5,
               "recues_prog": 1, "buts": 1, "pertes": -0.75, "dribbles_rates": -0.5},
    "avant-centre": {"xg": 2, "tirs": 0.5, "finition": 1, "touches_surface": 1.5, "aeriens_g": 0.5, "recup_haut": 0.5, "xa": 1,
                     "recues_lignes": 0.5, "buts": 1, "pertes": -0.5},
}
NOMS = {
    "buts_evites": "buts évités", "arrets": "arrêts", "sorties": "sorties aériennes ou hors de la surface", "relances_pct": "% de relances réussies",
    "erreurs": "erreurs", "duels_g": "duels gagnés", "aeriens_g": "duels aériens gagnés", "aeriens_p": "duels aériens perdus",
    "interceptions": "interceptions", "degagements": "dégagements", "contres": "tirs ou passes contrés", "prog": "passes qui font avancer de 15 m",
    "tiers": "passes vers le dernier tiers", "passes_pct": "% de passes réussies", "dribble": "fois dribblé", "pertes_bas": "ballons perdus dans son tiers",
    "pertes": "ballons perdus", "recup": "ballons récupérés", "recup_haut": "ballons récupérés dans la moitié adverse", "centres": "centres réussis",
    "surface": "passes dans la surface", "xa": "xA", "xg": "xG", "recues_prog": "passes reçues qui font avancer de 15 m",
    "recues_relance": "passes reçues à la relance", "recues_lignes": "passes reçues entre les lignes", "touches_surface": "ballons touchés dans la surface",
    "cles": "passes clés", "dribbles_g": "dribbles réussis", "dribbles_rates": "dribbles ratés", "tirs": "tirs", "finition": "finition (xGOT - xG)", "buts": "buts",
}
RATIOS = {"passes_pct", "relances_pct"}  # déjà des pourcentages : ni ramenés à 90 minutes ni corrigés
SANS_DUREE = {"buts_evites", "finition", "xg", "xa"}  # gardés tels quels dans les raisons (décimaux)
DEFENSIFS = {"recup", "interceptions", "degagements", "contres", "duels_g", "aeriens_g"}  # corrigés par la possession adverse


def role_place(v, h):
    """Rôle d'une place du système WhoScored (vertical 0 = gardien à 9 = attaque, horizontal 0 à 10 d'un côté à l'autre)."""
    large = h <= 2 or h >= 8
    if v == 0:
        return "gardien"
    if v <= 3:
        return "latéral" if h <= 1 or h >= 9 else "défenseur central"
    if v >= 8.5:
        return "ailier" if h <= 2.5 or h >= 7.5 else "avant-centre"
    if large:
        return "latéral" if v <= 5.5 and (h <= 1 or h >= 9) else "ailier"
    if v <= 5.5:
        return "milieu défensif" if v <= 5 or h == 5 else "relayeur"
    return "relayeur" if v < 6.5 and h != 5 else "meneur"


def minutes_et_roles(equipe, a, b):
    """{id joueur: (minutes jouées entre a et b, rôle le plus tenu)} d'après les systèmes successifs de l'équipe."""
    temps = {}
    for f in equipe["formations"]:
        debut, fin = max(f.get("startMinuteExpanded", 0), a), min(f.get("endMinuteExpanded", 200), b)
        if fin <= debut:
            continue
        for pid, slot in zip(f["playerIds"], f["formationSlots"]):
            if slot:
                p = f["formationPositions"][slot - 1]
                r = temps.setdefault(pid, {})
                r[role_place(p["vertical"], p["horizontal"])] = r.get(role_place(p["vertical"], p["horizontal"]), 0) + fin - debut
    return {pid: (sum(r.values()), max(r, key=r.get)) for pid, r in temps.items()}


def compter(actions, xg, xgot, equipe, a, b):
    """Comptes bruts de chaque joueur de l'équipe entre a et b : {id: {critère: nombre}}, plus la part de possession adverse."""
    ok = lambda e: e["outcomeType"]["value"] == 1
    c = {}
    get = lambda pid: c.setdefault(pid, {k: 0 for k in NOMS if k not in RATIOS} | {"passes": 0, "passes_ok": 0, "y": []})
    ev = [e for e in actions if a <= e["t"] < b]
    par_id = {(e["teamId"], e.get("eventId")): e for e in ev}
    passes = [e for e in ev if e["type"]["displayName"] == "Pass"]
    adv_share = sum(e["teamId"] != equipe for e in passes) / max(len(passes), 1)
    for i, e in enumerate(ev):
        if e["teamId"] != equipe or "playerId" not in e:
            continue
        typ, q, j = e["type"]["displayName"], bascules.quals(e), get(e["playerId"])
        if e.get("isTouch"):
            j["y"].append(e["y"])
            j["touches_surface"] += bascules.SURFACE(e["x"], e["y"])
        if typ == "Pass":
            j["passes"] += 1
            j["passes_ok"] += ok(e)
            if not ok(e) and e["x"] < 33.3:
                j["pertes_bas"] += 1
            if ok(e) and "endX" in e:
                j["prog"] += e["endX"] - e["x"] >= 15
                j["tiers"] += e["x"] < 66.7 <= e["endX"]
                j["surface"] += bascules.SURFACE(e["endX"], e["endY"])
                j["centres"] += "Cross" in q
                suite = next((z for z in ev[i + 1:i + 6] if z.get("isTouch") and "playerId" in z), None)
                if suite and suite["teamId"] == equipe and suite["playerId"] != e["playerId"]:
                    r = get(suite["playerId"])
                    r["recues_relance"] += e["x"] < 40  # il s'est offert à la relance et a été trouvé
                    r["recues_lignes"] += 50 <= e["endX"] <= 80 and 25 <= e["endY"] <= 75
                    r["recues_prog"] += e["endX"] - e["x"] >= 15
            j["cles"] += "KeyPass" in q
        if typ in bascules.DUELS:
            j["duels_g"] += bascules.GAGNE(e)
        if typ == "Aerial":
            j["aeriens_g" if ok(e) else "aeriens_p"] += 1
        if typ == "Challenge":
            j["dribble"] += 1
        if typ == "TakeOn":
            j["dribbles_g" if ok(e) else "dribbles_rates"] += 1
        if typ in ("Dispossessed",) or (typ == "TakeOn" and not ok(e)) or (typ == "BallTouch" and not ok(e)):
            j["pertes"] += 1
            j["pertes_bas"] += e["x"] < 33.3
        if typ in bascules.RECUP and (typ == "Tackle" or ok(e)):
            j["recup"] += 1
            j["recup_haut"] += e["x"] >= 50
        j["interceptions"] += typ == "Interception"
        j["degagements"] += typ == "Clearance"
        j["contres"] += typ == "BlockedPass" or (typ == "Save" and "OutfielderBlock" in q)
        j["erreurs"] += typ == "Error"
        if typ == "Save" and "OutfielderBlock" not in q:
            j["arrets"] += 1
        if typ in ("Claim", "Punch", "KeeperSweeper") and ok(e):
            j["sorties"] += 1
        if e.get("isShot"):
            j["tirs"] += 1
            j["buts"] += bool(e.get("isGoal")) and "OwnGoal" not in q
            j["xg"] += xg.get(int(e["id"]), 0)
            if xgot is not None:
                j["finition"] += xgot.get(int(e["id"]), 0) - xg.get(int(e["id"]), 0)
            lien = next((x.get("value") for x in e.get("qualifiers", []) if x["type"]["displayName"] == "RelatedEventId"), None)
            passe = par_id.get((equipe, int(lien))) if lien else None
            if passe and "playerId" in passe and passe["playerId"] != e["playerId"]:
                get(passe["playerId"])["xa"] += xg.get(int(e["id"]), 0)
    # tirs adverses cadrés : xGOT subi et buts encaissés, pour le gardien de l'équipe
    subis = [e for e in ev if e["teamId"] != equipe and e.get("isShot") and "OwnGoal" not in bascules.quals(e)]
    return c, adv_share, sum(xgot.get(int(e["id"]), 0) for e in subis) if xgot is not None else None, sum(bool(e.get("isGoal")) for e in subis)


def valeurs(c, minutes, role, adv_share):
    """Critères d'un joueur ramenés à 90 minutes (actions défensives corrigées par la possession adverse)."""
    k90 = 90 / max(minutes, 1)
    padj = 0.5 / min(max(adv_share, 0.25), 0.75)  # adversaire à 25 % du ballon : deux fois moins de ballons à défendre
    v = {}
    for k in NOMS:
        if k in RATIOS:
            continue
        x = c.get(k, 0)
        v[k] = None if x is None else x * k90 * (padj if k in DEFENSIFS else 1)
    v["passes_pct"] = 100 * c["passes_ok"] / c["passes"] if c["passes"] >= 10 else None
    if role == "gardien":
        v["relances_pct"] = v.pop("passes_pct")
    return v


def evaluer_equipe(d, actions, xg, xgot, cote, a, b, mini=20):
    """[(id, rôle, minutes, comptes, valeurs)] des joueurs d'une équipe ayant joué au moins `mini` minutes entre a et b."""
    equipe = d[cote]
    c, adv, xgot_subi, buts = compter(actions, xg, xgot, equipe["teamId"], a, b)
    out = []
    for pid, (m, role) in minutes_et_roles(equipe, a, b).items():
        if m < mini or pid not in c:
            continue
        ys = c[pid]["y"]
        if ys and role in ("ailier", "meneur"):  # le couloir réel prime sur la place du système
            axe = 37 <= statistics.mean(ys) <= 63
            role = "meneur" if axe and role == "ailier" else "ailier" if not axe and role == "meneur" else role
        if role == "gardien":  # xGOT des tirs adverses cadrés moins buts encaissés pendant qu'il était là
            c[pid]["buts_evites"] = xgot_subi - buts if xgot_subi is not None else None
        if xgot is None:
            c[pid]["finition"] = None
        out.append((pid, role, m, c[pid], valeurs(c[pid], m, role, adv)))
    return out


def preparer(d, fm):
    actions, _, xg, _ = bascules.preparer(d, None, fm)
    xgot = {s["id"]: s.get("expectedGoalsOnTarget") or 0 for s in (fm["content"].get("shotmap") or {}).get("shots") or []} if fm else None
    return actions, xg, xgot


def construire_reperes():
    """Repères par rôle (moyenne, écart) et habitudes de chaque joueur, sur les matchs entiers (45 minutes au moins) de matchs/."""
    par_role, par_joueur, n = {}, {}, 0
    for f in sorted(ICI.glob("matchs/*/whoscored.html")):
        d = whoscored.lire(f.read_text(encoding="utf-8"))
        fm_f = f.parent / "fotmob.json"
        fm = json.loads(fm_f.read_text(encoding="utf-8")) if fm_f.exists() else None
        actions, xg, xgot = preparer(d, fm)
        fin = max(e["t"] for e in actions) + 0.1
        n += 1
        for cote in ("home", "away"):
            for pid, role, m, _, v in evaluer_equipe(d, actions, xg, xgot, cote, 0, fin, mini=45):
                par_role.setdefault(role, []).append(v)
                par_joueur.setdefault(str(pid), []).append(v)
    stat = lambda vs, k: [x for x in (v.get(k) for v in vs) if x is not None]
    roles = {r: {"n": len(vs)} | {k: [statistics.mean(x), statistics.pstdev(x)] for k in NOMS if len(x := stat(vs, k)) >= 3}
             for r, vs in par_role.items()}
    joueurs = {pid: {"n": len(vs)} | {k: statistics.mean(x) for k in NOMS if (x := stat(vs, k))} for pid, vs in par_joueur.items() if len(vs) >= 3}
    REPERES.write_text(json.dumps({"matchs": n, "roles": roles, "joueurs": joueurs}, ensure_ascii=False, indent=1), encoding="utf-8")
    return n, {r: v["n"] for r, v in roles.items()}


def noter(role, v, reperes):
    """Score du joueur dans son rôle (moyenne pondérée des écarts au repère, de -3 à 3) et contributions de chaque critère."""
    rep = reperes["roles"].get(role, {})
    contrib = {}
    for k, w in POIDS[role].items():
        if v.get(k) is None or k not in rep:
            continue
        moy, ecart = rep[k]
        z = (v[k] - moy) / max(ecart, 0.1 * abs(moy), 0.05)
        contrib[k] = w * max(-3, min(3, z))
    return sum(contrib.values()) / sum(abs(w) for w in POIDS[role].values()), contrib


def montrer(k, c, v):
    """Valeur réelle d'un critère, telle qu'on la cite (compte du match, pas le rythme par 90 minutes)."""
    if k in RATIOS:
        return f"{v[k]:.0f} {NOMS[k]}"
    if k in SANS_DUREE:
        return f"{NOMS[k]} {c[k]:+.2f}" if k in ("buts_evites", "finition") else f"{NOMS[k]} {c[k]:.2f}"
    return f"{c[k]:g} {NOMS[k]}"


def habitudes_z(pid, role, v, reperes):
    """Le plus grand écart du joueur à ses propres matchs (en écarts du rôle), 0 s'il reste dans ses habitudes."""
    h, rep = reperes["joueurs"].get(str(pid)), reperes["roles"].get(role, {})
    zs = [abs(v[k] - h[k]) / max(rep[k][1], 0.1 * abs(h[k]), 0.05) for k in POIDS[role]
          if h and k in h and k in rep and v.get(k) is not None and k not in SANS_DUREE]
    return max(zs) if zs and max(zs) >= 1.5 else 0


def habitudes(pid, role, v, reperes):
    """Critères où le joueur s'écarte nettement de ses propres matchs (1,5 écart du rôle), s'il en a au moins 3 enregistrés."""
    h, rep = reperes["joueurs"].get(str(pid)), reperes["roles"].get(role, {})
    if not h:
        return []
    out = []
    for k in POIDS[role]:
        if k in h and k in rep and v.get(k) is not None and k not in SANS_DUREE:
            z = (v[k] - h[k]) / max(rep[k][1], 0.1 * abs(h[k]), 0.05)
            if abs(z) >= 1.5:
                out.append((abs(z), f"{NOMS[k]} {'au-dessus' if z > 0 else 'en dessous'} de ses habitudes"))
    return [t for _, t in sorted(out, reverse=True)[:2]]


def raisons(role, c, v, contrib):
    """Les critères qui font le score, en nombres réels : points forts (critères positifs au-dessus du repère) et points faibles
    (critères positifs en dessous, ou négatifs au-dessus : être dribblé, perdre le ballon). Ne pas faire d'erreur n'est pas une raison."""
    plus = [montrer(k, c, v) for k, x in sorted(contrib.items(), key=lambda i: -i[1]) if x > 0.5 and POIDS[role][k] > 0][:3]
    moins = [montrer(k, c, v) for k, x in sorted(contrib.items(), key=lambda i: i[1]) if x < -0.5][:2]
    return (" ; points forts : " + ", ".join(plus) if plus else "") + (" ; points faibles : " + ", ".join(moins) if moins else "")


def marquants(evals, remplacants, habit):
    """Les 3 à 5 joueurs du Real à présenter, un tweet chacun : [(motif, éval)]. Le meilleur de chaque ligne s'il est au-dessus du
    repère, complété par les meilleurs scores (+0,15 au moins) jusqu'à 3 ; puis celui qui est en difficulté (score de -0,3 ou moins), le remplaçant qui
    a pesé (+0,4 ou plus) et celui qui sort le plus de ses habitudes, s'ils ne sont pas déjà choisis."""
    tri = sorted(evals, key=lambda e: -e[0])
    choix = []
    pris = lambda e: any(e[1] == x[1][1] for x in choix)
    for roles in LIGNES.values():
        e = next((e for e in tri if e[2] in roles), None)
        if e and e[0] >= 0.2:
            choix.append(("parmi les meilleurs", e))
    for e in tri:
        if len(choix) >= 3 or e[0] < 0.15:
            break
        if not pris(e):
            choix.append(("parmi les meilleurs", e))
    choix.sort(key=lambda x: -x[1][0])
    if tri and tri[-1][0] <= -0.3 and not pris(tri[-1]):
        choix.append(("en difficulté", tri[-1]))
    entre = next((e for e in tri if e[1] in remplacants and e[0] >= 0.4), None)
    if entre and not pris(entre) and len(choix) < 5:
        choix.append(("a changé le match en entrant", entre))
    hors = max((e for e in tri if not pris(e) and habit(e)), key=habit, default=None)
    if hors and len(choix) < 5:
        choix.append(("hors de ses habitudes", hors))
    for e in tri:  # au moins 3 tweets
        if len(choix) >= 3:
            break
        if not pris(e):
            choix.append(("à noter", e))
    return choix[:5]


def rapport(d, actions, xg, xgot, fin, mi, reperes=None):
    """Lignes de l'étape 6 : sur le match, chaque joueur du Real par ligne et, pour l'adversaire, le plus haut et le plus bas de
    chaque ligne ; par mi-temps, le plus haut et le plus bas de chaque ligne du Real."""
    reperes = reperes or json.loads(REPERES.read_text(encoding="utf-8"))
    noms = {int(k): v for k, v in d["playerIdNameDictionary"].items()}
    real = "home" if d["home"]["teamId"] == REAL else "away"
    lignes = [f"  (repères : {reperes['matchs']} matchs enregistrés ; score de -3 à 3, 0 = joueur moyen du même rôle ; raisons en nombres "
              "réels ; « habitudes » = comparé à ses propres matchs enregistrés ; ni les appels sans ballon ni le placement ne sont mesurés)"]

    def ligne_joueur(e, prefixe=""):
        s, pid, role, m, c, v, contrib = e
        hab = habitudes(pid, role, v, reperes)
        return (f"    {prefixe}{noms.get(pid, '?')} ({role}, {m:.0f}', score {s:+.1f}){raisons(role, c, v, contrib)}"
                + (f" ; {', '.join(hab)}" if hab else ""))

    def evaluer(cote, a, b, mini):
        return [(s, pid, role, m, c, v, contrib) for pid, role, m, c, v in evaluer_equipe(d, actions, xg, xgot, cote, a, b, mini)
                for s, contrib in [noter(role, v, reperes)]]

    for titre, a, b, cotes, mini in (("match", 0, fin, (real, "away" if real == "home" else "home"), 30),
                                     ("1re mi-temps", 0, mi, (real,), 20), ("2e mi-temps", mi, fin, (real,), 20)):
        lignes.append(f"  {titre}")
        for cote in cotes:
            evals = evaluer(cote, a, b, mini)
            for ligne, roles in LIGNES.items():
                ls = sorted((e for e in evals if e[2] in roles), key=lambda e: -e[0])
                if cote == real and titre == "match":
                    lignes.append(f"   {d[cote]['name']} - {ligne}")
                    lignes += [ligne_joueur(e) for e in ls]
                    if ligne == "attaque":  # dernière ligne : la sélection pour les tweets joueurs
                        remp = {p["playerId"] for p in d[cote]["players"] if not p.get("isFirstEleven")}
                        habit = lambda e: habitudes_z(e[1], e[2], e[5], reperes)  # 0 : rien d'inhabituel
                        lignes.append("   sélection pour les tweets joueurs (un tweet chacun) :")
                        lignes += [ligne_joueur(e, f"{motif} : ") for motif, e in marquants(evals, remp, habit)]
                else:
                    choix = [("le plus haut", ls[0])] + ([("le plus bas", ls[-1])] if len(ls) > 1 else []) if ls else []
                    lignes += [ligne_joueur(e, f"{d[cote]['name']} - {ligne}, {etiquette} : ") for etiquette, e in choix]
    return lignes


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["--reperes"]:
        n, roles = construire_reperes()
        print(f"{REPERES.name} : {n} matchs ; joueurs par rôle (matchs entiers, 45 min au moins) : {roles}")
    elif len(sys.argv) == 2:
        dossier = Path(sys.argv[1])
        d = whoscored.lire((dossier / "whoscored.html").read_text(encoding="utf-8"))
        fm = json.loads((dossier / "fotmob.json").read_text(encoding="utf-8")) if (dossier / "fotmob.json").exists() else None
        actions, xg, xgot = preparer(d, fm)
        fin, mi = max(e["t"] for e in actions) + 0.1, 45 + bascules.horloge(d)[1]
        print("\n".join(rapport(d, actions, xg, xgot, fin, mi)))
    else:
        sys.exit(__doc__)

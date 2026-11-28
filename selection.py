"""Politique éditoriale (P2 de l'audit du 28 nov.) : plusieurs dimensions notées séparément, puis une décision selon la phase.

- notées par le tri (Claude, sur titre et chapeau), de 0 à 3 : importance, originalité (face à « déjà publié »), intérêt pour
  un supporter du Real, urgence ; et si l'information est confirmée ;
- calculée par le code : fiabilité de la source (1 = site du club, 2 = grande presse, 3 = par défaut, 4 = seconde main ;
  "niveaux_sources" dans config.json) ;
- décision : PUBLISH, IGNORE ou REVIEW (brouillon à relire), selon la phase de calendrier.phase().

Mode observation (28 nov.) : chaque décision est enregistrée dans la table `decisions` (motif
compris), le tri actuel décide seul de ce qui est publié. Comparer les deux pendant une semaine (python selection.py), calibrer, puis coder l'activation avec l'utilisateur.
"""
from datetime import timedelta

from calendrier import LIVE, POST, PRE
from commun import CONFIG, maintenant

NOTES = ("importance", "originalite", "interet", "urgence")


def fiabilite(it):
    if it.get("officiel"):
        return 1
    journal = it["source"].split(" - ")[0]
    niveaux = CONFIG.get("niveaux_sources", {})
    return next((int(n) for n, journaux in niveaux.items() if n.isdigit() and journal in journaux), 3)


def notes_valides(r):
    """Notes du tri bornées à 0..3 ; None si l'une manque ou n'est pas un nombre (décision impossible : REVIEW)."""
    try:
        return {k: max(0, min(3, int(r[k]))) for k in NOTES}
    except (KeyError, TypeError, ValueError):
        return None


def decider(type_, notes, fiab, phase, confirme=True):
    """(décision, motif). Règles volontairement lisibles, à calibrer sur la semaine d'observation."""
    if fiab == 1:
        return "PUBLISH", "site du club"
    if type_ == "conference":  # chaque déclaration part (choix du 28 nov.), l'anti-doublon écarte les répétitions
        return "PUBLISH", "conférence"
    if notes is None:
        return "REVIEW", "notes du tri absentes ou invalides"
    imp, ori, inte, urg = (notes[k] for k in NOTES)
    if phase == LIVE:  # pendant le match : seulement ce qui ne peut pas attendre
        return ("PUBLISH", "urgent pendant le match") if urg >= 2 or imp == 3 else ("IGNORE", "attend la fin du match")
    if type_ == "opinion":
        seuil = 1 if phase == POST else 2  # après un match, les analyses sont attendues
        if fiab == 4:
            return "IGNORE", "opinion de seconde main"
        if ori >= 2 and inte >= seuil:
            return "PUBLISH", f"opinion originale (originalité {ori}, intérêt {inte})"
        return "IGNORE", f"opinion peu originale ou peu utile (originalité {ori}, intérêt {inte})"
    # information
    if not confirme and fiab >= 3 and imp >= 2:
        return "REVIEW", "rumeur importante d'une source peu sûre"
    if ori == 0:
        return "IGNORE", "déjà publiée"
    seuil = 1 if phase == PRE else 2  # avant un match, les petites nouvelles (blessés, groupe) comptent
    if imp >= seuil or (inte >= 2 and ori >= 2):
        return "PUBLISH", f"information (importance {imp}, intérêt {inte})"
    return "IGNORE", f"information secondaire (importance {imp}, intérêt {inte})"


def connexion_decisions(con):
    con.execute("""CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY, date TEXT, phase TEXT, lien TEXT, journal TEXT,
        titre TEXT, type TEXT, importance INTEGER, originalite INTEGER, interet INTEGER, urgence INTEGER, confirme INTEGER,
        fiabilite INTEGER, decision TEXT, motif TEXT, actuel TEXT)""")


def noter(con, gardes, ecartes, phase):
    """Enregistre la décision de chaque article trié (notes du tri dans it["_tri"]) ; actuel : ce que le tri actuel a fait
    (garde / ecarte), pour comparer pendant l'observation. Retourne {lien: décision}."""
    connexion_decisions(con)
    now = maintenant().isoformat(timespec="seconds")
    sortie = {}
    for it, actuel in [(it, "garde") for it in gardes] + [(it, "ecarte") for it in ecartes]:
        r = it.get("_tri") or {}
        notes, fiab = notes_valides(r), fiabilite(it)
        confirme = r.get("confirme") is not False
        if actuel == "ecarte":
            decision, motif = "IGNORE", "écarté par le tri"
        else:
            decision, motif = decider(it.get("type"), notes, fiab, phase, confirme)
        n = notes or {}
        con.execute("INSERT INTO decisions (date, phase, lien, journal, titre, type, importance, originalite, interet, urgence,"
                    " confirme, fiabilite, decision, motif, actuel) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (now, phase, it["lien"], it["source"].split(" - ")[0], it["titre"][:200], it.get("type"),
                     *(n.get(k) for k in NOTES), int(confirme), fiab, decision, motif, actuel))
        sortie[it["lien"]] = decision
    con.commit()
    return sortie


def rapport(con, jours=7):
    """Bilan de l'observation : décisions par phase et par type, et désaccords avec le tri actuel (à calibrer)."""
    connexion_decisions(con)
    depuis = (maintenant() - timedelta(days=jours)).isoformat(timespec="seconds")
    lignes = [f"Décisions des {jours} derniers jours (mode observation)", ""]
    for phase_, type_, decision, nb in con.execute(
            "SELECT phase, type, decision, count(*) FROM decisions WHERE date >= ? AND actuel = 'garde'"
            " GROUP BY phase, type, decision ORDER BY phase, type, decision", (depuis,)):
        lignes.append(f"  {phase_:15} {type_ or '?':11} {decision:8} {nb}")
    lignes += ["", "Gardés par le tri actuel mais IGNORE ou REVIEW pour la sélection (les 40 derniers) :"]
    for journal, titre, decision, motif in con.execute(
            "SELECT journal, titre, decision, motif FROM decisions WHERE date >= ? AND actuel = 'garde' AND decision != 'PUBLISH'"
            " ORDER BY id DESC LIMIT 40", (depuis,)):
        lignes.append(f"  {decision:7} {journal} | {titre[:80]} ({motif})")
    return "\n".join(lignes)


if __name__ == "__main__":
    import sqlite3
    import sys
    from commun import DB_PATH, restaurer_base
    sys.stdout.reconfigure(encoding="utf-8")
    restaurer_base(DB_PATH)
    print(rapport(sqlite3.connect(DB_PATH)))

"""Tableau de bord de l'équipe d'agents : alertes classées par gravité, chiffres comparés à hier, graphiques, « daily » de
chaque agent et aide. Lit la base, l'historique GitHub Actions, l'issue du lundi et l'API Typefully, sans appel à Claude.
Publié sur GitHub Pages après chaque passage.

    python statut.py        → statut/index.html
"""
import json
import os
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, time, timedelta

from calendrier import LIVE, POST, PRE, phase_et_match
from commun import BASE, DB_PATH, e, maintenant, restaurer_base
from threads import ENVOYES, heure_madrid

SORTIE = BASE / "statut"
DEPOT = os.environ.get("GITHUB_REPOSITORY", "TemimiAlaaEddine/madridistas-arabes")
GH = f"https://github.com/{DEPOT}"
ARCHITECTURE = "https://claude.ai/artifact/KDwticb78QjLtewstW3N5e"
RUBRIQUES = {"actus": "Actus", "tactique": "Tactique", "mercato": "Mercato", "club": "Club", "debats": "Débats"}
JOURNAUX = {"marca": "Marca", "as": "AS"}
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
PUBLIENT = [("mise_a_jour.yml", "Mise à jour du site et threads"), ("suivi_direct.yml", "Suivi du match en direct"),
            ("conference_direct.yml", "Conférence de presse en direct"), ("apres_match.yml", "Analyse d'après-match")]
SILENCE_MAX = 40  # min sans passage avant l'alerte « panne » (les passages tournent toutes les ~6 à 10 min)


def iso(d):
    return d.isoformat(timespec="seconds")


def hm(utc):
    """« 23/11 à 18 h 42 », heure de Madrid."""
    m = heure_madrid(utc)
    return f"{m:%d/%m} à {m:%H} h {m:%M}"


MASQUE = re.compile(r"(access_token|token|key|secret|password)=[^&\s\"'<>]+|\b[A-Za-z0-9_\-]{40,}\b", re.I)


def masquer(texte):
    """Messages d'erreur affichés sur une page publique : aucun jeton ni clé, même collés dans une adresse."""
    return MASQUE.sub(lambda m: f"{m.group(1)}=…" if m.group(1) else "…", texte or "")


def api(chemin):
    """GET sur l'API GitHub (jeton facultatif : le dépôt est public)."""
    entetes = {"Accept": "application/vnd.github+json", "User-Agent": "statut-madridistas"}
    if os.environ.get("GH_TOKEN"):
        entetes["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    with urllib.request.urlopen(urllib.request.Request(f"https://api.github.com/repos/{DEPOT}/{chemin}", headers=entetes), timeout=20) as r:
        return json.load(r)


ECHECS = ("failure", "timed_out", "startup_failure")


def alertes_workflows(workflows, derniers):
    """Blocages du Veilleur hors passages : fichier de workflow invalide (GitHub lui donne alors son chemin pour nom) et
    dernier run en échec des autres workflows. Un run « push » d'un workflow redevenu valide est l'ancien fichier
    invalide, déjà réparé (aucun workflow du dépôt ne se déclenche sur un push). derniers = {id: [runs, du plus récent]}."""
    alertes = []
    for wf in workflows:
        if wf["name"] == wf["path"]:
            alertes.append(f"fichier de workflow invalide : {wf['path']} (voir le courriel de GitHub)")
            continue
        if wf["path"].endswith(("mise_a_jour.yml", "revue_sources.yml")):
            continue  # passages : bilan du Veilleur ; revue : fiches du lundi
        run = next((r for r in derniers.get(wf["id"], []) if r.get("event") != "push" and r.get("status") == "completed"), None)
        if run and run.get("conclusion") in ECHECS:
            alertes.append(f"workflow « {wf['name']} » en échec ({run['created_at'][:16].replace('T', ' ')} UTC) : voir l'onglet Actions")
    return alertes


def revues_ouvertes(issues):
    """Issues « Revue des sources » encore ouvertes : décisions à cocher (puis commentaire /appliquer)."""
    return [{"numero": i["number"], "titre": i["title"], "url": i["html_url"],
             "a_decider": len(re.findall(r"^\s*- \[[ xX]\] (?:Retirer le flux|Ajouter le flux|Ajouter la graphie|Corriger la publication) `", i.get("body") or "", re.M))}
            for i in issues if i["title"].startswith("Revue des sources") and "pull_request" not in i]


def sante_issue(corps):
    """Lignes de la section « Santé technique » (sante.py) du dernier rapport du lundi : [(ok|alerte|ko|info, texte)]."""
    m = re.search(r"^## Santé technique\s*$(.*?)(?=^## |\Z)", corps or "", re.M | re.S)
    sortie = []
    for ligne in (m.group(1).splitlines() if m else []):
        ligne = ligne.strip()
        if ligne.startswith("- "):
            etat = "ko" if "❌" in ligne else "alerte" if "⚠️" in ligne else "ok" if "✅" in ligne else "info"
            sortie.append((etat, masquer(re.sub(r"[*`]|❌|⚠️|✅", "", ligne[2:]).strip())))
    return sortie


def lire_github(depuis):
    """Passages du workflow depuis `depuis` (UTC), dernière revue du lundi, alertes des autres workflows, revues ouvertes et
    dernier rapport du lundi (santé) ; vides si l'API ne répond pas, avec la raison dans `erreur`."""
    passages, revue, alertes, revues, sante, erreur = [], None, [], [], None, None
    try:
        for page in range(1, 6):
            lot = api(f"actions/workflows/mise_a_jour.yml/runs?per_page=100&page={page}&created=%3E%3D{depuis:%Y-%m-%dT%H:%M:%SZ}")["workflow_runs"]
            passages += lot
            if len(lot) < 100:
                break
        revue = (api("actions/workflows/revue_sources.yml/runs?per_page=1")["workflow_runs"] or [None])[0]
        workflows = api("actions/workflows?per_page=100")["workflows"]
        derniers = {wf["id"]: api(f"actions/workflows/{wf['id']}/runs?per_page=5")["workflow_runs"] for wf in workflows
                    if not wf["path"].endswith(("mise_a_jour.yml", "revue_sources.yml"))}
        alertes = alertes_workflows(workflows, derniers)
        revues = revues_ouvertes(api("issues?state=open&per_page=50"))
        rapport = next((i for i in api("issues?state=all&per_page=30") if i["title"].startswith("Revue des sources") and "pull_request" not in i), None)
        if rapport:
            sante = {"numero": rapport["number"], "url": rapport["html_url"], "date": rapport["created_at"], "lignes": sante_issue(rapport.get("body"))}
    except (OSError, ValueError, KeyError) as err:
        erreur = masquer(str(err))
        print(f"  ! statut : API GitHub injoignable ({erreur}), tableau sans les passages")
    return passages, revue, alertes, revues, sante, erreur


def compter(con, table, col, a, b, cond="1"):
    try:
        return con.execute(f"SELECT count(*) FROM {table} WHERE {col} >= ? AND {col} < ? AND {cond}", (iso(a), iso(b))).fetchone()[0]
    except sqlite3.OperationalError:  # table créée au premier usage
        return 0


def lignes(con, sql, *params):
    try:
        return con.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


def pluriel(n, mot, participe=""):
    s = "s" if n > 1 else ""
    return f"{n} {mot}{s}" + (f" {participe}{s}" if participe else "")


# marche à suivre affichée sur la fiche d'un agent « Bloqué » ou « T'attend »
MARCHES = {
    "collecteur": "Le système réessaie à chaque passage. Si rien n'est repéré pendant des heures, la revue du lundi dira quels flux ne répondent plus.",
    "redacteur": "Le système réessaie à chaque passage. Au 3e échec de suite, une issue « Alerte : envoi en échec » s'ouvre avec l'erreur : lis-la dans l'onglet Actions.",
    "memoire": "Va dans « À faire » : décoche les faits faux, puis « Valider sur GitHub » et « Submit new issue ».",
    "controleur": "Ouvre la liste « Threads bloqués » plus bas : pour chaque brouillon encore dans Typefully, publie-le, corrige-le ou supprime-le.",
    "editeur_x": "Le système réessaie à chaque passage. Si ça dure : regarde la tuile « Quota Typefully » (quota épuisé ?) puis l'erreur dans l'onglet Actions.",
    "facebook": "Le système réessaie à chaque passage. Si l'erreur parle du jeton : renouvelle-le (python threads.py sur le PC, puis gh secret set FACEBOOK_PAGE_TOKEN, voir LISEZMOI).",
    "resume": "Le résumé n'est tenté qu'entre minuit et 3 h et n'est pas rattrapé : si tu y tiens, rédige-le avec /script.",
    "unes": "Si tu veux les publier : onglet Actions → « Mise à jour du site et threads » → Run workflow, case « Publier tout de suite les unes ».",
    "archiviste": "Rien : les adresses manquantes sont relevées aux passages suivants.",
    "veilleur": "Ouvre l'onglet Actions et clique sur le dernier passage rouge pour lire l'erreur. S'il n'y a plus aucun passage : vérifie la tâche sur cron-job.org.",
    "sources": "Va dans « À faire » : ouvre l'issue, coche ce que tu acceptes, puis commente /appliquer.",
    "sante": "Lis la section « Santé technique » de l'issue du lundi : chaque ligne ❌ dit quoi faire.",
}


def agent(id_, emoji, nom, role, equipe, rangs, blocages=(), attente=(), actif=True, lien=None):
    etat = "bloque" if blocages else "attente" if attente else "demande" if equipe == "demande" else "ok" if actif else "repos"
    marche = MARCHES.get(id_, "Ouvre l'onglet Actions pour lire la dernière erreur.") if etat in ("bloque", "attente") else None
    if etat in ("bloque", "attente") and id_ in ("performance", "audit"):
        marche = "Relance la revue : onglet Actions → « Revue des sources » → Run workflow."
    return {"id": id_, "emoji": emoji, "nom": nom, "role": role, "equipe": equipe, "rangs": rangs,
            "blocages": list(blocages) + list(attente), "etat": etat, "marche": marche, "lien": lien}


SERIES = {  # nom : (table, colonne de date, condition)
    "Articles rédigés": ("articles", "date", "1"),
    "Threads X": ("threads", "coalesce(envoye, date)", ENVOYES),
    "Posts Facebook": ("page_facebook", "date", "1"),
}

# règle du Contrôleur (statut « bloqué : … ») → explication en clair
REGLES = [("conférence", "conférence de presse déjà publiée en direct : un 2e thread ferait doublon"),
          ("en direct", "conférence de presse déjà publiée en direct : un 2e thread ferait doublon"),
          ("doublon", "même nouvelle qu'un thread déjà envoyé dans les 48 h"),
          ("trop long", "un tweet dépasse la longueur permise"),
          ("source absente", "le 1er tweet ne cite pas sa source"),
          ("engagement", "formule d'appel à l'engagement (« likez », « partagez »…)"),
          ("exclamation", "ton exagéré ou point d'exclamation")]


def expliquer(statut):
    regle = statut.split(":", 1)[-1].strip()
    sens = [t for cle, t in REGLES if cle in regle]
    return regle, (sens[0] if sens else "règle du contrôle qualité")


def alerte(niveau, quoi, pourquoi, action, lien=None, texte_lien=None):
    return {"niveau": niveau, "quoi": quoi, "pourquoi": pourquoi, "action": action, "lien": lien, "texte_lien": texte_lien}


NIVEAUX = {"panne": "Panne", "important": "Important", "surveiller": "À surveiller", "decision": "Décision"}


def repere(val, mediane):
    # shortcut: seuil fixe (moins de la moitié de la médiane des 7 jours précédents à la même heure), à ajuster si fausses alertes
    return "surveiller" if mediane >= 4 and val < mediane / 2 else "normal"


def donnees(con, utc, passages=(), revue=None, scripts=BASE / "scripts", videos=BASE / "videos", connaissance=BASE / "connaissance.md",
            alertes_gh=(), revues=(), quota=None, brouillons=None, sante=None, indispo=(), github_ok=True):
    dec = heure_madrid(utc) - utc
    madrid = utc + dec
    j0 = datetime.combine(madrid.date(), time()) - dec  # minuit à Madrid, en UTC
    hier, demain = j0 - timedelta(days=1), j0 + timedelta(days=1)
    pannes = {r[0]: r for r in lignes(con, "SELECT envoi, n, depuis, message FROM echecs")}
    indispo = list(indispo)
    alertes = []

    def panne(envoi):
        p = pannes.get(envoi)
        return [f"{envoi} en échec depuis {p[1]} passages : {masquer(p[3])[:140]}"] if p else []

    def deux(table, col, cond="1"):
        return compter(con, table, col, hier, j0, cond), compter(con, table, col, j0, demain, cond)

    # --- pipeline automatique
    vh, va = deux("vus", "date")
    ah, aa = deux("articles", "date")
    rubriques = lignes(con, "SELECT section, count(*) FROM articles WHERE date >= ? AND date < ? GROUP BY 1 ORDER BY 2 DESC", iso(j0), iso(demain))
    fh, fa = deux("faits", "date")
    relu = re.search(r"Dernier fait relu : (\d+)", connaissance.read_text(encoding="utf-8")) if connaissance.exists() else None
    a_valider = lignes(con, "SELECT f.id, date(f.date), f.fait, a.journal, a.lien FROM faits f LEFT JOIN articles a ON a.id = f.article_id "
                            "WHERE f.id > ? ORDER BY f.id LIMIT 60", int(relu.group(1)) if relu else 0)  # 60 par validation au plus
    faits_attente = (lignes(con, "SELECT count(*) FROM faits WHERE id > ?", int(relu.group(1)) if relu else 0) or [(0,)])[0][0]
    th, ta = deux("threads", "coalesce(envoye, date)", ENVOYES)
    imm = compter(con, "threads", "coalesce(envoye, date)", j0, demain, "statut = 'immédiat'")
    bh, ba = deux("threads", "date", "statut LIKE 'bloqu%'")

    # threads bloqués des 48 h : seuls ceux déposés en brouillon et encore dans Typefully t'attendent (brouillons = ids encore
    # en brouillon, None si illisible) ; « sans » (doublon, conférence déjà publiée) n'est jamais parti, rien à relire
    bloques, depuis48 = [], iso(utc - timedelta(hours=48))
    for date, statut, tf, journal, titre, lien in lignes(
            con, "SELECT t.date, t.statut, t.typefully, a.journal, a.titre, a.lien FROM threads t LEFT JOIN articles a ON a.id = t.article_id "
                 "WHERE t.date >= ? AND t.statut LIKE 'bloqu%' ORDER BY t.date DESC", depuis48) or lignes(  # sans titre ni lien : comptés quand même
            con, "SELECT date, statut, typefully, NULL, NULL, NULL FROM threads WHERE date >= ? AND statut LIKE 'bloqu%' ORDER BY date DESC", depuis48):
        regle, sens = expliquer(statut)
        if str(tf or "").isdigit():
            relire = brouillons is None or int(tf) in brouillons
            action = ("À relire : brouillon dans Typefully (publie, corrige ou supprime)" if brouillons is not None and relire else
                      "À vérifier dans Typefully (liste des brouillons illisible)" if relire else "Rien : brouillon déjà publié ou supprimé")
        else:
            relire, action = False, "Rien : jamais envoyé, aucun brouillon"
        bloques.append({"quand": hm(datetime.fromisoformat(date)), "journal": journal or "?", "titre": titre or "", "lien": lien,
                        "regle": regle, "sens": sens, "action": action, "relire": relire})
    b48 = sum(b["relire"] for b in bloques)

    pfh, pfa = deux("page_facebook", "date")
    xh, xa = deux("liens_x", "date")

    def resume(jour):
        r = lignes(con, "SELECT typefully FROM resumes WHERE jour = ?", jour.isoformat())
        if not r:
            return None
        return "rien à résumer (aucun article la veille)" if r[0][0] == "vide" else "publié sur X"
    r_auj, r_hier = resume(madrid.date() - timedelta(days=1)), resume(madrid.date() - timedelta(days=2))
    r_auj = r_auj or ("prévu entre minuit et 3 h (heure de Madrid)" if madrid.hour < 3 else "pas publié cette nuit")

    ok = lambda v: v not in (None, "sans", "vide")  # noqa: E731

    def unes(jour):
        r = lignes(con, "SELECT journal, x, facebook FROM unes WHERE jour = ? ORDER BY journal DESC", jour.isoformat())
        return ", ".join(f"{JOURNAUX.get(j, j)} : " + ("sans le Real, non publiée" if x == "sans" else
                         " + ".join(n for n, v in (("X", x), ("Facebook", fb)) if ok(v)) or "en cours") for j, x, fb in r) or "aucune"
    u_auj = unes(madrid.date())
    u_auj = u_auj if u_auj != "aucune" or madrid.hour < 6 else "aucune une publiée"
    unes_rows = lignes(con, "SELECT x FROM unes WHERE jour = ?", madrid.date().isoformat())

    fini = [p for p in passages if p.get("status") == "completed"]
    p_auj = [p for p in fini if p["created_at"] >= iso(j0)]
    p_hier = [p for p in fini if iso(hier) <= p["created_at"] < iso(j0)]
    p_hier_meme = [p for p in p_hier if p["created_at"] < iso(utc - timedelta(days=1))]
    rates = [p for p in p_auj if p.get("conclusion") != "success"]
    dernier = max((p["updated_at"] for p in fini), default=None)
    silence = (utc - datetime.fromisoformat(dernier.rstrip("Z"))).total_seconds() / 60 if dernier else None
    dernier_fini = max(fini, key=lambda p: p["updated_at"], default=None)
    debuts = sorted(datetime.fromisoformat(p["created_at"].rstrip("Z")) for p in passages if p["created_at"] >= iso(j0))
    ecarts = sorted((b - a).total_seconds() / 60 for a, b in zip(debuts, debuts[1:]))
    rythme = round(ecarts[len(ecarts) // 2]) if ecarts else None

    def bilan(lot):
        ok_ = sum(p.get("conclusion") == "success" for p in lot)
        return f"{pluriel(len(lot), 'passage')}, {ok_} réussi{'s' if ok_ > 1 else ''}" if lot else "historique indisponible"

    detail_rub = ", ".join(f"{n} {RUBRIQUES.get(s, s).lower()}" for s, n in rubriques)
    lien_bloques = ("Voir les threads bloqués", "#bloques") if bloques else None
    agents = [
        agent("collecteur", "📡", "Collecteur", "Lit les flux RSS, sitemaps et sites WordPress des journaux", "pipeline",
              [("Hier", pluriel(vh, "article", "repéré") + " dans les flux"), ("Aujourd'hui", pluriel(va, "article", "repéré"))],
              actif=va > 0),
        agent("redacteur", "✍️", "Rédacteur", "Trie et rédige en arabe le résumé commenté de chaque article (Claude)", "pipeline",
              [("Hier", pluriel(ah, "article", "rédigé")), ("Aujourd'hui", pluriel(aa, "article", "rédigé") + (f" ({detail_rub})" if detail_rub else ""))],
              panne("Claude (rédaction)"), actif=aa > 0),
        agent("memoire", "🧠", "Mémoire", "Note les faits durables de chaque article (table des faits)", "pipeline",
              [("Hier", pluriel(fh, "fait", "noté")), ("Aujourd'hui", pluriel(fa, "fait", "noté"))],
              attente=[f"{pluriel(faits_attente, 'fait')} attendent ta validation"] if faits_attente else [], actif=fa > 0),
        agent("controleur", "🛡️", "Contrôleur qualité", "Vérifie chaque thread avant l'envoi : longueur, source, ton, doublons", "pipeline",
              [("Hier", pluriel(th + bh, "thread", "contrôlé") + f", {bh} bloqué(s)"), ("Aujourd'hui", pluriel(ta + ba, "thread", "contrôlé") + f", {ba} bloqué(s)")],
              attente=[f"{pluriel(b48, 'thread')} mis en brouillon à relire dans Typefully (48 h)"] if b48 else [], actif=ta + ba > 0, lien=lien_bloques),
        agent("editeur_x", "𝕏", "Éditeur X", "Découpe les articles en threads et les dépose dans Typefully", "pipeline",
              [("Hier", pluriel(th, "thread", "envoyé")), ("Aujourd'hui", pluriel(ta, "thread", "envoyé") + f", dont {imm} publié(s) tout de suite")],
              panne("Typefully"), actif=ta > 0),
        agent("facebook", "📘", "Éditeur Facebook", "Publie les nouvelles sur la Page en français, anglais et espagnol", "pipeline",
              [("Hier", pluriel(pfh, "post", "publié")), ("Aujourd'hui", pluriel(pfa, "post", "publié"))],
              panne("Page Facebook"), actif=pfa > 0),
        agent("resume", "📌", "Résumé du jour", "Thread « حصاد ريال مدريد » : les 3 sujets de la veille, après minuit", "pipeline",
              [("Hier", r_hier or "aucune trace"), ("Aujourd'hui", r_auj)], panne("Résumé du jour"), actif=r_auj == "publié sur X"),
        agent("unes", "📰", "Revue des unes", "Traduit et publie les unes de Marca et AS, entre minuit et midi", "pipeline",
              [("Hier", unes(madrid.date() - timedelta(days=1))), ("Aujourd'hui", u_auj)], actif="X" in u_auj),
        agent("archiviste", "🔗", "Archiviste X", "Relève l'adresse X de chaque publication, pour les statistiques", "pipeline",
              [("Hier", pluriel(xh, "adresse", "relevée")), ("Aujourd'hui", pluriel(xa, "adresse", "relevée"))], actif=xa > 0),
        agent("veilleur", "🚨", "Veilleur", "Suit les passages et tous les workflows ; issue au 3e échec de suite", "pipeline",
              [("Hier", bilan(p_hier)), ("Aujourd'hui", bilan(p_auj))],
              ([pluriel(len(rates), "passage") + " en échec aujourd'hui"] if rates else [])
              + ([f"aucun passage depuis {round(silence)} min : vérifier cron-job.org"] if silence and silence > SILENCE_MAX else [])
              + [f"{p[0]} en échec depuis {p[1]} passages" for p in pannes.values()] + list(alertes_gh), actif=bool(p_auj)),
    ]

    # --- revue du lundi (un workflow, quatre rapports dans une issue)
    lundi = (madrid.date() + timedelta(days=(7 - madrid.weekday()) % 7 or 7)).strftime("%d/%m")
    if revue:
        quand = datetime.fromisoformat(revue["created_at"].rstrip("Z")) + dec
        reussi = revue.get("conclusion") == "success"
        dernier_rapport = f"{JOURS[quand.weekday()]} {quand:%d/%m} à {quand:%H:%M}, " + ("réussi" if reussi else f"« {revue.get('conclusion') or 'en cours'} »")
    else:
        reussi, dernier_rapport = True, "historique indisponible"
    lignes_sante = (sante or {}).get("lignes", [])
    lien_rapport = (f"Lire le rapport (issue n° {sante['numero']})", sante["url"]) if sante else None
    for id_, emoji, nom, role in [("sources", "🧭", "Revue des sources", "Santé des flux, rendement, sources à ajouter ou retirer"),
                                  ("performance", "📊", "Analyste Facebook", "Semaine comparée, posts par format et par heure"),
                                  ("audit", "⚖️", "Auditeur", "Relit 20 publications tirées au hasard face à leur article"),
                                  ("sante", "🩺", "Santé technique", "Jeton Facebook, quota Typefully, pannes en cours")]:
        en_attente = [f"issue n° {r['numero']} : " + (f"{pluriel(r['a_decider'], 'décision')} à cocher, puis commente /appliquer" if r["a_decider"]
                       else "ouverte sans décision à cocher, à fermer une fois lue") for r in revues] if id_ == "sources" else []
        bloc = [] if reussi else ["dernier rapport en échec : voir l'onglet Actions"]
        rangs = [("Dernier rapport", dernier_rapport), ("Prochain", f"lundi {lundi}, 7 h (Madrid)")]
        if id_ == "sante":  # le vrai résultat des contrôles, pas seulement la réussite du workflow
            bloc += [t for et, t in lignes_sante if et == "ko"]
            en_attente = [t for et, t in lignes_sante if et == "alerte"]
            rangs.append(("Contrôles", f"{sum(et == 'ok' for et, _ in lignes_sante)} OK sur {len(lignes_sante)}" if lignes_sante else
                          "donnée indisponible (section introuvable dans l'issue du lundi)"))
        agents.append(agent(id_, emoji, nom, role, "lundi", rangs, bloc, attente=en_attente, lien=lien_rapport))

    # --- équipe à la demande (Claude Code)
    textes = sorted(scripts.glob("*.md")) if scripts.exists() else []
    films = sorted(d.name for d in videos.iterdir() if d.is_dir()) if videos.exists() else []
    sans_trace = "pas d'historique (cet agent ne garde pas de trace)"
    for id_, emoji, nom, role, derniere, appel in [
        ("sujets", "🎯", "Rédacteur en chef", "Les 3 sujets du jour qui méritent ton avis", sans_trace, "/sujets"),
        ("moderation", "💬", "Community manager", "Commentaires Facebook sans réponse, réponses proposées", sans_trace, "/moderation"),
        ("angles", "♟️", "Analyste tactique", "3 angles d'analyse sourcés à développer", sans_trace, "/angles <sujet>"),
        ("script", "📝", "Plume d'analyse", "Threads et articles d'opinion, avec leurs sources",
         f"{textes[-1].stem} ({pluriel(len(textes), 'texte')} au total)" if textes else "aucun texte", "/script thread sur <sujet>"),
        ("video", "🎬", "Réalisateur vidéo", "Vidéos verticales en scènes rythmées",
         f"{', '.join(films)} ({pluriel(len(films), 'vidéo')})" if films else "aucune vidéo", "/video <sujet>"),
    ]:
        agents.append(agent(id_, emoji, nom, role, "demande", [("Dernière production", derniere), ("Pour l'appeler", appel)]))

    # --- alertes « À traiter maintenant »
    wf = f"{GH}/actions/workflows/mise_a_jour.yml"
    if not github_ok:
        indispo.append("Passages, workflows et issues : donnée indisponible, l'API GitHub n'a pas répondu au moment de la génération.")
    elif dernier is None:
        alertes.append(alerte("panne", "Aucun passage terminé dans les 2 derniers jours.", "Plus rien n'est collecté ni publié.",
                              "Vérifie la tâche sur cron-job.org, puis lance un passage : « Run workflow ».", wf, "Ouvrir le workflow"))
    elif silence > SILENCE_MAX:
        alertes.append(alerte("panne", f"Aucun passage depuis {round(silence)} min (dernier le {hm(datetime.fromisoformat(dernier.rstrip('Z')))}).",
                              "Plus rien n'est collecté ni publié tant que les passages ne reprennent pas.",
                              "Vérifie la tâche sur cron-job.org, puis lance un passage à la main : « Run workflow ».", wf, "Ouvrir le workflow"))
    if dernier_fini and dernier_fini.get("conclusion") != "success":
        alertes.append(alerte("panne", "Le dernier passage a échoué.", "Si les suivants échouent aussi, rien n'est publié.",
                              "Rien dans l'immédiat, le système réessaie au passage suivant. Si ça se répète, lis l'erreur.",
                              dernier_fini.get("html_url"), "Lire l'erreur"))
    elif rates:
        alertes.append(alerte("surveiller", f"{pluriel(len(rates), 'passage')} en échec aujourd'hui, mais le dernier a réussi.",
                              "Un échec isolé (site lent, API saturée) est sans conséquence.", "Rien, le système a déjà repris.", wf, "Voir les passages"))
    for envoi, n, depuis, msg in pannes.values():
        alertes.append(alerte("panne", f"{envoi} : envoi en échec depuis {pluriel(n, 'passage')} ({masquer(msg)[:120]}).",
                              "Les publications de ce canal ne partent pas.",
                              "Rien, le système réessaie à chaque passage." if n < 3 else
                              "Une issue « Alerte : envoi en échec » est ouverte : lis l'erreur et la marche à suivre.",
                              f"{GH}/issues?q=is%3Aopen+Alerte" if n >= 3 else None, "Voir les alertes" if n >= 3 else None))
    for a in alertes_gh:
        alertes.append(alerte("important", a[0].upper() + a[1:] + ".", "Ce workflow ne fait plus son travail (direct, analyse ou faits).",
                              "Ouvre l'onglet Actions et lis l'erreur du dernier lancement en rouge.", f"{GH}/actions", "Onglet Actions"))
    if quota:
        utilise, total, projection, _ = quota
        pct = round(projection / total * 100) if total else 0
        if pct >= 80:
            alertes.append(alerte("important" if pct >= 100 else "surveiller",
                                  f"Quota Typefully projeté à {pct} % : {utilise}/{total} publications, ~{projection} en fin de mois au rythme actuel.",
                                  f"Au-delà de {total}, Typefully n'accepte plus de publication jusqu'au 1er du mois suivant.",
                                  "Décide si on ralentit les envois (moins de threads) ou si tu passes à une offre supérieure.",
                                  "https://typefully.com", "Ouvrir Typefully"))
    else:
        alertes.append(alerte("surveiller", "Quota Typefully illisible.", "La clé Typefully est peut-être refusée : sans elle, aucun thread ne part.",
                              "Si la tuile « Threads X » continue de monter, rien à faire. Sinon, renouvelle la clé TYPEFULLY_API_KEY."))
    for et, texte in lignes_sante:
        if et in ("ko", "alerte"):
            alertes.append(alerte("important" if et == "ko" else "surveiller", f"Santé technique du lundi : {texte}",
                                  "Contrôle hebdomadaire de sante.py (jeton, quota, pages du club, unes).",
                                  "Suis l'indication de la ligne ; elle sera revérifiée lundi prochain.", sante["url"], "Lire l'issue"))
    if b48:
        alertes.append(alerte("surveiller", f"{pluriel(b48, 'thread')} bloqué(s) par le contrôle qualité attend(ent) en brouillon dans Typefully.",
                              "Ils ne partiront pas tant que tu ne les publies pas.", "Relis-les : publie, corrige ou supprime.",
                              "#bloques", "Voir lesquels"))
    if madrid.hour >= 12 and not any(ok(x) for (x,) in unes_rows) and not (unes_rows and all(x == "sans" for (x,) in unes_rows)):
        alertes.append(alerte("surveiller", "Aucune une de Marca ou AS publiée aujourd'hui.", "La fenêtre des unes (minuit-midi) est passée.",
                              MARCHES["unes"], wf, "Ouvrir le workflow"))
    if madrid.hour >= 3 and r_auj == "pas publié cette nuit":
        alertes.append(alerte("surveiller", "Le résumé du jour « حصاد ريال مدريد » n'est pas parti cette nuit.",
                              "Il n'est tenté qu'entre minuit et 3 h et n'est pas rattrapé.", MARCHES["resume"]))
    for r in revues:
        alertes.append(alerte("decision", f"Revue des sources (issue n° {r['numero']}) : " +
                              (f"{pluriel(r['a_decider'], 'décision')} à prendre." if r["a_decider"] else "à lire puis fermer."),
                              "Les sources ajoutées ou retirées changent ce que le Collecteur lit.", "Suis les étapes de la section « À faire ».",
                              "#a-faire", "Voir les étapes"))
    if faits_attente:
        alertes.append(alerte("decision", f"{pluriel(faits_attente, 'fait')} noté(s) par la Mémoire à valider.",
                              "Les faits validés vont dans connaissance.md, que les agents relisent pour ne pas se tromper.",
                              "Décoche ce qui est faux dans « À faire », puis valide.", "#a-faire", "Valider"))
    alertes.sort(key=lambda a: list(NIVEAUX).index(a["niveau"]))
    indispo.append("Expiration du jeton Facebook : donnée indisponible. Le jeton n'est pas transmis au tableau de bord (workflows inchangés) ; "
                   "la revue du lundi vérifie seulement qu'il fonctionne" + next((f" : « {t} »" for _, t in lignes_sante if "Facebook" in t), "") + ".")
    if github_ok and not sante:
        indispo.append("Santé technique : donnée indisponible, aucune issue « Revue des sources » trouvée.")

    # --- chiffres : aujourd'hui jusqu'à maintenant, face à hier à la même heure et aux 7 jours précédents
    kpi = []
    for nom, (table, col, cond), cle in zip(("Articles rédigés", "Threads X", "Posts Facebook"), SERIES.values(), ("articles", "threads", "facebook")):
        val = compter(con, table, col, j0, utc, cond)
        prec = [compter(con, table, col, j0 - timedelta(days=k), utc - timedelta(days=k), cond) for k in range(1, 8)]
        med = sorted(prec)[3]
        kpi.append({"nom": nom, "valeur": str(val), "comparaison": f"hier à la même heure : {prec[0]} ({val - prec[0]:+d}) · habituel : {med}",
                    "repere": repere(val, med), "aide": None, "cle": cle})
    if github_ok:
        okh = sum(p.get("conclusion") == "success" for p in p_hier_meme)
        kpi.append({"nom": "Passages réussis", "valeur": f"{len(p_auj) - len(rates)}/{len(p_auj)}" if p_auj else "0",
                    "comparaison": f"hier à la même heure : {okh}/{len(p_hier_meme)}" + (f" · un toutes les ~{rythme} min" if rythme else ""),
                    "repere": "surveiller" if rates or not p_auj or (silence or 0) > SILENCE_MAX else "normal", "aide": "g-passage", "cle": "passages"})
    else:
        kpi.append({"nom": "Passages réussis", "valeur": "donnée indisponible", "comparaison": "l'API GitHub n'a pas répondu",
                    "repere": None, "aide": "g-passage", "cle": "passages"})
    if quota:
        utilise, total, projection, _ = quota
        pct = round(projection / total * 100) if total else 0
        kpi.append({"nom": "Quota Typefully", "valeur": f"{utilise}/{total}",
                    "comparaison": f"~{projection} en fin de mois ({pct} %) · comparaison avec hier indisponible : Typefully ne donne que le total du mois",
                    "repere": "surveiller" if pct >= 80 else "normal", "aide": "g-quota", "cle": "quota"})
    else:
        kpi.append({"nom": "Quota Typefully", "valeur": "donnée indisponible", "comparaison": "l'API Typefully n'a pas répondu",
                    "repere": None, "aide": "g-quota", "cle": "quota"})

    # --- graphiques
    semaine = iso(j0 - timedelta(days=6))
    graphes = {
        "jours": [(madrid.date() - timedelta(days=k)).strftime("%d/%m") for k in range(13, -1, -1)],
        "par_jour": {nom: [compter(con, t, c, j0 - timedelta(days=k), j0 - timedelta(days=k - 1), w) for k in range(13, -1, -1)]
                     for nom, (t, c, w) in SERIES.items()},
        "par_heure": {nom: [compter(con, t, c, j0 + timedelta(hours=h), j0 + timedelta(hours=h + 1), w) if h <= madrid.hour else None for h in range(24)]
                      for nom, (t, c, w) in SERIES.items()},
        "heure": madrid.hour,
        "rubriques": [(RUBRIQUES.get(s, s), n) for s, n in lignes(con, "SELECT section, count(*) FROM articles WHERE date >= ? GROUP BY 1 ORDER BY 2 DESC", semaine)],
        "journaux": lignes(con, "SELECT journal, count(*) FROM articles WHERE date >= ? GROUP BY 1 ORDER BY 2 DESC LIMIT 8", semaine),
    }
    return {"genere": iso(utc) + "Z", "genere_txt": hm(utc), "dernier_passage": dernier,
            "dernier_txt": hm(datetime.fromisoformat(dernier.rstrip("Z"))) if dernier else "donnée indisponible",
            "rythme": rythme, "kpi": kpi, "agents": agents, "graphes": graphes, "faits": a_valider, "revues": list(revues),
            "alertes": alertes, "bloques": bloques, "indispo": [masquer(i) for i in indispo], "phase": phase_et_match(utc)}


# phase éditoriale (calendrier.phase_et_match) : libellé affiché, préposition devant le match
PHASES = {LIVE: ("match en cours", ""), POST: ("après-match (24 h)", "après "), PRE: ("avant-match (24 h)", "avant ")}


def phase_html(ph):
    """Badge de la phase du moment, dans le bandeau du haut."""
    nom, match = ph or ("WEEK_MODE", None)
    libelle, prep = PHASES.get(nom, ("semaine normale", ""))
    detail = f" · {e(prep)}<bdi>{e(match)}</bdi>" if match else ""
    return f'<p class="phase ph-{nom.lower()}">Phase {q("g-phase", "phase")} : <b>{e(nom)}</b> <small>({e(libelle)}{detail})</small></p>'


ETATS = {"ok": "Actif", "attente": "T'attend", "bloque": "Bloqué", "repos": "Au repos", "demande": "Sur demande"}


def equipes(rythme):
    return {"pipeline": ("⚙️ Pipeline automatique", f"un passage toutes les ~{rythme} min aujourd'hui (mesuré), sur GitHub Actions"
                         if rythme else "rythme des passages indisponible (historique GitHub illisible)"),
            "lundi": ("📅 Revue du lundi", "chaque lundi à 7 h, en issue GitHub"),
            "demande": ("🧑‍💻 Équipe à la demande", "dans Claude Code, quand tu l'appelles")}


def q(ancre, sujet):
    """Pastille « ? » qui mène à la définition du glossaire."""
    return f'<a class="q" href="#{ancre}" aria-label="Aide : {e(sujet)}" title="{e(sujet)} : voir le glossaire">?</a>'


def a_faire(faits, revues=()):
    """Section « À faire » : revues du lundi à décider (lien vers l'issue, pas à pas) et faits notés à valider (cases à cocher,
    puis une issue pré-remplie que le workflow « Validation des faits » traite ; seule une issue du propriétaire compte)."""
    if not (faits or revues):
        return ""
    appliquer = f"{GH}/actions/workflows/appliquer_revue.yml"

    def revue(r):
        lien = f'<a href="{e(r["url"])}" target="_blank" rel="noopener">issue n° {r["numero"]}</a>'
        if not r["a_decider"]:
            etapes = (f"<li>Ouvre l'{lien} et lis le rapport.</li><li>Il n'y a pas de case à cocher (revue d'avant les cases) : "
                      "applique à la main ce qui te convient, puis ferme l'issue (bouton « Close issue » en bas).</li>")
        else:
            etapes = (f"<li>Ouvre l'{lien} (sur GitHub, connecté avec ton compte ; ça marche aussi dans l'appli GitHub du téléphone).</li>"
                      "<li>Chaque case est une proposition : <b>retirer un flux</b> (source qui ne donne plus rien), <b>ajouter un flux</b> "
                      "(nouvelle source repérée), <b>ajouter une graphie</b> (écriture arabe d'un nom) ou <b>corriger une publication</b> "
                      "(écart relevé par l'Auditeur). Le rapport juste au-dessus dit pourquoi.</li>"
                      "<li>Coche directement dans l'issue ce que tu acceptes. Ce que tu laisses décoché est ignoré.</li>"
                      f"<li>En bas de l'issue, écris le commentaire <code>/appliquer</code> {q('g-appliquer', '/appliquer')} puis clique sur « Comment ». "
                      "Seul ton compte GitHub peut le faire.</li>"
                      f"<li><b>Ensuite</b> : le workflow « <a href=\"{appliquer}\" target=\"_blank\" rel=\"noopener\">Appliquer la revue des sources</a> » "
                      "modifie <code>config.json</code> (flux et graphies), l'enregistre et ferme l'issue avec le résumé des changements (1 à 2 min). "
                      "Ils comptent dès le passage suivant. Les corrections de publications cochées ne sont pas faites automatiquement : "
                      "le résumé les liste, à corriger à la main sur X ou Facebook. En cas d'erreur, l'issue reste ouverte avec un message.</li>")
        decide = pluriel(r["a_decider"], "décision") if r["a_decider"] else "à lire"
        return (f'<li class="revue"><b>🧭 {e(r["titre"])}</b> <span>({decide})</span><ol class="etapes">{etapes}</ol>'
                f'<a class="bouton" href="{e(r["url"])}" target="_blank" rel="noopener">Ouvrir l’issue n° {r["numero"]} →</a></li>')
    bloc_revues = (f'<h3>Revue des sources {q("g-issue", "issue")}</h3><ul class="revues">{"".join(revue(r) for r in revues)}</ul>') if revues else ""
    if not faits:
        return f'<section class="carte a-faire" id="a-faire"><h2>À faire</h2>{bloc_revues}</section>'

    def ligne(i, d, f, j, lien):
        source = f' <a href="{e(lien)}" target="_blank" rel="noopener">{e(j)}</a>' if lien else ""
        return f'<li><label><input type="checkbox" name="fait" value="{i}" checked><span><b>n° {i}</b> · {e(d)} · {e(f)}{source}</span></label></li>'
    return (f'<section class="carte a-faire" id="a-faire"><h2>À faire</h2>{bloc_revues}'
            f'<h3>{pluriel(len(faits), "fait")} à valider {q("g-faits", "table des faits")} <small>notés par la Mémoire</small></h3>'
            f'<p class="aide">Décoche ce qui est faux ou sans intérêt, puis « Valider sur GitHub » et « Submit new issue ». Claude range les faits '
            f'cochés dans <code>connaissance.md</code> (bonne section, fusion, tableau des matchs) ; les décochés ne reviennent pas. '
            f'La liste disparaît au passage suivant (10 min environ).</p>'
            f'<form id="form-faits" data-depot="{e(DEPOT)}" data-dernier="{faits[-1][0]}"><ul class="faits">{"".join(ligne(*f) for f in faits)}</ul>'
            f'<div class="boutons"><button type="button" data-tout="1">Tout cocher</button><button type="button" data-tout="0">Tout décocher</button>'
            f'<button type="submit" class="principal">Valider sur GitHub →</button></div></form></section>')


def zone_alertes(alertes, indispo):
    perimee = ('<li class="alerte n-panne" id="alerte-perimee" hidden><span class="niveau">Panne</span><div><b>Données périmées : le pipeline '
               "s'est peut-être arrêté.</b><p>Cette page n'a pas été régénérée depuis plus de 30 min, alors qu'elle l'est après chaque passage.</p>"
               '<p class="action">À faire : ouvre l\'onglet Actions ; s\'il n\'y a aucun passage récent, vérifie cron-job.org puis « Run workflow ».</p>'
               f'<a href="{GH}/actions/workflows/mise_a_jour.yml" target="_blank" rel="noopener">Ouvrir le workflow →</a></div></li>')

    def li(a):
        lien = ""
        if a["lien"]:
            externe = "" if a["lien"].startswith("#") else ' target="_blank" rel="noopener"'
            lien = f'<a href="{e(a["lien"])}"{externe}>{e(a["texte_lien"] or "Ouvrir")} →</a>'
        return (f'<li class="alerte n-{a["niveau"]}"><span class="niveau">{NIVEAUX[a["niveau"]]}</span><div><b>{e(a["quoi"])}</b>'
                f'<p>{e(a["pourquoi"])}</p><p class="action">À faire : {e(a["action"])}</p>{lien}</div></li>')
    calme = ('<p class="calme" id="calme">✅ <b>Rien à traiter.</b> Tout ce que la page peut vérifier est normal. '
             'Elle se met à jour après chaque passage.</p>') if not alertes else ""
    titre = f"À traiter maintenant <small>{pluriel(len(alertes), 'point')}, du plus grave au moins grave</small>" if alertes else "À traiter maintenant"
    manque = ("<details class=\"indispo\"><summary>Données indisponibles ({})</summary><ul>{}</ul></details>".format(
        len(indispo), "".join(f"<li>{e(i)}</li>" for i in indispo))) if indispo else ""
    return f'<section class="carte traiter" id="traiter"><h2>{titre}</h2><ul class="alertes">{perimee}{"".join(li(a) for a in alertes)}</ul>{calme}{manque}</section>'


def bloques_html(bloques):
    if not bloques:
        return ('<section class="carte" id="bloques"><h2>Threads bloqués {} <small>48 h</small></h2>'
                '<p class="aide">Aucun thread bloqué par le contrôle qualité ces dernières 48 h.</p></section>').format(q("g-controle", "contrôle qualité"))
    rangs = "".join(
        f'<tr><td>{e(b["quand"])}</td><td>{e(b["journal"])}</td><td><bdi dir="rtl">'
        + (f'<a href="{e(b["lien"])}" target="_blank" rel="noopener">{e(b["titre"])}</a>' if b["lien"] else e(b["titre"]))
        + f'</bdi></td><td><b>{e(b["regle"])}</b><br><small>{e(b["sens"])}</small></td>'
          f'<td class="{"a-relire" if b["relire"] else ""}">{e(b["action"])}</td></tr>' for b in bloques)
    a_relire = sum(b["relire"] for b in bloques)
    resume = (f"{pluriel(a_relire, 'thread')} t'attend{'ent' if a_relire > 1 else ''} dans Typefully." if a_relire else
              "Aucune action de ta part : ces threads n'ont jamais été envoyés.")
    return (f'<section class="carte" id="bloques"><h2>Threads bloqués {q("g-controle", "contrôle qualité")} <small>48 h · {len(bloques)}</small></h2>'
            f'<p class="aide">{resume}</p><div class="defile"><table><thead><tr><th>Quand</th><th>Source</th><th>Article</th><th>Règle</th>'
            f'<th>Ton action</th></tr></thead><tbody>{rangs}</tbody></table></div></section>')


def colonnes(etiquettes, series, pas, resume, vide):
    """Graphique en colonnes groupées, en HTML (sans script) ; le tableau des chiffres sert de version accessible."""
    valeurs = [x for v in series.values() for x in v if x is not None]
    if not any(valeurs):
        return f'<p class="vide">{e(vide)}</p>'
    m = max(valeurs)
    cols = "".join(
        '<div class="col"><div class="pile">' + "".join(
            f'<i class="s{i + 1}" style="height:{(v[k] or 0) / m * 100:.1f}%" title="{e(lab)} · {e(nom)} : {v[k]}"></i>' if v[k] is not None
            else '<i class="futur"></i>' for i, (nom, v) in enumerate(series.items()))
        + f'</div><small>{e(lab) if k % pas == 0 else ""}</small></div>' for k, lab in enumerate(etiquettes))
    legende = "".join(f'<span><i class="s{i + 1}"></i>{e(nom)}</span>' for i, nom in enumerate(series))
    tete = "".join(f"<th>{e(lab)}</th>" for lab in etiquettes)
    corps = "".join(f"<tr><th>{e(nom)}</th>" + "".join(f"<td>{'' if x is None else x}</td>" for x in v) + "</tr>" for nom, v in series.items())
    return (f'<p class="resume">{e(resume)}</p><div class="legende-g">{legende}</div>'
            f'<div class="colonnes" aria-hidden="true"><span class="max">{m}</span>{cols}</div>'
            f'<details><summary>Voir les chiffres</summary><div class="defile"><table><thead><tr><th></th>{tete}</tr></thead>'
            f'<tbody>{corps}</tbody></table></div></details>')


def barres(rangs, vide):
    if not rangs:
        return f'<p class="vide">{e(vide)}</p>'
    m = max(n for _, n in rangs) or 1
    return ('<ul class="barres">' + "".join(f'<li><span>{e(str(l))}</span><i style="--p:{n / m * 100:.0f}%"></i><b>{n}</b></li>' for l, n in rangs)
            + "</ul>")


def graphiques(g):
    h = g["heure"]
    tot = {nom: sum(x or 0 for x in v) for nom, v in g["par_heure"].items()}
    pointe = max(range(24), key=lambda k: sum(v[k] or 0 for v in g["par_heure"].values()))
    resume_h = (f"Aujourd'hui jusqu'à {h} h : " + ", ".join(f"{n} {nom.lower()}" for nom, n in tot.items())
                + (f". Heure la plus chargée : {pointe} h." if any(tot.values()) else "."))
    tot14 = {nom: sum(v) for nom, v in g["par_jour"].items()}
    resume_j = "Sur 14 jours : " + ", ".join(f"{n} {nom.lower()}" for nom, n in tot14.items()) + "."
    return ('<div class="graphes">'
            '<section class="carte"><h2>Aujourd\'hui, heure par heure <small>heure de Madrid</small></h2>'
            + colonnes([f"{k} h" for k in range(24)], g["par_heure"], 3, resume_h, "Rien de collecté ni publié depuis minuit (heure de Madrid).")
            + '</section><section class="carte"><h2>14 derniers jours</h2>'
            + colonnes(g["jours"], g["par_jour"], 2, resume_j, "Aucune donnée sur 14 jours : base vide ou illisible.")
            + '</section><section class="carte"><h2>Rubriques <small>articles rédigés, 7 jours</small></h2>'
            + barres(g["rubriques"], "Aucun article rédigé ces 7 derniers jours.")
            + '</section><section class="carte"><h2>Sources les plus reprises <small>articles rédigés par journal, 7 jours</small></h2>'
            + barres(g["journaux"], "Aucun article rédigé ces 7 derniers jours.") + "</section></div>")


PROBLEME = """<section class="carte" id="probleme"><h2>En cas de problème</h2>
<h3>Suspendre toutes les publications</h3>
<ol class="etapes"><li>Ouvre chacun des 4 workflows qui publient : {liens}.</li>
<li>Sur chaque page, bouton « ··· » en haut à droite → <b>Disable workflow</b>. Plus rien ne part à partir du passage suivant.</li>
<li>Les threads déjà <b>programmés</b> dans Typefully partent quand même : retire-les de la file dans <a href="https://typefully.com" target="_blank" rel="noopener">Typefully</a>.</li>
<li>Pendant la pause, cron-job.org signalera des erreurs : c'est attendu.</li></ol>
<h3>Relancer</h3>
<ol class="etapes"><li>Sur les mêmes pages : <b>Enable workflow</b>.</li>
<li>Sur « Mise à jour du site et threads » : <b>Run workflow</b> pour un passage tout de suite.</li>
<li>Vérifie que la tâche est toujours active sur cron-job.org, puis que « Dernier passage », en haut de cette page, indique moins de 10 min.</li></ol>
<h3>À quoi se fier</h3>
<ol class="etapes"><li><a href="{gh}/actions" target="_blank" rel="noopener">L'onglet Actions</a> {qa} : la référence. Chaque passage y est vert (réussi) ou rouge (échec, avec l'erreur).</li>
<li><a href="{gh}/issues" target="_blank" rel="noopener">Les issues</a> : « Alerte : envoi en échec » s'ouvre au 3e échec de suite d'un canal ; l'issue du lundi contient la santé technique.</li>
<li>Cette page : régénérée après chaque passage. Si elle a plus de 30 min, elle passe d'elle-même en alerte « Données périmées ».</li></ol></section>"""

GLOSSAIRE = [
    ("g-phase", "Phase", "Le moment du calendrier qui règle les priorités éditoriales, une seule à la fois : LIVE_MATCH (du coup d'envoi à 2 h 30 après), POST_MATCH_24H (les 24 h qui suivent), PRE_MATCH_24H (les 24 h avant un match), sinon WEEK_MODE. Les conférences et les compositions se superposent à la phase. Calculée d'après le calendrier du club (matchs.json) ; en observation, elle sert à noter les décisions de selection.py sans encore agir sur la publication."),
    ("g-passage", "Passage", "Un tour complet du pipeline : lire les journaux, rédiger, contrôler, publier. Lancé automatiquement par cron-job.org sur GitHub Actions, toutes les quelques minutes (le rythme mesuré est affiché dans l'organigramme)."),
    ("g-quota", "Quota Typefully", "Nombre de publications que l'offre Typefully autorise par mois (lu dans l'API Typefully). La projection prolonge le rythme du mois jusqu'au dernier jour. Au-delà du quota, plus aucune publication n'est acceptée avant le 1er du mois suivant."),
    ("g-rss", "Flux RSS", "La liste des derniers articles qu'un journal publie dans un format lisible par une machine. Le Collecteur la lit à chaque passage."),
    ("g-sitemap", "Sitemap", "Le plan du site qu'un journal publie pour les moteurs de recherche. Il sert à trouver les nouveaux articles quand le journal n'a pas de flux RSS."),
    ("g-actions", "GitHub Actions", "Les machines de GitHub qui exécutent le pipeline. L'onglet « Actions » du dépôt montre chaque lancement : vert = réussi, rouge = échec."),
    ("g-issue", "Issue", "Une fiche de discussion sur GitHub. Le système en ouvre une chaque lundi (revue des sources) et en cas de panne qui dure (3 échecs de suite)."),
    ("g-faits", "Table des faits", "Les faits durables (blessures, contrats, records) que la Mémoire relève dans les articles. Une fois validés par toi, ils vont dans connaissance.md, que les agents relisent pour ne pas se tromper."),
    ("g-controle", "Contrôle qualité", "Les règles vérifiées avant chaque thread : longueur, source citée, pas d'appel à l'engagement, pas de doublon d'un thread des 48 h ni d'une déclaration déjà tweetée en direct, ✅ réservé au site du club."),
    ("g-sujets", "/sujets", "Dans Claude Code (ouvert dans le dossier du projet) : les 3 sujets du jour qui méritent ta prise de position, plus les doublons et écarts de ton repérés."),
    ("g-moderation", "/moderation", "Dans Claude Code : lit les commentaires Facebook sans réponse et propose pour chacun une action et une réponse."),
    ("g-angles", "/angles", "Dans Claude Code : 3 angles d'analyse tactique sourcés sur un sujet, à développer ensuite."),
    ("g-script", "/script", "Dans Claude Code : rédige un thread X ou une publication Facebook d'analyse ou d'opinion, à partir de la base d'articles."),
    ("g-video", "/video", "Dans Claude Code : prépare une vidéo verticale en scènes rythmées."),
    ("g-appliquer", "/appliquer", "Commentaire à écrire sous l'issue « Revue des sources » sur GitHub (pas dans Claude Code) : applique à config.json les flux et graphies cochés, liste les corrections de publications à faire à la main, et ferme l'issue. Seul ton compte peut le faire."),
]


def page(d):
    agents = d["agents"]
    eq = equipes(d.get("rythme"))
    par_equipe = {k: [a for a in agents if a["equipe"] == k] for k in eq}
    niveaux = [a["niveau"] for a in d["alertes"]]
    if "panne" in niveaux:
        humeur = ("bloque", f"Panne en cours · {pluriel(len(niveaux), 'point')} à traiter")
    elif niveaux:
        humeur = ("attente", f"Ça tourne · {pluriel(len(niveaux), 'point')} à regarder")
    else:
        humeur = ("ok", "Tout tourne")

    def tuile(k):
        aide = q(k["aide"], k["nom"]) if k["aide"] else ""
        rep = f'<span class="repere r-{k["repere"]}">{"normal" if k["repere"] == "normal" else "à surveiller"}</span>' if k["repere"] else ""
        return (f'<div class="kpi"><span class="kpi-nom">{e(k["nom"])} {aide}</span><strong>{e(k["valeur"])}</strong>{rep}'
                f'<span class="delta">{e(k["comparaison"])}</span></div>')

    noeud = lambda a: (f'<a class="noeud e-{a["etat"]}" href="#{a["id"]}" title="{e(a["role"])}"><span class="em">{a["emoji"]}</span>'  # noqa: E731
                       f'<span>{e(a["nom"])}</span><i class="point" aria-label="{ETATS[a["etat"]]}"></i></a>')
    organi = "".join(f'<div class="branche"><div class="equipe-titre"><b>{t}</b><small>{e(s)}</small></div>'
                     f'<div class="noeuds">{"".join(noeud(a) for a in par_equipe[k])}</div></div>' for k, (t, s) in eq.items())

    def fiche(a):
        rangs = "".join(f'<div class="rang"><dt>{e(l)}</dt><dd>{e(t)}</dd></div>' for l, t in a["rangs"])
        bloc = "".join(f"<li>{e(b)}</li>" for b in a["blocages"]) or "<li class=rien>Aucun</li>"
        marche = f'<p class="marche"><b>Que faire :</b> {e(a["marche"])}</p>' if a["marche"] else ""
        lien = ""
        if a["lien"]:
            externe = "" if a["lien"][1].startswith("#") else ' target="_blank" rel="noopener"'
            lien = f'<a class="lire" href="{e(a["lien"][1])}"{externe}>{e(a["lien"][0])} →</a>'
        return (f'<article class="fiche e-{a["etat"]}" id="{a["id"]}"><header><span class="em">{a["emoji"]}</span><div><h3>{e(a["nom"])}</h3>'
                f'<p>{e(a["role"])}</p></div><span class="pastille">{ETATS[a["etat"]]}</span></header><dl>{rangs}</dl>'
                f'<div class="blocages"><span>Blocages</span><ul>{bloc}</ul></div>{marche}{lien}</article>')
    daily = "".join(f'<section class="equipe"><h2>{t} <small>{e(s)}</small></h2><div class="fiches">{"".join(fiche(a) for a in par_equipe[k])}</div></section>'
                    for k, (t, s) in eq.items())
    liens_wf = ", ".join(f'<a href="{GH}/actions/workflows/{f}" target="_blank" rel="noopener">{e(n)}</a>' for f, n in PUBLIENT)
    glossaire = "".join(f'<div id="{i}"><dt>{e(t)}</dt><dd>{e(x)}</dd></div>' for i, t, x in GLOSSAIRE)
    commandes = " · ".join(f'<a href="#g-{c}">/{c}</a>' for c in ("sujets", "moderation", "angles", "script", "video"))
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300"><meta name="robots" content="noindex"><title>Statut de l'équipe</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>⚽</text></svg>">
<style>{CSS}</style></head><body>
<header class="haut"><div><h1>Statut de l'équipe</h1><p><bdi>المدريديستا علاء</bdi> · agents du site, de X et de la Page Facebook</p>
<p class="liens-haut"><a href="{ARCHITECTURE}" target="_blank" rel="noopener">Architecture du système →</a> · <a href="#glossaire">Aide</a> · <a href="#probleme">En cas de problème</a></p></div>
<div class="etat-global e-{humeur[0]}" id="bandeau" data-genere="{d['genere']}" role="status">
<p class="humeur"><i class="point"></i><a href="#traiter" id="humeur">{e(humeur[1])}</a></p>
{phase_html(d.get("phase"))}
<p class="horaires">Dernier passage {q('g-passage', 'passage')} : <b>{e(d['dernier_txt'])}</b> <span data-age="{d['dernier_passage'] or ''}"></span><br>
Page mise à jour : <b>{e(d['genere_txt'])}</b> <span data-age="{d['genere']}"></span> <small>heure de Madrid</small></p>
<noscript><p class="horaires">Sans JavaScript, la page ne calcule pas son ancienneté : si la mise à jour a plus de 30 min, le pipeline s'est peut-être arrêté.</p></noscript></div></header>
<main>
{zone_alertes(d["alertes"], d.get("indispo", []))}
<div class="kpis">{"".join(tuile(k) for k in d["kpi"])}</div>
<p class="note-kpi">Chiffres d'aujourd'hui depuis minuit (heure de Madrid), comparés à hier à la même heure et à l'habituel (médiane des 7 jours précédents à la même heure).
« À surveiller » : moins de la moitié de l'habituel, échec de passage, ou quota projeté au-delà de 80 %.</p>
{a_faire(d["faits"], d.get("revues", []))}
{bloques_html(d.get("bloques", []))}
{graphiques(d["graphes"])}
<section class="carte"><h2>Organigramme</h2><div class="organi"><div class="chef">👤 <b>Toi</b><small>rédacteur en chef · tu décides et tu publies</small></div>
<div class="branches">{organi}</div></div>
<p class="legende">{"".join(f'<span class="e-{k}"><i class="point"></i>{v}</span>' for k, v in ETATS.items())}</p></section>
<h2 class="titre-daily">Daily de l'équipe <small>hier · aujourd'hui · blocages</small></h2>
{daily}
{PROBLEME.format(liens=liens_wf, gh=GH, qa=q('g-actions', 'GitHub Actions'))}
<section class="carte" id="glossaire"><h2>Aide</h2><p class="aide">Commandes : {commandes} · <a href="#g-appliquer">/appliquer</a></p><dl class="glossaire">{glossaire}</dl></section>
</main>
<footer>Généré par <code>statut.py</code> après chaque passage · données : base <code>articles.sql</code>, GitHub Actions, issue du lundi et API Typefully · sans appel à Claude
· <a href="{ARCHITECTURE}" target="_blank" rel="noopener">architecture</a></footer>
<script>{JS}</script></body></html>"""


CSS = """
:root{--fond:#f4f6fb;--carte:#fff;--texte:#14213d;--doux:#5b6785;--bord:#e3e7f0;--or:#b8901a;--bleu:#2f62c9;--violet:#7c4ddb;--vert:#15803d;
--ambre:#b45309;--jaune:#a16207;--rouge:#dc2626;--gris:#94a3b8;--ciel:#0284c7;--s1:var(--or);--s2:var(--bleu);--s3:var(--violet);
--ombre:0 1px 2px rgba(20,33,61,.06),0 4px 16px rgba(20,33,61,.06)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--fond:#0b1020;--carte:#141a2e;--texte:#e8ecf6;--doux:#a3aeca;--bord:#2a3452;
--or:#d6b13f;--bleu:#6b9bff;--violet:#a78bfa;--vert:#4ade80;--ambre:#fbbf24;--jaune:#facc15;--rouge:#f87171;--ciel:#38bdf8;
--ombre:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.25)}}
:root[data-theme="dark"]{--fond:#0b1020;--carte:#141a2e;--texte:#e8ecf6;--doux:#a3aeca;--bord:#2a3452;
--or:#d6b13f;--bleu:#6b9bff;--violet:#a78bfa;--vert:#4ade80;--ambre:#fbbf24;--jaune:#facc15;--rouge:#f87171;--ciel:#38bdf8}
*{box-sizing:border-box}html,body{overflow-x:hidden}html{scroll-behavior:smooth}
body{margin:0;background:var(--fond);color:var(--texte);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--bleu)}
h1,h2,h3{margin:0;line-height:1.25}h2{font-size:17px}h2 small,.equipe-titre small{color:var(--doux);font-weight:400;font-size:13px;margin-inline-start:6px}
.haut{display:flex;flex-wrap:wrap;gap:16px;justify-content:space-between;align-items:center;padding:24px max(16px,calc(50% - 600px));
background:linear-gradient(135deg,#14213d,#1f3a7a);color:#fff}.haut h1{font-size:26px}.haut p{margin:4px 0 0;opacity:.85}
.liens-haut a{color:#fff}
.etat-global{background:rgba(255,255,255,.1);padding:12px 16px;border-radius:12px;border-inline-start:5px solid var(--c);max-width:100%}
.etat-global p{margin:0}.humeur{display:flex;align-items:center;gap:8px;font-weight:700;font-size:17px}
.humeur a{color:#fff;text-decoration:underline;text-underline-offset:3px}.horaires{font-size:13px;opacity:.9;margin-top:6px!important}
.phase{display:inline-block;font-size:13px;margin-top:8px!important;padding:3px 10px;border-radius:999px;background:rgba(255,255,255,.14);opacity:1!important}
.phase b{letter-spacing:.02em}.ph-live_match{background:#c0392b}.ph-pre_match_24h{background:#8a5a12}.ph-post_match_24h{background:#2f6f4f}
.etat-global .q{color:#fff}
main{max-width:1200px;margin:0 auto;padding:20px 16px 40px;display:grid;gap:20px}
.carte,.fiche,.kpi{background:var(--carte);border:1px solid var(--bord);border-radius:14px;box-shadow:var(--ombre)}.carte{padding:18px;min-width:0}
.carte h3{font-size:15px;margin:16px 0 6px}
.q{display:inline-grid;place-items:center;width:20px;height:20px;border-radius:50%;border:1px solid currentColor;font-size:12px;font-weight:700;
text-decoration:none;color:var(--bleu);vertical-align:middle;line-height:1}
.alertes{list-style:none;margin:12px 0 0;padding:0;display:grid;gap:10px}
.alerte{display:grid;grid-template-columns:110px 1fr;gap:12px;padding:12px 14px;border-radius:10px;background:var(--fond);border-inline-start:5px solid var(--c)}
.alerte[hidden]{display:none}.alerte p{margin:3px 0 0;color:var(--doux);font-size:14px}.alerte .action{color:var(--texte)}
.alerte a{display:inline-block;margin-top:4px;font-weight:600;font-size:14px}
.niveau{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;color:var(--c)}
.n-panne{--c:var(--rouge)}.n-important{--c:var(--ambre)}.n-surveiller{--c:var(--jaune)}.n-decision{--c:var(--bleu)}
.calme{margin:10px 0 0;padding:14px;border-radius:10px;background:color-mix(in srgb,var(--vert) 12%,transparent);font-size:15px}
.indispo{margin-top:12px;font-size:14px;color:var(--doux)}.indispo summary{cursor:pointer}.indispo ul{margin:6px 0 0;padding-inline-start:20px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(170px,100%),1fr));gap:12px}
.kpi{padding:14px 16px;display:flex;flex-direction:column;gap:2px;min-width:0}.kpi-nom{color:var(--doux);font-size:13px}
.kpi strong{font-size:26px;line-height:1.2;overflow-wrap:anywhere}.delta{font-size:12px;color:var(--doux)}
.repere{align-self:flex-start;font-size:12px;font-weight:700;padding:1px 8px;border-radius:999px}
.r-normal{color:var(--vert);background:color-mix(in srgb,var(--vert) 14%,transparent)}
.r-surveiller{color:var(--ambre);background:color-mix(in srgb,var(--ambre) 16%,transparent)}
.note-kpi{margin:-8px 0 0;color:var(--doux);font-size:13px}
.point{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--c,var(--gris));flex:none}
.e-ok{--c:var(--vert)}.e-attente{--c:var(--ambre)}.e-bloque{--c:var(--rouge)}.e-repos{--c:var(--gris)}.e-demande{--c:var(--ciel)}
.etat-global.e-ok{--c:#4ade80}.etat-global.e-attente{--c:#fbbf24}.etat-global.e-bloque{--c:#f87171}
.e-ok .point,.e-bloque .point{box-shadow:0 0 0 0 var(--c);animation:pouls 2s infinite}
@keyframes pouls{70%{box-shadow:0 0 0 7px transparent}100%{box-shadow:0 0 0 0 transparent}}
@media (prefers-reduced-motion:reduce){.point{animation:none!important}html{scroll-behavior:auto}}
.organi{display:flex;flex-direction:column;align-items:center;margin-top:14px}
.chef{background:linear-gradient(135deg,#c9a227,#e6c35c);color:#14213d;padding:10px 20px;border-radius:12px;text-align:center;font-size:16px}
.chef small{display:block;font-size:12px;opacity:.8}
.branches{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;width:100%;margin-top:28px;position:relative}
.branches::before{content:"";position:absolute;top:-14px;left:16.66%;right:16.66%;border-top:2px solid var(--bord)}
.organi>.chef{position:relative}.organi>.chef::after{content:"";position:absolute;left:50%;top:100%;height:14px;border-left:2px solid var(--bord)}
.branche{position:relative;border:1px dashed var(--bord);border-radius:12px;padding:12px}
.branche::before{content:"";position:absolute;left:50%;top:-15px;height:14px;border-left:2px solid var(--bord)}
.equipe-titre{text-align:center;margin-bottom:10px}.equipe-titre small{display:block;margin:0}
.noeuds{display:grid;gap:6px}
.noeud{display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:9px;background:var(--fond);color:inherit;text-decoration:none;
border-inline-start:3px solid var(--c);transition:transform .15s}.noeud:hover,.noeud:focus-visible{transform:translateX(3px)}
.noeud span:nth-child(2){flex:1}.em{font-size:18px;width:24px;text-align:center}
.legende{display:flex;flex-wrap:wrap;gap:14px;justify-content:center;color:var(--doux);font-size:13px;margin:14px 0 0}
.legende span{display:flex;align-items:center;gap:6px}
.graphes{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}
.resume{margin:6px 0 8px;color:var(--doux);font-size:14px}.vide{color:var(--doux);font-size:14px;margin:10px 0 0}
.legende-g{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;color:var(--doux)}.legende-g span{display:flex;align-items:center;gap:5px}
.legende-g i{width:10px;height:10px;border-radius:3px;display:inline-block}
.s1{background:var(--s1)}.s2{background:var(--s2)}.s3{background:var(--s3)}
.colonnes{position:relative;display:flex;gap:2px;height:190px;margin-top:10px;padding-top:16px;border-bottom:1px solid var(--bord)}
.colonnes .max{position:absolute;top:0;left:0;font-size:11px;color:var(--doux)}
.col{flex:1;display:flex;flex-direction:column;min-width:0}
.pile{flex:1;display:flex;align-items:flex-end;gap:1px}.pile i{flex:1;min-height:0;border-radius:2px 2px 0 0}
.pile i.futur{height:100%;background:repeating-linear-gradient(-45deg,transparent 0 3px,var(--bord) 3px 4px);opacity:.5}
.col small{height:16px;margin-bottom:-18px;font-size:10px;color:var(--doux);white-space:nowrap;overflow:visible}
.graphes details{margin-top:26px;font-size:13px}.graphes summary{cursor:pointer;color:var(--bleu)}
.defile{overflow-x:auto;max-width:100%}table{border-collapse:collapse;font-size:13px;margin-top:8px;width:100%}
th,td{padding:5px 8px;border-bottom:1px solid var(--bord);text-align:start;vertical-align:top}thead th{color:var(--doux);font-weight:600}
td.a-relire{color:var(--ambre);font-weight:600}
.barres{list-style:none;margin:12px 0 0;padding:0;display:grid;gap:8px}
.barres li{display:grid;grid-template-columns:minmax(90px,38%) 1fr 36px;gap:8px;align-items:center;font-size:14px}
.barres span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.barres i{height:14px;width:var(--p);min-width:2px;background:var(--bleu);border-radius:4px}.barres b{text-align:end}
.titre-daily{font-size:20px;margin-top:8px}
.equipe h2{margin-bottom:10px}.fiches{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(300px,100%),1fr));gap:14px}
.fiche{padding:14px 16px;border-top:4px solid var(--c);scroll-margin-top:16px}.fiche:target{outline:2px solid var(--or)}
.fiche header{display:flex;gap:10px;align-items:flex-start}.fiche header div{flex:1}.fiche h3{font-size:16px}
.fiche header p{margin:2px 0 0;color:var(--doux);font-size:13px}
.pastille{font-size:12px;font-weight:600;padding:3px 9px;border-radius:999px;color:var(--c);background:color-mix(in srgb,var(--c) 14%,transparent);white-space:nowrap}
dl{margin:12px 0 0;display:grid;gap:8px}.rang{display:grid;grid-template-columns:120px 1fr;gap:8px}dt{color:var(--doux);font-size:13px}dd{margin:0}
.blocages{margin-top:10px;padding-top:10px;border-top:1px solid var(--bord);display:grid;grid-template-columns:120px 1fr;gap:8px}
.blocages span{color:var(--doux);font-size:13px}.blocages ul{margin:0;padding:0;list-style:none}.blocages li{color:var(--c)}
.blocages li.rien{color:var(--doux)}.marche{margin:10px 0 0;font-size:14px;padding:8px 10px;border-radius:8px;background:var(--fond)}
.lire{display:inline-block;margin-top:8px;font-size:14px;font-weight:600}
.a-faire{border:2px solid var(--ambre)}.a-faire h3 small{color:var(--doux);font-weight:400}
.revues{list-style:none;margin:8px 0 0;padding:0;display:grid;gap:8px}
.revue{padding:12px 14px;border-radius:9px;background:var(--fond);border-inline-start:3px solid var(--ambre)}.revue>span{color:var(--doux)}
.etapes{margin:8px 0 0;padding-inline-start:22px;display:grid;gap:6px;font-size:14px}
.bouton{display:inline-block;margin-top:10px;padding:8px 14px;border-radius:9px;background:#2f62c9;color:#fff;text-decoration:none;font-weight:600}
.aide{color:var(--doux);font-size:14px;margin:6px 0 12px}
.faits{list-style:none;margin:0;padding:0;display:grid;gap:6px;max-height:420px;overflow-y:auto}
.faits label{display:flex;gap:10px;align-items:flex-start;padding:8px 10px;border-radius:9px;background:var(--fond);cursor:pointer}
.faits input{margin-top:4px;width:18px;height:18px;accent-color:var(--vert);flex:none}
.faits label:has(input:not(:checked)) span{opacity:.5;text-decoration:line-through}
.boutons{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.boutons button{font:inherit;padding:8px 14px;border-radius:9px;border:1px solid var(--bord);background:var(--carte);color:var(--texte);cursor:pointer}
.boutons .principal{background:#15803d;border-color:#15803d;color:#fff;font-weight:600;margin-inline-start:auto}
.glossaire{grid-template-columns:repeat(auto-fill,minmax(min(320px,100%),1fr));gap:10px}
.glossaire div{padding:10px 12px;border-radius:9px;background:var(--fond);scroll-margin-top:16px}.glossaire div:target{outline:2px solid var(--or)}
.glossaire dt{color:var(--texte);font-weight:700;font-size:14px}.glossaire dd{font-size:14px;color:var(--doux)}
footer{text-align:center;color:var(--doux);font-size:13px;padding:0 16px 30px}
@media (max-width:800px){.branches,.graphes{grid-template-columns:minmax(0,1fr)}.branches::before,.branche::before{display:none}
.rang,.blocages,.alerte{grid-template-columns:1fr;gap:2px}.haut h1{font-size:22px}}
@media (max-width:640px){#bloques table,#bloques tbody,#bloques tr,#bloques td{display:block}#bloques thead{display:none}
#bloques tr{padding:8px 0;border-bottom:1px solid var(--bord)}#bloques td{border:0;padding:2px 0}}
"""

JS = """
function age(){const now=Date.now();
document.querySelectorAll('[data-age]').forEach(s=>{const v=s.dataset.age;if(!v)return;
const m=Math.round((now-new Date(v.endsWith('Z')?v:v+'Z'))/60000);
s.textContent=m<1?"(à l'instant)":m<60?`(il y a ${m} min)`:`(il y a ${Math.floor(m/60)} h ${String(m%60).padStart(2,'0')})`;});
const b=document.getElementById('bandeau');
if((now-new Date(b.dataset.genere))/60000>30){b.className='etat-global e-bloque';
document.getElementById('humeur').textContent="Données périmées : le pipeline s'est peut-être arrêté";
document.getElementById('alerte-perimee').hidden=false;const c=document.getElementById('calme');if(c)c.hidden=true;}}
age();setInterval(age,30000);
const F=document.getElementById('form-faits');
if(F){F.querySelectorAll('[data-tout]').forEach(b=>b.onclick=()=>F.querySelectorAll('input[name=fait]').forEach(c=>c.checked=b.dataset.tout==='1'));
F.addEventListener('submit',ev=>{ev.preventDefault();
const g=[...F.querySelectorAll('input[name=fait]:checked')].map(c=>c.value);
const corps=`Faits relus depuis le tableau de bord. Ne modifie pas les deux lignes ci-dessous.

garder: ${g.join(', ')}
dernier: ${F.dataset.dernier}

Clique sur « Submit new issue » : Claude range les faits gardés dans connaissance.md, puis ferme cette issue.`;
window.open(`https://github.com/${F.dataset.depot}/issues/new?title=${encodeURIComponent('Valider des faits')}&body=${encodeURIComponent(corps)}`,'_blank','noopener');});}
"""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    restaurer_base(DB_PATH)
    utc = maintenant()
    passages, revue, alertes, revues, sante, erreur_gh = lire_github(utc - timedelta(days=2))
    indispo = []
    try:
        import sante as sante_mod
        quota = sante_mod.quota_typefully()
    except (OSError, ValueError) as err:  # clé absente ou refusée : tuile « donnée indisponible », le tableau de bord sort quand même
        print(f"! quota Typefully illisible ({err})")
        indispo.append(f"Quota Typefully : donnée indisponible, l'API Typefully a répondu « {err} ».")
        quota = None
    try:
        from threads import typefully_api
        # shortcut: 50 brouillons lus au plus, paginer si la file de brouillons grossit
        brouillons = {b["id"] for b in typefully_api("drafts?status=draft&limit=50").get("results", [])}
    except (OSError, ValueError) as err:  # illisible : chaque bloqué déposé en brouillon est compté « à vérifier »
        print(f"! brouillons Typefully illisibles ({err})")
        indispo.append(f"Brouillons Typefully : liste illisible ({err}), les threads bloqués en brouillon sont marqués « à vérifier ».")
        brouillons = None
    if erreur_gh:
        indispo.append(f"API GitHub : {erreur_gh}.")
    con = sqlite3.connect(DB_PATH)
    d = donnees(con, utc, passages, revue, alertes_gh=alertes, revues=revues, quota=quota, brouillons=brouillons,
                sante=sante, indispo=indispo, github_ok=erreur_gh is None)
    con.close()
    SORTIE.mkdir(exist_ok=True)
    (SORTIE / "index.html").write_text(page(d), encoding="utf-8")
    print(f"Tableau de bord : {SORTIE / 'index.html'}")


if __name__ == "__main__":
    main()

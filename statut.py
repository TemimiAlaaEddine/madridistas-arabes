"""Tableau de bord de l'équipe d'agents : organigramme, « daily » de chaque agent (hier, aujourd'hui, blocages), chiffres
et graphiques. Lit la base et l'historique GitHub Actions, sans appel à Claude. Publié sur GitHub Pages après chaque passage.

    python statut.py        → statut/index.html
"""
import json
import os
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, time, timedelta

from commun import BASE, DB_PATH, e, maintenant, restaurer_base
from threads import ENVOYES, heure_madrid

SORTIE = BASE / "statut"
DEPOT = os.environ.get("GITHUB_REPOSITORY", "TemimiAlaaEddine/madridistas-arabes")
CHART_JS = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"
RUBRIQUES = {"actus": "Actus", "tactique": "Tactique", "mercato": "Mercato", "club": "Club", "debats": "Débats"}
JOURNAUX = {"marca": "Marca", "as": "AS"}
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def iso(d):
    return d.isoformat(timespec="seconds")


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
             "a_decider": len(re.findall(r"^\s*- \[[ xX]\] (?:Retirer le flux|Ajouter le flux|Ajouter la graphie) `", i.get("body") or "", re.M))}
            for i in issues if i["title"].startswith("Revue des sources") and "pull_request" not in i]


def lire_github(depuis):
    """Passages du workflow depuis `depuis` (UTC), dernière revue du lundi, alertes des autres workflows et revues
    ouvertes ; vides si l'API ne répond pas."""
    passages, revue, alertes, revues = [], None, [], []
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
    except (OSError, ValueError, KeyError) as err:
        print(f"  ! statut : API GitHub injoignable ({err}), tableau sans les passages")
    return passages, revue, alertes, revues


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


def agent(id_, emoji, nom, role, equipe, rangs, blocages=(), attente=(), actif=True):
    etat = "bloque" if blocages else "attente" if attente else "demande" if equipe == "demande" else "ok" if actif else "repos"
    return {"id": id_, "emoji": emoji, "nom": nom, "role": role, "equipe": equipe, "rangs": rangs,
            "blocages": list(blocages) + list(attente), "etat": etat}


SERIES = {  # nom : (table, colonne de date, condition)
    "Articles rédigés": ("articles", "date", "1"),
    "Threads X": ("threads", "coalesce(envoye, date)", ENVOYES),
    "Posts Facebook": ("page_facebook", "date", "1"),
}


def donnees(con, utc, passages=(), revue=None, scripts=BASE / "scripts", videos=BASE / "videos", connaissance=BASE / "connaissance.md",
            alertes_gh=(), revues=(), quota=None, brouillons=None):
    dec = heure_madrid(utc) - utc
    madrid = utc + dec
    j0 = datetime.combine(madrid.date(), time()) - dec  # minuit à Madrid, en UTC
    hier, demain = j0 - timedelta(days=1), j0 + timedelta(days=1)
    pannes = {r[0]: r for r in lignes(con, "SELECT envoi, n, depuis, message FROM echecs")}

    def panne(envoi):
        p = pannes.get(envoi)
        return [f"{envoi} en échec depuis {p[1]} passages : {p[3][:140]}"] if p else []

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
    # seuls les bloqués déposés en brouillon t'attendent ; « sans » (doublon, conférence déjà publiée) n'a rien à relire, et un
    # brouillon que tu as publié ou supprimé non plus (brouillons = ids encore en brouillon dans Typefully, None si illisible)
    b48 = sum(brouillons is None or int(i) in brouillons for (i,) in lignes(
        con, "SELECT typefully FROM threads WHERE date >= ? AND date < ? AND statut LIKE 'bloqu%' AND typefully GLOB '[0-9]*'",
        iso(utc - timedelta(hours=48)), iso(demain)))
    pfh, pfa = deux("page_facebook", "date")
    xh, xa = deux("liens_x", "date")

    def resume(jour):
        r = lignes(con, "SELECT typefully FROM resumes WHERE jour = ?", jour.isoformat())
        if not r:
            return None
        return "rien à résumer (aucun article la veille)" if r[0][0] == "vide" else "publié sur X"
    r_auj, r_hier = resume(madrid.date() - timedelta(days=1)), resume(madrid.date() - timedelta(days=2))
    r_auj = r_auj or ("prévu entre minuit et 3 h (heure de Madrid)" if madrid.hour < 3 else "pas publié cette nuit")

    def unes(jour):
        r = lignes(con, "SELECT journal, x, facebook FROM unes WHERE jour = ? ORDER BY journal DESC", jour.isoformat())
        ok = lambda v: v not in (None, "sans", "vide")  # noqa: E731
        return ", ".join(f"{JOURNAUX.get(j, j)} : " + ("sans le Real, non publiée" if x == "sans" else
                         " + ".join(n for n, v in (("X", x), ("Facebook", fb)) if ok(v)) or "en cours") for j, x, fb in r) or "aucune"
    u_auj = unes(madrid.date())
    u_auj = u_auj if u_auj != "aucune" or madrid.hour < 6 else "aucune une publiée"

    fini = [p for p in passages if p.get("status") == "completed"]
    p_auj = [p for p in fini if p["created_at"] >= iso(j0)]
    p_hier = [p for p in fini if iso(hier) <= p["created_at"] < iso(j0)]
    rates = [p for p in p_auj if p.get("conclusion") != "success"]
    dernier = max((p["updated_at"] for p in fini), default=None)
    silence = (utc - datetime.fromisoformat(dernier.rstrip("Z"))).total_seconds() / 60 if dernier else None

    def bilan(lot):
        ok = sum(p.get("conclusion") == "success" for p in lot)
        return f"{pluriel(len(lot), 'passage')}, {ok} réussi{'s' if ok > 1 else ''}" if lot else "historique indisponible"

    detail_rub = ", ".join(f"{n} {RUBRIQUES.get(s, s).lower()}" for s, n in rubriques)
    agents = [
        agent("collecteur", "📡", "Collecteur", "Lit les flux RSS, sitemaps et sites WordPress des journaux", "pipeline",
              [("Hier", pluriel(vh, "article", "repéré") + " dans les flux"), ("Aujourd'hui", pluriel(va, "article", "repéré"))],
              actif=va > 0),
        agent("redacteur", "✍️", "Rédacteur", "Trie et rédige en arabe le résumé commenté de chaque article (Claude)", "pipeline",
              [("Hier", pluriel(ah, "article", "rédigé")), ("Aujourd'hui", pluriel(aa, "article", "rédigé") + (f" ({detail_rub})" if detail_rub else ""))],
              panne("Claude (rédaction)"), actif=aa > 0),
        agent("memoire", "🧠", "Mémoire", "Note les faits durables de chaque article (table faits)", "pipeline",
              [("Hier", pluriel(fh, "fait", "noté")), ("Aujourd'hui", pluriel(fa, "fait", "noté"))],
              attente=[f"{pluriel(faits_attente, 'fait')} attendent ta validation : section « À faire » en haut de la page"] if faits_attente else [], actif=fa > 0),
        agent("controleur", "🛡️", "Contrôleur qualité", "Vérifie chaque thread avant l'envoi : longueur, source, ton, doublons", "pipeline",
              [("Hier", pluriel(th + bh, "thread", "contrôlé") + f", {bh} bloqué(s)"), ("Aujourd'hui", pluriel(ta + ba, "thread", "contrôlé") + f", {ba} bloqué(s)")],
              attente=[f"{pluriel(b48, 'thread')} mis en brouillon à relire dans Typefully (48 h)"] if b48 else [], actif=ta + ba > 0),
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
              + ([f"aucun passage depuis {round(silence)} min : vérifier cron-job.org"] if silence and silence > 40 else [])
              + [f"{p[0]} en échec depuis {p[1]} passages" for p in pannes.values()] + list(alertes_gh), actif=bool(p_auj)),
    ]

    # --- revue du lundi (un workflow, quatre rapports)
    lundi = (madrid.date() + timedelta(days=(7 - madrid.weekday()) % 7 or 7)).strftime("%d/%m")
    if revue:
        quand = datetime.fromisoformat(revue["created_at"].rstrip("Z")) + dec
        reussi = revue.get("conclusion") == "success"
        dernier_rapport = f"{JOURS[quand.weekday()]} {quand:%d/%m} à {quand:%H:%M}, " + ("réussi ✅" if reussi else f"« {revue.get('conclusion') or 'en cours'} »")
    else:
        reussi, dernier_rapport = True, "historique indisponible"
    for id_, emoji, nom, role in [("sources", "🧭", "Revue des sources", "Santé des flux, rendement, sources à ajouter ou retirer"),
                                  ("performance", "📊", "Analyste Facebook", "Semaine comparée, posts par format et par heure"),
                                  ("audit", "⚖️", "Auditeur", "Relit 20 publications tirées au hasard face à leur article"),
                                  ("sante", "🩺", "Santé technique", "Jeton Facebook, quota Typefully, pannes en cours")]:
        en_attente = [f"issue n° {r['numero']} : " + (f"{pluriel(r['a_decider'], 'décision')} à cocher, puis commente /appliquer" if r["a_decider"]
                       else "ouverte sans décision à cocher, à fermer une fois lue") for r in revues] if id_ == "sources" else []
        agents.append(agent(id_, emoji, nom, role, "lundi", [("Dernier rapport", dernier_rapport), ("Prochain", f"lundi {lundi}, 7 h (Madrid)")],
                            [] if reussi else ["dernier rapport en échec : voir l'onglet Actions"], attente=en_attente))

    # --- équipe à la demande (Claude Code)
    textes = sorted(scripts.glob("*.md")) if scripts.exists() else []
    films = sorted(d.name for d in videos.iterdir() if d.is_dir()) if videos.exists() else []
    for id_, emoji, nom, role, derniere, appel in [
        ("sujets", "🎯", "Rédacteur en chef", "Les 3 sujets du jour qui méritent ton avis", "pas de trace écrite", "/sujets"),
        ("moderation", "💬", "Community manager", "Commentaires Facebook sans réponse, réponses proposées", "pas de trace écrite", "/moderation"),
        ("angles", "♟️", "Analyste tactique", "3 angles d'analyse sourcés à développer", "pas de trace écrite", "/angles <sujet>"),
        ("script", "📝", "Plume d'analyse", "Threads et articles d'opinion, avec leurs sources",
         f"{textes[-1].stem} ({pluriel(len(textes), 'texte')} au total)" if textes else "aucun texte", "/script thread sur <sujet>"),
        ("video", "🎬", "Réalisateur vidéo", "Vidéos verticales en scènes rythmées",
         f"{', '.join(films)} ({pluriel(len(films), 'vidéo')})" if films else "aucune vidéo", "/video <sujet>"),
    ]:
        agents.append(agent(id_, emoji, nom, role, "demande", [("Dernière production", derniere), ("Pour l'appeler", appel)]))

    # --- graphiques
    def serie_jours(table, col, cond, n=14):
        return [compter(con, table, col, j0 - timedelta(days=k), j0 - timedelta(days=k - 1), cond) for k in range(n - 1, -1, -1)]

    def serie_heures(table, col, cond):
        return [compter(con, table, col, j0 + timedelta(hours=h), j0 + timedelta(hours=h + 1), cond) if h <= madrid.hour else None for h in range(24)]

    semaine = iso(j0 - timedelta(days=6))
    graphes = {
        "jours": [(madrid.date() - timedelta(days=k)).strftime("%d/%m") for k in range(13, -1, -1)],
        "par_jour": {nom: serie_jours(*s) for nom, s in SERIES.items()},
        "par_heure": {nom: serie_heures(*s) for nom, s in SERIES.items()},
        "rubriques": [(RUBRIQUES.get(s, s), n) for s, n in lignes(con, "SELECT section, count(*) FROM articles WHERE date >= ? GROUP BY 1 ORDER BY 2 DESC", semaine)],
        "journaux": lignes(con, "SELECT journal, count(*) FROM articles WHERE date >= ? GROUP BY 1 ORDER BY 2 DESC LIMIT 8", semaine),
    }
    kpi = [("Articles aujourd'hui", aa, ah), ("Threads X", ta, th), ("Posts Facebook", pfa, pfh),
           ("Passages réussis", f"{len(p_auj) - len(rates)}/{len(p_auj)}" if p_auj else "–", None), ("Pannes en cours", len(pannes), None),
           ("Quota Typefully (mois)", f"{'⚠️ ' if quota[3] else ''}{quota[0]}/{quota[1]} · ~{quota[2]} fin du mois" if quota else "–", None)]
    return {"genere": iso(utc) + "Z", "dernier_passage": dernier, "kpi": kpi, "agents": agents, "graphes": graphes, "faits": a_valider, "revues": list(revues)}


ETATS = {"ok": "Actif", "attente": "T'attend", "bloque": "Bloqué", "repos": "Au repos", "demande": "Sur demande"}
EQUIPES = {"pipeline": ("⚙️ Pipeline automatique", "toutes les 10 minutes, sur GitHub Actions"),
           "lundi": ("📅 Revue du lundi", "chaque lundi à 7 h, en issue GitHub"),
           "demande": ("🧑‍💻 Équipe à la demande", "dans Claude Code, quand tu l'appelles")}


def a_faire(faits, revues=()):
    """Section « À faire » : revues du lundi à décider (lien vers l'issue) et faits notés à valider (cases à cocher, puis
    une issue pré-remplie que le workflow « Validation des faits » traite ; seule une issue du propriétaire compte)."""
    if not (faits or revues):
        return ""
    lignes_revue = "".join(
        f'<li><a class="revue" href="{e(r["url"])}" target="_blank" rel="noopener"><b>🧭 {e(r["titre"])}</b> (issue n° {r["numero"]})<span>'
        + (f'{pluriel(r["a_decider"], "décision")} : coche ce que tu acceptes, puis écris le commentaire <code>/appliquer</code>. '
           f'<code>config.json</code> est modifié et l’issue se ferme.' if r["a_decider"] else
           "Pas de décision à cocher (revue d'avant les cases) : applique-la à la main ou ferme l'issue.")
        + '</span><em>Ouvrir l’issue →</em></a></li>' for r in revues)
    bloc_revues = (f'<h3>Revue des sources</h3><ul class="revues">{lignes_revue}</ul>') if revues else ""
    if not faits:
        return (f'<section class="carte a-faire" id="a-faire"><h2>À faire <small>{pluriel(len(revues), "revue")} du lundi</small></h2>'
                f'{bloc_revues}</section>')
    ligne = lambda i, d, f, j, l: (f'<li><label><input type="checkbox" name="fait" value="{i}" checked><span><b>n° {i}</b> · {e(d)} · '  # noqa: E731
                                   f'{e(f)} <a href="{e(l)}" target="_blank" rel="noopener">{e(j)}</a></span></label></li>') if l else         f'<li><label><input type="checkbox" name="fait" value="{i}" checked><span><b>n° {i}</b> · {e(d)} · {e(f)}</span></label></li>'
    return (f'<section class="carte a-faire" id="a-faire"><h2>À faire</h2>{bloc_revues}'
            f'<h3>{pluriel(len(faits), "fait")} à valider <small>notés par la Mémoire</small></h3>'
            f'<p class="aide">Décoche ce qui est faux ou sans intérêt, puis « Valider sur GitHub » et « Submit new issue ». Claude range les faits '
            f'cochés dans <code>connaissance.md</code> (bonne section, fusion, tableau des matchs) ; les décochés ne reviennent pas. '
            f'La liste disparaît au passage suivant (10 min environ).</p>'
            f'<form id="form-faits" data-depot="{e(DEPOT)}" data-dernier="{faits[-1][0]}"><ul class="faits">{"".join(ligne(*f) for f in faits)}</ul>'
            f'<div class="boutons"><button type="button" data-tout="1">Tout cocher</button><button type="button" data-tout="0">Tout décocher</button>'
            f'<button type="submit" class="principal">Valider sur GitHub →</button></div></form></section>')


def page(d):
    agents = d["agents"]
    par_equipe = {k: [a for a in agents if a["equipe"] == k] for k in EQUIPES}
    alerte = sum(a["etat"] == "bloque" for a in agents)
    attente = sum(a["etat"] == "attente" for a in agents)
    humeur = ("bloque", f"{pluriel(alerte, 'agent')} bloqué{'s' if alerte > 1 else ''}") if alerte else \
             ("attente", f"Tout tourne · {pluriel(attente, 'point')} t'attend{'ent' if attente > 1 else ''}") if attente else ("ok", "Tout tourne")

    def tuile(nom, val, avant):
        delta = ""
        if avant is not None:
            diff = val - avant
            delta = f'<span class="delta {"up" if diff >= 0 else "down"}">{"+" if diff >= 0 else ""}{diff} vs hier</span>'
        return f'<div class="kpi"><span class="kpi-nom">{e(nom)}</span><strong>{e(str(val))}</strong>{delta}</div>'

    noeud = lambda a: (f'<a class="noeud e-{a["etat"]}" href="#{a["id"]}" title="{e(a["role"])}"><span class="em">{a["emoji"]}</span>'  # noqa: E731
                       f'<span>{e(a["nom"])}</span><i class="point" aria-label="{ETATS[a["etat"]]}"></i></a>')
    organi = "".join(f'<div class="branche"><div class="equipe-titre"><b>{t}</b><small>{s}</small></div>'
                     f'<div class="noeuds">{"".join(noeud(a) for a in par_equipe[k])}</div></div>' for k, (t, s) in EQUIPES.items())

    def fiche(a):
        rangs = "".join(f'<div class="rang"><dt>{e(l)}</dt><dd>{e(t)}</dd></div>' for l, t in a["rangs"])
        bloc = "".join(f"<li>{e(b)}</li>" for b in a["blocages"]) or "<li class=rien>Aucun</li>"
        return (f'<article class="fiche e-{a["etat"]}" id="{a["id"]}"><header><span class="em">{a["emoji"]}</span><div><h3>{e(a["nom"])}</h3>'
                f'<p>{e(a["role"])}</p></div><span class="pastille">{ETATS[a["etat"]]}</span></header><dl>{rangs}</dl>'
                f'<div class="blocages"><span>Blocages</span><ul>{bloc}</ul></div></article>')
    daily = "".join(f'<section class="equipe"><h2>{t} <small>{s}</small></h2><div class="fiches">{"".join(fiche(a) for a in par_equipe[k])}</div></section>'
                    for k, (t, s) in EQUIPES.items())
    donnees_js = json.dumps(d["graphes"], ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300"><meta name="robots" content="noindex"><title>Statut de l'équipe</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>⚽</text></svg>">
<style>{CSS}</style></head><body>
<header class="haut"><div><h1>Statut de l'équipe</h1><p><bdi>المدريديستا علاء</bdi> · agents du site, de X et de la Page Facebook</p></div>
<div class="etat-global e-{humeur[0]}"><i class="point"></i>{f'<a href="#a-faire">{humeur[1]}</a>' if d["faits"] or d.get("revues") else humeur[1]}<small>Dernier passage <time data-depuis="{d['dernier_passage'] or ''}">–</time> ·
mis à jour <time data-depuis="{d['genere']}">–</time></small></div></header>
<main>
<div class="kpis">{"".join(tuile(*k) for k in d["kpi"])}</div>
{a_faire(d["faits"], d.get("revues", []))}
<section class="carte"><h2>Organigramme</h2><div class="organi"><div class="chef">👤 <b>Toi</b><small>rédacteur en chef · tu décides et tu publies</small></div>
<div class="branches">{organi}</div></div>
<p class="legende">{"".join(f'<span class="e-{k}"><i class="point"></i>{v}</span>' for k, v in ETATS.items())}</p></section>
<div class="graphes">
<section class="carte large"><h2>Aujourd'hui, heure par heure <small>heure de Madrid</small></h2><div class="toile"><canvas id="g-heures"></canvas></div></section>
<section class="carte large"><h2>14 derniers jours</h2><div class="toile"><canvas id="g-jours"></canvas></div></section>
<section class="carte"><h2>Rubriques <small>7 jours</small></h2><div class="toile"><canvas id="g-rubriques"></canvas></div></section>
<section class="carte"><h2>Sources les plus reprises <small>7 jours</small></h2><div class="toile"><canvas id="g-journaux"></canvas></div></section>
</div>
<h2 class="titre-daily">Daily de l'équipe <small>hier · aujourd'hui · blocages</small></h2>
{daily}
</main>
<footer>Généré par <code>statut.py</code> à chaque passage · données : <code>articles.sql</code> et GitHub Actions · sans appel à Claude</footer>
<script id="donnees" type="application/json">{donnees_js}</script>
<script src="{CHART_JS}"></script><script>{JS}</script></body></html>"""


CSS = """
:root{--fond:#f4f6fb;--carte:#fff;--texte:#14213d;--doux:#5b6785;--bord:#e3e7f0;--or:#c9a227;--bleu:#3b6fd8;--violet:#8b5cf6;--vert:#16a34a;
--ambre:#d97706;--rouge:#dc2626;--gris:#94a3b8;--ciel:#0ea5e9;--ombre:0 1px 2px rgba(20,33,61,.06),0 4px 16px rgba(20,33,61,.06)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--fond:#0b1020;--carte:#141a2e;--texte:#e8ecf6;--doux:#97a3c0;--bord:#232c47;
--ombre:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.25)}}
:root[data-theme="dark"]{--fond:#0b1020;--carte:#141a2e;--texte:#e8ecf6;--doux:#97a3c0;--bord:#232c47}
*{box-sizing:border-box}html,body{overflow-x:hidden}body{margin:0;background:var(--fond);color:var(--texte);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
h1,h2,h3{margin:0;line-height:1.25}h2{font-size:17px}h2 small,.equipe-titre small{color:var(--doux);font-weight:400;font-size:13px;margin-inline-start:6px}
.haut{display:flex;flex-wrap:wrap;gap:16px;justify-content:space-between;align-items:center;padding:24px max(16px,calc(50% - 600px));
background:linear-gradient(135deg,#14213d,#1f3a7a);color:#fff}.haut h1{font-size:26px}.haut p{margin:4px 0 0;opacity:.75}
.etat-global{display:flex;flex-wrap:wrap;align-items:center;gap:8px;background:rgba(255,255,255,.1);padding:10px 16px;border-radius:12px;font-weight:600}
.etat-global small{flex-basis:100%;font-weight:400;opacity:.75}
main{max-width:1200px;margin:0 auto;padding:20px 16px 40px;display:grid;gap:20px}
.carte,.fiche,.kpi{background:var(--carte);border:1px solid var(--bord);border-radius:14px;box-shadow:var(--ombre)}.carte{padding:18px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(150px,100%),1fr));gap:12px;margin-top:-44px}
.kpi{padding:14px 16px;display:flex;flex-direction:column}.kpi-nom{color:var(--doux);font-size:13px}.kpi strong{font-size:28px}
.delta{font-size:12px;font-weight:600}.delta.up{color:var(--vert)}.delta.down{color:var(--ambre)}
.point{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--c,var(--gris));flex:none}
.e-ok{--c:var(--vert)}.e-attente{--c:var(--ambre)}.e-bloque{--c:var(--rouge)}.e-repos{--c:var(--gris)}.e-demande{--c:var(--ciel)}
.e-ok .point,.e-bloque .point{box-shadow:0 0 0 0 var(--c);animation:pouls 2s infinite}
@keyframes pouls{70%{box-shadow:0 0 0 7px transparent}100%{box-shadow:0 0 0 0 transparent}}
@media (prefers-reduced-motion:reduce){.point{animation:none!important}}
.organi{display:flex;flex-direction:column;align-items:center;margin-top:14px}
.chef{background:linear-gradient(135deg,var(--or),#e6c35c);color:#14213d;padding:10px 20px;border-radius:12px;text-align:center;font-size:16px}
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
.graphes{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.large{grid-column:span 1}.toile{position:relative;height:260px;margin-top:10px}
.titre-daily{font-size:20px;margin-top:8px}
.equipe h2{margin-bottom:10px}.fiches{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(300px,100%),1fr));gap:14px}
.fiche{padding:14px 16px;border-top:4px solid var(--c);scroll-margin-top:16px}.fiche:target{outline:2px solid var(--or)}
.fiche header{display:flex;gap:10px;align-items:flex-start}.fiche header div{flex:1}.fiche h3{font-size:16px}
.fiche header p{margin:2px 0 0;color:var(--doux);font-size:13px}
.pastille{font-size:12px;font-weight:600;padding:3px 9px;border-radius:999px;color:var(--c);background:color-mix(in srgb,var(--c) 14%,transparent);white-space:nowrap}
dl{margin:12px 0 0;display:grid;gap:8px}.rang{display:grid;grid-template-columns:120px 1fr;gap:8px}dt{color:var(--doux);font-size:13px}dd{margin:0}
.blocages{margin-top:10px;padding-top:10px;border-top:1px solid var(--bord);display:grid;grid-template-columns:120px 1fr;gap:8px}
.blocages span{color:var(--doux);font-size:13px}.blocages ul{margin:0;padding:0;list-style:none}.blocages li{color:var(--c)}
.blocages li.rien{color:var(--doux)}
.a-faire{border:2px solid var(--ambre)}.a-faire h3{font-size:15px;margin:16px 0 4px}.a-faire h3 small{color:var(--doux);font-weight:400}
.revues{list-style:none;margin:8px 0 0;padding:0;display:grid;gap:8px}
.revue{display:grid;gap:2px;padding:10px 12px;border-radius:9px;background:var(--fond);color:inherit;text-decoration:none;border-inline-start:3px solid var(--ambre)}
.revue span{color:var(--doux);font-size:14px}.revue em{color:var(--bleu);font-style:normal;font-weight:600;font-size:14px}.revue:hover em{text-decoration:underline}.aide{color:var(--doux);font-size:14px;margin:6px 0 12px}
.etat-global a{color:inherit;text-decoration:underline;text-underline-offset:3px}
.faits{list-style:none;margin:0;padding:0;display:grid;gap:6px;max-height:420px;overflow-y:auto}
.faits label{display:flex;gap:10px;align-items:flex-start;padding:8px 10px;border-radius:9px;background:var(--fond);cursor:pointer}
.faits input{margin-top:4px;width:18px;height:18px;accent-color:var(--vert);flex:none}.faits a{color:var(--bleu)}
.faits label:has(input:not(:checked)) span{opacity:.5;text-decoration:line-through}
.boutons{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.boutons button{font:inherit;padding:8px 14px;border-radius:9px;border:1px solid var(--bord);background:var(--carte);color:var(--texte);cursor:pointer}
.boutons .principal{background:var(--vert);border-color:var(--vert);color:#fff;font-weight:600;margin-inline-start:auto}
footer{text-align:center;color:var(--doux);font-size:13px;padding:0 16px 30px}
@media (max-width:800px){.branches,.graphes{grid-template-columns:minmax(0,1fr)}.branches::before,.branche::before{display:none}.kpis{margin-top:-30px}
.rang,.blocages{grid-template-columns:1fr;gap:2px}}
"""

JS = """
const D=JSON.parse(document.getElementById('donnees').textContent);
function depuis(){document.querySelectorAll('time[data-depuis]').forEach(t=>{const v=t.dataset.depuis;if(!v)return;
const d=new Date(v.endsWith('Z')?v:v+'Z'),m=Math.round((Date.now()-d)/60000);
t.textContent=m<1?"à l'instant":m<60?`il y a ${m} min`:m<1440?`il y a ${Math.floor(m/60)} h ${m%60} min`:d.toLocaleString('fr');
t.title=d.toLocaleString('fr');});}
depuis();setInterval(depuis,30000);
const F=document.getElementById('form-faits');
if(F){F.querySelectorAll('[data-tout]').forEach(b=>b.onclick=()=>F.querySelectorAll('input[name=fait]').forEach(c=>c.checked=b.dataset.tout==='1'));
F.addEventListener('submit',ev=>{ev.preventDefault();
const g=[...F.querySelectorAll('input[name=fait]:checked')].map(c=>c.value);
const corps=`Faits relus depuis le tableau de bord. Ne modifie pas les deux lignes ci-dessous.

garder: ${g.join(', ')}
dernier: ${F.dataset.dernier}

Clique sur « Submit new issue » : Claude range les faits gardés dans connaissance.md, puis ferme cette issue.`;
window.open(`https://github.com/${F.dataset.depot}/issues/new?title=${encodeURIComponent('Valider des faits')}&body=${encodeURIComponent(corps)}`,'_blank','noopener');});}
if(window.Chart){
const css=getComputedStyle(document.documentElement),v=n=>css.getPropertyValue(n).trim();
const couleurs=[v('--or'),v('--bleu'),v('--violet'),v('--vert'),v('--ciel'),v('--ambre'),v('--rouge'),v('--gris')];
Chart.defaults.color=v('--doux');Chart.defaults.borderColor=v('--bord');Chart.defaults.font.family='system-ui,sans-serif';
Chart.defaults.plugins.legend.labels.usePointStyle=true;Chart.defaults.maintainAspectRatio=false;
const series=o=>Object.entries(o).map(([label,data],i)=>({label,data,backgroundColor:couleurs[i],borderColor:couleurs[i]}));
new Chart('g-heures',{type:'bar',data:{labels:[...Array(24).keys()].map(h=>h+' h'),datasets:series(D.par_heure).map(s=>({...s,borderRadius:4}))},
options:{scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,beginAtZero:true,ticks:{precision:0}}},interaction:{mode:'index'}}});
new Chart('g-jours',{type:'line',data:{labels:D.jours,datasets:series(D.par_jour).map(s=>({...s,tension:.35,pointRadius:3,
backgroundColor:s.borderColor+'22',fill:s.label==='Articles rédigés'}))},options:{scales:{y:{beginAtZero:true,ticks:{precision:0}},x:{grid:{display:false}}},
interaction:{mode:'index',intersect:false}}});
new Chart('g-rubriques',{type:'doughnut',data:{labels:D.rubriques.map(r=>r[0]),datasets:[{data:D.rubriques.map(r=>r[1]),
backgroundColor:couleurs,borderColor:v('--carte'),borderWidth:3}]},options:{cutout:'62%',plugins:{legend:{position:'right'}}}});
new Chart('g-journaux',{type:'bar',data:{labels:D.journaux.map(r=>r[0]),datasets:[{label:'Articles',data:D.journaux.map(r=>r[1]),
backgroundColor:v('--bleu'),borderRadius:5}]},options:{indexAxis:'y',plugins:{legend:{display:false}},scales:{x:{beginAtZero:true,ticks:{precision:0}},y:{grid:{display:false}}}}});
}
"""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    restaurer_base(DB_PATH)
    utc = maintenant()
    passages, revue, alertes, revues = lire_github(utc - timedelta(days=2))
    try:
        import sante
        quota = sante.quota_typefully()
    except (OSError, ValueError) as err:  # clé absente ou refusée : tuile « – », le tableau de bord sort quand même
        print(f"! quota Typefully illisible ({err})")
        quota = None
    try:
        from threads import typefully_api
        # shortcut: 50 brouillons lus au plus, paginer si la file de brouillons grossit
        brouillons = {b["id"] for b in typefully_api("drafts?status=draft&limit=50").get("results", [])}
    except (OSError, ValueError) as err:  # illisible : on compte tous les bloqués déposés en brouillon, comme avant
        print(f"! brouillons Typefully illisibles ({err})")
        brouillons = None
    con = sqlite3.connect(DB_PATH)
    d = donnees(con, utc, passages, revue, alertes_gh=alertes, revues=revues, quota=quota, brouillons=brouillons)
    con.close()
    SORTIE.mkdir(exist_ok=True)
    (SORTIE / "index.html").write_text(page(d), encoding="utf-8")
    print(f"Tableau de bord : {SORTIE / 'index.html'}")


if __name__ == "__main__":
    main()

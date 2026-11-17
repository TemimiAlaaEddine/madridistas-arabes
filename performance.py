"""Tableau de bord hebdomadaire de la Page Facebook, ajouté chaque lundi à l'issue « Revue des sources » : abonnés, vues
et interactions de la semaine comparés à la semaine d'avant, puis les posts classés par format et par tranche horaire.
Calculé en Python (aucun appel à Claude). Jeton de la Page avec read_insights et pages_read_user_content.

    python performance.py
"""
import sys
from datetime import timedelta
from statistics import median

import threads as t
from commun import maintenant

TRANCHES = ((0, 7, "nuit (0-7 h)"), (7, 12, "matin (7-12 h)"), (12, 18, "après-midi (12-18 h)"), (18, 24, "soir (18-24 h)"))
MIN_POSTS = 10  # en dessous, une médiane ne dit rien


def format_post(message):
    """Format d'un post d'après son texte : les unes et les nouvelles automatiques ont leur forme fixe."""
    message = message or ""
    if message.startswith("📰") and "la une" in message:
        return "Une de journal"
    if "⚜️" in message:
        return "Nouvelle (automatique)"
    return "Autre (manuel, /script)"


def tranche(utc):
    h = t.heure_madrid(utc).hour
    return next(nom for debut, fin, nom in TRANCHES if debut <= h < fin)


def posts_de(page, jeton, depuis, jusqu):
    """Posts publiés entre deux dates UTC, avec leurs interactions et leurs vues."""
    posts, apres = [], None
    while True:
        params = {"fields": "id,created_time,message,permalink_url,shares,reactions.summary(true).limit(0),comments.summary(true).limit(0)",
                  "since": int(depuis.timestamp()), "until": int(jusqu.timestamp()), "limit": 100, "access_token": jeton}
        if apres:
            params["after"] = apres
        r = t.graph_lire(f"{page}/posts", **params)
        posts += r.get("data", [])
        apres = (r.get("paging") or {}).get("cursors", {}).get("after") if (r.get("paging") or {}).get("next") else None
        if not apres:
            break
    for p in posts:
        vues = t.graph_lire(f"{p['id']}/insights", metric="post_media_view", access_token=jeton).get("data") or [{}]
        p["vues"] = (vues[0].get("values") or [{}])[0].get("value", 0) or 0
        p["interactions"] = (p.get("reactions", {}).get("summary", {}).get("total_count", 0)
                             + p.get("comments", {}).get("summary", {}).get("total_count", 0) + p.get("shares", {}).get("count", 0))
        p["format"] = format_post(p.get("message"))
        p["tranche"] = tranche(t.datetime.strptime(p["created_time"], "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=None))
    return posts


def page_par_jour(page, jeton, depuis, jusqu):
    """Valeurs quotidiennes de la Page : {métrique: [(date de fin, valeur), ...]}."""
    r = t.graph_lire(f"{page}/insights", metric="page_media_view,page_post_engagements,page_follows", period="day",
                     since=int(depuis.timestamp()), until=int(jusqu.timestamp()), access_token=jeton)
    return {m["name"]: [(v["end_time"][:10], v.get("value") or 0) for v in m.get("values", [])] for m in r.get("data", [])}


def evolution(avant, apres):
    if not avant:
        return "nouveau" if apres else "="
    return f"{(apres - avant) / avant:+.0%}"


def classement(posts, cle, titre):
    groupes = {}
    for p in posts:
        groupes.setdefault(p[cle], []).append(p)
    lignes = [f"| {titre} | Posts | Vues (médiane) | Interactions (médiane) |", "|---|---|---|---|"]
    for nom, ps in sorted(groupes.items(), key=lambda g: -len(g[1])):
        if len(ps) < MIN_POSTS:
            lignes.append(f"| {nom} | {len(ps)} | trop peu de données | |")
        else:
            lignes.append(f"| {nom} | {len(ps)} | {median(p['vues'] for p in ps):g} | {median(p['interactions'] for p in ps):g} |")
    return lignes


def tableau(maintenant_utc=None):
    jeton, page = t.reglage("facebook_page_token"), t.reglage("facebook_page_id")
    lignes = ["", "## Tableau de bord Facebook", ""]
    if not jeton or not page:
        return "\n".join(lignes + ["Jeton ou Page absent : rien à mesurer."])
    fin = (maintenant_utc or maintenant()).replace(minute=0, second=0, microsecond=0)
    semaine, avant = fin - timedelta(days=7), fin - timedelta(days=14)
    try:
        jours = page_par_jour(page, jeton, avant, fin)
        posts = posts_de(page, jeton, semaine, fin)
        posts_avant = posts_de(page, jeton, avant, semaine)
    except OSError as err:
        detail = err.read().decode("utf-8", "replace")[:200] if hasattr(err, "read") else ""
        return "\n".join(lignes + [f"❌ Statistiques illisibles ({err} {detail}). Le jeton a-t-il read_insights et pages_read_user_content ?"])

    def somme(metrique, depuis, jusqu):
        return sum(v for d, v in jours.get(metrique, []) if depuis.date().isoformat() < d <= jusqu.date().isoformat())

    abonnes = (jours.get("page_follows") or [("", 0)])[-1][1]
    vues, vues_avant = somme("page_media_view", semaine, fin), somme("page_media_view", avant, semaine)
    inter, inter_avant = somme("page_post_engagements", semaine, fin), somme("page_post_engagements", avant, semaine)
    lignes += [f"Semaine du {semaine:%d/%m} au {fin:%d/%m} (heure UTC), comparée à la semaine d'avant.", "",
               "| Indicateur | Semaine | Semaine d'avant | Évolution |", "|---|---|---|---|",
               f"| Abonnés | {abonnes} | | |",
               f"| Publications | {len(posts)} | {len(posts_avant)} | {evolution(len(posts_avant), len(posts))} |",
               f"| Vues de la Page | {vues} | {vues_avant} | {evolution(vues_avant, vues)} |",
               f"| Interactions | {inter} | {inter_avant} | {evolution(inter_avant, inter)} |"]
    if posts:
        lignes += ["", f"Vues médianes par post : {median(p['vues'] for p in posts):g}. "
                   f"Interactions médianes par post : {median(p['interactions'] for p in posts):g}.", ""]
        lignes += classement(posts, "format", "Format") + [""] + classement(posts, "tranche", "Heure de Madrid")
        lignes += ["", "**Les 3 posts les plus vus**"]
        for p in sorted(posts, key=lambda p: (-p["vues"], -p["interactions"]))[:3]:
            texte = (p.get("message") or "(sans texte)").split("\n")[0][:90]
            lignes.append(f"- {p['vues']} vues, {p['interactions']} interactions : [{texte}]({p.get('permalink_url', '')})")
    lignes += ["", f"_Médianes plutôt que moyennes ; pas de conclusion sous {MIN_POSTS} posts par ligne. Chaque post porte les trois "
               "langues : on ne peut pas comparer les langues par les vues._"]
    return "\n".join(lignes)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(tableau())

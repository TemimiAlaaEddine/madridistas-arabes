"""Santé technique, ajoutée chaque lundi à l'issue « Revue des sources » : jeton de la Page Facebook, quota Typefully
(projection à la fin du mois), lecture des pages du site du club et envois en échec en ce moment. Ne modifie rien.

    python sante.py
"""
import calendar
import sqlite3
import sys

import commun
import threads as t
from commun import DB_PATH, maintenant, restaurer_base


def quota_typefully():
    """(publications du mois, quota, projection à la fin du mois au rythme actuel, alerte à 80 %) d'après l'API Typefully."""
    q = t.typefully_api("").get("publishing_quota") or {}
    utilise, reste = q.get("used", 0), q.get("remaining", 0)
    total, now = utilise + reste, maintenant()
    ecoule = max(now.day - 1 + now.hour / 24, 1)  # jours écoulés dans le mois (1 au moins : début de mois trop bruité)
    projection = round(utilise / ecoule * calendar.monthrange(now.year, now.month)[1])
    return utilise, total, projection, bool(total and projection >= 0.8 * total)


def detail(err):
    return err.read().decode("utf-8", "replace")[:200] if hasattr(err, "read") else ""


def pages_club():
    """Structure des pages du club lues en plus du sitemap : si le site change, leur lecture ne trouve plus rien, sans erreur,
    et seul le sitemap (jusqu'à 10 h de retard) reste. On vérifie donc qu'elles ont encore des liens d'articles (sur 30 jours,
    pour ne pas dépendre de l'actualité) et qu'un article donne encore titre et date."""
    lignes = []
    for flux in (f for f in t.CONFIG["flux"] if f.get("pages")):
        problemes, exemple = [], None
        for url in flux["pages"]:
            try:
                liens = commun.liens_page(commun.lire_page(url), ["/"], jours=30)
            except OSError as err:
                problemes.append(f"`{url}` illisible ({err})")
                continue
            if not liens:
                problemes.append(f"`{url}` : aucun lien d'article trouvé")
            exemple = exemple or (liens[0] if liens else None)
        if exemple:
            try:
                e = commun.meta_article(exemple, commun.lire_page(exemple))
                if not e["title"] or not e["published_parsed"]:
                    problemes.append(f"article sans {'titre' if not e['title'] else 'date'} (`{exemple}`)")
            except OSError as err:
                problemes.append(f"article illisible ({err})")
        if problemes:
            lignes.append(f"- ❌ Pages de **{flux['nom']}** : " + " ; ".join(problemes)
                          + ". Structure du site changée ? Seul le sitemap est lu (retards de plusieurs heures) : "
                          "`liens_page` et `meta_article` de commun.py à adapter.")
        else:
            lignes.append(f"- ✅ Pages de {flux['nom']} lisibles ({len(flux['pages'])} rubriques, titre et date des articles).")
    return lignes


def unes_frontpages():
    """Unes de frontpages.com (vers 23 h 30 la veille) : si la page change, on retombe sans erreur sur kiosko (6 h 30). On
    vérifie que chaque page donne encore la date de sa une et l'adresse de la grande image, et que l'image se télécharge."""
    problemes = []
    for code, nom, _ in t.UNES:
        try:
            date, url = t.lire_frontpages(commun.lire_page(f"https://www.frontpages.com/{code}/"))
            if not date or not url:
                problemes.append(f"{nom} : {'date de la une' if not date else 'adresse de la grande image'} introuvable")
            else:
                t.telecharger_image(url, f"sante-{code}")
        except (OSError, ValueError) as err:
            problemes.append(f"{nom} : {err}")
    if problemes:
        return [f"- ❌ Unes sur frontpages.com : {' ; '.join(problemes)}. Les unes partent vers 6 h 30 (kiosko) au lieu de "
                "23 h 30 la veille : `lire_frontpages` de threads.py à adapter."]
    return ["- ✅ Unes de Marca et AS lisibles sur frontpages.com (date et grande image)."]


def sante(con):
    lignes = ["", "## Santé technique", ""]

    if not t.reglage("facebook_page_token"):
        lignes.append("- Jeton Facebook : absent, rien n'est publié sur la Page.")
    else:
        try:
            page = t.graph_lire("me", fields="id,name", access_token=t.reglage("facebook_page_token"))
            lignes.append(f"- ✅ Jeton Facebook valide (Page « {page.get('name')} »).")
        except OSError as err:
            lignes.append(f"- ❌ Jeton Facebook refusé ({err} {detail(err)}). À renouveler : `python threads.py` sur le PC, "
                          "puis `gh secret set FACEBOOK_PAGE_TOKEN` (voir LISEZMOI).")

    if not t.reglage("typefully_api_key") or not t.CONFIG.get("typefully_social_set"):
        lignes.append("- Typefully : clé ou compte absent, rien n'est envoyé sur X.")
    else:
        try:
            utilise, total, projection, alerte = quota_typefully()
            lignes.append(f"- {'⚠️' if alerte else '✅'} Quota Typefully : {utilise} publications sur {total} ce mois-ci, "
                          f"environ {projection} à la fin du mois au rythme actuel"
                          + (" : plus de 80 % du quota, à surveiller." if alerte else "."))
        except (OSError, ValueError) as err:
            lignes.append(f"- ❌ Typefully injoignable ({err} {detail(err)}).")

    lignes += pages_club()
    lignes += unes_frontpages()

    try:
        pannes = con.execute("SELECT envoi, n, depuis, message FROM echecs ORDER BY n DESC").fetchall()
    except sqlite3.OperationalError:  # table créée au premier échec
        pannes = []
    if pannes:
        lignes.append("- Envois en échec en ce moment :")
        lignes += [f"  - **{p[0]}** : {p[1]} passage(s) de suite, depuis le {p[2]} UTC. Dernière erreur : `{p[3]}`" for p in pannes]
    else:
        lignes.append("- ✅ Aucun envoi en échec en ce moment.")
    return "\n".join(lignes)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    restaurer_base(DB_PATH)  # base à jour (gardée en texte dans git)
    base = sqlite3.connect(DB_PATH)
    print(sante(base))
    base.close()

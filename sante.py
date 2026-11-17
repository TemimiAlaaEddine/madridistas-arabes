"""Santé technique, ajoutée chaque lundi à l'issue « Revue des sources » : jeton de la Page Facebook, quota Typefully
(projection à la fin du mois) et envois en échec en ce moment. Ne modifie rien.

    python sante.py
"""
import calendar
import sqlite3
import sys

import threads as t
from commun import DB_PATH, maintenant, restaurer_base


def detail(err):
    return err.read().decode("utf-8", "replace")[:200] if hasattr(err, "read") else ""


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
            q = t.typefully_api("").get("publishing_quota") or {}
            utilise, reste = q.get("used", 0), q.get("remaining", 0)
            total, now = utilise + reste, maintenant()
            ecoule = max(now.day - 1 + now.hour / 24, 1)  # jours écoulés dans le mois (1 au moins : début de mois trop bruité)
            projection = round(utilise / ecoule * calendar.monthrange(now.year, now.month)[1])
            alerte = total and projection >= 0.8 * total
            lignes.append(f"- {'⚠️' if alerte else '✅'} Quota Typefully : {utilise} publications sur {total} ce mois-ci, "
                          f"environ {projection} à la fin du mois au rythme actuel"
                          + (" : plus de 80 % du quota, à surveiller." if alerte else "."))
        except (OSError, ValueError) as err:
            lignes.append(f"- ❌ Typefully injoignable ({err} {detail(err)}).")

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

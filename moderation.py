"""Commentaires de la Page Facebook encore sans réponse de la Page, pour la commande /moderation. Lecture seule : répondre ou
masquer se fait à la main sur Facebook (l'API demanderait la permission pages_manage_engagement).

    python moderation.py [--jours 2]
"""
import argparse
import sys
from datetime import timedelta

import threads as t
from commun import maintenant


def commentaires(jours=2):
    """[(post, [commentaires sans réponse de la Page])] pour les posts des `jours` derniers jours, les plus récents d'abord."""
    jeton, page = t.reglage("facebook_page_token"), t.reglage("facebook_page_id")
    depuis = int((maintenant() - timedelta(days=jours)).replace(tzinfo=t.timezone.utc).timestamp())
    posts = t.graph_lire(f"{page}/posts", fields="id,created_time,message,permalink_url", since=depuis, limit=100,
                         access_token=jeton).get("data", [])
    resultat = []
    for p in posts:
        tous = t.graph_lire(f"{p['id']}/comments", fields="id,from,message,created_time,parent{id},permalink_url",
                            filter="stream", limit=100, access_token=jeton).get("data", [])
        repondus = {c["parent"]["id"] for c in tous if c.get("parent") and (c.get("from") or {}).get("id") == str(page)}
        attente = [c for c in tous if (c.get("from") or {}).get("id") != str(page) and c["id"] not in repondus]
        if attente:
            resultat.append((p, attente))
    return resultat


def afficher(resultat):
    if not resultat:
        return "Aucun commentaire en attente de réponse."
    lignes = []
    for p, cs in resultat:
        lignes.append(f"\n## Post du {p['created_time'][:16].replace('T', ' ')} UTC : {(p.get('message') or '(sans texte)').splitlines()[0][:100]}")
        lignes.append(p.get("permalink_url", ""))
        for c in cs:
            auteur = (c.get("from") or {}).get("name", "lecteur")  # Facebook masque parfois le nom
            reponse = " (réponse à un autre commentaire)" if c.get("parent") else ""
            lignes.append(f"- [{c['id']}] {c['created_time'][:16].replace('T', ' ')} · {auteur}{reponse} : {c.get('message', '')}")
    return "\n".join(lignes)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--jours", type=int, default=2)
    try:
        print(afficher(commentaires(ap.parse_args().jours)))
    except OSError as err:
        detail = err.read().decode("utf-8", "replace")[:200] if hasattr(err, "read") else ""
        sys.exit(f"Facebook a refusé la lecture ({err} {detail}). Le jeton a-t-il pages_read_user_content ?")

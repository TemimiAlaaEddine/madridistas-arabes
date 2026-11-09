"""Recherche dans la base d'articles (articles.db) tout ce qui touche un match, un joueur ou un sujet.

Usage : python connaissance.py "valence" "mbappe" --jours 14 --max 15
Chaque mot est cherché dans le titre, le titre d'origine, le chapeau, le texte et les joueurs cités (clés de config.json,
ex. mbappe, guler) ; un article est retenu s'il contient au moins un mot, les plus pertinents d'abord.
Sert à la commande /script (.claude/skills/script) avec le fichier connaissance.md.
"""
import argparse
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent


def sans_accents(t):
    """Minuscules sans accents latins (« Güler » -> « guler ») ; l'arabe reste tel quel."""
    return "".join(c for c in unicodedata.normalize("NFKD", (t or "").lower()) if not unicodedata.combining(c))


def chercher(mots, jours=30, maximum=15, chemin=BASE / "articles.db"):
    con = sqlite3.connect(chemin)
    con.row_factory = sqlite3.Row
    arts = con.execute("SELECT * FROM articles WHERE date >= date('now', ?) ORDER BY date DESC", (f"-{jours} days",)).fetchall()
    con.close()
    mots = [sans_accents(m) for m in mots if m.strip()]
    notes = []
    for a in arts:
        titres = sans_accents(f"{a['titre']} {a['titre_original']} {a['personnes']}")
        corps = sans_accents(f"{a['chapeau']} {a['texte']}")
        note = sum(3 * (m in titres) + (m in corps) for m in mots)  # un mot dans le titre compte triple
        if note:
            notes.append((note, a))
    notes.sort(key=lambda x: -x[0])  # tri stable : à pertinence égale, le plus récent d'abord
    return [a for _, a in notes[:maximum]]


def afficher(a):
    auteur = f" | {a['auteur']}" if a["auteur"] else ""
    return (f"### [{a['date'][:10]}] {a['titre']}\n{a['journal']}{auteur} | rubrique {a['section']} | {a['lien']}\n"
            f"Titre d'origine : {a['titre_original']}\nJoueurs : {', '.join(json.loads(a['personnes'] or '[]'))}\n\n{a['texte']}\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("mots", nargs="+")
    ap.add_argument("--jours", type=int, default=30)
    ap.add_argument("--max", type=int, default=15)
    args = ap.parse_args()
    from insider import restaurer_base  # base à jour après un git pull (gardée en texte dans git)
    restaurer_base(BASE / "articles.db")
    trouves = chercher(args.mots, args.jours, args.max)
    print(f"{len(trouves)} article(s) trouvé(s) sur {args.jours} jours pour : {' '.join(args.mots)}\n")
    print("\n".join(afficher(a) for a in trouves))

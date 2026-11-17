"""Validation des faits depuis le tableau de bord : l'issue « Valider des faits » (bouton du tableau) donne les numéros
gardés ; Claude les range dans connaissance.md comme /script (bonne section, fusion, tableau des matchs), puis
« Dernier fait relu » avance. Claude ne peut qu'ajouter une ligne ou en remplacer une : jamais en supprimer. Ce qu'il
ne sait pas placer va dans « À classer ». Lancé par le workflow « Validation des faits » (corps de l'issue dans CORPS).

    CORPS="garder: 3, 5
    dernier: 12" python faits.py      → résumé en Markdown (commentaire de l'issue)
"""
import os
import re
import sqlite3
import sys

from commun import BASE, CONFIG, DB_PATH, ErreurClaude, appeler_claude, extraire_json, restaurer_base

CONNAISSANCE = BASE / "connaissance.md"
A_CLASSER = "À classer"
RELU = re.compile(r"Dernier fait relu : (\d+)")

PROMPT = """Tu tiens connaissance.md, la mémoire des faits validés sur le Real Madrid. L'utilisateur vient de valider les faits
ci-dessous. Range chacun comme il le ferait :
- dans la bonne section (titre « ## » exact du fichier), une ligne par fait, au format des lignes voisines :
  « - AAAA-MM-JJ : le fait. Source : Journal (auteur). » ;
- s'il complète ou corrige une ligne existante, remplace cette ligne par une version fusionnée plutôt que de dupliquer ;
- un score validé : ajoute la ligne du tableau des matchs (mêmes colonnes) et mets à jour la ligne du bilan des buteurs ;
- français clair, sans rien inventer au-delà du fait et de sa source.

Réponds UNIQUEMENT avec un tableau JSON, une opération par élément :
{{"action": "ajouter", "section": "<titre exact sans ##>", "ligne": "<ligne complète>"}}
{{"action": "remplacer", "ancienne": "<ligne existante, copiée exactement>", "ligne": "<nouvelle ligne>"}}

Faits validés :
{faits}

connaissance.md :
{texte}"""


def lire_issue(corps):
    """(numéros gardés, dernier numéro présenté) depuis le corps de l'issue ; ValueError si illisible."""
    garder = re.search(r"garder\s*:\s*([\d,\s]*)", corps or "")
    dernier = re.search(r"dernier\s*:\s*(\d+)", corps or "")
    if not dernier:
        raise ValueError("ligne « dernier: N » absente de l'issue")
    return sorted({int(n) for n in re.findall(r"\d+", garder.group(1))} if garder else set()), int(dernier.group(1))


def sections(lignes):
    """{titre: (début, fin)} : indices de la ligne « ## titre » et de la ligne qui suit la section."""
    titres = [(i, l[3:].strip()) for i, l in enumerate(lignes) if l.startswith("## ")]
    return {t: (i, (titres[k + 1][0] if k + 1 < len(titres) else len(lignes))) for k, (i, t) in enumerate(titres)}


def ajouter(lignes, section, ligne):
    """Insère `ligne` dans la section : une ligne de tableau après la dernière du tableau, sinon après la dernière puce."""
    debut, fin = sections(lignes)[section]
    corps = range(debut + 1, fin)
    if ligne.startswith("|"):
        place = max((i for i in corps if lignes[i].startswith("|")), default=None)
    else:
        place = max((i for i in corps if lignes[i].startswith(("- ", "  "))), default=None)
    if place is None:  # section vide : sous le titre et sa ligne blanche
        if not (debut + 1 < fin and lignes[debut + 1] == ""):
            lignes.insert(debut + 1, "")
        place = debut + 1
    lignes.insert(place + 1, ligne)
    if place + 2 < len(lignes) and lignes[place + 2].startswith("## "):  # une ligne blanche avant le titre suivant
        lignes.insert(place + 2, "")


def a_classer(lignes, ligne):
    if A_CLASSER not in sections(lignes):  # avant les préférences, sinon à la fin
        avant = sections(lignes).get("Préférences pour les scripts", (len(lignes), 0))[0]
        lignes[avant:avant] = [f"## {A_CLASSER}", "", ""]
    ajouter(lignes, A_CLASSER, ligne)


def integrer(texte, operations, secours, dernier):
    """Applique les opérations de Claude ; une opération invalide (section inconnue, ligne introuvable) part dans
    « À classer ». `secours` (lignes par défaut des faits) sert si `operations` est None. Renvoie (texte, résumé)."""
    lignes, resume = texte.split("\n"), []
    for op in operations if operations is not None else [{"action": "ajouter", "section": A_CLASSER, "ligne": l} for l in secours]:
        ligne = str(op.get("ligne", "")).strip() if isinstance(op, dict) else ""
        if not ligne.startswith(("- ", "|")) or "\n" in ligne:
            continue  # jamais de titre, de bloc ou de ligne vide glissés dans le fichier
        vu = ligne[2:] if ligne.startswith("- ") else ligne
        if op.get("action") == "remplacer" and op.get("ancienne") in lignes and str(op["ancienne"]).startswith(("- ", "|")):
            lignes[lignes.index(op["ancienne"])] = ligne
            resume.append(f"- ✏️ fusionné : {vu}")
        elif op.get("action") == "ajouter" and op.get("section") in sections(lignes) and op.get("section") != A_CLASSER:
            ajouter(lignes, op["section"], ligne)
            resume.append(f"- ➕ {op['section']} : {vu}")
        else:
            a_classer(lignes, ligne)
            resume.append(f"- 📥 {A_CLASSER} : {vu}")
    texte = "\n".join(lignes)
    actuel = RELU.search(texte)
    if actuel and dernier > int(actuel.group(1)):
        texte = RELU.sub(f"Dernier fait relu : {dernier}", texte, count=1)
    return texte, resume


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    garder, dernier = lire_issue(os.environ.get("CORPS", ""))
    restaurer_base(DB_PATH)
    texte = CONNAISSANCE.read_text(encoding="utf-8")
    relu = int(RELU.search(texte).group(1))
    con = sqlite3.connect(DB_PATH)
    faits = con.execute("SELECT f.id, date(f.date), f.fait, a.journal, a.auteur FROM faits f JOIN articles a ON a.id = f.article_id "
                        f"WHERE f.id > ? AND f.id <= ? AND f.id IN ({','.join('?' * len(garder)) or 'NULL'}) ORDER BY f.id",
                        (relu, dernier, *garder)).fetchall()
    con.close()
    secours = [f"- {d} : {f} Source : {j}{f' ({a})' if a else ''}." for _, d, f, j, a in faits]
    operations, note = None, ""
    if faits:
        try:
            operations = extraire_json(appeler_claude(PROMPT.format(texte=texte, faits="\n".join(
                f"- n° {i} ({d}) : {f} Source : {j}{f' ({a})' if a else ''}." for i, d, f, j, a in faits)),
                CONFIG.get("modele_redaction", "sonnet")))
        except (ValueError, ErreurClaude) as err:
            note = f"\n\nClaude n'a pas répondu ({err}) : les faits sont dans « {A_CLASSER} », à ranger avec /script."
    nouveau, resume = integrer(texte, operations, secours, dernier)
    CONNAISSANCE.write_text(nouveau, encoding="utf-8")
    ecartes = max(0, dernier - relu - len(faits))
    print(f"{len(faits)} fait(s) gardé(s), {ecartes} écarté(s). « Dernier fait relu » : {max(relu, dernier)}.\n")
    print("\n".join(resume) or "Rien à ajouter.", end=note + "\n")


if __name__ == "__main__":
    main()

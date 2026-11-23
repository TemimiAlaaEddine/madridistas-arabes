"""Revue des sources : python sources.py > rapport.md

1. Santé de chaque flux de config.json, lu pour de vrai : erreur, vide, muet depuis longtemps, part d'articles sur le Real.
2. Rendement sur 30 jours : articles publiés sur le site par journal.
3. Médias cités dans nos articles (« بحسب «آس» ») : ceux qu'on lit de seconde main sont des sources à suivre.
4. Avis de Claude : flux à retirer, sources à ajouter ; chaque flux proposé est lu avant d'être recommandé.
Le rapport sort en Markdown ; le workflow revue_sources.yml en fait une issue GitHub chaque lundi.
Rien n'est changé dans config.json sans toi : tu coches les décisions de l'issue, et le commentaire /appliquer
les applique (python sources.py --appliquer, workflow appliquer_revue.yml).
"""
import calendar
import json
import os
import re
import socket
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from commun import (BASE, CONFIG, DB_PATH, ErreurClaude, appeler_claude, extraire_json, garde, lire_flux, nettoyer,
                    restaurer_base)

CONFIG_PATH = BASE / "config.json"
MOTS = [m.lower() for m in CONFIG["mots_cles"]]
MUET_JOURS = 7  # plus rien depuis une semaine : flux mort, URL changée ou rubrique fermée
MUET_VEILLE = 30  # flux de veille ("veille": true, presse d'un pays qui suit son joueur du Real) : creux de plusieurs semaines normaux


def sante(flux):
    """État d'un flux : nombre d'entrées, part qui parle du Real, ancienneté du dernier article."""
    entrees = lire_flux(flux)
    if isinstance(entrees, Exception):
        return {"etat": f"❌ erreur : {str(entrees)[:80]}", "entrees": 0, "real": 0, "jours": None}
    if not entrees:
        return {"etat": "❌ vide", "entrees": 0, "real": 0, "jours": None}
    dates = [calendar.timegm(p) for e in entrees if (p := e.get("published_parsed") or e.get("updated_parsed"))]
    jours = (time.time() - max(dates)) / 86400 if dates else None
    real = sum(garde(flux, nettoyer(e.get("title", ""), 300), nettoyer(e.get("summary", "")), e.get("link", ""), MOTS)
               for e in entrees)
    muet = MUET_VEILLE if flux.get("veille") else MUET_JOURS
    etat = f"⚠️ muet depuis {jours:.0f} j" if jours is not None and jours > muet else "⚠️ rien sur le Real" if not real else "✅"
    return {"etat": etat, "entrees": len(entrees), "real": real, "jours": jours}


def statistiques(chemin=DB_PATH, jours=30):
    """Articles publiés par journal, et médias cités entre «» dans nos textes (noms courts, au moins 3 fois)."""
    con = sqlite3.connect(chemin)
    lignes = con.execute("SELECT journal, texte FROM articles WHERE date >= date('now', ?)", (f"-{jours} days",)).fetchall()
    con.close()
    connus = set(CONFIG.get("noms_ar", {}).values())
    cites = Counter(m.strip() for _, t in lignes for m in re.findall(r"«([^»]{2,30})»", t or "")
                    if len(m.split()) <= 4 and m.strip() not in connus)
    return Counter(j for j, _ in lignes), [(m, n) for m, n in cites.most_common(40) if n >= 3]


PROMPT = """Tu conseilles un site arabophone qui résume en arabe la presse internationale sur le Real Madrid (football masculin) : surtout les articles d'opinion signés (chroniques, analyses tactiques, débats), puis les informations importantes. Il lit des flux RSS, des sitemaps Google News ou l'API WordPress d'un site (jamais Google News), et préfère : la presse espagnole d'abord, puis européenne, puis celle des pays des joueurs du Real ; des articles signés par des journalistes ; des pages lisibles sans abonnement.

FLUX ACTUELS (nom | pays | état | entrées | dont sur le Real | articles publiés sur 30 jours par ce journal | veille)
Un flux marqué « veille » est la presse d'un pays qui suit son joueur du Real : un faible rendement y est normal, ne le retire que s'il est en panne.
{flux}

MÉDIAS CITÉS DANS NOS ARTICLES SANS ÊTRE SUIVIS (nom arabe : nombre de citations sur 30 jours ; ignore ce qui n'est pas un média)
{cites}

Propose :
- "retirer" : les flux à supprimer (en panne, muets, sans rapport avec le Real, ou qui ne produisent rien de publié), avec la raison en une phrase. Ne propose pas de retirer un flux qui marche et publie.
- "ajouter" : au plus 6 sources qui manquent vraiment, en priorité celles que nos articles citent souvent, chacune avec l'adresse exacte de son flux RSS (ou sitemap / API WordPress) si tu la connais, l'adresse de sa page d'accueil ("site", où chercher le flux sinon), son pays (code ISO à 2 lettres en minuscules), son nom en arabe tel que le public arabe l'écrit ("nom_ar"), s'il s'agit d'une rubrique d'opinion, et la raison en une phrase. N'invente pas d'adresse : si tu ne la connais pas, laisse "url" vide.
- "remarques" : une ou deux phrases au plus.

Réponds UNIQUEMENT avec un objet JSON entre crochets, sans texte autour :
[{{"retirer": [{{"flux": "...", "raison": "..."}}], "ajouter": [{{"nom": "...", "nom_ar": "...", "url": "...", "site": "https://...", "pays": "es", "opinion": false, "raison": "..."}}], "remarques": "..."}}]
"""


def decouvrir(site):
    """Flux annoncé par la page d'accueil (<link rel="alternate" type="application/rss+xml">), ou ""."""
    try:
        req = urllib.request.Request(site, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read(1_000_000).decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""
    for balise in re.findall(r"<link\b[^>]*>", html, re.I):
        if re.search(r"application/(rss|atom)\+xml", balise, re.I) and (m := re.search(r"href=[\"']([^\"']+)", balise)):
            return urllib.parse.urljoin(site, m.group(1))
    return ""


def verifier(proposition):
    """Un flux proposé est lu pour de vrai : recommandé seulement s'il répond et parle du Real. Sans adresse, celle que
    sa page d'accueil annonce (gardée dans la proposition pour la case à cocher)."""
    url = proposition.get("url") or ""
    if not url.startswith(("http://", "https://")) and str(proposition.get("site", "")).startswith(("http://", "https://")):
        url = proposition["url"] = decouvrir(proposition["site"])
    if not url.startswith(("http://", "https://")):
        return "adresse à trouver"
    if any(f["url"] == url for f in CONFIG["flux"]):
        return "déjà suivi"
    s = sante({"url": url})
    return s["etat"] if s["etat"] != "✅" else f"✅ {s['entrees']} entrées, {s['real']} sur le Real"


def modifications(avis, ajouts):
    """Lignes de config.json prêtes à copier : seulement les flux proposés qui ont été lus avec succès (✅), et les retraits
    de flux qui existent vraiment. Jamais d'"autorisation" : elle exige l'accord écrit du journal."""
    noms = {f["nom"] for f in CONFIG["flux"]}
    retraits = [x.get("flux") for x in avis.get("retirer", []) if isinstance(x, dict) and x.get("flux") in noms]
    nouveaux = [{"nom": p["nom"], "url": p["url"], "pays": (p.get("pays") or "").lower() or None,
                 **({"opinion": True} if p.get("opinion") else {})} for p, v in ajouts if v.startswith("✅") and p.get("nom")]
    graphies = {p["nom"]: p["nom_ar"] for p, v in ajouts if v.startswith("✅") and p.get("nom_ar")
                and p["nom"].split(" - ")[0] not in CONFIG.get("noms_ar", {})}
    if not (retraits or nouveaux or graphies):
        return []
    return (["\n## Décisions\n", "Coche ce que tu acceptes, puis écris le commentaire `/appliquer` : `config.json` est modifié, "
             "puis l'issue se ferme avec le résumé. Vérifie avant les options `filtre_lien`, `que_le_real`, `veille` des flux ajoutés.\n"]
            + [f"- [ ] Retirer le flux `{n}`" for n in retraits]
            + [f"- [ ] Ajouter le flux `{json.dumps({k: v for k, v in f.items() if v is not None}, ensure_ascii=False)}`" for f in nouveaux]
            + [f"- [ ] Ajouter la graphie `{json.dumps({n: a}, ensure_ascii=False)}`" for n, a in graphies.items()])


DECISION = re.compile(r"^\s*- \[[xX]\] (Retirer le flux|Ajouter le flux|Ajouter la graphie) `(.+)`\s*$", re.M)
CORRECTION = re.compile(r"^\s*- \[[xX]\] Corriger la publication `([^`]+)`\s*:?\s*(.*?)\s*$", re.M)  # cases de l'audit (audit.py)


def appliquer(corps, config):
    """Décisions cochées dans l'issue de la revue → config modifiée (copie) et résumé. Seulement des retraits de flux
    existants, des flux en http(s) avec nom, url, pays et opinion (jamais "autorisation") et des graphies arabes."""
    config = json.loads(json.dumps(config))
    resume = []
    for quoi, valeur in DECISION.findall(corps or ""):
        if quoi == "Retirer le flux":
            avant = len(config["flux"])
            config["flux"] = [f for f in config["flux"] if f["nom"] != valeur]
            resume.append(f"- ➖ flux retiré : {valeur}" if len(config["flux"]) < avant else f"- ⏭️ {valeur} : déjà absent")
            continue
        try:
            obj = json.loads(valeur)
        except ValueError:
            resume.append(f"- ⚠️ ligne illisible, ignorée : {valeur[:80]}")
            continue
        if quoi == "Ajouter le flux":
            f = {k: obj[k] for k in ("nom", "url", "pays", "opinion") if isinstance(obj, dict) and k in obj}
            if not (str(f.get("nom", "")).strip() and str(f.get("url", "")).startswith(("http://", "https://"))):
                resume.append(f"- ⚠️ flux sans nom ou adresse valide, ignoré : {valeur[:80]}")
            elif any(x["url"] == f["url"] or x["nom"] == f["nom"] for x in config["flux"]):
                resume.append(f"- ⏭️ {f['nom']} : déjà suivi")
            else:
                config["flux"].append(f)
                resume.append(f"- ➕ flux ajouté : {f['nom']} ({f['url']})")
        elif isinstance(obj, dict):
            for nom, ar in obj.items():
                if isinstance(ar, str) and ar.strip() and nom not in config.setdefault("noms_ar", {}):
                    config["noms_ar"][nom] = ar.strip()
                    resume.append(f"- 🔤 graphie ajoutée : {nom} → {ar.strip()}")
    # publications déjà parues sur X ou Facebook : rien n'est modifié ici, le résumé de fermeture sert de liste à faire
    resume += [f"- ✏️ à corriger à la main : {pub}" + (f" ({quoi})" if quoi else "") for pub, quoi in CORRECTION.findall(corps or "")]
    return config, resume


def revue(chemin=DB_PATH):
    socket.setdefaulttimeout(30)
    with ThreadPoolExecutor(8) as ex:
        etats = list(ex.map(sante, CONFIG["flux"]))
    publies, cites = statistiques(chemin)
    lignes = []
    for f, s in zip(CONFIG["flux"], etats):
        j = f["nom"].split(" - ")[0]  # même règle que journal() de generer_site
        s["publies"] = publies.get(j, 0)
        if s["etat"] == "⚠️ rien sur le Real" and (s["publies"] or f.get("filtre_lien") or f.get("veille")):
            s["etat"] = "✅"  # il publie, filtre ses rubriques ou attend son joueur : rien en ce moment n'est pas une panne
        lignes.append(f"{f['nom']} | {f.get('pays') or '-'} | {s['etat']} | {s['entrees']} | {s['real']} | {s['publies']}"
                      + (" | veille" if f.get("veille") else ""))
    avis = {}
    try:
        reponse = appeler_claude(PROMPT.format(flux="\n".join(lignes), cites="\n".join(f"{m} : {n}" for m, n in cites) or "(aucun)"),
                                 CONFIG.get("modele_redaction", "sonnet"))
        avis = next((x for x in extraire_json(reponse) if isinstance(x, dict)), {})
    except (ErreurClaude, ValueError) as err:  # le bilan de santé reste utile sans l'avis de Claude
        avis = {"remarques": f"Avis de Claude indisponible ({err})."}
    with ThreadPoolExecutor(6) as ex:
        ajouts = [(p, v) for p, v in zip(avis.get("ajouter", []), ex.map(verifier, avis.get("ajouter", []))) if isinstance(p, dict)]

    r = [f"Revue automatique des {len(CONFIG['flux'])} flux de `config.json`. Rien n'a été modifié : à toi de décider.\n",
         "## Santé des flux\n", "| Flux | Pays | État | Entrées | Sur le Real | Publiés (30 j, journal) |", "|---|---|---|---|---|---|",
         ]
    ordre = sorted(zip(CONFIG["flux"], etats), key=lambda x: (x[1]["etat"] == "✅", x[1]["publies"]))  # problèmes en haut
    r += [f"| {f['nom']}{' (veille)' if f.get('veille') else ''} | {f.get('pays') or '-'} | {s['etat']} | {s['entrees']} | {s['real']} | {s['publies']} |" for f, s in ordre]
    r += ["\n## À retirer\n"] + ([f"- **{x.get('flux')}** : {x.get('raison')}" for x in avis.get("retirer", []) if isinstance(x, dict)]
                                or ["Rien à retirer."])
    r += ["\n## À ajouter\n"] + ([f"- **{p.get('nom')}** ({p.get('pays') or '?'}{', opinion' if p.get('opinion') else ''}) : "
                                  f"{p.get('raison')}  \n  `{p.get('url') or '-'}` → {v}" for p, v in ajouts] or ["Aucune proposition."])
    r += modifications(avis, ajouts)
    if cites:
        r += ["\n## Médias cités dans nos articles sans être suivis (30 jours)\n", ", ".join(f"{m} ({n})" for m, n in cites)]
    if avis.get("remarques"):
        r += ["\n## Remarques\n", str(avis["remarques"])]
    r += ["\n---\nPour appliquer : coche les décisions ci-dessus puis commente `/appliquer`, ou demande à Claude Code « applique la revue des sources »."]
    return "\n".join(r)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["--appliquer"]:  # workflow « Appliquer la revue » : corps de l'issue dans CORPS
        conf, lignes_resume = appliquer(os.environ.get("CORPS", ""), CONFIG)
        if conf != CONFIG:
            CONFIG_PATH.write_text(json.dumps(conf, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("\n".join(lignes_resume) or "Aucune décision cochée : rien n'a changé.")
        sys.exit()
    restaurer_base(DB_PATH)  # base à jour (gardée en texte dans git)
    print(revue())

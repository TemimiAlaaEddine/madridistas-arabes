"""Conférence de presse en direct, MODE TEST : écoute le direct YouTube (MARCA, ABC ou le club), transcrit l'espagnol
par tranches avec Whisper sur le PC et fait traduire les déclarations par Claude. N'écrit que dans direct/AAAA-MM-JJ.md :
rien n'est publié. Chaque déclaration porte ses heures (prononcée, transcrite, traduite) pour mesurer le gain.

    python direct.py                          cherche le direct jusqu'à --jusqua (heure locale), puis suit la conférence
    python direct.py --url URL --simuler      rejoue une vidéo enregistrée à vitesse réelle (essai)

Demande : faster-whisper et yt-dlp (pip), ffmpeg et deno (winget).
"""
import argparse
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from queue import Queue

import numpy as np

from commun import CONFIG, ErreurClaude, appeler_claude, extraire_json

CHAINES = ["https://www.youtube.com/@marca/streams", "https://www.youtube.com/@ABC_es/streams",
           "https://www.youtube.com/@realmadrid/streams"]
SUJET = re.compile(r"mourinho|real madrid.*(rueda de prensa|press conference)|(rueda de prensa|press conference).*real madrid", re.I)
TRANCHE = 90  # secondes : plus court = plus rapide, mais plus d'appels Claude et plus de réponses coupées
DOSSIER = Path(__file__).with_name("direct")
DENO = shutil.which("deno") or next(Path.home().glob("AppData/Local/Microsoft/WinGet/Packages/DenoLand.Deno*/deno.exe"), None)
YT_DLP = [sys.executable, "-m", "yt_dlp"] + (["--js-runtimes", f"deno:{DENO}"] if DENO else [])

PROMPT = """Tu suis en direct la conférence de presse de l'entraîneur du Real Madrid, José Mourinho. Voici la transcription
automatique (espagnol, sans ponctuation, avec des fautes d'écoute) du passage qui vient d'être prononcé, précédé du passage
d'avant pour le contexte (déjà traité : n'en reprends rien, sauf une réponse qui commençait à la fin du contexte).

Effectif et noms en arabe (un nom mal transcrit mais proche est ce joueur) : {personnes}

Extrais les déclarations fortes de Mourinho dans le NOUVEAU passage seulement (pas les questions des journalistes, pas les
banalités, pas les formules de politesse) : 0 à 3. Pour chacune, une citation fidèle, corrigée des fautes d'écoute, sans rien
inventer ni durcir. Si un mot clé est inaudible ou douteux, écarte la déclaration. Donne aussi le sujet de la question du
journaliste à laquelle il répond (la question peut être dans le contexte), en 2 à 5 mots arabes, sans la question elle-même.

Réponds uniquement par un tableau JSON : [{{"sujet": "sujet de la question en arabe", "es": "citation en espagnol corrigée",
"ar": "🎙️ مؤتمر مورينيو | sujet : « traduction arabe » (240 caractères au plus)", "doute": "ce qui reste incertain dans la
citation (nom, mot mal entendu, phrase coupée)"}}]. "doute" vaut "" quand rien n'est incertain : n'y écris jamais qu'il n'y a pas
de doute, ni une correction déjà faite, ni un avis sur la déclaration. Tableau vide [] s'il n'y a rien.

CONTEXTE :
{contexte}

NOUVEAU PASSAGE :
{texte}"""


def heure(t=None):
    return datetime.fromtimestamp(t or time.time()).strftime("%H:%M:%S")


def trouver_direct(jusqua):
    """Premier direct en cours dont le titre parle de la conférence, cherché toutes les 30 s jusqu'à l'heure limite."""
    while time.time() < jusqua:
        for chaine in CHAINES:
            r = subprocess.run(YT_DLP + ["--flat-playlist", "--playlist-end", "5", "--print",
                                "%(live_status)s\t%(url)s\t%(title)s", chaine], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            for ligne in r.stdout.splitlines():
                statut, url, titre = (ligne.split("\t") + ["", ""])[:3]
                if statut == "is_live" and SUJET.search(titre):
                    print(f"{heure()} direct trouvé : {titre} ({url})")
                    return url
        print(f"{heure()} pas encore de direct, nouvel essai dans 30 s")
        time.sleep(30)
    sys.exit("Aucun direct trouvé avant l'heure limite.")


def capturer(url, dossier, simuler, duree):
    """ffmpeg découpe le son en tranches WAV 16 kHz mono ; renvoie le processus (fini = direct terminé)."""
    # piste espagnole d'origine (YouTube ajoute des doublages automatiques), sinon le son du direct (vidéo la plus légère)
    flux = subprocess.run(YT_DLP + ["-g", "-f", "ba[format_note*=original]/ba[language^=es]/worst[acodec!=none]/worst", url],
                          capture_output=True, text=True, check=True).stdout.split()[0]
    cmd = ["ffmpeg", "-loglevel", "error"] + (["-re"] if simuler else []) + ["-i", flux]
    cmd += (["-t", str(duree)] if duree else []) + ["-vn", "-ac", "1", "-ar", "16000", "-f", "segment",
                                                   "-segment_time", str(TRANCHE), str(dossier / "tranche%03d.wav")]
    return subprocess.Popen(cmd)


def lire_wav(chemin):
    with wave.open(str(chemin)) as f:
        return np.frombuffer(f.readframes(f.getnframes()), np.int16).astype(np.float32) / 32768


def traduire(file, sortie):
    """Fil Claude : traduit les tranches dans l'ordre, sans bloquer la transcription de la suivante."""
    personnes = ", ".join(f"{k} = {p['nom']}" for k, p in CONFIG.get("personnes", {}).items())
    contexte = ""
    while (tache := file.get()) is not None:
        texte, debut, fin, transcrit = tache
        try:
            reponse = appeler_claude(PROMPT.format(personnes=personnes, contexte=contexte or "(début)", texte=texte),
                                     modele="sonnet", effort="low")
            declarations = extraire_json(reponse)
        except (ErreurClaude, ValueError) as err:
            declarations = [{"es": "", "ar": "", "doute": f"échec Claude : {err}"}]
        traduit = time.time()
        with sortie.open("a", encoding="utf-8") as f:
            f.write(f"\n## Passage {heure(debut)} → {heure(fin)} · transcrit {heure(transcrit)} · traduit {heure(traduit)}"
                    f" ({traduit - fin:.0f} s après la fin du passage)\n\n")
            for d in declarations:
                f.write(f"- {d.get('ar', '')}\n  - es : {d.get('es', '')}\n" + (f"  - ⚠️ {d['doute']}\n" if d.get("doute") else ""))
            if not declarations:
                f.write("- (rien de fort)\n")
        print(f"{heure()} traduit : {len(declarations)} déclaration(s)")
        contexte = texte


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", help="vidéo ou direct précis (sinon recherche sur les chaînes)")
    p.add_argument("--jusqua", default="05:00", help="heure locale limite de recherche du direct (HH:MM)")
    p.add_argument("--simuler", action="store_true", help="rejoue une vidéo enregistrée à vitesse réelle")
    p.add_argument("--duree", type=int, default=0, help="secondes à capter (0 : jusqu'à la fin)")
    p.add_argument("--modele", default="medium", help="modèle Whisper (small : plus rapide, moins précis)")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    h, m = map(int, a.jusqua.split(":"))
    jusqua = datetime.now().replace(hour=h, minute=m, second=0).timestamp()
    url = a.url or trouver_direct(jusqua)

    from faster_whisper import WhisperModel  # import lent : seulement une fois le direct trouvé
    whisper = WhisperModel(a.modele, device="cpu", compute_type="int8", cpu_threads=8)

    jour = datetime.now().strftime("%Y-%m-%d_%H%M")
    tranches = DOSSIER / jour
    tranches.mkdir(parents=True, exist_ok=True)
    sortie = DOSSIER / f"{jour}.md"
    sortie.write_text(f"# Conférence en direct, mode test ({jour})\n\nSource : {url}\nModèle : {a.modele}, tranches de "
                      f"{TRANCHE} s. Heures locales du PC.\n", encoding="utf-8")
    brut = sortie.with_suffix(".txt")

    file = Queue()
    ffmpeg = capturer(url, tranches, a.simuler, a.duree)  # avant le fil Claude : un échec ici ne laisse pas le script bloqué
    fil = threading.Thread(target=traduire, args=(file, sortie))
    fil.start()
    print(f"{heure()} écoute en cours, résultats dans {sortie}")

    n = 0
    while True:
        courante, suivante = tranches / f"tranche{n:03d}.wav", tranches / f"tranche{n + 1:03d}.wav"
        fini = ffmpeg.poll() is not None
        if not (suivante.exists() or (fini and courante.exists())):  # tranche complète quand la suivante commence
            if fini:
                break
            time.sleep(1)
            continue
        debut, fin = courante.stat().st_ctime, courante.stat().st_mtime  # Windows : ctime = création du fichier
        segments, _ = whisper.transcribe(lire_wav(courante), language="es", beam_size=1, vad_filter=True)
        texte = " ".join(s.text.strip() for s in segments)
        with brut.open("a", encoding="utf-8") as f:
            f.write(f"[{heure(debut)}] {texte}\n")
        print(f"{heure()} tranche {n} transcrite ({len(texte)} caractères)")
        if texte:
            file.put((texte, debut, fin, time.time()))
        n += 1

    file.put(None)
    fil.join()
    print(f"{heure()} terminé : {sortie}")


if __name__ == "__main__":
    main()

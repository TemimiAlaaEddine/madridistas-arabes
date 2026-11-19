"""Voix clonée (Chatterbox Multilingual, local, sur processeur). Lancé par video.py avec le Python de chatterbox-env
(%LOCALAPPDATA%\\chatterbox-env, Python 3.11 : Chatterbox ne s'installe pas sous 3.14). Le modèle est chargé une seule fois ;
chaque ligne JSON reçue sur stdin ({"texte", "langue", "echantillon", "sortie"}) produit un WAV, puis "__fini__" sur stdout."""
import json
import re
import sys

import torchaudio as ta
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
from num2words import num2words


def en_lettres(texte, langue):
    """Chatterbox saute les chiffres : « 140 » devient « ciento cuarenta » (décimale à virgule ou point acceptée)."""
    return re.sub(r"\d+(?:[.,]\d+)?", lambda m: num2words(float(m[0].replace(",", ".")) if m[0].strip("0123456789")
                                                          else int(m[0]), lang=langue), texte)


assert en_lettres("140 minutos, 2,5 goles", "es") == "ciento cuarenta minutos, dos punto cinco goles", en_lettres("140 minutos, 2,5 goles", "es")

modele = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
for ligne in sys.stdin:
    d = json.loads(ligne)
    wav = modele.generate(en_lettres(d["texte"], d["langue"]), language_id=d["langue"], audio_prompt_path=d["echantillon"])
    ta.save(d["sortie"], wav, modele.sr)
    print("__fini__", flush=True)

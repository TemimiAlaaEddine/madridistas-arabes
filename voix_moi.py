"""Voix clonée (Chatterbox Multilingual, local, sur processeur). Lancé par video.py avec le Python de chatterbox-env
(%LOCALAPPDATA%\\chatterbox-env, Python 3.11 : Chatterbox ne s'installe pas sous 3.14). Le modèle est chargé une seule fois ;
chaque ligne JSON reçue sur stdin ({"texte", "langue", "echantillon", "sortie"}) produit un WAV, puis "__fini__" sur stdout."""
import json
import sys

import torchaudio as ta
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

modele = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
for ligne in sys.stdin:
    d = json.loads(ligne)
    wav = modele.generate(d["texte"], language_id=d["langue"], audio_prompt_path=d["echantillon"])
    ta.save(d["sortie"], wav, modele.sr)
    print("__fini__", flush=True)

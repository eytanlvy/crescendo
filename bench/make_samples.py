"""Génère des échantillons wav 16 kHz mono avec `say` (+ silence via sox) et leurs transcriptions de référence.

Usage : python3 bench/make_samples.py  → bench/samples/*.wav + bench/samples/references.json
"""
import json
import subprocess
from pathlib import Path

OUT = Path(__file__).parent / "samples"

# (id, voix, texte de référence). Les voix françaises prononcent les termes anglais avec l'accent :
# c'est une bonne approximation du code-switching réel.
SAMPLES = [
    ("mix_refactor", "Thomas",
     "Est-ce que tu peux faire un refactor de la fonction parse config et ajouter des tests pytest avant de push sur GitHub ?"),
    ("mix_pr", "Thomas",
     "Ouvre une pull request sur le repo, fais un rebase sur main puis merge quand la CI est verte."),
    ("mix_claude", "Jacques",
     "Dans Claude Code, écris une fonction TypeScript qui parse le JSON renvoyé par l'API et gère les erreurs."),
    ("mix_k8s", "Jacques",
     "Le déploiement sur Kubernetes est plus lent que Docker Compose, mais avec un cache on amortit le coût."),
    ("mix_long", "Thomas",
     "Bon alors, je voudrais que tu lises le fichier history point JSON L, que tu calcules la latence médiane "
     "de chaque étape, Whisper, Ollama et le collage, et que tu me proposes un refactor du pipeline pour passer sous les deux secondes."),
    ("fr_plain", "Thomas",
     "Je pense qu'on devrait revoir l'architecture avant la réunion de demain matin."),
    ("en_plain", "Samantha",
     "Write a Python script that reads the history file and prints the average latency per step."),
    ("en_question", "Daniel",
     "Can you explain why the merge failed on the main branch yesterday?"),
    ("short_oui", "Thomas", "Oui."),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    refs = {}
    for sid, voice, text in SAMPLES:
        wav = OUT / f"{sid}.wav"
        subprocess.run(["say", "-v", voice, "-o", str(wav), "--file-format=WAVE",
                        "--data-format=LEI16@16000", text], check=True)
        refs[sid] = text
    # Silence numérique et bruit de fond faible : doivent produire un texte vide.
    subprocess.run(["sox", "-n", "-r", "16000", "-c", "1", "-b", "16", str(OUT / "silence.wav"),
                    "trim", "0", "3"], check=True)
    subprocess.run(["sox", "-n", "-r", "16000", "-c", "1", "-b", "16", str(OUT / "noise.wav"),
                    "synth", "3", "pinknoise", "vol", "0.02"], check=True)
    refs["silence"] = ""
    refs["noise"] = ""
    (OUT / "references.json").write_text(json.dumps(refs, ensure_ascii=False, indent=2))
    print(f"{len(refs)} échantillons dans {OUT}")


if __name__ == "__main__":
    main()

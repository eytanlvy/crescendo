import pytest

from tests.helpers import make_wav

from dictate.audio import analyze_wav
from dictate.filters import clean_transcript, normalize_text, remove_fillers

def test_analyze_duration_and_levels(tmp_path):
    info = analyze_wav(make_wav(tmp_path / "a.wav", [(1.0, 0.5)]))
    assert info.duration_s == pytest.approx(1.0, abs=0.01)
    assert info.rms_dbfs == pytest.approx(-9.03, abs=0.2)
    assert info.peak_dbfs == pytest.approx(-6.02, abs=0.2)
    assert info.speech_s == pytest.approx(1.0, abs=0.05)


def test_analyze_silence(tmp_path):
    info = analyze_wav(make_wav(tmp_path / "s.wav", [(2.0, 0.0)]))
    assert info.duration_s == pytest.approx(2.0, abs=0.01)
    assert info.rms_dbfs <= -100
    assert info.speech_s == 0


def test_speech_duration_counts_only_loud_frames(tmp_path):
    # 0,6 s de « parole » (-9 dBFS) entourée de bruit faible (-66 dBFS).
    info = analyze_wav(make_wav(tmp_path / "m.wav", [(1.0, 0.0007), (0.6, 0.5), (1.0, 0.0007)]),
                       speech_threshold_dbfs=-42)
    assert info.speech_s == pytest.approx(0.6, abs=0.06)


def test_analyze_empty_wav(tmp_path):
    info = analyze_wav(make_wav(tmp_path / "e.wav", []))
    assert info.duration_s == 0 and info.speech_s == 0


@pytest.mark.parametrize("raw,expected", [
    (" Bonjour ! Ça va ?\n", "Bonjour ! Ça va ?"),
    (" Ouvre une PR\n puis merge.\n", "Ouvre une PR puis merge."),
    ("a  \t b", "a b"),
])
def test_normalize_text(raw, expected):
    assert normalize_text(raw) == expected


@pytest.mark.parametrize("raw", [
    "Sous-titres réalisés par la communauté d'Amara.org",
    " Sous-titres réalisés para la communauté d'Amara.org\n",
    "Merci d'avoir regardé !",
    "Merci d'avoir regardé cette vidéo.",
    "Thanks for watching!",
    "Thank you for watching.",
    "Sous-titrage ST' 501",
    "Sous-titrage Société Radio-Canada",
    "[BLANK_AUDIO]",
    "[Musique]",
    "(musique)",
    "*rires*",
    " ...",
    "…",
    "♪",
    "Abonnez-vous à la chaîne !",
])
def test_hallucinations_are_dropped(raw):
    assert clean_transcript(raw) == ""


def test_trailing_hallucination_is_stripped_but_speech_kept():
    raw = "Ajoute un test pour la fonction parse. Merci d'avoir regardé !"
    assert clean_transcript(raw) == "Ajoute un test pour la fonction parse."


def test_annotations_removed_inside_speech():
    assert clean_transcript("Bon [Musique] on commence.") == "Bon on commence."


def test_legit_short_speech_is_kept():
    assert clean_transcript("Merci.") == "Merci."
    assert clean_transcript("Oui.") == "Oui."


def test_repetition_loop_is_collapsed():
    raw = "Je vais tester. Je vais tester. Je vais tester. Je vais tester. Je vais tester."
    assert clean_transcript(raw) == "Je vais tester."


def test_normal_repetition_kept():
    assert clean_transcript("Non, non, c'est bon.") == "Non, non, c'est bon."


def test_prompt_echo_is_dropped():
    prompt = ("Dictée en français avec des termes techniques anglais : Claude, Claude Code, Codex, "
              "Anthropic, OpenAI, Whisper, Ollama, GitHub.")
    assert clean_transcript("Claude, Claude Code, Codex, Anthropic, OpenAI, Whisper.", prompt=prompt) == ""
    assert clean_transcript("Dictée en français avec des termes techniques anglais.", prompt=prompt) == ""


def test_speech_mentioning_terms_is_kept_despite_prompt():
    prompt = "Dictée en français avec des termes techniques anglais : Claude Code, Codex, GitHub."
    text = "Demande à Claude Code de pousser la branche sur GitHub ce soir."
    assert clean_transcript(text, prompt=prompt) == text


def test_legit_mention_of_subtitles_is_kept():
    text = "Active les sous-titres par défaut dans le lecteur vidéo."
    assert clean_transcript(text) == text


@pytest.mark.parametrize("raw,expected", [
    ("Euh, pousse le code.", "Pousse le code."),
    ("je voudrais que tu, euh, regardes ça", "je voudrais que tu, regardes ça"),
    ("heu hum on y va", "on y va"),
    ("so uh we ship it", "so we ship it"),
    ("Euh…", ""),
    ("Le Heurtoir et l'humour", "Le Heurtoir et l'humour"),   # pas au milieu des mots
])
def test_remove_fillers(raw, expected):
    assert remove_fillers(raw) == expected

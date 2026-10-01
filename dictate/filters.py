"""Normalisation et filtre anti-hallucinations Whisper."""
from __future__ import annotations

import re
import unicodedata

# Espaces insécables / fines (typographie française de Whisper ou du LLM) → espace normale.
_SPACES = re.compile(r"[   -  \t\r\n]+")
_MULTI_SPACE = re.compile(r" {2,}")

# Annotations non verbales : [BLANK_AUDIO], [Musique], (rires), *applaudissements*, ♪
_ANNOTATIONS = re.compile(
    r"\[[^\]]*\]"
    r"|\((?:musique|music|rires?|laughs?|laughter|applaudissements|applause|silence|bruits?|noise|inaudible)[^)]*\)"
    r"|\*[^*\n]{1,40}\*"
    r"|[♪♫]+",
    re.IGNORECASE,
)

# Hallucinations typiques (sous-titres YouTube dans les données d'entraînement) : retirées où qu'elles soient.
_END = r"\s*[.!?…]*"
_HALLUCINATIONS = re.compile(
    "|".join(p + _END for p in [
        r"sous-titr\w*(?:\s+r[ée]alis[ée]s?)?\s+para?\s+(?:la\s+)?communaut[ée]\s+d['’]?\s*amara\.org",
        r"sous-titrage\s+st['’]?\s*\d+",
        r"sous-titrage\s+soci[ée]t[ée]\s+radio-canada",
        r"merci\s+d['’]avoir\s+regard[ée](?:\s+cette\s+vid[ée]o)?",
        r"merci\s+de\s+(?:m['’])?avoir\s+regard[ée]",
        r"thanks?\s+(?:you\s+)?(?:so\s+much\s+)?for\s+watching",
        r"abonnez-vous(?:\s+[àa]\s+(?:la|ma|notre)\s+cha[îi]ne)?",
        r"n['’]oubliez\s+pas\s+de\s+vous\s+abonner[^.!?]*",
        r"(?:www\.)?amara\.org",
    ]),
    re.IGNORECASE,
)
_HAS_WORD = re.compile(r"\w", re.UNICODE)
_WORD = re.compile(r"\w+", re.UNICODE)

MIN_LOOP_REPEATS = 4
MAX_LOOP_NGRAM = 8


def normalize_text(text: str) -> str:
    text = _SPACES.sub(" ", text)
    return _MULTI_SPACE.sub(" ", text).strip()


def fold(word: str) -> str:
    """Minuscules, sans accents ni ponctuation : pour comparer des mots."""
    decomposed = unicodedata.normalize("NFKD", word.lower())
    return "".join(c for c in decomposed if c.isalnum())


def collapse_loops(text: str) -> str:
    """« A B. A B. A B. A B. » → « A B. » (boucle de décodage Whisper : ≥ 4 répétitions consécutives)."""
    words = text.split(" ")
    keys = [fold(w) for w in words]
    out, i = [], 0
    while i < len(words):
        step = _loop_length(keys, i)
        if step:
            out.extend(words[i:i + step[0]])
            i += step[0] * step[1]
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)


def _loop_length(keys: list[str], i: int) -> tuple[int, int] | None:
    """(taille du n-gramme, nombre de répétitions) si une boucle commence en i, sinon None."""
    for n in range(1, MAX_LOOP_NGRAM + 1):
        gram = keys[i:i + n]
        if len(gram) < n or not any(gram):
            return None
        reps = 1
        while keys[i + reps * n:i + (reps + 1) * n] == gram:
            reps += 1
        if reps >= MIN_LOOP_REPEATS:
            return n, reps
    return None


def is_prompt_echo(text: str, prompt: str) -> bool:
    """Whisper recrache parfois son prompt (liste de termes) sur un audio sans parole."""
    if not prompt:
        return False
    words = [fold(w) for w in _WORD.findall(text)]
    if len(words) < 3:
        return False
    vocab = {fold(w) for w in _WORD.findall(prompt)}
    return sum(w in vocab for w in words) / len(words) >= 0.9


def clean_transcript(text: str, prompt: str = "") -> str:
    text = normalize_text(text)
    text = _ANNOTATIONS.sub(" ", text)
    text = _HALLUCINATIONS.sub(" ", text)
    text = normalize_text(text)
    text = collapse_loops(text) if text else text
    if not _HAS_WORD.search(text) or is_prompt_echo(text, prompt):
        return ""
    return text


_FILLERS = re.compile(r"(?<!\w)(?:e+uh+|heu+|hu+m+|hm+|u+m+|u+h+|erm)(?!\w)[,.…]*\s*", re.IGNORECASE)


def remove_fillers(text: str) -> str:
    """Retire les hésitations non ambiguës (filet de sécurité si le LLM est indisponible ou rejeté)."""
    cleaned = normalize_text(_FILLERS.sub("", text))
    if cleaned and text[:1].isupper() and not cleaned[:1].isupper():
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned

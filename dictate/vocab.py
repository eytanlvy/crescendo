"""Vocabulaire : prompt Whisper borné, remplacements déterministes, casse des termes."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

# Le prompt conditionne Whisper : il installe le style (français + termes anglais) et l'orthographe des termes.
PROMPT_PREFIX = "Dictée en français avec des termes techniques anglais :"
WHISPER_PROMPT_MAX_TOKENS = 224


@dataclass
class Vocabulary:
    terms: list[str] = field(default_factory=list)
    replacements: list[tuple[str, str]] = field(default_factory=list)


def parse_vocabulary(text: str) -> Vocabulary:
    vocab = Vocabulary()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=>" in line:
            wrong, _, right = (s.strip() for s in line.partition("=>"))
            if not wrong or not right:
                raise ValueError(f"vocabulaire, ligne {lineno} : remplacement mal formé {raw!r} "
                                 "(attendu « entendu => écrit »)")
            vocab.replacements.append((wrong, right))
        elif line not in vocab.terms:
            vocab.terms.append(line)
    return vocab


EXAMPLE_NAME = "vocabulary.example.txt"


def resolve_vocabulary_path(path: Path | str) -> Path:
    """Le vocabulaire personnel (non versionné) s'il existe, sinon l'exemple livré à côté."""
    path = Path(path)
    example = path.with_name(EXAMPLE_NAME)
    return example if not path.exists() and example.exists() else path


def load_vocabulary(path: Path | str) -> Vocabulary:
    return parse_vocabulary(resolve_vocabulary_path(path).read_text(encoding="utf-8"))


_PIECE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def estimate_tokens(text: str) -> int:
    """Estimation prudente (surestimée) du nombre de tokens Whisper.

    Mots : ~3 caractères/token ; acronymes en capitales : ~2 caractères/token ; ponctuation : 1 token.
    """
    total = 0
    for piece in _PIECE.findall(text):
        if not piece[0].isalnum() and piece[0] != "_":
            total += 1
        elif piece.isupper() and len(piece) > 1:
            total += math.ceil(len(piece) / 2)
        else:
            total += max(1, math.ceil(len(piece) / 3))
    return total


def build_prompt(terms: list[str], max_tokens: int = WHISPER_PROMPT_MAX_TOKENS) -> str:
    """Préfixe + termes séparés par des virgules, en s'arrêtant avant de dépasser le budget."""
    if not terms:
        return ""
    prompt = PROMPT_PREFIX
    first = True
    for term in terms:
        candidate = f"{prompt}{' ' if first else ', '}{term}"
        if estimate_tokens(candidate + ".") > max_tokens:
            break
        prompt, first = candidate, False
    return prompt + "."


def _phrase_regex(phrase: str) -> str:
    # Espaces/tirets interchangeables entre les mots.
    return r"[\s-]+".join(re.escape(w) for w in re.split(r"[\s-]+", phrase.strip()) if w)


def _substitute(text: str, mapping: list[tuple[str, str]]) -> str:
    """Remplace en une seule passe (le résultat d'une règle n'est jamais re-remplacé), mots entiers,
    insensible à la casse, la plus longue règle l'emportant."""
    if not mapping:
        return text
    ordered = sorted(mapping, key=lambda m: len(m[0]), reverse=True)
    alternation = "|".join(f"(?P<r{i}>{_phrase_regex(src)})" for i, (src, _) in enumerate(ordered))
    pattern = re.compile(r"(?<!\w)(?:" + alternation + r")(?!\w)", re.IGNORECASE)
    return pattern.sub(lambda m: ordered[int(m.lastgroup[1:])][1], text)


def apply_replacements(text: str, replacements: list[tuple[str, str]]) -> str:
    return _substitute(text, replacements)


def apply_term_case(text: str, terms: list[str]) -> str:
    """Rétablit la casse canonique des termes qui en ont une (contiennent une majuscule)."""
    return _substitute(text, [(t, t) for t in terms if any(c.isupper() for c in t)])

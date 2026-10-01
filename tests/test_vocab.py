from pathlib import Path

import pytest

from dictate.vocab import (PROMPT_PREFIX, apply_replacements, apply_term_case, build_prompt,
                           estimate_tokens, load_vocabulary, parse_vocabulary)

REPO = Path(__file__).resolve().parent.parent


def test_parse_terms_replacements_and_comments():
    v = parse_vocabulary("# commentaire\nClaude Code\n\n  pytest  \ncloud code => Claude Code\n")
    assert v.terms == ["Claude Code", "pytest"]
    assert v.replacements == [("cloud code", "Claude Code")]


def test_parse_malformed_replacement_reports_line():
    with pytest.raises(ValueError, match="ligne 2"):
        parse_vocabulary("Claude\n => Claude\n")


def test_parse_deduplicates_terms_keeping_order():
    assert parse_vocabulary("A\nB\nA\n").terms == ["A", "B"]


def test_prompt_contains_terms_in_order():
    p = build_prompt(["Claude Code", "pytest"])
    assert p.startswith(PROMPT_PREFIX)
    assert p.index("Claude Code") < p.index("pytest")


def test_prompt_respects_token_budget_and_keeps_first_terms():
    terms = [f"Terme{i:03d}" for i in range(500)]
    p = build_prompt(terms, max_tokens=224)
    assert estimate_tokens(p) <= 224
    assert "Terme000" in p
    assert "Terme499" not in p


def test_prompt_empty_terms():
    assert build_prompt([]) == ""


def test_repo_vocabulary_fits_budget():
    v = load_vocabulary(REPO / "vocabulary.txt")
    p = build_prompt(v.terms)
    assert estimate_tokens(p) <= 224
    assert "Claude Code" in p and "Slack" in p


def test_estimate_tokens_is_conservative_for_acronyms():
    # Whisper découpe les acronymes en plusieurs tokens : l'estimation doit être large.
    assert estimate_tokens("AWS, GCP, CLI, YAML") >= 8


@pytest.mark.parametrize("text,expected", [
    ("J'utilise cloud code tous les jours", "J'utilise Claude Code tous les jours"),
    ("Cloud Code et CLOUD CODE", "Claude Code et Claude Code"),
    ("cloud-code est bien", "Claude Code est bien"),
    ("cloud  code", "Claude Code"),
    ("un cloud codebase", "un cloud codebase"),        # pas de remplacement au milieu d'un mot
    ("soundcloud code", "soundcloud code"),
])
def test_apply_replacements(text, expected):
    assert apply_replacements(text, [("cloud code", "Claude Code")]) == expected


def test_replacements_apply_longest_first():
    reps = [("code", "CODE"), ("cloud code", "Claude Code")]
    assert apply_replacements("cloud code", reps) == "Claude Code"


def test_replacement_with_regex_chars_is_literal():
    assert apply_replacements("c++ est rapide", [("c++", "C++")]) == "C++ est rapide"


@pytest.mark.parametrize("text,expected", [
    ("pousse sur github", "pousse sur GitHub"),
    ("le json de l'api", "le JSON de l'API"),
    ("en typescript", "en TypeScript"),
    ("Github et GITHUB", "GitHub et GitHub"),
    ("il faut faire un push", "il faut faire un push"),   # termes en minuscules : pas touchés
    ("Push le code", "Push le code"),                    # ni leur majuscule de début de phrase
    ("githubusercontent", "githubusercontent"),          # pas au milieu d'un mot
    ("claude code", "Claude Code"),
])
def test_apply_term_case(text, expected):
    terms = ["GitHub", "JSON", "API", "TypeScript", "push", "Claude", "Claude Code"]
    assert apply_term_case(text, terms) == expected

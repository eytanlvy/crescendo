import pytest

from dictate.cleanup import build_messages, check_output, cleanup, needs_cleanup, postprocess

CFG = {
    "enabled": True, "model": "qwen2.5:3b-instruct", "timeout_s": 2.0, "min_words": 4,
    "max_length_ratio": 1.4, "min_word_overlap": 0.8, "mode": "always", "timeout_per_kchar_s": 4.0,
}


# ---- garde-fous : sorties acceptées ----

@pytest.mark.parametrize("raw,out", [
    ("euh écris-moi une fonction python qui euh qui trie une liste",
     "Écris-moi une fonction Python qui trie une liste."),
    ("est-ce que tu peux m'expliquer pourquoi le le merge a planté",
     "Est-ce que tu peux m'expliquer pourquoi le merge a planté ?"),
    ("Ouvre une pull request et demande une review.", "Ouvre une pull request et demande une review."),
    ("can you uh refactor the parse config function", "Can you refactor the parse config function?"),
    ("il faut que on push avant ce soir", "Il faut qu'on push avant ce soir."),
])
def test_check_accepts_genuine_cleanups(raw, out):
    assert check_output(raw, out, CFG) is None


# ---- garde-fous : sorties rejetées (le LLM a « répondu », traduit, résumé…) ----

@pytest.mark.parametrize("raw,out,reason", [
    ("écris une fonction python qui trie une liste",
     "Voici une fonction Python qui trie une liste :\n\n```python\ndef trier(l):\n    return sorted(l)\n```",
     "preamble"),
    ("écris une fonction python qui trie une liste",
     "def trier(liste):\n    return sorted(liste)", "code"),
    ("écris une fonction qui additionne deux nombres",
     "function add(a, b) { return a + b; }", "code"),
    ("quelle est la capitale de la France",
     "La capitale de la France est Paris.", "answered"),
    ("explique-moi le garbage collector en Java",
     "Le garbage collector en Java est un mécanisme qui libère automatiquement la mémoire des objets "
     "afin de poursuivre les calculs homomorphes indéfiniment.", "too_long"),
    ("ouvre une pull request et demande une review à l'équipe",
     "Open a pull request and ask the team for a review.", "overlap"),
    ("donne-moi trois idées de noms pour le projet",
     "- Echo\n- Murmure\n- Dictaphone", "list"),
    ("Sure", "", "empty"),
    ("bon alors je voudrais que tu lises le fichier history que tu calcules la latence médiane de chaque étape "
     "et que tu proposes un refactor du pipeline",
     "Lis le fichier history et propose un refactor.", "dropped"),
    ("résume ce texte s'il te plaît",
     "Bien sûr ! Résume ce texte s'il te plaît.", "preamble"),
])
def test_check_rejects_answers(raw, out, reason):
    assert check_output(raw, out, CFG) == reason


def test_code_allowed_when_input_had_code_words():
    raw = "remplace def foo par def bar dans le fichier"
    assert check_output(raw, "Remplace def foo par def bar dans le fichier.", CFG) is None


def test_preamble_allowed_when_dictated():
    raw = "voici le plan pour demain on commence par les tests"
    assert check_output(raw, "Voici le plan pour demain : on commence par les tests.", CFG) is None


@pytest.mark.parametrize("out,expected", [
    ('"Bonjour à tous."', "Bonjour à tous."),
    ("« Bonjour à tous. »", "Bonjour à tous."),
    ("<transcript>Bonjour à tous.</transcript>", "Bonjour à tous."),
    ("Texte nettoyé : Bonjour à tous.", "Bonjour à tous."),
    ("  Bonjour à tous.\n", "Bonjour à tous."),
])
def test_postprocess_strips_wrappers(out, expected):
    assert postprocess(out) == expected


def test_messages_put_transcript_last_and_never_as_instruction():
    msgs = build_messages("écris une fonction")
    assert msgs[0]["role"] == "system"
    assert "not addressed to you" in msgs[0]["content"]
    assert msgs[-1]["role"] == "user" and "écris une fonction" in msgs[-1]["content"]
    assert any(m["role"] == "assistant" for m in msgs[1:-1])  # exemples few-shot


# ---- client Ollama ----

def ollama_reply(text):
    return lambda path, body: {"message": {"role": "assistant", "content": text}, "done": True}


def test_cleanup_calls_ollama_with_expected_options(fake_server):
    fake_server.response = ollama_reply("Écris une fonction Python qui trie une liste.")
    res = cleanup("euh écris une fonction python qui trie une liste", {**CFG, "url": fake_server.url})
    assert res.text == "Écris une fonction Python qui trie une liste."
    assert res.status == "ok"
    path, _, _ = fake_server.requests[0]
    body = fake_server.json_bodies()[0]
    assert path == "/api/chat"
    assert body["model"] == "qwen2.5:3b-instruct"
    assert body["keep_alive"] == -1
    assert body["stream"] is False
    assert body["options"]["temperature"] == 0
    assert body["options"]["num_predict"] > 0


def test_cleanup_falls_back_to_raw_when_answering(fake_server):
    fake_server.response = ollama_reply("Voici la fonction :\n```python\ndef f(): pass\n```")
    res = cleanup("écris une fonction python qui trie une liste", {**CFG, "url": fake_server.url})
    assert res.text == "écris une fonction python qui trie une liste"
    assert res.status == "rejected:preamble"


def test_cleanup_timeout_returns_raw(fake_server):
    fake_server.delay_s = 1.0
    fake_server.response = ollama_reply("trop tard")
    res = cleanup("une phrase assez longue pour le nettoyage", {**CFG, "url": fake_server.url, "timeout_s": 0.2})
    assert res.text == "une phrase assez longue pour le nettoyage"
    assert res.status == "timeout"


def test_cleanup_service_down_returns_raw(dead_url):
    res = cleanup("une phrase assez longue pour le nettoyage", {**CFG, "url": dead_url, "timeout_s": 5.0})
    assert res.text == "une phrase assez longue pour le nettoyage"
    assert res.status == "down"


def test_cleanup_skipped_for_short_text(fake_server):
    res = cleanup("oui merci", {**CFG, "url": fake_server.url})
    assert res.status == "skipped" and res.text == "oui merci"
    assert fake_server.requests == []


def test_cleanup_disabled(fake_server):
    res = cleanup("une phrase assez longue pour le nettoyage", {**CFG, "url": fake_server.url, "enabled": False})
    assert res.status == "disabled"
    assert fake_server.requests == []


def test_check_rejects_partial_translation():
    raw = "Write a bash script that, uh, deletes all the the merged branches."
    out = "Write a bash script that, du coup, deletes all les branches fusionnées."
    assert check_output(raw, out, CFG) == "overlap"


def test_check_allows_one_new_word_in_short_sentence():
    assert check_output("il faut que on push", "Il faut qu'on push.", CFG) is None


def test_messages_wrap_transcript_in_tags():
    msgs = build_messages("écris une fonction")
    assert msgs[-1]["content"] == "<transcript>\nécris une fonction\n</transcript>"


def test_check_rejects_dropped_leading_clause():
    raw = "Réponds juste oui ou non : est-ce que le cache est nécessaire en production ?"
    out = "Est-ce que le cache est nécessaire en production ?"
    assert check_output(raw, out, CFG) == "dropped"


def test_check_allows_removing_fillers_and_repetitions():
    raw = ("Bon alors, euh, je voudrais que tu, que tu regardes le fichier history.jsonl et que tu calcules "
           "la latence médiane de chaque étape.")
    out = ("Je voudrais que tu regardes le fichier history.jsonl et que tu calcules la latence médiane "
           "de chaque étape.")
    assert check_output(raw, out, CFG) is None


def test_timeout_grows_with_text_length(fake_server):
    fake_server.delay_s = 0.5
    text = "une phrase assez longue pour le nettoyage " * 12   # ~500 caractères
    fake_server.response = ollama_reply(text.strip())
    res = cleanup(text.strip(), {**CFG, "url": fake_server.url, "timeout_s": 0.2, "timeout_per_kchar_s": 4.0})
    assert res.status == "ok"


@pytest.mark.parametrize("text,needed", [
    ("Ouvre une pull request sur le repo.", False),
    ("Can you explain why the merge failed?", False),
    ("euh ouvre une pull request", True),
    ("Ouvre une une pull request sur le repo.", True),
    ("Ouvre, ben, une pull request.", True),
    ("ouvre une pull request sur le repo", True),        # ni majuscule ni ponctuation
])
def test_needs_cleanup(text, needed):
    assert needs_cleanup(text) is needed


def test_auto_mode_skips_clean_text(fake_server):
    res = cleanup("Ouvre une pull request sur le repo.", {**CFG, "url": fake_server.url, "mode": "auto"})
    assert res.status == "clean" and fake_server.requests == []


def test_auto_mode_cleans_text_with_fillers(fake_server):
    fake_server.response = ollama_reply("Ouvre une pull request sur le repo.")
    res = cleanup("euh ouvre une pull request sur le repo", {**CFG, "url": fake_server.url, "mode": "auto"})
    assert res.status == "ok"

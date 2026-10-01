import json

import pytest

from dictate.config import load_config
from dictate.pipeline import run
from tests.conftest import FakeServer
from tests.helpers import make_wav


@pytest.fixture
def servers():
    whisper, ollama = FakeServer(), FakeServer()
    yield whisper, ollama
    whisper.close()
    ollama.close()


@pytest.fixture
def cfg(tmp_path, servers):
    whisper, ollama = servers
    vocab = tmp_path / "vocabulary.txt"
    vocab.write_text("Claude Code\nGitHub\npush\ncloud code => Claude Code\n")
    conf = tmp_path / "config.toml"
    conf.write_text(f"""
[whisper]
url = "{whisper.url}"
[cleanup]
url = "{ollama.url}"
timeout_s = 2.0
[paths]
data_dir = "{tmp_path / 'data'}"
vocabulary = "vocabulary.txt"
""")
    return load_config(conf)


def speech_wav(tmp_path, name="a.wav", seconds=1.5):
    return make_wav(tmp_path / name, [(0.2, 0.0), (seconds, 0.3), (0.2, 0.0)])


def llm(text):
    return lambda path, body: {"message": {"role": "assistant", "content": text}}


def history(cfg):
    path = cfg["paths"]["data_dir"] + "/history.jsonl"
    return [json.loads(line) for line in open(path)]


def test_full_pipeline(tmp_path, cfg, servers):
    whisper, ollama = servers
    whisper.response = {"text": " Euh, pousse le code sur github avec cloud code !\n"}
    ollama.response = llm("Pousse le code sur github avec cloud code !")
    res = run(speech_wav(tmp_path), cfg, app="com.apple.Terminal")
    assert res["status"] == "ok"
    assert res["text"] == "Pousse le code sur GitHub avec Claude Code ! "
    assert res["cleanup_status"] == "ok"
    assert set(res["timings_ms"]) >= {"analyze", "whisper", "cleanup", "total"}
    # prompt de vocabulaire envoyé à Whisper
    assert b"Claude Code, GitHub, push" in whisper.requests[0][2]
    rec = history(cfg)[-1]
    assert rec["id"] == res["id"]
    assert rec["raw"] == " Euh, pousse le code sur github avec cloud code !\n"
    assert rec["final"] == "Pousse le code sur GitHub avec Claude Code !"
    assert rec["app"] == "com.apple.Terminal"


def test_enter_mode_has_no_trailing_space(tmp_path, cfg, servers):
    whisper, ollama = servers
    whisper.response = {"text": "Lance les tests maintenant."}
    ollama.response = llm("Lance les tests maintenant.")
    assert run(speech_wav(tmp_path), cfg, mode="enter")["text"] == "Lance les tests maintenant."


def test_too_short_press_skips_everything(tmp_path, cfg, servers):
    whisper, _ = servers
    wav = make_wav(tmp_path / "s.wav", [(0.2, 0.3)])
    res = run(wav, cfg)
    assert res["status"] == "too_short" and res["text"] == ""
    assert whisper.requests == []


def test_silence_skips_whisper(tmp_path, cfg, servers):
    whisper, _ = servers
    res = run(make_wav(tmp_path / "s.wav", [(2.0, 0.0005)]), cfg)
    assert res["status"] == "silence" and res["text"] == ""
    assert whisper.requests == []


def test_hallucination_only_gives_empty(tmp_path, cfg, servers):
    whisper, ollama = servers
    whisper.response = {"text": " Sous-titres réalisés par la communauté d'Amara.org"}
    res = run(speech_wav(tmp_path), cfg)
    assert res["status"] == "empty" and res["text"] == ""
    assert ollama.requests == []


def test_whisper_down_is_an_error(tmp_path, cfg, dead_url):
    cfg["whisper"]["url"] = dead_url
    res = run(speech_wav(tmp_path), cfg)
    assert res["status"] == "error"
    assert res["error_service"] == "whisper"
    assert "injoignable" in res["error"]
    assert history(cfg)[-1]["status"] == "error"


def test_ollama_down_inserts_raw_with_warning(tmp_path, cfg, servers, dead_url):
    whisper, _ = servers
    cfg["cleanup"]["url"] = dead_url
    whisper.response = {"text": " euh pousse sur github avant ce soir"}
    res = run(speech_wav(tmp_path), cfg)
    assert res["status"] == "ok"
    assert res["text"] == "pousse sur GitHub avant ce soir "
    assert res["cleanup_status"] == "down"
    assert any("Ollama" in w for w in res["warnings"])


def test_llm_answer_is_rejected_and_raw_inserted(tmp_path, cfg, servers):
    whisper, ollama = servers
    whisper.response = {"text": " Écris une fonction Python qui trie une liste."}
    ollama.response = llm("```python\ndef f(l):\n    return sorted(l)\n```")
    res = run(speech_wav(tmp_path), cfg)
    assert res["text"] == "Écris une fonction Python qui trie une liste. "
    assert res["cleanup_status"] == "rejected:code"
    assert history(cfg)[-1]["llm_output"].startswith("```python")


def test_audio_is_kept_and_rotated(tmp_path, cfg, servers):
    whisper, ollama = servers
    cfg["recording"]["keep_audio"] = 2
    whisper.response = {"text": "Oui."}
    for i in range(3):
        run(speech_wav(tmp_path, f"w{i}.wav"), cfg)
    kept = sorted((tmp_path / "data" / "audio").glob("*.wav"))
    assert len(kept) == 2


def test_rec_gap_is_window_minus_recorded_duration(tmp_path, cfg, servers):
    whisper, _ = servers
    whisper.response = {"text": "Oui."}
    run(speech_wav(tmp_path), cfg, rec_window_ms=2000.0)  # wav de 1,9 s
    rec = history(cfg)[-1]
    assert rec["rec_window_ms"] == 2000.0
    assert rec["rec_gap_ms"] == 100.0


def test_bad_vocabulary_file_does_not_crash(tmp_path, cfg, servers):
    whisper, _ = servers
    (tmp_path / "vocabulary.txt").write_text("=> cassé\n")
    whisper.response = {"text": "Oui."}
    res = run(speech_wav(tmp_path), cfg)
    assert res["status"] == "ok" and res["text"] == "Oui. "
    assert any("vocabulaire" in w for w in res["warnings"])


def test_falls_back_to_example_vocabulary_when_personal_file_missing(tmp_path, cfg, servers):
    whisper, _ = servers
    (tmp_path / "vocabulary.txt").unlink()
    (tmp_path / "vocabulary.example.txt").write_text("Kubernetes\n")
    whisper.response = {"text": "Déploie sur kubernetes."}
    res = run(speech_wav(tmp_path), cfg)
    assert res["text"] == "Déploie sur Kubernetes. "
    assert res["warnings"] == []
    assert b"Kubernetes" in whisper.requests[0][2]

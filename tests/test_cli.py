import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import FakeServer
from tests.helpers import make_wav

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin" / "dictate"


def dictate(*args, config=None):
    cmd = [sys.executable, str(BIN), *args]
    if config:
        cmd[2:2] = ["--config", str(config)]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30)


@pytest.fixture
def setup(tmp_path):
    whisper, ollama = FakeServer(), FakeServer()
    (tmp_path / "vocabulary.txt").write_text("GitHub\n")
    conf = tmp_path / "config.toml"
    conf.write_text(f'[whisper]\nurl = "{whisper.url}"\n[cleanup]\nurl = "{ollama.url}"\n'
                    f"[paths]\ndata_dir = '{tmp_path / 'data'}'\n")
    wav = make_wav(tmp_path / "a.wav", [(1.0, 0.3)])
    yield conf, wav, whisper, ollama
    whisper.close()
    ollama.close()


def test_config_json_for_lua():
    out = dictate("config", "--json")
    assert out.returncode == 0, out.stderr
    cfg = json.loads(out.stdout)
    assert cfg["hotkeys_parsed"]["dictate"] == {"mods": ["alt"], "key": "space"}
    assert cfg["repo_dir"] == str(REPO)


def test_invalid_config_exits_1(tmp_path):
    bad = tmp_path / "config.toml"
    bad.write_text("[nope]\n")
    out = dictate("config", "--json", config=bad)
    assert out.returncode == 1
    assert "section inconnue" in out.stderr


def test_transcribe_plain_prints_text(setup):
    conf, wav, whisper, ollama = setup
    whisper.response = {"text": " pousse sur github"}
    out = dictate(str(wav), config=conf)
    assert out.returncode == 0, out.stderr
    assert out.stdout == "pousse sur GitHub\n"


def test_transcribe_json(setup):
    conf, wav, whisper, ollama = setup
    whisper.response = {"text": " pousse le code sur github ce soir"}
    ollama.response = {"message": {"content": "Pousse le code sur github ce soir."}}
    out = dictate(str(wav), "--json", "--mode", "enter", "--app", "com.test", "--rec-window-ms", "1100", config=conf)
    res = json.loads(out.stdout)
    assert res["status"] == "ok"
    assert res["text"] == "Pousse le code sur GitHub ce soir."
    rec = json.loads((conf.parent / "data" / "history.jsonl").read_text().splitlines()[-1])
    assert rec["app"] == "com.test" and rec["rec_gap_ms"] == 100.0 and rec["mode"] == "enter"


def test_whisper_down_exits_2(setup, dead_url, tmp_path):
    conf, wav, _, _ = setup
    conf.write_text(conf.read_text().replace(conf.read_text().split('"')[1], dead_url, 1))
    out = dictate(str(wav), "--json", config=conf)
    assert out.returncode == 2
    assert json.loads(out.stdout)["error_service"] == "whisper"


def test_history_stats(setup):
    conf, wav, whisper, ollama = setup
    whisper.response = {"text": "Oui."}
    for _ in range(3):
        dictate(str(wav), config=conf)
    out = dictate("history", "--stats", config=conf)
    assert out.returncode == 0, out.stderr
    assert "whisper" in out.stdout and "p50" in out.stdout
    out = dictate("history", "-n", "2", config=conf)
    assert out.stdout.count("Oui.") == 2


def test_text_out_writes_final_text_utf8(setup, tmp_path):
    conf, wav, whisper, ollama = setup
    whisper.response = {"text": " Déploie ça sur github, s'il te plaît."}
    ollama.response = {"message": {"content": "Déploie ça sur github, s'il te plaît."}}
    out_file = tmp_path / "out.txt"
    out = dictate(str(wav), "--text-out", str(out_file), "--mode", "enter", config=conf)
    assert out.returncode == 0, out.stderr
    assert out_file.read_text(encoding="utf-8") == "Déploie ça sur GitHub, s'il te plaît."


def test_text_out_empty_on_silence(setup, tmp_path):
    conf, _, _, _ = setup
    silent = make_wav(tmp_path / "s.wav", [(1.0, 0.0)])
    out_file = tmp_path / "out.txt"
    out = dictate(str(silent), "--text-out", str(out_file), config=conf)
    assert out.returncode == 0
    assert out_file.read_text(encoding="utf-8") == ""

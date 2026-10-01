import json
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest

from dictate.audio import analyze_wav, ensure_wav
from dictate.config import platform_defaults

REPO = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
def test_platform_defaults_are_complete(platform):
    d = platform_defaults(platform)
    assert d["paths"]["python"] and d["recording"]["rec_binary"] and d["paths"]["data_dir"]
    assert d["whisper"]["model"].endswith("ggml-large-v3-turbo-q8_0.bin")


def test_platform_defaults_differ_where_needed():
    mac, linux, win = (platform_defaults(p) for p in ("darwin", "linux", "win32"))
    assert mac["recording"]["rec_binary"] == "/opt/homebrew/bin/rec"
    assert linux["recording"]["rec_binary"] == "arecord"
    assert win["recording"]["rec_binary"] == "sox"
    assert "AppData" in win["paths"]["data_dir"] or "LOCALAPPDATA" in win["paths"]["data_dir"]


def test_raw_pcm_is_wrapped_into_wav(tmp_path):
    pcm = tmp_path / "rec.pcm"
    pcm.write_bytes(b"".join(struct.pack("<h", 8000 if i % 20 < 10 else -8000) for i in range(16000)))
    wav = ensure_wav(pcm)
    assert wav.suffix == ".wav"
    with wave.open(str(wav)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (16000, 1, 2, 16000)
    assert analyze_wav(wav).duration_s == pytest.approx(1.0)


def test_wav_is_returned_unchanged(tmp_path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"RIFF")
    assert ensure_wav(p) == p


def test_config_get_single_value():
    out = subprocess.run([sys.executable, str(REPO / "bin" / "dictate"), "config", "--get", "hotkeys.dictate"],
                         capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "alt+space"


def test_config_get_nested_json_value():
    out = subprocess.run([sys.executable, str(REPO / "bin" / "dictate"), "config", "--get", "hotkeys_parsed.dictate"],
                         capture_output=True, text=True, encoding="utf-8")
    assert json.loads(out.stdout) == {"mods": ["alt"], "key": "space"}


def test_python_dash_m_entry_point():
    out = subprocess.run([sys.executable, "-m", "dictate", "config", "--get", "whisper.language"],
                         capture_output=True, text=True, encoding="utf-8", cwd=REPO)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "fr"

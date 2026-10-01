import json
from pathlib import Path

import pytest

from dictate.config import ConfigError, load_config, parse_hotkey

REPO = Path(__file__).resolve().parent.parent


def write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text)
    return p


def test_empty_file_gives_defaults(tmp_path):
    cfg = load_config(write(tmp_path, ""))
    assert cfg["hotkeys"]["dictate"] == "alt+space"
    assert cfg["hotkeys"]["dictate_and_enter"] == "alt+shift+space"
    assert cfg["cleanup"]["enabled"] is True
    assert cfg["recording"]["max_duration_s"] == 120


def test_override_merges_with_defaults(tmp_path):
    cfg = load_config(write(tmp_path, '[whisper]\nlanguage = "auto"\n'))
    assert cfg["whisper"]["language"] == "auto"
    assert cfg["whisper"]["timeout_s"] > 0  # autres clés conservées


def test_unknown_key_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="whisper.langage"):
        load_config(write(tmp_path, '[whisper]\nlangage = "fr"\n'))


def test_unknown_section_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="whispr"):
        load_config(write(tmp_path, '[whispr]\nlanguage = "fr"\n'))


def test_wrong_type_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="cleanup.enabled"):
        load_config(write(tmp_path, '[cleanup]\nenabled = "yes"\n'))


def test_int_accepted_where_float_expected(tmp_path):
    cfg = load_config(write(tmp_path, "[recording]\nmin_duration_s = 1\n"))
    assert cfg["recording"]["min_duration_s"] == 1.0


def test_invalid_toml_reports_path(tmp_path):
    p = write(tmp_path, "[whisper\n")
    with pytest.raises(ConfigError, match="config.toml"):
        load_config(p)


def test_paths_are_expanded(tmp_path):
    cfg = load_config(write(tmp_path, '[paths]\ndata_dir = "~/foo"\n'))
    assert cfg["paths"]["data_dir"] == str(Path.home() / "foo")


def test_relative_vocabulary_resolved_against_config_dir(tmp_path):
    cfg = load_config(write(tmp_path, '[paths]\nvocabulary = "vocab.txt"\n'))
    assert cfg["paths"]["vocabulary"] == str(tmp_path / "vocab.txt")


def test_invalid_language_rejected(tmp_path):
    with pytest.raises(ConfigError, match="language"):
        load_config(write(tmp_path, '[whisper]\nlanguage = "french"\n'))


def test_invalid_hotkey_rejected(tmp_path):
    with pytest.raises(ConfigError, match="hotkeys.dictate"):
        load_config(write(tmp_path, '[hotkeys]\ndictate = "hyper+space"\n'))


@pytest.mark.parametrize("spec,mods,key", [
    ("alt+space", ["alt"], "space"),
    ("Option+Shift+Space", ["alt", "shift"], "space"),
    ("cmd+ctrl+d", ["cmd", "ctrl"], "d"),
    ("f13", [], "f13"),
])
def test_parse_hotkey(spec, mods, key):
    assert parse_hotkey(spec) == {"mods": mods, "key": key}


@pytest.mark.parametrize("spec", ["", "alt+", "alt+shift", "alt+space+x"])
def test_parse_hotkey_invalid(spec):
    with pytest.raises(ValueError):
        parse_hotkey(spec)


def test_repo_config_is_valid_and_json_serializable():
    cfg = load_config(REPO / "config.toml")
    json.dumps(cfg)
    vocab = Path(cfg["paths"]["vocabulary"])
    assert vocab.exists() or vocab.with_name("vocabulary.example.txt").exists()

"""Chargement et validation de config.toml (stdlib : tomllib)."""
from __future__ import annotations

import copy
import tomllib
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_DIR / "config.toml"

DEFAULTS: dict = {
    "hotkeys": {
        "dictate": "alt+space",
        "dictate_and_enter": "alt+shift+space",
    },
    "recording": {
        "rec_binary": "/opt/homebrew/bin/rec",
        "min_duration_s": 0.3,
        "max_duration_s": 120,
        "tail_ms": 150,
        "speech_threshold_dbfs": -42.0,
        "min_speech_s": 0.15,
        "keep_audio": 50,
    },
    "whisper": {
        "url": "http://127.0.0.1:8178",
        "model": "~/.local/share/voice-dictation/models/ggml-large-v3-turbo-q8_0.bin",
        "language": "fr",
        "threads": 4,
        "timeout_s": 20.0,
        "use_vocabulary_prompt": True,
    },
    "cleanup": {
        "enabled": True,
        "mode": "always",
        "url": "http://127.0.0.1:11434",
        "model": "qwen2.5:3b-instruct",
        "timeout_s": 4.0,
        "timeout_per_kchar_s": 4.0,
        "min_words": 4,
        "max_length_ratio": 1.4,
        "min_word_overlap": 0.8,
    },
    "output": {
        "trailing_space": True,
        "auto_case_terms": True,
        "restore_clipboard_delay_ms": 400,
        "enter_delay_ms": 120,
    },
    "feedback": {
        "sounds": True,
        "sound_start": "Tink",
        "sound_stop": "Pop",
        "sound_error": "Basso",
        "volume": 0.25,
        "overlay": True,
    },
    "paths": {
        "data_dir": "~/.local/share/voice-dictation",
        "vocabulary": "vocabulary.txt",
        "python": "/opt/homebrew/bin/python3",
    },
}

MODIFIERS = {
    "alt": "alt", "option": "alt", "opt": "alt", "⌥": "alt",
    "cmd": "cmd", "command": "cmd", "⌘": "cmd",
    "ctrl": "ctrl", "control": "ctrl", "⌃": "ctrl",
    "shift": "shift", "⇧": "shift",
}
MODIFIER_ORDER = ["cmd", "alt", "ctrl", "shift"]
# Codes ISO 639-1 acceptés par Whisper les plus probables ici, plus "auto".
LANGUAGES = {"auto", "fr", "en", "de", "es", "it", "pt", "nl", "he", "ar", "ja", "zh", "ru"}


class ConfigError(Exception):
    pass


def parse_hotkey(spec: str) -> dict:
    """"alt+shift+space" → {"mods": ["alt", "shift"], "key": "space"} (modificateurs triés, alias normalisés)."""
    parts = [p.strip().lower() for p in spec.split("+")]
    if not parts or any(not p for p in parts):
        raise ValueError(f"raccourci invalide : {spec!r}")
    *mods, key = parts
    if key in MODIFIERS:
        raise ValueError(f"raccourci sans touche principale : {spec!r}")
    norm = []
    for m in mods:
        if m not in MODIFIERS:
            raise ValueError(f"modificateur inconnu {m!r} dans {spec!r} (attendu : cmd, alt, ctrl, shift)")
        norm.append(MODIFIERS[m])
    if len(key) > 1 and key not in _NAMED_KEYS:
        raise ValueError(f"touche inconnue {key!r} dans {spec!r}")
    return {"mods": sorted(set(norm), key=MODIFIER_ORDER.index), "key": key}


_NAMED_KEYS = {"space", "return", "tab", "escape", "delete", "home", "end", "pageup", "pagedown",
               "left", "right", "up", "down", *(f"f{i}" for i in range(1, 21))}


def _merge(defaults: dict, user: dict, config_path: Path) -> dict:
    cfg = copy.deepcopy(defaults)
    for section, values in user.items():
        if section not in defaults:
            raise ConfigError(f"{config_path}: section inconnue [{section}]")
        if not isinstance(values, dict):
            raise ConfigError(f"{config_path}: [{section}] doit être une section")
        for key, value in values.items():
            name = f"{section}.{key}"
            if key not in defaults[section]:
                raise ConfigError(f"{config_path}: clé inconnue {name}")
            expected = type(defaults[section][key])
            if expected is float and isinstance(value, int) and not isinstance(value, bool):
                value = float(value)
            if type(value) is not expected:
                raise ConfigError(f"{config_path}: {name} doit être de type {expected.__name__}, "
                                  f"reçu {value!r}")
            cfg[section][key] = value
    return cfg


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict:
    path = Path(path)
    try:
        user = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"{path}: fichier introuvable") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: TOML invalide ({e})") from None
    cfg = _merge(DEFAULTS, user, path)

    for name in ("dictate", "dictate_and_enter"):
        try:
            parse_hotkey(cfg["hotkeys"][name])
        except ValueError as e:
            raise ConfigError(f"{path}: hotkeys.{name} : {e}") from None
    if cfg["cleanup"]["mode"] not in ("always", "auto"):
        raise ConfigError(f"{path}: cleanup.mode doit être \"always\" ou \"auto\"")
    if cfg["whisper"]["language"] not in LANGUAGES:
        raise ConfigError(f"{path}: whisper.language doit être l'un de {sorted(LANGUAGES)}")

    for key in ("data_dir", "python"):
        cfg["paths"][key] = str(Path(cfg["paths"][key]).expanduser())
    vocab = Path(cfg["paths"]["vocabulary"]).expanduser()
    cfg["paths"]["vocabulary"] = str(vocab if vocab.is_absolute() else path.parent / vocab)
    cfg["whisper"]["model"] = str(Path(cfg["whisper"]["model"]).expanduser())
    cfg["recording"]["rec_binary"] = str(Path(cfg["recording"]["rec_binary"]).expanduser())
    cfg["hotkeys_parsed"] = {k: parse_hotkey(v) for k, v in cfg["hotkeys"].items()}
    cfg["repo_dir"] = str(REPO_DIR)
    return cfg

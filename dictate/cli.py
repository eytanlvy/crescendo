"""Interface en ligne de commande.

  dictate FICHIER.wav [--json] [--mode insert|enter] [--app ID] [--rec-window-ms N]
  dictate config --json          configuration résolue (lue par Hammerspoon)
  dictate warmup [--wait S]      charge les modèles (Whisper, Ollama) ; attend les services jusqu'à S secondes
  dictate history [-n N] [--stats]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import struct
import sys
import tempfile
import time
import wave
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, ConfigError, load_config

EXIT_OK, EXIT_CONFIG, EXIT_SERVICE = 0, 1, 2


def _print_json(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")


def cmd_transcribe(cfg: dict, args) -> int:
    from .pipeline import run
    res = run(args.wav, cfg, mode=args.mode, app=args.app, rec_window_ms=args.rec_window_ms)
    if args.json:
        _print_json(res)
    else:
        for w in res["warnings"]:
            print(f"attention : {w}", file=sys.stderr)
        if res["status"] == "error":
            print(f"erreur : {res['error']}", file=sys.stderr)
        elif res["text"]:
            print(res["text"].rstrip(" "))
    return EXIT_SERVICE if res["status"] == "error" else EXIT_OK


def _noise_wav(path: Path, seconds: float = 1.0) -> None:
    rnd = random.Random(0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(i / 7) + rnd.randint(-800, 800)))
                               for i in range(int(16000 * seconds))))


def cmd_warmup(cfg: dict, args) -> int:
    from .cleanup import warmup as warm_llm
    from .services import ServiceError
    from .whisper import transcribe
    deadline = time.monotonic() + args.wait
    result: dict = {}
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "warmup.wav"
        _noise_wav(wav)
        for name, fn in [
            ("whisper", lambda: transcribe(wav, cfg["whisper"]["url"], cfg["whisper"]["language"], "", 60)),
            ("ollama", lambda: warm_llm(cfg["cleanup"]) if cfg["cleanup"]["enabled"] else None),
        ]:
            while True:
                t0 = time.perf_counter()
                try:
                    fn()
                    result[f"{name}_ms"] = round((time.perf_counter() - t0) * 1000)
                    break
                except ServiceError as e:
                    if time.monotonic() >= deadline:
                        result[f"{name}_error"] = str(e)
                        break
                    time.sleep(1.0)
    _print_json(result)
    return EXIT_SERVICE if any(k.endswith("_error") for k in result) else EXIT_OK


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _pct(values: list[float]) -> str:
    if not values:
        return "—"
    return f"p50 {statistics.median(values):6.0f} ms   max {max(values):6.0f} ms   (n={len(values)})"


def cmd_history(cfg: dict, args) -> int:
    data_dir = Path(cfg["paths"]["data_dir"])
    records = _read_jsonl(data_dir / "history.jsonl")
    if args.stats:
        ok = [r for r in records if r.get("status") == "ok"]
        print(f"{len(records)} dictées, dont {len(ok)} insérées")
        for stage in ["analyze", "whisper", "filter", "cleanup", "finalize", "total"]:
            print(f"  {stage:9s} {_pct([r['timings_ms'][stage] for r in ok if stage in r.get('timings_ms', {})])}")
        e2e = [r["e2e_ms"] for r in _read_jsonl(data_dir / "e2e.jsonl") if "e2e_ms" in r]
        print(f"  {'relâche→insertion':9s} {_pct(e2e)}")
        gaps = [r["rec_gap_ms"] for r in records if r.get("rec_gap_ms") is not None]
        print(f"  {'démarrage rec':9s} {_pct(gaps)}")
        statuses: dict[str, int] = {}
        for r in ok:
            statuses[r.get("cleanup_status", "?")] = statuses.get(r.get("cleanup_status", "?"), 0) + 1
        print(f"  nettoyage : {statuses}")
        return EXIT_OK
    for r in records[-args.n:]:
        total = r.get("timings_ms", {}).get("total", 0)
        line = f"{r.get('ts', '')[:19]}  {r.get('status', ''):9s} {total:6.0f} ms  {r.get('final', '')}"
        print(line)
        if args.verbose and r.get("raw"):
            print(f"{'':32s}brut : {r['raw'].strip()}  [{r.get('cleanup_status', '')}]")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=os.environ.get("DICTATE_CONFIG", str(DEFAULT_CONFIG_PATH)))
    pre, rest = common.parse_known_args(argv)

    if rest and rest[0] in ("config", "warmup", "history"):
        ap = argparse.ArgumentParser(prog="dictate", parents=[common])
        sub = ap.add_subparsers(dest="cmd", required=True)
        p = sub.add_parser("config")
        p.add_argument("--json", action="store_true")
        p = sub.add_parser("warmup")
        p.add_argument("--wait", type=float, default=0.0)
        p = sub.add_parser("history")
        p.add_argument("-n", type=int, default=20)
        p.add_argument("--stats", action="store_true")
        p.add_argument("-v", "--verbose", action="store_true")
    else:
        ap = argparse.ArgumentParser(prog="dictate", parents=[common])
        ap.add_argument("wav")
        ap.add_argument("--json", action="store_true")
        ap.add_argument("--mode", choices=["insert", "enter"], default="insert")
        ap.add_argument("--app")
        ap.add_argument("--rec-window-ms", type=float)
    args = ap.parse_args(argv)

    try:
        cfg = load_config(pre.config)
    except ConfigError as e:
        print(f"erreur de configuration : {e}", file=sys.stderr)
        if getattr(args, "json", False) and getattr(args, "cmd", None) is None:
            _print_json({"status": "error", "error": f"configuration : {e}", "error_service": "config",
                         "text": "", "warnings": []})
        return EXIT_CONFIG

    cmd = getattr(args, "cmd", None)
    if cmd == "config":
        _print_json(cfg)
        return EXIT_OK
    if cmd == "warmup":
        return cmd_warmup(cfg, args)
    if cmd == "history":
        return cmd_history(cfg, args)
    return cmd_transcribe(cfg, args)

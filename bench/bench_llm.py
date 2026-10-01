"""Compare des modèles de nettoyage sur les entrées piégeuses : acceptation, termes conservés, latence.

Usage : python3 bench/bench_llm.py qwen2.5:3b-instruct llama3.2:3b [--runs 2]
"""
import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dictate.cleanup import cleanup, warmup  # noqa: E402
from dictate.config import load_config  # noqa: E402
from tricky import TRICKY  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    base = load_config()["cleanup"]
    for model in args.models:
        cfg = {**base, "model": model, "timeout_s": 30.0}
        print(f"\n=== {model} — chargement {warmup(cfg):.0f} ms")
        lat, ok, kept_fail = [], 0, 0
        for raw, must_keep in TRICKY:
            for _ in range(args.runs):
                res = cleanup(raw, cfg)
            lat.append(res.ms)
            missing = [w for w in must_keep if w.lower() not in res.text.lower()]
            ok += res.status == "ok"
            kept_fail += bool(missing)
            flag = "OK " if res.status == "ok" and not missing else "!! "
            print(f"{flag}{res.ms:6.0f} ms  {res.status:18s} {raw[:60]!r}")
            if args.verbose or res.status != "ok" or missing:
                print(f"      → {res.text!r}")
                if res.llm_output and res.status != "ok":
                    print(f"      LLM : {res.llm_output[:160]!r}")
                if missing:
                    print(f"      manquants : {missing}")
        print(f"--- {model} : acceptés {ok}/{len(TRICKY)}, termes perdus {kept_fail}, "
              f"latence p50 {statistics.median(lat):.0f} ms, max {max(lat):.0f} ms")


if __name__ == "__main__":
    main()

"""Compare des configurations Whisper : WER, termes techniques exacts, latence.

Usage : python3 bench/bench_whisper.py --server q5=http://127.0.0.1:8178 --server q8=http://127.0.0.1:8179 \
            [--samples DIR] [--runs 3] [--languages fr,auto] [--audio-ctx 0,dyn]

DIR doit contenir des wav et un references.json {id: texte de référence}.
"""
import argparse
import json
import statistics
import sys
import time
import uuid
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dictate.filters import clean_transcript, fold  # noqa: E402
from dictate.services import post  # noqa: E402
from dictate.vocab import build_prompt, load_vocabulary  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def words(text):
    return [w for w in (fold(x) for x in text.replace("'", " ").replace("-", " ").split()) if w]


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    if not r:
        return 0.0 if not h else 1.0
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
            prev, d[j] = d[j], cur
    return d[len(h)] / len(r)


def term_hits(ref, hyp, terms):
    """Termes du vocabulaire présents dans la référence : combien sont transcrits à l'identique ?"""
    present = [t for t in terms if t.lower() in ref.lower()]
    return sum(t in hyp for t in present), len(present)


def request(url, wav, language, prompt, audio_ctx):
    fields = {"response_format": "json", "temperature": "0.0", "language": language}
    if prompt:
        fields["prompt"] = prompt
    if audio_ctx:
        fields["audio_ctx"] = str(audio_ctx)
    b = uuid.uuid4().hex
    body = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                    for k, v in fields.items())
    body += (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
             f"Content-Type: audio/wav\r\n\r\n").encode() + wav.read_bytes() + f"\r\n--{b}--\r\n".encode()
    t0 = time.perf_counter()
    data = post("whisper", url + "/inference", body, f"multipart/form-data; boundary={b}", 60)
    return data["text"], (time.perf_counter() - t0) * 1000


def dyn_ctx(wav):
    with wave.open(str(wav)) as w:
        seconds = w.getnframes() / w.getframerate()
    # 1500 positions = 30 s → 50/s ; marge de 1 s ; multiple de 64 (efficacité GPU).
    return min(1500, int((seconds + 1) * 50 + 63) // 64 * 64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", action="append", required=True, help="nom=url")
    ap.add_argument("--samples", default=str(REPO / "bench" / "samples"))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--languages", default="fr,auto")
    ap.add_argument("--audio-ctx", default="0,dyn")
    ap.add_argument("--no-prompt", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    samples = Path(args.samples)
    refs = json.loads((samples / "references.json").read_text())
    refs = {k: v for k, v in refs.items() if v and (samples / f"{k}.wav").exists()}
    terms = load_vocabulary(REPO / "vocabulary.txt").terms
    prompt = "" if args.no_prompt else build_prompt(terms)

    print(f"{'config':28s} {'WER':>6s} {'termes':>8s} {'lat p50':>8s} {'lat max':>8s}")
    for server in args.server:
        name, url = server.split("=", 1)
        for lang in args.languages.split(","):
            for ctx_mode in args.audio_ctx.split(","):
                wers, lats, hits, total = [], [], 0, 0
                for sid, ref in refs.items():
                    wav = samples / f"{sid}.wav"
                    ctx = dyn_ctx(wav) if ctx_mode == "dyn" else int(ctx_mode)
                    for _ in range(args.runs):
                        text, ms = request(url, wav, lang, prompt, ctx)
                        lats.append(ms)
                    hyp = clean_transcript(text, prompt)
                    wers.append(wer(ref, hyp))
                    h, t = term_hits(ref, hyp, terms)
                    hits, total = hits + h, total + t
                    if args.verbose:
                        print(f"   {sid:14s} WER {wers[-1]:.2f}  {hyp}")
                label = f"{name} lang={lang} ctx={ctx_mode}"
                print(f"{label:28s} {statistics.mean(wers):6.1%} {hits:3d}/{total:<3d} "
                      f"{statistics.median(lats):7.0f}  {max(lats):7.0f}")


if __name__ == "__main__":
    main()

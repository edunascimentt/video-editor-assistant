#!/usr/bin/env python3
"""Find which file belongs to a take, and its exact offset, by audio alone.

    sync_offset.py match REF CAND [CAND ...]       which candidates are the same take (peak score)
    sync_offset.py offset REF OTHER [--windows 3]  t_other = t_ref + offset, refined per window

Method (measured on 3–4 camera shoots and on screen-recording vs camera pairs):
  1. loudness envelope at 20 Hz — ffmpeg 8 kHz mono, RMS over 400-sample windows,
     log1p, z-score — cross-correlated over the whole file (FFT, no scipy);
     the right file peaks at 0.78–0.9, other takes at 0.1–0.3;
  2. refine at 200 Hz inside ±3 s of the coarse lag, in several windows spread
     over the overlap. The spread between windows is the drift; < 1 frame is good.
     Resolution is 5 ms (the 200 Hz envelope) — well under a frame at any rate.

Offsets are in seconds of each file's own timeline (media time), so they hold
whatever the frame rate: frame = round((t_ref + offset) * fps_of_other).
Needs ffmpeg and numpy.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

import numpy as np

AUDIO_SR = 8000


def pcm(path: str, start: float = 0.0, dur: float | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-ss", f"{start:.3f}"]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-map", "0:a:0", "-ac", "1", "-ar", str(AUDIO_SR), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True)
    if out.returncode:
        raise SystemExit(f"ffmpeg failed on {path}: {out.stderr.decode()[-300:]}")
    return np.frombuffer(out.stdout, dtype=np.float32)


def envelope(x: np.ndarray, rate: int) -> np.ndarray:
    hop = AUDIO_SR // rate
    n = len(x) // hop
    if n == 0:
        return np.zeros(0)
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1))
    e = np.log1p(rms * 1000)
    return (e - e.mean()) / (e.std() + 1e-9)


def xcorr(a: np.ndarray, b: np.ndarray) -> tuple[int, float]:
    """Lag L (in envelope samples) maximising sum a[i] * b[i + L], and its normalised score.

    Positive L: the event at a[i] happens at b[i + L] — b started recording earlier.
    """
    n = len(a) + len(b) - 1
    size = 1 << (n - 1).bit_length()
    c = np.fft.irfft(np.fft.rfft(b, size) * np.conj(np.fft.rfft(a, size)), size)
    c = np.concatenate([c[-(len(a) - 1):], c[: len(b)]]) if len(a) > 1 else c[: len(b)]
    k = int(np.argmax(c))
    lag = k - (len(a) - 1)
    overlap = min(len(a), len(b), len(a) - max(0, -lag), len(b) - max(0, lag))
    return lag, float(c[k]) / max(overlap, 1)


def coarse(ref: np.ndarray, other: np.ndarray) -> tuple[float, float]:
    ea, eb = envelope(ref, 20), envelope(other, 20)
    lag, score = xcorr(ea, eb)
    return lag / 20.0, score


def refine(ref_path: str, other_path: str, offset: float, ref_len: float,
           other_len: float, windows: int, win: float = 30.0, search: float = 3.0):
    """Re-measure the offset at 200 Hz in `windows` spots across the overlap."""
    lo = max(0.0, -offset) + search
    hi = min(ref_len, other_len - offset) - win - search
    if hi <= lo:
        return []
    spots = np.linspace(lo, hi, windows) if windows > 1 else [lo]
    out = []
    for t in spots:
        a = pcm(ref_path, t, win)
        b = pcm(other_path, t + offset - search, win + 2 * search)
        ea, eb = envelope(a, 200), envelope(b, 200)
        lag, score = xcorr(ea, eb)
        out.append((float(t), offset - search + lag / 200.0, score))
    return out


def dur(path: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def cmd_match(a):
    ref = pcm(a.ref, 0, a.max_seconds)
    rows = []
    for c in a.cands:
        off, score = coarse(ref, pcm(c, 0, a.max_seconds))
        rows.append((score, off, c))
    rows.sort(reverse=True)
    for score, off, c in rows:
        flag = "  <- same take" if score >= a.min_score else ""
        print(f"{score:6.3f}  offset {off:+9.2f}s  {c}{flag}")


def cmd_offset(a):
    ref_len, other_len = dur(a.ref), dur(a.other)
    off, score = coarse(pcm(a.ref), pcm(a.other))
    print(f"coarse: t_other = t_ref {off:+.2f} s   (score {score:.3f})")
    if score < 0.5:
        print("  score is low — probably not the same take; check with `match`", file=sys.stderr)
    fine = refine(a.ref, a.other, off, ref_len, other_len, a.windows)
    if not fine:
        print("overlap too short to refine")
        return
    for t, o, s in fine:
        print(f"  at ref {t:8.1f}s  offset {o:+.4f}s  (score {s:.3f})")
    vals = np.array([o for _, o, _ in fine])
    print(f"offset: t_other = t_ref {np.median(vals):+.4f} s   drift {1000 * (vals.max() - vals.min()):.0f} ms")
    ends_at = other_len - float(np.median(vals))       # other's last second, in ref time
    if ends_at < ref_len - 0.5:
        print(f"note: {a.other} ends at ref {ends_at:.1f}s — no coverage after that")
    starts_at = -float(np.median(vals))
    if starts_at > 0.5:
        print(f"note: {a.other} starts at ref {starts_at:.1f}s — no coverage before that")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("match")
    s.add_argument("ref")
    s.add_argument("cands", nargs="+")
    s.add_argument("--max-seconds", type=float, default=None,
                   help="only the first N s of each file (faster; keep it longer than the offset)")
    s.add_argument("--min-score", type=float, default=0.5)
    s.set_defaults(fn=cmd_match)
    s = sub.add_parser("offset")
    s.add_argument("ref")
    s.add_argument("other")
    s.add_argument("--windows", type=int, default=3)
    s.set_defaults(fn=cmd_offset)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Put the in/out of hand-picked spans on real silence, not on transcript times.

    span_edges.py spans.json [--head 0.20] [--tail 0.32] > spans.edges.json

spans.json:
    [{"id": "b03", "audio": "/path/clip.mp4", "words": "/path/words.json",
      "start": 48.5, "end": 55.2, "text": "what is said"}, ...]
    start/end are rough source seconds (from segments or your reading);
    words is a WhisperX json ({"segments":[{"words":[{word,start,end}]}]}).

Why: transcript times are not edges. Segment boundaries run into the
neighbouring word in ~40% of cases, and the aligner sometimes stretches one
token over a pause (a closing word measured 3.1 s long), so a span that starts
on t0 or ends on t1 either eats a short article or drags in the next sentence.

Method, per span:
  1. the span's words = those whose midpoint falls inside [start, end];
  2. room tone = 2nd percentile of the 300 ms-smoothed 10 ms energy of that clip;
  3. walk BACK from the first word's END and FORWARD from the last word's START
     until 120 ms in a row sit under room tone + 9 dB — walking from inside the
     word is what defeats a stretched token;
  4. pad by --head / --tail, but never past the silence that was found;
  5. never cross the neighbouring words (previous word's end / next word's start).
Spans whose walk hit a limit are flagged "check": listen or re-transcribe a wide
window around them.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

import numpy as np

SR = 16000
HOP = 0.01
_cache: dict[str, tuple[np.ndarray, float]] = {}


def energy(path: str) -> tuple[np.ndarray, float]:
    if path in _cache:
        return _cache[path]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-ac", "1",
                          "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    n = int(SR * HOP)
    k = len(x) // n
    e = 10 * np.log10(np.mean(x[: k * n].reshape(k, n) ** 2, axis=1) + 1e-12)
    sm = np.convolve(e, np.ones(30) / 30, mode="same")
    floor = float(np.percentile(sm, 2))
    _cache[path] = (e, floor)
    return e, floor


def words_of(path: str) -> list[dict]:
    d = json.load(open(path, encoding="utf-8"))
    out = []
    for s in d.get("segments", []):
        for w in s.get("words", []):
            if "start" in w and "end" in w:
                out.append({"w": w["word"], "t0": float(w["start"]), "t1": float(w["end"])})
    return sorted(out, key=lambda w: w["t0"])


def walk(e, floor, t, direction, limit, run=0.12, margin=9.0):
    """From time t, step until `run` seconds in a row are quiet. Returns (edge, silence_len, hit_limit)."""
    need = int(run / HOP)
    i = int(t / HOP)
    lim = int(limit / HOP)
    quiet = 0
    while 0 <= i < len(e) and (i - lim) * direction < 0:
        quiet = quiet + 1 if e[i] < floor + margin else 0
        if quiet >= need:
            edge_i = i - direction * (need - 1)       # first quiet step
            # how much silence continues past the edge (for padding)
            j = i
            while 0 <= j < len(e) and (j - lim) * direction < 0 and e[j] < floor + margin:
                j += direction
            return edge_i * HOP, abs(j - edge_i) * HOP, False
        i += direction
    return t, 0.0, True


def refine(span, head, tail):
    e, floor = energy(span["audio"])
    ws = words_of(span["words"])
    s, t = span["start"], span["end"]
    inside = [w for w in ws if s <= (w["t0"] + w["t1"]) / 2 <= t]
    out = dict(span)
    if not inside:
        out["check"] = "no words inside the span — transcript gap? re-transcribe a wide window"
        return out
    first, last = inside[0], inside[-1]
    prev = [w for w in ws if w["t1"] <= first["t0"] and w is not first]
    nxt = [w for w in ws if w["t0"] >= last["t1"] and w is not last]
    lo = prev[-1]["t1"] if prev else 0.0
    hi = nxt[0]["t0"] if nxt else len(e) * HOP
    a, sil_a, hit_a = walk(e, floor, first["t1"], -1, lo)
    b, sil_b, hit_b = walk(e, floor, last["t0"], +1, hi)
    a_pad = max(lo, a - min(head, max(0.0, sil_a - 0.02)))
    b_pad = min(hi, b + min(tail, max(0.0, sil_b - 0.02)))
    out.update({"start": round(a_pad, 3), "end": round(b_pad, 3),
                "first_word": first["w"], "last_word": last["w"],
                "room_tone_db": round(floor, 1)})
    notes = []
    if hit_a:
        notes.append("start: no silence before the first word (joined speech) — cut lands on the previous word's end")
    if hit_b:
        notes.append("end: no silence after the last word — cut lands on the next word's start")
    if last["t1"] - last["t0"] > 1.5:
        notes.append(f"last word '{last['w']}' is {last['t1'] - last['t0']:.1f}s long — stretched token, re-transcribe the window")
    if first["t1"] - first["t0"] > 1.5:
        notes.append(f"first word '{first['w']}' is {first['t1'] - first['t0']:.1f}s long — stretched token")
    if notes:
        out["check"] = "; ".join(notes)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spans")
    ap.add_argument("--head", type=float, default=0.20)
    ap.add_argument("--tail", type=float, default=0.32)
    a = ap.parse_args()
    spans = json.load(open(a.spans, encoding="utf-8"))
    out = [refine(s, a.head, a.tail) for s in spans]
    total = sum(s["end"] - s["start"] for s in out)
    flagged = sum(1 for s in out if "check" in s)
    print(f"{len(out)} spans, {total:.1f}s total, {flagged} to check", file=sys.stderr)
    for s in out:
        if "check" in s:
            print(f"  {s.get('id', '?')}: {s['check']}", file=sys.stderr)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

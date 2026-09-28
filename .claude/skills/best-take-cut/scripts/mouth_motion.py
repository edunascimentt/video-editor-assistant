#!/usr/bin/env python3
"""Who is speaking in each transcript segment — measured from the speaker's mouth.

When someone off camera reads each line first and the speaker repeats it (a
prompter, a producer feeding lines), audio LEVEL does not separate the two:
measured, both voices spanned the same 51–72 dB, and the level differences
between cameras grouped loud/quiet, not person. The mouth does.

    mouth_motion.py box VIDEO --crop W:H:X:Y --at 30,300,700 -o DIR
        draw the crop box on a few frames spread over the take — LOOK at them;
        the head moves, so check early, middle and late

    mouth_motion.py measure VIDEO --crop W:H:X:Y --segments segs.json [--split X] > labeled.json
        segs.json: [{"start": s, "end": s, "text": "..."}]  (WhisperX segments are fine)
        adds "mv" (median frame-to-frame motion inside the box) and "speaker"
        ("on" = the person in frame is talking, "off" = someone else)

Motion = mean absolute difference between consecutive 56x36 grey frames of the
mouth region at 10 fps. On real takes it came out bimodal and clean: the
on-camera speaker 1.8–6.5, the off-camera voice 0.2–1.2. --split defaults to
the widest gap between sorted segment medians (printed); check that it falls in
a real gap before trusting the labels.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import numpy as np

W, H, FPS = 56, 36, 10


def frames(video: str, crop: str) -> np.ndarray:
    vf = f"crop={crop},fps={FPS},scale={W}:{H},format=gray"
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vf", vf,
                          "-f", "rawvideo", "-"], capture_output=True)
    if out.returncode:
        sys.exit(out.stderr.decode()[-400:])
    buf = np.frombuffer(out.stdout, dtype=np.uint8)
    return buf[: len(buf) // (W * H) * W * H].reshape(-1, H, W).astype(np.float32)


def motion(fr: np.ndarray) -> np.ndarray:
    """mv[i] = motion between frame i and i+1, at time (i+1)/FPS."""
    if len(fr) < 2:
        return np.zeros(0)
    return np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))


def widest_gap(values: list[float]) -> float:
    v = sorted(values)
    if len(v) < 2:
        return v[0] if v else 1.5
    gaps = [(b - a, (a + b) / 2) for a, b in zip(v, v[1:])]
    return max(gaps)[1]


def cmd_box(a):
    os.makedirs(a.out, exist_ok=True)
    w, h, x, y = a.crop.split(":")
    for t in a.at.split(","):
        dst = os.path.join(a.out, f"box_{float(t):08.1f}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", t, "-i", a.video,
                        "-vf", f"drawbox=x={x}:y={y}:w={w}:h={h}:color=red:t=4,scale=960:-2",
                        "-frames:v", "1", dst], check=True)
        print(dst)


def cmd_measure(a):
    segs = json.load(open(a.segments, encoding="utf-8"))
    mv = motion(frames(a.video, a.crop))
    t = (np.arange(len(mv)) + 1) / FPS
    for s in segs:
        m = mv[(t >= s["start"]) & (t < s["end"])]
        s["mv"] = round(float(np.median(m)), 3) if len(m) else None
    vals = [s["mv"] for s in segs if s["mv"] is not None]
    split = a.split if a.split is not None else widest_gap(vals)
    for s in segs:
        s["speaker"] = None if s["mv"] is None else ("on" if s["mv"] >= split else "off")
    on = sorted(s["mv"] for s in segs if s["speaker"] == "on")
    off = sorted(s["mv"] for s in segs if s["speaker"] == "off")
    print(f"split {split:.2f}  on-camera {len(on)} segs "
          f"[{on[0] if on else '-'}..{on[-1] if on else '-'}]  off-camera {len(off)} segs "
          f"[{off[0] if off else '-'}..{off[-1] if off else '-'}]", file=sys.stderr)
    hist = np.histogram(vals, bins=12)
    for n, lo in zip(hist[0], hist[1]):
        print(f"  {lo:6.2f} {'#' * int(n)}", file=sys.stderr)
    json.dump(segs, sys.stdout, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("box")
    s.add_argument("video")
    s.add_argument("--crop", required=True, help="W:H:X:Y in source pixels")
    s.add_argument("--at", required=True, help="comma-separated seconds")
    s.add_argument("-o", "--out", required=True)
    s.set_defaults(fn=cmd_box)
    s = sub.add_parser("measure")
    s.add_argument("video")
    s.add_argument("--crop", required=True)
    s.add_argument("--segments", required=True)
    s.add_argument("--split", type=float)
    s.set_defaults(fn=cmd_measure)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

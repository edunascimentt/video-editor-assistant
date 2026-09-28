#!/usr/bin/env python3
"""Pick and prepare a music bed by measurement instead of by title.

Subcommands
  scan DIR [--allow PAT ...] [--top N]   rank licensed tracks by how well they sit under speech
  arc FILE [--win 5]                      RMS per window: where the track turns
  level FILE [--from S --dur D]           integrated loudness (LUFS) of any file / span
  align --turn S --key S                  source offset that lands the turn on the key line
  render FILE -o OUT --from S --dur D (--gain DB | --target-lufs L)
         [--fade-in S] [--fade-out S] [--env "t:dB,t:dB,..."]
                                          bake offset, gain, fades and an envelope into a WAV

Needs ffmpeg on PATH and numpy. Resolve's API has no clip volume, so the level
you hear in the timeline is the level rendered into the file.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import math
import os
import re
import subprocess
import sys

import numpy as np

SR = 16000
DEFAULT_ALLOW = ["ES_*", "MA_*", "*_source_*"]
AUDIO_EXT = {".wav", ".mp3", ".aif", ".aiff", ".m4a", ".flac", ".ogg"}


def decode(path: str, start: float | None = None, dur: float | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-i", path]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]          # after -i: exact seek
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def db(x: float) -> float:
    return 20 * math.log10(max(x, 1e-9))


def lufs(path: str, start: float | None = None, dur: float | None = None) -> float | None:
    # trim inside the graph — an output -ss would let ebur128 hear the whole head
    trim = f"atrim=start={start or 0:.3f}" + (f":duration={dur:.3f}" if dur else "")
    cmd = ["ffmpeg", "-nostats", "-i", path, "-af", f"{trim},ebur128", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    return float(m[-1]) if m else None


def arc(x: np.ndarray, win: float = 5.0) -> list[float]:
    n = int(win * SR)
    return [db(float(np.sqrt(np.mean(x[i:i + n] ** 2)))) for i in range(0, len(x) - n + 1, n)]


def voice_band_db(x: np.ndarray) -> float:
    """Energy in 300–3000 Hz relative to the full band. Lower = sits under speech better."""
    n = 4096
    frames = len(x) // n
    if frames == 0:
        return float("nan")
    spec = np.abs(np.fft.rfft(x[: frames * n].reshape(frames, n) * np.hanning(n), axis=1)) ** 2
    f = np.fft.rfftfreq(n, 1 / SR)
    band = spec[:, (f >= 300) & (f <= 3000)].sum()
    return 10 * math.log10(max(band, 1e-12) / max(spec.sum(), 1e-12))


def onsets_per_min(x: np.ndarray) -> float:
    """Spectral-flux peaks per minute — how busy the rhythm is under the voice."""
    n, hop = 1024, 512
    frames = 1 + (len(x) - n) // hop
    if frames < 3:
        return 0.0
    idx = np.arange(n)[None, :] + hop * np.arange(frames)[:, None]
    mag = np.abs(np.fft.rfft(x[idx] * np.hanning(n), axis=1))
    flux = np.maximum(np.diff(mag, axis=0), 0).sum(axis=1)
    thr = np.median(flux) + 1.5 * flux.std()
    peaks = (flux[1:-1] > thr) & (flux[1:-1] >= flux[:-2]) & (flux[1:-1] >= flux[2:])
    return float(peaks.sum()) / (len(x) / SR / 60)


def allowed(name: str, pats: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in pats)


def cmd_scan(a):
    files = sorted(f for f in os.listdir(a.dir)
                   if os.path.splitext(f)[1].lower() in AUDIO_EXT)
    ok = [f for f in files if allowed(f, a.allow)]
    print(f"{len(files)} audio files, {len(ok)} pass the licence filter {a.allow}", file=sys.stderr)
    rows = []
    for f in ok:
        p = os.path.join(a.dir, f)
        try:
            x = decode(p, dur=a.max_seconds)
        except subprocess.CalledProcessError:
            print(f"  skip (decode failed): {f}", file=sys.stderr)
            continue
        ar = arc(x)
        rows.append({"file": f, "seconds": round(len(x) / SR, 1),
                     "voice_band_db": round(voice_band_db(x), 1),
                     "onsets_per_min": round(onsets_per_min(x), 0),
                     "arc_min_db": round(min(ar), 1) if ar else None,
                     "arc_max_db": round(max(ar), 1) if ar else None})
    rows.sort(key=lambda r: r["voice_band_db"])
    if a.json:
        print(json.dumps(rows[: a.top], ensure_ascii=False, indent=1))
        return
    print(f"{'voice dB':>8} {'onset/m':>7} {'arc':>13} {'len':>6}  file")
    for r in rows[: a.top]:
        print(f"{r['voice_band_db']:>8} {r['onsets_per_min']:>7.0f} "
              f"{r['arc_min_db']:>6}..{r['arc_max_db']:<6} {r['seconds']:>6}  {r['file']}")


def cmd_arc(a):
    x = decode(a.file)
    for i, v in enumerate(arc(x, a.win)):
        bar = "#" * max(0, int((v + 60) / 2))
        print(f"{i * a.win:7.1f}s {v:7.1f} dB {bar}")


def cmd_level(a):
    print(lufs(a.file, a.start, a.dur))


def cmd_align(a):
    off = a.turn - a.key
    if off < 0:
        print(f"the turn ({a.turn}s) comes before the key line ({a.key}s): start the bed "
              f"{-off:.2f}s into the timeline instead, from source 0")
    else:
        print(f"enter the track at source {off:.2f}s so {a.turn}s lands on record {a.key}s")


def env_expr(points: list[tuple[float, float]]) -> str:
    """Piecewise-linear gain in dB over time -> an ffmpeg volume expression (linear)."""
    pts = sorted(points)
    parts = []
    for (t0, g0), (t1, g1) in zip(pts, pts[1:]):
        seg = f"(({g0})+(({g1})-({g0}))*(t-({t0}))/(({t1})-({t0})))"
        parts.append((t0, t1, seg))
    expr = f"({pts[-1][1]})"
    for t0, t1, seg in reversed(parts):
        expr = f"if(lt(t,{t1}),{seg},{expr})"
    expr = f"if(lt(t,{pts[0][0]}),({pts[0][1]}),{expr})"
    return f"pow(10,({expr})/20)"


def cmd_render(a):
    gain = a.gain
    if a.target_lufs is not None:
        now = lufs(a.file, a.start, a.dur)
        if now is None:
            sys.exit("could not measure the source loudness")
        gain = a.target_lufs - now
        print(f"source {now:.1f} LUFS -> gain {gain:+.1f} dB", file=sys.stderr)
    # Trim INSIDE the graph: an output -ss drops frames after the filters ran, so
    # fades and the envelope would be timed from the source start, not the cut.
    trim = f"atrim=start={a.start:.3f}" + (f":duration={a.dur:.3f}" if a.dur else "")
    filters = [trim, "asetpts=PTS-STARTPTS", f"volume={gain:.2f}dB"]
    if a.env:
        pts = [tuple(float(v) for v in p.split(":")) for p in a.env.split(",")]
        filters.append(f"volume='{env_expr(pts)}':eval=frame")
    if a.fade_in:
        filters.append(f"afade=t=in:st=0:d={a.fade_in}")
    if a.fade_out and a.dur:
        filters.append(f"afade=t=out:st={a.dur - a.fade_out:.3f}:d={a.fade_out}")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", a.file, "-af", ",".join(filters), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", a.out]
    subprocess.run(cmd, check=True)
    print(f"wrote {a.out}  ({lufs(a.out):.1f} LUFS integrated)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan")
    s.add_argument("dir")
    s.add_argument("--allow", nargs="+", default=DEFAULT_ALLOW,
                   help="filename globs that mark licensed tracks (default: %(default)s)")
    s.add_argument("--top", type=int, default=15)
    s.add_argument("--max-seconds", type=float, default=180, help="analyse only the first N s")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("arc")
    s.add_argument("file")
    s.add_argument("--win", type=float, default=5.0)
    s.set_defaults(fn=cmd_arc)

    s = sub.add_parser("level")
    s.add_argument("file")
    s.add_argument("--from", dest="start", type=float)
    s.add_argument("--dur", type=float)
    s.set_defaults(fn=cmd_level)

    s = sub.add_parser("align")
    s.add_argument("--turn", type=float, required=True, help="source second where the track turns")
    s.add_argument("--key", type=float, required=True, help="record second of the key line")
    s.set_defaults(fn=cmd_align)

    s = sub.add_parser("render")
    s.add_argument("file")
    s.add_argument("-o", "--out", required=True)
    s.add_argument("--from", dest="start", type=float, default=0.0)
    s.add_argument("--dur", type=float)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--gain", type=float, help="dB")
    g.add_argument("--target-lufs", type=float)
    s.add_argument("--fade-in", type=float, default=0.0)
    s.add_argument("--fade-out", type=float, default=0.0)
    s.add_argument("--env", help='extra gain envelope, "t:dB,t:dB" in output seconds')
    s.set_defaults(fn=cmd_render)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

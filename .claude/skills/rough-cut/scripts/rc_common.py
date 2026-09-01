"""Shared helpers for the rough-cut pipeline.

Everything here is deliberately dependency-light: numpy, ffmpeg, and (only in
the scripts that talk to Resolve) DaVinciResolveScript. No torch, no librosa.

Coordinate systems used across the pipeline
-------------------------------------------
file seconds    seconds from the head of a media FILE. WhisperX reports these,
                and Resolve's source_start/source_end are the frame-counted
                version of the same thing.
record seconds  seconds from the head of the TIMELINE. The canonical coordinate
                for every cut decision, because a decision may span two clips.
source frames   file seconds x that MEDIA's own fps. What AppendToTimeline eats.
                endFrame is EXCLUSIVE (duration = end - start) -- verified, see
                reference/resolve-notes.md.

Nothing in the pipeline reasons in timeline frames except the final duration
check, and nothing assumes the media fps equals the timeline fps.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

# ── Resolve bootstrap ────────────────────────────────────────────────────────

RESOLVE_MCP = Path(os.environ.get(
    "ROUGHCUT_RESOLVE_MCP", str(Path.home() / "Repositories/davinci-resolve-mcp")))
_SCRIPT_API = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"


def connect_resolve():
    """Return the Resolve app object, or raise with a diagnosable message."""
    modules = os.environ.get("RESOLVE_SCRIPT_API", _SCRIPT_API) + "/Modules"
    if modules not in sys.path:
        sys.path.append(modules)
    try:
        import DaVinciResolveScript as dvr  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment problem
        raise SystemExit(
            f"DaVinciResolveScript not importable ({exc}).\n"
            f"Run this script with {RESOLVE_MCP}/venv/bin/python and the "
            "RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB / PYTHONPATH env from .mcp.json."
        ) from exc
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise SystemExit(
            "scriptapp('Resolve') returned None. Resolve is not running, or "
            "Preferences > General > External scripting using is not 'Local'."
        )
    return resolve


def current_project(resolve):
    proj = resolve.GetProjectManager().GetCurrentProject()
    if proj is None:
        raise SystemExit("No project open in Resolve.")
    return proj


def find_timeline(proj, name: Optional[str]):
    if not name:
        tl = proj.GetCurrentTimeline()
        if tl is None:
            raise SystemExit("No current timeline. Open one, or pass --timeline NAME.")
        return tl
    for i in range(1, int(proj.GetTimelineCount() or 0) + 1):
        tl = proj.GetTimelineByIndex(i)
        if tl and tl.GetName() == name:
            return tl
    raise SystemExit(f"Timeline not found: {name!r}")


# ── work directory ───────────────────────────────────────────────────────────

def slug(text: str) -> str:
    s = re.sub(r"[^\w.-]+", "-", str(text).strip()).strip("-")
    return s[:80] or "untitled"


def workdir(project: str, timeline: str, root: Optional[str] = None) -> Path:
    base = Path(root or os.environ.get(
        "ROUGHCUT_WORK", str(Path.home() / ".cache/rough-cut")))
    d = base / slug(project) / slug(timeline)
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)
    return path


def media_key(path: str) -> str:
    """Stable per-file key that changes when the file changes."""
    try:
        st = os.stat(path)
        stamp = f"{path}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        stamp = path
    return f"{slug(Path(path).stem)}-{hashlib.sha1(stamp.encode()).hexdigest()[:10]}"


# ── audio envelopes ──────────────────────────────────────────────────────────

ENV_SR = 16000
ENV_HOP_MS = 10.0
ENV_WIN_MS = 30.0
#: Sibilants live above this. Their broadband RMS is tiny, which is exactly why
#: a level gate cuts them off; in this band they are loud and obvious.
SIBILANT_HZ = 4000


def _decode_mono(path: str, af: Optional[str] = None, sr: int = ENV_SR) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-map", "0:a:0",
           "-ac", "1", "-ar", str(sr)]
    if af:
        cmd += ["-af", af]
    cmd += ["-f", "f32le", "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on {path}:\n{proc.stderr.decode(errors='replace')[:2000]}")
    return np.frombuffer(proc.stdout, dtype="<f4").astype(np.float32)


def _rms_db(x: np.ndarray, sr: int, hop_ms: float, win_ms: float) -> np.ndarray:
    hop = max(1, int(round(sr * hop_ms / 1000.0)))
    win = max(hop, int(round(sr * win_ms / 1000.0)))
    if x.size < win:
        x = np.pad(x, (0, win - x.size))
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop]
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-20)
    return (20.0 * np.log10(rms + 1e-12)).astype(np.float32)


def noise_floor(db: np.ndarray, hop_ms: float = ENV_HOP_MS,
                window_ms: float = 300.0, pct: float = 2.0) -> float:
    """Room tone, estimated from the quietest sustained stretch.

    A plain percentile over frames is biased upward exactly where it matters: on
    a lecture the speaker talks ~85% of the time, so even the 10th percentile is
    speech, the gate ends up far above true silence, and the boundary walk stops
    while a fricative is still going. Measured on a real 11-minute lesson, that
    bias left 16 of 31 pause splices cutting into an /s/.

    Averaging over 300 ms first collapses the gaps *between* phonemes -- which
    are quiet but are not silence -- so only a genuine pause can win. The low
    percentile of those window means, rather than their strict minimum, keeps one
    freak dropout from setting the floor for the whole file.
    """
    win = max(1, int(round(window_ms / hop_ms)))
    if db.size <= win:
        return float(np.percentile(db, pct))
    means = np.convolve(db.astype(np.float64), np.ones(win) / win, mode="valid")
    return float(np.percentile(means, pct))


class Envelope:
    """Broadband + sibilant-band loudness curves for one media file.

    Times are file seconds. `floor_*` are robust noise floors (10th percentile),
    so a hissy room and a treated booth get different, self-calibrated gates
    instead of one hard-coded dB number that is wrong on both.
    """

    def __init__(self, path: str, hop_ms: float = ENV_HOP_MS):
        self.path = path
        self.hop = hop_ms / 1000.0
        bb = _decode_mono(path)
        hi = _decode_mono(path, af=f"highpass=f={SIBILANT_HZ}")
        n = min(bb.size, hi.size)
        self.bb = _rms_db(bb[:n], ENV_SR, hop_ms, ENV_WIN_MS)
        self.hi = _rms_db(hi[:n], ENV_SR, hop_ms, ENV_WIN_MS)
        m = min(self.bb.size, self.hi.size)
        self.bb, self.hi = self.bb[:m], self.hi[:m]
        self.duration = n / float(ENV_SR)
        self.floor_bb = noise_floor(self.bb)
        self.floor_hi = noise_floor(self.hi)
        self.peak_bb = float(np.percentile(self.bb, 98))

    # -- serialisation so the expensive decode happens once per file ---------

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path, bb=self.bb, hi=self.hi,
            meta=np.array([self.hop, self.duration, self.floor_bb,
                           self.floor_hi, self.peak_bb], dtype=np.float64))
        return path

    @classmethod
    def load(cls, path: Path, media_path: str) -> "Envelope":
        z = np.load(path)
        self = cls.__new__(cls)
        self.path = media_path
        self.bb, self.hi = z["bb"], z["hi"]
        (self.hop, self.duration, self.floor_bb,
         self.floor_hi, self.peak_bb) = (float(v) for v in z["meta"])
        return self

    @classmethod
    def cached(cls, media_path: str, cache_dir: Path) -> "Envelope":
        cache = cache_dir / f"{media_key(media_path)}.npz"
        if cache.exists():
            try:
                return cls.load(cache, media_path)
            except Exception:
                pass
        env = cls(media_path)
        env.save(cache)
        return env

    def calibrate(self, windows) -> bool:
        """Re-estimate room tone from the pauses the transcript points at.

        The global estimator answers "what is the quietest sustained moment in
        this file", which can be one freak silence at the head and sit far below
        anything that happens during speech. What the boundary walk actually
        needs is "what does a PAUSE in this recording look like" -- and the
        transcript already says where the pauses are.

        Measured on a real lesson the two differed by 11 dB: global floor
        -69.1 dB, real pause interior -58.5 dB. With the gate set from the
        global figure, 72% of pause interior read as *sound*, so the walk never
        found an end, ran to its distance limit, and swallowed the pause. That
        is why only 15% of the pause time was recoverable.

        `windows` are (start, end) file-second pairs covering pause interiors.
        Returns False and leaves the global estimate alone when there is not
        enough pause in the file to measure.
        """
        import numpy as _np
        idx = []
        for a, b in windows:
            i, j = self.idx(a), self.idx(b)
            if j > i:
                idx.append(_np.arange(i, j))
        if not idx:
            return False
        sel = _np.concatenate(idx)
        if sel.size < 50:          # under half a second of pause: not measurable
            return False
        self.floor_bb = float(_np.median(self.bb[sel]))
        self.floor_hi = float(_np.median(self.hi[sel]))
        self.calibrated_on = int(sel.size)
        return True

    # -- queries -------------------------------------------------------------

    def idx(self, t: float) -> int:
        return int(np.clip(round(t / self.hop), 0, self.bb.size - 1))

    def loud(self, t: float, bb_margin: float, hi_margin: float) -> bool:
        i = self.idx(t)
        return (self.bb[i] > self.floor_bb + bb_margin
                or self.hi[i] > self.floor_hi + hi_margin)

    def quietest(self, t0: float, t1: float) -> float:
        """File time of the least energetic hop in [t0, t1] -- where a splice
        is least audible. Ties resolve to the earliest index."""
        if t1 <= t0:
            return t0
        a, b = self.idx(t0), self.idx(t1)
        if b <= a:
            return t0
        seg = self.bb[a:b + 1].astype(np.float64) + 0.5 * self.hi[a:b + 1]
        return (a + int(np.argmin(seg))) * self.hop


# ── phonetic hints (pt-BR) ───────────────────────────────────────────────────

_STRIP = re.compile(r"^[^\w'À-ſ-]+|[^\w'À-ſ-]+$", re.UNICODE)


def norm(word: Any) -> str:
    return _STRIP.sub("", str(word or "").strip().lower())


#: Word endings whose last phoneme is a voiceless fricative or sibilant. These
#: are the ones an aligner truncates: nearly no energy below 4 kHz, so a CTC
#: alignment "ends" the word while the hiss is still going.
_SIBILANT_TAIL = re.compile(r"(ss|sh|ch|s|z|x|c|ç|f|j|r)$", re.UNICODE)
#: Onsets that begin with turbulence or a stop burst -- the head an aligner
#: clips off the front.
_HARD_ONSET = re.compile(r"^(ch|sh|ps|s|z|x|f|j|p|t|k|c|qu)", re.UNICODE)


def ends_sibilant(word: str) -> bool:
    return bool(_SIBILANT_TAIL.search(norm(word)))


def starts_hard(word: str) -> bool:
    return bool(_HARD_ONSET.match(norm(word)))


# ── interval algebra ─────────────────────────────────────────────────────────

def merge(spans: Iterable[Tuple[float, float]], gap: float = 0.0) -> List[Tuple[float, float]]:
    out: List[List[float]] = []
    for a, b in sorted((float(a), float(b)) for a, b in spans if b > a):
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def complement(spans: Sequence[Tuple[float, float]], lo: float, hi: float) -> List[Tuple[float, float]]:
    keep, cursor = [], lo
    for a, b in merge(spans):
        a, b = max(a, lo), min(b, hi)
        if b <= a:
            continue
        if a > cursor:
            keep.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < hi:
        keep.append((cursor, hi))
    return [(a, b) for a, b in keep if b > a]


def total(spans: Iterable[Tuple[float, float]]) -> float:
    return float(sum(b - a for a, b in spans))


def hms(seconds: float) -> str:
    s = max(0.0, float(seconds))
    return f"{int(s // 3600):02d}:{int(s // 60) % 60:02d}:{s % 60:06.3f}"

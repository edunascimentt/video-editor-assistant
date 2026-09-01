#!/usr/bin/env python
"""Check the cut before anyone watches it: did the meaning survive, and did any
word get clipped?

Three independent checks, because they fail in different ways:

  1. STRUCTURAL (no audio, instant) — does any kept word straddle a splice? A
     word that crosses a cut is a clipped word by construction. A clean plan has
     zero of these; any hit is a bug in the plan, not a matter of taste.
  2. ACOUSTIC — reconstructs exactly what the timeline will play (same ranges,
     same media, same order) and measures each splice. Energy still high in the
     4 kHz+ band on the last frames before a cut means a fricative was severed:
     the "S" failure, which sounds like a lisp and is invisible to a broadband
     meter. The same measure just after a cut catches a clipped word onset.
  3. SEMANTIC — re-transcribes the reconstruction with WhisperX and diffs it
     against the words the plan intended to keep. Anything the recogniser now
     hears differently is a place where the cut changed what was said.

The reconstruction is arithmetic on the source media, not a Premiere render, so
it is exact and takes seconds. Render the imported sequence too if you want to
prove Premiere agrees.

usage: pr_verify.py --work-dir DIR [--skip-transcribe]
"""

from __future__ import annotations

import argparse
import difflib
import os
import sys
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pr_common as rc  # noqa: E402

SR = rc.ENV_SR


def band_db(x: np.ndarray, sr: int, lo_hz: Optional[int] = None) -> float:
    """RMS in dBFS of a short window, optionally only above `lo_hz`.

    Parseval-exact and window-compensated, so the full-band answer equals plain
    time-domain RMS to within rounding. That matters: the planner's room-tone
    figure is measured in that scale and handed to this check through the plan,
    and a check that measured on its own scale would flag or excuse splices for
    no reason but a unit mismatch.
    """
    if x.size < 32:
        return -120.0
    w = np.hanning(x.size)
    spec = np.abs(np.fft.rfft(x.astype(np.float64) * w)) ** 2
    if lo_hz:
        spec = spec[np.fft.rfftfreq(x.size, 1.0 / sr) >= lo_hz]
        if spec.size == 0:
            return -120.0
        power = 2.0 * spec.sum()          # one-sided bins carry half the energy
    else:
        power = spec[0] + 2.0 * spec[1:-1].sum() + spec[-1]
    ms = power / (x.size ** 2 * np.mean(w ** 2))
    return float(10.0 * np.log10(ms + 1e-20))


def reconstruct(timeline: Dict[str, Any], plan: Dict[str, Any], out: Path
                ) -> Tuple[np.ndarray, List[float]]:
    """The exact audio the cut timeline will play, as one mono array."""
    tl_fps = float(timeline["timeline_fps"])
    audio = [i for i in timeline["items"]
             if i["track_type"] == "audio" and i.get("file_path")
             and not i.get("retimed") and i.get("source_start_seconds") is not None]
    if not audio:
        audio = [i for i in timeline["items"]
                 if i["track_type"] == "video" and i.get("file_path")
                 and not i.get("retimed") and i.get("source_start_seconds") is not None]
    if not audio:
        raise SystemExit("No audible, cutable item to reconstruct from.")

    decoded: Dict[str, np.ndarray] = {}
    chunks: List[np.ndarray] = []
    splices: List[float] = []
    cursor = 0.0
    for a, b in plan["keep"]:
        piece = None
        for item in audio:
            rec0, rec1 = item["start"] / tl_fps, item["end"] / tl_fps
            lo, hi = max(float(a), rec0), min(float(b), rec1)
            if hi <= lo:
                continue
            path = item["file_path"]
            if path not in decoded:
                decoded[path] = rc._decode_mono(path)
            src0 = float(item["source_start_seconds"])
            f0 = src0 + (lo - rec0)
            i0 = int(round(f0 * SR))
            i1 = i0 + int(round((hi - lo) * SR))
            piece = decoded[path][max(0, i0):max(0, i1)]
            break
        if piece is None:
            piece = np.zeros(int(round((float(b) - float(a)) * SR)), dtype=np.float32)
        chunks.append(piece)
        cursor += piece.size / SR
        splices.append(cursor)
    signal = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)

    out.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(signal, -1.0, 1.0)
    with wave.open(str(out), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes((pcm * 32767.0).astype("<i2").tobytes())
    return signal, splices[:-1]


def check_crossings(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    active = rc.merge([(r["start"], r["end"]) for r in plan["removals"] if r["state"] == "on"])
    hits = []
    for tok in plan["tokens"]:
        t0, t1 = tok["t0"], tok["t1"]
        for a, b in active:
            if b <= t0 or a >= t1:
                continue
            overlap = min(b, t1) - max(a, t0)
            if overlap >= (t1 - t0) - 1e-6:
                break   # fully removed on purpose
            if overlap > 0.02:
                hits.append({"word": tok["w"], "t0": round(t0, 3), "t1": round(t1, 3),
                             "overlap_ms": round(overlap * 1000, 1),
                             "removal": [round(a, 3), round(b, 3)]})
            break
    return hits


def check_splices(signal: np.ndarray, splices: List[float],
                  plan: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    win = int(0.030 * SR)
    # Prefer the planner's own room tone, measured across every pause the
    # transcript pointed at. Reconstruction copies samples without gain, so the
    # dBFS figure carries over exactly. Only fall back to estimating it here --
    # from audio that has just had most of its silence removed, which biases the
    # estimate upward -- when the plan predates this field.
    tone = (plan or {}).get("room_tone") or {}
    if tone.get("bb") is not None:
        floor_bb, floor_hi = float(tone["bb"]), float(tone["hi"])
    else:
        step = range(0, max(1, signal.size - win), win)
        floor_bb = rc.noise_floor(
            np.array([band_db(signal[i:i + win], SR) for i in step], dtype=np.float64),
            hop_ms=30.0)
        floor_hi = rc.noise_floor(
            np.array([band_db(signal[i:i + win], SR, rc.SIBILANT_HZ) for i in step],
                     dtype=np.float64), hop_ms=30.0)
    findings = []
    half = win // 2
    for index, t in enumerate(splices):
        i = int(round(t * SR))
        before, after = signal[max(0, i - win):i], signal[i:i + win]
        pre_hi, post_hi = band_db(before, SR, rc.SIBILANT_HZ), band_db(after, SR, rc.SIBILANT_HZ)
        pre_bb, post_bb = band_db(before, SR), band_db(after, SR)
        # Level alone does not separate a severed phoneme from a natural tail: a
        # decaying breath in a kept pause reads just as loud as a truncated /s/.
        # The SHAPE does. A tail falls across the last 30 ms; a sound that was
        # cut mid-flight is flat or still rising when the splice arrives. Same
        # logic mirrored after the cut, where a real word onset rises.
        pre_slope = band_db(before[half:], SR, rc.SIBILANT_HZ) - band_db(before[:half], SR, rc.SIBILANT_HZ)
        pre_slope_bb = band_db(before[half:], SR) - band_db(before[:half], SR)
        post_slope_bb = band_db(after[half:], SR) - band_db(after[:half], SR)
        issues = []
        if pre_hi > floor_hi + 9 and pre_slope > -3:
            issues.append(f"sibilant severed — +{pre_hi - floor_hi:.0f} dB @4k and not "
                          f"decaying ({pre_slope:+.0f} dB across the last 30 ms)")
        if pre_bb > floor_bb + 12 and pre_slope_bb > -3:
            issues.append(f"speech severed — +{pre_bb - floor_bb:.0f} dB and not decaying "
                          f"({pre_slope_bb:+.0f} dB)")
        if post_bb > floor_bb + 12 and post_slope_bb < 3:
            issues.append(f"word head clipped — +{post_bb - floor_bb:.0f} dB already at the "
                          f"cut and not rising ({post_slope_bb:+.0f} dB)")
        if issues:
            findings.append({"splice": index, "at_seconds": round(t, 3),
                             "issues": issues,
                             "levels": {"pre_bb": round(pre_bb, 1), "post_bb": round(post_bb, 1),
                                        "pre_hi": round(pre_hi, 1), "post_hi": round(post_hi, 1),
                                        "pre_slope_hi": round(pre_slope, 1),
                                        "post_slope_bb": round(post_slope_bb, 1),
                                        "floor_bb": round(floor_bb, 1),
                                        "floor_hi": round(floor_hi, 1)}})
    return findings


def splice_kind_map(plan: Dict[str, Any]) -> Dict[int, str]:
    """Which removal produced each splice — the flags mean different things."""
    by_start = {round(r["start"], 3): r["kind"] for r in plan["removals"]
                if r["state"] == "on"}
    keep = plan["keep"]
    return {n: by_start.get(round(keep[n][1], 3), "?") for n in range(len(keep) - 1)}


def splice_kinds(plan: Dict[str, Any], findings: List[Dict[str, Any]]
                 ) -> Dict[str, Tuple[int, int]]:
    kinds = splice_kind_map(plan)
    flagged = {f["splice"] for f in findings}
    out: Dict[str, List[int]] = {}
    for index, kind in kinds.items():
        row = out.setdefault(kind, [0, 0])
        row[1] += 1
        if index in flagged:
            row[0] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


def expected_words(plan: Dict[str, Any]) -> List[str]:
    active = rc.merge([(r["start"], r["end"]) for r in plan["removals"] if r["state"] == "on"])
    out = []
    for tok in plan["tokens"]:
        gone = any(a <= tok["t0"] + 1e-6 and tok["t1"] <= b + 1e-6 for a, b in active)
        if not gone:
            out.append(tok["n"])
    return out


def actual_words(wav: Path, work: Path, lang: str) -> List[str]:
    out_dir = work / "verify" / "words"
    doc = rc.read_json(rc.transcribe_json(str(wav), out_dir, lang, force=True))
    return [rc.norm(w.get("word")) for s in doc.get("segments") or []
            for w in s.get("words") or [] if rc.norm(w.get("word"))]


def diff_report(expected: List[str], actual: List[str], limit: int = 30) -> Tuple[List[str], Dict[str, int]]:
    sm = difflib.SequenceMatcher(a=expected, b=actual, autojunk=False)
    rows, counts = [], {"lost": 0, "gained": 0, "changed": 0}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        lost, gained = expected[i1:i2], actual[j1:j2]
        counts["lost"] += len(lost) if tag != "insert" else 0
        counts["gained"] += len(gained) if tag != "delete" else 0
        counts["changed"] += 1 if tag == "replace" else 0
        ctx = " ".join(expected[max(0, i1 - 4):i1])
        rows.append(f"| {tag} | …{ctx} | {' '.join(lost) or '—'} | {' '.join(gained) or '—'} |")
    counts["similarity"] = round(sm.ratio() * 100, 2)
    return rows[:limit], counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--lang", default=os.environ.get("TRANSCRIBEX_LANG", "pt"))
    ap.add_argument("--skip-transcribe", action="store_true",
                    help="structural + acoustic checks only (no second WhisperX pass)")
    args = ap.parse_args()

    work = Path(args.work_dir)
    timeline = rc.read_json(work / "timeline.json")
    plan = rc.read_json(work / "cutplan.json")

    crossings = check_crossings(plan)
    wav = work / "verify" / "cut.wav"
    signal, splices = reconstruct(timeline, plan, wav)
    splice_findings = check_splices(signal, splices, plan)

    rows: List[str] = []
    counts: Dict[str, Any] = {}
    if not args.skip_transcribe:
        exp = expected_words(plan)
        act = actual_words(wav, work, args.lang)
        rows, counts = diff_report(exp, act)
        (work / "verify" / "transcript_after.txt").write_text(" ".join(act), encoding="utf-8")
        (work / "verify" / "transcript_expected.txt").write_text(" ".join(exp), encoding="utf-8")

    st = plan["stats"]
    lines = [
        f"# Verification — {plan['timeline']}", "",
        f"{rc.hms(st['source_seconds'])} → {rc.hms(st['result_seconds'])}, "
        f"{len(splices)} splices, {st['words']} words in the source transcript", "",
        "## 1. Words straddling a splice (structural)", "",
    ]
    if crossings:
        lines += [f"**{len(crossings)} clipped word(s)** — every one of these is a defect in "
                  "the plan, not a taste call.", "",
                  "| word | at | overlap | removal |", "|---|---|---|---|"]
        lines += [f"| `{c['word']}` | {rc.hms(c['t0'])} | {c['overlap_ms']} ms | "
                  f"{c['removal'][0]}–{c['removal'][1]} |" for c in crossings[:40]]
    else:
        lines.append("None. No kept word overlaps a removed span.")

    lines += ["", "## 2. Splices measured on the reconstructed audio (acoustic)", ""]
    if splice_findings:
        by_kind = splice_kinds(plan, splice_findings)
        lines += [f"{len(splice_findings)} of {len(splices)} splices still have sound at an "
                  "edge. **Read this by kind — the two mean opposite things:**", "",
                  "| removal kind | flagged | total | what it means |", "|---|---:|---:|---|"]
        for kind, (bad, all_) in sorted(by_kind.items()):
            meaning = ("a pause should splice into silence — these are real defects, "
                       "raise --tail-ms-sibilant or --pause-residual-tail"
                       if kind == "silence" else
                       "word-to-word join: the removed word began right on the "
                       "previous word's tail. No setting fixes this — switch that "
                       "removal OFF if it sounds wrong.")
            lines.append(f"| {kind} | {bad} | {all_} | {meaning} |")
        lines += ["", "| # | at | removal | what |", "|---|---|---|---|"]
        kinds = splice_kind_map(plan)
        lines += [f"| {f['splice']} | {rc.hms(f['at_seconds'])} | "
                  f"{kinds.get(f['splice'], '?')} | {'; '.join(f['issues'])} |"
                  for f in splice_findings[:40]]
        if len(splice_findings) > 40:
            lines.append(f"| … | | | {len(splice_findings) - 40} more in verify.json |")
    else:
        lines.append(f"All {len(splices)} splices land in silence at both edges.")

    lines += ["", "## 3. What the recogniser hears now (semantic)", ""]
    if args.skip_transcribe:
        lines.append("Skipped (--skip-transcribe).")
    elif rows:
        lines += [f"Word-sequence similarity **{counts['similarity']}%** — "
                  f"{counts['lost']} lost, {counts['gained']} gained, {counts['changed']} changed.",
                  "", "| kind | context | planned | heard |", "|---|---|---|---|"] + rows
        lines += ["", "A handful of differences is normal — the recogniser is not "
                  "deterministic across a re-cut. Read them: a lost word next to a splice is "
                  "a real clip; a swapped homophone is noise."]
    else:
        lines.append(f"Word-sequence similarity **{counts.get('similarity', 100)}%** — "
                     "the cut audio says exactly what the plan intended to keep.")

    lines += ["", "## Still needs human eyes", "",
              "- Does the argument still follow across each cut? (Read `verify/transcript_after.txt`.)",
              "- Is the rhythm right, or did pause collapsing make it breathless?",
              "- Jump cuts: this pass does not add B-roll, punch-ins or transitions."]

    (work / "verify" / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    rc.write_json(work / "verify" / "verify.json", {
        "crossings": crossings, "splice_findings": splice_findings,
        "diff": counts, "splices": len(splices)})

    print(f"clipped words       : {len(crossings)}")
    print(f"splices with energy : {len(splice_findings)} / {len(splices)}")
    if counts:
        print(f"transcript similarity: {counts['similarity']}% "
              f"(lost {counts['lost']}, gained {counts['gained']})")
    print(f"\nwrote {work / 'verify' / 'report.md'} and {wav}")
    return 0 if not crossings else 1


if __name__ == "__main__":
    raise SystemExit(main())

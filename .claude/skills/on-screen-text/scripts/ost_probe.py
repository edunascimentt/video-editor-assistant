#!/usr/bin/env python
"""Probe a timeline for the on-screen-text pass.

Reads (never writes) the timeline, finds the two reusable VFX templates in the
media pool, locates a word-level transcript, and lays all of it out in a work
directory so the judging step has real numbers to work from.

    ost_probe.py                            # current timeline
    ost_probe.py --timeline "AULA 02"
    ost_probe.py --find "turnover,ROI,MIT"  # word-level frames for those terms

Writes:
    <work>/context.json     timeline facts + template ids + track layout
    <work>/transcript.md    every line with its timeline frame and timecode
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ost_common import (  # noqa: E402
    KINDS, connect_resolve, current_project, describe_clip, find_timeline,
    folder_by_path, norm_word, read_json, roughcut_dir, timecode,
    timeline_fps, workdir, write_json,
)

# The word template is the 24 fps `Text+` in Master/Assets -- the punch pair is
# built off it. The 60 fps copies in "00 - GERAL/Títulos e Fusion" render static
# on a 24 fps timeline; do not point this back at them.
WORD_TEMPLATE = ("Master/Assets", "Fusion Title")
EXPLAIN_TEMPLATE = ("Master/Assets/GCS", "Fusion Composition")
CLICK_TEMPLATE = ("Master/Assets/GCS", None, "Burnin Click")
CONTAINER_TEMPLATE = ("Master/00 - GERAL/Títulos e Fusion",
                      "Fusion Composition", None)


def pinned_path(project: str) -> Path:
    """Per-project record of which candidate is the real template."""
    from ost_common import workdir
    return workdir(project, "_templates").parent / "templates.json"


def discover_templates(media_pool, project, notes):
    """List the candidates; only choose when the choice is not a guess.

    Nothing readable from a media pool item says whether a Fusion Composition
    contains text nodes -- `GCS` holds the explanation card AND an unrelated
    two-MediaIn transition, and `Títulos e Fusion` holds four byte-identical
    copies of the Text+ plus a stock title. So: one candidate means it is
    settled, more than one means a human pins it once with --set-template and
    the answer is cached per project.
    """
    pins = {}
    pp = pinned_path(project)
    if pp.exists():
        try:
            pins = read_json(pp)
        except Exception:
            notes.append(f"{pp} is unreadable; ignoring pins")

    out = {}
    specs = [("word", *WORD_TEMPLATE, None),
             ("explain", *EXPLAIN_TEMPLATE, None),
             ("click", *CLICK_TEMPLATE)]
    for key, path, want_type, want_name in specs:
        folder = folder_by_path(media_pool, path)
        if folder is None:
            notes.append(f"template folder not found: {path}")
            out[key] = {"folder": path, "candidates": [], "chosen": None}
            continue
        cands = [describe_clip(c) for c in (folder.GetClipList() or [])]
        if want_type:
            cands = [c for c in cands if c["type"] == want_type]
        if want_name:
            cands = [c for c in cands
                     if str(c["name"] or "").startswith(want_name)]
        chosen = None
        if pins.get(key):
            chosen = next((c for c in cands if c["id"] == pins[key]), None)
            if chosen is None:
                notes.append(
                    f"pinned {key} template {pins[key]} is no longer in "
                    f"{path}; re-pin it")
        if chosen is None:
            if len(cands) == 1:
                chosen = cands[0]
            elif cands:
                notes.append(
                    f"{len(cands)} {key} candidates in {path} and no pin -- "
                    f"run: ost_probe.py --set-template {key}=<id>  (or put "
                    "clip_id on every item in the plan). Guessing is how you "
                    "end up placing the transition comp instead of the card.")
        out[key] = {"folder": path, "candidates": cands, "chosen": chosen,
                    "pinned": bool(pins.get(key))}
    return out


def load_transcript(project, timeline, notes):
    """Prefer the rough-cut verify transcript: it is already in timeline time."""
    rc = roughcut_dir(project, timeline)
    cut_json = rc / "verify/words/cut.json"
    if cut_json.exists():
        data = read_json(cut_json)
        return {
            "source": str(cut_json),
            "space": "timeline",
            "segments": data.get("segments", []),
            "words": data.get("word_segments", []),
        }
    notes.append(
        f"no verify transcript at {cut_json}. Run the rough-cut skill first, "
        "or transcribe the timeline's audio yourself -- this pass will not "
        "place a title from a timecode nobody measured.")
    return {"source": None, "space": None, "segments": [], "words": []}


def write_transcript_md(path, segments, fps):
    lines = ["| frame | tc | fala |", "|---|---|---|"]
    for seg in segments:
        start = seg.get("start")
        if start is None:
            continue
        f = int(round(float(start) * fps))
        text = str(seg.get("text", "")).strip().replace("|", "\\|")
        lines.append(f"| {f} | {timecode(f, fps)} | {text} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--timeline", help="name; default is the current timeline")
    ap.add_argument("--find", help="comma-separated terms to locate word-level")
    ap.add_argument("--work-root", help="override the work directory root")
    ap.add_argument("--set-template", action="append", default=[],
                    metavar="KIND=ID",
                    help="pin word=<clip id> / explain=<clip id> for this project")
    args = ap.parse_args()

    resolve = connect_resolve()
    proj = current_project(resolve)

    if args.set_template:
        pp = pinned_path(proj.GetName())
        pins = read_json(pp) if pp.exists() else {}
        for spec in args.set_template:
            kind, _, cid = spec.partition("=")
            if kind not in ("word", "explain", "click", "container") or not cid:
                raise SystemExit(f"bad --set-template {spec!r}; use word=<id>")
            pins[kind] = cid
        write_json(pp, pins)
        print(f"pinned {pins} -> {pp}")
    tl = find_timeline(proj, args.timeline)
    proj_name, tl_name = proj.GetName(), tl.GetName()
    fps = timeline_fps(tl)
    start, end = int(tl.GetStartFrame()), int(tl.GetEndFrame())
    notes = []

    tracks = {}
    for kind in ("video", "audio"):
        n = int(tl.GetTrackCount(kind) or 0)
        tracks[kind] = [
            {"index": i,
             "name": tl.GetTrackName(kind, i),
             "items": len(tl.GetItemListInTrack(kind, i) or [])}
            for i in range(1, n + 1)
        ]

    markers = tl.GetMarkers() or {}
    by_color = {}
    for frame, m in markers.items():
        by_color.setdefault(m.get("color", "?"), []).append(int(frame))

    templates = discover_templates(proj.GetMediaPool(), proj_name, notes)
    tr = load_transcript(proj_name, tl_name, notes)

    work = workdir(proj_name, tl_name, args.work_root)
    if tr["segments"]:
        write_transcript_md(work / "transcript.md", tr["segments"], fps)

    ctx = {
        "project": proj_name,
        "timeline": tl_name,
        "timeline_id": tl.GetUniqueId(),
        "timeline_fps": fps,
        "start_frame": start,
        "end_frame": end,
        "duration_frames": end - start,
        "tracks": tracks,
        "existing_markers": {c: sorted(v) for c, v in sorted(by_color.items())},
        "templates": templates,
        "transcript": {"source": tr["source"], "space": tr["space"],
                       "segments": len(tr["segments"]),
                       "words": len(tr["words"])},
        "warnings": notes,
    }
    write_json(work / "context.json", ctx)

    print(f"project    {proj_name}")
    print(f"timeline   {tl_name}  ({fps:g} fps, frames {start}-{end}, "
          f"{(end - start) / fps:.1f}s)")
    print("video      " + ", ".join(
        f"V{t['index']}={t['items']}" for t in tracks["video"]) or "none")
    if by_color:
        print("markers    " + ", ".join(
            f"{c}×{len(v)}" for c, v in sorted(by_color.items())))
    for key, info in templates.items():
        ch = info["chosen"]
        if ch:
            pin = " (pinned)" if info.get("pinned") else ""
            print(f"template   {key:8s} {ch['name']!r} id={ch['id']} "
                  f"{ch['frames']}f @{ch['fps']:g}fps{pin}")
        else:
            print(f"template   {key:8s} UNRESOLVED -- "
                  f"{len(info['candidates'])} candidate(s) in {info['folder']}")
            for c in info["candidates"]:
                print(f"             {c['id']}  {c['name']!r}  "
                      f"{c['frames']}f @{c['fps']:g}fps")
    print(f"transcript {tr['source'] or 'MISSING'} "
          f"({len(tr['segments'])} lines, {len(tr['words'])} timed words)")
    for w in notes:
        print(f"[WARN] {w}")

    if args.find:
        wanted = {norm_word(t) for t in args.find.split(",") if t.strip()}
        print("\nframe\ttc\tword")
        for w in tr["words"]:
            if norm_word(w.get("word", "")) in wanted and w.get("start") is not None:
                f = int(round(float(w["start"]) * fps))
                print(f"{f}\t{timecode(f, fps)}\t{w['word']}")

    print(f"\nwork {work}")
    print("legend " + ", ".join(f"{k}={c}" for k, (c, _) in KINDS.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

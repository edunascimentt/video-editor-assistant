#!/usr/bin/env python
"""Dump a Resolve timeline's structure to <workdir>/timeline.json.

Source-frame semantics in Resolve are a minefield (media-rate vs timeline-rate,
timecode-absolute vs file-relative second-readers, an end frame that flips
between inclusive and exclusive when the rates differ). None of that is
re-derived here: this imports the MCP server's own verified
`_timeline_item_summary`, so the pipeline inherits every fix upstream makes.
See reference/resolve-notes.md.

usage: rc_probe.py [--timeline NAME] [--work DIR]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rc_common as rc  # noqa: E402

sys.path.insert(0, str(rc.RESOLVE_MCP))
os.environ.setdefault(
    "RESOLVE_SCRIPT_API",
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting")
os.environ.setdefault(
    "PYTHONPATH", os.environ["RESOLVE_SCRIPT_API"] + "/Modules")

import src.server as S  # noqa: E402  (verified source-frame helpers)


def _prop(obj, getter: str, key: str):
    try:
        value = getattr(obj, getter)(key)
    except Exception:
        return None
    if isinstance(value, dict):
        return value.get(key)
    return value


def probe(timeline_name=None, work_root=None):
    resolve = rc.connect_resolve()
    proj = rc.current_project(resolve)
    tl = rc.find_timeline(proj, timeline_name)

    try:
        tl_fps = float(tl.GetSetting("timelineFrameRate"))
    except Exception:
        tl_fps = float(proj.GetSetting("timelineFrameRate") or 24.0)

    items, warnings = [], []
    mpi_cache: dict = {}
    for track_type in ("video", "audio"):
        count = int(tl.GetTrackCount(track_type) or 0)
        for ti in range(1, count + 1):
            for index, item in enumerate(tl.GetItemListInTrack(track_type, ti) or []):
                mpi = None
                try:
                    mpi = item.GetMediaPoolItem()
                except Exception:
                    pass
                props = None
                if mpi is not None:
                    key = id(mpi)
                    if key not in mpi_cache:
                        try:
                            mpi_cache[key] = mpi.GetClipProperty("") or {}
                        except Exception:
                            mpi_cache[key] = {}
                    props = mpi_cache[key]
                row = S._timeline_item_summary(
                    item, (track_type, ti), media_pool_item=mpi, clip_properties=props)
                if row is None:
                    continue
                row["item_index"] = index
                row["file_path"] = (props or {}).get("File Path")
                row["speed"] = _prop(item, "GetProperty", "Speed")
                # Retimed items break the linear file<->record mapping the whole
                # pipeline rests on. Flag loudly; rc_analyze refuses to cut them.
                try:
                    row["retimed"] = abs(float(row["speed"]) - 1.0) > 1e-6
                except (TypeError, ValueError):
                    row["retimed"] = False
                if row["retimed"]:
                    warnings.append(
                        f"{track_type} {ti} item {index} ({row['name']}) is retimed "
                        f"(speed={row['speed']}) — it will be carried through UNCUT.")
                if row.get("source_fps") in (None, 0):
                    warnings.append(
                        f"{track_type} {ti} item {index} ({row['name']}) has an unknown "
                        "source fps — it will be carried through UNCUT.")
                if not row["file_path"]:
                    warnings.append(
                        f"{track_type} {ti} item {index} ({row['name']}) has no file path "
                        "(title/generator/compound?) — it will be carried through UNCUT.")
                items.append(row)

    payload = {
        "project": proj.GetName(),
        "timeline": tl.GetName(),
        "timeline_fps": tl_fps,
        "timeline_start_frame": int(tl.GetStartFrame() or 0),
        "timeline_end_frame": int(tl.GetEndFrame() or 0),
        "track_counts": {t: int(tl.GetTrackCount(t) or 0) for t in ("video", "audio", "subtitle")},
        "items": items,
        "warnings": warnings,
    }
    out = rc.workdir(payload["project"], payload["timeline"], work_root)
    rc.write_json(out / "timeline.json", payload)
    return payload, out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeline", help="timeline name (default: the current one)")
    ap.add_argument("--work", help="work root (default: $ROUGHCUT_WORK or ~/.cache/rough-cut)")
    args = ap.parse_args()

    payload, out = probe(args.timeline, args.work)
    dur = (payload["timeline_end_frame"] - payload["timeline_start_frame"]) / payload["timeline_fps"]
    print(f"project : {payload['project']}")
    print(f"timeline: {payload['timeline']}  {payload['timeline_fps']:g} fps  "
          f"{rc.hms(dur)}  ({len(payload['items'])} items)")
    for t, n in payload["track_counts"].items():
        print(f"  {t:9s}: {n} track(s)")
    files = sorted({i["file_path"] for i in payload["items"] if i.get("file_path")})
    print(f"source files: {len(files)}")
    for f in files:
        print(f"  {f}")
    for w in payload["warnings"]:
        print(f"WARNING: {w}")
    print(f"\nwrote {out / 'timeline.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Build the cut timeline inside Resolve from a reviewed cut plan.

Resolve's scripting API has no razor. `edit_kernel_capabilities` says so in
writing: "does not expose a direct timeline split/razor primitive". A 300-cut
rough pass therefore cannot be made by deleting spans out of the timeline — a
range delete removes WHOLE items. The frame-accurate route is to re-assemble:
append the keep ranges, in order, at explicit record frames.

Both modes run on ONE mechanism — duplicate, clear, append — because
`DuplicateTimeline` is the only call that reproduces a timeline's settings
exactly. `CreateEmptyTimeline` inherits the PROJECT's settings instead, so a
24 fps timeline living in a 30 fps project came back at 30. Verified live: after
a duplicate all 157 timeline settings compare equal, and `DeleteClips` empties it
without disturbing the settings or the track layout.

  --mode variant   (default) duplicate the original, empty the copy, build in it.
                   The original is not touched at all.
  --mode in-place  duplicate the original as a backup, then empty and rebuild
                   THE ORIGINAL. Same timeline: same name, same unique id, same
                   settings, same place in the bin. This is destructive, which
                   is why the backup is made first and cannot be skipped
                   silently.

Timeline markers are carried through the cut rather than dropped: each one is
re-timed into the cut, and any that sat inside removed audio are reported.

Two Resolve behaviours this has to respect, both verified upstream:
  * clipInfo endFrame is EXCLUSIVE — duration is end - start, not +1.
  * when the media rate differs from the timeline rate, Resolve FLOORS the
    converted duration, so a range planned to fill a slot lands a frame short.
    Durations are therefore solved in timeline frames and back-solved per item.

usage: rc_apply.py --work-dir DIR [--mode variant|in-place] [--name NAME]
                   [--markers] [--dry-run]
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rc_common as rc  # noqa: E402

MARKER_COLOR = {
    "hesitation": "Yellow", "filler": "Sand", "false_start": "Red",
    "retake": "Purple", "manual": "Pink", "silence": "Blue",
}


def src_frames_for(dur_tl: int, tl_fps: float, item_fps: float) -> int:
    """Source frames that land on exactly `dur_tl` timeline frames.

    Resolve floors src * tl_fps / item_fps. Start from the ceiling so we never
    land short, then walk down to the smallest count that still fills the slot.
    """
    if abs(item_fps - tl_fps) < 1e-9:
        return dur_tl
    n = max(1, math.ceil(dur_tl * item_fps / tl_fps))
    while n > 1 and math.floor((n - 1) * tl_fps / item_fps) >= dur_tl:
        n -= 1
    return n


def build_clip_infos(timeline: Dict[str, Any], plan: Dict[str, Any]
                     ) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, int]]:
    tl_fps = float(timeline["timeline_fps"])
    keep = [(float(a), float(b)) for a, b in plan["keep"]]
    infos: List[Dict[str, Any]] = []
    warnings: List[str] = []
    tracks = {"video": 1, "audio": 1}

    cutable = []
    for item in timeline["items"]:
        why = None
        if item.get("retimed"):
            why = f"retimed (speed={item.get('speed')})"
        elif not item.get("file_path"):
            why = "no media file (title, generator, compound or Fusion clip)"
        elif not item.get("source_fps"):
            why = "unknown source fps"
        elif item.get("source_start_seconds") is None:
            why = "unreadable source span"
        if why:
            warnings.append(
                f"EXCLUDED from the cut timeline — {item['track_type']} "
                f"{item['track_index']} '{item['name']}': {why}. Re-place it by hand.")
            continue
        cutable.append(item)

    for item in cutable:
        fps = float(item["source_fps"])
        rec0 = item["start"] / tl_fps
        rec1 = item["end"] / tl_fps
        src0 = float(item["source_start_seconds"])
        media_type = 1 if item["track_type"] == "video" else 2
        tracks[item["track_type"]] = max(tracks[item["track_type"]], int(item["track_index"]))
        for a, b in keep:
            a, b = max(a, rec0), min(b, rec1)
            dur_tl = int(round((b - a) * tl_fps))
            if dur_tl <= 0:
                continue
            file_t = src0 + (a - rec0)
            start = int(round(file_t * fps))
            n = src_frames_for(dur_tl, tl_fps, fps)
            src_hi = int(item["source_end"]) if item.get("source_end") is not None else None
            if src_hi is not None and start + n > src_hi:
                n = max(1, src_hi - start)
            if start < 0:
                start = 0
            infos.append({
                "clip_id": item["media_pool_item_id"],
                "media_type": media_type,
                "track_index": int(item["track_index"]),
                "start_frame": start,
                "end_frame": start + n,   # EXCLUSIVE
                "record_seconds": round(a, 3),
                "duration_tl_frames": dur_tl,
                "quantization_ms": round(abs((b - a) - dur_tl / tl_fps) * 1000, 1),
            })
    infos.sort(key=lambda r: (r["media_type"], r["track_index"], r["record_seconds"]))
    # Explicit record frames rather than pack mode: the target timeline is an
    # emptied duplicate, not a fresh one, and packing "at the end of the track"
    # is only well-defined on a track nothing has ever been on.
    cursor: Dict[Tuple[int, int], int] = {}
    origin = int(timeline["timeline_start_frame"])
    for row in infos:
        key = (row["media_type"], row["track_index"])
        row["record_frame"] = cursor.get(key, origin)
        cursor[key] = row["record_frame"] + row["duration_tl_frames"]

    # A/V sync check: every track must contribute the same run of durations.
    by_track: Dict[Tuple[int, int], List[int]] = {}
    for row in infos:
        by_track.setdefault((row["media_type"], row["track_index"]), []).append(
            row["duration_tl_frames"])
    runs = list(by_track.values())
    if runs and any(r != runs[0] for r in runs[1:]):
        warnings.append(
            "A/V DRIFT RISK: tracks do not share an identical run of durations. "
            "Check detect_gaps_overlaps on the result before trusting sync.")
    return infos, warnings, tracks


def all_items(tl) -> List[Any]:
    return [item
            for track_type in ("video", "audio", "subtitle")
            for ti in range(1, int(tl.GetTrackCount(track_type) or 0) + 1)
            for item in (tl.GetItemListInTrack(track_type, ti) or [])]


def clear_timeline(tl) -> Tuple[bool, int]:
    """Empty a timeline without touching its settings or track layout."""
    items = all_items(tl)
    if not items:
        return True, 0
    ok = bool(tl.DeleteClips(items, False))
    return ok and not all_items(tl), len(items)


def remap_markers(markers: Dict[int, Dict[str, Any]], keep: List[Tuple[float, float]],
                  fps: float, origin: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Re-time the original's markers into the cut; report the ones that fell in
    removed audio rather than silently relocating them."""
    edges, cursor = [], 0.0
    for a, b in keep:
        edges.append((a, b, cursor))
        cursor += b - a
    moved, lost = [], []
    for frame, data in sorted((markers or {}).items()):
        # GetMarkers() keys are RELATIVE to the timeline start; the keep ranges
        # are absolute record seconds. Lift one into the other's space.
        at = (int(frame) + origin) / fps
        tol = 0.5 / fps          # half a frame
        for a, b, offset in edges:
            if a - tol <= at < b:
                moved.append({"frame": int(round((offset + (at - a)) * fps)), "data": data})
                break
        else:
            # A marker sitting exactly on a cut edge is not inside the removed
            # audio — it is the edge. Land it on the join instead of losing it.
            near = [(abs(at - b), offset + (b - a)) for a, b, offset in edges
                    if abs(at - b) <= tol]
            if near:
                moved.append({"frame": int(round(min(near)[1] * fps)), "data": data})
            else:
                lost.append({"frame": int(frame), "name": data.get("name", ""),
                             "at": round(at, 3)})
    return moved, lost


def marker_plan(plan: Dict[str, Any], keep: List[Tuple[float, float]]) -> List[Dict[str, Any]]:
    """One marker per splice on the NEW timeline, naming what was removed."""
    fps = float(plan["timeline_fps"])
    by_start = {round(r["start"], 3): r for r in plan["removals"] if r["state"] == "on"}
    markers, cursor = [], 0.0
    for index, (a, b) in enumerate(keep[:-1]):
        cursor += b - a
        removal = by_start.get(round(keep[index + 1][0], 3))
        if removal is None:
            near = [r for r in plan["removals"]
                    if r["state"] == "on" and abs(r["end"] - keep[index + 1][0]) < 0.05]
            removal = near[0] if near else None
        if removal is None or removal["kind"] == "silence":
            continue
        markers.append({
            "frame": max(0, int(round(cursor * fps)) - 1),
            "color": MARKER_COLOR.get(removal["kind"], "Cream"),
            "name": f"{removal['kind']}: {(removal['text'] or '')[:30]}".strip(),
            "note": removal["reason"],
        })
    return markers


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--mode", choices=("variant", "in-place"), default="variant",
                    help="variant: build in a duplicate, leave the original alone (default). "
                         "in-place: back the original up, then rebuild the original itself.")
    ap.add_argument("--name", help="name for the cut timeline (variant mode; default '<source> ROUGH')")
    ap.add_argument("--backup-name", help="name for the safety copy (in-place mode)")
    ap.add_argument("--markers", action="store_true",
                    help="drop a marker on every non-silence splice, for review in Resolve")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    work = Path(args.work_dir)
    timeline = rc.read_json(work / "timeline.json")
    plan = rc.read_json(work / "cutplan.json")
    keep = [(float(a), float(b)) for a, b in plan["keep"]]
    if not keep:
        raise SystemExit("Cut plan keeps nothing — refusing.")

    infos, warnings, tracks = build_clip_infos(timeline, plan)
    if not infos:
        raise SystemExit("Nothing cutable on this timeline — refusing.")
    name = args.name or f"{timeline['timeline']} ROUGH"

    worst = max(r["quantization_ms"] for r in infos)
    print(f"{len(keep)} keep ranges -> {len(infos)} clips "
          f"across V1..V{tracks['video']} / A1..A{tracks['audio']}")
    print(f"result {rc.hms(plan['stats']['result_seconds'])} "
          f"(from {rc.hms(plan['stats']['source_seconds'])})")
    print(f"worst frame quantization: {worst:.1f} ms "
          f"(1 frame = {1000 / timeline['timeline_fps']:.1f} ms)")
    for w in warnings:
        print(f"WARNING: {w}")

    rc.write_json(work / "append_infos.json",
                  {"timeline_name": name, "tracks": tracks, "infos": infos,
                   "warnings": warnings})
    if args.dry_run:
        print(f"\ndry run — wrote {work / 'append_infos.json'}, nothing changed in Resolve")
        return 0

    resolve = rc.connect_resolve()
    proj = rc.current_project(resolve)
    if proj.GetName() != timeline["project"]:
        raise SystemExit(f"Wrong project open: {proj.GetName()!r}, plan is for "
                         f"{timeline['project']!r}")
    source_tl = rc.find_timeline(proj, timeline["timeline"])
    mp = proj.GetMediaPool()

    root = mp.GetRootFolder()

    def find_clip(clip_id: str, folder=None):
        folder = folder or root
        for clip in folder.GetClipList() or []:
            try:
                if clip.GetUniqueId() == clip_id:
                    return clip
            except Exception:
                pass
        for sub in folder.GetSubFolderList() or []:
            found = find_clip(clip_id, sub)
            if found:
                return found
        return None

    cache: Dict[str, Any] = {}
    append: List[Dict[str, Any]] = []
    for row in infos:
        cid = row["clip_id"]
        if cid not in cache:
            clip = find_clip(cid)
            if clip is None:
                raise SystemExit(f"Media pool clip not found: {cid}")
            cache[cid] = clip
        append.append({
            "mediaPoolItem": cache[cid],
            "startFrame": row["start_frame"],
            "endFrame": row["end_frame"],       # EXCLUSIVE
            "trackIndex": row["track_index"],
            "mediaType": row["media_type"],
            "recordFrame": row["record_frame"],
        })

    in_place = args.mode == "in-place"
    origin = int(timeline["timeline_start_frame"])
    src_settings = source_tl.GetSetting()
    src_markers = source_tl.GetMarkers() or {}

    if in_place:
        backup = args.backup_name or f"{timeline['timeline']} · pre rough-cut"
        keeper = source_tl.DuplicateTimeline(backup)
        if not keeper:
            raise SystemExit(
                f"Could not create the safety backup {backup!r} — refusing to rebuild "
                "the original in place. A timeline by that name may already exist; "
                "pass --backup-name.")
        print(f"backup: {keeper.GetName()!r}")
        target = source_tl
    else:
        target = source_tl.DuplicateTimeline(name)
        if not target:
            raise SystemExit(
                f"DuplicateTimeline failed for {name!r} — a timeline by that name "
                "probably exists already. Pass --name.")

    proj.SetCurrentTimeline(target)
    cleared, removed_count = clear_timeline(target)
    if not cleared:
        raise SystemExit(
            f"Could not empty {target.GetName()!r} ({removed_count} items). Nothing was "
            "appended; the timeline is in a partial state — undo in Resolve.")

    placed = mp.AppendToTimeline(append)
    if not placed:
        raise SystemExit(f"AppendToTimeline returned nothing — {target.GetName()!r} is now "
                         "EMPTY. Undo in Resolve, or rebuild from the backup.")
    print(f"\nbuilt {len(placed)} items in timeline {target.GetName()!r} "
          f"({'in place' if in_place else 'variant'})")

    # settings must survive: this is the whole reason for duplicate-then-clear
    now = target.GetSetting()
    drift = {k: (v, now.get(k)) for k, v in src_settings.items() if now.get(k) != v}
    if drift:
        print(f"WARNING: {len(drift)} timeline setting(s) changed: "
              + ", ".join(f"{k} {a!r}->{b!r}" for k, (a, b) in list(drift.items())[:5]))
    else:
        print(f"settings: all {len(src_settings)} preserved "
              f"(fps {now.get('timelineFrameRate')})")

    moved, lost = remap_markers(src_markers, keep, float(timeline["timeline_fps"]), origin)
    if src_markers:
        target.DeleteMarkersByColor("All")
        readded = sum(1 for m in moved
                      if target.AddMarker(m["frame"], m["data"].get("color", "Blue"),
                                          m["data"].get("name", ""), m["data"].get("note", ""),
                                          max(1, int(m["data"].get("duration", 1))),
                                          m["data"].get("customData", "")))
        print(f"markers: {readded}/{len(src_markers)} re-timed into the cut"
              + (f", {len(lost)} sat in removed audio and were dropped" if lost else ""))
        for row in lost[:5]:
            print(f"  dropped: {row['name'] or '(unnamed)'} at {rc.hms(row['at'])}")

    if args.markers:
        added = sum(1 for m in marker_plan(plan, keep)
                    if target.AddMarker(m["frame"], m["color"], m["name"], m["note"], 1, ""))
        print(f"added {added} review markers")

    # readback: does the built timeline match the plan?
    built = int(target.GetEndFrame() or 0) - int(target.GetStartFrame() or 0)
    # Compare against the sum of the per-range frame durations, NOT against the
    # plan's total seconds: each range rounds to a whole frame independently, so
    # rounding the total instead drifts by a frame per few dozen cuts and raises
    # a false alarm on a build where every single range landed exactly.
    per_track: Dict[Tuple[int, int], int] = {}
    for row in infos:
        key = (row["media_type"], row["track_index"])
        per_track[key] = per_track.get(key, 0) + row["duration_tl_frames"]
    want = max(per_track.values()) if per_track else 0
    print(f"readback: {built} frames built vs {want} planned (delta {built - want})")
    if abs(built - want) > 2:
        print("WARNING: length does not match the plan. Inspect before trusting it.")
    name = target.GetName()
    rc.write_json(work / "applied.json", {
        "timeline_name": name, "mode": args.mode, "items_placed": len(placed),
        "built_frames": built, "planned_frames": want,
        "settings_drift": {k: [a, b] for k, (a, b) in drift.items()},
        "markers_remapped": len(moved), "markers_dropped": lost,
        "warnings": warnings})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

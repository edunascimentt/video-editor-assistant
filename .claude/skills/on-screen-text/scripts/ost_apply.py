#!/usr/bin/env python
"""Apply an on-screen-text plan to a Resolve timeline.

    ost_apply.py --work-dir "$WORK" --dry-run      # always do this first
    ost_apply.py --work-dir "$WORK" --markers-only
    ost_apply.py --work-dir "$WORK"                # markers + titles
    ost_apply.py --work-dir "$WORK" --clear        # remove this pass's output

Reads <work>/plan.json and <work>/context.json, writes <work>/applied.json.

The plan is the only thing that decides content and placement. This script owns
exactly three things you should not be doing by hand: the source/timeline fps
conversion, the overlap check, and the readback that proves what actually
landed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ost_common import (  # noqa: E402
    CLICK_DUR, CLICK_LEAD, CLICK_TRACK, ITEM_PREFIX, KINDS,
    MARKER_COLORS, NS, WORD_PAN, WORD_TILT, autosize, clip_by_id,
    connect_resolve, current_project, describe_clip,
    find_timeline, read_json, source_range_for, timecode, timeline_fps,
    write_json,
)

MAX_DEF_LINES = 3
MAX_DEF_COLS = 70

# ── the punch word ───────────────────────────────────────────────────────────
#
# A word is placed as a PAIR of clips off the 24 fps `Text+` in Master/Assets:
# an entrance of 41 frames (source 0..41, the letters flying in) and a hold that
# resumes at source 41 and stretches for whatever is left of the duration. That
# is the shape of the reference edit's PROCESSAMENTO and PLANEJAR, and the one approved on
# 2026-08-21, after watching it render. One long clip off the 60 fps Text+
# renders static instead; do not go back to it, and do not ImportFusionComp.
PUNCH_ENTRANCE = 41


def punch_segments(frame, dur, template_fps, tl_fps):
    """(record_frame, timeline_frames, source_in, source_out) for a punch word."""
    scale = (float(template_fps) or tl_fps) / float(tl_fps)
    warns = []
    ent = min(PUNCH_ENTRANCE, dur)
    if dur <= PUNCH_ENTRANCE + 8:
        warns.append(
            f"{dur} frames barely covers the {PUNCH_ENTRANCE}-frame entrance; "
            "the word will still be flying in when it cuts")
    segs = [(frame, ent, 0, max(1, int(round(ent * scale))))]
    if dur > ent:
        hold = dur - ent
        s0 = int(round(ent * scale))
        segs.append((frame + ent, hold, s0, s0 + max(1, int(round(hold * scale)))))
    return segs, warns


# ── validation ───────────────────────────────────────────────────────────────

def validate(plan, ctx, fps):
    """Everything that can be wrong before Resolve is touched."""
    errors, warnings = [], []
    end_frame = int(ctx["duration_frames"])

    markers = plan.get("markers", [])
    occupied = {int(f) for v in ctx.get("existing_markers", {}).values() for f in v}
    seen = {}
    for i, m in enumerate(markers):
        f = m.get("frame")
        if not isinstance(f, int):
            errors.append(f"markers[{i}]: frame must be an int")
            continue
        if not 0 <= f < end_frame:
            errors.append(f"markers[{i}]: frame {f} outside 0..{end_frame}")
        kind = m.get("kind")
        if kind and kind not in KINDS:
            errors.append(f"markers[{i}]: unknown kind {kind!r}")
        color = m.get("color") or (KINDS[kind][0] if kind in KINDS else None)
        if color not in MARKER_COLORS:
            errors.append(f"markers[{i}]: color {color!r} not a Resolve color")
        if f in seen:
            errors.append(
                f"markers[{i}]: frame {f} already taken by markers[{seen[f]}] "
                "-- Resolve holds one marker per frame")
        if f in occupied:
            errors.append(
                f"markers[{i}]: frame {f} already carries a marker on the "
                "timeline (rough-cut leftovers?) -- Resolve refuses a second "
                "one there; nudge a frame or clear the old one")
        seen[f] = i
        if kind == "slide" and int(m.get("duration", 1)) <= 1:
            warnings.append(
                f"markers[{i}]: slide marker with duration 1 -- slides are the "
                "one kind that should span their section")

    items = plan.get("items", [])
    per_track = {}
    for i, it in enumerate(items):
        kind = it.get("kind")
        if kind not in ("word", "explain"):
            errors.append(f"items[{i}]: kind must be 'word' or 'explain'")
            continue
        f, dur = it.get("frame"), it.get("duration")
        if not isinstance(f, int) or not isinstance(dur, int) or dur <= 0:
            errors.append(f"items[{i}]: need int frame and positive duration")
            continue
        if f + dur > end_frame:
            warnings.append(
                f"items[{i}]: runs to {f + dur}, past the timeline end {end_frame}")
        track = int(it.get("track", 0) or 0)
        if track < 2:
            errors.append(
                f"items[{i}]: track {track} -- V1 is the talking head, put "
                "titles on V2 or above")
        per_track.setdefault(track, []).append((f, f + dur, i))
        if kind == "word" and it.get("sfx", True) and f - CLICK_LEAD < 0:
            warnings.append(
                f"items[{i}]: at frame {f} the click has no room for its "
                f"{CLICK_LEAD}-frame lead; it will be dropped")
        if kind == "word" and not str(it.get("text", "")).strip():
            errors.append(f"items[{i}]: word needs text")
        if kind == "word" and dur < PUNCH_ENTRANCE + 8:
            warnings.append(
                f"items[{i}]: {dur} frames is shorter than the "
                f"{PUNCH_ENTRANCE}-frame entrance plus a beat of hold")
        if kind == "explain":
            if not str(it.get("term", "")).strip():
                errors.append(f"items[{i}]: explain needs term")
            definition = str(it.get("definition", ""))
            if not definition.strip():
                errors.append(f"items[{i}]: explain needs definition")
            lines = definition.split("\n")
            if len(lines) > MAX_DEF_LINES:
                warnings.append(
                    f"items[{i}]: definition is {len(lines)} lines; the card is "
                    f"built for {MAX_DEF_LINES}")
            for ln in lines:
                if len(ln) > MAX_DEF_COLS:
                    warnings.append(
                        f"items[{i}]: definition line of {len(ln)} chars will "
                        f"overrun (~{MAX_DEF_COLS} fits)")

    for track, spans in per_track.items():
        spans.sort()
        for (a_s, a_e, ai), (b_s, b_e, bi) in zip(spans, spans[1:]):
            if b_s < a_e:
                errors.append(
                    f"items[{ai}] and items[{bi}] overlap on V{track} "
                    f"({a_s}-{a_e} vs {b_s}-{b_e}). Resolve would shift one "
                    "silently -- move one to another track or shorten it")
    return errors, warnings


# ── resolve-side helpers ─────────────────────────────────────────────────────

def preflight_templates(media_pool, plan, ctx):
    """Resolve every template the plan needs BEFORE anything is written.

    A missing template discovered halfway through leaves the timeline with
    titles and no clicks, which is worse than not starting.
    """
    needed = set()
    for it in plan.get("items", []):
        if it.get("kind") == "explain":
            needed.add("explain")
        elif it.get("kind") == "word":
            needed.add("word")
    if any(it["kind"] == "word" and it.get("sfx", True)
           for it in plan.get("items", [])):
        needed.add("click")
    for kind in sorted(needed):
        override = plan.get(f"{kind}_clip_id")
        if kind in ("word", "explain"):
            override = override or next(
                (it.get("clip_id") for it in plan["items"]
                 if it["kind"] == kind and it.get("clip_id")), None)
        resolve_template(media_pool, ctx, kind, override)


def resolve_template(media_pool, ctx, kind, override_id):
    clip_id = override_id
    if not clip_id:
        chosen = (ctx.get("templates", {}).get(kind) or {}).get("chosen")
        if not chosen:
            raise SystemExit(
                f"no {kind} template in context.json and no clip_id in the "
                "plan. Re-run ost_probe.py, or pin the id yourself.")
        clip_id = chosen["id"]
    clip = clip_by_id(media_pool, clip_id)
    if clip is None:
        raise SystemExit(f"media pool item {clip_id} not found (project changed?)")
    return clip, describe_clip(clip)


def set_text(item, mapping, receipt):
    """Write StyledText/Size onto a timeline item's Fusion comp."""
    if int(item.GetFusionCompCount() or 0) < 1:
        receipt.append("no fusion comp on the placed item")
        return False
    comp = item.GetFusionCompByIndex(1)
    ok = True
    for tool_name, inputs in mapping.items():
        tool = comp.FindTool(tool_name)
        if tool is None:
            receipt.append(f"tool {tool_name!r} missing from comp")
            ok = False
            continue
        for key, value in inputs.items():
            if not tool.SetInput(key, value):
                # SetInput returns None on success in some builds; verify.
                got = tool.GetInput(key)
                if got != value:
                    receipt.append(f"{tool_name}.{key} did not take")
                    ok = False
    return ok


def managed_items(tl, tracks, work):
    """Timeline items this pass placed, by the ids recorded in applied.json.

    Name matching is not an option: this pass must not rename its items (a
    rename freezes the Fusion comp), so the receipt is the only handle.
    """
    receipt = work / "applied.json"
    if not receipt.exists():
        return []
    try:
        prev = read_json(receipt)
    except Exception:
        return []
    wanted = {}
    for r in prev.get("items", []):
        for uid in (r.get("item_ids") or ([r["item_id"]] if r.get("item_id") else [])):
            wanted[uid] = r.get("name", "?")
    hits = []
    for t in tracks:
        for idx, item in enumerate(tl.GetItemListInTrack("video", t) or []):
            uid = item.GetUniqueId()
            if uid in wanted:
                hits.append((t, idx, item, wanted[uid]))
    return hits


# ── actions ──────────────────────────────────────────────────────────────────

def do_clear(tl, plan, fps, work):
    tracks = sorted({int(i.get("track", 0)) for i in plan.get("items", [])
                     if int(i.get("track", 0)) >= 2}) or [2, 3]
    hits = managed_items(tl, tracks, work)
    removed_markers = 0
    for frame, m in list((tl.GetMarkers() or {}).items()):
        if str(m.get("customData", "")).startswith(f"{NS}:"):
            if tl.DeleteMarkerAtFrame(int(frame)):
                removed_markers += 1
    removed_items = 0
    if hits:
        if tl.DeleteClips([h[2] for h in hits]):
            removed_items = len(hits)
    if not hits:
        print("           (no applied.json receipt on this work dir -- nothing "
              "to match; titles must be removed by hand)")
    print(f"cleared    {removed_items} title(s), {removed_markers} marker(s)")
    for _, _, _, name in hits:
        print(f"  - {name}")
    return {"cleared_items": removed_items, "cleared_markers": removed_markers}


def do_markers(tl, plan, fps, dry):
    placed, failed = [], []
    for m in plan.get("markers", []):
        kind = m.get("kind")
        color = m.get("color") or KINDS[kind][0]
        custom = m.get("custom_data") or (KINDS[kind][1] if kind in KINDS else "")
        frame = int(m["frame"])
        dur = int(m.get("duration", 1))
        row = {"frame": frame, "tc": timecode(frame, fps), "color": color,
               "duration": dur, "name": m.get("name", ""), "kind": kind}
        if dry:
            placed.append(row)
            continue
        ok = tl.AddMarker(frame, color, m.get("name", ""), m.get("note", ""),
                          dur, custom)
        (placed if ok else failed).append(row)
    return placed, failed


def do_items(tl, media_pool, plan, ctx, fps, dry):
    placed, failed = [], []
    needed = max([int(i.get("track", 0)) for i in plan.get("items", [])] or [0])
    have = int(tl.GetTrackCount("video") or 0)
    if needed > have and not dry:
        for _ in range(needed - have):
            tl.AddTrack("video")
    if needed > have:
        print(f"tracks     V{have} -> V{needed} ({needed - have} added)")

    cache = {}
    for i, it in enumerate(plan.get("items", [])):
        kind = it["kind"]
        # A word is placed as a punch pair off the 24 fps Text+; an `explain`
        # card is one clip. See punch_segments above.
        key = (kind, it.get("clip_id"))
        if key not in cache:
            cache[key] = resolve_template(media_pool, ctx, kind, it.get("clip_id"))
        clip, meta = cache[key]
        dur = int(it["duration"])
        stretchable = str(meta.get("type") or "").startswith("Fusion")
        label = it.get("name") or (
            ITEM_PREFIX[kind] + str(it.get("text") or it.get("term")).replace("\n", " "))
        row = {"index": i, "kind": kind, "frame": int(it["frame"]),
               "tc": timecode(int(it["frame"]), fps), "duration": dur,
               "track": int(it["track"]), "name": label}
        if kind == "word":
            row["size"] = float(it.get("size") or autosize(it["text"]))
            segs, warns = punch_segments(int(it["frame"]), dur, meta["fps"], fps)
        else:
            s_, e_, warns = source_range_for(dur, meta["fps"], fps, meta["frames"],
                                             stretchable=stretchable)
            segs = [(int(it["frame"]), dur, s_, e_)]
        row["source_range"] = [segs[0][2], segs[-1][3]]
        row["segments"] = [list(seg) for seg in segs]
        row["warnings"] = warns
        if dry:
            placed.append(row)
            continue

        if kind == "word":
            mapping = {"Template": {"StyledText": it["text"], "Size": row["size"]}}
            tf = {"Pan": float(it.get("pan", WORD_PAN)),
                  "Tilt": float(it.get("tilt", WORD_TILT)),
                  "ZoomX": float(it.get("zoom", 1.0)),
                  "ZoomY": float(it.get("zoom", 1.0))}
            row["transform"] = tf
        else:
            mapping = {"Text1": {"StyledText": it["term"]},
                       "Template": {"StyledText": it["definition"]}}
            tf = {}

        receipt, ids = [], []
        for rec, seg_dur, src_in, src_out in segs:
            got = media_pool.AppendToTimeline([{
                "mediaPoolItem": clip, "startFrame": src_in, "endFrame": src_out,
                "recordFrame": rec, "trackIndex": int(it["track"]),
                "mediaType": 1}])
            if not got:
                row["error"] = f"AppendToTimeline refused at frame {rec}"
                break
            item = got[0]
            actual = int(item.GetEnd()) - int(item.GetStart())
            if actual != seg_dur:
                row["warnings"] = row.get("warnings", []) + [
                    f"segment at {rec} landed {actual} frames, asked {seg_dur}"]
            ids.append(item.GetUniqueId())
            if not set_text(item, mapping, receipt):
                row["error"] = "; ".join(receipt)
            for prop, value in tf.items():
                if not item.SetProperty(prop, value):
                    receipt.append(f"transform {prop} did not take at {rec}")
                    row["error"] = "; ".join(receipt)

        # No SetName here, ever -- see the warning in ost_common. The label is
        # recorded in applied.json instead, and --clear works off the ids.
        row["item_id"] = ids[0] if ids else None
        row["item_ids"] = ids
        (failed if row.get("error") else placed).append(row)
    return placed, failed


def do_sfx(tl, media_pool, plan, ctx, fps, dry):
    """One Burnin Click on the audio track, two frames ahead of each word."""
    wants = [it for it in plan.get("items", [])
             if it["kind"] == "word" and it.get("sfx", True)
             and int(it["frame"]) - CLICK_LEAD >= 0]
    if not wants:
        return [], []
    track = int(plan.get("sfx_track", CLICK_TRACK))
    have = int(tl.GetTrackCount("audio") or 0)
    if track > have:
        if not dry:
            for _ in range(track - have):
                tl.AddTrack("audio")
        print(f"tracks     A{have} -> A{track} ({track - have} added)")

    clip, meta = resolve_template(media_pool, ctx, "click",
                                  plan.get("click_clip_id"))
    placed, failed = [], []
    occupied = set()
    if not dry:
        for item in (tl.GetItemListInTrack("audio", track) or []):
            occupied.add(int(item.GetStart()))
    for it in wants:
        at = int(it["frame"]) - CLICK_LEAD
        dur = int(it.get("sfx_duration", CLICK_DUR))
        s_, e_, _ = source_range_for(dur, meta["fps"], fps, meta["frames"],
                                     stretchable=False)
        row = {"frame": at, "tc": timecode(at, fps), "duration": dur,
               "track": track, "for": it.get("text", "")}
        if dry:
            placed.append(row)
            continue
        if at in occupied:
            row["error"] = "an audio clip already starts here"
            failed.append(row)
            continue
        got = media_pool.AppendToTimeline([{
            "mediaPoolItem": clip, "startFrame": s_, "endFrame": e_,
            "recordFrame": at, "trackIndex": track, "mediaType": 2}])
        if not got:
            row["error"] = "AppendToTimeline refused"
            failed.append(row)
            continue
        occupied.add(at)
        placed.append(row)
    return placed, failed


def verify(tl, plan, fps):
    """Read the timeline back and confirm every title carries its text."""
    problems = []
    tracks = sorted({int(i["track"]) for i in plan.get("items", [])})
    by_frame = {}
    for t in tracks:
        for item in (tl.GetItemListInTrack("video", t) or []):
            by_frame[(t, int(item.GetStart()))] = item
    for it in plan.get("items", []):
        key = (int(it["track"]), int(it["frame"]))
        item = by_frame.get(key)
        if item is None:
            problems.append(f"V{key[0]}@{key[1]}: nothing there")
            continue
        if int(item.GetFusionCompCount() or 0) < 1:
            problems.append(f"V{key[0]}@{key[1]}: no fusion comp")
            continue
        comp = item.GetFusionCompByIndex(1)
        want = it["text"] if it["kind"] == "word" else it["term"]
        tool = comp.FindTool("Template" if it["kind"] == "word" else "Text1")
        got = tool.GetInput("StyledText") if tool else None
        if got != want:
            problems.append(f"V{key[0]}@{key[1]}: text is {got!r}, want {want!r}")
    markers = tl.GetMarkers() or {}
    for m in plan.get("markers", []):
        if int(m["frame"]) not in {int(k) for k in markers}:
            problems.append(f"marker@{m['frame']}: missing")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--markers-only", action="store_true")
    ap.add_argument("--items-only", action="store_true")
    ap.add_argument("--no-sfx", action="store_true",
                    help="skip the Burnin Click that announces each word")
    ap.add_argument("--clear", action="store_true",
                    help="delete this pass's markers and titles, then stop")
    ap.add_argument("--force", action="store_true",
                    help="apply despite validation errors (it will bite)")
    args = ap.parse_args()

    work = Path(args.work_dir).expanduser()
    ctx = read_json(work / "context.json")
    plan = read_json(work / "plan.json")

    resolve = connect_resolve()
    proj = current_project(resolve)
    tl = find_timeline(proj, plan.get("timeline") or ctx.get("timeline"))
    fps = timeline_fps(tl)
    if abs(fps - float(ctx["timeline_fps"])) > 1e-6:
        raise SystemExit(
            f"timeline is {fps:g} fps, context.json says {ctx['timeline_fps']:g}. "
            "Re-run ost_probe.py -- every duration here derives from that number.")
    if not proj.GetCurrentTimeline() or \
            proj.GetCurrentTimeline().GetUniqueId() != tl.GetUniqueId():
        proj.SetCurrentTimeline(tl)

    print(f"timeline   {tl.GetName()}  ({fps:g} fps)")

    if args.clear:
        do_clear(tl, plan, fps, work)
        resolve.GetProjectManager().SaveProject()
        return 0

    errors, warnings = validate(plan, ctx, fps)
    for w in warnings:
        print(f"[WARN] {w}")
    for e in errors:
        print(f"[ERROR] {e}")
    if errors and not args.force:
        print("\nrefusing to apply. Fix the plan, or pass --force.")
        return 1

    if not args.markers_only:
        preflight_templates(proj.GetMediaPool(), plan, ctx)

    mk_placed, mk_failed, it_placed, it_failed = [], [], [], []
    sfx_placed, sfx_failed = [], []
    if not args.items_only:
        mk_placed, mk_failed = do_markers(tl, plan, fps, args.dry_run)
    if not args.markers_only:
        it_placed, it_failed = do_items(
            tl, proj.GetMediaPool(), plan, ctx, fps, args.dry_run)
        if not args.no_sfx:
            sfx_placed, sfx_failed = do_sfx(
                tl, proj.GetMediaPool(), plan, ctx, fps, args.dry_run)

    verb = "would place" if args.dry_run else "placed"
    print(f"\nmarkers    {verb} {len(mk_placed)}"
          + (f", FAILED {len(mk_failed)}" if mk_failed else ""))
    for r in mk_placed:
        span = f"+{r['duration']}" if r["duration"] > 1 else ""
        print(f"  {r['tc']}  {r['color']:<7} {r['name']}{span}")
    print(f"titles     {verb} {len(it_placed)}"
          + (f", FAILED {len(it_failed)}" if it_failed else ""))
    for r in it_placed + it_failed:
        src = f"src {r['source_range'][0]}-{r['source_range'][1]}"
        print(f"  {r['tc']}  V{r['track']}  {r['duration']}f  {src:<12} {r['name']}")
        for w in r.get("warnings", []):
            print(f"      [WARN] {w}")
        if r.get("error"):
            print(f"      [ERROR] {r['error']}")
    if sfx_placed or sfx_failed:
        print(f"clicks     {verb} {len(sfx_placed)}"
              + (f", FAILED {len(sfx_failed)}" if sfx_failed else ""))
        for r in sfx_failed:
            print(f"  {r['tc']}  A{r['track']}  {r['for']}  "
                  f"[ERROR] {r['error']}")

    if args.dry_run:
        print("\ndry run -- nothing was written.")
        return 0

    problems = verify(tl, plan, fps)
    print(f"\nverify     {'OK' if not problems else str(len(problems)) + ' problem(s)'}")
    for p in problems:
        print(f"  [FAIL] {p}")

    write_json(work / "applied.json", {
        "timeline": tl.GetName(), "fps": fps,
        "markers": mk_placed, "markers_failed": mk_failed,
        "items": it_placed, "items_failed": it_failed,
        "sfx": sfx_placed, "sfx_failed": sfx_failed,
        "verify_problems": problems,
    })
    resolve.GetProjectManager().SaveProject()
    print("project saved.")
    return 1 if (problems or mk_failed or it_failed or sfx_failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())

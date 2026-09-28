#!/usr/bin/env python3
"""Plan angle switches for a cut built from one camera, onto a V2 of the others.

    plan_switches.py v1.json cams.json [--min-seconds 1.0] > plan.json

v1.json — the cut as it stands, one entry per V1 item, in order:
    [{"start": 0, "end": 74, "src": 7.917}, ...]
    start/end: record frames (end exclusive); src: second in the MAIN camera's
    file where the item starts (GetLeftOffset() / timeline_fps).

cams.json — the main camera and the sources for the other angles:
    {"timeline_fps": 23.976, "main": "FX30",
     "rotation": ["A7IV", "ZVE10", "ZVE1"],
     "sources": [
       {"cam": "A7IV",  "clip": "A7IV_1449_1.mp4", "fps": 23.976, "offset": 0.0247},
       {"cam": "ZVE1",  "clip": "ZVE1_1768_1.mp4", "fps": 59.94,  "offset": -5.984,
        "from": 6.0, "to": 178.0},
       {"cam": "ZVE1",  "clip": "ZVE1_1769_1.mp4", "fps": 59.94,  "offset": -185.018,
        "from": 185.0}
     ]}
    offset: t_cam = t_main + offset (from sync_offset.py). from/to: the span of
    MAIN-camera seconds this file covers (a camera that stopped, or split its
    take into two files); omitted = the whole file is assumed to cover.

Rules (the ones that worked on real multi-camera sermons/interviews):
  * open on the main camera; a switch only ever happens ON a V1 cut — it is
    what hides the jump cut;
  * alternate main <-> another angle, cycling the rotation;
  * an item shorter than --min-seconds keeps the previous angle, so no angle blinks;
  * an angle is only used if one of its files covers the whole item — otherwise
    the next angle in the rotation, otherwise stay on main.

Output: one V2 entry per stretch off the main camera, ready for
AppendToTimeline with mediaType 1: recordFrame, clip, startFrame/endFrame in the
CLIP's own fps (endFrame exclusive). Media already at the timeline rate takes
n = duration exactly; only rate-changing media goes through ceil().
"""
from __future__ import annotations

import argparse
import json
import math
import sys


def same_rate(a: float, b: float) -> bool:
    return abs(a - b) < 0.01


def covering(sources, cam, t0, t1):
    for s in sources:
        if s["cam"] != cam:
            continue
        lo = s.get("from", -math.inf)
        hi = s.get("to", math.inf)
        if lo <= t0 and t1 <= hi and t0 + s["offset"] >= 0:
            return s
    return None


def plan(v1, cfg, min_seconds=1.0):
    fps = cfg["timeline_fps"]
    rot = list(cfg["rotation"])
    k = 0                      # next angle in the rotation
    angle = cfg["main"]        # angle currently on screen
    stretches = []             # [cam, source, first_item, last_item]
    for i, it in enumerate(v1):
        dur_s = (it["end"] - it["start"]) / fps
        t0, t1 = it["src"], it["src"] + dur_s
        if i == 0:
            want = cfg["main"]                                 # open on the main angle
        elif dur_s < min_seconds:
            want = angle                                       # short: inherit
        else:
            want = cfg["main"] if angle != cfg["main"] else None
        src = None
        if want is None:                                       # time for another angle
            for j in range(len(rot)):
                cam = rot[(k + j) % len(rot)]
                src = covering(cfg["sources"], cam, t0, t1)
                if src:
                    want, k = cam, (k + j + 1) % len(rot)
                    break
            if not src:
                want = cfg["main"]
        elif want != cfg["main"]:
            src = covering(cfg["sources"], want, t0, t1)
            if not src:                                        # inherited angle ran out
                want = cfg["main"]
        angle = want
        if want == cfg["main"]:
            continue
        if stretches and stretches[-1][0] == want and stretches[-1][3] == i - 1 \
                and stretches[-1][1] is src:
            stretches[-1][3] = i
        else:
            stretches.append([want, src, i, i])

    out = []
    for cam, src, a, b in stretches:
        for it in v1[a:b + 1]:          # one entry per V1 item keeps the cut points exact
            n_tl = it["end"] - it["start"]
            cfps = src["fps"]
            n = n_tl if same_rate(cfps, fps) else math.ceil(n_tl * cfps / fps)
            sf = round((it["src"] + src["offset"]) * cfps)
            out.append({"cam": cam, "clip": src["clip"], "recordFrame": it["start"],
                        "startFrame": sf, "endFrame": sf + n, "timeline_frames": n_tl,
                        "mediaType": 1, "trackIndex": 2})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("v1")
    ap.add_argument("cams")
    ap.add_argument("--min-seconds", type=float, default=1.0)
    a = ap.parse_args()
    v1 = json.load(open(a.v1, encoding="utf-8"))
    cfg = json.load(open(a.cams, encoding="utf-8"))
    entries = plan(v1, cfg, a.min_seconds)
    fps = cfg["timeline_fps"]
    total = (v1[-1]["end"] - v1[0]["start"]) if v1 else 1
    off = sum(e["timeline_frames"] for e in entries)
    by = {}
    for e in entries:
        by[e["cam"]] = by.get(e["cam"], 0) + e["timeline_frames"]
    switches = sum(1 for i, e in enumerate(entries)
                   if i == 0 or entries[i - 1]["recordFrame"] + entries[i - 1]["timeline_frames"] != e["recordFrame"]
                   or entries[i - 1]["cam"] != e["cam"])
    print(f"{len(entries)} V2 entries, {switches} stretches off {cfg['main']}, "
          f"{100 * off / total:.0f}% of {total / fps:.1f}s off the main camera "
          + ", ".join(f"{c} {v / fps:.1f}s" for c, v in by.items()), file=sys.stderr)
    json.dump(entries, sys.stdout, indent=1)


if __name__ == "__main__":
    main()

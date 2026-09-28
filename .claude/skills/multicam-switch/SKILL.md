---
name: multicam-switch
description: Adds the other camera angles to a talking-head cut that was built from one camera — finds which file of each camera is the same take by audio correlation (file names never match across cameras), measures the sync offset to a few milliseconds, plans switches that land only on existing V1 cuts, and places them on V2 frame-accurately in DaVinci Resolve. Use when the user says "faltou as outras câmeras", "coloca as trocas de câmera", "dá uma diferença com os outros ângulos", wants a multicam feel on a sermon/interview/lesson, or needs two recordings of the same event synced (camera vs camera, camera vs screen recording).
---

# Multicam switches on a single-camera cut

The cut already exists on V1 from the camera with the main audio. This skill
puts the other angles on V2 (video only), switching **only where V1 already
cuts**, so every jump cut becomes an angle change instead.

```bash
MC="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/skills/multicam-switch/scripts"
PY="${RESOLVE_MCP_HOME:-$HOME/Repositories/davinci-resolve-mcp}/venv/bin/python"
```

Read the `resolve-scripting` skill before writing the apply script.

## 1. Find each camera's file for this take

File names never correspond across cameras, and durations only narrow it down.
Correlate audio envelopes against the main camera:

```bash
$PY $MC/sync_offset.py match MAIN.mp4 CAMB/*.mp4 CAMC/*.mp4
#  0.93  offset  +3.65s  CAMB/1444.mp4  <- same take
#  0.21  offset  ...     CAMB/1443.mp4
```

The right file scores 0.8–0.95, other takes 0.1–0.3. Short files (6–17 s) are
usually tests; a vertical file or a wide shot with crew in frame is not an
angle. A camera may have split one take into **two files** with a gap between
them — both will match, each for its own stretch.

## 2. Measure the offset

```bash
$PY $MC/sync_offset.py offset MAIN.mp4 CAMB/1444.mp4 --windows 3
# offset: t_other = t_ref +3.6450 s   drift 0 ms
# note: ... ends at ref 699.0s — no coverage after that
```

`t_cam = t_main + offset`, in seconds of each file — valid at any frame rate.
Every take has its own offsets; never reuse another take's. Drift above a frame
across the windows means a variable-rate file: split into stretches.
Accuracy is 5 ms. Tested on synthetic offsets (+3.6439 / −6.7411 s): recovered
within 1 ms, 0 ms drift.

**Coverage matters.** Note where each camera starts and stops relative to the
main one — a camera that ran out of card 2 minutes before the end cannot be
used for the closing line, and the plan must know.

## 3. Read the cut

From Resolve, one entry per V1 item: record start/end and the main-camera
second where it starts.

```python
fps = float(p.GetSetting("timelineFrameRate"))
v1 = [{"start": it.GetStart(), "end": it.GetEnd(), "src": it.GetLeftOffset() / fps}
      for it in rv.track_items(tl, "video", 1)]
```

`GetLeftOffset()` is in **timeline** frames — divide by the timeline fps, not
the media fps.

## 4. Plan

Write `cams.json` (format in the script's header: timeline fps, main camera,
rotation order, and one source per camera file with `offset` and optional
`from`/`to` coverage in main-camera seconds), then:

```bash
python3 $MC/plan_switches.py v1.json cams.json > plan.json
# 35 V2 entries, 20 stretches off FX30, 52% of 131.1s off the main camera ...
```

The rules it applies, measured on real edits:

- **Open on the main camera; switch only on a V1 cut.**
- **Alternate** main ↔ another angle, cycling the rotation (A → B → C → A…).
- **An item under 1 s keeps the previous angle** — no angle blinks.
- **Use an angle only where one of its files covers the whole item**; otherwise
  try the next angle, otherwise stay on main.

Around half the running time off the main camera (47–55%) read well to the
editor. Change `rotation` to favour an angle; drop one from it to exclude it.

## 5. Check before writing

- **Contact sheet of each switch:** extract the middle frame of every V2 entry
  (`ffmpeg -ss <t> -i cam.mp4 -frames:v 1 f.jpg`) and look: the speaker framed, nobody from
  the crew in shot, no one walking through. This machine's ffmpeg may lack
  `drawtext`; print the order instead of labelling the image.
- **Sync of each entry by its own audio:** correlate a 6 s window around each
  entry in the camera's audio against the main audio. A 1-frame item in a
  quiet stretch gives garbage (200–250 ms); widen the window before believing a
  desync. Worst real residual after a good plan: ~21 ms.

## 6. Apply

Append the entries with `mediaType: 1` on V2 (add the track if needed),
**one batch**, then read back `GetStart/GetEnd` of every placed item against
its V1 cut. The frame rules that bite here:

- `endFrame` is exclusive and in the **clip's own fps**.
- Media at the timeline rate uses `n = duration` exactly — **no `ceil`**
  (23.976023… vs 23.976 makes `ceil` add a frame). Only rate-changing media
  (29.97, 59.94 on a 23.976 timeline) uses `ceil`. The planner does this.
- One zero-length entry rejects the whole batch.

Re-read after applying; only the readback shows a frame too many or too few.

## Zooms on the angles

If the editor's reference cut has static punch-ins per angle, reproduce them
with the same numbers (`ZoomX/ZoomY`, `Tilt`) on the V2 items. Dynamic zooms
cannot be scripted — leave Cyan markers with duration (see `resolve-scripting`).

## Report

Offsets per camera with drift, coverage gaps, switch count and % off main per
angle, anything excluded (crew in frame, camera ended early), and the readback
result.

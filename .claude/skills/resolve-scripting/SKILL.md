---
name: resolve-scripting
description: The DaVinci Resolve scripting API facts that fail silently — AppendToTimeline frame semantics, stills that ignore endFrame, subtitles that ignore recordFrame, no volume/keyframe/adjustment-clip API, GetLeftOffset units, CopyGrades across timelines, cloning Fusion titles through a .drt — plus a connection helper that survives Resolve dropping the scripting link mid-run. Use before writing ANY ad-hoc Python against Resolve (building, rebuilding or finishing a timeline, placing clips/titles/SFX/music, copying grades, moving bins), when an append lands a frame short or long, when a script dies on a NoneType from scriptapp, or when the Resolve MCP returns success but nothing changed.
---

# Scripting DaVinci Resolve without silent failures

Every other editing skill in this repo ends up writing a small script against
Resolve's API. This one holds what those scripts must know, all of it measured
on real projects. Almost none of these fail loudly: the usual symptom is a
timeline that looks plausible and is a frame, a clip or a whole track wrong.

## Setup

```bash
RVS="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/skills/resolve-scripting/scripts"
RESOLVE_MCP_HOME="${RESOLVE_MCP_HOME:-$HOME/Repositories/davinci-resolve-mcp}"
PY="$RESOLVE_MCP_HOME/venv/bin/python"        # has DaVinciResolveScript deps + numpy
$PY $RVS/rv.py                                # prints project + current timeline
```

`rv.py` is the only way scripts should connect:

```python
import sys; sys.path.insert(0, RVS)
import rv
resolve, pm, p = rv.app(project="PROJECT NAME", folder="Subfolder")  # retries, loads, refuses wrong project
tl = rv.timeline(p, "TIMELINE NAME")
snapshot = rv.describe(tl)          # always look before you write
...
rv.assert_project(pm, "PROJECT NAME")   # right before each write
rv.save(pm)
```

If the Resolve MCP servers fail to start, check `RESOLVE_MCP_HOME` first —
`.mcp.json` reads the checkout from it, and unset it resolves to a path that
does not exist. The direct API above still works while the MCP is down.

## Before writing to any timeline

1. **Probe the live timeline** with `rv.describe`. Editors keep working while
   scripts run: tracks gain SFX, clips move, durations change by a few frames.
   Write only to an **empty track** (add one and `SetTrackName` it) instead of
   competing for space, and never "fix" something that appeared — it is theirs.
2. **Frames you saved earlier are stale** if the editor touched the timeline.
   Re-map from source time instead (below, *Re-mapping*).
3. **Refuse on the wrong project.** A rebuild that runs against whatever is
   current will delete the wrong timeline's items first and notice later.

## `AppendToTimeline` — the rules

| Fact | Consequence |
|---|---|
| `startFrame`/`endFrame` are in the **media's own fps**, not the timeline's | a 60 fps clip on a 24 fps timeline needs `round(s*60)`; a 30 fps SFX asking for `endFrame: 104` gives ~83 timeline frames. Convert per clip. |
| `endFrame` is **exclusive** (with `recordFrame`, any rate) | `endFrame = f0 + n` gives n frames. |
| Do **not** `ceil` a duration for media already at the timeline rate | `dur * 23.976023 / 23.976` is a hair over `dur`; `ceil` adds a frame and the item lands 1 frame long. Only rate-changing media goes through `ceil`. |
| One zero-length entry **rejects the whole batch** | returns 0 items, writes nothing. A 1-frame V1 item minus 1 is zero. Filter first. |
| A **still** always lands as **120 frames** (a user preference, not a project setting) | `endFrame` is ignored. Tile stills in blocks of 120 and align the block grid from the end: `start = end - ceil((end - target)/120)*120`, then trim the first keep range to match. |
| Omit `mediaType` → video+audio; `1` → video only; `2` → audio only; `3` → subtitle | cutaways/b-roll/other angles go in with `mediaType: 1`. |
| Without `recordFrame`, clips pack end-to-end | handy for assembling a V1 from spans; read `GetItemListInTrack` afterwards to learn where each block landed. |
| A range collision fails silently (MCP wrapper says `missing timeline item id at index 0`) | the track already holds something there — probe first. |
| **Always read back** `GetStart/GetEnd` of every placed item against what you planned | only the readback shows the frame too many or too few. |

## Things the API cannot do — plan around them

- **No razor.** `DeleteClips`, `lift_range`, `apply_cuts` remove whole items. A
  cut is a rebuild: duplicate, empty, re-append keep ranges. The `rough-cut`
  skill does this.
- **`CreateEmptyTimeline` inherits the PROJECT's settings.** A 24 fps timeline
  in a 30 fps project comes back at 30. Always `DuplicateTimeline` and empty it.
- **`DuplicateTimeline` ignores `SetCurrentFolder`** — the copy lands in the
  source's bin. `MoveClips` it afterwards and list the bin again.
- **No clip volume.** `GetProperty("Volume")` is None, there is no setter.
  Render gain, fades and envelopes into the file with ffmpeg and swap the file
  (see the `music-bed` skill). A `.drt` export does carry clip gain (in the
  item's `EffectFiltersBA`), which is how to *read* an editor's level.
- **No keyframes, no adjustment clips, no Dynamic Zoom.** `TimelineItem` has
  only `Get/SetProperty`; adjustment clips are not media-pool items;
  `DynamicZoomEase` is the only related property. Do the static half by
  script (`ZoomX/ZoomY/Pan/Tilt`) and leave a **Cyan marker with the duration**
  for each dynamic move, so the manual step is just dragging a box.
- **No copy of Fusion titles.** `copy_clips`/`duplicate_clips` refuse items
  without a media-pool item, and `InsertFusionTitleIntoTimeline` only knows
  installed templates by name. Clone them through the `.drt` — see
  `reference/drt-clone.md`.
- **Fusion comps already on a timeline** return `None` from
  `GetMediaPoolItem()`. To place another, find the template in the pool by its
  id or name (`rv.find_clip`).
- **Never `SetName` an item carrying a Fusion comp** — it freezes the comp
  (renders at full opacity from frame one).
- **Subtitles:** `timeline.ImportSubtitle` does not exist (`hasattr` lies on
  remote objects — only calling tells). `MediaPool.ImportMedia([srt])` gives a
  Subtitle clip; `AppendToTimeline` with `mediaType: 3` places it but
  **ignores `recordFrame`** — it lands at the end of the timeline, or at 0 on an
  empty one. `ImportMedia` of an already-imported path returns the **old**
  clip with the old parse: `DeleteClips` it from the pool first. Subtitle clips
  cannot be renamed. The `subtitles` skill owns this route.
- **Volume/Opacity of the intro music, dynamic zoom, window/crop by eye** —
  anything the API does not expose goes in the report as an explicit manual
  step. Never imply it was done.

## Reading positions correctly

- **`GetLeftOffset()` is in TIMELINE frames**, for 60 fps and 16 fps media
  alike. Source second = `GetLeftOffset() / timeline_fps`. Dividing by the
  media fps gives a map that is 2.5× wrong and looks plausible.
- `GetSourceStartFrame()` is sometimes 1 lower than the truth on conformed
  media; the `.drt`'s `<In>` is exact.
- Re-applying `GetSourceStart/EndFrame` of an item on a 29.97→24 conform gives
  an item 1 frame short or shifted. Rebuild in a loop: append, compare
  `GetLeftOffset`/`GetDuration` with the original, nudge in/out by ±1 source
  frame, repeat (converges in ~3 passes).

### Re-mapping source time to a timeline that was edited since

```python
F = float(p.GetSetting("timelineFrameRate"))
items = [(it.GetStart(), it.GetDuration(), it.GetLeftOffset())
         for it in rv.track_items(tl, "video", 1)]
def frame_of(src_s):
    for start, dur, lo in items:
        s0 = lo / F
        if s0 <= src_s < s0 + dur / F:
            return start + round((src_s - s0) * F)
    return None       # the editor removed that speech — worth reporting
```

Validate on a word before the first edit: delta 0 there, negative after.

## Grades, stills, bins

- **`src_item.CopyGrades([targets])` works across timelines** (make the source
  timeline current). Check with `GetNodeGraph().GetToolsInNode(k)`. Run it
  **after** the layout is built, or duplicated tracks come out ungraded.
- `GrabStill` captures one step late; `ExportStills(..., "drx")` returned False
  everywhere tried. Do not go down that path; copy grades item to item.
- An in-session render of a comp written by script can come out static even
  when it animates. Do not claim anything about animation from it.
- `MediaPool.MoveFolders()` works directly; the MCP's `move_folders` returns
  success and moves nothing. Re-list the tree after any move.

## Redoing a cut already applied `--mode in-place`

Running it again duplicates the **already cut** timeline over the backup. The
order that preserves the original: duplicate the `· pre rough-cut` backup →
delete the cut timeline → rename the copy to the original name → delete the old
backup → apply again. Ask before any of it.

## Media and environment traps

- **A vertical clip without a rotation flag lies down** while its siblings are
  auto-rotated. Fix on the item: `RotationAngle -90` (anticlockwise) and, in a
  `scaleToFit` vertical project, `ZoomX/ZoomY 1.7778`. In ffmpeg it is
  `transpose=2`, not `1`.
- The Resolve venv may run with an ASCII default encoding: `open(p, encoding="utf-8")`
  for every JSON with accents.
- `ffmpeg -ss` **before** `-i` seeks to a keyframe; audio can start seconds off.
  For any check that compares content, put `-ss` **after** `-i`.
- `find -name "Cam[A-1]_0042.MP4"` matches nothing: brackets are a glob class.
  Use `-name "*_0042.MP4"`.
- The Python process may segfault on teardown after a successful run; if
  `SaveProject()` already returned True, the state is saved.

## Reference

- `reference/drt-clone.md` — cloning titles and any other item by editing the
  `.drt` XML; the field meanings and a tested round-trip.
- `scripts/rv.py` — connection, project guard, timeline lookup, snapshot, save.

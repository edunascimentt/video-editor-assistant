# Resolve API facts this pipeline rests on

> Acoustic tuning lessons from the live validation are in
> `cut-rules-ptbr.md` § *Measuring silence*.

All of these are verified upstream in `davinci-resolve-mcp`
(`resolve_control{action:"api_truth"}` and `timeline{action:"edit_kernel_capabilities"}`),
not inferred. Breaking any of them produces a *plausible but wrong* timeline,
which is the expensive failure mode.

## There is no razor

> `razor_or_partial_lift`: "Resolve's public scripting API does not expose a
> direct timeline split/razor primitive; partial range edits are represented by
> append-based copies or whole-item deletes."
> — `timeline{action:"edit_kernel_capabilities"}`

Consequences:

- `timeline.lift_range`, `timeline.delete_clips` and `timeline.apply_cuts`
  delete **whole timeline items**. On a single-take timeline, one mid-clip cut
  deletes the entire take. `lift_range` at least refuses unless you pass
  `allow_partial_item_delete=true` — never pass it in a rough-cut context.
- The only frame-accurate route is re-assembly: `MediaPool.AppendToTimeline`
  with one clipInfo per keep range. `rc_apply.py` does exactly this;
  `timeline{action:"create_variant_from_ranges"}` is the MCP equivalent and takes
  the same shape (`ranges[]` of `clip_id`, SOURCE `start_frame`/`end_frame`,
  `track_type`, `track_index`, plus `pack:true`).
- **Re-assembly does not require a NEW timeline.** `Timeline.DeleteClips(items,
  False)` empties a timeline in place, keeping its settings and track layout, and
  `AppendToTimeline` then fills it at explicit `recordFrame`s. Verified live:
  2 items deleted, 0 remaining, tracks and all 157 settings unchanged, then
  3 clipInfos placed exactly where asked. That is what `--mode in-place` is.

## Only `DuplicateTimeline` reproduces a timeline's settings

`MediaPool.CreateEmptyTimeline(name)` builds from the **project's** settings. A
timeline with its own settings — the "Use Project Settings" box unchecked, which
is how a 24 fps sequence lives in a 30 fps project — comes back at the project's
rate instead, silently. Every source-frame conversion downstream is then wrong,
and the failure looks like drifting sync rather than a settings bug.

`Timeline.DuplicateTimeline(name)` copies them all. Measured live: 157 of 157
settings compare equal after a duplicate, and still equal after the copy has been
emptied and refilled. Both modes of `rc_apply.py` therefore duplicate first, and
both diff the settings afterwards and report any drift.

`GetSetting()` with no argument returns the whole map, which is what makes that
check a one-liner.

## Markers are relative, keep ranges are absolute

`Timeline.GetMarkers()` keys are frames **relative to the timeline start** (0 is
the first frame, whatever the start timecode says). The cut plan works in
absolute record seconds. Re-timing a marker means lifting it into that space
first (`(frame + timeline_start_frame) / fps`), mapping it through the keep
ranges, and emitting a relative frame again.

Use the MCP tool when the plan is small enough to pass through a tool call
comfortably; use `rc_apply.py` for a real rough cut, where 200–600 ranges would
otherwise be serialised through the conversation twice.

## `endFrame` is EXCLUSIVE

`AppendToTimeline` clipInfo `endFrame` is an exclusive bound: duration is
`endFrame - startFrame`, **not** `+ 1`. Verified by readback probe. Treat
`[startFrame, endFrame)` as half-open everywhere.

## Source frames are in the MEDIA's rate, never the timeline's

A WAV has no intrinsic frame rate, so it freezes the **project's** rate at
import — 24 only if the project was at 24 when the file was imported. Reading a
source offset at the timeline rate lands *minutes* away in the file and nothing
errors.

`rc_probe.py` therefore never computes source positions itself. It imports the
MCP server's own `_timeline_item_summary`, which:

- reads `source_fps` from the media-pool item's `FPS` clip property every time;
- reports `source_start_seconds` / `source_end_seconds` as **file-relative**
  seconds — the two second-readers (`GetSourceStartTime` / `GetSourceEndTime`)
  answer in the media's *timecode* space, so a camera clip with a time-of-day
  start TC gives a number ~44x its own length if you use it raw. The fix is to
  take the *span* between them, anchored on the file-relative
  `GetSourceStartFrame`; the offset cancels in the difference.
- blanks `source_fps` for an audio item whose offset came from `GetLeftOffset`
  (that one counts in *timeline* frames), so the pipeline refuses rather than
  converting confidently wrong.

Anything with a blank `source_fps`, a blank source span, a retime, or no file
path is excluded from the cut and reported. Do not try to rescue those
automatically — re-place them by hand.

## Mixed rates floor the placed duration

When the source rate differs from the timeline rate, Resolve converts the
source range to timeline frames by **flooring**, so a range planned to fill a
slot exactly lands one frame short and leaves a gap. `rc_apply.py` solves each
duration in timeline frames first, then back-solves the smallest source-frame
count that still fills it (`src_frames_for`). With matched rates this is the
identity, which is the common case.

After any assembly, confirm with `timeline{action:"detect_gaps_overlaps"}`.

## Other landmines in this project's MCP

- `media_pool{action:"move_folders"}` is a **silent no-op** — returns
  `success: true` and moves nothing (v2.98.2, Studio 21.0.0.48). Use
  `MediaPool.MoveFolders()` directly.
- `project_read{action:"timeline_clips"}` ignores `limit`; a 197-clip timeline
  returned 64 KB and blew the response ceiling. Another reason bulk reads go
  through `rc_probe.py`.
- Destructive live-server actions need two calls: the first returns a
  `confirm_token` with a 300 s TTL, the second executes.
- ResolveFX **Cinematic Focus** segfaults Resolve 21.0 on this machine as soon
  as a frame renders. Never open a project carrying it, and never add it.

## Working coordinates

| space | unit | who speaks it |
|---|---|---|
| file seconds | s from head of the media file | WhisperX, `source_*_seconds` |
| record seconds | s from head of the timeline | every cut decision in `cutplan.json` |
| source frames | file seconds x that media's own fps | `AppendToTimeline` only |

The mapping is linear per item and assumes speed 100% — which is why retimed
items are excluded rather than approximated:

```
record_seconds = item.start/timeline_fps + (file_seconds - item.source_start_seconds)
```

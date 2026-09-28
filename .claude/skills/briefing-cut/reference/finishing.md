# Finishing a short cut the way the editor finishes it

The instruction behind every finishing pass is literal: **"don't make anything
from scratch — copy what I put on the other cut."** A recreated Text+ that
looks similar is not a copy: her template carries animation, font, look and her
positioning. If the API refuses to copy something, route around the API (the
`.drt` clone in `resolve-scripting`), not around the instruction.

## Read her approved cut first

Open the video she finished or approved and inventory it with `rv.describe`
plus `GetProperty` on each item (Pan, Tilt, Zoom, CompositeMode, Opacity) and
the Fusion inputs of each title. That inventory is the spec. What was measured
on a real series:

| element | how she did it |
|---|---|
| **Word list** | words naming what is on screen pop one after another on V3, V4, V5…, each overlapping the previous by ~10 frames, a b-roll behind them |
| **Click** | the click clip on the audio at every word entry |
| **Flash** | the flash video with `CompositeMode 5` (Screen) **2 frames before the first word**, at section changes, and **once early** (first 2–3 s) as a hook |
| **Riser** | a riser SFX at the head, 96 frames, ending on the first hard cut |
| **Music bed** | its own track, ~−22 dB clip gain under speech (read from her `.drt`; the API returns no volume) |
| **Grade** | a camera look — Color Space Transform + a Rec.709 look LUT — on all footage of that camera |

## What she changed after my passes (so do it first time)

- **Words spelled out:** "13 MINUTOS", not "13 MIN".
- **Fewer pops.** Only words that name something the viewer is **seeing** right
  then (a list of ingredients over those ingredients). Technical terms spoken
  over unrelated picture were removed.
- **Early flash** as a hook, not only at section changes.
- **Riser at the head.**
- **Weak, far-off speech comes out**, with its subtitles — even when it is the
  only speech in the video. Barely audible is worse than none.
- Flashes moved to cuts that land on a strong picture change.

## Mechanics

- **Her Text+ templates are already in the media pool** (Fusion Titles, 24 fps,
  42 frames, with a `Follower`). `AppendToTimeline` with `startFrame 0,
  endFrame dur`, then set the text on the Follower
  (`comp.FindTool("Follower1").SetInput("Text", …)`) and
  `Template.SetInput("Size", …)`. Compared by `ExportFusionComp` + diff: identical
  to hers. Never `SetName` the item (freezes the comp).
- **Size by letter count:** her size was set for a given word length; scale
  `size = her_size * her_letters / letters` (0.2235 for 6 letters → 0.168 for 8).
  Then look — width is an estimate.
- **Line breaks** in the text (`"NOSSO\nPROCESSO"`) for two-line closers.
- **Grade:** `her_item.CopyGrades([targets])` with her timeline current; works
  across timelines. Verify with `GetNodeGraph().GetToolsInNode(k)`.
- **Animation:** do not judge it from an in-session render of a comp you just
  wrote — it can render static and still animate. Say it needs a look.

## Videos without speech

- **Process with little speech:** the speech first, then a picture sequence in
  brief order on V1 without audio. Subtitles only from A1 (`--track-kind audio`
  in the `subtitles` skill), since the picture clips have no transcript.
  Forced alignment fails on far, noisy speech — use checked text with the
  recogniser's word times there.
- **Event/"chamada" video, music only:** cut on the beat. At 90 bpm and 24 fps
  a beat is exactly 16 frames. Quiet intro = preparation shots, drop = the
  event, close on the widest, most beautiful shot under the two-line title.
- **Bed with an envelope** where speech gives way to picture: low under speech,
  ~0.6 s ramp up for the sequence — rendered into the file (`music-bed`).

## Checklist before "pronto"

- [ ] every word pop names something on screen, spelled out
- [ ] click at each entry, flash 2 frames before the first word, one early flash
- [ ] riser at the head ending on the first hard cut
- [ ] bed level vs measured speech, instrumental, licensed prefix
- [ ] grade copied to every clip of that camera, V2 included
- [ ] rotated clips fixed on every track
- [ ] subtitles rebuilt after the last picture change
- [ ] manual steps listed in the report (anything the API cannot set)

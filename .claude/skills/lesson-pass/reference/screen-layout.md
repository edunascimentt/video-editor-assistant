# Screen-recording lessons: sync, layout, finishing

For lessons where the presenter works in software while talking. The camera
file and the screen recording (often a meeting-app recording) are separate;
the edit shows the recording large with the presenter small beside it, going
back to full-screen face when the screen has nothing to show.

## 1. Match and sync the recording

Recordings arrive with names that say nothing (`<meeting>-<date>_<time>`).
Match each to its camera file by **audio**: the presenter's voice is on both.

```bash
MC="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/skills/multicam-switch/scripts"
$PY $MC/sync_offset.py match CAMERA.mp4 SCREEN/*.mp4      # 0.78–0.89 right one, 0.10–0.25 others
$PY $MC/sync_offset.py offset CAMERA.mp4 SCREEN/rec07.mp4  # SYNC: t_screen = t_camera + SYNC
```

Rename to `<LESSON> · TELA.mp4`, keep an untouched copy of the originals, and
write a `_SYNC.md` table (lesson ↔ camera file ↔ recording ↔ SYNC). Recording
start times (6–7 min before the camera) and durations confirm the pairing;
camera `creation_time` is UTC.

A lesson may have **no recording** (a slide lesson) or **speech about the screen
with no recording at that moment** — mark that stretch pink, do not invent picture.

## 2. The stack

Bottom to top, as the editor built it:

| track | content | geometry (one course's numbers — copy the latest approved lesson's) |
|---|---|---|
| V1 | the cut camera, full frame | covered while the layout is up |
| V2 | background still | `Pan` to taste; `CropBottom` if it shows a seam |
| V3 | the **same camera cut, duplicated** — presenter small on the right | `Pan 446…595` |
| V4 | the screen recording | `Zoom 0.83 · Pan −180…−222`, **crop left/right only** |
| V5 | intro container comp; the transition flash | — |
| V6 | explanation cards | — |
| A4 | intro container SFX in/out | — |
| A5 | the transition click | — |

The recording's geometry depends on the recording, not the course: measure the
software window's x-range on a frame (column profile) for each recording
batch. One day's recordings had the window at x=8–1644; the next day's at
x=22–1651 plus a meeting-app camera bubble at x=1733–1872. The editor's crop
goes ~48 px *inside* the window on each side — framing the content, not just
removing the frame. **Crop is left/right only**; top/bottom crops were mine,
not hers.

**Always copy the numbers from the last lesson she closed**, not from this
file and not from a lesson she later discarded — she refines per lesson
(transition zoom 1.87 → 1.91 → 2.01; pan −180 vs −184).

## 3. Building the layout

- Each V1 keep range becomes one block on V3 (camera) and V4 (recording,
  `startFrame = round((camera_s + SYNC) * rec_fps)` — recordings may be 16 fps;
  ±1 frame is invisible on a still screen).
- **The background still always lands as 120 frames.** Tile it in 120-frame
  blocks aligned from the end: `start = end − ceil((end − target)/120)*120`,
  then cut the first keep range to match. Use **ceil**, so the layout starts
  before the moment the screen matters — but check the result lands after the
  intro container ends; if not, take the next multiple down.
- One `AppendToTimeline` call handles ~3,600 items.
- **Layout does not run to the end.** When the presenter leaves the screen and
  talks to camera for the close, return to full frame 20–25 s before the end.
- **Screen idle = back to the face.** Open a gap in the layout, with a second
  transition, wherever the software is loading/processing. The trigger is
  speech, not picture: "processar", "carregar", "atualizar", "demora",
  "aguarda". A lesson with none of these keeps a continuous layout.
- The layout also starts late: ~28 s of full-frame head before shrinking.

## 4. Transition and container

- The **transition** is the click/flash clip stretched to cover the frame
  (`Zoom ~1.8–2.1`) with **`CompositeMode 5` (Screen)**, 3 frames before the
  layout starts, on V5, with its click on **A5**.
- The **intro container** stays **`CompositeMode 0` (Normal)**. (I had this
  exactly backwards once: Screen on the container, nothing on the transition.)
- A Fusion comp already on a timeline returns `None` from `GetMediaPoolItem()`;
  find the container template in the pool by id to place it.
- SFX `endFrame`s are in each file's own fps (a 60 fps SFX of 32 timeline
  frames needs `endFrame 81`).

## 5. Finishing checklist — every item was once redone by hand

- [ ] recording **cropped** (left/right), copied from the last approved lesson
- [ ] transition in **Screen**, zoom covering the frame; container **Normal**
- [ ] **colour**: the camera grade (a 5-node still: CST · HSL mix · primary
      balance · HDR · camera LUT) copied with `CopyGrades` from a graded clip of
      another lesson onto **every** camera item, **V3 duplicate included** —
      after the layout is built
- [ ] intro music **volume** — no API; listed as a manual step
- [ ] text: cards + step markers, no punch words over the layout
- [ ] every spoken number checked against the recording frame
- [ ] transcript read for retakes **and for repeated ideas** (see
      `reading-for-cuts.md`) — the analyser alone never sufficed for a
      re-take-heavy presenter, screen lessons included
- [ ] zooms: two fixed on the full-frame head + one Cyan marker
- [ ] tail in full frame; idle gaps back to the face
- [ ] what the API cannot do is in the report as pending, explicitly

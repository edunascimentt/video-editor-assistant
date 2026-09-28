---
name: lesson-pass
description: The complete pass on one course lesson in DaVinci Resolve, end to end and in order — rough cut with the judgement the analyser cannot make (burned openings, abandoned takes, repeated ideas), intro restored, on-screen text, zooms, screen-recording layout when the lesson has one, finishing checklist, and the report the editor actually reads (pink markers and refused decisions). Use when the user asks for "a aula N", "faz a próxima aula", "passada completa", "seguindo tudo que já fizemos", "edição completa" of a lesson/episode/module, or hands over a timeline of a talking-head lesson with or without a screen recording.
---

# Full pass on a lesson

The request is usually one line — *"do lesson N, following everything we did"*.
The procedure behind it is long, and each stage has a silent failure mode: a
plausible, wrong timeline; an intro destroyed by the rebuild; text 155 frames
off its word; a cut that still says the same thing three times. Run the stages
**in order** — stage 2 depends on the origin fixed in 1, stage 3 on both.

This skill orchestrates the others. Load them as you reach them:
`rough-cut` (1), `resolve-scripting` (2, 4, 6), `on-screen-text` (3),
`subtitles` (if the course has them), `multicam-switch` (if there are angles).

```bash
LP="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/skills/lesson-pass/scripts"
```

## 0. Before touching anything

- **Read the timeline as it is now.** Editors work between requests: clips move,
  a lesson gains its intro, durations shift by a few frames. Frames saved from a
  previous pass are stale — re-map (see `resolve-scripting`).
- **Ask the scope before any cascade.** Renumbering lessons or touching sibling
  timelines reaches into work the editor has already closed. One line to ask
  costs less than undoing.
- **What kind of lesson is it?** Slides only (talking head), or with a screen
  recording (software on screen)? Speech rate tells you before watching:
  110–120 words/min expository, 85–100 live build, ~70 installing/downloading
  (that one will shrink the most). Screen lessons add stage 6.
- **Is it a lesson at all?** A raw file where the presenter stops on camera
  ("let's cancel this one and start again"), has no closing, and whose content
  the **next** file covers in full is a discarded take. The next lesson's "in
  the previous lesson…" tells you the real chain. If asked to build it anyway,
  flag it in one sentence and build it — do not stop and wait.

## 1. Rough cut

`rough-cut` skill, with these lesson-specific parts:

**Park the intro first.** If the editor already built the vinheta and lower
third, the rebuild would destroy them. Move them out of `timeline.json` into
`intro_items_preserved.json`, save their transforms (`GetProperty` of Pan, Tilt,
ZoomX/Y, Crop*) in `intro_items_state.json`, and set `timeline_start_frame` to
where the presenter's V1 starts (155–158 under a 165-frame vinheta).

**Tuning:** start from defaults. If the verify flags sibilant or silence
splices on this microphone, what fixed one course's mic was
`--tail-ms 520 --tail-ms-sibilant 800 --head-ms 320 --hi-margin-db-sibilant 3.5`
(a looser variant made it worse: 44 flagged vs 32). Once a mic's tuning is
found, keep it for the whole course.

**Judge.** Run the analyser, then the audit, then read the whole transcript:

```bash
python3 $LP/lesson_audit.py "$WORK" > "$WORK/audit.md"
```

It lists restart cues said out loud, every opening (more than one = burned
openings), repeated 4-word phrases, stretched tokens, pauses announced by the
speaker, sentences left starting lowercase, and every auto-tier word removal.
It proposes nothing; it points. `reference/reading-for-cuts.md` has the rules
that decide each case. The ones that matter most:

- **Two kinds of presenter.** A fluent one: 12–13% removed, 60–70% of the
  analyser's word proposals switched **off**, a handful of manual retakes.
  A re-take-heavy one (re-reads the same sentence 4–13 times): 30–75% removed,
  almost all from manual `add`s — keep the **last complete take**, cut the
  earlier ones whole. The analyser alone will not get there; budget the time
  for reading.
- **Repeated idea, not just repeated words.** The same claim said three or four
  times in different words survives every detector. Count how many times each
  assertion appears in the cut text.
- **Abandoned take that carries unique content** (a name, a definition said
  only there) → pink marker, not a rescue.
- **After a large `add`, re-read the preview around it**: removing an abandoned
  take can leave two sentences announcing the same thing back to back — extend
  the removal to swallow the re-opening.

**Accept only with:** 0 clipped words, similarity ≥ 97.5%, a read of the
whole cut transcript. Two report artefacts that are not defects: the
`readback … delta 155` of `rc_apply` (append origin vs a plan starting at 0),
and "clipped word" on a word whose `t1` is aligner padding — measure the energy
envelope at 20 ms; if the cut lands after the real end of speech, it is fine.

**Known bug:** `rc_apply --markers` does not add `timeline_start_frame` to its
review markers — with the V1 at 155 they land 155 frames early. Re-place them
with `+origin` (or skip `--markers` and place your own).

**Redoing a cut** already applied in place: see `resolve-scripting` for the
order that keeps the real backup.

## 2. Restore the intro

`AppendToTimeline` the parked items at their old `recordFrame`, then re-apply
the saved transforms with `SetProperty` (they do not survive). `endFrame` is
exclusive and in the media's fps. Save with `pm.SaveProject()` in a separate
call. Compare against the previous lesson's intro item by item.

## 3. On-screen text

`on-screen-text` skill. **The frames in its `transcript.md` are relative to the
cut audio: add `timeline_start_frame` to every one** before writing
`plan.json`. This was missed on three lessons (text 6.5 s early). Before
applying, prove one item against the audio: the word's frame from the
`append_infos.json` map (record frame ↔ source second) must match the plan.

Density that the editor kept:

| lesson | words (V6, punch pair, click on A2 2 frames before) | explanation cards (V3, 193f) | blue markers |
|---|---|---|---|
| slide lesson, ~8–12 min | 3–7 | 1–3 | one per slide change |
| screen lesson | **none** over the layout (screen-left is where the recording is); at most one during the full-screen intro | 2–3, over the layout | one per build step — also the natural split points |

- In screen lessons **the slides are already inside the recording**: a blue
  marker there is a step, not a request for art.
- **Every number the presenter says** in a screen lesson: check the recording
  at that moment (`media second + sync` → `ffmpeg -ss <t> -frames:v 1`) before
  it becomes a graphic. Real catches: a count said aloud ~30% off the card on
  screen, and a percentage read out as a count.
- `ost_apply --clear` also deletes the Cyan dynamic-zoom markers, and the next
  apply validates against the **old** `context.json`: after a clear, re-run
  `ost_probe` and put the Cyan markers back.

## 4. Zooms

Slide lessons: in the **first ~2 minutes only**, alternate **6 static zooms**
on V1 items (`ZoomX/Y 1.06–1.13`, `Tilt` always negative −12 to −45, only on
items ≥ 72 frames or the zoom does not read) with **6 Cyan markers** carrying
the duration of each dynamic-zoom adjustment clip the editor will drag in —
the API cannot create those. Screen lessons: two fixed zooms on V1 during the
full-screen head and one Cyan marker.

## 5. Screen-recording layout (screen lessons only)

`reference/screen-layout.md`: syncing the recording by audio, the track stack,
geometry, the 120-frame still trap, the transition, "screen idle = back to the
face", colour, and the checklist the editor had to redo by hand when it was
skipped.

## 6. Report

What the editor reads, in this order:

1. Numbers: before → after, % removed, clipped words, similarity, verify result.
2. **The pink markers**, each with frame and why: speaker slips that a slide
   must not copy (wrong word, contradicting the case, inverted numbers), the
   interviewer speaking off frame, sensitive mentions, content lost with an
   abandoned take, holes in the image (speech about a screen that was not
   recorded).
3. **The decisions I refused**, with the reason (a retake with 20 ms of
   clearance; a whip transition I did not place).
4. **Manual steps left**: intro music volume, dynamic zooms (Cyan), anything
   the API does not expose. Never imply they were done.

**Not by default:** the whip transition (it goes where the editor *felt* the
jump, not at a structural point — placing it wrong is worse than missing), and
lesson titles. When asked for a title: container card, ALL CAPS, a short topic
label in 2–3 lines, no subtitle, sometimes a question; long explanatory
sentences do not fit. Do not write it into a marker without being asked.

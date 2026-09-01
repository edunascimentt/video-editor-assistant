---
name: on-screen-text
description: Marks up a DaVinci Resolve lesson timeline and builds its on-screen text — colored markers for where the slides belong, the keywords worth popping on screen, and the acronyms/jargon that need a definition card; then places the project's own Text+ and explanation-card Fusion templates at those points, with the click SFX. Use when the user wants a course lesson, VSL or talking-head timeline made more dynamic, asks where to put the slides, wants "palavras na tela" / GCs / lower thirds, or wants hard words explained on screen.
---

# On-screen text for a lesson timeline

Takes a cut talking-head timeline and returns two things: a **map** — colored
markers saying where the slides go, which words deserve the screen, which terms
need explaining, and what needs a human decision — and the **build**, the
project's own Fusion templates placed at those points with the right text,
position, duration and click.

Everything lands on tracks **above V1**. The talking head is never touched.

## Division of labour — read this first

| The scripts decide | You decide |
|---|---|
| The source/timeline **fps conversion** for every clip | **Which** words earn the screen |
| Overlap and marker-collision checks | Where a slide starts and ends |
| Screen position, click offset, name, readback | What a term actually means, in this lesson's register |
| What actually landed, proven by re-reading it | Which of the speaker's slips need flagging |

Do not hand-place titles through the MCP tools. Each `append_to_timeline` call
returns a full-timeline readback — on a 400-item timeline that is ~15k tokens
per call, and you will run out of context long before you run out of words.

## Prerequisites

- DaVinci Resolve Studio **running**, the lesson's project open.
- A word-level transcript **in timeline time**. The rough-cut skill leaves one
  at `~/.cache/rough-cut/<project>/<timeline>/verify/words/cut.json`; that is
  what `ost_probe.py` looks for. Without it, stop — see *Hard constraints*.
- The project's two Fusion templates and the click in the media pool. See
  `reference/vfx-templates.md`.

```bash
OST="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/skills/on-screen-text/scripts"
RESOLVE_MCP_HOME="${RESOLVE_MCP_HOME:-$HOME/Repositories/davinci-resolve-mcp}"
PY="$RESOLVE_MCP_HOME/venv/bin/python"
export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
export RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
export PYTHONPATH="$RESOLVE_SCRIPT_API/Modules"
```

## Pipeline

### 1. Probe

```bash
$PY $OST/ost_probe.py --timeline "AULA 02"
```

**Always pass `--timeline`.** The default is whatever is current in Resolve,
and reading another timeline for reference (which you will do) changes that
under you — a stale `context.json` is how a run ends up half-applied.

Prints the timeline, its fps, its tracks, its existing markers, the three
templates and the transcript it found. Writes `context.json` and
`transcript.md` into a work dir; take the path from the script's last line:

```bash
WORK=~/.cache/on-screen-text/<project-slug>/<timeline-slug>
```

If a template prints `UNRESOLVED`, the folder holds several candidates and the
script refuses to guess — nothing in a media pool item says whether a Fusion
Composition contains text nodes, and the wrong pick silently places an unrelated
transition. Pin it once per project:

```bash
$PY $OST/ost_probe.py --timeline "…" --set-template word=<id> --set-template explain=<id>
```

### 2. Read the lesson

Read `transcript.md` end to end. It is one line per spoken sentence with its
timeline frame. This is the whole job — everything after it is typing.

For exact word-level frames (a keyword must pop **on** its word, not near it):

```bash
$PY $OST/ost_probe.py --timeline "…" --find "turnover,ROI,MIT,espelhos"
```

### 3. Judge — the part only you can do

Four things to find. `reference/what-to-mark.md` has the full rules; the short
version:

- **Slides** — a stretch where the speaker is talking *to* something: a
  statistic, a list enumerated aloud, a comparison, a recap. The verbal cues for
  a slide change are "vamos em frente", "vamos seguir em frente", "bora", "olha
  só", "trazendo o último dado".
- **Words** — one uppercase word at the emotional peak of a sentence. Look at
  what the speaker repeats and raises their voice for, not at what sounds
  important on the page.
- **Terms** — acronyms and jargon a non-specialist viewer would stall on. Write
  the definition **in the note**, ready to use, three lines of ~60 characters.
- **Review** — the speaker corrected themselves on air, broke the fourth wall,
  or said something factually inverted. Flag it; do not build a graphic on top
  of an error.

**Match the edit's density, not your enthusiasm.** A finished 8-minute lesson
in this project carries roughly 3 words and 2 explanation cards. Ten words in nine minutes is
already generous; twenty is a different show.

Write `$WORK/plan.json`:

```json
{
  "timeline": "AULA 02",
  "sfx_track": 2,
  "markers": [
    {"kind": "slide", "frame": 3324, "duration": 384,
     "name": "SLIDE 06 · DADO 10,4x", "note": "número gigante, fonte MIT no rodapé"},
    {"kind": "word",   "frame": 3362, "name": "10,4x"},
    {"kind": "term",   "frame": 7178, "name": "TURNOVER", "note": "rotatividade…"},
    {"kind": "review", "frame": 7238, "name": "ROI usado invertido"}
  ],
  "items": [
    {"kind": "word", "frame": 3362, "duration": 104, "track": 3, "text": "10,4x"},
    {"kind": "word", "frame": 3619, "duration": 104, "track": 2, "text": "REMUNERAÇÃO"},
    {"kind": "explain", "frame": 7178, "duration": 193, "track": 3,
     "term": "TURNOVER",
     "definition": "Rotatividade de pessoal: proporção de funcionários que saem e\nprecisam ser repostos num período. Turnover alto significa custo\nde desligamento, recrutamento e treinamento."}
  ]
}
```

`frame` is a **timeline** frame, `duration` is in **timeline** frames — the
script converts to source frames itself, and that conversion is not the obvious
one (see *Hard constraints*). Defaults worth knowing: **word 126 frames**, which
`ost_apply` splits into the punch pair (41 entrance + 85 hold) by itself; card
193; `size` auto-fitted from the text; position screen-left; one click per word;
and **the template's animation left exactly as authored**. Optional per item:
`size`, `pan`, `tilt`, `zoom`, `sfx: false`, `clip_id`.

Show the user the marker list and the word list **before applying**. This is
the cheap moment to disagree.

### 4. Apply

```bash
$PY $OST/ost_apply.py --work-dir "$WORK" --dry-run     # always
$PY $OST/ost_apply.py --work-dir "$WORK" --markers-only
$PY $OST/ost_apply.py --work-dir "$WORK"
```

The dry run validates without touching Resolve, and the errors are the ones
that actually bite: two items overlapping on one track (Resolve would shift one
silently), a marker on a frame that already holds one (Resolve refuses the
second), a definition too long for the card, a title aimed at V1.

A real run adds the tracks it needs, places markers, places titles, sets their
text and transform, places the clicks, then **reads the timeline back** and
prints `verify OK` or the exact items that did not take. It saves the project.

To undo everything this pass placed:

```bash
$PY $OST/ost_apply.py --work-dir "$WORK" --clear
```

`--clear` finds its own work by name prefix (`PALAVRA · `, `EXPL · `) and by
namespaced marker `customData` (`ost:*`), so it cannot touch your own titles or
the rough-cut skill's leftover markers.

### 5. Look at it

The one thing no readback can tell you: **whether the words fit**. Text+ has no
auto-fit, this pass cannot render a frame, and the size it computes is a width
estimate normalised off one measured word. Open the viewer, scrub the marked
frames, and expect to nudge `size` on the long ones. Say so to the user rather
than implying the sizes are final.

## Hard constraints

- **Never place a title from a timecode nobody measured.** Word times come from
  WhisperX word-level output. Segment-level subtitles are far too coarse — a
  keyword landing 400 ms off its word reads as a mistake, not a beat.
- **The fps of the template is not the fps of the timeline.** `AppendToTimeline`
  counts `startFrame`/`endFrame` in the MEDIA's own rate. The explanation card is
  24 fps and maps 1:1; the old 60 fps Text+ does not — asking for `endFrame: 104`
  on a 24 fps timeline yields **41 frames**, not 105, and it fails silently.
  `duration` in the plan is always timeline frames and `source_range_for` does
  the conversion. The word template pinned now (`Master/Assets` › Text+) is 24 fps,
  so the punch pair is 1:1 — but never assume that of a template you did not check.
- **Screen position is an Edit-page move, not a Fusion one.** Every one of his
  Text+ comps sits at Fusion Center 0.5,0.5; the word gets to screen-left through
  the timeline item's Transform (`Pan -514`, `Tilt 130`). Setting the Fusion
  Center instead puts the animation path in the wrong place.
- **Never call `SetName` on an item carrying a Fusion comp.** It FREEZES the
  comp — the follower stops advancing and the word renders at full opacity from
  its first frame. Verified by A/B on one clip. Placed items are identified by
  the ids in `applied.json`, never by a name this pass wrote.
- **A word is placed as a punch pair from the 24 fps Text+ in `Master/Assets`.**
  `ost_apply` does this for you now — one plan item, two clips on the timeline —
  42 frames @ 24 fps, straight from the pool, no `ImportFusionComp`: an
  entrance of 41f (`startFrame` 0 → `endFrame` 41) plus a hold of ~85f
  (`startFrame` 41 → `endFrame` 126), same text and `Size` on both. That is the
  shape approved as animating (2026-08-21, AULA 03; used again on AULA 04); the
  60 fps Text+ placed as one 104f clip renders static. Full detail and the two
  measurement traps
  (`GrabStill` lags; an in-session render of a freshly scripted comp lies) are
  in `reference/vfx-templates.md`.
- **Do not touch the template's animation.** Retiming the splines to fit the clip
  is the obvious fix and it was rejected after seeing it render. The punch pair
  needs none of it: the entrance plays the animation, the hold parks
  on its last frame.
- **Every word is announced by a click**, `Burnin Click.mp4` on A2, starting
  **two frames before** the title. A word without it does not read as part of
  the same edit.
- **Resolve holds one marker per frame.** A second `AddMarker` on an occupied
  frame returns False and vanishes. The rough-cut skill leaves its own markers
  behind, so collisions are normal — nudge a frame rather than deleting his.
- **Do not hand-place through the MCP tools.** See *Division of labour*.
- **This pass only adds.** No cuts, no reframing of V1, no colour, no slide
  images — it marks where a slide belongs and leaves building it to a human.

## Reference

- `reference/vfx-templates.md` — the two Fusion templates and the click: where
  they live, which node holds which text, the measured layout numbers, and the
  fps arithmetic.
- `reference/what-to-mark.md` — the marker legend, what earns a slide / a word /
  a definition card, and the pt-BR traps in deciding.

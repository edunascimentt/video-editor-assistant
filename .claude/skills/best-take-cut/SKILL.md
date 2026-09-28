---
name: best-take-cut
description: Cuts a prompted/scripted take where every line was read several times — keeps the best (usually the last complete) read of each script line, throws away the off-camera voice that fed the lines, and only then lets rough-cut polish. Identifies the speaker by mouth motion (audio level cannot separate them), finds each script in a long day by its spoken slate, and verifies every span by re-transcribing it alone. Use when the user says "só a melhor tomada", "pega a última leitura de cada frase", "tira quem está no backstage falando", when a long take is the same lines repeated, or for teleprompter/sermon/VSL recordings that come as one take per script.
---

# Best read per line

`rough-cut` removes air and filler — on a prompted take that is ~1.5%. What
turns 13:36 of repeated reads into 1:45 is choosing, line by line, **which read
stays**. That is this skill. `rough-cut` runs afterwards, lightly.

```bash
BT="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/skills/best-take-cut/scripts"
BC="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/skills/briefing-cut/scripts"
PY="${RESOLVE_MCP_HOME:-$HOME/Repositories/davinci-resolve-mcp}/venv/bin/python"
```

## Four timelines, one job each

| timeline | content | why separate |
|---|---|---|
| `<SCRIPT> - BRUTO` | the main-audio camera's file, whole | what `rc_probe`/`rc_transcribe` read |
| `<SCRIPT> - SELECT` | one span per script line, in script order | your choice, rebuildable |
| `<SCRIPT> - SELECT ROUGH` | `rough-cut` over the SELECT | polish only |
| `<SCRIPT> - MONTAGEM` / final name | angles, subtitles, finishing | delivery |

Keep intermediate timelines in a *temps* bin and only the finished one in the
*prontas* bin, if the project has that convention (ask once).

## 1. Find the script in the day's footage

A shoot day is often one long file per script with the speaker **saying a
slate** at the start ("Roteiro 2, <title>"). Transcribe the first ~3 min of
each file from the main-audio camera and read the slates. The other cameras
match by audio (see `multicam-switch`), not by name or duration.

## 2. Transcribe the BRUTO

`rc_probe` + `rc_transcribe` from the `rough-cut` skill on the BRUTO timeline.
Note where the transcript is **silent**: WhisperX sometimes transcribes nothing
over a stretch that has speech. A good read that sits in such a hole is
invisible to the selection, and "the last complete read" then picks the
off-camera voice — the only one the cache saw. List the holes (> 3 s without
tokens while the audio is above room tone) and re-transcribe them before
choosing.

## 3. Who is speaking — measure the mouth, not the level

Level does not separate an off-camera prompter from the speaker (both measured
51–72 dB); inter-camera level differences group loud/quiet, not person. The
mouth does.

```bash
# find the mouth box on the FRONTAL camera — check three frames spread across the take
$PY $BT/mouth_motion.py box FRONTAL.mp4 --crop 460:240:1620:760 --at 60,400,800 -o /tmp/box
# then label each transcript segment
$PY $BT/mouth_motion.py measure FRONTAL.mp4 --crop 460:240:1620:760 --segments segs.json > labeled.json
```

The distribution must come out **bimodal** (real: speaker 1.8–6.5, prompter
0.2–1.2). A continuous spread means the box missed the mouth for part of the
take — the head moves; redraw it from frames across the whole take. Confirm by
eye: in low-motion segments the mouth is closed in every frame.

## 4. Choose one read per line

Line up the script (from the client's document, or reconstructed from the
reads) against the `on` segments. For each line keep **the best complete read —
usually the last**, unless a later one is broken. Everything else goes,
including every `off` segment.

## 5. Edges

```bash
$PY $BC/span_edges.py spans.json > spans.edges.json
```

Walks from inside the first/last word to 120 ms of sustained silence, then pads
0.20 s head / 0.32 s tail — which also fixes the stretched token (a closing word
measured 3.1 s long). Read every `check` note.

## 6. Verify every span — alone

Cut each span with ffmpeg (`-ss` **after** `-i`: before it seeks to a keyframe
and audio can start seconds late) and transcribe **each one separately**,
comparing with the expected line. Transcribing the joined file hides problems:
the recogniser swallows what comes after a long window. Real miss: a span that
read clean as a whole held two reads — the first dies half-way, the good one
starts 4 s in — and only transcribing its **tail alone** showed it. Check in
short, disjoint windows.

When a span comes back wrong, re-transcribe a **wide** window around it and
trust that over the cache — the cache was 4 s off in one stretch.

## 7. SELECT → SELECT ROUGH

Build SELECT by duplicating BRUTO, emptying it and appending one span per line
(`AppendToTimeline` **without** `mediaType`, or you get video only). Then
`rough-cut` on SELECT, with two adjustments:

- Items are too short to measure room tone; the analyser falls back to a global
  guess (was 19 dB wrong) and refuses the good pauses. Expect only 0.1–0.3 s
  trims.
- Any removal that lands **mid-sentence** splits an item: a jump cut inside a
  line **and** a broken subtitle (a cue cannot cross a cut). Switch those off in
  `decisions.json`; keep only removals at span edges.

`rc_verify` may rebuild `cut.wav` wrong on a SELECT (40 s of a 105 s cut) — its
similarity and acoustic table are then garbage; only `clipped words: 0` counts.
Rebuild the audio yourself from the items' `GetLeftOffset` and transcribe in
30 s blocks.

## 8. Subtitles

Before building them, **patch the word cache** for every span whose timing you
corrected (remove overlapping words, insert the re-transcribed ones with the
offset added) — otherwise that line lands on the timeline with no subtitle, and
`sub_verify` reports a hole. Then the `subtitles` skill. Short-card styles
(e.g. 15 characters) need `--max-chars 15 --min-chars 6` plus a re-split of
cards over 20 characters using the skill's own `Lexicon`, keeping "leave it
wide" (k=1) among the options.

## 9. Angles and zooms

`multicam-switch` for the other cameras. If a previous script of the same
series has static punch-ins, copy those numbers per camera.

## Report

Lines in the script vs spans kept, runtime before/after, how the speaker was
identified (the split value and both ranges), every span that failed its solo
check and what fixed it, and any proper noun the recognisers disagree on —
marked pink as "CONFERIR NOME" rather than guessed.

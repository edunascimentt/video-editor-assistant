---
name: podcast-cuts
description: Turns a long podcast/interview recording into the numbered cuts on a client's list — finds the real in and out of each cut from content (the list's timecodes are approximate), trims only silence the way the editor does (no word removal), reproduces her per-cut package (intro animation, lower-third blocks, outro) by cloning her items through a .drt, screens the raw for material that must never go public, and verifies each cut by rebuilding and re-transcribing its audio. Use when the user sends a cut list ("corte 1: [02:46] até [09:48]"), asks for "os cortes do podcast", "faz igual o corte 1", "tira só as pausas", or wants episodes/clips cut from one long recording in Resolve.
---

# Cuts from a podcast recording

One long recording (often 60+ min, 60 fps), a list of cuts with rough
timecodes, and a first cut the editor already made by hand. The job is to make
the rest exactly like hers.

Load `rough-cut` and `resolve-scripting` (its `drt-clone.md`) as you go.

## 1. Screen the raw before anything else

Transcribe the whole recording and read it. Recordings made "while the camera
was rolling" can contain a **closed business conversation**: prices and
negotiation numbers, a third party named and accused, a partner saying they
would sell the company. Nothing in the file name warns you, and publishing
any of it is irreversible harm.

- Write down the sensitive windows. Treat those stretches (or the whole file)
  as **mute picture** — usable as b-roll of people talking, never with audio.
- Say it to the user in the first reply, before any cut exists.
- The same applies to crew talk at the end ("thanks for coming, [name]"): a
  goodbye naming the videomaker under a correct picture passes every visual
  check. Only re-transcribing the cut's audio catches it (step 6).

## 2. Find each cut's real in and out

The list's timecodes are **pointers**. On the first cut the list said
02:46→09:48 and the editor cut 03:12→12:54: in on the episode's opening line,
out at the end of a conclusive answer three minutes past the mark.

For each cut: transcribe ±40 s around both marks, read, and choose sentence
boundaries — **in** on the line that opens the topic, **out** at the end of the
guest's answer, **before** the next question. Report the times you chose next
to the list's.

## 3. Measure her style from her cut

Read her first cut's V1 items (source in/out) and measure the removed spans
between them: RMS of each removed span, silence left before/after each splice,
share of each silence run removed, splices per second. On the measured podcast:

| measure | her cut |
|---|---|
| RMS of every removed span | all below −49 dB → **she removes only silence, never a word** |
| silence left before / after a splice | 0.115 s / 0.110 s |
| share of each silence run removed | 66% |
| splices per second of material | ~0.30 |

## 4. Rough cut, silence only

`rough-cut` on the cut's range with every word kind switched off
(`filler`, `false_start`, `hesitation`, `retake` → all ids in `decisions.json`
`off`), and the tuning that reproduced her hand (the default removes 12% where
she removes 17%):

```
--bb-margin-db 18 --hi-margin-db 18 --min-pause 0.10 \
--pause-residual-tail 0.05 --pause-residual-head 0.05 --silence-guard-db 25
```

`--tail-ms`/`--head-ms` barely matter here; the gate margins and the residuals
decide. The verify then flags ~35% of splices for edge energy — **not a
defect**: her own cut scores 21% on the same test. The number that must be 0 is
**clipped words**. Compare your stats with her table above.

## 5. Her package, cloned

Inventory her first cut on the main timeline (where the cuts are assembled in
front of the raw). On the measured project:

| where | what |
|---|---|
| V2/A2 from 0 | the intro animation (~1100 frames) |
| V1/A1 | the talking heads, **entering under the intro** (~70 frames before it ends) |
| V3, ~40 frames before the end | the outro animation |
| V2–V6 | lower thirds in **blocks of 4** — one name title + three in a second template at offsets +0/+473/+481/+490, each on its own track — one block at the open, ~5 through the body, plus single titles for each person's first appearance |

The lower thirds are Fusion titles from another project: the API cannot copy
or insert them. **Clone her items through the `.drt`** (`resolve-scripting` →
`reference/drt-clone.md`) — do not rebuild look-alikes. If her body blocks
still carry the template's placeholder text, replicate them as they are and say
the text is to be edited (she confirmed that is the intent).

The import creates a new timeline: rename hers to a backup, give the new one
her name, and compare signatures before deleting anything. Media from another
editor's machine (Windows paths) stays offline until relinked — list it.

## 6. Verify

- `rc_verify`: clipped words 0.
- **Rebuild the cut's audio** from the items (`GetLeftOffset`, durations) with
  ffmpeg and transcribe it end to end: first and last sentence are the ones you
  chose, no crew talk, nothing from the sensitive windows.
- Titles: every block on the right tracks at the right offsets from the cut's
  start; nothing overlapping the outro.

## Report

Per cut: list times vs chosen times and why, runtime, splices and % removed vs
her reference, clipped words, package placed (and what still has placeholder
text), offline media, and the sensitive windows kept out.

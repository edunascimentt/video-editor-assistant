---
name: briefing-cut
description: Builds a short client video from raw location footage in the order a brief/roteiro asks, under a duration cap — identifies unnamed rushes, separates speech from b-roll, rough-cuts the speech, picks sentence spans in brief order, snaps every edge to real silence, lays b-roll from the video's own material inside the block it illustrates, levels speech between clips, checks each span and then the whole thing as a viewer, and finishes it the way the editor finished the previous one (word pops, flashes, riser, music bed, grade, subtitles). Use when the user sends a roteiro/briefing/list of steps for a video, gives a cap ("no máximo 1:30", "4 minutos"), says "monta os vídeos com b-roll", "faz o próximo vídeo igual", "segue o roteiro", or delivers a folder of backstage/institutional/reels footage to turn into videos.
---

# Cut to the brief

`rough-cut` removes air; it does not choose what matters and does not respect
an order. When a client says *"show the process from the start: A, B, C… max
4 minutes"*, the cut is a **selection in brief order**, built from sentences.
This skill is that selection, plus the assembly and finishing around it.

```bash
BC="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/skills/briefing-cut/scripts"
PY="${RESOLVE_MCP_HOME:-$HOME/Repositories/davinci-resolve-mcp}/venv/bin/python"
```

Load `resolve-scripting` before writing any build script, and read
`reference/finishing.md` before the finishing pass.

## 0. Read the brief

The brief may be a rasterized PDF (`pdftotext` returns nothing) — read it as
images. Write down per video: the ordered topics, the cap, and anything the
brief asks for that may not exist in the footage (say so early: "there is no
shot of the truck arriving; closest is people carrying boxes in").

## 1. Know the footage

Unnamed rushes (hundreds of `CAM_0707.MP4`) are identified with two cheap passes:

- **contact sheets:** one frame at 40% and one at 80% of each clip, 20 per sheet;
- **transcripts** of clips longer than ~25 s.

The pictures give the subject; the transcript settles what the picture cannot
(two dishes that look identical in the pan; a knife being sharpened vs a
delivery). Put the result in the project's bins — **the bin is the source of
truth**, not a scratch file. Note sideways clips (no rotation flag) and clips
with no audio at all.

**Read every interview transcript for material that must never go public.**
A "planning chat" filmed with the camera rolling can hold prices, a named third
party being accused, a partner's intention to sell. Mark those files (or
windows) as **mute picture** and tell the user before any cut exists — see
`podcast-cuts` §1.

**A video's bin may hold other videos' material.** B-roll comes only from the
clips that show *this* video's subject. Check every cutaway against the speech
it covers.

## 2. Four layers per video

| timeline | content |
|---|---|
| `N - TITLE` | selects: every clip of the bin in shooting order |
| `N - TITLE FALA` | only clips with speech (≥ ~90 words in the transcript; below that it is b-roll) |
| `N - TITLE FALA ROUGH` | `rough-cut` run on FALA — **never on the selects**: b-roll is "silence" to the analyser and disappears |
| `N - TITLE <cap>` | the delivery, built by this skill |

`rough-cut` on location audio (kitchen, street): the room tone sits at −30 to
−45 dB and no pause reaches true silence. What worked:
`--pause-residual-tail 0.12 --pause-residual-head 0.10 --tail-ms-sibilant 700`
(flagged silence splices 39/202 → 18/151). Going to 0.20/0.15 made it worse.
Filler policy for process videos: sentence-initial *então / agora / aí / olha /
bom / ó* **stay** (they carry the sequence); *né* keep one in two; *tipo, assim,
cara, sabe, beleza, tá, entendeu, certo* go.

**Speech hides inside "silence".** The aligner loses far-off speech and the
interviewer's off-mic questions, and the silence pass then proposes removing
the point of the video. For every silence removal ≥ 2.5 s, re-transcribe a
**wide** window (±5 s — a tight crop returns empty when speech starts at the
edge) and switch the removal off if words come back. Energy does not work as
the test (far speech sat 0.7 dB over the floor). A transcriber that fails
prints nothing — check it actually ran before concluding a pause is mute.

`rc_analyze` ids (`r0000`, `s0000`) are regenerated on every run and **the
silence ids renumber when parameters change**. Match your findings to removals
**by time overlap**, write the `off`s, re-run, and confirm by time that none of
the critical ones came back on. `rc_verify --skip-transcribe` on long, heavily
cut material (the re-transcription alone passes an hour).

## 3. Interview or monologue?

In an interview, half the long pauses are the interviewer asking off-mic, and
the answer often does not stand without the question ("yes, we do"). Decide per
answer: keep the question, or keep only answers that stand alone.

## 4. Plan the spans

Read the WhisperX segments already in the rough-cut cache
(`~/.cache/rough-cut/<project>/<timeline>/words/<clip>-<hash>/*.json`): text and
source seconds, no re-transcription needed. Write a plan — one row per span:

```
block   clip        start    end     what is said
hook    CAM_0896    33.17    37.80   the one-line promise of the video
ratio   CAM_0896    52.10    58.40   ...
```

in the brief's order, summing durations against the cap. **Choose over the
rough cut's `keep` ranges** (intersect each span with the keeps) so the span
inherits the air/filler removal instead of reopening it.

Open with a hook (the most striking line, even if the brief puts it later) and
close on a line that concludes. A client list's timings are **pointers, not
edits** — move in/out to where the sentence really starts and ends.

## 5. Edges

```bash
$PY $BC/span_edges.py spans.json > spans.edges.json
```

Every edge walks to 120 ms of real silence and pads 0.20/0.32 s. Without this,
12 of 29 cuts landed inside a word in the first build. Starting on a word's
exact `t0` eats short articles ("a", "o" are 20–60 ms). Read every `check`.

**The word cache drifts locally** around stretched tokens — 1.3 to 2 s off in
those regions, ~0.05 s elsewhere. Re-measure each block edge: cut ±2 s around
it, transcribe, read times **per word** (segments stretch too). Where the
re-measure disagrees with the cache, the rough `keep` is also wrong there: use
that block whole, with inner cuts measured by hand.

A mid-sentence splice for the hook (out between two words, in on a later one)
must not double a word: cut *before* the repeated article, not after it.

## 6. Build

1. **V1:** `AppendToTimeline` the spans **without `recordFrame`** — they pack
   end to end. Read `GetItemListInTrack` back to learn each block's real start/end.
2. **V2 b-roll** (`mediaType: 1`), from this video's own clips, **inside the
   block it illustrates** — cutaways spaced evenly over the whole timeline end
   up showing paperwork while he talks about the product. ~50% coverage.
3. **Sideways clips:** `RotationAngle -90`, and `ZoomX/Y 1.7778` in a
   `scaleToFit` vertical project, on every track they appear.
4. **Speech level between clips** can jump ~10 dB (−27 to −16.5 LUFS measured
   across four clips of one video). There is no volume API: render each clip's
   speech to WAV with gain toward −20 LUFS and `alimiter=limit=-1dB`
   (`music_measure.py level` measures), swap A1 for those. Skip when one clip.

## 7. Check — both layers

1. **Span by span:** cut each span with ffmpeg (`-ss` after `-i`), transcribe
   each alone, compare with the plan text. A long joined file makes the
   recogniser drop whole sentences that are there.
2. **As a viewer:** print the full text of the cut in order and read it as
   someone who never saw the footage. For every *esse/essa/isso/ele/daí/aqui*,
   ask what it points to. Real misses that every per-span check passed: a
   "you can use force" with no mention of washing; "this sauce…" before any
   sauce was named; a signature ending on "hand it to…" with the ask cut off; a
   step opening with "finishing the wash" when the wash never appeared. Fix
   with the same speaker's own bridging line, even if it costs seconds.
3. **Rebuild the audio and re-transcribe the whole cut** before calling it done:
   it is what catches a closing line in the wrong voice (a crew goodbye naming
   the videomaker, under the right picture).

Joined-file duplications at splices ("each… each delivery") that read clean
when the span is transcribed alone are recogniser noise, not a defect.

## 8. Subtitles

The rough-cut cache is in **source** time and drifts where tokens stretched —
subtitles built from it quote sentences the cut removed. Either transcribe the
assembled audio (times are then timeline times) or force-align the checked text
per span (`reference/forced-alignment.md`). Then the `subtitles` skill. Fix
words in the **cache** or the client glossary, never in the `.srt`.

## 9. Finish and deliver

`reference/finishing.md`: copy the editor's finishing from the approved video —
her items, not look-alikes. Music with the `music-bed` skill.

Deliver into the project's "prontas"-style bin: **one timeline per video, the
latest version of each** (not only the finished ones). `DuplicateTimeline`
ignores the current folder — `MoveClips` and re-list.

## Report

Runtime vs cap, the block list in order, what the brief asked for that the
footage does not have, every b-roll clip and the block it serves, audio
levelling done, both checks' findings and fixes, and manual steps left.

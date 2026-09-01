---
name: rough-cut-premiere
description: Rough-cuts an Adobe Premiere Pro sequence from its own audio — removes silence, hums ("éé", "uhh"), unnecessary filler words, and abandoned/restarted lines, then verifies nothing was clipped or lost. Transcribes with WhisperX for word-level timing and applies the cut as an FCP7 XML round trip. Use when the user wants a talking-head, course lesson, VSL or podcast sequence cut down to a clean take, or asks for silence removal / filler removal / "deixa cortado" in Premiere.
---

# Rough cut a Premiere sequence

Takes a raw talking-head sequence and returns a cut one: dead air gone, hums
gone, unnecessary fillers gone, blown lines and their restarts gone — with a
report proving no word was clipped and no meaning was lost.

The cut lands **inside Premiere**, as a new sequence in the same project. The
original sequence is never modified — not even opened for writing.

This is the Premiere port of the `rough-cut` skill. The analysis, the pt-BR
judgement rules and the verification are the same code; what differs is how the
cut reaches the NLE. Read `reference/premiere-notes.md` before changing
anything in `pr_probe.py` / `pr_apply.py`.

## Division of labour — read this first

The pipeline splits the work along a hard line, and staying on your side of it
is what makes the result trustworthy:

| The scripts decide | You decide |
|---|---|
| **Where** every splice lands, to the frame | **What** deserves to be removed |
| Silence, hums, stammers, tight repeats (mechanical) | Whether "então", "né", "tipo", "aí" is filler or structure **in this sentence** |
| Boundary protection so no phoneme is severed | Which abandoned take was abandoned, and where the retake really starts |
| Every measurement in the verification | Whether the argument still follows after the cuts |

Do not hand-edit splice times. If a cut sounds wrong, change a tuning parameter
or switch the removal off and re-plan — the boundary math is the part you should
not be doing by hand.

## How the cut reaches Premiere

Premiere has no scripting call that razors a clip, and the QE DOM calls that
come close (`split_clip`, `ripple_delete`) are one bridge round trip each. A
300-cut pass through them is 600 mutating calls into an open project with no
atomic point. So the cut is applied as an **interchange round trip** instead:

```
export_as_fcp_xml  ->  pr_probe.py  ->  pr_analyze.py  ->  pr_apply.py  ->  import_fcp_xml
     (Premiere)          (parse)          (the plan)         (rewrite)       (Premiere)
```

One file out, one file in, one new sequence. Every cut is integer arithmetic on
record and source frames, so it is exact.

## Prerequisites

- **Premiere Pro open**, the project loaded, the sequence to cut **active**
  (`export_as_fcp_xml` exports the active sequence, nothing else).
- The **Premiere MCP** installed and connected — `PREMIERE-MCP.md` at the repo
  root, or ask "instala o mcp do premiere". Run `verify_premiere_connection`
  before starting; if the bridge is down, everything below still works from a
  hand-exported XML (**File ▸ Export ▸ Final Cut Pro XML**).
- **ffmpeg** on PATH.
- A **transcriber**: `transcribe-x` (the WhisperX wrapper) or the `whisperx` CLI.
- This skill's venv, built once:

```bash
bash .claude/skills/rough-cut-premiere/scripts/setup.sh      # add --with-whisperx if needed
```

Define this once per session:

```bash
RC=/path/to/video-editor-assistant/.claude/skills/rough-cut-premiere/scripts
PY=$RC/../.venv/bin/python
```

**Work on a duplicate project for the first pass.** The import is additive, but
a rough cut is a large change and Premiere's undo does not cover an import.

## Pipeline

### 1. Export and probe

Ask the MCP for the sequence, then read it:

```
export_as_fcp_xml{"output_path": "/tmp/aula01.xml"}
```

```bash
$PY $RC/pr_probe.py --fcpxml /tmp/aula01.xml       # --sequence NAME if the XML holds several
```

Prints the sequence, its fps, its source files, and writes
`~/.cache/rough-cut/<project>/<sequence>/timeline.json` plus a copy of the
export. Take the work directory from the script's own last line — never guess
it — and hold it:

```bash
WORK=~/.cache/rough-cut/<project-slug>/<sequence-slug>
```

**Read the warnings.** Titles, graphics, mattes, nested sequences and
transitions have no source range and cannot be split; each one is named. So are
retimed clips and anything carrying Time Remapping. If the sequence is mostly
those, say so and stop: this skill cuts assembled takes, not finished edits.

**Never re-use a stale export.** If the sequence is touched in Premiere after
this step, re-export and re-probe. A plan built against yesterday's XML cuts at
frames that have moved.

### 2. Transcribe

```bash
$PY $RC/pr_transcribe.py --work-dir "$WORK"        # --lang pt is the default
```

WhisperX runs on CPU at roughly 2.5x realtime — a 30-minute lesson takes about
12 minutes. Say so before starting, and run it in the background. Results are
cached per file identity; re-running is free.

Never add `--initial_prompt` or `--hotwords`. On this stack they collapse long
chunks into two words while tripling runtime, and they fail *silently* — you get
a plausible, incomplete transcript, and every cut planned from it is wrong in a
way no later check can see.

### 3. Plan

```bash
$PY $RC/pr_analyze.py --work-dir "$WORK"
```

Writes `cutplan.json` (machine) and `review.md` (yours). Every removal carries a
`kind`, a `tier`, a `reason` and an on/off `state`.

- `tier: auto` — mechanical. Silence, unambiguous hums, clipped restarts, tight
  repeats. Already on.
- `tier: review` — a proposal. Discourse fillers, ambiguous interjections,
  suspected retakes. Also on, and **your job is to switch off the ones that are
  wrong**.

### 4. Judge — the part only you can do

Read `review.md`, then read the actual transcript around each `review` entry
(`cutplan.json` → `tokens`, or `$WORK/words/*/*.txt`). Judge in context, not by
word list. See `reference/cut-rules-ptbr.md` for the full rules; the short
version:

- **"então", "aí", "agora", "bom", "olha"** — filler when they open a sentence
  as throat-clearing, structure when they carry the argument forward ("então o
  resultado disso é…"). The script only proposes them sentence-initially; still
  check each one.
- **"né", "sabe", "entendeu"** — usually padding, but they also do real work
  closing a rhetorical question to the viewer. Removing every single one makes a
  Brazilian speaker sound like a robot. Keep some.
- **"tipo", "assim", "meio que"** — remove aggressively; they almost never carry
  meaning.
- **"ah", "eh"** — proposed for review, not auto, because they can be a beat
  ("ah, entendi") rather than a hum.
- **Repetition** flagged as ambiguous — "não, não, não" is emphasis and must
  survive; "eu— eu acho" is a stammer and must not.
- **Retakes** — the script only catches a restart that reuses the same opening
  words. The common case it cannot see is a line abandoned and re-said
  *differently*. Read the transcript for those and add them yourself.
- **A pause the speaker announces is content, not dead air.** "vou deixar 10
  segundos para você refletir", "conta aí nos comentários", a beat held for
  effect — the silence pass sees only a long gap and takes it. Nothing in the
  audio distinguishes it; only the sentence before it does. Scan every removal
  over ~2 s against the line that precedes it and switch off the ones he asked
  for.

Write your decisions to `$WORK/decisions.json`:

```json
{
  "off": ["r0042", "r0107"],
  "add": [
    {"start": 132.40, "end": 139.85, "kind": "retake",
     "reason": "blew the line on the CIF definition, restarts clean at 139.9"}
  ]
}
```

`start`/`end` are **sequence record seconds**, and the boundary math is applied
to them too — put them roughly around the phrase, do not try to be exact. Then
re-plan:

```bash
$PY $RC/pr_analyze.py --work-dir "$WORK" --decisions "$WORK/decisions.json"
```

Iterate until `review.md` reads right. Show the user the summary table and the
`review` list before applying — this is the point of no misunderstanding, and it
is cheap here and expensive later.

### 5. Apply

```bash
$PY $RC/pr_apply.py --work-dir "$WORK" --dry-run      # numbers and warnings, writes nothing
$PY $RC/pr_apply.py --work-dir "$WORK"                # writes $WORK/cut.xml
```

Then hand the file to Premiere:

```
import_fcp_xml{"path": "<WORK>/cut.xml"}
```

The imported sequence is named `<sequence> ROUGH` (change with `--name`) and
carries a fresh UUID, so Premiere adds it rather than merging into the original.

**Read the warnings before importing.** Three kinds matter:

| Warning | What it means |
|---|---|
| `CARRIED <item>` | A title or graphic sat entirely inside kept audio and was moved with the cut. Nothing to do; check it landed right. |
| `DROPPED <item>` | A removal fell inside something with no source range to cut, or the item was entirely inside removed audio. **Re-place it by hand after the import.** |
| `N gap(s) on <track>` | Holes left where dropped items used to sit. The report names the first one. |

`OVERLAP` never appears on a good run. If it does, do not import — re-plan.

### 6. Verify

```bash
$PY $RC/pr_verify.py --work-dir "$WORK"
```

Three checks, described in the script's own header. Read `verify/report.md` and
report all three to the user:

- **Clipped words: must be 0.** Any hit is a defect — re-plan, do not ship it.
- **Splices with energy at the edge — read the by-kind table, not the total.**
  The two rows mean opposite things. A flag on a *silence* splice is a real
  defect: a pause should join into room tone, so raise `--tail-ms-sibilant` or
  `--pause-residual-tail`. A flag on a *filler / false_start* splice is expected
  — those are word-to-word joins with no silence to land in, and no setting
  fixes them. If one of those sounds wrong, switch that removal off.
- **Refused silences.** Pauses whose audio never comes down to room tone are
  proposed **off**, with the level in the reason. That usually means speech the
  transcript missed. Listen before switching one on.
- **Transcript similarity**: expect 97%+. Differences clustered at splices are
  real clips; scattered homophone swaps are recogniser noise.

The reconstruction is arithmetic on the source media, so it proves the *plan* is
sound. Prove Premiere agrees too, on the imported sequence:

- `get_sequence_structure` — the fragment count and the track layout should
  match `applied.json`.
- `export_sequence_review_frames` — a visual pass over the joins.
- Drag one cut clip: its audio must move with it. See
  `reference/premiere-notes.md` § *To confirm on the first live run*.

Then do the part no script can: **read `verify/transcript_after.txt` end to end**
and confirm the argument still follows across every cut. Report anything that
now reads as a non-sequitur.

## Tuning

Every threshold in `pr_analyze.py` is a flag (`--min-pause`, `--tail-ms`,
`--pause-residual-tail`, …); `--help` lists them with defaults. The three that
actually matter:

| Symptom | Change |
|---|---|
| **Too much dead air survives** | **raise `--bb-margin-db` / `--hi-margin-db` (9)** — see below, the direction is not the obvious one |
| Cuts feel breathless, machine-gun | raise `--pause-residual-tail` / `--pause-residual-head` (0.04 / 0.03) and `--min-pause` (0.22) |
| Trailing "s" clipped, lisping | raise `--tail-ms-sibilant` (620) and/or lower `--hi-margin-db-sibilant` (5.0) |
| Too many pauses refused as "not silent" | raise `--silence-guard-db` (15) — but check you are not cutting over speech |

**Lowering the gate removes LESS, not more.** This trips everyone, so it is
worth stating plainly: the gate is where the boundary walk *stops*. Lower it and
the walk must travel further to reach it, so it eats the very pause it was
protecting, and the shrunken removals fall under `--min-removal` and vanish
entirely. The defaults sit at the measured peak. If a cut is leaving dead air,
raise the margins first.

The plan's own `notes` print the room tone the pass measured. If that number
looks wrong for the recording, everything downstream is suspect — check the
media before touching any other flag.

## Hard constraints

- **Do not razor through the API.** `split_clip` and `ripple_delete` run on the
  undocumented QE DOM, one bridge round trip each, with no atomic point across a
  300-cut pass. `remove_from_timeline` deletes a WHOLE clip — on a single-take
  sequence that is the take. The interchange route exists for this reason.
- **Never edit `cut.xml` by hand.** Record and source frames, `pproTicks`, file
  back-references and link groups all have to agree; the rewrite keeps them
  consistent, and a hand edit that touches one of them imports silently wrong.
- **Never cut from timecode you did not measure.** Word times come from
  WhisperX, splice times from energy analysis. Do not eyeball a cut from a
  caption track: cue-level timing is far too coarse for word boundaries.
- **Do not remove a word the transcript could not time.** WhisperX leaves
  numerals and symbols unaligned; those are dropped from the token stream, which
  protects the audio around them. That is deliberate.
- **Room tone is measured from this recording's own pauses**, not from a fixed
  dB number and not from the quietest moment in the file.
- **A gap between words is not a gap in sound.** Where the audio never reaches
  room tone, something is still happening that the recogniser did not write down
  — a mumble, a swallowed word, an off-mic line. Those pauses are proposed off,
  never cut silently. Do not defeat that guard to hit a runtime target.
- **Never run this on a graded or finished sequence.** FCP7 XML carries Motion,
  Opacity and Volume, but not Lumetri, third-party effects or Essential Graphics
  text. A rough cut belongs before that work.
- The pass **only cuts**. It adds no B-roll, no punch-ins, no transitions, no
  crossfades. Jump cuts are the expected output of a rough cut.

## Reference

- `reference/cut-rules-ptbr.md` — the pt-BR filler/hum taxonomy and the traps in
  it (why the English `um`/`uh`/`eh` list is dangerous in Portuguese).
- `reference/premiere-notes.md` — the FCP7 XML semantics the rewrite rests on,
  which Premiere MCP tools are and are not the route, and the short list of
  things to confirm on the first live import.

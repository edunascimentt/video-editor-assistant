---
name: rough-cut
description: Rough-cuts a DaVinci Resolve timeline from its own audio — removes silence, hums ("éé", "uhh"), unnecessary filler words, and abandoned/restarted lines, then verifies nothing was clipped or lost. Transcribes with WhisperX for word-level timing. Use when the user wants a talking-head, course lesson, VSL or podcast timeline cut down to a clean take, or asks for silence removal / filler removal / "deixa cortado" in Resolve.
---

# Rough cut a Resolve timeline

Takes a raw talking-head timeline and returns a cut one: dead air gone, hums
gone, unnecessary fillers gone, blown lines and their restarts gone — with a
report proving no word was clipped and no meaning was lost.

The cut lands **inside Resolve**, as a new timeline in the same project. The
original is never modified.

## Division of labour — read this first

The pipeline splits the work along a hard line, and staying on your side of it
is what makes the result trustworthy:

| The scripts decide | You decide |
|---|---|
| **Where** every splice lands, to the frame | **What** deserves to be removed |
| Silence, hums, stammers, tight repeats (mechanical) | Whether "então", "né", "tipo", "aí" is filler or structure **in this sentence** |
| Boundary protection so no phoneme is severed | Which abandoned take was abandoned, and where the retake really starts |
| Every measurement in the verification | Whether the argument still follows after the cuts |

Do not hand-edit splice times. If a cut sounds wrong, change a tuning
parameter or switch the removal off and re-plan — the boundary math is the
part you should not be doing by hand.

## Prerequisites

- DaVinci Resolve Studio **running**, the right project open, the timeline to
  cut either current or nameable. Source media online.
- `transcribe-x` on PATH (WhisperX 3.8.6 wrapper in `~/.audio-tools`).
- ffmpeg, and the resolve-mcp venv, which supplies both `DaVinciResolveScript`
  and numpy.

Every script runs under that venv. Define this once per session:

```bash
RC="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/skills/rough-cut/scripts"
RESOLVE_MCP_HOME="${RESOLVE_MCP_HOME:-$HOME/Repositories/davinci-resolve-mcp}"
PY="$RESOLVE_MCP_HOME/venv/bin/python"
export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
export RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
export PYTHONPATH="$RESOLVE_SCRIPT_API/Modules"
```

If Resolve is not up, use the MCP tool `resolve_control{action:"launch"}` rather
than launching it by hand.

## Pipeline

### 1. Probe

```bash
$PY $RC/rc_probe.py                      # add --timeline "NAME" to pick one
```

Prints the timeline, its fps, its source files, and writes
`~/.cache/rough-cut/<project>/<timeline>/timeline.json`. Take that path from the
script's own last line — never guess it — and hold it:

```bash
WORK=~/.cache/rough-cut/<project-slug>/<timeline-slug>
```

**Read the warnings.** Retimed clips, titles, generators, compounds and
anything with an unreadable source rate cannot be cut safely and are excluded
from the result. If the timeline is full of them, say so and stop: this skill
cuts assembled takes, not finished edits.

### 2. Transcribe

```bash
$PY $RC/rc_transcribe.py --work-dir "$WORK"        # --lang pt is the default
```

WhisperX runs on CPU at roughly 2.5x realtime — a 30-minute lesson takes about
12 minutes. Say so before starting, and run it in the background. Results are
cached per file identity; re-running is free.

Never add `--initial_prompt` or `--hotwords`. On this machine they collapse
long chunks into two words while tripling runtime, and they fail *silently* —
you get a plausible, incomplete transcript. `transcribe-x` refuses them by
design; do not work around it.

### 3. Plan

```bash
$PY $RC/rc_analyze.py --work-dir "$WORK"
```

Writes `cutplan.json` (machine) and `review.md` (yours). Every removal carries
a `kind`, a `tier`, a `reason` and an on/off `state`.

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
  resultado disso é…"). The script only proposes them sentence-initially;
  still check each one.
- **"né", "sabe", "entendeu"** — usually padding, but they also do real work
  closing a rhetorical question to the viewer. Removing every single one makes
  a Brazilian speaker sound like a robot. Keep some.
- **"tipo", "assim", "meio que"** — remove aggressively; they almost never
  carry meaning.
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
  for. Measured on a real lesson: a 7.7 s reflection pause, the point of that
  lesson, was proposed for removal.

Write your decisions to `$WORK/decisions.json`:

```json
{
  "off": ["r0042", "r0107"],
  "add": [
    {"start": 132.40, "end": 139.85, "kind": "retake",
     "reason": "blew the line on the definition, restarts clean at 139.9"}
  ]
}
```

`start`/`end` are **timeline record seconds**, and the boundary math is applied
to them too — put them roughly around the phrase, do not try to be exact. Then
re-plan:

```bash
$PY $RC/rc_analyze.py --work-dir "$WORK" --decisions "$WORK/decisions.json"
```

Iterate until `review.md` reads right. Show the user the summary table and the
`review` list before applying — this is the point of no misunderstanding, and it
is cheap here and expensive later.

### 5. Apply

```bash
$PY $RC/rc_apply.py --work-dir "$WORK" --dry-run              # check the numbers first
$PY $RC/rc_apply.py --work-dir "$WORK" --markers              # variant (default)
$PY $RC/rc_apply.py --work-dir "$WORK" --markers --mode in-place
```

Two modes, one mechanism — **duplicate, empty, append**:

| mode | what it does | when |
|---|---|---|
| `variant` (default) | builds `<timeline> ROUGH` as a duplicate of the original, emptied and refilled. The original is not touched. | trying tuning, comparing passes, anything reversible |
| `in-place` | duplicates the original to `<timeline> · pre rough-cut` as a backup, then empties and rebuilds **the original itself** — same name, same unique id, same settings, same place in the bin | the user wants the cut *in* their timeline |

`in-place` is destructive by definition, so the backup is made first and the run
refuses outright if the backup cannot be created. Confirm with the user before
using it.

**Both modes duplicate rather than create.** `CreateEmptyTimeline` inherits the
PROJECT's settings, so a 24 fps timeline inside a 30 fps project would come back
at 30 — silently, and every source-frame conversion downstream would be wrong.
`DuplicateTimeline` reproduces all of them; the run verifies this afterwards and
prints `settings: all N preserved (fps …)`. If it ever prints a drift warning
instead, stop and investigate before trusting the result.

**The rebuild empties EVERY track, not just the ones it cuts.** `DeleteClips`
takes the whole timeline and only what is in `timeline.json` comes back. On a
timeline that already carries a vinheta, a lower third, slides or SFX, those
items are either destroyed (if the probe excluded them) or chopped by the keep
ranges as if they were speech (if they are ordinary media, which a `.mov` is).
Before applying, take them out and put them back yourself:

```bash
# 1. park the non-speech items and drop them from the plan
python - <<'EOF'
import json, pathlib
w = pathlib.Path("<WORK>")
d = json.load(open(w / "timeline.json"))
keep = [i for i in d["items"] if i["name"].startswith("VINHETA")]
json.dump([i for i in d["items"] if i not in keep], open(w / "intro_items_preserved.json", "w"))
d["items"] = keep
d["timeline_start_frame"] = 155      # 2. see below
json.dump(d, open(w / "timeline.json", "w"))
EOF
# 3. after rc_apply, AppendToTimeline them back at their old recordFrame,
#    then re-apply their Transform (SetProperty) — that does not survive either.
```

`timeline_start_frame` is what `rc_apply` uses as the record origin. A lesson
that opens under a vinheta has the talking head starting a few frames in — 155
to 158, with the vinheta ending at 165, in the project this was measured on.
Leave the origin at 0 and the whole cut slides up under the vinheta; setting it
to the V1 clip's own start keeps the head exactly where it was built.

**Markers survive the cut.** Every marker on the original is re-timed into the
cut; one sitting exactly on a splice lands on the join, and one that sat inside
removed audio is dropped and named in the output. `--markers` then adds the
review markers on top.

### 6. Verify

```bash
$PY $RC/rc_verify.py --work-dir "$WORK"
```

Three checks, described in the script's own header. Read `verify/report.md` and
report all three to the user:

- **Clipped words: must be 0.** Any hit is a defect — re-plan, do not ship it.
- **Splices with energy at the edge — read the by-kind table, not the total.**
  The two rows mean opposite things. A flag on a *silence* splice is a real
  defect: a pause should join into room tone, so raise `--tail-ms-sibilant` or
  `--pause-residual-tail`. A flag on a *filler / false_start* splice is
  expected — those are word-to-word joins with no silence to land in, and no
  setting fixes them. If one of those sounds wrong, switch that removal off.
- **Refused silences.** Pauses whose audio never comes down to room tone are
  proposed **off**, with the level in the reason. That usually means speech the
  transcript missed. Listen before switching one on.
- **Transcript similarity**: expect 97%+. Differences clustered at splices are
  real clips; scattered homophone swaps are recogniser noise.

Then do the part no script can: **read `verify/transcript_after.txt` end to
end** and confirm the argument still follows across every cut. Report anything
that now reads as a non-sequitur.

## Tuning

Every threshold in `rc_analyze.py` is a flag (`--min-pause`, `--tail-ms`,
`--pause-residual-tail`, …); `--help` lists them with defaults. The three that
actually matter:

| Symptom | Change |
|---|---|
| **Too much dead air survives** | **raise `--bb-margin-db` / `--hi-margin-db` (9)** — see below, the direction is not the obvious one |
| Cuts feel breathless, machine-gun | raise `--pause-residual-tail` / `--pause-residual-head` (0.04 / 0.03) and `--min-pause` (0.22) |
| Trailing "s" clipped, lisping | raise `--tail-ms-sibilant` (620) and/or lower `--hi-margin-db-sibilant` (5.0) |
| Too many pauses refused as "not silent" | raise `--silence-guard-db` (15) — but check you are not cutting over speech |

**Lowering the gate removes LESS, not more.** This trips everyone, so it is worth
stating plainly: the gate is where the boundary walk *stops*. Lower it and the
walk must travel further to reach it, so it eats the very pause it was protecting,
and the shrunken removals fall under `--min-removal` and vanish entirely. Swept
0→16 dB on real material, the yield rises with the gate until the splices start
landing on live audio. The defaults sit at that peak (9 dB, 0 dirty splices out
of 199). If a cut is leaving dead air, raise the margins first.

The plan's own `notes` print the room tone the pass measured. If that number
looks wrong for the recording, everything downstream is suspect — check the
media before touching any other flag.

## Hard constraints

- **Resolve has no razor in its API.** `edit_kernel_capabilities` says so
  outright. Intra-clip cuts cannot be made by deleting spans; the frame-accurate
  route is re-assembly. Never try to make a rough cut with `timeline.lift_range`,
  `delete_clips` on a span, or `apply_cuts` — those delete WHOLE items and will
  destroy the take. (Rebuilding *the same timeline* is still possible, and
  `--mode in-place` does it: empty it with `DeleteClips`, then append the keep
  ranges back at explicit record frames.)
- **Never build a cut timeline with `CreateEmptyTimeline`.** It takes the
  project's settings, not the source timeline's. Always duplicate.
- **Never cut from timecode you did not measure.** Word times come from
  WhisperX, splice times from energy analysis. Do not eyeball a cut from a
  subtitle track: cue-level timing is far too coarse for word boundaries.
- **Do not remove a word the transcript could not time.** WhisperX leaves
  numerals and symbols unaligned; those are dropped from the token stream,
  which protects the audio around them. That is deliberate.
- **Room tone is measured from this recording's own pauses**, not from a fixed
  dB number and not from the quietest moment in the file. The transcript already
  says where the pauses are; the floor comes from their interiors. Every gate in
  the pass is relative to it.
- **A gap between words is not a gap in sound.** Where the audio never reaches
  room tone, something is still happening that the recogniser did not write
  down — a mumble, a swallowed word, an off-mic line. Those pauses are proposed
  off, never cut silently. Do not defeat that guard to hit a runtime target.
- The pass **only cuts**. It adds no B-roll, no punch-ins, no transitions, no
  crossfades. Jump cuts are the expected output of a rough cut.

## Reference

- `reference/cut-rules-ptbr.md` — the pt-BR filler/hum taxonomy and the traps
  in it (why the English `um`/`uh`/`eh` list is dangerous in Portuguese).
- `reference/resolve-notes.md` — the Resolve API facts this rests on: no razor,
  exclusive `endFrame`, source frames in the media's own rate, mixed-fps
  flooring, and which MCP tools are the equivalents of these scripts.

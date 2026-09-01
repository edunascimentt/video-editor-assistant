# The Premiere facts this pipeline rests on

> The pt-BR filler/hum taxonomy and the acoustic tuning lessons are in
> `cut-rules-ptbr.md`. This file is only about how the cut reaches Premiere.

Two classes of statement live here, and they are labelled, because they carry
different weight:

- **Verified here** — checked against the MCP server's own tool catalogue, or
  exercised end to end by the scripts in this skill on a synthetic sequence.
- **To confirm on the first live run** — believed true from the format and from
  how Premiere is documented to read it, but not yet watched landing in a real
  Premiere. Check these once, on a duplicate project, and then never again.

## Premiere cannot razor 300 times through the API

**Verified here.** The Premiere MCP exposes 319 tools in the default profile.
The ones that could, in principle, build a rough cut are:

| Tool | Why it is not the route |
|---|---|
| `split_clip` | QE DOM. One bridge round trip per cut, and its own description says effect-keyframe redistribution stays unverified. |
| `ripple_delete` | QE DOM. Same cost again per removal, and the QE DOM is undocumented and shifts between Premiere builds. |
| `remove_from_timeline` | Removes a WHOLE clip, exactly like Resolve's `delete_clips`. On a single-take sequence that deletes the take. |
| `trim_clip` | One source in/out per call, and it refuses retimed clips. |

A 300-cut pass is 600 mutating calls through a file bridge into a project that
is already open, with no atomic point and no way back if the two-hundredth
fails. That is the reason this skill does not use them.

**The route it uses instead is interchange:**

```
export_as_fcp_xml{output_path}  ->  pr_probe.py  ->  plan  ->  pr_apply.py  ->  import_fcp_xml{path}
```

One file out, one file in, and the whole edit lands as a single new sequence.
Both tools exist and take exactly one argument each (`output_path`, `path`) —
**verified here** against the server's tool schemas.

## What the XML means

**Verified here** — every one of these is exercised by `pr_xmeml.py`, and
getting any of them wrong produces a plausible, wrongly-timed sequence rather
than an error:

- `<start>` / `<end>` are **record** frames in the sequence's timebase, and
  `<end>` is **exclusive**: duration is `end - start`.
- `<in>` / `<out>` are **source** frames in the clipitem's own `<rate>` — the
  media's rate, which need not be the sequence's. `<out>` is exclusive too.
- **NTSC rates are `timebase * 1000/1001`.** `<timebase>30</timebase>` with
  `<ntsc>TRUE</ntsc>` is 29.97, not 30. Reading it as 30 drifts a frame every
  33 seconds; half a minute into a lesson the cuts no longer land on the words.
- `<in>`/`<out>` of `-1` mean **no source range at all** — a title, a colour
  matte, a generator. That is not the same as a range starting at zero, and
  writing one into it turns a graphic into a clip with invented media.
- `<start>` of `-1` marks a clipitem living **inside a transition** rather than
  on the track proper. It has no record position to cut at.
- A `<file>` is defined **once, in document order**, and referenced as
  `<file id="..."/>` afterwards. Splitting a clip deep-copies it, so without
  re-collapsing the duplicates Premiere imports the same media once per
  fragment.
- Premiere writes its own `<pproTicksIn>` / `<pproTicksOut>` next to the frame
  values, at **254016000000 ticks per second** of source time. They are
  rewritten in step with `<in>` / `<out>`; a stale tick value beside a fresh
  frame value is exactly the kind of inconsistency that imports silently wrong.
- The sequence `<uuid>` is its identity. `pr_apply.py` writes a fresh one with a
  new name, so the import creates a sequence instead of matching the original.

## The cut is a razor expressed as arithmetic

**Verified here** on a synthetic 29.97 fps sequence (linked V1/A1 take plus a
title, 7 keep ranges): 12 fragments, record and source durations equal on every
one, both tracks fragmented identically, no overlaps, file definitions collapsed
to one, ticks matching the frames, markers re-timed and the one sitting in
removed audio reported rather than moved.

Each fragment's source range comes from the **original clipitem's own
record-to-source ratio**, not from an assumed 1x. A clip that was conformed
(25 fps media in a 29.97 sequence) or deliberately retimed therefore keeps its
speed through the cut instead of being silently normalised.

**Items with no source range cannot be split.** One that sits entirely inside
kept audio is carried across and shifted; one that a removal falls inside is
dropped and named. Moving it instead would put a graphic somewhere the editor
did not choose, which is worse than leaving a hole the report points at.

## To confirm on the first live run

Do these once, on a duplicate project, and read the result rather than assuming:

1. **A/V links.** `pr_apply.py` rebuilds `<link>` groups from scratch, with
   `<clipindex>` recomputed against the rebuilt tracks — the original indexes
   stop being true the moment one clip becomes forty. Confirm that dragging a
   cut clip in the imported sequence moves its audio with it. If it does not,
   the fragments are correct and only the links are not: select all and
   re-link in Premiere, and say so.
2. **`pproTicks`.** Confirm the imported clips' source in/out points match the
   frames the report claims, not a value one field older.
3. **Transitions.** They are dropped, by design. Confirm none survived in a
   half-state.
4. **Effects.** FCP7 XML carries a subset: Motion, Opacity, Volume and other
   built-ins travel as `<filter>` blocks and ride along on every fragment.
   Lumetri, third-party plugins and Essential Graphics text generally do not
   survive the round trip. A rough cut is done before that work, which is why
   this is acceptable — but check, and never run this on a graded sequence.
5. **Time Remapping.** A `timeremap` filter's keyframes are in source time and
   do not survive being split. `pr_probe.py` warns for every clip carrying one.

## What the MCP's own silence tools do and do not do

`detect_silence` and `plan_silence_review_markers` exist, and they are good at
what they do: FFmpeg silence ranges on one media file, mapped onto one 1x
placement, as review markers. They are **not** a rough cut:

- no word-level transcript, so no filler, no hum, no stammer, no abandoned take;
- no boundary protection, so a splice can land inside a fricative;
- one file at a time against one placement, not a multi-clip sequence;
- markers, not an edit.

Use them for a quick look. This pipeline is what happens when the pass has to be
defensible: `pr_verify.py` reconstructs exactly what the sequence will play and
measures every splice before anyone watches it.

## Useful read-only tools for checking the result

- `get_sequence_structure` — tracks, clips, positions and gaps of the imported
  sequence. The cheap way to confirm the fragment count matches the report.
- `inspect_fcpxml_interchange{path}` — root version, sequence and clip counts of
  a local XML before importing it.
- `verify_fcpxml_media_references{path, allowed_roots}` — confirms the `file://`
  references resolve inside roots you name, before Premiere goes looking.
- `export_sequence_review_frames` — evenly spaced rendered frames from a range,
  for a visual pass over the joins.
- `list_markers` — the re-timed markers, to check they landed where the report
  says.

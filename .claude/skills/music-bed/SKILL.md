---
name: music-bed
description: Picks a music bed for a cut by measurement — licence filter first, then voice-band energy, dynamic arc, rhythmic density and instrumental check — aligns the track's turn with the key line, measures the dialogue and renders the bed with gain, fades and ducking envelope baked into the file (Resolve's API has no clip volume). Use when the user asks for trilha, música de fundo, "coloca uma música", a bed under a reels/institutional/backstage cut, when a bed is too loud or fights the voice, or when a finishing pass needs music like the previous video's.
---

# Music bed by measurement

Titles lie about how a track sits under a voice. This picks from measurements,
places the track so its build lands on the line that matters, and delivers a
WAV that is already at the right level — because in Resolve, the level you
render into the file **is** the level on the timeline.

```bash
MB="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/skills/music-bed/scripts"
PY="${RESOLVE_MCP_HOME:-$HOME/Repositories/davinci-resolve-mcp}/venv/bin/python"   # any python with numpy
```

## 1. Licence filter — before anything else

A shared music folder usually mixes a licensed library with **commercial
rips** (pop singles, streaming downloads). A rip under a client's public ad is
a real copyright problem. `scan` only considers files whose names match the
licensed-library patterns (default `ES_*`, `MA_*`, `*_source_*`; override with
`--allow`). Never choose by title without checking the prefix, and ask the user
which patterns mark licensed tracks if the folder uses others.

## 2. Rank

```bash
$PY $MB/music_measure.py scan "<music folder>" --top 15
```

| column | read it as |
|---|---|
| `voice dB` | energy in 300–3000 Hz vs the full band. **Lower sits under speech better.** Finalists measured −19 to −21; −11 fights the voice |
| `onset/m` | attack density. High numbers compete with the rhythm of speech |
| `arc` | quietest..loudest 5 s window. A wide arc means the track *turns* somewhere — useful if you can place the turn |

Then, for each finalist:

- `arc FILE` — where it turns (a jump of 10+ dB between windows).
- **Instrumental check:** transcribe 60 s of it with whatever transcriber works
  on the machine. Words back = it has vocals = not a bed under speech.
- **Listen to your top pick's arc against the cut's mood**, not only the
  numbers: a chamada/event cut wants the build; a talking explanation wants the
  flat one.

## 3. Place the turn on the line

Find the record second of the key line (the announcement, the payoff) and the
source second where the track builds:

```bash
$PY $MB/music_measure.py align --turn 40.0 --key 29.9
# enter the track at source 10.10s so 40.0s lands on record 29.9s
```

For a cut with no speech, cut **on the beat** instead: at 90 bpm and 24 fps a
beat is exactly 16 frames — find the first beat and the drop in the arc, and
put the picture changes on multiples of the beat from there.

## 4. Level

Measure the dialogue as it plays in the cut, then set the bed **~11 LU below**
it:

```bash
$PY $MB/music_measure.py level "<dialogue.wav>"      # e.g. -18.5
# bed target = -29.5
```

Measured references that worked: speech −18.5 LUFS with the bed at −29.6; a
music-only chamada at −16 LUFS integrated.
If the editor already set a bed on a sibling video, **copy her level** instead
of computing one: the `.drt` export carries clip gain in the item's
`EffectFiltersBA` (a little-endian double; `…36c0` is −22.0).

## 5. Render

```bash
$PY $MB/music_measure.py render "<track.wav>" -o "<project>/_MUSICA/<name> (from 10.1s, -29.5 LUFS).wav" \
    --from 10.1 --dur 54.02 --target-lufs -29.5 --fade-in 1.5 --fade-out 2.5
```

- Put the **offset and level in the file name** — rebalancing means rendering
  again and swapping the file, so the name is the record of what was done.
- **Ducking/envelope** for a cut that goes from speech to picture-only:
  `--env "0:-10,12.3:-10,12.9:0"` holds −10 dB under the speech to 12.3 s and
  ramps up over 0.6 s. Output seconds, dB relative to the target.
- Trimming happens inside the filter graph (`atrim`), so fades and the envelope
  are timed from the cut, not from the source start. Do not "simplify" it to
  `-ss`: an output-side seek runs the fades on source time and silences the bed.

## 6. Put it on the timeline

Import the WAV and append it (`mediaType: 2`) on an **empty audio track** you
create and name (`SetTrackName("MUSICA")`). Probe the live timeline first —
editors drop their own SFX on A2/A3 while you work, and a collision fails
silently. A WAV in the media pool reports 24 fps: `startFrame = round(s*24)`.
See the `resolve-scripting` skill.

## Report

Say which track, why (the three numbers), where it enters, the level against
the measured speech, and that level changes need a re-render (not a fader).

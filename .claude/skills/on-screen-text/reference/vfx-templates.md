# The templates this pass places

All three live in the media pool of the lesson project. Everything below was
read off one reference edit — a finished lesson from this project, cut and
graded by hand. The ids are per project; `ost_probe.py`
rediscovers them and caches the choice in
`~/.cache/on-screen-text/<project>/templates.json`.

## 1. Word on screen — `Text+`

**Use `Master/Assets` › Text+ (42 frames @ 24 fps, `Fusion Title`).** That is what
`ost_probe` pins and what the punch pair below is built from. Everything in this
section about the 60 fps copies is kept as history — it is how the old words were
made, and why they render static.

`Master/00 - GERAL/Títulos e Fusion` › **Text+** (type `Fusion Title`, 60 fps).

The folder holds four byte-identical copies (`Text+`, `Text+ copy`, `copy 1`,
`copy 2` — all reading "20 ANOS" at `Size` 0.09) plus an unrelated stock title,
`Minimal Clean Title 07`. Any of the four works; pin one so the choice stops
being a coin flip.

| | |
|---|---|
| Node graph | `Template` (TextPlus) → `Merge`/`MediaOut`, animated by `Follower1` (StyledTextFollower) along `Path1` |
| Text input | `Template.StyledText` |
| Font | SF Pro Display **Bold**, white |
| Content | **one word, UPPERCASE** — ESTRATEGIAS, PLANEJAMENTO, PROBLEMA, SOLUÇÃO, EXEMPLO, PLANEJAR |
| Nominal length | 105 frames **@ 60 fps** = 1.75 s |
| Used length | ~104 timeline frames (4.3 s) — the reference edit stretches it |

### The animation does not run on a 24 fps timeline

Measured, not inferred, by capturing rendered frames:

| timeline | fps | word animates? |
|---|---|---|
| `AULA ANTIGA` | 60 | **yes** — at clip frame 2 only "ME" of ESTRATEGIAS is up, dim |
| `AULA 01` (the editor's own) | 24 | no — full opacity from frame 1 |
| `AULA 02` | 24 | no |
| the 24 fps explanation card, same timeline | 24 | **yes** — control case |

Comp, splines and every Follower setting are byte-identical between AULA ANTIGA and
the 24 fps ones; only the container's rate differs. `SetClipProperty("FPS", …)`
is refused, so the template cannot be retagged.

Things that look like a fix and are not:

- **Importing the comp into a 24 fps container** (`ImportFusionComp` onto a
  Fusion Composition from the media pool) animates correctly *in session* and
  **loses the animation on `SaveProject`**. Do not ship it.
- Longer clips, `insert_fusion_composition` (which ripple-inserts on V1 and
  splits whatever it lands on — it damaged the timeline once), retiming.

**The real fix is a 24 fps word template, made once in the UI**: drag Text+ from
the Effects Library onto a 24 fps timeline, rebuild the StyledTextFollower
(or paste it from an AULA ANTIGA instance), save it to
`Master/00 - GERAL/Títulos e Fusion`, then pin it with
`ost_probe.py --set-template word=<id>`.

**Corrected 2026-08-21 — the two claims above are wrong.** A `Text+` from the
media pool **does animate on a 24 fps timeline**: the 42-frame 24 fps Text+ in
`Master/Assets`, placed straight from the pool with its text written by script,
renders letter-by-letter. And the words placed by `ImportFusionComp` on
2026-08-20 survived a close/reopen with their text and splines intact, so the
"loses the animation on `SaveProject`" line does not hold either.

What *is* true is that the older hand-made words — PROCESSAMENTO and EXEMPLO —
render static from frame 1. Whatever kills the animation
there, it is **not** `Template.Size`, **not** `Pan`/`Tilt`, **not** the
template's fps, and **not** `ImportFusionComp`; each of those was ruled out with
rendered frames. Unresolved, and only worth chasing if the editor asks for
those old lessons to be redone.

## The punch word — the shape the editor approved

This is what to place for a word from now on (approved on 2026-08-21, on
AULA 03, after seeing it render):

- `Master/Assets` › **Text+**, `Fusion Title`, **42 frames @ 24 fps** — placed
  straight from the pool, **no `ImportFusionComp`**. On a 24 fps timeline it
  maps 1:1, so none of the 60 fps arithmetic below applies to it.
- **A pair of clips**, the shape of the reference edit's PROCESSAMENTO and PLANEJAR:
  an entrance of 41f (`startFrame` 0, `endFrame` 41) followed immediately by a
  hold of ~85f (`startFrame` 41, `endFrame` 126). Same text and same
  `Template.Size` on both comps.
- `Pan -514`, `Tilt 130`, `Zoom 1` on both items; `Burnin Click.mp4` on A2 two
  frames before the entrance.

### Measuring animation: two traps

- **`GrabStill` lags a step** — the still is not the frame you asked for. Two
  samples of the same clip contradicted each other before this surfaced.
- **A render made in the same session the comp was scripted can come back
  static** even when the finished result animates. That is what produced a
  confident, wrong "the words don't animate". Never settle an animation
  question from an in-session render of a freshly scripted comp: reopen the
  project first, or let the editor look.

### The authored range, and why the word also has no out

Every Follower spline in the template keys at **0 / 30 / 150 / 170** (`Delay`
adds 175 and 210): fade in over 30 frames, hold to 150, fade out by 170. That
is a **171-frame** animation — 7.1 s at 24 fps. A 104-frame clip therefore ends
in the middle of the hold, and the word is cut off with no out at all.

Some hand-cut words retime those splines to **0 / 30 / 64 / 84** — EXEMPLO on
AULA 01, three more on another 24 fps lesson and three on a 60 fps one. Words
shorter than ~90 frames
keep the stock 0/30/150/170 — they are razored halves and never reach the
fade-out anyway. **Retiming is not what makes a word animate**: EXEMPLO renders
static from its first frame, retimed splines and all. Do not reach for the
splines to fix animation; see *The punch word* below for what was actually
approved. That comp is kept as `assets/word-follower.retimed-splines.comp` for
reference only — `assets/word-follower.comp` is the stock-spline one the
container path imports.

An earlier pass retimed these splines by computation (in 30, out 20, hold
absorbs the rest) and it was rejected on sight. Do not reintroduce computed
retiming.

- **An additive fade** — a spline on `Template.Alpha1` that multiplies over the
  Follower without touching an authored keyframe — is implemented and **off by
  default**. It was refused too. Turn it on per item with `"fade_out": 20` only
  when asked.

Two API facts worth keeping:

- A Fusion Title clip **grows** to fit its comp's render range, and does not
  shrink back when the range shrinks — and there is no trim in the API. Writing
  a keyframe past frame N-1 silently lengthens the clip on the timeline.
- `TimelineItem.add_keyframe` does not work on this build (`'NoneType' object is
  not callable`), so clip opacity cannot be ramped from the Edit page. Any fade
  has to live inside the comp.

**Position is not in the comp.** Every instance has Fusion `Center` = 0.5,0.5.
The word reaches screen-left through the *timeline item's* Transform, and those
two numbers are identical on every word in the lesson:

```
Pan  = -514
Tilt =  130
```

**Size is two knobs and the reference edit uses both.** Final scale is Fusion `Size` × Transform
`Zoom`, tuned by eye:

| word | glyphs | Size | Zoom | effective |
|---|---|---|---|---|
| PROCESSAMENTO | 13 | 0.0874 | 0.924 | 0.081 |
| PLANEJAR | 8 | 0.2166 | 0.46 | 0.100 |
| EXEMPLO | 7 | 0.2343 | 0.54 | 0.127 |

No formula fits those. `autosize()` therefore puts the whole scale in `Size`,
leaves `Zoom` at 1, and normalises for width off EXEMPLO (`REF_SIZE` 0.1265 at
7 glyphs). It brackets the real choices to within about ±15% — a starting point
to nudge in the viewer, not the answer.

## 2. Explanation card — `Fusion Composition`

`Master/Assets/GCS` › **Fusion Composition**, the **194-frame** one.

The same folder holds a *second* Fusion Composition of 223 frames which is a
two-`MediaIn` whip transition with `VectorMotionBlur` and no text nodes at all.
Nothing in the media pool properties distinguishes them — same name, same type,
same resolution — which is exactly why the probe refuses to guess. Place the
wrong one and you get a silent, textless flash.

| | |
|---|---|
| Term input | `Text1.StyledText` — the term, UPPERCASE (NEARSHORING, TURNOVER) |
| Body input | `Template.StyledText` — the definition |
| Body shape | **3 lines**, hand-broken with `\n`, ~60–65 characters each, sentence case, ends in a period |
| Background art | `Master/00 - GERAL/Templates/SHAPE_ dicionário.png` |
| Length | 194 frames **@ 24 fps** = 8.1 s |
| Transform | untouched: Pan 0, Tilt 0, Zoom 1 |

The shape to write, on a stand-in term so the three-line break is visible:

```
Text1     TURNOVER
Template  Índice que mede quantas pessoas saem de uma empresa dentro de
          um período, comparado ao total de funcionários dela. Serve para
          medir a rotatividade e o custo de repor cada saída.
```

## 3. The click — `Burnin Click.mp4`

`Master/Assets/GCS` › **Burnin Click.mp4**, 10 frames **@ 30 fps** (0.33 s),
Video + Audio.

Placed on **A2** as audio (`mediaType: 2`), starting **2 frames before** the
title it announces. Every word gets one. The reference edit also uses it as *video* on a high
track to punch slide-image entries — same −2 offset — which this pass does not
do, because it does not place slide images.

## The fps arithmetic

`AppendToTimeline` counts `startFrame` / `endFrame` in the MEDIA's own rate,
and `endFrame` is exclusive. So for N frames of **timeline**:

```
endFrame = round(N × media_fps / timeline_fps)
```

On the 24 fps lesson timeline:

| template | media fps | want | endFrame |
|---|---|---|---|
| Text+ | 60 | 104 | 260 |
| explanation card | 24 | 193 | 193 |
| Burnin Click | 30 | 8 | 10 |

Getting this wrong does not raise: asking `endFrame: 104` for the Text+ lands a
**41-frame** title, because 105 source frames at 60 fps is 1.75 s no matter what
you ask for. Generators stretch past their nominal length happily, which is why
260 > 105 is fine here and would be a frozen tail on real media.

# What to mark, and what not to

## The legend

| kind | color | duration | what it says |
|---|---|---|---|
| `slide` | **Blue** | **spans the section** | a slide belongs on screen for this stretch |
| `word` | Green | point | pop this word on screen here |
| `term` | Yellow | point | this word needs a definition card; the note holds it, ready to use |
| `review` | Pink | point | a human decision — a slip, a fourth-wall break, an error |

Blue is the only kind that carries a duration, because it is the only one whose
*length* is the information: the editor needs the in and the out of the slide,
not a pin. The others mark a moment.

`customData` is namespaced `ost:slide`, `ost:word`, `ost:term`, `ost:review`,
which is how `--clear` finds its own work. **Sand / Red / Purple markers on a
timeline are the rough-cut skill's** (filler, false_start, retake). Leave them:
they carry no custom data, they are notes to the editor, and they are cheap to
bulk-delete by color when the editor wants them gone.

## Slides

A slide belongs where the speaker is talking **to something** rather than just
talking. The test is whether you could write the slide's content down from what
the speaker says. If the answer is "a sentence", it is not a slide — it is a
line, and a word on screen already covers it.

- a **statistic** said out loud ("3,2 vezes", "70% das equipes")
- a **list enumerated aloud** — three or four things in a row, especially a
  negation list ("não tem a ver só com… nem com… nem com…")
- a **comparison** with two sides (processo × talento, dois tipos de cliente)
- a **journey** narrated in steps (contato → proposta → contrato → renovação)
- an **exercise** the viewer is asked to do
- the **title** at the top and the **recap** at the end

**What is not a slide**, however quotable:

- a **question** ("por que isso acontece em toda equipe?")
- a **statement** or a negation ("não é por causa do preço") —
  that is a word on screen, struck through
- a **source credit** already carried by an explanation card
- a **riff** that circles a topic without listing anything
- an **appeal to the viewer** ("olha para a sua agenda agora")
- a **metaphor** with nothing enumerable behind it ("o processo é um espelho")

Marking those came back as *too much of this is not really a slide*. Ten blue
markers across nine minutes was already the outcome of cutting six of them;
start there rather than at sixteen.

The speaker's own verbal cues for a slide change, which are reliable enough to
find the boundaries without watching:

> "vamos em frente" · "vamos seguir em frente" · "bora" · "olha só" ·
> "trazendo o último dado" · "olha bem para mim"

Name them `SLIDE NN · tema` and put the actual line in the note, so the editor
knows what the slide has to say without scrubbing.

## Words

One uppercase word at the emotional peak of a sentence. What earns it:

- the **payoff noun** of a sentence built up to — CONCORRENTE, PREJUÍZO
- a **number** — 3,2x, 70%
- a **term repeated** three or four times in a row (segure a palavra na tela
  atravessando as repetições em vez de piscar uma por vez)
- the two halves of a **contrast**, entering a couple of seconds apart, so the
  screen reads PROCESSO > TALENTO

What does not:

- an abstract noun nobody said with weight
- a word already on the slide behind them
- anything in a sentence that already has a word on screen

**Two words within ~4 s of each other collide.** They cannot share a track — the
plan's overlap check will refuse it. Either shorten the first, or put the second
on V2 so both are up together. Both-up is the right call for a contrast pair;
sequential is right when the second replaces the first.

## Terms

A term needs a card when a viewer outside the field would stall on it. In a
business course that is:

- **acronyms** — ROI, RH, KPI, SLA, EBITDA
- **English business jargon** — turnover, compliance, nearshoring, lifestyle
  corporativo, great place to work
- **accounting and HR terms** — pró-labore, provisão, headcount
- **a label the course invents for its own method**

It does *not* when:

- **the speaker explains it** in the next breath (they often do — "Human
  Resources, o RH" needs a small corner lettering at most, not a card)
- it is jargon **only inside the speaker's own argument**, which they then
  define at length — a coined phrase they immediately unpack is a word on
  screen, not a card
- it is common enough that a card patronises (feedback, líder, propósito)

Write the definition **into the marker note**, already shaped for the card:
three lines, ~60 characters each, sentence case, ending in a period. Neutral
register — the card is a dictionary, not the speaker.

## Review

Flag, do not fix, and never build a graphic on top of one:

- **self-correction on air** — "custo não, investimento, perdão". If the word
  survives the cut, the on-screen word must not appear before they land on the
  right one.
- **fourth-wall breaks** — addressing the editor by name mid-lesson. In a sold
  course these normally come out.
- **spoken stage directions** — "pausa dramática aqui".
- **factual inversions** — the speaker says "diminuição do ROI" while meaning
  cost of replacement. Putting "ROI" on screen would print the error at 60
  point. Say so, offer the alternatives (cut the word, write the term they
  meant, ask for a pickup), and let the editor choose.

## Density

The reference edit — a finished 8.7-minute lesson — carries **3 words and 2
explanation cards**. That is the house rate.

Going richer is legitimate when the ask is "deixa mais dinâmico", but ten words
and four cards in nine minutes is already the generous end. Marking twenty and
building all of them turns a lesson into a lyric video. Mark generously — the
markers cost nothing and can be ignored — then **build a subset** and say
which ones you left as markers only, and why.

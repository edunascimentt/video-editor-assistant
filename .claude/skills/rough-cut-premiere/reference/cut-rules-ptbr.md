# What to cut, in Brazilian Portuguese

Read this before switching any `tier: review` removal on or off.

## The trap that makes English filler lists dangerous here

Every generic filler-word list — including the one inside an NLE's own
`transcript_edit.py` — is `{uh, um, er, erm, uhm, hmm, mm, mhm, ah, eh}`.

Four of those are ordinary, high-frequency Portuguese words:

| token | in English | in Portuguese |
|---|---|---|
| `um` | filler | **"a" / "one"** — an article |
| `a` | article | **"the"** — an article |
| `e` | — | **"and"** |
| `é` | — | **"is"** — the verb *ser*, one of the commonest words in the language |

Cutting them removes grammar, and the damage is silent: the transcript still
reads almost right and the audio sounds subtly broken. `pr_analyze.py` never
matches a bare `um`, `a`, `e` or `é`. Do not add them.

## Hums — removed automatically

The reliable signal is **elongation**, not the vowel. One vowel is a word; a
repeated vowel is a hum.

- Elongated: `éé`, `ééh`, `aaa`, `eee`, `ãã`, `uhh`, `hmmm` — matched by
  `^([aeiouáéíóúâêôãõ])\1+h*n*$`.
- Unambiguous literals: `hum`, `hmm`, `hm`, `mm`, `mmm`, `mhm`, `uhm`, `uh`,
  `uhum`, `ahn`, `ahm`, `hã`, `hãn`, `ehn`, `ãh`, `ahã`.

A large share of hums never reach the transcript at all — WhisperX hears them as
noise and leaves a gap. The silence pass removes those without ever knowing they
were hums. This is why hum removal and silence removal must run together.

## Interjections — proposed, never automatic

`ah`, `eh`, `oh`, `ó`, `ué`, `opa`. Each is a hum most of the time and a beat
some of the time:

- "**Ah**, entendi." — carries the realisation. Keep.
- "E aí você… **ah**… você calcula o frete." — pure hesitation. Cut.

## Discourse markers — always your call

All of these are real words doing real work part of the time.

**Cut aggressively** — they almost never carry meaning:
`tipo`, `tipo assim`, `assim`, `meio que`, `digamos`, `digamos assim`,
`por assim dizer`, `basicamente`, `literalmente`, `praticamente`.

**Cut with care** — they close a thought toward the viewer and removing every
one makes the delivery robotic. Thin them out; do not eliminate them:
`né`, `sabe`, `entendeu`, `entende`, `certo`, `tá`, `beleza`, `cara`.

**Only filler at the head of a sentence** — mid-sentence they are connectives
and the meaning depends on them:
`então`, `aí`, `agora`, `bom`, `olha`.

- "**Então** o custo do CIF já inclui o frete." — connective. Keep.
- "**Então**… **então** deixa eu explicar de outro jeito." — throat-clearing. Cut.

`pr_analyze.py` only proposes this group sentence-initially, where sentence
starts are punctuation from WhisperX plus any pause ≥ 0.7 s.

**Genuinely ambiguous, judge every instance**: `na verdade`, `ou seja`,
`quer dizer`, `enfim`, `realmente`. Each is often the pivot of the sentence.

## Repetition: stammer or emphasis?

Repetition is only a defect when it is *involuntary*, and the tell is timing —
a stammer truncates, emphasis is spoken evenly with real gaps.

Automatic:
- fragment then whole word within 400 ms: `pro— projeto`, `a— a gente`;
- any 2-to-4-word phrase repeated within 800 ms: `eu acho que— eu acho que`;
- a single word repeated within 350 ms, unless it is in the emphasis set.

Emphasis set, never cut on a single repeat: `não`, `nunca`, `sim`, `nada`,
`muito`, `bem`, `já`, `mais`, `só`, `sempre`, `tudo`, `vai`, `calma`.
"Não, não, não, não é isso" is the sentence, not a defect.

Everything else is proposed for review with both timings in the reason, so you
can see whether the speaker stumbled or leaned in.

## Retakes — where you do the real work

The scripted case: the speaker blows a line, stops, and starts the sentence
over. The script catches this **only when the restart reuses the same opening
words**, comparing the tokens after a pause ≥ 0.7 s with the phrase before it.

It cannot catch the common variants:

- the retake is reworded — "O Incoterm CIF significa… deixa eu falar de outro
  jeito. Quando a gente fala em CIF…"
- the speaker corrects himself mid-flow, with no pause at all
- the speaker abandons a whole paragraph and picks up from a different point
- a self-directed aside to the editor — "corta isso", "vou repetir"

Find these by reading the transcript, and add them as `add` entries in
`decisions.json`. Rules for adding one:

- Cut from the start of the abandoned sentence, not from where the error
  happened — half a wrong sentence is worse than the whole thing.
- Keep the *second* take unless the first is clearly better; when in doubt keep
  the one whose ending flows into the next sentence.
- Give rough boundaries. The boundary math is applied to your span exactly as it
  is to a detected one, so it will find the real silence around it.
- Say **why** in `reason`. It ends up in the timeline marker, and in six months
  that note is the only record of the decision.

## The five that keep biting (measured across two lessons)

Every one of these produced a plausible, wrong cut before it was caught. Check
them by name on every pass:

1. **`Olha só` — the proposal removes only `Olha` and leaves `só` dangling.**
   "Olha só, mais um dado" becomes "só, mais um dado". Sentence-initial `Olha`
   is only removable when nothing depends on it: `Olha, está tudo bem` yes;
   `Olha só` no; `Olha para a sua vida` never — there it is the verb *look at*.
2. **Anaphora reads as a retake.** `Isso é processo. Isso é disciplina.` /
   `Será que… Será que…` / `O gestor, aquele que abre o caminho, é quem decide
   primeiro… O gestor é quem sustenta a decisão…` — the detector sees the repeated
   opening and proposes deleting the first, which deletes a whole distinct idea.
   Read the SECOND occurrence: if it completes a different thought, keep both.
3. **Anadiplosis.** `não existe ferramenta melhor do que o método. O método
   foi o que…` — the removed token is the object of the previous clause. Look at the word
   BEFORE the removal: a preposition or article there means the cut breaks the
   grammar.
4. **Filler-shaped words doing real work.** `assim como` (conjunction),
   `tipo de` (noun), `esse cara` (noun — six of them in one lesson), `tá`
   (= está), `sabe quando` (verb), `quer dizer` (verb), `Está certo?` (whole
   question), `Aí é que está` (idiom). The proposal text alone never tells you;
   read the sentence.
5. **The imaginary objector is a character, not hesitation.** He voices the
   student — `Ah, Nathan, pô, mas é tudo culpa minha` — several times per
   lesson. Those `Ah,` / `pô,` / `cara,` are performance. Cutting them flattens
   the bit.

## Rhythm

A cut with every pause removed is exhausting to watch. The defaults keep 130 ms
after the outgoing word and 100 ms before the incoming one at every collapsed
pause, and collapse only gaps over 650 ms.

For a course lesson or explainer, raise both residuals — the viewer needs room
to think. For a short-form or VSL, lower `--min-pause` toward 0.45 and the
residuals toward 0.06.

## Measuring silence

Three findings from validating this on a real 11-minute lesson. All three
produced *plausible* cuts, which is why they had to be measured rather than
reasoned about.

**The noise floor must come from this recording's own pauses.** The first two
attempts both failed, and the second failed silently in the expensive direction —
it produced a clean-looking cut that barely cut anything.

A plain percentile over frames is the naive version: On a lecture the speaker talks
~85% of the time, so even the 10th percentile of frame energy *is speech*. The
gate then sits far above true silence and the boundary walk stops while a
fricative is still going: 16 of 31 pause splices cut into an /s/. `noise_floor`
in `pr_common.py` averages over 300 ms first — which collapses the quiet gaps
*between* phonemes, so only a genuine pause can win — and takes the 2nd
percentile of those window means. That halved the severed sibilants, and it is
still only a fallback.

The real fix is `Envelope.calibrate`: measure the floor from the interiors of the
pauses the **transcript points at**. The global estimator answers "what is the
quietest sustained moment anywhere in this file", which can be one freak silence
at the head. On the test lesson it said **-69.1 dB** while a real pause interior
sits at **-56.8 dB** — 12 dB apart. With the gate set from the global figure, 72%
of pause interior read as *sound*, so the walk never found an end, ran to its
distance limit, and swallowed the pause: only **15%** of the pause time was
recoverable and the pass removed 4.8% of the runtime. Calibrated, the same
material and the same thresholds removed **13.5%**, cutting 199 pauses instead of
12, with zero dirty splices.

Only the interior 60% of each gap is sampled — the edges are the decay of the
outgoing word and the approach of the incoming one, and including them drags the
estimate back up toward speech.

**Level alone cannot tell a severed phoneme from a natural tail.** A decaying
breath inside a kept pause measures just as loud as a truncated /s/. The shape
separates them: a tail falls across the last 30 ms, a sound cut mid-flight is
flat or still rising. `pr_verify` therefore flags on *level and slope*, and
mirrors the test after the cut, where a real word onset rises.

**Letting a sibilant intrude on the removed word was tried and rejected.** When
a filler starts immediately on the heels of an /s/ there is no room to protect
the hiss. Extending the cut 60 ms into the filler's head bought one clean splice
and left four audible fragments of the filler. There is no acoustic answer to
that case — the answer is editorial: switch that filler off.

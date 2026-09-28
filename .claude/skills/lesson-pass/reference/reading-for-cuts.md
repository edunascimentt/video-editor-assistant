# Reading a lesson for the cuts the analyser cannot see

Start with `rough-cut/reference/cut-rules-ptbr.md` (fillers, anaphora,
anadiplosis, `Olha só`, the imaginary objector). This file adds what full
lesson passes taught on top of it — on live-build and re-take-heavy material
especially. Every item was a real defect shipped or nearly shipped.

## Takes

- **Burned openings.** The presenter opens the lesson two to thirteen times
  ("Bom, pessoal, na aula anterior…" again and again), sometimes with studio
  talk in between (mic checks, questions to the crew). Keep the **last complete**
  opening; one `add` covers the rest (a single `add` of 179 s solved one
  lesson's first three minutes).
- **Last complete take wins**, except when an earlier, abandoned take holds
  something the good one lacks (a proper name, a list of examples). Then pink
  marker, not a rescue — rescuing duplicates the claim the good take makes.
- **Abandoned stretches in live builds** are not retakes: a measure started and
  abandoned, a technical error with two minutes of silence and a wrong
  diagnosis (keep the symptom and the fix, drop the detour), homework announced
  and then withdrawn ("no, I'll have to do this one too") — the whole
  announcement goes.
- **"Cut this later" said on camera** is an instruction. Honour it.
- **Off-camera talk after the closing** ("boa noite", a question to the crew) goes.

## Repetition

- **Repeated idea:** the same assertion three or four times in different words
  ("very easy to use" / "makes everything faster" / "processing is much
  faster"). No detector sees it — count assertions in the preview. This was
  the editor's explicit complaint twice.
- **Enumeration with a repeated prefix is not a retake**: "vendas por
  região… vendas por vendedor" are two items. Check every `retake` the
  analyser proposes inside a list.
- **Emphatic repetition stays**: "atenção, atenção", "cuidado,
  cuidado, cuidado", a sentence said twice for weight.
- **Repeated numbers are verification**: "12 mil, 12 mil. 40 mil, 40 mil." is
  the presenter checking two cards match after a filter. Cutting half destroys
  the proof.

## Words that look like filler here

- **`tipo` is content in technical lessons**: "tipo de dados", "tipo inteiro",
  "tabela tipo produto" (10 wrong proposals in one lesson).
- **Acronyms read as hums**: "o III, que é o índice interno" — `III` was
  classified as a hesitation in the **auto** tier and removed. Audit every auto
  `hesitation`/`false_start` by its text.
- **Two-word fillers lose half**: `É isso aí` → `aí` dangling; `E é isso aí,
  pessoal` → `E aí, pessoal`. After switching on any phrase filler, read the
  preview.
- **Lowercase after the splice**: removing a sentence-opening `Então,` that
  leaves the next sentence starting in lowercase means the connector was doing
  the joining. Switch it off.
- **Quotatives**: "ele fala assim, cara, isso aqui não fecha" — `assim` and `cara`
  introduce speech; keep.
- `tá` in "tá bom?" / "Tá vendo?" and `Sabe` in "Sabe a função SOMA?" are the verb.
- The auto `false_start` that ate "falta aqui?" out of "O que falta aqui?
  Falta o…" — a rhetorical question and its answer.

## Silence

- **An announced pause is content**: "vou deixar 10 segundos para você
  refletir" — the 7.7 s after it are the lesson.
- **Screen idle is not always dead air in a build lesson** — but the presenter
  clicking and waiting 10 s for the software to process is. Cut it, and in a
  screen lesson go back to the face over it (see `screen-layout.md`).

## Edge math of manual `add`s

- **Clearance:** only add a manual removal where there is ≥ 300 ms of silence
  at **both** edges. With 20 ms to the next word the boundary walk goes back
  into the previous word — no parameter fixes it; drop the `add`.
- **The `start` must come after the `t1` of the last word you keep.** Written
  inside that word, the word stops being the anchor and the cut enters it.
- **The `end` must stop ~300 ms before the first word of the good take**, or
  `rc_verify` reports that word's head clipped (seen at 40 ms).
- **A removal inside a stretch with no tokens is stretched to the next known
  token** — it can eat an untranscribed question. Either cut it all or keep it all.
- **Stretched tokens need a wider walk**: where the aligner stretched words,
  `--tail-ms 520` may not reach the real end of speech. One lesson needed
  `--tail-ms 900 --tail-ms-sibilant 1000` and, for one edge, `--head-ms 1200`;
  the code's floor prevents leftovers of the removed word, so it is safe.

## The transcripts lie in two known ways

- **The aligner stretches a token over two attempts** (a word measured 2.2–2.6 s
  hid a doubled "de dias de dias" and a whole sentence said twice). Hunt: live tokens longer
  than 1.5 s (`lesson_audit.py` lists them). Confirm by cutting that stretch of
  the **raw** file and transcribing it alone.
- **The re-transcription of the cut invents repetition at splices** ("já já",
  "o nosso o nosso", three attempts of a sentence said once). Never cut a
  repetition seen only in `verify/words/cut.json` — confirm in the plan's raw
  `tokens` or by transcribing the raw window. Cutting on a hallucination cost a
  full redo once.
- **A 1 s island between two splices vanishes from the re-transcription** and
  shows as "lost" in the similarity report. Measure the energy of that stretch
  of `cut.wav` before re-cutting anything.

## Slips the slide must not copy

Mark pink, never fix in the edit: a wrong word the presenter keeps using
(the same slip in two lessons is his, not the recogniser's — confirm by
transcribing the raw window), a technical term mispronounced every time, the same
table called three names, a number that contradicts the screen, a case
described inconsistently (one outcome in minute three, another in minute five).

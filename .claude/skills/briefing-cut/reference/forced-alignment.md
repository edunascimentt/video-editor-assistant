# Word times you can cut and caption on

Three sources of word times, and what each is good for:

| source | text | times | use for |
|---|---|---|---|
| WhisperX cache (rough-cut) | good | good, except **locally around stretched tokens** (1–2 s drift there) | planning; edges only after re-measuring |
| faster-whisper `word_timestamps=True` | good | **no gaps**: each word starts where the previous ends | hearing *what* is said; never edges or subtitles — a word at a cut leaks into the next card and the first word of a span drops |
| forced alignment of checked text (wav2vec2) | yours | tight, with real gaps | subtitles and edges on a finished selection |

## When WhisperX itself will not run

On some macOS builds scipy's Fortran dylibs fail to load inside the WhisperX
environment (`section '__DATA/__thread_bss' has a zero-fill section type`),
which breaks `transcribe-x`, `whisperx` and anything that imports
`transformers`. torch and torchaudio still load. Two fallbacks:

- **text:** `faster_whisper.WhisperModel` directly, with the local
  `faster-whisper-large-v3` snapshot (~15 s per 20 s of audio on CPU).
- **times:** forced alignment below.

## Forced alignment with torchaudio only

Model: the Portuguese wav2vec2 CTC model
(`jonatasgrosman/wav2vec2-large-xlsr-53-portuguese`) from the local Hugging Face
cache — the snapshot with `vocab.json`; the weights may sit in another snapshot.

1. Build `torchaudio.models.wav2vec2_model(**_get_config(cfg), aux_num_out=len(vocab))`
   with `_get_config` from `torchaudio.models.wav2vec2.utils.import_huggingface`.
2. Load the state dict by prefix: `wav2vec2.feature_extractor.`,
   `wav2vec2.feature_projection.`, `wav2vec2.encoder.` → `encoder.transformer`,
   `lm_head.` → `aux`.
3. Per span: 16 kHz mono audio, emissions, the checked text lower-cased and
   mapped to the vocab with `|` between words, then
   `torchaudio.functional.forced_align(emissions, targets, blank=pad_token_id)`.
   Merge token spans into words. ~2.5 s per span on CPU.

Write the aligned words into the rough-cut FALA cache for that clip (keep a
`.bak` first), **removing every old word that overlaps the span** — removing
only those that start inside leaves the stretched token from before the cut.
Then build subtitles.

Forced alignment fails on far, noisy speech (one word stretched to 7 s). There,
use the checked text with the recogniser's times and read the result.

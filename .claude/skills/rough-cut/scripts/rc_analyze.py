#!/usr/bin/env python
"""Turn WhisperX words + audio energy into a reviewable cut plan.

Two responsibilities, deliberately separated from the agent's:

  1. WHERE to cut  -- frame-accurate splice points that never clip a phoneme.
     Word timings from a CTC aligner are systematically short at both ends;
     unvoiced fricatives (the /s/ problem) are the worst case because they carry
     almost no energy below 4 kHz, so the aligner ends the word while the hiss
     is still going and a broadband gate agrees with it. Every splice here is
     pushed outward until BOTH the broadband and the 4 kHz+ band fall back to
     that file's own noise floor, then snapped to the quietest hop in the slack.

  2. WHAT to propose -- silence, hums, filler candidates, stammers, retakes,
     each as a separate removal carrying a reason, a tier and an on/off state.

What it does NOT do is decide the judgement calls. `tier: auto` removals are
mechanical (a hum is a hum). `tier: review` removals are proposals the agent
reads in context and switches off when the word is load-bearing -- in pt-BR
"então", "né" and "aí" are as often structure as they are filler.

usage:
  rc_analyze.py --work-dir DIR [tuning flags]
  rc_analyze.py --work-dir DIR --decisions decisions.json   # re-plan after review
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rc_common as rc  # noqa: E402

# ── pt-BR lexicon ────────────────────────────────────────────────────────────
# The generic English filler set (uh/um/er/ah/eh) is actively DANGEROUS here:
# "um" is the article "a/one", "e" is "and", "a" is "the", and "é" is the verb
# "to be" -- four of the most common words in Portuguese. Nothing below matches
# a bare "um", "a", "e" or "é".

#: Unambiguous hums. Removable without reading the sentence.
HUM_LITERAL = {
    "hum", "hmm", "hm", "hmmm", "mm", "mmm", "mhm", "uhm", "uh", "uhum",
    "ahn", "ahm", "ann", "hã", "hãn", "ehn", "ãh", "ã", "ahã", "ehh", "ãhn",
}
#: Elongation is the tell: "é" is the verb *ser*, "éé" is a hum. Matching bare
#: vowels here would eat the language, so a hum must be either a repeated vowel,
#: a vowel run of 3+, or a trailing breath -- and never 2 distinct vowels, which
#: is "eu", "ai", "ou", "ao".
_VOWELS = "aeiouáéíóúâêôãõ"
_VOWELISH = re.compile(rf"^[{_VOWELS}]+h*n*$", re.UNICODE)
_MURMUR = re.compile(r"^h*m{2,}$|^u+h+m*$|^h+[aãe]+n*$", re.UNICODE)


def is_hum(token: str) -> bool:
    if _MURMUR.match(token):
        return True
    if not _VOWELISH.match(token):
        return False
    if any(a == b for a, b in zip(token, token[1:])):
        return True   # "éé", "aah", "uhh" -- no pt-BR word doubles a letter here
    return len(token) >= 3 and token.endswith("h")
#: Single-token interjections that are USUALLY hums but sometimes carry beat or
#: meaning ("ah, entendi"). Proposed, never automatic.
HUM_AMBIGUOUS = {"ah", "eh", "oh", "ó", "ué", "opa"}

#: Discourse markers. Every one of these is a real word doing a real job some of
#: the time, so they are all `review` tier -- the agent reads the sentence.
FILLER_UNIGRAM = {
    "tipo", "assim", "né", "sabe", "entendeu", "entende", "cara", "enfim",
    "certo", "beleza", "digamos", "basicamente", "literalmente", "praticamente",
    "realmente", "tá", "ok", "pô", "poxa", "olha", "bom", "então", "aí", "agora",
}
#: Markers that are only filler at the head of a sentence; mid-sentence they are
#: connectives that the meaning depends on.
FILLER_SENTENCE_INITIAL_ONLY = {"então", "aí", "agora", "bom", "olha"}
FILLER_NGRAM = [
    ("tipo", "assim"), ("meio", "que"), ("quer", "dizer"), ("ou", "seja"),
    ("veja", "bem"), ("é", "isso"), ("sabe", "como", "é"), ("vamos", "dizer"),
    ("digamos", "assim"), ("por", "assim", "dizer"), ("tipo", "sabe"),
]
#: Portuguese closed-class words. A short word followed by a longer one that
#: starts with the same letters is the signature of a stammer in English
#: ("pro— project"), and in Portuguese it is the signature of ORDINARY GRAMMAR:
#: "e eu", "a atenção", "no nosso", "E esse", "de dentro". Measured on a real
#: 11-minute lesson that rule fired 9 times and was wrong 9 times. Nothing in
#: this set can ever be treated as a clipped restart.
FUNCTION_WORDS = {
    "o", "a", "os", "as", "um", "uma", "uns", "umas", "ao", "aos", "à", "às",
    "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas", "num", "numa",
    "por", "pelo", "pela", "pelos", "pelas", "para", "pra", "pro", "com", "sem",
    "sob", "sobre", "ante", "até", "após", "entre", "contra", "desde", "perante",
    "e", "ou", "mas", "que", "se", "como", "quando", "porque", "pois", "nem",
    "logo", "porém", "portanto", "embora", "enquanto",
    "eu", "tu", "ele", "ela", "nós", "vós", "eles", "elas", "me", "te", "lhe",
    "vos", "lhes", "meu", "minha", "teu", "tua", "seu", "sua", "nosso", "nossa",
    "este", "esta", "esse", "essa", "isso", "isto", "aquele", "aquela", "aquilo",
    "qual", "quem", "cujo", "onde", "todo", "toda", "cada", "outro", "outra",
    "é", "são", "foi", "era", "tem", "ter", "ser", "vai", "vou", "vem", "dá",
    "faz", "há", "seja", "tá", "tô", "não", "sim", "já", "ainda", "aqui", "ali",
    "lá", "cá", "muito", "mais", "menos", "bem", "mal", "só", "tão", "tal",
    "aí", "daí", "né", "ó", "assim", "agora", "então",
}

#: Repetition of these reads as emphasis far more often than as a stammer.
EMPHASIS_OK = {"não", "nunca", "sim", "nada", "muito", "bem", "já", "mais",
               "só", "sempre", "tudo", "vai", "calma"}

# ── tuning defaults ──────────────────────────────────────────────────────────

D = {
    # silence
    # Defaults below were swept against a real 11-minute lesson and chosen at the
    # point where the acoustic check still reported ZERO dirty splices out of 199.
    "min_pause": 0.22,          # a gap longer than this is dead air
    "pause_residual_tail": 0.04,  # ambience kept AFTER the outgoing word
    "pause_residual_head": 0.03,  # ambience kept BEFORE the incoming word
    # boundary protection
    "tail_ms": 400,             # how far past a word's aligned end we may hunt
    "tail_ms_sibilant": 620,    # ...when that word ends in /s/, /f/, /ʃ/, /x/
    "head_ms": 260,             # how far before a word's aligned start
    "head_ms_hard": 360,        # ...when it opens on a stop burst or fricative
    "settle_ms": 25,            # slack searched for the quietest splice frame
    "min_pad_ms": 45,           # never splice tighter than this to a kept word
    "onset_guard_ms": 35,       # never eat into a removed word's own onset
    # Counter-intuitive but measured: a LOWER gate removes LESS. The walk has to
    # travel further to reach it, eats the pause it was meant to protect, and the
    # shrunken removals fall under min_removal and vanish. Swept 0->16 dB: the
    # yield peaks where the splices are still clean, which is here.
    "bb_margin_db": 9.0,        # broadband gate above THIS RECORDING's room tone
    "hi_margin_db": 9.0,        # 4 kHz+ gate ...
    "hi_margin_db_sibilant": 5.0,  # ...loosened when a sibilant is expected
    "silence_guard_db": 15.0,   # a "pause" this far over room tone is not a pause
    "calibration_pause": 0.40,  # gaps at least this long teach it what a pause is
    # word-level detection
    "false_start_gap": 0.80,
    "unigram_repeat_gap": 0.35,
    "fragment_gap": 0.40,
    "retake_pause": 0.70,
    "retake_lookahead": 8,
    "retake_min_match": 2,
    # assembly
    "min_removal": 0.08,
}

# ── token stream ─────────────────────────────────────────────────────────────


class Media:
    """One timeline item's window onto a media file, plus its energy curves."""

    def __init__(self, item: Dict[str, Any], env: Optional[rc.Envelope]):
        self.item = item
        self.env = env
        self.rec0 = float(item["start"])
        self.rec1 = float(item["end"])
        self.src0 = float(item["source_start_seconds"] or 0.0)
        self.src1 = float(item["source_end_seconds"] or 0.0)

    def bind(self, tl_fps: float) -> None:
        self.rec0_s = self.rec0 / tl_fps
        self.rec1_s = self.rec1 / tl_fps

    def to_record(self, file_t: float) -> float:
        return self.rec0_s + (file_t - self.src0)

    def to_file(self, rec_t: float) -> float:
        return self.src0 + (rec_t - self.rec0_s)

    def covers(self, rec_t: float) -> bool:
        return self.rec0_s - 1e-6 <= rec_t <= self.rec1_s + 1e-6


def build_tokens(timeline: Dict[str, Any], words_index: Dict[str, str],
                 work: Path) -> Tuple[List[Dict[str, Any]], List[Media], List[str]]:
    """Words from every audible item, in TIMELINE record seconds."""
    tl_fps = float(timeline["timeline_fps"])
    notes: List[str] = []

    items = [i for i in timeline["items"] if i["track_type"] == "audio"]
    if not items:
        items = [i for i in timeline["items"] if i["track_type"] == "video"]
        notes.append("No audio items on this timeline — reading words off the video items.")

    cutable, medias = [], []
    for item in items:
        why = None
        if item.get("retimed"):
            why = "retimed"
        elif not item.get("file_path"):
            why = "no file path"
        elif not item.get("source_fps"):
            why = "unknown source fps"
        elif item.get("source_start_seconds") is None or item.get("source_end_seconds") is None:
            why = "unreadable source span"
        if why:
            notes.append(f"carried through UNCUT ({why}): {item['name']} "
                         f"[{item['track_type']} {item['track_index']}]")
            continue
        cutable.append(item)

    docs: Dict[str, Any] = {}
    tokens: List[Dict[str, Any]] = []
    for item in cutable:
        path = item["file_path"]
        media = Media(item, None)
        media.bind(tl_fps)
        if path not in docs:
            jpath = words_index.get(path)
            if not jpath:
                notes.append(f"no transcript for {path} — its items are carried through UNCUT")
                continue
            docs[path] = rc.read_json(Path(jpath))
        try:
            media.env = rc.Envelope.cached(path, work / "energy")
        except Exception as exc:  # media offline mid-run, exotic codec, ...
            notes.append(f"no energy curve for {Path(path).name} ({exc}); "
                         "boundaries fall back to fixed pads on its items")
        medias.append(media)

        for seg_index, seg in enumerate(docs[path].get("segments") or []):
            for word in seg.get("words") or []:
                t0, t1 = word.get("start"), word.get("end")
                if not isinstance(t0, (int, float)) or not isinstance(t1, (int, float)):
                    # WhisperX leaves numerals and symbols unaligned. They are
                    # real speech, so they must never be cut blind: they are
                    # dropped from the token stream, which makes the surrounding
                    # gap un-analysable and therefore protected.
                    continue
                if not (media.src0 - 1e-3 <= t0 and t1 <= media.src1 + 1e-3):
                    continue
                tokens.append({
                    "i": 0,
                    "t0": media.to_record(float(t0)),
                    "t1": media.to_record(float(t1)),
                    "w": str(word.get("word", "")),
                    "n": rc.norm(word.get("word")),
                    "score": float(word.get("score") or 0.0),
                    "seg": seg_index,
                    "media": id(media),
                })

    tokens = [t for t in sorted(tokens, key=lambda t: (t["t0"], t["t1"])) if t["n"]]
    for index, tok in enumerate(tokens):
        tok["i"] = index
    return tokens, medias, notes


def calibrate_floors(tokens, medias, cfg, notes) -> None:
    """Teach every media what a pause sounds like in ITS OWN recording.

    Only the interior 60% of each gap is used: the edges of a gap are the decay
    of the outgoing word and the approach of the incoming one, and including
    them would drag the estimate back up toward speech.
    """
    min_gap = cfg["calibration_pause"]
    for media in medias:
        if media.env is None:
            continue
        windows = []
        for a, b in zip(tokens, tokens[1:]):
            gap = b["t0"] - a["t1"]
            if gap < min_gap or not media.covers(a["t1"]) or not media.covers(b["t0"]):
                continue
            lo, hi = a["t1"] + 0.3 * gap, b["t0"] - 0.3 * gap
            windows.append((media.to_file(lo), media.to_file(hi)))
        before = media.env.floor_bb
        if media.env.calibrate(windows):
            notes.append(
                f"room tone for {Path(media.item['file_path']).name}: "
                f"{media.env.floor_bb:.1f} dB, measured across {len(windows)} pauses "
                f"(global estimate was {before:.1f} dB)")
        else:
            notes.append(
                f"{Path(media.item['file_path']).name}: too little pause to measure room "
                f"tone; falling back to the global estimate ({before:.1f} dB)")


# ── detection ────────────────────────────────────────────────────────────────


def sentence_starts(tokens: Sequence[Dict[str, Any]], cfg: Dict[str, float]) -> set:
    """Indices that open a sentence: first token, after end punctuation, or
    after a pause long enough to be a full stop in speech."""
    starts = {0} if tokens else set()
    for i in range(1, len(tokens)):
        prev = tokens[i - 1]
        if re.search(r"[.!?…:;]\s*$", str(prev["w"])):
            starts.add(i)
        elif tokens[i]["t0"] - prev["t1"] >= cfg["retake_pause"]:
            starts.add(i)
    return starts


def detect_words(tokens: List[Dict[str, Any]], cfg: Dict[str, float]) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    starts = sentence_starts(tokens, cfg)
    # Two independent pools. Within a pool a token is claimed once, so a phrase
    # is not proposed twice. ACROSS pools they may nest: a hum inside an
    # abandoned take is its own removal, so switching the take back on -- or
    # off -- never silently drags the hum with it.
    pools: Dict[str, set] = {"span": set(), "word": set()}

    def claim(idx: Sequence[int], kind: str, tier: str, reason: str, conf: float,
              pool: str = "span"):
        taken = pools[pool]
        idx = list(idx)
        if any(i in taken for i in idx):
            return
        taken.update(idx)
        found.append({"kind": kind, "tier": tier, "tokens": idx,
                      "reason": reason, "confidence": round(conf, 2)})

    # -- retake across a pause: the scripted-line restart ---------------------
    ordered = sorted(starts)
    for si, start in enumerate(ordered):
        if start == 0:
            continue
        gap = tokens[start]["t0"] - tokens[start - 1]["t1"]
        if gap < cfg["retake_pause"]:
            continue
        after = [tokens[start + k]["n"] for k in range(
            min(int(cfg["retake_lookahead"]), len(tokens) - start))]
        prev_start = ordered[si - 1] if si else 0
        before = [tokens[k]["n"] for k in range(prev_start, start)]
        best = 0
        for k in range(min(len(after), len(before)), int(cfg["retake_min_match"]) - 1, -1):
            if before[:k] == after[:k]:
                best = k
                break
        if not best:
            continue
        said = " ".join(tokens[k]["w"].strip() for k in range(prev_start, start))
        again = " ".join(after[:best])
        claim(range(prev_start, start), "retake", "review",
              f"abandoned take: {said!r} restarted as {again!r}…", 0.65)

    # -- immediate n-gram repetition ------------------------------------------
    for n in range(4, 0, -1):
        for i in range(len(tokens) - 2 * n + 1):
            first = [tokens[i + k]["n"] for k in range(n)]
            second = [tokens[i + n + k]["n"] for k in range(n)]
            if first != second or not all(first):
                continue
            gap = tokens[i + n]["t0"] - tokens[i + n - 1]["t1"]
            if gap > cfg["false_start_gap"]:
                continue
            phrase = " ".join(tokens[i + k]["w"].strip() for k in range(n))
            if n >= 2:
                claim(range(i, i + n), "false_start", "auto",
                      f"repeated restart {phrase!r} ({gap * 1000:.0f} ms apart)", 0.88)
            elif (first[0] not in EMPHASIS_OK and gap <= cfg["unigram_repeat_gap"]):
                claim([i], "false_start", "auto",
                      f"stammer {phrase!r} ({gap * 1000:.0f} ms apart)", 0.75)
            else:
                claim([i], "false_start", "review",
                      f"repetition {phrase!r} ({gap * 1000:.0f} ms apart) — "
                      "stammer, or deliberate emphasis?", 0.45)

    # -- stammered fragment: "a- a gente", "pro- projeto" ---------------------
    for i in range(len(tokens) - 1):
        a, b = tokens[i], tokens[i + 1]
        gap = b["t0"] - a["t1"]
        if not (2 <= len(a["n"]) <= 3 and len(b["n"]) > len(a["n"])
                and b["n"].startswith(a["n"]) and gap <= cfg["fragment_gap"]):
            continue
        if a["n"] in FUNCTION_WORDS:
            continue   # "no nosso", "de dentro" -- grammar, not a stammer
        tier = "auto" if gap <= 0.25 else "review"
        claim([a["i"]], "false_start", tier,
              f"clipped restart {a['w'].strip()!r} before {b['w'].strip()!r} "
              f"({gap * 1000:.0f} ms apart)", 0.85 if tier == "auto" else 0.5)

    # -- hums -----------------------------------------------------------------
    for tok in tokens:
        n = tok["n"]
        if n in HUM_LITERAL or is_hum(n):
            claim([tok["i"]], "hesitation", "auto",
                  f"hum {tok['w'].strip()!r}", 0.95, pool="word")
        elif n in HUM_AMBIGUOUS:
            claim([tok["i"]], "hesitation", "review",
                  f"interjection {tok['w'].strip()!r} — a hum, or a beat that carries meaning",
                  0.55, pool="word")

    # -- discourse fillers ----------------------------------------------------
    for phrase in sorted(FILLER_NGRAM, key=len, reverse=True):
        n = len(phrase)
        for i in range(len(tokens) - n + 1):
            if tuple(tokens[i + k]["n"] for k in range(n)) == phrase:
                text = " ".join(tokens[i + k]["w"].strip() for k in range(n))
                claim(range(i, i + n), "filler", "review",
                      f"filler phrase {text!r}", 0.6, pool="word")
    for tok in tokens:
        n, i = tok["n"], tok["i"]
        if n not in FILLER_UNIGRAM:
            continue
        initial = i in starts
        if n in FILLER_SENTENCE_INITIAL_ONLY and not initial:
            continue  # mid-sentence these are connectives, not padding
        conf = 0.7 if initial else 0.5
        claim([i], "filler", "review",
              f"filler {tok['w'].strip()!r}" + (" (sentence-initial)" if initial else ""),
              conf, pool="word")

    for row in found:
        row["tokens"] = sorted(row["tokens"])
    found.sort(key=lambda r: r["tokens"][0])
    return found


# ── boundary refinement ──────────────────────────────────────────────────────


def _media_for(medias: Sequence[Media], rec_t: float) -> Optional[Media]:
    for m in medias:
        if m.env is not None and m.covers(rec_t):
            return m
    return None


def refine_out(medias, t_end: float, ceiling: float, sibilant: bool,
               cfg: Dict[str, float]) -> float:
    """Latest safe splice point after a kept word ends.

    Walks forward while either band is still above this file's own noise floor,
    then snaps to the quietest hop in the slack that follows. `sibilant` widens
    the search and lowers the high-band gate, because that is exactly the case
    where the aligner's end time lands mid-hiss.
    """
    pad = cfg["min_pad_ms"] / 1000.0
    limit = (cfg["tail_ms_sibilant"] if sibilant else cfg["tail_ms"]) / 1000.0
    media = _media_for(medias, t_end)
    if media is None:
        return min(max(t_end + pad, t_end), ceiling)
    env, hop = media.env, media.env.hop
    hi_margin = cfg["hi_margin_db_sibilant"] if sibilant else cfg["hi_margin_db"]
    t = t_end
    stop = min(t_end + limit, ceiling)
    while t < stop and env.loud(media.to_file(t), cfg["bb_margin_db"], hi_margin):
        t += hop
    window_end = min(t + cfg["settle_ms"] / 1000.0, ceiling)
    if window_end > t:
        quiet = env.quietest(media.to_file(t), media.to_file(window_end))
        t = media.to_record(quiet)
    return min(max(t, min(t_end + pad, ceiling)), ceiling)


def refine_in(medias, t_start: float, floor: float, hard_onset: bool,
              cfg: Dict[str, float]) -> float:
    """Earliest safe splice point before a kept word begins (mirror of above)."""
    pad = cfg["min_pad_ms"] / 1000.0
    limit = (cfg["head_ms_hard"] if hard_onset else cfg["head_ms"]) / 1000.0
    media = _media_for(medias, t_start)
    if media is None:
        return max(min(t_start - pad, t_start), floor)
    env, hop = media.env, media.env.hop
    t = t_start
    stop = max(t_start - limit, floor)
    while t > stop and env.loud(media.to_file(t), cfg["bb_margin_db"], cfg["hi_margin_db"]):
        t -= hop
    window_start = max(t - cfg["settle_ms"] / 1000.0, floor)
    if t > window_start:
        quiet = env.quietest(media.to_file(window_start), media.to_file(t))
        t = media.to_record(quiet)
    return max(min(t, max(t_start - pad, floor)), floor)


# ── plan assembly ────────────────────────────────────────────────────────────


def assemble(tokens, medias, word_removals, manual, cfg, span) -> List[Dict[str, Any]]:
    """Word removals + silence, each turned into a boundary-safe record span."""
    lo, hi = span
    removed_tokens = set()
    for row in word_removals:
        if row.get("state", "on") == "on":
            removed_tokens.update(row["tokens"])
    kept = [t for t in tokens if t["i"] not in removed_tokens]

    out: List[Dict[str, Any]] = []

    def edges(first_removed_t0: Optional[float], last_removed_t1: Optional[float],
              prev_tok, next_tok, kind: str) -> Optional[Tuple[float, float]]:
        guard = cfg["onset_guard_ms"] / 1000.0
        prev_end = prev_tok["t1"] if prev_tok else lo
        next_start = next_tok["t0"] if next_tok else hi
        sibilant = bool(prev_tok and rc.ends_sibilant(prev_tok["n"]))
        # An in-point may not reach back past the removed audio's own tail, and
        # an out-point may not reach forward into its onset. Letting a sibilant
        # tail intrude on the removed word's head instead was tried and REJECTED:
        # on real material it bought one splice and left 4 kept fragments of the
        # filler audible. When a filler starts hard on the heels of an /s/ there
        # is no acoustic answer -- the answer is editorial, and rc_verify says so.
        floor = (last_removed_t1 + guard) if last_removed_t1 is not None else prev_end
        ceiling = (first_removed_t0 - guard) if first_removed_t0 is not None else next_start
        cut_out = refine_in(medias, next_start, max(floor, prev_end),
                            rc.starts_hard(next_tok["n"]) if next_tok else False, cfg)
        cut_in = refine_out(medias, prev_end, min(ceiling, cut_out), sibilant, cfg)
        # Hard invariant: a removal may never reach inside a kept word. When the
        # neighbours are packed too tightly for any protection at all, the
        # splice degenerates to the aligned boundary and the acoustic check in
        # rc_verify flags it -- it never silently eats a syllable.
        cut_in = max(cut_in, prev_end)
        cut_out = min(cut_out, next_start)
        if kind == "silence":
            cut_in += cfg["pause_residual_tail"]
            cut_out -= cfg["pause_residual_head"]
        if cut_out - cut_in < cfg["min_removal"]:
            return None
        return cut_in, cut_out

    def loudness_at(t: float) -> float:
        media = _media_for(medias, t)
        if media is None:
            return 0.0
        env = media.env
        return float(env.bb[env.idx(media.to_file(t))] - env.floor_bb)

    def quiet_at(t: float) -> bool:
        """Is this really dead air? Deliberately a LOOSER test than the gate the
        boundary walk uses. The walk has to be twitchy -- it is hunting the last
        breath of a fricative. This one only has to catch a "pause" that is
        obviously full of sound, and a twitchy test here refuses honest silences:
        at the walk's own thresholds it threw out pauses sitting 1-5 dB over the
        floor, which are silence by any reasonable reading."""
        return loudness_at(t) <= cfg["silence_guard_db"]

    # word-driven removals
    for index, row in enumerate(word_removals):
        idx = row["tokens"]
        first, last = tokens[idx[0]], tokens[idx[-1]]
        prev_tok = next((t for t in reversed(kept) if t["i"] < idx[0]), None)
        next_tok = next((t for t in kept if t["i"] > idx[-1]), None)
        span_ = edges(first["t0"], last["t1"], prev_tok, next_tok, row["kind"])
        entry = dict(row)
        entry["id"] = row.get("id") or f"r{index:04d}"
        entry["text"] = " ".join(tokens[i]["w"].strip() for i in idx)
        entry["raw_start"], entry["raw_end"] = round(first["t0"], 3), round(last["t1"], 3)
        entry["sibilant_before"] = bool(prev_tok and rc.ends_sibilant(prev_tok["n"]))
        entry["hard_onset_after"] = bool(next_tok and rc.starts_hard(next_tok["n"]))
        if span_ and row.get("state", "on") == "on":
            entry["start"], entry["end"] = round(span_[0], 3), round(span_[1], 3)
        else:
            entry["start"], entry["end"] = entry["raw_start"], entry["raw_end"]
            if row.get("state", "on") == "on" and not span_:
                entry["state"] = "off"
                entry["reason"] += " [dropped: nothing left to cut after boundary protection]"
        out.append(entry)

    # manual removals from the agent, given in record seconds
    for index, row in enumerate(manual):
        entry = {
            "id": row.get("id") or f"m{index:04d}",
            "kind": row.get("kind", "manual"),
            "tier": "manual",
            "state": row.get("state", "on"),
            "tokens": [],
            "reason": row.get("reason", "removed by review"),
            "confidence": 1.0,
            "raw_start": round(float(row["start"]), 3),
            "raw_end": round(float(row["end"]), 3),
        }
        a, b = float(row["start"]), float(row["end"])
        prev_tok = next((t for t in reversed(kept) if t["t1"] <= a + 1e-6), None)
        next_tok = next((t for t in kept if t["t0"] >= b - 1e-6), None)
        inner = [t for t in kept if t["t0"] >= a - 1e-6 and t["t1"] <= b + 1e-6]
        span_ = edges(inner[0]["t0"] if inner else a, inner[-1]["t1"] if inner else b,
                      prev_tok, next_tok, entry["kind"])
        entry["text"] = " ".join(t["w"].strip() for t in inner)
        if span_ and entry["state"] == "on":
            entry["start"], entry["end"] = round(span_[0], 3), round(span_[1], 3)
        else:
            entry["start"], entry["end"] = entry["raw_start"], entry["raw_end"]
        removed_tokens.update(t["i"] for t in inner)
        out.append(entry)

    # silence, computed last so an "éé" flanked by two pauses becomes ONE cut
    kept = [t for t in tokens if t["i"] not in removed_tokens]
    active = rc.merge([(r["start"], r["end"]) for r in out if r.get("state", "on") == "on"])

    def free(a: float, b: float) -> bool:
        return not any(x < b and a < y for x, y in active)

    silences = []
    if kept:
        pairs = [(None, kept[0])] + list(zip(kept, kept[1:])) + [(kept[-1], None)]
        for prev_tok, next_tok in pairs:
            a = prev_tok["t1"] if prev_tok else lo
            b = next_tok["t0"] if next_tok else hi
            if b - a < cfg["min_pause"] or not free(a, b):
                continue
            span_ = edges(None, None, prev_tok, next_tok, "silence")
            if not span_:
                continue
            label = ("head" if prev_tok is None else
                     "tail" if next_tok is None else f"{b - a:.2f} s pause")
            # A gap between WORDS is not proof of a gap in SOUND. Where the
            # audio never comes down to the room tone, something is still
            # happening that the recogniser did not write down -- a swallowed
            # word, a mumble, an off-mic line. Measured on a real lesson this
            # caught splices sitting 30 dB above the floor. Those are proposed
            # OFF, with the level in the reason, so a human decides.
            noisy = [t for t in (span_[0], span_[1]) if not quiet_at(t)]
            state, reason = "on", f"dead air ({label})"
            if noisy:
                state = "off"
                reason = (f"{label}, but the audio never reaches room tone here "
                          f"({loudness_at(noisy[0]):+.0f} dB over the floor) — "
                          "probably speech the transcript missed. Listen before "
                          "switching this on.")
            silences.append({
                "id": f"s{len(silences):04d}", "kind": "silence", "tier": "auto",
                "state": state, "tokens": [], "text": "",
                "reason": reason, "confidence": 0.9,
                "raw_start": round(a, 3), "raw_end": round(b, 3),
                "start": round(span_[0], 3), "end": round(span_[1], 3),
                "sibilant_before": bool(prev_tok and rc.ends_sibilant(prev_tok["n"])),
                "hard_onset_after": bool(next_tok and rc.starts_hard(next_tok["n"])),
            })
    out.extend(silences)
    out.sort(key=lambda r: (r["start"], r["end"]))
    return out


# ── reporting ────────────────────────────────────────────────────────────────


def tc(seconds: float, fps: float, start_frame: int = 0) -> str:
    frames = int(round(seconds * fps)) + int(start_frame)
    f = int(round(fps))
    return (f"{frames // (3600 * f):02d}:{frames // (60 * f) % 60:02d}:"
            f"{frames // f % 60:02d}:{frames % f:02d}")


def report(plan: Dict[str, Any], max_rows: int = 40) -> str:
    fps, sf = plan["timeline_fps"], plan["timeline_start_frame"]
    st = plan["stats"]
    lines = [
        f"# Rough cut plan — {plan['timeline']}",
        "",
        f"source {rc.hms(st['source_seconds'])} → cut {rc.hms(st['result_seconds'])} "
        f"({st['removed_seconds']:.1f}s removed, {st['removed_pct']:.1f}%)",
        f"{st['splices']} splices · {st['on']} removals on / {st['total']} proposed",
        "",
        "| kind | on | off | seconds |",
        "|---|---:|---:|---:|",
    ]
    for kind in ("silence", "hesitation", "false_start", "filler", "retake", "manual"):
        k = st["by_kind"].get(kind)
        if k:
            lines.append(f"| {kind} | {k['on']} | {k['off']} | {k['seconds']:.1f} |")
    review = [r for r in plan["removals"] if r["tier"] == "review"]
    if review:
        lines += ["", f"## Needs a judgement call ({len(review)})", "",
                  "Switch any of these off in decisions.json if the word is load-bearing.",
                  "", "| id | tc | kind | text | why |", "|---|---|---|---|---|"]
        for r in review[:max_rows]:
            lines.append(f"| `{r['id']}` | {tc(r['start'], fps, sf)} | {r['kind']} | "
                         f"{(r['text'] or '—')[:40]} | {r['reason'][:90]} |")
        if len(review) > max_rows:
            lines.append(f"| … | | | | {len(review) - max_rows} more in cutplan.json |")
    auto = [r for r in plan["removals"] if r["tier"] == "auto" and r["kind"] != "silence"]
    if auto:
        lines += ["", f"## Applied automatically ({len(auto)} word-level + "
                  f"{st['by_kind'].get('silence', {}).get('on', 0)} silences)", "",
                  "| id | tc | kind | text | why |", "|---|---|---|---|---|"]
        for r in auto[:max_rows]:
            lines.append(f"| `{r['id']}` | {tc(r['start'], fps, sf)} | {r['kind']} | "
                         f"{(r['text'] or '—')[:40]} | {r['reason'][:90]} |")
        if len(auto) > max_rows:
            lines.append(f"| … | | | | {len(auto) - max_rows} more in cutplan.json |")
    protected = [r for r in plan["removals"]
                 if r.get("state") == "on" and r.get("sibilant_before")]
    lines += ["", "## Boundary protection", "",
              f"- {len(protected)} splices follow a word ending in a sibilant; those got "
              f"up to {plan['params']['tail_ms_sibilant']:.0f} ms of extra tail and a "
              f"{plan['params']['hi_margin_db_sibilant']:.0f} dB high-band gate.",
              f"- every splice was pushed out to this file's own noise floor, then snapped "
              f"to the quietest point within {plan['params']['settle_ms']:.0f} ms."]
    if plan["notes"]:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in plan["notes"]]
    return "\n".join(lines) + "\n"


# ── main ─────────────────────────────────────────────────────────────────────


def build(work: Path, cfg: Dict[str, float], decisions: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    timeline = rc.read_json(work / "timeline.json")
    words_index = rc.read_json(work / "words" / "index.json")
    tl_fps = float(timeline["timeline_fps"])

    tokens, medias, notes = build_tokens(timeline, words_index, work)
    if not tokens:
        raise SystemExit("No usable words — check the transcript and the item warnings.")
    # Must run before any boundary math: every gate below is relative to this.
    calibrate_floors(tokens, medias, cfg, notes)
    notes = list(timeline.get("warnings") or []) + notes

    lo = timeline["timeline_start_frame"] / tl_fps
    hi = timeline["timeline_end_frame"] / tl_fps

    word_removals = detect_words(tokens, cfg)
    for index, row in enumerate(word_removals):
        row["id"] = f"r{index:04d}"
        row["state"] = "on"

    manual: List[Dict[str, Any]] = []
    if decisions:
        off = set(decisions.get("off") or [])
        on = set(decisions.get("on") or [])
        for row in word_removals:
            if row["id"] in off:
                row["state"] = "off"
            if row["id"] in on:
                row["state"] = "on"
        manual = list(decisions.get("add") or [])

    removals = assemble(tokens, medias, word_removals, manual, cfg, (lo, hi))
    if decisions:
        off = set(decisions.get("off") or [])
        for row in removals:
            if row["id"] in off:
                row["state"] = "off"

    active = rc.merge([(r["start"], r["end"]) for r in removals if r["state"] == "on"])
    keep = rc.complement(active, lo, hi)

    by_kind: Dict[str, Dict[str, float]] = {}
    for r in removals:
        k = by_kind.setdefault(r["kind"], {"on": 0, "off": 0, "seconds": 0.0})
        k["on" if r["state"] == "on" else "off"] += 1
        if r["state"] == "on":
            k["seconds"] += r["end"] - r["start"]

    plan = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "project": timeline["project"],
        "timeline": timeline["timeline"],
        "timeline_fps": tl_fps,
        "timeline_start_frame": timeline["timeline_start_frame"],
        "params": cfg,
        "room_tone": next(
            ({"bb": round(m.env.floor_bb, 2), "hi": round(m.env.floor_hi, 2),
              "source": Path(m.item["file_path"]).name}
             for m in medias if m.env is not None), {"bb": None, "hi": None}),
        "notes": notes,
        "tokens": [{k: (round(v, 3) if isinstance(v, float) else v)
                    for k, v in t.items() if k != "media"} for t in tokens],
        "removals": removals,
        "keep": [[round(a, 3), round(b, 3)] for a, b in keep],
        "stats": {
            "source_seconds": round(hi - lo, 3),
            "removed_seconds": round(rc.total(active), 3),
            "result_seconds": round(rc.total(keep), 3),
            "removed_pct": round(100.0 * rc.total(active) / max(hi - lo, 1e-6), 2),
            "splices": max(0, len(keep) - 1),
            "on": sum(1 for r in removals if r["state"] == "on"),
            "total": len(removals),
            "words": len(tokens),
            "by_kind": {k: {"on": v["on"], "off": v["off"], "seconds": round(v["seconds"], 2)}
                        for k, v in by_kind.items()},
        },
    }
    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--decisions", help="review decisions JSON: {off:[ids], on:[ids], add:[spans]}")
    for key, value in D.items():
        ap.add_argument(f"--{key.replace('_', '-')}", type=float, default=None,
                        help=f"default {value}")
    args = ap.parse_args()

    cfg = dict(D)
    for key in D:
        value = getattr(args, key)
        if value is not None:
            cfg[key] = value

    work = Path(args.work_dir)
    decisions = rc.read_json(Path(args.decisions)) if args.decisions else None
    plan = build(work, cfg, decisions)
    rc.write_json(work / "cutplan.json", plan)
    (work / "review.md").write_text(report(plan), encoding="utf-8")

    st = plan["stats"]
    print(f"{st['words']} words · {st['total']} removals proposed "
          f"({st['on']} on) · {st['splices']} splices")
    print(f"{rc.hms(st['source_seconds'])} -> {rc.hms(st['result_seconds'])} "
          f"({st['removed_pct']:.1f}% removed)")
    for kind, k in sorted(st["by_kind"].items()):
        print(f"  {kind:12s} on={k['on']:4d} off={k['off']:4d} {k['seconds']:7.1f}s")
    for n in plan["notes"]:
        print(f"NOTE: {n}")
    print(f"\nwrote {work / 'cutplan.json'} and {work / 'review.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

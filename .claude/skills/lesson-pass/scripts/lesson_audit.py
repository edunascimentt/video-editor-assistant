#!/usr/bin/env python3
"""Point at the places in a rough-cut plan that the analyser cannot judge.

    lesson_audit.py WORK_DIR [--plan cutplan.json] > audit.md

Reads the rough-cut work dir (cutplan.json: tokens + removals) and lists, with
times and context, the things that went wrong on real lessons when nobody
looked:

  1. restart cues        — "vou começar de novo", "cancela", "errei", "corta isso"…
                           the speaker abandoning a take out loud
  2. openings            — every greeting / "na aula anterior": more than one
                           means burned openings; the LAST complete one stays
  3. repeated phrases    — the same 4+ words said twice within 90 s in what is
                           kept (retakes re-said differently start like this)
  4. stretched tokens    — live words longer than 1.5 s: the aligner gave one
                           word the time of two attempts, hiding a repetition
  5. announced pauses    — silence removals > 2 s right after "segundos",
                           "refletir", "pensa"… the pause IS the content
  6. lowercase after cut — a removal that took a sentence-opening connector
                           ("Então,") and left the next sentence starting lowercase
  7. auto word removals  — every false_start / hesitation in tier auto, with its
                           text: acronyms read as hums ("III") and anadiplosis
                           ("X. X é…") get cut here without review

It proposes nothing. Everything it prints needs a human reading of the
transcript around it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata

RESTART = re.compile(
    r"\b(come[cç]ar de novo|come[cç]o de novo|iniciar de novo|inicia de novo|de novo aqui|"
    r"cancela|vamos cancelar|errei|perdi aqui|vou voltar|voltar isso|corta(r)? (isso|essa)|"
    r"pode cortar|vou pausar|faz de novo|repete|repetir|deixa eu refazer|refaz)\b", re.I)
OPENING = re.compile(
    r"\b(ol[aá],? (pessoal|galera)|seja(m)? (muito )?bem[- ]vindo|bom,? pessoal|fala,? pessoal|"
    r"na aula anterior|nessa aula|nesta aula|e a[ií],? pessoal)\b", re.I)
PAUSE_CUE = re.compile(r"\b(segundos?|refletir|reflex[aã]o|pensa(r)?|pausa|respira)\b", re.I)


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if c.isalnum() or c.isspace())


def mmss(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work")
    ap.add_argument("--plan", default="cutplan.json")
    ap.add_argument("--long", type=float, default=1.5, help="stretched-token threshold, seconds")
    ap.add_argument("--window", type=float, default=90.0, help="repeated-phrase window, seconds")
    ap.add_argument("--ngram", type=int, default=4)
    a = ap.parse_args()

    plan = json.load(open(os.path.join(a.work, a.plan), encoding="utf-8"))
    toks = plan["tokens"]
    rem = plan["removals"]
    on = [r for r in rem if r.get("state") == "on"]
    removed_tok = {i for r in on for i in r.get("tokens", [])}

    def dead(t0, t1):
        return any(r["start"] <= t0 and t1 <= r["end"] for r in on)

    live = [t for t in toks if t["i"] not in removed_tok and not dead(t["t0"], t["t1"])]

    def ctx(t, before=8, after=8):
        i = t["i"]
        lo, hi = max(0, i - before), min(len(toks), i + after + 1)
        return " ".join(("[" + x["w"] + "]") if x["i"] == i else x["w"] for x in toks[lo:hi])

    out = [f"# Audit — {plan.get('timeline', '')}", "",
           f"{len(toks)} words, {len(live)} kept, {len(on)} removals on "
           f"({plan.get('stats', {}).get('removed_pct', '?')}% removed)", ""]

    # 1 + 2: cues in the full text (with where they are relative to removals)
    text_by_seg: dict[int, list] = {}
    for t in toks:
        text_by_seg.setdefault(t.get("seg", -1), []).append(t)
    for title, pat in (("Restart cues — abandoned takes said out loud", RESTART),
                       ("Openings — more than one = burned openings", OPENING)):
        out += [f"## {title}", ""]
        n = 0
        for seg, ts in sorted(text_by_seg.items(), key=lambda kv: kv[1][0]["t0"]):
            line = " ".join(x["w"] for x in ts)
            if pat.search(line):
                n += 1
                gone = all(x["i"] in removed_tok or dead(x["t0"], x["t1"]) for x in ts)
                out.append(f"- {mmss(ts[0]['t0'])} {'(removed) ' if gone else ''}{line[:160]}")
        out += ["" if n else "- none", ""]

    # 3: repeated n-grams among kept words
    out += [f"## Repeated phrases in the kept text ({a.ngram}+ words within {a.window:.0f} s)", ""]
    seen: dict[tuple, float] = {}
    hits = []
    words = [(fold(t["w"]), t) for t in live]
    words = [(w, t) for w, t in words if w]
    for k in range(len(words) - a.ngram + 1):
        key = tuple(w for w, _ in words[k:k + a.ngram])
        t = words[k][1]
        if key in seen and t["t0"] - seen[key] <= a.window and t["t0"] - seen[key] > 2.0:
            if not hits or t["t0"] - hits[-1][1]["t0"] > 5:
                hits.append((seen[key], t, " ".join(key)))
        seen[key] = t["t0"]
    out += [f"- {mmss(t0)} and {mmss(t['t0'])}: \"{p}\"" for t0, t, p in hits] or ["- none"]
    out.append("")

    # 4: stretched tokens
    out += [f"## Stretched live tokens (> {a.long} s) — re-transcribe the raw window", ""]
    st = [t for t in live if t["t1"] - t["t0"] > a.long]
    out += [f"- {mmss(t['t0'])} '{t['w']}' {t['t1'] - t['t0']:.2f} s … {ctx(t)}" for t in st] or ["- none"]
    out.append("")

    # 5: announced pauses
    out += ["## Silence removals after an announced pause — probably content", ""]
    n = 0
    for r in on:
        if r["kind"] != "silence" or r["end"] - r["start"] < 2.0:
            continue
        before = [t for t in toks if r["start"] - 6 <= t["t1"] <= r["start"] + 0.05]
        line = " ".join(t["w"] for t in before)
        if PAUSE_CUE.search(line):
            n += 1
            out.append(f"- {r['id']} {mmss(r['start'])} {r['end'] - r['start']:.1f} s after: …{line[-120:]}")
    out += ["" if n else "- none", ""]

    # 6: lowercase after a removal that took a capitalised opener
    out += ["## Next sentence starts lowercase after a removal", ""]
    n = 0
    for r in on:
        if r["kind"] == "silence" or not r.get("text"):
            continue
        if r["text"][:1].isupper():
            nxt = next((t for t in live if t["t0"] >= r["end"] - 0.01), None)
            if nxt and nxt["w"][:1].islower():
                n += 1
                out.append(f"- {r['id']} {mmss(r['start'])} removed \"{r['text']}\" → next \"{nxt['w']}\" "
                           f"— reconnect the connector (switch it off)")
    out += ["" if n else "- none", ""]

    # 7: auto word removals
    out += ["## Auto-tier word removals — read every one", ""]
    auto = [r for r in on if r.get("tier") == "auto" and r["kind"] in ("false_start", "hesitation", "repeat", "stammer")]
    for r in auto:
        first = toks[r["tokens"][0]] if r.get("tokens") else None
        c = ctx(first, 6, 6) if first else ""
        out.append(f"- {r['id']} {r['kind']} {mmss(r['start'])} \"{r.get('text', '')}\" … {c}")
    if not auto:
        out.append("- none")
    print("\n".join(out))


if __name__ == "__main__":
    main()

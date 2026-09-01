#!/usr/bin/env python
"""Transcribe every source file used by the timeline, with WhisperX.

Calls the machine's `transcribe-x` wrapper (WhisperX 3.8.6, CPU int8, word-level
timestamps). Results are cached per file identity (path+size+mtime), so re-runs
are free and only new or changed media is transcribed.

Never pass --initial_prompt / --hotwords to WhisperX: on this stack they collapse
long chunks into two words while tripling the runtime. `transcribe-x` already
refuses to; do not work around it.

usage: rc_transcribe.py --work-dir DIR [--lang pt] [--force]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rc_common as rc  # noqa: E402


def transcribe_file(path: str, out_dir: Path, lang: str, force: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{Path(path).stem}.json"
    if target.exists() and not force:
        print(f"  cached  {Path(path).name}")
        return target
    if not shutil.which("transcribe-x"):
        raise SystemExit(
            "transcribe-x not on PATH. It lives in ~/.audio-tools and is normally "
            "symlinked into /opt/homebrew/bin.")
    env = dict(os.environ, TRANSCRIBEX_LANG=lang)
    print(f"  running transcribe-x on {Path(path).name} (WhisperX is ~2.5x realtime on CPU)")
    started = time.time()
    proc = subprocess.run(["transcribe-x", path, str(out_dir)], env=env,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"transcribe-x failed on {path}:\n{proc.stderr[-4000:]}")
    if not target.exists():
        produced = sorted(out_dir.glob("*.json"))
        if len(produced) == 1:
            produced[0].rename(target)
        else:
            raise SystemExit(f"transcribe-x produced no {target.name} in {out_dir}")
    print(f"  done    {Path(path).name} in {time.time() - started:.0f}s")
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--lang", default=os.environ.get("TRANSCRIBEX_LANG", "pt"))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    work = Path(args.work_dir)
    timeline = rc.read_json(work / "timeline.json")
    files = sorted({i["file_path"] for i in timeline["items"] if i.get("file_path")})
    if not files:
        raise SystemExit("No source files in timeline.json — nothing to transcribe.")

    index = {}
    for path in files:
        if not os.path.exists(path):
            raise SystemExit(f"Source media offline: {path}")
        key = rc.media_key(path)
        index[path] = str(transcribe_file(path, work / "words" / key, args.lang, args.force))

    rc.write_json(work / "words" / "index.json", index)
    total_words = 0
    for path, jpath in index.items():
        doc = rc.read_json(Path(jpath))
        total_words += sum(len(s.get("words") or []) for s in doc.get("segments") or [])
    print(f"\n{len(index)} file(s), {total_words} words -> {work / 'words' / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

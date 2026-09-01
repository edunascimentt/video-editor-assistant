#!/usr/bin/env bash
# One-time environment for the Premiere rough-cut pipeline.
#
#   bash .claude/skills/rough-cut-premiere/scripts/setup.sh [--with-whisperx]
#
# Builds a venv beside the scripts with numpy in it, which is all the cutting
# side needs. WhisperX is a much larger install (torch), so it is opt-in: pass
# --with-whisperx, or keep using an existing `transcribe-x` / `whisperx` on PATH.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/../.venv"
WITH_WHISPERX=0
[[ "${1:-}" == "--with-whisperx" ]] && WITH_WHISPERX=1

command -v ffmpeg >/dev/null 2>&1 || {
  echo "ERROR  ffmpeg is not on PATH. It decodes every envelope this pipeline measures." >&2
  echo "       brew install ffmpeg   /   winget install Gyan.FFmpeg" >&2
  exit 1
}

# WhisperX is happiest on 3.10-3.12, and numpy has no wheels for a brand-new
# interpreter for months after it ships. Pick a version in that band if one is
# installed, rather than whatever `python3` happens to point at.
PYBIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then PYBIN="$(command -v "$candidate")"; break; fi
done
[[ -n "$PYBIN" ]] || { echo "ERROR  No python3 on PATH." >&2; exit 1; }
echo "python: $PYBIN ($("$PYBIN" -V 2>&1))"

"$PYBIN" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet numpy
echo "OK     numpy installed in $VENV"

if [[ "$WITH_WHISPERX" -eq 1 ]]; then
  echo "installing whisperx (this pulls torch — several minutes and a few GB)"
  "$VENV/bin/pip" install whisperx
  echo "OK     whisperx installed"
else
  if command -v transcribe-x >/dev/null 2>&1; then
    echo "OK     transcribe-x on PATH — it will be used for transcription"
  elif command -v whisperx >/dev/null 2>&1; then
    echo "OK     whisperx on PATH — it will be used for transcription"
  else
    echo "NOTE   No transcriber found. Re-run with --with-whisperx, or install one"
    echo "       separately (pipx install whisperx). Nothing else in the pipeline needs it."
  fi
fi

cat <<NEXT

Use this interpreter for every script in this skill:

  PY=$VENV/bin/python
  RC=$SCRIPT_DIR
NEXT

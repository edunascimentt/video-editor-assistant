#!/usr/bin/env bash
# Installs the Adobe Premiere Pro MCP server and wires it into this repository.
# macOS (and Linux, for the server half only). Windows: use install.ps1.
#
#   bash .claude/skills/install-premiere-mcp/scripts/install.sh [--skip-cep]
#
# Idempotent: re-running upgrades the package, refreshes the CEP connector and
# rewrites the .mcp.json entry in place.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
SKIP_CEP=0
[[ "${1:-}" == "--skip-cep" ]] && SKIP_CEP=1

step() { printf '\n=== %s\n' "$1"; }
fail() { printf 'ERROR  %s\n' "$1" >&2; exit 1; }

step "Checking prerequisites"

command -v node >/dev/null 2>&1 || fail "Node.js is not installed. Install Node.js 20.19 or newer: https://nodejs.org"
command -v npm  >/dev/null 2>&1 || fail "npm is not on PATH, but Node.js is. Repair your Node.js installation."

NODE_VERSION="$(node -p 'process.versions.node')"
node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>20||(a===20&&b>=19)?0:1)' \
  || fail "Node.js $NODE_VERSION is too old. premiere-pro-mcp needs 20.19 or newer."
echo "OK     Node.js $NODE_VERSION"

if [[ "$(uname -s)" == "Darwin" ]]; then
  if compgen -G "/Applications/Adobe Premiere Pro *" >/dev/null; then
    for app in /Applications/Adobe\ Premiere\ Pro\ *; do echo "OK     Found $(basename "$app")"; done
  else
    echo "WARN   No Adobe Premiere Pro found in /Applications."
    echo "       The server installs fine, but the CEP connector has nowhere to go."
  fi
  if pgrep -x "Adobe Premiere Pro" >/dev/null 2>&1; then
    fail "Premiere Pro is running. Quit it completely, then run this again — a running Premiere will not pick up the connector."
  fi
else
  echo "WARN   $(uname -s) is not a Premiere Pro platform. Installing the server only."
  SKIP_CEP=1
fi

if command -v ffmpeg >/dev/null 2>&1; then
  echo "OK     ffmpeg on PATH (detect_silence available)"
else
  echo "NOTE   ffmpeg not on PATH — only the detect_silence tool needs it (brew install ffmpeg)."
fi

step "Installing the MCP server (npm install -g premiere-pro-mcp)"
if ! npm install -g premiere-pro-mcp; then
  echo "ERROR  npm install -g failed." >&2
  echo "       If it failed on permissions, do NOT rerun with sudo — point npm at a user-owned prefix:" >&2
  echo "         npm config set prefix ~/.npm-global && export PATH=\"\$HOME/.npm-global/bin:\$PATH\"" >&2
  echo "       then run this script again." >&2
  exit 1
fi
echo "OK     $(premiere-pro-mcp --version 2>/dev/null || echo 'installed')"

if [[ "$SKIP_CEP" -eq 0 ]]; then
  step "Installing the CEP connector into Premiere Pro"
  premiere-pro-mcp --install-cep
else
  step "Skipping the CEP connector (--skip-cep)"
  echo "NOTE   Without the connector there is no bridge to Premiere at all."
  echo "       Install it later with: premiere-pro-mcp --install-cep"
fi

step "Local readiness check (premiere-pro-mcp --doctor)"
premiere-pro-mcp --doctor || true
echo
echo "NOTE   'Live Premiere check: not_checked' is expected — a local check cannot prove"
echo "       Premiere is open and connected. verify_premiere_connection does that."

step "Wiring the server into $REPO_ROOT/.mcp.json"
node "$SCRIPT_DIR/configure-mcp.mjs"

step "Done"
cat <<'NEXT'
Three things remain, in this order:

  1. Start Premiere Pro, open a project, and confirm
     Window > Extensions > MCP for Adobe Premiere Pro shows green "Running".
  2. Restart Claude Code in this directory. MCP servers are read at session start,
     so the new server is not visible in the session that installed it.
  3. In the new session, run the read-only check before touching anything:
       "Run verify_premiere_connection. Make no changes."

Work on a duplicate project for the first pass.
NEXT

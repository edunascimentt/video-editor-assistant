# DaVinci Resolve MCP — local setup

Installed 2026-08-19 on this Mac (M1 Pro, macOS 26.6.1 / darwin 25.6).
Upstream: <https://github.com/samuelgursky/davinci-resolve-mcp> — MIT, v2.98.2.

Two MCP servers ship in that one checkout and **both** are wired into this
directory through [`.mcp.json`](.mcp.json) (project scope — they load only for
agents started in `~/Repositories/video-editor-assistant`).

Project-scoped servers need a one-time approval: the first `claude` run in this
directory asks, and until then `claude mcp list` shows both as
`⏸ Pending approval`. That is the current state.

| Server | Runtime | Tools | What it drives |
|---|---|---|---|
| `davinci-resolve` | Python 3.12 venv | 35 (compound) | A **running** Resolve, over Blackmagic's official scripting API |
| `davinci-resolve-advanced` | Node 26 | 18 | Resolve **files** — `.drp` / `.drt` / `.drx` and `Project.db` — with Resolve closed |

## Where things live

```
~/Repositories/davinci-resolve-mcp/           # the checkout (git, clean, on main @ v2.98.2)
├── venv/bin/python                           # Python 3.12.13 (uv-managed base)
├── src/server.py                             # live server, compound mode (35 tools)
├── bin/davinci-resolve-advanced-mcp.mjs      # offline server (18 tools)
├── node_modules/                             # npm deps incl. the optional three
├── scripts/doctor.py                         # the diagnostic to run first
└── logs/server.log, logs/update-check.json

~/Repositories/video-editor-assistant/.mcp.json   # this wiring
```

The live server needs three env vars, all set in `.mcp.json`:
`RESOLVE_SCRIPT_API`, `RESOLVE_SCRIPT_LIB`, `PYTHONPATH` → Blackmagic's
`Developer/Scripting` tree under `/Library/Application Support`.

**`.mcp.json` points at the checkout through `${RESOLVE_MCP_HOME}`**, not through
an absolute path, so the repository moves between machines unchanged. Set it once
in your shell profile before starting Claude Code:

```bash
export RESOLVE_MCP_HOME="$HOME/Repositories/davinci-resolve-mcp"
```

With the variable unset, both Resolve servers fail to start and log an error each
session — harmless, and exactly what you want on a machine that has no Resolve.
The Premiere installer offers to drop them entirely; see `PREMIERE-MCP.md`.

## Preconditions

- **DaVinci Resolve Studio must be running.** Verified here on Studio 21.0.0.48.
  With Resolve closed, `scriptapp("Resolve")` returns `None` and every live tool
  fails with "Not connected" — that is the expected failure, not a broken install.
  The `resolve_control` tool has `launch` / `runtime_mode` actions to handle it.
- **Preferences ▸ General ▸ External scripting using = Local.** Already on
  (`System.Scripting.Mode = 1` in
  `~/Library/Preferences/Blackmagic Design/DaVinci Resolve/config.dat`).
- Studio only. The free edition gates external scripting; the repo's in-app
  bridge (`scripts/install_resolve_bridge.py`) works around it, and is **not
  installed here** because it isn't needed.

The offline server needs none of this — no Resolve, no license.

## Verify

```bash
cd ~/Repositories/davinci-resolve-mcp
venv/bin/python scripts/doctor.py                 # paths, API, connection, extras
node bin/davinci-resolve-advanced-mcp.mjs --version   # "ready — 18 tools registered"
```

`doctor.py` printing `[WARN] Resolve scripting connection` while Resolve is
closed is normal. Two `[WARN]`s about Codex and Claude Desktop configs are also
expected — this install is deliberately project-scoped, so those clients have no
entry for it.

Last verified end-to-end (2026-08-19, Resolve open):

- `DaVinciResolveScript` imports, `GetProductName()` → `DaVinci Resolve Studio`,
  `GetVersionString()` → `21.0.0.48`.
- Live server: MCP handshake OK, 35 tools listed, `timeline{action:"list"}` and
  `project_manager{action:"list"}` returned real state (both empty — the active
  DB on that machine keeps every project inside subfolders, nothing at root).
- Offline server: handshake OK, 18 tools, `capabilities{action:"report"}` →
  ffmpeg, sharp and better-sqlite3 all `available: true`.

## Decisions worth remembering

**Python 3.12.13, not the system or Homebrew one.** The MCP SDK floor is 3.10;
upstream calls 3.10–3.12 the lowest-risk band for the Resolve scripting library.
macOS ships 3.9.6 (too old) and Homebrew here is 3.14.6 (above the band). The
venv was built by running `install.py` with a uv-managed 3.12 — `install.py`
creates the venv from whatever interpreter runs it:

```bash
uv python install 3.12
~/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12 install.py --clients manual
```

`--clients manual` makes the installer print configs instead of editing any
client's file. Worth keeping: its built-in `claude-code` target writes a
`.mcp.json` into the **current working directory**, which is not always where
you want it.

**`better-sqlite3` needs a version override.** `package.json` pins `^11.0.0`
under `optionalDependencies`; v11 has no prebuild for Node 26 and its `node-gyp`
fallback fails here, so npm silently skips it — an optional dep that fails is not
an error. v12 has a Node 26 prebuild and installs cleanly. `node_modules` holds
**12.11.1**, while the manifest still says `^11` (deliberately reverted, so the
checkout stays git-clean and upstream's safe auto-update stays eligible). A plain
`npm install` or `npm ci` in that repo will therefore knock it back out. Redo with:

```bash
cd ~/Repositories/davinci-resolve-mcp
npm install better-sqlite3@^12 && git checkout -- package.json package-lock.json
```

Without it the offline server still loads; only the Fairlight live-project-DB
path (and the other `Project.db`-backed reads) refuse.

**Optional analysis extras: `numpy` only.** Installed in the venv — enables
colour pre-balance, reference-still matching, sound-density audit. Deliberately
skipped: `openai-whisper` (the local `transcribe` / `transcribe-x` stack in
`~/.audio-tools` is faster and better), plus `librosa`, `open_clip_torch`,
`transformers`, `opencv-python`. Each missing extra refuses with its own pip
line rather than guessing, so nothing degrades silently.

**Update policy is `prompt`** (`logs/update-check.json`). The server checks
GitHub for releases, never blocks startup, and never self-updates without
consent. Change with `python install.py --update-policy notify|never|auto`.

## Resolve 21 hazard that predates this install

ResolveFX **Cinematic Focus** segfaults Resolve 21.0 on this machine the moment
a frame renders — a project carrying it crashes on open. Do not let an agent
open one, and do not add that effect through the grading tools. The offline
server's `project_db` / `drx` tools are the sanctioned version of the manual
`Project.db` surgery used to rescue such a project.

## Adding it somewhere else

Project scope was chosen so 53 extra tools don't load in every unrelated
session. To use it elsewhere:

```bash
# any single directory
cp ~/Repositories/video-editor-assistant/.mcp.json <dir>/

# or user scope for one Claude Code account (all directories, that account only)
claude mcp add -s user davinci-resolve \
  -e RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting" \
  -e RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so" \
  -e PYTHONPATH="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules" \
  -- "$RESOLVE_MCP_HOME/venv/bin/python" "$RESOLVE_MCP_HOME/src/server.py"
```

For Claude Desktop, Cursor, Codex, Zed, Continue and the rest, run
`venv/bin/python install.py --clients manual` and copy the block it prints for
that client — it emits the correct key name and shape per client
(`mcpServers` / `servers` / `context_servers` / TOML).

## Extras not set up

- **Control panel** — a loopback browser UI for inspecting Resolve state and
  analysis output: `venv/bin/python -m src.control_panel`, then open the printed
  `http://127.0.0.1:8765/#token=…` URL (it refuses requests without the token).
  Not launched as part of this setup.
- **Granular mode** — `src/server.py --full` exposes 353 one-per-API-method
  tools instead of the 35 compound ones. Only worth it if a compound action is
  missing something.

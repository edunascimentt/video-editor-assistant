---
name: install-premiere-mcp
description: Installs the Adobe Premiere Pro MCP server (leancoderkavy/premiere-pro-mcp) on this machine and wires it into this repository's .mcp.json — the npm package, the CEP connector inside Premiere, the client config, and the verification run. Use when the user asks to install, set up, repair, update or remove the Premiere MCP / "MCP do Premiere" / Premiere Pro integration, or when a Premiere tool fails because the bridge is not connected.
---

# Install the Premiere Pro MCP

Sets up [`premiere-pro-mcp`](https://github.com/leancoderkavy/premiere-pro-mcp) (MIT,
v1.14.5) so this repository's agent can drive a running Adobe Premiere Pro, the same way
`.mcp.json` already drives DaVinci Resolve for the other editor on this project.

The install has **three separate pieces**, and all three must be in place. Skipping the
second is the single most common reason "the MCP does not work":

1. **The MCP server** — an npm package that runs as a stdio MCP server.
2. **The CEP connector** — a panel installed *inside Premiere Pro*. The server and Premiere
   talk through a shared temp directory; without the panel there is no bridge at all.
3. **The client wiring** — a `premiere-pro` entry in this repo's `.mcp.json`, pre-approved in
   `.claude/settings.local.json`.

## Preconditions to check before running anything

| Requirement | How to check |
|---|---|
| Node.js 20.19+ | `node -v` |
| npm | `npm -v` |
| Adobe Premiere Pro 2020–2026 | macOS: `ls -d "/Applications/Adobe Premiere Pro"*` · Windows: `dir "%ProgramFiles%\Adobe" ` |
| ffmpeg (optional, only for `detect_silence`) | `ffmpeg -version` — `brew install ffmpeg` / `winget install Gyan.FFmpeg` |

Premiere must be **fully quit** while the connector is installed. Ask the user to close it
before running the installer; a running Premiere will not pick up the new panel and, on an
update, can leave a half-written connector behind.

## Running the install

macOS / Linux:

```bash
bash .claude/skills/install-premiere-mcp/scripts/install.sh
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File .claude\skills\install-premiere-mcp\scripts\install.ps1
```

The script is idempotent — running it again upgrades the package, refreshes the connector and
rewrites the config entry in place. It performs, in order:

1. `npm install -g premiere-pro-mcp`
2. `premiere-pro-mcp --install-cep` — copies the panel into Premiere's per-user extensions
   folder and enables the CSXS `PlayerDebugMode` keys it needs.
3. `premiere-pro-mcp --doctor --json` — local readiness check; reads no project.
4. `node .claude/skills/install-premiere-mcp/scripts/configure-mcp.mjs` — adds the
   `premiere-pro` server to `.mcp.json` (absolute path to the installed `dist/index.js`, so no
   shell-shim guessing on Windows) and adds it to `enabledMcpjsonServers` in
   `.claude/settings.local.json`.

Pass `--skip-cep` to the script when only the server and the wiring need refreshing.

## After the script: what you must tell the user to do

The install is not finished when the script exits. Say this explicitly:

1. **Restart Premiere Pro**, open a project, and check **Window ▸ Extensions ▸ MCP for Adobe
   Premiere Pro** shows green "Running".
2. **Restart Claude Code** in this directory — MCP servers are read once at session start, so
   the new server does not appear in the session that installed it.
3. In the new session, run the read-only check first: `verify_premiere_connection`, then
   `get_capabilities` and `ping`. Do not make any edit before that check passes.

## Reading `--doctor` output

`--doctor` reports four components with a boundary each. Interpret them literally:

- `mcp_process` `ready` — the package can run here. Says nothing about Premiere.
- `premiere_connector` `needs_attention` — **the CEP panel is missing**. Re-run with
  `--install-cep`, with Premiere closed.
- `uxp_bridge` `not_checked` — normal. The UXP route is optional and needs Premiere 25.6+
  plus `PREMIERE_UXP_TOKEN`; the CEP bridge is the production path.
- `premiere_host` `not_checked` — always, by design. A local check can never prove Premiere is
  open and connected; only `verify_premiere_connection` from a live session can.

`overall: needs_attention` with only `premiere_connector` outstanding means step 2 above has
not happened yet — it is not a broken install.

`premiere-pro-mcp --diagnose-cep` goes deeper (install paths, debug keys, Premiere's own
signature logs) and is the right next step when the panel is installed but never turns green.

## The Resolve servers in this repo

`.mcp.json` also carries `davinci-resolve` and `davinci-resolve-advanced`, both pointing at
paths under `$RESOLVE_MCP_HOME`, the checkout of the Resolve MCP. On a machine without that checkout they simply fail to start and log an error every
session; they cannot damage anything.

`configure-mcp.mjs` detects this and prints a warning. **Ask the user before removing them** —
some editors on this project use both NLEs. To remove them once the user agrees:

```bash
node .claude/skills/install-premiere-mcp/scripts/configure-mcp.mjs --drop-missing-resolve
```

To keep Resolve instead, install it from [`RESOLVE-MCP.md`](../../../RESOLVE-MCP.md) and fix
the paths in `.mcp.json` to match the new machine.

## Authority profile — what the server is allowed to do

The default profile is `inspect,edit,export,filesystem`, which exposes 319 of the 326 tools.
It deliberately withholds `execute_extendscript` and `evaluate_expression`, which run arbitrary
script inside Premiere. Leave it that way. Only if the user explicitly asks for raw scripting,
add to the server's `env` in `.mcp.json`:

```json
"PREMIERE_MCP_CAPABILITIES": "inspect,edit,export,filesystem,unsafe-script"
```

To cut the tool surface instead of expanding it, `PREMIERE_MCP_TOOL_PACKS` accepts
`essential`, `inspection`, `delivery`, `captions` (comma-separated) or `full`. A pack narrows
discovery only — it never grants authority.

Telemetry is off unless `POSTHOG_API_KEY` is set. Do not set it.

## Updating and removing

```bash
premiere-pro-mcp --check-update
premiere-pro-mcp --update          # updates the global package and refreshes the connector
premiere-pro-mcp --uninstall-cep   # removes the panel; quit Premiere first
npm uninstall -g premiere-pro-mcp
```

`--update` does not touch `.mcp.json` or any project. After it, restart Premiere and the client
and re-run `verify_premiere_connection`.

## Working safely once it is connected

- Run `verify_premiere_connection` before the first mutation of every session.
- Do the first pass on a **duplicate** project or a throwaway sequence.
- Premiere's undo does not cover everything an MCP tool can do; a saved project copy is the
  real safety net.
- QE-backed tools report as `experimental` because QE is undocumented and shifts between
  Premiere builds. Read each tool's result rather than assuming success — a returned
  "accepted" is a request, not a confirmed edit.

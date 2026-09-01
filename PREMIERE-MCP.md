# Adobe Premiere Pro MCP — install on a new machine

This repository was built around DaVinci Resolve (see [`RESOLVE-MCP.md`](RESOLVE-MCP.md)).
For an editor who works in **Adobe Premiere Pro**, the equivalent bridge is installed on
demand — nothing Premiere-specific is wired into `.mcp.json` until you run the install, so a
Resolve-only machine never loads it.

Upstream: <https://github.com/leancoderkavy/premiere-pro-mcp> — MIT, v1.14.5 (published
2026-08-31, actively maintained). 326 tools; 319 exposed under the default authority profile.

## The one-line version

In Claude Code, in this directory, ask:

> instala o mcp do premiere

That triggers the [`install-premiere-mcp`](.claude/skills/install-premiere-mcp/SKILL.md) skill,
which runs the installer, wires the server into `.mcp.json`, and tells you what to restart.

To do it by hand instead:

```bash
# macOS
bash .claude/skills/install-premiere-mcp/scripts/install.sh

# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File .claude\skills\install-premiere-mcp\scripts\install.ps1
```

## What gets installed

| Piece | Where it lands | Why it is needed |
|---|---|---|
| `premiere-pro-mcp` npm package | global npm prefix | the MCP server itself, stdio transport |
| `MCPBridgeCEP` connector | Premiere's per-user CEP extensions folder | Premiere has no external scripting socket — the server and Premiere exchange commands through a shared temp directory, and only this panel executes them |
| `premiere-pro` entry | this repo's `.mcp.json` | project scope, so the tools load only for agents started in this directory |
| `premiere-pro` in `enabledMcpjsonServers` | `.claude/settings.local.json` | pre-approves the project-scoped server |

The chain end to end: **agent → MCP server (Node) → file bridge in the OS temp dir → CEP panel
→ ExtendScript/QE → Premiere Pro**. Every link must be up; the panel is the one people forget.

## Requirements

- **Node.js 20.19+** on Windows or macOS.
- **Adobe Premiere Pro 2020–2026.** Quit it completely before installing the connector.
- Premiere, the connector and Claude Code must all run on the **same computer**.
- Optional: `ffmpeg` on `PATH`, used only by the `detect_silence` tool.

Unlike Resolve, there is no Studio/free license split here — the CEP route works on any
licensed Premiere in that version range.

## Verifying

```bash
premiere-pro-mcp --doctor          # local readiness; reads no project
premiere-pro-mcp --doctor --json   # same, machine-readable
premiere-pro-mcp --diagnose-cep    # install paths, CSXS debug keys, Premiere signature logs
```

`--doctor` reports four components. Two of them are *supposed* to look unfinished:

- `premiere_host: not_checked` — always. A local check cannot prove Premiere is open and
  connected; only `verify_premiere_connection`, run from a live session, can.
- `uxp_bridge: not_checked` — the UXP route is optional (Premiere 25.6+, `PREMIERE_UXP_TOKEN`,
  loopback WebSocket on port 7777). The CEP bridge is the production path.

`premiere_connector: needs_attention` is the real failure — the panel is missing. Quit Premiere
and run `premiere-pro-mcp --install-cep`.

Then, in Premiere: **Window ▸ Extensions ▸ MCP for Adobe Premiere Pro** must show green
"Running", and in a **fresh** Claude Code session (MCP servers are read at session start):

```text
Run verify_premiere_connection. Make no changes.
```

That check is read-only and reports no project names, paths or media details.

## Safety notes worth reading once

- **Do the first pass on a duplicate project.** Premiere's undo does not cover everything an
  MCP tool can do; a saved copy is the real safety net.
- **The default authority profile is `inspect,edit,export,filesystem`.** It withholds
  `execute_extendscript` and `evaluate_expression`, which run arbitrary script inside Premiere.
  Leave it withheld unless you specifically need raw scripting, then set
  `PREMIERE_MCP_CAPABILITIES=inspect,edit,export,filesystem,unsafe-script` in the server's `env`.
- **QE-backed tools report as `experimental`** because QE is undocumented and changes between
  Premiere builds. Read each tool's result: an "accepted" response is a request, not a
  confirmed edit.
- **Telemetry is off** unless `POSTHOG_API_KEY` is set. The installer never sets it.
- To narrow the tool surface for a focused session, `PREMIERE_MCP_TOOL_PACKS` accepts
  `essential`, `inspection`, `delivery`, `captions` (comma-separated) or `full`. A pack limits
  discovery only — it never grants authority.

## The Resolve servers already in `.mcp.json`

`davinci-resolve` and `davinci-resolve-advanced` point at absolute paths under
`$RESOLVE_MCP_HOME`. On a machine without that checkout, or with the variable unset, they fail
to start and log an error each session — noisy, but harmless. The installer detects this and
offers the removal command; it never removes them on its own:

```bash
node .claude/skills/install-premiere-mcp/scripts/configure-mcp.mjs --drop-missing-resolve
```

Keep them and follow `RESOLVE-MCP.md` instead if the machine also edits in Resolve.

## Which skills work here

`.claude/skills/rough-cut-premiere` is the Premiere port of the rough cut: same transcription,
same cut planning, same verification, but the edit reaches Premiere as an FCP7 XML round trip
(`export_as_fcp_xml` out, `import_fcp_xml` back) rather than through the scripting API. Build
its venv once with `bash .claude/skills/rough-cut-premiere/scripts/setup.sh`.

`.claude/skills/rough-cut` and `.claude/skills/on-screen-text` are the Resolve originals. They
drive Resolve's scripting API and its Fusion templates, and do **not** work against Premiere as
written — for on-screen text the method transfers, the templates do not.

## Updating and removing

```bash
premiere-pro-mcp --check-update
premiere-pro-mcp --update          # global package + connector; leaves config and projects alone
premiere-pro-mcp --uninstall-cep   # quit Premiere first
npm uninstall -g premiere-pro-mcp
```

After any update, restart Premiere and Claude Code, then re-run `verify_premiere_connection`
before editing.

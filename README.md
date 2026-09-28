# video-editor-assistant

A Claude Code working directory for video editing: the MCP servers that drive an NLE, plus the
skills that carry the actual editing recipes.

## Start here, by editor

| You edit in | Read | Setup state |
|---|---|---|
| **DaVinci Resolve** | [`RESOLVE-MCP.md`](RESOLVE-MCP.md) | already wired in `.mcp.json`, with machine-specific absolute paths |
| **Adobe Premiere Pro** | [`PREMIERE-MCP.md`](PREMIERE-MCP.md) | installed on demand — ask Claude *"instala o mcp do premiere"* |

Nothing Premiere-specific loads until you install it, and the Resolve entries can be dropped
on a Premiere-only machine. Both are project-scoped: the tools load only for agents started in
this directory, and the first `claude` run here asks you to approve them.

## Moving this to another machine

Nothing in the repository points at a home directory. The one thing to set is where the
Resolve MCP checkout lives, which `.mcp.json` reads as `${RESOLVE_MCP_HOME}`:

```bash
export RESOLVE_MCP_HOME="$HOME/Repositories/davinci-resolve-mcp"
```

Leave it unset on a machine without Resolve — the two Resolve servers then fail to start and
log an error each session, which is harmless, and `PREMIERE-MCP.md` explains how to drop them
for good. Each Python pipeline builds its own environment; see the skill you are using.

## Skills

| Skill | What it does |
|---|---|
| [`rough-cut`](.claude/skills/rough-cut) | Rough-cuts a Resolve timeline from its own audio — silence, hums, filler, abandoned lines — transcribing with WhisperX for word-level timing, then verifying nothing was clipped. |
| [`on-screen-text`](.claude/skills/on-screen-text) | Marks up a lesson timeline and builds its on-screen text: slide points, punch words, definition cards, using the project's own Text+ and Fusion templates. |
| [`rough-cut-premiere`](.claude/skills/rough-cut-premiere) | The same rough cut for an Adobe Premiere Pro sequence. Identical analysis and verification; the cut reaches Premiere as an FCP7 XML round trip instead of through the API. |
| [`install-premiere-mcp`](.claude/skills/install-premiere-mcp) | Installs and wires the Premiere Pro MCP on this machine. |

Complete edits — these orchestrate the skills above into a finished piece:

| Skill | What it does |
|---|---|
| [`lesson-pass`](.claude/skills/lesson-pass) | The full pass on a course lesson in Resolve, in order: rough cut with the reading the analyser cannot do, intro restored, on-screen text, zooms, screen-recording layout, and the report of pink markers and refused decisions. |
| [`briefing-cut`](.claude/skills/briefing-cut) | A short client video cut from raw location footage in the order of a brief, under a duration cap: speech spans snapped to silence, b-roll from its own material, two-layer check, and the editor's finishing copied from her approved cut. |
| [`best-take-cut`](.claude/skills/best-take-cut) | Prompted takes where each line was read many times: the speaker told apart by mouth motion, the best read per line kept, every span verified alone. |
| [`multicam-switch`](.claude/skills/multicam-switch) | The other camera angles added to a single-camera cut: takes matched and synced by audio, switches only on existing cuts. |
| [`podcast-cuts`](.claude/skills/podcast-cuts) | Numbered cuts from a long podcast recording: real in/out from content, silence-only trimming tuned to the editor's hand, her title package cloned through a `.drt`, sensitive material screened out. |
| [`music-bed`](.claude/skills/music-bed) | A licensed music bed picked by measurement, its turn aligned with the key line, and its level, fades and ducking rendered into the file. |
| [`resolve-scripting`](.claude/skills/resolve-scripting) | The Resolve API facts that fail silently, a connection helper that survives dropped links, and a `.drt` library for cloning items the API cannot copy. |

`rough-cut` and `on-screen-text` are written against Resolve's scripting API and its Fusion
templates. `rough-cut-premiere` is the ported cut; `on-screen-text` has no Premiere port yet —
its method transfers, its Fusion templates do not.

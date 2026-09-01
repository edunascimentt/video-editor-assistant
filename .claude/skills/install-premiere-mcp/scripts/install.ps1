# Installs the Adobe Premiere Pro MCP server and wires it into this repository. Windows.
#
#   powershell -ExecutionPolicy Bypass -File .claude\skills\install-premiere-mcp\scripts\install.ps1 [-SkipCep]
#
# Idempotent: re-running upgrades the package, refreshes the CEP connector and
# rewrites the .mcp.json entry in place.

param([switch]$SkipCep)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = (Resolve-Path (Join-Path $ScriptDir '..\..\..\..')).Path

function Step([string]$Message) { Write-Host "`n=== $Message" }
function Fail([string]$Message) { Write-Error "ERROR  $Message"; exit 1 }

Step 'Checking prerequisites'

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Fail 'Node.js is not installed. Install Node.js 20.19 or newer: https://nodejs.org'
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Fail 'npm is not on PATH, but Node.js is. Repair your Node.js installation.'
}

$NodeVersion = (node -p 'process.versions.node')
node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>20||(a===20&&b>=19)?0:1)'
if ($LASTEXITCODE -ne 0) {
  Fail "Node.js $NodeVersion is too old. premiere-pro-mcp needs 20.19 or newer."
}
Write-Host "OK     Node.js $NodeVersion"

$PremiereDirs = @(
  "$env:ProgramFiles\Adobe",
  "${env:ProgramFiles(x86)}\Adobe"
) | Where-Object { Test-Path $_ } |
    ForEach-Object { Get-ChildItem $_ -Directory -Filter 'Adobe Premiere Pro*' -ErrorAction SilentlyContinue }

if ($PremiereDirs) {
  $PremiereDirs | ForEach-Object { Write-Host "OK     Found $($_.Name)" }
} else {
  Write-Host 'WARN   No Adobe Premiere Pro found under Program Files.'
  Write-Host '       The server installs fine, but the CEP connector has nowhere to go.'
}

if (Get-Process -Name 'Adobe Premiere Pro' -ErrorAction SilentlyContinue) {
  Fail 'Premiere Pro is running. Quit it completely, then run this again — a running Premiere will not pick up the connector.'
}

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
  Write-Host 'OK     ffmpeg on PATH (detect_silence available)'
} else {
  Write-Host 'NOTE   ffmpeg not on PATH — only the detect_silence tool needs it (winget install Gyan.FFmpeg).'
}

Step 'Installing the MCP server (npm install -g premiere-pro-mcp)'
npm install -g premiere-pro-mcp
if ($LASTEXITCODE -ne 0) { Fail 'npm install -g premiere-pro-mcp failed.' }

Step 'Installing the CEP connector into Premiere Pro'
if (-not $SkipCep) {
  premiere-pro-mcp --install-cep
  if ($LASTEXITCODE -ne 0) {
    Write-Host 'WARN   The connector installer reported a failure.'
    Write-Host '       Run `premiere-pro-mcp --diagnose-cep` for the install paths and CSXS debug keys.'
  }
} else {
  Write-Host 'Skipped (-SkipCep). Without the connector there is no bridge to Premiere at all.'
  Write-Host 'Install it later with: premiere-pro-mcp --install-cep'
}

Step 'Local readiness check (premiere-pro-mcp --doctor)'
premiere-pro-mcp --doctor
Write-Host ''
Write-Host "NOTE   'Live Premiere check: not_checked' is expected — a local check cannot prove"
Write-Host '       Premiere is open and connected. verify_premiere_connection does that.'

Step "Wiring the server into $RepoRoot\.mcp.json"
node (Join-Path $ScriptDir 'configure-mcp.mjs')
if ($LASTEXITCODE -ne 0) { Fail 'Failed to write .mcp.json.' }

Step 'Done'
@'
Three things remain, in this order:

  1. Start Premiere Pro, open a project, and confirm
     Window > Extensions > MCP for Adobe Premiere Pro shows green "Running".
  2. Restart Claude Code in this directory. MCP servers are read at session start,
     so the new server is not visible in the session that installed it.
  3. In the new session, run the read-only check before touching anything:
       "Run verify_premiere_connection. Make no changes."

Work on a duplicate project for the first pass.
'@ | Write-Host

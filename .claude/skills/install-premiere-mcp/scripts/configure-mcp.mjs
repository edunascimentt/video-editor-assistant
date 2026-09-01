#!/usr/bin/env node
// Wires the installed premiere-pro-mcp package into this repository's .mcp.json and
// pre-approves it in .claude/settings.local.json. Idempotent: safe to re-run.
//
//   node configure-mcp.mjs [--drop-missing-resolve]
//
// --drop-missing-resolve removes the davinci-resolve* entries, but only when their
// configured paths do not exist on this machine. Never run it without asking the user.

import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SERVER_KEY = 'premiere-pro';
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..');
const mcpPath = join(repoRoot, '.mcp.json');
const settingsPath = join(repoRoot, '.claude', 'settings.local.json');
const dropResolve = process.argv.includes('--drop-missing-resolve');

function readJson(path, fallback) {
  if (!existsSync(path)) return fallback;
  const raw = readFileSync(path, 'utf8').trim();
  if (!raw) return fallback;
  try {
    return JSON.parse(raw);
  } catch (err) {
    console.error(`ERROR  ${path} is not valid JSON — fix it by hand before re-running.`);
    console.error(`       ${err.message}`);
    process.exit(1);
  }
}

function writeJson(path, value) {
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`);
}

// Prefer an absolute path to the globally installed entry point: on Windows the npm
// global bin is a .cmd shim that not every MCP client spawns correctly, and an absolute
// path also survives a PATH that differs between the terminal and a GUI-launched client.
function locateServer() {
  try {
    const globalRoot = execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim();
    const entry = join(globalRoot, 'premiere-pro-mcp', 'dist', 'index.js');
    if (existsSync(entry)) return { command: process.execPath, args: [entry], entry };
  } catch {
    // npm not on PATH, or no global root — fall through to the npx form.
  }
  return {
    command: 'npx',
    args: ['-y', 'premiere-pro-mcp@latest'],
    entry: null,
  };
}

const located = locateServer();
if (!located.entry) {
  console.warn('WARN   premiere-pro-mcp is not installed globally; falling back to npx.');
  console.warn('       Run `npm install -g premiere-pro-mcp` and re-run this script for a pinned path.');
}

const mcp = readJson(mcpPath, {});
mcp.mcpServers ??= {};

const existing = mcp.mcpServers[SERVER_KEY];
mcp.mcpServers[SERVER_KEY] = {
  command: located.command,
  args: located.args,
  // Any env the user added by hand (a capability profile, a tool pack, a temp dir) is kept.
  ...(existing?.env ? { env: existing.env } : {}),
};
writeJson(mcpPath, mcp);
console.log(`${existing ? 'UPDATED' : 'ADDED  '} ${SERVER_KEY} in .mcp.json`);
console.log(`       ${located.command} ${located.args.join(' ')}`);

// Pre-approve the project-scoped server so the first session does not sit on a prompt.
const settings = readJson(settingsPath, {});
const enabled = new Set(settings.enabledMcpjsonServers ?? []);
if (!enabled.has(SERVER_KEY)) {
  enabled.add(SERVER_KEY);
  settings.enabledMcpjsonServers = [...enabled];
  writeJson(settingsPath, settings);
  console.log('ADDED   premiere-pro to enabledMcpjsonServers in .claude/settings.local.json');
} else {
  console.log('OK      premiere-pro already enabled in .claude/settings.local.json');
}

// The Resolve entries carry absolute paths from the machine they were set up on.
const stale = [];
for (const [name, cfg] of Object.entries(mcp.mcpServers)) {
  if (!name.startsWith('davinci-resolve')) continue;
  const target = cfg.args?.find((a) => typeof a === 'string' && a.startsWith('/'));
  if (target && !existsSync(target)) stale.push([name, target]);
}

if (stale.length) {
  if (dropResolve) {
    for (const [name] of stale) delete mcp.mcpServers[name];
    const kept = new Set(settings.enabledMcpjsonServers ?? []);
    for (const [name] of stale) kept.delete(name);
    settings.enabledMcpjsonServers = [...kept];
    writeJson(mcpPath, mcp);
    writeJson(settingsPath, settings);
    console.log(`REMOVED ${stale.map(([n]) => n).join(', ')} — their paths do not exist here.`);
  } else {
    console.log('');
    console.log('WARN    These servers point at paths that do not exist on this machine:');
    for (const [name, target] of stale) console.log(`          ${name} -> ${target}`);
    console.log('        They will fail to start every session (harmless, but noisy).');
    console.log('        Remove them with: node .claude/skills/install-premiere-mcp/scripts/configure-mcp.mjs --drop-missing-resolve');
    console.log('        Keep them if this machine also edits in DaVinci Resolve — see RESOLVE-MCP.md.');
  }
}

console.log('');
console.log('Next: restart Premiere Pro, then restart Claude Code in this directory.');
console.log('Then run verify_premiere_connection before any edit.');

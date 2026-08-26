#!/usr/bin/env node
/**
 * Watchdog that outlives the dev supervisor.
 *
 * Cleanup that runs *inside* the dying process is not dependable on Windows. On
 * Ctrl+C the console delivers CTRL_C_EVENT to every process attached to it, so
 * a `taskkill` spawned from the handler is itself killed before it does its
 * work — the handler prints that it is stopping things, kills nothing, and
 * exits looking clean.
 *
 * So the kill is moved somewhere the signal cannot reach. This process is
 * spawned detached, with no console of its own, and simply watches the
 * supervisor. When the supervisor disappears — Ctrl+C, force-kill, closed
 * terminal, crash — it cleans up and exits.
 *
 * It guarantees PORTS, not just the child PIDs it was given. When the
 * supervisor dies, its children often die with it and orphan THEIR children,
 * at which point killing a recorded child pid reaches nothing while a
 * grandchild still holds the socket. The ports are the thing that actually
 * needs to end up free.
 *
 *   node dev-reaper.mjs --parent <pid> --children <pid,...> --ports <n,...>
 */

import { freePorts, killTree } from "./proc.mjs";

const argv = process.argv.slice(2);
const argOf = (name) => {
  const i = argv.indexOf(name);
  return i === -1 ? null : argv[i + 1];
};
const numbers = (s) => (s ?? "").split(",").map(Number).filter(Boolean);

const parent = Number(argOf("--parent"));
const children = numbers(argOf("--children"));
const ports = numbers(argOf("--ports"));

if (!parent || (children.length === 0 && ports.length === 0)) {
  console.error("usage: dev-reaper.mjs --parent <pid> --children <pid,...> --ports <n,...>");
  process.exit(2);
}

const POLL_MS = 400;
// A supervisor that never dies means this polls quietly forever, which is
// correct but worth bounding: 12h is far longer than any dev session.
const MAX_MS = 12 * 60 * 60 * 1000;

function alive(pid) {
  try {
    // Signal 0 tests for existence without touching the process.
    process.kill(pid, 0);
    return true;
  } catch (err) {
    // EPERM means it exists but belongs to someone else — still alive.
    return err.code === "EPERM";
  }
}

function reap() {
  // Direct children first: the cheap case, and it takes their trees with them.
  for (const pid of children) killTree(pid, { quiet: true });
  // Then make the ports actually free, whatever is holding them now. Foreign
  // processes are left alone — this runs unattended, so it never guesses.
  if (ports.length) freePorts(ports, { passes: 8 });
}

const startedAt = Date.now();

const timer = setInterval(() => {
  if (!alive(parent)) {
    reap();
    clearInterval(timer);
    process.exit(0);
  }
  if (Date.now() - startedAt > MAX_MS) {
    clearInterval(timer);
    process.exit(0);
  }
}, POLL_MS);

// The supervisor kills this process on a clean shutdown; ignoring console
// signals keeps it from dying alongside the thing it exists to outlive.
process.on("SIGINT", () => {});
process.on("SIGTERM", () => {});
process.on("SIGHUP", () => {});

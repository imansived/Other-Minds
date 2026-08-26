#!/usr/bin/env node
/**
 * Dev supervisor for the web + api processes.
 *
 * Replaces `concurrently` because of one specific Windows behaviour: killing a
 * process does NOT kill its descendants. Every wrapper layer is somewhere a
 * child can be orphaned, and an orphaned server keeps its port AND keeps
 * serving whatever code it started with — which reads as "my changes aren't
 * taking effect" rather than as a stale process.
 *
 * Four defences, because no single one is sufficient:
 *
 *   1. Fewer layers. Both servers are launched directly (the venv python, and
 *      next's own bin) rather than through npm/npx wrappers.
 *   2. Tree kills on shutdown, from a detached killer so the console signal
 *      that is killing us cannot kill it too.
 *   3. A watchdog (scripts/dev-reaper.mjs) that outlives this process and
 *      finishes the job if defence 2 does not run or does not finish. This is
 *      the one that actually makes Ctrl+C reliable.
 *   4. A preflight sweep on start, which says so loudly, so a cleanup failure
 *      can never again be silently tidied away.
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { freePorts, killTree, listeners } from "./proc.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const IS_WIN = process.platform === "win32";

const API_PORT = Number(process.env.API_PORT ?? 8000);
const WEB_PORT = Number(process.env.WEB_PORT ?? 3000);
const PORTS = [API_PORT, WEB_PORT];

const c = (n, s) => (process.stdout.isTTY ? `\x1b[${n}m${s}\x1b[0m` : s);
const shorten = (cmd) => (cmd || "").trim().split(/\s+/)[0] || "unknown";

function venvPython() {
  const p = IS_WIN
    ? join(ROOT, "backend", ".venv", "Scripts", "python.exe")
    : join(ROOT, "backend", ".venv", "bin", "python");
  if (!existsSync(p)) {
    console.error(
      `No backend virtualenv at ${p}\n\n` +
        `  python -m venv backend/.venv\n` +
        `  ${p} -m pip install -r backend/requirements-dev.txt\n`,
    );
    process.exit(1);
  }
  return p;
}

/** Clear anything a previous run left holding our ports. */
function preflight() {
  if (listeners(PORTS).length === 0) return;

  // Say this out loud. A leak that gets quietly tidied up on the next start is
  // still a leak, and staying quiet about it is how a broken shutdown goes
  // unnoticed for days.
  console.error(c(31, "! the previous session did not shut down cleanly - reaping it now"));
  console.error(c(31, "  if you pressed Ctrl+C, its cleanup failed - please report it"));

  const freed = freePorts(PORTS, {
    onKill: ({ kind, pid, port, cmd }) =>
      console.log(
        c(
          33,
          kind === "orphan"
            ? `- clearing orphan ${pid} (parent gone) ${shorten(cmd)}`
            : `- clearing process ${pid} on port ${port} (${shorten(cmd)})`,
        ),
      ),
    onForeign: (foreign) => {
      for (const f of foreign) {
        console.error(c(31, `x port ${f.port} is held by another program:`));
        console.error(c(31, `    ${f.cmd.slice(0, 140)}`));
      }
      console.error(c(31, "  Refusing to kill it. Free the port, or set API_PORT / WEB_PORT."));
    },
  });

  if (!freed) process.exit(1);
}

// `--clean` reaps and exits: for when you only want the ports back.
if (process.argv.includes("--clean")) {
  if (listeners(PORTS).length === 0) {
    console.log(c(32, `ok - ports ${API_PORT} and ${WEB_PORT} are already free`));
    process.exit(0);
  }
  preflight();
  console.log(c(32, `ok - ports ${API_PORT} and ${WEB_PORT} are now free`));
  process.exit(0);
}

const TASKS = [
  {
    name: "api",
    colour: 35,
    cmd: venvPython(),
    args: [
      "-m", "uvicorn", "app.main:app",
      "--app-dir", "backend",
      "--port", String(API_PORT),
      "--reload", "--reload-dir", "backend/app",
    ],
  },
  {
    name: "web",
    colour: 36,
    // next's own bin, not `npm run dev` -> `npx next`: two fewer layers for a
    // server to get orphaned behind.
    cmd: process.execPath,
    args: [
      join(ROOT, "node_modules", "next", "dist", "bin", "next"),
      "dev",
      "--port",
      String(WEB_PORT),
    ],
    env: { OTHER_MINDS_API_URL: `http://127.0.0.1:${API_PORT}` },
  },
];

const children = [];
// Declared here, assigned once the children exist. `let` rather than `const`
// so shutdown() can read it safely even if it runs before the assignment —
// `typeof` on a const in its temporal dead zone throws.
let reaper = null;
let shuttingDown = false;

function shutdown(reason, code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  if (reason) console.log(c(33, `\n- ${reason} - stopping both processes`));
  for (const ch of children) killTree(ch.pid);
  // The watchdog has nothing left to guard. If this line never runs — or the
  // kills above did not take — it notices we are gone and finishes the job,
  // which is the entire point of it.
  if (reaper?.pid) killTree(reaper.pid, { quiet: true });
  process.exit(code);
}

preflight();

for (const task of TASKS) {
  const child = spawn(task.cmd, task.args, {
    cwd: ROOT,
    stdio: ["ignore", "pipe", "pipe"],
    // POSIX: own process group, so the group can be signalled as one. On
    // Windows this would spawn a separate console, so `taskkill /T` covers it.
    detached: !IS_WIN,
    env: { ...process.env, ...task.env },
    windowsHide: true,
  });
  children.push(child);

  const tag = c(task.colour, `[${task.name}]`);
  const relay = (stream) => {
    let buffered = "";
    stream.setEncoding("utf8");
    stream.on("data", (chunk) => {
      buffered += chunk;
      const lines = buffered.split(/\r?\n/);
      buffered = lines.pop() ?? "";
      for (const line of lines) console.log(`${tag} ${line}`);
    });
  };
  relay(child.stdout);
  relay(child.stderr);

  child.on("exit", (code) => {
    // Half a stack is worse than none: the usual symptom is a frontend
    // proxying to a backend that is no longer there.
    if (!shuttingDown) shutdown(`${task.name} exited (code ${code})`, code ?? 1);
  });
  child.on("error", (err) => {
    console.error(`${tag} failed to start: ${err.message}`);
    if (!shuttingDown) shutdown(null, 1);
  });
}

// The watchdog, and the actual fix for Ctrl+C.
//
// Cleanup that runs inside the dying process is not dependable on Windows: the
// console delivers CTRL_C_EVENT to everything attached to it, so a killer
// spawned from the handler can be killed before it acts. This process is
// detached and console-less, so the signal cannot reach it. It is given the
// PORTS as well as the child pids, because a dying supervisor tends to orphan
// grandchildren that no longer belong to any tree we could kill.
reaper = spawn(
  process.execPath,
  [
    join(ROOT, "scripts", "dev-reaper.mjs"),
    "--parent",
    String(process.pid),
    "--children",
    children.map((ch) => ch.pid).filter(Boolean).join(","),
    "--ports",
    PORTS.join(","),
  ],
  { detached: true, stdio: "ignore", windowsHide: true },
);
// Never hold the event loop open on its account.
reaper.unref();

for (const signal of ["SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK"]) {
  process.on(signal, () => shutdown(signal));
}
// Last line of defence inside this process. The watchdog covers the rest.
process.on("exit", () => {
  for (const ch of children) killTree(ch.pid, { quiet: true });
  if (reaper?.pid) killTree(reaper.pid, { quiet: true });
});

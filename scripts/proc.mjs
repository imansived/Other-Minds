/**
 * Process and port helpers shared by the dev supervisor and its watchdog.
 *
 * Both need to answer the same two awkward questions — "what is holding this
 * port" and "how do I make it stop" — and they must answer them identically,
 * so the logic lives here rather than in two drifting copies.
 */

import { execFileSync, spawnSync } from "node:child_process";

export const IS_WIN = process.platform === "win32";

// Only processes matching this are ever killed automatically. Something else
// listening on port 3000 is the user's business, not ours.
export const OURS = /next|uvicorn|spawn_main|streamlit|multiprocessing|py\.mjs|dev\.mjs/i;

export function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

export const shorten = (cmd) => (cmd || "").trim().split(/\s+/)[0] || "unknown";

function powershell(script) {
  try {
    const out = execFileSync(
      "powershell",
      ["-NoProfile", "-NonInteractive", "-Command", script],
      { encoding: "utf8", maxBuffer: 8 * 1024 * 1024, windowsHide: true },
    ).trim();
    if (!out) return [];
    const parsed = JSON.parse(out);
    return Array.isArray(parsed) ? parsed : [parsed];
  } catch {
    return [];
  }
}

/**
 * What is listening on these ports.
 *
 * `alive` matters: Windows keeps the LISTENING entry under the PID that created
 * the socket even after that process dies, when a child inherited the handle.
 * A dead owner is therefore not "unknown, leave it alone" — it is the clearest
 * possible evidence of an orphan.
 */
export function listeners(ports) {
  if (!IS_WIN) {
    try {
      const args = ["-nP", ...ports.map((p) => `-iTCP:${p}`), "-sTCP:LISTEN", "-Fpc"];
      const out = execFileSync("lsof", args, { encoding: "utf8" });
      const found = [];
      let pid = null;
      for (const line of out.split("\n")) {
        if (line.startsWith("p")) pid = Number(line.slice(1));
        else if (line.startsWith("c") && pid) {
          found.push({ pid, cmd: line.slice(1), alive: true });
        }
      }
      return found;
    } catch {
      return [];
    }
  }
  const script = [
    `$ports = @(${ports.join(",")})`,
    `Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |`,
    `  Where-Object { $ports -contains $_.LocalPort } |`,
    `  ForEach-Object {`,
    `    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)" -ErrorAction SilentlyContinue`,
    `    [PSCustomObject]@{`,
    `      port  = $_.LocalPort`,
    `      owner = $_.OwningProcess`,
    `      alive = [bool]$proc`,
    `      cmd   = if ($proc) { "$($proc.Name) $($proc.CommandLine)" } else { "" }`,
    `    }`,
    `  } | ConvertTo-Json -Compress`,
  ].join("\n");
  return powershell(script).map((r) => ({
    port: r.port,
    pid: r.owner,
    alive: r.alive,
    cmd: r.cmd ?? "",
  }));
}

/**
 * Processes that look like ours whose parent no longer exists.
 *
 * This is how an inherited socket actually gets released: the PID on the
 * LISTENING row is dead, so there is nothing there to kill — the handle is held
 * by a surviving child. uvicorn's `--reload` worker is the usual culprit, and
 * its command line is `python -c "from multiprocessing.spawn import
 * spawn_main..."`, which is exactly why searching for "uvicorn" never finds it.
 */
export function orphans() {
  if (!IS_WIN) return [];
  const script = [
    `$all = Get-CimInstance Win32_Process`,
    `$live = @{}`,
    `foreach ($p in $all) { $live[[int]$p.ProcessId] = $true }`,
    `$all | Where-Object {`,
    `  $_.CommandLine -and`,
    `  $_.CommandLine -match 'uvicorn|spawn_main|multiprocessing|next|streamlit' -and`,
    `  -not $live.ContainsKey([int]$_.ParentProcessId)`,
    `} | ForEach-Object {`,
    `  [PSCustomObject]@{ opid = $_.ProcessId; cmd = "$($_.Name) $($_.CommandLine)" }`,
    `} | ConvertTo-Json -Compress`,
  ].join("\n");
  return powershell(script).map((r) => ({ pid: r.opid, cmd: r.cmd ?? "" }));
}

/**
 * Kill a process AND its descendants.
 *
 * `detached` is load-bearing on Windows, not tidiness. Ctrl+C delivers
 * CTRL_C_EVENT to every process attached to the console, so a `taskkill`
 * spawned normally from a SIGINT handler receives it too and dies before it
 * kills anything. Detaching puts it in its own process group, out of reach of
 * the event that is killing us.
 *
 * Failures are reported rather than swallowed: a silent failure here is what
 * let a broken shutdown look like a clean one.
 */
export function killTree(pid, { quiet = false } = {}) {
  if (!pid) return true;
  try {
    if (IS_WIN) {
      const r = spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], {
        detached: true,
        windowsHide: true,
        encoding: "utf8",
      });
      if (r.error) throw r.error;
      // 128 = "no such process": already gone, which is the outcome we wanted.
      if (r.status !== 0 && r.status !== 128 && !quiet) {
        const why = (r.stderr || r.stdout || "").trim();
        if (why && !/not found|could not be found/i.test(why)) {
          console.error(`  ! taskkill ${pid}: ${why.split(/\r?\n/)[0]}`);
        }
      }
    } else {
      try {
        process.kill(-pid, "SIGKILL");
      } catch {
        process.kill(pid, "SIGKILL");
      }
    }
  } catch (err) {
    if (!quiet) console.error(`  ! could not kill ${pid}: ${err.message}`);
    return false;
  }
  return true;
}

/**
 * Make these ports free, and report what had to be killed to get there.
 *
 * Loops because Windows lets several processes bind the same port when none
 * asked for exclusive use: killing one simply reveals the next, so a single
 * pass can report success while the port is still taken.
 *
 * `onForeign` is called instead of killing when a LIVE owner is not ours. It
 * decides what happens next — the supervisor refuses to start, the watchdog
 * simply leaves it alone.
 */
export function freePorts(ports, { onKill, onForeign, passes = 6 } = {}) {
  for (let attempt = 1; attempt <= passes; attempt++) {
    const found = listeners(ports);
    if (found.length === 0) return true;

    // Only a LIVE owner can be judged foreign. A dead one is an orphan.
    const foreign = found.filter((f) => f.alive && !OURS.test(f.cmd));
    if (foreign.length) {
      if (onForeign) onForeign(foreign);
      return false;
    }

    for (const f of found.filter((x) => x.alive)) {
      onKill?.({ kind: "listener", pid: f.pid, port: f.port, cmd: f.cmd, attempt });
      killTree(f.pid);
    }

    // A dead owner means a surviving child holds the inherited handle, so the
    // PID on the row cannot be killed — find the child instead.
    if (found.some((f) => !f.alive)) {
      for (const s of orphans()) {
        onKill?.({ kind: "orphan", pid: s.pid, cmd: s.cmd, attempt });
        killTree(s.pid);
      }
    }

    sleepSync(500);
  }
  return listeners(ports).length === 0;
}

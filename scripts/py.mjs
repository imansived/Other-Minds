#!/usr/bin/env node
// Runs a command inside the backend virtualenv, on any platform.
//
// npm scripts execute through cmd.exe on Windows, where a forward-slash path to
// an executable fails outright — and the venv layout differs between platforms
// anyway (Scripts/python.exe vs bin/python). Resolving both here keeps
// package.json readable and portable.

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const venv = join(root, "backend", ".venv");
const python =
  process.platform === "win32"
    ? join(venv, "Scripts", "python.exe")
    : join(venv, "bin", "python");

if (!existsSync(python)) {
  console.error(
    `No backend virtualenv at ${venv}\n\n` +
      `Create it with:\n` +
      `  python -m venv backend/.venv\n` +
      `  ${python} -m pip install -r backend/requirements-dev.txt\n`,
  );
  process.exit(1);
}

const child = spawn(python, process.argv.slice(2), {
  stdio: "inherit",
  cwd: root,
});
child.on("exit", (code, signal) => process.exit(signal ? 1 : (code ?? 0)));

// The browser feasibility gate (C work package §1; D-21, D-22). Dev-only test tooling.
//
//   node tests/browser/gate.mjs <site dir> <out.json> <python> [scenario:patch ...]
//
// Serves <site dir> with Python's http.server on 127.0.0.1, opens it in headless Chromium,
// loads DAIL through site/assets/js/dail-bridge.js and runs evaluate_fixed for each case. The
// traces the browser returned are written to <out.json>; tests/test_browser.py compares them
// with the native engine's.

import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
import net from "node:net";
import { chromium } from "playwright";

const [siteDir, outFile, python, ...cases] = process.argv.slice(2);

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

async function waitFor(url, tries = 100) {
  for (let i = 0; i < tries; i += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`the local server did not answer at ${url}`);
}

const port = await freePort();
const server = spawn(python, ["-m", "http.server", "--bind", "127.0.0.1", "-d", siteDir, String(port)], {
  stdio: "ignore",
});
const origin = `http://127.0.0.1:${port}`;
let browser;
try {
  await waitFor(`${origin}/vendor/files.json`);
  browser = await chromium.launch();
  const page = await browser.newPage();
  const console_ = [];
  page.on("console", (m) => console_.push(`${m.type()}: ${m.text()}`));
  page.on("pageerror", (e) => console_.push(`pageerror: ${e.message}`));
  await page.goto(`${origin}/vendor/files.json`);
  const started = Date.now();
  const result = await page.evaluate(async (pairs) => {
    const bridge = await import("/assets/js/dail-bridge.js");
    const t0 = performance.now();
    const dail = await bridge.loadDail({ vendor: "/vendor" });
    const loadMs = performance.now() - t0;
    const traces = {};
    const timings = {};
    for (const pair of pairs) {
      const [scenario, patch] = pair.split(":");
      const t = performance.now();
      const answer = dail.call("evaluate_fixed", scenario, patch);
      timings[pair] = performance.now() - t;
      traces[pair] = answer;
    }
    const versions = dail.pyodide.runPython("import sys, sqlite3\nf'{sys.version} | sqlite {sqlite3.sqlite_version}'");
    return { loadMs, traces, timings, bytes: dail.bytes, files: dail.files, python: versions };
  }, cases);
  result.wallMs = Date.now() - started;
  result.browser = browser.version();
  result.console = console_;
  writeFileSync(outFile, JSON.stringify(result));
  console.log(`browser ${result.browser}; ${result.python}; loaded ${result.files} files + Pyodide (${result.bytes} bytes) in ${Math.round(result.loadMs)} ms`);
  for (const [pair, answer] of Object.entries(result.traces)) {
    const c = answer.ok ? answer.value.comparison : null;
    console.log(`${pair}: ${answer.ok ? `C ${c.C.decision} (${c.C.check_count}) A ${c.A.decision} (${c.A.check_count})` : `ERROR ${answer.error}`} in ${Math.round(result.timings[pair])} ms`);
  }
} finally {
  if (browser) await browser.close();
  server.kill();
}

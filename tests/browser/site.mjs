// Drives the real page (site/index.html) in headless Chromium (D-21). Dev-only test tooling.
//
//   node tests/browser/site.mjs <site dir> <python> check <out.json>
//   node tests/browser/site.mjs <site dir> <python> shots <dir>
//
// "check" runs the live demo path end to end through the page's own controls (quick fill,
// Submit to the gate, Verify chain, Reset) and the replays, and writes what the page showed.
// "shots" takes the screenshots for docs/screenshots/ (1366x768 and 390x844).

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import net from "node:net";
import { chromium } from "playwright";

const [siteDir, python, command, target] = process.argv.slice(2);

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.unref();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}
async function waitFor(url) {
  for (let i = 0; i < 100; i += 1) {
    try { if ((await fetch(url)).ok) return; } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`no answer at ${url}`);
}

const port = await freePort();
const server = spawn(python, ["-m", "http.server", "--bind", "127.0.0.1", "-d", siteDir, String(port)], { stdio: "ignore" });
const origin = `http://127.0.0.1:${port}`;
const browser = await (async () => { await waitFor(`${origin}/index.html`); return chromium.launch(); })();

async function newPage(viewport, options = {}) {
  const context = await browser.newContext({ viewport, reducedMotion: options.reducedMotion || "no-preference" });
  const page = await context.newPage();
  const log = [];
  page.on("console", (m) => { if (m.type() === "error") log.push(`console: ${m.text()}`); });
  page.on("pageerror", (e) => log.push(`pageerror: ${e.message}`));
  page.on("requestfailed", (r) => log.push(`requestfailed: ${r.url()}`));
  page.on("response", (r) => { if (r.status() >= 400) log.push(`http ${r.status()}: ${r.url()}`); });
  return { page, context, log };
}

const text = (page, sel) => page.locator(sel).first().innerText();
async function waitDecision(page) {
  await page.waitForFunction(() => document.querySelector("#stamp") || document.querySelector(".refused"), null, { timeout: 120000 });
}
async function goLive(page) {
  await page.click("#mode-live");
  await page.waitForSelector("#editor-panel:not([hidden])", { timeout: 180000 });
}
async function fill(page, name) {
  await page.click(`[data-fill="${name}"]`);
}
async function submit(page) {
  await page.click("#submit");
  await page.waitForFunction(() => document.querySelector("#submit").textContent === "Submit to the gate" && document.querySelector("#announce").textContent.length > 0 && !document.querySelector("#announce").textContent.startsWith("DAIL is checking"), null, { timeout: 120000 });
  await waitDecision(page);
}
async function readDecision(page) {
  return page.evaluate(() => ({
    stamp: document.querySelector("#stamp") ? document.querySelector("#stamp").firstChild.textContent : null,
    refused: !!document.querySelector(".refused"),
    note: document.querySelector(".browser-note") ? document.querySelector(".browser-note").textContent : null,
    ovf: [...document.querySelectorAll(".ovf__col")].map((c) => ({
      verdict: c.querySelector(".ovf__verdict").textContent, count: c.querySelector(".ovf__count").textContent })),
    clippings: [...document.querySelectorAll(".clipping__version")].map((e) => e.textContent),
    announce: document.querySelector("#announce").textContent,
    issue: document.querySelector("#issue").textContent,
  }));
}

try {
  if (command === "check") {
    const out = {};
    // live: the demo path through the page's own controls
    {
      const { page, log } = await newPage({ width: 1366, height: 768 });
      const t0 = Date.now();
      await page.goto(`${origin}/index.html`);
      out.loadingTitle = await page.evaluate(async () => {
        document.querySelector("#mode-live").click();
        for (let i = 0; i < 50; i += 1) {
          const t = document.querySelector("#loading-title").textContent;
          if (/MB\)/.test(t)) return t;
          await new Promise((r) => setTimeout(r, 50));
        }
        return document.querySelector("#loading-title").textContent;
      });
      await page.waitForSelector("#editor-panel:not([hidden])", { timeout: 180000 });
      out.liveReadyMs = Date.now() - t0;
      await fill(page, "regression"); await submit(page); out.regression = await readDecision(page);
      await fill(page, "safe"); await submit(page); out.safe = await readDecision(page);
      // a third candidate from v1, typed: a harmless instance size change
      const v1 = await page.inputValue("#editor");
      // promote (v1), reject (against v1), promote (v2)
      await fill(page, "regression"); await submit(page); out.rejectFromV1 = await readDecision(page);
      out.thirdEdit = v1.includes('"t3.micro"');
      await page.fill("#editor", v1.replace('instance_type               = "t3.micro"', 'instance_type               = "t3.small"'));
      await submit(page); out.third = await readDecision(page);
      await page.click("#verify");
      await page.waitForSelector(".verify-result");
      out.verifyAfterThree = await text(page, ".verify-result");
      // Live -> Replays -> Live keeps the tab's session
      await page.click("#mode-replays");
      await page.waitForFunction(() => document.querySelector("#issue").textContent.startsWith("Replay"));
      out.verifyHiddenInReplays = await page.locator("#verify").isHidden();
      await page.click("#mode-live");
      await page.waitForFunction(() => document.querySelector("#issue").textContent.startsWith("Session"));
      out.resumed = await readDecision(page);
      // presenter mode in live mode with three clippings, page at the top
      await page.click("#presenter");
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(1500);
      out.presenterLive = await page.evaluate(() => {
        const r = (e) => e.getBoundingClientRect();
        const shown = (sel) => [...document.querySelectorAll(sel)].filter((e) => getComputedStyle(e).display !== "none");
        const over = shown(".stage, .ovf__col, .ovf, .clipping").filter((e) => r(e).right > window.innerWidth || e.scrollWidth > e.clientWidth + 1).map((e) => e.className);
        return { vh: window.innerHeight, stages: Math.max(...shown(".stage").map((e) => r(e).bottom)), stamp: r(document.querySelector("#stamp")).bottom, ovf: r(document.querySelector(".ovf")).bottom, ledger: Math.max(...shown(".clipping").map((e) => r(e).bottom)), clippings: shown(".clipping").length, over };
      });
      await page.click("#presenter");
      // a refusal before DAIL: an edit outside resource blocks
      await page.fill("#editor", (await page.inputValue("#editor")) + '\noutput "x" {\n  value = 1\n}\n');
      await submit(page); out.refusal = await readDecision(page);
      out.refusalText = await text(page, ".refused");
      await page.click("#verify");
      await page.waitForSelector(".verify-result");
      out.verify = await text(page, ".verify-result");
      await page.click("#reset");
      await page.waitForFunction(() => document.querySelectorAll(".clipping").length === 1);
      out.afterReset = await readDecision(page);
      out.liveLog = log;
    }
    // replays: every recorded run renders
    {
      const { page, log } = await newPage({ width: 1366, height: 768 });
      await page.goto(`${origin}/index.html`);
      await page.waitForSelector("#stamp, .refused", { timeout: 30000 });
      const runs = await page.evaluate(async () => (await (await fetch("runs/index.json")).json()).runs);
      out.replays = [];
      for (const run of runs) {
        await page.selectOption("#scenario", run.scenario_id);
        await page.selectOption("#replay", run.file);
        await page.waitForFunction((file) => true, run.file);
        await page.waitForTimeout(150);
        const shown = await readDecision(page);
        out.replays.push({ file: run.file, expected: run.decisions, shown, gemini: await page.locator("text=Generated by Gemini").count() });
      }
      out.pyodideRequestedInReplays = await page.evaluate(() => performance.getEntriesByType("resource").some((e) => e.name.includes("pyodide")));
      out.replayBytes = await page.evaluate(() => performance.getEntriesByType("resource").reduce((n, e) => n + (e.transferSize || e.encodedBodySize || 0), 0));
      out.replayLog = log;
    }
    // the signature motion: the candidate card travels across the trust boundary
    {
      const { page } = await newPage({ width: 1366, height: 768 });
      await page.goto(`${origin}/index.html`);
      await page.waitForSelector("#stamp");
      out.crossing = await page.evaluate(async () => {
        const boundary = document.querySelector(".boundary").getBoundingClientRect().left;
        const xs = [];
        document.querySelector("#replay").dispatchEvent(new Event("change"));
        const t0 = performance.now();
        while (performance.now() - t0 < 1500) {
          const g = document.querySelector(".card--crossing");
          if (g) xs.push(g.getBoundingClientRect().left);
          await new Promise(requestAnimationFrame);
        }
        return { boundary, min: Math.min(...xs), max: Math.max(...xs), left: !!document.querySelector(".card--crossing") };
      });
    }
    // first page load per mode (fresh pages, nothing cached)
    for (const [name, url, ready] of [["replays", "/index.html", "#stamp"], ["live", "/index.html?mode=live", "#editor-panel:not([hidden])"]]) {
      const { page } = await newPage({ width: 1366, height: 768 });
      await page.goto(`${origin}${url}`);
      await page.waitForSelector(ready, { timeout: 180000 });
      out[`firstLoad_${name}`] = await page.evaluate(() => {
        const entries = performance.getEntriesByType("resource");
        const nav = performance.getEntriesByType("navigation")[0];
        const size = (e) => e.encodedBodySize || e.transferSize || 0;
        return { bytes: entries.reduce((n, e) => n + size(e), 0) + size(nav), requests: entries.length + 1 };
      });
    }
    // motion and presenter mode classes
    {
      const { page } = await newPage({ width: 1366, height: 768 }, { reducedMotion: "reduce" });
      await page.goto(`${origin}/index.html`);
      await page.waitForSelector("#stamp");
      out.reducedMotionClass = await page.evaluate(() => document.documentElement.classList.contains("reduce-motion"));
      out.stampAnimation = await page.evaluate(() => getComputedStyle(document.querySelector("#stamp")).animationName);
      await page.click("#presenter");
      out.presenterClass = await page.evaluate(() => document.documentElement.classList.contains("presenter"));
      out.presenterBodyFont = await page.evaluate(() => getComputedStyle(document.querySelector(".stage__body")).fontSize);
      await page.evaluate(() => document.querySelector("#zones").scrollIntoView());
      out.presenterFits = await page.evaluate(() => {
        const vh = window.innerHeight;
        const box = (sel) => { const r = document.querySelector(sel).getBoundingClientRect(); return { top: r.top, bottom: r.bottom }; };
        const stages = [...document.querySelectorAll(".stage")].map((s) => s.getBoundingClientRect().bottom);
        const clips = [...document.querySelectorAll(".clipping")].filter((c) => getComputedStyle(c).display !== "none").map((c) => c.getBoundingClientRect().bottom);
        return { vh, stagesBottom: Math.max(...stages), stamp: box("#stamp"), ovf: box(".ovf"), ledgerBottom: Math.max(...clips), top: box("#zones").top };
      });
      out.noHorizontalScroll = {};
      for (const width of [390, 768, 1366]) {
        await page.setViewportSize({ width, height: 844 });
        out.noHorizontalScroll[width] = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
      }
    }
    writeFileSync(target, JSON.stringify(out, null, 1));
    console.log(JSON.stringify({ regression: out.regression.stamp, safe: out.safe.stamp, refused: out.refusal.refused, verify: out.verify, replays: out.replays.length }));
  } else if (command === "shots") {
    mkdirSync(target, { recursive: true });
    const desk = { width: 1366, height: 768 };
    const phone = { width: 390, height: 844 };
    {
      const { page } = await newPage(desk, { reducedMotion: "reduce" });
      await page.goto(`${origin}/index.html`);
      await goLive(page);
      await fill(page, "regression"); await submit(page);
      await page.screenshot({ path: `${target}/1366-live-reject.png`, fullPage: true });
      await fill(page, "safe"); await submit(page);
      await page.screenshot({ path: `${target}/1366-live-promote-two-clippings.png`, fullPage: true });
      await page.click("#presenter");
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: `${target}/1366-presenter.png` });
    }
    {
      const { page } = await newPage(desk, { reducedMotion: "reduce" });
      await page.goto(`${origin}/index.html`);
      await page.waitForSelector("#stamp");
      await page.screenshot({ path: `${target}/1366-replay-regression.png`, fullPage: true });
      const runs = await page.evaluate(async () => (await (await fetch("runs/index.json")).json()).runs);
      const gemini = runs.find((r) => r.source === "LLM");
      if (gemini) {
        await page.selectOption("#scenario", gemini.scenario_id);
        await page.selectOption("#replay", gemini.file);
        await page.waitForSelector("text=Generated by Gemini");
        await page.screenshot({ path: `${target}/1366-replay-gemini.png`, fullPage: true });
      }
    }
    {
      const { page } = await newPage(phone, { reducedMotion: "reduce" });
      await page.goto(`${origin}/index.html`);
      await page.waitForSelector("#stamp");
      await page.screenshot({ path: `${target}/390-replay.png`, fullPage: true });
      await goLive(page);
      await fill(page, "regression"); await submit(page);
      await page.screenshot({ path: `${target}/390-live-reject.png`, fullPage: true });
    }
    console.log(`screenshots written to ${target}`);
  }
} finally {
  await browser.close();
  server.kill();
}

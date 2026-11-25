// Drives the real page through the real `serve` with a fake Gemini, in a browser (D-21). Dev-only.
//
//   node tests/browser/site.mjs <python> check <out.json>
//   node tests/browser/site.mjs <python> shots <dir>
//
// DAIL_LIVE_BROWSER=chrome|msedge uses the installed browser; DAIL_LIVE_HEADED=1 shows it.

import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const [python, command, target] = process.argv.slice(2);
const here = dirname(fileURLToPath(import.meta.url));
const tmp = mkdtempSync(join(tmpdir(), "dail-live-site-"));
const seenFile = join(tmp, "seen.json");
const server = spawn(python, [join(here, "serve_fake.py"), seenFile], { stdio: ["ignore", "pipe", "inherit"] });
const port = await new Promise((resolve, reject) => {
  server.stdout.once("data", (d) => resolve(String(d).trim()));
  server.once("exit", () => reject(new Error("the local server stopped")));
});
const origin = `http://127.0.0.1:${port}`;
const seen = () => { try { return JSON.parse(readFileSync(seenFile, "utf8")); } catch { return []; } };
const browser = await chromium.launch({ channel: process.env.DAIL_LIVE_BROWSER || undefined, headless: process.env.DAIL_LIVE_HEADED !== "1" });
const DESK = { width: 1366, height: 768 };
const PHONE = { width: 390, height: 844 };

async function open(viewport = DESK, { reduced = false, path = "/index.html" } = {}) {
  const context = await browser.newContext({ viewport, reducedMotion: reduced ? "reduce" : "no-preference" });
  const page = await context.newPage();
  const log = [];
  page.on("console", (m) => { if (m.type() === "error") log.push(m.text()); });
  page.on("pageerror", (e) => log.push(`pageerror: ${e.message}`));
  const finished = [];
  context.on("requestfinished", (r) => finished.push(r));
  await page.goto(origin + path);
  return { page, context, log, finished };
}
const ready = (page) => page.waitForFunction(() => !document.querySelector("#ask").disabled, null, { timeout: 180000 });
const idle = (page) => page.waitForFunction(() => !document.querySelector("#reset").disabled && !document.querySelector("#writing"), null, { timeout: 120000 });
async function ask(page, text) {
  await page.fill("#instruction", text);
  await page.click("#ask");
  await page.waitForFunction(() => document.querySelector("#ask").disabled);
  await idle(page);
}
const read = (page) => page.evaluate(() => {
  const t = (s) => document.querySelector(s) && document.querySelector(s).textContent;
  const all = (s) => [...document.querySelectorAll(s)].map((e) => e.textContent);
  return {
    stamp: t("#stamp"), reason: t("#reason"), normal: t("#normal"), gaveUp: t("#gave-up"), refused: t("#refused"),
    refusedReason: t(".refused__reason"), note: t(".browser-note"), changes: all(".changes li"), attempts: all("#attempts .tab"),
    attemptNote: document.querySelector("#attempt-note").hidden ? null : t("#attempt-note"),
    ledger: all("#ledger .state"), health: all("#health .pill"), announce: t("#announce"),
    notice: document.querySelector("#notice").hidden ? null : t("#notice"),
    evidenceOpen: document.querySelector("#evidence").open, boxes: document.querySelectorAll(".box.is-done").length,
  };
});

async function check() {
  const out = { browser: `${process.env.DAIL_LIVE_BROWSER || "chromium"} ${browser.version()}` };
  { // first load per tab
    for (const [name, path, wait] of [["replays", "/index.html?tab=replays", "#stamp"], ["ask", "/index.html", "#ask:not([disabled])"]]) {
      const { page, context, finished } = await open(DESK, { path });
      await page.waitForSelector(wait, { timeout: 180000 });
      const sizes = await Promise.all(finished.map((r) => r.sizes().then((z) => z.responseBodySize).catch(() => 0)));
      out[`firstLoad_${name}`] = { bytes: sizes.reduce((a, b) => a + b, 0), requests: sizes.length };
      await context.close();
    }
  }
  { // the loop
    const { page, context, log } = await open();
    const t0 = Date.now();
    await ready(page);
    out.readyMs = Date.now() - t0;
    out.first = await read(page);
    out.firstText = await page.evaluate(() => document.querySelector("main").innerText);
    await page.click("#chips .btn:nth-child(3)");
    out.chip = await page.inputValue("#instruction");
    await page.evaluate(() => {
      window.__moments = []; window.__fills = []; window.__xs = [];
      new MutationObserver(() => {
        const note = document.querySelector("#attempt-note");
        const stamp = document.querySelector("#stamp");
        const writing = document.querySelector(".writing");
        const m = [stamp && stamp.textContent, note.hidden ? null : note.textContent, writing && writing.textContent].join("|");
        if (m !== window.__moments.at(-1)) window.__moments.push(m);
        const done = document.querySelectorAll(".box.is-done").length;
        if (!stamp && done && done !== window.__fills.at(-1)) window.__fills.push(done);
      }).observe(document.querySelector("#main-panel"), { subtree: true, childList: true, attributes: true, characterData: true });
      (function watch() {
        const g = document.querySelector(".card--crossing");
        if (g) { const r = g.getBoundingClientRect(); window.__xs.push([r.top, document.querySelector(".boundary").getBoundingClientRect().top]); }
        requestAnimationFrame(watch);
      })();
    });
    await page.click("#ask");
    await page.waitForFunction(() => document.querySelector("#ask").disabled);
    await idle(page);
    out.loop = await read(page);
    out.stampInView = await page.evaluate(() => { const r = document.querySelector("#stamp").getBoundingClientRect(); return r.top > 0 && r.bottom < innerHeight; });
    out.moments = await page.evaluate(() => window.__moments);
    out.fills = await page.evaluate(() => window.__fills);
    out.crossed = await page.evaluate(() => ({ above: window.__xs.some(([y, b]) => y < b), below: window.__xs.some(([y, b]) => y > b) }));
    out.seenAfterLoop = seen();
    await page.click("#attempts .tab:nth-child(1)");
    out.attemptOne = await read(page);
    await page.click("#evidence > summary");
    out.evidenceDetails = await page.evaluate(() => ["#evidence-body .check", "#evidence-body .pill--affected", "#evidence-body .pill--carried", "#evidence-body .ovf", "#evidence-body .blocking li"].map((s) => document.querySelectorAll(s).length));
    out.evidence = await page.locator("#evidence-body").innerText();
    await page.click("#evidence > summary");
    await page.click("#code > summary");
    out.code = await page.locator("#code .diff").innerText();
    await page.click("#attempts .tab:nth-child(2)");
    await page.click("#ledger .state:last-of-type");
    await page.locator("#ledger .state").last().click();
    out.stateDetail = await page.locator("#state-detail").innerText();
    await page.click("#verify");
    await page.waitForSelector(".verify-result");
    out.verify = await page.locator(".verify-result").innerText();
    // tabs keep the session
    await page.click("#tab-replays");
    await page.waitForSelector("#stamp");
    out.replayShown = await read(page);
    await page.click("#tab-write");
    await page.waitForFunction(() => document.querySelector("#editor").value.length > 100);
    out.writeEmpty = await read(page);
    await page.click('[data-fill="regression"]');
    await page.waitForFunction(() => document.activeElement === document.querySelector("#editor"));
    await page.click("#submit"); await page.waitForFunction(() => document.querySelector("#submit").disabled); await idle(page);
    out.own = await read(page);
    await page.fill("#editor", (await page.inputValue("#editor")) + '\noutput "x" {\n  value = 1\n}\n');
    await page.click("#submit"); await page.waitForFunction(() => document.querySelector("#submit").disabled); await idle(page);
    out.ownRefused = await read(page);
    await page.click("#tab-ask");
    out.backToAsk = await read(page);
    await page.evaluate(() => { document.querySelector("#system-picker").open = true; });
    await page.click("#reset"); await idle(page);
    out.afterReset = await read(page);
    // three failures
    await ask(page, "FAIL ALWAYS");
    out.threeFailures = await read(page);
    // a reply DAIL's parser refuses counts as an attempt
    await ask(page, "GARBAGE");
    out.garbage = await read(page);
    await page.click("#attempts .tab:nth-child(1)");
    out.garbageOne = await read(page);
    // quota
    out.logBeforeQuota = [...log];
    await ask(page, "QUOTA");
    out.quota = await read(page);
    await context.close();
  }
  { // another system than the canonical one can be asked about and judged
    const { page, context, log } = await open();
    await ready(page);
    await page.evaluate(() => { document.querySelector("#system-picker").open = true; });
    await page.selectOption("#scenario", "tp-v1-F4-0092");
    await idle(page);
    out.otherSystem = await read(page);
    await page.click("#tab-write");
    await page.click('[data-fill="fixed"]');
    await page.waitForFunction(() => document.activeElement === document.querySelector("#editor"));
    await page.click("#submit"); await page.waitForFunction(() => document.querySelector("#submit").disabled); await idle(page);
    out.otherOwn = await read(page);
    out.otherLog = log;
    await context.close();
  }
  { // every replay
    const { page, context, log } = await open(DESK, { path: "/index.html?tab=replays", reduced: true });
    await page.waitForSelector("#stamp");
    const runs = await page.evaluate(async () => (await (await fetch("runs/index.json")).json()).runs);
    out.replays = [];
    for (const run of runs) {
      const loaded = page.waitForResponse((r) => r.url().endsWith(run.file));
      await page.selectOption("#replay", run.file);
      await loaded;
      await page.waitForTimeout(120);
      out.replays.push({ file: run.file, expected: run.decisions, shown: await read(page), gemini: await page.locator("#proposal >> text=Generated by Gemini").count() });
    }
    out.pyodideInReplays = await page.evaluate(() => performance.getEntriesByType("resource").some((e) => e.name.includes("pyodide")));
    out.replayLog = log;
    out.reducedMotion = await page.evaluate(() => [document.documentElement.classList.contains("reduce-motion"), getComputedStyle(document.querySelector("#stamp")).animationName]);
    out.noHorizontalScroll = {};
    for (const width of [390, 768, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      await page.evaluate(() => { document.querySelector("#evidence").open = true; });
      out.noHorizontalScroll[width] = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
    }
    out.smallText = await page.evaluate(() => [...document.querySelectorAll("body *")].filter((e) => e.childNodes.length && [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) && parseFloat(getComputedStyle(e).fontSize) < 16).map((e) => e.className || e.tagName));
    out.smallOnColour = await page.evaluate(() => [...document.querySelectorAll(".stamp--promote, .stamp--reject, .pill--pass, .pill--fail, .ovf__verdict--promote, .ovf__verdict--reject")].filter((e) => parseFloat(getComputedStyle(e).fontSize) < 18.66 || Number(getComputedStyle(e).fontWeight) < 700).length);
    await context.close();
  }
  { // presenter mode after the loop
    const { page, context } = await open(DESK, { reduced: true });
    await ready(page);
    await ask(page, CHIP3);
    await page.click("#presenter");
    out.presenter = await page.evaluate(() => {
      const r = (s) => document.querySelector(s).getBoundingClientRect();
      const inside = {};
      for (const s of ["#boxes", "#stamp", "#reason", "#normal", "#ledger"]) inside[s] = [Math.round(r(s).top), Math.round(r(s).bottom)];
      return { on: document.documentElement.classList.contains("presenter"), font: getComputedStyle(document.body).fontSize, vh: innerHeight, band: Math.round(r(".band").bottom), inside, lines: getComputedStyle(document.querySelector(".editor__lines")).display };
    });
    // the keyboard reaches the main controls
    await page.evaluate(() => window.scrollTo(0, 0));
    out.keyboard = await page.evaluate(() => ["#presenter", "#tab-ask", "#instruction", "#ask", "#evidence > summary", "#ledger .state", "#verify"].filter((s) => { const e = document.querySelector(s); e.focus(); return document.activeElement !== e; }));
    await context.close();
  }
  writeFileSync(target, JSON.stringify(out, null, 1));
  console.log(JSON.stringify({ browser: out.browser, loop: out.loop.attempts, ledger: out.loop.ledger, replays: out.replays.length }));
}

const CHIP3 = "Close SSH and tidy up the database rules";

async function shots() {
  mkdirSync(target, { recursive: true });
  for (const [prefix, viewport] of [["1366", DESK], ["390", PHONE]]) {
    const { page, context } = await open(viewport, { reduced: true });
    await ready(page);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: `${target}/${prefix}-1-first-screen.png` });
    await page.screenshot({ path: `${target}/${prefix}-1-first-page.png`, fullPage: true });
    await page.fill("#instruction", CHIP3);
    await page.click("#ask");
    await page.waitForSelector(".writing");
    await page.waitForTimeout(250);
    await page.screenshot({ path: `${target}/${prefix}-2-ai-writing.png` });
    await page.waitForSelector(".stamp--reject");
    await page.screenshot({ path: `${target}/${prefix}-3-reject.png` });
    await page.waitForFunction(() => !document.querySelector("#attempt-note").hidden);
    await page.waitForTimeout(250);
    await page.screenshot({ path: `${target}/${prefix}-4-retry.png` });
    await page.waitForSelector(".stamp--promote");
    await idle(page);
    await page.screenshot({ path: `${target}/${prefix}-5-promote.png` });
    await page.screenshot({ path: `${target}/${prefix}-5-promote-page.png`, fullPage: true });
    await page.evaluate(() => { document.querySelector("#evidence").open = true; });
    await page.screenshot({ path: `${target}/${prefix}-6-evidence.png`, fullPage: true });
    await page.evaluate(() => { document.querySelector("#evidence").open = false; });
    if (prefix === "1366") {
      await page.click("#presenter");
      await page.waitForTimeout(250);
      await page.screenshot({ path: `${target}/1366-7-presenter.png` });
    }
    await context.close();
  }
  console.log(`screenshots written to ${target}`);
}

try {
  await (command === "shots" ? shots() : check());
} finally {
  await browser.close();
  server.kill();
  rmSync(tmp, { recursive: true, force: true });
}

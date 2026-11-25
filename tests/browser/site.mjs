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
const DESK = { width: 1440, height: 900 };
const PRESENTER = { width: 1366, height: 768 };
const PHONE = { width: 390, height: 844 };
const RISKY = "Close SSH and tidy up the database rules";

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
// a request is over: nothing is waiting for Gemini or for DAIL
const idle = (page) => page.waitForFunction(() => document.querySelector("#stop").hidden && !document.querySelector("#thread .writing")
  && [...document.querySelectorAll("#thread .dail")].every((d) => d.querySelector(".dail__foot")), null, { timeout: 120000 });

async function ask(page, text, { dock = false } = {}) {
  const box = dock ? "#next" : "#instruction";
  await page.fill(box, text);
  await page.press(box, "Enter");
  await page.waitForFunction(() => !document.querySelector("#stop").hidden || !document.querySelector("#thread-notice").hidden);
  await idle(page);
}

async function submitOwn(page) {
  const before = await page.locator("#thread .dail .dail__foot").count();
  await page.click("#submit");
  await page.waitForFunction((n) => document.querySelectorAll("#thread .dail .dail__foot").length > n
    || !document.querySelector("#thread-notice").hidden, before, { timeout: 120000 });
}

// What the page shows, read from the DOM only.
const read = (page) => page.evaluate(() => {
  const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : null);
  const shown = (s) => { const el = document.querySelector(s); return el && !el.hidden ? text(el) : null; };
  const card = (d) => d && {
    id: d.id,
    stamp: d.querySelector(".stamp") ? d.querySelector(".stamp").firstChild.textContent : null,
    by: text(d.querySelector(".stamp__by")),
    sentence: text(d.querySelector(".sentence")),
    raw: text(d.querySelector(".raw")),
    counts: text(d.querySelector(".dail__counts")),
    cells: [...d.querySelectorAll(".cell")].map((c) => text(c.querySelector(".cell__text"))),
    compare: text(d.querySelector(".compare")),
    note: text(d.querySelector(".browser-note")),
    mini: [...d.querySelectorAll(".vpill")].map((v) => v.firstChild.textContent),
    fresh: d.querySelector(".vpill.is-new") ? d.querySelector(".vpill.is-new").firstChild.textContent : null,
    verifyButton: [...d.querySelectorAll("button")].some((b) => b.textContent === "Verify chain"),
  };
  const cards = [...document.querySelectorAll("#thread .dail")];
  return {
    kinds: [...document.querySelectorAll("#thread > li")].map((li) => (li.firstElementChild ? li.firstElementChild.className.split(" ")[0] : "empty")),
    last: card(cards.at(-1)),
    cards: cards.map(card),
    gemini: [...document.querySelectorAll("#thread .gemini")].map((g) => ({
      label: g.getAttribute("aria-label"), title: text(g.querySelector(".gemini__title")), note: text(g.querySelector(".gemini__note")),
      changes: [...g.querySelectorAll(".changes li")].map(text), stripe: text(g.querySelector(".gemini__stripe")),
    })),
    you: [...document.querySelectorAll("#thread .you__bubble")].map(text),
    banners: [...document.querySelectorAll("#thread .banner")].map(text),
    collapsed: [...document.querySelectorAll("#thread .collapsed")].map(text),
    finals: [...document.querySelectorAll("#thread .final")].map(text),
    recorded: text(document.querySelector("#thread .recorded")),
    health: [...document.querySelectorAll("#health .pill")].map(text),
    status: document.querySelector("#status").hidden ? null : {
      version: text(document.querySelector("#status-version")), pills: [...document.querySelectorAll("#status-pills .pill")].map(text),
    },
    ledgerButton: text(document.querySelector("#ledger-open")),
    announce: text(document.querySelector("#announce")),
    askNotice: shown("#ask-notice"), threadNotice: shown("#thread-notice"),
    askScreen: !document.querySelector("#ask-screen").hidden, dock: !document.querySelector("#dock").hidden,
    placeholder: document.querySelector("#next").placeholder,
  };
});

async function check() {
  const out = { browser: `${process.env.DAIL_LIVE_BROWSER || "chromium"} ${browser.version()}` };
  { // first load per tab
    for (const [name, path, wait] of [["replays", "/index.html?tab=replays", "#runs .run"], ["ask", "/index.html", "#ask:not([disabled])"]]) {
      const { page, context, finished } = await open(DESK, { path });
      await page.waitForSelector(wait, { timeout: 180000 });
      await page.waitForTimeout(300);
      const sizes = await Promise.all(finished.map((r) => r.sizes().then((z) => z.responseBodySize).catch(() => 0)));
      out[`firstLoad_${name}`] = { bytes: sizes.reduce((a, b) => a + b, 0), requests: sizes.length };
      await context.close();
    }
  }
  { // the loop: regression, then the safe patch
    const { page, context, log } = await open();
    const t0 = Date.now();
    await ready(page);
    out.readyMs = Date.now() - t0;
    out.first = await read(page);
    out.firstText = await page.evaluate(() => document.querySelector("#ask-screen").innerText);
    out.model = await page.locator("#model-meta").innerText();
    await page.click("#chips .chip--risky");
    out.chip = await page.inputValue("#instruction");
    out.chipLabels = await page.locator("#chips .chip").allInnerTexts();
    await page.evaluate(() => {
      window.__fills = []; window.__said = [];
      new MutationObserver(() => {
        const waiting = [...document.querySelectorAll("#thread .dail")].find((d) => !d.querySelector(".dail__foot"));
        if (!waiting) return;
        const done = waiting.querySelectorAll(".cell.is-done").length;
        const last = window.__fills.at(-1);
        if (!last || last[0] !== waiting.id || last[1] !== done) window.__fills.push([waiting.id, done]);
      }).observe(document.querySelector("#thread"), { subtree: true, childList: true, attributes: true });
      new MutationObserver(() => {
        const t = document.querySelector("#announce").textContent;
        if (t && t !== window.__said.at(-1)) window.__said.push(t);
      }).observe(document.querySelector("#announce"), { childList: true, characterData: true, subtree: true });
    });
    await page.click("#ask");
    await page.waitForSelector("#thread .writing");
    out.writing = await page.locator("#thread .writing").innerText();
    await page.waitForSelector("#thread .banner");
    out.atBanner = await read(page);
    await idle(page);
    out.loop = await read(page);
    out.fills = await page.evaluate(() => window.__fills);
    out.stampInView = await page.waitForFunction(() => {
      const r = document.querySelector("#dail-2 .stamp").getBoundingClientRect();
      return r.top > document.querySelector("#hdr").getBoundingClientRect().bottom && r.bottom < document.querySelector("#dock .dock__box").getBoundingClientRect().top;
    }, null, { timeout: 3000 }).then(() => true, () => false);
    out.said = await page.evaluate(() => window.__said);
    out.seenAfterLoop = seen();
    // the collapsed attempt opens again
    await page.click("#thread .collapsed button");
    out.reopened = await read(page);
    // DAIL's evidence of attempt 1, and its code
    await page.click("#dail-1 [aria-controls='evidence-1']");
    out.evidence = await page.locator("#evidence-1").innerText();
    out.evidenceCounts = await page.evaluate(() => ["#evidence-1 .tag--pass", "#evidence-1 .tag--fail", "#evidence-1 .tag--marker", "#evidence-1 .tag--carry", "#evidence-1 .affects__path"].map((s) => document.querySelectorAll(s).length));
    await page.locator("#thread .gemini summary").first().click();
    out.code = await page.locator("#thread .gemini .diff").first().innerText();
    out.diffLines = await page.evaluate(() => [document.querySelectorAll("#thread .diff .add").length, document.querySelectorAll("#thread .diff .del").length]);
    // Verify chain on the PROMOTE card
    await page.locator("#dail-2 button", { hasText: "Verify chain" }).click();
    await page.waitForSelector("#dail-2 .verify-result--ok, #dail-2 .verify-result--bad");
    out.verify = await page.locator("#dail-2 .verify-slot").innerText();
    // the ledger drawer
    await page.click("#ledger-open");
    out.drawer = await page.locator("#drawer").innerText();
    out.drawerStates = await page.locator("#states .state").count();
    await page.click("#verify");
    await page.waitForSelector("#verify-result .verify-result--ok, #verify-result .verify-result--bad");
    out.drawerVerify = await page.locator("#verify-result").innerText();
    await page.keyboard.press("Escape");
    out.drawerClosed = await page.locator("#drawer").isHidden();
    // tabs keep the session: Replays, Write your own fix, back to Ask
    await page.click("#tab-replays");
    out.runCards = await page.locator("#runs .run").count();
    await page.click("#tab-write");
    await page.waitForFunction(() => document.querySelector("#editor") && document.querySelector("#editor").value.length > 100);
    out.writeHead = await page.locator("#write-head").innerText();
    out.fillButtons = await page.locator(".editor-card [data-fill]").allInnerTexts();
    await page.click('[data-fill="regression"]');
    await page.waitForFunction(() => document.activeElement === document.querySelector("#editor"));
    await submitOwn(page);
    out.own = await read(page);
    await page.fill("#editor", (await page.inputValue("#editor")) + '\noutput "x" {\n  value = 1\n}\n');
    await submitOwn(page);
    out.ownRefused = await read(page);
    await page.click("#tab-ask");
    out.backToAsk = await read(page);
    out.logLoop = [...log];
    await context.close();
  }
  { // three failures leave the trusted state unchanged; Enter submits from the docked box too
    const { page, context, log } = await open();
    await ready(page);
    const before = seen().length;
    await ask(page, "FAIL ALWAYS");
    out.threeFailures = await read(page);
    out.seenThree = seen().slice(before).map((s) => s.task.includes("Your previous patch was rejected by DAIL"));
    // a reply DAIL's parser refuses is a failed attempt; the retry starts from the same trusted state
    await ask(page, "GARBAGE", { dock: true });
    out.garbage = await read(page);
    out.log3 = [...log];
    await context.close();
  }
  { // the free quota, and Stop
    const { page, context, log } = await open();
    await ready(page);
    await ask(page, "QUOTA");
    out.quota = await read(page);
    await page.fill("#next", "Close the public SSH port");
    await page.press("#next", "Enter");
    await page.waitForSelector("#thread .writing");
    await page.click("#stop");
    await idle(page);
    out.stopped = await read(page);
    out.logQuota = log.filter((l) => !l.includes("429"));
    await context.close();
  }
  { // another system than the canonical one
    const { page, context, log } = await open();
    await ready(page);
    await page.selectOption("#scenario", "tp-v1-F4-0092");
    await page.waitForFunction(() => document.querySelector("#ask").disabled);
    await ready(page);
    out.otherFirst = await read(page);
    await page.click("#tab-write");
    await page.waitForSelector('[data-fill="fixed"]');
    await page.click('[data-fill="fixed"]');
    await page.waitForFunction(() => document.activeElement === document.querySelector("#editor"));
    await submitOwn(page);
    out.otherOwn = await read(page);
    out.otherLog = log;
    await context.close();
  }
  { // every replay, reduced motion, layout and small text
    const { page, context, log } = await open(DESK, { path: "/index.html?tab=replays", reduced: true });
    await page.waitForSelector("#runs .run");
    const runs = await page.evaluate(async () => (await (await fetch("runs/index.json")).json()).runs);
    out.replays = [];
    for (let i = 0; i < runs.length; i += 1) {
      const card = await page.locator("#runs .run").nth(i).innerText();
      await page.locator("#runs .run").nth(i).click();
      await page.waitForSelector("#thread .dail .stamp, #thread .dail .refused-box");
      out.replays.push({ file: runs[i].file, expected: runs[i].decisions, card: card.replace(/\s+/g, " "), shown: await read(page) });
      await page.click("#back-to-runs");
      await page.waitForSelector("#runs .run");
    }
    for (const filter of ["gemini", "reference", "rejected"]) {
      await page.click(`[data-filter="${filter}"]`);
      out[`filter_${filter}`] = await page.locator("#runs .run").count();
    }
    out.pyodideInReplays = await page.evaluate(() => performance.getEntriesByType("resource").some((e) => e.name.includes("pyodide")));
    await page.click('[data-filter="all"]');
    await page.locator("#runs .run").nth(1).click();
    await page.waitForSelector("#thread .dail .stamp");
    out.reducedMotion = await page.evaluate(() => [document.documentElement.classList.contains("reduce-motion"), getComputedStyle(document.querySelector("#thread .stamp")).animationName]);
    await page.click("#thread .dail [aria-controls^='evidence-']");
    out.noHorizontalScroll = {};
    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({ width, height: 844 });
      out.noHorizontalScroll[width] = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
    }
    await page.setViewportSize(DESK);
    // nothing that matters is smaller than 15 px; meta and mono may be 13 (D package §4.3); the stripe label is 11
    out.smallText = await page.evaluate(() => [...document.querySelectorAll("body *")]
      .filter((e) => e.offsetParent !== null && [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()))
      .filter((e) => parseFloat(getComputedStyle(e).fontSize) < 13 && !e.closest(".gemini__stripe"))
      .map((e) => `${e.tagName}.${e.className}`));
    out.replayLog = log;
    await context.close();
  }
  { // presenter mode after the loop at 1366 x 768
    const { page, context } = await open(PRESENTER, { reduced: true });
    await ready(page);
    await ask(page, RISKY);
    // the keyboard reaches the main controls
    out.keyboard = await page.evaluate(() => ["#tab-ask", "#tab-write", "#tab-replays", "#presenter", "#ledger-open", "#next", "#thread .dail button", "#thread .collapsed button"]
      .filter((s) => { const e = document.querySelector(s); if (!e) return true; e.focus(); return document.activeElement !== e; }));
    await page.click("#presenter");
    await page.waitForTimeout(200);
    out.presenter = await page.evaluate(() => {
      const r = (el) => el.getBoundingClientRect();
      const card = [...document.querySelectorAll("#thread .dail")].at(-1);
      return {
        on: document.documentElement.classList.contains("presenter"), font: getComputedStyle(document.body).fontSize,
        vh: innerHeight, header: Math.round(r(document.querySelector("#hdr")).bottom), card: [Math.round(r(card).top), Math.round(r(card).bottom)],
        dock: Math.round(r(document.querySelector("#dock .dock__box")).top),
        code: getComputedStyle(document.querySelector("#thread .code")).display,
      };
    });
    out.targets = await page.evaluate(() => [...document.querySelectorAll("button, a, select, textarea")]
      .filter((e) => e.offsetParent !== null && !e.closest(".site-foot") && !e.classList.contains("visually-hidden"))
      .filter((e) => e.getBoundingClientRect().height < 44).map((e) => `${e.tagName}#${e.id}.${e.className}`));
    await context.close();
  }
  { // the phone
    const { page, context, log } = await open(PHONE, { reduced: true });
    await ready(page);
    out.phoneMenu = await page.evaluate(() => getComputedStyle(document.querySelector("#nav")).display);
    await page.click("#menu");
    out.phoneMenuOpen = await page.evaluate(() => getComputedStyle(document.querySelector("#nav")).display);
    await page.click("#menu");
    await ask(page, RISKY);
    out.phone = await read(page);
    out.phoneScroll = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
    out.phoneCells = await page.evaluate(() => getComputedStyle(document.querySelector("#dail-2 .cell__text")).display);
    out.phoneLog = log;
    await context.close();
  }
  writeFileSync(target, JSON.stringify(out, null, 1));
  console.log(JSON.stringify({ browser: out.browser, loop: out.loop.kinds, status: out.loop.status, replays: out.replays.length }));
}

async function shot(page, name, { at = null, full = false, top = false } = {}) {
  if (top) await page.evaluate(() => window.scrollTo(0, 0));
  if (at) await page.locator(at).first().evaluate((e) => e.scrollIntoView({ block: "start" }));
  await page.waitForTimeout(150);
  await page.screenshot({ path: `${target}/${name}.png`, fullPage: full });
}

async function shots() {
  mkdirSync(target, { recursive: true });
  { // desktop 1440 x 900
    const { page, context } = await open(DESK, { reduced: true });
    await ready(page);
    await page.evaluate(() => document.fonts.ready);
    await shot(page, "1440-01-ask");
    await page.click("#chips .chip--risky");
    await page.click("#ask");
    await page.waitForSelector("#thread .writing");
    await shot(page, "1440-02-gemini-writing");
    await idle(page);
    await shot(page, "1440-04-attempt-2-promote-mini-ledger", { at: "#dail-2" });
    // attempt 1 as DAIL left it, with the retry banner under it ("Open ↓" unfolds the collapsed attempt)
    await page.click("#thread .collapsed button");
    await shot(page, "1440-03-attempt-1-reject-and-retry-banner", { at: "#dail-1" });
    await page.click("#dail-2 [aria-controls='evidence-2']");
    await shot(page, "1440-05-evidence-open", { at: "#evidence-2" });
    await page.click("#ledger-open");
    await page.click("#verify");
    await page.waitForSelector("#verify-result .verify-result--ok");
    await shot(page, "1440-08-ledger-drawer");
    await page.click("#ledger-close");
    await page.click("#tab-write");
    await page.waitForSelector('[data-fill="regression"]');
    await page.click('[data-fill="regression"]');
    await submitOwn(page);
    await shot(page, "1440-06-write-your-own-fix", { top: true });
    await shot(page, "1440-06b-write-your-own-fix-decision", { at: "#thread .dail" });
    await page.click("#tab-replays");
    await shot(page, "1440-07-replays");
    await context.close();
  }
  { // presenter 1366 x 768
    const { page, context } = await open(PRESENTER, { reduced: true });
    await ready(page);
    await ask(page, RISKY);
    await page.click("#presenter");
    await page.waitForTimeout(250);
    await shot(page, "1366-09-presenter");
    await context.close();
  }
  { // phone 390 x 844
    const { page, context } = await open(PHONE, { reduced: true });
    await ready(page);
    await page.evaluate(() => document.fonts.ready);
    await shot(page, "390-01-ask");
    await ask(page, RISKY);
    await shot(page, "390-03-promote", { at: "#dail-2" });
    await page.click("#thread .collapsed button");
    await shot(page, "390-02-reject", { at: "#dail-1" });
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

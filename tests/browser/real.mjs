// One real run on a running `serve` (with GEMINI_API_KEY): asks once and reports every attempt as it came.
//
//   node tests/browser/real.mjs <url> <request text>
//
// Dev-only (D-21). Nothing is retried by this script and no outcome is forced.
import { chromium } from "playwright";

const [url, text] = process.argv.slice(2);
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const answers = [];
  page.on("response", async (r) => {
    if (r.url().endsWith("/api/propose") && r.request().method() === "POST") {
      const body = await r.json().catch(() => null);
      answers.push({ status: r.status(), model: body && body.model, tokens: body && body.tokens, error: body && body.error,
        feedback: JSON.parse(r.request().postData()).feedback || null });
    }
  });
  await page.goto(url);
  await page.waitForFunction(() => !document.querySelector("#ask").disabled, null, { timeout: 180000 });
  await page.fill("#instruction", text);
  await page.click("#ask");
  await page.waitForFunction(() => !document.querySelector("#stop").hidden || !document.querySelector("#thread-notice").hidden);
  await page.waitForFunction(() => document.querySelector("#stop").hidden && !document.querySelector("#thread .writing")
    && [...document.querySelectorAll("#thread .dail")].every((d) => d.querySelector(".dail__foot")), null, { timeout: 600000 });
  // unfold the earlier attempts, then read every Gemini card and DAIL card as shown
  for (const button of await page.locator("#thread .collapsed button").all()) await button.click();
  const shown = await page.evaluate(() => {
    const t = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : null);
    const gemini = [...document.querySelectorAll("#thread .gemini")];
    return [...document.querySelectorAll("#thread .dail")].map((d, i) => ({
      gemini: t(gemini[i] && gemini[i].querySelector(".gemini__title")),
      changes: gemini[i] ? [...gemini[i].querySelectorAll(".changes li")].map(t) : [],
      stamp: d.querySelector(".stamp") ? d.querySelector(".stamp").firstChild.textContent : null,
      sentence: t(d.querySelector(".sentence")), raw: t(d.querySelector(".raw")), compare: t(d.querySelector(".compare")),
    }));
  });
  const end = await page.evaluate(() => ({
    banners: [...document.querySelectorAll("#thread .banner")].map((e) => e.textContent),
    finals: [...document.querySelectorAll("#thread .final")].map((e) => e.textContent),
    trusted: document.querySelector("#status-version").textContent,
    notice: document.querySelector("#thread-notice").hidden ? null : document.querySelector("#thread-notice").textContent,
  }));
  console.log(JSON.stringify({ request: text, answers, shown, ...end }, null, 1));
} finally {
  await browser.close();
}

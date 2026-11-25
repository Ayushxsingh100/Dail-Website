// One real run on a running `serve` (with GEMINI_API_KEY): asks and reports every attempt as it came.
//
//   node tests/browser/real.mjs <url> <request text>
//
// Dev-only (D-21). Nothing is retried by this script and no outcome is forced.
import { chromium } from "playwright";

const [url, text] = process.argv.slice(2);
const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  const answers = [];
  page.on("response", async (r) => {
    if (r.url().endsWith("/api/propose") && r.request().method() === "POST") {
      answers.push({ status: r.status(), body: await r.json().catch(() => null), feedback: JSON.parse(r.request().postData()).feedback || null });
    }
  });
  await page.goto(url);
  await page.waitForFunction(() => !document.querySelector("#ask").disabled, null, { timeout: 180000 });
  await page.fill("#instruction", text);
  await page.click("#ask");
  await page.waitForFunction(() => document.querySelector("#ask").disabled);
  await page.waitForFunction(() => !document.querySelector("#reset").disabled, null, { timeout: 600000 });
  const shown = [];
  const tabs = page.locator("#attempts .tab");
  for (let i = 0; i < await tabs.count(); i += 1) {
    await tabs.nth(i).click();
    shown.push(await page.evaluate(() => ({
      tab: document.querySelector('#attempts [aria-selected="true"]').textContent,
      changes: [...document.querySelectorAll(".changes li")].map((e) => e.textContent),
      stamp: document.querySelector("#stamp") && document.querySelector("#stamp").textContent,
      reason: document.querySelector("#reason") && document.querySelector("#reason").textContent,
      raw: document.querySelector(".reason__raw, .refused__reason") && document.querySelector(".reason__raw, .refused__reason").textContent,
      normal: document.querySelector("#normal") && document.querySelector("#normal").textContent,
    })));
  }
  const end = await page.evaluate(() => ({
    ledger: [...document.querySelectorAll("#ledger .state")].map((e) => e.textContent),
    notice: document.querySelector("#notice").hidden ? null : document.querySelector("#notice").textContent,
  }));
  console.log(JSON.stringify({ request: text, answers, shown, ...end }, null, 1));
} finally {
  await browser.close();
}

// names.js on given cases (JSON on stdin): dev-only test tooling (D-21).
import { readFileSync } from "node:fs";
const n = await import(new URL("../../site/assets/js/names.js", import.meta.url));
const { decisions = [], target = "INV-SEC-001", health = [], changes = [], comparisons = [] } = JSON.parse(readFileSync(0, "utf8"));
console.log(JSON.stringify({
  names: n.NAMES,
  sentences: decisions.map((d) => n.decisionSentence(d, target)),
  raw: decisions.map((d) => n.rawLine(d)),
  failed: decisions.map((d) => n.failedNames(d)),
  health: health.map(([id, status]) => n.healthOf(id, status)),
  changes: changes.map(([address, type]) => n.changeWords(address, type)),
  comparisons: comparisons.map((entry) => n.comparison(entry).slice(0, 3).join("")),
  refused: n.refusedSentence("the patch changes no file"),
}));

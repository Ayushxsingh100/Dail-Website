// names.js on given decisions (JSON on stdin): dev-only test tooling (D-21).
import { readFileSync } from "node:fs";
const names = await import(new URL("../../site/assets/js/names.js", import.meta.url));
const cases = JSON.parse(readFileSync(0, "utf8"));
console.log(JSON.stringify({ names: names.NAMES, plain: cases.map((d) => names.plainReason(d)), failed: cases.map((d) => names.failedNames(d)) }));

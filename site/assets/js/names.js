// Plain language (PLAN §3.9; work package D §3; D-37). Fixed texts, written once, here. They only
// describe what DAIL returned and never decide anything.

export const NAMES = {
  "INV-SEC-001": { holds: "SSH closed to the internet", broken: "SSH open to the internet", wouldBreak: "SSH would be open to the internet", shortHolds: "SSH closed", shortBroken: "SSH open" },
  "INV-SEC-002": { holds: "Database port closed", broken: "Database port open to the internet", wouldBreak: "the database port would be open to the internet", shortHolds: "DB port closed", shortBroken: "DB port open" },
  "INV-SEC-003": { holds: "Database not public", broken: "Database is public", wouldBreak: "the database would become public", shortHolds: "DB not public", shortBroken: "DB public" },
  "INV-FUNC-001": { holds: "App reaches database", broken: "App can't reach database", wouldBreak: "the app would lose its connection to the database", shortHolds: "App reaches DB", shortBroken: "App can't reach DB" },
};
export const ORDER = ["INV-SEC-001", "INV-SEC-002", "INV-SEC-003", "INV-FUNC-001"];

// A status from DAIL's ledger as a pill: { kind: "pass" | "fail" | "unknown", text, short, mark }.
export function healthOf(id, status) {
  const name = NAMES[id];
  if (status === "PROTECTED") return { kind: "pass", text: name.holds, short: name.shortHolds, mark: "✓" };
  if (status === "VIOLATED") return { kind: "fail", text: name.broken, short: name.shortBroken, mark: "✕" };
  return { kind: "unknown", text: `${name.holds}: unknown`, short: `${name.shortHolds}: unknown`, mark: "?" };
}

const VERBS = { CREATED: "Adds", MODIFIED: "Edits", DELETED: "Removes", REPLACED: "Replaces", UNCERTAIN: "Unclear change" };
const NOUNS = { aws_security_group_rule: "the rule", aws_security_group: "the security group", aws_instance: "the app server", aws_db_instance: "the database" };

// One changed resource of DAIL's identity stage: { verb, noun, name }.
export function changeWords(address, changeType) {
  const [type, ...rest] = String(address).split(".");
  return { verb: changeType === null ? "Keeps" : VERBS[changeType] || "Unclear change", noun: NOUNS[type] || type, name: rest.join(".") };
}

export function invariantOf(target) {
  const match = /^INVARIANT:(INV-[A-Z]+-\d+):\d+$/.exec(String(target));
  return match && NAMES[match[1]] ? match[1] : null;
}

// The verification result a blocking condition names ("result <id>: FAIL path.missing").
function resultOf(blocking) {
  const match = /:\s*(PASS|FAIL|UNKNOWN|UNSUPPORTED|VERIFIER_ERROR)\b/.exec(String(blocking.detail || ""));
  if (match) return match[1];
  return blocking.code === "REQUIRED_CHECK_FAILED" ? "FAIL" : "UNKNOWN";
}

function joined(parts) {
  return parts.length < 2 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

function inSentence(text) {
  // "Database port closed" -> "database port closed"; "SSH closed..." keeps its capitals
  return /^[A-Z][a-z]/.test(text) ? text.charAt(0).toLowerCase() + text.slice(1) : text;
}

// The decision sentence, built only from DAIL's decision type and its blocking conditions.
export function decisionSentence(decision, target) {
  if (decision.type === "PROMOTE") {
    return `Promoted: ${NAMES[target] ? NAMES[target].holds : "the repair"}, and everything that held before still holds.`;
  }
  if (decision.type === "ESCALATE") return "DAIL hit an error and stopped. Nothing was changed.";
  const failed = [];
  const unproven = [];
  for (const b of decision.blocking || []) {
    const id = invariantOf(b.target);
    if (!id) continue;
    const list = resultOf(b) === "FAIL" ? failed : unproven;
    if (!list.includes(id)) list.push(id);
  }
  if (failed.length) return `Rejected: ${joined(failed.map((id) => NAMES[id].wouldBreak))}.`;
  if (unproven.length) {
    return `DAIL couldn't prove that ${joined(unproven.map((id) => inSentence(NAMES[id].holds)))}, so it won't promote. DAIL never guesses.`;
  }
  return decision.type === "REJECT" ? "Rejected: one of DAIL's required checks did not pass." : "DAIL did not promote this fix. Nothing was changed.";
}

export function refusedSentence(reason) {
  return `DAIL's patch checker refused this fix: ${reason}.`.replace(/\.\.$/, ".");
}

// DAIL's raw decision line, e.g. "REQUIRED_CHECK_FAILED · INVARIANT:INV-FUNC-001:1 · path.missing".
export function rawLine(decision, carried = []) {
  const parts = [decision.reason];
  for (const b of decision.blocking || []) {
    parts.push(b.target);
    const tail = /:\s*(?:FAIL|UNKNOWN|UNSUPPORTED|VERIFIER_ERROR)\s+(.+)$/.exec(String(b.detail || ""));
    if (tail) parts.push(tail[1]);
  }
  for (const id of carried) parts.push(`${id} carried forward`);
  return parts.join(" · ");
}

// The plain names of the invariants DAIL's blocking conditions name (sent back to Gemini).
export function failedNames(decision) {
  return [...new Set((decision.blocking || []).map((b) => invariantOf(b.target)).filter(Boolean))].map((id) => NAMES[id].holds);
}

// What target-only checking (condition A) decided on the same patch: [before, word, after, kind].
export function comparison(entry) {
  const checks = `(${entry.check_count} checks)`;
  if (entry.decision === "PROMOTE") return ["A normal checker would have ", "accepted", ` this fix ${checks}.`, "pass"];
  if (entry.decision === "REJECT") return ["A normal checker would also have ", "rejected", ` it ${checks}.`, "fail"];
  return ["A normal checker would have ", "reached no decision", ` ${checks}.`, "unknown"];
}

// Plain names of the systems (the scenario select and the replays).
const PROBLEM = { "INV-SEC-001": "SSH open to the internet", "INV-SEC-002": "Database port open to the internet" };
export function scenarioName(scenario) {
  if (!scenario) return "";
  if (scenario.id === "canonical") return "App and database (canonical)";
  return `${PROBLEM[scenario.target] || "A repair"} · ${scenario.family} variant ${scenario.id.slice(-4)}`;
}

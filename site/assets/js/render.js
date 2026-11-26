// The thread of the website (PLAN §3.7 Mint and tomato, §3.9). Every value shown is read from a
// dail-live-trace/1, which holds DAIL's own records; nothing is decided here. Built with textContent only.
import { NAMES, ORDER, changeWords, comparison, decisionSentence, healthOf, rawLine, refusedSentence } from "./names.js";

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key === "hidden") el.hidden = true;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });
export const formatDate = (iso) => { const d = iso ? new Date(iso) : new Date(); return Number.isNaN(d.getTime()) ? "" : DATE.format(d); };
const short = (hash, n = 8) => (hash ? `${hash.slice(0, n)}…` : "");
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// ---- health ---------------------------------------------------------------------------------

function dot(kind) {
  return kind === "unknown" ? h("span", { class: "dot dot--unknown", "aria-hidden": "true", text: "?" }) : h("span", { class: `dot dot--${kind}`, "aria-hidden": "true" });
}

export function healthPills(list, state, { compact = false } = {}) {
  list.replaceChildren(...ORDER.map((id) => {
    const health = healthOf(id, state && state.invariants && state.invariants[id] ? state.invariants[id].status : null);
    const word = health.kind === "pass" ? "holds" : health.kind === "fail" ? "broken" : "unknown";
    return h(compact ? "span" : "li", { class: "pill", title: health.text },
      dot(health.kind), compact ? health.short : health.text, h("span", { class: "visually-hidden", text: ` (${word})` }));
  }));
}

export function healthDots(el, state) {
  el.replaceChildren(...ORDER.map((id) => dot(healthOf(id, state && state.invariants[id] && state.invariants[id].status).kind)),
    h("span", { text: `v${state ? state.version : 0}` }));
}

// ---- the thread's messages -------------------------------------------------------------------

export function you(text) {
  return h("li", {}, h("article", { class: "you", "aria-label": "Your request" },
    h("p", { class: "you__label", text: "You" }), h("p", { class: "you__bubble", text })));
}

function diffBlock(diff) {
  const pre = h("pre", { class: "diff", "aria-label": "The change, line by line" });
  for (const line of String(diff || "").split("\n")) {
    if (!line) continue;
    const cls = /^(\+\+\+|---|@@)/.test(line) ? "hunk" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : null;
    pre.append(h("span", { class: cls, text: line.replace(/^-(?!--)/, "−") }));
  }
  if (!pre.childNodes.length) pre.append(h("span", { text: "No configuration change." }));
  return pre;
}

function changeList(trace) {
  const c = trace.conditions && trace.conditions.C;
  const changed = (c && c.changed_resources) || [];
  const named = (trace.admission && trace.admission.patch_changed_addresses) || [];
  const rows = changed.map((r) => changeWords(r.address, r.change_type));
  for (const address of named) if (!changed.some((r) => r.address === address)) rows.push(changeWords(address, null));
  if (!rows.length) return h("p", { text: trace.refused_before_dail ? "No change DAIL could read." : "No resource changed." });
  return h("ul", { class: "changes" }, ...rows.map((r) => h("li", {}, h("span", { class: "tag", text: r.verb }), " ", r.noun, " ", h("code", { text: r.name }))));
}

// A proposal card: Gemini's (attempt n), a recorded reference patch, or a waiting state.
export function proposalCard({ title, note, trace = null, writing = false, label }) {
  const body = writing
    ? [h("p", { class: "writing" }, "Gemini is writing a fix", h("span", { class: "squares", "aria-hidden": "true" }, h("span"), h("span"), h("span")))]
    : [changeList(trace),
      trace.diff || (trace.ai && trace.ai.reply)
        ? h("details", { class: "code" }, h("summary", { text: "Show the code ↓" }), trace.diff ? diffBlock(trace.diff) : h("pre", { class: "diff" }, h("span", { text: trace.ai.reply })))
        : null];
  return h("li", {}, h("article", { class: "gemini", "aria-label": label },
    h("div", { class: "gemini__stripe" }, h("span", { text: "UNTRUSTED" })),
    writing ? null : h("div", { class: "gemini__head" }, h("p", { class: "gemini__title", text: title }), h("p", { class: "gemini__note", text: note })),
    ...body));
}

export function banner(n) {
  return h("li", {}, h("p", { class: "banner", role: "status" }, h("span", { "aria-hidden": "true", text: "↻" }),
    h("strong", { text: `Attempt ${n} of 3.` }), " DAIL's reason was sent back to Gemini."));
}

export function finalMessage(text) {
  return h("li", {}, h("p", { class: "final", text }));
}

export function collapsed(n, trace, onOpen) {
  const refused = trace.refused_before_dail;
  const type = refused ? "Refused" : trace.conditions.C.decision.type;
  const kind = type === "PROMOTE" ? "pass" : "fail";
  return h("li", {}, h("article", { class: "collapsed", "aria-label": `Attempt ${n}, collapsed` },
    h("span", { class: `outline-pill outline-pill--${kind}`, text: `Attempt ${n} · ${type.charAt(0)}${type.slice(1).toLowerCase()}` }),
    h("span", { class: "collapsed__sentence", text: sentenceOf(trace) }),
    h("button", { type: "button", class: "linkbtn", onclick: onOpen, "aria-label": `Open attempt ${n}` }, "Open ↓")));
}

export function sentenceOf(trace) {
  if (trace.refused_before_dail) return refusedSentence(refusalReason(trace));
  return decisionSentence(trace.conditions.C.decision, trace.scenario.target_invariant_id);
}

function refusalReason(trace) {
  const a = trace.admission || {};
  const g = trace.generation;
  const errors = a.errors && a.errors.length ? a.errors : [g ? g.detail || g.failure_class || "no valid patch" : "no valid patch"];
  return errors.join("; ").replace(/\.$/, "");
}

// ---- the DAIL card ---------------------------------------------------------------------------

const CELLS = [["01", "cell"], ["02", "cell"], ["03", "cell cell--marker"], ["04", "cell"], ["05", "cell cell--decided"]];

function cellTexts(trace) {
  if (!trace) return ["Checking…", "", "", "", ""].map((t) => [t, ""]);
  if (trace.refused_before_dail) return [["Refused", "✕"], ["Not reached", ""], ["Not reached", ""], ["Not reached", ""], ["Not reached", ""]];
  const c = trace.conditions.C;
  const failed = (c.verification || []).filter((v) => String(v.result).toUpperCase() !== "PASS").length;
  return [
    ["Valid patch", "✓"],
    [plural((c.changed_resources || []).length, "resource") + " changed", "✓"],
    [plural(((c.impact || {}).affected || []).length, "rule") + " re-checked", "✓"],
    [failed ? `${plural(failed, "check")} failed` : "All checks passed", failed ? "✕" : "✓"],
    ["Decided", ""],
  ];
}

export function steps(trace, done) {
  const texts = cellTexts(trace);
  return h("ol", { class: "steps", "aria-label": "DAIL's five stages" }, ...CELLS.map(([num, cls], i) => {
    const isDone = trace ? !trace.refused_before_dail || i === 0 : i < done;
    return h("li", { class: `${cls} ${isDone ? "is-done" : "is-waiting"}`, "data-cell": i },
      h("span", { class: "cell__num" }, num, " ", h("span", { class: "cell__mark", text: texts[i][1] })),
      h("span", { class: "cell__text", text: isDone || trace ? texts[i][0] : "Waiting" }));
  }));
}

export function markCell(card, index) {
  const cell = card && card.querySelector(`[data-cell="${index}"]`);
  if (!cell || cell.classList.contains("is-done")) return;
  cell.classList.replace("is-waiting", "is-done");
  cell.classList.add("anim-fill");
  cell.querySelector(".cell__text").textContent = index === 4 ? "Decided" : "Done";
}

function compareLine(trace) {
  const [before, word, after, kind] = comparison(trace.comparison.A);
  return h("p", { class: "compare", id: "compare" }, before, h("span", { class: `outline-pill outline-pill--${kind}`, text: word }), after);
}

export function miniLedger(states, fresh) {
  const oldestFirst = [...states].reverse();
  return h("ol", { class: "mini-ledger", "aria-label": "The ledger" }, ...oldestFirst.flatMap((s, i) => [
    i ? h("li", { class: "joint", "aria-hidden": "true" }) : null,
    h("li", { class: `vpill${s.state_id === fresh ? " is-new anim-slide" : ""}` }, `v${s.version}`, h("code", { text: short(s.state_hash) })),
  ]).filter(Boolean));
}

// The DAIL card of one attempt. trace = null while DAIL is still checking (cells fill from events).
export function dailCard({ n, trace, done = 0, live, states = null, fresh = null, onVerify = null, evidenceOpen = false, onEvidence = null }) {
  const c = trace && trace.conditions && trace.conditions.C;
  const counts = c ? `${plural(c.check_count, "check")} · ${(c.impact.carry_forward_candidates || []).length} carried forward` : "";
  const card = h("article", { class: "dail", "aria-label": `DAIL's decision on attempt ${n}`, id: `dail-${n}` },
    h("div", { class: "dail__head" }, h("p", { class: "dail__title", text: "DAIL · checked in your browser" }), h("p", { class: "dail__counts", text: counts })),
    steps(trace, done));
  if (!trace) return h("li", {}, card);
  if (trace.refused_before_dail) {
    card.append(h("div", { class: "refused-box" }, h("p", { class: "sentence", text: sentenceOf(trace) }),
      h("p", { class: "raw", text: [trace.admission.stage, trace.admission.failure_class].filter(Boolean).join(" · ") })));
  } else {
    const d = c.decision;
    const kind = d.type === "PROMOTE" ? "promote" : d.type === "REJECT" ? "reject" : "other";
    const carried = (c.proof_plan || []).filter((p) => p.source === "CARRIED_FORWARD").map((p) => p.invariant_id);
    card.append(h("div", { class: "verdict" },
      h("p", { class: `stamp stamp--${kind}`, id: `stamp-${n}` }, d.type, h("span", { class: "stamp__by", text: "Decided by DAIL" })),
      h("div", {}, h("p", { class: "sentence", text: sentenceOf(trace) }), h("p", { class: "raw", text: rawLine(d, d.type === "PROMOTE" ? carried : []) }))));
  }
  const foot = h("div", { class: "dail__foot" });
  const evidence = h("div", { class: "evidence", id: `evidence-${n}`, hidden: !evidenceOpen });
  if (evidenceOpen) evidence.append(...evidenceParts(trace));
  const toggle = h("button", { type: "button", class: "linkbtn", "aria-expanded": String(evidenceOpen), "aria-controls": `evidence-${n}` }, evidenceOpen ? "DAIL's evidence ↑ Hide" : "DAIL's evidence ↓");
  toggle.addEventListener("click", () => {
    const open = evidence.hidden;
    evidence.hidden = !open;
    if (open && !evidence.childNodes.length) evidence.append(...evidenceParts(trace));
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "DAIL's evidence ↑ Hide" : "DAIL's evidence ↓";
    if (onEvidence) onEvidence(open);
  });
  const row = h("div", { class: "dail__row" }, trace.refused_before_dail ? h("p", { class: "compare", text: "Nothing reached DAIL's checks, so nothing was compared." }) : compareLine(trace));
  if (!(states && !trace.refused_before_dail && c.decision.type === "PROMOTE")) row.append(toggle);
  foot.append(row);
  if (states && !trace.refused_before_dail && c.decision.type === "PROMOTE") {
    const result = h("div", { role: "status", class: "verify-slot" });
    foot.append(miniLedger(states, fresh), h("div", { class: "dail__row" },
      live ? h("p", { class: "browser-note", text: "Terraform validation is not run in the browser." }) : h("span"),
      h("div", { class: "links" },
        onVerify ? h("button", { type: "button", class: "linkbtn", onclick: () => onVerify(result) }, "Verify chain") : null, toggle)), result);
  } else if (live) {
    foot.append(h("p", { class: "browser-note", text: "Terraform validation is not run in the browser." }));
  }
  card.append(foot, evidence);
  return h("li", {}, card);
}

export function verifyText(answer) {
  if (!answer.ok) return h("p", { class: "verify-result verify-result--bad", text: `The chain check could not run: ${answer.error}` });
  const v = answer.value;
  return h("div", { class: `verify-result verify-result--${v.ok ? "ok" : "bad"}` },
    h("p", { text: v.ok ? `✓ Verified by DAIL: ${plural(v.states, "state")}, ${plural(v.candidates, "candidate")}, no problem.` : "✕ DAIL found problems in the chain:" }),
    ...(v.problems || []).map((p) => h("p", { class: "mono", text: p })));
}

// ---- DAIL's evidence -------------------------------------------------------------------------

function resultTag(result) {
  const value = String(result || "").toUpperCase();
  if (value === "PASS") return h("span", { class: "tag tag--pass", text: "✓ PASS" });
  if (value === "FAIL") return h("span", { class: "tag tag--fail", text: "✕ FAIL" });
  return h("span", { class: "tag", text: `? ${value || "UNKNOWN"}` });
}

const plainRef = (ref) => String(ref).replace(/\baws_/g, "");

function evidenceParts(trace) {
  const c = trace.conditions && trace.conditions.C;
  const parts = [];
  if (c) {
    const target = trace.scenario.target_invariant_id;
    parts.push(h("section", {}, h("h3", { text: "What changed" }), h("ul", { class: "rows" }, ...(c.changed_resources || []).map((r) => {
      const w = changeWords(r.address, r.change_type);
      return h("li", {}, h("span", { class: "tag", text: w.verb }), ` ${w.noun} `, h("span", { class: "mono", text: [r.address, r.change_type, ...(r.flags || [])].join(" · ") }));
    }))));
    const impact = c.impact || {};
    const unaffected = new Map((impact.unaffected || []).map((u) => [u.invariant_id, u.reason]));
    parts.push(h("section", {}, h("h3", { text: "What it affects" }), h("ul", { class: "rows rows--affects" },
      ...(impact.affected || []).map((a) => h("li", {}, h("span", { class: "tag tag--marker", text: "re-checked" }),
        h("span", {}, h("span", { class: "affects__name", text: NAMES[a.invariant_id] ? NAMES[a.invariant_id].holds : a.invariant_id }), " ",
          h("span", { class: "mono", text: [a.invariant_id, ...a.impact_types.map((t) => t.toLowerCase()), a.invariant_id === target ? "the repair target" : null].filter(Boolean).join(" · ") }),
          ...a.dependency_paths.map((p) => h("span", { class: "affects__path", text: [plainRef(p.changed_ref), ...p.steps.map((s) => plainRef(s.to_node))].join(" → ") }))))),
      ...(impact.carry_forward_candidates || []).map((x) => h("li", {}, h("span", { class: "tag tag--carry", text: "carried forward" }),
        h("span", {}, h("span", { class: "affects__name", text: NAMES[x.invariant_id] ? NAMES[x.invariant_id].holds : x.invariant_id }), " ",
          h("span", { class: "mono", text: [x.invariant_id, unaffected.get(x.invariant_id)].filter(Boolean).join(" · ") })))),
      ...(impact.uncertainty || []).map((u) => h("li", {}, h("span", { class: "tag", text: "? uncertain" }), h("span", { class: "mono", text: `${u.invariant_id} · ${u.code} · ${u.detail}` }))))));
    parts.push(h("section", {}, h("h3", { text: "Every check" }), h("ul", { class: "rows" }, ...(c.verification || []).map((v) =>
      h("li", {}, resultTag(v.result), h("span", { class: "mono", text: v.target }), h("span", { class: "mono", text: [v.verifier, v.reason].filter(Boolean).join(" · ") }))))));
  }
  const t = c && c.dail && c.dail.transition;
  const record = h("section", { class: "record" }, h("h3", { text: "Decision record" }));
  if (c) {
    record.append(h("p", { text: `${c.decision.type} · ${c.decision.reason}${(c.decision.blocking || []).map((b) => ` · blocking ${b.target}`).join("")}` }));
    if (t) record.append(h("p", { text: `parent state v${c.baseline.version} ${t.parent_state_hash} · candidate ${t.candidate_id}` }));
    if (c.new_state) record.append(h("p", { text: `new state v${c.new_state.version} ${c.new_state.state_hash}` }));
    const a = trace.comparison.A;
    record.append(h("p", { text: `target-only (condition A): ${a.decision} · ${a.reason} · ${plural(a.check_count, "check")}` }));
  }
  const ad = trace.admission || {};
  record.append(h("p", { text: `admission: ${[ad.stage, ad.admitted ? "admitted" : "refused", ...(ad.errors || [])].filter(Boolean).join(" · ")}` }));
  if (trace.browser) record.append(h("p", { text: trace.browser.terraform_validation }));
  const tf = ad.terraform_validate_run && typeof ad.terraform_validate_run === "object" ? ad.terraform_validate_run : null;
  if (tf) record.append(h("p", { text: `terraform validate: ${tf.ok ? "PASS" : "FAIL"} · ${Object.values(tf.versions || {}).join(", ")}` }));
  record.append(h("p", { text: `${trace.scenario.scenario_id} · ${trace.run_id} · ${trace.versions.dail_tag} ${short(trace.versions.dail_commit, 12)}` }));
  parts.push(record);
  if (trace.ai) {
    const { reply, model, attempt, instruction, tokens, feedback } = trace.ai;
    parts.push(h("section", { class: "record" }, h("h3", { text: "The AI (untrusted)" }),
      h("p", { text: `${model} · attempt ${attempt} · tokens ${JSON.stringify(tokens || {})}` }),
      instruction ? h("p", { text: `request: ${instruction}` }) : null,
      feedback ? h("p", { text: `sent back to Gemini: ${JSON.stringify(feedback)}` }) : null,
      h("p", { class: "reply-text", text: reply })));
  }
  for (const row of (trace.generation || {}).attempts || []) {
    parts.push(h("section", { class: "record" }, h("h3", { text: `Gemini attempt ${row.attempt} (recorded): ${row.failure_class || "valid patch"}` }),
      h("p", { text: `DAIL's parser: ${row.parse_errors.join("; ") || row.parsed_status || "no reply"}` }),
      h("p", { text: `DAIL's patch validator: ${row.validation_errors.join("; ") || (row.failure_class ? "not reached" : "valid")}` }),
      row.response && row.response.raw_response ? h("p", { class: "reply-text", text: row.response.raw_response }) : null));
  }
  return parts;
}

// ---- the ledger drawer -----------------------------------------------------------------------

export function ledgerFromTrace(trace) {
  if (trace.session && trace.session.ledger) return trace.session.ledger;
  const c = trace.conditions && trace.conditions.C;
  if (!c || !c.baseline || !c.baseline.state_id) return [];
  const base = { ...c.baseline, parent_state_id: null };
  return c.new_state ? [{ ...c.new_state, parent_state_id: base.state_id }, base] : [base];
}

export function drawerStates(list, states, { target, carried = {}, attempts = {}, fresh = null }) {
  const byId = new Map(states.map((s) => [s.state_id, s]));
  list.replaceChildren(...states.flatMap((s) => {
    const parent = byId.get(s.parent_state_id);
    const card = h("li", { class: `state${s.state_id === fresh ? " is-new" : ""}` },
      h("div", { class: "state__head" }, h("span", { class: "state__v", text: `v${s.version}` }),
        h("span", { class: "state__by", text: s.version === 0 ? "baseline, established by DAIL" : `promoted by DAIL${attempts[s.state_id] ? ` · attempt ${attempts[s.state_id]}` : ""}` })),
      h("ul", {}, ...ORDER.map((id) => {
        const status = s.invariants && s.invariants[id] && s.invariants[id].status;
        const health = healthOf(id, status);
        const isCarried = (carried[s.state_id] || []).includes(id);
        return h("li", {}, isCarried ? dot("carry") : dot(health.kind), health.text,
          isCarried ? " · carried forward" : "", status === "VIOLATED" && id === target ? " · the repair target" : "",
          h("span", { class: "visually-hidden", text: ` (${health.kind === "pass" ? "holds" : health.kind === "fail" ? "broken" : "unknown"})` }));
      })),
      h("p", { class: "state__hash", text: `state ${s.state_hash}` }));
    return s.parent_state_id ? [card, h("li", { class: "state-link", text: `parent ${parent ? parent.state_hash : s.parent_state_id}` })] : [card];
  }));
}

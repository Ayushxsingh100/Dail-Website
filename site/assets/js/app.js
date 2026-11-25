// DAIL Live: the page controller (PLAN §3.9; design §3.7 Mint and tomato). Three tabs, one thread each:
//   Ask the AI:         Gemini proposes (through /api/propose), DAIL judges in this tab, Gemini retries (3 attempts);
//   Write your own fix: the visitor's edit goes to the same DAIL, no retry loop;
//   Replays:            recorded traces from runs/, rendered as the same thread, no Pyodide needed.
// Every decision shown comes from DAIL; this file only moves DAIL's answers onto the page.
import { bundleInfo, loadDail } from "./dail-bridge.js";
import { failedNames, scenarioName } from "./names.js";
import {
  banner, collapsed, dailCard, drawerStates, finalMessage, formatDate, h, healthDots, healthPills, ledgerFromTrace,
  markCell, proposalCard, sentenceOf, verifyText, you,
} from "./render.js";

const $ = (id) => document.getElementById(id);
const root = document.documentElement;
const reduced = () => root.classList.contains("reduce-motion");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const MAX_ATTEMPTS = 3;
const PROPOSE = "/api/propose";
const CHIPS = [
  { text: "Close the public SSH port" },
  { text: "Make the database private" },
  { text: "Close SSH and tidy up the database rules", risky: true },
];
const FILL = { safe: "Fill: the safe repair", regression: "Fill: the repair that breaks the database path", fixed: "Fill: the recorded repair" };
const ALL_FAILED = "None of the 3 fixes passed DAIL. The infrastructure was not changed.";

const state = {
  tab: "ask", runs: [], scenarios: [], ai: null, dail: null, loading: null, busy: false, startFailed: null,
  filter: "all", replay: null, stop: null,
  live: { scenario: "canonical", started: false, trusted: {}, files: {}, current: null, ledger: [], carried: {}, attempts: {}, fresh: null },
  threads: { ask: [], write: [], replay: [] },
};

// ---- small helpers ------------------------------------------------------------------------------

const version = () => (state.live.ledger[0] ? state.live.ledger[0].version : 0);
const target = () => (state.scenarios.find((s) => s.id === state.live.scenario) || {}).target || "INV-SEC-001";
const announce = (text) => { $("announce").textContent = ""; setTimeout(() => { $("announce").textContent = text; }, 30); };

function notice(id, text) {
  $(id).hidden = !text;
  $(id).textContent = text || "";
}

function append(owner, ...nodes) {
  state.threads[owner].push(...nodes);
  if (showing(owner)) $("thread").append(...nodes);
  return nodes[0];
}

function replaceNode(owner, old, fresh) {
  const list = state.threads[owner];
  const i = list.indexOf(old);
  if (i >= 0) list[i] = fresh;
  if (old.isConnected) old.replaceWith(fresh);
  return fresh;
}

const showing = (owner) => (owner === "replay" ? state.tab === "replays" && state.replay : state.tab === owner);

function scrollTo(node) {
  if (node && node.isConnected) node.scrollIntoView({ block: "start", behavior: reduced() ? "auto" : "smooth" });
}

// ---- loading DAIL -------------------------------------------------------------------------------

const megabytes = (bytes) => (bytes / 1e6).toFixed(1);

function ensureDail() {
  if (state.dail) return Promise.resolve(state.dail);
  if (state.loading) return state.loading;
  state.loading = (async () => {
    const { bytes } = await bundleInfo("vendor");
    $("loading-title").textContent = `Loading DAIL into your browser (~${megabytes(bytes)} MB)`;
    state.dail = await loadDail({
      vendor: "vendor", onEvent: stageEvent,
      onProgress: ({ done, total }) => {
        $("meter").style.width = `${Math.min(100, Math.round((100 * done) / total))}%`;
        $("loading-title").textContent = `Loading DAIL into your browser: ${megabytes(done)} of ${megabytes(total)} MB`;
      },
    });
    return state.dail;
  })().catch((error) => {
    state.loading = null;
    throw error;
  });
  return state.loading;
}

// The DAIL card waiting for DAIL's events: each event DAIL commits fills one cell, 150 ms apart.
const STAGE_OF = { ADMITTED: 0, IDENTITY_COMPLETED: 1, IMPACT_COMPLETED: 2, VERIFICATION_COMPLETED: 3, PROMOTION_DECIDED: 4 };
let pending = null;

function stageEvent(name) {
  if (!pending || !(name in STAGE_OF)) return;
  const card = pending.card;
  pending.chain = pending.chain.then(() => { markCell(card, STAGE_OF[name]); return sleep(reduced() ? 0 : 150); });
}

// ---- the tab's session ----------------------------------------------------------------------------

async function startSession(scenario) {
  setBusy(true);
  try {
    const dail = await ensureDail();
    const answer = await dail.call("start", scenario);
    if (!answer.ok) throw new Error(answer.error);
    Object.assign(state.live, {
      scenario, started: true, trusted: answer.value.files, files: { ...answer.value.files }, current: null,
      ledger: answer.value.ledger, carried: {}, attempts: {}, fresh: null,
    });
    state.threads.ask = [];
    state.threads.write = [];
    editorCard = null;
    state.startFailed = null;
    announce("DAIL is ready. The trusted system is at version 0.");
  } catch (error) {
    state.startFailed = error.message;
  } finally {
    setBusy(false);
    render();
  }
}

function setBusy(on) {
  state.busy = on;
  updateControls();
}

function updateControls() {
  const ready = state.live.started && !state.busy;
  const running = Boolean(state.stop);
  $("ask").disabled = !ready || state.ai !== "available";
  $("dock-ask").disabled = !ready || state.ai !== "available" || running;
  $("next").disabled = running;
  $("stop").hidden = !running;
  $("scenario").disabled = !ready;
  $("verify").disabled = !state.live.started;
  for (const el of document.querySelectorAll("#chips .chip, .editor-card button, .editor")) el.disabled = state.busy;
  $("loading").hidden = state.live.started || Boolean(state.startFailed);
  $("next").placeholder = `Ask for another fix. It starts from trusted state v${version()}.`;
}

// After a decision: what the session now trusts (package C's session logic, in the worker).
function takeTrace(trace, attempt) {
  const session = trace.session || {};
  state.live.ledger = trace.ledger || state.live.ledger;
  if (!session.promoted) return null;
  const fresh = session.trusted_state.state_id;
  state.live.trusted = trace.files;
  state.live.files = { ...trace.files };
  state.live.current = null;
  state.live.fresh = fresh;
  state.live.carried[fresh] = (trace.conditions.C.proof_plan || []).filter((p) => p.source === "CARRIED_FORWARD").map((p) => p.invariant_id);
  if (attempt) state.live.attempts[fresh] = attempt;
  return fresh;
}

async function verifyInto(slot) {
  slot.replaceChildren(h("p", { class: "verify-result", text: "DAIL is checking the chain…" }));
  const answer = await state.dail.call("verify_chain");
  slot.replaceChildren(verifyText(answer));
}

// ---- one attempt: the waiting DAIL card, then DAIL's decision --------------------------------------

async function judge(owner, n, call) {
  const waiting = append(owner, dailCard({ n, trace: null, live: true }));
  pending = { card: waiting.querySelector(".dail"), chain: Promise.resolve() };
  if (showing(owner)) waiting.scrollIntoView({ block: "nearest" });
  let answer;
  try {
    answer = await call();
  } finally {
    const chain = pending.chain;
    pending = null;
    await chain;
  }
  if (!answer.ok) {
    throw new Error(`The check stopped with an error; this is not a DAIL decision. ${answer.error}`);
  }
  const trace = answer.value;
  const fresh = takeTrace(trace, owner === "ask" ? n : null);
  const card = dailCard({
    n, trace, live: true, states: fresh ? state.live.ledger : null, fresh,
    onVerify: (slot) => verifyInto(slot),
  });
  replaceNode(owner, waiting, card);
  land(card);
  render({ keepThread: true });
  if (showing(owner)) card.scrollIntoView({ block: "start", behavior: reduced() ? "auto" : "smooth" });
  return { trace, card, fresh };
}

function land(card) {
  if (reduced()) return;
  const stamp = card.querySelector(".stamp");
  if (stamp) stamp.classList.add("anim-land");
}

function decisionWords(trace) {
  if (trace.refused_before_dail) return `DAIL: refused. ${sentenceOf(trace)}`;
  const type = trace.conditions.C.decision.type;
  return `DAIL: ${type === "PROMOTE" ? "promoted" : type === "REJECT" ? "rejected" : type.toLowerCase()}. ${sentenceOf(trace)}`;
}

// ---- Ask the AI -------------------------------------------------------------------------------------

async function propose(body, signal) {
  const headers = { "Content-Type": "application/json" };
  if ($("passcode").value) headers["X-Demo-Passcode"] = $("passcode").value;
  let response;
  try {
    response = await fetch(PROPOSE, { method: "POST", headers, body: JSON.stringify(body), signal });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new Error("The AI cannot be reached. Check the connection, or write your own fix.");
  }
  const data = await response.json().catch(() => null);
  if (response.status === 401) $("passcode-field").hidden = false;
  if (!response.ok || !data || typeof data.reply !== "string") {
    throw new Error((data && data.error && data.error.message) || "The AI is not available here. Write your own fix, or watch the replays.");
  }
  return data;
}

function feedbackFrom(trace) {
  const cut = (text, n) => Array.from(String(text)).slice(0, n).join("");
  if (trace.refused_before_dail) {
    const a = trace.admission || {};
    const reason = (a.errors && a.errors.length ? a.errors : [(trace.generation && trace.generation.detail) || "no valid patch"]).join("; ");
    return { decision: "REFUSED", reason: cut(reason, 400), blocking: [], failed: [] };
  }
  const d = trace.conditions.C.decision;
  return { decision: d.type, reason: d.reason, blocking: (d.blocking || []).slice(0, 8).map((b) => cut(b.target, 80)), failed: failedNames(d) };
}

function geminiTitle(n) {
  return { title: `Gemini · attempt ${n}`, note: "a proposal, untrusted until DAIL says so", label: `Gemini, attempt ${n}` };
}

async function ask(instruction) {
  instruction = instruction.trim();
  if (!instruction) return;
  notice("thread-notice", "");
  state.tab = "ask";
  const stop = new AbortController();
  state.stop = stop;
  setBusy(true);
  render({ keepThread: false });
  scrollTo(append("ask", you(instruction)));
  let feedback = null;
  let previous = null;
  try {
    for (let n = 1; n <= MAX_ATTEMPTS; n += 1) {
      if (n > 1) {
        collapse(previous);
        announce(`Attempt ${n} of ${MAX_ATTEMPTS}`);
      }
      const writing = append("ask", proposalCard({ ...geminiTitle(n), writing: true }));
      if (showing("ask")) writing.scrollIntoView({ block: "nearest" });
      const body = { scenario_id: state.live.scenario, files: state.live.trusted, attempt: n, instruction };
      if (feedback) body.feedback = feedback;
      const data = await propose(body, stop.signal);
      announce("Gemini proposed a fix");
      const meta = { model: data.model, tokens: data.tokens, attempt: n, instruction, feedback };
      const { trace, card, fresh } = await judge("ask", n, () => state.dail.call("submit_reply", data.reply, JSON.stringify(meta)));
      const gemini = replaceNode("ask", writing, proposalCard({ ...geminiTitle(n), trace }));
      previous = { n, trace, nodes: [gemini, card] };
      announce(decisionWords(trace));
      if (fresh) break;
      if (n === MAX_ATTEMPTS) { append("ask", finalMessage(ALL_FAILED)); break; }
      feedback = feedbackFrom(trace);
      append("ask", banner(n + 1)); // shown under the rejection; the attempt folds when the next one starts
      await sleep(1600); // time to read the rejection (reading time, not motion: the same with reduced motion)
      if (stop.signal.aborted) throw new DOMException("stopped", "AbortError");
    }
  } catch (error) {
    dropWaiting("ask");
    if (error.name === "AbortError") append("ask", finalMessage(`Stopped. The trusted state is still v${version()}.`));
    else notice("thread-notice", error.message);
  } finally {
    state.stop = null;
    setBusy(false);
    render({ keepThread: true });
  }
}

// An attempt that is over folds into one row when the next one starts; "Open ↓" unfolds it again.
function collapse(attempt) {
  if (!attempt) return;
  const [gemini, card] = attempt.nodes;
  const row = collapsed(attempt.n, attempt.trace, () => {
    replaceNode("ask", row, gemini);
    const list = state.threads.ask;
    list.splice(list.indexOf(gemini) + 1, 0, card);
    if (gemini.isConnected) gemini.after(card);
  });
  replaceNode("ask", gemini, row);
  const list = state.threads.ask;
  list.splice(list.indexOf(card), 1);
  card.remove();
}

function dropWaiting(owner) {
  const list = state.threads[owner];
  for (const node of [...list]) {
    if (node.querySelector(".writing") || (node.querySelector(".dail") && !node.querySelector(".dail__foot"))) {
      list.splice(list.indexOf(node), 1);
      node.remove();
    }
  }
}

// ---- Write your own fix ------------------------------------------------------------------------------

let editorCard = null;

function saveEditor() {
  const editor = editorCard && editorCard.querySelector(".editor");
  if (editor && state.live.current) state.live.files[state.live.current] = editor.value;
}

function buildEditor() {
  const names = Object.keys(state.live.files);
  if (!names.includes(state.live.current)) state.live.current = names.includes("main.tf") ? "main.tf" : names[0] || null;
  const scenario = state.scenarios.find((s) => s.id === state.live.scenario) || {};
  const editor = h("textarea", { class: "editor", id: "editor", spellcheck: "false", "aria-label": `Edit ${state.live.current || "the configuration"}` });
  editor.value = state.live.files[state.live.current] || "";
  editor.addEventListener("input", saveEditor);
  const files = h("div", { class: "files", role: "group", "aria-label": "Files" }, ...names.map((name) =>
    h("button", { type: "button", class: "file-pill", "aria-pressed": String(name === state.live.current), onclick: () => { saveEditor(); state.live.current = name; refreshEditor(); } }, name)));
  const fills = h("div", { class: "fills", role: "group", "aria-label": "Quick fill" }, ...(scenario.quick_fill || []).map((name) =>
    h("button", {
      type: "button", class: "sbtn", "data-fill": name,
      onclick: async () => {
        const answer = await state.dail.call("patch_files", name);
        if (!answer.ok) return;
        state.live.files = answer.value;
        refreshEditor();
        editorCard.querySelector(".editor").focus();
      },
    }, FILL[name] || name)));
  const card = h("article", { class: "editor-card", "aria-label": "Your fix" },
    h("div", { class: "editor-card__bar" }, files, fills), editor,
    h("div", { class: "editor-card__foot" },
      h("p", { text: `Starts from trusted state v${version()}. DAIL checks it in your browser.` }),
      h("button", { type: "button", class: "btn btn--primary", id: "submit", onclick: submitOwn }, "Submit to DAIL →")));
  return h("li", {}, card);
}

function refreshEditor() {
  const fresh = buildEditor();
  if (editorCard) replaceNode("write", editorCard, fresh);
  editorCard = fresh;
  updateControls();
}

async function submitOwn() {
  if (state.busy || !state.live.started) return;
  saveEditor();
  notice("thread-notice", "");
  const n = state.threads.write.filter((node) => node.querySelector(".dail")).length + 1;
  setBusy(true);
  announce("DAIL is checking your fix.");
  try {
    const { trace } = await judge("write", n, () => state.dail.call("submit_files", JSON.stringify(state.live.files)));
    announce(decisionWords(trace));
    refreshEditor();
  } catch (error) {
    dropWaiting("write");
    notice("thread-notice", error.message);
  } finally {
    setBusy(false);
  }
}

// ---- Replays -----------------------------------------------------------------------------------------

function sourceOf(run) {
  if (run.source === "LLM") return `Gemini, recorded ${formatDate(run.recorded_at)}`;
  if (run.source === "TYPED") return "Typed";
  return "Reference patch";
}

function outcomeOf(run) {
  if (run.refused_before_dail) return ["Refused", "fail"];
  return [run.decisions.C, run.decisions.C === "PROMOTE" ? "pass" : "fail"];
}

const FILTERS = {
  all: () => true,
  gemini: (r) => r.source === "LLM",
  reference: (r) => r.source !== "LLM" && r.source !== "TYPED",
  rejected: (r) => r.refused_before_dail || r.decisions.C !== "PROMOTE",
};

function renderRuns() {
  const runs = state.runs.filter(FILTERS[state.filter]);
  for (const b of document.querySelectorAll("[data-filter]")) b.setAttribute("aria-pressed", String(b.dataset.filter === state.filter));
  $("runs").replaceChildren(...runs.map((run) => {
    const scenario = state.scenarios.find((s) => s.id === run.scenario_id) || { id: run.scenario_id, family: run.family };
    const [word, kind] = outcomeOf(run);
    const step = /session-step-(\d+)/.exec(run.file);
    return h("li", {}, h("button", { type: "button", class: "run", onclick: () => openReplay(run.file) },
      h("span", { class: "run__source", text: sourceOf(run) }),
      h("span", { class: "run__title", text: scenarioName(scenario) + (step ? ` · step ${step[1]}` : "") }),
      h("span", { class: `outline-pill outline-pill--${kind}`, text: word }),
      h("span", { class: "run__meta", text: run.refused_before_dail ? "turned away before DAIL's checks" : `DAIL: ${run.check_counts.C} checks · normal checker: ${run.decisions.A}` }),
      h("span", { class: "run__open", text: "Open" })));
  }));
  $("runs-count").textContent = `${runs.length} of ${state.runs.length} recorded runs. Demo, not part of the DAIL evaluation.`;
}

const modelName = (gen) => {
  const model = gen && gen.model;
  return String((model && (model.name || model)) || "Gemini").replace(/^models\//, "");
};

async function openReplay(file) {
  const response = await fetch(`runs/${file}`);
  if (!response.ok) return notice("thread-notice", `The recorded run could not be loaded (HTTP ${response.status}).`);
  const trace = await response.json();
  state.replay = file;
  const c = trace.conditions && trace.conditions.C;
  const states = ledgerFromTrace(trace);
  const gen = trace.generation;
  const source = trace.candidate_source === "LLM"
    ? { title: `Gemini · ${modelName(gen)} · recorded`, note: "a proposal, untrusted until DAIL says so", label: "Gemini, recorded" }
    : { title: trace.candidate_source === "TYPED" ? "A typed fix" : "Reference patch", note: "untrusted until DAIL says so", label: "The recorded patch" };
  const recordedAt = formatDate(trace.created_at);
  state.threads.replay = [
    h("li", {}, h("p", { class: "recorded", text: `Recorded run · ${recordedAt} · ${trace.scenario.scenario_id} · with the full Terraform check` })),
    trace.ai && trace.ai.instruction ? you(trace.ai.instruction) : null,
    proposalCard({ ...source, trace }),
    dailCard({ n: 1, trace, live: false, states: c && c.new_state ? states : null, fresh: c && c.new_state ? c.new_state.state_id : null }),
  ].filter(Boolean);
  render();
  const card = state.threads.replay.at(-1);
  land(card);
  announce(decisionWords(trace));
  window.scrollTo({ top: 0 });
  return undefined;
}

// ---- the ledger drawer --------------------------------------------------------------------------------

function openDrawer(open) {
  $("drawer").hidden = !open;
  $("ledger-open").setAttribute("aria-expanded", String(open));
  if (open) {
    renderDrawer();
    $("ledger-close").focus();
  } else {
    $("ledger-open").focus();
  }
}

function renderDrawer() {
  drawerStates($("states"), state.live.ledger, { target: target(), carried: state.live.carried, attempts: state.live.attempts, fresh: state.live.fresh });
}

// ---- the page as a whole -------------------------------------------------------------------------------

function render({ keepThread = false } = {}) {
  const tab = state.tab;
  for (const name of ["ask", "write", "replays"]) $(`tab-${name}`).setAttribute("aria-selected", String(tab === name));
  const owner = tab === "replays" ? (state.replay ? "replay" : null) : tab;
  const thread = owner && (owner !== "ask" || state.threads.ask.length > 0);
  $("ask-screen").hidden = tab !== "ask" || state.threads.ask.length > 0;
  $("thread-screen").hidden = !thread;
  $("replays-screen").hidden = tab !== "replays" || Boolean(state.replay);
  $("write-head").hidden = tab !== "write";
  $("replay-back").hidden = owner !== "replay";
  $("dock").hidden = !(tab === "ask" && state.threads.ask.length > 0);
  $("hdr").classList.toggle("is-thread", Boolean(thread));
  document.body.classList.toggle("has-dock", !$("dock").hidden);

  const current = state.live.ledger[0] || null;
  healthPills($("health"), current);
  $("status").hidden = !thread || owner === "replay";
  healthPills($("status-pills"), current, { compact: true });
  healthDots($("status-dots"), current);
  $("status-version").textContent = `Trusted state v${version()}`;
  if (!$("drawer").hidden) renderDrawer();

  if (tab === "write" && state.live.started && !editorCard) {
    editorCard = buildEditor();
    state.threads.write.unshift(editorCard);
  }
  if (owner && !(keepThread && $("thread").childNodes.length && showing(owner))) $("thread").replaceChildren(...state.threads[owner]);
  if (tab === "replays" && !state.replay) renderRuns();
  if (state.startFailed && tab !== "replays") notice("ask-notice", `DAIL could not start here: ${state.startFailed}. The replays still work.`);
  else if (state.ai === "unavailable" && tab === "ask") notice("ask-notice", "The AI is not set up on this site. Write your own fix, or watch the replays.");
  else notice("ask-notice", "");
  updateControls();
}

function setTab(tab) {
  if (state.tab === "write") saveEditor();
  if (tab === "replays" && state.tab === "replays") state.replay = null;
  state.tab = tab;
  notice("thread-notice", "");
  $("nav").classList.remove("is-open");
  $("menu").setAttribute("aria-expanded", "false");
  render();
  window.scrollTo({ top: 0 });
  // DAIL loads when a tab needs it: Replays alone never downloads it (about 17 MB)
  if (tab !== "replays" && !state.live.started && !state.starting) {
    state.starting = true;
    startSession(state.live.scenario).finally(() => { state.starting = false; });
  }
}

// The prompt boxes: Enter submits, Shift+Enter adds a line; the box grows from 2 (or 1) to 6 rows.
function promptBox(textarea, submit, minRows) {
  const grow = () => {
    textarea.rows = minRows;
    const line = parseFloat(getComputedStyle(textarea).lineHeight) || 24;
    const pad = textarea.scrollHeight - textarea.clientHeight;
    textarea.rows = Math.max(minRows, Math.min(6, Math.round((textarea.scrollHeight - Math.max(0, pad)) / line)));
  };
  textarea.addEventListener("input", grow);
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      submit();
    }
  });
  return grow;
}

async function init() {
  const get = (url, empty) => fetch(url).then((r) => (r.ok ? r.json() : empty)).catch(() => empty);
  const [runs, scenarios, ai] = await Promise.all([
    get("runs/index.json", { runs: [] }), get("vendor/scenarios/index.json", { scenarios: [] }), get(PROPOSE, null)]);
  state.runs = runs.runs || [];
  state.scenarios = scenarios.scenarios || [];
  state.ai = ai && ai.available ? "available" : "unavailable";
  $("passcode-field").hidden = !(ai && ai.passcode_required);
  $("model-meta").textContent = `${(ai && ai.model) || "Gemini"} · judged by DAIL v1.0`;
  $("scenario").replaceChildren(...state.scenarios.map((s) => h("option", { value: s.id }, scenarioName(s))));
  $("chips").replaceChildren(...CHIPS.map(({ text, risky }) => h("button", {
    type: "button", class: `chip${risky ? " chip--risky" : ""}`,
    onclick: () => { $("instruction").value = text; growAsk(); $("instruction").focus(); },
  }, risky ? `${text} · risky` : text)));

  const askNow = () => { if (!$("ask").disabled && $("instruction").value.trim()) ask($("instruction").value); };
  const askNext = () => {
    if ($("dock-ask").disabled || !$("next").value.trim()) return;
    const text = $("next").value;
    $("next").value = "";
    growNext();
    ask(text);
  };
  const growAsk = promptBox($("instruction"), askNow, 2);
  const growNext = promptBox($("next"), askNext, 1);
  $("ask-form").addEventListener("submit", (event) => { event.preventDefault(); askNow(); });
  $("dock-form").addEventListener("submit", (event) => { event.preventDefault(); askNext(); });
  $("stop").addEventListener("click", () => { if (state.stop) state.stop.abort(); });

  for (const name of ["ask", "write", "replays"]) $(`tab-${name}`).addEventListener("click", () => setTab(name));
  for (const b of document.querySelectorAll("[data-filter]")) b.addEventListener("click", () => { state.filter = b.dataset.filter; renderRuns(); });
  $("back-to-runs").addEventListener("click", () => { state.replay = null; render(); });
  $("scenario").addEventListener("change", (event) => { editorCard = null; startSession(event.target.value); });
  $("verify").addEventListener("click", () => verifyInto($("verify-result")));
  $("ledger-open").addEventListener("click", () => openDrawer($("drawer").hidden));
  $("ledger-close").addEventListener("click", () => openDrawer(false));
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !$("drawer").hidden) openDrawer(false); });
  $("menu").addEventListener("click", () => {
    const open = $("nav").classList.toggle("is-open");
    $("menu").setAttribute("aria-expanded", String(open));
  });
  $("presenter").setAttribute("aria-pressed", String(root.classList.contains("presenter")));
  $("presenter").addEventListener("click", () => {
    const on = root.classList.toggle("presenter");
    $("presenter").setAttribute("aria-pressed", String(on));
    const last = [...document.querySelectorAll("#thread .dail")].at(-1);
    if (on && last) last.scrollIntoView({ block: "start" });
  });
  window.matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", (e) => root.classList.toggle("reduce-motion", e.matches));

  const wanted = new URLSearchParams(location.search).get("tab");
  setTab(["ask", "write", "replays"].includes(wanted) ? wanted : "ask");
}

init();

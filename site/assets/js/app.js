// DAIL Live: the page controller (PLAN §3.9). Three tabs over one story:
//   Ask the AI:         Gemini proposes (through /api/propose), DAIL judges in this tab, the AI retries;
//   Write your own fix: the visitor's edit goes to the same DAIL;
//   Replays:            recorded traces from runs/, no Pyodide needed.
import { bundleInfo, loadDail } from "./dail-bridge.js";
import { failedNames } from "./names.js";
import {
  announcement, h, ledgerFromTrace, markBox, refusal, renderBoxes, renderDecision, renderEvidence,
  renderHealth, renderLedger, renderProposal, renderWaiting,
} from "./render.js";

const $ = (id) => document.getElementById(id);
const root = document.documentElement;
const reduced = () => root.classList.contains("reduce-motion");
const MAX_ATTEMPTS = 3;
const CHIPS = ["Close the public SSH port", "Make the database private", "Close SSH and tidy up the database rules"];
const PROPOSE = "/api/propose";

const state = {
  tab: "ask", runs: [], scenarios: [], dail: null, loading: null, busy: false, startFailed: null,
  live: { scenario: "canonical", started: false, trusted: {}, files: {}, current: null, ledger: [], attempts: [], shown: 0, own: null, running: null, note: "" },
  replay: null,
};

// ---- motion: the one signature sequence (PLAN §3.7) ----------------------------------------

function crossBoundary() {
  const card = $("candidate-card");
  if (!card || reduced()) return;
  const from = card.getBoundingClientRect();
  const to = $("boxes").getBoundingClientRect();
  const ghost = h("div", { class: "card card--crossing", "aria-hidden": "true" },
    h("p", { class: "card__source", text: card.querySelector(".card__source").textContent }));
  Object.assign(ghost.style, { left: `${from.left}px`, top: `${from.top}px`, width: `${from.width}px` });
  document.body.append(ghost);
  ghost.animate([{ transform: "none" }, { transform: `translate(${to.left - from.left}px, ${to.top - from.top}px)` }],
    { duration: 280, easing: "steps(6, jump-none)" }).finished.finally(() => ghost.remove());
}

function delay(elements, start, step) {
  elements.forEach((el, i) => { el.style.animationDelay = `${start + step * i}ms`; });
}

// ---- showing one result (a trace) in steps 2 and 3 -------------------------------------------

function showTrace(trace, { live, fresh = null, animate = "none", last = false }) {
  $("result").hidden = false;
  $("propose-title").textContent = trace.candidate_source === "LLM" ? "AI proposes" : trace.candidate_source === "TYPED" ? "You propose" : "The proposal";
  renderProposal($("proposal"), trace);
  const boxes = renderBoxes($("boxes"), trace.refused_before_dail ? 0 : 5);
  const stamp = renderDecision($("decision"), trace, { live, last });
  $("evidence").hidden = false;
  renderEvidence($("evidence-body"), trace);
  const states = live ? state.live.ledger : ledgerFromTrace(trace);
  renderLedger($("ledger"), $("state-detail"), states, fresh);
  renderHealth($("health"), states[0]);
  if (reduced() || animate === "none") return;
  let at = 0;
  if (animate === "all" && !trace.refused_before_dail) {
    crossBoundary();
    for (const box of boxes) box.classList.add("anim-fill");
    delay(boxes, 280, 140);
    at = 280 + 140 * 5;
  }
  if (stamp) { stamp.classList.add("anim-slam"); delay([stamp], at, 0); }
  delay([...document.querySelectorAll("#ledger .anim-drop, #ledger .anim-draw line")], at + 160, 0);
}

function clearResult() {
  $("result").hidden = true;
  $("attempts").hidden = true;
  $("attempt-note").hidden = true;
  $("evidence").open = false;
}

function notice(text) {
  $("notice").hidden = !text;
  $("notice").textContent = text || "";
}

// ---- loading DAIL ----------------------------------------------------------------------------

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
        $("loading-detail").textContent = `${megabytes(done)} of ${megabytes(total)} MB. The released DAIL runs here, unmodified. Replays work meanwhile.`;
      },
    });
    return state.dail;
  })().catch((error) => {
    state.loading = null;
    throw error;
  });
  return state.loading;
}

// Which box each event DAIL commits completes (01 is the admission, before the orchestrator).
const STAGE_OF = { ADMITTED: 0, IDENTITY_COMPLETED: 1, IMPACT_COMPLETED: 2, VERIFICATION_COMPLETED: 3, PROMOTION_DECIDED: 4 };

function stageEvent(name) {
  if (state.live.running !== state.tab || !(name in STAGE_OF)) return;
  if (name === "ADMITTED") crossBoundary();
  markBox($("boxes"), STAGE_OF[name]);
}

// ---- the tab's session ------------------------------------------------------------------------

async function startSession(scenario) {
  setBusy(true);
  try {
    const dail = await ensureDail();
    const answer = await dail.call("start", scenario);
    if (!answer.ok) throw new Error(answer.error);
    Object.assign(state.live, {
      scenario, started: true, trusted: answer.value.files, files: { ...answer.value.files }, current: null,
      ledger: answer.value.ledger, attempts: [], shown: 0, own: null, note: "",
    });
    state.startFailed = null;
    $("announce").textContent = "DAIL is ready. The trusted system is at version 0.";
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
  $("ask").disabled = !ready || state.ai === "unavailable";
  for (const id of ["submit", "reset", "verify", "editor"]) $(id).disabled = !ready;
  $("scenario").disabled = !ready;
  $("instruction").disabled = Boolean(state.live.running);
  for (const el of document.querySelectorAll("#chips .btn, #quick-fill .btn, #files .btn")) el.disabled = state.busy;
  $("loading").hidden = state.live.started || state.tab === "replays" || Boolean(state.startFailed);
}

function takeTrace(trace) {
  const session = trace.session || {};
  state.live.ledger = trace.ledger || state.live.ledger;
  if (session.promoted) {
    state.live.trusted = trace.files;
    state.live.files = { ...trace.files };
    state.live.current = null;
  }
  return session.promoted ? session.trusted_state.state_id : null;
}

// ---- attempts (tabs over steps 2 and 3) --------------------------------------------------------

function attemptLabel(attempt) {
  const t = attempt.trace;
  return `Attempt ${attempt.n} · ${t ? (t.refused_before_dail ? "TURNED AWAY" : t.comparison.C.decision) : "…"}`;
}

function renderAttempts() {
  const list = $("attempts");
  const many = state.tab === "ask" && state.live.attempts.length > 0;
  list.hidden = !many;
  list.replaceChildren(...(many ? state.live.attempts : []).map((a, i) => {
    const tab = h("button", { type: "button", class: "tab", role: "tab", "aria-selected": i === state.live.shown ? "true" : "false", "aria-controls": "result" }, attemptLabel(a));
    tab.disabled = Boolean(state.live.running);
    tab.addEventListener("click", () => { state.live.shown = i; render(); });
    return tab;
  }));
  $("attempt-note").hidden = !(state.tab === "ask" && state.live.note);
  $("attempt-note").textContent = state.live.note;
}

// ---- Ask the AI ------------------------------------------------------------------------------

async function propose(body) {
  const headers = { "Content-Type": "application/json" };
  if ($("passcode").value) headers["X-Demo-Passcode"] = $("passcode").value;
  let response;
  try {
    response = await fetch(PROPOSE, { method: "POST", headers, body: JSON.stringify(body) });
  } catch {
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
    return { decision: "REFUSED", reason: cut(refusal(trace).reasons.join("; "), 400), blocking: [], failed: [] };
  }
  const d = trace.conditions.C.decision;
  return { decision: d.type, reason: d.reason, blocking: (d.blocking || []).slice(0, 8).map((b) => cut(b.target, 80)), failed: failedNames(d) };
}

async function ask() {
  const instruction = $("instruction").value.trim();
  notice("");
  state.live.attempts = [];
  state.live.note = "";
  state.live.running = "ask";
  setBusy(true);
  $("evidence").open = false;
  let feedback = null;
  try {
    for (let n = 1; n <= MAX_ATTEMPTS; n += 1) {
      const attempt = { n, trace: null };
      state.live.attempts.push(attempt);
      state.live.shown = n - 1;
      if (n > 1) state.live.note = `Attempt ${n} of ${MAX_ATTEMPTS}: DAIL's reason was sent back to the AI`;
      showWorking("Gemini is writing a fix…");
      $("announce").textContent = n > 1 ? state.live.note : "Gemini is writing a fix.";
      const body = { scenario_id: state.live.scenario, files: state.live.trusted, attempt: n, instruction };
      if (feedback) body.feedback = feedback;
      const data = await propose(body);
      showWorking("The AI's fix is here. DAIL is reading it…");
      const meta = { model: data.model, tokens: data.tokens, attempt: n, instruction, feedback };
      const answer = await state.dail.call("submit_reply", data.reply, JSON.stringify(meta));
      if (!answer.ok) throw new Error(`The check stopped with an error; this is not a DAIL decision. ${answer.error}`);
      attempt.trace = answer.value;
      attempt.last = n === MAX_ATTEMPTS && !answer.value.session.promoted;
      const fresh = takeTrace(answer.value);
      state.live.showFresh = fresh;
      if (n === MAX_ATTEMPTS || fresh) state.live.running = null;
      render({ animate: "end", fresh });
      toDecision("ask");
      $("announce").textContent = announcement(answer.value);
      if (fresh) break;
      feedback = feedbackFrom(answer.value);
      if (n < MAX_ATTEMPTS) await new Promise((r) => setTimeout(r, reduced() ? 600 : 1800)); // time to read the rejection
    }
  } catch (error) {
    if (!state.live.attempts.at(-1).trace) state.live.attempts.pop();
    state.live.shown = Math.max(0, state.live.attempts.length - 1);
    state.live.note = "";
    state.live.running = null;
    if (state.tab === "ask") {
      render();
      notice(error.message);
      $("notice").scrollIntoView({ block: "center" });
    }
  } finally {
    state.live.running = null;
    setBusy(false);
    if (state.tab === "ask") renderAttempts();
  }
}

function toDecision(owner) {
  if (state.tab === owner) $("step-check").scrollIntoView({ block: "start" });
}

function showWorking(text) {
  state.live.working = text;
  if (state.tab !== state.live.running) return;
  $("result").hidden = false;
  $("propose-title").textContent = state.tab === "write" ? "You propose" : "AI proposes";
  renderWaiting($("proposal"), text);
  renderBoxes($("boxes"));
  $("decision").replaceChildren();
  $("evidence").hidden = true;
  renderAttempts();
  const target = $("attempts").hidden ? $("result") : $("attempts");
  target.scrollIntoView({ block: "start" });
}

// ---- Write your own fix ------------------------------------------------------------------------

function saveEditor() {
  if (state.live.current) state.live.files[state.live.current] = $("editor").value;
}

function updateLines() {
  $("lines").textContent = Array.from({ length: $("editor").value.split("\n").length }, (_, i) => i + 1).join("\n");
  $("lines").scrollTop = $("editor").scrollTop;
}

function renderEditor() {
  const names = Object.keys(state.live.files);
  if (!names.includes(state.live.current)) state.live.current = names.includes("main.tf") ? "main.tf" : names[0] || null;
  $("files").replaceChildren(...names.map((name) => {
    const button = h("button", { type: "button", class: "btn btn--small btn--plain", "aria-pressed": String(name === state.live.current) }, name);
    button.addEventListener("click", () => { saveEditor(); state.live.current = name; renderEditor(); });
    return button;
  }));
  $("editor").value = state.live.files[state.live.current] || "";
  updateLines();
  const scenario = state.scenarios.find((s) => s.id === state.live.scenario) || {};
  const label = { safe: "Fill: a safe fix", regression: "Fill: a fix that breaks something", fixed: "Fill: the recorded fix" };
  $("quick-fill").replaceChildren(...(scenario.quick_fill || []).map((name) => {
    const button = h("button", { type: "button", class: "btn btn--small btn--plain", "data-fill": name }, label[name] || name);
    button.addEventListener("click", async () => {
      const answer = await state.dail.call("patch_files", name);
      if (!answer.ok) return;
      state.live.files = answer.value;
      renderEditor();
      $("editor").focus();
    });
    return button;
  }));
  updateControls();
}

async function submitOwn() {
  saveEditor();
  notice("");
  state.live.own = { trace: null };
  state.live.running = "write";
  setBusy(true);
  $("evidence").open = false;
  showWorking("Your fix");
  $("announce").textContent = "DAIL is checking your fix.";
  try {
    const answer = await state.dail.call("submit_files", JSON.stringify(state.live.files));
    if (!answer.ok) throw new Error(`The check stopped with an error; this is not a DAIL decision. ${answer.error}`);
    state.live.own.trace = answer.value;
    const fresh = takeTrace(answer.value);
    state.live.running = null;
    render({ animate: "end", fresh });
    toDecision("write");
    $("announce").textContent = announcement(answer.value);
  } catch (error) {
    state.live.own = null;
    state.live.running = null;
    render();
    if (state.tab === "write") notice(error.message);
  } finally {
    state.live.running = null;
    setBusy(false);
  }
}

async function verifyChain() {
  const answer = await state.dail.call("verify_chain");
  const v = answer.value;
  $("verify-result").replaceChildren(!answer.ok
    ? h("p", { class: "verify-result verify-result--bad", text: `The chain check could not run: ${answer.error}` })
    : h("div", { class: `verify-result verify-result--${v.ok ? "ok" : "bad"}` },
      h("p", { text: v.ok ? `Chain verified by DAIL: ${v.states} trusted state${v.states === 1 ? "" : "s"}, ${v.candidates} candidate${v.candidates === 1 ? "" : "s"}, no problem.` : "DAIL found problems in the chain:" }),
      ...(v.problems || []).map((p) => h("p", { class: "mono", text: p }))));
}

// ---- Replays ----------------------------------------------------------------------------------

function runLabel(run) {
  const who = run.source === "LLM" ? "Gemini's fix" : run.session_step ? `step ${run.session_step} of a two-step fix` : "recorded fix";
  const what = run.refused_before_dail ? "turned away" : `DAIL ${run.decisions.C}, normal checker ${run.decisions.A}`;
  return `${who}: ${what} (${run.scenario_id})`;
}

async function showReplay(file) {
  $("replay").value = file;
  const response = await fetch(`runs/${file}`);
  if (!response.ok) return notice(`The recorded run could not be loaded (HTTP ${response.status}).`);
  const trace = await response.json();
  if (state.tab !== "replays") return undefined;
  state.replay = file;
  $("evidence").open = false;
  const c = trace.conditions && trace.conditions.C;
  showTrace(trace, { live: false, fresh: c && c.new_state ? c.new_state.state_id : null, animate: "all" });
  $("announce").textContent = announcement(trace);
  return undefined;
}

// ---- the page as a whole ------------------------------------------------------------------------

function render({ animate = "none", fresh = null } = {}) {
  for (const name of ["ask", "write", "replays"]) $(`tab-${name}`).setAttribute("aria-selected", String(state.tab === name));
  $("main-panel").setAttribute("aria-labelledby", `tab-${state.tab}`);
  $("ask-form").hidden = state.tab !== "ask";
  $("write-form").hidden = state.tab !== "write";
  $("replay-form").hidden = state.tab !== "replays";
  $("system-picker").hidden = state.tab === "replays";
  $("verify").hidden = state.tab === "replays" || !state.live.started;
  $("ask-title").textContent = { ask: "Ask", write: "Write", replays: "Watch" }[state.tab];
  if (state.startFailed && state.tab !== "replays") notice(`DAIL could not start here: ${state.startFailed}. The replays still work.`);
  updateControls();
  if (state.tab === "replays") return;
  if (state.tab === "write") renderEditor();
  const shown = state.tab === "ask" ? state.live.attempts[state.live.shown] : state.live.own;
  if (shown && shown.trace) showTrace(shown.trace, { live: true, fresh, animate, last: Boolean(shown.last) });
  else if (shown && state.live.running === state.tab) showWorking(state.live.working);
  else clearResult();
  renderAttempts();
  if (!shown || !shown.trace) {
    renderLedger($("ledger"), $("state-detail"), state.live.ledger);
    renderHealth($("health"), state.live.ledger[0]);
  }
}

async function setTab(tab) {
  if (state.tab === "write") saveEditor();
  state.tab = tab;
  notice("");
  $("verify-result").replaceChildren();
  clearResult();
  render();
  if (tab === "replays" && state.runs.length) await showReplay(state.replay || (state.runs.find((r) => r.file === "canonical--regression.json") || state.runs[0]).file);
}

async function init() {
  const get = (url, empty) => fetch(url).then((r) => (r.ok ? r.json() : empty)).catch(() => empty);
  const [runs, scenarios, ai] = await Promise.all([
    get("runs/index.json", { runs: [] }), get("vendor/scenarios/index.json", { scenarios: [] }), get(PROPOSE, null)]);
  state.runs = runs.runs || [];
  state.scenarios = scenarios.scenarios || [];
  state.ai = ai && ai.available ? "available" : "unavailable";
  renderHealth($("health"), null);
  $("passcode-field").hidden = !(ai && ai.passcode_required);
  $("replay").replaceChildren(...state.runs.map((r) => h("option", { value: r.file }, runLabel(r))));
  $("scenario").replaceChildren(...state.scenarios.map((s) => h("option", { value: s.id }, s.id === "canonical" ? "The standard example" : `${s.why} (${s.id})`)));
  $("chips").replaceChildren(...CHIPS.map((text) => {
    const chip = h("button", { type: "button", class: "btn btn--small btn--plain" }, text);
    chip.addEventListener("click", () => { $("instruction").value = text; $("instruction").focus(); });
    return chip;
  }));
  if (state.ai === "unavailable") $("ask").after(h("p", { class: "note", id: "ai-off", text: "The AI is not set up on this site. Write your own fix, or watch the replays." }));

  for (const name of ["ask", "write", "replays"]) $(`tab-${name}`).addEventListener("click", () => setTab(name));
  $("ask-form").addEventListener("submit", (event) => { event.preventDefault(); if (!$("ask").disabled) ask(); });
  $("write-form").addEventListener("submit", (event) => { event.preventDefault(); if (!$("submit").disabled) submitOwn(); });
  $("replay").addEventListener("change", (event) => showReplay(event.target.value));
  $("scenario").addEventListener("change", (event) => { clearResult(); startSession(event.target.value); });
  $("reset").addEventListener("click", () => { clearResult(); $("verify-result").replaceChildren(); startSession(state.live.scenario); });
  $("verify").addEventListener("click", verifyChain);
  $("editor").addEventListener("input", () => { saveEditor(); updateLines(); });
  $("editor").addEventListener("scroll", () => { $("lines").scrollTop = $("editor").scrollTop; });
  $("presenter").setAttribute("aria-pressed", String(root.classList.contains("presenter")));
  $("presenter").addEventListener("click", () => {
    const on = root.classList.toggle("presenter");
    $("presenter").setAttribute("aria-pressed", String(on));
    if (on && !$("result").hidden) $("step-check").scrollIntoView();
  });
  window.matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", (e) => root.classList.toggle("reduce-motion", e.matches));

  const wanted = new URLSearchParams(location.search).get("tab");
  await setTab(["ask", "write", "replays"].includes(wanted) ? wanted : "ask");
  if (state.tab !== "replays") startSession("canonical");
  else for (const name of ["ask", "write"]) $(`tab-${name}`).addEventListener("click", () => { if (!state.live.started && !state.busy) startSession("canonical"); });
}

init();

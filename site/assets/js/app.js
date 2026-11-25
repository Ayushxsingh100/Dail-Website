// DAIL Live: the page controller. Two modes (PLAN §3.8):
//   Replays: recorded traces from runs/, no Pyodide needed;
//   Live:    "Beat the gate": the visitor's edit goes to the real DAIL running in this tab.
import { bundleInfo, loadDail } from "./dail-bridge.js";
import {
  announcement, formatDate, h, ledgerFromTrace, markStage, pad, renderCandidate, renderDecision, renderLedger,
  renderOvf, renderStages, waitingStages,
} from "./render.js";

const $ = (id) => document.getElementById(id);
const root = document.documentElement;
const reduced = () => root.classList.contains("reduce-motion");

const state = {
  mode: "replays",
  runs: [],
  scenarios: [],
  dail: null,
  loading: null,
  live: { sessions: 0, scenario: null, files: {}, current: null, sequence: 0, version: 0, ledger: [] },
};

// ---- motion: the one signature sequence (PLAN §3.7) ----------------------------------------

// The candidate card crosses the trust boundary: a copy travels from the untrusted zone to the gate.
function crossBoundary(card) {
  const from = card.getBoundingClientRect();
  const to = $("stages").getBoundingClientRect();
  const ghost = h("div", { class: "card card--crossing", "aria-hidden": "true" },
    h("span", { class: "card__source", text: card.querySelector(".card__source").textContent }),
    h("p", { class: "card__label", text: card.querySelector(".card__label").textContent }));
  Object.assign(ghost.style, { left: `${from.left}px`, top: `${from.top}px`, width: `${from.width}px` });
  document.body.append(ghost);
  ghost.animate(
    [{ transform: "none" }, { transform: `translate(${to.left - from.left}px, ${to.top - from.top}px)` }],
    { duration: 280, easing: "steps(6, jump-none)" },
  ).finished.finally(() => ghost.remove());
}

function play({ card, stages, stamp, fresh }) {
  if (reduced()) return;
  const step = 140;
  const start = card ? 280 : 0;
  if (card) crossBoundary(card);
  stages.forEach((el, i) => {
    el.style.animationDelay = `${start + step * i}ms`;
    el.classList.add("anim-fill");
  });
  if (stamp) {
    stamp.style.animationDelay = `${start + step * stages.length}ms`;
    stamp.classList.add("anim-slam");
  }
  if (fresh) {
    const delay = `${start + step * (stages.length + 1)}ms`;
    for (const el of document.querySelectorAll(".anim-drop, .anim-draw line")) el.style.animationDelay = delay;
  }
}

function show(trace, { mode, freshState = null, issue, live = false }) {
  const card = renderCandidate($("candidate"), trace, { mode });
  const stages = renderStages($("stages"), trace);
  const stamp = renderDecision($("decision"), trace, { mode });
  renderOvf($("ovf"), trace);
  renderLedger($("ledger"), ledgerFromTrace(trace), { fresh: freshState, trace });
  $("issue").textContent = issue;
  $("announce").textContent = announcement(trace);
  // after a live run the card has crossed and the stages have filled while DAIL worked
  const filled = live || trace.refused_before_dail;
  play({ card: filled ? null : card, stages: filled ? [] : stages, stamp, fresh: freshState });
}

// ---- replays --------------------------------------------------------------------------------

function replayScenarios() {
  const seen = new Map();
  for (const run of state.runs) if (!seen.has(run.scenario_id)) seen.set(run.scenario_id, run.family);
  return [...seen.keys()];
}

function runLabel(run) {
  const source = run.source === "LLM" ? `Gemini (${run.model})` : run.source === "TYPED" ? "typed" : run.session_step ? `session step ${run.session_step}` : "fixed patch";
  const decided = run.refused_before_dail ? "refused before DAIL" : `DAIL ${run.decisions.C} · target-only ${run.decisions.A}`;
  return `${source}: ${decided}`;
}

function fillReplayPickers(selectedScenario) {
  const scenarios = replayScenarios();
  const scenario = scenarios.includes(selectedScenario) ? selectedScenario : scenarios[0];
  $("scenario").replaceChildren(...scenarios.map((id) => h("option", { value: id, selected: id === scenario }, id)));
  const runs = state.runs.filter((r) => r.scenario_id === scenario);
  $("replay").replaceChildren(...runs.map((r) => h("option", { value: r.file }, runLabel(r))));
  const info = state.scenarios.find((s) => s.id === scenario);
  $("scenario-why").textContent = info ? info.why : "";
  return runs;
}

async function showReplay(file) {
  $("replay").value = file;
  const run = state.runs.find((r) => r.file === file);
  if (!run) return;
  const response = await fetch(`runs/${file}`);
  if (!response.ok) throw new Error(`runs/${file}: HTTP ${response.status}`);
  const trace = await response.json();
  if (state.mode !== "replays") return;
  const index = state.runs.indexOf(run) + 1;
  const ledger = ledgerFromTrace(trace);
  const newest = ledger[0];
  const promoted = trace.conditions && trace.conditions.C && trace.conditions.C.new_state;
  show(trace, {
    mode: "replays",
    freshState: promoted ? promoted.state_id : null,
    issue: `Replay ${pad(index)} of ${pad(state.runs.length)} · Candidate ${pad((trace.session && trace.session.sequence) || 1)} · Trusted state v${newest ? newest.version : 0} · recorded ${formatDate(trace.created_at)}`,
  });
}

// ---- live mode ------------------------------------------------------------------------------

function liveScenarioPicker() {
  $("scenario").replaceChildren(...state.scenarios.map((s) =>
    h("option", { value: s.id, selected: s.id === state.live.scenario }, `${s.id}${s.family !== "canonical" ? ` (${s.family})` : ""}`)));
  const info = state.scenarios.find((s) => s.id === state.live.scenario);
  $("scenario-why").textContent = info ? info.why : "";
}

function megabytes(bytes) {
  return (bytes / 1e6).toFixed(1);
}

async function ensureDail() {
  if (state.dail) return state.dail;
  if (state.loading) return state.loading;
  $("loading").hidden = false;
  state.loading = (async () => {
    try {
      const { bytes } = await bundleInfo("vendor");
      $("loading-title").textContent = `Loading DAIL into your browser (~${megabytes(bytes)} MB)`;
      const dail = await loadDail({
        vendor: "vendor",
        onEvent: stageEvent,
        onProgress: ({ done, total, stage }) => {
          $("meter").style.width = `${Math.min(100, Math.round((100 * done) / total))}%`;
          $("loading-detail").textContent = stage === "ready" ? "DAIL is ready." :
            `${megabytes(done)} of ${megabytes(total)} MB: ${stage === "files" ? "DAIL's source, each file checked by its SHA-256" : stage === "sqlite3" ? "SQLite for the in-tab ledger" : "the Python runtime (Pyodide 0.27.7)"}.`;
        },
      });
      state.dail = dail;
      $("loading").hidden = true;
      return dail;
    } catch (error) {
      $("loading-error").hidden = false;
      $("loading-error").textContent = `Live mode could not start: ${error.message}. Replays still work.`;
      state.loading = null;
      throw error;
    }
  })();
  return state.loading;
}

function renderFiles() {
  const names = Object.keys(state.live.files);
  if (!names.includes(state.live.current)) state.live.current = names.includes("main.tf") ? "main.tf" : names[0];
  $("files").replaceChildren(...names.map((name) => {
    const tab = h("button", { type: "button", class: "btn btn--small", role: "tab", "aria-selected": name === state.live.current ? "true" : "false", "aria-pressed": name === state.live.current ? "true" : "false" }, name);
    tab.addEventListener("click", () => { saveEditor(); state.live.current = name; renderFiles(); });
    return tab;
  }));
  $("editor").value = state.live.files[state.live.current] || "";
  $("editor").setAttribute("aria-label", `Configuration file ${state.live.current}`);
  updateLines();
}

function saveEditor() {
  if (state.live.current) state.live.files[state.live.current] = $("editor").value;
}

function updateLines() {
  const count = $("editor").value.split("\n").length;
  $("lines").textContent = Array.from({ length: count }, (_, i) => i + 1).join("\n");
  $("lines").scrollTop = $("editor").scrollTop;
}

function liveIssue() {
  const l = state.live;
  return `Session ${pad(l.sessions)} · Candidate ${pad(l.sequence)} · Trusted state v${l.version} · ${formatDate()}`;
}

function quickFill(scenario) {
  const buttons = (scenario.quick_fill || []).map((name) => {
    const label = name === "safe" ? "Fill: the safe repair" : name === "regression" ? "Fill: the repair that breaks INV-FUNC-001" : "Fill: the scenario's own fix";
    const button = h("button", { type: "button", class: "btn btn--small", "data-fill": name }, label);
    button.addEventListener("click", async () => {
      const answer = await state.dail.call("patch_files", name);
      if (!answer.ok) return;
      state.live.files = answer.value;
      renderFiles();
      $("editor").focus();
    });
    return button;
  });
  $("quick-fill").replaceChildren(...buttons);
}

async function startLive(scenarioId) {
  const dail = await ensureDail();
  if (state.mode !== "live") return; // the visitor went back to the replays while DAIL was loading
  setBusy(true);
  const answer = await dail.call("start", scenarioId);
  setBusy(false);
  if (!answer.ok) throw new Error(answer.error);
  const s = answer.value;
  Object.assign(state.live, { scenario: scenarioId, files: s.files, current: null, sequence: 0, ledger: s.ledger, version: 0, last: null });
  state.live.sessions += 1;
  if (state.mode !== "live") return;
  liveScenarioPicker();
  quickFill(state.scenarios.find((x) => x.id === scenarioId) || {});
  renderFiles();
  $("editor-panel").hidden = false;
  $("ledger-tools").hidden = false;
  $("verify-result").replaceChildren();
  $("candidate").replaceChildren();
  $("decision").replaceChildren();
  $("ovf").replaceChildren();
  waitingStages($("stages"), "Waiting for your patch.");
  renderLedger($("ledger"), s.ledger);
  $("issue").textContent = liveIssue();
  $("announce").textContent = `New session on ${scenarioId}: the trusted state is DAIL's baseline, v0.`;
}

// Back from the replays: the tab's session is still there (nothing is re-evaluated).
function resumeLive() {
  liveScenarioPicker();
  if (state.live.last) {
    show(state.live.last, { mode: "live", live: true, issue: liveIssue() });
    return;
  }
  $("candidate").replaceChildren();
  $("decision").replaceChildren();
  $("ovf").replaceChildren();
  waitingStages($("stages"), "Waiting for your patch.");
  renderLedger($("ledger"), state.live.ledger);
  $("issue").textContent = liveIssue();
}

// Which stage each event DAIL commits completes (01 is the admission, before the orchestrator).
const STAGE_OF = { ADMITTED: 0, IDENTITY_COMPLETED: 1, IMPACT_COMPLETED: 2, VERIFICATION_COMPLETED: 3, PROMOTION_DECIDED: 4 };

function stageEvent(name) {
  if (state.mode !== "live" || !(name in STAGE_OF)) return;
  if (name === "ADMITTED" && !reduced()) crossBoundary($("candidate-card"));
  markStage($("stages"), STAGE_OF[name]);
}

function setBusy(on) {
  state.busy = on;
  for (const el of [$("submit"), $("reset"), $("verify"), $("scenario"), $("editor"), ...document.querySelectorAll("[data-fill]")]) {
    el.disabled = on;
  }
}

async function submitLive() {
  saveEditor();
  const button = $("submit");
  setBusy(true);
  button.textContent = "DAIL is checking…";
  $("announce").textContent = "DAIL is checking the patch.";
  $("decision").replaceChildren();
  $("ovf").replaceChildren();
  $("candidate").replaceChildren(h("article", { class: "card", id: "candidate-card" },
    h("span", { class: "card__source", text: "Typed patch" }),
    h("p", { class: "card__label", text: `${state.live.scenario} typed in the browser` })));
  waitingStages($("stages"), "DAIL is checking…");
  try {
    const answer = await state.dail.call("submit_files", JSON.stringify(state.live.files));
    if (!answer.ok) {
      if (state.mode !== "live") return;
      $("candidate").replaceChildren(h("div", { class: "refused", role: "status" },
        h("p", { class: "refused__title", text: "Not evaluated" }),
        h("p", { text: "The run stopped with an error. This is not a DAIL decision; the trusted state stays where it was." }),
        h("p", { class: "refused__reason", text: answer.error })));
      $("decision").replaceChildren();
      $("ovf").replaceChildren();
      waitingStages($("stages"), "Not evaluated.");
      $("announce").textContent = "Not evaluated: the run stopped with an error.";
      return;
    }
    const trace = answer.value;
    const session = trace.session || {};
    state.live.last = trace;
    state.live.sequence = session.sequence || state.live.sequence;
    state.live.ledger = trace.ledger || state.live.ledger;
    state.live.version = (session.trusted_state || {}).version ?? state.live.version;
    if (session.promoted) {
      state.live.files = trace.files;
      renderFiles();
    }
    if (state.mode !== "live") return; // shown when the visitor comes back (resumeLive)
    show(trace, { mode: "live", live: true, freshState: session.promoted ? session.trusted_state.state_id : null, issue: liveIssue() });
    $("verify-result").replaceChildren();
  } finally {
    setBusy(false);
    button.textContent = "Submit to the gate";
  }
}

async function verifyChain() {
  const answer = await state.dail.call("verify_chain");
  const box = $("verify-result");
  if (!answer.ok) {
    box.replaceChildren(h("p", { class: "verify-result verify-result--bad", text: `Chain check failed to run: ${answer.error}` }));
    return;
  }
  const v = answer.value;
  box.replaceChildren(h("div", { class: `verify-result verify-result--${v.ok ? "ok" : "bad"}` },
    h("p", { text: v.ok ? `Chain verified by DAIL: ${v.states} trusted state${v.states === 1 ? "" : "s"}, ${v.candidates} candidate${v.candidates === 1 ? "" : "s"}, no problem.` : "DAIL found problems in the chain:" }),
    ...(v.problems || []).map((p) => h("p", { class: "mono", text: p }))));
}

// ---- modes ----------------------------------------------------------------------------------

async function setMode(mode) {
  state.mode = mode;
  $("scenario").disabled = mode === "live" && Boolean(state.busy);
  $("mode-live").setAttribute("aria-pressed", String(mode === "live"));
  $("mode-replays").setAttribute("aria-pressed", String(mode === "replays"));
  $("live-panel").hidden = mode !== "live";
  $("replay-field").hidden = mode !== "replays";
  $("ledger-tools").hidden = mode !== "live" || !state.dail;
  $("verify-result").replaceChildren();
  if (mode === "replays") {
    const runs = fillReplayPickers($("scenario").value);
    if (runs.length) await showReplay(runs.find((r) => r.decisions.C === "REJECT")?.file || runs[0].file);
    return;
  }
  if (state.dail && state.live.sessions > 0) {
    resumeLive();
    return;
  }
  $("candidate").replaceChildren();
  $("decision").replaceChildren();
  $("ovf").replaceChildren();
  renderLedger($("ledger"), []);
  liveScenarioPicker();
  waitingStages($("stages"), "Loading DAIL into your browser…");
  try {
    await startLive(state.live.scenario || "canonical");
  } catch {
    /* the loading panel shows the reason; replays keep working */
  }
}

async function init() {
  const [runs, scenarios] = await Promise.all([
    fetch("runs/index.json").then((r) => (r.ok ? r.json() : { runs: [] })).catch(() => ({ runs: [] })),
    fetch("vendor/scenarios/index.json").then((r) => (r.ok ? r.json() : { scenarios: [] })).catch(() => ({ scenarios: [] })),
  ]);
  state.runs = runs.runs || [];
  state.scenarios = scenarios.scenarios || [];
  state.live.scenario = "canonical";

  $("mode-live").addEventListener("click", () => setMode("live"));
  $("mode-replays").addEventListener("click", () => setMode("replays"));
  $("presenter").addEventListener("click", () => {
    const on = root.classList.toggle("presenter");
    $("presenter").setAttribute("aria-pressed", String(on));
    if (on) $("zones").scrollIntoView(); // the decision, the stages and the ledger on one screen
  });
  $("presenter").setAttribute("aria-pressed", String(root.classList.contains("presenter")));
  $("scenario").addEventListener("change", async (event) => {
    if (state.busy) return;
    if (state.mode === "replays") {
      const list = fillReplayPickers(event.target.value);
      if (list.length) await showReplay(list[0].file);
    } else {
      await startLive(event.target.value);
    }
  });
  $("replay").addEventListener("change", (event) => showReplay(event.target.value));
  $("editor").addEventListener("input", () => { saveEditor(); updateLines(); });
  $("editor").addEventListener("scroll", () => { $("lines").scrollTop = $("editor").scrollTop; });
  $("submit").addEventListener("click", submitLive);
  $("reset").addEventListener("click", () => startLive(state.live.scenario));
  $("verify").addEventListener("click", verifyChain);
  window.matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", (e) => root.classList.toggle("reduce-motion", e.matches));

  const wanted = new URLSearchParams(location.search).get("mode") === "live" ? "live" : "replays";
  if (wanted === "replays") fillReplayPickers("canonical");
  await setMode(wanted);
}

init();

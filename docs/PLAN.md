# DAIL Live: build plan (v1, 25 Nov 2026)

**What this is.** The full plan for DAIL Live, a local demo application in which an AI (Google Gemini, free tier) or a person proposes a fix to a Terraform configuration and the real, released DAIL decides whether to promote it, live and stage by stage.

**How it will be built.** Claude Code implements it, one work package per pull request. Claude (the build chat) writes each work package and reviews each PR independently. Ayush merges after the review verdict, always with a merge commit. This file is committed to the new repository as `docs/PLAN.md` in work package L0 and is the authority for the build. Changes to it are made by PR and recorded in `docs/DECISIONS.md`.

---

## 1. Goal and success criteria

**Goal.** In under five minutes, show any audience (teacher, faculty, judges, interviewers):
- an AI, or a person, proposes a fix;
- DAIL checks it with its real code and decides PROMOTE, REJECT, RETRY or ESCALATE, with the reason;
- target-only checking, given the same patch, would have accepted a fix that breaks something else.

**Success criteria (all must hold at the end):**
1. **Real decisions.** Every decision shown comes from DAIL's own `EvaluationOrchestrator.evaluate` (`core/application/orchestrator.py`), the path used in DAIL's main run. Nothing on screen is simulated, hard-coded or computed by demo code.
2. **The released DAIL is untouched.** The demo reads DAIL from a checkout at tag `dail-v1.0` and refuses to start otherwise. No file of DAIL is changed or copied in modified form.
3. **Never fails on stage.** The typed-patch mode needs no network and always reaches a decision. The AI mode is optional; when Gemini is unavailable (no key, no internet, rate limit), the page says so and the demo continues.
4. **Zero cost.** Only the Gemini free tier is used; no paid API, no paid cloud, no AWS account.
5. **Honest labelling.** The page and every saved trace say "Demo, not part of the DAIL evaluation". The demo never presents its output as research results.
6. **Runs on the demo laptop.** Windows 11, Python 3.12, in a browser on `localhost`.

---

## 2. Scope

### In scope
- A local web page served on `localhost` only.
- A scenario picker: the canonical SSH/database example from DAIL's fixtures, plus a small set of public TerraPreserve repair scenarios.
- An **"Ask the AI"** button (Gemini), with up to 3 attempts, which is DAIL's retry limit.
- A **"Write your own patch"** editor: the "Beat the gate" mode.
- Live stages: admission, identity and change, impact, verification, decision.
- A comparison with target-only checking (DAIL's condition A) on the same patch.
- Sessions: a promoted candidate becomes the next trusted state; a ledger view with the hash chain; a reset.
- Saved traces of every run, and their export for a public replay page and a video.

### Not allowed (also keeps DAIL Live separate from the CloudShield AI product)
- Scanning or connecting to any real cloud account; any AWS API call; any AWS credentials.
- `terraform plan`, `apply` or `destroy`. The only Terraform command allowed is the offline `terraform validate` (with `init -backend=false` and the local provider mirror), as in DAIL.
- Risk scoring, findings dashboards, multi-account or user-account features, logins.
- CloudShield AI name or branding anywhere.
- Paid APIs, paid models or paid cloud.
- Serving the app to the network. It binds to `127.0.0.1` only.
- New safety logic. The demo may not decide anything itself; it only calls DAIL and displays what DAIL returns.
- Committing any secret, including the Gemini API key.

*Pending:* if the authors upload the CloudShield AI product documents, this list is checked against them and extended by a PR.

---

## 3. Architecture

### 3.1 Repository and pinning
- **A new repository, `Dail-Website` (https://github.com/Ayushxsingh100/Dail-Website),** created empty on GitHub by Ayush. Licence Apache-2.0.
- **DAIL is an external dependency.** The demo reads it from a path given by `DAIL_ROOT`. At startup it checks with `git describe --tags --exact-match` that the checkout is at `dail-v1.0`, with a clean tree, and refuses to start otherwise. This is the same pattern the experiment harness uses for TerraPreserve (`experiments/__main__.py`).
- **TerraPreserve.** The scenarios are read from a checkout given by `TERRAPRESERVE_ROOT`, at tag `terrapreserve-v1.0-public-r3`, checked the same way.
- **Runtime data** (session stores, traces, the Terraform work directory) goes to a directory given by `DAIL_LIVE_DATA`. It must be outside both repositories and is never committed.

### 3.2 Technology
- **Python 3.12, standard library only,** the same rule as DAIL:
  - the web server is `http.server`;
  - live updates use server-sent events;
  - Gemini is called through `urllib.request`.
- **One HTML page** with inline CSS and JS. No frontend framework, no build step, no CDN at run time, so the page works offline.
- **Tests:** `unittest`, as in DAIL. CI on GitHub Actions (free for a public repository) runs the suite and gitleaks.

### 3.3 What is reused from DAIL (never rewritten)

| Need | DAIL module |
|---|---|
| The decision pipeline | `core/application/orchestrator.py` (`EvaluationOrchestrator`, `EvaluationRequest`, `LLMEvaluationRequest`) |
| Establishing a verified baseline | `core/application/baseline.py` |
| Target-only and DAIL as conditions A and C | `experiments/conditions.py` |
| The LLM context, the repair prompt `dail-repair-prompt-3`, the generator | `llm/adapter/context.py`, `llm/prompts/templates.py`, `llm/adapter/generate.py` |
| The provider interface the Gemini adapter must implement | `llm/adapter/provider.py` (`ProviderCall`, `ProviderReply`; see `ollama.py` and `fake.py` for the two existing providers) |
| Response parsing and patch validation | `llm/validation/parser.py`, `llm/validation/patch.py` |
| The offline `terraform validate` gate | `experiments/terraform_validate.py` |
| The evidence store and hash chain | `core/persistence`, `core/application/chain.py` |

The work packages must use these entry points. If one of them cannot be used from outside DAIL without changing DAIL, Claude Code stops and reports. It does not patch DAIL.

### 3.4 The promotion switch
DAIL keeps automatic promotion off in its default configuration (`config/`). The experiment harness turns it on only in its own reviewed copy (`experiments/config/promotion.toml`, C-207). The demo does the same: it has its own reviewed `config/promotion.toml`, the only place the switch is turned on, and a test that fails if the switch is on anywhere else.

### 3.5 The Gemini adapter
- **Location:** `dail_demo/gemini.py`, a `GeminiProvider` that implements DAIL's provider interface, so DAIL's `Generator`, prompt, parser and patch validator are used unchanged.
- **The key:** read only from the environment variable `GEMINI_API_KEY`. It is never written to a file, a log, a trace or the page. `.env` files are git-ignored. gitleaks runs in CI.
- **The model:** configurable, never hard-coded in logic. The default is a model that Google's official pricing page lists as free of charge. On 25 Nov 2026 that page lists, among others, `gemini-3.5-flash` and `gemini-2.5-flash`.
  - At build time, Claude Code checks the official documentation for the current model codes and request format, and records both in `docs/DECISIONS.md` with the date.
  - At startup, the adapter confirms that the configured model exists by listing the models, and reports clearly if it does not.
- **The request:** temperature, top-p and the attempt time limit are fixed in config and recorded in every trace.
  - The adapter asks for JSON output, but DAIL's own parser remains the judge of the response.
- **Failures:** a missing key, no network, HTTP 429 (free-tier rate limit) or a time-out each give a clear message on the page. They never crash the demo, and they never count as a DAIL decision.
- **Data note:** on the free tier, Google may use the content sent to improve its products. Only the scenario's Terraform text, which uses invented values, and DAIL's prompt are sent. A typed patch is never sent to Gemini.
- **Ollama:** the existing `OllamaProvider` stays available as an offline fallback, selectable in config. This is optional and costs nothing.

### 3.6 The comparison with target-only checking
For every candidate, the demo runs DAIL (condition C) on the session's lineage. It also runs target-only checking (condition A) on the same candidate, against the same parent, in a throwaway store. The page shows both decisions and both check counts.

Only DAIL's lineage advances. Condition A never becomes the session's trusted state, so a bad patch that A would have accepted cannot poison the demo.

### 3.7 Visual design (binding for L3; chosen by the authors on 26 Nov 2026)

**Direction: Neo-Brutalism + Swiss grid + retro editorial.** The page reads like the front page of a printed technical gazette, laid out on a strict Swiss grid, built from heavy brutalist blocks. Its structure is DAIL's own architecture, so the style serves the subject instead of decorating it.

**Structure (12-column grid, 8 px baseline, flush-left text, asymmetric):**
- **Masthead** across the full width:
  - "DAIL LIVE" set very large;
  - an issue line in the retro-editorial manner, built from real session data: `Session 01 · Candidate 03 · Trusted state v2 · 26 Nov 2026`;
  - heavy and thin rules above and below, as on a newspaper;
  - the label "Demo, not part of the DAIL evaluation" sits in the masthead and is always visible.
- **Three zones** below the masthead, split by a thick black dashed vertical rule labelled **TRUST BOUNDARY** (set vertically):

  | Zone | Columns | Content |
  |---|---|---|
  | Untrusted | 1–4 | The AI's or the person's patch: the diff, the editor, the AI attempts. A diagonal hatch background says "not trusted" |
  | The gate | 5–8 | DAIL's five stages as numbered blocks 01–05, with very large numerals (a real sequence, so numbering is meaningful) |
  | The ledger | 9–12 | Trusted states stacked as newspaper "clippings", newest on top. Each shows its version, its invariant statuses and its hash in mono, joined to the one below by a drawn link |

- **The decision** is a large stamp block, rotated about −3°, with a thick border and a hard shadow: PROMOTE or REJECT, with DAIL's reason beneath it as an editorial pull-quote.
- **The comparison with target-only checking** is set as a two-column "Opinion vs. Fact" box under the gate: what target-only decided against what DAIL decided, with both check counts.
- At phone width the zones stack in the order untrusted, gate, ledger. The trust boundary becomes a horizontal rule.

**Brutalist rules:**
- borders 3 px solid ink;
- hard offset shadows (`6px 6px 0` ink), never blurred;
- flat colour blocks;
- no gradients, no glass, no blur, no rounded cards (radius 0; pills only for status tags);
- buttons that press physically: on `:active` they move by the shadow offset and the shadow drops to 0.

**Palette** (single light theme, chosen for projectors; every colour has exactly one meaning):

| Token | Value | Meaning |
|---|---|---|
| `--paper` | `#EEECE5` (newsprint) | Background |
| `--ink` | `#111111` | Text, borders, shadows, rules |
| `--signal-red` | `#E4321B` (Swiss red) | FAIL and REJECT only |
| `--signal-green` | `#0E8A5F` | PASS and PROMOTE only |
| `--marker` | `#FFD60A` | What this change affects (highlighter blocks) |
| `--cobalt` | `#2340E0` | Carried forward, links and focus |
| `--muted` | `#55524A` | Secondary text; never for anything that matters |

All text on colour blocks is ink, except on red, green and cobalt, where it is paper. Every pair meets WCAG AA (L3 checks this and records the ratios in `docs/DECISIONS.md`).

**Type** (Google Fonts, self-hosted copies so the page works offline; each with a system fallback):

| Role | Typeface |
|---|---|
| Masthead and stage numerals | Archivo, weight 800–900, expanded width |
| Body and UI | Archivo, weight 400–600 |
| Editorial voice: pull-quotes, the decision reason, kicker lines | Instrument Serif, italic |
| Code, hashes, resource addresses | IBM Plex Mono |

- The scale is fixed in tokens.
- Labels are uppercase with letter-spacing.
- Nothing that matters is smaller than 16 px; in presenter mode, 20 px.

**Motion** (brutalist: quick and stepped, no floaty easing; switched off under `prefers-reduced-motion`):
- **The one signature moment:**
  1. the candidate card moves across the trust boundary;
  2. the stage blocks fill in one by one as DAIL finishes them;
  3. the stamp slams down (scale 1.4 → 1 in about 120 ms);
  4. on PROMOTE, a new clipping drops onto the ledger and its hash link is drawn.
- No other decorative animation.

**Presenter mode:** a toggle in the masthead.
- It enlarges the type scale by 25%.
- It hides the editor's line numbers.
- It keeps the decision, the stages and the ledger on one screen at 1366×768.

**Not allowed:**
- dark-neon or terminal looks;
- purple or blue gradients;
- glassmorphism;
- emoji;
- stock illustrations;
- the CloudShield name or branding.

**Acceptance (added to L3):**
- The page follows this section.
- One screenshot per zone is attached to the PR, at 1366×768 and at phone width.
- The contrast ratios are recorded.
- The page works with no internet: fonts are self-hosted and no CDN is used.

---

## 4. What the user sees (the flow)

1. **Start.** `python -m dail_demo serve` checks the DAIL and TerraPreserve tags, the Terraform binary and mirror, and the Gemini key (optional). It prints `http://127.0.0.1:<port>`.
2. **Pick a scenario.** The page shows:
   - the configuration files;
   - a simple network view;
   - the ledger, established by DAIL's own baseline flow: which invariants are PROTECTED, and which one is the repair target (VIOLATED).
3. **Propose a fix:**
   - **Ask the AI.** Gemini writes a patch. The page shows the attempt, then DAIL's parser and patch-validator verdict, then `terraform validate`. An invalid answer is shown honestly as rejected before DAIL, with the reason. There are up to 3 attempts.
   - **Write your own.** Edit the files of the current trusted configuration in the editor and submit.
4. **Watch DAIL work.** Each stage appears as DAIL finishes it:
   - admission;
   - identity and change, with change types;
   - impact, with affected invariants, dependency paths, uncertainty and what is carried forward;
   - verification, with each check's verdict and reason;
   - the decision, with its reason and blocking conditions.
5. **Compare.** Target-only checking's decision and check count on the same patch, beside DAIL's.
6. **Continue.** On PROMOTE, the candidate becomes the new trusted state, and the next fix starts from it. The ledger view shows each promoted state and its hash link. **Reset** returns to the scenario's start.
7. **Saved.** Every run is written as a trace file: inputs, AI attempts, DAIL's outputs, decisions, versions and hashes. Traces never contain the API key.

---

## 5. Work packages

Each package is one Claude Code prompt and one PR. Each PR is reviewed before the next prompt is written.

| # | Package | Delivers | Accepted when |
|---|---|---|---|
| **L0** | **Bootstrap** | The repo skeleton (layout, `README`, `LICENSE`, `.gitignore`, CI with tests and gitleaks); this plan as `docs/PLAN.md`; `docs/DECISIONS.md`; the startup checks for the DAIL tag, the TerraPreserve tag, `DAIL_LIVE_DATA` and Terraform | CI green. The startup check refuses a DAIL checkout that is not at `dail-v1.0` or not clean (tested). No secret in the repo |
| **L1** | **Engine** | `python -m dail_demo evaluate --scenario <id> --patch <dir>`: establishes the baseline with DAIL, runs the candidate through DAIL (C) and target-only (A), and writes a trace | On the canonical example, the results equal DAIL's own fixture expectations: the safe repair is PROMOTE, the breaking repair is REJECT, blocked by INV-FUNC-001, and DAIL runs 5 checks against A's 3. Proven by tests that compare against DAIL's `expected.json`, not against numbers typed into the demo |
| **L2** | **AI and typed input** | `GeminiProvider`; generation through DAIL's `Generator`, prompt, parser, patch validator and the `terraform validate` gate; up to 3 attempts; typed-patch input from edited files | Tested with DAIL's `FakeProvider` (no network in CI): an invalid response never reaches the orchestrator; a valid one does. Missing key, 429 and time-out give clear errors. The key appears in no file, log or trace (tested) |
| **L3** | **Live page** | The local web app: scenario picker, configuration view, ledger, AI button, editor, live stages, comparison panel, "Demo, not part of the DAIL evaluation" label | The full flow works in Chrome and Edge on Windows, offline in typed mode. The server binds to `127.0.0.1` only (tested). The page follows the visual design of §3.7, with screenshots and contrast ratios in the PR |
| **L4** | **Sessions and ledger** | Promotion advances the session's trusted state; ledger view with hash links; reset; stale-parent protection shown if two candidates race | Three patches in a row (promote, reject, promote) leave exactly DAIL's lineage. The ledger's hash chain verifies with DAIL's own check |
| **L5** | **Traces and export** | Trace export for the public replay page; the demo script (`docs/DEMO_SCRIPT.md`) | An exported trace replays to the same decisions. The build chat then builds the public replay page from real exported traces |

**After L5:** a full rehearsal on the demo laptop, then the 2-minute screen recording.

---

## 6. Rules for every package (same as the DAIL build)
- Claude Code works on a feature branch, pushes, opens the PR, and never merges or enables auto-merge.
- Claude reviews each PR independently: clones it, runs the tests, checks the diff against this plan, and writes a verdict. Ayush merges with a merge commit after the verdict.
- No secrets in commits. The Gemini key lives only in the environment.
- Nothing runs `terraform plan`, `apply` or `destroy`, and nothing touches AWS.
- The demo never edits DAIL or TerraPreserve.
- Every choice not fixed here goes into `docs/DECISIONS.md`, with its reason and date.
- The README states that the code was written by Claude Code from work packages prepared under the authors' direction, as DAIL's README does.

---

## 7. Risks and how they are handled

| Risk | Handling |
|---|---|
| Gemini returns invalid patches or no patch | Shown honestly as rejected before DAIL; typed mode is the main demo |
| Free-tier rate limit, no internet or no key on demo day | Clear message on the page; typed mode needs none of them; optional Ollama fallback |
| Gemini model codes or API format change | Model and endpoint are configuration, checked at startup and recorded in `docs/DECISIONS.md` |
| `terraform validate` needs the offline provider mirror | The startup check reports a missing binary or mirror before the demo |
| Some DAIL entry point needs a change in DAIL to be used from outside | Claude Code stops and reports; the authors decide. DAIL is not patched in place |
| Someone takes demo output as research results | The label on the page and in every trace; the README says so |
| The key leaks | Environment only, gitleaks in CI, a test that scans traces and logs for it |

---

## 8. Timeline (about one week, one package at a time)

| Days | Package |
|---|---|
| 1 | L0 |
| 1–2 | L1 |
| 2–3 | L2 |
| 3–5 | L3 |
| 5–6 | L4 |
| 6–7 | L5, rehearsal, video |

---

## 9. What Ayush does before L0
1. **Create an empty GitHub repository** named `Dail-Website` (done 25 Nov 2026) (no README, licence or `.gitignore`; L0 adds them). Public is recommended, so that CI is free and the repository can be shown.
2. **Get a Gemini API key** from Google AI Studio on the free tier, without adding billing. Store it as an environment variable on the laptop only:

   ```powershell
   setx GEMINI_API_KEY "<your key>"
   ```

   Then open a new terminal so the variable is picked up. Never paste the key into a chat, a file or a commit.
3. **Check what's already on the laptop:**
   - DAIL and TerraPreserve, as before (`X:\DAIL-ref`, `X:\TerraPreserve`). L0 will tell you how to make two separate, clean read-only checkouts at the pinned tags (`dail-v1.0`, `terrapreserve-v1.0-public-r3`), so your working copies stay as they are;
   - Terraform 1.15.8 with the offline mirror;
   - Python 3.12.

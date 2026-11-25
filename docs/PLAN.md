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
6. **Two deliverables, both free.**
   - **The website:** static files only (HTML, CSS, JS, JSON, the bundled DAIL source), ready for the authors to deploy themselves on Vercel's free Hobby plan.
   - **The local tools:** Python 3.12 on Windows 11. They record the AI runs and verify everything.

   Nobody but the authors deploys anything.

---

## 2. Scope

### In scope
- A **static website** (no server code, no build step) that the authors deploy on Vercel themselves (§3.8). For local preview, use `python -m http.server --bind 127.0.0.1`.
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
- Server-side code on the website other than the single Gemini proxy function of §3.9.
- Any key or secret in the repository, in the browser, in a response, or in a log. The Gemini key exists only as the Vercel environment variable `GEMINI_API_KEY`, read only by the proxy function.
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

### 3.8 The website: static, free, on Vercel (authors' decision, 26 Nov 2026)

**Why it's static.** Vercel cannot run Terraform, keep a SQLite ledger between requests, or hold a key safely on a public page. The website is therefore static files only, with two modes.

**1. Live "Beat the gate"** (the visitor types a patch; the real DAIL judges it in the visitor's browser).
- **How it works:** DAIL v1.0 is pure Python 3.12 standard library, so it runs in the browser through **Pyodide**, a WebAssembly build of CPython.
  - The site bundles DAIL's source files from the `dail-v1.0` checkout, **copied unmodified**, with DAIL's `LICENSE` and a manifest of SHA-256 hashes.
  - The website's engine calls the same DAIL entry points as the local engine.
- **Feasibility.** On 26 Nov 2026 the build chat ran DAIL v1.0's canonical pipeline under Pyodide 0.27.7 (Python 3.12) in Node:
  - it returned the same decisions and check counts as native Python: PROMOTE / ALL_REQUIRED_PROVEN with 5 checks, and REJECT / REQUIRED_CHECK_FAILED with 5 checks;
  - it took under 1 second;
  - Pyodide's `sqlite3` package could not be fetched in that sandbox, so the SQLite-backed orchestrator path in the browser is **not yet verified**. Package C must verify it first.
- **Ledger:** an in-memory SQLite store per browser tab. A promotion advances the tab's trusted state; reloading the page starts over.
- **Pyodide** is self-hosted: the pinned release's runtime files and its `sqlite3` package are copied into `site/vendor/pyodide/<version>/` with SHA-256 hashes, so the site has no runtime CDN dependency and works on networks that block CDNs.
- **Honest limit:** `terraform validate` cannot run in a browser. In live mode, admission is DAIL's own parser and patch validator only. The page says so plainly next to every live decision: "Terraform validation is not run in the browser."

**2. Replays** (guaranteed to work).
- Runs recorded on the authors' laptop with the local engine, including Gemini-generated fixes and the `terraform validate` gate, are stored as JSON traces in the site and shown in the same three-zone layout.
- The Gemini key never leaves the laptop.

**If the browser check fails** (package C's first step), live mode is dropped and the site ships with replays only. The decision is recorded in `docs/DECISIONS.md`.

### 3.9 The AI loop on the website (authors' decisions, 26 Nov 2026; package D)

This section amends §2 and §3.8. The design of the website is §3.7 (Mint and tomato).

- **AI-first.** A visitor asks for a fix in plain words, Gemini proposes a patch, DAIL judges it in the browser, and when DAIL rejects it Gemini retries with DAIL's reason, up to 3 attempts in total. It stops at the first PROMOTE; after 3 failures the trusted state is unchanged.
- **The proxy.** One Vercel Python function, `api/propose.py`, reads the authors' key from the Vercel environment variable `GEMINI_API_KEY`, builds DAIL's own repair prompt (`dail-repair-prompt-3`) with the bundled DAIL, adds a clearly separated demo addendum (the visitor's text as untrusted text; on a retry, DAIL's reason), calls Gemini, and returns only the reply text, the model name and the token counts. It accepts only a fixed request, checks the origin and an optional passcode, and never puts the key in a response, an error or a log. `python -m dail_demo serve` runs the same proxy and the site on `127.0.0.1` only.
- **DAIL judges in the browser.** Each reply goes through DAIL's response parser, DAIL's patch validator and the orchestrator in the tab (C, and target-only A on the same patch). A reply refused before DAIL is a failed attempt. Terraform validation is not run in the browser, and the page says so.
- **Plain language.** Fixed texts describe what DAIL returned (four health pills, decision sentences, change verbs); they never decide anything. Every technical detail stays available under "DAIL's evidence".
- **Tabs.** Ask the AI, Write your own fix (typed patches, no retry loop), Replays.

### 3.7 Visual design: Mint and tomato (authors' decision, 26 Nov 2026; replaces the Neo-Brutalist design)

#### 4.1 Principles
- A **friendly, confident, modern** look: Poppins, a mint background, white cards with ink borders and **hard (unblurred) offset shadows**, rounded corners, and tomato for actions.
- **Like a chat app:** the first screen is almost empty, with one big prompt box. After asking, the page becomes a **conversation thread**.
- **No background animation, no gradients, no glass or blur, no emoji, no stock illustrations, no dark theme.** No CloudShield name.
- **Every colour has exactly one meaning** (4.2). Never use colour alone: every status also carries a word or ✓ / ✕ / ?.

#### 4.2 Colour tokens (CSS custom properties in `site/assets/css/dail.css`; no other colours)

| Token | Value | Meaning, and the only places it is used |
|---|---|---|
| `--mint` | `#DDF2E6` | Page background |
| `--mint-soft` | `#F1FAF5` | Card footers, quiet surfaces, code backgrounds |
| `--mint-hover` | `#C6EAD6` | Hover on chips and secondary buttons |
| `--white` | `#FFFFFF` | Cards, the prompt box, pills |
| `--ink` | `#0D1B2A` | Text, borders, hard shadows, the "You" bubble, active tab |
| `--ink-muted` | `#48566A` | Secondary text on white; `#33445A` on mint (`--ink-muted-on-mint`) |
| `--tomato` | `#FF5A36` | **Brand and action only:** the Ask button, the logo mark, the "AI" highlight in the headline, the "You" bubble's shadow. Never a status |
| `--tomato-soft` | `#FFD9CF` | The risky suggestion chip, the "untrusted proposal" stripe on Gemini cards, the retry banner |
| `--pass` | `#0E8A5F` | PASS, PROMOTE, "holds": dots, the PROMOTE stamp, ✓ |
| `--pass-soft` | `#CFEFDD` | PASS pill backgrounds (with ink text) |
| `--fail` | `#C0262D` | FAIL, REJECT, "broken": dots, the REJECT stamp, ✕ (crimson, deliberately darker than tomato) |
| `--fail-soft` | `#FBD9D9` | FAIL pill backgrounds (with ink text) |
| `--marker` | `#FFD60A` | "Re-checked by DAIL" (affected) only: stage 03 and the impact tags |
| `--carry` | `#2340E0` | "Carried forward" only: dot, tag border |
| `--carry-soft` | `#DCE3FF` | Carried-forward tag background (ink text) |

- **UNKNOWN / UNSUPPORTED / UNCERTAIN:** an ink-outlined pill on white, with "?" and the word. No new colour.
- **Text on colour:**
  - ink on mint, white, mint-soft, tomato, tomato-soft, marker, the soft tints;
  - white only on `--ink`, `--fail` and `--pass` at 24 px or larger (stamps, large buttons).
- **Contrast:** compute the ratio of every text/background pair used and list them in DECISIONS. Body text ≥ 4.5:1, large text (≥ 24 px, or ≥ 18.66 px bold) ≥ 3:1. Fix any failure before the PR.

#### 4.3 Type
- **Poppins** (OFL), weights 400, 500, 600, 700, 800, and **IBM Plex Mono** (OFL), 400 and 500. Self-hosted `woff2` in `site/assets/fonts/`, with the OFL texts. `font-display: swap`, system fallbacks.
- **Remove Archivo and Instrument Serif** and their files.
- **Scale (px):**

  | Role | Size and weight |
  |---|---|
  | display | 72 / 800 / tracking −0.03em (first-screen headline) |
  | h2 | 40 / 800 |
  | h3 | 28 / 700 (the decision sentence: 30 / 600) |
  | lead | 22 / 500 |
  | body | 18 / 400 |
  | small | 15 / 500 |
  | meta | 13 / 500–600 (only for secondary labels) |
  | mono | 13–15 |

- Nothing that matters is smaller than 15 px.
- Mono is used **only** for resource names, ids, hashes, raw DAIL lines, the model name and code.

#### 4.4 Shape, borders, shadows
- **Radii:**
  - cards and the prompt box: 22 px;
  - buttons and tab group: 14 px;
  - tabs inside the group: 10 px;
  - chips: 12 px;
  - pills and tags: 999 px;
  - the logo mark: 10 px.
- **Borders:** 3 px ink on the prompt box, the DAIL card and the primary buttons; 2 px ink on everything else.
- **Shadows** (hard, never blurred):

  | Element | Shadow |
  |---|---|
  | Prompt box and DAIL card | `10px 10px 0 var(--ink)` |
  | Gemini card | `8px 8px 0 var(--ink)` |
  | Primary button | `5px 5px 0 var(--ink)` |
  | "You" bubble | `5px 5px 0 var(--tomato)` |

- **Buttons press physically:** on `:active` they move by the shadow offset, and the shadow drops to 0.
- **Focus:** a visible 3 px `--carry` outline, offset 3 px, on every focusable element.

#### 4.5 Layout and screens

**Global header** (84 px tall on desktop):
- **Left:** the logo mark (34 px tomato square, 2 px ink border, "D" in ink 800), "DAIL Live" (Poppins 800, 24 px), and a "Demo" pill (ink outline). Hovering or focusing "Demo" shows: "Demo, not part of the DAIL evaluation."
- **Right:** a tab group (white, 2 px ink border, radius 14) with **Ask the AI** (active: ink background, white text), **Write your own fix** and **Replays**. Then a **Presenter** toggle and a **Ledger** button.

**Screen 1: Ask** (before the first request). Match `docs/design/Main.dc.html` (desktop) and `docs/design/Phone.dc.html` (phone). A centred column, 820 px wide, about 150 px below the header, gap 26 px:
1. **Tagline pill:** "AI writes the fix · DAIL proves it is safe". White, 2 px ink border, 14 px / 600.
2. **h1:** "What should the AI fix?", with "AI" on a tomato block (radius 14, padding 0 12 px).
3. **Health pills:** the four pills of section 3 for the current trusted state. White, 2 px ink border, with a 10 px status dot (`--pass`, `--fail`, or "?" for uncertain).
4. **The prompt box:**
   - a white card with a 3 px ink border, radius 22 and the 10 px hard shadow;
   - the label "Your request to Gemini" (13 / 600, ink-muted);
   - a textarea: Poppins 24 / 1.4, 2 rows, auto-growing to 6;
   - a footer bar on `--mint-soft` with a 2 px ink top border, holding:
     - the **Scenario** select ("canonical" plus the curated scenarios, in plain names);
     - the mono meta "<model> · judged by DAIL v1.0";
     - on the right, the **Ask →** button: tomato, ink text, 3 px border, 5 px shadow.
   - **Enter submits; Shift+Enter adds a new line.**
5. **Suggestion chips** (white, 2 px ink, radius 12): "Close the public SSH port", "Make the database private", and "Close SSH and tidy up the database rules · risky" on `--tomato-soft`. Clicking one fills the box; it does not send.
6. **Footer note** (13 px, ink-muted on mint): "Sent to Google Gemini (free tier; Google may use it to improve its products). Every decision comes from DAIL, not the AI. Demo, not part of the DAIL evaluation."

**Screen 2: The thread** (after Ask). Match `docs/design/Reject.dc.html`, `Promote.dc.html` and `PhoneThread.dc.html`. The header gains, centred, the health pills of the **current** trusted state and "Trusted state vN". Content is a centred column, 840 px wide, messages with a 24 px gap, in order:
1. **"You" bubble:** right-aligned, at most 560 px, ink background, white 20 px text, radius 22 (bottom-right corner 6 px), tomato hard shadow. The label "You" above it (13 / 600).
2. **Gemini card**, one per attempt:
   - white, 2 px ink border, radius 22, 8 px shadow;
   - a 14 px **untrusted stripe** in `--tomato-soft` down its left edge, with the vertical label "UNTRUSTED" (11 / 700, letter-spaced) for screen readers too;
   - header: "Gemini · attempt n" (15 / 700), and on the right "a proposal, untrusted until DAIL says so" (15 / 500, ink-muted);
   - a list of changes: verb tag (ink outline pill, 13 / 700), then the plain noun, then the short name in mono;
   - **Show the code:** expands a unified diff in a `--mint-soft` mono box with `+` and `−` lines. Added lines `--pass-soft` background, removed lines `--fail-soft`, ink text in both;
   - **while Gemini is writing:** the card shows "Gemini is writing a fix" and three 10 px ink squares blinking in sequence (the only looping animation; off under reduced motion).
3. **DAIL card:** white, **3 px** ink border, radius 22, 10 px shadow, padding 24.
   - **Header:** "DAIL · checked in your browser" (15 / 700), and on the right "N checks · M carried forward" (mono 13).
   - **Five-step bar:** one row of five equal cells inside a 2 px ink frame (radius 14):

     | Cell | Content |
     |---|---|
     | 01 | "Valid patch" (or "Refused") |
     | 02 | "N resources changed" |
     | 03 | "N rules re-checked" (on `--marker`) |
     | 04 | "All checks passed" or "N check(s) failed" |
     | 05 | "Decided" (ink background, white text) |

     Each cell shows its number at 28 / 800. The cells fill in one by one as DAIL reports each stage: a step animation of 150 ms per cell, none under reduced motion.
   - **Verdict row:**
     - the **stamp:** 3 px ink border, radius 14, rotated −4°, 8 px hard shadow, "PROMOTE" on `--pass` or "REJECT" on `--fail`, white Poppins 800 at 64 px, with "Decided by DAIL" (13 / 600) under it. It lands with one 160 ms scale from 1.15 to 1 (none under reduced motion);
     - beside it, the decision sentence (30 / 600) and DAIL's raw line in mono 13 (ink-muted).
   - **Card footer** (2 px ink top border):
     - the comparison line, with "accepted" or "rejected" in an outlined pill (`--pass` border if accepted, `--fail` border if rejected; ink text);
     - right: **DAIL's evidence ↓**;
     - on PROMOTE also: the mini ledger "v0 → v1", each state a 2 px ink pill with the short hash in mono, the new one with a 4 px `--pass` hard shadow, and a **Verify chain** button that shows DAIL's own result text.
   - **Live mode only:** "Terraform validation is not run in the browser." (13, ink-muted).
4. **Retry banner** (after a REJECT, before the next Gemini card): a `--tomato-soft` strip with a 2 px ink border, radius 14: "↻ **Attempt 2 of 3.** DAIL's reason was sent back to Gemini."
5. **Earlier attempts collapse** to one row each when a later attempt starts: a white row, 2 px ink border, radius 14, holding the outlined status pill "Attempt 1 · Reject" (`--fail` border, ink text), the decision sentence, and "Open ↓".
6. **The prompt box docks** at the bottom (sticky, 840 px wide, same style at a smaller scale):
   - label "Next request";
   - placeholder "Ask for another fix. It starts from trusted state vN.";
   - disabled, with a **Stop** button, while an attempt is running.

**DAIL's evidence** (collapsed by default, inside the DAIL card; match `docs/design/Evidence.dc.html`):
- **What changed:** every changed resource with its change type and flags (mono name, plain verb).
- **What it affects:**
  - every affected invariant, with a `--marker` tag "re-checked" and its dependency path in mono (for example `app_to_db_5432 → security_group.db → db_instance.database`);
  - every carried-forward invariant, with a `--carry-soft` tag "carried forward" (`--carry` border);
  - uncertainty reasons, if any.
- **Every check:** target, verifier, then a ✓ PASS pill (`--pass-soft`, ink text) or ✕ FAIL pill (`--fail-soft`), or "? UNKNOWN" / "? UNSUPPORTED" (outlined), then the reason.
- **Ids and hashes:** candidate, parent state, state hash.

**Screen 3: Write your own fix** (match `docs/design/OwnFix.dc.html`). The same thread, but the first message is an **editor card** in place of the "You" bubble and the Gemini card:
- white, 2 px ink, radius 22;
- file tabs as pills;
- a mono textarea on `--mint-soft`;
- quick-fill buttons "Fill: the safe repair" and "Fill: the repair that breaks the database path";
- **Submit to DAIL →** (the tomato primary button).

DAIL's card, the comparison and the ledger then work exactly as above. No retry loop.

**Screen 4: Replays** (match `docs/design/Replays.dc.html`).
- A grid of run cards: white, 2 px ink, radius 22, 8 px shadow. Each shows:
  - the scenario's plain name;
  - the source ("Gemini, recorded <date>", "Reference patch", "Typed");
  - the decision as an outlined pill (`--pass` or `--fail` border);
  - "Open".
- Opening a card renders the **same thread** from the trace (attempts, cards, evidence), with the label "Recorded run" in place of the prompt box.

**Ledger drawer** (the header button; match `docs/design/Ledger.dc.html`):
- a right-hand panel (white, 3 px ink left border) listing every trusted state of the tab: version, the four status dots, state hash, parent link;
- **Verify chain** at the top.

**Presenter mode:** multiplies the type scale by 1.25, hides the code by default, and keeps the DAIL card fully visible at 1366×768.

**Phone (≤ 600 px):**
- a single column with a 16 px gutter;
- header: logo and "DAIL Live", plus a **Menu** button that opens the tabs, Presenter and Ledger;
- the first-screen headline at 44 px;
- the health pills wrap;
- suggestion chips scroll horizontally inside their own container. The page never scrolls sideways;
- the prompt box docked at the bottom;
- in the five-step bar, the cells show only the number and a ✓ or ✕;
- the stamp at 44 px;
- the ledger drawer becomes a bottom sheet.

#### 4.6 Motion (functional only)
**Allowed:**
- the button press;
- the stage cells filling;
- the stamp landing;
- the typing squares;
- a new ledger pill sliding in (200 ms);
- expand and collapse (150 ms).

**Not allowed:**
- background or ambient animation;
- parallax;
- floating shapes;
- hover animations beyond the colour change.

All motion is off under `prefers-reduced-motion`.

#### 4.7 Accessibility
- Real `<button>`, `<a href>`, `<label>` + `<textarea>` / `<select>`.
- Every control reachable by keyboard, with a visible focus outline.
- An `aria-live="polite"` region announces "Gemini proposed a fix", "DAIL: rejected. <sentence>", "Attempt 2 of 3", and "DAIL: promoted. <sentence>".
- The thread is an `<ol>` of messages, each an `<article>` with an `aria-label` ("Your request", "Gemini, attempt 1", "DAIL's decision on attempt 1").
- Stamps and pills always contain words.
- Touch targets ≥ 44 px.

---

## 4. What the user sees (the flow)

1. **Start.** On the website: open the page. On the laptop: `python -m dail_demo check` verifies the pins, Terraform and the Gemini key before recording runs.
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

**Fast track (authors' decision, 26 Nov 2026):** after L0 (PR #1), the remaining packages are built as two PRs: **B = L1 + L2** (local engine and inputs) and **C = L3 + L4 + L5** (the static website of §3.8, its in-browser sessions, and the recorded replays). The acceptance criteria below apply, as amended by §3.8; each combined PR must meet the criteria of all its packages.

| # | Package | Delivers | Accepted when |
|---|---|---|---|
| **L0** | **Bootstrap** | The repo skeleton (layout, `README`, `LICENSE`, `.gitignore`, CI with tests and gitleaks); this plan as `docs/PLAN.md`; `docs/DECISIONS.md`; the startup checks for the DAIL tag, the TerraPreserve tag, `DAIL_LIVE_DATA` and Terraform | CI green. The startup check refuses a DAIL checkout that is not at `dail-v1.0` or not clean (tested). No secret in the repo |
| **L1** | **Engine** | `python -m dail_demo evaluate --scenario <id> --patch <dir>`: establishes the baseline with DAIL, runs the candidate through DAIL (C) and target-only (A), and writes a trace | On the canonical example, the results equal DAIL's own fixture expectations: the safe repair is PROMOTE, the breaking repair is REJECT, blocked by INV-FUNC-001, and DAIL runs 5 checks against A's 3. Proven by tests that compare against DAIL's `expected.json`, not against numbers typed into the demo |
| **L2** | **AI and typed input** | `GeminiProvider`; generation through DAIL's `Generator`, prompt, parser, patch validator and the `terraform validate` gate; up to 3 attempts; typed-patch input from edited files | Tested with DAIL's `FakeProvider` (no network in CI): an invalid response never reaches the orchestrator; a valid one does. Missing key, 429 and time-out give clear errors. The key appears in no file, log or trace (tested) |
| **L3** | **Website** | The static site of §3.8 in `site/`: scenario picker, configuration view, editor (live mode), replay viewer, five stages, comparison panel, ledger, the "Demo, not part of the DAIL evaluation" label | Live mode gives the same decisions in the browser as the local engine on the canonical patches and the curated scenarios (tested headless), or is dropped as §3.8 says. Replays render every recorded trace. It works in Chrome and Edge. No server code and no secret in `site/`. It follows §3.7, with screenshots and contrast ratios in the PR |
| **L4** | **Sessions and ledger** | In the browser tab: promotion advances the tab's trusted state; ledger view with hash links; reset | Three patches in a row (promote, reject, promote) leave exactly DAIL's lineage. The ledger's hash chain verifies with DAIL's own check |
| **L5** | **Recordings** | `python -m dail_demo record`: runs the curated scenarios (fixed and Gemini patches) locally and writes the traces into `site/runs/`; `docs/DEMO_SCRIPT.md`; `docs/DEPLOY.md` (how the authors deploy `site/` on Vercel's free plan) | Every trace in `site/runs/` comes from a real local run and contains no key. The site replays each one to the recorded decisions |

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

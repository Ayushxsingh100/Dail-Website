# DAIL Live

DAIL Live is a demo in which an AI (Google Gemini, free tier) or a person proposes a fix to a Terraform configuration, and the real, released DAIL decides, stage by stage, whether to promote it. Beside DAIL's decision it shows what target-only checking would have decided on the same patch.

**Status:** packages L0, B, C and D are built: the local engine, and the AI-first website in `site/`. The authors deploy the website themselves ([`docs/DEPLOY.md`](docs/DEPLOY.md)); the demo script is [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

**The website** (PLAN §3.9) works like a chat:
- **Ask the AI:** you ask for a fix in plain words. Gemini proposes a patch (an untrusted card); the released DAIL v1.0, unmodified, judges it in your browser (self-hosted Pyodide, about 17 MB) and shows its decision as a stamp, one plain sentence, DAIL's raw reason and what a normal, target-only checker would have decided. When DAIL rejects it, the page sends DAIL's reason back to Gemini and it tries again, up to 3 attempts. A promotion adds a trusted state to the tab's ledger.
- **Write your own fix:** your edit goes to the same DAIL, with no retry.
- **Replays:** runs recorded on the authors' laptop with `terraform validate`.

Every technical detail stays one click away under **DAIL's evidence**. Terraform validation is not run in the browser; the page says so under every live decision. The Gemini key lives only in the server function (`api/propose.py` on Vercel, or `serve` locally) and never reaches the browser.

**The design** is "Mint and tomato" (PLAN §3.7): Poppins and IBM Plex Mono, a mint background, white cards with ink borders and hard shadows, tomato for actions, and no background animation. The approved mock-ups are in [`docs/design/`](docs/design/); screenshots of the built site, at 1440×900, 1366×768 (presenter) and 390×844, are in [`docs/screenshots/`](docs/screenshots/).

Preview everything locally on http://127.0.0.1:8000/:

```powershell
py -3.12 -m dail_demo serve
```

**Demo, not part of the DAIL evaluation.** The output of DAIL Live is a demonstration. It is not part of the DAIL evaluation; the research results are in DAIL's repository and paper.

## Links

- **DAIL:** https://github.com/Ayushxsingh100/DAIL, doi:[10.5281/zenodo.24495207](https://doi.org/10.5281/zenodo.24495207)
- **TerraPreserve:** https://github.com/Ayushxsingh100/terrapreserve, doi:[10.5281/zenodo.24509952](https://doi.org/10.5281/zenodo.24509952)
- **The build plan:** [`docs/PLAN.md`](docs/PLAN.md); decisions: [`docs/DECISIONS.md`](docs/DECISIONS.md)

## Setup on Windows (PowerShell)

DAIL Live reads DAIL and TerraPreserve from two clean, read-only checkouts at the pinned tags. Make them with `git worktree`, so your working copies stay untouched:

```powershell
git -C X:\DAIL-ref fetch --tags
git -C X:\DAIL-ref worktree add X:\pins\dail-v1.0 dail-v1.0
git -C X:\TerraPreserve fetch --tags
git -C X:\TerraPreserve worktree add X:\pins\terrapreserve-r3 terrapreserve-v1.0-public-r3
setx DAIL_ROOT X:\pins\dail-v1.0
setx TERRAPRESERVE_ROOT X:\pins\terrapreserve-r3
setx DAIL_LIVE_DATA X:\dail-live-data
# DAIL_TERRAFORM_MIRROR: the same mirror DAIL's main run used
# GEMINI_API_KEY: set with setx by the user; never written to any file
```

Then open a new terminal and run:

```powershell
py -3.12 -m dail_demo check
```

It prints one `PASS`, `FAIL` or `WARN` line per check (Python 3.12, the two pinned checkouts, the data directory, Terraform v1.15.8, the provider mirror, the Gemini key) and exits with code 1 if any check fails. A missing Gemini key is only a warning: the AI mode is then unavailable, and the typed-patch mode still works.

## Commands

`evaluate` and `generate` print a short summary and write a JSON trace (`dail-live-trace/1`) to `DAIL_LIVE_DATA\traces\`, never into a repository. Only `record` writes into `site/runs/`, after checking that a trace holds no key and no local path.

```powershell
py -3.12 -m dail_demo check                                              # the startup checks
py -3.12 -m dail_demo evaluate --scenario canonical --patch safe        # DAIL's canonical safe repair
py -3.12 -m dail_demo evaluate --scenario canonical --patch regression  # the repair that breaks INV-FUNC-001
py -3.12 -m dail_demo evaluate --scenario tp-v1-F4-0092 --patch fixed   # a curated TerraPreserve scenario's own step 1
py -3.12 -m dail_demo evaluate --scenario canonical --patch C:\path\to\edited-config   # a typed patch
py -3.12 -m dail_demo generate --scenario canonical --attempts 3        # Gemini proposes, DAIL decides
py -3.12 -m dail_demo bundle                                             # rebuild site/vendor/
py -3.12 -m dail_demo record                                             # re-record site/runs/
```

- `evaluate` runs one candidate under DAIL (condition C) and under target-only checking (condition A) on the same parent, and shows both decisions and check counts.
- A typed patch is admitted only after `terraform validate` (it needs Terraform 1.15.8 and `DAIL_TERRAFORM_MIRROR`) and DAIL's own patch validator; a refused one never reaches DAIL.
- `generate` needs `GEMINI_API_KEY` (free tier) and network; without them it says so and stops. The key is sent only in a request header and is never written anywhere. The curated scenarios are listed in `dail_demo/scenarios.py`.

## What is never done

- No AWS: no account, no credentials, no API call.
- No `terraform plan`, `apply` or `destroy`.
- No paid API, paid model or paid cloud.
- No key in the repository, the browser, a response or a log; the only server code is the Gemini proxy `api/propose.py` (PLAN §3.9). `serve` binds to `127.0.0.1` only.

## How it was built

The code was written by an AI coding assistant (Claude Code) from work packages prepared under the authors' direction; every change is reviewed before it is merged.

The browser tests use Node and Playwright, in tests and CI only (D-21): `npm ci` in `tests/browser`.

## Licence and credits

Apache-2.0. See [`LICENSE`](LICENSE). The website also serves DAIL (Apache-2.0), TerraPreserve scenarios (CC-BY-4.0, TerraGoat-derived files Apache-2.0), Pyodide (MPL-2.0) and two OFL fonts (Poppins, IBM Plex Mono); see [`site/credits.html`](site/credits.html).

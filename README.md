# DAIL Live

DAIL Live is a local demo in which an AI (Google Gemini, free tier) or a person proposes a fix to a Terraform configuration, and the real, released DAIL decides, stage by stage, whether to promote it. Beside DAIL's decision it shows what target-only checking would have decided on the same patch.

**Status:** Under construction (package B of the fast track L0, B, C; see `docs/PLAN.md` §5). The local engine and inputs work from the command line (below); the static website (package C, PLAN §3.8) is not built yet.

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

All commands print a short summary and write a JSON trace (`dail-live-trace/1`) to `DAIL_LIVE_DATA\traces\`, never into a repository.

```powershell
py -3.12 -m dail_demo check                                              # the startup checks
py -3.12 -m dail_demo evaluate --scenario canonical --patch safe        # DAIL's canonical safe repair
py -3.12 -m dail_demo evaluate --scenario canonical --patch regression  # the repair that breaks INV-FUNC-001
py -3.12 -m dail_demo evaluate --scenario tp-v1-F4-0092 --patch fixed   # a curated TerraPreserve scenario's own step 1
py -3.12 -m dail_demo evaluate --scenario canonical --patch C:\path\to\edited-config   # a typed patch
py -3.12 -m dail_demo generate --scenario canonical --attempts 3        # Gemini proposes, DAIL decides
```

- `evaluate` runs one candidate under DAIL (condition C) and under target-only checking (condition A) on the same parent, and shows both decisions and check counts.
- A typed patch is admitted only after `terraform validate` (it needs Terraform 1.15.8 and `DAIL_TERRAFORM_MIRROR`) and DAIL's own patch validator; a refused one never reaches DAIL.
- `generate` needs `GEMINI_API_KEY` (free tier) and network; without them it says so and stops. The key is sent only in a request header and is never written anywhere. The curated scenarios are listed in `dail_demo/scenarios.py`.

## What is never done

- No AWS: no account, no credentials, no API call.
- No `terraform plan`, `apply` or `destroy`.
- No paid API, paid model or paid cloud.
- No server code and no key in the website: it is static files only (PLAN §3.8); a local preview binds to `127.0.0.1` only.

## How it was built

The code was written by an AI coding assistant (Claude Code) from work packages prepared under the authors' direction; every change is reviewed before it is merged.

## Licence

Apache-2.0. See [`LICENSE`](LICENSE).

# DAIL Live

DAIL Live is a local demo in which an AI (Google Gemini, free tier) or a person proposes a fix to a Terraform configuration, and the real, released DAIL decides, stage by stage, whether to promote it. Beside DAIL's decision it shows what target-only checking would have decided on the same patch.

**Status:** Under construction (L0 of L0–L5). Nothing is runnable yet except `python -m dail_demo check`.

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

## What is never done

- No AWS: no account, no credentials, no API call.
- No `terraform plan`, `apply` or `destroy`.
- No paid API, paid model or paid cloud.
- Nothing is served beyond `127.0.0.1`.

## How it was built

The code was written by an AI coding assistant (Claude Code) from work packages prepared under the authors' direction; every change is reviewed before it is merged.

## Licence

Apache-2.0. See [`LICENSE`](LICENSE).

# Decision log

Every choice not fixed in `docs/PLAN.md` is recorded here, with its reason and date (PLAN §6). Entries are added by PR and never rewritten; a later entry may supersede an earlier one.

| ID | Date | Decision | Reason | Source |
|---|---|---|---|---|
| D-1 | 2026-11-26 | DAIL is read from a checkout at tag `dail-v1.0`, given by `DAIL_ROOT`, outside this repository, and is never modified. | The demo must show the released DAIL's own decisions, unchanged. | PLAN §3.1 |
| D-2 | 2026-11-26 | TerraPreserve is read from a checkout at tag `terrapreserve-v1.0-public-r3`, given by `TERRAPRESERVE_ROOT`, checked the same way. | The scenarios must come from the pinned public release. | PLAN §3.1 |
| D-3 | 2026-11-26 | Python 3.12 standard library only: no third-party runtime dependency, no frontend build step. | The same rule as DAIL; nothing to install, works offline. | PLAN §3.2 |
| D-4 | 2026-11-26 | Gemini free tier only. The key lives only in the environment variable `GEMINI_API_KEY` and is never written to a file, log, trace or page. | Zero cost; no secret in the repository. | PLAN §3.5 |
| D-5 | 2026-11-26 | The first commit (`docs/PLAN.md` only) went directly to `main` because the repository was empty; everything else goes through PRs. | A PR needs a base branch to target. | L0 work package §1 |
| D-6 | 2026-11-26 | The Terraform provider mirror is given by `DAIL_TERRAFORM_MIRROR`, the variable DAIL's own validate gate uses (`experiments/terraform_validate.py`), rather than a new variable. | One mirror, one variable, for DAIL and the demo. | L0 work package §3 |
| D-7 | 2026-11-26 | The tag check uses `git tag --points-at HEAD` and requires the pinned tag in the list, plus an empty `git status --porcelain` (untracked files count as dirty). | PLAN §3.1 names `git describe --tags --exact-match`; the L0 work package fixes `tag --points-at`. Both test the same condition; `--points-at` lists every tag at HEAD, so the failure message can name them all. | L0 work package §3 |
| D-8 | 2026-11-26 | `DAIL_ROOT` and `TERRAPRESERVE_ROOT` must be the top level of a git checkout; a subdirectory of a repository is rejected. | A subdirectory would pass the git commands but is not the pinned checkout. | L0 implementation |
| D-9 | 2026-11-26 | The location of `DAIL_LIVE_DATA` is checked before the directory is created, so a forbidden path never leaves a new directory inside a repository (which would also make a pinned checkout dirty). | Checking first has no side effect on failure. | L0 implementation |
| D-10 | 2026-11-26 | A `GEMINI_API_KEY` that is empty or only whitespace is treated as unset (WARN). | Such a value cannot be a key; treating it as set would only fail later. | L0 implementation |

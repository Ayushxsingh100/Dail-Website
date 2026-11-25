# CLAUDE.md: standing rules for every session

**Read `docs/PLAN.md` and `docs/DECISIONS.md` at the start of every session.** `docs/PLAN.md` is the authority for this build. If a work package and `docs/PLAN.md` conflict, stop and ask.

## Hard rules

1. **Never merge, never enable auto-merge, never create a tag or a release.** Push the branch and open the PR, then stop. The user merges after an external review verdict.
2. **Every change goes through a PR** from a `feature/<package>` branch to `main`.
3. **No secrets, ever.**
   - The value of `GEMINI_API_KEY` may be read only by the process that calls Gemini (the proxy function, or the local `serve`, `generate` and `record`) and by the local leak scan. It is never printed, logged, written, returned or committed.
   - Never create a `.env` file with real values.
4. **Never run** `terraform plan`, `apply` or `destroy`. Use no AWS credentials and make no AWS calls. In L0, the only Terraform command allowed is `terraform version`.
5. **Never modify DAIL or TerraPreserve.** They are read-only inputs. Never import from DAIL's `tests/` package; later packages may import only DAIL's `core/`, `llm/`, `evidence/` and `experiments/`.
6. **Python 3.12 standard library only.** No third-party runtime dependency, no frontend build step.
7. **Honest reporting.** Never claim a command ran if it did not (write `NOT RUN — <reason>`). Quote real output. Never change a test to make it pass.
8. **If a needed DAIL entry point cannot be used without changing DAIL, stop and report; never patch DAIL** (PLAN §3.3).

## Branches and commits

- Branch: `feature/<package>` (`feature/b`, `feature/c`; fast track, D-12).
- Commit messages: `<Package> step <k>: <what> (PLAN §x)` (for example `B step 3: the engine (PLAN §3.3)`).

## Not allowed (PLAN §2, verbatim)

- Scanning or connecting to any real cloud account; any AWS API call; any AWS credentials.
- `terraform plan`, `apply` or `destroy`. The only Terraform command allowed is the offline `terraform validate` (with `init -backend=false` and the local provider mirror), as in DAIL.
- Risk scoring, findings dashboards, multi-account or user-account features, logins.
- CloudShield AI name or branding anywhere.
- Paid APIs, paid models or paid cloud.
- Server-side code on the website other than the single Gemini proxy function of §3.9.
- Any key or secret in the repository, in the browser, in a response, or in a log. The Gemini key exists only as the Vercel environment variable `GEMINI_API_KEY`, read only by the proxy function.
- New safety logic. The demo may not decide anything itself; it only calls DAIL and displays what DAIL returns.
- Committing any secret, including the Gemini API key.

## The UI rule

PLAN §3.7 is binding for any page, style, font or animation:
- use only its palette tokens, typefaces, grid, borders, shadows and motion rules;
- self-host the fonts (no CDN);
- use no colour outside the token table and give no colour a second meaning;
- add no rounded cards, gradients, blur, glass, emoji, dark or neon theme, or CloudShield branding;
- any deviation needs a `docs/DECISIONS.md` entry approved by the user **before** it is built;
- every UI PR attaches screenshots at 1366×768 and at phone width, plus the contrast ratios.

## End-of-package report (end every package with exactly this)

1. Commits (hash and message), branch, PR number, CI status.
2. Files created, with line counts.
3. The `check` output on this machine, verbatim.
4. Test results: counts, and the quoted failures from the package's "can it fail" checks.
5. Each item of the work package: IMPLEMENTED or NOT DONE, with evidence.
6. Deviations from the work package or `docs/PLAN.md`, and open questions.

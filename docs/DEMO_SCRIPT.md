# DAIL Live: the 3-minute demo

**Before you start:** open the site with `?mode=live`, so DAIL is already loaded when you begin (about 6 s, 16.8 MB; or press **Live** a minute early). Turn on **Presenter mode** for a projector. Pick the scenario **canonical**. Say once, early: *"This is a demo, not part of the DAIL evaluation; the results are in the paper."*

## 1. The problem (30 s)

- Point at the ledger: **v0**, DAIL's baseline. INV-SEC-001 is **VIOLATED**: SSH is open to the internet. The other three invariants are **PROTECTED**.
- *"An AI, or a person, proposes a fix. Most tools check only the thing being fixed. A fix can close SSH and quietly cut the app off from its database."*

## 2. Live: the fix that breaks something else (45 s)

- In the untrusted zone, press **Fill: the repair that breaks INV-FUNC-001**, then **Submit to the gate**.
- Walk the gate, 01 to 05: the patch is admitted; four resources changed; three invariants affected (yellow), INV-SEC-003 carried forward (blue); five checks, one **FAIL**: INV-FUNC-001.
- The stamp: **REJECT**.
- Point at **Opinion vs. Fact**: target-only checking says **PROMOTE** after 3 checks; DAIL says **REJECT** after 5.
- *"Same patch, same parent. Target-only would have shipped the outage."*
- Under the stamp: *"Terraform validation is not run in the browser"*. The replays show runs with the full gate.

## 3. Let the audience edit (45 s)

- Press **Fill: the safe repair** and **Submit**: **PROMOTE**. A new clipping, **v1**, drops onto the ledger, linked to v0 by its hash.
- Hand over the keyboard: *"Try to sneak something past the gate."* Ideas: re-open port 22; delete the database rule; add an `output` block. A refusal before DAIL shows its reason in the untrusted zone; a REJECT leaves the ledger where it was.
- **Reset** returns to v0 at any time.

## 4. A Gemini replay (30 s)

- Press **Replays**, pick **canonical**, then the run **Gemini (gemini-3.5-flash-lite)**.
- *"Recorded on the laptop: Gemini wrote this patch; DAIL's parser, patch validator and terraform validate checked it before DAIL decided."* Show the attempt and its verdicts, then the decision.
- Optionally, **tp-v1-F8-0196**, session steps 1 and 2: step 1 is promoted; step 2 is rejected by DAIL and promoted by target-only. The break is caught at step 2.

## 5. The ledger and "Verify chain" (30 s)

- Back in **Live**, press **Verify chain**: *"DAIL rebuilds every trusted state from its store, recomputes each hash and checks every candidate's evidence chain. Change one stored hash and this fails."* The test suite proves that.
- Close: *"Every decision you saw came from the released DAIL, unmodified. This is a demo; the evaluation is in the paper."*

**If something fails on stage:** Replays need no Pyodide, but each recorded run is fetched when you pick it, so the page still needs its server (or a local preview, `docs/DEPLOY.md`, which works offline).

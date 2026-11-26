# DAIL Live: the 3-minute demo

**Before you start:** open the site a minute early, so that DAIL is loaded (about 17 MB; the **Ask →** button becomes active). For a projector, press **Presenter** (bigger type, the code hidden). Say once, early: *"This is a demo, not part of the DAIL evaluation; the results are in the paper."*

## 1. The Ask screen (20 s)

Four health pills, one red: **SSH open to the internet**. *"An app server and a database. Four things must hold; three do. We want SSH closed."*

## 2. Ask the AI (20 s)

Click the chip **Close SSH and tidy up the database rules · risky**. It fills the box; it does not send. Then **Ask →** (or Enter). *"Gemini writes the fix with DAIL's own prompt. Everything it says is untrusted."* The Gemini card shows "Gemini is writing a fix", then the plain list of changes; **Show the code ↓** if someone asks.

## 3. DAIL rejects it (45 s)

The DAIL card fills its five cells as DAIL works, in this browser tab, then the stamp lands: **REJECT**. Read the sentence: *"Rejected: the app would lose its connection to the database."* Point at the footer: **"A normal checker would have accepted this fix."** *"Checking only the SSH rule would have let this through."*

## 4. The automatic retry, which DAIL promotes (45 s)

The banner says **"Attempt 2 of 3. DAIL's reason was sent back to Gemini."** The first attempt folds into one row. Gemini's second fix arrives, DAIL checks it: **PROMOTE**. The pills in the header turn green, and the mini ledger shows **v0 → v1**. *"Same AI, one honest reason, and now a fix that holds."* Press **Verify chain**: DAIL recomputes every hash.

**The AI is live, so be ready for the other story.** If DAIL promotes the first attempt (it did in our earlier real run of this request), say *"This time the AI was careful, and DAIL proved it."* and show the rejection with step 6's backup instead.

## 5. Open DAIL's evidence (30 s)

On either card, **DAIL's evidence ↓**: what changed, what it affects (the yellow "re-checked" rows with their dependency paths, the blue "carried forward" one), every check with ✓ PASS or ✕ FAIL, and the ids and hashes. **Ledger** (top right) lists every trusted state, each linked to its parent by hash. *"Rejected fixes never enter the ledger."*

## 6. Backup, if the AI is slow or the quota is gone (any time)

The page says "The AI's free quota is used up for now. Try again later, or write your own fix." Nothing else stops working.
- **Write your own fix → Fill: the repair that breaks the database path → Submit to DAIL →**: REJECT, "Rejected: the app would lose its connection to the database.", and a normal checker would have accepted it. **Fill: the safe repair** is promoted. No network is needed once DAIL is loaded.
- Or **Replays**: the canonical regression and `tp-v1-F8-0196` step 2 are both rejected by DAIL and accepted by a normal checker; the Gemini runs are recorded real runs.

Under every live decision the page says "Terraform validation is not run in the browser." The replays were recorded with it.

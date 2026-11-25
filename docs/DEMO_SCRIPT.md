# DAIL Live: the 3-minute demo

**Before you start:** open the site a minute early, so DAIL is loaded (about 17 MB; **Ask Gemini** becomes active). Turn on **Presenter mode** for a projector. Say once, early: *"This is a demo, not part of the DAIL evaluation; the results are in the paper."*

## 1. The system (20 s)

- Step 0: *"Internet, app server, database. Four things must hold. Three do. SSH is open to the internet: that is what we want fixed."*

## 2. Ask the risky question (90 s)

- Press the chip **Close SSH and tidy up the database rules**, then **Ask Gemini**. *"An AI writes the fix, with our real prompt."*
- Step 2: read the plain list of changes. **Show the code** if someone asks.
- Step 3: the five boxes fill, then the stamp.

**The AI is live, so there are two stories. Be ready for both.**

- **If DAIL rejects:** *"Rejected: the app would lose its connection to the database."* Point at the line under it: **"A normal checker would have accepted this fix."** The page sends DAIL's reason back by itself: *"Attempt 2 of 3: DAIL's reason was sent back to the AI."* If the retry is promoted: *"Same AI, one honest reason, and now a fix that holds."*
- **If DAIL promotes the first attempt** (this happened in our one recorded run of this request): *"This time the AI was careful, and DAIL proved it. DAIL is not there to say no; it is there to know."* Then show the rejection with **Write your own fix → Fill: a fix that breaks something → Submit to DAIL**: REJECT, and "A normal checker would have accepted this fix."

## 3. Let the audience try (40 s)

- **Write your own fix**, or a new request. *"Try to sneak something past it."* A fix that cannot be read as a change to this system is turned away before DAIL, with the reason.

## 4. The proof (30 s)

- **Show DAIL's evidence:** the changes, what each one touches, every check.
- The ledger under step 3: **v0 → v1**. Click a state for its four statuses and its hash. **Verify chain:** *"DAIL recomputes every hash and checks every candidate's evidence. Change one stored hash and this fails."* (A test proves it.)

**If the AI is out of quota or offline:** the page says so. Use **Write your own fix** (no network needed once DAIL is loaded) or **Replays**: the canonical regression, and `tp-v1-F8-0196` step 2, are both rejected by DAIL and accepted by a normal checker.

Under every live decision the page says "Terraform validation is not run in the browser." The replays were recorded with it.

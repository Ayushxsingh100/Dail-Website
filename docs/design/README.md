# DAIL Live: approved mock-ups (Mint and tomato), 26 Nov 2026

These are the screens the authors approved for package D. They are design-canvas files: plain HTML with inline styles. Open them for reference only: they load `./support.js` from the design tool, which is not included, so render them by reading the markup, or simply open them in a browser (the layout and styles show without it).

**Match their look and layout. Do not copy their structure blindly.** The live site follows PLAN §3.7 and work package D, and every value it shows comes from DAIL at run time. The values in these mock-ups are DAIL's real outputs on its canonical safe and regression patches, so the live site should show the same values on those patches.

| File | Screen (D prompt §4.5) |
|---|---|
| `Main.dc.html` | Screen 1: Ask (desktop 1440×900) |
| `Reject.dc.html` | Screen 2: the thread, attempt 1 rejected, then the retry banner and Gemini writing |
| `Promote.dc.html` | Screen 2: the thread, attempt 2 promoted, with the collapsed attempt 1, mini ledger and docked prompt |
| `Evidence.dc.html` | The DAIL card with "DAIL's evidence" open |
| `OwnFix.dc.html` | Screen 3: Write your own fix ("Beat the gate") |
| `Replays.dc.html` | Screen 4: Replays |
| `Ledger.dc.html` | The Ledger drawer |
| `Phone.dc.html` | Phone: Ask (390×844) |
| `PhoneThread.dc.html` | Phone: the thread |

**Not shown in the mock-ups, but specified in the prompt:**
- presenter mode;
- the failure states (Gemini quota, refused before DAIL, 3 failed attempts);
- "Show the code" expanded;
- the scenario select open.

Style those in the same design.

"""The page in a browser, on the real ``serve`` with a fake Gemini (D package §2, §4, §6; D-21).

The fake Gemini answers the canonical regression patch first and, once DAIL's reason is in the prompt,
the safe patch; "FAIL ALWAYS", "GARBAGE" and "QUOTA" change that (``tests/browser/serve_fake.py``).
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.support import FAKE_KEY, REPO_ROOT, DataDirCase, dail_root
from tests.test_browser import BROWSER_DIR, node_ready

LOST = "Rejected: the app would lose its connection to the database."
PROMOTED = "Promoted: SSH closed to the internet, and everything that held before still holds."
ALL_FAILED = "None of the 3 fixes passed DAIL. The infrastructure was not changed."
BANNER = "↻Attempt {n} of 3. DAIL's reason was sent back to Gemini."
HOLDS = ["SSH closed (holds)", "DB port closed (holds)", "DB not public (holds)", "App reaches DB (holds)"]
START = ["SSH open to the internet (broken)", "Database port closed (holds)", "Database not public (holds)",
         "App reaches database (holds)"]  # fmt: skip


class SiteInBrowserTests(DataDirCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dail = dail_root()
        node = node_ready()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "check.json"
            done = subprocess.run(
                [node, str(BROWSER_DIR / "site.mjs"), sys.executable, "check", str(out)],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", check=False, timeout=900,
            )
            if done.returncode != 0:
                raise AssertionError(f"the page check failed:\n{done.stdout}\n{done.stderr}")
            cls.stderr = done.stderr
            cls.text = out.read_text(encoding="utf-8")
            cls.r = json.loads(cls.text)
        print(f"\n  {cls.r['browser']}; ready in {cls.r['readyMs']} ms; first load: replays "
              f"{cls.r['firstLoad_replays']}, ask {cls.r['firstLoad_ask']}", end="")

    def test_the_ask_screen(self) -> None:
        first = self.r["first"]
        self.assertEqual((first["health"], first["askScreen"], first["dock"], first["status"]), (START, True, False, None))
        for words in ("AI writes the fix · DAIL proves it is safe", "What should the AI fix?", "Your request to Gemini",
                      "Sent to Google Gemini (free tier; Google may use it to improve its products). Every decision comes "
                      "from DAIL, not the AI. Demo, not part of the DAIL evaluation."):  # fmt: skip
            self.assertIn(words, self.r["firstText"])
        for word in ("sha", "dail.verify", "aws_", "hash", "invariant", "REQUIRED_"):
            self.assertNotIn(word, self.r["firstText"])
        self.assertEqual(self.r["model"], "gemini-3.5-flash-lite · judged by DAIL v1.0")
        self.assertEqual(self.r["chipLabels"], ["Close the public SSH port", "Make the database private",
                                                "Close SSH and tidy up the database rules · risky"])  # fmt: skip
        self.assertEqual(self.r["chip"], "Close SSH and tidy up the database rules")  # a chip fills, it does not send

    def test_the_ask_screen_fits_1440_by_900(self) -> None:
        fold = self.r["askFold"]
        below = {k: v for k, v in fold["bottoms"].items() if v > fold["height"]}
        self.assertEqual(below, {}, fold)  # nothing on the Ask screen lies below 900 px
        self.assertEqual((fold["headlineLines"], fold["pillRows"], fold["footRows"], fold["chipRows"]), (1, 1, 1, 1), fold)
        self.assertLessEqual(fold["select"], 300)
        self.assertEqual(fold["placeholder"], "Describe the fix, for example: close the public SSH port")

    def test_the_untrusted_label_is_never_clipped(self) -> None:
        stripes = self.r["stripes"]  # the writing card, then the Gemini card of every replay
        self.assertTrue(all(count >= 1 for count, _, _ in stripes), stripes)
        self.assertEqual([clipped for _, clipped, _ in stripes], [0] * len(stripes), stripes)

    def test_the_risky_chip_comes_first_on_a_phone(self) -> None:
        self.assertEqual(self.r["phoneChips"], ["Close SSH and tidy up the database rules · risky",
                                                "Close the public SSH port", "Make the database private"])  # fmt: skip
        self.assertEqual(self.r["chipLabels"][2], "Close SSH and tidy up the database rules · risky")  # desktop order

    def test_the_loop_rejects_sends_the_reason_and_promotes_the_retry(self) -> None:
        self.assertEqual(self.r["writing"], "Gemini is writing a fix")
        at = self.r["atBanner"]
        self.assertEqual(at["banners"], [BANNER.format(n=2)])
        loop = self.r["loop"]
        self.assertEqual(loop["kinds"], ["you", "collapsed", "banner", "gemini", "dail"])
        self.assertEqual(loop["collapsed"], [f"Attempt 1 · Reject{LOST}Open ↓"])
        last = loop["last"]
        self.assertEqual((last["stamp"], last["by"], last["sentence"]), ("PROMOTE", "Decided by DAIL", PROMOTED))
        self.assertEqual(last["cells"], ["Valid patch", "2 resources changed", "3 rules re-checked", "All checks passed", "Decided"])
        self.assertEqual((last["mini"], last["fresh"], last["verifyButton"]), (["v0", "v1"], "v1", True))
        self.assertEqual(last["note"], "Terraform validation is not run in the browser.")
        self.assertEqual(loop["status"], {"version": "Trusted state v1", "pills": HOLDS})
        self.assertEqual(loop["ledgerButton"], "Ledger")
        self.assertEqual(loop["placeholder"], "Ask for another fix. It starts from trusted state v1.")
        self.assertEqual(loop["gemini"][0]["title"], "Gemini · attempt 2")
        self.assertEqual(loop["gemini"][0]["note"], "a proposal, untrusted until DAIL says so")
        self.assertEqual(loop["gemini"][0]["stripe"], "UNTRUSTED")
        self.assertTrue(self.r["stampInView"])
        self.assertEqual(self.r["said"], [
            "Gemini proposed a fix", f"DAIL: rejected. {LOST}", "Attempt 2 of 3", "Gemini proposed a fix", f"DAIL: promoted. {PROMOTED}",
        ])  # fmt: skip
        seen = self.r["seenAfterLoop"]
        self.assertEqual(len(seen), 2)
        self.assertNotIn("Your previous patch", seen[0]["task"])
        self.assertIn("Close SSH and tidy up the database rules", seen[0]["task"])
        self.assertIn("Your previous patch was rejected by DAIL, an independent verifier: REJECT, REQUIRED_CHECK_FAILED; "
                      "blocking conditions: INVARIANT:INV-FUNC-001:1; no longer true: App reaches database. Propose a different "
                      "patch that repairs the target and keeps every protected invariant.", seen[1]["task"])  # fmt: skip

    def test_attempt_one_reopens_with_dails_words(self) -> None:
        one = self.r["reopened"]["cards"][0]
        self.assertEqual((one["stamp"], one["sentence"]), ("REJECT", LOST))
        self.assertEqual(one["raw"], "REQUIRED_CHECK_FAILED · INVARIANT:INV-FUNC-001:1 · path.missing")
        self.assertEqual(one["compare"], "A normal checker would have accepted this fix (3 checks).")
        self.assertEqual(one["cells"][3], "1 check failed")
        self.assertEqual(one["counts"], "5 checks · 1 carried forward")
        self.assertIn("Removes the rule app_to_db_5432", self.r["reopened"]["gemini"][0]["changes"])

    def test_the_decisions_equal_the_native_engine(self) -> None:
        from dail_demo.engine import run_evaluate

        for patch, shown in (("regression", self.r["own"]["last"]), ("safe", self.r["loop"]["last"])):
            native = run_evaluate("canonical", patch, environ=self.environ).trace["comparison"]
            self.assertEqual(shown["stamp"], native["C"]["decision"])
            self.assertIn("accepted" if native["A"]["decision"] == "PROMOTE" else "rejected", shown["compare"])

    def test_the_cells_fill_one_by_one_from_dails_events(self) -> None:
        self.assertEqual(self.r["fills"], [[f"dail-{n}", k] for n in (1, 2) for k in range(6)])

    def test_every_hidden_detail_is_reachable(self) -> None:
        for words in ("What changed", "aws_security_group_rule.app_to_db_5432 · DELETED", "What it affects", "re-checked",
                      "security_group_rule.app_to_db_5432 → RESOURCE:security_group.db → RESOURCE:db_instance.database",
                      "carried forward", "Every check", "dail.verify.reachability_cfg · path.missing", "parent state v0",
                      "candidate ", "target-only (condition A): PROMOTE", "dail-v1.0", "The AI (untrusted)", "test reply: regression"):  # fmt: skip
            self.assertIn(words.lower(), self.r["evidence"].lower())
        self.assertEqual(self.r["evidenceCounts"][:4], [4, 1, 3, 1])  # PASS, FAIL, re-checked, carried forward
        self.assertIn("app_to_db_5432", self.r["code"])
        self.assertGreater(self.r["diffLines"][1], 0)
        self.assertEqual(self.r["verify"], "✓ Verified by DAIL: 2 states, 2 candidates, no problem.")
        self.assertEqual(self.r["drawerVerify"], "✓ Verified by DAIL: 2 states, 2 candidates, no problem.")
        self.assertEqual(self.r["drawerStates"], 2)
        for words in ("promoted by DAIL · attempt 2", "baseline, established by DAIL", "Database not public · carried forward",
                      "SSH open to the internet · the repair target", "state ", "parent "):  # fmt: skip
            self.assertIn(words, self.r["drawer"])
        self.assertTrue(self.r["drawerClosed"])

    def test_after_three_failures_the_trusted_state_is_unchanged(self) -> None:
        r = self.r["threeFailures"]
        self.assertEqual(r["kinds"], ["you", "collapsed", "banner", "collapsed", "banner", "gemini", "dail", "final"])
        self.assertEqual(r["banners"], [BANNER.format(n=2), BANNER.format(n=3)])
        self.assertEqual(r["finals"], [ALL_FAILED])
        self.assertEqual(r["status"]["version"], "Trusted state v0")
        self.assertEqual(self.r["seenThree"], [False, True, True])

    def test_a_reply_dails_parser_refuses_is_a_failed_attempt(self) -> None:
        g = self.r["garbage"]
        self.assertEqual(g["kinds"][-5:], ["you", "collapsed", "banner", "gemini", "dail"])
        self.assertTrue(g["collapsed"][-1].startswith("Attempt 1 · RefusedDAIL's patch checker refused this fix:"), g["collapsed"][-1])
        self.assertEqual((g["last"]["stamp"], g["status"]["version"]), ("PROMOTE", "Trusted state v1"))

    def test_quota_and_stop_keep_everything_and_say_so(self) -> None:
        q = self.r["quota"]
        self.assertEqual(q["threadNotice"], "The AI's free quota is used up for now. Try again later, or write your own fix.")
        self.assertEqual((q["kinds"], q["status"]["version"]), (["you"], "Trusted state v0"))
        s = self.r["stopped"]
        self.assertEqual((s["finals"], s["status"]["version"]), (["Stopped. The trusted state is still v0."], "Trusted state v0"))

    def test_write_your_own_fix(self) -> None:
        self.assertIn("Beat the gate", self.r["writeHead"])
        self.assertEqual(self.r["fillButtons"], ["Fill: the safe repair", "Fill: the repair that breaks the database path"])
        own = self.r["own"]
        self.assertEqual(own["kinds"], ["editor-card", "dail"])
        self.assertEqual((own["last"]["stamp"], own["last"]["sentence"], own["status"]["version"]), ("REJECT", LOST, "Trusted state v1"))
        refused = self.r["ownRefused"]["last"]
        self.assertTrue(refused["sentence"].startswith("DAIL's patch checker refused this fix:"))
        self.assertIn("outside resource blocks", refused["sentence"])
        self.assertEqual(refused["cells"][0], "Refused")
        self.assertEqual(self.r["backToAsk"]["last"]["stamp"], "PROMOTE")  # the tabs keep their threads
        self.assertEqual(self.r["otherOwn"]["last"]["sentence"], LOST)  # tp-v1-F4-0092's fixed patch

    def test_replays(self) -> None:
        self.assertEqual((len(self.r["replays"]), self.r["runCards"]), (14, 14))
        for replay in self.r["replays"]:
            shown = replay["shown"]
            with self.subTest(run=replay["file"]):
                self.assertEqual(shown["last"]["stamp"], replay["expected"]["C"])
                self.assertIn("accepted" if replay["expected"]["A"] == "PROMOTE" else "rejected", shown["last"]["compare"])
                self.assertIsNone(shown["last"]["note"])
                self.assertTrue(shown["recorded"].startswith("Recorded run · "))
                source = "Gemini, recorded " if "gemini" in replay["file"] else "Reference patch"
                self.assertTrue(replay["card"].startswith(source), replay["card"])
                self.assertEqual(shown["gemini"][0]["title"].startswith("Gemini · gemini-3.5-flash-lite"), "gemini" in replay["file"])
        self.assertEqual((self.r["filter_gemini"], self.r["filter_reference"], self.r["filter_rejected"]), (3, 11, 5))
        self.assertFalse(self.r["pyodideInReplays"])
        self.assertLess(self.r["firstLoad_replays"]["bytes"], 1_000_000)
        self.assertGreater(self.r["firstLoad_ask"]["bytes"], 15_000_000)

    def test_layout_motion_and_access(self) -> None:
        self.assertEqual(self.r["reducedMotion"], [True, "none"])
        self.assertEqual(self.r["noHorizontalScroll"], {"390": True, "768": True, "1440": True})
        self.assertEqual((self.r["smallText"], self.r["keyboard"], self.r["targets"]), ([], [], []))
        p = self.r["presenter"]
        self.assertEqual((p["on"], p["font"], p["code"]), (True, "22.5px", "none"))
        top, bottom = p["card"]
        self.assertTrue(p["header"] <= top and bottom <= p["vh"], p)  # the DAIL card fully visible at 1366 x 768
        self.assertEqual((self.r["phoneMenu"], self.r["phoneMenuOpen"]), ("none", "flex"))
        self.assertTrue(self.r["phoneScroll"])
        self.assertEqual(self.r["phoneCells"], "none")  # the cells show only the number and the mark
        self.assertEqual(self.r["phone"]["last"]["stamp"], "PROMOTE")

    def test_no_console_errors_and_no_key(self) -> None:
        logs = [self.r[k] for k in ("logLoop", "log3", "logQuota", "otherLog", "replayLog", "phoneLog")]
        self.assertEqual(logs, [[]] * 6)
        self.assertNotIn(FAKE_KEY[:6], self.text)
        self.assertNotIn("Traceback", self.stderr)


class FailFastTests(unittest.TestCase):
    """If the page check cannot run (here: a browser channel that does not exist), it fails at once and the
    fake Gemini server is gone with it, instead of the caller waiting for the 900 s timeout (D-45)."""

    def test_a_browser_that_does_not_launch_fails_within_60_seconds(self) -> None:
        node = node_ready()
        environ = {**os.environ, "DAIL_LIVE_BROWSER": "no-such-browser-channel"}
        with tempfile.TemporaryDirectory() as tmp:
            start = time.monotonic()
            done = subprocess.run(
                [node, str(BROWSER_DIR / "site.mjs"), sys.executable, "check", str(Path(tmp) / "check.json")],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", check=False, timeout=60, env=environ,
            )
            elapsed = time.monotonic() - start
        self.assertNotEqual(done.returncode, 0)
        self.assertLess(elapsed, 60)
        self.assertIn("no-such-browser-channel", done.stderr)
        port = int(re.search(r"fake-gemini port (\d+)", done.stderr).group(1))
        with self.assertRaises(OSError):  # the fake Gemini and serve are stopped
            socket.create_connection(("127.0.0.1", port), timeout=2).close()
        print(f"\n  failed in {elapsed:.1f} s, server on port {port} stopped", end="")


if __name__ == "__main__":
    unittest.main()

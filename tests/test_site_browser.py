"""The page in a browser, on the real ``serve`` with a fake Gemini (D package §4; D-21)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import FAKE_KEY, REPO_ROOT, DataDirCase, dail_root
from tests.test_browser import BROWSER_DIR, node_ready

LOST = "Rejected: the app would lose its connection to the database."


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
            cls.text = out.read_text(encoding="utf-8")
            cls.r = json.loads(cls.text)
        print(f"\n  {cls.r['browser']}; ready in {cls.r['readyMs']} ms; first load: replays "
              f"{cls.r['firstLoad_replays']}, ask {cls.r['firstLoad_ask']}", end="")

    def test_the_first_screen_is_plain(self) -> None:
        self.assertEqual(self.r["first"]["health"], ["No", "Yes", "Yes", "Yes"])
        for word in ("SSH is closed to the internet", "The app can reach the database", "Don't type personal data"):
            self.assertIn(word, self.r["firstText"])
        for word in ("sha", "dail.verify", "aws_", "hash", "invariant", "REQUIRED_", "canonical"):
            self.assertNotIn(word, self.r["firstText"])
        self.assertFalse(self.r["first"]["evidenceOpen"])
        self.assertEqual(self.r["chip"], "Close SSH and tidy up the database rules")

    def test_the_loop_rejects_sends_the_reason_and_promotes_the_retry(self) -> None:
        loop, one = self.r["loop"], self.r["attemptOne"]
        self.assertEqual(loop["attempts"], ["Attempt 1 · REJECT", "Attempt 2 · PROMOTE"])
        self.assertEqual((one["stamp"], one["reason"]), ("REJECT", LOST))
        self.assertEqual(one["normal"], "A normal checker would have accepted this fix.")
        self.assertIn("Deletes rule app_to_db_5432", one["changes"])
        self.assertEqual((loop["stamp"], loop["ledger"], loop["health"]), ("PROMOTE", ["v0", "v1"], ["Yes"] * 4))
        self.assertEqual(loop["note"], "Terraform validation is not run in the browser.")
        self.assertTrue(self.r["stampInView"])
        stamps = [m.split("|")[0] for m in self.r["moments"] if m.split("|")[0]]
        self.assertEqual([s for i, s in enumerate(stamps) if i == 0 or s != stamps[i - 1]], ["REJECT", "PROMOTE"])
        self.assertTrue(any("Attempt 2 of 3: DAIL's reason was sent back to the AI|Gemini is writing" in m for m in self.r["moments"]))
        seen = self.r["seenAfterLoop"]
        self.assertEqual(len(seen), 2)
        self.assertNotIn("Your previous patch", seen[0]["task"])
        self.assertIn("rejected by DAIL, an independent verifier: REJECT, REQUIRED_CHECK_FAILED; blocking conditions: "
                      "INVARIANT:INV-FUNC-001:1; no longer true: The app can reach the database.", seen[1]["task"])

    def test_the_decisions_equal_the_native_engine(self) -> None:
        from dail_demo.engine import run_evaluate

        for patch, shown in (("regression", self.r["attemptOne"]), ("safe", self.r["loop"])):
            native = run_evaluate("canonical", patch, environ=self.environ).trace["comparison"]
            self.assertEqual(shown["stamp"], native["C"]["decision"])
            self.assertIn("accepted" if native["A"]["decision"] == "PROMOTE" else "rejected", shown["normal"])

    def test_the_boxes_fill_one_by_one_and_the_card_crosses_the_boundary(self) -> None:
        self.assertEqual(self.r["fills"], [1, 2, 3, 4, 5] * 2)
        self.assertEqual(self.r["crossed"], {"above": True, "below": True})

    def test_every_hidden_detail_is_reachable(self) -> None:
        for word in ("INVARIANT:INV-FUNC-001:1", "dail.verify.reachability_cfg", "INV-SEC-003 carried forward", "dependency paths",
                     "Target-only checking", "test reply: regression", "dail-v1.0"):  # fmt: skip
            self.assertIn(word.lower(), self.r["evidence"].lower())
        self.assertEqual(self.r["evidenceDetails"], [5, 3, 1, 1, 1])
        self.assertIn("app_to_db_5432", self.r["code"])
        self.assertIn("State hash", self.r["stateDetail"])
        self.assertIn("Parent", self.r["stateDetail"])
        self.assertIn("Chain verified by DAIL: 2 trusted states, 2 candidates", self.r["verify"])

    def test_after_three_failures_the_trusted_state_is_unchanged(self) -> None:
        r = self.r["threeFailures"]
        self.assertEqual(r["attempts"], [f"Attempt {n} · REJECT" for n in (1, 2, 3)])
        self.assertIn("Nothing was changed", r["gaveUp"])
        self.assertEqual((r["ledger"], r["health"]), (["v0"], ["No", "Yes", "Yes", "Yes"]))

    def test_a_reply_dails_parser_refuses_is_a_failed_attempt(self) -> None:
        self.assertEqual(self.r["garbage"]["attempts"], ["Attempt 1 · TURNED AWAY", "Attempt 2 · PROMOTE"])
        self.assertIn("not exactly one JSON object", self.r["garbageOne"]["refusedReason"])

    def test_quota_keeps_everything_and_says_so(self) -> None:
        self.assertIn("free quota is used up", self.r["quota"]["notice"])
        self.assertEqual((self.r["quota"]["attempts"], self.r["quota"]["attemptNote"]), ([], None))
        self.assertEqual(self.r["quota"]["ledger"], ["v0", "v1"])

    def test_write_your_own_and_tabs(self) -> None:
        own = self.r["own"]
        self.assertEqual((own["stamp"], own["reason"], own["ledger"]), ("REJECT", LOST, ["v0", "v1"]))
        self.assertIn("outside resource blocks", self.r["ownRefused"]["refusedReason"])
        self.assertEqual(self.r["backToAsk"]["attempts"], ["Attempt 1 · REJECT", "Attempt 2 · PROMOTE"])
        self.assertEqual(self.r["backToAsk"]["stamp"], "PROMOTE")
        self.assertEqual((self.r["afterReset"]["ledger"], self.r["afterReset"]["attempts"]), (["v0"], []))
        self.assertEqual(self.r["otherOwn"]["reason"], LOST)

    def test_replays(self) -> None:
        self.assertEqual(len(self.r["replays"]), 14)
        for replay in self.r["replays"]:
            with self.subTest(run=replay["file"]):
                self.assertEqual(replay["shown"]["stamp"], replay["expected"]["C"])
                self.assertIn("accepted" if replay["expected"]["A"] == "PROMOTE" else "rejected", replay["shown"]["normal"])
                self.assertIsNone(replay["shown"]["note"])
                self.assertEqual(replay["gemini"], 1 if "gemini" in replay["file"] else 0)
        self.assertFalse(self.r["pyodideInReplays"])
        self.assertLess(self.r["firstLoad_replays"]["bytes"], 1_000_000)
        self.assertGreater(self.r["firstLoad_ask"]["bytes"], 15_000_000)

    def test_layout_motion_and_access(self) -> None:
        self.assertEqual(self.r["reducedMotion"], [True, "none"])
        self.assertEqual(self.r["noHorizontalScroll"], {"390": True, "768": True, "1366": True})
        self.assertEqual((self.r["smallText"], self.r["smallOnColour"], self.r["keyboard"]), ([], 0, []))
        p = self.r["presenter"]
        self.assertEqual((p["on"], p["font"], p["lines"]), (True, "20px", "none"))
        for name, (top, bottom) in p["inside"].items():
            self.assertTrue(p["band"] <= top and bottom <= p["vh"], (name, top, bottom))

    def test_no_console_errors_and_no_key(self) -> None:
        self.assertEqual((self.r["logBeforeQuota"], self.r["otherLog"], self.r["replayLog"]), ([], [], []))
        self.assertNotIn(FAKE_KEY[:6], self.text)


if __name__ == "__main__":
    unittest.main()

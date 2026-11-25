"""The plain-words reason is built only from DAIL's decision and blocking conditions (D package §3, §4)."""

from __future__ import annotations

import json
import subprocess
import unittest

from tests.support import REPO_ROOT
from tests.test_browser import BROWSER_DIR, node_ready

RUNS = REPO_ROOT / "site" / "runs"


def blocked(target: str, code: str = "REQUIRED_CHECK_FAILED") -> dict:
    return {"code": code, "decision": "REJECT", "target": target, "detail": "ignored <b>detail</b>"}


class NamesTests(unittest.TestCase):
    def words(self, cases: list[dict]) -> dict:
        done = subprocess.run([node_ready(), str(BROWSER_DIR / "names.mjs")], input=json.dumps(cases), cwd=REPO_ROOT,
                              capture_output=True, text=True, encoding="utf-8", check=True)  # fmt: skip
        return json.loads(done.stdout)

    def test_the_recorded_canonical_decisions(self) -> None:
        cases = [json.loads((RUNS / f"canonical--{p}.json").read_text(encoding="utf-8"))["conditions"]["C"]["decision"]
                 for p in ("regression", "safe")]  # fmt: skip
        r = self.words(cases)
        self.assertEqual(r["plain"], ["Rejected: the app would lose its connection to the database.",
                                      "Accepted: DAIL proved that everything that must hold still holds."])  # fmt: skip
        self.assertEqual(r["failed"], [["The app can reach the database"], []])

    def test_only_the_decision_and_the_blocking_conditions_matter(self) -> None:
        one = {"type": "REJECT", "reason": "A", "blocking": [blocked("INVARIANT:INV-SEC-001:2")], "note": "x"}
        two = {"type": "REJECT", "reason": "B", "blocking": [{**blocked("INVARIANT:INV-SEC-001:2"), "detail": "y"}]}
        both = {"type": "REJECT", "reason": "A", "blocking": [blocked("INVARIANT:INV-SEC-001:2"), blocked("INVARIANT:INV-FUNC-001:1")]}
        unproven = {"type": "REJECT", "reason": "A", "blocking": [blocked("INVARIANT:INV-SEC-001:2", "REQUIRED_CHECK_UNKNOWN")]}
        other = {"type": "REJECT", "reason": "STALE_PARENT", "blocking": [blocked("STRUCTURAL")]}
        none = {"type": "ESCALATE", "reason": "X", "blocking": []}
        self.assertEqual(self.words([one, two, both, unproven, other, none])["plain"], [
            "Rejected: SSH would be open to the internet.", "Rejected: SSH would be open to the internet.",
            "Rejected: SSH would be open to the internet and the app would lose its connection to the database.",
            "Rejected: DAIL could not prove that SSH is closed to the internet.",
            "Rejected: one of DAIL's required checks did not pass.", "Not accepted: DAIL's rules do not allow it.",
        ])  # fmt: skip

    def test_the_four_sentences_are_the_recorded_ones(self) -> None:
        decisions = (REPO_ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        for name in self.words([])["names"].values():
            self.assertIn(name["holds"], decisions)


if __name__ == "__main__":
    unittest.main()

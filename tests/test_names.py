"""Plain language (work package D §3): fixed texts that only describe what DAIL returned."""

from __future__ import annotations

import json
import subprocess
import unittest

from tests.support import REPO_ROOT
from tests.test_browser import BROWSER_DIR, node_ready

RUNS = REPO_ROOT / "site" / "runs"


def blocked(target: str, result: str = "FAIL", code: str = "REQUIRED_CHECK_FAILED") -> dict:
    return {"code": code, "decision": "REJECT", "target": target, "detail": f"result {target}: {result} path.missing"}


class NamesTests(unittest.TestCase):
    def words(self, **cases) -> dict:
        done = subprocess.run([node_ready(), str(BROWSER_DIR / "names.mjs")], input=json.dumps(cases), cwd=REPO_ROOT,
                              capture_output=True, text=True, encoding="utf-8", check=True)  # fmt: skip
        return json.loads(done.stdout)

    def test_the_recorded_canonical_decisions(self) -> None:
        traces = [json.loads((RUNS / f"canonical--{p}.json").read_text(encoding="utf-8")) for p in ("regression", "safe")]
        r = self.words(decisions=[t["conditions"]["C"]["decision"] for t in traces],
                       comparisons=[t["comparison"]["A"] for t in traces])  # fmt: skip
        self.assertEqual(r["sentences"], [
            "Rejected: the app would lose its connection to the database.",
            "Promoted: SSH closed to the internet, and everything that held before still holds.",
        ])  # fmt: skip
        # the sentence names exactly the invariants DAIL's blocking conditions name
        blocking = traces[0]["conditions"]["C"]["decision"]["blocking"]
        self.assertEqual({b["target"].split(":")[1] for b in blocking}, {"INV-FUNC-001"})
        self.assertEqual(r["failed"], [["App reaches database"], []])
        self.assertTrue(r["raw"][0].startswith("REQUIRED_CHECK_FAILED · INVARIANT:INV-FUNC-001:"), r["raw"][0])
        self.assertEqual(r["comparisons"], ["A normal checker would have accepted this fix (3 checks).",
                                            "A normal checker would have accepted this fix (3 checks)."])  # fmt: skip

    def test_only_the_decision_and_the_blocking_conditions_matter(self) -> None:
        one = {"type": "REJECT", "reason": "A", "blocking": [blocked("INVARIANT:INV-SEC-001:2")], "note": "x"}
        two = {"type": "REJECT", "reason": "B", "blocking": [{**blocked("INVARIANT:INV-SEC-001:2"), "code": "OTHER"}]}
        both = {"type": "REJECT", "reason": "A",
                "blocking": [blocked("INVARIANT:INV-SEC-001:2"), blocked("INVARIANT:INV-FUNC-001:1")]}  # fmt: skip
        unproven = {"type": "RETRY", "reason": "A", "blocking": [blocked("INVARIANT:INV-SEC-002:1", "UNSUPPORTED")]}
        other = {"type": "REJECT", "reason": "STALE_PARENT", "blocking": [{"code": "STALE", "target": "STRUCTURAL"}]}
        error = {"type": "ESCALATE", "reason": "X", "blocking": []}
        r = self.words(decisions=[one, two, both, unproven, other, error])
        self.assertEqual(r["sentences"], [
            "Rejected: SSH would be open to the internet.",
            "Rejected: SSH would be open to the internet.",
            "Rejected: SSH would be open to the internet and the app would lose its connection to the database.",
            "DAIL couldn't prove that database port closed, so it won't promote. DAIL never guesses.",
            "Rejected: one of DAIL's required checks did not pass.",
            "DAIL hit an error and stopped. Nothing was changed.",
        ])  # fmt: skip
        self.assertEqual(r["raw"][0], "A · INVARIANT:INV-SEC-001:2 · path.missing")
        self.assertEqual(r["refused"], "DAIL's patch checker refused this fix: the patch changes no file.")

    def test_the_pills_and_the_change_words(self) -> None:
        r = self.words(
            health=[["INV-SEC-001", "PROTECTED"], ["INV-SEC-001", "VIOLATED"], ["INV-FUNC-001", "UNCERTAIN"]],
            changes=[["aws_security_group_rule.app_ssh_public", "MODIFIED"], ["aws_db_instance.database", "DELETED"],
                     ["aws_instance.app", "CREATED"], ["aws_security_group.db", "REPLACED"], ["aws_s3_bucket.logs", "UNCERTAIN"],
                     ["aws_security_group_rule.app_to_db_5432", None]],
            comparisons=[{"decision": "REJECT", "check_count": 3}, {"decision": "ESCALATE", "check_count": 0}])  # fmt: skip
        self.assertEqual([(p["kind"], p["text"], p["mark"]) for p in r["health"]], [
            ("pass", "SSH closed to the internet", "✓"), ("fail", "SSH open to the internet", "✕"),
            ("unknown", "App reaches database: unknown", "?")])  # fmt: skip
        self.assertEqual([(c["verb"], c["noun"], c["name"]) for c in r["changes"]], [
            ("Edits", "the rule", "app_ssh_public"), ("Removes", "the database", "database"),
            ("Adds", "the app server", "app"), ("Replaces", "the security group", "db"),
            ("Unclear change", "aws_s3_bucket", "logs"), ("Keeps", "the rule", "app_to_db_5432")])  # fmt: skip
        self.assertEqual(r["comparisons"][0], "A normal checker would also have rejected it (3 checks).")

    def test_the_table_of_section_3(self) -> None:
        names = self.words()["names"]
        self.assertEqual({k: (v["holds"], v["broken"], v["wouldBreak"]) for k, v in names.items()}, {
            "INV-SEC-001": ("SSH closed to the internet", "SSH open to the internet", "SSH would be open to the internet"),
            "INV-SEC-002": ("Database port closed", "Database port open to the internet",
                            "the database port would be open to the internet"),
            "INV-SEC-003": ("Database not public", "Database is public", "the database would become public"),
            "INV-FUNC-001": ("App reaches database", "App can't reach database",
                             "the app would lose its connection to the database"),
        })  # fmt: skip
        decisions = (REPO_ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        for name in names.values():
            self.assertIn(name["holds"], decisions)
            self.assertIn(name["wouldBreak"], decisions)


if __name__ == "__main__":
    unittest.main()

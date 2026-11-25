"""Sessions (L4; C work package §2.3), natively, on DAIL's own fixtures. The same code runs in the
browser tab (``evaluate_core.Session``, through ``dail_demo.browser``).

* promote, reject, promote leaves exactly DAIL's lineage: v0 -> v1 -> v2, the reject changes
  nothing, and DAIL's own store says the same (``trusted_states.lineage``, the lineage head);
* "Verify chain" (DAIL's lineage read-back, which recomputes every state hash, and
  ``describe_chain`` for every candidate) passes, and fails once a stored hash is altered.

The third candidate is DAIL's fixture ``fixtures/verification/ec2_rds_5432_pass_v1``, the one DAIL's
own lifecycle test promotes from version 1.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests.support import dail_root


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dail = dail_root()

    def setUp(self) -> None:
        from dail_demo import evaluate_core as core
        from dail_demo.settings import dail_config
        from experiments.generation.parent import config_only_copy

        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name).resolve()
        fx = self.dail / "fixtures"
        s0 = config_only_copy(fx / "canonical_regression" / "baseline", self.root / "s0")
        expected = json.loads((fx / "canonical_regression" / "baseline" / "expected.json").read_text(encoding="utf-8"))
        self.session = core.Session(
            root=self.root, scenario=core.canonical_scenario(expected, s0), s0_dir=s0,
            config=dail_config(self.dail), session_id="session-test",
        )
        self.traces = []
        for n, folder in enumerate(
            ("canonical_regression/patch_safe", "canonical_regression/patch_regression",
             "verification/ec2_rds_5432_pass_v1"),
            1,
        ):
            directory = config_only_copy(fx / folder, self.root / f"candidate-{n}")
            self.traces.append(self.session.submit(
                core.Candidate(source=core.FIXED_PATCH, label=folder, directory=directory),
                label="test", versions={},
            ))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_promote_reject_promote_leaves_dails_lineage(self) -> None:
        self.assertEqual([t["conditions"]["C"]["decision"]["type"] for t in self.traces], ["PROMOTE", "REJECT", "PROMOTE"])
        self.assertEqual([t["session"]["promoted"] for t in self.traces], [True, False, True])
        self.assertEqual([[c["version"] for c in t["session"]["ledger"]] for t in self.traces], [[1, 0], [1, 0], [2, 1, 0]])
        # the reject is evaluated against v1 and leaves it the trusted state
        self.assertEqual(self.traces[1]["session"]["parent_state_id"], self.traces[0]["session"]["trusted_state"]["state_id"])
        self.assertEqual(self.traces[1]["session"]["trusted_state"], self.traces[0]["session"]["trusted_state"])
        ledger = self.traces[2]["session"]["ledger"]
        for newer, older in zip(ledger, ledger[1:]):
            self.assertEqual(newer["parent_state_id"], older["state_id"])
        with self.session.run.factory() as uow:
            stored = uow.trusted_states.lineage(self.session.parent.state_id)
            head = uow.trusted_states.get_current(self.session.run.lineage_id)
        self.assertEqual([s.state_id for s in stored], [c["state_id"] for c in ledger])
        self.assertEqual([s.state_hash for s in stored], [c["state_hash"] for c in ledger])
        self.assertEqual(head.state_id, ledger[0]["state_id"])

    def test_target_only_never_touches_the_session(self) -> None:
        self.assertEqual(self.traces[1]["conditions"]["A"]["decision"]["type"], "PROMOTE")
        self.assertIsNone(self.traces[1]["conditions"]["A"]["store"])
        self.assertFalse(any(p.name.startswith("A-") for p in self.root.iterdir()))

    def test_verify_chain_passes(self) -> None:
        result = self.session.verify_chain()
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual((result["states"], result["candidates"]), (3, 3))

    def test_verify_chain_fails_when_a_stored_hash_is_altered(self) -> None:
        connection = sqlite3.connect(self.session.run.store)
        try:  # DAIL's store refuses updates through triggers: they are dropped to simulate tampering
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'trusted_states'"
            ).fetchall():
                connection.execute(f"DROP TRIGGER {name}")
            connection.execute("UPDATE trusted_states SET state_hash = ? WHERE version = 1", ("0" * 64,))
            connection.commit()
        finally:
            connection.close()
        result = self.session.verify_chain()
        self.assertFalse(result["ok"])
        self.assertTrue(any("DATA-INT-010" in p for p in result["problems"]), result["problems"])
        print(f"\n  after tampering: {result['problems'][0]}", end="")


if __name__ == "__main__":
    unittest.main()

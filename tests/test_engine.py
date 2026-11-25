"""The L1 engine on DAIL's canonical fixture, with real DAIL from ``DAIL_ROOT`` (B work package §2.3).

The expected decisions are read from DAIL's fixture files, never typed here:

* DAIL (C): ``decision.allowed`` of each patch's ``expected.json``;
* target-only (A) checks the repair target only (C-205), so its expected decision is PROMOTE
  exactly when the fixture's own result for the target (``results[<target>].result``) is PASS.

The engine is also compared with DAIL's own experiment trial (``experiments.trial.run_attempt``) on
the same inputs: the same decision, work, counts, identity and impact.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.support import FAKE_KEY, DataDirCase, assert_no_key, dail_root

PATCHES = ("safe", "regression")


def fixture(dail: Path, folder: str) -> dict:
    path = dail / "fixtures" / "canonical_regression" / folder / "expected.json"
    return json.loads(path.read_text(encoding="utf-8"))


class CanonicalEngineTests(DataDirCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dail = dail_root()
        cls.baseline = fixture(cls.dail, "baseline")
        cls.target = cls.baseline["baseline"]["remediation_targets"][0]

    def run_patch(self, patch: str) -> tuple[dict, Path]:
        from dail_demo.engine import run_evaluate

        outcome = run_evaluate("canonical", patch, environ=self.environ)
        self.assertEqual(outcome.exit_code, 0)
        return outcome.trace, outcome.path

    def test_decisions_match_dails_fixture_expectations(self) -> None:
        from dail_demo.scenarios import CANONICAL_PATCHES, expected_decision

        for patch in PATCHES:
            with self.subTest(patch=patch):
                trace, _ = self.run_patch(patch)
                expected = fixture(self.dail, CANONICAL_PATCHES[patch])
                self.assertIn(trace["conditions"]["C"]["decision"]["type"], expected_decision(self.dail, patch))
                target_passes = expected["results"][self.target]["result"] == "PASS"
                self.assertEqual(
                    trace["conditions"]["A"]["decision"]["type"], "PROMOTE" if target_passes else "REJECT"
                )

    def test_regression_is_blocked_by_inv_func_001(self) -> None:
        trace, _ = self.run_patch("regression")
        expected = fixture(self.dail, "patch_regression")
        failing = sorted(inv for inv, row in expected["results"].items() if row["result"] == "FAIL")
        version = expected["results"][failing[0]]["invariant_version"]
        blocking = {b["target"] for b in trace["conditions"]["C"]["decision"]["blocking"]}
        self.assertEqual(blocking, {f"INVARIANT:{failing[0]}:{version}"})
        self.assertEqual(blocking, {"INVARIANT:INV-FUNC-001:1"})

    def test_c_trace_shows_changes_impact_and_carry_forward(self) -> None:
        from dail_demo.scenarios import CANONICAL_PATCHES

        for patch in PATCHES:
            with self.subTest(patch=patch):
                trace, _ = self.run_patch(patch)
                expected = fixture(self.dail, CANONICAL_PATCHES[patch])
                c = trace["conditions"]["C"]
                changed = {r["address"]: r["change_type"] for r in c["changed_resources"]}
                self.assertEqual(
                    changed, {a: row["change"] for a, row in expected["changes"]["resources"].items()}
                )
                affected = {a["invariant_id"] for a in c["impact"]["affected"]}
                self.assertEqual(affected, set(expected["impact"]["required_affected"]))
                self.assertTrue(all(a["impact_types"] for a in c["impact"]["affected"]))
                self.assertTrue(all(a["dependency_paths"] for a in c["impact"]["affected"]))
                carried = {x["invariant_id"] for x in c["impact"]["carry_forward_candidates"]}
                self.assertIn("INV-SEC-003", carried)
                plan = {p["invariant_id"]: p["source"] for p in c["proof_plan"]}
                self.assertEqual(plan["INV-SEC-003"], "CARRIED_FORWARD")
                self.assertTrue(c["identity"]["pairs"])

    def test_check_counts_are_dails_verifier_invocations(self) -> None:
        for patch in PATCHES:
            trace, _ = self.run_patch(patch)
            for key in ("C", "A"):
                section = trace["conditions"][key]
                with self.subTest(patch=patch, condition=key):
                    stored = section["dail"]["verification"]["verifier_invocations"]
                    self.assertEqual(section["check_count"], stored)
                    self.assertGreater(stored, 0)
                    print(f"\n  check count {patch} {key}: {stored}", end="")

    def test_trace_fields_and_location(self) -> None:
        from dail_demo import DEMO_LABEL

        trace, path = self.run_patch("safe")
        self.assertEqual(trace["schema"], "dail-live-trace/1")
        self.assertEqual(trace["label"], DEMO_LABEL)
        self.assertEqual(trace["candidate_source"], "FIXED_PATCH")
        self.assertEqual(trace["versions"]["dail_tag"], "dail-v1.0")
        self.assertRegex(trace["versions"]["dail_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(trace["versions"]["registry"]["means"], "registry-v1.1")
        self.assertIn("+++ b/main.tf", trace["diff"])
        for key in ("C", "A"):
            section = trace["conditions"][key]
            for field in ("baseline", "identity", "impact", "verification", "decision", "check_count", "wall_seconds"):
                self.assertIn(field, section)
            for row in section["verification"]:
                self.assertTrue({"target", "verifier", "result", "reason"} <= set(row))
        self.assertEqual(path.parent, self.data / "traces")
        self.assertTrue(path.read_text(encoding="utf-8").startswith("{"))
        assert_no_key(self, path.read_text(encoding="utf-8"), str(path))

    def test_only_cs_store_is_kept(self) -> None:
        trace, path = self.run_patch("regression")
        run_root = self.data / "runs" / trace["run_id"]
        self.assertTrue((run_root / trace["conditions"]["C"]["store"]).is_file())
        self.assertIsNone(trace["conditions"]["A"]["store"])
        self.assertFalse((run_root / "A").exists())

    def test_the_key_is_refused_if_it_ever_reaches_a_trace(self) -> None:
        from dail_demo.engine import Run, write_trace
        from dail_demo.settings import SetupError

        run = Run(self.dail, self.data, "leak-test", self.data / "runs" / "leak-test")
        with self.assertRaises(SetupError):
            write_trace({"oops": FAKE_KEY}, run, self.environ)
        self.assertFalse((self.data / "traces" / "leak-test.json").exists())

    def test_out_inside_the_repository_is_refused(self) -> None:
        from dail_demo.engine import run_evaluate
        from dail_demo.settings import SetupError
        from tests.support import REPO_ROOT

        with self.assertRaises(SetupError):
            run_evaluate("canonical", "safe", environ=self.environ, out=REPO_ROOT / "trace.json")
        self.assertFalse((REPO_ROOT / "trace.json").exists())


class SameAsDailsTrialTests(unittest.TestCase):
    """The engine's records equal those of DAIL's own ``experiments.trial.run_attempt``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dail = dail_root()

    def test_engine_equals_run_attempt(self) -> None:
        from dail_demo import evaluate_core as core
        from dail_demo.settings import dail_config
        from experiments.definition import Condition
        from experiments.generation.parent import config_only_copy
        from experiments.trial import TrialInputs, run_attempt

        config = dail_config(self.dail)
        base = self.dail / "fixtures" / "canonical_regression"
        expected = fixture(self.dail, "baseline")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp).resolve()
            s0 = config_only_copy(base / "baseline", root / "inputs" / "s0")
            cand = config_only_copy(base / "patch_regression", root / "inputs" / "candidate")
            scenario = core.canonical_scenario(expected, s0, cand)
            trace = core.evaluate(
                root=root,
                scenario=scenario,
                s0_dir=s0,
                candidate=core.Candidate(source=core.FIXED_PATCH, label="regression", directory=cand),
                config=config,
                run_id="equivalence",
                label="test",
                versions={},
            )
            for condition in (Condition.C, Condition.A):
                with self.subTest(condition=condition.value):
                    outcome = run_attempt(
                        TrialInputs(
                            trial_id=f"equivalence-{condition.value}",
                            experiment_id="dail-live-equivalence",
                            scenario=scenario,
                            condition=condition,
                            repetition=1,
                            attempt=1,
                            admission_evidence="test",
                        ),
                        root / f"trial-{condition.value}",
                        config=config,
                    )
                    theirs = outcome.result["transitions"][0]
                    ours = trace["conditions"][condition.value]["dail"]["transition"]
                    self.assertEqual(ours["decision"]["type"], theirs["decision"]["type"])
                    self.assertEqual(ours["decision"]["reason"], theirs["decision"]["reason"])
                    self.assertEqual(
                        [b["target"] for b in ours["decision"]["blocking"]],
                        [b["target"] for b in theirs["decision"]["blocking"]],
                    )
                    self.assertEqual(
                        [(w["target_id"], w["result"], w["origin"]) for w in ours["work"]],
                        [(w["target_id"], w["result"], w["origin"]) for w in theirs["work"]],
                    )
                    self.assertEqual(ours["work_counts"], theirs["work_counts"])
                    self.assertEqual(ours["identity"]["pairs"], theirs["identity"]["pairs"])
                    self.assertEqual(ours["impact"]["affected"], theirs["impact"]["affected"])
                    self.assertEqual(
                        outcome.result["baseline"]["invariants"],
                        trace["conditions"][condition.value]["baseline"]["invariants"],
                    )


if __name__ == "__main__":
    unittest.main()

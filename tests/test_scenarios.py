"""The curated TerraPreserve scenarios (B work package §3.1, §3.4).

The list follows the work package: 5 to 8 ids across F2, F4 and F8, at least two F4, all repair
scenarios of the controlled tier. With real DAIL and TerraPreserve, each is loaded through DAIL's
loader, establishes a baseline under C and A, and gets a decision under both with ``--patch fixed``
(the decisions are reported as found, not asserted).
"""

from __future__ import annotations

import unittest
from collections import Counter

from dail_demo.scenarios import CURATED, CURATED_IDS
from tests.support import DataDirCase, dail_root, terrapreserve_root


class CuratedListTests(unittest.TestCase):
    def test_the_list_follows_the_work_package(self) -> None:
        families = Counter(family for _, family, _ in CURATED)
        self.assertTrue(5 <= len(CURATED) <= 8, len(CURATED))
        self.assertEqual(set(families), {"F2", "F4", "F8"})
        self.assertGreaterEqual(families["F4"], 2)
        self.assertEqual(len(set(CURATED_IDS)), len(CURATED_IDS))
        for scenario_id, family, why in CURATED:
            self.assertTrue(scenario_id.startswith(f"tp-v1-{family}-"))
            self.assertTrue(why)


class CuratedScenarioTests(DataDirCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dail = dail_root()
        cls.tp = terrapreserve_root()

    def test_each_is_a_controlled_repair_loaded_by_dails_loader(self) -> None:
        from dail_demo.scenarios import terrapreserve

        for scenario_id in CURATED_IDS:
            with self.subTest(scenario=scenario_id):
                source = terrapreserve(self.tp, scenario_id)
                self.assertEqual(source.scenario.target_kind, "repair")
                self.assertIsNotNone(source.scenario.template_id)  # controlled tier: a template id
                self.assertEqual(source.scenario.split, "dev")

    def test_an_id_that_is_not_listed_is_refused(self) -> None:
        from dail_demo.scenarios import ScenarioError, terrapreserve

        with self.assertRaises(ScenarioError):
            terrapreserve(self.tp, "tp-v1-F1-0001")

    def test_dails_loader_refuses_the_test_split(self) -> None:
        from experiments.loader import LoaderError, load

        with self.assertRaises(LoaderError):
            load(self.tp, split="test")

    def test_each_establishes_a_baseline_and_gets_decisions_with_its_fixed_patch(self) -> None:
        from dail_demo.engine import run_evaluate

        for scenario_id in CURATED_IDS:
            with self.subTest(scenario=scenario_id):
                outcome = run_evaluate(scenario_id, "fixed", environ=self.environ)
                self.assertEqual(outcome.exit_code, 0)
                self.assertTrue(outcome.trace["admission"]["content_hash_matches_manifest"])
                found = []
                for key in ("C", "A"):
                    section = outcome.trace["conditions"][key]
                    self.assertEqual(section["baseline"]["outcome"], "ESTABLISHED")
                    self.assertIn(section["decision"]["type"], ("PROMOTE", "REJECT", "RETRY", "ESCALATE"))
                    found.append(f"{key} {section['decision']['type']} ({section['check_count']} checks)")
                print(f"\n  {scenario_id}: " + ", ".join(found), end="")


if __name__ == "__main__":
    unittest.main()

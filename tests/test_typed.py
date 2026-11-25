"""Typed patches (B work package §3.2, §3.4).

* Core level (DAIL only, also on CI): the typed directory becomes the resource-block patch DAIL's
  patch validator checks, and the validator admits or refuses it (without ``terraform validate``,
  as in the browser, PLAN §3.8).
* Engine level with a stand-in gate (also on CI): a refused typed patch never reaches the
  orchestrator, and a typed copy of the canonical regression patch gives the same decisions.
* With the real gate (provider mirror; skipped on CI): a syntax error is refused before DAIL with
  Terraform's reason, and the typed regression copy gives the same decisions as ``--patch
  regression``.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest import mock

from tests.support import DataDirCase, dail_root, mirror_environment


def _ok_gate(calls: list[Path] | None = None):  # type: ignore[no-untyped-def]
    """A stand-in for the validate gate (tests only: CI has no provider mirror)."""
    from llm.validation.patch import TerraformCheck

    def gate(directory: Path) -> TerraformCheck:
        if calls is not None:
            calls.append(Path(directory))
        return TerraformCheck(True, "", {"terraform": "stand-in for tests"})

    return gate


class TypedCase(DataDirCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dail = dail_root()
        cls.fixtures = cls.dail / "fixtures" / "canonical_regression"

    def typed_copy(self, folder: str) -> Path:
        target = self.data.parent / f"typed-{folder}"
        target.mkdir(parents=True)
        for path in (self.fixtures / folder).glob("*.tf"):
            shutil.copyfile(path, target / path.name)
        return target


class CoreTypedTests(TypedCase):
    def admit(self, folder: Path) -> dict:
        import json

        from dail_demo import evaluate_core as core
        from experiments.generation.parent import config_only_copy

        root = self.data / "core"
        s0 = config_only_copy(self.fixtures / "baseline", root / "inputs" / "s0")
        edited = config_only_copy(folder, root / "inputs" / "edited")
        expected = json.loads((self.fixtures / "baseline" / "expected.json").read_text(encoding="utf-8"))
        return core.admit_typed(
            root=root,
            scenario=core.canonical_scenario(expected, s0),
            s0_dir=s0,
            edited_dir=edited,
            run_id="typed-core",
            terraform_validate=None,
        )

    def test_the_regression_copy_becomes_dails_resource_patch(self) -> None:
        import json

        from dail_demo import evaluate_core as core

        response = core.typed_response(self.fixtures / "baseline", self.typed_copy("patch_regression"))
        expected = json.loads((self.fixtures / "patch_regression" / "expected.json").read_text(encoding="utf-8"))
        self.assertEqual(set(response.changed_addresses), set(expected["changes"]["resources"]))

    def test_dails_validator_admits_the_regression_copy(self) -> None:
        record = self.admit(self.typed_copy("patch_regression"))
        self.assertTrue(record["admitted"], record)
        self.assertEqual(
            sorted(op for _, op in record["operations"]), ["DELETE", "DELETE", "MODIFY", "MODIFY"]
        )

    def test_a_change_outside_resource_blocks_is_refused(self) -> None:
        folder = self.typed_copy("patch_safe")
        with (folder / "main.tf").open("a", encoding="utf-8") as handle:
            handle.write('\noutput "leak" {\n  value = aws_instance.app.id\n}\n')
        record = self.admit(folder)
        self.assertFalse(record["admitted"])
        self.assertIn("outside resource blocks", record["errors"][0])

    def test_a_provisioner_is_refused_by_dails_validator(self) -> None:
        folder = self.typed_copy("baseline")
        text = (folder / "main.tf").read_text(encoding="utf-8")
        text = text.replace(
            'resource "aws_instance" "app" {',
            'resource "aws_instance" "app" {\n  provisioner "local-exec" {\n    command = "echo hi"\n  }',
        )
        (folder / "main.tf").write_text(text, encoding="utf-8")
        record = self.admit(folder)
        self.assertFalse(record["admitted"])
        self.assertEqual(record["failure_class"], "POLICY_VIOLATION")

    def test_a_syntax_error_is_refused_by_dails_parser_without_terraform(self) -> None:
        folder = self.typed_copy("baseline")
        with (folder / "main.tf").open("a", encoding="utf-8") as handle:
            handle.write('\nresource "aws_security_group_rule" "broken" {\n  type = "ingress"\n')
        record = self.admit(folder)
        self.assertFalse(record["admitted"])
        self.assertIn("parser", record["errors"][0])

    def test_no_change_is_refused(self) -> None:
        record = self.admit(self.typed_copy("baseline"))
        self.assertFalse(record["admitted"])


class EngineTypedTests(TypedCase):
    def test_a_refused_typed_patch_never_reaches_the_orchestrator(self) -> None:
        from core.application.orchestrator import EvaluationOrchestrator
        from dail_demo.engine import run_evaluate

        folder = self.typed_copy("baseline")
        with (folder / "main.tf").open("a", encoding="utf-8") as handle:
            handle.write('\nresource "aws_security_group_rule" "broken" {\n  type = "ingress"\n')
        with mock.patch.object(EvaluationOrchestrator, "evaluate", side_effect=AssertionError("reached DAIL")):
            outcome = run_evaluate("canonical", str(folder), environ=self.environ, terraform=_ok_gate())
        self.assertEqual(outcome.exit_code, 2)
        self.assertTrue(outcome.trace["refused_before_dail"])
        self.assertIsNone(outcome.trace["conditions"])
        self.assertEqual(outcome.trace["candidate_source"], "TYPED")

    def test_a_gate_refusal_is_reported_with_the_gates_reason(self) -> None:
        from core.application.orchestrator import EvaluationOrchestrator
        from dail_demo.engine import run_evaluate
        from llm.validation.patch import TerraformCheck

        def refusing(directory: Path) -> TerraformCheck:
            return TerraformCheck(False, "Error: Unclosed configuration block (main.tf:150)", {})

        with mock.patch.object(EvaluationOrchestrator, "evaluate", side_effect=AssertionError("reached DAIL")):
            outcome = run_evaluate(
                "canonical", str(self.typed_copy("patch_safe")), environ=self.environ, terraform=refusing
            )
        self.assertEqual(outcome.trace["admission"]["stage"], "terraform_validate")
        self.assertIn("Unclosed configuration block", outcome.trace["admission"]["errors"][0])

    def test_the_typed_regression_copy_gives_the_regression_decisions(self) -> None:
        from dail_demo.engine import run_evaluate

        gate_calls: list[Path] = []
        typed = run_evaluate(
            "canonical", str(self.typed_copy("patch_regression")), environ=self.environ,
            terraform=_ok_gate(gate_calls),
        )
        fixed = run_evaluate("canonical", "regression", environ=self.environ)
        self.assertEqual(typed.trace["candidate_source"], "TYPED")
        self.assertIn("+++ b/main.tf", typed.trace["diff"])
        self.assertTrue(gate_calls)
        for key in ("C", "A"):
            with self.subTest(condition=key):
                self.assertEqual(typed.trace["comparison"][key], fixed.trace["comparison"][key])
                self.assertEqual(  # the detail names per-run result ids; the rest must match
                    [(b["code"], b["decision"], b["target"]) for b in typed.trace["conditions"][key]["decision"]["blocking"]],
                    [(b["code"], b["decision"], b["target"]) for b in fixed.trace["conditions"][key]["decision"]["blocking"]],
                )


class RealGateTypedTests(TypedCase):
    def setUp(self) -> None:
        mirror = mirror_environment()["DAIL_TERRAFORM_MIRROR"]  # skips before anything is created
        super().setUp()
        self.environ["DAIL_TERRAFORM_MIRROR"] = mirror

    def test_a_syntax_error_is_refused_before_dail_with_terraforms_reason(self) -> None:
        from core.application.orchestrator import EvaluationOrchestrator
        from dail_demo.engine import run_evaluate

        folder = self.typed_copy("baseline")
        with (folder / "main.tf").open("a", encoding="utf-8") as handle:
            handle.write('\nresource "aws_security_group_rule" "broken" {\n  type = "ingress"\n')
        with mock.patch.object(EvaluationOrchestrator, "evaluate", side_effect=AssertionError("reached DAIL")):
            outcome = run_evaluate("canonical", str(folder), environ=self.environ)
        self.assertEqual(outcome.exit_code, 2)
        admission = outcome.trace["admission"]
        self.assertEqual(admission["stage"], "terraform_validate")
        self.assertIn("Error:", admission["errors"][0])
        self.assertEqual(admission["terraform_validate"]["versions"]["terraform"], "1.15.8")
        print(f"\n  Terraform's reason: {admission['errors'][0]}", end="")

    def test_the_typed_regression_copy_gives_the_regression_decisions(self) -> None:
        from dail_demo.engine import run_evaluate

        typed = run_evaluate("canonical", str(self.typed_copy("patch_regression")), environ=self.environ)
        fixed = run_evaluate("canonical", "regression", environ=self.environ)
        self.assertEqual(typed.exit_code, 0, typed.trace.get("admission"))
        for key in ("C", "A"):
            with self.subTest(condition=key):
                self.assertEqual(typed.trace["comparison"][key], fixed.trace["comparison"][key])


if __name__ == "__main__":
    unittest.main()

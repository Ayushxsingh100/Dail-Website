"""Generation end to end with DAIL's ``FakeProvider`` (B work package §3.3, §3.4). No network.

The valid reply is the canonical safe repair written as DAIL's response schema: its patch is the
resource blocks that differ between DAIL's fixtures ``baseline`` and ``patch_safe`` (taken from
the fixture files, not typed here). An invalid reply must never reach the orchestrator.
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest import mock

from tests.support import DataDirCase, assert_no_key, dail_root
from tests.test_typed import _ok_gate


class GenerateTests(DataDirCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dail = dail_root()
        fixtures = cls.dail / "fixtures" / "canonical_regression"
        from dail_demo.evaluate_core import typed_response

        safe = typed_response(fixtures / "baseline", fixtures / "patch_safe")
        cls.safe_reply = json.dumps(
            {
                "schema_version": safe.schema_version,
                "status": "PATCH",
                "summary": "remove the public SSH rule",
                "patch": safe.patch,
                "changed_addresses": list(safe.changed_addresses),
                "assumptions": [],
                "rationale": "the SSH rule admits 0.0.0.0/0",
            }
        )
        cls.expected_c = json.loads((fixtures / "patch_safe" / "expected.json").read_text(encoding="utf-8"))

    def generate(self, script: list[Any], attempts: int = 3) -> Any:
        from dail_demo.generate import run_generate
        from llm.adapter.fake import FakeProvider

        self.provider = FakeProvider(script)
        return run_generate(
            "canonical",
            attempts=attempts,
            environ=self.environ,
            provider=self.provider,
            terraform=_ok_gate(),
            context_window=131072,
        )

    @staticmethod
    def reply(text: str) -> Any:
        from llm.adapter.provider import ProviderReply

        return ProviderReply(text=text, latency_ms=1.0, token_usage={"input": 1, "output": 1})

    def test_an_invalid_reply_never_reaches_the_orchestrator(self) -> None:
        from core.application.orchestrator import EvaluationOrchestrator

        with mock.patch.object(EvaluationOrchestrator, "evaluate", side_effect=AssertionError("reached DAIL")):
            outcome = self.generate([self.reply("not json"), self.reply("{}"), self.reply("[1]")])
        generation = outcome.trace["generation"]
        self.assertEqual(outcome.exit_code, 2)
        self.assertEqual(generation["status"], "FAILED")
        self.assertEqual(generation["failure_class"], "INVALID_OUTPUT")
        self.assertEqual(len(generation["attempts"]), 3)
        self.assertTrue(all(a["parse_errors"] for a in generation["attempts"]))
        self.assertIsNone(outcome.trace["conditions"])

    def test_a_patch_the_validator_refuses_never_reaches_the_orchestrator(self) -> None:
        from core.application.orchestrator import EvaluationOrchestrator

        bad = json.loads(self.safe_reply)
        bad["patch"] = bad["patch"].replace("{", '{\n  provisioner "local-exec" {\n    command = "id"\n  }', 1)
        with mock.patch.object(EvaluationOrchestrator, "evaluate", side_effect=AssertionError("reached DAIL")):
            outcome = self.generate([self.reply(json.dumps(bad))])
        row = outcome.trace["generation"]["attempts"][0]
        self.assertEqual(row["failure_class"], "POLICY_VIOLATION")
        self.assertTrue(row["validation_errors"])
        self.assertEqual(len(outcome.trace["generation"]["attempts"]), 1)  # not retryable (§23)

    def test_a_valid_reply_is_evaluated_under_c_and_a(self) -> None:
        outcome = self.generate([self.reply(self.safe_reply)])
        trace = outcome.trace
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(trace["candidate_source"], "LLM")
        self.assertEqual(trace["generation"]["status"], "PATCH")
        self.assertIn(trace["conditions"]["C"]["decision"]["type"], self.expected_c["decision"]["allowed"])
        self.assertIsNotNone(trace["conditions"]["A"]["decision"])
        self.assertIn("+++ b/", trace["diff"])
        self.assertEqual(trace["generation"]["config"]["prompt_version"], "dail-repair-prompt-3")
        self.assertEqual(trace["generation"]["config"]["temperature"], 0.7)
        self.assertEqual(trace["generation"]["config"]["top_p"], 0.95)
        self.assertEqual(len(self.provider.calls), 1)

    def test_an_invalid_then_a_valid_reply(self) -> None:
        outcome = self.generate([self.reply("not json"), self.reply(self.safe_reply)])
        attempts = outcome.trace["generation"]["attempts"]
        self.assertEqual([a["failure_class"] for a in attempts], ["INVALID_OUTPUT", None])
        self.assertEqual(outcome.trace["conditions"]["C"]["decision"]["type"], "PROMOTE")

    def test_a_provider_failure_is_recorded_not_raised(self) -> None:
        from llm.adapter.provider import ProviderError
        from llm.schemas.records import FailureClass

        outcome = self.generate([ProviderError(FailureClass.RATE_LIMIT, "free-tier limit")])
        generation = outcome.trace["generation"]
        self.assertEqual(generation["failure_class"], "RATE_LIMIT")
        self.assertEqual(generation["failure_source"], "provider")

    def test_attempts_outside_1_to_3_are_refused(self) -> None:
        from dail_demo.settings import SetupError

        for attempts in (0, 4):
            with self.subTest(attempts=attempts), self.assertRaises(SetupError):
                self.generate([], attempts=attempts)

    def test_no_key_in_any_generation_trace(self) -> None:
        outcome = self.generate([self.reply("not json"), self.reply(self.safe_reply)])
        assert_no_key(self, outcome.path.read_text(encoding="utf-8"), str(outcome.path))


class GenerateCommandTests(DataDirCase):
    """``python -m dail_demo generate`` without a key: a one-line reason, no call, no crash."""

    @classmethod
    def setUpClass(cls) -> None:
        dail_root()

    def test_missing_key(self) -> None:
        import subprocess
        import sys

        from dail_demo.gemini import NO_KEY
        from tests.support import REPO_ROOT

        environ = dict(self.environ)
        environ.pop("GEMINI_API_KEY")
        done = subprocess.run(
            [sys.executable, "-m", "dail_demo", "generate", "--scenario", "canonical"],
            cwd=REPO_ROOT, env=environ, capture_output=True, text=True, check=False,
        )
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn(NO_KEY, done.stdout)
        self.assertNotIn("Traceback", done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()

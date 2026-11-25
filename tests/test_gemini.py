"""The Gemini adapter against a local fake server (B work package §3.3, §3.4). No network.

The fake server (``http.server`` on 127.0.0.1, in this test) answers models.get and
generateContent with canned success, 401, 403, 429, 404, a malformed body, an empty candidate
list and a delay. Each failure must give its DAIL failure class and a one-line reason that never
contains the key; the key must arrive only in the ``x-goog-api-key`` header, never in a URL.
"""

from __future__ import annotations

import io
import json
import socket
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from tests.support import FAKE_KEY, DataDirCase, assert_no_key, assert_no_key_in_dir, dail_root

MODEL = "fake-flash"


class FakeGemini(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.mode = "ok"
        self.reply_text = json.dumps({"status": "NO_SOLUTION"})
        self.seen: list[dict[str, Any]] = []

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class Handler(BaseHTTPRequestHandler):
    server: FakeGemini

    def log_message(self, *args: Any) -> None:  # keep the test output clean
        pass

    def _send(self, status: int, body: bytes | str) -> None:
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except ConnectionError:  # the client gave up first (the time-out case)
            pass

    def _record(self, body: bytes) -> None:
        self.server.seen.append(
            {"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body}
        )

    def do_GET(self) -> None:  # noqa: N802
        self._record(b"")
        if self.server.mode in ("401", "403"):
            return self._send(int(self.server.mode), '{"error": {"code": "authentication"}}')
        if self.path == f"/v1beta/models/{MODEL}":
            return self._send(
                200,
                json.dumps(
                    {
                        "name": f"models/{MODEL}",
                        "version": "001",
                        "inputTokenLimit": 1048576,
                        "outputTokenLimit": 65536,
                        "supportedGenerationMethods": ["generateContent", "countTokens"],
                    }
                ),
            )
        return self._send(404, '{"error": {"code": "model_not_found"}}')

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self._record(body)
        mode = self.server.mode
        if mode == "delay":
            time.sleep(1.5)
            return self._send(200, "{}")
        if mode in ("401", "403", "429", "500"):
            return self._send(int(mode), '{"error": {"code": "x"}}')
        if mode == "malformed":
            return self._send(200, "this is not json {")
        if mode == "empty":
            return self._send(200, json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}))
        return self._send(
            200,
            json.dumps(
                {
                    "candidates": [
                        {"content": {"role": "model", "parts": [{"text": self.server.reply_text}]},
                         "finishReason": "STOP"}
                    ],
                    "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 80},
                    "modelVersion": f"{MODEL}-001",
                }
            ),
        )


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        dail_root()  # the provider seam's types are DAIL's
        cls.server = FakeGemini()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        self.server.mode = "ok"
        self.server.seen.clear()

    def provider(self, key: str = FAKE_KEY, endpoint: str | None = None) -> Any:
        from dail_demo.gemini import GeminiProvider

        return GeminiProvider(api_key=key, model=MODEL, endpoint=endpoint or self.server.endpoint)

    def call(self, timeout: float = 5.0) -> Any:
        from llm.adapter.provider import ProviderCall
        from llm.prompts.templates import PROMPT_VERSION
        from llm.schemas.records import LLMConfig, LLMRequest
        from llm.schemas.repair_response import RESPONSE_JSON_SCHEMA, RESPONSE_SCHEMA_VERSION
        from datetime import UTC, datetime

        config = LLMConfig(
            provider="gemini", model_name=MODEL, model_version=f"models/{MODEL}", temperature=0.7,
            top_p=0.95, seed=1, max_output_tokens=256, timeout_seconds=timeout,
            retry_policy_id="test", prompt_version=PROMPT_VERSION,
            response_schema_version=RESPONSE_SCHEMA_VERSION,
        )
        request = LLMRequest(
            request_id="00000000-0000-4000-8000-000000000001",
            attempt_id="00000000-0000-4000-8000-000000000002",
            attempt_number=1, parent_state_id="00000000-0000-4000-8000-000000000003",
            trusted_state_hash="0" * 64, context_version="c", context_hash="0" * 64,
            prompt_hash="0" * 64, prompt_version=PROMPT_VERSION, template_hash="0" * 64,
            model_config=config.to_dict(), created_at=datetime.now(UTC),
        )
        return ProviderCall(request=request, system="system text", task="task text",
                            response_schema=RESPONSE_JSON_SCHEMA, config=config)

    def failure(self, mode: str, timeout: float = 5.0) -> Any:
        from llm.adapter.provider import ProviderError

        self.server.mode = mode
        with self.assertRaises(ProviderError) as raised:
            self.provider().generate(self.call(timeout))
        error = raised.exception
        assert_no_key(self, str(error), "the error message")
        self.assertNotIn("\n", error.detail)
        return error


class ProviderTests(ServerCase):
    def test_success_returns_the_reply_text_and_usage(self) -> None:
        provider = self.provider()
        reply = provider.generate(self.call())
        self.assertEqual(reply.text, self.server.reply_text)
        self.assertEqual(dict(reply.token_usage), {"input": 1200, "output": 80})
        self.assertEqual(provider.model_versions, [f"{MODEL}-001"])
        body = json.loads(self.server.seen[-1]["body"])
        config = body["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual((config["temperature"], config["topP"], config["seed"]), (0.7, 0.95, 1))
        self.assertIn("responseJsonSchema", config)
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "system text")
        self.assertEqual(body["contents"][0]["parts"][0]["text"], "task text")

    def test_the_key_is_sent_only_in_the_header(self) -> None:
        self.provider().generate(self.call())
        self.provider().check_model()
        for seen in self.server.seen:
            headers = {k.lower(): v for k, v in seen["headers"].items()}
            self.assertEqual(headers.get("x-goog-api-key"), FAKE_KEY)
            assert_no_key(self, seen["path"], "the URL")
            assert_no_key(self, seen["body"].decode(), "the body")

    def test_each_failure_class_has_its_one_line_reason(self) -> None:
        cases = {
            "401": ("UNSUPPORTED", "refused the API key (HTTP 401)"),
            "403": ("UNSUPPORTED", "refused the API key (HTTP 403)"),
            "429": ("RATE_LIMIT", "rate limit"),
            "500": ("TRANSIENT_ERROR", "unavailable (HTTP 500)"),
            "malformed": ("INVALID_OUTPUT", "not JSON"),
            "empty": ("INVALID_OUTPUT", "blockReason SAFETY"),
        }
        for mode, (failure, text) in cases.items():
            with self.subTest(mode=mode):
                error = self.failure(mode)
                self.assertEqual(error.failure_class.value, failure)
                self.assertIn(text, error.detail)

    def test_a_delay_is_a_timeout(self) -> None:
        error = self.failure("delay", timeout=0.3)
        self.assertEqual(error.failure_class.value, "TIMEOUT")
        self.assertIn("no answer", error.detail)

    def test_no_network_is_a_transient_error(self) -> None:
        from llm.adapter.provider import ProviderError

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed = probe.getsockname()[1]
        with self.assertRaises(ProviderError) as raised:
            self.provider(endpoint=f"http://127.0.0.1:{closed}").generate(self.call())
        self.assertEqual(raised.exception.failure_class.value, "TRANSIENT_ERROR")
        self.assertIn("no network", raised.exception.detail)

    def test_a_missing_key_fails_before_any_request(self) -> None:
        from dail_demo.gemini import NO_KEY
        from llm.adapter.provider import ProviderError

        for key in ("", "   "):
            with self.subTest(key=repr(key)), self.assertRaises(ProviderError) as raised:
                self.provider(key=key).generate(self.call())
            self.assertEqual(raised.exception.failure_class.value, "UNSUPPORTED")
            self.assertEqual(raised.exception.detail, NO_KEY)
        self.assertEqual(self.server.seen, [])

    def test_the_model_check(self) -> None:
        from llm.adapter.provider import ProviderError

        facts = self.provider().check_model()
        self.assertEqual(facts["name"], f"models/{MODEL}")
        self.assertEqual(facts["input_token_limit"], 1048576)
        from dail_demo.gemini import GeminiProvider

        missing = GeminiProvider(api_key=FAKE_KEY, model="no-such-model", endpoint=self.server.endpoint)
        with self.assertRaises(ProviderError) as raised:
            missing.check_model()
        self.assertIn("HTTP 404", raised.exception.detail)

    def test_the_endpoint_must_be_https_or_loopback(self) -> None:
        from dail_demo.gemini import GeminiProvider

        for endpoint in ("http://example.com", "ftp://127.0.0.1", "https://x.test/path", "https://u:p@x.test"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                GeminiProvider(api_key=FAKE_KEY, model=MODEL, endpoint=endpoint)
        GeminiProvider(api_key=FAKE_KEY, model=MODEL, endpoint="https://generativelanguage.googleapis.com")

    def test_the_provider_never_shows_the_key(self) -> None:
        provider = self.provider()
        assert_no_key(self, repr(provider), "repr")
        assert_no_key(self, str(vars(provider).get("model")), "attributes")


class GenerateThroughFakeServerTests(ServerCase, DataDirCase):
    """The whole ``generate`` flow with the Gemini provider and the fake server: each failure gives
    its one-line reason in the summary and the trace, nothing crashes, and the key appears in no
    output, trace or log."""

    def setUp(self) -> None:
        ServerCase.setUp(self)
        DataDirCase.setUp(self)

    def tearDown(self) -> None:
        DataDirCase.tearDown(self)

    def run_mode(self, mode: str) -> tuple[Any, str]:
        from dail_demo.generate import run_generate, summary_lines
        from dail_demo.settings import gemini_settings
        from tests.test_typed import _ok_gate

        import dataclasses

        self.server.mode = mode
        settings = dataclasses.replace(
            gemini_settings(), model=MODEL, endpoint=self.server.endpoint, timeout_seconds=0.5
        )
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            outcome = run_generate(
                "canonical", attempts=2, environ=self.environ, settings=settings, terraform=_ok_gate()
            )
            for line in summary_lines(outcome.trace, outcome.path):
                print(line)
        text = out.getvalue() + err.getvalue()
        assert_no_key(self, text, "the output")
        assert_no_key(self, outcome.path.read_text(encoding="utf-8"), "the trace")
        return outcome, text

    def test_each_failure_is_reported_and_nothing_reaches_dail(self) -> None:
        from core.application.orchestrator import EvaluationOrchestrator
        from unittest import mock

        cases = {
            "401": "refused the API key (HTTP 401)",
            "429": "rate limit",
            "malformed": "INVALID_OUTPUT",
            "delay": "TIMEOUT",
        }
        for mode, text in cases.items():
            with self.subTest(mode=mode), mock.patch.object(
                EvaluationOrchestrator, "evaluate", side_effect=AssertionError("reached DAIL")
            ):
                outcome, output = self.run_mode(mode)
                self.assertEqual(outcome.exit_code, 2)
                self.assertTrue(outcome.trace["refused_before_dail"])
                self.assertIn(text, output + json.dumps(outcome.trace))
        self.assertGreater(assert_no_key_in_dir(self, self.data), 0)


if __name__ == "__main__":
    unittest.main()

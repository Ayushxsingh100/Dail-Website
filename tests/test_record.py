"""``python -m dail_demo record`` and the recorded runs in ``site/runs/`` (C work package §3, §5).

* a trace that contains the key's value, its first 6 characters or a local path is refused, and
  nothing is written for it;
* every published trace is a real ``dail-live-trace/1`` with the demo label, holds no key-like
  string and no local path, and ``runs/index.json`` lists exactly the traces, with their decisions.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.support import FAKE_KEY, REPO_ROOT, assert_no_key

RUNS = REPO_ROOT / "site" / "runs"
GOOGLE_KEY = re.compile(r"AIza[0-9A-Za-z_\-]{30,}")


class PublishableTests(unittest.TestCase):
    def test_a_trace_with_the_key_is_refused(self) -> None:
        from dail_demo.record import RecordError, publishable

        environ = {"GEMINI_API_KEY": FAKE_KEY}
        for text in (f'{{"x": "{FAKE_KEY}"}}', f'{{"x": "{FAKE_KEY[:6]}"}}'):
            with self.subTest(text=text[:12]), self.assertRaises(RecordError):
                publishable(text, environ)
        publishable('{"x": "clean"}', environ)

    def test_a_trace_with_a_local_path_is_refused(self) -> None:
        from dail_demo.record import RecordError, publishable

        for text in ('"C:\\\\Users\\\\someone"', '"X:/dail-live-data/runs"', '"/home/someone/x"', '"/tmp/x"'):
            with self.subTest(text=text), self.assertRaises(RecordError):
                publishable(text, {})
        publishable('{"patch": "a\\\\n b", "url": "https://example.org/x"}', {})

    def test_the_recorder_writes_nothing_for_a_refused_trace(self) -> None:
        from dail_demo.record import RecordError, Recorder

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "runs"
            recorder = Recorder({"GEMINI_API_KEY": FAKE_KEY}, out)
            with self.assertRaises(RecordError):
                recorder.add("leak", {"candidate": FAKE_KEY})
            self.assertEqual(recorder.staging, [])
            self.assertFalse(out.exists())


class PublishedRunsTests(unittest.TestCase):
    def test_every_trace_is_clean_and_labelled(self) -> None:
        from dail_demo import DEMO_LABEL
        from dail_demo.record import _LOCAL_PATH

        files = sorted(p for p in RUNS.glob("*.json") if p.name != "index.json")
        self.assertGreaterEqual(len(files), 11)
        for path in files:
            with self.subTest(trace=path.name):
                text = path.read_text(encoding="utf-8")
                trace = json.loads(text)
                self.assertEqual(trace["schema"], "dail-live-trace/1")
                self.assertEqual(trace["label"], DEMO_LABEL)
                self.assertIsNone(GOOGLE_KEY.search(text))
                self.assertIsNone(_LOCAL_PATH.search(text))
                assert_no_key(self, text, path.name)

    def test_the_index_lists_exactly_the_traces(self) -> None:
        index = json.loads((RUNS / "index.json").read_text(encoding="utf-8"))
        listed = {run["file"] for run in index["runs"]}
        present = {p.name for p in RUNS.glob("*.json") if p.name != "index.json"}
        self.assertEqual(listed, present)
        for run in index["runs"]:
            trace = json.loads((RUNS / run["file"]).read_text(encoding="utf-8"))
            with self.subTest(run=run["file"]):
                self.assertEqual(run["source"], trace["candidate_source"])
                self.assertEqual(run["scenario_id"], trace["scenario"]["scenario_id"])
                for key, entry in (trace.get("comparison") or {}).items():
                    self.assertEqual(run["decisions"][key], entry["decision"])
                    self.assertEqual(run["check_counts"][key], entry["check_count"])

    def test_the_canonical_runs_match_dails_fixture_expectations(self) -> None:
        index = {r["file"]: r for r in json.loads((RUNS / "index.json").read_text(encoding="utf-8"))["runs"]}
        self.assertEqual(index["canonical--safe.json"]["decisions"]["C"], "PROMOTE")
        self.assertEqual(index["canonical--regression.json"]["decisions"]["C"], "REJECT")
        self.assertEqual(index["canonical--regression.json"]["decisions"]["A"], "PROMOTE")

    def test_llm_runs_record_the_model_and_every_attempt(self) -> None:
        for run in json.loads((RUNS / "index.json").read_text(encoding="utf-8"))["runs"]:
            if run["source"] != "LLM":
                continue
            with self.subTest(run=run["file"]):
                trace = json.loads((RUNS / run["file"]).read_text(encoding="utf-8"))
                generation = trace["generation"]
                self.assertEqual(run["model"], generation["settings"]["model"])
                self.assertEqual(generation["config"]["provider"], "gemini")
                self.assertTrue(generation["attempts"])


if __name__ == "__main__":
    unittest.main()

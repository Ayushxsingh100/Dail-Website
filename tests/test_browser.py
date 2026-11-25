"""The browser feasibility gate and the live page in headless Chromium (C work package §1, §5;
D-21, D-22).

``tests/browser/gate.mjs`` (Node and Playwright, dev-only) serves ``site/`` on 127.0.0.1, loads the
self-hosted Pyodide and the bundled, unmodified DAIL, and runs ``evaluate_fixed`` on the canonical
patches and every curated scenario's fixed patch. Each browser trace must equal the native
engine's on: decision type and reason, blocking conditions, check counts for C and A, affected and
carried-forward invariants, change types (and, beyond the work package's list, every verification
result and the proof plan).

Skipped locally when Node or the Playwright package is missing; required on CI.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.support import ON_CI, REPO_ROOT, DataDirCase, dail_root, terrapreserve_root

BROWSER_DIR = REPO_ROOT / "tests" / "browser"
CASES = ("canonical:safe", "canonical:regression") + tuple(
    f"{sid}:fixed"
    for sid in ("tp-v1-F2-0027", "tp-v1-F2-0040", "tp-v1-F4-0079", "tp-v1-F4-0092", "tp-v1-F4-0093",
                "tp-v1-F8-0192", "tp-v1-F8-0196")
)


def node_ready() -> str:
    node = shutil.which("node")
    missing = None
    if node is None:
        missing = "node is not on PATH"
    elif not (BROWSER_DIR / "node_modules" / "playwright").is_dir():
        missing = "the Playwright package is not installed (npm ci in tests/browser)"
    if missing:
        if ON_CI:
            raise AssertionError(f"{missing} on CI, which is meant to provide it")
        raise unittest.SkipTest(missing)
    assert node is not None
    return node


def essentials(trace: dict[str, Any]) -> dict[str, Any]:
    """The fields the gate compares, per condition, all copied from DAIL's records."""
    found = {}
    for key, section in trace["conditions"].items():
        decision = section["decision"]
        impact = section["impact"] or {}
        found[key] = {
            "decision": decision["type"],
            "reason": decision["reason"],
            "blocking": sorted((b["code"], b["decision"], b["target"]) for b in decision["blocking"]),
            "check_count": section["check_count"],
            "affected": sorted(
                (a["invariant_id"], tuple(a["impact_types"])) for a in impact.get("affected", [])
            ),
            "carried_forward": sorted(c["invariant_id"] for c in impact.get("carry_forward_candidates", [])),
            "proof_plan": sorted((p["invariant_id"], p["source"]) for p in section["proof_plan"] or []),
            "changes": sorted((c["address"], c["change_type"]) for c in section["changed_resources"] or []),
            "verification": sorted((v["target"], v["result"], v["reason"]) for v in section["verification"]),
        }
    return found


def run_gate(cases: tuple[str, ...]) -> dict[str, Any]:
    node = node_ready()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "gate.json"
        done = subprocess.run(
            [node, str(BROWSER_DIR / "gate.mjs"), str(REPO_ROOT / "site"), str(out), sys.executable, *cases],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=900,
        )
        if done.returncode != 0:
            raise AssertionError(f"the browser gate failed:\n{done.stdout}\n{done.stderr}")
        print("\n" + done.stdout.strip(), end="")
        return json.loads(out.read_text(encoding="utf-8"))


class BrowserGateTests(DataDirCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dail = dail_root()
        cls.tp = terrapreserve_root()
        if not (REPO_ROOT / "site" / "vendor" / "files.json").is_file():
            raise AssertionError("site/vendor is not built: run python -m dail_demo bundle")
        cls.result = run_gate(CASES)

    def test_dail_loads_in_the_browser(self) -> None:
        self.assertIn("3.12", self.result["python"])
        errors = [line for line in self.result["console"] if line.startswith(("error", "pageerror"))]
        self.assertEqual(errors, [])

    def test_browser_decisions_equal_the_native_engine(self) -> None:
        from dail_demo.engine import run_evaluate

        for case in CASES:
            scenario, patch = case.split(":")
            with self.subTest(case=case):
                answer = self.result["traces"][case]
                self.assertTrue(answer["ok"], answer.get("error"))
                browser = answer["value"]
                native = run_evaluate(scenario, patch, environ=self.environ).trace
                self.assertEqual(essentials(browser), essentials(native))
                self.assertEqual(browser["candidate_source"], "FIXED_PATCH")
                self.assertEqual(browser["versions"]["dail_commit"], native["versions"]["dail_commit"])


if __name__ == "__main__":
    unittest.main()

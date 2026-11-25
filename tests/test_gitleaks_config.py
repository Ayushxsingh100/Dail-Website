"""``.gitleaks.toml`` keeps every default rule and allows one thing only (D-30)."""

from __future__ import annotations

import re
import tomllib
import unittest

from tests.support import REPO_ROOT


class GitleaksConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = tomllib.loads((REPO_ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
        self.allow = self.config["allowlist"]

    def test_the_default_rules_stay_on_and_nothing_else_is_allowed(self) -> None:
        self.assertEqual(self.config["extend"], {"useDefault": True})
        self.assertEqual(set(self.config), {"title", "extend", "allowlist"})
        self.assertEqual(set(self.allow), {"description", "condition", "regexTarget", "paths", "regexes"})
        self.assertEqual((self.allow["condition"], self.allow["regexTarget"]), ("AND", "line"))
        self.assertEqual((len(self.allow["paths"]), len(self.allow["regexes"])), (1, 1))
        self.assertFalse((REPO_ROOT / ".gitleaksignore").exists())

    def test_only_an_edge_key_hash_line_matches(self) -> None:
        line = re.compile(self.allow["regexes"][0])
        self.assertTrue(line.search('          "edge_key": "' + "0a" * 32 + '",'))
        for other in (
            '"api_key": "' + "0a" * 32 + '",',
            '"edge_key": "AIza' + "x" * 35 + '",',
            '"edge_key": "' + "0a" * 31 + '",',
            '"edge_key": "' + "0a" * 32 + '", "api_key": "x"',
        ):
            with self.subTest(line=other[:24]):
                self.assertIsNone(line.search(other))

    def test_only_recorded_runs_match(self) -> None:
        path = re.compile(self.allow["paths"][0])
        self.assertTrue(path.search("site/runs/canonical--safe.json"))
        for other in ("site/index.html", "dail_demo/gemini.py", "site/runs/x/y.json", "other/site/runs/a.json"):
            with self.subTest(path=other):
                self.assertIsNone(path.search(other))


if __name__ == "__main__":
    unittest.main()

"""``dail_demo/evaluate_core.py`` uses only DAIL and the standard library (B work package §2.3b).

Package C runs it in the browser under Pyodide, so it may import nothing else and none of
``subprocess``, ``threading``, ``socket``, ``urllib`` or ``os`` (no environment variables). No module
of DAIL Live may import DAIL's ``tests`` package. These tests read the source with ``ast``; they
need no DAIL checkout.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE = REPO_ROOT / "dail_demo" / "evaluate_core.py"
DAIL_PACKAGES = {"core", "llm", "evidence", "experiments"}
FORBIDDEN = {"subprocess", "threading", "socket", "urllib", "os", "multiprocessing", "asyncio", "http"}


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.append("." * node.level + (node.module or ""))
            else:
                found.append(node.module or "")
    return found


def check_core(path: Path) -> list[str]:
    """Every problem with the core's imports and names (empty when it follows the rule)."""
    problems = []
    for name in imported_modules(path):
        top = name.split(".")[0]
        if name.startswith("."):
            problems.append(f"relative import {name}")
        elif top in FORBIDDEN:
            problems.append(f"forbidden module {name}")
        elif top == "__future__":
            continue
        elif top not in DAIL_PACKAGES and top not in sys.stdlib_module_names:
            problems.append(f"{name} is neither DAIL nor the standard library")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv", "putenv"):
            problems.append(f"uses .{node.attr}")
        if isinstance(node, ast.Name) and node.id in ("environ", "getenv", "__import__"):
            problems.append(f"uses {node.id}")
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("eval", "exec"):
            problems.append(f"calls {node.func.id}")  # type: ignore[attr-defined]
    return problems


class CoreImportTests(unittest.TestCase):
    def test_the_core_imports_only_dail_and_the_standard_library(self) -> None:
        self.assertEqual(check_core(CORE), [])

    def test_the_core_imports_dail(self) -> None:
        tops = {name.split(".")[0] for name in imported_modules(CORE)}
        self.assertTrue(tops & DAIL_PACKAGES)

    def test_the_check_catches_each_forbidden_import(self) -> None:
        import tempfile

        for line in (
            "import subprocess",
            "import threading",
            "import socket",
            "from urllib import request",
            "import urllib.request",
            "import os",
            "from os import environ",
            "from dail_demo import settings",
            "from tests import support",
        ):
            with self.subTest(line=line), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "core.py"
                path.write_text(line + "\n", encoding="utf-8")
                self.assertNotEqual(check_core(path), [], line)

    def test_the_check_catches_environment_access(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "core.py"
            path.write_text("import sys\nvalue = sys.modules['os'].environ\n", encoding="utf-8")
            self.assertIn("uses .environ", check_core(path))

    def test_no_module_imports_dails_tests_package(self) -> None:
        for path in sorted((REPO_ROOT / "dail_demo").glob("*.py")):
            for name in imported_modules(path):
                with self.subTest(module=path.name, imported=name):
                    self.assertNotEqual(name.split(".")[0], "tests")


if __name__ == "__main__":
    unittest.main()

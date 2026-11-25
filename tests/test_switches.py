"""The safety switches are on in exactly one reviewed file each (PLAN §3.4; B work package §2.2).

* ``promotion.automatic_enabled`` is turned on only in ``config/promotion.toml``;
* ``llm.generation_enabled`` only in ``config/llm.toml``.

The scan covers every text file of the repository; it needs no DAIL. With DAIL, the merged
configuration is checked as well: DAIL's own files keep both switches off, and only the demo's
copy turns them on.
"""

from __future__ import annotations

import os
import re
import subprocess
import unittest
from pathlib import Path

from tests.support import REPO_ROOT

SWITCHES = {
    "automatic_enabled": REPO_ROOT / "config" / "promotion.toml",
    "generation_enabled": REPO_ROOT / "config" / "llm.toml",
}
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv"}
TEXT_SUFFIXES = {".toml", ".py", ".json", ".yml", ".yaml", ".cfg", ".ini", ".txt", ".md", ".env"}


def repository_files(root: Path) -> list[Path]:
    """This repository's own files, tracked and untracked (not ignored), as git lists them; git
    does not descend into a nested repository (CI's ``_dail`` and ``_tp`` checkouts). Outside a
    git repository (the self-test below): every file under ``root``."""
    top = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )
    if top.returncode == 0 and Path(top.stdout.strip()).resolve() == Path(root).resolve():
        listed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"],
            capture_output=True, text=True, check=True,
        )
        return [Path(root) / line for line in listed.stdout.splitlines() if line and not line.endswith("/")]
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        found.extend(Path(dirpath) / name for name in filenames)
    return found


def files_turning_on(key: str, root: Path = REPO_ROOT) -> list[Path]:
    pattern = re.compile(rf"(?m)^\s*(?:\[?[a-z_.]*\]?\s*)?{key}\s*=\s*true\b")
    found = []
    for path in repository_files(root):
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".env":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if pattern.search(text):
            found.append(path.resolve())
    return sorted(found)


class SwitchTests(unittest.TestCase):
    def test_each_switch_is_on_in_its_reviewed_file_only(self) -> None:
        # the website bundles the same reviewed file for the browser (site/vendor/dail_live/config/);
        # that copy must be byte-identical to it
        bundled = REPO_ROOT / "site" / "vendor" / "dail_live" / "config"
        for key, reviewed in SWITCHES.items():
            with self.subTest(switch=key):
                found = files_turning_on(key)
                copy = (bundled / reviewed.name).resolve()
                self.assertEqual(sorted(set(found) - {copy}), [reviewed.resolve()])
                if copy in found:
                    self.assertEqual(copy.read_bytes(), reviewed.read_bytes())

    def test_the_scan_would_find_another_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "other.toml").write_text("automatic_enabled = true\n", encoding="utf-8")
            (Path(tmp) / "commented.toml").write_text("# automatic_enabled = true\n", encoding="utf-8")
            self.assertEqual(
                [p.name for p in files_turning_on("automatic_enabled", Path(tmp))], ["other.toml"]
            )


class MergedConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.support import dail_root

        cls.dail_root = dail_root()

    def test_dails_own_configuration_keeps_both_switches_off(self) -> None:
        from core.application.config import load_config

        config = load_config(self.dail_root / "config", "experiment", environ={})
        self.assertIs(config.get("promotion.automatic_enabled"), False)
        self.assertIs(config.get("llm.generation_enabled"), False)

    def test_the_demo_copy_turns_both_on(self) -> None:
        from dail_demo.settings import dail_config

        config = dail_config(self.dail_root)
        self.assertIs(config.get("promotion.automatic_enabled"), True)
        self.assertIs(config.get("llm.generation_enabled"), True)


if __name__ == "__main__":
    unittest.main()

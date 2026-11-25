"""``python -m dail_demo bundle`` and the committed ``site/vendor/`` (C work package §1, §5).

* every manifest's hashes match its files, with nothing missing or unlisted;
* nothing from DAIL's ``tests/`` is bundled;
* the bundled DAIL files are byte-identical to ``DAIL_ROOT`` at ``dail-v1.0``;
* the bundled scenario packs equal those DAIL's loader gives;
* Pyodide's files match their pinned SHA-256, and a changed file is refused;
* a fresh bundle reproduces the committed ``site/vendor/`` exactly.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT, dail_root, terrapreserve_root

VENDOR = REPO_ROOT / "site" / "vendor"
PARTS = ("dail", "dail_live", "scenarios", "pyodide/0.27.7")


class CommittedVendorTests(unittest.TestCase):
    """The committed site/vendor/ (no DAIL checkout needed)."""

    def test_every_manifest_matches(self) -> None:
        from dail_demo.bundle import check_manifest

        for part in PARTS:
            with self.subTest(part=part):
                self.assertEqual(check_manifest(VENDOR / part), [])

    def test_nothing_from_dails_tests_is_bundled(self) -> None:
        for path in (VENDOR / "dail").rglob("*"):
            relative = path.relative_to(VENDOR / "dail").as_posix()
            self.assertFalse(relative.split("/")[0] == "tests" or "/tests/" in f"/{relative}", relative)

    def test_pyodide_files_match_their_pins(self) -> None:
        from dail_demo.bundle import PYODIDE_FILES, sha256_file

        found = {p.name for p in (VENDOR / "pyodide" / "0.27.7").iterdir() if p.name != "MANIFEST.sha256"}
        self.assertEqual(found, set(PYODIDE_FILES))
        for name, digest in PYODIDE_FILES.items():
            with self.subTest(file=name):
                self.assertEqual(sha256_file(VENDOR / "pyodide" / "0.27.7" / name), digest)

    def test_files_json_lists_every_loaded_file_with_its_hash(self) -> None:
        from dail_demo.bundle import sha256_file

        listing = json.loads((VENDOR / "files.json").read_text(encoding="utf-8"))
        listed = {f["path"]: f["sha256"] for f in listing["files"]}
        present = {
            p.relative_to(VENDOR).as_posix(): p
            for part in ("dail", "dail_live", "scenarios")
            for p in (VENDOR / part).rglob("*")
            if p.is_file()
        }
        self.assertEqual(set(listed), set(present))
        for name, path in present.items():
            self.assertEqual(listed[name], sha256_file(path), name)

    def test_the_bundled_core_is_the_repositorys(self) -> None:
        for name in ("__init__.py", "evaluate_core.py", "browser.py"):
            with self.subTest(module=name):
                self.assertEqual(
                    (VENDOR / "dail_live" / "dail_demo" / name).read_bytes(),
                    (REPO_ROOT / "dail_demo" / name).read_bytes(),
                )


class BundleAgainstDailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dail = dail_root()
        cls.tp = terrapreserve_root()

    def test_bundled_dail_files_are_byte_identical_to_dail_root(self) -> None:
        from dail_demo.bundle import dail_files

        names = dail_files(self.dail)
        self.assertGreater(len(names), 150)
        for name in names:
            self.assertEqual((VENDOR / "dail" / name).read_bytes(), (self.dail / name).read_bytes(), name)
        bundled = {
            p.relative_to(VENDOR / "dail").as_posix()
            for p in (VENDOR / "dail").rglob("*")
            if p.is_file() and p.name not in ("MANIFEST.sha256", "VERSION.json")
        }
        self.assertEqual(bundled, set(names))
        version = json.loads((VENDOR / "dail" / "VERSION.json").read_text(encoding="utf-8"))
        from dail_demo.settings import git_commit

        self.assertEqual(version, {"dail_tag": "dail-v1.0", "dail_commit": git_commit(self.dail)})

    def test_a_fresh_bundle_reproduces_the_committed_vendor(self) -> None:
        import os

        from dail_demo.bundle import bundle, sha256_file

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            out = Path(tmp) / "vendor"
            summary = bundle(os.environ, pyodide=VENDOR / "pyodide" / "0.27.7", out=out)
            self.assertEqual(len(summary["scenarios"]), 8)
            fresh = {p.relative_to(out).as_posix(): sha256_file(p) for p in out.rglob("*") if p.is_file()}
            committed = {p.relative_to(VENDOR).as_posix(): sha256_file(p) for p in VENDOR.rglob("*") if p.is_file()}
            self.assertEqual(fresh, committed)

    def test_a_changed_pyodide_file_is_refused(self) -> None:
        import os

        from dail_demo.bundle import bundle
        from dail_demo.settings import SetupError

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            source = Path(tmp) / "pyodide"
            shutil.copytree(VENDOR / "pyodide" / "0.27.7", source)
            with (source / "pyodide.mjs").open("ab") as handle:
                handle.write(b"\n// changed\n")
            with self.assertRaises(SetupError) as raised:
                bundle(os.environ, pyodide=source, out=Path(tmp) / "vendor")
            self.assertIn("pyodide.mjs", str(raised.exception))


if __name__ == "__main__":
    unittest.main()

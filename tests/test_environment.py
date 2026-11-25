"""Tests for the startup checks (L0 work package §4).

No network, no real DAIL or TerraPreserve checkout and no Terraform binary
are needed: the pinned checkouts are temporary git repositories built here.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from dail_demo import environment
from dail_demo.environment import (
    DAIL_TAG,
    FAIL,
    PASS,
    TERRAPRESERVE_TAG,
    WARN,
    CheckResult,
    check_data_dir,
    check_gemini_key,
    check_pinned_checkout,
    check_python,
    check_terraform,
    exit_code,
    parse_python_version,
    parse_terraform_version,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FAKE_KEY = "TEST-KEY-123456"


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )


def make_repo(root: Path, tag: str | None) -> Path:
    """A git repository with one commit and, optionally, one tag at HEAD."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "DAIL Live tests")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "config", "tag.gpgsign", "false")
    _git(root, "config", "core.autocrlf", "false")
    (root / "README").write_text("fixture\n", encoding="utf-8")
    _git(root, "add", "README")
    _git(root, "commit", "-q", "-m", "fixture")
    if tag is not None:
        _git(root, "tag", tag)
    return root


class TempDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name).resolve()

    def tearDown(self) -> None:
        self._tmp.cleanup()


class PinnedCheckoutTests(TempDirTestCase):
    def check(self, root: Path | str | None, tag: str = DAIL_TAG) -> CheckResult:
        env = {} if root is None else {"DAIL_ROOT": str(root)}
        return check_pinned_checkout("dail_root", "DAIL_ROOT", tag, env)

    def test_right_tag_and_clean_tree_pass(self) -> None:
        repo = make_repo(self.tmp / "dail", DAIL_TAG)
        result = self.check(repo)
        self.assertEqual(result.status, PASS, result.detail)

    def test_terrapreserve_tag_passes_the_same_rule(self) -> None:
        repo = make_repo(self.tmp / "tp", TERRAPRESERVE_TAG)
        result = check_pinned_checkout(
            "terrapreserve_root",
            "TERRAPRESERVE_ROOT",
            TERRAPRESERVE_TAG,
            {"TERRAPRESERVE_ROOT": str(repo)},
        )
        self.assertEqual(result.status, PASS, result.detail)

    def test_wrong_tag_fails_and_names_the_tags_found(self) -> None:
        repo = make_repo(self.tmp / "dail", "dail-v0.9")
        _git(repo, "tag", "another-tag")
        result = self.check(repo)
        self.assertEqual(result.status, FAIL)
        self.assertIn(DAIL_TAG, result.detail)
        self.assertIn("dail-v0.9", result.detail)
        self.assertIn("another-tag", result.detail)

    def test_tag_with_a_shared_prefix_is_not_accepted(self) -> None:
        repo = make_repo(self.tmp / "dail", DAIL_TAG + "-rc1")
        result = self.check(repo)
        self.assertEqual(result.status, FAIL)
        self.assertIn(DAIL_TAG + "-rc1", result.detail)

    def test_tag_on_an_older_commit_fails(self) -> None:
        repo = make_repo(self.tmp / "dail", DAIL_TAG)
        (repo / "NEXT").write_text("later\n", encoding="utf-8")
        _git(repo, "add", "NEXT")
        _git(repo, "commit", "-q", "-m", "later")
        result = self.check(repo)
        self.assertEqual(result.status, FAIL)
        self.assertIn("tags at HEAD: none", result.detail)

    def test_untagged_head_fails(self) -> None:
        repo = make_repo(self.tmp / "dail", None)
        result = self.check(repo)
        self.assertEqual(result.status, FAIL)
        self.assertIn("tags at HEAD: none", result.detail)

    def test_dirty_tree_with_an_untracked_file_fails(self) -> None:
        repo = make_repo(self.tmp / "dail", DAIL_TAG)
        (repo / "untracked.txt").write_text("x\n", encoding="utf-8")
        result = self.check(repo)
        self.assertEqual(result.status, FAIL)
        self.assertIn("not clean", result.detail)

    def test_dirty_tree_with_a_modified_file_fails(self) -> None:
        repo = make_repo(self.tmp / "dail", DAIL_TAG)
        (repo / "README").write_text("changed\n", encoding="utf-8")
        result = self.check(repo)
        self.assertEqual(result.status, FAIL)
        self.assertIn("not clean", result.detail)

    def test_unset_variable_fails(self) -> None:
        result = self.check(None)
        self.assertEqual(result.status, FAIL)
        self.assertIn("not set", result.detail)

    def test_empty_variable_fails(self) -> None:
        result = self.check("")
        self.assertEqual(result.status, FAIL)
        self.assertIn("not set", result.detail)

    def test_path_that_is_not_a_git_repository_fails(self) -> None:
        plain = self.tmp / "plain"
        plain.mkdir()
        result = self.check(plain)
        self.assertEqual(result.status, FAIL)
        self.assertIn("not a git repository", result.detail)

    def test_missing_path_fails(self) -> None:
        result = self.check(self.tmp / "does-not-exist")
        self.assertEqual(result.status, FAIL)
        self.assertIn("not a directory", result.detail)

    def test_subdirectory_of_a_repository_fails(self) -> None:
        repo = make_repo(self.tmp / "dail", DAIL_TAG)
        sub = repo / "sub"
        sub.mkdir()
        result = self.check(sub)
        self.assertEqual(result.status, FAIL)
        self.assertIn("not the top of a git repository", result.detail)


class DataDirTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.dail = (self.tmp / "dail").resolve()
        self.terrapreserve = (self.tmp / "terrapreserve").resolve()
        self.repo = (self.tmp / "dail-website").resolve()
        for root in (self.dail, self.terrapreserve, self.repo):
            root.mkdir()

    def check(self, data: Path | None) -> CheckResult:
        env = {
            "DAIL_ROOT": str(self.dail),
            "TERRAPRESERVE_ROOT": str(self.terrapreserve),
        }
        if data is not None:
            env["DAIL_LIVE_DATA"] = str(data)
        return check_data_dir(env, repo_root=self.repo)

    def test_inside_each_of_the_three_roots_fails(self) -> None:
        for root in (self.dail, self.terrapreserve, self.repo):
            with self.subTest(root=root.name):
                data = root / "data"
                result = self.check(data)
                self.assertEqual(result.status, FAIL, result.detail)
                self.assertIn("lies inside", result.detail)
                self.assertFalse(data.exists(), "a forbidden data dir was created")

    def test_equal_to_a_root_fails(self) -> None:
        for root in (self.dail, self.terrapreserve, self.repo):
            with self.subTest(root=root.name):
                self.assertEqual(self.check(root).status, FAIL)

    def test_inside_a_root_after_resolve_fails(self) -> None:
        sneaky = self.tmp / "outside" / ".." / "dail" / "data"
        result = self.check(sneaky)
        self.assertEqual(result.status, FAIL, result.detail)

    def test_sibling_with_a_shared_name_prefix_passes(self) -> None:
        result = self.check(self.tmp / "dail-live-data")
        self.assertEqual(result.status, PASS, result.detail)

    def test_outside_the_roots_passes_and_is_created(self) -> None:
        data = self.tmp / "outside" / "data"
        result = self.check(data)
        self.assertEqual(result.status, PASS, result.detail)
        self.assertTrue(data.is_dir())
        again = self.check(data)
        self.assertEqual(again.status, PASS, again.detail)

    def test_inside_this_repository_by_default_fails(self) -> None:
        data = REPO_ROOT / "dail-live-data-test-never-created"
        result = check_data_dir({"DAIL_LIVE_DATA": str(data)})
        self.assertEqual(result.status, FAIL, result.detail)
        self.assertFalse(data.exists())

    def test_unset_fails(self) -> None:
        result = self.check(None)
        self.assertEqual(result.status, FAIL)
        self.assertIn("not set", result.detail)

    def test_existing_file_fails(self) -> None:
        path = self.tmp / "a-file"
        path.write_text("x", encoding="utf-8")
        self.assertEqual(self.check(path).status, FAIL)


class VersionParsingTests(unittest.TestCase):
    def test_python_version_parsing(self) -> None:
        self.assertEqual(parse_python_version("3.12.10"), (3, 12, 10))
        self.assertEqual(parse_python_version("Python 3.12.0"), (3, 12, 0))
        self.assertIsNone(parse_python_version("not a version"))

    def test_python_check(self) -> None:
        self.assertEqual(check_python("3.12.10").status, PASS)
        self.assertEqual(check_python("3.12.0").status, PASS)
        self.assertEqual(check_python("3.11.9").status, FAIL)
        self.assertEqual(check_python("3.13.0").status, FAIL)
        self.assertEqual(check_python("3.1.20").status, FAIL)
        self.assertEqual(check_python("garbage").status, FAIL)

    def test_terraform_version_parsing(self) -> None:
        self.assertEqual(parse_terraform_version("Terraform v1.15.8\n"), "v1.15.8")
        self.assertEqual(
            parse_terraform_version("Terraform v1.15.8\non windows_amd64\n"), "v1.15.8"
        )
        self.assertEqual(parse_terraform_version("Terraform v1.14.0"), "v1.14.0")
        self.assertIsNone(parse_terraform_version("on windows_amd64\nTerraform v1.15.8"))
        self.assertIsNone(parse_terraform_version(""))

    def _terraform(self, stdout: str, returncode: int = 0) -> CheckResult:
        def runner(executable: str) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess([executable, "version"], returncode, stdout, "")

        return check_terraform(which=lambda _: "/fake/terraform", runner=runner)

    def test_terraform_check(self) -> None:
        self.assertEqual(self._terraform("Terraform v1.15.8\non linux_amd64\n").status, PASS)
        self.assertEqual(self._terraform("Terraform v1.15.9\n").status, FAIL)
        self.assertEqual(self._terraform("Terraform v1.15.80\n").status, FAIL)
        self.assertEqual(self._terraform("Terraform v1.15.8-rc1\n").status, FAIL)
        self.assertEqual(self._terraform("Terraform v1.15.8\n", returncode=1).status, FAIL)
        self.assertEqual(self._terraform("something else\n").status, FAIL)

    def test_terraform_missing_fails(self) -> None:
        result = check_terraform(which=lambda _: None)
        self.assertEqual(result.status, FAIL)
        self.assertIn("not on PATH", result.detail)


class GeminiKeyTests(unittest.TestCase):
    def run_cli(self, key: str | None) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.pop("GEMINI_API_KEY", None)
        if key is not None:
            env["GEMINI_API_KEY"] = key
        return subprocess.run(
            [sys.executable, "-m", "dail_demo", "check"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_key_never_appears_in_the_check_output(self) -> None:
        completed = self.run_cli(FAKE_KEY)
        self.assertIn("PASS gemini_key:", completed.stdout)
        for stream_name, stream in (("stdout", completed.stdout), ("stderr", completed.stderr)):
            with self.subTest(stream=stream_name):
                self.assertNotIn(FAKE_KEY, stream)
                self.assertNotIn(FAKE_KEY[:6], stream)

    def test_unset_key_warns_and_keeps_the_exit_code(self) -> None:
        with_key = self.run_cli(FAKE_KEY)
        without_key = self.run_cli(None)
        self.assertIn(
            f"WARN gemini_key: {environment.GEMINI_UNSET_MESSAGE}", without_key.stdout
        )
        self.assertNotIn("FAIL gemini_key", without_key.stdout)
        self.assertEqual(with_key.returncode, without_key.returncode)

    def test_unset_or_empty_key_is_warn(self) -> None:
        self.assertEqual(check_gemini_key({}).status, WARN)
        self.assertEqual(check_gemini_key({"GEMINI_API_KEY": ""}).status, WARN)
        self.assertEqual(check_gemini_key({"GEMINI_API_KEY": FAKE_KEY}).status, PASS)

    def test_warn_alone_gives_exit_code_zero(self) -> None:
        results = [
            CheckResult(PASS, "python", "ok"),
            CheckResult(WARN, "gemini_key", environment.GEMINI_UNSET_MESSAGE),
        ]
        self.assertEqual(exit_code(results), 0)
        self.assertEqual(exit_code(results + [CheckResult(FAIL, "x", "y")]), 1)


class OutputFormatTests(unittest.TestCase):
    def test_one_line_per_check_in_order(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "dail_demo", "check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        names = [
            line.split(" ", 2)[1].rstrip(":") for line in completed.stdout.splitlines()
        ]
        self.assertEqual(
            names,
            [
                "python",
                "dail_root",
                "terrapreserve_root",
                "data_dir",
                "terraform",
                "terraform_mirror",
                "gemini_key",
            ],
        )
        for line in completed.stdout.splitlines():
            self.assertRegex(line, r"^(PASS|FAIL|WARN) [a-z_]+: ")
        expected = 1 if "FAIL " in completed.stdout else 0
        self.assertEqual(completed.returncode, expected)


if __name__ == "__main__":
    unittest.main()

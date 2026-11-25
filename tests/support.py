"""Shared test helpers (B work package §2.3, §4).

* A test that needs real DAIL or TerraPreserve is skipped locally, with the reason, when its
  variable is unset; on CI (``CI`` set) CI provides both, so a missing one is a failure.
* A test that needs the Terraform provider mirror is skipped on CI with the reason
  "no provider mirror on CI", and locally when ``DAIL_TERRAFORM_MIRROR`` or Terraform is missing.
* ``FAKE_KEY`` is the only key any test uses; ``assert_no_key`` scans text and directories for it.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FAKE_KEY = "TEST-KEY-123456"  # gitleaks:allow  (a fake value; see D-11)
ON_CI = bool(os.environ.get("CI"))
NO_MIRROR_ON_CI = "no provider mirror on CI"


def _required(name: str, what: str) -> str:
    value = os.environ.get(name, "")
    if value:
        return value
    if ON_CI:
        raise AssertionError(f"{name} is not set on CI, which is meant to provide {what}")
    raise unittest.SkipTest(f"{name} is not set: these tests need {what}")


def dail_root() -> Path:
    """``DAIL_ROOT``, made importable through the L0 check (``settings.import_dail``)."""
    _required("DAIL_ROOT", "a DAIL checkout at dail-v1.0")
    from dail_demo.settings import SetupError, import_dail

    try:
        return import_dail(os.environ)
    except SetupError as error:
        raise AssertionError(str(error)) from None


def terrapreserve_root() -> Path:
    _required("TERRAPRESERVE_ROOT", "a TerraPreserve checkout at terrapreserve-v1.0-public-r3")
    from dail_demo.settings import SetupError, terrapreserve_root as checked

    try:
        return checked(os.environ)
    except SetupError as error:
        raise AssertionError(str(error)) from None


def mirror_environment() -> dict[str, str]:
    """The environment for the real ``terraform validate`` gate, or a skip."""
    if ON_CI:
        raise unittest.SkipTest(NO_MIRROR_ON_CI)
    if not os.environ.get("DAIL_TERRAFORM_MIRROR"):
        raise unittest.SkipTest("DAIL_TERRAFORM_MIRROR is not set: these tests need the provider mirror")
    if shutil.which("terraform") is None:
        raise unittest.SkipTest("terraform is not on PATH")
    return dict(os.environ)


class DataDirCase(unittest.TestCase):
    """A fresh ``DAIL_LIVE_DATA`` (outside the repository) per test, scanned for the key after."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="dail-live-test-", ignore_cleanup_errors=True)
        self.data = Path(self._tmp.name).resolve() / "data"
        self.environ = dict(os.environ)
        self.environ["DAIL_LIVE_DATA"] = str(self.data)
        self.environ["GEMINI_API_KEY"] = FAKE_KEY

    def tearDown(self) -> None:
        try:
            if self.data.exists():
                assert_no_key_in_dir(self, self.data)
        finally:
            self._tmp.cleanup()


def assert_no_key(case: unittest.TestCase, text: str, where: str = "text") -> None:
    case.assertNotIn(FAKE_KEY, text, f"the fake key appears in {where}")
    case.assertNotIn(FAKE_KEY[:6], text, f"the fake key's first 6 characters appear in {where}")


def assert_no_key_in_dir(case: unittest.TestCase, root: Path) -> int:
    """Scan every file under ``root`` (traces, logs, stores) for the fake key. Returns the count."""
    count = 0
    for path in root.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            case.assertNotIn(FAKE_KEY.encode(), data, f"the fake key appears in {path}")
            case.assertNotIn(FAKE_KEY[:6].encode(), data, f"the fake key's prefix appears in {path}")
            count += 1
    return count

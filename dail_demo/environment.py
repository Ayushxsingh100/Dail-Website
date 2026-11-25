"""Startup checks for DAIL Live (PLAN §3.1, §3.5; L0 work package §3).

Each check returns a ``CheckResult`` with status PASS, FAIL or WARN. The
checks only read the environment and run ``git`` and ``terraform version``;
the one side effect is creating ``DAIL_LIVE_DATA`` when it is missing and
its location is allowed.

The value of ``GEMINI_API_KEY`` is never printed, logged or stored, not even
in part. The checks only test whether it is set.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

# The pinned releases. Change them only through docs/DECISIONS.md.
DAIL_TAG = "dail-v1.0"
TERRAPRESERVE_TAG = "terrapreserve-v1.0-public-r3"
TERRAFORM_VERSION = "v1.15.8"
PYTHON_VERSION = (3, 12)

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

GEMINI_UNSET_MESSAGE = "AI mode unavailable; typed-patch mode still works"

# This repository's root (the directory that holds the dail_demo package).
REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class CheckResult:
    status: str
    name: str
    detail: str


def format_result(result: CheckResult) -> str:
    return f"{result.status} {result.name}: {result.detail}"


def exit_code(results: list[CheckResult]) -> int:
    """1 if any check is FAIL, otherwise 0. WARN never changes the code."""
    return 1 if any(r.status == FAIL for r in results) else 0


# --------------------------------------------------------------------- git


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _first_line(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[0].strip() if lines else ""


def check_pinned_checkout(
    name: str, variable: str, tag: str, environ: Mapping[str, str]
) -> CheckResult:
    """The checkout named by ``variable`` is a clean git checkout at ``tag``."""
    value = environ.get(variable, "")
    if not value:
        return CheckResult(FAIL, name, f"{variable} is not set")
    root = Path(value)
    if not root.is_dir():
        return CheckResult(FAIL, name, f"{variable}={value} is not a directory")

    try:
        top = _git(root, "rev-parse", "--show-toplevel")
    except FileNotFoundError:
        return CheckResult(FAIL, name, "git is not on PATH")
    if top.returncode != 0:
        return CheckResult(FAIL, name, f"{variable}={value} is not a git repository")
    if Path(top.stdout.strip()).resolve() != root.resolve():
        return CheckResult(
            FAIL,
            name,
            f"{variable}={value} is not the top of a git repository "
            f"(the repository root is {top.stdout.strip()})",
        )

    problems: list[str] = []

    tags = _git(root, "tag", "--points-at", "HEAD")
    if tags.returncode != 0:
        problems.append(f"cannot read the tags at HEAD ({_first_line(tags.stderr)})")
    else:
        found = sorted(t for t in tags.stdout.split() if t)
        if tag not in found:
            listed = ", ".join(found) if found else "none"
            problems.append(f"HEAD is not at tag {tag} (tags at HEAD: {listed})")

    status = _git(root, "status", "--porcelain")
    if status.returncode != 0:
        problems.append(f"cannot read the working tree status ({_first_line(status.stderr)})")
    else:
        changed = [line for line in status.stdout.splitlines() if line.strip()]
        if changed:
            problems.append(
                f"working tree is not clean ({len(changed)} changed or untracked "
                f"path(s), e.g. {changed[0].strip()})"
            )

    if problems:
        return CheckResult(FAIL, name, f"{variable}={value}: " + "; ".join(problems))
    return CheckResult(PASS, name, f"{variable}={value} is clean at tag {tag}")


# ------------------------------------------------------------- data dir


def _is_within(path: Path, root: Path) -> bool:
    """True if ``path`` equals ``root`` or lies inside it (both resolved)."""
    return path == root or root in path.parents


def check_data_dir(
    environ: Mapping[str, str], repo_root: Path = REPO_ROOT
) -> CheckResult:
    """``DAIL_LIVE_DATA`` is set, outside the three repositories, and exists.

    The location is checked before anything is created, so a forbidden path
    never leaves a new directory inside a repository.
    """
    name = "data_dir"
    value = environ.get("DAIL_LIVE_DATA", "")
    if not value:
        return CheckResult(FAIL, name, "DAIL_LIVE_DATA is not set")
    data = Path(value).resolve()

    forbidden = [
        ("DAIL_ROOT", environ.get("DAIL_ROOT", "")),
        ("TERRAPRESERVE_ROOT", environ.get("TERRAPRESERVE_ROOT", "")),
        ("this repository", str(repo_root)),
    ]
    for label, root_value in forbidden:
        if root_value and _is_within(data, Path(root_value).resolve()):
            return CheckResult(
                FAIL, name, f"DAIL_LIVE_DATA={value} lies inside {label} ({root_value})"
            )

    if data.exists() and not data.is_dir():
        return CheckResult(FAIL, name, f"DAIL_LIVE_DATA={value} exists and is not a directory")
    created = not data.exists()
    try:
        data.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return CheckResult(FAIL, name, f"cannot create DAIL_LIVE_DATA={value} ({error.strerror})")
    return CheckResult(
        PASS, name, f"DAIL_LIVE_DATA={value} " + ("created" if created else "exists")
    )


# -------------------------------------------------------------- python


def parse_python_version(text: str) -> tuple[int, int, int] | None:
    """Parse '3.12.10' (or 'Python 3.12.10') into (3, 12, 10)."""
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def check_python(version_text: str | None = None) -> CheckResult:
    name = "python"
    if version_text is None:
        version_text = ".".join(str(part) for part in sys.version_info[:3])
    version = parse_python_version(version_text)
    if version is None:
        return CheckResult(FAIL, name, f"cannot parse the Python version {version_text!r}")
    shown = ".".join(str(part) for part in version)
    if version[:2] != PYTHON_VERSION:
        wanted = ".".join(str(part) for part in PYTHON_VERSION)
        return CheckResult(FAIL, name, f"Python {shown}; {wanted}.x is required")
    return CheckResult(PASS, name, f"Python {shown}")


# ----------------------------------------------------------- terraform


def parse_terraform_version(output: str) -> str | None:
    """Return the version on the first line of `terraform version`, e.g. 'v1.15.8'."""
    match = re.match(r"Terraform (v\d+\.\d+\.\d+\S*)", _first_line(output))
    return match.group(1) if match else None


def _run_terraform_version(executable: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [executable, "version"],
        capture_output=True,
        text=True,
        check=False,
    )


def check_terraform(
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[[str], subprocess.CompletedProcess[str]] = _run_terraform_version,
) -> CheckResult:
    """`terraform` is on PATH and `terraform version` reports the pinned version.

    No other Terraform command is run.
    """
    name = "terraform"
    executable = which("terraform")
    if executable is None:
        return CheckResult(FAIL, name, "terraform is not on PATH")
    try:
        completed = runner(executable)
    except OSError as error:
        return CheckResult(FAIL, name, f"cannot run terraform version ({error.strerror})")
    first = _first_line(completed.stdout)
    version = parse_terraform_version(completed.stdout)
    if completed.returncode != 0 or version is None:
        return CheckResult(FAIL, name, f"unexpected output from terraform version: {first!r}")
    if version != TERRAFORM_VERSION:
        return CheckResult(FAIL, name, f"terraform {version}; {TERRAFORM_VERSION} is required")
    return CheckResult(PASS, name, f"terraform {version} at {executable}")


def check_terraform_mirror(environ: Mapping[str, str]) -> CheckResult:
    """``DAIL_TERRAFORM_MIRROR`` (DAIL's own variable) is a directory."""
    name = "terraform_mirror"
    value = environ.get("DAIL_TERRAFORM_MIRROR", "")
    if not value:
        return CheckResult(FAIL, name, "DAIL_TERRAFORM_MIRROR is not set")
    if not Path(value).is_dir():
        return CheckResult(FAIL, name, f"DAIL_TERRAFORM_MIRROR={value} is not a directory")
    return CheckResult(PASS, name, f"DAIL_TERRAFORM_MIRROR={value} is a directory")


# --------------------------------------------------------------- gemini


def check_gemini_key(environ: Mapping[str, str]) -> CheckResult:
    """WARN if ``GEMINI_API_KEY`` is unset or empty, PASS if set.

    The detail never contains the value or anything derived from it.
    """
    name = "gemini_key"
    if not environ.get("GEMINI_API_KEY", "").strip():
        return CheckResult(WARN, name, GEMINI_UNSET_MESSAGE)
    return CheckResult(PASS, name, "GEMINI_API_KEY is set")


# ----------------------------------------------------------------- all


def run_checks(environ: Mapping[str, str] | None = None) -> list[CheckResult]:
    """Run the seven startup checks in the order of the L0 work package."""
    env = os.environ if environ is None else environ
    return [
        check_python(),
        check_pinned_checkout("dail_root", "DAIL_ROOT", DAIL_TAG, env),
        check_pinned_checkout(
            "terrapreserve_root", "TERRAPRESERVE_ROOT", TERRAPRESERVE_TAG, env
        ),
        check_data_dir(env),
        check_terraform(),
        check_terraform_mirror(env),
        check_gemini_key(env),
    ]

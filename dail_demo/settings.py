"""Local-only setup: importing DAIL, its configuration, the data directory, the Terraform gate and
the Gemini settings (PLAN §3.1, §3.4, §3.5; B work package §2.2).

This module may use the environment, ``git`` and Terraform; ``evaluate_core`` may not.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from dail_demo import DEMO_LABEL, __version__
from dail_demo.environment import (
    DAIL_TAG,
    FAIL,
    REPO_ROOT,
    TERRAPRESERVE_TAG,
    check_data_dir,
    check_pinned_checkout,
)

CONFIG_DIR: Final = REPO_ROOT / "config"
PROMOTION_FILE: Final = CONFIG_DIR / "promotion.toml"
LLM_FILE: Final = CONFIG_DIR / "llm.toml"
GEMINI_FILE: Final = CONFIG_DIR / "gemini.toml"
DAIL_PACKAGES: Final = ("core", "llm", "evidence", "experiments")


class SetupError(Exception):
    """The environment cannot run the command (one line, safe to print)."""


def import_dail(environ: Mapping[str, str]) -> Path:
    """Make DAIL importable, only after the L0 ``dail_root`` check passes.

    ``DAIL_ROOT`` is appended to ``sys.path`` (so this repository's own packages, such as
    ``tests``, keep precedence; DAIL's ``tests`` package is never imported).
    """
    result = check_pinned_checkout("dail_root", "DAIL_ROOT", DAIL_TAG, environ)
    if result.status == FAIL:
        raise SetupError(f"DAIL is not usable: {result.detail}")
    root = str(Path(environ["DAIL_ROOT"]).resolve())
    if root not in sys.path:
        sys.path.append(root)
    return Path(root)


def terrapreserve_root(environ: Mapping[str, str]) -> Path:
    result = check_pinned_checkout(
        "terrapreserve_root", "TERRAPRESERVE_ROOT", TERRAPRESERVE_TAG, environ
    )
    if result.status == FAIL:
        raise SetupError(f"TerraPreserve is not usable: {result.detail}")
    return Path(environ["TERRAPRESERVE_ROOT"]).resolve()


def data_dir(environ: Mapping[str, str]) -> Path:
    result = check_data_dir(environ)
    if result.status == FAIL:
        raise SetupError(f"no data directory: {result.detail}")
    return Path(environ["DAIL_LIVE_DATA"]).resolve()


def git_commit(root: Path) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() if done.returncode == 0 else "unknown"


def committed(root: Path, name: str) -> bytes:
    """The bytes of ``name`` as committed at HEAD (no line-ending conversion, unlike the checkout)."""
    done = subprocess.run(
        ["git", "-C", str(root), "cat-file", "blob", f"HEAD:{name}"], capture_output=True, check=False
    )
    if done.returncode != 0:
        raise SetupError(f"git cannot read {name} at HEAD of {root}")
    return done.stdout


def committed_copy(root: Path, source: Path, target: Path) -> Path:
    """DAIL's ``config_only_copy`` of ``source`` (inside ``root``), with the committed bytes (D-28)."""
    from experiments.generation.parent import config_only_copy

    config_only_copy(Path(source), target)
    for path in target.iterdir():
        path.write_bytes(committed(root, (Path(source) / path.name).relative_to(root).as_posix()))
    return target


def versions(dail_root: Path, terrapreserve: Path | None = None) -> dict[str, Any]:
    found: dict[str, Any] = {
        "dail_tag": DAIL_TAG,
        "dail_commit": git_commit(dail_root),
        "demo_version": __version__,
    }
    if terrapreserve is not None:
        found["terrapreserve_tag"] = TERRAPRESERVE_TAG
        found["terrapreserve_commit"] = git_commit(terrapreserve)
    return found


def dail_config(dail_root: Path) -> Any:
    """DAIL's configuration with DAIL Live's two reviewed files in place (D-14), built in a
    temporary folder by ``evaluate_core.build_config`` (the same function the browser uses)."""
    from dail_demo.evaluate_core import CoreError, build_config

    with tempfile.TemporaryDirectory(prefix="dail-live-config-") as tmp:
        try:
            config = build_config(dail_root / "config", PROMOTION_FILE, LLM_FILE, Path(tmp))
        except CoreError as error:
            raise SetupError(str(error)) from None
    if config.get("llm.generation_enabled") is not True:
        raise SetupError("config/llm.toml must enable llm.generation_enabled")
    return config


def terraform_runner(environ: Mapping[str, str], work_root: Path) -> Any:
    """DAIL's pinned ``terraform validate`` gate (``TerraformValidateRunner``), with
    ``DAIL_TERRAFORM_MIRROR`` and Terraform on PATH."""
    from experiments.terraform_validate import RunnerError, TerraformValidateRunner

    terraform = shutil.which("terraform")
    if terraform is None:
        raise SetupError("terraform validate gate unavailable: terraform is not on PATH")
    mirror = environ.get("DAIL_TERRAFORM_MIRROR", "")
    if not mirror:
        raise SetupError("terraform validate gate unavailable: DAIL_TERRAFORM_MIRROR is not set")
    try:
        return TerraformValidateRunner(terraform=terraform, mirror=Path(mirror), work_root=work_root)
    except RunnerError as error:
        raise SetupError(f"terraform validate gate unavailable: {error}") from None


@dataclass(frozen=True)
class GeminiSettings:
    model: str
    endpoint: str
    api_version: str
    temperature: float
    top_p: float
    seed: int
    max_output_tokens: int
    timeout_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def gemini_settings(path: Path = GEMINI_FILE) -> GeminiSettings:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return GeminiSettings(
        model=str(data["model"]),
        endpoint=str(data["endpoint"]),
        api_version=str(data["api_version"]),
        temperature=float(data["temperature"]),
        top_p=float(data["top_p"]),
        seed=int(data["seed"]),
        max_output_tokens=int(data["max_output_tokens"]),
        timeout_seconds=float(data["timeout_seconds"]),
    )


LABEL: Final = DEMO_LABEL

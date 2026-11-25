"""``python -m dail_demo bundle``: build ``site/vendor/`` for the website (PLAN §3.8; C work package
§1; D-20).

Local only. It writes, from scratch each time:

* ``dail/``: DAIL v1.0's source files the browser needs (every ``*.py`` file of ``core/``,
  ``llm/``, ``evidence/`` and ``experiments/``, DAIL's ``config/`` and ``LICENSE``), copied
  byte-for-byte as committed at ``dail-v1.0`` (git blobs, not the working files: a Windows checkout
  may hold CRLF copies, D-28; only files git tracks at the tag; never ``tests/``), with ``VERSION.json`` (tag and commit) and ``MANIFEST.sha256``;
* ``dail_live/``: ``dail_demo/__init__.py``, ``evaluate_core.py`` and ``browser.py``, and the two
  reviewed configuration files (``config/promotion.toml``, ``config/llm.toml``);
* ``scenarios/``: one pack per scenario (``canonical`` and every curated id of D-16): S0's
  configuration files, the patches (canonical ``safe`` and ``regression``; a TerraPreserve
  scenario's own steps), and ``scenario.json`` (DAIL's scenario record, bindings, target and the
  content hashes); with TerraPreserve's licences and attribution;
* ``pyodide/0.27.7/``: the pinned Pyodide runtime files and its ``sqlite3`` package, each checked
  against ``PYODIDE_FILES`` (SHA-256) before it is copied; a mismatch stops the bundle;
* ``files.json``: every file the page loads into Pyodide, with its SHA-256 and size (the page checks
  each one before use).

Every manifest is in ``sha256sum`` format (``<sha256>  <path>``), so ``sha256sum -c`` checks it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from dail_demo import scenarios as sc
from dail_demo.environment import DAIL_TAG, REPO_ROOT, TERRAPRESERVE_TAG
from dail_demo.settings import CONFIG_DIR, SetupError, git_commit, import_dail, terrapreserve_root

SITE: Final = REPO_ROOT / "site"
VENDOR: Final = SITE / "vendor"
PYODIDE_VERSION: Final = "0.27.7"
# SHA-256 of each file of the official Pyodide 0.27.7 release we serve (D-20): the npm package
# pyodide@0.27.7 (registry integrity sha512-RUSVJlhQ…qpSRA==), the sqlite3 wheel of the release's
# full/ files (its pyodide-lock.json hash) and the release's MPL-2.0 LICENSE.
PYODIDE_FILES: Final = {
    "LICENSE": "1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5",
    "package.json": "bf221f60c881626236d3501375a97753672a7fa6fed70e469e083f157c8a30d4",
    "pyodide-lock.json": "9c45b916001a750f4102fc287494f3eab215909c7535c626a20db80fd6333e2c",
    "pyodide.asm.js": "6b4c90de5b7172873f04f21884d0e9d2274e305fe32116558fe3e4fbe3618d51",
    "pyodide.asm.wasm": "a50dd1843f805a0b7c45b61037ee0d7b26dfe85efe0e18ef95a34ad24e401f5f",
    "pyodide.js": "b4cb23a53aba19c221659b9fb40a2f18281d685691dc06647fb0afd0681baf98",
    "pyodide.mjs": "04c052c815abb0bf2981fa38c2dfa58e3120ee5288c956df2b2a15e301782c5f",
    "python_stdlib.zip": "16611534726e5d8ac2bd8f926410b2dcb8d6f49aa24913463533b457a2115c16",
    "sqlite3-1.0.0-cp312-cp312-pyodide_2024_0_wasm32.whl": (
        "43061928762b03482676a1e11dcef99a003148e59fe914b6a3e41180c382cfc3"
    ),
}
DAIL_PACKAGES: Final = ("core", "llm", "evidence", "experiments")
DEMO_MODULES: Final = ("__init__.py", "evaluate_core.py", "browser.py")
TP_LICENCES: Final = (
    ("LICENSES/CC-BY-4.0.txt", "CC-BY-4.0.txt"),
    ("pool/terragoat/aws/LICENSE.upstream", "TerraGoat-LICENSE.txt"),
    ("pool/terragoat/aws/NOTICE", "TerraGoat-NOTICE.txt"),
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_manifest(root: Path) -> Path:
    """``MANIFEST.sha256`` of every other file under ``root`` (sorted, POSIX paths)."""
    lines = [
        f"{sha256_file(p)}  {p.relative_to(root).as_posix()}"
        for p in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix())
        if p.is_file() and p.name != "MANIFEST.sha256"
    ]
    path = root / "MANIFEST.sha256"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def check_manifest(root: Path) -> list[str]:
    """Every problem with ``root``'s manifest (missing, changed or unlisted files)."""
    problems = []
    listed: dict[str, str] = {}
    for line in (root / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        listed[name] = digest
    present = {
        p.relative_to(root).as_posix(): p
        for p in root.rglob("*")
        if p.is_file() and p.name != "MANIFEST.sha256"
    }
    for name, digest in listed.items():
        if name not in present:
            problems.append(f"missing: {name}")
        elif sha256_file(present[name]) != digest:
            problems.append(f"changed: {name}")
    problems.extend(f"unlisted: {name}" for name in sorted(set(present) - set(listed)))
    return problems


def dail_files(dail_root: Path) -> list[str]:
    """The DAIL files the browser needs, as git tracks them at the tag (never ``tests/``)."""
    done = subprocess.run(
        ["git", "-C", str(dail_root), "ls-files", "--", *DAIL_PACKAGES, "config", "LICENSE"],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise SetupError(f"git ls-files failed in DAIL_ROOT: {done.stderr.strip()}")
    files = []
    for name in done.stdout.splitlines():
        top = name.split("/")[0]
        if top == "tests" or "/tests/" in f"/{name}":
            continue
        if top in DAIL_PACKAGES and not name.endswith(".py"):
            continue
        files.append(name)
    return sorted(files)


def committed(root: Path, name: str) -> bytes:
    """The bytes of ``name`` as committed at HEAD (no line-ending conversion, unlike the checkout)."""
    done = subprocess.run(
        ["git", "-C", str(root), "cat-file", "blob", f"HEAD:{name}"], capture_output=True, check=False
    )
    if done.returncode != 0:
        raise SetupError(f"git cannot read {name} at HEAD of {root}")
    return done.stdout


def _copy_dail(dail_root: Path, out: Path) -> int:
    names = dail_files(dail_root)
    for name in names:
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(committed(dail_root, name))
    (out / "VERSION.json").write_text(
        json.dumps({"dail_tag": DAIL_TAG, "dail_commit": git_commit(dail_root)}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_manifest(out)
    return len(names)


def _copy_demo(out: Path) -> None:
    package = out / "dail_demo"
    package.mkdir(parents=True)
    for name in DEMO_MODULES:
        shutil.copyfile(REPO_ROOT / "dail_demo" / name, package / name)
    (out / "config").mkdir()
    for name in ("promotion.toml", "llm.toml"):
        shutil.copyfile(CONFIG_DIR / name, out / "config" / name)
    write_manifest(out)


def _config_copy(source: Path, target: Path) -> Path:
    from experiments.generation.parent import config_only_copy

    return config_only_copy(Path(source), target)


def _committed_copy(root: Path, source: Path, target: Path) -> Path:
    """``_config_copy`` with each file's committed bytes."""
    _config_copy(source, target)
    for path in target.iterdir():
        path.write_bytes(committed(root, (Path(source) / path.name).relative_to(root).as_posix()))
    return target


def _pack_canonical(dail_root: Path, out: Path) -> dict[str, Any]:
    from dail_demo import evaluate_core as core
    from experiments.loader import step_content_hash

    source = sc.canonical(dail_root)
    pack = out / sc.CANONICAL
    s0 = _committed_copy(dail_root, source.s0_dir, pack / "s0")
    assert source.expected is not None
    scenario = core.canonical_scenario(source.expected, s0)
    patches = {}
    for name, directory in source.fixed.items():
        copied = _committed_copy(dail_root, directory, pack / "patches" / name)
        patches[name] = {"dir": f"patches/{name}", "content_hash": step_content_hash(copied), "step": 1}
    data = {
        "schema": "dail-live-scenario-pack/1",
        "kind": "canonical",
        "record": core.scenario_record(scenario),
        "s0": "s0",
        "hashes": {"0": step_content_hash(s0)},
        "patches": patches,
        "steps": [],
        "source": f"DAIL {DAIL_TAG} fixtures/canonical_regression (Apache-2.0)",
    }
    (pack / "scenario.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {
        "id": sc.CANONICAL,
        "family": "canonical",
        "title": "DAIL's canonical example: public SSH open, a database behind it",
        "why": "DAIL's own fixture: the safe repair is promoted, the repair that cuts the database off is rejected",
        "target": scenario.target_invariant_id,
        "patches": sorted(patches),
        "quick_fill": ["safe", "regression"],
        "source": "DAIL",
    }


def _pack_terrapreserve(tp_root: Path, scenario_id: str, why: str, family: str, out: Path) -> dict[str, Any]:
    from dail_demo import evaluate_core as core
    from experiments.loader import step_content_hash

    source = sc.terrapreserve(tp_root, scenario_id)
    scenario = source.scenario
    pack = out / scenario_id
    s0 = _config_copy(source.s0_dir, pack / "s0")
    if step_content_hash(s0) != scenario.steps[0].content_hash:
        raise SetupError(f"{scenario_id}: S0's configuration copy is not the manifest's step 0")
    patches, steps = {}, []
    for step in scenario.steps[1:]:
        name = f"step-{step.index}"
        copied = _config_copy(step.directory, pack / "patches" / name)
        if step_content_hash(copied) != step.content_hash:
            raise SetupError(f"{scenario_id} step {step.index}: the copy is not the manifest's step")
        patches[name] = {"dir": f"patches/{name}", "content_hash": step.content_hash, "step": step.index}
        steps.append({"index": step.index, "dir": f"patches/{name}", "content_hash": step.content_hash})
    patches["fixed"] = dict(patches["step-1"])
    data = {
        "schema": "dail-live-scenario-pack/1",
        "kind": "terrapreserve",
        "record": core.scenario_record(scenario),
        "s0": "s0",
        "hashes": {"0": scenario.steps[0].content_hash},
        "patches": patches,
        "steps": steps,
        "source": f"TerraPreserve {TERRAPRESERVE_TAG} scenarios/dev/{scenario_id} (CC-BY-4.0)",
    }
    (pack / "scenario.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {
        "id": scenario_id,
        "family": family,
        "title": f"TerraPreserve {scenario_id}",
        "why": why,
        "target": scenario.target_invariant_id,
        "patches": sorted(patches),
        "quick_fill": ["fixed"],
        "source": "TerraPreserve",
        "steps": len(steps),
    }


ATTRIBUTION: Final = """# Scenario attribution

The `canonical` pack is DAIL's own fixture `fixtures/canonical_regression` from DAIL {dail_tag}
(https://github.com/Ayushxsingh100/DAIL, Apache-2.0, see `../dail/LICENSE`).

Every other pack is a scenario of TerraPreserve {tp_tag}
(https://github.com/Ayushxsingh100/terrapreserve, doi:10.5281/zenodo.24509952) by Ayush Kumar Singh
and Krishika: its S0 configuration, its own steps and its labels, unchanged. TerraPreserve's
scenarios and labels are licensed under CC-BY-4.0 (`CC-BY-4.0.txt`). The controlled-tier scenarios
are derived from TerraGoat (Bridgecrew), whose Apache-2.0 licence and notice are kept
(`TerraGoat-LICENSE.txt`, `TerraGoat-NOTICE.txt`). The files are copied as they are; DAIL Live
changed nothing.
"""


def _copy_pyodide(source: Path, out: Path) -> int:
    """Check every pinned file in ``source`` and copy it into ``out`` (``source`` may be ``out``:
    then the files already in the site are checked in place)."""
    out.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, digest in PYODIDE_FILES.items():
        path = source / name
        if not path.is_file():
            raise SetupError(f"Pyodide {PYODIDE_VERSION}: {name} is missing in {source}")
        found = sha256_file(path)
        if found != digest:
            raise SetupError(f"Pyodide {PYODIDE_VERSION}: {name} has SHA-256 {found}, not the pinned {digest}")
        if path.resolve() != (out / name).resolve():
            shutil.copyfile(path, out / name)
        total += path.stat().st_size
    extra = sorted(p.name for p in out.iterdir() if p.name not in PYODIDE_FILES and p.name != "MANIFEST.sha256")
    for name in extra:
        (out / name).unlink()
    write_manifest(out)
    return total


def bundle(environ: Mapping[str, str], *, pyodide: Path | None = None, out: Path = VENDOR) -> dict[str, Any]:
    """Build ``out`` (see the module docstring). Returns a summary for the command line."""
    dail_root = import_dail(environ)
    tp_root = terrapreserve_root(environ)
    out = Path(out).resolve()
    pyodide_out = out / "pyodide" / PYODIDE_VERSION
    source = Path(pyodide) if pyodide is not None else pyodide_out
    with tempfile.TemporaryDirectory(prefix="dail-live-bundle-") as tmp:
        staging = Path(tmp)
        dail_count = _copy_dail(dail_root, staging / "dail")
        _copy_demo(staging / "dail_live")
        scenarios = staging / "scenarios"
        scenarios.mkdir()
        index = [_pack_canonical(dail_root, scenarios)]
        index += [_pack_terrapreserve(tp_root, sid, why, family, scenarios) for sid, family, why in sc.CURATED]
        for relative, name in TP_LICENCES:
            shutil.copyfile(tp_root / relative, scenarios / name)
        (scenarios / "ATTRIBUTION.md").write_text(
            ATTRIBUTION.format(dail_tag=DAIL_TAG, tp_tag=TERRAPRESERVE_TAG), encoding="utf-8", newline="\n"
        )
        (scenarios / "index.json").write_text(
            json.dumps({"schema": "dail-live-scenarios/1", "scenarios": index}, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        write_manifest(scenarios)
        pyodide_size = _copy_pyodide(source, pyodide_out)
        for part in ("dail", "dail_live", "scenarios"):
            shutil.rmtree(out / part, ignore_errors=True)
            shutil.copytree(staging / part, out / part)
    files = []
    for part in ("dail", "dail_live", "scenarios"):
        for path in sorted((out / part).rglob("*"), key=lambda p: p.relative_to(out).as_posix()):
            if path.is_file():
                files.append(
                    {"path": path.relative_to(out).as_posix(), "sha256": sha256_file(path), "size": path.stat().st_size}
                )
    listing = {
        "schema": "dail-live-files/1",
        "pyodide": {"version": PYODIDE_VERSION, "dir": f"pyodide/{PYODIDE_VERSION}", "size": pyodide_size},
        "files": files,
        "size": sum(f["size"] for f in files),
    }
    (out / "files.json").write_text(json.dumps(listing, indent=1) + "\n", encoding="utf-8", newline="\n")
    return {
        "dail_files": dail_count,
        "bundled_files": len(files),
        "bundled_bytes": listing["size"],
        "pyodide_bytes": pyodide_size,
        "scenarios": [entry["id"] for entry in index],
        "out": str(out),
    }

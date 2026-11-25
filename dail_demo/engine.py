"""The local engine: ``python -m dail_demo evaluate`` (PLAN §3.3, §3.6; B work package §2, §3.1,
§3.2).

Local only: it reads the environment, runs ``git`` and the Terraform gate, and copies the inputs
into a fresh run directory under ``DAIL_LIVE_DATA/runs/``. The evaluation itself is
``dail_demo.evaluate_core`` (DAIL and the standard library only), which works inside that run
directory. Traces are written to ``DAIL_LIVE_DATA/traces/``, never into a repository.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from dail_demo import DEMO_LABEL
from dail_demo import scenarios as sc
from dail_demo.environment import REPO_ROOT
from dail_demo.settings import (
    SetupError,
    dail_config,
    data_dir,
    import_dail,
    terraform_runner,
    terrapreserve_root,
    versions,
)

EXIT_DECIDED: Final = 0
EXIT_SETUP: Final = 1
EXIT_REFUSED: Final = 2  # refused before DAIL: no decision


@dataclass(frozen=True)
class Outcome:
    trace: dict[str, Any]
    path: Path
    exit_code: int


@dataclass(frozen=True)
class Run:
    dail_root: Path
    data: Path
    run_id: str
    root: Path


def new_run(environ: Mapping[str, str], kind: str) -> Run:
    dail_root = import_dail(environ)
    data = data_dir(environ)
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{kind}-{uuid.uuid4().hex[:8]}"
    root = data / "runs" / run_id
    root.mkdir(parents=True)
    return Run(dail_root, data, run_id, root)


def resolve(scenario_id: str, environ: Mapping[str, str], dail_root: Path) -> tuple[sc.Source, Path | None]:
    if scenario_id == sc.CANONICAL:
        return sc.canonical(dail_root), None
    tp_root = terrapreserve_root(environ)
    try:
        return sc.terrapreserve(tp_root, scenario_id), tp_root
    except sc.ScenarioError as error:
        raise SetupError(str(error)) from None


def _forbidden_roots(environ: Mapping[str, str]) -> list[Path]:
    found = [REPO_ROOT.resolve()]
    for name in ("DAIL_ROOT", "TERRAPRESERVE_ROOT"):
        if environ.get(name):
            found.append(Path(environ[name]).resolve())
    return found


def check_no_key(text: str, environ: Mapping[str, str]) -> None:
    """Refuse to write or print anything that contains the Gemini key (defence in depth)."""
    key = environ.get("GEMINI_API_KEY", "").strip()
    if key and key in text:
        raise SetupError("refused to write a record that contains GEMINI_API_KEY")


def write_trace(
    trace: Mapping[str, Any], run: Run, environ: Mapping[str, str], out: Path | None = None
) -> Path:
    text = json.dumps(trace, indent=2, ensure_ascii=False) + "\n"
    check_no_key(text, environ)
    if out is None:
        path = run.data / "traces" / f"{run.run_id}.json"
    else:
        path = Path(out).resolve()
        for root in _forbidden_roots(environ):
            if path == root or root in path.parents:
                raise SetupError(f"--out {out} lies inside {root}: traces never go into a repository")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _copy(source: Path, target: Path) -> Path:
    from experiments.generation.parent import config_only_copy

    if not Path(source).is_dir():
        raise SetupError(f"{source} is not a directory")
    return config_only_copy(Path(source), target)


def run_evaluate(
    scenario_id: str,
    patch: str,
    *,
    environ: Mapping[str, str],
    out: Path | None = None,
    terraform: Any = None,
    validate_fixed: bool = False,
) -> Outcome:
    """Evaluate one candidate under DAIL (C) and target-only (A) and write the trace.

    ``patch`` is ``safe`` or ``regression`` (canonical), ``fixed`` (a TerraPreserve scenario's step
    1) or a directory (a typed patch). ``terraform`` replaces the real validate gate (tests only).
    With ``validate_fixed`` (``record``), a fixed patch also passes the pinned ``terraform
    validate`` gate before DAIL, and the gate's result is recorded in its admission.
    """
    run = new_run(environ, "evaluate")
    from dail_demo import evaluate_core as core
    from experiments.loader import step_content_hash

    source, tp_root = resolve(scenario_id, environ, run.dail_root)
    inputs = run.root / "inputs"
    s0 = _copy(source.s0_dir, inputs / "s0")
    meta = versions(run.dail_root, tp_root)
    if patch in source.fixed:
        kind, origin = core.FIXED_PATCH, source.fixed[patch]
    elif patch in ("safe", "regression", "fixed"):
        raise SetupError(f"--patch {patch} does not exist for {scenario_id}; use one of {sorted(source.fixed)}")
    else:
        kind, origin = core.TYPED, Path(patch)
    candidate_dir = _copy(origin, inputs / "candidate")

    if source.scenario is None:
        assert source.expected is not None
        scenario = core.canonical_scenario(source.expected, s0, candidate_dir)
    else:
        scenario = source.scenario if kind == core.FIXED_PATCH else core.s0_only(source.scenario)

    label = (
        f"{scenario_id} {patch}" if kind == core.FIXED_PATCH else f"{scenario_id} typed patch from {origin}"
    )
    if kind == core.FIXED_PATCH:
        admission: dict[str, Any] = {
            "stage": "fixed_patch",
            "admitted": True,
            "content_hash": step_content_hash(Path(origin)),
        }
        if source.scenario is not None and tp_root is not None:
            admission["content_hash_matches_manifest"] = (
                admission["content_hash"] == source.scenario.steps[1].content_hash
            )
            admission["terraform_validate"] = sc.admission_evidence(tp_root)
            if not admission["content_hash_matches_manifest"]:
                raise SetupError(f"{scenario_id} step 1: the content hash is not the manifest's")
        else:
            admission["origin"] = f"DAIL fixture {sc.CANONICAL_DIR.as_posix()}/{sc.CANONICAL_PATCHES[patch]}"
        if validate_fixed:
            gate = terraform if terraform is not None else terraform_runner(environ, run.root / "terraform")
            check = gate(candidate_dir)
            admission["terraform_validate_run"] = check.to_dict()
            if not check.ok:
                raise SetupError(f"{scenario_id} {patch}: terraform validate refused it: {check.error}")
    else:
        gate = terraform if terraform is not None else terraform_runner(environ, run.root / "terraform")
        check = gate(candidate_dir)
        if not check.ok:
            admission = {
                "stage": "terraform_validate",
                "admitted": False,
                "errors": [check.error],
                "terraform_validate": check.to_dict(),
            }
        else:
            admission = core.admit_typed(
                root=run.root,
                scenario=scenario,
                s0_dir=s0,
                edited_dir=candidate_dir,
                run_id=run.run_id,
                terraform_validate=gate,
            )
            admission["terraform_validate_typed_dir"] = check.to_dict()
        if not admission["admitted"]:
            candidate = core.Candidate(source=kind, label=label, directory=candidate_dir, admission=admission)
            trace = {
                **core.base_trace(
                    label=DEMO_LABEL, versions=meta, scenario=scenario, candidate=candidate, run_id=run.run_id
                ),
                "diff": core.unified_diff(s0, candidate_dir),
                "admission": admission,
                "conditions": None,
                "refused_before_dail": True,
            }
            return Outcome(trace, write_trace(trace, run, environ, out), EXIT_REFUSED)

    candidate = core.Candidate(source=kind, label=label, directory=candidate_dir, admission=admission)
    trace = core.evaluate(
        root=run.root,
        scenario=scenario,
        s0_dir=s0,
        candidate=candidate,
        config=dail_config(run.dail_root),
        run_id=run.run_id,
        label=DEMO_LABEL,
        versions=meta,
        extra={"refused_before_dail": False},
    )
    return Outcome(trace, write_trace(trace, run, environ, out), EXIT_DECIDED)


def summary_lines(trace: Mapping[str, Any], path: Path) -> list[str]:
    """A short human summary; every value is read from the trace."""
    lines = [
        f"DAIL Live ({trace['label']})",
        f"scenario {trace['scenario']['scenario_id']}: {trace['candidate']['label']} "
        f"[{trace['candidate_source']}]",
    ]
    admission = trace.get("admission") or {}
    if trace.get("refused_before_dail"):
        reasons = "; ".join(admission.get("errors") or []) or "refused"
        lines.append(f"refused before DAIL at {admission.get('stage')}: {reasons}")
    for key, section in (trace.get("conditions") or {}).items():
        decision = section.get("decision")
        if decision is None:
            why = section.get("rebuild_failure") or (section.get("baseline") or {}).get("reasons")
            lines.append(f"{section['name']} ({key}): no decision ({why})")
            continue
        blocking = ", ".join(sorted({b["target"] for b in decision.get("blocking") or []}))
        lines.append(
            f"{section['name']} ({key}): {decision['type']} {decision['reason']}"
            + (f", blocking {blocking}" if blocking else "")
            + f"; checks {section['check_count']}"
        )
    lines.append(f"trace: {path}")
    return lines

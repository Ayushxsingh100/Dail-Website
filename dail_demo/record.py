"""``python -m dail_demo record``: record the replays of the website (PLAN §3.8, §5 L5; C work
package §3).

Local only. With the local engine and the pinned ``terraform validate`` gate on, it records:

* the canonical ``safe`` and ``regression`` patches and every curated scenario's fixed patch;
* ``tp-v1-F8-0196``'s steps in one session (DAIL's lineage, as DAIL's trial plays a scenario: each
  step against the state the previous one promoted, stopping at the first decision that is not
  PROMOTE, C-200), so a replay shows where the break is caught;
* if ``GEMINI_API_KEY`` is set: ``generate --attempts 3`` on ``canonical`` and two F4 scenarios.

Each trace is also kept under ``DAIL_LIVE_DATA``; the copy for the site goes to ``site/runs/`` with
``runs/index.json``. Before anything is written to the site, every trace is checked: it must not
contain the key's value (nor its first 6 characters) or a local file path; a trace that does is
refused and nothing is written for it.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from dail_demo import DEMO_LABEL
from dail_demo import scenarios as sc
from dail_demo.engine import new_run, resolve, run_evaluate
from dail_demo.environment import REPO_ROOT
from dail_demo.settings import SetupError, dail_config, terraform_runner, versions

RUNS: Final = REPO_ROOT / "site" / "runs"
SESSION_SCENARIO: Final = "tp-v1-F8-0196"
GEMINI_SCENARIOS: Final = ("canonical", "tp-v1-F4-0092", "tp-v1-F4-0093")
# A local path in a published trace: a drive-letter path, or a home or temporary directory. (No UNC
# pattern: in JSON text, the escaped newlines of a model's reply would match it.)
_LOCAL_PATH: Final = re.compile(r"(?i)(?:\b[a-z]:[\\/])|(?:/(?:home|users|tmp)/)")


class RecordError(SetupError):
    """A trace that may not be published (one line)."""


def publishable(text: str, environ: Mapping[str, str]) -> None:
    """Refuse a trace that holds the key (or its first 6 characters) or a local path."""
    key = environ.get("GEMINI_API_KEY", "").strip()
    if key and (key in text or (len(key) >= 6 and key[:6] in text)):
        raise RecordError("refused: the trace contains GEMINI_API_KEY")
    found = _LOCAL_PATH.search(text)
    if found:
        raise RecordError(f"refused: the trace contains a local path ({found.group(0)!r}...)")


def _summary(name: str, trace: Mapping[str, Any], group: str | None) -> dict[str, Any]:
    comparison = trace.get("comparison") or {}
    generation = trace.get("generation") or {}
    entry = {
        "file": f"{name}.json",
        "scenario_id": trace["scenario"]["scenario_id"],
        "family": trace["scenario"]["family"],
        "source": trace["candidate_source"],
        "label": trace["candidate"]["label"],
        "recorded_at": trace["created_at"],
        "refused_before_dail": bool(trace.get("refused_before_dail")),
        "decisions": {k: v["decision"] for k, v in comparison.items()},
        "check_counts": {k: v["check_count"] for k, v in comparison.items()},
        "group": group,
    }
    if generation:
        entry["model"] = (generation.get("settings") or {}).get("model")
        entry["attempts"] = [a["failure_class"] or "PATCH" for a in generation.get("attempts") or []]
    if trace.get("session"):
        entry["session_step"] = trace["session"].get("step")
    return entry


class Recorder:
    def __init__(self, environ: Mapping[str, str], out: Path = RUNS) -> None:
        self.environ = environ
        self.out = Path(out)
        self.staging: list[tuple[str, dict[str, Any], str | None]] = []

    def add(self, name: str, trace: dict[str, Any], group: str | None = None) -> None:
        text = json.dumps(trace, indent=1, ensure_ascii=False)
        publishable(text, self.environ)
        self.staging.append((name, trace, group))

    def write(self) -> list[dict[str, Any]]:
        """Replace ``site/runs/`` with the staged traces and their index."""
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        index = []
        for name, trace, group in self.staging:
            text = json.dumps(trace, indent=1, ensure_ascii=False) + "\n"
            publishable(text, self.environ)  # checked again as written
            (self.out / f"{name}.json").write_text(text, encoding="utf-8", newline="\n")
            index.append(_summary(name, trace, group))
        listing = {
            "schema": "dail-live-runs/1",
            "label": DEMO_LABEL,
            "recorded_at": datetime.now(UTC).isoformat(),
            "runs": index,
        }
        (self.out / "index.json").write_text(json.dumps(listing, indent=1) + "\n", encoding="utf-8", newline="\n")
        return index


def record_session(scenario_id: str, environ: Mapping[str, str]) -> list[dict[str, Any]]:
    """A scenario's steps in one DAIL session (one lineage), each through the validate gate."""
    from dail_demo import evaluate_core as core
    from experiments.generation.parent import config_only_copy
    from experiments.loader import step_content_hash

    run = new_run(environ, "session")
    source, tp_root = resolve(scenario_id, environ, run.dail_root)
    if source.scenario is None or tp_root is None:
        raise SetupError("a recorded session needs a TerraPreserve scenario")
    gate = terraform_runner(environ, run.root / "terraform")
    s0 = config_only_copy(source.s0_dir, run.root / "inputs" / "s0")
    session = core.Session(
        root=run.root, scenario=source.scenario, s0_dir=s0, config=dail_config(run.dail_root),
        session_id=run.run_id,
    )
    meta = versions(run.dail_root, tp_root)
    traces = []
    for step in source.scenario.steps[1:]:
        candidate_dir = config_only_copy(step.directory, run.root / "inputs" / f"step-{step.index}")
        check = gate(candidate_dir)
        if not check.ok:
            raise SetupError(f"{scenario_id} step {step.index}: terraform validate refused it: {check.error}")
        admission = {
            "stage": "fixed_patch",
            "admitted": True,
            "content_hash": step_content_hash(step.directory),
            "content_hash_matches_manifest": step_content_hash(step.directory) == step.content_hash,
            "terraform_validate": sc.admission_evidence(tp_root),
            "terraform_validate_run": check.to_dict(),
        }
        trace = session.submit(
            core.Candidate(
                source=core.FIXED_PATCH, label=f"{scenario_id} step {step.index}", directory=candidate_dir,
                admission=admission,
            ),
            label=DEMO_LABEL, versions=meta, step=step.index, extra={"refused_before_dail": False},
        )  # fmt: skip
        traces.append(trace)
        if not trace["session"]["promoted"]:
            break  # C-200: the rest of the scenario is not played
    verified = session.verify_chain()
    for trace in traces:
        trace["session"]["chain_check"] = verified
    return traces


def run_record(environ: Mapping[str, str], *, out: Path = RUNS, log: Any = print) -> dict[str, Any]:
    from dail_demo.generate import run_generate

    recorder = Recorder(environ, out)
    gate_root = new_run(environ, "record-gate").root / "terraform"
    gate = terraform_runner(environ, gate_root)
    fixed = [(sc.CANONICAL, "safe"), (sc.CANONICAL, "regression")] + [(sid, "fixed") for sid in sc.CURATED_IDS]
    for scenario_id, patch in fixed:
        outcome = run_evaluate(scenario_id, patch, environ=environ, terraform=gate, validate_fixed=True)
        recorder.add(f"{scenario_id}--{patch}", outcome.trace)
        c = outcome.trace["comparison"]
        log(f"recorded {scenario_id} {patch}: C {c['C']['decision']} ({c['C']['check_count']}), "
            f"A {c['A']['decision']} ({c['A']['check_count']})")
    for trace in record_session(SESSION_SCENARIO, environ):
        step = trace["session"]["step"]
        recorder.add(f"{SESSION_SCENARIO}--session-step-{step}", trace, group=f"{SESSION_SCENARIO} session")
        c = trace["comparison"]
        log(f"recorded {SESSION_SCENARIO} session step {step}: C {c['C']['decision']} "
            f"({c['C']['check_count']}), A {c['A']['decision']}; promoted {trace['session']['promoted']}; "
            f"chain {'verified' if trace['session']['chain_check']['ok'] else 'NOT verified'}")
    gemini = "NOT RUN — GEMINI_API_KEY is not set"
    if environ.get("GEMINI_API_KEY", "").strip():
        gemini = "run"
        for scenario_id in GEMINI_SCENARIOS:
            outcome = run_generate(scenario_id, attempts=3, environ=environ, terraform=gate)
            stamp = outcome.trace["created_at"][:19].replace(":", "").replace("-", "")
            recorder.add(f"{scenario_id}--gemini-{stamp}", outcome.trace)
            generation = outcome.trace["generation"]
            attempts = [a["failure_class"] or "PATCH" for a in generation.get("attempts") or []]
            decided = outcome.trace.get("comparison") or {}
            log(f"recorded {scenario_id} Gemini {generation['settings']['model']}: {generation['status']} "
                f"{generation.get('failure_class') or ''} attempts {attempts}"
                + (f"; C {decided['C']['decision']}, A {decided['A']['decision']}" if decided else
                   f"; nothing reached DAIL ({generation.get('detail') or generation.get('failure_class')})"))
    else:
        log(f"Gemini: {gemini}")
    index = recorder.write()
    return {"runs": len(index), "gemini": gemini, "out": str(out)}

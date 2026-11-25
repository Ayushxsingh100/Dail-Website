"""The evaluation core: baseline, conditions C and A, typed-patch admission and the trace
(PLAN §3.3, §3.6, §3.8; B work package §2.2, §2.3b, §2.4, §3.2).

**It decides nothing.** Every value in a trace is copied from what DAIL returns or stores: the
condition setup is DAIL's ``experiments.conditions.setup_for``, the baseline is DAIL's
``establish_baseline``, the decision is DAIL's ``EvaluationOrchestrator.evaluate``, and the records
are built by DAIL's own ``experiments.records`` helpers. The sequence is the one of DAIL's
experiment trial (``experiments/trial.py``): a fresh store, the earlier invariant versions
registered first, the baseline with the condition's definitions and bindings, then one candidate
evaluated against it. An LLM candidate is rebuilt from its reply by DAIL's patch validator and
evaluated through ``LLMEvaluationRequest``, as DAIL's replay does (``experiments/generation/
replay.py``).

**Built to run in the browser (PLAN §3.8).** This module imports only DAIL and the standard
library: no ``subprocess``, no threads, no network, no environment variables
(``tests/test_core_imports.py`` checks it). It reads and writes only inside the ``root`` directory
it is given; the caller copies the configurations it needs into ``root`` first. The optional
``terraform validate`` gate is a callable the caller passes in; in the browser there is none.

DAIL must already be importable (``dail_demo.settings.import_dail``) before this module is imported.
"""

from __future__ import annotations

import dataclasses
import difflib
import re
import shutil
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from core.application.baseline import BaselineRefused, BaselineRequest, establish_baseline
from core.application.orchestrator import (
    EvaluationOrchestrator,
    EvaluationRequest,
    EvaluationResult,
    LLMEvaluationRequest,
)
from core.domain.enums import CandidateSource
from core.domain.patch import Patch
from core.domain.registry_v1_1 import REGISTRY_VERSION_V1_1
from core.domain.repositories import UnitOfWork
from core.domain.state import TrustedState
from core.persistence.schema import initialize_database
from core.persistence.sqlite import SqliteUnitOfWork
from core.promotion.commit import PromotionContext
from core.terraform_model.config import ParseStatus, load_configuration
from core.terraform_model.normalization import normalize_directory
from experiments import records
from experiments.conditions import REGISTRY_RECORD, ConditionSetup, setup_for
from experiments.definition import Condition, name_id
from experiments.generation.task import change_scope
from experiments.loader import ScenarioInput, StepInput, step_content_hash
from experiments.trial import DAIL_CLOCK_BASE, STORE_NAME, LogicalClock
from llm.schemas.repair_response import RESPONSE_SCHEMA_VERSION, LLMRepairResponse, RepairStatus
from llm.validation.patch import PatchValidator, TerraformValidate

TRACE_SCHEMA: Final = "dail-live-trace/1"
FIXED_PATCH: Final = "FIXED_PATCH"
TYPED: Final = "TYPED"
LLM: Final = "LLM"
SOURCES: Final = (FIXED_PATCH, TYPED, LLM)
CONDITION_NAMES: Final = {Condition.C: "DAIL", Condition.A: "target-only"}
CONFIG_SUFFIXES: Final = (".tf", ".tf.json")
# The registry TerraPreserve v1.0 and DAIL's canonical fixtures name (registry-v1.0, version "1.0").
FIXTURE_REGISTRY_TAG: Final = "registry-v1.0"
FIXTURE_REGISTRY_VERSION: Final = "1.0"
ID_NAMESPACE: Final = "dail-live"


class CoreError(Exception):
    """The core cannot run as asked (a path outside the root, a fixture it cannot read)."""


@dataclass(frozen=True)
class Candidate:
    """One candidate: a directory (FIXED_PATCH, TYPED) or a parsed reply (LLM)."""

    source: str
    label: str
    directory: Path | None = None
    response: LLMRepairResponse | None = None
    request_id: str | None = None
    built_tree_hash: str | None = None
    admission: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise CoreError(f"unknown candidate source {self.source!r}")
        if self.source == LLM:
            if self.response is None or self.request_id is None or not self.built_tree_hash:
                raise CoreError("an LLM candidate needs its reply, request id and built tree hash")
        elif self.directory is None:
            raise CoreError(f"a {self.source} candidate needs a directory")


# --- paths -----------------------------------------------------------------------------------


def _inside(path: Path, root: Path) -> Path:
    resolved = Path(path).resolve()
    base = Path(root).resolve()
    if resolved != base and base not in resolved.parents:
        raise CoreError(f"{path} is outside the root directory {root}")
    return resolved


def config_files(directory: Path) -> list[Path]:
    """The top-level configuration files of ``directory`` (as DAIL's ``config_only_copy``)."""
    return sorted(
        p
        for p in Path(directory).iterdir()
        if p.is_file() and not p.is_symlink() and p.name.endswith(CONFIG_SUFFIXES)
    )


def unified_diff(parent_dir: Path, candidate_dir: Path) -> str:
    """The unified diff of the configuration files of two directories (display only)."""
    before = {p.name: p for p in config_files(parent_dir)}
    after = {p.name: p for p in config_files(candidate_dir)}
    chunks: list[str] = []
    for name in sorted(set(before) | set(after)):
        old = before[name].read_text(encoding="utf-8").splitlines(keepends=True) if name in before else []
        new = after[name].read_text(encoding="utf-8").splitlines(keepends=True) if name in after else []
        chunks.extend(
            difflib.unified_diff(
                old,
                new,
                fromfile=f"a/{name}" if name in before else "/dev/null",
                tofile=f"b/{name}" if name in after else "/dev/null",
            )
        )
    return "".join(line if line.endswith("\n") else line + "\n" for line in chunks)


# --- scenarios -------------------------------------------------------------------------------


def canonical_scenario(
    expected: Mapping[str, Any],
    s0_dir: Path,
    candidate_dir: Path | None = None,
    *,
    scenario_id: str = "canonical",
) -> ScenarioInput:
    """DAIL's canonical fixture as a ``ScenarioInput`` for ``setup_for``.

    Everything comes from the baseline fixture's ``expected.json``: the INV-FUNC-001 endpoints
    (``bindings``), the repair target (``baseline.remediation_targets``) and the four invariants it
    names (``results``) at the fixture's registry version (registry-v1.0 = "1.0", which
    ``setup_for`` maps to the registry-v1.1 definitions, C-203).
    """
    registry = expected.get("registry") or {}
    if registry.get("tag") != FIXTURE_REGISTRY_TAG:
        raise CoreError(f"the canonical fixture names registry {registry.get('tag')!r}")
    binding = (expected.get("bindings") or {}).get("INV-FUNC-001") or {}
    targets = list((expected.get("baseline") or {}).get("remediation_targets") or [])
    if len(targets) != 1 or not binding.get("S") or not binding.get("D"):
        raise CoreError("the canonical fixture must name one repair target and the INV-FUNC-001 binding")
    protected = tuple(sorted((inv, FIXTURE_REGISTRY_VERSION) for inv in expected.get("results") or {}))
    return ScenarioInput(
        scenario_id=scenario_id,
        family="canonical",
        split="fixture",
        template_id=str(expected.get("fixture_id")),
        source_lineage_id=None,
        target_kind="repair",
        target_invariant_id=targets[0],
        protected_invariants=protected,
        source_endpoint=binding["S"],
        destination_endpoint=binding["D"],
        variable_values={},
        steps=(StepInput(0, Path(s0_dir), step_content_hash(Path(s0_dir))),)
        + (
            ()
            if candidate_dir is None
            else (StepInput(1, Path(candidate_dir), step_content_hash(Path(candidate_dir))),)
        ),
    )


def s0_only(scenario: ScenarioInput) -> ScenarioInput:
    """The scenario with its first step only (as DAIL's replay): no target is open."""
    return dataclasses.replace(scenario, steps=scenario.steps[:1])


def scenario_record(scenario: ScenarioInput) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "family": scenario.family,
        "split": scenario.split,
        "template_id": scenario.template_id,
        "source_lineage_id": scenario.source_lineage_id,
        "target_kind": scenario.target_kind,
        "target_invariant_id": scenario.target_invariant_id,
        "protected_invariants": [list(p) for p in scenario.protected_invariants],
        "endpoints": {"S": scenario.source_endpoint, "D": scenario.destination_endpoint},
        "variable_values": dict(scenario.variable_values),
        "step_hashes": [s.content_hash for s in scenario.steps],
    }


# --- one condition -----------------------------------------------------------------------------


class _Run:
    """One condition on its own fresh store under ``root/<condition>`` (``experiments/trial.py``)."""

    def __init__(
        self, root: Path, condition: Condition, scenario: ScenarioInput, run_id: str, config: Any = None
    ) -> None:
        self.condition = condition
        self.config = config
        self.scenario = scenario
        self.run_id = run_id
        self.dir = root / condition.value
        if self.dir.exists():
            raise CoreError(f"{self.dir} exists: every run has a fresh store")
        self.setup: ConditionSetup = setup_for(condition, scenario, DAIL_CLOCK_BASE)
        self.store = self.dir / "store" / STORE_NAME
        self.store.parent.mkdir(parents=True)
        initialize_database(self.store)
        self.clock = LogicalClock()
        self.lineage_id = self.id("lineage")

    def factory(self) -> UnitOfWork:
        return SqliteUnitOfWork(self.store)

    def id(self, *parts: object) -> str:
        return name_id(ID_NAMESPACE, self.run_id, self.condition.value, *parts)

    def context(self, step: int) -> PromotionContext:
        return PromotionContext(
            run_id=self.id("run"),
            correlation_id=self.id("correlation"),
            operation_id=self.id("operation", step),
            attempt_id=self.id("attempt"),
            actor_id=None,
        )

    def baseline(self, s0_dir: Path) -> tuple[TrustedState | None, dict[str, Any]]:
        with self.factory() as uow:  # earlier versions first: no gaps (DAIL Doc 06 §4.2, C-203)
            for definition in self.setup.history:
                uow.invariants.register_definition(definition)
        request = BaselineRequest(
            baseline_id=self.id("baseline"),
            lineage_id=self.lineage_id,
            baseline_dir=s0_dir,
            variables=dict(self.scenario.variable_values),
            definitions=self.setup.baseline_definitions,
            bindings=self.setup.baseline_bindings,
            context=self.context(0),
            now=self.clock(),
            eligible=True,
            registry_version=REGISTRY_VERSION_V1_1,
            allow_no_invariants=self.setup.allow_no_invariants,
        )
        try:
            made = establish_baseline(self.factory, request)
        except BaselineRefused as refused:
            return None, {"outcome": "REFUSED", "reasons": list(refused.reasons)}
        return made.state, {"outcome": "ESTABLISHED", **records.state_summary(made.state)}

    def orchestrator(self) -> EvaluationOrchestrator:
        return EvaluationOrchestrator(
            self.factory,
            config=self.config,
            scope_policy=self.setup.scope_policy,
            clock=self.clock,
            policy_version=self.setup.policy_version,
            policy_factory=self.setup.policy_factory,
            identity_strategy=self.setup.identity_strategy,
        )


def _proof(entry: Any) -> dict[str, Any]:
    """A ``ProofPlanEntry`` (no ``to_dict`` in DAIL) as plain JSON, field by field."""
    return {
        "invariant_id": entry.invariant_id,
        "invariant_version": entry.invariant_version,
        "source": entry.source.value,
        "verification_id": entry.verification_id,
        "source_state_id": entry.source_state_id,
        "evidence_ids": list(entry.evidence_ids),
    }


def _changed(impact: Any) -> list[dict[str, Any]]:
    return [c.to_dict() for c in impact.changed_resources]


def _result(run: _Run, parent: TrustedState, opened: Sequence[str], evaluated: EvaluationResult,
            admission: Mapping[str, Any]) -> dict[str, Any]:
    """Copy what DAIL returned into the trace's condition section (no value computed here)."""
    t = records.transition_record(
        base={"condition": run.condition.value, "scenario_id": run.scenario.scenario_id},
        step=1,
        admission=admission,
        parent=parent,
        open_targets=opened,
        result=evaluated,
    )
    impact, report, decision, outcome = (
        evaluated.impact, evaluated.verification, evaluated.decision, evaluated.outcome,
    )  # fmt: skip
    return {
        "result_kind": evaluated.kind.value,
        "decision": t["decision"],
        "check_count": None if report is None else report.verifier_invocations,
        "identity": t["identity"],
        "changed_resources": None if impact is None else _changed(impact),
        "impact": None if impact is None else {
            "affected": [a.to_dict() for a in impact.affected_invariants],
            "unaffected": [u.to_dict() for u in impact.unaffected],
            "carry_forward_candidates": [c.to_dict() for c in impact.carry_forward_candidates],
            "uncertainty": [u.to_dict() for u in impact.uncertainty],
            "verification_work": [w.to_dict() for w in impact.verification_work],
        },
        "verification": [
            {
                "target": row["target_id"],
                "target_type": row["target_type"],
                "verifier": row["verifier_id"],
                "verifier_version": row["verifier_version"],
                "result": row["result"],
                "reason": row["reason"],
                "class": row["class"],
                "origin": row["origin"],
            }
            for row in t["work"]
        ],
        "required": t["required"],
        "proof_plan": None if outcome is None else [_proof(e) for e in outcome.proof_plan],
        "work_counts": t["work_counts"],
        "new_state": t["new_state"],
        "dail": {
            "transition": t,
            "impact": None if impact is None else records.stable(impact.to_dict()),
            "verification": None if report is None else records.stable(report.to_dict()),
            "decision": None if decision is None else decision.to_dict(),
        },
    }


def _condition(
    *,
    root: Path,
    condition: Condition,
    scenario: ScenarioInput,
    s0_dir: Path,
    candidate: Candidate,
    config: Any,
    run_id: str,
) -> tuple[dict[str, Any], str | None]:
    """One condition: (its trace section, the diff of an LLM build or None)."""
    started = time.perf_counter()
    run = _Run(root, condition, scenario, run_id, config)
    section: dict[str, Any] = {
        "condition": condition.value,
        "name": CONDITION_NAMES[condition],
        "versions": run.setup.versions(),
        "registry": dict(REGISTRY_RECORD),
        "baseline": None,
        "decision": None,
        "check_count": None,
        "rebuild_failure": None,
    }
    parent, section["baseline"] = run.baseline(s0_dir)
    diff: str | None = None
    if parent is None:
        section["wall_seconds"] = time.perf_counter() - started
        return section, diff
    orchestrator = run.orchestrator()
    opened = run.setup.open_targets(scenario, 1)
    if candidate.source == LLM:
        assert candidate.response is not None and candidate.request_id is not None
        validator = PatchValidator(
            parent_dir=s0_dir,
            trusted=parent,
            scope=change_scope(parent.resources),
            work_root=run.dir / "builds",
            variables=dict(scenario.variable_values),
            now=run.clock(),
        )
        outcome = validator.validate(
            candidate.response, request_id=candidate.request_id, patch_id=run.id("patch", 1)
        )
        build = outcome.build
        if build is None:
            section["rebuild_failure"] = {
                "failure_class": None if outcome.failure_class is None else outcome.failure_class.value,
                "errors": list(outcome.errors),
            }
            section["wall_seconds"] = time.perf_counter() - started
            return section, diff
        try:
            if build.tree_hash != candidate.built_tree_hash:
                section["rebuild_failure"] = {
                    "failure_class": None,
                    "errors": [
                        f"the rebuilt tree {build.tree_hash} is not the generated "
                        f"{candidate.built_tree_hash}"
                    ],
                }
                section["wall_seconds"] = time.perf_counter() - started
                return section, diff
            diff = unified_diff(s0_dir, build.candidate_dir)
            request: EvaluationRequest = LLMEvaluationRequest(
                lineage_id=run.lineage_id,
                candidate_id=run.id("candidate", 1),
                candidate_sequence=1,
                attempt_number=1,
                patch=build.patch,
                candidate_dir=build.candidate_dir,
                variables=dict(scenario.variable_values),
                definitions=run.setup.definitions,
                bindings=run.setup.bindings,
                context=run.context(1),
                open_targets=opened,
                built_tree_hash=build.tree_hash,
            )
            evaluated = orchestrator.evaluate(request)
        finally:
            shutil.rmtree(build.candidate_dir.parent, ignore_errors=True)
    else:
        assert candidate.directory is not None
        patch = Patch.create(
            source=CandidateSource.FIXED_PATCH,
            content=f"DAIL Live {candidate.source} candidate: {candidate.label}\n",
            parent_state_id=parent.state_id,
            now=run.clock(),
            patch_id=run.id("patch", 1),
        )
        request = EvaluationRequest(
            lineage_id=run.lineage_id,
            candidate_id=run.id("candidate", 1),
            candidate_sequence=1,
            attempt_number=1,
            patch=patch,
            candidate_dir=candidate.directory,
            variables=dict(scenario.variable_values),
            definitions=run.setup.definitions,
            bindings=run.setup.bindings,
            context=run.context(1),
            open_targets=opened,
        )
        evaluated = orchestrator.evaluate(request)
    section.update(_result(run, parent, opened, evaluated, candidate.admission))
    section["store"] = run.store.relative_to(root).as_posix()
    section["wall_seconds"] = time.perf_counter() - started
    return section, diff


# --- the evaluation ----------------------------------------------------------------------------


def evaluate(
    *,
    root: Path,
    scenario: ScenarioInput,
    s0_dir: Path,
    candidate: Candidate,
    config: Any,
    run_id: str,
    label: str,
    versions: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate ``candidate`` under DAIL (C) and target-only (A); return the trace.

    C's store is kept under ``root/C`` (for package C's sessions); A's store is a throwaway and is
    removed once its section is built (PLAN §3.6). Only DAIL's lineage ever advances.
    """
    root = Path(root).resolve()
    s0_dir = _inside(s0_dir, root)
    if candidate.directory is not None:
        candidate = dataclasses.replace(candidate, directory=_inside(candidate.directory, root))
    sections: dict[str, Any] = {}
    llm_diff: str | None = None
    for condition in (Condition.C, Condition.A):
        section, diff = _condition(
            root=root,
            condition=condition,
            scenario=scenario,
            s0_dir=s0_dir,
            candidate=candidate,
            config=config,
            run_id=run_id,
        )
        sections[condition.value] = section
        if condition is Condition.C:
            llm_diff = diff
    shutil.rmtree(root / Condition.A.value, ignore_errors=True)
    sections[Condition.A.value]["store"] = None  # the throwaway store is gone
    diff = llm_diff if candidate.source == LLM else unified_diff(s0_dir, candidate.directory)  # type: ignore[arg-type]
    return {
        **base_trace(
            label=label,
            versions=versions,
            scenario=scenario,
            candidate=candidate,
            run_id=run_id,
        ),
        "diff": diff,
        "admission": dict(candidate.admission),
        "conditions": sections,
        "comparison": {
            key: {
                "name": section["name"],
                "decision": None if section["decision"] is None else section["decision"]["type"],
                "reason": None if section["decision"] is None else section["decision"]["reason"],
                "check_count": section["check_count"],
            }
            for key, section in sections.items()
        },
        **dict(extra or {}),
    }


def base_trace(
    *, label: str, versions: Mapping[str, Any], scenario: ScenarioInput, candidate: Candidate,
    run_id: str,
) -> dict[str, Any]:
    """The fields every trace has, also one refused before DAIL."""
    return {
        "schema": TRACE_SCHEMA,
        "label": label,
        "created_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "versions": {**dict(versions), "registry": dict(REGISTRY_RECORD)},
        "scenario": scenario_record(scenario),
        "candidate_source": candidate.source,
        "candidate": {
            "label": candidate.label,
            "request_id": candidate.request_id,
            "built_tree_hash": candidate.built_tree_hash,
        },
    }


# --- typed patches -----------------------------------------------------------------------------

_LINE_COMMENT = re.compile(r"(?m)^[ \t]*(?:#|//).*$")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_SPACE = re.compile(r"\s+")


def _squash(text: str) -> str:
    return _SPACE.sub(" ", _BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub("", text))).strip()


def _loaded(directory: Path) -> tuple[Any, dict[str, bytes]]:
    outcome = load_configuration(directory)
    if outcome.configuration is None or outcome.status is not ParseStatus.OK:
        detail = "; ".join(str(e) for e in getattr(outcome, "errors", ()) or ()) or str(outcome.status)
        raise CoreError(f"DAIL's parser refuses the configuration: {detail}")
    configuration = outcome.configuration
    files = {name: (directory / name).read_bytes() for name in configuration.files}
    return configuration, files


def _blocks(configuration: Any, files: Mapping[str, bytes]) -> dict[str, str]:
    found = {}
    for (kind, name), decl in configuration.resources.items():
        data = files[decl.file]
        found[f"{kind}.{name}"] = data[decl.block.range.start_byte : decl.block.range.end_byte].decode(
            "utf-8", "surrogateescape"
        )
    return found


def _outside_resources(configuration: Any, files: Mapping[str, bytes]) -> list[str]:
    """The squashed text of each file with its resource blocks cut out (non-empty ones, sorted)."""
    cuts: dict[str, list[tuple[int, int]]] = {}
    for decl in configuration.resources.values():
        cuts.setdefault(decl.file, []).append((decl.block.range.start_byte, decl.block.range.end_byte))
    rest = []
    for name, data in files.items():
        for start, end in sorted(cuts.get(name, []), reverse=True):
            data = data[:start] + data[end:]
        squashed = _squash(data.decode("utf-8", "surrogateescape"))
        if squashed:
            rest.append(squashed)
    return sorted(rest)


def typed_response(parent_dir: Path, edited_dir: Path) -> LLMRepairResponse:
    """A typed directory as the resource-block patch DAIL's patch validator checks.

    Every resource block that is new or whose text differs (comments and spacing aside) is copied
    as written; a parent resource that is gone is listed without a block (a DELETE). Anything that
    changed outside resource blocks cannot be expressed as such a patch and is refused. This is
    input conversion only: the validator then runs all of its checks on the result.
    """
    parent, parent_files = _loaded(parent_dir)
    edited, edited_files = _loaded(edited_dir)
    if _outside_resources(parent, parent_files) != _outside_resources(edited, edited_files):
        raise CoreError(
            "the typed configuration changes something outside resource blocks; a typed patch may "
            "add, change or remove resource blocks only (as DAIL's LLM patches)"
        )
    before, after = _blocks(parent, parent_files), _blocks(edited, edited_files)
    changed = [a for a in sorted(after) if a not in before or _squash(after[a]) != _squash(before[a])]
    deleted = [a for a in sorted(before) if a not in after]
    if not changed and not deleted:
        raise CoreError("the typed configuration changes no resource block")
    return LLMRepairResponse(
        schema_version=RESPONSE_SCHEMA_VERSION,
        status=RepairStatus.PATCH,
        summary="typed patch",
        patch="\n\n".join(after[a] for a in changed) + "\n" if changed else "",
        changed_addresses=tuple(changed + deleted),
        assumptions=(),
        rationale="written by a person in the demo's typed-patch mode",
    )


def admit_typed(
    *,
    root: Path,
    scenario: ScenarioInput,
    s0_dir: Path,
    edited_dir: Path,
    run_id: str,
    terraform_validate: TerraformValidate | None,
) -> dict[str, Any]:
    """Admission of a typed directory by DAIL's patch validator (B work package §3.2).

    The validator is built on condition C's S0 (in its own throwaway store under
    ``root/admission``); with ``terraform_validate`` it also runs the pinned validate gate on the
    build (check 9b). Admitted only if the validator builds the patch and the build has the same
    normalized resource set as the typed directory. Nothing here reaches the orchestrator.
    """
    root = Path(root).resolve()
    s0_dir, edited_dir = _inside(s0_dir, root), _inside(edited_dir, root)
    record: dict[str, Any] = {
        "stage": "dail_patch_validator",
        "admitted": False,
        "failure_class": None,
        "errors": [],
        "operations": [],
        "terraform_validate": None,
    }
    try:
        response = typed_response(s0_dir, edited_dir)
    except CoreError as refused:
        record["errors"] = [str(refused)]
        return record
    run = _Run(root / "admission", Condition.C, s0_only(scenario), run_id)
    try:
        parent, baseline = run.baseline(s0_dir)
        if parent is None:
            record["errors"] = [f"the S0 baseline was refused: {baseline['reasons']}"]
            return record
        validator = PatchValidator(
            parent_dir=s0_dir,
            trusted=parent,
            scope=change_scope(parent.resources),
            work_root=run.dir / "builds",
            variables=dict(scenario.variable_values),
            now=DAIL_CLOCK_BASE,
            terraform_validate=terraform_validate,
        )
        outcome = validator.validate(response, request_id=run.id("typed-request"))
        record["operations"] = [[a, op.value] for a, op in outcome.operations]
        record["terraform_validate"] = None if outcome.terraform is None else dict(outcome.terraform)
        build = outcome.build
        if build is None:
            record["failure_class"] = None if outcome.failure_class is None else outcome.failure_class.value
            record["errors"] = list(outcome.errors)
            return record
        typed = normalize_directory(edited_dir, dict(scenario.variable_values), now=DAIL_CLOCK_BASE)
        if typed.resource_set_hash != build.resource_set_hash:
            record["errors"] = [
                "the validator's build is not the typed configuration (resource-set hash "
                f"{build.resource_set_hash} against {typed.resource_set_hash})"
            ]
            return record
        record["admitted"] = True
        record["patch_changed_addresses"] = list(response.changed_addresses)
        return record
    finally:
        shutil.rmtree(root / "admission", ignore_errors=True)

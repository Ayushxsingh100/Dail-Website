"""``python -m dail_demo generate``: Gemini repair attempts through DAIL's generator, and every valid
candidate through the engine (PLAN §3.5, §4 step 3; B work package §3.3).

Local only (network, environment, Terraform). Generation is DAIL's own, unchanged:

* the parent is S0, built by DAIL's ``experiments.generation.parent.s0_parent`` (configuration-only
  copy, registry v1.1, the INV-FUNC-001 binding);
* the context is DAIL's ``build_context`` with the inputs DAIL's generation uses
  (``experiments/generation/run.py``): the target invariant as the repair target, the focus of
  ``task.focus_for``, the scope of ``task.change_scope`` and the objective of ``task.objective_for``;
  the prompt is DAIL's ``dail-repair-prompt-3``, rendered by DAIL's ``Generator``;
* DAIL's ``Generator`` calls the provider, parses each reply with DAIL's parser and checks it with
  DAIL's ``PatchValidator`` and the pinned ``terraform validate`` gate (``Generator`` refuses to
  start without the gate, C-227);
* a valid candidate is evaluated by ``evaluate_core`` under C and A (rebuilt from the reply by the
  validator for each condition, as DAIL's replay does); an invalid one never reaches the
  orchestrator.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from dail_demo import DEMO_LABEL
from dail_demo.engine import (
    EXIT_DECIDED,
    EXIT_REFUSED,
    Outcome,
    Run,
    new_run,
    resolve,
    write_trace,
)
from dail_demo.engine import summary_lines as engine_summary
from dail_demo.settings import (
    GeminiSettings,
    SetupError,
    committed_copy,
    dail_config,
    gemini_settings,
    terraform_runner,
    versions,
)

MAX_ATTEMPTS: Final = 3  # DAIL Live's limit (PLAN §2: up to 3 attempts)
RETRY_ON: Final = ("TRANSIENT_ERROR", "INVALID_OUTPUT", "NO_SOLUTION")


def _wall() -> datetime:
    return datetime.now(UTC)


def _context(given: Any, parent: Any) -> tuple[Any, dict[str, Any]]:
    """DAIL's ``build_context`` with the inputs ``experiments/generation/run.py`` gives it."""
    from experiments.generation.task import (
        change_scope,
        config_address,
        focus_for,
        objective_for,
        scope_record,
    )
    from llm.adapter.context import ContextInputs, build_context

    state = parent.state
    (target,) = (d for d in parent.definitions if d.invariant_id == given.target_invariant_id)
    scope = change_scope(state.resources)
    focus = focus_for(target, state.resources)
    objective = objective_for(target)
    context = build_context(
        ContextInputs(
            parent_state_id=state.state_id,
            trusted_state_hash=state.state_hash,
            resources=tuple(state.resources),
            invariants=parent.definitions,
            statuses={r.invariant_id: r.status.value for r in state.invariant_refs},
            objective=objective,
            repair_targets=(target.invariant_id,),
            scope=scope,
            focus=focus,
        )
    )
    facts = {
        "parent": {
            "state_id": state.state_id,
            "state_hash": state.state_hash,
            "resource_set_hash": state.resource_set_hash(),
            "resource_addresses": sorted({config_address(r.address) for r in state.resources}),
            "s0_content_hash": given.s0_content_hash,
            "invariants": {
                r.invariant_id: {"version": r.invariant_version, "status": r.status.value}
                for r in state.invariant_refs
            },
        },
        "scope": scope_record(scope),
        "objective": objective,
        "focus": list(focus),
        "target_invariant_id": target.invariant_id,
    }
    return context, facts


def _attempt_rows(result: Any) -> list[dict[str, Any]]:
    rows = []
    for attempt in result.attempts:
        response = attempt.response
        rows.append(
            {
                "attempt": attempt.request.attempt_number,
                "failure_class": None if response.failure_class is None else response.failure_class.value,
                "parsed_status": response.parsed_status,
                "parse_errors": list(response.parse_errors),
                "validator_version": response.validator_version,
                "validation_errors": list(response.validation_errors),
                "candidate_tree_hash": response.candidate_tree_hash,
                "request": attempt.request.to_dict(),
                "response": response.to_dict(),
            }
        )
    return rows


def _refused(run: Run, environ: Mapping[str, str], out: Path | None, scenario: Any, meta: Any,
             generation: dict[str, Any]) -> Outcome:
    """A generation with no valid candidate: written as a trace, never sent to DAIL."""
    from dail_demo import evaluate_core as core

    trace = {
        "schema": core.TRACE_SCHEMA,
        "label": DEMO_LABEL,
        "created_at": _wall().isoformat(),
        "run_id": run.run_id,
        "versions": {**meta, "registry": dict(core.REGISTRY_RECORD)},
        "scenario": core.scenario_record(scenario),
        "candidate_source": core.LLM,
        "candidate": {"label": f"{scenario.scenario_id} {generation.get('provider')} repair",
                      "request_id": None, "built_tree_hash": None},
        "diff": None,
        "admission": {"stage": "dail_generator", "admitted": False},
        "generation": generation,
        "conditions": None,
        "refused_before_dail": True,
    }
    return Outcome(trace, write_trace(trace, run, environ, out), EXIT_REFUSED)


def run_generate(
    scenario_id: str,
    *,
    attempts: int,
    environ: Mapping[str, str],
    out: Path | None = None,
    provider: Any = None,
    terraform: Any = None,
    settings: GeminiSettings | None = None,
    context_window: int | None = None,
) -> Outcome:
    """Generate up to ``attempts`` replies and evaluate a valid candidate.

    ``provider``, ``terraform`` and ``context_window`` replace the Gemini provider, the real
    validate gate and the API's input token limit (tests only: DAIL's ``FakeProvider`` and a fake
    gate; no network in tests).
    """
    if not 1 <= attempts <= MAX_ATTEMPTS:
        raise SetupError(f"--attempts must be 1 to {MAX_ATTEMPTS}")
    run = new_run(environ, "generate")
    from dail_demo import evaluate_core as core
    from dail_demo.gemini import GeminiProvider
    from experiments.generation.models import SAFETY_MARGIN
    from experiments.generation.parent import config_only_copy, s0_parent
    from experiments.generation.run import failure_source
    from experiments.generation.task import change_scope, generation_input
    from llm.adapter.generate import Generator
    from llm.adapter.provider import ProviderError
    from llm.prompts.templates import PROMPT_VERSION
    from llm.schemas.records import BudgetConfig, FailureClass, LLMConfig, RetryPolicy
    from llm.schemas.repair_response import RESPONSE_SCHEMA_VERSION
    from llm.validation.parser import parse_response
    from llm.validation.patch import PatchValidator

    source, tp_root = resolve(scenario_id, environ, run.dail_root)
    meta = versions(run.dail_root, tp_root)
    s0_target = run.root / "inputs" / "s0"
    if source.scenario is None:  # DAIL's own fixture: its committed bytes (D-28)
        s0_copy = committed_copy(run.dail_root, source.s0_dir, s0_target)
    else:
        s0_copy = config_only_copy(source.s0_dir, s0_target)
    if source.scenario is None:
        assert source.expected is not None
        scenario = core.canonical_scenario(source.expected, s0_copy)
    else:
        scenario = core.s0_only(source.scenario)
    given = generation_input(scenario)
    settings = settings or gemini_settings()
    generation: dict[str, Any] = {
        "provider": "gemini" if provider is None else provider.name,
        "settings": settings.to_dict(),
        "status": None,
        "failure_class": None,
        "detail": "",
    }

    if provider is None:
        provider = GeminiProvider.from_environment(
            environ, model=settings.model, endpoint=settings.endpoint, api_version=settings.api_version
        )
    if isinstance(provider, GeminiProvider):
        try:
            facts = provider.check_model(timeout=settings.timeout_seconds)
        except ProviderError as error:
            generation.update(status="NOT_STARTED", failure_class=error.failure_class.value, detail=error.detail)
            return _refused(run, environ, out, scenario, meta, generation)
        window = facts.get("input_token_limit")
        model_version = str(facts["name"])
    else:
        facts = {"name": provider.name}
        window = context_window
        model_version = f"{provider.name}-test"
    generation["model"] = facts
    if not isinstance(window, int) or window <= settings.max_output_tokens + SAFETY_MARGIN:
        raise SetupError("the model's input token limit is unknown or too small for the budget")

    gate = terraform if terraform is not None else terraform_runner(environ, run.root / "terraform")
    parent = s0_parent(given, run.root / "parent", "dail-live")
    context, context_facts = _context(given, parent)
    policy = RetryPolicy(
        policy_id=f"dail-live-retry-{attempts}",
        max_attempts=attempts,
        retry_on=tuple(FailureClass(c) for c in RETRY_ON),
        backoff_seconds=0.0,
        prompt_adjustment_policy="none",
    )
    config = LLMConfig(
        provider=provider.name,
        model_name=settings.model,
        model_version=model_version,
        temperature=settings.temperature,
        top_p=settings.top_p,
        seed=settings.seed,
        max_output_tokens=settings.max_output_tokens,
        timeout_seconds=settings.timeout_seconds,
        retry_policy_id=policy.policy_id,
        prompt_version=PROMPT_VERSION,
        response_schema_version=RESPONSE_SCHEMA_VERSION,
    )
    validator = PatchValidator(
        parent_dir=parent.directory,
        trusted=parent.state,
        scope=change_scope(parent.state.resources),
        work_root=run.root / "generation-builds",
        variables=dict(given.variable_values),
        now=core.DAIL_CLOCK_BASE,
        terraform_validate=gate,
    )
    generator = Generator(
        provider=provider,
        config=config,
        retry_policy=policy,
        budget=BudgetConfig(
            max_context_tokens=window,
            reserved_output_tokens=settings.max_output_tokens,
            safety_margin=SAFETY_MARGIN,
        ),
        generation_enabled=dail_config(run.dail_root).get("llm.generation_enabled") is True,
        clock=_wall,
        validator=validator,
    )
    result = generator.generate(context)
    generation.update(
        status=result.status.value,
        failure_class=None if result.failure_class is None else result.failure_class.value,
        failure_source=failure_source(result),
        detail=result.detail,
        config=result.config.to_dict(),
        retry_policy=policy.to_dict(),
        context_version=result.context_version,
        context_hash=result.context_hash,
        prompt_version=result.prompt_version,
        prompt_hash=result.prompt_hash,
        parser_version=result.parser_version,
        validator_version=result.validator_version,
        observability=result.observability(),
        context=context_facts,
        attempts=_attempt_rows(result),
        model_versions_reported=list(getattr(provider, "model_versions", [])),
    )
    build = result.build
    if result.status.value != "PATCH" or build is None:
        if build is not None:
            shutil.rmtree(build.candidate_dir.parent, ignore_errors=True)
        return _refused(run, environ, out, scenario, meta, generation)
    try:
        final = result.attempts[-1].response
        parsed = parse_response(final.raw_response)
        if parsed.response is None:
            generation["detail"] = f"the recorded reply does not parse again: {list(parsed.errors)}"
            return _refused(run, environ, out, scenario, meta, generation)
        candidate = core.Candidate(
            source=core.LLM,
            label=f"{scenario.scenario_id} {provider.name} repair, attempt {len(result.attempts)}",
            response=parsed.response,
            request_id=final.request_id,
            built_tree_hash=build.tree_hash,
            admission={
                "stage": "dail_generator",
                "admitted": True,
                "validator_version": final.validator_version,
                "terraform_validate": None if gate is None else dict(getattr(gate, "versions", {}) or {}),
            },
        )
    finally:
        shutil.rmtree(build.candidate_dir.parent, ignore_errors=True)
    trace = core.evaluate(
        root=run.root,
        scenario=scenario,
        s0_dir=parent.directory,
        candidate=candidate,
        config=dail_config(run.dail_root),
        run_id=run.run_id,
        label=DEMO_LABEL,
        versions=meta,
        extra={"generation": generation, "refused_before_dail": False},
    )
    return Outcome(trace, write_trace(trace, run, environ, out), EXIT_DECIDED)


def summary_lines(trace: Mapping[str, Any], path: Path) -> list[str]:
    generation = trace.get("generation") or {}
    lines = [f"DAIL Live ({trace['label']})", f"scenario {trace['scenario']['scenario_id']}: "
             f"{generation.get('provider')} {generation.get('settings', {}).get('model')}"]
    if generation.get("status") == "NOT_STARTED":
        lines.append(f"not started: {generation.get('failure_class')}: {generation.get('detail')}")
    for row in generation.get("attempts") or []:
        verdict = "valid PATCH" if row["failure_class"] is None else row["failure_class"]
        parser = "; ".join(row["parse_errors"]) or (row["parsed_status"] or "no reply")
        validator = "; ".join(row["validation_errors"]) or ("ok" if row["failure_class"] is None else "-")
        lines.append(f"attempt {row['attempt']}: {verdict} | parser: {parser} | validator: {validator}")
    if trace.get("refused_before_dail"):
        lines.append(
            f"no valid candidate: {generation.get('status')} {generation.get('failure_class') or ''}".rstrip()
            + "; nothing reached DAIL"
        )
        lines.append(f"trace: {path}")
        return lines
    return lines + engine_summary(trace, path)[2:]

"""DAIL's repair context and prompt for one parent state, shared by ``generate`` and the proxy (D-18).

Only DAIL's public functions are called, with the inputs DAIL's generation gives them
(``experiments/generation/run.py``). DAIL's prompt is rendered by DAIL (``llm.prompts.templates``).
"""

from __future__ import annotations

from typing import Any


def context_for(given: Any, parent: Any) -> tuple[Any, dict[str, Any]]:
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

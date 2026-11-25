"""The scenarios DAIL Live offers (B work package §2.1, §3.1; decisions D-16).

* ``canonical``: DAIL's own fixture ``fixtures/canonical_regression`` (baseline, ``patch_safe``,
  ``patch_regression``), read from ``DAIL_ROOT``.
* a short curated list of TerraPreserve **repair** scenarios of the controlled tier (a template id,
  no real-world source), loaded only through DAIL's loader ``experiments.loader.load(root,
  split="dev")``, which verifies the manifest hash and every step hash and refuses the test split,
  and projected through DAIL's ``experiments.generation.task.generation_input``, which refuses a
  scenario that is not a repair.

The reasons for each choice are in ``docs/DECISIONS.md`` (D-16).
"""

from __future__ import annotations

import functools
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

CANONICAL: Final = "canonical"
CANONICAL_DIR: Final = Path("fixtures") / "canonical_regression"
CANONICAL_PATCHES: Final = {"safe": "patch_safe", "regression": "patch_regression"}

# (id, family, what it shows). All controlled tier, dev split, repair scenarios.
CURATED: Final = (
    ("tp-v1-F2-0027", "F2", "a safe SSH repair (INV-SEC-001): the target is fixed and nothing breaks"),
    ("tp-v1-F2-0040", "F2", "an unsafe SSH repair: INV-SEC-001 is still violated after the fix"),
    ("tp-v1-F4-0079", "F4", "a safe SSH repair in the family where a fix can break another invariant"),
    ("tp-v1-F4-0092", "F4", "an SSH repair that removes the database ingress: INV-FUNC-001 breaks"),
    ("tp-v1-F4-0093", "F4", "an INV-SEC-002 repair that opens SSH again: INV-SEC-001 breaks"),
    ("tp-v1-F8-0192", "F8", "the first step of a safe two-step repair (the target stays open)"),
    ("tp-v1-F8-0196", "F8", "the first step of a two-step repair that ends by breaking INV-FUNC-001"),
)
CURATED_IDS: Final = tuple(entry[0] for entry in CURATED)


class ScenarioError(Exception):
    """The scenario cannot be offered (one line, safe to print)."""


@dataclass(frozen=True)
class Source:
    """Where a scenario's files are (outside the run root; the engine copies them in)."""

    scenario_id: str
    s0_dir: Path
    fixed: Mapping[str, Path]  # patch name -> directory
    scenario: Any = None  # a DAIL ScenarioInput for TerraPreserve; None for canonical
    expected: Mapping[str, Any] | None = None  # the canonical baseline's expected.json


def canonical(dail_root: Path) -> Source:
    base = Path(dail_root) / CANONICAL_DIR
    expected = json.loads((base / "baseline" / "expected.json").read_text(encoding="utf-8"))
    return Source(
        scenario_id=CANONICAL,
        s0_dir=base / "baseline",
        fixed={name: base / folder for name, folder in CANONICAL_PATCHES.items()},
        expected=expected,
    )


def expected_decision(dail_root: Path, patch: str) -> list[str]:
    """``decision.allowed`` of a canonical patch's ``expected.json`` (for the tests)."""
    folder = Path(dail_root) / CANONICAL_DIR / CANONICAL_PATCHES[patch]
    data = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
    return list(data["decision"]["allowed"])


@functools.lru_cache(maxsize=2)
def _loaded(root: str) -> Any:
    from experiments.loader import LoaderError, load

    try:
        return load(Path(root), split="dev")
    except LoaderError as error:
        raise ScenarioError(f"DAIL's loader refused the TerraPreserve checkout: {error}") from None


def terrapreserve(tp_root: Path, scenario_id: str) -> Source:
    """A curated TerraPreserve scenario, through DAIL's loader and ``generation_input``."""
    from experiments.generation.task import GenerationError, generation_input

    if scenario_id not in CURATED_IDS:
        raise ScenarioError(
            f"{scenario_id} is not offered; the scenarios are {CANONICAL} and " + ", ".join(CURATED_IDS)
        )
    loaded = _loaded(str(Path(tp_root).resolve()))
    found = {s.scenario_id: s for s in loaded.scenarios}
    if scenario_id not in found:
        raise ScenarioError(f"{scenario_id} is not in the dev split of the TerraPreserve manifest")
    scenario = found[scenario_id]
    try:
        given = generation_input(scenario)
    except GenerationError as error:
        raise ScenarioError(str(error)) from None
    if scenario.transitions < 1:
        raise ScenarioError(f"{scenario_id} has no step 1")
    return Source(
        scenario_id=scenario_id,
        s0_dir=given.s0_dir,
        fixed={"fixed": scenario.steps[1].directory},
        scenario=scenario,
    )


def admission_evidence(tp_root: Path) -> str:
    """DAIL's admission evidence for steps of the pinned TerraPreserve manifest (C-201)."""
    return _loaded(str(Path(tp_root).resolve())).admission_evidence

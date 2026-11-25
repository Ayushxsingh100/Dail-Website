"""The browser bridge: what the website's JavaScript calls inside Pyodide (PLAN §3.8; C work
package §1, §2.2, §2.3).

It uses only DAIL, the standard library and ``dail_demo.evaluate_core`` (``tests/test_core_imports.py``
checks it), and reads only the bundled files under ``vendor`` (``python -m dail_demo bundle``) and
its own ``work`` directory in Pyodide's in-memory file system. Every decision is DAIL's: this module
copies files, builds the same ``ScenarioInput`` the local engine builds, and calls the core.

* ``evaluate_fixed(scenario_id, patch)``: one fixed patch under C and A, exactly as
  ``python -m dail_demo evaluate --patch <safe|regression|fixed>`` does (the feasibility gate).
* ``start``, ``submit_files``, ``submit_patch``, ``verify_chain``: the tab's session (L4). A typed
  edit is admitted by DAIL's patch validator only: **Terraform validation is not run in the
  browser.**

Every entry point takes and returns JSON text, so the JavaScript side never handles Python objects.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Final

from dail_demo import DEMO_LABEL
from dail_demo import evaluate_core as core
from experiments.loader import ScenarioInput, StepInput, step_content_hash
from llm.validation.parser import parse_response

NOT_VALIDATED: Final = "Terraform validation is not run in the browser."
_FILE_NAME: Final = re.compile(r"^[A-Za-z0-9_.-]{1,80}\.tf$")
MAX_FILE_BYTES: Final = 200_000


class BridgeError(Exception):
    """A request the bridge refuses (a bad file name, an unknown scenario): one line."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


class Live:
    def __init__(self, vendor: str, work: str) -> None:
        self.vendor = Path(vendor)
        self.work = Path(work)
        self.work.mkdir(parents=True, exist_ok=True)
        self._n = 0
        self.config = core.build_config(
            self.vendor / "dail" / "config",
            self.vendor / "dail_live" / "config" / "promotion.toml",
            self.vendor / "dail_live" / "config" / "llm.toml",
            self._fresh("config"),
        )
        self.versions = {
            **json.loads((self.vendor / "dail" / "VERSION.json").read_text(encoding="utf-8")),
            "runtime": "browser (Pyodide)",
        }
        self.index = json.loads((self.vendor / "scenarios" / "index.json").read_text(encoding="utf-8"))
        self.session: core.Session | None = None
        self._listener: Any = None
        self.session_id: str | None = None
        self.scenario_id: str | None = None

    def listen(self, listener: Any) -> None:
        """``listener(name)`` is called with ``ADMITTED`` and then with each audit event DAIL commits
        for the session's candidate, as it commits it (the page fills its stages from these)."""
        self._listener = listener

    def _notify(self, name: str) -> None:
        if self._listener is not None:
            self._listener(name)

    # --- helpers ---------------------------------------------------------------------------------

    def _fresh(self, kind: str) -> Path:
        self._n += 1
        path = self.work / f"{kind}-{self._n}"
        if path.exists():
            shutil.rmtree(path)
        return path

    def pack(self, scenario_id: str) -> dict[str, Any]:
        ids = {entry["id"] for entry in self.index["scenarios"]}
        if scenario_id not in ids:
            raise BridgeError(f"unknown scenario {scenario_id!r}")
        path = self.vendor / "scenarios" / scenario_id / "scenario.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _copy(self, source: Path, target: Path) -> Path:
        target.mkdir(parents=True)
        for path in core.config_files(source):
            shutil.copyfile(path, target / path.name)
        return target

    def _scenario(self, pack: dict[str, Any], steps: list[tuple[int, Path]]) -> ScenarioInput:
        """The ``ScenarioInput`` of a pack, with each step's content hash checked."""
        record = pack["record"]
        found = []
        for index, directory in steps:
            recomputed = step_content_hash(directory)
            pinned = pack["hashes"].get(str(index)) if index == 0 else None
            if pinned is not None and recomputed != pinned:
                raise BridgeError(f"{record['scenario_id']} step {index}: the content hash is not the pack's")
            found.append(StepInput(index, directory, recomputed))
        return ScenarioInput(
            scenario_id=record["scenario_id"],
            family=record["family"],
            split=record["split"],
            template_id=record["template_id"],
            source_lineage_id=record["source_lineage_id"],
            target_kind=record["target_kind"],
            target_invariant_id=record["target_invariant_id"],
            protected_invariants=tuple(tuple(p) for p in record["protected_invariants"]),
            source_endpoint=record["endpoints"]["S"],
            destination_endpoint=record["endpoints"]["D"],
            variable_values=dict(record["variable_values"]),
            steps=tuple(found),
        )

    def _pack_dir(self, scenario_id: str, relative: str) -> Path:
        return self.vendor / "scenarios" / scenario_id / relative

    def _patch(self, pack: dict[str, Any], name: str) -> dict[str, Any]:
        patches = pack["patches"]
        if name not in patches:
            raise BridgeError(f"{pack['record']['scenario_id']} has no patch {name!r}")
        return patches[name]

    # --- one-shot evaluation (the feasibility gate) -----------------------------------------------

    def evaluate_fixed(self, scenario_id: str, patch: str) -> str:
        """One fixed patch under C and A, as the local engine's ``--patch`` does."""
        pack = self.pack(scenario_id)
        entry = self._patch(pack, patch)
        root = self._fresh("evaluate")
        s0 = self._copy(self._pack_dir(scenario_id, pack["s0"]), root / "inputs" / "s0")
        candidate_dir = self._copy(self._pack_dir(scenario_id, entry["dir"]), root / "inputs" / "candidate")
        if pack["kind"] == "canonical":
            steps = [(0, s0), (1, candidate_dir)]
        else:  # the scenario as DAIL's loader gives it: all its steps (C-196 open targets)
            steps = [(0, s0)] + [
                (step["index"], self._pack_dir(scenario_id, step["dir"])) for step in pack["steps"]
            ]
        scenario = self._scenario(pack, steps)
        candidate = core.Candidate(
            source=core.FIXED_PATCH,
            label=f"{scenario_id} {patch}",
            directory=candidate_dir,
            admission={
                "stage": "fixed_patch",
                "admitted": True,
                "content_hash": step_content_hash(candidate_dir),
                "content_hash_matches_pack": step_content_hash(candidate_dir) == entry["content_hash"],
            },
        )
        trace = core.evaluate(
            root=root,
            scenario=scenario,
            s0_dir=s0,
            candidate=candidate,
            config=self.config,
            run_id=f"browser-{self._n}",
            label=DEMO_LABEL,
            versions=self.versions,
            extra={"refused_before_dail": False},
        )
        shutil.rmtree(root, ignore_errors=True)
        return _json(trace)

    # --- the tab's session (L4) -------------------------------------------------------------------

    def _files(self, directory: Path) -> dict[str, str]:
        return {p.name: p.read_text(encoding="utf-8") for p in core.config_files(directory)}

    def start(self, scenario_id: str) -> str:
        """A new session from the scenario's S0 (also the Reset button)."""
        pack = self.pack(scenario_id)
        root = self._fresh("session")
        s0 = self._copy(self._pack_dir(scenario_id, pack["s0"]), root / "s0")
        scenario = self._scenario(pack, [(0, s0)])
        self.session_id = f"tab-{self._n}"
        self.session = core.Session(
            root=root, scenario=scenario, s0_dir=s0, config=self.config, session_id=self.session_id
        )
        self.session.run.on_event = self._notify
        self.scenario_id = scenario_id
        return _json(
            {
                "scenario_id": scenario_id,
                "session_id": self.session_id,
                "files": self._files(s0),
                "ledger": self.session.ledger(),
                "baseline": self.session.baseline,
            }
        )

    def _need_session(self) -> core.Session:
        if self.session is None:
            raise BridgeError("no session: pick a scenario first")
        return self.session

    def _write_edit(self, files: dict[str, str]) -> Path:
        session = self._need_session()
        if not files:
            raise BridgeError("no files were submitted")
        target = session.root / "edits" / str(session.sequence + 1)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for name, text in files.items():
            if not _FILE_NAME.match(name) or name.startswith("."):
                raise BridgeError(f"{name!r} is not a plain .tf file name")
            data = text.encode("utf-8")
            if len(data) > MAX_FILE_BYTES:
                raise BridgeError(f"{name} is larger than {MAX_FILE_BYTES} bytes")
            (target / name).write_bytes(data)
        return target

    def _finish(self, trace: dict[str, Any]) -> str:
        session = self._need_session()
        trace["browser"] = {"terraform_validation": NOT_VALIDATED}
        trace["files"] = self._files(session.parent_dir)
        trace["ledger"] = session.ledger()
        return _json(trace)

    def _refused(self, candidate: core.Candidate, admission: dict[str, Any], diff: str | None,
                 extra: dict[str, Any] | None = None) -> str:
        """The trace of a candidate DAIL's parser or patch validator refused: nothing was evaluated."""
        session = self._need_session()
        return self._finish({
            **core.base_trace(
                label=DEMO_LABEL, versions=self.versions, scenario=session.scenario,
                candidate=candidate, run_id=f"{self.session_id}-refused-{session.sequence + 1}",
            ),
            "diff": diff,
            "admission": admission,
            "conditions": None,
            "refused_before_dail": True,
            "session": {
                "session_id": self.session_id,
                "sequence": session.sequence,
                "promoted": False,
                "trusted_state": session.ledger()[0],
                "ledger": session.ledger(),
            },
            **(extra or {}),
        })

    def submit_reply(self, reply: str, meta_json: str) -> str:
        """An AI reply (PLAN §3.9): DAIL's response parser, DAIL's patch validator, then C and A."""
        session = self._need_session()
        extra = {"ai": {**json.loads(meta_json), "reply": reply}}
        label = f"{self.scenario_id} AI proposal"
        parsed = parse_response(reply)
        if parsed.response is None or parsed.failure_class is not None:
            admission: dict[str, Any] = {
                "stage": "dail_parser", "admitted": False, "errors": list(parsed.errors) or ["the AI proposed no patch"],
                "failure_class": None if parsed.failure_class is None else parsed.failure_class.value,
            }
            candidate = None
        else:
            admission, candidate = session.admit_reply(parsed.response, label)
        admission["terraform_validation"] = NOT_VALIDATED
        if candidate is None:
            # nothing was built: the record names the reply, not a candidate directory
            shown = core.Candidate(source=core.TYPED, label=label, directory=session.parent_dir, admission=admission)
            refused = json.loads(self._refused(shown, admission, None, extra))
            refused["candidate_source"] = core.LLM
            return _json(refused)
        self._notify("ADMITTED")
        trace = session.submit(
            candidate, label=DEMO_LABEL, versions=self.versions, extra={"refused_before_dail": False, **extra}
        )
        return self._finish(trace)

    def submit_files(self, files_json: str) -> str:
        """A typed edit: DAIL's patch validator, then (if admitted) C and A."""
        session = self._need_session()
        edited = self._write_edit(json.loads(files_json))
        label = f"{self.scenario_id} typed in the browser"
        admission = session.admit_typed(edited, terraform_validate=None)
        admission["terraform_validation"] = NOT_VALIDATED
        candidate = core.Candidate(source=core.TYPED, label=label, directory=edited, admission=admission)
        if not admission["admitted"]:
            return self._refused(candidate, admission, core.unified_diff(session.parent_dir, edited))
        self._notify("ADMITTED")
        trace = session.submit(
            candidate, label=DEMO_LABEL, versions=self.versions, extra={"refused_before_dail": False}
        )
        return self._finish(trace)

    def submit_patch(self, name: str) -> str:
        """One of the scenario's own patches as a fixed candidate in the session."""
        session = self._need_session()
        assert self.scenario_id is not None
        pack = self.pack(self.scenario_id)
        entry = self._patch(pack, name)
        target = session.root / "fixed" / str(session.sequence + 1)
        candidate_dir = self._copy(self._pack_dir(self.scenario_id, entry["dir"]), target)
        candidate = core.Candidate(
            source=core.FIXED_PATCH,
            label=f"{self.scenario_id} {name}",
            directory=candidate_dir,
            admission={"stage": "fixed_patch", "admitted": True, "content_hash": step_content_hash(candidate_dir)},
        )
        trace = session.submit(
            candidate, label=DEMO_LABEL, versions=self.versions, step=entry.get("step"),
            extra={"refused_before_dail": False},
        )
        return self._finish(trace)

    def patch_files(self, name: str) -> str:
        """The files of one of the scenario's patches, for the quick-fill buttons."""
        assert self.scenario_id is not None
        pack = self.pack(self.scenario_id)
        return _json(self._files(self._pack_dir(self.scenario_id, self._patch(pack, name)["dir"])))

    def verify_chain(self) -> str:
        return _json(self._need_session().verify_chain())

"""Training-data contract and loader for the qualified F3 ref0081818 recipe.

This module is deliberately separate from the historical ``f3_training_data``
path.  A ref0081818 contract is accepted only when the revision gate, the
revision-bound development entry point, and every actual development source
are present and hash-bound.  A prepared input or the old ``.010`` domain gate
can never be relabelled as training data.

The public functions mirror the old training-data boundary so the training
worker can dispatch by the immutable ``recipe_id`` without duplicating the
loader implementation.  This module never launches CFD or training.
"""

from __future__ import annotations

from collections import OrderedDict
import copy
import json
import math
from pathlib import Path

import numpy as np

from scripts import f3_ref0081818_development as development
from scripts import f3_training_data as legacy
from scripts.f3_control import AccelerationControl
from scripts.f3_nopen_stage_score import CachedSource, TIME_ALIGNMENT, target_grid
from scripts.f3_timestep_evidence import evidence as timestep_evidence
from scripts.l1r_continuation_evidence import LAB, OUT
from scripts.l1r_q2_mdbc_bridge import atomic_json, sha256, utc_now


SCHEMA = "f3.training.development_data.v1"
CONTRACTS = {"pilot": "F3-REF0081818-TRAINING-DEVELOPMENT-PILOT.json",
             "full": "F3-REF0081818-TRAINING-DEVELOPMENT-FULL.json"}
INTERVAL = 0.01
HORIZON = 8.35
RECIPE = development.REVISION_RECIPE
DOMAIN_GATE = development.REVISION_GATE
PROGRAMS = (
    "f3_ref0081818_training_data.py",
    "f3_ref0081818_development.py",
    "f3_ref0081818_score.py",
    "f3_training_core.py",
    "f3_control.py",
    "f3_nopen_stage_score.py",
    "f3_reference_score.py",
    "f3_timestep_evidence.py",
)


def _read(path):
    return json.loads(Path(path).read_text())


def _relative(path):
    return str(Path(path).resolve().relative_to(LAB.resolve()))


def _path(relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("ref0081818 evidence paths must be LAB-relative")
    result = (LAB / relative).resolve()
    result.relative_to(LAB.resolve())
    return result


def _contract_path(path):
    result = Path(path)
    if not result.is_absolute():
        result = LAB / result
    result = result.resolve()
    result.relative_to(LAB.resolve())
    return result


def _bind(bindings, path, expected=None):
    path = Path(path)
    digest = sha256(path)
    if expected is not None and digest != expected:
        raise ValueError("changed ref0081818 source evidence: " + _relative(path))
    relative = _relative(path)
    if relative in bindings and bindings[relative] != digest:
        raise ValueError("ref0081818 source changed during verification: " + relative)
    bindings[relative] = digest
    return {"path": relative, "sha256": digest}


def _bind_json(bindings, path, value):
    item = _bind(bindings, path)
    if _read(path) != value:
        raise ValueError("ref0081818 source JSON changed during contract construction")
    return item


def _verify_bindings(bindings):
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError("ref0081818 training contract requires bound evidence")
    for relative, digest in bindings.items():
        if not isinstance(digest, str) or sha256(_path(relative)) != digest:
            raise ValueError("ref0081818 contract source evidence changed: " + relative)


def _require_training_gate():
    """Require the revision gate's explicit post-development training opt-in."""
    gate = development.verify_revision_gate()
    if gate.get("development_launch_allowed") is not True:
        raise ValueError("ref0081818 development launch is not enabled by the revision gate")
    if gate.get("training_launch_allowed") is not True:
        raise ValueError("ref0081818 training launch is not enabled by the revision gate")
    return gate


def _selected(scope, context):
    if scope not in CONTRACTS:
        raise ValueError("ref0081818 contract scope must be pilot or full")
    rows = context["manifest"]["cases"]
    selected = rows if scope == "full" else [row for row in rows if row["pilot"]]
    expected = 32 if scope == "full" else 8
    if len(selected) != expected or len({row["case_id"] for row in selected}) != expected:
        raise ValueError("all registered ref0081818 development cases are required")
    return selected


def _verify_preflight(row, record, context):
    name = row["case_id"]
    preflight_path = OUT / f"{name}-INPUT-PREFLIGHT.json"
    preflight = _read(preflight_path)
    prefix = _path(record["generated_prefix"])
    control_path = prefix.parent / "CaseSloshingAccData.csv"
    parser = preflight.get("native_reader", {})
    if (preflight.get("status") != "passed"
            or preflight.get("record_id") != name
            or preflight.get("recipe_id") != RECIPE
            or preflight.get("revision_manifest_sha256") != sha256(OUT / development.DEVELOPMENT_MANIFEST)
            or preflight.get("record_sha256") != sha256(OUT / f"{name}-PREPARED.json")
            or _path(preflight["asset"]["path"]) != control_path
            or preflight["asset"]["sha256"] != row["control_file_sha256"]
            or preflight["asset"]["sha256"] != record["drive_sha256"]
            or parser.get("first_time_s") != 0
            or parser.get("last_time_s") != HORIZON):
        raise ValueError("ref0081818 development input preflight is not fully bound")
    return preflight, control_path


def _source(row, context, bindings):
    name = row["case_id"]
    record, audit, solver = development._verified_development(name, context)
    sources = {}
    for suffix, value in (("PREPARED", record), ("AUDIT", audit), ("SOLVER", solver)):
        sources[suffix.lower()] = _bind_json(bindings, OUT / f"{name}-{suffix}.json", value)
    preflight, control_path = _verify_preflight(row, record, context)
    sources["input_preflight"] = _bind_json(bindings, OUT / f"{name}-INPUT-PREFLIGHT.json", preflight)
    sources["control"] = _bind(bindings, control_path, record["drive_sha256"])
    sources["registered_control"] = _bind(bindings, _path(row["control_path"]), row["control_file_sha256"])
    nominal = context["nominal"]
    # The historical candidate manifest binds the vendor bytes by digest but
    # predates an explicit source path field.  The revision development entry
    # point names the immutable vendor source; never infer it from a prepared
    # candidate directory.
    source_drive = development.VENDOR_DRIVE
    if (preflight.get("source", {}).get("sha256") != context["manifest"]["source_drive_sha256"]
            or preflight.get("native_reader", {}).get("rows") != len(nominal)):
        raise ValueError("ref0081818 development source forcing is not the registered nominal control")
    _bind(bindings, source_drive, context["manifest"]["source_drive_sha256"])
    prefix = _path(record["generated_prefix"])
    for filename, digest in record["input_assets"].items():
        _bind(bindings, prefix.parent / filename, digest)
    sources["native_log"] = _bind(bindings, Path(solver["attempt_directory"]) / "Run.out")
    native = timestep_evidence(name)
    if (native.get("case") != name or native.get("total_steps", 0) <= 0
            or not all(math.isfinite(native[key]) and native[key] > 0
                       for key in ("dt_min_s", "dt_max_s"))
            or native["dt_min_s"] > native["dt_max_s"]):
        raise ValueError("actual ref0081818 native timestep evidence is required")
    sources["native_timestep"] = _bind(bindings, _path(native["csv_path"]), native["csv_sha256"])
    sources["hdf5"] = {"path": _relative(_path(audit["hdf5"])), "sha256": audit["hdf5_sha256"]}
    bindings[sources["hdf5"]["path"]] = audit["hdf5_sha256"]
    summary = copy.deepcopy(row)
    summary.update(hard_audit_passed=True, sources=sources, native_timestep=native,
                   native_frames=audit["frames"], particle_axis_count=audit["particle_axis_count"],
                   initial_fluid_mass_kg=audit["initial_fluid_mass_kg"], native_time_end_s=audit["time_end_s"])
    source = dict(case_id=name, record=record, audit=audit, solver=solver,
                  native_timestep=native, hdf5_path=_path(audit["hdf5"]),
                  entry={"output_interval_s": INTERVAL}, control_path=control_path)
    with _Reference(source):
        pass
    return summary, source


def _gate_bindings(gate, bindings):
    gate_ref = _bind_json(bindings, OUT / DOMAIN_GATE, gate)
    score_path = _path(gate["scoring_evidence_path"])
    score = _read(score_path)
    score_ref = _bind_json(bindings, score_path, score)
    if gate.get("scoring_evidence_sha256") != sha256(score_path):
        raise ValueError("ref0081818 scoring report hash changed")
    for relative, digest in score.get("evidence_sha256", {}).items():
        _bind(bindings, _path(relative), digest)
    return gate_ref, score_ref


def _collect(scope):
    gate = _require_training_gate()
    context = development._context(register=False)
    rows = _selected(scope, context)
    bindings = {}
    gate_ref, score_ref = _gate_bindings(gate, bindings)
    registry_ref = _bind_json(bindings, OUT / development.REGISTRY, context["registry"])
    manifest_ref = _bind_json(bindings, OUT / development.DEVELOPMENT_MANIFEST, context["manifest"])
    for item in context["registry"].get("evidence", []):
        _bind(bindings, _path(item["path"]), item["sha256"])
    for name in PROGRAMS:
        _bind(bindings, LAB / "scripts" / name)
    cases, sources = [], {}
    for row in rows:
        summary, source = _source(row, context, bindings)
        cases.append(summary)
        sources[row["case_id"]] = source
    result = dict(
        schema=SCHEMA, scope=scope, status="passed", recipe_id=RECIPE,
        qualified_sources=True, completed_case_ids=[case["case_id"] for case in cases],
        source_domain_gate=gate_ref, qualification_score=score_ref,
        development_registry=registry_ref, candidate_manifest=manifest_ref,
        cases=cases, production_resolution_m=gate["production_resolution_m"],
        time_window_s=gate["time_window_s"], scoring_interval_s=gate["scoring_interval_s"],
        canonical_frame_count=len(target_grid(INTERVAL)), time_alignment=TIME_ALIGNMENT,
        velocity_convention="Native initial velocity; thereafter previous canonical position difference divided by 0.01 s",
        target_convention="Next canonical position minus current canonical position; supervision only",
        split_semantics="Registered ref0081818 development roles: train optimization, validation interpolation, test public development extrapolation",
        identity_convention="Full immutable native particle IDs and per-ID masses; no survivor filtering",
        model_qualified=False, material_layers_qualified=[], formal_release=False,
        evidence_sha256=dict(sorted(bindings.items())),
    )
    return result, sources


def publish_development_contract(scope="pilot", *, path=None):
    """Publish only a fully completed ref0081818 actual-source contract."""
    if scope not in CONTRACTS:
        raise ValueError("ref0081818 contract scope must be pilot or full")
    target = _contract_path(path if path is not None else OUT / CONTRACTS[scope])
    if target.exists():
        existing = validate_development_contract(target)
        if existing["scope"] != scope:
            raise ValueError("existing ref0081818 contract has another scope")
        return existing
    value, _ = _collect(scope)
    _verify_bindings(value["evidence_sha256"])
    value["recorded_at_utc"] = utc_now()
    if target.exists():
        raise ValueError("ref0081818 contract appeared during verification; refusing replacement")
    atomic_json(target, value)
    return value


def _validated(path):
    path = _contract_path(path)
    raw = _read(path)
    if (not isinstance(raw, dict) or raw.get("schema") != SCHEMA
            or raw.get("scope") not in CONTRACTS or raw.get("status") != "passed"
            or raw.get("qualified_sources") is not True
            or raw.get("recipe_id") != RECIPE
            or not isinstance(raw.get("recorded_at_utc"), str)
            or not raw["recorded_at_utc"]):
        raise ValueError("a completed ref0081818 actual-source training contract is required")
    expected, sources = _collect(raw["scope"])
    saved = {key: value for key, value in raw.items() if key != "recorded_at_utc"}
    if saved != expected:
        raise ValueError("ref0081818 training contract differs from current actual runs or gate")
    if _read(path) != raw:
        raise ValueError("ref0081818 training contract changed during verification")
    return raw, sources


def validate_development_contract(path):
    return _validated(path)[0]


class _Reference(legacy._Reference):
    """The same bounded complete-axis native cache under the new contract."""

    pass


class QualifiedF3Loader(legacy.QualifiedF3Loader):
    """Loader whose contract and sources are exclusively ref0081818-bound."""

    def __init__(self, contract_path=None):
        path = OUT / CONTRACTS["full"] if contract_path is None else contract_path
        self.contract_path = _contract_path(path)
        self.contract, self._sources = _validated(self.contract_path)
        self.contract_sha256 = sha256(self.contract_path)
        self._rows = {row["case_id"]: row for row in self.contract["cases"]}
        self._tokens = {path: legacy._token(path) for source in self._sources.values()
                        for path in (source["hdf5_path"], source["control_path"])}
        self._reference = None
        self._reference_case = None
        self._control = None
        self._closed = False
        self.times = target_grid(INTERVAL)
        self.times.setflags(write=False)

    def _open(self, case_id):
        source = self._sources[case_id]
        for path in (source["hdf5_path"], source["control_path"]):
            if legacy._token(path) != self._tokens[path]:
                raise ValueError("verified ref0081818 source changed after loader opened")
        if case_id != self._reference_case:
            self._clear_reference()
            reference = _Reference(source)
            try:
                control = AccelerationControl.from_csv(source["control_path"])
                control.values.setflags(write=False)
                control.integrated.setflags(write=False)
            except BaseException:
                reference.close()
                raise
            self._reference, self._control = reference, control
            self._reference_case = case_id
        return self._reference


def loader_for_contract(contract_path):
    """Dispatch by immutable recipe identity; never silently fall back."""
    path = _contract_path(contract_path)
    raw = _read(path)
    recipe = raw.get("recipe_id")
    if recipe == RECIPE:
        return QualifiedF3Loader(path)
    if recipe == legacy.development.RECIPE:
        return legacy.QualifiedF3Loader(path)
    raise ValueError("training contract recipe is not registered")

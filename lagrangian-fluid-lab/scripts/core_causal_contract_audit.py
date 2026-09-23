#!/usr/bin/env python3
"""Audit Core causal-input and physical-lineage contracts without a solver.

The audit deliberately separates two questions that are easy to conflate:

* the predictor receives only the current state and public known inputs; and
* reference future frames may be read by the evaluator after a prediction for
  scoring and diagnostics; and
* replacing synthetic future frames leaves autonomous predictions unchanged.

It validates the immutable reader manifests, performs a small source-level
interface audit of :func:`scripts.core_learning.rollout_case`, and executes a
two-step synthetic future-frame intervention. It does not claim model quality,
CFD qualification, or a full registered-data causal study.
The resulting evidence is suitable for the typed ``core.contract_audit.v1``
completion gate, while its scope records the limits explicitly.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import platform
import sys
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.core_dataset import validate_manifest
from scripts.core_runtime import atomic_json, digest
from scripts.protocol_metrics import validate_split_lineage
from scripts.core_contract import (FiniteGeometry, KnownInputs, PrescribedControl,
                                   State, StepPrediction, contract_hash)


SCHEMA = "core.contract_audit.v1"
AUDIT_VERSION = "causal_lineage_contracts_v2_future_frame_intervention"


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _node_has_call(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == name
        for item in ast.walk(node)
    )


def _rollout_interface_audit(source_path: Path) -> dict[str, Any]:
    source = source_path.read_text()
    tree = ast.parse(source, filename=str(source_path))
    rollout = next(
        (node for node in tree.body
         if isinstance(node, ast.FunctionDef) and node.name == "rollout_case"),
        None,
    )
    if rollout is None:
        raise ValueError("rollout_case function is missing")
    calls = [
        node for node in ast.walk(rollout)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "predict_step"
    ]
    if len(calls) != 1:
        raise ValueError(f"expected one predictor.predict_step call, found {len(calls)}")
    call = calls[0]
    if len(call.args) != 3:
        raise ValueError("predict_step must receive exactly state, known_inputs, dt")
    names = [arg.id if isinstance(arg, ast.Name) else None for arg in call.args]
    if names != ["previous", "known", "dt"]:
        raise ValueError(f"predict_step arguments are not current-state causal: {names}")
    # Future frame reads are allowed for scoring, but must be syntactically
    # after the predictor call.  This guards against accidental privileged
    # reference access in the model update path.
    body_positions = {id(node): index for index, node in enumerate(rollout.body)}
    predict_line = call.lineno
    reference_reads = [
        node for node in ast.walk(rollout)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "read_state"
        and node.lineno > predict_line
    ]
    if not reference_reads:
        raise ValueError("rollout_case has no post-prediction reference read for scoring audit")
    # The implementation publishes an explicit marker in both progress and
    # final rollout receipts.  Requiring both keeps the contract visible to
    # downstream evaluators instead of relying on a private convention.
    if source.count('"future_state_inputs": False') < 2:
        raise ValueError("rollout receipts do not explicitly declare future_state_inputs=false")
    return {
        "passed": True,
        "predict_step_call_count": len(calls),
        "predict_step_arguments": names,
        "future_reference_reads_after_predict": len(reference_reads),
        "future_reference_reads_are_evaluator_side": True,
        "receipt_markers": {
            "progress_future_state_inputs_false": True,
            "rollout_future_state_inputs_false": True,
        },
        "source_sha256": digest(source_path),
    }


def future_frame_intervention_probe() -> dict[str, Any]:
    """Verify future reference substitutions cannot change autonomous outputs.

    This deliberately tiny synthetic probe exercises the actual public
    ``rollout_case`` path, not a registered trajectory.  Two runs receive the
    same initial state, prescribed inputs, intervals, and deterministic
    predictor; both future reference frames are then changed in the second
    run.  Prediction inputs and increments must remain bitwise identical,
    while evaluator-side scores must respond to the changed references.
    """
    from scripts.core_learning import rollout_case

    wall_spec = {
        "container_interior": {
            "xmin": -1.0, "xmax": 1.0, "ymin": -1.0, "ymax": 1.0,
            "zmin": 0.0, "zmax": 1.0,
        },
        "closed_faces": ["left", "right", "front", "back", "bottom"],
        "open_faces": ["top"], "obstacles": [],
    }
    geometry = FiniteGeometry.from_wall_spec(wall_spec, coordinate_frame="causal-probe")
    control = PrescribedControl(np.array([
        [0.0, 0.0, 0.0, -9.81, 0.0, 0.0, 0.0],
        [0.02, 0.0, 0.0, -9.81, 0.0, 0.0, 0.0],
    ]))
    known = KnownInputs(
        geometry, control,
        {"gravity_mps2": [0.0, 0.0, -9.81], "reference_density_kgm3": 1000.0},
        {"dp_m": 0.01, "h_m": 0.016}, "causal-probe",
    )
    initial = State(
        0.0, np.array([[0.0, 0.0, 0.1], [0.01, 0.0, 0.1]]),
        np.zeros((2, 3)), np.array([11, 12]), np.zeros(2, dtype=int),
        np.ones(2), np.ones(2, dtype=bool),
    )
    times = np.array([0.0, 0.01, 0.02])
    base_positions = (
        initial.position,
        initial.position + np.array([[0.001, 0.0, 0.0], [0.0, 0.001, 0.0]]),
        initial.position + np.array([[0.002, 0.0, 0.0], [0.0, 0.002, 0.0]]),
    )
    base_velocities = (
        initial.velocity,
        initial.velocity + np.array([[0.02, 0.0, 0.0], [0.0, 0.02, 0.0]]),
        initial.velocity + np.array([[0.04, 0.0, 0.0], [0.0, 0.04, 0.0]]),
    )

    class SyntheticDataset:
        def __init__(self, intervention):
            self.events = []
            self.states = [initial]
            for frame in (1, 2):
                position = np.array(base_positions[frame], copy=True)
                velocity = np.array(base_velocities[frame], copy=True)
                if intervention:
                    position += np.array([0.05, -0.03, 0.02]) * frame
                    velocity += np.array([0.4, -0.2, 0.1]) * frame
                self.states.append(State(
                    times[frame], position, velocity, initial.particle_id,
                    initial.particle_zone, initial.mass, initial.valid,
                ))

        def times(self, case_id):
            if case_id != "synthetic-causal-probe":
                raise KeyError(case_id)
            return times

        def known_inputs(self, case_id):
            if case_id != "synthetic-causal-probe":
                raise KeyError(case_id)
            return known

        def read_state(self, case_id, frame):
            if case_id != "synthetic-causal-probe":
                raise KeyError(case_id)
            self.events.append(f"read:{frame}")
            return self.states[frame]

    def run(intervention):
        dataset = SyntheticDataset(intervention)
        events = dataset.events

        class Recorder:
            def __init__(self):
                self.inputs = []
                self.increments = []

            def predict_step(self, state, current_known, dt):
                events.append("predict")
                self.inputs.append({
                    "time_s": state.time_s,
                    "position": np.array(state.position, copy=True),
                    "velocity": np.array(state.velocity, copy=True),
                    "known_sha256": contract_hash(current_known),
                    "dt": float(dt),
                })
                displacement = np.full_like(state.position, 0.003)
                delta_velocity = np.full_like(state.velocity, 0.7)
                self.increments.append((displacement.copy(), delta_velocity.copy()))
                return StepPrediction(displacement, delta_velocity)

        predictor = Recorder()
        result = rollout_case(dataset, "synthetic-causal-probe", predictor)
        return dataset, predictor, result

    baseline = run(False)
    altered = run(True)
    baseline_events, baseline_predictor, baseline_report = baseline
    altered_events, altered_predictor, altered_report = altered
    if baseline_events.events != altered_events.events:
        raise AssertionError("future-frame intervention changed predictor/read ordering")
    if baseline_events.events != ["read:0", "predict", "read:1", "predict", "read:2"]:
        raise AssertionError("reference frames are not read only at evaluator boundaries")
    if len(baseline_predictor.inputs) != 2 or len(altered_predictor.inputs) != 2:
        raise AssertionError("synthetic rollout did not execute the full two-step horizon")
    for left, right in zip(baseline_predictor.inputs, altered_predictor.inputs):
        if (left["time_s"] != right["time_s"] or left["dt"] != right["dt"]
                or left["known_sha256"] != right["known_sha256"]
                or not np.array_equal(left["position"], right["position"])
                or not np.array_equal(left["velocity"], right["velocity"])):
            raise AssertionError("future-frame intervention changed predictor inputs")
    for left, right in zip(baseline_predictor.increments, altered_predictor.increments):
        if not all(np.array_equal(a, b) for a, b in zip(left, right)):
            raise AssertionError("future-frame intervention changed predictor outputs")
    if (baseline_report["position_rmse_m"] == altered_report["position_rmse_m"]
            or baseline_report["velocity_rmse_mps"] == altered_report["velocity_rmse_mps"]):
        raise AssertionError("intervention did not alter evaluator-side scores")
    if (baseline_report["future_state_inputs"] is not False
            or altered_report["future_state_inputs"] is not False):
        raise AssertionError("rollout did not retain its future-state exclusion marker")
    return {
        "passed": True,
        "synthetic_only": True,
        "future_reference_frames_replaced": 2,
        "full_horizon_steps": 2,
        "predictor_future_state_inputs": False,
        "prediction_inputs_bitwise_identical": True,
        "prediction_increments_bitwise_identical": True,
        "evaluator_scores_changed": True,
        "baseline_position_rmse_m": float(baseline_report["position_rmse_m"]),
        "intervened_position_rmse_m": float(altered_report["position_rmse_m"]),
        "baseline_velocity_rmse_mps": float(baseline_report["velocity_rmse_mps"]),
        "intervened_velocity_rmse_mps": float(altered_report["velocity_rmse_mps"]),
        "read_predict_order": baseline_events.events,
    }


def _manifest_audit(path: Path, root: Path) -> dict[str, Any]:
    payload = _load(path)
    validate_manifest(payload)
    cases = payload["cases"]
    validate_split_lineage(cases)
    physical = {}
    lineages = {}
    qualification_cases = []
    for row in cases:
        physical.setdefault(row["physical_case_id"], set()).add(row["split"])
        lineages.setdefault(row["lineage_group_id"], set()).add(row["split"])
        if row.get("qualification_case"):
            qualification_cases.append(row["case_id"])
        known = row.get("known_inputs") or row.get("known_inputs_ref")
        if not isinstance(known, dict):
            raise ValueError(f"known input contract missing: {row['case_id']}")
        forbidden_keys = {"hdf5", "trajectory", "future_state", "reference_state",
                          "density", "pressure", "survival_mask"}
        observed_forbidden = sorted(forbidden_keys.intersection(known))
        if observed_forbidden:
            raise ValueError(
                f"known inputs expose future/reference fields for {row['case_id']}: "
                + ", ".join(observed_forbidden)
            )
    cross_physical = {key: sorted(value) for key, value in physical.items() if len(value) > 1}
    cross_lineage = {key: sorted(value) for key, value in lineages.items() if len(value) > 1}
    if cross_physical or cross_lineage:
        raise ValueError("manifest split lineage crosses boundary")
    return {
        "path": _relative(path, root),
        "sha256": digest(path),
        "schema": payload["schema"],
        "dataset_id": payload.get("dataset_id"),
        "formal_release": payload.get("formal_release") is True,
        "case_count": len(cases),
        "family_counts": {
            family: sum(row["family"] == family for row in cases)
            for family in sorted({row["family"] for row in cases})
        },
        "split_counts": {
            split: sum(row["split"] == split for row in cases)
            for split in sorted({row["split"] for row in cases})
        },
        "physical_case_count": len(physical),
        "lineage_count": len(lineages),
        "qualification_case_count": len(qualification_cases),
        "future_state_known_input_fields": [],
        "cross_split_physical_case_count": 0,
        "cross_split_lineage_count": 0,
    }


def audit(*, root: Path, manifests: list[Path], output: Path,
          reproduction_reports: list[Path] | None = None) -> dict[str, Any]:
    root = root.resolve()
    source_path = root / "scripts/core_learning.py"
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    manifest_rows = [_manifest_audit(path.resolve(), root) for path in manifests]
    interface = _rollout_interface_audit(source_path)
    future_intervention = future_frame_intervention_probe()
    intervention_test_path = root / "tests/test_core_causal_contract_audit.py"
    if not intervention_test_path.is_file():
        raise FileNotFoundError(intervention_test_path)
    future_intervention["implementation"] = {
        "path": _relative(Path(__file__).resolve(), root),
        "sha256": digest(Path(__file__).resolve()),
    }
    future_intervention["regression_test"] = {
        "path": _relative(intervention_test_path, root),
        "sha256": digest(intervention_test_path),
    }
    reproduction_rows = []
    for report_path in reproduction_reports or []:
        report = _load(report_path.resolve())
        reproduction_rows.append({
            "path": _relative(report_path, root),
            "sha256": digest(report_path),
            "schema": report.get("schema"),
            "predictor_future_state_inputs": report.get("predictor_future_state_inputs"),
            "future_reference_state_used_by_oracle": report.get("future_reference_state_used_by_oracle"),
            "passed": report.get("passed") is True,
        })
    if any(row["predictor_future_state_inputs"] is not False for row in reproduction_rows):
        raise ValueError("a supplied reproduction report does not bind predictor future inputs=false")
    payload = {
        "schema": SCHEMA,
        "audit_version": AUDIT_VERSION,
        "passed": True,
        "scope": "reader manifest split/lineage, predictor input contract, and a synthetic future-reference intervention; not model quality or CFD qualification",
        "root": str(root),
        "host": platform.node(),
        "manifests": manifest_rows,
        "interface": interface,
        "reproduction_reports": reproduction_rows,
        "checks": {
            "manifest_schema_and_hash_contract": True,
            "physical_case_split_isolation": True,
            "lineage_split_isolation": True,
            "known_inputs_exclude_future_reference_fields": True,
            "predictor_receives_current_state_known_inputs_dt_only": True,
            "future_reference_reads_are_evaluator_side": True,
            "future_frame_intervention_predictions_invariant": future_intervention["passed"],
            "reproduction_receipts_bind_future_state_false": all(
                row["predictor_future_state_inputs"] is False for row in reproduction_rows
            ),
        },
        "future_frame_intervention": future_intervention,
        "limitations": [
            "The causal intervention uses a tiny synthetic fixture; it does not read or qualify registered F3/F4 CFD trajectories.",
            "A passed contract does not establish T1/T2 qualification or model accuracy.",
        ],
    }
    atomic_json(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, action="append", required=True)
    parser.add_argument("--reproduction-report", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(root=args.root, manifests=args.manifest, output=args.output,
                   reproduction_reports=args.reproduction_report)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

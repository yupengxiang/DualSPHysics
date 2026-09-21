#!/usr/bin/env python3
"""Run a tiny CPU-only full-field/halo and updater-oracle interface witness.

The witness exercises the public Core contracts without an optimizer or a
trajectory reader.  An untrained, deterministic graph model is evaluated once
with all centers and again in small center chunks; the model still receives
the complete field and the exact two-hop halo for each chunk.  Separately, a
privileged following state supplies independent displacement and native
delta-velocity increments to the public ``commit``/``updater_oracle`` path.

The following state is never passed to the model predictor.  A nested
future-state key is also submitted to ``KnownInputs`` and must be rejected.
The resulting JSON is a diagnostic receipt only and cannot count as a formal
run, a qualification, or a training result.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import numpy as np
import torch

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_contract import (
    FiniteGeometry,
    KnownInputs,
    PrescribedControl,
    State,
    StepPrediction,
    commit,
    contract_hash,
    updater_oracle,
)
from scripts.core_learning import ModelPredictor as LearningModelPredictor
from scripts.core_models import (
    DualIncrementModel,
    ModelPredictor,
    neighbor_table,
    two_hop_halo,
)


SCHEMA = "core.fullfield_halo_oracle_diagnostic.v1"
DT_S = 0.1
H_M = 0.016
CHUNK_SIZE = 2
SEED = 17


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_path(value: str | Path, root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _reference(path: Path, root: Path) -> dict[str, Any]:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = str(path.resolve())
    return {"path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size}


def _state() -> State:
    # The line spacing is below 2h, so the graph has a nontrivial two-hop
    # source set even when center chunks contain only two particles.
    positions = np.asarray([
        [0.000, 0.000, 0.100], [0.010, 0.000, 0.100],
        [0.020, 0.004, 0.100], [0.030, -0.003, 0.100],
        [0.040, 0.002, 0.100], [0.050, -0.004, 0.100],
        [0.060, 0.001, 0.100], [0.070, 0.000, 0.100],
    ], dtype=np.float64)
    velocity = np.asarray([
        [0.10, 0.00, 0.00], [0.11, 0.01, 0.00],
        [0.12, 0.00, 0.01], [0.13, -0.01, 0.00],
        [0.14, 0.02, 0.00], [0.15, -0.02, 0.01],
        [0.16, 0.01, -0.01], [0.17, 0.00, 0.00],
    ], dtype=np.float64)
    return State(
        0.0, positions, velocity,
        np.arange(100, 108, dtype=np.int64),
        np.zeros(8, dtype=np.int64),
        np.ones(8, dtype=np.float64),
        np.ones(8, dtype=bool),
    )


def _known_inputs() -> KnownInputs:
    spec = {
        "container_interior": {
            "xmin": -1.0, "xmax": 1.0,
            "ymin": -1.0, "ymax": 1.0,
            "zmin": 0.0, "zmax": 1.0,
        },
        "closed_faces": ["left", "right", "front", "back", "bottom"],
        "open_faces": ["top"],
        "obstacles": [],
    }
    return KnownInputs(
        FiniteGeometry.from_wall_spec(spec, coordinate_frame="cpu-fixture"),
        PrescribedControl(np.asarray([
            [0.0, 0.0, 0.0, -9.81, 0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0, -9.81, 0.0, 0.0, 0.0],
        ], dtype=np.float64)),
        {"reference_density_kgm3": 1000.0},
        {"dp_m": 0.01, "h_m": H_M},
        "cpu-fixture",
    )


def _independent_oracle(state: State) -> tuple[State, StepPrediction]:
    index = np.arange(state.count, dtype=np.float64)
    displacement = np.column_stack((
        0.0008 + 0.0001 * index,
        0.0002 * (-1.0) ** index,
        -0.0001 * index,
    ))
    # This is deliberately independent of displacement / dt.  It represents
    # saved native velocity increments, not a finite difference of position.
    delta_velocity = np.column_stack((
        0.025 + 0.004 * index,
        -0.010 + 0.002 * index,
        0.006 + 0.001 * index,
    ))
    prediction = StepPrediction(
        displacement, delta_velocity,
        {"oracle": "privileged_fixture", "native_velocity_semantics": True},
    )
    following = State(
        state.time_s + DT_S,
        state.position + displacement,
        state.velocity + delta_velocity,
        state.particle_id, state.particle_zone, state.mass, state.valid,
    )
    return following, prediction


def _causal_rejection(known: KnownInputs) -> dict[str, Any]:
    try:
        KnownInputs(
            known.geometry, known.control,
            {"nested": {"future_state": [[1.0, 2.0, 3.0]]}},
            known.numerics, known.coordinate_frame,
        )
    except ValueError as error:
        return {
            "rejected": True,
            "error_type": type(error).__name__,
            "error": str(error),
            "future_state_passed_to_predictor": False,
        }
    return {
        "rejected": False,
        "error_type": None,
        "error": None,
        "future_state_passed_to_predictor": False,
    }


def _interface_signatures() -> dict[str, str]:
    return {
        "core_learning.ModelPredictor.predict_step": str(
            inspect.signature(LearningModelPredictor.predict_step)
        ),
        "core_models.ModelPredictor.predict_step": str(
            inspect.signature(ModelPredictor.predict_step)
        ),
        "core_models.DualIncrementModel.forward": str(
            inspect.signature(DualIncrementModel.forward)
        ),
        "core_contract.commit": str(inspect.signature(commit)),
        "core_contract.updater_oracle": str(inspect.signature(updater_oracle)),
        "core_models.two_hop_halo": str(inspect.signature(two_hop_halo)),
    }


def run_diagnostic(*, data_root: str | Path) -> dict[str, Any]:
    root = Path(data_root).expanduser().resolve()
    state = _state()
    known = _known_inputs()
    neighbors, neighbor_diagnostics = neighbor_table(state, H_M, limit=64)
    centers = np.arange(state.count, dtype=np.int64)
    chunks = [centers[start:start + CHUNK_SIZE]
              for start in range(0, state.count, CHUNK_SIZE)]
    halo_rows = []
    for chunk in chunks:
        one_hop, two_hop = two_hop_halo(chunk, neighbors, n=state.count)
        halo_rows.append({
            "centers": chunk.tolist(),
            "one_hop_indices": one_hop.tolist(),
            "two_hop_indices": two_hop.tolist(),
            "two_hop_count": int(len(two_hop)),
            "all_indices_in_field": bool(np.all((two_hop >= 0) & (two_hop < state.count))),
        })

    # This is inference only: no optimizer, backward pass, checkpoint, or GPU
    # is involved. Both calls use the same deterministic untrained parameters.
    torch.manual_seed(SEED)
    model = DualIncrementModel("graph_raw", hidden=8)
    full_predictor = ModelPredictor(model, device="cpu", chunk_size=state.count)
    chunk_predictor = ModelPredictor(model, device="cpu", chunk_size=CHUNK_SIZE)
    full_prediction = full_predictor.predict_step(state, known, DT_S)
    chunk_prediction = chunk_predictor.predict_step(state, known, DT_S)
    full_output = np.column_stack((full_prediction.displacement, full_prediction.delta_velocity))
    chunk_output = np.column_stack((chunk_prediction.displacement, chunk_prediction.delta_velocity))
    model_max_abs_error = float(np.max(np.abs(full_output - chunk_output)))
    full_committed = commit(state, full_prediction, DT_S)
    chunk_committed = commit(state, chunk_prediction, DT_S)
    commit_max_position_error = float(np.max(np.abs(full_committed.position - chunk_committed.position)))
    commit_max_velocity_error = float(np.max(np.abs(full_committed.velocity - chunk_committed.velocity)))

    following, oracle_prediction = _independent_oracle(state)
    oracle_committed = commit(state, oracle_prediction, DT_S)
    oracle_update = updater_oracle(state, following)
    dx_over_dt = oracle_prediction.displacement / DT_S
    independent_velocity_semantics = bool(
        not np.allclose(dx_over_dt, oracle_prediction.delta_velocity, rtol=0.0, atol=1e-12)
    )
    oracle_commit_position_error = float(np.max(np.abs(oracle_committed.position - following.position)))
    oracle_commit_velocity_error = float(np.max(np.abs(oracle_committed.velocity - following.velocity)))
    causal = _causal_rejection(known)
    source_paths = [
        root / "scripts/core_fullfield_halo_oracle.py",
        root / "scripts/core_learning.py",
        root / "scripts/core_models.py",
        root / "scripts/core_contract.py",
    ]
    source_bindings = [_reference(path, root) for path in source_paths]
    checks = {
        "full_particle_axis_preserved": neighbor_diagnostics["field_particle_count"] == state.count,
        "halo_indices_in_full_field": all(row["all_indices_in_field"] for row in halo_rows),
        "all_centers_covered_once": np.array_equal(
            np.sort(np.concatenate([row["centers"] for row in halo_rows])), centers
        ),
        "full_vs_chunk_prediction_equivalent": bool(np.allclose(
            full_output, chunk_output, rtol=1e-6, atol=1e-7
        )),
        "full_vs_chunk_commit_equivalent": bool(
            commit_max_position_error <= 1e-7 and commit_max_velocity_error <= 1e-7
        ),
        "oracle_dx_dv_independent": independent_velocity_semantics,
        "oracle_predict_commit_position_exact": oracle_commit_position_error <= 1e-12,
        "oracle_predict_commit_velocity_exact": oracle_commit_velocity_error <= 1e-12,
        "updater_oracle_position_exact": oracle_update["position_max_abs_error"] <= 1e-12,
        "updater_oracle_velocity_exact": oracle_update["native_velocity_max_abs_error"] <= 1e-12,
        "future_state_rejected": causal["rejected"],
    }
    return {
        "schema": SCHEMA,
        "record_id": "core-fullfield-halo-oracle-diagnostic-20260921",
        "status": "diagnostic_passed" if all(checks.values()) else "diagnostic_failed",
        "proposal_only": True,
        "diagnostic_only": True,
        "training_excluded": True,
        "qualification_excluded": True,
        "formal_release": False,
        "formal_training": False,
        "formal_job_count": 0,
        "formal_runs_counted": 0,
        "data_root": str(root),
        "protocol": {
            "device": "cpu",
            "optimizer_started": False,
            "backward_started": False,
            "gpu_started": False,
            "model_kind": "graph_raw",
            "model_is_untrained": True,
            "seed": SEED,
            "particles": state.count,
            "dt_s": DT_S,
            "h_m": H_M,
            "chunk_size": CHUNK_SIZE,
            "centers": centers.tolist(),
        },
        "interface_audit": {
            "source_bindings": source_bindings,
            "signatures": _interface_signatures(),
            "state_schema": "core.state.native_velocity.v1",
            "prediction_schema": "core.prediction.dual_increment.v1",
            "predict_commit_rule": "position_next=position+displacement; velocity_next=velocity+delta_velocity",
            "halo_rule": "complete field neighbor table plus exact two-hop center halo",
        },
        "full_field_halo": {
            "neighbor_diagnostics": neighbor_diagnostics,
            "neighbor_table": neighbors.tolist(),
            "chunks": halo_rows,
            "full_prediction_shape": list(full_output.shape),
            "chunk_prediction_shape": list(chunk_output.shape),
            "full_vs_chunk_max_abs_error": model_max_abs_error,
            "full_vs_chunk_commit_position_max_abs_error": commit_max_position_error,
            "full_vs_chunk_commit_velocity_max_abs_error": commit_max_velocity_error,
        },
        "dual_increment_oracle": {
            "privileged_reference_only": True,
            "future_state_passed_to_predictor": False,
            "displacement_shape": list(oracle_prediction.displacement.shape),
            "delta_velocity_shape": list(oracle_prediction.delta_velocity.shape),
            "displacement_over_dt_vs_delta_velocity_max_abs": float(
                np.max(np.abs(dx_over_dt - oracle_prediction.delta_velocity))
            ),
            "independent_velocity_semantics": independent_velocity_semantics,
            "predict_commit_position_max_abs_error": oracle_commit_position_error,
            "predict_commit_velocity_max_abs_error": oracle_commit_velocity_error,
            "updater_oracle": oracle_update,
        },
        "causal_rejection": causal,
        "checks": checks,
        "execution_constraints": {
            "read_only": True,
            "trajectory_reader_used": False,
            "future_state_inputs": False,
            "formal_specs_written": False,
            "formal_jobs_submitted": False,
            "formal_runs_started": 0,
            "optimizer_started": False,
            "gpu_started": False,
            "solver_started": False,
            "registry_written": False,
            "ledger_written": False,
        },
        "admission": {
            "formal_training_authorized": False,
            "counts_toward_formal_9_runs": False,
            "next_step": "use this interface witness as a contract diagnostic; rerun formal gates separately",
        },
    }


def verify_receipt(payload: Mapping[str, Any], *, data_root: str | Path) -> dict[str, Any]:
    """Re-hash the receipt's implementation bindings and recheck its gates."""
    root = Path(data_root).expanduser().resolve()
    bindings = payload.get("interface_audit", {}).get("source_bindings", [])
    mismatches: list[str] = []
    if not isinstance(bindings, list):
        bindings = []
    for binding in bindings:
        if not isinstance(binding, Mapping):
            mismatches.append("<invalid-binding>")
            continue
        path_value = binding.get("path")
        if not isinstance(path_value, str):
            mismatches.append("<missing-path>")
            continue
        path = _resolve_path(path_value, root)
        observed = sha256_file(path) if path.is_file() else None
        if observed != binding.get("sha256"):
            mismatches.append(path_value)
    checks = {
        "schema": payload.get("schema") == SCHEMA,
        "source_bindings_present": len(bindings) == 4,
        "source_hashes_match": not mismatches,
        "diagnostic_only": payload.get("diagnostic_only") is True
        and payload.get("proposal_only") is True,
        "formal_release_closed": payload.get("formal_release") is False,
        "formal_training_closed": payload.get("formal_training") is False
        and payload.get("formal_job_count") == 0
        and payload.get("formal_runs_counted") == 0,
        "all_diagnostic_checks_pass": all(payload.get("checks", {}).values()),
        "execution_closed": payload.get("execution_constraints", {}).get("formal_runs_started") == 0
        and payload.get("execution_constraints", {}).get("optimizer_started") is False
        and payload.get("execution_constraints", {}).get("gpu_started") is False
        and payload.get("execution_constraints", {}).get("registry_written") is False
        and payload.get("execution_constraints", {}).get("ledger_written") is False,
    }
    return {"ok": all(checks.values()), "checks": checks, "mismatch_paths": mismatches}


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True,
                                    ensure_ascii=False, allow_nan=False) + "\n",
                          encoding="utf-8")
    temporary.replace(target)


def write_sha256(path: str | Path, *, source: str | Path) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    source_path = Path(source).expanduser().resolve()
    target.write_text(f"{sha256_file(source_path)}  {source_path.name}\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path,
                        help="diagnostic receipt output (required unless --verify)")
    parser.add_argument("--sha256-output", type=Path)
    parser.add_argument("--input", type=Path,
                        help="existing diagnostic receipt for --verify; defaults to --output")
    parser.add_argument("--verify", action="store_true",
                        help="verify source bindings and closed execution flags without running inference")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.verify:
        input_path = args.input or args.output
        if input_path is None:
            raise SystemExit("--input or --output is required with --verify")
        payload = json.loads(Path(input_path).expanduser().resolve().read_text(encoding="utf-8"))
        result = verify_receipt(payload, data_root=args.data_root)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1
    if args.output is None:
        raise SystemExit("--output is required unless --verify is used")
    report = run_diagnostic(data_root=args.data_root)
    write_json(args.output, report)
    if args.sha256_output is not None:
        write_sha256(args.sha256_output, source=args.output)
    print(json.dumps({
        "status": report["status"],
        "formal_release": report["formal_release"],
        "formal_job_count": report["formal_job_count"],
        "full_vs_chunk_max_abs_error": report["full_field_halo"]["full_vs_chunk_max_abs_error"],
        "checks_passed": all(report["checks"].values()),
    }, sort_keys=True))
    return 0 if report["status"] == "diagnostic_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

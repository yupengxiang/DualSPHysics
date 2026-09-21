#!/usr/bin/env python3
"""Run and score a complete float64 autonomous rollout for one case.

This entrypoint extends the bounded float64 arithmetic variant to the full
registered trajectory.  It reads frame zero and prescribed inputs for
prediction; reference frames are read only after each prediction for scoring.
The optional HDF5 trajectory stores every predicted state with native
velocity, particle identities, mass, and validity.  A fixed-denominator JSON
receipt is written even when a rollout fails early.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback
from typing import Any

import h5py
import numpy as np
import torch



def _load_variant_module():
    """Load the sibling variant without depending on a source PYTHONPATH."""
    path = Path(__file__).with_name("core_cross_host_canary_float64.py").resolve()
    spec = importlib.util.spec_from_file_location("core_cross_host_float64_variant", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load float64 variant: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


variant = _load_variant_module()


SCHEMA = "core.cross_host_float64_rollout.v1"
PROGRESS_SCHEMA = "core.cross_host_float64_rollout.progress.v1"
MODEL_KIND = "graph_residual"
EXPECTED_HIDDEN = 64
EXPECTED_SEED = 17
EXPECTED_UPDATE = 500
EXPECTED_STEPS = 835
EXPECTED_CHUNK_SIZE = 256
POSITION_ATOL_M = variant.POSITION_ATOL_M
VELOCITY_ATOL_MPS = variant.VELOCITY_ATOL_MPS
RELATIVE_TOLERANCE = variant.RELATIVE_TOLERANCE


def _load_bundle_modules(bundle_root: Path) -> dict[str, Any]:
    # The entrypoint imports the variant from the source snapshot.  Remove
    # only the source ``scripts`` package before asking the variant loader to
    # resolve the immutable bundle modules; no model code is copied or edited.
    for name in tuple(sys.modules):
        if name == "scripts" or name in {
            "scripts.core_contract", "scripts.core_dataset", "scripts.core_models",
        }:
            sys.modules.pop(name, None)
    modules = variant._load_bundle_modules(bundle_root)
    import importlib
    modules["core_evaluation"] = importlib.import_module("scripts.core_evaluation")
    modules["core_physics"] = importlib.import_module("scripts.core_physics")
    return modules


def _write_progress(path: Path | None, *, case_id: str, expected: int,
                    completed: int, started: float, status: str,
                    trajectory: Path | None, error: str | None = None) -> None:
    if path is None:
        return
    payload: dict[str, Any] = {
        "schema": PROGRESS_SCHEMA,
        "case_id": str(case_id),
        "status": str(status),
        "completed_frames": int(completed),
        "expected_frames": int(expected),
        "elapsed_seconds": float(time.perf_counter() - started),
        "trajectory_output": str(trajectory) if trajectory is not None else None,
        "autonomous": True,
        "future_state_inputs": False,
    }
    if error is not None:
        payload["error"] = str(error)
    variant.atomic_json(path, payload)


def _open_trajectory(path: Path | None, *, times: np.ndarray, initial: Any,
                     total_steps: int):
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = h5py.File(path, "w")
    handle.attrs.update(
        schema=SCHEMA,
        state_schema="core.state.native_velocity.v1",
        velocity_semantics="native saved numerical velocity",
        storage_dtype="float64",
        autonomous_prediction=True,
        future_state_inputs=False,
        identity_semantics="particle_zone,particle_id",
    )
    handle.create_dataset("time", data=np.asarray(times[:total_steps + 1], dtype=np.float64))
    shape = (total_steps + 1, initial.count, 3)
    handle.create_dataset("position", shape=shape, dtype="f8", fillvalue=np.nan)
    handle.create_dataset("velocity", shape=shape, dtype="f8", fillvalue=np.nan)
    handle.create_dataset("particle_id", data=initial.particle_id)
    handle.create_dataset("particle_zone", data=initial.particle_zone)
    handle.create_dataset("mass", data=initial.mass)
    handle.create_dataset("valid", shape=(total_steps + 1, initial.count),
                          dtype="bool", fillvalue=False)
    handle["position"][0] = initial.position
    handle["velocity"][0] = initial.velocity
    handle["valid"][0] = initial.valid
    handle.flush()
    return handle


def _trajectory_record(path: Path | None, *, expected_frames: int,
                       particle_count: int) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return {
        "path": str(path),
        "sha256": variant.sha256_file(path),
        "bytes": int(path.stat().st_size),
        "frames": int(expected_frames),
        "particle_count": int(particle_count),
        "dtype": "float64",
        "keys": ["time", "position", "velocity", "particle_id",
                 "particle_zone", "mass", "valid"],
    }


def _characteristic_scales(known: Any) -> tuple[float, float]:
    vertices = known.geometry.triangles.reshape(-1, 3)
    length = max(float(np.ptp(vertices, axis=0).max()) if len(vertices)
                 else float(known.numerics["dp_m"]), float(known.numerics["dp_m"]))
    gravity = np.asarray(known.physics.get("gravity_mps2", [0.0, 0.0, -9.81]), dtype=np.float64)
    magnitude = float(np.linalg.norm(gravity))
    if not np.isfinite(magnitude) or magnitude <= 0:
        raise ValueError("known gravity must have a positive finite magnitude")
    return length, float(np.sqrt(magnitude * length))


def run(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve()
    progress = (Path(args.progress_output).expanduser().resolve()
                if args.progress_output else output.with_name(output.stem + "-progress.json"))
    trajectory_path = (Path(args.trajectory_output).expanduser().resolve()
                       if args.trajectory_output else None)
    started = time.perf_counter()
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "started",
        "variant": "float64_inference",
        "case_id": args.case_id,
        "model_kind": args.model_kind,
        "inference_dtype": "float64",
        "maximum_steps": int(args.maximum_steps),
        "expected_transition_count": int(args.maximum_steps),
        "expected_state_frames": int(args.maximum_steps) + 1,
        "chunk_size": int(args.chunk_size),
        "dtype_contract": variant.dtype_contract("float64"),
        "comparison_protocol": {
            "schema": "core.cross_host_comparison.v1",
            "position_absolute_tolerance_m": POSITION_ATOL_M,
            "velocity_absolute_tolerance_mps": VELOCITY_ATOL_MPS,
            "relative_tolerance": RELATIVE_TOLERANCE,
            "tolerances_frozen": True,
        },
        "diagnostic_scope": {
            "formal_training": False,
            "formal_evaluation": False,
            "complete_registered_rollout": True,
            "full_835_frame_rollout": True,
        },
        "trajectory_output": str(trajectory_path) if trajectory_path is not None else None,
        "position_rmse": [None] * int(args.maximum_steps),
        "velocity_rmse": [None] * int(args.maximum_steps),
        "position_ade": [None] * int(args.maximum_steps),
        "velocity_ade": [None] * int(args.maximum_steps),
        "physics_frames": [None] * int(args.maximum_steps),
    }
    trajectory = None
    completed = 0
    failure_category = None
    first_failure_frame = None
    failure_detail: dict[str, Any] | None = None
    attempted = False
    try:
        if int(args.maximum_steps) != EXPECTED_STEPS:
            raise ValueError(f"full rollout is fixed to {EXPECTED_STEPS} transitions")
        if int(args.chunk_size) != EXPECTED_CHUNK_SIZE:
            raise ValueError(f"chunk_size is fixed at {EXPECTED_CHUNK_SIZE}")
        if args.model_kind != MODEL_KIND:
            raise ValueError(f"model_kind is fixed at {MODEL_KIND}")
        _ = variant.dtype_contract("float64")
        variant._configure_determinism(bool(args.deterministic))
        bundle_root = Path(args.bundle_root).expanduser().resolve()
        checkpoint = (Path(args.checkpoint).expanduser().resolve()
                      if args.checkpoint else bundle_root / "models" / "checkpoint-001.pt")
        modules = _load_bundle_modules(bundle_root)
        imported = [variant._module_identity(modules[name]) for name in sorted(modules)]
        result["environment"] = variant.capture_environment(
            device=args.device, deterministic_requested=bool(args.deterministic),
            imported_modules=imported)
        result["events"] = ["environment_captured_before_model_construction"]
        result["bundle"] = {
            "root": str(bundle_root),
            "identity": variant._fixed_identity(
                bundle_root, modules,
                manifest_sha256=args.expected_manifest_sha256,
                checkpoint_sha256=args.expected_checkpoint_sha256,
                models_sha256=args.expected_models_sha256,
                checkpoint=checkpoint),
            "variant_runner": {"path": str(Path(variant.__file__).resolve()),
                               "sha256": variant.sha256_file(Path(variant.__file__))},
            "rollout_runner": {"path": str(Path(__file__).resolve()),
                               "sha256": variant.sha256_file(Path(__file__))},
        }
        if not result["environment"].get("cuda_available") and str(args.device).startswith("cuda"):
            raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")
        dataset = modules["core_dataset"].CoreDataset(bundle_root / "dataset.json",
                                                       bundle_root, max_open_files=2)
        record = dataset.record(args.case_id)
        times = np.asarray(dataset.times(args.case_id), dtype=np.float64)
        if len(times) - 1 != EXPECTED_STEPS:
            raise ValueError(f"registered case has {len(times) - 1} transitions, expected {EXPECTED_STEPS}")
        known = dataset.known_inputs(args.case_id)
        initial = dataset.read_state(args.case_id, 0)
        result["case"] = {
            "physical_case_id": record["physical_case_id"],
            "lineage_group_id": record["lineage_group_id"],
            "family": record["family"],
            "split": record["split"],
            "hdf5": record["hdf5"],
            "hdf5_sha256_declared": record["sha256"],
            "known_inputs_sha256": record["known_inputs_sha256"],
        }
        result["initial_state"] = {
            "time_s": float(initial.time_s),
            "position": variant.array_digest(initial.position),
            "velocity": variant.array_digest(initial.velocity),
        }
        result["case"]["particle_count"] = int(initial.count)
        payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
        if payload.get("model_kind") != MODEL_KIND or int(payload.get("hidden", -1)) != EXPECTED_HIDDEN:
            raise ValueError("checkpoint model identity mismatch")
        if int(payload.get("seed", -1)) != EXPECTED_SEED or int(payload.get("update", -1)) != EXPECTED_UPDATE:
            raise ValueError("checkpoint seed/update mismatch")
        normalization = modules["core_models"].Normalization.from_dict(payload["normalization"])
        model = modules["core_models"].DualIncrementModel(MODEL_KIND, hidden=EXPECTED_HIDDEN)
        model.load_state_dict(payload.get("model_state", payload["state_dict"]))
        model.eval().to(torch.device(args.device)).to(dtype=torch.float64)
        variant._check_model_dtype(model, torch.float64)
        result["model_parameter_dtype_after_promotion"] = "float64"
        result["events"].append("float64_model_constructed_after_environment_capture")
        device = torch.device(args.device)
        trajectory = _open_trajectory(trajectory_path, times=times,
                                      initial=initial, total_steps=EXPECTED_STEPS)
        current = initial
        position_sq_sum = velocity_sq_sum = 0.0
        position_norm_sum = velocity_norm_sum = 0.0
        component_count = int(initial.count * 3)
        for step in range(EXPECTED_STEPS):
            attempted = True
            dt = float(times[step + 1] - times[step])
            previous = current
            try:
                prediction, _ = variant.predict_step(
                    state=current, known=known, dt=dt, model=model,
                    normalization=normalization, device=device,
                    chunk_size=EXPECTED_CHUNK_SIZE,
                    core_models=modules["core_models"], inference_dtype="float64")
                if not np.isfinite(prediction.displacement).all() or not np.isfinite(prediction.delta_velocity).all():
                    raise FloatingPointError("nonfinite model prediction")
                current = modules["core_contract"].apply_prediction(current, prediction, dt)
            except FloatingPointError as error:
                failure_category, first_failure_frame = "nonfinite_prediction", step + 1
                failure_detail = {"phase": "prediction", "type": type(error).__name__,
                                  "message": str(error), "frame": step + 1}
                break
            except ValueError as error:
                failure_category, first_failure_frame = "invalid_model_state", step + 1
                failure_detail = {"phase": "prediction", "type": type(error).__name__,
                                  "message": str(error), "frame": step + 1}
                break
            except Exception as error:
                failure_category, first_failure_frame = "model_execution_error", step + 1
                failure_detail = {"phase": "prediction", "type": type(error).__name__,
                                  "message": str(error), "frame": step + 1}
                break
            # This read is for the fixed-denominator score only and occurs
            # after the causal prediction has committed its new state.
            try:
                reference = dataset.read_state(args.case_id, step + 1)
                position_error = current.position - reference.position
                velocity_error = current.velocity - reference.velocity
                if not np.isfinite(position_error).all() or not np.isfinite(velocity_error).all():
                    raise FloatingPointError("nonfinite score error")
            except FloatingPointError as error:
                failure_category, first_failure_frame = "nonfinite_error", step + 1
                failure_detail = {"phase": "score", "type": type(error).__name__,
                                  "message": str(error), "frame": step + 1}
                break
            except Exception as error:
                failure_category, first_failure_frame = "reference_read_error", step + 1
                failure_detail = {"phase": "score", "type": type(error).__name__,
                                  "message": str(error), "frame": step + 1}
                break
            try:
                result["physics_frames"][step] = modules["core_physics"].frame_physics(
                    previous, current, reference, known.geometry)
            except Exception as error:
                failure_category, first_failure_frame = "physics_diagnostic_error", step + 1
                failure_detail = {"phase": "physics", "type": type(error).__name__,
                                  "message": str(error), "frame": step + 1}
                break
            position_norm = np.linalg.norm(position_error, axis=-1)
            velocity_norm = np.linalg.norm(velocity_error, axis=-1)
            result["position_rmse"][step] = float(np.sqrt(np.mean(position_error ** 2)))
            result["velocity_rmse"][step] = float(np.sqrt(np.mean(velocity_error ** 2)))
            result["position_ade"][step] = float(np.mean(position_norm))
            result["velocity_ade"][step] = float(np.mean(velocity_norm))
            position_sq_sum += float(np.sum(position_error ** 2))
            velocity_sq_sum += float(np.sum(velocity_error ** 2))
            position_norm_sum += float(np.sum(position_norm))
            velocity_norm_sum += float(np.sum(velocity_norm))
            completed += 1
            if trajectory is not None:
                trajectory["position"][step + 1] = current.position
                trajectory["velocity"][step + 1] = current.velocity
                trajectory["valid"][step + 1] = current.valid
            if completed % int(args.progress_every) == 0:
                if trajectory is not None:
                    trajectory.flush()
                _write_progress(progress, case_id=args.case_id, expected=EXPECTED_STEPS,
                                completed=completed, started=started, status="running",
                                trajectory=trajectory_path)
        if completed == EXPECTED_STEPS:
            failure_category = None
            first_failure_frame = None
        result["status"] = "complete" if completed == EXPECTED_STEPS else "failed"
        result["completed_transitions"] = int(completed)
        result["frames_predicted"] = int(completed)
        result["failure_category"] = failure_category
        result["first_failure_frame"] = first_failure_frame
        if failure_detail is not None:
            result["failure_detail"] = failure_detail
        result["read_log"] = [[str(case), int(frame)] for case, frame in dataset.read_log]
        result["predictor_future_state_inputs"] = False
        completed_physics = [row for row in result["physics_frames"] if row is not None]
        wall_rows = [row["wall_chord"] for row in completed_physics]
        wall_counts = [row.get("particle_count") for row in wall_rows
                       if isinstance(row.get("particle_count"), (int, np.integer))]
        wall_masses = [row.get("mass_kg") for row in wall_rows
                       if isinstance(row.get("mass_kg"), (int, float, np.integer, np.floating))]
        result["physics_summary"] = {
            "expected_frames": EXPECTED_STEPS,
            "completed_frames": len(completed_physics),
            "mass_error_abs_max_kg": (max(abs(row["mass_error_kg"]) for row in completed_physics)
                                       if completed_physics else None),
            "kinetic_energy_error_abs_max_j": (
                max(abs(row["kinetic_energy_error_j"]) for row in completed_physics)
                if completed_physics else None),
            "validity_mismatch_frames": sum(row["validity_mismatch_count"] > 0 for row in completed_physics),
            "changed_particle_mass_frames": sum(row["changed_particle_mass_count"] > 0 for row in completed_physics),
            "wall_chord_statuses": sorted({row.get("status") for row in wall_rows}),
            "wall_chord_particle_count": int(sum(wall_counts)) if wall_counts else 0,
            "wall_chord_mass_kg": float(sum(wall_masses)) if wall_masses else 0.0,
        }
        length_m, speed_mps = _characteristic_scales(known)
        score_positions = result["position_rmse"] if attempted else []
        score_velocities = result["velocity_rmse"] if attempted else []
        result["score_protocol"] = modules["core_evaluation"].PROTOCOL
        result["score"] = {
            **modules["core_evaluation"].score_case(
                score_positions, score_velocities,
                expected_frames=EXPECTED_STEPS,
                length_m=length_m, speed_mps=speed_mps,
                executed=attempted,
                failure_category=failure_category),
            "expected_transition_count": EXPECTED_STEPS,
            "completed_transition_count": completed,
            "raw_complete_position_rmse_m": (float(np.sqrt(position_sq_sum / (completed * component_count))) if completed else None),
            "raw_complete_velocity_rmse_mps": (float(np.sqrt(velocity_sq_sum / (completed * component_count))) if completed else None),
            "position_ade_m": (float(position_norm_sum / (completed * initial.count)) if completed else None),
            "velocity_ade_mps": (float(velocity_norm_sum / (completed * initial.count)) if completed else None),
            "length_m": length_m,
            "speed_mps": speed_mps,
            "fixed_denominator": True,
        }
    except Exception as error:
        result["status"] = "failed"
        result["completed_transitions"] = int(completed)
        result["failure_category"] = "rollout_setup_error"
        result["first_failure_frame"] = 1 if completed == 0 else completed + 1
        result["error"] = {"type": type(error).__name__, "message": str(error),
                            "traceback": traceback.format_exc()}
    finally:
        if trajectory is not None:
            trajectory.close()
    trajectory_record = _trajectory_record(
        trajectory_path,
        expected_frames=EXPECTED_STEPS + 1,
        particle_count=(int(result.get("case", {}).get("particle_count", 0))
                        if result.get("case") else 34560),
    )
    if trajectory_record is not None:
        result["trajectory"] = trajectory_record
    result["elapsed_seconds"] = float(time.perf_counter() - started)
    variant.atomic_json(output, result)
    _write_progress(progress, case_id=args.case_id, expected=EXPECTED_STEPS,
                    completed=completed, started=started,
                    status="complete" if result.get("status") == "complete" else "failed",
                    trajectory=trajectory_path,
                    error=result.get("error", {}).get("message") if isinstance(result.get("error"), dict) else None)
    return 0 if result.get("status") == "complete" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--model-kind", default=MODEL_KIND)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--chunk-size", type=int, default=EXPECTED_CHUNK_SIZE)
    parser.add_argument("--maximum-steps", type=int, default=EXPECTED_STEPS)
    parser.add_argument("--deterministic", action="store_true")
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--progress-output", type=Path)
    parser.add_argument("--trajectory-output", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", default=variant.EXPECTED_MANIFEST_SHA256)
    parser.add_argument("--expected-checkpoint-sha256", default=variant.EXPECTED_CHECKPOINT_SHA256)
    parser.add_argument("--expected-models-sha256", default=variant.EXPECTED_MODELS_SHA256)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.checkpoint is not None:
        expected = (Path(args.bundle_root).resolve() / "models" / "checkpoint-001.pt").resolve()
        if Path(args.checkpoint).resolve() != expected:
            raise SystemExit("checkpoint is fixed to bundle/models/checkpoint-001.pt")
    if int(args.progress_every) < 1:
        raise SystemExit("--progress-every must be positive")
    return run(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

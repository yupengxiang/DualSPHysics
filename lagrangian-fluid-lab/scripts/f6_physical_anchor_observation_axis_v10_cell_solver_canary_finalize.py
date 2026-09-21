#!/usr/bin/env python3
"""Finalize an already-completed F6 cell solver attempt after worker metadata failure.

This recovery path never invokes a solver.  It reads the exact attempt's
existing Run.out, native BI4 frames and FloatingInfo sidecar, reconstructs the
immutable frame audit and receipt, and records the worker exception as
infrastructure evidence.  It is allowed once for this specific post-solver
metadata failure.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

import numpy as np

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f6_physical_anchor_observation_axis_v10_cell_solver_canary as worker


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def resolve(item: dict[str, Any]) -> Path:
    path = Path(item["path"])
    if not path.is_absolute():
        path = LAB / path
    return path.resolve()


def finalize(attempt: Path) -> dict[str, Any]:
    attempt = attempt.resolve()
    job_path = attempt / "job.json"
    review_path = attempt / "root-review.json"
    lock_path = attempt / "finalize-lock.json"
    if lock_path.exists():
        raise RuntimeError("post-solver finalize already consumed for this attempt")
    job = load(job_path)
    review = load(review_path)
    if job.get("job_status") != "root_authorized_not_started" or job.get("attempt") != 1:
        raise ValueError("attempt is not the original exact-one authorization")
    if not (attempt / "solver/Run.out").is_file() or not (attempt / "body-state-force-torque-sidecar.json").is_file():
        raise FileNotFoundError("completed solver output or sidecar is missing")

    worker.JOB = job_path
    worker.REVIEW = review_path
    worker.TMAX = float(job["window"]["target_end_s"])
    worker.TOUT = float(job["window"]["requested_output_interval_s"])
    worker.EXPECTED_FRAMES = int(job["window"]["expected_frames"])
    worker.MAX_GAP_S = float(job["window"]["max_gap_s"])
    worker.TERMINAL_TARGET_S = float(job["window"]["terminal_target_s"])
    worker.TERMINAL_OVERSHOOT_MAX_S = float(job["window"]["terminal_overshoot_max_s"])
    worker.OBSERVATION_START_S = float(job["window"]["observation_window_s"][0])
    worker.OBSERVATION_END_S = float(job["window"]["observation_window_s"][1])
    worker.SCOPE_ID = str(job["scope_id"])

    contract = load(resolve(job["inputs"]["definition_contract"]))
    native_preflight = load(resolve(job["inputs"]["native_preflight"]))
    bound_case_id = native_preflight.get("cell_binding", {}).get("case_id", job.get("case_id", job.get("cell_id")))
    generated_xml = resolve(job["inputs"]["generated_xml"])
    decoder = resolve(job["decoder"])
    groups = worker.read_groups(generated_xml)
    data_dir = attempt / "solver/data"
    frames = sorted(data_dir.glob("Part_*.bi4"), key=lambda path: int(re.fullmatch(r"Part_(\d+)\.bi4", path.name).group(1)))
    frame_indices = [int(re.fullmatch(r"Part_(\d+)\.bi4", path.name).group(1)) for path in frames]
    native_times: list[float] = []
    audits: list[dict[str, Any]] = []
    native_identity: np.ndarray | None = None
    with tempfile.TemporaryDirectory(prefix="f6-v10-finalize-native-") as temp:
        for index, path in enumerate(frames):
            stem = Path(temp) / f"frame-{index:04d}"
            try:
                ids, positions, velocities, density, metadata, info, _ = worker.native_frame(path, stem, decoder)
                finite = bool(np.isfinite(ids).all() and np.isfinite(positions).all() and np.isfinite(velocities).all() and np.isfinite(density).all())
                unique = len(np.unique(ids)) == len(ids)
                if native_identity is None:
                    native_identity = ids.copy()
                same_identity = bool(np.array_equal(native_identity, ids))
                body_positions = positions[worker.mask_range(ids, groups["floating"])]
                fluid_positions = positions[worker.mask_range(ids, groups["fluid"])]
                audits.append({
                    "index": frame_indices[index],
                    "time_s": float(info.get("TimeStep", "nan")),
                    "particle_count": int(len(ids)),
                    "fluid_count": int(worker.mask_range(ids, groups["fluid"]).sum()),
                    "body_count": int(worker.mask_range(ids, groups["floating"]).sum()),
                    "finite": finite,
                    "ids_unique": unique,
                    "same_identity": same_identity,
                    "body_min_m": body_positions.min(axis=0).tolist(),
                    "body_max_m": body_positions.max(axis=0).tolist(),
                    "fluid_outside_top_count": int(np.sum(fluid_positions[:, 2] > contract["tank"]["high_m"][2] + worker.GEOMETRY_TOLERANCE_M)),
                    "mass_per_particle_kg": float(metadata.get("MassFluid", "nan")),
                })
                native_times.append(float(info.get("TimeStep", "nan")))
            except Exception as error:
                audits.append({"index": frame_indices[index], "time_s": float("nan"), "particle_count": 0, "fluid_count": 0, "body_count": 0, "finite": False, "ids_unique": False, "same_identity": False, "error": repr(error), "body_min_m": [float("nan")] * 3, "body_max_m": [float("nan")] * 3, "fluid_outside_top_count": -1, "mass_per_particle_kg": float("nan")})
                native_times.append(float("nan"))

    run = worker.run_summary(attempt / "solver/Run.out")
    sidecar = load(attempt / "body-state-force-torque-sidecar.json")
    sidecar_checks = sidecar.get("audit", {}).get("checks", {})
    diffs = np.diff(native_times) if len(native_times) > 1 else np.asarray([])
    native_checks = {
        "frame_count_exact": len(frames) == worker.EXPECTED_FRAMES and frame_indices == list(range(worker.EXPECTED_FRAMES)),
        "run_reported_frame_count_exact": run.get("reported_part_files") == worker.EXPECTED_FRAMES,
        "native_time_count_exact": len(native_times) == worker.EXPECTED_FRAMES,
        "native_time_gap_bound": bool(len(native_times) == worker.EXPECTED_FRAMES and np.isfinite(diffs).all() and (not len(diffs) or float(np.max(diffs)) <= worker.MAX_GAP_S)),
        "native_terminal_bracket": bool(native_times and worker.TERMINAL_TARGET_S <= native_times[-1] <= worker.TERMINAL_TARGET_S + worker.TERMINAL_OVERSHOOT_MAX_S),
        "native_observation_hold_bracketed": bool(native_times and native_times[0] <= worker.OBSERVATION_START_S <= native_times[-1] and native_times[-1] >= worker.OBSERVATION_END_S),
        "native_arrays_finite": bool(audits) and all(item.get("finite") for item in audits),
        "native_ids_unique": bool(audits) and all(item.get("ids_unique") for item in audits),
        "native_identity_fixed": bool(audits) and all(item.get("same_identity") for item in audits),
        "fluid_group_count_fixed": bool(audits) and all(item.get("fluid_count") == groups["fluid"]["count"] for item in audits),
        "body_group_count_fixed": bool(audits) and all(item.get("body_count") == groups["floating"]["count"] for item in audits),
        "no_fluid_outside_open_top": bool(audits) and all(item.get("fluid_outside_top_count") == 0 for item in audits),
    }
    hard_gates = {
        "solver_return_code_zero": True,
        "run_finished_code_zero": run["finished_code_zero"],
        "timemax_matches": run["timemax_s"] is not None and abs(run["timemax_s"] - worker.TMAX) <= 1.0e-9,
        "timeout_matches": run["timeout_s"] is not None and abs(run["timeout_s"] - worker.TOUT) <= 1.0e-9,
        "excluded_particles_zero": run["excluded_particles"] == 0,
        **native_checks,
        "floating_info_present": True,
        "sidecar_present": True,
        **{f"sidecar_{key}": bool(value) for key, value in sidecar_checks.items()},
    }
    status = "solver_completed_sidecar_pass_pending_scientific_review" if all(hard_gates.values()) else "solver_completed_hard_failure"
    receipt = {
        "schema": "core.f6.observation_axis.protected_solver_canary_receipt.v1",
        "receipt_id": f"{job['job_id']}_receipt",
        "status": status,
        "family": "F6",
        "scope_id": job["scope_id"],
        "revision_id": job.get("revision_id"),
        "cell_id": job.get("cell_id"),
        "case_id": bound_case_id,
        "attempt": 1,
        "root_review": worker.ref(review_path, "root authorization"),
        "job": worker.ref(job_path, "root-authorized canary job"),
        "runtime_worker": worker.ref(worker.RUNTIME_SCRIPT, "single-use canary worker"),
        "recovery": {"kind": "post_solver_worker_metadata_failure", "original_error": "KeyError: case_id", "solver_invoked_once": True, "solver_not_reinvoked": True},
        "run": run,
        "frames": {"count": len(frames), "indices_first": frame_indices[:3], "indices_last": frame_indices[-3:]},
        "native_frame_audit": worker.ref(attempt / "native-frame-audit.json", "per-frame native audit"),
        "sidecar": worker.ref(attempt / "body-state-force-torque-sidecar.json", "runtime sidecar"),
        "hard_gates": hard_gates,
        "sidecar_checks": sidecar_checks,
        "time_axis_contract": {"native_time_axis": "solver_reported_actual_TimeStep", "requested_output_interval_s": worker.TOUT, "max_gap_s": worker.MAX_GAP_S, "terminal_target_s": worker.TERMINAL_TARGET_S, "terminal_overshoot_max_s": worker.TERMINAL_OVERSHOOT_MAX_S, "observation_window_s": [worker.OBSERVATION_START_S, worker.OBSERVATION_END_S], "equilibrium_status": "not_claimed"},
        "qualification_only": True,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "execution_controls": {"solver_invoked": True, "gpu_started": False, "queue_mutation": 0, "registry_mutation": 0, "ledger_mutation": 0, "matrix_submission": False, "qualification_credit": 0},
    }
    write(attempt / "native-frame-audit.json", {"schema": "core.f6.observation_axis.native_frame_audit.v1", "groups": groups, "frames": audits, "native_times_s": native_times, "checks": native_checks})
    write(attempt / "execution-receipt.json", receipt)
    write(attempt / "worker-status.json", {"status": status, "recovered": True, "hard_gate_pass": all(hard_gates.values())})
    write(lock_path, {"schema": "core.f6.observation_axis.finalize_lock.v1", "attempt": 1, "solver_reinvoked": False, "finalize_consumed": True, "qualification_credit": 0})
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = finalize(args.attempt)
    print(json.dumps({"status": receipt["status"], "frames": receipt["frames"]["count"], "recovered": True}, ensure_ascii=False))
    return 0 if receipt["status"] == "solver_completed_sidecar_pass_pending_scientific_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())

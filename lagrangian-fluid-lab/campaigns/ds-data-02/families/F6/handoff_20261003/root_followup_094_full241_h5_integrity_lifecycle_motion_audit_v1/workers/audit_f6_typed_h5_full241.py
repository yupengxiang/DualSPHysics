#!/usr/bin/env python3
"""Audit one completed F6 typed trajectory without changing its HDF5 source.

Root runs an enabled copy only after the case's typed receipt is terminal and
its independent FloatingInfo state-zero gate passes.  The worker checks the
producer report, the complete 241-frame HDF5 schema, native identities/Mk/type
counts, finite active state, per-frame validity/exclusion lifecycle, and
motion ranges.  It reads HDF5 in frame-sized slices and never supplements an
excluded particle.  It deliberately does not impose a numerical convergence
or precision gate and does not hash the HDF5 payload; the producer report is
the payload attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import h5py
import numpy as np


SCHEMA = "ds02.f6.fresh094.typed-h5-full241-audit-result.v1"
REQUIRED_FIELDS = (
    "valid", "initial_type", "particle_id", "particle_zone", "initial_mk",
    "initial_mass", "mass", "velocity", "density", "pressure", "type",
)
VECTOR_FIELDS = ("position", "velocity")
SCALAR_FIELDS = ("valid", "initial_type", "particle_id", "particle_zone",
                 "initial_mk", "initial_mass", "mass", "density", "pressure", "type")
EXPECTED_COUNTS = {0: 73441, 1: 0, 2: 16384, 3: 327680}
EXPECTED_MK = {30: 73441, 1: 327680, 60: 16384}
TIME_TOLERANCE_S = 1.0e-9


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def load_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file(), f"{label} missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{label} is not an object: {path}")
    return value


def metadata_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def attr_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    return str(value)


def finite_numeric(array: np.ndarray, label: str) -> None:
    if not np.issubdtype(array.dtype, np.number):
        raise AuditError(f"{label} is not numeric: {array.dtype}")
    require(bool(np.all(np.isfinite(array))), f"{label} contains non-finite values")


def finite_active(array: np.ndarray, active: np.ndarray, label: str) -> None:
    view = array[active]
    finite_numeric(view, label + "[valid]")


def integer_values(array: np.ndarray, label: str) -> np.ndarray:
    finite_numeric(array, label)
    as_float = np.asarray(array, dtype=np.float64)
    require(bool(np.all(as_float == np.floor(as_float))), f"{label} contains non-integers")
    return as_float.astype(np.int64, copy=False)


def frame_slice(dataset: h5py.Dataset, frame: int, frames: int, particles: int) -> np.ndarray:
    shape = tuple(dataset.shape)
    if shape == (particles,):
        return np.asarray(dataset[:])
    if shape == (frames, particles):
        return np.asarray(dataset[frame, :])
    if len(shape) == 3 and shape == (frames, particles, 3):
        return np.asarray(dataset[frame, :, :])
    raise AuditError(f"unexpected dataset shape for {dataset.name}: {shape}")


def uid_digest(zone: np.ndarray, particle_id: np.ndarray) -> str:
    pairs = np.column_stack((zone.astype("<i8", copy=False), particle_id.astype("<i8", copy=False)))
    return hashlib.sha256(pairs.tobytes(order="C")).hexdigest()


def ranges(array: np.ndarray, label: str) -> dict[str, list[float] | None]:
    if array.size == 0:
        return {"min": None, "max": None}
    finite_numeric(array, label)
    return {"min": np.min(array, axis=0).astype(float).tolist(),
            "max": np.max(array, axis=0).astype(float).tolist()}


def scalar_range(array: np.ndarray, label: str) -> dict[str, float | None]:
    if array.size == 0:
        return {"min": None, "max": None}
    finite_numeric(array, label)
    return {"min": float(np.min(array)), "max": float(np.max(array))}


def check_report(report: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    expected = case["expected_native_contract"]
    require(report.get("frames") == expected["frames"], "producer frame count mismatch")
    require(report.get("particles") == expected["total"], "producer particle count mismatch")
    dimension = report.get("solver_dimension")
    if isinstance(dimension, dict):
        dimension = dimension.get("solver_dimension", dimension.get("dimension"))
    require(dimension == expected["dimension"], "producer dimension mismatch")
    validation = report.get("partvtk_validation")
    require(isinstance(validation, dict) and validation.get("all_passed") is True,
            "producer PartVTK validation is not all_passed")
    scopes = report.get("hash_scopes")
    require(isinstance(scopes, dict), "producer hash_scopes missing")
    typed = case["typed_terminal_dependency"]
    expected_producer_scope = typed.get("producer_physical_condition_sha256")
    require(isinstance(expected_producer_scope, str) and len(expected_producer_scope) == 64,
            "Root must bind actual producer physical scope before H5 audit")
    require(scopes.get("physical_condition_sha256") == expected_producer_scope,
            "producer physical scope differs from Root-bound actual producer scope")
    scope = scopes.get("physical_condition")
    require(isinstance(scope, dict) and scope.get("physical_case_id") == case["physical_case_id"],
            "producer physical case scope mismatch")
    return {
        "frames": report["frames"], "particles": report["particles"],
        "dimension": dimension, "partvtk_all_passed": True,
        "producer_scope_schema": scope.get("schema"),
        "producer_physical_condition_sha256": scopes.get("physical_condition_sha256"),
    }


def audit_h5(request: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    require(request.get("schema") == "ds02.f6.fresh094.typed-h5-full241-audit-request.v1",
            "fresh094 request schema mismatch")
    require(request.get("case_count") == 1, "worker requires one case")
    require(request.get("disabled") is False and request.get("execution_allowed") is True,
            "Root must enable an isolated copy before execution")
    case = request.get("case")
    require(isinstance(case, dict), "request lacks nested case")
    for key in ("case_id", "canonical_owner", "source_definition", "typed_terminal_dependency",
                "state0_dependency", "expected_native_contract"):
        require(key in case, f"case lacks {key}")
    state0 = case["state0_dependency"]
    require(state0.get("status") == "actual_pass" and state0.get("checks_all_pass") is True,
            "independent FloatingInfo state0 pass is required before H5 audit")
    owner = load_json(Path(case["canonical_owner"]), "canonical owner")
    source_definition = Path(case["source_definition"])
    require(source_definition.is_file(), f"generated source definition missing: {source_definition}")
    typed = case["typed_terminal_dependency"]
    typed_receipt_path = Path(typed["execution_receipt"])
    report_path = Path(typed["conversion_report"])
    h5_path = Path(typed["trajectory_h5"])
    receipt = load_json(typed_receipt_path, "typed execution receipt")
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0,
            "typed execution receipt is not completed/0")
    report = load_json(report_path, "typed conversion report")
    producer = check_report(report, case)
    expected = case["expected_native_contract"]
    require(h5_path.is_file(), f"typed trajectory H5 missing: {h5_path}")
    output_dir.mkdir(parents=True, exist_ok=False)

    checks: dict[str, bool] = {}
    frame_reports: list[dict[str, Any]] = []
    identity_stable = True
    lifecycle_consistent = True
    finite_active_all = True
    mass_positive_all = True
    schema_ok = True
    initial_uid_ok = True
    initial_counts_ok = True
    with h5py.File(h5_path, "r") as h5:
        required = {"time", "position", *REQUIRED_FIELDS}
        schema_ok = required <= set(h5.keys())
        require(schema_ok, f"H5 missing required datasets: {sorted(required - set(h5.keys()))}")
        frames = int(expected["frames"])
        particles = int(expected["total"])
        position = h5["position"]
        require(tuple(position.shape) == (frames, particles, 3),
                f"position shape mismatch: {position.shape}")
        for name in REQUIRED_FIELDS:
            shape = tuple(h5[name].shape)
            allowed = {(particles,), (frames, particles)}
            if name == "velocity":
                allowed.add((frames, particles, 3))
            require(shape in allowed, f"unexpected {name} shape: {shape}")
        times = np.asarray(h5["time"][:], dtype=np.float64)
        require(times.shape == (frames,), f"time shape mismatch: {times.shape}")
        finite_numeric(times, "time")
        expected_times = np.arange(frames, dtype=np.float64) * float(expected["tout_s"])
        time_delta = np.abs(times - expected_times)
        time_ok = bool(np.all(time_delta <= TIME_TOLERANCE_S))
        require(time_ok, "time vector is not exactly the 0..12/.05 schedule")

        initial_type = integer_values(frame_slice(h5["initial_type"], 0, frames, particles), "initial_type")
        initial_mk = integer_values(frame_slice(h5["initial_mk"], 0, frames, particles), "initial_mk")
        particle_id = integer_values(frame_slice(h5["particle_id"], 0, frames, particles), "particle_id")
        particle_zone = integer_values(frame_slice(h5["particle_zone"], 0, frames, particles), "particle_zone")
        require(len(np.unique(np.column_stack((particle_zone, particle_id)), axis=0)) == particles,
                "native (Zone,Idp) UID is not unique")
        initial_uid_ok = True
        type_counts = {str(int(k)): int(v) for k, v in zip(*np.unique(initial_type, return_counts=True))}
        mk_counts = {str(int(k)): int(v) for k, v in zip(*np.unique(initial_mk, return_counts=True))}
        initial_counts_ok = (type_counts == {str(k): v for k, v in EXPECTED_COUNTS.items()}
                             and mk_counts == {str(k): v for k, v in EXPECTED_MK.items()})
        require(initial_counts_ok, f"native type/Mk counts mismatch: type={type_counts} mk={mk_counts}")
        finite_numeric(frame_slice(h5["initial_mass"], 0, frames, particles), "initial_mass")
        require(bool(np.all(frame_slice(h5["initial_mass"], 0, frames, particles) > 0)),
                "initial mass is not positive")
        previous_valid: np.ndarray | None = None
        ever_excluded = np.zeros(particles, dtype=bool)
        body_mask = initial_type == 2
        mass_sum_by_type: dict[str, float] = {}
        for frame in range(frames):
            valid_raw = frame_slice(h5["valid"], frame, frames, particles)
            finite_numeric(valid_raw, f"valid[{frame}]")
            valid_values = np.asarray(valid_raw)
            require(bool(np.all((valid_values == 0) | (valid_values == 1))),
                    f"valid mask contains values other than 0/1 at frame {frame}")
            valid = valid_values.astype(bool, copy=False)
            active_count = int(np.count_nonzero(valid))
            excluded = ~valid
            excluded_count = int(np.count_nonzero(excluded))
            lifecycle_consistent = lifecycle_consistent and active_count + excluded_count == particles
            excluded_digest = uid_digest(particle_zone[excluded], particle_id[excluded])
            newly_excluded = excluded if previous_valid is None else excluded & previous_valid
            reentered = np.zeros(particles, dtype=bool) if previous_valid is None else valid & ~previous_valid
            ever_excluded |= excluded
            pos = frame_slice(position, frame, frames, particles)
            vel = frame_slice(h5["velocity"], frame, frames, particles)
            require(tuple(pos.shape) == (particles, 3), f"position frame shape mismatch at {frame}")
            require(tuple(vel.shape) == (particles, 3), f"velocity frame shape mismatch at {frame}")
            finite_active(pos, valid, f"position[{frame}]")
            finite_active(vel, valid, f"velocity[{frame}]")
            finite_active_all = finite_active_all and bool(np.all(np.isfinite(pos[valid]))) and bool(np.all(np.isfinite(vel[valid])))
            per_frame: dict[str, Any] = {
                "frame": frame, "time_s": float(times[frame]),
                "active_count": active_count, "excluded_count": excluded_count,
                "excluded_uid_sha256": excluded_digest,
                "newly_excluded_count": int(np.count_nonzero(newly_excluded)),
                "reentered_count": int(np.count_nonzero(reentered)),
                "position_range_m": ranges(pos[valid], f"position[{frame}]") if active_count else {"min": None, "max": None},
                "velocity_range_m_s": ranges(vel[valid], f"velocity[{frame}]") if active_count else {"min": None, "max": None},
            }
            for name in ("density", "pressure", "mass"):
                values = frame_slice(h5[name], frame, frames, particles)
                finite_active(values, valid, f"{name}[{frame}]")
                if name == "mass":
                    positive = bool(np.all(values[valid] > 0))
                    mass_positive_all = mass_positive_all and positive
                    require(positive, f"mass is non-positive at frame {frame}")
                    for type_code in EXPECTED_COUNTS:
                        selected = valid & (initial_type == type_code)
                        mass_sum_by_type[str(type_code)] = mass_sum_by_type.get(str(type_code), 0.0) + float(np.sum(values[selected]))
                if name == "density":
                    require(bool(np.all(values[valid] > 0)), f"density is non-positive at frame {frame}")
            current_type = integer_values(frame_slice(h5["type"], frame, frames, particles), f"type[{frame}]")
            current_mk = integer_values(frame_slice(h5["initial_mk"], frame, frames, particles), f"initial_mk[{frame}]")
            require(bool(np.array_equal(current_type[valid], initial_type[valid])),
                    f"active native type changed at frame {frame}")
            require(bool(np.array_equal(current_mk[valid], initial_mk[valid])),
                    f"active native Mk changed at frame {frame}")
            body_active = valid & body_mask
            per_frame["floating_position_range_m"] = ranges(pos[body_active], f"floating position[{frame}]") if np.any(body_active) else {"min": None, "max": None}
            per_frame["floating_velocity_range_m_s"] = ranges(vel[body_active], f"floating velocity[{frame}]") if np.any(body_active) else {"min": None, "max": None}
            previous_valid = valid.copy()
            frame_reports.append(per_frame)
        require(frame_reports[0]["active_count"] == particles, "frame zero excludes native particles")
        attrs = {str(k): attr_text(v) for k, v in h5.attrs.items()}
        attr_condition = attrs.get("physical_condition_sha256")
        expected_producer_scope = case["typed_terminal_dependency"]["producer_physical_condition_sha256"]
        require(attr_condition == expected_producer_scope, "H5 physical condition attribute mismatch with producer scope")
        attr_identity = attrs.get("identity_key")
        if attr_identity is not None:
            require(attr_identity in ("(Zone,Idp)", "Zone,Idp", "particle_zone,particle_id"),
                    f"unexpected H5 identity key: {attr_identity}")

    checks.update({
        "producer_report_completed_and_partvtk_passed": True,
        "frames_241_time_0_to_12_step_0p05": time_ok,
        "required_h5_datasets_and_shapes": schema_ok,
        "native_uid_zone_id_unique": initial_uid_ok,
        "native_type_and_mk_counts": initial_counts_ok,
        "active_state_finite_all_frames": finite_active_all,
        "active_mass_positive_all_frames": mass_positive_all,
        "valid_exclusion_lifecycle_conserved": lifecycle_consistent,
        "h5_physical_condition_attribute_matches_owner": True,
        "independent_floatinginfo_state0_pass": True,
    })
    result = {
        "schema": SCHEMA, "status": "pass" if all(checks.values()) else "fail",
        "case_id": case["case_id"], "physical_case_id": case["physical_case_id"],
        "source_canonical_physical_condition_sha256": case["physical_condition_sha256"],
        "producer_physical_condition_sha256": case["typed_terminal_dependency"]["producer_physical_condition_sha256"],
        "typed_execution_receipt": {"path": str(typed_receipt_path), "sha256": metadata_sha(typed_receipt_path), "status": receipt.get("status"), "returncode": receipt.get("returncode")},
        "conversion_report": {"path": str(report_path), "sha256": metadata_sha(report_path), **producer},
        "trajectory_h5": {"path": str(h5_path), "sha256": None, "hash_policy": "producer attestation only; this worker does not hash raw H5"},
        "native_contract": expected,
        "identity": {"key": "(Zone,Idp)", "particle_count": int(expected["total"]), "type_counts": {str(k): int(v) for k, v in EXPECTED_COUNTS.items()}, "mk_counts": {str(k): int(v) for k, v in EXPECTED_MK.items()}},
        "mass_policy": case["mass_policy"],
        "mass_sum_by_type_accumulated_kg": mass_sum_by_type,
        "lifecycle": {"frames": frame_reports, "ever_excluded_count": int(np.count_nonzero(ever_excluded)), "policy": "record actual valid/excluded lifecycle; do not supplement excluded particles"},
        "motion_range": {"policy": "report-only structural range; no precision/convergence gate", "tank_bounds_m": [[0.0, 0.0, 0.0], [4.8, 2.4, 2.4]], "frame_reports": frame_reports},
        "checks": checks, "state0_dependency": state0,
        "claim_boundary": "Per-case typed H5 structural/lifecycle/motion audit only; no numerical convergence, Q-N, visual, or production approval.",
        "trajectory_h5_sha256": None,
    }
    (output_dir / "full241-h5-integrity-audit.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = audit_h5(json.loads(args.request.read_text(encoding="utf-8")), args.output_dir)
    except (AuditError, OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"fresh094 audit failed: {exc}") from exc
    print(json.dumps({"status": result["status"], "case_id": result["case_id"], "report": str(args.output_dir / "full241-h5-integrity-audit.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

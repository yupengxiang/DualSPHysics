#!/usr/bin/env python3
"""Audit one completed historical F3 typed product without reconversion.

The audit reads the immutable direct HDF5, native-label HDF5, receipts and
reports.  It checks source hashes, 3-D typed identity closure, native mass and
units, label closure, and preview provenance.  It deliberately leaves Q-I,
Q-N, and production decisions to the campaign gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np


SCHEMA = "ds02.f3.historical-cell3-qi-audit.v1"
REQUIRED_TRAJECTORY = (
    "time",
    "particle_id",
    "particle_zone",
    "valid",
    "position",
    "velocity",
    "density",
    "mass",
    "pressure",
    "type",
    "mk",
    "initial_type",
    "initial_mk",
    "initial_mass",
)
REQUIRED_LABELS = (
    "time",
    "particle_id",
    "particle_zone",
    "destination_time_series",
    "final_category",
    "failure_reason",
    "initial_fluid_mass_kg",
    "invalid_state_mass_kg",
    "numerical_loss_mass_kg",
    "unknown_mass_kg",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, role: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{role} missing: {path}")
    return path


def json_load(path: Path, role: str) -> dict[str, Any]:
    value = json.loads(require(path, role).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{role} is not a JSON object: {path}")
    return value


def text_attr(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, np.generic):
        return value.item()
    return value


def jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def file_binding(path: Path, role: str) -> dict[str, Any]:
    path = require(path, role)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path), "role": role}


def fail(checks: list[dict[str, Any]], name: str, detail: Any) -> None:
    checks.append({"name": name, "status": "fail", "detail": detail})


def passed(checks: list[dict[str, Any]], name: str, detail: Any) -> None:
    checks.append({"name": name, "status": "pass", "detail": detail})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--labels-receipt", type=Path, required=True)
    parser.add_argument("--preview-report", type=Path, required=True)
    parser.add_argument("--preview-receipt", type=Path, required=True)
    parser.add_argument("--owner", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = require(args.source, "direct HDF5")
    source_report = json_load(args.source_report, "direct conversion report")
    source_receipt = json_load(args.source_receipt, "direct conversion receipt")
    labels = require(args.labels, "labels HDF5")
    labels_receipt = json_load(args.labels_receipt, "labels receipt")
    preview_report = json_load(args.preview_report, "preview report")
    preview_receipt = json_load(args.preview_receipt, "preview receipt")
    owner = json_load(args.owner, "owner metadata")

    checks: list[dict[str, Any]] = []
    bindings = {
        "source_hdf5": file_binding(source, "direct typed HDF5"),
        "source_report": file_binding(args.source_report, "direct conversion report"),
        "source_receipt": file_binding(args.source_receipt, "direct conversion receipt"),
        "labels_hdf5": file_binding(labels, "native labels HDF5"),
        "labels_receipt": file_binding(args.labels_receipt, "native labels receipt"),
        "preview_report": file_binding(args.preview_report, "preview report"),
        "preview_receipt": file_binding(args.preview_receipt, "preview receipt"),
        "owner_metadata": file_binding(args.owner, "owner metadata"),
    }

    if source_receipt.get("status") == "completed" and source_receipt.get("returncode") == 0:
        passed(checks, "direct_receipt_terminal", {"status": source_receipt.get("status"), "returncode": source_receipt.get("returncode")})
    else:
        fail(checks, "direct_receipt_terminal", {"status": source_receipt.get("status"), "returncode": source_receipt.get("returncode")})
    if labels_receipt.get("status") == "completed" and labels_receipt.get("returncode") == 0:
        passed(checks, "labels_receipt_terminal", {"status": labels_receipt.get("status"), "returncode": labels_receipt.get("returncode")})
    else:
        fail(checks, "labels_receipt_terminal", {"status": labels_receipt.get("status"), "returncode": labels_receipt.get("returncode")})
    if preview_receipt.get("status") == "completed" and preview_receipt.get("returncode") == 0:
        passed(checks, "preview_receipt_terminal", {"status": preview_receipt.get("status"), "returncode": preview_receipt.get("returncode")})
    else:
        fail(checks, "preview_receipt_terminal", {"status": preview_receipt.get("status"), "returncode": preview_receipt.get("returncode")})

    source_sha = bindings["source_hdf5"]["sha256"]
    if source_report.get("output_sha256") == source_sha:
        passed(checks, "source_report_output_hash", source_sha)
    else:
        fail(checks, "source_report_output_hash", {"report": source_report.get("output_sha256"), "actual": source_sha})
    raw_tree = source_report.get("source_provenance", {}).get("raw_tree", {})
    if raw_tree.get("unchanged") is True:
        passed(checks, "raw_tree_unchanged", True)
    else:
        fail(checks, "raw_tree_unchanged", raw_tree)

    trajectory: dict[str, Any] = {}
    with h5py.File(source, "r") as h5:
        missing = [name for name in REQUIRED_TRAJECTORY if name not in h5]
        if missing:
            fail(checks, "trajectory_required_datasets", missing)
            raise ValueError(f"trajectory missing datasets: {missing}")
        attrs = {key: text_attr(value) for key, value in h5.attrs.items()}
        frames, particles = h5["valid"].shape
        expected_shapes = {
            "time": (frames,),
            "particle_id": (particles,),
            "particle_zone": (particles,),
            "position": (frames, particles, 3),
            "velocity": (frames, particles, 3),
            "density": (frames, particles),
            "mass": (frames, particles),
            "pressure": (frames, particles),
            "type": (frames, particles),
            "mk": (frames, particles),
            "valid": (frames, particles),
            "initial_type": (particles,),
            "initial_mk": (particles,),
            "initial_mass": (particles,),
        }
        shape_errors = {name: [list(h5[name].shape), list(shape)] for name, shape in expected_shapes.items() if h5[name].shape != shape}
        if shape_errors:
            fail(checks, "trajectory_shapes", shape_errors)
        else:
            passed(checks, "trajectory_shapes", {"frames": frames, "particles": particles})
        if attrs.get("schema") == "ds-data-02.hdf5-schema.v1" and int(attrs.get("solver_dimension", 0)) == 3:
            passed(checks, "trajectory_schema_3d", {"schema": attrs.get("schema"), "solver_dimension": attrs.get("solver_dimension")})
        else:
            fail(checks, "trajectory_schema_3d", {"schema": attrs.get("schema"), "solver_dimension": attrs.get("solver_dimension")})
        try:
            units = json.loads(str(attrs.get("units_json", "{}")))
        except json.JSONDecodeError:
            units = {}
        required_units = {"density": "kg/m^3", "mass": "kg", "position": "m", "pressure": "Pa", "time": "s", "velocity": "m/s"}
        if units == required_units:
            passed(checks, "trajectory_units", units)
        else:
            fail(checks, "trajectory_units", {"actual": units, "expected": required_units})

        particle_id = h5["particle_id"][:]
        particle_zone = h5["particle_zone"][:]
        initial_type = h5["initial_type"][:]
        initial_mk = h5["initial_mk"][:]
        initial_mass = h5["initial_mass"][:].astype(np.float64)
        identity_unique = len(np.unique(np.stack((particle_zone, particle_id), axis=1), axis=0)) == particles
        if identity_unique:
            passed(checks, "typed_identity_unique", {"key": "(Zone,Idp)", "particles": particles})
        else:
            fail(checks, "typed_identity_unique", {"particles": particles})
        type_counts = {str(int(value)): int(np.sum(initial_type == value)) for value in np.unique(initial_type)}
        if type_counts == {"0": 73440, "3": 34560}:
            passed(checks, "initial_typed_counts", type_counts)
        else:
            fail(checks, "initial_typed_counts", type_counts)
        initial_fluid = initial_type == 3
        target_fluid_mass = float(initial_mass[initial_fluid].sum(dtype=np.float64))
        expected_fluid_mass = 14.58
        mass_relative_error = (target_fluid_mass - expected_fluid_mass) / expected_fluid_mass
        fluid_mass_min = float("inf")
        fluid_mass_max = float("-inf")
        valid_min = particles
        valid_max = 0
        type_drift = 0
        mk_drift = 0
        nonfinite_frames = 0
        position_min = np.full(3, np.inf)
        position_max = np.full(3, -np.inf)
        for start in range(0, frames, 16):
            stop = min(frames, start + 16)
            valid = h5["valid"][start:stop]
            particle_type = h5["type"][start:stop]
            particle_mk = h5["mk"][start:stop]
            frame_mass = h5["mass"][start:stop].astype(np.float64)
            valid_counts = valid.sum(axis=1)
            valid_min = min(valid_min, int(valid_counts.min()))
            valid_max = max(valid_max, int(valid_counts.max()))
            type_drift += int(np.count_nonzero(particle_type != initial_type[None, :]))
            mk_drift += int(np.count_nonzero(particle_mk != initial_mk[None, :]))
            fluid_mass = frame_mass[:, initial_fluid].sum(axis=1, dtype=np.float64)
            fluid_mass_min = min(fluid_mass_min, float(fluid_mass.min()))
            fluid_mass_max = max(fluid_mass_max, float(fluid_mass.max()))
            for name in ("mass", "density", "pressure", "position", "velocity"):
                if not np.isfinite(h5[name][start:stop]).all():
                    nonfinite_frames += 1
                    break
            positions = h5["position"][start:stop]
            position_min = np.minimum(position_min, positions.min(axis=(0, 1)))
            position_max = np.maximum(position_max, positions.max(axis=(0, 1)))
        if valid_min == particles and valid_max == particles:
            passed(checks, "valid_identity_closure", {"frames": frames, "valid_per_frame": particles})
        else:
            fail(checks, "valid_identity_closure", {"valid_min": valid_min, "valid_max": valid_max, "particles": particles})
        if type_drift == 0 and mk_drift == 0:
            passed(checks, "typed_state_closure", {"type_drift_entries": 0, "mk_drift_entries": 0})
        else:
            fail(checks, "typed_state_closure", {"type_drift_entries": type_drift, "mk_drift_entries": mk_drift})
        if nonfinite_frames == 0:
            passed(checks, "native_numeric_finiteness", {"frames": frames, "fields": ["mass", "density", "pressure", "position", "velocity"]})
        else:
            fail(checks, "native_numeric_finiteness", {"nonfinite_chunk_count": nonfinite_frames})
        trajectory = {
            "attrs": attrs,
            "frames": int(frames),
            "particles": int(particles),
            "time_start_s": float(h5["time"][0]),
            "time_end_s": float(h5["time"][-1]),
            "initial_type_counts": type_counts,
            "initial_fluid_mass_kg": target_fluid_mass,
            "initial_fluid_mass_relative_error": mass_relative_error,
            "fluid_mass_min_kg": fluid_mass_min,
            "fluid_mass_max_kg": fluid_mass_max,
            "position_min_m": position_min.tolist(),
            "position_max_m": position_max.tolist(),
        }
        if abs(mass_relative_error) <= 0.01:
            passed(checks, "initial_mass_budget", {"mass_kg": target_fluid_mass, "relative_error": mass_relative_error, "budget": 0.01})
        else:
            fail(checks, "initial_mass_budget", {"mass_kg": target_fluid_mass, "relative_error": mass_relative_error, "budget": 0.01})

    labels_summary: dict[str, Any] = {}
    with h5py.File(labels, "r") as h5:
        missing = [name for name in REQUIRED_LABELS if name not in h5]
        if missing:
            fail(checks, "labels_required_datasets", missing)
            raise ValueError(f"labels missing datasets: {missing}")
        attrs = {key: text_attr(value) for key, value in h5.attrs.items()}
        if attrs.get("schema") == "ds-data-02.native-labels.v1" and attrs.get("model_invoked") is False:
            passed(checks, "labels_schema_no_model", {"schema": attrs.get("schema"), "model_invoked": attrs.get("model_invoked")})
        else:
            fail(checks, "labels_schema_no_model", {"schema": attrs.get("schema"), "model_invoked": attrs.get("model_invoked")})
        source_attr = attrs.get("source_hdf5_sha256")
        if source_attr == source_sha:
            passed(checks, "labels_source_hash", source_sha)
        else:
            fail(checks, "labels_source_hash", {"labels": source_attr, "direct": source_sha})
        frames, particles = trajectory["frames"], trajectory["particles"]
        shape_errors = {}
        for name, shape in {"time": (frames,), "particle_id": (particles,), "particle_zone": (particles,), "destination_time_series": (frames, particles), "initial_fluid_mass_kg": (particles,)}.items():
            if h5[name].shape != shape:
                shape_errors[name] = [list(h5[name].shape), list(shape)]
        if shape_errors:
            fail(checks, "labels_shapes", shape_errors)
        else:
            passed(checks, "labels_shapes", {"frames": frames, "particles": particles})
        codes = np.unique(h5["destination_time_series"][:])
        allowed_codes = {-3, -2, -1, 0, 1, 2}
        if set(int(value) for value in codes).issubset(allowed_codes):
            passed(checks, "labels_destination_codes", [int(value) for value in codes])
        else:
            fail(checks, "labels_destination_codes", [int(value) for value in codes])
        for name in ("invalid_state_mass_kg", "numerical_loss_mass_kg", "unknown_mass_kg", "initial_fluid_mass_kg"):
            values = h5[name][:]
            if np.isfinite(values).all() and np.all(values >= -1e-12):
                continue
            fail(checks, f"labels_{name}_finite_nonnegative", {"min": float(np.nanmin(values)), "max": float(np.nanmax(values))})
        labels_summary = {
            "attrs": attrs,
            "destination_codes": [int(value) for value in codes],
            "unknown_mass_max_kg": float(np.max(h5["unknown_mass_kg"][:])),
            "numerical_loss_mass_max_kg": float(np.max(h5["numerical_loss_mass_kg"][:])),
            "invalid_state_mass_max_kg": float(np.max(h5["invalid_state_mass_kg"][:])),
            "unresolved_interval_time_max_s": float(np.max(h5["unresolved_interval_time_s"][:])) if "unresolved_interval_time_s" in h5 else None,
        }

    preview_source = preview_report.get("source_sha256")
    if preview_source == source_sha and preview_report.get("frames") == trajectory["frames"] and preview_report.get("particles") == trajectory["particles"]:
        passed(checks, "preview_source_closure", {"source_sha256": preview_source, "frames": preview_report.get("frames"), "particles": preview_report.get("particles")})
    else:
        fail(checks, "preview_source_closure", {"source_sha256": preview_source, "frames": preview_report.get("frames"), "particles": preview_report.get("particles")})
    if preview_report.get("visual_decimation_only") is True and preview_report.get("numerical_qualification") == "not_assessed":
        passed(checks, "preview_semantics", {"visual_decimation_only": True, "numerical_qualification": "not_assessed"})
    else:
        fail(checks, "preview_semantics", {"visual_decimation_only": preview_report.get("visual_decimation_only"), "numerical_qualification": preview_report.get("numerical_qualification")})

    owner_source = owner.get("source", {})
    owner_xml = owner_source.get("generated_xml", {})
    owner_control = owner_source.get("control", {})
    xml_path = Path(owner_xml.get("path", ""))
    control_path = Path(owner_control.get("path", ""))
    source_binding = {}
    if xml_path.is_file():
        actual = sha256(xml_path)
        source_binding["generated_xml"] = {"path": str(xml_path), "registered": owner_xml.get("sha256"), "actual": actual, "match": actual == owner_xml.get("sha256")}
    if control_path.is_file():
        actual = sha256(control_path)
        source_binding["control"] = {"path": str(control_path), "registered": owner_control.get("sha256"), "actual": actual, "match": actual == owner_control.get("sha256")}
    for name, value in source_binding.items():
        if value["match"]:
            passed(checks, f"owner_{name}_hash", value)
        else:
            fail(checks, f"owner_{name}_hash", value)

    failed = [check for check in checks if check["status"] == "fail"]
    report = {
        "schema": SCHEMA,
        "status": "completed_pass" if not failed else "completed_review_required",
        "case_id": owner.get("physical_case_id"),
        "family_id": "F3",
        "scope": "historical fixed CELL3 plain source/product QI evidence only",
        "source_bindings": bindings,
        "trajectory": trajectory,
        "labels": labels_summary,
        "preview": {
            "report_status": preview_report.get("status"),
            "preview_sha256": preview_report.get("preview_sha256"),
            "selected_frames": preview_report.get("selected_frames"),
            "visual_decimation_only": preview_report.get("visual_decimation_only"),
        },
        "owner_source_binding": source_binding,
        "checks": checks,
        "claim_boundary": {
            "q_i_status": "audit evidence only; campaign Q-I gate remains external",
            "q_n_status": "not_assessed",
            "production_eligibility": "not_evaluated",
            "model_invoked": False,
            "hidden_subframe_crossings": "unresolved by saved-frame chord labels",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=jsonable) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "failed_checks": len(failed), "output": str(args.output)}))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())

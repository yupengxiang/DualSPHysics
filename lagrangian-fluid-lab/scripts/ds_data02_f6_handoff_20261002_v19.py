#!/usr/bin/env python3
"""F6 additive native conversion that preserves solver exclusions.

The integration Stage 8 converter intentionally requires a fixed identity set.
The RIGID003 medium solver has one native ``NpOutPos`` event, so that converter
cannot materialize the complete twelve-second record.  This F6-local wrapper
keeps the initial native Idp axis, writes missing rows as ``valid=false`` and
NaN, and records the first missing frame and native role.  It never edits the
solver tree and never starts a solver or GPU job.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    import h5py
    import numpy as np
except (ImportError, OSError, ValueError):  # system Python may have an ABI-incompatible h5py
    h5py = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]


SCRIPT = Path(__file__).resolve()
V16 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v16.py")
V18 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v18.py")
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
VENV_PYTHON = INTEGRATION_LAB / ".venv/bin/python"
CONVERTER = INTEGRATION_LAB / "scripts/ds_data02_f6_stage8_convert.py"
BASE_SPEC = importlib.util.spec_from_file_location("f6_stage8_converter_v19_base", CONVERTER)
if BASE_SPEC is None or BASE_SPEC.loader is None:
    raise RuntimeError(f"cannot load integration converter: {CONVERTER}")
BASE = None
if h5py is not None and np is not None:
    BASE = importlib.util.module_from_spec(BASE_SPEC)
    BASE_SPEC.loader.exec_module(BASE)

V16_SPEC = importlib.util.spec_from_file_location("f6_handoff_v16_for_sparse_conversion", V16)
if V16_SPEC is None or V16_SPEC.loader is None:
    raise RuntimeError(f"cannot load frozen v16 module: {V16}")
V16_MODULE = importlib.util.module_from_spec(V16_SPEC)
V16_SPEC.loader.exec_module(V16_MODULE)

V18_SPEC = importlib.util.spec_from_file_location("f6_handoff_v18_for_sparse_requests", V18)
if V18_SPEC is None or V18_SPEC.loader is None:
    raise RuntimeError(f"cannot load frozen v18 module: {V18}")
V18_MODULE = importlib.util.module_from_spec(V18_SPEC)
V18_SPEC.loader.exec_module(V18_MODULE)

FAMILY_ROOT = V16_MODULE.FAMILY_ROOT
RAW_ROOT = V16_MODULE.RAW_ROOT
POST_ROOT = FAMILY_ROOT / "postprocessing_004"
REQUEST_ROOT = POST_ROOT / "execution_requests"
SIMPLE_LABEL_CONFIG = V16_MODULE.SIMPLE_LABEL_CONFIG
WAVE_LABEL_CONFIG = V16_MODULE.WAVE_LABEL_CONFIG


def sha256(path: Path) -> str:
    return V16_MODULE.sha256(path)


def read_json(path: Path) -> dict[str, Any]:
    return V16_MODULE.read_json(path)


def write_json(path: Path, value: Any) -> None:
    V16_MODULE.MODULE.write_json(path, value)


def _source_motion_csv(mechanism: str) -> Path:
    case = V16_MODULE._old_medium_case(mechanism)
    case_id = str(case["case_id"])
    path = RAW_ROOT / case_id / f"{case_id}_FLOATINGINFO_001/floatinginfo/FloatingMotion_mk60.csv"
    if not path.is_file():
        raise FileNotFoundError(f"completed FloatingInfo CSV missing: {path}")
    return path


def _source_inputs(row: dict[str, Any], mechanism: str) -> tuple[dict[str, Path], list[Path], Path]:
    """Return immutable native inputs, keeping the venv symlink literal."""

    paths = V16_MODULE._old_medium_paths(V16_MODULE._old_medium_case(mechanism))
    inputs = V16_MODULE._post_common_inputs(row)
    config = SIMPLE_LABEL_CONFIG if mechanism == "simple_free_response" else WAVE_LABEL_CONFIG
    motion_csv = _source_motion_csv(mechanism)
    inputs.extend([SCRIPT, V16, V18, VENV_PYTHON, CONVERTER, V16_MODULE.NATIVE_LABELS, config, motion_csv])
    unique: list[Path] = []
    seen: set[str] = set()
    for value in inputs:
        path = Path(value)
        # Path.resolve() on this installation follows the venv symlink to the
        # system interpreter.  Preserve the literal path in provenance.
        key = str(path) if path == VENV_PYTHON else str(path.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(path)
    missing = [str(path) for path in unique if not path.is_file()]
    if missing:
        raise FileNotFoundError("sparse conversion input missing: " + ", ".join(missing))
    return paths, unique, motion_csv


def prepare() -> dict[str, Any]:
    """Prepare additive sparse conversion and deferred label requests."""

    audit = read_json(V16_MODULE.MEDIUM_AUDIT_PATH)
    rows = audit.get("cases", [])
    if len(rows) != 2 or not all(row.get("postprocessing_ready") for row in rows):
        raise RuntimeError("medium terminal audit is not ready")
    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    requests: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {
        "schema": "ds-data-02.f6.rigid003.postprocessing_004.sparse_conversion_retry_001.v1",
        "family_id": "F6",
        "source_failed_attempt": "NATIVE_H5_002",
        "source_failure": "fixed identity set changed at Part_0009.bi4 because RunPARTs recorded a native position exclusion",
        "repair": "retain initial native Idp axis, fill missing frame rows as invalid/NaN, and preserve first-missing role/time ledger",
        "old_attempts_immutable": True,
        "gpu_launch": False,
        "q_n_status": "pending_native_exclusion_reconciliation",
    }
    for row in rows:
        mechanism = str(row["mechanism_id"])
        case = V16_MODULE._old_medium_case(mechanism)
        paths, inputs, motion_csv = _source_inputs(row, mechanism)
        cid = str(case["case_id"])
        conversion_attempt = f"{cid}_NATIVE_H5_003"
        output = RAW_ROOT / cid / conversion_attempt / "trajectory.h5"
        report = RAW_ROOT / cid / conversion_attempt / "conversion-report.json"
        # Keep the venv symlink literal in both argv and provenance.  Other
        # inputs are canonicalized for the runner's immutable hash map.
        input_strings = [str(path) if path == VENV_PYTHON else str(path.resolve()) for path in inputs]
        input_hashes = {key: sha256(Path(key)) for key in input_strings}
        common: dict[str, Any] = {
            "schema": "ds-data-02.runner.request.v1",
            "family_id": "F6",
            "case_id": cid,
            "mechanism_id": mechanism,
            "resolution_id": "medium",
            "kind": "cpu",
            "cpu_task_kind": "conversion",
            "cpu_threads": 4,
            "max_wall_seconds": 1800,
            "estimated_storage_bytes": 2147483648,
            "input_files": input_strings,
            "input_hashes_at_request": input_hashes,
            "worktree_root": str(V16_MODULE.MODULE.REPO_ROOT.resolve()),
            "cwd": str(INTEGRATION_LAB),
            "source_raw_tree_manifest": row["native_frames"]["tree_manifest"],
            "source_raw_tree_manifest_sha256": row["native_frames"]["tree_manifest_sha256"],
            "source_solver_attempt": row["solver_receipt"]["path"],
            "source_solver_receipt_sha256": row["solver_receipt"]["sha256"],
            "supersedes_attempt": f"{cid}_NATIVE_H5_002",
            "retry_root_cause": evidence["source_failure"],
            "conversion_concurrency_note": "one conversion slot; submit only through shared runtime v2",
            "q_n_status": "pending",
            "gpu_launch": False,
        }
        conversion = {
            **common,
            "attempt_id": conversion_attempt,
            "command": [str(VENV_PYTHON), str(SCRIPT), "run-native-conversion", "--case-id", cid, "--data-dir", str(paths["data"].resolve()), "--generated-xml", str(paths["xml"].resolve()), "--motion-csv", str(motion_csv.resolve()), "--manifest", str(Path(row["native_frames"]["tree_manifest"]).resolve()), "--output", "{attempt_root}/trajectory.h5", "--report", "{attempt_root}/conversion-report.json"],
            "purpose": "F6-local sparse native BI4 to HDF5 conversion; preserve exclusions for later PartVTKOut reconciliation",
            "output_contract": {"trajectory": str(output), "report": str(report), "frames": 241, "complete_rigid_state": ["pose", "orientation", "quaternion", "linear_velocity", "angular_velocity", "force", "torque", "massbody", "inertia"], "sparse_validity": "native Idp missing rows are valid=false and NaN"},
            "source_failed_attempt": f"{cid}_NATIVE_H5_002",
        }
        conversion_path = REQUEST_ROOT / f"{cid}_native_h5_003.json"
        write_json(conversion_path, conversion)
        requests.append({"path": str(conversion_path.resolve()), "sha256": sha256(conversion_path), "kind": "conversion", "case_id": cid})

        label_config = SIMPLE_LABEL_CONFIG if mechanism == "simple_free_response" else WAVE_LABEL_CONFIG
        label_attempt = f"{cid}_LABELS_003"
        label_input_strings = input_strings + [str(output.resolve())]
        labels = {
            **common,
            "attempt_id": label_attempt,
            "cpu_task_kind": "labels",
            "cpu_threads": 2,
            "max_wall_seconds": 900,
            "estimated_storage_bytes": 536870912,
            "input_files": label_input_strings,
            "input_hashes_at_request": {key: (sha256(Path(key)) if Path(key).is_file() else "deferred_until_native_h5_003_receipt") for key in label_input_strings},
            "command": [str(VENV_PYTHON), str(SCRIPT), "run-labels", "--source", str(output.resolve()), "--config", str(label_config.resolve()), "--output", "{attempt_root}/native-labels.h5"],
            "purpose": "materialize native event labels after sparse HDF5 conversion succeeds",
            "deferred_until_attempt": conversion_attempt,
            "source_trajectory": str(output.resolve()),
            "source_trajectory_sha256": "deferred_until_native_h5_003_receipt",
            "required_label_semantics": ["fluid_type3_only", "fixed_identity", "finite_saved_frame_chord_events", "mass_ledger", "no_model"],
        }
        labels_path = REQUEST_ROOT / f"{cid}_labels_003.json"
        write_json(labels_path, labels)
        requests.append({"path": str(labels_path.resolve()), "sha256": sha256(labels_path), "kind": "labels", "case_id": cid, "deferred": True})
        evidence.setdefault("cases", []).append({"case_id": cid, "motion_csv": str(motion_csv.resolve()), "motion_csv_sha256": sha256(motion_csv), "supersedes": f"{cid}_NATIVE_H5_002"})

    write_json(POST_ROOT / "sparse_conversion_retry_evidence_001.json", evidence)
    result = {"schema": "ds-data-02.f6.rigid003.postprocessing_004.requests_001.v1", "family_id": "F6", "created_at": V16_MODULE.MODULE.now(), "status": "prepared_pending_shared_conversion_slot", "requests": requests, "conversion_launch": False, "gpu_launch": False, "q_n_status": "pending sparse HDF5, PartVTKOut, and labels"}
    write_json(POST_ROOT / "request_manifest.json", result)
    return result


def _align_motion(rigid_data: dict[str, np.ndarray], h5_times: np.ndarray, nframes: int) -> dict[str, np.ndarray]:
    aligned: dict[str, np.ndarray] = {}
    motion_times = rigid_data["time"]
    for key in (
        "position",
        "linear_velocity",
        "angular_velocity",
        "orientation_quaternion",
        "body_quaternion_xyzw",
        "orientation_euler_deg",
        "orientation_euler_rad",
        "surge_sway_heave_m",
        "linear_acceleration",
        "angular_acceleration",
        "fluid_force",
        "fluid_torque",
    ):
        arr = rigid_data[key]
        if len(arr) == nframes and np.allclose(motion_times[:nframes], h5_times, atol=1e-3):
            current = arr[:nframes]
        else:
            current = np.zeros((nframes, arr.shape[1]), dtype=np.float64)
            for dim in range(arr.shape[1]):
                current[:, dim] = np.interp(h5_times, motion_times, arr[:, dim])
            if "quaternion" in key:
                norms = np.linalg.norm(current, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                current = current / norms
        aligned[key] = current
    return aligned


def convert_sparse(
    *,
    case_id: str,
    data_dir: Path,
    generated_xml: Path,
    motion_csv: Path,
    output_h5: Path,
    report_path: Path,
) -> dict[str, Any]:
    """Materialize a native Idp axis with explicit sparse validity."""

    if BASE is None or h5py is None or np is None:
        raise RuntimeError("sparse conversion requires the integration .venv Python with compatible numpy/h5py")
    started = time.monotonic()
    data_dir = data_dir.resolve()
    generated_xml = generated_xml.resolve()
    motion_csv = motion_csv.resolve()
    output_h5 = output_h5.resolve()
    report_path = report_path.resolve()
    output_h5.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    xml_data = BASE.parse_gencase_xml(generated_xml)
    total_particles = int(xml_data["np"])
    groups = xml_data["groups"]
    frame_files = sorted(data_dir.glob("Part_*.bi4"))
    if len(frame_files) < 2:
        raise ValueError(f"fewer than two BI4 frames: {data_dir}")
    nframes = len(frame_files)
    rigid_data = BASE.parse_floating_motion_csv(motion_csv)

    # The initial frame is the immutable native identity cohort.  The XML
    # groups are serialized in Idp order by GenCase, as required by the
    # existing fixed-cohort converter.
    with tempfile.TemporaryDirectory(prefix="f6-sparse-convert-") as temp:
        initial_ids, _, _, _, _ = BASE._decode_bi4_frame(frame_files[0], Path(temp))
        if len(initial_ids) != total_particles or not np.array_equal(initial_ids, np.arange(total_particles, dtype=np.uint32)):
            raise ValueError("initial native Idp axis is not the XML 0..N-1 cohort")

    particle_ids = initial_ids.astype(np.uint32, copy=True)
    particle_zone = np.zeros(total_particles, dtype=np.int16)
    particle_type = np.zeros(total_particles, dtype=np.int8)
    particle_mk = np.zeros(total_particles, dtype=np.int16)
    mass_template = np.full(total_particles, xml_data["massfluid"], dtype=np.float32)
    role_by_id = np.full(total_particles, "unknown", dtype=object)
    for group in groups:
        begin = int(group["begin"])
        count = int(group["count"])
        end = begin + count
        particle_type[begin:end] = int(group["type"])
        particle_mk[begin:end] = int(group["mk"])
        role_by_id[begin:end] = str(group["role"])
        if group["role"] != "fluid":
            mass_template[begin:end] = xml_data["massbound"]

    partial_h5 = output_h5.with_suffix(output_h5.suffix + ".partial")
    if partial_h5.exists():
        partial_h5.unlink()
    chunk_size = min(total_particles, 65536)
    missing_by_frame: list[dict[str, Any]] = []
    first_missing: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(prefix="f6-sparse-convert-") as temp_dir:
        temp_path = Path(temp_dir)
        with h5py.File(partial_h5, "w") as h5:
            h5.attrs["schema"] = "ds-data-02.hdf5-schema.v1"
            h5.attrs["family_id"] = "F6"
            h5.attrs["case_id"] = case_id
            h5.attrs["time_units"] = "s"
            h5.attrs["position_units"] = "m"
            h5.attrs["velocity_units"] = "m/s"
            h5.attrs["density_units"] = "kg/m^3"
            h5.attrs["mass_units"] = "kg"
            h5.attrs["pressure_units"] = "Pa"
            h5.attrs["coordinate_frame"] = "world_tank_and_tank_attached_observations" if "wave" in case_id.lower() else "tank_attached_inertial"
            h5.attrs["generated_xml_sha256"] = BASE.sha256_file(generated_xml)
            h5.attrs["generated_xml"] = str(generated_xml)
            if xml_data["massbody_kg"] is not None:
                h5.attrs["floating_massbody_kg"] = float(xml_data["massbody_kg"])
            if xml_data["masspart_kg"] is not None:
                h5.attrs["floating_masspart_kg"] = float(xml_data["masspart_kg"])
            if xml_data["floating_inertia_kg_m2"] is not None:
                h5.attrs["floating_inertia_kg_m2"] = json.dumps(xml_data["floating_inertia_kg_m2"], separators=(",", ":"))
            h5.attrs["orientation_semantics"] = "FloatingInfo roll/pitch/yaw intrinsic XYZ and xyzw unit quaternion"
            h5.attrs["particle_identity"] = "native Idp"
            h5.attrs["identity_key"] = "(Zone,Idp)"
            h5.attrs["geometry"] = "F6_BOX_TANK_FREE_BODY" if "simple" in case_id.lower() else "F6_BOX_TANK_WAVE_PADDLE"
            h5.attrs["control"] = "F6_CTRL_INITIAL_RELEASE" if "simple" in case_id.lower() else "F6_CTRL_REGULAR_PISTON_WAVE"
            h5.attrs["boundary_mode"] = "closed_system"
            h5.attrs["closed_system"] = True
            h5.attrs["lifecycle_mode"] = "native_sparse_cohort"
            h5.attrs["rigid_body_state"] = "/rigid_body"
            h5.attrs["solver_dimension"] = 3

            h5.create_dataset("particle_id", data=particle_ids, dtype="u4")
            h5.create_dataset("particle_zone", data=particle_zone, dtype="i2")
            h5.create_dataset("initial_type", data=particle_type, dtype="i1")
            h5.create_dataset("initial_mk", data=particle_mk, dtype="i2")
            h5.create_dataset("initial_mass", data=mass_template, dtype="f4")
            h5.create_dataset("time", shape=(nframes,), dtype="f8")
            h5.create_dataset("valid", shape=(nframes, total_particles), dtype="bool", chunks=(1, chunk_size), compression="lzf", fillvalue=False)
            h5.create_dataset("type", data=np.broadcast_to(particle_type, (nframes, total_particles)), dtype="i1", chunks=(1, chunk_size), compression="lzf")
            h5.create_dataset("mk", data=np.broadcast_to(particle_mk, (nframes, total_particles)), dtype="i2", chunks=(1, chunk_size), compression="lzf")
            h5.create_dataset("position", shape=(nframes, total_particles, 3), dtype="f4", chunks=(1, chunk_size, 3), compression="lzf", fillvalue=np.nan)
            h5.create_dataset("velocity", shape=(nframes, total_particles, 3), dtype="f4", chunks=(1, chunk_size, 3), compression="lzf", fillvalue=np.nan)
            h5.create_dataset("density", shape=(nframes, total_particles), dtype="f4", chunks=(1, chunk_size), compression="lzf", fillvalue=np.nan)
            h5.create_dataset("mass", shape=(nframes, total_particles), dtype="f4", chunks=(1, chunk_size), compression="lzf", fillvalue=np.nan)
            h5.create_dataset("pressure", shape=(nframes, total_particles), dtype="f4", chunks=(1, chunk_size), compression="lzf", fillvalue=np.nan)

            for frame_idx, frame_path in enumerate(frame_files):
                ids, pos, vel, rho, time_s = BASE._decode_bi4_frame(frame_path, temp_path)
                if len(np.unique(ids)) != len(ids):
                    raise ValueError(f"duplicate native Idp at {frame_path.name}")
                indices = np.searchsorted(particle_ids, ids)
                if np.any(indices >= total_particles) or not np.array_equal(particle_ids[indices], ids):
                    raise ValueError(f"introduced native Idp at {frame_path.name}")
                present = np.zeros(total_particles, dtype=bool)
                present[indices] = True
                missing = np.flatnonzero(~present).astype(int).tolist()
                record = {"frame": frame_idx, "file": frame_path.name, "time_s": float(time_s), "missing_count": len(missing), "missing_ids": missing}
                missing_by_frame.append(record)
                if missing and first_missing is None:
                    first_missing = {
                        **record,
                        "missing_roles": {role: sum(role_by_id[i] == role for i in missing) for role in sorted(set(role_by_id))},
                    }
                full_pos = np.full((total_particles, 3), np.nan, dtype=np.float32)
                full_vel = np.full((total_particles, 3), np.nan, dtype=np.float32)
                full_rho = np.full(total_particles, np.nan, dtype=np.float32)
                full_pos[indices] = pos.astype(np.float32)
                full_vel[indices] = vel.astype(np.float32)
                full_rho[indices] = rho.astype(np.float32)
                pressure = np.full(total_particles, np.nan, dtype=np.float32)
                valid = present & np.isfinite(full_rho)
                pressure[valid] = (xml_data["b"] * ((full_rho[valid].astype(np.float64) / xml_data["rhop0"]) ** xml_data["gamma"] - 1.0)).astype(np.float32)
                h5["time"][frame_idx] = time_s
                h5["valid"][frame_idx] = present
                h5["position"][frame_idx] = full_pos
                h5["velocity"][frame_idx] = full_vel
                h5["density"][frame_idx] = full_rho
                h5["pressure"][frame_idx] = pressure
                mass = np.full(total_particles, np.nan, dtype=np.float32)
                mass[present] = mass_template[present]
                h5["mass"][frame_idx] = mass

            h5.attrs["missing_initial_identity_frames"] = int(sum(row["missing_count"] for row in missing_by_frame))
            h5.attrs["first_missing_frame"] = -1 if first_missing is None else int(first_missing["frame"])
            h5.attrs["first_missing_time_s"] = math.nan if first_missing is None else float(first_missing["time_s"])

            rb_group = h5.create_group("rigid_body")
            rb_group.attrs["schema"] = "ds-data-02.f6.rigid-body-state.v1"
            rb_group.attrs["body_name"] = "floating_box"
            rb_group.attrs["mass_kg"] = float(xml_data["massbody_kg"]) if xml_data["massbody_kg"] is not None else float("nan")
            rb_group.attrs["quaternion_convention"] = "xyzw"
            rb_group.attrs["orientation_convention"] = "FloatingInfo roll/pitch/yaw intrinsic XYZ, quaternion xyzw"
            if xml_data["floating_inertia_kg_m2"] is not None:
                rb_group.attrs["inertia_tensor_kg_m2"] = json.dumps(xml_data["floating_inertia_kg_m2"])
            h5_times = h5["time"][:]
            aligned = _align_motion(rigid_data, h5_times, nframes)
            for key, value in aligned.items():
                rb_group.create_dataset(key, data=value, dtype="f8")
            rb_group.create_dataset("contact_event_flag", data=np.zeros(nframes, dtype=bool))
            rs_group = h5.create_group("rigid_state")
            for key in rb_group.keys():
                rs_group[key] = h5py.SoftLink(f"/rigid_body/{key}")
            h5.attrs["conversion_complete"] = True
            h5.attrs["conversion_complete_frames"] = nframes

    partial_h5.replace(output_h5)
    report = {
        "schema": "ds02.f6.sparse-conversion-report.v1",
        "family_id": "F6",
        "case_id": case_id,
        "status": "completed",
        "output_h5": str(output_h5),
        "output_sha256": sha256(output_h5),
        "file_bytes": output_h5.stat().st_size,
        "frames": nframes,
        "particles": total_particles,
        "native_sparse_identity": True,
        "missing_total_frame_identity_rows": int(sum(row["missing_count"] for row in missing_by_frame)),
        "frames_with_missing_identities": int(sum(bool(row["missing_count"]) for row in missing_by_frame)),
        "first_missing": first_missing,
        "missing_by_frame": missing_by_frame,
        "data_dir": str(data_dir),
        "generated_xml": str(generated_xml),
        "generated_xml_sha256": sha256(generated_xml),
        "motion_csv": str(motion_csv),
        "motion_csv_sha256": sha256(motion_csv),
        "elapsed_seconds": time.monotonic() - started,
        "q_n_status": "pending_native_exclusion_reconciliation",
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _verify_tree(manifest: Path, data_dir: Path) -> None:
    V16_MODULE._verify_tree(manifest, data_dir)


def _run_native_conversion(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    manifest = Path(args.manifest).resolve()
    _verify_tree(manifest, data_dir)
    convert_sparse(
        case_id=str(args.case_id),
        data_dir=data_dir,
        generated_xml=Path(args.generated_xml),
        motion_csv=Path(args.motion_csv),
        output_h5=Path(args.output),
        report_path=Path(args.report),
    )
    _verify_tree(manifest, data_dir)
    return 0


def _run_labels(args: argparse.Namespace) -> int:
    return V16_MODULE._run_labels(args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run-native-conversion", "run-labels"])
    parser.add_argument("--case-id")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--motion-csv", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        print(json.dumps(prepare(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "run-native-conversion":
        required = ("case_id", "data_dir", "manifest", "generated_xml", "motion_csv", "output", "report")
        for name in required:
            if getattr(args, name) is None:
                parser.error(f"run-native-conversion requires --{name.replace('_', '-')}")
        return _run_native_conversion(args)
    for name in ("source", "config", "output"):
        if getattr(args, name) is None:
            parser.error(f"run-labels requires --{name}")
    return _run_labels(args)


if __name__ == "__main__":
    raise SystemExit(main())

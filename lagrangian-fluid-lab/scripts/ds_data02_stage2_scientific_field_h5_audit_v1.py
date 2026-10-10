#!/usr/bin/env python3
"""Source-bound, bounded-memory raw-HDF5 field audit.

prepare reads only metadata and file statistics. audit is the guarded worker:
it streams all saved frames in chunks, separates active and inactive
non-finite observations, and preserves UNKNOWN scientific boundaries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any

SCRIPT = Path(__file__).resolve()
PRIMARY_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LAB_ROOT = PRIMARY_ROOT
STAGE2_ROOT = PRIMARY_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT_DEFAULT = STAGE2_ROOT / "CURRENT336.json"
VENV_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
CONFIG_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")
RUNTIME_DEFAULT = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
DISPATCH_DEFAULT = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT_DEFAULT = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
REQUEST_SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.scientific-field-h5-audit-manifest.v1"
REPORT_SCHEMA = "ds02.stage2.scientific-field-h5-audit.v1"
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
DEFAULT_CHUNK = 65536
TYPE_NAMES = {0: "fixed", 1: "moving", 2: "floating", 3: "fluid"}
FRAME_FIELDS = ("position", "velocity", "density", "mass", "pressure", "valid", "type")
FINITE_FIELDS = ("position", "velocity", "density", "mass", "pressure")
UNIT_PROTOCOL = {"position": "m", "velocity": "m/s", "density": "kg/m^3", "mass": "kg", "pressure": "Pa", "time": "s"}
PILOT_DEFAULTS = (
    ("F1", "TYPED_LIFECYCLE_BATCH_F1_ACTUAL_ROOT_VERIFICATION_286.json", "F1_DUAL_HEAD_340_VX_150_FRESH090_V1"),
    ("F2", "TYPED_LIFECYCLE_BATCH_F2_ACTUAL_ROOT_VERIFICATION_289.json", "F2_STAGE1_FIRST8_OFFSET_OPEN_RIM_RX050_RY014_FILL080"),
    ("F3", "TYPED_LIFECYCLE_BATCH_F3_ACTUAL_ROOT_VERIFICATION_294.json", "F3_TWOAXIS_PITCH1000_AY0540_STAGE1_FIRST24_NEW"),
    ("F4", "TYPED_LIFECYCLE_BATCH_F4_ACTUAL_ROOT_VERIFICATION_280.json", "F4_DROP_gap0p24000_xoffm0p08000_yoff0p04000_uz0p60000"),
    ("F5", "TYPED_LIFECYCLE_BATCH_F5_ACTUAL_ROOT_VERIFICATION_302.json", "F5_COMPACT_RUNUP_RECOVERY_C082S1_M110_T100"),
    ("F6", "TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_281.json", "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S130_DP025"),
    ("F7", "TYPED_LIFECYCLE_BATCH_F7_ACTUAL_ROOT_VERIFICATION_304.json", "F7_OBSTACLE_QUINTIC_B08_A036P5"),
)


class H5FieldAuditError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise H5FieldAuditError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise H5FieldAuditError(f"{label} is not hexadecimal")
    return value


def source_path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise H5FieldAuditError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise H5FieldAuditError(f"{label} is missing: {path}")
    return path


def json_object(path: Path, label: str) -> dict[str, Any]:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise H5FieldAuditError(f"{label} exceeds bounded JSON size")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise H5FieldAuditError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise H5FieldAuditError(f"{label} must be an object")
    return value


def stat_ref(path: Path, role: str) -> dict[str, Any]:
    value = path.stat()
    return {
        "role": role, "path": str(path.resolve()), "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev), "st_ino": int(value.st_ino),
    }


def static_ref(path: Path, role: str, expected_sha: str | None = None) -> dict[str, Any]:
    ref = stat_ref(path, role)
    actual = sha256_file(path)
    if expected_sha is not None and actual != require_sha(expected_sha, f"{role} expected SHA"):
        raise H5FieldAuditError(f"{role} changed")
    ref.update({"sha256": actual, "content_read_by_preparer": True})
    return ref


def deferred_ref(path: Path, role: str, expected_sha: str, expected_stat: dict[str, Any]) -> dict[str, Any]:
    ref = stat_ref(path, role)
    for key in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if key in expected_stat and int(expected_stat[key]) != int(ref[key]):
            raise H5FieldAuditError(f"{role} stat changed before reservation: {key}")
    digest = require_sha(expected_sha, f"{role} known SHA")
    ref.update({"sha256": digest, "known_sha256": digest, "deferred_after_reservation": True, "content_read_by_preparer": False})
    return ref


def atomic_json(path: Path, value: dict[str, Any], max_bytes: int = MAX_JSON_BYTES) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise H5FieldAuditError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temp.stat().st_size > max_bytes:
            raise H5FieldAuditError(f"output exceeds bounded JSON size: {path}")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def same_stat(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(left.get(key) == right.get(key) for key in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"))


def dedupe_refs(refs: list[dict[str, Any]]) -> tuple[list[str], dict[str, str]]:
    by_path: dict[str, dict[str, Any]] = {}
    for ref in refs:
        path = str(Path(ref["path"]).resolve())
        if path in by_path and by_path[path]["sha256"] != ref["sha256"]:
            raise H5FieldAuditError(f"conflicting source reference: {path}")
        by_path[path] = {**ref, "path": path}
    paths = sorted(by_path)
    return paths, {path: by_path[path]["sha256"] for path in paths}


def find_case(document: dict[str, Any], case_id: str, key: str) -> dict[str, Any]:
    rows = document.get(key)
    if not isinstance(rows, list):
        raise H5FieldAuditError(f"{key} missing")
    matches = [row for row in rows if isinstance(row, dict) and row.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise H5FieldAuditError(f"case is not unique: {case_id}")
    return matches[0]


def parse_pilot(value: str) -> tuple[str, Path, str]:
    try:
        family, proof, case_id = value.split("|", 2)
    except ValueError as exc:
        raise H5FieldAuditError("--pilot must be FAMILY|PROOF_PATH|CASE_ID") from exc
    return family, source_path(proof, f"{family} proof"), case_id


def default_pilots() -> list[tuple[str, Path, str]]:
    return [(family, STAGE2_ROOT / "checkpoints" / proof, case_id) for family, proof, case_id in PILOT_DEFAULTS]


def proof_case(family: str, proof_path: Path, case_id: str, proof: dict[str, Any], current: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise H5FieldAuditError(f"{case_id}: unexpected proof schema")
    if proof.get("guarded_receipt_status") != "completed" or proof.get("outer_unit_result") != "success":
        raise H5FieldAuditError(f"{case_id}: proof is not completed/successful")
    counts = proof.get("counts")
    if not isinstance(counts, dict) or int(counts.get("failed", -1)) != 0 or int(counts.get("completed", -1)) != int(counts.get("cases_requested", -2)):
        raise H5FieldAuditError(f"{case_id}: proof has failed cases")
    row = find_case(proof, case_id, "case_verifications")
    current_row = find_case(current, case_id, "cases")
    if row.get("family_id") != family or current_row.get("family_id") != family:
        raise H5FieldAuditError(f"{case_id}: family mismatch")
    if row.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
        raise H5FieldAuditError(f"{case_id}: selected row is not saved-mask diagnostic")
    trajectory = row.get("source_trajectory")
    current_trajectory = current_row.get("trajectory")
    if not isinstance(trajectory, dict) or not isinstance(current_trajectory, dict):
        raise H5FieldAuditError(f"{case_id}: trajectory metadata missing")
    h5_path = source_path(trajectory.get("path"), f"{case_id} HDF5")
    if Path(current_trajectory.get("path", "")).expanduser().resolve() != h5_path:
        raise H5FieldAuditError(f"{case_id}: CURRENT/HDF5 path mismatch")
    h5_sha = require_sha(trajectory.get("known_sha256"), f"{case_id} HDF5 SHA")
    if require_sha(current_trajectory.get("producer_declared_sha256"), f"{case_id} CURRENT HDF5 SHA") != h5_sha:
        raise H5FieldAuditError(f"{case_id}: CURRENT/HDF5 SHA mismatch")
    pre_stat = trajectory.get("pre_stat")
    if not isinstance(pre_stat, dict):
        raise H5FieldAuditError(f"{case_id}: HDF5 pre-stat missing")
    h5_ref = deferred_ref(h5_path, f"{case_id} trajectory_h5", h5_sha, pre_stat)
    refs = [static_ref(proof_path, f"{case_id} terminal_proof")]
    for field, label in (("case_manifest", "case_manifest"), ("receipt", "producer_receipt"), ("summary", "typed_summary")):
    
        value = source_path(row.get(field), f"{case_id} {label}")
        refs.append(static_ref(value, f"{case_id} {label}", row.get(f"{field}_sha256")))
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    expected_units = metadata.get("units_expected_protocol")
    if not isinstance(expected_units, dict):
        expected_units = dict(UNIT_PROTOCOL)
    case = {
        "physical_case_id": case_id,
        "family_id": family,
        "producer_terminal_proof": refs[0],
        "case_manifest": refs[1],
        "producer_receipt": refs[2],
        "typed_summary": refs[3],
        "trajectory_h5": h5_ref,
        "expected_frames": int(row.get("actual_timeline", {}).get("frames", current_row.get("frames", -1))),
        "expected_particles": int(row.get("actual_timeline", {}).get("particles", current_row.get("particles", -1))),
        "expected_units": expected_units,
        "producer_metadata": {
            "units_status": metadata.get("units_status", "UNKNOWN"),
            "coordinate_frame_status": metadata.get("coordinate_frame_status", "UNKNOWN"),
            "identity_key": metadata.get("identity_key", "UNKNOWN"),
        },
        "source_content_read_by_preparer": False,
    }
    return case, refs


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    current_path = source_path(args.current, "CURRENT336")
    if sha256_file(current_path) != CURRENT_SHA256:
        raise H5FieldAuditError("CURRENT SHA differs")
    current = json_object(current_path, "CURRENT336")
    if current.get("schema") != "ds02.stage2.current336.v1":
        raise H5FieldAuditError("CURRENT schema differs")
    pilots = [parse_pilot(value) for value in args.pilot] if args.pilot else default_pilots()
    if len(pilots) != 7 or {family for family, _, _ in pilots} != {f"F{i}" for i in range(1, 8)}:
        raise H5FieldAuditError("prepare requires exactly one F1..F7 pilot")
    cases: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = [static_ref(current_path, "current336")]
    for family, proof_path, case_id in pilots:
        proof = json_object(proof_path, f"{family} proof")
        case, proof_refs = proof_case(family, proof_path, case_id, proof, current)
        cases.append(case)
        refs.extend(proof_refs)
    worker_path = source_path(args.worker, "HDF5 field worker")
    runtime_path = source_path(args.runtime, "runtime v8")
    dispatch_path = source_path(args.dispatch, "dispatch v8")
    strict_path = source_path(args.strict, "strict dispatch v8")
    config_path = source_path(args.config, "official config")
    python_declared = Path(args.python).expanduser()
    python_path = source_path(python_declared, "literal Python")
    code_refs = [
        static_ref(worker_path, "h5_field_worker"),
        static_ref(runtime_path, "runtime_v8"),
        static_ref(dispatch_path, "dispatch_v8"),
        static_ref(strict_path, "strict_dispatch_v8"),
        static_ref(config_path, "official_runtime_config"),
        static_ref(python_path, "literal_python"),
    ]
    code_refs[-1]["literal_path"] = str(python_declared)
    code_refs[-1]["resolved_path"] = str(python_path)
    refs.extend(code_refs)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "scientific-field-h5-audit-manifest.json"
    request_path = output_dir / "scientific-field-h5-audit-request.json"
    gap_report_path = Path(args.gap_report).expanduser().resolve()
    static_paths, static_hashes = dedupe_refs(refs)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_FOR_GUARDED_RAW_H5_FIELD_AUDIT",
        "current_catalog": {"path": str(current_path), "sha256": CURRENT_SHA256, "cases": 336},
        "pilot_scope": {"families": [f"F{i}" for i in range(1, 8)], "selected_cases": [case["physical_case_id"] for case in cases], "one_case_per_family": True, "historical_alias_excluded": True},
        "static_source_refs": refs,
        "cases": cases,
        "worker_contract": {
            "required_static_datasets": ["time", "particle_id", "particle_zone", "initial_type", "initial_mass"],
            "required_frame_datasets": list(FRAME_FIELDS),
            "optional_material_datasets": ["initial_mk", "material", "mk"],
            "chunk_particles": int(args.chunk),
            "sequential_cases": True,
            "bounded_memory": True,
        },
        "output": {"path": "{attempt_root}/scientific-field-h5-audit.json", "max_bytes": MAX_OUTPUT_BYTES},
        "read_policy": {"prepare_json_and_stat_only": True, "trajectory_h5_opened_by_preparer": False, "trajectory_h5_hashed_by_preparer": False, "trajectory_h5_opened_by_worker_after_reservation": True, "raw_bi4_opened": False, "solver_started": False, "legacy_model_fields_used": False},
        "claim_boundary": {"lifecycle_mask": "saved-record diagnostic only", "units": "producer declaration versus protocol comparison; authority UNKNOWN", "material_and_mk": "dataset presence only; semantics UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(manifest_path, manifest)
    manifest_ref = static_ref(manifest_path, "field_h5_audit_manifest")
    input_paths, input_hashes = dedupe_refs(refs + [manifest_ref])
    request = {
        "schema": REQUEST_SCHEMA,
        "shared_runtime_version": "v8",
        "request_id": "scientific-field-h5-audit-v1-root-prepared-001",
        "family_id": "F1_F2_F3_F4_F5_F6_F7",
        "physical_case_ids": [case["physical_case_id"] for case in cases],
        "attempt_id": "scientific-field-h5-audit-v1-root-prepared-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 3600,
        "max_memory_bytes": 4 * 1024 * 1024 * 1024,
        "estimated_storage_bytes": MAX_OUTPUT_BYTES,
        "estimated_cpu_core_hours": 2.0,
        "estimated_gpu_seconds": 0,
        "cwd": str(LAB_ROOT),
        "worktree_root": str(LAB_ROOT),
        "command": [str(python_declared), "-B", str(worker_path), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/scientific-field-h5-audit.json", "--chunk", str(args.chunk)],
        "input_files": input_paths,
        "input_sha256": input_hashes,
        "deferred_input_files": [case["trajectory_h5"]["path"] for case in cases],
        "deferred_input_records": [case["trajectory_h5"] for case in cases],
        "output_files": ["{attempt_root}/scientific-field-h5-audit.json"],
        "manifest_contract": {"path": str(manifest_path), "sha256": manifest_ref["sha256"]},
        "interpreter_binding": {"literal_path": str(python_declared), "resolved_path": str(python_path), "sha256": code_refs[-1]["sha256"]},
        "runtime_binding": {"runtime_v8": code_refs[1], "dispatch_v8": code_refs[2], "strict_dispatch_v8": code_refs[3], "official_config": code_refs[4]},
        "source_read_cost": {"case_count": 7, "h5_bytes_by_case": {case["physical_case_id"]: case["trajectory_h5"]["bytes"] for case in cases}, "minimum_h5_passes_per_case": 3, "h5_content_read_by_preparer": False, "estimated_memory_bytes": 4 * 1024 * 1024 * 1024, "output_cap_bytes": MAX_OUTPUT_BYTES},
        "read_policy": manifest["read_policy"],
        "claim_boundary": manifest["claim_boundary"],
        "launch_allowed": True,
        "execution_allowed": True,
        "launch_owner": "root",
        "shared_lease_required": True,
        "request_note": "Seven completed source-closed lifecycle pilots, one per family. The guarded worker streams raw HDF5 after reservation only; no BI4/native payload or scientific qualification is claimed.",
    }
    atomic_json(request_path, request)
    report = {
        "schema": "ds02.stage2.scientific-field-h5-gap-report.v1",
        "status": "SOURCE_PREPARED_RAW_H5_FIELD_AUDIT_NOT_RUN",
        "current_binding": {"path": str(current_path), "sha256": CURRENT_SHA256, "case_count": 336},
        "pilot_source_scope": {"proofs": [case["producer_terminal_proof"] for case in cases], "cases": [case["physical_case_id"] for case in cases], "families": [case["family_id"] for case in cases], "one_case_per_family": True},
        "field_gap": {"lifecycle_mask": "saved-record diagnostic only", "raw_active_finite_fields": "pending full-frame HDF5 scan", "inactive_nan_handling": "separate inactive count from active non-finite count", "unit_authority": "producer declaration versus protocol comparison only", "material_and_mk": "not established; optional dataset presence only", "typed_mass_native_massfluid_binding": "UNKNOWN_NOT_ATTEMPTED", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "request": {"path": str(request_path), "sha256": sha256_file(request_path)},
        "manifest": {"path": str(manifest_path), "sha256": manifest_ref["sha256"]},
        "source_read_policy": {"preparer_opened_h5": False, "preparer_hashed_h5": False, "worker_opens_h5_after_reservation": True, "launch_performed": False},
        "goal_complete": False,
    }
    atomic_json(gap_report_path, report)
    return {"status": "prepared", "manifest": str(manifest_path), "manifest_sha256": manifest_ref["sha256"], "request": str(request_path), "request_sha256": sha256_file(request_path), "gap_report": str(gap_report_path), "gap_report_sha256": sha256_file(gap_report_path), "case_count": 7, "h5_content_read_by_preparer": False}


def load_h5_backend() -> tuple[Any, Any]:
    try:
        import h5py  # type: ignore
        import numpy as np  # type: ignore
    except Exception as exc:
        raise H5FieldAuditError("audit requires the bound numpy/h5py runtime") from exc
    return h5py, np


def finite_mask(values: Any, np: Any) -> Any:
    return np.isfinite(values).all(axis=-1) if getattr(values, "ndim", 0) == 2 else np.isfinite(values)


def scan_case(case: dict[str, Any], chunk: int) -> dict[str, Any]:
    h5py, np = load_h5_backend()
    ref = case.get("trajectory_h5")
    if not isinstance(ref, dict):
        raise H5FieldAuditError("trajectory HDF5 ref missing")
    h5_path = source_path(ref.get("path"), "trajectory HDF5")
    expected_sha = require_sha(ref.get("known_sha256"), "known HDF5 SHA")
    pre_stat = stat_ref(h5_path, "h5_pre")
    pre_sha = sha256_file(h5_path)
    if pre_sha != expected_sha:
        raise H5FieldAuditError(f"{case.get('physical_case_id')}: HDF5 pre SHA differs")
    expected_frames = int(case.get("expected_frames", -1))
    expected_particles = int(case.get("expected_particles", -1))
    if chunk <= 0:
        raise H5FieldAuditError("chunk must be positive")
    with h5py.File(h5_path, "r") as h5:
        missing = [field for field in ("time", "particle_id", "particle_zone", "initial_type", "initial_mass") if field not in h5]
        if missing:
            raise H5FieldAuditError(f"{case.get('physical_case_id')}: missing static fields {missing}")
        times = np.asarray(h5["time"][:])
        ids = np.asarray(h5["particle_id"][:])
        zones = np.asarray(h5["particle_zone"][:])
        initial_type = np.asarray(h5["initial_type"][:])
        initial_mass = np.asarray(h5["initial_mass"][:], dtype="float64")
        frames, particles = int(len(times)), int(len(ids))
        if (frames, particles) != (expected_frames, expected_particles):
            raise H5FieldAuditError(f"{case.get('physical_case_id')}: dimensions differ from proof")
        if times.dtype.kind not in "fiu" or not np.isrealobj(times) or not np.isfinite(times).all() or not np.all(np.diff(np.asarray(times, dtype="float64")) > 0):
            raise H5FieldAuditError("time axis is not finite and increasing")
        if ids.dtype.kind not in "iu" or zones.dtype.kind not in "iu" or initial_type.dtype.kind not in "iu":
            raise H5FieldAuditError("identity/type axes are not integer")
        if len(np.unique(np.rec.fromarrays([zones, ids]))) != particles:
            raise H5FieldAuditError("Zone/Idp identity is not unique")
        if initial_mass.shape != (particles,) or not np.isfinite(initial_mass).all() or not (initial_mass > 0).all():
            raise H5FieldAuditError("initial_mass is not finite positive")
        expected_shapes = {
            "position": (frames, particles, 3), "velocity": (frames, particles, 3),
            "density": (frames, particles), "mass": (frames, particles),
            "pressure": (frames, particles), "valid": (frames, particles), "type": (frames, particles),
        }
        missing_frame = [field for field in FRAME_FIELDS if field not in h5 or tuple(h5[field].shape) != expected_shapes[field]]
        if missing_frame:
            raise H5FieldAuditError(f"missing/mismatched frame fields {missing_frame}")
        roles = {
            name: {
                "initial_particle_count": int(np.sum(initial_type == code)),
                "initial_mass_kg": float(np.sum(initial_mass[initial_type == code], dtype="float64")),
                "active_observations": 0,
                "active_nonfinite": {field: 0 for field in FINITE_FIELDS},
                "inactive_nonfinite": {field: 0 for field in FINITE_FIELDS},
                "active_type_unknown_observations": 0,
                "invalid_mask_observations": 0,
            }
            for code, name in TYPE_NAMES.items()
        }
        active_nonfinite_total = inactive_nonfinite_total = invalid_mask_total = active_type_unknown_total = 0
        for frame in range(frames):
            for lo in range(0, particles, chunk):
                hi = min(particles, lo + chunk)
                valid = np.asarray(h5["valid"][frame, lo:hi])
                type_values = np.asarray(h5["type"][frame, lo:hi])
                valid_ok = np.isin(valid, [0, 1])
                active, inactive = valid == 1, valid == 0
                type_ok = np.isfinite(type_values) if type_values.dtype.kind in "fc" else np.ones(len(type_values), dtype=bool)
                type_ok &= np.isin(type_values, list(TYPE_NAMES))
                unknown_type, invalid_mask = active & valid_ok & ~type_ok, ~valid_ok
                active_type_unknown_total += int(np.sum(unknown_type))
                invalid_mask_total += int(np.sum(invalid_mask))
                local_roles = initial_type[lo:hi]
                for code, name in TYPE_NAMES.items():
                    selected = active & valid_ok & type_ok & (local_roles == code)
                    roles[name]["active_observations"] += int(np.sum(selected))
                    roles[name]["active_type_unknown_observations"] += int(np.sum(unknown_type & (local_roles == code)))
                    roles[name]["invalid_mask_observations"] += int(np.sum(invalid_mask & (local_roles == code)))
                for field in FINITE_FIELDS:
                    finite = finite_mask(np.asarray(h5[field][frame, lo:hi]), np)
                    active_bad, inactive_bad = active & valid_ok & ~finite, inactive & ~finite
                    active_nonfinite_total += int(np.sum(active_bad))
                    inactive_nonfinite_total += int(np.sum(inactive_bad))
                    for code, name in TYPE_NAMES.items():
                        roles[name]["active_nonfinite"][field] += int(np.sum(active_bad & (local_roles == code)))
                        roles[name]["inactive_nonfinite"][field] += int(np.sum(inactive_bad & (local_roles == code)))
        attrs: dict[str, Any] = {}
        if "units_json" in h5.attrs:
            raw_units = h5.attrs["units_json"]
            if isinstance(raw_units, bytes):
                raw_units = raw_units.decode("utf-8")
            try:
                attrs["units_json"] = json.loads(str(raw_units))
            except (TypeError, UnicodeError, json.JSONDecodeError):
                attrs["units_json"] = "INVALID_DECLARATION"
        else:
            attrs["units_json"] = None
        for key in ("coordinate_frame", "identity_key", "schema", "mass_semantics"):
            value = h5.attrs.get(key)
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            if value is not None:
                attrs[key] = str(value)
        optional = {name: name in h5 for name in ("initial_mk", "material", "mk")}
    post_stat = stat_ref(h5_path, "h5_post")
    post_sha = sha256_file(h5_path)
    if not same_stat(pre_stat, post_stat) or post_sha != pre_sha:
        raise H5FieldAuditError("HDF5 changed during scan")
    declared_units = attrs.get("units_json")
    if declared_units is None:
        unit_status = "NOT_DECLARED"
    elif not isinstance(declared_units, dict):
        unit_status = "INVALID_DECLARATION"
    elif declared_units == case.get("expected_units"):
        unit_status = "DECLARED_MATCHES_PRODUCER_PROTOCOL"
    else:
        unit_status = "DECLARED_DIFFERS_FROM_PRODUCER_PROTOCOL"
    return {
        "physical_case_id": case["physical_case_id"], "family_id": case["family_id"],
        "status": "COMPLETED_RAW_H5_FIELD_SCAN_NO_SCIENTIFIC_CREDIT",
        "source": {"trajectory_h5": {"path": str(h5_path), "known_sha256": expected_sha, "pre_sha256": pre_sha, "post_sha256": post_sha, "pre_stat": pre_stat, "post_stat": post_stat}, "hash_passes_minimum": 3},
        "dimensions": {"frames_expected": expected_frames, "frames_scanned": frames, "particles_expected": expected_particles, "particles_scanned": particles},
        "identity": {"key": "(Zone,Idp)", "unique": True, "integer_zone": True, "integer_idp": True},
        "initial_mass": {"finite_positive": True, "total_kg": float(np.sum(initial_mass, dtype="float64")), "role_ledger": {name: {"count": value["initial_particle_count"], "mass_kg": value["initial_mass_kg"]} for name, value in roles.items()}, "native_massfluid_binding": "UNKNOWN_NOT_ATTEMPTED"},
        "field_scan": {"required_datasets_present": True, "active_nonfinite_total": active_nonfinite_total, "inactive_nonfinite_total": inactive_nonfinite_total, "invalid_mask_total": invalid_mask_total, "active_type_unknown_total": active_type_unknown_total, "active_finite_status": "ALL_ACTIVE_REQUIRED_FIELDS_FINITE" if active_nonfinite_total == 0 and active_type_unknown_total == 0 and invalid_mask_total == 0 else "ACTIVE_FIELD_OR_MASK_UNKNOWN_OBSERVATIONS_PRESENT", "inactive_nonfinite_separate": True, "frames_full_scan": True, "roles": roles},
        "units": {"producer_declared": declared_units, "expected_protocol": case.get("expected_units"), "comparison": unit_status, "authority": "UNKNOWN_UNVERIFIED"},
        "material_and_mk": {"dataset_presence": optional, "semantic_authority": "UNKNOWN", "material_labels_used_for_science": False},
        "coordinate_frame": {"producer_declared": attrs.get("coordinate_frame"), "status": "DECLARED_UNINTERPRETED" if attrs.get("coordinate_frame") is not None else "NOT_DECLARED"},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "claim_boundary": {"continuous_event_time": "UNKNOWN", "native_exit_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }


def audit(manifest_path: Path, output_path: Path, chunk: int = DEFAULT_CHUNK) -> dict[str, Any]:
    started = time.monotonic()
    manifest_path = source_path(manifest_path, "HDF5 audit manifest")
    manifest = json_object(manifest_path, "HDF5 audit manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_GUARDED_RAW_H5_FIELD_AUDIT":
        raise H5FieldAuditError("manifest is not guarded-ready")
    results, failures = [], []
    for case in manifest.get("cases", []):
        try:
            results.append(scan_case(case, chunk))
        except Exception as exc:
            failures.append({"physical_case_id": case.get("physical_case_id"), "family_id": case.get("family_id"), "status": "FAILED_RAW_H5_FIELD_SCAN", "error_type": type(exc).__name__, "error": str(exc), "scientific_credit": 0})
    status = "COMPLETED_RAW_H5_FIELD_SCAN_NO_SCIENTIFIC_CREDIT" if not failures else "COMPLETED_WITH_CASE_FAILURES_NO_SCIENTIFIC_CREDIT"
    result = {
        "schema": REPORT_SCHEMA, "status": status,
        "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
        "case_results": results, "failed_cases": failures,
        "counts": {"requested": len(results) + len(failures), "completed": len(results), "failed": len(failures)},
        "read_policy": {"trajectory_h5_opened_after_reservation": True, "raw_bi4_opened": False, "solver_started": False, "legacy_model_fields_used": False},
        "source_read_cost": {"minimum_h5_passes_per_completed_case": 3, "wall_seconds": time.monotonic() - started},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "goal_complete": False,
    }
    atomic_json(output_path, result, MAX_OUTPUT_BYTES)
    return {"status": status, "output": str(Path(output_path).resolve()), "completed": len(results), "failed": len(failures)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    prep.add_argument("--pilot", action="append", default=[], help="FAMILY|PROOF_PATH|CASE_ID")
    prep.add_argument("--worker", type=Path, default=SCRIPT)
    prep.add_argument("--runtime", type=Path, default=RUNTIME_DEFAULT)
    prep.add_argument("--dispatch", type=Path, default=DISPATCH_DEFAULT)
    prep.add_argument("--strict", type=Path, default=STRICT_DEFAULT)
    prep.add_argument("--config", type=Path, default=CONFIG_DEFAULT)
    prep.add_argument("--python", type=Path, default=VENV_DEFAULT)
    prep.add_argument("--chunk", type=int, default=DEFAULT_CHUNK)
    prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--gap-report", type=Path, required=True)
    run = sub.add_parser("audit")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--chunk", type=int, default=DEFAULT_CHUNK)
    args = parser.parse_args(argv)
    try:
        value = prepare(args) if args.command == "prepare" else audit(args.manifest, args.output, args.chunk)
    except (H5FieldAuditError, OSError) as exc:
        print(f"scientific-field-h5-audit: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True))
    return 1 if args.command == "audit" and value.get("failed", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())

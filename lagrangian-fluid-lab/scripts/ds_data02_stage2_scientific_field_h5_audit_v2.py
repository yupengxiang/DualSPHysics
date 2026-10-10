#!/usr/bin/env python3
"""Source-bound, bounded-memory raw-HDF5 field audit V2.

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
MANIFEST_SCHEMA = "ds02.stage2.scientific-field-h5-audit-manifest.v2"
REPORT_SCHEMA = "ds02.stage2.scientific-field-h5-audit.v2"
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
            "missing_field_policy": "per-field NOT_EXPOSED/UNKNOWN while scanning all available fields",
            "physical_range_policy": "diagnostic counts/extrema only; no positivity or dynamics gate",
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
        # runtime v8 identities are one dataset-level infrastructure task;
        # the seven physical pilots remain explicit in physical_case_ids.
        "request_id": "scientific-field-h5-audit-v2-root-prepared-003",
        "family_id": "infra",
        "case_id": "scientific-field-h5-audit-v2-root-prepared-003",
        "physical_case_ids": [case["physical_case_id"] for case in cases],
        "attempt_id": "scientific-field-h5-audit-v2-root-prepared-003",
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
        "schema": "ds02.stage2.scientific-field-h5-gap-report.v2",
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



def validate_manifest_bindings(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate static producer/current references without reading deferred H5 content."""
    current = manifest.get("current_catalog")
    if not isinstance(current, dict):
        raise H5FieldAuditError("manifest current_catalog is missing")
    current_path = source_path(current.get("path"), "manifest CURRENT catalog")
    current_sha = require_sha(current.get("sha256"), "manifest CURRENT SHA")
    if current_sha != CURRENT_SHA256 or sha256_file(current_path) != current_sha:
        raise H5FieldAuditError("manifest CURRENT path/SHA binding is not the frozen CURRENT catalog")
    refs = manifest.get("static_source_refs")
    if not isinstance(refs, list) or not refs:
        raise H5FieldAuditError("manifest has no static source refs")
    static_by_path: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict):
            raise H5FieldAuditError("manifest static source ref is not an object")
        path = source_path(ref.get("path"), "manifest static source ref")
        if path.suffix.lower() in {".h5", ".hdf5"}:
            raise H5FieldAuditError("deferred HDF5 content must not be a static source ref")
        expected = require_sha(ref.get("sha256"), f"static source SHA {path}")
        if sha256_file(path) != expected:
            raise H5FieldAuditError(f"static source changed: {path}")
        static_by_path[str(path)] = {**ref, "path": str(path), "sha256": expected}
    for case in manifest.get("cases", []):
        if not isinstance(case, dict):
            raise H5FieldAuditError("manifest case is not an object")
        h5 = case.get("trajectory_h5")
        if not isinstance(h5, dict):
            raise H5FieldAuditError("manifest case has no deferred HDF5 ref")
        h5_path = source_path(h5.get("path"), "manifest deferred HDF5")
        if h5_path.suffix.lower() not in {".h5", ".hdf5"}:
            raise H5FieldAuditError(f"deferred source is not HDF5: {h5_path}")
        require_sha(h5.get("known_sha256"), f"deferred HDF5 SHA {h5_path}")
        for field in ("producer_terminal_proof", "case_manifest", "producer_receipt", "typed_summary"):
            ref = case.get(field)
            if not isinstance(ref, dict):
                raise H5FieldAuditError(f"{case.get('physical_case_id')}: {field} source ref missing")
            ref_path = source_path(ref.get("path"), f"{case.get('physical_case_id')} {field}")
            expected = require_sha(ref.get("sha256"), f"{case.get('physical_case_id')} {field} SHA")
            registered = static_by_path.get(str(ref_path))
            if registered is None or registered.get("sha256") != expected:
                raise H5FieldAuditError(f"{case.get('physical_case_id')}: {field} is not bound to static_source_refs")
            if sha256_file(ref_path) != expected:
                raise H5FieldAuditError(f"{case.get('physical_case_id')}: {field} changed")
    return {"path": str(current_path), "sha256": current_sha, "static_ref_count": len(static_by_path), "manifest_path": str(manifest_path), "manifest_sha256": sha256_file(manifest_path)}


def _stat_matches_deferred(actual: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    for key in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if key in expected and actual.get(key) != expected.get(key):
            raise H5FieldAuditError(f"{label} differs from deferred manifest: {key}")


def _available_dataset(h5: Any, name: str, shape: tuple[int, ...]) -> tuple[Any | None, str]:
    if name not in h5:
        return None, "NOT_EXPOSED"
    dataset = h5[name]
    if tuple(dataset.shape) != shape:
        return None, "PRESENT_SHAPE_MISMATCH"
    return dataset, "PRESENT"


def _finite_scalar(value: Any, np: Any) -> bool:
    try:
        return bool(np.isfinite(value))
    except (TypeError, ValueError):
        return False


def _role_name(code: int) -> str:
    return TYPE_NAMES.get(int(code), "unknown_initial_type")


def _new_role_ledger() -> dict[str, dict[str, Any]]:
    names = list(TYPE_NAMES.values()) + ["unknown_initial_type"]
    return {
        name: {
            "initial_particle_count": 0,
            "initial_mass_kg": None,
            "observed_active_count": 0,
            "observed_inactive_count": 0,
            "active_nonfinite": {field: 0 for field in FINITE_FIELDS},
            "inactive_nonfinite": {field: 0 for field in FINITE_FIELDS},
            "active_nonpositive": {field: 0 for field in ("density", "mass")},
            "active_negative_pressure": 0,
            "active_type_unknown_observations": 0,
            "invalid_mask_observations": 0,
            "mass_min_kg": None,
            "mass_max_kg": None,
            "mass_drift_abs_max_kg": None,
        }
        for name in names
    }


def _update_extreme(ledger: dict[str, Any], value: float) -> None:
    ledger["mass_min_kg"] = value if ledger["mass_min_kg"] is None else min(ledger["mass_min_kg"], value)
    ledger["mass_max_kg"] = value if ledger["mass_max_kg"] is None else max(ledger["mass_max_kg"], value)


def scan_case(case: dict[str, Any], chunk: int, binding: dict[str, Any]) -> dict[str, Any]:
    h5py, np = load_h5_backend()
    ref = case.get("trajectory_h5")
    if not isinstance(ref, dict):
        raise H5FieldAuditError("trajectory HDF5 ref missing")
    h5_path = source_path(ref.get("path"), "trajectory HDF5")
    expected_sha = require_sha(ref.get("known_sha256"), "known HDF5 SHA")
    pre_stat = stat_ref(h5_path, "h5_pre")
    _stat_matches_deferred(pre_stat, ref, f"{case.get('physical_case_id')} HDF5 pre-stat")
    pre_sha = sha256_file(h5_path)
    if pre_sha != expected_sha:
        raise H5FieldAuditError(f"{case.get('physical_case_id')}: HDF5 pre SHA differs")
    expected_frames = int(case.get("expected_frames", -1))
    expected_particles = int(case.get("expected_particles", -1))
    if chunk <= 0 or expected_frames <= 0 or expected_particles <= 0:
        raise H5FieldAuditError("invalid bounded scan dimensions")
    with h5py.File(h5_path, "r") as h5:
        time_ds, time_status = _available_dataset(h5, "time", (expected_frames,))
        id_ds, id_status = _available_dataset(h5, "particle_id", (expected_particles,))
        zone_ds, zone_status = _available_dataset(h5, "particle_zone", (expected_particles,))
        initial_type_ds, initial_type_status = _available_dataset(h5, "initial_type", (expected_particles,))
        initial_mass_ds, initial_mass_status = _available_dataset(h5, "initial_mass", (expected_particles,))
        if id_ds is not None and id_ds.dtype.kind not in "iu":
            id_status = "PRESENT_INVALID_TYPE"
            id_ds = None
        if zone_ds is not None and zone_ds.dtype.kind not in "iu":
            zone_status = "PRESENT_INVALID_TYPE"
            zone_ds = None
        if initial_type_ds is not None and initial_type_ds.dtype.kind not in "iu":
            initial_type_status = "PRESENT_INVALID_TYPE"
            initial_type_ds = None
        times = np.asarray(time_ds[:], dtype="float64") if time_ds is not None and time_ds.dtype.kind in "fiu" else None
        time_status = "PRESENT" if times is not None and np.isfinite(times).all() and (len(times) < 2 or np.all(np.diff(times) > 0)) else ("PRESENT_INVALID_VALUES" if time_ds is not None else "NOT_EXPOSED")
        ids = np.asarray(id_ds[:]) if id_ds is not None else None
        zones = np.asarray(zone_ds[:]) if zone_ds is not None else None
        initial_type = np.asarray(initial_type_ds[:]) if initial_type_ds is not None else None
        initial_mass = None
        if initial_mass_ds is not None:
            try:
                initial_mass = np.asarray(initial_mass_ds[:], dtype="float64")
            except (TypeError, ValueError):
                initial_mass_status = "PRESENT_INVALID_TYPE"
        identity_unique = False
        identity_status = "NOT_EXPOSED"
        if ids is not None and zones is not None:
            identity_unique = len(np.unique(np.rec.fromarrays([zones, ids]))) == expected_particles
            identity_status = "VALID" if identity_unique else "DUPLICATE_ZONE_IDP"
        initial_type_valid = initial_type is not None and initial_type.shape == (expected_particles,)
        initial_type_invalid_codes = int(np.sum(~np.isin(initial_type, list(TYPE_NAMES)))) if initial_type_valid else None
        initial_type_status = "PRESENT_VALID_CODES" if initial_type_valid and initial_type_invalid_codes == 0 else ("PRESENT_UNKNOWN_CODES" if initial_type_valid else initial_type_status)
        initial_mass_invalid = None
        initial_mass_total = None
        if initial_mass is not None:
            initial_mass_invalid = int(np.sum(~np.isfinite(initial_mass) | (initial_mass <= 0)))
            if initial_mass_invalid == 0:
                initial_mass_total = float(np.sum(initial_mass, dtype="float64"))
            initial_mass_status = "PRESENT_FINITE_POSITIVE" if initial_mass_invalid == 0 else "PRESENT_INVALID_VALUES"
        else:
            initial_mass_status = "NOT_EXPOSED"
        roles = _new_role_ledger()
        if initial_type_valid:
            for code, name in TYPE_NAMES.items():
                selected = initial_type == code
                roles[name]["initial_particle_count"] = int(np.sum(selected))
                if initial_mass is not None and initial_mass_invalid == 0:
                    roles[name]["initial_mass_kg"] = float(np.sum(initial_mass[selected], dtype="float64"))
            roles["unknown_initial_type"]["initial_particle_count"] = int(np.sum(~np.isin(initial_type, list(TYPE_NAMES))))
        else:
            roles["unknown_initial_type"]["initial_particle_count"] = expected_particles
        expected_shapes = {
            "position": (expected_frames, expected_particles, 3), "velocity": (expected_frames, expected_particles, 3),
            "density": (expected_frames, expected_particles), "mass": (expected_frames, expected_particles),
            "pressure": (expected_frames, expected_particles), "valid": (expected_frames, expected_particles), "type": (expected_frames, expected_particles),
        }
        datasets: dict[str, Any | None] = {}
        field_status: dict[str, str] = {}
        for name, shape in expected_shapes.items():
            datasets[name], field_status[name] = _available_dataset(h5, name, shape)
            if datasets[name] is not None and name in FINITE_FIELDS and datasets[name].dtype.kind not in "fiu":
                datasets[name] = None
                field_status[name] = "PRESENT_INVALID_TYPE"
            if datasets[name] is not None and name in ("valid", "type") and datasets[name].dtype.kind not in "fiu b":
                datasets[name] = None
                field_status[name] = "PRESENT_INVALID_TYPE"
        mask_available = datasets["valid"] is not None
        frame_type_available = datasets["type"] is not None
        field_totals: dict[str, dict[str, Any]] = {
            name: {"status": field_status[name], "observations": 0, "nonfinite_total": 0, "active_nonfinite": None, "inactive_nonfinite": None, "unclassified_nonfinite": None, "active_nonpositive": None, "active_negative": None}
            for name in FINITE_FIELDS
        }
        if mask_available:
            for value in field_totals.values():
                value["active_nonfinite"] = 0
                value["inactive_nonfinite"] = 0
                value["unclassified_nonfinite"] = 0
                value["active_nonpositive"] = 0
                value["active_negative"] = 0
        invalid_mask_total = 0
        active_type_unknown_total = 0
        frame_type_unknown_total = 0
        unclassified_observations = 0
        transition_counts: dict[str, int] = {}
        previous_mass = np.full(expected_particles, np.nan, dtype="float64")
        previous_mass_known = np.zeros(expected_particles, dtype=bool)
        for frame in range(expected_frames):
            for lo in range(0, expected_particles, chunk):
                hi = min(expected_particles, lo + chunk)
                valid = np.asarray(datasets["valid"][frame, lo:hi]) if mask_available else None
                type_values = np.asarray(datasets["type"][frame, lo:hi]) if frame_type_available else None
                if valid is not None:
                    valid_ok = np.isin(valid, [0, 1])
                    active = valid == 1
                    inactive = valid == 0
                    invalid_mask = ~valid_ok
                    invalid_mask_total += int(np.sum(invalid_mask))
                else:
                    valid_ok = active = inactive = invalid_mask = None
                    unclassified_observations += hi - lo
                if type_values is not None:
                    type_ok = np.isfinite(type_values) if type_values.dtype.kind in "fc" else np.ones(len(type_values), dtype=bool)
                    type_ok &= np.isin(type_values, list(TYPE_NAMES))
                    frame_type_unknown_total += int(np.sum(~type_ok))
                else:
                    type_ok = None
                    frame_type_unknown_total += hi - lo
                if valid is not None and type_values is not None:
                    active_type_unknown_total += int(np.sum(active & valid_ok & ~type_ok))
                local_roles = initial_type[lo:hi] if initial_type_valid else np.full(hi - lo, -1, dtype="int64")
                for field in FINITE_FIELDS:
                    dataset = datasets[field]
                    if dataset is None:
                        continue
                    values = np.asarray(dataset[frame, lo:hi])
                    finite = finite_mask(values, np)
                    field_totals[field]["observations"] += int(len(finite))
                    field_totals[field]["nonfinite_total"] += int(np.sum(~finite))
                    if valid is not None:
                        active_good = active & valid_ok
                        inactive_good = inactive
                        unknown_good = ~valid_ok
                        active_bad = active_good & ~finite
                        inactive_bad = inactive_good & ~finite
                        unclassified_bad = unknown_good & ~finite
                        field_totals[field]["active_nonfinite"] += int(np.sum(active_bad))
                        field_totals[field]["inactive_nonfinite"] += int(np.sum(inactive_bad))
                        field_totals[field]["unclassified_nonfinite"] += int(np.sum(unclassified_bad))
                        if values.ndim == 1:
                            finite_values = np.asarray(values, dtype="float64")
                            finite_active = active_good & finite
                            if field in ("density", "mass"):
                                field_totals[field]["active_nonpositive"] += int(np.sum(finite_active & (finite_values <= 0)))
                            if field == "pressure":
                                field_totals[field]["active_negative"] += int(np.sum(finite_active & (finite_values < 0)))
                            if field == "mass":
                                for local_index in np.flatnonzero(finite_active):
                                    absolute = lo + int(local_index)
                                    value = float(finite_values[local_index])
                                    role = _role_name(int(local_roles[local_index]))
                                    _update_extreme(roles[role], value)
                                    if previous_mass_known[absolute]:
                                        drift = abs(value - previous_mass[absolute])
                                        old = roles[role]["mass_drift_abs_max_kg"]
                                        roles[role]["mass_drift_abs_max_kg"] = drift if old is None else max(old, drift)
                                    previous_mass[absolute] = value
                                    previous_mass_known[absolute] = True
                        for code, name in TYPE_NAMES.items():
                            role_mask = local_roles == code
                            roles[name]["active_nonfinite"][field] += int(np.sum(active_bad & role_mask))
                            roles[name]["inactive_nonfinite"][field] += int(np.sum(inactive_bad & role_mask))
                            if field in ("density", "mass") and values.ndim == 1:
                                roles[name]["active_nonpositive"][field] += int(np.sum(active_good & finite & (values <= 0) & role_mask))
                            if field == "pressure" and values.ndim == 1:
                                roles[name]["active_negative_pressure"] += int(np.sum(active_good & finite & (values < 0) & role_mask))
                        unknown_role_mask = ~np.isin(local_roles, list(TYPE_NAMES))
                        roles["unknown_initial_type"]["active_nonfinite"][field] += int(np.sum(active_bad & unknown_role_mask))
                        roles["unknown_initial_type"]["inactive_nonfinite"][field] += int(np.sum(inactive_bad & unknown_role_mask))
                        if field in ("density", "mass") and values.ndim == 1:
                            roles["unknown_initial_type"]["active_nonpositive"][field] += int(np.sum(active_good & finite & (values <= 0) & unknown_role_mask))
                        if field == "pressure" and values.ndim == 1:
                            roles["unknown_initial_type"]["active_negative_pressure"] += int(np.sum(active_good & finite & (values < 0) & unknown_role_mask))
                if valid is not None:
                    for code, name in TYPE_NAMES.items():
                        role_mask = local_roles == code
                        roles[name]["observed_active_count"] += int(np.sum(active & valid_ok & role_mask))
                        roles[name]["observed_inactive_count"] += int(np.sum(inactive & role_mask))
                        roles[name]["active_type_unknown_observations"] += int(np.sum(active & valid_ok & (~type_ok if type_ok is not None else np.ones(len(local_roles), dtype=bool)) & role_mask))
                        roles[name]["invalid_mask_observations"] += int(np.sum(invalid_mask & role_mask))
                    unknown_role_mask = ~np.isin(local_roles, list(TYPE_NAMES))
                    roles["unknown_initial_type"]["observed_active_count"] += int(np.sum(active & valid_ok & unknown_role_mask))
                    roles["unknown_initial_type"]["observed_inactive_count"] += int(np.sum(inactive & unknown_role_mask))
                    roles["unknown_initial_type"]["active_type_unknown_observations"] += int(np.sum(active & valid_ok & (~type_ok if type_ok is not None else np.ones(len(local_roles), dtype=bool)) & unknown_role_mask))
                    roles["unknown_initial_type"]["invalid_mask_observations"] += int(np.sum(invalid_mask & unknown_role_mask))
                if valid is not None and type_values is not None and initial_type_valid:
                    known = active & valid_ok & type_ok
                    for initial_code, initial_name in TYPE_NAMES.items():
                        for current_code, current_name in TYPE_NAMES.items():
                            count = int(np.sum(known & (local_roles == initial_code) & (type_values == current_code)))
                            if count:
                                key = f"{initial_name}->{current_name}"
                                transition_counts[key] = transition_counts.get(key, 0) + count
        post_stat = stat_ref(h5_path, "h5_post")
        post_sha = sha256_file(h5_path)
    if not same_stat(pre_stat, post_stat) or post_sha != pre_sha:
        raise H5FieldAuditError("HDF5 changed during scan")
    declared_units: Any = None
    # Attributes were read while the file was open; optional declarations are not science authority.
    with h5py.File(h5_path, "r") as h5:
        if "units_json" in h5.attrs:
            raw_units = h5.attrs["units_json"]
            if isinstance(raw_units, bytes):
                raw_units = raw_units.decode("utf-8")
            try:
                declared_units = json.loads(str(raw_units))
            except (TypeError, UnicodeError, json.JSONDecodeError):
                declared_units = "INVALID_DECLARATION"
        attrs = {}
        for key in ("coordinate_frame", "identity_key", "schema", "mass_semantics"):
            value = h5.attrs.get(key)
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            if value is not None:
                attrs[key] = str(value)
        optional = {name: name in h5 for name in ("initial_mk", "material", "mk")}
    if declared_units is None:
        unit_status = "NOT_DECLARED"
    elif not isinstance(declared_units, dict):
        unit_status = "INVALID_DECLARATION"
    elif declared_units == case.get("expected_units"):
        unit_status = "DECLARED_MATCHES_PRODUCER_PROTOCOL"
    else:
        unit_status = "DECLARED_DIFFERS_FROM_PRODUCER_PROTOCOL"
    active_nonfinite_total = sum(value["active_nonfinite"] or 0 for value in field_totals.values()) if mask_available else None
    inactive_nonfinite_total = sum(value["inactive_nonfinite"] or 0 for value in field_totals.values()) if mask_available else None
    if not all(field_status[field] == "PRESENT" for field in FINITE_FIELDS):
        active_status = "REQUIRED_FIELD_NOT_EXPOSED"
    elif not mask_available:
        active_status = "ACTIVE_MASK_NOT_EXPOSED"
    elif not frame_type_available or frame_type_unknown_total or initial_type_invalid_codes:
        active_status = "ACTIVE_TYPE_OR_ROLE_UNKNOWN"
    elif active_nonfinite_total:
        active_status = "ACTIVE_NONFINITE_OBSERVATIONS"
    elif invalid_mask_total:
        active_status = "MASK_UNKNOWN_OBSERVATIONS"
    else:
        active_status = "ALL_ACTIVE_REQUIRED_FIELDS_FINITE"
    initial_role_total = sum(value["initial_particle_count"] for value in roles.values())
    observed_active_total = sum(value["observed_active_count"] for value in roles.values())
    observed_inactive_total = sum(value["observed_inactive_count"] for value in roles.values())
    role_reconciliation = {
        "initial_expected_particles": expected_particles,
        "initial_role_count_total": initial_role_total,
        "initial_role_counts_reconciled": initial_role_total == expected_particles,
        "frame_expected_observations": expected_frames * expected_particles,
        "frame_active_count_total": observed_active_total if mask_available else None,
        "frame_inactive_count_total": observed_inactive_total if mask_available else None,
        "frame_invalid_mask_count": invalid_mask_total if mask_available else None,
        "frame_role_counts_reconciled": (
            observed_active_total + observed_inactive_total + invalid_mask_total == expected_frames * expected_particles
            if mask_available else None
        ),
        "unknown_initial_type_count": roles["unknown_initial_type"]["initial_particle_count"],
    }
    source_refs = []
    for field in ("producer_terminal_proof", "case_manifest", "producer_receipt", "typed_summary"):
        ref_value = case[field]
        source_refs.append({"role": field, "path": ref_value["path"], "sha256": ref_value["sha256"]})
    return {
        "physical_case_id": case["physical_case_id"], "family_id": case["family_id"],
        "status": "COMPLETED_RAW_H5_FIELD_SCAN_NO_SCIENTIFIC_CREDIT",
        "source_binding": {"manifest": binding, "producer_refs": source_refs, "trajectory_h5": {"path": str(h5_path), "known_sha256": expected_sha, "pre_sha256": pre_sha, "post_sha256": post_sha, "pre_stat": pre_stat, "post_stat": post_stat, "deferred_manifest_stat_match": True}, "hash_passes_minimum": 3},
        "dimensions": {"frames_expected": expected_frames, "frames_scanned": expected_frames, "particles_expected": expected_particles, "particles_scanned": expected_particles},
        "time": {"status": time_status, "frames": expected_frames, "first_s": None if times is None else float(times[0]), "last_s": None if times is None else float(times[-1]), "monotonic": time_status == "PRESENT"},
        "identity": {"key": "(Zone,Idp)", "status": identity_status, "unique": identity_unique, "integer_zone": zone_status == "PRESENT", "integer_idp": id_status == "PRESENT", "initial_axis_exposed": {"particle_id": id_status, "particle_zone": zone_status}},
        "initial_type": {"status": initial_type_status, "valid_codes": sorted(TYPE_NAMES), "invalid_code_count": initial_type_invalid_codes, "role_counts": {name: value["initial_particle_count"] for name, value in roles.items()}},
        "initial_mass": {"status": initial_mass_status, "finite_positive": initial_mass_status == "PRESENT_FINITE_POSITIVE", "invalid_value_count": initial_mass_invalid, "total_kg": initial_mass_total, "role_ledger": {name: {"count": value["initial_particle_count"], "mass_kg": value["initial_mass_kg"]} for name, value in roles.items()}, "native_massfluid_binding": "UNKNOWN_NOT_ATTEMPTED"},
        "field_scan": {"field_status": field_status, "active_nonfinite_total": active_nonfinite_total, "inactive_nonfinite_total": inactive_nonfinite_total, "unclassified_nonfinite_total": None if mask_available else sum(value["nonfinite_total"] for value in field_totals.values()), "invalid_mask_total": invalid_mask_total if mask_available else None, "active_type_unknown_total": active_type_unknown_total if frame_type_available else None, "frame_type_unknown_total": frame_type_unknown_total, "active_finite_status": active_status, "inactive_nonfinite_separate": True, "frames_full_scan": True, "roles": roles, "role_reconciliation": role_reconciliation, "frame_type_transitions": transition_counts, "observations": field_totals},
        "physical_ranges": {"status": "DIAGNOSTIC_ONLY_NO_GATE", "density_mass_active_nonpositive": {field: field_totals[field]["active_nonpositive"] for field in ("density", "mass")}, "pressure_active_negative": field_totals["pressure"]["active_negative"], "per_role_mass_extrema_and_drift": {name: {"min_kg": value["mass_min_kg"], "max_kg": value["mass_max_kg"], "drift_abs_max_kg": value["mass_drift_abs_max_kg"]} for name, value in roles.items()}},
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
    binding = validate_manifest_bindings(manifest_path, manifest)
    results, failures = [], []
    for case in manifest.get("cases", []):
        try:
            results.append(scan_case(case, chunk, binding))
        except Exception as exc:
            failures.append({"physical_case_id": case.get("physical_case_id"), "family_id": case.get("family_id"), "status": "FAILED_RAW_H5_FIELD_SCAN", "error_type": type(exc).__name__, "error": str(exc), "scientific_credit": 0})
    status = "COMPLETED_RAW_H5_FIELD_SCAN_NO_SCIENTIFIC_CREDIT" if not failures else "COMPLETED_WITH_CASE_FAILURES_NO_SCIENTIFIC_CREDIT"
    result = {
        "schema": REPORT_SCHEMA, "status": status,
        "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path), "current_binding": binding},
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

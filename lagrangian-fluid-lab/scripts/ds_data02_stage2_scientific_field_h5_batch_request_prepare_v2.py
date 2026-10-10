#!/usr/bin/env python3
"""Prepare bounded, source-closed V3 raw-HDF5 audit requests.

This is a metadata-only continuation of the frozen 335-case index.  It reads
the canonical JSON index and small producer references, hashes only static
source files, and records HDF5 paths/statistics as deferred inputs.  It never
opens or hashes a trajectory HDF5/BI4/native payload.  Each family group is
limited to eight cases and twenty GiB of deferred HDF5 bytes; the resulting
requests point at the additive V3 worker, which performs one case at a time
with bounded chunk reductions after root admission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

SCRIPT = Path(__file__).resolve()
PRIMARY_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LAB_ROOT = PRIMARY_ROOT
STAGE2_ROOT = PRIMARY_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
MASTER_DEFAULT = STAGE2_ROOT / "requests/scientific-field-h5-335-batch-source-prepared-001/scientific-field-h5-335-batch-manifest.json"
CURRENT_DEFAULT = STAGE2_ROOT / "CURRENT336.json"
PLAN_DEFAULT = STAGE2_ROOT / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json"
REGISTRY_DEFAULT = STAGE2_ROOT / "requests/typed-lifecycle-evidence-registry-v4-after-root307-001.json"
# Worker/verifier defaults follow this checkout so an isolated source
# preparer does not silently point at a missing primary-worktree copy.  Root
# may later rebind these paths while preserving the source SHA in the request.
WORKER_DEFAULT = SCRIPT.parent / "ds_data02_stage2_scientific_field_h5_audit_v3.py"
V2_WORKER_DEFAULT = SCRIPT.parent / "ds_data02_stage2_scientific_field_h5_audit_v2.py"
VERIFIER_DEFAULT = SCRIPT.parent / "ds_data02_stage2_verify_scientific_field_h5_audit_v2.py"
RUNTIME_DEFAULT = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
DISPATCH_DEFAULT = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT_DEFAULT = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
VENV_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
CONFIG_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
MASTER_SHA256 = "f396bcaa87e34cb40ac312fd6f00c93d9dacd2ec7f2c056622e5c5ac420fb76d"
MASTER_SCHEMA = "ds02.stage2.scientific-field-h5-batch-source.v1"
MANIFEST_SCHEMA = "ds02.stage2.scientific-field-h5-audit-manifest.v2"
REQUEST_SCHEMA = "ds02.request.v1"
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_GROUP_CASES = 8
MAX_GROUP_H5_BYTES = 20 * 1024**3
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
UNIT_PROTOCOL = {"position": "m", "velocity": "m/s", "density": "kg/m^3", "mass": "kg", "pressure": "Pa", "time": "s"}
H5_SUFFIXES = {".h5", ".hdf5"}
PAYLOAD_SUFFIXES = H5_SUFFIXES | {".bi4", ".obi4", ".vtk", ".vtu", ".vtp"}


class BatchPrepareError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
        raise BatchPrepareError(f"{label} must be a SHA-256 digest")
    return value.lower()


def source_file(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise BatchPrepareError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise BatchPrepareError(f"{label} is missing: {path}")
    return path


def json_object(path: Path, label: str) -> dict[str, Any]:
    path = source_file(path, label)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise BatchPrepareError(f"{label} exceeds bounded JSON size")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BatchPrepareError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise BatchPrepareError(f"{label} must be an object")
    return value


def stat_ref(path: Path, role: str) -> dict[str, Any]:
    value = path.stat()
    return {
        "role": role,
        "path": str(path.resolve()),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def static_ref(path: Path, role: str, expected_sha: str | None = None) -> dict[str, Any]:
    path = source_file(path, role)
    if path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise BatchPrepareError(f"payload cannot be a static input: {path}")
    ref = stat_ref(path, role)
    actual = sha256_file(path)
    if expected_sha is not None and actual != require_sha(expected_sha, f"{role} expected SHA"):
        raise BatchPrepareError(f"{role} changed: {path}")
    ref.update({"sha256": actual, "content_read_by_preparer": True})
    return ref


def deferred_h5_ref(row: dict[str, Any]) -> dict[str, Any]:
    ref = row.get("trajectory_h5")
    if not isinstance(ref, dict):
        raise BatchPrepareError(f"{row.get('physical_case_id')}: trajectory_h5 metadata missing")
    path = source_file(ref.get("path"), f"{row.get('physical_case_id')} trajectory H5")
    if path.suffix.lower() not in H5_SUFFIXES:
        raise BatchPrepareError(f"{row.get('physical_case_id')}: trajectory is not HDF5")
    actual = stat_ref(path, f"{row.get('physical_case_id')} deferred trajectory H5")
    for key in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if key in ref and int(ref[key]) != int(actual[key]):
            raise BatchPrepareError(f"{row.get('physical_case_id')}: deferred H5 stat changed: {key}")
    digest = require_sha(ref.get("known_sha256"), f"{row.get('physical_case_id')} deferred H5 known SHA")
    actual.update({"sha256": digest, "known_sha256": digest, "deferred_after_parent_reservation": True, "content_read_by_preparer": False, "known_sha_source": ref.get("known_sha_source", "canonical producer evidence")})
    return actual


def atomic_json(path: Path, value: dict[str, Any], max_bytes: int = MAX_JSON_BYTES) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise BatchPrepareError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if tmp.stat().st_size > max_bytes:
            raise BatchPrepareError(f"output exceeds bounded JSON size: {path}")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {}
    for ref in refs:
        path = str(Path(ref["path"]).resolve())
        digest = require_sha(ref.get("sha256"), f"source ref {path} SHA")
        if path in by_path and by_path[path]["sha256"] != digest:
            raise BatchPrepareError(f"conflicting source reference: {path}")
        by_path[path] = {**ref, "path": path, "sha256": digest}
    return [by_path[path] for path in sorted(by_path)]


def _embedded_static_ref(value: Any, role: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BatchPrepareError(f"{role} is missing")
    return static_ref(source_file(value.get("path"), role), role, require_sha(value.get("sha256"), f"{role} embedded SHA"))


def _validate_master(master: dict[str, Any], *, require_full: bool = True) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if master.get("schema") != MASTER_SCHEMA:
        raise BatchPrepareError("335 source manifest schema differs")
    if master.get("status") != "SOURCE_PREPARED_335_CANONICAL_METADATA_ONLY":
        raise BatchPrepareError("335 source manifest is not canonical metadata-only")
    cases = master.get("cases")
    groups = master.get("groups")
    if not isinstance(cases, list) or not isinstance(groups, list):
        raise BatchPrepareError("335 source manifest lacks cases/groups")
    if require_full and (len(cases) != 335 or len(groups) != 43):
        raise BatchPrepareError(f"expected 335 cases and 43 groups, got {len(cases)} and {len(groups)}")
    case_map: dict[str, dict[str, Any]] = {}
    for row in cases:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise BatchPrepareError("invalid canonical case row")
        case_id = row["physical_case_id"]
        if case_id in case_map:
            raise BatchPrepareError(f"duplicate canonical case: {case_id}")
        if row.get("saved_mask_status") == "HISTORICAL_ALIAS_UNRESOLVED" or row.get("source_join_status") == "SEPARATE_HISTORICAL_ALIAS_UNRESOLVED":
            raise BatchPrepareError(f"alias entered canonical case set: {case_id}")
        case_map[case_id] = row
    group_map: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("group_id"), str):
            raise BatchPrepareError("invalid group row")
        group_id = group["group_id"]
        if group_id in group_map:
            raise BatchPrepareError(f"duplicate group: {group_id}")
        ids = group.get("case_ids")
        if not isinstance(ids, list) or not 0 < len(ids) <= MAX_GROUP_CASES:
            raise BatchPrepareError(f"{group_id}: group case count exceeds bound")
        if len(set(ids)) != len(ids):
            raise BatchPrepareError(f"{group_id}: duplicate case IDs")
        source_bytes = int(group.get("declared_source_bytes", -1))
        if source_bytes < 0 or source_bytes > MAX_GROUP_H5_BYTES:
            raise BatchPrepareError(f"{group_id}: deferred H5 bytes exceed 20 GiB")
        family = group.get("family_id")
        for case_id in ids:
            if case_id not in case_map:
                raise BatchPrepareError(f"{group_id}: unknown case {case_id}")
            if case_id in seen:
                raise BatchPrepareError(f"case occurs in multiple groups: {case_id}")
            if case_map[case_id].get("family_id") != family:
                raise BatchPrepareError(f"{group_id}: family mismatch for {case_id}")
            seen.add(case_id)
        group_map[group_id] = group
    if require_full and seen != set(case_map):
        raise BatchPrepareError(f"group partition differs from canonical case set: {len(set(case_map) - seen)} missing")
    return case_map, group_map


def _expected_units(current_row: dict[str, Any]) -> dict[str, str]:
    header = current_row.get("header")
    units = header.get("units") if isinstance(header, dict) else None
    if isinstance(units, dict) and all(isinstance(units.get(key), str) for key in UNIT_PROTOCOL):
        return {key: str(units[key]) for key in UNIT_PROTOCOL}
    return dict(UNIT_PROTOCOL)


def _case_contract(master_row: dict[str, Any], current_row: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    case_id = master_row["physical_case_id"]
    if master_row.get("family_id") != current_row.get("family_id"):
        raise BatchPrepareError(f"{case_id}: master/CURRENT family mismatch")
    producer = master_row.get("producer")
    typed = master_row.get("typed_lifecycle_evidence")
    if not isinstance(producer, dict) or producer.get("status") != "COMPLETED":
        raise BatchPrepareError(f"{case_id}: producer is not completed")
    if not isinstance(typed, dict) or not isinstance(typed.get("case_receipt"), dict) or not isinstance(typed.get("typed_summary"), dict):
        raise BatchPrepareError(f"{case_id}: typed lifecycle source refs incomplete")
    proof_ref = _embedded_static_ref(producer.get("proof"), f"{case_id} producer terminal proof")
    manifest_ref = _embedded_static_ref(typed.get("case_manifest"), f"{case_id} typed case manifest") if typed.get("case_manifest") is not None else None
    receipt_ref = _embedded_static_ref(typed.get("case_receipt"), f"{case_id} typed case receipt")
    summary_ref = _embedded_static_ref(typed.get("typed_summary"), f"{case_id} typed lifecycle summary")
    trajectory = deferred_h5_ref(master_row)
    frames = int(current_row.get("frames", -1))
    particles = int(current_row.get("particles", -1))
    if frames <= 0 or particles <= 0:
        raise BatchPrepareError(f"{case_id}: invalid CURRENT dimensions")
    refs = [proof_ref, receipt_ref, summary_ref]
    if manifest_ref is not None:
        refs.insert(1, manifest_ref)
    case = {
        "physical_case_id": case_id,
        "family_id": str(master_row["family_id"]),
        "producer_terminal_proof": proof_ref,
        "case_manifest": manifest_ref,
        "case_manifest_status": "BOUND" if manifest_ref is not None else "NOT_EXPOSED_BY_PRODUCER",
        "producer_receipt": receipt_ref,
        "typed_summary": summary_ref,
        "trajectory_h5": trajectory,
        "expected_frames": frames,
        "expected_particles": particles,
        "expected_units": _expected_units(current_row),
        "producer_metadata": {
            "producer_id": producer.get("producer_id"),
            "saved_mask_status": master_row.get("saved_mask_status"),
            "source_join_status": master_row.get("source_join_status"),
            "units_status": "DECLARED_ONLY_UNVERIFIED",
            "identity_key": ((current_row.get("header") or {}).get("identity_key") if isinstance(current_row.get("header"), dict) else None) or "UNKNOWN",
        },
        "source_content_read_by_preparer": False,
    }
    return case, refs


def _core_refs(args: argparse.Namespace) -> list[dict[str, Any]]:
    refs = [
        static_ref(SCRIPT, "h5_batch_request_builder_v2"),
        static_ref(source_file(args.worker, "V3 HDF5 worker"), "h5_field_worker_v3"),
        static_ref(source_file(args.v2_worker, "V2 HDF5 worker dependency"), "h5_field_worker_v2_dependency"),
        static_ref(source_file(args.verifier, "HDF5 audit verifier"), "h5_field_verifier"),
        static_ref(source_file(args.runtime, "runtime v8"), "runtime_v8"),
        static_ref(source_file(args.dispatch, "dispatch v8"), "dispatch_v8"),
        static_ref(source_file(args.strict, "strict dispatch v8"), "strict_dispatch_v8"),
        static_ref(source_file(args.config, "official runtime config"), "official_runtime_config"),
    ]
    python_declared = Path(args.python).expanduser()
    python_path = source_file(python_declared, "literal Python")
    python_ref = static_ref(python_path, "literal_python")
    python_ref["literal_path"] = str(python_declared)
    python_ref["resolved_path"] = str(python_path)
    refs.append(python_ref)
    return refs


def _build_group(group: dict[str, Any], case_map: dict[str, dict[str, Any]], current_map: dict[str, dict[str, Any]], common_refs: list[dict[str, Any]], current_ref: dict[str, Any], source_manifest_ref: dict[str, Any], plan_ref: dict[str, Any] | None, registry_ref: dict[str, Any] | None, args: argparse.Namespace, group_dir: Path) -> dict[str, Any]:
    group_id = str(group["group_id"])
    cases: list[dict[str, Any]] = []
    refs = [current_ref, source_manifest_ref, *common_refs]
    for case_id in group["case_ids"]:
        case, case_refs = _case_contract(case_map[case_id], current_map[case_id])
        cases.append(case)
        refs.extend(case_refs)
    if plan_ref is not None:
        refs.append(plan_ref)
    if registry_ref is not None:
        refs.append(registry_ref)
    static_refs = dedupe_refs(refs)
    static_ref_paths = {ref["path"] for ref in static_refs}
    deferred_paths = [case["trajectory_h5"]["path"] for case in cases]
    if static_ref_paths.intersection(deferred_paths):
        raise BatchPrepareError(f"{group_id}: deferred H5 leaked into static inputs")
    group_manifest_path = group_dir / "scientific-field-h5-audit-manifest.json"
    group_manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_FOR_GUARDED_RAW_H5_FIELD_AUDIT",
        "batch_source": {"schema": "ds02.stage2.scientific-field-h5-batch-source.v2", "group_id": group_id, "source_manifest_sha256": source_manifest_ref["sha256"], "source_manifest_path": source_manifest_ref["path"]},
        "current_catalog": {"path": current_ref["path"], "sha256": current_ref["sha256"], "cases": 336},
        "group_scope": {"group_id": group_id, "family_id": group["family_id"], "case_count": len(cases), "case_ids": [case["physical_case_id"] for case in cases], "one_case_at_a_time": True, "historical_alias_excluded": True},
        "static_source_refs": static_refs,
        "cases": cases,
        "worker_contract": {
            "worker_version": "v3_vectorized_postread_guard",
            "required_static_datasets": ["time", "particle_id", "particle_zone", "initial_type", "initial_mass"],
            "required_frame_datasets": ["position", "velocity", "density", "mass", "pressure", "valid", "type"],
            "optional_material_datasets": ["initial_mk", "material", "mk"],
            "chunk_particles": int(args.chunk), "sequential_cases": True, "bounded_memory": True,
            "missing_field_policy": "per-field NOT_EXPOSED/UNKNOWN while scanning all available fields",
            "physical_range_policy": "diagnostic counts/extrema only; no positivity or dynamics gate",
            "mass_reduction": "vectorized per-role min/max and consecutive-active-saved-frame drift",
            "post_guard": "final stat/hash after all datasets and attributes are read",
        },
        "output": {"path": "{attempt_root}/scientific-field-h5-audit.json", "max_bytes": MAX_OUTPUT_BYTES},
        "read_policy": {"prepare_json_and_stat_only": True, "trajectory_h5_opened_by_preparer": False, "trajectory_h5_hashed_by_preparer": False, "trajectory_h5_opened_by_worker_after_reservation": True, "raw_bi4_opened": False, "solver_started": False, "legacy_model_fields_used": False},
        "claim_boundary": {"lifecycle_mask": "saved-record diagnostic only", "units": "producer declaration versus protocol comparison; authority UNKNOWN", "initial_type": "UNKNOWN when missing/invalid; no ALL_ACTIVE promotion", "material_and_mk": "dataset presence only; semantics UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(group_manifest_path, group_manifest)
    group_manifest_ref = static_ref(group_manifest_path, "group H5 audit manifest")
    request_static_refs = dedupe_refs([*static_refs, group_manifest_ref])
    input_paths = [ref["path"] for ref in request_static_refs]
    input_hashes = {ref["path"]: ref["sha256"] for ref in request_static_refs}
    request_path = group_dir / "scientific-field-h5-audit-request.json"
    request = {
        "schema": REQUEST_SCHEMA, "shared_runtime_version": "v8",
        "request_id": f"scientific-field-h5-batch-v2-{group_id}", "family_id": "infra", "case_id": f"scientific-field-h5-{group_id}",
        "physical_case_ids": [case["physical_case_id"] for case in cases], "attempt_id": f"scientific-field-h5-batch-v2-{group_id}",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": int(args.max_wall_seconds), "max_memory_bytes": int(args.max_memory_bytes), "estimated_storage_bytes": MAX_OUTPUT_BYTES,
        "estimated_cpu_core_hours": max(1.0, 0.35 * len(cases)), "estimated_gpu_seconds": 0,
        "cwd": str(LAB_ROOT), "worktree_root": str(LAB_ROOT),
        "command": [str(Path(args.python).expanduser()), "-B", str(Path(args.worker).expanduser().resolve()), "audit", "--manifest", str(group_manifest_path.resolve()), "--output", "{attempt_root}/scientific-field-h5-audit.json", "--chunk", str(args.chunk)],
        "input_files": input_paths, "input_sha256": input_hashes,
        "deferred_input_files": deferred_paths, "deferred_input_records": [case["trajectory_h5"] for case in cases],
        "output_files": ["{attempt_root}/scientific-field-h5-audit.json"], "manifest_contract": {"path": str(group_manifest_path.resolve()), "sha256": group_manifest_ref["sha256"]},
        "interpreter_binding": {"literal_path": str(Path(args.python).expanduser()), "resolved_path": str(source_file(args.python, "literal Python")), "sha256": next(ref["sha256"] for ref in request_static_refs if ref["path"] == str(source_file(args.python, "literal Python")))},
        "runtime_binding": {"runtime_v8": next(ref for ref in request_static_refs if ref["role"] == "runtime_v8"), "dispatch_v8": next(ref for ref in request_static_refs if ref["role"] == "dispatch_v8"), "strict_dispatch_v8": next(ref for ref in request_static_refs if ref["role"] == "strict_dispatch_v8"), "official_config": next(ref for ref in request_static_refs if ref["role"] == "official_runtime_config")},
        "source_read_cost": {"family": group["family_id"], "case_count": len(cases), "h5_bytes_by_case": {case["physical_case_id"]: case["trajectory_h5"]["bytes"] for case in cases}, "h5_bytes_total": sum(case["trajectory_h5"]["bytes"] for case in cases), "minimum_h5_passes_per_case": 3, "minimum_h5_passes_total": 3 * len(cases), "h5_content_read_by_preparer": False, "estimated_memory_bytes": int(args.max_memory_bytes), "output_cap_bytes": MAX_OUTPUT_BYTES},
        "read_policy": group_manifest["read_policy"], "claim_boundary": group_manifest["claim_boundary"], "launch_allowed": True, "execution_allowed": True, "launch_owner": "root", "shared_lease_required": True,
        "status": "SOURCE_PREPARED_GROUP_NOT_RUN", "request_note": "Metadata-only source preparation. V3 opens each deferred H5 only after parent reservation, processes one case at a time with vectorized chunk reductions, and captures post-read stat/hash; no scientific qualification is claimed.",
    }
    atomic_json(request_path, request)
    return {"group_id": group_id, "family_id": group["family_id"], "case_ids": [case["physical_case_id"] for case in cases], "case_count": len(cases), "deferred_h5_bytes": sum(case["trajectory_h5"]["bytes"] for case in cases), "manifest": {"path": str(group_manifest_path.resolve()), "sha256": group_manifest_ref["sha256"]}, "request": {"path": str(request_path.resolve()), "sha256": sha256_file(request_path)}, "source_read_policy": {"h5_opened_by_preparer": False, "h5_hashed_by_preparer": False}, "status": "SOURCE_PREPARED_GROUP_NOT_RUN"}


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    master_path = source_file(args.source_manifest, "335 source manifest")
    if sha256_file(master_path) != MASTER_SHA256:
        raise BatchPrepareError("335 source manifest SHA differs from frozen source index")
    master = json_object(master_path, "335 source manifest")
    case_map, group_map = _validate_master(master)
    current_path = source_file(args.current, "CURRENT336")
    if sha256_file(current_path) != CURRENT_SHA256:
        raise BatchPrepareError("CURRENT SHA differs from frozen CURRENT336")
    current = json_object(current_path, "CURRENT336")
    if current.get("schema") != "ds02.stage2.current336.v1":
        raise BatchPrepareError("CURRENT schema differs")
    current_rows = current.get("cases")
    if not isinstance(current_rows, list) or len(current_rows) != 336:
        raise BatchPrepareError("CURRENT must expose exactly 336 rows")
    current_map: dict[str, dict[str, Any]] = {}
    for row in current_rows:
        case_id = row.get("physical_case_id") if isinstance(row, dict) else None
        if not isinstance(case_id, str) or case_id in current_map:
            raise BatchPrepareError("CURRENT case IDs are not unique")
        current_map[case_id] = row
    if not set(case_map).issubset(current_map):
        raise BatchPrepareError("canonical case is missing from CURRENT")
    plan_ref = static_ref(source_file(args.plan, "CURRENT typed lifecycle plan"), "current_typed_lifecycle_plan") if args.plan else None
    registry_ref = static_ref(source_file(args.registry, "typed lifecycle registry"), "typed_lifecycle_registry") if args.registry else None
    current_ref = static_ref(current_path, "current336")
    source_manifest_ref = static_ref(master_path, "335_source_manifest", MASTER_SHA256)
    common_refs = _core_refs(args)
    groups = list(group_map.values())
    if args.limit_groups:
        if args.limit_groups <= 0 or args.limit_groups > len(groups):
            raise BatchPrepareError("--limit-groups must be within available groups")
        groups = groups[:args.limit_groups]
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    group_results = []
    for group in groups:
        group_dir = output_dir / f"group-{group['group_id']}"
        group_results.append(_build_group(group, case_map, current_map, common_refs, current_ref, source_manifest_ref, plan_ref, registry_ref, args, group_dir))
    index_path = output_dir / "scientific-field-h5-batch-v2-index.json"
    index = {
        "schema": "ds02.stage2.scientific-field-h5-batch-source.v2",
        "status": "SOURCE_PREPARED_BATCH_GROUPS_NOT_RUN",
        "source_manifest": {"path": str(master_path), "sha256": MASTER_SHA256, "canonical_cases": len(case_map), "canonical_groups": len(group_map)},
        "current_binding": {"path": str(current_path), "sha256": CURRENT_SHA256, "cases": 336, "alias_excluded": True},
        "group_bound": {"max_cases": MAX_GROUP_CASES, "max_deferred_h5_bytes": MAX_GROUP_H5_BYTES, "groups_prepared": len(group_results), "one_case_at_a_time": True},
        "groups": group_results,
        "source_read_policy": {"preparer_opened_h5": False, "preparer_hashed_h5": False, "preparer_opened_bi4": False, "launch_performed": False},
        "qualification_boundary": {"raw_field_finiteness": "PENDING_GUARDED_V3_SCAN", "units": "DECLARED_ONLY_UNVERIFIED", "material_and_mk": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(index_path, index)
    report_path = Path(args.report).expanduser().resolve() if args.report else output_dir / "scientific-field-h5-batch-v2-source-report.json"
    report = {
        "schema": "ds02.stage2.scientific-field-h5-batch-source-report.v2", "status": "SOURCE_PREPARED_BATCH_GROUPS_NOT_RUN",
        "index": {"path": str(index_path), "sha256": sha256_file(index_path)}, "group_count": len(group_results), "case_count": sum(row["case_count"] for row in group_results),
        "deferred_h5_bytes": sum(row["deferred_h5_bytes"] for row in group_results), "minimum_h5_passes": 3 * sum(row["case_count"] for row in group_results),
        "source_read_policy": index["source_read_policy"], "qualification_boundary": index["qualification_boundary"], "goal_complete": False,
    }
    atomic_json(report_path, report)
    return {"status": report["status"], "index": str(index_path), "index_sha256": sha256_file(index_path), "report": str(report_path), "report_sha256": sha256_file(report_path), "groups": len(group_results), "cases": report["case_count"], "deferred_h5_bytes": report["deferred_h5_bytes"], "h5_content_read_by_preparer": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, default=MASTER_DEFAULT)
    parser.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    parser.add_argument("--plan", type=Path, default=PLAN_DEFAULT)
    parser.add_argument("--registry", type=Path, default=REGISTRY_DEFAULT)
    parser.add_argument("--worker", type=Path, default=WORKER_DEFAULT)
    parser.add_argument("--v2-worker", type=Path, default=V2_WORKER_DEFAULT)
    parser.add_argument("--verifier", type=Path, default=VERIFIER_DEFAULT)
    parser.add_argument("--runtime", type=Path, default=RUNTIME_DEFAULT)
    parser.add_argument("--dispatch", type=Path, default=DISPATCH_DEFAULT)
    parser.add_argument("--strict", type=Path, default=STRICT_DEFAULT)
    parser.add_argument("--python", type=Path, default=VENV_DEFAULT)
    parser.add_argument("--config", type=Path, default=CONFIG_DEFAULT)
    parser.add_argument("--chunk", type=int, default=65536)
    parser.add_argument("--max-wall-seconds", type=int, default=3600)
    parser.add_argument("--max-memory-bytes", type=int, default=4 * 1024**3)
    parser.add_argument("--limit-groups", type=int, default=0, help="metadata-only test limit; omit for all 43 groups")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        value = prepare(args)
    except (BatchPrepareError, OSError) as exc:
        print(f"scientific-field-h5-batch-prepare: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

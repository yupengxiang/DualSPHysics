#!/usr/bin/env python3
"""ROOT233-V4 request builder with complete dictionary source closure.

The consumed ROOT233-V3 builder accidentally iterated the dictionary keys in
``base_request["input_records"]``.  Its generated request retained only the
newly added runtime records and therefore omitted the owner/proof/solver
receipt/RunPARTs/XML/decoder records from the static closure.  This additive
builder starts from the immutable ROOT229-V2 builder, consumes
``input_records.values()`` explicitly, and emits a fresh ROOT233-V4 request.
No ROOT233-V3 bytes are rewritten and no deferred Part file is opened.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import stage2_f1_s2_initial_support_observer_v2 as observer
import stage2_f1_s2_initial_support_request_v2 as base
import stage2_f1_s2_initial_support_request_v3 as v3


HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_f1_s2_initial_support_observer_v2.py"
BASE_WORKER = HERE / "stage2_f1_s2_initial_support_observer_v1.py"
V2_BUILDER = HERE / "stage2_f1_s2_initial_support_request_v2.py"
V3_BUILDER = HERE / "stage2_f1_s2_initial_support_request_v3.py"
BUILDER = HERE / "stage2_f1_s2_initial_support_request_v4.py"
CALIBRATED = HERE / "stage2_f1_native_selected_observer_v1.py"
BASE_OBSERVER = HERE / "stage2_native_physical_observer_v2.py"
ROOT = base.ROOT
PYTHON = base.PYTHON
PYTHON_TARGET = base.PYTHON_TARGET
PYVENV_CFG = base.PYVENV_CFG
MAX_SMALL_BYTES = 16 * 1024 * 1024
MAX_NATIVE_BYTES = 512 * 1024 * 1024
NATIVE_READ_PASSES = 4
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.initial-support-request.v4"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.initial-support-manifest.v2"


class BuildError(RuntimeError):
    pass


def stable_hash(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildError(f"{label} is not a regular non-symlink file: {path}")
    before = path.stat()
    if before.st_size > max_bytes:
        raise BuildError(f"{label} exceeds bounded preparation read: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise BuildError(f"{label} changed while being read: {path}")
    return {"path": str(path), "label": label, "bytes": int(after.st_size), "sha256": digest, "stat": {"dev": int(after.st_dev), "ino": int(after.st_ino), "bytes": int(after.st_size), "mtime_ns": int(after.st_mtime_ns), "ctime_ns": int(after.st_ctime_ns)}}


def write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise BuildError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _record_values(input_records: Any) -> list[dict[str, Any]]:
    if isinstance(input_records, dict):
        values = list(input_records.values())
    elif isinstance(input_records, list):
        values = input_records
    else:
        raise BuildError("base request input_records must be a dict or list")
    records = [value for value in values if isinstance(value, dict) and isinstance(value.get("path"), str)]
    if len(records) < 20:
        raise BuildError(f"base request source closure unexpectedly short: {len(records)}")
    return records


def _decorate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    result = v3._decorate_manifest(manifest)
    result["source_binding"] = {
        **(result.get("source_binding") if isinstance(result.get("source_binding"), dict) else {}),
        "root233_v3_static_closure_bug_preserved": True,
        "root233_v4_input_records_values_fix": True,
    }
    return result


def _add(records: dict[str, dict[str, Any]], path: Path, label: str) -> None:
    record = stable_hash(path, label)
    records[record["path"]] = record


def build(output_manifest: Path, output_request: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    output_manifest = output_manifest.expanduser().absolute()
    output_request = output_request.expanduser().absolute()
    with tempfile.TemporaryDirectory(prefix="root233-v4-build-") as temporary:
        temp_manifest = Path(temporary) / "manifest.json"
        temp_request = Path(temporary) / "request.json"
        # V2 is the consumed source builder.  V3 is used only for its tested
        # grid-label decorator; the V3 request's defective closure is not
        # reused.
        _, base_request = base.build(temp_manifest, temp_request)
        manifest = json.loads(temp_manifest.read_text(encoding="utf-8"))
    manifest = _decorate_manifest(manifest)
    records = {str(item["path"]): item for item in _record_values(base_request.get("input_records"))}
    records.pop(str(temp_manifest), None)
    records.pop(str(temp_manifest.absolute()), None)
    for path, label in (
        (WORKER, "ROOT233 V4 observer worker"),
        (BASE_WORKER, "ROOT229 legacy observer worker"),
        (V2_BUILDER, "ROOT229 V2 request builder"),
        (V3_BUILDER, "ROOT233 V3 request builder dependency"),
        (BUILDER, "ROOT233 V4 request builder"),
        (CALIBRATED, "calibrated native observer"),
        (BASE_OBSERVER, "native observer base"),
        (ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py", "runtime V8"),
        (ROOT / "lagrangian-fluid-lab/scripts/ds_data02_batch_runner.py", "batch runner"),
        (ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py", "stage2 dispatch V8"),
        (ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py", "strict dispatch V8"),
        (PYVENV_CFG, "literal venv configuration"),
        (PYTHON_TARGET, "resolved Python target"),
    ):
        _add(records, path, label)
    required_labels = ("ROOT227 owner proof", "ROOT207 proof", "ROOT217 calibration proof", "coarse RunPARTs", "medium RunPARTs", "fine RunPARTs", "coarse generated XML", "medium generated XML", "fine generated XML", "fine official decoder")
    labels = {str(item.get("label")) for item in records.values()}
    missing = [label for label in required_labels if label not in labels]
    if missing:
        raise BuildError(f"ROOT233 V4 source closure missing required records: {missing}")
    manifest["static_source_records"] = list(records.values())
    write_once(output_manifest, manifest)
    manifest_record = stable_hash(output_manifest, "ROOT233 V4 manifest")
    records[manifest_record["path"]] = manifest_record
    deferred = manifest["deferred_native_records"]
    native_read_bytes = len(deferred) * MAX_NATIVE_BYTES * NATIVE_READ_PASSES
    static_bytes = sum(int(item.get("bytes", 0)) for item in records.values())
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "READY_FOR_PARENT_V8_F1_S2_INITIAL_SUPPORT_ROOT233_V4",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "request_id": "f1-s2-initial-support-audit-root233-v4-002",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "case_id": "F1_S2_INITIAL_SUPPORT_AUDIT_ROOT233_V4",
        "attempt_id": "f1-s2-initial-support-audit-root233-v4-002",
        "cwd": str(ROOT),
        "worktree_root": str(ROOT),
        "command": [str(PYTHON), "-B", str(WORKER), "--manifest", "{attempt_root}/inputs/f1_s2_initial_support_manifest_v2.json", "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/observer/f1_s2_initial_support_observer_v2.json"],
        "literal_venv_invocation": {"path": str(PYTHON), "argv0_literal": True, "resolved_target": str(PYTHON_TARGET), "pyvenv_cfg": str(PYVENV_CFG)},
        "input_files": sorted(records),
        "input_sha256": {path: item["sha256"] for path, item in records.items()},
        "input_records": records,
        "manifest": manifest_record,
        "deferred_input_files": sorted(item["path"] for item in deferred),
        "deferred_input_records": deferred,
        "deferred_input_policy": {"parent_after_reservation_first_sha_and_stat": True, "parent_after_child_post_sha_and_stat": True, "required_stat_fields": ["bytes", "mtime_ns", "ctime_ns", "dev", "ino"], "producer_known_sha_is_not_builder_computed": True, "source_replace_or_stat_change": "FAIL", "selected_frame_count": 3},
        "grid_label_normalization": {"builder_emits_both": True, "reader_requires_equal_grid_and_grid_label": True, "missing_or_conflicting": "FAIL"},
        "source_binding": {"manifest": str(output_manifest), "root229_failure_preserved": True, "root233_v3_failure_preserved": True, "root233_v4_input_records_values_fix": True, "owner_mass_kg": 340.0, "native_sample_mass_separate": True, "axis_scope": "component-space support only; producer world-axis remains UNKNOWN", "position_support_tolerance_m": 1.0e-6, "position_tolerance_is_task_error": False, "interpolation": "FORBIDDEN", "neighbor_grid_truth": False},
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "max_memory_bytes": 2 * 1024**3,
        "max_storage_bytes": 512 * 1024**2,
        "estimated_peak_memory_bytes": 2 * 1024**3,
        "estimated_scratch_bytes": 512 * 1024**2,
        "estimated_storage_bytes": 512 * 1024**2,
        "estimated_native_read_passes": NATIVE_READ_PASSES,
        "estimated_native_read_bytes": native_read_bytes,
        "estimated_native_read_bytes_is_conservative_upper_bound": True,
        "estimated_input_read_bytes": static_bytes + native_read_bytes,
        "estimated_input_read_bytes_scope": "complete bounded static owner/proof/receipt/RunPARTs/XML/decoder closure plus three deferred Part files at the 512 MiB cap and four worker/decoder passes",
        "estimated_hdf5_read_bytes": 0,
        "runtime_closure": {"literal_python": {"path": str(PYTHON), "resolved_target": str(PYTHON_TARGET), "pyvenv_cfg": str(PYVENV_CFG)}, "worker": str(WORKER), "base_worker": str(BASE_WORKER), "v2_builder": str(V2_BUILDER), "v3_builder": str(V3_BUILDER), "calibrated_observer": str(CALIBRATED), "base_observer": str(BASE_OBSERVER), "parent_v8_deferred_sha_stat_gate": True},
        "storage_scope": {"output_root": "{attempt_root}", "native_payload_read": "three deferred frame-0 Part_0000.bi4 files only", "h5_vtk_allowed": False, "full_native_tree_scan": False, "solver_launch": False},
        "resources": {"gpu": False, "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "memory_max_bytes": 2 * 1024**3, "external_storage_max_bytes": 512 * 1024**2, "home_storage_max_bytes": 128 * 1024**2, "log_max_bytes": 512 * 1024, "parent_guard_required": True},
        "scope": {"selected_frame": 0, "continuous_owner_mass_kg": 340.0, "native_sample_mass_separate": True, "support_checks": ["finite", "owner_box_containment", "divider_disjoint", "typed_role_and_mk", "native_header_mass_and_dp", "pre_post_source_stability"], "science_Q": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}},
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "ledger_mutation": False,
        "qualification_credit": 0,
    }
    write_once(output_request, request)
    return manifest, request


def self_test() -> None:
    valid_values = {f"key{index}": {"path": f"path{index}"} for index in range(20)}
    assert _record_values(valid_values) == list(valid_values.values())
    try:
        _record_values([{"no_path": True}] * 19)
    except BuildError:
        pass
    else:
        raise AssertionError("short source closure was accepted")
    shaped = {"grids": [{"label": "coarse"}, {"label": "medium"}, {"label": "fine"}], "deferred_native_records": [{"path": "coarse.bi4"}, {"path": "medium.bi4"}, {"path": "fine.bi4"}]}
    decorated = _decorate_manifest(shaped)
    normalized = observer.normalize_deferred_records(decorated)
    assert [(item["grid"], item["grid_label"]) for item in normalized["deferred_native_records"]] == [("coarse", "coarse"), ("medium", "medium"), ("fine", "fine")]
    print("PASS_F1_S2_INITIAL_SUPPORT_REQUEST_V4_SOURCE_CLOSURE_AND_ENTRY_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--output-manifest", type=Path)
    parser.add_argument("--output-request", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output_manifest is None or args.output_request is None:
        parser.error("--output-manifest and --output-request are required with --build")
    try:
        build(args.output_manifest, args.output_request)
    except (BuildError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"FAIL_F1_S2_INITIAL_SUPPORT_REQUEST_V4: {exc}")
        return 2
    print(f"PASS_PREPARED_F1_S2_INITIAL_SUPPORT_V4 {args.output_manifest} {args.output_request}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

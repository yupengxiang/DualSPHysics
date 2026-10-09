#!/usr/bin/env python3
"""Build the additive ROOT233 F1-S2 initial-support request.

ROOT229's consumed request is immutable.  ROOT233 keeps its source joins and
adds an explicit ``grid``/``grid_label`` pair to every deferred frame-0
record.  The matching worker validates that pair before entering the legacy
component-space support decoder, so a parent manifest using either historical
spelling cannot silently select the wrong grid.

Preparation reads only bounded source/proof metadata.  The three native Part
files remain deferred to the parent reservation and are never opened here.
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


HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_f1_s2_initial_support_observer_v2.py"
BASE_WORKER = HERE / "stage2_f1_s2_initial_support_observer_v1.py"
CALIBRATED = HERE / "stage2_f1_native_selected_observer_v1.py"
BASE_OBSERVER = HERE / "stage2_native_physical_observer_v2.py"
ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYTHON_TARGET = Path("/usr/bin/python3.10")
PYVENV_CFG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg")
MAX_SMALL_BYTES = 16 * 1024 * 1024
MAX_NATIVE_BYTES = 512 * 1024 * 1024
NATIVE_READ_PASSES = 4
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.initial-support-request.v3"
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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    before_sig = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    after_sig = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if before_sig != after_sig:
        raise BuildError(f"{label} changed while being read: {path}")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(after.st_size),
        "sha256": digest.hexdigest(),
        "stat": {
            "dev": int(after.st_dev),
            "ino": int(after.st_ino),
            "bytes": int(after.st_size),
            "mtime_ns": int(after.st_mtime_ns),
            "ctime_ns": int(after.st_ctime_ns),
        },
    }


def write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise BuildError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _decorate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    grids = manifest.get("grids")
    deferred = manifest.get("deferred_native_records")
    if not isinstance(grids, list) or len(grids) != 3:
        raise BuildError("ROOT233 requires exactly three grid records")
    labels = [item.get("label") for item in grids if isinstance(item, dict)]
    if labels != ["coarse", "medium", "fine"]:
        raise BuildError(f"ROOT233 grid order/labels are not frozen: {labels!r}")
    if not isinstance(deferred, list) or len(deferred) != 3:
        raise BuildError("ROOT233 requires exactly three deferred frame-0 records")
    normalized: list[dict[str, Any]] = []
    for index, (record, label) in enumerate(zip(deferred, labels, strict=True)):
        if not isinstance(record, dict):
            raise BuildError(f"deferred record {index} is not an object")
        supplied = [record.get(key) for key in ("grid", "grid_label", "case_label")]
        supplied_labels = [value for value in supplied if isinstance(value, str) and value]
        if supplied_labels and any(value != label for value in supplied_labels):
            raise BuildError(f"deferred record {index} label conflicts with grid {label!r}")
        item = dict(record)
        item["grid"] = label
        item["grid_label"] = label
        normalized.append(item)
    result = dict(manifest)
    result["schema"] = MANIFEST_SCHEMA
    result["status"] = "PREPARED_NOT_RUN_ROOT233_INITIAL_SUPPORT_SOURCE_AUDIT"
    result["deferred_native_records"] = normalized
    result["deferred_record_label_normalization"] = {
        "required_keys": ["grid", "grid_label"],
        "values": ["coarse", "medium", "fine"],
        "source": "ROOT233 builder decorates builder-shaped records and worker rechecks at entry",
    }
    result["source_binding"] = {
        **(result.get("source_binding") if isinstance(result.get("source_binding"), dict) else {}),
        "root229_failure_preserved": True,
        "grid_label_normalization": "exact_grid_and_grid_label_pair",
        "axis_scope": "component-space support only; producer world-axis remains UNKNOWN",
    }
    return result


def _record_map(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        path = record.get("path") if isinstance(record, dict) else None
        if isinstance(path, str):
            result[path] = record
    return result


def _add_source(records: dict[str, dict[str, Any]], path: Path, label: str) -> None:
    record = stable_hash(path, label)
    records[record["path"]] = record


def build(output_manifest: Path, output_request: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    output_manifest = output_manifest.expanduser().absolute()
    output_request = output_request.expanduser().absolute()
    # Build the consumed V2 envelope in a temporary directory.  This keeps
    # its immutable ROOT229 output untouched while retaining its actual
    # proof/source joins as the input to this forward request.
    with tempfile.TemporaryDirectory(prefix="root233-request-") as temporary:
        temp_manifest = Path(temporary) / "legacy-manifest.json"
        temp_request = Path(temporary) / "legacy-request.json"
        _, base_request = base.build(temp_manifest, temp_request)
        manifest = json.loads(temp_manifest.read_text(encoding="utf-8"))
    manifest = _decorate_manifest(manifest)
    manifest["observer_worker"] = {"path": str(WORKER), "schema": observer.SCHEMA}
    manifest["read_scope"] = {
        "native_payload_read": "three deferred frame-0 Part_0000.bi4 files only",
        "selected_frame_count": 3,
        "hdf5_read": False,
        "vtk_read": False,
        "full_native_tree_scan": False,
        "solver_launch": False,
    }
    # Start from the source records assembled by the V2 envelope, dropping
    # only its temporary manifest path.  Add the actual V2 worker, this V3
    # builder, and the runtime files used by the parent admission gate.
    records = _record_map([item for item in base_request.get("input_records", []) if isinstance(item, dict)])
    records.pop(str(temp_manifest), None)
    records.pop(str(temp_manifest.absolute()), None)
    for path, label in (
        (WORKER, "ROOT233 observer worker"),
        (BASE_WORKER, "ROOT229 legacy observer worker"),
        (CALIBRATED, "calibrated native observer"),
        (BASE_OBSERVER, "native observer base"),
        (HERE / "stage2_f1_s2_initial_support_request_v2.py", "ROOT229 V2 request builder"),
        (HERE / "stage2_f1_s2_initial_support_request_v1.py", "ROOT229 V1 request builder"),
        (ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py", "runtime V8"),
        (ROOT / "lagrangian-fluid-lab/scripts/ds_data02_batch_runner.py", "batch runner"),
        (ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py", "stage2 dispatch V8"),
        (ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py", "strict dispatch V8"),
        (PYVENV_CFG, "literal venv configuration"),
        (PYTHON_TARGET, "resolved Python target"),
    ):
        _add_source(records, path, label)
    static_records = list(records.values())
    manifest["static_source_records"] = static_records
    # The worker checks the final manifest's static records, so write it only
    # after this closure has been assembled.  The final output is still an
    # atomic write-once artifact; there is no delete-and-rewrite window.
    write_once(output_manifest, manifest)
    manifest_record = stable_hash(output_manifest, "ROOT233 final manifest")
    records[manifest_record["path"]] = manifest_record

    deferred = manifest["deferred_native_records"]
    native_read_bytes = len(deferred) * MAX_NATIVE_BYTES * NATIVE_READ_PASSES
    static_bytes = sum(int(item.get("bytes", 0)) for item in records.values())
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "READY_FOR_PARENT_V8_F1_S2_INITIAL_SUPPORT_ROOT233",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "request_id": "f1-s2-initial-support-audit-root233-v3-001",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "case_id": "F1_S2_INITIAL_SUPPORT_AUDIT_ROOT233_V3",
        "attempt_id": "f1-s2-initial-support-audit-root233-v3-001",
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
        "grid_label_normalization": {"worker_entry": "grid and grid_label required and equal", "builder_entry": "both keys emitted for coarse/medium/fine", "missing_or_conflicting": "FAIL"},
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
        "estimated_input_read_bytes_scope": "static metadata plus three deferred Part files at the 512 MiB cap and four worker/decoder passes; actual bytes remain parent-measured",
        "estimated_hdf5_read_bytes": 0,
        "runtime_closure": {"literal_python": {"path": str(PYTHON), "resolved_target": str(PYTHON_TARGET), "pyvenv_cfg": str(PYVENV_CFG)}, "worker": str(WORKER), "legacy_worker": str(BASE_WORKER), "base_builder": str(HERE / "stage2_f1_s2_initial_support_request_v2.py"), "calibrated_observer": str(CALIBRATED), "base_observer": str(BASE_OBSERVER), "parent_v8_deferred_sha_stat_gate": True},
        "storage_scope": {"output_root": "{attempt_root}", "native_payload_read": "three deferred frame-0 Part_0000.bi4 files only", "h5_vtk_allowed": False, "full_native_tree_scan": False, "solver_launch": False},
        "source_binding": {"manifest": str(output_manifest), "root229_failure_preserved": True, "owner_mass_kg": 340.0, "native_sample_mass_separate": True, "axis_scope": "component-space support only; producer world-axis remains UNKNOWN", "position_support_tolerance_m": 1.0e-6, "position_tolerance_is_task_error": False, "interpolation": "FORBIDDEN", "neighbor_grid_truth": False},
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
    # Exercise the actual builder-shaped manifest entry, then send that same
    # object through the reader normalizer.  This catches the ROOT229 failure
    # at the builder/worker boundary rather than only testing a helper in
    # isolation.
    shaped = {"grids": [{"label": "coarse"}, {"label": "medium"}, {"label": "fine"}], "deferred_native_records": [{"path": "coarse.bi4"}, {"path": "medium.bi4"}, {"path": "fine.bi4"}]}
    decorated = _decorate_manifest(shaped)
    normalized = observer.normalize_deferred_records(decorated)
    assert [(item["grid"], item["grid_label"]) for item in normalized["deferred_native_records"]] == [("coarse", "coarse"), ("medium", "medium"), ("fine", "fine")]
    for bad in (
        {"grids": shaped["grids"], "deferred_native_records": [{"path": "a", "grid": "fine"}, {"path": "b"}, {"path": "c"}]},
        {"grids": shaped["grids"], "deferred_native_records": [{"path": "a"}, {"path": "b"}, {"path": "c", "grid_label": "coarse"}]},
    ):
        try:
            _decorate_manifest(bad)
        except BuildError:
            pass
        else:
            raise AssertionError("builder accepted a conflicting grid label")
    print("PASS_F1_S2_INITIAL_SUPPORT_REQUEST_V3_BUILDER_READER_ENTRY_SELFTEST")


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
        print(f"FAIL_F1_S2_INITIAL_SUPPORT_REQUEST_V3: {exc}")
        return 2
    print(f"PASS_PREPARED_F1_S2_INITIAL_SUPPORT_V3 {args.output_manifest} {args.output_request}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

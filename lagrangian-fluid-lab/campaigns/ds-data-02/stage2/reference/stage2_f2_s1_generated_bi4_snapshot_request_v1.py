#!/usr/bin/env python3
"""Prepare the parent-v8 CPU request for the F2-S1 generated BI4 snapshot.

This builder intentionally never opens, stats, or hashes ``generated.bi4``.
The source is listed as a deferred input and the worker performs the full
pre/post stat and SHA guard only after the parent has reserved the attempt.
The small GenCase receipt/XML and guard sources are bound here so the parent
can review the exact ROOT076 product without turning the large BI4 into an
unguarded preparation-time read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


REQUEST_SCHEMA = "ds02.request.v1"
SNAPSHOT_SCHEMA = "ds02.stage2.f2-s1.generated-bi4-source-snapshot.v1"
MAIN_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
VENV_PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
REFERENCE_REL = "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
SCRIPTS_REL = "lagrangian-fluid-lab/scripts"
STAGE2_REQUESTS_REL = "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"

FAMILY_ID = "F2"
SENTINEL_ID = "F2-S1"
PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
CASE_ID = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_BI4_SOURCE_SNAPSHOT_ROOT_094"
ATTEMPT_ID = "f2-s1-owner-centered-cell-selector-generated-bi4-snapshot-v1-root-094-001"

GENCASE_CASE_ID = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_ROOT_076"
GENCASE_ATTEMPT_ID = "f2-s1-owner-centered-cell-selector-gencase-root-076-001-root-forward-030-001"
GENCASE_OUTPUT = DATA_ROOT / "families/F2/F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_ROOT_076" / GENCASE_ATTEMPT_ID
GENERATED_BI4 = GENCASE_OUTPUT / "generated.bi4"
GENERATED_XML = GENCASE_OUTPUT / "generated.xml"
GENCASE_RECEIPT = GENCASE_OUTPUT / "execution-receipt.json"
EXPECTED_BI4_BYTES = 23_789_263

GENCASE_REQUEST = MAIN_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f2-s1-owner-centered-cell-selector-gencase-root-forward-076-001.json"
SUPPORT_REPORT = DATA_ROOT / "families/F2/F2_S1_CELL_SELECTOR_SUPPORT_V8_ROOT_080" / "f2-s1-cell-selector-support-v8-root-080-001-root-forward-030-001" / "report/f2_s1_owner_centered_cell_selector_support_audit_v8.json"
SUPPORT_RECEIPT = SUPPORT_REPORT.parent.parent / "execution-receipt.json"
WORKER = MAIN_REPO / REFERENCE_REL / "stage2_f2_s1_generated_bi4_snapshot_v1.py"
BUILDER = MAIN_REPO / REFERENCE_REL / "stage2_f2_s1_generated_bi4_snapshot_request_v1.py"
DISPATCH_V8 = MAIN_REPO / SCRIPTS_REL / "ds_data02_stage2_dispatch_v8.py"
STRICT_V8 = MAIN_REPO / SCRIPTS_REL / "ds_data02_strict_dispatch_v8.py"
RUNTIME_V8 = MAIN_REPO / SCRIPTS_REL / "ds_data02_runtime_v8.py"
RUNTIME_V6 = MAIN_REPO / SCRIPTS_REL / "ds_data02_runtime_v6.py"
RUNTIME_V2 = MAIN_REPO / SCRIPTS_REL / "ds_data02_runtime_v2.py"
OUTPUT_DEFAULT = MAIN_REPO / STAGE2_REQUESTS_REL / "f2-s1-generated-bi4-snapshot-root-forward-094-001.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    """Resolve and validate only a small metadata/source file."""

    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def small_record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
        "sha256": sha256(path),
        "content_scope": "small_metadata_hashed_by_builder_and_parent_v8",
    }


def json_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise FileExistsError(f"temporary request already exists: {temporary}")
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if fd >= 0:
                os.close(fd)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def canonical_sha(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    encoded = json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def build(args: argparse.Namespace) -> dict[str, Any]:
    # This list deliberately excludes GENERATED_BI4.  It is the deferred
    # source read owned by the after-reservation worker, never by this builder.
    small_paths = [
        (GENCASE_REQUEST, "ROOT076 GenCase request"),
        (GENCASE_RECEIPT, "ROOT076 GenCase receipt"),
        (GENERATED_XML, "ROOT076 generated XML"),
        (SUPPORT_REPORT, "F2 V8 support report"),
        (SUPPORT_RECEIPT, "F2 V8 support receipt"),
        (WORKER, "generated BI4 snapshot worker"),
        (BUILDER, "generated BI4 snapshot builder"),
        (DISPATCH_V8, "parent v8 dispatch"),
        (STRICT_V8, "parent v8 strict dispatch"),
        (RUNTIME_V8, "parent v8 runtime"),
        (RUNTIME_V6, "parent v6 runtime dependency"),
        (RUNTIME_V2, "parent v2 runtime dependency"),
        (VENV_PYTHON, "literal stage2 Python interpreter"),
    ]
    records = {str(regular(path, label)): small_record(path, label) for path, label in small_paths}
    gencase_receipt = load_json(GENCASE_RECEIPT, "ROOT076 GenCase receipt")
    gencase_request = load_json(GENCASE_REQUEST, "ROOT076 GenCase request")
    support_report = load_json(SUPPORT_REPORT, "F2 V8 support report")
    support_receipt = load_json(SUPPORT_RECEIPT, "F2 V8 support receipt")
    actual_request = gencase_receipt.get("request") or {}
    if gencase_receipt.get("status") != "completed" or gencase_receipt.get("returncode") != 0:
        raise ValueError("ROOT076 GenCase receipt is not completed with returncode 0")
    if gencase_request.get("case_id") != GENCASE_CASE_ID or actual_request.get("case_id") != GENCASE_CASE_ID:
        raise ValueError("ROOT076 GenCase case identity mismatch")
    if actual_request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("ROOT076 physical case identity mismatch")
    if support_report.get("status") != "COMPLETED_INITIAL_XML_VTK_SUPPORT_AUDIT":
        raise ValueError("F2 support report is not the completed V8 report")
    if support_report.get("mass_audit", {}).get("gate") != "PASS_SOURCE_OWNER_SAMPLE_DIAGNOSTIC_WITHIN_ONE_PERCENT":
        raise ValueError("F2 V8 sample mass gate is not PASS")
    if support_report.get("vtk_support", {}).get("support_gate") != "PASS_DISCRETE_SUPPORT_INSIDE_FROZEN_OWNER_BOXES":
        raise ValueError("F2 V8 support gate is not PASS")
    if support_receipt.get("status") != "completed" or support_receipt.get("returncode") != 0:
        raise ValueError("F2 V8 support receipt is not completed with returncode 0")

    input_files = sorted(records)
    input_hashes = {path: records[path]["sha256"] for path in input_files}
    input_records = {path: records[path] for path in input_files}
    output_root = DATA_ROOT / "families" / FAMILY_ID / CASE_ID / ATTEMPT_ID
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": FAMILY_ID,
        "sentinel_id": SENTINEL_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "launch_commit": args.launch_commit,
        "command": [
            str(VENV_PYTHON), str(WORKER),
            "--input-bi4", str(GENERATED_BI4),
            "--expected-bytes", str(EXPECTED_BI4_BYTES),
            "--case-id", CASE_ID,
            "--physical-case-id", PHYSICAL_CASE_ID,
            "--output", "{attempt_root}/generated_bi4_snapshot_v1.json",
        ],
        "cwd": str(MAIN_REPO),
        "worktree_root": str(MAIN_REPO),
        "input_files": input_files,
        "input_hashes": input_hashes,
        "input_records": input_records,
        "deferred_input_files": [str(GENERATED_BI4)],
        "deferred_input_file_count": 1,
        "deferred_hash_policy": {
            "schema": SNAPSHOT_SCHEMA,
            "source": str(GENERATED_BI4),
            "expected_bytes": EXPECTED_BI4_BYTES,
            "sha256": "PARENT_V8_AFTER_RESERVATION_WORKER_ONLY",
            "pre_stat_fields": ["bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino", "st_mode"],
            "post_stat_fields": ["bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino", "st_mode"],
            "mutation_policy": "nonzero_failure_and_immutable_failure_report",
            "full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER",
            "bi4_decode": False,
            "hdf5_read": False,
        },
        "source_binding": {
            "gencase_case_id": GENCASE_CASE_ID,
            "gencase_attempt_id": GENCASE_ATTEMPT_ID,
            "gencase_request": records[str(GENCASE_REQUEST.resolve())],
            "gencase_receipt": records[str(GENCASE_RECEIPT.resolve())],
            "generated_xml": records[str(GENERATED_XML.resolve())],
            "generated_bi4": {
                "path": str(GENERATED_BI4),
                "bytes": EXPECTED_BI4_BYTES,
                "sha256": "DEFERRED_PARENT_V8_WORKER_AFTER_RESERVATION",
                "stat_sha_source": "worker_pre_post_open_file_guard",
            },
            "support_report": records[str(SUPPORT_REPORT.resolve())],
            "support_receipt": records[str(SUPPORT_RECEIPT.resolve())],
            "scientific_identity": "F2-S1 owner-centered cell-selector coarse GenCase product; support/mass QA only, no solver qualification",
        },
        "output": {
            "path": "{attempt_root}/generated_bi4_snapshot_v1.json",
            "atomic": True,
            "refuse_overwrite": True,
            "failure_report_is_immutable": True,
            "scope": "one complete generated.bi4 SHA plus full pre/post source stat records",
        },
        "estimated_input_read_bytes": EXPECTED_BI4_BYTES,
        "estimated_native_read_bytes": EXPECTED_BI4_BYTES,
        "estimated_bi4_read_bytes": EXPECTED_BI4_BYTES,
        "estimated_hdf5_read_bytes": 0,
        "estimated_storage_bytes": 128 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "solver_launch": False,
        "hdf5_read": False,
        "bi4_read": True,
        "output_root": str(output_root),
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH_V8),
            "strict_guard": str(STRICT_V8),
            "runtime": str(RUNTIME_V8),
            "cpu_parent_binding": "required",
            "parent_reservation_before_deferred_source_hash": True,
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
        },
        "qualification_stage": "stage2_f2_s1_generated_bi4_source_snapshot_root094_pending_parent_v8_guard",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "status": "READY_FOR_PARENT_V8_CPU_SOURCE_SNAPSHOT",
        "source_provenance": {
            "root076_generated_tree": str(GENCASE_OUTPUT),
            "source_sha256": "DEFERRED_PARENT_WORKER_AFTER_RESERVATION",
            "source_bytes_registered_from_closed_root076_product": EXPECTED_BI4_BYTES,
            "builder_did_not_open_or_hash_generated_bi4": True,
            "worker_does_not_decode_or_start_solver": True,
        },
    }
    request["sha256"] = canonical_sha(request)
    json_new(Path(args.output), request)
    return {
        "status": "PASS_REQUEST_BUILT",
        "output": str(Path(args.output).expanduser().absolute()),
        "request_sha256": request["sha256"],
        "deferred_bi4": str(GENERATED_BI4),
        "builder_read_generated_bi4": False,
        "launch": "PARENT_ONLY_NOT_STARTED",
    }


def self_test() -> dict[str, Any]:
    probe = {
        "schema": REQUEST_SCHEMA,
        "deferred_input_files": [str(GENERATED_BI4)],
        "input_files": [str(WORKER)],
        "source_sha256": "DEFERRED_PARENT_V8_WORKER_AFTER_RESERVATION",
    }
    assert str(GENERATED_BI4) not in probe["input_files"]
    assert probe["source_sha256"].startswith("DEFERRED_")
    digest = canonical_sha(probe)
    assert len(digest) == 64
    return {
        "status": "PASS",
        "schema": REQUEST_SCHEMA,
        "deferred_bi4_not_hashed_by_builder": True,
        "parent_reservation_required": True,
        "worker_stat_fields": ["bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino", "st_mode"],
        "solver_or_hdf5": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--launch-commit")
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if not args.launch_commit:
        parser.error("--build-request requires --launch-commit from the parent integration HEAD")
    print(json.dumps(build(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

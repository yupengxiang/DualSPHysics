#!/usr/bin/env python3
"""Build the post-GenCase V6 F2-S1 support/mass audit request.

The request is intentionally separate from the V6 GenCase request.  It is
launched only after the parent has a terminal V6 receipt and reserves one
small CPU/XML/VTK audit slot.  The builder reads metadata and hashes of the
already-bound static inputs; it does not read the deferred generated VTK or
BI4 payload while preparing the request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[5]
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
V6_BUILDER = REFERENCE / "stage2_f2_s1_source_centered_v6_support_repair_v1.py"
V6_MANIFEST = REFERENCE / "stage2_f2_s1_source_centered_v6_support_repair_manifest_v1.json"
V6_AUDIT = REFERENCE / "stage2_f2_s1_source_centered_v6_support_repair_audit_v1.json"
V6_REQUEST = STAGE2 / "requests/stage2-f2-s1-source-centered-v6-support-repair-v1/f2_s1_source_centered_v6_actual_fluid_dp0p0088_gencase.json"
V6_WORKER = REFERENCE / "stage2_f2_s1_source_centered_v6_support_audit_v1.py"
V4_WORKER = REFERENCE / "stage2_f2_s1_inner_native_geometry_audit_v4.py"
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
REQUEST = STAGE2 / "requests/f2-s1-source-centered-v6-support-audit-root-forward-001.json"
REPORT = REFERENCE / "stage2_f2_s1_source_centered_v6_support_audit_request_v1.json"
AUDIT_CASE = "F2_S1_SOURCE_CENTERED_V6_SUPPORT_MASS_AUDIT"
AUDIT_ATTEMPT = "f2-s1-source-centered-v6-support-audit-root-forward-001"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def record(path: Path) -> dict[str, Any]:
    path = regular(path)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def build(launch_commit: str) -> dict[str, Any]:
    v6 = json.loads(regular(V6_REQUEST).read_text(encoding="utf-8"))
    manifest = json.loads(regular(V6_MANIFEST).read_text(encoding="utf-8"))
    candidate = Path(v6["source_binding"]["candidate_def"]["path"])
    source_def = Path(v6["source_binding"]["source_def"]["path"])
    source_motion = Path(v6["source_binding"]["source_motion"]["path"])
    v6_output = Path(v6["output_root"])
    generated_xml = v6_output / "generated.xml"
    fluid_vtk = v6_output / "generated_Fluid.vtk"
    receipt = v6_output / "execution-receipt.json"
    output_root = DATA_ROOT / "families/F2" / AUDIT_CASE / AUDIT_ATTEMPT

    static_paths = [
        Path(__file__), V6_BUILDER, V6_MANIFEST, V6_AUDIT, V6_REQUEST,
        V6_WORKER, V4_WORKER, candidate, source_def, source_motion,
        DISPATCH, STRICT, RUNTIME, PYTHON,
    ]
    static_paths = list(dict.fromkeys(regular(path) for path in static_paths))
    records = {str(path): record(path) for path in static_paths}
    expected = {
        "candidate_def": records[str(candidate)]["sha256"],
        "source_def": records[str(source_def)]["sha256"],
        "source_motion": records[str(source_motion)]["sha256"],
    }
    command = [
        str(PYTHON), str(V6_WORKER),
        "--generated-xml", str(generated_xml),
        "--fluid-vtk", str(fluid_vtk),
        "--receipt", str(receipt),
        "--candidate-def", str(candidate),
        "--source-def", str(source_def),
        "--source-motion", str(source_motion),
        "--expected-candidate-sha", expected["candidate_def"],
        "--expected-source-def-sha", expected["source_def"],
        "--expected-source-motion-sha", expected["source_motion"],
        "--output", "{attempt_root}/report/f2_s1_source_centered_v6_support_audit.json",
    ]
    request = {
        "schema": "ds02.request.v1",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F2",
        "sentinel_id": "F2-S1",
        "physical_case_id": v6["physical_case_id"],
        "case_id": AUDIT_CASE,
        "attempt_id": AUDIT_ATTEMPT,
        "launch_commit": launch_commit,
        "command": command,
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": list(records),
        "input_hashes": {path: item["sha256"] for path, item in records.items()},
        "input_records": records,
        "deferred_input_files": [str(generated_xml), str(fluid_vtk), str(receipt)],
        "deferred_input_stats": {
            str(generated_xml): {"sha256": "PARENT_GUARD_COMPUTED", "stat": "PARENT_GUARD_COMPUTED"},
            str(fluid_vtk): {"sha256": "PARENT_GUARD_COMPUTED", "stat": "PARENT_GUARD_COMPUTED"},
            str(receipt): {"sha256": "PARENT_GUARD_COMPUTED", "stat": "PARENT_GUARD_COMPUTED"},
        },
        "guarded_input_files": [str(generated_xml), str(fluid_vtk), str(receipt)],
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "max_memory_bytes": 2 * 1024**3,
        "max_storage_bytes": 64 * 1024**2,
        "estimated_input_read_bytes": 8 * 1024**2,
        "estimated_output_bytes": 4 * 1024**2,
        "estimated_storage_bytes": 64 * 1024**2,
        "estimated_peak_memory_bytes": 2 * 1024**3,
        "estimated_native_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "solver_launch": False,
        "hdf5_read": False,
        "bi4_read": False,
        "output_root": str(output_root),
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/report/f2_s1_source_centered_v6_support_audit.json"},
        "source_binding": {
            "schema": "ds02.stage2.f2-s1.source-centered-v6-support-audit-binding.v1",
            "v6_gencase_request": record(V6_REQUEST),
            "v6_manifest": record(V6_MANIFEST),
            "v6_static_audit": record(V6_AUDIT),
            "candidate_def": records[str(candidate)],
            "source_def": records[str(source_def)],
            "source_motion": records[str(source_motion)],
            "expected_static_sha256": expected,
            "generated_inputs": {
                "generated_xml": str(generated_xml),
                "generated_fluid_vtk": str(fluid_vtk),
                "execution_receipt": str(receipt),
                "must_be_terminal_v6_gencase_output": True,
            },
            "owner_mass_kg": 18.876,
            "predicted_count_is_not_gate": True,
        },
        "guard_policy": {
            "parent_terminal_v6_receipt_required": True,
            "pre_post_complete_stat_and_sha": "required for generated XML, Fluid.vtk, receipt, candidate Def, source Def, source motion",
            "worker_reads": "generated.xml + generated_Fluid.vtk + receipt + small static XML/source files only",
            "bi4_read": False,
            "hdf5_read": False,
            "solver_launch": False,
            "source_output_protection": "read-only source and V6 output; atomic new audit report",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "native_or_hdf5_read": "forbidden",
        },
        "qualification_stage": "stage2_f2_s1_v6_post_gencase_support_mass_audit_pending",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "initial XML/VTK support and mass audit only"},
    }
    write_new(REQUEST, request)
    report = {
        "schema": "ds02.stage2.f2-s1.source-centered-v6-support-audit-request.v1",
        "status": "PREPARED_PARENT_GUARDED_POST_GENCASE_AUDIT",
        "launch_commit": launch_commit,
        "request": record(REQUEST),
        "v6_gencase_request": record(V6_REQUEST),
        "generated_inputs_deferred": [str(generated_xml), str(fluid_vtk), str(receipt)],
        "static_input_count": len(records),
        "solver_started": False,
        "native_payload_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    write_new(REPORT, report)
    return report


def self_test() -> dict[str, Any]:
    assert V6_REQUEST.is_file() and V6_MANIFEST.is_file() and V6_WORKER.is_file()
    assert "generated.xml" in str(Path("/tmp") / "generated.xml")
    return {"status": "PASS", "gencase_started": False, "native_payload_read": False, "deferred_count": 3}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if sum((args.self_test, args.build_request)) != 1:
        parser.error("choose exactly one mode")
    if args.self_test:
        value = self_test()
    else:
        if not args.launch_commit:
            parser.error("--build-request requires --launch-commit")
        value = build(args.launch_commit)
    print(json.dumps(value if args.self_test else {"status": value["status"], "request": str(REQUEST)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

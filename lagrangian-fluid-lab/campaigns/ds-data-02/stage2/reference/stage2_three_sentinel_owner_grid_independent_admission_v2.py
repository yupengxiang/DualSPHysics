#!/usr/bin/env python3
"""Add route-level context closure for the independent owner-grid admission.

This is an additive wrapper around the frozen V1 route.  ROOT313, ROOT316,
and ROOT370 are current, small verification records that may be useful to the
parent scheduler as operational context.  They are deliberately recorded as
route inputs, never as inputs of the nine GenCase producers.  Their referenced
reports remain deferred: this builder only stats those paths and carries the
proof-declared SHA for a parent-after-reservation recheck.

The old ROOT321/ROOT326/native/mass waiter is not synthesized or consumed.  No
generated XML/VTK/BI4/native product is opened and this request remains
launch-disabled with zero scientific credit.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve()
V1_PATH = HERE.with_name("stage2_three_sentinel_owner_grid_independent_admission_v1.py")
PRIMARY_STAGE2 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
)
PRIMARY_REF = PRIMARY_STAGE2 / "reference"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
MAX_METADATA_BYTES = 10 * 1024 * 1024
SCHEMA = "ds02.stage2.three-sentinel.owner-grid-independent-admission.v2"
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.three-sentinel.owner-grid-independent-admission-context-request.v2"

CONTEXT_PATHS = {
    "ROOT313": PRIMARY_STAGE2 / "checkpoints/NATIVE_TYPED_MASS_IMPACT_ACTUAL_ROOT_VERIFICATION_313.json",
    "ROOT316": PRIMARY_STAGE2 / "checkpoints/GEOMETRY_SUPPORT_ACTUAL_ROOT_VERIFICATION_316.json",
    "ROOT370": PRIMARY_STAGE2 / "checkpoints/ROOT370_SCIENTIFIC_FIELD_H5_INDEPENDENT_V5.json",
}
CONTEXT_EXPECTED = {
    "ROOT313": {
        "status_prefix": "VERIFIED_ACTUAL_ROOT313_NATIVE_TYPED_MASS_IMPACT_",
        "role": "typed_mass_support_context_only",
    },
    "ROOT316": {
        "status_prefix": "VERIFIED_ACTUAL_ROOT316_FOUR_SENTINEL_VTK_GEOMETRY_SUPPORT_",
        "role": "geometry_support_context_only",
    },
    "ROOT370": {
        "status": "VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT",
        "role": "field_resource_context_only",
    },
}
STALE_BARRIERS = (
    "ROOT242",
    "ROOT276",
    "ROOT314",
    "ROOT_MASS30",
    "ROOT321",
    "ROOT326",
    "native321",
    "mass30",
)


class AdmissionFailure(RuntimeError):
    pass


def _load_v1() -> Any:
    if V1_PATH.is_symlink() or not V1_PATH.is_file():
        raise AdmissionFailure(f"frozen V1 route is missing: {V1_PATH}")
    spec = importlib.util.spec_from_file_location("stage2_owner_grid_route_v1", V1_PATH)
    if spec is None or spec.loader is None:
        raise AdmissionFailure("cannot load frozen V1 route")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path, label: str) -> tuple[Any, dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise AdmissionFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_METADATA_BYTES:
        raise AdmissionFailure(f"{label} exceeds the metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise AdmissionFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdmissionFailure(f"{label} is not JSON metadata: {exc}") from exc
    return value, {
        "path": str(path),
        "bytes": len(raw),
        "sha256": _sha(raw),
        "stat": after,
        "scope": "bounded_json_metadata",
        "payload_read_by_builder": True,
    }


def _stat_only_report(path: Path, label: str, expected_sha: str) -> dict[str, Any]:
    """Bind a proof-declared report without opening its content."""
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise AdmissionFailure(f"{label} report is not a regular file: {path}")
    value = _stat(path)
    return {
        "path": str(path),
        "stat": value,
        "expected_sha256_from_proof": expected_sha,
        "content_sha256_basis": "PROOF_DECLARED_SHA_RECHECKED_BY_PARENT_AFTER_RESERVATION",
        "content_read_by_builder": False,
        "parent_after_reservation_recheck_required": True,
    }


def _context(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    value, record = _read_json(path, f"{label} context proof")
    if not isinstance(value, dict):
        raise AdmissionFailure(f"{label} context proof is not an object")
    expected = CONTEXT_EXPECTED[label]
    status = value.get("status")
    if expected.get("status") is not None:
        if status != expected["status"]:
            raise AdmissionFailure(f"{label} has unexpected status: {status!r}")
    elif not isinstance(status, str) or not status.startswith(expected["status_prefix"]):
        raise AdmissionFailure(f"{label} has unexpected status: {status!r}")
    report_path = value.get("report")
    report_sha = value.get("report_sha256")
    # ROOT313/316 verification records use top-level report/report_sha256;
    # ROOT370's metadata verifier nests the same binding under report.
    if isinstance(report_path, dict):
        report_sha = report_path.get("sha256")
        report_path = report_path.get("path")
    if not isinstance(report_path, str) or not isinstance(report_sha, str) or len(report_sha) != 64:
        raise AdmissionFailure(f"{label} lacks a proof-declared report path/SHA")
    int(report_sha, 16)
    report_ref = _stat_only_report(Path(report_path), f"{label}", report_sha)
    q = value.get("scientific_qualification")
    if isinstance(q, dict) and any(q.get(k) not in (None, "UNKNOWN") for k in ("QI", "QN", "QE")):
        raise AdmissionFailure(f"{label} unexpectedly carries a scientific qualification")
    if value.get("scientific_credit", 0) not in (None, 0):
        raise AdmissionFailure(f"{label} carries nonzero scientific credit")
    context = {
        "label": label,
        "role": expected["role"],
        "proof": record,
        "status": status,
        "report": report_ref,
        "operational_context_only": True,
        "producer_input": False,
        "scientific_credit": 0,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    return context, record


def build_context_route(source_manifest: Path, case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    v1 = _load_v1()
    route = v1.inspect_source(source_manifest)
    contexts: dict[str, dict[str, Any]] = {}
    context_records: dict[str, dict[str, Any]] = {}
    for label, path in CONTEXT_PATHS.items():
        item, record = _context(path, label)
        contexts[label] = item
        context_records[record["path"]] = record

    records: dict[str, dict[str, Any]] = {}
    for item in [route["source_manifest"], *route["producer_source_manifests"], route["owner_report"]]:
        records[item["path"]] = item
    for item in route["producer_requests"]:
        records[item["request"]["path"]] = item["request"]
    records.update(context_records)
    code_records: dict[str, dict[str, Any]] = {}
    for path in (V1_PATH, HERE):
        if path.is_file() and not path.is_symlink():
            stat = _stat(path)
            code_records[str(path)] = {
                "path": str(path),
                "bytes": stat["bytes"],
                "sha256": _sha(path.read_bytes()),
                "stat": stat,
                "scope": "bounded_worker_source",
                "payload_read_by_builder": False,
            }
    records.update(code_records)

    route["schema"] = SCHEMA
    route["status"] = "SOURCE_ROUTE_READY_FOR_PARENT_AFTER_FIELDCASE_RESOURCE_RELEASE"
    route["operational_context"] = contexts
    route["dependency_audit"].update({
        "ROOT326": "NOT_A_PRODUCER_INPUT; mass/readiness continuation only",
        "ROOT313": "ROUTE_CONTEXT_ONLY; typed-mass report is downstream and carries no Q",
        "ROOT316": "ROUTE_CONTEXT_ONLY; geometry-support report is downstream and carries no owner Q",
        "ROOT370": "ROUTE_CONTEXT_ONLY; field resource/scientific metadata has zero Q",
        "current_context_files_are_producer_inputs": False,
        "old_waiter_is_serial_scheduling_only": True,
    })

    route_path = str(Path("{attempt_root}") / "route" / "owner_grid_independent_admission_v2.json")
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V10_OWNER_GRID_GENCASE_INDEPENDENT_CONTEXT_ROUTE",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "request_id": "three-sentinel-owner-grid-independent-context-v2-root372",
        "family_id": "infra",
        "sentinel_id": "F2-S2,F3-S1,F5-S1",
        "physical_case_id": "THREE_SENTINEL_OWNER_GRID_GENCASE_CONTEXT_ROUTE",
        "case_id": case_id,
        "attempt_id": "PARENT_ASSIGNED_AFTER_FIELDCASE_RELEASE",
        "cwd": str(PRIMARY_STAGE2.parents[2]),
        "worktree_root": str(PRIMARY_STAGE2.parents[2]),
        "command": [str(PYTHON), str(PRIMARY_REF / HERE.name), "--run", "--manifest", "{attempt_root}/manifest.json", "--output", route_path],
        "input_files": sorted(records),
        "input_records": records,
        "input_sha256": {path: item["sha256"] for path, item in records.items()},
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 300,
        "max_memory_bytes": 1024 * 1024**2,
        "estimated_storage_bytes": 2 * 1024**2,
        "estimated_peak_memory_bytes": 256 * 1024**2,
        "estimated_input_read_bytes": sum(int(item.get("bytes", 0)) for item in records.values()),
        "estimated_native_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": False,
        "launch_disabled": True,
        "parent_admission_required": True,
        "gencase_launch": False,
        "solver_launch": False,
        "native_payload_read": False,
        "output_root": "{attempt_root}",
        "output": {"atomic": True, "refuse_overwrite": True, "path": route_path},
        "source_binding": {
            "route_manifest": route,
            "operational_context": contexts,
            "current_context_is_not_producer_input": True,
            "old_native_mass_waiter_bypassed_as_non_input": True,
            "fieldcase_terminal_and_fee_release_still_required": True,
            "products_are_not_present_until_parent_gen_case": True,
            "scientific_credit": 0,
        },
        "deferred_context_reports": [contexts[label]["report"] for label in sorted(contexts)],
        "resource_guard": {
            "runner": "parent-v10-after-reservation",
            "cpu_task": "metadata-audit-only",
            "fieldcase_exclusion": True,
            "payload_read": "bounded JSON proof metadata only; context reports stat-only until parent",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0},
    }
    request["sha256"] = _sha(json.dumps({k: v for k, v in request.items() if k != "sha256"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())
    return route, request


def self_test() -> dict[str, Any]:
    if not str(PYTHON).endswith("/.venv/bin/python"):
        raise AssertionError("literal venv binding changed")
    if set(CONTEXT_PATHS) != {"ROOT313", "ROOT316", "ROOT370"}:
        raise AssertionError("context closure changed")
    return {
        "status": "PASS_OWNER_GRID_INDEPENDENT_CONTEXT_ROUTE_SOURCE_ONLY",
        "old_native321_and_mass326_are_not_producer_inputs": True,
        "context_labels": sorted(CONTEXT_PATHS),
        "scientific_credit": 0,
        "native_payload_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--inspect", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--source-manifest", type=Path, default=PRIMARY_STAGE2 / "requests/three-sentinel-owner-grid-gencase-v3-primary-admission-source-001/owner-grid-gencase-root-admission-manifest-v3.json")
    parser.add_argument("--output", type=Path, default=Path("/tmp/owner-grid-independent-context-route-v2.json"))
    parser.add_argument("--request-output", type=Path, default=Path("/tmp/owner-grid-independent-context-request-v2.json"))
    parser.add_argument("--case-id", default="THREE_SENTINEL_OWNER_GRID_INDEPENDENT_CONTEXT_ROUTE_ROOT372_V2")
    args = parser.parse_args()
    try:
        if args.self_test:
            print(json.dumps(self_test(), sort_keys=True))
            return 0
        route, request = build_context_route(args.source_manifest, args.case_id)
        if args.inspect:
            args.output.write_text(json.dumps(route, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps({"status": route["status"], "output": str(args.output.absolute()), "scientific_credit": 0}, sort_keys=True))
            return 0
        args.output.write_text(json.dumps(route, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.request_output.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": request["status"], "route": str(args.output.absolute()), "request": str(args.request_output.absolute()), "scientific_credit": 0}, sort_keys=True))
        return 0
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_OWNER_GRID_INDEPENDENT_CONTEXT_ROUTE", "error": {"type": type(exc).__name__, "message": str(exc)}}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

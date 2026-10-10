#!/usr/bin/env python3
"""Build a source-only GenCase admission route without the stale native321 barrier.

The nine owner-grid requests are GenCase producers.  Their source closure is
the owner audit, the nine producer request files, the candidate Def/auxiliary
records, the official GenCase record, and the shared runtime/code records.
The old ROOT242/276/314/mass30/native321 chain is a scheduler lineage for
later native/support work; it is not an input to any of those producer
requests.  This module proves that distinction from the frozen JSON records
and emits a *launch-disabled* route for the parent to rebind after the
current heavy field case has released its resources.

No generated XML/VTK/BI4/native product is opened here.  The parent must still
run each request through the real runtime and then perform the independent
initial-support/header audit.  This route carries no scientific credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve()
PRIMARY_STAGE2 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
)
PRIMARY_REF = PRIMARY_STAGE2 / "reference"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
MAX_METADATA_BYTES = 10 * 1024 * 1024
SCHEMA = "ds02.stage2.three-sentinel.owner-grid-independent-admission.v1"
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.three-sentinel.owner-grid-independent-admission-request.v1"
EXPECTED_KEYS = [
    f"{sentinel}:{grid}"
    for sentinel in ("F2-S2", "F3-S1", "F5-S1")
    for grid in ("original", "coarse", "fine")
]
STALE_BARRIERS = ("ROOT242", "ROOT276", "ROOT314", "ROOT_MASS30", "ROOT321", "native321", "mass30")


class AdmissionFailure(RuntimeError):
    pass


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
        raise AdmissionFailure(f"{label} changed during the bounded read: {path}")
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


def _record_path(path: Path, label: str) -> dict[str, Any]:
    """Record a source JSON file; never open a declared payload input."""
    value, record = _read_json(path, label)
    if not isinstance(value, dict):
        raise AdmissionFailure(f"{label} must be a JSON object")
    return record


def _strings(value: Any, output: list[str]) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _strings(item, output)
    elif isinstance(value, list):
        for item in value:
            _strings(item, output)
    elif isinstance(value, str):
        output.append(value)


def _source_declared_record(request: dict[str, Any], path: str) -> dict[str, Any] | None:
    records = request.get("input_records")
    if not isinstance(records, dict):
        return None
    item = records.get(path)
    return item if isinstance(item, dict) else None


def _validate_request(
    request_path: Path,
    expected_key: str,
    expected_sha: str,
    source_manifest_path: Path,
) -> dict[str, Any]:
    request, request_record = _read_json(request_path, f"producer request {expected_key}")
    if not isinstance(request, dict):
        raise AdmissionFailure(f"producer request {expected_key} is not an object")
    if request_record["sha256"] != expected_sha:
        raise AdmissionFailure(f"producer request {expected_key} SHA differs from source manifest")
    identity = request.get("row_key")
    if identity is None and request.get("sentinel_id") and request.get("grid_label"):
        identity = f"{request['sentinel_id']}:{request['grid_label']}"
    if request.get("schema") != REQUEST_SCHEMA or identity != expected_key:
        raise AdmissionFailure(f"producer request {expected_key} schema/row identity mismatch")
    staged_worker = isinstance(request.get("staged_gencase_worker"), dict)
    if request.get("cpu_task_kind") != "gencase" or (request.get("gencase_only") is not True and not staged_worker):
        raise AdmissionFailure(f"producer request {expected_key} is not a GenCase-only request")
    if request.get("execution_allowed") is not False or request.get("launch_disabled") is not True:
        raise AdmissionFailure(f"producer request {expected_key} is already execution-enabled")
    if request.get("solver_launch") is not False or request.get("solver_started") is not False:
        raise AdmissionFailure(f"producer request {expected_key} has solver scope")
    if request.get("source_only") is not True:
        raise AdmissionFailure(f"producer request {expected_key} is not source-only")
    command = request.get("command")
    if not isinstance(command, list) or len(command) < 3:
        raise AdmissionFailure(f"producer request {expected_key} has no executable GenCase command")
    official_path = command[0] if isinstance(command[0], str) and command[0].endswith("/GenCase_linux64") else None
    if official_path is None and staged_worker:
        for path, item in request.get("input_records", {}).items():
            if isinstance(item, dict) and isinstance(path, str) and path.endswith("/GenCase_linux64"):
                official_path = path
                break
    if official_path is None:
        raise AdmissionFailure(f"producer request {expected_key} does not bind official GenCase")
    if not isinstance(request.get("input_files"), list) or not isinstance(request.get("input_records"), dict):
        raise AdmissionFailure(f"producer request {expected_key} lacks input records")
    if set(request["input_files"]) - set(request["input_records"]):
        raise AdmissionFailure(f"producer request {expected_key} input_files are not recorded")
    official = _source_declared_record(request, official_path)
    if not isinstance(official, dict) or official.get("sha256") != "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226":
        raise AdmissionFailure(f"producer request {expected_key} lacks the frozen official GenCase SHA")
    # The old queue may carry a deferred control input.  Its content is not
    # opened here; only the request's declared source record is carried to the
    # parent, which must hash it after reservation in the actual attempt.
    deferred = request.get("deferred_input_records", [])
    if not isinstance(deferred, list):
        raise AdmissionFailure(f"producer request {expected_key} has malformed deferred inputs")
    declared_strings: list[str] = []
    _strings(request, declared_strings)
    stale_mentions = sorted({marker for marker in STALE_BARRIERS if any(marker in item for item in declared_strings)})
    if stale_mentions:
        raise AdmissionFailure(f"producer request {expected_key} directly declares stale barrier(s): {stale_mentions}")
    return {
        "row_key": expected_key,
        "request": request_record,
        "source_manifest": str(source_manifest_path),
        "family_id": request.get("family_id"),
        "sentinel_id": request.get("sentinel_id"),
        "grid_label": request.get("grid_label"),
        "case_id": request.get("case_id"),
        "physical_case_id": request.get("physical_case_id"),
        "producer_status": request.get("status"),
        "execution_allowed": False,
        "launch_disabled": True,
        "deferred_input_count": len(deferred),
        "declared_input_count": len(request["input_files"]),
        "official_gencase": {"path": official_path, "sha256": official["sha256"], "bytes": official.get("bytes")},
        "staged_worker": staged_worker,
    }


def _load_source_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, record = _read_json(path, "owner-grid admission source manifest")
    if not isinstance(manifest, dict) or manifest.get("schema") != "ds02.stage2.root-nine-gencase-admission-source.v3":
        raise AdmissionFailure("unexpected owner-grid admission source manifest schema")
    if manifest.get("status") != "SOURCE_METADATA_PREFLIGHTED_PENDING_ACTUAL_NATIVE321":
        raise AdmissionFailure("source manifest status changed; refuse to infer a new admission")
    rows = manifest.get("producer_requests")
    if not isinstance(rows, list) or len(rows) != 9:
        raise AdmissionFailure("source manifest does not contain exactly nine producer requests")
    return manifest, record


def inspect_source(source_manifest_path: Path) -> dict[str, Any]:
    manifest, manifest_record = _load_source_manifest(source_manifest_path)
    rows = manifest["producer_requests"]
    by_key = {row.get("row_key"): row for row in rows if isinstance(row, dict)}
    if set(by_key) != set(EXPECTED_KEYS):
        raise AdmissionFailure(f"source manifest row set differs: {sorted(by_key)}")
    source_records = manifest.get("source_manifests")
    if not isinstance(source_records, list) or not source_records:
        raise AdmissionFailure("source manifest lacks producer source-manifest records")
    source_manifest_edges = []
    all_strings: list[str] = []
    _strings(manifest, all_strings)
    stale_manifest_mentions = sorted({marker for marker in STALE_BARRIERS if any(marker in item for item in all_strings)})
    for index, edge in enumerate(source_records):
        if not isinstance(edge, dict) or not isinstance(edge.get("path"), str) or not isinstance(edge.get("sha256"), str):
            raise AdmissionFailure(f"source manifest edge {index} is malformed")
        edge_path = Path(edge["path"])
        _, edge_record = _read_json(edge_path, f"producer source manifest {index}")
        if edge_record["sha256"] != edge["sha256"]:
            raise AdmissionFailure(f"producer source manifest {index} SHA changed")
        source_manifest_edges.append(edge_record)
    producer_details = []
    for key in EXPECTED_KEYS:
        row = by_key[key]
        producer_path = Path(str(row.get("path", "")))
        if row.get("row_key") != key or not isinstance(row.get("sha256"), str):
            raise AdmissionFailure(f"source row {key} is malformed")
        producer_details.append(_validate_request(producer_path, key, row["sha256"], source_manifest_path))
    owner_report = manifest.get("owner_report")
    if not isinstance(owner_report, dict) or not isinstance(owner_report.get("path"), str) or not isinstance(owner_report.get("sha256"), str):
        raise AdmissionFailure("owner report edge is missing")
    _, owner_record = _read_json(Path(owner_report["path"]), "owner source audit")
    if owner_record["sha256"] != owner_report["sha256"]:
        raise AdmissionFailure("owner source audit SHA changed")
    # The stale native barrier appears only in the old continuation checkpoint
    # and its waiter's code, not in producer request inputs.  Keep this finding
    # explicit so the parent cannot mistake this route for a native proof.
    return {
        "schema": SCHEMA,
        "status": "SOURCE_ROUTE_READY_FOR_PARENT_AFTER_FIELDCASE_RESOURCE_RELEASE",
        "source_manifest": manifest_record,
        "producer_source_manifests": source_manifest_edges,
        "owner_report": owner_record,
        "producer_requests": producer_details,
        "dependency_audit": {
            "producer_input_closure_contains_old_native_barriers": bool(stale_manifest_mentions),
            "producer_input_stale_barrier_markers": stale_manifest_mentions,
            "ROOT242": "NOT_A_PRODUCER_INPUT; no direct request/manifest edge",
            "ROOT276": "NOT_A_PRODUCER_INPUT; initial-support is downstream",
            "ROOT314": "NOT_A_PRODUCER_INPUT; frame0 geometry audit is downstream",
            "ROOT_MASS30": "NOT_A_PRODUCER_INPUT; native typed-mass audit is downstream",
            "ROOT321": "NOT_A_PRODUCER_INPUT; old continuation barrier only",
            "native321": "NOT_A_PRODUCER_INPUT; old continuation barrier only",
            "fieldcase": "ROOT_OPERATIONAL_GATE_ONLY; current heavy parent must be terminal and fees released",
        },
        "downstream_gates": [
            "parent runtime reservation and exact attempt identity",
            "official GenCase returncode and execution receipt",
            "generated XML/Fluid VTK/Bound VTK/BI4 product stat and post-reservation hashes",
            "native header/role/finite initial-support audit",
            "continuous-owner equivalence remains UNKNOWN unless independently proved",
        ],
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0},
        "execution": {"execution_allowed": False, "launch_disabled": True, "gencase_launch_by_builder": False, "native_payload_read": False, "solver_launch": False},
    }


def build_request(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    source_manifest_path = Path(args.source_manifest).expanduser().absolute()
    route = inspect_source(source_manifest_path)
    records: dict[str, dict[str, Any]] = {}
    for item in [route["source_manifest"], *route["producer_source_manifests"], route["owner_report"]]:
        records[item["path"]] = item
    for item in route["producer_requests"]:
        records[item["request"]["path"]] = item["request"]
    code_paths = [HERE, PRIMARY_REF / "stage2_three_sentinel_owner_grid_independent_admission_v1.py"]
    for path in code_paths:
        if path.is_file() and not path.is_symlink():
            _, record = _read_json(path, "route source") if path.suffix == ".json" else (None, {"path": str(path), "bytes": _stat(path)["bytes"], "sha256": _sha(path.read_bytes()), "stat": _stat(path), "scope": "bounded_worker_source", "payload_read_by_builder": False})
            records[str(path)] = record
    route_path = str(Path("{attempt_root}") / "route" / "owner_grid_independent_admission_v1.json")
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V10_OWNER_GRID_GENCASE_INDEPENDENT_ROUTE",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "request_id": "three-sentinel-owner-grid-independent-admission-v1-root371",
        "family_id": "infra",
        "sentinel_id": "F2-S2,F3-S1,F5-S1",
        "physical_case_id": "THREE_SENTINEL_OWNER_GRID_GENCASE_SOURCE_ROUTE",
        "case_id": args.case_id,
        "attempt_id": "PARENT_ASSIGNED_AFTER_RESERVATION",
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
            "old_native321_barrier_bypassed_as_non_input": True,
            "fieldcase_terminal_and_fee_release_still_required": True,
            "products_are_not_present_until_parent_gen_case": True,
            "scientific_credit": 0,
        },
        "resource_guard": {"runner": "parent-v10-after-reservation", "cpu_task": "metadata-audit-only", "fieldcase_exclusion": True, "payload_read": "bounded JSON metadata only"},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0},
    }
    request["sha256"] = _sha(json.dumps({k: v for k, v in request.items() if k != "sha256"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())
    return route, request


def self_test() -> dict[str, Any]:
    if not str(PYTHON).endswith("/.venv/bin/python"):
        raise AssertionError("literal venv binding changed")
    return {"status": "PASS_OWNER_GRID_INDEPENDENT_ROUTE_SOURCE_ONLY", "old_native_barrier_not_producer_input": True, "scientific_credit": 0, "native_payload_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--inspect", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--source-manifest", type=Path, default=PRIMARY_STAGE2 / "requests/three-sentinel-owner-grid-gencase-v3-primary-admission-source-001/owner-grid-gencase-root-admission-manifest-v3.json")
    parser.add_argument("--output", type=Path, default=Path("/tmp/owner-grid-independent-admission-v1.json"))
    parser.add_argument("--request-output", type=Path, default=Path("/tmp/owner-grid-independent-admission-request-v1.json"))
    parser.add_argument("--case-id", default="THREE_SENTINEL_OWNER_GRID_INDEPENDENT_ROUTE_ROOT371")
    args = parser.parse_args()
    try:
        if args.self_test:
            print(json.dumps(self_test(), sort_keys=True)); return 0
        if args.inspect:
            value = inspect_source(args.source_manifest)
            args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps({"status": value["status"], "output": str(args.output.absolute()), "scientific_credit": 0}, sort_keys=True)); return 0
        route, request = build_request(args)
        args.output.write_text(json.dumps(route, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.request_output.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": request["status"], "route": str(args.output.absolute()), "request": str(args.request_output.absolute()), "scientific_credit": 0}, sort_keys=True)); return 0
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_OWNER_GRID_INDEPENDENT_ROUTE", "error": {"type": type(exc).__name__, "message": str(exc)}}, sort_keys=True)); return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Prepare a strict, source-bound frame-zero audit for F2-S2/F4-S2/F5-S2/F7-S1.

This builder consumes the existing small quality manifest and terminal
receipts.  It hashes only small metadata and source XML/RunPARTs; the native
Part_0000 files are stat-only deferred inputs.  A parent must reserve the
request before the worker reads those files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
QUALITY = HERE / "stage2_reference_quality_cost_v2.json"
WORKER_REL = Path("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_four_sentinel_frame0_support_audit_v2.py")
CONTRACT_REL = Path("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_four_sentinel_frame0_support_audit_contract_v2.json")
OBSERVER_REL = Path("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_v2.py")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/native/bi4_dump.cpp")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SCHEMA = "ds02.stage2.four-sentinel-frame0-support-request.v2"
MANIFEST_SCHEMA = "ds02.stage2.four-sentinel-frame0-support-manifest.v2"
CASES = ("F2-S2", "F4-S2", "F5-S2", "F7-S1")
MAX_SMALL_BYTES = 16 * 1024 * 1024
SCRATCH_CAP_BYTES = 256 * 1024 * 1024


class BuildFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _record(path: Path, label: str, *, read_content: bool = True) -> dict[str, Any]:
    path = _regular(path, label); stat_before = _stat(path)
    # Deferred native frames (and stat-only executable bindings) may be large;
    # the builder must record their complete stat without opening the payload.
    # Keep the bounded-read policy only for files whose bytes are consumed here.
    if read_content and stat_before["bytes"] > MAX_SMALL_BYTES:
        raise BuildFailure(f"{label} exceeds bounded metadata input: {path}")
    digest = None
    if read_content:
        digest_obj = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest_obj.update(block)
        digest = digest_obj.hexdigest()
    stat_after = _stat(path)
    if stat_before != stat_after:
        raise BuildFailure(f"{label} changed while reading: {path}")
    return {"path": str(path), "sha256": digest, "hash_status": "BOUND" if digest else "STAT_ONLY_DEFERRED", "stat": stat_after, "payload_read_by_builder": bool(read_content)}


def _json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rec = _record(path, label, read_content=True)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} is not an object")
    return value, rec


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _source_case(row: dict[str, Any], quality_record: dict[str, Any], *, worker: Path,
                 contract: Path, observer: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    sid = row.get("sentinel_id")
    physical = row.get("physical_case_id")
    if sid not in CASES or not isinstance(physical, str):
        raise BuildFailure("quality row has invalid four-sentinel identity")
    source_xml = Path(row["source_xml"]["path"])
    xml, xml_record = _record(source_xml, f"{sid} source XML", read_content=True), None
    # _record above returns metadata; parse only the small XML is intentionally
    # left to the parent worker so this builder cannot turn XML parsing into a
    # payload-read claim.
    xml_record = xml
    binding = row.get("current_row_binding") or {}
    solver_rec = binding.get("solver_receipt") or {}
    if not isinstance(solver_rec.get("path"), str):
        raise BuildFailure(f"{sid} lacks current solver receipt")
    receipt_path = Path(solver_rec["path"])
    receipt, receipt_record = _json(receipt_path, f"{sid} solver receipt")
    if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise BuildFailure(f"{sid} solver receipt is not completed rc=0")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise BuildFailure(f"{sid} receipt lacks nested request")
    expected_identity = {
        "family_id": row.get("family_id"),
        "sentinel_id": sid,
        "physical_case_id": physical,
        "case_id": row.get("case_id"),
        "attempt_id": row.get("attempt_id"),
    }
    missing_identity: list[str] = []
    actual_identity: dict[str, Any] = {}
    for key, expected in expected_identity.items():
        actual = request.get(key)
        actual_identity[key] = actual
        if actual is None:
            # Historical receipts may omit sentinel_id or physical_case_id.
            # Preserve that fact as a partial identity result; never fill it
            # from a label or from the output directory name.
            missing_identity.append(key)
        elif expected is not None and actual != expected:
            raise BuildFailure(f"{sid} receipt request {key} mismatch")
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().absolute()
    frame0 = output_root / "solver_output" / "data" / "Part_0000.bi4"
    runparts = output_root / "solver_output" / "RunPARTs.csv"
    frame_record = _record(frame0, f"{sid} deferred frame-0", read_content=False)
    runparts_record = _record(runparts, f"{sid} RunPARTs", read_content=True)
    # The decoder is a small static executable dependency, so bind its actual
    # bytes in the parent input closure.  Only the native Part_0000 payloads
    # remain stat-only deferred inputs.
    decoder_record = _record(DECODER, "official BI4 decoder", read_content=True)
    decoder_source_record = _record(DECODER_SOURCE, "official BI4 decoder source", read_content=True)
    source_xml_path = source_xml.expanduser().absolute()
    case = {
        "sentinel_id": sid, "family_id": actual_identity.get("family_id") or row["family_id"],
        "physical_case_id": actual_identity.get("physical_case_id"),
        "source_row_physical_case_id": physical,
        "case_id": actual_identity.get("case_id"), "attempt_id": actual_identity.get("attempt_id"),
        "receipt_identity_expected": expected_identity,
        "receipt_identity_missing_fields": missing_identity,
        "source_xml": xml_record, "receipt": receipt_record, "receipt_sha256": receipt_record["sha256"],
        "terminal_output_root": str(output_root), "frame0": {**frame_record, "known_sha256": "PARENT_AFTER_RESERVATION_REQUIRED"},
        "runparts": runparts_record, "decoder": decoder_record, "decoder_source": decoder_source_record,
        "source_control": {"command": request.get("command"), "tmax_s": row.get("source_solver_controls", {}).get("tmax_s"), "tout_s": row.get("source_solver_controls", {}).get("tout_s"), "request_sha256": receipt.get("request_sha256")},
        "support_scope": {"fluid_vtk": "UNKNOWN_NOT_FOUND_IN_CURRENT_SOURCE_PRODUCT", "bound_vtk": "UNKNOWN_NOT_FOUND_IN_CURRENT_SOURCE_PRODUCT", "continuous_owner": "UNKNOWN", "mass_rescale": False},
        "prior_actual_evidence": {"quality_manifest_row": "SOURCE_METADATA_ONLY", "neighbor_grid_truth": False},
    }
    records = {quality_record["path"]: quality_record, str(source_xml_path): xml_record, receipt_record["path"]: receipt_record, runparts_record["path"]: runparts_record, decoder_record["path"]: decoder_record, decoder_source_record["path"]: decoder_source_record, str(worker.absolute()): _record(worker, "frame-0 worker", read_content=True), str(contract.absolute()): _record(contract, "frame-0 contract", read_content=True), str(observer.absolute()): _record(observer, "native observer dependency", read_content=True)}
    return case, records


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    source_root = args.source_root.expanduser().absolute()
    if not source_root.is_dir() or source_root.is_symlink():
        raise BuildFailure(f"source root is not a regular directory: {source_root}")
    worker = source_root / WORKER_REL
    contract = source_root / CONTRACT_REL
    observer = source_root / OBSERVER_REL
    for path, label in ((worker, "frame-0 worker"), (contract, "frame-0 contract"), (observer, "native observer dependency")):
        _regular(path, label)
    quality, quality_record = _json(args.quality, "quality manifest")
    rows = {str(row.get("sentinel_id")): row for row in quality.get("sources", []) if isinstance(row, dict)}
    if set(CASES) - set(rows):
        raise BuildFailure("quality manifest lacks one or more requested sentinels")
    cases: list[dict[str, Any]] = []; records: dict[str, dict[str, Any]] = {}
    for sid in CASES:
        case, case_records = _source_case(rows[sid], quality_record, worker=worker, contract=contract, observer=observer)
        cases.append(case); records.update(case_records)
    manifest = {"schema": MANIFEST_SCHEMA, "status": "PREPARED_PARENT_FRAME0_SUPPORT_GUARD_REQUIRED", "cases": cases, "source_quality_manifest": quality_record, "contract": _record(contract, "frame-0 contract", read_content=True), "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}, "read_scope": {"builder_hdf5_read": False, "builder_native_payload_read": False, "builder_vtk_payload_read": False, "solver_launch": False, "deferred_native_count": len(cases)}}
    manifest_path = args.manifest_output.expanduser().absolute(); _write_once(manifest_path, manifest); manifest_record = _record(manifest_path, "frame-0 manifest", read_content=True); records[manifest_record["path"]] = manifest_record
    input_files = sorted(records)
    request = {"schema": "ds02.request.v1", "variant_schema": SCHEMA, "status": "READY_FOR_PARENT_FRAME0_POSITION_SUPPORT_GUARD", "kind": "cpu", "cpu_task_kind": "audit", "request_id": "four-sentinel-frame0-position-support-audit-v2-001", "family_id": "DS02-MULTI", "sentinel_ids": list(CASES), "case_id": "FOUR_SENTINEL_FRAME0_POSITION_SUPPORT_AUDIT_V2", "attempt_id": "four-sentinel-frame0-position-support-audit-v2-001", "cwd": str(source_root), "worktree_root": str(source_root), "command": [str(PYTHON), str(worker), "--run", "--manifest", manifest_record["path"], "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/observer/four_sentinel_frame0_position_support_audit_v2.json"], "input_files": input_files, "input_sha256": {path: records[path]["sha256"] for path in input_files}, "input_records": records, "manifest": manifest_record, "deferred_input_files": [case["frame0"]["path"] for case in cases], "deferred_input_records": [{"sentinel_id": case["sentinel_id"], **case["frame0"], "parent_after_reservation_first_sha_stat": True, "post_decode_sha_stat": True} for case in cases], "deferred_input_policy": {"parent_v8_hashes_deferred": True, "worker_pre_post_sha_stat": True, "decoder_output_arrays_pre_post_stat_sha": True, "source_replace_or_touch": "FAIL", "full_native_tree_scan": False}, "resources": {"cpu_threads": 1, "max_wall_seconds": 1800, "memory_max_bytes": 2 * 1024**3, "scratch_max_bytes": SCRATCH_CAP_BYTES, "log_max_bytes": 1024 * 1024, "gpu": "none", "solver_launch": False}, "storage_scope": {"native_payload": "four Part_0000.bi4 only", "hdf5_read": False, "vtk_payload": False, "solver_launch": False}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}, "launch_disabled": False, "execution_allowed": True, "native_payload_read": False, "ledger_mutation": False, "source_binding": {"exact_current_rows": True, "receipt_request_identity": True, "role_overlap_from_xml": True, "position_only_accepted": True, "optional_velocity_density_mass_unknown_when_absent": True, "geometric_support": "UNKNOWN_NO_BOUND_FLUID_VTK", "continuous_owner": "UNKNOWN", "neighbor_grid_truth": False}}
    request_path = args.request_output.expanduser().absolute(); _write_once(request_path, request); return manifest, request


def self_test() -> None:
    with __import__("tempfile").TemporaryDirectory(prefix="four-sentinel-request-") as td:
        p = Path(td) / "small.json"; p.write_text("{}", encoding="utf-8")
        record = _record(p, "fixture", read_content=True)
        assert record["sha256"] and record["payload_read_by_builder"] is True
        payload = Path(td) / "Part_0000.bi4"; payload.write_bytes(b"payload")
        stat_record = _record(payload, "deferred", read_content=False)
        assert stat_record["sha256"] is None and stat_record["payload_read_by_builder"] is False
        # A stat-only native frame may exceed the builder's bounded byte-read
        # budget.  It must still be admitted as a deferred input without
        # opening or hashing its payload here.
        large = Path(td) / "large-deferred.bi4"
        with large.open("wb") as stream:
            stream.truncate(MAX_SMALL_BYTES + 1)
        large_record = _record(large, "large deferred", read_content=False)
        assert large_record["sha256"] is None
        assert large_record["stat"]["bytes"] == MAX_SMALL_BYTES + 1
    print("PASS_FOUR_SENTINEL_FRAME0_POSITION_SUPPORT_REQUEST_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--build", action="store_true")
    parser.add_argument("--quality", type=Path, default=PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_reference_quality_cost_v2.json"); parser.add_argument("--source-root", type=Path, default=PRIMARY); parser.add_argument("--manifest-output", type=Path); parser.add_argument("--request-output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test(); return 0
    if args.manifest_output is None or args.request_output is None:
        parser.error("--build requires --manifest-output and --request-output")
    try:
        manifest, request = build(args)
        print(json.dumps({"status": request["status"], "manifest": str(args.manifest_output.absolute()), "request": str(args.request_output.absolute()), "native_payload_read": False}, sort_keys=True)); return 0
    except Exception as exc:
        print(f"FOUR_SENTINEL_REQUEST_BUILD_FAILED: {exc}"); return 2


if __name__ == "__main__":
    raise SystemExit(main())

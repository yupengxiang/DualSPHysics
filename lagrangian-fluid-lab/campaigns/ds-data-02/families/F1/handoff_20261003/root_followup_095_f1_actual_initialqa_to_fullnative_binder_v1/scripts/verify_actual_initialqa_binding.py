#!/usr/bin/env python3
"""Verify fresh095 actual-initial-QA bindings without reading scientific payloads."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

PAYLOAD_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".npy", ".npz", ".vtk", ".dat"}

def load(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value

def digest(path: Path) -> str:
    if path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise RuntimeError(f"scientific payload read/hash forbidden: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def require(value, message):
    if not value:
        raise RuntimeError(message)

def verify_input_closure(request: dict, path: Path):
    files = set(request.get("input_files", []))
    hashes = request.get("input_sha256", {})
    require(files == set(hashes), f"{path}: input_files/input_sha256 set mismatch")
    for raw in sorted(files):
        item = Path(raw)
        require(item.is_file(), f"{path}: missing static input {item}")
        if item.suffix.lower() in PAYLOAD_SUFFIXES:
            require(isinstance(hashes[raw], str) and len(hashes[raw]) == 64, f"{path}: producer digest missing for payload {item}")
            continue
        require(digest(item) == hashes[raw], f"{path}: stale static input {item}")
    require(request.get("future_input_sha256") is None, f"{path}: future input digest must remain null")
    require(request.get("disabled") is True and request.get("execution_allowed") is False and request.get("launch_allowed") is False and request.get("launch") is False, f"{path}: request is enabled")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, required=True)
    args = ap.parse_args()
    package = args.package.resolve()
    requests = sorted((package / "full-native-requests").glob("*.json"))
    frame0 = sorted((package / "native-frame0-requests").glob("*.json"))
    require(len(requests) == 24 and len(frame0) == 24, f"expected 24 full-native and 24 frame0 requests, got {len(requests)} and {len(frame0)}")
    rows = []
    for path in requests:
        request = load(path)
        case = request.get("case_id")
        require(request.get("fresh_id") == "fresh095", f"{case}: fresh id mismatch")
        require(request.get("initial_qa_gate", {}).get("status") == "actual_root473_initial_qa_completed_zero", f"{case}: actual QA gate not bound")
        receipt_path = Path(request["initial_qa_receipt"])
        report_path = Path(request["initial_qa_report"])
        qa_request_path = Path(request["initial_qa_request"])
        for metadata_path in (receipt_path, report_path, qa_request_path):
            require(metadata_path.suffix.lower() == ".json" and metadata_path.is_file(), f"{case}: missing actual QA metadata {metadata_path}")
        receipt = load(receipt_path)
        report = load(report_path)
        qa_request = load(qa_request_path)
        require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, f"{case}: actual QA receipt is not completed/0")
        report_case = next((item for item in report.get("cases", []) if item.get("case_id") == case), None)
        require(report_case is not None and report_case.get("passed") is True and report_case.get("actual_3d") is True, f"{case}: actual QA report failed or is not 3D")
        expected = request["actual_particle_counts"]
        require(report_case.get("native_particles") == request["actual_total_particles"], f"{case}: report total mismatch")
        require(report_case.get("native_fluid") == expected["fluid"], f"{case}: report fluid mismatch")
        require(report_case.get("native_nonfluid") == request["actual_total_particles"] - expected["fluid"], f"{case}: report non-fluid mismatch")
        require(qa_request.get("case_id") == case and qa_request.get("fresh_id") == "fresh094", f"{case}: Root473 request identity mismatch")
        require(request["initial_qa_receipt_sha256"] == digest(receipt_path), f"{case}: receipt digest mismatch")
        require(request["initial_qa_report_sha256"] == digest(report_path), f"{case}: report digest mismatch")
        require(request["initial_qa_request_sha256"] == digest(qa_request_path), f"{case}: request digest mismatch")
        require(request.get("future_outputs", {}).get("sha256") is None, f"{case}: native future hash is populated")
        require(request.get("native_frame0_gate", {}).get("receipt") is None and request.get("native_frame0_gate", {}).get("report") is None, f"{case}: frame0 gate was falsely completed")
        verify_input_closure(request, path)
        rows.append({"case_id": case, "receipt_sha256": request["initial_qa_receipt_sha256"], "report_sha256": request["initial_qa_report_sha256"], "passed": True})
    for path in frame0:
        request = load(path)
        require(request.get("fresh_id") == "fresh095", f"{path}: fresh id mismatch")
        require(request.get("disabled") is True and request.get("execution_allowed") is False and request.get("launch_allowed") is False and request.get("launch") is False, f"{path}: frame0 request enabled")
        require(request.get("future_input_sha256") is None and request.get("future_outputs", {}).get("sha256") is None, f"{path}: frame0 future digest populated")
        verify_input_closure(request, path)
    print(json.dumps({"schema": "ds02.f1.fresh095.actual-initialqa-verification.v1", "passed": True, "full_native_cases": len(rows), "frame0_cases": len(frame0), "scientific_payloads_read": False, "future_native_outputs": "null"}, sort_keys=True))

if __name__ == "__main__":
    main()

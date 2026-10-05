#!/usr/bin/env python3
"""Stage full-native requests after Root supplies actual initial-QA receipts.

This adapter reads only JSON metadata and writes a new staging directory. It
never opens BI4/CSV/H5/DAT/VTK payloads, never resolves a GPU, and never enables
a request. The committed requests remain disabled and their future hashes stay
null until Root gives an explicit per-case manifest.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

ARRAY_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".npy", ".npz", ".vtk", ".dat"}

def load(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise RuntimeError(f"expected JSON object: {path}")
    return value

def sha(path):
    if Path(path).suffix.lower() in ARRAY_SUFFIXES:
        raise RuntimeError(f"payload hashing is forbidden: {path}")
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()

def require(value, msg):
    if not value: raise RuntimeError(msg)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--actual-qa-manifest", type=Path)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    package = args.package
    requests = sorted((package / "full-native-requests").glob("*.json"))
    require(len(requests) == 24, f"expected 24 full-native requests, got {len(requests)}")
    supplied = load(args.actual_qa_manifest) if args.actual_qa_manifest else {}
    require(isinstance(supplied, dict), "actual QA manifest must be an object")
    results = []
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for request_path in requests:
        request = load(request_path)
        case_id = request["case_id"]
        item = supplied.get(case_id)
        if item is None:
            results.append({"case_id": case_id, "status": "pending_actual_root_initial_qa"})
            continue
        receipt_path = Path(item["receipt"])
        report_path = Path(item["report"])
        require(receipt_path.suffix.lower() == ".json" and report_path.suffix.lower() == ".json", f"{case_id}: QA metadata must be JSON")
        receipt = load(receipt_path); report = load(report_path)
        require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, f"{case_id}: QA receipt is not completed/0")
        require(item.get("receipt_sha256") in (None, sha(receipt_path)), f"{case_id}: QA receipt SHA mismatch")
        require(item.get("report_sha256") in (None, sha(report_path)), f"{case_id}: QA report SHA mismatch")
        staged = dict(request)
        staged["initial_qa_receipt"] = str(receipt_path)
        staged["initial_qa_receipt_sha256"] = sha(receipt_path)
        staged["initial_qa_report"] = str(report_path)
        staged["initial_qa_report_sha256"] = sha(report_path)
        staged["initial_qa_gate"] = {"required": True, "status": "actual_root_initial_qa_completed_zero", "receipt": str(receipt_path), "report": str(report_path)}
        staged["status"] = "disabled_ready_actual_initial_qa_completed_zero"
        staged["execution_allowed"] = False
        staged["launch_allowed"] = False
        staged["disabled"] = True
        staged["launch"] = False
        target = args.output_dir / request_path.name
        target.write_text(json.dumps(staged, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        results.append({"case_id": case_id, "status": "staged_disabled", "request": str(target), "receipt_sha256": staged["initial_qa_receipt_sha256"], "report_sha256": staged["initial_qa_report_sha256"]})
    (args.output_dir / "materialization-report.json").write_text(json.dumps({"schema": "ds02.f1.fresh092.initial-qa-materialization.v1", "source_only": True, "execution_allowed": False, "launch_allowed": False, "scientific_payloads_read": False, "cases": results}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

if __name__ == "__main__": main()

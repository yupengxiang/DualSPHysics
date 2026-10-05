#!/usr/bin/env python3
"""Static verifier for F1 fresh096 actual Root480 -> frame-0 VX gates.

This verifier reads JSON/XML/source metadata only.  It checks the Root480
completed/0 receipts, request/receipt/controller identity, exact static input
closures, and the disabled PartVTK worker contracts.  It never opens or hashes
BI4, H5, CSV, DAT, VTK, or other scientific payloads, and never launches a
solver or PartVTK.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

PAYLOAD_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".npy", ".npz", ".vtk", ".dat", ".raw"}

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

def require(condition, message):
    if not condition:
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
        else:
            require(digest(item) == hashes[raw], f"{path}: stale static input {item}")
    require(request.get("future_input_sha256") is None, f"{path}: future input digest must remain null")
    require(request.get("disabled") is True and request.get("execution_allowed") is False and request.get("launch_allowed") is False and request.get("launch") is False, f"{path}: request is enabled")
    require(request.get("future_outputs", {}).get("sha256") is None, f"{path}: future frame0 output hash is populated")
    require(request.get("native_solver_receipt_sha256"), f"{path}: actual native receipt SHA missing")
    require(request.get("native_run_out_sha256") is None, f"{path}: Run.out was hashed by source package")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, required=True)
    args = ap.parse_args()
    package = args.package.resolve()
    requests = sorted((package / "requests").glob("*.json"))
    bindings = sorted((package / "bindings").glob("*.json"))
    require(len(requests) == 24 and len(bindings) == 24, f"expected 24 requests and bindings, got {len(requests)} and {len(bindings)}")
    controller_path = Path(load(package / "metadata/actual-root480-native-frame0-source-summary.json")["actual_controller_result"])
    controller = load(controller_path)
    require(controller.get("requested") == 24 and controller.get("finished") == 24 and controller.get("completed0") == 24 and controller.get("pending_held") == 0, "Root480 controller is not 24 completed/0")
    controller_rows = {row["case_id"]: row for row in controller["results"]}
    require(len(controller_rows) == 24, "Root480 controller case map is not 24")
    bind_by_case = {load(p)["case_id"]: p for p in bindings}
    require(len(bind_by_case) == 24, "binding case IDs are not unique")
    out = []
    for path in requests:
        req = load(path)
        case = req.get("case_id")
        require(req.get("fresh_id") == "fresh096", f"{case}: fresh id mismatch")
        require(case in bind_by_case and case in controller_rows, f"{case}: missing binding/controller row")
        bind_path = bind_by_case[case]
        bind = load(bind_path)
        require(bind.get("source_only") is True and bind.get("execution_allowed") is False and bind.get("launch_allowed") is False, f"{case}: binding is enabled")
        require(len(bind.get("cases", [])) == 1 and bind["cases"][0].get("case_id") == case, f"{case}: worker binding case shape mismatch")
        receipt_path = Path(req["native_solver_receipt"])
        receipt = load(receipt_path)
        require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, f"{case}: actual native receipt is not completed/0")
        require(req["native_solver_receipt_sha256"] == digest(receipt_path), f"{case}: actual receipt digest mismatch")
        full_req_path = Path(req["depends_on"]["fullnative_request"])
        full_req = load(full_req_path)
        require(req["depends_on"]["fullnative_request_sha256"] == digest(full_req_path), f"{case}: Root480 request digest mismatch")
        require(full_req.get("attempt_id") == req.get("native_solver_attempt_id"), f"{case}: Root480 attempt identity mismatch")
        require(receipt.get("request_sha256") == req["depends_on"]["fullnative_request_sha256"], f"{case}: receipt/request SHA mismatch")
        output_root = Path(receipt["output_root"])
        run_out = Path(req["native_run_out"])
        require(output_root.is_dir() and Path(req["native_data_dir"]).is_dir() and run_out.is_file(), f"{case}: actual native output metadata paths missing")
        require(req["native_run_out_sha256"] is None, f"{case}: Run.out digest populated")
        require(bind["actual_native_completion"]["receipt_sha256"] == req["native_solver_receipt_sha256"], f"{case}: binding/request receipt SHA mismatch")
        require(bind["native_frame0_gate"]["frame0_velocity_proved"] is False, f"{case}: frame0 gate falsely passed")
        verify_input_closure(req, path)
        out.append({"case_id": case, "receipt_sha256": req["native_solver_receipt_sha256"], "fullnative_request_sha256": req["depends_on"]["fullnative_request_sha256"], "passed": True})
    print(json.dumps({"schema": "ds02.f1.fresh096.actual-native480-frame0-verification.v1", "passed": True, "cases": len(out), "actual_native_completed0": 24, "frame0_velocity_proved": 0, "scientific_payloads_read": False, "future_frame0_hashes": "null"}, sort_keys=True))

if __name__ == "__main__":
    main()

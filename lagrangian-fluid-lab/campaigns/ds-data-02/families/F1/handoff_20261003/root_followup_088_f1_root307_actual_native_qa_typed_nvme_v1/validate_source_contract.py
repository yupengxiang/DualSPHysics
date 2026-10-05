#!/usr/bin/env python3
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
CASES = [
    "F1_STAGE1_DUAL_H240_DP020", "F1_STAGE1_DUAL_H240_DP020_VX010", "F1_STAGE1_DUAL_H280_DP020", "F1_STAGE1_DUAL_H320_DP020",
    "F1_STAGE1_ECC_H120_DP010", "F1_STAGE1_ECC_H140_DP010", "F1_STAGE1_ECC_H160_DP010", "F1_STAGE1_ECC_H180_DP010",
]
SCIENCE = {".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".npy", ".npz"}

def sha(path):
    d = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            d.update(b)
    return d.hexdigest()

def ensure(c, m):
    if not c: raise AssertionError(m)

def load(p):
    return json.loads(Path(p).read_text())

def main():
    manifest = load(PACKAGE / "manifest.json") if (PACKAGE / "manifest.json").is_file() else None
    # Manifest is written after this validator in the builder; all package files are checked below.
    files = [p for p in PACKAGE.rglob("*") if p.is_file()]
    ensure(not any(p.suffix.lower() in SCIENCE for p in files), "scientific array file is present in source package")
    for p in files:
        if p.suffix == ".json": load(p)
        elif p.suffix == ".py": ast.parse(p.read_text())
    if manifest:
        ensure(manifest["fresh_id"] == "fresh088" and manifest["family_id"] == "F1", "manifest identity")
        ensure(manifest["execution_allowed"] is False and manifest["launch_allowed"] is False, "manifest must be disabled")
        ensure(manifest["arrays_read"] is False and manifest["arrays_hashed"] is False, "manifest array policy")
    contract = load(PACKAGE / "metadata/contracts/typed-conversion-contract.json")
    ensure(contract["cpu_task_kind"] == "conversion" and contract["conversion_slots"] == 2, "conversion contract")
    ensure(contract["staging_limit_bytes"] == 25769803776 and contract["free_space_floor_bytes"] == 107374182400, "NVMe limits")
    ensure("--decoder" in contract["required_command_keys"] and "--partvtk" in contract["required_command_keys"], "decoder/PartVTK keys")
    root230 = load(PACKAGE / "metadata/root230-policy.json")
    ensure(root230["disabled"] is True and root230["launch_allowed"] is False, "Root230 policy")
    summary = load(PACKAGE / "metadata/root307-frame0-qa-summary.json")
    ensure(summary["all_completed_zero_pass"] is True and summary["actual_case_count"] == 8, "Root307 summary")
    requests = []
    for case in CASES:
        req_path = PACKAGE / "requests" / f"{case}.full-native-typed-nvme.request.json"
        bind_path = PACKAGE / "bindings" / f"{case}.typed-nvme-binding.json"
        owner_path = PACKAGE / "owners" / f"{case}.typed-owner.json"
        req, bind, owner = load(req_path), load(bind_path), load(owner_path)
        requests.append(req)
        ensure(req["fresh_id"] == bind["fresh_id"] == owner["fresh_id"] == "fresh088", f"fresh id {case}")
        ensure(req["cpu_task_kind"] == "conversion" and req["kind"] == "cpu" and req["cpu_threads"] == 2, f"CPU conversion {case}")
        ensure(req["estimated_storage_bytes"] == 25769803776 and req["max_wall_seconds"] == 14400, f"resource fields {case}")
        ensure(req["launch_owner"] == "root" and req["launch"] is False and req["launch_allowed"] is False and req["execution_allowed"] is False and req["disabled"] is True, f"disabled state {case}")
        ensure(req["depends_on_attempts"] and len(req["depends_on_attempts"]) == 3, f"dependency chain {case}")
        ensure(req["actual_gencase_initial_qa"]["status"] == "completed/0" and req["actual_gencase_initial_qa"]["passed"] is True, f"GenQA evidence {case}")
        ensure(req["actual_native_receipt"]["status"] == "completed/0" and req["actual_native_receipt"]["observed_frame_file_count"] == req["actual_native_receipt"]["expected_frames"], f"native evidence {case}")
        ensure(req["actual_native_frame0_qa"]["status"] == "completed/0" and req["actual_native_frame0_qa"]["passed"] is True, f"frame0 evidence {case}")
        ensure(bind["actual_native_frame0_qa"]["max_abs_velocity_error_m_per_s"] == 0.0, f"frame0 velocity evidence {case}")
        ensure(bind["typed_output_sha256"] is None and bind["typed_conversion_report_sha256"] is None and bind["typed_execution_receipt_sha256"] is None, f"future binding hashes {case}")
        ensure(req["future_input_sha256"] is None and req["future_outputs"]["trajectory_h5_sha256"] is None, f"future request hashes {case}")
        ensure(bind["legacy_h5_physical_condition_sha256"] is None and owner["legacy_h5_physical_condition_scope"]["schema"] == "legacy-owner-scope.v0", f"legacy scope separation {case}")
        ensure(owner["physical_condition_sha256"] != bind["legacy_h5_physical_condition_scope"].get("legacy_h5_physical_condition_sha256"), f"canonical/legacy confusion {case}")
        command = req["command"]
        ensure(command[0] == "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", f"approved interpreter {case}")
        for key in ["--data-root", "--generated-xml", "--solver-log", "--solver-receipt", "--gencase-receipt", "--decoder", "--partvtk", "--validation-dir", "--owner-metadata", "--particle-chunk"]:
            ensure(key in command, f"missing converter worker key {key}: {case}")
        ensure(command[command.index("--decoder") + 1] == "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump", f"approved BASE decoder {case}")
        ensure(command[command.index("--partvtk") + 1].endswith("PartVTK_linux64"), f"approved PartVTK {case}")
        ensure(req["nvme_policy"]["conversion_slots"] == 2 and req["nvme_policy"]["staging_limit_bytes"] == 25769803776, f"request NVMe policy {case}")
        ensure(req["typed_field_contract"]["actual_native_dimension"] == 3 and req["typed_field_contract"]["required_fields"] == ["Idp", "Zone", "Type", "Mk", "position", "velocity", "density", "mass", "pressure"], f"typed field contract {case}")
        ensure(req["raw_arrays_read"] is False and req["mass_rescale"] is False, f"array/mass guard {case}")
        declared = req["input_sha256"]
        ensure(set(declared) == set(req["input_files"]), f"input hash closure keys {case}")
        for raw in req["input_files"]:
            p = Path(raw)
            ensure(p.is_file(), f"input missing {case}: {p}")
            ensure(p.suffix.lower() not in SCIENCE, f"scientific input registered {case}: {p}")
            ensure(sha(p) == declared[raw], f"input digest mismatch {case}: {p}")
        # Executable key checks inspect the real scripts, not merely request syntax.
        converter = Path(command[1]).read_text()
        direct = Path(req["nvme_policy"]["converter"]).read_text()
        ensure("staging_limit_bytes" in converter and "verified_copy" in converter and "convert_direct" in converter, f"NVMe worker implementation guard {case}")
        ensure("decode_frame" in direct and "partvtk" in direct and "owner_metadata" in direct, f"direct converter implementation guard {case}")
    ensure(len(requests) == 8, "request count")
    result = {"status": "pass", "fresh_id": "fresh088", "family_id": "F1", "cases": 8, "root307_frame0_completed0_pass": True, "typed_requests_disabled": True, "conversion_slots": 2, "arrays_opened": False, "jobs_started": False}
    arg = argparse.ArgumentParser(); arg.add_argument("--output")
    opts = arg.parse_args()
    if opts.output: Path(opts.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))

if __name__ == "__main__": main()

#!/usr/bin/env python3
"""Metadata/AST-only preflight for the fresh098 full801 bed-audit template.

It never opens the future H5/XMF/BI4/CSV products and never invokes the worker
or runtime.  Root must create a new bound sidecar with producer metadata before
enabling the request.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINDING = ROOT / "bindings/full-event-bed-audit-binding.json"
REQUEST = ROOT / "requests/full-bed-audit-request.json"
WORKER = ROOT / "workers/bed_audit_full801.py"
CONTRACT = ROOT / "metadata/full801-bed-audit-contract.json"
FRESH097 = ROOT.parent / "root_followup_097_stage1_f5_c082s1_full801_disabled_pipeline_v1"
FRESH097_TYPED = FRESH097 / "requests/full-typed-801-request.json"
FRESH097_XMF = FRESH097 / "requests/full-xmf-801-request.json"
NATIVE_RECEIPT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-qualification-349/execution-receipt.json")
SCIENCE_SUFFIXES = {".dat", ".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu"}
EXPECTED_COUNTS = {"total_particles": 194427, "fixed_particles": 158559, "moving_particles": 4210, "floating_particles": 0, "fluid_particles": 31658, "solver_dimension": 3}


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"object expected: {path}")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    binding = load(BINDING)
    request = load(REQUEST)
    contract = load(CONTRACT)
    typed = load(FRESH097_TYPED)
    xmf = load(FRESH097_XMF)

    require(binding["schema"] == "ds02.f5.c082s1.full-event-bed-audit-binding.fresh098.v1", "binding schema mismatch")
    require(binding["status"].startswith("template_disabled"), "binding is not a future template")
    require(binding["expected_frames"] == 801 and binding["full_event"]["window_s"] == [0.0, 16.0], "full time contract mismatch")
    require(binding["actual_counts"] == {"fixed_particles": 158559, "floating_particles": 0, "fluid_particles": 31658, "moving_particles": 4210, "solver_dimension": 3, "total_particles": 194427, "xml_particle_counts": {"fixed": 158559, "floating": 0, "fluid": 31658, "moving": 4210}}, "actual counts changed")
    require(binding["native_bed_marker_mk"] == 50 and binding["source_bed_marker_mkbound"] == 40, "Mk mapping changed")
    require(binding["bed_y_bounds_m"] == [-0.22, 0.22] and binding["penetration_bins_m"] == [0.02, 0.04], "bed profile contract changed")
    require(binding["full_native_attempt_id"].endswith("-349"), "native349 identity missing")
    require(binding["full_native_receipt"].endswith("execution-receipt.json"), "native receipt path missing")
    require(binding["full_native_receipt_sha256"] == digest(NATIVE_RECEIPT), "native349 receipt hash mismatch")
    for key in ("full_typed_receipt", "full_typed_receipt_sha256", "full_typed_conversion_report", "full_typed_conversion_report_sha256", "trajectory_h5", "trajectory_h5_sha256", "xmf_manifest", "xmf_manifest_sha256", "xdmf", "xdmf_sha256"):
        require(isinstance(binding[key], str) and binding[key].startswith("<root-bind:"), f"future binding {key} is not a placeholder")
    require(binding["full_typed_attempt_id"] == typed["attempt_id"] == "root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-typed-nvme-350", "typed350 binding mismatch")
    require(binding["full_xmf_attempt_id"] == xmf["attempt_id"] == "root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-xmf-351", "XMF351 binding mismatch")
    require(binding["future_output_hashes"] is None and binding["full801_authorized"] is False, "future authorization/hash changed")
    require(binding["science_arrays_read_by_binder"] is False and binding["science_arrays_hashed_by_binder"] is False, "binding array policy changed")

    require(request["schema"] == "ds02.runner-request.v2", "request schema mismatch")
    required = {"kind", "cpu_task_kind", "command", "cwd", "worktree_root", "max_wall_seconds", "cpu_threads", "estimated_storage_bytes", "input_files", "input_sha256", "execution_allowed", "launch", "launch_allowed", "disabled", "full801_authorized", "future_output_hashes"}
    require(required.issubset(request), f"request missing keys: {sorted(required.difference(request))}")
    require(request["kind"] == "cpu" and request["cpu_task_kind"] == "audit", "runtime kind/task mismatch")
    require(request["attempt_id"] == "root-stage1-f5-c082s1-full801-native-bed-audit-353", "audit attempt identity mismatch")
    require(request["depends_on_attempt"] == xmf["attempt_id"], "audit dependency mismatch")
    require(request["expected_frames"] == 801 and request["time_window_s"] == [0.0, 16.0] and request["save_interval_s"] == 0.02, "request full time mismatch")
    request_count_keys = {
        "total_particles": "expected_particles",
        "fixed_particles": "expected_fixed_particles",
        "moving_particles": "expected_moving_particles",
        "floating_particles": "expected_floating_particles",
        "fluid_particles": "expected_fluid_particles",
        "solver_dimension": "expected_dimension",
    }
    for key, value in EXPECTED_COUNTS.items():
        require(request[request_count_keys[key]] == value, f"request count/dimension mismatch: {key}")
    require(request["execution_allowed"] is False and request["launch"] is False and request["launch_allowed"] is False and request["disabled"] is True, "request enabled")
    require(request["full801_authorized"] is False and request["future_output_hashes"] is None, "request future gate changed")
    require(set(request["input_files"]) == set(request["input_sha256"]), "input/hash closure mismatch")
    for raw in request["input_files"]:
        path = Path(raw)
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science artifact registered: {path}")
        require(path.is_file(), f"missing input source: {path}")
        require(isinstance(request["input_sha256"][raw], str) and len(request["input_sha256"][raw]) == 64, f"bad input hash: {path}")
    require(str(NATIVE_RECEIPT) in request["input_files"], "native349 receipt not registered")
    require(str(FRESH097_TYPED) in request["input_files"] and str(FRESH097_XMF) in request["input_files"], "source097 typed/XMF request metadata missing")
    require(request["source_arrays_read_or_hashed_by_source_agent"] is False, "request array policy changed")

    native = load(NATIVE_RECEIPT)
    require(native["status"] == "completed" and native["returncode"] == 0, "native349 receipt is not completed/0")
    require(native["request"]["attempt_id"] == binding["full_native_attempt_id"] and native["request"]["expected_frames"] == 801, "native349 receipt identity/frame mismatch")
    require(typed["attempt_id"] == binding["full_typed_attempt_id"] and typed["execution_allowed"] is False and typed["future_output_hashes"] is None, "fresh097 typed template changed")
    require(xmf["attempt_id"] == binding["full_xmf_attempt_id"] and xmf["execution_allowed"] is False and xmf["future_output_hashes"] is None, "fresh097 XMF template changed")

    require(contract["frames"] == 801 and contract["window_s"] == [0.0, 16.0], "contract full time mismatch")
    require(contract["short_event_evidence_reused_as_pass"] is False and contract["full801_authorized"] is False, "short evidence was promoted")

    source = WORKER.read_text(encoding="utf-8")
    require("EXPECTED_FRAMES = 801" in source, "worker frame constant mismatch")
    require("BINDING_SCHEMA = \"ds02.f5.c082s1.full-event-bed-audit-binding.fresh098.v1\"" in source, "worker binding schema mismatch")
    require("all 801 actual native saved frames" in source and "full_event_limit" in source, "worker full-event scope missing")
    require("short event" not in source.lower() or "short-event pass is not reused" in source.lower(), "worker contains an unbounded short-event claim")
    require("EXPECTED_FRAMES = 51" not in source and "0..1 s" not in source, "worker retained short time contract")
    tree = ast.parse(source, filename=str(WORKER))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    require(not ({"subprocess", "Popen", "run_job"} & names) and not ({"system", "Popen", "run_job"} & attrs), "worker has a dispatch primitive")

    summary = {
        "schema": "ds02.f5.c082s1.fresh098.metadata-preflight.v1",
        "status": "pass_disabled_full801_audit_template",
        "attempt_id": request["attempt_id"],
        "window_s": request["time_window_s"],
        "frames": request["expected_frames"],
        "typed_attempt": binding["full_typed_attempt_id"],
        "xmf_attempt": binding["full_xmf_attempt_id"],
        "native349_receipt_sha256": binding["full_native_receipt_sha256"],
        "future_h5_xmf_hashes": None,
        "short_event_evidence_reused_as_pass": False,
        "execution_disabled": True,
        "science_arrays_read_or_hashed_by_source_agent": False,
        "job_started_by_source_agent": False,
    }
    if args.write_report:
        (ROOT / "metadata/fresh098-preflight-report.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

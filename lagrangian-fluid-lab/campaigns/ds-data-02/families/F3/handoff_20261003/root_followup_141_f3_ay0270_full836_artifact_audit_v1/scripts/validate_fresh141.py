#!/usr/bin/env python3
"""Metadata-only fresh141 contract validator.

This validator deliberately does not open or hash H5, BI4, CSV, DAT, VTK, NPY,
or other scientific payloads.  It verifies the disabled request, small JSON
provenance, source/code digest closure, and future-null contract only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".h5part", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz"}
HEX = set("0123456789abcdefABCDEF")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def ref(value: object, label: str) -> dict:
    require(isinstance(value, dict), f"{label} ref is not an object")
    path = Path(value.get("path", ""))
    digest = value.get("sha256")
    require(path.is_absolute() and path.is_file(), f"{label} path missing")
    require(isinstance(digest, str) and len(digest) == 64 and all(c in HEX for c in digest),
            f"{label} digest malformed")
    require(path.suffix.lower() not in PAYLOAD_SUFFIXES,
            f"payload path entered metadata digest closure: {path}")
    require(sha(path) == digest, f"{label} digest drift")
    return value


def main() -> int:
    binding_path = HERE / "metadata" / "ay0270-audit-binding.json"
    request_path = HERE / "requests" / "ay0270_full836_scientific_artifact_audit.disabled-request.json"
    comparison_path = HERE / "metadata" / "source-audit-kernel-comparison.json"
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))

    require(binding["schema"] == "ds02.fresh141.ay0270-full836-audit-binding.v1", "binding schema")
    require(binding["source_only"] is True and binding["execution_allowed"] is False and binding["launch_allowed"] is False, "binding is enabled")
    require(request["schema"] == "ds02.runner-request.v2", "request schema")
    require(request["source_only"] is True and request["disabled"] is True, "request source-only flags")
    require(request["execution_allowed"] is False and request["launch_allowed"] is False, "request launch flags")
    require(request["cpu_task_kind"] == "audit" and request["cpu_threads"] == 2, "CPU audit profile")
    require(request["runtime_policy"]["controller"] == "Root142/928", "Root controller profile")
    require(request["runtime_policy"]["serial_audit_cap"] == 1, "audit serial cap")
    require(request["launch_owner"] == "root", "launch owner")
    require(request["physical_binding"]["physical_case_id"] == "F3_TWOAXIS_PITCH1000_AY0270_STAGE1_FIRST24_NEW", "actual physical ID")
    require(request["physical_binding"]["census_alias"] != request["physical_binding"]["physical_case_id"], "alias was collapsed into actual ID")
    require(request["source_conversion_lifecycle"]["status"] in {"running", "interrupted_unfinalized"}, "old lifecycle")
    require(request["source_conversion_lifecycle"]["returncode"] is None, "old returncode was filled")
    require(request["source_conversion_lifecycle"]["old_launcher_tool_status"] == 143, "old tool status")
    require(request["source_conversion_lifecycle"]["must_not_edit_receipt"] is True, "receipt edit guard")
    require(request["opaque_scientific_inputs"]["source_agent_sha256"] is None, "source agent H5 hash")
    enablement = request["root_enablement"]
    require(enablement["derive_new_request_before_strict_dispatch"] is True, "Root derivation guard")
    require(enablement["source_request_is_intentionally_not_strict_dispatchable"] is True,
            "disabled request must disclose strict-dispatch boundary")
    require(enablement["required_root_h5_input_sha256_key"] == request["opaque_scientific_inputs"]["trajectory_h5"],
            "Root H5 input key drift")
    require(request["future_outputs"]["audit_receipt_sha256"] is None, "future audit receipt hash")
    require(request["future_outputs"]["audit_report_sha256"] is None, "future audit report hash")
    require(request["future_outputs"]["observed_h5_sha256"] is None, "future observed H5 hash")

    command = request["command"]
    require(str(HERE / "scripts" / "ay0270_full836_scientific_audit_worker.py") in command, "worker missing from command")
    require(str(binding_path) in command, "binding missing from command")
    require("{attempt_root}/full836-scientific-artifact-audit.json" in command, "output is not attempt scoped")

    # Hash only explicitly allow-listed small code/JSON metadata inputs.  H5 is
    # present in input_files as a Root-owned runtime input but absent here.
    input_sha = request["input_sha256"]
    input_files = set(request["input_files"])
    h5_path = request["opaque_scientific_inputs"]["trajectory_h5"]
    require(h5_path in input_files and h5_path not in input_sha, "H5 must be Root-only digest input")
    for path_text, expected in input_sha.items():
        path = Path(path_text)
        require(path.is_absolute(), f"input path is not absolute: {path}")
        require(path.suffix.lower() not in PAYLOAD_SUFFIXES, f"payload entered input digest map: {path}")
        require(path.is_file(), f"input path missing: {path}")
        require(isinstance(expected, str) and len(expected) == 64, f"input hash malformed: {path}")
        require(sha(path) == expected, f"input hash drift: {path}")

    for name, value in binding["metadata_refs"].items():
        ref(value, name)
    for name, value in binding["runtime_contract"].items():
        if isinstance(value, dict) and "path" in value:
            ref(value, name)
    ref(binding["approved_temporal_kernel"], "approved_temporal_kernel")

    worker_path = HERE / "scripts" / "ay0270_full836_scientific_audit_worker.py"
    worker_text = worker_path.read_text(encoding="utf-8")
    require("f3_full_temporal_verify_v1" in worker_text, "approved temporal kernel not referenced")
    require("source_receipt_edited" in worker_text and "source_conversion_reclassified" in worker_text, "lifecycle output guards")
    require("write_new_json" in worker_text, "atomic audit output writer missing")
    require("trajectory.h5" not in {p.name for p in HERE.rglob("*") if p.is_file()}, "payload copied into package")
    require(not any(p.is_file() and p.suffix.lower() in PAYLOAD_SUFFIXES for p in HERE.rglob("*")), "payload file in source package")

    require(comparison["existing_opaque_kernel"]["limitation"].startswith("does not decode H5"), "old kernel limitation was hidden")
    require(comparison["fresh141_adapter"]["source_payload_policy"].startswith("H5 reads/hash are Root"), "payload ownership disclosure")

    result = {
        "schema": "ds02.fresh141.metadata-validator-result.v1",
        "fresh_id": "fresh141",
        "status": "PASS",
        "metadata_inputs_hashed": len(input_sha),
        "scientific_payloads_opened": False,
        "scientific_payloads_hashed": False,
        "source_package_payload_files": 0,
        "disabled_audit": True,
        "old_receipt_edit": False,
        "old_returncode_reclassification": False,
        "future_audit_hashes": None,
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

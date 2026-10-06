#!/usr/bin/env python3
"""Metadata-only validator for fresh131.

The validator checks request/binding/receipt contracts and fixed package hashes.
It never opens a BI4, DAT, H5, CSV, VTK, or solver payload.  Producer-attested
hashes for those inputs are checked for presence and provenance only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PKG = Path(__file__).resolve().parents[1]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1")
TAGS = [
    "M085_T090", "M085_T100",
    "M095_T080", "M095_T090", "M095_T100",
    "M105_T080", "M105_T090", "M105_T100",
    "M115_T080", "M115_T090",
]
DENIED_SUFFIXES = {".bi4", ".dat", ".h5", ".csv", ".vtk", ".vtu", ".vtp"}


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fail(message: str) -> None:
    raise AssertionError(message)


def main() -> None:
    manifest = load(PKG / "manifest.json")
    if manifest.get("source_only") is not True:
        fail("manifest is not source-only")
    manifest_paths = {entry["path"] for entry in manifest["files"]}
    if "manifest.json" in manifest_paths or "metadata/fresh131-validator-report.json" in manifest_paths:
        fail("manifest self-reference or report self-reference")
    for entry in manifest["files"]:
        path = PKG / entry["path"]
        if not path.exists():
            fail(f"missing manifest file: {path}")
        if path.suffix.lower() in DENIED_SUFFIXES:
            fail(f"scientific payload entered source package: {path}")
        if sha(path) != entry["sha256"]:
            fail(f"manifest hash mismatch: {path}")

    plan = load(PKG / "metadata/fresh131-source-plan.json")
    if plan.get("candidate_tags") != TAGS or plan.get("candidate_count") != 10:
        fail("candidate set is not exactly the ten non-T120 tags")
    if any("T120" in tag for tag in plan["candidate_tags"]):
        fail("T120 was included")
    if plan.get("full_native_authorized") is not False or plan.get("remaining10_release_enabled") is not False:
        fail("release gate was enabled")
    gate = plan["gate"]
    if gate.get("status") != "WAIT" or gate.get("remaining10_release_enabled") is not False:
        fail("endpoint visual gate is not WAIT")

    results = []
    for tag in TAGS:
        binding_path = PKG / f"bindings/{tag}-full801-native-release-binding.json"
        request_path = PKG / f"requests/{tag}-full801-native-release-request.json"
        binding = load(binding_path)
        request = load(request_path)
        if binding.get("source_only") is not True:
            fail(f"{tag}: binding is not source-only")
        for flag in ["disabled", "execution_allowed", "launch", "launch_allowed", "full801_authorized", "full_native_authorized"]:
            if flag in request:
                expected = True if flag == "disabled" else False
                if request[flag] is not expected:
                    fail(f"{tag}: {flag}={request[flag]!r}")
        if request.get("kind") != "qualification" or request.get("cpu_task_kind") != "solver":
            fail(f"{tag}: wrong solver request kind")
        if request.get("expected_frames") != 801 or request.get("tmax_s") != 16.0 or request.get("tout_s") != 0.02:
            fail(f"{tag}: wrong native time contract")
        if binding.get("expected_frames") != 801 or binding.get("qualification_window_s") != [0.0, 16.0]:
            fail(f"{tag}: wrong binding time contract")
        if binding.get("native_bed_marker_mk") != 50 or binding.get("source_mkbound") != 40:
            fail(f"{tag}: marker mapping changed")
        if binding.get("actual_initial_qa", {}).get("basic_placement_checks_pass") is not True:
            fail(f"{tag}: initial placement proof missing")
        if binding.get("actual_initial_qa", {}).get("exact_dp_lattice", {}).get("accepted_as_stage1_gate") is not False:
            fail(f"{tag}: precision negative not preserved")
        if request.get("upstream_full801_visual_gate", {}).get("status") != "WAIT":
            fail(f"{tag}: upstream visual gate not WAIT")
        if any("<root-bind:" in str(value) for value in request.values()):
            fail(f"{tag}: unresolved root-bind placeholder in request")
        for arg in request.get("command", []):
            if "<root-bind:" in str(arg):
                fail(f"{tag}: unresolved command placeholder")
        input_files = request.get("input_files", [])
        input_sha = request.get("input_sha256", {})
        provenance = request.get("input_sha256_provenance", {})
        if set(input_files) != set(input_sha) or set(input_files) != set(provenance):
            fail(f"{tag}: input hash closure mismatch")
        for path, value in input_sha.items():
            suffix = Path(path).suffix.lower()
            if suffix in DENIED_SUFFIXES:
                if value is None:
                    fail(f"{tag}: producer-attested payload hash missing for {path}")
                if "producer-attested" not in provenance[path]:
                    fail(f"{tag}: payload provenance is not producer-attested for {path}")
            elif path.startswith("<"):
                fail(f"{tag}: unresolved input placeholder {path}")
        gencase_receipt = Path(binding["genuine_gencase"]["receipt"])
        qa_receipt = Path(binding["actual_initial_qa"]["receipt"])
        qa_report = Path(binding["actual_initial_qa"]["report"])
        if load(gencase_receipt).get("returncode") != 0 or load(gencase_receipt).get("status") not in {"completed", "completed/0"}:
            fail(f"{tag}: GenCase is not completed/0")
        if load(qa_receipt).get("returncode") != 0 or load(qa_receipt).get("status") != "completed":
            fail(f"{tag}: initial QA receipt is not completed/0")
        report = load(qa_report)
        if report.get("status") != "completed_stage1_placement_mk50_diagnostic" or report.get("all_basic_placement_checks_pass") is not True:
            fail(f"{tag}: actual placement report does not pass basic gate")
        if report.get("numerical_precision_result_accepted", report.get("numerical_precision", {}).get("accepted_as_stage1_placement_gate", True)):
            fail(f"{tag}: exact-DP negative was accepted")
        results.append({
            "tag": tag,
            "request": str(request_path),
            "request_sha256": sha(request_path),
            "binding": str(binding_path),
            "binding_sha256": sha(binding_path),
            "actual_counts": binding["actual_counts"],
            "gencase_status": "completed/0",
            "initial_qa_status": "completed/0",
            "basic_placement_pass": True,
            "precision_status": "diagnostic_negative_preserved",
            "future_hashes_null": all(value is None for value in request["future_output_hashes"].values()),
        })

    report = {
        "schema": "ds02.f5.c082s1.fresh131-validator-report.v1",
        "status": "passed_metadata_only",
        "candidate_count": len(results),
        "results": results,
        "root783_root786_gate": "WAIT",
        "remaining10_release_enabled": False,
        "T120_included": False,
        "scientific_payloads_read_or_hashed_by_validator": False,
        "jobs_started": False,
        "shared_state_modified": False,
        "manifest_report_excluded_from_fixed_hash_set": True,
    }
    (PKG / "metadata/fresh131-validator-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "candidate_count": len(results), "report": str(PKG / 'metadata/fresh131-validator-report.json')}, indent=2))


if __name__ == "__main__":
    main()

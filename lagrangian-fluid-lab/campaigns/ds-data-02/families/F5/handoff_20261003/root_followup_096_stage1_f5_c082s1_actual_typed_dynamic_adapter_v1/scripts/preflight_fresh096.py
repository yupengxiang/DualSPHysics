#!/usr/bin/env python3
"""Metadata-only contract preflight for fresh096.

This checker reads only package JSON and Python source text/AST.  It does not
open or hash trajectory H5, BI4, CSV, or any scientific array product, and it
does not invoke the bed worker.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINDING = ROOT / "bindings/short-event-bed-audit-binding.json"
REQUEST = ROOT / "requests/dynamic-bed-audit-request.json"
SUMMARY = ROOT / "metadata/actual-typed317-xmf318-summary.json"
WORKER = ROOT / "workers/bed_audit.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def main() -> int:
    binding = load(BINDING)
    request = load(REQUEST)
    summary = load(SUMMARY)
    require(binding["schema"] == "ds02.f5.c082s1.short-event-bed-audit-binding.fresh096.v1", "binding schema mismatch")
    require(binding["case_id"] == "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1", "case identity mismatch")
    require(binding["physical_case_id"] == "F5_COMPACT_STILL_WATER_RUNUP_RECOVERY_C082S1", "physical owner mismatch")
    require(binding["physical_condition_sha256"] == "e691d030eda575b9cfabe62f295c9bdc142e5a04cb4357c9fe2790aaec549dbf", "canonical hash mismatch")
    require(binding["source_plan_physical_condition_sha256"] == "5bad3ec9f9a71aa87da8272003c357f4523d4ffa164d3f06e5d25fee1a4fbfa6", "source-plan hash mismatch")
    require(binding["source_h5_physical_condition_sha256"] == "3cd1ceab16be11428bbc1011a1b4e297c384d8c7926432c222c254064744ccd0", "legacy scope mismatch")
    require(binding["expected_frames"] == 51 and binding["expected_particle_axis"] == 194427, "frame/axis contract mismatch")
    counts = binding["actual_counts"]
    require(counts == {"fixed_particles": 158559, "floating_particles": 0, "fluid_particles": 31658, "moving_particles": 4210, "solver_dimension": 3, "total_particles": 194427, "xml_particle_counts": {"fixed": 158559, "floating": 0, "fluid": 31658, "moving": 4210}}, "placement actual_counts were not preserved verbatim")
    require(binding["stage1_placement"]["numerical_precision_result_accepted"] is False, "precision failure was relabelled")
    require(binding["stage1_placement"]["central_mk50_surface_half_dp_counts"] == [208, 27, 22, 15, 20, 20], "Mk50 coverage mismatch")
    require(binding["native_conversion_metadata"]["frames"] == 51 and binding["native_conversion_metadata"]["particles"] == 194427, "typed dimensions mismatch")
    require(binding["native_conversion_metadata"]["observed_mks"] == [1, 10, 20, 40, 50], "typed Mk identity mismatch")
    require(binding["native_conversion_metadata"]["observed_types"] == [0, 1, 3], "typed type identity mismatch")
    require(binding["trajectory_h5"].endswith(".h5") and len(binding["trajectory_h5_sha256"]) == 64, "H5 producer binding missing")
    require(binding["xdmf"].endswith(".xmf") and len(binding["xdmf_sha256"]) == 64, "XMF binding missing")
    require(binding["xmf_manifest"].endswith("manifest.json") and len(binding["xmf_manifest_sha256"]) == 64, "XMF manifest binding missing")
    require(binding["future_output_hashes"] is None and binding["full801_authorized"] is False, "future/full authorization changed")
    require(binding["science_arrays_read_by_binder"] is False and binding["science_arrays_hashed_by_binder"] is False, "binder science-array policy changed")

    require(request["schema"] == "ds02.runner-request.v2", "request schema mismatch")
    require(request["disabled"] is True and request["execution_allowed"] is False and request["launch"] is False, "request is enabled")
    require(request["solver_allowed"] is False and request["conversion_allowed"] is False, "request enables solver/conversion")
    require(request["full801_authorized"] is False and request["future_output_hashes"] is None, "request future authorization/hash changed")
    require(request["cpu_task_kind"] == "audit" and request["worker_kind"] == "dynamic_bed_footprint_audit", "runtime task kind mismatch")
    require(request["actual_counts"] == counts and request["binding_contract"]["actual_counts_full_placement_copy"] == counts, "request count copy mismatch")
    input_files = request["input_files"]
    require(binding["trajectory_h5"] in input_files and binding["xdmf"] in input_files, "runtime artifacts not registered")
    require(not any(path.lower().endswith((".bi4", ".csv")) for path in input_files), "BI4/CSV science input registered")
    require(request["input_sha256_provenance"]["trajectory_h5"].startswith("producer-declared"), "H5 provenance not explicit")
    require(request["source_arrays_read_or_hashed_by_source_agent"] is False, "request array policy changed")

    require(summary["status"] == "actual_upstream_metadata_bound_root_review_required", "summary status mismatch")
    require(summary["xmf318"]["manifest_sha256"] == binding["xmf_manifest_sha256"], "summary XMF hash mismatch")
    require(summary["typed317"]["producer_h5_sha256_from_report_only"] == binding["trajectory_h5_sha256"], "summary H5 provenance mismatch")

    tree = ast.parse(WORKER.read_text(encoding="utf-8"), filename=str(WORKER))
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except Exception:
                pass
    require(constants.get("BINDING_SCHEMA") == binding["schema"], "worker binding schema differs")
    require(constants.get("PHYSICAL_CASE_ID") == binding["physical_case_id"], "worker physical case constant differs")
    require(constants.get("SOURCE_H5_PHYSICAL_CONDITION_SHA256") == binding["source_h5_physical_condition_sha256"], "worker legacy H5 scope constant differs")
    require(constants.get("EXPECTED_FRAMES") == 51 and constants.get("EXPECTED_PARTICLE_AXIS") == 194427, "worker scientific contract changed")
    print(json.dumps({"status": "fresh096_metadata_preflight_pass", "worker": str(WORKER), "binding": str(BINDING), "request_disabled": True, "arrays_read": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

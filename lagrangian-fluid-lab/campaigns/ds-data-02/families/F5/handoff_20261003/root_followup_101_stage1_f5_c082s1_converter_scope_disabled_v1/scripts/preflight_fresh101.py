#!/usr/bin/env python3
"""Source-only structural preflight for F5 fresh101.

It validates only package JSON/XML/Python metadata and static input hashes.  It
never opens DAT/BI4/CSV/H5/VTK/XMF/science payloads and never starts a job.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parents[1]
SCIENCE_SUFFIXES = {".dat", ".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".xmf", ".xdmf"}


def load(path: Path) -> Any:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise ValueError(f"science artifact is forbidden in fresh101 preflight: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise ValueError(f"science artifact hash is forbidden in fresh101 preflight: {path}")
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    reports = {}
    for tag in ("A080", "A120"):
        report_path = PACKAGE / "metadata" / f"{tag.lower()}-converter-scope-report.json"
        report = load(report_path)
        require(report["status"] == "passed_with_converter_hold", f"{tag}: report status")
        require(report["converter_scope_probe"]["scope_schema"] == "legacy-owner-scope.v0", f"{tag}: scope schema")
        require(report["converter_scope_probe"]["direct_conversion_eligible"] is False, f"{tag}: conversion hold")
        require(report["hash_layers"]["all_layers_distinct"] is True, f"{tag}: identity layers collapsed")
        require(report["fresh099_owner_identity"]["matches_declared"] is True, f"{tag}: owner identity")
        require(report["baseline_c082s1_actual_provenance"]["actual_counts"]["fluid_particles"] == 31658, f"{tag}: baseline fluid count")
        require(report["baseline_c082s1_actual_provenance"]["actual_counts"]["fixed_particles"] == 158559, f"{tag}: baseline fixed count")
        require(report["baseline_c082s1_actual_provenance"]["actual_counts"]["moving_particles"] == 4210, f"{tag}: baseline moving count")
        require(report["baseline_c082s1_actual_provenance"]["actual_counts"]["total_particles"] == 194427, f"{tag}: baseline total count")
        require(report["future_producer_values"]["actual_counts"] is None, f"{tag}: future counts were filled")
        require(report["future_producer_values"]["generated_xml_sha256"] is None, f"{tag}: future XML hash was filled")
        require(report["gencase_contract"]["request_disabled"] is True, f"{tag}: disabled GenCase contract")
        flow = load(PACKAGE / "metadata" / f"{tag}-disabled-stage-flow.json")
        require(flow["converter_direct_conversion_eligible"] is False, f"{tag}: flow conversion hold")
        require(all(stage.get("disabled") is True for stage in flow["stages"]), f"{tag}: downstream stage enabled")
        require(flow["root230_semantic_gencase_fields"]["actual_total_particles"] is None, f"{tag}: Root230 count guessed")
        require(flow["root230_semantic_gencase_fields"]["solver_dimension_from_gencase"] is None, f"{tag}: Root230 dimension guessed")
        reports[tag] = {
            "report": str(report_path.resolve()),
            "report_sha256": sha(report_path),
            "converter_scope_sha256": report["converter_scope_probe"]["scope_sha256"],
            "owner_identity_sha256": report["fresh099_owner_identity"]["declared_canonical_physical_condition_sha256"],
            "source_plan_sha256": report["source_plan_physical_condition_sha256"],
        }

    requests_checked = 0
    request_summaries = {}
    for tag in ("A080", "A120"):
        path = PACKAGE / "requests" / f"{tag}-converter-scope-validator-request.json"
        request = load(path)
        require(request["schema"] == "ds02.runner-request.v2", f"{tag}: request schema")
        require(request["kind"] == "cpu" and request["cpu_task_kind"] == "audit", f"{tag}: request kind")
        require(request["disabled"] is True and request["execution_allowed"] is False and request["launch"] is False and request["launch_allowed"] is False, f"{tag}: request enabled")
        require(request["arrays_allowed"] is False and request["solver_allowed"] is False and request["conversion_allowed"] is False, f"{tag}: unsafe request capability")
        require(request["full801_authorized"] is False and request["full16_authorized"] is False and request["independent_case_count_increment"] == 0, f"{tag}: downstream gate")
        require(request["actual_counts"] is None and request["generated_xml_particle_counts"] is None and request["solver_dimension_from_gencase"] is None, f"{tag}: future producer value")
        require(request["converter_physical_condition_sha256"] is None, f"{tag}: converter hash guessed")
        for input_path in request["input_files"]:
            suffix = Path(input_path).suffix.lower()
            require(suffix not in SCIENCE_SUFFIXES, f"{tag}: science input listed: {input_path}")
            expected = request["input_sha256"].get(input_path)
            if expected is not None:
                require(Path(input_path).is_file(), f"{tag}: missing static input: {input_path}")
                require(sha(Path(input_path)) == expected, f"{tag}: static input SHA mismatch: {input_path}")
        request_summaries[tag] = {"request": str(path.resolve()), "request_sha256": sha(path), "disabled": True}
        requests_checked += 1

    mechanism = load(PACKAGE / "metadata" / "full801-mechanism-hold.json")
    require(mechanism["case_credit"] == 0 and mechanism["precision_granted"] is False and mechanism["visual_runup_acceptance"] is False, "mechanism hold was weakened")
    require(mechanism["shoreward_delta_m"] < 0.02, "mechanism hold evidence changed")
    for path in PACKAGE.rglob("*"):
        if path.is_file():
            require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science artifact added to package: {path}")

    result = {
        "schema": "ds02.f5.c082s1.fresh101-preflight.v1",
        "status": "passed_with_converter_hold",
        "source_only": True,
        "converter_scope_function_verified": "ds_data02_direct_convert._physical_condition_scope",
        "converter_hash_function_verified": "ds_data02_direct_convert.canonical_hash",
        "reports": reports,
        "requests": request_summaries,
        "requests_checked": requests_checked,
        "baseline_actual_counts": {"total": 194427, "fixed": 158559, "moving": 4210, "fluid": 31658, "floating": 0, "dimension": 3},
        "future_candidate_counts": None,
        "future_conversion_hashes": None,
        "root230_semantic_fields_future_only": True,
        "full801_enabled": False,
        "case_credit": 0,
        "precision_grant": False,
        "science_arrays_read": False,
        "science_arrays_hashed": False,
        "jobs_started": False,
        "shared_state_modified": False,
    }
    out = PACKAGE / "metadata" / "fresh101-preflight-report.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

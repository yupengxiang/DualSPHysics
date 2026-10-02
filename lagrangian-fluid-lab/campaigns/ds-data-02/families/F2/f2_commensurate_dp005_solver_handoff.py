#!/usr/bin/env python3
"""Register, but never launch, solver candidates for the DP005 views.

The DP005 GenCase and initial PartVTK/BI4 audit are already complete.  This
producer binds the actual completed GenCase directory, generated XML, BI4,
motion bytes, receipt, and frozen F2 contracts into a primary-process solver
request.  The current generated XML keeps ``TimeOut=.01``; therefore these
requests are explicitly macro-spatial candidates and cannot support the F2
event-time qualification until an independently produced ``.001`` view is
reviewed.  The producer performs no solver, conversion, or GPU launch.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET


FAMILY_ROOT = Path(__file__).resolve().parent
WORKTREE_ROOT = FAMILY_ROOT.parents[4]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
MANIFEST_DEFAULT = FAMILY_ROOT / "commensurate_cellcenter_dp005_v2/manifest.json"
AUDIT_REPORT_DEFAULT = DATA_ROOT / "families/F2/F2_COMM4_DP005_REPAIR01_INITIAL_AUDIT_V2/audit-f2-comm4-dp005-repair01-v2/report/commensurate-cellcenter-audit.json"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
QUALITY_CONTRACT = FAMILY_ROOT / "quality_contract.json"
EVENT_DEFINITIONS = FAMILY_ROOT / "event_definitions.json"
SAVE_PLAN = FAMILY_ROOT / "integration_save_plan.json"
CASE_REGISTRY = FAMILY_ROOT / "case_registry.jsonl"
REFERENCE_MATRIX = FAMILY_ROOT / "definitions/reference_matrix.json"
GOAL = FAMILY_ROOT.parents[1] / "GOAL_ZH.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def require_dir(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def input_binding(paths: list[Path]) -> dict[str, str]:
    return {str(path.resolve()): sha256(path) for path in paths}


def xml_parameters(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {
        item.get("key", ""): item.get("value", "")
        for item in root.findall(".//execution/parameters/parameter")
    }


def quality_thresholds(background: str) -> dict[str, Any]:
    contract = json.loads(require(QUALITY_CONTRACT, "quality contract").read_text(encoding="utf-8"))
    qn = contract["background_contracts"][background]["q_n"]
    return {
        "continuous_initial_mass_kg": 24.576,
        "native_mass_relative_budget_fraction": 1e-12,
        "event_time_absolute_budget_s": qn["event_time_absolute_budget_s"],
        "save_half_width_budget_s": qn["event_time_absolute_budget_s"] * qn["save_fraction_of_total_error_budget_max"],
        "macro_relative_error_threshold": qn["macro_relative_error_threshold"],
        "unknown_mass_remains_in_initial_denominator": True,
        "timing_qualification": False,
        "timing_qualification_reason": "TimeOut=.01 in the bound XML; event budget requires a separately reviewed .001 view",
    }


def make_request(entry: Mapping[str, Any], audit_case: Mapping[str, Any], output_dir: Path, request_path: Path) -> dict[str, Any]:
    case_id = str(entry["case_id"])
    background = str(entry["background"])
    receipt_path = require(Path(str(entry["receipt_path"])), f"{case_id} GenCase receipt")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"GenCase receipt is not completed: {receipt_path}")
    data_dir = require_dir(Path(str(receipt["output_root"])), f"{case_id} GenCase output")
    generated_xml = require(data_dir / f"{case_id}.xml", f"{case_id} generated XML")
    bi4 = require(data_dir / f"{case_id}.bi4", f"{case_id} BI4")
    motion = require(data_dir / f"{case_id}_motion.dat", f"{case_id} copied motion")
    metadata_path = require(Path(str(entry["metadata"]["path"])), f"{case_id} metadata")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    params = xml_parameters(generated_xml)
    if params.get("TimeMax") != "4" or params.get("TimeOut") != "0.01":
        raise ValueError(f"candidate requires the actual .01 baseline XML, got {params}")
    if int(receipt["solver_dimension_from_gencase"]) != 3 or int(receipt["fluid_particles"]) != int(entry["expected_population"]["total_particle_count"]):
        raise ValueError(f"GenCase population/dimension mismatch for {case_id}")
    total_particles = int(receipt["total_particles"])
    # 64 bytes/particle/frame is a lower-bound planning model.  Add 40% for
    # BI4/solver metadata and conversion headroom; root may reduce or reject
    # the candidate after its storage ledger review.
    frames = 4001
    raw_lower_bound = frames * total_particles * 64
    storage_estimate = int(raw_lower_bound * 1.4)
    physical_case_id = str(entry["physical_case_id"])
    new_case_id = f"{case_id}_REPAIR01_MACRO_SAVE010"
    attempt_id = f"qualification-{new_case_id.lower()}-native-fullstate-v1"
    source_xml = require(Path(str(metadata["source_definition"]["path"])), f"{case_id} source XML")
    source_motion = require(Path(str(metadata["source_motion"]["path"])), f"{case_id} source motion")
    audit_report_path = require(AUDIT_REPORT_DEFAULT, "DP005 initial audit report")
    common = [
        Path(__file__).resolve(), MANIFEST_DEFAULT.resolve(), audit_report_path,
        QUALITY_CONTRACT.resolve(), EVENT_DEFINITIONS.resolve(), SAVE_PLAN.resolve(),
        CASE_REGISTRY.resolve(), REFERENCE_MATRIX.resolve(), GOAL.resolve(), SOLVER.resolve(),
        receipt_path, generated_xml, bi4, motion, metadata_path, source_xml, source_motion,
    ]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "kind": "qualification",
        "family_id": "F2",
        "case_id": new_case_id,
        "attempt_id": attempt_id,
        "command": [str(SOLVER.resolve()), str(data_dir / case_id), "{attempt_root}/solver_output"],
        "cwd": str(data_dir),
        "max_wall_seconds": 1800,
        "cpu_threads": 4,
        "estimated_peak_gpu_mib": 16384,
        "estimated_storage_bytes": storage_estimate,
        "storage_estimate_basis": {
            "frames": frames,
            "actual_total_particles": total_particles,
            "lower_bound_bytes": raw_lower_bound,
            "planning_multiplier": 1.4,
            "root_cost_review_required": True,
        },
        "event_window_s": 4.0,
        "physical_case_id": physical_case_id,
        "physical_condition_hash": entry["physical_condition_hash"],
        "physical_geometry_control_hash": metadata["physical_condition"]["source_geometry_control_hash"],
        "numerical_recipe_hash": metadata["numerical_recipe_hash"],
        "recipe_id": metadata["numerical_recipe"]["recipe_id"],
        "scope_id": entry["scope_id"] if "scope_id" in entry else "F2_SCOPE_COMMENSURATE_CELLCENTER_V4",
        "mechanism_id": background,
        "resolution": "dp005",
        "registry_role": "same_COMM4_physical_mother_numerical_view; zero_new_independent_physical_cases",
        "new_independent_physical_case_count": 0,
        "gencase_receipt": str(receipt_path),
        "gencase_receipt_sha256": sha256(receipt_path),
        "gencase_prefix": str((data_dir / case_id).resolve()),
        "gencase_artifacts": {
            "generated_xml": {"path": str(generated_xml), "sha256": sha256(generated_xml)},
            "copied_bi4": {"path": str(bi4), "sha256": sha256(bi4)},
            "copied_motion": {"path": str(motion), "sha256": sha256(motion)},
            "consumed_gencase_receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path)},
        },
        "source_binding": {
            "source_definition_sha256": sha256(source_xml),
            "source_motion_sha256": sha256(source_motion),
            "definition_sha256": sha256(generated_xml),
            "bi4_sha256": sha256(bi4),
            "motion_sha256": sha256(motion),
            "physical_condition_hash": entry["physical_condition_hash"],
            "same_physical_mother_as": metadata["same_physical_mother_as"],
        },
        "numerical_recipe_fields": {
            "dp_m": metadata["dp_m"],
            "TimeMax": params["TimeMax"],
            "TimeOut": params["TimeOut"],
            "DtFixed": params.get("DtFixed"),
            "DtIni": params.get("DtIni"),
            "DtMin": params.get("DtMin"),
            "domain_repair": metadata["domain_repair"],
        },
        "quality_thresholds": quality_thresholds(background),
        "thresholds_apply_before_results": True,
        "input_files": [str(path.resolve()) for path in common],
        "input_sha256": input_binding(common),
        "gpu_launch": {"family_owner_launch": False, "requested_by": "primary_process"},
        "qualification_launch_authority": "shared_ds_data_02_runner_only_primary_process",
        "status": "candidate_macro_spatial_only_ready_after_root_cost_review",
        "qualification_claim": "none",
        "production_claim": "none",
        "request_note": "Actual DP005 GenCase input prefix is completed XML/BI4 directory. This .01-save candidate is for macro-spatial comparison only; it cannot satisfy the frozen event-time budget or Q-N without an independently reviewed .001-save run. No GPU is launched by this producer.",
    }
    write_json(request_path, request)
    return request


def build(manifest_path: Path, audit_report_path: Path, output_dir: Path) -> dict[str, Any]:
    global MANIFEST_DEFAULT, AUDIT_REPORT_DEFAULT
    MANIFEST_DEFAULT = require(manifest_path, "DP005 manifest")
    AUDIT_REPORT_DEFAULT = require(audit_report_path, "DP005 initial audit report")
    manifest = json.loads(MANIFEST_DEFAULT.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT_REPORT_DEFAULT.read_text(encoding="utf-8"))
    if audit.get("status") != "PASS_INITIAL_STRUCTURE":
        raise ValueError(f"DP005 audit is not PASS_INITIAL_STRUCTURE: {audit.get('status')}")
    by_case = {item["case_id"]: item for item in audit["cases"]}
    output_dir = output_dir.resolve()
    records = []
    for entry in manifest["cases"]:
        case_audit = by_case.get(entry["case_id"])
        if case_audit is None or case_audit.get("status") != "PASS_INITIAL_STRUCTURE":
            raise ValueError(f"missing passing audit case: {entry['case_id']}")
        request_path = output_dir / f"{entry['case_id']}_REPAIR01_MACRO_SAVE010_request.json"
        request = make_request(entry, case_audit, output_dir, request_path)
        records.append({"case_id": request["case_id"], "request_path": str(request_path), "request_sha256": sha256(request_path), "status": request["status"]})
    manifest_out = {
        "schema": "ds-data-02.f2.commensurate-dp005-solver-handoff.v1",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_manifest": {"path": str(MANIFEST_DEFAULT), "sha256": sha256(MANIFEST_DEFAULT)},
        "source_audit": {"path": str(AUDIT_REPORT_DEFAULT), "sha256": sha256(AUDIT_REPORT_DEFAULT)},
        "requests": records,
        "qualification_claim": "none; root cost review and event-cadence study remain required",
        "production_claim": "none",
        "gpu_launch": False,
        "timing_status": "current .01 candidates are macro-spatial only; .001 event reference is a separate future numerical recipe",
    }
    manifest_out_path = output_dir / "solver_handoff_manifest.json"
    write_json(manifest_out_path, manifest_out)
    return {"manifest": str(manifest_out_path), "manifest_sha256": sha256(manifest_out_path), "requests": records}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST_DEFAULT)
    parser.add_argument("--audit-report", type=Path, default=AUDIT_REPORT_DEFAULT)
    parser.add_argument("--output-dir", type=Path, default=FAMILY_ROOT / "commensurate_cellcenter_dp005_v2/solver_requests")
    args = parser.parse_args()
    print(json.dumps(build(args.manifest.resolve(), args.audit_report.resolve(), args.output_dir), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

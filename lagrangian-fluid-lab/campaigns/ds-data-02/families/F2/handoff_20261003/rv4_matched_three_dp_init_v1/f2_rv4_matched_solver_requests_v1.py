#!/usr/bin/env python3
"""Register root-only solver requests for the matched RV4 CPU parents.

The requests bind the actual terminal GenCase output directory, XML, BI4,
motion file, and receipt.  They are registration artifacts only: this module
never launches a solver or touches a GPU.  The materialised XMLs use
``TimeOut=.001`` for a four-second spatial/macro study.  The frozen event
allocation is recorded explicitly and remains pending because a .001 save
interval has a .0005 s half bracket, above the per-save .000146727816 s
allocation.  A .00025 event-capable recipe is recorded as a deferred option;
it is not silently substituted into these requests.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET


FAMILY_ID = "F2"
SCOPE_ID = "F2_SCOPE_RV4_MATCHED_THREE_DP_INIT_20261003"
SCHEMA = "ds-data-02.f2.rv4-matched-solver-request.v1"
HANDOFF_ROOT = Path(__file__).resolve().parent
ARTIFACT_ROOT = HANDOFF_ROOT / "artifacts"
OUTPUT_ROOT = HANDOFF_ROOT / "solver_requests_v1"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
STRICT_DISPATCH = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
CONTRACT_FILES = (
    Path(__file__).resolve(),
    RUNTIME_V2,
    STRICT_DISPATCH,
    HANDOFF_ROOT / "f2_rv4_matched_three_dp_init_v1.py",
    HANDOFF_ROOT / "f2_rv4_matched_initial_partvtk_audit_v1.py",
    HANDOFF_ROOT / "f2_rv4_matched_initial_evidence_summary_v1.py",
    ARTIFACT_ROOT / "rv4-matched-three-dp-init-manifest.json",
)

EVENT_TIME_BUDGET_S = 0.0036681953999691376
SAVE_TOTAL_BUDGET_S = 0.0007336390799938275
SAVE_ALLOCATION_S = 0.0001467278159987655
SPATIAL_SAVE_S = 0.001
SPATIAL_SAVE_HALF_BRACKET_S = SPATIAL_SAVE_S / 2.0
DEFERRED_EVENT_SAVE_S = 0.00025
FRAME_BYTES = 64
STORAGE_MARGIN = 1.5
WINDOW_S = 4.0
SPATIAL_FRAME_COUNT = 4001


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object: {path}")
    return value


def require(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def load_manifest() -> dict[str, Any]:
    manifest = read_json(ARTIFACT_ROOT / "rv4-matched-three-dp-init-manifest.json", "matched-mother manifest")
    if manifest.get("scope_id") != SCOPE_ID or len(manifest.get("cases", [])) != 4:
        raise ValueError("matched-mother manifest is not the four-case scope")
    return manifest


def discover_gencase(case_id: str) -> tuple[Path, dict[str, Any], Path]:
    roots = sorted((DATA_ROOT / "families" / "F2" / case_id).glob("gencase-*/execution-receipt.json"))
    if len(roots) != 1:
        raise ValueError(f"expected one terminal GenCase receipt for {case_id}, got {roots}")
    receipt_path = roots[0].resolve()
    receipt = read_json(receipt_path, "GenCase receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"GenCase is not terminal-successful for {case_id}")
    if receipt.get("solver_dimension_from_gencase") != 3:
        raise ValueError(f"GenCase is not 3D for {case_id}")
    if not isinstance(receipt.get("total_particles"), int) or not isinstance(receipt.get("fluid_particles"), int):
        raise ValueError(f"GenCase receipt lacks actual particle counts for {case_id}")
    output_root = Path(str(receipt.get("output_root", ""))).resolve()
    if not output_root.is_dir():
        raise ValueError(f"GenCase output directory missing for {case_id}: {output_root}")
    prefix = output_root / case_id
    for suffix in (".xml", ".bi4", "_motion.dat"):
        require(prefix.with_name(prefix.name + suffix), f"GenCase {suffix} for {case_id}")
    return receipt_path, receipt, prefix


def xml_parameters(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    definition = root.find(".//casedef/geometry/definition")
    parameters = root.findall(".//execution/parameters/parameter")
    if definition is None:
        raise ValueError(f"missing generated definition: {xml_path}")
    values = {node.attrib.get("key", ""): node.attrib.get("value", "") for node in parameters}
    time_max = float(values.get("TimeMax", "nan"))
    time_out = float(values.get("TimeOut", "nan"))
    if abs(time_max - WINDOW_S) > 1e-12 or abs(time_out - SPATIAL_SAVE_S) > 1e-12:
        raise ValueError(f"generated XML does not contain the frozen spatial recipe: {xml_path}: {values}")
    return {"dp_m": float(definition.attrib["dp"]), "time_max_s": time_max, "time_out_s": time_out, "parameters": values}


def file_bindings(paths: list[Path]) -> tuple[list[str], dict[str, str]]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        path = require(path, "solver request input")
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return [str(path) for path in unique], {str(path): sha256(path) for path in unique}


def storage_estimate(total_particles: int) -> int:
    return int(math.ceil(total_particles * SPATIAL_FRAME_COUNT * FRAME_BYTES * STORAGE_MARGIN))


def make_request(manifest_case: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(manifest_case["case_id"])
    metadata_path = require(Path(str(manifest_case["metadata"]["path"])), "matched case metadata")
    metadata = read_json(metadata_path, "matched case metadata")
    receipt_path, receipt, prefix = discover_gencase(case_id)
    xml = require(prefix.with_name(prefix.name + ".xml"), "generated XML")
    bi4 = require(prefix.with_name(prefix.name + ".bi4"), "generated BI4")
    motion = require(prefix.with_name(prefix.name + "_motion.dat"), "generated motion")
    params = xml_parameters(xml)
    total_particles = int(receipt["total_particles"])
    fluid_particles = int(receipt["fluid_particles"])
    recipe_name = f"SPATIAL_SAVE001_EVENT_PENDING_{case_id}"
    request_case_id = f"{case_id}_SPATIAL_SAVE001"
    attempt_id = f"qualification-{case_id.lower()}-spatial-save001-root-review-001"
    output_prefix = str(prefix)
    input_paths, input_hashes = file_bindings([
        *CONTRACT_FILES,
        metadata_path,
        receipt_path,
        xml,
        bi4,
        motion,
        SOLVER,
        HANDOFF_ROOT / "artifacts/rv4-matched-initial-evidence-summary-v1.json",
    ])
    gencase_binding = {
        "receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path)},
        "prefix": output_prefix,
        "xml": {"path": str(xml), "sha256": sha256(xml)},
        "bi4": {"path": str(bi4), "sha256": sha256(bi4)},
        "motion": {"path": str(motion), "sha256": sha256(motion)},
        "actual_total_particles": total_particles,
        "actual_fluid_particles": fluid_particles,
        "actual_solver_dimension": receipt["solver_dimension_from_gencase"],
    }
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY_ID,
        "case_id": request_case_id,
        "physical_case_id": metadata["physical_case_id"],
        "mechanism_id": metadata["mechanism_id"],
        "attempt_id": attempt_id,
        "kind": "qualification",
        "cpu_threads": 4,
        "max_wall_seconds": 1800 if metadata["resolution"] == "COARSE" else 2400,
        "estimated_peak_gpu_mib": 4096 if metadata["resolution"] == "COARSE" else 8192,
        "estimated_storage_bytes": storage_estimate(total_particles),
        "command": [str(SOLVER), output_prefix, "{attempt_root}/solver_output"],
        "cwd": str(prefix.parent),
        "raw_output_root": str((DATA_ROOT / "families" / "F2" / request_case_id).resolve()),
        "worktree_root": str(Path(__file__).resolve().parents[7]),
        "gencase_prefix": output_prefix,
        "gencase_receipt": str(receipt_path),
        "gencase_receipt_sha256": sha256(receipt_path),
        "gencase_artifacts": gencase_binding,
        "input_files": input_paths,
        "input_sha256": input_hashes,
        "physical_condition_hash": metadata["rv4_binding"]["physical_condition_hash"],
        "physical_geometry_control_hash": metadata["rv4_binding"]["physical_condition_hash"],
        "numerical_recipe_hash": metadata["numerical_recipe_hash"],
        "numerical_recipe_fields": {
            "dp_m": params["dp_m"],
            "time_max_s": params["time_max_s"],
            "time_out_s": params["time_out_s"],
            "frame_count_expected": SPATIAL_FRAME_COUNT,
            "recipe_role": "spatial_macro_reference_only_until_event_save_review",
        },
        "event_window_s": WINDOW_S,
        "quality_thresholds": {
            "event_time_absolute_budget_s": EVENT_TIME_BUDGET_S,
            "save_integration_total_budget_s": SAVE_TOTAL_BUDGET_S,
            "save_allocation_s": SAVE_ALLOCATION_S,
            "macro_relative_error_threshold": 0.01,
            "thresholds_apply_before_results": True,
        },
        "save_strategy_review": {
            "registered_save_interval_s": SPATIAL_SAVE_S,
            "registered_half_bracket_s": SPATIAL_SAVE_HALF_BRACKET_S,
            "per_save_allocation_s": SAVE_ALLOCATION_S,
            "registered_recipe_event_qualification": "deferred",
            "registered_recipe_spatial_role": "candidate spatial/macro evidence only",
            "reason": "0.001 s half bracket exceeds the frozen per-save allocation; no event pass is claimed",
            "deferred_event_recipe": {
                "save_interval_s": DEFERRED_EVENT_SAVE_S,
                "frame_count_full_window": int(round(WINDOW_S / DEFERRED_EVENT_SAVE_S)) + 1,
                "status": "cost_review_only; XML/solver request not materialized",
                "requires": ["additive XML TimeOut=.00025", "root storage/wall review", "actual realized timestamps"],
            },
            "coarse_dense_chord_option": "Any coarse-vs-dense spatial comparison must report measured interval widths and cannot override the frozen event budget.",
        },
        "gpu_launch": {"family_owner_launch": False, "requested_by": "primary_process", "root_review_required": True},
        "root_only": True,
        "solver_launch_forbidden": False,
        "qualification_claim": "none; root-only spatial reference request pending review",
        "q_i_status": "pending solver trajectory and full typed lifecycle evidence",
        "q_n_status": "not_assessed",
        "production_claim": "none",
        "new_independent_physical_case_count": 0,
        "registry_role": "matched RV4 numeric reference outside original 48 registry; same physical mother",
        "request_note": "Do not launch from this worktree. Root must review exact gencase_prefix/receipt binding, storage estimate, and event-save allocation before dispatch.",
    }


def build(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    manifest = load_manifest()
    output_root = Path(output_root).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"output directory must be fresh: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in manifest["cases"]:
        request = make_request(item, manifest)
        path = output_root / f"{request['case_id']}_request.json"
        path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        rows.append({"case_id": request["case_id"], "path": str(path), "sha256": sha256(path), "gencase_receipt": request["gencase_receipt"], "gencase_receipt_sha256": request["gencase_receipt_sha256"], "estimated_storage_bytes": request["estimated_storage_bytes"]})
    budget = {
        "schema": "ds-data-02.f2.rv4-matched-save-budget-review.v1",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope_id": SCOPE_ID,
        "event_time_absolute_budget_s": EVENT_TIME_BUDGET_S,
        "save_integration_total_budget_s": SAVE_TOTAL_BUDGET_S,
        "save_per_study_allocation_s": SAVE_ALLOCATION_S,
        "registered_spatial_save_interval_s": SPATIAL_SAVE_S,
        "registered_spatial_half_bracket_s": SPATIAL_SAVE_HALF_BRACKET_S,
        "registered_spatial_recipe_event_status": "deferred",
        "deferred_event_save_interval_s": DEFERRED_EVENT_SAVE_S,
        "deferred_event_save_frame_count": int(round(WINDOW_S / DEFERRED_EVENT_SAVE_S)) + 1,
        "decision": "Root must choose event-capable cadence after reviewing measured coarse/dense chord interval widths; no cadence is allowed to relax the frozen hard gate.",
        "requests": rows,
        "q_n_status": "not_assessed",
        "production_status": "not_evaluated",
    }
    budget_path = output_root / "save-budget-review-v1.json"
    budget_path.write_text(json.dumps(budget, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "root_review_only_requests_registered", "request_count": len(rows), "output_root": str(output_root), "budget": str(budget_path), "requests": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    result = build(args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

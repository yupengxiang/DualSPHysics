#!/usr/bin/env python3
"""Register additive .01 s spatial-reference requests for matched RV4.

The already-registered ``.001`` requests are retained as high-cadence
spatial/macro candidates.  This module creates a separate solver-input copy
whose only XML execution change is ``TimeOut=.01``.  The physical mother,
initial BI4, motion bytes, four-second window, and source GenCase receipt are
bound explicitly.  It only materialises input copies and JSON requests; the
root process owns solver launch and GPU scheduling.

The .01 s cadence has a .005 s half bracket and therefore cannot satisfy the
frozen per-study event allocation (0.0001467278159987655 s).  These requests
are spatial/macro references only.  The event-capable .00025 s candidate stays
deferred and is not substituted here.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from typing import Any, Mapping
import xml.etree.ElementTree as ET


FAMILY_ID = "F2"
SCOPE_ID = "F2_SCOPE_RV4_MATCHED_THREE_DP_INIT_20261003"
SCHEMA = "ds-data-02.f2.rv4-matched-spatial-reference-request.v1"
HANDOFF_ROOT = Path(__file__).resolve().parent
ARTIFACT_ROOT = HANDOFF_ROOT / "artifacts"
OUTPUT_ROOT = HANDOFF_ROOT / "solver_requests_spatial_reference_v1"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INPUT_ROOT = DATA_ROOT / "families" / "F2" / "F2_RV4EQ_MATCHED_SPATIAL_REFERENCE_INPUTS_20261003"
INTEGRATION_LAB = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab"
)
SOLVER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
)
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
STRICT_DISPATCH = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
BASE_GENERATOR = HANDOFF_ROOT / "f2_rv4_matched_solver_requests_v1.py"
CONTRACT_FILES = (
    Path(__file__).resolve(),
    BASE_GENERATOR,
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
SOURCE_SAVE_S = 0.001
SPATIAL_SAVE_S = 0.01
SPATIAL_SAVE_HALF_BRACKET_S = SPATIAL_SAVE_S / 2.0
DEFERRED_EVENT_SAVE_S = 0.00025
FRAME_BYTES = 64
STORAGE_MARGIN = 1.5
WINDOW_S = 4.0
SPATIAL_FRAME_COUNT = 401


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


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


def xml_parameter_values(xml_path: Path) -> dict[str, str]:
    root = ET.parse(xml_path).getroot()
    definition = root.find(".//casedef/geometry/definition")
    parameters = root.findall(".//execution/parameters/parameter")
    if definition is None:
        raise ValueError(f"missing generated definition: {xml_path}")
    values = {node.attrib.get("key", ""): node.attrib.get("value", "") for node in parameters}
    if abs(float(values.get("TimeMax", "nan")) - WINDOW_S) > 1e-12:
        raise ValueError(f"generated XML has the wrong window: {xml_path}")
    return {"dp_m": definition.attrib["dp"], **values}


def derive_xml(source_xml: Path, target_xml: Path) -> dict[str, Any]:
    """Copy source XML changing exactly the TimeOut value."""
    source_text = source_xml.read_text(encoding="utf-8")
    matches = list(re.finditer(r'(<parameter key="TimeOut" value=")([^"]+)("\s*/>)', source_text))
    if len(matches) != 1:
        raise ValueError(f"expected one TimeOut parameter in {source_xml}, found {len(matches)}")
    source_value = matches[0].group(2)
    if abs(float(source_value) - SOURCE_SAVE_S) > 1e-12:
        raise ValueError(f"source XML is not the consumed .001 recipe: {source_xml}: {source_value}")
    derived_text = source_text[: matches[0].start(2)] + f"{SPATIAL_SAVE_S:g}" + source_text[matches[0].end(2) :]
    target_xml.parent.mkdir(parents=True, exist_ok=True)
    if target_xml.exists():
        if target_xml.read_text(encoding="utf-8") != derived_text:
            raise ValueError(f"existing derived XML differs: {target_xml}")
    else:
        target_xml.write_text(derived_text, encoding="utf-8")
    derived_values = xml_parameter_values(target_xml)
    if abs(float(derived_values["TimeOut"]) - SPATIAL_SAVE_S) > 1e-12:
        raise ValueError(f"derived XML did not receive .01 TimeOut: {target_xml}")
    return {
        "source_xml": str(source_xml),
        "source_xml_sha256": sha256(source_xml),
        "derived_xml": str(target_xml),
        "derived_xml_sha256": sha256(target_xml),
        "changed_execution_parameter": "TimeOut",
        "source_time_out_s": float(source_value),
        "derived_time_out_s": float(derived_values["TimeOut"]),
    }


def copy_immutable(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256(source) != sha256(target):
            raise ValueError(f"existing derived input differs: {target}")
        return
    shutil.copy2(source, target)


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


def make_derived_inputs(case_id: str, source_prefix: Path) -> tuple[Path, dict[str, Any]]:
    source_xml = require(source_prefix.with_name(source_prefix.name + ".xml"), "source GenCase XML")
    source_bi4 = require(source_prefix.with_name(source_prefix.name + ".bi4"), "source GenCase BI4")
    source_motion = require(source_prefix.with_name(source_prefix.name + "_motion.dat"), "source motion")
    target_dir = INPUT_ROOT / case_id
    target_prefix = target_dir / f"{case_id}_SPATIAL_REFERENCE_SAVE010"
    derived_xml = target_prefix.with_name(target_prefix.name + ".xml")
    derived_bi4 = target_prefix.with_name(target_prefix.name + ".bi4")
    derived_motion = target_dir / source_motion.name
    xml_binding = derive_xml(source_xml, derived_xml)
    copy_immutable(source_bi4, derived_bi4)
    copy_immutable(source_motion, derived_motion)
    values = xml_parameter_values(derived_xml)
    if abs(float(values["TimeOut"]) - SPATIAL_SAVE_S) > 1e-12:
        raise ValueError(f"derived input cadence mismatch: {derived_xml}")
    return target_prefix, {
        **xml_binding,
        "source_bi4": str(source_bi4),
        "source_bi4_sha256": sha256(source_bi4),
        "derived_bi4": str(derived_bi4),
        "derived_bi4_sha256": sha256(derived_bi4),
        "source_motion": str(source_motion),
        "source_motion_sha256": sha256(source_motion),
        "derived_motion": str(derived_motion),
        "derived_motion_sha256": sha256(derived_motion),
        "derived_prefix": str(target_prefix),
        "physical_input_change": "none; only solver TimeOut changed in additive XML",
    }


def make_request(manifest_case: Mapping[str, Any], manifest: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    case_id = str(manifest_case["case_id"])
    metadata_path = require(Path(str(manifest_case["metadata"]["path"])), "matched case metadata")
    metadata = read_json(metadata_path, "matched case metadata")
    receipt_path, receipt, source_prefix = discover_gencase(case_id)
    derived_prefix, derived = make_derived_inputs(case_id, source_prefix)
    derived_xml = require(derived_prefix.with_name(derived_prefix.name + ".xml"), "derived XML")
    derived_bi4 = require(derived_prefix.with_name(derived_prefix.name + ".bi4"), "derived BI4")
    derived_motion = require(Path(derived["derived_motion"]), "derived motion")
    params = xml_parameter_values(derived_xml)
    total_particles = int(receipt["total_particles"])
    fluid_particles = int(receipt["fluid_particles"])
    numerical_fields = {
        "dp_m": float(params["dp_m"]),
        "time_max_s": float(params["TimeMax"]),
        "time_out_s": float(params["TimeOut"]),
        "frame_count_expected": SPATIAL_FRAME_COUNT,
        "source_time_out_s": SOURCE_SAVE_S,
        "recipe_role": "spatial_macro_reference_only; same cadence as existing fine baseline",
    }
    input_paths, input_hashes = file_bindings([
        *CONTRACT_FILES,
        metadata_path,
        receipt_path,
        source_prefix.with_name(source_prefix.name + ".xml"),
        source_prefix.with_name(source_prefix.name + ".bi4"),
        source_prefix.with_name(source_prefix.name + "_motion.dat"),
        derived_xml,
        derived_bi4,
        derived_motion,
        SOLVER,
        ARTIFACT_ROOT / "rv4-matched-initial-evidence-summary-v1.json",
    ])
    gencase_binding = {
        "source_receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path)},
        "source_prefix": str(source_prefix),
        "source_xml": {"path": derived["source_xml"], "sha256": derived["source_xml_sha256"]},
        "source_bi4": {"path": derived["source_bi4"], "sha256": derived["source_bi4_sha256"]},
        "source_motion": {"path": derived["source_motion"], "sha256": derived["source_motion_sha256"]},
        "actual_total_particles": total_particles,
        "actual_fluid_particles": fluid_particles,
        "actual_solver_dimension": receipt["solver_dimension_from_gencase"],
    }
    request_case_id = f"{case_id}_SPATIAL_REFERENCE_SAVE010"
    numerical_hash = canonical_sha(numerical_fields)
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY_ID,
        "case_id": request_case_id,
        "physical_case_id": metadata["physical_case_id"],
        "mechanism_id": metadata["mechanism_id"],
        "attempt_id": f"qualification-{case_id.lower()}-spatial-reference-save010-root-review-001",
        "kind": "qualification",
        "cpu_threads": 4,
        "max_wall_seconds": 1200 if metadata["resolution"] == "COARSE" else 1800,
        "estimated_peak_gpu_mib": 4096 if metadata["resolution"] == "COARSE" else 8192,
        "estimated_storage_bytes": storage_estimate(total_particles),
        "command": [str(SOLVER), str(derived_prefix), "{attempt_root}/solver_output"],
        "cwd": str(derived_prefix.parent),
        "raw_output_root": str((DATA_ROOT / "families" / "F2" / request_case_id).resolve()),
        "worktree_root": str(Path(__file__).resolve().parents[7]),
        "gencase_prefix": str(derived_prefix),
        "gencase_receipt": str(receipt_path),
        "gencase_receipt_sha256": sha256(receipt_path),
        "gencase_artifacts": gencase_binding,
        "derived_solver_inputs": derived,
        "input_files": input_paths,
        "input_sha256": input_hashes,
        "physical_condition_hash": metadata["rv4_binding"]["physical_condition_hash"],
        "physical_geometry_control_hash": metadata["rv4_binding"]["physical_condition_hash"],
        "numerical_recipe_hash": numerical_hash,
        "source_numerical_recipe_hash": metadata["numerical_recipe_hash"],
        "numerical_recipe_fields": numerical_fields,
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
            "registered_recipe_spatial_role": "spatial/macro reference at existing fine baseline cadence",
            "reason": "0.01 s is suitable for spatial/macro comparison but its .005 s half bracket exceeds the frozen event allocation; no event pass is claimed",
            "deferred_event_recipe": {
                "save_interval_s": DEFERRED_EVENT_SAVE_S,
                "frame_count_full_window": int(round(WINDOW_S / DEFERRED_EVENT_SAVE_S)) + 1,
                "status": "cost_review_only; XML/solver request not materialized",
                "requires": ["additive XML TimeOut=.00025", "root storage/wall review", "actual realized timestamps"],
            },
            "coarse_dense_chord_option": "Report measured interval widths; a spatial chord comparison cannot override the frozen event budget.",
        },
        "gpu_launch": {"family_owner_launch": False, "requested_by": "primary_process", "root_review_required": True},
        "root_only": True,
        "solver_launch_forbidden": False,
        "qualification_claim": "none; root-only .01 s spatial reference request pending review",
        "q_i_status": "pending solver trajectory and full typed lifecycle evidence",
        "q_n_status": "not_assessed",
        "production_claim": "none",
        "new_independent_physical_case_count": 0,
        "registry_role": "same matched RV4 physical mother; additive .01 s spatial reference",
        "request_note": "Do not launch from this worktree. Root must review derived-input hashes, storage estimate, and event-save allocation before dispatch.",
    }
    return request, {"case_id": case_id, "derived": derived, "request_case_id": request_case_id}


def build(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    manifest = load_manifest()
    output_root = Path(output_root).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"output directory must be fresh: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    rows = []
    derived_rows = []
    for item in manifest["cases"]:
        request, derived_row = make_request(item, manifest)
        path = output_root / f"{request['case_id']}_request.json"
        path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        rows.append({
            "case_id": request["case_id"],
            "path": str(path),
            "sha256": sha256(path),
            "gencase_receipt": request["gencase_receipt"],
            "gencase_receipt_sha256": request["gencase_receipt_sha256"],
            "estimated_storage_bytes": request["estimated_storage_bytes"],
            "estimated_storage_gib": request["estimated_storage_bytes"] / (1024**3),
        })
        derived_rows.append(derived_row)
    budget = {
        "schema": "ds-data-02.f2.rv4-matched-spatial-reference-save-budget-review.v1",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope_id": SCOPE_ID,
        "event_time_absolute_budget_s": EVENT_TIME_BUDGET_S,
        "save_integration_total_budget_s": SAVE_TOTAL_BUDGET_S,
        "save_per_study_allocation_s": SAVE_ALLOCATION_S,
        "registered_spatial_save_interval_s": SPATIAL_SAVE_S,
        "registered_spatial_half_bracket_s": SPATIAL_SAVE_HALF_BRACKET_S,
        "registered_spatial_recipe_event_status": "deferred",
        "spatial_role": "same four-second .01 s cadence as existing fine baseline spatial/macro reference",
        "deferred_event_save_interval_s": DEFERRED_EVENT_SAVE_S,
        "deferred_event_save_frame_count": int(round(WINDOW_S / DEFERRED_EVENT_SAVE_S)) + 1,
        "decision": "No event qualification is claimed. Root must review measured coarse/dense chord interval widths and the frozen event allocation separately.",
        "requests": rows,
        "derived_inputs": derived_rows,
        "q_n_status": "not_assessed",
        "production_status": "not_evaluated",
    }
    budget_path = output_root / "save-budget-review-v1.json"
    budget_path.write_text(json.dumps(budget, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "root_review_only_spatial_reference_requests_registered", "request_count": len(rows), "output_root": str(output_root), "budget": str(budget_path), "requests": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(build(args.output_root), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

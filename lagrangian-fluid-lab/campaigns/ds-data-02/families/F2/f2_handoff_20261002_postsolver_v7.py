#!/usr/bin/env python3
"""Prepare additive F2 direct-conversion and temporal-study handoffs.

This module only reads completed solver/GenCase evidence and writes versioned
request/manifest JSON.  It never starts a solver, converter, or label job.
The request uses the official full-frame ``PartVTK_linux64`` executable;
``PartVTKOut_linux64`` is deliberately excluded because it is the native
exclusion accounting tool rather than a full-frame decoder.

The temporal manifest compares the actual Run.csv/RunPARTs.csv records before
any trajectory labels exist.  It records the realized save interval and
integration-step ratios, so a fixed-step candidate is not called an exact
half-step study merely from its name or requested XML value.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET


F2_ROOT = Path(__file__).resolve().parent
WORKTREE_ROOT = F2_ROOT.parents[4]
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA_ROOT = DATA_ROOT / "families/F2"
DIRECT_CONVERTER = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
PYTHON = WORKTREE_ROOT / "lagrangian-fluid-lab/.venv/bin/python"
V6_SCRIPT = F2_ROOT / "f2_handoff_20261002_v6_labels.py"
V6_OPERATOR = F2_ROOT / "f2_handoff_20261002_event_semantics_v6.py"
V6_MANIFEST = F2_ROOT / "handoff_20261002/event_semantics_v6/operator_manifest.json"
QUALITY_CONTRACT = F2_ROOT / "quality_contract.json"
EVENT_DEFINITIONS = F2_ROOT / "event_definitions.json"
SAVE_PLAN = F2_ROOT / "integration_save_plan.json"
CASE_REGISTRY = F2_ROOT / "case_registry.jsonl"
REFERENCE_MATRIX = F2_ROOT / "definitions/reference_matrix.json"
GOAL = F2_ROOT.parents[1] / "GOAL_ZH.md"
DP005_MANIFEST = F2_ROOT / "commensurate_cellcenter_dp005_v2/manifest.json"
DP005_AUDIT = F2_DATA_ROOT / "F2_COMM4_DP005_REPAIR01_INITIAL_AUDIT_V2/audit-f2-comm4-dp005-repair01-v2/report/commensurate-cellcenter-audit.json"

BASELINE_REQUEST_DIR = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001"
TEMPORAL_REQUEST_DIR = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261002/root_temporal_launch_002"
TEMPORAL_EQUIVALENCE = TEMPORAL_REQUEST_DIR / "equivalence_manifest.json"
OWNER_DIR = F2_ROOT / "handoff_20261002/postsolver/owner_metadata"
OUTPUT_DIR = F2_ROOT / "handoff_20261002/postsolver_v7"
OWNER_OUTPUT_DIR = OUTPUT_DIR / "owner_metadata"
CENTER_MEDIUM_AUDIT = OUTPUT_DIR / "center_medium_actual_audit.json"
CENTER_MEDIUM_CASE_ROOT = F2_DATA_ROOT / "F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001"
CENTER_MEDIUM_SOLVER_RECEIPT = CENTER_MEDIUM_CASE_ROOT / "qualification-f2h10v2_center_v1_medium_rv4d1_baseline_save001-native-fullstate-v1/execution-receipt.json"
CENTER_MEDIUM_SOLVER_OUT = CENTER_MEDIUM_SOLVER_RECEIPT.parent / "solver_output"
GENCASE_RECEIPT = F2_DATA_ROOT / "F2H10V2_CENTER_V1_MEDIUM/gencase-f2-f2h10v2-center-medium-20261002-002/execution-receipt.json"

# Completed CENTER coarse conversion used as a measured direct-conversion
# reference.  The estimate is deliberately particle-frame based, rather than
# a fixed 1200-second guess.
REFERENCE_CONVERSION = {
    "total_particles": 28_647,
    "frames": 4_001,
    "elapsed_seconds": 191.78278693789616,
    "trajectory_bytes": 619_911_672,
    "case_id": "F2H10V2_CENTER_V1_COARSE_RV4D1_BASELINE_SAVE001",
    "conversion_attempt": "conversion-f2h10v2_center_v1_coarse_rv4d1_baseline_save001-fullstate-v5-002",
}
REFERENCE_TRAJECTORY = F2_DATA_ROOT / REFERENCE_CONVERSION["case_id"] / REFERENCE_CONVERSION["conversion_attempt"] / "trajectory.h5"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path, label: str = "file") -> Path:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def require_dir(path: Path, label: str = "directory") -> Path:
    path = path.resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def load_json(path: Path, label: str = "JSON") -> dict[str, Any]:
    path = require_file(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def binding(paths: Iterable[Path]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for path in paths:
        path = require_file(path)
        result[str(path)] = {"path": str(path), "sha256": sha256(path)}
    return result


def input_sha256(paths: Iterable[Path]) -> dict[str, str]:
    return {path: item["sha256"] for path, item in binding(paths).items()}


def request_case_id(path: Path) -> str:
    request = load_json(path, "solver request")
    return str(request["case_id"])


def expected_solver_receipt(request_path: Path) -> Path:
    request = load_json(request_path, "solver request")
    return F2_DATA_ROOT / str(request["case_id"]) / str(request["attempt_id"]) / "execution-receipt.json"


def completed_solver(request_path: Path) -> tuple[Path, dict[str, Any]]:
    request = load_json(request_path, "solver request")
    receipt_path = expected_solver_receipt(request_path)
    receipt = load_json(receipt_path, "solver receipt")
    if receipt.get("status") not in {"completed", "success"} or receipt.get("returncode", receipt.get("exit_code")) != 0:
        raise ValueError(f"solver receipt is not completed code 0: {receipt_path}")
    return receipt_path, receipt


def solver_output(receipt: Mapping[str, Any]) -> tuple[Path, Path]:
    root = require_dir(Path(str(receipt["output_root"])), "solver output root")
    out = root / "solver_output"
    if not out.is_dir():
        out = root
    data = require_dir(out / "data", "native Part data")
    return out, data


def _strip_num(value: str) -> float:
    return float(value.replace(",", "").strip())


def read_run_summary(out: Path) -> dict[str, Any]:
    run_path = require_file(out / "Run.csv", "Run.csv")
    runparts_path = require_file(out / "RunPARTs.csv", "RunPARTs.csv")
    run_lines = [line for line in run_path.read_text(errors="replace").splitlines() if line]
    if len(run_lines) < 2:
        raise ValueError(f"Run.csv has no data row: {run_path}")
    run_row = next(csv.DictReader([run_lines[0].lstrip("#")] + [run_lines[1]], delimiter=";"))
    rp_lines = [line for line in runparts_path.read_text(errors="replace").splitlines() if line]
    if not rp_lines:
        raise ValueError(f"RunPARTs.csv is empty: {runparts_path}")
    rp_rows = list(csv.DictReader([rp_lines[0].lstrip("#")] + [line for line in rp_lines[1:] if not line.startswith("#")], delimiter=";"))
    if not rp_rows:
        raise ValueError(f"RunPARTs.csv has no data rows: {runparts_path}")

    def values(field: str) -> list[float]:
        return [_strip_num(row[field]) for row in rp_rows if field in row and row[field] not in (None, "")]

    dt_min = [value for value in values("DtMin [s]") if value > 0.0]
    dt_max = [value for value in values("DtMax [s]") if value > 0.0]
    save_times = values("TimeStep [s]")
    save_intervals = [b - a for a, b in zip(save_times, save_times[1:]) if b > a]
    np_out = values("NpOut")
    part_files = int(_strip_num(run_row["PartFiles"]))
    parts_out = int(_strip_num(run_row["PartsOut"]))
    steps = int(_strip_num(run_row["Steps"]))
    return {
        "run_csv": str(run_path),
        "runparts_csv": str(runparts_path),
        "particle_count": int(_strip_num(run_row["Np"])),
        "physical_time_s": float(run_row["PhysicalTime"]),
        "part_files": part_files,
        "parts_out": parts_out,
        "steps": steps,
        "dp_m": float(run_row["Dp"]),
        "runparts_rows": len(rp_rows),
        "np_out_sum": float(sum(np_out)),
        "dt_min_s": {"min": min(dt_min), "max": max(dt_min), "median": _median(dt_min)},
        "dt_max_s": {"min": min(dt_max), "max": max(dt_max), "median": _median(dt_max)},
        "save_interval_s": {"min": min(save_intervals), "max": max(save_intervals), "median": _median(save_intervals)},
    }


def _median(values: list[float]) -> float:
    if not values:
        raise ValueError("cannot calculate median of empty values")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def xml_parameters(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {
        str(item.get("key")): str(item.get("value"))
        for item in root.findall(".//execution/parameters/parameter")
        if item.get("key") is not None
    }


def _xml_tuple(element: ET.Element, allowed_parameter_changes: set[str]) -> tuple[Any, ...]:
    attrs = dict(element.attrib)
    if element.tag == "parameter" and attrs.get("key") in allowed_parameter_changes:
        attrs["value"] = "<allowed-change>"
    text = (element.text or "").strip()
    return (
        element.tag,
        tuple(sorted(attrs.items())),
        text,
        tuple(_xml_tuple(child, allowed_parameter_changes) for child in element),
    )


def xml_semantic_equality(baseline: Path, variant: Path) -> dict[str, Any]:
    base_root = ET.parse(baseline).getroot()
    variant_root = ET.parse(variant).getroot()
    allowed = {"TimeOut", "DtFixed"}
    base_params = xml_parameters(baseline)
    variant_params = xml_parameters(variant)
    changed = {
        key: {"baseline": base_params.get(key), "variant": variant_params.get(key)}
        for key in sorted(set(base_params) | set(variant_params))
        if base_params.get(key) != variant_params.get(key)
    }
    normalized_equal = _xml_tuple(base_root, allowed) == _xml_tuple(variant_root, allowed)
    unexpected = sorted(set(changed) - allowed)
    return {
        "baseline": {"path": str(baseline), "sha256": sha256(baseline)},
        "variant": {"path": str(variant), "sha256": sha256(variant)},
        "allowed_parameter_changes": sorted(allowed),
        "changed_execution_parameters": changed,
        "unexpected_parameter_changes": unexpected,
        "normalized_equal_after_allowed_changes": normalized_equal,
        "physical_xml_equivalent": normalized_equal and not unexpected,
    }


def _prefix_files(request: Mapping[str, Any]) -> tuple[Path, Path, Path]:
    prefix = require_file(Path(str(request["command"][1]) + ".xml"), "generated XML")
    bi4 = require_file(prefix.with_suffix(".bi4"), "GenCase BI4")
    motion_candidates = sorted(prefix.parent.glob("*_motion.dat"))
    if len(motion_candidates) != 1:
        raise ValueError(f"expected one motion file near {prefix}, got {motion_candidates}")
    return prefix, bi4, require_file(motion_candidates[0], "copied motion")


def actual_solver_record(request_path: Path) -> dict[str, Any]:
    request = load_json(request_path, "solver request")
    receipt_path, receipt = completed_solver(request_path)
    out, data = solver_output(receipt)
    frames = sorted(data.glob("Part_*.bi4"))
    if not frames:
        raise FileNotFoundError(f"no native Part files under {data}")
    prefix, bi4, motion = _prefix_files(request)
    source = request.get("source_binding", {})
    expected_hashes = {
        prefix: source.get("new_xml_sha256", source.get("definition_sha256")),
        bi4: source.get("bi4_sha256"),
        motion: source.get("control_sha256", source.get("motion_sha256")),
    }
    hash_checks = {}
    for path, expected in expected_hashes.items():
        actual = sha256(path)
        hash_checks[str(path)] = {"actual": actual, "expected": expected, "matches": expected in (None, actual)}
        if expected is not None and actual != expected:
            raise ValueError(f"source hash mismatch for {path}: {actual} != {expected}")
    summary = read_run_summary(out)
    if summary["part_files"] != len(frames):
        raise ValueError(f"Run.csv PartFiles disagrees with native files for {request_path}")
    return {
        "request_path": str(require_file(request_path, "solver request")),
        "request_sha256": sha256(request_path),
        "case_id": str(request["case_id"]),
        "attempt_id": str(request["attempt_id"]),
        "physical_case_id": request.get("physical_case_id"),
        "physical_condition_hash": request.get("physical_condition_hash"),
        "numerical_recipe_hash": request.get("numerical_recipe_hash"),
        "numerical_recipe_fields": request.get("numerical_recipe_fields", {}),
        "source_binding": request.get("source_binding", {}),
        "source_hash_checks": hash_checks,
        "solver_receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path)},
        "gencase_receipt": {"path": str(request["gencase_receipt"]), "sha256": sha256(Path(str(request["gencase_receipt"])))},
        "generated_xml": {"path": str(prefix), "sha256": sha256(prefix)},
        "bi4": {"path": str(bi4), "sha256": sha256(bi4)},
        "motion": {"path": str(motion), "sha256": sha256(motion)},
        "solver_output": str(out),
        "data_root": str(data),
        "native_frame_count": len(frames),
        "native_frame_samples": [str(frames[0]), str(frames[len(frames) // 2]), str(frames[-1])],
        "solver_elapsed_seconds": receipt.get("elapsed_seconds"),
        "summary": summary,
        "solver_status": receipt.get("status"),
        "returncode": receipt.get("returncode", receipt.get("exit_code")),
    }


def baseline_requests() -> dict[str, Path]:
    return {
        "center_catch": BASELINE_REQUEST_DIR / "F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001_request.json",
        "offset_spill": BASELINE_REQUEST_DIR / "F2H10V2_OFFSET_V1_MEDIUM_RV4D1_BASELINE_SAVE001_request.json",
    }


def temporal_requests() -> list[Path]:
    return sorted(TEMPORAL_REQUEST_DIR.glob("F2H10V2_*_MEDIUM_RV4D1_*_request.json"))


def owner_for_mechanism(mechanism: str) -> Path:
    prefix = "F2H10V2_CENTER_V1_MEDIUM" if mechanism == "center_catch" else "F2H10V2_OFFSET_V1_MEDIUM"
    return require_file(OWNER_DIR / f"{prefix}.generator.v2.metadata.json", "owner metadata")


def temporal_owner_metadata(record: Mapping[str, Any], output_dir: Path) -> Path:
    """Create a numerical-view owner sidecar without touching consumed metadata."""
    mechanism = "center_catch" if "CENTER" in str(record["case_id"]) else "offset_spill"
    source_owner = owner_for_mechanism(mechanism)
    owner = load_json(source_owner, "temporal owner metadata")
    xml = Path(str(record["generated_xml"]["path"]))
    motion = Path(str(record["motion"]["path"]))
    owner["case_id"] = str(record["case_id"])
    owner["definition"] = {"path": str(xml), "sha256": sha256(xml)}
    owner["motion"] = {"path": str(motion), "sha256": sha256(motion)}
    owner["solver_parameters"] = xml_parameters(xml)
    owner["numerical_recipe_hash_declared"] = str(record["numerical_recipe_hash"])
    owner["numerical_view"] = {
        "variant_case_id": str(record["case_id"]),
        "variant": record.get("numerical_recipe_fields", {}).get("variant"),
        "physical_condition_hash": record.get("physical_condition_hash"),
        "source_owner_metadata": {"path": str(source_owner), "sha256": sha256(source_owner)},
        "scope": "numerical parameters and save/integration recipe; physical_binding remains unchanged",
    }
    if isinstance(owner.get("event_window"), dict):
        owner["event_window"] = dict(owner["event_window"])
        owner["event_window"]["save_interval_s"] = record.get("numerical_recipe_fields", {}).get("save_interval_s")
    owner["schema"] = "ds-data-02.f2.gem-handoff-20261002.generator-v7-numerical-view"
    path = output_dir / "owner_metadata" / f"{record['case_id']}.generator.v7.metadata.json"
    write_json(path, owner)
    return path


def dp005_owner_metadata(solver_request: Mapping[str, Any], generated_xml: Path, motion: Path, source_metadata: Path, output_dir: Path) -> Path:
    """Add exact XML solver parameters to the legacy DP005 metadata sidecar."""
    owner = load_json(source_metadata, "DP005 source metadata")
    owner["schema"] = "ds-data-02.f2.commensurate-dp005-owner-v7"
    owner["case_id"] = str(solver_request["case_id"])
    owner["definition"] = {"path": str(generated_xml), "sha256": sha256(generated_xml)}
    owner["motion"] = {"path": str(motion), "sha256": sha256(motion)}
    owner["solver_parameters"] = xml_parameters(generated_xml)
    owner["numerical_recipe_hash_declared"] = str(solver_request.get("numerical_recipe_hash"))
    owner["physical_condition_hash_declared"] = solver_request.get("physical_condition_hash")
    owner["numerical_view"] = {
        "variant_case_id": str(solver_request["case_id"]),
        "physical_condition_hash": solver_request.get("physical_condition_hash"),
        "source_owner_metadata": {"path": str(source_metadata), "sha256": sha256(source_metadata)},
        "scope": "DP005 .01 macro-spatial numerical view; legacy physical scope is retained for audit and does not grant Q-I/Q-N",
    }
    path = output_dir / "owner_metadata" / f"{solver_request['case_id']}.generator.v7.metadata.json"
    write_json(path, owner)
    return path


def temporal_comparison(output_dir: Path) -> dict[str, Any]:
    baseline = {mechanism: actual_solver_record(path) for mechanism, path in baseline_requests().items()}
    variant_paths = temporal_requests()
    if len(variant_paths) != 3:
        raise ValueError(f"root_temporal_launch_002 must contain exactly three requests, found {variant_paths}")
    variants = [actual_solver_record(path) for path in variant_paths]
    pairs = []
    for variant in variants:
        mechanism = "center_catch" if "CENTER" in variant["case_id"] else "offset_spill"
        base = baseline[mechanism]
        base_xml = Path(base["generated_xml"]["path"])
        variant_xml = Path(variant["generated_xml"]["path"])
        xml_check = xml_semantic_equality(base_xml, variant_xml)
        base_motion = base["motion"]["sha256"]
        variant_motion = variant["motion"]["sha256"]
        base_bi4 = base["bi4"]["sha256"]
        variant_bi4 = variant["bi4"]["sha256"]
        base_summary = base["summary"]
        variant_summary = variant["summary"]
        dt_ratio_to_min = variant_summary["dt_min_s"]["median"] / base_summary["dt_min_s"]["min"]
        dt_ratio_to_median = variant_summary["dt_min_s"]["median"] / base_summary["dt_min_s"]["median"]
        save_ratio = variant_summary["save_interval_s"]["median"] / base_summary["save_interval_s"]["median"]
        pairs.append({
            "baseline_case_id": base["case_id"],
            "variant_case_id": variant["case_id"],
            "mechanism": mechanism,
            "physical_condition_hash_equal": base["physical_condition_hash"] == variant["physical_condition_hash"],
            "bi4_hash_equal": base_bi4 == variant_bi4,
            "motion_hash_equal": base_motion == variant_motion,
            "xml_check": xml_check,
            "actual_ratio_audit": {
                "baseline_frames": base["native_frame_count"],
                "variant_frames": variant["native_frame_count"],
                "save_interval_median_ratio": save_ratio,
                "baseline_dt_min_positive_min_s": base_summary["dt_min_s"]["min"],
                "baseline_dt_min_positive_median_s": base_summary["dt_min_s"]["median"],
                "variant_dt_min_median_s": variant_summary["dt_min_s"]["median"],
                "variant_dt_to_baseline_min_ratio": dt_ratio_to_min,
                "variant_dt_to_baseline_median_ratio": dt_ratio_to_median,
                "step_count_ratio": variant_summary["steps"] / base_summary["steps"],
                "physical_time_difference_s": variant_summary["physical_time_s"] - base_summary["physical_time_s"],
            },
            "native_output_accounting": {
                "baseline_parts_out": base_summary["parts_out"],
                "variant_parts_out": variant_summary["parts_out"],
                "baseline_np_out_sum": base_summary["np_out_sum"],
                "variant_np_out_sum": variant_summary["np_out_sum"],
            },
            "event_operator_status": "deferred_until_direct_conversion_and_v6_pose_labels",
        })
    manifest = {
        "schema": "ds-data-02.f2.temporal-comparison.v7",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope_id": "F2_SCOPE_GEM_COMMENSURATE_CELLCENTER_20261002_V2",
        "physical_window_s": [0.0, 4.0],
        "baseline_requests": baseline,
        "temporal_requests": variants,
        "equivalence_manifest": {"path": str(require_file(TEMPORAL_EQUIVALENCE)), "sha256": sha256(TEMPORAL_EQUIVALENCE)},
        "comparisons": pairs,
        "interpretation": {
            "physical_input_equality_required": True,
            "xml_allowed_changes": ["DtFixed", "TimeOut"],
            "exact_half_dt_claim": False,
            "exact_half_dt_reason": "The fixed-step candidates are compared with realized RunPARTs DtMin values; requested fixed values are independently recorded and do not establish a half-step ratio.",
            "event_timing_status": "pending direct conversion and v6 pose labels; .01 baseline is macro-spatial evidence only",
            "qn_status": "pending; this manifest is numerical evidence and does not grant Q-N",
        },
    }
    path = output_dir / "temporal_comparison_manifest.json"
    write_json(path, manifest)
    return {"path": str(path), "sha256": sha256(path), **manifest}


def estimate_conversion_resources(total_particles: int, frames: int) -> dict[str, Any]:
    if total_particles <= 0 or frames <= 0:
        raise ValueError("particle/frame counts must be positive")
    ratio = total_particles * frames / (REFERENCE_CONVERSION["total_particles"] * REFERENCE_CONVERSION["frames"])
    predicted_wall = REFERENCE_CONVERSION["elapsed_seconds"] * ratio
    predicted_h5 = REFERENCE_CONVERSION["trajectory_bytes"] * ratio
    # Keep a measured headroom factor while rounding to a reviewable GiB.  The
    # input solver tree is already charged separately; this is conversion
    # output/validation reservation, not a promise that raw BI4 disappears.
    storage = int(math.ceil(predicted_h5 * 2.5 / (1024**3)) * 1024**3)
    wall = int(math.ceil(predicted_wall * 1.35 / 60.0) * 60)
    return {
        "reference": {
            "case_id": REFERENCE_CONVERSION["case_id"],
            "total_particles": REFERENCE_CONVERSION["total_particles"],
            "frames": REFERENCE_CONVERSION["frames"],
            "elapsed_seconds": REFERENCE_CONVERSION["elapsed_seconds"],
            "trajectory_bytes": REFERENCE_CONVERSION["trajectory_bytes"],
            "trajectory_path": str(REFERENCE_TRAJECTORY),
        },
        "actual_total_particles": total_particles,
        "actual_frames": frames,
        "particle_frame_ratio": ratio,
        "predicted_wall_seconds": predicted_wall,
        "max_wall_seconds": max(300, wall),
        "predicted_trajectory_bytes": predicted_h5,
        "estimated_storage_bytes": storage,
        "planning_multiplier": 2.5,
        "wall_headroom_multiplier": 1.35,
        "basis": "measured CENTER coarse PartVTK_linux64 direct conversion, scaled by actual particle-frame count",
    }


def _v6_label_plan(*, case_id: str, conversion_attempt_root: Path, trajectory: Path, owner: Path, xml: Path, motion: Path, solver_receipt: Path, gencase_receipt: Path, numerical_hash: str, conversion_receipt: Path, conversion_report: Path) -> dict[str, Any]:
    output_root = conversion_attempt_root / "v6-pose-labels"
    command = [
        str(PYTHON), str(V6_SCRIPT), "run",
        "--source-trajectory", str(trajectory),
        "--augmented-trajectory", str(output_root / "trajectory-with-actual-pose.h5"),
        "--owner-metadata", str(owner),
        "--generated-xml", str(xml),
        "--motion-control", str(motion),
        "--run-out", str(Path(str(solver_receipt.parent / "solver_output")) / "Run.out"),
        "--conversion-report", str(conversion_report),
        "--solver-receipt", str(solver_receipt),
        "--gencase-receipt", str(gencase_receipt),
        "--conversion-receipt", str(conversion_receipt),
        "--numerical-recipe-hash", numerical_hash,
        "--case-id", case_id,
        "--output", str(output_root / "f2-v6-labels.h5"),
        "--report", str(output_root / "f2-v6-observations.json"),
        "--pose-report", str(output_root / "rigid-body-state.json"),
    ]
    return {
        "requires_conversion_terminal": True,
        "requires_actual_native_pose": True,
        "trajectory": str(trajectory),
        "owner_metadata": str(owner),
        "definition_override": str(xml),
        "motion_control": str(motion),
        "numerical_recipe_hash": numerical_hash,
        "case_id_override": case_id,
        "conversion_receipt": {"path": str(conversion_receipt)},
        "conversion_report": {"path": str(conversion_report)},
        "v6": command,
        "operator_hash": sha256(V6_MANIFEST),
        "status": "deferred_until_conversion_terminal",
        "qn_status": "pending",
    }


def center_medium_owner_metadata(output_dir: Path, report: Mapping[str, Any]) -> Path:
    """Freeze a baseline owner sidecar against the actual RV4 generated XML."""
    source_owner = owner_for_mechanism("center_catch")
    owner = load_json(source_owner, "CENTER medium owner metadata")
    xml = require_file(Path(str(report["source_provenance"]["generated_xml"]["path"])), "CENTER medium generated XML")
    motion = require_file(Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001/staged_inputs/F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001/F2H10V2_CENTER_V1_MEDIUM_motion.dat"), "CENTER medium motion control")
    physical_hash = str(report["hash_scopes"]["physical_condition_sha256"])
    numerical_hash = str(report["hash_scopes"]["numerical_parameters_sha256"])
    owner["schema"] = "ds-data-02.f2.gem-handoff-20261002.generator-v7-baseline"
    owner["case_id"] = "F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001"
    owner["definition"] = {"path": str(xml), "sha256": sha256(xml)}
    owner["motion"] = {"path": str(motion), "sha256": sha256(motion)}
    owner["solver_parameters"] = xml_parameters(xml)
    owner["physical_condition_hash_declared"] = physical_hash
    owner["numerical_recipe_hash_declared"] = numerical_hash
    owner["numerical_view"] = {
        "variant_case_id": owner["case_id"],
        "variant": "RV4D1_BASELINE_SAVE001",
        "physical_condition_hash": physical_hash,
        "source_owner_metadata": {"path": str(source_owner), "sha256": sha256(source_owner)},
        "scope": "RV4 repaired-domain baseline; exact physical/control binding is retained and numerical recipe is separate",
    }
    path = output_dir / "owner_metadata" / f"{owner['case_id']}.generator.v7.metadata.json"
    write_json(path, owner)
    return path


def build_center_medium_v6_label_request(output_dir: Path) -> Path:
    """Register a labels request for the completed CENTER medium H5.

    This request is intentionally additive and remains pending for the shared
    CPU runner.  It is not a conversion or solver request.
    """
    audit_path = require_file(CENTER_MEDIUM_AUDIT, "CENTER medium actual audit")
    audit = load_json(audit_path, "CENTER medium actual audit")
    report_path = require_file(Path(str(audit["conversion"]["report"]["path"])), "CENTER medium conversion report")
    report = load_json(report_path, "CENTER medium conversion report")
    source_h5 = require_file(Path(str(audit["conversion"]["trajectory"]["path"])), "CENTER medium trajectory")
    conversion_receipt = require_file(Path(str(audit["conversion"]["receipt"]["path"])), "CENTER medium conversion receipt")
    solver_receipt = require_file(Path(str(audit["solver"]["receipt"]["path"])), "CENTER medium solver receipt")
    gencase_receipt = require_file(GENCASE_RECEIPT, "CENTER medium GenCase receipt")
    run_out = require_file(CENTER_MEDIUM_SOLVER_OUT / "Run.out", "CENTER medium Run.out")
    generated_xml = require_file(Path(str(report["source_provenance"]["generated_xml"]["path"])), "CENTER medium generated XML")
    motion = require_file(Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001/staged_inputs/F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001/F2H10V2_CENTER_V1_MEDIUM_motion.dat"), "CENTER medium motion control")
    owner = center_medium_owner_metadata(output_dir, report)
    owner_data = load_json(owner, "CENTER medium v7 owner metadata")
    case_id = "F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001"
    attempt_id = "labels-f2h10v2-center-v1-medium-rv4d1-baseline-save001-event-semantics-v6-pose-v2"
    attempt_root = F2_DATA_ROOT / case_id / attempt_id
    augmented = attempt_root / "trajectory-with-actual-pose.h5"
    labels = attempt_root / "f2-v6-labels.h5"
    observations = attempt_root / "f2-v6-observations.json"
    pose_report = attempt_root / "rigid-body-state.json"
    python = WORKTREE_ROOT / "lagrangian-fluid-lab/.venv/bin/python"
    numerical_hash = str(report["hash_scopes"]["numerical_parameters_sha256"])
    physical_hash = str(report["hash_scopes"]["physical_condition_sha256"])
    input_paths = [
        F2_ROOT / "f2_handoff_20261002_postsolver_v7.py",
        F2_ROOT / "f2_handoff_20261002_center_medium_audit.py",
        V6_SCRIPT, V6_OPERATOR, V6_MANIFEST,
        INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_convert.py",
        INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        QUALITY_CONTRACT, EVENT_DEFINITIONS, SAVE_PLAN, CASE_REGISTRY,
        source_h5, audit_path, report_path, conversion_receipt, solver_receipt,
        gencase_receipt, generated_xml, motion, owner, run_out,
    ]
    input_paths = [require_file(path, "CENTER medium labels input") for path in input_paths]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "labels",
        "cpu_threads": 4,
        "max_wall_seconds": 1200,
        "estimated_storage_bytes": 8 * 1024**3,
        "command": [
            str(python), str(V6_SCRIPT), "run",
            "--source-trajectory", str(source_h5),
            "--augmented-trajectory", "{attempt_root}/trajectory-with-actual-pose.h5",
            "--owner-metadata", str(owner), "--generated-xml", str(generated_xml),
            "--motion-control", str(motion), "--run-out", str(run_out),
            "--conversion-report", str(report_path), "--solver-receipt", str(solver_receipt),
            "--gencase-receipt", str(gencase_receipt), "--conversion-receipt", str(conversion_receipt),
            "--numerical-recipe-hash", numerical_hash, "--case-id", case_id,
            "--output", "{attempt_root}/f2-v6-labels.h5",
            "--report", "{attempt_root}/f2-v6-observations.json",
            "--pose-report", "{attempt_root}/rigid-body-state.json",
        ],
        "cwd": str(F2_ROOT),
        "raw_output_root": str(F2_DATA_ROOT / "families/F2"),
        "worktree_root": str(WORKTREE_ROOT),
        "input_files": [str(path) for path in input_paths],
        "source_bindings": binding(input_paths),
        "source_h5": {"path": str(source_h5), "sha256": sha256(source_h5)},
        "actual_audit": {"path": str(audit_path), "sha256": sha256(audit_path)},
        "conversion_receipt": {"path": str(conversion_receipt), "sha256": sha256(conversion_receipt)},
        "conversion_report": {"path": str(report_path), "sha256": sha256(report_path)},
        "solver_receipt": {"path": str(solver_receipt), "sha256": sha256(solver_receipt)},
        "gencase_receipt": {"path": str(gencase_receipt), "sha256": sha256(gencase_receipt)},
        "generated_xml": {"path": str(generated_xml), "sha256": sha256(generated_xml)},
        "motion_control": {"path": str(motion), "sha256": sha256(motion)},
        "physical_condition_hash": physical_hash,
        "numerical_recipe_hash": numerical_hash,
        "physical_binding_sha256": owner_data.get("physical_binding_sha256"),
        "expected_outputs": {
            "receipt": str(attempt_root / "execution-receipt.json"),
            "augmented_trajectory": str(augmented),
            "pose_report": str(pose_report),
            "labels": str(labels),
            "observations": str(observations),
        },
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "status": "ready_for_root_shared_labels_after_conversion_terminal",
        "request_note": "CPU-only additive v6 pose and event labels from completed CENTER medium full-state H5; source H5 remains immutable, saved Type=1 pose is fitted with frozen motion control, and Q-I/Q-N/production remain pending.",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    path = output_dir / "center_medium_v6_labels_request.json"
    write_json(path, request)
    return path


def build_temporal_conversion_request(record: Mapping[str, Any], comparison_path: Path, output_dir: Path) -> Path:
    case_id = str(record["case_id"])
    mechanism = "center_catch" if "CENTER" in case_id else "offset_spill"
    owner = temporal_owner_metadata(record, output_dir)
    launch_path = Path(str(record["request_path"]))
    receipt_path = Path(str(record["solver_receipt"]["path"]))
    gencase_receipt = Path(str(record["gencase_receipt"]["path"]))
    xml = Path(str(record["generated_xml"]["path"]))
    bi4 = Path(str(record["bi4"]["path"]))
    motion = Path(str(record["motion"]["path"]))
    solver_out = Path(str(record["solver_output"]))
    data_root = Path(str(record["data_root"]))
    attempt_id = f"conversion-{case_id.lower()}-fullstate-v7-001"
    attempt_root = F2_DATA_ROOT / case_id / attempt_id
    report = attempt_root / "conversion-report.json"
    trajectory = attempt_root / "trajectory.h5"
    conversion_receipt = attempt_root / "execution-receipt.json"
    resource = estimate_conversion_resources(int(record["summary"]["particle_count"]), int(record["native_frame_count"]))
    input_paths = [
        F2_ROOT / "f2_handoff_20261002_postsolver_v7.py",
        DIRECT_CONVERTER, DECODER, PARTVTK, V6_SCRIPT, V6_MANIFEST,
        QUALITY_CONTRACT, EVENT_DEFINITIONS, SAVE_PLAN, CASE_REGISTRY, REFERENCE_MATRIX,
        owner, launch_path, receipt_path, gencase_receipt, xml, bi4, motion,
        solver_out / "Run.out", solver_out / "Run.csv", solver_out / "RunPARTs.csv",
        Path(record["native_frame_samples"][0]), Path(record["native_frame_samples"][1]), Path(record["native_frame_samples"][2]),
        comparison_path,
    ]
    input_paths = [require_file(path, "conversion input") for path in input_paths]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "command": [
            str(PYTHON), str(DIRECT_CONVERTER), "--data-root", str(data_root),
            "--generated-xml", str(xml), "--output", "{attempt_root}/trajectory.h5",
            "--report", "{attempt_root}/conversion-report.json", "--solver-log", str(solver_out / "Run.out"),
            "--solver-receipt", str(receipt_path), "--gencase-receipt", str(gencase_receipt),
            "--owner-metadata", str(owner), "--decoder", str(DECODER), "--partvtk", str(PARTVTK),
            "--validation-dir", "{attempt_root}/partvtk-validation", "--keep-validation-csv",
        ],
        "cwd": str(WORKTREE_ROOT / "lagrangian-fluid-lab"),
        "max_wall_seconds": resource["max_wall_seconds"],
        "cpu_threads": 4,
        "estimated_storage_bytes": resource["estimated_storage_bytes"],
        "resource_estimate": resource,
        "raw_output_root": str(F2_DATA_ROOT),
        "worktree_root": str(WORKTREE_ROOT),
        "input_files": [str(path) for path in input_paths],
        "source_bindings": binding(input_paths),
        "input_sha256": input_sha256(input_paths),
        "physical_condition_hash": record["physical_condition_hash"],
        "numerical_recipe_hash": record["numerical_recipe_hash"],
        "generated_xml": {"path": str(xml), "sha256": sha256(xml)},
        "actual_source": {
            "solver_attempt": str(Path(str(record["solver_receipt"]["path"])).parent),
            "solver_receipt": str(receipt_path),
            "gencase_receipt": str(gencase_receipt),
            "data_root": str(data_root),
            "native_frame_count": record["native_frame_count"],
            "native_frame_samples": record["native_frame_samples"],
            "particle_count": record["summary"]["particle_count"],
            "physical_time_s": record["summary"]["physical_time_s"],
            "parts_out": record["summary"]["parts_out"],
            "np_out_sum": record["summary"]["np_out_sum"],
            "solver_dimension": 3,
            "event_window_s": [0.0, 4.0],
        },
        "expected_outputs": {
            "receipt": str(conversion_receipt),
            "trajectory": str(trajectory),
            "conversion_report": str(report),
        },
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "request_note": "CPU-only correct-tool direct conversion after a completed solver receipt; v6 pose/labels are deferred and Q-N/production remain pending.",
        "label_request_plan": _v6_label_plan(
            case_id=case_id, conversion_attempt_root=attempt_root, trajectory=trajectory,
            owner=owner, xml=xml, motion=motion, solver_receipt=receipt_path,
            gencase_receipt=gencase_receipt, numerical_hash=str(record["numerical_recipe_hash"]),
            conversion_receipt=conversion_receipt, conversion_report=report,
        ),
        "status": "ready_for_root_shared_conversion_after_solver_terminal",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    path = output_dir / "conversion_requests" / f"{case_id}_conversion_request.json"
    write_json(path, request)
    return path


def dp005_conversion_template(solver_request_path: Path, output_dir: Path) -> Path:
    solver_request = load_json(solver_request_path, "DP005 solver request")
    case_id = str(solver_request["case_id"])
    prefix = require_file(Path(str(solver_request["gencase_prefix"]) + ".xml"), "DP005 generated XML")
    bi4 = require_file(prefix.with_suffix(".bi4"), "DP005 BI4")
    motion = require_file(prefix.parent / f"{prefix.stem}_motion.dat", "DP005 motion")
    gencase_receipt = require_file(Path(str(solver_request["gencase_receipt"])), "DP005 GenCase receipt")
    source_metadata = next(Path(path) for path in solver_request["input_files"] if str(path).endswith(".metadata.json"))
    source_metadata = require_file(source_metadata, "DP005 metadata")
    metadata = dp005_owner_metadata(solver_request, prefix, motion, source_metadata, output_dir)
    gencase = load_json(gencase_receipt, "DP005 GenCase receipt")
    total_particles = int(gencase["total_particles"])
    frames = 401
    solver_receipt = F2_DATA_ROOT / case_id / str(solver_request["attempt_id"]) / "execution-receipt.json"
    solver_out = solver_receipt.parent / "solver_output"
    data_root = solver_out / "data"
    terminal = False
    actual_summary: dict[str, Any] | None = None
    actual_frames: list[Path] = []
    if solver_receipt.is_file():
        candidate_receipt = load_json(solver_receipt, "DP005 solver receipt")
        terminal = candidate_receipt.get("status") in {"completed", "success"} and candidate_receipt.get("returncode", candidate_receipt.get("exit_code")) == 0
        if terminal:
            actual_out, actual_data = solver_output(candidate_receipt)
            actual_frames = sorted(actual_data.glob("Part_*.bi4"))
            if not actual_frames:
                raise FileNotFoundError(f"completed DP005 solver has no Part files: {actual_data}")
            solver_out, data_root = actual_out, actual_data
            frames = len(actual_frames)
            actual_summary = read_run_summary(solver_out)
            total_particles = int(actual_summary["particle_count"])
    resource = estimate_conversion_resources(total_particles, frames)
    attempt_id = f"conversion-{case_id.lower()}-fullstate-v7-001"
    attempt_root = F2_DATA_ROOT / case_id / attempt_id
    trajectory = attempt_root / "trajectory.h5"
    report = attempt_root / "conversion-report.json"
    conversion_receipt = attempt_root / "execution-receipt.json"
    existing = [
        F2_ROOT / "f2_handoff_20261002_postsolver_v7.py", DIRECT_CONVERTER, DECODER, PARTVTK,
        V6_SCRIPT, V6_MANIFEST, QUALITY_CONTRACT, EVENT_DEFINITIONS, SAVE_PLAN, CASE_REGISTRY,
        REFERENCE_MATRIX, GOAL, DP005_MANIFEST, DP005_AUDIT, solver_request_path,
        gencase_receipt, prefix, bi4, motion, source_metadata, metadata,
    ]
    existing = [require_file(path, "DP005 conversion input") for path in existing]
    if terminal:
        existing.extend([solver_receipt, solver_out / "Run.out", solver_out / "Run.csv", solver_out / "RunPARTs.csv", actual_frames[0], actual_frames[len(actual_frames) // 2], actual_frames[-1]])
        existing = [require_file(path, "DP005 terminal conversion input") for path in existing]
        deferred: list[Path] = []
    else:
        deferred = [solver_receipt, solver_out / "Run.out", solver_out / "Run.csv", solver_out / "RunPARTs.csv", data_root / "Part_0000.bi4", data_root / "Part_0200.bi4", data_root / "Part_0400.bi4"]
    actual_source = {
        "gencase_receipt": str(gencase_receipt),
        "data_root_expected": str(data_root),
        "native_frame_count_expected": frames,
        "particle_count_from_gencase": int(gencase["total_particles"]),
        "solver_dimension_from_gencase": gencase.get("solver_dimension_from_gencase"),
        "event_window_s": [0.0, 4.0],
    }
    if terminal and actual_summary is not None:
        actual_source.update({
            "solver_receipt": str(solver_receipt),
            "data_root": str(data_root),
            "native_frame_count": len(actual_frames),
            "native_frame_samples": [str(actual_frames[0]), str(actual_frames[len(actual_frames) // 2]), str(actual_frames[-1])],
            "particle_count": actual_summary["particle_count"],
            "physical_time_s": actual_summary["physical_time_s"],
            "parts_out": actual_summary["parts_out"],
            "np_out_sum": actual_summary["np_out_sum"],
            "run_summary": actual_summary,
            "solver_status": "completed",
        })
    native_exclusion_sum = float(actual_summary["np_out_sum"]) if terminal and actual_summary is not None else None
    exclusion_gate = {
        "status": "not_observed_until_solver_terminal" if not terminal else (
            "blocked_pending_native_exclusion_diagnosis" if native_exclusion_sum else "clear"),
        "np_out_sum": native_exclusion_sum,
        "np_out_semantics": "RunPARTs full-window sum; unknown native fate is retained and is not inferred as physical spill",
    }
    status = "ready_for_root_shared_conversion_after_solver_terminal" if terminal and not native_exclusion_sum else (
        "blocked_pending_native_exclusion_diagnosis" if terminal else "deferred_until_root_dp005_solver_terminal")
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "command": [
            str(PYTHON), str(DIRECT_CONVERTER), "--data-root", str(data_root),
            "--generated-xml", str(prefix), "--output", "{attempt_root}/trajectory.h5",
            "--report", "{attempt_root}/conversion-report.json", "--solver-log", str(solver_out / "Run.out"),
            "--solver-receipt", str(solver_receipt), "--gencase-receipt", str(gencase_receipt),
            "--owner-metadata", str(metadata), "--decoder", str(DECODER), "--partvtk", str(PARTVTK),
            "--validation-dir", "{attempt_root}/partvtk-validation", "--keep-validation-csv",
        ],
        "cwd": str(WORKTREE_ROOT / "lagrangian-fluid-lab"),
        "max_wall_seconds": resource["max_wall_seconds"],
        "cpu_threads": 4,
        "estimated_storage_bytes": resource["estimated_storage_bytes"],
        "resource_estimate": resource,
        "raw_output_root": str(F2_DATA_ROOT),
        "worktree_root": str(WORKTREE_ROOT),
        "input_files": [str(path) for path in existing],
        "source_bindings": binding(existing),
        "input_sha256": input_sha256(existing),
        "deferred_input_files": [str(path) for path in deferred],
        "deferred_binding_policy": "After the root solver receipt is terminal code 0, materialize exact hashes for solver receipt/Run*.csv/Part samples before submitting this conversion request." if deferred else "all solver and native Part source bindings are terminal and hashed",
        "physical_condition_hash": solver_request.get("physical_condition_hash"),
        "numerical_recipe_hash": solver_request.get("numerical_recipe_hash"),
        "generated_xml": {"path": str(prefix), "sha256": sha256(prefix)},
        "actual_source": actual_source,
        "expected_outputs": {"receipt": str(conversion_receipt), "trajectory": str(trajectory), "conversion_report": str(report)},
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "native_exclusion_gate": exclusion_gate,
        "request_note": (
            "CPU-only correct-tool direct conversion is held until a bounded native exclusion diagnosis classifies the nonzero RunPARTs NpOut rows; unknown is not physical spill. Macro-spatial evidence only; event timing and Q-N remain pending."
            if terminal and native_exclusion_sum else
            "CPU-only correct-tool direct conversion for the root-owned DP005 .01-save run. Macro-spatial evidence only; event timing and Q-N remain pending."
            if terminal else
            "Deferred CPU-only correct-tool conversion template. The DP005 .01-save solver is root-owned; bind its terminal receipt and actual RunPARTs/Part samples before scheduling. Macro-spatial evidence only; event timing and Q-N remain pending."
        ),
        "status": status,
        "qualification_claim": "none",
        "production_claim": "none",
        "label_request_plan": (
            _v6_label_plan(
                case_id=case_id,
                conversion_attempt_root=attempt_root,
                trajectory=trajectory,
                owner=metadata,
                xml=prefix,
                motion=motion,
                solver_receipt=solver_receipt,
                gencase_receipt=gencase_receipt,
                numerical_hash=str(solver_request.get("numerical_recipe_hash")),
                conversion_receipt=conversion_receipt,
                conversion_report=report,
            )
            if terminal
            else {
                "requires_conversion_terminal": True,
                "requires_actual_native_pose": True,
                "owner_metadata": str(metadata),
                "definition_override": str(prefix),
                "motion_control": str(motion),
                "numerical_recipe_hash": solver_request.get("numerical_recipe_hash"),
                "case_id_override": case_id,
                "operator_hash": sha256(V6_MANIFEST),
                "status": "deferred_until_conversion_terminal",
            }
        ),
    }
    folder = "dp005_pending_diagnosis" if terminal and native_exclusion_sum else ("conversion_requests" if terminal else "dp005_conversion_templates")
    filename = f"{case_id}_conversion_request.json" if terminal else f"{case_id}_conversion_template.json"
    path = output_dir / folder / filename
    write_json(path, request)
    return path


def build(output_dir: Path, *, include_dp005: bool = True) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    require_file(DIRECT_CONVERTER, "direct converter")
    require_file(DECODER, "BI4 decoder")
    require_file(PARTVTK, "official full-frame PartVTK")
    comparison = temporal_comparison(output_dir)
    comparison_path = Path(comparison["path"])
    temporal_records = [actual_solver_record(path) for path in temporal_requests()]
    requests = [build_temporal_conversion_request(record, comparison_path, output_dir) for record in temporal_records]
    center_audit = require_file(CENTER_MEDIUM_AUDIT, "CENTER medium actual audit")
    center_labels = build_center_medium_v6_label_request(output_dir)
    dp005 = []
    if include_dp005:
        for path in sorted((F2_ROOT / "commensurate_cellcenter_dp005_v2/solver_requests").glob("*_request.json")):
            dp005.append(dp005_conversion_template(path, output_dir))
    manifest = {
        "schema": "ds-data-02.f2.postsolver-handoff.v7",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope_id": "F2_SCOPE_GEM_COMMENSURATE_CELLCENTER_20261002_V2",
        "official_partvtk": {"path": str(PARTVTK), "sha256": sha256(PARTVTK), "role": "full-frame validation"},
        "owner_metadata_dir": str(output_dir / "owner_metadata"),
        "owner_metadata_files": [
            {"path": str(path), "sha256": sha256(path)}
            for path in sorted((output_dir / "owner_metadata").glob("*.json"))
        ],
        "temporal_comparison": {"path": str(comparison_path), "sha256": sha256(comparison_path)},
        "temporal_conversion_requests": [{"path": str(path), "sha256": sha256(path)} for path in requests],
        "center_medium_actual_audit": {"path": str(center_audit), "sha256": sha256(center_audit)},
        "center_medium_v6_labels_request": {"path": str(center_labels), "sha256": sha256(center_labels)},
        "dp005_conversion_requests": [{"path": str(path), "sha256": sha256(path)} for path in dp005],
        "source_bytes_immutable": True,
        "solver_launch": False,
        "conversion_launch": False,
        "qualification_claim": "none; conversion and v6 pose labels are evidence stages, Q-N remains pending",
        "production_claim": "none",
    }
    manifest_path = output_dir / "postsolver_handoff_manifest.json"
    write_json(manifest_path, manifest)
    return {"manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path), "temporal_requests": [str(path) for path in requests], "center_medium_labels_request": str(center_labels), "dp005_requests": [str(path) for path in dp005], "comparison": str(comparison_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--no-dp005", action="store_true", help="write only the completed temporal requests")
    args = parser.parse_args()
    print(json.dumps(build(args.output_dir, include_dp005=not args.no_dp005), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

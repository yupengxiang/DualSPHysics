#!/usr/bin/env python3
"""Audit the terminal XML from the bounded Stage2 GenCase v3 probes.

This is a small-input audit only.  It reads generated XML and guard receipts;
it never opens a production HDF5 file, starts a solver, or rescales particle
mass.  The whole-initial-source mass error is the frozen acceptance metric.
Per-mk rows are retained as diagnostics and do not grant scientific
qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-mass-fit-probe-v3"
INPUT_MANIFEST = REFERENCE / "stage2_mass_fit_probe_inputs_v3/manifest.json"
OUTPUT = REFERENCE / "stage2_mass_fit_probe_results_v3.json"

# These are the exact small generated-XML references used for the source
# sample target.  They are not solver outputs and are never read as HDF5.
SOURCE_XML = {
    "F2-S1": DATA_ROOT / "families/F2/F2_S1_PREFLIGHT_NATIVE_DP010_DENSE_CFL010/f2_s1_preflight_native_dp010_dense_cfl010-003/generated.xml",
    "F4-S1": DATA_ROOT / "families/F4/F4_DROP_CENTERED_REFERENCE_001_DP010/gencase-centered-reference-002/F4_DROP_CENTERED_REFERENCE_001_DP010.xml",
    "F7-S1": DATA_ROOT / "families/F7/F7_QUINTIC_VERIFIED_MOTION_ASSET_CLONES/root-quintic-verified-three-dp-actual-motion-asset-clones-024/prepared/coarse/F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE.xml",
    "F7-S2": DATA_ROOT / "families/F7/F7_OBSTACLE_QUINTIC_B08_A065/root-stage1-f7-angle065-genuine-gencase-085/prepared/F7_OBSTACLE_QUINTIC_B08_A065.xml",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def source_semantics(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    mass_nodes = root.findall(".//massfluid")
    values = [node.attrib.get("value") for node in mass_nodes]
    if len(values) != 1 or values[0] is None:
        raise ValueError(f"{path}: expected one massfluid value")
    massfluid = float(values[0])
    blocks = []
    for node in root.findall(".//fluid"):
        if "mkfluid" not in node.attrib or "count" not in node.attrib:
            continue
        blocks.append({
            "mkfluid": node.attrib["mkfluid"],
            "count": int(node.attrib["count"]),
        })
    if not blocks:
        raise ValueError(f"{path}: no material fluid blocks")
    by_mk = {
        row["mkfluid"]: {
            "count": row["count"],
            "massfluid_kg": massfluid,
            "sample_mass_kg": row["count"] * massfluid,
        }
        for row in blocks
    }
    return {
        "file": record(path),
        "dp_m": [node.attrib.get("dp") for node in root.findall(".//definition") if node.attrib.get("dp") is not None],
        "fluid_blocks": blocks,
        "total_fluid_particles": sum(row["count"] for row in blocks),
        "massfluid_kg": massfluid,
        "by_mkfluid": by_mk,
    }


def gate(error_fraction: float) -> str:
    absolute = abs(error_fraction)
    if absolute <= 0.01:
        return "PASS_TARGET_1PCT"
    if absolute <= 0.02:
        return "MARGINAL_1_TO_2PCT"
    return "HARD_FAIL_GT2PCT"


def diagnostic_3pct(error_fraction: float) -> str:
    return "WITHIN_3PCT_DIAGNOSTIC" if abs(error_fraction) <= 0.03 else "OVER_3PCT_DIAGNOSTIC"


def audit_candidate(item: dict[str, Any], source_cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidate = item["candidate"]
    case_id = candidate["case_id"]
    request_path = REQUEST_ROOT / (case_id.lower() + ".json")
    if not request_path.is_file():
        raise FileNotFoundError(request_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    receipt_path = DATA_ROOT / "families" / candidate["family_id"] / case_id / (case_id.lower() + "-001") / "execution-receipt.json"
    if not receipt_path.is_file():
        raise FileNotFoundError(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    output_root = Path(receipt["output_root"])
    generated_xml = output_root / "generated.xml"
    if not generated_xml.is_file():
        raise FileNotFoundError(generated_xml)

    source = source_cache[candidate["sentinel_id"]]
    derived = source_semantics(generated_xml)
    target = float(request["scope"]["whole_initial_source_mass_target_kg"])
    derived_mass = sum(row["sample_mass_kg"] for row in derived["by_mkfluid"].values())
    total_error = (derived_mass - target) / target
    source_by_mk = source["by_mkfluid"]
    rows = []
    for mk in sorted(set(source_by_mk) | set(derived["by_mkfluid"])):
        if mk not in source_by_mk or mk not in derived["by_mkfluid"]:
            rows.append({
                "mkfluid": mk,
                "status": "UNKNOWN_MK_NOT_PRESENT_IN_BOTH_SOURCE_AND_DERIVED",
                "source": source_by_mk.get(mk),
                "derived": derived["by_mkfluid"].get(mk),
            })
            continue
        src_mass = source_by_mk[mk]["sample_mass_kg"]
        der_mass = derived["by_mkfluid"][mk]["sample_mass_kg"]
        delta = der_mass - src_mass
        relative = delta / src_mass
        rows.append({
            "mkfluid": mk,
            "source": source_by_mk[mk],
            "derived": derived["by_mkfluid"][mk],
            "delta_kg": delta,
            "deviation_fraction_vs_source_mk": relative,
            "deviation_pct_vs_source_mk": relative * 100.0,
            "absolute_delta_fraction_of_source_total": abs(delta) / target,
            "diagnostic_3pct": diagnostic_3pct(relative),
        })

    request_sha = sha256_file(request_path)
    request_inputs = request.get("input_hashes", {})
    receipt_inputs = receipt.get("input_hashes_at_launch", {})
    launch_input_match = request_inputs == receipt_inputs
    return {
        "case_id": case_id,
        "sentinel_id": candidate["sentinel_id"],
        "family_id": candidate["family_id"],
        "physical_case_id": candidate["physical_case_id"],
        "label": candidate["label"],
        "candidate_dp_m": candidate["candidate_dp_m"],
        "source_dp_m": candidate["source_dp_m"],
        "source_mass_target_kg": target,
        "request": {
            "path": str(request_path.resolve()),
            "sha256": request_sha,
            "sha256_matches_receipt": request_sha == receipt.get("request_sha256"),
            "input_file_count": len(request_inputs),
            "contains_hdf5_input": any(str(path).lower().endswith((".h5", ".hdf5")) for path in request_inputs),
            "launch_input_hashes_match_request": launch_input_match,
            "launch_commit": request.get("resource_guard", {}).get("launch_commit"),
        },
        "receipt": {
            "path": str(receipt_path.resolve()),
            "file": record(receipt_path),
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "termination_reason": receipt.get("termination_reason"),
            "elapsed_seconds": receipt.get("elapsed_seconds"),
            "cpu_core_seconds": receipt.get("cpu_core_seconds"),
            "gpu_seconds": receipt.get("gpu_seconds"),
            "bytes": receipt.get("bytes"),
            "terminal_storage_guard": receipt.get("terminal_storage_guard"),
            "output_root": str(output_root),
        },
        "source": source,
        "derived": derived,
        "whole_initial_mass": {
            "derived_sample_mass_kg": derived_mass,
            "delta_kg": derived_mass - target,
            "error_fraction_vs_source_target": total_error,
            "error_pct_vs_source_target": total_error * 100.0,
            "gate": gate(total_error),
            "gate_basis": "abs(derived_total - frozen_source_initial_sample_mass_target) / frozen_source_initial_sample_mass_target; target <=1%, marginal <=2%, hard >2%",
        },
        "per_mk_diagnostics": rows,
        "input_integrity": {
            "only_definition_dp_changed": candidate["derived_inputs"]["only_definition_dp_changed"],
            "normalized_geometry_hash_source": candidate["derived_inputs"]["normalized_geometry_hash_source"],
            "normalized_geometry_hash_derived": candidate["derived_inputs"]["normalized_geometry_hash_derived"],
            "normalized_geometry_unchanged": candidate["derived_inputs"]["normalized_geometry_hash_source"] == candidate["derived_inputs"]["normalized_geometry_hash_derived"],
            "continuous_geometry_unchanged": candidate["continuous_vs_intentional"]["continuous_geometry_unchanged"],
            "continuous_fill_and_control_unchanged": candidate["continuous_vs_intentional"]["continuous_fill_and_control_unchanged"],
            "motion_or_acceleration_changed": candidate["continuous_vs_intentional"]["motion_or_acceleration_changed"],
            "dependencies_byte_identical": candidate["continuous_vs_intentional"]["dependencies_byte_identical"],
            "particle_mass_rescale": candidate["continuous_vs_intentional"]["particle_mass_rescale"],
        },
        "scientific_qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "solver_started": False,
            "full_time_hdf5_read": False,
            "note": "GenCase mass compatibility does not establish geometry, dynamics, time/output, observer, or material-task qualification.",
        },
    }


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    manifest = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
    source_cache = {sentinel: source_semantics(path) for sentinel, path in SOURCE_XML.items()}
    results = [audit_candidate(item, source_cache) for item in manifest["records"]]
    summary = {}
    for item in results:
        key = item["whole_initial_mass"]["gate"]
        summary[key] = summary.get(key, 0) + 1
    report = {
        "schema": "ds02.stage2.mass-fit-probe-results.v3",
        "status": "COMPLETED_GENCACE_V3_AUDIT_ONLY",
        "generated_at_commit": git_commit(),
        "input_manifest": record(INPUT_MANIFEST),
        "policy": {
            "scope": "bounded GenCase-only spacing/phase probes for F2-S1, F4-S1, F7-S1, and F7-S2",
            "whole_initial_source_mass_metric": "frozen source sample target; source continuum mass is not substituted",
            "thresholds": {"target_abs_pct": 1.0, "marginal_upper_abs_pct": 2.0, "hard_gt_abs_pct": 2.0},
            "per_mk_rows": "diagnostic only; the 3% per-mk row does not replace the whole-initial task budget or grant scientific acceptance",
            "continuous_conditions": "geometry, fill, controls, and declared motion dependencies remain bound; only definition@dp is intentionally varied",
            "no_mass_rescale": True,
            "solver_started": False,
            "full_time_hdf5_read": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "summary": {"candidate_count": len(results), "whole_initial_mass_gate_counts": summary},
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(args.output), "summary": report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

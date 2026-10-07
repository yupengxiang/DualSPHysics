#!/usr/bin/env python3
"""Audit the four bounded F2-S1 dp=0.0085-neighborhood GenCase outputs."""
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
INPUT_MANIFEST = REFERENCE / "stage2_f2_mass_fit_probe_inputs_v4/manifest.json"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f2-mass-fit-probe-v4"
OUTPUT = REFERENCE / "stage2_f2_mass_fit_results_v4.json"
SOURCE_XML = DATA_ROOT / "families/F2/F2_S1_PREFLIGHT_NATIVE_DP010_DENSE_CFL010/f2_s1_preflight_native_dp010_dense_cfl010-003/generated.xml"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def parse_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    mass_nodes = root.findall(".//massfluid")
    if len(mass_nodes) != 1 or mass_nodes[0].get("value") is None:
        raise ValueError(f"{path}: expected one massfluid")
    massfluid = float(mass_nodes[0].get("value"))
    blocks = []
    for node in root.findall(".//fluid"):
        if "mkfluid" in node.attrib and "count" in node.attrib:
            blocks.append({"mkfluid": node.attrib["mkfluid"], "count": int(node.attrib["count"])})
    if not blocks:
        raise ValueError(f"{path}: no mkfluid blocks")
    by_mk = {b["mkfluid"]: {"count": b["count"], "massfluid_kg": massfluid, "sample_mass_kg": b["count"] * massfluid} for b in blocks}
    return {
        "file": record(path),
        "dp_m": [n.get("dp") for n in root.findall(".//definition") if n.get("dp") is not None],
        "fluid_blocks": blocks,
        "total_fluid_particles": sum(b["count"] for b in blocks),
        "massfluid_kg": massfluid,
        "by_mkfluid": by_mk,
    }


def gate(error: float) -> str:
    if abs(error) <= 0.01:
        return "PASS_TARGET_1PCT"
    if abs(error) <= 0.02:
        return "MARGINAL_1_TO_2PCT"
    return "HARD_FAIL_GT2PCT"


def audit(item: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    candidate = item["candidate"]
    case_id = candidate["case_id"]
    request_path = REQUEST_ROOT / f"{case_id.lower()}.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    receipt_path = DATA_ROOT / "families/F2" / case_id / f"{case_id.lower()}-001" / "execution-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    output_root = Path(receipt["output_root"])
    xml_path = output_root / "generated.xml"
    derived = parse_xml(xml_path)
    target = float(request["scope"]["whole_initial_source_mass_target_kg"])
    total = sum(v["sample_mass_kg"] for v in derived["by_mkfluid"].values())
    error = (total - target) / target
    rows = []
    for mk in sorted(set(source["by_mkfluid"]) | set(derived["by_mkfluid"])):
        if mk not in source["by_mkfluid"] or mk not in derived["by_mkfluid"]:
            rows.append({"mkfluid": mk, "status": "UNKNOWN_MK_NOT_PRESENT_IN_BOTH_SOURCE_AND_DERIVED"})
            continue
        sm = source["by_mkfluid"][mk]["sample_mass_kg"]
        dm = derived["by_mkfluid"][mk]["sample_mass_kg"]
        delta = dm - sm
        rows.append({
            "mkfluid": mk,
            "source": source["by_mkfluid"][mk],
            "derived": derived["by_mkfluid"][mk],
            "delta_kg": delta,
            "deviation_pct_vs_source_mk": delta / sm * 100.0,
            "absolute_delta_fraction_of_source_total": abs(delta) / target,
            "diagnostic_3pct": "WITHIN_3PCT_DIAGNOSTIC" if abs(delta / sm) <= 0.03 else "OVER_3PCT_DIAGNOSTIC",
        })
    request_sha = sha256_file(request_path)
    return {
        "case_id": case_id,
        "sentinel_id": candidate["sentinel_id"],
        "family_id": candidate["family_id"],
        "physical_case_id": candidate["physical_case_id"],
        "candidate_dp_m": candidate["candidate_dp_m"],
        "source_dp_m": candidate["source_dp_m"],
        "source_mass_target_kg": target,
        "request": {
            "path": str(request_path.resolve()),
            "sha256": request_sha,
            "sha256_matches_receipt": request_sha == receipt.get("request_sha256"),
            "input_file_count": len(request.get("input_hashes", {})),
            "contains_hdf5_input": any(str(p).lower().endswith((".h5", ".hdf5")) for p in request.get("input_hashes", {})),
            "launch_input_hashes_match_request": request.get("input_hashes", {}) == receipt.get("input_hashes_at_launch", {}),
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
            "derived_sample_mass_kg": total,
            "delta_kg": total - target,
            "error_pct_vs_source_target": error * 100.0,
            "gate": gate(error),
            "basis": "frozen Stage1 discrete source sample mass target; continuum box mass is not substituted",
        },
        "per_mk_diagnostics": rows,
        "input_integrity": {
            "only_definition_dp_changed": candidate["derived_inputs"]["only_definition_dp_changed"],
            "normalized_geometry_unchanged": candidate["derived_inputs"]["normalized_geometry_hash_source"] == candidate["derived_inputs"]["normalized_geometry_hash_derived"],
            "continuous_geometry_unchanged": candidate["continuous_vs_intentional"]["continuous_geometry_unchanged"],
            "continuous_fill_and_control_unchanged": candidate["continuous_vs_intentional"]["continuous_fill_and_control_unchanged"],
            "motion_dependency_byte_identical": candidate["continuous_vs_intentional"]["motion_dependency_byte_identical"],
            "particle_mass_rescale": candidate["continuous_vs_intentional"]["particle_mass_rescale"],
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "solver_started": False, "full_time_hdf5_read": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    manifest = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
    source = parse_xml(SOURCE_XML)
    results = [audit(item, source) for item in manifest["records"]]
    counts: dict[str, int] = {}
    for result in results:
        key = result["whole_initial_mass"]["gate"]
        counts[key] = counts.get(key, 0) + 1
    report = {
        "schema": "ds02.stage2.f2-mass-fit-results.v4",
        "status": "COMPLETED_GENCACE_V4_AUDIT_ONLY",
        "generated_at_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip(),
        "input_manifest": record(INPUT_MANIFEST),
        "policy": {
            "scope": "four bounded F2-S1 dp candidates near consumed dp=0.0085",
            "whole_initial_mass_thresholds_pct": {"target": 1.0, "marginal_upper": 2.0, "hard_gt": 2.0},
            "per_mk_rows": "diagnostic only; no particle-mass rescaling and no automatic scientific acceptance",
            "solver_started": False,
            "full_time_hdf5_read": False,
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
        "summary": {"candidate_count": len(results), "whole_initial_mass_gate_counts": counts},
        "results": results,
    }
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(args.output), "summary": report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

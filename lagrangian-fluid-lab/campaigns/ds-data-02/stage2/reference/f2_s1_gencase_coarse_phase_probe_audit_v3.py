#!/usr/bin/env python3
"""Audit the source-bound F2-S1 coarse phase probe v3 outputs.

The audit consumes only the committed v3 manifest/requests, the GenCase XML
and its terminal receipts.  It does not open BI4/H5 data and it cannot start a
solver.  Whole-sample mass is the qualification gate; per-mkfluid rows are
diagnostics retained to expose the layer imbalance that a total can hide.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f2-s1.gencase-coarse-phase-probe-audit.v3"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
MANIFEST = REFERENCE / "f2_s1_coarse_phase_probe_inputs_v3/manifest.json"
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f2-s1-coarse-phase-probe-v3"
SOURCE_XML = DATA_ROOT / "families/F2/F2_S1_PREFLIGHT_NATIVE_DP010_DENSE_CFL010/f2_s1_preflight_native_dp010_dense_cfl010-003/generated.xml"
OUTPUT = REFERENCE / "stage2_f2_s1_coarse_phase_probe_results_v3.json"
PASS_RELATIVE = 0.01
HARD_UPPER_RELATIVE = 0.02


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()


def parse_generated_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    mass_nodes = [node for node in root.findall(".//massfluid") if node.get("value") is not None]
    if len(mass_nodes) != 1:
        raise ValueError(f"{path}: expected one massfluid value, got {len(mass_nodes)}")
    massfluid = float(mass_nodes[0].get("value"))
    blocks = []
    for node in root.findall(".//fluid"):
        # The generated XML also has summary fluid nodes.  They do not carry
        # mkfluid/count and must not be folded into the source sample mass.
        if "mkfluid" not in node.attrib or "count" not in node.attrib:
            continue
        blocks.append(
            {
                "mkfluid": str(node.attrib["mkfluid"]),
                "mk": node.attrib.get("mk"),
                "begin": int(node.attrib["begin"]) if node.attrib.get("begin") else None,
                "count": int(node.attrib["count"]),
            }
        )
    if not blocks:
        raise ValueError(f"{path}: no generated fluid blocks with mkfluid/count")
    by_mk = {
        block["mkfluid"]: {
            "count": block["count"],
            "massfluid_kg": massfluid,
            "sample_mass_kg": block["count"] * massfluid,
        }
        for block in blocks
    }
    definitions = [node.get("dp") for node in root.findall(".//definition") if node.get("dp") is not None]
    return {
        "file": file_record(path),
        "definition_dp_values": definitions,
        "fluid_blocks": blocks,
        "total_fluid_particles": sum(block["count"] for block in blocks),
        "massfluid_kg": massfluid,
        "initial_fluid_sample_mass_kg": sum(value["sample_mass_kg"] for value in by_mk.values()),
        "by_mkfluid": by_mk,
    }


def gate(actual_mass: float, target_mass: float) -> dict[str, Any]:
    relative = (actual_mass - target_mass) / target_mass
    absolute = abs(relative)
    if absolute <= PASS_RELATIVE:
        status = "PASS_TARGET_1PCT"
    elif absolute <= HARD_UPPER_RELATIVE:
        status = "MARGINAL_1_TO_2PCT"
    else:
        status = "HARD_FAIL_GT2PCT"
    return {
        "status": status,
        "target_initial_fluid_sample_mass_kg": target_mass,
        "actual_initial_fluid_sample_mass_kg": actual_mass,
        "delta_kg": actual_mass - target_mass,
        "relative_error": relative,
        "error_pct": relative * 100.0,
        "pass_relative_tolerance": PASS_RELATIVE,
        "hard_upper_relative_tolerance": HARD_UPPER_RELATIVE,
        "decision": "diagnostic pre-solver evidence; only PASS_TARGET_1PCT is eligible for parent review and no solver credit is granted",
    }


def per_mk_rows(source: dict[str, Any], derived: dict[str, Any], target_mass: float) -> list[dict[str, Any]]:
    rows = []
    for mk in sorted(set(source["by_mkfluid"]) | set(derived["by_mkfluid"]), key=str):
        if mk not in source["by_mkfluid"] or mk not in derived["by_mkfluid"]:
            rows.append({"mkfluid": mk, "status": "UNKNOWN_MK_NOT_PRESENT_IN_BOTH_SOURCE_AND_DERIVED"})
            continue
        source_mass = source["by_mkfluid"][mk]["sample_mass_kg"]
        derived_mass = derived["by_mkfluid"][mk]["sample_mass_kg"]
        delta = derived_mass - source_mass
        relative = delta / source_mass
        rows.append(
            {
                "mkfluid": mk,
                "source": source["by_mkfluid"][mk],
                "derived": derived["by_mkfluid"][mk],
                "delta_kg": delta,
                "deviation_pct_vs_source_mk": relative * 100.0,
                "absolute_delta_fraction_of_source_total": abs(delta) / target_mass,
                "diagnostic_3pct": "WITHIN_3PCT_DIAGNOSTIC" if abs(relative) <= 0.03 else "OVER_3PCT_DIAGNOSTIC",
                "qualification": "DIAGNOSTIC_ONLY_NO_PER_MK_RESCALE_OR_ACCEPTANCE",
            }
        )
    return rows


def audit_case(record: dict[str, Any], source: dict[str, Any], target_mass: float) -> dict[str, Any]:
    case_id = record["case_id"]
    request_path = require_file(REQUEST_DIR / f"{case_id.lower()}.json", "v3 request")
    request = load_json(request_path)
    if request.get("case_id") != case_id:
        raise ValueError(f"request case_id mismatch: {request_path}")
    attempt_root = DATA_ROOT / "families/F2" / case_id / request["attempt_id"]
    receipt_path = require_file(attempt_root / "execution-receipt.json", "v3 receipt")
    receipt = load_json(receipt_path)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise RuntimeError(f"guard receipt not completed successfully: {receipt_path}")
    output_root = Path(receipt.get("output_root", str(attempt_root)))
    generated_xml = require_file(output_root / "generated.xml", "v3 generated XML")
    derived = parse_generated_xml(generated_xml)
    request_hash = sha256_file(request_path)
    launch_hashes = receipt.get("input_hashes_at_launch", {})
    request_hashes = request.get("input_hashes", {})
    source_template = record["source_template"]
    derived_inputs = record["derived_inputs"]
    source_motion = source_template["motion"]["sha256"]
    derived_motion = derived_inputs["motion"]["sha256"]
    input_binding = {
        "request_sha256_matches_receipt": request_hash == receipt.get("request_sha256"),
        "request_input_hashes_match_receipt_launch": request_hashes == launch_hashes,
        "request_input_count": len(request_hashes),
        "contains_hdf5_input": any(str(path).lower().endswith((".h5", ".hdf5")) for path in request_hashes),
        "source_template_definition": source_template["definition"],
        "source_template_motion": source_template["motion"],
        "derived_definition": derived_inputs["definition"],
        "derived_motion": derived_inputs["motion"],
        "motion_bytes_unchanged": source_motion == derived_motion,
        "physical_case_id_exact": request.get("scope", {}).get("physical_case_id") == record["physical_case_id"],
        "gencase_only": bool(request.get("scope", {}).get("gencase_only")),
        "solver_started_declared_false": request.get("scope", {}).get("solver_started") is False,
        "full_time_hdf5_read_declared_false": request.get("scope", {}).get("full_time_hdf5_read") is False,
    }
    return {
        "case_id": case_id,
        "sentinel_id": "F2-S1",
        "family_id": "F2",
        "physical_case_id": record["physical_case_id"],
        "candidate_dp_m": record["dp_m"],
        "same_origin_phase_policy": record["phase_policy"],
        "source_geometry_control_policy": "CURRENT336 Def/motion copied byte-for-byte except declared dp and generated motion filename; this is a GenCase input probe, not a continuous-state equivalence proof",
        "request": {
            "path": str(request_path.resolve()),
            "file": file_record(request_path),
            "launch_commit": request.get("resource_guard", {}).get("launch_commit"),
            "attempt_id": request.get("attempt_id"),
        },
        "receipt": {
            "path": str(receipt_path.resolve()),
            "file": file_record(receipt_path),
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "termination_reason": receipt.get("termination_reason"),
            "elapsed_seconds": receipt.get("elapsed_seconds"),
            "cpu_core_seconds": receipt.get("cpu_core_seconds"),
            "gpu_seconds": receipt.get("gpu_seconds"),
            "bytes": receipt.get("bytes"),
            "total_particles": receipt.get("total_particles"),
            "fluid_particles": receipt.get("fluid_particles"),
            "output_root": str(output_root),
        },
        "generated_xml": derived,
        "initial_fluid_sample_mass_gate": gate(derived["initial_fluid_sample_mass_kg"], target_mass),
        "per_mkfluid_diagnostics": per_mk_rows(source, derived, target_mass),
        "input_binding": input_binding,
        "scientific_qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "solver_started": False,
            "full_time_hdf5_read": False,
            "qualification_scope": "GenCase XML and receipt only",
        },
    }


def build_report() -> dict[str, Any]:
    manifest_path = require_file(MANIFEST, "v3 manifest")
    source_path = require_file(SOURCE_XML, "CURRENT F2-S1 source generated XML")
    manifest = load_json(manifest_path)
    source = parse_generated_xml(source_path)
    target_mass = source["initial_fluid_sample_mass_kg"]
    results = [audit_case(record, source, target_mass) for record in manifest["cases"]]
    counts: dict[str, int] = {}
    for result in results:
        status = result["initial_fluid_sample_mass_gate"]["status"]
        counts[status] = counts.get(status, 0) + 1
    return {
        "schema": SCHEMA,
        "status": "COMPLETED_GENCASE_V3_AUDIT_ONLY",
        "generated_at_commit": git_commit(),
        "family_id": "F2",
        "sentinel_id": "F2-S1",
        "physical_case_id": manifest["physical_case_id"],
        "source": {
            "manifest": file_record(manifest_path),
            "current_source_generated_xml": source,
        },
        "policy": {
            "scope": "four bounded F2-S1 coarse same-origin phase candidates dp=0.01290, 0.01300, 0.01310, 0.01320",
            "whole_initial_mass_target_basis": "CURRENT Stage1 discrete generated sample mass; continuum box mass is not substituted",
            "whole_initial_mass_thresholds_pct": {"target": 1.0, "marginal_upper": 2.0, "hard_gt": 2.0},
            "per_mkfluid_rows": "diagnostic only; do not rescale particle mass and do not grant material/flux acceptance",
            "continuous_geometry_motion_control": "fixed by source-bound derived-input policy; only dp and generated motion filename vary",
            "solver_started": False,
            "full_time_hdf5_read": False,
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "summary": {
            "candidate_count": len(results),
            "whole_initial_mass_gate_counts": counts,
            "all_requests_source_bound": all(
                result["input_binding"]["physical_case_id_exact"]
                and result["input_binding"]["gencase_only"]
                and result["input_binding"]["motion_bytes_unchanged"]
                for result in results
            ),
            "any_hdf5_input": any(result["input_binding"]["contains_hdf5_input"] for result in results),
        },
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = build_report()
    atomic_json(args.output, report)
    print(json.dumps({"status": "PASS", "output": str(args.output), "summary": report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Audit the three completed information-gain GenCase probes.

This is a forward-only, small-XML audit.  It reads the immutable CURRENT
source XML, the three terminal GenCase XML/receipt pairs, and the copied
motion dependency where present.  It never reads native Part/HDF5 data, runs
a solver, or changes a particle mass.  Whole-initial fluid mass is compared
to the frozen CURRENT sample target; per-material rows and rigid-body fields
are reported separately and do not grant scientific qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any
from xml.etree import ElementTree as ET


REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
WRAPPER = Path(__file__).resolve()
SCHEMA = "ds02.stage2.infogain-gencase-audit.v2"
OUTPUT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_infogain_gencase_audit_v2.json"


CASES: tuple[dict[str, Any], ...] = (
    {
        "sentinel_id": "F1-S2",
        "family_id": "F1",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "candidate_label": "infogain_dp0p0185",
        "candidate_dp_m": 0.0185,
        "source_xml": DATA_ROOT / "families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027/prepared/F1_STAGE1_DUAL_H340_DP020.xml",
        "source_receipt": DATA_ROOT / "families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027/execution-receipt.json",
        "candidate_root": DATA_ROOT / "families/F1/F1_S2_SPATIAL_INFOGAIN_DP0p018500/f1-s2-spatial-infogain-dp0p018500-v4-primary-001",
        "source_target_mass_kg": 340.0,
        "source_grid_role": "CURRENT_DP0",
    },
    {
        "sentinel_id": "F6-S1",
        "family_id": "F6",
        "physical_case_id": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025",
        "candidate_label": "infogain_dp0p0215",
        "candidate_dp_m": 0.0215,
        "source_xml": DATA_ROOT / "families/F6/F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025/root-stage1-f6-omega-95p0-genuine-gencase-082/F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025.xml",
        "source_receipt": DATA_ROOT / "families/F6/F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025/root-stage1-f6-omega-95p0-genuine-gencase-082/execution-receipt.json",
        "candidate_root": DATA_ROOT / "families/F6/F6_S1_SPATIAL_INFOGAIN_DP0p021500/f6-s1-spatial-infogain-dp0p021500-v4-primary-001",
        "source_target_mass_kg": 5120.0,
        "source_grid_role": "CURRENT_DP0",
    },
    {
        "sentinel_id": "F7-S1",
        "family_id": "F7",
        "physical_case_id": "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1",
        "candidate_label": "infogain_dp0p0215",
        "candidate_dp_m": 0.0215,
        "source_xml": DATA_ROOT / "families/F7/F7_QUINTIC_VERIFIED_MOTION_ASSET_CLONES/root-quintic-verified-three-dp-actual-motion-asset-clones-024/prepared/coarse/F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE.xml",
        "source_receipt": DATA_ROOT / "families/F7/F7_QUINTIC_VERIFIED_MOTION_ASSET_CLONES/root-quintic-verified-three-dp-actual-motion-asset-clones-024/execution-receipt.json",
        "candidate_root": DATA_ROOT / "families/F7/F7_S1_SPATIAL_INFOGAIN_DP0p021500/f7-s1-spatial-infogain-dp0p021500-v4-primary-001",
        "source_target_mass_kg": 325.6,
        "source_grid_role": "CURRENT_DP0",
    },
)


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
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def tree_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def floats(values: list[str]) -> list[float]:
    result: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and not any(abs(number - old) <= 1.0e-14 * max(1.0, abs(number), abs(old)) for old in result):
            result.append(number)
    return result


def attrs(root: ET.Element, element_tag: str, attribute: str) -> list[str]:
    return [element.attrib[attribute] for element in root.iter() if tag(element) == element_tag and attribute in element.attrib]


def first_attr(root: ET.Element, element_tag: str, attribute: str) -> float | None:
    values = floats(attrs(root, element_tag, attribute))
    return values[0] if values else None


def parameter_map(root: ET.Element) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for element in root.iter():
        if tag(element) != "parameter" or "key" not in element.attrib or "value" not in element.attrib:
            continue
        result.setdefault(element.attrib["key"], []).append(element.attrib["value"])
    return result


def fluid_blocks(root: ET.Element) -> list[dict[str, Any]]:
    rows = []
    for element in root.iter():
        if tag(element) != "fluid" or "mkfluid" not in element.attrib or "count" not in element.attrib:
            continue
        try:
            count = int(element.attrib["count"])
        except ValueError:
            count = None
        rows.append({"mkfluid": element.attrib["mkfluid"], "count": count})
    return rows


def floating_contract(root: ET.Element) -> dict[str, Any]:
    # The explicit floating contract is the child of a <floating> definition.
    # Summary rows in generated.xml are retained separately as particle counts.
    floating = next((e for e in root.iter() if tag(e) == "floating" and e.find("massbody") is not None), None)
    if floating is None:
        return {
            "present": False,
            "massbody_kg": None,
            "center_m": None,
            "inertia_diag_kg_m2": None,
            "floating_particle_count": None,
        }
    massbody = floating.find("massbody")
    center = floating.find("center")
    inertia = floating.find("inertia")
    particle_counts = []
    for element in root.iter():
        if tag(element) == "floating" and "mkbound" in element.attrib and "count" in element.attrib:
            try:
                particle_counts.append(int(element.attrib["count"]))
            except ValueError:
                pass
    return {
        "present": True,
        "massbody_kg": float(massbody.attrib["value"]) if massbody is not None and "value" in massbody.attrib else None,
        "center_m": [float(center.attrib[axis]) for axis in ("x", "y", "z")] if center is not None and all(axis in center.attrib for axis in ("x", "y", "z")) else None,
        "inertia_diag_kg_m2": [float(inertia.attrib[axis]) for axis in ("x", "y", "z")] if inertia is not None and all(axis in inertia.attrib for axis in ("x", "y", "z")) else None,
        "floating_particle_count": sum(particle_counts) if particle_counts else None,
    }


def parse_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    massfluid_values = floats(attrs(root, "massfluid", "value"))
    blocks = fluid_blocks(root)
    if len(massfluid_values) != 1:
        raise ValueError(f"{path}: expected one unique massfluid value, found {massfluid_values}")
    massfluid = massfluid_values[0]
    by_mk: dict[str, dict[str, Any]] = {}
    for block in blocks:
        count = block["count"]
        if count is None:
            continue
        by_mk[block["mkfluid"]] = {
            "count": count,
            "sample_mass_kg": count * massfluid,
        }
    gravity = [first_attr(root, "gravity", axis) for axis in ("x", "y", "z")]
    motion_files = [e.attrib["name"] for e in root.iter() if tag(e) == "file" and "name" in e.attrib]
    floating_counts = []
    for element in root.iter():
        if tag(element) == "floating" and "mkbound" in element.attrib and "count" in element.attrib:
            try:
                floating_counts.append({"mkbound": element.attrib["mkbound"], "count": int(element.attrib["count"])})
            except ValueError:
                floating_counts.append({"mkbound": element.attrib["mkbound"], "count": None})
    return {
        "file": file_record(path),
        "definition_dp_m": first_attr(root, "definition", "dp"),
        "h_m": first_attr(root, "h", "value"),
        "support_radius_m": (2.0 * first_attr(root, "h", "value")) if first_attr(root, "h", "value") is not None else None,
        "massfluid_kg": massfluid,
        "fluid_blocks": blocks,
        "fluid_by_mk": by_mk,
        "total_fluid_particles": sum(row["count"] for row in blocks if row["count"] is not None),
        "total_fluid_sample_mass_kg": sum(row["sample_mass_kg"] for row in by_mk.values()),
        "gravity_m_s2": gravity,
        "cfl": first_attr(root, "cflnumber", "value"),
        "parameters": parameter_map(root),
        "motion_files": motion_files,
        "floating_particle_blocks": floating_counts,
        "floating_contract": floating_contract(root),
    }


def relative(value: float | None, reference: float | None) -> float | None:
    if value is None or reference in (None, 0.0):
        return None
    return (value - reference) / reference


def mass_gate(error: float | None) -> str:
    if error is None:
        return "UNKNOWN"
    if abs(error) <= 0.01:
        return "PASS_TARGET_1PCT_DIAGNOSTIC"
    if abs(error) <= 0.02:
        return "MARGINAL_1_TO_2PCT"
    return "HARD_FAIL_GT2PCT"


def compare_contract(source: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    body_source = source["floating_contract"]
    body_candidate = candidate["floating_contract"]
    if body_source["present"] != body_candidate["present"]:
        body_status = "FAIL_PRESENCE_MISMATCH"
    elif not body_source["present"]:
        body_status = "NOT_APPLICABLE"
    else:
        mass_delta = abs(body_candidate["massbody_kg"] - body_source["massbody_kg"])
        center_delta = [abs(a - b) for a, b in zip(body_candidate["center_m"], body_source["center_m"])]
        inertia_delta = [abs(a - b) for a, b in zip(body_candidate["inertia_diag_kg_m2"], body_source["inertia_diag_kg_m2"])]
        body_status = "PASS_EXACT_XML_CONTRACT" if mass_delta <= 1.0e-9 and max(center_delta) <= 1.0e-9 and max(inertia_delta) <= 5.0e-9 else "FAIL_XML_CONTRACT_DIFFERENCE"
    source_params = source["parameters"]
    candidate_params = candidate["parameters"]
    parameter_diffs = {}
    for key in sorted(set(source_params) | set(candidate_params)):
        if source_params.get(key) != candidate_params.get(key):
            parameter_diffs[key] = {"source": source_params.get(key), "candidate": candidate_params.get(key)}
    return {
        "gravity_equal": source["gravity_m_s2"] == candidate["gravity_m_s2"],
        "cfl_equal": source["cfl"] == candidate["cfl"],
        "motion_file_names_equal": source["motion_files"] == candidate["motion_files"],
        "parameter_differences": parameter_diffs,
        "h_delta_m": candidate["h_m"] - source["h_m"] if source["h_m"] is not None and candidate["h_m"] is not None else None,
        "h_relative_error": relative(candidate["h_m"], source["h_m"]),
        "support_radius_delta_m": candidate["support_radius_m"] - source["support_radius_m"] if source["support_radius_m"] is not None and candidate["support_radius_m"] is not None else None,
        "rigid_body": {
            "source": body_source,
            "candidate": body_candidate,
            "status": body_status,
        },
        "geometry_control_status": "PASS_DECLARED_CONTROL_FIELDS_EQUAL_EXCEPT_INTENTIONAL_DP_DERIVED_H_MASS_COUNT" if not parameter_diffs and source["gravity_m_s2"] == candidate["gravity_m_s2"] and source["cfl"] == candidate["cfl"] and source["motion_files"] == candidate["motion_files"] else "UNKNOWN_CONTROL_OR_PARAMETER_DIFFERENCE",
    }


def motion_dependency(candidate_root: Path, source_xml: Path, source: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    names = sorted(set(source["motion_files"] + candidate["motion_files"]))
    rows = []
    for name in names:
        source_file = source_xml.parent / name
        candidate_file = candidate_root / name
        row = {"name": name, "source": file_record(source_file) if source_file.is_file() else None, "candidate": file_record(candidate_file) if candidate_file.is_file() else None}
        row["byte_identical"] = bool(row["source"] and row["candidate"] and row["source"]["sha256"] == row["candidate"]["sha256"])
        rows.append(row)
    return {"status": "NOT_APPLICABLE" if not names else ("PASS" if all(row["byte_identical"] for row in rows) else "UNKNOWN_OR_MISMATCH"), "files": rows}


def audit_case(spec: dict[str, Any]) -> dict[str, Any]:
    source_xml = spec["source_xml"]
    source_receipt = spec["source_receipt"]
    candidate_root = spec["candidate_root"]
    candidate_xml = candidate_root / "generated.xml"
    candidate_receipt = candidate_root / "execution-receipt.json"
    source = parse_xml(source_xml)
    candidate = parse_xml(candidate_xml)
    receipt = json.loads(candidate_receipt.read_text(encoding="utf-8"))
    source_receipt_data = json.loads(source_receipt.read_text(encoding="utf-8"))
    total_error = relative(candidate["total_fluid_sample_mass_kg"], spec["source_target_mass_kg"])
    per_material = []
    for mk in sorted(set(source["fluid_by_mk"]) | set(candidate["fluid_by_mk"])):
        source_row = source["fluid_by_mk"].get(mk)
        candidate_row = candidate["fluid_by_mk"].get(mk)
        if source_row is None or candidate_row is None:
            per_material.append({"mkfluid": mk, "status": "UNKNOWN_MK_MISSING", "source": source_row, "candidate": candidate_row})
            continue
        error = relative(candidate_row["sample_mass_kg"], source_row["sample_mass_kg"])
        per_material.append({"mkfluid": mk, "source": source_row, "candidate": candidate_row, "error_fraction_vs_source_mk": error, "error_pct_vs_source_mk": error * 100.0 if error is not None else None, "whole_initial_fraction_of_source": (candidate_row["sample_mass_kg"] - source_row["sample_mass_kg"]) / spec["source_target_mass_kg"]})
    input_hashes_match = receipt.get("input_hashes_at_launch") == receipt.get("input_hashes_after_run")
    tree_size = tree_bytes(candidate_root)
    contract = compare_contract(source, candidate)
    return {
        "sentinel_id": spec["sentinel_id"],
        "family_id": spec["family_id"],
        "physical_case_id": spec["physical_case_id"],
        "candidate_label": spec["candidate_label"],
        "candidate_dp_m": spec["candidate_dp_m"],
        "source": source,
        "candidate": candidate,
        "whole_initial_mass": {
            "source_sample_mass_target_kg": spec["source_target_mass_kg"],
            "candidate_sample_mass_kg": candidate["total_fluid_sample_mass_kg"],
            "delta_kg": candidate["total_fluid_sample_mass_kg"] - spec["source_target_mass_kg"],
            "error_fraction": total_error,
            "error_pct": total_error * 100.0 if total_error is not None else None,
            "gate": mass_gate(total_error),
            "gate_basis": "frozen CURRENT discrete sample mass; continuum volume is not substituted",
        },
        "per_material_diagnostics": per_material,
        "geometry_control_h_rigid_comparison": contract,
        "motion_dependency": motion_dependency(candidate_root, source_xml, source, candidate),
        "candidate_receipt": {
            "file": file_record(candidate_receipt),
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "termination_reason": receipt.get("termination_reason"),
            "elapsed_seconds": receipt.get("elapsed_seconds"),
            "cpu_core_seconds": receipt.get("cpu_core_seconds"),
            "gpu_seconds": receipt.get("gpu_seconds"),
            "receipt_bytes": receipt.get("bytes"),
            "terminal_storage_guard": receipt.get("terminal_storage_guard"),
            "actual_output_tree_bytes": tree_size,
            "input_digest_stable": input_hashes_match,
            "request_sha256": receipt.get("request_sha256"),
            "git_at_launch": receipt.get("git_at_launch"),
            "runner_source": receipt.get("runner_source"),
            "command": receipt.get("command"),
        },
        "source_receipt": {"file": file_record(source_receipt), "status": source_receipt_data.get("status"), "returncode": source_receipt_data.get("returncode")},
        "scientific_qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "solver_started": False,
            "full_time_native_read": False,
            "note": "GenCase XML quality/H/rigid contract evidence is preparation evidence only; it does not qualify dynamics, time/output, or observers.",
        },
    }


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    results = [audit_case(spec) for spec in CASES]
    report = {
        "schema": SCHEMA,
        "status": "COMPLETED_SMALL_XML_RECEIPT_AUDIT",
        "generated_at_commit": git_commit(),
        "audit_wrapper": file_record(WRAPPER),
        "policy": {
            "scope": "F1-S2/F6-S1/F7-S1 information-gain GenCase outputs only",
            "whole_initial_mass_thresholds": {"target_pct": 1.0, "marginal_upper_pct": 2.0, "hard_gt_pct": 2.0},
            "per_material": "diagnostic; never substitutes for frozen whole-initial task budget",
            "floating_semantics": "floating particle sample count*massfluid is separate from physical massbody/inertia/center",
            "no_mass_rescale": True,
            "no_native_or_hdf5_read": True,
            "solver_started": False,
            "QI_QN_QE": "UNKNOWN",
        },
        "summary": {
            "case_count": len(results),
            "whole_initial_mass_gate_counts": {gate: sum(row["whole_initial_mass"]["gate"] == gate for row in results) for gate in ("PASS_TARGET_1PCT_DIAGNOSTIC", "MARGINAL_1_TO_2PCT", "HARD_FAIL_GT2PCT", "UNKNOWN")},
            "rigid_contract_statuses": {status: sum(row["geometry_control_h_rigid_comparison"]["rigid_body"]["status"] == status for row in results) for status in ("PASS_EXACT_XML_CONTRACT", "NOT_APPLICABLE", "FAIL_PRESENCE_MISMATCH", "FAIL_XML_CONTRACT_DIFFERENCE")},
        },
        "results": results,
    }
    atomic_json(args.output, report)
    print(json.dumps({"status": report["status"], "output": str(args.output), "summary": report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

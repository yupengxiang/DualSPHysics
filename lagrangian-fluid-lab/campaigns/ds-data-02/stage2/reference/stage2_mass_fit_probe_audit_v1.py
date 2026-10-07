#!/usr/bin/env python3
"""Audit completed mass-fit GenCase receipts without reading solver output.

The audit binds each request to its guarded GenCase receipt and parses only the
new generated XML.  Fluid mass is summed over every ``<fluid mkfluid=...>``
block.  Floating particle mass and rigid-body mass/inertia are kept separate;
the latter is never substituted into the fluid sample-mass gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from xml.etree import ElementTree as ET


REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-mass-fit-probe-v1"
QUALITY_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_reference_quality_cost_v2.json"
PREP_MANIFEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_mass_fit_probe_inputs_v1/manifest.json"
OUTPUT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_mass_fit_probe_results_v1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def unique_numeric(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def parse_generated(path: Path) -> dict[str, Any]:
    root = ET.fromstring(path.read_bytes())
    fluid_blocks: list[dict[str, Any]] = []
    floating_blocks: list[dict[str, Any]] = []
    massfluid_values: list[str] = []
    masspart_values: list[str] = []
    massbody_values: list[str] = []
    inertia_values = {axis: [] for axis in ("x", "y", "z")}
    dp_values: list[str] = []
    h_values: list[str] = []
    for element in root.iter():
        tag = local_tag(element)
        if tag == "fluid" and "mkfluid" in element.attrib and "count" in element.attrib:
            try:
                count: int | str = int(element.attrib["count"])
            except ValueError:
                count = "UNKNOWN"
            fluid_blocks.append({"mkfluid": element.attrib.get("mkfluid", "UNKNOWN"), "count": count})
        if tag == "floating" and "count" in element.attrib:
            try:
                count: int | str = int(element.attrib["count"])
            except ValueError:
                count = "UNKNOWN"
            floating_blocks.append({"mkbound": element.attrib.get("mkbound", "UNKNOWN"), "count": count})
        if tag == "massfluid" and "value" in element.attrib:
            massfluid_values.append(element.attrib["value"])
        if tag == "masspart" and "value" in element.attrib:
            masspart_values.append(element.attrib["value"])
        if tag == "massbody" and "value" in element.attrib:
            massbody_values.append(element.attrib["value"])
        if tag == "inertia":
            for axis in inertia_values:
                if axis in element.attrib:
                    inertia_values[axis].append(element.attrib[axis])
        if tag == "definition" and "dp" in element.attrib:
            dp_values.append(element.attrib["dp"])
        if tag == "h" and "value" in element.attrib:
            h_values.append(element.attrib["value"])
    counts = [item["count"] for item in fluid_blocks]
    masses = unique_numeric(massfluid_values)
    sample_mass: float | str
    total_fluid: int | str
    if not counts or any(not isinstance(count, int) for count in counts):
        total_fluid = "UNKNOWN"
        sample_mass = "UNKNOWN"
    elif len(masses) != 1 or number(masses[0]) is None:
        total_fluid = sum(counts)
        sample_mass = "UNKNOWN"
    else:
        total_fluid = sum(counts)
        sample_mass = total_fluid * float(masses[0])
    return {
        "fluid_blocks": fluid_blocks,
        "total_fluid_particles": total_fluid,
        "massfluid_values": massfluid_values,
        "sample_mass_kg": sample_mass,
        "floating_blocks": floating_blocks,
        "floating_masspart_values": masspart_values,
        "rigid_body_massbody_values": massbody_values,
        "rigid_body_inertia_values": inertia_values,
        "dp_values": dp_values,
        "h_values": h_values,
        "floating_mass_semantics": "floating particle masspart is separate from physical rigid massbody/inertia; no substitution",
    }


def normalized_geometry_hash(path: Path) -> str:
    data = path.read_bytes()
    normalized, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb'\1<DP>\2', data, count=1)
    if count != 1:
        raise ValueError(f"expected one definition@dp: {path}")
    return hashlib.sha256(normalized).hexdigest()


def quality_label(deviation: float) -> str:
    absolute = abs(deviation)
    if absolute <= 1.0 + 1e-12:
        return "PASS_TARGET_1PCT"
    if absolute <= 2.0 + 1e-12:
        return "MARGINAL_1_TO_2PCT"
    return "HARD_FAIL_GT2PCT"


def audit_one(request_path: Path, quality_by_key: dict[tuple[str, str], dict[str, Any]], prep_by_key: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    family = request["family_id"]
    case_id = request["case_id"]
    attempt_id = request["attempt_id"]
    receipt_path = DATA_ROOT / "families" / family / case_id / attempt_id / "execution-receipt.json"
    if not receipt_path.is_file():
        raise FileNotFoundError(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    output_root = Path(receipt["output_root"])
    generated = output_root / "generated.xml"
    generated_bi4 = output_root / "generated.bi4"
    if not generated.is_file() or not generated_bi4.is_file():
        raise FileNotFoundError(f"GenCase outputs missing for {case_id}: {output_root}")
    generated_meta = parse_generated(generated)
    key = (request["scope"]["sentinel_id"], request["scope"].get("three_spatial_grid_label", request.get("label", "UNKNOWN")))
    # The request itself carries the mass-fit row; derive the lookup by the
    # sentinel and case label encoded in the preparation manifest.
    prep = prep_by_key.get((request["scope"]["sentinel_id"], request["mass_fit_prediction"].get("prior_candidate_dp_m")))
    if prep is None:
        prep = next((item for (sid, _), item in prep_by_key.items() if sid == request["scope"]["sentinel_id"] and item["candidate"]["case_id"] == case_id), None)
    if prep is None:
        raise ValueError(f"preparation record missing for {case_id}")
    candidate = prep["candidate"]
    sid = candidate["sentinel_id"]
    label = candidate["label"]
    quality = quality_by_key[(sid, label)]
    source_mass = float(quality["mass_diagnostic"]["source_sample_mass_kg"])
    actual_mass = generated_meta["sample_mass_kg"]
    if not isinstance(actual_mass, (int, float)):
        deviation = "UNKNOWN"
        gate = "UNKNOWN"
    else:
        deviation = (float(actual_mass) - source_mass) / source_mass * 100.0
        gate = quality_label(deviation)
    request_hash = sha256_file(request_path)
    derived_def = Path(candidate["derived_inputs"]["definition"]["path"])
    normalized_match = normalized_geometry_hash(derived_def) == candidate["continuous_vs_intentional"]["source_definition_normalized_hash"]
    dependencies_match = all(item["byte_identical"] for item in candidate["derived_inputs"]["relative_dependencies"])
    return {
        "case_id": case_id,
        "sentinel_id": sid,
        "family_id": family,
        "physical_case_id": candidate["physical_case_id"],
        "label": label,
        "request": record(request_path) | {"request_sha256_in_receipt": receipt.get("request_sha256"), "request_sha256_matches_receipt": receipt.get("request_sha256") == request_hash},
        "receipt": record(receipt_path) | {
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "termination_reason": receipt.get("termination_reason"),
            "elapsed_seconds": receipt.get("elapsed_seconds"),
            "cpu_core_seconds": receipt.get("cpu_core_seconds"),
            "gpu_seconds": receipt.get("gpu_seconds"),
            "output_root": str(output_root),
            "bytes": receipt.get("bytes"),
            "total_particles_from_receipt": receipt.get("total_particles"),
            "fluid_particles_from_receipt": receipt.get("fluid_particles"),
        },
        "generated_xml": record(generated),
        "generated_bi4": record(generated_bi4),
        "generated_semantics": generated_meta,
        "mass_gate": {
            "source_sample_mass_kg": source_mass,
            "actual_generated_xml_sample_mass_kg": actual_mass,
            "deviation_pct_vs_source": deviation,
            "gate": gate,
            "prior_candidate_deviation_pct": quality["mass_diagnostic"]["deviation_pct_vs_source"],
            "meaning": "initial fluid particle mass diagnostic only; not QI/QN/QE or scientific qualification",
        },
        "prediction": candidate["prediction"],
        "continuous_vs_intentional": {
            "normalized_geometry_unchanged": normalized_match,
            "dependencies_byte_identical": dependencies_match,
            "motion_or_acceleration_changed": False,
            "intentional": ["dp", "h/massfluid/count/lattice phase measured by generated XML"],
        },
        "historical_controls": candidate["historical_controls"],
        "status": "PASS_GENCACE_AND_AUDIT" if receipt.get("status") == "completed" and receipt.get("returncode") == 0 else "FAIL_GENCACE",
        "solver_started": False,
        "full_time_hdf5_read": False,
        "gpu_lease": "none",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    quality = json.loads(QUALITY_PATH.read_text(encoding="utf-8"))
    quality_by_key = {(row["sentinel_id"], row["label"]): row for row in quality["candidate_quality_and_controls"]}
    prep = json.loads(PREP_MANIFEST.read_text(encoding="utf-8"))
    prep_by_key = {(item["candidate"]["sentinel_id"], item["candidate"]["case_id"]): item for item in prep["records"]}
    results = []
    for request_path in sorted(REQUEST_ROOT.glob("*.json")):
        request = json.loads(request_path.read_text(encoding="utf-8"))
        item = prep_by_key.get((request["scope"]["sentinel_id"], request["case_id"]))
        if item is None:
            raise ValueError(f"request not present in preparation manifest: {request_path}")
        results.append(audit_one(request_path, quality_by_key, prep_by_key))
    counts: dict[str, int] = {}
    for item in results:
        gate = item["mass_gate"]["gate"]
        counts[gate] = counts.get(gate, 0) + 1
    output = {
        "schema": "ds02.stage2.mass-fit-probe-results.v1",
        "status": "COMPLETED_GENCACE_AUDIT_ONLY",
        "quality_source": record(QUALITY_PATH),
        "preparation_manifest": record(PREP_MANIFEST),
        "request_count": len(results),
        "gate_counts": counts,
        "policy": {
            "fluid_mass": "sum every generated XML fluid block with mkfluid/count times the common massfluid value",
            "thresholds": {"target_abs_pct": 1.0, "marginal_upper_abs_pct": 2.0, "hard_gt_abs_pct": 2.0},
            "floating": "sample masspart and rigid massbody/inertia are separate; never substitute body mass for fluid sample mass",
            "scientific_status": "QI/QN/QE UNKNOWN; GenCase mass compatibility does not qualify geometry, dynamics, time, output, or observer agreement",
            "solver_started": False,
            "full_time_hdf5_read": False,
        },
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "request_count": len(results), "gate_counts": counts, "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

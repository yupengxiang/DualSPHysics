#!/usr/bin/env python3
"""Audit generated F4 endpoint XML against a Root-produced initial QA report.

This worker is intentionally downstream of GenCase.  It does not decode BI4,
read H5, load particle arrays, generate CSV, or run a solver.  Root supplies a
runtime manifest after each strict GenCase/initial-native audit; the worker
checks the generated all-numeric XML and the QA report's native UID/type,
support-weight, 3-D, and clearance/face-coverage fields.  A passing audit is
an input-integrity receipt only and grants no numerical or visual acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "ds02.f4.drop-gap-initial-native-audit-result.v1"
REQUIRED_QA_CHECKS = (
    "finite_unique_complete_ids",
    "complete_type_partition",
    "true_3d",
    "all_source_population_checks",
    "finite_tank_face_coverage",
    "gencase_completed",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parameter_map(root: ET.Element) -> dict[str, str]:
    return {
        str(node.attrib["key"]): str(node.attrib["value"])
        for node in root.findall("execution/parameters/parameter")
        if "key" in node.attrib and "value" in node.attrib
    }


def xml_summary(xml_path: Path, endpoint: dict[str, Any], mother_recipe: dict[str, Any]) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    geometry = root.find("casedef/geometry/definition")
    particles = root.find("execution/particles")
    constants = root.find("execution/constants")
    if geometry is None or particles is None or constants is None:
        raise ValueError(f"generated XML lacks required all-numeric sections: {xml_path}")
    params = parameter_map(root)
    fluid_blocks = particles.findall("fluid")
    fixed = particles.find("fixed")
    if fixed is None or len(fluid_blocks) != 2:
        raise ValueError(f"generated XML has unexpected fixed/fluid partition: {xml_path}")
    fixed_count = int(fixed.attrib["count"])
    fluid_count = sum(int(node.attrib["count"]) for node in fluid_blocks)
    total = int(particles.attrib["np"])
    type_ok = int(fixed.attrib["mk"]) == 17 and all(int(node.attrib["mk"]) in (1, 2) for node in fluid_blocks)

    target_literal = str(endpoint["drop_point_z_literal"])
    drop_point_literals: list[str] = []
    mainlist = root.findall("casedef/geometry/commands/mainlist")
    for main in mainlist:
        active_mk: str | None = None
        for node in main:
            if node.tag == "setmkfluid":
                active_mk = node.attrib.get("mk")
            elif node.tag == "setmkbound":
                active_mk = None
            elif node.tag == "drawbox" and active_mk == "1":
                point = node.find("point")
                if point is not None and "z" in point.attrib:
                    drop_point_literals.append(str(point.attrib["z"]))
    target_value = finite_float(target_literal)
    observed_values = [finite_float(value) for value in drop_point_literals]
    drop_z_numeric_match = (
        target_value is not None
        and len(observed_values) == 1
        and observed_values[0] is not None
        and math.isclose(observed_values[0], target_value, rel_tol=0.0, abs_tol=1e-15)
    )
    xml_checks = {
        "dp_is_source_dp010": geometry.attrib.get("dp") == "0.01",
        "time_max_is_source_1p2": params.get("TimeMax") == "1.2",
        "save_interval_is_source_0p001": params.get("TimeOut") == "0.001",
        "drop_z_is_requested_value": drop_z_numeric_match,
        "fixed_fluid_type_partition_is_source": type_ok,
        "total_matches_fixed_plus_fluid": total == fixed_count + fluid_count,
        "total_matches_source_recipe": total == int(mother_recipe["source_particle_counts"]["total"]),
        "fixed_matches_source_recipe": fixed_count == int(mother_recipe["source_particle_counts"]["fixed"]),
        "fluid_matches_source_recipe": fluid_count == int(mother_recipe["source_particle_counts"]["fluid"]),
    }
    return {
        "xml_sha256": sha256(xml_path),
        "generated_xml": str(xml_path),
        "geometry_dp_m": geometry.attrib.get("dp"),
        "time_max_s": params.get("TimeMax"),
        "time_out_s": params.get("TimeOut"),
        "particles": {
            "total": total,
            "fixed": fixed_count,
            "fluid": fluid_count,
            "fluid_blocks": [dict(node.attrib) for node in fluid_blocks],
            "native_types": {"fixed": [0], "fluid": [3], "moving": []},
        },
        "mass_policy": "native body support weights; physical mass is rho*dp^3; no continuum rescale",
        "massbound_kg": constants.find("massbound").attrib.get("value") if constants.find("massbound") is not None else None,
        "massfluid_kg": constants.find("massfluid").attrib.get("value") if constants.find("massfluid") is not None else None,
        "drop_point_z_literals": drop_point_literals,
        "requested_drop_point_z_literal": target_literal,
        "drop_point_z_literal_exact_match": drop_point_literals == [target_literal],
        "xml_checks": xml_checks,
    }


def qa_summary(qa_path: Path, expected_total: int, expected_fluid: int, expected_massfluid: float | None) -> dict[str, Any]:
    qa = load_json(qa_path)
    checks = qa.get("checks")
    if not isinstance(checks, dict):
        raise ValueError(f"initial QA report lacks checks: {qa_path}")
    missing = [name for name in REQUIRED_QA_CHECKS if name not in checks]
    if missing:
        raise ValueError(f"initial QA report lacks required checks {missing}: {qa_path}")
    source_rows = qa.get("source_rows")
    if not isinstance(source_rows, list) or not source_rows:
        raise ValueError(f"initial QA report lacks source_rows: {qa_path}")
    observed_total = int(qa.get("total_particles"))
    observed_fluid = int(qa.get("fluid_particles"))
    row_count = sum(int(row["fluid_count"]) for row in source_rows)
    row_mass = sum(float(row["native_mass_kg"]) for row in source_rows)
    checks_out = {
        name: bool(checks.get(name)) for name in REQUIRED_QA_CHECKS
    }
    checks_out.update(
        {
            "qa_total_matches_generated_xml": observed_total == expected_total,
            "qa_fluid_matches_generated_xml": observed_fluid == expected_fluid,
            "source_rows_sum_to_fluid": row_count == observed_fluid,
            "source_rows_have_native_support_weights": all(
                finite_float(row.get("native_mass_kg")) is not None for row in source_rows
            ),
            "native_support_weight_sum_matches_xml_mass": (
                expected_massfluid is not None
                and math.isclose(row_mass, expected_fluid * expected_massfluid, rel_tol=1e-9, abs_tol=1e-9)
            ),
            "qa_reports_no_precision_acceptance": qa.get("q_n_status") == "not_assessed"
            and qa.get("production_approval") == "none",
        }
    )
    return {
        "initial_qa": str(qa_path),
        "initial_qa_sha256": sha256(qa_path),
        "qa_case_id": qa.get("case_id"),
        "uid_type_weight_clearance_observations": {
            "unique_complete_uid_check": bool(checks.get("finite_unique_complete_ids")),
            "complete_type_partition_check": bool(checks.get("complete_type_partition")),
            "native_support_weight_checks": bool(checks.get("all_source_population_checks")),
            "three_dimensional_check": bool(checks.get("true_3d")),
            "tank_clearance_face_coverage_check": bool(checks.get("finite_tank_face_coverage")),
        },
        "reported_total_particles": observed_total,
        "reported_fluid_particles": observed_fluid,
        "source_rows": source_rows,
        "finite_tank_face_coverage": qa.get("finite_tank_face_coverage"),
        "qa_checks": checks_out,
    }


def audit(plan_path: Path, runtime_manifest_path: Path, output_path: Path) -> int:
    plan = load_json(plan_path)
    if plan.get("stage_contract", {}).get("launch_allowed") is not False:
        raise RuntimeError("endpoint plan must keep launch_allowed=false")
    manifest = load_json(runtime_manifest_path)
    rows = manifest.get("endpoints")
    if not isinstance(rows, list):
        raise ValueError("runtime manifest must contain an endpoints list")
    by_id = {row.get("endpoint_id"): row for row in rows if isinstance(row, dict)}
    recipe = plan["mother_binding"]["source_recipe"]
    endpoint_results: list[dict[str, Any]] = []
    all_pass = True
    for endpoint in plan["endpoints"]:
        endpoint_id = endpoint["endpoint_id"]
        runtime = by_id.get(endpoint_id)
        if runtime is None:
            raise ValueError(f"runtime manifest missing endpoint {endpoint_id}")
        xml_path = Path(runtime["generated_xml"])
        qa_path = Path(runtime["initial_qa_json"])
        if not xml_path.is_file() or not qa_path.is_file():
            raise FileNotFoundError(f"Root runtime inputs missing for {endpoint_id}")
        if runtime.get("generated_xml_sha256") and sha256(xml_path) != runtime["generated_xml_sha256"]:
            raise RuntimeError(f"runtime generated XML hash mismatch: {endpoint_id}")
        if runtime.get("initial_qa_json_sha256") and sha256(qa_path) != runtime["initial_qa_json_sha256"]:
            raise RuntimeError(f"runtime initial QA hash mismatch: {endpoint_id}")
        xml = xml_summary(xml_path, endpoint, recipe)
        expected_massfluid = finite_float(xml.get("massfluid_kg"))
        qa = qa_summary(
            qa_path,
            int(xml["particles"]["total"]),
            int(xml["particles"]["fluid"]),
            expected_massfluid,
        )
        checks = dict(xml["xml_checks"])
        checks.update(qa["qa_checks"])
        endpoint_pass = all(bool(value) for value in checks.values())
        all_pass = all_pass and endpoint_pass
        endpoint_results.append(
            {
                "endpoint_id": endpoint_id,
                "physical_condition_sha256": endpoint["physical_condition_sha256"],
                "generated_xml": xml,
                "initial_qa": qa,
                "checks": checks,
                "pass": endpoint_pass,
                "qualification_claim": "none",
            }
        )
    result = {
        "schema": SCHEMA,
        "family_id": plan["family_id"],
        "scope_id": plan["scope_id"],
        "source_plan": str(plan_path),
        "source_plan_sha256": sha256(plan_path),
        "runtime_manifest": str(runtime_manifest_path),
        "runtime_manifest_sha256": sha256(runtime_manifest_path),
        "endpoint_count": len(endpoint_results),
        "endpoints": endpoint_results,
        "pass": all_pass,
        "status": "initial-native-input-integrity-pass" if all_pass else "initial-native-input-integrity-fail",
        "read_policy": {
            "bi4": False,
            "h5": False,
            "particle_arrays": False,
            "csv": False,
            "generated_xml": True,
            "root_initial_qa_json": True,
        },
        "historical_negative_evidence": "preserved; this receipt does not assess spatial precision, q_n, or visual acceptance",
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
        "production_approval": "none",
        "launch_allowed": False,
    }
    write_json(output_path, result)
    return 0 if all_pass else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--runtime-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    return audit(args.plan, args.runtime_manifest, args.output)


if __name__ == "__main__":
    raise SystemExit(main())

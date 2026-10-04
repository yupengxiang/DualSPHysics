#!/usr/bin/env python3
"""Strict native initial-state QA for the two fresh F7 target-angle GenCase outputs.

The worker deliberately consumes only the actual 085 GenCase BI4/XML through the
official PartVTK exporter.  It verifies the source/forcing lineage before export,
then checks every exported particle UID, type, Mk, weight, density, velocity,
dimension, and coordinate overlap.  It records the native fluid mass beside the
continuum-envelope mass without applying a rescale.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import numpy as np


CSV_FIELDS = [
    "Pos.x [m]",
    "Pos.y [m]",
    "Pos.z [m]",
    "Zone",
    "Idp",
    "Type",
    "Mk",
    "Mass [kg]",
    "Vel.x [m/s]",
    "Vel.y [m/s]",
    "Vel.z [m/s]",
    "Rhop [kg/m^3]",
    "Press [Pa]",
]


def sha(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def require_hash(path: str | Path, expected: str, label: str) -> None:
    actual = sha(path)
    require(actual == expected, f"{label}: sha256 {actual} != registered {expected}")


def as_int(value: str | float, label: str) -> int:
    number = float(value)
    require(np.isfinite(number) and number == np.floor(number), f"{label} is not an integral finite value")
    return int(number)


def verify_forcing_lineage(binding: dict, case: dict) -> dict:
    forcing = binding["forcing_source"]
    require_hash(forcing["source_plan"], forcing["source_plan_sha256"], "source plan")
    require_hash(
        forcing["motion_preparation_report"],
        forcing["motion_preparation_report_sha256"],
        "motion preparation report",
    )
    require_hash(
        forcing["motion_preparation_receipt"],
        forcing["motion_preparation_receipt_sha256"],
        "motion preparation receipt",
    )
    prep_receipt = load_json(forcing["motion_preparation_receipt"])
    require(prep_receipt.get("status") == "completed", "motion preparation was not completed")
    require(prep_receipt.get("returncode") == 0, "motion preparation returncode is not zero")
    prep_report = load_json(forcing["motion_preparation_report"])
    require(prep_report.get("schema") == forcing["motion_preparation_schema"], "motion report schema changed")
    require(prep_report.get("source_plan_sha256") == forcing["source_plan_sha256"], "motion report source plan changed")
    endpoint = forcing["endpoint_metadata"][case["endpoint_id"]]
    require(endpoint["amplitude_deg"] == case["amplitude_deg"], "motion amplitude does not match endpoint")
    require(endpoint["motion_rows"] == case["expected"]["motion_rows"], "motion row count is not 12001")
    require(endpoint["physical_condition_sha256"] == case["physical_condition_sha256"], "physical condition hash changed")
    require(endpoint["source_definition_sha256"] == case["source_definition_sha256"], "source definition hash changed")
    require(endpoint["prepared_definition_sha256"] == case["prepared_definition_sha256"], "prepared definition hash changed")
    require(endpoint["motion_file_sha256"] == case["source_motion_sha256"], "prepared motion hash changed")
    require(endpoint["native_reader"] == "piecewise_linear_absolute_angle_increment", "native reader declaration changed")
    require(endpoint["native_sampled_regular"] == "not C2", "native sampled regularity was overclaimed")
    require(Path(endpoint["motion_file"]).resolve() == Path(case["source_motion"]).resolve(), "motion source path changed")
    return {
        "motion_preparation_completed": True,
        "source_plan_hash_verified": True,
        "endpoint_condition_hash_verified": True,
        "motion_rows_metadata_verified": True,
        "native_piecewise_linear_declared": True,
        "native_C2_claim": False,
    }


def verify_gencase_metadata(binding: dict, case: dict) -> dict:
    expected = case["expected"]
    receipt = load_json(case["gencase_receipt"])
    require(receipt.get("status") == "completed", f"{case['case_id']}: GenCase status is not completed")
    require(receipt.get("returncode") == 0, f"{case['case_id']}: GenCase returncode is not zero")
    require(receipt.get("total_particles") == expected["total_particles"], f"{case['case_id']}: total count changed")
    require(receipt.get("fluid_particles") == expected["fluid_particles"], f"{case['case_id']}: fluid count changed")
    require(receipt.get("solver_dimension_from_gencase") == expected["solver_dimension"], f"{case['case_id']}: GenCase is not 3D")

    report = load_json(case["prepared_input_report"])
    require(report.get("schema") == "ds02.root.actual-native-source-preflight.v1", f"{case['case_id']}: unexpected preflight schema")
    require(report.get("case_id") == case["case_id"], f"{case['case_id']}: preflight case mismatch")
    require(report.get("actual_total_particles") == expected["total_particles"], f"{case['case_id']}: report total changed")
    require(report.get("definition_sha256") == case["generated_definition_sha256"], f"{case['case_id']}: Def hash mismatch in report")
    require(report.get("xml_sha256") == case["generated_xml_sha256"], f"{case['case_id']}: XML hash mismatch in report")
    require(report.get("bi4_sha256") == case["generated_bi4_sha256"], f"{case['case_id']}: BI4 hash mismatch in report")
    counts = report.get("generated_xml_particle_counts", {})
    require(counts == {"fixed": 27495, "floating": 0, "fluid": 40700, "moving": 1984}, f"{case['case_id']}: generated count metadata changed")
    require(report.get("native_initial_typed_QA") == "pending actual arrays", f"{case['case_id']}: preflight already claims typed QA")
    require(report.get("production_approval") == "none", f"{case['case_id']}: production approval is not none")

    tree = ET.parse(case["generated_xml"]).getroot()
    constants = tree.find("./execution/constants")
    require(constants is not None, f"{case['case_id']}: generated constants missing")
    data2d = constants.find("data2d")
    require(data2d is not None and data2d.get("value") == "false", f"{case['case_id']}: generated XML is not 3D")
    dp = constants.find("dp")
    require(dp is not None and float(dp.get("value")) == expected["dp_m"], f"{case['case_id']}: dp changed")
    parameters = {node.get("key"): node.get("value") for node in tree.findall("./execution/parameters/parameter")}
    for key, value in {"Boundary": "1", "StepAlgorithm": "2", "Kernel": "2", "Visco": "0.05", "DensityDT": "3", "DensityDTvalue": "0.1", "TimeMax": "12", "TimeOut": "0.02"}.items():
        require(parameters.get(key) == value, f"{case['case_id']}: execution parameter {key} changed")
    particles = tree.find("./execution/particles")
    require(particles is not None, f"{case['case_id']}: particle summary missing")
    require(int(particles.get("np")) == expected["total_particles"], f"{case['case_id']}: XML np changed")
    require(int(particles.get("nbf")) == expected["fixed_particles"], f"{case['case_id']}: XML nbf changed")
    require(int(particles.get("nb")) == expected["fixed_particles"] + expected["moving_particles"], f"{case['case_id']}: XML nb changed")
    for block in expected["type_mk_blocks"]:
        node = particles.find(block["name"])
        require(node is not None, f"{case['case_id']}: XML {block['name']} block missing")
        require(int(node.get("begin")) == block["begin"], f"{case['case_id']}: XML {block['name']} begin changed")
        require(int(node.get("count")) == block["count"], f"{case['case_id']}: XML {block['name']} count changed")
        require(int(node.get("mk")) == block["mk"], f"{case['case_id']}: XML {block['name']} Mk changed")

    motion = tree.find("./execution/motion/objreal/mvrotfile")
    require(motion is not None, f"{case['case_id']}: generated execution motion missing")
    require(motion.get("duration") == "12", f"{case['case_id']}: motion duration changed")
    motion_file = motion.find("file")
    p1 = motion.find("axisp1")
    p2 = motion.find("axisp2")
    require(motion_file is not None and motion_file.get("name") == "motion_obstacle_quintic.dat", f"{case['case_id']}: forcing filename changed")
    require(p1 is not None and [p1.get(k) for k in ("x", "y", "z")] == ["-0.04", "0", "0.05"], f"{case['case_id']}: forcing p1 changed")
    require(p2 is not None and [p2.get(k) for k in ("x", "y", "z")] == ["-0.04", "0", "1.05"], f"{case['case_id']}: forcing p2 changed")
    return {
        "gencase_completed_zero": True,
        "gencase_counts_verified": True,
        "gencase_3d_verified": True,
        "generated_xml_hash_verified": True,
        "generated_bi4_hash_verified": True,
        "generated_definition_hash_verified": True,
        "generated_motion_binding_verified": True,
        "execution_parameters_verified": True,
    }


def verify_source_wet_obstacle(binding: dict, case: dict) -> dict:
    contract = binding["source_wet_obstacle_contract"]
    source_text = Path(case["source_definition"]).read_text()
    prepared_text = Path(case["prepared_definition"]).read_text()
    require(source_text == prepared_text, f"{case['case_id']}: prepared Def differs from source Def")
    for fragment in contract["required_definition_fragments"]:
        require(fragment in source_text, f"{case['case_id']}: wet-obstacle source fragment missing: {fragment}")
    require(source_text.count("Explicit native cell-center slab") == 4, f"{case['case_id']}: explicit wet slab count changed")
    require(source_text.count("<boxfill>solid</boxfill>") >= 4, f"{case['case_id']}: explicit solid wet slab markers missing")
    return {
        "source_definition_exact_to_prepared": True,
        "moving_obstacle_mk12_source": True,
        "explicit_wet_fluid_mk2_source": True,
        "explicit_wet_slab_count": 4,
        "motion_pivot_and_duration_source": True,
        "true_wet_obstacle_source_contract": True,
        "solver_dynamics_or_visual_acceptance": False,
    }


def export_csv(case: dict, output: Path, partvtk: str) -> tuple[np.ndarray, dict]:
    csv_path = output / f"{case['role']}-initial-all.csv"
    require(not csv_path.exists(), f"refusing to overwrite existing CSV: {csv_path}")
    before = sha(case["generated_bi4"])
    command = [
        partvtk,
        "-filedata", case["generated_bi4"],
        "-filexml", case["generated_xml"],
        "-threads:2",
        "-savecsv", str(csv_path),
        "-onlytype:+all",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone",
        "-csvsep:1",
    ]
    subprocess.run(command, cwd=str(output), check=True)
    require(sha(case["generated_bi4"]) == before, f"{case['case_id']}: PartVTK mutated BI4")
    require(csv_path.is_file(), f"{case['case_id']}: PartVTK did not produce CSV")
    with csv_path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = None
        for row in reader:
            if "Pos.x [m]" in row:
                header = row
                break
        require(header is not None, f"{case['case_id']}: official CSV header missing")
        indices = []
        for key in CSV_FIELDS:
            require(key in header, f"{case['case_id']}: official CSV field missing: {key}")
            indices.append(header.index(key))
        rows = np.loadtxt(handle, delimiter=",", usecols=indices, ndmin=2)
    return rows, {
        "official_csv": str(csv_path),
        "official_csv_sha256": sha(csv_path),
        "initial_bi4_sha256": before,
        "partvtk_command": command,
    }


def check_rows(binding: dict, case: dict, rows: np.ndarray) -> dict:
    expected = case["expected"]
    require(rows.shape == (expected["total_particles"], len(CSV_FIELDS)), f"{case['case_id']}: CSV shape {rows.shape} is not {(expected['total_particles'], len(CSV_FIELDS))}")
    require(bool(np.isfinite(rows).all()), f"{case['case_id']}: CSV contains nonfinite values")
    for column, name in zip((3, 4, 5, 6), ("Zone", "Idp", "Type", "Mk")):
        require(bool(np.equal(rows[:, column], np.floor(rows[:, column])).all()), f"{case['case_id']}: {name} contains nonintegral values")
    zone = rows[:, 3].astype(np.int64)
    idp = rows[:, 4].astype(np.int64)
    particle_type = rows[:, 5].astype(np.int64)
    mk = rows[:, 6].astype(np.int64)
    require(bool(np.equal(zone, 0).all()), f"{case['case_id']}: nonzero zones present")
    require(bool(np.array_equal(np.sort(idp), np.arange(expected["total_particles"]))), f"{case['case_id']}: Idp set is not exact 0..N-1")
    require(bool(np.unique(idp).size == expected["total_particles"]), f"{case['case_id']}: duplicate/lost Idp")
    # PartVTK normally emits Idp order, but the contract is per UID rather than
    # an incidental export order.  Normalize once, then apply every block and
    # spatial check to the UID-ordered rows.
    order = np.argsort(idp, kind="stable")
    rows = rows[order]
    zone = zone[order]
    idp = idp[order]
    particle_type = particle_type[order]
    mk = mk[order]
    require(bool(np.array_equal(idp, np.arange(expected["total_particles"]))), f"{case['case_id']}: UID normalization failed")

    block_checks = {}
    for block in expected["type_mk_blocks"]:
        start = block["begin"]
        stop = start + block["count"]
        block_type = particle_type[start:stop]
        block_mk = mk[start:stop]
        require(bool(np.equal(block_type, block["type"]).all()), f"{case['case_id']}: {block['name']} Type mismatch")
        require(bool(np.equal(block_mk, block["mk"]).all()), f"{case['case_id']}: {block['name']} Mk mismatch")
        block_checks[block["name"]] = {
            "begin": start,
            "count": block["count"],
            "type": block["type"],
            "mk": block["mk"],
            "uid_range_exact": True,
            "type_exact": True,
            "mk_exact": True,
        }
    require(bool(np.all(rows[:, 7] > 0)), f"{case['case_id']}: nonpositive native weight")
    require(bool(np.all(rows[:, 11] > 0)), f"{case['case_id']}: nonpositive density")
    require(float(np.max(np.abs(rows[:, 8:11]))) <= expected["velocity_zero_tolerance_m_per_s"], f"{case['case_id']}: nonzero initial velocity")

    coords = rows[:, :3]
    unique_coords = np.unique(coords, axis=0)
    require(unique_coords.shape[0] == rows.shape[0], f"{case['case_id']}: initial coordinates overlap")
    sets = []
    for block in expected["type_mk_blocks"]:
        start = block["begin"]
        stop = start + block["count"]
        sets.append({tuple(point) for point in coords[start:stop]})
    pairwise_overlap = {
        "fixed_moving": len(sets[0].intersection(sets[1])),
        "fixed_fluid": len(sets[0].intersection(sets[2])),
        "moving_fluid": len(sets[1].intersection(sets[2])),
    }
    require(all(value == 0 for value in pairwise_overlap.values()), f"{case['case_id']}: typed initial spatial overlap {pairwise_overlap}")

    fluid = particle_type == 3
    require(int(fluid.sum()) == expected["fluid_particles"], f"{case['case_id']}: fluid Type count changed")
    fluid_coords = coords[fluid]
    require(all(np.unique(fluid_coords[:, axis]).size > 1 for axis in range(3)), f"{case['case_id']}: fluid is not genuinely 3D")
    fluid_mass = float(rows[fluid, 7].sum())
    mass_error = fluid_mass - expected["native_fluid_mass_kg"]
    require(np.isfinite(fluid_mass) and abs(mass_error) <= expected["mass_tolerance_kg"], f"{case['case_id']}: native fluid mass {fluid_mass} differs from registered {expected['native_fluid_mass_kg']}")
    continuum_delta = fluid_mass - expected["continuum_envelope_mass_kg"]

    return {
        "row_shape_exact": True,
        "all_13_fields_finite": True,
        "zone_integral_and_zero": True,
        "uid_exact_sorted_unique": True,
        "native_type_mk_blocks": block_checks,
        "all_native_weights_positive": True,
        "all_native_densities_positive": True,
        "initial_velocity_zero_within_tolerance": True,
        "global_coordinate_unique": True,
        "pairwise_initial_overlap_counts": pairwise_overlap,
        "no_initial_overlap": True,
        "fluid_count_exact": True,
        "actual_3d_fluid_envelope": [fluid_coords.min(axis=0).tolist(), fluid_coords.max(axis=0).tolist()],
        "actual_3d": True,
        "official_CSV_fluid_mass_sum_kg": fluid_mass,
        "registered_native_fluid_mass_kg": expected["native_fluid_mass_kg"],
        "native_mass_difference_kg": mass_error,
        "continuum_envelope_mass_kg": expected["continuum_envelope_mass_kg"],
        "native_minus_continuum_mass_kg": continuum_delta,
        "mass_policy": "native unscaled; continuum comparison reported separately; no rescale",
        "native_mass_match_registered": True,
    }


def check_case(binding: dict, case: dict, output: Path) -> dict:
    # Verify all immutable inputs before invoking PartVTK.
    for key, label in (
        ("gencase_receipt", "GenCase receipt"),
        ("prepared_input_report", "prepared input report"),
        ("generated_xml", "generated XML"),
        ("generated_bi4", "generated BI4"),
        ("generated_definition", "generated Def"),
        ("generated_motion", "generated motion"),
        ("source_definition", "source Def"),
        ("prepared_definition", "prepared Def"),
        ("source_motion", "source motion"),
    ):
        require_hash(case[key], case[f"{key}_sha256"], f"{case['case_id']}: {label}")
    forcing_checks = verify_forcing_lineage(binding, case)
    gencase_checks = verify_gencase_metadata(binding, case)
    source_checks = verify_source_wet_obstacle(binding, case)
    rows, provenance = export_csv(case, output, binding["partvtk"])
    row_checks = check_rows(binding, case, rows)
    result = {
        "role": case["role"],
        "endpoint_id": case["endpoint_id"],
        "case_id": case["case_id"],
        "amplitude_deg": case["amplitude_deg"],
        "physical_condition_sha256": case["physical_condition_sha256"],
        "native_particles": int(rows.shape[0]),
        **provenance,
        "checks": {**forcing_checks, **gencase_checks, **source_checks, **row_checks},
        "passed": True,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    binding = load_json(args.binding)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    require(binding.get("schema") == "ds02.f7.target-angle-actual-native-qa-binding.v1", "unexpected fresh063 binding schema")
    require(len(binding.get("cases", [])) == 2, "fresh063 must contain exactly two endpoints")
    require_hash(binding["partvtk"], binding["partvtk_sha256"], "PartVTK")
    results = [check_case(binding, case, output) for case in binding["cases"]]
    report = {
        "schema": "ds02.f7.actual-native-initial-qa.v2",
        "scope_id": binding["scope_id"],
        "binding": str(Path(args.binding).resolve()),
        "binding_sha256": sha(args.binding),
        "partvtk": binding["partvtk"],
        "partvtk_sha256": binding["partvtk_sha256"],
        "cases": results,
        "all_cases_passed": True,
        "independent_case_count_increment": 0,
        "q_n": "not_granted",
        "production_approval": "none",
        "precision_status": "not_accepted",
        "visual_acceptance": "not_assessed",
        "claim_boundary": "Native source and initial typed QA only; no solver dynamics, full-window qualification, visual acceptance, or Q-N claim.",
    }
    destination = output / "native-initial-qa.json"
    require(not destination.exists(), f"refusing to overwrite {destination}")
    destination.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()

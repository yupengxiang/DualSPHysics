#!/usr/bin/env python3
"""Root-owned C082S1 stage-one placement and native-Mk50 audit.

This worker consumes the already-produced official particle CSV and the
metadata reports bound by Root314.  The exact DP lattice residual is measured
and retained as a numerical-precision diagnostic.  It is deliberately not a
gate for the basic placement proof, and this worker never authorizes a solver.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = "ds02.f5.c082s1.stage1-placement-mk50-binding.fresh092.v1"
RESULT_SCHEMA = "ds02.f5.c082s1.stage1-placement-mk50-audit.fresh092.v1"
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
GATT = "root-stage1-f5-c082s1-solid-fluid-recovery-genuine-gencase-293"
PREVIOUS_QA = "root-stage1-f5-c082s1-solid-fluid-recovery-actual-initial-qa-306-actual-audit312-particlecsv314"
TYPE_FIXED, TYPE_MOVING, TYPE_FLOATING, TYPE_FLUID = 0, 1, 2, 3
DP = 0.02
POINTREF = np.asarray([0.01, 0.0, 0.01], dtype=np.float64)
LATTICE_THRESHOLD = 1e-6
PROFILE = np.asarray(
    [[-0.2, 0.0], [2.0, 0.0], [3.0, 0.28], [3.6, 0.448],
     [3.9, 0.448], [4.4, 0.05], [4.8, 0.05]], dtype=np.float64
)
FLUID_BOX_MIN = np.asarray([0.01, -0.14, 0.01], dtype=np.float64)
FLUID_BOX_MAX = np.asarray([3.43, 0.14, 0.39], dtype=np.float64)
FIELDS = [
    "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Type", "Mk",
    "Mass [kg]", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]",
    "Rhop [kg/m^3]", "Press [Pa]",
]


def require(value: Any, message: str) -> None:
    if not value:
        raise ValueError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, digest: str, label: str) -> dict[str, Any]:
    require(path.is_file(), f"{label} missing: {path}")
    require(sha256_file(path) == digest, f"{label} SHA mismatch")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{label} is not a JSON object")
    return value


def validate_binding(binding: dict[str, Any]) -> None:
    require(binding.get("schema") == SCHEMA, "fresh092 placement binding schema mismatch")
    require(binding.get("case_id") == CASE, "C082S1 case identity mismatch")
    require(binding.get("gencase_attempt_id") == GATT, "actual GenCase identity mismatch")
    require(isinstance(binding.get("audit_attempt_id"), str), "audit attempt identity is missing")
    require(binding["audit_attempt_id"] not in {GATT, PREVIOUS_QA}, "audit identity collapsed")
    counts = binding.get("actual_counts")
    required_counts = ("total_particles", "fixed_particles", "moving_particles",
                       "floating_particles", "fluid_particles")
    require(isinstance(counts, dict) and all(isinstance(counts.get(k), int) for k in required_counts),
            "actual producer counts are not bound")
    require(counts["total_particles"] > 0 and counts["fluid_particles"] > 0,
            "actual producer counts are not positive")
    require(binding.get("dimension") == 3, "stage-one audit requires 3-D")
    require(binding.get("source_mkbound") == 40 and binding.get("native_bed_mk") == 50,
            "source/native bed marker mapping is missing")
    files = binding.get("files")
    require(isinstance(files, dict), "placement audit files are missing")
    required_files = {
        "actual_gencase_binding", "gencase_receipt", "prepared_input_report",
        "generated_xml", "generated_bi4", "gencase_output_root", "previous_qa_receipt",
        "initial_qa_report", "physical_geometry_diagnostic", "official_csv",
    }
    require(set(files) == required_files, "placement audit file contract differs")
    for key, ref in files.items():
        require(isinstance(ref, dict) and isinstance(ref.get("path"), str) and ref["path"],
                f"files.{key}.path is missing")
        if key != "gencase_output_root":
            require(isinstance(ref.get("sha256"), str) and len(ref["sha256"]) == 64,
                    f"files.{key}.sha256 is missing")
    contract = binding.get("placement_contract")
    require(isinstance(contract, dict)
            and contract.get("lattice_residual_is_diagnostic_only") is True
            and contract.get("lattice_residual_must_not_be_labelled_pass") is True,
            "numerical precision policy is not explicit")
    require(binding.get("historical_precision_failure", {}).get("accepted_for_stage1_placement") is False,
            "historical precision failure was accidentally accepted")


def profile_z(x: np.ndarray) -> np.ndarray:
    return np.interp(np.asarray(x, dtype=np.float64), PROFILE[:, 0], PROFILE[:, 1])


def xml_metadata(path: Path) -> tuple[int, dict[str, int]]:
    root = ET.parse(path).getroot()
    require(root.tag == "case", "generated XML root is not <case>")
    data2d = root.find("./execution/constants/data2d")
    require(data2d is not None and data2d.get("value", "true").lower() == "false",
            "generated XML is not 3-D")
    particles = root.find("./execution/particles")
    require(particles is not None, "generated XML particle metadata is missing")
    total = int(particles.get("np", "-1"))
    names = ("fixed", "moving", "floating", "fluid")
    counts = {name: sum(int(node.get("count", "-1")) for node in particles.findall(name))
              for name in names}
    require(total > 0 and sum(counts.values()) == total, "XML counts do not sum to total")
    return total, counts


def read_csv(path: Path) -> np.ndarray:
    header: list[str] | None = None
    header_line = -1
    with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
        for index, row in enumerate(csv.reader(stream)):
            row = [item.strip() for item in row]
            if "Pos.x [m]" in row and "Idp" in row and "Type" in row:
                header, header_line = row, index
                break
    require(header is not None and all(field in header for field in FIELDS),
            "official particle CSV fields are incomplete")
    rows = np.loadtxt(path, delimiter=",", skiprows=header_line + 1,
                      usecols=[header.index(field) for field in FIELDS], ndmin=2)
    rows = np.asarray(rows, dtype=np.float64)
    require(rows.ndim == 2 and rows.shape[1] == len(FIELDS), f"CSV shape is {rows.shape}")
    return rows


def mk50_support(rows: np.ndarray) -> dict[str, Any]:
    fixed_mk50 = ((np.rint(rows[:, 5]).astype(np.int64) == TYPE_FIXED)
                  & (np.rint(rows[:, 6]).astype(np.int64) == 50))
    x, y, z = rows[:, 0], rows[:, 1], rows[:, 2]
    bed = profile_z(np.clip(x, PROFILE[0, 0], PROFILE[-1, 0]))
    segments = [(-0.2, 2.0), (2.0, 3.0), (3.0, 3.6),
                (3.6, 3.9), (3.9, 4.4), (4.4, 4.8)]
    records = []
    for index, (left, right) in enumerate(segments):
        segment = fixed_mk50 & (x >= left)
        segment &= x <= right if index == len(segments) - 1 else x < right
        surface = segment & (np.abs(z - bed) <= 0.5 * DP + 1e-8)
        central = surface & (np.abs(y) <= 0.01)
        records.append({
            "x_bounds_m": [left, right],
            "surface_half_dp_count": int(surface.sum()),
            "central_abs_y_le_0p01_surface_half_dp_count": int(central.sum()),
        })
    central_counts = [item["central_abs_y_le_0p01_surface_half_dp_count"] for item in records]
    return {
        "native_type0_mk50_count": int(fixed_mk50.sum()),
        "six_segment_bins": records,
        "central_half_dp_global_count": int(sum(central_counts)),
        "all_six_segments_central_positive": bool(all(value > 0 for value in central_counts)),
        "source_mkbound": 40,
        "native_bed_mk": 50,
    }


def lattice_diagnostic(fluid_xyz: np.ndarray) -> dict[str, Any]:
    normalized = (fluid_xyz - POINTREF) / DP
    axis_residual = np.abs(normalized - np.rint(normalized))
    per_particle = np.max(axis_residual, axis=1)
    worst = int(np.argmax(per_particle))
    quantiles = np.quantile(per_particle, [0.5, 0.95, 0.99, 1.0])
    return {
        "threshold": LATTICE_THRESHOLD,
        "max_residual_cells": float(np.max(per_particle)),
        "axis_max_residual_cells": [float(value) for value in np.max(axis_residual, axis=0)],
        "quantiles_cells": {
            "p50": float(quantiles[0]), "p95": float(quantiles[1]),
            "p99": float(quantiles[2]), "p100": float(quantiles[3]),
        },
        "worst_particle_fluid_index": worst,
        "worst_particle_position_m": [float(value) for value in fluid_xyz[worst]],
        "pass_at_original_threshold": bool(float(np.max(per_particle)) <= LATTICE_THRESHOLD),
        "accepted_as_stage1_placement_gate": False,
        "classification": "numerical_precision",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    binding = json.loads(args.binding.read_text(encoding="utf-8"))
    require(isinstance(binding, dict), "binding must be a JSON object")
    validate_binding(binding)
    files = binding["files"]
    counts = binding["actual_counts"]
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    producer = load_json(Path(files["actual_gencase_binding"]["path"]),
                         files["actual_gencase_binding"]["sha256"], "actual GenCase binding")
    require(producer.get("case_id") == CASE, "producer case mismatch")
    require(producer.get("attempt_id", producer.get("gencase_attempt_id")) == GATT,
            "producer attempt mismatch")
    require(producer.get("actual_counts") == counts, "producer counts differ from binding")

    receipt = load_json(Path(files["gencase_receipt"]["path"]), files["gencase_receipt"]["sha256"],
                        "GenCase receipt")
    prepared = load_json(Path(files["prepared_input_report"]["path"]),
                          files["prepared_input_report"]["sha256"], "prepared report")
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0,
            "GenCase receipt is not completed/zero")
    nested = receipt.get("request", {})
    require(nested.get("case_id") == CASE and nested.get("attempt_id") == GATT,
            "nested GenCase identity mismatch")
    require(receipt.get("solver_dimension_from_gencase") == 3, "GenCase is not 3-D")
    require(int(receipt.get("total_particles", -1)) == counts["total_particles"],
            "GenCase total mismatch")
    require(int(receipt.get("fluid_particles", -1)) == counts["fluid_particles"],
            "GenCase fluid mismatch")
    require(Path(str(receipt.get("output_root", ""))).resolve()
            == Path(files["gencase_output_root"]["path"]).resolve(),
            "GenCase output root mismatch")
    xml_total, xml_counts = xml_metadata(Path(files["generated_xml"]["path"]))
    require(sha256_file(Path(files["generated_xml"]["path"])) == files["generated_xml"]["sha256"],
            "generated XML SHA mismatch")
    require(xml_total == counts["total_particles"], "XML total mismatch")
    prepared_counts = prepared.get("generated_xml_particle_counts", {})
    require({name: int(prepared_counts.get(name, 0)) for name in xml_counts} == xml_counts,
            "prepared/XML counts differ")
    # The binary is an immutable producer artifact.  This audit checks its presence and
    # report provenance only; it does not open or rehash the BI4 payload.
    require(Path(files["generated_bi4"]["path"]).is_file(), "generated BI4 is missing")
    require(files["generated_bi4"]["sha256"] == prepared.get("bi4_sha256"),
            "BI4 SHA provenance differs from prepared report")

    previous = load_json(Path(files["previous_qa_receipt"]["path"]),
                         files["previous_qa_receipt"]["sha256"], "Root314 QA receipt")
    require(previous.get("status") == "failed" and previous.get("returncode") == 1,
            "Root314 numerical-precision failure was not preserved")
    previous_request = previous.get("request", {})
    require(previous_request.get("actual_gencase_attempt") == GATT,
            "Root314 receipt is not bound to actual GenCase")
    qa_report = load_json(Path(files["initial_qa_report"]["path"]),
                          files["initial_qa_report"]["sha256"], "Root314 native QA report")
    geometry = load_json(Path(files["physical_geometry_diagnostic"]["path"]),
                          files["physical_geometry_diagnostic"]["sha256"],
                          "Root314 geometry diagnostic")
    require(qa_report.get("schema") == "ds02.root.actual-initial-native-QA.v1",
            "Root314 QA report schema mismatch")
    require(isinstance(qa_report.get("cases"), list) and len(qa_report["cases"]) == 1,
            "Root314 QA report case metadata missing")
    prior_case = qa_report["cases"][0]
    require(prior_case.get("official_csv_sha256") == files["official_csv"]["sha256"],
            "official CSV SHA differs from Root314 helper provenance")
    require(geometry.get("provenance", {}).get("official_csv_sha256")
            == files["official_csv"]["sha256"], "geometry CSV SHA provenance mismatch")
    require(geometry.get("actual_native_fluid") == counts["fluid_particles"]
            and geometry.get("actual_unique_fluid_y_levels") == 15
            and geometry.get("expected_unique_fluid_y_levels") == 15,
            "Root314 scalar geometry evidence is inconsistent")

    csv_path = Path(files["official_csv"]["path"])
    require(csv_path.is_file() and sha256_file(csv_path) == files["official_csv"]["sha256"],
            "bound official particle CSV missing/SHA mismatch")
    rows = read_csv(csv_path)
    total = counts["total_particles"]
    shape_ok = rows.shape == (total, len(FIELDS))
    require(shape_ok, f"CSV shape {rows.shape} != ({total},13)")
    finite_ok = bool(np.isfinite(rows).all())
    categorical_ok = bool(np.equal(rows[:, 3:7], np.rint(rows[:, 3:7])).all())
    zone_ok = bool(np.all(rows[:, 3] == 0))
    ids = rows[:, 4].astype(np.int64)
    uid_ok = bool(np.array_equal(np.sort(ids), np.arange(total)))
    expected_types = {code for code, key in ((0, "fixed_particles"), (1, "moving_particles"),
                                              (2, "floating_particles"), (3, "fluid_particles"))
                      if counts[key] > 0}
    observed_types = {int(value) for value in np.unique(rows[:, 5])}
    types_ok = observed_types == expected_types
    type_counts_ok = all(int(np.sum(rows[:, 5] == code)) == counts[key]
                         for code, key in ((0, "fixed_particles"), (1, "moving_particles"),
                                           (2, "floating_particles"), (3, "fluid_particles")))
    positive_ok = bool(np.all(rows[:, 7] > 0) and np.all(rows[:, 11] > 0))
    zero_velocity_ok = bool(float(np.max(np.abs(rows[:, 8:11]))) <= 1e-8)
    positions = rows[:, :3]
    unique_position_ok = bool(np.unique(positions, axis=0).shape[0] == total)
    groups = {code: {tuple(row) for row in positions[rows[:, 5] == code]}
              for code in expected_types}
    overlap = {}
    labels = {0: "fixed", 1: "moving", 2: "floating", 3: "fluid"}
    codes = sorted(groups)
    for left_index, left in enumerate(codes):
        for right in codes[left_index + 1:]:
            overlap[f"{labels[left]}_{labels[right]}"] = len(groups[left] & groups[right])
    no_overlap_ok = not any(overlap.values())

    fluid = rows[:, 5] == TYPE_FLUID
    fluid_xyz = positions[fluid]
    fx, fy, fz = fluid_xyz.T
    bed_z = profile_z(fx)
    outside = ((fluid_xyz < FLUID_BOX_MIN - 1e-8)
               | (fluid_xyz > FLUID_BOX_MAX + 1e-8)).any(axis=1)
    below = fz < bed_z - 2e-7
    source_box_ok = not outside.any()
    above_bed_ok = not below.any()
    unique_y = np.unique(np.round(fy, 10))
    y15_ok = unique_y.size == 15
    precision = lattice_diagnostic(fluid_xyz)
    support = mk50_support(rows)
    mk50_present = support["native_type0_mk50_count"] > 0
    central_support_present = support["central_half_dp_global_count"] > 0
    fluid_mass = float(rows[fluid, 7].sum())
    continuum = float(binding["continuum_mass_kg_legacy"])

    checks = {
        "actual_gencase_completed_3d_and_counts": True,
        "all_native_rows_finite": finite_ok,
        "categorical_zone_id_type_mk_integral": categorical_ok,
        "zone_zero": zone_ok,
        "uid_unique_consecutive": uid_ok,
        "native_type_set_and_counts_match_actual_producer": types_ok and type_counts_ok,
        "positive_mass_and_density": positive_ok,
        "zero_initial_velocity": zero_velocity_ok,
        "all_particle_positions_unique": unique_position_ok,
        "fixed_moving_floating_fluid_spatial_no_overlap": no_overlap_ok,
        "fluid_inside_exact_source_box": source_box_ok,
        "fluid_initial_above_exact_continuous_bed": above_bed_ok,
        "fluid_has_exact_15_transverse_levels": y15_ok,
        "native_type0_mk50_exists": mk50_present,
        "central_mk50_surface_support_is_present": central_support_present,
        "numerical_precision_lattice_gate_passed": precision["pass_at_original_threshold"],
    }
    basic_keys = [key for key in checks if key != "numerical_precision_lattice_gate_passed"]
    basic_pass = all(checks[key] for key in basic_keys)
    stage1_label = "pass_excluding_numerical_precision" if basic_pass else "failed_basic_placement_check"
    result = {
        "schema": RESULT_SCHEMA,
        "status": "completed_stage1_placement_mk50_diagnostic",
        "diagnostic_only": True,
        "stage1_basic_placement_proof": stage1_label,
        "all_basic_placement_checks_pass": basic_pass,
        "numerical_precision": precision,
        "numerical_precision_result_accepted": False,
        "historical_root314_failure": {
            "attempt_id": PREVIOUS_QA,
            "classification": "numerical_precision",
            "exact_dp_lattice_gate": "failed_and_retained",
            "not_relabelled_as_pass": True,
        },
        "actual_counts": {**{key: int(counts[key]) for key in
                             ("total_particles", "fixed_particles", "moving_particles",
                              "floating_particles", "fluid_particles")},
                          "solver_dimension": 3, "xml_particle_counts": xml_counts},
        "audit_attempt_id": binding["audit_attempt_id"],
        "gencase_attempt_id": GATT,
        "checks": checks,
        "source_marker_mapping": {"source_mkbound": 40, "native_bed_mk": 50,
                                   "native_filter": "Type==0 and Mk==50"},
        "mk50_coverage": support,
        "fluid_geometry": {
            "source_fluid_box_min_m": FLUID_BOX_MIN.tolist(),
            "source_fluid_box_max_m": FLUID_BOX_MAX.tolist(),
            "x_bounds_m": [float(fx.min()), float(fx.max())],
            "y_bounds_m": [float(fy.min()), float(fy.max())],
            "z_bounds_m": [float(fz.min()), float(fz.max())],
            "unique_y_levels": unique_y.tolist(),
            "below_profile_count": int(below.sum()),
            "outside_source_box_count": int(outside.sum()),
        },
        "native_fluid_mass": {
            "csv_mass_kg": fluid_mass,
            "continuum_mass_kg_legacy": continuum,
            "difference_kg": fluid_mass - continuum,
            "mass_rescaled": False,
        },
        "input_provenance": {
            "official_csv": str(csv_path),
            "official_csv_sha256": files["official_csv"]["sha256"],
            "official_csv_hash_source": "Root314 helper JSON",
            "generated_bi4_sha256": files["generated_bi4"]["sha256"],
            "generated_bi4_opened_by_this_worker": False,
            "source_agent_read_or_hashed_particle_csv": False,
            "source_agent_read_or_hashed_bi4": False,
        },
        "review_boundary": {
            "short_solver_requires_root_review": True,
            "short_solver_requires_basic_placement_and_mk50_review": True,
            "short_solver_authorized": False,
            "full16_authorized": False,
            "full801_authorized": False,
            "q_n_granted": False,
            "independent_case_count_increment": 0,
        },
        "inputs": files,
        "arrays_opened_by_source_agent": False,
    }
    output_file = output / "c082s1-stage1-placement-mk50-audit.json"
    output_file.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"],
                      "stage1_basic_placement_proof": stage1_label,
                      "numerical_precision": precision["classification"],
                      "numerical_precision_pass": precision["pass_at_original_threshold"],
                      "native_type0_mk50_count": support["native_type0_mk50_count"],
                      "central_half_dp_global_count": support["central_half_dp_global_count"],
                      "full801_authorized": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

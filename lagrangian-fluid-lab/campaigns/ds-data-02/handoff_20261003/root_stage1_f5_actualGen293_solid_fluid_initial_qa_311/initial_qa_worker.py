#!/usr/bin/env python3
"""Root-owned C082S1 native initial QA.

This worker is disabled in the source handoff.  When Root binds a fresh
GenCase receipt it invokes the official QA helper and then checks the actual
CSV independently.  Counts are read from the bound producer/XML; this module
contains no mother-case count and never rescales mass.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = "ds02.f5.c082s1.actual-initial-qa-binding.fresh091.v1"
RESULT_SCHEMA = "ds02.f5.c082s1.actual-initial-qa.fresh091.v1"
FIELDS = [
    "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Type", "Mk",
    "Mass [kg]", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]",
    "Rhop [kg/m^3]", "Press [Pa]",
]
TYPE_FIXED, TYPE_MOVING, TYPE_FLUID = 0, 1, 3
DP = 0.02
POINTREF = np.asarray([0.01, 0.0, 0.01], dtype=np.float64)
PROFILE = np.asarray(
    [[-0.2, 0.0], [2.0, 0.0], [3.0, 0.28], [3.6, 0.448],
     [3.9, 0.448], [4.4, 0.05], [4.8, 0.05]], dtype=np.float64
)
FLUID_BOX_MIN = np.asarray([0.01, -0.14, 0.01], dtype=np.float64)
FLUID_BOX_MAX = np.asarray([3.43, 0.14, 0.39], dtype=np.float64)
BED_MK = 50


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


def file_ref(files: dict[str, Any], key: str, *, sha_required: bool = True) -> dict[str, Any]:
    ref = files.get(key)
    require(isinstance(ref, dict) and isinstance(ref.get("path"), str) and ref["path"],
            f"files.{key}.path is missing")
    if sha_required:
        require(isinstance(ref.get("sha256"), str) and len(ref["sha256"]) == 64,
                f"files.{key}.sha256 is missing")
    return ref


def load_json(path: Path, digest: str, label: str) -> dict[str, Any]:
    require(path.is_file(), f"{label} missing: {path}")
    require(sha256_file(path) == digest, f"{label} SHA mismatch")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{label} is not a JSON object")
    return value


def validate_binding_contract(binding: dict[str, Any]) -> None:
    require(binding.get("schema") == SCHEMA, "C082S1 initial-QA binding schema mismatch")
    require("attempt_id" not in binding, "ambiguous top-level attempt_id is forbidden")
    require(isinstance(binding.get("qa_attempt_id"), str), "qa_attempt_id is missing")
    require(isinstance(binding.get("gencase_attempt_id"), str), "gencase_attempt_id is missing")
    require(binding["qa_attempt_id"] != binding["gencase_attempt_id"],
            "QA and GenCase identities must remain separate")
    require(binding.get("case_id") == "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1",
            "C082S1 case identity mismatch")
    counts = binding.get("actual_counts")
    required_counts = ("total_particles", "fixed_particles", "moving_particles",
                       "floating_particles", "fluid_particles")
    require(isinstance(counts, dict) and all(isinstance(counts.get(key), int) for key in required_counts),
            "actual producer counts are not Root-bound")
    require(counts["total_particles"] > 0 and counts["fluid_particles"] > 0,
            "actual producer counts are not positive")
    files = binding.get("files")
    require(isinstance(files, dict), "files binding is missing")
    for key in ("gencase_receipt", "prepared_input_report", "generated_xml", "generated_bi4",
                "gencase_output_root", "partvtk", "qa054_tool", "actual_gencase_binding"):
        file_ref(files, key, sha_required=key in {"gencase_receipt", "prepared_input_report",
                                                   "generated_xml", "generated_bi4",
                                                   "actual_gencase_binding"})
    require(isinstance(binding.get("continuum_mass_kg_legacy"), (int, float)),
            "legacy continuum mass is missing")
    require(binding.get("native_bed_marker_mk") == 50 and binding.get("source_bed_marker_mkbound") == 40,
            "source/native bed marker mapping is missing")


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
    counts = {name: 0 for name in ("fixed", "moving", "floating", "fluid")}
    for node in particles:
        if node.tag in counts:
            counts[node.tag] += int(node.get("count", "-1"))
    require(total > 0 and sum(counts.values()) == total,
            "generated XML counts do not sum to total")
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
    require(header is not None, "official QA CSV header is missing")
    require(all(field in header for field in FIELDS), "official QA CSV fields are incomplete")
    rows = np.loadtxt(path, delimiter=",", skiprows=header_line + 1,
                      usecols=[header.index(field) for field in FIELDS], ndmin=2)
    rows = np.asarray(rows, dtype=np.float64)
    require(rows.ndim == 2 and rows.shape[1] == len(FIELDS), f"CSV shape is {rows.shape}")
    return rows


def support_summary(rows: np.ndarray) -> dict[str, Any]:
    fixed_mk50 = (rows[:, 5] == TYPE_FIXED) & (np.rint(rows[:, 6]).astype(np.int64) == BED_MK)
    x, y, z = rows[:, 0], rows[:, 1], rows[:, 2]
    bed = profile_z(np.clip(x, PROFILE[0, 0], PROFILE[-1, 0]))
    segments = [(-0.2, 2.0), (2.0, 3.0), (3.0, 3.6),
                (3.6, 3.9), (3.9, 4.4), (4.4, 4.8)]
    records = []
    for index, (left, right) in enumerate(segments):
        in_segment = fixed_mk50 & (x >= left)
        in_segment &= x <= right if index == len(segments) - 1 else x < right
        near = in_segment & (np.abs(z - bed) <= 0.5 * DP + 1e-8)
        central = near & (np.abs(y) <= 0.01)
        records.append({
            "x_bounds_m": [left, right],
            "surface_half_dp_count": int(near.sum()),
            "central_abs_y_le_0p01_surface_half_dp_count": int(central.sum()),
        })
    return {"native_type0_mk50_count": int(fixed_mk50.sum()),
            "six_segment_surface_support": records,
            "source_mkbound": 40, "native_bed_mk": 50}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    binding = json.loads(args.binding.read_text(encoding="utf-8"))
    require(isinstance(binding, dict), "binding must be a JSON object")
    validate_binding_contract(binding)
    files = binding["files"]
    counts = binding["actual_counts"]
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    producer = load_json(Path(files["actual_gencase_binding"]["path"]), files["actual_gencase_binding"]["sha256"], "actual GenCase binding")
    require(producer.get("case_id") == binding["case_id"], "actual producer sidecar case mismatch")
    require(producer.get("attempt_id", producer.get("gencase_attempt_id")) == binding["gencase_attempt_id"], "actual producer sidecar attempt mismatch")
    require(producer.get("actual_counts") == counts, "actual producer sidecar counts differ from QA binding")
    receipt_path = Path(files["gencase_receipt"]["path"])
    report_path = Path(files["prepared_input_report"]["path"])
    xml_path = Path(files["generated_xml"]["path"])
    bi4_path = Path(files["generated_bi4"]["path"])
    receipt = load_json(receipt_path, files["gencase_receipt"]["sha256"], "GenCase receipt")
    prepared = load_json(report_path, files["prepared_input_report"]["sha256"], "prepared-input report")
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0,
            "genuine GenCase receipt is not completed/zero")
    nested = receipt.get("request", {})
    require(nested.get("case_id") == binding["case_id"], "nested GenCase case identity mismatch")
    require(nested.get("attempt_id") == binding["gencase_attempt_id"],
            "nested GenCase attempt identity mismatch")
    require(receipt.get("solver_dimension_from_gencase") == 3, "GenCase is not 3-D")
    require(int(receipt.get("total_particles", -1)) == counts["total_particles"],
            "receipt total differs from actual binding")
    require(int(receipt.get("fluid_particles", -1)) == counts["fluid_particles"],
            "receipt fluid count differs from actual binding")
    require(Path(str(receipt.get("output_root", ""))).resolve() == Path(files["gencase_output_root"]["path"]).resolve(),
            "receipt output root differs from bound output root")
    xml_total, xml_counts = xml_metadata(xml_path)
    require(sha256_file(xml_path) == files["generated_xml"]["sha256"], "generated XML SHA mismatch")
    require(xml_total == counts["total_particles"], "generated XML total differs from producer")
    prepared_counts = prepared.get("generated_xml_particle_counts", {})
    normalized_prepared = {name: int(prepared_counts.get(name, 0)) for name in xml_counts}
    require(normalized_prepared == xml_counts, "prepared report/XML particle counts differ")
    require(int(prepared.get("actual_total_particles", -1)) == xml_total,
            "prepared report total differs from XML")
    require(bi4_path.is_file() and sha256_file(bi4_path) == files["generated_bi4"]["sha256"],
            "generated BI4 binding is missing or changed")

    runtime_binding = output / "qa054-runtime-binding.json"
    runtime_binding.write_text(json.dumps({
        "partvtk": files["partvtk"]["path"],
        "cases": [{"role": "C082S1", "receipt": str(receipt_path),
                    "prefix": str(xml_path.with_suffix("")),
                    "expected_total": counts["total_particles"],
                    "expected_fluid": counts["fluid_particles"],
                    "expected_types": [0, 1, 3], "compact_f5_geometry": True,
                    "cells_y": 15}],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    qa_proc = subprocess.run(
        [sys.executable, files["qa054_tool"]["path"], "--binding", str(runtime_binding),
         "--output-dir", str(output)], cwd=str(output), check=False,
    )
    require(qa_proc.returncode == 0, "official QA helper failed for actual C082S1 producer")
    csv_files = sorted(output.glob("*.csv"))
    require(len(csv_files) == 1, f"expected one official QA CSV, found {[p.name for p in csv_files]}")
    rows = read_csv(csv_files[0])
    total = counts["total_particles"]
    require(rows.shape == (total, len(FIELDS)), f"CSV shape {rows.shape} != ({total},13)")
    require(np.isfinite(rows).all(), "native CSV contains nonfinite values")
    require(np.equal(rows[:, 3:7], np.rint(rows[:, 3:7])).all(),
            "Zone/Idp/Type/Mk contain nonintegral values")
    require(np.all(rows[:, 3] == 0), "native Zone is not zero")
    ids = rows[:, 4].astype(np.int64)
    require(np.array_equal(np.sort(ids), np.arange(total)), "Idp is not unique/consecutive")
    expected_types = {code for code, key in ((0, "fixed_particles"), (1, "moving_particles"),
                                              (2, "floating_particles"), (3, "fluid_particles"))
                      if counts[key] > 0}
    observed_types = {int(value) for value in np.unique(rows[:, 5])}
    require(observed_types == expected_types, f"native type set {observed_types} != {expected_types}")
    for code, key in ((0, "fixed_particles"), (1, "moving_particles"),
                      (2, "floating_particles"), (3, "fluid_particles")):
        require(int(np.sum(rows[:, 5] == code)) == counts[key], f"actual {key} count mismatch")
    require(np.all(rows[:, 7] > 0) and np.all(rows[:, 11] > 0),
            "native mass or density is not positive")
    require(float(np.max(np.abs(rows[:, 8:11]))) <= 1e-8, "initial velocity is nonzero")
    positions = rows[:, :3]
    require(np.unique(positions, axis=0).shape[0] == total, "native positions are duplicated")
    groups = {code: {tuple(row) for row in positions[rows[:, 5] == code]}
              for code in expected_types}
    overlap = {}
    labels = {0: "fixed", 1: "moving", 2: "floating", 3: "fluid"}
    codes = sorted(groups)
    for left_index, left in enumerate(codes):
        for right in codes[left_index + 1:]:
            overlap[f"{labels[left]}_{labels[right]}"] = len(groups[left] & groups[right])
    require(not any(overlap.values()), f"native type spatial overlap: {overlap}")

    fluid = rows[:, 5] == TYPE_FLUID
    fluid_xyz = positions[fluid]
    fx, fy, fz = fluid_xyz.T
    bed_z = profile_z(fx)
    outside = ((fluid_xyz < FLUID_BOX_MIN - 1e-8) | (fluid_xyz > FLUID_BOX_MAX + 1e-8)).any(axis=1)
    below = fz < bed_z - 2e-7
    require(not outside.any(), "initial fluid is outside the exact source box/profile x domain")
    require(not below.any(), "initial fluid is below the exact source bed profile")
    unique_y = np.unique(np.round(fy, 10))
    require(unique_y.size == 15, f"initial fluid has {unique_y.size} y levels; source contract requires 15")
    lattice_residual = np.max(np.abs((fluid_xyz - POINTREF) / DP - np.rint((fluid_xyz - POINTREF) / DP))
                              if fluid_xyz.size else np.asarray([np.inf]))
    require(float(lattice_residual) <= 1e-6, "initial fluid is not on the exact DP lattice")
    support = support_summary(rows)
    require(support["native_type0_mk50_count"] > 0, "no Type0/native Mk50 bed marker exists")
    fluid_mass = float(rows[fluid, 7].sum())
    continuum = float(binding["continuum_mass_kg_legacy"])
    require(np.isfinite(fluid_mass - continuum), "mass difference is nonfinite")
    qa_report = output / "native-initial-qa.json"
    require(qa_report.is_file(), "official QA report is missing")

    result = {
        "schema": RESULT_SCHEMA,
        "status": "completed_actual_initial_qa",
        "all_actual_checks_pass": True,
        "diagnostic_only": True,
        "q_n_status": "not_granted",
        "full_solver_authorized": False,
        "qa_attempt_id": binding["qa_attempt_id"],
        "gencase_attempt_id": binding["gencase_attempt_id"],
        "actual_counts": {**{key: int(counts[key]) for key in
                             ("total_particles", "fixed_particles", "moving_particles",
                              "floating_particles", "fluid_particles")},
                          "solver_dimension": 3, "xml_particle_counts": xml_counts},
        "checks": {
            "actual_gencase_receipt_completed": True,
            "actual_xml_total_and_3d": True,
            "all_native_rows_finite": True,
            "categorical_columns_integral_density_real_valued": True,
            "mass_density_positive": True,
            "idp_unique_consecutive": True,
            "native_type_codes_match_actual_contract": True,
            "zero_initial_velocity": True,
            "fixed_moving_floating_fluid_spatial_no_overlap": True,
            "fluid_inside_exact_source_profile_and_box": True,
            "fluid_initial_below_profile_zero": True,
            "fluid_has_exact_15_transverse_levels": True,
            "fluid_dp_lattice_aligned": True,
            "native_type0_mk50_bed_marker_present": True,
            "native_fluid_mass_difference_reported_without_rescale": True,
        },
        "source_marker_mapping": {"source_mkbound": 40, "native_bed_mk": 50},
        "support_diagnostic": support,
        "fluid_geometry": {
            "source_fluid_box_min_m": FLUID_BOX_MIN.tolist(),
            "source_fluid_box_max_m": FLUID_BOX_MAX.tolist(),
            "x_bounds_m": [float(fx.min()), float(fx.max())],
            "y_bounds_m": [float(fy.min()), float(fy.max())],
            "z_bounds_m": [float(fz.min()), float(fz.max())],
            "unique_y_levels": unique_y.tolist(),
            "below_profile_count": int(below.sum()),
            "outside_source_box_or_profile_count": int(outside.sum()),
            "max_fluid_lattice_residual": float(lattice_residual),
        },
        "native_fluid_mass": {"csv_mass_kg": fluid_mass,
                               "continuum_mass_kg_legacy": continuum,
                               "difference_kg": fluid_mass - continuum,
                               "mass_rescaled": False},
        "actual_producer": {
            "receipt": str(receipt_path), "receipt_sha256": files["gencase_receipt"]["sha256"],
            "prepared_input_report": str(report_path),
            "prepared_input_report_sha256": files["prepared_input_report"]["sha256"],
            "generated_xml": str(xml_path), "generated_xml_sha256": files["generated_xml"]["sha256"],
            "generated_bi4": str(bi4_path), "generated_bi4_sha256": files["generated_bi4"]["sha256"],
        },
        "official_qa_report": {"path": str(qa_report), "sha256": sha256_file(qa_report)},
        "interpretation": "step-zero actual native structure/geometry only; no dynamic or full16/full801 authorization",
        "arrays_opened_by_source_agent": False,
    }
    (output / "c082s1-native-initial-qa-provenance.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "completed", "actual_counts": result["actual_counts"],
                      "all_actual_checks_pass": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

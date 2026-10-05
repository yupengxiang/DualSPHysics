#!/usr/bin/env python3
"""Root-authorized frame-zero central fixed-bed diagnostic for B071.

Root175 already ran the official PartVTK frame-zero export during actual native
initial QA.  This worker consumes that exact CSV through the small QA reports'
opaque provenance hash and audits the fixed Mk50, Type0 profile directly.  It
uses no typed H5/XDMF input and does not launch PartVTK again.  The Mk50
namespace may contain walls, so every result is diagnostic only.  Root175's
structural initial-QA pass is bound as provenance; it does not certify central
bed coverage or dynamic acceptance.  No solver, GenCase, converter, renderer,
threshold relaxation, or source-array mutation is performed by this worker.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Sequence

import numpy as np

SCHEMA = "ds02.f5.b071.root175-csv-initial-fixed-bed-coverage.v2"
CSV_FIELDS = [
    "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Type", "Mk",
    "Mass [kg]", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]",
    "Rhop [kg/m^3]", "Press [Pa]",
]
TYPE_FIXED = 0
TYPE_MOVING = 1
TYPE_FLUID = 3
BED_MK = 50
DP_M = 0.02
BED_Y = (-0.15, 0.15)
CENTRAL_Y = 0.01
PROFILE = np.asarray((
    (-0.2, 0.0), (2.0, 0.0), (3.0, 0.28), (3.6, 0.448),
    (3.9, 0.448), (4.4, 0.05), (4.8, 0.05),
), dtype=np.float64)
CSV_BANDS = (("surface_half_dp", 0.5 * DP_M), ("surface_one_dp", DP_M), ("surface_two_dp", 2.0 * DP_M))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bed_profile_z(x: np.ndarray) -> np.ndarray:
    values = np.asarray(x, dtype=np.float64)
    result = np.full(values.shape, np.nan, dtype=np.float64)
    covered = (values >= PROFILE[0, 0]) & (values <= PROFILE[-1, 0])
    result[covered] = np.interp(values[covered], PROFILE[:, 0], PROFILE[:, 1])
    return result


def load_csv(path: Path) -> np.ndarray:
    header: list[str] | None = None
    header_line = -1
    with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
        reader = csv.reader(stream)
        for index, row in enumerate(reader):
            stripped = [item.strip() for item in row]
            if "Pos.x [m]" in stripped and "Idp" in stripped and "Type" in stripped:
                header = stripped
                header_line = index
                break
    require(header is not None, f"official PartVTK header missing: {path}")
    missing = [field for field in CSV_FIELDS if field not in header]
    require(not missing, f"PartVTK CSV missing columns: {missing}")
    rows = np.loadtxt(
        path,
        delimiter=",",
        skiprows=header_line + 1,
        usecols=[header.index(field) for field in CSV_FIELDS],
        ndmin=2,
    )
    rows = np.asarray(rows, dtype=np.float64)
    require(rows.ndim == 2 and rows.shape[1] == len(CSV_FIELDS), f"CSV shape invalid: {rows.shape}")
    return rows


def xml_metadata(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    require(root.tag == "case", "generated XML root is not case")
    data2d = root.find("./execution/constants/data2d")
    require(data2d is not None and data2d.get("value", "true").lower() == "false", "generated XML is not 3-D")
    particles = root.find("./execution/particles")
    require(particles is not None, "generated XML has no execution/particles")
    np_total = int(particles.get("np", "-1"))
    blocks: list[dict[str, Any]] = []
    for node in particles:
        if node.tag in {"fixed", "moving", "floating", "fluid"}:
            blocks.append({
                "kind": node.tag,
                "begin": int(node.get("begin", "-1")),
                "count": int(node.get("count", "-1")),
                "end_exclusive": int(node.get("begin", "-1")) + int(node.get("count", "-1")),
                "mk": node.get("mk"),
            })
    return {"sha256": sha256_file(path), "actual_total_particles": np_total, "blocks": blocks, "is_3d": True}


def pairwise_overlap(positions: np.ndarray, type_codes: np.ndarray) -> dict[str, Any]:
    finite = np.isfinite(positions).all(axis=1)
    rounded = np.round(positions[finite], decimals=10)
    _, inverse, counts = np.unique(rounded, axis=0, return_inverse=True, return_counts=True)
    duplicate_rows = int(np.sum(counts[inverse] > 1)) if inverse.size else 0
    groups: dict[int, set[tuple[float, float, float]]] = {}
    for code in (TYPE_FIXED, TYPE_MOVING, TYPE_FLUID):
        mask = finite & (type_codes == code)
        groups[code] = {tuple(row) for row in np.round(positions[mask], decimals=10)}
    pairs: dict[str, int] = {}
    for left, left_name in ((TYPE_FIXED, "fixed"), (TYPE_MOVING, "moving"), (TYPE_FLUID, "fluid")):
        for right, right_name in ((TYPE_FIXED, "fixed"), (TYPE_MOVING, "moving"), (TYPE_FLUID, "fluid")):
            if left < right:
                pairs[f"{left_name}__{right_name}"] = len(groups[left] & groups[right])
    return {
        "all_finite_coordinate_duplicate_rows": duplicate_rows,
        "group_pair_overlap_rows": pairs,
        "all_group_pairs_zero_overlap": all(value == 0 for value in pairs.values()),
    }


def segment_records(support: np.ndarray, x: np.ndarray, y: np.ndarray, distance: np.ndarray) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(zip(PROFILE[:-1, 0], PROFILE[1:, 0])):
        in_segment = support & (x >= left)
        if index < len(PROFILE) - 2:
            in_segment &= x < right
        else:
            in_segment &= x <= right
        count = int(in_segment.sum())
        bands: dict[str, Any] = {}
        for name, tolerance in CSV_BANDS:
            near = in_segment & (np.abs(distance) <= tolerance)
            central = near & (np.abs(y) <= CENTRAL_Y)
            bands[name] = {
                "tolerance_m": float(tolerance),
                "count": int(near.sum()),
                "fraction_of_segment_support": (float(near.sum()) / count) if count else None,
                "central_abs_y_le_0p01_count": int(central.sum()),
                "central_abs_y_le_0p01_fraction_of_band": (float(central.sum()) / int(near.sum())) if near.any() else None,
            }
        records.append({
            "segment_index": index,
            "x_left_m": float(left),
            "x_right_m": float(right),
            "actual_type0_mk50_support_count": count,
            "surface_bands": bands,
            "y_levels_m": sorted(float(value) for value in np.unique(y[in_segment]))[:128],
            "y_level_count": int(np.unique(y[in_segment]).size),
            "central_abs_y_le_0p01_support_count": int((in_segment & (np.abs(y) <= CENTRAL_Y)).sum()),
        })
    return records


def run(binding_path: Path, output_dir: Path) -> dict[str, Any]:
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    require(not any(output.iterdir()), f"fresh output directory is not empty: {sorted(p.name for p in output.iterdir())}")

    receipt_path = Path(binding["gencase_receipt"]).resolve()
    report_path = Path(binding["prepared_input_report"]).resolve()
    xml_path = Path(binding["generated_xml"]).resolve()
    bi4_path = Path(binding["generated_bi4"]).resolve()
    source_path = Path(binding["source_definition"]).resolve()
    actual_request_path = Path(binding["actual_gencase_request"]).resolve()
    partvtk_path = Path(binding["partvtk"]).resolve()
    qa_receipt_path = Path(binding["actual_initial_qa_receipt"]).resolve()
    qa_provenance_path = Path(binding["actual_initial_qa_provenance_report"]).resolve()
    qa_native_path = Path(binding["actual_initial_qa_native_report"]).resolve()
    csv_path = Path(binding["initial_qa_official_csv"]).resolve()
    require(xml_path.name == binding["generated_xml_basename"] and not xml_path.name.endswith("_Def.xml"), "wrong generated XML role")
    require(receipt_path.is_file() and report_path.is_file() and xml_path.is_file(), "actual GenCase small input missing")
    require(source_path.is_file() and actual_request_path.is_file(), "source provenance input missing")
    require(partvtk_path.is_file(), "official PartVTK provenance executable missing")
    require(qa_receipt_path.is_file() and qa_provenance_path.is_file() and qa_native_path.is_file(), "Root175 QA metadata missing")
    require(csv_path.is_file(), "Root175 official QA CSV missing")

    immutable_before = {
        "receipt": sha256_file(receipt_path),
        "report": sha256_file(report_path),
        "xml": sha256_file(xml_path),
        "source_definition": sha256_file(source_path),
        "actual_request": sha256_file(actual_request_path),
    }
    qa_immutable_before = {
        "receipt": sha256_file(qa_receipt_path),
        "provenance": sha256_file(qa_provenance_path),
        "native_report": sha256_file(qa_native_path),
    }
    require(immutable_before["receipt"] == binding["gencase_receipt_sha256"], "receipt hash mismatch")
    require(immutable_before["report"] == binding["prepared_input_report_sha256"], "prepared report hash mismatch")
    require(immutable_before["xml"] == binding["generated_xml_sha256"], "generated XML hash mismatch")
    require(immutable_before["source_definition"] == binding["source_definition_sha256"], "source definition hash mismatch")
    require(immutable_before["actual_request"] == binding["actual_gencase_request_sha256"], "actual request hash mismatch")
    require(qa_immutable_before["receipt"] == binding["actual_initial_qa_receipt_sha256"], "Root175 QA receipt hash mismatch")
    require(qa_immutable_before["provenance"] == binding["actual_initial_qa_provenance_report_sha256"], "Root175 QA provenance hash mismatch")
    require(qa_immutable_before["native_report"] == binding["actual_initial_qa_native_report_sha256"], "Root175 native QA report hash mismatch")

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, "genuine GenCase receipt is not completed/zero")
    require(receipt.get("request", {}).get("case_id") == binding["case_id"], "receipt nested request case mismatch")
    require(receipt.get("total_particles") == binding["actual_counts"]["total_particles"], "receipt total mismatch")
    require(receipt.get("fluid_particles") == binding["actual_counts"]["fluid_particles"], "receipt fluid mismatch")
    require(receipt.get("solver_dimension_from_gencase") == 3, "receipt is not 3-D")
    prepared = json.loads(report_path.read_text(encoding="utf-8"))
    require(prepared.get("actual_total_particles") == binding["actual_counts"]["total_particles"], "prepared total mismatch")
    require(prepared.get("generated_xml_particle_counts") == binding["actual_counts"]["xml_particle_counts"], "prepared type counts mismatch")
    xml = xml_metadata(xml_path)
    require(xml["actual_total_particles"] == binding["actual_counts"]["total_particles"], "XML total mismatch")

    root175_receipt = json.loads(qa_receipt_path.read_text(encoding="utf-8"))
    root175_provenance = json.loads(qa_provenance_path.read_text(encoding="utf-8"))
    root175_native = json.loads(qa_native_path.read_text(encoding="utf-8"))
    require(root175_receipt.get("status") == "completed" and root175_receipt.get("returncode") == 0, "Root175 initial QA receipt is not completed/zero")
    require(root175_provenance.get("all_actual_checks_pass") is True, "Root175 initial QA did not report all actual checks pass")
    qa_case = root175_native.get("cases", [{}])[0]
    require(qa_case.get("passed") is True, "Root175 native QA case did not pass")
    require(qa_case.get("official_csv") == str(csv_path), "Root175 official CSV path mismatch")
    require(qa_case.get("official_csv_sha256") == binding["initial_qa_official_csv_sha256_opaque"], "Root175 official CSV opaque hash mismatch")
    require(binding["initial_qa_official_csv_sha256_opaque"] == binding["files"]["initial_qa_official_csv"]["sha256"], "binding CSV opaque hash mismatch")
    csv_before = sha256_file(csv_path)
    require(csv_before == binding["initial_qa_official_csv_sha256_opaque"], "actual CSV hash mismatch")
    require(int(binding["bed_marker_mk"]) == BED_MK, "binding native bed Mk mismatch")
    rows = load_csv(csv_path)
    csv_after = sha256_file(csv_path)
    require(csv_before == csv_after, "actual CSV changed during read")

    finite_rows = np.isfinite(rows).all(axis=1)
    positions = rows[:, :3]
    finite_positions = np.isfinite(positions).all(axis=1)
    ids = rows[:, 4]
    types_float = rows[:, 5]
    markers_float = rows[:, 6]
    types_finite = np.isfinite(types_float)
    markers_finite = np.isfinite(markers_float)
    types_integral = bool(types_finite.all() and np.equal(types_float, np.rint(types_float)).all())
    markers_integral = bool(markers_finite.all() and np.equal(markers_float, np.rint(markers_float)).all())
    type_codes = np.rint(types_float).astype(np.int64, copy=False) if types_integral else np.full(len(rows), -99, dtype=np.int64)
    markers = np.rint(markers_float).astype(np.int64, copy=False) if markers_integral else np.full(len(rows), -99, dtype=np.int64)
    id_integral = bool(np.isfinite(ids).all() and np.equal(ids, np.rint(ids)).all())
    id_unique = False
    id_consecutive = False
    uid_digest = None
    if id_integral:
        id_values = ids.astype(np.int64)
        id_unique = int(np.unique(id_values).size) == len(rows)
        id_consecutive = bool(id_unique and np.array_equal(np.sort(id_values), np.arange(len(rows), dtype=np.int64)))
        uid_digest = hashlib.sha256(np.sort(id_values.astype("<i8")).tobytes()).hexdigest()

    type_counts = {str(code): int(np.sum(type_codes == code)) for code in (0, 1, 2, 3)}
    fixed = type_codes == TYPE_FIXED
    moving = type_codes == TYPE_MOVING
    fluid = type_codes == TYPE_FLUID
    profile = bed_profile_z(rows[:, 0])
    finite_support = finite_positions & np.isfinite(profile)
    support = finite_support & fixed & markers_integral & (markers == BED_MK)
    support &= (rows[:, 0] >= PROFILE[0, 0]) & (rows[:, 0] <= PROFILE[-1, 0])
    support &= (rows[:, 1] >= BED_Y[0]) & (rows[:, 1] <= BED_Y[1])
    distance = rows[:, 2] - profile
    support_distance = distance[support]
    surface_summary: dict[str, Any] = {}
    for name, tolerance in CSV_BANDS:
        near = support & (np.abs(distance) <= tolerance)
        central = near & (np.abs(rows[:, 1]) <= CENTRAL_Y)
        surface_summary[name] = {
            "tolerance_m": float(tolerance),
            "count": int(near.sum()),
            "fraction_of_actual_type0_mk50_support": (float(near.sum()) / int(support.sum())) if support.any() else None,
            "central_abs_y_le_0p01_count": int(central.sum()),
            "central_abs_y_le_0p01_fraction_of_band": (float(central.sum()) / int(near.sum())) if near.any() else None,
        }

    fluid_footprint = fluid & finite_positions & np.isfinite(profile)
    fluid_footprint &= (rows[:, 0] >= PROFILE[0, 0]) & (rows[:, 0] <= PROFILE[-1, 0])
    fluid_footprint &= (rows[:, 1] >= BED_Y[0]) & (rows[:, 1] <= BED_Y[1])
    below = fluid_footprint & (rows[:, 2] < profile)
    depths = profile[below] - rows[below, 2]
    overlap = pairwise_overlap(positions, type_codes)
    immutable_after = {
        "receipt": sha256_file(receipt_path),
        "report": sha256_file(report_path),
        "xml": sha256_file(xml_path),
        "source_definition": sha256_file(source_path),
        "actual_request": sha256_file(actual_request_path),
    }
    qa_immutable_after = {
        "receipt": sha256_file(qa_receipt_path),
        "provenance": sha256_file(qa_provenance_path),
        "native_report": sha256_file(qa_native_path),
    }


    checks = {
        "official_partvtk_frame0_bound_from_root175": True,
        "root175_initial_qa_receipt_completed": True,
        "root175_initial_qa_reported_all_checks_pass": True,
        "actual_total_matches_gencase_receipt": int(len(rows)) == int(binding["actual_counts"]["total_particles"]),
        "actual_fluid_matches_gencase_receipt": int(fluid.sum()) == int(binding["actual_counts"]["fluid_particles"]),
        "actual_3d_generated_xml": bool(xml["is_3d"]),
        "all_exported_fields_finite": bool(finite_rows.all()),
        "idp_unique_and_consecutive": bool(id_consecutive),
        "type_and_mk_fields_integral": bool(types_integral and markers_integral),
        "all_type0_type1_type3_spatial_pairs_no_overlap": bool(overlap["all_group_pairs_zero_overlap"]),
        "immutable_small_inputs_unchanged": immutable_before == immutable_after,
        "root175_qa_metadata_unchanged": qa_immutable_before == qa_immutable_after,
    }
    report = {
        "schema": SCHEMA,
        "status": "completed_root175_csv_frame0_diagnostic",
        "diagnostic_only": True,
        "all_reported_structural_checks_pass": bool(all(checks.values())),
        "checks": checks,
        "case_id": binding["case_id"],
        "condition_id": binding["condition_id"],
        "physical_case_id": binding["physical_case_id"],
        "source_arrays_modified": False,
        "source_arrays_dropped_or_masked": False,
        "initial_qa_dependency": {
            "status": "actual_root175_completed_structural_qa_bound",
            "pass_assumed": False,
            "initial_qa_pass_assumed": False,
            "reported_pass": True,
            "receipt_bound": True,
            "receipt": str(qa_receipt_path),
            "receipt_sha256": qa_immutable_before["receipt"],
            "provenance_report": str(qa_provenance_path),
            "provenance_report_sha256": qa_immutable_before["provenance"],
            "native_report": str(qa_native_path),
            "native_report_sha256": qa_immutable_before["native_report"],
            "official_csv": str(csv_path),
            "official_csv_sha256_opaque": binding["initial_qa_official_csv_sha256_opaque"],
            "coverage_does_not_grant_dynamic_acceptance": True,
        },
        "genuine_gencase": {
            "attempt_id": binding["genuine_gencase_attempt_id"],
            "receipt": str(receipt_path),
            "receipt_sha256": immutable_before["receipt"],
            "prepared_input_report": str(report_path),
            "prepared_input_report_sha256": immutable_before["report"],
            "generated_xml": str(xml_path),
            "generated_xml_sha256": immutable_before["xml"],
            "generated_bi4": str(bi4_path),
            "generated_bi4_sha256_declared": binding["generated_bi4_sha256_declared"],
            "generated_bi4_bytes_declared": int(binding["generated_bi4_bytes_declared"]),
            "actual_counts": binding["actual_counts"],
        },
        "official_partvtk": {
            "execution_owner": binding["actual_initial_qa_attempt_id"],
            "execution_receipt": str(qa_receipt_path),
            "execution_receipt_sha256": qa_immutable_before["receipt"],
            "executable": str(partvtk_path),
            "executable_sha256": binding["partvtk_sha256"],
            "command": None,
            "frame_index": 0,
            "csv": str(csv_path),
            "csv_sha256": csv_before,
            "csv_sha256_after": csv_after,
            "csv_sha256_opaque": binding["initial_qa_official_csv_sha256_opaque"],
            "csv_hash_source": "actual strict CPU worker verifies before/after bytes against Root175 opaque report hash",
            "worker_rehashed_csv_bytes": True,
            "csv_fields": CSV_FIELDS,
            "h5_or_xdmf_used": False,
            "launched_by_this_worker": False,
            "official_export_completed_before_fresh075": True,
        },
        "frame_zero": {
            "row_count": int(len(rows)),
            "type_counts": type_counts,
            "solver_dimension": 3,
            "nonfinite_row_count": int((~finite_rows).sum()),
            "nonfinite_position_count": int((~finite_positions).sum()),
            "mass_positive_count": int(np.sum(np.isfinite(rows[:, 7]) & (rows[:, 7] > 0))),
            "density_positive_count": int(np.sum(np.isfinite(rows[:, 11]) & (rows[:, 11] > 0))),
            "maximum_initial_velocity_m_s": float(np.nanmax(np.abs(rows[:, 8:11]))) if len(rows) else None,
        },
        "uid_and_finite": {
            "idp_integral": id_integral,
            "idp_unique": id_unique,
            "idp_consecutive_zero_based": id_consecutive,
            "idp_uid_digest": uid_digest,
            "nonfinite_row_count": int((~finite_rows).sum()),
        },
        "spatial_overlap": overlap,
        "central_fixed_bed_support": {
            "support_identity": "actual CSV Type=0 and Mk=50 in exact x profile and -0.15<=y<=0.15",
            "actual_type0_mk50_support_count": int(support.sum()),
            "mk50_is_mixed_geometry_cohort": True,
            "bed_only_claim": False,
            "surface_bands_m": [0.5 * DP_M, DP_M, 2.0 * DP_M],
            "central_y_band_m": [-CENTRAL_Y, CENTRAL_Y],
            "surface_counts_global": surface_summary,
            "segments": segment_records(support, rows[:, 0], rows[:, 1], distance),
            "y_levels_m": sorted(float(value) for value in np.unique(rows[support, 1]))[:256],
            "y_level_count": int(np.unique(rows[support, 1]).size),
            "relative_layers_dp": (
                [{"layer": int(layer), "count": int(count)} for layer, count in zip(*np.unique(np.rint(support_distance / DP_M).astype(np.int64), return_counts=True))]
                if support.any() else []
            ),
        },
        "fluid_initial_profile_separation": {
            "actual_fluid_count": int(fluid.sum()),
            "fluid_rows_in_exact_bed_footprint": int(fluid_footprint.sum()),
            "fluid_rows_outside_exact_bed_footprint": int(fluid.sum() - fluid_footprint.sum()),
            "below_profile_count": int(below.sum()),
            "below_profile_fraction_of_actual_fluid": (float(below.sum()) / int(fluid.sum())) if fluid.any() else None,
            "below_profile_fraction_of_bed_footprint_fluid": (float(below.sum()) / int(fluid_footprint.sum())) if fluid_footprint.any() else None,
            "max_below_profile_depth_m": float(np.max(depths)) if depths.size else 0.0,
            "minimum_profile_distance_m": float(np.min(distance[fluid_footprint])) if fluid_footprint.any() else None,
            "no_initial_fluid_below_profile": not bool(below.any()),
        },
        "audit_contract": {
            "frame_indices": [0],
            "dp_m": DP_M,
            "profile_nodes_xz_m": PROFILE.tolist(),
            "bed_y_bounds_m": list(BED_Y),
            "central_abs_y_le_0p01_m": True,
            "bed_marker_mk": BED_MK,
            "actual_type0_mk50_filter": True,
            "surface_bands_m": [0.5 * DP_M, DP_M, 2.0 * DP_M],
            "full_fluid_below_profile_evidence": True,
            "uid_finite_and_nooverlap": True,
            "no_initial_qa_pass_assumption": True,
            "initial_qa_receipt_bound": True,
            "no_dynamic_acceptance": True,
            "no_full16_authorization": True,
        },
        "interpretation_boundary": {
            "mk50_range_is_not_bed_only": True,
            "initial_partvtk_support_is_geometry_diagnostic_only": True,
            "initial_qa_status_root175_actual_structural_pass_bound": True,
            "dynamic_solver_cause_unassigned": True,
            "no_threshold_relaxation": True,
            "root_manual_review_required": True,
            "full801_remains_disabled": True,
        },
    }
    out = output / "b071-direct-native-initial-fixed-bed-coverage.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def synthetic_check() -> None:
    rows = np.asarray([
        [0.0, 0.0, 0.0, 0, 0, 0, 40, 1, 0, 0, 0, 1000, 0],
        [0.02, 0.0, 0.0, 0, 1, 0, 40, 1, 0, 0, 0, 1000, 0],
        [0.0, 0.0, 0.02, 0, 2, 3, 0, 1, 0, 0, 0, 1000, 0],
    ], dtype=np.float64)
    support = (rows[:, 5] == 0) & (rows[:, 6] == 40)
    assert segment_records(support, rows[:, 0], rows[:, 1], rows[:, 2] - bed_profile_z(rows[:, 0]))[0]["actual_type0_mk50_support_count"] == 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.check:
        synthetic_check()
        print("fresh075 Root175 CSV coverage synthetic checks passed")
        return 0
    if args.binding is None or args.output_dir is None:
        parser.error("--binding and --output-dir are required")
    run(args.binding.resolve(), args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

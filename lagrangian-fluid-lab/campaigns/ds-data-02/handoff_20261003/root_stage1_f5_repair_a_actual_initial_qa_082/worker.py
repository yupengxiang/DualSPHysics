#!/usr/bin/env python3
"""A061-specific native initial-state QA for the genuine Root075 GenCase.

The worker is intentionally additive and source-bound.  It exports the fresh
GenCase BI4 with official PartVTK, then checks the actual native rows against
the A061 XML and the exact explicit source profile.  It does not alter the
GenCase attempt, rescale weights, or make a solver/qualification claim.
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


SCHEMA = "ds02.f5.a061.actual-native-qa.v1"
TYPE_CODES = {"fixed": 0, "moving": 1, "floating": 2, "fluid": 3}
CSV_FIELDS = [
    "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Type", "Mk",
    "Mass [kg]", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]",
    "Rhop [kg/m^3]", "Press [Pa]",
]


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_csv(path: Path) -> np.ndarray:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
        reader = csv.reader(stream)
        header: list[str] | None = None
        for row in reader:
            if "Pos.x [m]" in row and "Idp" in row:
                header = [item.strip() for item in row]
                break
        if header is None:
            raise ValueError(f"official PartVTK header missing: {path}")
        missing = [field for field in CSV_FIELDS if field not in header]
        require(not missing, f"PartVTK CSV missing columns: {missing}")
        rows = np.loadtxt(
            stream,
            delimiter=",",
            usecols=[header.index(field) for field in CSV_FIELDS],
            ndmin=2,
        )
    return np.asarray(rows, dtype=np.float64)


def read_typed_xml(xml_path: Path) -> tuple[ET.Element, ET.Element, list[dict[str, int | str]]]:
    root = ET.parse(xml_path).getroot()
    require(root.tag == "case", "generated XML root is not case")
    data2d = root.find("./execution/constants/data2d")
    require(data2d is not None and data2d.get("value", "true").lower() == "false", "generated XML is not 3-D")
    particles = root.find("./execution/particles")
    require(particles is not None, "generated XML particles block missing")
    blocks: list[dict[str, int | str]] = []
    for node in particles:
        if node.tag not in TYPE_CODES:
            continue
        blocks.append(
            {
                "type_name": node.tag,
                "type": TYPE_CODES[node.tag],
                "mk": int(node.get("mk", "-1")),
                "begin": int(node.get("begin", "-1")),
                "count": int(node.get("count", "-1")),
            }
        )
    require(bool(blocks), "generated XML has no typed particle blocks")
    return root, particles, blocks


def profile_interpolator(nodes: list[list[float]]):
    points = np.asarray(nodes, dtype=np.float64)
    require(points.ndim == 2 and points.shape == (7, 2), "A061 source profile must contain seven x/z nodes")
    require(np.all(np.diff(points[:, 0]) > 0), "A061 source profile x nodes must increase")

    def evaluate(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        values = np.full(x.shape, np.nan, dtype=np.float64)
        covered = (x >= points[0, 0]) & (x <= points[-1, 0])
        if not np.any(covered):
            return values, covered
        for index in range(len(points) - 1):
            left, right = points[index], points[index + 1]
            mask = covered & (x >= left[0]) & (x <= right[0])
            if np.any(mask):
                fraction = (x[mask] - left[0]) / (right[0] - left[0])
                values[mask] = left[1] + fraction * (right[1] - left[1])
        return values, covered

    return points, evaluate


def coordinate_sets(rows: np.ndarray) -> dict[int, set[tuple[float, float, float]]]:
    return {
        code: {tuple(float(value) for value in row) for row in rows[rows[:, 5] == code, :3]}
        for code in (0, 1, 2, 3)
    }


def profile_support_diagnostic(
    rows: np.ndarray,
    profile: np.ndarray,
    evaluate_profile,
    *,
    dp_m: float,
    bed_y_bounds: tuple[float, float],
) -> dict[str, object]:
    fixed_mk40 = rows[(rows[:, 5] == 0) & (np.rint(rows[:, 6]) == 40)]
    interior_y = (fixed_mk40[:, 1] > bed_y_bounds[0] + 1.0e-10) & (
        fixed_mk40[:, 1] < bed_y_bounds[1] - 1.0e-10
    )
    interior = fixed_mk40[interior_y]
    top_z, covered = evaluate_profile(interior[:, 0]) if len(interior) else (
        np.empty(0), np.empty(0, dtype=bool)
    )
    segments = []
    for left, right in zip(profile[:-1, 0], profile[1:, 0]):
        in_segment = (interior[:, 0] >= left - 1.0e-10) & (interior[:, 0] <= right + 1.0e-10)
        near_profile = in_segment & covered & (np.abs(interior[:, 2] - top_z) <= dp_m / 2.0 + 1.0e-10)
        segment = {
            "x_left_m": float(left),
            "x_right_m": float(right),
            "actual_mk40_rows_in_strict_bed_y_domain": int(in_segment.sum()),
            "actual_mk40_rows_within_half_dp_of_source_profile": int(near_profile.sum()),
        }
        if np.any(in_segment):
            segment.update(
                {
                    "z_min_m": float(interior[in_segment, 2].min()),
                    "z_max_m": float(interior[in_segment, 2].max()),
                    "y_levels": sorted(float(value) for value in np.unique(interior[in_segment, 1])),
                }
            )
        segments.append(segment)
    return {
        "cohort_filter": "native Type=0, Mk=40, strict interior -0.15<y<0.15",
        "mixed_boundary_cohort_warning": True,
        "support_is_diagnostic_only": True,
        "mk40_total_rows": int(len(fixed_mk40)),
        "mk40_rows_in_strict_bed_y_domain": int(len(interior)),
        "source_profile_nodes_xz_m": profile.tolist(),
        "source_profile_segments": segments,
        "continuous_bed_completeness_claim": False,
        "mk40_bed_only_claim": False,
    }


def run(binding_path: Path, output_dir: Path) -> dict[str, object]:
    binding = json.loads(Path(binding_path).read_text(encoding="utf-8"))
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    runtime_files = {"stdout.log", "execution-receipt.json"}
    preexisting = [path.name for path in output.iterdir() if path.name not in runtime_files]
    require(not preexisting, f"fresh QA output directory contains prior artifacts: {preexisting}")

    case_id = binding["case_id"]
    gencase_root = Path(binding["gencase_output_root"]).resolve()
    require(output != gencase_root, "QA output must not equal the genuine GenCase attempt root")
    receipt_path = Path(binding["gencase_receipt"]).resolve()
    report_path = Path(binding["prepared_input_report"]).resolve()
    xml_path = Path(binding["generated_xml"]).resolve()
    bi4_path = Path(binding["generated_bi4"]).resolve()
    source_path = Path(binding["source_definition"]).resolve()
    patch_path = Path(binding["candidate_patch"]).resolve()

    receipt_bytes_before = sha256(receipt_path)
    report_bytes_before = sha256(report_path)
    xml_bytes_before = sha256(xml_path)
    bi4_bytes_before = sha256(bi4_path)
    source_bytes_before = sha256(source_path)
    patch_bytes_before = sha256(patch_path)
    require(receipt_bytes_before == binding["gencase_receipt_sha256"], "genuine075 receipt hash mismatch")
    require(report_bytes_before == binding["prepared_input_report_sha256"], "genuine075 prepared report hash mismatch")
    require(xml_bytes_before == binding["generated_xml_sha256"], "genuine075 generated XML hash mismatch")
    require(bi4_bytes_before == binding["generated_bi4_sha256"], "genuine075 generated BI4 hash mismatch")
    require(source_bytes_before == binding["source_definition_sha256"], "A061 source definition hash mismatch")
    require(patch_bytes_before == binding["candidate_patch_sha256"], "A061 candidate patch hash mismatch")

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for key, expected in {
        "status": "completed",
        "returncode": 0,
        "total_particles": binding["expected_total_particles"],
        "fluid_particles": binding["expected_fluid_particles"],
        "solver_dimension_from_gencase": 3,
    }.items():
        require(receipt.get(key) == expected, f"genuine075 receipt {key}={receipt.get(key)!r}, expected {expected!r}")
    require(Path(receipt["output_root"]).resolve() == gencase_root, "receipt output root mismatch")

    prepared = json.loads(report_path.read_text(encoding="utf-8"))
    require(prepared.get("case_id") == case_id, "prepared report case mismatch")
    require(prepared.get("definition_sha256") == binding["source_definition_sha256"], "prepared report source hash mismatch")
    require(prepared.get("actual_total_particles") == binding["expected_total_particles"], "prepared report total mismatch")
    require(prepared.get("generated_xml_particle_counts", {}).get("fluid") == binding["expected_fluid_particles"], "prepared report fluid mismatch")
    candidate_patch = json.loads(patch_path.read_text(encoding="utf-8"))
    require(candidate_patch.get("condition_id") == binding["condition_id"], "candidate condition binding mismatch")
    require(candidate_patch.get("derived_definition", {}).get("sha256") == binding["source_definition_sha256"], "candidate derived definition hash mismatch")
    require(candidate_patch.get("geometry_semantics", {}).get("profile_nodes_xz_m") == binding["source_profile_xz_m"], "candidate profile binding mismatch")

    source_root = ET.parse(source_path).getroot()
    source_triangles = source_root.findall(".//drawtriangles")
    require(len(source_triangles) == 1, "A061 source must contain one explicit triangle mesh")
    source_points = source_triangles[0].findall("./points/point")
    source_faces = source_triangles[0].findall("./triangles/triangle")
    require(len(source_points) == 156 and len(source_faces) == 52, "A061 source mesh is not 156 points/52 triangles")
    require(not source_root.findall(".//drawfilestl") and not source_root.findall(".//shapeout"), "A061 source still contains STL/shapeout nodes")
    profile, evaluate_profile = profile_interpolator(binding["source_profile_xz_m"])
    source_point_xz = np.asarray([[float(node.get("x")), float(node.get("z"))] for node in source_points])
    profile_nodes_present = all(
        np.any(np.max(np.abs(source_point_xz - node), axis=1) <= 1.0e-12) for node in profile
    )
    require(profile_nodes_present, "A061 exact profile nodes are absent from the source mesh")

    root, particles, xml_blocks = read_typed_xml(xml_path)
    require(int(particles.get("np", "-1")) == binding["expected_total_particles"], "generated XML np mismatch")
    require(len(root.findall(".//drawtriangles/points/point")) == 156, "generated XML mesh point count mismatch")
    require(len(root.findall(".//drawtriangles/triangles/triangle")) == 52, "generated XML mesh triangle count mismatch")
    generated_triangles = root.find(".//drawtriangles")
    require(generated_triangles is not None, "generated XML explicit mesh missing")
    require(generated_triangles.attrib == source_triangles[0].attrib, "generated mesh attributes differ from source")
    require(
        [node.attrib for node in generated_triangles.findall("./points/point")]
        == [node.attrib for node in source_triangles[0].findall("./points/point")],
        "generated mesh points differ from source",
    )
    require(
        [node.attrib for node in generated_triangles.findall("./triangles/triangle")]
        == [node.attrib for node in source_triangles[0].findall("./triangles/triangle")],
        "generated mesh triangles differ from source",
    )

    csv_path = output / f"{case_id}-initial-all.csv"
    partvtk = Path(binding["partvtk"]).resolve()
    command = [
        str(partvtk), "-filedata", str(bi4_path), "-filexml", str(xml_path), "-threads:2",
        "-savecsv", str(csv_path), "-onlytype:+all",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1",
    ]
    process = subprocess.run(command, cwd=output, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    require(process.returncode == 0, f"official PartVTK failed: {process.stdout[-2000:]}")
    rows = load_csv(csv_path)
    require(rows.shape == (binding["expected_total_particles"], len(CSV_FIELDS)), f"native CSV shape mismatch: {rows.shape}")
    require(np.isfinite(rows).all(), "native rows contain nonfinite values")

    integer_columns = rows[:, [3, 4, 5, 6]]
    require(np.equal(integer_columns, np.rint(integer_columns)).all(), "native categorical fields are nonintegral")
    require(np.all(rows[:, 3] == 0), "native Zone is not zero")
    order = np.argsort(rows[:, 4])
    rows = rows[order]
    require(np.array_equal(rows[:, 4], np.arange(len(rows), dtype=np.float64)), "native Idp is not consecutive and unique")
    require(set(int(value) for value in np.unique(rows[:, 5])) == set(binding["expected_type_codes"]), "native type set mismatch")
    require(np.all(rows[:, 7] > 0) and np.all(rows[:, 11] > 0), "native mass/density is not positive")
    max_velocity = float(np.abs(rows[:, 8:11]).max())
    require(max_velocity <= binding["max_initial_velocity_m_s"], f"initial velocity exceeds limit: {max_velocity}")

    covered = np.zeros(len(rows), dtype=bool)
    typed_blocks: list[dict[str, int | str]] = []
    for block in xml_blocks:
        begin, count = int(block["begin"]), int(block["count"])
        require(begin >= 0 and count >= 0 and begin + count <= len(rows), f"invalid XML typed block: {block}")
        selection = slice(begin, begin + count)
        require(not covered[selection].any(), f"overlapping XML typed ranges: {block}")
        require(np.all(rows[selection, 5] == block["type"]), f"native type differs from XML block: {block}")
        require(np.all(rows[selection, 6] == block["mk"]), f"native Mk differs from XML block: {block}")
        covered[selection] = True
        typed_blocks.append(block)
    require(covered.all(), "XML typed blocks do not cover every native Idp")
    fluid = rows[rows[:, 5] == 3]
    require(len(fluid) == binding["expected_fluid_particles"], "native fluid count mismatch")

    coords = rows[:, :3]
    unique_coordinate_count = len(np.unique(coords, axis=0))
    require(unique_coordinate_count == len(rows), "native coordinates are duplicated")
    by_type = coordinate_sets(rows)
    pairwise_overlap = {
        "fixed_moving": len(by_type[0] & by_type[1]),
        "fixed_fluid": len(by_type[0] & by_type[3]),
        "moving_fluid": len(by_type[1] & by_type[3]),
    }
    require(not any(pairwise_overlap.values()), f"fixed/moving/fluid spatial overlap: {pairwise_overlap}")

    fluid_mass = float(fluid[:, 7].sum())
    continuum_mass = float(binding["continuum_mass_kg"])
    mass_difference = fluid_mass - continuum_mass
    require(np.isfinite(mass_difference), "native fluid mass difference is nonfinite")

    bed_y_min, bed_y_max = (float(value) for value in binding["bed_y_bounds_m"])
    fluid_y_in_bed = (fluid[:, 1] >= bed_y_min - 1.0e-10) & (fluid[:, 1] <= bed_y_max + 1.0e-10)
    fluid_profile_z, profile_covered = evaluate_profile(fluid[:, 0])
    profile_unknown = fluid_y_in_bed & ~profile_covered
    below_bed = fluid_y_in_bed & profile_covered & (fluid[:, 2] < fluid_profile_z - binding["bed_clearance_tolerance_m"])
    require(not profile_unknown.any(), f"fluid rows fall outside exact source profile x domain: {int(profile_unknown.sum())}")
    require(not below_bed.any(), f"fluid rows below exact source bed profile: {int(below_bed.sum())}")

    support_diagnostic = profile_support_diagnostic(
        rows,
        profile,
        evaluate_profile,
        dp_m=float(binding["dp_m"]),
        bed_y_bounds=(bed_y_min, bed_y_max),
    )

    checks = {
        "fresh_genuine075_receipt_bound": True,
        "actual_total_particles_214385": int(len(rows)) == binding["expected_total_particles"],
        "actual_fluid_particles_40710": int(len(fluid)) == binding["expected_fluid_particles"],
        "actual_3d_xml_and_receipt": receipt.get("solver_dimension_from_gencase") == 3,
        "all_native_rows_finite": bool(np.isfinite(rows).all()),
        "all_native_mass_density_positive": bool(np.all(rows[:, 7] > 0) and np.all(rows[:, 11] > 0)),
        "all_native_idp_unique_consecutive": True,
        "native_type_mk_matches_xml": True,
        "zero_initial_velocity": max_velocity <= binding["max_initial_velocity_m_s"],
        "fixed_moving_fluid_spatial_no_overlap": not any(pairwise_overlap.values()),
        "fluid_initial_state_not_below_exact_source_bed": not below_bed.any() and not profile_unknown.any(),
        "native_fluid_mass_difference_reported_without_rescale": np.isfinite(mass_difference),
        "source_definition_unchanged": source_bytes_before == sha256(source_path),
        "genuine075_xml_bi4_unchanged": xml_bytes_before == sha256(xml_path) and bi4_bytes_before == sha256(bi4_path),
    }
    result: dict[str, object] = {
        "schema": SCHEMA,
        "case_id": case_id,
        "status": "actual_native_qa",
        "all_actual_checks_pass": bool(all(checks.values())),
        "checks": checks,
        "genuine_gencase": {
            "receipt": str(receipt_path),
            "receipt_sha256": receipt_bytes_before,
            "prepared_input_report": str(report_path),
            "prepared_input_report_sha256": report_bytes_before,
            "generated_xml": str(xml_path),
            "generated_xml_sha256": xml_bytes_before,
            "generated_bi4": str(bi4_path),
            "generated_bi4_sha256": bi4_bytes_before,
            "actual_total_particles": int(receipt["total_particles"]),
            "actual_fluid_particles": int(receipt["fluid_particles"]),
            "solver_dimension_from_gencase": int(receipt["solver_dimension_from_gencase"]),
        },
        "native_rows": {
            "total_particles": int(len(rows)),
            "fluid_particles": int(len(fluid)),
            "type_counts": {str(int(code)): int(np.sum(rows[:, 5] == code)) for code in np.unique(rows[:, 5])},
            "typed_blocks": typed_blocks,
            "unique_coordinate_count": int(unique_coordinate_count),
            "pairwise_spatial_overlap_counts": pairwise_overlap,
            "maximum_initial_velocity_m_s": max_velocity,
        },
        "native_fluid_mass": {
            "csv_mass_kg": fluid_mass,
            "continuum_mass_kg": continuum_mass,
            "difference_kg": mass_difference,
            "relative_difference": mass_difference / continuum_mass if continuum_mass else None,
            "mass_rescaled": False,
            "precision_note": "PartVTK CSV mass is reported; no weight mutation or rescaling is performed.",
        },
        "exact_source_profile": {
            "source_definition": str(source_path),
            "source_definition_sha256": source_bytes_before,
            "profile_nodes_xz_m": profile.tolist(),
            "bed_y_bounds_m": [bed_y_min, bed_y_max],
            "fluid_rows_in_bed_y_domain": int(fluid_y_in_bed.sum()),
            "fluid_rows_outside_bed_y_domain": int((~fluid_y_in_bed).sum()),
            "fluid_rows_outside_profile_x_domain": int(profile_unknown.sum()),
            "fluid_rows_below_profile": int(below_bed.sum()),
            "bed_clearance_tolerance_m": binding["bed_clearance_tolerance_m"],
        },
        "mk40_support_diagnostic": support_diagnostic,
        "provenance": {
            "partvtk": str(partvtk),
            "partvtk_sha256": sha256(partvtk),
            "official_csv": str(csv_path),
            "official_csv_sha256": sha256(csv_path),
            "output_root": str(output),
            "fresh_output_root": True,
            "q_n_granted": False,
            "production_approval": "none",
            "repair_success": "unknown_until_short_event_and_framewise_bed_audit",
        },
    }
    report_path_out = output / "a061-native-initial-qa.json"
    report_path_out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    require(result["all_actual_checks_pass"], f"A061 native QA failed: {json.dumps(result, sort_keys=True)}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.binding, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

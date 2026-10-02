#!/usr/bin/env python3
"""Read-only audit for the additive F6 .02/.0125 native mother.

The phase003 GenCase products are already consumed by the CPU receipts.  This
module does not regenerate them and does not launch a solver.  It recomputes
the fluid ledger from the PartVTK CSV derived from each raw GenCase BI4,
checks the generated native XML rigid contract, compares the continuous
geometry/control contract with the completed RIGID003/DP025 mother, and
records the actual boundary point extents.  A default simulation domain is
never promoted to a swept-domain pass: the fine cases remain pending a
solver MapRealPos or an additive, root-owned domain-only input repair.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import struct
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002"
CURRENT_ROOT = FAMILY_ROOT / "rigid_contract_003/dp020_dp0125_cpu_003"
CURRENT_MANIFEST = CURRENT_ROOT / "manifest.json"
CURRENT_GEOMETRY = CURRENT_ROOT / "physical_mother_geometry.json"
CURRENT_AUDIT = CURRENT_ROOT / "partvtk_002/strict_partvtk_rigid_audit_003.json"
DP025_ROOT = FAMILY_ROOT / "commensurate_dp025_rigid003"
DP025_MANIFEST = DP025_ROOT / "manifest.json"
DP025_GEOMETRY = DP025_ROOT / "physical_mother_geometry.json"
DP025_SIMPLE_RUNOUT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/"
    "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_COMMENSURATE_RIGID003_DP025/"
    "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_COMMENSURATE_RIGID003_DP025_SOLVER_QUAL_DP025_001/"
    "solver_output/Run.out"
)
DP025_WAVE_RUNOUT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/"
    "F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025/"
    "F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025_SOLVER_QUAL_DP025_DOMAIN_X_REPAIR_001/"
    "solver_output/Run.out"
)
DP025_WAVE_MOTION = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/"
    "F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025/"
    "F6_HANDOFF_20261002_WAVE_NO_CONTACT_COMMENSURATE_RIGID003_DP025_SOLVER_QUAL_DP025_DOMAIN_X_REPAIR_001/"
    "solver_output/WavePaddle_mkb0010.csv"
)
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6")
OUTPUT = CURRENT_ROOT / "equivalence_domain_audit_001.json"

RHO_WATER = 1000.0
FLUID_MASS_TOLERANCE_KG = 0.01
SERIALIZED_INERTIA_TOLERANCE = 5.0e-5
FLOAT32_TOLERANCE = 2.0e-5
WAVE_DISPLACEMENT_M = 0.0437819
KERNEL_PADDING_MULTIPLIER = 2.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(path: Path) -> dict[str, Any]:
    path = path.resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _float_attrs(node: ET.Element, names: str) -> list[float]:
    return [float(node.attrib[name]) for name in names]


def _summary_count(summary: ET.Element, name: str) -> int:
    node = summary.find(name)
    return int(node.attrib["count"]) if node is not None else 0


def parse_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = root.find("./execution/particles")
    constants = root.find("./execution/constants")
    summary = particles.find("_summary") if particles is not None else None
    floating = particles.find("floating") if particles is not None else None
    simdomain = root.find("./execution/parameters/simulationdomain")
    if particles is None or constants is None or summary is None or floating is None:
        raise ValueError(f"generated XML lacks native blocks: {path}")
    positions = summary.find("positions")
    if positions is None:
        raise ValueError(f"generated XML lacks positions: {path}")
    massfluid = float(constants.find("massfluid").attrib["value"])
    massbound = float(constants.find("massbound").attrib["value"])
    dp = float(constants.find("dp").attrib["value"])
    center = _float_attrs(floating.find("center"), "xyz")
    inertia = _float_attrs(floating.find("inertia"), "xyz")
    massbody = float(floating.find("massbody").attrib["value"])
    counts = {name: _summary_count(summary, name) for name in ("fixed", "moving", "floating", "fluid")}

    drawboxes: list[dict[str, Any]] = []
    for node in root.findall("./casedef/geometry/commands/mainlist/drawbox"):
        point = node.find("point")
        size = node.find("size")
        fill = node.findtext("boxfill", default="")
        if point is None or size is None:
            continue
        drawboxes.append({
            "comment": node.attrib.get("cmt", ""),
            "fill": fill,
            "point_m": _float_attrs(point, "xyz"),
            "size_m": _float_attrs(size, "xyz"),
        })

    piston = root.find("./execution/special/wavepaddles/piston")
    wave = None
    if piston is not None:
        wave = {key: float(piston.find(key).attrib["value"]) for key in ("depth", "waveheight", "waveperiod", "ramp")}
        wave["mkbound"] = int(piston.find("mkbound").attrib["value"])
        wave["waveorder"] = int(piston.find("waveorder").attrib["value"])
        wave["pistondir"] = _float_attrs(piston.find("pistondir"), "xyz")

    source_domain = None
    if simdomain is not None:
        source_domain = {
            "posmin": dict(simdomain.find("posmin").attrib),
            "posmax": dict(simdomain.find("posmax").attrib),
        }
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "solver_dimension": 3 if constants.findtext("data2d", default="false") != "true" else 2,
        "dp_m": dp,
        "particle_np": int(particles.attrib["np"]),
        "particle_nb": int(particles.attrib["nb"]),
        "particle_nbf": int(particles.attrib["nbf"]),
        "type_counts": counts,
        "positions_bounds_m": {
            "posmin": _float_attrs(positions.find("posmin"), "xyz"),
            "posmax": _float_attrs(positions.find("posmax"), "xyz"),
        },
        "massfluid_kg": massfluid,
        "massbound_kg": massbound,
        "xml_fluid_mass_kg": counts["fluid"] * massfluid,
        "floating_contract": {
            "massbody_kg": massbody,
            "masspart_kg": float(floating.find("masspart").attrib["value"]),
            "center_m": center,
            "inertia_diag_kg_m2": inertia,
        },
        "drawboxes": drawboxes,
        "wave_piston": wave,
        "simulationdomain_source": source_domain,
    }


def parse_partvtk_csv(path: Path, massfluid: float) -> dict[str, Any]:
    """Recompute type counts and bounds from the CSV exported from raw BI4."""
    header_seen = False
    counts = {"fixed": 0, "moving": 0, "floating": 0, "fluid": 0, "unknown": 0}
    bounds: dict[str, list[list[float]] | None] = {name: None for name in counts}
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            if row[0].strip() == "Pos.x [m]":
                header_seen = True
                continue
            if not header_seen or len(row) < 10:
                continue
            try:
                xyz = [float(row[0]), float(row[1]), float(row[2])]
                kind = int(row[9].strip())
            except (ValueError, IndexError):
                continue
            name = {0: "fixed", 1: "moving", 2: "floating", 3: "fluid"}.get(kind, "unknown")
            counts[name] += 1
            current = bounds[name]
            if current is None:
                bounds[name] = [[value, value] for value in xyz]
            else:
                for axis, value in enumerate(xyz):
                    current[axis][0] = min(current[axis][0], value)
                    current[axis][1] = max(current[axis][1], value)
    if not header_seen:
        raise ValueError(f"PartVTK CSV particle header missing: {path}")
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "type_counts": counts,
        "bounds_m": bounds,
        "fluid_mass_kg_from_xml_massfluid": counts["fluid"] * massfluid,
        "fluid_mass_per_particle_kg": massfluid,
    }


def parse_bound_vtk(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    match = re.search(rb"POINTS\s+(\d+)\s+float\n", data)
    if match is None:
        raise ValueError(f"POINTS header missing: {path}")
    count = int(match.group(1))
    offset = match.end()
    values = struct.unpack(">" + "f" * count * 3, data[offset : offset + count * 12])
    points = [values[index : index + 3] for index in range(0, len(values), 3)]
    point_data = re.compile(rb"POINT_DATA\s+\d+\n").search(data, offset + count * 12)
    lookup = re.compile(rb"LOOKUP_TABLE\s+default\n").search(data, point_data.end()) if point_data else None
    field = re.compile(rb"FIELD\s+FieldData\s+2\n").search(data, lookup.end()) if lookup else None
    type_header = re.compile(rb"Type\s+1\s+\d+\s+unsigned_char\n").search(data, field.end()) if field else None
    if type_header is None:
        raise ValueError(f"Type field missing: {path}")
    types = data[type_header.end() : type_header.end() + count]
    groups: dict[str, list[tuple[float, float, float]]] = {"fixed": [], "moving": [], "floating": [], "unknown": []}
    names = {0: "fixed", 1: "moving", 2: "floating"}
    for point, type_id in zip(points, types):
        groups[names.get(type_id, "unknown")].append(point)

    def group_bounds(items: list[tuple[float, float, float]]) -> list[list[float]] | None:
        if not items:
            return None
        return [[min(point[axis] for point in items), max(point[axis] for point in items)] for axis in range(3)]

    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "point_count": count,
        "type_counts": {name: len(items) for name, items in groups.items() if items},
        "type_bounds_m": {name: group_bounds(items) for name, items in groups.items() if items},
        "solver_dimension": 3,
    }


def parse_motion(path: Path) -> dict[str, Any]:
    values: list[float] = []
    times: list[float] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or not line[0].isdigit() or ";" not in line:
            continue
        fields = line.split(";")
        if len(fields) < 2:
            continue
        times.append(float(fields[0]))
        values.append(float(fields[1]))
    if not values:
        raise ValueError(f"wave motion data has no numeric rows: {path}")
    return {
        "source": ref(path),
        "rows": len(values),
        "time_s": [min(times), max(times)],
        "position_m": [min(values), max(values)],
        "amplitude_peak_m": max(abs(min(values)), abs(max(values))),
    }


def map_real_pos(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    result: dict[str, Any] = {"source": ref(path)}
    for label in ("border", "final"):
        match = re.search(rf"MapRealPos\({label}\)=\(([^)]*)\)-\(([^)]*)\)", text)
        if match:
            result[label] = {
                "min_m": [float(x.strip()) for x in match.group(1).split(",")],
                "max_m": [float(x.strip()) for x in match.group(2).split(",")],
            }
    return result


def canonical_contract(geometry: dict[str, Any]) -> dict[str, Any]:
    return {
        "fluid": geometry["fluid"],
        "fluid_volume_m3": geometry["continuous_fluid_volume_m3"],
        "tank": geometry["tank"],
        "body": geometry["body"],
        "body_inertia_kg_m2": geometry["body_inertia_kg_m2"],
        "paddle": geometry["paddle"],
        "initial_submerged_body_volume_m3": geometry["initial_submerged_body_volume_m3"],
    }


def _case_by(manifest: dict[str, Any], mechanism: str, resolution: str) -> dict[str, Any]:
    for case in manifest["cases"]:
        if case["mechanism_id"] == mechanism and case["resolution_id"] == resolution:
            return case
    raise KeyError((mechanism, resolution))


def _source_box(boxes: list[dict[str, Any]], text: str) -> dict[str, Any]:
    for box in boxes:
        if text in box["comment"].lower():
            return box
    raise KeyError(text)


def audit_case(case: dict[str, Any], audit_row: dict[str, Any], canonical_case: dict[str, Any], current_geometry: dict[str, Any], canonical_geometry: dict[str, Any], motion: dict[str, Any] | None) -> dict[str, Any]:
    cid = str(case["case_id"])
    audit_xml = audit_row["generated_xml_rigid_contract"]["xml"]
    xml_path = Path(audit_xml)
    xml = parse_xml(xml_path)
    csv_path = Path(audit_row["partvtk"]["csv"])
    csv_audit = parse_partvtk_csv(csv_path, xml["massfluid_kg"])
    prefix = xml_path.with_suffix("")
    bi4 = prefix.with_suffix(".bi4")
    bound = prefix.with_name(prefix.name + "_Bound.vtk")
    receipt = Path(audit_row["gencase"]["receipt"])
    if not all(path.is_file() for path in (bi4, bound, receipt)):
        raise FileNotFoundError(f"raw GenCase audit inputs missing for {cid}")
    bound_audit = parse_bound_vtk(bound)
    source_contract = canonical_contract(current_geometry)
    reference_contract = canonical_contract(canonical_geometry)

    expected_inertia = [row[i] for i, row in enumerate(canonical_geometry["body_inertia_kg_m2"])]
    xml_inertia = xml["floating_contract"]["inertia_diag_kg_m2"]
    inertia_errors = [abs(a - b) for a, b in zip(xml_inertia, expected_inertia)]
    fluid_expected = float(case["expected_fluid_mass_kg"])
    current_wave = xml["wave_piston"]
    wave_controls = None
    if motion is not None:
        wave_controls = {
            "xml": current_wave,
            "motion": motion,
            "height_matches_canonical": current_wave is not None and abs(current_wave["waveheight"] - 0.12) <= 1e-12,
            "period_matches_canonical": current_wave is not None and abs(current_wave["waveperiod"] - 1.6) <= 1e-12,
            "depth_matches_canonical": current_wave is not None and abs(current_wave["depth"] - 0.84) <= 1e-12,
            "ramp_matches_canonical": current_wave is not None and abs(current_wave["ramp"] - 3.0) <= 1e-12,
            "motion_sweep_in_canonical_physical_envelope": motion["amplitude_peak_m"] <= WAVE_DISPLACEMENT_M + 2.0e-6,
        }

    # A phase-aligned direct drawbox intentionally puts the first native
    # boundary layer at physical plane + dp/2.  Keep this visible instead of
    # comparing it to exact source planes and silently calling it a wall pass.
    tank = current_geometry["tank"]
    tank_hi = [tank["low"][axis] + tank["size"][axis] for axis in range(3)]
    fixed_bounds = bound_audit["type_bounds_m"].get("fixed")
    phase_offsets = None
    if fixed_bounds:
        phase_offsets = {
            "low_from_physical_low_m": [fixed_bounds[axis][0] - tank["low"][axis] for axis in range(3)],
            "high_from_physical_high_m": [fixed_bounds[axis][1] - tank_hi[axis] for axis in range(3)],
            "expected_low_m": [xml["dp_m"] / 2.0] * 3,
            "expected_high_m": [-xml["dp_m"] / 2.0] * 3,
            "within_float32_tolerance": all(
                abs(fixed_bounds[axis][0] - (tank["low"][axis] + xml["dp_m"] / 2.0)) <= FLOAT32_TOLERANCE
                and abs(fixed_bounds[axis][1] - (tank_hi[axis] - xml["dp_m"] / 2.0)) <= FLOAT32_TOLERANCE
                for axis in range(3)
            ),
        }

    moving_bounds = bound_audit["type_bounds_m"].get("moving")
    moving_sweep = None
    if moving_bounds is not None and motion is not None:
        moving_sweep = {
            "native_initial_bounds_m": moving_bounds,
            "prescribed_displacement_range_m": motion["position_m"],
            "swept_x_bounds_m": [moving_bounds[0][0] + motion["position_m"][0], moving_bounds[0][1] + motion["position_m"][1]],
            "sweep_plus_two_kernel_halfwidth_m": 2.0 * xml["dp_m"] * KERNEL_PADDING_MULTIPLIER,
        }
        moving_sweep["guarded_swept_x_bounds_m"] = [
            moving_sweep["swept_x_bounds_m"][0] - moving_sweep["sweep_plus_two_kernel_halfwidth_m"],
            moving_sweep["swept_x_bounds_m"][1] + moving_sweep["sweep_plus_two_kernel_halfwidth_m"],
        ]

    expected_types = {"fixed": int(audit_row["actual_type_counts"]["fixed"]), "moving": int(audit_row["actual_type_counts"]["moving"]), "floating": int(audit_row["actual_type_counts"]["floating"]), "fluid": int(audit_row["actual_type_counts"]["fluid"])}
    actual_types = csv_audit["type_counts"]
    return {
        "case_id": cid,
        "mechanism_id": case["mechanism_id"],
        "resolution_id": case["resolution_id"],
        "dp_m": xml["dp_m"],
        "raw_inputs": {"gencase_receipt": ref(receipt), "generated_bi4": ref(bi4), "generated_xml": ref(xml_path), "bound_vtk": ref(bound), "partvtk_csv": ref(csv_path)},
        "xml_native_contract": xml,
        "partvtk_recomputed_from_bi4_export": csv_audit,
        "bound_native_extents": bound_audit,
        "continuous_contract_comparison": {
            "current": source_contract,
            "dp025_reference": reference_contract,
            "exact_json_equivalence": source_contract == reference_contract,
            "control_sha256_equal_to_dp025": case["control"]["sha256"] == canonical_case["control"]["sha256"],
            "control_rows_and_window_equal_to_dp025": case["control"]["rows"] == canonical_case["control"]["rows"] and case["control"]["window_s"] == canonical_case["control"]["window_s"],
        },
        "authoritative_mass_and_rigid_checks": {
            "xml_type_counts_equal_partvtk_recomputed": all(expected_types[name] == actual_types[name] for name in expected_types),
            "xml_fluid_mass_kg": xml["xml_fluid_mass_kg"],
            "partvtk_fluid_mass_kg": csv_audit["fluid_mass_kg_from_xml_massfluid"],
            "expected_continuous_fluid_mass_kg": fluid_expected,
            "xml_fluid_mass_error_kg": xml["xml_fluid_mass_kg"] - fluid_expected,
            "partvtk_fluid_mass_error_kg": csv_audit["fluid_mass_kg_from_xml_massfluid"] - fluid_expected,
            "fluid_mass_within_tolerance": abs(csv_audit["fluid_mass_kg_from_xml_massfluid"] - fluid_expected) <= FLUID_MASS_TOLERANCE_KG,
            "aggregate_massbody_kg": xml["floating_contract"]["massbody_kg"],
            "aggregate_massbody_exact": abs(xml["floating_contract"]["massbody_kg"] - 128.0) <= 1.0e-12,
            "aggregate_center_m": xml["floating_contract"]["center_m"],
            "aggregate_center_exact": xml["floating_contract"]["center_m"] == [2.4, 1.2, 1.08],
            "aggregate_inertia_m": xml_inertia,
            "aggregate_inertia_abs_error_m": inertia_errors,
            "aggregate_inertia_positive": all(value > 0.0 for value in xml_inertia),
            "aggregate_inertia_within_serialization_tolerance": all(value <= SERIALIZED_INERTIA_TOLERANCE for value in inertia_errors),
            "type2_particle_mass_is_not_aggregate_mass": xml["floating_contract"]["massbody_kg"] != xml["floating_contract"]["masspart_kg"] * xml["type_counts"]["floating"],
        },
        "phase_aligned_native_geometry": {
            "fixed_bounds_vs_physical_planes": phase_offsets,
            "moving_bounds_initial_and_swept": moving_sweep,
            "phase_offset_is_discretization_record_only": True,
            "finite_wall_exact_physical_endpoint_pass": False,
            "reason": "pointref=dp/2 yields native boundary layers offset from continuous tank planes; source geometry remains frozen and the offset must be assessed with solver/domain evidence.",
        },
        "wave_control_and_motion": wave_controls,
        "simulationdomain_coverage": {
            "xml_source": xml["simulationdomain_source"],
            "actual_solver_maprealpos_available": False,
            "status": "pending_solver_MapRealPos_or_root_domain_repair",
            "required_evidence": ["actual MapRealPos(border/final)", "fixed and floating extents plus body trajectory", "wave moving sweep over complete 0-12 s", "kernel/domain padding check"],
            "prior_dp025_wave_domain_repair_reference": {"x_min_m": -0.2, "x_max_m": 5.0},
            "prior_dp025_runout": ref(DP025_WAVE_RUNOUT),
        },
        "checks": {
            "actual_3d": xml["solver_dimension"] == 3,
            "positive_fluid_type3": actual_types["fluid"] > 0,
            "positive_floating_type2": actual_types["floating"] > 0,
            "moving_control_covered": (case["mechanism_id"] == "simple_free_response" and actual_types["moving"] == 0) or (case["mechanism_id"] == "wave_no_contact" and actual_types["moving"] > 0),
            "authoritative_fluid_mass_pass": abs(csv_audit["fluid_mass_kg_from_xml_massfluid"] - fluid_expected) <= FLUID_MASS_TOLERANCE_KG,
            "authoritative_rigid_contract_pass": abs(xml["floating_contract"]["massbody_kg"] - 128.0) <= 1.0e-12 and xml["floating_contract"]["center_m"] == [2.4, 1.2, 1.08] and all(value <= SERIALIZED_INERTIA_TOLERANCE for value in inertia_errors),
            "continuous_physical_equivalence_pass": source_contract == reference_contract and case["control"]["sha256"] == canonical_case["control"]["sha256"],
            "simulationdomain_coverage_pass": False,
        },
    }


def audit() -> dict[str, Any]:
    current_manifest = read_json(CURRENT_MANIFEST)
    current_geometry = read_json(CURRENT_GEOMETRY)
    current_audit = read_json(CURRENT_AUDIT)
    dp025_manifest = read_json(DP025_MANIFEST)
    dp025_geometry = read_json(DP025_GEOMETRY)
    motion = parse_motion(DP025_WAVE_MOTION)
    audit_by_case = {row["case_id"]: row for row in current_audit["cases"]}
    cases: list[dict[str, Any]] = []
    for case in current_manifest["cases"]:
        canonical = _case_by(dp025_manifest, case["mechanism_id"], "dp025")
        cases.append(audit_case(case, audit_by_case[case["case_id"]], canonical, current_geometry, dp025_geometry, motion if case["mechanism_id"] == "wave_no_contact" else None))
    references = {"current_manifest": ref(CURRENT_MANIFEST), "current_geometry": ref(CURRENT_GEOMETRY), "current_rigid_audit": ref(CURRENT_AUDIT), "dp025_manifest": ref(DP025_MANIFEST), "dp025_geometry": ref(DP025_GEOMETRY), "dp025_simple_runout": ref(DP025_SIMPLE_RUNOUT), "dp025_wave_runout": ref(DP025_WAVE_RUNOUT), "dp025_wave_motion": ref(DP025_WAVE_MOTION)}
    return {
        "schema": "ds-data-02.f6.rigid_contract_003.equivalence_domain_audit.v1",
        "family_id": "F6",
        "status": "continuous_contract_pass_domain_pending",
        "created_by": str(SCRIPT.resolve()),
        "gpu_launch": False,
        "conversion_launch": False,
        "qualification_claim": "none",
        "q_i_status": "native initial mass/rigid contract and continuous mother equivalence audited; phase endpoint offset retained",
        "q_n_status": "pending solver domain MapRealPos and full trajectory evidence",
        "source_references": references,
        "wave_motion_evidence": motion,
        "domain_policy": {
            "kernel_padding_multiplier": KERNEL_PADDING_MULTIPLIER,
            "continuous_physical_domain_is_unchanged": True,
            "phase_aligned_pointref_is_not_a_physical_domain_change": True,
            "default_simulationdomain_is_not_accepted_as_swept_coverage": True,
            "root_only_domain_repair_allowed": True,
        },
        "cases": cases,
    }


def main() -> int:
    result = audit()
    write_json(OUTPUT, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

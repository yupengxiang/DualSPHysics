#!/usr/bin/env python3
"""Audit the completed dp=.025 RIGID003 GenCase outputs without rerunning them."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V27 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v27.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_dp025_rigid003_v27_for_audit", V27)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load dp025 RIGID003 manifest module: {V27}")
V27_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V27_MODULE)

V12 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v12.py")
SPEC12 = importlib.util.spec_from_file_location("f6_handoff_v12_for_dp025_audit", V12)
if SPEC12 is None or SPEC12.loader is None:
    raise RuntimeError(f"cannot load Bound.vtk decoder: {V12}")
V12_MODULE = importlib.util.module_from_spec(SPEC12)
SPEC12.loader.exec_module(V12_MODULE)

FAMILY_ROOT = V27_MODULE.FAMILY_ROOT
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
RAW_ROOT = DATA_ROOT / "families/F6"
OUTPUT = FAMILY_ROOT / "preflight_001.json"
EXPECTED_FLUID_COUNT = 327680
EXPECTED_FLUID_MASS = 5120.0
EXPECTED_MASSBODY = 128.0
EXPECTED_CENTER = [2.4, 1.2, 1.08]
EXPECTED_INERTIA = [8.533333333333335, 8.533333333333335, 13.653333333333336]
SERIALIZED_INERTIA_TOLERANCE = 5.0e-5
EXPECTED_DP = 0.025
RHO_WATER = 1000.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _float_attrs(node: ET.Element | None, names: tuple[str, ...]) -> list[float] | None:
    if node is None:
        return None
    return [float(node.attrib[name]) for name in names]


def _generated_xml(xml: Path) -> dict[str, Any]:
    root = ET.parse(xml).getroot()
    particles = root.find("./execution/particles")
    constants = root.find("./execution/constants")
    summary = particles.find("_summary") if particles is not None else None
    floating = particles.find("floating") if particles is not None else None
    simdomain = root.find("./execution/parameters/simulationdomain")
    if particles is None or constants is None or summary is None or floating is None:
        raise ValueError(f"generated XML contract incomplete: {xml}")

    def count(tag: str) -> int:
        node = summary.find(tag)
        return int(node.attrib.get("count", "0")) if node is not None else 0

    massfluid = float(constants.find("massfluid").attrib["value"])
    massbound = float(constants.find("massbound").attrib["value"])
    massbody = float(floating.find("massbody").attrib["value"])
    masspart = float(floating.find("masspart").attrib["value"])
    center = _float_attrs(floating.find("center"), ("x", "y", "z"))
    inertia = _float_attrs(floating.find("inertia"), ("x", "y", "z"))
    data2d = constants.find("data2d")
    positions = summary.find("positions")
    return {
        "path": str(xml.resolve()),
        "sha256": sha256(xml),
        "particle_np": int(particles.attrib["np"]),
        "particle_nb": int(particles.attrib["nb"]),
        "particle_nbf": int(particles.attrib["nbf"]),
        "solver_dimension": 2 if data2d is not None and data2d.attrib.get("value", "true").lower() == "true" else 3,
        "type_counts": {tag: count(tag) for tag in ("fixed", "moving", "floating", "fluid")},
        "fluid_mass_per_particle_kg": massfluid,
        "bound_mass_per_particle_kg": massbound,
        "fluid_mass_kg": count("fluid") * massfluid,
        "floating_contract": {
            "massbody_kg": massbody,
            "masspart_kg": masspart,
            "type2_particle_mass_sum_kg": count("floating") * masspart,
            "center_m": center,
            "inertia_diag_kg_m2": inertia,
        },
        "positions_bounds_m": {
            "posmin": _float_attrs(positions.find("posmin"), ("x", "y", "z")),
            "posmax": _float_attrs(positions.find("posmax"), ("x", "y", "z")),
        },
        "simulationdomain_source": {
            "posmin": dict(simdomain.find("posmin").attrib) if simdomain is not None else None,
            "posmax": dict(simdomain.find("posmax").attrib) if simdomain is not None else None,
        },
    }


def _case_row(case: dict[str, Any]) -> dict[str, Any]:
    cid = str(case["case_id"])
    attempt = str(case["request"]["attempt_id"])
    output_root = RAW_ROOT / cid / attempt
    prefix = output_root / cid
    receipt_path = output_root / "execution-receipt.json"
    xml = prefix.with_suffix(".xml")
    bound_vtk = prefix.with_name(prefix.name + "_Bound.vtk")
    required = (receipt_path, xml, bound_vtk, prefix.with_suffix(".bi4"), prefix.with_name(prefix.name + "_All.vtk"), prefix.with_name(prefix.name + "_Fluid.vtk"))
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("dp025 RIGID003 output missing: " + ", ".join(missing))
    receipt = read_json(receipt_path)
    generated = _generated_xml(xml)
    boundary = V12_MODULE._decode_bound_vtk(bound_vtk, dp=EXPECTED_DP)
    fluid_count = generated["type_counts"]["fluid"]
    floating = generated["type_counts"]["floating"]
    moving = generated["type_counts"]["moving"]
    contract = generated["floating_contract"]
    body = case["body"]
    fluid_spec = case["fluid"]
    fluid_top = float(fluid_spec["low"][2]) + float(fluid_spec["size"][2])
    body_bottom = float(body["point"][2])
    body_top = body_bottom + float(body["size"][2])
    overlap_z = max(0.0, min(fluid_top, body_top) - max(float(fluid_spec["low"][2]), body_bottom))
    overlap_x = max(0.0, min(float(fluid_spec["low"][0]) + float(fluid_spec["size"][0]), float(body["point"][0]) + float(body["size"][0])) - max(float(fluid_spec["low"][0]), float(body["point"][0])))
    overlap_y = max(0.0, min(float(fluid_spec["low"][1]) + float(fluid_spec["size"][1]), float(body["point"][1]) + float(body["size"][1])) - max(float(fluid_spec["low"][1]), float(body["point"][1])))
    overlap_volume = overlap_x * overlap_y * overlap_z
    density_ratio = EXPECTED_MASSBODY / (math.prod(float(v) for v in body["size"]) * RHO_WATER)
    checks = {
        "gencase_completed_code0": receipt.get("status") == "completed" and receipt.get("returncode") == 0,
        "actual_3d": receipt.get("solver_dimension_from_gencase") == 3 and generated["solver_dimension"] == 3,
        "positive_type3_fluid": fluid_count == EXPECTED_FLUID_COUNT and receipt.get("fluid_particles") == EXPECTED_FLUID_COUNT,
        "strict_fluid_mass_exact": abs(generated["fluid_mass_kg"] - EXPECTED_FLUID_MASS) <= 1.0e-9,
        "positive_type2_floating": floating > 0 and boundary["type_counts"].get("floating", 0) == floating,
        "wave_actual_moving_particles": moving > 0 if case["mechanism_id"] == "wave_no_contact" else moving == 0,
        "finite_wall_faces_nonzero": boundary["fixed_face_coverage"]["all_declared_faces_nonzero"],
        "finite_wall_endpoints_cover_frozen_tank": boundary["fixed_points_bounds_m"][0][1] >= 4.8 - 1.0e-5 and boundary["fixed_points_bounds_m"][1][1] >= 2.4 - 1.0e-5,
        "aggregate_massbody_exact": abs(contract["massbody_kg"] - EXPECTED_MASSBODY) <= 1.0e-12,
        "aggregate_center_exact": all(abs(a - b) <= 1.0e-12 for a, b in zip(contract["center_m"], EXPECTED_CENTER)),
        "aggregate_inertia_positive_and_serialized_matches": all(value > 0 for value in contract["inertia_diag_kg_m2"]) and all(abs(a - b) <= SERIALIZED_INERTIA_TOLERANCE for a, b in zip(contract["inertia_diag_kg_m2"], EXPECTED_INERTIA)),
        "initial_submerged_body_volume_zero": overlap_volume <= 1.0e-12,
        "density_ratio_half": abs(density_ratio - 0.5) <= 1.0e-12,
        "source_hashes_at_launch_and_after_run": bool(receipt.get("input_hashes_at_launch")) and receipt.get("input_hashes_at_launch") == receipt.get("input_hashes_after_run"),
    }
    return {
        "case_id": cid,
        "mechanism_id": case["mechanism_id"],
        "resolution_id": case["resolution_id"],
        "dp_m": EXPECTED_DP,
        "gencase_receipt": {"path": str(receipt_path.resolve()), "sha256": sha256(receipt_path), "status": receipt.get("status"), "returncode": receipt.get("returncode"), "total_particles": receipt.get("total_particles"), "fluid_particles": receipt.get("fluid_particles"), "solver_dimension_from_gencase": receipt.get("solver_dimension_from_gencase"), "input_hashes_at_launch": receipt.get("input_hashes_at_launch"), "input_hashes_after_run": receipt.get("input_hashes_after_run")},
        "generated_native_contract": generated,
        "native_boundary_vtk": boundary,
        "initial_geometry": {"fluid_low_m": fluid_spec["low"], "fluid_size_m": fluid_spec["size"], "fluid_top_m": fluid_top, "body_point_m": body["point"], "body_size_m": body["size"], "body_bottom_m": body_bottom, "body_top_m": body_top, "body_fluid_overlap_volume_m3": overlap_volume, "density_ratio_to_water": density_ratio},
        "checks": checks,
        "preflight_pass": all(checks.values()),
        "qualification_claim": "none; actual GenCase/XML/Bound.vtk preflight only",
    }


def audit() -> dict[str, Any]:
    manifest = read_json(FAMILY_ROOT / "manifest.json")
    rows = [_case_row(case) for case in manifest["cases"]]
    result = {
        "schema": "ds-data-02.f6.commensurate_dp025_rigid003.preflight.v1",
        "family_id": "F6",
        "scope_id": "F6_HANDOFF_20261002_COMMENSURATE_DP025_RIGID003",
        "status": "all_two_actual_gencase_preflight_pass" if all(row["preflight_pass"] for row in rows) else "actual_gencase_preflight_failed",
        "source_manifest": {"path": str((FAMILY_ROOT / "manifest.json").resolve()), "sha256": sha256(FAMILY_ROOT / "manifest.json")},
        "source_script": {"path": str(SCRIPT.resolve()), "sha256": sha256(SCRIPT)},
        "frozen_contract": {"fluid_volume_m3": 5.12, "fluid_mass_kg": EXPECTED_FLUID_MASS, "aggregate_massbody_kg": EXPECTED_MASSBODY, "center_m": EXPECTED_CENTER, "inertia_diag_kg_m2": EXPECTED_INERTIA, "floatingtype": 2, "solver_dimension": 3, "finite_walls": ["bottom", "left", "right", "front", "back"]},
        "old_dp025_without_explicit_rigid_contract_preserved": True,
        "cases": rows,
        "gpu_launch": False,
        "qualification_claim": "none",
        "q_i_status": "actual GenCase native XML and Bound.vtk preflight complete; solver remains pending root",
        "q_n_status": "pending root review and any solver dispatch",
    }
    write_json(OUTPUT, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audit"])
    args = parser.parse_args()
    result = audit() if args.action == "audit" else None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

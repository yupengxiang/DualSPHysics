"""F1 ECC thick-boundary candidate 002.

Candidate 001 remains immutable as a static negative review.  Candidate 002
keeps the tank support slabs outside the tank faces, while the obstacle's
four vertical faces and top receive three solid support rows *inside* the
declared obstacle volume.  This is a numeric boundary representation choice;
the continuous obstacle [0.9, .24, 0]--[1.02, .36, .45], fluid reservoir,
controls, and mass denominator are unchanged.

The official GenCase/PartVTK and double-BI4 audit implementation is reused
from the additive v1 module.  Its outer-face checks are retained and the
obstacle coverage check is replaced with an explicit inside-solid-side check.
No solver or GPU is invoked by this module.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

import ds_data02_f1_eccentric_thick_boundary as base


VARIANT_ID = "002-obstacle-internal-solid-support"
SCHEMA = "ds02.f1.eccentric-thick-boundary.v2"
_SCOPE = base._LAB / "campaigns/ds-data-02/families/F1/handoff_20261003/eccentric_thick_boundary_fallback_002"
DEFAULT_TEMPLATE = base.DEFAULT_TEMPLATE


def _internal_obstacle_slabs(dp: float) -> dict[str, dict[str, list[float]]]:
    """Three rows wholly inside the obstacle on each audited face."""

    lo = np.asarray(base.OBSTACLE_LOW, dtype=float)
    hi = lo + np.asarray(base.OBSTACLE_SIZE, dtype=float)
    half = 0.5 * dp
    thickness = 2.0 * dp
    # Tangential extents are also inside the continuous body.  The endpoint
    # rows remain one half-dp from the corresponding physical tangential face.
    tangential_low = lo + half
    tangential_high = hi - half
    return {
        "x_low": {"point": [lo[0] + half, tangential_low[1], tangential_low[2]], "size": [thickness, tangential_high[1] - tangential_low[1], tangential_high[2] - tangential_low[2]]},
        "x_high": {"point": [hi[0] - 2.5 * dp, tangential_low[1], tangential_low[2]], "size": [thickness, tangential_high[1] - tangential_low[1], tangential_high[2] - tangential_low[2]]},
        "y_low": {"point": [tangential_low[0], lo[1] + half, tangential_low[2]], "size": [tangential_high[0] - tangential_low[0], thickness, tangential_high[2] - tangential_low[2]]},
        "y_high": {"point": [tangential_low[0], hi[1] - 2.5 * dp, tangential_low[2]], "size": [tangential_high[0] - tangential_low[0], thickness, tangential_high[2] - tangential_low[2]]},
        "z_high": {"point": [tangential_low[0], tangential_low[1], hi[2] - 2.5 * dp], "size": [tangential_high[0] - tangential_low[0], tangential_high[1] - tangential_low[1], thickness]},
    }


def _replace_geometry_v2(root: ET.Element, dp: float) -> None:
    definition = root.find("./casedef/geometry/definition")
    commands = root.find("./casedef/geometry/commands")
    if definition is None or commands is None:
        raise ValueError("candidate geometry nodes missing")
    definition.set("dp", base._q(dp))
    definition.set("units_comment", "metres (m)")
    pointref = definition.find("pointref")
    if pointref is None:
        pointref = ET.Element("pointref")
        definition.insert(0, pointref)
    pointref.attrib.update({"x": base._q(dp / 2), "y": base._q(dp / 2), "z": base._q(dp / 2)})
    pointmin = definition.find("pointmin")
    pointmax = definition.find("pointmax")
    if pointmin is None or pointmax is None:
        raise ValueError("ECC source point bounds missing")
    pointmin.attrib.update({"x": base._q(-2.5 * dp), "y": base._q(-2.5 * dp), "z": base._q(-2.5 * dp)})
    pointmax.attrib.update({"x": "2", "y": "1", "z": "1"})
    mainlist = commands.find("mainlist")
    if mainlist is None:
        raise ValueError("ECC source mainlist missing")
    for child in list(mainlist):
        mainlist.remove(child)
    base._element(mainlist, "setshapemode", text="dp | actual | bound")
    base._element(mainlist, "setdrawmode", {"mode": "full"})
    base._element(mainlist, "setmkbound", {"mk": "0"})
    for name, slab in base._slab_geometry(dp).items():
        base._drawbox(mainlist, f"thick outer support {name}; external solid layers only", "solid", slab["point"], slab["size"])
    base._element(mainlist, "setmkvoid")
    base._drawbox(mainlist, "frozen ECC obstacle physical solid; continuous geometry unchanged", "solid", base.OBSTACLE_LOW, base.OBSTACLE_SIZE)
    base._element(mainlist, "setmkbound", {"mk": "1"})
    for name, slab in _internal_obstacle_slabs(dp).items():
        base._drawbox(mainlist, f"thick obstacle support {name}; internal solid layers only", "solid", slab["point"], slab["size"])
    base._element(mainlist, "setmkfluid", {"mk": "0"})
    base._drawbox(mainlist, "exact ECC fluid cell centres; one native particle per dp^3 cell", "solid", [dp / 2] * 3, [base.FLUID_SIZE[i] - dp for i in range(3)])


def materialize_case(template: Path, output_root: Path) -> dict[str, Any]:
    source = base.inspect_source(template.resolve())
    root = ET.parse(template).getroot()
    _replace_geometry_v2(root, base.DP_M)
    base._set_parameter(root, "SavePosDouble", "1")
    base._set_parameter(root, "Boundary", "1")
    output_root = output_root.resolve()
    case_dir = output_root / "definitions" / "F1_ECC_THICK_BOUNDARY_DBC_DP010"
    case_dir.mkdir(parents=True, exist_ok=True)
    definition = case_dir / "F1_ECC_THICK_BOUNDARY_DBC_DP010_Def.xml"
    ET.ElementTree(root).write(definition, encoding="utf-8", xml_declaration=True)
    expected = base.EXPECTED_MASS
    metadata = {
        "schema": SCHEMA,
        "family_id": base.FAMILY_ID,
        "mechanism_id": base.MECHANISM_ID,
        "case_id": "F1_ECC_THICK_BOUNDARY_DBC_DP010",
        "variant_id": VARIANT_ID,
        "physical_case_id": "F1_ECCENTRIC_THICK_BOUNDARY_DBC",
        "status": "static_recipe_pending_root_review_and_bounded_cpu_gencase",
        "qualification_claim": "none",
        "q_n_status": "not_assessed",
        "production_claim": "none",
        "claim_boundary": "Static candidate 002 only; no solver/GPU/Q-N claim.",
        "source_binding": source,
        "physical_binding": {
            "physical_hash": source["physical_hash"],
            "payload": source["physical_payload"],
            "continuous_fluid_mass_kg": expected,
            "mass_normalization": "forbidden",
            "boundary_method": "DBC",
            "normals": False,
        },
        "numeric_binding": {
            "dp_m": base.DP_M,
            "pointref_m": [base.DP_M / 2] * 3,
            "pointmin_m": [-2.5 * base.DP_M] * 3,
            "outer_support_side": "outside tank continuous faces",
            "outer_support_layers": 3,
            "outer_support_slabs": base._slab_geometry(base.DP_M),
            "obstacle_support_side": "inside obstacle continuous solid",
            "obstacle_support_layers": 3,
            "obstacle_support_slabs": _internal_obstacle_slabs(base.DP_M),
            "obstacle_continuous_low_m": list(base.OBSTACLE_LOW),
            "obstacle_continuous_high_m": [base.OBSTACLE_LOW[i] + base.OBSTACLE_SIZE[i] for i in range(3)],
            "obstacle_support_semantics": "all obstacle support coordinates lie within [0.9,1.02]x[.24,.36]x[0,.45]; nearest audited row is half-dp inward",
            "fluid_primitive": "boxfill=solid; point=low+0.5dp; size=extent-dp",
            "uses_vdp": False,
            "save_pos_double": True,
            "boundary_parameter": 1,
        },
        "expected_initial": {
            "counts_xyz": list(base.EXPECTED_COUNTS),
            "fluid_particles": base.EXPECTED_FLUID,
            "fluid_mass_kg": expected,
            "fluid_center_low_m": [base.DP_M / 2] * 3,
            "fluid_center_high_m": [base.FLUID_SIZE[i] - base.DP_M / 2 for i in range(3)],
        },
        "hard_gates": [
            "official child receipt has returncode=0, total/fluid counts and Data2D=0",
            "double BI4 has Posd.bin and unique contiguous Idp.bin",
            "fixed/fluid XML ranges partition Idp exactly",
            "fluid count/mass remain 80400/80.4 kg without rescale",
            "outer typed fixed positions cover all five faces from the external side",
            "obstacle typed fixed positions cover all five faces from the internal solid side",
            "every obstacle support point lies inside the declared obstacle body",
        ],
        "preserved_001_review": {
            "manifest": "/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/eccentric_thick_boundary_fallback_001/eccentric-thick-boundary-manifest.json",
            "review": "/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/eccentric_thick_boundary_fallback_001/thick-boundary-static-review.json",
            "negative_review": "Obstacle supports in 001 were external and would occupy a fluid-accessible region; 001 remains immutable evidence and is not reused as an approved recipe.",
        },
        "definition_path": str(definition.resolve()),
        "definition_sha256": base.sha256(definition),
    }
    metadata_path = case_dir / "F1_ECC_THICK_BOUNDARY_DBC_DP010.metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=base._json_default) + "\n", encoding="utf-8")
    return {
        "case_id": metadata["case_id"],
        "variant_id": VARIANT_ID,
        "definition": str(definition.resolve()),
        "metadata": str(metadata_path.resolve()),
        "definition_sha256": base.sha256(definition),
        "metadata_sha256": base.sha256(metadata_path),
        "physical_hash": source["physical_hash"],
        "expected_fluid_particles": base.EXPECTED_FLUID,
        "expected_fluid_mass_kg": expected,
    }


def _internal_face_report(fixed: np.ndarray, dp: float = base.DP_M) -> dict[str, Any]:
    """Audit obstacle faces with the expected support side inside the body."""

    lo = np.asarray(base.OBSTACLE_LOW, dtype=float)
    hi = lo + np.asarray(base.OBSTACLE_SIZE, dtype=float)
    specs = [
        ("x_low", 0, lo[0], (lo[1], lo[2]), (hi[1], hi[2])),
        ("x_high", 0, hi[0], (lo[1], lo[2]), (hi[1], hi[2])),
        ("y_low", 1, lo[1], (lo[0], lo[2]), (hi[0], hi[2])),
        ("y_high", 1, hi[1], (lo[0], lo[2]), (hi[0], hi[2])),
        ("z_high", 2, hi[2], (lo[0], lo[1]), (hi[0], hi[1])),
    ]
    result: dict[str, Any] = {}
    for name, axis, plane, tangent_low, tangent_high in specs:
        tangents = [idx for idx in range(3) if idx != axis]
        values = [base._axis_samples(tangent_low[i], tangent_high[i], dp) for i in range(2)]
        aa, bb = np.meshgrid(values[0], values[1], indexing="ij")
        query = np.zeros((aa.size, 3), dtype=float)
        query[:, axis] = plane
        query[:, tangents[0]] = aa.ravel()
        query[:, tangents[1]] = bb.ravel()
        near_all = fixed[np.abs(fixed[:, axis] - plane) <= dp / 2 + 2e-6]
        interior = np.ones(len(near_all), dtype=bool)
        for tangent, low, high in zip(tangents, tangent_low, tangent_high):
            interior &= near_all[:, tangent] >= low + 0.75 * dp - 2e-6
            interior &= near_all[:, tangent] <= high - 0.75 * dp + 2e-6
        near_interior = near_all[interior]
        inward = near_interior[:, axis] > plane + 1e-7 if name.endswith("_low") else near_interior[:, axis] < plane - 1e-7
        fraction = float(np.mean(inward)) if len(inward) else 0.0
        distances = base.cKDTree(near_all).query(query, workers=1)[0] if len(near_all) else np.full(len(query), np.inf)
        radius = math.sqrt(3.0) * dp / 2 + 2e-6
        result[name] = {
            "plane_m": float(plane),
            "near_plane_fixed_points": int(len(near_all)),
            "interior_orientation_points": int(len(near_interior)),
            "inward_orientation_fraction": fraction,
            "surface_samples": int(len(query)),
            "maximum_distance_m": float(distances.max()) if len(distances) else None,
            "uncovered_samples": int(np.count_nonzero(distances > radius)),
            "expected_support_side": "inside_obstacle",
            "covered": bool(len(query) and np.all(distances <= radius) and fraction >= 0.90),
        }
    result["all_obstacle_five_covered"] = all(row["covered"] for row in result.values())
    return result


def _obstacle_points_inside(points: np.ndarray, tolerance: float = 2e-7) -> bool:
    lo = np.asarray(base.OBSTACLE_LOW, dtype=float) - tolerance
    hi = np.asarray(base.OBSTACLE_LOW, dtype=float) + np.asarray(base.OBSTACLE_SIZE, dtype=float) + tolerance
    return bool(len(points) and np.all(points >= lo) and np.all(points <= hi))


def audit_native(case: dict[str, Any], case_root: Path, bi4_dump: Path) -> dict[str, Any]:
    report = base.audit_native(case, case_root, bi4_dump)
    # Keep the v1 external-obstacle interpretation as explicit negative
    # evidence.  v2 changes the expected side only after preserving the
    # original result; it must never look as though an external-face failure
    # was silently rewritten into a pass.
    v1_coverage = report["coverage_from_actual_double_bi4_fixed_positions"]["obstacle"]
    v1_check = report["checks"]["obstacle_five_face_coverage_from_typed_fixed"]
    report["v1_external_obstacle_check"] = {
        "coverage": v1_coverage,
        "check": v1_check,
        "status": "retained_negative_evidence",
        "meaning": "v1 expected obstacle supports outside the continuous body; that side is intentionally rejected by v2.",
    }
    typed = report["typed_identity"]
    # Recover typed fixed positions from the already validated BI4 exactly as
    # v1 does, without changing its source files or its output artifacts.
    prefix = case_root / "F1_ECC_THICK_BOUNDARY_DBC_DP010"
    xml_path = prefix.with_suffix(".xml")
    bi4_path = prefix.with_suffix(".bi4")
    ids, positions, _ = base._decode_double_bi4(bi4_path, bi4_dump)
    ranges = base._parse_particle_ranges(xml_path)
    fixed, _, _ = base._typed_positions(ids, positions, ranges)
    obstacle = _internal_face_report(fixed)
    obstacle_rows = [row for key, row in obstacle.items() if key != "all_obstacle_five_covered"]
    obstacle_support_points = fixed[
        np.all(fixed >= np.asarray(base.OBSTACLE_LOW) - 2e-7, axis=1)
        & np.all(fixed <= np.asarray(base.OBSTACLE_LOW) + np.asarray(base.OBSTACLE_SIZE) + 2e-7, axis=1)
    ]
    report["schema"] = "ds02.f1.eccentric-thick-boundary.native-audit.v2"
    report["variant_id"] = VARIANT_ID
    report["coverage_from_actual_double_bi4_fixed_positions"]["obstacle"] = obstacle
    report["coverage_from_actual_double_bi4_fixed_positions"]["all_obstacle_five_covered"] = obstacle["all_obstacle_five_covered"]
    report["checks"]["obstacle_five_face_coverage_from_typed_fixed"] = obstacle["all_obstacle_five_covered"]
    report["checks"]["obstacle_support_points_inside_continuous_solid"] = _obstacle_points_inside(obstacle_support_points)
    report["actual"]["obstacle_support_fixed_points"] = int(len(obstacle_support_points))
    report["status"] = "pass_initial_native_contract" if all(report["checks"].values()) else "failed_initial_native_contract"
    child = Path(report["child_gencase_receipt"])
    if child.exists():
        receipt = json.loads(child.read_text(encoding="utf-8"))
        receipt["variant_id"] = VARIANT_ID
        receipt["obstacle_support_side"] = "inside_obstacle"
        child.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # The child receipt is amended with the v2 semantic binding before
        # the parent report is returned.  Bind the hash of those final bytes,
        # never the pre-amendment v1 receipt.
        child_sha = base.sha256(child)
        report["child_gencase_receipt_sha256"] = child_sha
        report["source_hashes"]["child_gencase_receipt"] = child_sha
    return report


def design(output_root: Path = _SCOPE, template: Path = DEFAULT_TEMPLATE) -> dict[str, Any]:
    output_root = output_root.resolve()
    case = materialize_case(template.resolve(), output_root)
    manifest = {
        "schema": "ds02.f1.eccentric-thick-boundary-manifest.v2",
        "family_id": base.FAMILY_ID,
        "mechanism_id": base.MECHANISM_ID,
        "physical_case_id": "F1_ECCENTRIC_THICK_BOUNDARY_DBC",
        "variant_id": VARIANT_ID,
        "claim_boundary": "static candidate only; root review required before bounded CPU GenCase",
        "case": case,
        "recipe": {
            "resolution": "dp010",
            "counts_xyz": list(base.EXPECTED_COUNTS),
            "fluid_particles": base.EXPECTED_FLUID,
            "fluid_mass_kg": base.EXPECTED_MASS,
            "outer_support_side": "outside_tank",
            "obstacle_support_side": "inside_obstacle",
            "support_layers": 3,
            "obstacle_support_slabs": _internal_obstacle_slabs(base.DP_M),
            "obstacle_support_coordinates_must_be_inside": {
                "low": list(base.OBSTACLE_LOW),
                "high": [base.OBSTACLE_LOW[i] + base.OBSTACLE_SIZE[i] for i in range(3)],
            },
            "uses_vdp": False,
        },
        "preserved_candidate_001": "/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/eccentric_thick_boundary_fallback_001",
        "no_execution_performed": True,
        "q_n_status": "not_assessed",
    }
    path = output_root / "eccentric-thick-boundary-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=base._json_default) + "\n", encoding="utf-8")
    manifest["manifest_path"] = str(path.resolve())
    manifest["manifest_sha256"] = base.sha256(path)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=base._json_default) + "\n", encoding="utf-8")
    return manifest


def run_gencase(manifest_path: Path, attempt_root: Path, output_path: Path, gencase: Path, partvtk: Path, bi4_dump: Path) -> dict[str, Any]:
    # v1 runs the official child tools and writes the immutable child receipt;
    # v2 then re-audits the same outputs with obstacle-inside semantics.
    base.run_gencase(manifest_path, attempt_root, output_path, gencase, partvtk, bi4_dump)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case = manifest["case"]
    case_root = attempt_root / case["case_id"]
    report = audit_native(case, case_root, bi4_dump)
    report.update({
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": base.sha256(manifest_path),
        "attempt_root": str(attempt_root.resolve()),
        "official_gencase": str(gencase.resolve()),
        "official_partvtk": str(partvtk.resolve()),
        "variant_id": VARIANT_ID,
        "parent_v1_external_obstacle_check_retained_as_negative": True,
        "claim_boundary": "Initial GenCase/PartVTK/BI4 only; no solver/GPU/Q-N/production claim.",
    })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=base._json_default) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_design = sub.add_parser("design")
    p_design.add_argument("--output-root", type=Path, default=_SCOPE)
    p_design.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    p_run = sub.add_parser("run-gencase")
    p_run.add_argument("--manifest", type=Path, required=True)
    p_run.add_argument("--attempt-root", type=Path, required=True)
    p_run.add_argument("--output", type=Path, required=True)
    p_run.add_argument("--gencase", type=Path, required=True)
    p_run.add_argument("--partvtk", type=Path, required=True)
    p_run.add_argument("--bi4-dump", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "design":
        result = design(args.output_root, args.template)
    else:
        result = run_gencase(args.manifest, args.attempt_root, args.output, args.gencase, args.partvtk, args.bi4_dump)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=base._json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

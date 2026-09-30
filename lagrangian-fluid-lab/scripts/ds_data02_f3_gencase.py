#!/usr/bin/env python3
"""Prepare and audit F3 weak dual-axis GenCase resolution references.

This F3-scoped utility derives three *new* Def files from the frozen weak-axis
source.  It changes only the particle spacing and the lattice insets around
the same continuous tank and initial fluid volume.  It never edits the source
Def/control bytes and never launches GenCase; the shared CPU runner owns that
launch.  The audit consumes a completed runner output and reports actual
particle counts, native mass, geometry, normal generation, and initialization
evidence without granting Q-N or production status.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from typing import Any, Mapping, Sequence

try:  # package import for tests; direct-file import for the shared runner CLI
    from .ds_data02_direct_convert import sha256_file
except ImportError:  # pragma: no cover - exercised by ``python scripts/...``
    from ds_data02_direct_convert import sha256_file


SCHEMA = "ds02.f3.gencase-matrix.v1"


class F3GenCaseError(RuntimeError):
    """Raised when the F3 numeric reference contract is inconsistent."""


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _float_attr(node: ET.Element, name: str) -> float:
    value = node.get(name)
    if value is None:
        raise F3GenCaseError(f"missing numeric XML attribute {name!r} on <{node.tag}>")
    try:
        return float(value)
    except ValueError as exc:
        raise F3GenCaseError(f"invalid numeric XML attribute {name!r}={value!r}") from exc


def _vector(node: ET.Element, names: tuple[str, str, str] = ("x", "y", "z")) -> list[float]:
    return [_float_attr(node, name) for name in names]


def _set_vector(node: ET.Element, values: Sequence[float]) -> None:
    for name, value in zip(("x", "y", "z"), values):
        node.set(name, format(float(value), ".15g"))


def _add(left: Sequence[float], right: Sequence[float]) -> list[float]:
    return [float(a + b) for a, b in zip(left, right)]


def _sub(left: Sequence[float], right: Sequence[float]) -> list[float]:
    return [float(a - b) for a, b in zip(left, right)]


def _scale(value: Sequence[float], factor: float) -> list[float]:
    return [float(item * factor) for item in value]


def _close_vector(actual: Sequence[float], expected: Sequence[float], tol: float = 2e-12) -> bool:
    return all(abs(float(a) - float(b)) <= tol for a, b in zip(actual, expected))


@dataclass(frozen=True)
class ContinuousGeometry:
    tank_low_m: tuple[float, float, float]
    tank_size_m: tuple[float, float, float]
    fluid_low_m: tuple[float, float, float]
    fluid_size_m: tuple[float, float, float]

    def as_json(self) -> dict[str, Any]:
        return {
            "tank_low_m": list(self.tank_low_m),
            "tank_size_m": list(self.tank_size_m),
            "fluid_low_m": list(self.fluid_low_m),
            "fluid_size_m": list(self.fluid_size_m),
        }


def _locate_geometry(root: ET.Element) -> tuple[ET.Element, ET.Element, ET.Element, ET.Element, float, ContinuousGeometry]:
    definition = root.find(".//geometry/definition")
    pointref = root.find(".//geometry/definition/pointref")
    if definition is None or pointref is None:
        raise F3GenCaseError("source Def lacks geometry definition/pointref")
    try:
        source_dp = _float_attr(definition, "dp")
    except F3GenCaseError:
        raise
    if source_dp <= 0:
        raise F3GenCaseError("source dp must be positive")
    normal_list = root.find(".//geometry/commands/list[@name='GeometryForNormals']")
    main_list = root.find(".//geometry/commands/mainlist")
    if normal_list is None or main_list is None:
        raise F3GenCaseError("source Def lacks GeometryForNormals/mainlist")
    normal_boxes = normal_list.findall("./drawbox")
    main_boxes = main_list.findall("./drawbox")
    if len(normal_boxes) != 1 or len(main_boxes) < 2:
        raise F3GenCaseError("source Def must have one normal box and fluid/boundary main boxes")
    normal_box, fluid_box, boundary_box = normal_boxes[0], main_boxes[0], main_boxes[1]
    normal_point = normal_box.find("point")
    normal_size = normal_box.find("size")
    fluid_point = fluid_box.find("point")
    fluid_size = fluid_box.find("size")
    boundary_point = boundary_box.find("point")
    boundary_size = boundary_box.find("size")
    if any(item is None for item in (normal_point, normal_size, fluid_point, fluid_size, boundary_point, boundary_size)):
        raise F3GenCaseError("source Def drawbox is missing point/size")
    tank_low = _vector(normal_point)
    tank_size = _vector(normal_size)
    half_source = source_dp / 2.0
    fluid_low = _sub(_vector(fluid_point), [half_source] * 3)
    fluid_size_cont = _add(_vector(fluid_size), [source_dp] * 3)
    observed_boundary_low = _vector(boundary_point)
    observed_boundary_size = _vector(boundary_size)
    expected_boundary_low = _sub(tank_low, [half_source] * 3)
    expected_boundary_size = [tank_size[0] + source_dp, tank_size[1] + source_dp, tank_size[2] + half_source]
    if not _close_vector(observed_boundary_low, expected_boundary_low) or not _close_vector(observed_boundary_size, expected_boundary_size):
        raise F3GenCaseError(
            "source boundary lattice is not the expected all^top inset; refusing to infer a new resolution"
        )
    geometry = ContinuousGeometry(tuple(tank_low), tuple(tank_size), tuple(fluid_low), tuple(fluid_size_cont))
    return definition, pointref, fluid_box, boundary_box, source_dp, geometry


def generate_definition(source_def: Path, output_def: Path, dp: float, *, owner_metadata: Path | None = None) -> dict[str, Any]:
    """Create one resolution-only Def copy and a manifest-ready description."""
    if dp <= 0:
        raise F3GenCaseError("candidate dp must be positive")
    tree = ET.parse(source_def)
    root = tree.getroot()
    definition, pointref, fluid_box, boundary_box, source_dp, geometry = _locate_geometry(root)
    tank_low, tank_size = geometry.tank_low_m, geometry.tank_size_m
    fluid_low, fluid_size = geometry.fluid_low_m, geometry.fluid_size_m
    definition.set("dp", format(dp, ".15g"))
    _set_vector(pointref, [dp / 2.0] * 3)
    fluid_point = fluid_box.find("point")
    fluid_size_node = fluid_box.find("size")
    boundary_point = boundary_box.find("point")
    boundary_size_node = boundary_box.find("size")
    assert fluid_point is not None and fluid_size_node is not None
    assert boundary_point is not None and boundary_size_node is not None
    _set_vector(fluid_point, _add(fluid_low, [dp / 2.0] * 3))
    _set_vector(fluid_size_node, _sub(fluid_size, [dp] * 3))
    _set_vector(boundary_point, _sub(tank_low, [dp / 2.0] * 3))
    _set_vector(boundary_size_node, [tank_size[0] + dp, tank_size[1] + dp, tank_size[2] + dp / 2.0])
    # Preserve the original source's control path and every physical/control
    # parameter.  Only the numeric lattice values above are changed.
    try:
        ET.indent(tree, space="  ")
    except AttributeError:  # pragma: no cover - Python 3.10 has ET.indent
        pass
    output_def.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_def, encoding="utf-8", xml_declaration=True)
    owner_sha = None
    physical_case_id = None
    physical_binding_sha = None
    if owner_metadata is not None:
        owner = json.loads(owner_metadata.read_text())
        physical_case_id = owner.get("physical_case_id")
        binding = owner.get("physical_binding")
        if isinstance(binding, Mapping):
            physical_binding_sha = hashlib.sha256(
                json.dumps(binding, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")
            ).hexdigest()
        owner_sha = sha256_file(owner_metadata)
    control_node = root.find(".//execution/special/accinputs/accinput/acctimesfile")
    control_name = None if control_node is None else control_node.get("value")
    source_control = None if not control_name else source_def.parent / control_name
    candidate_control = None if not control_name else output_def.parent / control_name
    return {
        "schema": SCHEMA,
        "candidate_def": str(output_def),
        "candidate_def_sha256": sha256_file(output_def),
        "source_def": str(source_def),
        "source_def_sha256": sha256_file(source_def),
        "source_dp_m": source_dp,
        "candidate_dp_m": dp,
        "continuous_geometry": geometry.as_json(),
        "fluid_lattice": {
            "point_m": _add(fluid_low, [dp / 2.0] * 3),
            "size_m": _sub(fluid_size, [dp] * 3),
            "mass_policy": "GenCase native MassFluid multiplied by actual fluid count; no normalization",
        },
        "boundary_lattice": {
            "point_m": _sub(tank_low, [dp / 2.0] * 3),
            "size_m": [tank_size[0] + dp, tank_size[1] + dp, tank_size[2] + dp / 2.0],
            "boxfill": "all^top",
        },
        "owner_metadata_sha256": owner_sha,
        "control": {
            "relative_name": control_name,
            "source_path": None if source_control is None else str(source_control),
            "source_sha256": None if source_control is None or not source_control.is_file() else sha256_file(source_control),
            "candidate_copy_path": None if candidate_control is None else str(candidate_control),
            "candidate_copy_sha256": None if candidate_control is None or not candidate_control.is_file() else sha256_file(candidate_control),
            "candidate_copy_matches_source": bool(
                source_control is not None and candidate_control is not None
                and source_control.is_file() and candidate_control.is_file()
                and sha256_file(source_control) == sha256_file(candidate_control)
            ),
        },
        "physical_case_id": physical_case_id,
        "physical_binding_sha256": physical_binding_sha,
        "scope": "F3 weak dual-axis numeric resolution reference; no solver or Q-N claim",
    }


def _parse_int(text: str, label: str) -> int:
    try:
        return int(text.replace(",", ""))
    except ValueError as exc:
        raise F3GenCaseError(f"cannot parse {label}: {text!r}") from exc


def _ref(path: Path) -> dict[str, Any]:
    return {"path": str(path), "exists": path.is_file(), "sha256": sha256_file(path) if path.is_file() else None}


def audit_gencase_output(*, generated_xml: Path, output_root: Path, receipt: Path, candidate_manifest: Path, expected_mass_kg: float = 14.58) -> dict[str, Any]:
    """Audit actual generated XML/BI4/VTK/normal evidence from a runner attempt."""
    execution = json.loads(receipt.read_text())
    if execution.get("status") not in {"completed", "success"} or execution.get("returncode") not in {0, None}:
        raise F3GenCaseError(f"GenCase receipt is not successful: {receipt}")
    manifest = json.loads(candidate_manifest.read_text())
    root = ET.parse(generated_xml).getroot()
    data2d = root.find(".//execution/constants/data2d")
    normals = root.find(".//normals")
    particles = root.find(".//execution/particles")
    constants = root.find(".//execution/constants")
    if data2d is None or data2d.get("value", "").lower() not in {"false", "0", "no"}:
        raise F3GenCaseError("actual generated XML is not explicit 3-D")
    if normals is None or normals.get("active", "").lower() not in {"true", "1", "yes"}:
        raise F3GenCaseError("actual generated XML does not enable normals")
    if particles is None or constants is None:
        raise F3GenCaseError("actual generated XML lacks particles/constants")
    fluid = root.find(".//execution/particles/fluid")
    fixed = root.find(".//execution/particles/fixed")
    if fluid is None or fixed is None:
        raise F3GenCaseError("actual generated XML lacks fixed/fluid typed blocks")
    fluid_count = int(fluid.get("count", "-1"))
    fixed_count = int(fixed.get("count", "-1"))
    total_count = int(particles.get("np", "-1"))
    mass_node = constants.find("massfluid")
    if mass_node is None:
        raise F3GenCaseError("actual generated XML lacks constants/massfluid")
    massfluid = float(mass_node.get("value", "nan"))
    actual_mass = fluid_count * massfluid
    mass_error = abs(actual_mass - expected_mass_kg) / expected_mass_kg
    output_stem = generated_xml.stem
    case_out = output_root / f"{output_stem}.out"
    case_bi4 = output_root / f"{output_stem}.bi4"
    fluid_vtk = output_root / f"{output_stem}_Fluid.vtk"
    normal_vtk = output_root / f"{output_stem}_hdp_Actual.vtk"
    if not case_out.is_file() or not case_bi4.is_file() or not fluid_vtk.is_file() or not normal_vtk.is_file():
        raise F3GenCaseError("actual GenCase output lacks .out/.bi4/Fluid.vtk/hdp_Actual.vtk")
    out_text = case_out.read_text(errors="replace")
    normal_match = re.search(r"Final zero normals:\s*0/([\d,]+)", out_text)
    nonzero_match = re.search(r"Non-zero particle normals:\s*([\d,]+)/([\d,]+)", out_text)
    points_match = re.search(rb"POINTS\s+(\d+)\s+", fluid_vtk.read_bytes()[:4096])
    vtk_points = None if points_match is None else int(points_match.group(1))
    normal_pass = bool(
        normal_match
        and nonzero_match
        and int(normal_match.group(1).replace(",", "")) == fixed_count
        and int(nonzero_match.group(1).replace(",", "")) == fixed_count
        and int(nonzero_match.group(2).replace(",", "")) == fixed_count
    )
    source_geometry = manifest["continuous_geometry"]
    normal_box = root.find(".//geometry/commands/list[@name='GeometryForNormals']/drawbox")
    if normal_box is None or normal_box.find("point") is None or normal_box.find("size") is None:
        raise F3GenCaseError("actual XML lacks GeometryForNormals drawbox")
    actual_low = _vector(normal_box.find("point"))
    actual_size = _vector(normal_box.find("size"))
    geometry_pass = _close_vector(actual_low, source_geometry["tank_low_m"]) and _close_vector(actual_size, source_geometry["tank_size_m"])
    control_ref = root.find(".//execution/special/accinputs/accinput/acctimesfile")
    control_path = None if control_ref is None else generated_xml.parent / str(control_ref.get("value"))
    report = {
        "schema": SCHEMA,
        "audit_status": "completed_actual_gencase_read_only",
        "claim": "actual F3 initialization/reference evidence only; no solver, Q-N, or production claim",
        "candidate_manifest": _ref(candidate_manifest),
        "candidate_dp_m": manifest["candidate_dp_m"],
        "generated_xml": _ref(generated_xml),
        "receipt": _ref(receipt),
        "output_root": str(output_root),
        "actual_3d": data2d.get("value"),
        "typed_counts": {"fixed": fixed_count, "fluid": fluid_count, "total": total_count},
        "mass": {
            "massfluid_kg": massfluid,
            "fluid_count": fluid_count,
            "initial_fluid_mass_kg": actual_mass,
            "expected_continuum_mass_kg": expected_mass_kg,
            "relative_error": mass_error,
            "within_1_percent": mass_error <= 0.01,
            "normalization": "none",
        },
        "continuous_geometry": {
            "expected": source_geometry,
            "actual_normal_box_low_m": actual_low,
            "actual_normal_box_size_m": actual_size,
            "matches": geometry_pass,
        },
        "initialization_outputs": {
            "case_out": _ref(case_out),
            "case_bi4": _ref(case_bi4),
            "fluid_vtk": _ref(fluid_vtk),
            "fluid_vtk_point_count": vtk_points,
            "fluid_vtk_count_matches": vtk_points == fluid_count,
            "normal_geometry_vtk": _ref(normal_vtk),
            "control_copy": None if control_path is None else _ref(control_path),
        },
        "normal_evidence": {
            "final_zero_normals_line": None if normal_match is None else normal_match.group(0),
            "nonzero_normals_line": None if nonzero_match is None else nonzero_match.group(0),
            "all_fixed_normals_nonzero": normal_pass,
        },
        "physical_binding_sha256": manifest.get("physical_binding_sha256"),
        "q_i_status": "actual GenCase 3-D/typed initialization evidence; no Q-N",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
    }
    report["passed_actual_preflight"] = bool(
        report["mass"]["within_1_percent"]
        and report["continuous_geometry"]["matches"]
        and report["initialization_outputs"]["fluid_vtk_count_matches"]
        and report["normal_evidence"]["all_fixed_normals_nonzero"]
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--source-def", type=Path, required=True)
    generate.add_argument("--output-def", type=Path, required=True)
    generate.add_argument("--dp", type=float, required=True)
    generate.add_argument("--owner-metadata", type=Path)
    generate.add_argument("--manifest", type=Path, required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--generated-xml", type=Path, required=True)
    audit.add_argument("--output-root", type=Path, required=True)
    audit.add_argument("--receipt", type=Path, required=True)
    audit.add_argument("--candidate-manifest", type=Path, required=True)
    audit.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "generate":
            manifest = generate_definition(args.source_def, args.output_def, args.dp, owner_metadata=args.owner_metadata)
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=_json_default) + "\n")
            print(json.dumps(manifest, sort_keys=True, default=_json_default))
        else:
            report = audit_gencase_output(
                generated_xml=args.generated_xml,
                output_root=args.output_root,
                receipt=args.receipt,
                candidate_manifest=args.candidate_manifest,
            )
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True, default=_json_default) + "\n")
            print(json.dumps(report, sort_keys=True, default=_json_default))
    except (F3GenCaseError, OSError, ET.ParseError, ValueError, json.JSONDecodeError) as exc:
        print(f"F3 GenCase utility failed: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

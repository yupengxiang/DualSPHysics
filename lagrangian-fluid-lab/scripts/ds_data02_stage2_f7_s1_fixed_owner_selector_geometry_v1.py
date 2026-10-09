#!/usr/bin/env python3
"""Derive a fixed-owner F7 selector lattice without mass fitting.

This is a source-only geometry diagnostic.  It derives cell centers from the
declared continuous-owner envelope and removes centers inside the fixed
paddle.  A second positive-volume overlap count is reported as a boundary
sensitivity diagnostic.  Neither rule searches for a target particle count
or mass, edits a Def, starts GenCase/solver, or opens BI4, OBI4, VTK, or HDF5.
The represented volume is reported against the immutable owner mass so the z
discretisation gap remains visible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f7.s1.fixed-owner-selector-geometry.v1"
MANIFEST_SCHEMA = "ds02.stage2.f7.s1.fixed-owner-selector-geometry.manifest.v1"
CASE_ID = "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1"
CURRENT_INDEX = 288
DP_M = 0.025
RHO_KG_M3 = 1000.0
OWNER_MASS_KG = 320.1984
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".hdf", ".vtk", ".obi4", ".bi4", ".bi2", ".bi1"}


class GeometryError(ValueError):
    """Raised when a source-bound fixed-owner contract is not closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def static_record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise GeometryError(f"source is not a regular file: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": sha256_file(path),
    }


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GeometryError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise GeometryError(f"{label} must be an object: {path}")
    return value


def expect(actual: Any, wanted: Any, label: str) -> None:
    if actual != wanted:
        raise GeometryError(f"{label}: expected {wanted!r}, got {actual!r}")


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GeometryError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise GeometryError(f"{label} is not finite")
    return result


def vec(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise GeometryError(f"{label} is not a length-three vector")
    return tuple(finite(item, f"{label}[{index}]") for index, item in enumerate(value))


def close_vec(actual: tuple[float, float, float], wanted: tuple[float, float, float], label: str, tol: float = 2e-15) -> None:
    if any(abs(a - b) > tol for a, b in zip(actual, wanted)):
        raise GeometryError(f"{label}: expected {wanted!r}, got {actual!r}")


def load_refs(manifest: dict[str, Any]) -> tuple[dict[str, Path], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    refs = manifest.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise GeometryError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    stats: dict[str, dict[str, Any]] = {}
    docs: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("key"), str):
            raise GeometryError("malformed source reference")
        key = ref["key"]
        if key in paths:
            raise GeometryError(f"duplicate source reference: {key}")
        path = Path(str(ref.get("path", ""))).expanduser().resolve()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise GeometryError(f"{key} points to forbidden native payload: {path}")
        if path.suffix.lower() not in {".json", ".xml"}:
            raise GeometryError(f"{key} is not JSON/XML: {path}")
        actual = static_record(path)
        if ref.get("sha256") not in (None, "PARENT_GUARD_COMPUTED"):
            expect(actual["sha256"], str(ref["sha256"]), f"{key} SHA")
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if ref.get(field) is not None:
                expect(actual[field], int(ref[field]), f"{key} {field}")
        paths[key] = path
        stats[key] = actual
        if ref.get("kind", "json") == "json":
            docs[key] = read_json(path, key)
    return paths, stats, docs


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _xml_vec(element: ET.Element, label: str) -> tuple[float, float, float]:
    return tuple(finite(element.get(axis), f"{label}.{axis}") for axis in ("x", "y", "z"))


def parse_control_xml(path: Path, *, expected_dp: str | None = None) -> dict[str, Any]:
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError) as exc:
        raise GeometryError(f"source control XML cannot be parsed: {path}") from exc
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise GeometryError("source control XML lacks geometry/definition")
    if expected_dp is not None:
        expect(definition.get("dp"), expected_dp, f"source dp ({path.name})")
    mainlist = root.find(".//geometry/commands/mainlist")
    if mainlist is None:
        raise GeometryError("source control XML lacks geometry commands")
    active_mk: str | None = None
    boxes: dict[str, list[tuple[tuple[float, float, float], tuple[float, float, float]]]] = {}
    for element in mainlist:
        tag = _tag(element)
        if tag in {"setmkbound", "setmkfluid"}:
            active_mk = element.get("mk")
        elif tag == "drawbox" and active_mk in {"0", "1", "2"}:
            point, size = element.find("point"), element.find("size")
            if point is None or size is None:
                raise GeometryError("source drawbox lacks point/size")
            low = _xml_vec(point, "drawbox.point")
            extent = _xml_vec(size, "drawbox.size")
            high = tuple(low[i] + extent[i] for i in range(3))
            boxes.setdefault(active_mk, []).append((low, high))
    if len(boxes.get("0", [])) != 1 or len(boxes.get("2", [])) != 1:
        raise GeometryError(f"source fixed geometry boxes are not closed: {boxes.keys()}")
    close_vec(boxes["0"][0][0], (-0.6, -0.4, 0.0), "source tank low")
    close_vec(boxes["0"][0][1], (0.6, 0.4, 0.6), "source tank high")
    close_vec(boxes["2"][0][0], (-0.07, -0.24, 0.05), "source paddle low")
    close_vec(boxes["2"][0][1], (-0.01, 0.24, 0.53), "source paddle high")
    constants = root.find(".//casedef/constantsdef")
    if constants is None:
        raise GeometryError("source control XML lacks constantsdef")
    gravity, rhop0 = constants.find("gravity"), constants.find("rhop0")
    if gravity is None or rhop0 is None:
        raise GeometryError("source control XML lacks gravity/rhop0")
    close_vec(_xml_vec(gravity, "gravity"), (0.0, 0.0, -9.81), "source gravity")
    expect(finite(rhop0.get("value"), "rhop0"), RHO_KG_M3, "source density")
    return {
        "definition_dp": definition.get("dp"),
        "tank_low": boxes["0"][0][0],
        "tank_high": boxes["0"][0][1],
        "paddle_low": boxes["2"][0][0],
        "paddle_high": boxes["2"][0][1],
    }


def validate_current(current: dict[str, Any]) -> dict[str, Any]:
    cases = current.get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise GeometryError("CURRENT336 does not expose exactly 336 cases")
    row = cases[CURRENT_INDEX]
    if not isinstance(row, dict):
        raise GeometryError("CURRENT F7 row is malformed")
    expect(row.get("family_id"), "F7", "CURRENT family")
    expect(row.get("physical_case_id"), CASE_ID, "CURRENT physical case")
    expect(row.get("runtime_case_alias"), "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE", "CURRENT runtime alias")
    return {"case_key": row.get("case_key"), "index": CURRENT_INDEX, "family_id": row["family_id"], "physical_case_id": row["physical_case_id"], "runtime_case_alias": row["runtime_case_alias"]}


def validate_owner(owner: dict[str, Any]) -> dict[str, Any]:
    binding = owner.get("physical_binding")
    if not isinstance(binding, dict):
        raise GeometryError("owner metadata lacks physical_binding")
    expect(binding.get("physical_case_id"), CASE_ID, "owner physical case")
    geometry = binding.get("geometry")
    if not isinstance(geometry, dict):
        raise GeometryError("owner metadata lacks geometry")
    envelope = geometry.get("fluid_envelope")
    paddle = geometry.get("paddle")
    if not isinstance(envelope, dict) or not isinstance(paddle, dict):
        raise GeometryError("owner geometry lacks fluid envelope/paddle")
    owner_low = vec(envelope.get("low_m"), "owner envelope low")
    envelope_size = vec(envelope.get("size_m"), "owner envelope size")
    owner_high = tuple(owner_low[i] + envelope_size[i] for i in range(3))
    paddle_low = vec(paddle.get("low_m"), "owner paddle low")
    paddle_size = vec(paddle.get("size_m"), "owner paddle size")
    paddle_high = tuple(paddle_low[i] + paddle_size[i] for i in range(3))
    close_vec(owner_low, (-0.55, -0.35, 0.05), "owner envelope low")
    close_vec(owner_high, (0.55, 0.35, 0.482), "owner envelope high")
    close_vec(paddle_low, (-0.07, -0.24, 0.05), "owner paddle low")
    close_vec(paddle_high, (-0.01, 0.24, 0.53), "owner paddle high")
    initial = binding.get("initial_state")
    if not isinstance(initial, dict):
        raise GeometryError("owner metadata lacks initial_state")
    masses = initial.get("continuum_mass_by_source_kg")
    expect(masses, {"fluid": OWNER_MASS_KG}, "owner continuum mass")
    expect(initial.get("initial_mass_total_kg"), OWNER_MASS_KG, "owner initial mass")
    return {
        "low": owner_low,
        "high": owner_high,
        "paddle_low": paddle_low,
        "paddle_high": paddle_high,
        "owner_mass_kg": OWNER_MASS_KG,
        "rho_kg_m3": finite(binding.get("density_kg_m3"), "owner density"),
    }


def axis_cells(low: float, high: float, dp: float = DP_M) -> list[tuple[float, float, float]]:
    """Return fully contained (low, center, high) cells using Decimal floor."""
    lo, hi, step = Decimal(str(low)), Decimal(str(high)), Decimal(str(dp))
    count = int(((hi - lo) / step).to_integral_value(rounding=ROUND_FLOOR))
    return [(float(lo + i * step), float(lo + (Decimal(i) + Decimal("0.5")) * step), float(lo + (i + 1) * step)) for i in range(count)]


def positive_overlap(a_low: float, a_high: float, b_low: float, b_high: float) -> bool:
    return min(a_high, b_high) > max(a_low, b_low)


def center_inside(center: float, low: float, high: float) -> bool:
    """Use a half-open center predicate; upper-face equality is not guessed."""
    return low <= center < high


def center_hits_paddle(center: tuple[float, float, float], paddle_low: tuple[float, float, float], paddle_high: tuple[float, float, float]) -> bool:
    return all(center_inside(center[i], paddle_low[i], paddle_high[i]) for i in range(3))


def cell_hits_paddle(cell: tuple[tuple[float, float, float], tuple[float, float, float]], paddle_low: tuple[float, float, float], paddle_high: tuple[float, float, float]) -> bool:
    low, high = cell
    return all(positive_overlap(low[i], high[i], paddle_low[i], paddle_high[i]) for i in range(3))


def derive_owner_lattice(owner: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    close_vec(owner["paddle_low"], control["paddle_low"], "owner/control paddle low")
    close_vec(owner["paddle_high"], control["paddle_high"], "owner/control paddle high")
    axes = [axis_cells(owner["low"][i], owner["high"][i]) for i in range(3)]
    dimensions = [len(axis) for axis in axes]
    all_cells = []
    center_excluded = []
    center_selected = []
    overlap_excluded = []
    for x in axes[0]:
        for y in axes[1]:
            for z in axes[2]:
                low = (x[0], y[0], z[0])
                high = (x[2], y[2], z[2])
                center = (x[1], y[1], z[1])
                cell = (low, high)
                all_cells.append(cell)
                if center_hits_paddle(center, owner["paddle_low"], owner["paddle_high"]):
                    center_excluded.append(cell)
                else:
                    center_selected.append(cell)
                if cell_hits_paddle(cell, owner["paddle_low"], owner["paddle_high"]):
                    overlap_excluded.append(cell)
    cell_volume = DP_M**3
    represented_volume = len(center_selected) * cell_volume
    envelope_volume = math.prod(owner["high"][i] - owner["low"][i] for i in range(3))
    paddle_overlap_volume = math.prod(max(0.0, min(owner["high"][i], owner["paddle_high"][i]) - max(owner["low"][i], owner["paddle_low"][i])) for i in range(3))
    owner_fluid_volume = envelope_volume - paddle_overlap_volume
    represented_mass = represented_volume * RHO_KG_M3
    return {
        "rule": "full_cell_inside_owner_envelope_then_remove_cell_centers_inside_paddle",
        "mass_fit_search": False,
        "target_count_search": False,
        "dp_m": DP_M,
        "axis_dimensions": {"x": dimensions[0], "y": dimensions[1], "z": dimensions[2]},
        "axis_center_ranges_m": {axis: [cells[0][1], cells[-1][1]] for axis, cells in zip(("x", "y", "z"), axes)},
        "owner_envelope_m": {"low": list(owner["low"]), "high": list(owner["high"])},
        "represented_cell_union_m": {"low": [axes[i][0][0] for i in range(3)], "high": [axes[i][-1][2] for i in range(3)]},
        "paddle_m": {"low": list(owner["paddle_low"]), "high": list(owner["paddle_high"])},
        "all_envelope_cells": len(all_cells),
        "paddle_excluded_cells_center_rule": len(center_excluded),
        "selected_cells_center_rule": len(center_selected),
        "paddle_excluded_cells_positive_volume_diagnostic": len(overlap_excluded),
        "selected_cells_positive_volume_diagnostic": len(all_cells) - len(overlap_excluded),
        "paddle_boundary_rule_changes_count": len(center_excluded) != len(overlap_excluded),
        "cell_volume_m3": cell_volume,
        "owner_envelope_volume_m3": envelope_volume,
        "owner_paddle_overlap_volume_m3": paddle_overlap_volume,
        "owner_fluid_volume_m3": owner_fluid_volume,
        "owner_mass_kg": owner["owner_mass_kg"],
        "represented_volume_m3": represented_volume,
        "represented_mass_kg": represented_mass,
        "represented_minus_owner_mass_kg": represented_mass - owner["owner_mass_kg"],
        "represented_mass_fraction_of_owner": represented_mass / owner["owner_mass_kg"],
        "positive_volume_overlap_diagnostic_mass_kg": (len(all_cells) - len(overlap_excluded)) * cell_volume * RHO_KG_M3,
        "support_gap_is_discretisation": True,
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise GeometryError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def derive(manifest_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path.resolve(), "fixed-owner manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    paths, stats, docs = load_refs(manifest)
    for key in ("current336", "owner_metadata", "root143_proof", "root146_proof", "root149_proof", "root154_proof"):
        if key not in docs:
            raise GeometryError(f"required JSON reference is missing: {key}")
    current = validate_current(docs["current336"])
    owner = validate_owner(docs["owner_metadata"])
    control = parse_control_xml(paths["source_control_xml"])
    coarse_def = parse_control_xml(paths["coarse_def"], expected_dp="0.025")
    lattice = derive_owner_lattice(owner, control)
    # Parse/validate the preflight Def as a second immutable declaration, but
    # do not copy or modify it and do not interpret it as a generated result.
    close_vec(control["paddle_low"], coarse_def["paddle_low"], "source/control paddle low")
    close_vec(control["paddle_high"], coarse_def["paddle_high"], "source/control paddle high")
    return {
        "schema": SCHEMA,
        "status": "ACTUAL_FIXED_OWNER_LATTICE_GEOMETRY_DIAGNOSTIC_NO_GENCASE",
        "current_binding": current,
        "source_inputs": {key: stats[key] for key in stats},
        "owner_contract": {
            "mass_policy": "unscaled declared continuous owner mass; no target fitting",
            "owner_mass_kg": owner["owner_mass_kg"],
            "density_kg_m3": RHO_KG_M3,
            "paddle_intersection_rule": "positive-volume intersection",
        },
        "dp_declarations": {
            "source_control_xml_dp": control["definition_dp"],
            "preflight_coarse_def_dp": coarse_def["definition_dp"],
            "lattice_dp": DP_M,
            "source_and_lattice_dp_equal": control["definition_dp"] == format(DP_M, "g"),
            "preflight_and_lattice_dp_equal": coarse_def["definition_dp"] == format(DP_M, "g"),
            "dp_mismatch_is_not_mass_or_science_credit": True,
        },
        "lattice": lattice,
        "comparison": {
            "ROOT154_candidate_is_separate": True,
            "ROOT154_predicted_cells": 20484,
            "ROOT154_predicted_mass_kg": 320.0625,
            "this_rule_does_not_reproduce_massfit_candidate": True,
            "continuous_owner_equivalence": "UNKNOWN",
            "GenCase_rounding_and_boundary_inclusion": "UNKNOWN",
        },
        "qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "wall_contact_or_penetration": "UNKNOWN",
            "legal_flux_or_spill": "UNKNOWN",
            "dynamics": "UNKNOWN",
        },
        "read_policy": {
            "json_xml_only": True,
            "h5_opened": False,
            "bi4_opened": False,
            "obi4_opened": False,
            "vtk_opened": False,
            "solver_started": False,
            "gencase_started": False,
            "old_products_modified": False,
        },
        "scope_limits": [
            "The lattice is a deterministic representation of the declared owner envelope, not an actual GenCase particle result.",
            "The z extent is truncated by full-cell containment because 0.432 m is not an integer number of 0.025 m cells.",
            "Represented mass deficit is a discretisation/support diagnostic and cannot be repaired by rescaling or by claiming physical outflow.",
            "ROOT154 remains an immutable selector-sensitivity candidate with a different cropped/shifted support.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        atomic_json(args.output, derive(args.manifest))
    except GeometryError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

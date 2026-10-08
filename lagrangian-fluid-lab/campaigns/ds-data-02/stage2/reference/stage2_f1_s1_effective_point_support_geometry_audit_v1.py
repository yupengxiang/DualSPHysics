#!/usr/bin/env python3
"""Audit the three completed F1-S1 GenCase geometry products.

This is a bounded CPU metadata/geometry audit.  It consumes the exact
completed ``.010`` default product and the exact ``.009`` ``actual`` and
``bound`` products, their receipts, generated XML/OUT, and the four small
``-save:all`` VTK products.  It never opens a BI4/HDF5 file and never starts
GenCase or a solver.

The audit answers a narrow question: do equal particle counts represent an
equal effective point/support geometry for these exact source inputs?  It
uses the binary VTK POINTS payload digest and coordinate bounds, rather than
count alone.  The CURRENT owner contract remains the authority for the
continuous fluid reservoir; a particle quadrature mass and a midpoint-cell
support envelope are reported as discretization evidence only.  The two
``.009`` mode products are one resolution and therefore cannot supply a
third spatial grid.

The generated report is intentionally additive and immutable.  It is an
input-bound preparation artifact, not QI/QN/QE qualification.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import tempfile
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f1-s1.effective-point-support-geometry-audit.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
V8_RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
V8_STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
V8_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"

OWNER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/"
    "handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/"
    "ecc_coarse/owner.json"
)
BINDING = OWNER.parent.parent / "ecc-physical-binding.json"
CURRENT_SOURCE_ROOT = DATA_ROOT / "families/F1/F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027/prepared"
CURRENT_SOURCE_DEF = CURRENT_SOURCE_ROOT / "F1_FALLBACK_ECC_COARSE_Def.xml"
CURRENT_SOURCE_XML = CURRENT_SOURCE_ROOT / "F1_FALLBACK_ECC_COARSE.xml"
CURRENT_SOURCE_RECEIPT = CURRENT_SOURCE_ROOT.parent / "execution-receipt.json"

DEFAULT_ROOT = DATA_ROOT / "families/F1/F1_S1_SPATIAL_ORIGINAL_DP0p010000/f1_s1_spatial_original_dp0p010000-001"
ACTUAL_ROOT = DATA_ROOT / "families/F1/F1_S1_SPATIAL_MODE_ACTUAL_DP0p009000/f1-s1-spatial-mode-actual-dp0p009000-v2-root-001-root-forward-001"
BOUND_ROOT = DATA_ROOT / "families/F1/F1_S1_SPATIAL_MODE_BOUND_DP0p009000/f1-s1-spatial-mode-bound-dp0p009000-v2-root-001-root-forward-001"

DEFAULT_DEF = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_sentinel_spatial_preflight_inputs_v1/F1_S1/original/F1_S1_SPATIAL_ORIGINAL_DP0p010000_Def.xml"
ACTUAL_DEF = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_s1_geometry_mode_probe_inputs_v2/F1_S1/dp0p009000/setshapemode_actual/F1_S1_DP009_MODE_ACTUAL_Def.xml"
BOUND_DEF = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_s1_geometry_mode_probe_inputs_v2/F1_S1/dp0p009000/setshapemode_bound/F1_S1_DP009_MODE_BOUND_Def.xml"

CASE_ID = "F1_S1_EFFECTIVE_POINT_SUPPORT_GEOMETRY_AUDIT_V1"
ATTEMPT_ID = "f1-s1-effective-point-support-geometry-audit-v1-root-001"
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-s1-effective-point-support-geometry-audit-v1"
REQUEST_PATH = REQUEST_DIR / "f1_s1_effective_point_support_geometry_audit_v1.json"
DEFAULT_OUTPUT = Path(__file__).with_name("stage2_f1_s1_effective_point_support_geometry_audit_v1.json")

FILE_NAMES = (
    "generated.xml",
    "generated.out",
    "generated_Fluid.vtk",
    "generated_Bound.vtk",
    "generated_All.vtk",
    "generated_MkCells.vtk",
)
VTK_NAMES = FILE_NAMES[2:]
VTK_POINTS_RE = re.compile(rb"POINTS\s+(\d+)\s+float\s*\r?\n")
TOL = 2.0e-6
INDEX_TOL = 2.0e-5
OWNER_LOW = [0.0, 0.0, 0.0]
OWNER_SIZE = [0.4, 0.67, 0.15]
OWNER_UPPER = [OWNER_LOW[i] + OWNER_SIZE[i] for i in range(3)]
OWNER_MASS_KG = 40.2
OWNER_DENSITY_KG_M3 = 1000.0

CASES: dict[str, dict[str, Any]] = {
    "default": {
        "case_id": "F1_S1_SPATIAL_ORIGINAL_DP0p010000",
        "attempt_id": "f1_s1_spatial_original_dp0p010000-001",
        "root": DEFAULT_ROOT,
        "source_def": DEFAULT_DEF,
        "dp_m": 0.01,
        "expected_shape": "dp | actual | bound",
        "resolution_role": "original_default_grid",
    },
    "actual": {
        "case_id": "F1_S1_SPATIAL_MODE_ACTUAL_DP0p009000",
        "attempt_id": "f1-s1-spatial-mode-actual-dp0p009000-v2-root-001-root-forward-001",
        "root": ACTUAL_ROOT,
        "source_def": ACTUAL_DEF,
        "dp_m": 0.009,
        "expected_shape": "actual",
        "resolution_role": "mode_probe_dp009",
    },
    "bound": {
        "case_id": "F1_S1_SPATIAL_MODE_BOUND_DP0p009000",
        "attempt_id": "f1-s1-spatial-mode-bound-dp0p009000-v2-root-001-root-forward-001",
        "root": BOUND_ROOT,
        "source_def": BOUND_DEF,
        "dp_m": 0.009,
        "expected_shape": "bound",
        "resolution_role": "mode_probe_dp009",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def file_record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": sha256(path),
    }


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object: {path}")
    return value


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def finite(value: str | None, label: str) -> float:
    if value is None:
        raise ValueError(f"missing {label}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite {label}")
    return result


def vector(node: ET.Element | None, label: str) -> list[float]:
    if node is None:
        raise ValueError(f"missing {label}")
    return [finite(node.get(axis), f"{label}.{axis}") for axis in ("x", "y", "z")]


def canonical_xml(path: Path) -> Any:
    """Canonicalize source Def semantics, leaving only dp/mode replaceable."""

    root = ET.parse(regular(path, "source Def")).getroot()

    def node_value(node: ET.Element) -> Any:
        tag = local_name(node.tag)
        attrs = dict(sorted(node.attrib.items()))
        if tag == "case":
            attrs.pop("date", None)
        if tag == "definition" and "dp" in attrs:
            attrs["dp"] = "<INTENTIONAL_DP>"
        text = (node.text or "").strip()
        if tag == "setshapemode":
            text = "<INTENTIONAL_SHAPEMODE>"
        return {
            "tag": tag,
            "attributes": attrs,
            "text": text,
            "children": [node_value(child) for child in list(node)],
        }

    return node_value(root)


def parse_xml(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    root = ET.parse(path).getroot()
    definition = next((node for node in root.iter() if local_name(node.tag) == "definition"), None)
    if definition is None:
        raise ValueError(f"{label} has no geometry definition")
    pointref = vector(next((node for node in definition if local_name(node.tag) == "pointref"), None), f"{label}.pointref")
    dp = finite(definition.get("dp"), f"{label}.dp")
    shapes = [(node.text or "").strip() for node in root.iter() if local_name(node.tag) == "setshapemode"]
    particles = next((node for node in root.iter() if local_name(node.tag) == "particles"), None)
    fluid_nodes = [node for node in list(particles or []) if local_name(node.tag) == "fluid"]
    if not fluid_nodes:
        raise ValueError(f"{label} has no fluid blocks")
    counts: list[int] = []
    for node in fluid_nodes:
        if node.get("count") is None:
            raise ValueError(f"{label} fluid block lacks count")
        counts.append(int(node.get("count")))
    constants = next((node for node in root.iter() if local_name(node.tag) == "constants"), None)
    mass_node = next((node for node in list(constants or []) if local_name(node.tag) == "massfluid"), None)
    rhop_nodes = [node for node in root.iter() if local_name(node.tag) == "rhop0"]
    massfluid = finite(mass_node.get("value"), f"{label}.massfluid") if mass_node is not None else None
    density = finite(rhop_nodes[-1].get("value"), f"{label}.rhop0") if rhop_nodes else None
    boxes: list[dict[str, Any]] = []
    active_mkfluid: str | None = None
    for node in root.iter():
        tag = local_name(node.tag)
        if tag == "setmkfluid":
            active_mkfluid = node.get("mk")
        elif tag in {"setmkbound", "setmkvoid"}:
            active_mkfluid = None
        elif tag == "drawbox" and active_mkfluid is not None:
            boxfill = next((child for child in node if local_name(child.tag) == "boxfill"), None)
            if boxfill is None or (boxfill.text or "").strip().lower() != "solid":
                continue
            point = vector(next((child for child in node if local_name(child.tag) == "point"), None), f"{label}.fluid.drawbox.point")
            size = vector(next((child for child in node if local_name(child.tag) == "size"), None), f"{label}.fluid.drawbox.size")
            if any(value <= 0.0 for value in size):
                raise ValueError(f"{label} has non-positive fluid drawbox")
            boxes.append({
                "mkfluid_relative": active_mkfluid,
                "comment": node.get("cmt"),
                "point_m": point,
                "size_m": size,
                "upper_m": [point[i] + size[i] for i in range(3)],
                "volume_m3": math.prod(size),
            })
    if not boxes:
        raise ValueError(f"{label} has no solid fluid drawbox")
    count = sum(counts)
    return {
        "file": file_record(path, label),
        "case_app": root.get("app"),
        "generated_date": root.get("date"),
        "definition": {"dp_m": dp, "pointref_m": pointref},
        "setshapemode": shapes,
        "fluid_blocks": [{"count": count_value, "attributes": dict(node.attrib)} for count_value, node in zip(counts, fluid_nodes)],
        "fluid_count_from_xml": count,
        "massfluid_kg": massfluid,
        "density_kg_m3": density,
        "sample_mass_kg": count * massfluid if massfluid is not None else None,
        "fluid_drawboxes": boxes,
        "fluid_drawbox_last": boxes[-1],
    }


def grouped(values: list[float]) -> list[float]:
    result: list[float] = []
    for value in sorted(values):
        if not result or abs(value - result[-1]) > TOL:
            result.append(value)
    return result


def parse_vtk(path: Path, xml: dict[str, Any], label: str, *, fluid: bool = False) -> dict[str, Any]:
    path = regular(path, label)
    raw = path.read_bytes()
    match = VTK_POINTS_RE.search(raw)
    if match is None:
        raise ValueError(f"{label} lacks binary POINTS header")
    count = int(match.group(1))
    offset = match.end()
    payload_size = 3 * count * 4
    if len(raw) < offset + payload_size:
        raise ValueError(f"{label} POINTS payload is truncated")
    payload = raw[offset:offset + payload_size]
    values = struct.unpack(f">{3 * count}f", payload)
    axes = [list(values[index::3]) for index in range(3)]
    axis_records: list[dict[str, Any]] = []
    dp = xml["definition"]["dp_m"]
    pointref = xml["definition"]["pointref_m"]
    drawbox = xml["fluid_drawbox_last"]
    for axis, values_axis in enumerate(axes):
        unique = grouped(values_axis)
        if not unique:
            raise ValueError(f"{label} axis {axis} is empty")
        steps = [unique[i + 1] - unique[i] for i in range(len(unique) - 1)]
        indices = [(value - pointref[axis]) / dp for value in unique]
        residual = max(abs(value - round(value)) for value in indices)
        axis_records.append({
            "axis": "xyz"[axis],
            "unique_count": len(unique),
            "first_m": unique[0],
            "last_m": unique[-1],
            "step_min_m": min(steps) if steps else None,
            "step_median_m": sorted(steps)[len(steps) // 2] if steps else None,
            "step_max_m": max(steps) if steps else None,
            "pointref_index_first": indices[0],
            "pointref_index_last": indices[-1],
            "pointref_index_max_integer_residual": residual,
            "all_points_inside_fluid_xml_drawbox": (
                (not fluid)
                or (min(values_axis) >= drawbox["point_m"][axis] - TOL and max(values_axis) <= drawbox["upper_m"][axis] + TOL)
            ),
            "cell_envelope_low_m": unique[0] - dp / 2.0,
            "cell_envelope_high_m": unique[-1] + dp / 2.0,
        })
    return {
        "file": file_record(path, label),
        "point_count_header": count,
        "points_payload_sha256": hashlib.sha256(payload).hexdigest(),
        "axis": axis_records,
        "axis_count_product": math.prod(item["unique_count"] for item in axis_records),
        "point_bounds_m": {
            "lower_m": [min(values_axis) for values_axis in axes],
            "upper_m": [max(values_axis) for values_axis in axes],
        },
        "lattice_phase": {
            "first_point_minus_pointref_over_dp": [item["pointref_index_first"] for item in axis_records],
            "last_point_minus_pointref_over_dp": [item["pointref_index_last"] for item in axis_records],
            "all_axis_indices_integer_within_tolerance": all(item["pointref_index_max_integer_residual"] <= INDEX_TOL for item in axis_records),
        },
        "observed_midpoint_cell_envelope_m": {
            "lower_m": [item["cell_envelope_low_m"] for item in axis_records],
            "upper_m": [item["cell_envelope_high_m"] for item in axis_records],
        },
        "fluid_drawbox_observation": {
            "lower_m": drawbox["point_m"],
            "upper_m": drawbox["upper_m"],
            "all_points_inside": all(item["all_points_inside_fluid_xml_drawbox"] for item in axis_records),
        },
    }


def parse_receipt(spec: dict[str, Any], label: str) -> dict[str, Any]:
    root = Path(spec["root"])
    receipt_path = root / "execution-receipt.json"
    receipt = load_json(receipt_path, f"{label} receipt")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"{label} is not a successful completed receipt")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise ValueError(f"{label} receipt lacks embedded request")
    identity = {
        "family_id": request.get("family_id"),
        "sentinel_id": request.get("sentinel_id"),
        "physical_case_id": request.get("physical_case_id"),
        "case_id": request.get("case_id"),
        "attempt_id": request.get("attempt_id"),
    }
    if identity["sentinel_id"] is None:
        identity["sentinel_id"] = request.get("scope", {}).get("sentinel_id")
    if identity["physical_case_id"] is None:
        identity["physical_case_id"] = request.get("scope", {}).get("physical_case_id")
    expected = {
        "family_id": "F1",
        "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": spec["case_id"],
        "attempt_id": spec["attempt_id"],
    }
    if identity != expected:
        raise ValueError(f"{label} identity mismatch: {identity} != {expected}")
    if Path(str(receipt.get("output_root", ""))).expanduser().resolve() != root.resolve():
        raise ValueError(f"{label} receipt output root differs from exact terminal root")
    for key in ("solver_started", "cfd_invoked", "model_invoked", "bi4_read", "hdf5_read"):
        value = request.get(key)
        if value is True:
            raise ValueError(f"{label} unexpectedly reports {key}=true")
    launch_hashes = receipt.get("input_hashes_at_launch")
    end_hashes = receipt.get("input_hashes_after_run")
    stable = launch_hashes == end_hashes if launch_hashes is not None and end_hashes is not None else None
    if stable is False:
        raise ValueError(f"{label} source input hashes changed during GenCase")
    return {
        "receipt": file_record(receipt_path, f"{label} receipt"),
        "status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "request_sha256": receipt.get("request_sha256"),
        "identity": identity,
        "request_scope": {
            "cpu_task_kind": request.get("cpu_task_kind"),
            "command": request.get("command"),
            "input_files": request.get("input_files"),
            "input_hashes": request.get("input_hashes"),
            "solver_started": request.get("solver_started"),
            "cfd_invoked": request.get("cfd_invoked"),
            "bi4_read": request.get("bi4_read"),
            "hdf5_read": request.get("hdf5_read"),
        },
        "source_hashes_stable": stable,
        "elapsed_seconds": receipt.get("elapsed_seconds"),
        "cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "terminal_bytes": receipt.get("bytes"),
    }


def owner_contract() -> dict[str, Any]:
    owner = load_json(OWNER, "F1 CURRENT owner")
    binding = load_json(BINDING, "F1 canonical physical binding")
    physical = owner.get("physical_binding")
    if not isinstance(physical, dict):
        raise ValueError("owner physical_binding missing")
    geometry = physical.get("geometry", {}).get("fluid_reservoir")
    initial = physical.get("initial_state", {}).get("source_regions", {}).get("fluid")
    if geometry != initial:
        raise ValueError("owner reservoir and initial fluid source differ")
    low = [float(value) for value in geometry["low_m"]]
    size = [float(value) for value in geometry["size_m"]]
    density = float(physical["density_kg_m3"])
    mass = float(physical["initial_state"]["continuum_mass_by_source_kg"]["fluid"])
    if low != OWNER_LOW or size != OWNER_SIZE or abs(math.prod(size) * density - mass) > 1.0e-12 or abs(mass - OWNER_MASS_KG) > 1.0e-12:
        raise ValueError("owner continuous geometry contract changed")
    payload = binding.get("physical_binding")
    if not isinstance(payload, dict) or payload.get("family_id") != "F1" or payload.get("physical_case_id") != "F1_ECC_THICK_DBC_LOWER_HEAD_V1":
        raise ValueError("canonical binding identity mismatch")
    if binding.get("physical_condition_sha256") != owner.get("physical_condition_sha256"):
        raise ValueError("owner and canonical physical condition hashes differ")
    return {
        "owner_file": file_record(OWNER, "F1 owner"),
        "canonical_binding_file": file_record(BINDING, "F1 canonical binding"),
        "identity": {key: owner.get(key) for key in ("family_id", "case_id", "physical_case_id", "mechanism_id")},
        "physical_condition_sha256": owner.get("physical_condition_sha256"),
        "continuous_source_contract": {
            "low_m": low,
            "size_m": size,
            "upper_m": [low[i] + size[i] for i in range(3)],
            "volume_m3": math.prod(size),
            "density_kg_m3": density,
            "mass_kg": mass,
            "mkfluid_relative": geometry.get("mkfluid"),
            "authority": "CURRENT336 owner/physical-binding; not inferred from particle samples",
        },
        "mass_policy": physical["initial_state"].get("mass_policy"),
    }


def source_semantics() -> dict[str, Any]:
    records = {label: file_record(spec["source_def"], f"{label} source Def") for label, spec in CASES.items()}
    canonical = {label: canonical_xml(spec["source_def"]) for label, spec in CASES.items()}
    equal = canonical["default"] == canonical["actual"] == canonical["bound"]
    return {
        "source_definitions": records,
        "normalization": {
            "replaced": ["definition@dp", "setshapemode text"],
            "dropped": ["case@date"],
            "meaning": "Only registered resolution/mode inputs are normalized; continuous drawboxes, motion, controls, and material definitions remain compared.",
        },
        "normalized_continuous_source_equal": equal,
        "status": "PASS_SOURCE_DEF_EQUAL_AFTER_INTENTIONAL_DP_MODE_ONLY" if equal else "FAIL_SOURCE_DEF_HAS_UNREGISTERED_DIFFERENCE",
    }


def parse_case(label: str, spec: dict[str, Any]) -> dict[str, Any]:
    root = Path(spec["root"])
    receipt = parse_receipt(spec, f"F1-S1 {label}")
    xml = parse_xml(root / "generated.xml", f"F1-S1 {label} generated XML")
    if abs(xml["definition"]["dp_m"] - spec["dp_m"]) > 1.0e-12:
        raise ValueError(f"F1-S1 {label} generated dp mismatch")
    if xml["setshapemode"] != [spec["expected_shape"]]:
        raise ValueError(f"F1-S1 {label} generated setshapemode mismatch: {xml['setshapemode']}")
    products = {
        name: parse_vtk(root / name, xml, f"F1-S1 {label} {name}", fluid=name == "generated_Fluid.vtk")
        for name in VTK_NAMES
    }
    fluid = products["generated_Fluid.vtk"]
    bound = products["generated_Bound.vtk"]
    all_points = products["generated_All.vtk"]
    if fluid["point_count_header"] != xml["fluid_count_from_xml"]:
        raise ValueError(f"F1-S1 {label} Fluid.vtk/XML count mismatch")
    if all_points["point_count_header"] != fluid["point_count_header"] + bound["point_count_header"]:
        raise ValueError(f"F1-S1 {label} All.vtk count does not equal Fluid+Bound")
    envelope = fluid["observed_midpoint_cell_envelope_m"]
    residual_low = [envelope["lower_m"][i] - OWNER_LOW[i] for i in range(3)]
    residual_high = [envelope["upper_m"][i] - OWNER_UPPER[i] for i in range(3)]
    max_residual = max(max(abs(value) for value in residual_low), max(abs(value) for value in residual_high))
    sample_mass = fluid["point_count_header"] * xml["massfluid_kg"]
    return {
        "case_id": spec["case_id"],
        "attempt_id": spec["attempt_id"],
        "resolution_role": spec["resolution_role"],
        "root": str(root),
        "receipt": receipt,
        "source_def": file_record(spec["source_def"], f"F1-S1 {label} source Def"),
        "generated_xml": xml,
        "generated_out": file_record(root / "generated.out", f"F1-S1 {label} generated OUT"),
        "products": products,
        "effective_fluid_point_count": fluid["point_count_header"],
        "effective_bound_point_count": bound["point_count_header"],
        "effective_all_point_count": all_points["point_count_header"],
        "sample_mass_kg": sample_mass,
        "sample_mass_error_pct_vs_owner": 100.0 * (sample_mass - OWNER_MASS_KG) / OWNER_MASS_KG,
        "fluid_midpoint_cell_envelope_vs_owner": {
            "lower_residual_m": residual_low,
            "upper_residual_m": residual_high,
            "max_abs_residual_m": max_residual,
            "matches_owner_within_2e-6_m": max_residual <= TOL,
        },
    }


def product_equal(left: dict[str, Any], right: dict[str, Any], name: str) -> dict[str, Any]:
    lp = left["products"][name]
    rp = right["products"][name]
    return {
        "point_count_equal": lp["point_count_header"] == rp["point_count_header"],
        "points_payload_sha256_equal": lp["points_payload_sha256"] == rp["points_payload_sha256"],
        "file_sha256_equal": lp["file"]["sha256"] == rp["file"]["sha256"],
        "point_count_left": lp["point_count_header"],
        "point_count_right": rp["point_count_header"],
        "same_effective_point_payload": lp["point_count_header"] == rp["point_count_header"] and lp["points_payload_sha256"] == rp["points_payload_sha256"],
    }


def compare_cases(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    products = {name: product_equal(left, right, name) for name in VTK_NAMES}
    return {
        "left_case_id": left["case_id"],
        "right_case_id": right["case_id"],
        "products": products,
        "all_selected_products_byte_equal": all(item["file_sha256_equal"] for item in products.values()),
        "fluid_same_count_and_effective_points": products["generated_Fluid.vtk"]["same_effective_point_payload"],
        "bound_same_count_and_effective_points": products["generated_Bound.vtk"]["same_effective_point_payload"],
        "all_same_count_and_effective_points": products["generated_All.vtk"]["same_effective_point_payload"],
    }


def audit(output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refuse to overwrite immutable report: {output}")
    owner = owner_contract()
    source = source_semantics()
    parsed = {label: parse_case(label, spec) for label, spec in CASES.items()}
    actual_bound = compare_cases(parsed["actual"], parsed["bound"])
    default_actual = compare_cases(parsed["default"], parsed["actual"])
    default_bound = compare_cases(parsed["default"], parsed["bound"])
    same_dp009 = actual_bound["fluid_same_count_and_effective_points"] and actual_bound["bound_same_count_and_effective_points"] and actual_bound["all_same_count_and_effective_points"]
    report = {
        "schema": SCHEMA,
        "status": "PASS_THREE_SOURCE_GEOMETRY_AUDIT_WITH_DP009_MODE_EQUIVALENCE" if source["normalized_continuous_source_equal"] and same_dp009 else "FAIL_GEOMETRY_SOURCE_OR_MODE_AUDIT",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_scope": {
            "bi4_read": False,
            "hdf5_read": False,
            "solver_launch": False,
            "gencase_launch": False,
            "read_inputs": "completed GenCase receipts, generated XML/OUT, source Defs, and four generated VTK point payloads per case",
            "excluded_inputs": ["generated.bi4", "native H5/trajectory files", "solver outputs"],
            "source_outputs_immutable": True,
        },
        "source_authority": owner,
        "continuous_source_semantics": source,
        "cases": parsed,
        "comparisons": {
            "actual_vs_bound": actual_bound,
            "default_vs_actual": default_actual,
            "default_vs_bound": default_bound,
        },
        "effective_point_support_conclusion": {
            "same_count_is_sufficient": False,
            "actual_bound_same_fluid_count": parsed["actual"]["effective_fluid_point_count"] == parsed["bound"]["effective_fluid_point_count"],
            "actual_bound_same_effective_fluid_points": actual_bound["fluid_same_count_and_effective_points"],
            "actual_bound_same_effective_bound_points": actual_bound["bound_same_count_and_effective_points"],
            "actual_bound_same_effective_all_points": actual_bound["all_same_count_and_effective_points"],
            "interpretation": "For this exact completed pair, equal .009 counts and equal Fluid/Bound/All POINTS payloads support observed initial point/support equivalence. This is a producer-output observation, not a generic setshapemode theorem.",
            "default_grid_owner_envelope": parsed["default"]["fluid_midpoint_cell_envelope_vs_owner"],
            "actual_dp009_owner_envelope": parsed["actual"]["fluid_midpoint_cell_envelope_vs_owner"],
            "bound_dp009_owner_envelope": parsed["bound"]["fluid_midpoint_cell_envelope_vs_owner"],
            "sample_mass_is_not_continuum_geometry_proof": True,
            "mass_rescale": False,
        },
        "three_grid_source_equivalence": {
            "status": "NOT_READY_THREE_GRID_SPATIAL_REFERENCE",
            "observed_resolution_levels": sorted({parsed[label]["generated_xml"]["definition"]["dp_m"] for label in parsed}),
            "reason": "default is dp=.010; actual and bound are byte-identical mode outputs at the same dp=.009. The mode pair is not a third spatial resolution.",
            "required_next_condition": "A separately source-bound dp rung must preserve the owner continuous geometry/control contract and pass the same point/support and whole-initial-mass audit without particle mass rescaling.",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "frozen_error_policy": {
            "whole_initial_fluid_mass_target_pct": 1.0,
            "hard_upper_pct": 2.0,
            "position_pct_L": 2.0,
            "velocity_or_ke_pct_nonzero_scale": 5.0,
            "time_event_pct_T": 1.0,
            "time_output_each_fraction_of_task_tolerance": 0.25,
            "event_time_T": "UNKNOWN; not inferred from output window",
        },
    }
    atomic_json(output, report)
    return report


def all_input_paths() -> list[Path]:
    paths: list[Path] = [Path(__file__), OWNER, BINDING, CURRENT_SOURCE_DEF, CURRENT_SOURCE_XML, CURRENT_SOURCE_RECEIPT, V8_RUNNER, V8_STRICT, V8_RUNTIME, PYTHON]
    paths.extend(spec["source_def"] for spec in CASES.values())
    for spec in CASES.values():
        root = Path(spec["root"])
        paths.extend(root / name for name in FILE_NAMES)
    unique = list(dict.fromkeys(path.expanduser().resolve() for path in paths))
    if any(path.suffix.lower() in {".bi4", ".h5", ".hdf5"} for path in unique):
        raise ValueError("audit input closure must not contain BI4/H5")
    return unique


def build_request(output: Path = REQUEST_PATH) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refuse to overwrite immutable request: {output}")
    input_paths = [regular(path, "audit input") for path in all_input_paths()]
    records = {str(path): file_record(path, "audit input") for path in input_paths}
    geometry_read_bytes = sum(record["bytes"] for path, record in records.items() if path.endswith(".vtk"))
    output_root = DATA_ROOT / "families/F1" / CASE_ID / ATTEMPT_ID
    request = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F1",
        "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "command": [str(PYTHON), str(Path(__file__).resolve()), "--audit", "--output", "{attempt_root}/f1_s1_effective_point_support_geometry_audit_v1.json"],
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": list(records),
        "input_hashes": {path: record["sha256"] for path, record in records.items()},
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "estimated_input_read_bytes": sum(record["bytes"] for record in records.values()),
        "estimated_geometry_read_bytes": geometry_read_bytes,
        "estimated_native_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "hdf5_read": False,
        "bi4_read": False,
        "deferred_input_files": [],
        "source_binding": {
            "schema": "ds02.stage2.f1-s1.effective-point-support-geometry-binding.v1",
            "owner": file_record(OWNER, "F1 owner"),
            "canonical_binding": file_record(BINDING, "F1 canonical binding"),
            "continuous_geometry_authority": {
                "low_m": OWNER_LOW,
                "size_m": OWNER_SIZE,
                "upper_m": OWNER_UPPER,
                "density_kg_m3": OWNER_DENSITY_KG_M3,
                "mass_kg": OWNER_MASS_KG,
                "source": "CURRENT336 owner/physical-binding; not inferred from particle samples",
            },
            "cases": {
                label: {
                    "case_id": spec["case_id"],
                    "attempt_id": spec["attempt_id"],
                    "terminal_root": str(Path(spec["root"]).resolve()),
                    "receipt": file_record(Path(spec["root"]) / "execution-receipt.json", f"{label} receipt"),
                    "source_def": file_record(spec["source_def"], f"{label} source Def"),
                    "generated_products": {name: file_record(Path(spec["root"]) / name, f"{label} {name}") for name in FILE_NAMES},
                }
                for label, spec in CASES.items()
            },
            "same_count_requires_point_payload_digest": True,
            "three_grid_rule": "actual/bound same dp=.009 mode outputs cannot count as a third resolution",
        },
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "path": "{attempt_root}/f1_s1_effective_point_support_geometry_audit_v1.json",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(V8_RUNNER),
            "strict_guard": str(V8_STRICT),
            "runtime": str(V8_RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "gpu_uuid": "none",
            "solver_launch": "forbidden",
            "gencase_launch": "forbidden",
            "hdf5_read": "forbidden",
            "bi4_read": "forbidden",
            "parent_v8_review_required": True,
        },
        "output_root": str(output_root),
        "qualification_stage": "stage2_f1_s1_effective_point_support_geometry_audit_v1_pending_parent_v8_dispatch",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(output, request)
    return request


def self_test() -> dict[str, Any]:
    """Test equal-count/different-point rejection without real data reads."""

    def vtk_bytes(points: list[tuple[float, float, float]]) -> bytes:
        header = b"# vtk DataFile Version 3.0\nsynthetic\nBINARY\nDATASET POLYDATA\n"
        header += f"POINTS {len(points)} float\n".encode("ascii")
        payload = struct.pack(f">{3 * len(points)}f", *(value for point in points for value in point))
        return header + payload

    with tempfile.TemporaryDirectory(prefix="ds02-f1-s1-effective-geometry-selftest-") as tmp:
        root = Path(tmp)
        xml_path = root / "synthetic.xml"
        xml_path.write_text(
            "<case><geometry><definition dp='0.1'><pointref x='0.05' y='0.05' z='0.05'/></definition>"
            "<commands><mainlist><setmkfluid mk='1'/><drawbox><boxfill>solid</boxfill>"
            "<point x='0' y='0' z='0'/><size x='0.2' y='0.2' z='0.2'/></drawbox>"
            "<setmkbound mk='0'/></mainlist></commands></geometry>"
            "<particles><fluid count='2'/></particles><constants><massfluid value='1'/></constants><rhop0 value='1000'/></case>",
            encoding="utf-8",
        )
        xml = parse_xml(xml_path, "synthetic XML")
        same = root / "same.vtk"
        different = root / "different.vtk"
        same.write_bytes(vtk_bytes([(0.05, 0.05, 0.05), (0.15, 0.05, 0.05)]))
        different.write_bytes(vtk_bytes([(0.05, 0.05, 0.05), (0.15, 0.15, 0.05)]))
        left = parse_vtk(same, xml, "same", fluid=True)
        right = parse_vtk(different, xml, "different", fluid=True)
        if left["point_count_header"] != right["point_count_header"] or left["points_payload_sha256"] == right["points_payload_sha256"]:
            raise AssertionError("self-test did not create equal-count different-point counterexample")
        truncated = root / "truncated.vtk"
        truncated.write_bytes(same.read_bytes()[:-1])
        try:
            parse_vtk(truncated, xml, "truncated", fluid=True)
        except ValueError:
            pass
        else:
            raise AssertionError("truncated VTK was accepted")
    return {
        "status": "PASS",
        "equal_count_different_point_payload_rejected": True,
        "truncated_point_payload_rejected": True,
        "bi4_read": False,
        "hdf5_read": False,
        "solver_launch": False,
        "gencase_launch": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    selected = [args.self_test, args.audit, args.build_request]
    if sum(selected) != 1:
        parser.error("choose exactly one of --self-test, --audit, --build-request")
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    if args.build_request:
        request = build_request()
        print(json.dumps({"status": "PREPARED", "path": str(REQUEST_PATH), "input_count": len(request["input_files"]), "estimated_geometry_read_bytes": request["estimated_geometry_read_bytes"]}, indent=2))
        return 0
    report = audit(args.output)
    print(json.dumps({"status": report["status"], "output": str(args.output.resolve()), "actual_bound_same_effective_points": report["effective_point_support_conclusion"]["actual_bound_same_effective_all_points"], "three_grid_status": report["three_grid_source_equivalence"]["status"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

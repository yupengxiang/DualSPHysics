#!/usr/bin/env python3
"""Prepare and audit an owner-centred F1-S1 spatial rung.

The completed ``.010``, ``.009`` and ``.008`` products share the owner
drawbox text, but their point reference and lattice support are different.
This module records that distinction from the actual generated VTK points and
prepares one commensurate ``.005`` GenCase-only preflight.  The ``.005``
candidate changes only ``definition@dp`` and ``definition/pointref`` from the
immutable CURRENT Def: ``dp=.01, pointref=.005`` becomes
``dp=.005, pointref=.0025``.  The owner reservoir, drawboxes, obstacle,
controls, and particle mass policy remain unchanged.

``--audit`` reads only the three completed generated XML/VTK/receipt products
and small owner/source files.  It does not read BI4/Part/HDF5 data, invoke a
decoder, or start a solver.  It can optionally include the later ``.005``
product when that exact parent-guarded GenCase attempt exists.

``--prepare-input`` creates the immutable ``.005`` Def, ``--candidate-request``
registers its bounded GenCase preflight, and ``--audit-request`` registers the
small VTK support audit.  Requests are additive and refuse overwrite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import tempfile
from typing import Any
import xml.etree.ElementTree as ET


SCHEMA = "ds02.stage2.f1-s1.owner-centred-support.v1"
REPORT_SCHEMA = "ds02.stage2.f1-s1.owner-centred-support-report.v1"
REQUEST_SCHEMA = "ds02.request.v1"

REPO = Path(__file__).resolve().parents[5]
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
GENCASE = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/GenCase_linux64"
)
RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"

OWNER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/"
    "handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/"
    "ecc_coarse/owner.json"
)
OWNER_BINDING = OWNER.parent.parent / "ecc-physical-binding.json"
CURRENT_ROOT = DATA_ROOT / (
    "families/F1/F1_FALLBACK_ECC_COARSE/"
    "root-fallback-ecc-coarse-actual-gencase-027"
)
CURRENT_DEF = CURRENT_ROOT / "prepared/F1_FALLBACK_ECC_COARSE_Def.xml"
CURRENT_XML = CURRENT_ROOT / "prepared/F1_FALLBACK_ECC_COARSE.xml"
CURRENT_RECEIPT = CURRENT_ROOT / "execution-receipt.json"
GEOMETRY_EVIDENCE = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f1_s1_geometry_semantics_source_evidence_v1.json"
)

INPUT_ROOT = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f1_s1_owner_centered_support_inputs_v1"
)
CANDIDATE_CASE_ID = "F1_S1_OWNER_CENTERED_DP0p005000"
CANDIDATE_ATTEMPT_ID = "f1-s1-owner-centered-dp0p005000-v1-root-001"
CANDIDATE_DEF = INPUT_ROOT / f"{CANDIDATE_CASE_ID}_Def.xml"
CANDIDATE_OUTPUT_ROOT = DATA_ROOT / "families/F1" / CANDIDATE_CASE_ID / CANDIDATE_ATTEMPT_ID

AUDIT_CASE_ID = "F1_S1_OWNER_CENTERED_SUPPORT_AUDIT_V1"
AUDIT_ATTEMPT_ID = "f1-s1-owner-centered-support-audit-v1-root-001"
AUDIT_REQUEST_DIR = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "stage2-f1-s1-owner-centered-support-audit-v1"
)
AUDIT_REQUEST = AUDIT_REQUEST_DIR / "f1_s1_owner_centered_support_audit_v1.json"
AUDIT_OUTPUT = DATA_ROOT / "families/F1" / AUDIT_CASE_ID / AUDIT_ATTEMPT_ID / "report/f1_s1_owner_centered_support_v1.json"

CANDIDATE_REQUEST_DIR = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "stage2-f1-s1-owner-centered-dp005-gencase-v1"
)
CANDIDATE_REQUEST = CANDIDATE_REQUEST_DIR / "f1_s1_owner_centered_dp005_gencase_v1.json"

OWNER_LOW = [0.0, 0.0, 0.0]
OWNER_SIZE = [0.4, 0.67, 0.15]
OWNER_UPPER = [OWNER_LOW[i] + OWNER_SIZE[i] for i in range(3)]
OWNER_DENSITY = 1000.0
OWNER_MASS = 40.2
SOURCE_DP = 0.01
CANDIDATE_DP = 0.005
SOURCE_POINTREF = [0.005, 0.005, 0.005]
CANDIDATE_POINTREF = [0.0025, 0.0025, 0.0025]
SUPPORT_TOL = 3.0e-6
VTK_POINTS_RE = re.compile(rb"POINTS\s+(\d+)\s+float\s*\r?\n")


CASES: dict[str, dict[str, Any]] = {
    "dp010": {
        "case_id": "F1_FALLBACK_ECC_COARSE",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "dp_m": 0.01,
        "source_def": CURRENT_DEF,
        "generated_xml": CURRENT_ROOT / "prepared/F1_FALLBACK_ECC_COARSE.xml",
        "receipt": CURRENT_RECEIPT,
        "fluid_vtk": CURRENT_ROOT / "prepared/F1_FALLBACK_ECC_COARSE_Fluid.vtk",
        "bound_vtk": CURRENT_ROOT / "prepared/F1_FALLBACK_ECC_COARSE_Bound.vtk",
        "all_vtk": CURRENT_ROOT / "prepared/F1_FALLBACK_ECC_COARSE_All.vtk",
        "resolution_role": "owner_current_original",
    },
    "dp009": {
        "case_id": "F1_S1_SPATIAL_MODE_ACTUAL_DP0p009000",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "dp_m": 0.009,
        "source_def": REPO / (
            "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
            "stage2_f1_s1_geometry_mode_probe_inputs_v2/F1_S1/dp0p009000/"
            "setshapemode_actual/F1_S1_DP009_MODE_ACTUAL_Def.xml"
        ),
        "generated_xml": DATA_ROOT / (
            "families/F1/F1_S1_SPATIAL_MODE_ACTUAL_DP0p009000/"
            "f1-s1-spatial-mode-actual-dp0p009000-v2-root-001-root-forward-001/generated.xml"
        ),
        "receipt": DATA_ROOT / (
            "families/F1/F1_S1_SPATIAL_MODE_ACTUAL_DP0p009000/"
            "f1-s1-spatial-mode-actual-dp0p009000-v2-root-001-root-forward-001/execution-receipt.json"
        ),
        "fluid_vtk": DATA_ROOT / (
            "families/F1/F1_S1_SPATIAL_MODE_ACTUAL_DP0p009000/"
            "f1-s1-spatial-mode-actual-dp0p009000-v2-root-001-root-forward-001/generated_Fluid.vtk"
        ),
        "bound_vtk": DATA_ROOT / (
            "families/F1/F1_S1_SPATIAL_MODE_ACTUAL_DP0p009000/"
            "f1-s1-spatial-mode-actual-dp0p009000-v2-root-001-root-forward-001/generated_Bound.vtk"
        ),
        "all_vtk": DATA_ROOT / (
            "families/F1/F1_S1_SPATIAL_MODE_ACTUAL_DP0p009000/"
            "f1-s1-spatial-mode-actual-dp0p009000-v2-root-001-root-forward-001/generated_All.vtk"
        ),
        "resolution_role": "completed_middle_mode_actual",
    },
    "dp008": {
        "case_id": "F1_S1_OWNER_THIRD_DP0p008000",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "dp_m": 0.008,
        "source_def": REPO / (
            "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
            "stage2_f1_s1_owner_third_dp_rung_inputs_v1/"
            "F1_S1_OWNER_THIRD_DP0p008000_Def.xml"
        ),
        "generated_xml": DATA_ROOT / (
            "families/F1/F1_S1_OWNER_THIRD_DP0p008000/"
            "f1-s1-owner-third-dp0p008000-v1-root-001-root-forward-001/generated.xml"
        ),
        "receipt": DATA_ROOT / (
            "families/F1/F1_S1_OWNER_THIRD_DP0p008000/"
            "f1-s1-owner-third-dp0p008000-v1-root-001-root-forward-001/execution-receipt.json"
        ),
        "fluid_vtk": DATA_ROOT / (
            "families/F1/F1_S1_OWNER_THIRD_DP0p008000/"
            "f1-s1-owner-third-dp0p008000-v1-root-001-root-forward-001/generated_Fluid.vtk"
        ),
        "bound_vtk": DATA_ROOT / (
            "families/F1/F1_S1_OWNER_THIRD_DP0p008000/"
            "f1-s1-owner-third-dp0p008000-v1-root-001-root-forward-001/generated_Bound.vtk"
        ),
        "all_vtk": DATA_ROOT / (
            "families/F1/F1_S1_OWNER_THIRD_DP0p008000/"
            "f1-s1-owner-third-dp0p008000-v1-root-001-root-forward-001/generated_All.vtk"
        ),
        "resolution_role": "completed_third_noncentred_probe",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str = "file") -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be an existing regular file: {path}")
    return path


def record(path: Path, label: str = "file") -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def atomic_bytes(path: Path, value: bytes) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse overwrite immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


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


def parse_definition(path: Path, label: str) -> dict[str, Any]:
    root = ET.parse(regular(path, label)).getroot()
    definition = next((n for n in root.iter() if local_name(n.tag) == "definition"), None)
    if definition is None:
        raise ValueError(f"{label} has no definition")
    pointref = vector(next((n for n in definition if local_name(n.tag) == "pointref"), None), f"{label}.pointref")
    dp = finite(definition.get("dp"), f"{label}.dp")
    shapes = [(n.text or "").strip() for n in root.iter() if local_name(n.tag) == "setshapemode"]
    particles = next((n for n in root.iter() if local_name(n.tag) == "particles"), None)
    fluids = [n for n in list(particles or []) if local_name(n.tag) == "fluid"]
    if not fluids:
        raise ValueError(f"{label} has no generated fluid blocks")
    counts = [int(n.get("count")) for n in fluids if n.get("count") is not None]
    if len(counts) != len(fluids):
        raise ValueError(f"{label} has a fluid block without count")
    constants = next((n for n in root.iter() if local_name(n.tag) == "constants"), None)
    mass_node = next((n for n in list(constants or []) if local_name(n.tag) == "massfluid"), None)
    massfluid = finite(mass_node.get("value"), f"{label}.massfluid") if mass_node is not None else None
    active_mk: str | None = None
    fluid_boxes: list[dict[str, Any]] = []
    for node in root.iter():
        tag = local_name(node.tag)
        if tag == "setmkfluid":
            active_mk = node.get("mk")
        elif tag in {"setmkbound", "setmkvoid"}:
            active_mk = None
        elif tag == "drawbox" and active_mk is not None:
            fill = next((n for n in node if local_name(n.tag) == "boxfill"), None)
            if fill is None or (fill.text or "").strip().lower() != "solid":
                continue
            point = vector(next((n for n in node if local_name(n.tag) == "point"), None), f"{label}.fluid.point")
            size = vector(next((n for n in node if local_name(n.tag) == "size"), None), f"{label}.fluid.size")
            fluid_boxes.append({
                "mkfluid_relative": active_mk,
                "comment": node.get("cmt"),
                "point_m": point,
                "size_m": size,
                "upper_m": [point[i] + size[i] for i in range(3)],
                "volume_m3": math.prod(size),
            })
    if not fluid_boxes:
        raise ValueError(f"{label} has no fluid drawbox")
    return {
        "file": record(path, label),
        "case_app": root.get("app"),
        "definition": {"dp_m": dp, "pointref_m": pointref},
        "setshapemode": shapes,
        "fluid_count_from_xml": sum(counts),
        "fluid_block_counts": counts,
        "massfluid_kg": massfluid,
        "fluid_drawboxes": fluid_boxes,
        "fluid_drawbox_last": fluid_boxes[-1],
    }


def parse_receipt(spec: dict[str, Any], label: str) -> dict[str, Any]:
    receipt = load_json(spec["receipt"], f"{label} receipt")
    request = receipt.get("request", {})
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"{label} is not a successful GenCase receipt")
    if request.get("family_id") not in (None, "F1"):
        raise ValueError(f"{label} family identity mismatch")
    if request.get("sentinel_id") not in (None, "F1-S1"):
        raise ValueError(f"{label} sentinel identity mismatch")
    if request.get("physical_case_id") not in (None, "F1_ECC_THICK_DBC_LOWER_HEAD_V1"):
        raise ValueError(f"{label} physical identity mismatch")
    if request.get("case_id") != spec["case_id"]:
        raise ValueError(f"{label} case identity mismatch")
    generated_parent = Path(spec["generated_xml"]).expanduser().resolve().parent
    expected_output_roots = {generated_parent}
    # The CURRENT owner product stores generated XML/VTK below a ``prepared``
    # subdirectory while its receipt output_root is the attempt directory.
    if generated_parent.name == "prepared":
        expected_output_roots.add(generated_parent.parent)
    if Path(str(receipt.get("output_root", ""))).expanduser().resolve() not in expected_output_roots:
        raise ValueError(f"{label} receipt output root differs from generated products")
    launch = receipt.get("input_hashes_at_launch")
    finish = receipt.get("input_hashes_after_run")
    if launch is not None and finish is not None and launch != finish:
        raise ValueError(f"{label} source input hashes changed")
    return {
        "record": record(spec["receipt"], f"{label} receipt"),
        "status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "request_sha256": receipt.get("request_sha256"),
        "case_id": request.get("case_id"),
        "attempt_id": request.get("attempt_id"),
        "source_hashes_stable": launch == finish if launch is not None and finish is not None else None,
        "bytes": receipt.get("bytes"),
        "cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "input_def_path": next((p for p in request.get("input_files", []) if str(p).endswith(".xml")), None),
    }


def grouped(values: list[float], tol: float = 2.0e-6) -> list[float]:
    result: list[float] = []
    for value in sorted(values):
        if not result or abs(value - result[-1]) > tol:
            result.append(value)
    return result


def parse_vtk(path: Path, dp: float, pointref: list[float], label: str) -> dict[str, Any]:
    raw = regular(path, label).read_bytes()
    match = VTK_POINTS_RE.search(raw)
    if match is None:
        raise ValueError(f"{label} lacks binary POINTS header")
    count = int(match.group(1))
    offset = match.end()
    size = 12 * count
    if len(raw) < offset + size:
        raise ValueError(f"{label} POINTS payload is truncated")
    payload = raw[offset:offset + size]
    values = struct.unpack(f">{3 * count}f", payload)
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"{label} contains NaN or Inf POINTS")
    axes = [list(values[i::3]) for i in range(3)]
    axis_records: list[dict[str, Any]] = []
    for axis, values_axis in enumerate(axes):
        unique = grouped(values_axis)
        if not unique:
            raise ValueError(f"{label} axis {axis} is empty")
        indices = [(value - pointref[axis]) / dp for value in unique]
        residual = max(abs(index - round(index)) for index in indices)
        axis_records.append({
            "axis": "xyz"[axis],
            "unique_count": len(unique),
            "first_m": unique[0],
            "last_m": unique[-1],
            "step_min_m": min((b - a for a, b in zip(unique, unique[1:])), default=None),
            "step_max_m": max((b - a for a, b in zip(unique, unique[1:])), default=None),
            "pointref_index_first": indices[0],
            "pointref_index_last": indices[-1],
            "pointref_index_max_integer_residual": residual,
            "support_low_m": unique[0] - dp / 2.0,
            "support_high_m": unique[-1] + dp / 2.0,
        })
    return {
        "file": record(path, label),
        "point_count_header": count,
        "points_payload_sha256": hashlib.sha256(payload).hexdigest(),
        "axis": axis_records,
        "axis_count_product": math.prod(item["unique_count"] for item in axis_records),
        "support_envelope_m": {
            "lower_m": [item["support_low_m"] for item in axis_records],
            "upper_m": [item["support_high_m"] for item in axis_records],
        },
        "all_axis_indices_integer_within_2e-5": all(item["pointref_index_max_integer_residual"] <= 2e-5 for item in axis_records),
    }


def support_comparison(vtk: dict[str, Any], pointref: list[float], dp: float) -> dict[str, Any]:
    lower = vtk["support_envelope_m"]["lower_m"]
    upper = vtk["support_envelope_m"]["upper_m"]
    lower_error = [lower[i] - OWNER_LOW[i] for i in range(3)]
    upper_error = [upper[i] - OWNER_UPPER[i] for i in range(3)]
    max_error = max([abs(value) for value in lower_error + upper_error], default=math.inf)
    pointref_dp_half = [abs(pointref[i] - dp / 2.0) <= SUPPORT_TOL for i in range(3)]
    return {
        "owner_lower_m": OWNER_LOW,
        "owner_upper_m": OWNER_UPPER,
        "observed_lower_m": lower,
        "observed_upper_m": upper,
        "lower_residual_m": lower_error,
        "upper_residual_m": upper_error,
        "max_abs_support_residual_m": max_error,
        "pointref_m": pointref,
        "dp_over_2_m": [dp / 2.0] * 3,
        "pointref_equals_dp_over_2": all(pointref_dp_half),
        "matches_owner_within_tolerance": max_error <= SUPPORT_TOL,
        "status": "PASS_OWNER_SUPPORT_ENVELOPE" if max_error <= SUPPORT_TOL else "FAIL_SUPPORT_ENVELOPE_DIFFERS_FROM_OWNER",
    }


def audit_case(label: str, spec: dict[str, Any]) -> dict[str, Any]:
    source = parse_definition(spec["source_def"], f"{label} source Def")
    generated = parse_definition(spec["generated_xml"], f"{label} generated XML")
    receipt = parse_receipt(spec, label)
    if abs(source["definition"]["dp_m"] - spec["dp_m"]) > 1e-12 or abs(generated["definition"]["dp_m"] - spec["dp_m"]) > 1e-12:
        raise ValueError(f"{label} dp identity mismatch")
    if source["definition"]["pointref_m"] != generated["definition"]["pointref_m"]:
        raise ValueError(f"{label} source/generated pointref mismatch")
    if generated["fluid_count_from_xml"] <= 0 or generated["massfluid_kg"] is None:
        raise ValueError(f"{label} generated fluid mass/count missing")
    fluid = parse_vtk(spec["fluid_vtk"], spec["dp_m"], generated["definition"]["pointref_m"], f"{label} Fluid.vtk")
    bound = parse_vtk(spec["bound_vtk"], spec["dp_m"], generated["definition"]["pointref_m"], f"{label} Bound.vtk")
    all_points = parse_vtk(spec["all_vtk"], spec["dp_m"], generated["definition"]["pointref_m"], f"{label} All.vtk")
    if fluid["point_count_header"] != generated["fluid_count_from_xml"]:
        raise ValueError(f"{label} Fluid.vtk/XML count mismatch")
    if all_points["point_count_header"] != fluid["point_count_header"] + bound["point_count_header"]:
        raise ValueError(f"{label} All.vtk != Fluid.vtk + Bound.vtk")
    sample_mass = fluid["point_count_header"] * generated["massfluid_kg"]
    mass_error = (sample_mass - OWNER_MASS) / OWNER_MASS
    return {
        "label": label,
        "case_id": spec["case_id"],
        "physical_case_id": spec["physical_case_id"],
        "resolution_role": spec["resolution_role"],
        "dp_m": spec["dp_m"],
        "source_def": source,
        "generated_xml": generated,
        "receipt": receipt,
        "fluid": fluid,
        "bound": bound,
        "all": all_points,
        "fluid_count": fluid["point_count_header"],
        "bound_count": bound["point_count_header"],
        "all_count": all_points["point_count_header"],
        "sample_mass_kg": sample_mass,
        "sample_mass_error_fraction_vs_owner": mass_error,
        "sample_mass_error_percent_vs_owner": 100.0 * mass_error,
        "mass_gate": "PREFERRED_WITHIN_1_PERCENT" if abs(mass_error) <= 0.01 else "MARGINAL_WITHIN_2_PERCENT" if abs(mass_error) <= 0.02 else "HARD_FAIL_ABOVE_2_PERCENT",
        "support_comparison": support_comparison(fluid, generated["definition"]["pointref_m"], spec["dp_m"]),
    }


def owner_contract() -> dict[str, Any]:
    owner = load_json(OWNER, "F1 owner")
    binding = load_json(OWNER_BINDING, "F1 physical binding")
    physical = owner.get("physical_binding", {})
    geometry = physical.get("geometry", {}).get("fluid_reservoir")
    initial = physical.get("initial_state", {}).get("source_regions", {}).get("fluid")
    if geometry != initial:
        raise ValueError("owner reservoir and initial fluid source differ")
    low = [float(v) for v in geometry["low_m"]]
    size = [float(v) for v in geometry["size_m"]]
    density = float(physical["density_kg_m3"])
    mass = float(physical["initial_state"]["continuum_mass_by_source_kg"]["fluid"])
    if low != OWNER_LOW or size != OWNER_SIZE or density != OWNER_DENSITY or abs(mass - OWNER_MASS) > 1e-12:
        raise ValueError("owner continuous geometry contract changed")
    if binding.get("physical_condition_sha256") != owner.get("physical_condition_sha256"):
        raise ValueError("owner/binding condition SHA mismatch")
    return {
        "owner_file": record(OWNER, "F1 owner"),
        "binding_file": record(OWNER_BINDING, "F1 physical binding"),
        "identity": {k: owner.get(k) for k in ("family_id", "case_id", "physical_case_id", "mechanism_id")},
        "physical_condition_sha256": owner.get("physical_condition_sha256"),
        "continuous_fluid_reservoir": {
            "low_m": low,
            "size_m": size,
            "upper_m": OWNER_UPPER,
            "volume_m3": math.prod(size),
            "density_kg_m3": density,
            "mass_kg": mass,
            "mkfluid_relative": geometry.get("mkfluid"),
            "authority": "CURRENT336 owner/physical-binding; never inferred from sample count",
        },
        "mass_policy": physical["initial_state"].get("mass_policy"),
    }


def source_contract() -> dict[str, Any]:
    parsed = {label: parse_definition(spec["source_def"], f"{label} source Def") for label, spec in CASES.items()}
    expected_box_point = [0.005, 0.005, 0.005]
    expected_box_size = [0.39, 0.66, 0.14]
    drawbox_equal = all(
        item["fluid_drawbox_last"]["point_m"] == expected_box_point and item["fluid_drawbox_last"]["size_m"] == expected_box_size
        for item in parsed.values()
    )
    pointrefs = {label: item["definition"]["pointref_m"] for label, item in parsed.items()}
    dps = {label: item["definition"]["dp_m"] for label, item in parsed.items()}
    shape_modes = {label: item["setshapemode"] for label, item in parsed.items()}
    return {
        "source_defs": {label: item["file"] for label, item in parsed.items()},
        "dp_m": dps,
        "pointref_m": pointrefs,
        "setshapemode": shape_modes,
        "continuous_drawbox_contract": {
            "point_m": expected_box_point,
            "size_m": expected_box_size,
            "volume_m3": math.prod(expected_box_size),
            "mass_kg_at_density_1000": math.prod(expected_box_size) * OWNER_DENSITY,
            "same_across_sources": drawbox_equal,
            "interpretation": "XML command primitive; owner continuous reservoir remains authoritative",
        },
        "pointref_rule_observed": {
            "dp010_pointref_equals_dp_over_2": all(abs(pointrefs["dp010"][i] - dps["dp010"] / 2.0) <= SUPPORT_TOL for i in range(3)),
            "dp009_pointref_equals_dp_over_2": all(abs(pointrefs["dp009"][i] - dps["dp009"] / 2.0) <= SUPPORT_TOL for i in range(3)),
            "dp008_pointref_equals_dp_over_2": all(abs(pointrefs["dp008"][i] - dps["dp008"] / 2.0) <= SUPPORT_TOL for i in range(3)),
            "interpretation": "pointref is explicit source input; generic setshapemode crop/tie-breaking remains UNKNOWN",
        },
        "owner_centered_candidate_rule": {
            "definition_dp_m": CANDIDATE_DP,
            "pointref_m": CANDIDATE_POINTREF,
            "pointref_is_dp_over_2": True,
            "expected_axis_counts_if_owner_boundary_cells_are_included": [80, 134, 30],
            "expected_fluid_count": 80 * 134 * 30,
            "expected_quadrature_mass_kg": 80 * 134 * 30 * CANDIDATE_DP ** 3 * OWNER_DENSITY,
            "status": "PROPOSAL_REQUIRES_ACTUAL_GENCASE_SUPPORT_AUDIT",
        },
    }


def derive_candidate() -> dict[str, Any]:
    source = regular(CURRENT_DEF, "CURRENT F1 Def").read_text(encoding="utf-8")
    definitions = list(re.finditer(r"<definition\b[^>]*>", source))
    if len(definitions) != 1:
        raise ValueError("CURRENT Def must contain one definition")
    tag = definitions[0].group(0)
    dp_match = re.search(r'\bdp="([^"]+)"', tag)
    if dp_match is None or dp_match.group(1) != "0.01":
        raise ValueError("CURRENT Def dp is not 0.01")
    pointref_match = re.search(r"<pointref\b[^>]*/>", source)
    if pointref_match is None:
        raise ValueError("CURRENT Def pointref is missing")
    pointref_tag = pointref_match.group(0)
    if any(value not in pointref_tag for value in ('x="0.005"', 'y="0.005"', 'z="0.005"')):
        raise ValueError("CURRENT Def pointref is not the expected .005 reference")
    new_tag = tag[:dp_match.start(1)] + "0.005" + tag[dp_match.end(1):]
    derived = source[:definitions[0].start()] + new_tag + source[definitions[0].end():]
    new_pointref = '<pointref x="0.0025" y="0.0025" z="0.0025"/>'
    derived, replacements = re.subn(r"<pointref\b[^>]*/>", new_pointref, derived, count=1)
    if replacements != 1 or derived == source:
        raise ValueError("candidate pointref/dp edits were not applied exactly")
    normalized_source = re.sub(r'(<definition\b[^>]*\bdp=")[^"]+(")', r"\1<DP>\2", source, count=1)
    normalized_source = re.sub(r"<pointref\b[^>]*/>", "<pointref x=\"<PX>\" y=\"<PY>\" z=\"<PZ>\"/>", normalized_source, count=1)
    normalized_candidate = re.sub(r'(<definition\b[^>]*\bdp=")[^"]+(")', r"\1<DP>\2", derived, count=1)
    normalized_candidate = re.sub(r"<pointref\b[^>]*/>", "<pointref x=\"<PX>\" y=\"<PY>\" z=\"<PZ>\"/>", normalized_candidate, count=1)
    if normalized_source != normalized_candidate:
        raise ValueError("candidate differs from CURRENT beyond dp and pointref")
    atomic_bytes(CANDIDATE_DEF, derived.encode("utf-8"))
    return {
        "source": record(CURRENT_DEF, "CURRENT F1 Def"),
        "candidate": record(CANDIDATE_DEF, "owner-centred .005 Def"),
        "only_intentional_edits": {
            "definition@dp": [SOURCE_DP, CANDIDATE_DP],
            "definition/pointref": [SOURCE_POINTREF, CANDIDATE_POINTREF],
        },
        "normalized_source_sha256": hashlib.sha256(normalized_source.encode()).hexdigest(),
        "normalized_candidate_sha256": hashlib.sha256(normalized_candidate.encode()).hexdigest(),
        "expected_owner_lattice": {"axis_counts": [80, 134, 30], "fluid_count": 321600, "quadrature_mass_kg": OWNER_MASS},
    }


def input_records(paths: list[Path]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in paths:
        path = regular(path, "request input")
        if path.suffix.lower() in {".bi4", ".h5", ".hdf5"}:
            raise ValueError(f"raw/native input forbidden in this CPU request: {path}")
        result[str(path)] = record(path, "request input")
    return result


def base_request(paths: list[Path], case_id: str, attempt_id: str, output_root: Path, command: list[str], cpu_task_kind: str, launch_commit: str) -> dict[str, Any]:
    records = input_records(list(dict.fromkeys(path.expanduser().resolve() for path in paths)))
    return {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": cpu_task_kind,
        "family_id": "F1",
        "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "command": command,
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": list(records),
        "input_hashes": {path: item["sha256"] for path, item in records.items()},
        "input_records": records,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()),
        "estimated_storage_bytes": 256 * 1024 * 1024 if cpu_task_kind == "gencase" else 64 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "estimated_native_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": cpu_task_kind == "gencase",
        "solver_launch": False,
        "hdf5_read": False,
        "bi4_read": False,
        "deferred_input_files": [],
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(RUNNER),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "launch_commit": launch_commit,
            "cpu_parent_binding": "required",
            "gpu": "none",
            "gpu_uuid_lease": "none",
            "solver_launch": "forbidden",
            "bi4_read": "forbidden",
            "hdf5_read": "forbidden",
            "source_output_protection": "new attempt output only; completed CURRENT products immutable",
        },
        "output_root": str(output_root),
        "output": {"atomic": True, "refuse_overwrite": True},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def build_candidate_request(launch_commit: str) -> dict[str, Any]:
    if CANDIDATE_REQUEST.exists():
        raise FileExistsError(f"refuse overwrite immutable request: {CANDIDATE_REQUEST}")
    if not CANDIDATE_DEF.exists():
        raise FileNotFoundError(f"run --prepare-input first: {CANDIDATE_DEF}")
    paths = [Path(__file__), PYTHON, GENCASE, RUNNER, STRICT, RUNTIME, CURRENT_DEF, CURRENT_XML, CURRENT_RECEIPT, OWNER, OWNER_BINDING, GEOMETRY_EVIDENCE, CANDIDATE_DEF]
    request = base_request(
        paths,
        CANDIDATE_CASE_ID,
        CANDIDATE_ATTEMPT_ID,
        CANDIDATE_OUTPUT_ROOT,
        [str(GENCASE), str(CANDIDATE_DEF.with_suffix("")), "{attempt_root}/generated", "-save:all", "-threads:1"],
        "gencase",
        launch_commit,
    )
    request.update({
        "qualification_stage": "stage2_f1_s1_owner_centered_dp005_gencase_preflight_pending_support_audit",
        "source_binding": {
            "schema": "ds02.stage2.f1-s1.owner-centred-support-binding.v1",
            "continuous_owner": {"low_m": OWNER_LOW, "size_m": OWNER_SIZE, "upper_m": OWNER_UPPER, "density_kg_m3": OWNER_DENSITY, "mass_kg": OWNER_MASS, "authority": "CURRENT336 owner/physical-binding"},
            "source_control": {"source_def": record(CURRENT_DEF, "CURRENT Def"), "candidate_def": record(CANDIDATE_DEF, "candidate Def"), "only_intentional_edits": ["definition@dp 0.01 -> 0.005", "definition/pointref [0.005,0.005,0.005] -> [0.0025,0.0025,0.0025]"], "drawboxes_and_controls_unchanged": True, "setshapemode": "dp | actual | bound"},
            "expected_owner_lattice": {"axis_counts": [80, 134, 30], "fluid_count": 321600, "support_lower_m": OWNER_LOW, "support_upper_m": OWNER_UPPER, "sample_mass_kg": OWNER_MASS, "status": "EXPECTED_ONLY_UNTIL_GENERATED_VTK_AUDIT"},
            "acceptance": {"whole_initial_mass_target_kg": OWNER_MASS, "preferred_absolute_fraction": 0.01, "marginal_absolute_fraction": 0.02, "hard_fail_above_absolute_fraction": 0.02, "support_envelope_must_match_owner_within": SUPPORT_TOL, "no_mass_rescale": True, "no_posthoc_drawbox_or_control_change": True, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
            "generic_setshapemode_boundary_semantics": "UNKNOWN; accept only actual generated lattice/support evidence",
        },
    })
    atomic_json(CANDIDATE_REQUEST, request)
    return request


def audit_input_paths(include_candidate: bool) -> list[Path]:
    paths = [Path(__file__), PYTHON, RUNNER, STRICT, RUNTIME, OWNER, OWNER_BINDING, GEOMETRY_EVIDENCE]
    for spec in CASES.values():
        paths.extend([spec["source_def"], spec["generated_xml"], spec["receipt"], spec["fluid_vtk"], spec["bound_vtk"], spec["all_vtk"]])
    if include_candidate:
        candidate_root = CANDIDATE_OUTPUT_ROOT / "generated"
        paths.extend([CANDIDATE_DEF, candidate_root / "generated.xml", CANDIDATE_ROOT / "execution-receipt.json"])
    return list(dict.fromkeys(path.expanduser().resolve() for path in paths))


def build_audit_request(launch_commit: str) -> dict[str, Any]:
    if AUDIT_REQUEST.exists():
        raise FileExistsError(f"refuse overwrite immutable request: {AUDIT_REQUEST}")
    paths = audit_input_paths(include_candidate=False)
    request = base_request(
        paths,
        AUDIT_CASE_ID,
        AUDIT_ATTEMPT_ID,
        AUDIT_OUTPUT.parent.parent,
        [str(PYTHON), str(Path(__file__).resolve()), "--audit", "--output", "{attempt_root}/report/f1_s1_owner_centered_support_v1.json"],
        "audit",
        launch_commit,
    )
    request.update({
        "qualification_stage": "stage2_f1_s1_owner_centered_support_audit_dp010_dp009_dp008_pending_parent_cpu_guard",
        "source_binding": {
            "owner_contract": record(OWNER, "F1 owner"),
            "physical_binding": record(OWNER_BINDING, "F1 physical binding"),
            "scope": "actual generated XML/Fluid.vtk/Bound.vtk/All.vtk and GenCase receipts for .010/.009/.008; no BI4/H5/solver",
            "three_grid_status": "DP010_OWNER_ALIGNED; DP009_AND_DP008_SUPPORT_MISMATCH_OR_UNKNOWN_UNTIL_AUDIT",
            "candidate_dp005": "separately registered GenCase preflight; this request does not consume its future output",
            "sample_mass_not_continuum_truth": True,
        },
    })
    atomic_json(AUDIT_REQUEST, request)
    return request


def audit(output: Path, include_candidate: bool = False) -> dict[str, Any]:
    owner = owner_contract()
    source = source_contract()
    cases = {label: audit_case(label, spec) for label, spec in CASES.items()}
    candidate_status: dict[str, Any] = {
        "status": "PENDING_PARENT_GUARDED_GENCASE",
        "candidate_def": record(CANDIDATE_DEF, "candidate .005 Def") if CANDIDATE_DEF.exists() else None,
        "expected_pointref_m": CANDIDATE_POINTREF,
        "expected_axis_counts": [80, 134, 30],
        "expected_fluid_count": 321600,
        "expected_sample_mass_kg": OWNER_MASS,
        "actual": None,
    }
    if include_candidate:
        spec = {
            "case_id": CANDIDATE_CASE_ID,
            "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
            "dp_m": CANDIDATE_DP,
            "source_def": CANDIDATE_DEF,
            "generated_xml": CANDIDATE_OUTPUT_ROOT / "generated/generated.xml",
            "receipt": CANDIDATE_OUTPUT_ROOT / "execution-receipt.json",
            "fluid_vtk": CANDIDATE_OUTPUT_ROOT / "generated/generated_Fluid.vtk",
            "bound_vtk": CANDIDATE_OUTPUT_ROOT / "generated/generated_Bound.vtk",
            "all_vtk": CANDIDATE_OUTPUT_ROOT / "generated/generated_All.vtk",
            "resolution_role": "owner_centred_commensurate_candidate",
        }
        candidate_status["actual"] = audit_case("dp005", spec)
        candidate_status["status"] = "AUDITED_OWNER_CENTERED_CANDIDATE"
    owner_support_pass = all(cases[label]["support_comparison"]["matches_owner_within_tolerance"] for label in ("dp010",))
    report = {
        "schema": REPORT_SCHEMA,
        "status": "PASS_OWNER_DP010_ONLY_DP009_DP008_RETAINED_DIAGNOSTIC" if owner_support_pass else "FAIL_OWNER_SUPPORT_AUDIT",
        "generated_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "sentinel_id": "F1-S1",
        "family_id": "F1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "audit_scope": {"bi4_read": False, "hdf5_read": False, "solver_launch": False, "gencase_launch": False, "vtk_scope": "binary POINTS payload only; no native BI4/H5", "source_outputs_immutable": True},
        "source_authority": owner,
        "source_contract": source,
        "completed_cases": cases,
        "candidate_dp005": candidate_status,
        "conclusion": {
            "dp010_owner_support": cases["dp010"]["support_comparison"],
            "dp009_owner_support": cases["dp009"]["support_comparison"],
            "dp008_owner_support": cases["dp008"]["support_comparison"],
            "dp009_and_dp008_are_not_promoted_by_mass_alone": True,
            "same_count_is_not_support_proof": True,
            "three_grid_scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(output, report)
    return report


def self_test() -> dict[str, Any]:
    if abs(math.prod(OWNER_SIZE) * OWNER_DENSITY - OWNER_MASS) > 1e-12:
        raise AssertionError("owner volume/mass contract failed")
    if CANDIDATE_POINTREF != [CANDIDATE_DP / 2.0] * 3:
        raise AssertionError("candidate is not owner-centred by pointref")
    if [round(size / CANDIDATE_DP) for size in OWNER_SIZE] != [80, 134, 30]:
        raise AssertionError("candidate owner lattice counts changed")
    synthetic = {"support_envelope_m": {"lower_m": OWNER_LOW, "upper_m": OWNER_UPPER}}
    passed = support_comparison(synthetic, CANDIDATE_POINTREF, CANDIDATE_DP)
    if not passed["matches_owner_within_tolerance"]:
        raise AssertionError("synthetic owner envelope was rejected")
    wrong = {"support_envelope_m": {"lower_m": [0.0005, 0.0005, 0.0005], "upper_m": [0.3965, 0.6665, 0.1535]}}
    if support_comparison(wrong, SOURCE_POINTREF, 0.009)["matches_owner_within_tolerance"]:
        raise AssertionError("non-centred .009 support was accepted")
    return {"status": "PASS", "checks": ["owner volume/mass contract", "dp005 pointref=dp/2", "commensurate axis counts", "non-centred support counterexample rejected"], "passed": 4, "solver_started": False, "gencase_started": False, "bi4_read": False, "hdf5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare-input", action="store_true")
    parser.add_argument("--candidate-request", action="store_true")
    parser.add_argument("--audit-request", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--include-candidate", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    selected = [args.self_test, args.prepare_input, args.candidate_request, args.audit_request, args.audit]
    if sum(selected) != 1:
        parser.error("choose exactly one operation")
    if args.self_test:
        result = self_test()
    elif args.prepare_input:
        result = derive_candidate()
    elif args.candidate_request:
        if not args.launch_commit:
            parser.error("--candidate-request requires --launch-commit")
        request = build_candidate_request(args.launch_commit)
        result = {"status": "PASS_CANDIDATE_REQUEST_BUILT", "path": str(CANDIDATE_REQUEST), "sha256": sha256(CANDIDATE_REQUEST), "input_count": len(request["input_files"]), "estimated_input_read_bytes": request["estimated_input_read_bytes"]}
    elif args.audit_request:
        if not args.launch_commit:
            parser.error("--audit-request requires --launch-commit")
        request = build_audit_request(args.launch_commit)
        result = {"status": "PASS_AUDIT_REQUEST_BUILT", "path": str(AUDIT_REQUEST), "sha256": sha256(AUDIT_REQUEST), "input_count": len(request["input_files"]), "estimated_input_read_bytes": request["estimated_input_read_bytes"]}
    else:
        if args.output is None:
            parser.error("--audit requires --output")
        result = audit(args.output, include_candidate=args.include_candidate)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

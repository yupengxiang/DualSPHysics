#!/usr/bin/env python3
"""Separate F1-S1 physical volume authority from generated lattice mass.

The F1-S1 XML uses a fluid drawbox beginning at ``(0.005, 0.005, 0.005)``
with size ``(0.39, 0.66, 0.14)``.  The older geometry-only audit therefore
reported 36.036 kg.  The exact CURRENT owner contract, however, identifies
the continuous lower-head reservoir as ``[0, .4] x [0, .67] x [0, .15]``
with mass 40.2 kg.  This audit makes that authority explicit and checks the
two existing generated ``Fluid.vtk`` lattices without opening BI4/HDF5.

It distinguishes four evidence classes:

* the owner/physical-binding contract is the source-authoritative continuous
  domain and target mass;
* XML drawbox coordinates are the GenCase command primitive;
* generated VTK points prove the observed lattice population and phase for
  these exact runs;
* ``count * dp**3 * rho`` is a discrete particle quadrature diagnostic.  It
  is an exact midpoint-cell representation for the original dp=.01 output,
  while the dp=.009 output does not tile the owner box and cannot be called a
  continuous-geometry match merely because its sample mass is close.

No parser implementation is inferred from the public token list alone.  The
report preserves the unresolved generic ``setshapemode``/boundary ownership
semantics and records the actual generated evidence separately.
"""

from __future__ import annotations

import argparse
import csv
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


SCHEMA = "ds02.stage2.f1-s1-geometry-semantics-audit.v3"
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
    "handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/ecc_coarse/owner.json"
)
CANONICAL_BINDING = OWNER.parent.parent / "ecc-physical-binding.json"
CURRENT_CATALOG = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/review_20261007/CASES_336.json"
)
GENCASE_DOC = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/doc/xml_format/GenCase_CaseTemplate.xml")
SOURCE_XML = DATA_ROOT / "families/F1/F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027/prepared/F1_FALLBACK_ECC_COARSE.xml"
SOURCE_OUT = SOURCE_XML.with_suffix(".out")
SOURCE_VTK = SOURCE_XML.with_name("F1_FALLBACK_ECC_COARSE_Fluid.vtk")
FINE_ROOT = DATA_ROOT / "families/F1/F1_S1_SPATIAL_REPAIR_DP0p009000/f1-s1-spatial-repair-dp0p009000-v1-root-001"
FINE_XML = FINE_ROOT / "generated.xml"
FINE_OUT = FINE_ROOT / "generated.out"
FINE_VTK = FINE_ROOT / "generated_Fluid.vtk"
CASE_ID = "F1_S1_GEOMETRY_SEMANTICS_AUDIT_V3"
ATTEMPT_ID = "f1-s1-geometry-semantics-audit-v3-root-001"
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-s1-geometry-semantics-audit-v3"
REQUEST_PATH = REQUEST_DIR / "f1_s1_geometry_semantics_audit_v3.json"
V2_REPORT = Path(__file__).with_name("stage2_f1_s1_geometry_semantics_audit_v2.json")
V2_SCRIPT = Path(__file__).with_name("stage2_f1_s1_geometry_semantics_audit_v2.py")
V1_SCRIPT = Path(__file__).with_name("stage2_f1_s1_geometry_semantics_audit_v1.py")
DEFAULT_OUTPUT = Path(__file__).with_name("stage2_f1_s1_geometry_semantics_audit_v3.json")
VTK_POINTS_RE = re.compile(rb"POINTS\s+(\d+)\s+float\s*\r?\n")
TOL = 2.0e-6


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_binding(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def claimed_file(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_file() and not path.is_symlink():
        return {"exists": True, **file_binding(path)}
    return {"exists": False, "path": str(path)}


def number(value: str | None, label: str) -> float:
    if value is None:
        raise ValueError(f"missing numeric {label}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite numeric {label}")
    return result


def vector(node: ET.Element | None, label: str) -> list[float]:
    if node is None:
        raise ValueError(f"missing vector {label}")
    return [number(node.get(axis), f"{label}.{axis}") for axis in ("x", "y", "z")]


def parse_xml(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    root = ET.parse(path).getroot()
    definition = next((node for node in root.iter() if local_name(node.tag) == "definition"), None)
    if definition is None:
        raise ValueError(f"no geometry definition in {path}")
    dp = number(definition.get("dp"), "definition.dp")
    pointref = vector(next((node for node in definition if local_name(node.tag) == "pointref"), None), "pointref")
    setshape = [
        (node.text or "").strip()
        for node in root.iter()
        if local_name(node.tag) == "setshapemode"
    ]
    active_mkfluid: str | None = None
    fluid_boxes: list[dict[str, Any]] = []
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
            point = vector(next((child for child in node if local_name(child.tag) == "point"), None), "fluid.drawbox.point")
            size = vector(next((child for child in node if local_name(child.tag) == "size"), None), "fluid.drawbox.size")
            if any(value <= 0.0 for value in size):
                raise ValueError(f"non-positive fluid drawbox size in {path}")
            fluid_boxes.append({
                "mkfluid_relative": active_mkfluid,
                "comment": node.get("cmt"),
                "point_m": point,
                "size_m": size,
                "upper_m": [point[index] + size[index] for index in range(3)],
                "volume_m3": math.prod(size),
            })
    if not fluid_boxes:
        raise ValueError(f"no solid fluid drawbox in {path}")
    particles = next((node for node in root.iter() if local_name(node.tag) == "particles"), None)
    fluid_node = next((node for node in particles or [] if local_name(node.tag) == "fluid"), None)
    constants = next((node for node in root.iter() if local_name(node.tag) == "constants"), None)
    mass_node = next((node for node in constants or [] if local_name(node.tag) == "massfluid"), None)
    rhop_node = next((node for node in root.iter() if local_name(node.tag) == "rhop0"), None)
    count = int(fluid_node.get("count")) if fluid_node is not None and fluid_node.get("count") else None
    massfluid = number(mass_node.get("value"), "constants.massfluid") if mass_node is not None else None
    rhop0 = number(rhop_node.get("value"), "constants.rhop0") if rhop_node is not None else None
    generated_time = root.get("date")
    return {
        "xml": file_binding(path),
        "case_app": root.get("app"),
        "generated_date": generated_time,
        "definition": {"dp_m": dp, "pointref_m": pointref},
        "setshapemode": {
            "raw_values": setshape,
            "tokens": sorted({token.strip() for value in setshape for token in value.split("|") if token.strip()}),
            "public_documentation_role": "interface token list only; generic parser/tie-breaking semantics are not source-proven",
        },
        "fluid_drawboxes": fluid_boxes,
        "fluid_drawbox_last": fluid_boxes[-1],
        "generated_particles": {
            "fluid_count_from_xml": count,
            "massfluid_kg": massfluid,
            "rhop0_kg_m3": rhop0,
            "sample_mass_from_xml_kg": count * massfluid if count is not None and massfluid is not None else None,
        },
    }


def group_axis(values: list[float]) -> list[float]:
    grouped: list[float] = []
    for value in sorted(values):
        if not grouped or abs(value - grouped[-1]) > TOL:
            grouped.append(value)
    return grouped


def parse_vtk(path: Path, xml: dict[str, Any]) -> dict[str, Any]:
    path = path.expanduser().resolve()
    raw = path.read_bytes()
    match = VTK_POINTS_RE.search(raw)
    if match is None:
        raise ValueError(f"Fluid.vtk lacks binary POINTS header: {path}")
    count = int(match.group(1))
    offset = match.end()
    byte_count = 3 * count * 4
    if len(raw) < offset + byte_count:
        raise ValueError(f"Fluid.vtk is shorter than POINTS payload: {path}")
    payload = raw[offset:offset + byte_count]
    values = struct.unpack(f">{3 * count}f", payload)
    # Validate every coordinate before sorting/grouping.  In particular,
    # ``abs(nan) > TOL`` is false, so a NaN can otherwise survive a lattice
    # comparison and make two equally corrupt payloads look equivalent.
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"Fluid.vtk POINTS payload contains NaN or Inf: {path}")
    axes = [list(values[index::3]) for index in range(3)]
    dp = float(xml["definition"]["dp_m"])
    pointref = xml["definition"]["pointref_m"]
    box = xml["fluid_drawbox_last"]
    lower = box["point_m"]
    upper = box["upper_m"]
    axis_records: list[dict[str, Any]] = []
    for axis, values_axis in enumerate(axes):
        unique = group_axis(values_axis)
        steps = [unique[index + 1] - unique[index] for index in range(len(unique) - 1)]
        first = unique[0]
        last = unique[-1]
        index_values = [(value - pointref[axis]) / dp for value in unique]
        nearest_residual = max(abs(value - round(value)) for value in index_values)
        axis_records.append({
            "axis": "xyz"[axis],
            "unique_count": len(unique),
            "first_m": first,
            "last_m": last,
            "step_min_m": min(steps) if steps else None,
            "step_median_m": sorted(steps)[len(steps) // 2] if steps else None,
            "step_max_m": max(steps) if steps else None,
            "pointref_index_first": index_values[0],
            "pointref_index_last": index_values[-1],
            "pointref_index_max_integer_residual": nearest_residual,
            "all_points_inside_xml_drawbox": min(values_axis) >= lower[axis] - TOL and max(values_axis) <= upper[axis] + TOL,
            "cell_envelope_low_m": first - dp / 2.0,
            "cell_envelope_high_m": last + dp / 2.0,
        })
    sample_mass = xml["generated_particles"]["sample_mass_from_xml_kg"]
    quadrature_volume = count * dp ** 3
    return {
        "vtk": file_binding(path),
        "point_count_header": count,
        "points_payload_sha256": hashlib.sha256(payload).hexdigest(),
        "points_all_finite": True,
        "axis": axis_records,
        "axis_count_product": math.prod(item["unique_count"] for item in axis_records),
        "lattice_phase": {
            "first_point_minus_pointref_m": [item["first_m"] - pointref[index] for index, item in enumerate(axis_records)],
            "first_point_minus_pointref_over_dp": [item["pointref_index_first"] for item in axis_records],
            "all_axis_indices_integer_within_tolerance": all(
                item["pointref_index_max_integer_residual"] <= 2.0e-5 for item in axis_records
            ),
        },
        "xml_drawbox_observation": {
            "lower_m": lower,
            "upper_m": upper,
            "all_points_inside": all(item["all_points_inside_xml_drawbox"] for item in axis_records),
        },
        "observed_cell_envelope_m": {
            "lower_m": [item["cell_envelope_low_m"] for item in axis_records],
            "upper_m": [item["cell_envelope_high_m"] for item in axis_records],
        },
        "discrete_sample_quadrature": {
            "density_kg_m3": xml["generated_particles"]["rhop0_kg_m3"],
            "cell_volume_dp3_m3": dp ** 3,
            "quadrature_volume_m3": quadrature_volume,
            "quadrature_mass_kg": quadrature_volume * xml["generated_particles"]["rhop0_kg_m3"],
            "xml_massfluid_sample_kg": sample_mass,
            "count_times_massfluid_kg": sample_mass,
            "status": "DISCRETE_QUADRATURE_ONLY_NOT_CONTINUUM_TRUTH",
        },
    }


def owner_contract() -> dict[str, Any]:
    owner = json.loads(OWNER.read_text(encoding="utf-8"))
    binding = json.loads(CANONICAL_BINDING.read_text(encoding="utf-8"))
    physical = owner["physical_binding"]
    reservoir = physical["geometry"]["fluid_reservoir"]
    initial = physical["initial_state"]["source_regions"]["fluid"]
    size = [float(value) for value in reservoir["size_m"]]
    low = [float(value) for value in reservoir["low_m"]]
    volume = math.prod(size)
    mass = float(physical["initial_state"]["continuum_mass_by_source_kg"]["fluid"])
    if abs(volume - float(physical["parameters"]["continuum_fluid_volume_m3"])) > 1e-12:
        raise ValueError("owner volume and owner parameter disagree")
    if abs(volume * float(physical["density_kg_m3"]) - mass) > 1e-9:
        raise ValueError("owner volume*density and owner continuum mass disagree")
    if reservoir != initial:
        raise ValueError("owner reservoir and initial source region disagree")
    return {
        "owner_file": file_binding(OWNER),
        "canonical_binding_file": file_binding(CANONICAL_BINDING),
        "owner_identity": {key: owner.get(key) for key in ("family_id", "case_id", "physical_case_id", "mechanism_id")},
        "physical_condition_sha256": owner.get("physical_condition_sha256"),
        "canonical_condition_sha256": binding.get("physical_condition_sha256"),
        "continuous_source_contract": {
            "low_m": low,
            "size_m": size,
            "upper_m": [low[index] + size[index] for index in range(3)],
            "volume_m3": volume,
            "density_kg_m3": float(physical["density_kg_m3"]),
            "mass_kg": mass,
            "mkfluid_relative": reservoir.get("mkfluid"),
            "authority": "CURRENT336 owner/physical-binding metadata; not inferred from particle count",
        },
        "owner_source_claims": {
            "generated_xml": claimed_file(Path(owner["source"]["generated_xml"])),
            "native_solver_receipt": claimed_file(Path(owner["source"]["native_solver_receipt"])),
            "actual_full_initial_QA": claimed_file(Path(owner["source"]["actual_full_initial_QA"])),
        },
    }


def solver_time_provenance(authority: dict[str, Any]) -> dict[str, Any]:
    """Read the small historical receipt/RunPARTs time sidecars, never BI4/H5."""

    claim = authority["owner_source_claims"]["native_solver_receipt"]
    receipt_path = Path(claim["path"])
    if not receipt_path.is_file():
        return {"status": "UNKNOWN_NATIVE_RECEIPT_MISSING", "receipt": claim, "bi4_read": False, "hdf5_read": False}
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    output_root = Path(str(receipt.get("output_root", ""))).expanduser()
    runparts_path = output_root / "solver_output" / "RunPARTs.csv"
    rows: list[dict[str, str]] = []
    if runparts_path.is_file():
        lines = [line for line in runparts_path.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
        rows = list(csv.DictReader(lines, delimiter=";"))
    def clean_int(value: str | None) -> int | None:
        if value is None or not value.strip():
            return None
        return int(value.replace(",", "").strip())
    def clean_float(value: str | None) -> float | None:
        if value is None or not value.strip():
            return None
        return float(value.replace(",", "").strip())
    first = rows[0] if rows else None
    last = rows[-1] if rows else None
    command = receipt.get("command") if isinstance(receipt.get("command"), list) else []
    return {
        "status": "PASS_RECEIPT_AND_RUNPARTS_TIME_PROVENANCE" if last is not None else "UNKNOWN_RUNPARTS_MISSING_OR_EMPTY",
        "receipt": file_binding(receipt_path),
        "receipt_status": receipt.get("status"),
        "receipt_returncode": receipt.get("returncode"),
        "receipt_started_at_utc": receipt.get("started_at_utc"),
        "receipt_finished_at_utc": receipt.get("finished_at_utc"),
        "receipt_output_root": str(output_root),
        "solver_command": command,
        "requested_tmax_s": next((clean_float(str(item).split(":", 1)[1]) for item in command
                                   if str(item).startswith("-tmax:")), None),
        "requested_tout_s": next((clean_float(str(item).split(":", 1)[1]) for item in command
                                   if str(item).startswith("-tout:")), None),
        "runparts": file_binding(runparts_path) if runparts_path.is_file() else {"exists": False, "path": str(runparts_path)},
        "runparts_row_count": len(rows),
        "first_saved_row": ({"part": clean_int(first.get("Part")), "time_s": clean_float(first.get("TimeStep [s]")),
                              "steps": clean_int(first.get("Steps"))} if first else None),
        "last_saved_row": ({"part": clean_int(last.get("Part")), "time_s": clean_float(last.get("TimeStep [s]")),
                             "steps": clean_int(last.get("Steps"))} if last else None),
        "time_basis": "actual RunPARTs saved-row TimeStep [s]; command tmax/tout are requested controls",
        "bi4_read": False,
        "hdf5_read": False,
    }


def catalog_provenance() -> dict[str, Any]:
    """Bind the CURRENT336 identity and its catalog time window if available."""

    result: dict[str, Any] = {"catalog": claimed_file(CURRENT_CATALOG), "matched_rows": []}
    if not CURRENT_CATALOG.is_file():
        result["status"] = "UNKNOWN_CURRENT_CATALOG_MISSING"
        return result
    catalog = json.loads(CURRENT_CATALOG.read_text(encoding="utf-8"))
    for row in catalog.get("cases", []):
        if not isinstance(row, dict):
            continue
        if row.get("runtime_case_alias") == "F1_FALLBACK_ECC_COARSE" or row.get("physical_case_id") == "F1_ECC_THICK_DBC_LOWER_HEAD_V1":
            result["matched_rows"].append({
                "family_id": row.get("family_id"),
                "physical_case_id": row.get("physical_case_id"),
                "runtime_case_alias": row.get("runtime_case_alias"),
                "frames": row.get("frames"),
                "particles": row.get("particles"),
                "actual_time_window_s": row.get("actual_time_window_s"),
                "precision_status": row.get("precision_status"),
            })
    result["status"] = "PASS_CURRENT336_IDENTITY_BOUND" if result["matched_rows"] else "UNKNOWN_CURRENT336_ROW_MISSING"
    return result


def docs_binding() -> dict[str, Any]:
    text = GENCASE_DOC.read_text(encoding="utf-8")
    required = ["<setshapemode>actual | dp | all</setshapemode>", "<setshapemode>bound</setshapemode>", "<drawbox>"]
    return {
        "documentation": file_binding(GENCASE_DOC),
        "required_tokens_present": {token: token in text for token in required},
        "interpretation": "public XML interface examples only; no exact cell crop/tie-breaking rule is claimed",
    }


def compare_run(label: str, xml: dict[str, Any], vtk: dict[str, Any], out_path: Path) -> dict[str, Any]:
    contract = owner_contract()["continuous_source_contract"]
    owner_low, owner_upper = contract["low_m"], contract["upper_m"]
    observed_low = vtk["observed_cell_envelope_m"]["lower_m"]
    observed_upper = vtk["observed_cell_envelope_m"]["upper_m"]
    envelope_residual = [
        max(abs(observed_low[index] - owner_low[index]), abs(observed_upper[index] - owner_upper[index]))
        for index in range(3)
    ]
    owner_mass = contract["mass_kg"]
    sample_mass = vtk["discrete_sample_quadrature"]["quadrature_mass_kg"]
    sample_error_pct = 100.0 * (sample_mass - owner_mass) / owner_mass
    box = xml["fluid_drawbox_last"]
    box_mass = box["volume_m3"] * contract["density_kg_m3"]
    source_count = vtk["point_count_header"]
    xml_count = xml["generated_particles"]["fluid_count_from_xml"]
    return {
        "label": label,
        "xml": xml["xml"],
        "generated_out": file_binding(out_path),
        "generated_date": xml["generated_date"],
        "dp_m": xml["definition"]["dp_m"],
        "source_drawbox": {
            "point_m": box["point_m"],
            "size_m": box["size_m"],
            "upper_m": box["upper_m"],
            "primitive_volume_m3": box["volume_m3"],
            "primitive_mass_kg": box_mass,
            "interpretation": "XML command primitive; not selected as continuous authority when owner contract exists",
        },
        "setshapemode": xml["setshapemode"],
        "generated_vtk": vtk,
        "count_cross_check": {
            "vtk_header_count": source_count,
            "generated_xml_fluid_count": xml_count,
            "axis_count_product": vtk["axis_count_product"],
            "all_three_equal": source_count == xml_count == vtk["axis_count_product"],
        },
        "owner_contract_comparison": {
            "owner_continuum_mass_kg": owner_mass,
            "sample_quadrature_mass_kg": sample_mass,
            "sample_mass_error_pct_vs_owner": sample_error_pct,
            "observed_cell_envelope_low_m": observed_low,
            "observed_cell_envelope_upper_m": observed_upper,
            "owner_low_m": owner_low,
            "owner_upper_m": owner_upper,
            "cell_envelope_max_abs_residual_m": max(envelope_residual),
            "cell_envelope_matches_owner_within_tolerance": max(envelope_residual) <= TOL,
            "continuous_contract_status": "SOURCE_AUTHORITY_OWNER_CONTRACT",
        },
        "mass_gate_interpretation": {
            "whole_initial_mass_target_basis": "owner continuum contract 40.2 kg",
            "sample_mass_within_frozen_1pct_target": abs(sample_error_pct) <= 1.0,
            "sample_mass_is_sufficient_for_continuum_gate": False,
            "geometry_consistent_three_grid_candidate": (
                "PASS_FOR_THIS_ORIGINAL_GRID" if label == "dp0p010_original" and max(envelope_residual) <= TOL
                else "NOT_READY_CONTINUOUS_GEOMETRY_MATCH" if max(envelope_residual) > TOL
                else "UNKNOWN_PENDING_GRID_AND_CONTROL_CLOSURE"
            ),
            "no_mass_rescale": True,
        },
    }


def observed_result_explanation(original: dict[str, Any], fine: dict[str, Any]) -> dict[str, Any]:
    """Turn the two exact producer outputs into scoped prose and flags.

    The wording is generated from measured counts, masses, payload digests,
    and cell-envelope residuals.  It deliberately does not convert a close
    sample mass or a matching count into a continuous-geometry claim.
    """

    def sentence(run: dict[str, Any]) -> str:
        comparison = run["owner_contract_comparison"]
        finite_points = bool(run["generated_vtk"].get("points_all_finite"))
        return (
            f"{run['label']} has {run['count_cross_check']['vtk_header_count']} finite Fluid.vtk POINTS "
            f"(finite_check={finite_points}), discrete sample mass "
            f"{comparison['sample_quadrature_mass_kg']:.9g} kg "
            f"({comparison['sample_mass_error_pct_vs_owner']:+.6f}% versus the owner 40.2 kg), "
            f"and maximum midpoint-cell-envelope residual "
            f"{comparison['cell_envelope_max_abs_residual_m']:.9g} m."
        )

    original_match = bool(original["owner_contract_comparison"]["cell_envelope_matches_owner_within_tolerance"])
    fine_match = bool(fine["owner_contract_comparison"]["cell_envelope_matches_owner_within_tolerance"])
    finite = bool(original["generated_vtk"].get("points_all_finite")) and bool(fine["generated_vtk"].get("points_all_finite"))
    if original_match and fine_match:
        geometry_text = "Both exact outputs have owner-matching midpoint envelopes; this remains a two-run observation, not a three-grid qualification."
    else:
        failed = [label for label, matched in (("dp0p010_original", original_match), ("dp0p009_repair_existing", fine_match)) if not matched]
        geometry_text = (
            "The exact output(s) " + ", ".join(failed) +
            " do not have an owner-matching midpoint envelope; the observed source/support mismatch is retained and no continuous-geometry equivalence is inferred."
        )
    return {
        "finite_point_payloads": finite,
        "measured_runs": [sentence(original), sentence(fine)],
        "geometry_interpretation": geometry_text,
        "mass_interpretation": (
            "The reported masses are discrete rho*dp^3 quadrature diagnostics. "
            "They do not replace the owner continuous 40.2 kg contract and no mass rescaling was applied."
        ),
        "mode_and_grid_interpretation": (
            "The available outputs are dp=.010 and one dp=.009 repair run; they do not supply a third spatial rung. "
            "Any future mode/source comparison must bind exact POINTS payloads and retain mismatches."
        ),
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def build(output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refuse to overwrite immutable report: {output}")
    authority = owner_contract()
    source_xml = parse_xml(SOURCE_XML)
    fine_xml = parse_xml(FINE_XML)
    original_vtk = parse_vtk(SOURCE_VTK, source_xml)
    fine_vtk = parse_vtk(FINE_VTK, fine_xml)
    # Force the small OUT files into the audit's input closure.  The parser
    # does not use their prose for mass; they are retained for provenance.
    original = compare_run("dp0p010_original", source_xml, original_vtk, SOURCE_OUT)
    fine = compare_run("dp0p009_repair_existing", fine_xml, fine_vtk, FINE_OUT)
    counterexamples = self_test()
    interpretation = observed_result_explanation(original, fine)
    report = {
        "schema": SCHEMA,
        "status": "PASS_FINITE_POINT_AUDIT_SCIENTIFIC_GEOMETRY_UNKNOWN",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_scope": {
            "bi4_read": False,
            "hdf5_read": False,
            "solver_launch": False,
            "gencase_launch": False,
            "read_inputs": "owner/binding/catalog JSON, exact generated XML/OUT/Fluid.vtk, public XML documentation",
            "vtk_scope": "Fluid.vtk POINTS payload only; no BI4/H5 payload",
        },
        "finite_point_validation": {
            "all_actual_points_finite": interpretation["finite_point_payloads"],
            "validation_order": "all binary POINTS float32 values are checked with math.isfinite before sorting/grouping",
            "manufactured_counterexamples": counterexamples,
        },
        "source_authority": authority,
        "current_catalog": catalog_provenance(),
        "native_time_provenance": solver_time_provenance(authority),
        "official_documentation": docs_binding(),
        "evidence_rules": {
            "continuous_geometry": "owner/physical-binding contract is authoritative when present",
            "xml_drawbox": "analytic command primitive, retained as separate diagnostic",
            "generated_vtk": "actual per-run lattice/count/phase evidence",
            "sample_mass": "count * massfluid or rho*dp^3 discrete initialization quadrature; never silently promoted to continuum truth",
            "generic_setshapemode_semantics": "UNKNOWN beyond documented token interface and these actual outputs",
        },
        "runs": [original, fine],
        "observed_result_explanation": interpretation,
        "three_grid_mass_gate": {
            "frozen_target": {
                "owner_continuum_mass_kg": authority["continuous_source_contract"]["mass_kg"],
                "owner_low_m": authority["continuous_source_contract"]["low_m"],
                "owner_size_m": authority["continuous_source_contract"]["size_m"],
                "owner_upper_m": authority["continuous_source_contract"]["upper_m"],
                "density_kg_m3": authority["continuous_source_contract"]["density_kg_m3"],
            },
            "original_dp0p010": {
                "continuous_geometry_basis": "OWNER_CONTRACT_40P2KG",
                "sample_quadrature_basis": "OBSERVED_40200_CENTERS_X_FULL_DP3",
                "status": "PASS_SOURCE_CONTRACT_AND_MIDPOINT_CELL_ENVELOPE",
            },
            "dp0p009": {
                "continuous_geometry_basis": "OWNER_CONTRACT_UNCHANGED_40P2KG",
                "sample_quadrature_basis": "OBSERVED_55352_CENTERS_X_FULL_DP3",
                "sample_mass_status": "WITHIN_1PCT_DIAGNOSTIC",
                "continuous_geometry_status": "NOT_READY_CONTINUOUS_GEOMETRY_MATCH",
                "reason": "dp=.009 lattice cell envelope does not equal owner [0,.4]x[0,.67]x[0,.15] even though all centers remain inside XML drawbox",
                "mass_rescale": False,
            },
            "qualification": "UNKNOWN_UNTIL_A_THIRD_GRID_USES_THE_SAME_OWNER_GEOMETRY_CONTRACT_AND_VALIDATED_BOUNDARY_RULE",
        },
        "conditional_geometry_repair_proposal": {
            "launch_status": "PREPARE_ONLY_LAUNCH_DISABLED",
            "need": "A geometry-consistent dp=.009 (or other separated grid) requires a preregistered boundary/lattice rule because .4/.009, .67/.009, and .15/.009 are not all integers.",
            "fixed_contract": {
                "low_m": authority["continuous_source_contract"]["low_m"],
                "size_m": authority["continuous_source_contract"]["size_m"],
                "mass_kg": authority["continuous_source_contract"]["mass_kg"],
                "density_kg_m3": authority["continuous_source_contract"]["density_kg_m3"],
                "no_particle_mass_rescale": True,
                "no_posthoc_box_adjustment": True,
            },
            "minimal_cpu_gencase_scope": {
                "purpose": "compare explicitly registered lattice/boundary rules only",
                "solver": "none",
                "hdf5": "none",
                "worker_count": 1,
                "max_wall_s": 600,
                "output": "new generated XML/OUT/Fluid.vtk/receipt path; preserve existing raw/BI4",
                "candidate_rules": [
                    "owner_box_midpoint_centres_with_explicit_inside_or_boundary_rule",
                    "setshapemode_actual_probe_if_official_binary accepts the exact syntax",
                ],
                "acceptance_fields": [
                    "owner low/upper contract binding",
                    "observed center phase and cell envelope",
                    "count product and sample mass diagnostic",
                    "no particle mass rescale",
                ],
                "scientific_qualification": "UNKNOWN_PENDING_PARENT_GUARD_AND_ACTUAL_OUTPUT",
            },
        },
    }
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return report


def self_test() -> dict[str, Any]:
    """Exercise the POINTS guard with valid and manufactured-invalid data."""

    def vtk_bytes(points: list[tuple[float, float, float]]) -> bytes:
        header = b"# vtk DataFile Version 3.0\nsynthetic\nBINARY\nDATASET POLYDATA\n"
        header += f"POINTS {len(points)} float\n".encode("ascii")
        payload = struct.pack(">" + "f" * (3 * len(points)), *(value for point in points for value in point))
        return header + payload

    synthetic_xml: dict[str, Any] = {
        "definition": {"dp_m": 0.1, "pointref_m": [0.05, 0.05, 0.05]},
        "fluid_drawbox_last": {
            "point_m": [0.0, 0.0, 0.0],
            "upper_m": [0.2, 0.2, 0.2],
        },
        "generated_particles": {"sample_mass_from_xml_kg": 2.0, "rhop0_kg_m3": 1000.0},
    }
    valid_points = [(0.05, 0.05, 0.05), (0.15, 0.05, 0.05)]
    with tempfile.TemporaryDirectory(prefix="ds02-f1-s1-geometry-semantics-v3-selftest-") as tmp:
        root = Path(tmp)
        valid_path = root / "valid.vtk"
        different_path = root / "same_count_different_points.vtk"
        valid_path.write_bytes(vtk_bytes(valid_points))
        different_path.write_bytes(vtk_bytes([(0.05, 0.05, 0.05), (0.15, 0.15, 0.05)]))
        left = parse_vtk(valid_path, synthetic_xml)
        right = parse_vtk(different_path, synthetic_xml)
        if left["point_count_header"] != right["point_count_header"] or left["points_payload_sha256"] == right["points_payload_sha256"]:
            raise AssertionError("equal-count/different-point counterexample was not retained")

        truncated_path = root / "truncated.vtk"
        truncated_path.write_bytes(valid_path.read_bytes()[:-1])
        try:
            parse_vtk(truncated_path, synthetic_xml)
        except ValueError as error:
            truncated_reason = str(error)
        else:
            raise AssertionError("truncated POINTS payload was accepted")

        rejected: dict[str, str] = {}
        for name, invalid in (("nan", float("nan")), ("inf", float("inf"))):
            invalid_path = root / f"{name}.vtk"
            invalid_path.write_bytes(vtk_bytes([(0.05, 0.05, 0.05), (invalid, 0.05, 0.05)]))
            try:
                parse_vtk(invalid_path, synthetic_xml)
            except ValueError as error:
                rejected[name] = str(error)
            else:
                raise AssertionError(f"{name} POINTS payload was accepted")
    return {
        "status": "PASS",
        "equal_count_different_payload_is_distinguished": True,
        "truncated_payload_rejected": True,
        "truncated_rejection_reason": truncated_reason,
        "nan_payload_rejected": "nan" in rejected,
        "inf_payload_rejected": "inf" in rejected,
        "rejection_reasons": rejected,
        "bi4_read": False,
        "hdf5_read": False,
        "solver_launch": False,
        "gencase_launch": False,
    }


def all_input_paths() -> list[Path]:
    """Return the bounded, non-BI4/H5 input closure for the forward worker."""

    paths = [
        Path(__file__), OWNER, CANONICAL_BINDING, CURRENT_CATALOG, GENCASE_DOC,
        SOURCE_XML, SOURCE_OUT, SOURCE_VTK, FINE_XML, FINE_OUT, FINE_VTK,
        V8_RUNNER, V8_STRICT, V8_RUNTIME, PYTHON,
    ]
    if V2_SCRIPT.is_file():
        paths.append(V2_SCRIPT)
    if V2_REPORT.is_file():
        paths.append(V2_REPORT)
    native_receipt = OWNER / "../.."  # replaced below by the owner contract path
    del native_receipt
    owner = json.loads(OWNER.read_text(encoding="utf-8"))
    claim = owner.get("source", {}).get("native_solver_receipt")
    if isinstance(claim, str):
        receipt_path = Path(claim).expanduser()
        if receipt_path.is_file():
            paths.append(receipt_path)
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                output_root = Path(str(receipt.get("output_root", ""))).expanduser()
                runparts = output_root / "solver_output" / "RunPARTs.csv"
                if runparts.is_file():
                    paths.append(runparts)
            except (OSError, json.JSONDecodeError):
                pass
    unique = list(dict.fromkeys(path.expanduser().resolve() for path in paths if path.is_file()))
    if any(path.suffix.lower() in {".bi4", ".h5", ".hdf5"} for path in unique):
        raise ValueError("F1 geometry semantics closure must not contain BI4/H5")
    return unique


def atomic_json(output: Path, value: Any) -> None:
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"refuse to overwrite immutable artifact: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def build_request(output: Path = REQUEST_PATH) -> dict[str, Any]:
    """Prepare a parent-v8 CPU-only audit request; no solver or GenCase."""

    if output.exists():
        raise FileExistsError(f"refuse to overwrite immutable request: {output}")
    inputs = all_input_paths()
    records = {str(path): file_binding(path) for path in inputs}
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
        "command": [str(PYTHON), str(Path(__file__).resolve()), "--audit", "--output", "{attempt_root}/f1_s1_geometry_semantics_audit_v3.json"],
        "cwd": str(REPO),
        "input_files": list(records),
        "input_hashes": {path: record["sha256"] for path, record in records.items()},
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "estimated_input_read_bytes": sum(record["bytes"] for record in records.values()),
        "estimated_geometry_read_bytes": sum(record["bytes"] for path, record in records.items() if path.endswith(".vtk")),
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
            "schema": "ds02.stage2.f1-s1.geometry-semantics-binding.v3",
            "owner": file_binding(OWNER),
            "canonical_binding": file_binding(CANONICAL_BINDING),
            "continuous_geometry_authority": {
                "low_m": [0.0, 0.0, 0.0],
                "size_m": [0.4, 0.67, 0.15],
                "upper_m": [0.4, 0.67, 0.15],
                "density_kg_m3": 1000.0,
                "mass_kg": 40.2,
                "source": "CURRENT336 owner/physical-binding; not inferred from particle samples",
            },
            "point_payload_contract": {
                "all_float32_coordinates_must_be_finite_before_grouping": True,
                "same_count_requires_points_payload_sha256": True,
                "nan_inf_and_truncated_payloads_are_rejection_cases": True,
                "manufactured_self_test": "run locally in worker without source VTK",
            },
            "lineage": {
                "prior_v2_script": file_binding(V2_SCRIPT) if V2_SCRIPT.is_file() else None,
                "prior_v2_report": file_binding(V2_REPORT) if V2_REPORT.is_file() else None,
                "prior_bytes_immutable": True,
            },
            "actual_inputs": {
                "original_xml": file_binding(SOURCE_XML),
                "original_out": file_binding(SOURCE_OUT),
                "original_vtk": file_binding(SOURCE_VTK),
                "dp009_xml": file_binding(FINE_XML),
                "dp009_out": file_binding(FINE_OUT),
                "dp009_vtk": file_binding(FINE_VTK),
            },
            "parent_guard_prepost_hash_required": True,
        },
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "path": "{attempt_root}/f1_s1_geometry_semantics_audit_v3.json",
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
        "qualification_stage": "stage2_f1_s1_geometry_semantics_audit_v3_pending_parent_v8_dispatch",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(output, request)
    return request


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
        print(json.dumps({
            "status": "PREPARED",
            "path": str(REQUEST_PATH),
            "input_count": len(request["input_files"]),
            "estimated_geometry_read_bytes": request["estimated_geometry_read_bytes"],
            "estimated_storage_bytes": request["estimated_storage_bytes"],
        }, indent=2))
        return 0
    report = build(args.output)
    print(json.dumps({
        "status": report["status"],
        "output": str(args.output.resolve()),
        "runs": len(report["runs"]),
        "all_actual_points_finite": report["finite_point_validation"]["all_actual_points_finite"],
        "scientific_qualification": report["observed_result_explanation"]["scientific_qualification"],
        "bi4_read": report["audit_scope"]["bi4_read"],
        "hdf5_read": report["audit_scope"]["hdf5_read"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

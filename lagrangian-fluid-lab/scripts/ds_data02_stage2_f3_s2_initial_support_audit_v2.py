#!/usr/bin/env python3
"""Guarded initial support audit for the existing F3-S2 spatial products.

The original, coarse, and fine GenCase products already exist.  This worker
reads only their generated XML plus Fluid/Bound VTK point clouds and receipts;
it never re-runs GenCase and never opens BI4/HDF5.  VTK files are deferred
inputs: the parent guard hashes them after reservation and this worker checks a
complete SHA/stat pair before and after decoding.

The report separates the discrete producer sample mass from the continuous
owner geometry and checks the receipt-bound acceleration-control identity for
each grid.  The F3 owner contract has no scalar continuous fluid-mass value,
so a particle-sample match is diagnostic and cannot grant QI/QN/QE.  XML
basenames alone are never treated as a forcing identity; the existing
original-grid control mismatch is reported rather than repaired in place.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import struct
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np

DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")

SOURCE_XML = DATA_ROOT / (
    "families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/"
    "root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/"
    "prepared/pitch120_ay0750/F3_STAGE1_DP006_P1200_AY0750.xml"
)
SOURCE_RECEIPT = DATA_ROOT / (
    "families/F3/F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005/"
    "root-cell3-dp006-twoaxis-ay0p50-actual-gencase-056/execution-receipt.json"
)
SOURCE_QA = DATA_ROOT / (
    "families/F3/F3_TWOAXIS_NOMINAL_THREE_DP_ACTUAL_INITIAL_QA/"
    "root-cell3-twoaxis-nominal-three-dp-official-native-initial-qa-058/native-initial-qa.json"
)
SOURCE_QA_RECEIPT = DATA_ROOT / (
    "families/F3/F3_TWOAXIS_NOMINAL_THREE_DP_ACTUAL_INITIAL_QA/"
    "root-cell3-twoaxis-nominal-three-dp-official-native-initial-qa-058/execution-receipt.json"
)
S2_CONTROL_REFERENCE = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2-reference/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_sentinel_spatial_preflight_inputs_v2/F3_S2/original/CaseSloshingAccData.csv"
)

CASES = {
    "original_dp006": {
        "root": DATA_ROOT / "families/F3/F3_S2_SPATIAL_ORIGINAL_DP0p006000/f3_s2_spatial_original_dp0p006000-001",
        "role": "original_current",
        "case_id": "F3_S2_SPATIAL_ORIGINAL_DP0p006000",
    },
    "coarse_dp0075": {
        "root": DATA_ROOT / "families/F3/F3_S2_SPATIAL_V2_COARSE_DP0p007500/f3_s2_spatial_v2_coarse_dp0p007500-001",
        "role": "coarse_candidate",
        "case_id": "F3_S2_SPATIAL_V2_COARSE_DP0p007500",
    },
    "fine_dp0048": {
        "root": DATA_ROOT / "families/F3/F3_S2_SPATIAL_V2_FINE_DP0p004800/f3_s2_spatial_v2_fine_dp0p004800-001",
        "role": "fine_candidate",
        "case_id": "F3_S2_SPATIAL_V2_FINE_DP0p004800",
    },
}

SOURCE_SAMPLE_MASS_KG = 14.58
MASS_ONE_PERCENT = 0.01
MASS_TWO_PERCENT = 0.02


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
    }


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable audit output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def finite(values: list[float], label: str) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"non-finite {label}: {values}")


def number(value: str | None, label: str) -> float:
    if value is None:
        raise ValueError(f"missing numeric value for {label}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite numeric value for {label}")
    return result


def vec(node: ET.Element | None, label: str) -> list[float] | None:
    if node is None:
        return None
    values = [number(node.get(axis), f"{label}.{axis}") for axis in "xyz"]
    finite(values, label)
    return values


def parse_box(node: ET.Element, label: str) -> dict[str, Any]:
    point = next((child for child in node if local(child.tag) == "point"), None)
    size = next((child for child in node if local(child.tag) == "size"), None)
    low = vec(point, f"{label}.point")
    size_m = vec(size, f"{label}.size")
    if low is None or size_m is None or any(v <= 0 for v in size_m):
        raise ValueError(f"invalid {label}")
    high = [low[i] + size_m[i] for i in range(3)]
    return {"low_m": low, "high_m": high, "size_m": size_m,
            "boxfill": next((child.text or "" for child in node if local(child.tag) == "boxfill"), "").strip(),
            "layers": dict(next((child for child in node if local(child.tag) == "layers"), ET.Element("layers")).attrib)}


def parse_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = next((node for node in root.iter() if local(node.tag) == "definition"), None)
    if definition is None:
        raise ValueError(f"missing definition: {path}")
    dp = number(definition.get("dp"), "definition.dp")
    pointref = vec(next((node for node in definition if local(node.tag) == "pointref"), None), "definition.pointref")
    pointmin = vec(next((node for node in definition if local(node.tag) == "pointmin"), None), "definition.pointmin")
    pointmax = vec(next((node for node in definition if local(node.tag) == "pointmax"), None), "definition.pointmax")
    params = {node.get("key"): node.get("value") for node in root.iter() if local(node.tag) == "parameter" and node.get("key")}
    cfl = [number(node.get("value"), "cflnumber") for node in root.iter() if local(node.tag) == "cflnumber"]
    gravity = [dict(node.attrib) for node in root.iter() if local(node.tag) == "gravity"]
    accinputs = [{"attributes": dict(node.attrib), "children": [dict(child.attrib) for child in node]}
                 for node in root.iter() if local(node.tag) == "accinput"]
    files = [node.get("name") for node in root.iter() if local(node.tag) == "file" and node.get("name")]

    fluid_boxes: list[dict[str, Any]] = []
    bound_boxes: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    for mainlist in (node for node in root.iter() if local(node.tag) == "mainlist"):
        shape_mode = "full"
        limit_mode = "full"
        active_fluid: int | None = None
        active_bound: int | None = None
        for child in list(mainlist):
            tag = local(child.tag)
            if tag == "setshapemode":
                shape_mode = (child.text or "").strip()
            elif tag == "setboxlimitmode":
                limit_mode = child.get("mode", "UNKNOWN")
            elif tag == "setmkfluid":
                active_fluid = int(child.get("mk", "0")); active_bound = None
            elif tag in {"setmkbound", "setmkvoid"}:
                active_bound = int(child.get("mk", "0")) if tag == "setmkbound" else None; active_fluid = None
            elif tag == "drawbox":
                box = parse_box(child, "drawbox")
                box.update({"shape_mode": shape_mode, "box_limit_mode": limit_mode,
                            "mkfluid": active_fluid, "mkbound": active_bound})
                if active_fluid is not None:
                    fluid_boxes.append(box)
                elif active_bound is not None:
                    bound_boxes.append(box)
                operations.append({"op": tag, "box": box})
            elif tag in {"setdrawmode", "clipplane", "clipbox", "clipreset", "drawextrude", "shapeout"}:
                operations.append({"op": tag, "attributes": dict(child.attrib), "text": (child.text or "").strip()})

    particles = next((node for node in root.iter() if local(node.tag) == "particles"), None)
    blocks: list[dict[str, Any]] = []
    if particles is not None:
        for node in particles:
            if local(node.tag) != "fluid" or not all(node.get(k) is not None for k in ("mkfluid", "mk", "begin", "count")):
                continue
            blocks.append({"mkfluid": int(node.get("mkfluid")), "mk": int(node.get("mk")),
                           "begin": int(node.get("begin")), "count": int(node.get("count"))})
    if not blocks:
        raise ValueError(f"no typed fluid blocks: {path}")
    total_particles = int(particles.get("np")) if particles is not None and particles.get("np") else None
    constants = next((node for node in root.iter() if local(node.tag) == "constants"), None)
    mass_node = next((node for node in (list(constants) if constants is not None else []) if local(node.tag) == "massfluid"), None)
    massfluid = number(mass_node.get("value") if mass_node is not None else None, "massfluid")
    fluid_count = sum(block["count"] for block in blocks)
    return {
        "path": str(path.resolve()), "dp_m": dp, "pointref_m": pointref,
        "pointmin_m": pointmin, "pointmax_m": pointmax,
        "parameters": params, "cflnumber": cfl, "gravity": gravity,
        "accinputs": accinputs, "motion_files": files,
        "fluid_boxes": fluid_boxes, "bound_boxes": bound_boxes, "operations": operations,
        "total_particles": total_particles, "fluid_blocks": blocks, "fluid_count": fluid_count,
        "massfluid_kg": massfluid, "sample_mass_kg": fluid_count * massfluid,
    }


def control_summary(path: Path, bound: dict[str, Any]) -> dict[str, Any]:
    """Read a generated acceleration table and retain its exact source ID.

    The S2 control is deliberately checked separately from the XML control
    projection.  A basename such as ``CaseSloshingAccData.csv`` is not a
    forcing identity: the product receipt's input digest and the file's own
    digest must agree.  This catches the existing original-grid/S1-control
    mismatch without silently substituting the corrected S2 control.
    """
    times: list[float] = []
    rows = 0
    header: list[str] | None = None
    finite_rows = 0
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, delimiter=";")
        for raw in reader:
            if not raw or all(not cell.strip() for cell in raw):
                continue
            if header is None:
                header = [cell.strip().lstrip("#") for cell in raw]
                continue
            if len(raw) != len(header):
                raise ValueError(f"acceleration control row width differs: {path}")
            values = [float(cell.strip()) for cell in raw]
            if not all(math.isfinite(value) for value in values):
                raise ValueError(f"non-finite acceleration control row: {path}")
            times.append(values[0]); rows += 1; finite_rows += 1
    if header is None or rows == 0 or header[0].lower() != "time":
        raise ValueError(f"acceleration control header/rows are missing: {path}")
    if any(later < earlier for earlier, later in zip(times, times[1:])):
        raise ValueError(f"acceleration control time is not monotonic: {path}")
    return {
        **bound,
        "header": header,
        "row_count": rows,
        "finite_numeric_rows": finite_rows,
        "time_first_s": times[0],
        "time_last_s": times[-1],
        "time_monotonic_non_decreasing": True,
    }


def receipt_control_binding(receipt: dict[str, Any], control: dict[str, Any], label: str) -> dict[str, Any]:
    """Find the receipt's exact CaseSloshingAccData input digest."""
    mappings = []
    request = receipt.get("request")
    if isinstance(request, dict):
        for key in ("input_sha256", "input_hashes"):
            if isinstance(request.get(key), dict):
                mappings.append(request[key])
    for key in ("input_hashes_at_launch", "input_hashes_after_run"):
        if isinstance(receipt.get(key), dict):
            mappings.append(receipt[key])
    candidates: list[dict[str, str]] = []
    for mapping in mappings:
        for path_text, digest in mapping.items():
            if Path(path_text).name == "CaseSloshingAccData.csv" and isinstance(digest, str):
                candidates.append({"path": str(Path(path_text).expanduser().resolve()), "sha256": digest})
    unique = {(item["path"], item["sha256"]): item for item in candidates}
    if not unique:
        raise ValueError(f"{label} receipt does not bind a CaseSloshingAccData.csv input")
    digest_set = {item["sha256"] for item in unique.values()}
    if len(digest_set) != 1:
        raise ValueError(f"{label} receipt binds conflicting CaseSloshingAccData.csv digests")
    matches = [item for item in unique.values() if item["sha256"] == control["sha256"]]
    if not matches:
        raise ValueError(f"{label} control file digest is absent or ambiguous in its receipt")
    # A corrected S2 receipt can list both its copied prepared input and the
    # reference snapshot.  Multiple paths are acceptable only when the digest
    # is identical; differing digests remain a hard source-join failure.
    return {"paths": sorted(item["path"] for item in matches), "sha256": control["sha256"],
            "path_count": len(matches)}


def read_vtk_points(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    data = path.read_bytes()
    points_re = re.compile(rb"(?m)^POINTS\s+(\d+)\s+float\r?\n")
    match = points_re.search(data)
    if match is None:
        raise ValueError(f"missing binary POINTS: {path}")
    count = int(match.group(1)); offset = match.end(); size = count * 3 * 4
    if offset + size > len(data):
        raise ValueError(f"truncated POINTS payload: {path}")
    points = np.frombuffer(data, dtype=">f4", count=count * 3, offset=offset).reshape((-1, 3)).copy()
    if not np.isfinite(points).all():
        raise ValueError(f"non-finite VTK point: {path}")
    return points, {"point_count": count, "points_offset": offset, "points_bytes": size}


def read_vtk_fluid(path: Path, expected_count: int, blocks: list[dict[str, Any]]) -> tuple[np.ndarray, dict[str, Any]]:
    points, header = read_vtk_points(path)
    if points.shape[0] != expected_count:
        raise ValueError(f"Fluid VTK count {points.shape[0]} != XML fluid count {expected_count}")
    data = path.read_bytes()
    point_data_re = re.compile(rb"(?m)^POINT_DATA\s+(\d+)\r?\n")
    point_data = point_data_re.search(data, header["points_offset"] + header["points_bytes"])
    if point_data is None or int(point_data.group(1)) != expected_count:
        raise ValueError("Fluid VTK missing matching POINT_DATA")
    scalars_re = re.compile(rb"(?m)^SCALARS\s+([^\s]+)\s+([^\s]+)(?:\s+(\d+))?\r?\n")
    matches = [m for m in scalars_re.finditer(data, point_data.end()) if m.group(1) == b"Idp"]
    if len(matches) != 1 or matches[0].group(2) != b"unsigned_int" or int(matches[0].group(3) or b"1") != 1:
        raise ValueError("Fluid VTK has no unique unsigned-int Idp scalar")
    lookup_re = re.compile(rb"LOOKUP_TABLE\s+default\r?\n")
    lookup = lookup_re.match(data[matches[0].end():])
    if lookup is None:
        raise ValueError("Fluid Idp scalar lacks LOOKUP_TABLE default")
    ids_offset = matches[0].end() + lookup.end(); ids_bytes = expected_count * 4
    if ids_offset + ids_bytes > len(data):
        raise ValueError("truncated Fluid Idp payload")
    raw_ids = np.frombuffer(data, dtype=">u4", count=expected_count, offset=ids_offset).copy()
    global_ids = np.concatenate([np.arange(b["begin"], b["begin"] + b["count"], dtype=np.uint32) for b in blocks])
    if np.array_equal(np.sort(raw_ids), np.sort(global_ids)):
        mapping = "GLOBAL_XML_PARTICLE_IDS"
    elif np.array_equal(np.sort(raw_ids), np.arange(expected_count, dtype=np.uint32)):
        mapping = "LOCAL_FLUID_ORDER_TO_XML_IDS"
    else:
        raise ValueError("Fluid VTK Idp values do not match XML fluid ranges")
    return points, {**header, "idp_mapping": mapping, "idp_scalar": "unsigned_int", "idp_count": int(raw_ids.size)}


def axis_summary(points: np.ndarray) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for axis, i in zip("xyz", range(3)):
        values = np.unique(points[:, i]); diffs = np.diff(values)
        result[axis] = {"unique_count": int(values.size), "min_m": float(values[0]), "max_m": float(values[-1]),
                        "spacing_min_m": float(diffs.min()) if diffs.size else 0.0,
                        "spacing_max_m": float(diffs.max()) if diffs.size else 0.0,
                        "spacing_values_m": sorted({round(float(v), 12) for v in diffs})[:32]}
    return result


def inside_relation(points: np.ndarray, box: dict[str, Any] | None, dp: float) -> dict[str, Any]:
    if box is None:
        return {"status": "UNKNOWN_NO_FLUID_DRAWBOX"}
    low = np.asarray(box["low_m"], dtype=np.float64); high = np.asarray(box["high_m"], dtype=np.float64)
    tol = max(1e-8, dp * 1e-5)
    inside = np.all((points >= low - tol) & (points <= high + tol), axis=1)
    return {"low_m": box["low_m"], "high_m": box["high_m"], "tolerance_m": tol,
            "inside_closed_count": int(inside.sum()), "outside_closed_count": int((~inside).sum())}


def control_projection(meta: dict[str, Any]) -> dict[str, Any]:
    keys = ("StepAlgorithm", "VerletSteps", "Kernel", "ViscoTreatment", "Visco", "DensityDT", "DensityDTvalue",
            "Shifting", "RigidAlgorithm", "CoefDtMin", "DtIni", "DtMin", "DtFixed", "DtFixedFile", "DtAllParticles",
            "Boundary", "SlipMode", "TimeMax", "TimeOut")
    return {key: meta["parameters"].get(key) for key in keys}


def controls_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (control_projection(a) == control_projection(b) and a["cflnumber"] == b["cflnumber"]
            and a["gravity"] == b["gravity"] and a["accinputs"] == b["accinputs"])


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_product_receipt(label: str, expected_case_id: str, root: Path, xml_meta: dict[str, Any], receipt: dict[str, Any]) -> None:
    """Close a generated XML to its own completed GenCase receipt.

    The receipt is an existing producer fact.  It is not used to grant any
    solver or physical qualification; it only prevents joining the XML/VTK
    files from a different attempt with the same display label.
    """
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        raise ValueError(f"{label} receipt schema is not the Stage2 execution receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"{label} GenCase receipt is not completed with return code 0")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise ValueError(f"{label} receipt request is malformed")
    if request.get("case_id") != expected_case_id:
        raise ValueError(f"{label} receipt case identity is not exact")
    output_root = receipt.get("output_root")
    if not isinstance(output_root, str) or Path(output_root).expanduser().resolve() != root.resolve():
        raise ValueError(f"{label} receipt output root does not own its generated files")
    if receipt.get("total_particles") != xml_meta.get("total_particles"):
        raise ValueError(f"{label} receipt/XML total particle count differs")
    if receipt.get("fluid_particles") != xml_meta.get("fluid_count"):
        raise ValueError(f"{label} receipt/XML fluid count differs")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    source_xml = SOURCE_XML.resolve(); source_receipt = SOURCE_RECEIPT.resolve(); source_qa = SOURCE_QA.resolve()
    source_qa_receipt = SOURCE_QA_RECEIPT.resolve()
    s2_control_reference = S2_CONTROL_REFERENCE.resolve()
    static_paths = {"source_xml": source_xml, "source_receipt": source_receipt,
                    "source_native_qa": source_qa, "source_native_qa_receipt": source_qa_receipt,
                    "s2_control_reference": s2_control_reference}
    cases: dict[str, dict[str, Any]] = {}
    for label, spec in CASES.items():
        root = spec["root"].resolve()
        cases[label] = {"role": spec["role"], "case_id": spec["case_id"], "root": root,
                        "xml": root / "generated.xml", "fluid_vtk": root / "generated_Fluid.vtk",
                        "bound_vtk": root / "generated_Bound.vtk", "control": root / "CaseSloshingAccData.csv",
                        "receipt": root / "execution-receipt.json"}
    static_pre = {key: record(path) for key, path in static_paths.items()}
    output_pre: dict[str, dict[str, Any]] = {}
    for label, case in cases.items():
        for key in ("xml", "control", "fluid_vtk", "bound_vtk", "receipt"):
            output_pre[f"{label}.{key}"] = record(case[key])
    # Every existing GenCase receipt must be a completed zero-return product.
    for label, case in cases.items():
        receipt = load(case["receipt"])
        if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or int(receipt.get("returncode", 0)) != 0:
            raise ValueError(f"{label} GenCase receipt is not a completed zero-return product")
    source = parse_xml(source_xml)
    source_receipt_data = load(source_receipt)
    source_qa_data = load(source_qa)
    source_qa_receipt_data = load(source_qa_receipt)
    if source_receipt_data.get("status") != "completed" or source_receipt_data.get("returncode") != 0:
        raise ValueError("source GenCase receipt is not a completed zero-return product")
    if source_qa_receipt_data.get("status") != "completed" or source_qa_receipt_data.get("returncode") != 0:
        raise ValueError("native initial QA receipt is not completed")
    if source_qa_data.get("schema") != "ds02.f3.adaptive-spatial-native-initial-qa.v1" or source_qa_data.get("q_n") != "not_granted" or source_qa_data.get("production_approval") != "none":
        raise ValueError("native initial QA is not the expected diagnostic-only product")
    source_receipt_case_id = source_receipt_data.get("request", {}).get("case_id")
    source_receipt_exact_s2_case = source_receipt_case_id == "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
    results: dict[str, Any] = {}
    for label, case in cases.items():
        meta = parse_xml(case["xml"])
        receipt_data = load(case["receipt"])
        validate_product_receipt(label, case["case_id"], case["root"], meta, receipt_data)
        control_bound = record(case["control"])
        control_receipt = receipt_control_binding(receipt_data, control_bound, label)
        control_data = control_summary(case["control"], control_bound)
        points, fluid_meta = read_vtk_fluid(case["fluid_vtk"], meta["fluid_count"], meta["fluid_blocks"])
        bound_points, bound_meta = read_vtk_points(case["bound_vtk"])
        expected_bound = (meta["total_particles"] - meta["fluid_count"]) if meta["total_particles"] is not None else None
        if expected_bound is not None and bound_meta["point_count"] != expected_bound:
            raise ValueError(f"{label} Bound VTK count {bound_meta['point_count']} != XML fixed/bound count {expected_bound}")
        sample_relative = meta["sample_mass_kg"] / SOURCE_SAMPLE_MASS_KG - 1.0
        gate = ("PASS_DISCRETE_SAMPLE_WITHIN_ONE_PERCENT" if abs(sample_relative) <= MASS_ONE_PERCENT else
                "MARGINAL_DISCRETE_SAMPLE_ONE_TO_TWO_PERCENT" if abs(sample_relative) <= MASS_TWO_PERCENT else
                "HARDFAIL_DISCRETE_SAMPLE_OVER_TWO_PERCENT")
        results[label] = {
            "role": case["role"], "case_id": case["case_id"],
            "paths": {key: str(case[key]) for key in ("xml", "control", "fluid_vtk", "bound_vtk", "receipt")},
            "generated": {key: meta[key] for key in ("dp_m", "pointref_m", "pointmin_m", "pointmax_m", "total_particles", "fluid_blocks", "fluid_count", "massfluid_kg", "sample_mass_kg", "fluid_boxes", "bound_boxes", "operations")},
            "receipt": {key: receipt_data.get(key) for key in ("status", "returncode", "total_particles", "fluid_particles", "output_root", "bytes", "elapsed_seconds", "cpu_core_seconds")},
            "vtk_support": {"fluid": {key: value for key, value in fluid_meta.items()}, "fluid_axis_summary": axis_summary(points),
                            "fluid_box_relation": inside_relation(points, meta["fluid_boxes"][0] if meta["fluid_boxes"] else None, meta["dp_m"]),
                            "bound": bound_meta, "bound_axis_summary": axis_summary(bound_points), "finite_points": True},
            "mass_audit": {"sample_mass_kg": meta["sample_mass_kg"], "source_discrete_sample_mass_kg": SOURCE_SAMPLE_MASS_KG,
                           "relative_error_vs_source_discrete_fraction": sample_relative,
                           "relative_error_vs_source_discrete_percent": 100.0 * sample_relative,
                           "discrete_sample_gate": gate, "continuous_owner_mass_kg": "UNKNOWN_NOT_SCALARIZED",
                           "mass_rescale": False},
            "forcing_control": {"file": control_data, "receipt_input": control_receipt,
                                 "xml_basename": "CaseSloshingAccData.csv",
                                 "exact_receipt_and_file_digest_match": True},
            "control_projection": control_projection(meta),
        }
    output_post = {key: record(path) for key, path in [
        (f"{label}.{key2}", cases[label][key2])
        for label in cases for key2 in ("xml", "control", "fluid_vtk", "bound_vtk", "receipt")
    ]}
    static_post = {key: record(path) for key, path in static_paths.items()}
    if output_pre != output_post or static_pre != static_post:
        raise RuntimeError("F3 source or generated product changed during audit")
    control = {label: controls_equal(source, parse_xml(case["xml"])) for label, case in cases.items()}
    s2_control = record(s2_control_reference)
    forcing = {label: results[label]["forcing_control"]["file"] for label in cases}
    control_to_s2 = {label: forcing[label]["sha256"] == s2_control["sha256"] for label in cases}
    control_digest_groups: dict[str, list[str]] = {}
    for label, bound in forcing.items():
        control_digest_groups.setdefault(bound["sha256"], []).append(label)
    return {
        "schema": "ds02.stage2.f3-s2.initial-support-audit.v2", "status": "COMPLETED_INITIAL_SUPPORT_AUDIT_SOURCE_CLOSED",
        "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT",
        "scope": {"gen_case_rerun": False, "generated_xml_read": True, "fluid_vtk_read": True, "bound_vtk_read": True,
                  "bi4_read": False, "hdf5_read": False, "solver_started": False,
                  "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
        "source": {"current_xml": static_pre["source_xml"], "gencase_receipt": static_pre["source_receipt"], "native_initial_qa": static_pre["source_native_qa"], "native_initial_qa_receipt": static_pre["source_native_qa_receipt"], "s2_control_reference": s2_control,
                   "current_receipt_scope": {key: source_receipt_data.get(key) for key in ("status", "returncode", "total_particles", "fluid_particles", "output_root")},
                   "source_receipt_case_id": source_receipt_case_id,
                   "source_receipt_exact_s2_case": source_receipt_exact_s2_case,
                   "source_receipt_scope_note": "The bound source receipt is retained as provenance only; its case identity is checked explicitly and does not substitute for the S2 control identity.",
                   "native_qa_scope": {key: source_qa_data.get(key) for key in ("status", "fluid_count", "total_particles", "massfluid_kg", "sample_mass_kg") if key in source_qa_data},
                   "discrete_sample_mass_kg": SOURCE_SAMPLE_MASS_KG,
                   "continuous_owner_mass_kg": "UNKNOWN_NOT_SCALARIZED_BY_SOURCE_CONTRACT"},
        "cases": results,
        "control_comparison_to_current_source": control,
        "forcing_control_comparison": {"s2_reference_sha256": s2_control["sha256"], "case_matches_s2_reference": control_to_s2,
                                        "digest_groups": control_digest_groups,
                                        "original_control_is_s2_match": control_to_s2["original_dp006"],
                                        "all_three_controls_equal": len(control_digest_groups) == 1,
                                        "scope": "receipt-bound CaseSloshingAccData.csv identities; XML basename alone is insufficient"},
        "control_comparison_scope": "XML constants/parameters plus receipt-bound acceleration control identities; spatial geometry and particle counts are reported per grid and not declared identical",
        "input_integrity": {"outputs_pre": output_pre, "outputs_post": output_post, "outputs_pre_post_equal": True,
                            "static_pre": static_pre, "static_post": static_post, "static_pre_post_equal": True,
                            "deferred_vtk_scope": "parent guard must hash/stat Fluid/Bound VTK after reservation; this worker compares complete pre/post SHA/stat"},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                          "reason": "three existing GenCase products have finite XML/VTK support and receipt-bound controls; any control digest mismatch is reported rather than substituted; discrete mass gates are diagnostic, continuous owner mass and numerical qualification remain UNKNOWN"},
    }


def self_test() -> dict[str, Any]:
    # Small binary VTK fixture exercises the same offset-sensitive parser used
    # for the real files and proves wrong scalar types are rejected.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="f3-support-v1-") as td:
        p = Path(td) / "tiny.vtk"
        payload = (b"# vtk DataFile Version 3.0\ntiny\nBINARY\nDATASET POLYDATA\nPOINTS 1 float\n" +
                   struct.pack(">fff", 0.1, 0.2, 0.3) +
                   b"\nPOINT_DATA 1\nSCALARS Idp unsigned_int 1\nLOOKUP_TABLE default\n" + struct.pack(">I", 0) + b"\n")
        p.write_bytes(payload)
        points, meta = read_vtk_fluid(p, 1, [{"begin": 0, "count": 1}])
        if meta["idp_mapping"] != "GLOBAL_XML_PARTICLE_IDS" or not np.isfinite(points).all():
            raise AssertionError("binary VTK positive fixture failed")
        bad = Path(td) / "bad.vtk"; bad.write_bytes(payload.replace(b"unsigned_int", b"float"))
        try:
            read_vtk_fluid(bad, 1, [{"begin": 0, "count": 1}])
        except ValueError:
            pass
        else:
            raise AssertionError("wrong Idp type accepted")
    return {"status": "PASS", "binary_vtk_positive": True, "wrong_idp_type_rejected": True,
            "bi4_read": False, "hdf5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2)); return 0
    if args.output is None:
        parser.error("--output is required")
    report = build_report(args)
    write_new(args.output, report)
    print(json.dumps({"status": report["status"], "cases": list(report["cases"]), "output": str(args.output.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

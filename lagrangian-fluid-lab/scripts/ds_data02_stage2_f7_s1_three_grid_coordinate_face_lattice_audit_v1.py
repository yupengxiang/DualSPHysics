#!/usr/bin/env python3
"""Bounded coordinate/face/lattice audit for the three existing F7-S1 BI4 files.

ROOT146 established the coarse ``outside_owner_envelope_count=810`` from the
three frame-zero BI4 files.  This forward worker reopens those same files only
after the shared parent guard and uses the pinned F7 v2 scanner's private
``_ids`` and ``_positions`` results to identify the individual coarse rows.

The output records exact Idp, position, face bits, signed distances, selector
box membership under both closed and half-open diagnostics, four-ULP endpoint
distances, and per-axis coordinate spacing/phase distributions.  Four ULP is
a fixed representation diagnostic; it never changes the reported outside
count or any scientific gate.  The worker does not start a solver or GenCase,
and it does not open HDF5, VTK, PartOut, or later trajectory frames.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA = "ds02.stage2.f7.s1.three-grid-coordinate-face-lattice-audit.v1"
MANIFEST_SCHEMA = "ds02.stage2.f7.s1.three-grid-coordinate-face-lattice-audit.manifest.v1"
CASE_ID = "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1"
RUNTIME_ALIAS = "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE"
CURRENT_INDEX = 288
RUNG_LABELS = ("coarse", "original", "fine")
ENDPOINT_ULP_ALLOWANCE = 4
FACE_BITS = {
    "x_low": 1,
    "x_high": 2,
    "y_low": 4,
    "y_high": 8,
    "z_low": 16,
    "z_high": 32,
}
FORBIDDEN_STATIC_SUFFIXES = {".h5", ".hdf5", ".hdf", ".vtk", ".obi4", ".bi4", ".bi2", ".bi1"}


OWNER_LOW = np.asarray([-0.55, -0.35, 0.05], dtype=np.float64)
OWNER_HIGH = np.asarray([0.55, 0.35, 0.482], dtype=np.float64)
PADDLE_LOW = np.asarray([-0.07, -0.24, 0.05], dtype=np.float64)
PADDLE_HIGH = np.asarray([-0.01, 0.24, 0.53], dtype=np.float64)


class CoordinateAuditError(ValueError):
    """Raised when the source or deferred coordinate contract is not closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CoordinateAuditError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CoordinateAuditError(f"{label} is not a JSON object: {path}")
    return value


def expect(value: Any, wanted: Any, label: str) -> None:
    if value != wanted:
        raise CoordinateAuditError(f"{label}: expected {wanted!r}, got {value!r}")


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CoordinateAuditError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise CoordinateAuditError(f"{label} is not finite")
    return result


def static_record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise CoordinateAuditError(f"source is not a regular file: {path}")
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


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise CoordinateAuditError(f"refusing to overwrite output: {path}")
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


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _vec(attrs: dict[str, str], label: str) -> list[float]:
    return [finite(attrs.get(axis), f"{label}.{axis}") for axis in ("x", "y", "z")]


def _generated_summary(path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise CoordinateAuditError(f"generated XML cannot be parsed: {path}") from exc
    definition = root.find(".//geometry/definition")
    particles = root.find(".//execution/particles")
    fluid = root.find(".//execution/particles/fluid")
    position_summary = root.find(".//execution/particles/_summary/positions")
    if definition is None or particles is None or fluid is None or position_summary is None:
        raise CoordinateAuditError(f"generated XML lacks particle/position summary: {path}")
    constants = {_tag(element): element.get("value") for element in root.findall(".//execution/constants/*")}
    fluid_begin = int(fluid.get("begin", ""))
    fluid_count = int(fluid.get("count", ""))
    total = int(particles.get("np", ""))
    return {
        "dp_m": finite(definition.get("dp"), "generated dp"),
        "total_particles": total,
        "fixed_particles": int(particles.get("nbf", "")),
        "boundary_particles": int(particles.get("nb", "")),
        "fluid_begin": fluid_begin,
        "fluid_count": fluid_count,
        "fluid_end_inclusive": fluid_begin + fluid_count - 1,
        "fluid_mk": fluid.get("mk"),
        "fluid_mkfluid": fluid.get("mkfluid"),
        "massfluid_kg": finite(constants.get("massfluid"), "generated MassFluid"),
        "summary_bounds_m": {
            "low_m": _vec(position_summary.find("posmin").attrib, "generated posmin"),
            "high_m": _vec(position_summary.find("posmax").attrib, "generated posmax"),
        },
    }


def _selector_summary(path: Path, dp: float) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise CoordinateAuditError(f"Def XML cannot be parsed: {path}") from exc
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise CoordinateAuditError(f"Def XML lacks geometry definition: {path}")
    drawboxes: list[dict[str, Any]] = []
    active_mk: str | None = None
    for element in root.iter():
        tag = _tag(element)
        if tag in {"setmkbound", "setmkfluid"}:
            active_mk = element.get("mk")
        elif tag == "drawbox":
            point = element.find("point")
            size = element.find("size")
            if point is None or size is None:
                continue
            low = _vec(point.attrib, "drawbox point")
            extent = _vec(size.attrib, "drawbox size")
            high = [low[i] + extent[i] for i in range(3)]
            drawboxes.append({
                "active_mk": active_mk,
                "boxfill": (element.findtext("boxfill") or "").strip(),
                "comment": element.get("cmt"),
                "low_m": low,
                "high_m": high,
                "size_m": extent,
                "size_over_dp": [value / dp for value in extent],
                "point_over_dp": [value / dp for value in low],
                "point_phase_mod_1": [((value / dp) % 1.0) for value in low],
                "layers": (element.find("layers").get("vdp") if element.find("layers") is not None else None),
            })
    fluid_boxes = [row for row in drawboxes if row["active_mk"] == "1"]
    if not fluid_boxes:
        raise CoordinateAuditError(f"Def XML has no mk=1 fluid drawboxes: {path}")
    return {
        "definition_dp_m": finite(definition.get("dp"), "Def dp"),
        "definition_pointmin_m": _vec(definition.find("pointmin").attrib, "Def pointmin"),
        "definition_pointmax_m": _vec(definition.find("pointmax").attrib, "Def pointmax"),
        "drawboxes": drawboxes,
        "fluid_selector_boxes": fluid_boxes,
        "paddle_boxes": [row for row in drawboxes if row["active_mk"] == "2"],
        "boundary_boxes": [row for row in drawboxes if row["active_mk"] == "0"],
        "selector_union_low_m": [min(row["low_m"][i] for row in fluid_boxes) for i in range(3)],
        "selector_union_high_m": [max(row["high_m"][i] for row in fluid_boxes) for i in range(3)],
        "selector_union_is_not_owner_contract": True,
    }


def _load_refs(manifest: dict[str, Any]) -> tuple[dict[str, Path], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    entries = manifest.get("source_refs")
    if not isinstance(entries, list) or not entries:
        raise CoordinateAuditError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    stats: dict[str, dict[str, Any]] = {}
    docs: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
            raise CoordinateAuditError("malformed source reference")
        key = entry["key"]
        path = Path(entry.get("path", "")).expanduser().resolve()
        if key in paths:
            raise CoordinateAuditError(f"duplicate source key: {key}")
        if path.suffix.lower() in FORBIDDEN_STATIC_SUFFIXES:
            raise CoordinateAuditError(f"{key} is a forbidden native payload: {path}")
        actual = static_record(path)
        expected = entry.get("sha256")
        if expected not in (None, "PARENT_GUARD_COMPUTED"):
            expect(actual["sha256"], str(expected), f"{key} SHA")
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if entry.get(field) is not None:
                expect(actual[field], int(entry[field]), f"{key} {field}")
        paths[key] = path
        stats[key] = actual
        if entry.get("kind", "json") == "json":
            docs[key] = read_json(path, key)
    return paths, stats, docs


def _load_v2_worker(path: Path):
    spec = importlib.util.spec_from_file_location("f7_s1_initial_spatial_qa_v2_for_coordinate_audit", path)
    if spec is None or spec.loader is None:
        raise CoordinateAuditError(f"cannot load pinned F7 v2 worker: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _predicate_sources(cpu_path: Path, jsph_path: Path) -> dict[str, Any]:
    cpu_lines = cpu_path.read_text(encoding="utf-8").splitlines()
    jsph_lines = jsph_path.read_text(encoding="utf-8").splitlines()
    snippets = {
        "cpu_update_pos": (cpu_path, cpu_lines, 1471, 1477, ("dx<0", "dx>=MapRealSize.x")),
        "jsph_load_dcell_half_open": (jsph_path, jsph_lines, 1800, 1803, ("ps>=DomRealPosMin", "ps<DomRealPosMax")),
    }
    result: dict[str, Any] = {"compiled_binary_linkage": "UNKNOWN"}
    for name, (path, lines, start, end, needles) in snippets.items():
        text = "\n".join(lines[start - 1:end])
        result[name] = {
            "path": str(path),
            "lines": [start, end],
            "needles_present": all(needle in text for needle in needles),
            "snippet_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source_sha256": sha256_file(path),
        }
        expect(result[name]["needles_present"], True, f"{name} source predicate")
    return result


def _validate_manifest(manifest_path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    manifest = read_json(manifest_path, "coordinate face/lattice manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    expect(manifest.get("family_id"), "F7", "manifest family")
    expect(manifest.get("sentinel_id"), "F7-S1", "manifest sentinel")
    expect(manifest.get("physical_case_id"), CASE_ID, "manifest physical case")
    expect(manifest.get("current_index"), CURRENT_INDEX, "manifest CURRENT index")
    expect(manifest.get("endpoint_ulp_allowance"), ENDPOINT_ULP_ALLOWANCE, "fixed endpoint ULP allowance")
    paths, stats, docs = _load_refs(manifest)
    required = {
        "current336", "source_status", "owner_metadata", "v2_worker", "safe_decoder", "native_decoder_helper",
        "root146_proof", "root146_report", "root146_receipt", "root146_request", "cpu_source", "jsph_source",
    }
    missing = required - set(paths)
    if missing:
        raise CoordinateAuditError(f"manifest source closure missing {sorted(missing)}")
    current = docs["current336"].get("cases")
    if not isinstance(current, list) or len(current) != 336:
        raise CoordinateAuditError("CURRENT336 must contain exactly 336 cases")
    row = current[CURRENT_INDEX]
    expect(row.get("family_id"), "F7", "CURRENT288 family")
    expect(row.get("physical_case_id"), CASE_ID, "CURRENT288 physical case")
    expect(row.get("runtime_case_alias"), RUNTIME_ALIAS, "CURRENT288 runtime alias")
    status_rows = [r for r in docs["source_status"].get("sentinels", []) if isinstance(r, dict) and r.get("sentinel_id") == "F7-S1"]
    if len(status_rows) != 1:
        raise CoordinateAuditError("source status lacks unique F7-S1 row")
    owner = docs["owner_metadata"].get("physical_binding", {})
    expect(owner.get("family_id"), "F7", "owner family")
    expect(owner.get("physical_case_id"), CASE_ID, "owner case")
    expect(owner.get("initial_state", {}).get("initial_mass_total_kg"), 320.1984, "owner mass")

    proof = docs["root146_proof"]
    expect(proof.get("status"), "VERIFIED_ACTUAL_F7_THREE_GRID_PREPARED_BI4_INITIAL_IDENTITY_MASS_AND_EXACT_BOX_DIAGNOSTICS", "ROOT146 proof status")
    expect(proof.get("H5_BI4_read_by_root"), False, "ROOT146 root BI4 read")
    expect(proof.get("root_array_content_read"), False, "ROOT146 root array read")
    expect(proof.get("request"), str(paths["root146_request"]), "ROOT146 request path")
    expect(proof.get("request_sha256"), stats["root146_request"]["sha256"], "ROOT146 request SHA")
    expect(proof.get("report"), str(paths["root146_report"]), "ROOT146 report path")
    expect(proof.get("report_sha256"), stats["root146_report"]["sha256"], "ROOT146 report SHA")
    expect(proof.get("receipt"), str(paths["root146_receipt"]), "ROOT146 receipt path")
    expect(proof.get("receipt_sha256"), stats["root146_receipt"]["sha256"], "ROOT146 receipt SHA")
    report = docs["root146_report"]
    expect(report.get("status"), "COMPLETED_F7_S1_THREE_GRID_FRAME0_BI4_IDENTITY_SUPPORT_QA", "ROOT146 report status")
    expect(report.get("current_binding", {}).get("index"), CURRENT_INDEX, "ROOT146 report CURRENT index")
    expect(report.get("source_binding", {}).get("continuum_owner_mass_kg"), 320.1984, "ROOT146 report owner mass")
    receipt = docs["root146_receipt"]
    expect(receipt.get("status"), "completed", "ROOT146 receipt status")
    expect(receipt.get("returncode"), 0, "ROOT146 receipt returncode")
    report_rungs = report.get("rungs")
    if not isinstance(report_rungs, list) or [r.get("label") for r in report_rungs] != list(RUNG_LABELS):
        raise CoordinateAuditError("ROOT146 report does not contain coarse/original/fine rungs")

    rungs = manifest.get("rungs")
    if not isinstance(rungs, list) or [r.get("label") for r in rungs if isinstance(r, dict)] != list(RUNG_LABELS):
        raise CoordinateAuditError("manifest rungs must be coarse/original/fine")
    deferred = manifest.get("deferred_inputs")
    if not isinstance(deferred, dict) or set(deferred) != set(RUNG_LABELS):
        raise CoordinateAuditError("manifest must bind exactly three deferred BI4 inputs")
    for rung in rungs:
        label = rung["label"]
        for key in ("generated_xml_ref", "def_ref", "gencase_receipt_ref"):
            if rung.get(key) not in paths:
                raise CoordinateAuditError(f"{label} missing {key}")
        xml = _generated_summary(paths[rung["generated_xml_ref"]])
        expect(xml["dp_m"], finite(rung.get("dp_m"), f"{label} manifest dp"), f"{label} generated dp")
        expect(xml["fluid_mk"], "2", f"{label} generated fluid Mk")
        expect(xml["fluid_mkfluid"], "1", f"{label} generated fluid MKfluid")
        def_summary = _selector_summary(paths[rung["def_ref"]], xml["dp_m"])
        expect(def_summary["definition_dp_m"], xml["dp_m"], f"{label} Def dp")
        gencase_receipt = docs.get(rung["gencase_receipt_ref"])
        if gencase_receipt is None:
            raise CoordinateAuditError(f"{label} GenCase receipt is not JSON")
        expect(gencase_receipt.get("schema"), "ds02.execution-receipt.v1", f"{label} receipt schema")
        expect(gencase_receipt.get("status"), "completed", f"{label} receipt status")
        expect(gencase_receipt.get("returncode"), 0, f"{label} receipt returncode")
        entry = deferred.get(label)
        if not isinstance(entry, dict) or not str(entry.get("path", "")).lower().endswith(".bi4"):
            raise CoordinateAuditError(f"{label} deferred BI4 path is malformed")
        expect(entry.get("sha256"), "PARENT_GUARD_COMPUTED", f"{label} deferred hash policy")
        if int(entry.get("bytes", 0)) <= 0:
            raise CoordinateAuditError(f"{label} deferred BI4 bytes are missing")
    return manifest, paths, stats, docs


def _nextafter(value: float, direction: int, count: int = ENDPOINT_ULP_ALLOWANCE) -> float:
    result = np.float64(value)
    target = np.inf if direction > 0 else -np.inf
    for _ in range(count):
        result = np.nextafter(result, target)
    return float(result)


def _box_membership(points: np.ndarray, boxes: list[dict[str, Any]], *, closed: bool) -> list[np.ndarray]:
    result: list[np.ndarray] = []
    for box in boxes:
        low = np.asarray(box["low_m"], dtype=np.float64)
        high = np.asarray(box["high_m"], dtype=np.float64)
        if closed:
            result.append(np.all((points >= low) & (points <= high), axis=1))
        else:
            result.append(np.all((points >= low) & (points < high), axis=1))
    return result


def _distribution(values: np.ndarray, *, decimals: int | None = None) -> list[dict[str, Any]]:
    if len(values) == 0:
        return []
    prepared = np.round(values, decimals) if decimals is not None else values
    unique, counts = np.unique(prepared, return_counts=True)
    return [{"value": float(value), "count": int(count)} for value, count in zip(unique, counts)]


def _lattice_axis(values: np.ndarray, dp: float, axis: str) -> dict[str, Any]:
    unique = np.unique(values.astype(np.float64, copy=False))
    spacings = np.diff(unique)
    phase = np.mod(values.astype(np.float64, copy=False) / dp, 1.0)
    phase_round = np.round(phase, 12)
    return {
        "axis": axis,
        "coordinate_unique_count": int(len(unique)),
        "coordinate_low_m": float(unique[0]) if len(unique) else None,
        "coordinate_high_m": float(unique[-1]) if len(unique) else None,
        "spacing_unique_count": int(len(np.unique(spacings))),
        "spacing_distribution_m": _distribution(spacings),
        "spacing_min_m": float(np.min(spacings)) if len(spacings) else None,
        "spacing_max_m": float(np.max(spacings)) if len(spacings) else None,
        "declared_dp_m": dp,
        "phase_raw_unique_count": int(len(np.unique(phase))),
        "phase_distribution_round12": _distribution(phase_round),
        "phase_rounding_decimals": 12,
        "phase_interpretation": "observed coordinate/dp diagnostic; no continuous-owner or GenCase sampling claim",
    }


def _face_record(index: int, fluid_index: int, ids: np.ndarray, positions: np.ndarray, selector_closed: list[np.ndarray], selector_half: list[np.ndarray]) -> dict[str, Any]:
    point = positions[index]
    lower = point - OWNER_LOW
    upper = OWNER_HIGH - point
    signed = {
        "x": {"lower_m": float(lower[0]), "upper_m": float(upper[0])},
        "y": {"lower_m": float(lower[1]), "upper_m": float(upper[1])},
        "z": {"lower_m": float(lower[2]), "upper_m": float(upper[2])},
    }
    margins = {"x_low": float(lower[0]), "x_high": float(upper[0]), "y_low": float(lower[1]), "y_high": float(upper[1]), "z_low": float(lower[2]), "z_high": float(upper[2])}
    mask = 0
    violation: dict[str, float] = {}
    endpoint_ulp: dict[str, float] = {}
    within_4ulp: dict[str, bool] = {}
    for face, margin in margins.items():
        endpoint = OWNER_LOW["xyz".index(face[0])] if face.endswith("low") else OWNER_HIGH["xyz".index(face[0])]
        ulp = math.ulp(float(endpoint))
        endpoint_ulp[face] = ulp
        within_4ulp[face] = abs(margin) <= ENDPOINT_ULP_ALLOWANCE * ulp
        if margin < 0.0:
            mask |= FACE_BITS[face]
            violation[face] = -margin
    extended_low = np.asarray([_nextafter(float(value), -1) for value in OWNER_LOW], dtype=np.float64)
    extended_high = np.asarray([_nextafter(float(value), +1) for value in OWNER_HIGH], dtype=np.float64)
    outside_extended = bool(np.any(point < extended_low) or np.any(point > extended_high))
    closed_hits = [int(i) for i, rows in enumerate(selector_closed) if bool(rows[fluid_index])]
    half_hits = [int(i) for i, rows in enumerate(selector_half) if bool(rows[fluid_index])]
    return {
        "row_index": int(index),
        "Idp": int(ids[index]),
        "position_m": [float(value) for value in point],
        "face_bitmask": int(mask),
        "face_bits": [name for name, bit in FACE_BITS.items() if mask & bit],
        "signed_face_distances_m": signed,
        "positive_violation_distance_m": violation,
        "endpoint_ulp_m": endpoint_ulp,
        "within_fixed_4ulp": within_4ulp,
        "outside_extended_4ulp": outside_extended,
        "selector_box_indices_closed": closed_hits,
        "selector_box_indices_half_open": half_hits,
        "selector_membership_boundary_disagreement": closed_hits != half_hits,
        "inside_paddle_closed": bool(np.all((point >= PADDLE_LOW) & (point <= PADDLE_HIGH))),
        "inside_paddle_half_open": bool(np.all((point >= PADDLE_LOW) & (point < PADDLE_HIGH))),
    }


def _frame_coordinate_audit(frame: dict[str, Any], generated: dict[str, Any], selector: dict[str, Any], expected_outside: int, label: str) -> dict[str, Any]:
    ids = frame.get("_ids")
    positions = frame.get("_positions")
    if not isinstance(ids, np.ndarray) or not isinstance(positions, np.ndarray):
        raise CoordinateAuditError(f"{label} pinned v2 frame does not expose _ids/_positions")
    ids = ids.reshape(-1)
    positions = np.asarray(positions, dtype=np.float64)
    total = int(frame.get("total_particles", len(ids)))
    fluid = int(frame.get("fluid_particles", generated["fluid_count"]))
    if len(ids) != total or len(positions) != total:
        raise CoordinateAuditError(f"{label} frame arrays do not match CaseNp")
    if len(np.unique(ids)) != len(ids):
        raise CoordinateAuditError(f"{label} Idp values are not unique")
    type_values = frame.get("_types")
    if type_values is not None:
        fluid_mask = np.asarray(type_values).reshape(-1) == 3
        type_source = "native_Type_array"
    else:
        fluid_mask = ids >= total - fluid
        type_source = "header_Idp_partition_fallback"
    if int(np.count_nonzero(fluid_mask)) != fluid:
        raise CoordinateAuditError(f"{label} fluid mask does not match CaseNfluid")
    fluid_indices = np.flatnonzero(fluid_mask)
    fluid_pos = positions[fluid_mask]
    outside = np.any((fluid_pos < OWNER_LOW) | (fluid_pos > OWNER_HIGH), axis=1)
    outside_indices = fluid_indices[outside]
    outside_count = int(len(outside_indices))
    expect(outside_count, expected_outside, f"{label} exact outside count")
    selector_closed = _box_membership(fluid_pos, selector["fluid_selector_boxes"], closed=True)
    selector_half = _box_membership(fluid_pos, selector["fluid_selector_boxes"], closed=False)
    selector_closed_count = np.sum(np.stack(selector_closed, axis=1), axis=1) if selector_closed else np.zeros(len(fluid_pos), dtype=int)
    selector_half_count = np.sum(np.stack(selector_half, axis=1), axis=1) if selector_half else np.zeros(len(fluid_pos), dtype=int)
    extended_low = np.asarray([_nextafter(float(value), -1) for value in OWNER_LOW], dtype=np.float64)
    extended_high = np.asarray([_nextafter(float(value), +1) for value in OWNER_HIGH], dtype=np.float64)
    outside_extended = np.any((fluid_pos < extended_low) | (fluid_pos > extended_high), axis=1)
    outside_local_indices = np.flatnonzero(outside)
    records = [
        _face_record(int(index), int(local_index), ids, positions, selector_closed, selector_half)
        for index, local_index in zip(outside_indices, outside_local_indices)
    ]
    face_counts = {name: int(sum(name in row["face_bits"] for row in records)) for name in FACE_BITS}
    max_violation = {name: float(max((row["positive_violation_distance_m"].get(name, 0.0) for row in records), default=0.0)) for name in FACE_BITS}
    within_4ulp_counts = {name: int(sum(row["within_fixed_4ulp"][name] for row in records if name in row["face_bits"])) for name in FACE_BITS}
    all_face_within_4ulp = int(sum(bool(row["face_bits"]) and all(row["within_fixed_4ulp"][name] for name in row["face_bits"]) for row in records))
    selector_union_low = np.asarray(selector["selector_union_low_m"], dtype=np.float64)
    selector_union_high = np.asarray(selector["selector_union_high_m"], dtype=np.float64)
    return {
        "label": label,
        "dp_m": generated["dp_m"],
        "header_case_np": int(frame["header"]["CaseNp"]),
        "header_case_nfluid": int(frame["header"]["CaseNfluid"]),
        "fluid_count": fluid,
        "id_range": {"min": int(ids.min()) if len(ids) else None, "max": int(ids.max()) if len(ids) else None},
        "id_unique": True,
        "array_type_source": type_source,
        "v2_positions_dtype_after_float64_cast": str(positions.dtype),
        "native_position_dtype": "UNKNOWN_PINNED_V2_FRAME_SUMMARY_DOES_NOT_EXPORT_RECORD_DTYPE",
        "fluid_bounds_m": {"low_m": np.min(fluid_pos, axis=0).tolist(), "high_m": np.max(fluid_pos, axis=0).tolist(), "count": fluid} if fluid else None,
        "spacing_phase_by_axis": [_lattice_axis(fluid_pos[:, axis], generated["dp_m"], "xyz"[axis]) for axis in range(3)],
        "outside_owner_envelope_count": outside_count,
        "outside_extended_4ulp_count": int(np.count_nonzero(outside_extended)),
        "exact_outside_count_reproduced": True,
        "face_counts_unique_outside_ids": face_counts,
        "max_positive_violation_distance_m": max_violation,
        "within_fixed_4ulp_violation_counts": within_4ulp_counts,
        "all_violating_faces_within_fixed_4ulp_count": all_face_within_4ulp,
        "representation_allowance": {
            "endpoint_ulp_count": ENDPOINT_ULP_ALLOWANCE,
            "not_a_scientific_tolerance": True,
            "not_used_to_reclassify_outside_count": True,
            "extended_low_m": extended_low.tolist(),
            "extended_high_m": extended_high.tolist(),
        },
        "selector_vs_owner_paddle": {
            "selector_union_low_m": selector_union_low.tolist(),
            "selector_union_high_m": selector_union_high.tolist(),
            "owner_low_m": OWNER_LOW.tolist(),
            "owner_high_m": OWNER_HIGH.tolist(),
            "paddle_low_m": PADDLE_LOW.tolist(),
            "paddle_high_m": PADDLE_HIGH.tolist(),
            "selector_union_contains_owner_envelope": bool(np.all(selector_union_low <= OWNER_LOW) and np.all(selector_union_high >= OWNER_HIGH)),
            "owner_envelope_contains_selector_union": bool(np.all(OWNER_LOW <= selector_union_low) and np.all(OWNER_HIGH >= selector_union_high)),
            "selector_closed_hit_count": int(np.count_nonzero(selector_closed_count > 0)),
            "selector_half_open_hit_count": int(np.count_nonzero(selector_half_count > 0)),
            "selector_none_closed_count": int(np.count_nonzero(selector_closed_count == 0)),
            "selector_none_half_open_count": int(np.count_nonzero(selector_half_count == 0)),
            "selector_multi_closed_count": int(np.count_nonzero(selector_closed_count > 1)),
            "selector_multi_half_open_count": int(np.count_nonzero(selector_half_count > 1)),
            "selector_closed_vs_half_open_disagreement_count": int(np.count_nonzero(selector_closed_count != selector_half_count)),
            "selector_semantics": "closed and half-open memberships are both diagnostics; source implementation semantics are not inferred from this comparison",
        },
        "outside_records": records,
        "sampling_diagnostic": {
            "coordinate_phase_is_observed_fluid_position_over_dp": True,
            "closed_vs_half_open_selector_boundary_count": int(np.count_nonzero(selector_closed_count != selector_half_count)),
            "inclusive_or_cell_center_mechanism": "UNKNOWN_REQUIRES_OFFICIAL_GENERATOR_AND_PER_ID_SOURCE_JOIN",
            "outside_count_source": "actual_pinned_v2_BI4_coordinate_payload",
        },
        "read_scope": "one existing generated BI4 after parent reservation; no solver or later frame",
    }


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest, paths, stats, docs = _validate_manifest(manifest_path.expanduser().resolve())
    v2 = _load_v2_worker(paths["v2_worker"])
    scanner = v2._load_scanner({"safe_decoder": paths["safe_decoder"], "native_decoder_helper": paths["native_decoder_helper"]})
    deferred = manifest["deferred_inputs"]
    report_rungs = docs["root146_report"]["rungs"]
    outputs: list[dict[str, Any]] = []
    for rung in manifest["rungs"]:
        label = rung["label"]
        generated = _generated_summary(paths[rung["generated_xml_ref"]])
        selector = _selector_summary(paths[rung["def_ref"]], generated["dp_m"])
        entry = deferred[label]
        native_path = Path(entry["path"]).expanduser().resolve()
        if not native_path.is_file():
            raise CoordinateAuditError(f"deferred {label} BI4 is unavailable after parent reservation: {native_path}")
        expect(native_path.stat().st_size, int(entry["bytes"]), f"deferred {label} bytes")
        root_rung = next(row for row in report_rungs if row.get("label") == label)
        root_frame = root_rung.get("frame", {})
        expected_outside = int(root_frame.get("support_diagnostics", {}).get("fluid_outside_owner_envelope_count"))
        frame = v2._frame_summary(native_path, scanner, {"expected_fluid": generated["fluid_count"]}, f"coordinate_{label}_generated_bi4")
        expect(int(frame.get("header", {}).get("CaseNp")), generated["total_particles"], f"{label} CaseNp")
        expect(int(frame.get("header", {}).get("CaseNfluid")), generated["fluid_count"], f"{label} CaseNfluid")
        expect(frame.get("post_after_all_payload_reads"), True, f"{label} post hash placement")
        if not frame.get("finite_positions") or not frame.get("id_unique"):
            raise CoordinateAuditError(f"{label} BI4 positions/Idp are not finite and unique")
        if not math.isclose(float(frame["header"]["MassFluid"]), generated["massfluid_kg"], rel_tol=0.0, abs_tol=1e-12):
            raise CoordinateAuditError(f"{label} BI4 MassFluid differs from generated XML")
        audit = _frame_coordinate_audit(frame, generated, selector, expected_outside, label)
        audit["generated_xml"] = generated
        audit["source_def"] = selector
        audit["native_file"] = {
            "path": str(native_path),
            "pre": frame["pre"],
            "post": frame["post"],
            "safe_scan_sha256": frame.get("safe_scan_sha256"),
            "safe_scan_bytes": frame.get("safe_scan_bytes"),
            "array_reader_content_sha256": frame.get("array_reader_content_sha256", "NOT_COMPUTED"),
            "post_after_all_payload_reads": frame.get("post_after_all_payload_reads"),
        }
        outputs.append(audit)
        del frame
    coarse = next(row for row in outputs if row["label"] == "coarse")
    expect(coarse["outside_owner_envelope_count"], 810, "ROOT146 coarse outside count")
    predicate = _predicate_sources(paths["cpu_source"], paths["jsph_source"])
    result = {
        "schema": SCHEMA,
        "status": "COMPLETED_F7_S1_THREE_GRID_COORDINATE_FACE_LATTICE_AUDIT",
        "family_id": "F7",
        "sentinel_id": "F7-S1",
        "physical_case_id": CASE_ID,
        "current_binding": {"index": CURRENT_INDEX, "runtime_case_alias": RUNTIME_ALIAS},
        "root146_binding": {
            "report": str(paths["root146_report"]),
            "report_sha256": stats["root146_report"]["sha256"],
            "proof": str(paths["root146_proof"]),
            "proof_sha256": stats["root146_proof"]["sha256"],
            "coarse_reported_outside_count": 810,
            "coarse_actual_per_id_count": coarse["outside_owner_envelope_count"],
            "count_preserved_exact": True,
        },
        "fixed_representation_diagnostic": {
            "endpoint_ulp_allowance": ENDPOINT_ULP_ALLOWANCE,
            "meaning": "predetermined endpoint representation diagnostic only",
            "science_gate_or_tolerance": False,
            "does_not_reclassify_outside_count": True,
        },
        "rungs": outputs,
        "official_predicate_sources": predicate,
        "sampling_mechanism_scope": {
            "selector_closed_and_half_open_counts_emitted": True,
            "per_axis_spacing_and_phase_emitted": True,
            "inclusive_node_or_cell_center_mechanism": "UNKNOWN_UNTIL_OFFICIAL_GENERATOR_SOURCE_AND_PER_ID_EVIDENCE_ARE_JOINED",
            "minimal_coarse_repair": "NOT_PROPOSED; requires exact per-ID face/lattice evidence first",
        },
        "read_policy": {
            "three_existing_bi4_opened_after_parent_reservation": True,
            "all_payload_reads_bracketed_by_worker_pre_post_full_sha_stat": True,
            "later_native_frames_opened": 0,
            "hdf5_opened": False,
            "vtk_opened": False,
            "partout_opened": False,
            "solver_started": False,
            "gencase_started": False,
            "gpu_started": False,
            "old_products_immutable": True,
        },
        "qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "continuous_owner": "UNKNOWN",
            "contact": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
        },
    }
    atomic_json(output, result)
    print(json.dumps({"status": result["status"], "coarse_outside_count": coarse["outside_owner_envelope_count"], "rungs": list(RUNG_LABELS)}, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.manifest, args.output)
    except (CoordinateAuditError, OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

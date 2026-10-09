#!/usr/bin/env python3
"""Source-only diagnosis of the ROOT146 three-grid support counts.

ROOT146 already read the three existing BI4 files under guard.  This worker
consumes only that small JSON report/proof, the generated XML and Def XML, and
the official source predicate text.  It does not reopen any BI4, VTK, HDF5,
PartOut, or solver output.  It preserves the reported coarse count of 810 and
checks whether aggregate bounds can reproduce it.  A one-ULP endpoint margin
is recorded as a representation diagnostic; it is never used as a scientific
tolerance or qualification gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f7.s1.three-grid-face-distance-source-diag.v1"
MANIFEST_SCHEMA = "ds02.stage2.f7.s1.three-grid-face-distance-source-diag.manifest.v1"
CASE_ID = "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1"
CURRENT_INDEX = 288
RUNG_LABELS = ("coarse", "original", "fine")
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".hdf", ".bi4", ".obi4", ".bi2", ".bi1", ".vtk"}


class FaceDiagError(ValueError):
    """Raised when the source-only diagnostic contract is not closed."""


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
        raise FaceDiagError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FaceDiagError(f"{label} is not a JSON object: {path}")
    return value


def expect(value: Any, wanted: Any, label: str) -> None:
    if value != wanted:
        raise FaceDiagError(f"{label}: expected {wanted!r}, got {value!r}")


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise FaceDiagError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise FaceDiagError(f"{label} is not finite")
    return result


def static_record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FaceDiagError(f"source is not a regular file: {path}")
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
        raise FaceDiagError(f"refusing to overwrite output: {path}")
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
        raise FaceDiagError(f"generated XML cannot be parsed: {path}") from exc
    definition = root.find(".//geometry/definition")
    particles = root.find(".//execution/particles")
    fluid = root.find(".//execution/particles/fluid")
    pos = root.find(".//execution/particles/_summary/positions")
    if definition is None or particles is None or fluid is None or pos is None:
        raise FaceDiagError(f"generated XML lacks particle/position summary: {path}")
    constants = {_tag(e): e.get("value") for e in root.findall(".//execution/constants/*")}
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
            "low_m": _vec(pos.find("posmin").attrib, "generated posmin"),
            "high_m": _vec(pos.find("posmax").attrib, "generated posmax"),
        },
    }


def _def_selector_summary(path: Path, dp: float) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise FaceDiagError(f"Def XML cannot be parsed: {path}") from exc
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise FaceDiagError(f"Def XML lacks geometry definition: {path}")
    drawboxes: list[dict[str, Any]] = []
    active_mk: str | None = None
    for element in root.iter():
        tag = _tag(element)
        if tag == "setmkbound":
            active_mk = element.get("mk")
        elif tag == "setmkfluid":
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
        raise FaceDiagError(f"Def XML has no mk=1 fluid drawboxes: {path}")
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
        raise FaceDiagError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    stats: dict[str, dict[str, Any]] = {}
    docs: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
            raise FaceDiagError("malformed source reference")
        key = entry["key"]
        path = Path(entry.get("path", "")).expanduser().resolve()
        if key in paths:
            raise FaceDiagError(f"duplicate source key: {key}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise FaceDiagError(f"{key} is a forbidden native payload: {path}")
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


def _predicate_source(cpu_path: Path, jsph_path: Path) -> dict[str, Any]:
    cpu_lines = cpu_path.read_text(encoding="utf-8").splitlines()
    jsph_lines = jsph_path.read_text(encoding="utf-8").splitlines()
    snippets = {
        "cpu_update_pos": (cpu_path, cpu_lines, 1471, 1477, ("dx<0", "dx>=MapRealSize.x")),
        "jsph_load_dcell_half_open": (jsph_path, jsph_lines, 1800, 1803, ("ps>=DomRealPosMin", "ps<DomRealPosMax")),
    }
    result: dict[str, Any] = {"compiled_binary_linkage": "UNKNOWN"}
    for name, (path, lines, start, end, needles) in snippets.items():
        text = "\n".join(lines[start - 1:end])
        result[name] = {"lines": [start, end], "needles_present": all(needle in text for needle in needles), "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
        result[name]["path"] = str(path)
        result[name]["source_sha256"] = sha256_file(path)
        expect(result[name]["needles_present"], True, f"{name} source predicate")
    return result


def _face_distances(bounds: dict[str, Any], owner_low: list[float], owner_high: list[float]) -> dict[str, Any]:
    low = [finite(v, "fluid lower bound") for v in bounds["low_m"]]
    high = [finite(v, "fluid upper bound") for v in bounds["high_m"]]
    names = ("x", "y", "z")
    rows: dict[str, Any] = {}
    all_margins: list[float] = []
    for i, axis in enumerate(names):
        lower_margin = low[i] - owner_low[i]
        upper_margin = owner_high[i] - high[i]
        all_margins.extend((lower_margin, upper_margin))
        rows[axis] = {
            "lower_margin_m": lower_margin,
            "upper_margin_m": upper_margin,
            "lower_endpoint_ulp_m": math.ulp(owner_low[i]),
            "upper_endpoint_ulp_m": math.ulp(owner_high[i]),
            "lower_within_one_ulp": abs(lower_margin) <= math.ulp(owner_low[i]),
            "upper_within_one_ulp": abs(upper_margin) <= math.ulp(owner_high[i]),
        }
    return {
        "per_axis": rows,
        "aggregate_bounds_within_owner_envelope": min(all_margins) >= 0.0,
        "aggregate_min_signed_face_margin_m": min(all_margins),
        "aggregate_max_signed_face_violation_m": max(0.0, -min(all_margins)),
        "per_particle_max_signed_face_violation_m": "UNKNOWN_NO_ARRAYS_IN_THIS_DIAGNOSTIC",
    }


def build_report(manifest_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path, "face-distance diagnostic manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    expect(manifest.get("family_id"), "F7", "manifest family")
    expect(manifest.get("sentinel_id"), "F7-S1", "manifest sentinel")
    expect(manifest.get("physical_case_id"), CASE_ID, "manifest physical case")
    paths, stats, docs = _load_refs(manifest)
    required = {"current336", "root146_proof", "root146_report", "root146_receipt", "root143_proof", "root143_report", "cpu_source", "jsph_source"}
    missing = required - set(paths)
    if missing:
        raise FaceDiagError(f"manifest source closure missing {sorted(missing)}")
    current = docs["current336"].get("cases")
    if not isinstance(current, list) or len(current) != 336:
        raise FaceDiagError("CURRENT336 must contain 336 cases")
    expect(current[CURRENT_INDEX].get("physical_case_id"), CASE_ID, "CURRENT288 physical case")
    proof = docs["root146_proof"]
    expect(proof.get("status"), "VERIFIED_ACTUAL_F7_THREE_GRID_PREPARED_BI4_INITIAL_IDENTITY_MASS_AND_EXACT_BOX_DIAGNOSTICS", "ROOT146 status")
    expect(proof.get("H5_BI4_read_by_root"), False, "ROOT146 H5/BI4 root read")
    expect(proof.get("root_array_content_read"), False, "ROOT146 array read")
    expect(proof.get("report"), str(paths["root146_report"]), "ROOT146 report path")
    expect(proof.get("report_sha256"), stats["root146_report"]["sha256"], "ROOT146 report SHA")
    expect(proof.get("receipt"), str(paths["root146_receipt"]), "ROOT146 receipt path")
    expect(proof.get("receipt_sha256"), stats["root146_receipt"]["sha256"], "ROOT146 receipt SHA")
    report = docs["root146_report"]
    expect(report.get("current_binding", {}).get("index"), CURRENT_INDEX, "ROOT146 report current index")
    owner_mass = finite(manifest.get("continuum_owner_mass_kg"), "continuum owner mass")
    root_report_owner_mass = finite(report.get("source_binding", {}).get("continuum_owner_mass_kg"), "ROOT146 owner mass")
    expect(root_report_owner_mass, owner_mass, "ROOT146 owner mass")
    owner_low = None
    owner_high = None
    output_rows: list[dict[str, Any]] = []
    for rung in manifest.get("rungs", []):
        label = rung["label"]
        xml = _generated_summary(paths[rung["generated_xml_ref"]])
        selector = _def_selector_summary(paths[rung["def_ref"]], xml["dp_m"])
        expect(xml["dp_m"], finite(rung.get("dp_m"), f"{label} manifest dp"), f"{label} generated dp")
        expect(selector["definition_dp_m"], finite(rung.get("dp_m"), f"{label} manifest Def dp"), f"{label} Def dp")
        root_rung = next((row for row in report.get("rungs", []) if row.get("label") == label), None)
        if not isinstance(root_rung, dict):
            raise FaceDiagError(f"ROOT146 report lacks {label} rung")
        frame = root_rung.get("frame")
        if not isinstance(frame, dict):
            raise FaceDiagError(f"ROOT146 report lacks {label} frame")
        expect(root_rung.get("generated_xml_path"), str(paths[rung["generated_xml_ref"]]), f"{label} XML path")
        expect(frame.get("header", {}).get("CaseNp"), xml["total_particles"], f"{label} CaseNp")
        expect(frame.get("header", {}).get("CaseNfluid"), xml["fluid_count"], f"{label} CaseNfluid")
        expect(frame.get("fluid_particles"), xml["fluid_count"], f"{label} fluid count")
        support = frame.get("support_diagnostics", {})
        bounds = frame.get("fluid_bounds_m")
        if not isinstance(bounds, dict):
            raise FaceDiagError(f"{label} fluid bounds missing")
        if owner_low is None:
            owner_low = [finite(v, "owner lower bound") for v in support.get("declared_owner_fluid_envelope_m", [])[0]]
            owner_high = [finite(v, "owner upper bound") for v in support.get("declared_owner_fluid_envelope_m", [])[1]]
        expect(support.get("declared_owner_fluid_envelope_m"), [owner_low, owner_high], f"{label} owner envelope")
        faces = _face_distances(bounds, owner_low, owner_high)
        reported_outside = int(support.get("fluid_outside_owner_envelope_count"))
        aggregate_ok = bool(faces["aggregate_bounds_within_owner_envelope"])
        output_rows.append({
            "label": label,
            "dp_m": xml["dp_m"],
            "generated_xml": xml,
            "source_def": selector,
            "reported_root146": {
                "outside_owner_envelope_count": reported_outside,
                "fluid_bounds_m": bounds,
                "id_unique": frame.get("id_unique"),
                "id_min": frame.get("id_min"),
                "id_max": frame.get("id_max"),
                "fluid_count": frame.get("fluid_particles"),
            },
            "aggregate_face_distance": faces,
            "outside_count_reconciliation": {
                "reported_count_preserved": True,
                "aggregate_bounds_contain_all": aggregate_ok,
                "reported_count_reproducible_from_aggregate_bounds": (
                    True if reported_outside == 0 and aggregate_ok else
                    False if reported_outside == 0 and not aggregate_ok else
                    "UNKNOWN_NO_PER_PARTICLE_COUNTS"
                ),
                "per_particle_face_distances": "UNKNOWN_NO_ARRAYS_IN_THIS_DIAGNOSTIC",
                "interpretation": "Aggregate extrema cannot recover a count. A nonzero count remains exact report evidence, while its per-particle face distances and inclusive/exclusive/ULP cause require a separate bounded ID/position audit.",
            },
            "representation_allowance": {
                "endpoint_ulp_only_diagnostic": True,
                "maximum_endpoint_ulp_m": max(max(row["lower_endpoint_ulp_m"], row["upper_endpoint_ulp_m"]) for row in faces["per_axis"].values()),
                "not_a_scientific_tolerance": True,
                "not_used_to_reclassify_outside_count": True,
            },
            "source_lattice_and_selector": {
                "selector_boxes_are_declared_source_geometry_not_continuous_owner": True,
                "dp_m": xml["dp_m"],
                "fluid_selector_box_count": len(selector["fluid_selector_boxes"]),
                "selector_union_low_m": selector["selector_union_low_m"],
                "selector_union_high_m": selector["selector_union_high_m"],
                "phase_values_are_declared_point_over_dp_only": True,
                "native_lattice_phase": "UNKNOWN_NO_ARRAYS_IN_THIS_DIAGNOSTIC",
            },
        })
    if owner_low is None or owner_high is None:
        raise FaceDiagError("owner envelope was not found")
    predicate = _predicate_source(paths["cpu_source"], paths["jsph_source"])
    return {
        "schema": SCHEMA,
        "status": "SOURCE_XML_SELECTOR_AND_FACE_DISTANCE_DIAGNOSTIC_ONLY",
        "family_id": "F7",
        "sentinel_id": "F7-S1",
        "physical_case_id": CASE_ID,
        "current_index": CURRENT_INDEX,
        "root146_report": {"path": str(paths["root146_report"]), "sha256": stats["root146_report"]["sha256"]},
        "root146_proof": {"path": str(paths["root146_proof"]), "sha256": stats["root146_proof"]["sha256"], "reported_coarse_outside_count": 810},
        "rungs": output_rows,
        "official_predicate_sources": predicate,
        "mass_semantics": {"continuum_owner_mass_kg": owner_mass, "owner_rescale": False, "tolerance_widen": False, "mass_qualification": "UNKNOWN"},
        "next_control": {
            "per_particle_face_distance_required": True,
            "candidate_coarse_repair": "NOT_PROPOSED_UNTIL_PER_PARTICLE_FACE_AUDIT",
            "no_solver_or_array_read_by_this_worker": True,
            "physical_fate_contact_legal_flux_dynamics": "UNKNOWN",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
        "read_policy": {"json_xml_source_code_only": True, "bi4_opened": False, "hdf5_opened": False, "partout_opened": False, "solver_started": False, "old_products_immutable": True},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        atomic_json(args.output, build_report(args.manifest))
    except (FaceDiagError, OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

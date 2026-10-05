#!/usr/bin/env python3
"""Root-owned F4 stage-1 native input audit.

This worker is serialized for a future registered CPU audit.  It consumes one
case binding and one completed Root230 native receipt, opens the solver's
saved frame zero read-only through the pinned BI4 scanner, and writes one
metadata report.  It checks the facts needed to establish a valid native
input: actual 3-D finite positions, complete unique Idp values, exact XML
counts and UID ranges, inclusive drawbox extrema, separated drop/pool boxes,
and the native gap inside the tank.  It reports native and nominal continuum
mass independently; mass, center, lattice and precision are diagnostics and
never gates this stage-1 result.

The source package never invokes this worker.  A Root-owned CPU task must
provide the actual native receipt, frame-0 path and its producer SHA.  The
worker never writes or copies a BI4 and never reads H5/CSV/VTK data.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import mmap
import os
from pathlib import Path
import sys
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np

RAW_SUFFIXES = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv"}
HEX = set("0123456789abcdef")
SCHEMA = "ds02.f4.fresh094.stage1-native-input-qa.v1"
DECODER_REGISTERED_SHA = "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
TOL = 1e-8


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha_static(path: Path) -> str:
    path = Path(path)
    if path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f"source worker refuses scientific payload hash: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= HEX


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def canonical_xml(element: ET.Element) -> tuple[Any, ...]:
    """Ignore GenCase whitespace while preserving tags, attributes and order."""
    return (element.tag, tuple(sorted(element.attrib.items())), tuple(canonical_xml(child) for child in element))


def parse_xml(binding: dict[str, Any]) -> dict[str, Any]:
    xml_path = require_file(Path(binding["generated_xml"]["path"]))
    xml_expected_sha = binding["generated_xml"]["sha256"]
    if sha_static(xml_path) != xml_expected_sha:
        raise ValueError("generated XML SHA changed")
    root = ET.parse(xml_path).getroot()
    particles = root.find(".//execution/particles")
    if particles is None:
        raise ValueError("generated XML lacks execution/particles")
    counts = {
        "total": int(particles.attrib["np"]),
        "fixed": int(particles.attrib["nb"]),
    }
    blocks = []
    for element in particles.findall("fluid"):
        blocks.append({
            "mkfluid": int(element.attrib["mkfluid"]),
            "mk": int(element.attrib["mk"]),
            "begin": int(element.attrib["begin"]),
            "count": int(element.attrib["count"]),
        })
    counts["fluid"] = sum(row["count"] for row in blocks)
    if counts["total"] != counts["fixed"] + counts["fluid"]:
        raise ValueError("generated XML particle counts do not close")
    if counts["total"] != int(binding["expected"]["total_particles"]):
        raise ValueError("generated XML total differs from actual GenCase evidence")
    if counts["fixed"] != int(binding["expected"]["fixed_particles"]):
        raise ValueError("generated XML fixed count differs from actual GenCase evidence")
    if counts["fluid"] != int(binding["expected"]["fluid_particles"]):
        raise ValueError("generated XML fluid count differs from actual GenCase evidence")
    data2d = root.find(".//execution/constants/data2d")
    if data2d is None:
        data2d = root.find(".//data2d")
    if data2d is None or str(data2d.attrib.get("value", "")).lower() != "false":
        raise ValueError("generated XML is not explicit true 3-D")
    parameters = {item.attrib.get("key"): item.attrib.get("value") for item in root.findall(".//execution/parameters/parameter")}
    if parameters.get("TimeMax") != "1.2" or parameters.get("TimeOut") != "0.001":
        raise ValueError("generated XML time recipe drift")
    if abs(float(root.find(".//geometry/definition").attrib["dp"]) - 0.01) > 1e-12:
        raise ValueError("generated XML dp drift")
    by_mkfluid = {row["mkfluid"]: row for row in blocks}
    sources = {}
    for name in ("drop", "pool"):
        source = binding["expected"]["sources"][name]
        mkfluid = int(source["mkfluid"])
        if mkfluid not in by_mkfluid:
            raise ValueError(f"XML lacks {name} mkfluid block")
        row = by_mkfluid[mkfluid]
        if row["count"] != int(source["count"]):
            raise ValueError(f"XML {name} count differs from registered UID block")
        sources[name] = {**source, "xml_block": row}
    if sum(row["count"] for row in sources.values()) != counts["fluid"]:
        raise ValueError("registered source UID blocks do not close")
    return {"path": str(xml_path), "sha256": xml_expected_sha, "counts": counts, "sources": sources, "root": root}


def verify_static_invariants(binding: dict[str, Any], xml: dict[str, Any]) -> dict[str, Any]:
    source_path = require_file(Path(binding["source_definition"]["path"]))
    if sha_static(source_path) != binding["source_definition"]["sha256"]:
        raise ValueError("source Definition SHA changed")
    source_root = ET.parse(source_path).getroot()
    generated_root = xml["root"]
    same_constants = canonical_xml(source_root.find("casedef/constantsdef")) == canonical_xml(generated_root.find("casedef/constantsdef"))
    same_initials = canonical_xml(source_root.find("casedef/initials")) == canonical_xml(generated_root.find("casedef/initials"))
    source_params = {x.attrib.get("key"): x.attrib.get("value") for x in source_root.findall("./execution/parameters/parameter")}
    generated_params = {x.attrib.get("key"): x.attrib.get("value") for x in generated_root.findall("./execution/parameters/parameter")}
    same_parameters = source_params == generated_params
    same_geometry_definition = canonical_xml(source_root.find("casedef/geometry/definition")) == canonical_xml(generated_root.find("casedef/geometry/definition"))
    same_geometry_commands = canonical_xml(source_root.find("casedef/geometry/commands/mainlist")) == canonical_xml(generated_root.find("casedef/geometry/commands/mainlist"))
    report_path = require_file(Path(binding["prepared_report"]["path"]))
    report = load_json(report_path)
    if sha_static(report_path) != binding["prepared_report"]["sha256"]:
        raise ValueError("prepared report SHA changed")
    receipt_path = require_file(Path(binding["gencase_receipt"]["path"]))
    receipt = load_json(receipt_path)
    if sha_static(receipt_path) != binding["gencase_receipt"]["sha256"]:
        raise ValueError("GenCase receipt SHA changed")
    if receipt.get("status") not in {"completed", "completed/0"} or receipt.get("returncode") != 0:
        raise ValueError("GenCase source receipt is not completed/0")
    if receipt.get("solver_dimension_from_gencase") != 3:
        raise ValueError("GenCase source receipt is not 3-D")
    return {
        "source_definition_sha256": binding["source_definition"]["sha256"],
        "gencase_receipt_sha256": binding["gencase_receipt"]["sha256"],
        "prepared_report_sha256": binding["prepared_report"]["sha256"],
        "same_constants": same_constants,
        "same_initials": same_initials,
        "same_execution_parameters": same_parameters,
        "same_geometry_definition": same_geometry_definition,
        "same_geometry_commands": same_geometry_commands,
        "source_bytes_unchanged": all((same_constants, same_initials, same_parameters, same_geometry_definition, same_geometry_commands)),
        "raw_receipt_unchanged": True,
        "prepared_report_actual_total": report.get("actual_total_particles"),
        "prepared_report_actual_data2d": report.get("actual_generated_constants", {}).get("data2d", {}).get("value"),
    }


def load_decoder(path: Path):
    if path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError("decoder cannot be a scientific payload")
    spec = importlib.util.spec_from_file_location("ds02_f4_fresh094_safe_decoder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import decoder: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.MAX_RAW_BYTES = 2**40
    module.MAX_ARRAY_COUNT = 10_000_000
    module.MAX_ARRAY_BYTES = 2**40
    module.MAX_ARRAY_BYTES_TOTAL = 2**40
    module.MAX_OUTPUT_BYTES = 2**40
    return module


def actual_native_audit(binding: dict[str, Any], xml: dict[str, Any], receipt_path: Path, frame_path: Path, expected_frame_sha: str, decoder_path: Path) -> dict[str, Any]:
    receipt = load_json(receipt_path)
    if receipt.get("status") not in {"completed", "completed/0"} or receipt.get("returncode") != 0:
        raise ValueError("native execution receipt is not completed/0")
    native_attempt = binding.get("native_attempt_id")
    if native_attempt and receipt.get("attempt_id") not in {None, native_attempt} and receipt.get("request", {}).get("attempt_id") not in {None, native_attempt}:
        raise ValueError("native receipt attempt identity drift")
    if not valid_sha(expected_frame_sha):
        raise ValueError("registered native frame-0 producer SHA is required")
    decoder = load_decoder(decoder_path)
    if sha_static(decoder_path) != DECODER_REGISTERED_SHA:
        raise ValueError("registered safe BI4 decoder SHA drift")
    flags = getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(frame_path, os.O_RDONLY | flags)
    mapped = None
    try:
        actual_before = decoder._hash_fd(fd, frame_path.stat().st_size)
        if actual_before != expected_frame_sha:
            raise ValueError("native frame-0 SHA differs from registered producer SHA")
        scan = decoder.scan_bi4_fd(fd, expected_frame_sha)
        root_values = {item.name: item.value for item in scan.root.values}
        if not scan.root.children:
            raise ValueError("native BI4 lacks particle item")
        particle_name = scan.root.children[0].name
        arrays = {item.name: item for item in scan.arrays if item.item_path[-1] == particle_name}
        for name in ("Posd", "Idp"):
            if name not in arrays:
                raise ValueError(f"native BI4 lacks required {name} array")
        total_expected = int(binding["expected"]["total_particles"])
        if int(root_values.get("CaseNp", -1)) != total_expected:
            raise ValueError("native CaseNp differs from actual GenCase total")
        if int(root_values.get("CaseNfluid", -1)) != int(binding["expected"]["fluid_particles"]):
            raise ValueError("native CaseNfluid differs from actual GenCase fluid count")
        if int(root_values.get("CaseNfixed", -1)) != int(binding["expected"]["fixed_particles"]):
            raise ValueError("native CaseNfixed differs from actual GenCase fixed count")
        if root_values.get("Data2d") is not False:
            raise ValueError("native BI4 is not 3-D")
        pos_record = arrays["Posd"]
        id_record = arrays["Idp"]
        if pos_record.type_code != 23 or pos_record.count != total_expected or id_record.count != total_expected:
            raise ValueError("native Posd/Idp shape or type does not match actual total")
        mapped = mmap.mmap(fd, 0, access=mmap.ACCESS_READ)
        # The scanner represents a BI4 ``double3`` as the format string
        # ``<ddd``; NumPy needs its scalar component dtype plus the explicit
        # (N,3) shape used below.
        if pos_record.type_code != 23:
            raise ValueError("native Posd is not double3")
        pos = np.ndarray((total_expected, 3), dtype=np.dtype("<f8"), buffer=mapped, offset=pos_record.offset)
        ids = np.ndarray((total_expected,), dtype=np.dtype(decoder.TYPE_INFO[id_record.type_code][1]), buffer=mapped, offset=id_record.offset)
        ids_i64 = ids.astype(np.int64, copy=False)
        finite = bool(np.isfinite(pos).all())
        unique_complete = bool(np.array_equal(np.sort(ids_i64), np.arange(total_expected, dtype=np.int64)))
        fluid_mask = ids_i64 >= int(binding["expected"]["fixed_particles"])
        fluid_pos = pos[fluid_mask]
        all_axes_levels = [int(np.unique(fluid_pos[:, axis]).size) > 1 for axis in range(3)]
        source_rows: dict[str, Any] = {}
        for name in ("drop", "pool"):
            source = xml["sources"][name]
            block = source["xml_block"]
            mask = (ids_i64 >= int(block["begin"])) & (ids_i64 < int(block["begin"] + block["count"]))
            cloud = pos[mask]
            if cloud.shape[0] != int(block["count"]):
                raise ValueError(f"{name} native source UID count mismatch")
            low = np.asarray(source["low_m"], dtype=float)
            high = low + np.asarray(source["size_m"], dtype=float)
            actual_low = np.min(cloud, axis=0)
            actual_high = np.max(cloud, axis=0)
            source_rows[name] = {
                "fluid_count": int(cloud.shape[0]),
                "uid_begin": int(block["begin"]),
                "uid_end_exclusive": int(block["begin"] + block["count"]),
                "declared_drawbox_low_m": low.tolist(),
                "declared_drawbox_high_m": high.tolist(),
                "actual_inclusive_bounds_m": [actual_low.tolist(), actual_high.tolist()],
                "checks": {
                    "exact_registered_uid_block": int(cloud.shape[0]) == int(block["count"]),
                    "finite_positions": bool(np.isfinite(cloud).all()),
                    "inside_declared_drawbox_inclusive": bool(np.all(actual_low >= low - TOL) and np.all(actual_high <= high + TOL)),
                    "declared_drawbox_inclusive_extrema_match": bool(np.allclose(actual_low, low, rtol=0.0, atol=TOL) and np.allclose(actual_high, high, rtol=0.0, atol=TOL)),
                    "positive_population": bool(cloud.shape[0] > 0),
                },
            }
        drop_low, drop_high = (np.asarray(source_rows["drop"]["actual_inclusive_bounds_m"][i], dtype=float) for i in (0, 1))
        pool_low, pool_high = (np.asarray(source_rows["pool"]["actual_inclusive_bounds_m"][i], dtype=float) for i in (0, 1))
        separations = [("x", max(float(pool_low[0] - drop_high[0]), float(drop_low[0] - pool_high[0]))), ("y", max(float(pool_low[1] - drop_high[1]), float(drop_low[1] - pool_high[1]))), ("z", max(float(pool_low[2] - drop_high[2]), float(drop_low[2] - pool_high[2])))]
        gap_axis, measured_gap = max(separations, key=lambda item: item[1])
        tank = binding["expected"]["tank"]
        tank_low = np.asarray(tank["low_m"], dtype=float)
        tank_high = tank_low + np.asarray(tank["size_m"], dtype=float)
        both_inside_tank = bool(np.all(drop_low >= tank_low - TOL) and np.all(drop_high <= tank_high + TOL) and np.all(pool_low >= tank_low - TOL) and np.all(pool_high <= tank_high + TOL))
        no_overlap = bool(measured_gap >= -TOL)
        massfluid = root_values.get("MassFluid")
        density = float(binding["expected"]["density_kg_m3"])
        nominal = {name: float(np.prod(np.asarray(binding["expected"]["sources"][name]["size_m"], dtype=float)) * density) for name in ("drop", "pool")}
        native_mass = None if massfluid is None else {name: float(source_rows[name]["fluid_count"] * float(massfluid)) for name in ("drop", "pool")}
        mass_report = {"native_mass_by_source_kg": native_mass, "nominal_continuum_mass_by_source_kg": nominal, "difference_kg": None if native_mass is None else {name: native_mass[name] - nominal[name] for name in nominal}, "mass_rescaled": False, "is_stage1_gate": False, "status": "diagnostic_only"}
        checks = {
            "native_receipt_completed0": True,
            "native_3d": root_values.get("Data2d") is False and pos_record.type_code == 23,
            "finite_positions": finite,
            "unique_complete_Idp": unique_complete,
            "exact_actual_total_count": int(root_values["CaseNp"]) == total_expected,
            "exact_actual_fixed_count": int(root_values["CaseNfixed"]) == int(binding["expected"]["fixed_particles"]),
            "exact_actual_fluid_count": int(root_values["CaseNfluid"]) == int(binding["expected"]["fluid_particles"]),
            "source_uid_blocks_exact": all(row["checks"]["exact_registered_uid_block"] for row in source_rows.values()),
            "all_fluid_axes_have_multiple_levels": all(all_axes_levels),
            "drop_pool_nonoverlap": no_overlap,
            "native_gap_inside_tank": bool(no_overlap and measured_gap > TOL and both_inside_tank),
            "declared_source_extrema_are_inclusive": all(row["checks"]["declared_drawbox_inclusive_extrema_match"] for row in source_rows.values()),
            "source_bytes_and_recipe_invariant": True,
        }
        actual_after = decoder._hash_fd(fd, frame_path.stat().st_size)
        if actual_after != actual_before:
            raise ValueError("native frame-0 bytes changed during read-only audit")
        return {
            "native_frame0_sha256": actual_before,
            "native_frame0_bytes_unchanged": actual_after == actual_before,
            "native_root_values": {key: root_values.get(key) for key in ("CaseNp", "CaseNfixed", "CaseNfluid", "Data2d", "Dp", "MassFluid")},
            "array_contract": {name: {"type_code": arrays[name].type_code, "count": arrays[name].count, "offset": arrays[name].offset, "byte_count": arrays[name].byte_count} for name in ("Posd", "Idp")},
            "source_rows": source_rows,
            "all_fluid_axes_have_multiple_levels": all_axes_levels,
            "gap": {"axis": gap_axis, "measured_inclusive_surface_gap_m": float(measured_gap), "declared_source_gap_m": float(binding["expected"]["parameters"]["gap_m"]), "interpretation": "Measured native inclusive extrema are reported separately from the source parameter; no source gap is relabelled."},
            "inside_tank": both_inside_tank,
            "mass": mass_report,
            "checks": checks,
            "pass": all(checks.values()),
            "arrays_observed_by_registered_job": ["Posd", "Idp"],
            "raw_marker_arrays_required": False,
            "saved_frame0_velocity_audit": {"status": "future_separate_audit", "pass": None, "report": None, "sha256": None},
        }
    finally:
        if mapped is not None:
            mapped.close()
        os.close(fd)


def run(args: argparse.Namespace) -> int:
    binding = load_json(require_file(args.binding))
    if binding.get("schema") != "ds02.f4.fresh094.stage1-native-input-binding.v1":
        raise ValueError("fresh094 binding schema mismatch")
    if binding.get("source_only") is not True or binding.get("execution_allowed") is not False:
        raise ValueError("fresh094 worker must be disabled source-only")
    xml = parse_xml(binding)
    invariant = verify_static_invariants(binding, xml)
    receipt_path = require_file(args.native_receipt)
    frame_path = require_file(args.native_frame0)
    result = actual_native_audit(binding, xml, receipt_path, frame_path, args.native_frame0_sha256, Path(binding["decoder"]["path"]))
    report = {"schema": SCHEMA, "case_id": binding["case_id"], "physical_case_id": binding["physical_case_id"], "physical_condition_sha256": binding["physical_condition_sha256"], "status": "completed", "returncode": 0, "source_gencase": {"receipt": binding["gencase_receipt"], "prepared_report": binding["prepared_report"], "generated_xml": binding["generated_xml"], "generated_bi4": {"path": binding["generated_bi4"]["path"], "producer_sha256": binding["generated_bi4"]["producer_sha256"], "read_by_source": False}}, "native": {"execution_receipt": str(receipt_path), "execution_receipt_sha256": sha_static(receipt_path), "frame0": str(frame_path), "frame0_producer_sha256": args.native_frame0_sha256, "frame0_read_only": True}, "static_invariants": invariant, "audit": result, "strict_root237_diagnostic": binding.get("strict_root237_diagnostic"), "precision_status": "not_accepted", "q_n_status": "not_assessed", "production_approval": "none", "independent_case_count_increment": 0, "arrays_read_by_source": False, "claim_boundary": "Stage-1 native input structure only. Native-vs-continuum mass, inclusive surface gap, strict center/lattice diagnostics and separate saved-frame0 velocity audit are reported without rescaling or precision/Q-N promotion."}
    dump_json(args.output / "native-input-qa.json", report)
    return 0 if result["pass"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--native-receipt", required=True, type=Path)
    parser.add_argument("--native-frame0", required=True, type=Path)
    parser.add_argument("--native-frame0-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as error:
        print(json.dumps({"schema": SCHEMA, "status": "failed", "error_type": type(error).__name__, "error": str(error), "parent_native_receipt_preserved": True, "arrays_read_by_source": False}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

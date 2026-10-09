#!/usr/bin/env python3
"""Run a bounded source-only owner/control preflight for F2-S2, F3-S1 and F5-S1.

The preflight binds the exact source XML, the completed solver receipt, and any
small motion file recorded by the source audit.  It recomputes the declared
axis-aligned fluid-box volume and density mass from the source XML and checks
those values against the independent small geometry-bounds report.  It does
not read a BI4, VTK, HDF5, native Part file, or generated particle payload.

The declared-box result is deliberately kept separate from a continuous owner
and from a GenCase sample.  In particular, F2-S2's 18.876 kg is reported as a
source primitive only; it is never imported from the F2-S1 owner contract.
Support, overlap, boundary ownership, effective particle mass, and all QI/QN/QE
remain UNKNOWN until a parent-guarded generated-product audit supplies them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from typing import Any


HERE = Path(__file__).resolve().parent
SCHEMA = "ds02.stage2.three-sentinel.source-owner-control-preflight.v1"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel.source-owner-control-manifest.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
MAX_SMALL_BYTES = 16 * 1024 * 1024
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
FORBIDDEN_SUFFIXES = {".bi4", ".vtk", ".h5", ".hdf5", ".part"}


class PreflightFailure(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_bytes(path: Path, label: str) -> tuple[bytes, dict[str, int], dict[str, int]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise PreflightFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise PreflightFailure(f"{label} exceeds bounded source cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise PreflightFailure(f"{label} changed during bounded read: {path}")
    return raw, before, after


def _record(path: Path, label: str, *, parse_json: bool = False) -> tuple[Any, dict[str, Any]]:
    raw, before, after = _read_bytes(path, label)
    record = {
        "path": str(_absolute(path)),
        "sha256": _sha256(raw),
        "stat_before": before,
        "stat_after": after,
        "payload_read_by_worker": True,
        "scope": "bounded_small_source_metadata",
    }
    if not parse_json:
        return raw, record
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreflightFailure(f"{label} is not bounded JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise PreflightFailure(f"{label} must be a JSON object")
    return value, record


def _bound_record(binding: dict[str, Any], label: str, *, parse_json: bool = False) -> tuple[Any, dict[str, Any]]:
    if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
        raise PreflightFailure(f"{label} lacks a path binding")
    expected_sha = binding.get("sha256")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise PreflightFailure(f"{label} lacks a concrete SHA-256")
    value, actual = _record(Path(binding["path"]), label, parse_json=parse_json)
    if actual["sha256"] != expected_sha.lower():
        raise PreflightFailure(f"{label} SHA changed since source binding")
    expected_stat = binding.get("stat_after", binding.get("stat"))
    if isinstance(expected_stat, dict):
        for key in ("device", "inode", "bytes", "mtime_ns", "ctime_ns"):
            if key in expected_stat and int(expected_stat[key]) != int(actual["stat_after"][key]):
                raise PreflightFailure(f"{label} {key} changed since source binding")
    return value, actual


def _tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()


def _number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PreflightFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise PreflightFailure(f"{label} is non-finite")
    return result


def _vec(node: ET.Element, label: str) -> list[float]:
    values = []
    for axis in ("x", "y", "z"):
        if axis not in node.attrib:
            raise PreflightFailure(f"{label} lacks {axis}")
        values.append(_number(node.attrib[axis], f"{label}.{axis}"))
    return values


def _parameter_values(root: ET.Element, key: str) -> list[str]:
    return [node.attrib["value"] for node in root.iter() if _tag(node) == "parameter" and node.attrib.get("key") == key and "value" in node.attrib]


def _first_value(root: ET.Element, name: str, attribute: str = "value") -> str | None:
    for node in root.iter():
        if _tag(node) == name and attribute in node.attrib:
            return node.attrib[attribute]
    return None


def _parse_source_xml(raw: bytes, sentinel: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PreflightFailure(f"{sentinel} source XML is not well formed: {exc}") from exc
    dp_raw = _first_value(root, "definition", "dp")
    if dp_raw is None:
        raise PreflightFailure(f"{sentinel} source XML lacks definition@dp")
    dp = _number(dp_raw, f"{sentinel}.dp")
    if dp <= 0:
        raise PreflightFailure(f"{sentinel} dp must be positive")
    pointref = None
    pointrefs = [node for node in root.iter() if _tag(node) == "pointref"]
    if pointrefs:
        pointref = _vec(pointrefs[0], f"{sentinel}.pointref")
    active_mk: str | None = None
    fluids: list[dict[str, Any]] = []
    for node in root.iter():
        name = _tag(node)
        if name == "setmkfluid":
            active_mk = str(node.attrib.get("mk", "UNKNOWN"))
        elif name == "setmkbound":
            active_mk = None
        elif name == "drawbox" and active_mk is not None:
            point = next((child for child in node if _tag(child) == "point"), None)
            size = next((child for child in node if _tag(child) == "size"), None)
            if point is None or size is None:
                raise PreflightFailure(f"{sentinel} fluid drawbox lacks point/size")
            point_m = _vec(point, f"{sentinel}.fluid[{len(fluids)}].point")
            size_m = _vec(size, f"{sentinel}.fluid[{len(fluids)}].size")
            if any(value <= 0 for value in size_m):
                raise PreflightFailure(f"{sentinel} fluid drawbox has non-positive size")
            fluids.append({
                "mkfluid": active_mk,
                "point_m": point_m,
                "size_m": size_m,
                "volume_m3": size_m[0] * size_m[1] * size_m[2],
            })
    if not fluids:
        raise PreflightFailure(f"{sentinel} source XML has no fluid drawbox")
    cfl_values = [_number(value, f"{sentinel}.cflnumber") for value in [
        node.attrib.get("value") for node in root.iter() if _tag(node) == "cflnumber" and "value" in node.attrib
    ]]
    controls = {
        "cflnumber": cfl_values,
        "CoefDtMin": [_number(value, f"{sentinel}.CoefDtMin") for value in _parameter_values(root, "CoefDtMin")],
        "DtIni": [_number(value, f"{sentinel}.DtIni") for value in _parameter_values(root, "DtIni")],
        "DtMin": [_number(value, f"{sentinel}.DtMin") for value in _parameter_values(root, "DtMin")],
        "TimeMax": [_number(value, f"{sentinel}.TimeMax") for value in _parameter_values(root, "TimeMax")],
        "TimeOut": [_number(value, f"{sentinel}.TimeOut") for value in _parameter_values(root, "TimeOut")],
        "Boundary": _parameter_values(root, "Boundary"),
        "SlipMode": _parameter_values(root, "SlipMode"),
        "StepAlgorithm": _parameter_values(root, "StepAlgorithm"),
    }
    file_refs = [node.attrib.get("name") or node.attrib.get("file") for node in root.iter() if _tag(node) in {"file", "geometryfile", "vtkfile"}]
    return {
        "definition": {"dp_m": dp, "pointref_m": pointref},
        "fluid_drawboxes": fluids,
        "declared_primitive_volume_m3": sum(item["volume_m3"] for item in fluids),
        "controls": controls,
        "file_refs": [value for value in file_refs if value],
        "setshapemode_present": any(_tag(node) == "setshapemode" for node in root.iter()),
    }


def _close(a: float, b: float, *, rel: float = 1e-11, abs_tol: float = 1e-12) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)


def _audit_row(audit: dict[str, Any], sentinel: str) -> dict[str, Any]:
    rows = audit.get("sources")
    if not isinstance(rows, list):
        raise PreflightFailure("source audit lacks sources list")
    matches = [row for row in rows if isinstance(row, dict) and row.get("sentinel_id") == sentinel]
    if len(matches) != 1:
        raise PreflightFailure(f"source audit must contain exactly one {sentinel} row")
    return matches[0]


def _bounds_row(bounds: dict[str, Any], sentinel: str) -> dict[str, Any]:
    rows = bounds.get("sources")
    if not isinstance(rows, list):
        raise PreflightFailure("geometry bounds report lacks sources list")
    matches = [row for row in rows if isinstance(row, dict) and row.get("sentinel_id") == sentinel]
    if len(matches) != 1:
        raise PreflightFailure(f"geometry bounds must contain exactly one {sentinel} row")
    return matches[0]


def _motion_binding(row: dict[str, Any]) -> dict[str, Any] | None:
    resolution = row.get("motion_file_resolution") or {}
    refs = resolution.get("references") if isinstance(resolution, dict) else None
    if not isinstance(refs, list):
        return None
    for item in refs:
        for candidate in item.get("candidates", []) if isinstance(item, dict) else []:
            if isinstance(candidate, dict) and candidate.get("path") and candidate.get("actual_sha256"):
                path = Path(str(candidate["path"]))
                if path.is_file() and path.suffix.lower() not in FORBIDDEN_SUFFIXES:
                    return {"path": str(path), "sha256": str(candidate["actual_sha256"]), "bytes": int(candidate.get("bytes", -1))}
    return None


def _validate_receipt(row: dict[str, Any], receipt: dict[str, Any], sentinel: str) -> dict[str, Any]:
    source_control = row.get("source_solver_control") or {}
    if source_control.get("status") not in (None, "completed"):
        raise PreflightFailure(f"{sentinel} source audit does not identify completed solver receipt")
    if source_control.get("returncode") not in (None, 0):
        raise PreflightFailure(f"{sentinel} source audit identifies nonzero solver returncode")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise PreflightFailure(f"{sentinel} receipt is not completed with returncode 0")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise PreflightFailure(f"{sentinel} receipt has no request object")
    if request.get("family_id") != row.get("family_id"):
        raise PreflightFailure(f"{sentinel} receipt family identity mismatch")
    request_physical = request.get("physical_case_id")
    if request_physical not in (None, row.get("physical_case_id")):
        raise PreflightFailure(f"{sentinel} receipt physical_case_id mismatch")
    command = request.get("command")
    if not isinstance(command, list) or not command:
        raise PreflightFailure(f"{sentinel} receipt request has no command")
    return {
        "status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "case_id": request.get("case_id"),
        "physical_case_id": request.get("physical_case_id"),
        "source_row_physical_case_id": row.get("physical_case_id"),
        "physical_case_join": "PASS" if request_physical == row.get("physical_case_id") else "UNKNOWN_RECEIPT_FIELD_ABSENT",
        "attempt_id": request.get("attempt_id"),
        "command": command,
        "source_request_sha256": receipt.get("request_sha256"),
        "tmax_s": source_control.get("tmax_s"),
        "tout_s": source_control.get("tout_s"),
    }


def _compare_drawboxes(source: dict[str, Any], bounds: dict[str, Any], sentinel: str) -> dict[str, Any]:
    expected = bounds.get("fluid_drawboxes")
    if not isinstance(expected, list) or len(expected) != len(source["fluid_drawboxes"]):
        raise PreflightFailure(f"{sentinel} source/audit fluid drawbox count mismatch")
    rows = []
    for index, (actual, declared) in enumerate(zip(source["fluid_drawboxes"], expected)):
        point = declared.get("point_m")
        size = declared.get("size_m")
        if not isinstance(point, list) or not isinstance(size, list) or len(point) != 3 or len(size) != 3:
            raise PreflightFailure(f"{sentinel} bounds drawbox {index} malformed")
        same = all(_close(float(actual["point_m"][axis]), float(point[axis])) and _close(float(actual["size_m"][axis]), float(size[axis])) for axis in range(3))
        if not same:
            raise PreflightFailure(f"{sentinel} source/audit drawbox mismatch at {index}")
        rows.append({"index": index, "mkfluid": actual["mkfluid"], "point_m": actual["point_m"], "size_m": actual["size_m"], "volume_m3": actual["volume_m3"]})
    return {"count": len(rows), "rows": rows, "source_and_bounds_drawboxes": "MATCH"}


def _case(audit: dict[str, Any], bounds: dict[str, Any], sentinel: str) -> dict[str, Any]:
    row = _audit_row(audit, sentinel)
    bound = _bounds_row(bounds, sentinel)
    source_xml_binding = row.get("source_xml")
    receipt_binding = (row.get("source_solver_control") or {}).get("receipt")
    if not isinstance(source_xml_binding, dict) or not isinstance(receipt_binding, dict):
        raise PreflightFailure(f"{sentinel} source XML/receipt bindings are incomplete")
    source_raw, source_actual = _bound_record(source_xml_binding, f"{sentinel} source XML")
    source = _parse_source_xml(source_raw, sentinel)
    receipt, receipt_actual = _bound_record(receipt_binding, f"{sentinel} completed solver receipt", parse_json=True)
    receipt_summary = _validate_receipt(row, receipt, sentinel)
    drawboxes = _compare_drawboxes(source, bound, sentinel)
    density = _number(bound.get("rhop0_kg_m3"), f"{sentinel}.rhop0_kg_m3")
    volume = source["declared_primitive_volume_m3"]
    declared_mass = volume * density
    geometry = bound.get("total_declared_box_geometry") or {}
    report_volume = _number(geometry.get("primitive_sum_volume_m3"), f"{sentinel}.reported primitive volume")
    report_mass = _number((geometry.get("declared_mass_bounds_before_particle_crop_kg") or {}).get("lower_kg"), f"{sentinel}.reported primitive mass")
    if not _close(volume, report_volume) or not _close(declared_mass, report_mass):
        raise PreflightFailure(f"{sentinel} source XML primitive scalar does not match bounds report")
    motion_binding = _motion_binding(row)
    motion_actual = None
    if motion_binding is not None:
        motion_actual = _bound_record(motion_binding, f"{sentinel} motion file", parse_json=False)[1]
        if motion_actual["sha256"] != motion_binding["sha256"]:
            raise PreflightFailure(f"{sentinel} motion SHA differs from source audit")
        if motion_binding["bytes"] >= 0 and motion_actual["stat_after"]["bytes"] != motion_binding["bytes"]:
            raise PreflightFailure(f"{sentinel} motion byte count differs from source audit")
    owner_status = {
        "status": "UNVERIFIED_SOURCE_CONTINUOUS_OWNER",
        "owner_mass_kg": "UNKNOWN",
        "reason": "declared primitive and existing sample mass are not a continuous-owner proof",
    }
    if sentinel == "F2-S2":
        owner_status = {
            "status": "UNVERIFIED_CROSS_SENTINEL_TARGET",
            "owner_mass_kg": "UNKNOWN",
            "reason": "18.876 kg is this source's declared primitive only; F2-S1 owner evidence is not imported into F2-S2",
        }
    return {
        "sentinel_id": sentinel,
        "family_id": row.get("family_id"),
        "physical_case_id": row.get("physical_case_id"),
        "source_bindings": {"source_xml": source_actual, "solver_receipt": receipt_actual, "motion": motion_actual},
        "producer_identity": {"case_id": receipt_summary["case_id"], "attempt_id": receipt_summary["attempt_id"], "physical_case_id": receipt_summary["physical_case_id"], "source_row_physical_case_id": receipt_summary["source_row_physical_case_id"], "physical_case_join": receipt_summary["physical_case_join"], "returncode": 0, "status": "completed"},
        "source_definition": source,
        "control_snapshot": {
            "source_audit_canonical_control_sha256": row.get("canonical_control_payload_sha256"),
            "source_audit_control_equivalence": row.get("control_equivalence"),
            "receipt_tmax_s": receipt_summary.get("tmax_s"),
            "receipt_tout_s": receipt_summary.get("tout_s"),
            "source_xml_controls": source["controls"],
            "motion_status": row.get("motion_metadata_status"),
            "motion_binding_status": "PASS_EXACT_SHA" if motion_actual else "UNKNOWN_NO_BOUND_MOTION_FILE",
        },
        "declared_primitive": {"density_kg_m3": density, "volume_m3": volume, "mass_kg": declared_mass, "source_and_bounds_scalar_status": "PASS_METADATA_ONLY"},
        "drawbox_check": drawboxes,
        "owner_contract": owner_status,
        "guarded_followup": {
            "kind": "INITIAL_GENERATED_SUPPORT_AUDIT",
            "required_payloads_after_parent_reservation": ["generated.xml", "Fluid.vtk", "Bound.vtk", "optional generated.bi4"],
            "support_overlap_boundary_ownership": "UNKNOWN_UNTIL_GUARDED_PRODUCT",
            "effective_particle_mass": "UNKNOWN_UNTIL_GUARDED_PRODUCT",
            "solver_launch": False,
        },
        "qualification": QUALIFICATION,
    }


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise PreflightFailure("manifest schema mismatch")
    if manifest.get("status") != "PREPARED_SOURCE_OWNER_CONTROL_PREFLIGHT_V1":
        raise PreflightFailure("manifest is not a prepared source-owner-control preflight")
    if manifest.get("sentinel_ids") != list(TARGETS):
        raise PreflightFailure("manifest target sentinel list mismatch")
    static = manifest.get("static_sources")
    if not isinstance(static, list) or not static:
        raise PreflightFailure("manifest has no static sources")
    for item in static:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise PreflightFailure("manifest static source record malformed")
        if Path(item["path"]).suffix.lower() in FORBIDDEN_SUFFIXES:
            raise PreflightFailure(f"forbidden payload entered static source list: {item['path']}")


def run(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest, manifest_record = _record(manifest_path, "source-owner-control manifest", parse_json=True)
    _validate_manifest(manifest)
    inputs = manifest.get("source_inputs")
    if not isinstance(inputs, dict):
        raise PreflightFailure("manifest source_inputs must be an object")
    audit, audit_actual = _bound_record(inputs.get("source_control_audit"), "source control audit", parse_json=True)
    bounds, bounds_actual = _bound_record(inputs.get("geometry_bounds"), "geometry bounds report", parse_json=True)
    status, status_actual = _bound_record(inputs.get("source_status"), "source status report", parse_json=True)
    if audit.get("schema") != "ds02.stage2.fourteen-source-control-audit.v5":
        raise PreflightFailure("source control audit schema mismatch")
    if bounds.get("schema") != "ds02.stage2.continuum-geometry-bounds.v1":
        raise PreflightFailure("geometry bounds schema mismatch")
    if not isinstance(status.get("sentinels"), list):
        raise PreflightFailure("source status report lacks sentinel list")
    cases = [_case(audit, bounds, sentinel) for sentinel in TARGETS]
    result = {
        "schema": SCHEMA,
        "status": "COMPLETE_SOURCE_OWNER_CONTROL_PREFLIGHT_NO_SCIENTIFIC_Q",
        "manifest": manifest_record,
        "source_inputs": {"source_control_audit": audit_actual, "geometry_bounds": bounds_actual, "source_status": status_actual},
        "cases": cases,
        "summary": {
            "source_xml_receipt_motion_join": "PASS_METADATA_ONLY",
            "declared_primitive_volume_mass": "PASS_METADATA_ONLY",
            "continuous_owner": "UNKNOWN_FOR_ALL_CASES",
            "effective_particle_support_overlap_mass": "UNKNOWN_FOR_ALL_CASES",
            "f2_s2_cross_sentinel_owner_import": False,
        },
        "read_scope": {"bounded_json_xml_motion_only": True, "bi4_read": False, "vtk_read": False, "hdf5_read": False, "native_part_read": False, "solver_launch": False},
        "scientific_qualification": QUALIFICATION,
    }
    output_path = _absolute(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise PreflightFailure(f"refusing to overwrite immutable output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, output_path)
    return result


def _fixture_case() -> None:
    """Exercise the XML parser and its negative paths without production files."""
    xml = b'''<case><cflnumber value="0.2"/><definition dp="0.01"/><setmkfluid mk="0"><drawbox><point x="0" y="0" z="0"/><size x="0.1" y="0.2" z="0.3"/></drawbox></setmkfluid><parameter key="TimeMax" value="4"/><parameter key="TimeOut" value="0.01"/></case>'''
    parsed = _parse_source_xml(xml, "fixture")
    assert math.isclose(parsed["declared_primitive_volume_m3"], 0.006, rel_tol=0.0, abs_tol=1e-15)
    assert parsed["fluid_drawboxes"][0]["mkfluid"] == "0"
    try:
        _parse_source_xml(b"<case><definition dp=\"nan\"/></case>", "bad")
    except PreflightFailure:
        pass
    else:
        raise AssertionError("non-finite/missing fluid fixture was accepted")


def self_test() -> None:
    _fixture_case()
    assert TARGETS == ("F2-S2", "F3-S1", "F5-S1")
    try:
        _validate_manifest({"schema": MANIFEST_SCHEMA, "status": "PREPARED_SOURCE_OWNER_CONTROL_PREFLIGHT_V1", "sentinel_ids": list(TARGETS), "static_sources": [{"path": "bad.bi4"}]})
    except PreflightFailure:
        pass
    else:
        raise AssertionError("forbidden BI4 fixture was accepted")
    print("PASS_THREE_SENTINEL_SOURCE_OWNER_CONTROL_PREFLIGHT_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run", action="store_true", help="explicit guarded-run marker; execution remains metadata-only")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.manifest is None or args.output is None:
        parser.error("--manifest and --output are required unless --self-test is used")
    try:
        result = run(args.manifest, args.output)
    except (PreflightFailure, OSError, ValueError, ET.ParseError) as exc:
        print(f"FAILED_THREE_SENTINEL_SOURCE_OWNER_CONTROL_PREFLIGHT: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "output": str(_absolute(args.output)), "cases": len(result["cases"]), "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

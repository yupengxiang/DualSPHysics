#!/usr/bin/env python3
"""Guarded GenCase-product initial-support audit for three owner ladders.

This worker consumes nine already-produced GenCase products: F2-S2, F3-S1,
and F5-S1 at the original, coarse, and fine rungs.  It never starts GenCase
or a solver.  Generated XML is read as bounded metadata; Fluid/Bound VTK and
the generated BI4 are read only after the parent has reserved the request and
are closed by complete pre/post SHA/stat records.  A parent may additionally
provide a small native-header probe produced by its BI4 adapter.  Missing
probe fields remain UNKNOWN; XML ``massfluid`` is never promoted to native
MassFluid/MassBound or continuous-owner mass.

The report is an initial-support diagnostic.  It does not assign QI/QN/QE,
three-grid error, no-penetration, flux, or truth credit.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
GEOMETRY_PATH = HERE / "stage2_four_sentinel_gencase_geometry_support_audit_v1.py"
GEOMETRY_SPEC = importlib.util.spec_from_file_location("stage2_root316_geometry_helpers_for_owner_grid_v1", GEOMETRY_PATH)
if GEOMETRY_SPEC is None or GEOMETRY_SPEC.loader is None:
    raise RuntimeError(f"cannot load geometry parser: {GEOMETRY_PATH}")
GEOMETRY = importlib.util.module_from_spec(GEOMETRY_SPEC)
GEOMETRY_SPEC.loader.exec_module(GEOMETRY)

SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-audit.v1"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1"
NATIVE_HEADER_SCHEMA = "ds02.stage2.native-header-probe.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)
SMALL_CAP = 16 * 1024 * 1024
PAYLOAD_CAP = 512 * 1024 * 1024
STAT_FIELDS = ("device", "inode", "bytes", "mtime_ns", "ctime_ns")
UNKNOWN = "UNKNOWN"
QUALIFICATION = {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0}


class AuditFailure(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _regular(path: Path, label: str) -> Path:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise AuditFailure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _expected_stat(record: dict[str, Any]) -> dict[str, int]:
    source = record.get("stat") or record.get("stat_after") or record.get("stat_at_build") or {}
    aliases = {
        "device": ("device", "dev", "st_dev"),
        "inode": ("inode", "ino", "st_ino"),
        "bytes": ("bytes", "size"),
        "mtime_ns": ("mtime_ns",),
        "ctime_ns": ("ctime_ns",),
    }
    result: dict[str, int] = {}
    for target, names in aliases.items():
        for name in names:
            if name in source:
                result[target] = int(source[name])
                break
    return result


def _assert_stat(path: Path, record: dict[str, Any], label: str) -> dict[str, int]:
    actual = _stat(_regular(path, label))
    expected = _expected_stat(record)
    for key, value in expected.items():
        if actual[key] != value:
            raise AuditFailure(f"{label} {key} changed: expected {value}, got {actual[key]}")
    return actual


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bounded_bytes(path: Path, record: dict[str, Any] | None, label: str,
                   *, payload: bool = False) -> tuple[bytes, dict[str, Any]]:
    """Read one immutable byte image and compute complete pre/post digests."""
    path = _regular(path, label)
    before = _assert_stat(path, record or {}, f"{label} pre")
    if before["bytes"] > (PAYLOAD_CAP if payload else SMALL_CAP):
        raise AuditFailure(f"{label} exceeds bounded read cap: {path}")
    # The first complete pass establishes the source digest before parsing.
    pre_raw = path.read_bytes()
    pre_stat = _stat(path)
    pre_sha = _digest(pre_raw)
    if pre_stat != before or len(pre_raw) != before["bytes"]:
        raise AuditFailure(f"{label} changed during pre-read: {path}")
    declared = (record or {}).get("sha256")
    if isinstance(declared, str) and len(declared) == 64 and pre_sha != declared.lower():
        raise AuditFailure(f"{label} SHA differs from manifest: {path}")
    # Parsing is performed from pre_raw; post pass encloses the parser and
    # proves that no producer replacement occurred during the diagnostic.
    post_raw = path.read_bytes()
    after = _stat(path)
    post_sha = _digest(post_raw)
    if after != before or len(post_raw) != before["bytes"] or pre_sha != post_sha:
        raise AuditFailure(f"{label} changed across guarded read: {path}")
    return pre_raw, {"path": str(path), "sha256_pre": pre_sha, "sha256_post": post_sha,
                     "stat_pre": before, "stat_post": after,
                     "stable": True, "complete_payload_passes": 2,
                     "payload_read": True, "post_equal": pre_sha == post_sha}


def _small_json(path: Path, record: dict[str, Any] | None, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, guard = _bounded_bytes(path, record, label, payload=False)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise AuditFailure(f"{label} must be an object")
    return value, guard


def _small_xml(path: Path, record: dict[str, Any] | None, label: str) -> tuple[bytes, dict[str, Any]]:
    raw, guard = _bounded_bytes(path, record, label, payload=False)
    return raw, guard


def _record_path(record: Any, label: str) -> Path:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise AuditFailure(f"{label} record lacks path")
    return _absolute(Path(record["path"]))


def _parse_xml(raw: bytes, path: str) -> dict[str, Any]:
    try:
        return GEOMETRY._parse_xml(raw, path)
    except Exception as exc:
        raise AuditFailure(f"generated XML parse failed: {path}: {exc}") from exc


def _xml_tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _xml_diffs(left: ET.Element, right: ET.Element, path: str = "") -> list[dict[str, Any]]:
    here = f"{path}/{_xml_tag(left)}[0]"
    diffs: list[dict[str, Any]] = []
    if _xml_tag(left) != _xml_tag(right):
        return [{"path": here, "kind": "tag", "left": _xml_tag(left), "right": _xml_tag(right)}]
    for name in sorted(set(left.attrib) | set(right.attrib)):
        if left.attrib.get(name) != right.attrib.get(name):
            diffs.append({"path": here, "kind": "attribute", "attribute": name,
                          "left": left.attrib.get(name), "right": right.attrib.get(name)})
    if len(left) != len(right):
        diffs.append({"path": here, "kind": "child_count", "left": len(left), "right": len(right)})
    for index, (child_left, child_right) in enumerate(zip(left, right)):
        diffs.extend(_xml_diffs(child_left, child_right, f"{here}[{index}]"))
    return diffs


def _candidate_contract(source_raw: bytes, candidate_raw: bytes, sid: str, grid: str) -> dict[str, Any]:
    try:
        left = ET.fromstring(source_raw)
        right = ET.fromstring(candidate_raw)
        diffs = _xml_diffs(left, right)
        allowed = [item for item in diffs
                   if item.get("kind") == "attribute" and item.get("attribute") == "dp"
                   and item.get("path", "").endswith("/definition[0]")]
        unexpected = [item for item in diffs if item not in allowed]
        result = {"all_differences": diffs, "allowed_definition_dp_differences": allowed,
                  "unexpected_differences": unexpected,
                  "status": "PASS_ONLY_DEFINITION_DP" if diffs and not unexpected else
                  ("PASS_IDENTICAL_SOURCE_DEF" if not diffs else "FAIL_OTHER_SOURCE_EDIT")}
    except Exception as exc:
        raise AuditFailure(f"{sid}:{grid} candidate Def comparison failed: {exc}") from exc
    if result.get("unexpected_differences"):
        return {"status": "FAIL_SOURCE_CONTROL_OR_GEOMETRY_CHANGED",
                "comparison": result, "mass_rescale": False}
    return {"status": result.get("status", "UNKNOWN"), "comparison": result, "mass_rescale": False}


def _native_probe(path: Path | None, record: dict[str, Any] | None,
                  native_guard: dict[str, Any], label: str) -> dict[str, Any]:
    """Validate an optional parent-produced native-header JSON sidecar.

    This is intentionally a sidecar interface: the worker never invents
    MassFluid/MassBound from XML.  The sidecar must name the guarded BI4 and
    carry the native fields it actually observed.
    """
    if path is None or record is None or (
        record.get("status") in {"NOT_BOUND", "PARENT_AFTER_RESERVATION_REQUIRED"}
        and not path.is_file()
    ):
        return {"status": "UNKNOWN_NATIVE_HEADER_PROBE_NOT_BOUND",
                "massfluid": UNKNOWN, "massbound": UNKNOWN,
                "source_xml_mass_is_not_native": True}
    value, guard = _small_json(path, record, label)
    if value.get("schema") != NATIVE_HEADER_SCHEMA:
        raise AuditFailure(f"{label} schema mismatch")
    source_path = str(_absolute(Path(str(value.get("source_path", "")))))
    if source_path != native_guard["path"]:
        raise AuditFailure(f"{label} source path does not match guarded BI4")
    source_sha = value.get("source_sha256")
    if source_sha not in (native_guard.get("sha256_pre"), native_guard.get("sha256_post")):
        raise AuditFailure(f"{label} source SHA does not match guarded BI4")
    for key in ("massfluid", "massbound", "dp", "time_s"):
        if key in value and value[key] is not None:
            try:
                number = float(value[key])
            except (TypeError, ValueError) as exc:
                raise AuditFailure(f"{label} {key} is not numeric") from exc
            if not math.isfinite(number):
                raise AuditFailure(f"{label} {key} is non-finite")
    role_counts = value.get("role_counts")
    finite = value.get("finite_fields")
    if not isinstance(role_counts, dict) or not isinstance(finite, dict):
        raise AuditFailure(f"{label} lacks native role/finite fields")
    if finite.get("position") is not True or finite.get("ids_unique") is not True:
        raise AuditFailure(f"{label} native finite/identity checks failed")
    return {"status": "PASS_NATIVE_HEADER_FIELDS",
            "source_path": source_path, "source_sha256": source_sha,
            "probe": guard, "massfluid": value.get("massfluid", UNKNOWN),
            "massbound": value.get("massbound", UNKNOWN), "dp": value.get("dp"),
            "time_s": value.get("time_s"), "role_counts": role_counts,
            "finite_fields": finite, "xml_mass_is_not_native": True,
            "native_header_values_only": True}


def _audit_case(case: dict[str, Any], attempt_root: Path) -> dict[str, Any]:
    sid = str(case.get("sentinel_id")); grid = str(case.get("grid_label")); key = f"{sid}:{grid}"
    source_xml = _record_path(case.get("source_xml"), f"{key} source XML")
    source_def = _record_path(case.get("source_def"), f"{key} source Def")
    candidate_def = _record_path(case.get("candidate_def"), f"{key} candidate Def")
    generated_xml = _record_path(case.get("generated_xml"), f"{key} generated XML")
    receipt_path = _record_path(case.get("gencase_receipt"), f"{key} GenCase receipt")
    fluid_path = _record_path(case.get("fluid_vtk"), f"{key} Fluid VTK")
    bound_path = _record_path(case.get("bound_vtk"), f"{key} Bound VTK")
    native_path = _record_path(case.get("native_bi4"), f"{key} generated BI4")
    source_raw, source_guard = _small_xml(source_xml, case.get("source_xml"), f"{key} source XML")
    source_def_raw, source_def_guard = _small_xml(source_def, case.get("source_def"), f"{key} source Def")
    candidate_raw, candidate_guard = _small_xml(candidate_def, case.get("candidate_def"), f"{key} candidate Def")
    generated_raw, generated_guard = _small_xml(generated_xml, case.get("generated_xml"), f"{key} generated XML")
    receipt, receipt_guard = _small_json(receipt_path, case.get("gencase_receipt"), f"{key} GenCase receipt")
    if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise AuditFailure(f"{key} GenCase receipt is not completed with returncode 0")
    source_meta = _parse_xml(source_raw, str(source_xml))
    candidate_meta = _parse_xml(candidate_raw, str(candidate_def))
    generated_meta = _parse_xml(generated_raw, str(generated_xml))
    contract = _candidate_contract(source_def_raw, candidate_raw, sid, grid)
    fluid_raw, fluid_guard = _bounded_bytes(fluid_path, case.get("fluid_vtk"), f"{key} Fluid VTK", payload=True)
    bound_raw, bound_guard = _bounded_bytes(bound_path, case.get("bound_vtk"), f"{key} Bound VTK", payload=True)
    fluid = GEOMETRY._parse_vtk(fluid_raw, str(fluid_path), expected_count=generated_meta.get("fluid_count") or None)
    bound = GEOMETRY._parse_vtk(bound_raw, str(bound_path), expected_count=None)
    fluid_ids = fluid["arrays"].get("Idp") if "Idp" in fluid["arrays"] else fluid["arrays"].get("Idpd")
    bound_ids = bound["arrays"].get("Idp") if "Idp" in bound["arrays"] else bound["arrays"].get("Idpd")
    fluid_map = GEOMETRY._map_ids(fluid_ids, generated_meta["fluid_blocks"], fluid["point_count"])
    bound_map = GEOMETRY._map_ids(bound_ids, generated_meta["bound_blocks"], bound["point_count"])
    envelope = GEOMETRY._inside(fluid["points"], generated_meta["fluid_boxes"], generated_meta["dp_m"])
    contact = GEOMETRY._contact(fluid["points"], bound["points"], max(generated_meta["dp_m"] * 1.0e-4, 1.0e-7))
    if case.get("native_bi4", {}).get("payload_read_by_builder") is True:
        raise AuditFailure(f"{key} BI4 was marked as pre-read by the builder")
    # Unlike the source-only builder, this parent-guarded worker is allowed to
    # consume the native initial product.  The complete pre/post digest is the
    # source identity used by the optional native-header probe.
    _, native_guard = _bounded_bytes(native_path, case.get("native_bi4") or {},
                                     f"{key} generated BI4", payload=True)
    native_guard["post_equal"] = native_guard["sha256_pre"] == native_guard["sha256_post"]
    native_guard["sha_basis"] = "ESTABLISHED_BY_THIS_PARENT_GUARDED_READ"
    probe_record = case.get("native_header_probe")
    probe_path = _record_path(probe_record, f"{key} native header probe") if isinstance(probe_record, dict) and isinstance(probe_record.get("path"), str) else None
    header = _native_probe(probe_path, probe_record, native_guard, f"{key} native header probe")
    owner = case.get("owner_predicate")
    if not isinstance(owner, dict):
        raise AuditFailure(f"{key} owner predicate is missing")
    return {
        "row_key": key, "sentinel_id": sid, "grid_label": grid,
        "status": "PASS_INITIAL_SUPPORT_DIAGNOSTIC",
        "source_identity": {"source_xml": source_guard, "source_def": source_def_guard,
                             "candidate_def": candidate_guard, "gencase_receipt": receipt_guard,
                             "physical_case_id": case.get("physical_case_id")},
        "source_geometry_contract": {"source": source_meta, "candidate": candidate_meta,
                                     "candidate_edit": contract, "owner_predicate": owner},
        "generated_xml": {"guard": generated_guard, "metadata": generated_meta},
        "deferred_payload_guards": {"fluid_vtk": fluid_guard, "bound_vtk": bound_guard,
                                     "native_bi4": native_guard},
        "fluid": {"point_count": fluid["point_count"], "finite_points": fluid["finite_points"],
                  "axis_summary": GEOMETRY._axis(fluid["points"]), "array_meta": fluid["array_meta"],
                  "idp_mapping": fluid_map, "xml_fluid_count": generated_meta["fluid_count"],
                  "xml_massfluid_kg": generated_meta["massfluid_kg"],
                  "xml_envelope_relation": envelope},
        "bound": {"point_count": bound["point_count"], "finite_points": bound["finite_points"],
                  "axis_summary": GEOMETRY._axis(bound["points"]), "array_meta": bound["array_meta"],
                  "idp_mapping": bound_map},
        "fluid_bound_contact": contact,
        "native_header": header,
        "owner_status": owner.get("status", UNKNOWN),
        "admission": {"gencase_only": True, "payload_integrity": "PASS_FINITE_AND_XML_JOIN",
                       "owner_geometry": "DIAGNOSTIC_ONLY", "continuous_owner_mass": UNKNOWN,
                       "native_mass": header.get("status"), "mass_rescale": False,
                       "QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN,
                       "scientific_credit": 0},
        "read_scope": {"generated_xml": True, "fluid_vtk": True, "bound_vtk": True,
                        "native_bi4_bytes": True, "native_header_probe": bool(probe_path),
                        "solver_launch": False, "gencase_launch": False, "hdf5": False},
    }


def _validate_manifest(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise AuditFailure(f"manifest schema mismatch: {manifest.get('schema')!r}")
    if manifest.get("status") != "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT":
        raise AuditFailure("manifest is not a guarded owner-grid initial-support manifest")
    rows = manifest.get("cases")
    if not isinstance(rows, list) or len(rows) != len(ROW_KEYS):
        raise AuditFailure(f"manifest must contain exactly {len(ROW_KEYS)} rows")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("sentinel_id") not in TARGETS or row.get("grid_label") not in GRIDS:
            raise AuditFailure("manifest row has invalid sentinel/grid")
        key = f"{row['sentinel_id']}:{row['grid_label']}"
        if key in result:
            raise AuditFailure(f"duplicate manifest row {key}")
        result[key] = row
        if row.get("owner_predicate", {}).get("mass_rescale") is not False:
            raise AuditFailure(f"{key} permits mass rescaling")
    if set(result) != set(ROW_KEYS):
        raise AuditFailure("manifest does not cover all three sentinels at all three grids")
    scope = manifest.get("scientific_scope")
    if not isinstance(scope, dict) or scope.get("neighbor_grid_truth") is not False or scope.get("scientific_credit") != 0:
        raise AuditFailure("manifest scientific scope is not diagnostic-only")
    return result


def run(manifest_path: Path, attempt_root: Path, output_path: Path) -> dict[str, Any]:
    raw, manifest_guard = _bounded_bytes(Path(manifest_path), None, "owner-grid support manifest", payload=False)
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditFailure("owner-grid support manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise AuditFailure("owner-grid support manifest must be an object")
    rows = _validate_manifest(manifest)
    results: list[dict[str, Any]] = []
    for key in ROW_KEYS:
        case = rows[key]
        try:
            results.append(_audit_case(case, _absolute(attempt_root)))
        except Exception as exc:
            results.append({"row_key": key, "sentinel_id": case.get("sentinel_id"),
                            "grid_label": case.get("grid_label"),
                            "status": "FAILED_INITIAL_SUPPORT_DIAGNOSTIC", "reason": repr(exc),
                            "admission": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0},
                            "read_scope": {"solver_launch": False, "gencase_launch": False}})
    passed = sum(1 for row in results if row.get("status") != "FAILED_INITIAL_SUPPORT_DIAGNOSTIC")
    failed = len(results) - passed
    value = {"schema": SCHEMA,
             "status": "COMPLETE_PARTIAL_OWNER_GRID_INITIAL_SUPPORT_DIAGNOSTICS",
             "manifest": manifest_guard, "cases": results,
             "case_counts": {"PASS_OR_DIAGNOSTIC": passed, "FAILED": failed},
             "scientific_scope": {"continuous_owner": UNKNOWN, "native_mass_xml_fallback": False,
                                  "neighbor_grid_truth": False, "mass_rescale": False,
                                  "QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0},
             "read_scope": {"gencase_launch": False, "solver_launch": False,
                            "production_hdf5_read": False, "native_bi4_bytes": True,
                            "native_header_probe_optional": True}}
    output_path = _absolute(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise AuditFailure(f"refusing overwrite: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.manifest is None or args.attempt_root is None or args.output is None:
        parser.error("--run requires --manifest, --attempt-root, --output")
    try:
        value = run(args.manifest, args.attempt_root, args.output)
    except (AuditFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": value["status"], "output": str(_absolute(args.output)),
                      "case_counts": value["case_counts"], "scientific_credit": 0}, sort_keys=True))
    return 0


def _tiny_vtk(points: list[tuple[float, float, float]], ids: list[int]) -> bytes:
    import struct
    header = b"# vtk DataFile Version 3.0\ntiny\nBINARY\nDATASET POLYDATA\n"
    header += f"POINTS {len(points)} float\n".encode("ascii")
    payload = b"".join(struct.pack(">fff", *point) for point in points)
    tail = f"\nPOINT_DATA {len(points)}\nSCALARS Idp unsigned_int 1\nLOOKUP_TABLE default\n".encode("ascii")
    return header + payload + tail + b"".join(struct.pack(">I", value) for value in ids) + b"\n"


def _fixture_manifest(root: Path) -> Path:
    """Create a nine-row fixture without touching any production artifact."""
    root.mkdir(parents=True, exist_ok=True)
    xml_text = """<case><casedef><definition dp=\"0.1\"/><mainlist><setmkfluid mk=\"1\"/><drawbox><point x=\"0\" y=\"0\" z=\"0\"/><size x=\"1\" y=\"1\" z=\"1\"/></drawbox><setmkbound mk=\"2\"/></mainlist></casedef><execution><particles><fluid begin=\"0\" count=\"2\" mkfluid=\"0\" mk=\"1\"/><bound begin=\"2\" count=\"1\" mkbound=\"2\" mk=\"2\"/></particles><constants><massfluid value=\"0.5\"/></constants></execution></case>"""
    source_xml = root / "source.xml"; source_xml.write_text(xml_text, encoding="utf-8")
    source_def = root / "source_Def.xml"; source_def.write_text(xml_text, encoding="utf-8")
    candidate_def = root / "candidate_Def.xml"; candidate_def.write_text(xml_text.replace('dp="0.1"', 'dp="0.05"'), encoding="utf-8")
    def rec(path: Path, *, digest: bool = True) -> dict[str, Any]:
        value = _stat(path); row = {"path": str(path.absolute()), "stat": value}
        if digest:
            row["sha256"] = _digest(path.read_bytes())
        return row
    cases: list[dict[str, Any]] = []
    for sid in TARGETS:
        for grid in GRIDS:
            row_root = root / sid / grid; row_root.mkdir(parents=True, exist_ok=True)
            generated_xml = row_root / "generated.xml"; generated_xml.write_text(xml_text, encoding="utf-8")
            receipt = row_root / "execution-receipt.json"; receipt.write_text('{"status":"completed","returncode":0}\n', encoding="utf-8")
            fluid = row_root / "generated_Fluid.vtk"; fluid.write_bytes(_tiny_vtk([(0.25, 0.25, 0.25), (0.75, 0.75, 0.75)], [0, 1]))
            bound = row_root / "generated_Bound.vtk"; bound.write_bytes(_tiny_vtk([(0.25, 0.25, 0.25)], [2]))
            bi4 = row_root / "generated.bi4"; bi4.write_bytes(b"tiny-native")
            probe_record: dict[str, Any] = {"status": "NOT_BOUND", "path": str(row_root / "native-header.json")}
            if sid == "F2-S2" and grid == "original":
                native_probe = row_root / "native-header.json"
                native_probe.write_text(json.dumps({"schema": NATIVE_HEADER_SCHEMA,
                    "source_path": str(bi4.absolute()), "source_sha256": _digest(bi4.read_bytes()),
                    "massfluid": 0.5, "massbound": 0.5, "dp": 0.1, "time_s": 0.0,
                    "role_counts": {"fluid": 2, "bound": 1},
                    "finite_fields": {"position": True, "ids_unique": True}}), encoding="utf-8")
                probe_record = rec(native_probe)
            cases.append({"sentinel_id": sid, "grid_label": grid, "family_id": sid[:2],
                          "physical_case_id": f"fixture-{sid}-{grid}",
                          "source_xml": rec(source_xml), "source_def": rec(source_def),
                          "candidate_def": rec(candidate_def), "generated_xml": rec(generated_xml),
                          "gencase_receipt": rec(receipt), "fluid_vtk": {**rec(fluid, digest=False), "payload_read_by_builder": False},
                          "bound_vtk": {**rec(bound, digest=False), "payload_read_by_builder": False},
                          "native_bi4": {**rec(bi4, digest=False), "payload_read_by_builder": False},
                          "native_header_probe": probe_record,
                          "owner_predicate": {"status": "UNKNOWN_CONTINUOUS_OWNER", "mass_rescale": False,
                                              "predicate": "diagnostic fixture owner predicate only"}})
    manifest = {"schema": MANIFEST_SCHEMA, "status": "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT",
                "cases": cases, "scientific_scope": {"neighbor_grid_truth": False, "scientific_credit": 0}}
    path = root / "manifest.json"; path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return path


def self_test() -> None:
    with __import__("tempfile").TemporaryDirectory(prefix="owner-grid-support-") as value:
        root = Path(value); manifest = _fixture_manifest(root); output = root / "report.json"
        result = run(manifest, root / "attempt", output)
        assert result["case_counts"] == {"PASS_OR_DIAGNOSTIC": 9, "FAILED": 0}
        assert result["cases"][0]["native_header"]["status"] == "PASS_NATIVE_HEADER_FIELDS"
        assert sum(row["native_header"]["status"].startswith("UNKNOWN") for row in result["cases"]) == 8
        assert all(row["admission"]["scientific_credit"] == 0 for row in result["cases"])
    print("PASS_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_WORKER_SELFTEST")


if __name__ == "__main__":
    raise SystemExit(main())

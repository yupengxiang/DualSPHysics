#!/usr/bin/env python3
"""Source-bound ROOT279 axis/unit semantics checker.

This checker separates two facts that were previously conflated:

* the repository writer and the XML establish tuple storage and SI units;
* a producer-to-world rotation/axis-label authority may still be absent.

It reads only the small ROOT279 manifest/XML and checked-in source files.  It
does not read BI4/VTK/Part/H5 payloads and cannot turn component-space fields
into world-space scientific credit.  A missing explicit rotation or axis
record is reported as UNKNOWN, even when the storage tuple and SI units are
closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET
from typing import Any


HERE = Path(__file__).resolve().parent
SCHEMA = "ds02.stage2.f1-s2.root279-axis-semantics.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v3-root310"
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
CAP = 10 * 1024 * 1024


class AxisSemanticsFailure(RuntimeError):
    pass


def _abs(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    st = path.stat()
    return {"device": int(st.st_dev), "inode": int(st.st_ino), "bytes": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_small(path: Path | str, label: str) -> tuple[bytes, dict[str, Any]]:
    value = _abs(path)
    if value.is_symlink() or not value.is_file():
        raise AxisSemanticsFailure(f"{label} is not a regular non-symlink file: {value}")
    before = _stat(value)
    if before["bytes"] > CAP:
        raise AxisSemanticsFailure(f"{label} exceeds 10 MiB metadata cap: {value}")
    raw = value.read_bytes(); after = _stat(value)
    if before != after or len(raw) != before["bytes"]:
        raise AxisSemanticsFailure(f"{label} changed during bounded read: {value}")
    return raw, {"path": str(value), "sha256": _sha(raw), "bytes": len(raw),
                 "stat_before": before, "stat_after": after,
                 "read_scope": "bounded_source_metadata", "payload_read": False}


def _json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, rec = _read_small(path, label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AxisSemanticsFailure(f"{label} is not JSON") from exc
    if not isinstance(value, dict):
        raise AxisSemanticsFailure(f"{label} must be an object")
    return value, rec


def _xml_semantics(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, rec = _read_small(path, "ROOT279 generated XML")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise AxisSemanticsFailure(f"ROOT279 generated XML is not parseable: {path}") from exc
    definition = root.find("./casedef/geometry/definition")
    pos = definition.find("pointref") if definition is not None else None
    gravity_nodes = list(root.iter("gravity"))
    gravity = gravity_nodes[-1] if gravity_nodes else None
    dp = definition.get("dp") if definition is not None else None
    units_comment = definition.get("units_comment") if definition is not None else None
    gravity_units = gravity.get("units_comment") if gravity is not None else None
    # These are source/input semantics, not a world orientation assertion.
    units = {
        "position": "m" if isinstance(units_comment, str) and "metre" in units_comment.lower() else "UNKNOWN",
        # Gravity's ``m/s^2`` comment does not by itself establish velocity
        # units.  The source update law and an explicit seconds authority are
        # joined below; this prevents the old m/s-from-m/s^2 shortcut.
        "velocity": "UNKNOWN",
        "time": "UNKNOWN",
        "mass": "kg" if any("kg" in str(node.get("units_comment", ""))
                            for node in root.iter() if node.tag in {"massfluid", "massbound", "rhop0"}) else "UNKNOWN",
        "gravity": gravity_units or "UNKNOWN",
    }
    evidence = {
        "xml": rec, "root_tag": root.tag, "definition_dp": dp,
        "definition_units_comment": units_comment,
        "pointref_present": pos is not None,
        "pointref_xyz_fields": sorted(pos.attrib) if pos is not None else [],
        "gravity": dict(gravity.attrib) if gravity is not None else None,
        "units": units,
        "explicit_axis_labels": [node.attrib for node in root.iter()
                                  if any(key in node.attrib for key in ("axis", "axis_labels", "rotation_to_world"))],
        "explicit_rotation_to_world": any("rotation_to_world" in node.attrib for node in root.iter()),
    }
    return evidence, rec


def _source_semantics(paths: list[Path]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    snippets: dict[str, bool] = {
        'bi4_writer_posd_double3': False,
        'bi4_writer_pos_float3': False,
        'bi4_writer_vel_float3': False,
        'bi4_writer_rhop_float': False,
        'bi4_reader_posd': False,
        'solver_gravity_input': False,
        'solver_position_update_velocity_times_dt': False,
        'solver_time_seconds_authority': False,
    }
    records: list[dict[str, Any]] = []
    for path in paths:
        raw, rec = _read_small(path, f"axis authority source {path.name}")
        text = raw.decode("utf-8", errors="strict")
        records.append(rec)
        if 'CreateArray("Posd",JBinaryDataDef::DatDouble3' in text:
            snippets['bi4_writer_posd_double3'] = True
        if 'CreateArray("Pos",JBinaryDataDef::DatFloat3' in text:
            snippets['bi4_writer_pos_float3'] = True
        if 'CreateArray("Vel",JBinaryDataDef::DatFloat3' in text:
            snippets['bi4_writer_vel_float3'] = True
        if 'CreateArray("Rhop",JBinaryDataDef::DatFloat' in text:
            snippets['bi4_writer_rhop_float'] = True
        if 'GetArray("Posd"' in text or 'Get_Posd' in text:
            snippets['bi4_reader_posd'] = True
        if 'Gravity=ToTFloat3(ctes.GetGravity())' in text or 'Gravity.z' in text:
            snippets['solver_gravity_input'] = True
        if ('velrho1[p].x)*dt' in text or 'velrhoprec[p].x)*dt' in text or
                'velrho1[p].x)*dt05' in text or 'velrhoprec[p].x)*dt05' in text):
            snippets['solver_position_update_velocity_times_dt'] = True
        if 'TimeStep [s]' in text or 'Physical time of simulation' in text:
            snippets['solver_time_seconds_authority'] = True
    return snippets, records


def check(manifest_path: Path, source_paths: list[Path] | None = None) -> dict[str, Any]:
    manifest, manifest_record = _json(_abs(manifest_path), "ROOT279 source manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise AxisSemanticsFailure(f"manifest schema mismatch: {manifest.get('schema')!r}")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise AxisSemanticsFailure("ROOT279 manifest has no cases")
    xmls: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("generated_xml"), str):
            raise AxisSemanticsFailure("ROOT279 case lacks generated_xml")
        xml_evidence, _ = _xml_semantics(Path(case["generated_xml"]))
        xml_evidence["case_label"] = case.get("label")
        xmls.append(xml_evidence)
    if source_paths is None:
        repo = HERE.parents[4]
        source_paths = [repo / "src/source/JPartDataBi4.cpp",
                         repo / "src/source/JPartDataBi4.h",
                         repo / "src/source/JSph.cpp",
                         repo / "src/source/JSphCpu.cpp"]
    snippets, source_records = _source_semantics([_abs(p) for p in source_paths])
    # Posd is the double-precision path used by SavePosDouble=1; the source
    # also has a float ``Pos`` fallback, but that fallback is not required to
    # establish the selected producer's Posd/Vel/Rhop tuple contract.
    required_storage = all(snippets[name] for name in (
        "bi4_writer_posd_double3", "bi4_writer_vel_float3",
        "bi4_writer_rhop_float", "bi4_reader_posd", "solver_gravity_input"))
    units_bound = (
        all(item["units"].get("position") == "m" and item["units"].get("mass") == "kg"
            and item["units"].get("gravity") == "m/s^2" for item in xmls)
        and snippets["solver_position_update_velocity_times_dt"]
        and snippets["solver_time_seconds_authority"]
    )
    for item in xmls:
        item["units"]["time"] = "s" if snippets["solver_time_seconds_authority"] else "UNKNOWN"
        item["units"]["velocity"] = "m/s" if units_bound else "UNKNOWN"
    explicit_axis = all(item["explicit_rotation_to_world"] and item["explicit_axis_labels"] for item in xmls)
    return {
        "schema": SCHEMA,
        "status": "COMPONENT_STORAGE_AND_SI_UNITS_BOUND_WORLD_AXIS_UNKNOWN" if required_storage else "WAITING_AXIS_SOURCE_EVIDENCE",
        "manifest": manifest_record,
        "xml_evidence": xmls,
        "source_evidence": {"files": source_records, "writer_reader_semantics": snippets},
        "axis_authority": {
            "component_tuple_order": "Posd/Pos float3/double3 and Vel float3 follow JBinaryData arrays as written by JPartDataBi4",
            "si_units_bound_from_xml_and_solver_time_update": units_bound,
            "producer_to_world_orientation": "BOUND" if explicit_axis else "UNKNOWN",
            "world_axis_labels": "BOUND" if explicit_axis else "UNKNOWN",
            "rotation_to_world": "BOUND" if explicit_axis else "UNKNOWN",
            "reason": ("XML/source contain no explicit axis_labels or rotation_to_world record; component storage and SI units do not prove world orientation"
                       if not explicit_axis else "explicit source/input orientation record was found"),
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "read_scope": {"metadata_json_xml_cpp_only": True, "native_bi4_payload": False,
                        "vtk_payload": False, "solver_launch": False},
    }


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="root279-axis-semantics-") as td:
        root = Path(td)
        xml = root / "case.xml"
        xml.write_text("<case><casedef><geometry><definition dp='0.1' units_comment='metres (m)'><pointref x='0' y='0' z='0'/></definition></geometry></casedef><execution><constants><gravity x='0' y='0' z='-9.81' units_comment='m/s^2'/></constants></execution></case>\n", encoding="utf-8")
        cpp = root / "JPartDataBi4.cpp"
        cpp.write_text('CreateArray("Posd",JBinaryDataDef::DatDouble3,npok,posd,externalpointer);\nCreateArray("Pos",JBinaryDataDef::DatFloat3,npok,pos,externalpointer);\nCreateArray("Vel",JBinaryDataDef::DatFloat3,npok,vel,externalpointer);\nCreateArray("Rhop",JBinaryDataDef::DatFloat,npok,rhop,externalpointer);\nGetArray("Posd"); Gravity=ToTFloat3(ctes.GetGravity());\nconst double dx=double(velrho1[p].x)*dt;\n// TimeStep [s]\n', encoding="utf-8")
        header = root / "JPartDataBi4.h"; header.write_text('Get_Posd(unsigned size,tdouble3* data);\n', encoding="utf-8")
        jsph = root / "JSph.cpp"; jsph.write_text('Gravity=ToTFloat3(ctes.GetGravity());\n', encoding="utf-8")
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"schema": MANIFEST_SCHEMA, "cases": [{"label": "tiny", "generated_xml": str(xml)}]}) + "\n", encoding="utf-8")
        result = check(manifest, [cpp, header, jsph])
        assert result["status"] == "COMPONENT_STORAGE_AND_SI_UNITS_BOUND_WORLD_AXIS_UNKNOWN"
        assert result["axis_authority"]["producer_to_world_orientation"] == "UNKNOWN"
        assert result["scientific_qualification"]["QI"] == "UNKNOWN"
        # An axis label without a source storage join must not produce a pass;
        # this fixture deliberately has no rotation record.
    print("PASS_ROOT279_AXIS_SEMANTICS_SOURCE_STORAGE_UNITS_FIXTURE_WORLD_UNKNOWN")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.manifest is None:
            parser.error("--check requires --manifest")
        result = check(args.manifest, [Path(p) for p in args.source] or None)
        if args.output:
            output = _abs(args.output)
            if output.exists() or output.is_symlink():
                raise AxisSemanticsFailure(f"refusing overwrite: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (AxisSemanticsFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT279_AXIS_SEMANTICS: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

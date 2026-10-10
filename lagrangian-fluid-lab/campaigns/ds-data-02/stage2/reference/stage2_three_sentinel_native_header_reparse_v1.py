#!/usr/bin/env python3
"""Reparse retained ROOT709 ``bi4_dump`` XML without rereading native BI4.

ROOT709's decoder XML is a small, retained artifact.  Its scalar values are
serialized by JBinaryData as ``v=...`` attributes.  The consumed probe looked
only at ``value``, ``data`` and text, so it reported an empty value map even
though the XML contains ``Dp``, ``MassFluid``, ``MassBound`` and role counts.

This additive tool reparses those retained XML files under a bounded guard. It
binds every XML path/SHA/stat to the ROOT709 report and the original BI4
source path/SHA/stat, but it does not open the BI4, VTK, HDF5, or Part arrays.
The XML is emitted by the project ``bi4_dump`` adapter over JBinaryData; this
is a decoder-field diagnostic, not official-tool or scientific qualification.
Header mass is preserved as per-particle header metadata and is never summed
into a case total.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any


JSON_CAP = 10 * 1024 * 1024
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
REPORT_SCHEMA = "ds02.stage2.native-header-probe.v3"
PROOF_STATUS = "VERIFIED_ACTUAL_NINE_GENCASE_NATIVE_HEADER_DIAGNOSTIC_NO_SCIENTIFIC_Q"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = {f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS}
UNKNOWN = "UNKNOWN_NOT_EXPOSED_BY_DECODER"


class ReparseFailure(RuntimeError):
    pass


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    st = path.stat()
    return {"device": int(st.st_dev), "inode": int(st.st_ino), "bytes": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(path: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise ReparseFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise ReparseFailure(f"{label} exceeds the 10 MiB cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise ReparseFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReparseFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ReparseFailure(f"{label} must be an object")
    return value, {"path": str(path), "sha256": _sha(raw), "bytes": len(raw), "stat": after}


def _xml(path: Path | str, expected: dict[str, Any], label: str) -> tuple[ET.Element, dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise ReparseFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise ReparseFailure(f"{label} exceeds the bounded XML cap")
    raw = path.read_bytes()
    after = _stat(path)
    post_raw = path.read_bytes()
    if before != after or raw != post_raw:
        raise ReparseFailure(f"{label} changed during XML read")
    digest = _sha(raw)
    expected_sha = expected.get("sha256_pre") or expected.get("sha256")
    if isinstance(expected_sha, str) and expected_sha and digest.lower() != expected_sha.lower():
        raise ReparseFailure(f"{label} SHA differs from ROOT709 decoder record")
    expected_post = expected.get("sha256_post")
    if isinstance(expected_post, str) and expected_post and digest.lower() != expected_post.lower():
        raise ReparseFailure(f"{label} post-SHA differs from ROOT709 decoder record")
    expected_stat = expected.get("stat_pre") or expected.get("stat")
    if isinstance(expected_stat, dict):
        for target, aliases in {"device": ("device", "dev", "st_dev"),
                                "inode": ("inode", "ino", "st_ino"),
                                "bytes": ("bytes", "size"),
                                "mtime_ns": ("mtime_ns",), "ctime_ns": ("ctime_ns",)}.items():
            for alias in aliases:
                if alias in expected_stat and int(expected_stat[alias]) != before[target]:
                    raise ReparseFailure(f"{label} {target} differs from ROOT709 record")
                if alias in expected_stat:
                    break
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ReparseFailure(f"{label} is not valid XML") from exc
    return root, {"path": str(path), "sha256_pre": digest, "sha256_post": digest,
                  "stat_pre": before, "stat_post": after, "stable": True,
                  "complete_payload_passes": 2}


def _number(raw: str | None, label: str, integer: bool = False) -> int | float:
    if raw is None:
        raise ReparseFailure(f"missing JBinaryData value for {label}")
    try:
        value = int(raw) if integer else float(raw)
    except ValueError as exc:
        raise ReparseFailure(f"non-numeric JBinaryData value for {label}") from exc
    if isinstance(value, float) and not (value == value and abs(value) != float("inf")):
        raise ReparseFailure(f"non-finite JBinaryData value for {label}")
    return value


def _header_item(root: ET.Element) -> ET.Element:
    if root.tag != "data" or root.attrib.get("fmt") != "JBinaryData":
        raise ReparseFailure("decoder XML is not a JBinaryData data root")
    items = [node for node in root if node.tag == "item" and node.attrib.get("name") == "JPartDataBi4"]
    if len(items) != 1:
        raise ReparseFailure("decoder XML does not contain exactly one JPartDataBi4 item")
    return items[0]


def _values(root: ET.Element) -> dict[str, Any]:
    header = _header_item(root)
    values: dict[str, Any] = {}
    for node in list(header):
        name = node.attrib.get("name")
        if not name or node.tag == "item" or node.tag.startswith("array_"):
            continue
        # JBinaryData::ValueToXml uses v= for scalar values and x/y/z for
        # vector values.  Do not accept value/data/text: those are not the
        # official serializer's scalar representation here.
        if "v" in node.attrib:
            if name in values:
                raise ReparseFailure(f"duplicate JBinaryData header scalar {name}")
            values[name] = node.attrib["v"]
        elif all(axis in node.attrib for axis in ("x", "y", "z")):
            values[name] = tuple(node.attrib[axis] for axis in ("x", "y", "z"))
    part_items = [node for node in list(header) if node.tag == "item" and node.attrib.get("name") == "PART_0000"]
    if len(part_items) == 1:
        for node in list(part_items[0]):
            name = node.attrib.get("name")
            if name in ("TimeStep", "RunTime") and "v" in node.attrib:
                values[name] = node.attrib["v"]
    return values


def _row(row: dict[str, Any], xml_path: Path, xml_record: dict[str, Any]) -> dict[str, Any]:
    key = row.get("row_key")
    if key not in ROW_KEYS:
        raise ReparseFailure(f"unexpected ROOT709 row key {key!r}")
    root, guard = _xml(xml_path, row.get("decoder_xml") or {}, f"{key} retained decoder XML")
    values = _values(root)
    required_scalars = ("Dp", "MassBound", "MassFluid", "CaseNp", "CaseNfixed", "CaseNmoving", "CaseNfloat", "CaseNfluid")
    missing = [name for name in required_scalars if name not in values]
    if missing:
        raise ReparseFailure(f"{key} decoder XML is missing JPartDataBi4 fields: {missing}")
    counts = {"total": _number(values["CaseNp"], f"{key}.CaseNp", integer=True),
              "fixed": _number(values["CaseNfixed"], f"{key}.CaseNfixed", integer=True),
              "moving": _number(values["CaseNmoving"], f"{key}.CaseNmoving", integer=True),
              "floating": _number(values["CaseNfloat"], f"{key}.CaseNfloat", integer=True),
              "fluid": _number(values["CaseNfluid"], f"{key}.CaseNfluid", integer=True)}
    finite = {name: _number(values[name], f"{key}.{name}") == _number(values[name], f"{key}.{name}")
              for name in ("Dp", "MassBound", "MassFluid")}
    finite.update({"position": row.get("finite_fields", {}).get("position"),
                   "ids_unique": row.get("finite_fields", {}).get("ids_unique")})
    return {"schema": "ds02.stage2.native-header-probe.reparsed-row.v1",
            "row_key": key, "status": "PASS_NATIVE_HEADER_FIELDS_REPARSED_FROM_RETAINED_DECODER_XML",
            "source_path": row.get("source_path"), "source_sha256": row.get("source_sha256"),
            "source_guard": row.get("source_guard"), "decoder_xml": guard,
            "decoder_returncode": row.get("decoder_returncode"),
            "decoder_values": {"Dp": float(values["Dp"]), "MassBound": float(values["MassBound"]),
                               "MassFluid": float(values["MassFluid"]),
                               "TimeStep": float(values["TimeStep"]) if "TimeStep" in values else UNKNOWN,
                               "RunTime": float(values["RunTime"]) if "RunTime" in values else UNKNOWN},
            "role_counts": counts, "finite_fields": finite,
            "mass_semantics": "JPartDataHead_per_particle_header_value; not case_total",
            "source_xml_mass_is_not_native": True, "xml_fallback": False,
            "authority": {"producer": "GenCase", "serializer": "JBinaryData::ValueToXml",
                           "adapter": "project_custom_bi4_dump", "official_executable": False,
                           "native_payload_reread": False}}


def reparse(report_path: Path, output_path: Path) -> dict[str, Any]:
    report, report_record = _json(report_path, "ROOT709 native-header report")
    if report.get("schema") != REPORT_SCHEMA or report.get("xml_fallback") not in (False, None):
        raise ReparseFailure("ROOT709 report schema/fallback mismatch")
    rows = report.get("cases")
    if not isinstance(rows, list) or {row.get("row_key") for row in rows if isinstance(row, dict)} != ROW_KEYS:
        raise ReparseFailure("ROOT709 report row set is incomplete")
    parsed = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("decoder_xml"), dict):
            raise ReparseFailure(f"{row.get('row_key') if isinstance(row, dict) else 'row'} lacks retained decoder XML")
        xml_path = _abs(row["decoder_xml"].get("path", ""))
        parsed.append(_row(row, xml_path, report_record))
    value = {"schema": "ds02.stage2.native-header-probe.reparsed.v1",
             "status": "COMPLETE_RETAINED_DECODER_XML_HEADER_REPARSE_DIAGNOSTIC",
             "source_report": report_record, "cases": parsed,
             "native_header_source": "RETAINED_ROOT709_CUSTOM_BI4_DUMP_JBINARYDATA_XML",
             "native_payload_reread": False, "xml_mass_is_not_native": True,
             "scientific_scope": {"native_mass": "UNKNOWN_PER_PARTICLE_HEADER_ONLY",
                                  "continuous_owner": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN",
                                  "QE": "UNKNOWN", "scientific_credit": 0},
             "read_scope": {"report_json": True, "retained_decoder_xml": True,
                             "native_bi4": False, "vtk": False, "hdf5": False,
                             "part_arrays": False, "solver_launch": False, "gencase_launch": False}}
    output_path = _abs(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise ReparseFailure(f"refusing to overwrite {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return value


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="native-header-reparse-") as td:
        root = Path(td)
        xml = root / "decoded.xml"
        xml.write_text('''<?xml version="1.0"?><data fmt="JBinaryData"><item name="JPartDataBi4">'
                       '<double name="Dp" v="6e-3"/><double name="MassFluid" v="2.16e-4"/>'
                       '<double name="MassBound" v="2.16e-4"/><ullong name="CaseNp" v="3"/>'
                       '<ullong name="CaseNfixed" v="2"/><ullong name="CaseNmoving" v="0"/>'
                       '<ullong name="CaseNfloat" v="0"/><ullong name="CaseNfluid" v="1"/>'
                       '<item name="PART_0000"><double name="TimeStep" v="0"/></item>'
                       '</item></data>'''.replace("'\n                       '", ""), encoding="utf-8")
        raw = xml.read_bytes(); stat = _stat(xml)
        row = {"row_key": "F3-S1:original", "source_path": str(root / "generated.bi4"),
               "source_sha256": "0" * 64, "source_guard": {}, "decoder_returncode": 0,
               "decoder_xml": {"path": str(xml), "sha256_pre": _sha(raw), "sha256_post": _sha(raw),
                               "stat_pre": stat, "stat_post": stat},
               "finite_fields": {"position": "UNKNOWN", "ids_unique": "UNKNOWN"}}
        out = _row(row, xml, {"path": str(xml), "sha256": _sha(raw)})
        assert out["decoder_values"]["MassFluid"] == 2.16e-4
        assert out["role_counts"]["fluid"] == 1
        bad = xml.read_text().replace('name="MassFluid"', 'name="MassFluid2"')
        xml.write_text(bad, encoding="utf-8")
        try:
            _row(row, xml, {"path": str(xml), "sha256": _sha(raw)})
        except ReparseFailure:
            pass
        else:
            raise AssertionError("missing JBinaryData field was accepted")
    print("PASS_RETAINED_JBINARYDATA_HEADER_REPARSE_V1_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.report is None or args.output is None:
            parser.error("--run requires --report and --output")
        result = reparse(args.report, args.output)
        print(json.dumps({"status": result["status"], "output": str(_abs(args.output)),
                          "case_count": len(result["cases"]), "scientific_credit": 0}, sort_keys=True))
        return 0
    except (ReparseFailure, OSError, ValueError, json.JSONDecodeError, ET.ParseError) as exc:
        print(f"FAILED_RETAINED_JBINARYDATA_HEADER_REPARSE_V1: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

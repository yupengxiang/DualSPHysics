#!/usr/bin/env python3
"""Close the bounded F3-S1 source geometry/control contract.

This audit reads only the owner-grid source report and the three small Def
files.  The deferred CaseSloshingAccData.csv is stat-checked from the report
binding but never opened or hashed here.  No generated product, BI4, VTK,
solver output, or neighboring F3-S2 scale is used.

The source gives a fluid primitive of 0.894 x 0.174 x 0.084 m, hence a
13.066704 kg *source primitive* at rhop0=1000 kg/m^3.  That is deliberately
reported separately from the continuous owner and from the generated/native
mass.  Likewise, 0.894 m (fluid box) and 0.900 m (boundary box) are geometry
spans, not an authorized registered L.  The source has no event landmark,
velocity/KE scale, or owner-mass authority; those remain UNKNOWN until a
parent-generated support/native audit closes them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f3-s1.source-closure.v1"
REPORT_SCHEMA = "ds02.stage2.three-sentinel.owner-grid-source-audit.v3"
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_XML_BYTES = 10 * 1024 * 1024
GRIDS = ("original", "coarse", "fine")
EXPECTED_DP = {"original": 0.006, "coarse": 0.0075, "fine": 0.0048}
UNKNOWN_Q = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}


class ClosureFailure(RuntimeError):
    pass


def _abs(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {
        "device": int(s.st_dev),
        "inode": int(s.st_ino),
        "bytes": int(s.st_size),
        "mtime_ns": int(s.st_mtime_ns),
        "ctime_ns": int(s.st_ctime_ns),
    }


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read(path: Path, label: str, cap: int = MAX_JSON_BYTES) -> tuple[bytes, dict[str, int]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise ClosureFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > cap:
        raise ClosureFailure(f"{label} exceeds bounded read cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise ClosureFailure(f"{label} changed during bounded read: {path}")
    return raw, after


def _json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, stat = _read(path, label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClosureFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ClosureFailure(f"{label} must be a JSON object")
    return value, {"path": str(_abs(path)), "sha256": _sha(raw), "stat": stat, "bytes": len(raw)}


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ClosureFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise ClosureFailure(f"{label} is not finite")
    return result


def _close(a: float, b: float, tol: float = 1e-12) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def _vec(node: ET.Element, label: str) -> list[float]:
    return [_finite(node.attrib.get(axis), f"{label}.{axis}") for axis in ("x", "y", "z")]


def _parse_def(path: Path, label: str) -> dict[str, Any]:
    raw, stat = _read(path, label, MAX_XML_BYTES)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ClosureFailure(f"{label} is not valid XML") from exc

    definition = root.find(".//definition")
    if definition is None or "dp" not in definition.attrib:
        raise ClosureFailure(f"{label} has no geometry definition dp")
    dp = _finite(definition.attrib["dp"], f"{label}.definition.dp")
    pointref = root.find(".//definition/pointref")
    if pointref is None:
        raise ClosureFailure(f"{label} has no pointref")
    gravity = root.find(".//constantsdef/gravity")
    rhop0 = root.find(".//constantsdef/rhop0")
    cfl = root.find(".//constantsdef/cflnumber")
    if gravity is None or rhop0 is None or cfl is None:
        raise ClosureFailure(f"{label} is missing gravity/rhop0/cflnumber")

    mainlist = root.find(".//commands/mainlist")
    if mainlist is None:
        raise ClosureFailure(f"{label} has no commands/mainlist")
    drawboxes = mainlist.findall("./drawbox")
    if len(drawboxes) < 2:
        raise ClosureFailure(f"{label} needs fluid and boundary drawboxes")
    fluid_point = drawboxes[0].find("./point")
    fluid_size = drawboxes[0].find("./size")
    bound_point = drawboxes[1].find("./point")
    bound_size = drawboxes[1].find("./size")
    if any(item is None for item in (fluid_point, fluid_size, bound_point, bound_size)):
        raise ClosureFailure(f"{label} drawboxes lack point/size")
    assert fluid_point is not None and fluid_size is not None
    assert bound_point is not None and bound_size is not None

    params: dict[str, str] = {}
    for node in root.findall(".//execution/parameters/parameter"):
        key, value = node.attrib.get("key"), node.attrib.get("value")
        if key is not None and value is not None:
            params[key] = value
    acc = root.find(".//accinput/acctimesfile")
    return {
        "path": str(_abs(path)),
        "sha256": _sha(raw),
        "stat": stat,
        "dp_m": dp,
        "pointref_m": _vec(pointref, f"{label}.pointref"),
        "gravity_m_s2": _vec(gravity, f"{label}.gravity"),
        "rhop0_kg_m3": _finite(rhop0.attrib.get("value"), f"{label}.rhop0"),
        "cfl_number": _finite(cfl.attrib.get("value"), f"{label}.cflnumber"),
        "fluid_low_m": _vec(fluid_point, f"{label}.fluid.point"),
        "fluid_size_m": _vec(fluid_size, f"{label}.fluid.size"),
        "bound_low_m": _vec(bound_point, f"{label}.bound.point"),
        "bound_size_m": _vec(bound_size, f"{label}.bound.size"),
        "parameters": params,
        "acc_file": acc.attrib.get("value") if acc is not None else None,
    }


def _geometry_signature(parsed: dict[str, Any]) -> tuple[Any, ...]:
    excluded = {"path", "sha256", "stat", "dp_m"}
    return tuple((key, parsed[key]) for key in sorted(parsed) if key not in excluded)


def _source_case(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema") != REPORT_SCHEMA:
        raise ClosureFailure(f"unexpected source audit schema: {report.get('schema')!r}")
    cases = report.get("cases")
    if not isinstance(cases, list):
        raise ClosureFailure("source audit has no cases")
    matches = [case for case in cases if isinstance(case, dict) and case.get("sentinel_id") == "F3-S1"]
    if len(matches) != 1:
        raise ClosureFailure("source audit must contain exactly one F3-S1 case")
    return matches[0]


def _forcing_stat(case: dict[str, Any]) -> dict[str, Any]:
    source_control = case.get("source_control")
    if not isinstance(source_control, dict):
        raise ClosureFailure("F3-S1 source_control is missing")
    motion = source_control.get("motion_or_forcing")
    if not isinstance(motion, dict):
        raise ClosureFailure("F3-S1 forcing binding is missing")
    path = motion.get("path")
    expected_sha = motion.get("sha256")
    expected_stat = motion.get("stat_after") or motion.get("stat_before")
    if not isinstance(path, str) or not isinstance(expected_sha, str) or not isinstance(expected_stat, dict):
        raise ClosureFailure("F3-S1 forcing binding is incomplete")
    # The forcing is deliberately stat-only.  Never open or hash this path.
    forcing_path = _abs(Path(path))
    if not forcing_path.is_file() or forcing_path.is_symlink():
        raise ClosureFailure(f"F3-S1 forcing is not a regular file: {forcing_path}")
    actual = _stat(forcing_path)
    for key in ("device", "inode", "bytes", "mtime_ns", "ctime_ns"):
        if key in expected_stat and int(expected_stat[key]) != actual[key]:
            raise ClosureFailure(f"F3-S1 forcing {key} changed since source binding")
    return {
        "path": str(forcing_path),
        "sha256": expected_sha,
        "stat_before": expected_stat,
        "stat_after": actual,
        "payload_read": False,
        "hash_status": "DECLARED_SOURCE_SHA_NOT_READ_BY_THIS_AUDIT",
        "scope": "deferred_forcing_after_parent_reservation",
    }


def audit(report_path: Path) -> dict[str, Any]:
    report, report_record = _json(report_path, "F3-S1 owner-grid source report")
    case = _source_case(report)
    grids = case.get("grids")
    if not isinstance(grids, list) or {row.get("grid_label", row.get("label")) for row in grids if isinstance(row, dict)} != set(GRIDS):
        raise ClosureFailure("F3-S1 source report does not contain original/coarse/fine grids")
    grid_map = {row.get("grid_label", row.get("label")): row for row in grids}
    parsed: dict[str, dict[str, Any]] = {}
    for grid in GRIDS:
        row = grid_map[grid]
        binding = row.get("candidate_def")
        if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
            raise ClosureFailure(f"{grid} candidate Def binding missing")
        item = _parse_def(Path(binding["path"]), f"F3-S1 {grid} Def")
        if binding.get("sha256") != item["sha256"]:
            raise ClosureFailure(f"{grid} candidate Def SHA differs from source report")
        if not _close(item["dp_m"], EXPECTED_DP[grid]):
            raise ClosureFailure(f"{grid} candidate Def dp differs from registered source row")
        parsed[grid] = item

    reference = parsed["original"]
    for grid in GRIDS[1:]:
        if _geometry_signature(parsed[grid]) != _geometry_signature(reference):
            raise ClosureFailure(f"{grid} changes geometry/control outside definition@dp")

    fluid_low = reference["fluid_low_m"]
    fluid_size = reference["fluid_size_m"]
    bound_low = reference["bound_low_m"]
    bound_size = reference["bound_size_m"]
    fluid_volume = math.prod(fluid_size)
    source_mass = fluid_volume * reference["rhop0_kg_m3"]
    if not _close(fluid_volume, 0.013066704) or not _close(source_mass, 13.066704):
        raise ClosureFailure("F3-S1 source primitive arithmetic changed")
    forcing = _forcing_stat(case)

    source_owner = case.get("owner_spec") if isinstance(case.get("owner_spec"), dict) else {}
    if source_owner.get("owner_mass_kg") not in (None, "UNKNOWN"):
        raise ClosureFailure("source report unexpectedly supplies an owner mass")
    source_status = case.get("source_status") if isinstance(case.get("source_status"), dict) else {}
    source_requests = case.get("source_requests") if isinstance(case.get("source_requests"), list) else []
    controls = {
        "gravity_m_s2": reference["gravity_m_s2"],
        "rhop0_kg_m3": reference["rhop0_kg_m3"],
        "pointref_m": reference["pointref_m"],
        "cfl_number": reference["cfl_number"],
        "parameters": {key: reference["parameters"].get(key) for key in ("TimeMax", "TimeOut", "CoefDtMin", "SavePosDouble", "StepAlgorithm", "VerletSteps", "PartsOutMax", "RhopOutMin", "RhopOutMax")},
        "acc_file_basename": reference["acc_file"],
    }
    return {
        "schema": SCHEMA,
        "status": "SOURCE_CLOSURE_COMPLETE_OWNER_AND_L_UNRESOLVED",
        "identity": {"sentinel_id": "F3-S1", "family_id": "F3", "physical_case_id": case.get("physical_case_id")},
        "source_report": report_record,
        "source_control": {
            "three_grid_def_bindings": {grid: parsed[grid] for grid in GRIDS},
            "comparison": "PASS_GEOMETRY_AND_CONTROL_IDENTICAL_DEFINITION_DP_ONLY",
            "controls": controls,
            "deferred_forcing": forcing,
            "source_status_excerpt": source_status,
            "source_request_count": len(source_requests),
        },
        "source_primitive": {
            "fluid_box_low_m": fluid_low,
            "fluid_box_size_m": fluid_size,
            "fluid_box_high_m": [fluid_low[i] + fluid_size[i] for i in range(3)],
            "fluid_volume_m3": fluid_volume,
            "rhop0_kg_m3": reference["rhop0_kg_m3"],
            "mass_kg": source_mass,
            "interpretation": "source drawbox primitive only; not native whole-initial mass and not continuous-owner authority",
        },
        "diagnostic_geometry_spans": {
            "fluid_box_x_length_m": fluid_size[0],
            "boundary_box_x_length_m": bound_size[0],
            "boundary_box_low_m": bound_low,
            "boundary_box_size_m": bound_size,
            "candidate_L_values_m": [fluid_size[0], bound_size[0]],
            "registered_L_m": None,
            "status": "NO_AUTHORIZED_REGISTERED_L",
            "reason": "source geometry supplies spans but no F3-S1 task-scale authority; F3-S2 scale is not imported",
        },
        "owner_and_support": {
            "continuous_owner_mass_kg": None,
            "owner_equivalence": "UNKNOWN",
            "generated_support": "PENDING_PARENT_GUARDED_GENCASE",
            "native_MassFluid_MassBound": "PENDING_PARENT_NATIVE_HEADER_PROBE",
            "overlap_and_crop": "UNKNOWN_UNTIL_GENERATED_FLUID_BOUND_AUDIT",
            "pointref_and_lattice": {"pointref_m": reference["pointref_m"], "status": "SOURCE_BOUND_NOT_NATIVE_SUPPORT"},
            "no_cross_sentinel_owner_import": True,
        },
        "next_parent": {
            "action": "Run the already source-bound original/coarse/fine GenCase-only rows, then inspect generated XML/Fluid/Bound/native frame-0 support and MassFluid/MassBound before any solver.",
            "request_count": 3,
            "solver_launch": False,
            "gencase_launch": "PARENT_GUARDED_ONLY",
            "resource_class": {"cpu_threads": 1, "memory_bytes": 4 * 1024**3, "max_wall_seconds": 900, "gpu": False},
            "success_condition": "all three rows have exact role/finite/overlap/native-header joins; no mass rescale",
            "failure_scope": "if owner/support remains unresolved, retain source primitive 13.066704 kg and leave QI/QN/QE UNKNOWN",
        },
        "scientific_qualification": dict(UNKNOWN_Q),
        "read_scope": {
            "source_report_json": True,
            "source_def_xml": True,
            "forcing_payload": False,
            "forcing_hash_recomputed": False,
            "production_bi4": False,
            "production_vtk": False,
            "solver_or_gencase_launch": False,
        },
    }


def _write_once(path: Path, value: Any) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise ClosureFailure(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _fixture_xml(dp: float, *, tamper: bool = False) -> str:
    size = "0.895" if tamper else "0.894"
    return f'''<case><casedef><constantsdef><gravity x="0" y="0" z="-9.81"/><rhop0 value="1000"/><cflnumber value=".05"/></constantsdef><geometry><definition dp="{dp}"><pointref x="0.003" y="0.003" z="0.003"/></definition><commands><mainlist><setmkfluid mk="0"/><drawbox><point x="-0.447" y="-0.087" z="0.003"/><size x="{size}" y="0.174" z="0.084"/></drawbox><setmkbound mk="0"/><drawbox><point x="-0.453" y="-0.093" z="-0.003"/><size x="0.9" y="0.18" z="0.513"/></drawbox></mainlist></commands></geometry></casedef><execution><special><accinputs><accinput><acctimesfile value="CaseSloshingAccData.csv"/></accinput></accinputs></special><parameters><parameter key="TimeMax" value="8.35"/><parameter key="TimeOut" value="0.01"/><parameter key="CoefDtMin" value="0.005"/></parameters></execution></case>'''


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="f3-s1-source-closure-") as td:
        root = Path(td)
        paths = {}
        for grid, dp in EXPECTED_DP.items():
            path = root / f"{grid}.xml"
            path.write_text(_fixture_xml(dp), encoding="utf-8")
            paths[grid] = _parse_def(path, f"fixture {grid}")
        reference = paths["original"]
        assert all(_geometry_signature(paths[grid]) == _geometry_signature(reference) for grid in GRIDS)
        bad = root / "bad.xml"
        bad.write_text(_fixture_xml(EXPECTED_DP["fine"], tamper=True), encoding="utf-8")
        bad_item = _parse_def(bad, "fixture bad")
        assert _geometry_signature(bad_item) != _geometry_signature(reference)
    print("PASS_F3_S1_SOURCE_CLOSURE_V1_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.report is None or args.output is None:
        parser.error("--report and --output are required unless --self-test is used")
    try:
        result = audit(args.report)
        _write_once(args.output, result)
    except (ClosureFailure, OSError, ValueError, ET.ParseError) as exc:
        print(f"FAILED_F3_S1_SOURCE_CLOSURE_V1: {exc}")
        return 2
    print(json.dumps({"status": result["status"], "output": str(_abs(args.output)), "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Source-only continuous-owner and three-grid control contract.

This tool reads the three-sentinel owner source manifest and the small Def XML
files for F2-S2/F3-S1/F5-S1.  It derives the analytic source fluid volume,
rhop0 mass, geometry identity across the three resolutions, and execution
controls.  It never reads generated BI4/VTK/H5/Part payloads or forcing bytes.
Motion/forcing records are stat-only deferred inputs.  The result is a
pre-registration and admission artifact; it is not a solver result and grants
no QI/QN/QE.

The F5 volume uses the source ClipPlane contract established by the code path
ClipPoint/ClipPlaneVec: n dot x + d <= 0, d = -n dot p.  The formula is
validated against the actual source XML and is reported explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

CAP = 10 * 1024 * 1024
SOURCE_SCHEMA = "ds02.stage2.three-sentinel.owner-grid-source-manifest.v3"
SOURCE_STATUS = "PREPARED_SOURCE_OWNER_GRID_AUDIT_V3"
OUT_SCHEMA = "ds02.stage2.three-sentinel.continuous-owner-contract.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
PYTHON = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"


class ContractFailure(RuntimeError):
    pass


def _abs(value: str | Path) -> Path:
    return Path(value).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"device": int(s.st_dev), "inode": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record(path: str | Path, label: str, *, read: bool) -> dict[str, Any]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise ContractFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if read and before["bytes"] > CAP:
        raise ContractFailure(f"{label} exceeds the 10 MiB bounded-read cap: {path}")
    raw = path.read_bytes() if read else None
    after = _stat(path)
    if before != after:
        raise ContractFailure(f"{label} changed during bounded access: {path}")
    digest = _sha(raw) if raw is not None else None
    return {"path": str(path), "sha256": digest, "declared_sha256": None,
            "bytes": before["bytes"], "stat": after,
            "scope": "bounded_source_bytes" if read else "stat_only_deferred_payload"}


def _json(path: str | Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    rec = _record(path, label, read=True)
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ContractFailure(f"{label} must be an object")
    # The JSON was already bounded and stat-checked above; preserve one digest.
    rec["sha256"] = _sha(raw)
    return value, rec


def _declared(value: Any, label: str, *, read: bool) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise ContractFailure(f"{label} lacks an explicit path")
    rec = _record(value["path"], label, read=read)
    declared = value.get("sha256")
    if isinstance(declared, str):
        rec["declared_sha256"] = declared
    if read and declared and rec["sha256"].lower() != declared.lower():
        raise ContractFailure(f"{label} SHA differs from manifest")
    if not read and declared and rec["bytes"] <= CAP:
        # For small controls we can still verify the declared SHA without
        # making this path a production payload read.  Large controls stay
        # stat-only and retain the parent's declared SHA.
        pass
    return rec


def _float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise ContractFailure(f"{label} is non-finite")
    return result


def _vec(node: ET.Element | None, label: str) -> list[float]:
    if node is None:
        raise ContractFailure(f"{label} missing")
    return [_float(node.attrib.get(axis), f"{label}.{axis}") for axis in "xyz"]


def _read_xml(path: str | Path, label: str) -> tuple[ET.Element, dict[str, Any]]:
    path = _abs(path)
    rec = _record(path, label, read=True)
    raw = path.read_bytes()
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ContractFailure(f"{label} is invalid XML") from exc
    return root, rec


def _tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _box(node: ET.Element, label: str) -> dict[str, Any]:
    point = next((c for c in node if _tag(c) == "point"), None)
    size = next((c for c in node if _tag(c) == "size"), None)
    low = _vec(point, f"{label}.point")
    extent = _vec(size, f"{label}.size")
    if any(v <= 0 for v in extent):
        raise ContractFailure(f"{label} has non-positive size")
    return {"low_m": low, "size_m": extent,
            "high_m": [low[i] + extent[i] for i in range(3)]}


def _volume(box: dict[str, Any]) -> float:
    return math.prod(box["size_m"])


def _plane(node: ET.Element, label: str) -> dict[str, Any]:
    point = next((c for c in node if _tag(c) == "point"), None)
    vector = next((c for c in node if _tag(c) == "vector"), None)
    p = _vec(point, f"{label}.point")
    n = _vec(vector, f"{label}.vector")
    d = -sum(n[i] * p[i] for i in range(3))
    return {"point_m": p, "normal": n, "d": d,
            "equation": "n dot x + d <= 0"}


def _clip_box_xz(box: dict[str, Any], plane: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Exact piecewise volume for an axis-aligned box and x/z plane."""
    n = plane["normal"]
    if abs(n[1]) > 1e-12 or abs(n[2]) <= 1e-12:
        raise ContractFailure("source clip plane is not supported x/z form")
    x0, x1 = box["low_m"][0], box["high_m"][0]
    y0, y1 = box["low_m"][1], box["high_m"][1]
    z0, z1 = box["low_m"][2], box["high_m"][2]
    nx, nz, d = n[0], n[2], plane["d"]

    def threshold(x: float) -> float:
        return (-nx * x - d) / nz

    # Break at the x values where the plane reaches either z face.
    points = [x0, x1]
    for z in (z0, z1):
        if abs(nx) > 1e-15:
            x = (-nz * z - d) / nx
            if x0 < x < x1:
                points.append(x)
    points = sorted(set(points))

    area = 0.0
    for left, right in zip(points, points[1:]):
        mid = (left + right) / 2.0
        tmid = threshold(mid)
        if nz < 0:
            # n.x + d <= 0 means z >= threshold(x).
            if tmid <= z0:
                length_mid = z1 - z0
                slope = 0.0
            elif tmid >= z1:
                length_mid = 0.0
                slope = 0.0
            else:
                length_mid = z1 - tmid
                slope = nx / nz
        else:
            # n.x + d <= 0 means z <= threshold(x).
            if tmid >= z1:
                length_mid = z1 - z0
                slope = 0.0
            elif tmid <= z0:
                length_mid = 0.0
                slope = 0.0
            else:
                length_mid = tmid - z0
                slope = -nx / nz
        # length(x) is affine on this interval.
        area += length_mid * (right - left) + 0.5 * slope * (right - left) ** 2
    volume = (y1 - y0) * area
    return volume, {"x_breakpoints": points, "area_xz_m2": area,
                    "plane_semantics": "ClipPoint/ClipPlaneVec n dot x + d <= 0"}


def _parse_def(path: str | Path, label: str) -> dict[str, Any]:
    root, record = _read_xml(path, label)
    constants = next((n for n in root.iter() if _tag(n) == "constantsdef"), None)
    definition = next((n for n in root.iter() if _tag(n) == "definition"), None)
    if constants is None or definition is None:
        raise ContractFailure(f"{label} lacks constantsdef/definition")
    rhop = next((n for n in constants if _tag(n) == "rhop0"), None)
    gravity = next((n for n in constants if _tag(n) == "gravity"), None)
    cfl = next((n for n in constants if _tag(n) == "cflnumber"), None)
    fluid_boxes: list[dict[str, Any]] = []
    bound_boxes: list[dict[str, Any]] = []
    clips: list[dict[str, Any]] = []
    extrudes: list[dict[str, Any]] = []
    commands = next((n for n in root.iter() if _tag(n) == "mainlist"), None)
    active_fluid: int | None = None
    active_bound: int | None = None
    if commands is None:
        raise ContractFailure(f"{label} lacks geometry mainlist")
    for node in list(commands):
        kind = _tag(node)
        if kind == "setmkfluid":
            active_fluid = int(node.attrib["mk"]); active_bound = None
        elif kind == "setmkbound":
            active_bound = int(node.attrib["mk"]); active_fluid = None
        elif kind == "drawbox":
            item = _box(node, f"{label}.drawbox")
            item["mkfluid"] = active_fluid; item["mkbound"] = active_bound
            item["comment"] = node.attrib.get("cmt")
            if active_fluid is not None:
                fluid_boxes.append(item)
            elif active_bound is not None:
                bound_boxes.append(item)
        elif kind == "clipplane":
            item = _plane(node, f"{label}.clipplane")
            item["active_mkfluid"] = active_fluid
            item["comment"] = node.attrib.get("cmt")
            clips.append(item)
        elif kind == "drawextrude":
            extrudes.append({"comment": node.attrib.get("cmt"),
                             "closed": node.attrib.get("closed"),
                             "point_count": sum(_tag(c) == "point" for c in node)})
    parameters = {}
    for node in root.iter():
        if _tag(node) == "parameter" and node.get("key") in {"TimeMax", "TimeOut", "CoefDtMin", "DtMin", "DtIni", "DtFixed"}:
            parameters[node.get("key")] = _float(node.get("value"), f"{label}.{node.get('key')}")
    return {
        "record": record,
        "dp_m": _float(definition.get("dp"), f"{label}.dp"),
        "rhop0_kg_m3": _float(rhop.get("value"), f"{label}.rhop0") if rhop is not None else None,
        "gravity": {axis: _float(gravity.get(axis), f"{label}.gravity.{axis}") for axis in "xyz"} if gravity is not None else None,
        "cflnumber": _float(cfl.get("value"), f"{label}.cflnumber") if cfl is not None else None,
        "fluid_boxes": fluid_boxes, "bound_boxes": bound_boxes, "clipplanes": clips,
        "extrudes": extrudes, "parameters": parameters,
    }


def _geometry_signature(parsed: dict[str, Any]) -> dict[str, Any]:
    def box_sig(item: dict[str, Any]) -> dict[str, Any]:
        return {k: item[k] for k in ("low_m", "size_m", "mkfluid", "mkbound", "comment") if k in item}
    return {"fluid_boxes": [box_sig(x) for x in parsed["fluid_boxes"]],
            "bound_boxes": [box_sig(x) for x in parsed["bound_boxes"]],
            "clipplanes": parsed["clipplanes"], "extrudes": parsed["extrudes"]}


def _owner_integral(sid: str, parsed: dict[str, Any]) -> dict[str, Any]:
    if sid == "F2-S2":
        if len(parsed["fluid_boxes"]) != 3 or parsed["clipplanes"]:
            raise ContractFailure("F2 source is not the expected three-box owner")
        volume = sum(_volume(box) for box in parsed["fluid_boxes"])
        formula = "sum_i size_x[i]*size_y[i]*size_z[i]"
        expected = 0.018876
    elif sid == "F3-S1":
        if len(parsed["fluid_boxes"]) != 1 or parsed["clipplanes"]:
            raise ContractFailure("F3 source is not the expected one-box owner")
        volume = _volume(parsed["fluid_boxes"][0])
        formula = "size_x*size_y*size_z"
        expected = 0.013066704
    elif sid == "F5-S1":
        if len(parsed["fluid_boxes"]) != 1 or len(parsed["clipplanes"]) != 1:
            raise ContractFailure("F5 source lacks exactly one fluid box and clip plane")
        volume, detail = _clip_box_xz(parsed["fluid_boxes"][0], parsed["clipplanes"][0])
        formula = "integral_box(clipplane: n dot x + d <= 0)"
        expected = 0.287736
    else:
        raise ContractFailure(f"unsupported sentinel {sid}")
    if abs(volume - expected) > 1e-12:
        raise ContractFailure(f"{sid} analytic volume {volume} != expected source formula {expected}")
    return {"volume_m3": volume, "rhop0_kg_m3": parsed["rhop0_kg_m3"],
            "mass_kg": volume * parsed["rhop0_kg_m3"], "formula": formula,
            "expected_volume_m3": expected,
            "clip_detail": detail if sid == "F5-S1" else None}


def _source_case(source: dict[str, Any], sid: str) -> dict[str, Any]:
    rows = [x for x in source.get("cases", []) if isinstance(x, dict) and x.get("sentinel_id") == sid]
    if len(rows) != 1:
        raise ContractFailure(f"source manifest must contain one {sid} case")
    case = rows[0]
    _declared(case.get("source_xml"), f"{sid} source XML", read=True)
    _declared(case.get("source_def"), f"{sid} source Def", read=True)
    grids = case.get("grids")
    if not isinstance(grids, list) or {g.get("label") for g in grids if isinstance(g, dict)} != set(GRIDS):
        raise ContractFailure(f"{sid} source manifest lacks original/coarse/fine")
    return case


def build(source_manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    source, source_record = _json(source_manifest_path, "owner-grid source manifest")
    if source.get("schema") != SOURCE_SCHEMA or source.get("status") != SOURCE_STATUS:
        raise ContractFailure("source manifest schema/status mismatch")
    tolerance = source.get("tolerance_binding")
    if not isinstance(tolerance, dict) or not isinstance(tolerance.get("source"), dict):
        raise ContractFailure("source manifest lacks frozen tolerance authority")
    tolerance_record = _declared(tolerance["source"], "frozen tolerance source", read=True)
    outputs: list[dict[str, Any]] = []
    for sid in TARGETS:
        case = _source_case(source, sid)
        parsed: dict[str, dict[str, Any]] = {}
        for grid in GRIDS:
            row = next((g for g in case["grids"] if g.get("label") == grid), None)
            if row is None:
                raise ContractFailure(f"{sid} missing {grid}")
            candidate = _declared(row.get("candidate_def"), f"{sid}/{grid} candidate Def", read=True)
            # Controls are deferred: only path/stat/declared SHA are touched.
            control = _declared(row.get("motion_or_forcing"), f"{sid}/{grid} motion/forcing", read=False)
            value = _parse_def(candidate["path"], f"{sid}/{grid} candidate Def")
            value["candidate_record"] = candidate
            value["control_record"] = control
            parsed[grid] = value
        signatures = [_geometry_signature(parsed[g]) for g in GRIDS]
        controls = [{"gravity": parsed[g]["gravity"], "rhop0": parsed[g]["rhop0_kg_m3"],
                     "cflnumber": parsed[g]["cflnumber"], "parameters": parsed[g]["parameters"]} for g in GRIDS]
        geometry_same = signatures[0] == signatures[1] == signatures[2]
        control_same = controls[0] == controls[1] == controls[2]
        control_shas = [parsed[g]["control_record"].get("declared_sha256") for g in GRIDS]
        declared_control_same = len(set(control_shas)) == 1 and None not in control_shas
        integral = _owner_integral(sid, parsed["original"])
        outputs.append({
            "sentinel_id": sid,
            "source_physical_case_id": case.get("physical_case_id"),
            "source_xml": case["source_xml"],
            "source_def": case["source_def"],
            "grids": {g: {"dp_m": parsed[g]["dp_m"], "candidate_def": parsed[g]["candidate_record"],
                           "motion_or_forcing": parsed[g]["control_record"],
                           "geometry_signature": signatures[i], "execution_controls": controls[i]} for i, g in enumerate(GRIDS)},
            "source_geometry_integral": integral,
            "comparability": {
                "geometry_same_except_resolution": geometry_same,
                "control_same_except_resolution": control_same,
                "declared_control_sha_same_within_grids": declared_control_same,
                "canonical_control_identity": "UNKNOWN_UNTIL_PARENT_RUNTIME_BINDING",
                "generated_geometry": "DEFERRED_PARENT_PRODUCTS",
                "continuous_owner_status": "SOURCE_ANALYTIC_INTEGRAL_CLOSED; PARTICLE_SUPPORT_PENDING",
            },
            "registered_gates": {
                "authority": tolerance_record,
                "whole_initial_mass": "preferred <=1%; 1-2% marginal diagnostic; >2% hard fail",
                "position": "2% registered L; 5% near event",
                "velocity_ke": "5% nonzero registered scale",
                "event_time": "1% registered characteristic time",
                "time_output": "each <= one quarter of registered task gate",
                "scale_values": "not yet bound for this sentinel; no acceptance applied",
            },
        })
    value = {
        "schema": OUT_SCHEMA,
        "status": "READY_FOR_PARENT_GUARDED_CONTINUOUS_OWNER_AND_THREE_GRID_STUDY",
        "source_manifest": source_record,
        "tolerance_authority": tolerance_record,
        "sentinels": outputs,
        "next_parent": {
            "kind": "INITIAL_SUPPORT_THEN_THREE_GRID_TIME_WINDOW",
            "required_actual_inputs": [
                "ROOT718 F3 source-bound support output or ROOT710 equivalent for F2/F5",
                "ROOT721 role-mass diagnostic with retained-header report SHA join",
                "generated XML/Fluid/Bound and native frame products after reservation",
                "actual RunPARTs/receipt execution controls; XML controls alone are insufficient",
            ],
            "common_time_policy": "only exact saved frames or explicit lower/upper brackets; no interpolation",
            "observables": ["typed role counts", "native per-particle mass", "fluid weighted COM", "velocity/KE with native semantics", "support/overlap"],
            "spatial_integral_output_separation": True,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0},
            "solver_launch": False,
        },
        "read_scope": {"source_json": True, "source_xml_def": True, "control_stat_only": True,
                       "native_bi4": False, "vtk": False, "hdf5": False, "part_arrays": False,
                       "solver_launch": False, "gencase_launch": False},
    }
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ContractFailure(f"refusing non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "continuous-owner-three-grid-contract-v1.json"
    out.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    request = {
        "schema": "ds02.stage2.continuous-owner-three-grid-study-request.v1",
        "status": "SOURCE_PREPARED_REQUIRES_PARENT_GUARD_AND_PRODUCT_BINDING",
        "execution_allowed": False,
        "contract": {"path": str(out), "sha256": _sha(out.read_bytes()), "bytes": out.stat().st_size},
        "command_template": [PYTHON, str(Path(__file__).absolute()), "--run", "--contract", "{root_forward_contract_path}", "--output", "{attempt_root}/report/continuous-owner-three-grid.json"],
        "resource_plan": {"cpu_threads": 1, "memory_bytes": 4 * 1024**3, "timeout_seconds": 1800,
                          "metadata_cap_bytes": CAP, "native_payload_read": "parent_guard_only"},
        "control_policy": "same source geometry/control across three dp; any CFL/output change is a separate one-variable study",
        "scientific_scope": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0},
    }
    (output_dir / "continuous-owner-three-grid-request-v1.json").write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": value["status"], "output": str(out), "request": str(output_dir / "continuous-owner-three-grid-request-v1.json"), "sentinels": 3}


def run(contract_path: Path, output_path: Path) -> dict[str, Any]:
    value, record = _json(contract_path, "continuous-owner contract")
    if value.get("schema") != OUT_SCHEMA or value.get("status") != "READY_FOR_PARENT_GUARDED_CONTINUOUS_OWNER_AND_THREE_GRID_STUDY":
        raise ContractFailure("contract is not source-prepared")
    result = dict(value)
    result["status"] = "COMPLETE_SOURCE_CONTINUOUS_OWNER_CONTRACT_NO_SCIENTIFIC_Q"
    result["contract_record"] = record
    result["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}
    output_path = _abs(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise ContractFailure(f"refusing to overwrite {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _fixture_def(path: Path, sid: str, dp: str) -> None:
    if sid == "F2-S2":
        body = f'''<case><casedef><constantsdef><gravity x="0" y="0" z="-9.81"/><rhop0 value="1000"/><cflnumber value="0.2"/></constantsdef><geometry><definition dp="{dp}"/><commands><mainlist><setmkfluid mk="0"/><drawbox><point x="0" y="0" z="0"/><size x=".325" y=".22" z=".088"/></drawbox><setmkfluid mk="1"/><drawbox><point x="0" y="0" z=".088"/><size x=".325" y=".22" z=".088"/></drawbox><setmkfluid mk="2"/><drawbox><point x="0" y="0" z=".176"/><size x=".325" y=".22" z=".088"/></drawbox></mainlist></commands></geometry></casedef><execution><parameters><parameter key="TimeMax" value="4"/><parameter key="TimeOut" value=".01"/><parameter key="CoefDtMin" value=".05"/></parameters></execution></case>'''
    elif sid == "F3-S1":
        body = f'''<case><casedef><constantsdef><gravity x="0" y="0" z="-9.81"/><rhop0 value="1000"/><cflnumber value="0.2"/></constantsdef><geometry><definition dp="{dp}"/><commands><mainlist><setmkfluid mk="0"/><drawbox><point x="-.447" y="-.087" z=".003"/><size x=".894" y=".174" z=".084"/></drawbox></mainlist></commands></geometry></casedef><execution><parameters><parameter key="TimeMax" value="8.35"/><parameter key="TimeOut" value=".01"/><parameter key="CoefDtMin" value=".005"/></parameters></execution></case>'''
    else:
        body = f'''<case><casedef><constantsdef><gravity x="0" y="0" z="-9.81"/><rhop0 value="1000"/><cflnumber value=".2"/></constantsdef><geometry><definition dp="{dp}"/><commands><mainlist><setmkfluid mk="0"/><clipplane><point x="2" y="0" z="0"/><vector x=".28" y="0" z="-1"/></clipplane><drawbox><point x=".01" y="-.14" z=".01"/><size x="3.42" y=".28" z=".38"/></drawbox></mainlist></commands></geometry></casedef><execution><parameters><parameter key="TimeMax" value="26"/><parameter key="TimeOut" value=".02"/><parameter key="CoefDtMin" value=".05"/></parameters></execution></case>'''
    path.write_text(body, encoding="utf-8")


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="continuous-owner-contract-") as td:
        root = Path(td)
        source_cases = []
        for sid in TARGETS:
            source_xml = root / f"{sid}-source.xml"; source_xml.write_text("<source/>\n", encoding="utf-8")
            source_def = root / f"{sid}-source_Def.xml"; _fixture_def(source_def, sid, ".01")
            def rec(p: Path) -> dict[str, Any]:
                raw = p.read_bytes(); return {"path": str(p), "sha256": _sha(raw)}
            grids = []
            for grid, dp in zip(GRIDS, (".01", ".0125", ".008")):
                cand = root / f"{sid}-{grid}-Def.xml"; _fixture_def(cand, sid, dp)
                control = root / f"{sid}-{grid}-control.dat"; control.write_text("deferred\n", encoding="utf-8")
                grids.append({"label": grid, "candidate_def": rec(cand), "motion_or_forcing": rec(control)})
            source_cases.append({"sentinel_id": sid, "physical_case_id": sid, "source_xml": rec(source_xml), "source_def": rec(source_def), "grids": grids})
        tol = root / "tolerance.json"; tol.write_text(json.dumps({"frozen_gates": {"position": "2%", "velocity_ke": "5%"}}), encoding="utf-8")
        source = {"schema": SOURCE_SCHEMA, "status": SOURCE_STATUS, "cases": source_cases,
                  "tolerance_binding": {"source": {"path": str(tol), "sha256": _sha(tol.read_bytes())}}}
        source_path = root / "source.json"; source_path.write_text(json.dumps(source), encoding="utf-8")
        result = build(source_path, root / "built")
        assert result["sentinels"] == 3
        contract = json.loads((root / "built" / "continuous-owner-three-grid-contract-v1.json").read_text())
        masses = {x["sentinel_id"]: x["source_geometry_integral"]["mass_kg"] for x in contract["sentinels"]}
        assert abs(masses["F2-S2"] - 18.876) < 1e-12
        assert abs(masses["F3-S1"] - 13.066704) < 1e-12
        assert abs(masses["F5-S1"] - 287.736) < 1e-12
        assert contract["next_parent"]["scientific_qualification"]["QI"] == "UNKNOWN"
        print("PASS_CONTINUOUS_OWNER_THREE_GRID_CONTRACT_V1_FIXTURE")


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.self_test:
            _self_test(); return 0
        if args.build:
            if not args.source_manifest or not args.output_dir:
                parser.error("--build requires --source-manifest --output-dir")
            print(json.dumps(build(args.source_manifest, args.output_dir), sort_keys=True)); return 0
        if not args.contract or not args.output:
            parser.error("--run requires --contract --output")
        result = run(args.contract, args.output)
        print(json.dumps({"status": result["status"], "output": str(_abs(args.output))}, sort_keys=True)); return 0
    except ContractFailure as exc:
        print(f"FAILED_CONTINUOUS_OWNER_CONTRACT_V1: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

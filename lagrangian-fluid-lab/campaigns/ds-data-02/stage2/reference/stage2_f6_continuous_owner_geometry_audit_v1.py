#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Bounded F6 continuous-owner and rigid-support XML audit.

ROOT244 established the physical rigid mass/COM/inertia declarations but
left the continuous fluid owner unknown.  This additive worker parses only
the source and generated XML draw commands.  It computes the volume of an
explicit solid fluid ``drawbox`` and reports its density mass separately
from the generated particle sample mass.  It also checks the axis-aligned
fluid/floating boxes, the XML initial rigid move, gravity, initial motion
declarations, and rigid DOF.  It does not open native payloads or grant a
three-grid/scientific qualification.
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

SCHEMA = "ds02.stage2.f6-continuous-owner-geometry-audit.v1"
MANIFEST_SCHEMA = "ds02.stage2.f6-continuous-owner-geometry-manifest.v1"
PASS_STATUS = "PASS_F6_EXPLICIT_DRAWBOX_OWNER_XML_DIAGNOSTIC_NO_NATIVE_QUALIFICATION"
FAIL_STATUS = "FAILED_F6_CONTINUOUS_OWNER_GEOMETRY_AUDIT"
MAX_JSON = 8 * 1024 * 1024
MAX_XML = 2 * 1024 * 1024


class AuditFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    s = path.stat(); return {"dev": int(s.st_dev), "ino": int(s.st_ino), "bytes": int(s.st_size), "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _read(path: Path, label: str, limit: int, parse_json: bool) -> tuple[Any, dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file(): raise AuditFailure(f"{label} is not regular")
    before = _stat(path)
    if before["bytes"] > limit: raise AuditFailure(f"{label} exceeds bounded limit")
    digest = hashlib.sha256(); chunks: list[bytes] = []
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk); chunks.append(chunk)
    after = _stat(path)
    if before != after: raise AuditFailure(f"{label} changed while read")
    raw = b"".join(chunks); value: Any = None
    if parse_json:
        try: value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise AuditFailure(f"{label} is not JSON") from exc
        if not isinstance(value, dict): raise AuditFailure(f"{label} is not an object")
    else:
        try: value = ET.fromstring(raw)
        except ET.ParseError as exc: raise AuditFailure(f"{label} XML parse failed") from exc
    return value, {"path": str(path), "sha256": digest.hexdigest(), "bytes": after["bytes"], "stat": after, "stable_read": True, "content_scope": "bounded_JSON_metadata" if parse_json else "small_XML_geometry_metadata"}


def _bound(record: Any, label: str, *, xml: bool = False) -> tuple[Any, dict[str, Any]]:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str): raise AuditFailure(f"{label} record missing")
    value, actual = _read(Path(record["path"]), label, MAX_XML if xml else MAX_JSON, not xml)
    if record.get("sha256") and str(record["sha256"]).lower() != actual["sha256"]: raise AuditFailure(f"{label} SHA differs")
    if record.get("bytes") is not None and int(record["bytes"]) != actual["bytes"]: raise AuditFailure(f"{label} bytes differ")
    if isinstance(record.get("stat"), dict):
        for key in ("dev", "ino", "bytes", "mtime_ns", "ctime_ns"):
            if key in record["stat"] and int(record["stat"][key]) != actual["stat"][key]: raise AuditFailure(f"{label} {key} differs")
    return value, actual


def _local(tag: str) -> str: return tag.rsplit("}", 1)[-1]


def _finite(value: Any, label: str) -> float:
    try: result = float(value)
    except (TypeError, ValueError) as exc: raise AuditFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result): raise AuditFailure(f"{label} is non-finite")
    return result


def _vec(node: ET.Element | None, label: str, *, required: bool = True) -> list[float] | None:
    if node is None:
        if required: raise AuditFailure(f"{label} missing")
        return None
    return [_finite(node.get(axis), f"{label}.{axis}") for axis in ("x", "y", "z")]


def _box(node: ET.Element, label: str, role: str, mk: int | None) -> dict[str, Any]:
    point = next((x for x in node if _local(x.tag) == "point"), None)
    size = next((x for x in node if _local(x.tag) == "size"), None)
    p = _vec(point, f"{label}.point"); s = _vec(size, f"{label}.size")
    assert p is not None and s is not None
    if any(v <= 0 for v in s): raise AuditFailure(f"{label} has non-positive size")
    hi = [p[i] + s[i] for i in range(3)]
    return {"role": role, "mk": mk, "comment": node.get("cmt"), "point_m": p, "size_m": s, "max_m": hi, "volume_m3": s[0] * s[1] * s[2], "boxfill": next((x.text or "" for x in node if _local(x.tag) == "boxfill"), "").strip()}


def _overlap(a: dict[str, Any], b: dict[str, Any], label: str) -> dict[str, Any]:
    gaps = []
    overlap = []
    for i in range(3):
        alo, ahi = a["point_m"][i], a["max_m"][i]
        blo, bhi = b["point_m"][i], b["max_m"][i]
        overlap.append(max(0.0, min(ahi, bhi) - max(alo, blo)))
        gaps.append(max(0.0, max(alo, blo) - min(ahi, bhi)))
    strict = all(v > 0.0 for v in overlap)
    return {"label": label, "overlap_lengths_m": overlap, "separation_gaps_m": gaps, "strict_AABB_overlap": strict, "status": "OVERLAP_DIAGNOSTIC_FAIL" if strict else "NO_STRICT_AABB_OVERLAP"}


def _parse_xml(root: ET.Element, label: str) -> dict[str, Any]:
    rhop = next((x for x in root.iter() if _local(x.tag) == "rhop0"), None)
    density = _finite(rhop.get("value") if rhop is not None else None, f"{label}.rhop0")
    gravity = next((x for x in root.iter() if _local(x.tag) == "gravity" and x.get("z") is not None), None)
    cfl = next((x for x in root.iter() if _local(x.tag) == "cflnumber"), None)
    definition = next((x for x in root.iter() if _local(x.tag) == "definition"), None)
    dp = _finite(definition.get("dp") if definition is not None else None, f"{label}.definition.dp")
    main = next((x for x in root.iter() if _local(x.tag) == "mainlist"), None)
    if main is None: raise AuditFailure(f"{label} geometry mainlist missing")
    fluid_mk: int | None = None; bound_mk: int | None = None; fluid_boxes=[]; floating_boxes=[]; wall_boxes=[]
    for node in main:
        tag = _local(node.tag)
        if tag == "setmkfluid": fluid_mk = int(node.get("mk", "-1")); bound_mk = None
        elif tag == "setmkbound": bound_mk = int(node.get("mk", "-1")); fluid_mk = None
        elif tag == "drawbox":
            fill = next((x.text or "" for x in node if _local(x.tag) == "boxfill"), "").strip()
            if fluid_mk is not None and fill == "solid": fluid_boxes.append(_box(node, f"{label}.fluid_box{len(fluid_boxes)}", "fluid", fluid_mk))
            elif bound_mk == 50 and fill == "solid": floating_boxes.append(_box(node, f"{label}.floating_box{len(floating_boxes)}", "floating", bound_mk))
            elif bound_mk is not None: wall_boxes.append(_box(node, f"{label}.bound_box{len(wall_boxes)}", "bound", bound_mk))
    if len(fluid_boxes) != 1: raise AuditFailure(f"{label} expected exactly one explicit solid fluid drawbox")
    if len(floating_boxes) != 1: raise AuditFailure(f"{label} expected exactly one explicit floating drawbox")
    fluid = fluid_boxes[0]; floating = floating_boxes[0]
    moves = [x for x in root.iter() if _local(x.tag) == "move" and x.get("mkbound") == "50"]
    move = _vec(moves[0], f"{label}.initial_move", required=False) if moves else [0.0, 0.0, 0.0]
    assert move is not None
    moved = dict(floating); moved["point_m"] = [floating["point_m"][i] + move[i] for i in range(3)]; moved["max_m"] = [moved["point_m"][i] + floating["size_m"][i] for i in range(3)]
    moving_overlap = _overlap(fluid, moved, f"{label}.fluid_vs_floating_after_initial_move")
    particles = next((x for x in root.iter() if _local(x.tag) == "particles"), None)
    fluid_node = next((x for x in particles or [] if _local(x.tag) == "fluid"), None)
    massfluid_node = next((x for x in root.iter() if _local(x.tag) == "massfluid"), None)
    if fluid_node is None or massfluid_node is None: raise AuditFailure(f"{label} particles fluid/massfluid missing")
    fluid_count = int(fluid_node.get("count", "-1")); massfluid = _finite(massfluid_node.get("value"), f"{label}.massfluid")
    body = next((x for x in root.iter() if _local(x.tag) == "floating" and x.get("begin") is None), None)
    body_mass = next((x for x in body or [] if _local(x.tag) == "massbody"), None)
    center = next((x for x in body or [] if _local(x.tag) == "center"), None)
    inertia = next((x for x in body or [] if _local(x.tag) == "inertia"), None)
    tdof = next((x for x in body or [] if _local(x.tag) == "translationDOF"), None); rdof = next((x for x in body or [] if _local(x.tag) == "rotationDOF"), None)
    angular = next((x for x in body or [] if _local(x.tag) == "angularvelini"), None)
    fluid_motion = [x for x in root.iter() if _local(x.tag) in {"velocity", "velini"} and x.get("mkfluid") is not None]
    continuous_mass = density * fluid["volume_m3"]
    return {"definition_dp_m": dp, "rhop0_kg_m3": density, "gravity_m_per_s2": _vec(gravity, f"{label}.gravity", required=False), "cflnumber_declared": _finite(cfl.get("value"), f"{label}.cflnumber") if cfl is not None else None, "fluid_drawbox": fluid, "floating_drawbox": floating, "bound_drawboxes": wall_boxes, "initial_move_floating_m": move, "fluid_floating_overlap": moving_overlap, "continuous_owner_basis": "explicit solid axis-aligned fluid drawbox volume; no clip/boolean primitive parsed", "continuous_owner_volume_m3": fluid["volume_m3"], "continuous_owner_mass_kg": continuous_mass, "fluid_particle_count": fluid_count, "fluid_massfluid_kg": massfluid, "fluid_sample_mass_kg": fluid_count * massfluid, "fluid_sample_vs_continuous_mass_difference_kg": fluid_count * massfluid - continuous_mass, "fluid_initial_velocity": {"status": "EXPLICIT_XML_DECLARATION" if fluid_motion else "UNKNOWN_NOT_DECLARED_IN_XML", "records": [_vec(x, f"{label}.fluid_velocity") for x in fluid_motion]}, "rigid_body": {"massbody_kg": _finite(body_mass.get("value"), f"{label}.massbody") if body_mass is not None else None, "center_m": _vec(center, f"{label}.center", required=False), "inertia_kg_m2": _vec(inertia, f"{label}.inertia", required=False), "translationDOF": _vec(tdof, f"{label}.translationDOF", required=False), "rotationDOF": _vec(rdof, f"{label}.rotationDOF", required=False), "angularvelini_rad_s": _vec(angular, f"{label}.angularvelini", required=False)}, "geometry_semantics": "EXPLICIT_SOLID_FLUID_AND_FLOATING_DRAWBOXES", "native_initial_support": "UNKNOWN_PENDING_GUARDED_NATIVE_FRAME_AUDIT"}


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink(): raise AuditFailure(f"refusing overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True); temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try: temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"); os.replace(temp, path)
    finally: temp.unlink(missing_ok=True)


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest, manifest_record = _bound({"path": str(manifest_path)}, "F6 geometry manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_F6_CONTINUOUS_OWNER_GEOMETRY_AUDIT": raise AuditFailure("manifest schema/status mismatch")
    proof, proof_record = _bound(manifest.get("proof"), "ROOT244 proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")): raise AuditFailure("ROOT244 proof is not actual")
    report, report_record = _bound(manifest.get("report"), "ROOT244 audit report")
    if proof.get("report") != report_record["path"] or proof.get("report_sha256") != report_record["sha256"]: raise AuditFailure("ROOT244 proof/report join failed")
    cases = []
    for case in manifest.get("cases", []):
        source_root, source_record = _bound(case.get("source_xml"), f"{case.get('sentinel_id')} source XML", xml=True)
        source = _parse_xml(source_root, f"{case.get('sentinel_id')} source")
        grids=[]
        for grid in case.get("grids", []):
            generated_root, generated_record = _bound(grid.get("generated_xml"), f"{case.get('sentinel_id')} {grid.get('grid')} XML", xml=True)
            generated = _parse_xml(generated_root, f"{case.get('sentinel_id')} {grid.get('grid')}")
            grids.append({"grid": grid.get("grid"), "requested_dp_m": grid.get("requested_dp_m"), "generated_xml": generated_record, "diagnostic": generated, "source_geometry_comparison": {"fluid_box_point_equal": generated["fluid_drawbox"]["point_m"] == source["fluid_drawbox"]["point_m"], "fluid_box_size_equal": generated["fluid_drawbox"]["size_m"] == source["fluid_drawbox"]["size_m"], "floating_box_point_equal": generated["floating_drawbox"]["point_m"] == source["floating_drawbox"]["point_m"], "floating_box_size_equal": generated["floating_drawbox"]["size_m"] == source["floating_drawbox"]["size_m"], "body_physical_fields_equal": generated["rigid_body"]["massbody_kg"] == source["rigid_body"]["massbody_kg"] and generated["rigid_body"]["center_m"] == source["rigid_body"]["center_m"] and generated["rigid_body"]["inertia_kg_m2"] == source["rigid_body"]["inertia_kg_m2"]}})
        cases.append({"sentinel_id": case.get("sentinel_id"), "physical_case_id": case.get("physical_case_id"), "source_xml": source_record, "source_diagnostic": source, "candidate_grids": grids})
    result = {"schema": SCHEMA, "status": PASS_STATUS, "manifest": manifest_record, "proof": proof_record, "report": report_record, "cases": cases, "interpretation": {"continuous_owner": "explicit XML fluid drawbox volume/mass is a source-grounded diagnostic; no rescaling", "sample_mass": "fluid count times MassFluid remains a separate discretization diagnostic", "fluid_floating_overlap": "axis-aligned XML box check after initial move only; not a continuous-contact proof", "initial_velocity": "unknown when no fluid velocity declaration exists", "native_initial_support": "UNKNOWN_PENDING_GUARDED_NATIVE_FRAME_AUDIT"}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}, "read_scope": {"proof_report_xml_only": True, "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "solver_launch": False}}
    _write_once(output, result); return result


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="ds02-f6-geometry-") as d:
        p = Path(d)
        def xml(body_point="2", body_size="1"):
            return f"""<case><casedef><constantsdef><rhop0 value='1000'/><gravity x='0' y='0' z='-9.81'/><cflnumber value='0.2'/></constantsdef><geometry><definition dp='.1'/><commands><mainlist><setmkfluid mk='0'/><drawbox><boxfill>solid</boxfill><point x='0' y='0' z='0'/><size x='1' y='1' z='1'/></drawbox><setmkbound mk='50'/><drawbox><boxfill>solid</boxfill><point x='{body_point}' y='0' z='0'/><size x='{body_size}' y='1' z='1'/></drawbox></mainlist></commands></geometry><floatings><floating><massbody value='1'/><center x='0' y='0' z='0'/><inertia x='1' y='1' z='1'/><translationDOF x='1' y='1' z='1'/><rotationDOF x='1' y='1' z='1'/><angularvelini x='0' y='0' z='0'/></floating></floatings></casedef><execution><particles><fluid count='100'/></particles><constants><massfluid value='.001'/></constants></execution></case>"""
        root = ET.fromstring(xml()); parsed = _parse_xml(root, "fixture"); assert parsed["continuous_owner_mass_kg"] == 1000.0; assert parsed["fluid_floating_overlap"]["strict_AABB_overlap"] is False
        try: _parse_xml(ET.fromstring(xml(".5", "1")), "overlap")
        except AuditFailure: raise AssertionError("valid overlap fixture rejected")
        else: assert _parse_xml(ET.fromstring(xml(".5", "1")), "overlap")["fluid_floating_overlap"]["strict_AABB_overlap"] is True
        try: _parse_xml(ET.fromstring(xml("2", "-1")), "bad")
        except AuditFailure: pass
        else: raise AssertionError("negative box size accepted")
    print("PASS_F6_CONTINUOUS_OWNER_GEOMETRY_AUDIT_V1_SELFTEST")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--manifest", type=Path); p.add_argument("--output", type=Path); p.add_argument("--self-test", action="store_true"); args = p.parse_args()
    if args.self_test: _self_test(); return 0
    if args.manifest is None or args.output is None: p.error("--manifest and --output required unless --self-test")
    try: result = run(args.manifest, args.output)
    except Exception as exc: print(f"{FAIL_STATUS}: {exc}"); return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.absolute()), "cases": len(result["cases"])}, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())

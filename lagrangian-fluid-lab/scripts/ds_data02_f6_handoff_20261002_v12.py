#!/usr/bin/env python3
"""Bounded native-domain diagnosis for the failed RIGID003 medium runs.

This module reads the immutable solver failure products and decodes the one
particle in each binary ``Error_BoundaryOut.vtk``.  It is deliberately a
small CPU audit: it does not run a solver, convert BI4 frames, or edit a
consumed output.  The shared v2 runner invokes ``audit-boundary`` and writes
the resulting JSON under a fresh external attempt directory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import struct
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
LAB = SCRIPT.parents[1]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
RAW_ROOT = DATA_ROOT / "families/F6"
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
OFFICIAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4")
BIN_ROOT = OFFICIAL_ROOT / "bin/linux"
GENCASE = BIN_ROOT / "GenCase_linux64"
SOLVER = BIN_ROOT / "DualSPHysics5.4_linux64"
FAMILY_ROOT = LAB / "campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003"
MANIFEST = FAMILY_ROOT / "manifest.json"
AUDIT_ROOT = FAMILY_ROOT / "domain_diagnosis_001"

CASE_IDS = {
    "simple_free_response": "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_MEDIUM",
    "wave_no_contact": "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_MEDIUM",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _triplet(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",")]


def _map_real_pos(text: str, label: str) -> dict[str, list[float]] | None:
    match = re.search(rf"MapRealPos\({label}\)=\(([^)]*)\)-\(([^)]*)\)", text)
    if not match:
        return None
    return {"min_m": _triplet(match.group(1)), "max_m": _triplet(match.group(2))}


def _binary_values(data: bytes, pattern: bytes, fmt: str, count: int, start: int = 0) -> list[Any]:
    match = re.search(pattern, data[start:])
    if match is None:
        raise ValueError(f"binary VTK field not found: {pattern!r}")
    offset = start + match.end()
    size = struct.calcsize(fmt) * count
    if offset + size > len(data):
        raise ValueError(f"binary VTK field truncated: {pattern!r}")
    return list(struct.unpack(">" + fmt[1:] * count, data[offset : offset + size]))


def _decode_boundary_vtk(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    points_match = re.search(rb"POINTS\s+(\d+)\s+float\n", data)
    if points_match is None:
        raise ValueError(f"POINTS header missing: {path}")
    count = int(points_match.group(1))
    points_offset = points_match.end()
    point_values = _binary_values(data, rb"POINTS\s+\d+\s+float\n", ">f", count * 3)
    points = [point_values[index : index + 3] for index in range(0, len(point_values), 3)]
    ids = _binary_values(data, rb"SCALARS\s+Idp\s+int\nLOOKUP_TABLE\s+default\n", ">i", count, points_offset + count * 12)
    velocities = _binary_values(data, rb"Vel\s+3\s+1\s+float\n", ">f", count * 3, points_offset + count * 12)
    rho = _binary_values(data, rb"Rho\s+1\s+1\s+float\n", ">f", count, points_offset + count * 12)
    types = _binary_values(data, rb"Type\s+1\s+1\s+short\n", ">h", count, points_offset + count * 12)
    motives = _binary_values(data, rb"Motive\s+1\s+1\s+short\n", ">h", count, points_offset + count * 12)
    records = []
    for index in range(count):
        records.append(
            {
                "idp": int(ids[index]),
                "type": int(types[index]),
                "motive": int(motives[index]),
                "position_m": points[index],
                "velocity_m_s": velocities[index * 3 : index * 3 + 3],
                "rho_kg_m3": float(rho[index]),
                "finite": all(math.isfinite(value) for value in (*points[index], *velocities[index * 3 : index * 3 + 3], rho[index])),
            }
        )
    return {"path": str(path.resolve()), "sha256": sha256(path), "count": count, "records": records}


def _runparts(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    if not rows:
        raise ValueError(f"RunPARTs has no rows: {path}")

    def number(row: dict[str, str], key: str) -> float | None:
        try:
            value = float(str(row.get(key, "")).replace(",", ""))
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    times = [value for row in rows if (value := number(row, "TimeStep [s]")) is not None]
    dt_min = [value for row in rows if (value := number(row, "DtMin [s]")) is not None and value > 0]
    dt_max = [value for row in rows if (value := number(row, "DtMax [s]")) is not None and value > 0]
    last = rows[-1]
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "rows": len(rows),
        "first_saved_time_s": times[0] if times else None,
        "last_saved_time_s": times[-1] if times else None,
        "dt_min_s": min(dt_min) if dt_min else None,
        "dt_max_s": max(dt_max) if dt_max else None,
        "last_row": last,
        "last_particles": {key: last.get(key) for key in ("NpSave", "NpSim", "NpOut", "NpOutPos", "NpOutRho", "NpOutMov", "NpbSim", "NpfSim")},
    }


def _parse_runout(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")

    def integer(pattern: str) -> int | None:
        match = re.search(pattern, text)
        return int(match.group(1).replace(",", "")) if match else None

    def scalar(pattern: str) -> float | None:
        match = re.search(pattern, text)
        return float(match.group(1)) if match else None

    map_border = _map_real_pos(text, "border")
    map_final = _map_real_pos(text, "final")
    cells_match = re.search(r"MapCells=\(([^)]*)\)\s+\(([^)]*)\s+cells\)", text)
    time_match = re.search(r"TimeStep:\s*([0-9.eE+-]+)\s+\(Nstep:\s*(\d+)\)", text)
    excluded_match = re.search(r"Excluded for:\s*position=(\d+)\s+rho=(\d+)\s+velocity=(\d+)", text)
    total_out = [int(value.replace(",", "")) for value in re.findall(r"total out:\s*([\d,]+)", text)]
    # Run.out does not print the Data2D flag in this build.  Keep the solver
    # log as the source for MapSize/failure timing, and let the generated XML
    # below provide the authoritative dimensionality check.
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "loaded_particles": integer(r"Loaded particles:\s*([\d,]+)"),
        "case_nbound": integer(r"CaseNbound=([\d,]+)"),
        "time_max_s": scalar(r"TimeMax=([0-9.eE+-]+)"),
        "map_real_pos_border_m": map_border,
        "map_real_pos_final_m": map_final,
        "map_cells": {"shape": [int(value.strip()) for value in cells_match.group(1).split(",")], "total": int(cells_match.group(2).replace(",", ""))} if cells_match else None,
        "initial_part_particles": integer(r"Part_0000\s+([\d,]+)\s+\(100\.0%\) particles successfully stored"),
        "failure_time_s": float(time_match.group(1)) if time_match else None,
        "failure_step": int(time_match.group(2)) if time_match else None,
        "excluded_summary": {"position": int(excluded_match.group(1)), "rho": int(excluded_match.group(2)), "velocity": int(excluded_match.group(3))} if excluded_match else None,
        "total_out_last": total_out[-1] if total_out else None,
        "boundary_error": next((line.strip() for line in text.splitlines() if "exceeded the" in line), None),
        "abort_kind": "JSphGpuSingle::AbortBoundOut" if "AbortBoundOut" in text else None,
        "is_3d": None,
    }


def _decode_bound_vtk(path: Path, dp: float = 0.05) -> dict[str, Any]:
    """Decode native GenCase ``*_Bound.vtk`` and audit fixed wall coverage.

    The binary VTK uses big-endian payloads.  In this GenCase output the
    ``Type`` byte is 0 for fixed, 1 for moving, and 2 for floating boundary
    points.  Face centers lie on the source planes when the endpoint is
    represented; the old x-max endpoint is absent because its lattice
    coordinate was truncated before reaching 4.8 m.  These are distinct
    checks below.
    """
    data = path.read_bytes()
    header = re.search(rb"POINTS\s+(\d+)\s+float\n", data)
    if header is None:
        raise ValueError(f"POINTS header missing: {path}")
    count = int(header.group(1))
    points_offset = header.end()
    points_size = count * 3 * 4
    if points_offset + points_size > len(data):
        raise ValueError(f"points payload truncated: {path}")
    values = struct.unpack(">" + "f" * (count * 3), data[points_offset : points_offset + points_size])
    points = [list(values[index : index + 3]) for index in range(0, len(values), 3)]
    vertices = re.compile(rb"VERTICES\s+\d+\s+\d+\n").search(data, points_offset + points_size)
    if vertices is None:
        raise ValueError(f"VERTICES header missing: {path}")
    point_data = re.compile(rb"POINT_DATA\s+\d+\n").search(data, vertices.end() + count * 2 * 4)
    if point_data is None:
        raise ValueError(f"POINT_DATA header missing: {path}")
    lookup = re.compile(rb"LOOKUP_TABLE\s+default\n").search(data, point_data.end())
    if lookup is None:
        raise ValueError(f"Idp lookup missing: {path}")
    id_offset = lookup.end()
    if id_offset + count * 4 > len(data):
        raise ValueError(f"Idp payload truncated: {path}")
    ids = struct.unpack(">" + "I" * count, data[id_offset : id_offset + count * 4])
    field = re.compile(rb"FIELD\s+FieldData\s+2\n").search(data, id_offset + count * 4)
    if field is None:
        raise ValueError(f"FieldData header missing: {path}")
    type_header = re.compile(rb"Type\s+1\s+\d+\s+unsigned_char\n").search(data, field.end())
    if type_header is None:
        raise ValueError(f"Type field missing: {path}")
    type_offset = type_header.end()
    types = data[type_offset : type_offset + count]
    if len(types) != count:
        raise ValueError(f"Type payload truncated: {path}")
    mk_header = re.compile(rb"Mk\s+1\s+\d+\s+unsigned_char\n").search(data, type_offset + count)
    if mk_header is None:
        raise ValueError(f"Mk field missing: {path}")
    mk_offset = mk_header.end()
    mks = data[mk_offset : mk_offset + count]
    if len(mks) != count:
        raise ValueError(f"Mk payload truncated: {path}")

    fixed = [points[index] for index, value in enumerate(types) if value == 0]
    # Source physical planes: x=0 and x=4.8, y=0 and y=2.4, z=0.
    # The tolerance only covers float32 serialization and therefore cannot
    # turn an absent face into a pass.
    tol = 2.0e-5
    expected = {
        "x_min": (0, 0.0),
        "x_max": (0, 4.8),
        "y_min": (1, 0.0),
        "y_max": (1, 2.4),
        "z_min": (2, 0.0),
    }
    face_counts = {
        name: sum(abs(point[axis] - target) <= tol for point in fixed)
        for name, (axis, target) in expected.items()
    }
    type_names = {0: "fixed", 1: "moving", 2: "floating"}
    fixed_bounds = (
        [[min(point[axis] for point in fixed), max(point[axis] for point in fixed)] for axis in range(3)]
        if fixed
        else None
    )
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "count": count,
        "type_counts": {type_names.get(value, f"unknown_{value}"): types.count(value) for value in sorted(set(types))},
        "mk_counts": {str(value): mks.count(value) for value in sorted(set(mks))},
        "fixed_points_bounds_m": fixed_bounds,
        "fixed_face_coverage": {
            "expected_center_targets_m": {name: {"axis": "xyz"[axis], "value": target} for name, (axis, target) in expected.items()},
            "counts": face_counts,
            "all_declared_faces_nonzero": all(value > 0 for value in face_counts.values()),
        },
        "solver_dimension": 3,
        "id_range": [int(min(ids)), int(max(ids))] if ids else None,
    }


def _generated_contract(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    particles = root.find("./execution/particles")
    floating = particles.find("floating") if particles is not None else None
    if particles is None or floating is None:
        raise ValueError(f"generated XML floating block missing: {xml_path}")
    center = floating.find("center")
    inertia = floating.find("inertia")
    massbody = floating.find("massbody")
    params = root.find("./execution/parameters/simulationdomain")
    data2d = root.find("./execution/constants/data2d")
    return {
        "path": str(xml_path.resolve()),
        "sha256": sha256(xml_path),
        "particle_np": int(particles.attrib.get("np", "0")),
        "floating_begin": int(floating.attrib.get("begin", "0")),
        "floating_count": int(floating.attrib.get("count", "0")),
        "massbody_kg": float(massbody.attrib["value"]) if massbody is not None else None,
        "center_m": [float(center.attrib[axis]) for axis in "xyz"] if center is not None else None,
        "inertia_diag_kg_m2": [float(inertia.attrib[axis]) for axis in "xyz"] if inertia is not None else None,
        "solver_dimension": 2 if data2d is not None and data2d.attrib.get("value", "true").lower() == "true" else 3,
        "simulationdomain_source": {
            "posmin": dict(params.find("posmin").attrib) if params is not None and params.find("posmin") is not None else None,
            "posmax": dict(params.find("posmax").attrib) if params is not None and params.find("posmax") is not None else None,
        },
    }


def _case_paths(mechanism: str) -> dict[str, Path]:
    cid = CASE_IDS[mechanism]
    raw = RAW_ROOT / cid / f"{cid}_SOLVER_QUAL_003"
    gen = RAW_ROOT / cid / f"{cid}_GENCASE_001" / cid
    case_dir = FAMILY_ROOT / "cases" / mechanism / "medium"
    return {
        "cid": Path(cid),
        "raw": raw,
        "receipt": raw / "execution-receipt.json",
        "solver_out": raw / "solver_output",
        "run_out": raw / "solver_output/Run.out",
        "runparts": raw / "solver_output/RunPARTs.csv",
        "error_vtk": raw / "solver_output/Error_BoundaryOut.vtk",
        "bound_vtk": gen.with_name(gen.name + "_Bound.vtk"),
        "data": raw / "solver_output/data",
        "generated_xml": gen.with_suffix(".xml"),
        "gencase_receipt": gen.parent / "execution-receipt.json",
        "definition": case_dir / f"{cid}_Def.xml",
        "control": case_dir / f"{cid}_Control.csv",
        "native": case_dir / f"{cid}_Native.json",
        "normal": case_dir / f"{cid}_Normal.json",
    }


def audit_boundary(mechanism: str, output_path: Path) -> dict[str, Any]:
    paths = _case_paths(mechanism)
    required = [paths[name] for name in ("receipt", "run_out", "runparts", "error_vtk", "bound_vtk", "generated_xml", "gencase_receipt")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing immutable failure evidence: " + ", ".join(missing))
    receipt = read_json(paths["receipt"])
    run_out = _parse_runout(paths["run_out"])
    runparts = _runparts(paths["runparts"])
    vtk = _decode_boundary_vtk(paths["error_vtk"])
    bound_vtk = _decode_bound_vtk(paths["bound_vtk"])
    generated = _generated_contract(paths["generated_xml"])
    run_out["is_3d"] = generated["solver_dimension"] == 3
    boundary = vtk["records"]
    map_final = run_out.get("map_real_pos_final_m")
    right_limit = map_final["max_m"][0] if map_final else None
    physical_right_wall = 4.8
    for row in boundary:
        row["numerical_domain_x_excess_m"] = float(row["position_m"][0] - right_limit) if right_limit is not None else None
        row["physical_wall_x_clearance_m"] = float(physical_right_wall - row["position_m"][0])
        row["classification"] = {
            "type_semantics": {1: "fixed", 2: "floating", 3: "fluid", 4: "moving"}.get(row["type"], "unknown"),
            "is_floating_type2": row["type"] == 2,
            "is_moving_motive": row["motive"] == 1,
            "outside_numerical_domain": right_limit is not None and row["position_m"][0] > right_limit,
            "inside_physical_tank_x": 0.0 <= row["position_m"][0] <= physical_right_wall,
        }
    result = {
        "schema": "ds-data-02.f6.rigid_contract_003.domain_diagnosis_001.v1",
        "family_id": "F6",
        "mechanism_id": mechanism,
        "case_id": CASE_IDS[mechanism],
        "created_at": now(),
        "status": "native_domain_failure_decoded",
        "solver_receipt": {"path": str(paths["receipt"].resolve()), "sha256": sha256(paths["receipt"]), "status": receipt.get("status"), "returncode": receipt.get("returncode"), "gpu": receipt.get("gpu"), "gpu_seconds": receipt.get("gpu_seconds")},
        "run_out": run_out,
        "runparts": runparts,
        "error_boundary_vtk": vtk,
        "native_boundary_vtk": bound_vtk,
        "generated_native_contract": generated,
        "physical_reference": {"finite_tank_right_wall_x_m": physical_right_wall, "continuous_fluid_box_x_m": [0.4, 4.4], "body_center_m": [2.4, 1.2, 1.08], "massbody_kg": 128.0, "inertia_diag_kg_m2": [8.53333, 8.53333, 13.6533]},
        "root_cause_evidence": {
            "all_excluded_records_type2": bool(boundary) and all(row["type"] == 2 for row in boundary),
            "all_excluded_records_outside_numerical_x_limit": bool(boundary) and all(row["classification"]["outside_numerical_domain"] for row in boundary),
            "all_excluded_records_inside_frozen_physical_tank": bool(boundary) and all(row["classification"]["inside_physical_tank_x"] for row in boundary),
            "domain_limit_is_below_frozen_wall_endpoint": right_limit is not None and right_limit < physical_right_wall,
            "native_fixed_wall_faces_complete": bound_vtk["fixed_face_coverage"]["all_declared_faces_nonzero"],
            "native_right_wall_face_missing": bound_vtk["fixed_face_coverage"]["counts"]["x_max"] == 0,
            "native_lattice_x_endpoint_below_physical_wall": bound_vtk["fixed_points_bounds_m"][1][1] < physical_right_wall if bound_vtk["fixed_points_bounds_m"] else True,
            "floating_boundary_abort": run_out.get("abort_kind") == "JSphGpuSingle::AbortBoundOut",
        },
        "diagnosis": "Both medium attempts excluded one type-2 floating particle at +X beyond the solver MapRealPos(final) limit while the particle remained inside the frozen physical tank x<=4.8 m. Native *_Bound.vtk confirms the fixed x-max face is absent: the source box declares a right face, but pointmax x=4.85 leaves the float lattice at x=4.75 and no interior x-max fixed face. The evidence therefore separates auto-domain exhaustion from a lattice endpoint/wall representation defect; widening only the simulation domain would leave the missing wall unresolved.",
        "legal_next_scope": {
            "repair_id": "F6_HANDOFF_20261002_RIGID003_DOMAIN_X_REPAIR_01",
            "change": "extend only the numerical lattice pointmax to include the frozen x=4.8 wall center and set explicit simulationdomain x bounds with a documented positive margin",
            "preserve": ["continuous tank/fluid/body geometry", "finite wall endpoints", "fluid population and mass denominator", "floating massbody/center/inertia", "wave paddle control"],
            "must_recheck": ["GenCase nonzero fluid/actual3D/layers", "generated center/inertia exact serialized contract", "native fixed x-max face coverage plus all other declared faces", "MapRealPos x limit above body clearance", "same physical wall/fluid/body source semantics"],
            "gpu": "root only after CPU GenCase and review",
        },
        "qualification_claim": "none; failed solver evidence only",
    }
    write_json(output_path, result)
    return result


def _inputs(paths: dict[str, Path]) -> list[str]:
    values = [SCRIPT, RUNTIME_V2, SOLVER, GENCASE, paths["receipt"], paths["gencase_receipt"], paths["run_out"], paths["runparts"], paths["error_vtk"], paths["bound_vtk"], paths["generated_xml"], paths["definition"], paths["control"], paths["native"], paths["normal"]]
    values.extend(sorted(paths["data"].glob("*.bi4")))
    missing = [str(path) for path in values if not path.is_file()]
    if missing:
        raise FileNotFoundError("audit request input missing: " + ", ".join(missing))
    return [str(path.resolve()) for path in values]


def _make_requests(audit_root: Path, attempt_suffix: str, schema_suffix: str) -> dict[str, Any]:
    audit_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for mechanism in CASE_IDS:
        paths = _case_paths(mechanism)
        cid = CASE_IDS[mechanism]
        attempt = f"{cid}_DOMAIN_AUDIT_{attempt_suffix}"
        request = {
            "schema": "ds-data-02.runner.request.v1",
            "family_id": "F6",
            "case_id": cid,
            "attempt_id": attempt,
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "command": [str(Path("/usr/bin/python3")), str(SCRIPT.resolve()), "audit-boundary", "--mechanism", mechanism, "--output", "{attempt_root}/boundary-audit.json"],
            "cwd": str(LAB.resolve()),
            "max_wall_seconds": 120,
            "cpu_threads": 2,
            "estimated_storage_bytes": 16777216,
            "input_files": _inputs(paths),
            "worktree_root": str(LAB.resolve()),
            "purpose": "decode immutable Error_BoundaryOut.vtk, Run.out, RunPARTs.csv and generated native XML for numerical-domain root-cause evidence; no solver/GPU/conversion",
            "mechanism_id": mechanism,
            "solver_parent_attempt": str(paths["raw"].resolve()),
            "generated_prefix": str(paths["generated_xml"].with_suffix("").resolve()),
            "expected": {"solver_dimension": 3, "excluded_type": 2, "frozen_physical_right_wall_x_m": 4.8, "frozen_massbody_kg": 128.0, "frozen_center_m": [2.4, 1.2, 1.08], "frozen_serialized_inertia_diag_kg_m2": [8.53333, 8.53333, 13.6533]},
            "qualification_claim": "none",
        }
        path = audit_root / "execution_requests" / f"{mechanism}_boundary_audit.json"
        write_json(path, request)
        rows.append({"mechanism_id": mechanism, "case_id": cid, "path": str(path.resolve()), "sha256": sha256(path), "attempt_id": attempt})
    result = {"schema": f"ds-data-02.f6.rigid_contract_003.domain_diagnosis_requests.{schema_suffix}", "status": "ready_for_shared_cpu_audit", "created_at": now(), "requests": rows, "gpu_launch": False}
    write_json(audit_root / "request_manifest.json", result)
    return result


def make_requests() -> dict[str, Any]:
    return _make_requests(AUDIT_ROOT, "001", "v1")


AUDIT_ROOT_002 = FAMILY_ROOT / "domain_diagnosis_002"


def make_requests_002() -> dict[str, Any]:
    # Additive rerun after the fixed-wall VTK decoder was added.  The original
    # _001 requests and receipts remain byte-for-byte immutable.
    return _make_requests(AUDIT_ROOT_002, "002", "v2")


def _record_receipts(audit_root: Path, schema_suffix: str, next_scope: str) -> dict[str, Any]:
    manifest = read_json(audit_root / "request_manifest.json")
    rows = []
    for request_row in manifest["requests"]:
        cid = request_row["case_id"]
        attempt = request_row["attempt_id"]
        receipt = RAW_ROOT / cid / attempt / "execution-receipt.json"
        result_path = RAW_ROOT / cid / attempt / "boundary-audit.json"
        if not receipt.is_file() or not result_path.is_file():
            raise FileNotFoundError(f"audit receipt/output pending: {receipt}")
        result = read_json(result_path)
        rows.append({"case_id": cid, "attempt_id": attempt, "receipt": str(receipt.resolve()), "receipt_sha256": sha256(receipt), "result": str(result_path.resolve()), "result_sha256": sha256(result_path), "status": result.get("status"), "excluded": result["error_boundary_vtk"]["records"], "failure_time_s": result["run_out"].get("failure_time_s")})
    output = {"schema": f"ds-data-02.f6.rigid_contract_003.domain_diagnosis_002.{schema_suffix}", "status": "evidence_bound", "created_at": now(), "records": rows, "next_scope": next_scope, "qualification_claim": "none"}
    write_json(audit_root / "diagnosis_receipt_sidecar.json", output)
    return output


def record_receipts() -> dict[str, Any]:
    return _record_receipts(AUDIT_ROOT, "v1", "RIGID003_DOMAIN_X_REPAIR_01 CPU GenCase then root review")


def record_receipts_002() -> dict[str, Any]:
    return _record_receipts(AUDIT_ROOT_002, "v2", "RIGID003_DOMAIN_X_REPAIR_01 CPU GenCase then root review")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("make-requests")
    sub.add_parser("make-requests-002")
    audit = sub.add_parser("audit-boundary")
    audit.add_argument("--mechanism", choices=CASE_IDS, required=True)
    audit.add_argument("--output", type=Path, required=True)
    sub.add_parser("record-receipts")
    sub.add_parser("record-receipts-002")
    args = parser.parse_args()
    if args.action == "make-requests":
        result = make_requests()
    elif args.action == "make-requests-002":
        result = make_requests_002()
    elif args.action == "audit-boundary":
        result = audit_boundary(args.mechanism, args.output)
    elif args.action == "record-receipts":
        result = record_receipts()
    else:
        result = record_receipts_002()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

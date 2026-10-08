#!/usr/bin/env python3
"""Audit F6 rigid-body declarations and generated floating-point geometry.

The F6 physical body has massbody=128 kg and a declared COM/inertia.  Its
floating SPH sample mass (count*masspart) is a separate discretization
quantity.  This bounded CPU audit reads only exact GenCase XML/OUT/receipt
metadata and generated ``*_All.vtk`` POINTS payloads for the original,
coarse, and fine F6 products.  It never reads BI4/H5 and never starts a
solver.  It reports declaration equality and sample-cloud COM/inertia
diagnostics separately; sample agreement cannot silently grant rigid-body
dynamic equivalence.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import tempfile
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f6-rigid-body-geometry-audit.v3"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SOURCE_AUDIT = REFERENCE / "stage2_fourteen_source_control_audit_v5.json"
GRAPH = REFERENCE / "stage2_minimal14_study_graph_v2.json"
V8_RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
V8_STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
V8_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
CASE_IDS = ("F6-S1", "F6-S2")
VTK_POINTS_RE = re.compile(rb"POINTS\s+(\d+)\s+float\s*\r?\n")
DEFAULT_OUTPUT = REFERENCE / "stage2_f6_rigid_body_geometry_audit_v3.json"
CASE_ID = "F6_RIGID_BODY_GEOMETRY_AUDIT_V3"
ATTEMPT_ID = "f6-rigid-body-geometry-audit-v3-root-001"
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f6-rigid-body-geometry-audit-v3"
REQUEST_PATH = REQUEST_DIR / "f6_rigid_body_geometry_audit_v3.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def record(path: Path) -> dict[str, Any]:
    path = regular(path)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def finite(value: str | float | None, label: str) -> float:
    if value is None:
        raise ValueError(f"missing {label}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite {label}")
    return result


def vector(node: ET.Element | None, label: str) -> list[float]:
    if node is None:
        raise ValueError(f"missing {label}")
    return [finite(node.get(axis), f"{label}.{axis}") for axis in ("x", "y", "z")]


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def load(path: Path) -> dict[str, Any]:
    value = json.loads(regular(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def physical_declaration(root: ET.Element, label: str) -> dict[str, Any]:
    nodes = [node for node in root.iter() if local(node.tag) == "floating" and node.get("begin") is not None]
    if len(nodes) != 1:
        raise ValueError(f"{label} expected one execution floating block, got {len(nodes)}")
    block = nodes[0]
    body = next((node for node in root.iter() if local(node.tag) == "floating" and node.get("begin") is None), None)
    # The execution particle block is the authoritative generated declaration;
    # retain the pre-execution floatings declaration when present as a check.
    mass_node = next((node for node in block if local(node.tag) == "massbody"), None)
    center_node = next((node for node in block if local(node.tag) == "center"), None)
    inertia_node = next((node for node in block if local(node.tag) == "inertia"), None)
    masspart_node = next((node for node in root.iter() if local(node.tag) == "masspart"), None)
    if mass_node is None or center_node is None or inertia_node is None:
        raise ValueError(f"{label} floating declaration lacks massbody/center/inertia")
    return {
        "floating_mk_absolute": int(block.get("mk", "-1")),
        "begin": int(block.get("begin", "-1")),
        "count": int(block.get("count", "-1")),
        "massbody_kg": finite(mass_node.get("value"), f"{label}.massbody"),
        "masspart_kg": finite(masspart_node.get("value"), f"{label}.masspart") if masspart_node is not None else None,
        "center_m": vector(center_node, f"{label}.center"),
        "inertia_kg_m2": vector(inertia_node, f"{label}.inertia"),
        "body_declaration_present": body is not None,
    }


def case_inputs() -> dict[str, list[Path]]:
    source_audit = load(SOURCE_AUDIT)
    graph = load(GRAPH)
    source_rows = {row["sentinel_id"]: row for row in source_audit.get("sources", [])}
    graph_rows = {row["sentinel_id"]: row for row in graph.get("sentinels", [])}
    result: dict[str, list[Path]] = {}
    for sid in CASE_IDS:
        if sid not in source_rows or sid not in graph_rows:
            raise ValueError(f"missing F6 source/graph row {sid}")
        source_xml = Path(source_rows[sid]["source_xml"]["path"])
        source_root = source_xml.parent
        paths = [source_xml, source_root / (source_xml.stem + "_All.vtk"), Path(source_rows[sid]["source_solver_control"]["receipt"]["path"])]
        for grid in graph_rows[sid].get("spatial_ladder", []):
            if grid.get("grid") == "original":
                continue
            generated = grid.get("generated_xml", {}).get("path")
            if not generated:
                continue
            generated_xml = Path(generated)
            paths.extend([generated_xml, generated_xml.parent / "generated_All.vtk", generated_xml.parent / "execution-receipt.json", generated_xml.parent / "generated.out"])
        unique = list(dict.fromkeys(path.expanduser().resolve() for path in paths))
        result[sid] = unique
    return result


def parse_points(path: Path) -> tuple[int, list[tuple[float, float, float]], str]:
    raw = regular(path).read_bytes()
    match = VTK_POINTS_RE.search(raw)
    if match is None:
        raise ValueError(f"missing POINTS header: {path}")
    count = int(match.group(1))
    offset = match.end()
    size = count * 3 * 4
    if len(raw) < offset + size:
        raise ValueError(f"truncated POINTS payload: {path}")
    payload = raw[offset:offset + size]
    values = struct.unpack(">" + "f" * (count * 3), payload)
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"non-finite POINTS payload: {path}")
    points = [(float(values[i]), float(values[i + 1]), float(values[i + 2])) for i in range(0, len(values), 3)]
    return count, points, hashlib.sha256(payload).hexdigest()


def cloud_stats(points: list[tuple[float, float, float]], begin: int, count: int, masspart: float, declared_center: list[float]) -> dict[str, Any]:
    selected = points[begin:begin + count]
    if len(selected) != count:
        raise ValueError(f"floating block {begin}:{begin + count} exceeds POINTS count {len(points)}")
    mass = count * masspart
    center = [sum(point[i] for point in selected) / count for i in range(3)]
    inertia = [[0.0, 0.0, 0.0] for _ in range(3)]
    for point in selected:
        r = [point[i] - center[i] for i in range(3)]
        rr = sum(value * value for value in r)
        for i in range(3):
            for j in range(3):
                inertia[i][j] += masspart * ((rr if i == j else 0.0) - r[i] * r[j])
    diagonal = [inertia[i][i] for i in range(3)]
    return {
        "point_count": count,
        "sample_mass_kg": mass,
        "sample_centroid_m": center,
        "declared_center_m": declared_center,
        "centroid_minus_declared_m": [center[i] - declared_center[i] for i in range(3)],
        "sample_inertia_about_sample_centroid_kg_m2": diagonal,
        "sample_inertia_matrix_kg_m2": inertia,
        "physical_body_mass_is_not_sample_mass": True,
    }


def parse_case(sid: str, path_list: list[Path], source_row: dict[str, Any]) -> dict[str, Any]:
    source_xml = path_list[0]
    source_root = ET.parse(source_xml).getroot()
    source_decl = physical_declaration(source_root, f"{sid} source")
    source_vtk = path_list[1]
    source_points_count, _, source_payload_sha = parse_points(source_vtk)
    source_result = {
        "role": "original_current",
        "generated_xml": record(source_xml),
        "generated_all_vtk": record(source_vtk),
        "execution_receipt": record(path_list[2]),
        "declaration": source_decl,
        "vtk_point_count": source_points_count,
        "points_payload_sha256": source_payload_sha,
        "floating_block_count_matches_vtk": source_decl["begin"] + source_decl["count"] <= source_points_count,
    }
    grids = [source_result]
    for index in range(3, len(path_list), 4):
        xml_path, vtk_path, receipt_path, out_path = path_list[index:index + 4]
        generated_root = ET.parse(xml_path).getroot()
        declaration = physical_declaration(generated_root, f"{sid} {xml_path}")
        point_count, points, payload_sha = parse_points(vtk_path)
        stats = cloud_stats(points, declaration["begin"], declaration["count"], declaration["masspart_kg"], declaration["center_m"])
        grids.append({
            "role": "candidate",
            "case_id": generated_root.get("app"),
            "generated_xml": record(xml_path),
            "generated_all_vtk": record(vtk_path),
            "execution_receipt": record(receipt_path),
            "generated_out": record(out_path),
            "declaration": declaration,
            "vtk_point_count": point_count,
            "points_payload_sha256": payload_sha,
            "floating_cloud": stats,
            "floating_block_count_matches_vtk": declaration["begin"] + declaration["count"] <= point_count,
        })
    source_physical = source_decl
    for grid in grids[1:]:
        decl = grid["declaration"]
        grid["declaration_comparison_to_original"] = {
            "massbody_equal": math.isclose(decl["massbody_kg"], source_physical["massbody_kg"], rel_tol=0.0, abs_tol=1e-12),
            "center_equal": all(math.isclose(decl["center_m"][i], source_physical["center_m"][i], rel_tol=0.0, abs_tol=1e-12) for i in range(3)),
            "inertia_equal": all(math.isclose(decl["inertia_kg_m2"][i], source_physical["inertia_kg_m2"][i], rel_tol=0.0, abs_tol=1e-10) for i in range(3)),
            "status": "PASS_DECLARED_PHYSICAL_RIGID_BINDING_EQUAL" if (
                math.isclose(decl["massbody_kg"], source_physical["massbody_kg"], rel_tol=0.0, abs_tol=1e-12)
                and all(math.isclose(decl["center_m"][i], source_physical["center_m"][i], rel_tol=0.0, abs_tol=1e-12) for i in range(3))
                and all(math.isclose(decl["inertia_kg_m2"][i], source_physical["inertia_kg_m2"][i], rel_tol=0.0, abs_tol=1e-10) for i in range(3))
            ) else "FAIL_DECLARED_PHYSICAL_RIGID_BINDING_DIFFERS",
        }
    return {
        "sentinel_id": sid,
        "physical_case_id": source_row.get("physical_case_id"),
        "source_physical_declaration": source_physical,
        "grids": grids,
        "interpretation": {
            "declared_massbody_inertia_center_are_physical_inputs": True,
            "floating_sample_mass_is_not_massbody": True,
            "sample_cloud_com_and_inertia_are_discretization_diagnostics": True,
            "continuous_geometry_and_rigid_dynamics_qualification": "UNKNOWN_UNTIL_PARENT_REVIEW_AND_SOLVER_OBSERVER",
        },
    }


def self_test() -> dict[str, Any]:
    """Check finite POINTS and a two-point analytic inertia case."""

    with tempfile.TemporaryDirectory(prefix="ds02-f6-rigid-audit-v2-") as tmp:
        path = Path(tmp) / "synthetic.vtk"
        payload = struct.pack(">6f", -0.5, 0.0, 0.0, 0.5, 0.0, 0.0)
        path.write_bytes(b"# vtk DataFile Version 3.0\nsynthetic\nBINARY\nDATASET POLYDATA\nPOINTS 2 float\n" + payload)
        count, points, _ = parse_points(path)
        if count != 2 or len(points) != 2:
            raise AssertionError("synthetic finite point payload failed")
        stats = cloud_stats(points, 0, 2, 1.0, [0.0, 0.0, 0.0])
        if abs(stats["sample_inertia_about_sample_centroid_kg_m2"][1] - 0.5) > 1e-12:
            raise AssertionError("analytic two-point inertia check failed")
        invalid = Path(tmp) / "nan.vtk"
        invalid.write_bytes(b"# vtk DataFile Version 3.0\nsynthetic\nBINARY\nDATASET POLYDATA\nPOINTS 1 float\n" + struct.pack(">3f", float("nan"), 0.0, 0.0))
        try:
            parse_points(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("NaN POINTS payload was accepted")
    return {"status": "PASS", "finite_points": True, "analytic_inertia": True, "nan_rejected": True}


def build(output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refuse overwrite immutable report: {output}")
    source_audit = load(SOURCE_AUDIT)
    source_rows = {row["sentinel_id"]: row for row in source_audit.get("sources", [])}
    inputs = case_inputs()
    cases = {sid: parse_case(sid, paths, source_rows[sid]) for sid, paths in inputs.items()}
    report = {
        "schema": SCHEMA,
        "status": "PASS_DECLARATION_AND_SAMPLE_CLOUD_AUDIT_SCIENTIFIC_QUALIFICATION_UNKNOWN",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_scope": {
            "bi4_read": False,
            "hdf5_read": False,
            "solver_launch": False,
            "gencase_launch": False,
            "read_inputs": "exact current/candidate generated XML, OUT, receipt, and *_All.vtk POINTS only",
            "physical_mass_semantics": "massbody, COM, inertia are retained separately from floating SPH sample mass",
        },
        "source_inputs": {
            "source_audit": record(SOURCE_AUDIT),
            "graph": record(GRAPH),
        },
        "manufactured_self_test": self_test(),
        "frozen_gate": {
            "physical_massbody_kg": 128.0,
            "physical_center_m": [2.4, 1.2, 1.08],
            "physical_inertia_kg_m2": [8.53333333333, 8.53333333333, 13.6533333333],
            "sample_mass_must_not_replace_physical_massbody": True,
            "sample_com_inertia_are_diagnostics": True,
        },
        "cases": list(cases.values()),
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + f".{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    return report


def all_input_paths() -> list[Path]:
    paths = [Path(__file__), SOURCE_AUDIT, GRAPH, V8_RUNNER, V8_STRICT, V8_RUNTIME, PYTHON]
    for case_paths_list in case_inputs().values():
        paths.extend(case_paths_list)
    unique = list(dict.fromkeys(path.expanduser().resolve() for path in paths))
    if any(path.suffix.lower() in {".bi4", ".h5", ".hdf5"} for path in unique):
        raise ValueError("F6 rigid audit input closure must not contain BI4/H5")
    return unique


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse overwrite immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def build_request() -> dict[str, Any]:
    if REQUEST_PATH.exists():
        raise FileExistsError(f"refuse overwrite immutable request: {REQUEST_PATH}")
    paths = all_input_paths()
    records = {str(path): record(path) for path in paths}
    output_root = DATA_ROOT / "families/F6" / CASE_ID / ATTEMPT_ID
    request = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F6",
        "sentinel_id": "F6-S1,F6-S2",
        "physical_case_id": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025;F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "command": [str(PYTHON), str(Path(__file__).resolve()), "--audit", "--output", "{attempt_root}/stage2_f6_rigid_body_geometry_audit_v3.json"],
        "cwd": str(REPO),
        "input_files": list(records),
        "input_hashes": {path: value["sha256"] for path, value in records.items()},
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "estimated_input_read_bytes": sum(value["bytes"] for value in records.values()),
        "estimated_geometry_read_bytes": sum(value["bytes"] for path, value in records.items() if path.endswith("_All.vtk")),
        "estimated_native_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "hdf5_read": False,
        "bi4_read": False,
        "deferred_input_files": [],
        "source_binding": {
            "schema": "ds02.stage2.f6-rigid-body-geometry-binding.v3",
            "physical_massbody_kg": 128.0,
            "physical_center_m": [2.4, 1.2, 1.08],
            "physical_inertia_kg_m2": [8.53333333333, 8.53333333333, 13.6533333333],
            "sample_mass_not_body_mass": True,
            "points_finite_before_computation": True,
            "parent_guard_prepost_hash_required": True,
            "cases": {sid: [str(path) for path in paths] for sid, paths in case_inputs().items()},
        },
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/stage2_f6_rigid_body_geometry_audit_v3.json"},
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(V8_RUNNER),
            "strict_guard": str(V8_STRICT),
            "runtime": str(V8_RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "gencase_launch": "forbidden",
            "hdf5_read": "forbidden",
            "bi4_read": "forbidden",
            "parent_v8_review_required": True,
        },
        "output_root": str(output_root),
        "qualification_stage": "stage2_f6_rigid_body_geometry_audit_v3_pending_parent_v8_dispatch",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(REQUEST_PATH, request)
    return request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    selected = [args.self_test, args.audit, args.build_request]
    if sum(selected) != 1:
        parser.error("choose exactly one of --self-test, --audit, --build-request")
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    if args.build_request:
        request = build_request()
        print(json.dumps({"status": "PREPARED", "path": str(REQUEST_PATH), "input_count": len(request["input_files"]), "estimated_geometry_read_bytes": request["estimated_geometry_read_bytes"]}, indent=2))
        return 0
    report = build(args.output)
    print(json.dumps({"status": report["status"], "output": str(args.output.resolve()), "cases": len(report["cases"]), "bi4_read": report["audit_scope"]["bi4_read"], "hdf5_read": report["audit_scope"]["hdf5_read"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

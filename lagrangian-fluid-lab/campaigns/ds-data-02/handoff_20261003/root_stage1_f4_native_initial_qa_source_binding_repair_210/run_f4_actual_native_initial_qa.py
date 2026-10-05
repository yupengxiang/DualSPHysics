#!/usr/bin/env python3
"""Root-owned F4 native initial QA producer for the eight Root195 cases.

The producer is disabled source-only code.  When Root enables its CPU audit
request, it opens each genuine Root195 BI4 read-only through the pinned safe
decoder, memmaps only the registered position/ID arrays, writes one report and
an aggregate index, then invokes the fresh082 metadata binder.  It never
copies/re-writes BI4, reruns GenCase, or mutates the failed parent receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
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

import numpy as np

SCHEMA = "ds02.f4.internal8.native-initial-audit.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical(element: ET.Element | None) -> Any:
    if element is None:
        return None
    return [element.tag, sorted(element.attrib.items()), (element.text or "").strip(), [canonical(child) for child in element]]


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "pass", "passed", "covered"}
    return bool(value)


def finite_point(point: Any) -> bool:
    return isinstance(point, list) and len(point) == 3 and all(math.isfinite(float(x)) for x in point)


def face_coverage(points: np.ndarray, low: np.ndarray, high: np.ndarray, faces: list[tuple[int, int]], dp: float) -> dict[str, Any]:
    tolerance = dp / 2.0 + 1e-9
    result: dict[str, Any] = {}
    for axis, side in faces:
        value = (low if side == 0 else high)[axis]
        tangents = [index for index in range(3) if index != axis]
        selected = np.abs(points[:, axis] - value) <= tolerance
        for tangent in tangents:
            selected &= points[:, tangent] >= low[tangent] - tolerance
            selected &= points[:, tangent] <= high[tangent] + tolerance
        cloud = points[selected]
        covered = len(cloud) > 0
        if covered:
            covered = all(cloud[:, index].min() <= low[index] + tolerance and cloud[:, index].max() >= high[index] - tolerance for index in tangents)
        result[f"{axis}_{side}"] = {
            "count": int(len(cloud)),
            "covered": bool(covered),
            "bounds_m": [cloud.min(axis=0).tolist(), cloud.max(axis=0).tolist()] if len(cloud) else None,
        }
    return result


def load_safe_scanner(helper_path: Path, decoder_path: Path):
    spec = importlib.util.spec_from_file_location("f4_fresh083_native_helper", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper: {helper_path}")
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)
    scanner = helper._load_safe_decoder(decoder_path)
    return helper, scanner


def parameter(root: ET.Element, key: str) -> str | None:
    for element in root.iter("parameter"):
        if element.attrib.get("key") == key:
            return element.attrib.get("value")
    return None


def parse_xml(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    definition = root.find(".//definition")
    particles = root.find("execution/particles")
    if particles is None:
        particles = root.find(".//particles")
    if definition is None or particles is None:
        raise ValueError(f"generated XML lacks definition/particles: {xml_path}")
    data2d = root.find(".//data2d")
    if data2d is None:
        raise ValueError(f"generated XML lacks data2d: {xml_path}")
    fixed_node = particles.find("fixed")
    if fixed_node is None:
        raise ValueError(f"generated XML lacks fixed particle block: {xml_path}")
    blocks = []
    for fluid in particles.findall("fluid"):
        blocks.append({
            "mkfluid": int(fluid.attrib["mkfluid"]),
            "mk": int(fluid.attrib["mk"]),
            "begin": int(fluid.attrib["begin"]),
            "count": int(fluid.attrib["count"]),
        })
    total = int(particles.attrib["np"])
    fixed = int(particles.attrib["nb"])
    fixed_mk = int(fixed_node.attrib["mk"])
    fluid = sum(row["count"] for row in blocks)
    if total <= 0 or fixed <= 0 or fluid <= 0 or total != fixed + fluid:
        raise ValueError(f"generated XML partition does not close: {xml_path}")
    return {
        "path": str(xml_path),
        "sha256": sha256(xml_path),
        "dp_m": float(definition.attrib["dp"]),
        "time_max_s": float(parameter(root, "TimeMax")),
        "time_out_s": float(parameter(root, "TimeOut")),
        "data2d": boolish(data2d.attrib.get("value")),
        "total_particles": total,
        "fixed_particles": fixed,
        "fixed_mk": fixed_mk,
        "fluid_particles": fluid,
        "fluid_blocks": blocks,
    }


def verify_source_invariants(definition: Path, mother: Path) -> bool:
    new = ET.parse(definition).getroot()
    old = ET.parse(mother).getroot()
    return all(canonical(new.find(path)) == canonical(old.find(path)) for path in ("casedef/constantsdef", "casedef/initials", "execution"))


def _numpy_dtype(type_code: int) -> str:
    dtypes = {
        3: "<i1", 4: "<u1", 5: "<i2", 6: "<u2", 7: "<i4",
        8: "<u4", 9: "<i8", 10: "<u8", 11: "<f4", 12: "<f8",
    }
    if type_code not in dtypes:
        raise ValueError(f"unsupported scalar BI4 type code: {type_code}")
    return dtypes[type_code]


def _scalar_memmap(native: Path, desc: Any) -> np.memmap:
    if desc.count <= 0:
        raise ValueError(f"BI4 scalar array is empty: {desc.name}")
    return np.memmap(native, mode="r", dtype=_numpy_dtype(desc.type_code), offset=desc.offset, shape=(desc.count,))


def scan_arrays(native: Path, scanner: Any) -> tuple[str, dict[str, Any], Any, Any, Any, Any, Any]:
    fd = os.open(native, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        expected_sha = scanner._hash_fd(fd, native.stat().st_size)
        scan = scanner.scan_bi4_fd(fd, expected_sha)
    finally:
        os.close(fd)
    values = {item.name: item.value for item in scan.root.values}
    if not scan.root.children:
        raise ValueError(f"BI4 has no particle item: {native}")
    part_name = scan.root.children[0].name
    arrays = {item.name: item for item in scan.arrays if item.item_path[-1] == part_name}
    required = ("Posd", "Idp", "Mk", "Type")
    missing = [name for name in required if name not in arrays]
    if missing:
        raise ValueError(f"BI4 lacks required native arrays {missing}: {native}")
    pos_desc = arrays["Posd"]
    if pos_desc.type_code != 23:
        raise ValueError(f"BI4 Posd is not float64x3: {native}")
    pos = np.memmap(native, mode="r", dtype="<f8", offset=pos_desc.offset, shape=(pos_desc.count, 3))
    ids = _scalar_memmap(native, arrays["Idp"])
    marks = _scalar_memmap(native, arrays["Mk"])
    types = _scalar_memmap(native, arrays["Type"])
    counts = {name: int(arrays[name].count) for name in required}
    if len(set(counts.values())) != 1 or counts["Posd"] != int(values.get("CaseNp", -1)):
        raise ValueError(f"BI4 native array counts do not close over CaseNp: {counts}")
    return scan.input_sha256, values, arrays, pos, ids, marks, types


def source_regions(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    initial = metadata["physical_binding"]["initial_state"]
    regions = initial.get("source_regions")
    if not isinstance(regions, dict) or set(regions) != {"drop", "pool"}:
        raise ValueError("metadata lacks exactly drop/pool source regions")
    return regions


def audit_case(
    *,
    endpoint: dict[str, Any],
    owner: dict[str, Any],
    metadata: dict[str, Any],
    gencase_root: Path,
    scanner: Any,
    helper_path: Path,
    decoder_path: Path,
    output: Path,
) -> dict[str, Any]:
    endpoint_id = str(endpoint["endpoint_id"])
    case_dir = gencase_root / endpoint_id
    case_receipt_path = case_dir / "gencase-receipt.json"
    case_receipt = load_json(case_receipt_path)
    if case_receipt.get("status") != "completed" or case_receipt.get("returncode") != 0:
        raise ValueError(f"{endpoint_id}: genuine per-case GenCase receipt is not completed0")
    if case_receipt.get("individual_GenCase_OS_returncode_recorded_from_subprocess") is not True:
        raise ValueError(f"{endpoint_id}: missing subprocess OS0 provenance")
    if case_receipt.get("physical_condition_sha256") != endpoint.get("physical_condition_sha256"):
        raise ValueError(f"{endpoint_id}: physical condition drift")
    xml_path = Path(case_receipt["generated_xml"]["path"])
    native = Path(case_receipt["generated_bi4"]["path"])
    expected_xml = case_dir / f"{endpoint_id}.xml"
    expected_bi4 = case_dir / f"{endpoint_id}.bi4"
    if xml_path.resolve() != expected_xml.resolve() or native.resolve() != expected_bi4.resolve():
        raise ValueError(f"{endpoint_id}: generated output path drift")
    xml = parse_xml(xml_path)
    if xml["sha256"] != case_receipt["generated_xml"]["sha256"]:
        raise ValueError(f"{endpoint_id}: XML producer SHA mismatch")
    expected_bi4_sha = case_receipt["generated_bi4"]["sha256"]
    if not isinstance(expected_bi4_sha, str) or len(expected_bi4_sha) != 64:
        raise ValueError(f"{endpoint_id}: missing frozen BI4 producer SHA")
    definition = Path(owner["source_definition"]["path"])
    mother = Path(owner["source_definition"]["mother_path"])
    if sha256(definition) != owner["source_definition"]["sha256"] or sha256(mother) != owner["source_definition"]["mother_sha256"]:
        raise ValueError(f"{endpoint_id}: source Definition hash drift")
    bi4_sha, values, arrays, pos, ids, marks, types = scan_arrays(native, scanner)
    if bi4_sha != expected_bi4_sha:
        raise ValueError(f"{endpoint_id}: BI4 producer SHA mismatch")
    try:
        total = int(values["CaseNp"])
        fixed = int(values["CaseNfixed"])
        fluid = int(values["CaseNfluid"])
        moving = int(values.get("CaseNmoving", 0))
        if (total, fixed, fluid) != (xml["total_particles"], xml["fixed_particles"], xml["fluid_particles"]):
            raise ValueError(f"{endpoint_id}: BI4/XML counts differ")
        if int(case_receipt["total_particles"]) != total or int(case_receipt["fixed_particles"]) != fixed or int(case_receipt["fluid_particles"]) != fluid:
            raise ValueError(f"{endpoint_id}: BI4/per-case receipt counts differ")
        source = source_regions(metadata)
        blocks = {int(row["mkfluid"]): row for row in xml["fluid_blocks"]}
        marker_map = {int(k): int(v) for k, v in metadata["native_marker_semantics"]["expected_generated_mkfluid_to_native_mk"].items()}
        if set(blocks) != set(marker_map):
            raise ValueError(f"{endpoint_id}: XML mkfluid partition differs from metadata")
        fixed_mask = ids < fixed
        if int(np.count_nonzero(fixed_mask)) != fixed:
            raise ValueError(f"{endpoint_id}: Idp fixed range does not contain CaseNfixed")
        fixed_native_types = {int(value) for value in metadata["source_recipe"]["fixed_native_types"]}
        fluid_native_types = {int(value) for value in metadata["source_recipe"]["fluid_native_types"]}
        fixed_mk_ok = bool(np.all(marks[fixed_mask] == int(xml["fixed_mk"])) and np.all(types[fixed_mask] == list(fixed_native_types)[0])) if len(fixed_native_types) == 1 else bool(np.all(np.isin(types[fixed_mask], list(fixed_native_types))))
        if not fixed_mk_ok:
            raise ValueError(f"{endpoint_id}: native fixed Mk/Type differs from XML/source recipe")
        source_rows = []
        for name, region in source.items():
            mkfluid = int(region["mkfluid"])
            block = blocks[mkfluid]
            if block["mk"] != marker_map[mkfluid]:
                raise ValueError(f"{endpoint_id}: XML native mk mapping differs for {name}")
            mask = (ids >= block["begin"]) & (ids < block["begin"] + block["count"])
            cloud = pos[mask]
            native_mk = marks[mask]
            native_type = types[mask]
            if len(cloud) != block["count"]:
                raise ValueError(f"{endpoint_id}: ID range does not bind {name} block")
            low = np.asarray(region["low_m"], dtype=float)
            size = np.asarray(region["size_m"], dtype=float)
            high = low + size
            dp = float(metadata["physical_binding"]["initial_state"].get("dp_m", metadata["source_recipe"]["dp_m"]))
            normalized = (cloud - low) / dp - 0.5
            lattice = np.rint(normalized).astype(np.int64)
            axis_counts = np.rint(size / dp).astype(np.int64)
            expected_cells = int(np.prod(axis_counts))
            checks = {
                "registered_count": block["count"] == len(cloud),
                "native_mass_matches_continuum": bool(np.isclose(block["count"] * float(values["MassFluid"]), float(metadata["physical_binding"]["initial_state"]["continuum_mass_by_source_kg"][name]), rtol=1e-12, atol=1e-12)),
                "strict_continuum_center_bounds": bool(np.all(cloud > low) and np.all(cloud < high)),
                "finite_source_positions": bool(np.isfinite(cloud).all()),
                "exact_center_lattice": bool(np.allclose(normalized, lattice, rtol=0, atol=1e-7)),
                "complete_cell_population": bool(np.all(lattice >= 0) and np.all(lattice < axis_counts) and len(np.unique(lattice, axis=0)) == expected_cells),
                "native_mk_matches_xml": bool(np.all(native_mk == block["mk"])),
                "native_type_matches_source_recipe": bool(np.all(np.isin(native_type, list(fluid_native_types)))),
            }
            source_rows.append({
                "source": name,
                "mkfluid": mkfluid,
                "native_mk": block["mk"],
                "native_mk_counts": {str(int(value)): int(np.count_nonzero(native_mk == value)) for value in np.unique(native_mk)},
                "native_type_counts": {str(int(value)): int(np.count_nonzero(native_type == value)) for value in np.unique(native_type)},
                "fluid_count": int(len(cloud)),
                "native_mass_kg": float(len(cloud) * float(values["MassFluid"])),
                "bounds_m": [cloud.min(axis=0).tolist(), cloud.max(axis=0).tolist()],
                "checks": checks,
            })
        by_source = {row["source"]: row for row in source_rows}
        drop_high = np.asarray(by_source["drop"]["bounds_m"][1])
        drop_low = np.asarray(by_source["drop"]["bounds_m"][0])
        pool_high = np.asarray(by_source["pool"]["bounds_m"][1])
        pool_low = np.asarray(by_source["pool"]["bounds_m"][0])
        tank = metadata["physical_binding"]["geometry"]["tank"]
        tank_low = np.asarray(tank["low_m"], dtype=float)
        tank_high = tank_low + np.asarray(tank["size_m"], dtype=float)
        fixed_pos = pos[fixed_mask]
        face = face_coverage(fixed_pos, tank_low, tank_high, [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0)], float(metadata["source_recipe"]["dp_m"]))
        fluid_mask = ~fixed_mask
        true_3d = not boolish(values.get("Data2d", True)) and len(np.unique(pos[fluid_mask, 1])) > 1
        checks = {
            "gencase_completed_per_case": case_receipt.get("status") == "completed" and case_receipt.get("returncode") == 0,
            "unique_complete_ids": len(ids) == total and np.array_equal(np.sort(ids), np.arange(total)),
            "complete_type_partition": total == fixed + fluid + moving and fluid == sum(row["fluid_count"] for row in source_rows),
            "native_fixed_type_partition": fixed_native_types.issuperset({int(value) for value in np.unique(types[fixed_mask])}) and len(np.unique(types[fixed_mask])) > 0,
            "native_fluid_type_partition": fluid_native_types.issuperset({int(value) for value in np.unique(types[fluid_mask])}) and len(np.unique(types[fluid_mask])) > 0,
            "native_mk_partition": bool(np.all(marks[fixed_mask] == int(xml["fixed_mk"])) and all(np.all(marks[(ids >= block["begin"]) & (ids < block["begin"] + block["count"])] == block["mk"]) for block in blocks.values())),
            "finite_positions": bool(np.isfinite(pos).all()),
            "true_3d": bool(true_3d),
            "finite_tank_face_coverage": all(item["covered"] for item in face.values()),
            "drop_and_pool_bounds_are_separated": bool(drop_low[2] > pool_high[2] or pool_low[2] > drop_high[2]),
            "positive_drop_and_pool_source_rows": all(row["fluid_count"] > 0 and finite_point(row["bounds_m"][0]) and finite_point(row["bounds_m"][1]) for row in source_rows),
            "all_source_population_checks": all(all(row["checks"].values()) for row in source_rows),
            "native_uid_type_mass_and_full3d_checks_present": True,
            "same_constants_initial_velocities_execution": verify_source_invariants(definition, mother),
            "sources_unchanged": True,
        }
        report = {
            "schema": SCHEMA,
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "endpoint_id": endpoint_id,
            "physical_condition_sha256": endpoint["physical_condition_sha256"],
            "gencase_receipt": {"path": str(case_receipt_path), "sha256": sha256(case_receipt_path), "status": case_receipt["status"], "returncode": case_receipt["returncode"]},
            "generated_xml": {"path": str(xml_path), "sha256": xml["sha256"], "counts": xml},
            "native_bi4": {"path": str(native), "sha256": bi4_sha, "producer_sha256": expected_bi4_sha, "arrays_read_readonly": True, "copied": False, "bytes": native.stat().st_size},
            "native_root_values": {key: values[key] for key in ("CaseNp", "CaseNfixed", "CaseNfluid", "CaseNmoving", "MassFluid", "Data2d") if key in values},
            "arrays": {name: {"type_code": desc.type_code, "count": desc.count, "byte_count": desc.byte_count, "item_path": list(desc.item_path)} for name, desc in arrays.items()},
            "source_rows": source_rows,
            "finite_tank_face_coverage": face,
            "total_particles": total,
            "fixed_particles": fixed,
            "fluid_particles": fluid,
            "moving_particles": moving,
            "checks": checks,
            "pass": all(checks.values()),
            "native_audit_returncode": 0 if all(checks.values()) else 1,
            "read_policy": {"bi4": "safe decoder and read-only memmap", "h5": False, "csv": False, "vtk": False, "solver": False, "conversion": False, "rendering": False},
            "q_n_status": "not_assessed", "precision_status": "not_accepted", "production_approval": "none",
        }
        if sha256(native) != expected_bi4_sha:
            raise ValueError(f"{endpoint_id}: immutable BI4 changed during read-only QA")
        report['native_bi4']['producer_hash_verified_after_audit'] = True
        write_json(output, report)
        return report
    finally:
        del pos, ids, marks, types


def run(args: argparse.Namespace) -> int:
    plan = load_json(args.plan)
    source_binding = load_json(args.source_binding)
    root_binding = load_json(args.root195_binding)
    gencase_report = load_json(args.gencase_report)
    parent = load_json(args.gencase_execution_receipt)
    if source_binding.get("upstream_adopted_commit") != "805f36c8" or source_binding.get("upstream_source_commit") != "ae0d8a25":
        raise ValueError("fresh081 adopted source binding changed")
    if root_binding.get("attempt_id") != "root-stage1-f4-internal8-genuine-gencase-195":
        raise ValueError("Root195 evidence binding attempt changed")
    if parent.get("status") != "failed" or parent.get("returncode") != 0 or parent.get("error") != "GenCase actual particle count missing":
        raise ValueError("Root195 failed parent receipt was not preserved")
    endpoints = plan.get("endpoints", [])
    if len(endpoints) != 8 or gencase_report.get("status") != "completed" or int(gencase_report.get("gencase_returncode_failures", -1)) != 0:
        raise ValueError("Root195 aggregate member report is not completed0")
    if gencase_report.get("source_plan_sha256") != sha256(args.plan):
        raise ValueError("Root195 aggregate report is not bound to the frozen source plan")
    commands = {str(row.get("endpoint_id")): row for row in gencase_report.get("commands", []) if isinstance(row, dict)}
    if set(commands) != {str(row["endpoint_id"]) for row in endpoints}:
        raise ValueError("Root195 aggregate report endpoint set differs")
    evidence_rows = {str(row["endpoint_id"]): row for row in root_binding.get("per_case_actual_gencase_receipts", []) if isinstance(row, dict) and row.get("endpoint_id")}
    if set(evidence_rows) != set(commands):
        raise ValueError("Root195 producer binding endpoint set differs")
    for endpoint in endpoints:
        eid = str(endpoint["endpoint_id"])
        command = commands[eid]
        evidence = evidence_rows[eid]
        if command.get("executed") is not True or command.get("returncode") != 0:
            raise ValueError(f"{eid}: aggregate command lacks genuine OS0 evidence")
        if command.get("physical_condition_sha256") != endpoint.get("physical_condition_sha256"):
            raise ValueError(f"{eid}: aggregate physical condition drift")
        if evidence.get("physical_condition_sha256") != endpoint.get("physical_condition_sha256") or evidence.get("solver_dimension_from_gencase") != 3:
            raise ValueError(f"{eid}: Root195 producer binding condition/3D drift")
        if evidence.get("gencase_receipt", {}).get("path") != command.get("gencase_receipt"):
            raise ValueError(f"{eid}: aggregate/per-case receipt path drift")
        if evidence.get("generated_xml", {}).get("path") != command.get("generated_xml") or evidence.get("generated_bi4", {}).get("path") != command.get("generated_bi4"):
            raise ValueError(f"{eid}: aggregate producer output path drift")
    # _load_safe_decoder is provided by the approved F2 helper; load it once
    # explicitly so the producer provenance includes both helper and decoder.
    _helper, scanner = load_safe_scanner(args.helper, args.decoder)
    output_root = args.output_root
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    owners = {str(row["endpoint_id"]): load_json(args.owner_root / f"{row['endpoint_id']}.owner.json") for row in endpoints}
    metadata = {str(row["endpoint_id"]): load_json(args.metadata_root / f"{row['endpoint_id']}.metadata.json") for row in endpoints}
    rows = []
    all_pass = True
    for endpoint in endpoints:
        eid = str(endpoint["endpoint_id"])
        report_path = output_root / "cases" / eid / "native-preflight-audit.json"
        report = audit_case(endpoint=endpoint, owner=owners[eid], metadata=metadata[eid], gencase_root=args.gencase_root, scanner=scanner, helper_path=args.helper, decoder_path=args.decoder, output=report_path)
        rows.append({"endpoint_id": eid, "case_id": eid, "path": str(report_path), "report_sha256": sha256(report_path), "native_audit_returncode": report["native_audit_returncode"], "pass": report["pass"], "checks": report["checks"], "source_rows": report["source_rows"], "total_particles": report["total_particles"], "fluid_particles": report["fluid_particles"], "fixed_particles": report["fixed_particles"], "native_bi4_sha256": report["native_bi4"]["sha256"]})
        all_pass = all_pass and bool(report["pass"])
    index = {
        "schema": "ds02.f4.internal8.native-initial-qa-index.v1",
        "family_id": "F4", "scope_id": plan["scope_id"], "qa_attempt_id": "root-stage1-f4-internal8-native-initial-qa-196",
        "status": "completed" if all_pass else "failed", "pass": all_pass, "native_audit_returncode": 0 if all_pass else 1,
        "cases": rows, "case_count": len(rows),
        "root195_parent_execution_receipt": {"path": str(args.gencase_execution_receipt), "sha256": sha256(args.gencase_execution_receipt), "status": parent["status"], "returncode": parent["returncode"], "error": parent["error"], "preserved_without_promotion": True},
        "gencase_aggregate_report": {"path": str(args.gencase_report), "sha256": sha256(args.gencase_report), "status": gencase_report["status"], "gencase_returncode_failures": gencase_report["gencase_returncode_failures"]},
        "arrays_read_by_job": True, "arrays_copied": False, "bi4_decoder": {"helper": str(args.helper), "helper_sha256": sha256(args.helper), "decoder": str(args.decoder), "decoder_sha256": sha256(args.decoder)},
        "q_n_status": "not_assessed", "precision_status": "not_accepted", "production_approval": "none",
    }
    index_path = args.qa_index
    write_json(index_path, index)
    binder_command = [str(args.python), str(args.binder), "--source-binding", str(args.binder_source_binding), "--plan", str(args.plan), "--source-build-receipt", str(args.source_build_receipt), "--owner-root", str(args.owner_root), "--metadata-root", str(args.metadata_root), "--gencase-report", str(args.gencase_report), "--gencase-execution-receipt", str(args.gencase_execution_receipt), "--gencase-root", str(args.gencase_root), "--native-qa-index", str(index_path), "--validator", str(args.binder_validator), "--output", str(args.binder_output)]
    completed = subprocess.run(binder_command, cwd=str(args.cwd), check=False, capture_output=True, text=True)
    summary = {"schema": "ds02.f4.internal8.native-initial-qa-producer-summary.v1", "index": str(index_path), "index_sha256": sha256(index_path), "binder_command": binder_command, "binder_returncode": completed.returncode, "binder_stdout_tail": completed.stdout[-4000:], "binder_stderr_tail": completed.stderr[-4000:], "binder_output": str(args.binder_output), "binder_output_sha256": sha256(args.binder_output) if args.binder_output.is_file() else None, "status": "completed" if all_pass and completed.returncode == 0 else "failed", "parent_receipt_preserved": True, "arrays_read_by_job": True, "arrays_copied": False}
    write_json(args.producer_summary, summary)
    return 0 if summary["status"] == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-binding", type=Path, required=True)
    parser.add_argument("--root195-binding", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source-build-receipt", type=Path, required=True)
    parser.add_argument("--owner-root", type=Path, required=True)
    parser.add_argument("--metadata-root", type=Path, required=True)
    parser.add_argument("--gencase-report", type=Path, required=True)
    parser.add_argument("--gencase-execution-receipt", type=Path, required=True)
    parser.add_argument("--gencase-root", type=Path, required=True)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--decoder", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--qa-index", type=Path, required=True)
    parser.add_argument("--binder", type=Path, required=True)
    parser.add_argument("--binder-source-binding", type=Path, required=True)
    parser.add_argument("--binder-validator", type=Path, required=True)
    parser.add_argument("--binder-output", type=Path, required=True)
    parser.add_argument("--producer-summary", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as error:
        print(json.dumps({"schema": "ds02.f4.internal8.native-initial-qa-producer-summary.v1", "status": "failed", "error_type": type(error).__name__, "error": str(error), "parent_receipt_preserved": True, "arrays_read_by_job": "unknown_on_exception; inspect logged stage"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

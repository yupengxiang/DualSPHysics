#!/usr/bin/env python3
"""Bounded actual F2 frame-zero QA after a Root GenCase receipt.

This worker may run the official PartVTK binary, but never GenCase or the
solver. It streams the CSV once and emits only dynamic counts, UID/type/Mk
partitions, finite-field checks, and unscaled mass summaries. It does not
retain particle rows or assume the accepted mother's particle count.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "ds02.f2.stage1.actual-initial-qa.v2"
DP = 0.01
TIME_MAX = 4.0
TIME_OUT = 0.01


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Mapping[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON object required: {path}")
    return value


def _float(row: Mapping[str, str], names: tuple[str, ...]) -> float | None:
    for name in names:
        if name in row:
            try:
                value = float(row[name])
            except (TypeError, ValueError):
                return None
            return value if math.isfinite(value) else None
    return None


def _int(row: Mapping[str, str], names: tuple[str, ...]) -> int | None:
    value = _float(row, names)
    return int(value) if value is not None and math.isfinite(value) else None


def _number(value: str | None) -> float | None:
    try:
        parsed = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return parsed if parsed is not None and math.isfinite(parsed) else None


def motion_contract(definition: Path) -> dict[str, Any]:
    """Validate only the source XML's fixed recipe/motion contract."""
    errors: list[str] = []
    root = ET.parse(definition).getroot()
    node = root.find(".//casedef/geometry/definition")
    params = {str(item.attrib.get("key")): str(item.attrib.get("value")) for item in root.findall(".//execution/parameters/parameter")}
    dp = _number(node.attrib.get("dp")) if node is not None else None
    time_max = _number(params.get("TimeMax"))
    time_out = _number(params.get("TimeOut"))
    if dp is None or abs(dp - DP) > 1e-12:
        errors.append(f"source dp={dp!r}, expected {DP}")
    if time_max is None or abs(time_max - TIME_MAX) > 1e-12:
        errors.append(f"source TimeMax={time_max!r}, expected {TIME_MAX}")
    if time_out is None or abs(time_out - TIME_OUT) > 1e-12:
        errors.append(f"source TimeOut={time_out!r}, expected {TIME_OUT}")
    motion_file = root.find(".//casedef/motion/objreal/mvrotfile/file")
    motion_path = (definition.parent / motion_file.attrib["name"]).resolve() if motion_file is not None else None
    times: list[float] = []
    angles: list[float] = []
    finite = True
    if motion_path is None or not motion_path.is_file():
        errors.append("source motion file is missing")
    else:
        for raw in motion_path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            try:
                t_text, a_text = raw.split(";", 1)
                t_value, a_value = float(t_text), float(a_text)
            except ValueError:
                finite = False
                continue
            finite = finite and math.isfinite(t_value) and math.isfinite(a_value)
            times.append(t_value)
            angles.append(a_value)
    increasing = all(b > a for a, b in zip(times, times[1:]))
    if not times or abs(times[0]) > 1e-12 or abs(times[-1] - TIME_MAX) > 1e-9:
        errors.append("source motion does not span 0..4 s")
    if not finite or not increasing:
        errors.append("source motion is nonfinite or nonmonotonic")
    if angles and abs(angles[-1] + 105.0) > 1e-6:
        errors.append("source motion final angle is not -105 degrees")
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "definition": str(definition.resolve()),
        "definition_sha256": sha256(definition),
        "dp_m": dp,
        "time_max_s": time_max,
        "time_out_s": time_out,
        "motion": {
            "path": str(motion_path) if motion_path else None,
            "sha256": sha256(motion_path) if motion_path and motion_path.is_file() else None,
            "rows": len(times),
            "finite": finite,
            "strictly_increasing": increasing,
            "time_start_s": times[0] if times else None,
            "time_end_s": times[-1] if times else None,
            "final_angle_deg": angles[-1] if angles else None,
        },
    }


def actual_xml_contract(xml_path: Path) -> dict[str, Any]:
    """Read generated XML metadata; all particle counts come from this file."""
    errors: list[str] = []
    root = ET.parse(xml_path).getroot()
    constants = {node.tag: dict(node.attrib) for node in root.findall(".//execution/constants/*")}
    params = {str(node.attrib.get("key")): str(node.attrib.get("value")) for node in root.findall(".//execution/parameters/parameter")}
    definition = root.find(".//casedef/geometry/definition")
    dp = _number(definition.attrib.get("dp")) if definition is not None else None
    time_max = _number(params.get("TimeMax"))
    time_out = _number(params.get("TimeOut"))
    if dp is None or abs(dp - DP) > 1e-12:
        errors.append(f"actual XML dp={dp!r}, expected {DP}")
    if time_max is None or abs(time_max - TIME_MAX) > 1e-12:
        errors.append(f"actual XML TimeMax={time_max!r}, expected {TIME_MAX}")
    if time_out is None or abs(time_out - TIME_OUT) > 1e-12:
        errors.append(f"actual XML TimeOut={time_out!r}, expected {TIME_OUT}")
    particle_counts: Counter[str] = Counter()
    particle_by_mk: Counter[str] = Counter()
    for node in root.findall(".//execution/particles/*"):
        kind = str(node.tag)
        # GenCase emits a metadata-only `_summary` sibling without a count.
        raw_count = node.attrib.get("count")
        if raw_count is None:
            continue
        count = int(raw_count)
        particle_counts[kind] += count
        particle_by_mk[f"{kind}:mk={node.attrib.get('mk', '?')}"] += count
    total = sum(particle_counts.values())
    massfluid = _number(constants.get("massfluid", {}).get("value"))
    massbound = _number(constants.get("massbound", {}).get("value"))
    if str(constants.get("data2d", {}).get("value", "")).lower() != "false":
        errors.append("actual XML is not 3D")
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "path": str(xml_path.resolve()),
        "sha256": sha256(xml_path),
        "dp_m": dp,
        "time_max_s": time_max,
        "time_out_s": time_out,
        "actual_particle_counts_from_xml": dict(sorted(particle_counts.items())),
        "actual_particle_counts_by_mk_from_xml": dict(sorted(particle_by_mk.items())),
        "actual_total_particles_from_xml": total,
        "unscaled_mass_constants_kg": {"massfluid": massfluid, "massbound": massbound},
        "data2d": constants.get("data2d", {}).get("value"),
    }


def receipt_output_root(receipt_path: Path, receipt: Mapping[str, Any]) -> Path:
    value = receipt.get("output_root")
    if isinstance(value, str) and value:
        return Path(value).resolve()
    files = receipt.get("output_files")
    if isinstance(files, Mapping):
        for key in ("xml", "bi4"):
            raw = files.get(key)
            if isinstance(raw, str) and raw:
                return Path(raw).resolve().parent
    return receipt_path.parent.resolve()


def run_partvtk(partvtk: Path, bi4: Path, xml: Path, output_dir: Path) -> tuple[Path | None, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / "initial"
    command = [
        str(partvtk), "-filedata", str(bi4), "-filexml", str(xml), "-first:0", "-last:0", "-threads:4",
        "-savecsv", str(prefix), "-onlytype:+all", "-vars:-all,+idp,+vel,+rhop,+type,+mk,+mass,+zone", "-csvsep:1",
    ]
    result = subprocess.run(command, cwd=output_dir, capture_output=True, text=True, check=False, timeout=900)
    log = output_dir / "partvtk.stdout.log"
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    candidates = [p for p in sorted(output_dir.glob("initial*.csv")) if not p.name.endswith("_stats.csv")]
    return (candidates[0] if candidates else None), {
        "command": command,
        "returncode": result.returncode,
        "log": {"path": str(log.resolve()), "sha256": sha256(log)},
    }


def stream_csv(path: Path) -> dict[str, Any]:
    row_count = 0
    finite_rows = 0
    ids: set[int] = set()
    fluid_ids: set[int] = set()
    type_counts: Counter[str] = Counter()
    mk_counts: Counter[str] = Counter()
    uid_partition_counts: Counter[str] = Counter()
    mass_by_type: defaultdict[str, float] = defaultdict(float)
    mass_by_mk: defaultdict[str, float] = defaultdict(float)
    fluid_mass = 0.0
    mass_rows = 0
    errors: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = tuple(reader.fieldnames or ())
        missing = [name for name in ("Type", "Mk", "Idp") if name not in headers]
        if missing:
            errors.append(f"missing columns: {missing}")
        for row in reader:
            row_count += 1
            type_value = _int(row, ("Type",))
            mk_value = _int(row, ("Mk",))
            id_value = _int(row, ("Idp", "Idp [none]"))
            type_key = str(type_value) if type_value is not None else "unknown"
            mk_key = str(mk_value) if mk_value is not None else "unknown"
            type_counts[type_key] += 1
            mk_counts[mk_key] += 1
            uid_partition_counts[f"type={type_key};mk={mk_key}"] += 1
            if id_value is not None:
                ids.add(id_value)
                if type_value == 3:
                    fluid_ids.add(id_value)
            mass = _float(row, ("Mass [kg]", "Mass"))
            if mass is not None:
                mass_rows += 1
                mass_by_type[type_key] += mass
                mass_by_mk[mk_key] += mass
                if type_value == 3:
                    fluid_mass += mass
            numeric = [
                _float(row, ("Pos.x [m]",)), _float(row, ("Pos.y [m]",)), _float(row, ("Pos.z [m]",)),
                _float(row, ("Vel.x [m/s]",)), _float(row, ("Vel.y [m/s]",)), _float(row, ("Vel.z [m/s]",)),
                _float(row, ("Rhop [kg/m^3]",)), mass,
            ]
            if all(value is not None and math.isfinite(value) for value in numeric):
                finite_rows += 1
    return {
        "csv": {"path": str(path.resolve()), "sha256": sha256(path), "bytes": path.stat().st_size},
        "row_count": row_count,
        "finite_row_count": finite_rows,
        "finite_all_rows": finite_rows == row_count,
        "unique_id_count": len(ids),
        "fluid_type3_count": type_counts.get("3", 0),
        "fluid_unique_id_count": len(fluid_ids),
        "type_counts": dict(sorted(type_counts.items())),
        "mk_counts": dict(sorted(mk_counts.items())),
        "uid_partition_counts": dict(sorted(uid_partition_counts.items())),
        "mass_rows": mass_rows,
        "unscaled_mass_sum_kg_by_type": dict(sorted(mass_by_type.items())),
        "unscaled_mass_sum_kg_by_mk": dict(sorted(mass_by_mk.items())),
        "unscaled_fluid_mass_sum_kg": fluid_mass if mass_rows else None,
        "errors": errors,
    }


def audit(args: argparse.Namespace) -> dict[str, Any]:
    definition = Path(args.definition).resolve()
    receipt_path = Path(args.gencase_receipt).resolve()
    receipt = load(receipt_path)
    source = motion_contract(definition)
    output_root = receipt_output_root(receipt_path, receipt)
    files = receipt.get("output_files") if isinstance(receipt.get("output_files"), Mapping) else {}
    xml_path = Path(str(files.get("xml"))).resolve() if isinstance(files.get("xml"), str) else output_root / f"{args.case_id}.xml"
    bi4_path = Path(str(files.get("bi4"))).resolve() if isinstance(files.get("bi4"), str) else output_root / f"{args.case_id}.bi4"
    gencase_success = receipt.get("status") == "completed" and receipt.get("returncode") == 0 and receipt.get("solver_dimension_from_gencase") == 3
    if not xml_path.is_file() or not bi4_path.is_file():
        gencase_success = False
    actual_xml = actual_xml_contract(xml_path) if xml_path.is_file() else {"status": "pending", "path": str(xml_path)}
    csv_path = Path(args.csv).resolve() if args.csv else None
    partvtk: dict[str, Any] = {"status": "supplied_csv" if csv_path else "pending"}
    if csv_path is None and bi4_path.is_file() and xml_path.is_file():
        csv_path, partvtk = run_partvtk(Path(args.partvtk).resolve(), bi4_path, xml_path, Path(args.partvtk_output_dir).resolve())
    if csv_path is None or not csv_path.is_file():
        csv_summary: dict[str, Any] = {"status": "pending", "reason": "PartVTK CSV is not available"}
    else:
        csv_summary = stream_csv(csv_path)
        csv_summary["status"] = "pass" if csv_summary["finite_all_rows"] and csv_summary["fluid_type3_count"] > 0 and not csv_summary["errors"] else "fail"
    receipt_counts = {key: receipt.get(key) for key in ("total_particles", "fluid_particles", "solver_dimension_from_gencase")}
    checks = {
        "actual_gencase_terminal_success": gencase_success,
        "source_motion_contract": source["status"] == "pass",
        "actual_xml_contract": actual_xml.get("status") == "pass",
        "actual_initial_csv_available": csv_summary.get("status") in {"pass", "fail"},
        "all_reported_fields_finite": csv_summary.get("finite_all_rows") is True,
        "positive_type3_fluid": int(csv_summary.get("fluid_type3_count", 0) or 0) > 0,
        "particle_ids_unique_in_report": csv_summary.get("unique_id_count") == csv_summary.get("row_count") if csv_summary.get("row_count") else False,
        "receipt_xml_count_agrees": receipt_counts.get("total_particles") == actual_xml.get("actual_total_particles_from_xml"),
        "receipt_fluid_count_agrees": receipt_counts.get("fluid_particles") == actual_xml.get("actual_particle_counts_from_xml", {}).get("fluid"),
    }
    status = "pass" if all(checks.values()) else "fail" if csv_summary.get("status") == "fail" else "pending"
    report = {
        "schema": SCHEMA,
        "case_id": args.case_id,
        "status": status,
        "source_only_worker": False,
        "claim": "actual bounded initial QA summary only; no solver/visual/precision/Q-N claim",
        "gencase_receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path), "status": receipt.get("status"), "returncode": receipt.get("returncode"), "output_root": str(output_root), "dynamic_counts": receipt_counts},
        "source_motion_contract": source,
        "actual_xml_contract": actual_xml,
        "partvtk": partvtk,
        "csv_summary": csv_summary,
        "checks": checks,
        "mass_policy": "unscaled native MassFluid/Mass values reported from actual XML and streamed CSV; no mother-count or mass substitution",
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--definition", required=True)
    parser.add_argument("--gencase-receipt", required=True)
    parser.add_argument("--partvtk", default="/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
    parser.add_argument("--partvtk-output-dir", default=".")
    parser.add_argument("--csv")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = audit(args)
    return 0 if report["status"] == "pass" else 2 if report["status"] == "fail" else 3


if __name__ == "__main__":
    raise SystemExit(main())

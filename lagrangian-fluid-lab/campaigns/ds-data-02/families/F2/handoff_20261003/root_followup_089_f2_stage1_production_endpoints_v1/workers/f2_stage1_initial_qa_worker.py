#!/usr/bin/env python3
"""Bounded actual initial QA worker for the F2 Stage1 endpoint requests.

Root may enable this CPU audit after a fresh GenCase receipt exists.  The
worker can invoke official PartVTK to stream a frame-zero CSV, but it emits
only a bounded JSON summary; it never starts GenCase or DualSPHysics and never
stores particle arrays in its report.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "ds02.f2.stage1.actual-initial-qa.v1"
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
                return float(row[name])
            except (TypeError, ValueError):
                return None
    return None


def _int(row: Mapping[str, str], names: tuple[str, ...]) -> int | None:
    value = _float(row, names)
    return int(value) if value is not None and math.isfinite(value) else None


def xml_contract(definition: Path) -> dict[str, Any]:
    errors: list[str] = []
    root = ET.parse(definition).getroot()
    node = root.find(".//casedef/geometry/definition")
    params = {str(item.attrib.get("key")): str(item.attrib.get("value")) for item in root.findall(".//execution/parameters/parameter")}
    dp = float(node.attrib["dp"]) if node is not None and "dp" in node.attrib else None
    time_max = float(params["TimeMax"]) if "TimeMax" in params else None
    time_out = float(params["TimeOut"]) if "TimeOut" in params else None
    if dp is None or abs(dp - DP) > 1e-12:
        errors.append(f"dp={dp!r}, expected {DP}")
    if time_max is None or abs(time_max - TIME_MAX) > 1e-12:
        errors.append(f"TimeMax={time_max!r}, expected {TIME_MAX}")
    if time_out is None or abs(time_out - TIME_OUT) > 1e-12:
        errors.append(f"TimeOut={time_out!r}, expected {TIME_OUT}")
    motion_file = root.find(".//casedef/motion/objreal/mvrotfile/file")
    motion_path = (definition.parent / motion_file.attrib["name"]).resolve() if motion_file is not None else None
    motion_rows = 0
    motion_finite = True
    motion_monotonic = True
    motion_start = None
    motion_end = None
    motion_final_angle = None
    if motion_path is None or not motion_path.is_file():
        errors.append("native motion file is missing")
    else:
        times: list[float] = []
        angles: list[float] = []
        for raw in motion_path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            try:
                t_text, a_text = raw.split(";", 1)
                t_value, a_value = float(t_text), float(a_text)
            except ValueError:
                motion_finite = False
                continue
            motion_finite = motion_finite and math.isfinite(t_value) and math.isfinite(a_value)
            times.append(t_value)
            angles.append(a_value)
        motion_rows = len(times)
        motion_monotonic = all(b > a for a, b in zip(times, times[1:]))
        motion_start = times[0] if times else None
        motion_end = times[-1] if times else None
        motion_final_angle = angles[-1] if angles else None
        if not times or abs(times[0]) > 1e-12 or abs(times[-1] - TIME_MAX) > 1e-9:
            errors.append("motion does not span 0..4 s")
        if not motion_finite or not motion_monotonic:
            errors.append("motion rows are nonfinite or nonmonotonic")
        if angles and abs(angles[-1] + 105.0) > 1e-6:
            errors.append("motion final angle is not -105 degrees")
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
            "rows": motion_rows,
            "finite": motion_finite,
            "strictly_increasing": motion_monotonic,
            "time_start_s": motion_start,
            "time_end_s": motion_end,
            "final_angle_deg": motion_final_angle,
        },
    }


def receipt_output_root(receipt_path: Path, receipt: Mapping[str, Any]) -> Path:
    value = receipt.get("output_root")
    if isinstance(value, str) and value:
        return Path(value).resolve()
    value = receipt.get("output_files")
    if isinstance(value, Mapping):
        for key in ("xml", "bi4"):
            raw = value.get(key)
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
    type_counts: Counter[str] = Counter()
    mk_counts: Counter[str] = Counter()
    fluid_ids: set[int] = set()
    errors: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = tuple(reader.fieldnames or ())
        required = ("Type", "Mk", "Idp")
        missing = [name for name in required if name not in headers]
        if missing:
            errors.append(f"missing columns: {missing}")
        for row in reader:
            row_count += 1
            type_value = _int(row, ("Type",))
            mk_value = _int(row, ("Mk",))
            id_value = _int(row, ("Idp", "Idp [none]"))
            if type_value is not None:
                type_counts[str(type_value)] += 1
            if mk_value is not None:
                mk_counts[str(mk_value)] += 1
            if id_value is not None:
                ids.add(id_value)
                if type_value == 3:
                    fluid_ids.add(id_value)
            numeric = [
                _float(row, ("Pos.x [m]",)), _float(row, ("Pos.y [m]",)), _float(row, ("Pos.z [m]",)),
                _float(row, ("Vel.x [m/s]",)), _float(row, ("Vel.y [m/s]",)), _float(row, ("Vel.z [m/s]",)),
                _float(row, ("Rhop [kg/m^3]",)), _float(row, ("Mass [kg]",)),
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
        "errors": errors,
    }


def audit(args: argparse.Namespace) -> dict[str, Any]:
    definition = Path(args.definition).resolve()
    receipt_path = Path(args.gencase_receipt).resolve()
    receipt = load(receipt_path)
    xml = xml_contract(definition)
    output_root = receipt_output_root(receipt_path, receipt)
    files = receipt.get("output_files") if isinstance(receipt.get("output_files"), Mapping) else {}
    xml_path = Path(str(files.get("xml"))).resolve() if isinstance(files.get("xml"), str) else output_root / f"{args.case_id}.xml"
    bi4_path = Path(str(files.get("bi4"))).resolve() if isinstance(files.get("bi4"), str) else output_root / f"{args.case_id}.bi4"
    gencase_success = receipt.get("status") == "completed" and receipt.get("returncode") == 0 and receipt.get("solver_dimension_from_gencase") == 3
    if not xml_path.is_file() or not bi4_path.is_file():
        gencase_success = False
    csv_path = Path(args.csv).resolve() if args.csv else None
    partvtk: dict[str, Any] = {"status": "supplied_csv" if csv_path else "pending"}
    if csv_path is None and bi4_path.is_file() and xml_path.is_file():
        csv_path, partvtk = run_partvtk(Path(args.partvtk).resolve(), bi4_path, xml_path, Path(args.partvtk_output_dir).resolve())
    if csv_path is None or not csv_path.is_file():
        csv_summary = {"status": "pending", "reason": "PartVTK CSV is not available"}
    else:
        csv_summary = stream_csv(csv_path)
        csv_summary["status"] = "pass" if csv_summary["finite_all_rows"] and csv_summary["fluid_type3_count"] > 0 and not csv_summary["errors"] else "fail"
    checks = {
        "actual_gencase_terminal_success": gencase_success,
        "source_xml_contract": xml["status"] == "pass",
        "actual_initial_csv_available": csv_summary.get("status") in {"pass", "fail"},
        "all_reported_fields_finite": csv_summary.get("finite_all_rows") is True,
        "positive_type3_fluid": int(csv_summary.get("fluid_type3_count", 0) or 0) > 0,
        "particle_ids_unique_in_report": csv_summary.get("unique_id_count") == csv_summary.get("row_count") if csv_summary.get("row_count") else False,
    }
    status = "pass" if all(checks.values()) else "fail" if csv_summary.get("status") == "fail" else "pending"
    report = {
        "schema": SCHEMA,
        "case_id": args.case_id,
        "status": status,
        "source_only_worker": False,
        "claim": "actual bounded initial QA summary only; no solver/visual/precision/Q-N claim",
        "gencase_receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path), "status": receipt.get("status"), "returncode": receipt.get("returncode"), "output_root": str(output_root)},
        "xml_contract": xml,
        "partvtk": partvtk,
        "csv_summary": csv_summary,
        "checks": checks,
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
    parser.add_argument("--partvtk", default="/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
    parser.add_argument("--partvtk-output-dir", default=".")
    parser.add_argument("--csv")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = audit(args)
    return 0 if report["status"] == "pass" else 2 if report["status"] == "fail" else 3


if __name__ == "__main__":
    raise SystemExit(main())

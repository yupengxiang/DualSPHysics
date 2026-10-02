#!/usr/bin/env python3
"""Summarize the actual DP005 PartVTKOut exports within the CPU budget.

The v2 diagnostic already completed the official PartVTKOut calls and left
the raw CSV/Stats/VTK artifacts immutable before its reserved-storage guard
terminated the oversized JSONL enrichment.  This additive reader consumes
those raw exports, joins each Idp/PartOut/Motive/position to RunPARTs time,
and writes a compact CSV plus the measured RV4 mother comparison.  It never
invokes a solver or rewrites the raw export.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


FAMILY_ROOT = Path(__file__).resolve().parent
V1_SCRIPT = FAMILY_ROOT / "f2_handoff_20261002_dp005_native_diagnostic_v1.py"


class SummaryError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(require_file(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SummaryError(f"{label} is not an object: {path}")
    return value


def import_v1() -> Any:
    spec = importlib.util.spec_from_file_location("f2_dp005_native_v1", V1_SCRIPT)
    if spec is None or spec.loader is None:
        raise SummaryError(f"cannot import {V1_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runparts(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    header: list[str] | None = None
    with require_file(path, "RunPARTs.csv").open(encoding="utf-8", errors="replace", newline="") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if header is None:
                header = [item.strip() for item in line.split(";")]
                continue
            values = [item.strip() for item in line.split(";")]
            if len(values) != len(header):
                continue
            record = dict(zip(header, values))
            try:
                rows.append({
                    "part": int(record["Part"].replace(",", "")),
                    "time_s": float(record["TimeStep [s]"].replace(",", "")),
                    "NpOut": int(float(record["NpOut"].replace(",", ""))),
                    "NpOutPos": int(float(record["NpOutPos"].replace(",", ""))),
                    "NpOutRho": int(float(record["NpOutRho"].replace(",", ""))),
                    "NpOutMov": int(float(record["NpOutMov"].replace(",", ""))),
                })
            except (KeyError, TypeError, ValueError):
                continue
    rows.sort(key=lambda row: int(row["part"]))
    if not rows or [int(row["part"]) for row in rows] != list(range(len(rows))):
        raise SummaryError(f"RunPARTs parts are not contiguous: {path}")
    return rows


def compact_float(text: str) -> str:
    return format(float(text.strip()), ".9g")


def summarize_case(case: dict[str, Any], *, v1: Any, output_root: Path) -> dict[str, Any]:
    case_id = str(case["case_id"])
    xml_path = require_file(Path(str(case["generated_xml"])), f"{case_id} XML")
    runpart_rows = runparts(Path(str(case["runparts"])))
    csv_path = require_file(Path(str(case["partvtkout_csv"])), f"{case_id} PartVTKOut CSV")
    stats_path = require_file(Path(str(case["partvtkout_stats"])), f"{case_id} PartVTKOut Stats")
    log_path = require_file(Path(str(case["partvtkout_log"])), f"{case_id} PartVTKOut log")
    signature = v1.geometry_signature(xml_path)
    ranges = v1.parse_ranges(xml_path)
    motion = v1.motion_values(require_file(Path(str(case["motion"])), f"{case_id} motion"))
    output_csv = output_root / "records" / f"{case_id}.csv"
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "idp", "part_out", "first_missing_time_s", "motive", "pos_x_m", "pos_y_m", "pos_z_m",
        "vel_x_m_s", "vel_y_m_s", "vel_z_m_s", "density_kg_m3", "typed_status", "type", "mk",
        "source", "domain_inside", "domain_near_faces", "cup_initial_aabb", "receiver_aabb", "tray_aabb",
    ]
    motive_totals: dict[str, int] = {}
    type_totals: dict[str, int] = {}
    near_face_totals: dict[str, int] = {}
    row_count = 0
    unresolved = 0
    min_part = None
    max_part = None
    with csv_path.open(encoding="utf-8", errors="replace", newline="") as source, output_csv.open("w", encoding="utf-8", newline="") as target:
        lines = source.readlines()
        header_index = next((index for index, line in enumerate(lines) if line.startswith("Pos.x [m]")), None)
        if header_index is None:
            raise SummaryError(f"PartVTKOut CSV has no particle header: {csv_path}")
        reader = csv.DictReader(lines[header_index:], skipinitialspace=True)
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        for raw in reader:
            if not raw or not str(raw.get("Idp", "")).strip():
                continue
            try:
                idp = int(str(raw["Idp"]).strip())
                part = int(str(raw["PartOut"]).strip())
                motive_value = int(str(raw["Motive"]).strip())
                position = [float(raw[key]) for key in ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]")]
                velocity = [float(raw[key]) for key in ("Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]")]
                density = float(raw["Rhop [kg/m^3]"])
            except (KeyError, TypeError, ValueError) as error:
                raise SummaryError(f"invalid PartVTKOut row in {csv_path}: {raw}") from error
            time_s = runpart_rows[part]["time_s"] if 0 <= part < len(runpart_rows) else None
            if time_s is None:
                unresolved += 1
            identity = v1.typed_identity(idp, ranges)
            location = v1.position_evidence(position, signature, float(case["dp_m"]))
            near_faces = location["simulation_domain"].get("near_faces_within_2dp", [])
            for face in near_faces:
                near_face_totals[face] = near_face_totals.get(face, 0) + 1
            motive_key = str(motive_value)
            motive_totals[motive_key] = motive_totals.get(motive_key, 0) + 1
            type_key = str(identity.get("type", "unknown"))
            type_totals[type_key] = type_totals.get(type_key, 0) + 1
            writer.writerow({
                "idp": idp,
                "part_out": part,
                "first_missing_time_s": "" if time_s is None else compact_float(str(time_s)),
                "motive": motive_value,
                "pos_x_m": compact_float(str(position[0])),
                "pos_y_m": compact_float(str(position[1])),
                "pos_z_m": compact_float(str(position[2])),
                "vel_x_m_s": compact_float(str(velocity[0])),
                "vel_y_m_s": compact_float(str(velocity[1])),
                "vel_z_m_s": compact_float(str(velocity[2])),
                "density_kg_m3": compact_float(str(density)),
                "typed_status": identity.get("status"),
                "type": identity.get("type", "unknown"),
                "mk": identity.get("mk", "unknown"),
                "source": identity.get("source", "unknown"),
                "domain_inside": location["simulation_domain"].get("inside_without_tolerance", "unknown"),
                "domain_near_faces": "|".join(near_faces),
                "cup_initial_aabb": location["finite_geometry"].get("moving_cup_initial_aabb", {}).get("inside_initial_aabb_with_2dp"),
                "receiver_aabb": location["finite_geometry"].get("receiver_aabb", {}).get("inside_initial_aabb_with_2dp"),
                "tray_aabb": location["finite_geometry"].get("tray_aabb", {}).get("inside_initial_aabb_with_2dp"),
            })
            row_count += 1
            min_part = part if min_part is None else min(min_part, part)
            max_part = part if max_part is None else max(max_part, part)
    comparison = v1.comparison_record(case, signature, motion)
    source_files = [
        V1_SCRIPT, xml_path, Path(str(case["motion"])), Path(str(case["runparts"])), csv_path, stats_path, log_path,
        Path(str(case["solver_receipt"])), Path(str(case["gencase_receipt"])), Path(str(case["owner_metadata"])), output_csv,
        Path(str(case["v2_receipt"])), Path(str(case["rv4"]["generated_xml"])), Path(str(case["rv4"]["motion"])),
        Path(str(case["rv4"]["owner_metadata"])), Path(str(case["rv4"]["conversion_report"])),
    ]
    bindings = {str(path.resolve()): {"path": str(path.resolve()), "sha256": sha256(path)} for path in source_files if path.is_file()}
    return {
        "case_id": case_id,
        "background": case.get("background"),
        "dp_m": float(case["dp_m"]),
        "physical_case_id": case.get("physical_case_id"),
        "source_bindings": bindings,
        "runparts": {
            "path": str(Path(str(case["runparts"]))),
            "sha256": sha256(Path(str(case["runparts"]))),
            "rows": len(runpart_rows),
            "first_time_s": runpart_rows[0]["time_s"],
            "last_time_s": runpart_rows[-1]["time_s"],
            "NpOut_sum": sum(row["NpOut"] for row in runpart_rows),
            "NpOutPos_sum": sum(row["NpOutPos"] for row in runpart_rows),
            "NpOutRho_sum": sum(row["NpOutRho"] for row in runpart_rows),
            "NpOutMov_sum": sum(row["NpOutMov"] for row in runpart_rows),
        },
        "partvtkout_export": {
            "binary": {"path": str(case["partvtkout_binary"]), "sha256": str(case["partvtkout_binary_sha256"])},
            "raw_csv": {"path": str(csv_path), "sha256": sha256(csv_path), "bytes": csv_path.stat().st_size},
            "raw_stats": {"path": str(stats_path), "sha256": sha256(stats_path)},
            "stdout_log": {"path": str(log_path), "sha256": sha256(log_path)},
            "row_count": row_count,
            "part_range": [min_part, max_part],
            "motive_totals": dict(sorted(motive_totals.items())),
            "typed_type_totals": dict(sorted(type_totals.items())),
            "near_domain_face_totals": dict(sorted(near_face_totals.items())),
            "unresolved_first_missing_parts": unresolved,
            "compact_records": {"path": str(output_csv), "sha256": sha256(output_csv), "bytes": output_csv.stat().st_size, "columns_include": ["idp", "part_out", "first_missing_time_s", "motive", "pos_x_m", "pos_y_m", "pos_z_m"]},
            "all_motive_rows_remain_numerical_unknown": True,
        },
        "strict_mother_equivalence": comparison,
        "interpretation": {
            "raw_export_was_produced_by_official_partvtkout": True,
            "motive_is_not_physical_spill": True,
            "position_near_domain_face_is_not_physical_spill": True,
            "moving_cup_classification_uses_initial_aabb_only": True,
            "finite_receiver_tray_membership_is_geometric_side_evidence_only": True,
            "qualification_claim": "none",
            "production_claim": "none",
            "scientific_status": "native_exclusions_decoded_and_mother_equivalence_pending_root_review",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = require_file(args.manifest, "DP005 summary manifest")
    manifest = load_json(manifest_path, "DP005 summary manifest")
    if manifest.get("schema") != "ds-data-02.f2.dp005-native-summary-input.v1":
        raise SummaryError(f"unexpected manifest schema: {manifest.get('schema')!r}")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 2:
        raise SummaryError("DP005 summary manifest must contain exactly two cases")
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    v1 = import_v1()
    report = {
        "schema": "ds-data-02.f2.dp005-native-summary.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "cases": [summarize_case(case, v1=v1, output_root=output.parent / "artifacts") for case in cases],
        "status": "diagnostic_complete_pending_scientific_review",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "path": str(output), "sha256": sha256(output), "case_count": 2}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

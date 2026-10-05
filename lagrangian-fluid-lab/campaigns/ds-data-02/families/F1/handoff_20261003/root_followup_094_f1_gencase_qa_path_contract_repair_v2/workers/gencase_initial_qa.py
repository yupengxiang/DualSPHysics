#!/usr/bin/env python3
"""Pre-native GenCase QA for the F1 Root283 outputs.

Root enables the native solver only after this worker passes.  It reads the
actual GenCase BI4 through the official PartVTK decoder and checks particle
identity, type/Mk partition, finite coordinates, positive mass/density, 3-D
extent, and dynamic counts from the registered prepared-input report.  It
never treats the GenCase velocity declaration as proof of the solver's saved
initial state; that check belongs to the downstream native frame-0 audit.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export(prefix: Path, output_dir: Path, partvtk: Path, tag: str) -> tuple[np.ndarray, dict[str, Any]]:
    xml = Path(str(prefix) + ".xml")
    bi4 = Path(str(prefix) + ".bi4")
    if not xml.is_file() or not bi4.is_file():
        raise FileNotFoundError(f"registered GenCase output is incomplete: {prefix}")
    before = sha256(bi4)
    csv_path = output_dir / f"{tag}-gencase-initial.csv"
    if csv_path.exists():
        raise FileExistsError(csv_path)
    subprocess.run(
        [
            str(partvtk),
            "-filedata", str(bi4),
            "-filexml", str(xml),
            "-threads:2",
            "-savecsv", str(csv_path),
            "-onlytype:+all",
            "-vars:-all,+idp,+rhop,+type,+mk,+mass,+zone",
            "-csvsep:1",
        ],
        check=True,
    )
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if "Pos.x [m]" in row:
                columns = row
                break
        else:
            raise ValueError("official PartVTK CSV header is missing")
        keys = [
            "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp",
            "Type", "Mk", "Mass [kg]", "Rhop [kg/m^3]",
        ]
        indexes = [columns.index(key) for key in keys]
        parsed: list[list[float]] = []
        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            if len(row) <= max(indexes):
                raise ValueError("official PartVTK CSV row is shorter than its header")
            parsed.append([float(row[index]) for index in indexes])
    if sha256(bi4) != before:
        raise AssertionError("PartVTK changed the registered GenCase BI4")
    if not parsed:
        raise ValueError("official PartVTK CSV contains no particles")
    return np.asarray(parsed, dtype=float), {
        "initial_bi4_sha256": before,
        "generated_xml_sha256": sha256(xml),
        "official_csv_sha256": sha256(csv_path),
        "official_csv": str(csv_path),
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    binding = json.loads(Path(args.binding).read_text(encoding="utf-8"))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    partvtk = Path(binding["partvtk"])
    results = []
    for case in binding["cases"]:
        case_id = case["case_id"]
        receipt = json.loads(Path(case["gencase_receipt"]).read_text(encoding="utf-8"))
        require(receipt.get("status") == "completed" and receipt.get("returncode") == 0,
                f"GenCase receipt is not completed/0: {case_id}")
        rows, provenance = export(Path(case["prefix"]), output_dir, partvtk, case_id)
        expected_counts = {key: int(value) for key, value in case["actual_particle_counts"].items()}
        expected_total = int(case["actual_total_particles"])
        require(rows.shape == (expected_total, 9), f"particle shape failed: {case_id}: {rows.shape}")
        require(np.isfinite(rows).all(), f"nonfinite native fields: {case_id}")
        require(np.array_equal(rows[:, 3:7], np.floor(rows[:, 3:7])), f"integer fields are not integral: {case_id}")
        require(np.all(rows[:, 3] == 0), f"unexpected Zone values: {case_id}")
        ids = rows[:, 4].astype(np.int64)
        require(np.array_equal(np.sort(ids), np.arange(expected_total)), f"Idp identity failed: {case_id}")
        types = rows[:, 5].astype(np.int64)
        require(set(types.tolist()) == set(case.get("expected_types", [0, 3])), f"unexpected particle types: {case_id}")
        fluid = types == int(case.get("fluid_type", 3))
        boundary = ~fluid
        require(int(fluid.sum()) == expected_counts["fluid"], f"fluid count failed: {case_id}")
        require(int(boundary.sum()) == expected_counts["fixed"] + expected_counts.get("moving", 0) + expected_counts.get("floating", 0),
                f"nonfluid count failed: {case_id}")
        require(np.all(rows[:, 6][fluid] == int(case.get("fluid_mk", 1))), f"fluid Mk failed: {case_id}")
        require(np.all(rows[:, 7] > 0) and np.all(rows[:, 8] > 0), f"mass/density positivity failed: {case_id}")
        coords = rows[:, :3]
        require(len(np.unique(coords, axis=0)) == expected_total, f"duplicate coordinates: {case_id}")
        fluid_coords = coords[fluid]
        require(all(len(np.unique(fluid_coords[:, axis])) > 1 for axis in range(3)), f"fluid is not genuine 3-D: {case_id}")
        tree = ET.parse(str(case["prefix"]) + ".xml").getroot()
        # GenCase's generated XML has no execution/constants/data2d node. The
        # registered producer report is the authority for data2d=false; the XML
        # geometry definition independently proves a nonzero z extent.
        prepared_report_path = Path(case["prepared_input_report"])
        prepared_report = json.loads(prepared_report_path.read_text(encoding="utf-8"))
        data2d = prepared_report.get("actual_generated_constants", {}).get("data2d", {})
        require(str(data2d.get("value", "")).lower() == "false", f"GenCase report is not 3-D: {case_id}")
        definition = tree.find("./casedef/geometry/definition")
        require(definition is not None, f"GenCase XML geometry definition missing: {case_id}")
        pointmin = definition.find("pointmin") if definition is not None else None
        pointmax = definition.find("pointmax") if definition is not None else None
        require(pointmin is not None and pointmax is not None and float(pointmax.get("z", "nan")) > float(pointmin.get("z", "nan")), f"GenCase XML is not genuine 3-D: {case_id}")
        results.append({
            "case_id": case_id,
            "passed": True,
            "native_particles": expected_total,
            "native_fluid": int(fluid.sum()),
            "native_nonfluid": int(boundary.sum()),
            "native_type_counts": {str(int(value)): int((types == value).sum()) for value in np.unique(types)},
            "native_zone_count": int(len(np.unique(rows[:, 3]))),
            "native_idp_min": int(ids.min()),
            "native_idp_max": int(ids.max()),
            "actual_3d": True,
            "fluid_coordinate_bounds_m": [fluid_coords.min(axis=0).tolist(), fluid_coords.max(axis=0).tolist()],
            "fluid_mk": int(case.get("fluid_mk", 1)),
            "source_velocity_status": "GenCase declaration recorded only; not solver initial-state evidence",
            **provenance,
        })
    report = {
        "schema": "ds02.f1.gencase-initial-qa.v1",
        "stage": "pre_native_solver",
        "cases": results,
        "native_solver_receipt_required": False,
        "gencase_raw_velocity_claim": "not_used_as_solver_initial_velocity_proof",
        "q_n": "not_granted",
        "production_approval": "none",
        "independent_case_count_increment": 0,
    }
    (output_dir / "gencase-initial-qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Strict native initial-state QA for the prospective F1 initial-vx axis.

This is a runnable worker for Root's later enabled request.  It is intentionally
more specific than the historical zero-velocity QA worker: Type 3/Mk 1 fluid
particles must carry the requested uniform velocity, while Type 0 boundary
particles must remain at rest.  The worker never changes a BI4 file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export(prefix: Path, output_dir: Path, partvtk: Path, tag: str) -> tuple[np.ndarray, dict[str, str]]:
    xml = Path(str(prefix) + ".xml")
    bi4 = Path(str(prefix) + ".bi4")
    if not xml.is_file() or not bi4.is_file():
        raise FileNotFoundError(f"future GenCase output is incomplete: {prefix}")
    before = sha256(bi4)
    csv_path = output_dir / f"{tag}-initial-all.csv"
    if csv_path.exists():
        raise FileExistsError(csv_path)
    subprocess.run(
        [
            str(partvtk),
            "-filedata",
            str(bi4),
            "-filexml",
            str(xml),
            "-threads:2",
            "-savecsv",
            str(csv_path),
            "-onlytype:+all",
            "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone",
            "-csvsep:1",
        ],
        check=True,
    )
    with csv_path.open(newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if "Pos.x [m]" in row:
                columns = row
                break
        else:
            raise ValueError("official PartVTK CSV header is missing")
        keys = [
            "Pos.x [m]",
            "Pos.y [m]",
            "Pos.z [m]",
            "Zone",
            "Idp",
            "Type",
            "Mk",
            "Mass [kg]",
            "Vel.x [m/s]",
            "Vel.y [m/s]",
            "Vel.z [m/s]",
            "Rhop [kg/m^3]",
            "Press [Pa]",
        ]
        rows = np.loadtxt(
            handle,
            delimiter=",",
            usecols=[columns.index(key) for key in keys],
            ndmin=2,
        )
    if sha256(bi4) != before:
        raise AssertionError("PartVTK changed the input BI4")
    return rows, {
        "initial_bi4_sha256": before,
        "generated_xml_sha256": sha256(xml),
        "official_csv_sha256": sha256(csv_path),
        "official_csv": str(csv_path),
    }


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
        receipt = json.loads(Path(case["receipt"]).read_text(encoding="utf-8"))
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise AssertionError(f"GenCase receipt is not completed: {case['case_id']}")
        rows, provenance = export(Path(case["prefix"]), output_dir, partvtk, case["case_id"])
        expected_total = int(case["expected_total"])
        expected_fluid = int(case["expected_fluid"])
        expected_v = np.asarray(case["expected_velocity_m_per_s"], dtype=float)
        if rows.shape != (expected_total, 13) or not np.isfinite(rows).all():
            raise AssertionError(f"shape/finite check failed: {case['case_id']}: {rows.shape}")
        if not np.array_equal(rows[:, 3:7], np.floor(rows[:, 3:7])):
            raise AssertionError("integer particle fields are not integral")
        if not np.all(rows[:, 3] == 0) or not np.array_equal(np.sort(rows[:, 4]), np.arange(len(rows))):
            raise AssertionError("zone or Idp invariant failed")
        if set(rows[:, 5].astype(int)) != set(case.get("expected_types", [0, 3])):
            raise AssertionError("unexpected native particle types")
        fluid = rows[:, 5].astype(int) == int(case.get("fluid_type", 3))
        boundary = ~fluid
        if int(fluid.sum()) != expected_fluid:
            raise AssertionError(f"fluid count failed: {case['case_id']}")
        if np.max(np.abs(rows[fluid, 8:11] - expected_v), initial=0.0) > 1e-8:
            raise AssertionError(f"fluid initial velocity failed: {case['case_id']}")
        if np.max(np.abs(rows[boundary, 8:11]), initial=0.0) > 1e-8:
            raise AssertionError(f"boundary velocity is nonzero: {case['case_id']}")
        if np.any(rows[:, 7] <= 0) or np.any(rows[:, 11] <= 0):
            raise AssertionError("mass/density positivity failed")
        if len(np.unique(rows[:, :3], axis=0)) != len(rows):
            raise AssertionError("duplicate particle coordinates")
        fluid_coords = rows[fluid, :3]
        if any(len(np.unique(fluid_coords[:, axis])) <= 1 for axis in range(3)):
            raise AssertionError("fluid is not three-dimensional")
        if "expected_fluid_envelope_m" in case:
            expected_envelope = np.asarray(case["expected_fluid_envelope_m"], dtype=float)
            actual_envelope = np.stack([fluid_coords.min(axis=0), fluid_coords.max(axis=0)])
            if np.max(np.abs(actual_envelope - expected_envelope)) >= 1e-7:
                raise AssertionError(f"fluid envelope changed unexpectedly: {case['case_id']}")
        tree = ET.parse(str(Path(case["prefix"]) + ".xml")).getroot()
        data2d = tree.find("./execution/constants/data2d")
        if data2d is None or data2d.get("value") != "false":
            raise AssertionError("native output is not marked 3-D")
        results.append(
            {
                **case,
                **provenance,
                "passed": True,
                "native_particles": int(len(rows)),
                "native_fluid": int(fluid.sum()),
                "native_boundary": int(boundary.sum()),
                "actual_3d": True,
                "native_type_counts": {
                    str(int(k)): int((rows[:, 5].astype(int) == k).sum())
                    for k in np.unique(rows[:, 5].astype(int))
                },
                "actual_fluid_envelope_m": [
                    fluid_coords.min(axis=0).tolist(),
                    fluid_coords.max(axis=0).tolist(),
                ],
                "official_csv_fluid_mass_sum_kg": float(rows[fluid, 7].sum()),
                "mass_precision": "Official CSV rounded export; native BI4 weights remain the mass authority",
            }
        )
    output = output_dir / "native-initial-vx-qa.json"
    output.write_text(
        json.dumps(
            {
                "schema": "ds02.f1.initial-vx-native-initial-qa.v1",
                "cases": results,
                "q_n": "not_granted",
                "production_approval": "none",
                "independent_case_count_increment": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

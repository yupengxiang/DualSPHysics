#!/usr/bin/env python3
"""Root-only native frame-0 QA for F1 fresh085.

The source package only serializes this worker and disabled bindings. Root may
execute it after a native solver receipt is completed/0. It derives particle
counts from each actual Root283 prepared-input-report.json and uses official
PartVTK for the solver-saved frame. It never trusts source forecast counts.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path
import xml.etree.ElementTree as ET


def load(path: Path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(value, message: str):
    if not value:
        raise RuntimeError(message)


def finite_number(value, message: str) -> float:
    result = float(str(value).strip())
    require(math.isfinite(result), message)
    return result


def column(header, names):
    for name in names:
        if name in header:
            return header.index(name)
    raise RuntimeError(f"missing CSV column {names}")


def frame_summary(summary, case_id: str):
    header_info = None
    for index, row in enumerate(summary):
        labels = {item.strip(): position for position, item in enumerate(row) if item.strip()}
        if all(name in labels for name in ("TimeStep [s]", "Np", "Nfluid")):
            header_info = (index, labels, row)
            break
    require(header_info is not None, f"{case_id}: missing named TimeStep header")
    index, labels, header = header_info
    data = next((row for row in summary[index + 1:] if any(item.strip() for item in row)), None)
    require(data is not None, f"{case_id}: missing TimeStep row")
    time_s = finite_number(data[labels["TimeStep [s]"]], "TimeStep [s]")
    require(abs(time_s) <= 5e-5, f"{case_id}: first saved frame is not t=0")
    return {
        "time_s": time_s,
        "np": int(finite_number(data[labels["Np"]], "Np")),
        "nfluid": int(finite_number(data[labels["Nfluid"]], "Nfluid")),
        "header": header,
        "row": data,
    }


def audit(case, output_dir: Path):
    case_id = case["case_id"]
    receipt = load(Path(case["native_solver_receipt"]))
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, f"{case_id}: native receipt is not completed/0")

    prepared = load(Path(case["prepared_input_report"]))
    counts = prepared.get("generated_xml_particle_counts")
    require(isinstance(counts, dict), f"{case_id}: actual particle-count object missing")
    total = int(prepared["actual_total_particles"])
    fluid_expected = int(counts["fluid"])
    fixed_expected = int(counts["fixed"])
    moving_expected = int(counts.get("moving", 0))
    floating_expected = int(counts.get("floating", 0))
    require(total == fixed_expected + moving_expected + floating_expected + fluid_expected, f"{case_id}: actual count sum mismatch")
    require(case.get("actual_total_particles") == total, f"{case_id}: binding total differs from actual report")
    require(case.get("actual_particle_counts", {}).get("fluid") == fluid_expected, f"{case_id}: binding fluid count differs from actual report")

    xml_path = Path(case["generated_xml"])
    root = ET.parse(xml_path).getroot()
    data2d = root.find("./execution/constants/data2d")
    require(data2d is not None and str(data2d.get("value", "")).lower() == "false", f"{case_id}: generated XML is not 3-D")
    generated_xml_sha = sha256_file(xml_path)
    require(generated_xml_sha == case["generated_xml_sha256"], f"{case_id}: generated XML producer SHA mismatch")

    frame = Path(case["native_data_dir"]) / "Part_0000.bi4"
    require(frame.is_file(), f"{case_id}: native frame-0 BI4 missing")
    before = sha256_file(frame)
    prefix = output_dir / f"{case_id}-frame0"
    command = [
        case["partvtk"], "-dirdata", str(frame.parent), "-first:0", "-last:0", "-threads:4",
        "-savecsv", str(prefix), "-onlytype:+all",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1",
    ]
    subprocess.run(command, cwd=output_dir, check=True)
    csv_files = sorted(prefix.parent.glob(f"{prefix.name}_*.csv"))
    require(csv_files, f"{case_id}: official PartVTK produced no CSV")

    summary = []
    header = None
    rows = 0
    finite_rows = 0
    fluid_rows = 0
    identities = set()
    coordinates = set()
    levels = [set(), set(), set()]
    max_velocity_error = 0.0
    expected_velocity = tuple(float(value) for value in case["expected_velocity_m_per_s"])
    with csv_files[0].open(newline="", encoding="utf-8") as stream:
        for row in csv.reader(stream):
            if header is None:
                if "Pos.x [m]" in row:
                    header = row
                else:
                    summary.append(row)
                continue
            if not any(item.strip() for item in row):
                continue
            positions = {
                key: column(header, names)
                for key, names in {
                    "x": ("Pos.x [m]",), "y": ("Pos.y [m]",), "z": ("Pos.z [m]",),
                    "id": ("Idp", "Idp [none]"), "zone": ("Zone",), "type": ("Type",),
                    "mk": ("Mk",), "mass": ("Mass [kg]", "Mass"),
                    "vx": ("Vel.x [m/s]",), "vy": ("Vel.y [m/s]",), "vz": ("Vel.z [m/s]",),
                    "rho": ("Rhop [kg/m^3]",),
                }.items()
            }
            values = [finite_number(row[positions[key]], key) for key in ("x", "y", "z", "mass", "vx", "vy", "vz", "rho")]
            rows += 1
            finite_rows += int(all(math.isfinite(value) for value in values))
            coordinates.add((values[0], values[1], values[2]))
            identities.add((int(float(row[positions["zone"]])), int(float(row[positions["id"]]))))
            for axis, value in enumerate(values[:3]):
                levels[axis].add(value)
            if int(float(row[positions["type"]])) == 3 and int(float(row[positions["mk"]])) == int(case["fluid_mk"]):
                fluid_rows += 1
                max_velocity_error = max(max_velocity_error, *(abs(actual - expected) for actual, expected in zip(values[4:7], expected_velocity)))

    require(header is not None, f"{case_id}: particle header missing")
    summary_record = frame_summary(summary, case_id)
    require(summary_record["np"] == total and summary_record["nfluid"] == fluid_expected, f"{case_id}: official summary counts differ from actual GenCase report")
    require(rows == total and finite_rows == rows, f"{case_id}: finite/native row count mismatch")
    require(fluid_rows == fluid_expected, f"{case_id}: Type3/Mk1 fluid count mismatch")
    require(len(identities) == rows and len(coordinates) == rows, f"{case_id}: duplicate identity or coordinates")
    require(all(len(axis) > 1 for axis in levels), f"{case_id}: native output is not genuine 3-D")
    require(max_velocity_error <= 1e-6, f"{case_id}: frame-0 velocity mismatch")
    after = sha256_file(frame)
    require(after == before, f"{case_id}: PartVTK mutated solver BI4")
    return {
        "case_id": case_id,
        "passed": True,
        "actual_particle_counts": {"fixed": fixed_expected, "moving": moving_expected, "floating": floating_expected, "fluid": fluid_expected},
        "actual_total_particles": total,
        "native_rows": rows,
        "fluid_rows": fluid_rows,
        "finite_rows": finite_rows,
        "unique_identity_count": len(identities),
        "unique_coordinate_count": len(coordinates),
        "fluid_3d_levels": [len(axis) for axis in levels],
        "frame_summary": summary_record,
        "max_abs_velocity_error_m_per_s": max_velocity_error,
        "generated_xml_sha256": generated_xml_sha,
        "native_frame0_bi4_sha256_before_partvtk": before,
        "native_frame0_bi4_sha256_after_partvtk": after,
        "gencase_raw_velocity_evidence": "not_used",
        "mass_rescaling": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    binding = load(args.binding)
    require(binding.get("source_only") is True and binding.get("execution_allowed") is False, "binding must remain disabled source-only")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = [audit(case, args.output_dir) for case in binding["cases"]]
    output = args.output_dir / "native-initial-height-audit.json"
    require(not output.exists(), "refusing to overwrite an existing QA receipt")
    output.write_text(json.dumps({
        "schema": "ds02.f1.fresh085.native-frame0-height-audit.v1",
        "source_only_worker": True,
        "cases": results,
        "native_frame0_source": "official PartVTK on solver-saved Part_0000.bi4",
        "gencase_raw_velocity_claim": "not_used",
        "q_n": "not_assessed",
        "production_approval": "none",
        "independent_case_count_increment": 0,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

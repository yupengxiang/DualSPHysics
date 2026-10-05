#!/usr/bin/env python3
"""Root-owned post-native frame-0 audit for F4 fresh097.

The source handoff only serializes this worker and disabled bindings.  Root may
run it after the matching full1201 native receipt is completed/0.  The worker
uses official PartVTK on the saved frame and observes raw Mk, Type and velocity
columns.  GenCase's declared velocity is recorded as provenance only and is
never used as evidence for the native velocity check.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected metadata object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(value: Any, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def finite(value: Any, label: str) -> float:
    number = float(str(value).strip())
    require(math.isfinite(number), f"non-finite {label}")
    return number


def index_of(header: list[str], names: tuple[str, ...]) -> int:
    stripped = [item.strip() for item in header]
    for name in names:
        if name in stripped:
            return stripped.index(name)
    raise RuntimeError(f"missing CSV column {names}")


def delimiter_for(path: Path) -> str:
    with path.open("r", newline="", encoding="utf-8") as stream:
        for _ in range(16):
            line = stream.readline()
            if not line:
                break
            if line.count(";") > line.count(","):
                return ";"
            if "," in line:
                return ","
    return ","


def read_rows(path: Path) -> list[list[str]]:
    with path.open("r", newline="", encoding="utf-8") as stream:
        return list(csv.reader(stream, delimiter=delimiter_for(path)))


def locate_particle_csv(csv_files: list[Path]) -> tuple[Path, list[list[str]], list[list[str]]]:
    particle: tuple[Path, list[list[str]], list[list[str]]] | None = None
    all_rows: list[tuple[Path, list[list[str]]]] = []
    for path in csv_files:
        rows = read_rows(path)
        all_rows.append((path, rows))
        if particle is None:
            for row in rows:
                if "Pos.x [m]" in [item.strip() for item in row]:
                    particle = (path, rows, [])
                    break
    require(particle is not None, "official PartVTK produced no particle CSV")
    particle_path, particle_rows, _ = particle
    summary_rows: list[list[str]] = []
    for _, rows in all_rows:
        summary_rows.extend(rows)
    return particle_path, particle_rows, summary_rows


def frame_summary(rows: list[list[str]], case_id: str) -> dict[str, Any]:
    found: tuple[int, dict[str, int], list[str]] | None = None
    for index, row in enumerate(rows):
        labels = {item.strip(): position for position, item in enumerate(row) if item.strip()}
        if all(name in labels for name in ("TimeStep [s]", "Np", "Nfluid")):
            found = (index, labels, row)
            break
    require(found is not None, f"{case_id}: official PartVTK summary header missing")
    index, labels, header = found
    data = next((row for row in rows[index + 1:] if any(item.strip() for item in row)), None)
    require(data is not None, f"{case_id}: official PartVTK summary row missing")
    time_s = finite(data[labels["TimeStep [s]"]], "TimeStep [s]")
    require(abs(time_s) <= 5e-5, f"{case_id}: first saved frame is not t=0")
    return {
        "time_s": time_s,
        "np": int(finite(data[labels["Np"]], "Np")),
        "nfluid": int(finite(data[labels["Nfluid"]], "Nfluid")),
        "header": header,
        "row": data,
    }


def audit(case: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    case_id = case["case_id"]
    receipt_path = Path(case["native_solver_receipt"])
    require(receipt_path.is_file(), f"{case_id}: native receipt missing")
    receipt = load(receipt_path)
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0,
            f"{case_id}: native receipt is not completed/0")

    report = load(Path(case["prepared_input_report"]))
    counts = report.get("generated_xml_particle_counts")
    require(isinstance(counts, dict), f"{case_id}: actual GenCase counts missing")
    total = int(report["actual_total_particles"])
    fluid_expected = int(counts["fluid"])
    fixed_expected = int(counts["fixed"])
    moving_expected = int(counts.get("moving", 0))
    floating_expected = int(counts.get("floating", 0))
    require(total == fixed_expected + moving_expected + floating_expected + fluid_expected,
            f"{case_id}: actual count sum mismatch")
    require(total == int(case["actual_total_particles"]), f"{case_id}: total binding mismatch")
    require(fluid_expected == int(case["actual_particle_counts"]["fluid"]),
            f"{case_id}: fluid binding mismatch")

    xml_path = Path(case["generated_xml"])
    xml_root = ET.parse(xml_path).getroot()
    data2d = xml_root.find("./execution/constants/data2d")
    require(data2d is not None and str(data2d.get("value", "")).lower() == "false",
            f"{case_id}: generated XML is not 3-D")
    generated_xml_sha = sha256_file(xml_path)
    require(generated_xml_sha == case["generated_xml_sha256"], f"{case_id}: XML SHA mismatch")

    data_dir = Path(case["native_data_dir"])
    frame = data_dir / "Part_0000.bi4"
    require(frame.is_file(), f"{case_id}: native Part_0000.bi4 missing")
    before = sha256_file(frame)
    prefix = output_dir / f"{case_id}-frame0"
    command = [
        case["partvtk"], "-dirdata", str(data_dir), "-first:0", "-last:0", "-threads:4",
        "-savecsv", str(prefix), "-onlytype:+all",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1",
    ]
    subprocess.run(command, cwd=output_dir, check=True)
    csv_files = sorted(prefix.parent.glob(f"{prefix.name}_*.csv"))
    require(csv_files, f"{case_id}: official PartVTK produced no CSV files")
    _, particle_rows, summary_rows = locate_particle_csv(csv_files)

    particle_header_index = next(
        (index for index, row in enumerate(particle_rows)
         if "Pos.x [m]" in [item.strip() for item in row]), None)
    require(particle_header_index is not None, f"{case_id}: particle header missing")
    header = particle_rows[particle_header_index]
    rows = [row for row in particle_rows[particle_header_index + 1:] if any(item.strip() for item in row)]
    positions = {
        key: index_of(header, names) for key, names in {
            "x": ("Pos.x [m]",), "y": ("Pos.y [m]",), "z": ("Pos.z [m]",),
            "id": ("Idp", "Idp [none]"), "zone": ("Zone", "Zone [none]"),
            "type": ("Type", "Type [none]"), "mk": ("Mk", "Mk [none]"),
            "mass": ("Mass [kg]", "Mass"), "rho": ("Rhop [kg/m^3]", "Rhop [kg/m3]", "Rhop"),
            "vx": ("Vel.x [m/s]",), "vy": ("Vel.y [m/s]",), "vz": ("Vel.z [m/s]",),
        }.items()
    }

    velocity_by_mk = {int(key.split(":", 1)[1]): tuple(float(item) for item in value)
                      for key, value in case["expected_velocity_by_mk"].items()}
    allowed_types = {int(value) for value in case["expected_native_types"]["fixed"] + case["expected_native_types"]["fluid"]}
    identities: set[tuple[int, int]] = set()
    coordinates: set[tuple[float, float, float]] = set()
    levels = [set(), set(), set()]
    type_counts: dict[str, int] = {}
    fluid_by_mk: dict[str, int] = {}
    finite_rows = 0
    fluid_rows = 0
    max_velocity_error = 0.0
    for row in rows:
        values = [finite(row[positions[key]], key) for key in
                  ("x", "y", "z", "mass", "rho", "vx", "vy", "vz")]
        type_value = int(finite(row[positions["type"]], "Type"))
        mk_value = int(finite(row[positions["mk"]], "Mk"))
        zone_value = int(finite(row[positions["zone"]], "Zone"))
        id_value = int(finite(row[positions["id"]], "Idp"))
        require(type_value in allowed_types, f"{case_id}: unexpected raw Type {type_value}")
        finite_rows += int(all(math.isfinite(value) for value in values))
        identities.add((zone_value, id_value))
        coordinates.add((values[0], values[1], values[2]))
        for axis, value in enumerate(values[:3]):
            levels[axis].add(value)
        type_counts[str(type_value)] = type_counts.get(str(type_value), 0) + 1
        if type_value in set(int(value) for value in case["expected_native_types"]["fluid"]):
            require(mk_value in velocity_by_mk, f"{case_id}: raw fluid Mk {mk_value} not in owner contract")
            fluid_rows += 1
            fluid_by_mk[str(mk_value)] = fluid_by_mk.get(str(mk_value), 0) + 1
            actual = values[5:8]
            expected = velocity_by_mk[mk_value]
            max_velocity_error = max(max_velocity_error, *(abs(a - b) for a, b in zip(actual, expected)))

    summary = frame_summary(summary_rows, case_id)
    require(summary["np"] > 0 and summary["np"] <= total,
            f"{case_id}: native frame-0 total is outside the actual GenCase upper bound")
    require(summary["nfluid"] > 0 and summary["nfluid"] <= fluid_expected,
            f"{case_id}: native frame-0 fluid count is outside the actual GenCase upper bound")
    require(len(rows) == summary["np"] and finite_rows == len(rows),
            f"{case_id}: native row/finite mismatch")
    require(fluid_rows == summary["nfluid"], f"{case_id}: native fluid summary mismatch")
    require(type_counts.get("0", 0) <= fixed_expected, f"{case_id}: native fixed count exceeds GenCase count")
    require(len(identities) == len(rows) and len(coordinates) == len(rows),
            f"{case_id}: duplicate native identity or coordinates")
    require(all(len(axis) > 1 for axis in levels), f"{case_id}: native output is not genuine 3-D")
    require(max_velocity_error <= float(case["velocity_tolerance_m_per_s"]),
            f"{case_id}: raw native frame-0 velocity mismatch")
    after = sha256_file(frame)
    require(after == before, f"{case_id}: PartVTK mutated native BI4")
    return {
        "case_id": case_id,
        "status": "completed_pass",
        "pass": True,
        "native_raw_mk_type_observed": True,
        "native_raw_velocity_observed": True,
        "gencase_declared_velocity_used_as_evidence": False,
        "actual_particle_counts": {"fixed": fixed_expected, "moving": moving_expected,
                                    "floating": floating_expected, "fluid": fluid_expected},
        "actual_total_particles": total,
        "native_rows": len(rows),
        "fluid_rows": fluid_rows,
        "frame0_count_lifecycle": {
            "gencase_total_particles": total,
            "gencase_fluid_particles": fluid_expected,
            "native_frame0_particles": summary["np"],
            "native_frame0_fluid_particles": summary["nfluid"],
            "delta_total_particles": summary["np"] - total,
            "delta_fluid_particles": summary["nfluid"] - fluid_expected,
            "observed_rows_preserved_without_padding": True,
        },
        "type_counts": type_counts,
        "fluid_rows_by_mk": fluid_by_mk,
        "finite_rows": finite_rows,
        "unique_identity_count": len(identities),
        "unique_coordinate_count": len(coordinates),
        "native_3d_levels": [len(axis) for axis in levels],
        "frame_summary": summary,
        "max_abs_velocity_error_m_per_s": max_velocity_error,
        "velocity_tolerance_m_per_s": float(case["velocity_tolerance_m_per_s"]),
        "generated_xml_sha256": generated_xml_sha,
        "native_frame0_bi4_sha256_before_partvtk": before,
        "native_frame0_bi4_sha256_after_partvtk": after,
        "mass_rescaling": False,
        "q_n": "not_assessed",
        "production_approval": "none",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    binding = load(args.binding)
    require(binding.get("source_only") is True and binding.get("execution_allowed") is False,
            "binding must remain a disabled source-only contract")
    require(binding.get("native_solver_status") == "completed/0",
            "native solver receipt must be completed/0 before frame-0 audit")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = [audit(case, args.output_dir) for case in binding["cases"]]
    output = args.output_dir / "native-frame0-partvtk-vz-audit.json"
    require(not output.exists(), "refusing to overwrite an existing audit report")
    output.write_text(json.dumps({
        "schema": "ds02.f4.fresh097.native-frame0-partvtk-vz-audit.v1",
        "source_only_worker": True,
        "native_frame0_source": "official PartVTK on solver-saved Part_0000.bi4",
        "raw_mk_type_observed": True,
        "raw_velocity_observed": True,
        "gencase_raw_velocity_claim": "not_used",
        "mass_rescaling": False,
        "cases": results,
        "q_n": "not_assessed",
        "production_approval": "none",
        "independent_case_count_increment": 0,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

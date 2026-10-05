#!/usr/bin/env python3
"""Root-registered native frame-0 identity and zero-velocity QA for F5.

The worker is serialized here but remains disabled in the source handoff.  A
Root-owned CPU registration may enable a matching request after review.  It
reads the solver-saved Part_0000.bi4 through the official PartVTK producer,
then checks the resulting native state.  It deliberately does not use the
GenCase particle CSV or its declared velocity as evidence for the native
saved state.
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

import numpy as np
import xml.etree.ElementTree as ET


SCHEMA = "ds02.f5.c082s1.native-frame0-zero-velocity-identity-binding.fresh106.v1"
RESULT_SCHEMA = "ds02.f5.c082s1.native-frame0-zero-velocity-identity-audit.fresh106.v1"
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
TYPE_FIXED, TYPE_MOVING, TYPE_FLOATING, TYPE_FLUID = 0, 1, 2, 3
ZERO_VELOCITY_TOLERANCE = 1.0e-8
SCIENCE_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".npy", ".npz", ".dat"}


def require(value: Any, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite_number(value: Any, message: str) -> float:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{message}: not numeric") from exc
    require(math.isfinite(result), f"{message}: non-finite")
    return result


def integral_column(values: np.ndarray, label: str) -> tuple[np.ndarray, bool]:
    rounded = np.rint(values)
    return rounded.astype(np.int64), bool(np.equal(values, rounded).all())


def locate_header(path: Path) -> tuple[list[str], int]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
        for line_number, row in enumerate(csv.reader(stream)):
            row = [item.strip() for item in row]
            if "Pos.x [m]" in row and "Pos.y [m]" in row and "Pos.z [m]" in row:
                return row, line_number
    raise RuntimeError(f"native particle CSV header missing: {path}")


def locate_particle_csv(files: list[Path]) -> tuple[Path, list[str], int]:
    for path in files:
        try:
            header, line_number = locate_header(path)
        except RuntimeError:
            continue
        needed = {"Zone", "Idp", "Type", "Mk", "Mass [kg]",
                  "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]",
                  "Rhop [kg/m^3]"}
        if needed.issubset(header):
            return path, header, line_number
    raise RuntimeError("official PartVTK produced no complete native particle CSV")


def read_summary(files: list[Path], case_id: str) -> dict[str, Any]:
    for path in files:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
            rows = list(csv.reader(stream))
        for line_number, row in enumerate(rows):
            labels = {item.strip(): index for index, item in enumerate(row) if item.strip()}
            if not {"TimeStep [s]", "Np", "Nfluid"}.issubset(labels):
                continue
            data = next((item for item in rows[line_number + 1:] if any(value.strip() for value in item)), None)
            require(data is not None, f"{case_id}: missing PartVTK frame summary row")
            time_s = finite_number(data[labels["TimeStep [s]"]], "PartVTK TimeStep [s]")
            require(abs(time_s) <= 5.0e-5, f"{case_id}: PartVTK first frame is not t=0")
            return {
                "time_s": time_s,
                "np": int(finite_number(data[labels["Np"]], "PartVTK Np")),
                "nfluid": int(finite_number(data[labels["Nfluid"]], "PartVTK Nfluid")),
                "source_file": str(path),
            }
    raise RuntimeError(f"{case_id}: PartVTK frame summary missing")


def csv_indices(header: list[str]) -> dict[str, int]:
    names = {
        "x": ("Pos.x [m]",),
        "y": ("Pos.y [m]",),
        "z": ("Pos.z [m]",),
        "zone": ("Zone",),
        "id": ("Idp", "Idp [none]"),
        "type": ("Type",),
        "mk": ("Mk",),
        "mass": ("Mass [kg]", "Mass"),
        "vx": ("Vel.x [m/s]",),
        "vy": ("Vel.y [m/s]",),
        "vz": ("Vel.z [m/s]",),
        "rho": ("Rhop [kg/m^3]",),
    }
    output: dict[str, int] = {}
    for key, candidates in names.items():
        for candidate in candidates:
            if candidate in header:
                output[key] = header.index(candidate)
                break
        require(key in output, f"native PartVTK field missing: {key}")
    return output


def read_particles(path: Path, header: list[str], header_line: int) -> np.ndarray:
    indices = csv_indices(header)
    ordered = [indices[key] for key in (
        "x", "y", "z", "zone", "id", "type", "mk", "mass", "vx", "vy", "vz", "rho"
    )]
    rows = np.loadtxt(
        path,
        delimiter=",",
        skiprows=header_line + 1,
        usecols=ordered,
        ndmin=2,
    )
    rows = np.asarray(rows, dtype=np.float64)
    require(rows.ndim == 2 and rows.shape[1] == len(ordered), f"native CSV shape is {rows.shape}")
    return rows


def xml_is_3d(path: Path) -> bool:
    root = ET.parse(path).getroot()
    data2d = root.find("./execution/constants/data2d")
    return bool(data2d is not None and str(data2d.get("value", "")).lower() == "false")


def audit_case(case: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    case_id = case["case_id"]
    require(case_id == CASE, f"{case_id}: case identity")
    binding = load_json(Path(case["binding_path"]))
    require(binding.get("schema") == SCHEMA, f"{case_id}: binding schema")
    require(binding.get("source_only") is True, f"{case_id}: binding must remain source-only")
    require(binding.get("execution_allowed") is False, f"{case_id}: binding must remain disabled")
    source_velocity = binding.get("source_defined_initial_velocity")
    require(isinstance(source_velocity, dict)
            and source_velocity.get("gencase_csv_velocity_not_substituted") is True,
            f"{case_id}: GenCase CSV velocity cannot substitute native frame-0 measurement")
    require(int(binding.get("native_bed_mk", -1)) == 50
            and int(binding.get("source_mkbound", -1)) == 40,
            f"{case_id}: source Mk-bound/native Mk50 mapping is missing")

    counts = binding.get("actual_particle_counts")
    require(isinstance(counts, dict), f"{case_id}: actual producer counts missing")
    expected_total = int(counts["total"])
    expected_fluid = int(counts["fluid"])
    expected_types = {
        TYPE_FIXED: int(counts["fixed"]),
        TYPE_MOVING: int(counts["moving"]),
        TYPE_FLOATING: int(counts["floating"]),
        TYPE_FLUID: expected_fluid,
    }

    files = binding.get("files")
    require(isinstance(files, dict), f"{case_id}: files binding missing")
    native_receipt_path = Path(files["native_receipt"]["path"])
    native_receipt = load_json(native_receipt_path)
    require(
        native_receipt.get("status") == "completed"
        and int(native_receipt.get("returncode", -1)) == 0,
        f"{case_id}: Root455 native receipt is not completed/0",
    )
    nested = native_receipt.get("request")
    require(isinstance(nested, dict), f"{case_id}: native receipt nested request missing")
    require(
        nested.get("attempt_id") == binding["native_attempt_id"]
        and nested.get("case_id") == CASE,
        f"{case_id}: native receipt identity mismatch",
    )
    require(sha256_file(native_receipt_path) == files["native_receipt"]["sha256"],
            f"{case_id}: native receipt SHA mismatch")
    require(
        nested.get("actual_counts") == {
            "dimension": 3,
            "fixed": expected_types[TYPE_FIXED],
            "floating": expected_types[TYPE_FLOATING],
            "fluid": expected_fluid,
            "moving": expected_types[TYPE_MOVING],
            "total": expected_total,
        },
        f"{case_id}: native receipt actual counts mismatch",
    )

    prepared = load_json(Path(files["prepared_input_report"]["path"]))
    generated = prepared.get("generated_xml_particle_counts")
    require(isinstance(generated, dict), f"{case_id}: GenCase count metadata missing")
    require(
        {key: int(generated.get(key, -1)) for key in ("fixed", "moving", "floating", "fluid")}
        == {key: expected_types[code] for code, key in (
            (TYPE_FIXED, "fixed"), (TYPE_MOVING, "moving"),
            (TYPE_FLOATING, "floating"), (TYPE_FLUID, "fluid")
        )},
        f"{case_id}: GenCase producer counts mismatch",
    )
    require(int(prepared.get("actual_total_particles", -1)) == expected_total,
            f"{case_id}: GenCase total mismatch")
    generated_xml = Path(files["generated_xml"]["path"])
    require(xml_is_3d(generated_xml), f"{case_id}: generated XML is not 3-D")
    require(sha256_file(generated_xml) == files["generated_xml"]["sha256"],
            f"{case_id}: generated XML SHA mismatch")

    frame = Path(files["native_frame0_bi4"]["path"])
    require(frame.name == "Part_0000.bi4", f"{case_id}: frame-0 binding must be Part_0000.bi4")
    require(frame.is_file(), f"{case_id}: solver-saved Part_0000.bi4 is missing")

    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / f"{case_id}-native-frame0"
    before = sha256_file(frame)
    command = [
        str(binding["partvtk"]),
        "-dirdata", str(frame.parent),
        "-first:0", "-last:0", "-threads:2",
        "-savecsv", str(prefix),
        "-onlytype:+all",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone",
        "-csvsep:1",
    ]
    subprocess.run(command, cwd=output_dir, check=True)
    csv_files = sorted(prefix.parent.glob(f"{prefix.name}_*.csv"))
    require(csv_files, f"{case_id}: PartVTK wrote no CSV")
    particle_csv, header, header_line = locate_particle_csv(csv_files)
    rows = read_particles(particle_csv, header, header_line)
    summary = read_summary(csv_files, case_id)

    require(rows.shape[0] == expected_total, f"{case_id}: native row count mismatch")
    require(summary["np"] == expected_total and summary["nfluid"] == expected_fluid,
            f"{case_id}: PartVTK summary count mismatch")
    finite_ok = bool(np.isfinite(rows).all())
    require(finite_ok, f"{case_id}: non-finite native frame-0 value")
    zone, zone_integral = integral_column(rows[:, 3], "Zone")
    ids, ids_integral = integral_column(rows[:, 4], "Idp")
    types, types_integral = integral_column(rows[:, 5], "Type")
    mks, mks_integral = integral_column(rows[:, 6], "Mk")
    require(zone_integral and ids_integral and types_integral and mks_integral,
            f"{case_id}: native identity/type/Mk fields are non-integral")
    require(bool(np.all(zone == 0)), f"{case_id}: native Zone is not zero")
    require(bool(np.array_equal(np.sort(ids), np.arange(expected_total))),
            f"{case_id}: native Idp is not unique/consecutive")
    observed_type_counts = {
        code: int(np.sum(types == code)) for code in sorted(set(expected_types))
    }
    require(observed_type_counts == expected_types,
            f"{case_id}: native Type counts differ from producer counts")
    require(bool(np.all(rows[:, 7] > 0.0)) and bool(np.all(rows[:, 11] > 0.0)),
            f"{case_id}: native mass/density is not positive")
    positions = rows[:, :3]
    require(np.unique(positions, axis=0).shape[0] == expected_total,
            f"{case_id}: duplicate native coordinates")
    levels = [np.unique(positions[:, axis]).size for axis in range(3)]
    require(all(level > 1 for level in levels), f"{case_id}: native state is not genuinely 3-D")

    groups = {code: {tuple(item) for item in positions[types == code]} for code in sorted(expected_types)}
    overlap = {}
    labels = {0: "fixed", 1: "moving", 2: "floating", 3: "fluid"}
    codes = sorted(groups)
    for left_index, left in enumerate(codes):
        for right in codes[left_index + 1:]:
            overlap[f"{labels[left]}_{labels[right]}"] = len(groups[left] & groups[right])
    require(not any(overlap.values()), f"{case_id}: native type spatial overlap")

    fluid = types == TYPE_FLUID
    require(int(fluid.sum()) == expected_fluid, f"{case_id}: native fluid Type count mismatch")
    fluid_velocity = rows[fluid, 8:11]
    max_fluid_velocity = float(np.max(np.abs(fluid_velocity))) if fluid_velocity.size else 0.0
    velocity_ok = max_fluid_velocity <= float(binding["source_defined_initial_velocity"]["tolerance_m_per_s"])
    require(velocity_ok, f"{case_id}: native fluid frame-0 velocity is not source-defined zero")
    fluid_mks = sorted({int(value) for value in mks[fluid]})
    after = sha256_file(frame)
    require(after == before, f"{case_id}: PartVTK mutated native Part_0000.bi4")

    return {
        "case_id": case_id,
        "candidate_id": binding["candidate_id"],
        "passed": True,
        "native_frame0_source": "official PartVTK export from solver-saved Part_0000.bi4",
        "gencase_velocity_evidence_used": False,
        "actual_particle_counts": counts,
        "native_rows": int(rows.shape[0]),
        "native_fluid_rows": int(fluid.sum()),
        "finite_native_values": int(np.isfinite(rows).sum()),
        "unique_uid_count": int(np.unique(ids).size),
        "type_counts": {str(code): observed_type_counts[code] for code in observed_type_counts},
        "mk_counts": {str(code): int(np.sum(mks == code)) for code in sorted(set(mks))},
        "fluid_mk_values": fluid_mks,
        "zone_values": sorted({int(value) for value in zone}),
        "unique_coordinate_count": int(np.unique(positions, axis=0).shape[0]),
        "coordinate_levels": levels,
        "spatial_overlap_counts": overlap,
        "source_defined_initial_fluid_velocity_m_per_s": binding["source_defined_initial_velocity"]["vector_m_per_s"],
        "native_fluid_frame0_max_abs_velocity_m_per_s": max_fluid_velocity,
        "native_fluid_zero_velocity_tolerance_m_per_s": binding["source_defined_initial_velocity"]["tolerance_m_per_s"],
        "native_fluid_zero_velocity_pass": velocity_ok,
        "partvtk_frame_summary": summary,
        "generated_xml_sha256": files["generated_xml"]["sha256"],
        "native_frame0_bi4_sha256_before_partvtk": before,
        "native_frame0_bi4_sha256_after_partvtk": after,
        "historical_exact_dp_lattice": binding["historical_exact_dp_lattice"],
        "dynamic_acceptance": "not assessed by this frame-0 identity QA",
        "q_n_granted": False,
        "full801_authorized": False,
        "production_approval": "none",
        "independent_case_count_increment": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    binding = load_json(args.binding)
    require(binding.get("source_only") is True and binding.get("execution_allowed") is False,
            "frame-0 QA binding must remain source-only and disabled")
    cases = binding.get("cases")
    require(isinstance(cases, list) and len(cases) == 1,
            "one disabled frame-0 QA request binds one native candidate")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = audit_case(cases[0], args.output_dir)
    output = args.output_dir / "native-frame0-zero-velocity-identity-audit.json"
    require(not output.exists(), "refusing to overwrite an existing native frame-0 QA report")
    output.write_text(json.dumps({
        "schema": RESULT_SCHEMA,
        "source_only_worker": True,
        "native_frame0_source": "official PartVTK on Root455 solver-saved Part_0000.bi4",
        "cases": [result],
        "source_velocity_is_declaration_only": True,
        "gencase_raw_velocity_claim": "not_used",
        "historical_exact_dp_lattice": {
            "threshold": 1.0e-6,
            "diagnostic_only": True,
            "accepted_as_stage1_gate": False,
            "status": "historical negative retained; this QA does not loosen or relabel it",
        },
        "q_n": "not_assessed",
        "production_approval": "none",
        "independent_case_count_increment": 0,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

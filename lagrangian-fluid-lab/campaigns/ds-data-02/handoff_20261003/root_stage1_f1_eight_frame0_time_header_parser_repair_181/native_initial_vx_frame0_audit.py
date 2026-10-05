#!/usr/bin/env python3
"""Audit solver-saved native frame 0 for the F1 uniform initial-Vx axis.

The source package never invokes this worker.  Root enables the disabled CPU
request only after the strict qualification solver has completed.  The worker
uses official PartVTK on the solver's ``data/Part_0000.bi4`` through the
``-dirdata`` interface and streams the isolated CSV; it never treats the
GenCase BI4 as velocity evidence.  The generated report therefore separates:

* source XML's declared ``<initials><velocity .../>``;
* GenCase geometry/count evidence (metadata only); and
* observed solver-saved native frame 0 fluid velocity.

The frame time comes only from the official PartVTK summary block.  The
summary header is identified by ``TimeStep [s]``, ``Np`` and ``Nfluid``; the
next non-empty row supplies the numeric time and counts.  Particle-column
headers are never treated as time evidence.

No Q-N, precision, visual or case-count decision is made here.
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
from typing import Any, Iterable


FIELDS = {
    "x": ("Pos.x [m]",),
    "y": ("Pos.y [m]",),
    "z": ("Pos.z [m]",),
    "zone": ("Zone",),
    "idp": ("Idp", "Idp [none]"),
    "type": ("Type",),
    "mk": ("Mk",),
    "mass": ("Mass [kg]", "Mass"),
    "vx": ("Vel.x [m/s]",),
    "vy": ("Vel.y [m/s]",),
    "vz": ("Vel.z [m/s]",),
    "rhop": ("Rhop [kg/m^3]",),
    "press": ("Press [Pa]",),
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON object required: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def column(header: list[str], aliases: Iterable[str], label: str) -> int:
    for alias in aliases:
        if alias in header:
            return header.index(alias)
    raise RuntimeError(f"missing PartVTK column {label}: {aliases}")


def number(raw: str, label: str) -> float:
    try:
        value = float(raw.strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid numeric {label}: {raw!r}") from exc
    require(math.isfinite(value), f"nonfinite numeric {label}")
    return value


def integer(raw: str, label: str) -> int:
    value = number(raw, label)
    rounded = int(value)
    require(value == rounded, f"nonintegral integer {label}: {raw!r}")
    return rounded


def direct_xml_velocity(path: Path, expected: tuple[float, float, float]) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    nodes = root.findall(".//initials/velocity")
    require(len(nodes) == 1, f"{path}: expected one direct initials velocity")
    node = nodes[0]
    require(node.get("mkfluid") == "0", f"{path}: mkfluid is not 0")
    actual = tuple(number(node.get(axis, "nan"), f"{path}:{axis}") for axis in ("x", "y", "z"))
    require(actual == expected, f"{path}: XML velocity {actual} != {expected}")
    return {"source_definition": str(path), "source_definition_sha256": sha(path), "velocity_m_per_s": list(actual), "fluid_mk": 0}


def generated_xml_3d(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    data2d = root.find("./execution/constants/data2d")
    require(data2d is not None and str(data2d.get("value", "")).lower() == "false", f"{path}: generated XML is not 3-D")
    return {"generated_xml": str(path), "generated_xml_sha256": sha(path), "data2d": data2d.get("value")}


def csv_candidate(prefix: Path) -> Path:
    candidates = sorted(path for path in prefix.parent.glob(prefix.name + "_*.csv") if not path.name.endswith("_stats.csv"))
    require(len(candidates) >= 1, f"PartVTK produced no CSV beside {prefix}")
    return candidates[0]


def frame_summary_evidence(summary: list[list[str]], case: dict[str, Any]) -> dict[str, Any]:
    """Read the official PartVTK frame summary before the particle header.

    PartVTK writes a metadata block before the particle columns, for example
    ``TimeStep [s],Np,...,Nfluid`` followed by one numeric row.  The former
    worker treated the first summary row as a time value; that row is the
    header and therefore produced ``nan``.  We require the named fields and
    parse the following non-empty row, so a missing or non-numeric time still
    fails the frame-0 gate.
    """
    required = {
        "time": "TimeStep [s]",
        "total": "Np",
        "fluid": "Nfluid",
    }
    header_index: int | None = None
    indices: dict[str, int] = {}
    header: list[str] = []
    for index, row in enumerate(summary):
        labels = {cell.strip(): position for position, cell in enumerate(row) if cell.strip()}
        if all(label in labels for label in required.values()):
            header_index = index
            indices = {key: labels[label] for key, label in required.items()}
            header = list(row)
            break
    require(header_index is not None, f"{case['case_id']}: official PartVTK TimeStep summary header is missing")

    data_row: list[str] | None = None
    for row in summary[header_index + 1 :]:
        if any(cell.strip() for cell in row):
            data_row = row
            break
    require(data_row is not None, f"{case['case_id']}: official PartVTK TimeStep summary data row is missing")
    require(max(indices.values()) < len(data_row), f"{case['case_id']}: short official PartVTK TimeStep summary row")

    time_s = number(data_row[indices["time"]], "PartVTK TimeStep [s]")
    total = integer(data_row[indices["total"]], "PartVTK Np")
    fluid = integer(data_row[indices["fluid"]], "PartVTK Nfluid")
    expected_total = int(case["expected_total"])
    expected_fluid = int(case["expected_fluid"])
    require(total == expected_total, f"{case['case_id']}: PartVTK Np {total} != {expected_total}")
    require(fluid == expected_fluid, f"{case['case_id']}: PartVTK Nfluid {fluid} != {expected_fluid}")
    return {
        "header": header,
        "header_index_before_particle_columns": header_index,
        "data_row": data_row,
        "time_s": time_s,
        "np": total,
        "nfluid": fluid,
        "expected_np": expected_total,
        "expected_nfluid": expected_fluid,
        "source": "official_partvtk_particle_csv_summary",
    }


def audit_csv(path: Path, case: dict[str, Any], output_dir: Path, command: list[str], raw_frame_sha256: str) -> dict[str, Any]:
    expected_total = int(case["expected_total"])
    expected_fluid = int(case["expected_fluid"])
    expected_v = tuple(float(value) for value in case["expected_velocity_m_per_s"])
    expected_types = {int(value) for value in case.get("expected_types", [0, 3])}
    header: list[str] | None = None
    summary: list[list[str]] = []
    rows = 0
    finite_rows = 0
    type_counts: Counter[str] = Counter()
    mk_counts: Counter[str] = Counter()
    ids: set[tuple[int, int]] = set()
    coords: set[tuple[float, float, float]] = set()
    fluid_x: set[float] = set()
    fluid_y: set[float] = set()
    fluid_z: set[float] = set()
    fluid_count = 0
    fluid_mk_counts: Counter[str] = Counter()
    max_fluid_v_error = 0.0
    fluid_velocity_min = [float("inf"), float("inf"), float("inf")]
    fluid_velocity_max = [float("-inf"), float("-inf"), float("-inf")]
    fluid_velocity_sum = [0.0, 0.0, 0.0]
    max_boundary_v_abs = 0.0
    positive_mass = 0
    positive_density = 0
    time_s = float("nan")

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for raw in reader:
            if header is None:
                if "Pos.x [m]" in raw:
                    header = raw
                else:
                    summary.append(raw)
                continue
            if not raw or not any(cell.strip() for cell in raw):
                continue
            indices = {key: column(header, aliases, key) for key, aliases in FIELDS.items()}
            require(len(raw) > max(indices.values()), f"{case['case_id']}: short CSV row")
            x = number(raw[indices["x"]], "x")
            y = number(raw[indices["y"]], "y")
            z = number(raw[indices["z"]], "z")
            zone = integer(raw[indices["zone"]], "zone")
            idp = integer(raw[indices["idp"]], "idp")
            typ = integer(raw[indices["type"]], "type")
            mk = integer(raw[indices["mk"]], "mk")
            mass = number(raw[indices["mass"]], "mass")
            vx = number(raw[indices["vx"]], "vx")
            vy = number(raw[indices["vy"]], "vy")
            vz = number(raw[indices["vz"]], "vz")
            rhop = number(raw[indices["rhop"]], "rhop")
            press = number(raw[indices["press"]], "press")
            values = (x, y, z, mass, vx, vy, vz, rhop, press)
            rows += 1
            finite_rows += int(all(math.isfinite(value) for value in values))
            type_counts[str(typ)] += 1
            mk_counts[str(mk)] += 1
            ids.add((zone, idp))
            coords.add((x, y, z))
            positive_mass += int(mass > 0.0)
            positive_density += int(rhop > 0.0)
            if typ == int(case.get("fluid_type", 3)) and mk == int(case.get("fluid_mk", 0)):
                fluid_count += 1
                fluid_mk_counts[str(mk)] += 1
                fluid_x.add(x)
                fluid_y.add(y)
                fluid_z.add(z)
                velocity = (vx, vy, vz)
                for axis, value in enumerate(velocity):
                    fluid_velocity_min[axis] = min(fluid_velocity_min[axis], value)
                    fluid_velocity_max[axis] = max(fluid_velocity_max[axis], value)
                    fluid_velocity_sum[axis] += value
                max_fluid_v_error = max(max_fluid_v_error, *(abs(actual - wanted) for actual, wanted in zip(velocity, expected_v)))
            else:
                max_boundary_v_abs = max(max_boundary_v_abs, abs(vx), abs(vy), abs(vz))

    require(header is not None, f"{case['case_id']}: official PartVTK particle header is missing")
    frame_summary = frame_summary_evidence(summary, case)
    time_s = float(frame_summary["time_s"])
    require(rows == expected_total, f"{case['case_id']}: rows {rows} != {expected_total}")
    require(finite_rows == rows, f"{case['case_id']}: nonfinite CSV row")
    require(fluid_count == expected_fluid, f"{case['case_id']}: fluid count {fluid_count} != {expected_fluid}")
    require(set(int(key) for key in type_counts) == expected_types, f"{case['case_id']}: unexpected native types {type_counts}")
    require(type_counts.get(str(case.get("fluid_type", 3)), 0) == expected_fluid, f"{case['case_id']}: Type 3 count mismatch")
    require(len(ids) == rows, f"{case['case_id']}: duplicate (Zone,Idp) identities")
    require(len(coords) == rows, f"{case['case_id']}: duplicate coordinates")
    require(positive_mass == rows and positive_density == rows, f"{case['case_id']}: nonpositive mass/density")
    require(len(fluid_x) > 1 and len(fluid_y) > 1 and len(fluid_z) > 1, f"{case['case_id']}: fluid is not 3-D")
    require(math.isfinite(time_s) and abs(time_s) <= float(case.get("frame_time_tolerance_s", 5.0e-5)), f"{case['case_id']}: frame time is not zero: {time_s!r}")
    require(max_fluid_v_error <= float(case.get("velocity_tolerance_m_s", 1.0e-6)), f"{case['case_id']}: native frame-0 Vx error {max_fluid_v_error}")
    observed_velocity_mean = [value / fluid_count for value in fluid_velocity_sum]
    require(max_boundary_v_abs <= float(case.get("boundary_velocity_tolerance_m_s", 1.0e-6)), f"{case['case_id']}: boundary frame-0 velocity {max_boundary_v_abs}")
    return {
        "case_id": case["case_id"],
        "passed": True,
        "official_csv": str(path),
        "official_csv_sha256": sha(path),
        "partvtk_command": command,
        "partvtk_summary_line_count": len(summary),
        "partvtk_frame_summary": frame_summary,
        "partvtk_frame_time_s": time_s,
        "native_particles": rows,
        "native_fluid_particles": fluid_count,
        "native_boundary_particles": rows - fluid_count,
        "native_type_counts": dict(sorted(type_counts.items())),
        "native_mk_counts": dict(sorted(mk_counts.items())),
        "native_fluid_mk_counts": dict(sorted(fluid_mk_counts.items())),
        "unique_identity_count": len(ids),
        "unique_coordinate_count": len(coords),
        "finite_row_count": finite_rows,
        "positive_mass_rows": positive_mass,
        "positive_density_rows": positive_density,
        "fluid_unique_coordinate_levels": {"x": len(fluid_x), "y": len(fluid_y), "z": len(fluid_z)},
        "expected_fluid_velocity_m_per_s": list(expected_v),
        "observed_fluid_velocity_mean_m_per_s": observed_velocity_mean,
        "observed_fluid_velocity_min_m_per_s": fluid_velocity_min,
        "observed_fluid_velocity_max_m_per_s": fluid_velocity_max,
        "max_abs_fluid_velocity_error_m_s": max_fluid_v_error,
        "max_abs_boundary_velocity_m_s": max_boundary_v_abs,
        "velocity_tolerance_m_s": float(case.get("velocity_tolerance_m_s", 1.0e-6)),
        "boundary_velocity_tolerance_m_s": float(case.get("boundary_velocity_tolerance_m_s", 1.0e-6)),
        "native_frame0_bi4_sha256_before_partvtk": raw_frame_sha256,
        "mass_semantics": "native PartVTK mass rows; no continuum rescale or CSV precision claim",
    }


def audit_case(case: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    solver_receipt = Path(case["native_solver_receipt"])
    require(solver_receipt.is_file(), f"{case['case_id']}: native solver receipt missing")
    receipt = load(solver_receipt)
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, f"{case['case_id']}: native receipt is not completed/0")
    data_dir = Path(case["native_data_dir"])
    frame = data_dir / "Part_0000.bi4"
    require(data_dir.is_dir() and frame.is_file(), f"{case['case_id']}: native frame 0 is missing")
    before = sha(frame)
    definition_evidence = direct_xml_velocity(Path(case["source_definition"]), tuple(float(value) for value in case["expected_velocity_m_per_s"]))
    generated_evidence = generated_xml_3d(Path(case["generated_xml"]))
    csv_prefix = output_dir / f"{case['case_id']}-frame0"
    command = [
        str(case["partvtk"]), "-dirdata", str(data_dir), "-first:0", "-last:0", "-threads:4",
        "-savecsv", str(csv_prefix), "-onlytype:+all",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1",
    ]
    subprocess.run(command, cwd=output_dir, check=True)
    csv_path = csv_candidate(csv_prefix)
    result = audit_csv(csv_path, case, output_dir, command, before)
    require(sha(frame) == before, f"{case['case_id']}: PartVTK changed native BI4")
    result.update({
        "source_definition_evidence": definition_evidence,
        "generated_xml_evidence": generated_evidence,
        "native_solver_receipt": str(solver_receipt),
        "native_solver_receipt_sha256": sha(solver_receipt),
        "native_frame0_bi4": str(frame),
        "native_frame0_bi4_sha256_after_partvtk": sha(frame),
        "gencase_raw_velocity_evidence": {
            "status": "not_used",
            "claim": "GenCase BI4/raw particle velocity is not used to prove the requested VX; only solver-saved native frame 0 is authoritative for this axis.",
            "gencase_receipt": case["gencase_receipt"],
            "gencase_receipt_sha256": case.get("gencase_receipt_sha256"),
        },
        "native_initial_velocity_evidence": {
            "status": "observed_from_solver_saved_frame0",
            "frame_index": 0,
            "time_s": result["partvtk_frame_time_s"],
            "requested_velocity_m_per_s": list(case["expected_velocity_m_per_s"]),
            "observed_uniform_fluid_velocity_mean_m_per_s": result["observed_fluid_velocity_mean_m_per_s"],
            "observed_uniform_fluid_velocity_min_m_per_s": result["observed_fluid_velocity_min_m_per_s"],
            "observed_uniform_fluid_velocity_max_m_per_s": result["observed_fluid_velocity_max_m_per_s"],
        },
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    binding = load(args.binding)
    require(binding.get("source_only") is True, "binding must remain source-only")
    require(binding.get("execution_allowed") is False, "binding unexpectedly enables execution")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = [audit_case(case, args.output_dir) for case in binding["cases"]]
    output = args.output_dir / "native-initial-vx-audit.json"
    require(not output.exists(), f"refusing to overwrite {output}")
    output.write_text(json.dumps({
        "schema": "ds02.f1.native-frame0-vx-audit.v1",
        "source_only_worker": True,
        "cases": results,
        "gencase_raw_velocity_claim": "not_used",
        "native_frame0_velocity_claim": "official PartVTK on solver-saved Part_0000.bi4",
        "q_n": "not_assessed",
        "production_approval": "none",
        "independent_case_count_increment": 0,
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

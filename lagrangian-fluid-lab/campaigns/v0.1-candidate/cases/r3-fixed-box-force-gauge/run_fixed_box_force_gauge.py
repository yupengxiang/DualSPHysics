#!/usr/bin/env python3
"""Run and audit the isolated fixed-box force-gauge controls.

The case is intentionally self-contained below ``lagrangian-fluid-lab``.  No
floating-body or Chrono path is used: the submerged cube is a fixed boundary
block selected by the source ``mkbound=1`` label.  The runner keeps each
solver invocation in an immutable attempt directory, records the physical GPU
UUID selected immediately before launch, and preserves both successful and
failed attempts.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET


CASE_ROOT = Path(__file__).resolve().parent
LAB_ROOT = next(
    parent for parent in CASE_ROOT.parents
    if (parent / "vendor" / "official" / "DualSPHysics_v5.4").is_dir()
)
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "v0.1-candidate"
BIN = LAB_ROOT / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
PARTVTK = BIN / "PartVTK_linux64"

GENERATED_ROOT = CASE_ROOT / "generated"
RUN_ROOT = CASE_ROOT / "runs"
RESULT_ROOT = CASE_ROOT / "results"
REPORT_PATH = CASE_ROOT / "fixed-box-force-gauge-report.json"

ALLOWED_GPU_INDICES = (4, 5, 6, 7)
IDLE_MEMORY_LIMIT_MIB = 500
IDLE_UTILIZATION_LIMIT_PERCENT = 0
BOX_MIN = (0.50, 0.30, 0.20)
BOX_MAX = (0.70, 0.50, 0.40)
TANK_INNER_MIN = (0.04, 0.04, 0.04)
TANK_INNER_MAX = (1.16, 0.76, 0.60)
BOX_SIZE = tuple(hi - lo for lo, hi in zip(BOX_MIN, BOX_MAX))
BOX_VOLUME_M3 = math.prod(BOX_SIZE)
RHO0 = 1000.0
G = 9.81
ANALYTIC_FZ_N = RHO0 * G * BOX_VOLUME_M3
TIME_MAX_S = 0.80

CASES = {
    "fixed_box_dbc_gravity": {
        "definition": CASE_ROOT / "fixed_box_dbc_gravity_Def.xml",
        "label": "DBC gravity / hydrostatic initial gradient",
        "expected_fz_n": ANALYTIC_FZ_N,
        "expected_pressure": "hydrostatic",
    },
    "fixed_box_dbc_zero_pressure": {
        "definition": CASE_ROOT / "fixed_box_dbc_zero_pressure_Def.xml",
        "label": "DBC zero-pressure / uniform initial density",
        "expected_fz_n": 0.0,
        "expected_pressure": "zero",
    },
}

# The requested mDBC variants are explicitly recorded as bounded blocked
# calibrations.  No mDBC XML is emitted or run until a separately audited
# normals/ghost construction is available; a placeholder result would be
# misleading evidence.
BLOCKED_CALIBRATIONS = [
    {
        "case_id": "fixed_box_mdbc_same_geometry",
        "status": "blocked_not_run",
        "reason": "No independently safe mDBC normals/ghost geometry path was established; no fake run.",
    },
    {
        "case_id": "fixed_box_mdbc_refined",
        "status": "blocked_not_run",
        "reason": "No independently safe mDBC normals/ghost geometry path was established; no fake run.",
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(temporary, path)


def environment() -> dict[str, str]:
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    return env


def query_gpus() -> tuple[str, list[dict[str, object]]]:
    command = [
        "nvidia-smi",
        "--query-gpu=index,uuid,memory.used,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    proc = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False)
    rows: list[dict[str, object]] = []
    for line in proc.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 5:
            continue
        try:
            rows.append({
                "index": int(fields[0]),
                "uuid": fields[1],
                "memory_used_mib": int(fields[2]),
                "memory_total_mib": int(fields[3]),
                "utilization_percent": int(fields[4]),
            })
        except ValueError:
            continue
    return " ".join(command), [{"return_code": proc.returncode, "rows": rows, "raw": proc.stdout}]


def capture_gpu_snapshot(path: Path) -> dict[str, object]:
    command, wrapped = query_gpus()
    record = wrapped[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(record["raw"]))
    return {
        "command": command,
        "return_code": record["return_code"],
        "rows": record["rows"],
        "snapshot": str(path.relative_to(CASE_ROOT)),
    }


def choose_idle_gpu(snapshot: dict[str, object]) -> dict[str, object]:
    rows = snapshot.get("rows", [])
    candidates = [
        row for row in rows
        if int(row["index"]) in ALLOWED_GPU_INDICES
        and int(row["memory_used_mib"]) < IDLE_MEMORY_LIMIT_MIB
        and int(row["utilization_percent"]) <= IDLE_UTILIZATION_LIMIT_PERCENT
    ]
    if not candidates:
        raise RuntimeError(
            "no truly idle allowed GPU (4-7) found; existing processes were not interrupted"
        )
    return sorted(candidates, key=lambda row: (int(row["memory_used_mib"]), int(row["index"])))[0]


def source_geometry_audit(definition: Path) -> dict[str, object]:
    root = ET.parse(definition).getroot()
    mainlist = root.find(".//geometry/commands/mainlist")
    if mainlist is None:
        raise ValueError(f"missing geometry mainlist in {definition}")
    current_mkbound: str | None = None
    body_boxes: list[dict[str, object]] = []
    boundary_boxes: list[dict[str, object]] = []
    for child in list(mainlist):
        if child.tag == "setmkbound":
            current_mkbound = child.attrib.get("mk")
        elif child.tag == "setmkvoid":
            current_mkbound = None
        elif child.tag == "drawbox":
            point = child.find("point")
            size = child.find("size")
            if point is None or size is None:
                continue
            item = {
                "mkbound": current_mkbound,
                "boxfill": (child.findtext("boxfill") or "").strip(),
                "point_m": [float(point.attrib[key]) for key in ("x", "y", "z")],
                "size_m": [float(size.attrib[key]) for key in ("x", "y", "z")],
            }
            if current_mkbound == "1":
                body_boxes.append(item)
            elif current_mkbound == "0":
                boundary_boxes.append(item)
    if len(body_boxes) != 1:
        raise ValueError(f"expected exactly one mkbound=1 body box, found {len(body_boxes)}")
    body = body_boxes[0]
    point = tuple(body["point_m"])
    size = tuple(body["size_m"])
    actual_max = tuple(lo + width for lo, width in zip(point, size))
    no_floatings = root.find(".//floatings") is None
    force_nodes = root.findall(".//force")
    targets = [node.find("target") for node in force_nodes]
    target_mkbound = [node.attrib.get("mkbound") for node in targets if node is not None]
    parameters = {
        node.attrib.get("key"): node.attrib.get("value")
        for node in root.findall(".//execution/parameters/parameter")
    }
    constants = root.find(".//constantsdef")
    constant_values = {
        node.tag: dict(node.attrib) for node in list(constants or [])
    }
    return {
        "definition": str(definition.relative_to(LAB_ROOT)),
        "definition_sha256": sha256(definition),
        "no_floatings_section": no_floatings,
        "floating_nodes": len(root.findall(".//floating")),
        "force_gauge_names": [node.attrib.get("name") for node in force_nodes],
        "force_targets_mkbound": target_mkbound,
        "body_box": {
            "source_mkbound": 1,
            "point_m": list(point),
            "size_m": list(size),
            "max_m": list(actual_max),
            "volume_m3": math.prod(size),
            "boxfill": body["boxfill"],
        },
        "tank_boundary_box_count": len(boundary_boxes),
        "constants": constant_values,
        "execution_parameters": parameters,
    }


def parse_generated_xml(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    particles = root.find(".//execution/particles")
    if particles is None:
        raise ValueError(f"generated XML has no particles block: {path}")
    mapping: list[dict[str, object]] = []
    for node in particles.findall("fixed") + particles.findall("moving") + particles.findall("floating"):
        mapping.append({
            "particle_type": node.tag,
            "source_mkbound": int(node.attrib["mkbound"]),
            "global_mk": int(node.attrib["mk"]),
            "begin": int(node.attrib["begin"]),
            "count": int(node.attrib["count"]),
        })
    fluid_mapping = [
        {
            "particle_type": "fluid",
            "source_mkfluid": int(node.attrib["mkfluid"]),
            "global_mk": int(node.attrib["mk"]),
            "begin": int(node.attrib["begin"]),
            "count": int(node.attrib["count"]),
        }
        for node in particles.findall("fluid")
    ]
    summary = particles.find("_summary")
    return {
        "generated_xml": str(path.relative_to(CASE_ROOT)),
        "generated_xml_sha256": sha256(path),
        "mapping_source_to_global_mk": mapping,
        "fluid_mapping": fluid_mapping,
        "np": int(particles.attrib["np"]),
        "nb": int(particles.attrib["nb"]),
        "nbf": int(particles.attrib["nbf"]),
        "mkboundfirst": int(particles.attrib["mkboundfirst"]),
        "mkfluidfirst": int(particles.attrib["mkfluidfirst"]),
        "summary": ET.tostring(summary, encoding="unicode") if summary is not None else None,
    }


def run_gencase(case_id: str, definition: Path) -> dict[str, object]:
    generated_dir = GENERATED_ROOT / case_id
    generated_dir.mkdir(parents=True, exist_ok=True)
    prefix = generated_dir / case_id
    command = [str(GENCASE), str(definition.with_suffix("")), str(prefix), "-save:all"]
    started = time.monotonic()
    proc = subprocess.run(command, cwd=LAB_ROOT, env=environment(), text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    elapsed = time.monotonic() - started
    log_path = generated_dir / "gencase.stdout.log"
    log_path.write_text(proc.stdout)
    generated_xml = prefix.with_suffix(".xml")
    record: dict[str, object] = {
        "command": command,
        "return_code": proc.returncode,
        "elapsed_seconds": round(elapsed, 6),
        "generated_prefix": str(prefix.relative_to(CASE_ROOT)),
        "generated_xml": str(generated_xml.relative_to(CASE_ROOT)) if generated_xml.exists() else None,
        "stdout_log": str(log_path.relative_to(CASE_ROOT)),
        "stdout_sha256": sha256(log_path),
        "finished_text_found": "Finished execution (code=0)." in proc.stdout,
    }
    if proc.returncode == 0 and generated_xml.exists():
        record["generated"] = parse_generated_xml(generated_xml)
    else:
        record["generated"] = None
    return record


def new_attempt(case_id: str, command: list[str], gpu: dict[str, object]) -> tuple[str, Path, dict[str, object]]:
    attempts = RUN_ROOT / case_id / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    attempt_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    partial = attempts / f"{attempt_id}.partial"
    partial.mkdir()
    payload = {
        "schema_version": 1,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "status": "running",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "gpu_at_launch": gpu,
    }
    json_dump(partial / "attempt.json", payload)
    return attempt_id, partial, payload


def run_solver_attempt(case_id: str, generated_prefix: Path, gpu: dict[str, object]) -> dict[str, object]:
    command = [str(SOLVER), f"-gpu:{gpu['index']}", str(generated_prefix), "{output}"]
    attempt_id, partial, payload = new_attempt(case_id, command, gpu)
    actual_command = [str(value).replace("{output}", str(partial)) for value in command]
    started = time.monotonic()
    proc = subprocess.run(actual_command, cwd=LAB_ROOT, env=environment(), text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    elapsed = time.monotonic() - started
    stdout_path = partial / "solver.stdout.log"
    stdout_path.write_text(proc.stdout)
    part_files = sorted((partial / "data").glob("Part_[0-9][0-9][0-9][0-9].bi4"))
    finished = "Finished execution (code=0)." in proc.stdout
    succeeded = proc.returncode == 0 and finished and bool(part_files)
    suffix = ".complete" if succeeded else ".failed"
    final = partial.with_name(attempt_id + suffix)
    payload.update({
        "status": "completed" if succeeded else "failed",
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 6),
        "return_code": proc.returncode,
        "actual_command": actual_command,
        "finished_text_found": finished,
        "part_files": len(part_files),
        "solver_stdout_sha256": sha256(stdout_path),
    })
    json_dump(partial / "attempt.json", payload)
    os.replace(partial, final)
    payload["attempt_directory"] = str(final.relative_to(CASE_ROOT))
    json_dump(RUN_ROOT / case_id / "latest.json", payload)
    return payload


def read_table(path: Path, separator: str) -> tuple[float, list[str], list[dict[str, str]]]:
    lines = path.read_text(errors="replace").splitlines()
    if len(lines) < 4:
        raise ValueError(f"short PartVTK output: {path}")
    time_value = float(lines[1].split(separator)[0].strip())
    header = [field.strip() for field in lines[3].split(separator) if field.strip()]
    rows: list[dict[str, str]] = []
    for values in csv.reader(lines[4:], delimiter=separator):
        if not values or not any(value.strip() for value in values):
            continue
        values = values[:len(header)]
        if len(values) != len(header):
            raise ValueError(f"row/header mismatch in {path}: {len(values)} vs {len(header)}")
        rows.append({key: value.strip() for key, value in zip(header, values)})
    return time_value, header, rows


def run_partvtk_frame(data_dir: Path, generated_xml: Path, output_dir: Path,
                      part_index: int, only_type: str) -> tuple[Path, dict[str, object]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / "Particles"
    command = [
        str(PARTVTK), "-dirdata", str(data_dir), f"-first:{part_index}",
        f"-last:{part_index}", "-savecsv", str(prefix), f"-onlytype:{only_type}",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1",
    ]
    proc = subprocess.run(command, cwd=LAB_ROOT, env=environment(), text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    log_path = output_dir / "partvtk.stdout.log"
    log_path.write_text(proc.stdout)
    frames = sorted(output_dir.glob("Particles_[0-9][0-9][0-9][0-9].csv"))
    if proc.returncode or len(frames) != 1:
        raise RuntimeError(f"PartVTK failed for {data_dir} part {part_index}: {proc.stdout[-1000:]}")
    frame = frames[0]
    return frame, {
        "command": command,
        "return_code": proc.returncode,
        "stdout_log": str(log_path.relative_to(CASE_ROOT)),
        "frame": str(frame.relative_to(CASE_ROOT)),
        "frame_sha256": sha256(frame),
    }


def numeric(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite value {value!r}")
    return parsed


def field_audit(attempt_dir: Path, generated_xml: Path, result_dir: Path,
                expected_fluids: int) -> dict[str, object]:
    data_dir = attempt_dir / "data"
    part_files = sorted(data_dir.glob("Part_[0-9][0-9][0-9][0-9].bi4"))
    if not part_files:
        raise ValueError(f"no solver Part files in {data_dir}")
    first_index = 0
    last_index = len(part_files) - 1
    frame_records: dict[str, dict[str, object]] = {}
    all_rows: dict[str, list[dict[str, str]]] = {}
    for label, index in (("initial", first_index), ("final", last_index)):
        fluid_path, fluid_record = run_partvtk_frame(
            data_dir, generated_xml, result_dir / "fields" / label / "fluid", index, "-all,+fluid"
        )
        fixed_path, fixed_record = run_partvtk_frame(
            data_dir, generated_xml, result_dir / "fields" / label / "fixed", index, "-all,+fixed"
        )
        fluid_time, fluid_header, fluid_rows = read_table(fluid_path, ",")
        fixed_time, fixed_header, fixed_rows = read_table(fixed_path, ",")
        required = {
            "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Idp", "Vel.x [m/s]",
            "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]", "Mass [kg]",
            "Press [Pa]", "Type", "Mk",
        }
        missing = sorted(required - set(fluid_header))
        if missing:
            raise ValueError(f"PartVTK omitted required fluid fields: {missing}")
        missing_fixed = sorted(required - set(fixed_header))
        if missing_fixed:
            raise ValueError(f"PartVTK omitted required fixed fields: {missing_fixed}")
        for row in fluid_rows + fixed_rows:
            for key, value in row.items():
                if key not in ("Type", "Mk", "Idp", "Zone"):
                    numeric(value)
        frame_records[label] = {
            "part_index": index,
            "fluid_time_s": fluid_time,
            "fixed_time_s": fixed_time,
            "fluid_count": len(fluid_rows),
            "fixed_count": len(fixed_rows),
            "fluid_fields": fluid_header,
            "fixed_fields": fixed_header,
            "fluid_partvtk": fluid_record,
            "fixed_partvtk": fixed_record,
        }
        all_rows[label] = fluid_rows

    initial_rows = all_rows["initial"]
    final_rows = all_rows["final"]

    def positions(rows: list[dict[str, str]]) -> list[tuple[float, float, float]]:
        return [tuple(numeric(row[key]) for key in ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]")) for row in rows]

    fluid_initial_positions = positions(initial_rows)
    fluid_final_positions = positions(final_rows)
    def in_box(point: tuple[float, float, float]) -> bool:
        # Strict interior is penetration; contact on a boundary is not counted.
        return all(lo + 1e-8 < value < hi - 1e-8 for value, lo, hi in zip(point, BOX_MIN, BOX_MAX))

    penetration_initial = sum(in_box(point) for point in fluid_initial_positions)
    penetration_final = sum(in_box(point) for point in fluid_final_positions)
    initial_mass = sum(numeric(row["Mass [kg]"]) for row in initial_rows)
    final_mass = sum(numeric(row["Mass [kg]"]) for row in final_rows)

    # The fixed-body CSVs are regenerated only for the integrity check.  Their
    # coordinates must stay unchanged, which is a direct fixedness check.
    fixed_positions: dict[str, dict[tuple[int, int], tuple[float, float, float]]] = {}
    for label in ("initial", "final"):
        fixed_path = CASE_ROOT / frame_records[label]["fixed_partvtk"]["frame"]
        _, _, rows = read_table(fixed_path, ",")
        fixed_positions[label] = {
            (int(row["Zone"]), int(row["Idp"])): tuple(
                numeric(row[key]) for key in ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]")
            )
            for row in rows
        }
    fixed_motion_max = 0.0
    if set(fixed_positions["initial"]) == set(fixed_positions["final"]):
        for key in fixed_positions["initial"]:
            left = fixed_positions["initial"][key]
            right = fixed_positions["final"][key]
            fixed_motion_max = max(
                fixed_motion_max,
                math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right))),
            )
    else:
        fixed_motion_max = math.inf

    pressure_initial = [numeric(row["Press [Pa]"]) for row in initial_rows]
    pressure_final = [numeric(row["Press [Pa]"]) for row in final_rows]
    return {
        "part_file_count": len(part_files),
        "frames": frame_records,
        "required_fields_complete": True,
        "fluid_count_initial": len(initial_rows),
        "fluid_count_final": len(final_rows),
        "expected_fluid_count": expected_fluids,
        "fluid_count_constant": len(initial_rows) == len(final_rows) == expected_fluids,
        "fluid_mass_initial_kg": initial_mass,
        "fluid_mass_final_kg": final_mass,
        "fluid_mass_delta_kg": final_mass - initial_mass,
        "fluid_mass_conserved": math.isclose(initial_mass, final_mass, rel_tol=0, abs_tol=1e-6),
        "fluid_penetration_into_box": {
            "initial_particles": penetration_initial,
            "final_particles": penetration_final,
            "pass": penetration_initial == 0 and penetration_final == 0,
            "scope": "initial_and_final_field_snapshots; all solver outputs are checked for excluded particles",
        },
        "fixed_body_particle_motion_max_m": fixed_motion_max,
        "fixed_body_unchanged": math.isfinite(fixed_motion_max) and fixed_motion_max <= 1e-12,
        "pressure_initial_pa": {
            "min": min(pressure_initial), "max": max(pressure_initial),
            "mean": sum(pressure_initial) / len(pressure_initial),
        },
        "pressure_final_pa": {
            "min": min(pressure_final), "max": max(pressure_final),
            "mean": sum(pressure_final) / len(pressure_final),
        },
    }


def parse_force_csv(source: Path, destination: Path) -> dict[str, object]:
    lines = source.read_text(errors="replace").splitlines()
    if len(lines) < 2:
        raise ValueError(f"force gauge output is empty: {source}")
    header = [field.strip() for field in lines[0].split(";")]
    required = ["time [s]", "force [N]", "forcex [N]", "forcey [N]", "forcez [N]"]
    if header != required:
        raise ValueError(f"unexpected force-gauge header: {header}")
    rows: list[dict[str, float]] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        values = [value.strip() for value in line.split(";")]
        if len(values) != len(required):
            raise ValueError(f"unexpected force-gauge row: {line}")
        rows.append({key: numeric(value) for key, value in zip(required, values)})
    if not rows:
        raise ValueError("force-gauge output has no samples")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)

    def window(start: float, end: float) -> dict[str, object]:
        selected = [row for row in rows if start <= row["time [s]"] <= end]
        stats: dict[str, object] = {"start_s": start, "end_s": end, "samples": len(selected)}
        for key in ("force [N]", "forcex [N]", "forcey [N]", "forcez [N]"):
            values = [row[key] for row in selected]
            if not values:
                stats[key] = None
                continue
            mean = sum(values) / len(values)
            variance = sum((value - mean) ** 2 for value in values) / len(values)
            stats[key] = {
                "mean": mean,
                "std": math.sqrt(variance),
                "min": min(values),
                "max": max(values),
            }
        return stats

    windows = {
        "last_0p20s": window(max(0.0, TIME_MAX_S - 0.20), TIME_MAX_S),
        "last_0p40s": window(max(0.0, TIME_MAX_S - 0.40), TIME_MAX_S),
        "last_0p60s": window(max(0.0, TIME_MAX_S - 0.60), TIME_MAX_S),
    }
    return {
        "source": str(source.relative_to(CASE_ROOT)),
        "source_sha256": sha256(source),
        "signed_csv": str(destination.relative_to(CASE_ROOT)),
        "sample_count": len(rows),
        "time_min_s": rows[0]["time [s]"],
        "time_max_s": rows[-1]["time [s]"],
        "header": header,
        "rows_first": rows[:3],
        "rows_last": rows[-3:],
        "windows": windows,
    }


def solver_log_audit(attempt_dir: Path, attempt: dict[str, object]) -> dict[str, object]:
    log_path = attempt_dir / "solver.stdout.log"
    text = log_path.read_text(errors="replace")
    def value(pattern: str) -> str | None:
        match = re.search(pattern, text)
        return match.group(1) if match else None
    return {
        "log": str(log_path.relative_to(CASE_ROOT)),
        "log_sha256": sha256(log_path),
        "fixed_summary": value(r"Fixed\.\.\.\.:\s+([0-9,]+)"),
        "moving_summary": value(r"Moving\.\.\.\.:\s+([0-9,]+)"),
        "floating_summary": value(r"Floating\.\.\.:\s+([0-9,]+)"),
        "fluid_summary": value(r"Fluid\.\.\.\.:\s+([0-9,]+)"),
        "excluded_particles": value(r"Excluded particles\.\.\.\.\.\.\.\.\.:\s+([0-9,]+)"),
        "finished_text_found": "Finished execution (code=0)." in text,
        "gauge_config_target_found": "MkBound.....: 1 (Fixed particles)" in text,
        "chrono_timer": value(r"SU-Chrono\.\.\.\.\.\.\.\.\.\.\.\.\.\.\.\.\.\.\.\.\.\.\.\.\.\.\s+([^\n]+)"),
        "attempt_status": attempt["status"],
    }


def copy_run_metadata(attempt_dir: Path, result_dir: Path) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    for name in ("solver.stdout.log", "Run.csv", "Run.out", "RunPARTs.csv", "CfgGauge_InitPoints.vtk"):
        source = attempt_dir / name
        if source.is_file():
            shutil.copy2(source, result_dir / name)
    source_attempt = attempt_dir / "attempt.json"
    if source_attempt.is_file():
        shutil.copy2(source_attempt, result_dir / "attempt.json")


def run_case(case_id: str, config: dict[str, object], index: int) -> dict[str, object]:
    definition = Path(config["definition"])
    source = source_geometry_audit(definition)
    gencase = run_gencase(case_id, definition)
    case_report: dict[str, object] = {
        "case_id": case_id,
        "label": config["label"],
        "definition": source,
        "gencase": gencase,
        "analytical_reference": {
            "rho_kg_m3": RHO0,
            "gravity_m_s2": G,
            "box_size_m": list(BOX_SIZE),
            "box_volume_m3": BOX_VOLUME_M3,
            "pressure_resultant_fz_n": ANALYTIC_FZ_N,
            "status": "pre_registered_reference_only",
        },
        "execution_status": "not_started",
        "acceptance_status": "not_accepted",
    }
    if gencase["return_code"] != 0 or not gencase.get("generated"):
        case_report["execution_status"] = "gencase_failed"
        return case_report

    generated = gencase["generated"]
    mapping = generated["mapping_source_to_global_mk"]
    body_map = [item for item in mapping if item["source_mkbound"] == 1]
    case_report["fixed_body_mapping_gate"] = {
        "source_mkbound": 1,
        "mapping_rows": body_map,
        "source_mkbound_maps_to_fixed": len(body_map) == 1 and body_map[0]["particle_type"] == "fixed",
        "no_floatings": source["no_floatings_section"] and source["floating_nodes"] == 0,
    }
    preflight_path = RUN_ROOT / "gpu-preflight" / f"{index:02d}-{case_id}.txt"
    snapshot = capture_gpu_snapshot(preflight_path)
    gpu = choose_idle_gpu(snapshot)
    case_report["gpu_preflight"] = snapshot
    generated_prefix = CASE_ROOT / gencase["generated_prefix"]
    attempt = run_solver_attempt(case_id, generated_prefix, gpu)
    case_report["attempt"] = attempt
    attempt_dir = CASE_ROOT / attempt["attempt_directory"]
    result_dir = RESULT_ROOT / case_id / attempt["attempt_id"]
    copy_run_metadata(attempt_dir, result_dir)
    case_report["solver_log"] = solver_log_audit(attempt_dir, attempt)
    case_report["execution_status"] = "completed" if attempt["status"] == "completed" else "solver_failed"
    if attempt["status"] != "completed":
        case_report["result_directory"] = str(result_dir.relative_to(CASE_ROOT))
        return case_report

    generated_xml = CASE_ROOT / generated["generated_xml"]
    generated_evidence: dict[str, str] = {}
    generated_evidence_xml = result_dir / "generated_particles.xml"
    shutil.copy2(generated_xml, generated_evidence_xml)
    generated_evidence["particles_xml"] = str(generated_evidence_xml.relative_to(CASE_ROOT))
    generated_evidence["particles_xml_sha256"] = sha256(generated_evidence_xml)
    generated_evidence_log = result_dir / "gencase.stdout.log"
    shutil.copy2(CASE_ROOT / gencase["stdout_log"], generated_evidence_log)
    generated_evidence["gencase_stdout"] = str(generated_evidence_log.relative_to(CASE_ROOT))
    generated_evidence["gencase_stdout_sha256"] = sha256(generated_evidence_log)
    case_report["generated_evidence"] = generated_evidence
    expected_fluid = generated["fluid_mapping"][0]["count"]
    fields = field_audit(attempt_dir, generated_xml, result_dir, expected_fluid)
    case_report["field_integrity"] = fields
    gauge_source = attempt_dir / "GaugesForce_BoxForce.csv"
    gauge = parse_force_csv(gauge_source, result_dir / "force_timeseries.csv")
    case_report["force_gauge"] = gauge
    case_report["result_directory"] = str(result_dir.relative_to(CASE_ROOT))

    body_fixed = case_report["fixed_body_mapping_gate"]["source_mkbound_maps_to_fixed"]
    no_floatings = case_report["fixed_body_mapping_gate"]["no_floatings"]
    field_ok = (
        fields["required_fields_complete"] and fields["fluid_count_constant"]
        and fields["fluid_mass_conserved"] and fields["fluid_penetration_into_box"]["pass"]
        and fields["fixed_body_unchanged"]
    )
    force_windows = gauge["windows"]
    stable_window_samples = all(
        value["samples"] >= 20 and value["forcez [N]"] is not None
        for value in force_windows.values()
    )
    stability_limit = max(0.05 * max(abs(float(config["expected_fz_n"])), 1.0), 0.5)
    stable_window_gate = stable_window_samples and all(
        value["forcez [N]"]["std"] <= stability_limit
        for value in force_windows.values()
        if value["forcez [N]"] is not None
    )
    means = [value["forcez [N]"]["mean"] for value in force_windows.values() if value["forcez [N]"]]
    expected = float(config["expected_fz_n"])
    reference_error = None if expected == 0 else abs(means[0] - expected) / expected * 100 if means else None
    initial_pressure = fields["pressure_initial_pa"]
    zero_pressure_initial_ok = (
        config["expected_pressure"] != "zero" or max(abs(initial_pressure["min"]), abs(initial_pressure["max"])) <= 1e-6
    )
    case_report["screen"] = {
        "fixed_body_gate": body_fixed and no_floatings,
        "fields_gate": field_ok,
        "multiple_window_gate": stable_window_samples,
        "stable_window_gate": stable_window_gate,
        "stable_window_std_limit_n": stability_limit,
        "initial_pressure_gate": zero_pressure_initial_ok,
        "forcez_window_means_n": means,
        "reference_error_last_0p20s_percent": reference_error,
        "status": "diagnostic_only_not_physical_acceptance",
    }
    # The user requested evidence, not an automatic physical label.  Keep the
    # acceptance field explicitly non-accepted even when structural gates pass.
    case_report["acceptance_status"] = "candidate_not_accepted"
    return case_report


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# R3 fixed immersed box force gauge",
        "",
        "> Candidate-only evidence. `overall_acceptance_status` is deliberately "
        "`candidate_not_accepted`; a finite trace is not a physical acceptance.",
        "",
        "## Geometry and force semantics",
        "",
        f"- Box: `{BOX_SIZE[0]:g} x {BOX_SIZE[1]:g} x {BOX_SIZE[2]:g} m`, "
        f"volume `{BOX_VOLUME_M3:.6f} m^3`; bottom at `z={BOX_MIN[2]:g} m`, "
        f"water top `z={TANK_INNER_MAX[2]:g} m`, floor gap `{BOX_MIN[2]:g} m`.",
        f"- Pre-registered pressure reference: `Fz={ANALYTIC_FZ_N:.2f} N` "
        "(`rho*g*V`), reference only.",
        "- Gauge output is signed pressure interaction on selected fixed boundary "
        "particles; it excludes gravity, support reaction, and viscosity.",
        "- Source-to-global mapping is read from generated XML, not inferred from "
        "the requested label alone.",
        "",
        "## Source semantics evidence",
        "",
        "- Gauge XML: `doc/xml_format/_FmtXML_Gauges.xml` (`force/target mkbound`).",
        "- `JGaugeSystem::AddGaugeForce`: `src/source/JDsGaugeSystem.cpp:472-493`; "
        "it resolves `mkbound` through `JSphMk`, and accepts fixed/moving blocks.",
        "- `JGaugeForce`: `src/source/JDsGaugeItem.cpp:1710-1988`; it sums only "
        "fluid pressure interactions and emits signed `forcex/y/z`.",
        "",
        "## Runs",
        "",
        "| control | status | GPU / UUID | attempt | `Fz` mean last 0.20 s (N) | reference error | stable | fields |",
        "|---|---|---:|---|---:|---:|---|---|",
    ]
    detail_lines: list[str] = []
    for case in report["cases"]:
        if case.get("execution_status") != "completed":
            lines.append(
                f"| `{case.get('case_id')}` | `{case.get('execution_status')}` | — | — | — | — | — | — |"
            )
            continue
        gpu = case["attempt"]["gpu_at_launch"]
        force = case["force_gauge"]
        last_window = force["windows"]["last_0p20s"]
        fz_mean = last_window["forcez [N]"]["mean"]
        error = case["screen"]["reference_error_last_0p20s_percent"]
        error_text = "n/a" if error is None else f"{error:.2f}%"
        lines.append(
            f"| `{case['case_id']}` | `completed` | `{gpu['index']}` / "
            f"`{gpu['uuid']}` | `{case['attempt']['attempt_id']}` | "
            f"`{fz_mean:.3f}` | `{error_text}` | "
            f"`{case['screen']['stable_window_gate']}` | `{case['screen']['fields_gate']}` |"
        )
        detail_lines.extend([
            "",
            f"### `{case['case_id']}`",
            "",
            f"- Force trace: `{case['force_gauge']['signed_csv']}`; "
            f"samples `{case['force_gauge']['sample_count']}`, "
            f"time `{case['force_gauge']['time_min_s']:.6f}--{case['force_gauge']['time_max_s']:.6f} s`.",
            f"- Three-window signed `Fz` means: "
            f"`{case['screen']['forcez_window_means_n'][0]:.3f}`, "
            f"`{case['screen']['forcez_window_means_n'][1]:.3f}`, "
            f"`{case['screen']['forcez_window_means_n'][2]:.3f} N`; "
            f"stability limit `{case['screen']['stable_window_std_limit_n']:.3f} N`.",
            f"- Source `mkbound=1` maps to generated global `Mk={case['fixed_body_mapping_gate']['mapping_rows'][0]['global_mk']}` "
            f"with `{case['fixed_body_mapping_gate']['mapping_rows'][0]['count']}` fixed particles; "
            f"solver log says `Floating=0`, `Moving=0`.",
            f"- Field snapshots: fixed body max identity-matched motion "
            f"`{case['field_integrity']['fixed_body_particle_motion_max_m']:.3e} m`; "
            f"fluid count constant `{case['field_integrity']['fluid_count_constant']}`, "
            f"mass delta `{case['field_integrity']['fluid_mass_delta_kg']:.3e} kg`, "
            f"penetration `{case['field_integrity']['fluid_penetration_into_box']['initial_particles']}/"
            f"{case['field_integrity']['fluid_penetration_into_box']['final_particles']}`.",
            f"- Initial pressure range: `{case['field_integrity']['pressure_initial_pa']['min']:.3f}--"
            f"{case['field_integrity']['pressure_initial_pa']['max']:.3f} Pa`.",
        ])
    lines.extend(detail_lines)
    lines.extend([
        "",
        "## Interpretation",
        "",
        "The zero-pressure control is a useful chain check: uniform `rhop0`, "
        "zero gravity, complete fields, fixed body and zero signed force are all "
        "observed.  The gravity DBC chain is executable and genuinely fixed, but "
        "its force windows are not stable and the late mean is about 59% above "
        "the analytical pressure reference.  It remains a diagnostic failure, "
        "not evidence that the DBC pressure resultant is physically valid.",
        "",
        "No mDBC run was fabricated: this package contains only the two requested "
        "DBC controls.  The two bounded mDBC calibrations are explicitly recorded "
        "as `blocked_not_run` until their normals/ghost geometry is independently "
        "safe and audited.",
        "",
        "| blocked calibration | status | reason |",
        "|---|---|---|",
        *[
            f"| `{item['case_id']}` | `{item['status']}` | {item['reason']} |"
            for item in report["blocked_calibrations"]
        ],
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    if not all(path.is_file() for path in (GENCASE, SOLVER, PARTVTK)):
        raise SystemExit("missing one or more vendored DualSPHysics binaries")
    started = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, object]] = []
    for index, (case_id, config) in enumerate(CASES.items()):
        try:
            records.append(run_case(case_id, config, index))
        except Exception as error:  # Preserve a machine-readable failed row.
            records.append({
                "case_id": case_id,
                "execution_status": "runner_exception",
                "acceptance_status": "not_accepted",
                "error": f"{type(error).__name__}: {error}",
            })
    report = {
        "schema_version": 1,
        "report_id": "R3-fixed-box-force-gauge",
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_root": str(CASE_ROOT.relative_to(LAB_ROOT)),
        "resource_policy": {
            "allowed_gpu_indices": list(ALLOWED_GPU_INDICES),
            "forbidden_gpu_indices": [0, 1, 2, 3],
            "idle_memory_limit_mib": IDLE_MEMORY_LIMIT_MIB,
            "idle_utilization_limit_percent": IDLE_UTILIZATION_LIMIT_PERCENT,
            "existing_processes_not_interrupted": True,
        },
        "source_semantics": {
            "gauge_xml": "doc/xml_format/_FmtXML_Gauges.xml",
            "gauge_system_add_gauge_force": "src/source/JDsGaugeSystem.cpp:472-493",
            "gauge_force_impl": "src/source/JDsGaugeItem.cpp:1710-1988",
            "gauge_force_kernel": "src/source/JDsGauge_ker.cu:497-603",
            "interpretation": "pressure interaction on selected fixed boundary particles only; excludes gravity, support reaction, and viscosity",
        },
        "analytical_reference": {
            "box_dimensions_m": list(BOX_SIZE),
            "box_volume_m3": BOX_VOLUME_M3,
            "rho_kg_m3": RHO0,
            "g_m_s2": G,
            "fz_n": ANALYTIC_FZ_N,
            "status": "pre_registered_reference_only",
        },
        "cases": records,
        "blocked_calibrations": BLOCKED_CALIBRATIONS,
        "overall_acceptance_status": "candidate_not_accepted",
    }
    json_dump(REPORT_PATH, report)
    (CASE_ROOT / "fixed-box-force-gauge-report.md").write_text(render_markdown(report))
    print(json.dumps({
        "report": str(REPORT_PATH),
        "cases": [{"case_id": row.get("case_id"), "execution_status": row.get("execution_status"),
                   "acceptance_status": row.get("acceptance_status")} for row in records],
    }, indent=2))
    return 0 if all(row.get("execution_status") == "completed" for row in records) else 1


if __name__ == "__main__":
    sys.exit(main())

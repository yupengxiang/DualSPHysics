#!/usr/bin/env python3
"""Source-bound native QA for the completed F2 coarse canary.

The canary solver receipt reports 153 fewer fluid particles at its final
saved state, but a per-``Part`` ``NpOut`` value of zero is not a cumulative
loss count.  This worker runs the official PartVTKOut command against the
already completed ``PartOut_000.obi4`` product and joins every emitted
``Idp`` to the generated XML fluid blocks.  It reports the native Motive,
saved-record time bracket, position, density, MK and per-particle mass.

The generated BI4 is hashed and checked against its existing guarded
snapshot; it is not decoded.  No trajectory HDF5, ``Part_*.bi4`` frame,
solver, GenCase or model is opened or started.  A native numerical motive is
kept separate from physical fate, legal flux and dynamical impact, which
remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any


SCHEMA = "ds02.stage2.f2.coarse-canary-native-qa.v1"
PARTVTKOUT_SHA256 = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
MOTIVES = {1: "position", 2: "density", 3: "movement"}
RUNPART_COUNTERS = ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")


class NativeQaError(ValueError):
    """Raised when the completed canary source contract is not closed."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_record(path: Path, *, digest: str | None = None) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise NativeQaError(f"missing input: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": digest if digest is not None else sha256(path),
    }


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise NativeQaError(f"{label} is not a regular file: {path}")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NativeQaError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise NativeQaError(f"{label} is not a JSON object: {path}")
    return value


def check_ref(ref: dict[str, Any], label: str, *, hash_content: bool = True) -> tuple[Path, dict[str, Any]]:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise NativeQaError(f"{label} lacks a path")
    path = require_file(ref["path"], label)
    actual = stat_record(path, digest=sha256(path) if hash_content else None)
    expected = ref.get("sha256")
    if expected is not None and expected != "PARENT_GUARD_COMPUTED" and actual["sha256"] != str(expected):
        raise NativeQaError(f"{label} digest differs: {path}")
    if ref.get("bytes") is not None and actual["bytes"] != int(ref["bytes"]):
        raise NativeQaError(f"{label} byte count differs: {path}")
    for field in ("mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if ref.get(field) is not None and actual[field] != int(ref[field]):
            raise NativeQaError(f"{label} {field} differs: {path}")
    return path, actual


def local(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def first(root: ET.Element, name: str, label: str) -> ET.Element:
    for node in root.iter():
        if local(node) == name:
            return node
    raise NativeQaError(f"{label} has no <{name}>")


def number(value: str | None, label: str) -> float:
    if value is None:
        raise NativeQaError(f"{label} is missing")
    try:
        result = float(value)
    except ValueError as exc:
        raise NativeQaError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise NativeQaError(f"{label} is not finite")
    return result


def generated_fluid_blocks(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = first(root, "particles", "generated XML")
    blocks: list[dict[str, Any]] = []
    for child in list(particles):
        if local(child) != "fluid":
            continue
        try:
            begin = int(child.attrib["begin"])
            count = int(child.attrib["count"])
            mkfluid = int(child.attrib["mkfluid"])
            mk = int(child.attrib["mk"])
        except (KeyError, TypeError, ValueError) as exc:
            raise NativeQaError("generated XML fluid block is malformed") from exc
        if begin < 0 or count <= 0:
            raise NativeQaError("generated XML fluid block has invalid range")
        blocks.append({"begin": begin, "count": count, "mkfluid": mkfluid, "mk": mk})
    if not blocks:
        raise NativeQaError("generated XML has no fluid blocks")
    particles_count = int(particles.attrib.get("np", "-1"))
    massfluid = first(root, "massfluid", "generated XML")
    mass_kg = number(massfluid.get("value"), "generated XML massfluid")
    if particles_count <= 0 or mass_kg <= 0:
        raise NativeQaError("generated XML particles/massfluid are invalid")
    total = sum(block["count"] for block in blocks)
    summary = first(particles, "_summary", "generated XML")
    fluid_summary = next((node for node in list(summary) if local(node) == "fluid"), None)
    if fluid_summary is not None and int(fluid_summary.get("count", "-1")) != total:
        raise NativeQaError("generated XML fluid summary differs from block counts")
    return {
        "particles": particles_count,
        "massfluid_kg": mass_kg,
        "fluid_count": total,
        "fluid_blocks": blocks,
    }


def validate_generated_expectations(generated: dict[str, Any], expected: dict[str, Any]) -> None:
    """Close the generated XML identity against the bound canary metadata."""
    if generated["particles"] != int(expected.get("initial_particles_total", generated["particles"])):
        raise NativeQaError("generated XML total particle count differs from manifest")
    if generated["fluid_count"] != int(expected.get("initial_fluid_count", generated["fluid_count"])):
        raise NativeQaError("generated XML initial fluid count differs from manifest")
    expected_mass = expected.get("massfluid_kg")
    if expected_mass is not None and not math.isclose(
        generated["massfluid_kg"], float(expected_mass), rel_tol=0.0, abs_tol=1.0e-15
    ):
        raise NativeQaError("generated XML massfluid differs from manifest")
    expected_blocks = expected.get("fluid_blocks")
    if expected_blocks is not None:
        normalized = [
            {
                "begin": int(block["begin"]),
                "count": int(block["count"]),
                "mkfluid": int(block["mkfluid"]),
                "mk": int(block["mk"]),
            }
            for block in expected_blocks
        ]
        if generated["fluid_blocks"] != normalized:
            raise NativeQaError("generated XML fluid blocks differ from manifest")
    ordered = sorted(generated["fluid_blocks"], key=lambda block: block["begin"])
    previous_end = 0
    for block in ordered:
        if block["begin"] < previous_end or block["begin"] + block["count"] > generated["particles"]:
            raise NativeQaError("generated XML fluid blocks overlap or exceed particles")
        previous_end = block["begin"] + block["count"]


def parse_runparts(path: Path) -> dict[str, Any]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines, delimiter=";")
    if not reader.fieldnames or not set(("Part", "TimeStep [s]", *RUNPART_COUNTERS)) <= set(reader.fieldnames):
        raise NativeQaError("RunPARTs lacks required native counters")
    rows: list[dict[str, Any]] = []
    totals = {field: 0 for field in RUNPART_COUNTERS}
    for raw in reader:
        try:
            part = int(str(raw["Part"]).replace(",", ""))
            time_s = float(raw["TimeStep [s]"])
            counters = {field: int(str(raw[field]).replace(",", "")) for field in RUNPART_COUNTERS}
        except (KeyError, TypeError, ValueError) as exc:
            raise NativeQaError("RunPARTs contains malformed data") from exc
        if part != len(rows) or not math.isfinite(time_s):
            raise NativeQaError("RunPARTs part index/time sequence is invalid")
        if rows and time_s <= rows[-1]["time_s"]:
            raise NativeQaError("RunPARTs time is not increasing")
        if any(value < 0 for value in counters.values()):
            raise NativeQaError("RunPARTs contains negative counters")
        if counters["NpOut"] != sum(counters[field] for field in RUNPART_COUNTERS[1:]):
            raise NativeQaError("RunPARTs motive counters do not sum to NpOut")
        rows.append({"part": part, "time_s": time_s, **counters})
        for field, value in counters.items():
            totals[field] += value
    if not rows:
        raise NativeQaError("RunPARTs has no records")
    return {"rows": rows, "totals": totals, "last_time_s": rows[-1]["time_s"]}


def _field(row: dict[str, str], *names: str) -> str:
    for name in names:
        if name in row:
            return row[name]
    raise KeyError(names[0])


def parse_native_csv(path: Path, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise NativeQaError("PartVTKOut CSV is empty")
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    reader = csv.DictReader(lines, delimiter=delimiter)
    if not reader.fieldnames:
        raise NativeQaError("PartVTKOut CSV header is missing")
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in reader:
        try:
            idp = int(_field(raw, "Idp"))
            part = int(_field(raw, "PartOut"))
            motive_code = int(_field(raw, "Motive"))
            pos = [number(_field(raw, f"Pos.{axis} [m]"), f"Idp {idp} position {axis}") for axis in "xyz"]
            density = number(_field(raw, "Rhop [kg/m^3]"), f"Idp {idp} density")
        except (KeyError, TypeError, ValueError) as exc:
            raise NativeQaError("PartVTKOut CSV contains malformed row") from exc
        if idp in seen or idp < 0 or part < 1 or motive_code not in MOTIVES:
            raise NativeQaError(f"PartVTKOut CSV has invalid native identity Idp={idp}")
        seen.add(idp)
        velocity = None
        if all(f"Vel.{axis} [m/s]" in raw for axis in "xyz"):
            velocity = [number(raw[f"Vel.{axis} [m/s]"], f"Idp {idp} velocity {axis}") for axis in "xyz"]
        block = next((item for item in blocks if item["begin"] <= idp < item["begin"] + item["count"]), None)
        if block is None:
            raise NativeQaError(f"PartVTKOut Idp {idp} is outside generated fluid blocks")
        rows.append({
            "idp": idp,
            "part_out": part,
            "motive_code": motive_code,
            "motive": MOTIVES[motive_code],
            "position_m": pos,
            "density_kg_m3": density,
            "velocity_m_s": velocity,
            "particle_type": "fluid",
            "type_code": 3,
            "mkfluid": block["mkfluid"],
            "mk": block["mk"],
            "initial_mass_kg": None,
        })
    if not rows:
        raise NativeQaError("PartVTKOut CSV has no native rows")
    return rows


def attach_saved_brackets(rows: list[dict[str, Any]], runparts: dict[str, Any]) -> None:
    by_part = {row["part"]: row for row in runparts["rows"]}
    ordered = sorted(by_part)
    for row in rows:
        if row["part_out"] not in by_part:
            raise NativeQaError(f"native PartOut {row['part_out']} is absent from RunPARTs")
        index = ordered.index(row["part_out"])
        current = by_part[row["part_out"]]["time_s"]
        previous = by_part[ordered[index - 1]]["time_s"] if index else None
        row["saved_record_time_s"] = current
        row["saved_record_bracket_s"] = [previous, current]


def expanded_command(command: list[Any], attempt_root: Path) -> list[str]:
    return [str(value).replace("{attempt_root}", str(attempt_root)) for value in command]


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = require_file(manifest_path, "native QA manifest")
    manifest = read_json(manifest_path, "native QA manifest")
    if manifest.get("schema") != "ds02.stage2.f2.coarse-canary-native-qa.manifest.v1":
        raise NativeQaError("unsupported native QA manifest schema")
    refs = manifest.get("inputs")
    if not isinstance(refs, dict):
        raise NativeQaError("native QA manifest has no inputs")
    required = (
        "solver_receipt", "solver_request", "raw_partout", "runparts", "run_out",
        "generated_xml", "generated_bi4", "generated_bi4_snapshot", "gencase_receipt",
        "candidate_definition", "lineage_definition", "support_report", "partvtk_binary",
    )
    for key in required:
        if key not in refs:
            raise NativeQaError(f"native QA manifest lacks {key}")
    records: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    for key in required:
        path, record = check_ref(refs[key], key)
        paths[key] = path
        records[key] = record
    manifest_record = stat_record(manifest_path)
    solver_receipt = read_json(paths["solver_receipt"], "solver receipt")
    if solver_receipt.get("schema") != "ds02.stage2.external-solver-report.v5" or not str(solver_receipt.get("status", "")).startswith("COMPLETED"):
        raise NativeQaError("solver receipt is not a completed external-solver report")
    if solver_receipt.get("execution", {}).get("returncode") != 0:
        raise NativeQaError("solver receipt has nonzero returncode")
    raw_data_ref = manifest.get("raw_data_root")
    solver_output_ref = manifest.get("solver_output_root")
    if not isinstance(raw_data_ref, dict) or not isinstance(raw_data_ref.get("path"), str):
        raise NativeQaError("native QA manifest lacks top-level raw_data_root")
    if not isinstance(solver_output_ref, dict) or not isinstance(solver_output_ref.get("path"), str):
        raise NativeQaError("native QA manifest lacks top-level solver_output_root")
    raw_data_root = Path(raw_data_ref["path"]).expanduser().resolve()
    solver_output_root = Path(solver_output_ref["path"]).expanduser().resolve()
    if not raw_data_root.is_dir() or paths["raw_partout"].parent != raw_data_root:
        raise NativeQaError("raw PartOut is not under the bound solver data root")
    if paths["runparts"].parent != solver_output_root or paths["run_out"].parent != solver_output_root:
        raise NativeQaError("RunPARTs/Run.out are not under the bound solver output root")
    if Path(solver_receipt.get("filesystem", {}).get("output_root", "")).resolve() != solver_output_root.parent:
        raise NativeQaError("solver receipt output root differs from manifest")
    solver_request_path, solver_request_record = check_ref(refs["solver_request"], "solver request")
    if solver_receipt.get("request", {}).get("path") != str(solver_request_path):
        raise NativeQaError("solver receipt request path differs")
    if solver_receipt.get("request", {}).get("sha256") != solver_request_record["sha256"]:
        raise NativeQaError("solver receipt request digest differs")
    snapshot = read_json(paths["generated_bi4_snapshot"], "generated BI4 snapshot")
    snapshot_source = snapshot.get("source", {})
    if snapshot.get("status") != "PASS_GENERATED_BI4_HASHED_STABLE":
        raise NativeQaError("generated BI4 snapshot is not stable")
    if snapshot_source.get("path") != str(paths["generated_bi4"]):
        raise NativeQaError("generated BI4 snapshot path differs")
    if snapshot_source.get("sha256") != records["generated_bi4"]["sha256"]:
        raise NativeQaError("generated BI4 snapshot digest differs")
    gencase_receipt = read_json(paths["gencase_receipt"], "GenCase receipt")
    if gencase_receipt.get("status") not in {"completed", "COMPLETED"} or gencase_receipt.get("returncode") != 0:
        raise NativeQaError("GenCase receipt is not completed")
    if records["partvtk_binary"]["sha256"] != PARTVTKOUT_SHA256:
        raise NativeQaError("official PartVTKOut digest differs")
    generated = generated_fluid_blocks(paths["generated_xml"])
    expected = manifest.get("expected", {})
    validate_generated_expectations(generated, expected)
    decoder_root = Path(output_path).expanduser().resolve().parent
    decoder_root.mkdir(parents=True, exist_ok=True)
    csv_path = decoder_root / "PartOut.csv"
    resume_path = decoder_root / "resume.csv"
    if csv_path.exists() or resume_path.exists():
        raise NativeQaError("decoder output already exists in attempt root")
    command = [
        str(paths["partvtk_binary"]), "-dirdata", str(raw_data_root),
        "-savecsv", str(csv_path), "-saveresume", str(resume_path),
        "-createdirs:1", "-csvsep:1",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=600)
    if completed.returncode != 0:
        raise NativeQaError(f"official PartVTKOut failed with returncode {completed.returncode}: {completed.stderr[-1000:]}")
    if not csv_path.is_file() or not resume_path.is_file():
        raise NativeQaError("official PartVTKOut did not produce CSV/resume")
    runparts = parse_runparts(paths["runparts"])
    native_rows = parse_native_csv(csv_path, generated["fluid_blocks"])
    attach_saved_brackets(native_rows, runparts)
    for row in native_rows:
        row["initial_mass_kg"] = generated["massfluid_kg"]
    motive_counts = Counter(row["motive"] for row in native_rows)
    runpart_totals = runparts["totals"]
    if len(native_rows) != runpart_totals["NpOut"]:
        raise NativeQaError(f"native CSV rows {len(native_rows)} differ from RunPARTs cumulative NpOut {runpart_totals['NpOut']}")
    for motive, field in (("position", "NpOutPos"), ("density", "NpOutRho"), ("movement", "NpOutMov")):
        if motive_counts.get(motive, 0) != runpart_totals[field]:
            raise NativeQaError(f"native CSV {motive} rows differ from RunPARTs {field}")
    expected_loss = expected.get("expected_native_loss_count")
    if expected_loss is not None and len(native_rows) != int(expected_loss):
        raise NativeQaError(f"native CSV count differs from bound canary summary: {len(native_rows)} != {expected_loss}")
    post = {key: stat_record(path) for key, path in paths.items()}
    if records != post:
        raise NativeQaError("bound native QA inputs changed during decoder/QA")
    report = {
        "schema": SCHEMA,
        "status": "COMPLETED_F2_COARSE_CANARY_NATIVE_IDENTITY_MOTIVE_QA",
        "manifest": manifest_record,
        "solver_receipt": records["solver_receipt"],
        "decoder": {
            "binary": records["partvtk_binary"],
            "command": command,
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
            "csv": stat_record(csv_path),
            "resume": stat_record(resume_path),
        },
        "generated_particles": generated,
        "runparts": {
            "records": len(runparts["rows"]),
            "last_saved_time_s": runparts["last_time_s"],
            "cumulative_counters": runpart_totals,
            "final_record_counters": runparts["rows"][-1],
        },
        "native_identity": {
            "rows": native_rows,
            "row_count": len(native_rows),
            "motive_counts": dict(sorted(motive_counts.items())),
            "mass_by_mk": {
                str(mk): sum(row["initial_mass_kg"] for row in native_rows if row["mk"] == mk)
                for mk in sorted({row["mk"] for row in native_rows})
            },
            "total_missing_mass_kg": sum(row["initial_mass_kg"] for row in native_rows),
            "units": {"idp": "native particle index", "mass": "kg", "position": "m", "density": "kg/m^3", "saved_time": "s", "velocity": "m/s"},
        },
        "source_cause": {
            "basis": "official PartVTKOut Motive joined to generated XML fluid Idp block and RunPARTs cumulative motive counters",
            "native_numerical_causes": sorted(motive_counts),
            "physical_fate": "UNKNOWN_NOT_PROVEN",
            "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN",
            "continuous_event_time": "UNKNOWN; saved record brackets only",
            "dynamical_impact": "UNKNOWN",
        },
        "input_stability": {"pre": records, "post": post, "all_equal": records == post},
        "read_policy": {
            "trajectory_h5_opened": False,
            "part_frames_opened": False,
            "partout_000_opened_by_official_decoder": True,
            "generated_bi4_decoded": False,
            "solver_started": False,
            "gencase_started": False,
            "model_or_cfd_started": False,
            "old_products_modified": False,
        },
        "scientific_status": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    write_new(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = audit(Path(args.manifest), Path(args.output))
    except Exception as exc:
        print(f"F2 coarse canary native QA failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"schema": report["schema"], "status": report["status"], "rows": report["native_identity"]["row_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

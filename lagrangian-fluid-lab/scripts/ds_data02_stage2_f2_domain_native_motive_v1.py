#!/usr/bin/env python3
"""Bounded per-ID native motive audit for the completed ROOT130 control.

This forward-only worker runs the official PartVTKOut binary once against the
already completed ROOT130 ``PartOut_000.obi4`` product.  It joins every
emitted ``Idp`` to the exact ROOT130 XML fluid blocks and RunPARTs saved
records, preserving the actual Motive and a saved-record time bracket.  The
ROOT138 aggregate stream is used only as an identity-scope cross-check:
common/old-only/new-only sets are recorded and never expanded into synthetic
per-ID rows.

The worker opens no trajectory HDF5 and no ``Part_*.bi4`` frame.  It does not
start a solver or GenCase.  Native numerical motive remains separate from
physical fate, legal flux, contact, and dynamical impact, all of which remain
UNKNOWN.
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


SCHEMA = "ds02.stage2.f2.domain-native-motive.v1"
PARTVTKOUT_SHA256 = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
MANIFEST_SCHEMA = "ds02.stage2.f2.domain-native-motive.manifest.v1"
ROOT130_CASE_ID = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_DOMAIN_SENSITIVITY_MARGIN_V1"
ROOT130_EXPECTED_NP_OUT = 67
ROOT130_EXPECTED_LAST_TIME_S = 4.00002065943922
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


def _check_root130_scope(manifest: dict[str, Any], records: dict[str, dict[str, Any]], paths: dict[str, Path]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the completed ROOT130 receipt/proof and ROOT138 identity scope."""
    receipt = read_json(paths["domain_receipt"], "ROOT130 solver receipt")
    if receipt.get("schema") != "ds02.stage2.external-solver-report.v5":
        raise NativeQaError("ROOT130 receipt schema is not external-solver-report.v5")
    if not str(receipt.get("status", "")).startswith("COMPLETED") or receipt.get("execution", {}).get("returncode") != 0:
        raise NativeQaError("ROOT130 receipt is not a completed successful solver report")
    request_info = receipt.get("request", {})
    if request_info.get("path") != str(paths["domain_request"]):
        raise NativeQaError("ROOT130 receipt request path differs")
    if request_info.get("sha256") != records["domain_request"]["sha256"]:
        raise NativeQaError("ROOT130 receipt request SHA differs")
    if receipt.get("filesystem", {}).get("output_root") != str(paths["solver_output_root"]):
        raise NativeQaError("ROOT130 receipt output root differs")
    if receipt.get("execution", {}).get("source_verified_after_reservation") is not True:
        raise NativeQaError("ROOT130 receipt lacks post-reservation source verification")
    domain_proof = read_json(paths["domain_proof"], "ROOT130 verification proof")
    if domain_proof.get("request_sha256") != records["domain_request"]["sha256"]:
        raise NativeQaError("ROOT130 proof request SHA differs")
    if domain_proof.get("receipt_sha256") != records["domain_receipt"]["sha256"]:
        raise NativeQaError("ROOT130 proof receipt SHA differs")
    run_summary = domain_proof.get("RunPARTs_summary", {})
    if int(run_summary.get("rows", -1)) != 401:
        raise NativeQaError("ROOT130 proof RunPARTs row count differs")
    if float(run_summary.get("final_NpfSim", -1)) != 27683.0:
        raise NativeQaError("ROOT130 proof final active fluid count differs")
    if float(run_summary.get("saved_window_new_exclusion_sums", {}).get("NpOut", -1)) != ROOT130_EXPECTED_NP_OUT:
        raise NativeQaError("ROOT130 proof aggregate NpOut differs")
    if float(run_summary.get("saved_window_new_exclusion_sums", {}).get("NpOutPos", -1)) != ROOT130_EXPECTED_NP_OUT:
        raise NativeQaError("ROOT130 proof aggregate position count differs")
    if float(run_summary.get("saved_window_new_exclusion_sums", {}).get("NpOutRho", -1)) != 0.0:
        raise NativeQaError("ROOT130 proof aggregate density count differs")
    if float(run_summary.get("saved_window_new_exclusion_sums", {}).get("NpOutMov", -1)) != 0.0:
        raise NativeQaError("ROOT130 proof aggregate movement count differs")
    root138 = read_json(paths["root138_proof"], "ROOT138 identity proof")
    comparison = root138.get("native_control_identity_comparison", {})
    expected_comparison = {
        "old_count": 153,
        "new_count": 67,
        "common_ids": 27,
        "old_only_ids": 126,
        "new_only_ids": 40,
        "new_set_is_subset_of_old": False,
    }
    for key, value in expected_comparison.items():
        if comparison.get(key) != value:
            raise NativeQaError(f"ROOT138 identity scope differs for {key}: {comparison.get(key)!r}")
    if root138.get("per_id_motive") != "UNKNOWN_NO_BOUND_PARTOUT_IDENTITY_SOURCE":
        raise NativeQaError("ROOT138 proof does not preserve the pre-ROOT142 per-ID motive gap")
    return domain_proof, root138


def _deferred_ref(ref: dict[str, Any], label: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise NativeQaError(f"{label} lacks a deferred path")
    path = require_file(ref["path"], label)
    actual = stat_record(path)
    expected = ref.get("sha256")
    if expected not in (None, "PARENT_GUARD_COMPUTED") and actual["sha256"] != str(expected):
        raise NativeQaError(f"{label} digest differs: {path}")
    if ref.get("bytes") is not None and actual["bytes"] != int(ref["bytes"]):
        raise NativeQaError(f"{label} byte count differs: {path}")
    return path, actual


def _validate_manifest(manifest_path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]]]:
    manifest_path = require_file(manifest_path, "domain native motive manifest")
    manifest = read_json(manifest_path, "domain native motive manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise NativeQaError("unsupported domain native motive manifest schema")
    if manifest.get("case_id") != ROOT130_CASE_ID or manifest.get("family_id") != "F2":
        raise NativeQaError("manifest ROOT130 case/family binding differs")
    refs = manifest.get("inputs")
    if not isinstance(refs, dict):
        raise NativeQaError("manifest has no inputs")
    required_static = ("domain_receipt", "domain_request", "domain_proof", "domain_xml", "domain_prepared", "partvtk_binary", "root138_proof")
    required_deferred = ("raw_partout", "runparts", "run_out")
    for key in (*required_static, *required_deferred):
        if key not in refs:
            raise NativeQaError(f"manifest lacks {key}")
    records: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    for key in required_static:
        path, record = check_ref(refs[key], key)
        paths[key] = path
        records[key] = record
    for key in required_deferred:
        path, record = _deferred_ref(refs[key], key)
        paths[key] = path
        records[key] = record
    raw_root_ref = manifest.get("raw_data_root")
    solver_root_ref = manifest.get("solver_output_root")
    if not isinstance(raw_root_ref, dict) or not isinstance(raw_root_ref.get("path"), str):
        raise NativeQaError("manifest lacks raw_data_root")
    if not isinstance(solver_root_ref, dict) or not isinstance(solver_root_ref.get("path"), str):
        raise NativeQaError("manifest lacks solver_output_root")
    raw_root = Path(raw_root_ref["path"]).expanduser().resolve()
    solver_root = Path(solver_root_ref["path"]).expanduser().resolve()
    paths["raw_data_root"] = raw_root
    paths["solver_output_root"] = solver_root
    if not raw_root.is_dir() or paths["raw_partout"].parent != raw_root:
        raise NativeQaError("raw PartOut is not under ROOT130 raw data root")
    if paths["runparts"].parent != solver_root or paths["run_out"].parent != solver_root:
        raise NativeQaError("RunPARTs/Run.out are not under ROOT130 solver output root")
    if paths["raw_partout"].name != "PartOut_000.obi4":
        raise NativeQaError("ROOT142 must bind exactly PartOut_000.obi4")
    if paths["raw_partout"].parent != raw_root:
        raise NativeQaError("ROOT142 PartOut parent differs from raw root")
    domain_xml = paths["domain_xml"]
    generated = generated_fluid_blocks(domain_xml)
    expected = manifest.get("expected", {})
    validate_generated_expectations(generated, expected)
    if generated["particles"] != 540633 or generated["fluid_count"] != 27750:
        raise NativeQaError("ROOT130 XML particle/fluid identity differs")
    domain_proof, root138 = _check_root130_scope(manifest, records, paths)
    return manifest, paths, {"records": records, "generated": generated, "domain_proof": domain_proof, "root138": root138, "manifest_record": stat_record(manifest_path)}


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest, paths, context = _validate_manifest(manifest_path)
    records = context["records"]
    generated = context["generated"]
    decoder_root = Path(output_path).expanduser().resolve().parent
    decoder_root.mkdir(parents=True, exist_ok=True)
    csv_path = decoder_root / "PartOut.csv"
    resume_path = decoder_root / "resume.csv"
    if csv_path.exists() or resume_path.exists():
        raise NativeQaError("decoder output already exists in attempt root")
    command = [
        str(paths["partvtk_binary"]), "-dirdata", str(paths["raw_data_root"]),
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
        row["mass_source"] = "ROOT130 domain XML MassFluid; native BI4 mass array was not decoded by this worker"
    motive_counts = Counter(row["motive"] for row in native_rows)
    runpart_totals = runparts["totals"]
    if len(native_rows) != runpart_totals["NpOut"]:
        raise NativeQaError(f"native CSV rows {len(native_rows)} differ from ROOT130 cumulative NpOut {runpart_totals['NpOut']}")
    if len(native_rows) != ROOT130_EXPECTED_NP_OUT:
        raise NativeQaError(f"ROOT130 native row count differs from bound 67: {len(native_rows)}")
    for motive, field in (("position", "NpOutPos"), ("density", "NpOutRho"), ("movement", "NpOutMov")):
        if motive_counts.get(motive, 0) != runpart_totals[field]:
            raise NativeQaError(f"native CSV {motive} rows differ from RunPARTs {field}")
    if motive_counts.get("position", 0) != ROOT130_EXPECTED_NP_OUT or motive_counts.get("density", 0) != 0 or motive_counts.get("movement", 0) != 0:
        raise NativeQaError("ROOT130 per-ID motive rows do not match its aggregate counters")
    post = {key: stat_record(path) for key, path in paths.items() if key not in {"raw_data_root", "solver_output_root"}}
    if records != post:
        raise NativeQaError("ROOT130 bound inputs changed during official decoder/QA")
    total_missing_mass = sum(row["initial_mass_kg"] for row in native_rows)
    whole_initial_mass = float(manifest["expected"]["whole_initial_xml_mass_kg"])
    unknown_fraction = total_missing_mass / whole_initial_mass
    report = {
        "schema": SCHEMA,
        "status": "COMPLETED_F2_ROOT130_NATIVE_IDENTITY_MOTIVE_QA",
        "case_id": ROOT130_CASE_ID,
        "manifest": context["manifest_record"],
        "source_scope": {
            "root130_solver_receipt": records["domain_receipt"],
            "root130_request": records["domain_request"],
            "root130_proof": records["domain_proof"],
            "root138_identity_proof": records["root138_proof"],
            "raw_data_root": str(paths["raw_data_root"]),
            "solver_output_root": str(paths["solver_output_root"]),
        },
        "decoder": {
            "binary": records["partvtk_binary"],
            "command": command,
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
            "csv": stat_record(csv_path),
            "resume": stat_record(resume_path),
            "reads_exact_partout": "PartOut_000.obi4",
            "threads_flag_present": False,
        },
        "generated_particles": generated,
        "runparts": {
            "records": len(runparts["rows"]),
            "last_saved_time_s": runparts["last_time_s"],
            "cumulative_counters": runpart_totals,
            "final_record_counters": runparts["rows"][-1],
            "last_saved_time_expected_s": ROOT130_EXPECTED_LAST_TIME_S,
        },
        "native_identity": {
            "rows": native_rows,
            "row_count": len(native_rows),
            "motive_counts": dict(sorted(motive_counts.items())),
            "mass_by_mk": {str(mk): sum(row["initial_mass_kg"] for row in native_rows if row["mk"] == mk) for mk in sorted({row["mk"] for row in native_rows})},
            "total_missing_mass_kg": total_missing_mass,
            "units": {"idp": "native particle index", "mass": "kg", "position": "m", "density": "kg/m^3", "saved_time": "s", "velocity": "m/s"},
            "motive_authority": "official PartVTKOut CSV Idp/Motive; no synthetic rows from aggregate NpOut",
        },
        "identity_scope": {
            "root138_aggregate": {"old_count": 153, "new_count": 67, "common_ids": 27, "old_only_ids": 126, "new_only_ids": 40, "new_set_is_subset_of_old": False},
            "scope_statement": "ROOT130 per-ID rows are a new PartOut identity audit. ROOT138 aggregate differences are not interpreted as recovery, fate, or a subset relation.",
        },
        "mass_screen": {
            "whole_initial_xml_mass_kg": whole_initial_mass,
            "native_xml_massfluid_per_id_kg": generated["massfluid_kg"],
            "observed_missing_mass_kg": total_missing_mass,
            "observed_unknown_fraction_of_xml_whole": unknown_fraction,
            "frozen_unknown_fraction_limit": 0.003,
            "status": "PASS_ONLY_LOWER_BOUND_SCREEN" if unknown_fraction <= 0.003 else "FAIL",
            "screen_scope": "mass visibility lower bound only; no QI/QN/QE or dynamics credit",
        },
        "source_cause": {
            "basis": "official PartVTKOut Motive joined to ROOT130 XML fluid Idp block and ROOT130 RunPARTs cumulative counters",
            "native_numerical_causes": sorted(motive_counts),
            "physical_fate": "UNKNOWN_NOT_PROVEN",
            "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN",
            "wall_or_contact": "UNKNOWN_NOT_PROVEN",
            "continuous_event_time": "UNKNOWN; saved-record bracket only, not exact physical event time",
            "dynamical_impact": "UNKNOWN",
        },
        "input_stability": {"pre": records, "post": post, "all_equal": records == post},
        "read_policy": {
            "trajectory_h5_opened": False,
            "part_frames_opened": False,
            "partout_000_opened_by_official_decoder": True,
            "runparts_opened": True,
            "run_out_content_hashed": True,
            "run_out_parsed": False,
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

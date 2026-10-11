#!/usr/bin/env python3
"""Decode and audit full-window native PartOut records for a completed run.

This is the metadata-driven successor to
``ds_data02_stage2_f1_dp0025_native_motive_audit_v2.py``.  It keeps the
official ``PartVTKOut_linux64`` decoder and its native Motive/PartOut parsing,
but takes the case id, receipts, expected counts, and source paths from a
small manifest.  It is intentionally bounded: it opens the small
``PartOut_000.obi4``, ``RunPARTs.csv``, ``Run.out``, and generated metadata,
never opens ``Part_*.bi4`` trajectory frames or HDF5, and never starts a
solver.

The output is the source-closed evidence consumed by the F1 numerical-bridge
comparison.  Native ``Idp`` and Motive/PartOut causes are retained.  The
``Idp`` check covers one row per native exclusion and its initial range; it
does not claim per-frame identity continuity because trajectory frames are
deliberately not opened.  A native numerical-node exclusion is not
interpreted as physical outflow or particle death.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping


MANIFEST_SCHEMA = "ds-data-02.upstream-first.native-integrity-manifest.v1"
OUTPUT_SCHEMA = "ds-data-02.upstream-first.f1-native-integrity.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
MOTIVES = {1: "position", 2: "density", 3: "movement"}
RUNPART_FIELDS = {1: "NpOutPos", 2: "NpOutRho", 3: "NpOutMov"}
TIME_EPSILON_S = 1.0e-6


class IntegrityError(ValueError):
    """Raised when a native source or decoded result is not closed."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path_value: str | Path, label: str, *, reject_trajectory: bool = False) -> Path:
    declared = Path(path_value).expanduser()
    if declared.is_symlink():
        raise IntegrityError(f"{label} is a symbolic link: {declared}")
    path = declared.resolve()
    if reject_trajectory and path.name.startswith("Part_") and path.suffix == ".bi4":
        raise IntegrityError(f"{label} is a trajectory frame: {path}")
    if not path.is_file():
        raise IntegrityError(f"{label} is not a regular file: {path}")
    return path


def binding(
    value: Mapping[str, Any], label: str, *, reject_trajectory: bool = False
) -> tuple[Path, dict[str, Any]]:
    path_value = value.get("path")
    if not isinstance(path_value, str) or not path_value:
        raise IntegrityError(f"{label} lacks a path")
    path = regular(path_value, label, reject_trajectory=reject_trajectory)
    actual = sha256(path)
    expected = value.get("sha256")
    if not isinstance(expected, str) or actual != expected:
        raise IntegrityError(f"{label} SHA-256 differs: expected {expected}, got {actual}")
    size = path.stat().st_size
    if "bytes" in value and int(value["bytes"]) != size:
        raise IntegrityError(f"{label} byte count differs")
    return path, {"path": str(path), "sha256": actual, "bytes": size}


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"{label} must be a JSON object")
    return value


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise IntegrityError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
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


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise IntegrityError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise IntegrityError(f"{label} is not finite: {value!r}")
    return result


def _integer(value: Any, label: str) -> int:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise IntegrityError(f"{label} is not an integer: {value!r}") from exc


def _receipt_binding(
    path: Path,
    *,
    label: str,
    family_id: str,
    case_id: str,
    expected_output_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = read_json(path, label)
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise IntegrityError(f"{label} has unexpected schema")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise IntegrityError(f"{label} is not a completed zero-return receipt")
    request = receipt.get("request")
    if not isinstance(request, Mapping):
        raise IntegrityError(f"{label} lacks request metadata")
    if request.get("family_id") != family_id or request.get("case_id") != case_id:
        raise IntegrityError(f"{label} case binding differs from manifest")
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if output_root != expected_output_root.resolve():
        raise IntegrityError(f"{label} output root differs from manifest")
    return receipt, {
        "path": str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "case_id": request.get("case_id"),
        "attempt_id": request.get("attempt_id"),
        "status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "output_root": str(output_root),
    }


def _read_runout(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")

    def extract(pattern: str, label: str) -> int:
        match = re.search(pattern, text)
        if not match:
            raise IntegrityError(f"Run.out lacks {label}")
        return _integer(match.group(1), label)

    events = [
        {
            "particles_out": _integer(match.group(1), "Run.out particles out event"),
            "total_out": _integer(match.group(2), "Run.out total out event"),
            "current_particles": _integer(match.group(3), "Run.out current particle event"),
        }
        for match in re.finditer(
            r"Particles out:\s*([0-9,]+)\s*\(total out:\s*([0-9,]+)\)\s*-\s*Current np:\s*([0-9,]+)",
            text,
            flags=re.IGNORECASE,
        )
    ]
    if not events:
        raise IntegrityError("Run.out lacks native particle-out event lines")
    previous_total = -1
    for event in events:
        if event["particles_out"] <= 0 or event["total_out"] <= previous_total:
            raise IntegrityError("Run.out particle-out totals are not strictly increasing")
        previous_total = event["total_out"]
    return {
        "initial_particles": extract(
            r"Particles of simulation \(initial\):\s*([0-9,]+)",
            "initial particle count",
        ),
        "excluded_particles": extract(
            r"Excluded particles\.*:\s*([0-9,]+)", "excluded particle count"
        ),
        "particle_out_events": events,
        "terminal_particle_out": events[-1],
    }


def _read_runparts(path: Path, *, minimum_time_end_s: float) -> dict[str, Any]:
    lines = [
        line
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    reader = csv.DictReader(lines, delimiter=";")
    required = {"Part", "TimeStep [s]", "NpOut", *RUNPART_FIELDS.values()}
    if not reader.fieldnames or not required <= set(reader.fieldnames):
        raise IntegrityError("RunPARTs.csv lacks native exclusion counters")
    optional = {"NpSave", "NpSim", "NpNew"}
    rows: list[dict[str, Any]] = []
    totals = {name: 0 for name in ("NpOut", *RUNPART_FIELDS.values())}
    previous_time: float | None = None
    for index, raw in enumerate(reader):
        part = _integer(raw.get("Part"), f"RunPARTs row {index}.Part")
        time_s = _finite(raw.get("TimeStep [s]"), f"RunPARTs row {index}.time")
        if part != index:
            raise IntegrityError("RunPARTs Part sequence is not contiguous from zero")
        if previous_time is not None and time_s <= previous_time:
            raise IntegrityError("RunPARTs time sequence is not strictly increasing")
        counters = {
            name: _integer(raw.get(name), f"RunPARTs row {index}.{name}")
            for name in totals
        }
        if any(value < 0 for value in counters.values()):
            raise IntegrityError("RunPARTs contains a negative native counter")
        if counters["NpOut"] != sum(counters[name] for name in RUNPART_FIELDS.values()):
            raise IntegrityError("RunPARTs motive counters do not sum to NpOut")
        extra = {
            name: _integer(raw.get(name), f"RunPARTs row {index}.{name}")
            for name in optional
            if name in raw and str(raw.get(name, "")).strip()
        }
        if extra.get("NpNew", 0) != 0:
            raise IntegrityError("dynamic/new particle records are outside this fixed-identity route")
        rows.append({"part": part, "time_s": time_s, **counters, **extra})
        previous_time = time_s
        for name, value in counters.items():
            totals[name] += value
    if not rows:
        raise IntegrityError("RunPARTs.csv has no saved rows")
    first_time = rows[0]["time_s"]
    last_time = rows[-1]["time_s"]
    if first_time > TIME_EPSILON_S or last_time < minimum_time_end_s - TIME_EPSILON_S:
        raise IntegrityError(
            f"RunPARTs time window [{first_time}, {last_time}] does not cover "
            f"the required end {minimum_time_end_s}"
        )
    return {
        "rows": rows,
        "totals": totals,
        "strictly_increasing": True,
        "window_s": [first_time, last_time],
        "part_count": len(rows),
        "part_index_start": rows[0]["part"],
        "part_index_end": rows[-1]["part"],
    }


def _read_partout_csv(path: Path, *, initial_particles: int) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    if not lines:
        raise IntegrityError("decoded PartOut.csv is empty")
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    reader = csv.DictReader(lines, delimiter=delimiter)
    if not reader.fieldnames:
        raise IntegrityError("decoded PartOut.csv has no header")
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, raw in enumerate(reader):
        try:
            idp = _integer(raw.get("Idp"), f"PartOut row {index}.Idp")
            part_out = _integer(raw.get("PartOut"), f"PartOut row {index}.PartOut")
            motive_code = _integer(raw.get("Motive"), f"PartOut row {index}.Motive")
            position = [
                _finite(raw.get(f"Pos.{axis} [m]"), f"PartOut row {index}.Pos.{axis}")
                for axis in "xyz"
            ]
            density = _finite(raw.get("Rhop [kg/m^3]"), f"PartOut row {index}.Rhop")
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrityError(f"PartOut row {index} is malformed") from exc
        if idp < 0 or idp >= initial_particles:
            raise IntegrityError(f"PartOut Idp {idp} is outside the initial identity range")
        if idp in seen:
            raise IntegrityError(f"PartOut contains duplicate Idp {idp}")
        if part_out < 1 or motive_code not in MOTIVES:
            raise IntegrityError(f"PartOut row {index} has invalid PartOut/Motive")
        seen.add(idp)
        rows.append(
            {
                "idp": idp,
                "part_out": part_out,
                "motive_code": motive_code,
                "motive": MOTIVES[motive_code],
                "position_m": position,
                "rhop_kg_m3": density,
            }
        )
    if not rows:
        raise IntegrityError("PartOut.csv has no native exclusion records")
    return rows


def _validate_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = read_json(path, "native integrity manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise IntegrityError(f"unsupported native integrity manifest schema: {manifest.get('schema')!r}")
    for key in ("family_id", "case_id", "upstream_case_id", "solver_root", "gencase_root", "expected"):
        if key not in manifest:
            raise IntegrityError(f"manifest lacks {key}")
    expected = manifest["expected"]
    if not isinstance(expected, Mapping):
        raise IntegrityError("manifest expected section is not an object")
    for key in ("initial_particles", "excluded_particles", "minimum_time_end_s"):
        if key not in expected:
            raise IntegrityError(f"manifest expected section lacks {key}")
    return manifest, dict(expected)


def audit(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest_path = regular(manifest_path, "native integrity manifest")
    manifest, expected = _validate_manifest(manifest_path)
    family_id = str(manifest["family_id"])
    case_id = str(manifest["case_id"])
    upstream_case_id = str(manifest["upstream_case_id"])
    source = manifest.get("source")
    if not isinstance(source, Mapping):
        raise IntegrityError("manifest source section is missing")

    source_bindings: dict[str, dict[str, Any]] = {}
    source_paths: dict[str, Path] = {}
    for key in (
        "solver_receipt",
        "gencase_receipt",
        "generated_xml",
        "source_definition",
        "runparts",
        "run_out",
        "raw_partout",
        "part_info",
        "partvtk",
        "dsph_config",
    ):
        value = source.get(key)
        if not isinstance(value, Mapping):
            raise IntegrityError(f"manifest source lacks {key}")
        path, result = binding(value, key, reject_trajectory=key not in {"raw_partout"})
        source_paths[key] = path
        source_bindings[key] = result

    solver_root = Path(str(manifest["solver_root"])).expanduser().resolve()
    gencase_root = Path(str(manifest["gencase_root"])).expanduser().resolve()
    data_root = solver_root / "data"
    if not data_root.is_dir() or not data_root.resolve().is_relative_to(solver_root):
        raise IntegrityError(f"solver data root is missing or escapes solver root: {data_root}")
    if source_paths["raw_partout"].parent != data_root:
        raise IntegrityError("raw PartOut is not under solver data root")
    if source_paths["raw_partout"].name != "PartOut_000.obi4":
        raise IntegrityError("native source must be PartOut_000.obi4")
    if source_paths["part_info"].parent != data_root:
        raise IntegrityError("PartInfo is not under solver data root")
    if source_paths["part_info"].name != "PartInfo.ibi4":
        raise IntegrityError("native metadata source must be PartInfo.ibi4")
    if source_paths["generated_xml"].parent != gencase_root:
        raise IntegrityError("generated XML is not under GenCase root")

    solver_receipt, solver_summary = _receipt_binding(
        source_paths["solver_receipt"],
        label="solver receipt",
        family_id=family_id,
        case_id=case_id,
        expected_output_root=solver_root,
    )
    gencase_receipt, gencase_summary = _receipt_binding(
        source_paths["gencase_receipt"],
        label="GenCase receipt",
        family_id=family_id,
        case_id=case_id,
        expected_output_root=gencase_root,
    )
    if solver_receipt.get("request", {}).get("upstream_case_id") not in (None, upstream_case_id):
        raise IntegrityError("solver receipt upstream case differs from manifest")
    if gencase_receipt.get("request", {}).get("upstream_case_id") not in (None, upstream_case_id):
        raise IntegrityError("GenCase receipt upstream case differs from manifest")

    runout = _read_runout(source_paths["run_out"])
    initial_particles = int(expected["initial_particles"])
    excluded_particles = int(expected["excluded_particles"])
    minimum_time_end_s = _finite(expected["minimum_time_end_s"], "minimum_time_end_s")
    if runout["initial_particles"] != initial_particles:
        raise IntegrityError("Run.out initial particle count differs from manifest")
    if runout["excluded_particles"] != excluded_particles:
        raise IntegrityError("Run.out excluded particle count differs from manifest")
    terminal_particle_out = runout["terminal_particle_out"]
    if terminal_particle_out["total_out"] != excluded_particles:
        raise IntegrityError("Run.out terminal particle-out total differs from manifest")
    if terminal_particle_out["current_particles"] != initial_particles - excluded_particles:
        raise IntegrityError("Run.out terminal current-particle count does not close the native ledger")
    runparts = _read_runparts(source_paths["runparts"], minimum_time_end_s=minimum_time_end_s)
    runparts_total_out = runparts["totals"]["NpOut"]
    if runparts_total_out > excluded_particles:
        raise IntegrityError("RunPARTs cumulative NpOut exceeds the Run.out native ledger")
    runparts_coverage = {
        "saved_runparts_total_out": runparts_total_out,
        "runout_terminal_total_out": excluded_particles,
        "terminal_records_after_last_saved_part": excluded_particles - runparts_total_out,
        "status": "complete_on_saved_rows"
        if runparts_total_out == excluded_particles
        else "terminal_runout_closes_unsaved_tail",
        "semantics": (
            "RunPARTs counters cover all native exclusions on saved rows"
            if runparts_total_out == excluded_particles
            else "RunPARTs counters cover saved rows; Run.out terminal ledger covers the post-save tail"
        ),
    }

    # The completed F1 routes have a fixed generated cohort.  Check the active
    # count continuity when the solver writes these standard columns, while
    # keeping the native exclusion ledger authoritative.
    last_runpart = runparts["rows"][-1]
    count_continuity: dict[str, Any] = {
        "initial_particles": initial_particles,
        "excluded_particles": excluded_particles,
        "expected_final_active_particles": initial_particles - excluded_particles,
    }
    for field in ("NpSave", "NpSim"):
        if field in last_runpart:
            count_continuity[field] = last_runpart[field]
            if last_runpart[field] != initial_particles - excluded_particles:
                raise IntegrityError(f"RunPARTs final {field} does not close initial minus exclusions")
    count_continuity["status"] = "verified"

    output = Path(output).expanduser().resolve()
    attempt_root = output.parent
    if not attempt_root.is_dir():
        raise IntegrityError(f"attempt root does not exist: {attempt_root}")
    csv_path = attempt_root / "PartOut.csv"
    resume_path = attempt_root / "PartOut-resume.csv"
    decoder_receipt_path = attempt_root / "partvtk-decode-receipt.json"
    for path in (csv_path, resume_path, decoder_receipt_path, output):
        if path.exists() or path.is_symlink():
            raise IntegrityError(f"refusing to overwrite output: {path}")

    partvtk = source_paths["partvtk"]
    command = [
        str(partvtk),
        "-dirdata",
        str(data_root),
        "-savecsv",
        str(csv_path),
        "-saveresume",
        str(resume_path),
        "-createdirs:1",
        "-csvsep:1",
    ]
    completed = subprocess.run(
        command,
        cwd=str(attempt_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise IntegrityError(
            f"official PartVTKOut returned {completed.returncode}: {completed.stderr[-2000:]}"
        )
    if not csv_path.is_file() or not resume_path.is_file():
        raise IntegrityError("official PartVTKOut did not produce CSV and resume outputs")
    rows = _read_partout_csv(csv_path, initial_particles=initial_particles)
    if len(rows) != excluded_particles:
        raise IntegrityError("decoded PartOut row count differs from manifest")

    part_times = {int(row["part"]): float(row["time_s"]) for row in runparts["rows"]}
    final_saved_part = int(runparts["rows"][-1]["part"])
    for row in rows:
        if row["part_out"] not in part_times and row["part_out"] != final_saved_part + 1:
            raise IntegrityError(f"PartOut Idp {row['idp']} references unknown Part {row['part_out']}")
        row["part_out_time_s"] = part_times.get(row["part_out"])
        row["part_out_time_semantics"] = (
            "saved native PartOut record time"
            if row["part_out"] in part_times
            else "terminal native exclusion after final saved Part; continuous exclusion time UNKNOWN"
        )
    motive_counts = {
        name: sum(row["motive"] == name for row in rows) for name in MOTIVES.values()
    }
    if runparts_total_out == excluded_particles:
        for code, field in RUNPART_FIELDS.items():
            if runparts["totals"][field] != motive_counts[MOTIVES[code]]:
                raise IntegrityError(f"decoded {MOTIVES[code]} count differs from RunPARTs")

    # Confirm immutable native sources did not change while the official
    # decoder ran.  This also makes the raw PartOut binding explicit.
    for key, path in source_paths.items():
        if key in {"runparts", "run_out", "raw_partout", "part_info", "solver_receipt", "gencase_receipt"}:
            if sha256(path) != source_bindings[key]["sha256"]:
                raise IntegrityError(f"native source changed during decode: {key}")

    decoder_receipt = {
        "schema": "ds-data-02.upstream-first.partvtk-decode-receipt.v1",
        "status": "completed",
        "returncode": completed.returncode,
        "command": command,
        "cwd": str(attempt_root),
        "source_raw_partout": source_bindings["raw_partout"],
        "source_solver_root": str(solver_root),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "outputs": {
            "csv": {"path": str(csv_path), "sha256": sha256(csv_path), "bytes": csv_path.stat().st_size},
            "resume": {"path": str(resume_path), "sha256": sha256(resume_path), "bytes": resume_path.stat().st_size},
        },
        "read_policy": {
            "trajectory_part_frames_opened": False,
            "h5_opened": False,
            "solver_started": False,
            "native_partout_decoder": True,
        },
    }
    atomic_json(decoder_receipt_path, decoder_receipt)

    saved_brackets = {
        str(row["idp"]): {
            "part_out": row["part_out"],
            "saved_time_s": row["part_out_time_s"],
            "event_time_semantics": row["part_out_time_semantics"],
        }
        for row in rows
    }
    evidence = {
        "schema": OUTPUT_SCHEMA,
        "status": "verified",
        "family_id": family_id,
        "case_id": case_id,
        "upstream_case_id": upstream_case_id,
        "reference_role": manifest.get("reference_role"),
        "solver_root": str(solver_root),
        "gencase_root": str(gencase_root),
        "source_hashes": {
            "solver_receipt_sha256": source_bindings["solver_receipt"]["sha256"],
            "gencase_receipt_sha256": source_bindings["gencase_receipt"]["sha256"],
            "generated_xml_sha256": source_bindings["generated_xml"]["sha256"],
            "source_definition_sha256": source_bindings["source_definition"]["sha256"],
            "runparts_sha256": source_bindings["runparts"]["sha256"],
            "run_out_sha256": source_bindings["run_out"]["sha256"],
            "raw_partout_sha256": source_bindings["raw_partout"]["sha256"],
            "part_info_sha256": source_bindings["part_info"]["sha256"],
            "partvtk_sha256": source_bindings["partvtk"]["sha256"],
            "dsph_config_sha256": source_bindings["dsph_config"]["sha256"],
        },
        "source_bindings": source_bindings,
        "receipts": {"solver": solver_summary, "gencase": gencase_summary},
        "native_time_record": {
            **{key: runparts[key] for key in ("strictly_increasing", "window_s", "part_count", "part_index_start", "part_index_end")},
            "required_window_s": [0.0, minimum_time_end_s],
        },
        "excluded_particle_records": {
            "present": True,
            "path": str(csv_path),
            "sha256": sha256(csv_path),
            "bytes": csv_path.stat().st_size,
            "format": "official PartVTKOut CSV",
            "record_count": len(rows),
            "raw_native_fields_retained": True,
        },
        "decoded_identity": {
            "status": "verified",
            "key": "Idp",
            "spatial_identity_verified": True,
            "identity_scope": "one native Idp row per PartOut record; excluded-record range only",
            "per_frame_identity_verified": False,
            "per_frame_identity_scope": "not assessed because Part_*.bi4 trajectory frames were not opened",
            "raw_native_fields_retained": True,
            "validity_semantics_retained": True,
            "id_count": len(rows),
            "id_unique": len({row["idp"] for row in rows}) == len(rows),
            "id_min": min(row["idp"] for row in rows),
            "id_max": max(row["idp"] for row in rows),
            "initial_id_range": [0, initial_particles - 1],
            "continuity": "each excluded Idp appears exactly once; unobserved Idp fate is not inferred",
        },
        "count_continuity": count_continuity,
        "excluded_particle_causes": {
            "motive_counts": motive_counts,
            "runparts_totals": runparts["totals"],
            "runout_counts": runout,
            "runparts_coverage": runparts_coverage,
            "cause_binding": (
                "PartOut Motive rows are authoritative for the complete native exclusion set"
                if runparts_total_out != excluded_particles
                else "PartOut Motive rows agree with complete RunPARTs native counters"
            ),
            "cause_semantics": "native numerical Motive/PartOut cause only",
        },
        "native_rows": rows,
        "saved_record_time_brackets_s": saved_brackets,
        "decoder": {
            "receipt": {
                "path": str(decoder_receipt_path),
                "sha256": sha256(decoder_receipt_path),
                "bytes": decoder_receipt_path.stat().st_size,
            },
            "command": command,
            "csv": {"path": str(csv_path), "sha256": sha256(csv_path), "bytes": csv_path.stat().st_size},
            "resume": {"path": str(resume_path), "sha256": sha256(resume_path), "bytes": resume_path.stat().st_size},
        },
        "read_policy": {
            "h5_opened": False,
            "trajectory_part_frames_opened": False,
            "solver_started": False,
            "raw_partout_preserved": True,
            "partout_decoder_used": True,
        },
        "qualification": {
            "native_identity": "SOURCE_CLOSED",
            "physical_fate": "UNKNOWN",
            "legal_outflow": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
    }
    atomic_json(output, evidence)
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = audit(args.manifest, args.output)
        print(json.dumps({"status": result["status"], "path": str(args.output)}, sort_keys=True))
        return 0
    except (OSError, IntegrityError, subprocess.SubprocessError) as exc:
        print(f"native-integrity: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

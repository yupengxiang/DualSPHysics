#!/usr/bin/env python3
"""Create an immutable omission-forensics sidecar for one completed Stage2 scan.

The sidecar joins the already-consumed typed scan with a fresh official
PartVTKOut decode and the native RunPARTs counters.  It deliberately keeps
physical fate and dynamical impact unknown: a native numerical exclusion is
an identity/accounting result, not evidence of physical spill.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from ds_data02_runtime_v2 import atomic_json


MOTIVES = {1: "position", 2: "density", 3: "movement"}
RUNPART_FIELDS = ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path) -> dict:
    path = Path(path)
    stat = path.stat()
    return {"path": str(path), "sha256": sha256(path), "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns}


def tree_bytes(root: Path) -> int:
    root = Path(root)
    return sum(path.stat().st_size for path in root.rglob("*")
               if path.is_file())


def command_value(command: list[str], flag: str) -> str:
    for index, value in enumerate(command[:-1]):
        if value == flag:
            return command[index + 1]
    raise ValueError(f"decoder command missing {flag}")


def receipt_input_hash(receipt: dict, path: Path, *, actual_sha256: str | None = None) -> str:
    key = str(Path(path))
    request = receipt.get("request", {})
    declared = request.get("input_sha256", {}).get(key)
    launch = receipt.get("input_hashes_at_launch", {}).get(key)
    finished = receipt.get("input_hashes_after_run", {}).get(key)
    if not declared or declared != launch or declared != finished:
        raise ValueError(f"receipt input hash is incomplete or changed: {key}")
    if actual_sha256 is not None and declared != actual_sha256:
        raise ValueError(f"receipt input hash does not match current source: {key}")
    return declared


def validate_scan_completion(scan: dict, scan_path: Path, trajectory_path: Path,
                             expected_trajectory_sha256: str) -> tuple[dict, Path]:
    receipt_path = scan_path.parent / "execution-receipt.json"
    if not receipt_path.is_file():
        raise ValueError("scientific scan completion receipt is missing")
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get("status") != "completed" or receipt.get("returncode") != 0 or
            receipt.get("output_root") != str(scan_path.parent)):
        raise ValueError("scientific scan completion receipt is not successful")
    command = receipt.get("command", [])
    if command_value(command, "--output") != str(scan_path):
        raise ValueError("scientific scan receipt output is not this scan")
    request_files = set(receipt.get("request", {}).get("input_files", []))
    if str(trajectory_path) not in request_files:
        raise ValueError("scientific scan receipt does not bind this trajectory")
    source_hash = receipt_input_hash(receipt, trajectory_path)
    if source_hash != expected_trajectory_sha256:
        raise ValueError("conversion and scientific scan trajectory hashes differ")
    return receipt, receipt_path


def validate_decoder_sources(decoder_receipt: dict, scan_path: Path,
                             runparts_path: Path, conversion_path: Path,
                             source_provenance: dict) -> None:
    request_files = set(decoder_receipt.get("request", {}).get("input_files", []))
    for path in (scan_path, runparts_path, conversion_path):
        if str(path) not in request_files:
            raise ValueError(f"decoder request does not bind source: {path}")
        receipt_input_hash(decoder_receipt, path, actual_sha256=sha256(path))
    for field in ("generated_xml", "solver_receipt", "gencase_receipt"):
        provenance = source_provenance.get(field)
        if not isinstance(provenance, dict) or not provenance.get("path"):
            raise ValueError(f"conversion source provenance missing {field}")
        path = Path(provenance["path"])
        if str(path) not in request_files:
            raise ValueError(f"decoder request does not bind provenance {field}")
        if provenance.get("sha256") != sha256(path):
            raise ValueError(f"conversion provenance hash changed for {field}")
        receipt_input_hash(decoder_receipt, path, actual_sha256=provenance["sha256"])


def read_partout(path: Path) -> list[dict]:
    rows = []
    with Path(path).open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError("PartOut header missing")
        required = {"Idp", "PartOut", "Motive", "Pos.x [m]", "Pos.y [m]",
                    "Pos.z [m]", "Rhop [kg/m^3]"}
        if not required <= set(name.strip() for name in reader.fieldnames):
            raise ValueError("PartOut header missing required fields")
        for raw in reader:
            row = {key.strip(): (value or "").strip() for key, value in raw.items()
                   if key and value is not None}
            try:
                idp = int(row["Idp"])
                part_out = int(row["PartOut"])
                motive_code = int(row["Motive"])
                position = [float(row[f"Pos.{axis} [m]"]) for axis in "xyz"]
                density = float(row["Rhop [kg/m^3]"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("invalid PartOut row") from error
            if motive_code not in MOTIVES or part_out < 1:
                raise ValueError("invalid PartOut motive or frame")
            if not all(math.isfinite(value) for value in (*position, density)):
                raise ValueError("nonfinite PartOut state")
            rows.append({"idp": idp, "part_out": part_out,
                         "motive_code": motive_code,
                         "motive": MOTIVES[motive_code],
                         "position_m": position,
                         "density_kg_m3": density})
    if not rows:
        raise ValueError("PartOut records missing")
    return rows


def read_runparts(path: Path) -> dict:
    # Official RunPARTs includes '# field: description' comments.
    lines = [line for line in Path(path).read_text().splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines, delimiter=";")
    required = {"Part", "TimeStep [s]", *RUNPART_FIELDS}
    if reader.fieldnames is None or not required <= set(reader.fieldnames):
        raise ValueError("native RunPARTs header missing")
    rows = []
    totals = {name: 0 for name in RUNPART_FIELDS}
    for raw in reader:
        try:
            part = int(raw["Part"].replace(",", ""))
            time_s = float(raw["TimeStep [s]"])
            counts = {name: int(raw[name].replace(",", ""))
                      for name in RUNPART_FIELDS}
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid native RunPARTs row") from error
        if part != len(rows) or not math.isfinite(time_s):
            raise ValueError("native PART sequence/time is incomplete")
        if rows and time_s <= rows[-1]["time_s"]:
            raise ValueError("native RunPARTs time is not increasing")
        if any(value < 0 for value in counts.values()) or counts["NpOut"] != sum(counts[name] for name in RUNPART_FIELDS[1:]):
            raise ValueError("invalid native exclusion counters")
        rows.append({"part": part, "time_s": time_s, **counts})
        for name, value in counts.items():
            totals[name] += value
    if not rows:
        raise ValueError("native RunPARTs records missing")
    return {"rows": rows, "totals": totals}


def _source_stat(scan: dict) -> dict:
    trajectory = Path(scan["trajectory"])
    stat = trajectory.stat()
    if stat.st_size != scan["source_bytes"] or stat.st_mtime_ns != scan["source_mtime_ns"]:
        raise ValueError("trajectory changed after scientific scan")
    return {"path": str(trajectory), "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns}


def reconcile(scan: dict, partout: list[dict], runparts: dict,
              conversion: dict, decoder_receipt: dict,
              scan_path: Path, partout_path: Path, runparts_path: Path,
              conversion_path: Path, decoder_receipt_path: Path) -> dict:
    if scan.get("schema") != "ds02.stage2.scientific-scan.v1":
        raise ValueError("unsupported scientific scan schema")
    if scan.get("scan_status") != "SCANNED" or scan.get("failures"):
        raise ValueError("scientific scan is not a clean completed scan")
    source_provenance = conversion.get("source_provenance", {})
    if conversion.get("conversion_status") != "completed":
        raise ValueError("conversion report is not completed")
    trajectory_path = Path(scan["trajectory"])
    output_hdf5 = Path(conversion.get("output_hdf5", ""))
    if output_hdf5 != trajectory_path:
        raise ValueError("conversion output_hdf5 does not equal scan trajectory")
    trajectory_sha256 = conversion.get("output_sha256")
    if (not isinstance(trajectory_sha256, str) or len(trajectory_sha256) != 64 or
            any(char not in "0123456789abcdef" for char in trajectory_sha256)):
        raise ValueError("conversion trajectory output_sha256 is invalid")
    scan_completion, scan_receipt_path = validate_scan_completion(
        scan, scan_path, trajectory_path, trajectory_sha256)
    trajectory = _source_stat(scan)
    trajectory["sha256"] = trajectory_sha256
    times = scan["time_s"]
    native_times = [row["time_s"] for row in runparts["rows"]]
    if len(times) != len(native_times):
        raise ValueError("native saved timeline length mismatch")
    max_time_delta = max(abs(float(a) - b) for a, b in zip(times, native_times))
    if max_time_delta > 1e-8 * max(1.0, max(float(times[-1]), native_times[-1])):
        raise ValueError("native saved time mismatch")

    missing = [record for record in scan["missing_id_records"]
               if record.get("type_code") == 3 and record.get("missing_at_final")]
    if len(missing) != scan["type_ledgers"]["fluid"]["missing_at_final"]:
        raise ValueError("typed final fluid omission ledger mismatch")
    typed_by_id = {}
    typed_keys = set()
    for record in missing:
        key = (int(record["zone"]), int(record["idp"]))
        if key in typed_keys:
            raise ValueError("duplicate typed omission identity")
        typed_keys.add(key)
        typed_by_id.setdefault(key[1], []).append(record)

    joined = []
    seen = set()
    for native in partout:
        matches = typed_by_id.get(native["idp"], [])
        if len(matches) != 1:
            raise ValueError("native Idp absent or ambiguous in typed fluid omissions")
        typed = matches[0]
        key = (int(typed["zone"]), int(typed["idp"]))
        if key in seen:
            raise ValueError("duplicate native omission identity")
        seen.add(key)
        if int(typed["first_missing_frame"]) != native["part_out"]:
            raise ValueError("native PartOut does not match typed first missing frame")
        if not 1 <= native["part_out"] < len(times):
            raise ValueError("native PartOut is outside the saved timeline")
        joined.append({
            "zone": key[0], "idp": key[1],
            "type_code": int(typed["type_code"]),
            "initial_mass_kg": typed["initial_mass_kg"],
            "first_missing_frame": int(typed["first_missing_frame"]),
            "first_missing_bracket_s": typed["first_missing_bracket_s"],
            "first_gap_previous_state": typed.get("first_gap_previous_state"),
            "last_known_frame": typed["last_known_frame"],
            "last_known_time_s": typed["last_known_time_s"],
            "last_known_position_m": typed["last_known_position_m"],
            "last_known_velocity_m_s": typed["last_known_velocity_m_s"],
            "last_known_density_kg_m3": typed["last_known_density_kg_m3"],
            "native_exit_cause": "NUMERICAL_" + native["motive"].upper() + "_EXCLUSION",
            "native_motive": native["motive"],
            "native_motive_code": native["motive_code"],
            "partvtkout_position_m": native["position_m"],
            "partvtkout_density_kg_m3": native["density_kg_m3"],
            "physical_fate": "UNKNOWN",
            "legal_outflow_proven": False,
        })
    if seen != typed_keys:
        raise ValueError("native exclusion set differs from typed fluid omission set")

    counts = {name: 0 for name in MOTIVES.values()}
    for row in joined:
        counts[row["native_motive"]] += 1
    expected_counts = {"position": runparts["totals"]["NpOutPos"],
                       "density": runparts["totals"]["NpOutRho"],
                       "movement": runparts["totals"]["NpOutMov"]}
    if runparts["totals"]["NpOut"] != len(joined) or counts != expected_counts:
        raise ValueError("PartOut and RunPARTs motive counts differ")

    lifecycle = scan["type_ledgers"]["fluid"]
    if any(lifecycle[name] for name in ("revived_unique_ids", "births_unique_ids", "initially_absent_count")):
        raise ValueError("fluid lifecycle contains births/revivals beyond initial cohort")
    decoder_status = decoder_receipt.get("status")
    if decoder_status != "completed" or decoder_receipt.get("returncode") != 0:
        raise ValueError("official PartVTKOut decoder receipt is not completed")
    decoder_command = decoder_receipt.get("command", [])
    decoder_output_root = Path(decoder_receipt.get("output_root", ""))
    if decoder_output_root != partout_path.parent or not decoder_output_root.is_dir():
        raise ValueError("PartVTKOut output root does not contain PartOut")
    request_command = decoder_receipt.get("request", {}).get("command", [])
    expanded_request_command = [arg.replace("{attempt_root}", str(decoder_output_root))
                                for arg in request_command]
    if expanded_request_command != decoder_command:
        raise ValueError("decoder receipt command differs from requested command")
    data_root = Path(source_provenance.get("data_root", ""))
    if not data_root.is_dir():
        raise ValueError("conversion source data_root is missing")
    if Path(command_value(decoder_command, "-dirdata")) != data_root:
        raise ValueError("PartVTKOut -dirdata does not equal conversion source data_root")
    if Path(command_value(decoder_command, "-savecsv")) != partout_path:
        raise ValueError("PartVTKOut -savecsv does not equal bound PartOut CSV")
    resume_path = Path(command_value(decoder_command, "-saveresume"))
    if resume_path.parent != decoder_output_root or not resume_path.is_file():
        raise ValueError("PartVTKOut resume output is outside decoder output root")
    if partout_path.parent != decoder_output_root or not partout_path.is_file():
        raise ValueError("PartOut CSV is outside decoder output root")
    receipt_bytes = decoder_receipt.get("bytes")
    payload_bytes = sum(path.stat().st_size for path in decoder_output_root.rglob("*")
                        if path.is_file() and path.name != "execution-receipt.json")
    if (not isinstance(receipt_bytes, int) or receipt_bytes < payload_bytes or
            payload_bytes <= 0):
        raise ValueError("PartOut CSV is not bound to decoder receipt output tree")
    if runparts_path.parent != data_root.parent:
        raise ValueError("RunPARTs is not from the decoder data root's solver_output")
    request_files = set(decoder_receipt.get("request", {}).get("input_files", []))
    raw_partout = [Path(path) for path in request_files
                   if Path(path).name == "PartOut_000.obi4"]
    if len(raw_partout) != 1 or raw_partout[0].parent != data_root:
        raise ValueError("decoder request raw PartOut source is not under data_root")
    validate_decoder_sources(decoder_receipt, scan_path, runparts_path,
                             conversion_path, source_provenance)
    partvtk_provenance = source_provenance.get("partvtk")
    decoder_binary = decoder_command[0] if decoder_command else None
    if not decoder_binary or not isinstance(partvtk_provenance, dict):
        raise ValueError("PartVTKOut binary provenance is missing")
    if (decoder_receipt.get("binary_sha256") != partvtk_provenance.get("sha256") or
            decoder_receipt.get("binary_sha256") != sha256(Path(decoder_binary))):
        raise ValueError("PartVTKOut binary hash does not match conversion provenance")
    solver_receipt_info = source_provenance.get("solver_receipt", {})
    solver_receipt_path = Path(solver_receipt_info.get("path", ""))
    solver_receipt = json.loads(solver_receipt_path.read_text())
    solver_root = Path(solver_receipt.get("output_root", ""))
    if data_root.parent != solver_root / "solver_output":
        raise ValueError("solver receipt output_root does not contain RunPARTs")
    return {
        "schema": "ds02.stage2.omission-forensics.v2",
        "status": "CAUSES_RECONCILED",
        "family_id": scan["family_id"],
        "physical_case_id": scan["physical_case_id"],
        "scan": binding(scan_path),
        "scan_completion": {
            "receipt": binding(scan_receipt_path),
            "trajectory_sha256_launch": scan_completion["input_hashes_at_launch"][str(trajectory_path)],
            "trajectory_sha256_end": scan_completion["input_hashes_after_run"][str(trajectory_path)],
        },
        "trajectory": {**trajectory,
                        "conversion_report_sha256": conversion.get("output_sha256"),
                        "conversion_report": binding(conversion_path)},
        "typed_identity": {
            "identity_key": scan.get("metadata", {}).get("identity_key"),
            "missing_fluid_count": len(missing),
            "missing_fluid_initial_mass_kg": sum(float(row["initial_mass_kg"]) for row in missing),
            "ids": [{"zone": int(row["zone"]), "idp": int(row["idp"]),
                     "first_missing_frame": int(row["first_missing_frame"])} for row in missing],
        },
        "native_decode": {
            "tool": "PartVTKOut",
            "binary": {"path": decoder_binary,
                       "sha256": decoder_receipt.get("binary_sha256")},
            "receipt": binding(decoder_receipt_path),
            "output_root": {"path": str(decoder_output_root),
                            "receipt_reported_bytes": receipt_bytes,
                            "payload_bytes": payload_bytes},
            "command": decoder_command,
            "partout": binding(partout_path),
            "runparts": binding(runparts_path),
            "runparts_row_count": len(runparts["rows"]),
            "runparts_totals": runparts["totals"],
            "max_saved_time_delta_s": max_time_delta,
        },
        "source_provenance": {
            "data_root": source_provenance.get("data_root"),
            "generated_xml": source_provenance.get("generated_xml"),
            "solver_receipt": source_provenance.get("solver_receipt"),
            "gencase_receipt": source_provenance.get("gencase_receipt"),
            "partvtk": source_provenance.get("partvtk"),
            "control_sha256": source_provenance.get("control_sha256"),
        },
        "excluded_particles": joined,
        "physical_fate": "UNKNOWN; native numerical exclusion is not proof of physical spill",
        "dynamical_impact": "NOT_ASSESSED; requires a paired reference or bounded domain-impact experiment",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--partout", type=Path, required=True)
    parser.add_argument("--runparts", type=Path, required=True)
    parser.add_argument("--conversion-report", type=Path, required=True)
    parser.add_argument("--decoder-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve existing sidecar: " + str(args.output))
    result = reconcile(json.loads(args.scan.read_text()), read_partout(args.partout),
                       read_runparts(args.runparts), json.loads(args.conversion_report.read_text()),
                       json.loads(args.decoder_receipt.read_text()), args.scan, args.partout,
                       args.runparts, args.conversion_report, args.decoder_receipt)
    atomic_json(args.output, result)
    print(json.dumps({"status": result["status"], "case": result["physical_case_id"],
                      "missing_fluid": result["typed_identity"]["missing_fluid_count"],
                      "motives": result["native_decode"]["runparts_totals"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

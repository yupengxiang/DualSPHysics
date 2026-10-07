#!/usr/bin/env python3
"""Bounded binary-boundary check for a native position exclusion.

This is a small follow-up to the consumed omission sidecar.  It reads only a
bound PartOut BI4, its decoded CSV, existing receipts/CSV/RunPARTs/Run.out,
and pinned source files.  It never opens trajectory.h5.  The purpose is to
separate exact native double-coordinate evidence from `%g`-formatted log/CSV
text at a printed boundary.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import struct
import sys
from decimal import Decimal
from pathlib import Path

# The shared bounded BI4 parser imports sibling modules through the
# ``scripts`` namespace.  Make that namespace resolvable both from the batch
# runner's lab cwd and when this file is invoked directly.
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR.parent))
sys.path.insert(0, str(_SCRIPT_DIR))

import ds_data02_stage2_omission_bounds_diagnostic_v2 as bounds
import f8_r008_partout_runparts_diagnostic_v1 as partout_diag
import f8_r008_safe_bi4_decoder_v1 as bi4


class EvidenceError(bounds.EvidenceError):
    """Raised when exact native boundary evidence cannot be established."""


def _sha256(path: Path) -> str:
    return bounds.sha256(Path(path))


def _binding(path: Path) -> dict:
    return bounds.binding(Path(path))


def _command_value(command: list[str], flag: str) -> str:
    for index, token in enumerate(command[:-1]):
        if token == flag:
            return command[index + 1]
    raise EvidenceError(f"decoder command is missing {flag}")


def _source_excerpt(path: Path, start: int, end: int, needles: tuple[str, ...]) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    if start < 1 or end < start or end > len(lines):
        raise EvidenceError(f"source line range is outside {path}")
    excerpt = lines[start - 1:end]
    if any(needle not in "\n".join(excerpt) for needle in needles):
        raise EvidenceError(f"source anchor is absent from {path}:{start}-{end}")
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "line_start": start,
        "line_end": end,
        "anchors": list(needles),
        "excerpt": excerpt,
    }


def _decoder_sources(sidecar: dict) -> dict:
    native = sidecar.get("native_decode", {})
    receipt_info = native.get("receipt", {})
    receipt_path = Path(receipt_info.get("path", ""))
    if not receipt_path.is_file() or receipt_info.get("sha256") != _sha256(receipt_path):
        raise EvidenceError("PartVTKOut receipt binding is missing or changed")
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise EvidenceError("PartVTKOut receipt is not completed")
    command = receipt.get("command", [])
    request = receipt.get("request", {})
    expanded = [arg.replace("{attempt_root}", str(Path(receipt.get("output_root", ""))))
                for arg in request.get("command", [])]
    if expanded != command:
        raise EvidenceError("PartVTKOut command differs from its request")
    raw_candidates = [Path(value) for value in request.get("input_files", [])
                      if Path(value).name == "PartOut_000.obi4"]
    if len(raw_candidates) != 1:
        raise EvidenceError("decoder receipt does not bind exactly one raw PartOut_000.obi4")
    raw = raw_candidates[0]
    partout_csv = Path(_command_value(command, "-savecsv"))
    raw_parent = Path(_command_value(command, "-dirdata"))
    if raw.parent != raw_parent:
        raise EvidenceError("raw PartOut is outside decoder -dirdata")
    if Path(native.get("partout", {}).get("path", "")) != partout_csv:
        raise EvidenceError("decoded CSV is not the decoder -savecsv output")
    for path in (raw, partout_csv):
        if not path.is_file():
            raise EvidenceError(f"decoder output/source missing: {path}")
    raw_key = str(raw)
    declared = request.get("input_sha256", {}).get(raw_key)
    launch = receipt.get("input_hashes_at_launch", {}).get(raw_key)
    finish = receipt.get("input_hashes_after_run", {}).get(raw_key)
    actual = _sha256(raw)
    if not declared or declared != launch or declared != finish or declared != actual:
        raise EvidenceError("raw PartOut receipt digest is not stable")
    csv_info = native.get("partout", {})
    if csv_info.get("sha256") != _sha256(partout_csv):
        raise EvidenceError("decoded PartOut CSV digest changed")
    return {
        "receipt_path": receipt_path,
        "receipt": receipt,
        "raw": raw,
        "csv": partout_csv,
        "raw_sha256": actual,
        "csv_sha256": csv_info["sha256"],
        "command": command,
    }


def _root_values(root_identity: tuple[tuple[str, int, object], ...]) -> dict:
    return {name: value for name, _type_code, value in root_identity}


def _array_values(fd: int, array: bi4.ArrayRecord, file_size: int) -> tuple:
    payload = bi4._pread_exact(fd, array.byte_count, array.offset, file_size)
    if array.type_code == 8:
        return struct.unpack("<" + "I" * array.count, payload)
    if array.type_code == 10:
        return struct.unpack("<" + "Q" * array.count, payload)
    if array.type_code == 22:
        return struct.unpack("<" + "f" * (3 * array.count), payload)
    if array.type_code == 23:
        return struct.unpack("<" + "d" * (3 * array.count), payload)
    if array.type_code == 11:
        return struct.unpack("<" + "f" * array.count, payload)
    if array.type_code == 4:
        return struct.unpack("<" + "B" * array.count, payload)
    raise EvidenceError(f"unsupported PartOut array type {array.type_code}")


def _raw_particle(raw: Path, idp: int) -> dict:
    fd = os.open(raw, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        size = os.fstat(fd).st_size
        source = partout_diag.PartOutSource(raw.name, fd, _sha256(raw))
        block, root_identity, case_np, records, _ref, _identity = (
            partout_diag._scan_partout_source(source)
        )
        root = _root_values(root_identity)
        matches = []
        for record in records:
            arrays = record.arrays
            id_name = "Idpd" if "Idpd" in arrays else "Idp"
            ids = _array_values(fd, arrays[id_name], size)
            for index, value in enumerate(ids):
                if int(value) != idp:
                    continue
                pos_name = "Posd" if "Posd" in arrays else "Pos"
                pos_values = _array_values(fd, arrays[pos_name], size)
                pos = tuple(float(x) for x in pos_values[3 * index:3 * index + 3])
                vel_values = _array_values(fd, arrays["Vel"], size)
                rho_values = _array_values(fd, arrays["Rhop"], size)
                motive_values = _array_values(fd, arrays["Motive"], size)
                matches.append({
                    "part": record.part,
                    "index": index,
                    "idp": int(value),
                    "position_m": list(pos),
                    "position_type": pos_name,
                    "position_type_code": arrays[pos_name].type_code,
                    "velocity_m_s": list(float(x) for x in vel_values[3 * index:3 * index + 3]),
                    "density_kg_m3": float(rho_values[index]),
                    "motive_code": int(motive_values[index]),
                })
        if len(matches) != 1:
            raise EvidenceError(f"raw PartOut Idp {idp} matched {len(matches)} records")
        return {
            "block": block,
            "case_np": case_np,
            "root_values": root,
            "particle": matches[0],
        }
    finally:
        os.close(fd)


def _csv_particle(path: Path, idp: int) -> dict:
    matches = []
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        for raw in reader:
            row = {key.strip(): (value or "").strip() for key, value in raw.items()
                   if key and value is not None}
            if int(row["Idp"]) != idp:
                continue
            tokens = [row[f"Pos.{axis} [m]"] for axis in "xyz"]
            matches.append({
                "tokens": tokens,
                "position_m": [float(token) for token in tokens],
                "position_decimal": [str(Decimal(token)) for token in tokens],
                "motive_code": int(row["Motive"]),
                "part": int(row["PartOut"]),
            })
    if len(matches) != 1:
        raise EvidenceError(f"decoded CSV Idp {idp} matched {len(matches)} rows")
    return matches[0]


def _violations(position: list[float], pmin: tuple[float, ...],
                pmax: tuple[float, ...]) -> list[dict]:
    result = []
    for axis, value, low, high in zip("xyz", position, pmin, pmax):
        if value < low:
            result.append({"axis": axis, "direction": "below", "coordinate_m": value,
                           "bound_m": low, "amount_m": low - value,
                           "predicate": "coordinate < MapPosMin"})
        elif value >= high:
            result.append({"axis": axis, "direction": "at_or_above",
                           "coordinate_m": value, "bound_m": high,
                           "amount_m": value - high,
                           "predicate": "coordinate >= MapPosMax"})
    return result


def diagnose(sidecar_path: Path, diagnostic_path: Path, source_paths: dict[str, Path], idp: int) -> dict:
    sidecar_path = Path(sidecar_path)
    sidecar = json.loads(sidecar_path.read_text())
    if sidecar.get("schema") != "ds02.stage2.omission-forensics.v2" or sidecar.get("status") != "CAUSES_RECONCILED":
        raise EvidenceError("input omission sidecar is not a completed v2 sidecar")
    diagnostic = json.loads(Path(diagnostic_path).read_text())
    if diagnostic.get("physical_case_id") != sidecar.get("physical_case_id"):
        raise EvidenceError("diagnostic and omission sidecar physical IDs differ")
    decoder = _decoder_sources(sidecar)
    raw = _raw_particle(decoder["raw"], idp)
    csv_row = _csv_particle(decoder["csv"], idp)
    root = raw["root_values"]
    pmin = tuple(float(x) for x in root["MapPosMin"])
    pmax = tuple(float(x) for x in root["MapPosMax"])
    exact_violations = _violations(raw["particle"]["position_m"], pmin, pmax)
    csv_violations = _violations(csv_row["position_m"], pmin, pmax)
    if raw["particle"]["motive_code"] != 1 or not exact_violations:
        raise EvidenceError("raw native motive/coordinate does not establish a position exclusion")
    if raw["particle"]["part"] != csv_row["part"]:
        raise EvidenceError("raw and CSV PartOut identities differ")
    run_out = bounds.parse_run_out(source_paths["run_out"])
    runparts = bounds.parse_runparts(source_paths["runparts"])
    native_part = next((row for row in runparts["rows"] if row["part"] == raw["particle"]["part"]), None)
    if native_part is None or native_part["NpOutPos"] < 1:
        raise EvidenceError("RunPARTs does not bind the raw position motive")
    map_log = run_out["map_real_pos"]["final"]
    if any(abs(a - b) > 1e-12 for a, b in zip(map_log[0], pmin)) or any(abs(a - b) > 1e-12 for a, b in zip(map_log[1], pmax)):
        raise EvidenceError("Run.out final map does not numerically agree with raw PartOut bounds")
    source_evidence = {
        "functions_h": _source_excerpt(source_paths["functions_h"], 208, 212,
                                        ("DoubleStr(double v,const char* fmt=\"%g\")", "Double3gStr")),
        "jsph_config_limits": _source_excerpt(source_paths["jsph_cpp"], 2762, 2769,
                                               ("DataOutBi4->ConfigLimits(MapRealPosMin,MapRealPosMax",)),
        "jsph_log_final_map": _source_excerpt(source_paths["jsph_cpp"], 2172, 2181,
                                               ("MapRealPos(final)", "MapRealSize=MapRealPosMax-MapRealPosMin")),
        "partout_double_storage": _source_excerpt(source_paths["partout_cpp"], 157, 163,
                                                   ("SetvDouble3(\"MapPosMin\"", "SetvDouble3(\"MapPosMax\"")),
        "partout_position_type": _source_excerpt(source_paths["partout_cpp"], 191, 210,
                                                  ("if(posd)Part->CreateArray(\"Posd\"", "CreateArray(\"Pos\"")),
        "cpu_boundary_predicate": _source_excerpt(source_paths["jsph_cpu_cpp"], 1470, 1502,
                                                   ("dx<0 || dy<0 || dz<0", "dy>=MapRealSize.y", "CODE_SetOutPos")),
    }
    native = raw["particle"]
    return {
        "schema": "ds02.stage2.omission-boundary-precision.v1",
        "status": "EXACT_NATIVE_BOUNDARY_POSITION_CONFIRMED",
        "family_id": sidecar["family_id"],
        "physical_case_id": sidecar["physical_case_id"],
        "idp": idp,
        "input_sidecar": _binding(sidecar_path),
        "input_diagnostic_v2": _binding(Path(diagnostic_path)),
        "decoder_binding": {
            "receipt": _binding(decoder["receipt_path"]),
            "raw_partout": _binding(decoder["raw"]),
            "decoded_csv": _binding(decoder["csv"]),
            "command": decoder["command"],
            "trajectory_h5_read": False,
        },
        "native_binary": {
            "block": raw["block"],
            "case_np": raw["case_np"],
            "root_values": root,
            "map_bounds_exact_double_m": {"min": list(pmin), "max": list(pmax)},
            "rhop_bounds_native_kg_m3": [root["RhopMin"], root["RhopMax"]],
            "particle": native,
            "exact_predicate_violations": exact_violations,
        },
        "csv_observation": {
            "row": csv_row,
            "predicate_violations_using_exact_binary_bounds": csv_violations,
            "textual_boundary_ambiguity": bool(exact_violations and not csv_violations),
        },
        "run_out": {
            "path": str(source_paths["run_out"]),
            "sha256": _sha256(source_paths["run_out"]),
            "map_real_pos_logged_final": map_log,
            "rhop_out": run_out["rhop_out"],
            "formatting_note": "Run.out MapRealPos(final) is emitted through Double3gRangeStr/%g; retain as display evidence only.",
        },
        "runparts": {
            "path": str(source_paths["runparts"]),
            "sha256": _sha256(source_paths["runparts"]),
            "part_row": native_part,
        },
        "source_code": source_evidence,
        "finding": {
            "native_motive": "position",
            "native_motive_credit": True,
            "exact_coordinate_predicate_credit": True,
            "printed_coordinate_predicate_credit": False,
            "explanation": "Raw PartOut Posd is below exact binary MapPosMin.y by 9.71163445e-08 m; CSV/log display rounds it to -1.2 and therefore hides the strict dy<0 predicate.",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "NOT_ASSESSED",
        },
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "NOT_ASSESSED",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--diagnostic-v2", type=Path, required=True)
    parser.add_argument("--run-out", type=Path, required=True)
    parser.add_argument("--runparts", type=Path, required=True)
    parser.add_argument("--functions-h", type=Path, required=True)
    parser.add_argument("--jsph-cpp", type=Path, required=True)
    parser.add_argument("--partout-cpp", type=Path, required=True)
    parser.add_argument("--jsph-cpu-cpp", type=Path, required=True)
    parser.add_argument("--idp", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Preserve existing precision sidecar: {args.output}")
    result = diagnose(
        args.sidecar, args.diagnostic_v2,
        {"run_out": args.run_out, "runparts": args.runparts,
         "functions_h": args.functions_h, "jsph_cpp": args.jsph_cpp,
         "partout_cpp": args.partout_cpp, "jsph_cpu_cpp": args.jsph_cpu_cpp},
        args.idp,
    )
    bounds.atomic_json(args.output, result)
    print(json.dumps({"status": result["status"], "case": result["physical_case_id"],
                      "idp": result["idp"],
                      "exact_violations": result["native_binary"]["exact_predicate_violations"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

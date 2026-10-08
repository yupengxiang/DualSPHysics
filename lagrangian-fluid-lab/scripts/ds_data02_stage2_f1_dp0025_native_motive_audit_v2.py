#!/usr/bin/env python3
"""Validate source-bound F1 DP0025 PartVTKOut outputs.

This is a post-decoder audit for the two already completed DP0025 solver
outputs (half-CFL and same-CFL).  It consumes only the guarded decoder
receipt, its small CSV/resume output, the native ``PartOut_000.obi4`` parent,
RunPARTs/Run.out, and the declared XML/solver/tool/config metadata.  It never
opens trajectory ``Part_*.bi4`` files, H5, or starts a solver.  The report
assigns native Motive counts and source-bound saved-time brackets; physical
fate, legal outflow, and dynamical impact remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1.dp0025.native-motive-audit-manifest.v1"
OUTPUT_SCHEMA = "ds02.stage2.f1.dp0025.native-motive-audit.v2"
MOTIVES = {1: "position", 2: "density", 3: "movement"}
RUNPART_FIELDS = {1: "NpOutPos", 2: "NpOutRho", 3: "NpOutMov"}
TOOL = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/"
    "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
)
CONFIG = TOOL.parent / "DsphConfig.xml"


class AuditError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if path.name.startswith("Part_") and path.suffix == ".bi4":
        raise AuditError(f"{label} attempts to read a trajectory Part_*.bi4: {path}")
    if not path.is_file():
        raise AuditError(f"{label} is missing: {path}")
    return path


def binding(path: Path, expected: dict[str, Any] | None, label: str) -> dict[str, Any]:
    path = require_file(path, label)
    digest = sha256(path)
    size = path.stat().st_size
    if expected:
        if expected.get("sha256") != digest:
            raise AuditError(f"{label} SHA differs: {path}")
        if "bytes" in expected and int(expected["bytes"]) != size:
            raise AuditError(f"{label} size differs: {path}")
    return {"path": str(path), "sha256": digest, "bytes": size}


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"{label} is not an object: {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
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


def flag_value(command: list[Any], flag: str, label: str) -> str:
    for index, value in enumerate(command[:-1]):
        if str(value) == flag:
            return str(command[index + 1])
    raise AuditError(f"{label} command lacks {flag}")


def expanded(command: list[Any], output_root: Path) -> list[str]:
    return [str(value).replace("{attempt_root}", str(output_root)) for value in command]


def stable_input(receipt: dict[str, Any], path: Path, label: str) -> dict[str, Any]:
    key = str(path.resolve())
    request = receipt.get("request", {})
    declared = request.get("input_sha256", {}).get(key)
    launch = receipt.get("input_hashes_at_launch", {}).get(key)
    finish = receipt.get("input_hashes_after_run", {}).get(key)
    if not declared or declared != launch or declared != finish:
        raise AuditError(f"{label} is not stable at decoder launch/end: {key}")
    return binding(path, {"sha256": declared, "bytes": path.stat().st_size}, label)


def _read_rows(csv_path: Path) -> list[dict[str, Any]]:
    lines = [line for line in csv_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise AuditError("decoded PartOut.csv is empty")
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    reader = csv.DictReader(lines, delimiter=delimiter)
    if not reader.fieldnames:
        raise AuditError("decoded PartOut.csv has no header")
    rows: list[dict[str, Any]] = []
    for raw in reader:
        try:
            idp = int(str(raw["Idp"]).strip())
            part = int(str(raw["PartOut"]).strip())
            motive_code = int(str(raw["Motive"]).strip())
            position = [float(str(raw[f"Pos.{axis} [m]"]).strip()) for axis in "xyz"]
            rhop = float(str(raw["Rhop [kg/m^3]"]).strip())
        except (KeyError, TypeError, ValueError) as exc:
            raise AuditError("decoded PartOut.csv contains an invalid native row") from exc
        if motive_code not in MOTIVES or part < 1:
            raise AuditError(f"decoded PartOut.csv contains invalid motive/PartOut for Idp {idp}")
        rows.append({
            "idp": idp,
            "part_out": part,
            "motive_code": motive_code,
            "motive": MOTIVES[motive_code],
            "position_m": position,
            "rhop_kg_m3": rhop,
        })
    if not rows or len({row["idp"] for row in rows}) != len(rows):
        raise AuditError("decoded PartOut.csv has no rows or duplicate Idp")
    return rows


def _read_runparts(path: Path) -> dict[str, Any]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines, delimiter=";")
    required = {"Part", "TimeStep [s]", "NpOut", *RUNPART_FIELDS.values()}
    if not reader.fieldnames or not required <= set(reader.fieldnames):
        raise AuditError("RunPARTs.csv lacks native exclusion counters")
    rows: list[dict[str, Any]] = []
    totals = {name: 0 for name in ("NpOut", *RUNPART_FIELDS.values())}
    for raw in reader:
        try:
            part = int(str(raw["Part"]).replace(",", ""))
            time_s = float(raw["TimeStep [s]"])
            counters = {
                name: int(str(raw[name]).replace(",", ""))
                for name in totals
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise AuditError("RunPARTs.csv contains invalid counters") from exc
        if part != len(rows) or (rows and time_s <= rows[-1]["time_s"]):
            raise AuditError("RunPARTs.csv Part/time sequence is not increasing")
        if any(value < 0 for value in counters.values()):
            raise AuditError("RunPARTs.csv contains negative exclusion counters")
        if counters["NpOut"] != sum(counters[name] for name in RUNPART_FIELDS.values()):
            raise AuditError("RunPARTs.csv motive counters do not sum to NpOut")
        rows.append({"part": part, "time_s": time_s, **counters})
        for key, value in counters.items():
            totals[key] += value
    if not rows:
        raise AuditError("RunPARTs.csv has no saved rows")
    return {"rows": rows, "totals": totals}


def _runout_counts(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    def extract(pattern: str, label: str) -> int:
        match = re.search(pattern, text)
        if not match:
            raise AuditError(f"Run.out lacks {label}")
        return int(match.group(1).replace(",", ""))
    return {
        "initial_particles": extract(r"Particles of simulation \(initial\):\s*([0-9,]+)", "initial count"),
        "excluded_particles": extract(r"Excluded particles\.*:\s*([0-9,]+)", "excluded count"),
        "excluded_density": extract(r"Excluded particles due to Density\.*:\s*([0-9,]+)", "density count"),
    }


def _validate_case_binding(manifest_case: str, receipt: dict[str, Any]) -> dict[str, Any]:
    """Accept only an explicitly chained root-forward case alias.

    The v8 runtime receipt uses the root-forward case id while the immutable
    manifest uses the original case id.  The alias is valid only when the
    receipt's source request hash and the source request's own forward chain
    resolve exactly back to the manifest case.  A same-family or same-prefix
    case id alone is never sufficient.
    """
    request = receipt.get("request", {})
    actual_case = request.get("case_id")
    if actual_case == manifest_case:
        return {"mode": "exact", "manifest_case_id": manifest_case, "receipt_case_id": actual_case}
    provenance = request.get("root_forward_provenance", {})
    source_path_value = provenance.get("source_request")
    source_sha = provenance.get("source_request_sha256")
    if not isinstance(source_path_value, str) or not isinstance(source_sha, str):
        raise AuditError("receipt case alias lacks root-forward source request provenance")
    source_path = require_file(source_path_value, "root-forward source request")
    if sha256(source_path) != source_sha:
        raise AuditError("root-forward source request SHA differs")
    source_request = read_json(source_path, "root-forward source request")
    if source_request.get("family_id") != request.get("family_id"):
        raise AuditError("receipt case alias changes family across root-forward source request")
    source_provenance = source_request.get("root_forward_provenance", {})
    origin_path_value = source_provenance.get("source_request")
    origin_sha = source_provenance.get("source_request_sha256")
    if not isinstance(origin_path_value, str) or not isinstance(origin_sha, str):
        raise AuditError("root-forward source request lacks original request provenance")
    origin_path = require_file(origin_path_value, "original native motive request")
    if sha256(origin_path) != origin_sha:
        raise AuditError("original native motive request SHA differs")
    origin_request = read_json(origin_path, "original native motive request")
    if origin_request.get("case_id") != manifest_case:
        raise AuditError("root-forward alias does not resolve to manifest case")
    return {
        "mode": "explicit_root_forward_alias",
        "manifest_case_id": manifest_case,
        "receipt_case_id": actual_case,
        "root_forward_source_request": binding(source_path, {"sha256": source_sha}, "root-forward source request"),
        "original_request": binding(origin_path, {"sha256": origin_sha}, "original native motive request"),
        "root_forward_source_case_id": source_request.get("case_id"),
    }


def audit(manifest_path: Path, receipt_path: Path, output: Path) -> dict[str, Any]:
    manifest_path = require_file(manifest_path, "F1 native motive manifest")
    manifest = read_json(manifest_path, "F1 native motive manifest")
    if manifest.get("schema") != SCHEMA:
        raise AuditError("unsupported F1 native motive manifest schema")
    receipt_path = require_file(receipt_path, "PartVTKOut execution receipt")
    receipt = read_json(receipt_path, "PartVTKOut execution receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise AuditError("PartVTKOut execution receipt is not completed code 0")
    case = manifest.get("case")
    if not isinstance(case, dict):
        raise AuditError("manifest case is missing")
    case_binding = _validate_case_binding(str(case.get("case_id")), receipt)
    if case_binding["mode"] == "explicit_root_forward_alias":
        for label in ("root-forward source request", "original native motive request"):
            stable_input(
                receipt,
                Path(case_binding["root_forward_source_request" if label.startswith("root") else "original_request"]["path"]),
                label,
            )
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if output_root != receipt_path.parent.resolve():
        raise AuditError("receipt output_root differs from receipt directory")
    request_command = receipt.get("request", {}).get("command", [])
    if not isinstance(request_command, list) or not request_command:
        raise AuditError("decoder request command is missing")
    expected_command = expanded(request_command, output_root)
    recorded_command = receipt.get("command")
    if recorded_command:
        command = [str(value) for value in recorded_command]
        if expected_command != command:
            raise AuditError("decoder receipt command differs from expanded request")
        command_source = "receipt.command"
    else:
        command = expected_command
        command_source = "receipt.request.command_expanded"
    if not command or Path(command[0]).resolve() != TOOL.resolve():
        raise AuditError("decoder does not invoke the bound official PartVTKOut binary as argv[0]")
    if any(value.startswith("-threads") for value in command):
        raise AuditError("PartVTKOut request contains unsupported -threads flag")
    data_root = Path(flag_value(command, "-dirdata", "decoder")).expanduser().resolve()
    csv_path = require_file(flag_value(command, "-savecsv", "decoder"), "decoded PartOut.csv")
    resume_path = require_file(flag_value(command, "-saveresume", "decoder"), "decoder resume.csv")
    if csv_path.parent != output_root or resume_path.parent != output_root:
        raise AuditError("decoder outputs are outside the guarded attempt root")
    source = manifest.get("source", {})
    scope = receipt.get("request", {}).get("native_scope", {})
    if scope.get("expected_excluded_count") != case.get("expected_excluded_count"):
        raise AuditError("decoder native scope count differs from manifest")
    for scope_key, source_key in (
        ("raw_partout", "raw_partout"), ("source_runparts", "runparts"),
        ("source_run_out", "run_out"), ("source_solver_receipt", "solver_receipt"),
    ):
        if scope.get(scope_key) != source.get(source_key, {}).get("path"):
            raise AuditError(f"decoder native scope {scope_key} differs from manifest source")
    if Path(str(source.get("raw_partout", {}).get("path", ""))).resolve().parent != data_root:
        raise AuditError("raw PartOut parent differs from decoder -dirdata")
    source_bindings: dict[str, Any] = {}
    source_key_map = {
        "raw_partout": "raw_partout",
        "runparts": "runparts",
        "run_out": "run_out",
        "solver_receipt": "solver_receipt",
        "solver_proof": "solver_proof",
        "generated_xml": "xml",
        "partvtk_binary": "tool",
        "dsph_config": "config",
        "prior_identity_report": "prior",
    }
    for key, manifest_key in source_key_map.items():
        row = source.get(manifest_key)
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise AuditError(f"manifest source binding lacks {manifest_key}")
        source_bindings[key] = stable_input(receipt, Path(row["path"]), key)
    if Path(source_bindings["partvtk_binary"]["path"]).resolve() != TOOL.resolve():
        raise AuditError("manifest PartVTKOut source differs from command")
    if Path(source_bindings["dsph_config"]["path"]).resolve() != CONFIG.resolve():
        raise AuditError("manifest DsphConfig source differs from official binary")
    if source_bindings["raw_partout"]["path"].split("/")[-1] != "PartOut_000.obi4":
        raise AuditError("manifest raw source is not PartOut_000.obi4")
    runparts = _read_runparts(Path(source_bindings["runparts"]["path"]))
    runout = _runout_counts(Path(source_bindings["run_out"]["path"]))
    rows = _read_rows(csv_path)
    expected_count = int(case.get("expected_excluded_count", -1))
    if len(rows) != expected_count or runout["excluded_particles"] != expected_count:
        raise AuditError("PartVTKOut rows disagree with Run.out/manifest excluded count")
    if runparts["totals"]["NpOut"] != expected_count:
        raise AuditError("PartVTKOut rows disagree with cumulative RunPARTs NpOut")
    motive_counts = {name: sum(row["motive"] == name for row in rows) for name in MOTIVES.values()}
    for code, field in RUNPART_FIELDS.items():
        if runparts["totals"][field] != motive_counts[MOTIVES[code]]:
            raise AuditError(f"PartVTKOut motive {MOTIVES[code]} disagrees with RunPARTs")
    expected_ids = case.get("expected_removed_ids")
    if expected_ids is not None and sorted(int(value) for value in expected_ids) != sorted(row["idp"] for row in rows):
        raise AuditError("PartVTKOut Idp set differs from manifest expected identity set")
    part_times = {row["part"]: row["time_s"] for row in runparts["rows"]}
    for row in rows:
        if row["part_out"] not in part_times:
            raise AuditError(f"PartVTKOut Idp {row['idp']} PartOut is outside RunPARTs")
    result = {
        "schema": OUTPUT_SCHEMA,
        "status": "COMPLETED_NATIVE_MOTIVE_AUDIT",
        "family_id": "F1",
        "case_id": case["case_id"],
        "decoder_request_case_id": receipt.get("request", {}).get("case_id"),
        "case_binding": case_binding,
        "physical_case_id": case["physical_case_id"],
        "expected_excluded_count": expected_count,
        "native_rows": rows,
        "motive_counts": motive_counts,
        "runparts_totals": runparts["totals"],
        "runout_counts": runout,
        "saved_record_time_brackets_s": {
            str(row["idp"]): {
                "part_out": row["part_out"],
                "saved_time_s": part_times[row["part_out"]],
                "event_time_semantics": "saved-record time only; continuous exclusion time UNKNOWN",
            }
            for row in rows
        },
        "source_bindings": source_bindings,
        "decoder": {
            "receipt": binding(receipt_path, None, "decoder receipt"),
            "command": command,
            "command_source": command_source,
            "csv": binding(csv_path, None, "decoded PartOut.csv"),
            "resume": binding(resume_path, None, "decoder resume.csv"),
            "data_root": str(data_root),
        },
        "read_policy": {
            "h5_opened": False,
            "trajectory_part_frames_opened": False,
            "solver_started": False,
            "raw_partout_only": True,
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
    atomic_json(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    audit(args.manifest, args.receipt, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

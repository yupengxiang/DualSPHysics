#!/usr/bin/env python3
"""Prepare and run the forward Stage2 native decoder configuration closure.

The historical 118-case native sidecars are immutable.  This forward-only
worker runs the official ``PartVTKOut_linux64`` once per exact CURRENT case,
using the already-produced ``PartOut_000.obi4`` as its only native particle
input, and compares the fresh CSV with the preserved decoder CSV.  The
request binds the same raw parent through ``PartOut_000.obi4``, RunPARTs,
Run.out, generated XML, solver/GenCase receipts, the official tool, and
``DsphConfig.xml``.  It never opens H5 or trajectory ``Part_*.bi4`` files and
it never modifies an old receipt or sidecar.

Preparation hashes only the selected small inputs.  The shared Stage2 v4
runtime owns launch/end hashing of exactly those inputs; the worker itself is
run only through that guard.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
LAB_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
VENV = LAB_ROOT / ".venv/bin/python"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
COVERAGE_DEFAULT = DATA_ROOT / "families/infra/STAGE2_OMISSION_COVERAGE_FORWARD/coverage-forward-v3-primary-001/omission-coverage-index-v3.json"
TOOL_DEFAULT = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
CONFIG_DEFAULT = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"
RUNTIME_V4_DEFAULT = SCRIPT.parent / "ds_data02_runtime_v4.py"
RUNTIME_V2_DEFAULT = SCRIPT.parent / "ds_data02_runtime_v2.py"
DISPATCH_V4_DEFAULT = SCRIPT.parent / "ds_data02_stage2_dispatch_v4.py"
STRICT_V4_DEFAULT = SCRIPT.parent / "ds_data02_strict_dispatch_v4.py"
OUTPUT_SCHEMA = "ds02.stage2.native-runtime-config-closure.v1"
MANIFEST_SCHEMA = "ds02.stage2.native-runtime-config-closure-manifest.v1"
REQUEST_CASE = "STAGE2_NATIVE_RUNTIME_CONFIG_CLOSURE_118_V1"
REQUEST_ATTEMPT = "native-runtime-config-closure-118-v1"
EXPECTED_FAMILIES = {"F2": 48, "F4": 22, "F6": 48}
NUMERIC_ABS_TOL = 1.0e-9


class ClosureError(RuntimeError):
    """Raised when a source-bound closure cannot be proven."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ClosureError(f"{label} is missing: {path}")
    return path


def require_dir(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ClosureError(f"{label} is missing: {path}")
    return path


def read_json(value: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClosureError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ClosureError(f"{label} is not a JSON object: {path}")
    return path, payload


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.resolve()
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


def actual_ref(value: str | Path, expected: str | None, label: str) -> dict[str, Any]:
    path = require_file(value, label)
    actual = sha256(path)
    if expected is not None and actual != str(expected):
        raise ClosureError(f"{label} digest differs: {path}; expected {expected}, got {actual}")
    return {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}


def source_ref(container: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    value = container.get(key)
    if not isinstance(value, dict) or not value.get("path"):
        raise ClosureError(f"{label} has no path reference")
    expected = value.get("sha256", value.get("expected_sha256"))
    if not isinstance(expected, str) or len(expected) != 64:
        raise ClosureError(f"{label} has no 64-character digest")
    return actual_ref(value["path"], expected, label)


def resolved_path(value: str | Path, label: str) -> Path:
    return require_file(value, label)


def assert_no_trajectory(path: Path, label: str) -> None:
    name = path.name
    if name == "trajectory.h5" or (name.startswith("Part_") and name.endswith(".bi4")):
        raise ClosureError(f"{label} unexpectedly includes scientific trajectory content: {path}")


def decoder_command(request: dict[str, Any], label: str) -> tuple[Path, Path, Path]:
    command = request.get("command")
    if not isinstance(command, list) or len(command) < 8:
        raise ClosureError(f"{label} decoder command is incomplete")
    if Path(str(command[0])).resolve() != TOOL_DEFAULT.resolve():
        raise ClosureError(f"{label} does not use the bound official PartVTKOut tool")
    if any(str(item).startswith("-threads") for item in command):
        raise ClosureError(f"{label} contains unsupported PartVTKOut threads flag")

    def flag(name: str) -> Path:
        try:
            index = command.index(name)
            return Path(str(command[index + 1])).expanduser().resolve()
        except (ValueError, IndexError) as exc:
            raise ClosureError(f"{label} command lacks {name}") from exc

    return Path(str(command[command.index("-dirdata") + 1])).expanduser().resolve(), flag("-savecsv"), flag("-saveresume")


def read_delimited(path: Path, label: str) -> tuple[list[str], list[list[str]]]:
    """Read native CSV without interpreting delimiter or trailing empty column."""
    with path.open("r", encoding="utf-8", newline="") as stream:
        lines = [line for line in stream if line.strip()]
    if not lines:
        raise ClosureError(f"{label} is empty: {path}")
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    rows = list(csv.reader(lines, delimiter=delimiter))
    header = [str(item).strip() for item in rows[0]]
    body = [[str(item).strip() for item in row] for row in rows[1:] if any(str(item).strip() for item in row)]
    return header, body


CSV_FIELDS = (
    "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "PartOut", "Motive", "Idp",
    "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]",
)
FLOAT_FIELDS = CSV_FIELDS[:3] + CSV_FIELDS[6:]


def canonical_rows(path: Path, label: str) -> dict[int, dict[str, Any]]:
    header, body = read_delimited(path, label)
    positions = {name: header.index(name) for name in CSV_FIELDS if name in header}
    missing = [name for name in CSV_FIELDS if name not in positions]
    if missing:
        raise ClosureError(f"{label} lacks CSV fields {missing}: {path}")
    result: dict[int, dict[str, Any]] = {}
    for ordinal, raw in enumerate(body):
        if len(raw) <= max(positions.values()):
            raise ClosureError(f"{label} row {ordinal} is short: {path}")
        try:
            row: dict[str, Any] = {
                "Idp": int(raw[positions["Idp"]]),
                "PartOut": int(raw[positions["PartOut"]]),
                "Motive": int(raw[positions["Motive"]]),
            }
            for name in FLOAT_FIELDS:
                value = float(raw[positions[name]])
                if not math.isfinite(value):
                    raise ValueError(name)
                row[name] = value
        except (TypeError, ValueError) as exc:
            raise ClosureError(f"{label} row {ordinal} has invalid numeric data") from exc
        if row["Idp"] in result:
            raise ClosureError(f"{label} has duplicate Idp {row['Idp']}")
        result[row["Idp"]] = row
    return result


def compare_rows(old_path: Path, fresh_path: Path, label: str) -> dict[str, Any]:
    old = canonical_rows(old_path, f"{label} preserved CSV")
    fresh = canonical_rows(fresh_path, f"{label} fresh CSV")
    old_ids = set(old)
    fresh_ids = set(fresh)
    if old_ids != fresh_ids:
        raise ClosureError(
            f"{label} Idp set differs: missing={sorted(old_ids - fresh_ids)[:10]}, "
            f"unexpected={sorted(fresh_ids - old_ids)[:10]}"
        )
    identity_mismatches: list[dict[str, Any]] = []
    numeric_mismatches: list[dict[str, Any]] = []
    max_abs: dict[str, float] = {name: 0.0 for name in FLOAT_FIELDS}
    for idp in sorted(old_ids):
        before, after = old[idp], fresh[idp]
        for name in ("PartOut", "Motive"):
            if before[name] != after[name]:
                identity_mismatches.append({"idp": idp, "field": name, "old": before[name], "fresh": after[name]})
        for name in FLOAT_FIELDS:
            delta = abs(float(before[name]) - float(after[name]))
            max_abs[name] = max(max_abs[name], delta)
            if delta > NUMERIC_ABS_TOL:
                numeric_mismatches.append({"idp": idp, "field": name, "old": before[name], "fresh": after[name], "abs_diff": delta})
    if identity_mismatches or numeric_mismatches:
        raise ClosureError(
            f"{label} semantic CSV mismatch: identities={len(identity_mismatches)}, "
            f"numeric={len(numeric_mismatches)}"
        )
    return {
        "status": "EXACT_SEMANTIC_MATCH",
        "row_count": len(old),
        "idp_set_sha256": hashlib.sha256("\n".join(str(value) for value in sorted(old)).encode("ascii")).hexdigest(),
        "numeric_abs_tolerance": NUMERIC_ABS_TOL,
        "max_abs_difference": max_abs,
        "identity_fields": ["Idp", "PartOut", "Motive"],
        "numeric_fields": list(FLOAT_FIELDS),
    }


def source_fallback(physical_id: str) -> dict[str, Any] | None:
    """Return the exact legacy F2-S1 source binding absent from coverage v3."""
    if physical_id != "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090":
        return None
    base = DATA_ROOT / "families/F2/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010"
    source_dir = base / "root-stage1-f2-f2_stage1_first48_expansion_rx056_ry014_fill080_rot090_dp010_spatial_reference_save010-full401-native-source801-qa809-root812"
    generated_dir = base / "root-stage1-f2-f2_stage1_first48_expansion_rx056_ry014_fill080_rot090_dp010_spatial_reference_save010-actual-gencase-source801-root804"
    return {
        "decoder_receipt": DATA_ROOT / "families/F2/STAGE2_F2_S1_EXCLUSIONS/decode-F2-S1-002/execution-receipt.json",
        "old_partout": DATA_ROOT / "families/F2/STAGE2_F2_S1_EXCLUSIONS/decode-F2-S1-002/PartOut.csv",
        "solver_receipt": source_dir / "execution-receipt.json",
        "generated_xml": generated_dir / "prepared/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010.xml",
        "gencase_receipt": generated_dir / "execution-receipt.json",
        "raw_root": source_dir / "solver_output/data",
        "legacy_evidence": DATA_ROOT / "families/F2/STAGE2_F2_S1_EXCLUSIONS/join-F2-S1-001/native-reconciliation.json",
    }


def source_case(row: dict[str, Any], index: int) -> dict[str, Any]:
    physical_id = str(row.get("physical_case_id", ""))
    family = str(row.get("family_id", ""))
    if family not in EXPECTED_FAMILIES or not physical_id:
        raise ClosureError(f"coverage row {index} has invalid family or physical identity")
    binding = row.get("cause", {}).get("native_evidence_bindings")
    fallback = source_fallback(physical_id)
    if fallback is not None:
        decoder_receipt_path = require_file(fallback["decoder_receipt"], f"{physical_id} legacy decoder receipt")
        old_partout_path = require_file(fallback["old_partout"], f"{physical_id} preserved decoder CSV")
        solver_receipt_path = require_file(fallback["solver_receipt"], f"{physical_id} source solver receipt")
        generated_xml_path = require_file(fallback["generated_xml"], f"{physical_id} source generated XML")
        gencase_receipt_path = require_file(fallback["gencase_receipt"], f"{physical_id} source GenCase receipt")
        gencase_evidence_path = gencase_receipt_path
        raw_root = require_dir(fallback["raw_root"], f"{physical_id} source raw root")
        legacy_evidence = actual_ref(fallback["legacy_evidence"], None, f"{physical_id} legacy native evidence")
        source_mode = "legacy_f2_s1_explicit_current_binding"
    else:
        if not isinstance(binding, dict):
            raise ClosureError(f"{physical_id} has no native evidence binding")
        decoder = binding.get("decoder", {})
        provenance = binding.get("source_provenance", {})
        decoder_receipt_ref = decoder.get("receipt")
        old_partout_ref = decoder.get("partout")
        solver_receipt_ref = provenance.get("solver_receipt")
        generated_xml_ref = provenance.get("generated_xml")
        gencase_receipt_ref = provenance.get("gencase_receipt")
        for value, label in ((decoder_receipt_ref, "decoder receipt"), (old_partout_ref, "preserved decoder CSV"),
                             (solver_receipt_ref, "source solver receipt"), (generated_xml_ref, "source generated XML"),
                             (gencase_receipt_ref, "source GenCase receipt")):
            if not isinstance(value, dict) or not value.get("path"):
                raise ClosureError(f"{physical_id} has no bound {label}")
        decoder_receipt_path = require_file(decoder_receipt_ref["path"], f"{physical_id} decoder receipt")
        old_partout_path = require_file(old_partout_ref["path"], f"{physical_id} preserved decoder CSV")
        solver_receipt_path = require_file(solver_receipt_ref["path"], f"{physical_id} source solver receipt")
        generated_xml_path = require_file(generated_xml_ref["path"], f"{physical_id} source generated XML")
        gencase_evidence_path = require_file(gencase_receipt_ref["path"], f"{physical_id} source GenCase evidence")
        gencase_evidence = read_json(gencase_evidence_path, f"{physical_id} GenCase evidence")[1]
        raw_execution = gencase_evidence.get("raw_execution_receipt")
        if gencase_evidence.get("schema") == "ds02.execution-receipt.v1":
            gencase_receipt_path = gencase_evidence_path
        elif isinstance(raw_execution, dict) and raw_execution.get("path"):
            gencase_receipt_path = require_file(raw_execution["path"], f"{physical_id} raw GenCase receipt")
            expected_raw_sha = raw_execution.get("sha256")
            if not isinstance(expected_raw_sha, str) or len(expected_raw_sha) != 64:
                raise ClosureError(f"{physical_id} raw GenCase receipt has no digest")
            if sha256(gencase_receipt_path) != expected_raw_sha:
                raise ClosureError(f"{physical_id} raw GenCase receipt digest differs")
        else:
            raise ClosureError(f"{physical_id} GenCase evidence has no completed raw execution receipt")
        raw_root = require_dir(row.get("current_identity", {}).get("raw_root", ""), f"{physical_id} source raw root")
        legacy_evidence = actual_ref(row.get("cause", {}).get("evidence", {}).get("path", ""), row.get("cause", {}).get("evidence", {}).get("sha256"), f"{physical_id} native cause evidence")
        source_mode = "coverage_v3_native_binding"

    decoder_receipt = read_json(decoder_receipt_path, f"{physical_id} decoder receipt")[1]
    if decoder_receipt.get("schema") != "ds02.execution-receipt.v1" or decoder_receipt.get("status") != "completed" or decoder_receipt.get("returncode") != 0:
        raise ClosureError(f"{physical_id} decoder receipt is not completed code 0")
    decoder_request = decoder_receipt.get("request", {})
    request_raw, _, _ = decoder_command(decoder_request, physical_id)
    receipt_command = decoder_receipt.get("command")
    if not isinstance(receipt_command, list):
        raise ClosureError(f"{physical_id} decoder receipt has no expanded command")
    raw_from_decoder, old_csv_from_decoder, _ = decoder_command({"command": receipt_command}, physical_id)
    if request_raw != raw_from_decoder or raw_from_decoder != raw_root.resolve() or old_csv_from_decoder != old_partout_path.resolve():
        raise ClosureError(f"{physical_id} old decoder receipt does not bind the exact raw root/CSV")
    if decoder_receipt.get("binary_sha256") not in (None, sha256(TOOL_DEFAULT)):
        raise ClosureError(f"{physical_id} decoder tool digest differs")
    if str(decoder_request.get("case_id", "")).startswith("STAGE2_") is False and fallback is not None:
        raise ClosureError(f"{physical_id} legacy decoder case identity is missing")

    solver = read_json(solver_receipt_path, f"{physical_id} source solver receipt")[1]
    if solver.get("schema") != "ds02.execution-receipt.v1" or solver.get("status") != "completed" or solver.get("returncode") != 0:
        raise ClosureError(f"{physical_id} source solver receipt is not completed code 0")
    solver_request = solver.get("request", {})
    if solver_request.get("family_id") != family:
        raise ClosureError(f"{physical_id} source solver receipt family differs")
    solver_physical = solver_request.get("physical_case_id")
    if solver_physical not in (None, physical_id):
        raise ClosureError(f"{physical_id} source solver receipt physical identity differs")
    if solver_physical is None and not solver_request.get("case_id"):
        raise ClosureError(f"{physical_id} source solver receipt lacks both physical and case identity")
    solver_command = solver_request.get("command", [])
    if not isinstance(solver_command, list) or len(solver_command) < 3:
        raise ClosureError(f"{physical_id} source solver command is incomplete")
    solver_prefix = Path(str(solver_command[1])).expanduser().resolve()
    if solver_prefix.with_suffix(".xml") != generated_xml_path.resolve():
        raise ClosureError(f"{physical_id} source XML differs from completed solver command")

    gencase_evidence_ref = actual_ref(gencase_evidence_path, None, f"{physical_id} GenCase evidence")
    gencase = read_json(gencase_receipt_path, f"{physical_id} GenCase receipt")[1]
    if gencase.get("schema") != "ds02.execution-receipt.v1" or gencase.get("status") != "completed" or gencase.get("returncode") != 0:
        raise ClosureError(f"{physical_id} GenCase receipt is not completed code 0")
    if gencase.get("request", {}).get("family_id") != family:
        raise ClosureError(f"{physical_id} GenCase receipt family differs")

    partout = require_file(raw_root / "PartOut_000.obi4", f"{physical_id} raw PartOut_000.obi4")
    runparts = require_file(raw_root.parent / "RunPARTs.csv", f"{physical_id} RunPARTs.csv")
    runout = require_file(raw_root.parent / "Run.out", f"{physical_id} Run.out")
    for path, label in ((partout, "raw PartOut"), (runparts, "RunPARTs"), (runout, "Run.out"),
                        (old_partout_path, "preserved PartOut CSV"), (decoder_receipt_path, "decoder receipt"),
                        (generated_xml_path, "generated XML"), (solver_receipt_path, "solver receipt"),
                        (gencase_receipt_path, "GenCase receipt")):
        assert_no_trajectory(path, f"{physical_id} {label}")

    # A source-parent check makes a same-ID file from another solver run fail
    # before any fresh decoder is allowed to claim a match.
    if runparts.parent != raw_root.parent or runout.parent != raw_root.parent:
        raise ClosureError(f"{physical_id} RunPARTs/Run.out do not share raw solver_output parent")

    refs = {
        "raw_partout": actual_ref(partout, None, f"{physical_id} raw PartOut_000.obi4"),
        "preserved_partout_csv": actual_ref(old_partout_path, None, f"{physical_id} preserved PartOut.csv"),
        "decoder_receipt": actual_ref(decoder_receipt_path, None, f"{physical_id} decoder receipt"),
        "runparts": actual_ref(runparts, None, f"{physical_id} RunPARTs.csv"),
        "runout": actual_ref(runout, None, f"{physical_id} Run.out"),
        "generated_xml": actual_ref(generated_xml_path, None, f"{physical_id} generated XML"),
        "solver_receipt": actual_ref(solver_receipt_path, None, f"{physical_id} solver receipt"),
        "gencase_receipt": actual_ref(gencase_receipt_path, None, f"{physical_id} GenCase receipt"),
        "gencase_evidence": gencase_evidence_ref,
    }
    scan = row.get("current_scan", {})
    scan_receipt = scan.get("execution_receipt")
    if not isinstance(scan_receipt, dict) or not scan_receipt.get("path"):
        raise ClosureError(f"{physical_id} has no current completed scan receipt binding")
    scan_receipt_ref = actual_ref(scan_receipt["path"], scan_receipt.get("sha256"), f"{physical_id} current scan receipt")
    return {
        "index": index,
        "family_id": family,
        "physical_case_id": physical_id,
        "source_mode": source_mode,
        "legacy_native_evidence": legacy_evidence,
        "current_scan": {
            "scan_status": scan.get("scan_status"),
            "frames": scan.get("frames"),
            "time_window_s": scan.get("time_window_s"),
            "execution_receipt": scan_receipt_ref,
            "fluid_missing_count": scan.get("fluid", {}).get("cumulative_unique_missing"),
        },
        "raw_root": str(raw_root),
        "sources": refs,
    }


def unique_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for value in paths:
        path = Path(value).expanduser().resolve()
        key = str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def prepare(coverage_path: Path, output_dir: Path, *, tool_path: Path = TOOL_DEFAULT,
            config_path: Path = CONFIG_DEFAULT, runtime_v4_path: Path = RUNTIME_V4_DEFAULT,
            runtime_v2_path: Path = RUNTIME_V2_DEFAULT, dispatch_path: Path = DISPATCH_V4_DEFAULT,
            strict_path: Path = STRICT_V4_DEFAULT) -> dict[str, Any]:
    coverage_path, coverage = read_json(coverage_path, "final immutable coverage-v3")
    if coverage.get("schema") != "ds02.stage2.omission-coverage-index.v3":
        raise ClosureError("coverage input must be omission-coverage-index.v3")
    rows = coverage.get("rows")
    if not isinstance(rows, list) or len(rows) != sum(EXPECTED_FAMILIES.values()):
        raise ClosureError("coverage input does not contain exactly 118 rows")
    counts = {family: 0 for family in EXPECTED_FAMILIES}
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        case = source_case(row, index)
        if case["physical_case_id"] in seen:
            raise ClosureError(f"coverage has duplicate physical case {case['physical_case_id']}")
        seen.add(case["physical_case_id"])
        counts[case["family_id"]] += 1
        cases.append(case)
    if counts != EXPECTED_FAMILIES:
        raise ClosureError(f"coverage family counts {counts} != {EXPECTED_FAMILIES}")
    tool = require_file(tool_path, "official PartVTKOut tool")
    config = require_file(config_path, "official DsphConfig.xml")
    runtime_v4 = require_file(runtime_v4_path, "Stage2 runtime v4")
    runtime_v2 = require_file(runtime_v2_path, "Stage2 runtime v2")
    dispatch = require_file(dispatch_path, "Stage2 dispatch v4")
    strict = require_file(strict_path, "Stage2 strict dispatch v4")
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "native-runtime-config-closure-manifest.json"
    request_path = output_dir / "native-runtime-config-closure-request.json"
    source_files: list[Path] = [SCRIPT, coverage_path, tool, config, runtime_v4, runtime_v2, dispatch, strict]
    for case in cases:
        source_files.extend(Path(ref["path"]) for ref in case["sources"].values())
        source_files.append(Path(case["legacy_native_evidence"]["path"]))
        scan_receipt = case["current_scan"].get("execution_receipt")
        if isinstance(scan_receipt, dict) and scan_receipt.get("path"):
            source_files.append(Path(str(scan_receipt["path"])))
    source_files = unique_paths(source_files)
    for path in source_files:
        assert_no_trajectory(path, "closure input")
    input_hashes = {str(path): sha256(path) for path in source_files}
    raw_bytes = sum(int(case["sources"]["raw_partout"]["bytes"]) for case in cases)
    preserved_bytes = sum(int(case["sources"]["preserved_partout_csv"]["bytes"]) for case in cases)
    output_estimate = max(128 * 1024 * 1024, preserved_bytes * 4 + len(cases) * 512 * 1024)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_RUNTIME_CONFIG_CLOSURE",
        "coverage": {"path": str(coverage_path), "sha256": sha256(coverage_path), "schema": coverage["schema"]},
        "selected_case_count": len(cases),
        "family_counts": counts,
        "official_runtime": {
            "partvtkout": {"path": str(tool), "sha256": sha256(tool), "bytes": tool.stat().st_size},
            "dsph_config": {"path": str(config), "sha256": sha256(config), "bytes": config.stat().st_size},
            "runtime_v4": {"path": str(runtime_v4), "sha256": sha256(runtime_v4), "bytes": runtime_v4.stat().st_size},
            "runtime_v2": {"path": str(runtime_v2), "sha256": sha256(runtime_v2), "bytes": runtime_v2.stat().st_size},
            "dispatch_v4": {"path": str(dispatch), "sha256": sha256(dispatch), "bytes": dispatch.stat().st_size},
            "strict_dispatch_v4": {"path": str(strict), "sha256": sha256(strict), "bytes": strict.stat().st_size},
        },
        "cases": cases,
        "guard_input_files": sorted(input_hashes),
        "input_sha256": dict(sorted(input_hashes.items())),
        "read_policy": {
            "h5_opened": False,
            "trajectory_part_content_opened": False,
            "partout_000_obi4_only": True,
            "scientific_scan_reexecuted": False,
            "solver_started": False,
            "cfd_or_model_run": False,
        },
        "closure_contract": {
            "official_decoder_command": [
                str(tool), "-dirdata", "<exact case raw solver_output/data>",
                "-savecsv", "<fresh attempt case output>/PartOut.csv",
                "-saveresume", "<fresh attempt case output>/resume.csv",
                "-createdirs:1", "-csvsep:1",
            ],
            "unsupported_threads_flag": False,
            "source_parent_identity": "raw PartOut_000.obi4, RunPARTs.csv, and Run.out share one solver_output parent; XML/solver/GenCase receipts are identity-bound",
            "comparison": "Idp set and PartOut/Motive exact; Pos/Vel/Rhop parsed semantic values within 1e-9 absolute tolerance",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        },
        "cost": {
            "cpu_threads": 1,
            "omp_threads": 1,
            "raw_partout_input_bytes": raw_bytes,
            "preserved_csv_input_bytes": preserved_bytes,
            "runtime_pre_post_hash_bytes_estimate": sum(input_hashes_path.stat().st_size for input_hashes_path in source_files) * 2,
            "estimated_output_bytes": output_estimate,
            "h5_bytes_read": 0,
            "trajectory_bytes_read": 0,
        },
        "preparation_policy": {
            "source_inputs_hashed": True,
            "h5_content_hashed": False,
            "old_receipts_modified": False,
            "old_sidecars_modified": False,
        },
    }
    atomic_json(manifest_path, manifest)
    manifest_sha = sha256(manifest_path)
    # The manifest itself is also part of the guarded source closure.
    input_hashes[str(manifest_path)] = manifest_sha
    command = [
        str(VENV), str(SCRIPT), "run", "--manifest", str(manifest_path),
        "--output", "{attempt_root}/native-runtime-config-closure.json",
    ]
    request = {
        "schema": "ds02.request.v1",
        "family_id": "infra",
        "case_id": REQUEST_CASE,
        "physical_case_id": "DS_DATA_02_HISTORICAL_118_NATIVE_CONFIG_CLOSURE",
        "attempt_id": REQUEST_ATTEMPT,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 3600,
        "estimated_storage_bytes": int(output_estimate),
        "cwd": str(SCRIPT.parent),
        "worktree_root": str(WORKTREE_ROOT),
        "command": command,
        "input_files": sorted(input_hashes),
        "input_sha256": dict(sorted(input_hashes.items())),
        "runtime_binding": manifest["official_runtime"]["runtime_v4"],
        "source_scope": {
            "coverage_v3": manifest["coverage"],
            "case_count": len(cases),
            "family_counts": counts,
            "raw_partout_only": True,
            "h5_or_trajectory_input_files": [],
            "official_tool": manifest["official_runtime"]["partvtkout"],
            "dsph_config": manifest["official_runtime"]["dsph_config"],
        },
        "source_read_cost": manifest["cost"],
        "canonical_ready": True,
        "launch_owner": "root",
        "primary_launch_owner": "root",
        "launch": True,
        "launch_allowed": True,
        "execution_allowed": True,
        "foreign_process_protection_required": True,
        "shared_lease_required": True,
        "solver_launch_forbidden": True,
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
        "request_note": (
            "Forward-only one-worker official PartVTKOut configuration closure for exact historical "
            "F2/F4/F6 118 cases. It binds each exact current raw PartOut_000.obi4, RunPARTs, Run.out, "
            "generated XML, completed solver/GenCase receipts, the official decoder, and DsphConfig.xml. "
            "The v4 runtime hashes all declared inputs before and after the worker. No H5, trajectory "
            "Part_*.bi4, scientific rescan, solver, CFD, or model is used; old evidence remains immutable."
        ),
    }
    atomic_json(request_path, request)
    report = {
        "schema": "ds02.stage2.native-runtime-config-closure-preparation.v1",
        "status": "CANONICAL_READY",
        "manifest": {"path": str(manifest_path), "sha256": manifest_sha},
        "request": {"path": str(request_path), "sha256": sha256(request_path), "case_id": REQUEST_CASE, "attempt_id": REQUEST_ATTEMPT},
        "case_count": len(cases),
        "family_counts": counts,
        "input_count": len(input_hashes),
        "read_policy": manifest["read_policy"],
    }
    report_path = output_dir / "native-runtime-config-closure-preparation.json"
    atomic_json(report_path, report)
    return report


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "native closure manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_RUNTIME_CONFIG_CLOSURE":
        raise ClosureError("native closure manifest is not prepared")
    tool = require_file(manifest["official_runtime"]["partvtkout"]["path"], "manifest official PartVTKOut")
    if sha256(tool) != manifest["official_runtime"]["partvtkout"]["sha256"]:
        raise ClosureError("official PartVTKOut changed after preparation")
    output = output.expanduser().resolve()
    if output.exists():
        raise ClosureError(f"refusing to overwrite closure output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for ordinal, case in enumerate(manifest.get("cases", [])):
        physical_id = str(case["physical_case_id"])
        raw_root = require_dir(case["raw_root"], f"{physical_id} raw root")
        sources = case["sources"]
        for name, label in (("raw_partout", "raw PartOut"), ("preserved_partout_csv", "preserved PartOut CSV"),
                            ("decoder_receipt", "decoder receipt"), ("runparts", "RunPARTs"), ("runout", "Run.out"),
                            ("generated_xml", "generated XML"), ("solver_receipt", "solver receipt"), ("gencase_receipt", "GenCase receipt")):
            ref = sources[name]
            path = require_file(ref["path"], f"{physical_id} {label}")
            if sha256(path) != ref["sha256"]:
                raise ClosureError(f"{physical_id} {label} changed after preparation")
        case_dir = output.parent / "cases" / f"{ordinal:03d}-{physical_id}"
        case_dir.mkdir(parents=True, exist_ok=False)
        fresh_csv = case_dir / "PartOut.csv"
        resume = case_dir / "resume.csv"
        stdout_path = case_dir / "stdout.log"
        stderr_path = case_dir / "stderr.log"
        command = [
            str(tool), "-dirdata", str(raw_root), "-savecsv", str(fresh_csv),
            "-saveresume", str(resume), "-createdirs:1", "-csvsep:1",
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=300)
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        if completed.returncode != 0:
            raise ClosureError(f"{physical_id} official PartVTKOut failed with {completed.returncode}")
        fresh_csv = require_file(fresh_csv, f"{physical_id} fresh PartOut.csv")
        resume = require_file(resume, f"{physical_id} fresh resume.csv")
        comparison = compare_rows(Path(sources["preserved_partout_csv"]["path"]), fresh_csv, physical_id)
        results.append({
            "ordinal": ordinal,
            "family_id": case["family_id"],
            "physical_case_id": physical_id,
            "status": "EXACT_SEMANTIC_MATCH",
            "source_mode": case["source_mode"],
            "source_parent": {
                "raw_root": str(raw_root),
                "raw_partout": sources["raw_partout"],
                "runparts": sources["runparts"],
                "runout": sources["runout"],
            },
            "preserved_decoder": {
                "receipt": sources["decoder_receipt"],
                "partout_csv": sources["preserved_partout_csv"],
            },
            "fresh_decoder": {
                "command": command,
                "partout_csv": {"path": str(fresh_csv), "sha256": sha256(fresh_csv), "bytes": fresh_csv.stat().st_size},
                "resume_csv": {"path": str(resume), "sha256": sha256(resume), "bytes": resume.stat().st_size},
                "stdout": {"path": str(stdout_path), "sha256": sha256(stdout_path), "bytes": stdout_path.stat().st_size},
                "stderr": {"path": str(stderr_path), "sha256": sha256(stderr_path), "bytes": stderr_path.stat().st_size},
            },
            "comparison": comparison,
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        })
    if len(results) != 118 or {row["physical_case_id"] for row in results} != {case["physical_case_id"] for case in manifest["cases"]}:
        raise ClosureError("native closure did not produce exact 118-case union")
    result = {
        "schema": OUTPUT_SCHEMA,
        "status": "completed",
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "case_count": len(results),
        "family_counts": {family: sum(row["family_id"] == family for row in results) for family in EXPECTED_FAMILIES},
        "cases": results,
        "source_policy": {
            "h5_opened": False,
            "trajectory_part_content_opened": False,
            "official_partvtkout_started": True,
            "old_receipts_modified": False,
            "old_sidecars_modified": False,
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "qualification": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
    }
    atomic_json(output, result)
    return result


def validate(manifest_path: Path, output_path: Path, receipt_path: Path) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "native closure manifest")
    output_path, result = read_json(output_path, "native closure output")
    receipt_path, receipt = read_json(receipt_path, "native closure execution receipt")
    if manifest.get("schema") != MANIFEST_SCHEMA or result.get("schema") != OUTPUT_SCHEMA:
        raise ClosureError("native closure schema mismatch")
    if result.get("status") != "completed" or receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ClosureError("native closure output/receipt is not completed code 0")
    runtime = manifest["official_runtime"]["runtime_v4"]
    if receipt.get("runner_source") != runtime["path"] or receipt.get("runner_sha256") != runtime["sha256"]:
        raise ClosureError("execution receipt is not from bound Stage2 v4 runtime")
    request = receipt.get("request", {})
    expected_files = set(str(Path(path).resolve()) for path in manifest.get("guard_input_files", []))
    expected_files.add(str(manifest_path.resolve()))
    input_files = {str(Path(path).resolve()) for path in request.get("input_files", [])}
    declared = request.get("input_sha256", {})
    launch = receipt.get("input_hashes_at_launch", {})
    finish = receipt.get("input_hashes_after_run", {})
    if not expected_files <= input_files:
        raise ClosureError("runtime request omits a closure input")
    for key in expected_files:
        if not declared.get(key) or launch.get(key) != declared.get(key) or finish.get(key) != declared.get(key):
            raise ClosureError(f"runtime receipt lacks stable source binding: {key}")
    if int(result.get("case_count", -1)) != 118 or len(result.get("cases", [])) != 118:
        raise ClosureError("native closure output is not exactly 118 cases")
    if any(row.get("status") != "EXACT_SEMANTIC_MATCH" for row in result["cases"]):
        raise ClosureError("native closure contains a non-matching case")
    checked = {
        "schema": "ds02.stage2.native-runtime-config-closure-validation.v1",
        "status": "completed",
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "output": {"path": str(output_path), "sha256": sha256(output_path)},
        "execution_receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path)},
        "stable_input_binding": True,
        "case_count": 118,
        "qualification": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
    }
    checked_path = output_path.parent / "native-runtime-config-closure-validation.json"
    atomic_json(checked_path, checked)
    return checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--coverage", type=Path, default=COVERAGE_DEFAULT)
    prepare_parser.add_argument("--output-dir", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--manifest", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--manifest", type=Path, required=True)
    validate_parser.add_argument("--output", type=Path, required=True)
    validate_parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare(args.coverage, args.output_dir)
        elif args.action == "run":
            result = run(args.manifest, args.output)
        else:
            result = validate(args.manifest, args.output, args.receipt)
    except ClosureError as exc:
        raise SystemExit(f"ClosureError: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

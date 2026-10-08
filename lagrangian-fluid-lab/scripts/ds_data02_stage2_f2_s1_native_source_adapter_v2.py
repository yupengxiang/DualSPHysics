#!/usr/bin/env python3
"""Close the one F2-S1 native-source gap with a forward-only v2 adapter.

The historical all-case audit intentionally left ``F2/scan-F2-S1-001``
source-incomplete because its original PartVTKOut receipt did not name the
typed conversion report.  This adapter joins the already completed, small
V37 converter report to the original producer conversion report, CURRENT
scientific scan, official PartVTKOut CSV/receipt, and the same-solver
RunPARTs/Run.out/XML receipts.

The adapter reads JSON/CSV/XML and the 1.3 KiB ``PartOut_000.obi4`` only for
its guarded digest.  It never opens ``trajectory.h5`` or any ``Part_*.bi4``
frame and never launches a decoder, solver, CFD, or model.  The root-049
typed HDF5 output is metadata-only: its path and producer digest are recorded,
but the HDF5 is deliberately not opened.  The root-049 native receipt and
typed-only owner report are content-bound separately from the relocated
converter report.  Native identity/MK credit is therefore limited to the
three official PartVTKOut rows.  Converter implementation, physical fate,
legal outflow, continuous event time, QI/QN/QE, and dynamics remain UNKNOWN.

This is a new forward version.  It does not alter the consumed V1/V2/V37
reports or receipts.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


MANIFEST_SCHEMA = "ds02.stage2.f2-s1-native-source-adapter-manifest.v2"
OUTPUT_SCHEMA = "ds02.stage2.f2-s1-native-source-adapter.v2"
SCHEMA = "ds02.stage2.f2-s1-native-source-adapter-request.v2"
MOTIVES = {1: "position", 2: "density", 3: "movement"}
RUNPART_FIELDS = ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")
FLOAT_TOL = 2.0e-12
RAW_TREE_SHA256 = "08b0f5bef680bffc6bd0af05c81444340da6877eff403e318008994a56e4d0cd"
EXPECTED_IDPS = (397194, 403829, 404024)
EXPECTED_BLOCKS = (
    {"begin": 0, "count": 69405, "mk": 18, "mkfluid": None, "tag": "fixed", "type": 0},
    {"begin": 69405, "count": 303435, "mk": 19, "mkfluid": None, "tag": "fixed", "type": 0},
    {"begin": 372840, "count": 24150, "mk": 17, "mkfluid": None, "tag": "moving", "type": 1},
    {"begin": 396990, "count": 7038, "mk": 1, "mkfluid": 0, "tag": "fluid", "type": 3},
    {"begin": 404028, "count": 7038, "mk": 2, "mkfluid": 1, "tag": "fluid", "type": 3},
    {"begin": 411066, "count": 7038, "mk": 3, "mkfluid": 2, "tag": "fluid", "type": 3},
)


class AdapterError(ValueError):
    """Raised when the exact F2-S1 source contract is not closed."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _reject_forbidden(path: Path, label: str) -> None:
    name = path.name
    if name == "trajectory.h5" or (name.startswith("Part_") and name.endswith(".bi4")):
        raise AdapterError(f"{label} would open forbidden trajectory content: {path}")


def bind(value: dict[str, Any], label: str, *, allow_raw_partout: bool = False) -> tuple[Path, dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise AdapterError(f"{label} lacks a path binding")
    path = Path(value["path"]).expanduser().resolve()
    if not allow_raw_partout:
        _reject_forbidden(path, label)
    if not path.is_file():
        raise AdapterError(f"{label} is missing: {path}")
    actual = sha256(path)
    expected = value.get("sha256")
    if not isinstance(expected, str) or actual != expected:
        raise AdapterError(f"{label} digest differs: expected {expected}, got {actual}")
    result = {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}
    return path, result


def read_json_binding(value: dict[str, Any], label: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path, binding = bind(value, label)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise AdapterError(f"{label} is not a JSON object: {path}")
    return path, data, binding


def _receipt_status(receipt: dict[str, Any], label: str) -> None:
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise AdapterError(f"{label} is not a completed zero-return receipt")


def _command_value(command: list[Any], flag: str) -> str:
    if not isinstance(command, list):
        raise AdapterError(f"decoder command is missing {flag}")
    for index, value in enumerate(command[:-1]):
        if str(value) == flag:
            return str(command[index + 1])
    raise AdapterError(f"decoder command is missing {flag}")


def _stable_receipt_input(receipt: dict[str, Any], path: Path, label: str) -> str:
    key = str(path.resolve())
    request = receipt.get("request", {})
    declared = request.get("input_sha256", {}).get(key)
    launch = receipt.get("input_hashes_at_launch", {}).get(key)
    finish = receipt.get("input_hashes_after_run", {}).get(key)
    if not declared or declared != launch or declared != finish:
        raise AdapterError(f"{label} does not have stable launch/end hash: {key}")
    return str(declared)


def _same_ref(actual: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    if _canonical(actual.get("path", "")) != _canonical(expected.get("path", "")):
        raise AdapterError(f"{label} path differs")
    if actual.get("sha256") != expected.get("sha256"):
        raise AdapterError(f"{label} digest differs")


def _typed_blocks(report: dict[str, Any], label: str) -> tuple[list[dict[str, Any]], float, float]:
    typed = report.get("typed_identity")
    if not isinstance(typed, dict) or typed.get("key") != "(Zone,Idp)":
        raise AdapterError(f"{label} typed identity key is not (Zone,Idp)")
    raw_blocks = typed.get("blocks")
    if not isinstance(raw_blocks, list):
        raise AdapterError(f"{label} typed blocks are missing")
    blocks: list[dict[str, Any]] = []
    for row in raw_blocks:
        if not isinstance(row, dict):
            raise AdapterError(f"{label} typed block is not an object")
        try:
            normalized = {
                "begin": int(row["begin"]), "count": int(row["count"]),
                "mk": int(row["mk"]), "mkfluid": row.get("mkfluid"),
                "tag": row.get("tag"), "type": int(row["type"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise AdapterError(f"{label} typed block is malformed") from exc
        if normalized["begin"] < 0 or normalized["count"] <= 0:
            raise AdapterError(f"{label} typed block range is invalid")
        blocks.append(normalized)
    blocks.sort(key=lambda row: (row["begin"], row["mk"], row["type"]))
    if tuple(blocks) != EXPECTED_BLOCKS:
        raise AdapterError(f"{label} typed blocks differ from source-bound V37 blocks")
    ledger = typed.get("initial_exclusion_ledger")
    if not isinstance(ledger, dict) or int(ledger.get("count", -1)) != 0:
        raise AdapterError(f"{label} initial conversion exclusion ledger is not zero")
    constants = report.get("hash_scopes", {}).get("numerical_parameters", {}).get("decoder_header_constants", {})
    try:
        mass_fluid = float(constants["MassFluid"])
        mass_bound = float(constants["MassBound"])
        dp = float(constants["Dp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AdapterError(f"{label} decoder header constants are incomplete") from exc
    if not all(math.isfinite(value) and value > 0 for value in (mass_fluid, mass_bound, dp)):
        raise AdapterError(f"{label} decoder header constants are invalid")
    if not math.isclose(mass_fluid, mass_bound, rel_tol=0.0, abs_tol=1.0e-12) or not math.isclose(dp, 0.01, rel_tol=0.0, abs_tol=1.0e-12):
        raise AdapterError(f"{label} decoder header constants differ from F2-S1 source")
    return blocks, mass_fluid, mass_bound


def _read_partout(path: Path) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise AdapterError("official PartVTKOut CSV is empty")
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(lines, delimiter=delimiter)
    if not reader.fieldnames:
        raise AdapterError("official PartVTKOut CSV has no header")
    for raw in reader:
        try:
            row = {
                "idp": int(str(raw["Idp"]).strip()),
                "part_out": int(str(raw["PartOut"]).strip()),
                "motive_code": int(str(raw["Motive"]).strip()),
                "position_m": [float(str(raw[f"Pos.{axis} [m]"]).strip()) for axis in "xyz"],
                "density_kg_m3": float(str(raw["Rhop [kg/m^3]"]).strip()),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise AdapterError("official PartVTKOut CSV has an invalid row") from exc
        if row["motive_code"] not in MOTIVES or row["part_out"] < 1:
            raise AdapterError(f"official PartVTKOut CSV has an invalid native row: {row}")
        if not all(math.isfinite(value) for value in (*row["position_m"], row["density_kg_m3"])):
            raise AdapterError("official PartVTKOut CSV has non-finite values")
        rows.append(row)
    if len(rows) != len({row["idp"] for row in rows}):
        raise AdapterError("official PartVTKOut CSV contains duplicate Idp rows")
    return rows


def _read_runparts(path: Path) -> dict[str, int]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines, delimiter=";")
    if not reader.fieldnames or not set(("Part", "TimeStep [s]", *RUNPART_FIELDS)) <= set(reader.fieldnames):
        raise AdapterError("RunPARTs lacks required native fields")
    totals = {name: 0 for name in RUNPART_FIELDS}
    previous_time = None
    for index, raw in enumerate(reader):
        try:
            part = int(str(raw["Part"]).replace(",", ""))
            time_s = float(raw["TimeStep [s]"])
            values = {name: int(str(raw[name]).replace(",", "")) for name in RUNPART_FIELDS}
        except (KeyError, TypeError, ValueError) as exc:
            raise AdapterError("RunPARTs has an invalid row") from exc
        if part != index or (previous_time is not None and time_s <= previous_time):
            raise AdapterError("RunPARTs Part/time sequence is not increasing")
        if any(value < 0 for value in values.values()) or values["NpOut"] != sum(values[name] for name in RUNPART_FIELDS[1:]):
            raise AdapterError("RunPARTs motive counters are inconsistent")
        previous_time = time_s
        for name, value in values.items():
            totals[name] += value
    if not totals["NpOut"]:
        raise AdapterError("RunPARTs reports no native exclusions")
    return totals


def _validate_case(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise AdapterError(f"unsupported manifest schema: {manifest.get('schema')}")
    case = manifest.get("case")
    if not isinstance(case, dict):
        raise AdapterError("manifest case is missing")
    identity = case.get("identity")
    if identity != {
        "current_case_index": 78,
        "family_id": "F2",
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "runtime_case_alias": "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010",
    }:
        raise AdapterError("F2-S1 source identity differs")
    return case


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.is_file():
        raise AdapterError(f"manifest is missing: {manifest_path}")
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = _validate_case(manifest_data)
    refs = manifest_data.get("bindings")
    if not isinstance(refs, dict):
        raise AdapterError("manifest bindings are missing")

    closure_path, closure, closure_binding = read_json_binding(refs["source_closure"], "F2-S1 source closure")
    if closure.get("schema") != "ds02.stage2.f2-s1-native-source-closure.v1":
        raise AdapterError("source closure schema differs")
    if closure.get("status") != "EXACT_NATIVE_SOURCE_CLOSED_WITH_PHYSICAL_FATE_UNKNOWN":
        raise AdapterError("source closure is not the completed F2-S1 closure")
    closure_refs = closure.get("source_bindings", {})
    for closure_key, manifest_key in (
        ("old_scientific_scan", "scan"), ("old_scientific_scan_receipt", "scan_receipt"),
        ("old_partvtkout_csv", "native_csv"), ("old_partvtkout_receipt", "native_decoder_receipt"),
        ("raw_partout", "raw_partout"), ("runparts", "runparts"), ("runout", "runout"),
        ("solver_receipt", "solver_receipt"), ("gencase_receipt", "gencase_receipt"),
        ("generated_xml", "xml"), ("dsph_config", "dsph_config"),
        ("partvtkout", "partvtk_binary"), ("current_conversion_report", "producer_conversion_report"),
    ):
        source_ref = closure_refs.get(closure_key)
        manifest_ref = refs.get(manifest_key)
        if not isinstance(source_ref, dict) or not isinstance(manifest_ref, dict):
            raise AdapterError(f"source closure lacks {closure_key}")
        _same_ref(source_ref, manifest_ref, f"source closure {closure_key}")
    if closure.get("current", {}).get("path") != refs.get("current", {}).get("path") or closure.get("current", {}).get("sha256") != refs.get("current", {}).get("sha256"):
        raise AdapterError("source closure CURRENT binding differs")
    current_path, current, current_binding = read_json_binding(refs["current"], "CURRENT336")
    current_rows = [row for row in current.get("cases", [])
                    if row.get("family_id") == manifest["identity"]["family_id"]
                    and row.get("physical_case_id") == manifest["identity"]["physical_case_id"]]
    if len(current_rows) != 1:
        raise AdapterError("CURRENT does not contain exactly one F2-S1 row")
    current_row = current_rows[0]
    if current_row.get("runtime_case_alias") != manifest["identity"]["runtime_case_alias"] or current_row.get("frames") != 401 or current_row.get("particles") != 418104:
        raise AdapterError("CURRENT F2-S1 row differs")

    producer_path, producer, producer_binding = read_json_binding(refs["producer_conversion_report"], "producer conversion report")
    v37_path, v37, v37_binding = read_json_binding(refs["v37_converter_report"], "root-049 V37 converter report")
    # The root-049 portable bundle did not create a second solver receipt.  Its
    # converter report is source-bound to the completed native solver receipt
    # copied into the bundle.  Bind that receipt by the report's own
    # source_provenance reference; do not infer provenance from a directory
    # relationship (the report is under /var/tmp while the solver receipt's
    # output_root is the original producer tree).
    v37_receipt_path, v37_receipt, v37_receipt_binding = read_json_binding(refs["v37_actual_receipt"], "root-049 actual native receipt")
    _receipt_status(v37_receipt, "root-049 actual native receipt")
    typed_only_path, typed_only, typed_only_binding = read_json_binding(refs["typed_only_producer_report"], "typed-only producer report")
    if typed_only.get("schema") != "ds02.f2.stage1.actual812-typed157-provenance-owner.v1":
        raise AdapterError("typed-only producer report schema differs")
    if typed_only.get("case_id") != manifest["identity"]["runtime_case_alias"] or typed_only.get("family_id") != "F2":
        raise AdapterError("typed-only producer report case identity differs")
    if typed_only.get("q_n") != "not_granted" or typed_only.get("scientific_payloads_read_or_hashed_by_owner_builder") is not False:
        raise AdapterError("typed-only producer report grants unsupported credit")
    runtime_audit_path, runtime_audit, runtime_audit_binding = read_json_binding(refs["v37_runtime_audit"], "V37 runtime audit")
    if runtime_audit.get("schema") != "ds02.stage2.f2-private-runtime-audit.v1" or runtime_audit.get("status") != "PASS_CLOSED_RUNTIME_MODULE_FILES":
        raise AdapterError("V37 runtime audit is not closed")
    native_reconcile_path, native_reconcile, native_reconcile_binding = read_json_binding(refs["native_reconciliation_receipt"], "native reconciliation receipt")
    _receipt_status(native_reconcile, "native reconciliation receipt")
    if producer.get("schema") != "ds-data-02.bi4-direct-conversion.v1" or producer.get("conversion_status") != "completed":
        raise AdapterError("producer conversion report is not completed")
    if v37.get("schema") != "ds-data-02.bi4-direct-conversion.v1" or v37.get("conversion_status") != "completed":
        raise AdapterError("V37 converter report is not completed")
    for label, report in (("producer conversion", producer), ("root-049 V37 converter", v37)):
        if report.get("frames") != 401 or report.get("particles") != 418104:
            raise AdapterError(f"{label} frame/particle header differs")
        _typed_blocks(report, label)
    producer_blocks, producer_mass, producer_bound = _typed_blocks(producer, "producer conversion")
    v37_blocks, v37_mass, v37_bound = _typed_blocks(v37, "root-049 V37 converter")
    if producer_blocks != v37_blocks or not math.isclose(producer_mass, v37_mass, rel_tol=0.0, abs_tol=0.0) or not math.isclose(producer_bound, v37_bound, rel_tol=0.0, abs_tol=0.0):
        raise AdapterError("V37 typed blocks/header do not exactly match producer conversion")

    source_p = producer.get("source_provenance", {})
    source_v = v37.get("source_provenance", {})
    if not isinstance(source_p, dict) or not isinstance(source_v, dict):
        raise AdapterError("conversion source provenance is missing")
    raw_path, raw_binding = bind(refs["raw_partout"], "original raw PartOut", allow_raw_partout=True)
    v37_raw_path, v37_raw_binding = bind(refs["v37_raw_partout"], "root-049 raw PartOut", allow_raw_partout=True)
    data_root = Path(str(source_p.get("data_root", ""))).expanduser().resolve()
    if raw_path.parent != data_root or raw_path.name != "PartOut_000.obi4":
        raise AdapterError("original raw PartOut is not the producer conversion data root")
    v37_data_root = Path(str(source_v.get("data_root", ""))).expanduser().resolve()
    if v37_raw_path.parent != v37_data_root or v37_raw_path.name != "PartOut_000.obi4":
        raise AdapterError("root-049 raw PartOut is not the V37 converter data root")
    if source_p.get("raw_tree", {}).get("after_file_count") != 405 or source_p.get("raw_tree", {}).get("after_tree_sha256") != RAW_TREE_SHA256:
        raise AdapterError("producer raw tree manifest is not the frozen 405-file tree")
    if source_v.get("raw_tree", {}).get("after_file_count") != 405 or source_v.get("raw_tree", {}).get("after_tree_sha256") != RAW_TREE_SHA256:
        raise AdapterError("root-049 raw tree manifest is not the frozen 405-file tree")
    # The portable bundle legitimately relocates these source files.  Their
    # content digests, rather than their paths, must match the original
    # producer references.
    for field, ref_key, label in (("generated_xml", "v37_xml", "V37 generated XML"), ("gencase_receipt", "v37_gencase_receipt", "V37 GenCase receipt"), ("solver_receipt", "v37_actual_receipt", "V37 solver receipt"), ("owner_metadata", "typed_only_producer_report", "typed-only owner metadata"), ("decoder", "v37_decoder", "V37 decoder")):
        actual = source_v.get(field)
        if not isinstance(actual, dict):
            raise AdapterError(f"root-049 {label} provenance is missing")
        _same_ref(actual, refs[ref_key], label)
    for field in ("control_sha256", "control_reference_sha256", "geometry_sha256", "geometry_reference_sha256"):
        if source_v.get(field) != source_p.get(field):
            raise AdapterError(f"root-049 {field} differs from producer")
    if source_v.get("partvtk") is not None:
        raise AdapterError("root-049 report unexpectedly claims a PartVTK source")
    if v37.get("output_sha256") != refs["v37_output_hdf5"]["sha256"] or v37.get("output_hdf5") != refs["v37_output_hdf5"]["path"]:
        raise AdapterError("root-049 typed HDF5 output binding differs")
    if v37.get("output_sha256") != "f2082256dee796cd8c2bcee830eb15a0a426583666dbe86d9dc5120dd9a0235e":
        raise AdapterError("root-049 typed HDF5 output digest is not the frozen producer digest")
    actual_native_ref = typed_only.get("provenance", {}).get("actual_native_receipt")
    _same_ref(actual_native_ref, refs["solver_receipt"], "typed-only actual native receipt")

    scan_path, scan, scan_binding = read_json_binding(refs["scan"], "scientific scan")
    scan_receipt_path, scan_receipt, scan_receipt_binding = read_json_binding(refs["scan_receipt"], "scientific scan receipt")
    if scan.get("schema") != "ds02.stage2.scientific-scan.v1" or scan.get("scan_status") != "SCANNED" or scan.get("failures"):
        raise AdapterError("scientific scan is not clean")
    if scan.get("family_id") != manifest["identity"]["family_id"] or scan.get("physical_case_id") != manifest["identity"]["physical_case_id"]:
        raise AdapterError("scientific scan physical identity differs")
    _receipt_status(scan_receipt, "scientific scan receipt")
    trajectory = Path(str(scan.get("trajectory", ""))).expanduser().resolve()
    if trajectory.name != "trajectory.h5":
        raise AdapterError("scientific scan trajectory is not trajectory.h5")
    trajectory_key = str(trajectory)
    trajectory_hash = scan_receipt.get("request", {}).get("input_sha256", {}).get(trajectory_key)
    if not isinstance(trajectory_hash, str) or trajectory_hash != scan_receipt.get("input_hashes_at_launch", {}).get(trajectory_key) or trajectory_hash != scan_receipt.get("input_hashes_after_run", {}).get(trajectory_key):
        raise AdapterError("scientific scan trajectory producer hash is unstable")
    if producer.get("output_hdf5") != trajectory_key or producer.get("output_sha256") != trajectory_hash:
        raise AdapterError("producer conversion output does not bind the original scan trajectory")
    if current_row.get("trajectory", {}).get("producer_declared_sha256") != trajectory_hash:
        raise AdapterError("CURRENT trajectory producer digest differs")
    if source_p.get("generated_xml", {}).get("path") != str(Path(refs["xml"]["path"]).resolve()):
        raise AdapterError("producer XML source path differs")

    decoder_path, decoder, decoder_binding = read_json_binding(refs["native_decoder_receipt"], "official PartVTKOut receipt")
    _receipt_status(decoder, "official PartVTKOut receipt")
    native_path, native_binding = bind(refs["native_csv"], "official PartVTKOut CSV")
    command = decoder.get("command", [])
    binary_path, binary_binding = bind(refs["partvtk_binary"], "official PartVTKOut binary")
    if not command or Path(str(command[0])).resolve() != binary_path or decoder.get("binary_sha256") != binary_binding["sha256"]:
        raise AdapterError("official PartVTKOut receipt binary is not the bound binary")
    if Path(_command_value(command, "-savecsv")).resolve() != native_path or Path(_command_value(command, "-dirdata")).resolve() != data_root:
        raise AdapterError("official PartVTKOut command output/data root differs")
    resume_path = Path(_command_value(command, "-saveresume")).resolve()
    if resume_path.parent != native_path.parent or not resume_path.is_file():
        raise AdapterError("official PartVTKOut resume is not in CSV output root")
    for path in (raw_path, Path(refs["runparts"]["path"]).resolve(), Path(refs["xml"]["path"]).resolve(), binary_path):
        _stable_receipt_input(decoder, path, "official PartVTKOut receipt")
    if decoder.get("output_root") != str(native_path.parent):
        raise AdapterError("official PartVTKOut output root differs")

    rows = _read_partout(native_path)
    row_ids = {row["idp"] for row in rows}
    if row_ids != set(EXPECTED_IDPS) or any(row["motive_code"] != 1 for row in rows):
        raise AdapterError("official PartVTKOut rows do not contain the exact three position IDs")
    runparts_path, runparts_binding = bind(refs["runparts"], "RunPARTs")
    totals = _read_runparts(runparts_path)
    if runparts_path.parent != data_root.parent:
        raise AdapterError("RunPARTs is not from the same solver_output parent")
    if totals != {"NpOut": 3, "NpOutPos": 3, "NpOutRho": 0, "NpOutMov": 0}:
        raise AdapterError(f"RunPARTs totals differ from official CSV: {totals}")

    missing = {int(row["idp"]): row for row in scan.get("missing_id_records", [])
               if int(row.get("type_code", -1)) == 3 and row.get("missing_at_final") is True}
    if set(missing) != row_ids:
        raise AdapterError("scientific scan final fluid omission IDs differ from PartVTKOut")
    identities: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda value: value["idp"]):
        scan_row = missing[row["idp"]]
        if row["part_out"] != int(scan_row["first_missing_frame"]):
            raise AdapterError(f"PartVTKOut first Part differs for Idp {row['idp']}")
        if not math.isclose(float(scan_row["initial_mass_kg"]), v37_mass, rel_tol=0.0, abs_tol=FLOAT_TOL):
            raise AdapterError(f"scan mass differs from V37 MassFluid for Idp {row['idp']}")
        block_matches = [block for block in v37_blocks if block["begin"] <= row["idp"] < block["begin"] + block["count"]]
        if len(block_matches) != 1 or block_matches[0]["type"] != 3:
            raise AdapterError(f"Idp {row['idp']} does not map to one typed fluid block")
        block = block_matches[0]
        identities.append({
            "zone": int(scan_row["zone"]), "idp": row["idp"], "mk": block["mk"],
            "mkfluid": block["mkfluid"], "type": block["type"], "typed_tag": block["tag"],
            "motive": MOTIVES[row["motive_code"]], "motive_code": row["motive_code"],
            "part_out": row["part_out"], "first_missing_bracket_s": scan_row.get("first_missing_bracket_s"),
            "initial_mass_kg": v37_mass, "position_m": row["position_m"],
            "density_kg_m3": row["density_kg_m3"],
        })

    solver_path, solver_receipt, solver_binding = read_json_binding(refs["solver_receipt"], "solver receipt")
    gencase_path, gencase_receipt, gencase_binding = read_json_binding(refs["gencase_receipt"], "GenCase receipt")
    _receipt_status(solver_receipt, "solver receipt")
    _receipt_status(gencase_receipt, "GenCase receipt")
    xml_path, xml_binding = bind(refs["xml"], "generated XML")
    runout_path, runout_binding = bind(refs["runout"], "Run.out")
    if runout_path.parent != data_root.parent:
        raise AdapterError("Run.out is not from the same solver_output parent")
    config_path, config_binding = bind(refs["dsph_config"], "DsphConfig.xml")
    snapshot_path, snapshot, snapshot_binding = read_json_binding(refs["raw_snapshot_report"], "raw auxiliary snapshot report")
    snapshot_receipt_path, snapshot_receipt, snapshot_receipt_binding = read_json_binding(refs["raw_snapshot_receipt"], "raw auxiliary snapshot receipt")
    _receipt_status(snapshot_receipt, "raw auxiliary snapshot receipt")
    if snapshot.get("schema") != "ds02.stage2.f2-raw-auxiliary-binding.v1" or snapshot.get("status") != "COMPLETE_PARENT_GUARDED":
        raise AdapterError("raw auxiliary snapshot is not the completed V37 source snapshot")
    if snapshot.get("expected_raw_tree", {}).get("tree_sha256") != RAW_TREE_SHA256 or snapshot.get("expected_raw_tree", {}).get("file_count") != 405:
        raise AdapterError("raw auxiliary snapshot tree differs")
    entries = {entry.get("filename"): entry for entry in snapshot.get("entries", []) if isinstance(entry, dict)}
    if entries.get("PartOut_000.obi4", {}).get("sha256") != raw_binding["sha256"]:
        raise AdapterError("raw auxiliary snapshot PartOut digest differs")
    if snapshot.get("execution_boundary", {}).get("converter_invoked") is not False or snapshot.get("execution_boundary", {}).get("hdf5_opened") is not False:
        raise AdapterError("raw auxiliary snapshot claims forbidden reads")

    # The V37 report's output is intentionally distinct from the producer HDF5
    # used by the scientific scan.  We bind both reports and prove their
    # shared raw/control/typed metadata; we never equate or open the HDF5s.
    v37_output = {"path": str(v37.get("output_hdf5", "")), "sha256": v37.get("output_sha256"), "opened": False}
    source_bindings = {
        "source_closure": closure_binding, "current": current_binding,
        "producer_conversion_report": producer_binding, "v37_converter_report": v37_binding,
        "v37_actual_receipt": v37_receipt_binding,
        "typed_only_producer_report": typed_only_binding,
        "v37_runtime_audit": runtime_audit_binding,
        "native_reconciliation_receipt": native_reconcile_binding,
        "v37_raw_partout": v37_raw_binding,
        "v37_output_hdf5": {"path": str(v37.get("output_hdf5")), "sha256": v37.get("output_sha256"), "opened": False},
        "scientific_scan": scan_binding, "scientific_scan_receipt": scan_receipt_binding,
        "native_decoder_receipt": decoder_binding, "native_csv": native_binding,
        "raw_partout": raw_binding, "runparts": runparts_binding, "runout": runout_binding,
        "solver_receipt": solver_binding, "gencase_receipt": gencase_binding,
        "xml": xml_binding, "dsph_config": config_binding, "partvtk_binary": binary_binding,
        "raw_snapshot_report": snapshot_binding, "raw_snapshot_receipt": snapshot_receipt_binding,
        "v37_xml": bind(refs["v37_xml"], "V37 generated XML")[1],
        "v37_gencase_receipt": bind(refs["v37_gencase_receipt"], "V37 GenCase receipt")[1],
        "v37_decoder": bind(refs["v37_decoder"], "V37 decoder")[1],
    }
    result = {
        "schema": OUTPUT_SCHEMA,
        "status": "COMPLETED_F2_S1_NATIVE_SOURCE_JOIN_WITH_PHYSICAL_FATE_UNKNOWN",
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path), "bytes": manifest_path.stat().st_size},
        "case_identity": manifest["identity"],
        "source_bindings": source_bindings,
        "conversion_join": {
            "producer_conversion_report": {"schema": producer.get("schema"), "status": producer.get("conversion_status"), "output_hdf5": producer.get("output_hdf5"), "output_sha256": producer.get("output_sha256"), "opened": False},
            "v37_converter_report": {"schema": v37.get("schema"), "status": v37.get("conversion_status"), "output_hdf5": v37_output, "opened": False, "report_sha256": v37_binding["sha256"]},
            "typed_blocks_identical": True,
            "header_mass_fluid_kg": v37_mass,
            "header_mass_bound_kg": v37_bound,
            "raw_tree_sha256": RAW_TREE_SHA256,
            "source_provenance_shared": ["data_root", "generated_xml", "gencase_receipt", "solver_receipt", "raw_tree", "control_sha256", "geometry_sha256"],
            "trajectory_join": "producer_report_only; root-049 output HDF5 is a distinct metadata-only typed artifact",
            "root_049_source_report": "source-provenance and typed-only owner metadata are content-bound; no converter execution receipt was synthesized",
        },
        "native_identity": {
            "status": "CLOSED_FOR_THREE_OFFICIAL_PARTVTKOUT_ROWS",
            "id_count": len(identities), "ids": identities,
            "motive_counts": {"position": 3, "density": 0, "movement": 0},
            "source_mk_counts": {"1": 3, "2": 0, "3": 0},
            "initial_exclusion_ledger_count": 0,
            "typed_initial_mass_kg": float(scan.get("type_ledgers", {}).get("fluid", {}).get("typed_initial_mass_kg")),
            "missing_mass_kg": v37_mass * len(identities),
            "missing_mass_fraction_of_whole_initial": (v37_mass * len(identities)) / float(scan.get("type_ledgers", {}).get("fluid", {}).get("typed_initial_mass_kg")),
            "runparts_totals": totals,
        },
        "claim_boundary": {
            "converter_implementation": "UNKNOWN; root-049 report and typed-only owner metadata are source evidence only",
            "physical_fate": "UNKNOWN; native numerical position exclusion is not legal spill or physical outflow",
            "continuous_event_time": "UNKNOWN beyond saved first-missing brackets",
            "dynamical_impact": "UNKNOWN; missing mass is a source-visible lower bound only",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "typed_only_scientific_credit": "NOT_GRANTED",
        },
        "read_policy": {
            "json_csv_xml_runout_opened": True, "raw_partout_hashed": True,
            "official_decoder_started": False, "trajectory_h5_opened": False,
            "part_frames_opened": False, "solver_started": False,
            "cfd_or_model_run": False,
        },
    }
    output_path = Path(output_path).resolve()
    if output_path.exists():
        raise AdapterError(f"preserve existing output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{output_path.name}.", dir=str(output_path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output_path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", choices=["run"])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.manifest, args.output)
    print(json.dumps({"status": result["status"], "id_count": result["native_identity"]["id_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

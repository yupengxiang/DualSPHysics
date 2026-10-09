#!/usr/bin/env python3
"""Prepare and, after ROOT170 termination, audit its native PartOut product.

``prepare`` is deliberately source-only.  It binds the immutable ROOT170
request/checkpoint and the existing CURRENT336 scientific-scan JSON evidence,
then writes a manifest whose native solver inputs remain deferred until ROOT170
has a completed receipt.  It does not open trajectory HDF5, Part_*.bi4, BI4, or
OBI4 payloads.

``audit`` is a parent-guarded follow-up.  It requires an additive manifest with
an exact completed ROOT170 receipt, solver output root, ``PartOut_000.obi4``,
RunPARTs, Run.out, and generated XML bindings.  It invokes the official
PartVTKOut command once and joins emitted Idp/Motive rows to XML fluid blocks
and saved RunPARTs brackets.  A PartOut row is evidence of a native numerical
gate only.  Absence from PartOut is not assigned a motive, physical fate,
legal flux, wall contact, or dynamical impact.
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
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any


SCHEMA = "ds02.stage2.f3.s2.fine-native-motive-audit.v1"
MANIFEST_SCHEMA = "ds02.stage2.f3.s2.fine-native-motive.manifest.v1"
REQUEST_SCHEMA = "ds02.stage2.f3.s2.fine-native-motive-request.v1"
OUTPUT_SCHEMA = "ds02.stage2.f3.s2.fine-native-motive-audit.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
SCAN_SCHEMA = "ds02.stage2.scientific-scan.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
ROOT170_REQUEST_SCHEMA = "ds02.stage2.external-solver-request.v5"
ROOT170_CHECKPOINT_SCHEMA = "ds02.stage2.root-running-checkpoint.v1"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
ROOT170_CASE_ID = "F3_S2_MATCHED_FINE_SAME_CFL_ROOT_170"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
SENTINEL_ID = "F3-S2"
ROOT170_ATTEMPT_ID = "f3-s2-matched-fine-same-cfl-v5-root-170-001"
PARTVTKOUT = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
)
DSPH_CONFIG = PARTVTKOUT.parent / "DsphConfig.xml"
PARTVTKOUT_SHA256 = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
DSPH_CONFIG_SHA256 = "a2bc1f88c6ea95347187a64a991ebada177c6314de5c35ab078b06d78235eece"
MOTIVES = {1: "position", 2: "density", 3: "movement"}
RUNPART_COUNTERS = ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")
FORBIDDEN_PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".vtk", ".vtu"}


class FineMotiveError(ValueError):
    """Raised when a source or terminal audit contract is not closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str, *, allow_payload: bool = False) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FineMotiveError(f"{label} is not a regular file: {path}")
    if not allow_payload and path.suffix.lower() in FORBIDDEN_PAYLOAD_SUFFIXES:
        raise FineMotiveError(f"{label} points at forbidden native payload: {path}")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FineMotiveError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FineMotiveError(f"{label} must be a JSON object: {path}")
    return value


def stat_ref(path: Path, role: str, *, allow_payload: bool = False) -> dict[str, Any]:
    path = require_file(path, role, allow_payload=allow_payload)
    stat = path.stat()
    return {
        "role": role,
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": sha256_file(path),
        "source_scope": "PARENT_GUARDED_NATIVE_PAYLOAD" if allow_payload else "JSON_OR_SMALL_SOURCE",
    }


def verify_ref(ref: dict[str, Any], label: str, *, allow_payload: bool = False) -> tuple[Path, dict[str, Any]]:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise FineMotiveError(f"{label} lacks an absolute path")
    path = require_file(ref["path"], label, allow_payload=allow_payload)
    actual = stat_ref(path, str(ref.get("role", label)), allow_payload=allow_payload)
    expected_sha = ref.get("sha256")
    if expected_sha not in (None, "PARENT_GUARD_COMPUTED") and actual["sha256"] != expected_sha:
        raise FineMotiveError(f"{label} SHA differs: {path}")
    for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if ref.get(field) is not None and int(ref[field]) != actual[field]:
            raise FineMotiveError(f"{label} {field} differs: {path}")
    return path, actual


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise FineMotiveError(f"refusing to overwrite existing output: {path}")
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


def _case_key(row: dict[str, Any]) -> str:
    family = row.get("family_id")
    physical = row.get("physical_case_id")
    if not isinstance(family, str) or not isinstance(physical, str):
        raise FineMotiveError("CURRENT row lacks family_id/physical_case_id")
    return f"{family}/{physical}"


def _command_flag(command: list[Any], flag: str, label: str) -> str:
    for index, value in enumerate(command[:-1]):
        if str(value) == flag:
            return str(command[index + 1])
    raise FineMotiveError(f"{label} lacks {flag}")


def _current_row(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    current = read_json(path, "CURRENT336")
    if current.get("schema") != CURRENT_SCHEMA or not isinstance(current.get("cases"), list) or len(current["cases"]) != 336:
        raise FineMotiveError("CURRENT336 is not the exact 336-case catalog")
    rows: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(current["cases"]):
        if not isinstance(row, dict) or row.get("current_index", index) != index:
            raise FineMotiveError(f"CURRENT336 index is not exact at {index}")
        # CURRENT336 is an ordered list; older/current producer rows do not
        # repeat the list index as a field.  Add the authoritative list index
        # only to this in-memory view, never to the immutable catalog bytes.
        row = dict(row)
        row.setdefault("current_index", index)
        key = _case_key(row)
        if key in rows:
            raise FineMotiveError(f"CURRENT336 duplicate case key: {key}")
        rows[key] = row
    if len(rows) != 336:
        raise FineMotiveError("CURRENT336 identity count is not 336")
    key = f"F3/{PHYSICAL_CASE_ID}"
    if key not in rows:
        raise FineMotiveError("F3-S2 physical case is absent from exact CURRENT336")
    return rows[key], {"schema": current["schema"], "case_count": len(rows), "case_key": key}


def _scan_current_binding(receipt: dict[str, Any], current_path: Path) -> dict[str, Any]:
    expected_path = str(current_path)
    expected_sha = CURRENT_SHA256
    observed: list[dict[str, Any]] = []
    for section_name in ("input_hashes_at_launch", "input_hashes_after_run"):
        values = receipt.get(section_name)
        if not isinstance(values, dict):
            raise FineMotiveError(f"scan receipt lacks {section_name}")
        matching = [
            {"path": str(path), "sha256": value}
            for path, value in values.items()
            if Path(str(path)).name == "CURRENT336.json"
        ]
        observed.append({"section": section_name, "values": matching})
        if len(matching) != 1 or matching[0]["path"] != expected_path or matching[0]["sha256"] != expected_sha:
            raise FineMotiveError(f"scan receipt CURRENT binding is not exact in {section_name}")
    return {"status": "EXACT_CURRENT_AT_LAUNCH_AND_END", "path": expected_path, "sha256": expected_sha, "observed": observed}


def _validate_root170(request_path: Path, checkpoint_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    request = read_json(request_path, "ROOT170 request")
    checkpoint = read_json(checkpoint_path, "ROOT170 checkpoint")
    if request.get("schema") != ROOT170_REQUEST_SCHEMA:
        raise FineMotiveError("ROOT170 request schema differs")
    if checkpoint.get("schema") != ROOT170_CHECKPOINT_SCHEMA:
        raise FineMotiveError("ROOT170 checkpoint schema differs")
    if checkpoint.get("request") != str(request_path):
        raise FineMotiveError("ROOT170 checkpoint request path differs")
    request_sha = sha256_file(request_path)
    if checkpoint.get("request_sha256") != request_sha:
        raise FineMotiveError("ROOT170 checkpoint request SHA differs")
    exact = {
        "case_id": ROOT170_CASE_ID,
        "family_id": "F3",
        "physical_case_id": PHYSICAL_CASE_ID,
        "sentinel_id": SENTINEL_ID,
        "attempt_id": ROOT170_ATTEMPT_ID,
    }
    for key, expected in exact.items():
        if request.get(key) != expected:
            raise FineMotiveError(f"ROOT170 request {key} differs")
    if checkpoint.get("root_native_payload_read") is True:
        raise FineMotiveError("ROOT170 checkpoint claims native payload was already read")
    for key in ("hdf5_opened", "raw_opened", "model_invoked", "cfd_invoked"):
        if request.get(key) is True:
            raise FineMotiveError(f"ROOT170 request claims forbidden operation: {key}")
    command = request.get("command")
    if not isinstance(command, list) or "--tmax" not in command or "--tout" not in command:
        raise FineMotiveError("ROOT170 command lacks time-window flags")
    output_root = request.get("storage_scope", {}).get("output_root")
    if not isinstance(output_root, str) or not output_root.startswith("/var/tmp/ds02-stage2/"):
        raise FineMotiveError("ROOT170 output root is not the shared data root")
    if request.get("source_provenance", {}).get("mass_rescale") is True:
        raise FineMotiveError("ROOT170 source provenance claims mass rescale")
    return request, checkpoint, {
        "request": stat_ref(request_path, "root170_request"),
        "checkpoint": stat_ref(checkpoint_path, "root170_checkpoint"),
        "request_sha256": request_sha,
        "output_root": output_root,
        "checkpoint_status": checkpoint.get("status"),
    }


def _validate_historic_scan(
    current_path: Path,
    current_row: dict[str, Any],
    scan_path: Path,
    scan_receipt_path: Path,
    detail_path: Path,
) -> dict[str, Any]:
    scan = read_json(scan_path, "historic scientific scan")
    if scan.get("schema") != SCAN_SCHEMA or scan.get("scan_status") != "SCANNED":
        raise FineMotiveError("historic scan is not completed scientific-scan.v1")
    if scan.get("family_id") != "F3" or scan.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise FineMotiveError("historic scan producer identity differs")
    if scan.get("frames") != current_row.get("frames") or scan.get("particles") != current_row.get("particles"):
        raise FineMotiveError("historic scan dimensions differ from CURRENT case")
    receipt = read_json(scan_receipt_path, "historic scan receipt")
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise FineMotiveError("historic scan receipt is not completed")
    command = receipt.get("request", {}).get("command")
    if not isinstance(command, list) or PHYSICAL_CASE_ID not in [str(value) for value in command]:
        raise FineMotiveError("historic scan receipt command does not bind the physical case")
    current_binding = _scan_current_binding(receipt, current_path)
    detail = read_json(detail_path, "historic scan detail card")
    expected_key = f"F3/{PHYSICAL_CASE_ID}"
    if detail.get("schema") != "ds02.stage2.scientific-scan-detail-card.v2" or detail.get("case_key") != expected_key:
        raise FineMotiveError("historic detail card identity differs")
    detail_index = detail.get("current_index")
    if detail_index is None:
        identity = detail.get("current_identity")
        if isinstance(identity, dict):
            detail_index = identity.get("current_index", identity.get("current_list_index"))
    if detail_index != current_row.get("current_index"):
        raise FineMotiveError("historic detail card current index differs")
    if (detail.get("scan_provenance") or {}).get("path") != str(scan_path):
        raise FineMotiveError("historic detail card scan path differs")
    if (detail.get("receipt_provenance") or {}).get("path") != str(scan_receipt_path):
        raise FineMotiveError("historic detail card receipt path differs")
    return {
        "scan": stat_ref(scan_path, "historic_scan"),
        "receipt": stat_ref(scan_receipt_path, "historic_scan_receipt"),
        "detail_card": stat_ref(detail_path, "historic_detail_card"),
        "producer": {
            "family_id": scan["family_id"],
            "physical_case_id": scan["physical_case_id"],
            "frames": scan["frames"],
            "particles": scan["particles"],
            "scan_status": scan["scan_status"],
            "missing_id_record_count": len(scan.get("missing_id_records", [])) if isinstance(scan.get("missing_id_records"), list) else "NOT_EXPOSED",
            "per_id_lifecycle": "NOT_EXPOSED_BY_SCIENTIFIC_SCAN",
        },
        "current_binding": current_binding,
        "trajectory_h5_opened": False,
    }


def prepare(
    *,
    root170_request: Path,
    root170_checkpoint: Path,
    current: Path,
    scan: Path,
    scan_receipt: Path,
    detail_card: Path,
    source_xml: Path,
    output_manifest: Path,
    output_request: Path,
    worker: Path,
) -> dict[str, Any]:
    root170_request = require_file(root170_request, "ROOT170 request")
    root170_checkpoint = require_file(root170_checkpoint, "ROOT170 checkpoint")
    current = require_file(current, "CURRENT336")
    scan = require_file(scan, "historic scientific scan")
    scan_receipt = require_file(scan_receipt, "historic scan receipt")
    detail_card = require_file(detail_card, "historic detail card")
    source_xml = require_file(source_xml, "F3 source XML")
    worker = require_file(worker, "ROOT182 worker")
    request_data, checkpoint_data, root170_binding = _validate_root170(root170_request, root170_checkpoint)
    current_row, current_meta = _current_row(current)
    scan_meta = _validate_historic_scan(current, current_row, scan, scan_receipt, detail_card)
    declared_source_xml = request_data.get("source_provenance", {}).get("source_xml")
    if not isinstance(declared_source_xml, dict) or declared_source_xml.get("path") != str(source_xml):
        raise FineMotiveError("source XML path differs from ROOT170 source provenance")
    if declared_source_xml.get("sha256") != sha256_file(source_xml):
        raise FineMotiveError("source XML SHA differs from ROOT170 source provenance")
    tool_ref = stat_ref(PARTVTKOUT, "official_partvtkout")
    config_ref = stat_ref(DSPH_CONFIG, "official_dsph_config")
    if tool_ref["sha256"] != PARTVTKOUT_SHA256:
        raise FineMotiveError("official PartVTKOut SHA differs")
    if config_ref["sha256"] != DSPH_CONFIG_SHA256:
        raise FineMotiveError("official DsphConfig SHA differs")
    source_refs = [
        root170_binding["request"], root170_binding["checkpoint"],
        stat_ref(current, "current336"), stat_ref(scan, "historic_scan"),
        stat_ref(scan_receipt, "historic_scan_receipt"), stat_ref(detail_card, "historic_detail_card"),
        stat_ref(source_xml, "source_xml"), tool_ref, config_ref,
        stat_ref(worker, "worker"),
    ]
    # Keep exactly one row per role; the role is used by the final parent
    # rebind, and no discovery/glob is permitted.
    by_role = {item["role"]: item for item in source_refs}
    if len(by_role) != len(source_refs):
        raise FineMotiveError("duplicate ROOT182 source role")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "WAITING_FOR_ROOT170_TERMINAL_BINDING",
        "prepared_by_worker_schema": SCHEMA,
        "case": {
            "family_id": "F3",
            "sentinel_id": SENTINEL_ID,
            "case_id": ROOT170_CASE_ID,
            "attempt_id": ROOT170_ATTEMPT_ID,
            "physical_case_id": PHYSICAL_CASE_ID,
            "current_index": current_row["current_index"],
            "current_case_key": f"F3/{PHYSICAL_CASE_ID}",
        },
        "root170_binding": {
            **root170_binding,
            "request": root170_binding["request"],
            "checkpoint": root170_binding["checkpoint"],
            "terminal_status": "PENDING_ROOT170_TERMINAL",
            "output_root": root170_binding["output_root"],
            "checkpoint_status_at_prepare": root170_binding["checkpoint_status"],
        },
        "current_binding": {"catalog": stat_ref(current, "current336"), "case": current_meta},
        "historic_scan_binding": scan_meta,
        "source_refs": source_refs,
        "terminal_binding": {
            "status": "PENDING_ROOT170_TERMINAL",
            "required_after_terminal": [
                "completed ROOT170 execution receipt with returncode 0 and exact request SHA",
                "terminal solver output root equal to ROOT170 receipt output_root",
                "terminal raw solver_output/data/PartOut_000.obi4",
                "terminal solver_output/RunPARTs.csv",
                "terminal solver_output/Run.out",
                "generated XML path and SHA from ROOT170 source contract",
            ],
            "deferred_native_payload": "PartOut_000.obi4 is not opened or stat/read during prepare",
            "deferred_paths_are_not_claims": True,
        },
        "expected": {
            "current_case_frames": current_row.get("frames"),
            "current_case_particles": current_row.get("particles"),
            "window_s": request_data.get("solver_plan", {}).get("window_s"),
            "tout_s": request_data.get("solver_plan", {}).get("tout_s"),
            "continuous_owner_mass_kg": request_data.get("source_provenance", {}).get("continuous_owner_mass_kg"),
            "generated_xml_sha256": request_data.get("source_provenance", {}).get("generated_xml", {}).get("sha256"),
            "generated_bi4_sha256": request_data.get("source_provenance", {}).get("generated_bi4", {}).get("sha256"),
        },
        "read_policy": {
            "prepare_json_opened": True,
            "prepare_source_xml_content_opened": False,
            "prepare_official_tool_hashed_only": True,
            "prepare_trajectory_h5_opened": False,
            "prepare_part_frames_opened": False,
            "prepare_bi4_or_obi4_opened": False,
            "solver_started": False,
            "decoder_started": False,
        },
        "semantic_contract": {
            "native_motive": "Only official PartVTKOut CSV Idp/Motive rows joined to RunPARTs and XML blocks.",
            "unobserved_ids": "An Idp absent from PartOut receives no invented motive; aggregate counters never create per-ID rows.",
            "first_missing_time": "Only saved-record bracket [previous RunPARTs time, current saved time] is reported; continuous event time is UNKNOWN.",
            "lifecycle": "Full per-ID lifecycle, repeated crossings, residence, and re-entry are NOT_EXPOSED by PartOut-only evidence.",
            "physical_fate": "UNKNOWN: numerical position/density/movement motive is not legal spill, wall contact, or physical fate.",
            "dynamical_impact": "UNKNOWN; no QI/QN/QE credit.",
        },
        "resource_estimate": {
            "cpu_threads": 1,
            "omp_threads": 1,
            "max_wall_seconds": 900,
            "max_memory_bytes": 1073741824,
            "estimated_storage_bytes": 134217728,
            "estimated_small_json_bytes": sum(int(ref["bytes"]) for ref in source_refs if ref["path"].endswith(".json")),
            "estimated_native_read_bytes": "UNKNOWN_UNTIL_ROOT170_TERMINAL",
            "estimated_h5_read_bytes": 0,
            "estimated_part_frame_read_bytes": 0,
            "estimated_bi4_read_bytes": "UNKNOWN_UNTIL_ROOT170_TERMINAL",
        },
    }
    atomic_json(output_manifest, manifest)
    input_files = [str(output_manifest.resolve()), str(worker.resolve())] + [ref["path"] for ref in source_refs if ref["role"] != "worker"]
    input_hashes = {path: sha256_file(Path(path)) for path in input_files}
    request = {
        "schema": "ds02.runner-request.v1",
        "request_schema": REQUEST_SCHEMA,
        "attempt_id": "f3-s2-fine-native-motive-audit-v1-root-182-001",
        "case_id": "f3-s2-fine-native-motive-audit-v1-root-182-001",
        "family_id": "infra",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "max_memory_bytes": 1073741824,
        "estimated_storage_bytes": 134217728,
        "cwd": str(worker.parent),
        "worktree_root": str(Path(__file__).resolve().parents[2]),
        "command": [
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            str(worker.resolve()), "audit", "--manifest", str(output_manifest.resolve()),
            "--output", "{attempt_root}/f3-s2-fine-native-motive-audit-v1.json",
        ],
        "input_files": input_files,
        "input_sha256": input_hashes,
        "launch_allowed": False,
        "status": "prepared_waiting_root170_terminal",
        "primary_launch_owner": "root",
        "source_cost": {
            "small_json_and_source_bytes": sum(Path(path).stat().st_size for path in input_files if Path(path).suffix.lower() != ".so"),
            "native_payload_bytes_read": "UNKNOWN_UNTIL_ROOT170_TERMINAL",
            "trajectory_h5_bytes_read": 0,
            "part_frame_bytes_read": 0,
            "solver_started": False,
            "decoder_started": False,
        },
        "read_policy": manifest["read_policy"],
        "claim_boundary": manifest["semantic_contract"],
        "manifest_contract": {
            "manifest": str(output_manifest.resolve()),
            "manifest_sha256": sha256_file(output_manifest),
            "pending_terminal_bind": True,
            "required_cli_subcommand": "audit",
            "official_partvtkout_sha256": PARTVTKOUT_SHA256,
            "forbid_threads_flag": True,
        },
    }
    atomic_json(output_request, request)
    return {"manifest": manifest, "request": request}


def _local_tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _first(root: ET.Element, name: str, label: str) -> ET.Element:
    for node in root.iter():
        if _local_tag(node) == name:
            return node
    raise FineMotiveError(f"{label} has no <{name}>")


def _finite_number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise FineMotiveError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise FineMotiveError(f"{label} is not finite")
    return result


def parse_generated_xml(path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise FineMotiveError(f"generated XML is invalid: {path}") from exc
    particles = _first(root, "particles", "generated XML")
    blocks: list[dict[str, int]] = []
    for child in list(particles):
        if _local_tag(child) != "fluid":
            continue
        try:
            block = {key: int(child.attrib[key]) for key in ("begin", "count", "mkfluid", "mk")}
        except (KeyError, TypeError, ValueError) as exc:
            raise FineMotiveError("generated XML fluid block is malformed") from exc
        if block["begin"] < 0 or block["count"] <= 0:
            raise FineMotiveError("generated XML fluid block range is invalid")
        blocks.append(block)
    if not blocks:
        raise FineMotiveError("generated XML contains no fluid blocks")
    try:
        particle_count = int(particles.attrib["np"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FineMotiveError("generated XML particles np is invalid") from exc
    massfluid = _first(root, "massfluid", "generated XML")
    mass_kg = _finite_number(massfluid.attrib.get("value"), "generated XML massfluid")
    if particle_count <= 0 or mass_kg <= 0:
        raise FineMotiveError("generated XML particles/massfluid is invalid")
    blocks.sort(key=lambda item: item["begin"])
    previous_end = 0
    for block in blocks:
        if block["begin"] < previous_end or block["begin"] + block["count"] > particle_count:
            raise FineMotiveError("generated XML fluid ranges overlap or exceed particles")
        previous_end = block["begin"] + block["count"]
    return {"particles": particle_count, "massfluid_kg": mass_kg, "fluid_count": sum(item["count"] for item in blocks), "fluid_blocks": blocks}


def parse_runparts(path: Path) -> dict[str, Any]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    delimiter = ";" if lines and lines[0].count(";") >= lines[0].count(",") else ","
    reader = csv.DictReader(lines, delimiter=delimiter)
    required = {"Part", "TimeStep [s]", *RUNPART_COUNTERS}
    if not reader.fieldnames or not required <= set(reader.fieldnames):
        raise FineMotiveError("RunPARTs lacks native exclusion counters")
    rows: list[dict[str, Any]] = []
    totals = {field: 0 for field in RUNPART_COUNTERS}
    for raw in reader:
        try:
            part = int(str(raw["Part"]).replace(",", ""))
            time_s = _finite_number(raw["TimeStep [s]"], "RunPARTs time")
            counters = {field: int(str(raw[field]).replace(",", "")) for field in RUNPART_COUNTERS}
        except (KeyError, TypeError, ValueError) as exc:
            raise FineMotiveError("RunPARTs contains malformed counters") from exc
        if part != len(rows) or (rows and time_s <= rows[-1]["time_s"]):
            raise FineMotiveError("RunPARTs Part/time sequence is not increasing")
        if any(value < 0 for value in counters.values()):
            raise FineMotiveError("RunPARTs contains negative counters")
        if counters["NpOut"] != sum(counters[field] for field in RUNPART_COUNTERS[1:]):
            raise FineMotiveError("RunPARTs motive counters do not sum to NpOut")
        row = {"part": part, "time_s": time_s, **counters}
        rows.append(row)
        for field, value in counters.items():
            totals[field] += value
    if not rows:
        raise FineMotiveError("RunPARTs contains no saved records")
    return {"rows": rows, "totals": totals, "last_time_s": rows[-1]["time_s"]}


def parse_runout(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    patterns = {
        "initial_particles": r"Particles of simulation \(initial\):\s*([0-9,]+)",
        "excluded_particles": r"Excluded particles\.*:\s*([0-9,]+)",
        "excluded_density": r"Excluded particles due to Density\.*:\s*([0-9,]+)",
    }
    result: dict[str, int] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if not match:
            result[key] = -1
        else:
            result[key] = int(match.group(1).replace(",", ""))
    return result


def _csv_value(row: dict[str, str], *names: str) -> str:
    for name in names:
        if name in row:
            return row[name]
    raise KeyError(names[0])


def parse_native_csv(path: Path, blocks: list[dict[str, int]]) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise FineMotiveError("PartVTKOut CSV is empty")
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    reader = csv.DictReader(lines, delimiter=delimiter)
    if not reader.fieldnames:
        raise FineMotiveError("PartVTKOut CSV has no header")
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in reader:
        try:
            idp = int(_csv_value(raw, "Idp"))
            part = int(_csv_value(raw, "PartOut"))
            motive_code = int(_csv_value(raw, "Motive"))
            position = [_finite_number(_csv_value(raw, f"Pos.{axis} [m]"), f"Idp {idp} Pos.{axis}") for axis in "xyz"]
            density = _finite_number(_csv_value(raw, "Rhop [kg/m^3]", "Rhop"), f"Idp {idp} Rhop")
        except (KeyError, TypeError, ValueError) as exc:
            raise FineMotiveError("PartVTKOut CSV contains malformed native row") from exc
        if idp < 0 or idp in seen or part < 1 or motive_code not in MOTIVES:
            raise FineMotiveError(f"PartVTKOut CSV has invalid Idp/PartOut/Motive: {idp}")
        seen.add(idp)
        velocity: list[float] | None = None
        velocity_names = [f"Vel.{axis} [m/s]" for axis in "xyz"]
        if all(name in raw for name in velocity_names):
            velocity = [_finite_number(raw[name], f"Idp {idp} {name}") for name in velocity_names]
        block = next((item for item in blocks if item["begin"] <= idp < item["begin"] + item["count"]), None)
        if block is None:
            raise FineMotiveError(f"PartVTKOut Idp {idp} is outside generated XML fluid blocks")
        rows.append({"idp": idp, "part_out": part, "motive_code": motive_code, "motive": MOTIVES[motive_code], "position_m": position, "density_kg_m3": density, "velocity_m_s": velocity, "mkfluid": block["mkfluid"], "mk": block["mk"]})
    if not rows:
        raise FineMotiveError("PartVTKOut CSV has no native rows")
    return rows


def attach_saved_brackets(rows: list[dict[str, Any]], runparts: dict[str, Any]) -> None:
    by_part = {row["part"]: row for row in runparts["rows"]}
    ordered = sorted(by_part)
    for row in rows:
        if row["part_out"] not in by_part:
            raise FineMotiveError(f"native PartOut {row['part_out']} is absent from RunPARTs")
        index = ordered.index(row["part_out"])
        current = by_part[row["part_out"]]["time_s"]
        previous = by_part[ordered[index - 1]]["time_s"] if index else None
        row["saved_record_time_s"] = current
        row["saved_record_bracket_s"] = [previous, current]
        row["continuous_event_time_s"] = "UNKNOWN"


def _validate_terminal_request_chain(manifest: dict[str, Any], paths: dict[str, Path], terminal_receipt: dict[str, Any]) -> None:
    if terminal_receipt.get("status") not in ("completed", "COMPLETED") or terminal_receipt.get("returncode") != 0:
        raise FineMotiveError("ROOT170 terminal receipt is not completed code 0")
    request = terminal_receipt.get("request")
    if isinstance(request, dict):
        request_path = request.get("path")
        if request_path is not None and str(Path(request_path).expanduser().resolve()) != str(paths["root170_request"]):
            raise FineMotiveError("ROOT170 terminal receipt request path differs")
        request_sha = request.get("sha256") or request.get("request_sha256")
        if request_sha is not None and request_sha != paths["root170_request_ref"]["sha256"]:
            raise FineMotiveError("ROOT170 terminal receipt request SHA differs")
        attempt = request.get("attempt_id")
        if attempt is not None and attempt != ROOT170_ATTEMPT_ID:
            raise FineMotiveError("ROOT170 terminal receipt attempt differs")
    receipt_root = terminal_receipt.get("output_root") or (terminal_receipt.get("filesystem") or {}).get("output_root")
    if receipt_root is not None and str(Path(receipt_root).expanduser().resolve()) != str(paths["solver_output_root"].parent):
        raise FineMotiveError("ROOT170 terminal receipt output root differs")


def _validate_final_manifest(manifest_path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]], dict[str, Any]]:
    manifest_path = require_file(manifest_path, "F3 fine native motive manifest")
    manifest = read_json(manifest_path, "F3 fine native motive manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise FineMotiveError("unsupported F3 fine native motive manifest schema")
    if manifest.get("status") != "READY_FOR_GUARDED_AUDIT":
        raise FineMotiveError("manifest is still pending ROOT170 terminal binding")
    case = manifest.get("case")
    if not isinstance(case, dict) or case.get("case_id") != ROOT170_CASE_ID or case.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise FineMotiveError("manifest case identity differs")
    refs = manifest.get("source_refs")
    if not isinstance(refs, list):
        raise FineMotiveError("manifest source_refs is missing")
    paths: dict[str, Path] = {}
    records: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("role"), str):
            raise FineMotiveError("manifest source ref is malformed")
        role = ref["role"]
        if role in paths:
            raise FineMotiveError(f"duplicate manifest source role: {role}")
        path, record = verify_ref(ref, role, allow_payload=False)
        paths[role] = path
        records[role] = record
    required = ("root170_request", "root170_checkpoint", "current336", "historic_scan", "historic_scan_receipt", "source_xml", "official_partvtkout", "official_dsph_config")
    for role in required:
        if role not in paths:
            raise FineMotiveError(f"manifest lacks required source ref: {role}")
    terminal = manifest.get("terminal_binding")
    if not isinstance(terminal, dict) or terminal.get("status") != "READY_FOR_GUARDED_AUDIT":
        raise FineMotiveError("manifest terminal binding is not ready")
    terminal_refs = terminal.get("refs")
    if not isinstance(terminal_refs, dict):
        raise FineMotiveError("manifest lacks terminal refs")
    for role in ("terminal_receipt", "raw_partout", "runparts", "run_out", "generated_xml"):
        if role not in terminal_refs:
            raise FineMotiveError(f"manifest lacks terminal ref: {role}")
        path, record = verify_ref(terminal_refs[role], role, allow_payload=(role == "raw_partout"))
        paths[role] = path
        records[role] = record
    terminal_receipt = read_json(paths["terminal_receipt"], "ROOT170 terminal receipt")
    paths["root170_request_ref"] = records["root170_request"]  # type: ignore[assignment]
    paths["solver_output_root"] = Path(str(terminal.get("solver_output_root"))).expanduser().resolve()
    if not paths["solver_output_root"].is_dir():
        raise FineMotiveError("terminal solver output root is missing")
    if paths["raw_partout"].name != "PartOut_000.obi4":
        raise FineMotiveError("terminal raw payload is not PartOut_000.obi4")
    raw_root = paths["raw_partout"].parent
    if raw_root != paths["solver_output_root"] / "data":
        raise FineMotiveError("terminal PartOut is not under solver_output_root/data")
    for role in ("runparts", "run_out"):
        if paths[role].parent != paths["solver_output_root"]:
            raise FineMotiveError(f"terminal {role} is outside solver output root")
    _validate_terminal_request_chain(manifest, paths, terminal_receipt)
    return manifest, paths, records, terminal_receipt


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest, paths, records, terminal_receipt = _validate_final_manifest(manifest_path)
    generated = parse_generated_xml(paths["generated_xml"])
    decoder_root = Path(output_path).expanduser().resolve().parent
    decoder_root.mkdir(parents=True, exist_ok=True)
    csv_path = decoder_root / "PartOut.csv"
    resume_path = decoder_root / "resume.csv"
    if csv_path.exists() or resume_path.exists():
        raise FineMotiveError("decoder outputs already exist")
    before = {role: stat_ref(paths[role], role, allow_payload=(role == "raw_partout")) for role in ("raw_partout", "runparts", "run_out", "generated_xml")}
    command = [str(paths["official_partvtkout"]), "-dirdata", str(paths["raw_partout"].parent), "-savecsv", str(csv_path), "-saveresume", str(resume_path), "-createdirs:1", "-csvsep:1"]
    if any(str(value).startswith("-threads") for value in command):
        raise FineMotiveError("official PartVTKOut command must not contain -threads")
    environment = os.environ.copy()
    environment["OMP_NUM_THREADS"] = "1"
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=900, env=environment)
    except subprocess.TimeoutExpired as exc:
        raise FineMotiveError("official PartVTKOut timed out") from exc
    if completed.returncode != 0:
        raise FineMotiveError(f"official PartVTKOut failed: {completed.returncode}: {completed.stderr[-1000:]}")
    if not csv_path.is_file() or not resume_path.is_file():
        raise FineMotiveError("official PartVTKOut did not produce CSV/resume")
    runparts = parse_runparts(paths["runparts"])
    runout = parse_runout(paths["run_out"])
    rows = parse_native_csv(csv_path, generated["fluid_blocks"])
    attach_saved_brackets(rows, runparts)
    if len(rows) != runparts["totals"]["NpOut"]:
        raise FineMotiveError("native CSV row count differs from cumulative RunPARTs NpOut")
    motive_counts = Counter(row["motive"] for row in rows)
    for motive, field in (("position", "NpOutPos"), ("density", "NpOutRho"), ("movement", "NpOutMov")):
        if motive_counts.get(motive, 0) != runparts["totals"][field]:
            raise FineMotiveError(f"native CSV {motive} count differs from RunPARTs {field}")
    after = {role: stat_ref(paths[role], role, allow_payload=(role == "raw_partout")) for role in ("raw_partout", "runparts", "run_out", "generated_xml")}
    if before != after:
        raise FineMotiveError("terminal inputs changed during PartVTKOut")
    total_lower_bound = len(rows) * generated["massfluid_kg"]
    whole_initial = generated["fluid_count"] * generated["massfluid_kg"]
    unknown_fraction = total_lower_bound / whole_initial if whole_initial else math.nan
    report = {
        "schema": OUTPUT_SCHEMA,
        "status": "COMPLETED_F3_S2_FINE_NATIVE_IDENTITY_MOTIVE_AUDIT",
        "case": manifest["case"],
        "terminal_binding": {
            "receipt": records["terminal_receipt"],
            "solver_output_root": str(paths["solver_output_root"]),
            "request_chain": terminal_receipt.get("request"),
        },
        "source_bindings": {role: records[role] for role in ("root170_request", "root170_checkpoint", "current336", "historic_scan", "historic_scan_receipt", "source_xml", "official_partvtkout", "official_dsph_config", "generated_xml", "raw_partout", "runparts", "run_out")},
        "decoder": {"binary": records["official_partvtkout"], "command": command, "returncode": completed.returncode, "stdout_tail": completed.stdout[-2000:], "stderr_tail": completed.stderr[-2000:], "csv": stat_ref(csv_path, "decoder_csv"), "resume": stat_ref(resume_path, "decoder_resume"), "threads_flag_present": False},
        "generated_particles": generated,
        "runparts": {"records": len(runparts["rows"]), "last_saved_time_s": runparts["last_time_s"], "cumulative_counters": runparts["totals"], "final_record": runparts["rows"][-1]},
        "run_out": runout,
        "native_identity": {"row_count": len(rows), "rows": rows, "motive_counts": dict(sorted(motive_counts.items())), "authority": "official PartVTKOut CSV Idp/Motive joined to generated XML fluid blocks and RunPARTs", "aggregate_counters_do_not_create_rows": True},
        "lifecycle_censoring": {
            "full_per_id_lifecycle": "NOT_EXPOSED_BY_PARTOUT_ONLY",
            "ids_absent_from_partout": "NO_MOTIVE_ASSIGNED",
            "first_missing_time": "saved-record bracket only",
            "continuous_event_time": "UNKNOWN",
            "repeated_crossings_or_reentry": "UNKNOWN",
            "unmatched_identity_count": "NOT_COMPUTED_WITHOUT_FULL_LIFECYCLE_SOURCE",
            "native_rows_are_not_physical_loss": True,
        },
        "mass_screen": {"whole_initial_xml_mass_kg": whole_initial, "native_partout_lower_bound_mass_kg": total_lower_bound, "fraction_of_xml_whole": unknown_fraction, "frozen_unknown_fraction_limit": 0.003, "status": "PASS_ONLY_LOWER_BOUND_SCREEN" if unknown_fraction <= 0.003 else "FAIL", "qualification_credit": "NONE"},
        "source_cause": {"native_numerical_causes": dict(sorted(motive_counts.items())), "physical_fate": "UNKNOWN", "legal_outflow_or_spill": "UNKNOWN", "wall_contact": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "input_stability": {"pre": before, "post": after, "all_equal": before == after},
        "read_policy": {"trajectory_h5_opened": False, "part_frames_opened": False, "generated_bi4_decoded": False, "raw_partout_opened_by_official_decoder": True, "runparts_opened": True, "run_out_opened": True, "solver_started": False, "model_or_cfd_started": False, "old_products_modified": False},
    }
    atomic_json(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--root170-request", required=True, type=Path)
    prep.add_argument("--root170-checkpoint", required=True, type=Path)
    prep.add_argument("--current", required=True, type=Path)
    prep.add_argument("--scan", required=True, type=Path)
    prep.add_argument("--scan-receipt", required=True, type=Path)
    prep.add_argument("--detail-card", required=True, type=Path)
    prep.add_argument("--source-xml", required=True, type=Path)
    prep.add_argument("--output-manifest", required=True, type=Path)
    prep.add_argument("--output-request", required=True, type=Path)
    prep.add_argument("--worker", required=True, type=Path)
    aud = sub.add_parser("audit")
    aud.add_argument("--manifest", required=True, type=Path)
    aud.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(root170_request=args.root170_request, root170_checkpoint=args.root170_checkpoint, current=args.current, scan=args.scan, scan_receipt=args.scan_receipt, detail_card=args.detail_card, source_xml=args.source_xml, output_manifest=args.output_manifest, output_request=args.output_request, worker=args.worker)
            print(json.dumps({"status": "WAITING_FOR_ROOT170_TERMINAL_BINDING", "launch_allowed": False}, sort_keys=True))
        else:
            result = audit(args.manifest, args.output)
            print(json.dumps({"schema": result["schema"], "status": result["status"], "rows": result["native_identity"]["row_count"]}, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"F3-S2 fine native motive audit failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

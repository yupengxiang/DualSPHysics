#!/usr/bin/env python3
"""Run and independently verify a tiny official BI4 serialization chain.

The chain is intentionally a manufactured calibration fixture.  ``prepare``
hashes only source/tools and writes a bounded request.  ``run`` compiles the
official ``JBinaryData`` sources in a private temporary attempt directory,
writes a tiny BI4 with a float-to-double-widened ``MassFluid``, reads it back
with the official library, and invokes the pinned official ``bi4_dump``.  It
never opens a DS-DATA-02 production payload.  ``verify`` independently checks
the resulting XML/arrays and all source/output identity edges.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from typing import Any


SCRIPT = Path(__file__).resolve()
HARNESS = SCRIPT.parent / "native/ds_data02_native_massfluid_official_tiny_writer.cpp"
OFFICIAL_ROOT = Path("/home/jade/Projects/DualSPHysics")
PRIMARY_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
OFFICIAL_SOURCE = OFFICIAL_ROOT / "src/source"
DECODER = OFFICIAL_ROOT / "lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump"
DECODER_SOURCE = OFFICIAL_ROOT / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
VENV = OFFICIAL_ROOT / "lagrangian-fluid-lab/.venv/bin/python"
CONFIG = OFFICIAL_ROOT / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"
RUNTIME = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
DISPATCH = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
JBD_SOURCE_FILES = (
    "JBinaryData.cpp", "JBinaryData.h", "TypesDef.h", "JObject.cpp", "JObject.h",
    "JException.cpp", "JException.h", "RunExceptionDef.h", "Functions.cpp", "Functions.h",
)
WRITER_PROFILE_FILES = ("JPartDataBi4.cpp", "JPartDataBi4.h")
XML_MASSFLUID = 0.000681472
NATIVE_MASSFLUID = struct.unpack("<f", struct.pack("<f", XML_MASSFLUID))[0]
NATIVE_MASSFLUID_BITS = struct.unpack("<Q", struct.pack("<d", float(NATIVE_MASSFLUID)))[0]
SCHEMA = "ds02.stage2.native-massfluid-official-tiny-chain.v1"
REQUEST_SCHEMA = "ds02.request.v1"
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_STATIC_BYTES = 32 * 1024 * 1024


class ChainError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ChainError(f"{label} must be a SHA-256 digest")
    return value.lower()


def require_file(value: Any, label: str, *, max_bytes: int = MAX_STATIC_BYTES) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise ChainError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ChainError(f"{label} is missing: {path}")
    if path.stat().st_size > max_bytes:
        raise ChainError(f"{label} exceeds bounded static size: {path}")
    return path


def stat_ref(path: Path, role: str) -> dict[str, Any]:
    value = path.stat()
    return {
        "role": role, "path": str(path.resolve()), "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev), "st_ino": int(value.st_ino),
    }


def static_ref(path: Path, role: str) -> dict[str, Any]:
    path = require_file(path, role)
    ref = stat_ref(path, role)
    ref.update({"sha256": sha256_file(path), "content_read_by_preparer": True})
    return ref


def json_object(path: Path, label: str) -> dict[str, Any]:
    path = require_file(path, label, max_bytes=MAX_JSON_BYTES)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ChainError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ChainError(f"{label} must be an object")
    return value


def atomic_json(path: Path, value: dict[str, Any], max_bytes: int = MAX_JSON_BYTES) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise ChainError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > max_bytes:
            raise ChainError(f"output exceeds bounded JSON size: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def official_refs() -> list[dict[str, Any]]:
    refs = [static_ref(HARNESS, "tiny official writer harness"), static_ref(DECODER, "official bi4_dump decoder"), static_ref(DECODER_SOURCE, "bi4_dump source")]
    for name in JBD_SOURCE_FILES + WRITER_PROFILE_FILES:
        refs.append(static_ref(OFFICIAL_SOURCE / name, f"official source {name}"))
    for path, role in ((VENV, "literal Python"), (CONFIG, "official runtime config"), (RUNTIME, "runtime v8"), (DISPATCH, "dispatch v8"), (STRICT, "strict dispatch v8")):
        refs.append(static_ref(path, role))
    return refs


def require_static_refs(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    refs = manifest.get("static_source_refs")
    if not isinstance(refs, list) or not refs:
        raise ChainError("manifest static_source_refs is missing")
    by_path: dict[str, dict[str, Any]] = {}
    for value in refs:
        if not isinstance(value, dict):
            raise ChainError("static source ref is not an object")
        path = require_file(value.get("path"), "manifest static source")
        expected = digest(value.get("sha256"), f"static source {path} SHA")
        actual = sha256_file(path)
        if actual != expected:
            raise ChainError(f"static source changed: {path}")
        key = str(path)
        if key in by_path and by_path[key]["sha256"] != expected:
            raise ChainError(f"conflicting static source ref: {path}")
        by_path[key] = {**value, "path": key, "sha256": expected}
    return by_path


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    refs = official_refs()
    manifest_path = output_dir / "native-massfluid-official-tiny-chain-manifest.json"
    manifest = {
        "schema": SCHEMA + ".manifest",
        "status": "SOURCE_PREPARED_MANUFACTURED_CALIBRATION_NOT_RUN",
        "case_id": "MANUFACTURED_NATIVE_MASSFLUID_SERIALIZATION_TINY",
        "static_source_refs": refs,
        "writer_contract": {
            "writer": "official JBinaryData API compiled from pinned source",
            "massfluid_xml_reference": XML_MASSFLUID,
            "massfluid_observed_contract": "float32(XML MassFluid) widened to binary64 JBinaryData value",
            "arrays": {"Idp": "uint", "Pos": "float3", "Vel": "float3", "Rhop": "float", "Mass": "float"},
            "reader": "same official JBinaryData LoadFile/GetvDouble after SaveFile",
            "external_decoder": "pinned official bi4_dump; binary-to-source build provenance remains UNKNOWN",
        },
        "read_policy": {"production_payload_opened": False, "production_solver_started": False, "temporary_fixture_only": True, "decoder_input_created_by_worker": True},
        "claim_boundary": {"manufactured_serialization_only": True, "native_massfluid_restoration": "serialization_contract_only", "physical_case": "NONE", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "production_eligible": False},
        "output": {"path": "{attempt_root}/native-massfluid-official-tiny-chain.json", "max_bytes": MAX_OUTPUT_BYTES},
    }
    atomic_json(manifest_path, manifest)
    manifest_ref = static_ref(manifest_path, "tiny chain manifest")
    refs_with_manifest = refs + [manifest_ref]
    by_path = {ref["path"]: ref["sha256"] for ref in refs_with_manifest}
    request_path = output_dir / "native-massfluid-official-tiny-chain-request.json"
    venv_ref = next(ref for ref in refs_with_manifest if Path(ref["path"]).resolve() == VENV.resolve())
    request = {
        "schema": REQUEST_SCHEMA,
        "shared_runtime_version": "v8",
        "request_id": "native-massfluid-official-tiny-chain-v1-source-prepared-001",
        "family_id": "infra", "case_id": "MANUFACTURED_NATIVE_MASSFLUID_SERIALIZATION_TINY",
        "attempt_id": "native-massfluid-official-tiny-chain-v1-source-prepared-001",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 180, "max_memory_bytes": 512 * 1024 * 1024, "estimated_storage_bytes": 16 * 1024 * 1024,
        "estimated_cpu_core_hours": 0.02, "estimated_gpu_seconds": 0,
        "cwd": str(OFFICIAL_ROOT), "worktree_root": str(OFFICIAL_ROOT),
        "command": [str(VENV), "-B", str(SCRIPT), "run", "--manifest", str(manifest_path), "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/native-massfluid-official-tiny-chain.json"],
        "input_files": sorted(by_path), "input_sha256": by_path,
        "deferred_input_files": [], "deferred_input_records": [],
        "output_files": ["{attempt_root}/native-massfluid-official-tiny-chain.json"],
        "manifest_contract": {"path": str(manifest_path), "sha256": manifest_ref["sha256"]},
        "interpreter_binding": {"literal_path": str(VENV), "resolved_path": venv_ref["path"], "sha256": venv_ref["sha256"]},
        "source_read_cost": {"production_payload_bytes": 0, "temporary_bi4_bytes": "created_after_start", "official_decoder_passes": 1, "compiler_passes": 1, "output_cap_bytes": MAX_OUTPUT_BYTES},
        "read_policy": manifest["read_policy"], "claim_boundary": manifest["claim_boundary"],
        "launch_allowed": False, "execution_allowed": True, "launch_owner": "root", "shared_lease_required": False,
        "status": "SOURCE_PREPARED_MANUFACTURED_CALIBRATION_NOT_RUN",
    }
    atomic_json(request_path, request)
    gap_path = output_dir / "native-massfluid-official-tiny-chain-gap-report.json"
    gap = {"schema": SCHEMA + ".gap-report", "status": "SOURCE_PREPARED_MANUFACTURED_CALIBRATION_NOT_RUN", "manifest": {"path": str(manifest_path), "sha256": manifest_ref["sha256"]}, "request": {"path": str(request_path), "sha256": sha256_file(request_path)}, "binary_build_provenance": "UNKNOWN", "production_payload_opened": False, "scientific_credit": 0, "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    atomic_json(gap_path, gap)
    return {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": manifest_ref["sha256"], "request": str(request_path), "request_sha256": sha256_file(request_path), "gap_report": str(gap_path), "gap_report_sha256": sha256_file(gap_path), "production_payload_opened": False}


def parse_writer_stdout(value: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, raw in re.findall(r"(writer_massfluid|writer_massfluid_bits|reader_massfluid|idp_count|pos_type|vel_type|rhop_type|mass_type)=([^\s]+)", value):
        if key.endswith("_bits") or key == "idp_count":
            result[key] = int(raw, 16) if key.endswith("_bits") else int(raw)
        elif key.endswith("_type"):
            result[key] = raw
        else:
            result[key] = float(raw)
    required = {"writer_massfluid", "writer_massfluid_bits", "reader_massfluid", "idp_count", "pos_type", "vel_type", "rhop_type", "mass_type"}
    if set(result) != required:
        raise ChainError(f"official writer stdout lacks fields: {sorted(required - set(result))}")
    return result


def run_chain(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = require_file(args.manifest, "tiny chain manifest", max_bytes=MAX_JSON_BYTES)
    manifest = json_object(manifest_path, "tiny chain manifest")
    if manifest.get("schema") != SCHEMA + ".manifest" or manifest.get("status") not in {"SOURCE_PREPARED_MANUFACTURED_CALIBRATION_NOT_RUN", "READY_FOR_MANUFACTURED_CALIBRATION"}:
        raise ChainError("manifest is not a prepared tiny calibration manifest")
    static = require_static_refs(manifest)
    attempt_root = Path(args.attempt_root).expanduser().resolve()
    if attempt_root.exists() and any(attempt_root.iterdir()):
        raise ChainError(f"attempt root must be fresh: {attempt_root}")
    attempt_root.mkdir(parents=True, exist_ok=True)
    artifact_dir = attempt_root / "tiny-chain-artifacts"
    artifact_dir.mkdir()
    writer_source = require_file(next(ref["path"] for ref in static.values() if ref.get("role") == "tiny official writer harness"), "writer source")
    decoder = require_file(next(ref["path"] for ref in static.values() if ref.get("role") == "official bi4_dump decoder"), "official decoder")
    output_bi4 = artifact_dir / "tiny.bi4"
    binary = artifact_dir / "tiny-writer-reader"
    compile_command = ["g++", "-std=c++11", "-O2", "-ffunction-sections", "-fdata-sections", "-I", str(OFFICIAL_SOURCE), str(writer_source), str(OFFICIAL_SOURCE / "JBinaryData.cpp"), str(OFFICIAL_SOURCE / "JObject.cpp"), str(OFFICIAL_SOURCE / "JException.cpp"), str(OFFICIAL_SOURCE / "Functions.cpp"), "-Wl,--gc-sections", "-o", str(binary)]
    started = time.monotonic()
    compile_result = subprocess.run(compile_command, text=True, capture_output=True, check=False)
    if compile_result.returncode != 0:
        raise ChainError(f"official tiny writer compilation failed: {compile_result.stderr[-2000:]}")
    writer_result = subprocess.run([str(binary), str(output_bi4)], text=True, capture_output=True, check=False)
    if writer_result.returncode != 0:
        raise ChainError(f"official tiny writer/reader failed: {writer_result.stderr[-2000:]}")
    observed = parse_writer_stdout(writer_result.stdout)
    decode_root = artifact_dir / "decoded"
    decoder_result = subprocess.run([str(decoder), str(output_bi4), str(decode_root)], text=True, capture_output=True, check=False)
    if decoder_result.returncode != 0:
        raise ChainError(f"official bi4_dump failed: {decoder_result.stderr[-2000:]}")
    xml_path = artifact_dir / "decoded.xml"
    if not xml_path.is_file():
        raise ChainError("official decoder did not produce decoded XML")
    xml = ET.parse(xml_path).getroot()
    mass_nodes = [node for node in xml.iter("double") if node.get("name") == "MassFluid"]
    if len(mass_nodes) != 1:
        raise ChainError("official decoded XML has no unique MassFluid double")
    array_types = {node.get("name"): node.tag.removeprefix("array_") for node in xml.iter() if node.tag.startswith("array_")}
    expected_arrays = {"Idp": "uint", "Pos": "float3", "Vel": "float3", "Rhop": "float", "Mass": "float"}
    if array_types != expected_arrays:
        raise ChainError(f"official decoded array types differ: {array_types}")
    output_refs = []
    for path in sorted(artifact_dir.rglob("*")):
        if path.is_file():
            output_refs.append({**stat_ref(path, "tiny chain output"), "sha256": sha256_file(path), "content_read_by_worker": True})
    report = {
        "schema": SCHEMA, "status": "COMPLETED_MANUFACTURED_SERIALIZATION_CALIBRATION_ONLY", "manufactured_fixture": True, "production_eligible": False, "scientific_credit": 0,
        "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
        "attempt_root": str(attempt_root),
        "compiler": {"command": compile_command, "returncode": compile_result.returncode, "stderr_tail": compile_result.stderr[-2000:], "writer_binary": {**stat_ref(binary, "compiled writer"), "sha256": sha256_file(binary)}},
        "writer_reader": {"argv": [str(binary), str(output_bi4)], "returncode": writer_result.returncode, "stdout": writer_result.stdout, "stderr": writer_result.stderr, "observed": observed, "writer_reader_massfluid_bits_match": observed["writer_massfluid_bits"] == NATIVE_MASSFLUID_BITS and observed["writer_massfluid"] == observed["reader_massfluid"]},
        "decoder": {"path": str(decoder), "sha256": static[str(decoder)]["sha256"], "argv": [str(decoder), str(output_bi4), str(decode_root)], "returncode": decoder_result.returncode, "stdout": decoder_result.stdout, "stderr": decoder_result.stderr, "xml_massfluid_text": mass_nodes[0].get("v"), "array_types": array_types, "output_root": str(artifact_dir / "decoded")},
        "observations": {"xml_reference_massfluid": XML_MASSFLUID, "float32_widened_massfluid": NATIVE_MASSFLUID, "float32_widened_binary64_bits": NATIVE_MASSFLUID_BITS, "decoded_massfluid_is_float32_widened": float(mass_nodes[0].get("v")) == NATIVE_MASSFLUID, "initial_case_or_solver": "NONE"},
        "outputs": output_refs,
        "source_provenance": {"official_writer_api": "JBinaryData direct API; JPartDataBi4 ConfigCtes callsite statically pinned but not invoked by this manufactured harness", "official_decoder_binary_build_provenance": "UNKNOWN", "production_payload_opened": False},
        "source_read_cost": {"production_payload_bytes": 0, "temporary_bi4_bytes": output_bi4.stat().st_size, "decoder_passes": 1, "wall_seconds": time.monotonic() - started},
        "claim_boundary": {"serialization_contract": "OBSERVED_MANUFACTURED_ONLY", "native_massfluid_restoration_for_real_case": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    output_path = Path(args.output).expanduser().resolve()
    atomic_json(output_path, report, MAX_OUTPUT_BYTES)
    return {"status": report["status"], "output": str(output_path), "production_eligible": False, "scientific_credit": 0, "temporary_bi4_bytes": output_bi4.stat().st_size}


def verify(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = require_file(args.manifest, "tiny chain manifest", max_bytes=MAX_JSON_BYTES)
    report_path = require_file(args.report, "tiny chain report", max_bytes=MAX_JSON_BYTES)
    manifest = json_object(manifest_path, "tiny chain manifest")
    report = json_object(report_path, "tiny chain report")
    if manifest.get("schema") != SCHEMA + ".manifest" or report.get("schema") != SCHEMA or report.get("status") != "COMPLETED_MANUFACTURED_SERIALIZATION_CALIBRATION_ONLY":
        raise ChainError("tiny chain schema/status is not complete")
    if report.get("manufactured_fixture") is not True or report.get("production_eligible") is not False or report.get("scientific_credit") != 0:
        raise ChainError("manufactured calibration boundary was overstated")
    static = require_static_refs(manifest)
    if report.get("manifest", {}).get("path") != str(manifest_path) or digest(report.get("manifest", {}).get("sha256"), "report manifest SHA") != sha256_file(manifest_path):
        raise ChainError("report does not bind the supplied manifest")
    observed = report.get("writer_reader", {}).get("observed")
    if not isinstance(observed, dict) or observed.get("writer_massfluid_bits") != NATIVE_MASSFLUID_BITS or observed.get("writer_massfluid") != observed.get("reader_massfluid"):
        raise ChainError("writer/readback MassFluid evidence is inconsistent")
    decoder = report.get("decoder")
    if not isinstance(decoder, dict) or decoder.get("returncode") != 0 or decoder.get("sha256") != static.get(str(Path(decoder.get("path", "")).resolve()), {}).get("sha256"):
        raise ChainError("decoder identity/result is not source-bound")
    xml_path = Path(report.get("attempt_root", "")).resolve() / "tiny-chain-artifacts/decoded.xml"
    if not xml_path.is_file():
        raise ChainError("decoded XML is missing")
    xml = ET.parse(xml_path).getroot()
    values = [node.get("v") for node in xml.iter("double") if node.get("name") == "MassFluid"]
    if values != [format(NATIVE_MASSFLUID, ".15E")]:
        # The official formatter may retain one more significant digit.  Parse
        # the value, but require exact binary64 equality with the source contract.
        if len(values) != 1 or float(values[0]) != NATIVE_MASSFLUID:
            raise ChainError("decoded XML MassFluid differs from float32-widened contract")
    arrays = decoder.get("array_types")
    if arrays != {"Idp": "uint", "Pos": "float3", "Vel": "float3", "Rhop": "float", "Mass": "float"}:
        raise ChainError("decoded array type map is inconsistent")
    output_path = Path(args.output).expanduser().resolve()
    value = {"schema": SCHEMA + ".verification", "status": "VERIFIED_MANUFACTURED_SERIALIZATION_ONLY", "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)}, "report": {"path": str(report_path), "sha256": sha256_file(report_path)}, "production_eligible": False, "scientific_credit": 0, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "claim_boundary": "official writer/readback/decoder contract only; no real-case or physical credit"}
    atomic_json(output_path, value, MAX_OUTPUT_BYTES)
    return {"status": value["status"], "output": str(output_path), "production_eligible": False, "scientific_credit": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--output-dir", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--attempt-root", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    ver = sub.add_parser("verify")
    ver.add_argument("--manifest", type=Path, required=True)
    ver.add_argument("--report", type=Path, required=True)
    ver.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = prepare(args) if args.command == "prepare" else run_chain(args) if args.command == "run" else verify(args)
    except (ChainError, OSError, subprocess.SubprocessError, ET.ParseError) as exc:
        print(f"native-massfluid-official-tiny-chain: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

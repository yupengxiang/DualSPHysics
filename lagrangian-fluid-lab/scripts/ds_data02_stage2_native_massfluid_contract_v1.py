#!/usr/bin/env python3
"""Prepare and verify a source-bound native ``MassFluid`` contract.

The worker consumes a small, guarded observation produced by a parent native
reader.  It deliberately does not open a BI4/HDF5 payload itself.  This keeps
the source preparation useful before a parent reservation while making the
eventual observation strict: one header scalar, its exact bits, its producer
receipt, and its CURRENT/physical-case identity must agree.  A mean, a
baseline copied from another case, or a dynamic-mass row is rejected or kept
UNKNOWN.

The contract also records the official writer/reader path and a small unit
calibration.  HDF5 ``units_json`` declarations are treated as declarations;
they do not establish unit authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2_ROOT = PRIMARY_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT_DEFAULT = STAGE2_ROOT / "CURRENT336.json"
PROOF_DEFAULT = STAGE2_ROOT / "checkpoints/F2_FIRST_RAW_MASS_SCALAR_V7_ACTUAL_SOURCE_ENCODING_ROOT_VERIFICATION_125.json"
REPORT_DEFAULT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_COARSE_RAW_HEADER_V7_ROOT_125/"
    "f2-coarse-raw-header-v7-root-125-001-root-forward-030-001/"
    "f2-coarse-raw-header-v7.json"
)
STREAM_REPORT_DEFAULT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_COARSE_ACTIVE_STREAM_V8_ROOT_126/"
    "f2-coarse-full-stream-v8-root-126-001-root-forward-030-001/"
    "f2-coarse-active-stream-v8.json"
)
PYTHON_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
RUNTIME_DEFAULT = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
DISPATCH_DEFAULT = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT_DEFAULT = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
CONFIG_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")
BI4_DUMP_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTKOUT_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64")
SOURCE_ROOT_DEFAULT = PRIMARY_ROOT / "src/source"
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
REQUEST_SCHEMA = "ds02.request.v1"
CONTRACT_SCHEMA = "ds02.stage2.native-massfluid-contract.v1"
OBSERVATION_SCHEMA = "ds02.stage2.native-massfluid-observation.v1"
REPORT_SCHEMA = "ds02.stage2.native-massfluid-report.v1"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
TYPE_CODES = {0: "fixed", 1: "moving", 2: "floating", 3: "fluid"}


class MassFluidContractError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise MassFluidContractError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise MassFluidContractError(f"{label} is not hexadecimal")
    return value


def path_file(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise MassFluidContractError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise MassFluidContractError(f"{label} is missing: {path}")
    return path


def path_dir(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise MassFluidContractError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise MassFluidContractError(f"{label} is missing: {path}")
    return path


def stat_ref(path: Path, role: str) -> dict[str, Any]:
    value = path.stat()
    return {
        "role": role,
        "path": str(path.resolve()),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def static_ref(value: Any, role: str, expected_sha: Any = None, *, allow_binary: bool = True) -> dict[str, Any]:
    path = path_file(value, role)
    if path.suffix.lower() in {".h5", ".hdf5", ".bi4", ".obi4"}:
        raise MassFluidContractError(f"payload cannot be a static source: {path}")
    if not allow_binary and not path.suffix.lower() in {".json", ".jsonl", ".py", ".h", ".cpp", ".cu", ".xml", ".txt"}:
        raise MassFluidContractError(f"unexpected static binary: {path}")
    actual = sha256_file(path)
    if expected_sha is not None and actual != require_sha(expected_sha, f"{role} expected SHA"):
        raise MassFluidContractError(f"{role} changed: {path}")
    return {**stat_ref(path, role), "sha256": actual, "content_read_by_preparer": True}


def read_json(path_value: Any, label: str) -> tuple[Path, dict[str, Any], str]:
    path = path_file(path_value, label)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise MassFluidContractError(f"{label} exceeds bounded JSON size")
    before = stat_ref(path, label)
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MassFluidContractError(f"{label} is invalid JSON") from exc
    after = stat_ref(path, label)
    if before != after:
        raise MassFluidContractError(f"{label} changed during metadata read")
    if not isinstance(value, dict):
        raise MassFluidContractError(f"{label} must be an object")
    return path, value, hashlib.sha256(payload).hexdigest()


def atomic_json(path: Path, value: dict[str, Any], max_bytes: int = MAX_JSON_BYTES) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise MassFluidContractError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > max_bytes:
            raise MassFluidContractError(f"output exceeds bounded JSON size: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def float32_widened_bits(value: float) -> tuple[float, str]:
    narrowed = struct.unpack("<f", struct.pack("<f", float(value)))[0]
    return narrowed, struct.pack("<d", float(narrowed)).hex()


def finite_positive(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
        raise MassFluidContractError(f"{label} must be finite and positive")
    return float(value)


def calibration_fixture() -> dict[str, Any]:
    xml_mass = 0.000681472
    narrowed, bits = float32_widened_bits(xml_mass)
    # These are deliberately non-zero/non-unit values: an identity calibration
    # cannot expose an accidental axis, sign, or precision swap.
    return {
        "schema": "ds02.stage2.native-unit-calibration.v1",
        "status": "TEST_ONLY_SOURCE_CONVERSION_CALIBRATION",
        "authority": "source_contract_only; not a production measurement",
        "massfluid_xml": {"value": xml_mass, "unit": "kg", "solver_storage": "float32", "writer_storage": "DatDouble", "float32_widened_value": narrowed, "binary64_little_hex": bits},
        "arrays": {
            "position": {"input": [0.123456789, -0.03125, 0.987654321], "unit": "m", "writer_type": "DatFloat3_or_DatDouble3_by_SvPosDouble", "observed_float32_widened": [float32_widened_bits(v)[0] for v in (0.123456789, -0.03125, 0.987654321)]},
            "velocity": {"input": [-1.25, 0.0625, 2.375], "unit": "m/s", "writer_type": "DatFloat3", "observed_float32": [float32_widened_bits(v)[0] for v in (-1.25, 0.0625, 2.375)]},
            "density": {"input": 998.125, "unit": "kg/m^3", "writer_type": "DatFloat", "observed_float32": float32_widened_bits(998.125)[0]},
            "particle_mass": {"input": 0.004812345, "unit": "kg", "writer_type": "DatFloat_when_splitting", "observed_float32": float32_widened_bits(0.004812345)[0]},
            "pressure": {"input": 101325.25, "unit": "Pa", "writer_type": "NOT_IN_NATIVE_BI4_MAIN_ARRAYS", "authority": "H5_protocol_declaration_only"},
            "roles": {"codes": [0, 1, 2, 3], "names": ["fixed", "moving", "floating", "fluid"], "identity": "JSph Idp ranges / Type output; not an independent native type field"},
            "mk": {"codes": [1, 2, 3], "identity": "JPartDataHead MkBlocks / JSphMk mapping; independent payload validation required"},
        },
        "h5_units_attr_authority": "DECLARATION_ONLY",
    }


SOURCE_SPECS = (
    ("jcase_ctes_source", "JCaseCtes.cpp", "XML ReadElementDouble massfluid; WriteXmlElementAuto kg"),
    ("jsph_source", "JSph.cpp", "LoadConfigCtes float cast; ConfigSaveData/JPartData arrays"),
    ("jsph_header", "JSph.h", "MassFluid solver storage float"),
    ("jpartdatahead_source", "JPartDataHead.cpp", "ConfigCtes/SaveFile/LoadFile MassFluid DatDouble"),
    ("jpartdatahead_header", "JPartDataHead.h", "MassFluid field and MkBlock roles"),
    ("jpartdata_source", "JPartDataBi4.cpp", "ConfigCtes SetvDouble; LoadFileData reader; AddPartData array types"),
    ("jpartdata_header", "JPartDataBi4.h", "Get_MassFluid and typed array readers"),
    ("jbinarydata_source", "JBinaryData.cpp", "DatDouble In/Out and SetvDouble"),
    ("jbinarydata_header", "JBinaryData.h", "DatDouble declarations"),
    ("functions_header", "Functions.h", "float/double type definitions"),
    ("functions_source", "Functions.cpp", "numeric serialization helpers"),
)


def source_map(source_root: Path, *, extra: list[tuple[str, Path]] | None = None) -> dict[str, dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    for role, filename, semantic in SOURCE_SPECS:
        path = path_file(source_root / filename, f"official {role}")
        refs[role] = {**static_ref(path, role), "source_role": role, "semantic_anchor": semantic}
    for role, path in extra or []:
        refs[role] = {**static_ref(path, role), "source_role": role}
    return refs


def source_contract_map() -> dict[str, Any]:
    return {
        "xml_to_solver": "JCaseCtes::LoadXmlRun ReadElementDouble -> JSph::LoadConfigCtes casts MassFluid to float",
        "solver_to_header": "JSph::ConfigSaveData -> JPartDataHead::ConfigCtes -> JPartDataBi4::ConfigCtes -> Data->SetvDouble(\"MassFluid\")",
        "header_write": "JBinaryData::InValue DatDouble -> InDouble; root VALUES sequence, little endian",
        "header_read": "JPartDataBi4::LoadFileData -> JBinaryData::OpenFileStructure; GetvDouble(\"MassFluid\")",
        "particle_arrays": {
            "position": "JSph SaveData uses Pos Double3 then optionally GetPointerDataFloat3; BI4 writes Posd DatDouble3 or Pos DatFloat3",
            "velocity": "JPartDataBi4::AddPartData writes Vel DatFloat3",
            "density": "JPartDataBi4::AddPartData writes Rhop DatFloat",
            "particle_mass": "JPartDataBi4::AddPartDataSplitting writes Mass DatFloat only when splitting is configured",
            "pressure": "not a native BI4 main array; H5 producer protocol only",
            "role": "JSph CSV Type is derived from Idp ranges; native BI4 MkBlocks are header metadata",
            "mk": "JPartDataHead MkBlocks and JSphMk mapping; independently decoded role/MK authority remains case-specific",
        },
        "unit_authority": "official source path is required; H5 units attributes are declarations only",
    }


def _proof_report_contract(proof: dict[str, Any], report: dict[str, Any], proof_path: Path, report_path: Path, stream: dict[str, Any] | None, stream_path: Path | None) -> dict[str, Any]:
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or proof.get("guarded_receipt_status") != "completed" or proof.get("outer_unit_result") != "success":
        raise MassFluidContractError("producer proof is not completed")
    if report.get("schema") != "ds02.stage2.f2.coarse-active-stream.v7" or report.get("status") != "RAW_HEADER_SCALAR_PROOF_COMPLETED_NO_FULL_STREAM_CREDIT":
        raise MassFluidContractError("MassFluid source report is not the pinned V7 scalar report")
    if proof.get("report") != str(report_path) or require_sha(proof.get("report_sha256"), "proof report SHA") != sha256_file(report_path):
        raise MassFluidContractError("proof/report identity does not match")
    comparison = proof.get("raw_massfluid_comparison")
    if not isinstance(comparison, dict):
        raise MassFluidContractError("raw_massfluid_comparison is missing")
    expected_bits = comparison.get("raw_bytes_hex")
    if not isinstance(expected_bits, str) or len(expected_bits) != 16:
        raise MassFluidContractError("raw MassFluid bytes are missing")
    if comparison.get("matches_float32_widened_binary64") is not True or comparison.get("matches_xml_binary64") is not False:
        raise MassFluidContractError("float32-to-double encoding diagnosis is not closed")
    source = report.get("source_contract")
    if not isinstance(source, dict) or not isinstance(source.get("serialization"), dict):
        raise MassFluidContractError("source serialization contract is missing")
    if source["serialization"].get("target", {}).get("field_name") != "MassFluid":
        raise MassFluidContractError("source target is not MassFluid")
    stream_binding: dict[str, Any] = {"status": "NOT_PROVIDED", "path": None}
    if stream is not None:
        if stream.get("schema") != "ds02.stage2.f2.coarse-active-stream.v8" or not str(stream.get("status", "")).startswith("COMPLETED_"):
            raise MassFluidContractError("stream report is not completed V8")
        stream_mass = stream.get("active_fluid_stream")
        if not isinstance(stream_mass, dict):
            raise MassFluidContractError("V8 report has no active-fluid stream summary")
        if stream_mass.get("native_massfluid_bits_hex") != expected_bits:
            raise MassFluidContractError("V8 stream MassFluid bits do not match V7")
        stream_binding = {"status": "COMPLETED_NATIVE_STREAM_SUMMARY_ONLY", "path": str(stream_path), "sha256": sha256_file(stream_path), "frames": stream_mass.get("frame_count"), "type_mk_independent": False}
    return {
        "proof": static_ref(proof_path, "native_massfluid_producer_proof"),
        "report": static_ref(report_path, "native_massfluid_v7_report"),
        "stream_report": stream_binding,
        "physical_case_id": report.get("physical_case_id"),
        "case_key": report.get("case_key"),
        "raw_header": report.get("source_contract", {}).get("serialization", {}).get("target", {}),
        "raw_massfluid_comparison": comparison,
        "read_policy": {"preparer_opened_h5": False, "preparer_opened_bi4": False, "preparer_hashed_bi4": False, "future_native_observation_after_parent_reservation": True},
    }


def _current_binding(current_path: Path, physical_case_id: str | None) -> dict[str, Any]:
    current = json.loads(current_path.read_text(encoding="utf-8"))
    if current.get("schema") != "ds02.stage2.current336.v1" or sha256_file(current_path) != CURRENT_SHA256:
        raise MassFluidContractError("CURRENT catalog is not the frozen CURRENT336")
    rows = [row for row in current.get("cases", []) if isinstance(row, dict) and row.get("physical_case_id") == physical_case_id]
    if len(rows) == 1:
        return {"status": "CANONICAL_CURRENT_CASE", "physical_case_id": physical_case_id, "family_id": rows[0].get("family_id"), "current_catalog": {"path": str(current_path), "sha256": CURRENT_SHA256}, "row_present": True}
    return {"status": "REFERENCE_CASE_NOT_IN_CURRENT336", "physical_case_id": physical_case_id, "current_catalog": {"path": str(current_path), "sha256": CURRENT_SHA256}, "row_present": False}


def _request(contract_path: Path, contract: dict[str, Any], output_dir: Path, args: argparse.Namespace, static_refs: list[dict[str, Any]], source_refs: dict[str, dict[str, Any]], deferred_native: dict[str, Any] | None) -> dict[str, Any]:
    paths: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for ref in static_refs + list(source_refs.values()):
        paths[str(Path(ref["path"]).resolve())] = str(Path(ref["path"]).resolve())
        hashes[str(Path(ref["path"]).resolve())] = ref["sha256"]
    paths[str(contract_path.resolve())] = str(contract_path.resolve())
    hashes[str(contract_path.resolve())] = sha256_file(contract_path)
    worker = SCRIPT
    for path in (worker, args.runtime, args.dispatch, args.strict, args.config, args.python):
        p = path_file(path, "request source")
        paths[str(p)] = str(p)
        hashes[str(p)] = sha256_file(p)
    literal_python = Path(args.python).expanduser()
    resolved_python = path_file(literal_python, "literal Python")
    deferred = []
    deferred_records = []
    if deferred_native:
        deferred.append(deferred_native["path"])
        deferred_records.append(deferred_native)
    request = {
        "schema": REQUEST_SCHEMA,
        "shared_runtime_version": "v8",
        "status": "SOURCE_PREPARED_NATIVE_MASSFLUID_OBSERVATION_NOT_RUN",
        "request_id": "native-massfluid-contract-v1-source-prepared-001",
        "family_id": "infra",
        "case_id": "native-massfluid-contract-v1-source-prepared-001",
        "physical_case_id": contract["physical_case_id"],
        "attempt_id": "native-massfluid-contract-v1-source-prepared-001",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 900, "max_memory_bytes": 1024 * 1024 * 1024,
        "estimated_storage_bytes": MAX_OUTPUT_BYTES, "estimated_cpu_core_hours": 0.25, "estimated_gpu_seconds": 0,
        "cwd": str(PRIMARY_ROOT), "worktree_root": str(PRIMARY_ROOT),
        "command": [str(literal_python), "-B", str(worker), "audit", "--contract", str(contract_path), "--observation", "{attempt_root}/native-massfluid-observation.json", "--output", "{attempt_root}/native-massfluid-report.json"],
        "input_files": sorted(paths), "input_sha256": {key: hashes[key] for key in sorted(hashes)},
        "deferred_input_files": deferred, "deferred_input_records": deferred_records,
        "output_files": ["{attempt_root}/native-massfluid-report.json"],
        "manifest_contract": {"path": str(contract_path), "sha256": sha256_file(contract_path)},
        "interpreter_binding": {"literal_path": str(literal_python), "resolved_path": str(resolved_python), "sha256": sha256_file(resolved_python)},
        "runtime_binding": {role: {"path": str(path_file(path, role)), "sha256": sha256_file(path_file(path, role))} for role, path in (("runtime_v8", args.runtime), ("dispatch_v8", args.dispatch), ("strict_dispatch_v8", args.strict), ("official_config", args.config))},
        "resource_policy": {"cpu_threads": 1, "max_wall_seconds": 900, "max_memory_bytes": 1024 * 1024 * 1024, "output_cap_bytes": MAX_OUTPUT_BYTES, "native_payload_read_after_parent_reservation": True},
        "read_policy": contract["read_policy"], "claim_boundary": contract["claim_boundary"],
        "launch_allowed": True, "execution_allowed": True, "launch_owner": "root", "shared_lease_required": True,
    }
    return request


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    proof_path, proof, proof_sha = read_json(args.proof, "producer proof")
    report_path, report, report_sha = read_json(args.report, "V7 report")
    stream_path = stream = None
    if args.stream_report:
        stream_path, stream, _ = read_json(args.stream_report, "V8 stream report")
    current_path = path_file(args.current, "CURRENT336")
    binding = _proof_report_contract(proof, report, proof_path, report_path, stream, stream_path)
    current_binding = _current_binding(current_path, binding["physical_case_id"])
    source_root = path_dir(args.source_root, "official source root")
    extras = [("official_bi4_dump", path_file(args.bi4_dump, "official BI4 decoder")), ("official_partvtkout", path_file(args.partvtkout, "official PartVTKOut decoder"))]
    source_refs = source_map(source_root, extra=extras)
    fixture = calibration_fixture()
    output_dir = Path(args.output_dir).expanduser().resolve()
    fixture_path = output_dir / "native-unit-calibration-fixture.json"
    atomic_json(fixture_path, fixture)
    fixture_ref = static_ref(fixture_path, "unit calibration fixture")
    contract = {
        "schema": CONTRACT_SCHEMA,
        "status": "READY_PARENT_GUARDED_NATIVE_MASSFLUID_OBSERVATION",
        "physical_case_id": binding["physical_case_id"], "case_key": binding["case_key"],
        "scope": current_binding,
        "producer_binding": {**binding, "proof_sha256": proof_sha, "report_sha256": report_sha},
        "official_source_roles": source_refs,
        "source_conversion_contract": source_contract_map(),
        "unit_contract": fixture,
        "unit_authority": {"h5_units_attributes": "DECLARATION_ONLY", "native_writer_decoder_source": "SOURCE_BOUND", "pressure_and_material_semantics": "UNKNOWN_UNVERIFIED"},
        "deferred_native_observation": {"status": "PARENT_MUST_READ_AFTER_RESERVATION", "path": report.get("raw_source", {}).get("first_frame", {}).get("pre", {}).get("path"), "known_sha256": report.get("raw_source", {}).get("first_frame", {}).get("pre", {}).get("parent_full_sha256"), "content_read_by_preparer": False, "content_hashed_by_preparer": False},
        "identity_policy": {"initial_fluid_mass": "UNKNOWN_UNLESS_SINGLE_HEADER_SCALAR_AND_EXPLICIT_FLUID_ROLE_IDENTITY", "dynamic_mass": "UNKNOWN", "averages": "REJECTED", "baseline_copy": "REJECTED"},
        "read_policy": binding["read_policy"],
        "claim_boundary": {"native_massfluid_scalar": "HEADER_ENCODING_ONLY", "initial_fluid_identity": "UNKNOWN_UNLESS_EXPLICIT_IDENTITY_BINDING", "dynamic_mass": "UNKNOWN", "units": "OFFICIAL_SOURCE_CONTRACT_BOUND; H5 ATTR DECLARATION ONLY", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    contract_path = output_dir / "native-massfluid-contract.json"
    atomic_json(contract_path, contract)
    static_refs = [binding["proof"], binding["report"]]
    if binding.get("stream_report", {}).get("path"):
        static_refs.append(static_ref(binding["stream_report"]["path"], "V8 stream report", binding["stream_report"]["sha256"]))
    static_refs.extend([fixture_ref, static_ref(current_path, "CURRENT336", CURRENT_SHA256), static_ref(contract_path, "native massfluid contract")])
    deferred = contract["deferred_native_observation"] if contract["deferred_native_observation"].get("path") else None
    request = _request(contract_path, contract, output_dir, args, static_refs, source_refs, deferred)
    request_path = output_dir / "native-massfluid-request.json"
    atomic_json(request_path, request)
    report_out = {
        "schema": REPORT_SCHEMA,
        "status": "SOURCE_PREPARED_NATIVE_MASSFLUID_NOT_RUN",
        "contract": {"path": str(contract_path), "sha256": sha256_file(contract_path)},
        "request": {"path": str(request_path), "sha256": sha256_file(request_path)},
        "producer_scope": {"proof": {"path": str(proof_path), "sha256": proof_sha}, "v7_report": {"path": str(report_path), "sha256": report_sha}, "v8_stream_summary": contract["producer_binding"]["stream_report"]},
        "current_binding": current_binding,
        "source_roles": {role: {"path": value["path"], "sha256": value["sha256"], "bytes": value["bytes"]} for role, value in source_refs.items()},
        "massfluid": {"source_xml_value_kg": binding["raw_massfluid_comparison"].get("source_xml_value_kg"), "native_raw_value_kg": binding["raw_massfluid_comparison"].get("raw_value_binary64_kg"), "raw_bytes_hex": binding["raw_massfluid_comparison"].get("raw_bytes_hex"), "status": "HEADER_SCALAR_BOUND_INITIAL_FLUID_ROLE_IDENTITY_UNKNOWN"},
        "unit_authority": contract["unit_authority"],
        "read_policy": contract["read_policy"], "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "goal_complete": False,
    }
    report_path_out = output_dir / "native-massfluid-source-gap-report.json"
    atomic_json(report_path_out, report_out)
    return {"status": report_out["status"], "contract": str(contract_path), "contract_sha256": sha256_file(contract_path), "request": str(request_path), "request_sha256": sha256_file(request_path), "report": str(report_path_out), "report_sha256": sha256_file(report_path_out), "h5_or_bi4_content_read_by_preparer": False, "current_case_scope": current_binding["status"]}


def _same_ref(value: Any, expected: dict[str, Any], label: str) -> None:
    if not isinstance(value, dict) or value.get("path") != expected.get("path") or require_sha(value.get("sha256"), label) != expected.get("sha256"):
        raise MassFluidContractError(f"{label} does not bind the contract")


def verify_observation(contract_path: Path, observation_path: Path, output_path: Path) -> dict[str, Any]:
    _, contract, contract_sha = read_json(contract_path, "MassFluid contract")
    _, observation, observation_sha = read_json(observation_path, "native observation")
    if contract.get("schema") != CONTRACT_SCHEMA or observation.get("schema") != OBSERVATION_SCHEMA:
        raise MassFluidContractError("unexpected contract or observation schema")
    if observation.get("contract_sha256") != contract_sha or observation.get("physical_case_id") != contract.get("physical_case_id"):
        raise MassFluidContractError("observation contract/case binding mismatch")
    status = observation.get("status")
    allowed_unknown = {"DYNAMIC_MASS_NO_INITIAL_IDENTITY", "MISSING_INITIAL_IDENTITY", "UNKNOWN_NOT_OBSERVED"}
    result: dict[str, Any] = {"schema": REPORT_SCHEMA, "status": "UNKNOWN_NATIVE_MASSFLUID_OBSERVATION", "contract": {"path": str(Path(contract_path).resolve()), "sha256": contract_sha}, "observation": {"path": str(Path(observation_path).resolve()), "sha256": observation_sha}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    if status in allowed_unknown:
        result["native_massfluid"] = {"status": status, "value_kg": None, "initial_fluid_identity": "UNKNOWN", "physical_fate": "UNKNOWN"}
    elif status == "INITIAL_FLUID_SCALAR_BOUND":
        comparison = contract.get("producer_binding", {}).get("raw_massfluid_comparison", {})
        value = finite_positive(observation.get("massfluid_value_kg"), "observed MassFluid")
        bits = observation.get("massfluid_bits_hex")
        expected_bits = comparison.get("raw_bytes_hex")
        if bits != expected_bits or observation.get("source_kind") != "single_header_scalar" or observation.get("aggregation") not in {"none", "single_header_scalar"}:
            raise MassFluidContractError("observed MassFluid does not match the pinned scalar contract")
        identity = observation.get("initial_fluid_identity")
        if not isinstance(identity, dict) or identity.get("status") != "EXPLICIT_FLUID_ROLE_IDENTITY":
            raise MassFluidContractError("scalar cannot be credited without explicit fluid-role identity")
        if observation.get("mass_estimator") in {"mean", "average", "preserved_baseline", "role_average"}:
            raise MassFluidContractError("averaged or baseline mass is forbidden")
        refs = observation.get("producer_refs")
        if not isinstance(refs, dict) or refs.get("receipt_sha256") != contract.get("producer_binding", {}).get("proof", {}).get("sha256") and refs.get("proof_sha256") != contract.get("producer_binding", {}).get("proof", {}).get("sha256"):
            raise MassFluidContractError("observation producer receipt/proof is not bound")
        result["status"] = "COMPLETED_INITIAL_FLUID_MASSFLUID_SOURCE_BOUND_NO_SCIENTIFIC_CREDIT"
        result["native_massfluid"] = {"status": status, "value_kg": value, "bits_hex": bits, "initial_fluid_identity": identity, "physical_fate": "UNKNOWN", "dynamic_mass": "UNKNOWN"}
    else:
        raise MassFluidContractError(f"unsupported observation status: {status!r}")
    atomic_json(output_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--proof", type=Path, default=PROOF_DEFAULT)
    prep.add_argument("--report", type=Path, default=REPORT_DEFAULT)
    prep.add_argument("--stream-report", type=Path, default=STREAM_REPORT_DEFAULT)
    prep.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    prep.add_argument("--source-root", type=Path, default=SOURCE_ROOT_DEFAULT)
    prep.add_argument("--bi4-dump", type=Path, default=BI4_DUMP_DEFAULT)
    prep.add_argument("--partvtkout", type=Path, default=PARTVTKOUT_DEFAULT)
    prep.add_argument("--runtime", type=Path, default=RUNTIME_DEFAULT)
    prep.add_argument("--dispatch", type=Path, default=DISPATCH_DEFAULT)
    prep.add_argument("--strict", type=Path, default=STRICT_DEFAULT)
    prep.add_argument("--config", type=Path, default=CONFIG_DEFAULT)
    prep.add_argument("--python", type=Path, default=PYTHON_DEFAULT)
    prep.add_argument("--output-dir", type=Path, required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--contract", type=Path, required=True)
    audit.add_argument("--observation", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = prepare(args) if args.command == "prepare" else verify_observation(args.contract, args.observation, args.output)
    except (MassFluidContractError, OSError, ValueError) as exc:
        print(f"native-massfluid-contract: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

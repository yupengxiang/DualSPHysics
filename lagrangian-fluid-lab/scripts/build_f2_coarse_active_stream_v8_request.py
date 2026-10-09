#!/usr/bin/env python3
"""Build the ROOT126 source-bound V8 manifest/request without opening BI4/H5.

The builder copies the completed V4 deferred 401-frame inventory and replaces
only the consumer/provenance layer.  Deferred frame references retain their
PARENT_GUARD_COMPUTED content SHA: this script reads the manifest JSON but does
not hash or open any Part_*.bi4 file.  The ROOT125 V7 report, source contract,
and completed execution receipt are immutable small-input predecessors; their
raw scalar is used only as metadata to populate the strict V8 expected bits.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

CASE_KEY = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"
V7_SCHEMA = "ds02.stage2.f2.coarse-active-stream.v7"
V7_STATUS = "RAW_HEADER_SCALAR_PROOF_COMPLETED_NO_FULL_STREAM_CREDIT"
V8_SCHEMA = "ds02.stage2.f2.coarse-active-stream.v8"
V8_MANIFEST_SCHEMA = "ds02.stage2.f2.coarse-active-stream.manifest.v8"
V8_REQUEST_SCHEMA = "ds02.stage2.f2.coarse-active-stream.v8-request.v1"
V8_CONTRACT_SCHEMA = "ds02.stage2.f2.coarse-active-stream.v8.full-stream-contract.v1"


class BuildError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise BuildError(f"{label} does not exist: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BuildError(f"{label} is not an object: {path}")
    return value


def record(path: Path, *, parent_guard: bool = False) -> dict[str, Any]:
    if not path.is_file():
        raise BuildError(f"input is not a regular file: {path}")
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": "PARENT_GUARD_COMPUTED" if parent_guard else sha256(path),
    }


def validate_v7(report: dict[str, Any], contract: dict[str, Any], receipt: dict[str, Any], report_path: Path, contract_path: Path) -> tuple[str, float, float]:
    if report.get("schema") != V7_SCHEMA or report.get("status") != V7_STATUS:
        raise BuildError("V7 predecessor is not completed raw-scalar proof")
    if report.get("case_key") != CASE_KEY or report.get("physical_case_id") != CASE_KEY:
        raise BuildError("V7 predecessor case identity differs")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise BuildError("V7 execution receipt is not completed")
    if Path(str(receipt.get("output_root", ""))).resolve() != report_path.parent.resolve():
        raise BuildError("V7 receipt does not contain the report")
    request = receipt.get("request") or {}
    if request.get("request_schema") != "ds02.stage2.f2.coarse-active-stream.v7-request.v1" or request.get("physical_case_id") != CASE_KEY:
        raise BuildError("V7 receipt request identity differs")
    if contract.get("schema") != "ds02.stage2.f2.coarse-active-stream.v7.massfluid-source-contract.v1" or contract.get("status") != "SOURCE_BOUND_RAW_SCALAR_PROOF_ONLY":
        raise BuildError("V7 source contract is not source-bound")
    embedded = report.get("source_contract") or {}
    if (embedded.get("contract") or {}).get("sha256") != sha256(contract_path):
        raise BuildError("V7 report does not bind the supplied source contract")
    scalar = (report.get("raw_source") or {}).get("massfluid_scalar") or {}
    raw_bits = scalar.get("raw_bytes_hex")
    if not isinstance(raw_bits, str) or len(raw_bits) != 16:
        raise BuildError("V7 raw scalar bytes are absent")
    try:
        raw = bytes.fromhex(raw_bits)
    except ValueError as exc:
        raise BuildError("V7 raw scalar bytes are not hexadecimal") from exc
    if len(raw) != 8 or scalar.get("matches_v6_typed_binary64") is not True:
        raise BuildError("V7 raw scalar does not match completed typed value")
    if scalar.get("raw_bytes_sha256") != hashlib.sha256(raw).hexdigest():
        raise BuildError("V7 raw scalar SHA differs")
    if report.get("probe_scope", {}).get("remaining_frames_opened") != 0:
        raise BuildError("V7 opened frames outside first-frame scalar scope")
    if contract.get("serialization", {}).get("target", {}).get("item_path") != ["JPartDataBi4"]:
        raise BuildError("V7 official target path differs")
    return raw_bits.lower(), float(scalar["raw_value_binary64_kg"]), float(scalar["source_xml_value_kg"])


def build(args: argparse.Namespace) -> tuple[Path, Path]:
    template_path = args.template.resolve()
    template = require_json(template_path, "V4 template manifest")
    if template.get("schema") != "ds02.stage2.f2.coarse-active-stream.manifest.v4" or len(template.get("frames", [])) != 401:
        raise BuildError("V4 template is not the completed 401-frame inventory")
    report_path = args.v7_report.resolve()
    contract_path = args.v7_source_contract.resolve()
    receipt_path = args.v7_receipt.resolve()
    report = require_json(report_path, "V7 report")
    contract = require_json(contract_path, "V7 source contract")
    receipt = require_json(receipt_path, "V7 execution receipt")
    native_bits, native_mass, xml_mass = validate_v7(report, contract, receipt, report_path, contract_path)

    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "f2-coarse-active-stream-v8-manifest.json"
    request_path = out_dir / "f2-coarse-active-stream-v8-request.json"
    worker = args.worker.resolve()
    v8_contract = args.v8_contract.resolve()
    builder = Path(__file__).resolve()
    if manifest_path.exists() or request_path.exists():
        raise BuildError("refusing to overwrite ROOT126 prepared files")

    manifest = copy.deepcopy(template)
    manifest.update({
        "schema": V8_MANIFEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARDED_EXECUTION_V8_EXACT_MASS_BITS",
        "v8_contract_schema": V8_CONTRACT_SCHEMA,
        "v8_contract_sha256": sha256(v8_contract),
    })
    inputs = manifest["inputs"]
    inputs.update({
        "v7_report": record(report_path),
        "v7_source_contract": record(contract_path),
        "v7_execution_receipt": record(receipt_path),
    })
    manifest["expected"].update({
        "native_massfluid_bits_hex": native_bits,
        "native_massfluid_kg": native_mass,
        "xml_massfluid_kg": xml_mass,
        "massfluid_bit_comparison": "exact little-endian binary64 bits against V7 raw scalar on every frame",
        "whole_initial_fluid_mass_basis": "XML fluid count × XML MassFluid; frozen .003 denominator",
        "native_whole_initial_fluid_mass_basis": "XML fluid count × exact native MassFluid; diagnostic only",
    })
    manifest["decoder"].update({
        "worker": str(worker),
        "official_backend_registration": "sys.modules before dataclass import",
        "framewise_massfluid_bits": native_bits,
        "max_scratch_bytes": 134217728,
        "max_decoder_seconds_per_frame": 180,
    })
    manifest["read_policy"].update({
        "v7_report_and_receipt_read": True,
        "all_401_part_frames_opened_after_parent_reservation": True,
        "all_401_frame_full_sha_pre_post_required": True,
        "massfluid_absolute_tolerance": None,
        "massfluid_rescaling": False,
        "hdf5_opened": False,
        "solver_started": False,
        "gencase_started": False,
        "gpu_started": False,
    })
    manifest["source_scope"].update({
        "v7_raw_scalar_reported": True,
        "v7_first_frame_full_sha_origin": "V7 worker pre/post source; not a parent-provided full-frame hash",
        "v8_full_frame_sha_scope": "V8 worker pre/post full SHA for all 401 deferred Part_*.bi4 frames",
        "old_products_immutable": True,
    })
    manifest["claim_boundary"].update({
        "massfluid_framewise_bits": "SOURCE_CLOSED only after all 401 exact bit comparisons",
        "xml_native_mass_difference": "diagnostic; no mass rescale",
        "physical_destination": "UNKNOWN",
        "legal_outflow_or_spill": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
    })
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    old_request = require_json(template_path.parent / "f2-coarse-active-stream-v4-request.json", "V4 request")
    runtime_inputs = []
    for value in old_request.get("input_files", []):
        path = Path(value)
        if path.name.endswith("active_stream_v4.py"):
            continue
        if "f2-coarse-active-stream-v4-root-forward-111-001" in value:
            continue
        runtime_inputs.append(value)
    input_files = [
        str(worker), str(manifest_path), str(v8_contract), str(report_path), str(contract_path), str(receipt_path), str(builder),
    ]
    for value in runtime_inputs:
        if value not in input_files:
            input_files.append(value)
    input_hashes: dict[str, str] = {}
    for value in input_files:
        path = Path(value)
        if path.is_file() and not path.name.startswith("Part_"):
            input_hashes[str(path)] = sha256(path)

    request = {
        "request_schema": V8_REQUEST_SCHEMA,
        "schema": "ds02.runner-request.v1",
        "attempt_id": "f2-coarse-active-stream-v8-root-forward-126-001",
        "kind": "cpu",
        "cpu_task_kind": "active_frame_observation",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 10800,
        "estimated_cpu_core_hours": 3.0,
        "estimated_gpu_seconds": 0,
        "estimated_input_read_bytes": 28615302010,
        "estimated_native_read_bytes": 9538327695,
        "estimated_hdf5_read_bytes": 0,
        "estimated_storage_bytes": 268435456,
        "estimated_scratch_bytes": 134217728,
        "estimated_decoder_scratch_write_bytes": 20000000000,
        "case_id": CASE_KEY,
        "family_id": "F2",
        "physical_case_id": CASE_KEY,
        "dataset_families": ["F2"],
        "worktree_root": str(worker.parents[2].resolve()),
        "cwd": str(worker.parent.resolve()),
        "command": [
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            str(worker), "--manifest", str(manifest_path),
            "--output", "{attempt_root}/f2-coarse-active-stream-v8.json",
        ],
        "output_root": "{attempt_root}",
        "output": {"path": "{attempt_root}/f2-coarse-active-stream-v8.json", "schema": V8_SCHEMA},
        "input_files": input_files,
        "input_sha256": input_hashes,
        "input_read_policy": {
            "v7_report_contract_receipt": "small JSON only",
            "frames": "all 401 deferred raw frames after parent reservation; full pre/post SHA and decoder reads",
            "hdf5": "forbidden",
            "solver": "forbidden",
            "massfluid": "exact bits, no tolerance, no rescaling",
        },
        "source_provenance": {
            "v7_first_frame_sha_origin": "V7 worker pre/post source; parent request did not provide first-frame full SHA",
            "v8_frame_sha_origin": "V8 worker pre/post full SHA for all 401 frames",
            "official_write_path": "V7 source contract and ROOT125 report/receipt",
        },
        "hdf5_read": False,
        "solver_launch": False,
        "gencase_launch": False,
        "gpu_launch": False,
    }
    request_path.write_text(json.dumps(request, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path, request_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--v7-report", type=Path, required=True)
    parser.add_argument("--v7-source-contract", type=Path, required=True)
    parser.add_argument("--v7-receipt", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--v8-contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest, request = build(args)
    print(json.dumps({"manifest": str(manifest), "request": str(request)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

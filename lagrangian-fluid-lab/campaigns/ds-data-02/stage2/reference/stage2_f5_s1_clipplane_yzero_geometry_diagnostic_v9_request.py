#!/usr/bin/env python3
"""Build the forward F5 root124 Y-zero geometry/support request.

The terminal q123 receipt and generated XML/Fluid/Bound VTK are required at
build time, but this builder itself never reads VTK payload bytes.  It adapts
the consumed V8 request envelope to the additive V9 worker, whose static
identity adapter accepts only the new dp=.005, pointref.y=0 rung.  The V8
worker's payload first-hash, pre/post stat, Idp, selector, clip and overlap
machinery is reused without editing its consumed source.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V8_REQUEST_PATH = HERE / "stage2_f5_s1_clipplane_geometry_diagnostic_v8_request.py"
V9_WORKER_PATH = HERE / "stage2_f5_s1_clipplane_geometry_diagnostic_yzero_v9.py"
CONTRACT_HELPER_PATH = HERE / "stage2_f5_s1_clipplane_yzero_contract_v1.py"
REQUEST_SCHEMA = "ds02.request.v1"
REQUEST_VARIANT_SCHEMA = "ds02.stage2.f5-s1.clipplane-yzero-geometry-diagnostic.v9-request"
WORKER_SCHEMA = "ds02.stage2.f5-s1.clipplane-yzero-geometry-diagnostic.v9"
SUPPORT_CONTRACT_SCHEMA = "ds02.stage2.f5-s1.clipplane-geometry-diagnostic-contract.v8"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V8REQ = load_module("stage2_f5_yzero_v8_request_adapter", V8_REQUEST_PATH)
CONTRACT = load_module("stage2_f5_yzero_contract_for_request_v1", CONTRACT_HELPER_PATH)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    stat = path.stat()
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": sha256(path), "content_scope": "small_code_contract_hashed_by_builder_and_parent_v8"}


def configure_adapter() -> None:
    # Both layers validate the original GenCase request.  Patch their in-memory
    # V7 identity function only; no consumed file is edited.
    V8REQ.V7REQ.V7.validate_gencase_request = CONTRACT.validate_gencase_request
    V8REQ.V7REQ.V7_PATH = V9_WORKER_PATH
    V8REQ.V7REQ.V7_WORKER_SCHEMA = WORKER_SCHEMA
    V8REQ.V7REQ.REQUEST_VARIANT_SCHEMA = REQUEST_VARIANT_SCHEMA
    V8REQ.V7REQ.SUPPORT_CONTRACT_SCHEMA = SUPPORT_CONTRACT_SCHEMA
    V8REQ.V8_WORKER_PATH = V9_WORKER_PATH
    V8REQ.WORKER_SCHEMA = WORKER_SCHEMA
    V8REQ.REQUEST_VARIANT_SCHEMA = REQUEST_VARIANT_SCHEMA
    V8REQ.SUPPORT_CONTRACT_SCHEMA = SUPPORT_CONTRACT_SCHEMA


def build(args: argparse.Namespace) -> dict[str, Any]:
    configure_adapter()
    adapted = argparse.Namespace(**vars(args))
    payload = V8REQ.build(adapted)
    records = payload.get("input_records")
    if not isinstance(records, dict):
        raise ValueError("V8 adapter produced no input records")
    for path, label in ((V9_WORKER_PATH, "F5 Y-zero V9 geometry worker"), (CONTRACT_HELPER_PATH, "F5 Y-zero contract helper"), (Path(__file__).resolve(), "F5 Y-zero V9 geometry request builder")):
        item = record(path, label)
        records[item["path"]] = item
    payload["input_records"] = records
    payload["input_files"] = sorted(records)
    payload["input_hashes"] = {path: records[path]["sha256"] for path in payload["input_files"]}
    command = list(payload["command"])
    if str(V9_WORKER_PATH.resolve()) not in command:
        raise ValueError("V9 request command does not invoke the forward Y-zero worker")
    output_path = "{attempt_root}/report/stage2_f5_s1_clipplane_yzero_geometry_diagnostic_v9.json"
    try:
        output_index = command.index("--output")
        command[output_index + 1] = output_path
    except (ValueError, IndexError) as exc:
        raise ValueError("V8 adapter emitted a malformed --output command") from exc
    payload["command"] = command
    payload["schema"] = REQUEST_SCHEMA
    payload["request_variant_schema"] = REQUEST_VARIANT_SCHEMA
    payload["worker_schema"] = WORKER_SCHEMA
    payload["status"] = "READY_FOR_PARENT_V8_F5_YZERO_GEOMETRY_DIAGNOSTIC"
    payload["qualification_stage"] = "stage2_f5_s1_yzero_global_shape_idp_overlap_diagnostic_v9_pending_parent_guard"
    payload["output"]["path"] = output_path
    payload["source_binding"].update({
        "grid": "dp005", "pointref_m": [0.0125, 0.0, 0.0125],
        "global_lattice_phase_change": True,
        "phase_change_relative_to_q107": "pointref.y 0.0025 -> 0.0000 only",
        "pointref_scope": "global GenCase lattice origin",
        "all_shapes_scope": ["fluid", "boundary", "forcing", "shape_operations"],
        "fluid_selector_unchanged": True, "boundary_selector_unchanged": True,
        "forcing_motion_content_unchanged": True, "boundary_geometry_audit_required": True,
    })
    payload["parent_v8_input_closure"] = payload.get("parent_v8_input_closure", {})
    payload["parent_v8_input_closure"]["worker_first_payload_hash_after_parent_reservation"] = True
    payload["parent_v8_input_closure"]["parent_v8_does_not_hash_worker_owned_vtk"] = True
    payload["worker_owned_input_hashes"] = payload.get("worker_owned_input_hashes", {})
    payload["worker_owned_input_hashes"]["hash_status"] = "NOT_COMPUTED_BY_BUILDER_OR_PARENT_INPUT_FILES"
    payload["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "Y-zero global pointref diagnostic; support/geometry/mass/control evidence only, no solver or physical contact/flux qualification"}
    payload["estimated_input_read_bytes"] = sum(int(item.get("bytes", 0)) for item in records.values()) + sum(int(item.get("bytes", 0)) for item in payload.get("worker_owned_input_stats_at_build", {}).values() if isinstance(item, dict))
    return payload


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable V9 request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
            handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    helper = CONTRACT.self_test()
    worker = json.loads(__import__("subprocess").check_output([sys.executable, str(V9_WORKER_PATH), "--self-test"], text=True))
    if helper.get("status") != "PASS" or worker.get("status") != "PASS":
        raise AssertionError({"helper": helper, "worker": worker})
    return {"status": "PASS", "schema": REQUEST_SCHEMA, "request_variant_schema": REQUEST_VARIANT_SCHEMA, "worker_schema": WORKER_SCHEMA, "reuses_v8_payload_reader": True, "vtk_payload_read_by_builder": False, "yhalf_rejected": True, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--grid", choices=("dp005",), default="dp005")
    for name in ("gencase-request", "receipt", "generated-xml", "candidate-def", "source-def", "candidate-motion", "source-motion", "fluid-vtk", "bound-vtk", "clip-evidence", "output", "support-contract"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--attempt-id")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = [args.gencase_request, args.receipt, args.generated_xml, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.fluid_vtk, args.bound_vtk, args.clip_evidence, args.output, args.launch_commit]
    if any(value is None for value in required):
        parser.error("--build-request requires q123 terminal inputs, --clip-evidence, --output and --launch-commit")
    payload = build(args)
    write_new(args.output, payload)
    print(json.dumps({"status": payload["status"], "schema": payload["schema"], "request_variant_schema": payload["request_variant_schema"], "worker_schema": payload["worker_schema"], "output": str(args.output.resolve()), "vtk_payload_read_by_builder": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

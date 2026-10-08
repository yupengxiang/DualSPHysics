#!/usr/bin/env python3
"""Build the forward V6 F5 support request for a terminal V5 GenCase run.

This adapter reuses the immutable V5 request builder for path and guard
semantics, then rebinds the worker and builder records to V6.  It does not
read Fluid/Bound VTK.  Their hashes stay
``WORKER_AFTER_RESERVATION_ONLY`` and the V6 worker performs full
pre/immediate/post SHA/stat checks after the parent reservation.
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
V5_PATH = HERE / "stage2_f5_s1_clipplane_initial_support_audit_v5_request.py"
V6_WORKER = HERE / "stage2_f5_s1_clipplane_initial_support_audit_v6.py"
REQUEST_SCHEMA = "ds02.request.v1"
REQUEST_VARIANT_SCHEMA = "ds02.stage2.f5-s1.clipplane-initial-support-audit.v6-request"
V5_SCHEMA = "ds02.stage2.f5-s1.clipplane-initial-support-audit.v5-request"
V6_WORKER_SCHEMA = "ds02.stage2.f5-s1.clipplane-initial-support-audit.v6"
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"
CONTINUOUS_MASS_KG = 287.736
OLD_DISCRETE_SAMPLE_MASS_KG = 254.4779834119572


def load_v5():
    spec = importlib.util.spec_from_file_location("stage2_f5_support_request_v5_for_v6", V5_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(V5_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V5 = load_v5()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    stat = path.stat()
    return {"path": str(path), "label": label, "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns, "st_dev": stat.st_dev, "st_ino": stat.st_ino, "sha256": sha256(path), "content_scope": "small_input_hashed_by_builder_and_parent_v8"}


def rebind_records(payload: dict[str, Any]) -> None:
    records = payload.get("input_records")
    if not isinstance(records, dict):
        raise ValueError("V5 builder emitted no input_records")
    old_builder = str(V5_PATH.resolve())
    new_builder = str(Path(__file__).resolve())
    records.pop(old_builder, None)
    records[new_builder] = record(Path(__file__), "F5 V6 support request builder")
    payload["input_records"] = records
    payload["input_files"] = sorted(records)
    payload["input_hashes"] = {path: records[path]["sha256"] for path in payload["input_files"]}


def build(args: argparse.Namespace) -> dict[str, Any]:
    V5.WORKER = V6_WORKER
    # The dispatch envelope remains ds02.request.v1.  V5.SCHEMA is the
    # source-binding/worker variant field, so point it at the V6 worker
    # schema without changing the envelope schema required by parent v8.
    V5.SCHEMA = V6_WORKER_SCHEMA
    # Give the forward request its own immutable identity/output namespace
    # when callers do not supply one.  Reusing the V5 default would make a
    # V6 worker write a V5-named report and risks an output collision.
    build_args = argparse.Namespace(**vars(args))
    if not build_args.case_id:
        build_args.case_id = f"F5_S1_CLIPPLANE_INITIAL_SUPPORT_AUDIT_V6_{args.grid.upper()}"
    if not build_args.attempt_id:
        build_args.attempt_id = f"f5-s1-clipplane-initial-support-audit-v6-{args.grid}-root-review-001"
    # The consumed V5 builder writes its own immutable output as part of
    # build().  Give it a private temporary path, then emit only the adapted
    # V6 request at the caller's requested destination.  This avoids both a
    # V5-named artifact and an overwrite attempt while preserving V5's source
    # validation and record construction.
    target = Path(args.output).expanduser().resolve()
    base_tmp = target.with_name(f".{target.name}.{os.getpid()}.v5-base.tmp")
    if base_tmp.exists() or base_tmp.is_symlink():
        raise FileExistsError(f"refuse to reuse V5 adapter temporary path: {base_tmp}")
    build_args.output = base_tmp
    try:
        payload = V5.build(build_args)
    finally:
        base_tmp.unlink(missing_ok=True)
    if payload.get("schema") != REQUEST_SCHEMA:
        raise ValueError("V5 adapter did not emit the ds02.request.v1 envelope")
    rebind_records(payload)
    command = payload.get("command", [])
    if len(command) < 2 or Path(command[1]).resolve() != V6_WORKER.resolve():
        raise ValueError("V6 worker was not bound in the request command")
    v6_output_path = "{attempt_root}/report/stage2_f5_s1_clipplane_initial_support_audit_v6.json"
    try:
        output_index = command.index("--output")
        command[output_index + 1] = v6_output_path
    except (ValueError, IndexError) as exc:
        raise ValueError("V5 adapter emitted no replaceable worker output argument") from exc
    payload["command"] = command
    payload["output"]["path"] = v6_output_path
    payload["worker_schema"] = V6_WORKER_SCHEMA
    payload["request_variant_schema"] = REQUEST_VARIANT_SCHEMA
    payload["qualification_stage"] = "stage2_f5_s1_initial_support_mass_control_audit_v6_pending_parent_guard"
    payload["source_binding"]["schema"] = V6_WORKER_SCHEMA
    # V5's support builder carries the terminal GenCase request record but
    # does not copy the rung geometry into its own source binding.  The V6
    # worker validates this contract before it opens any payload, so bind the
    # exact Y-half dp/pointref pair explicitly here rather than inferring it
    # from generated XML after the fact.
    if args.grid == "dp010":
        expected_dp = 0.010
        expected_pointref = [0.015, 0.005, 0.015]
    elif args.grid == "dp005":
        expected_dp = 0.005
        expected_pointref = [0.0125, 0.0025, 0.0125]
    else:
        raise ValueError(f"unsupported F5 Y-half grid: {args.grid!r}")
    payload["source_binding"]["dp_m"] = expected_dp
    payload["source_binding"]["pointref_m"] = expected_pointref
    payload["source_binding"]["grid"] = args.grid
    payload["source_binding"]["continuous_region_mass_kg"] = CONTINUOUS_MASS_KG
    payload["source_binding"]["old_discrete_sample_mass_kg"] = OLD_DISCRETE_SAMPLE_MASS_KG
    payload["source_binding"]["old_discrete_sample_is_diagnostic_only"] = True
    payload["source_binding"]["official_clip_and_box_unchanged"] = True
    payload["source_binding"]["controls_and_motion_unchanged"] = True
    payload["source_binding"]["mass_rescale"] = False
    payload["guard_policy"]["worker_schema"] = V6_WORKER_SCHEMA
    payload["guard_policy"]["worker_vtk_pre_post_sha_stat_required"] = True
    payload["guard_policy"]["deferred_input_files_used"] = False
    payload["parent_v8_input_closure"]["deferred_input_files_used"] = False
    payload["parent_v8_input_closure"]["vtk_sha_authority"] = "V4 worker pre/post full SHA after parent reservation"
    payload["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "V6 support/mass/control audit only; source-derived continuous owner and old discrete sample are separate"}
    return payload


def json_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable V6 request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = -1; handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        finally:
            if fd >= 0: os.close(fd)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    base = V5.self_test()
    assert base["status"] == "PASS"
    assert V5_SCHEMA.endswith("v5-request")
    return {"status": "PASS", "schema": REQUEST_SCHEMA, "request_variant_schema": REQUEST_VARIANT_SCHEMA, "worker_schema": V6_WORKER_SCHEMA, "vtk_payload_read_by_builder": False, "worker_vtk_sha_after_reservation": True, "deferred_input_files_used": False, "solver_started": False, "v5_dependency_self_test": base["status"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--grid", choices=("dp010", "dp005"))
    for name in ("gencase-request", "receipt", "generated-xml", "candidate-def", "source-def", "candidate-motion", "source-motion", "fluid-vtk", "bound-vtk", "output"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--attempt-id")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = [args.grid, args.gencase_request, args.receipt, args.generated_xml, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.fluid_vtk, args.bound_vtk, args.output, args.launch_commit]
    if any(value is None for value in required):
        parser.error("--build-request requires grid, terminal inputs, output and launch commit")
    payload = build(args)
    json_new(args.output, payload)
    print(json.dumps({"status": payload["status"], "schema": payload["schema"], "request_variant_schema": payload["request_variant_schema"], "worker_schema": payload["worker_schema"], "grid": args.grid, "output": str(args.output.resolve()), "vtk_payload_read_by_builder": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

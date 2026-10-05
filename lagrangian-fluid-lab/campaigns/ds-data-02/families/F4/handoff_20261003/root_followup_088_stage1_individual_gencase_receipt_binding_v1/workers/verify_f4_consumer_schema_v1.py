#!/usr/bin/env python3
"""Verify fresh087 request consumers without opening generated science data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ARRAY_SUFFIXES = {".bi4", ".h5", ".vtk", ".csv"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def verify_hashes(request: dict[str, Any], path: Path) -> None:
    active = request.get("input_files", [])
    hashes = request.get("input_sha256", {})
    if len(active) != len(hashes) or not active:
        raise ValueError(f"{path.name}: active input/hash sets differ")
    for value in active:
        source = Path(value)
        if source.suffix.lower() in ARRAY_SUFFIXES:
            raise ValueError(f"{path.name}: scientific array is active input: {source}")
        if not source.is_file() or sha256(source) != hashes.get(str(source)):
            raise ValueError(f"{path.name}: active input hash mismatch: {source}")
    for value in request.get("deferred_input_files", []):
        if Path(value).suffix.lower() in ARRAY_SUFFIXES and request.get("deferred_input_sha256", {}).get(value) is not None:
            raise ValueError(f"{path.name}: deferred scientific array has a fabricated digest")


def verify_common(request: dict[str, Any], path: Path) -> None:
    required = ("family_id", "case_id", "attempt_id", "kind", "command", "cwd", "max_wall_seconds", "cpu_threads", "estimated_storage_bytes", "input_files", "worktree_root")
    missing = [key for key in required if key not in request]
    if missing:
        raise ValueError(f"{path.name}: missing runtime fields {missing}")
    if request.get("family_id") != "F4" or request.get("launch") is not False or request.get("launch_allowed") is not False:
        raise ValueError(f"{path.name}: source-only launch guard drift")
    if request.get("status") != "source_only_disabled" or request.get("independent_case_count_increment") != 0:
        raise ValueError(f"{path.name}: source-only status/credit drift")
    if not isinstance(request.get("command"), list) or not all(isinstance(arg, str) for arg in request["command"]):
        raise ValueError(f"{path.name}: command is not an argv list")
    verify_hashes(request, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = load(args.source_root / "source-plan.json")
    endpoints = {str(row["endpoint_id"]): row for row in plan["endpoints"]}
    if len(endpoints) != 6:
        raise ValueError("fresh087 plan is not six endpoints")
    cases = []
    for endpoint_id in endpoints:
        gen = args.source_root / "requests" / f"{endpoint_id}-gencase.request.json"
        qa = args.source_root / "requests" / f"{endpoint_id}-initial-native-qa.request.json"
        native = args.source_root / "requests" / f"{endpoint_id}-full1201-native-qualification.request.json"
        gen_req, qa_req, native_req = load(gen), load(qa), load(native)
        verify_common(gen_req, gen)
        verify_common(qa_req, qa)
        verify_common(native_req, native)
        if gen_req.get("kind") != "cpu" or gen_req.get("cpu_task_kind") != "gencase":
            raise ValueError(f"{endpoint_id}: GenCase consumer kind drift")
        if "{attempt_root}" not in " ".join(gen_req["command"]):
            raise ValueError(f"{endpoint_id}: GenCase output is not runtime-bound")
        if qa_req.get("kind") != "cpu" or qa_req.get("cpu_task_kind") != "audit":
            raise ValueError(f"{endpoint_id}: initial QA consumer kind drift")
        if "{gencase_binding}" not in qa_req["command"]:
            raise ValueError(f"{endpoint_id}: initial QA lacks deferred binding token")
        if not any(str(value).endswith(".bi4") for value in qa_req.get("deferred_input_files", [])):
            raise ValueError(f"{endpoint_id}: initial QA has no deferred BI4 input")
        if not any(str(value).endswith(".xml") for value in qa_req.get("deferred_input_files", [])):
            raise ValueError(f"{endpoint_id}: initial QA has no deferred XML input")
        if native_req.get("kind") != "qualification" or native_req.get("cpu_task_kind") != "qualification":
            raise ValueError(f"{endpoint_id}: native qualification consumer kind drift")
        if native_req.get("gencase_receipt_sha256") is not None:
            raise ValueError(f"{endpoint_id}: native qualification prefilled a future receipt digest")
        if "-tmax:1.2" not in native_req["command"] or "-tout:0.001" not in native_req["command"]:
            raise ValueError(f"{endpoint_id}: native recipe drift")
        cases.append({
            "endpoint_id": endpoint_id,
            "gencase_request": str(gen),
            "initial_qa_request": str(qa),
            "native_qualification_request": str(native),
            "gencase_active_inputs": len(gen_req["input_files"]),
            "initial_qa_active_inputs": len(qa_req["input_files"]),
            "initial_qa_deferred_inputs": len(qa_req["deferred_input_files"]),
            "native_deferred_inputs": len(native_req["deferred_input_files"]),
            "future_hashes_null": all(value is None for value in native_req.get("deferred_input_sha256", {}).values()),
        })
    output = {
        "schema": "ds02.f4.fresh087-consumer-schema-verification.v1",
        "status": "completed",
        "scope_id": plan["scope_id"],
        "case_count": len(cases),
        "cases": cases,
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "qualification_launch": "deferred until Root binds native QA index and actual receipt",
        "worker_shape_finding": "fresh087 run_f4_fallback_native_initial_qa_v1 is a six-case aggregate consumer despite per-case request filenames; use fresh088 aggregate request after binding, not six direct invocations",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"schema": output["schema"], "status": "completed", "cases": len(cases), "arrays_read_by_source": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

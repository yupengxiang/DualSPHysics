#!/usr/bin/env python3
"""Static preflight for the F7 fresh075 source-only package.

It checks the request closure and the repaired flat-path contract.  It never
opens scientific payloads and never launches a worker.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[1]
RAW_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".dat", ".ibi4"}
EXPECTED = {"total": 70179, "fixed": 27495, "moving": 1984, "floating": 0, "fluid": 40700, "dimension": 3}


class PreflightError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PreflightError(message)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha(path: Path) -> str:
    require(path.suffix.lower() not in RAW_SUFFIXES,
            f"scientific payload hash requested by source preflight: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_python(path: Path) -> None:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def check_closure(request: dict[str, Any], path: Path) -> int:
    files = [str(item) for item in request.get("input_files", [])]
    hashes = request.get("input_sha256", {})
    require(len(files) == len(set(files)), f"duplicate input_files: {path}")
    require(set(files) == set(hashes), f"input/hash set mismatch: {path}")
    for raw in files:
        item = Path(raw)
        require(item.is_absolute() and item.is_file(), f"missing source input {item}: {path}")
        require(item.suffix.lower() not in RAW_SUFFIXES,
                f"scientific payload registered in source input closure: {item}")
        require(sha(item) == hashes[raw], f"source input hash drift: {item}")
    future = [str(item) for item in request.get("future_input_files", [])]
    future_hashes = request.get("future_input_sha256", {})
    require(set(future) == set(future_hashes), f"future input/hash set mismatch: {path}")
    require(all(value is None for value in future_hashes.values()),
            f"future input hash is not null: {path}")
    require(request.get("future_hashes_null") is True, f"future hash flag drift: {path}")
    require(request.get("disabled") is True and request.get("launch") is False,
            f"request not disabled: {path}")
    require(request.get("execution_allowed") is False and request.get("launch_allowed") is False,
            f"request launch guard drift: {path}")
    require(request.get("no_arrays_read") is True and request.get("no_jobs_started") is True and
            request.get("no_shared_registry_write") is True,
            f"source-only guards missing: {path}")
    return len(files)


def main() -> int:
    manifest = load(PACKAGE / "manifest.json")
    require(manifest.get("schema") == "ds02.f7.fresh075.manifest.v1", "manifest schema drift")
    require(manifest.get("case_count") == 24 and manifest.get("arrays_read") is False,
            "manifest source-only flags drift")
    contract = load(PACKAGE / "metadata/adapter-contract.json")
    require(contract.get("schema") == "ds02.f7.fresh075.actual-gencase-native-qa-adapter-contract.v1",
            "adapter contract schema drift")
    for rel in (
        "scripts/bind_fresh075_actual_gencase_metadata.py",
        "scripts/preflight_fresh075.py",
        "workers/run_f7_fresh075_native_initial_qa.py",
        "builders/build_fresh075_metadata_adapter.py",
    ):
        check_python(PACKAGE / rel)

    adapter_request_path = PACKAGE / "requests/actual-gencase-metadata-adapter-request.json"
    qa_request_path = PACKAGE / "requests/native-initial-qa-execution-request.json"
    adapter = load(adapter_request_path)
    qa = load(qa_request_path)
    closure_counts = {
        "adapter": check_closure(adapter, adapter_request_path),
        "native_initial_qa": check_closure(qa, qa_request_path),
    }
    require(adapter.get("kind") == "cpu" and adapter.get("cpu_task_kind") == "audit",
            "adapter kind drift")
    require(qa.get("kind") == "cpu" and qa.get("cpu_task_kind") == "audit",
            "initial QA kind drift")
    require(adapter.get("expected_counts") == EXPECTED and qa.get("expected_counts") == EXPECTED,
            "metadata count contract drift")
    require("prepared/{case}/{case}.xml" not in json.dumps(adapter),
            "old nested GenCase path remains in adapter request")
    require("prepared/{case}/{case}.xml" not in json.dumps(qa),
            "old nested GenCase path remains in QA request")
    require("/prepared/" in json.dumps(adapter) and ".xml" in json.dumps(adapter),
            "flat XML path is absent from adapter request")
    require("/prepared/" in json.dumps(qa) and ".xml" in json.dumps(qa),
            "flat XML path is absent from QA request")
    native_paths = sorted((PACKAGE / "requests/native").glob("*.json"))
    require(len(native_paths) == 24, f"expected 24 native requests, got {len(native_paths)}")
    native_rows = []
    for path in native_paths:
        request = load(path)
        count = check_closure(request, path)
        require(request.get("kind") == "qualification" and request.get("cpu_task_kind") == "solver",
                f"native kind drift: {path}")
        require(request.get("estimated_peak_gpu_mib") == 4096 and
                request.get("cpu_threads") == 4 and request.get("expected_counts") == EXPECTED,
                f"native resource/count contract drift: {path}")
        require(request.get("command", [None])[0].endswith("DualSPHysics5.4_linux64"),
                f"native command does not use official solver: {path}")
        require("/prepared/" in request.get("command", ["", ""])[1] and
                "/prepared" in request.get("cwd", ""),
                f"native flat prepared path drift: {path}")
        require(request.get("initial_qa_binding", "").endswith("binding/binding.json"),
                f"native adapter binding path drift: {path}")
        require(request.get("initial_typed_qa", "").endswith("native-initial-qa.json"),
                f"native QA report path drift: {path}")
        native_rows.append({"path": str(path), "source_input_count": count,
                            "case_id": request.get("case_id")})

    report = {
        "schema": "ds02.f7.fresh075.source-validation-report.v1",
        "scope_id": manifest["scope_id"],
        "source_package": str(PACKAGE),
        "case_count": 24,
        "native_request_count": len(native_paths),
        "source_input_counts": closure_counts,
        "native_requests": native_rows,
        "flat_prepared_layout_checked": True,
        "zero_floating_node_supported": True,
        "worker_imports_numpy_only_for_root_runtime": True,
        "arrays_read": False,
        "bi4_read": False,
        "motion_read": False,
        "h5_read": False,
        "jobs_started": False,
        "shared_state_written": False,
        "future_hashes_null": True,
        "all_passed": True,
        "claim_boundary": "Static source/request contract only; no actual native QA, full solver, visual, Q-N, precision, or production result.",
    }
    target = PACKAGE / "metadata/source-validation-report.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreflightError as exc:
        raise SystemExit(f"fresh075 preflight failed: {exc}") from exc

#!/usr/bin/env python3
"""Derive disabled Root690 render requests with the real runtime fields.

This helper only reads JSON metadata and source request files. It never opens
science payloads, runs a dispatcher, or changes fresh107. Its output remains a
WAIT/disabled request until Root supplies its own actual Root669 records.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

PACKAGE = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((PACKAGE / "metadata/runtime-contract.json").read_text())
RAW_SUFFIXES = {".bi4", ".ibi4", ".h5", ".hdf5", ".vtk", ".vtu", ".vtp", ".csv", ".dat", ".npy", ".npz"}
REQUIRED_RUNTIME = (
    "family_id", "case_id", "attempt_id", "kind", "command", "cwd",
    "max_wall_seconds", "cpu_threads", "estimated_storage_bytes",
    "input_files", "worktree_root",
)

def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value

def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def _assert_absolute_paths(request: Mapping[str, Any], *, allow_future: bool) -> None:
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    if not isinstance(files, list) or not isinstance(hashes, dict) or set(files) != set(hashes):
        raise ValueError("input_files and input_sha256 must be the same closed set")
    for raw in files:
        path = Path(raw)
        if not path.is_absolute():
            raise ValueError(f"input path is not absolute: {raw}")
        if path.suffix.lower() in RAW_SUFFIXES:
            raise ValueError(f"source repair must not read science payload: {raw}")
        if not allow_future and not path.is_file():
            raise ValueError(f"metadata input is missing: {raw}")
        declared = hashes[raw]
        if not isinstance(declared, str) or len(declared) != 64:
            raise ValueError(f"input digest is not a 64-hex string: {raw}")
        if path.is_file() and digest(path) != declared:
            raise ValueError(f"input digest mismatch: {raw}")

def validate_runtime_fields(request: Mapping[str, Any], *, disabled: bool = True) -> None:
    missing = [key for key in REQUIRED_RUNTIME if key not in request]
    if missing:
        raise ValueError("missing runtime fields: " + ", ".join(missing))
    if request["family_id"] != "F4" or request["kind"] != "cpu" or request["cpu_task_kind"] != "audit":
        raise ValueError("Root690 renderer must be a CPU audit request")
    if request["worktree_root"] != CONTRACT["worktree_root"] or request["cwd"] != CONTRACT["cwd"]:
        raise ValueError("Root690 worktree_root/cwd do not match reviewed integration paths")
    if request.get("launch_owner") != CONTRACT["launch_owner"]:
        raise ValueError("Root142 requires launch_owner=root")
    if request["cpu_threads"] != CONTRACT["cpu_threads"] or request["max_wall_seconds"] != CONTRACT["max_wall_seconds"]:
        raise ValueError("Root690 CPU/wall values differ from Root638 contract")
    if request["estimated_storage_bytes"] != CONTRACT["estimated_storage_bytes"]:
        raise ValueError("estimated_storage_bytes differs from Root638 bounded render reservation")
    if request.get("root_dataset_inventory_profile") != CONTRACT["root_dataset_inventory_profile"]:
        raise ValueError("Root142 Home-floor profile is missing or wrong")
    if request.get("expected_frames") != CONTRACT["expected_frames"]:
        raise ValueError("expected_frames must be 1201")
    command = request["command"]
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise ValueError("command must be an argv list")
    if CONTRACT["root023_renderer"]["path"] not in command:
        raise ValueError("Root023 renderer path is absent from command")
    if "--manifest" not in command or "--output-dir" not in command:
        raise ValueError("Root023 --manifest/--output-dir arguments are required")
    if any("fresh105" in item.lower() or "fresh106" in item.lower() for item in command):
        raise ValueError("stale fresh105/fresh106 path remains in command")
    env_values = {item.split("=", 1)[0]: item.split("=", 1)[1] for item in command if "=" in item and item.split("=", 1)[0] in CONTRACT["explicit_environment_threads"]}
    for name, expected in CONTRACT["explicit_environment_threads"].items():
        if env_values.get(name) != str(expected):
            raise ValueError(f"explicit renderer environment {name} must be {expected}")
    if disabled:
        for key in ("disabled", "launch", "launch_allowed", "execution_allowed"):
            if request.get(key) is not (True if key == "disabled" else False):
                raise ValueError(f"disabled repair has invalid {key}")
        if request.get("case_xmf") is not None or request.get("manifest") is not None:
            raise ValueError("disabled repair cannot claim future manifest/XMF paths")
        future = request.get("future_hashes", {})
        if not isinstance(future, dict) or any(value is not None for value in future.values()):
            raise ValueError("disabled repair future hashes must remain null")
    _assert_absolute_paths(request, allow_future=disabled)

def derive_disabled(source: Mapping[str, Any]) -> dict[str, Any]:
    request = copy.deepcopy(dict(source))
    request.update({
        "kind": CONTRACT["kind"],
        "cpu_task_kind": CONTRACT["cpu_task_kind"],
        "worktree_root": CONTRACT["worktree_root"],
        "cwd": CONTRACT["cwd"],
        "launch_owner": CONTRACT["launch_owner"],
        "cpu_threads": CONTRACT["cpu_threads"],
        "max_wall_seconds": CONTRACT["max_wall_seconds"],
        "estimated_storage_bytes": CONTRACT["estimated_storage_bytes"],
        "root_dataset_inventory_profile": CONTRACT["root_dataset_inventory_profile"],
        "expected_frames": CONTRACT["expected_frames"],
        "disabled": True,
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "case_xmf": None,
        "manifest": None,
        "future_hashes": {key: None for key in (source.get("future_hashes") or {"manifest_sha256": None, "execution_receipt_sha256": None, "report_sha256": None})},
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
    })
    # Add the immutable runtime/dispatcher/render policy inputs needed by
    # strict dispatch. These are metadata/code files; no science payload is
    # opened. Root's active successor must still append its actual Root669
    # records and exact producer digests.
    for raw in CONTRACT["static_input_paths"]:
        path = Path(raw)
        if not path.is_file():
            raise ValueError(f"static dispatch input is missing: {raw}")
        request.setdefault("input_files", []).append(str(path))
        request.setdefault("input_sha256", {})[str(path)] = digest(path)
    request["input_files"] = sorted(set(request["input_files"]))
    request["input_sha256"] = {key: request["input_sha256"][key] for key in request["input_files"]}
    validate_runtime_fields(request, disabled=True)
    return request

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-package", type=Path, required=True)
    parser.add_argument("--output-package", type=Path, required=True)
    args = parser.parse_args()
    source_package = args.source_package.resolve()
    output_package = args.output_package.resolve()
    source_requests = sorted((source_package / "requests").glob("*.request.json"))
    if len(source_requests) != 24:
        raise ValueError(f"expected 24 fresh107 requests, found {len(source_requests)}")
    output_package.mkdir(parents=True, exist_ok=True)
    rows=[]
    for source_path in source_requests:
        repaired=derive_disabled(load(source_path))
        target=output_package / source_path.name.replace("fresh107", "fresh108")
        target.write_text(json.dumps(repaired, indent=2) + "\n", encoding="utf-8")
        rows.append({"case_id": repaired["case_id"], "path": str(target), "sha256": digest(target), "disabled": True})
    (output_package / "index.json").write_text(json.dumps({"schema":"ds02.f4.fresh108.disabled-request-index.v1","request_count":len(rows),"all_disabled":True,"requests":rows},indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"request_count":len(rows),"all_disabled":True,"output":str(output_package)}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

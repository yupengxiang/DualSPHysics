#!/usr/bin/env python3
"""Pure metadata validator for the fresh066-corner706 source package."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CASES = (
    "F3_STAGE1_DP006_P0800_AY0250",
    "F3_STAGE1_DP006_P0800_AY0750",
    "F3_STAGE1_DP006_P1200_AY0250",
    "F3_STAGE1_DP006_P1200_AY0750",
)
PAYLOAD_SUFFIXES = {".bi4", ".obi4", ".csv", ".dat", ".h5", ".hdf5", ".vtk", ".npy", ".npz"}
F3_ROOT = "/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics"
INT_ROOT = "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics"
CONVERTER_NAME = "ds_data02_direct_convert.py"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_metadata(path: Path) -> str:
    if path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise AssertionError(f"validator refuses payload hashing: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate_request(request: dict[str, Any], case_id: str, *, check_files: bool = True) -> None:
    require(request.get("schema") == "ds02.runner-request.v2", f"{case_id}: schema")
    require(request.get("case_id") == case_id, f"{case_id}: case identity")
    require(request.get("family_id") == "F3", f"{case_id}: family")
    require(request.get("disabled") is True, f"{case_id}: request must remain disabled")
    require(request.get("launch") is False and request.get("launch_allowed") is False, f"{case_id}: launch guard")
    require(request.get("execution_allowed") is False, f"{case_id}: execution guard")
    require(request.get("source_only") is True, f"{case_id}: source-only guard")
    require(request.get("launch_owner") == "root", f"{case_id}: launch owner")
    require(request.get("kind") == "cpu" and request.get("cpu_task_kind") == "conversion", f"{case_id}: CPU task kind")
    require(request.get("cpu_threads") == 2, f"{case_id}: CPU threads")
    require(request.get("max_wall_seconds") == 10800, f"{case_id}: wall limit")
    require(request.get("estimated_storage_bytes") == 25769803776, f"{case_id}: storage estimate")
    require(request.get("worktree_root") == F3_ROOT, f"{case_id}: worktree_root")
    require(request.get("cwd") == INT_ROOT + "/lagrangian-fluid-lab", f"{case_id}: cwd")
    require(request.get("root_dataset_inventory_profile") == "root_home_floor_no_legacy_dataset_walk_v1", f"{case_id}: Root142 profile")
    require(request.get("expected_saved_frames") == 836, f"{case_id}: frames")
    require(request.get("expected_particles") == 179208, f"{case_id}: total particles")
    require(request.get("expected_fluid_particles") == 67500, f"{case_id}: fluid particles")
    require(request.get("expected_fixed_particles") == 111708, f"{case_id}: fixed particles")
    require(request.get("expected_moving_particles") == 0, f"{case_id}: moving particles")
    require(request.get("physical_condition_sha256") == request.get("actual_converter_physical_condition_scope_sha256"), f"{case_id}: physical scope hash")
    require(request.get("source_physical_condition_sha256") is None, f"{case_id}: source hash must remain unresolved")
    require(request.get("production_approval") == "none" and request.get("q_n") == "not_granted", f"{case_id}: approval claim")
    require(request.get("numerical_precision_status") == "not_accepted", f"{case_id}: precision claim")
    native = request.get("native_full836_binding", {})
    require(native.get("status") == "completed" and native.get("returncode") == 0, f"{case_id}: native terminal status")
    quality = native.get("quality", {})
    for key, value in (("actual_3d", True), ("dimension", 3), ("total_particles", 179208), ("fixed_particles", 111708), ("fluid_particles", 67500), ("moving_particles", 0), ("saved_frames", 836)):
        require(quality.get(key) == value, f"{case_id}: native quality {key}")
    future = request.get("future_typed_outputs", {})
    require(all((not isinstance(v, dict)) or v.get("sha256") is None for v in future.values()), f"{case_id}: future hash was filled")
    command = request.get("command", [])
    require("--" in command, f"{case_id}: wrapper delimiter")
    delimiter = command.index("--")
    require(command[0].endswith("/.venv/bin/python"), f"{case_id}: approved virtualenv")
    require(command[1].endswith("ds_data02_nvme_convert_v1.py"), f"{case_id}: NVMe wrapper")
    require(CONVERTER_NAME not in " ".join(command[delimiter + 1:]), f"{case_id}: direct converter after wrapper delimiter")
    require(command[command.index("--staging-root") + 1] == "/tmp/ds02-nvme-conversion", f"{case_id}: staging root")
    require(command[command.index("--staging-limit-bytes") + 1] == "25769803776", f"{case_id}: staging cap")
    require("--owner-metadata" in command and command[command.index("--owner-metadata") + 1] == request["owner_metadata"]["path"], f"{case_id}: owner path")
    require(len(request.get("input_files", [])) == len(request.get("input_sha256", {})), f"{case_id}: input closure cardinality")
    require(set(request["input_files"]) == set(request["input_sha256"]), f"{case_id}: input closure keys")
    if check_files:
        for raw in request["input_files"]:
            path = Path(raw)
            require(path.is_file(), f"{case_id}: missing input {path}")
            if path.suffix.lower() not in PAYLOAD_SUFFIXES and path.suffix.lower() != ".out":
                require(sha256_metadata(path) == request["input_sha256"][raw], f"{case_id}: metadata digest drift {path}")
            else:
                require(bool(request["input_sha256"][raw]), f"{case_id}: missing producer payload/log digest {path}")
    owner_path = Path(request["owner_metadata"]["path"])
    owner = load(owner_path)
    require(owner.get("physical_binding", {}).get("schema") == "ds-data-02.physical-binding.v1", f"{case_id}: physical binding schema")
    require(owner.get("actual_converter_physical_condition_scope_sha256") == request["physical_condition_sha256"], f"{case_id}: owner/request scope")
    require(owner.get("source_only") is True and owner.get("execution_allowed") is False, f"{case_id}: owner guard")


def validate_package(*, check_files: bool = True) -> dict[str, Any]:
    manifest = load(HERE / "manifest.json")
    require(manifest.get("assignment_id") == "fresh066-corner706", "manifest assignment")
    require(manifest.get("case_ids") == list(CASES), "manifest cases")
    require(manifest.get("case_count") == 4 and manifest.get("all_requests_disabled") is True, "manifest count/disabled")
    require(manifest.get("all_native_completed0") is True and manifest.get("expected_saved_frames") == 836, "manifest native evidence")
    require(manifest.get("counts") == {"total": 179208, "fixed": 111708, "fluid": 67500, "moving": 0, "dimension": 3}, "manifest counts")
    require(manifest.get("future_typed_receipt_sha256") is None and manifest.get("future_trajectory_h5_sha256") is None, "manifest future hash")
    for case in CASES:
        request_path = HERE / "requests" / f"{case}.json"
        owner_path = HERE / "owners" / f"{case}.json"
        require(request_path.is_file() and owner_path.is_file(), f"{case}: package files")
        validate_request(load(request_path), case, check_files=check_files)
    return manifest


if __name__ == "__main__":
    result = validate_package()
    print(f"PASS: {result['assignment_id']} {result['case_count']} disabled requests; metadata closure verified")

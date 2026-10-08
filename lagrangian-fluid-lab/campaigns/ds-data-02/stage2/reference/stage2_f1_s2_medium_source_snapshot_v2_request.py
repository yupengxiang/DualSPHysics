#!/usr/bin/env python3
"""Build the bounded v2 source-snapshot request for F1-S2 medium.

Only the immutable medium observer template and small provenance/guard files
are read while building this request.  The nine selected BI4 paths remain
deferred to the parent CPU guard; this builder does not stat, open, or hash
them.  The v2 worker will hash exactly those nine files and reject a source
mutation between its pre/post stats.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any


REQUEST_SCHEMA = "ds02.request.v1"
SNAPSHOT_SCHEMA = "ds02.stage2.native-source-snapshot.v2"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUEST_TEMPLATE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-s2-medium-observer-v2/f1_s2_medium_dp020_selected_native_observer_v2.json"
SNAPSHOT_WORKER = REFERENCE / "stage2_native_source_snapshot_v2.py"
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
V6_RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v6.py"
V6_STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v6.py"
V6_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
V2_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CASE_ID = "F1_S2_MEDIUM_DP020_NATIVE_SOURCE_SNAPSHOT_V2"
ATTEMPT_ID = "f1-s2-medium-dp020-native-source-snapshot-v2-parent-001"
OUTPUT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-s2-medium-source-snapshot-v2/f1_s2_medium_source_snapshot_v2.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable request: {path}")
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_template() -> dict[str, Any]:
    value = json.loads(regular(REQUEST_TEMPLATE, "medium observer template").read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != REQUEST_SCHEMA:
        raise ValueError("medium template is not ds02.request.v1")
    if value.get("case_id") != "F1_S2_MEDIUM_DP020_SELECTED_NATIVE_OBSERVER_V2" or value.get("sentinel_id") != "F1-S2":
        raise ValueError("medium template identity changed")
    frames = value.get("selected_native_frame_ids")
    deferred = value.get("deferred_input_files")
    source = value.get("source_binding")
    if not isinstance(frames, list) or frames != [0, 99, 100, 199, 200, 299, 300, 399, 400]:
        raise ValueError("medium template selected frame set is not the registered 9-frame set")
    if not isinstance(deferred, list) or len(deferred) != 10:
        raise ValueError("medium template deferred input set is not raw-root plus nine BI4 paths")
    if not isinstance(source, dict) or not isinstance(source.get("raw_root"), str):
        raise ValueError("medium template lacks raw-root binding")
    if value.get("launch_disabled") is not True or value.get("execution_allowed") is not False:
        raise ValueError("medium observer template must remain launch-disabled")
    return value


def build(output: Path) -> dict[str, Any]:
    template = load_template()
    for path, label in ((SNAPSHOT_WORKER, "snapshot v2 worker"), (V6_RUNNER, "v6 runner"),
                        (V6_STRICT, "v6 strict runner"), (V6_RUNTIME, "v6 runtime"),
                        (V2_RUNTIME, "v2 runtime"), (PYTHON, "python")):
        regular(path, label)
    source = template["source_binding"]
    static_paths: list[Path] = [Path(__file__).resolve(), REQUEST_TEMPLATE, SNAPSHOT_WORKER,
                                V6_RUNNER, V6_STRICT, V6_RUNTIME, V2_RUNTIME, PYTHON]
    for key in ("runparts", "generated_xml", "source_gencase_receipt", "solver_receipt"):
        value = source.get(key)
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            static_paths.append(Path(value["path"]))
    static_paths = list(dict.fromkeys(path.expanduser().resolve() for path in static_paths))
    input_files = [str(regular(path, "static input")) for path in static_paths]
    input_hashes = {path: sha256(Path(path)) for path in input_files}
    raw_root = str(Path(str(source["raw_root"])).expanduser().resolve())
    selected_paths = [item for item in template["deferred_input_files"] if Path(item).name.startswith("Part_")]
    if len(selected_paths) != 9:
        raise ValueError("medium template does not provide exactly nine deferred Part paths")
    output_root = DATA_ROOT / "families/infra" / CASE_ID / ATTEMPT_ID
    command = [str(PYTHON), str(SNAPSHOT_WORKER), "--observer-request", str(REQUEST_TEMPLATE),
               "--output", "{attempt_root}/native_selected_source_snapshot_v2.json"]
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "physical_case_id": template["physical_case_id"],
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "command": command,
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": input_files,
        "input_hashes": input_hashes,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_native_read_bytes": "PARENT_GUARD_MEASURE_EXACT_NINE_SELECTED_FRAMES",
        "estimated_storage_bytes": 1024 * 1024 * 1024,
        "estimated_peak_memory_bytes": 1024 * 1024 * 1024,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "hdf5_read": False,
        "deferred_input_files": [raw_root, *selected_paths],
        "deferred_input_file_count": len(selected_paths),
        "deferred_hash_policy": {
            "worker_schema": SNAPSHOT_SCHEMA,
            "selected_frames_only": True,
            "exact_selected_native_frame_ids": template["selected_native_frame_ids"],
            "pre_post_stat_consistency": "REQUIRED; worker rejects any size/mtime/ctime/device/inode change",
            "full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER",
            "hdf5_read": False,
            "solver_launch": False,
        },
        "source_binding": {
            "template_request": record(REQUEST_TEMPLATE, "medium observer template"),
            "raw_root": raw_root,
            "selected_native_frame_ids": template["selected_native_frame_ids"],
            "selected_native_paths": selected_paths,
            "source_template_binding": template["source_binding"],
            "snapshot_schema": SNAPSHOT_SCHEMA,
            "source_sha_before_after_required": True,
        },
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "path": "{attempt_root}/native_selected_source_snapshot_v2.json",
            "status": "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE or explicit failure",
        },
        "qualification_stage": "stage2_f1_s2_medium_selected_native_source_snapshot_v2_pending_parent_cpu_guard",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(V6_RUNNER),
            "strict_guard": str(V6_STRICT),
            "runtime": str(V6_RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "launch_disabled": False,
        },
        "output_root": str(output_root),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(output, request)
    return request


def self_test() -> dict[str, Any]:
    template = load_template()
    assert template["selected_native_frame_ids"] == [0, 99, 100, 199, 200, 299, 300, 399, 400]
    return {"status": "PASS", "bi4_read": False, "selected_frame_count": 9,
            "pre_post_stat_guard": True, "solver_launch": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    request = build(args.output)
    print(json.dumps({"status": "PASS_REQUEST_BUILT", "output": str(args.output.resolve()),
                      "selected_frame_count": request["deferred_input_file_count"], "bi4_read": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

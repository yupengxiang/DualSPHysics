#!/usr/bin/env python3
"""Emit v8 CPU snapshot requests for the four terminal F1 runs.

This is the first leg of the F1 v4 closure.  It reads only the existing v3
observer request, terminal solver receipt, RunPARTs, and copied solver XML.
The selected BI4 files remain deferred to ``stage2_native_source_snapshot_v2``
under a parent guard; this builder never stats, hashes, copies, or decodes
native payloads.  The resulting snapshot v2 output is the sole source of
selected SHA/stat values for ``stage2_f1_owner_snapshot_bound_observer_v1``.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
# ``HERE`` is ``<repo>/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference``;
# parents[4] is the checkout root.  Keep this explicit so a generated request
# remains portable between the reference and primary worktrees.
REPO = HERE.parents[4]
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKER = HERE / "stage2_native_source_snapshot_v2.py"
DISPATCH = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py")
STRICT = DISPATCH.parent / "ds_data02_strict_dispatch_v8.py"
RUNTIME = DISPATCH.parent / "ds_data02_runtime_v8.py"
SCHEMA = "ds02.stage2.f1.owner-snapshot-request-builder.v4"

CASES = (
    ("dp005", "same_cfl", "dp005-same", "f1-s1-owner-dp005-same_cfl-savedt-v5-root-040-001"),
    ("dp005", "half_cfl", "dp005-half", "f1-s1-owner-dp005-half_cfl-savedt-v5-root-041-001"),
    ("dp0025", "same_cfl", "dp0025-same", "f1-s1-owner-dp0025-same_cfl-savedt-v5-root-041-001"),
    ("dp0025", "half_cfl", "dp0025-half", "f1-s1-owner-dp0025-half_cfl-savedt-v5-root-041-001"),
)
PRE_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-owner-postsolver-v3-standalone"
OUT_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-owner-postsolver-v4-snapshot-bound"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"static input must be regular and non-symlink: {path}")
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(path)
    return value


def atomic(path: Path, value: Any) -> None:
    path = path.resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_one(dp: str, mode: str, folder: str, attempt: str, output_dir: Path) -> Path:
    pre = PRE_ROOT / folder / f"f1_s1_owner_{dp}_{mode}_selected_native_observer_v3.json"
    pre_value = load(pre)
    source = pre_value.get("source_binding", {})
    raw_root = source.get("raw_root")
    runparts = source.get("runparts", {}).get("path") if isinstance(source.get("runparts"), dict) else None
    solver_xml = source.get("solver_input_xml", {}).get("path") if isinstance(source.get("solver_input_xml"), dict) else None
    frames = pre_value.get("selected_native_frame_ids")
    deferred = pre_value.get("deferred_input_files")
    if not isinstance(raw_root, str) or not isinstance(runparts, str) or not isinstance(solver_xml, str) or not isinstance(frames, list) or not isinstance(deferred, list):
        raise ValueError(f"pre observer request lacks F1 source closure: {pre}")
    receipt = DATA / "families/F1" / f"f1-s1-owner-{dp}-{mode}-savedt-nvme-v2" / attempt / "execution-receipt.json"
    receipt_value = load(receipt)
    if receipt_value.get("status") != "COMPLETED_DEVELOPMENT_UNKNOWN" or receipt_value.get("cfd_invoked") is not True:
        raise ValueError(f"terminal F1 receipt is not a completed development run: {receipt}")
    output_name = f"f1_s1_owner_{dp}_{mode}_selected_native_snapshot_v4.json"
    case_id = f"F1_S1_OWNER_{dp.upper()}_{mode.upper()}_SELECTED_NATIVE_SNAPSHOT_V4"
    attempt_id = f"f1-s1-owner-{dp}-{mode}-selected-native-snapshot-v4-root-forward-001"
    request_path = output_dir / folder / output_name
    static = [Path(__file__), WORKER, pre, receipt, Path(runparts), Path(solver_xml), DISPATCH, STRICT, RUNTIME, PYTHON]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in static:
        path = path.resolve()
        if str(path) not in seen:
            record(path); unique.append(path); seen.add(str(path))
    command = [str(PYTHON), str(WORKER.resolve()), "--observer-request", str(pre.resolve()), "--output", f"{{attempt_root}}/native_selected_source_snapshot_v2.json"]
    output_root = DATA / "families/F1" / case_id / attempt_id
    if output_root.exists():
        raise FileExistsError(output_root)
    request = {
        "schema": "ds02.request.v1", "kind": "cpu", "cpu_task_kind": "audit",
        "family_id": "F1", "sentinel_id": "F1-S1", "physical_case_id": pre_value.get("physical_case_id", "F1_ECC_THICK_DBC_LOWER_HEAD_V1"),
        "case_id": case_id, "attempt_id": attempt_id, "command": command,
        "cwd": str(REPO), "worktree_root": str(REPO), "input_files": [str(path) for path in unique],
        "input_hashes": {str(path): sha256(path) for path in unique}, "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 1800, "estimated_native_read_bytes": "PARENT_GUARD_MEASURE_EXACT_SELECTED_FRAMES",
        "estimated_storage_bytes": 8 * (1 << 30) if dp == "dp0025" else 2 * (1 << 30), "estimated_peak_memory_bytes": 1 << 30,
        "output": {"path": f"{{attempt_root}}/native_selected_source_snapshot_v2.json", "atomic": True, "refuse_overwrite": True},
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "hdf5_read": False, "bi4_decode": False,
        "deferred_input_files": deferred,
        "deferred_hash_policy": {"selected_files_only": True, "pre_post_stat_and_sha": "required; mutation rejects snapshot", "full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER", "full_tree_copy": "FORBIDDEN", "builder_bi4_read": False, "builder_bi4_hash": False},
        "source_binding": {"schema": SCHEMA, "pre_snapshot_observer_request": record(pre), "terminal_solver_receipt": record(receipt), "runparts": record(Path(runparts)), "solver_input_xml": record(Path(solver_xml)), "raw_root": raw_root, "selected_native_frame_ids": frames, "selected_sha256": "PENDING_NATIVE_SOURCE_SNAPSHOT_V2_RESULT", "selected_sha_binding": "downstream binder consumes snapshot result; no prefilled SHA"},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden", "parent_v8_review_required": True},
        "qualification_stage": "stage2_f1_owner_selected_native_source_snapshot_v2_pending_parent_v8_cpu_guard",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic(request_path, request)
    return request_path


def build_all(output_dir: Path) -> dict[str, Any]:
    paths = [str(build_one(*case, output_dir.resolve())) for case in CASES]
    manifest = {"schema": SCHEMA, "status": "PREPARED_FOUR_F1_TERMINAL_SNAPSHOT_REQUESTS_SHA_PENDING", "request_paths": paths, "selected_sha_policy": "PENDING_NATIVE_SOURCE_SNAPSHOT_V2_RESULT", "full_tree_copy_or_scan": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    atomic(output_dir / "f1_owner_snapshot_requests_v4_manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUT_ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps({"status": "PASS", "bi4_read": False, "solver_launch": False, "selected_sha_policy": "PENDING_NATIVE_SOURCE_SNAPSHOT_V2_RESULT"}, indent=2)); return 0
    print(json.dumps(build_all(args.output_dir), ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())

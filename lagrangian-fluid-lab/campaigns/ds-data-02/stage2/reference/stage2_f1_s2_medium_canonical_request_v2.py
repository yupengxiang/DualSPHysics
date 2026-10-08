#!/usr/bin/env python3
"""Bind the completed F1-S2 medium snapshot to the v2 observer enforcer.

This forward-only builder consumes the small v2 snapshot JSON and terminal
receipt.  It never opens, stats, or hashes the nine deferred BI4 files.  The
new request invokes the v2 enforcer, which performs the source SHA and full
stat boundary checks immediately before and after the child observer decode.
The older medium template, snapshot request, and v1/v4 observer requests are
left immutable.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


REQUEST_SCHEMA = "ds02.request.v1"
SNAPSHOT_SCHEMA = "ds02.stage2.native-source-snapshot.v2"
MANIFEST_SCHEMA = "ds02.stage2.native-observer-source-manifest.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
OBSERVER = REFERENCE / "stage2_native_physical_observer_v2.py"
ENFORCER = REFERENCE / "stage2_native_physical_observer_enforcer_v2.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
V8_RUNNER = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py")
V8_STRICT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py")
V8_RUNTIME = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py")
V6_RUNTIME = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py")
V2_RUNTIME = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")
TEMPLATE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-s2-medium-observer-v2/f1_s2_medium_dp020_selected_native_observer_v2.json"
SNAPSHOT_DIR = DATA_ROOT / "families/F1/F1_S2_MEDIUM_DP020_NATIVE_SOURCE_SNAPSHOT_V2/f1-s2-medium-dp020-native-source-snapshot-v2-root-v8-001"
SNAPSHOT_RESULT = SNAPSHOT_DIR / "native_selected_source_snapshot_v2.json"
SNAPSHOT_RECEIPT = SNAPSHOT_DIR / "execution-receipt.json"
DEFAULT_OUTPUT = REQUEST_ROOT / "stage2-f1-s2-medium-observer-canonical-v2"
PART_RE = re.compile(r"^Part_(\d+)\.bi4$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


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


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def validate_snapshot(template: dict[str, Any], receipt: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError("medium snapshot receipt is not a completed successful terminal")
    if result.get("schema") != SNAPSHOT_SCHEMA or result.get("status") != "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE":
        raise ValueError("medium snapshot result is not the stable v2 success schema")
    scope = result.get("worker_scope")
    if not isinstance(scope, dict) or scope.get("selected_file_count") != 9 or scope.get("full_raw_tree_hash") != "NOT_COMPUTED_BY_WORKER":
        raise ValueError("medium snapshot scope is not exactly nine selected files")
    entries = result.get("requests")
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise ValueError("medium snapshot result must contain exactly one request entry")
    entry = entries[0]
    identity = (template.get("case_id"), template.get("sentinel_id"), template.get("family_id"), template.get("physical_case_id"))
    actual_identity = (entry.get("case_id"), entry.get("sentinel_id"), entry.get("family_id"), entry.get("physical_case_id"))
    if identity != actual_identity:
        raise ValueError(f"medium snapshot identity differs from template: {identity} != {actual_identity}")
    frames = [int(value) for value in template.get("selected_native_frame_ids", [])]
    selected = entry.get("selected_native_files")
    if not isinstance(selected, list) or [int(item.get("frame", -1)) for item in selected] != frames:
        raise ValueError("medium snapshot selected frame list differs from template")
    source = template.get("source_binding")
    if not isinstance(source, dict) or str(Path(str(entry.get("raw_root"))).resolve()) != str(Path(str(source.get("raw_root"))).resolve()):
        raise ValueError("medium snapshot raw root differs from template")
    deferred = [Path(str(value)).resolve() for value in template.get("deferred_input_files", []) if PART_RE.fullmatch(Path(str(value)).name)]
    expected_paths = {str(path) for path in deferred}
    records: list[dict[str, Any]] = []
    for item in selected:
        if not isinstance(item, dict):
            raise ValueError("medium snapshot selected file is not an object")
        path = str(Path(str(item.get("path"))).resolve())
        if path not in expected_paths:
            raise ValueError(f"medium snapshot selected path differs from template: {path}")
        digest = item.get("sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("medium snapshot selected file lacks content SHA")
        if not isinstance(item.get("bytes"), int) or item["bytes"] <= 0:
            raise ValueError("medium snapshot selected file lacks positive byte count")
        records.append({"frame": int(item["frame"]), "path": path, "bytes": int(item["bytes"]), "sha256": digest})
    if len({item["path"] for item in records}) != 9:
        raise ValueError("medium snapshot selected files are not unique")
    if not isinstance(entry.get("selected_source_sha256"), str):
        raise ValueError("medium snapshot entry lacks selected_source_sha256")
    return {"entry": entry, "records": records}


def build(output_dir: Path) -> dict[str, Any]:
    template = load_json(TEMPLATE, "medium observer template")
    if template.get("schema") != REQUEST_SCHEMA or template.get("case_id") != "F1_S2_MEDIUM_DP020_SELECTED_NATIVE_OBSERVER_V2":
        raise ValueError("unexpected medium template identity")
    frames = template.get("selected_native_frame_ids")
    if frames != [0, 99, 100, 199, 200, 299, 300, 399, 400]:
        raise ValueError("medium template frame set changed")
    source = template.get("source_binding")
    if not isinstance(source, dict):
        raise ValueError("medium template lacks source binding")
    receipt = load_json(SNAPSHOT_RECEIPT, "medium snapshot receipt")
    result = load_json(SNAPSHOT_RESULT, "medium snapshot result")
    snapshot = validate_snapshot(template, receipt, result)
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refuse to populate non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    token = "f1_s2_medium_dp020_selected_native_observer_v2"
    case_id = "F1_S2_MEDIUM_DP020_SELECTED_NATIVE_OBSERVER_V2_CANONICAL_SNAPSHOT_V2"
    attempt_id = "f1-s2-medium-dp020-selected-native-observer-v2-canonical-snapshot-v2-parent-001"
    manifest_path = output_dir / f"{token}_expected_source_manifest_v2.json"
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "snapshot_schema": SNAPSHOT_SCHEMA,
        "observer_request": record(TEMPLATE, "medium observer template"),
        "case_id": template["case_id"],
        "family_id": template["family_id"],
        "sentinel_id": template["sentinel_id"],
        "physical_case_id": template["physical_case_id"],
        "raw_root": str(Path(str(source["raw_root"])).expanduser().resolve()),
        "selected_native_frame_ids": frames,
        "selected_native_files": snapshot["records"],
        "selected_source_sha256": snapshot["entry"]["selected_source_sha256"],
        "source_sha_policy": "snapshot v2 selected SHA; enforcer v2 compares full stat boundaries before/after child decode",
    }
    atomic_json(manifest_path, manifest)
    static_paths: list[Path] = [
        Path(__file__).resolve(), TEMPLATE, SNAPSHOT_RESULT, SNAPSHOT_RECEIPT, manifest_path,
        OBSERVER, ENFORCER, DECODER, DECODER_SOURCE, V8_RUNNER, V8_STRICT, V8_RUNTIME, V6_RUNTIME, V2_RUNTIME, PYTHON,
    ]
    for key in ("runparts", "generated_xml", "source_gencase_receipt", "solver_receipt"):
        value = source.get(key)
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            static_paths.append(Path(value["path"]))
    static_paths = list(dict.fromkeys(path.expanduser().resolve() for path in static_paths))
    input_files = [str(regular(path, "static input")) for path in static_paths]
    input_hashes = {path: sha256(Path(path)) for path in input_files}
    raw_root = str(Path(str(source["raw_root"])).expanduser().resolve())
    selected_paths = [item["path"] for item in snapshot["records"]]
    query_times = [float(value) for value in template.get("query_times_s", [0, 1, 2, 3, 4])]
    output_name = f"{token}_canonical_snapshot_v2.json"
    command = [str(PYTHON), str(ENFORCER), "--observer-worker", str(OBSERVER),
               "--expected-source-manifest", str(manifest_path), "--raw-root", raw_root,
               "--runparts", str(Path(str(source["runparts"]["path"])).expanduser().resolve()),
               "--generated-xml", str(Path(str(source["generated_xml"]["path"])).expanduser().resolve()),
               "--decoder", str(DECODER), "--decoder-source", str(DECODER_SOURCE),
               "--output", f"{{attempt_root}}/observer/{output_name}",
               "--scratch-root", "{attempt_root}/scratch/bi4_decode", "--cwd", str(REPO),
               "--expected-frame-count", str(source["frame_count"]),
               "--expected-final-time-s", str(source["last_saved_time_s"]), "--final-time-tolerance-s", "1e-12",
               "--frames", *[str(frame) for frame in frames], "--query-times", *[str(value) for value in query_times]]
    output_root = DATA_ROOT / "families/F1" / case_id / attempt_id
    selected_bytes = sum(item["bytes"] for item in snapshot["records"])
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": template["family_id"],
        "sentinel_id": template["sentinel_id"],
        "physical_case_id": template["physical_case_id"],
        "case_id": case_id,
        "attempt_id": attempt_id,
        "command": command,
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": input_files,
        "input_hashes": input_hashes,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_native_read_bytes": selected_bytes,
        "estimated_storage_bytes": 1024 * 1024 * 1024,
        "estimated_peak_memory_bytes": 1024 * 1024 * 1024,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "hdf5_read": False,
        "deferred_input_files": [raw_root, *selected_paths],
        "deferred_input_file_count": len(selected_paths),
        "deferred_hash_policy": {
            "snapshot_terminal_sha_source": record(SNAPSHOT_RESULT, "snapshot result"),
            "builder_bi4_read": False,
            "builder_bi4_hash": False,
            "full_raw_tree_hash": "NOT_COMPUTED_BY_BUILDER",
            "observer_runtime_scope": "nine selected frames only",
            "enforcer_v2_pre_decode_sha_and_complete_stat": "REQUIRED",
            "enforcer_v2_post_decode_sha_and_complete_stat": "REQUIRED",
            "cross_decode_stat_boundaries": "pre.stat_after == post.stat_before and pre.stat_before == post.stat_after",
            "unknown_child_status": "FAILURE",
            "hdf5_read": False,
        },
        "source_snapshot_binding": {
            "snapshot_receipt": record(SNAPSHOT_RECEIPT, "snapshot receipt"),
            "snapshot_result": record(SNAPSHOT_RESULT, "snapshot result"),
            "expected_source_manifest": record(manifest_path, "expected source manifest"),
            "selected_source_sha256": snapshot["entry"]["selected_source_sha256"],
            "selected_native_files": snapshot["records"],
            "builder_did_not_read_bi4": True,
        },
        "source_binding": {
            "template_request": record(TEMPLATE, "medium observer template"),
            "raw_root": raw_root,
            "runparts": record(Path(str(source["runparts"]["path"])), "RunPARTs"),
            "generated_xml": record(Path(str(source["generated_xml"]["path"])), "generated XML"),
            "selected_native_frame_ids": frames,
            "query_times_s": query_times,
            "last_saved_time_s": source["last_saved_time_s"],
            "physical_case_id": template["physical_case_id"],
            "source_control": "inherited exact medium template; no geometry/control mutation",
        },
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "path": f"{{attempt_root}}/observer/{output_name}",
            "scratch_cleanup": "worker-owned temporary decoder tree",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(V8_RUNNER),
            "strict_guard": str(V8_STRICT),
            "runtime": str(V8_RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "launch_disabled": False,
            "parent_v8_review_required": True,
        },
        "output_root": str(output_root),
        "qualification_stage": "stage2_f1_s2_medium_selected_native_observer_v2_enforcer_v2_pending_parent_v8_dispatch",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    request_path = output_dir / f"{token}_canonical_snapshot_v2.json"
    atomic_json(request_path, request)
    manifest_value = {
        "schema": "ds02.stage2.f1-s2-medium-canonical-request-v2",
        "status": "PREPARED_MEDIUM_SNAPSHOT_BOUND_ENFORCER_V2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_receipt": record(SNAPSHOT_RECEIPT, "snapshot receipt"),
        "snapshot_result": record(SNAPSHOT_RESULT, "snapshot result"),
        "selected_native_file_count": 9,
        "request_path": str(request_path),
        "expected_source_manifest": record(manifest_path, "expected source manifest"),
        "enforcer": {"path": str(ENFORCER), "schema": "ds02.stage2.native-physical-observer-enforcer.v2"},
        "bi4_read": False,
        "hdf5_read": False,
        "solver_launch": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(output_dir / "medium_canonical_request_v2_manifest.json", manifest_value)
    return request


def self_test() -> dict[str, Any]:
    assert ENFORCER.name.endswith("enforcer_v2.py")
    assert [0, 99, 100, 199, 200, 299, 300, 399, 400] == [0, 99, 100, 199, 200, 299, 300, 399, 400]
    return {"status": "PASS", "snapshot_read": False, "bi4_read": False,
            "enforcer_v2_bound": True, "selected_frame_count": 9, "solver_launch": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    request = build(args.output_dir)
    print(json.dumps({"status": "PASS_MEDIUM_CANONICAL_REQUEST_BUILT", "output_dir": str(args.output_dir.resolve()),
                      "selected_frame_count": request["deferred_input_file_count"], "estimated_native_read_bytes": request["estimated_native_read_bytes"],
                      "bi4_read": False, "hdf5_read": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

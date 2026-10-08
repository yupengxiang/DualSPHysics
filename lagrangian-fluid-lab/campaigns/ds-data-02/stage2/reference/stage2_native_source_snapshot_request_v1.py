#!/usr/bin/env python3
"""Build the v6 CPU request for the selected-native source snapshot.

The four observer requests retain their selected ``Part_*.bi4`` files as
deferred inputs.  They are deliberately absent from the v6 static input
closure: the snapshot worker hashes exactly those files during its bounded
CPU run and records their immutable content digests.  This builder reads only
the observer JSON metadata and ``stat`` metadata for the selected files; it
does not read BI4 contents or walk any raw tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


SCHEMA = "ds02.request.v1"
WORKTREE_ROOT = Path(__file__).resolve().parents[5]
MAIN_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
VENV_PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
REQUEST_ROOT = WORKTREE_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
OUTPUT_REQUEST = REQUEST_ROOT / "stage2-native-source-snapshot-v1/native_source_snapshot_v1.json"
WORKER = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_native_source_snapshot_v1.py"
)
OBSERVER_REQUESTS = (
    REQUEST_ROOT / "stage2-f1-s1-observer-v1/f1_s1_dp010_same_cfl_selected_native_observer_v1.json",
    REQUEST_ROOT / "stage2-f1-s1-observer-v1/f1_s1_dp010_half_cfl_selected_native_observer_v1.json",
    REQUEST_ROOT / "stage2-f1-s2-coarse-observer-v3/f1_s2_coarse_dp0225_selected_native_observer_v3.json",
    REQUEST_ROOT / "stage2-f1-s2-fine-observer-v2/f1_s2_fine_dp017_selected_native_observer_v2.json",
)
V6_RUNNER = MAIN_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v6.py"
V6_STRICT = MAIN_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v6.py"
V6_RUNTIME = MAIN_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
V2_RUNTIME = MAIN_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
PART_RE = re.compile(r"^Part_(\d+)\.bi4$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_file(path: Path, label: str) -> Path:
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file: {path}")
    return path.resolve()


def observer_metadata(path: Path) -> tuple[dict[str, Any], list[Path], list[int], Path]:
    path = regular_file(path, "observer request")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError(f"observer request is not {SCHEMA}: {path}")
    frames = value.get("selected_native_frame_ids")
    if not isinstance(frames, list) or not frames:
        raise ValueError(f"observer request has no selected frame IDs: {path}")
    try:
        frame_ids = [int(frame) for frame in frames]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"observer request has non-integer frame ID: {path}") from exc
    if any(frame < 0 for frame in frame_ids) or len(set(frame_ids)) != len(frame_ids):
        raise ValueError(f"observer request selected frame IDs are not unique: {path}")
    source = value.get("source_binding")
    raw_root = source.get("raw_root") if isinstance(source, dict) else None
    if not isinstance(raw_root, str) or not raw_root:
        raise ValueError(f"observer request has no source_binding.raw_root: {path}")
    raw_root_path = Path(raw_root).expanduser()
    if raw_root_path.is_symlink() or not raw_root_path.is_dir():
        raise ValueError(f"observer request raw root is not a regular directory: {raw_root_path}")
    raw_root_path = raw_root_path.resolve()
    deferred = value.get("deferred_input_files")
    if not isinstance(deferred, list) or not deferred:
        raise ValueError(f"observer request has no deferred_input_files: {path}")
    selected: dict[int, Path] = {}
    for item in deferred:
        if not isinstance(item, str):
            raise ValueError(f"deferred_input_files must contain strings: {path}")
        candidate = Path(item).expanduser()
        if candidate.is_symlink():
            raise ValueError(f"deferred selected source must not be a symlink: {candidate}")
        candidate = candidate.resolve()
        match = PART_RE.fullmatch(candidate.name)
        if match is None:
            continue
        if candidate.parent != raw_root_path:
            raise ValueError(f"selected BI4 is outside raw root: {candidate}")
        frame = int(match.group(1))
        if frame in selected and selected[frame] != candidate:
            raise ValueError(f"duplicate deferred frame with different paths: {path} frame {frame}")
        selected[frame] = candidate
    missing = [frame for frame in frame_ids if frame not in selected]
    if missing:
        raise ValueError(f"deferred input omits selected frame(s): {path}: {missing}")
    extra = sorted(set(selected) - set(frame_ids))
    if extra:
        raise ValueError(f"deferred input includes unselected BI4 frame(s): {path}: {extra}")
    files = [selected[frame] for frame in frame_ids]
    for candidate in files:
        if candidate.is_symlink() or not candidate.is_file():
            raise FileNotFoundError(f"selected BI4 is not a regular file: {candidate}")
    return value, files, frame_ids, raw_root_path


def collect_deferred() -> tuple[list[dict[str, Any]], list[str], int]:
    records: list[dict[str, Any]] = []
    deferred_paths: list[str] = []
    total_bytes = 0
    seen: set[str] = set()
    for observer_path in OBSERVER_REQUESTS:
        request, files, frame_ids, raw_root = observer_metadata(observer_path)
        for frame, candidate in zip(frame_ids, files):
            key = str(candidate)
            if key in seen:
                raise ValueError(f"same selected BI4 is bound by two observer requests: {candidate}")
            seen.add(key)
            size = candidate.stat().st_size
            total_bytes += size
            deferred_paths.append(key)
            records.append({
                "observer_request": str(observer_path.resolve()),
                "case_id": request.get("case_id", "UNKNOWN"),
                "sentinel_id": request.get("sentinel_id", "UNKNOWN"),
                "family_id": request.get("family_id", "UNKNOWN"),
                "physical_case_id": request.get("physical_case_id", "UNKNOWN"),
                "raw_root": str(raw_root),
                "frame": frame,
                "path": key,
                "bytes_at_prepare_stat_only": size,
                "content_sha256": "DEFERRED_TO_WORKER",
            })
    if len(records) != 36:
        raise ValueError(f"expected 36 selected BI4 files, found {len(records)}")
    return records, deferred_paths, total_bytes


def static_inputs(builder_path: Path) -> list[Path]:
    paths = [builder_path, WORKER, *OBSERVER_REQUESTS, V6_RUNNER, V6_STRICT,
             V6_RUNTIME, V2_RUNTIME, VENV_PYTHON.resolve()]
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = regular_file(path, "static input")
        key = str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def build_request(output_path: Path = OUTPUT_REQUEST) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"refuse to overwrite request: {output_path}")
    deferred_records, deferred_paths, selected_bytes = collect_deferred()
    inputs = static_inputs(Path(__file__).resolve())
    input_hashes = {str(path): sha256(path) for path in inputs}
    command = [
        str(VENV_PYTHON), str(WORKER),
    ]
    for observer_path in OBSERVER_REQUESTS:
        command.extend(["--observer-request", str(observer_path.resolve())])
    command.extend(["--output", "{attempt_root}/native_selected_source_snapshot_v1.json"])
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "infra",
        "case_id": "STAGE2_NATIVE_SOURCE_SNAPSHOT_V1",
        "attempt_id": "native-source-snapshot-v1-parent-001",
        "command": command,
        "cwd": str(WORKTREE_ROOT),
        "worktree_root": str(WORKTREE_ROOT),
        "input_files": [str(path) for path in inputs],
        "input_hashes": input_hashes,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "estimated_native_read_bytes": selected_bytes,
        "estimated_native_read_scope": "36 selected Part_*.bi4 files only; stat estimate, worker content hashes",
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "path": "{attempt_root}/native_selected_source_snapshot_v1.json",
            "content": "immutable selected BI4 SHA list; no decoded fields",
        },
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "hdf5_read": False,
        "deferred_input_files": deferred_paths,
        "deferred_input_file_count": len(deferred_paths),
        "deferred_input_bytes_at_prepare_stat_only": selected_bytes,
        "deferred_hash_policy": {
            "worker": "hash exactly deferred selected Part_*.bi4 paths and record bytes/mtime/SHA256",
            "runtime_static_input_closure": "does not include deferred BI4 contents",
            "full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER",
            "unlisted_part_files": "NOT_INSPECTED_BY_WORKER",
            "hdf5_read": False,
            "bi4_decode": False,
            "solver_launch": False,
        },
        "selected_native_bindings": deferred_records,
        "source_binding": {
            "snapshot_worker": str(WORKER),
            "selected_file_count": len(deferred_paths),
            "selected_file_scope": "four observer requests, nine native frames each",
            "source_sha256": "DEFERRED_TO_WORKER_OUTPUT",
        },
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
            "source_snapshot_only": True,
        },
        "qualification_stage": "stage2_selected_native_source_provenance_only",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(request, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temporary = output_path.with_name(output_path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_bytes(encoded)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return request


def validate_built_request(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schema") != SCHEMA:
        raise ValueError("wrong request schema")
    if set(request["input_files"]) != set(request["input_hashes"]):
        raise ValueError("static input files and registered digests differ")
    deferred = set(request["deferred_input_files"])
    if deferred & set(request["input_files"]):
        raise ValueError("deferred BI4 unexpectedly entered static input closure")
    if len(deferred) != 36:
        raise ValueError("snapshot request must bind exactly 36 deferred BI4 paths")
    return {"status": "PASS", "static_inputs": len(request["input_files"]), "deferred_files": len(deferred)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_REQUEST)
    args = parser.parse_args()
    request = build_request(args.output.resolve())
    print(json.dumps(validate_built_request(request), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

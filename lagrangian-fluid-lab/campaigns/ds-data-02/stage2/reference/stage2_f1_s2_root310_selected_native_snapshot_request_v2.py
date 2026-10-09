#!/usr/bin/env python3
"""Prepare the parent-guarded ROOT310 ten-file BI4 snapshot request v2.

ROOT279's observer request binds two raw roots (same-CFL and half-CFL), while
``stage2_native_source_snapshot_v2.py`` consumes one raw root per observer
request.  This source-only builder therefore emits two tiny observer templates
and one ds02.request.v1 parent request.  It stats the ten selected files for a
cost estimate but never opens or hashes a BI4 file.  The snapshot worker does
the single content pass after the parent reservation and rejects any
pre/post stat mutation.  No decoded fields, solver output, or scientific
qualification is produced here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYTHON_TARGET = Path("/usr/bin/python3.10")
PYVENV_CFG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg")
SNAPSHOT_WORKER = HERE / "stage2_native_source_snapshot_v2.py"
ROOT279_WORKER = HERE / "stage2_f1_s2_root279_pair_native_observer_guarded_v1.py"
ROOT279_BUILDER = HERE / "stage2_f1_s2_root279_pair_native_observer_request_v3.py"
ROOT279_CONTRACT = HERE / "stage2_f1_s2_root279_pair_native_observer_contract_v1.json"
V4_WRAPPER = HERE / "stage2_f1_native_selected_observer_guarded_v4.py"
V1_WORKER = HERE / "stage2_f1_native_selected_observer_v1.py"
BASE_OBSERVER = HERE / "stage2_native_physical_observer_v2.py"
RUNTIME = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
STRICT = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.root310-selected-native-source-snapshot-request.v2"
SNAPSHOT_SCHEMA = "ds02.stage2.native-source-snapshot.v2"
MAX_SMALL_BYTES = 16 * 1024 * 1024
PART_SUFFIX = ".bi4"
EXPECTED_FRAMES_PER_MODE = 5
EXPECTED_TOTAL = 10


class BuildError(RuntimeError):
    pass


def _regular(path: Path, label: str, *, allow_symlink: bool = False) -> Path:
    path = path.expanduser().absolute()
    if (path.is_symlink() and not allow_symlink) or not path.is_file():
        raise BuildError(f"{label} is not a regular file: {path}")
    return path


def _small_record(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    before = path.stat()
    if before.st_size > MAX_SMALL_BYTES:
        raise BuildError(f"{label} exceeds bounded metadata read: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    before_sig = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    after_sig = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if before_sig != after_sig:
        raise BuildError(f"{label} changed during bounded read: {path}")
    return {
        "path": str(path), "label": label, "bytes": int(after.st_size),
        "sha256": digest.hexdigest(), "stat": {
            "dev": int(after.st_dev), "ino": int(after.st_ino),
            "bytes": int(after.st_size), "mtime_ns": int(after.st_mtime_ns),
            "ctime_ns": int(after.st_ctime_ns),
        }, "payload_read_by_builder": False,
    }


def _stat_only(path: Path, label: str) -> dict[str, Any]:
    """Record selected BI4 size/stat without opening it."""
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != PART_SUFFIX:
        raise BuildError(f"{label} is not a regular selected BI4: {path}")
    value = path.stat()
    return {
        "path": str(path), "label": label, "bytes_at_prepare_stat_only": int(value.st_size),
        "content_sha256": "DEFERRED_TO_ROOT310_SNAPSHOT_WORKER",
        "stat_at_prepare": {
            "dev": int(value.st_dev), "ino": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns),
        }, "payload_read_by_builder": False,
    }


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise BuildError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    record = _small_record(path, label)
    value = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BuildError(f"{label} is not a JSON object")
    return value, record


def _load_root279(path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    request, request_record = _load_json(path, "ROOT279 v3 observer request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("variant_schema") != "ds02.stage2.f1-s2.root279-pair-native-observer-request.v3":
        raise BuildError("ROOT310 requires the additive ROOT279 v3 request")
    if request.get("family_id") != "F1" or request.get("sentinel_id") != "F1-S2":
        raise BuildError("ROOT279 identity is not F1-S2")
    if request.get("solver_started") is not False or request.get("hdf5_read") is not False:
        raise BuildError("ROOT279 request has an unsafe execution flag")
    command = request.get("command")
    if not isinstance(command, list) or "--manifest" not in command:
        raise BuildError("ROOT279 v3 command lacks its manifest argument")
    manifest_index = command.index("--manifest")
    if manifest_index + 1 >= len(command) or not isinstance(command[manifest_index + 1], str) or "{attempt_root}" in command[manifest_index + 1]:
        raise BuildError("ROOT279 v3 manifest path still contains a materialization placeholder")
    deferred = request.get("deferred_input_records")
    paths = request.get("deferred_input_files")
    if not isinstance(deferred, list) or len(deferred) != EXPECTED_TOTAL or not isinstance(paths, list):
        raise BuildError("ROOT279 must bind exactly ten deferred selected records")
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in deferred:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise BuildError("ROOT279 deferred record lacks a path")
        path_value = str(Path(item["path"]).expanduser().absolute())
        if path_value in seen or Path(path_value).suffix.lower() != PART_SUFFIX:
            raise BuildError("ROOT279 deferred paths are not unique selected BI4 files")
        seen.add(path_value)
        if not isinstance(item.get("frame"), int) or item["frame"] < 0:
            raise BuildError("ROOT279 deferred frame identity is malformed")
        selected.append({"path": path_value, "frame": int(item["frame"]), "time_s": item.get("time_s")})
    if set(path_value for path_value in paths if isinstance(path_value, str) and path_value.endswith(PART_SUFFIX)) != seen:
        raise BuildError("ROOT279 deferred file list and records differ")
    if len({Path(item["path"]).parent for item in selected}) != 2:
        raise BuildError("ROOT279 must contain exactly two raw-root groups")
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in selected:
        groups.setdefault(str(Path(item["path"]).parent), []).append(item)
    if any(len(group) != EXPECTED_FRAMES_PER_MODE for group in groups.values()):
        raise BuildError("ROOT279 each same/half raw-root group must have five selected frames")
    return request, request_record, selected


def _template(request: dict[str, Any], request_record: dict[str, Any], group: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    raw_root = str(Path(group[0]["path"]).parent)
    frames = sorted(int(item["frame"]) for item in group)
    paths = [item["path"] for item in sorted(group, key=lambda item: int(item["frame"]))]
    if len(set(frames)) != EXPECTED_FRAMES_PER_MODE:
        raise BuildError(f"ROOT310 {mode} selected frame IDs are not unique")
    return {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu", "cpu_task_kind": "audit",
        "family_id": "F1", "sentinel_id": "F1-S2",
        "physical_case_id": request.get("physical_case_id", "UNKNOWN"),
        "case_id": f"F1_S2_ROOT310_{mode.upper()}_SELECTED_SOURCE_SNAPSHOT",
        "attempt_id": f"f1-s2-root310-{mode}-selected-source-snapshot-v2-001",
        "selected_native_frame_ids": frames,
        "source_binding": {
            "raw_root": raw_root, "root279_request": request_record,
            "root279_variant": request.get("variant_schema"), "mode": mode,
        },
        "command": [str(PYTHON), str(SNAPSHOT_WORKER), "--raw-root", raw_root],
        "deferred_input_files": [raw_root, *paths],
        "deferred_input_file_count": EXPECTED_FRAMES_PER_MODE,
        "execution_allowed": False, "launch_disabled": True,
        "solver_started": False, "hdf5_read": False, "bi4_decode": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    root279, root279_record, selected = _load_root279(args.root279_request)
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in selected:
        groups.setdefault(str(Path(item["path"]).parent), []).append(item)
    ordered_groups = sorted(groups.items(), key=lambda pair: pair[0])
    # The producer paths are the source authority for mode assignment; do not
    # infer a case from a user label or silently swap the two terminal roots.
    if not any("ROOT277" in raw_root for raw_root, _ in ordered_groups) or not any("ROOT278" in raw_root for raw_root, _ in ordered_groups):
        raise BuildError("ROOT310 selected roots do not identify ROOT277 and ROOT278 producers")
    same_pair = next(group for raw_root, group in ordered_groups if "ROOT277" in raw_root)
    half_pair = next(group for raw_root, group in ordered_groups if "ROOT278" in raw_root)
    templates = {
        "same_cfl": _template(root279, root279_record, same_pair, "same_cfl"),
        "half_cfl": _template(root279, root279_record, half_pair, "half_cfl"),
    }
    template_paths = {mode: Path(path).expanduser().absolute() for mode, path in (("same_cfl", args.same_template), ("half_cfl", args.half_template))}
    for mode, path in template_paths.items():
        _write_once(path, templates[mode])
    template_records = {mode: _small_record(path, f"ROOT310 {mode} observer template") for mode, path in template_paths.items()}
    selected_records = [_stat_only(Path(item["path"]), f"ROOT310 selected {item['frame']} {('same' if 'ROOT277' in item['path'] else 'half')}") for item in selected]
    static_paths = [
        Path(__file__), args.root279_request, template_paths["same_cfl"], template_paths["half_cfl"],
        SNAPSHOT_WORKER, ROOT279_WORKER, ROOT279_BUILDER, ROOT279_CONTRACT,
        V4_WRAPPER, V1_WORKER, BASE_OBSERVER, RUNTIME, STRICT, PYVENV_CFG, PYTHON_TARGET,
    ]
    source_records: dict[str, dict[str, Any]] = {}
    for path, label in ((path, f"ROOT310 source {Path(path).name}") for path in static_paths):
        record = _small_record(Path(path), label)
        source_records[record["path"]] = record
    deferred_paths = sorted(item["path"] for item in selected)
    raw_roots = sorted({str(Path(path).parent) for path in deferred_paths})
    request = {
        "schema": REQUEST_SCHEMA, "variant_schema": VARIANT_SCHEMA,
        "status": "READY_FOR_PARENT_V8_ROOT310_SELECTED_NATIVE_SOURCE_SNAPSHOT",
        "kind": "cpu", "cpu_task_kind": "audit", "request_id": "f1-s2-root310-selected-native-source-snapshot-v2-001",
        "family_id": "F1", "sentinel_id": "F1-S2", "physical_case_id": root279.get("physical_case_id", "UNKNOWN"),
        "case_id": "F1_S2_ROOT310_SELECTED_NATIVE_SOURCE_SNAPSHOT", "attempt_id": "f1-s2-root310-selected-native-source-snapshot-v2-001",
        "cwd": str(PRIMARY), "worktree_root": str(PRIMARY),
        "command": [str(PYTHON), str(SNAPSHOT_WORKER), "--observer-request", str(template_paths["same_cfl"]), "--observer-request", str(template_paths["half_cfl"]), "--output", "{attempt_root}/native_selected_source_snapshot_v2.json"],
        "literal_venv_invocation": {"path": str(PYTHON), "argv0_literal": True, "resolved_target": str(PYTHON_TARGET), "pyvenv_cfg": str(PYVENV_CFG)},
        "input_files": sorted(source_records), "input_sha256": {path: source_records[path]["sha256"] for path in sorted(source_records)}, "input_records": source_records,
        "deferred_input_files": [*raw_roots, *deferred_paths], "deferred_input_file_count": EXPECTED_TOTAL,
        "selected_native_bindings": selected_records,
        "source_binding": {"root279_request": root279_record, "same_template": template_records["same_cfl"], "half_template": template_records["half_cfl"], "selected_frame_count": EXPECTED_TOTAL, "selected_frames_per_mode": EXPECTED_FRAMES_PER_MODE, "raw_roots": raw_roots, "content_sha256": "DEFERRED_TO_ROOT310_WORKER"},
        "deferred_hash_policy": {"worker_schema": SNAPSHOT_SCHEMA, "selected_files_only": True, "pre_post_stat_consistency": "REQUIRED; reject bytes/mtime/ctime/device/inode mutation", "content_hash_passes": 1, "full_raw_tree_hash": "NOT_COMPUTED", "bi4_decode": False, "solver_launch": False},
        "resource_guard": {"cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "memory_bytes": 1024 * 1024 * 1024, "estimated_storage_bytes": 64 * 1024 * 1024, "parent_reservation_required": True, "gpu": "none", "hdf5_read": False, "solver_launch": False},
        "estimated_native_read_passes": 1, "estimated_native_read_bytes": sum(int(item["bytes_at_prepare_stat_only"]) for item in selected_records), "estimated_native_read_bytes_scope": "ten selected Part_*.bi4 files; stat estimate only until ROOT310 worker", "estimated_native_stat_ops": EXPECTED_TOTAL * 2,
        "output": {"path": "{attempt_root}/native_selected_source_snapshot_v2.json", "atomic": True, "refuse_overwrite": True},
        "launch_disabled": False, "execution_allowed": True, "solver_started": False, "native_payload_read": False, "hdf5_read": False, "ledger_mutation": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }
    _write_once(args.output, request)
    return request


def self_test() -> None:
    fixture = {
        "schema": REQUEST_SCHEMA, "variant_schema": "ds02.stage2.f1-s2.root279-pair-native-observer-request.v3",
        "family_id": "F1", "sentinel_id": "F1-S2", "deferred_input_records": [], "deferred_input_files": [],
        "solver_started": False, "hdf5_read": False, "command": ["python", "--manifest", "/tmp/absolute.json"],
    }
    for mode, root in (("same", "/var/tmp/F1_S2_DP020_SAVEDT_SAME_CFL_ROOT277/x/data"), ("half", "/var/tmp/F1_S2_DP020_SAVEDT_HALF_CFL_ROOT278/x/data")):
        for frame in (0, 49, 50, 99, 100):
            path = f"{root}/Part_{frame:04d}.bi4"
            fixture["deferred_input_records"].append({"path": path, "frame": frame, "time_s": float(frame)})
            fixture["deferred_input_files"].append(path)
    assert len(fixture["deferred_input_records"]) == EXPECTED_TOTAL
    assert all(item["path"].endswith(PART_SUFFIX) for item in fixture["deferred_input_records"])
    assert "{attempt_root}" not in " ".join(fixture["command"])
    # Exercise the real ROOT310 builder entry with two temporary raw roots.
    # The files contain only tiny fixture bytes; the builder must stat them,
    # never open/hash them, and must emit both runnable snapshot templates.
    with tempfile.TemporaryDirectory(prefix="root310-v2-builder-") as td:
        root = Path(td)
        same = root / "F1_S2_ROOT277_RAW"; half = root / "F1_S2_ROOT278_RAW"
        same.mkdir(); half.mkdir()
        deferred = []
        for base in (same, half):
            for frame in (0, 49, 50, 99, 100):
                part = base / f"Part_{frame:04d}.bi4"; part.write_bytes(b"fixture")
                deferred.append({"path": str(part), "frame": frame, "time_s": float(frame)})
        root_request = root / "root279-v3.json"
        root_request.write_text(json.dumps({
            "schema": REQUEST_SCHEMA,
            "variant_schema": "ds02.stage2.f1-s2.root279-pair-native-observer-request.v3",
            "family_id": "F1", "sentinel_id": "F1-S2", "physical_case_id": "fixture",
            "solver_started": False, "hdf5_read": False,
            "command": [str(PYTHON), "--manifest", str(root / "manifest.json")],
            "deferred_input_records": deferred,
            "deferred_input_files": [item["path"] for item in deferred],
        }, indent=2), encoding="utf-8")
        output = root / "root310-request.json"
        result = build(argparse.Namespace(root279_request=root_request,
                                          same_template=root / "same-template.json",
                                          half_template=root / "half-template.json",
                                          output=output))
        assert result["deferred_input_file_count"] == EXPECTED_TOTAL
        assert json.loads((root / "same-template.json").read_text(encoding="utf-8"))["deferred_input_file_count"] == EXPECTED_FRAMES_PER_MODE
        assert json.loads((root / "half-template.json").read_text(encoding="utf-8"))["deferred_input_file_count"] == EXPECTED_FRAMES_PER_MODE
    print("PASS_F1_S2_ROOT310_REQUEST_V2_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--build", action="store_true")
    parser.add_argument("--root279-request", type=Path)
    parser.add_argument("--same-template", type=Path)
    parser.add_argument("--half-template", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test(); return 0
    required = (args.root279_request, args.same_template, args.half_template, args.output)
    if any(value is None for value in required):
        parser.error("--build requires --root279-request, --same-template, --half-template, and --output")
    try:
        request = build(args)
    except Exception as exc:
        print(f"ROOT310 V2 builder failed: {exc}", file=os.sys.stderr)
        return 2
    print(json.dumps({"status": request["status"], "deferred_count": request["deferred_input_file_count"], "native_payload_read": False, "request": str(args.output.absolute())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

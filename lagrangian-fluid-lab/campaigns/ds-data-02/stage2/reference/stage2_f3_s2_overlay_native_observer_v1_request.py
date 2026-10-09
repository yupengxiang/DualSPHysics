#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build a post-terminal guarded observer request for ROOT162/173/174.

This is an additive adapter over the consumed full-native v5 request builder.
It is intentionally not runnable until a terminal solver request, receipt,
proof, source snapshot and output paths are supplied.  Building the request
hashes only the small metadata/XML/RunPARTs inputs that the delegated v5
builder already permits; the native Part tree remains a parent-reserved,
worker-owned input.
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
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
V5_REQUEST_PATH = HERE / "stage2_f3_s2_full_native_stream_observer_v5_request.py"
WRAPPER_NAME = "stage2_f3_s2_overlay_native_observer_v1.py"
CONTRACT_NAME = "stage2_f3_s2_overlay_native_task_contract_v1.json"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.overlay-native-observer-request.v1"


def _load_v5_request():
    spec = importlib.util.spec_from_file_location(
        "stage2_f3_s2_overlay_native_observer_v1_v5_request_dependency", V5_REQUEST_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(V5_REQUEST_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V5_REQUEST = _load_v5_request()


def _path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def _repo_file(name: str) -> Path:
    for root in (PRIMARY_REPO, LOCAL_REPO):
        candidate = root / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference" / name
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise FileNotFoundError(name)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _record(path: Path, label: str, *, max_bytes: int = 32 * 1024 * 1024) -> dict[str, Any]:
    path = _path(path)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    if int(stat.st_size) > max_bytes:
        raise ValueError(f"{label} exceeds small-input limit: {stat.st_size}")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": _sha256(path),
        "content_scope": "small_input_hashed_by_builder_and_parent_v8",
    }


def _canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def _set_after_flag(command: list[str], flag: str, value: str) -> None:
    try:
        index = command.index(flag)
    except ValueError as exc:
        raise ValueError(f"delegated observer command lacks {flag}") from exc
    if index + 1 >= len(command):
        raise ValueError(f"delegated observer command has no value after {flag}")
    command[index + 1] = value


def _replace_worker(command: list[str], worker: Path) -> None:
    if len(command) < 2:
        raise ValueError("delegated observer command has no worker operand")
    command[1] = str(worker)


def build(args: argparse.Namespace) -> dict[str, Any]:
    if args.overlay_label not in {"same_cfl_baseline", "half_cfl", "half_output"}:
        raise ValueError("overlay label is outside the frozen F3 overlay contract")
    if args.overlay_variable not in {"none", "CFLnumber", "TimeOut"}:
        raise ValueError("overlay variable is outside the frozen one-variable contract")
    if not str(args.overlay_value):
        raise ValueError("overlay value must be explicit")

    base = V5_REQUEST.build(args)
    wrapper = _repo_file(WRAPPER_NAME)
    contract = _repo_file(CONTRACT_NAME)
    wrapper_record = _record(wrapper, "overlay native observer wrapper")
    contract_record = _record(contract, "overlay native task contract")
    records = dict(base["input_records"])
    records[wrapper_record["path"]] = wrapper_record
    records[contract_record["path"]] = contract_record
    input_files = sorted(records)
    hashes = {path: records[path]["sha256"] for path in input_files if records[path].get("sha256") is not None}

    output_path = "{attempt_root}/observer/f3_s2_overlay_native_observer_v1.json"
    summary_path = "{attempt_root}/observer/f3_s2_overlay_native_observer_v1.summary.json"
    binding_path = "{attempt_root}/observer/f3_s2_overlay_native_observer_v1.binding.json"
    command = list(base["command"])
    _replace_worker(command, wrapper)
    _set_after_flag(command, "--output", output_path)
    _set_after_flag(command, "--summary-output", summary_path)
    command.extend([
        "--binding-output", binding_path,
        "--overlay-label", str(args.overlay_label),
        "--overlay-variable", str(args.overlay_variable),
        "--overlay-value", str(args.overlay_value),
    ])

    base_static = int(base.get("estimated_static_small_input_bytes", 0) or 0)
    static_bytes = sum(int(item.get("bytes", 0) or 0) for item in records.values())
    value: dict[str, Any] = dict(base)
    value.update({
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V8_OVERLAY_NATIVE_OBSERVER",
        "request_variant_status": "READY_AFTER_TERMINAL_OVERLAY_WITH_NATIVE_MASS_AND_BRACKET_SCOPE",
        "command": command,
        "input_files": input_files,
        "input_hashes": hashes,
        "input_sha256": hashes,
        "input_records": records,
        "estimated_static_small_input_bytes": max(static_bytes, base_static),
        "estimated_input_read_bytes": int(base.get("estimated_native_read_bytes", 0)) + static_bytes,
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "path": output_path,
            "compact_summary_path": summary_path,
            "binding_path": binding_path,
        },
        "source_binding": dict(base.get("source_binding", {})),
        "overlay_binding": {
            "label": str(args.overlay_label),
            "changed_variable": str(args.overlay_variable),
            "changed_value": str(args.overlay_value),
            "source_bi4_and_forcing_unchanged": True,
            "continuous_owner_unchanged": True,
            "native_mass_source": "decoded native_header.MassFluid",
            "xml_mass_fallback": False,
            "registered_query_times_s": [0.0, 2.0, 4.0, 6.0, 8.0, float(args.expected_final_time_s)],
            "time_interpolation": False,
            "neighbor_grid_as_truth": False,
            "event_time": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
        },
        "qualification_stage": "stage2_f3_s2_overlay_native_observer_pending_parent_guard",
        "scientific_qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "native field/header/time/source audit only; later comparison keeps integration/output/spatial/event errors separate",
        },
    })
    value["resource_guard"] = dict(base.get("resource_guard", {}))
    value["resource_guard"].update({
        "wrapper_sidecar_written_in_same_guard": True,
        "full_report_payload_not_reopened_by_wrapper": True,
        "solver_launch": "forbidden",
    })
    value["sha256"] = _canonical(value)
    return value


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = _path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    delegated = V5_REQUEST.self_test()
    if delegated.get("status") != "PASS":
        raise AssertionError(delegated)
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "delegated_schema": V5_REQUEST.VARIANT,
        "payload_read": False,
        "solver_started": False,
        "native_mass_source": "native_header.MassFluid",
        "xml_mass_fallback": False,
        "event_time": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--solver-request", type=Path)
    parser.add_argument("--terminal-receipt", type=Path)
    parser.add_argument("--terminal-proof", type=Path)
    parser.add_argument("--source-snapshot-proof", type=Path)
    parser.add_argument("--source-snapshot-report", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--runparts", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--calibration-contract", type=Path, default=None)
    parser.add_argument("--expected-frame-count", type=int)
    parser.add_argument("--expected-final-time-s", type=float)
    parser.add_argument("--expected-dp-m", type=float)
    parser.add_argument("--expected-initial-fluid-count", type=int)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1.0e-9)
    parser.add_argument("--estimated-part-bytes", type=int)
    parser.add_argument("--estimated-native-tree-bytes", type=int)
    parser.add_argument("--estimated-output-records", type=int)
    parser.add_argument("--estimated-storage-bytes", type=int)
    parser.add_argument("--launch-commit")
    parser.add_argument("--case-id", default="F3_S2_OVERLAY_NATIVE_OBSERVER")
    parser.add_argument("--attempt-id", default="f3-s2-overlay-native-observer-v1-001")
    parser.add_argument("--overlay-label", required=False, default="same_cfl_baseline")
    parser.add_argument("--overlay-variable", required=False, default="none")
    parser.add_argument("--overlay-value", required=False, default="0.05/0.01")
    parser.add_argument("--output", type=Path, default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-overlay-native-observer-v1.json")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if args.calibration_contract is None:
        args.calibration_contract = _repo_file("stage2_f3_s2_observer_calibration_contract_v1.json")
    required = (
        args.solver_request, args.terminal_receipt, args.terminal_proof,
        args.source_snapshot_proof, args.source_snapshot_report, args.raw_root,
        args.runparts, args.generated_xml, args.expected_frame_count,
        args.expected_final_time_s, args.expected_dp_m, args.expected_initial_fluid_count,
        args.estimated_part_bytes, args.estimated_native_tree_bytes,
        args.estimated_storage_bytes, args.launch_commit,
    )
    if any(item is None for item in required):
        parser.error("--build-request requires terminal/source paths, frame contract, byte estimates and launch commit")
    try:
        value = build(args)
        _write_once(args.output, value)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F3_OVERLAY_NATIVE_OBSERVER_REQUEST_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": value["status"], "output": str(_path(args.output)), "payload_read": "parent_after_reservation", "solver_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

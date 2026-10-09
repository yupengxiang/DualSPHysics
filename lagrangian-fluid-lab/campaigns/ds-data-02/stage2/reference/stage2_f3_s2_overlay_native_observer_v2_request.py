#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build a V2 ROOT173/174 overlay observer request.

This is an additive request adapter over the consumed V1 builder.  It keeps
the V1 terminal/source accounting and replaces only the worker and contract
with the V2 in-memory V8 snapshot-binding adapter.  The terminal solver
request, receipt, proof, native tree, and source bytes are immutable inputs;
this builder performs no native payload read and never launches a solver.
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
V1_REQUEST_PATH = HERE / "stage2_f3_s2_overlay_native_observer_v1_request.py"
WRAPPER_NAME = "stage2_f3_s2_overlay_native_observer_v2.py"
CONTRACT_NAME = "stage2_f3_s2_overlay_native_task_contract_v2.json"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.overlay-native-observer-request.v2"


def _load_v1_request():
    spec = importlib.util.spec_from_file_location(
        "stage2_f3_s2_overlay_native_observer_v2_v1_request_dependency", V1_REQUEST_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(V1_REQUEST_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V1_REQUEST = _load_v1_request()


def _repo_file(name: str) -> Path:
    for root in (PRIMARY_REPO, LOCAL_REPO):
        candidate = root / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference" / name
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise FileNotFoundError(name)


def _record(path: Path, label: str, *, max_bytes: int = 32 * 1024 * 1024) -> dict[str, Any]:
    return V1_REQUEST._record(path, label, max_bytes=max_bytes)


def _canonical(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            {key: item for key, item in value.items() if key != "sha256"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
            default=str,
        ).encode()
    ).hexdigest()


def _set_after_flag(command: list[str], flag: str, value: str) -> None:
    try:
        index = command.index(flag)
    except ValueError as exc:
        raise ValueError(f"delegated observer command lacks {flag}") from exc
    if index + 1 >= len(command):
        raise ValueError(f"delegated observer command has no value after {flag}")
    command[index + 1] = value


def _request_snapshot_binding(request: dict[str, Any]) -> dict[str, Any]:
    """Build the V3-compatible BI4 binding from an actual V8 request.

    The delegated V1/V5 builder performs terminal metadata validation while
    constructing the new request.  This adapter supplies the same in-memory
    shape used by the V2 worker without changing the immutable terminal q.
    """
    source = request.get("source_provenance")
    input_sha = request.get("input_sha256")
    if not isinstance(source, dict) or not isinstance(input_sha, dict):
        raise ValueError("terminal V8 request lacks source metadata")
    proof = source.get("root161_snapshot_proof")
    generated_bi4 = source.get("generated_bi4")
    if not isinstance(proof, dict) or not isinstance(generated_bi4, dict):
        raise ValueError("terminal V8 request lacks ROOT161 snapshot metadata")
    proof_path = proof.get("path")
    proof_sha = proof.get("sha256")
    bi4_path = generated_bi4.get("path")
    bi4_sha = input_sha.get(str(bi4_path))
    bi4_bytes = generated_bi4.get("bytes")
    if not isinstance(proof_path, str) or not isinstance(proof_sha, str) or len(proof_sha) != 64:
        raise ValueError("ROOT161 snapshot proof path/SHA binding is incomplete")
    if not isinstance(bi4_path, str) or not isinstance(bi4_sha, str) or len(bi4_sha) != 64:
        raise ValueError("V8 generated BI4 path/SHA binding is incomplete")
    if not isinstance(bi4_bytes, int) or bi4_bytes <= 0:
        raise ValueError("V8 generated BI4 byte binding is incomplete")
    return {
        "proof": proof_path,
        "proof_sha256": proof_sha,
        "bi4": {
            "path": bi4_path,
            "content_sha256": bi4_sha,
            "expected_bytes": bi4_bytes,
        },
        "adapter_source": "V8 source_provenance.root161_snapshot_proof + generated_bi4 + input_sha256",
        "payload_read_by_adapter": False,
    }


def _load_json_with_v8_adapter(original, request_path: Path):
    def load(path: Path, label: str):
        value = original(path, label)
        if Path(path).expanduser().resolve() != request_path or "bi4_snapshot_binding" in value:
            return value
        enriched = dict(value)
        enriched["bi4_snapshot_binding"] = _request_snapshot_binding(value)
        return enriched

    return load


def build(args: argparse.Namespace) -> dict[str, Any]:
    if args.overlay_label not in {"same_cfl_baseline", "half_cfl", "half_output"}:
        raise ValueError("overlay label is outside the frozen F3 overlay contract")
    if args.overlay_variable not in {"none", "CFLnumber", "TimeOut"}:
        raise ValueError("overlay variable is outside the frozen one-variable contract")

    # V1 delegates to the consumed V5/V3 builder, which validates the
    # terminal request while building and expects the later observer schema's
    # top-level BI4 binding.  Adapt only that in-memory load for this V8 q.
    # The request builder loads the V3 worker for terminal binding; patch that
    # worker module's loader for the same narrow in-memory adapter, and force
    # the builder to reuse that patched module instance.
    delegated_v3 = V1_REQUEST.V5_REQUEST.V4_REQUEST.V3_REQUEST
    request_path = Path(args.solver_request).expanduser().resolve()
    original_load_worker = delegated_v3._load_worker
    worker_module = original_load_worker()
    original_loader = worker_module._load_json
    worker_module._load_json = _load_json_with_v8_adapter(original_loader, request_path)
    delegated_v3._load_worker = lambda: worker_module
    try:
        base = V1_REQUEST.build(args)
    finally:
        delegated_v3._load_worker = original_load_worker
        worker_module._load_json = original_loader
    wrapper = _repo_file(WRAPPER_NAME)
    contract = _repo_file(CONTRACT_NAME)
    wrapper_record = _record(wrapper, "overlay native observer V2 wrapper")
    contract_record = _record(contract, "overlay native V2 task contract")

    records = dict(base["input_records"])
    # The V1 worker and contract are not runtime dependencies of V2.  Remove
    # them from this new request rather than claiming the old worker is bound.
    for path in list(records):
        if path.endswith("/stage2_f3_s2_overlay_native_observer_v1.py") or path.endswith(
            "/stage2_f3_s2_overlay_native_task_contract_v1.json"
        ):
            records.pop(path, None)
    records[wrapper_record["path"]] = wrapper_record
    records[contract_record["path"]] = contract_record

    input_files = sorted(records)
    hashes = {path: records[path]["sha256"] for path in input_files if records[path].get("sha256") is not None}
    command = list(base["command"])
    if len(command) < 2:
        raise ValueError("delegated observer command has no worker operand")
    command[1] = str(wrapper)
    _set_after_flag(command, "--output", "{attempt_root}/observer/f3_s2_overlay_native_observer_v2.json")
    _set_after_flag(command, "--summary-output", "{attempt_root}/observer/f3_s2_overlay_native_observer_v2.summary.json")
    _set_after_flag(command, "--binding-output", "{attempt_root}/observer/f3_s2_overlay_native_observer_v2.binding.json")

    value: dict[str, Any] = dict(base)
    value.update(
        {
            "schema": SCHEMA,
            "variant_schema": VARIANT,
            "status": "READY_FOR_PARENT_V8_OVERLAY_NATIVE_OBSERVER_V2",
            "request_variant_status": "READY_AFTER_TERMINAL_OVERLAY_WITH_V8_SNAPSHOT_BINDING_ADAPTER",
            "command": command,
            "input_files": input_files,
            "input_hashes": hashes,
            "input_sha256": hashes,
            "input_records": records,
            "observer_adapter": {
                "version": "v2",
                "terminal_request_schema": "ds02.stage2.external-solver-request.v5",
                "snapshot_binding_source": "source_provenance.root161_snapshot_proof + generated_bi4 + input_sha256",
                "terminal_request_rewritten": False,
                "native_payload_read_before_parent_guard": False,
                "consumed_v1_request_immutable": True,
            },
        }
    )
    value["resource_guard"] = dict(base.get("resource_guard", {}))
    value["resource_guard"].update(
        {
            "v2_snapshot_binding_adapter": True,
            "full_report_payload_not_reopened_by_wrapper": True,
            "solver_launch": "forbidden",
        }
    )
    value["sha256"] = _canonical(value)
    return value


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
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
    base = V1_REQUEST.self_test()
    if base.get("status") != "PASS":
        raise AssertionError(base)
    wrapper = _repo_file(WRAPPER_NAME)
    contract = _repo_file(CONTRACT_NAME)
    if wrapper.is_symlink() or contract.is_symlink():
        raise AssertionError("V2 source closure must use regular files")
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "delegated_schema": V1_REQUEST.VARIANT,
        "wrapper_bytes": wrapper.stat().st_size,
        "contract_bytes": contract.stat().st_size,
        "payload_read": False,
        "solver_started": False,
        "v8_snapshot_binding_adapter": True,
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
    parser.add_argument("--case-id", default="F3_S2_OVERLAY_NATIVE_OBSERVER_V2")
    parser.add_argument("--attempt-id", default="f3-s2-overlay-native-observer-v2-001")
    parser.add_argument("--overlay-label", default="same_cfl_baseline")
    parser.add_argument("--overlay-variable", default="none")
    parser.add_argument("--overlay-value", default="0.05/0.01")
    parser.add_argument(
        "--output",
        type=Path,
        default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-overlay-native-observer-v2.json",
    )
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if args.calibration_contract is None:
        args.calibration_contract = _repo_file("stage2_f3_s2_observer_calibration_contract_v1.json")
    required = (
        args.solver_request,
        args.terminal_receipt,
        args.terminal_proof,
        args.source_snapshot_proof,
        args.source_snapshot_report,
        args.raw_root,
        args.runparts,
        args.generated_xml,
        args.expected_frame_count,
        args.expected_final_time_s,
        args.expected_dp_m,
        args.expected_initial_fluid_count,
        args.estimated_part_bytes,
        args.estimated_native_tree_bytes,
        args.estimated_storage_bytes,
        args.launch_commit,
    )
    if any(item is None for item in required):
        parser.error("--build-request requires terminal/source paths, frame contract, byte estimates and launch commit")
    try:
        value = build(args)
        _write_once(args.output, value)
    except BaseException as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED_F3_OVERLAY_NATIVE_OBSERVER_V2_REQUEST_BUILD",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": value["status"],
                "output": str(args.output.expanduser().resolve()),
                "payload_read": "parent_after_reservation",
                "solver_started": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

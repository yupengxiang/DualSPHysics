#!/usr/bin/env python3
"""V53 command-path forward for the V52 copied-worker executor.

V52 fixed the native-module aliases, but its inherited ``execution.command``
still named ``target/runtime/executor/...``.  V41/V45 materialize every
runtime row below ``target/runtime/<target_relative_path>``, so the command
that a relocated parent records must name
``target/runtime/runtime/executor/...``.  V53 adds its own executor row and
rewrites only this derived command path.  The V52 request, source hashes,
worker-parent aliases, and UNKNOWN qualification state remain intact.

This module only reads bounded JSON/code metadata.  It does not copy or hash
raw/BI4/HDF5, typed, or result payloads, and ``run`` delegates the existing
V52 worker boundary without changing the scientific operator.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V52_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_portable_executor_v52.py"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v53-forward.v1"
V52_FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v52-forward.v1"
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class PortableV53Error(RuntimeError):
    pass


def _load_v52() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_bound_f2_executor_v52_for_v53", V52_SCRIPT)
    if spec is None or spec.loader is None:
        raise PortableV53Error(f"cannot load V52: {V52_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V52 = _load_v52()


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V52.canonical_sha(value)


def _absolute(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise PortableV53Error(f"{role} must be an absolute path")
    return Path(value).expanduser()


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _absolute(str(path), role)
    if target.is_symlink() or not target.is_file():
        raise PortableV53Error(f"{role} is not a regular non-symlink file: {target}")
    if target.stat().st_size > V52.V51.MAX_JSON_BYTES:
        raise PortableV53Error(f"{role} exceeds bounded metadata size")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableV53Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV53Error(f"{role} must be an object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = _absolute(str(path), "output")
    if target.exists() or target.is_symlink():
        raise PortableV53Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        stream.write("\n")
    return target


def _request(path: Path | str) -> tuple[Path, dict[str, Any]]:
    target, value = _json(path, "V52 executor request")
    if value.get("schema") != V34_SCHEMA or value.get("sha256") != canonical_sha(value):
        raise PortableV53Error("V52 request is not canonical V34")
    marker = value.get("forward_v52")
    if not isinstance(marker, Mapping) or marker.get("schema") != V52_FORWARD_SCHEMA:
        raise PortableV53Error("V52 forward marker is missing")
    if value.get("model_invoked") is not False or value.get("cfd_invoked") is not False:
        raise PortableV53Error("V52 request is not model-free")
    if value.get("qualification") != UNKNOWN:
        raise PortableV53Error("V52 qualification is not UNKNOWN")
    roots = value.get("fresh_roots")
    if not isinstance(roots, Mapping):
        raise PortableV53Error("V52 fresh roots are missing")
    return target, value


def _rewrite_command(command: list[Any], target: Path) -> list[str]:
    if not command or not all(isinstance(item, str) for item in command):
        raise PortableV53Error("V52 execution command is malformed")
    matches = [index for index, item in enumerate(command)
               if item.endswith("ds_data02_stage2_f2_portable_executor_v52.py")]
    if len(matches) != 1:
        raise PortableV53Error("V52 command has no unique executor-v52 operand")
    result = list(command)
    result[matches[0]] = str(
        target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v53.py"
    )
    return result


def build_forward(*, v52_request: Path | str, output_request: Path | str,
                  target_root: Path | str | None = None,
                  output_root: Path | str | None = None) -> dict[str, Any]:
    source_path, source = _request(v52_request)
    roots = source["fresh_roots"]
    target = _absolute(str(target_root or roots.get("target_root")), "target_root")
    product = _absolute(str(output_root or roots.get("output_root")), "output_root")
    if target == product:
        raise PortableV53Error("target/output roots must differ")
    old_target = roots.get("target_root")
    old_product = roots.get("output_root")
    if str(target) in {str(old_target), str(old_product)} or str(product) in {str(old_target), str(old_product)}:
        raise PortableV53Error("V53 cannot reuse V52 namespace")
    if target.exists() or product.exists():
        raise PortableV53Error("V53 target/output namespaces must be fresh")
    value = copy.deepcopy(source)
    runtime = value.get("runtime_sources")
    if not isinstance(runtime, list):
        raise PortableV53Error("V52 runtime_sources are missing")
    if any(isinstance(row, Mapping) and row.get("role") == "executor_v53" for row in runtime):
        raise PortableV53Error("V53 executor role already exists")
    info = SCRIPT.stat()
    runtime.append({
        "role": "executor_v53",
        "path": str(SCRIPT),
        "target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v53.py",
        "target_path": str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v53.py"),
        "bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "mode_bits": 0o644,
        "sha256": V52.V51.sha256_file(SCRIPT),
        "source_path_fallback": "FORBIDDEN",
        "materialization_path_policy": "V41_V45_TARGET_ROOT_RUNTIME_PREFIX",
        "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
    })
    execution = dict(value.get("execution", {}))
    execution["command"] = _rewrite_command(list(execution.get("command", [])), target)
    execution["command_materialization_policy"] = "target_root/runtime/<target_relative_path>"
    execution["executor_script_target_path"] = str(
        target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v53.py"
    )
    execution["source_path_fallback"] = "FORBIDDEN"
    value["execution"] = execution
    value["fresh_roots"] = {"target_root": str(target), "output_root": str(product)}
    value["request_id"] = str(value.get("request_id", "f2-s1-v52")) + "-v53-command-path"
    value["forward_v53"] = {
        "schema": FORWARD_SCHEMA,
        "previous_request": {
            "path": str(source_path),
            "physical_sha256": V52.V51.sha256_file(source_path, max_bytes=V52.V51.MAX_JSON_BYTES),
            "canonical_sha256": source["sha256"],
        },
        "executor_role": "executor_v53",
        "executor_target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v53.py",
        "executor_target_path": str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v53.py"),
        "command_materialization_policy": "target_root/runtime/<target_relative_path>",
        "worker_parent_relative_directory": "runtime/runtime/native",
        "source_path_fallback": "FORBIDDEN",
        "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
        "payload_read_during_build": False,
        "qualification": dict(UNKNOWN),
    }
    value["status"] = "READY_FOR_PARENT_STAGE2_GUARD"
    value["raw_opened"] = False
    value["hdf5_opened"] = False
    value["model_invoked"] = False
    value["cfd_invoked"] = False
    value["qualification"] = dict(UNKNOWN)
    value["sha256"] = canonical_sha(value)
    out = _write_new(output_request, value)
    return {
        "schema": FORWARD_SCHEMA,
        "status": value["status"],
        "request": str(out),
        "request_sha256": V52.V51.sha256_file(out, max_bytes=V52.V51.MAX_JSON_BYTES),
        "executor_target_path": str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v53.py"),
        "payload_read": False,
        "qualification": dict(UNKNOWN),
    }


def run(request_path: Path | str, *, io_slot_approved: bool,
        parent_pid: int | None = None, evaluator_proof: Path | None = None,
        max_wall_seconds: float | None = None) -> dict[str, Any]:
    """Use V52's worker boundary after validating the V53 command contract."""
    _, request = _request(request_path)
    marker = request.get("forward_v53")
    if not isinstance(marker, Mapping) or marker.get("schema") != FORWARD_SCHEMA:
        raise PortableV53Error("V53 forward marker is missing")
    return V52.run(request_path, io_slot_approved=io_slot_approved,
                   parent_pid=parent_pid, evaluator_proof=evaluator_proof,
                   max_wall_seconds=max_wall_seconds)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-forward")
    build.add_argument("--v52-request", type=Path, required=True)
    build.add_argument("--output-request", type=Path, required=True)
    build.add_argument("--target-root", type=Path)
    build.add_argument("--output-root", type=Path)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    run_parser.add_argument("--evaluator-proof", type=Path)
    run_parser.add_argument("--max-wall-seconds", type=float)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-forward":
            result = build_forward(v52_request=args.v52_request, output_request=args.output_request,
                                   target_root=args.target_root, output_root=args.output_root)
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved,
                         parent_pid=args.parent_pid, evaluator_proof=args.evaluator_proof,
                         max_wall_seconds=args.max_wall_seconds)
    except (PortableV53Error, V52.PortableV52Error, V52.V51.PortableV51Error,
            OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v53: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2, default=str))
    return 1 if str(result.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())

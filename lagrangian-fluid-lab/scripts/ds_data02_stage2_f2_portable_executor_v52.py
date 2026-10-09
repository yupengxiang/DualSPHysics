#!/usr/bin/env python3
"""V52 forward of V51 with modules co-located beside the private worker.

V38's real alias guard calls ``_materialize_aliases(bindings, worker.parent)``.
V51 corrected stale worktree paths but left the bindings in ``target/sources``;
that is still outside the copied worker directory when the worker lives under
``target/runtime/native``.  V52 keeps the V51 request and source provenance,
and adds four parent-guarded, SHA-identical module copies under
``target/runtime/native``.  The new paths are the only executable module paths;
the original and ``sources/*`` paths remain provenance/registry evidence.

This file only builds metadata and delegates a future run to V51 with its
module-plan function replaced.  It does not copy, open, or hash raw/BI4/HDF5,
typed, or result payloads.
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
V51_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_portable_executor_v51.py"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v52-forward.v1"
V51_SCHEMA = "ds02.stage2.f2-portable-executor-v51-forward.v1"
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class PortableV52Error(RuntimeError):
    pass


def _load_v51() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_bound_f2_executor_v51_for_v52", V51_SCRIPT)
    if spec is None or spec.loader is None:
        raise PortableV52Error(f"cannot load V51: {V51_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V51 = _load_v51()


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V51.canonical_sha(value)


def _absolute(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise PortableV52Error(f"{role} must be an absolute path")
    return Path(value).expanduser()


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _absolute(str(path), role)
    if target.is_symlink() or not target.is_file():
        raise PortableV52Error(f"{role} is not a regular non-symlink file: {target}")
    if target.stat().st_size > V51.MAX_JSON_BYTES:
        raise PortableV52Error(f"{role} exceeds bounded metadata size")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableV52Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV52Error(f"{role} must be an object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = _absolute(str(path), "output")
    if target.exists() or target.is_symlink():
        raise PortableV52Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        stream.write("\n")
    return target


CANONICAL_MODULE_NAMES = {
    "raw_converter": "ds_data02_f5_bi4.py",
    "v14_operator": "ds_data02_stage2_f2_replay_v14.py",
    "v15_operator": "ds_data02_stage2_f2_replay_v15.py",
    "v16_operator": "ds_data02_stage2_f2_flux_v16.py",
}


def module_rebinding_plan(request: Mapping[str, Any], target_root: Path | str) -> dict[str, dict[str, Any]]:
    """Return the V52 worker-parent bindings; no target content is opened."""
    target = _absolute(str(target_root), "target_root")
    forward = request.get("forward_v51")
    if not isinstance(forward, Mapping) or forward.get("schema") != V51_SCHEMA:
        raise PortableV52Error("V51 forward marker is missing")
    old = forward.get("module_rebinding")
    if not isinstance(old, Mapping):
        raise PortableV52Error("V51 module plan is missing")
    result: dict[str, dict[str, Any]] = {}
    for role, canonical in CANONICAL_MODULE_NAMES.items():
        row = old.get(role)
        if not isinstance(row, Mapping):
            raise PortableV52Error(f"V51 module role is missing: {role}")
        expected = row.get("expected_sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise PortableV52Error(f"V51 expected SHA is missing: {role}")
        source_relative = row.get("target_relative_path")
        if not isinstance(source_relative, str) or source_relative.startswith("/") or ".." in Path(source_relative).parts:
            raise PortableV52Error(f"V51 source target path is unsafe: {role}")
        relative = f"runtime/native/{canonical}"
        result[role] = {
            "module_role": role,
            "canonical_module": canonical,
            "source_role": row.get("source_role", role),
            "source_path_provenance": row.get("source_path_provenance"),
            "source_entry_target_relative_path": source_relative,
            "target_relative_path": relative,
            "target_path": str(target / relative),
            "expected_sha256": expected,
            "expected_bytes": row.get("expected_bytes"),
            "worker_parent": str(target / "runtime/native"),
            "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
            "source_path_fallback": "FORBIDDEN",
            "copy_reason": "V38_materialize_aliases_requires_worker_parent_co_location",
        }
    return result


def _request(path: Path | str) -> tuple[Path, dict[str, Any]]:
    target, value = _json(path, "V51 executor request")
    if value.get("schema") != V34_SCHEMA or value.get("sha256") != canonical_sha(value):
        raise PortableV52Error("V51 request is not canonical V34")
    if value.get("model_invoked") is not False or value.get("cfd_invoked") is not False:
        raise PortableV52Error("V51 request is not model-free")
    if value.get("qualification") != UNKNOWN:
        raise PortableV52Error("V51 qualification is not UNKNOWN")
    return target, value


def build_forward(*, v51_request: Path | str, output_request: Path | str,
                  target_root: Path | str | None = None,
                  output_root: Path | str | None = None) -> dict[str, Any]:
    source_path, source = _request(v51_request)
    roots = source.get("fresh_roots")
    if not isinstance(roots, Mapping):
        raise PortableV52Error("V51 fresh roots are missing")
    target = _absolute(str(target_root or roots.get("target_root")), "target_root")
    product = _absolute(str(output_root or roots.get("output_root")), "output_root")
    if target == product:
        raise PortableV52Error("target/output roots must differ")
    old_target = roots.get("target_root")
    old_product = roots.get("output_root")
    if str(target) in {str(old_target), str(old_product)} or str(product) in {str(old_target), str(old_product)}:
        raise PortableV52Error("V52 cannot reuse V51 namespace")
    plan = module_rebinding_plan(source, target)
    value = copy.deepcopy(source)
    runtime = value.get("runtime_sources")
    if not isinstance(runtime, list):
        raise PortableV52Error("V51 runtime_sources are missing")
    existing = {row.get("role") for row in runtime if isinstance(row, Mapping)}
    aliases: list[dict[str, Any]] = []
    for role, item in plan.items():
        alias_role = f"copied_module_{role}"
        if alias_role in existing:
            raise PortableV52Error(f"V52 alias role already exists: {alias_role}")
        aliases.append({
            "role": alias_role,
            "path": item["source_path_provenance"],
            "target_relative_path": item["target_relative_path"],
            "bytes": item["expected_bytes"],
            "sha256": item["expected_sha256"],
            "preserve_mode": True,
            "required_executable": False,
            "source_alias_of": role,
            "source_entry_target_relative_path": item["source_entry_target_relative_path"],
            "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
            "source_path_fallback": "FORBIDDEN",
        })
        runtime.append(aliases[-1])
    info = SCRIPT.stat()
    runtime.append({"role": "executor_v52", "path": str(SCRIPT),
                    "target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v52.py",
                    "bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
                    "mode_bits": 0o644, "sha256": V51.sha256_file(SCRIPT),
                    "source_path_fallback": "FORBIDDEN"})
    execution = dict(value.get("execution", {}))
    command = list(execution.get("command", []))
    matches = [i for i, item in enumerate(command) if isinstance(item, str) and item.endswith("ds_data02_stage2_f2_portable_executor_v51.py")]
    if len(matches) != 1:
        raise PortableV52Error("V51 command does not contain one executor_v51 operand")
    command[matches[0]] = "<target_root>/runtime/executor/ds_data02_stage2_f2_portable_executor_v52.py"
    execution["command"] = command
    execution["copied_module_directory"] = "<target_root>/runtime/native"
    execution["module_alias_policy"] = "all four V38 module bindings must be under worker.parent"
    execution["source_path_fallback"] = "FORBIDDEN"
    value["execution"] = execution
    value["fresh_roots"] = {"target_root": str(target), "output_root": str(product)}
    value["request_id"] = str(value.get("request_id", "f2-s1-v51")) + "-v52-worker-parent-modules"
    value["forward_v52"] = {
        "schema": FORWARD_SCHEMA,
        "previous_request": {"path": str(source_path), "sha256": V51.sha256_file(source_path, max_bytes=V51.MAX_JSON_BYTES),
                              "canonical_sha256": source["sha256"]},
        "module_rebinding": plan,
        "runtime_alias_roles": [item["role"] for item in aliases],
        "worker_parent_relative_directory": "runtime/native",
        "v38_alias_guard": "_materialize_aliases(bindings, worker.parent)",
        "source_path_fallback": "FORBIDDEN",
        "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
        "payload_read_during_build": False,
        "qualification": dict(UNKNOWN),
    }
    value["status"] = "READY_FOR_PARENT_STAGE2_GUARD"
    value["sha256"] = canonical_sha(value)
    out = _write_new(output_request, value)
    return {"schema": FORWARD_SCHEMA, "status": value["status"], "request": str(out),
            "request_sha256": V51.sha256_file(out, max_bytes=V51.MAX_JSON_BYTES),
            "module_roles": sorted(plan), "alias_roles": [item["role"] for item in aliases],
            "payload_read": False, "qualification": dict(UNKNOWN)}


def run(request_path: Path | str, *, io_slot_approved: bool,
        parent_pid: int | None = None, evaluator_proof: Path | None = None,
        max_wall_seconds: float | None = None) -> dict[str, Any]:
    """Delegate V51 with its module target plan redirected to worker.parent."""
    request_path, request = _request(request_path)
    target = _absolute(str(request["fresh_roots"]["target_root"]), "target_root")
    forward = request.get("forward_v52")
    if not isinstance(forward, Mapping) or forward.get("schema") != FORWARD_SCHEMA:
        raise PortableV52Error("V52 forward marker is missing")
    original = V51.module_rebinding_plan
    V51.module_rebinding_plan = module_rebinding_plan
    try:
        return V51.run(request_path, io_slot_approved=io_slot_approved,
                       parent_pid=parent_pid, evaluator_proof=evaluator_proof,
                       max_wall_seconds=max_wall_seconds)
    finally:
        V51.module_rebinding_plan = original


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-forward")
    build.add_argument("--v51-request", type=Path, required=True)
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
            result = build_forward(v51_request=args.v51_request, output_request=args.output_request,
                                   target_root=args.target_root, output_root=args.output_root)
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved,
                         parent_pid=args.parent_pid, evaluator_proof=args.evaluator_proof,
                         max_wall_seconds=args.max_wall_seconds)
    except (PortableV52Error, V51.PortableV51Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v52: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2, default=str))
    return 1 if str(result.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())

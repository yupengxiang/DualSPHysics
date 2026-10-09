#!/usr/bin/env python3
"""V54 forward for the actual V34 overlay worker directory.

V53 fixed the native-module aliases' runtime command path, but its inherited
``execution.command``
still named ``target/runtime/executor/...``.  V41/V45 materialize every
runtime row below ``target/runtime/<target_relative_path>``, so the command
that a relocated parent records must name
``target/runtime/runtime/executor/...``.  V53 adds its own executor row and
rewrites only this derived command path.  The V52 request, source hashes,
worker-parent aliases, and UNKNOWN qualification state remain intact.

The executed V34 worker is the overlay entry ``v2_worker`` under
``target/sources``.  V52 put the four V14/V15/V16/converter module copies
under ``target/runtime/runtime/native`` and V38 then rejected them because
it required module sources beside that worker.  V54 keeps those source
hashes and creates verified canonical aliases in the actual worker parent
after the parent guard reservation; it never permits a worktree fallback.

This module only reads bounded JSON/code metadata during build.  Its run
entry is for a future parent guard and is not started by this agent.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V53_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_portable_executor_v53.py"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v54-forward.v1"
V53_FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v53-forward.v1"
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class PortableV54Error(RuntimeError):
    pass


def _load_v53() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_bound_f2_executor_v53_for_v54", V53_SCRIPT)
    if spec is None or spec.loader is None:
        raise PortableV54Error(f"cannot load V53: {V53_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V53 = _load_v53()


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V53.canonical_sha(value)


def _absolute(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise PortableV54Error(f"{role} must be an absolute path")
    return Path(value).expanduser()


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _absolute(str(path), role)
    if target.is_symlink() or not target.is_file():
        raise PortableV54Error(f"{role} is not a regular non-symlink file: {target}")
    if target.stat().st_size > V53.V52.V51.MAX_JSON_BYTES:
        raise PortableV54Error(f"{role} exceeds bounded metadata size")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableV54Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV54Error(f"{role} must be an object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = _absolute(str(path), "output")
    if target.exists() or target.is_symlink():
        raise PortableV54Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        stream.write("\n")
    return target


def _request(path: Path | str) -> tuple[Path, dict[str, Any]]:
    target, value = _json(path, "V53 executor request")
    if value.get("schema") != V34_SCHEMA or value.get("sha256") != canonical_sha(value):
        raise PortableV54Error("V53 request is not canonical V34")
    marker = value.get("forward_v53")
    if not isinstance(marker, Mapping) or marker.get("schema") != V53_FORWARD_SCHEMA:
        raise PortableV54Error("V53 forward marker is missing")
    if value.get("model_invoked") is not False or value.get("cfd_invoked") is not False:
        raise PortableV54Error("V53 request is not model-free")
    if value.get("qualification") != UNKNOWN:
        raise PortableV54Error("V53 qualification is not UNKNOWN")
    roots = value.get("fresh_roots")
    if not isinstance(roots, Mapping):
        raise PortableV54Error("V53 fresh roots are missing")
    return target, value


def _rewrite_command(command: list[Any], target: Path) -> list[str]:
    if not command or not all(isinstance(item, str) for item in command):
        raise PortableV54Error("V53 execution command is malformed")
    matches = [index for index, item in enumerate(command)
               if item.endswith("ds_data02_stage2_f2_portable_executor_v52.py")]
    if not matches:
        matches = [index for index, item in enumerate(command)
                   if item.endswith("ds_data02_stage2_f2_portable_executor_v53.py")]
    if len(matches) != 1:
        raise PortableV54Error("V53 command has no unique executor-v53 operand")
    result = list(command)
    result[matches[0]] = str(
        target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v54.py"
    )
    return result


def _rewrite_delegated_evaluator(command: list[Any], target: Path) -> list[str]:
    """Keep the V34 evaluator, but bind it to this fresh copied namespace."""
    if not command or not all(isinstance(item, str) for item in command):
        raise PortableV54Error("V53 delegated evaluator command is malformed")
    matches = [index for index, item in enumerate(command)
               if item.endswith("ds_data02_stage2_f2_portable_executor_v34.py")]
    if len(matches) != 1:
        raise PortableV54Error("V53 command has no unique delegated V34 evaluator operand")
    result = list(command)
    result[matches[0]] = str(
        target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v34.py"
    )
    return result


def build_forward(*, v53_request: Path | str, output_request: Path | str,
                  target_root: Path | str | None = None,
                  output_root: Path | str | None = None) -> dict[str, Any]:
    source_path, source = _request(v53_request)
    roots = source["fresh_roots"]
    target = _absolute(str(target_root or roots.get("target_root")), "target_root")
    product = _absolute(str(output_root or roots.get("output_root")), "output_root")
    if target == product:
        raise PortableV54Error("target/output roots must differ")
    old_target = roots.get("target_root")
    old_product = roots.get("output_root")
    if str(target) in {str(old_target), str(old_product)} or str(product) in {str(old_target), str(old_product)}:
        raise PortableV54Error("V54 cannot reuse V53 namespace")
    if target.exists() or product.exists():
        raise PortableV54Error("V54 target/output namespaces must be fresh")
    value = copy.deepcopy(source)
    runtime = value.get("runtime_sources")
    if not isinstance(runtime, list):
        raise PortableV54Error("V53 runtime_sources are missing")
    if any(isinstance(row, Mapping) and row.get("role") == "executor_v54" for row in runtime):
        raise PortableV54Error("V54 executor role already exists")
    info = SCRIPT.stat()
    runtime.append({
        "role": "executor_v54",
        "path": str(SCRIPT),
        "target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v54.py",
        "target_path": str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v54.py"),
        "bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "mode_bits": 0o644,
        "sha256": V53.V52.V51.sha256_file(SCRIPT),
        "source_path_fallback": "FORBIDDEN",
        "materialization_path_policy": "V41_V45_TARGET_ROOT_RUNTIME_PREFIX",
        "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
    })
    execution = dict(value.get("execution", {}))
    execution["command"] = _rewrite_command(list(execution.get("command", [])), target)
    execution["evaluator_command"] = _rewrite_delegated_evaluator(
        list(execution.get("evaluator_command", [])), target)
    execution["command_materialization_policy"] = "target_root/runtime/<target_relative_path>"
    execution["executor_script_target_path"] = str(
        target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v54.py"
    )
    execution["worker_parent_relative_directory"] = "sources"
    execution["evaluator_executor_role"] = "executor_v34"
    execution["evaluator_command_scope"] = (
        "delegated V34 evaluator in the same fresh target; it runs only after the V54 "
        "worker stage and never falls back to the ROOT140 target")
    execution["module_alias_policy"] = (
        "four V52 module bindings are copied under runtime/runtime/native and "
        "verified into the actual overlay v2_worker.parent under sources")
    execution["source_path_fallback"] = "FORBIDDEN"
    value["execution"] = execution
    value["fresh_roots"] = {"target_root": str(target), "output_root": str(product)}
    value["request_id"] = str(value.get("request_id", "f2-s1-v53")) + "-v54-worker-parent"
    value["forward_v54"] = {
        "schema": FORWARD_SCHEMA,
        "previous_request": {
            "path": str(source_path),
            "physical_sha256": V53.V52.V51.sha256_file(source_path, max_bytes=V53.V52.V51.MAX_JSON_BYTES),
            "canonical_sha256": source["sha256"],
        },
        "executor_role": "executor_v54",
        "executor_target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v54.py",
        "executor_target_path": str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v54.py"),
        "command_materialization_policy": "target_root/runtime/<target_relative_path>",
        "worker_parent_relative_directory": "sources",
        "worker_role": "v2_worker",
        "worker_parent_is_overlay_entry_parent": True,
        "module_binding_roles": ["raw_converter", "v14_operator", "v15_operator", "v16_operator"],
        "module_source_scope": "copied target runtime/runtime/native only",
        "alias_scope": "actual copied v2_worker.parent only",
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
        "request_sha256": V53.V52.V51.sha256_file(out, max_bytes=V53.V52.V51.MAX_JSON_BYTES),
        "executor_target_path": str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v54.py"),
        "payload_read": False,
        "qualification": dict(UNKNOWN),
    }


MODULE_NAMES = {
    "raw_converter": "ds_data02_f5_bi4.py",
    "v14_operator": "ds_data02_stage2_f2_replay_v14.py",
    "v15_operator": "ds_data02_stage2_f2_replay_v15.py",
    "v16_operator": "ds_data02_stage2_f2_flux_v16.py",
}


def _require_copy_path(value: Any, role: str) -> Path:
    path = Path(str(value)).expanduser()
    if path.is_symlink() or not path.is_file():
        raise PortableV54Error(f"{role} is not a copied regular file: {path}")
    return path


def _materialize_aliases_in_worker_parent(bindings: Mapping[str, Mapping[str, Any]],
                                          worker_dir: Path | str) -> list[dict[str, Any]]:
    """Copy all four verified module bindings beside the actual V34 worker.

    ``worker_dir`` is the parent of the overlay ``v2_worker`` entry.  Source
    files must already be inside that same copied bundle (normally
    ``bundle-target/runtime/runtime/native``); an original worktree path is
    rejected before any alias is created.
    """
    target_dir = Path(worker_dir).expanduser().resolve()
    if not target_dir.is_dir():
        raise PortableV54Error(f"actual copied worker parent is missing: {target_dir}")
    bundle_root = target_dir.parent
    records: list[dict[str, Any]] = []
    for role, canonical in MODULE_NAMES.items():
        item = bindings.get(role)
        if not isinstance(item, Mapping):
            raise PortableV54Error(f"copied module binding is missing: {role}")
        source = _require_copy_path(item.get("path"), role)
        try:
            source.relative_to(bundle_root)
        except ValueError as error:
            raise PortableV54Error(
                f"module {role} is outside the copied bundle: {source}") from error
        expected = item.get("sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise PortableV54Error(f"module {role} SHA is missing")
        actual = V53.V52.V51.sha256_file(source)
        if actual != expected:
            raise PortableV54Error(f"copied module SHA differs: {role}")
        alias = target_dir / canonical
        state = "EXISTING_VERIFIED_ALIAS"
        if alias.exists() or alias.is_symlink():
            if alias.is_symlink() or not alias.is_file() \
                    or V53.V52.V51.sha256_file(alias) != expected:
                raise PortableV54Error(f"existing worker-parent alias differs: {alias}")
        else:
            shutil.copyfile(source, alias)
            os.chmod(alias, stat.S_IMODE(source.stat().st_mode))
            state = "CREATED_FROM_COPIED_RUNTIME_SOURCE"
        alias_stat = alias.stat()
        if alias_stat.st_size != int(item.get("bytes", alias_stat.st_size)) \
                or V53.V52.V51.sha256_file(alias) != expected:
            raise PortableV54Error(f"worker-parent alias content differs: {alias}")
        records.append({
            "role": role,
            "canonical_module": canonical,
            "copied_source_path": str(source),
            "alias_path": str(alias),
            "sha256": expected,
            "bytes": int(alias_stat.st_size),
            "mode_bits": int(stat.S_IMODE(alias_stat.st_mode)),
            "inode_distinct": bool(alias.resolve() != source.resolve()),
            "state": state,
            "worker_parent": str(target_dir),
            "source_fallback": "FORBIDDEN",
        })
    return records


def _import_four_modules(python: Path | str,
                         records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Import the three operators while also sealing the converter alias."""
    if {row.get("role") for row in records} != set(MODULE_NAMES):
        raise PortableV54Error("V54 requires all four copied module aliases")
    # The pinned venv argv0 is intentionally a symlink; resolving it would
    # select the ABI-incompatible system interpreter.  Source aliases above
    # remain strict non-symlink copied files.
    python_path = Path(python).expanduser()
    if not python_path.is_file():
        raise PortableV54Error(f"bound venv Python is missing: {python_path}")
    with tempfile.TemporaryDirectory(prefix="ds02-v54-import-") as temporary:
        root = Path(temporary)
        for item in records:
            source = _require_copy_path(item.get("alias_path"), str(item.get("role")))
            target = root / str(item["canonical_module"])
            shutil.copyfile(source, target)
            os.chmod(target, stat.S_IMODE(source.stat().st_mode))
            if V53.V52.V51.sha256_file(target) != item.get("sha256"):
                raise PortableV54Error(f"temporary import source SHA differs: {item.get('role')}")
        code = r'''
import importlib.util, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("no loader for " + str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
converter = load(root / "ds_data02_f5_bi4.py", "ds_data02_f5_bi4")
v14 = load(root / "ds_data02_stage2_f2_replay_v14.py", "ds_data02_stage2_f2_replay_v14")
v15 = load(root / "ds_data02_stage2_f2_replay_v15.py", "ds_data02_stage2_f2_replay_v15")
v16 = load(root / "ds_data02_stage2_f2_flux_v16.py", "ds_data02_stage2_f2_flux_v16")
print(json.dumps({"raw_converter": str(pathlib.Path(converter.__file__).resolve()),
                  "v14": str(pathlib.Path(v14.__file__).resolve()),
                  "v15": str(pathlib.Path(v15.__file__).resolve()),
                  "v16": str(pathlib.Path(v16.__file__).resolve()),
                  "sys_path0": str(root)}, sort_keys=True))
'''
        env = {key: value for key, value in os.environ.items()
               if key not in {"PYTHONPATH", "PYTHONHOME"}}
        proc = __import__("subprocess").run(
            [str(python_path), "-B", "-I", "-c", code, str(root)],
            capture_output=True, text=True, check=False, env=env)
        if proc.returncode != 0:
            raise PortableV54Error(f"four-module ABI smoke failed: {proc.stderr[-1000:]}")
        try:
            result = json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as error:
            raise PortableV54Error("four-module ABI smoke returned no JSON") from error
        result["aliases"] = [dict(row) for row in records]
        result["all_four_modules_colocated"] = True
        return result


def _run_v51_with_worker_parent_aliases(request_path: Path | str, *, io_slot_approved: bool,
                                        parent_pid: int | None,
                                        evaluator_proof: Path | None,
                                        max_wall_seconds: float | None) -> dict[str, Any]:
    """V51 run graph with V54's actual overlay-worker alias hook."""
    v51 = V53.V52.V51
    request_path, outer = v51._request(request_path)
    target_root = v51._absolute(str(outer["fresh_roots"]["target_root"]), "target_root")
    v45 = v51._load_v45()
    original_bindings = v45.V41.V38._module_bindings
    original_aliases = v45.V41.V38._materialize_aliases
    original_import = v45.V41.V38._import_subprocess
    original_make = v45.V41._make_v40_engine_inputs

    def rebound(base_request: Path | str) -> dict[str, dict[str, Any]]:
        return v51._target_module_bindings(outer, Path(base_request), target_root)

    def make_inputs(request_value: Mapping[str, Any], output: Path, base_path: Path) -> dict[str, Any]:
        state = original_make(request_value, output, base_path)
        v51._rebind_written_base(v45, outer, Path(state["base"]), target_root)
        return state

    v45.V41.V38._module_bindings = rebound
    v45.V41.V38._materialize_aliases = _materialize_aliases_in_worker_parent
    v45.V41.V38._import_subprocess = _import_four_modules
    v45.V41._make_v40_engine_inputs = make_inputs
    try:
        return v45.run(request_path, io_slot_approved=io_slot_approved,
                       parent_pid=parent_pid, evaluator_proof=evaluator_proof,
                       max_wall_seconds=max_wall_seconds)
    finally:
        v45.V41.V38._module_bindings = original_bindings
        v45.V41.V38._materialize_aliases = original_aliases
        v45.V41.V38._import_subprocess = original_import
        v45.V41._make_v40_engine_inputs = original_make


def run(request_path: Path | str, *, io_slot_approved: bool,
        parent_pid: int | None = None, evaluator_proof: Path | None = None,
        max_wall_seconds: float | None = None) -> dict[str, Any]:
    """Use the V53 chain with actual overlay-worker module co-location."""
    _, request = _request(request_path)
    marker = request.get("forward_v54")
    if not isinstance(marker, Mapping) or marker.get("schema") != FORWARD_SCHEMA:
        raise PortableV54Error("V54 forward marker is missing")
    v52 = V53.V52
    original = v52.V51.run
    v52.V51.run = _run_v51_with_worker_parent_aliases
    try:
        return V53.run(request_path, io_slot_approved=io_slot_approved,
                       parent_pid=parent_pid, evaluator_proof=evaluator_proof,
                       max_wall_seconds=max_wall_seconds)
    finally:
        v52.V51.run = original


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-forward")
    build.add_argument("--v53-request", type=Path, required=True)
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
            result = build_forward(v53_request=args.v53_request, output_request=args.output_request,
                                   target_root=args.target_root, output_root=args.output_root)
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved,
                         parent_pid=args.parent_pid, evaluator_proof=args.evaluator_proof,
                         max_wall_seconds=args.max_wall_seconds)
    except (PortableV54Error, V53.PortableV53Error, V53.V52.PortableV52Error,
            V53.V52.V51.PortableV51Error,
            OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v54: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2, default=str))
    return 1 if str(result.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())

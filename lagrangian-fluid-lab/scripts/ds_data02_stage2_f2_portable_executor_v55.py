#!/usr/bin/env python3
"""V55 forward for the actual V34 overlay worker directory.

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
it required module sources beside that worker.  V55 keeps those source
hashes and creates verified canonical aliases in the actual worker parent
after the parent guard reservation; it checks device/inode identity and
mode bits, and never permits a worktree fallback.  Its private import smoke
has a finite timeout and uses scratch below the owned target root.

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
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V54_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_portable_executor_v54.py"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v55-forward.v1"
V54_FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v54-forward.v1"
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
IMPORT_TIMEOUT_SECONDS = 60.0


class PortableV55Error(RuntimeError):
    pass


def _load_v54() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_bound_f2_executor_v54_for_v55", V54_SCRIPT)
    if spec is None or spec.loader is None:
        raise PortableV55Error(f"cannot load V54: {V54_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V54 = _load_v54()
CORE = V54.V53.V52.V51
MODULE_NAMES = dict(V54.MODULE_NAMES)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V54.canonical_sha(value)


def _absolute(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise PortableV55Error(f"{role} must be an absolute path")
    return Path(value).expanduser()


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _absolute(str(path), role)
    if target.is_symlink() or not target.is_file():
        raise PortableV55Error(f"{role} is not a regular non-symlink file: {target}")
    if target.stat().st_size > CORE.MAX_JSON_BYTES:
        raise PortableV55Error(f"{role} exceeds bounded metadata size")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableV55Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV55Error(f"{role} must be an object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = _absolute(str(path), "output")
    if target.exists() or target.is_symlink():
        raise PortableV55Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        stream.write("\n")
    return target


def _request(path: Path | str) -> tuple[Path, dict[str, Any]]:
    target, value = _json(path, "V54 executor request")
    if value.get("schema") != V34_SCHEMA or value.get("sha256") != canonical_sha(value):
        raise PortableV55Error("V54 request is not canonical V34")
    marker = value.get("forward_v54")
    if not isinstance(marker, Mapping) or marker.get("schema") != V54_FORWARD_SCHEMA:
        raise PortableV55Error("V54 forward marker is missing")
    if value.get("model_invoked") is not False or value.get("cfd_invoked") is not False:
        raise PortableV55Error("V54 request is not model-free")
    if value.get("qualification") != UNKNOWN:
        raise PortableV55Error("V54 qualification is not UNKNOWN")
    roots = value.get("fresh_roots")
    if not isinstance(roots, Mapping):
        raise PortableV55Error("V54 fresh roots are missing")
    return target, value


def _rewrite_command(command: list[Any], target: Path) -> list[str]:
    if not command or not all(isinstance(item, str) for item in command):
        raise PortableV55Error("V54 execution command is malformed")
    matches = [index for index, item in enumerate(command)
               if item.endswith("ds_data02_stage2_f2_portable_executor_v54.py")]
    if len(matches) != 1:
        raise PortableV55Error("V54 command has no unique executor-v54 operand")
    result = list(command)
    result[matches[0]] = str(
        target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v55.py"
    )
    return result


def _rewrite_delegated_evaluator(command: list[Any], target: Path) -> list[str]:
    """Keep the V34 evaluator, but bind it to this fresh copied namespace."""
    if not command or not all(isinstance(item, str) for item in command):
        raise PortableV55Error("V54 delegated evaluator command is malformed")
    matches = [index for index, item in enumerate(command)
               if item.endswith("ds_data02_stage2_f2_portable_executor_v34.py")]
    if len(matches) != 1:
        raise PortableV55Error("V54 command has no unique delegated V34 evaluator operand")
    result = list(command)
    result[matches[0]] = str(
        target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v34.py"
    )
    return result


def _rebase_derived_paths(value: Any, *, old_target: str, old_product: str,
                           target: str, product: str, key: str = "") -> Any:
    """Rebase derived target/output paths while retaining provenance paths."""
    if key in {"forward_v51", "forward_v52", "forward_v53", "forward_v54",
               "forward_root140_binding", "previous_request"}:
        return value
    if isinstance(value, dict):
        return {
            name: _rebase_derived_paths(item, old_target=old_target,
                                        old_product=old_product, target=target,
                                        product=product, key=name)
            for name, item in value.items()
        }
    if isinstance(value, list):
        return [_rebase_derived_paths(item, old_target=old_target,
                                      old_product=old_product, target=target,
                                      product=product, key=key) for item in value]
    if not isinstance(value, str):
        return value
    # Explicit source/provenance paths identify the historical bytes and must
    # remain unchanged.  Target paths, commands, and runtime/storage roots are
    # actionable paths and must follow this fresh namespace.
    if key in {"path", "source_path_provenance", "resolved_source_path",
               "prior_builder_target_path"}:
        return value
    if value.startswith(old_target):
        return target + value[len(old_target):]
    if value.startswith(old_product):
        return product + value[len(old_product):]
    return value


def build_forward(*, v54_request: Path | str, output_request: Path | str,
                  target_root: Path | str | None = None,
                  output_root: Path | str | None = None) -> dict[str, Any]:
    source_path, source = _request(v54_request)
    roots = source["fresh_roots"]
    target = _absolute(str(target_root or roots.get("target_root")), "target_root")
    product = _absolute(str(output_root or roots.get("output_root")), "output_root")
    if target == product:
        raise PortableV55Error("target/output roots must differ")
    old_target = roots.get("target_root")
    old_product = roots.get("output_root")
    if str(target) in {str(old_target), str(old_product)} or str(product) in {str(old_target), str(old_product)}:
        raise PortableV55Error("V55 cannot reuse V54 namespace")
    if target.exists() or product.exists():
        raise PortableV55Error("V55 target/output namespaces must be fresh")
    value = copy.deepcopy(source)
    old_target_str = str(roots.get("target_root"))
    old_product_str = str(roots.get("output_root"))
    value = _rebase_derived_paths(value, old_target=old_target_str,
                                   old_product=old_product_str,
                                   target=str(target), product=str(product))
    runtime = value.get("runtime_sources")
    if not isinstance(runtime, list):
        raise PortableV55Error("V54 runtime_sources are missing")
    if any(isinstance(row, Mapping) and row.get("role") == "executor_v55" for row in runtime):
        raise PortableV55Error("V55 executor role already exists")
    # Earlier forwards carried target_path values from several historical
    # namespaces (V53 and V54B).  Recompute every actionable runtime target
    # from its immutable relative role; historical forward_* provenance stays
    # untouched by _rebase_derived_paths above.
    for row in runtime:
        if isinstance(row, dict) and isinstance(row.get("target_relative_path"), str):
            row["target_path"] = str(target / "runtime" / row["target_relative_path"])
    info = SCRIPT.stat()
    runtime.append({
        "role": "executor_v55",
        "path": str(SCRIPT),
        "target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v55.py",
        "target_path": str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v55.py"),
        "bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "mode_bits": 0o644,
        "sha256": CORE.sha256_file(SCRIPT),
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
        target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v55.py"
    )
    execution["runtime_target_root"] = str(target / "runtime")
    execution["worker_parent_relative_directory"] = "sources"
    execution["evaluator_executor_role"] = "executor_v34"
    execution["evaluator_command_scope"] = (
        "delegated V34 evaluator in the same fresh target; it runs only after the V54 "
        "worker stage and never falls back to the ROOT140 target")
    execution["module_alias_policy"] = (
        "four V54 module bindings are copied under runtime/runtime/native and "
        "verified by st_dev/st_ino and mode before aliasing into v2_worker.parent")
    execution["private_import_timeout_seconds"] = IMPORT_TIMEOUT_SECONDS
    execution["private_import_scratch_policy"] = "owned target_root scratch only"
    execution["source_path_fallback"] = "FORBIDDEN"
    value["execution"] = execution
    value["fresh_roots"] = {"target_root": str(target), "output_root": str(product)}
    new_attempt = "f2-s1-root145-v55-parent-20261009-001"
    parent_resource = value.get("parent_resource_binding")
    if isinstance(parent_resource, dict):
        parent_resource["attempt_id"] = new_attempt
        parent_resource["reservation_id"] = new_attempt + "::v55-reservation"
        parent_resource["supplemental_charge_id"] = new_attempt + "::v55-charge"
    storage_scope = value.get("storage_scope")
    if isinstance(storage_scope, dict):
        storage_scope["parent_attempt_id"] = new_attempt
        storage_scope["external_output_root"] = str(product)
        storage_scope["supervisor_output_root"] = str(product.parent / "supervisor")
    value["request_id"] = str(value.get("request_id", "f2-s1-v54")) + "-v55-inode-timeout"
    value["forward_v55"] = {
        "schema": FORWARD_SCHEMA,
        "previous_request": {
            "path": str(source_path),
            "physical_sha256": CORE.sha256_file(source_path, max_bytes=CORE.MAX_JSON_BYTES),
            "canonical_sha256": source["sha256"],
        },
        "executor_role": "executor_v55",
        "executor_target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v55.py",
        "executor_target_path": str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v55.py"),
        "command_materialization_policy": "target_root/runtime/<target_relative_path>",
        "worker_parent_relative_directory": "sources",
        "worker_role": "v2_worker",
        "worker_parent_is_overlay_entry_parent": True,
        "module_binding_roles": ["raw_converter", "v14_operator", "v15_operator", "v16_operator"],
        "module_source_scope": "copied target runtime/runtime/native only",
        "alias_identity_check": "st_dev_and_st_ino_must_differ_from_copied_source",
        "mode_check": "alias_mode_bits_must_equal_copied_source_mode_bits",
        "private_import_timeout_seconds": IMPORT_TIMEOUT_SECONDS,
        "private_import_scratch_policy": "target_root_owned_scratch; host /tmp forbidden",
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
        "request_sha256": CORE.sha256_file(out, max_bytes=CORE.MAX_JSON_BYTES),
        "executor_target_path": str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v55.py"),
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
        raise PortableV55Error(f"{role} is not a copied regular file: {path}")
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
        raise PortableV55Error(f"actual copied worker parent is missing: {target_dir}")
    bundle_root = target_dir.parent
    records: list[dict[str, Any]] = []
    for role, canonical in MODULE_NAMES.items():
        item = bindings.get(role)
        if not isinstance(item, Mapping):
            raise PortableV55Error(f"copied module binding is missing: {role}")
        source = _require_copy_path(item.get("path"), role)
        try:
            source.relative_to(bundle_root)
        except ValueError as error:
            raise PortableV55Error(
                f"module {role} is outside the copied bundle: {source}") from error
        expected = item.get("sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise PortableV55Error(f"module {role} SHA is missing")
        source_stat = source.stat(follow_symlinks=False)
        source_mode = stat.S_IMODE(source_stat.st_mode)
        expected_mode = item.get("mode_bits")
        if expected_mode is not None and int(expected_mode) != source_mode:
            raise PortableV55Error(f"copied module mode differs from binding: {role}")
        actual = CORE.sha256_file(source)
        if actual != expected:
            raise PortableV55Error(f"copied module SHA differs: {role}")
        alias = target_dir / canonical
        state = "EXISTING_VERIFIED_ALIAS"
        if alias.exists() or alias.is_symlink():
            if alias.is_symlink() or not alias.is_file() \
                    or CORE.sha256_file(alias) != expected:
                raise PortableV55Error(f"existing worker-parent alias differs: {alias}")
        else:
            shutil.copyfile(source, alias)
            os.chmod(alias, source_mode)
            state = "CREATED_FROM_COPIED_RUNTIME_SOURCE"
        alias_stat = alias.stat(follow_symlinks=False)
        alias_mode = stat.S_IMODE(alias_stat.st_mode)
        if (alias_stat.st_dev, alias_stat.st_ino) == (source_stat.st_dev, source_stat.st_ino):
            raise PortableV55Error(f"worker-parent alias shares source inode: {alias}")
        if alias_mode != source_mode:
            raise PortableV55Error(f"worker-parent alias mode differs: {alias}")
        if alias_stat.st_size != int(item.get("bytes", alias_stat.st_size)) \
                or CORE.sha256_file(alias) != expected:
            raise PortableV55Error(f"worker-parent alias content differs: {alias}")
        records.append({
            "role": role,
            "canonical_module": canonical,
            "copied_source_path": str(source),
            "alias_path": str(alias),
            "sha256": expected,
            "bytes": int(alias_stat.st_size),
            "source_mode_bits": source_mode,
            "alias_mode_bits": alias_mode,
            "source_st_dev": int(source_stat.st_dev),
            "source_st_ino": int(source_stat.st_ino),
            "alias_st_dev": int(alias_stat.st_dev),
            "alias_st_ino": int(alias_stat.st_ino),
            "inode_distinct": True,
            "state": state,
            "worker_parent": str(target_dir),
            "source_fallback": "FORBIDDEN",
        })
    return records


def _import_four_modules(python: Path | str,
                         records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Import the four aliases in owned scratch with a finite timeout."""
    if {row.get("role") for row in records} != set(MODULE_NAMES):
        raise PortableV55Error("V55 requires all four copied module aliases")
    # The pinned venv argv0 is intentionally a symlink; resolving it would
    # select the ABI-incompatible system interpreter.  Source aliases above
    # remain strict non-symlink copied files.
    python_path = Path(python).expanduser()
    if not python_path.is_file():
        raise PortableV55Error(f"bound venv Python is missing: {python_path}")
    if not records or not isinstance(records[0].get("worker_parent"), str):
        raise PortableV55Error("worker-parent scratch root is missing")
    bundle_root = Path(str(records[0]["worker_parent"])).expanduser().resolve().parent
    scratch_root = bundle_root / "scratch-v55-import"
    if not str(scratch_root).startswith(str(bundle_root) + os.sep):
        raise PortableV55Error("private import scratch escapes target root")
    if scratch_root.exists() and scratch_root.is_symlink():
        raise PortableV55Error("private import scratch is a symlink")
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ds02-v55-import-", dir=str(scratch_root)) as temporary:
        root = Path(temporary)
        for item in records:
            source = _require_copy_path(item.get("alias_path"), str(item.get("role")))
            target = root / str(item["canonical_module"])
            shutil.copyfile(source, target)
            os.chmod(target, stat.S_IMODE(source.stat().st_mode))
            if CORE.sha256_file(target) != item.get("sha256"):
                raise PortableV55Error(f"temporary import source SHA differs: {item.get('role')}")
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
        try:
            proc = subprocess.run(
                [str(python_path), "-B", "-I", "-c", code, str(root)],
                capture_output=True, text=True, check=False, env=env,
                timeout=IMPORT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise PortableV55Error(
                f"four-module ABI smoke timed out after {IMPORT_TIMEOUT_SECONDS}s") from error
        if proc.returncode != 0:
            raise PortableV55Error(f"four-module ABI smoke failed: {proc.stderr[-1000:]}")
        try:
            result = json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as error:
            raise PortableV55Error("four-module ABI smoke returned no JSON") from error
        result["aliases"] = [dict(row) for row in records]
        result["all_four_modules_colocated"] = True
        result["scratch_root"] = str(scratch_root)
        result["timeout_seconds"] = IMPORT_TIMEOUT_SECONDS
        return result


def _run_v51_with_worker_parent_aliases(request_path: Path | str, *, io_slot_approved: bool,
                                        parent_pid: int | None,
                                        evaluator_proof: Path | None,
                                        max_wall_seconds: float | None) -> dict[str, Any]:
    """V51 run graph with V54's actual overlay-worker alias hook."""
    v51 = CORE
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
    """Use V54's chain with strict actual overlay-worker module co-location."""
    _, request = _request(request_path)
    marker = request.get("forward_v55")
    if not isinstance(marker, Mapping) or marker.get("schema") != FORWARD_SCHEMA:
        raise PortableV55Error("V55 forward marker is missing")
    original_aliases = V54._materialize_aliases_in_worker_parent
    original_import = V54._import_four_modules
    V54._materialize_aliases_in_worker_parent = _materialize_aliases_in_worker_parent
    V54._import_four_modules = _import_four_modules
    try:
        return V54.run(request_path, io_slot_approved=io_slot_approved,
                       parent_pid=parent_pid, evaluator_proof=evaluator_proof,
                       max_wall_seconds=max_wall_seconds)
    finally:
        V54._materialize_aliases_in_worker_parent = original_aliases
        V54._import_four_modules = original_import


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-forward")
    build.add_argument("--v54-request", type=Path, required=True)
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
            result = build_forward(v54_request=args.v54_request, output_request=args.output_request,
                                   target_root=args.target_root, output_root=args.output_root)
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved,
                         parent_pid=args.parent_pid, evaluator_proof=args.evaluator_proof,
                         max_wall_seconds=args.max_wall_seconds)
    except (PortableV55Error, V54.PortableV54Error, V54.V53.PortableV53Error,
            V54.V53.V52.PortableV52Error, V54.V53.V52.V51.PortableV51Error,
            OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v55: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2, default=str))
    return 1 if str(result.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())

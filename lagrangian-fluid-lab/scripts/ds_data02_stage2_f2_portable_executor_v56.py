#!/usr/bin/env python3
"""V56 compatibility bridge for the ROOT145 copied V4 worker.

The immutable V4 wrapper is copied as the overlay ``v2_worker`` under
``target/sources``.  Its ``_worker_path`` contract looks for the plain V2
worker at ``target/runtime/native/<WORKER_NAME>``.  V55 materialized that
plain worker only at the runtime registry path
``target/runtime/runtime/native``.  V56 creates a verified, distinct-inode
copy at the path the wrapper actually consumes, then imports the wrapper and
worker in the pinned interpreter before the scientific child starts.

This module only performs code/metadata checks.  The parent guard still owns
reservation, payload hashing, ledger accounting, and the scientific child.
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
from typing import Any, Mapping, Sequence

SCRIPT = Path(__file__).resolve()
V55_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_portable_executor_v55.py"
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
V55_SCHEMA = "ds02.stage2.f2-portable-executor-v55-forward.v1"
V56_SCHEMA = "ds02.stage2.f2-portable-executor-v56-forward.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
WORKER_NAME = "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
IMPORT_TIMEOUT_SECONDS = 60.0


class PortableV56Error(RuntimeError):
    pass


def _load_v55() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_v55_for_v56", V55_SCRIPT)
    if spec is None or spec.loader is None:
        raise PortableV56Error(f"cannot load V55: {V55_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V55 = _load_v55()
CORE = V55.CORE


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V55.canonical_sha(value)


def _absolute(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise PortableV56Error(f"{role} must be an absolute path")
    return Path(value).expanduser()


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _absolute(str(path), role)
    if target.is_symlink() or not target.is_file():
        raise PortableV56Error(f"{role} is not a regular non-symlink file: {target}")
    if target.stat().st_size > CORE.MAX_JSON_BYTES:
        raise PortableV56Error(f"{role} exceeds bounded metadata size")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableV56Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV56Error(f"{role} must be an object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = _absolute(str(path), "output")
    if target.exists() or target.is_symlink():
        raise PortableV56Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        stream.write("\n")
    return target


def _request_v55(path: Path | str) -> tuple[Path, dict[str, Any]]:
    target, value = _json(path, "V55 executor request")
    if value.get("schema") != V34_SCHEMA or value.get("sha256") != canonical_sha(value):
        raise PortableV56Error("V55 request is not canonical V34")
    marker = value.get("forward_v55")
    if not isinstance(marker, Mapping) or marker.get("schema") != V55_SCHEMA:
        raise PortableV56Error("V55 forward marker is missing")
    if value.get("model_invoked") is not False or value.get("cfd_invoked") is not False:
        raise PortableV56Error("V55 request is not model-free")
    if value.get("qualification") != UNKNOWN:
        raise PortableV56Error("V55 qualification is not UNKNOWN")
    if not isinstance(value.get("fresh_roots"), Mapping):
        raise PortableV56Error("V55 fresh roots are missing")
    return target, value


def _rebase(value: Any, *, old_target: str, old_product: str,
            target: str, product: str, key: str = "") -> Any:
    if key in {"forward_v51", "forward_v52", "forward_v53", "forward_v54",
               "forward_v55", "forward_root140_binding", "previous_request"}:
        return value
    if isinstance(value, dict):
        return {name: _rebase(item, old_target=old_target, old_product=old_product,
                              target=target, product=product, key=name)
                for name, item in value.items()}
    if isinstance(value, list):
        return [_rebase(item, old_target=old_target, old_product=old_product,
                        target=target, product=product, key=key) for item in value]
    if not isinstance(value, str):
        return value
    if key in {"path", "source_path_provenance", "resolved_source_path", "prior_builder_target_path"}:
        return value
    if value.startswith(old_target):
        return target + value[len(old_target):]
    if value.startswith(old_product):
        return product + value[len(old_product):]
    return value


def _rewrite_command(command: Any, target: Path) -> list[str]:
    if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
        raise PortableV56Error("V55 execution command is malformed")
    positions = [i for i, item in enumerate(command)
                 if item.endswith("ds_data02_stage2_f2_portable_executor_v55.py")]
    if len(positions) != 1:
        raise PortableV56Error("V55 command has no unique executor-v55 operand")
    result = list(command)
    result[positions[0]] = str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v56.py")
    return result


def build_forward(*, v55_request: Path | str, output_request: Path | str,
                  target_root: Path | str | None = None,
                  output_root: Path | str | None = None) -> dict[str, Any]:
    source_path, source = _request_v55(v55_request)
    roots = source["fresh_roots"]
    target = _absolute(str(target_root or roots.get("target_root")), "target_root")
    product = _absolute(str(output_root or roots.get("output_root")), "output_root")
    old_target, old_product = str(roots["target_root"]), str(roots["output_root"])
    if target == product or str(target) in {old_target, old_product} or str(product) in {old_target, old_product}:
        raise PortableV56Error("V56 target/output roots must be distinct from V55")
    if target.exists() or product.exists():
        raise PortableV56Error("V56 target/output namespaces must be fresh")
    value = _rebase(copy.deepcopy(source), old_target=old_target, old_product=old_product,
                    target=str(target), product=str(product))
    runtime = value.get("runtime_sources")
    if not isinstance(runtime, list):
        raise PortableV56Error("V55 runtime_sources are missing")
    if any(isinstance(row, Mapping) and row.get("role") == "executor_v56" for row in runtime):
        raise PortableV56Error("V56 executor role already exists")
    for row in runtime:
        if isinstance(row, dict) and isinstance(row.get("target_relative_path"), str):
            row["target_path"] = str(target / "runtime" / row["target_relative_path"])
    info = SCRIPT.stat()
    runtime.append({
        "role": "executor_v56", "path": str(SCRIPT),
        "target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v56.py",
        "target_path": str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v56.py"),
        "bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns), "mode_bits": 0o644,
        "sha256": CORE.sha256_file(SCRIPT), "source_path_fallback": "FORBIDDEN",
        "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
    })
    execution = dict(value.get("execution", {}))
    execution["command"] = _rewrite_command(execution.get("command"), target)
    execution["executor_script_target_path"] = str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v56.py")
    execution["runtime_target_root"] = str(target / "runtime")
    execution["worker_compatibility_target_relative_path"] = "runtime/native/" + WORKER_NAME
    execution["worker_compatibility_source_role"] = "raw_worker_v2"
    execution["worker_compatibility_source_scope"] = "copied target runtime/runtime/native only"
    execution["worker_path_smoke_timeout_seconds"] = IMPORT_TIMEOUT_SECONDS
    execution["worker_compatibility_invariants"] = {
        "source_path_fallback": "FORBIDDEN", "target_must_be_regular_non_symlink": True,
        "inode_distinct": True, "mode_preserved": True, "content_sha_preserved": True,
    }
    value["execution"] = execution
    value["fresh_roots"] = {"target_root": str(target), "output_root": str(product)}
    attempt = "f2-s1-root145-v56-parent-20261009-001"
    if isinstance(value.get("parent_resource_binding"), dict):
        value["parent_resource_binding"].update({
            "attempt_id": attempt, "reservation_id": attempt + "::v56-reservation",
            "supplemental_charge_id": attempt + "::v56-charge"})
    if isinstance(value.get("storage_scope"), dict):
        value["storage_scope"].update({"parent_attempt_id": attempt,
            "external_output_root": str(product), "supervisor_output_root": str(product.parent / "supervisor")})
    value["request_id"] = str(value.get("request_id", "f2-s1-v55")) + "-v56-worker-compatibility"
    value["forward_v56"] = {
        "schema": V56_SCHEMA,
        "previous_request": {"path": str(source_path),
                              "physical_sha256": CORE.sha256_file(source_path, max_bytes=CORE.MAX_JSON_BYTES),
                              "canonical_sha256": source["sha256"]},
        "executor_role": "executor_v56", "worker_role": "v2_worker",
        "worker_wrapper_path": "sources/<sealed-overlay-v34 v2_worker target>",
        "worker_wrapper_path_contract": "wrapper._worker_path() -> target/runtime/native/WORKER_NAME",
        "plain_worker_source_role": "raw_worker_v2",
        "plain_worker_source_scope": "copied target runtime/runtime/native only",
        "compatibility_target_relative_path": "runtime/native/" + WORKER_NAME,
        "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
        "private_worker_path_smoke": "pinned venv imports copied wrapper._worker_path and _load_worker",
        "private_import_timeout_seconds": IMPORT_TIMEOUT_SECONDS,
        "source_path_fallback": "FORBIDDEN", "payload_read_during_build": False,
        "qualification": dict(UNKNOWN),
    }
    value["status"] = "READY_FOR_PARENT_STAGE2_GUARD"
    value["raw_opened"] = False; value["hdf5_opened"] = False
    value["model_invoked"] = False; value["cfd_invoked"] = False
    value["qualification"] = dict(UNKNOWN)
    value["sha256"] = canonical_sha(value)
    out = _write_new(output_request, value)
    return {"schema": V56_SCHEMA, "status": value["status"], "request": str(out),
            "request_sha256": CORE.sha256_file(out, max_bytes=CORE.MAX_JSON_BYTES),
            "executor_target_path": str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v56.py"),
            "payload_read": False, "qualification": dict(UNKNOWN)}


_ACTIVE_REQUEST: Mapping[str, Any] | None = None
_ACTIVE_COMPATIBILITY: dict[str, Any] | None = None


def _runtime_row(request: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    rows = request.get("runtime_sources")
    if not isinstance(rows, list):
        raise PortableV56Error("runtime_sources are missing")
    found = [row for row in rows if isinstance(row, Mapping) and row.get("role") == role]
    if len(found) != 1:
        raise PortableV56Error(f"exactly one runtime source is required: {role}")
    return found[0]


def inspect_copied_graph(*, sealed_overlay: Path | str,
                         private_import_report: Path | str,
                         runtime_audit: Path | str,
                         engine_binding: Path | str,
                         bundle_root: Path | str) -> dict[str, Any]:
    """Check the copied code graph without opening any payload file.

    This is deliberately a source-only gate.  It hashes only the bounded
    Python/JSON metadata roles named by the reports, and reports the V4
    compatibility target separately from the four V55 sibling aliases.  A
    missing target is a concrete preflight failure; it is never converted to
    a synthetic import pass.
    """
    overlay_path, overlay = _json(sealed_overlay, "sealed overlay")
    import_path, imports = _json(private_import_report, "private import report")
    audit_path, audit = _json(runtime_audit, "private runtime audit")
    binding_path, binding = _json(engine_binding, "engine binding")
    root = _absolute(str(bundle_root), "bundle_root")
    entries = overlay.get("entries")
    if not isinstance(entries, list):
        raise PortableV56Error("sealed overlay entries are missing")
    role_rows: dict[str, Mapping[str, Any]] = {}
    for item in entries:
        if isinstance(item, Mapping) and isinstance(item.get("role"), str):
            role_rows.setdefault(str(item["role"]), item)
    required_roles = ["v2_worker", "raw_converter", "v14_operator", "v15_operator", "v16_operator"]
    role_checks: list[dict[str, Any]] = []
    for role in required_roles:
        row = role_rows.get(role)
        if row is None:
            raise PortableV56Error(f"sealed overlay role is missing: {role}")
        target_value = row.get("target_path")
        if not isinstance(target_value, str):
            raise PortableV56Error(f"sealed overlay target is missing: {role}")
        target = _regular(target_value, f"sealed overlay {role}")
        try:
            target.relative_to(root)
        except ValueError as error:
            raise PortableV56Error(f"sealed overlay target escapes bundle: {role}") from error
        expected = row.get("target_sha256") or row.get("expected_sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise PortableV56Error(f"sealed overlay SHA is missing: {role}")
        actual = CORE.sha256_file(target)
        if actual != expected:
            raise PortableV56Error(f"sealed overlay code SHA differs: {role}")
        role_checks.append({"role": role, "path": str(target), "sha256": actual,
                            "bytes": int(target.stat().st_size), "inside_bundle": True})
    aliases = imports.get("aliases")
    if imports.get("status") != "PASS_V40_COPIED_TARGET_TRANSITIVE_IMPORT" \
            or imports.get("original_path_fallback") != "FORBIDDEN" \
            or imports.get("hdf5_or_bi4_read") is not False \
            or not isinstance(aliases, list) or len(aliases) != 4:
        raise PortableV56Error("V40 copied four-module import report is not closed")
    alias_checks = []
    for item in aliases:
        if not isinstance(item, Mapping):
            raise PortableV56Error("V40 alias record is malformed")
        alias = _regular(item.get("alias_path"), "V40 copied alias")
        expected = item.get("sha256")
        if not isinstance(expected, str) or CORE.sha256_file(alias) != expected:
            raise PortableV56Error(f"V40 alias SHA differs: {alias}")
        alias_checks.append({"role": item.get("role"), "path": str(alias),
                             "sha256": expected, "inode_distinct": item.get("inode_distinct") is True})
    modules = audit.get("modules")
    if audit.get("status") != "PASS_CLOSED_RUNTIME_MODULE_FILES" \
            or audit.get("original_path_fallback") != "FORBIDDEN" \
            or not isinstance(modules, Mapping):
        raise PortableV56Error("private runtime audit is not closed")
    runtime_checks = []
    for role, item in modules.items():
        if not isinstance(item, Mapping) or item.get("under_runtime") is not True:
            raise PortableV56Error(f"runtime module is not under copied runtime: {role}")
        path = _regular(item.get("module_file"), f"runtime module {role}")
        try:
            path.relative_to(root)
        except ValueError as error:
            raise PortableV56Error(f"runtime module escapes bundle: {role}") from error
        runtime_checks.append({"role": role, "path": str(path), "inside_bundle": True})
    if binding.get("status") != "PASS_V40_RELOCATED_CONTRACT_CONSUMED_BEFORE_LABEL":
        raise PortableV56Error("V40 engine binding is not complete")
    compatibility = root / "runtime" / "native" / WORKER_NAME
    plain = modules.get("raw_worker_v2", {})
    plain_path = Path(str(plain.get("module_file"))) if isinstance(plain, Mapping) else Path()
    compatibility_ready = compatibility.is_file() and not compatibility.is_symlink()
    if compatibility_ready:
        expected_plain = CORE.sha256_file(plain_path) if plain_path.is_file() else None
        compatibility_ready = expected_plain is not None and CORE.sha256_file(compatibility) == expected_plain
        compatibility_ready = compatibility_ready and (compatibility.stat().st_dev, compatibility.stat().st_ino) != (plain_path.stat().st_dev, plain_path.stat().st_ino)
    status = "PASS_COPIED_CODE_GRAPH_WITH_V4_COMPATIBILITY_TARGET" if compatibility_ready \
        else "FAILED_V4_COMPATIBILITY_TARGET_MISSING"
    return {"schema": "ds02.stage2.f2-copied-code-graph-v56.v1", "status": status,
            "sealed_overlay": {"path": str(overlay_path), "physical_sha256": CORE.sha256_file(overlay_path, max_bytes=CORE.MAX_JSON_BYTES)},
            "private_import_report": {"path": str(import_path), "physical_sha256": CORE.sha256_file(import_path, max_bytes=CORE.MAX_JSON_BYTES)},
            "runtime_audit": {"path": str(audit_path), "physical_sha256": CORE.sha256_file(audit_path, max_bytes=CORE.MAX_JSON_BYTES)},
            "engine_binding": {"path": str(binding_path), "physical_sha256": CORE.sha256_file(binding_path, max_bytes=CORE.MAX_JSON_BYTES)},
            "bundle_root": str(root), "roles": role_checks, "four_aliases": alias_checks,
            "runtime_modules": runtime_checks,
            "v4_compatibility": {"path": str(compatibility), "plain_worker_source": str(plain_path),
                                 "ready": bool(compatibility_ready), "smoke_required": True,
                                 "source_path_fallback": "FORBIDDEN"},
            "payload_read": False, "qualification": dict(UNKNOWN)}


def _regular(value: Any, role: str) -> Path:
    path = Path(str(value)).expanduser()
    if path.is_symlink() or not path.is_file():
        raise PortableV56Error(f"{role} is not a copied regular file: {path}")
    return path


def _materialize_worker_compatibility(request: Mapping[str, Any], worker_dir: Path | str) -> dict[str, Any]:
    """Create the plain V2 file at immutable V4 wrapper's actual lookup path."""
    target_dir = Path(worker_dir).expanduser().resolve()
    if not target_dir.is_dir():
        raise PortableV56Error(f"copied overlay worker directory is missing: {target_dir}")
    bundle_root = target_dir.parent
    row = _runtime_row(request, "raw_worker_v2")
    source = _regular(row.get("target_path"), "copied raw_worker_v2")
    try:
        source.relative_to(bundle_root)
    except ValueError as error:
        raise PortableV56Error(f"copied raw_worker_v2 is outside bundle: {source}") from error
    expected = row.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise PortableV56Error("raw_worker_v2 SHA is missing")
    source_stat = source.stat(follow_symlinks=False)
    expected_bytes = int(row.get("bytes", source_stat.st_size))
    expected_mode = int(row.get("mode_bits", row.get("source_mode_bits", stat.S_IMODE(source_stat.st_mode))))
    if CORE.sha256_file(source) != expected or source_stat.st_size != expected_bytes:
        raise PortableV56Error("copied raw_worker_v2 content differs from request")
    if stat.S_IMODE(source_stat.st_mode) != expected_mode:
        raise PortableV56Error("copied raw_worker_v2 mode differs from request")
    alias = bundle_root / "runtime" / "native" / WORKER_NAME
    if alias.exists() or alias.is_symlink():
        if alias.is_symlink() or not alias.is_file():
            raise PortableV56Error(f"worker compatibility target is not a regular file: {alias}")
        state = "EXISTING_VERIFIED_COMPATIBILITY_COPY"
    else:
        alias.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, alias)
        os.chmod(alias, expected_mode)
        state = "CREATED_FROM_COPIED_RUNTIME_SOURCE"
    alias_stat = alias.stat(follow_symlinks=False)
    if (alias_stat.st_dev, alias_stat.st_ino) == (source_stat.st_dev, source_stat.st_ino):
        raise PortableV56Error("worker compatibility target shares source inode")
    if alias_stat.st_size != expected_bytes or stat.S_IMODE(alias_stat.st_mode) != expected_mode:
        raise PortableV56Error("worker compatibility target stat differs")
    if CORE.sha256_file(alias) != expected:
        raise PortableV56Error("worker compatibility target SHA differs")
    record = {"role": "raw_worker_v2_compatibility", "source_path": str(source),
              "target_path": str(alias), "sha256": expected, "bytes": expected_bytes,
              "source_mode_bits": expected_mode, "target_mode_bits": stat.S_IMODE(alias_stat.st_mode),
              "source_st_dev": int(source_stat.st_dev), "source_st_ino": int(source_stat.st_ino),
              "target_st_dev": int(alias_stat.st_dev), "target_st_ino": int(alias_stat.st_ino),
              "inode_distinct": True, "state": state, "source_path_fallback": "FORBIDDEN",
              "lookup_contract": "copied wrapper._worker_path() exact target/runtime/native/WORKER_NAME"}
    global _ACTIVE_COMPATIBILITY
    _ACTIVE_COMPATIBILITY = record
    return record


def _wrapper(request: Mapping[str, Any], worker_dir: Path) -> Path:
    candidates = sorted(worker_dir.glob("*ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"))
    if len(candidates) != 1 or candidates[0].is_symlink() or not candidates[0].is_file():
        raise PortableV56Error("copied overlay has no unique regular V4 worker wrapper")
    expected = (((request.get("execution") or {}).get("decoder_scratch") or {}).get("wrapper_sha256"))
    if not isinstance(expected, str) or CORE.sha256_file(candidates[0]) != expected:
        raise PortableV56Error("copied overlay V4 worker wrapper SHA differs")
    return candidates[0]


def _smoke_worker(python: Path | str, request: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records or not isinstance(records[0].get("worker_parent"), str):
        raise PortableV56Error("worker-parent aliases are missing")
    worker_dir = Path(str(records[0]["worker_parent"])).expanduser().resolve()
    wrapper = _wrapper(request, worker_dir)
    compatibility = _ACTIVE_COMPATIBILITY
    if not isinstance(compatibility, Mapping):
        raise PortableV56Error("worker compatibility record is missing")
    python_path = Path(python).expanduser()
    if not python_path.is_file():
        raise PortableV56Error(f"bound venv Python is missing: {python_path}")
    code = '''
import importlib.util, json, pathlib, sys
wrapper = pathlib.Path(sys.argv[1]).resolve()
expected = pathlib.Path(sys.argv[2]).resolve()
spec = importlib.util.spec_from_file_location("_ds02_copied_v4_worker_wrapper", wrapper)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load copied wrapper")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
path = module._worker_path().resolve()
if path != expected:
    raise RuntimeError(f"worker path mismatch: {path} != {expected}")
loaded = module._load_worker()
loaded_path = pathlib.Path(loaded.__file__).resolve()
if loaded_path != expected:
    raise RuntimeError(f"loaded worker mismatch: {loaded_path} != {expected}")
print(json.dumps({"wrapper": str(wrapper), "worker_path": str(path),
                  "loaded_worker": str(loaded_path)}, sort_keys=True))
'''
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    try:
        proc = subprocess.run([str(python_path), "-B", "-I", "-c", code,
                               str(wrapper), str(compatibility["target_path"])],
                              capture_output=True, text=True, check=False, env=env,
                              timeout=IMPORT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise PortableV56Error("copied V4 worker path smoke timed out") from error
    if proc.returncode != 0:
        raise PortableV56Error(f"copied V4 worker path smoke failed: {proc.stderr[-1200:]}")
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise PortableV56Error("copied V4 worker path smoke returned no JSON") from error
    result.update({"status": "PASS_COPIED_V4_WORKER_PATH_AND_LOAD",
                   "timeout_seconds": IMPORT_TIMEOUT_SECONDS, "payload_read": False,
                   "original_path_fallback": "FORBIDDEN", "compatibility": dict(compatibility)})
    return result


def _materialize_aliases_v56(bindings: Mapping[str, Mapping[str, Any]], worker_dir: Path | str) -> list[dict[str, Any]]:
    if not isinstance(_ACTIVE_REQUEST, Mapping):
        raise PortableV56Error("V56 active request is missing")
    records = V55._materialize_aliases_in_worker_parent(bindings, worker_dir)
    _materialize_worker_compatibility(_ACTIVE_REQUEST, worker_dir)
    return records


def _import_four_modules_v56(python: Path | str, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = V55._import_four_modules(python, records)
    if not isinstance(_ACTIVE_REQUEST, Mapping):
        raise PortableV56Error("V56 active request is missing")
    result["worker_path_smoke"] = _smoke_worker(python, _ACTIVE_REQUEST, records)
    result["worker_compatibility_target"] = dict(_ACTIVE_COMPATIBILITY or {})
    return result


def run(request_path: Path | str, *, io_slot_approved: bool,
        parent_pid: int | None = None, evaluator_proof: Path | None = None,
        max_wall_seconds: float | None = None) -> dict[str, Any]:
    global _ACTIVE_REQUEST, _ACTIVE_COMPATIBILITY
    _, request = _request_v55(request_path)
    marker = request.get("forward_v56")
    if not isinstance(marker, Mapping) or marker.get("schema") != V56_SCHEMA:
        raise PortableV56Error("V56 forward marker is missing")
    _ACTIVE_REQUEST = request
    _ACTIVE_COMPATIBILITY = None
    original_aliases = V55._materialize_aliases_in_worker_parent
    original_import = V55._import_four_modules
    V55._materialize_aliases_in_worker_parent = _materialize_aliases_v56
    V55._import_four_modules = _import_four_modules_v56
    try:
        return V55.run(request_path, io_slot_approved=io_slot_approved,
                       parent_pid=parent_pid, evaluator_proof=evaluator_proof,
                       max_wall_seconds=max_wall_seconds)
    finally:
        V55._materialize_aliases_in_worker_parent = original_aliases
        V55._import_four_modules = original_import
        _ACTIVE_REQUEST = None
        _ACTIVE_COMPATIBILITY = None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-forward")
    build.add_argument("--v55-request", type=Path, required=True)
    build.add_argument("--output-request", type=Path, required=True)
    build.add_argument("--target-root", type=Path)
    build.add_argument("--output-root", type=Path)
    runner = sub.add_parser("run")
    runner.add_argument("--request", type=Path, required=True)
    runner.add_argument("--io-slot-approved", action="store_true")
    runner.add_argument("--parent-pid", type=int)
    runner.add_argument("--evaluator-proof", type=Path)
    runner.add_argument("--max-wall-seconds", type=float)
    graph = sub.add_parser("inspect-copied-graph")
    graph.add_argument("--sealed-overlay", type=Path, required=True)
    graph.add_argument("--private-import-report", type=Path, required=True)
    graph.add_argument("--runtime-audit", type=Path, required=True)
    graph.add_argument("--engine-binding", type=Path, required=True)
    graph.add_argument("--bundle-root", type=Path, required=True)
    graph.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-forward":
            result = build_forward(v55_request=args.v55_request, output_request=args.output_request,
                                   target_root=args.target_root, output_root=args.output_root)
        else:
            if args.command == "inspect-copied-graph":
                result = inspect_copied_graph(
                    sealed_overlay=args.sealed_overlay,
                    private_import_report=args.private_import_report,
                    runtime_audit=args.runtime_audit,
                    engine_binding=args.engine_binding,
                    bundle_root=args.bundle_root)
                _write_new(args.output, result)
            else:
                result = run(args.request, io_slot_approved=args.io_slot_approved,
                             parent_pid=args.parent_pid, evaluator_proof=args.evaluator_proof,
                             max_wall_seconds=args.max_wall_seconds)
    except (PortableV56Error, V55.PortableV55Error, V55.V54.PortableV54Error,
            V55.V54.V53.PortableV53Error, V55.V54.V53.V52.PortableV52Error,
            V55.V54.V53.V52.V51.PortableV51Error, OSError, ValueError,
            TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v56: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2, default=str))
    return 1 if str(result.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())

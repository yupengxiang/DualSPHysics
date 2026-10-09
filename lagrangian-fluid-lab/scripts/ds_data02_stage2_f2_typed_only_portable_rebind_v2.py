#!/usr/bin/env python3
"""Strict target-relative request rebinding for the typed-only consumer.

This is an additive successor to ``portable_rebind_v1``.  V1 seals copied
files; V2 also rewrites and registers the *inner* consumer request, then
recursively checks every actionable nested path before it can be run.  Source
paths remain provenance only.  The copied process reads the relocated V8 JSON,
V12 scope, and existing typed scorer after the parent guard, with a bounded
streaming subprocess wrapper and parent-death cleanup.

The builder reads only bounded JSON/code metadata.  Deferred result/HDF5 paths
remain explicitly ``PARENT_AFTER_RESERVATION`` and are never hashed by this
metadata phase.  No ledger, model, CFD, raw, BI4, or cold-replay credit is
created here.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V1_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_typed_only_portable_rebind_v1.py"
if not V1_SCRIPT.is_file():
    raise RuntimeError(f"portable rebind V1 dependency is unavailable: {V1_SCRIPT}")
_v1_spec = importlib.util.spec_from_file_location("ds02_portable_rebind_v1_for_v2", V1_SCRIPT)
if _v1_spec is None or _v1_spec.loader is None:
    raise RuntimeError(f"cannot load portable rebind V1 dependency: {V1_SCRIPT}")
V1 = importlib.util.module_from_spec(_v1_spec)
sys.modules[_v1_spec.name] = V1
_v1_spec.loader.exec_module(V1)


REQUEST_SCHEMA = "ds02.stage2.f2-typed-only-portable-rebind-request.v2"
REPORT_SCHEMA = "ds02.stage2.f2-typed-only-portable-rebind-execution-report.v2"
MAX_METADATA_BYTES = 10 * 1024 * 1024
MAX_LOG_BYTES = 4 * 1024 * 1024
ROLLING_TAIL_BYTES = 64 * 1024
HEX64 = set("0123456789abcdef")
PROVENANCE_KEYS = {
    "original_roots", "source_provenance", "provenance", "old_absolute_paths",
    "source_path_provenance", "argv0_provenance", "resolved_provenance",
}


class PortableRebindV2Error(RuntimeError):
    """Strict V2 request, runtime, or child boundary failure."""


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _sha(path: Path, *, maximum: int = MAX_METADATA_BYTES) -> str:
    if path.is_symlink() or not path.is_file():
        raise PortableRebindV2Error(f"bound file must be regular and non-symlink: {path}")
    if path.stat().st_size > maximum:
        raise PortableRebindV2Error(f"bounded metadata hash limit exceeded: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _full_stat(path: Path) -> dict[str, int]:
    if path.is_symlink() or not path.is_file():
        raise PortableRebindV2Error(f"bound target must be regular and non-symlink: {path}")
    value = path.stat()
    return {"bytes": int(value.st_size), "mode_bits": int(value.st_mode & 0o7777),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
            "st_dev": int(value.st_dev), "st_ino": int(value.st_ino)}


def _json(path: Path, role: str, *, maximum: int = MAX_METADATA_BYTES) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PortableRebindV2Error(f"{role} must be regular and non-symlink: {path}")
    if path.stat().st_size > maximum:
        raise PortableRebindV2Error(f"{role} exceeds bounded metadata limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableRebindV2Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PortableRebindV2Error(f"{role} must be a JSON object")
    return value


def _absolute(path: Path | str) -> Path:
    value = Path(path).expanduser()
    return value if value.is_absolute() else Path(os.path.abspath(value))


def _safe_relative(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value:
        raise PortableRebindV2Error(f"{role} target-relative path is missing")
    path = Path(value)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        raise PortableRebindV2Error(f"{role} target path is not safely relative: {value}")
    return path.as_posix()


def _reject_symlink_components(path: Path, root: Path) -> None:
    if root.is_symlink():
        raise PortableRebindV2Error(f"relocated root is a symlink: {root}")
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise PortableRebindV2Error(f"target escapes relocated root: {path}") from error
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise PortableRebindV2Error(f"relocation target contains a symlink: {current}")


def _target(root: Path, relative: str, *, required: bool = True) -> Path:
    target = root / _safe_relative(relative, "target")
    _reject_symlink_components(target, root)
    if required and (not target.exists() or not target.is_file() or target.is_symlink()):
        raise PortableRebindV2Error(f"required relocated role is missing: {target}")
    return target


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _load_contract(path: Path) -> dict[str, Any]:
    return V1._load_contract(path)


def _role_maps(contract: Mapping[str, Any]) -> tuple[Path, dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    root = _absolute(contract.get("relocated_root"))
    by_role: dict[str, Mapping[str, Any]] = {}
    by_source: dict[str, Mapping[str, Any]] = {}
    for role in contract.get("roles", []):
        if not isinstance(role, Mapping):
            raise PortableRebindV2Error("malformed role in V1 contract")
        logical = role.get("logical_role")
        target = role.get("target_relative_path")
        source = role.get("source_path_provenance")
        if not isinstance(logical, str) or not logical or not isinstance(source, str):
            raise PortableRebindV2Error("V1 role lacks logical/source provenance")
        target = _safe_relative(target, f"{logical}.target")
        if logical in by_role or target in {str(item.get("target_relative_path")) for item in by_role.values()}:
            raise PortableRebindV2Error(f"duplicate role/target in V1 contract: {logical}/{target}")
        by_role[logical] = role
        by_source[os.path.abspath(source)] = role
    return root, by_role, by_source


def _verify_contract_targets(contract: Mapping[str, Any], root: Path) -> None:
    """Verify small targets; leave deferred payloads for the parent gate."""
    for role in contract.get("roles", []):
        if not isinstance(role, Mapping):
            raise PortableRebindV2Error("malformed contract role")
        target = _target(root, _safe_relative(role.get("target_relative_path"), "role.target"), required=False)
        deferred = bool(role.get("deferred_content"))
        if not target.exists():
            if deferred:
                continue
            raise PortableRebindV2Error(f"required relocated role is missing: {target}")
        stat = _full_stat(target)
        if not deferred:
            observed = _sha(target)
            if observed != role.get("source_sha256"):
                raise PortableRebindV2Error(f"relocated role SHA differs: {role.get('logical_role')}")
        # A source mtime/inode is never compared with this fresh target stat.
        if stat["bytes"] != int(role.get("source_stat_provenance", {}).get("bytes", stat["bytes"])) and not deferred:
            raise PortableRebindV2Error(f"relocated role byte size differs: {role.get('logical_role')}")


def _source_to_target(root: Path, by_source: Mapping[str, Mapping[str, Any]]) -> dict[str, tuple[Mapping[str, Any], Path]]:
    result: dict[str, tuple[Mapping[str, Any], Path]] = {}
    for source, role in by_source.items():
        target = root / _safe_relative(role.get("target_relative_path"), "role.target")
        result[source] = (role, target)
    return result


def _pointer(parts: tuple[str, ...]) -> str:
    return "" if not parts else "".join("/" + item.replace("~", "~0").replace("/", "~1") for item in parts)


def _provenance_context(parts: tuple[str, ...]) -> bool:
    return any(part.lower() in PROVENANCE_KEYS for part in parts)


def _directory_rebind(parts: tuple[str, ...], root: Path) -> Path | None:
    lower = [part.lower() for part in parts]
    if not lower:
        return None
    key = lower[-1]
    if key in {"target_root", "runtime_root", "runtime_target_root"}:
        return root / "runtime"
    if key in {"output_root", "products_root", "proof_output_root_binding"}:
        return root / "products"
    if key in {"fresh_output_root", "fresh_output_namespace", "fresh_proof_namespace", "proof_namespace"}:
        return root / "reports"
    # Some producer requests wrap the output directory as
    # ``{"fresh_output_namespace": {"root": ...}}``.  The ``root`` key is
    # still an actionable directory binding; do not leave its historical
    # absolute source path in the copied request.
    if key == "root" and any(item in {
        "fresh_output_namespace", "fresh_output_root", "fresh_proof_namespace", "proof_namespace"
    } for item in lower[:-1]):
        return root / "reports"
    return None


def _rewrite_request(value: Any, *, root: Path,
                     source_map: Mapping[str, tuple[Mapping[str, Any], Path]],
                     role_by_target: Mapping[str, Mapping[str, Any]],
                     bindings: list[dict[str, Any]], parts: tuple[str, ...] = ()) -> Any:
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if (isinstance(child, str) and child.startswith("/") and
                    key_text.lower() in {"root", "target_root", "output_root", "runtime_root",
                                         "runtime_target_root", "fresh_output_root"}):
                directory = _directory_rebind(parts + (key_text,), root)
                if directory is not None and not _provenance_context(parts):
                    output[key] = str(directory)
                    bindings.append({"pointer": _pointer(parts + (key_text,)),
                                     "actionable": True,
                                     "synthetic_directory": str(directory.relative_to(root))})
                    continue
            if key_text == "path" and isinstance(child, str) and child.startswith("/"):
                raw = _absolute(child)
                if _provenance_context(parts):
                    output[key] = child
                    bindings.append({"pointer": _pointer(parts + (key_text,)),
                                     "actionable": False, "provenance_path": child})
                    continue
                mapped = source_map.get(os.path.abspath(str(raw)))
                if mapped is None:
                    directory = _directory_rebind(parts, root)
                    if directory is None:
                        raise PortableRebindV2Error(
                            f"unbound actionable request path at {_pointer(parts + (key_text,))}: {child}")
                    output[key] = str(directory)
                    bindings.append({"pointer": _pointer(parts + (key_text,)),
                                     "actionable": True, "synthetic_directory": str(directory.relative_to(root))})
                    continue
                role, target = mapped
                relative = str(target.relative_to(root))
                if target.exists():
                    _reject_symlink_components(target, root)
                    target_stat = _full_stat(target)
                else:
                    target_stat = None
                deferred = bool(role.get("deferred_content"))
                output[key] = str(target)
                binding: dict[str, Any] = {
                    "pointer": _pointer(parts + (key_text,)), "actionable": True,
                    "logical_role": role["logical_role"], "source_path_provenance": role.get("source_path_provenance"),
                    "source_sha256": role.get("source_sha256"),
                    "source_stat_provenance": dict(role.get("source_stat_provenance", {})),
                    "target_relative_path": relative, "target_stat": target_stat,
                    "source_inode_mtime_equivalence": "NOT_CLAIMED",
                    "deferred_content": deferred,
                    "content_verification_phase": "PARENT_AFTER_RESERVATION" if deferred else "REBOUND_METADATA",
                }
                bindings.append(binding)
                continue
            if key_text == "original_roots" and isinstance(child, list):
                output[key] = list(child)
                for index, item in enumerate(child):
                    if isinstance(item, str):
                        bindings.append({"pointer": _pointer(parts + (key_text, str(index))),
                                         "actionable": False, "provenance_path": item})
                continue
            output[key] = _rewrite_request(child, root=root, source_map=source_map,
                                           role_by_target=role_by_target, bindings=bindings,
                                           parts=parts + (key_text,))
        # A copied contract's top-level canonical SHA must describe its
        # rebased bytes.  Nested request bindings deliberately carry their
        # producer *file* SHA (which is distinct from that request's
        # canonical SHA); recalculating every nested ``sha256`` here would
        # silently turn that file binding into a canonical digest and make
        # the V12 source-request/producer join fail after relocation.
        if (not parts) and "sha256" in output and isinstance(output.get("schema"), str):
            output["sha256"] = _canonical(output)
        return output
    if isinstance(value, list):
        return [_rewrite_request(item, root=root, source_map=source_map,
                                 role_by_target=role_by_target, bindings=bindings,
                                 parts=parts + (str(index),)) for index, item in enumerate(value)]
    return value


def _runtime_role(by_role: Mapping[str, Mapping[str, Any]], *names: str) -> Mapping[str, Any]:
    for name in names:
        role = by_role.get(name)
        if role is not None:
            return role
    raise PortableRebindV2Error(f"required runtime role is not declared: {'/'.join(names)}")


def build_request_overlay(*, contract_path: Path | str, request_role: str,
                          output: Path | str, request_target_relative: str,
                          request_id: str) -> dict[str, Any]:
    contract = _load_contract(contract_path)
    root, by_role, by_source = _role_maps(contract)
    _verify_contract_targets(contract, root)
    role = by_role.get(request_role)
    if role is None:
        raise PortableRebindV2Error(f"request role is not declared in V1 contract: {request_role}")
    request_rel = _safe_relative(request_target_relative, "generated request")
    request_target = root / request_rel
    if request_target.exists() or request_target.is_symlink():
        raise PortableRebindV2Error(f"refusing existing generated request: {request_target}")
    source_target = root / _safe_relative(role.get("target_relative_path"), "request role target")
    if not source_target.is_file() or source_target.is_symlink():
        raise PortableRebindV2Error(f"relocated request role is missing: {source_target}")
    source_request = _json(source_target, "relocated inner request")
    source_map = _source_to_target(root, by_source)
    bindings: list[dict[str, Any]] = []
    rebased = _rewrite_request(source_request, root=root, source_map=source_map,
                               role_by_target={str(v.get("target_relative_path")): v for v in by_role.values()},
                               bindings=bindings)
    if not isinstance(rebased, dict):
        raise PortableRebindV2Error("rebased inner request is not an object")
    # The target path itself is an actionable role, and is bound separately
    # from nested paths.  This avoids allowing run() to select an arbitrary
    # request-relative file.
    request_target.parent.mkdir(parents=True, exist_ok=True)
    request_target.write_text(json.dumps(rebased, indent=2, sort_keys=True,
                                         ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    generated_stat = _full_stat(request_target)
    generated_sha = _sha(request_target)
    runtime = {
        # The copied entrypoint must invoke the copied V1/V2 pair.  Running
        # this source file from the consumer worktree would make the private
        # subprocess depend on the agent checkout and would defeat the
        # relocation audit.
        # V1's consumed contract builder names its injected helper role
        # ``typed_only_portable_rebind_v1``.  Accept that exact historical
        # logical name as the compatibility alias; the target path remains
        # strictly sealed and is never guessed.
        "portable_rebind_v1_entrypoint": _runtime_role(
            by_role, "portable_rebind_v1_entrypoint", "typed_only_portable_rebind_v1"),
        "portable_rebind_v2_entrypoint": _runtime_role(by_role, "portable_rebind_v2_entrypoint"),
        "v8_consumer": _runtime_role(by_role, "fresh_v16_proof_consumer_v8"),
        "v12_consumer": _runtime_role(by_role, "fresh_v16_proof_consumer_v12"),
        "typed_scorer": _runtime_role(by_role, "typed_only_evaluator_v1"),
        # typed_only_evaluator_v1 imports V3, which imports V2 and the
        # replay v14/v15 pair from its own sibling directory.  Bind those
        # transitive files explicitly instead of allowing sys.path/original
        # checkout fallback.
        "typed_scorer_v3": _runtime_role(by_role, "typed_only_evaluator_v3"),
        "typed_scorer_v2": _runtime_role(by_role, "typed_only_evaluator_v2"),
        "replay_v14": _runtime_role(by_role, "replay_v14"),
        "replay_v15": _runtime_role(by_role, "replay_v15"),
        "frozen_v15": _runtime_role(by_role, "frozen_v15_request"),
        "literal_python": _runtime_role(by_role, "literal_project_venv_python"),
        "pyvenv_cfg": _runtime_role(by_role, "pinned_project_pyvenv_cfg"),
        "v12_sidecar": _runtime_role(by_role, "v12_semantic_sidecar"),
        "producer_nested_report": _runtime_role(by_role, "producer_nested_report_v2"),
    }
    runtime_bindings = {}
    for key, runtime_role in runtime.items():
        runtime_bindings[key] = {
            "logical_role": runtime_role["logical_role"],
            "target_relative_path": runtime_role["target_relative_path"],
            "source_sha256": runtime_role.get("source_sha256"),
            "source_stat_provenance": dict(runtime_role.get("source_stat_provenance", {})),
            "target_stat": (dict(_full_stat(root / runtime_role["target_relative_path"]))
                            if (root / runtime_role["target_relative_path"]).is_file() else None),
            "source_inode_mtime_equivalence": "NOT_CLAIMED",
        }
    deferred = [item for item in bindings if item.get("deferred_content")]
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD" if not deferred else "PENDING_PARENT_RELOCATION_TARGETS",
        "request_id": request_id,
        "contract_binding": {"path": str(_absolute(contract_path)), "sha256": contract["sha256"],
                              "contract_id": contract.get("contract_id")},
        "relocated_root": str(root),
        "request_binding": {
            "source_logical_role": request_role,
            "source_target_relative_path": role["target_relative_path"],
            "generated_target_relative_path": request_rel,
            "generated_file_sha256": generated_sha,
            "generated_target_stat": generated_stat,
            "source_sha256": role.get("source_sha256"),
            "source_stat_provenance": dict(role.get("source_stat_provenance", {})),
            "source_inode_mtime_equivalence": "NOT_CLAIMED",
        },
        "nested_actionable_bindings": bindings,
        "runtime_bindings": runtime_bindings,
        "runtime_closure": {
            "entrypoint_role": "portable_rebind_v2_entrypoint",
            "v1_entrypoint_role": "portable_rebind_v1_entrypoint",
            "strict_sibling_imports": True,
            "required_roles": sorted(runtime_bindings),
            "original_worktree_fallback": "REJECT",
            "literal_interpreter_path_policy": "SEALED_TARGET_REGULAR_EXECUTABLE",
        },
        "scorer_frozen_request": {
            "logical_role": runtime["frozen_v15"]["logical_role"],
            "target_relative_path": runtime["frozen_v15"]["target_relative_path"],
            "source_sha256": runtime["frozen_v15"].get("source_sha256"),
            "source_stat_provenance": dict(runtime["frozen_v15"].get("source_stat_provenance", {})),
            "target_stat": runtime_bindings["frozen_v15"].get("target_stat"),
        },
        "path_policy": {"original_absolute_path_fallback": "REJECT",
                        "unbound_actionable_paths": "REJECT",
                        "provenance_paths_are_not_actionable": True,
                        "symlink_targets": "REJECT"},
        "execution": {"max_wall_seconds": 900.0, "max_result_bytes": 100 * 1024 * 1024,
                       "max_log_bytes": MAX_LOG_BYTES, "rolling_tail_bytes": ROLLING_TAIL_BYTES,
                       "read_hdf5_or_bi4": False, "raw_opened": False,
                       "model_invoked": False, "cfd_invoked": False,
                       "content_sha_phase": "AFTER_PARENT_RESERVATION",
                       "parent_death_signal": "SIGTERM"},
        "ledger_mutated": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "old_path_fallback": False,
        "portable_cold_replay_credit": "NOT_CLAIMED",
        "payload_read_by_builder": False,
    }
    request["sha256"] = _canonical(request)
    out = _absolute(output)
    if out.exists() or out.is_symlink():
        raise PortableRebindV2Error(f"refusing existing request overlay output: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(request, indent=2, sort_keys=True,
                              ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    return {"schema": REQUEST_SCHEMA, "status": request["status"], "request": str(out),
            "file_sha256": _sha(out), "canonical_sha256": request["sha256"],
            "payload_read": False, "deferred_roles": len(deferred)}


def _load_request(path: Path | str) -> tuple[Path, dict[str, Any]]:
    target = _absolute(path)
    value = _json(target, "portable V2 request")
    if value.get("schema") != REQUEST_SCHEMA or value.get("sha256") != _canonical(value):
        raise PortableRebindV2Error("portable V2 request schema/canonical SHA differs")
    if value.get("old_path_fallback") is not False or value.get("ledger_mutated") is not False:
        raise PortableRebindV2Error("portable V2 request opens fallback or ledger mutation")
    return target, value


def _verify_runtime_role(root: Path, binding: Mapping[str, Any], role: str, *, hash_content: bool = True) -> Path:
    rel = _safe_relative(binding.get("target_relative_path"), f"runtime.{role}")
    target = _target(root, rel)
    stat = _full_stat(target)
    expected_stat = binding.get("target_stat")
    if not isinstance(expected_stat, Mapping) or stat != dict(expected_stat):
        raise PortableRebindV2Error(f"runtime target stat differs: {role}")
    if hash_content and _sha(target) != binding.get("source_sha256"):
        raise PortableRebindV2Error(f"runtime target SHA differs: {role}")
    return target


def _verify_request_recursive(request: Mapping[str, Any], root: Path,
                              registered: Sequence[Mapping[str, Any]] | None = None) -> None:
    # The generated inner request intentionally does not carry the outer
    # overlay's binding table.  Validation therefore receives that immutable
    # table explicitly; otherwise every valid nested path appears
    # "unregistered" after relocation.
    source_bindings = request.get("nested_actionable_bindings", []) if registered is None else registered
    expected = {item.get("pointer"): item for item in source_bindings
                if isinstance(item, Mapping) and item.get("actionable")}
    seen: set[str] = set()
    def visit(item: Any, parts: tuple[str, ...] = ()) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                text = str(key)
                synthetic_key = text.lower() in {
                    "root", "target_root", "output_root", "runtime_root",
                    "runtime_target_root", "fresh_output_root",
                    "fresh_output_namespace", "fresh_proof_namespace", "proof_namespace",
                }
                if synthetic_key and isinstance(child, str) and child.startswith("/"):
                    pointer = _pointer(parts + (text,))
                    if _provenance_context(parts):
                        continue
                    target = Path(child)
                    if not _under(target, root):
                        raise PortableRebindV2Error(f"actionable request path escapes target root: {pointer}")
                    _reject_symlink_components(target, root)
                    if pointer not in expected:
                        raise PortableRebindV2Error(f"unregistered actionable request path: {pointer}")
                    binding = expected[pointer]
                    synthetic = binding.get("synthetic_directory")
                    if synthetic is None:
                        raise PortableRebindV2Error(f"directory binding missing at {pointer}")
                    if target != root / _safe_relative(synthetic, pointer):
                        raise PortableRebindV2Error(f"synthetic request directory differs at {pointer}")
                    seen.add(pointer)
                    continue
                if text == "path" and isinstance(child, str) and child.startswith("/"):
                    pointer = _pointer(parts + (text,))
                    if _provenance_context(parts):
                        continue
                    target = Path(child)
                    if not _under(target, root):
                        raise PortableRebindV2Error(f"actionable request path escapes target root: {pointer}")
                    _reject_symlink_components(target, root)
                    if pointer not in expected:
                        raise PortableRebindV2Error(f"unregistered actionable request path: {pointer}")
                    binding = expected[pointer]
                    if binding.get("synthetic_directory") is not None:
                        synthetic = root / _safe_relative(binding["synthetic_directory"], pointer)
                        if target != synthetic:
                            raise PortableRebindV2Error(f"synthetic request directory differs at {pointer}")
                        seen.add(pointer)
                        continue
                    if str(target.relative_to(root)) != binding.get("target_relative_path"):
                        raise PortableRebindV2Error(f"request target path differs at {pointer}")
                    if binding.get("deferred_content"):
                        seen.add(pointer)
                    else:
                        if not target.is_file() or _sha(target) != binding.get("source_sha256"):
                            raise PortableRebindV2Error(f"request target content differs at {pointer}")
                        seen.add(pointer)
                else:
                    visit(child, parts + (text,))
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, parts + (str(index),))
    visit(request)
    if seen != set(expected):
        missing = sorted(set(expected) - seen)
        raise PortableRebindV2Error(f"registered actionable bindings were not observed: {missing[:3]}")


def validate_request_overlay(path: Path | str) -> dict[str, Any]:
    request_path, request = _load_request(path)
    root = _absolute(request.get("relocated_root"))
    if not root.is_dir() or root.is_symlink():
        raise PortableRebindV2Error(f"relocated root is unavailable: {root}")
    contract_path = _absolute(request["contract_binding"]["path"])
    contract = _load_contract(contract_path)
    if contract.get("sha256") != request["contract_binding"].get("sha256"):
        raise PortableRebindV2Error("V1 contract SHA differs from V2 request")
    if _absolute(contract.get("relocated_root")) != root:
        raise PortableRebindV2Error("V1/V2 relocated roots differ")
    role_binding = request["request_binding"]
    generated_rel = _safe_relative(role_binding.get("generated_target_relative_path"), "generated request")
    generated = _target(root, generated_rel)
    if str(generated.relative_to(root)) != generated_rel or _sha(generated) != role_binding.get("generated_file_sha256"):
        raise PortableRebindV2Error("generated request target SHA differs")
    if _full_stat(generated) != role_binding.get("generated_target_stat"):
        raise PortableRebindV2Error("generated request target stat differs")
    rebased = _json(generated, "generated rebased inner request")
    _verify_request_recursive(rebased, root, request.get("nested_actionable_bindings", []))
    runtime_paths = {}
    runtime_bindings = request.get("runtime_bindings")
    if not isinstance(runtime_bindings, Mapping) or not runtime_bindings:
        raise PortableRebindV2Error("runtime binding closure is missing")
    closure = request.get("runtime_closure")
    if not isinstance(closure, Mapping) or closure.get("strict_sibling_imports") is not True:
        raise PortableRebindV2Error("strict copied-runtime closure is not declared")
    if closure.get("original_worktree_fallback") != "REJECT":
        raise PortableRebindV2Error("runtime closure permits original-worktree fallback")
    if set(closure.get("required_roles", [])) != set(runtime_bindings):
        raise PortableRebindV2Error("runtime closure role list differs from bindings")
    if closure.get("entrypoint_role") != "portable_rebind_v2_entrypoint":
        raise PortableRebindV2Error("runtime closure entrypoint is not the copied V2 entrypoint")
    for role, binding in runtime_bindings.items():
        runtime_paths[role] = _verify_runtime_role(root, binding, role)
    frozen_binding = request.get("scorer_frozen_request")
    if not isinstance(frozen_binding, Mapping):
        raise PortableRebindV2Error("scorer frozen request binding is missing")
    runtime_paths["frozen_v15"] = _verify_runtime_role(root, frozen_binding, "frozen_v15")
    return {"request_path": request_path, "request": request, "root": root,
            "contract": contract, "generated_request": generated,
            "inner": rebased, "runtime_paths": runtime_paths,
            "payload_read": False}


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PortableRebindV2Error(f"cannot load copied runtime module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _rebase_runtime_json(path: Path, *, root: Path,
                         source_map: Mapping[str, tuple[Mapping[str, Any], Path]],
                         label: str) -> tuple[Path, dict[str, Any], str]:
    """Make a private, target-relative view of a copied JSON contract.

    The V2 request itself is sealed before the child starts.  Some of the
    source-bound contracts it points at (the V12 sidecar and the frozen V15
    request) contain their own actionable ``path`` fields.  Leaving those
    fields at their historical absolute locations would make a relocated
    worker either fail after the source tree is removed or silently fall back
    to it.  Rebase these *small* JSON contracts in the child, after the outer
    request has been validated, and use the resulting file only for this
    process.  The source bytes and their SHA/stat provenance remain recorded
    by the outer V2 contract; the temporary view gets its own target path.

    This helper never opens a deferred result/HDF5/BI4 payload.  The caller
    supplies the sealed source-to-target map, so an absolute path without an
    explicit role is rejected by ``_rewrite_request``.
    """
    source = _json(path, f"copied {label}")
    local_bindings: list[dict[str, Any]] = []
    rebased = _rewrite_request(
        source, root=root, source_map=source_map, role_by_target={},
        bindings=local_bindings, parts=())
    if not isinstance(rebased, dict):
        raise PortableRebindV2Error(f"copied {label} is not a JSON object")
    target = root / "runtime" / f".v2-rebased-{label}-{os.getpid()}.json"
    if target.exists() or target.is_symlink():
        raise PortableRebindV2Error(f"refusing existing private {label} view: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rebased, indent=2, sort_keys=True,
                                ensure_ascii=True, allow_nan=False) + "\n",
                      encoding="utf-8")
    # The source SHA is useful in the report, but the temporary target SHA is
    # intentionally not substituted for the sealed source binding.
    return target, rebased, _sha(path)


def _set_pdeathsig() -> None:
    try:
        libc = ctypes.CDLL(None)
        if int(libc.prctl(1, signal.SIGTERM, 0, 0, 0)) != 0:
            raise OSError("prctl(PR_SET_PDEATHSIG) failed")
    except (AttributeError, OSError) as error:
        raise PortableRebindV2Error(f"parent-death signal unavailable: {error}") from error


def _worker_run(overlay_path: Path, output_path: Path, parent_pid: int) -> dict[str, Any]:
    if os.getppid() != int(parent_pid):
        raise PortableRebindV2Error("worker is not directly owned by the portable guard")
    checked = validate_request_overlay(overlay_path)
    request = checked["request"]
    root = checked["root"]
    inner_path = checked["generated_request"]
    runtime = checked["runtime_paths"]
    v8 = _load_module(runtime["v8_consumer"], "ds02_relocated_v8_v2")
    v12 = _load_module(runtime["v12_consumer"], "ds02_relocated_v12_v2")
    evaluator = _load_module(runtime["typed_scorer"], "ds02_relocated_typed_scorer_v2")
    _root_from_contract, _by_role, by_source = _role_maps(checked["contract"])
    source_map = _source_to_target(root, by_source)
    # Rebase the small contracts nested below the sealed V8 request before
    # loading them.  This is the point where the copied worker is allowed to
    # consume target-side metadata; no source/provenance path is opened.
    sidecar_path = runtime["v12_sidecar"]
    rebased_sidecar, _sidecar_value, sidecar_source_sha = _rebase_runtime_json(
        sidecar_path, root=root, source_map=source_map, label="v12-sidecar")
    frozen_path = _target(root, _safe_relative(
        request["scorer_frozen_request"]["target_relative_path"], "scorer frozen request"))
    rebased_frozen, frozen_value, frozen_source_sha = _rebase_runtime_json(
        frozen_path, root=root, source_map=source_map, label="frozen-v15")
    inner = v8._load_object(inner_path)
    # Keep the generated request immutable as an audit artifact.  The private
    # execution view changes only the nested sidecar location and receives a
    # fresh canonical SHA; all other bindings remain those validated above.
    effective_inner = json.loads(json.dumps(inner))
    marker = effective_inner.get("v12_forward")
    if not isinstance(marker, dict) or not isinstance(marker.get("semantic_sidecar"), dict):
        raise PortableRebindV2Error("V12 forward marker lacks a semantic sidecar binding")
    marker["semantic_sidecar"]["path"] = str(rebased_sidecar)
    marker["semantic_sidecar"]["sha256"] = _sha(rebased_sidecar)
    effective_inner["sha256"] = _canonical(effective_inner)
    effective_inner_path = root / "runtime" / f".v2-rebased-inner-{os.getpid()}.json"
    if effective_inner_path.exists() or effective_inner_path.is_symlink():
        raise PortableRebindV2Error("refusing existing private V8 request view")
    effective_inner_path.write_text(
        json.dumps(effective_inner, indent=2, sort_keys=True,
                   ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    inner_path_for_run = effective_inner_path
    inner = effective_inner
    bound = v8._validate_request(inner, verify_result_stat=True)
    result_path = Path(bound["result_path"])
    if not _under(result_path, root) or result_path.is_symlink():
        raise PortableRebindV2Error("V8 result resolves outside relocated target root")
    pre = _full_stat(result_path)
    started = time.monotonic()
    result, result_sha, result_bytes = v8._read_result(result_path, int(bound["max_result_bytes"]))
    post = _full_stat(result_path)
    if pre != post:
        raise PortableRebindV2Error("result target stat changed during one-pass JSON read")
    if result_sha != bound["result_sha256"] or result_bytes != bound["result_bytes"]:
        raise PortableRebindV2Error("result target SHA/bytes differ from request")
    mode = str(request.get("semantic_mode", "strict_v12"))
    if mode != "strict_v12":
        raise PortableRebindV2Error("production V2 run requires strict_v12 semantic mode")
    _marker_file, _marker_request, scope = v12._load_marker(inner_path_for_run)
    old_scope = v12._ACTIVE_SCOPE
    try:
        v12._ACTIVE_SCOPE = scope
        summary = v12._validate_result_v12(result, bound, result_sha, result_bytes)
    finally:
        v12._ACTIVE_SCOPE = old_scope
    score = evaluator._score_typed_result(result, frozen_value)
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA, "status": "PASS_RELOCATED_V8_V12_TYPED_SCORER",
        "request": {"path": str(overlay_path), "file_sha256": _sha(overlay_path)},
        "inner_request": {"target_relative_path": str(inner_path.relative_to(root)),
                          "effective_target_relative_path": str(inner_path_for_run.relative_to(root)),
                          "file_sha256": _sha(inner_path),
                          "effective_file_sha256": _sha(inner_path_for_run),
                          "canonical_sha256": inner.get("sha256")},
        "result_source": {"target_relative_path": str(result_path.relative_to(root)),
                           "sha256": result_sha, "bytes": result_bytes,
                           "pre_stat": pre, "post_stat": post, "pre_post_stat_equal": True,
                           "read_phase": "AFTER_PARENT_GUARD"},
        "v12_summary": summary, "typed_operator_score": score,
        "rebased_contract_views": {
            "v12_sidecar": {"target_relative_path": str(rebased_sidecar.relative_to(root)),
                             "source_sha256": sidecar_source_sha, "target_sha256": _sha(rebased_sidecar)},
            "frozen_v15": {"target_relative_path": str(rebased_frozen.relative_to(root)),
                            "source_sha256": frozen_source_sha, "target_sha256": _sha(rebased_frozen)},
        },
        "runtime_modules": {
            role: {"path": str(path), "module_file": str(path), "sha256": _sha(path)}
            for role, path in runtime.items()
            if role not in {"literal_python", "pyvenv_cfg", "frozen_v15", "v12_sidecar",
                            "producer_nested_report"}
        },
        "execution": {"v8_validator": True, "v12_validator": True, "typed_scorer": True,
                       "model_invoked": False, "cfd_invoked": False,
                       "hdf5_or_bi4_content_read": False, "raw_opened": False,
                       "elapsed_wall_seconds": time.monotonic() - started},
        "source_fallback": "REJECT", "ledger_mutated": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "portable_cold_replay_credit": "NOT_CLAIMED",
    }
    report["sha256"] = _canonical(report)
    if output_path.exists() or output_path.is_symlink():
        raise PortableRebindV2Error(f"refusing existing V2 report: {output_path}")
    if not _under(output_path, root):
        raise PortableRebindV2Error("V2 report is outside relocated root")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True,
                                      ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    return report


def _drain_child(child: subprocess.Popen[bytes], *, max_wall: float,
                 stdout_path: Path, stderr_path: Path) -> tuple[int, dict[str, Any]]:
    selector = selectors.DefaultSelector()
    streams: dict[int, tuple[Any, bytearray, int, Path]] = {}
    finished: dict[int, tuple[bytearray, int, Path]] = {}
    for stream, path in ((child.stdout, stdout_path), (child.stderr, stderr_path)):
        if stream is None:
            continue
        selector.register(stream, selectors.EVENT_READ)
        streams[stream.fileno()] = (stream, bytearray(), 0, path)
    started = time.monotonic()
    timed_out = False
    while streams:
        remaining = max_wall - (time.monotonic() - started)
        if remaining <= 0:
            timed_out = True
            break
        for key, _ in selector.select(min(0.25, remaining)):
            stream = key.fileobj
            chunk = stream.read1(64 * 1024) if hasattr(stream, "read1") else stream.read(64 * 1024)
            fd = stream.fileno()
            if not chunk:
                selector.unregister(stream)
                stream.close()
                current, tail, total, path = streams[fd]
                finished[fd] = (tail, total, path)
                # Remove the closed pipe from the live set.  Keeping the
                # descriptor in ``streams`` would make the selector loop
                # wait until the deadline even after the child has exited.
                del streams[fd]
                continue
            current, tail, total, path = streams[fd]
            total += len(chunk)
            tail.extend(chunk)
            if len(tail) > ROLLING_TAIL_BYTES:
                del tail[:-ROLLING_TAIL_BYTES]
            streams[fd] = (current, tail, total, path)
    if timed_out:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=5.0)
    else:
        child.wait(timeout=max(1.0, max_wall))
    totals: dict[str, int] = {}
    completed: list[tuple[bytearray, int, Path]] = list(finished.values())
    for _fd, (stream, tail, total, path) in list(streams.items()):
        try:
            selector.unregister(stream)
        except Exception:
            pass
        stream.close()
        completed.append((tail, total, path))
    # Keep only a bounded terminal tail and record total bytes separately.
    for tail, total, path in completed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(tail))
        totals["stdout_bytes" if path == stdout_path else "stderr_bytes"] = total
    selector.close()
    return child.returncode if child.returncode is not None else 1, {
        "timed_out": timed_out,
        "stdout_bytes": totals.get("stdout_bytes", 0),
        "stderr_bytes": totals.get("stderr_bytes", 0),
        "stdout_tail_bytes": stdout_path.stat().st_size if stdout_path.exists() else 0,
        "stderr_tail_bytes": stderr_path.stat().st_size if stderr_path.exists() else 0,
        "rolling_tail_bytes": ROLLING_TAIL_BYTES,
    }


def run_guard(*, request_path: Path | str, output_relative: str,
              parent_pid: int, python_path: Path | str, max_wall_seconds: float) -> dict[str, Any]:
    if os.getppid() != int(parent_pid):
        raise PortableRebindV2Error("portable V2 guard is not under declared parent")
    _set_pdeathsig()
    checked = validate_request_overlay(request_path)
    root = checked["root"]
    # ``checked["request"]`` is the decoded mapping.  The child CLI needs
    # the sealed file path so it can validate the exact bytes again; passing
    # the mapping through ``str()`` would turn it into an invalid filename
    # (and, worse, lose the request-file binding at the process boundary).
    overlay = checked["request_path"]
    output = _target(root, _safe_relative(output_relative, "V2 output"), required=False)
    if output.exists() or output.is_symlink():
        raise PortableRebindV2Error(f"refusing existing V2 output: {output}")
    stdout = root / (str(Path(output_relative).with_suffix(".stdout.log")))
    stderr = root / (str(Path(output_relative).with_suffix(".stderr.log")))
    for path in (stdout, stderr):
        _reject_symlink_components(path, root)
        if path.exists() or path.is_symlink():
            raise PortableRebindV2Error(f"refusing existing V2 log: {path}")
    interpreter = _absolute(python_path)
    if interpreter.is_symlink() or not interpreter.is_file():
        raise PortableRebindV2Error("literal interpreter must be a regular copied executable")
    # Use the sealed, relocated V2 entrypoint.  ``SCRIPT`` is retained only
    # for the builder/CLI used by the parent; it is forbidden as a child
    # runtime dependency once the bundle is relocated.
    copied_entrypoint = checked["runtime_paths"]["portable_rebind_v2_entrypoint"]
    command = [str(interpreter), "-B", "-I", str(copied_entrypoint), "worker",
               "--request", str(overlay), "--output", str(output),
               "--parent-pid", str(os.getpid())]
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[key] = "1"
    child = subprocess.Popen(command, cwd=str(root), env=environment,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True, close_fds=True)
    old_term = signal.getsignal(signal.SIGTERM)
    old_int = signal.getsignal(signal.SIGINT)
    def _cancel(signum: int, _frame: Any) -> None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        raise KeyboardInterrupt(f"portable V2 guard cancelled by signal {signum}")
    signal.signal(signal.SIGTERM, _cancel)
    signal.signal(signal.SIGINT, _cancel)
    try:
        returncode, stream_info = _drain_child(child, max_wall=float(max_wall_seconds),
                                                stdout_path=stdout, stderr_path=stderr)
    except KeyboardInterrupt as error:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=5.0)
        raise PortableRebindV2Error(str(error)) from error
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)
    if stream_info["timed_out"]:
        raise PortableRebindV2Error("V2 child exceeded bounded deadline")
    if returncode != 0:
        tail = stderr.read_text(encoding="utf-8", errors="replace") if stderr.exists() else ""
        raise PortableRebindV2Error(f"V2 child failed with return code {returncode}: {tail[-1000:]}")
    report = _json(output, "V2 child report")
    if report.get("status") != "PASS_RELOCATED_V8_V12_TYPED_SCORER":
        raise PortableRebindV2Error("V2 child report is not a successful V8/V12/scorer result")
    receipt: dict[str, Any] = {
        "schema": "ds02.stage2.f2-typed-only-portable-rebind-guard-receipt.v2",
        "status": "COMPLETE_RELOCATED_TYPED_ONLY_V2",
        "request_file_sha256": _sha(overlay), "report_sha256": _sha(output),
        "report_target_relative_path": str(output.relative_to(root)),
        "stdout_target_relative_path": str(stdout.relative_to(root)),
        "stderr_target_relative_path": str(stderr.relative_to(root)),
        "stream_accounting": stream_info, "child_returncode": returncode,
        "parent_death_signal": "SIGTERM", "source_fallback": "REJECT",
        "ledger_mutated": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "portable_cold_replay_credit": "NOT_CLAIMED",
    }
    receipt["sha256"] = _canonical(receipt)
    receipt_path = output.with_suffix(".guard-receipt.json")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise PortableRebindV2Error(f"refusing existing V2 receipt: {receipt_path}")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--contract", type=Path, required=True)
    build.add_argument("--request-role", required=True)
    build.add_argument("--request-target-relative", required=True)
    build.add_argument("--request-id", required=True)
    build.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--request", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output-relative", required=True)
    run.add_argument("--python", type=Path, required=True)
    run.add_argument("--parent-pid", type=int, required=True)
    run.add_argument("--max-wall-seconds", type=float, required=True)
    worker = sub.add_parser("worker")
    worker.add_argument("--request", type=Path, required=True)
    worker.add_argument("--output", type=Path, required=True)
    worker.add_argument("--parent-pid", type=int, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request_overlay(contract_path=args.contract, request_role=args.request_role,
                                          output=args.output, request_target_relative=args.request_target_relative,
                                          request_id=args.request_id)
        elif args.command == "validate":
            value = validate_request_overlay(args.request)
        elif args.command == "worker":
            _set_pdeathsig()
            value = _worker_run(_absolute(args.request), _absolute(args.output), args.parent_pid)
        else:
            value = run_guard(request_path=args.request, output_relative=args.output_relative,
                              parent_pid=args.parent_pid, python_path=args.python,
                              max_wall_seconds=args.max_wall_seconds)
        print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (PortableRebindV2Error, V1.PortableRebindError, OSError, ValueError) as error:
        print(f"typed-only portable rebind V2: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

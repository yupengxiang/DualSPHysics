#!/usr/bin/env python3
"""Forward V50 onto a copied-module V51 worker boundary.

ROOT122 showed a real, useful failure after the 8.6 GB source copy: the
native worker request still contained the original worktree paths for
``v14_operator`` (and its v15/v16/converter siblings).  V38 quite correctly
rejected that path before opening a BI4 frame.  V51 keeps the V50/V45
scientific and accounting code immutable and fixes only the metadata edge:
the V40 native request's module bindings are rebound to the copied
``target_root/sources/*`` files whose SHA/byte identities are already present
in the parent request.  V38 still creates canonical aliases in the copied
worker directory and the private process still has no source-worktree
fallback.

``build_forward`` reads bounded JSON/code metadata only.  ``run`` is an
additive launch entry for a future parent guard; this module does not start a
worker by itself.  It preserves the literal pinned ``.venv/bin/python``
argv[0].  Scientific qualification remains UNKNOWN.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V45_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v45.py"
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v51-forward.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_JSON_BYTES = 8 * 1024 * 1024

# These are module names in the V2 native request, not necessarily the names
# of the executor runtime roles.  Their actionable files are copied into the
# source-entry target directory by V34 before V40 makes the request.
MODULE_SOURCE_ROLES = {
    "raw_converter": "raw_converter",
    "v14_operator": "v14_operator",
    "v15_operator": "v15_operator",
    "v16_operator": "v16_operator",
}


class PortableV51Error(RuntimeError):
    pass


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str, *, max_bytes: int | None = None) -> str:
    target = Path(path).expanduser()
    if max_bytes is not None and target.stat().st_size > max_bytes:
        raise PortableV51Error(f"refusing oversized metadata file: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise PortableV51Error(f"{role} must be a lowercase SHA-256")
    return value


def _absolute(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise PortableV51Error(f"{role} must be an absolute path")
    return Path(value).expanduser()


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _absolute(str(path), role)
    if target.is_symlink() or not target.is_file():
        raise PortableV51Error(f"{role} is not a regular non-symlink file: {target}")
    if target.stat().st_size > MAX_JSON_BYTES:
        raise PortableV51Error(f"{role} exceeds the bounded JSON limit: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableV51Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV51Error(f"{role} must be a JSON object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = _absolute(str(path), "output")
    if target.exists() or target.is_symlink():
        raise PortableV51Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True,
                  allow_nan=False)
        stream.write("\n")
    return target


def _safe_relative(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise PortableV51Error(f"{role} must be a relative target path")
    path = Path(value)
    if ".." in path.parts or str(path) != value:
        raise PortableV51Error(f"{role} escapes its copied root")
    return value


def _load_v45() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_bound_f2_portable_executor_v45_for_v51", V45_SCRIPT)
    if spec is None or spec.loader is None:
        raise PortableV51Error(f"cannot load V45 runtime: {V45_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request(path: Path | str) -> tuple[Path, dict[str, Any]]:
    target, value = _json(path, "V50 executor request")
    if value.get("schema") != V34_SCHEMA:
        raise PortableV51Error("V50 executor schema differs")
    if value.get("sha256") != canonical_sha(value):
        raise PortableV51Error("V50 executor canonical SHA differs")
    if value.get("role") != "DEVELOPMENT" or value.get("model_invoked") is not False:
        raise PortableV51Error("V50 executor is not model-free DEVELOPMENT")
    if value.get("cfd_invoked") is not False or value.get("qualification") != UNKNOWN:
        raise PortableV51Error("V50 executor qualification/CFD state differs")
    if not isinstance(value.get("forward_v50"), Mapping):
        raise PortableV51Error("V50 forward marker is missing")
    roots = value.get("fresh_roots")
    if not isinstance(roots, Mapping):
        raise PortableV51Error("V50 fresh roots are missing")
    return target, value


def _source_index(value: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = value.get("source_entries")
    if not isinstance(rows, list):
        raise PortableV51Error("V50 source_entries are missing")
    found: dict[str, dict[str, Any]] = {}
    for number, raw in enumerate(rows):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("role"), str):
            raise PortableV51Error(f"source_entries[{number}] is malformed")
        role = str(raw["role"])
        if role in MODULE_SOURCE_ROLES.values():
            if role in found:
                raise PortableV51Error(f"module source role is not unique: {role}")
            relative = _safe_relative(raw.get("target_relative_path"), f"source_entries[{number}].target_relative_path")
            expected = _sha(raw.get("sha256"), f"source_entries[{number}].sha256")
            bytes_value = raw.get("bytes")
            if isinstance(bytes_value, bool) or not isinstance(bytes_value, int) or bytes_value < 0:
                raise PortableV51Error(f"source_entries[{number}].bytes is malformed")
            found[role] = {
                "role": role, "source_path_provenance": raw.get("path"),
                "target_relative_path": relative, "sha256": expected,
                "bytes": int(bytes_value),
                "source_mode_bits": raw.get("source_mode_bits"),
            }
    missing = set(MODULE_SOURCE_ROLES.values()).difference(found)
    if missing:
        raise PortableV51Error(f"V50 module source roles are missing: {sorted(missing)}")
    return found


def module_rebinding_plan(request: Mapping[str, Any], target_root: Path | str) -> dict[str, dict[str, Any]]:
    """Return copied-source targets for V2 module bindings without opening them.

    This is intentionally metadata-only.  The target is checked for existence
    and SHA only by the future parent-owned ``run`` boundary, after its
    reservation.  The builder never falls back to ``source_path_provenance``.
    """
    target = _absolute(str(target_root), "target_root")
    sources = _source_index(request)
    result: dict[str, dict[str, Any]] = {}
    for module_role, source_role in MODULE_SOURCE_ROLES.items():
        row = dict(sources[source_role])
        copied = target / row["target_relative_path"]
        result[module_role] = {
            "module_role": module_role,
            "source_role": source_role,
            "source_path_provenance": row["source_path_provenance"],
            "target_relative_path": row["target_relative_path"],
            "target_path": str(copied),
            "expected_sha256": row["sha256"],
            "expected_bytes": row["bytes"],
            "content_verification_phase": "AFTER_PARENT_RESERVATION",
            "source_path_fallback": "FORBIDDEN",
        }
    return result


def build_forward(*, v50_request: Path | str, output_request: Path | str,
                  target_root: Path | str | None = None,
                  output_root: Path | str | None = None) -> dict[str, Any]:
    """Build an additive V51 request; no payload is opened or hashed."""
    source_path, source = _request(v50_request)
    roots = source["fresh_roots"]
    target = _absolute(str(target_root or roots.get("target_root")), "target_root")
    output = _absolute(str(output_root or roots.get("output_root")), "output_root")
    if target == output:
        raise PortableV51Error("V51 target/output roots must be distinct")
    if target == Path(str(roots.get("target_root"))) or output == Path(str(roots.get("output_root"))):
        raise PortableV51Error("V51 cannot reuse V50 target/output roots")
    plan = module_rebinding_plan(source, target)
    value = copy.deepcopy(source)
    runtime = value.get("runtime_sources")
    if not isinstance(runtime, list):
        raise PortableV51Error("V50 runtime_sources are missing")
    if any(isinstance(row, Mapping) and row.get("role") == "executor_v51" for row in runtime):
        raise PortableV51Error("executor_v51 is already bound")
    info = SCRIPT.stat()
    runtime.append({
        "role": "executor_v51", "path": str(SCRIPT),
        "target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v51.py",
        "bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
        "mode_bits": int(stat.S_IMODE(info.st_mode)), "sha256": sha256_file(SCRIPT),
        "original_path_fallback": "FORBIDDEN",
    })
    execution = dict(value.get("execution", {}))
    command = list(execution.get("command", []))
    script_positions = [index for index, item in enumerate(command)
                        if isinstance(item, str) and Path(item).name in {
                            "ds_data02_stage2_f2_portable_executor_v45.py",
                            "ds_data02_stage2_f2_portable_executor_v50.py",
                            "ds_data02_stage2_f2_portable_executor_v41.py",
                        }]
    if len(script_positions) != 1:
        raise PortableV51Error("V50 command has no unique V45/V50 executor script operand")
    # This is a provenance command template.  The parent copies the script to
    # runtime/executor before launch; no worktree path is used as an action.
    command[script_positions[0]] = "<target_root>/runtime/executor/ds_data02_stage2_f2_portable_executor_v51.py"
    execution.update({
        "command": command,
        "copied_module_rebinding": "V2 native request modules -> target_root/sources/*",
        "original_path_fallback": "FORBIDDEN",
        "module_content_hash_phase": "AFTER_PARENT_RESERVATION",
    })
    value["execution"] = execution
    value["fresh_roots"] = {"target_root": str(target), "output_root": str(output)}
    value["request_id"] = str(value.get("request_id", "f2-s1-v50")) + "-v51-module-rebind"
    value["forward_v51"] = {
        "schema": FORWARD_SCHEMA,
        "previous_request": {"path": str(source_path), "physical_sha256": sha256_file(source_path, max_bytes=MAX_JSON_BYTES),
                              "canonical_sha256": source["sha256"]},
        "module_rebinding": plan,
        "binding_scope": "V40 base native request only; V38 canonical aliases remain in copied worker directory",
        "target_source_root": str(target),
        "source_path_fallback": "FORBIDDEN",
        "copy_and_content_hash_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
        "payload_read_during_build": False,
        "payload_hashes_computed_during_build": False,
        "failure_fixed": "V38 module bindings no longer point at consumer worktree after copy",
        "qualification": dict(UNKNOWN),
    }
    value["status"] = "READY_FOR_PARENT_STAGE2_GUARD"
    value["raw_opened"] = False; value["hdf5_opened"] = False
    value["model_invoked"] = False; value["cfd_invoked"] = False
    value["qualification"] = dict(UNKNOWN)
    value["sha256"] = canonical_sha(value)
    out = _write_new(output_request, value)
    return {"status": value["status"], "request": str(out),
            "request_sha256": sha256_file(out, max_bytes=MAX_JSON_BYTES),
            "module_roles": sorted(plan), "payload_read": False,
            "qualification": dict(UNKNOWN)}


def _target_module_bindings(outer_request: Mapping[str, Any], base_request: Path,
                            target_root: Path) -> dict[str, dict[str, Any]]:
    """Resolve V2 module rows to copied source entries after the copy."""
    _, base = _json(base_request, "V40 native base request")
    modules = base.get("modules")
    if not isinstance(modules, Mapping):
        raise PortableV51Error("V40 native base request has no modules closure")
    plan = module_rebinding_plan(outer_request, target_root)
    result: dict[str, dict[str, Any]] = {}
    for module_role, item in plan.items():
        raw = modules.get(module_role)
        if not isinstance(raw, Mapping):
            raise PortableV51Error(f"V40 native base request module is missing: {module_role}")
        expected = _sha(raw.get("sha256"), f"modules.{module_role}.sha256")
        if expected != item["expected_sha256"]:
            raise PortableV51Error(f"module {module_role} SHA differs from copied source entry")
        target = Path(item["target_path"])
        if not target.is_file() or target.is_symlink():
            raise PortableV51Error(f"copied module target is missing: {target}")
        if target.stat().st_size != item["expected_bytes"] or sha256_file(target) != expected:
            raise PortableV51Error(f"copied module target content differs: {module_role}")
        result[module_role] = {
            "role": module_role,
            "module": {
                "v14_operator": "ds_data02_stage2_f2_replay_v14.py",
                "v15_operator": "ds_data02_stage2_f2_replay_v15.py",
                "v16_operator": "ds_data02_stage2_f2_flux_v16.py",
                "raw_converter": "ds_data02_f5_bi4.py",
            }[module_role],
            "path": str(target), "sha256": expected,
            "bytes": int(target.stat().st_size),
            "source_path_fallback": "FORBIDDEN",
            "copied_target_binding": dict(item),
        }
    return result


def _rebind_written_base(v45: Any, outer_request: Mapping[str, Any], base_path: Path,
                         target_root: Path) -> None:
    """Rebind the newly written V40 request before the native worker opens it."""
    _, value = _json(base_path, "new V40 native base request")
    modules = value.get("modules")
    if not isinstance(modules, dict):
        raise PortableV51Error("new V40 native base request modules are missing")
    plan = module_rebinding_plan(outer_request, target_root)
    for role, item in plan.items():
        raw = modules.get(role)
        if not isinstance(raw, dict):
            raise PortableV51Error(f"new V40 native module is missing: {role}")
        old = {key: raw.get(key) for key in ("path", "resolved_source_path", "sha256", "bytes")}
        raw["source_path_provenance"] = old
        raw["path"] = item["target_path"]
        raw["resolved_source_path"] = item["target_path"]
        raw["sha256"] = item["expected_sha256"]
        raw["bytes"] = item["expected_bytes"]
        raw["source_path_fallback"] = "FORBIDDEN"
    value["v51_module_rebinding"] = {"schema": FORWARD_SCHEMA,
                                      "plan": plan,
                                      "content_verified_after_copy": True,
                                      "source_path_fallback": "FORBIDDEN"}
    value["sha256"] = v45.canonical_sha(value)
    with base_path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True,
                  allow_nan=False)
        stream.write("\n")


def run(request_path: Path | str, *, io_slot_approved: bool,
        parent_pid: int | None = None, evaluator_proof: Path | None = None,
        max_wall_seconds: float | None = None) -> dict[str, Any]:
    """Run V45 only after a parent guard; V51 fixes copied module paths."""
    request_path, outer = _request(request_path)
    target_root = _absolute(str(outer["fresh_roots"]["target_root"]), "target_root")
    v45 = _load_v45()
    original_bindings = v45.V41.V38._module_bindings
    original_make = v45.V41._make_v40_engine_inputs

    def rebound(base_request: Path | str) -> dict[str, dict[str, Any]]:
        return _target_module_bindings(outer, Path(base_request), target_root)

    def make_inputs(request_value: Mapping[str, Any], output: Path, base_path: Path) -> dict[str, Any]:
        state = original_make(request_value, output, base_path)
        _rebind_written_base(v45, outer, Path(state["base"]), target_root)
        return state

    v45.V41.V38._module_bindings = rebound
    v45.V41._make_v40_engine_inputs = make_inputs
    try:
        return v45.run(request_path, io_slot_approved=io_slot_approved,
                       parent_pid=parent_pid, evaluator_proof=evaluator_proof,
                       max_wall_seconds=max_wall_seconds)
    finally:
        v45.V41.V38._module_bindings = original_bindings
        v45.V41._make_v40_engine_inputs = original_make


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-forward")
    build.add_argument("--v50-request", type=Path, required=True)
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
            result = build_forward(v50_request=args.v50_request, output_request=args.output_request,
                                   target_root=args.target_root, output_root=args.output_root)
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved,
                         parent_pid=args.parent_pid, evaluator_proof=args.evaluator_proof,
                         max_wall_seconds=args.max_wall_seconds)
    except (PortableV51Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v51: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2, default=str))
    return 1 if str(result.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())

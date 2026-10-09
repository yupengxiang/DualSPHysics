#!/usr/bin/env python3
"""Build a parent-v3-compatible V50 request from the V49 metadata closure.

V49 is kept immutable.  This forward builder makes the smallest parent
boundary changes needed by the consumed parent-v3 runner: the child status is
the exact v34 status, the executor binding keeps its schema/canonical SHA, and
the existing storage scope is merged rather than replaced.  Source and
runtime rows are stat-checked only; payload content hashing remains a
post-reservation operation of the parent guard.

The terminal sealer, fresh V16 proof consumer, and no-model evaluator are
explicit arguments.  There is no default path to a possibly different
worktree, which makes a missing root-side dependency fail before a copy.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.f2-portable-executor-parent-request.v3"
EXECUTOR_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
V50_EXECUTOR_STATUS = "READY_FOR_PARENT_STAGE2_GUARD"
V50_FORWARD_SCHEMA = "ds02.stage2.f2-portable-parent-v50-closure.v1"
V50_EXECUTOR_FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v50-forward.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_WALL_SECONDS = 6000.0
DEFAULT_HOME_RECEIPT_BYTES = 64 * 1024
DEFAULT_EXTERNAL_MIN_FREE_BYTES = 1
DEFAULT_TYPED_OUTPUT_BYTES = 2 * 1024 * 1024 * 1024


class ParentV50Error(RuntimeError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _file(value: Any, role: str, *, max_bytes: int = MAX_METADATA_BYTES) -> Path:
    if not isinstance(value, (str, Path)):
        raise ParentV50Error(f"{role} path is missing")
    target = Path(value).expanduser()
    if target.is_symlink() or not target.is_file():
        raise ParentV50Error(f"{role} must be a regular non-symlink file: {target}")
    if target.stat().st_size > max_bytes:
        raise ParentV50Error(f"{role} exceeds metadata bound: {target}")
    return target


def _source_file(value: Any, role: str, *, allow_symlink: bool = False) -> Path:
    """Validate a source closure path using stat only, regardless of size.

    Raw/HDF5 rows can be multi-gigabyte inputs.  The V50 parent builder must
    preserve their declared bytes and defer content hashing to the same-parent
    post-reservation phase; a JSON-size limit here would reject valid closure
    metadata before the guard can do that work.
    """
    if not isinstance(value, (str, Path)):
        raise ParentV50Error(f"{role} path is missing")
    target = Path(value).expanduser()
    if (target.is_symlink() and not allow_symlink) or not target.is_file():
        raise ParentV50Error(f"{role} must be a regular non-symlink file: {target}")
    return target


def _load(path: Path | str, role: str) -> dict[str, Any]:
    target = _file(path, role)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ParentV50Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise ParentV50Error(f"{role} must be an object")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise ParentV50Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True,
                  allow_nan=False)
        stream.write("\n")
    return target


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise ParentV50Error(f"{role} must be a lowercase SHA-256")
    return value


def _stat(path: Path, role: str, *, allow_symlink: bool = False) -> dict[str, int]:
    info = path.stat()
    if (path.is_symlink() and not allow_symlink) or not stat.S_ISREG(info.st_mode):
        raise ParentV50Error(f"{role} is not a regular non-symlink file")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode))}


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _fresh(path: Path | str, role: str, *, under: Path | None = None) -> Path:
    value = Path(path).expanduser()
    if not value.is_absolute() or value.exists() or value.is_symlink():
        raise ParentV50Error(f"{role} must be a fresh absolute namespace: {value}")
    if under is not None and not _under(value, under):
        raise ParentV50Error(f"{role} is outside the bound filesystem: {value}")
    return value


def _validate_source_closure(executor: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[tuple[str, Mapping[str, Any]]] = []
    # source_entries and runtime_sources can deliberately install the same
    # immutable runtime file at one target path.  Only differing content may
    # not collide; this mirrors the consumed v34 closure semantics.
    target_bindings: dict[str, tuple[str, str, int]] = {}
    # Match V49's copy accounting: one immutable content identity is copied
    # once even when source/runtime roles expose it through two paths.
    unique: dict[tuple[str, int], dict[str, Any]] = {}
    for section in ("source_entries", "runtime_sources"):
        values = executor.get(section)
        if not isinstance(values, list) or not values:
            raise ParentV50Error(f"executor.{section} is missing")
        for index, raw in enumerate(values):
            if not isinstance(raw, Mapping):
                raise ParentV50Error(f"executor.{section}[{index}] is malformed")
            rows.append((section, raw))
    for section, raw in rows:
        role = str(raw.get("role", ""))
        allow_symlink = section == "runtime_sources" and role == "python_executable"
        path = _source_file(raw.get("path"), f"executor.{section}.path",
                            allow_symlink=allow_symlink)
        digest = _sha(raw.get("sha256"), f"executor.{section}.sha256")
        raw_bytes = raw.get("bytes")
        if isinstance(raw_bytes, bool):
            raise ParentV50Error(f"executor.{section}.bytes is malformed")
        try:
            declared_bytes = int(raw_bytes)
        except (TypeError, ValueError) as error:
            raise ParentV50Error(f"executor.{section}.bytes is malformed") from error
        observed = _stat(path, f"executor.{section}.path", allow_symlink=allow_symlink)
        if observed["bytes"] != declared_bytes:
            raise ParentV50Error(f"executor.{section}.bytes differs: {path}")
        relative = raw.get("target_relative_path")
        if relative is not None:
            if not isinstance(relative, str) or not relative or relative.startswith("/"):
                raise ParentV50Error(f"executor.{section}.target_relative_path is malformed")
            binding = (str(path), digest, declared_bytes)
            if relative in target_bindings and target_bindings[relative] != binding:
                raise ParentV50Error(f"duplicate target_relative_path: {relative}")
            target_bindings[relative] = binding
        unique[(digest, declared_bytes)] = {
            "section": section, "role": str(raw.get("role", "")),
            "path": str(path), "sha256": digest, "bytes": declared_bytes,
        }
    forward = executor.get("forward_v50")
    if not isinstance(forward, Mapping) or forward.get("schema") != V50_EXECUTOR_FORWARD_SCHEMA:
        raise ParentV50Error("executor lacks V50 forward marker")
    declared = forward.get("source_closure", {}).get("deduplicated_copy_bytes") \
        if isinstance(forward.get("source_closure"), Mapping) else None
    total = sum(int(item["bytes"]) for item in unique.values())
    if isinstance(declared, bool) or not isinstance(declared, int) or declared != total:
        raise ParentV50Error(f"executor source closure bytes differ: {declared} != {total}")
    return {"declared_item_count": len(rows), "deduplicated_item_count": len(unique),
            "deduplicated_copy_bytes": total, "target_relative_path_count": len(target_bindings),
            "content_read": False, "payload_hashes_computed": False}


def _validate_base(path: Path | str) -> tuple[Path, dict[str, Any]]:
    target = _file(path, "base parent request")
    value = _load(target, "base parent request")
    if value.get("schema") != SCHEMA or value.get("status") != "READY_FOR_PARENT_GUARD":
        raise ParentV50Error("base parent is not a consumed parent-v3 request")
    if value.get("sha256") != canonical_sha(value):
        raise ParentV50Error("base parent canonical SHA differs")
    if value.get("role") != "DEVELOPMENT" or value.get("qualification") != UNKNOWN \
            or value.get("model_invoked") is not False or value.get("cfd_invoked") is not False:
        raise ParentV50Error("base parent is not model-free DEVELOPMENT/UNKNOWN")
    for role in ("parent_resource_binding", "storage_scope", "execution",
                 "executor_request", "runtime_binding", "executor_script"):
        if not isinstance(value.get(role), Mapping):
            raise ParentV50Error(f"base parent.{role} is missing")
    return target, value


def _validate_executor(path: Path | str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    target = _file(path, "V50 executor request")
    value = _load(target, "V50 executor request")
    if value.get("schema") != EXECUTOR_SCHEMA or value.get("status") != V50_EXECUTOR_STATUS:
        raise ParentV50Error("executor is not the exact parent-v3 v34 status")
    if value.get("sha256") != canonical_sha(value):
        raise ParentV50Error("V50 executor canonical SHA differs")
    if value.get("role") != "DEVELOPMENT" or value.get("model_invoked") is not False \
            or value.get("cfd_invoked") is not False or value.get("qualification") != UNKNOWN:
        raise ParentV50Error("V50 executor must remain model-free DEVELOPMENT/UNKNOWN")
    execution = value.get("execution")
    if not isinstance(execution, Mapping) or execution.get("original_path_fallback") != "FORBIDDEN":
        raise ParentV50Error("V50 executor does not forbid original path fallback")
    roots = value.get("fresh_roots")
    if not isinstance(roots, Mapping):
        raise ParentV50Error("V50 executor fresh_roots is missing")
    target_root = Path(str(roots.get("target_root", ""))).expanduser()
    output_root = Path(str(roots.get("output_root", ""))).expanduser()
    if not target_root.is_absolute() or not output_root.is_absolute() \
            or target_root == output_root or target_root.exists() or output_root.exists():
        raise ParentV50Error("V50 executor fresh roots are invalid")
    closure = _validate_source_closure(value)
    return target, value, {"target_root": target_root, "output_root": output_root, "closure": closure}


def _replace_exact(value: Any, old: str, new: str) -> Any:
    if isinstance(value, dict):
        return {key: _replace_exact(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_exact(item, old, new) for item in value]
    if isinstance(value, str) and value == old:
        return new
    return value


def _add_binding(parent: dict[str, Any], role: str, path: Path) -> dict[str, Any]:
    info = _stat(path, role)
    row = {"role": role, "path": str(path), "sha256": sha256_file(path),
           **info, "immutable": True}
    rows = parent.setdefault("static_bindings", [])
    if not isinstance(rows, list):
        raise ParentV50Error("parent.static_bindings must be a list")
    rows[:] = [item for item in rows if not isinstance(item, Mapping) or item.get("role") != role]
    rows.append(row)
    return row


def build_parent(*, base_parent: Path | str, executor_request: Path | str,
                 parent_output: Path | str, target_root: Path | str,
                 output_root: Path | str, supervisor_output_root: Path | str,
                 home_receipt_path: Path | str, parent_attempt_id: str,
                 external_filesystem: Path | str, external_reservation_bytes: int,
                 home_receipt_bytes: int = DEFAULT_HOME_RECEIPT_BYTES,
                 external_min_free_bytes: int = DEFAULT_EXTERNAL_MIN_FREE_BYTES,
                 typed_output_budget_bytes: int = DEFAULT_TYPED_OUTPUT_BYTES,
                 max_wall_seconds: float = DEFAULT_MAX_WALL_SECONDS,
                 terminal_sealer: Path | str | None = None,
                 proof_consumer: Path | str | None = None,
                 evaluator: Path | str | None = None) -> dict[str, Any]:
    if not parent_attempt_id or "::" in parent_attempt_id:
        raise ParentV50Error("parent_attempt_id must be a fresh scoped identifier")
    if any(isinstance(value, bool) or int(value) <= 0 for value in
           (external_reservation_bytes, home_receipt_bytes, external_min_free_bytes,
            typed_output_budget_bytes)):
        raise ParentV50Error("storage budgets must be positive integers")
    if not isinstance(max_wall_seconds, (int, float)) or max_wall_seconds <= 0:
        raise ParentV50Error("max_wall_seconds must be positive")
    base_path, base = _validate_base(base_parent)
    executor_path, executor, detail = _validate_executor(executor_request)
    target = _fresh(target_root, "new target_root")
    output = _fresh(output_root, "new output_root")
    if target != detail["target_root"] or output != detail["output_root"]:
        raise ParentV50Error("parent target/output roots must match executor fresh_roots")
    external = Path(external_filesystem).expanduser()
    if not external.is_absolute() or not external.is_dir():
        raise ParentV50Error("external filesystem must be an existing directory")
    if not _under(target, external) or not _under(output, external):
        raise ParentV50Error("executor roots are outside external filesystem")
    supervisor = _fresh(supervisor_output_root, "supervisor output root", under=external)
    receipt = Path(home_receipt_path).expanduser()
    if not receipt.is_absolute() or receipt.exists() or receipt.is_symlink():
        raise ParentV50Error("home receipt must be a fresh absolute file")
    source_bytes = int(detail["closure"]["deduplicated_copy_bytes"])
    reserved_bytes = source_bytes + int(typed_output_budget_bytes)
    scratch = executor.get("execution", {}).get("decoder_scratch", {})
    scratch_bytes = int(scratch.get("max_frame_scratch_bytes", 0) or 0) if isinstance(scratch, Mapping) else 0
    reserved_bytes += scratch_bytes
    if reserved_bytes > int(external_reservation_bytes):
        raise ParentV50Error("external reservation does not cover source/scratch/output bound")
    for role, candidate in (("terminal sealer", terminal_sealer),
                            ("fresh proof consumer", proof_consumer),
                            ("no-model evaluator", evaluator)):
        if candidate is None:
            raise ParentV50Error(f"{role} path must be explicit; no worktree default is permitted")
        _file(candidate, role, max_bytes=MAX_METADATA_BYTES)
    parent = copy.deepcopy(base)
    old_executor_path = str(base["executor_request"].get("path", ""))
    parent["executor_request"] = {
        **dict(base["executor_request"]),
        "path": str(executor_path), "sha256": sha256_file(executor_path),
        "canonical_sha256": executor["sha256"], "schema": EXECUTOR_SCHEMA,
        "immutable": True,
    }
    for row in parent.get("static_bindings", []):
        if isinstance(row, dict) and row.get("role") == "executor_v34_request":
            row.update({"path": str(executor_path), "sha256": sha256_file(executor_path),
                        "canonical_sha256": executor["sha256"], "schema": EXECUTOR_SCHEMA,
                        **_stat(executor_path, "V50 executor request")})
    parent_resource = dict(parent["parent_resource_binding"])
    reservation_id = parent_attempt_id + "::f2-v50-parent-reservation"
    charge_id = parent_attempt_id + "::f2-v50-parent-charge"
    parent_resource.update({
        "attempt_id": parent_attempt_id, "reservation_id": reservation_id,
        "charge_id": charge_id, "allow_missing_parent": True,
        "same_parent_ledger": True, "ledger_reset": False, "no_new_data_root": True,
        "external_filesystem": str(external),
    })
    parent["parent_resource_binding"] = parent_resource
    accounting = dict(parent.get("accounting", {}))
    accounting.update({"attempt_id": parent_attempt_id, "reservation_id": reservation_id,
                       "charge_id": charge_id, "same_parent_ledger": True,
                       "allow_missing_parent": True,
                       "allow_missing_parent_scope": "fresh same-ledger V50 attempt only"})
    parent["accounting"] = accounting
    parent["attempt_id"] = parent_attempt_id + "::f2-v50-parent"
    storage = dict(parent.get("storage_scope", {}))
    storage.update({
        "external_filesystem": str(external), "supervisor_output_root": str(supervisor),
        "home_receipt_path": str(receipt), "home_receipt_bytes": int(home_receipt_bytes),
        "external_reservation_bytes": int(external_reservation_bytes),
        "source_copy_bytes": source_bytes, "external_min_free_bytes": int(external_min_free_bytes),
        "two_filesystem_charge_required": True, "new_namespace_absent_before_run": True,
        "declared_decoder_scratch_bytes": scratch_bytes,
        "declared_typed_output_budget_bytes": int(typed_output_budget_bytes),
        "payload_content_hash_phase": "after_same_parent_reservation",
    })
    parent["storage_scope"] = storage
    execution = copy.deepcopy(parent.get("execution", {}))
    execution = _replace_exact(execution, old_executor_path, str(executor_path))
    execution["max_wall_seconds"] = float(max_wall_seconds)
    execution["cpu_reservation_seconds"] = float(max_wall_seconds)
    execution["trace_path"] = str(supervisor / "os-trace-v34")
    execution["entry_clock"] = "parent-v50 entry before metadata validation/reservation"
    execution["reservation_order"] = "same-parent ledger reservation before source content SHA"
    parent["execution"] = execution
    sealer = _add_binding(parent, "terminal_sealer_v1", Path(terminal_sealer))
    proof = _add_binding(parent, "fresh_v16_proof_consumer_v11", Path(proof_consumer))
    evaluator_binding = _add_binding(parent, "no_model_evaluator_v4", Path(evaluator))
    builder_binding = _add_binding(parent, "parent_closure_builder_v50", SCRIPT)
    parent["v50_forward"] = {
        "schema": V50_FORWARD_SCHEMA,
        "base_parent": {"path": str(base_path), "physical_sha256": sha256_file(base_path),
                         "canonical_sha256": base["sha256"]},
        "executor": {"path": str(executor_path), "physical_sha256": sha256_file(executor_path),
                      "canonical_sha256": executor["sha256"]},
        "source_closure": detail["closure"],
        "target_root": str(target), "output_root": str(output),
        "supervisor_output_root": str(supervisor), "home_receipt_path": str(receipt),
        "terminal_sealer": sealer, "proof_consumer": proof,
        "evaluator": evaluator_binding, "builder": builder_binding,
        "fresh_product": {
            "producer_terminal_manifest": None, "new_v16_source_contract": None,
            "new_v16_result_sha256": None, "status": "DEFERRED_UNTIL_V50_PRODUCER_TERMINAL",
        },
        "historical_proof_inputs_forbidden": True,
        "content_read": False, "payload_hashes_computed": False,
        "qualification": dict(UNKNOWN),
    }
    parent["status"] = "READY_FOR_PARENT_GUARD"
    parent["role"] = "DEVELOPMENT"
    parent["model_invoked"] = False
    parent["cfd_invoked"] = False
    parent["raw_opened"] = False
    parent["hdf5_opened"] = False
    parent["qualification"] = dict(UNKNOWN)
    parent["sha256"] = canonical_sha(parent)
    output_path = _write_new(parent_output, parent)
    return {
        "schema": V50_FORWARD_SCHEMA, "status": "READY_FOR_PARENT_GUARD_V50",
        "parent_request": str(output_path), "parent_physical_sha256": sha256_file(output_path),
        "parent_canonical_sha256": parent["sha256"],
        "executor_request": str(executor_path), "executor_canonical_sha256": executor["sha256"],
        "declared_source_copy_bytes": source_bytes, "declared_external_reservation_bytes": int(external_reservation_bytes),
        "content_read": False, "payload_hashes_computed": False,
        "qualification": dict(UNKNOWN),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-parent", type=Path, required=True)
    parser.add_argument("--executor-request", type=Path, required=True)
    parser.add_argument("--parent-output", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--supervisor-output-root", type=Path, required=True)
    parser.add_argument("--home-receipt-path", type=Path, required=True)
    parser.add_argument("--parent-attempt-id", required=True)
    parser.add_argument("--external-filesystem", type=Path, required=True)
    parser.add_argument("--external-reservation-bytes", type=int, required=True)
    parser.add_argument("--home-receipt-bytes", type=int, default=DEFAULT_HOME_RECEIPT_BYTES)
    parser.add_argument("--external-min-free-bytes", type=int, default=DEFAULT_EXTERNAL_MIN_FREE_BYTES)
    parser.add_argument("--typed-output-budget-bytes", type=int, default=DEFAULT_TYPED_OUTPUT_BYTES)
    parser.add_argument("--max-wall-seconds", type=float, default=DEFAULT_MAX_WALL_SECONDS)
    parser.add_argument("--terminal-sealer", type=Path, required=True)
    parser.add_argument("--proof-consumer", type=Path, required=True)
    parser.add_argument("--evaluator", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = build_parent(
            base_parent=args.base_parent, executor_request=args.executor_request,
            parent_output=args.parent_output, target_root=args.target_root,
            output_root=args.output_root, supervisor_output_root=args.supervisor_output_root,
            home_receipt_path=args.home_receipt_path, parent_attempt_id=args.parent_attempt_id,
            external_filesystem=args.external_filesystem,
            external_reservation_bytes=args.external_reservation_bytes,
            home_receipt_bytes=args.home_receipt_bytes,
            external_min_free_bytes=args.external_min_free_bytes,
            typed_output_budget_bytes=args.typed_output_budget_bytes,
            max_wall_seconds=args.max_wall_seconds,
            terminal_sealer=args.terminal_sealer, proof_consumer=args.proof_consumer,
            evaluator=args.evaluator,
        )
    except (ParentV50Error, OSError, ValueError, TypeError) as error:
        print(f"parent V50: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build a fresh V49 parent request without opening scientific payloads.

V49 is the additive parent boundary for the V49 executor request.  It checks
the root source closure and the V4 decoder budget using declared SHA/stat
metadata, but does not hash or open BI4, HDF5, raw-frame, typed-product, or
result payloads.  The shared parent guard must repeat content hashing after
reservation.  This builder creates no ledger, reservation, process, or
scientific proof.

The request also carries a deferred terminal-sealer/proof/evaluator contract.
Those roles can consume only a new V49 producer terminal record and new V16
source contract; historical ROOT060/aabfb proof paths are explicitly barred.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
SCHEMA = "ds02.stage2.f2-portable-executor-parent-request.v3"
EXECUTOR_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-parent-v49-closure.v1"
V49_EXECUTOR_FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v49-forward.v1"
V49_OVERLAY_FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v49-forward.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 32 * 1024 * 1024
DEFAULT_DECODER_SCRATCH_BYTES = 512 * 1024 * 1024
DEFAULT_TYPED_OUTPUT_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_EXTERNAL_BUDGET_BYTES = 12 * 1024 * 1024 * 1024
DEFAULT_HOME_BUDGET_BYTES = 512 * 1024 * 1024


class ParentV49Error(RuntimeError):
    """Raised for an unsafe or incomplete V49 parent hand-off."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _absolute(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ParentV49Error(f"{role} must be an absolute path")
    path = Path(value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ParentV49Error(f"{role} must be an existing regular non-symlink file: {path}")
    return path


def _load_json(path: Path | str, role: str) -> dict[str, Any]:
    target = _absolute(str(path), role)
    if target.stat().st_size > MAX_METADATA_BYTES:
        raise ParentV49Error(f"{role} exceeds metadata-only bound: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ParentV49Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise ParentV49Error(f"{role} must contain an object")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise ParentV49Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise ParentV49Error(f"{role} must be a lowercase SHA-256")
    return value


def _stat(path: Path, role: str) -> dict[str, int]:
    info = path.stat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise ParentV49Error(f"{role} is not a regular non-symlink file: {path}")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode))}


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _fresh_root(value: Any, role: str) -> Path:
    # ``build_parent`` accepts Path objects while the JSON/CLI contract uses
    # strings.  Normalize without resolving: a fresh namespace must remain a
    # literal absolute destination and must not be silently remapped.
    raw = str(value) if isinstance(value, Path) else value
    if not isinstance(raw, str) or not raw.startswith("/"):
        raise ParentV49Error(f"{role} must be an absolute path")
    path = Path(raw).expanduser()
    if path.exists() or path.is_symlink():
        raise ParentV49Error(f"{role} must be a fresh namespace: {path}")
    return path


def _source_rows(executor: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for section in ("source_entries", "runtime_sources"):
        values = executor.get(section, [])
        if not isinstance(values, list):
            raise ParentV49Error(f"executor.{section} must be a list")
        for index, raw in enumerate(values):
            if not isinstance(raw, Mapping):
                raise ParentV49Error(f"executor.{section}[{index}] is malformed")
            rows.append((section, dict(raw)))
    if not rows:
        raise ParentV49Error("V49 executor has no declared source closure")
    return rows


def _validate_source_closure(executor: Mapping[str, Any]) -> dict[str, Any]:
    """Check path/stat/identity metadata; never content-hash payload rows."""
    rows = _source_rows(executor)
    target_paths: dict[str, tuple[str, str]] = {}
    unique: dict[tuple[str, str, int], dict[str, Any]] = {}
    payload_like = {".h5", ".hdf5", ".bi4", ".obi4", ".ibi4", ".xmf"}
    payload_bytes = 0
    for section, raw in rows:
        path = _absolute(raw.get("path"), f"executor.{section}.path")
        digest = _sha(raw.get("sha256"), f"executor.{section}.sha256")
        try:
            declared_bytes = int(raw.get("bytes", -1))
        except (TypeError, ValueError) as error:
            raise ParentV49Error(f"executor.{section}.bytes is invalid") from error
        actual = _stat(path, f"executor.{section}.path")
        if actual["bytes"] != declared_bytes:
            raise ParentV49Error(f"executor.{section}.bytes differs at {path}")
        relative = raw.get("target_relative_path")
        if relative is not None:
            if not isinstance(relative, str) or not relative or relative.startswith("/"):
                raise ParentV49Error(f"executor.{section}.target_relative_path is malformed")
            if relative in target_paths:
                raise ParentV49Error(f"duplicate target_relative_path: {relative}")
            target_paths[relative] = (section, str(raw.get("role", "")))
        key = (str(path), digest, declared_bytes)
        unique[key] = {"section": section, "role": str(raw.get("role", "")),
                       "path": str(path), "sha256": digest,
                       "bytes": declared_bytes, "stat": actual}
        if path.suffix.lower() in payload_like:
            payload_bytes += declared_bytes
    return {
        "declared_item_count": len(rows),
        "deduplicated_item_count": len(unique),
        "deduplicated_copy_bytes": sum(int(item["bytes"]) for item in unique.values()),
        "payload_declared_bytes": payload_bytes,
        "target_relative_path_count": len(target_paths),
        "content_read_during_builder": False,
        "payload_hashes_computed_during_builder": False,
        "items": list(unique.values()),
    }


def _validate_v49_executor(path: Path | str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    executor_path = _absolute(str(path), "V49 executor request")
    executor = _load_json(executor_path, "V49 executor request")
    if executor.get("schema") != EXECUTOR_SCHEMA:
        raise ParentV49Error("V49 executor schema differs")
    if executor.get("sha256") != canonical_sha(executor):
        raise ParentV49Error("V49 executor canonical SHA differs")
    forward = executor.get("forward_v49")
    if not isinstance(forward, Mapping) or forward.get("schema") != V49_EXECUTOR_FORWARD_SCHEMA:
        raise ParentV49Error("V49 executor forward marker is missing")
    scratch = executor.get("execution", {}).get("decoder_scratch") if isinstance(executor.get("execution"), Mapping) else None
    if not isinstance(scratch, Mapping):
        raise ParentV49Error("V49 decoder scratch contract is missing")
    if scratch.get("wrapper_schema") != "ds02.stage2.f2-native-raw-to-typed-label-scratch-wrapper.v4":
        raise ParentV49Error("V49 executor is not bound to the V4 scratch wrapper")
    if scratch.get("default_tmp_forbidden") is not True or scratch.get("cleanup_after_each_frame") is not True:
        raise ParentV49Error("V49 scratch default-temp/cleanup contract is incomplete")
    try:
        scratch_bytes = int(scratch["max_frame_scratch_bytes"])
        timeout = float(scratch["decoder_timeout_seconds"])
    except (KeyError, TypeError, ValueError) as error:
        raise ParentV49Error("V49 scratch byte/timeout values are malformed") from error
    if scratch_bytes <= 0 or timeout <= 0:
        raise ParentV49Error("V49 scratch byte/timeout values must be positive")
    roots = executor.get("fresh_roots")
    if not isinstance(roots, Mapping):
        raise ParentV49Error("V49 fresh_roots is missing")
    target = _fresh_root(roots.get("target_root"), "V49 target_root")
    output = _fresh_root(roots.get("output_root"), "V49 output_root")
    if target == output:
        raise ParentV49Error("V49 target_root and output_root must differ")
    overlay_binding = executor.get("v5_overlay_template")
    if not isinstance(overlay_binding, Mapping):
        raise ParentV49Error("V49 overlay binding is missing")
    overlay_path = _absolute(overlay_binding.get("path"), "V49 overlay")
    overlay_physical_sha = sha256_file(overlay_path)
    if overlay_physical_sha != _sha(overlay_binding.get("sha256"), "V49 overlay physical SHA"):
        raise ParentV49Error("V49 overlay physical SHA differs")
    overlay = _load_json(overlay_path, "V49 overlay")
    if overlay.get("sha256") != canonical_sha(overlay):
        raise ParentV49Error("V49 overlay canonical SHA differs")
    if overlay.get("sha256") != _sha(overlay_binding.get("canonical_sha256"), "V49 overlay canonical SHA"):
        raise ParentV49Error("V49 overlay canonical binding differs")
    marker = overlay.get("forward_v49")
    if not isinstance(marker, Mapping) or marker.get("schema") != V49_OVERLAY_FORWARD_SCHEMA:
        raise ParentV49Error("V49 overlay forward marker is missing")
    closure = _validate_source_closure(executor)
    declared_copy = forward.get("static_copy_bytes_after_rebind")
    if isinstance(declared_copy, bool) or not isinstance(declared_copy, int):
        raise ParentV49Error("V49 static_copy_bytes_after_rebind is missing")
    if int(declared_copy) != int(closure["deduplicated_copy_bytes"]):
        raise ParentV49Error("V49 declared copy bytes differ from source closure")
    return executor_path, executor, {
        "forward": dict(forward), "scratch_bytes": scratch_bytes,
        "decoder_timeout_seconds": timeout, "target_root": target,
        "output_root": output, "overlay_path": overlay_path,
        "overlay_physical_sha256": overlay_physical_sha,
        "overlay_canonical_sha256": overlay["sha256"], "closure": closure,
    }


def _validate_base_parent(path: Path | str) -> tuple[Path, dict[str, Any]]:
    base_path = _absolute(str(path), "base parent request")
    base = _load_json(base_path, "base parent request")
    if base.get("schema") != SCHEMA or base.get("status") != "READY_FOR_PARENT_GUARD":
        raise ParentV49Error("base parent is not a ready v3 parent request")
    if base.get("sha256") != canonical_sha(base):
        raise ParentV49Error("base parent canonical SHA differs")
    if base.get("qualification") != UNKNOWN or base.get("model_invoked") is not False:
        raise ParentV49Error("base parent must remain DEVELOPMENT/UNKNOWN")
    if not isinstance(base.get("parent_resource_binding"), Mapping):
        raise ParentV49Error("base parent resource binding is missing")
    return base_path, base


def _add_static_binding(parent: dict[str, Any], role: str, path: Path) -> None:
    info = _stat(path, role)
    row = {"role": role, "path": str(path), "sha256": sha256_file(path),
           **info, "immutable": True, "content_read_during_builder": True}
    rows = parent.setdefault("static_bindings", [])
    if not isinstance(rows, list):
        raise ParentV49Error("parent.static_bindings must be a list")
    rows[:] = [item for item in rows if not isinstance(item, Mapping) or item.get("role") != role]
    rows.append(row)


def _rebind_executor(parent: dict[str, Any], executor_path: Path, executor: Mapping[str, Any],
                     stat_record: Mapping[str, Any]) -> None:
    binding = {
        "path": str(executor_path), "sha256": sha256_file(executor_path),
        "canonical_sha256": executor["sha256"], **dict(stat_record),
        "role": "executor_v49_request",
    }
    parent["executor_request"] = binding
    rows = parent.setdefault("static_bindings", [])
    if not isinstance(rows, list):
        raise ParentV49Error("parent.static_bindings must be a list")
    for row in rows:
        if isinstance(row, dict) and row.get("role") == "executor_v34_request":
            row.update(binding)
            row["role"] = "executor_v49_request"


def build_parent(*, base_parent: Path | str, executor_request: Path | str,
                 parent_output: Path | str, target_root: Path | str,
                 output_root: Path | str, parent_attempt_id: str,
                 home_budget_bytes: int = DEFAULT_HOME_BUDGET_BYTES,
                 external_budget_bytes: int = DEFAULT_EXTERNAL_BUDGET_BYTES,
                 typed_output_budget_bytes: int = DEFAULT_TYPED_OUTPUT_BYTES,
                 terminal_sealer: Path | str | None = None,
                 proof_consumer: Path | str | None = None,
                 evaluator: Path | str | None = None) -> dict[str, Any]:
    if not parent_attempt_id or "::" in parent_attempt_id:
        raise ParentV49Error("parent_attempt_id must be a fresh scoped identifier")
    if min(home_budget_bytes, external_budget_bytes, typed_output_budget_bytes) <= 0:
        raise ParentV49Error("all filesystem budgets must be positive")
    base_path, base = _validate_base_parent(base_parent)
    executor_path, executor, detail = _validate_v49_executor(executor_request)
    target = _fresh_root(target_root, "new parent target_root")
    output = _fresh_root(output_root, "new parent output_root")
    if target != detail["target_root"] or output != detail["output_root"]:
        raise ParentV49Error(
            "parent target/output roots must exactly match the V49 executor fresh_roots"
        )
    parent_path = Path(parent_output).expanduser()
    if parent_path.exists() or parent_path.is_symlink():
        raise ParentV49Error(f"refusing existing parent output: {parent_path}")
    static_bytes = int(detail["closure"]["deduplicated_copy_bytes"])
    reserved_bytes = static_bytes + int(detail["scratch_bytes"]) + int(typed_output_budget_bytes)
    if reserved_bytes > int(external_budget_bytes):
        raise ParentV49Error(
            f"V49 declared copy+scratch+typed budget exceeds external budget: {reserved_bytes} > {external_budget_bytes}"
        )
    parent = copy.deepcopy(base)
    _rebind_executor(parent, executor_path, executor, _stat(executor_path, "V49 executor request"))
    resource = dict(parent.get("parent_resource_binding", {}))
    reservation_id = parent_attempt_id + "::v49-parent-reservation"
    charge_id = parent_attempt_id + "::v49-parent-charge"
    resource.update({"attempt_id": parent_attempt_id, "reservation_id": reservation_id,
                     "charge_id": charge_id, "allow_missing_parent": True,
                     "allow_missing_parent_scope": "fresh same-ledger V49 attempt only"})
    parent["parent_resource_binding"] = resource
    accounting = dict(parent.get("accounting", {}))
    accounting.update({"attempt_id": parent_attempt_id, "reservation_id": reservation_id,
                       "charge_id": charge_id, "allow_missing_parent": True,
                       "same_parent_ledger": True})
    parent["accounting"] = accounting
    parent["attempt_id"] = parent_attempt_id + "::v49-parent"
    parent["storage_scope"] = {
        "policy": "home_floor_plus_external_separate",
        "home_budget_bytes": int(home_budget_bytes),
        "external_budget_bytes": int(external_budget_bytes),
        "typed_output_budget_bytes": int(typed_output_budget_bytes),
        "declared_static_copy_bytes": static_bytes,
        "decoder_scratch_budget_bytes": int(detail["scratch_bytes"]),
        "declared_total_external_reservation_bytes": reserved_bytes,
        "target_root": str(target), "output_root": str(output),
        "source_content_hash_phase": "after_same_parent_reservation",
        "payload_content_read_during_builder": False,
        "payload_hashes_computed_during_builder": False,
    }
    parent["fresh_roots"] = {"target_root": str(target), "output_root": str(output)}
    parent["execution"] = dict(parent.get("execution", {}))
    parent["execution"].update({
        "executor_request_path": str(executor_path),
        "decoder_scratch_budget_bytes": int(detail["scratch_bytes"]),
        "decoder_timeout_seconds": float(detail["decoder_timeout_seconds"]),
        "original_path_fallback": "FORBIDDEN",
        "os_open_audit_required": True,
    })
    sealer_path = Path(terminal_sealer).expanduser() if terminal_sealer else SCRIPT_DIR / "ds_data02_stage2_f2_v47_terminal_sealer_v1.py"
    proof_path = Path(proof_consumer).expanduser() if proof_consumer else SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v11.py"
    evaluator_path = Path(evaluator).expanduser() if evaluator else SCRIPT_DIR / "ds_data02_stage2_f2_no_model_evaluator_v4.py"
    for role, path in (("terminal_sealer_v1", sealer_path),
                       ("fresh_v16_proof_consumer_v11", proof_path),
                       ("no_model_evaluator_v4", evaluator_path)):
        path = _absolute(str(path), role)
        _add_static_binding(parent, role, path)
    _add_static_binding(parent, "parent_builder_v49", SCRIPT)
    role_bindings = {
        str(row["role"]): {
            key: row[key] for key in ("path", "sha256", "bytes", "mtime_ns", "mode_bits")
            if key in row
        }
        for row in parent.get("static_bindings", [])
        if isinstance(row, Mapping) and isinstance(row.get("role"), str)
    }
    parent["v49_forward"] = {
        "schema": FORWARD_SCHEMA,
        "base_parent": {"path": str(base_path), "physical_sha256": sha256_file(base_path),
                         "canonical_sha256": base["sha256"]},
        "executor": {"path": str(executor_path), "physical_sha256": sha256_file(executor_path),
                      "canonical_sha256": executor["sha256"]},
        "overlay": {"path": str(detail["overlay_path"]),
                     "physical_sha256": detail["overlay_physical_sha256"],
                     "canonical_sha256": detail["overlay_canonical_sha256"]},
        "source_closure": {
            "declared_item_count": detail["closure"]["declared_item_count"],
            "deduplicated_item_count": detail["closure"]["deduplicated_item_count"],
            "deduplicated_copy_bytes": static_bytes,
            "target_relative_path_count": detail["closure"]["target_relative_path_count"],
            "content_read": False, "payload_hashes_computed": False,
        },
        "decoder_scratch": {
            "max_frame_scratch_bytes": int(detail["scratch_bytes"]),
            "decoder_timeout_seconds": float(detail["decoder_timeout_seconds"]),
            "peak_measurement_required": True,
            "cleanup_failure_is_terminal": True,
        },
        "fresh_product": {
            "target_root": str(target), "output_root": str(output),
            "producer_terminal_manifest": None,
            "new_v16_source_contract": None,
            "new_v16_result_sha256": None,
            "status": "DEFERRED_UNTIL_V49_PRODUCER_TERMINAL",
        },
        "terminal_sealer": {
            "role": "terminal_sealer_v1", "binding": role_bindings["terminal_sealer_v1"],
            "historical_inputs_forbidden": True,
        },
        "proof_consumer": {
            "role": "fresh_v16_proof_consumer_v11",
            "binding": role_bindings["fresh_v16_proof_consumer_v11"],
            "historical_proof_forbidden": True,
        },
        "evaluator": {
            "role": "no_model_evaluator_v4", "binding": role_bindings["no_model_evaluator_v4"],
            "status": "DEFERRED_UNTIL_FRESH_PROOF",
        },
        "qualification": dict(UNKNOWN),
    }
    parent["status"] = "READY_FOR_PARENT_GUARD_V49_METADATA"
    parent["qualification"] = dict(UNKNOWN)
    parent["sha256"] = canonical_sha(parent)
    output_path = _write_new(parent_path, parent)
    return {
        "schema": FORWARD_SCHEMA,
        "status": parent["status"],
        "parent_request": str(output_path),
        "parent_physical_sha256": sha256_file(output_path),
        "parent_canonical_sha256": parent["sha256"],
        "declared_static_copy_bytes": static_bytes,
        "declared_decoder_scratch_bytes": int(detail["scratch_bytes"]),
        "declared_external_reservation_bytes": reserved_bytes,
        "content_read": False,
        "payload_hashes_computed": False,
        "qualification": dict(UNKNOWN),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-parent", type=Path, required=True)
    parser.add_argument("--executor-request", type=Path, required=True)
    parser.add_argument("--parent-output", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--parent-attempt-id", required=True)
    parser.add_argument("--home-budget-bytes", type=int, default=DEFAULT_HOME_BUDGET_BYTES)
    parser.add_argument("--external-budget-bytes", type=int, default=DEFAULT_EXTERNAL_BUDGET_BYTES)
    parser.add_argument("--typed-output-budget-bytes", type=int, default=DEFAULT_TYPED_OUTPUT_BYTES)
    parser.add_argument("--terminal-sealer", type=Path)
    parser.add_argument("--proof-consumer", type=Path)
    parser.add_argument("--evaluator", type=Path)
    args = parser.parse_args(argv)
    try:
        value = build_parent(
            base_parent=args.base_parent, executor_request=args.executor_request,
            parent_output=args.parent_output, target_root=args.target_root,
            output_root=args.output_root, parent_attempt_id=args.parent_attempt_id,
            home_budget_bytes=args.home_budget_bytes,
            external_budget_bytes=args.external_budget_bytes,
            typed_output_budget_bytes=args.typed_output_budget_bytes,
            terminal_sealer=args.terminal_sealer, proof_consumer=args.proof_consumer,
            evaluator=args.evaluator,
        )
    except (OSError, ValueError, TypeError, ParentV49Error) as error:
        parser.error(str(error))
    print(json.dumps(value, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

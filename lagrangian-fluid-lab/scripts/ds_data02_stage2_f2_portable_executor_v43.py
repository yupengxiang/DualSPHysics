#!/usr/bin/env python3
"""Build a fresh ROOT082 V41 cold-producer request.

The builder is metadata/stat-only.  It forwards the already reviewed V41
request into a new target/output namespace and a new same-ledger parent
attempt, while preserving the frozen 405-file/401-frame raw-tree declaration.
It does not read or hash H5, BI4, raw frames, or a typed/label result.  The
V41 runtime still keeps the V34 evaluator *code* roles because the immutable
V34 validator requires that transitive closure, but this request supplies no
old proof and never invokes the evaluator stage; a fresh V16 proof is a later
separate stage.

``build-forward`` creates the new executor request.  ``build-parent`` calls
the reviewed V41 parent builder with ``allow_missing_parent=True`` for the
new attempt.  Both commands refuse existing output namespaces and preserve
the same ledger/data root/floor policy.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V41_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v41.py"
SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v43-forward.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
RAW_TREE_SHA = "08b0f5bef680bffc6bd0af05c81444340da6877eff403e318008994a56e4d0cd"
RAW_TREE_FILES = 405
RAW_TREE_FRAMES = 401
# A relocated request can legitimately carry the old mtime/mode of a small
# JSON/code binding.  Refreshing that metadata is safe only after its known
# content SHA is rechecked.  Scientific payloads remain stat-strict: this
# bound is deliberately below CURRENT/H5/CSV/raw sizes and payload roles are
# excluded even when a file happens to be small.
SMALL_REFRESH_MAX_BYTES = 2 * 1024 * 1024
PAYLOAD_ROLE_PREFIXES = (
    "raw_frame_input", "raw_auxiliary", "reference_typed_hdf5",
    "v2:initial_csv", "v2:xmf",
)


class PortableV43Error(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PortableV43Error(f"cannot load V41 source: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V41 = _load(V41_SCRIPT, "ds02_bound_f2_portable_executor_v41_for_v43")


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V41.canonical_sha(value)


def sha256_file(path: Path | str) -> str:
    return V41.sha256_file(path)


def _load_json(path: Path | str, role: str, *, max_bytes: int = 32 * 1024 * 1024) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise PortableV43Error(f"{role} is not a regular file: {target}")
    if target.stat().st_size > max_bytes:
        raise PortableV43Error(f"{role} exceeds metadata bound: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableV43Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV43Error(f"{role} must be a JSON object")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise PortableV43Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _stat_only(path_value: Any, role: str, declared: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(path_value, str) or not path_value:
        raise PortableV43Error(f"{role} path is missing")
    path = Path(path_value).expanduser()
    # The approved ABI environment is intentionally bound by its literal
    # ``.venv/bin/python`` invocation path; that path is a symlink on this
    # host.  Preserve argv[0] and stat the target, while all data/code source
    # roles remain required regular non-symlink files.
    allow_literal_python_symlink = role.endswith("::python_executable") or role == "python_executable"
    if (path.is_symlink() and not allow_literal_python_symlink) or not path.is_file():
        raise PortableV43Error(f"{role} is not a regular non-symlink file: {path}")
    info = path.stat()
    observed = {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
                "mode_bits": int(info.st_mode & 0o777)}
    for key, value in observed.items():
        if key in declared and int(declared[key]) != value:
            raise PortableV43Error(f"{role} {key} differs from frozen request")
    return observed


def _payload_role(role: str) -> bool:
    return any(role == prefix or role.startswith(prefix + ":")
               for prefix in PAYLOAD_ROLE_PREFIXES)


def _refresh_small_stat(path_value: Any, role: str, declared: Mapping[str, Any]) -> dict[str, Any]:
    """Verify a small non-payload binding by SHA, then refresh stat metadata.

    A different byte count is never relocatable.  A different mtime/mode is
    accepted only for a small source/code file whose full declared SHA still
    matches.  This function is never called for raw/H5/CSV/XMF payloads.
    """
    if _payload_role(role):
        raise PortableV43Error(f"{role} stat differs for a protected scientific payload")
    path = Path(str(path_value)).expanduser()
    if path.is_symlink() or not path.is_file():
        raise PortableV43Error(f"{role} is not a regular non-symlink file: {path}")
    observed = path.stat()
    declared_bytes = int(declared.get("bytes", -1))
    if observed.st_size != declared_bytes:
        raise PortableV43Error(f"{role} byte stat differs; content refresh is not permitted")
    if observed.st_size > SMALL_REFRESH_MAX_BYTES:
        raise PortableV43Error(f"{role} stat differs outside the small/code refresh bound")
    expected_sha = declared.get("sha256")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise PortableV43Error(f"{role} SHA declaration is malformed")
    actual_sha = sha256_file(path)
    if actual_sha != expected_sha:
        raise PortableV43Error(f"{role} content SHA differs during stat refresh")
    return {"bytes": int(observed.st_size), "mtime_ns": int(observed.st_mtime_ns),
            "mode_bits": int(observed.st_mode & 0o777),
            "content_sha_verified": True}


def _validate_metadata(base_path: Path) -> dict[str, Any]:
    value = _load_json(base_path, "V41 executor request")
    if value.get("schema") != SCHEMA or value.get("sha256") != canonical_sha(value):
        raise PortableV43Error("base V41 request schema/canonical SHA differs")
    forward = value.get("forward_v41")
    if not isinstance(forward, Mapping) or forward.get("schema") != "ds02.stage2.f2-portable-executor-v41-forward.v1":
        raise PortableV43Error("base V41 forward marker is missing")
    raw = forward.get("frozen_raw_tree")
    if not isinstance(raw, Mapping) or raw.get("file_count") != RAW_TREE_FILES \
            or raw.get("frame_count") != RAW_TREE_FRAMES or raw.get("tree_sha256") != RAW_TREE_SHA:
        raise PortableV43Error("frozen 405-file/401-frame raw-tree binding differs")
    if value.get("role") != "DEVELOPMENT" or value.get("model_invoked") is not False \
            or value.get("cfd_invoked") is not False or value.get("qualification") != UNKNOWN:
        raise PortableV43Error("base V41 request is not conservative DEVELOPMENT/UNKNOWN")
    entries = value.get("source_entries")
    if not isinstance(entries, list) or not entries:
        raise PortableV43Error("source_entries are missing")
    current = [item for item in entries if isinstance(item, Mapping)
               and item.get("role") == "v2:current_catalog"]
    if len(current) != 1 or current[0].get("sha256") != V41.V40.ACTUAL_CURRENT_SHA:
        raise PortableV43Error("base request does not preserve exact CURRENT df7e identity")
    refreshes: list[dict[str, Any]] = []
    # Stat-only closure check.  In particular, raw_frame_input and the
    # reference H5 are never opened or hashed by this builder.  A stale stat
    # is refreshable only for a small non-payload binding after SHA proof.
    payload_roles = {"raw_frame_input", "reference_typed_hdf5", "native_partout",
                     "native_reconciliation", "native_reconciliation_receipt"}
    for index, item in enumerate(entries):
        if not isinstance(item, Mapping):
            raise PortableV43Error(f"source_entries[{index}] is malformed")
        role_name = str(item.get("role", ""))
        try:
            observed = _stat_only(item.get("path"), f"source_entries[{index}]", item)
        except PortableV43Error:
            if role_name in payload_roles or _payload_role(role_name):
                raise PortableV43Error(
                    f"source_entries[{index}] {role_name} stat differs for a protected scientific payload")
            before = {key: item.get(key) for key in ("bytes", "mtime_ns", "mode_bits")}
            observed = _refresh_small_stat(item.get("path"), role_name, item)
            if isinstance(item, dict):
                item["mtime_ns"] = observed["mtime_ns"]
                item["mode_bits"] = observed["mode_bits"]
            refreshes.append({"role": role_name, "path": str(item.get("path")),
                              "declared_stat_before": before,
                              "observed_stat_after": {key: observed[key]
                                                      for key in ("bytes", "mtime_ns", "mode_bits")},
                              "content_sha_verified": True})
        if role_name in payload_roles:
            # Keep frozen content SHA as a parent-after-reservation declaration;
            # do not compute it here.
            continue
        if not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64:
            raise PortableV43Error(f"source_entries[{index}] SHA declaration is malformed")
        _ = observed
    runtime = value.get("runtime_sources")
    if not isinstance(runtime, list) or not runtime:
        raise PortableV43Error("runtime_sources are missing")
    roles: set[str] = set()
    for index, item in enumerate(runtime):
        if not isinstance(item, Mapping):
            raise PortableV43Error(f"runtime_sources[{index}] is malformed")
        role = str(item.get("role", ""))
        if not role or role in roles:
            raise PortableV43Error(f"runtime role is missing or duplicated: {role}")
        roles.add(role)
        runtime_role = f"runtime_sources[{index}]::{role}"
        try:
            _stat_only(item.get("path"), runtime_role, item)
        except PortableV43Error:
            # Runtime entries are code bindings, so a relocated stat can be
            # refreshed only after the same small-file SHA proof.  A changed
            # worker/loader/executor byte is still rejected by the helper.
            before = {key: item.get(key) for key in ("bytes", "mtime_ns", "mode_bits")}
            observed = _refresh_small_stat(item.get("path"), role, item)
            if isinstance(item, dict):
                item["mtime_ns"] = observed["mtime_ns"]
                item["mode_bits"] = observed["mode_bits"]
            refreshes.append({"role": role, "path": str(item.get("path")),
                              "declared_stat_before": before,
                              "observed_stat_after": {key: observed[key]
                                                      for key in ("bytes", "mtime_ns", "mode_bits")},
                              "content_sha_verified": True})
        if not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64:
            raise PortableV43Error(f"runtime_sources[{index}] SHA declaration is malformed")
    source_roles = {str(item.get("role")) for item in entries
                    if isinstance(item, Mapping) and item.get("role")}
    # The V34 parent validator calls these through its source-entry closure;
    # they are deliberately not duplicated in runtime_sources.  Treat the
    # two declarations as one transitive role set while retaining the
    # runtime/source distinction in the forward receipt.
    all_roles = roles | source_roles
    required = {"executor_v34", "executor_v41", "cold_producer_v40", "v39_source_contract",
                "portable_loader_v5", "raw_worker_v2", "operator_v14", "operator_v15",
                "operator_v16", "python_executable", "runtime_v2", "runtime_v4",
                "stage2_dispatch_v4", "strict_dispatch_v4", "raw_auxiliary:PartInfo.ibi4",
                "raw_auxiliary:PartMotionRef.ibi4", "raw_auxiliary:Part_Head.ibi4"}
    missing = sorted(required - all_roles)
    if missing:
        raise PortableV43Error(f"transitive runtime closure is incomplete: {missing}")
    contract = value.get("source_contract_binding")
    if not isinstance(contract, Mapping):
        raise PortableV43Error("V41 source contract binding is missing")
    try:
        _stat_only(contract.get("path"), "source contract", contract)
    except PortableV43Error:
        before = {key: contract.get(key) for key in ("bytes", "mtime_ns", "mode_bits")}
        observed = _refresh_small_stat(contract.get("path"), "source contract", contract)
        if isinstance(contract, dict):
            contract["mtime_ns"] = observed["mtime_ns"]
            contract["mode_bits"] = observed["mode_bits"]
        refreshes.append({"role": "source contract", "path": str(contract.get("path")),
                          "declared_stat_before": before,
                          "observed_stat_after": {key: observed[key]
                                                  for key in ("bytes", "mtime_ns", "mode_bits")},
                          "content_sha_verified": True})
    value["_v43_stat_refreshes"] = refreshes
    return value


def _runtime_roles(value: Mapping[str, Any]) -> set[str]:
    return {str(item.get("role")) for item in value.get("runtime_sources", [])
            if isinstance(item, Mapping) and item.get("role")}


def build_forward(*, base_request: Path | str, output: Path | str,
                  target_root: Path | str, output_root: Path | str,
                  parent_attempt_id: str, ledger_path: Path | str,
                  external_filesystem: Path | str, deadline_utc: str | None = None,
                  home_min_free_bytes: int | None = None) -> dict[str, Any]:
    base_path = Path(base_request).expanduser().resolve()
    value = _validate_metadata(base_path)
    roles = _runtime_roles(value)
    source_roles = {str(item.get("role")) for item in value.get("source_entries", [])
                    if isinstance(item, Mapping) and item.get("role")}
    all_roles = roles | source_roles
    target = Path(target_root).expanduser().resolve()
    product = Path(output_root).expanduser().resolve()
    if target.exists() or product.exists() or target == product:
        raise PortableV43Error("V43 target/output roots must be fresh and distinct")
    if not parent_attempt_id:
        raise PortableV43Error("new parent attempt ID is required")
    ledger = Path(ledger_path).expanduser().resolve()
    external = Path(external_filesystem).expanduser().resolve()
    if not ledger.is_file() or not external.is_dir():
        raise PortableV43Error("same-parent ledger/external filesystem is unavailable")
    live = _load_json(ledger, "same-parent ledger", max_bytes=128 * 1024 * 1024)
    limits = live.get("limits")
    if not isinstance(limits, Mapping):
        raise PortableV43Error("same-parent ledger limits are missing")
    if home_min_free_bytes is not None and int(home_min_free_bytes) != int(limits.get("home_min_free_bytes", -1)):
        raise PortableV43Error("Home floor differs from same-parent live ledger")
    if deadline_utc is not None and str(deadline_utc) != str(live.get("deadline_utc", "")):
        raise PortableV43Error("deadline differs from same-parent live ledger")
    out = copy.deepcopy(value)
    out["request_id"] = str(value.get("request_id", "f2-s1-v41")) + "-v43"
    out["fresh_roots"] = {"target_root": str(target), "output_root": str(product)}
    parent = dict(out.get("parent_resource_binding", {}))
    parent.update({
        "attempt_id": parent_attempt_id,
        "ledger_path": str(ledger),
        "external_filesystem": str(external),
        "same_parent_ledger": True, "ledger_reset": False, "no_new_data_root": True,
        "storage_policy": str(limits.get("storage_policy", "")),
        "deadline_utc": str(live.get("deadline_utc", "")),
        "home_min_free_bytes": int(limits.get("home_min_free_bytes", 0) or 0),
        "allow_missing_parent": True,
        "reservation_id": parent_attempt_id + "::v43-reservation",
        "supplemental_charge_id": parent_attempt_id + "::v43-charge",
    })
    out["parent_resource_binding"] = parent
    for item in out.get("runtime_sources", []):
        if isinstance(item, dict) and item.get("role") == "executor_v41":
            source = Path(str(item["path"])).expanduser()
            info = source.stat()
            item.update({"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
                         "mode_bits": int(info.st_mode & 0o777),
                         "sha256": sha256_file(source),
                         "content_hash_refresh": "V43 wrapper source refresh"})
    storage = dict(out.get("storage_scope", {}))
    storage.update({"external_filesystem": str(external),
                    "external_output_root": str(product),
                    "new_namespace_absent_before_run": True,
                    "parent_attempt_id": parent_attempt_id})
    out["storage_scope"] = storage
    execution = dict(out.get("execution", {}))
    command = [str(item) for item in execution.get("command", [])]
    command[0:0] = []
    script_indices = [i for i, item in enumerate(command)
                      if item.endswith("ds_data02_stage2_f2_portable_executor_v41.py")]
    if len(script_indices) != 1:
        raise PortableV43Error("V41 command has no unique executor script")
    command[script_indices[0]] = str(V41.SCRIPT)
    execution["command"] = command
    execution["evaluator_stage"] = "DISABLED_UNTIL_NEW_V16_RESULT_AND_NEW_SEMANTIC_PROOF"
    execution["evaluator_proof_input"] = None
    execution["old_proof_input"] = None
    execution["old_evaluator_output_reuse"] = "FORBIDDEN"
    execution["source_content_hash_phase"] = "PARENT_AFTER_RESERVATION"
    out["execution"] = execution
    out["forward_v43"] = {
        "schema": FORWARD_SCHEMA,
        "previous_request": {"path": str(base_path), "sha256": value["sha256"]},
        "wrapper": {"path": str(SCRIPT), "sha256": sha256_file(SCRIPT)},
        "v41_wrapper": {"path": str(V41.SCRIPT), "sha256": sha256_file(V41.SCRIPT)},
        "frozen_raw_tree": {"file_count": RAW_TREE_FILES, "frame_count": RAW_TREE_FRAMES,
                             "tree_sha256": RAW_TREE_SHA, "content_hash_phase": "PARENT_AFTER_RESERVATION"},
        "transitive_runtime_roles": sorted(roles),
        "transitive_source_roles": sorted(source_roles),
        "transitive_closure_roles": sorted(all_roles),
        "stat_refreshes": list(value.get("_v43_stat_refreshes", [])),
        "stat_refresh_policy": {
            "small_non_payload_max_bytes": SMALL_REFRESH_MAX_BYTES,
            "content_sha_required_before_stat_refresh": True,
            "payload_stat_mismatch": "REJECT",
            "hdf5_bi4_raw_csv_content_read_during_build": False,
        },
        "evaluator_code_roles_retained_for_v34_validator": [
            "evaluator_v2", "evaluator_v3", "evaluator_v4", "evaluator_v4_source_request",
            "operator_v14", "operator_v15", "operator_v16"],
        "old_proof_input": None,
        "old_result_input": None,
        "evaluator_invoked_by_this_request": False,
        "new_v16_proof_required_after_producer": True,
        "same_parent_ledger": True, "new_ledger_owner": False,
        "allow_missing_parent": True,
        "hdf5_bi4_raw_read_during_build": False,
        "raw_h5_sha_during_build": False,
        "qualification": dict(UNKNOWN),
    }
    out["status"] = "READY_FOR_PARENT_STAGE2_GUARD"
    out["v43_status"] = "READY_FOR_PARENT_V43_RELOCATED_COLD_GUARD"
    out["raw_opened"] = False; out["hdf5_opened"] = False
    out["model_invoked"] = False; out["cfd_invoked"] = False
    out["qualification"] = dict(UNKNOWN)
    out["sha256"] = canonical_sha(out)
    target_path = _write_new(output, out)
    return {"status": out["v43_status"], "request": str(target_path),
            "sha256": out["sha256"], "parent_attempt_id": parent_attempt_id,
            "runtime_role_count": len(roles), "source_role_count": len(source_roles),
            "transitive_role_count": len(all_roles), "source_entry_count": len(out["source_entries"]),
            "raw_h5_sha_during_build": False, "qualification": dict(UNKNOWN)}


def build_parent(*, executor_request: Path | str, output: Path | str,
                 external_filesystem: Path | str, ledger_path: Path | str,
                 parent_attempt_id: str, max_wall_seconds: float,
                 home_receipt_path: Path | str, supervisor_output_root: Path | str,
                 home_path: Path | str = "/home/jade", home_min_free_bytes: int | None = None,
                 external_bytes: int | None = None, home_receipt_bytes: int = 65536) -> dict[str, Any]:
    request = _validate_metadata(Path(executor_request).expanduser().resolve())
    # V41's reviewed parent builder performs only request/stat metadata checks
    # here; payload source hashing remains in the parent-approved run.
    return V41.build_parent(
        executor_request=executor_request, output=output,
        external_filesystem=external_filesystem, ledger_path=ledger_path,
        parent_attempt_id=parent_attempt_id, max_wall_seconds=max_wall_seconds,
        home_receipt_path=home_receipt_path, supervisor_output_root=supervisor_output_root,
        home_path=home_path, home_min_free_bytes=home_min_free_bytes,
        external_bytes=external_bytes, home_receipt_bytes=home_receipt_bytes,
        allow_missing_parent=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-forward")
    build.add_argument("--base-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--target-root", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--parent-attempt-id", required=True)
    build.add_argument("--ledger-path", type=Path, required=True)
    build.add_argument("--external-filesystem", type=Path, required=True)
    build.add_argument("--deadline-utc")
    build.add_argument("--home-min-free-bytes", type=int)
    parent = sub.add_parser("build-parent")
    parent.add_argument("--executor-request", type=Path, required=True)
    parent.add_argument("--output", type=Path, required=True)
    parent.add_argument("--external-filesystem", type=Path, required=True)
    parent.add_argument("--ledger-path", type=Path, required=True)
    parent.add_argument("--parent-attempt-id", required=True)
    parent.add_argument("--max-wall-seconds", type=float, default=6000.0)
    parent.add_argument("--home-receipt-path", type=Path, required=True)
    parent.add_argument("--supervisor-output-root", type=Path, required=True)
    parent.add_argument("--home-path", type=Path, default=Path("/home/jade"))
    parent.add_argument("--home-min-free-bytes", type=int)
    parent.add_argument("--external-bytes", type=int)
    parent.add_argument("--home-receipt-bytes", type=int, default=65536)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-forward":
            value = build_forward(
                base_request=args.base_request, output=args.output,
                target_root=args.target_root, output_root=args.output_root,
                parent_attempt_id=args.parent_attempt_id, ledger_path=args.ledger_path,
                external_filesystem=args.external_filesystem,
                deadline_utc=args.deadline_utc, home_min_free_bytes=args.home_min_free_bytes)
        else:
            value = build_parent(
                executor_request=args.executor_request, output=args.output,
                external_filesystem=args.external_filesystem, ledger_path=args.ledger_path,
                parent_attempt_id=args.parent_attempt_id, max_wall_seconds=args.max_wall_seconds,
                home_receipt_path=args.home_receipt_path,
                supervisor_output_root=args.supervisor_output_root, home_path=args.home_path,
                home_min_free_bytes=args.home_min_free_bytes,
                external_bytes=args.external_bytes, home_receipt_bytes=args.home_receipt_bytes)
    except (PortableV43Error, V41.PortableV41Error, V41.V38.PortableV38Error,
            V41.V40.ColdProducerV40Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v43: {error}")
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

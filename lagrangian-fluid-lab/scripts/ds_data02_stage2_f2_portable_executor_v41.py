#!/usr/bin/env python3
"""V41 executable cold producer for a relocated F2 raw-to-label bundle.

V38 fixed the copied V14/V15/V16 import names, while V40 supplied the
relocated-CURRENT contract helpers.  Neither was consumed by the native
worker: V38 still passed the V5-generated V15/base pair to the worker.  V41
is the additive executor that closes that gap after the parent has copied and
sealed the bundle:

``copy/seal -> V40 overlay+manifest -> V40 V15 rebind -> V40 source contract
-> V40 base request -> private raw/typed/label worker -> optional independent
fresh evaluator``.

The request builder reads only small JSON/code metadata.  The run path is
parent-guarded and does all payload work only after the inherited V34
reservation/copy boundary.  V34/V38/V40 files, requests and receipts remain
immutable.  All scientific quality fields stay UNKNOWN.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V38_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v38.py"
# V41 and V38 are copied into the executor directory.  The V40 producer is
# likewise bound there by V41; the second candidate keeps source-tree imports
# readable if a caller invokes this module directly from a split source tree.
V40_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_cold_producer_forward_v2.py"
if not V40_SCRIPT.is_file():
    V40_SCRIPT = SCRIPT_DIR.parent / "producer" / V40_SCRIPT.name
PARENT_V3_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_parent_v3.py"
SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
PARENT_SCHEMA = "ds02.stage2.f2-portable-executor-parent-request.v3"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v41-forward.v1"
IMPORT_SCHEMA = "ds02.stage2.f2-private-transitive-import.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
RAW_TREE_SHA = "08b0f5bef680bffc6bd0af05c81444340da6877eff403e318008994a56e4d0cd"
RAW_TREE_FILES = 405
RAW_TREE_FRAMES = 401


class PortableV41Error(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PortableV41Error(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V38 = _load(V38_SCRIPT, "ds02_bound_f2_portable_executor_v38_for_v41")
V40 = _load(V40_SCRIPT, "ds02_bound_f2_cold_producer_v40_for_v41")


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V38.canonical_sha(value)


def sha256_file(path: Path | str) -> str:
    return V38.sha256_file(path)


def load_json(path: Path | str, role: str = "JSON") -> dict[str, Any]:
    value = V38.load_json(path)
    if not isinstance(value, dict):
        raise PortableV41Error(f"{role} must be a JSON object: {path}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise PortableV41Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _require_file(path: Path | str, role: str) -> Path:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise PortableV41Error(f"{role} is missing: {target}")
    return target


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise PortableV41Error(f"{role} must be a lowercase SHA-256")
    return value


def _binding(path: Path, role: str) -> dict[str, Any]:
    stat = path.stat()
    return {"role": role, "path": str(path), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "mode_bits": int(stat.st_mode & 0o777),
            "sha256": sha256_file(path)}


def _runtime_item(request: Mapping[str, Any], role: str) -> dict[str, Any]:
    values = [dict(item) for item in request.get("runtime_sources", [])
              if isinstance(item, Mapping) and item.get("role") == role]
    if len(values) != 1:
        raise PortableV41Error(f"runtime role is not unique: {role}")
    return values[0]


def _validate_request(path: Path | str) -> dict[str, Any]:
    request = V38._load_request(path)
    forward = request.get("forward_v41")
    if not isinstance(forward, Mapping) or forward.get("schema") != FORWARD_SCHEMA:
        raise PortableV41Error("V41 forward marker is missing")
    contract = request.get("source_contract_binding")
    if not isinstance(contract, Mapping):
        raise PortableV41Error("V41 source contract binding is missing")
    _require_file(contract.get("path"), "V39 source contract")
    _sha(contract.get("sha256"), "V39 source contract SHA")
    raw = forward.get("frozen_raw_tree")
    if not isinstance(raw, Mapping) or raw.get("file_count") != RAW_TREE_FILES or raw.get("frame_count") != RAW_TREE_FRAMES or raw.get("tree_sha256") != RAW_TREE_SHA:
        raise PortableV41Error("V41 frozen 405-file/401-frame raw tree binding differs")
    current_rows = [item for item in request.get("source_entries", [])
                    if isinstance(item, Mapping) and item.get("role") == "v2:current_catalog"]
    if len(current_rows) != 1 or current_rows[0].get("sha256") != V40.ACTUAL_CURRENT_SHA:
        raise PortableV41Error("V41 request does not bind exact CURRENT df7e source")
    return request


def build_forward(*, v38_request: Path | str, v39_contract: Path | str,
                  output: Path | str, target_root: Path | str,
                  output_root: Path | str) -> dict[str, Any]:
    """Build a fresh V41 request; no H5/BI4/raw/typed payload is opened."""
    old_path = _require_file(v38_request, "V38 executor request")
    old = load_json(old_path, "V38 executor request")
    if old.get("schema") != SCHEMA or old.get("sha256") != canonical_sha(old):
        raise PortableV41Error("V38 request schema/canonical SHA differs")
    if not isinstance(old.get("forward_v38"), Mapping):
        raise PortableV41Error("V38 forward marker is missing")
    raw = old["forward_v38"].get("frozen_raw_tree", {})
    if raw.get("file_count") != RAW_TREE_FILES or raw.get("frame_count") != RAW_TREE_FRAMES or raw.get("tree_sha256") != RAW_TREE_SHA:
        raise PortableV41Error("V38 request raw tree binding differs")
    contract_path = _require_file(v39_contract, "V39 source contract")
    contract = V40._load_canonical(contract_path, V40.SCHEMA_V39, "V39 source contract")
    target = Path(target_root).expanduser()
    product = Path(output_root).expanduser()
    if target.exists() or product.exists() or target == product:
        raise PortableV41Error("V41 target/output roots must be fresh and distinct")
    old_roots = old.get("fresh_roots", {})
    if str(target) in {str(old_roots.get("target_root", "")), str(old_roots.get("output_root", ""))}:
        raise PortableV41Error("V41 cannot reuse a consumed V38 root")
    runtime = old.get("runtime_sources")
    if not isinstance(runtime, list) or not runtime:
        raise PortableV41Error("V38 runtime_sources are missing")
    roles = {str(item.get("role")) for item in runtime if isinstance(item, Mapping)}
    additions = [
        ("v39_source_contract", contract_path, "runtime/producer/f2-s1-source-contract-v39.json"),
        ("cold_producer_v40", V40.SCRIPT, "runtime/executor/ds_data02_stage2_f2_cold_producer_forward_v2.py"),
        ("executor_v41", SCRIPT, "runtime/executor/ds_data02_stage2_f2_portable_executor_v41.py"),
    ]
    if any(role in roles for role, _, _ in additions):
        raise PortableV41Error("V41 runtime role is already bound")
    value = copy.deepcopy(old)
    value["request_id"] = str(old.get("request_id", "f2-s1-v38")) + "-v41"
    value["fresh_roots"] = {"target_root": str(target), "output_root": str(product)}
    value["runtime_sources"] = [dict(item) for item in runtime]
    for role, path, relative in additions:
        value["runtime_sources"].append({
            "role": role, "path": str(path), "target_relative_path": relative,
            "bytes": int(path.stat().st_size), "mtime_ns": int(path.stat().st_mtime_ns),
            "mode_bits": int(path.stat().st_mode & 0o777), "sha256": sha256_file(path),
            "original_path_fallback": "FORBIDDEN",
        })
    execution = dict(value.get("execution", {}))
    command = list(execution.get("command", []))
    # V38's closed command is ``python -B -I <v38.py> ...``.  Replace the
    # script operand, not the ``-I`` flag; the earlier positional shortcut
    # produced ``python -B <v41.py> <v38.py> ...`` and would fail before the
    # copied executor started.
    script_indices = [index for index, item in enumerate(command)
                      if isinstance(item, str) and item.endswith("ds_data02_stage2_f2_portable_executor_v38.py")]
    if len(script_indices) != 1:
        raise PortableV41Error("V38 execution command has no unique executor-v38 script operand")
    command[script_indices[0]] = str(SCRIPT)
    execution.update({
        "command": command,
        "original_path_fallback": "FORBIDDEN",
        "v40_relocation_before_label": True,
        "actual_new_typed_h5_sha_phase": "AFTER_PARENT_COPY_AND_NATIVE_RECONSTRUCTION",
        "fresh_consumer_phase": "AFTER_NEW_V16_RESULT_AND_INDEPENDENT_PROOF",
    })
    value["execution"] = execution
    value["source_contract_binding"] = _binding(contract_path, "v39_source_contract")
    value["forward_v41"] = {
        "schema": FORWARD_SCHEMA,
        "compatibility_envelope": SCHEMA,
        "previous_request": {"path": str(old_path), "sha256": old["sha256"]},
        "wrapper": {"path": str(SCRIPT), "sha256": sha256_file(SCRIPT)},
        "v38_wrapper": {"path": str(V38.SCRIPT), "sha256": sha256_file(V38.SCRIPT)},
        "v40_module": {"path": str(V40.SCRIPT), "sha256": sha256_file(V40.SCRIPT)},
        "source_contract": {"path": str(contract_path), "sha256": contract["sha256"],
                            "schema": V40.SCHEMA_V39},
        "relocation_pipeline": [
            "parent_after_copy_current_json", "make_relocated_overlay",
            "rebind_replay_v15", "build_contract", "replace_worker_base_request",
            "private_native_raw_to_typed_label_worker", "fresh_independent_consumer",
        ],
        "frozen_raw_tree": {"file_count": RAW_TREE_FILES, "frame_count": RAW_TREE_FRAMES,
                             "tree_sha256": RAW_TREE_SHA},
        "identity_scope": "CURRENT source identity df7e; relocated view is actionable runtime digest",
        "actual_typed_h5_sha": "MUST_BE_COMPUTED_BY_THIS_ATTEMPT",
        "actual_converted_metadata_sha": "MUST_BE_COMPUTED_BY_THIS_ATTEMPT",
        "old_f208_sha_reuse": "FORBIDDEN",
        "same_parent_ledger": True, "new_ledger_owner": False,
        "hdf5_bi4_content_read_during_build": False,
        "payload_read_during_build": False,
        "qualification": dict(UNKNOWN),
    }
    # Parent V3 has an exact status gate for the v34-compatible envelope.
    # Keep that executable value and carry the V41 stage as a separate marker.
    value["status"] = "READY_FOR_PARENT_STAGE2_GUARD"
    value["v41_status"] = "READY_FOR_PARENT_V41_RELOCATED_COLD_GUARD"
    value["raw_opened"] = False; value["hdf5_opened"] = False
    value["model_invoked"] = False; value["cfd_invoked"] = False
    value["qualification"] = dict(UNKNOWN)
    value["sha256"] = canonical_sha(value)
    write_new(output, value)
    return {"status": value["v41_status"], "request": str(Path(output).expanduser()),
            "sha256": value["sha256"], "source_entry_count": len(value.get("source_entries", [])),
            "runtime_source_count": len(value["runtime_sources"]),
            "frozen_raw_tree_sha256": RAW_TREE_SHA, "payload_read": False,
            "hdf5_or_bi4_read": False, "qualification": dict(UNKNOWN)}


def build_parent(*, executor_request: Path | str, output: Path | str,
                 external_filesystem: Path | str, ledger_path: Path | str,
                 parent_attempt_id: str, max_wall_seconds: float,
                 home_receipt_path: Path | str, supervisor_output_root: Path | str,
                 home_path: Path | str = "/home/jade", home_min_free_bytes: int | None = None,
                 external_bytes: int | None = None, home_receipt_bytes: int = 65536,
                 allow_missing_parent: bool = False) -> dict[str, Any]:
    """Use the reviewed V3 parent builder with the new V41 executor path."""
    executor = _validate_request(executor_request)
    parent = _load(PARENT_V3_SCRIPT, "ds02_bound_f2_executor_parent_v3_for_v41")
    final_parent_path = Path(output).expanduser()
    if final_parent_path.exists():
        raise PortableV41Error(f"refusing existing V41 parent request: {final_parent_path}")
    with tempfile.TemporaryDirectory(prefix="ds02-v41-parent-builder-") as tmp:
        intermediate = Path(tmp) / "parent-v3.json"
        parent.build_request(
            executor_request=executor_request, output=intermediate,
            external_filesystem=external_filesystem, ledger_path=ledger_path,
            parent_attempt_id=parent_attempt_id, max_wall_seconds=max_wall_seconds,
            external_bytes=external_bytes, home_receipt_bytes=home_receipt_bytes,
            home_receipt_path=home_receipt_path, supervisor_output_root=supervisor_output_root,
            home_path=home_path, home_min_free_bytes=home_min_free_bytes,
            executor_script=SCRIPT, allow_missing_parent=allow_missing_parent)
        parent_path = intermediate
        request = load_json(parent_path, "V41 parent request")
    # Parent V3's ``executor_v34`` role is retained as a compatibility role,
    # but the actual immutable path and command are V41.  Add a distinct
    # contract role so the parent receipt can audit the V40 source edge.
    contract_item = executor.get("source_contract_binding")
    if not isinstance(contract_item, Mapping):
        raise PortableV41Error("executor has no V39 source contract binding")
    bindings = request.get("static_bindings")
    if not isinstance(bindings, list):
        raise PortableV41Error("V3 parent static bindings are missing")
    bindings.append(dict(contract_item, role="v39_source_contract"))
    bindings.append(_binding(V40.SCRIPT, "cold_producer_v40"))
    request["static_bindings"] = bindings
    request["executor_script"] = {"path": str(SCRIPT), "sha256": sha256_file(SCRIPT), "immutable": True}
    request["v41_forward"] = {
        "schema": FORWARD_SCHEMA,
        "executor_request": {"path": str(Path(executor_request).expanduser().resolve()), "sha256": executor["sha256"]},
        "source_contract": dict(contract_item),
        "same_parent_ledger": True, "new_ledger_owner": False,
        "allow_missing_parent": bool(allow_missing_parent),
        "old_f208_reuse": "FORBIDDEN", "qualification": dict(UNKNOWN),
    }
    request["sha256"] = parent.canonical_sha(request)
    # The V3 builder writes into a private temporary path.  Enrich that fresh
    # request in memory, then write one new immutable V41 parent request; no
    # consumed V3 request or receipt is overwritten.
    write_new(final_parent_path, request)
    return {"status": "READY_FOR_PARENT_V41_RELOCATED_COLD_GUARD", "parent_request": str(final_parent_path),
            "parent_request_sha256": sha256_file(final_parent_path), "v41_parent_binding": str(final_parent_path),
            "v41_parent_binding_sha256": sha256_file(final_parent_path), "executor_request": str(Path(executor_request)),
            "executor_request_sha256": executor["sha256"], "qualification": dict(UNKNOWN)}


def _sealed_overlay(output_root: Path) -> dict[str, Any]:
    path = output_root / "sealed-overlay-v34.json"
    value = load_json(path, "sealed V34 overlay")
    if value.get("content_hash_verified") is not True:
        raise PortableV41Error("V34 overlay was not content-sealed")
    return value


def _overlay_role(overlay: Mapping[str, Any], role: str) -> dict[str, Any]:
    rows = [dict(item) for item in overlay.get("entries", [])
            if isinstance(item, Mapping) and item.get("role") == role]
    if len(rows) != 1:
        raise PortableV41Error(f"sealed overlay role is not unique: {role}")
    return rows[0]


def _copied_runtime_path(request: Mapping[str, Any], role: str, target_root: Path) -> Path:
    item = _runtime_item(request, role)
    relative = item.get("target_relative_path")
    if not isinstance(relative, str) or relative.startswith("/") or ".." in Path(relative).parts:
        raise PortableV41Error(f"unsafe runtime target path: {role}")
    target = target_root / "runtime" / relative
    if not target.is_file():
        raise PortableV41Error(f"copied runtime role is missing: {role}: {target}")
    if sha256_file(target) != _sha(item.get("sha256"), f"runtime {role}.sha256"):
        raise PortableV41Error(f"copied runtime role SHA differs: {role}")
    return target


def _validate_completed_label_report(path: Path) -> dict[str, Any]:
    """Require the native worker's actual typed/V15/V16 stages to finish.

    V34 writes a report even when its label stage is pending or rejected.  A
    report file alone therefore cannot be promoted to a completed cold
    producer.  This check is JSON-only after the worker has finished; it
    hashes only the newly produced typed/result artifacts already named by
    that report and never substitutes an old result or proof.
    """
    value = load_json(path, "native raw-to-typed-to-label report")
    if value.get("schema") != "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2":
        raise PortableV41Error("native worker report schema differs")
    if value.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise PortableV41Error(
            f"native worker did not complete: {value.get('status')!r}")
    typed = value.get("typed_output")
    if not isinstance(typed, Mapping) or not isinstance(typed.get("path"), str):
        raise PortableV41Error("native report has no typed output")
    typed_path = _require_file(typed["path"], "actual reconstructed typed H5")
    if typed.get("sha256") != sha256_file(typed_path):
        raise PortableV41Error("native typed output SHA differs from its report")
    labels = value.get("typed_to_label")
    if not isinstance(labels, Mapping):
        raise PortableV41Error("native report has no typed-to-label stage")
    if labels.get("status") != "V15_LABEL_REPLAY_COMPLETE_DEVELOPMENT_UNKNOWN":
        raise PortableV41Error(
            f"V15 label stage is incomplete: {labels.get('status')!r}")
    v15_result = labels.get("result")
    if not isinstance(v15_result, str):
        raise PortableV41Error("native report has no V15 result")
    v15_path = _require_file(v15_result, "actual V15 label result")
    if labels.get("result_sha256") != sha256_file(v15_path):
        raise PortableV41Error("V15 result SHA differs from its report")
    v16 = labels.get("v16_forward")
    if not isinstance(v16, Mapping) or v16.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise PortableV41Error(
            f"V16 label stage is incomplete: {v16.get('status') if isinstance(v16, Mapping) else None!r}")
    v16_result = v16.get("result")
    if not isinstance(v16_result, str):
        raise PortableV41Error("native report has no V16 result")
    v16_path = _require_file(v16_result, "actual V16 label result")
    if v16.get("result_sha256") != sha256_file(v16_path):
        raise PortableV41Error("V16 result SHA differs from its report")
    return {"report": value, "typed_path": typed_path,
            "v15_path": v15_path, "v16_path": v16_path}


def _make_v40_engine_inputs(request: Mapping[str, Any], output: Path,
                            base_path: Path) -> dict[str, Any]:
    output_root = output.parent
    overlay = _sealed_overlay(output_root)
    current = Path(_overlay_role(overlay, "v2:current_catalog")["target_path"])
    reference = Path(_overlay_role(overlay, "reference_typed_hdf5")["target_path"])
    if not current.is_file() or not reference.is_file():
        raise PortableV41Error("sealed copied CURRENT/reference target is missing")
    v40_dir = output_root / "v40-relocated-runtime"
    overlay_path = v40_dir / "CURRENT336-case78-v40-runtime-view.json"
    relocation = V40.make_relocated_overlay(actual_current=current,
                                             target_trajectory=reference,
                                             output=overlay_path)
    old_v15 = output_root / "relocated-runtime" / "f2-s1-replay-request-v15-relocated.json"
    old_v15 = _require_file(old_v15, "V5 relocated V15 request")
    # V5 has already changed its actionable current row to the first alias
    # digest.  V40 deliberately requires an exact CURRENT input at the
    # rebind boundary, so make a small copied-current bridge from the V5 JSON
    # before calling the immutable V40 helper.  Other V5-rebound paths stay
    # target-local; no original source path is reintroduced.
    v40_input_value = load_json(old_v15, "V5 relocated V15 request")
    v40_binding = v40_input_value.get("current_binding")
    v40_sources = v40_input_value.get("source_files")
    if not isinstance(v40_binding, dict) or not isinstance(v40_sources, list):
        raise PortableV41Error("V5 relocated V15 lacks current binding/source files")
    v40_binding.update({"path": str(current), "sha256": V40.ACTUAL_CURRENT_SHA,
                        "binding_status": "COPIED_EXACT_CURRENT_BEFORE_V40_RELOCATION",
                        "exact_current_source": True})
    current_rows = [item for item in v40_sources
                    if isinstance(item, dict) and item.get("role") == "current_catalog"]
    if len(current_rows) != 1:
        raise PortableV41Error("V5 relocated V15 current source row is not unique")
    current_rows[0].update({"path": str(current), "sha256": V40.ACTUAL_CURRENT_SHA,
                            "binding_status": "COPIED_EXACT_CURRENT_BEFORE_V40_RELOCATION"})
    profile = v40_input_value.get("observer_profile")
    if isinstance(profile, dict):
        profile["current_binding_sha256"] = V40.ACTUAL_CURRENT_SHA
        source_sha = profile.get("source_file_sha256")
        if isinstance(source_sha, dict):
            source_sha["current_catalog"] = V40.ACTUAL_CURRENT_SHA
    exact_v15_path = v40_dir / "f2-s1-replay-request-v15-copied-exact-current.json"
    write_new(exact_v15_path, v40_input_value)
    rebound_path = v40_dir / "f2-s1-replay-request-v15-v40-relocated.json"
    rebound = V40.rebind_replay_v15(replay_request=exact_v15_path,
                                    manifest=relocation["manifest"], output=rebound_path)
    copied_contract = _copied_runtime_path(request, "v39_source_contract",
                                           Path(overlay["target_root"]))
    contract_path = v40_dir / "f2-s1-fresh-v16-source-contract-v40-runtime.json"
    contract = V40.build_contract(v39_contract=copied_contract,
                                  relocated_v15=rebound["path"], manifest=relocation["manifest"],
                                  output=contract_path)
    rebound_value = load_json(rebound["path"], "V40 relocated V15 request")
    base_value = load_json(base_path, "V5 base native request")
    source_files = base_value.get("source_files")
    if not isinstance(source_files, list):
        raise PortableV41Error("V5 base request source_files are missing")
    for item in source_files:
        if not isinstance(item, dict):
            continue
        if item.get("role") == "current_catalog":
            item.update({"path": relocation["overlay"], "sha256": relocation["overlay_sha256"],
                         "binding_status": "RELOCATED_RUNTIME_CURRENT_VIEW"})
        elif item.get("role") == "v15_replay_request":
            item.update({"path": rebound["path"], "sha256": rebound["sha256"]})
    binding = base_value.get("current_binding")
    if isinstance(binding, dict):
        binding.update({"path": relocation["overlay"], "sha256": relocation["overlay_sha256"],
                        "binding_status": "RELOCATED_RUNTIME_CURRENT_VIEW"})
    base_value["v15_request"] = rebound_value
    base_value["v40_source_contract_binding"] = {
        "path": str(contract_path), "sha256": contract["sha256"],
        "file_sha256": sha256_file(contract_path),
        "original_current_sha256": V40.ACTUAL_CURRENT_SHA,
        "relocated_current_view_sha256": relocation["overlay_sha256"],
        "source_contract_consumed_before_label": True,
    }
    base_value["v40_relocation"] = {
        "manifest": {"path": relocation["manifest"], "sha256": sha256_file(relocation["manifest"])},
        "overlay": {"path": relocation["overlay"], "sha256": relocation["overlay_sha256"]},
        "v15": {"path": rebound["path"], "sha256": rebound["sha256"]},
        "v15_exact_copied_current_input": {"path": str(exact_v15_path), "sha256": sha256_file(exact_v15_path)},
        "source_contract": {"path": str(contract_path), "sha256": contract["sha256"],
                             "file_sha256": sha256_file(contract_path)},
        "original_current_sha256": V40.ACTUAL_CURRENT_SHA,
        "historical_v39_overlay_sha256": V40.HISTORICAL_OVERLAY_SHA,
        "old_f208_reuse": "FORBIDDEN",
    }
    base_value["sha256"] = canonical_sha(base_value)
    new_base_path = v40_dir / "f2-s1-native-raw-to-typed-label-request-v2-v40-relocated.json"
    write_new(new_base_path, base_value)
    integration = {
        "schema": "ds02.stage2.f2-v40-engine-binding.v1",
        "status": "PASS_V40_RELOCATED_CONTRACT_CONSUMED_BEFORE_LABEL",
        "label_producer_request": {"path": str(new_base_path), "sha256": sha256_file(new_base_path)},
        "v15_request": {"path": rebound["path"], "sha256": rebound["sha256"]},
        "source_contract": {"path": str(contract_path), "sha256": contract["sha256"],
                             "file_sha256": sha256_file(contract_path)},
        "relocation_manifest": {"path": relocation["manifest"], "sha256": sha256_file(relocation["manifest"])},
        "relocated_current_view": {"path": relocation["overlay"], "sha256": relocation["overlay_sha256"]},
        "original_current_identity_sha256": V40.ACTUAL_CURRENT_SHA,
        "frozen_raw_tree": {"file_count": RAW_TREE_FILES, "frame_count": RAW_TREE_FRAMES,
                             "tree_sha256": RAW_TREE_SHA},
        "identity_scope": "CURRENT source identity df7e; actionable runtime view is the observed V40 digest",
        "label_producer_consumes": "V40 rebound V15 embedded in the V40 base request",
        "payload_read_before_worker": False,
        "hdf5_or_bi4_read_before_worker": False,
        "qualification": dict(UNKNOWN),
    }
    write_new(output_root / "v40-engine-binding-before-label.json", integration)
    return {"integration": integration, "base": new_base_path,
            "v15": Path(rebound["path"]), "contract": contract_path,
            "manifest": Path(relocation["manifest"])}


def _v41_worker_hook(v34: Any, request_value: Mapping[str, Any], state: dict[str, Any]):
    def wrapped(python: Path, worker: Path, request: Path, output: Path,
                *, deadline: float | None):
        bindings = V38._module_bindings(request)
        aliases = V38._materialize_aliases(bindings, worker.parent)
        imported = V38._import_subprocess(python, aliases)
        closure = {"schema": IMPORT_SCHEMA,
                   "status": "PASS_V40_COPIED_TARGET_TRANSITIVE_IMPORT",
                   "base_request": {"path": str(request), "sha256": sha256_file(request)},
                   "worker": {"path": str(worker), "sha256": sha256_file(worker)},
                   "aliases": aliases, "import": imported,
                   "original_path_fallback": "FORBIDDEN", "payload_read": False,
                   "hdf5_or_bi4_read": False, "qualification": dict(UNKNOWN)}
        write_new(output.parent / "private-import-closure-v40.json", closure)
        v40_state = _make_v40_engine_inputs(request_value, output, request)
        state.update(v40_state)
        return V38._run_worker_with_bootstrap(v34, python, worker, v40_state["base"], output,
                                              deadline=deadline)
    return wrapped


def _runtime_records(request: Mapping[str, Any], target_root: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for raw in request.get("runtime_sources", []):
        if not isinstance(raw, Mapping):
            continue
        role = str(raw.get("role", ""))
        relative = raw.get("target_relative_path")
        if not role or not isinstance(relative, str):
            continue
        record = dict(raw)
        record["path"] = str(target_root / "runtime" / relative)
        records[role] = record
    python = records.get("python_executable")
    if isinstance(python, dict) and isinstance(python.get("invocation_path"), str):
        python["invocation_path"] = python["invocation_path"]
    return records


def _run_evaluator_with_bootstrap(v34: Any, python: Path, evaluator: Path,
                                  request: Path, output: Path,
                                  *, deadline: float | None) -> tuple[int, str, str]:
    """Run V4 evaluator with only its copied sibling directory on sys.path."""
    code = (
        "import runpy,sys; script=sys.argv[1]; sys.argv=sys.argv[1:]; "
        "sys.path.insert(0, __import__('pathlib').Path(script).parent.as_posix()); "
        "runpy.run_path(script, run_name='__main__')"
    )
    command = [str(python), "-B", "-I", "-c", code, str(evaluator), "run",
               "--request", str(request), "--output", str(output)]
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME"}}
    proc = subprocess.Popen(command, start_new_session=False, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env)
    try:
        stdout, stderr = proc.communicate(
            timeout=None if deadline is None else max(0.1, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        v34._child_group_terminate(proc)
        stdout, stderr = proc.communicate()
        return 124, stdout, stderr + "\nprivate V40 evaluator deadline exceeded"
    return int(proc.returncode), stdout, stderr


def _run_fresh_evaluator(v34: Any, request: Mapping[str, Any], state: Mapping[str, Any],
                         proof: Path, output_root: Path, deadline: float | None,
                         worker_report: Path) -> tuple[Path, str]:
    if not proof.is_file():
        raise PortableV41Error(f"fresh independent proof is missing: {proof}")
    contract = state.get("contract")
    v15 = state.get("v15")
    if not isinstance(contract, Path) or not isinstance(v15, Path):
        raise PortableV41Error("V40 contract/V15 state is missing before evaluator")
    # Re-read only the small contract/request JSON and verify the actual new
    # digest.  No old f208/aabfb value can satisfy this check.
    V40.build_contract  # keep the bound module explicit in the closure
    contract_value = V40._load_canonical(contract, V40.SCHEMA_CONTRACT, "V40 source contract")
    v15_value = load_json(v15, "V40 V15 request")
    relocated_sha = contract_value["expected"]["source_binding"]["current_catalog_sha256"]
    if v15_value.get("current_binding", {}).get("sha256") != relocated_sha:
        raise PortableV41Error("fresh evaluator V15 binding differs from V40 contract")
    worker_value = load_json(worker_report, "V40 raw-to-label report")
    result_binding = worker_value.get("typed_to_label", {}).get("v16_forward", {})
    result_path_value = result_binding.get("result") if isinstance(result_binding, Mapping) else None
    if not isinstance(result_path_value, str):
        raise PortableV41Error("worker report has no actual V16 result for fresh evaluator")
    result_path = _require_file(result_path_value, "actual V16 label result")
    # A V40 header contract is deliberately insufficient for this stage.  The
    # proof must be the fresh JSON-only semantic proof of this exact V16 file,
    # generated after the relocated producer completed; an old proof or a
    # header-only proof cannot be injected into a new namespace.
    try:
        result_path.relative_to(output_root.resolve())
    except ValueError as error:
        raise PortableV41Error("actual V16 result is outside the relocated output root") from error
    proof_value = load_json(proof, "fresh V16 semantic proof")
    if proof_value.get("schema") != "ds02.stage2.f2-fresh-v16-proof.v8":
        raise PortableV41Error(
            "fresh evaluator requires the V8/V10 semantic proof; V40 label-header proof is insufficient")
    if proof_value.get("sha256") != V38.canonical_sha(proof_value):
        raise PortableV41Error("fresh semantic proof canonical SHA differs")
    if proof_value.get("status") != "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN":
        raise PortableV41Error("fresh semantic proof is not a completed development verification")
    proof_result = proof_value.get("source_result")
    if not isinstance(proof_result, Mapping):
        raise PortableV41Error("fresh semantic proof has no source_result binding")
    actual_result_sha = sha256_file(result_path)
    if proof_result.get("sha256") != actual_result_sha:
        raise PortableV41Error("fresh semantic proof does not bind this V16 result SHA")
    if Path(str(proof_result.get("path", ""))).expanduser().resolve() != result_path.resolve():
        raise PortableV41Error("fresh semantic proof result path differs from the relocated V16 result")
    proof_binding = proof_value.get("source_binding")
    if not isinstance(proof_binding, Mapping) or proof_binding.get("current_catalog_sha256") != relocated_sha:
        raise PortableV41Error("fresh semantic proof does not bind the V40 relocated CURRENT view")
    try:
        proof.resolve().relative_to(output_root.resolve())
    except ValueError as error:
        raise PortableV41Error("fresh semantic proof is outside the relocated output root") from error
    runtime = _runtime_records(request, Path(request["fresh_roots"]["target_root"]))
    evaluator_source = Path(runtime["evaluator_v4_source_request"]["path"])
    evaluator_module = Path(runtime["evaluator_v4"]["path"])
    temporary = output_root / "evaluator-v4-v40-request.tmp.json"
    final_request = output_root / "evaluator-v4-v40-relocated-request.json"
    evaluator_source_value = load_json(evaluator_source, "copied evaluator source request")
    v34._rewrite_evaluator_request(
        evaluator_source_value, result=result_path, frozen=v15, proof=proof,
        raw_report=worker_report, runtime=runtime, output=temporary)
    request_value = load_json(temporary, "V40 evaluator request")
    request_value["v40_source_contract_binding"] = {
        "path": str(contract), "sha256": sha256_file(contract),
        "current_source_identity_sha256": V40.ACTUAL_CURRENT_SHA,
        "relocated_view_sha256": relocated_sha,
        "old_f208_reuse": "FORBIDDEN",
    }
    request_value["sha256"] = v34.canonical_sha(request_value)
    write_new(final_request, request_value)
    temporary.unlink()
    evaluator_report = output_root / "no-model-evaluator-v40.json"
    remaining = None if deadline is None else max(0.1, deadline - time.monotonic())
    # The evaluator uses V34's reviewed direct-child boundary, not the raw
    # worker bootstrap.  It remains in the parent-owned process group.
    code, out, err = _run_evaluator_with_bootstrap(
        v34, Path(runtime["python_executable"].get("invocation_path", runtime["python_executable"]["path"])),
        evaluator_module, final_request, evaluator_report, deadline=remaining)
    (output_root / "evaluator-v40.stdout.log").write_text(out, encoding="utf-8")
    (output_root / "evaluator-v40.stderr.log").write_text(err, encoding="utf-8")
    if code != 0:
        raise PortableV41Error(f"V40 private evaluator failed with {code}: {err[-1000:]}")
    return evaluator_report, sha256_file(evaluator_report)


def run(request_path: Path | str, *, io_slot_approved: bool,
        parent_pid: int | None = None, evaluator_proof: Path | None = None,
        max_wall_seconds: float | None = None) -> dict[str, Any]:
    request = _validate_request(request_path)
    entry_wall = time.monotonic()
    v34 = V38._load_v34()
    state: dict[str, Any] = {}
    original = v34._run_private_worker
    v34._run_private_worker = _v41_worker_hook(v34, request, state)
    try:
        # V34's evaluator path uses its old V5 alias.  Run the actual new
        # label producer first; the independent V40 evaluator is attached
        # below with the new V15/contract pair.
        result = v34.run(request_path, io_slot_approved=io_slot_approved,
                         parent_pid=parent_pid, evaluator_proof=None,
                         max_wall_seconds=max_wall_seconds)
    finally:
        v34._run_private_worker = original
    output_root = Path(request["fresh_roots"]["output_root"]).expanduser()
    worker_report = output_root / "native-raw-to-label-v34" / "raw-to-typed-to-label-report-v2.json"
    final_sidecar = output_root / "v40-engine-integration-report.json"
    integration = state.get("integration")
    if integration is None:
        raise PortableV41Error("V40 relocation/contract stage did not run")
    actual: dict[str, Any] = {"worker_report": None, "typed_output": None,
                              "v15_label_result": None, "v16_label_result": None}
    completed_worker = False
    if worker_report.is_file():
        completed = _validate_completed_label_report(worker_report)
        worker_value = completed["report"]
        completed_worker = True
        actual["worker_report"] = {"path": str(worker_report), "sha256": sha256_file(worker_report)}
        typed = worker_value.get("typed_output")
        if isinstance(typed, Mapping) and isinstance(typed.get("path"), str):
            typed_path = _require_file(typed["path"], "actual reconstructed typed H5")
            actual["typed_output"] = {"path": str(typed_path), "sha256": sha256_file(typed_path),
                                       "bytes": int(typed_path.stat().st_size)}
        labels = worker_value.get("typed_to_label")
        if isinstance(labels, Mapping):
            for key in ("result",):
                value = labels.get(key)
                if isinstance(value, str) and Path(value).is_file():
                    actual["v15_label_result"] = {"path": value, "sha256": sha256_file(value)}
            v16 = labels.get("v16_forward")
            if isinstance(v16, Mapping) and isinstance(v16.get("result"), str) and Path(v16["result"]).is_file():
                actual["v16_label_result"] = {"path": v16["result"], "sha256": sha256_file(v16["result"])}
    evaluator = None
    if evaluator_proof is not None:
        evaluator, evaluator_sha = _run_fresh_evaluator(
            v34, request, state, Path(evaluator_proof).expanduser(), output_root,
            None if max_wall_seconds is None else entry_wall + max_wall_seconds,
            worker_report)
        evaluator = {"path": str(evaluator), "sha256": evaluator_sha,
                     "status": "COMPLETE_DEVELOPMENT_UNKNOWN"}
    final = dict(integration)
    final.update({"schema": "ds02.stage2.f2-v40-engine-integration-report.v1",
                  "status": "COMPLETE_V40_RELOCATED_RAW_TYPED_LABEL" if completed_worker else "FAILED_V40_LABEL_STAGE",
                  "actual_outputs": actual,
                  "independent_fresh_evaluator": evaluator,
                  "old_f208_reuse": "FORBIDDEN",
                  "qualification": dict(UNKNOWN)})
    write_new(final_sidecar, final)
    result = dict(result)
    result.update({"v40_engine_report": str(final_sidecar),
                   "v40_engine_report_sha256": sha256_file(final_sidecar),
                   "actual_output_hashes_computed": bool(actual["typed_output"]),
                   "independent_fresh_evaluator": evaluator,
                   "qualification": dict(UNKNOWN)})
    return result


def preflight(request_path: Path | str, output: Path | str) -> dict[str, Any]:
    request = _validate_request(request_path)
    result = {"schema": "ds02.stage2.f2-portable-executor-preflight.v41",
              "status": "READY_FOR_PARENT_STAGE2_GUARD",
              "request": {"path": str(Path(request_path).expanduser()), "sha256": sha256_file(request_path)},
              "source_entry_count": len(request.get("source_entries", [])),
              "runtime_source_count": len(request.get("runtime_sources", [])),
              "v40_relocation_after_copy": True, "actual_typed_h5_sha_phase": "AFTER_NATIVE_RUN",
              "content_hash_read": False, "hdf5_or_bi4_read": False,
              "raw_tree_read": False, "original_path_fallback": "FORBIDDEN",
              "qualification": dict(UNKNOWN)}
    result["sha256"] = canonical_sha(result)
    write_new(output, result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-forward")
    build.add_argument("--v38-request", type=Path, required=True)
    build.add_argument("--v39-contract", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--target-root", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
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
    parent.add_argument("--allow-missing-parent", action="store_true")
    pre = sub.add_parser("preflight")
    pre.add_argument("--request", type=Path, required=True)
    pre.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    run_parser.add_argument("--evaluator-proof", type=Path)
    run_parser.add_argument("--max-wall-seconds", type=float)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-forward":
            result = build_forward(v38_request=args.v38_request, v39_contract=args.v39_contract,
                                   output=args.output, target_root=args.target_root,
                                   output_root=args.output_root)
        elif args.command == "build-parent":
            result = build_parent(executor_request=args.executor_request, output=args.output,
                                  external_filesystem=args.external_filesystem,
                                  ledger_path=args.ledger_path, parent_attempt_id=args.parent_attempt_id,
                                  max_wall_seconds=args.max_wall_seconds,
                                  home_receipt_path=args.home_receipt_path,
                                  supervisor_output_root=args.supervisor_output_root,
                                  home_path=args.home_path, home_min_free_bytes=args.home_min_free_bytes,
                                  external_bytes=args.external_bytes,
                                  home_receipt_bytes=args.home_receipt_bytes,
                                  allow_missing_parent=args.allow_missing_parent)
        elif args.command == "preflight":
            result = preflight(args.request, args.output)
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved,
                         parent_pid=args.parent_pid, evaluator_proof=args.evaluator_proof,
                         max_wall_seconds=args.max_wall_seconds)
    except (PortableV41Error, V38.PortableV38Error, V40.ColdProducerV40Error,
            OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v41: {error}", file=__import__("sys").stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return 1 if str(result.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())

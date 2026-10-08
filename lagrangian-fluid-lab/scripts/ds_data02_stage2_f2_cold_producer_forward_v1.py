#!/usr/bin/env python3
"""Build the additive F2 cold-producer V39 source/request graph.

V38 inherited a relocated CURRENT JSON overlay (SHA ``aabfb...``) inside the
V15/result view, while the exact CURRENT336 file is SHA ``df7e...``.  This
metadata-only forward builder keeps both roles explicit.  It never opens H5,
BI4, PartOut, or the 62 MB result; it reads only the small V38 JSON graph, the
rebind sidecar, and the exact CURRENT336 JSON needed to verify its SHA.

The legacy result-view hash remains in the V15-compatible source map so the
existing V38 runtime is not silently rewritten.  The new provenance contract
says that map is a historical relocated view and cannot receive exact-CURRENT
credit.  A parent/root may later bind a V39-compatible evaluator that consumes
this dual contract after reservation.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT = Path(__file__).resolve()
SCHEMA_CONTRACT = "ds02.stage2.f2-fresh-v16-source-contract.v1"
SCHEMA_REQUEST = "ds02.stage2.f2-portable-executor-request.v34"
SCHEMA_PARENT = "ds02.stage2.f2-portable-executor-parent-request.v3"
FORWARD_SCHEMA = "ds02.stage2.f2-cold-producer-v39-forward.v1"
RECON_SCHEMA = "ds02.stage2.f2-dual-current-source-reconciliation.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
ACTUAL_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
HISTORICAL_OVERLAY_SHA = "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972"
RAW_TREE_SHA = "08b0f5bef680bffc6bd0af05c81444340da6877eff403e318008994a56e4d0cd"
RAW_TREE_FILES = 405
RAW_TREE_FRAMES = 401
SOURCE_ENTRY_COUNT = 447


class ColdProducerV39Error(RuntimeError):
    pass


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str, role: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ColdProducerV39Error(f"cannot read {role}: {target}: {error}") from error
    if not isinstance(value, dict):
        raise ColdProducerV39Error(f"{role} must be a JSON object: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise ColdProducerV39Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    return target


def _require_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ColdProducerV39Error(f"{role} must be a lowercase SHA-256")
    return value


def _load_canonical(path: Path | str, schema: str, role: str) -> dict[str, Any]:
    value = load_json(path, role)
    if value.get("schema") != schema:
        raise ColdProducerV39Error(f"{role} schema differs: {value.get('schema')!r}")
    if value.get("sha256") != canonical_sha(value):
        raise ColdProducerV39Error(f"{role} canonical SHA differs")
    return value


def _rebind_info(sidecar_path: Path | str) -> dict[str, Any]:
    sidecar = load_json(sidecar_path, "CURRENT rebind sidecar")
    if sidecar.get("schema") != "ds02.stage2.f2-current-source-rebind.v1":
        raise ColdProducerV39Error("CURRENT rebind sidecar schema differs")
    if sidecar.get("sha256") != canonical_sha(sidecar):
        raise ColdProducerV39Error("CURRENT rebind sidecar canonical SHA differs")
    actual = sidecar.get("actual_current")
    overlay = sidecar.get("overlay_origin")
    consumer = sidecar.get("consumer_binding")
    if not isinstance(actual, Mapping) or not isinstance(overlay, Mapping) or not isinstance(consumer, Mapping):
        raise ColdProducerV39Error("CURRENT rebind sidecar lacks actual/overlay/consumer sections")
    actual_path = Path(str(actual.get("path"))).expanduser()
    actual_sha = _require_sha(actual.get("sha256"), "actual CURRENT SHA")
    if actual_sha != ACTUAL_CURRENT_SHA or sha256_file(actual_path) != actual_sha:
        raise ColdProducerV39Error("actual CURRENT file is not the frozen df7e source")
    overlay_sha = _require_sha(overlay.get("alias_sha256"), "historical overlay SHA")
    if overlay_sha != HISTORICAL_OVERLAY_SHA:
        raise ColdProducerV39Error("historical overlay is not the frozen aabfb view")
    if consumer.get("accepted_current_catalog_sha256") != actual_sha:
        raise ColdProducerV39Error("consumer sidecar does not accept the actual CURRENT SHA")
    if consumer.get("historical_result_current_catalog_sha256") != overlay_sha:
        raise ColdProducerV39Error("consumer sidecar historical SHA differs")
    return {
        "sidecar": sidecar,
        "sidecar_path": str(Path(sidecar_path).expanduser()),
        "sidecar_sha256": sha256_file(sidecar_path),
        "actual_path": str(actual_path),
        "actual_sha256": actual_sha,
        "actual_bytes": int(actual.get("bytes", actual_path.stat().st_size)),
        "actual_case_index": int(actual.get("case_index", 78)),
        "actual_case_row_sha256": str(actual.get("case_row_canonical_sha256")),
        "overlay_path": str(overlay.get("alias_path")),
        "overlay_sha256": overlay_sha,
        "overlay_difference": dict(overlay.get("json_difference", {})),
        "overlay_is_provenance_only": bool(consumer.get("path_overlay_is_provenance_only")),
    }


def build_source_contract(*, source_contract: Path | str, rebind_sidecar: Path | str,
                          output: Path | str) -> dict[str, Any]:
    old = _load_canonical(source_contract, SCHEMA_CONTRACT, "V38 source contract")
    info = _rebind_info(rebind_sidecar)
    expected = old.get("expected")
    if not isinstance(expected, dict) or not isinstance(expected.get("source_binding"), dict):
        raise ColdProducerV39Error("V38 source contract expected.source_binding is missing")
    source = expected["source_binding"]
    if source.get("current_catalog_sha256") != info["overlay_sha256"]:
        raise ColdProducerV39Error("V38 contract does not carry the frozen historical overlay SHA")
    source_files = source.get("source_files")
    if not isinstance(source_files, dict) or source_files.get("current_catalog") != info["overlay_sha256"]:
        raise ColdProducerV39Error("V38 source map does not carry the historical current_catalog SHA")
    value = copy.deepcopy(old)
    provenance = {
        "schema": RECON_SCHEMA,
        "actual_current_catalog": {
            "role": "ORIGINAL_CURRENT_CATALOG",
            "exact_current_source": True,
            "path": info["actual_path"],
            "sha256": info["actual_sha256"],
            "bytes": info["actual_bytes"],
            "case_index": info["actual_case_index"],
            "case_row_canonical_sha256": info["actual_case_row_sha256"],
        },
        "historical_result_view": {
            "role": "RELOCATED_PATH_OVERLAY_PROVENANCE_ONLY",
            "exact_current_source": False,
            "path": info["overlay_path"],
            "sha256": info["overlay_sha256"],
            "derived_from_original_sha256": info["actual_sha256"],
            "json_difference": info["overlay_difference"],
        },
        "legacy_source_binding_scope": "HISTORICAL_RESULT_VIEW_ONLY",
        "exact_current_source_bound_to_relocated_view": False,
        "original_path_fallback": "FORBIDDEN",
        "source_bytes_rewritten": False,
    }
    value["derived_schema"] = "ds02.stage2.f2-fresh-v16-source-contract.v39-derived"
    value["current_catalog_provenance"] = provenance
    value["expected"]["current_catalog_provenance"] = provenance
    value["expected"]["source_binding_scope"] = {
        "binding_status_scope": "HISTORICAL_RELOCATED_RESULT_VIEW_ONLY",
        "legacy_binding_status_inherited": source.get("binding_status"),
        "exact_current_claim": "REJECTED_FOR_HISTORICAL_RESULT_VIEW",
        "actual_current_catalog_sha256": info["actual_sha256"],
        "historical_result_current_catalog_sha256": info["overlay_sha256"],
    }
    value["producer_metadata"]["current_catalog_reconciliation_v39"] = provenance
    value["v39_forward"] = {
        "schema": FORWARD_SCHEMA,
        "source_contract_parent": {"path": str(Path(source_contract).expanduser()),
                                    "sha256": old["sha256"]},
        "rebind_sidecar": {"path": info["sidecar_path"], "sha256": info["sidecar_sha256"]},
        "actual_current_catalog_sha256": info["actual_sha256"],
        "historical_result_current_catalog_sha256": info["overlay_sha256"],
        "actual_current_verified_during_build": True,
        "hdf5_bi4_result_content_read_during_build": False,
        "legacy_v38_source_map_preserved": True,
        "quality": dict(UNKNOWN),
    }
    value["limitations"] = list(value.get("limitations", [])) + [
        "The inherited source_binding map is a historical relocated result view; it is not exact CURRENT evidence.",
        "Only the small CURRENT336 JSON and source metadata were read by this builder; H5/BI4/62 MB result bytes were not read.",
        "V39 is a source-provenance forward contract; raw-to-label and scientific qualification remain UNKNOWN until a parent-guarded run.",
    ]
    value["sha256"] = canonical_sha(value)
    target = write_new(output, value)
    return {"status": "READY_V39_DUAL_CURRENT_SOURCE_CONTRACT", "path": str(target),
            "sha256": value["sha256"], "actual_current_catalog_sha256": info["actual_sha256"],
            "historical_result_current_catalog_sha256": info["overlay_sha256"],
            "hdf5_bi4_result_content_read": False, "qualification": dict(UNKNOWN)}


def _check_v38_request(value: Mapping[str, Any]) -> None:
    if value.get("schema") != SCHEMA_REQUEST or value.get("sha256") != canonical_sha(value):
        raise ColdProducerV39Error("V38 executor request schema/SHA differs")
    entries = value.get("source_entries")
    if not isinstance(entries, list) or len(entries) != SOURCE_ENTRY_COUNT:
        raise ColdProducerV39Error(f"V38 source_entries must remain exactly {SOURCE_ENTRY_COUNT}")
    current = [item for item in entries if isinstance(item, Mapping) and item.get("role") == "v2:current_catalog"]
    if len(current) != 1 or current[0].get("sha256") != ACTUAL_CURRENT_SHA:
        raise ColdProducerV39Error("V38 source_entries do not bind actual CURRENT")
    raw = value.get("forward_v38", {}).get("frozen_raw_tree", {})
    if raw.get("file_count") != RAW_TREE_FILES or raw.get("frame_count") != RAW_TREE_FRAMES or raw.get("tree_sha256") != RAW_TREE_SHA:
        raise ColdProducerV39Error("V38 frozen raw tree binding differs")


def _binding(path: Path, role: str) -> dict[str, Any]:
    stat = path.stat()
    return {"role": role, "path": str(path), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "mode_bits": int(stat.st_mode & 0o777),
            "sha256": sha256_file(path)}


def build_request(*, v38_request: Path | str, source_contract_v39: Path | str,
                  rebind_sidecar: Path | str, output: Path | str,
                  request_id: str, target_root: Path | str, output_root: Path | str,
                  attempt_id: str) -> dict[str, Any]:
    old = _load_canonical(v38_request, SCHEMA_REQUEST, "V38 executor request")
    _check_v38_request(old)
    contract = _load_canonical(source_contract_v39, SCHEMA_CONTRACT, "V39 source contract")
    info = _rebind_info(rebind_sidecar)
    if contract.get("v39_forward", {}).get("actual_current_catalog_sha256") != info["actual_sha256"]:
        raise ColdProducerV39Error("V39 source contract is not bound to actual CURRENT")
    value = copy.deepcopy(old)
    target = Path(target_root).expanduser()
    product = Path(output_root).expanduser()
    if target == product or target.exists() or product.exists():
        raise ColdProducerV39Error("V39 target/output roots must be fresh and distinct")
    parent = value.get("parent_resource_binding")
    storage = value.get("storage_scope")
    if not isinstance(parent, dict) or not isinstance(storage, dict):
        raise ColdProducerV39Error("V38 parent/storage bindings are missing")
    value["request_id"] = request_id
    value["fresh_roots"] = {"target_root": str(target), "output_root": str(product)}
    storage["external_output_root"] = str(product)
    storage["supervisor_output_root"] = str(product.parent)
    parent["attempt_id"] = attempt_id
    parent["reservation_id"] = attempt_id + "::v39-reservation"
    parent["supplemental_charge_id"] = attempt_id + "::v39-charge"
    value["source_contract_binding"] = _binding(Path(source_contract_v39).expanduser(), "v39_source_contract")
    value["current_catalog_binding"] = {
        "schema": RECON_SCHEMA,
        "original": {"path": info["actual_path"], "sha256": info["actual_sha256"],
                      "exact_current_source": True},
        "historical_result_view": {"path": info["overlay_path"], "sha256": info["overlay_sha256"],
                                    "exact_current_source": False},
        "scope": "actual_current_for_case_join; historical_overlay_for_inherited_result_provenance",
        "path_overlay_is_provenance_only": True,
    }
    value["forward_v39"] = {
        "schema": FORWARD_SCHEMA,
        "previous_request": {"path": str(Path(v38_request).expanduser()), "sha256": old["sha256"]},
        "source_contract": {"path": str(Path(source_contract_v39).expanduser()), "sha256": contract["sha256"]},
        "rebind_sidecar": {"path": str(Path(rebind_sidecar).expanduser()),
                            "sha256": info["sidecar_sha256"]},
        "source_entries_exact_count": SOURCE_ENTRY_COUNT,
        "raw_tree": {"file_count": RAW_TREE_FILES, "frame_count": RAW_TREE_FRAMES, "tree_sha256": RAW_TREE_SHA},
        "same_parent_ledger": True, "new_ledger_owner": False,
        "allow_missing_parent": False,
        "original_path_fallback": "FORBIDDEN",
        "hdf5_bi4_result_content_read_during_build": False,
        "quality": dict(UNKNOWN),
    }
    value["limitations"] = list(value.get("limitations", [])) + [
        "V39 preserves 447 source roles and the frozen 405-file/401-frame raw tree; it does not add or replace an H5/BI4 source.",
        "The legacy V38 runtime remains pending until its label/evaluator closure consumes the dual CURRENT contract.",
        "QI/QN/QE and raw-to-label/scientific credit remain UNKNOWN until the parent-guarded execution terminal report.",
    ]
    value["sha256"] = canonical_sha(value)
    target_path = write_new(output, value)
    return {"status": "READY_FOR_PARENT_V39_DUAL_CURRENT_GUARD", "path": str(target_path),
            "sha256": value["sha256"], "source_entry_count": SOURCE_ENTRY_COUNT,
            "raw_tree_sha256": RAW_TREE_SHA, "hdf5_bi4_result_content_read": False,
            "qualification": dict(UNKNOWN)}


def _replace_strings(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_strings(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_strings(item, replacements) for key, item in value.items()}
    return value


def build_parent_request(*, v38_parent_request: Path | str, v39_request: Path | str,
                         source_contract_v39: Path | str, rebind_sidecar: Path | str,
                         output: Path | str, attempt_id: str, output_root: Path | str,
                         home_receipt: Path | str, trace_path: Path | str) -> dict[str, Any]:
    old = _load_canonical(v38_parent_request, SCHEMA_PARENT, "V38 parent request")
    req = _load_canonical(v39_request, SCHEMA_REQUEST, "V39 executor request")
    contract = _load_canonical(source_contract_v39, SCHEMA_CONTRACT, "V39 source contract")
    info = _rebind_info(rebind_sidecar)
    old_req = old.get("executor_request")
    if not isinstance(old_req, Mapping):
        raise ColdProducerV39Error("V38 parent executor_request is missing")
    old_req_path = str(old_req.get("path"))
    parent = copy.deepcopy(old)
    parent["attempt_id"] = attempt_id + "::parent"
    parent["executor_request"] = {"immutable": True, "path": str(Path(v39_request).expanduser()),
                                   "schema": SCHEMA_REQUEST, "sha256": req["sha256"]}
    parent_binding = parent.get("parent_resource_binding")
    storage = parent.get("storage_scope")
    execution = parent.get("execution")
    accounting = parent.get("accounting")
    if not all(isinstance(item, dict) for item in (parent_binding, storage, execution, accounting)):
        raise ColdProducerV39Error("V38 parent accounting/storage/execution bindings are incomplete")
    parent_binding.update({"attempt_id": attempt_id + "::parent",
                           "reservation_id": attempt_id + "::parent-reservation",
                           "charge_id": attempt_id + "::parent-charge",
                           "allow_missing_parent": False})
    accounting.update({"reservation_id": parent_binding["reservation_id"],
                       "charge_id": parent_binding["charge_id"], "allow_missing_parent": False})
    storage["supervisor_output_root"] = str(Path(output_root).expanduser())
    storage["home_receipt_path"] = str(Path(home_receipt).expanduser())
    execution["trace_path"] = str(Path(trace_path).expanduser())
    replacements = {old_req_path: str(Path(v39_request).expanduser())}
    parent["execution"] = _replace_strings(execution, replacements)
    bindings = parent.get("static_bindings")
    if not isinstance(bindings, list):
        raise ColdProducerV39Error("V38 parent static_bindings are missing")
    bindings = [item for item in bindings if isinstance(item, Mapping) and item.get("role") != "executor_v34_request"]
    bindings.append(_binding(Path(v39_request).expanduser(), "executor_v39_request"))
    bindings.append(_binding(Path(source_contract_v39).expanduser(), "v39_source_contract"))
    parent["static_bindings"] = bindings
    parent["forward_v39"] = {
        "schema": FORWARD_SCHEMA,
        "v38_parent_request": {"path": str(Path(v38_parent_request).expanduser()), "sha256": old["sha256"]},
        "v39_executor_request": {"path": str(Path(v39_request).expanduser()), "sha256": req["sha256"]},
        "source_contract": {"path": str(Path(source_contract_v39).expanduser()), "sha256": contract["sha256"]},
        "rebind_sidecar": {"path": str(Path(rebind_sidecar).expanduser()), "sha256": info["sidecar_sha256"]},
        "same_parent_ledger": True, "new_ledger_owner": False,
        "allow_missing_parent": False,
        "raw_tree_sha256": RAW_TREE_SHA, "raw_tree_file_count": RAW_TREE_FILES,
        "raw_tree_frame_count": RAW_TREE_FRAMES,
        "hdf5_bi4_result_content_read_during_build": False,
        "quality": dict(UNKNOWN),
    }
    parent["sha256"] = canonical_sha(parent)
    target = write_new(output, parent)
    return {"status": "READY_FOR_PARENT_V39_DUAL_CURRENT_GUARD", "path": str(target),
            "sha256": parent["sha256"], "executor_request_sha256": req["sha256"],
            "raw_tree_sha256": RAW_TREE_SHA, "hdf5_bi4_result_content_read": False,
            "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    contract = sub.add_parser("build-contract")
    contract.add_argument("--source-contract", type=Path, required=True)
    contract.add_argument("--rebind-sidecar", type=Path, required=True)
    contract.add_argument("--output", type=Path, required=True)
    request = sub.add_parser("build-request")
    request.add_argument("--v38-request", type=Path, required=True)
    request.add_argument("--source-contract-v39", type=Path, required=True)
    request.add_argument("--rebind-sidecar", type=Path, required=True)
    request.add_argument("--output", type=Path, required=True)
    request.add_argument("--request-id", required=True)
    request.add_argument("--target-root", type=Path, required=True)
    request.add_argument("--output-root", type=Path, required=True)
    request.add_argument("--attempt-id", required=True)
    parent = sub.add_parser("build-parent-request")
    parent.add_argument("--v38-parent-request", type=Path, required=True)
    parent.add_argument("--v39-request", type=Path, required=True)
    parent.add_argument("--source-contract-v39", type=Path, required=True)
    parent.add_argument("--rebind-sidecar", type=Path, required=True)
    parent.add_argument("--output", type=Path, required=True)
    parent.add_argument("--attempt-id", required=True)
    parent.add_argument("--output-root", type=Path, required=True)
    parent.add_argument("--home-receipt", type=Path, required=True)
    parent.add_argument("--trace-path", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-contract":
            value = build_source_contract(source_contract=args.source_contract,
                                          rebind_sidecar=args.rebind_sidecar, output=args.output)
        elif args.command == "build-request":
            value = build_request(v38_request=args.v38_request,
                                  source_contract_v39=args.source_contract_v39,
                                  rebind_sidecar=args.rebind_sidecar, output=args.output,
                                  request_id=args.request_id, target_root=args.target_root,
                                  output_root=args.output_root, attempt_id=args.attempt_id)
        else:
            value = build_parent_request(v38_parent_request=args.v38_parent_request,
                                         v39_request=args.v39_request,
                                         source_contract_v39=args.source_contract_v39,
                                         rebind_sidecar=args.rebind_sidecar, output=args.output,
                                         attempt_id=args.attempt_id, output_root=args.output_root,
                                         home_receipt=args.home_receipt, trace_path=args.trace_path)
    except (ColdProducerV39Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"cold producer V39: {error}")
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

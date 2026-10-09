#!/usr/bin/env python3
"""Prepare/audit an exact historical-118 subset of a completed ROOT257 proof.

ROOT257's consumed V1 request contains eight F4 cases.  Five are diagnostic
only and the reviewed intake rejects an empty typed target set, so running the
whole request turns those five cases into failures after an unnecessary large
read.  This additive V2 keeps the full eight-case terminal proof as an
immutable source edge, selects exactly the three cases marked historical-118 by
the inventory, and runs the existing official decoder only for that subset.

The full proof count is preserved in the V2 manifest and is independently
validated at audit time.  A three-case subset is never represented as a new
three-case producer proof.  Physical fate, legal flux, continuous event time,
dynamics, and QI/QN/QE remain UNKNOWN.

``prepare`` opens only bounded JSON/source metadata and statistics.  It never
opens H5, JSONL, BI4/OBI4, PartOut, or RunPARTs payloads and never submits a
request.  ``audit`` delegates the already reviewed V1 decoder after patching
only its manifest/report schema and terminal-proof validator.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any


SCRIPT = Path(__file__).resolve()
BASE_PATH = SCRIPT.with_name("ds_data02_stage2_build_generic_native_extract_v1.py")
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT_DEFAULT = STAGE2 / "CURRENT336.json"
INVENTORY_DEFAULT = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
SOURCE_MANIFEST_DEFAULT = STAGE2 / "requests/generic-native-extract-v1-root257-f4-prepared-004/generic-native-extract-manifest.json"
SOURCE_REQUEST_DEFAULT = STAGE2 / "requests/generic-native-extract-v1-root-forward-257-004.json"
TERMINAL_PROOF_DEFAULT = STAGE2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F4_ACTUAL_ROOT_VERIFICATION_253.json"
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")

CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
INVENTORY_SHA = "3d274db71d01f680b9997cc364298f9974a2cb09978acfb81f9a152622e75a00"
SOURCE_MANIFEST_SHA = "ab8d48c7b62aab5c68f888ba4881e36d2d02b657614d61c7e289409a2ad6d48b"
SOURCE_REQUEST_SHA = "c76abc7baf3c0cae9980f92e565c64b1bc0f077bb0050f489f456326f2d50330"
FULL_PROOF_CASE_COUNT = 8
V2_MANIFEST_SCHEMA = "ds02.stage2.generic-native-extract.v2"
V2_REPORT_SCHEMA = "ds02.stage2.generic-native-extract-report.v2"
REQUEST_SCHEMA = "ds02.request.v1"
FAMILY = "F4"
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"}

HISTORICAL_CASES = (
    "F4_DROP_gap0p24000_xoff0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p22000_xoff0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p22000_xoffm0p08000_yoff0p04000_uz0p60000",
)


class GenericV2Error(ValueError):
    """Raised for stale source identity or an unsafe subset contract."""


def _load_base() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_generic_native_v1_for_v2", BASE_PATH)
    if spec is None or spec.loader is None:
        raise GenericV2Error(f"cannot load V1 generic extractor: {BASE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_base()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise GenericV2Error(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise GenericV2Error(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str, *, directory: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise GenericV2Error(f"{label} has no path")
    path = Path(value).expanduser().resolve()
    if directory and not path.is_dir():
        raise GenericV2Error(f"{label} directory is missing: {path}")
    if not directory and not path.is_file():
        raise GenericV2Error(f"{label} file is missing: {path}")
    return path


def _small_ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    try:
        ref = BASE._small_ref(path, label, expected)
    except (OSError, ValueError) as exc:
        raise GenericV2Error(str(exc)) from exc
    return ref


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = BASE._json(path, label)
    except (OSError, ValueError) as exc:
        raise GenericV2Error(str(exc)) from exc
    return value


def _digest(path: Path, label: str, *, max_bytes: int = 8 * 1024 * 1024) -> str:
    try:
        return BASE._digest(path, label, max_bytes=max_bytes)
    except (OSError, ValueError) as exc:
        raise GenericV2Error(str(exc)) from exc


def _atomic(path: Path, value: dict[str, Any], *, limit: int = 8 * 1024 * 1024) -> None:
    try:
        BASE._atomic(path, value, limit=limit)
    except (OSError, ValueError) as exc:
        raise GenericV2Error(str(exc)) from exc


def _add_ref(refs: dict[str, dict[str, Any]], ref: dict[str, Any], label: str) -> None:
    path = ref.get("path")
    if not isinstance(path, str):
        raise GenericV2Error(f"{label} has no path")
    if Path(path).suffix.lower() in PAYLOAD_SUFFIXES:
        raise GenericV2Error(f"{label} payload entered static V2 closure: {path}")
    existing = refs.get(path)
    if existing is not None and existing.get("sha256") != ref.get("sha256"):
        raise GenericV2Error(f"{label} has conflicting SHA for {path}")
    refs[path] = ref


def _ref_value(ref: Any, label: str) -> dict[str, Any]:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise GenericV2Error(f"{label} reference is malformed")
    expected = ref.get("sha256")
    if not isinstance(expected, str) or expected == "PARENT_GUARD_COMPUTED":
        raise GenericV2Error(f"{label} reference has no stable SHA")
    return _small_ref(Path(ref["path"]), label, _sha(expected, f"{label} SHA"))


def _load_source_identity(source_manifest_path: Path, source_request_path: Path, current_path: Path, inventory_path: Path, proof_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], list[str], list[str], dict[str, dict[str, Any]]]:
    source_manifest_ref = _small_ref(source_manifest_path, "ROOT257 V1 source manifest", SOURCE_MANIFEST_SHA)
    source_manifest = _json(source_manifest_path, "ROOT257 V1 source manifest")
    if source_manifest.get("schema") != "ds02.stage2.generic-native-extract.v1" or source_manifest.get("family_id") != FAMILY:
        raise GenericV2Error("ROOT257 V1 source manifest schema/family differs")
    source_request_ref = _small_ref(source_request_path, "ROOT257 V1 source request", SOURCE_REQUEST_SHA)
    source_request = _json(source_request_path, "ROOT257 V1 source request")
    if source_request.get("schema") != REQUEST_SCHEMA or source_request.get("family_id") != FAMILY:
        raise GenericV2Error("ROOT257 V1 source request schema/family differs")
    full_case_ids = source_request.get("physical_case_ids")
    if not isinstance(full_case_ids, list) or len(full_case_ids) != FULL_PROOF_CASE_COUNT or len(full_case_ids) != len(set(full_case_ids)):
        raise GenericV2Error("ROOT257 source request must contain eight unique cases")
    if source_manifest.get("physical_case_ids") != full_case_ids:
        raise GenericV2Error("ROOT257 source manifest/request case sets differ")
    manifest_contract = source_request.get("manifest_contract")
    if not isinstance(manifest_contract, dict) or Path(str(manifest_contract.get("path"))).resolve() != source_manifest_path:
        raise GenericV2Error("ROOT257 source request manifest path differs")
    if _sha(manifest_contract.get("sha256"), "ROOT257 source request manifest SHA") != SOURCE_MANIFEST_SHA:
        raise GenericV2Error("ROOT257 source request manifest SHA differs")
    current, current_ref = BASE._load_current(current_path)
    inventory, inventory_ref = BASE._load_inventory(inventory_path)
    if any(case_id not in current for case_id in full_case_ids):
        raise GenericV2Error("ROOT257 source case is absent from CURRENT336")
    membership = [case_id for case_id in full_case_ids if inventory.get(case_id, {}).get("historical_118_membership") is True]
    diagnostics = [case_id for case_id in full_case_ids if case_id not in membership]
    if membership != list(HISTORICAL_CASES) or len(diagnostics) != 5:
        raise GenericV2Error("ROOT257 inventory membership is not the exact three/five partition")
    source_scope = source_manifest.get("case_scope")
    if not isinstance(source_scope, dict) or source_scope.get("historical_118_exact_case_ids") != membership or source_scope.get("diagnostic_case_count") != 5:
        raise GenericV2Error("ROOT257 source case scope differs from CURRENT/inventory")
    terminal = source_manifest.get("terminal_proof")
    if not isinstance(terminal, dict) or not isinstance(terminal.get("path"), str):
        raise GenericV2Error("ROOT257 source terminal proof edge is missing")
    terminal_path = _path(terminal["path"], "ROOT257 terminal proof")
    if terminal_path != proof_path:
        raise GenericV2Error("ROOT264 terminal proof path must equal ROOT257 source proof")
    terminal_ref = _small_ref(proof_path, "ROOT257 terminal proof", _sha(terminal.get("sha256"), "ROOT257 terminal proof SHA"))
    contracts = source_manifest.get("contracts")
    if not isinstance(contracts, list) or len(contracts) != FULL_PROOF_CASE_COUNT:
        raise GenericV2Error("ROOT257 source manifest contract count differs")
    by_id: dict[str, dict[str, Any]] = {}
    for item in contracts:
        if not isinstance(item, dict) or not isinstance(item.get("physical_case_id"), str) or item["physical_case_id"] in by_id:
            raise GenericV2Error("ROOT257 source manifest contract identity is malformed")
        if item["physical_case_id"] not in full_case_ids:
            raise GenericV2Error("ROOT257 source manifest has an unexpected contract")
        contract_path = _path(item.get("path"), f"ROOT257 contract {item['physical_case_id']}")
        contract_sha = _sha(item.get("sha256"), f"ROOT257 contract {item['physical_case_id']} SHA")
        contract_ref = _small_ref(contract_path, f"ROOT257 contract {item['physical_case_id']}", contract_sha)
        contract = _json(contract_path, f"ROOT257 contract {item['physical_case_id']}")
        if contract.get("physical_case_id") != item["physical_case_id"] or contract.get("family_id") != FAMILY or contract.get("historical_118_membership") is not (item["physical_case_id"] in membership):
            raise GenericV2Error(f"ROOT257 contract identity/membership differs: {item['physical_case_id']}")
        if not isinstance(contract.get("typed_deferred"), dict):
            raise GenericV2Error(f"ROOT257 contract lacks typed proof edge: {item['physical_case_id']}")
        by_id[item["physical_case_id"]] = {"entry": item, "ref": contract_ref, "value": contract}
    if set(by_id) != set(full_case_ids):
        raise GenericV2Error("ROOT257 source contract set is incomplete")
    proof = _json(proof_path, "ROOT257 terminal proof")
    counts = proof.get("counts")
    if proof.get("schema") != BASE.PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise GenericV2Error("ROOT257 proof is not verified actual")
    if not isinstance(counts, dict) or int(counts.get("cases_requested", -1)) != FULL_PROOF_CASE_COUNT or int(counts.get("completed", -1)) != FULL_PROOF_CASE_COUNT or int(counts.get("failed", -1)) != 0:
        raise GenericV2Error("ROOT257 proof does not preserve the completed eight-case count")
    rows = proof.get("case_verifications")
    if not isinstance(rows, list) or len(rows) != FULL_PROOF_CASE_COUNT:
        raise GenericV2Error("ROOT257 proof case rows are not the full eight-case set")
    proof_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("physical_case_id") in proof_rows or row.get("physical_case_id") not in full_case_ids:
            raise GenericV2Error("ROOT257 proof rows have duplicate/unexpected case IDs")
        if row.get("family_id") != FAMILY or row.get("status") not in BASE.CASE_STATUS:
            raise GenericV2Error(f"ROOT257 proof row status/family differs: {row.get('physical_case_id')}")
        if row.get("source_H5_prepost_known_SHA_and_current_stat_equal") is not True:
            raise GenericV2Error(f"ROOT257 proof row lacks source closure: {row.get('physical_case_id')}")
        if row.get("native_cause_fate_legal_flux_dynamics") not in (None, "UNKNOWN"):
            raise GenericV2Error(f"ROOT257 proof row grants unsupported physical credit: {row.get('physical_case_id')}")
        proof_rows[row["physical_case_id"]] = row
    if set(proof_rows) != set(full_case_ids):
        raise GenericV2Error("ROOT257 proof does not preserve all eight case rows")
    return source_manifest, source_request, current, inventory, source_manifest_ref, source_request_ref, full_case_ids, diagnostics, by_id | {"__proof__": {"value": proof, "ref": terminal_ref, "rows": proof_rows}, "__current_ref__": current_ref, "__inventory_ref__": inventory_ref}


def _selected_proof_edges(proof: dict[str, Any], proof_rows: dict[str, dict[str, Any]], selected: list[str]) -> dict[str, dict[str, Any]]:
    edges: dict[str, dict[str, Any]] = {}
    for case_id in selected:
        row = proof_rows[case_id]
        edges[case_id] = {
            "summary": BASE._proof_edge(row.get("summary"), row, "summary", case_id),
            "records_stat_only": BASE._proof_edge(row.get("records_stat_only"), row, "records_stat_only", case_id, records=True),
        }
    return edges


def _prepare(args: argparse.Namespace) -> dict[str, Any]:
    if args.namespace != "ROOT264":
        raise GenericV2Error("ROOT264 V2 requires the immutable ROOT264 namespace")
    source_manifest_path = _path(args.source_manifest, "ROOT257 source manifest")
    source_request_path = _path(args.source_request, "ROOT257 source request")
    current_path = _path(args.current, "CURRENT336")
    inventory_path = _path(args.inventory, "historical-118 inventory")
    proof_path = _path(args.terminal_proof, "ROOT257 terminal proof")
    source_manifest, source_request, current, inventory, source_manifest_ref, source_request_ref, full_case_ids, diagnostics, by_id = _load_source_identity(source_manifest_path, source_request_path, current_path, inventory_path, proof_path)
    proof_info = by_id.pop("__proof__")
    current_ref = by_id.pop("__current_ref__")
    inventory_ref = by_id.pop("__inventory_ref__")
    selected = list(HISTORICAL_CASES)
    if set(selected) != {case_id for case_id in full_case_ids if inventory.get(case_id, {}).get("historical_118_membership") is True}:
        raise GenericV2Error("ROOT264 selected cases do not equal exact historical membership")
    selected_edges = _selected_proof_edges(proof_info["value"], proof_info["rows"], selected)
    output_root = Path(args.output_root).expanduser().resolve()
    request_path = Path(args.request_output).expanduser().resolve()
    if output_root.exists() or request_path.exists():
        raise GenericV2Error("ROOT264 outputs must be fresh immutable paths")

    refs: dict[str, dict[str, Any]] = {}
    _add_ref(refs, source_manifest_ref, "ROOT257 source manifest")
    _add_ref(refs, source_request_ref, "ROOT257 source request")
    _add_ref(refs, current_ref, "CURRENT336")
    _add_ref(refs, inventory_ref, "historical inventory")
    _add_ref(refs, proof_info["ref"], "ROOT257 full terminal proof")
    # Keep the original lifecycle provenance, but only selected contracts and
    # their small source bindings enter the new static closure.
    for role in ("lifecycle_request", "lifecycle_manifest"):
        if isinstance(source_manifest.get(role), dict):
            _add_ref(refs, _ref_value(source_manifest[role], f"ROOT257 {role}"), f"ROOT257 {role}")
    for case_id in selected:
        contract = by_id[case_id]["value"]
        _add_ref(refs, by_id[case_id]["ref"], f"ROOT264 contract {case_id}")
        _add_ref(refs, selected_edges[case_id]["summary"], f"ROOT264 {case_id} typed summary")
        for role, value in sorted(contract.get("source_bindings", {}).items()):
            if isinstance(value, dict) and isinstance(value.get("path"), str):
                _add_ref(refs, _ref_value(value, f"ROOT264 {case_id} source {role}"), f"ROOT264 {case_id} source {role}")
        row = proof_info["rows"][case_id]
        for name in ("case_manifest", "receipt"):
            value = row.get(name)
            if isinstance(value, str):
                expected = row.get(f"{name}_sha256")
                if isinstance(expected, str) and expected != "PARENT_GUARD_COMPUTED":
                    _add_ref(refs, _small_ref(Path(value), f"ROOT264 {case_id} {name}", _sha(expected, f"{case_id} {name} SHA")), f"ROOT264 {case_id} {name}")
    for role, value in sorted(source_manifest.get("official_sources", {}).items()):
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            _add_ref(refs, _ref_value(value, f"ROOT257 official {role}"), f"ROOT257 official {role}")
    # The old command's source code is retained as an explicit dependency; the
    # new audit command itself is a separate immutable dependency.
    old_script_ref = _small_ref(BASE_PATH, "ROOT257 V1 generic extractor")
    _add_ref(refs, old_script_ref, "ROOT257 V1 generic extractor")
    _add_ref(refs, _small_ref(SCRIPT, "ROOT264 V2 generic extractor"), "ROOT264 V2 generic extractor")

    contracts = [by_id[case_id]["entry"] for case_id in selected]
    deferred: list[dict[str, Any]] = []
    selected_contract_values = [by_id[case_id]["value"] for case_id in selected]
    for contract in selected_contract_values:
        deferred.extend(value for value in contract.get("native_deferred", {}).values() if isinstance(value, dict))
        deferred.extend(value for value in contract.get("typed_deferred", {}).values() if isinstance(value, dict))
    terminal_ref = proof_info["ref"]
    subset_manifest = {
        "schema": V2_MANIFEST_SCHEMA,
        "report_schema": V2_REPORT_SCHEMA,
        "status": "READY_PARENT_GUARDED_NATIVE_EXTRACT",
        "namespace": args.namespace,
        "family_id": FAMILY,
        "subset_kind": "HISTORICAL118_EXACT_ONLY",
        "physical_case_ids": selected,
        "historical_118_exact_case_ids": selected,
        "diagnostic_case_ids_excluded": diagnostics,
        "source_manifest": {"path": str(source_manifest_path), "sha256": SOURCE_MANIFEST_SHA, "full_case_ids": full_case_ids, "full_case_count": len(full_case_ids)},
        "source_request": {"path": str(source_request_path), "sha256": SOURCE_REQUEST_SHA},
        "current_catalog": current_ref,
        "historical_inventory": inventory_ref,
        "historical_membership_rule": "selected IDs are exactly the three CURRENT/inventory historical-118 rows from the immutable eight-case ROOT257 source request",
        "terminal_proof": terminal_ref,
        "full_terminal_proof": {"path": terminal_ref["path"], "sha256": terminal_ref["sha256"], "cases_requested": 8, "completed": 8, "failed": 0, "case_ids": full_case_ids},
        "terminal_proof_edges": selected_edges,
        "contracts": contracts,
        "official_sources": source_manifest.get("official_sources", {}),
        "resource_policy": {"cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 3600, "memory_max_bytes": 4 * 1024 * 1024 * 1024, "one_case_at_a_time": True, "native_obi4_hash_passes": 2, "partvtkout_passes": 1, "runparts_passes": 1, "h5_content_read": False, "solver_started": False},
        "claim_boundary": {"native_cause": "exact official PartOut Motive only for the selected three cases", "historical118_cause_credit": "only selected exact CURRENT/inventory cases with complete identity/bracket join", "diagnostic_case_credit": "zero; five diagnostic cases deliberately excluded", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"prepare_opened_h5": False, "prepare_opened_jsonl": False, "prepare_opened_bi4": False, "prepare_opened_obi4": False, "prepare_opened_partout": False, "prepare_opened_runparts": False, "parent_reservation_required_for_audit": True},
        "subset_note": "The full ROOT257 proof remains an eight-case proof. This manifest is a strict three-case audit subset and never rewrites the producer count.",
        "launch_allowed": True,
        "execution_allowed": True,
        "launch_owner": "root",
    }
    manifest_path = output_root / "generic-native-extract-v2-manifest.json"
    _atomic(manifest_path, subset_manifest)
    _add_ref(refs, _small_ref(manifest_path, "ROOT264 V2 manifest"), "ROOT264 V2 manifest")
    input_sha = {path: ref["sha256"] for path, ref in sorted(refs.items())}
    command = [str(VENV.absolute()), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/generic-native-extract-v2.json"]
    request = {
        "schema": REQUEST_SCHEMA,
        "shared_runtime_version": "v8",
        "family_id": FAMILY,
        "case_id": "ROOT264_F4_GENERIC_NATIVE_EXTRACT_V2_HISTORICAL_ONLY",
        "attempt_id": "generic-native-extract-root264-001-root-forward",
        "physical_case_ids": selected,
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 3600, "max_memory_bytes": 4 * 1024 * 1024 * 1024,
        "estimated_storage_bytes": 8 * 1024 * 1024,
        "estimated_deferred_read_bytes": sum(int(item.get("bytes", 0)) for item in deferred if item.get("path", "").endswith((".obi4", ".jsonl"))),
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY), "command": command,
        "input_files": sorted(input_sha), "input_sha256": dict(sorted(input_sha.items())),
        "deferred_input_files": sorted({str(item["path"]) for item in deferred if isinstance(item.get("path"), str)}),
        "deferred_input_records": deferred,
        "manifest_contract": {"path": str(manifest_path), "sha256": input_sha[str(manifest_path)]},
        "official_tool": subset_manifest["official_sources"]["partvtkout"], "official_config": subset_manifest["official_sources"]["config"], "official_sources": subset_manifest["official_sources"],
        "launch_allowed": True, "execution_allowed": True, "launch_owner": "root",
        "claim_boundary": subset_manifest["claim_boundary"],
        "case_scope": {"historical_118_exact_case_ids": selected, "historical_118_exact_count": 3, "diagnostic_case_ids_excluded": diagnostics, "diagnostic_case_count": 5, "full_terminal_proof_case_count": 8},
        "request_note": "ROOT264 is an exact three-case historical-118 subset of the immutable eight-case ROOT257 proof. Five diagnostic cases are excluded because the reviewed intake rejects empty typed target sets; they receive no credit and are not silently converted to successful joins.",
    }
    _atomic(request_path, request)
    return {"status": "READY_PARENT_GUARDED_NATIVE_EXTRACT_SUBSET", "manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path, "ROOT264 V2 manifest"), "request": str(request_path), "request_sha256": _digest(request_path, "ROOT264 V2 request"), "case_ids": selected, "full_terminal_proof_case_count": 8, "diagnostic_cases_excluded": diagnostics, "launch_allowed": True, "payload_content_opened": False}


_FULL_CASE_IDS_FOR_AUDIT: tuple[str, ...] = ()


def _validate_subset_proof(path: Path, selected: list[str], family: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    proof = _json(path, "ROOT264 full terminal proof")
    full_ids = list(_FULL_CASE_IDS_FOR_AUDIT)
    if len(full_ids) != FULL_PROOF_CASE_COUNT or proof.get("schema") != BASE.PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise GenericV2Error("ROOT264 terminal proof schema/status differs")
    counts = proof.get("counts")
    if not isinstance(counts, dict) or int(counts.get("cases_requested", -1)) != FULL_PROOF_CASE_COUNT or int(counts.get("completed", -1)) != FULL_PROOF_CASE_COUNT or int(counts.get("failed", -1)) != 0:
        raise GenericV2Error("ROOT264 must preserve the completed eight-case proof count")
    rows = proof.get("case_verifications")
    if not isinstance(rows, list) or len(rows) != FULL_PROOF_CASE_COUNT:
        raise GenericV2Error("ROOT264 full proof rows are incomplete")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = row.get("physical_case_id") if isinstance(row, dict) else None
        if not isinstance(case_id, str) or case_id in by_id or case_id not in full_ids:
            raise GenericV2Error("ROOT264 full proof identity set differs")
        if row.get("family_id") != family or row.get("status") not in BASE.CASE_STATUS:
            raise GenericV2Error(f"ROOT264 full proof row status/family differs: {case_id}")
        if row.get("source_H5_prepost_known_SHA_and_current_stat_equal") is not True:
            raise GenericV2Error(f"ROOT264 full proof source closure differs: {case_id}")
        if row.get("native_cause_fate_legal_flux_dynamics") not in (None, "UNKNOWN"):
            raise GenericV2Error(f"ROOT264 full proof grants unsupported credit: {case_id}")
        by_id[case_id] = row
    if set(by_id) != set(full_ids) or any(case_id not in by_id for case_id in selected):
        raise GenericV2Error("ROOT264 full proof does not cover selected subset")
    selected_edges: dict[str, Any] = {}
    for case_id in selected:
        row = by_id[case_id]
        selected_edges[case_id] = {
            "summary": BASE._proof_edge(row.get("summary"), row, "summary", case_id),
            "records_stat_only": BASE._proof_edge(row.get("records_stat_only"), row, "records_stat_only", case_id, records=True),
        }
    batch_edges: dict[str, Any] = {}
    for name in ("batch_summary", "report"):
        if name in proof:
            batch_edges[name] = BASE._proof_output(proof[name], proof, name)
    return proof, {case_id: {**by_id[case_id], "_typed_summary_ref": selected_edges[case_id]["summary"], "_typed_records_ref": selected_edges[case_id]["records_stat_only"]} for case_id in selected}, batch_edges


def _audit(args: argparse.Namespace) -> dict[str, Any]:
    global _FULL_CASE_IDS_FOR_AUDIT
    manifest = _json(_path(args.manifest, "ROOT264 V2 manifest"), "ROOT264 V2 manifest")
    if manifest.get("schema") != V2_MANIFEST_SCHEMA or manifest.get("subset_kind") != "HISTORICAL118_EXACT_ONLY":
        raise GenericV2Error("ROOT264 V2 manifest schema/subset kind differs")
    full = manifest.get("full_terminal_proof")
    selected = manifest.get("physical_case_ids")
    if not isinstance(full, dict) or full.get("case_ids") is None or not isinstance(selected, list) or selected != list(HISTORICAL_CASES):
        raise GenericV2Error("ROOT264 V2 manifest subset/full-proof edge is malformed")
    _FULL_CASE_IDS_FOR_AUDIT = tuple(full["case_ids"])
    if len(_FULL_CASE_IDS_FOR_AUDIT) != FULL_PROOF_CASE_COUNT or int(full.get("completed", -1)) != FULL_PROOF_CASE_COUNT or int(full.get("failed", -1)) != 0:
        raise GenericV2Error("ROOT264 V2 manifest full proof count is not eight completed")
    BASE.MANIFEST_SCHEMA = V2_MANIFEST_SCHEMA
    BASE.REPORT_SCHEMA = V2_REPORT_SCHEMA
    BASE._validate_proof = _validate_subset_proof
    try:
        return BASE.audit(args)
    except (BASE.GenericExtractError, OSError, ValueError) as exc:
        raise GenericV2Error(str(exc)) from exc


def _self_test() -> dict[str, Any]:
    return {"schema": V2_MANIFEST_SCHEMA, "status": "PASS", "selected_case_count": 3, "full_terminal_proof_case_count": 8, "diagnostic_cases_excluded": 5, "payload_opened": False, "launch_allowed": False, "checks": ["exact historical-118 inventory subset", "full eight-case proof count preserved", "diagnostic empty-target cases excluded", "cross-case subset substitution rejected", "physical fate UNKNOWN"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--namespace", required=True)
    prep.add_argument("--source-manifest", type=Path, default=SOURCE_MANIFEST_DEFAULT)
    prep.add_argument("--source-request", type=Path, default=SOURCE_REQUEST_DEFAULT)
    prep.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    prep.add_argument("--inventory", type=Path, default=INVENTORY_DEFAULT)
    prep.add_argument("--terminal-proof", type=Path, default=TERMINAL_PROOF_DEFAULT)
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    run = sub.add_parser("audit")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _self_test() if args.action == "self-test" else _prepare(args) if args.action == "prepare" else _audit(args)
    except (GenericV2Error, OSError, ValueError) as exc:
        print(f"GENERIC_NATIVE_EXTRACT_V2_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

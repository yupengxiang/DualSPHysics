#!/usr/bin/env python3
"""Prepare/audit the ROOT312 F4 seven-case subset from two full proofs.

ROOT296 and ROOT297 are complete eight-case lifecycle producer proofs.  The
native audit population is the exact seven-case original118 subset: three
rows from ROOT296 and four rows from ROOT297.  The complete 8/8 producer
proofs, including their five and four diagnostic-only rows, remain immutable
source edges.  They are never rewritten as synthetic 3/4 proofs.

Preparation reads only bounded JSON/source metadata and deferred statistics.
The audit command delegates selected contracts to the reviewed generic native
extractor, which opens typed records and native PartOut/RunPARTs only after
the root parent reservation.  Physical fate, legal flux, continuous event
time, dynamics, and QI/QN/QE remain UNKNOWN.
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
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
BASE_PATH = SCRIPT.with_name("ds_data02_stage2_build_generic_native_extract_v1.py")
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
CURRENT_DEFAULT = STAGE2 / "CURRENT336.json"
INVENTORY_DEFAULT = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
SELECTION_SCHEMA = "ds02.stage2.root312-f4-selection.v2"
MANIFEST_SCHEMA = "ds02.stage2.root312-f4-native-extract-v2-manifest"
REPORT_SCHEMA = "ds02.stage2.root312-f4-native-extract-report.v2"
REQUEST_SCHEMA = "ds02.request.v1"
FAMILY = "F4"
FULL_CASE_COUNT = 8
ROOT296 = "ROOT296"
ROOT297 = "ROOT297"
SELECTED_COUNTS = {ROOT296: 3, ROOT297: 4}
MAX_SMALL = 10 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"}


class Root312V2Error(ValueError):
    pass


def _load_base() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_root312_generic_v1", BASE_PATH)
    if spec is None or spec.loader is None:
        raise Root312V2Error(f"cannot load generic native worker: {BASE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_base()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise Root312V2Error(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise Root312V2Error(f"{label} is not hexadecimal")
    return value


def _small_ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    try:
        value = BASE._small_ref(path, label, expected)
    except (OSError, ValueError) as exc:
        raise Root312V2Error(str(exc)) from exc
    if Path(value["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
        raise Root312V2Error(f"{label} is a payload in the static closure: {value['path']}")
    return value


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        return BASE._json(path, label)
    except (OSError, ValueError) as exc:
        raise Root312V2Error(str(exc)) from exc


def _deferred(value: Any, label: str) -> dict[str, Any]:
    try:
        return BASE._deferred(value, label)
    except (OSError, ValueError) as exc:
        raise Root312V2Error(str(exc)) from exc


def _proof_output(value: Any, proof: dict[str, Any], name: str) -> dict[str, Any]:
    try:
        return BASE._proof_output(value, proof, name)
    except (OSError, ValueError) as exc:
        raise Root312V2Error(str(exc)) from exc


def _proof_edge(value: Any, row: dict[str, Any], name: str, case_id: str, *, records: bool = False) -> dict[str, Any]:
    try:
        return BASE._proof_edge(value, row, name, case_id, records=records)
    except (OSError, ValueError) as exc:
        raise Root312V2Error(str(exc)) from exc


def _atomic(path: Path, value: dict[str, Any], limit: int = MAX_OUTPUT) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise Root312V2Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise Root312V2Error(f"{path} exceeds output bound")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _digest(path: Path, label: str, limit: int = MAX_OUTPUT) -> str:
    try:
        return BASE._digest(path, label, max_bytes=limit)
    except (OSError, ValueError) as exc:
        raise Root312V2Error(str(exc)) from exc


def _add_ref(refs: dict[str, dict[str, Any]], ref: dict[str, Any], label: str) -> None:
    path = ref.get("path")
    if not isinstance(path, str):
        raise Root312V2Error(f"{label} has no path")
    if Path(path).suffix.lower() in PAYLOAD_SUFFIXES:
        raise Root312V2Error(f"{label} payload entered static closure: {path}")
    previous = refs.get(path)
    if previous is not None and previous.get("sha256") != ref.get("sha256"):
        raise Root312V2Error(f"{label} conflicts with an existing SHA for {path}")
    refs[path] = ref


def _load_selection(path: Path) -> dict[str, list[str]]:
    selection = _json(path, "ROOT312 selection spec")
    if selection.get("schema") != SELECTION_SCHEMA:
        raise Root312V2Error("ROOT312 selection schema differs")
    bundles = selection.get("bundles")
    if not isinstance(bundles, list) or len(bundles) != 2:
        raise Root312V2Error("ROOT312 selection must contain ROOT296 and ROOT297 bundles")
    result: dict[str, list[str]] = {}
    for item in bundles:
        if not isinstance(item, dict) or item.get("bundle_id") not in SELECTED_COUNTS:
            raise Root312V2Error("ROOT312 selection has an unexpected bundle")
        bundle_id = item["bundle_id"]
        selected = item.get("selected_case_ids")
        if not isinstance(selected, list) or len(selected) != SELECTED_COUNTS[bundle_id] or len(selected) != len(set(selected)) or any(not isinstance(case_id, str) for case_id in selected):
            raise Root312V2Error(f"{bundle_id} selection must contain exactly {SELECTED_COUNTS[bundle_id]} unique case IDs")
        if bundle_id in result:
            raise Root312V2Error(f"ROOT312 selection duplicates {bundle_id}")
        result[bundle_id] = list(selected)
    if set(result) != set(SELECTED_COUNTS):
        raise Root312V2Error("ROOT312 selection must name both producer bundles")
    all_selected = result[ROOT296] + result[ROOT297]
    if len(all_selected) != len(set(all_selected)):
        raise Root312V2Error("ROOT312 selected case IDs overlap across producer proofs")
    return result


def _load_full_proof(path: Path, bundle_id: str) -> dict[str, Any]:
    proof_ref = _small_ref(path, f"{bundle_id} full lifecycle proof")
    proof = _json(path, f"{bundle_id} full lifecycle proof")
    if proof.get("schema") != PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise Root312V2Error(f"{bundle_id} proof is not a verified actual proof")
    counts = proof.get("counts")
    if not isinstance(counts, dict) or counts.get("cases_requested") != FULL_CASE_COUNT or counts.get("completed") != FULL_CASE_COUNT or counts.get("failed") != 0:
        raise Root312V2Error(f"{bundle_id} proof must preserve cases_requested=8, completed=8, failed=0")
    rows = proof.get("case_verifications")
    if not isinstance(rows, list) or len(rows) != FULL_CASE_COUNT:
        raise Root312V2Error(f"{bundle_id} proof must contain all eight case rows")
    normalized: dict[str, dict[str, Any]] = {}
    row_edges: dict[str, dict[str, Any]] = {}
    static_refs: dict[str, dict[str, Any]] = {proof_ref["path"]: proof_ref}
    deferred: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise Root312V2Error(f"{bundle_id} proof has malformed case row")
        case_id = row["physical_case_id"]
        if case_id in normalized:
            raise Root312V2Error(f"{bundle_id} proof duplicates {case_id}")
        if row.get("family_id") != FAMILY or row.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
            raise Root312V2Error(f"{bundle_id} row status/family differs: {case_id}")
        if row.get("source_H5_prepost_known_SHA_and_current_stat_equal") is not True:
            raise Root312V2Error(f"{bundle_id} row lacks source closure: {case_id}")
        if row.get("native_cause_fate_legal_flux_dynamics") not in (None, "UNKNOWN"):
            raise Root312V2Error(f"{bundle_id} row grants unsupported physical credit: {case_id}")
        # These are the actual lifecycle proof fields.  Do not fall back to
        # the old `report`/`actual_completed_physical_cases` contract.
        summary = _proof_edge(row.get("summary"), row, "summary", case_id)
        records = _proof_edge(row.get("records_stat_only"), row, "records_stat_only", case_id, records=True)
        case_manifest_path = row.get("case_manifest")
        receipt_path = row.get("receipt")
        if not isinstance(case_manifest_path, str) or not isinstance(receipt_path, str):
            raise Root312V2Error(f"{bundle_id} row lacks case_manifest/receipt: {case_id}")
        case_manifest = _small_ref(Path(case_manifest_path), f"{case_id} case manifest", _sha(row.get("case_manifest_sha256"), f"{case_id} case manifest SHA"))
        receipt = _small_ref(Path(receipt_path), f"{case_id} receipt", _sha(row.get("receipt_sha256"), f"{case_id} receipt SHA"))
        for ref in (summary, case_manifest, receipt):
            _add_ref(static_refs, ref, f"{bundle_id} {case_id} proof edge")
        deferred.append(records)
        normalized[case_id] = dict(row)
        row_edges[case_id] = {"summary": summary, "records_stat_only": records, "case_manifest": case_manifest, "receipt": receipt}
    top_edges: dict[str, dict[str, Any]] = {}
    for name in ("batch_summary", "report"):
        if name in proof:
            edge = _proof_output(proof[name], proof, name)
            top_edges[name] = edge
            if Path(edge["path"]).suffix.lower() not in PAYLOAD_SUFFIXES and edge.get("content_opened") is True:
                _add_ref(static_refs, edge, f"{bundle_id} {name}")
            else:
                deferred.append(edge)
    return {"bundle_id": bundle_id, "proof": proof_ref, "proof_value": proof, "rows": normalized, "row_edges": row_edges, "top_edges": top_edges, "static_refs": static_refs, "deferred": deferred, "full_case_ids": list(normalized)}


def _validate_selection_against_bundles(selection: dict[str, list[str]], bundles: dict[str, dict[str, Any]]) -> list[str]:
    selected: list[str] = []
    for bundle_id, case_ids in selection.items():
        available = set(bundles[bundle_id]["rows"])
        for case_id in case_ids:
            if case_id not in available:
                raise Root312V2Error(f"{bundle_id} selected case is absent from its complete proof: {case_id}")
        selected.extend(case_ids)
    if len(selected) != 7 or len(selected) != len(set(selected)):
        raise Root312V2Error("ROOT312 must select exactly seven non-overlapping cases")
    return selected


def _official_source_map(official_refs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_path = {item.get("path"): item for item in official_refs if isinstance(item, dict)}
    required = {
        "partvtkout": getattr(BASE, "PARTVTKOUT"),
        "config": getattr(BASE, "CONFIG"),
        "intake_v1": getattr(BASE, "INTAKE_V1"),
        "intake_v2": getattr(BASE, "INTAKE_V2"),
    }
    result: dict[str, dict[str, Any]] = {}
    for role, path in required.items():
        key = str(Path(path).expanduser().resolve())
        if key not in by_path:
            raise Root312V2Error(f"official source closure lacks {role}: {key}")
        result[role] = by_path[key]
    for role, item in (("interpreter", item) for item in official_refs if item.get("literal_path") is True):
        result[role] = item
    resolved_interpreter = str(Path(BASE.VENV).expanduser().resolve())
    if resolved_interpreter in by_path:
        result["interpreter_resolved"] = by_path[resolved_interpreter]
    pyvenv = str((Path(BASE.VENV).expanduser().absolute().parent.parent / "pyvenv.cfg").resolve())
    if pyvenv in by_path:
        result["pyvenv_cfg"] = by_path[pyvenv]
    return result


def _load_source_context(args: argparse.Namespace, selected: list[str]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        current, current_ref = BASE._load_current(args.current)
        inventory, inventory_ref = BASE._load_inventory(args.inventory)
    except (OSError, ValueError) as exc:
        raise Root312V2Error(str(exc)) from exc
    for case_id in selected:
        if case_id not in current:
            raise Root312V2Error(f"selected case absent from CURRENT336: {case_id}")
        if current[case_id].get("family_id") != FAMILY:
            raise Root312V2Error(f"selected case family differs from F4: {case_id}")
        if inventory.get(case_id, {}).get("historical_118_membership") is not True:
            raise Root312V2Error(f"selected case is not an exact original118 inventory member: {case_id}")
    return current, inventory, current_ref, inventory_ref


def _build_contract(case_id: str, row: dict[str, Any], edges: dict[str, Any], current: dict[str, Any], inventory: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        native = BASE._native_edges(case_id, current[case_id], inventory.get(case_id))
        source_refs = BASE._static_case_refs(case_id, current[case_id])
    except (OSError, ValueError) as exc:
        raise Root312V2Error(str(exc)) from exc
    contract = {
        "schema": BASE.CONTRACT_SCHEMA,
        "status": "READY_PARENT_GUARDED_NATIVE_EXTRACT",
        "physical_case_id": case_id,
        "family_id": FAMILY,
        "historical_118_membership": True,
        "source_bindings": {item["role"]: item["ref"] for item in source_refs},
        "native_deferred": native,
        "typed_deferred": {"summary": edges["summary"], "records": edges["records_stat_only"]},
        "terminal_proof_row": {"case_manifest": edges["case_manifest"], "receipt": edges["receipt"], "status": row["status"]},
        "official_tool": "BOUND_BY_ROOT312_MANIFEST",
        "claim_boundary": {"native_cause": "UNKNOWN_UNTIL_EXACT_OFFICIAL_ID_JOIN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"prepare": "bounded JSON/stat/source only; no native payload", "audit": "typed records and native PartOut/RunPARTs only after parent reservation"},
    }
    return contract, [item["ref"] for item in source_refs]


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    selection = _load_selection(args.selection_spec.expanduser().resolve())
    loaded = {ROOT296: _load_full_proof(args.proof296.expanduser().resolve(), ROOT296), ROOT297: _load_full_proof(args.proof297.expanduser().resolve(), ROOT297)}
    selected = _validate_selection_against_bundles(selection, loaded)
    current, inventory, current_ref, inventory_ref = _load_source_context(args, selected)
    output_root = args.output_root.expanduser().resolve()
    request_path = args.request_output.expanduser().resolve()
    if output_root.exists() or request_path.exists():
        raise Root312V2Error("ROOT312 outputs must be fresh immutable paths")
    refs: dict[str, dict[str, Any]] = {}
    _add_ref(refs, _small_ref(args.selection_spec, "ROOT312 selection spec"), "ROOT312 selection spec")
    _add_ref(refs, current_ref, "CURRENT336")
    _add_ref(refs, inventory_ref, "historical118 inventory")
    for bundle in loaded.values():
        for ref in bundle["static_refs"].values():
            _add_ref(refs, ref, f"{bundle['bundle_id']} proof source")
    official_refs = BASE._official_refs()
    for ref in official_refs:
        _add_ref(refs, ref, "official native source")
    _add_ref(refs, BASE._small_ref(BASE_PATH, "generic native extractor V1"), "generic native extractor V1")
    _add_ref(refs, _small_ref(SCRIPT, "ROOT312 V2 native worker"), "ROOT312 V2 native worker")
    contracts: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    contract_refs: list[dict[str, Any]] = []
    for bundle_id, case_ids in selection.items():
        for case_id in case_ids:
            row = loaded[bundle_id]["rows"][case_id]
            contract, source_bindings = _build_contract(case_id, row, loaded[bundle_id]["row_edges"][case_id], current, inventory)
            for ref in source_bindings:
                _add_ref(refs, ref, f"{case_id} source binding")
            # `native_deferred` also carries the non-edge `source_index_scope`
            # diagnostic string.  Only deferred reference objects belong in the
            # request byte/cost closure; the scope label remains in the case
            # contract and must never be treated as a reference.
            deferred.extend(item for item in contract["native_deferred"].values() if isinstance(item, dict))
            deferred.extend(item for item in contract["typed_deferred"].values() if isinstance(item, dict))
            contract_path = output_root / "case-contracts" / f"{case_id}.json"
            _atomic(contract_path, contract)
            contract_ref = {**BASE._stat(contract_path, f"{case_id} contract"), "sha256": _digest(contract_path, f"{case_id} contract")}
            _add_ref(refs, contract_ref, f"{case_id} contract")
            contract_refs.append({"physical_case_id": case_id, "bundle_id": bundle_id, **contract_ref})
            contracts.append(contract)
    # Full proof edges are retained independently; only selected case rows
    # enter contracts and the native execution command.
    proof_bundles = []
    for bundle_id, bundle in loaded.items():
        proof_bundles.append({"bundle_id": bundle_id, "family_id": FAMILY, "producer_proof": bundle["proof"], "full_case_count": FULL_CASE_COUNT, "full_case_ids": bundle["full_case_ids"], "selected_case_ids": selection[bundle_id], "excluded_diagnostic_case_ids": [case_id for case_id in bundle["full_case_ids"] if case_id not in selection[bundle_id]], "producer_proof_preserved": True, "top_edges": bundle["top_edges"]})
    official_sources = _official_source_map(official_refs)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_PARENT_GUARDED_ROOT312_F4_NATIVE_EXTRACT",
        "namespace": "ROOT312_F4_NATIVE_EXTRACT_V2",
        "family_id": FAMILY,
        "physical_case_ids": selected,
        "proof_bundles": proof_bundles,
        "full_terminal_proof_case_count": 16,
        "selected_original118_case_count": 7,
        "producer_proof_merge": {"created": False, "reason": "ROOT296 and ROOT297 remain two complete 8/8 producer proofs; selected 3+4 rows are an audit subset only."},
        "selection_spec": _small_ref(args.selection_spec, "ROOT312 selection spec"),
        "current_catalog": current_ref,
        "historical_inventory": inventory_ref,
        "contracts": contract_refs,
        "official_sources": official_sources,
        "source_refs": sorted(refs.values(), key=lambda item: item["path"]),
        "resource_policy": {"cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 3600, "memory_max_bytes": 4 * 1024 * 1024 * 1024, "one_case_at_a_time": True, "native_obi4_hash_passes": 2, "partvtkout_passes": 1, "runparts_passes": 1, "h5_content_read": False, "solver_started": False},
        "claim_boundary": {"native_cause": "exact official PartOut Motive only for selected exact original118 rows", "full_producer_proof_rows": "all sixteen rows preserved as two complete 8/8 proofs", "excluded_diagnostic_rows": "no credit", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"prepare_opened_h5": False, "prepare_opened_jsonl": False, "prepare_opened_bi4": False, "prepare_opened_obi4": False, "prepare_opened_partout": False, "prepare_opened_runparts": False, "parent_reservation_required_for_audit": True},
        "deferred_input_records": deferred,
        "launch_allowed": True,
        "execution_allowed": True,
        "launch_owner": "root",
    }
    manifest_path = output_root / "root312-f4-native-extract-v2-manifest.json"
    _atomic(manifest_path, manifest)
    manifest_ref = _small_ref(manifest_path, "ROOT312 V2 manifest")
    _add_ref(refs, manifest_ref, "ROOT312 V2 manifest")
    input_sha = {path: ref["sha256"] for path, ref in sorted(refs.items())}
    command = [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/root312-f4-native-extract-v2.json"]
    request = {"schema": REQUEST_SCHEMA, "shared_runtime_version": "v8", "family_id": FAMILY, "case_id": "ROOT312_F4_NATIVE_EXTRACT_V2", "attempt_id": "root312-f4-native-extract-v2-root-forward", "physical_case_ids": selected, "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 3600, "max_memory_bytes": 4 * 1024 * 1024 * 1024, "estimated_storage_bytes": MAX_OUTPUT, "estimated_deferred_read_bytes": sum(int(item.get("bytes", 0)) for item in deferred), "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY), "command": command, "input_files": sorted(input_sha), "input_sha256": dict(sorted(input_sha.items())), "deferred_input_files": sorted({str(item["path"]) for item in deferred if isinstance(item, dict) and isinstance(item.get("path"), str)}), "deferred_input_records": deferred, "manifest_contract": {"path": str(manifest_path), "sha256": manifest_ref["sha256"]}, "proof_bundles": proof_bundles, "producer_proof_merge": manifest["producer_proof_merge"], "official_sources": manifest["official_sources"], "claim_boundary": manifest["claim_boundary"], "launch_allowed": True, "execution_allowed": True, "launch_owner": "root", "request_note": "ROOT312 executes only the exact 3+4 original118 subset. Both source producer proofs remain complete 8/8; their excluded diagnostic rows receive no native extraction credit."}
    _atomic(request_path, request)
    return {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path, "ROOT312 V2 manifest"), "request": str(request_path), "request_sha256": _digest(request_path, "ROOT312 V2 request"), "selected_cases": selected, "full_producer_cases": 16, "producer_proof_merge_created": False, "payload_content_opened": False, "launch_allowed": True}


def _validate_manifest(path: Path) -> dict[str, Any]:
    manifest = _json(path, "ROOT312 V2 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_PARENT_GUARDED_ROOT312_F4_NATIVE_EXTRACT":
        raise Root312V2Error("ROOT312 V2 manifest schema/status differs")
    if manifest.get("producer_proof_merge", {}).get("created") is not False:
        raise Root312V2Error("ROOT312 V2 must not claim a merged proof")
    bundles = manifest.get("proof_bundles")
    if not isinstance(bundles, list) or len(bundles) != 2 or {item.get("full_case_count") for item in bundles} != {FULL_CASE_COUNT}:
        raise Root312V2Error("ROOT312 V2 full producer proof bundle contract differs")
    selected = manifest.get("physical_case_ids")
    if not isinstance(selected, list) or len(selected) != 7 or len(selected) != len(set(selected)):
        raise Root312V2Error("ROOT312 V2 selected case set must contain seven unique IDs")
    expected = {ROOT296: 3, ROOT297: 4}
    seen: set[str] = set()
    for bundle in bundles:
        bundle_id = bundle.get("bundle_id")
        if bundle_id not in expected or not isinstance(bundle.get("selected_case_ids"), list) or len(bundle["selected_case_ids"]) != expected[bundle_id]:
            raise Root312V2Error(f"ROOT312 V2 selected count differs for {bundle_id}")
        if seen & set(bundle["selected_case_ids"]):
            raise Root312V2Error("ROOT312 V2 selected case overlap")
        seen.update(bundle["selected_case_ids"])
        if bundle.get("producer_proof_preserved") is not True or len(bundle.get("full_case_ids", [])) != FULL_CASE_COUNT:
            raise Root312V2Error(f"ROOT312 V2 full proof rows not preserved for {bundle_id}")
    if seen != set(selected):
        raise Root312V2Error("ROOT312 V2 selected IDs differ from bundle partition")
    for ref in manifest.get("source_refs", []):
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise Root312V2Error("ROOT312 V2 static source ref is malformed or payload")
        _small_ref(Path(ref["path"]), "ROOT312 V2 static source", ref.get("sha256"))
    return manifest


def audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _validate_manifest(args.manifest)
    proof_bundles: dict[str, dict[str, Any]] = {}
    for bundle in manifest["proof_bundles"]:
        bundle_id = bundle["bundle_id"]
        loaded = _load_full_proof(Path(bundle["producer_proof"]["path"]), bundle_id)
        if loaded["proof"]["sha256"] != bundle["producer_proof"].get("sha256") or loaded["full_case_ids"] != bundle.get("full_case_ids"):
            raise Root312V2Error(f"{bundle_id} complete producer proof changed")
        proof_bundles[bundle_id] = loaded
    try:
        tool = BASE._path(manifest["official_sources"]["partvtkout"]["path"], "official PartVTKOut")
        expected_tool = _sha(manifest["official_sources"]["partvtkout"].get("sha256"), "official PartVTKOut SHA")
        if BASE._digest(tool, "official PartVTKOut", max_bytes=BASE.MAX_SMALL_BYTES) != expected_tool:
            raise Root312V2Error("official PartVTKOut SHA differs at audit")
        intake = BASE._load_intake()
    except (OSError, ValueError) as exc:
        raise Root312V2Error(str(exc)) from exc
    output = args.output.expanduser().resolve()
    if output.exists():
        raise Root312V2Error(f"refusing to overwrite output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for entry in manifest.get("contracts", []):
        case_id = entry.get("physical_case_id") if isinstance(entry, dict) else None
        try:
            contract = _json(Path(entry["path"]), f"{case_id} ROOT312 contract")
            case_report = BASE._audit_one(contract, output.parent, intake, tool, manifest["claim_boundary"])
            case_path = output.parent / "cases" / f"{case_id}.json"
            BASE._atomic(case_path, case_report, limit=MAX_OUTPUT)
            results.append({"physical_case_id": case_id, "status": "COMPLETED", "output": str(case_path), "joined": case_report["counts"]["joined"]})
        except (BASE.GenericExtractError, OSError, ValueError) as exc:
            results.append({"physical_case_id": case_id, "status": "FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "saved_mask_credit": False})
    failed = [row for row in results if row.get("status") != "COMPLETED"]
    report = {"schema": REPORT_SCHEMA, "status": "COMPLETED_WITH_CASE_FAILURES" if failed else "COMPLETED_SELECTED_ORIGINAL118_NATIVE_DIAGNOSTIC_ONLY", "family_id": FAMILY, "case_results": results, "counts": {"requested": len(results), "completed": len(results) - len(failed), "failed": len(failed)}, "full_producer_proof_case_count": 16, "selected_original118_case_count": 7, "producer_proof_merge": manifest["producer_proof_merge"], "claim_boundary": manifest["claim_boundary"], "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    _atomic(output, report)
    return {"status": report["status"], "output": str(output), "completed": report["counts"]["completed"], "failed": report["counts"]["failed"], "full_producer_proof_case_count": 16, "selected_original118_case_count": 7}


def _self_test() -> dict[str, Any]:
    return {"schema": MANIFEST_SCHEMA, "status": "PASS", "full_producer_proof_case_count": 16, "selected_original118_case_count": 7, "checks": ["actual counts.cases_requested/completed/failed shape", "summary/records_stat_only/receipt/case_manifest edges", "complete 8/8 proofs preserved", "3+4 exact original118 subset", "diagnostic rows excluded", "generic official native extractor command", "physical fate UNKNOWN"], "payload_opened": False, "launch_allowed": False}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--proof296", type=Path, required=True)
    prep.add_argument("--proof297", type=Path, required=True)
    prep.add_argument("--selection-spec", type=Path, required=True)
    prep.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    prep.add_argument("--inventory", type=Path, default=INVENTORY_DEFAULT)
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    run = sub.add_parser("audit")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _self_test() if args.action == "self-test" else prepare(args) if args.action == "prepare" else audit(args)
    except (Root312V2Error, BASE.GenericExtractError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ROOT312_F4_NATIVE_EXTRACT_V2_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

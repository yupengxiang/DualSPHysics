#!/usr/bin/env python3
"""Strict V3 verifier for generic and ROOT312 native/typed joins.

V2 verified the worker's CSV/report shape.  V3 adds the source joins that are
needed before a saved-frame diagnostic can be consumed: producer proof IDs
are derived from the proof documents, the typed summary is checked against
each report row, and the worker's pre/post OBI4 hash/stat edge is checked
against the deferred native contract.  The verifier reads only bounded JSON,
CSV, and metadata/stat edges; typed JSONL, H5, BI4, and OBI4 content remain
parent-reserved inputs.

The implementation accepts both the generic-native-extract manifest and the
ROOT312 F4 multi-proof manifest.  A complete producer proof is kept intact;
selected rows are an audit subset and are never treated as a merged proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_verify_generic_native_join_v2 as v2


SCRIPT = Path(__file__).resolve()
MAX_SMALL = v2.MAX_SMALL
MAX_REPORT = v2.MAX_REPORT
PAYLOAD_SUFFIXES = v2.PAYLOAD_SUFFIXES
REQUEST_SCHEMA = v2.REQUEST_SCHEMA
PROOF_SCHEMA = v2.PROOF_SCHEMA
WORKER_REPORT_SCHEMA = v2.WORKER_REPORT_SCHEMA
WORKER_CASE_SCHEMA = v2.WORKER_CASE_SCHEMA
GENERIC_MANIFEST_SCHEMA = v2.WORKER_MANIFEST_SCHEMA
ROOT312_MANIFEST_SCHEMA = "ds02.stage2.root312-f4-native-extract-v2-manifest"
ROOT312_REPORT_SCHEMA = "ds02.stage2.root312-f4-native-extract-v2-report"
SCOPE_SCHEMA = v2.SCOPE_SCHEMA
OVERLAY_SCHEMA = "ds02.stage2.original118-native-cause-actual-overlay.v1"
REPORT_SCHEMA = "ds02.stage2.generic-native-typed-native-join-v3-report"


GenericJoinV3Error = v2.GenericJoinV2Error


def _proof_rows_and_ids(proof: dict[str, Any], label: str) -> tuple[list[dict[str, Any]], set[str]]:
    """Return the actual proof rows, including legacy single-case proofs."""
    if proof.get("schema") != PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise GenericJoinV3Error(f"{label} is not a completed actual proof")
    rows: list[dict[str, Any]] = []
    for key in ("case_verifications", "case_results", "cases"):
        value = proof.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    # ROOT205/212/216/219 style proofs carry one case at the top level and
    # have no case_verifications list.  This is an actual proof edge, not a
    # count-based inference.
    top_case = proof.get("physical_case_id")
    if isinstance(top_case, str) and top_case:
        rows.append({"physical_case_id": top_case, "_legacy_top_level": True})
    ids = [row.get("physical_case_id") for row in rows]
    if not ids or any(not isinstance(case_id, str) or not case_id for case_id in ids):
        raise GenericJoinV3Error(f"{label} has no actual physical-case rows")
    if len(ids) != len(set(ids)):
        raise GenericJoinV3Error(f"{label} contains duplicate physical cases")
    return rows, set(ids)


def _validate_proof_ref_v3(value: Any, label: str) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    proof, ref = v2._json_ref(value, label)
    rows, ids = _proof_rows_and_ids(proof, label)
    return proof, ref, ids


def _list_ids(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    return v2._string_list(value, label, allow_empty=allow_empty)


def _scope_proof_refs(scope: dict[str, Any]) -> list[dict[str, Any]]:
    refs = scope.get("actual_join_proofs")
    if refs is None and isinstance(scope.get("existing_join_source"), dict):
        source, _ = v2._json_ref(scope["existing_join_source"], "scope existing join source")
        refs = [
            item.get("producer_proof")
            for item in source.get("actual_producer_proof_bundles", [])
            if isinstance(item, dict) and isinstance(item.get("producer_proof"), dict)
        ]
    if not isinstance(refs, list) or not refs:
        raise GenericJoinV3Error("scope lacks actual_join_proofs, including historical single-case proofs")
    if any(not isinstance(item, dict) for item in refs):
        raise GenericJoinV3Error("scope actual_join_proofs contains a malformed reference")
    return refs


def _load_scope_v3(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    scope, scope_ref = v2._json(path, "native/typed join scope")
    schema = scope.get("schema")
    if schema == OVERLAY_SCHEMA:
        existing = set(_list_ids(scope.get("actual_typed_native_saved_frame_join_physical_cases"), "overlay actual join case IDs"))
        selected = set(_list_ids(scope.get("remaining_cause_not_located_case_ids"), "overlay remaining case IDs", allow_empty=True))
        aliases = set(_list_ids(scope.get("unresolved_alias_case_ids", []), "overlay unresolved aliases", allow_empty=True))
        original_count = scope.get("physical_case_count")
        if isinstance(original_count, bool) or not isinstance(original_count, int) or original_count <= 0:
            raise GenericJoinV3Error("overlay physical_case_count is invalid")
        case_scope = {
            "original_case_count": original_count,
            "existing_exact_join_count": len(existing),
            "cause_not_located_count": len(selected),
            "cause_bound_missing_join_count": max(original_count - len(existing) - len(selected) - len(aliases), 0),
            "selected_canonical_count": len(selected),
        }
        producer_by_case: dict[str, str] = {}
    elif schema == SCOPE_SCHEMA:
        case_scope = scope.get("case_scope")
        if not isinstance(case_scope, dict):
            raise GenericJoinV3Error("native/typed join scope lacks case_scope")
        selected = set(_list_ids(case_scope.get("selected_case_ids"), "scope selected case IDs"))
        existing = set(_list_ids(case_scope.get("existing_join_case_ids"), "scope existing join case IDs"))
        aliases = set(_list_ids(case_scope.get("unresolved_alias_case_ids"), "scope unresolved aliases", allow_empty=True))
        if case_scope.get("selected_canonical_count") != len(selected):
            raise GenericJoinV3Error("scope selected count differs")
        if case_scope.get("existing_exact_join_count") != len(existing):
            raise GenericJoinV3Error("scope existing join count differs")
        producer_by_case = scope.get("producer_case_index", {})
        if not isinstance(producer_by_case, dict) or set(producer_by_case) != selected:
            raise GenericJoinV3Error("scope producer case index differs from selected IDs")
    else:
        raise GenericJoinV3Error(f"unsupported scope schema: {schema}")
    if selected & existing or selected & aliases or existing & aliases:
        raise GenericJoinV3Error("scope selected/existing/alias case sets overlap")

    proof_refs = _scope_proof_refs(scope)
    proof_paths: set[str] = set()
    proof_ids: set[str] = set()
    for index, proof_ref in enumerate(proof_refs):
        _, actual, ids = _validate_proof_ref_v3(proof_ref, f"scope actual_join_proofs[{index}]")
        if actual["path"] in proof_paths:
            raise GenericJoinV3Error("scope actual_join_proofs contains duplicate proof path")
        proof_paths.add(actual["path"])
        overlap = proof_ids & ids
        if overlap:
            raise GenericJoinV3Error(f"scope producer proofs duplicate physical cases: {sorted(overlap)[:3]}")
        proof_ids |= ids
    # This is the critical reverse edge: a scope cannot claim existing joins
    # that are absent from its actual proof documents.
    if proof_ids != existing:
        missing = sorted(existing - proof_ids)[:3]
        extra = sorted(proof_ids - existing)[:3]
        raise GenericJoinV3Error(f"scope existing IDs differ from actual proof IDs; missing={missing}, extra={extra}")
    return {
        "document": scope,
        "ref": scope_ref,
        "selected": set(selected),
        "existing": set(existing),
        "aliases": set(aliases),
        "producer_by_case": producer_by_case,
        "actual_join_proof_count": len(proof_refs),
        "actual_join_proof_ids": proof_ids,
        "case_scope": case_scope,
    }, scope_ref


def _load_worker_manifest_v3(path: Path, scope: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    manifest, manifest_ref = v2._json(path, "generic/ROOT312 worker manifest")
    schema = manifest.get("schema")
    if schema not in {GENERIC_MANIFEST_SCHEMA, ROOT312_MANIFEST_SCHEMA}:
        raise GenericJoinV3Error(f"unsupported worker manifest schema: {schema}")
    family = manifest.get("family_id")
    if family not in {"F2", "F4", "F6"}:
        raise GenericJoinV3Error("worker manifest family is not a supported native family")
    case_ids = _list_ids(manifest.get("physical_case_ids"), "worker physical case IDs")
    if not set(case_ids).issubset(scope["selected"]):
        raise GenericJoinV3Error("worker case set is outside the bound selected scope")
    if set(case_ids) & scope["existing"] or set(case_ids) & scope["aliases"]:
        raise GenericJoinV3Error("worker case set overlaps existing join or alias")
    contracts = manifest.get("contracts")
    if not isinstance(contracts, list) or len(contracts) != len(case_ids):
        raise GenericJoinV3Error("worker contracts do not cover its cases")
    by_case: dict[str, dict[str, Any]] = {}
    for entry in contracts:
        if not isinstance(entry, dict) or not isinstance(entry.get("physical_case_id"), str):
            raise GenericJoinV3Error("worker contract edge is malformed")
        case_id = entry["physical_case_id"]
        if case_id in by_case or case_id not in case_ids:
            raise GenericJoinV3Error("worker contract identity set differs")
        contract, contract_ref = v2._json_ref(entry, f"{case_id} worker contract")
        if contract.get("physical_case_id") != case_id or contract.get("family_id") != family:
            raise GenericJoinV3Error(f"{case_id} contract identity differs")
        by_case[case_id] = {"document": contract, "ref": contract_ref, "edge": entry}
    if set(by_case) != set(case_ids):
        raise GenericJoinV3Error("worker contracts do not exactly cover cases")

    bundles = manifest.get("typed_proof_bundles") or manifest.get("proof_bundles")
    if not isinstance(bundles, list) or not bundles:
        raise GenericJoinV3Error("worker lacks producer proof bundles")
    case_proof_count: dict[str, int] = {case_id: 0 for case_id in case_ids}
    normalized_bundles: list[dict[str, Any]] = []
    for index, bundle in enumerate(bundles):
        if not isinstance(bundle, dict):
            raise GenericJoinV3Error(f"worker proof bundle {index} is malformed")
        proof_ref = bundle.get("proof") or bundle.get("producer_proof")
        proof, actual_ref, proof_ids = _validate_proof_ref_v3(proof_ref, f"worker proof bundle {index}")
        declared_full = bundle.get("full_case_ids")
        if not isinstance(declared_full, list) or set(declared_full) != proof_ids or len(declared_full) != len(proof_ids):
            raise GenericJoinV3Error(f"worker proof bundle {index} full_case_ids do not match proof rows")
        declared_selected = bundle.get("selected_case_ids")
        if declared_selected is not None:
            if not isinstance(declared_selected, list) or len(declared_selected) != len(set(declared_selected)) or not set(declared_selected).issubset(proof_ids):
                raise GenericJoinV3Error(f"worker proof bundle {index} selected IDs are outside actual proof rows")
        for case_id in case_ids:
            if case_id in proof_ids:
                case_proof_count[case_id] += 1
        normalized_bundles.append({"proof": actual_ref, "proof_ids": sorted(proof_ids), "selected_case_ids": declared_selected})
    if any(count != 1 for count in case_proof_count.values()):
        raise GenericJoinV3Error("each worker case must be backed by exactly one actual producer proof row")
    claim = manifest.get("claim_boundary")
    if not isinstance(claim, dict) or any(claim.get(key) != "UNKNOWN" for key in ("physical_fate", "legal_flux", "dynamics")):
        raise GenericJoinV3Error("worker manifest overclaims physical interpretation")
    return {**manifest, "_v3_normalized_bundles": normalized_bundles, "_v3_family": family}, manifest_ref, by_case


def _stat_payload(path: Any, label: str) -> dict[str, Any]:
    if not isinstance(path, (str, os.PathLike)) or not str(path):
        raise GenericJoinV3Error(f"{label} has no payload path")
    value = Path(path).expanduser().absolute()
    if not value.is_file():
        raise GenericJoinV3Error(f"{label} is missing: {value}")
    st = value.stat()
    return {"path": str(value), "bytes": int(st.st_size), "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns), "st_dev": int(st.st_dev), "st_ino": int(st.st_ino)}


def _summary_first_rows(summary: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]] | None:
    candidates: list[Any] = [summary.get("first_missing_records"), summary.get("first_disappearance_records"), summary.get("first_missing")]
    records = summary.get("records")
    if isinstance(records, dict):
        candidates.extend((records.get("first_missing_records"), records.get("first_disappearance_records"), records.get("first_missing")))
    for value in candidates:
        if not isinstance(value, list):
            continue
        result: dict[tuple[int, int], dict[str, Any]] = {}
        for item in value:
            if not isinstance(item, dict):
                raise GenericJoinV3Error("typed summary first-missing record is malformed")
            key = v2._identity(item, "typed summary first-missing identity")
            if key in result:
                raise GenericJoinV3Error("typed summary first-missing identities are duplicated")
            result[key] = item
        return result
    return None


def _compare_optional(actual: Any, expected: Any, label: str) -> None:
    if actual is None or expected is None:
        return
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-12):
            raise GenericJoinV3Error(f"{label} differs")
    elif actual != expected:
        raise GenericJoinV3Error(f"{label} differs")


def _summary_matches_rows(summary: dict[str, Any], rows: list[dict[str, Any]], case_id: str) -> None:
    if summary.get("physical_case_id") not in (None, case_id):
        raise GenericJoinV3Error(f"{case_id} typed summary identity differs")
    timeline = summary.get("timeline")
    times = timeline.get("time_s") if isinstance(timeline, dict) else None
    if not isinstance(times, list) or not times:
        raise GenericJoinV3Error(f"{case_id} typed summary has no saved timeline")
    first_rows = _summary_first_rows(summary)
    fluid = summary.get("role_ledgers", {}).get("fluid", {}) if isinstance(summary.get("role_ledgers"), dict) else {}
    expected_count = fluid.get("first_disappearance_count")
    if first_rows is not None:
        if set(first_rows) != {v2._identity(row, f"{case_id} report row") for row in rows}:
            raise GenericJoinV3Error(f"{case_id} report/summary first-missing identity sets differ")
    elif isinstance(expected_count, int) and expected_count != len(rows):
        raise GenericJoinV3Error(f"{case_id} report/summary first-missing count differs")
    else:
        raise GenericJoinV3Error(f"{case_id} typed summary does not expose first-missing identity records or count")
    for row in rows:
        key = v2._identity(row, f"{case_id} report row")
        summary_row = first_rows.get(key) if first_rows is not None else None
        frame = row.get("first_missing_frame")
        if isinstance(frame, bool) or not isinstance(frame, int) or frame <= 0 or frame >= len(times):
            raise GenericJoinV3Error(f"{case_id} {key} first-missing frame is outside summary timeline")
        frame_fields = ("first_missing_frame", "first_disappeared_frame", "frame")
        time_fields = ("first_missing_time_s", "first_disappeared_time_s", "time_s", "time")
        bracket_fields = ("bracket_s", "first_missing_bracket_s", "first_disappeared_bracket_s")
        if summary_row is not None:
            sf = next((summary_row.get(name) for name in frame_fields if summary_row.get(name) is not None), None)
            st = next((summary_row.get(name) for name in time_fields if summary_row.get(name) is not None), None)
            sb = next((summary_row.get(name) for name in bracket_fields if summary_row.get(name) is not None), None)
            _compare_optional(frame, sf, f"{case_id} {key} report/summary frame")
            _compare_optional(row.get("first_missing_time_s"), st, f"{case_id} {key} report/summary time")
            _compare_optional(row.get("bracket_s"), sb, f"{case_id} {key} report/summary bracket")
        expected_time = float(times[frame])
        reported_time = v2._number(row.get("first_missing_time_s"), f"{case_id} {key} first-missing time")
        if not math.isclose(expected_time, reported_time, rel_tol=0.0, abs_tol=1e-12):
            raise GenericJoinV3Error(f"{case_id} {key} report time differs from summary timeline")
        bracket = row.get("bracket_s")
        if not isinstance(bracket, list) or len(bracket) != 2:
            raise GenericJoinV3Error(f"{case_id} {key} report bracket is malformed")
        expected_bracket = [float(times[frame - 1]), expected_time]
        if any(not math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-12) for a, b in zip(bracket, expected_bracket)):
            raise GenericJoinV3Error(f"{case_id} {key} report bracket differs from summary timeline")


def _verify_obi4(contract: dict[str, Any], native: dict[str, Any], case_id: str) -> dict[str, Any]:
    evidence = native.get("partout_obi4")
    if not isinstance(evidence, dict):
        evidence = native.get("native_obi4")
    if not isinstance(evidence, dict):
        raise GenericJoinV3Error(f"{case_id} native report lacks OBI4 pre/post evidence")
    pre = evidence.get("pre_stat")
    post = evidence.get("post_stat")
    if not isinstance(pre, dict) or not isinstance(post, dict):
        raise GenericJoinV3Error(f"{case_id} OBI4 evidence lacks pre/post stat")
    v2._compare_stat(post, pre, f"{case_id} OBI4 pre/post", include_path=True)
    deferred = contract.get("native_deferred", {}).get("partout_obi4") if isinstance(contract.get("native_deferred"), dict) else None
    if not isinstance(deferred, dict):
        raise GenericJoinV3Error(f"{case_id} contract lacks deferred OBI4 edge")
    current = _stat_payload(deferred.get("path"), f"{case_id} deferred OBI4")
    v2._compare_stat(current, deferred, f"{case_id} OBI4 current stat")
    v2._compare_stat(pre, current, f"{case_id} OBI4 report/pre stat")
    for name in ("pre_sha256", "post_sha256"):
        value = evidence.get(name)
        if not isinstance(value, str) or len(value) != 64:
            raise GenericJoinV3Error(f"{case_id} OBI4 {name} is missing")
        v2._sha(value, f"{case_id} OBI4 {name}")
    if evidence["pre_sha256"] != evidence["post_sha256"]:
        raise GenericJoinV3Error(f"{case_id} OBI4 pre/post SHA differs")
    expected = deferred.get("sha256")
    if expected not in (None, "PARENT_GUARD_COMPUTED") and evidence["pre_sha256"] != v2._sha(expected, f"{case_id} deferred OBI4 SHA"):
        raise GenericJoinV3Error(f"{case_id} OBI4 report SHA differs from deferred contract")
    return {"pre_stat": pre, "post_stat": post, "pre_sha256": evidence["pre_sha256"], "post_sha256": evidence["post_sha256"]}


def _verify_case_v3(case_id: str, entry: dict[str, Any], contract: dict[str, Any], family: str) -> dict[str, Any]:
    case_report, case_ref = v2._json(v2._path(entry["output"], f"{case_id} generic case output"), f"{case_id} generic case output", limit=MAX_REPORT)
    if case_report.get("schema") != WORKER_CASE_SCHEMA or case_report.get("status") != "COMPLETED_GENERIC_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY":
        raise GenericJoinV3Error(f"{case_id} generic case report schema/status differs")
    if case_report.get("physical_case_id") != case_id or case_report.get("family_id") != family:
        raise GenericJoinV3Error(f"{case_id} generic case report identity differs")
    counts = case_report.get("counts")
    rows = case_report.get("rows")
    if not isinstance(counts, dict) or not isinstance(rows, list) or not rows:
        raise GenericJoinV3Error(f"{case_id} generic case report lacks rows/counts")
    if counts.get("joined") != len(rows) or counts.get("typed_targets") != len(rows) or counts.get("native_rows") != len(rows):
        raise GenericJoinV3Error(f"{case_id} generic case report counts differ")
    keys: set[tuple[int, int]] = set()
    brackets: list[list[float]] = []
    row_summary: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        key = v2._identity(row, f"{case_id} generic case row")
        if key in keys:
            raise GenericJoinV3Error(f"{case_id} generic case report duplicates {key}")
        keys.add(key)
        motive = row.get("motive_code", row.get("native_motive_code"))
        if motive not in (1, 2, 3):
            raise GenericJoinV3Error(f"{case_id} generic case row motive is unsupported")
        bracket = row.get("bracket_s")
        if not isinstance(bracket, list) or len(bracket) != 2:
            raise GenericJoinV3Error(f"{case_id} generic case row lacks saved bracket")
        bracket_values = [v2._number(value, f"{case_id} bracket") for value in bracket]
        first_time = v2._number(row.get("first_missing_time_s"), f"{case_id} first missing time")
        if bracket_values[0] > first_time or first_time > bracket_values[1]:
            raise GenericJoinV3Error(f"{case_id} first missing time is outside saved bracket")
        brackets.append(bracket_values)
        row_summary[key] = {**row, "motive_code": motive}
    typed = case_report.get("typed")
    if not isinstance(typed, dict):
        raise GenericJoinV3Error(f"{case_id} generic case report lacks typed evidence")
    typed_deferred = contract.get("typed_deferred")
    if not isinstance(typed_deferred, dict) or not isinstance(typed_deferred.get("summary"), dict) or not isinstance(typed_deferred.get("records"), dict):
        raise GenericJoinV3Error(f"{case_id} contract lacks typed summary/records refs")
    summary, summary_ref = v2._json_ref(typed_deferred["summary"], f"{case_id} typed summary")
    if summary.get("physical_case_id") not in (None, case_id):
        raise GenericJoinV3Error(f"{case_id} typed summary identity differs")
    records_ref = typed_deferred["records"]
    records_path = v2._path(records_ref.get("path"), f"{case_id} typed records", allow_payload=True)
    records_stat = v2._stat(records_path, f"{case_id} typed records", allow_payload=True)
    v2._compare_stat(records_stat, records_ref, f"{case_id} typed records")
    for edge in (typed.get("pre_stat"), typed.get("post_stat")):
        if not isinstance(edge, dict):
            raise GenericJoinV3Error(f"{case_id} typed evidence lacks pre/post stat")
        v2._compare_stat(edge, records_stat, f"{case_id} typed report/contract stat")
    _summary_matches_rows(summary, rows, case_id)
    native = case_report.get("native")
    if not isinstance(native, dict) or not isinstance(native.get("partout_csv"), dict) or not isinstance(native.get("runparts"), dict):
        raise GenericJoinV3Error(f"{case_id} generic case report lacks native CSV/RunPARTs evidence")
    obi4 = _verify_obi4(contract, native, case_id)
    partout = native["partout_csv"]
    pre = partout.get("pre_stat")
    post = partout.get("post_stat")
    if not isinstance(pre, dict) or not isinstance(post, dict):
        raise GenericJoinV3Error(f"{case_id} PartOut CSV evidence lacks pre/post stat")
    v2._compare_stat(post, pre, f"{case_id} PartOut CSV pre/post")
    native_rows, native_stat = v2._read_csv(pre, f"{case_id} PartOut CSV")
    if partout.get("sha256") not in (None, "PARENT_GUARD_COMPUTED") and native_stat["sha256"] != v2._sha(partout["sha256"], f"{case_id} PartOut CSV SHA"):
        raise GenericJoinV3Error(f"{case_id} PartOut CSV report SHA differs")
    if set(native_rows) != keys:
        raise GenericJoinV3Error(f"{case_id} PartOut/native identity set differs")
    for key, value in native_rows.items():
        if value["motive_code"] != row_summary[key].get("motive_code") or value["part_out"] != row_summary[key].get("part_out"):
            raise GenericJoinV3Error(f"{case_id} PartOut row differs for {key}")
    runparts = v2._read_runparts(native["runparts"], brackets, case_id)
    return {"physical_case_id": case_id, "status": "COMPLETED", "joined_identity_count": len(keys), "case_output": case_ref, "typed_summary": summary_ref, "typed_records_stat_only": records_stat, "native_obi4": obi4, "native_csv": native_stat, "runparts": runparts}


def verify(scope_path: Path, manifest_path: Path, request_path: Path, report_path: Path) -> dict[str, Any]:
    scope, scope_ref = _load_scope_v3(scope_path)
    manifest, manifest_ref, contracts = _load_worker_manifest_v3(manifest_path, scope)
    request, request_ref = v2._load_request(request_path, manifest_path, manifest_ref, manifest)
    report, report_ref = v2._json(report_path, "generic worker batch report", limit=MAX_REPORT)
    if report.get("schema") not in {WORKER_REPORT_SCHEMA, ROOT312_REPORT_SCHEMA} or report.get("family_id") != manifest.get("family_id"):
        raise GenericJoinV3Error("generic/ROOT312 worker batch report schema/family differs")
    if report.get("status") not in {"COMPLETED_ALL_CASES", "COMPLETED_WITH_CASE_FAILURES", "COMPLETED_SELECTED_ORIGINAL118_NATIVE_DIAGNOSTIC_ONLY"}:
        raise GenericJoinV3Error("generic/ROOT312 worker batch report status differs")
    for field in ("physical_fate", "legal_flux", "dynamics", "QI", "QN", "QE"):
        if report.get(field) not in (None, "UNKNOWN"):
            raise GenericJoinV3Error(f"worker batch report overclaims {field}")
    results = report.get("case_results")
    counts = report.get("counts")
    if not isinstance(results, list) or not isinstance(counts, dict):
        raise GenericJoinV3Error("worker batch report lacks case results/counts")
    result_ids = [row.get("physical_case_id") for row in results if isinstance(row, dict)]
    if len(result_ids) != len(results) or len(result_ids) != len(set(result_ids)) or set(result_ids) != set(manifest["physical_case_ids"]):
        raise GenericJoinV3Error("worker report case identity set differs from manifest")
    if counts.get("requested") != len(results):
        raise GenericJoinV3Error("worker requested count differs")
    completed = 0
    failures: list[dict[str, Any]] = []
    verified_cases: list[dict[str, Any]] = []
    for result in results:
        case_id = result["physical_case_id"]
        if result.get("status") == "FAILED":
            failures.append({"physical_case_id": case_id, "status": "FAILED_NO_JOIN_CREDIT", "error_type": result.get("error_type"), "error_message": result.get("error_message")})
            continue
        if result.get("status") != "COMPLETED" or not isinstance(result.get("output"), str):
            raise GenericJoinV3Error(f"{case_id} worker result status/output differs")
        verified = _verify_case_v3(case_id, result, contracts[case_id]["document"], manifest["family_id"])
        if result.get("joined") != verified["joined_identity_count"]:
            raise GenericJoinV3Error(f"{case_id} worker joined count differs")
        verified_cases.append(verified)
        completed += 1
    failed = len(results) - completed
    if counts.get("completed") != completed or counts.get("failed") != failed:
        raise GenericJoinV3Error("worker completed/failed counts differ")
    return {
        "schema": REPORT_SCHEMA,
        "status": "VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_WITH_CASE_FAILURES" if failed else "VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_ALL_CASES",
        "scope": scope_ref, "worker_manifest": manifest_ref, "worker_request": request_ref, "worker_report": report_ref,
        "counts": {"worker_requested_cases": len(results), "worker_completed_cases": completed, "worker_failed_cases": failed, "new_typed_native_join_physical_cases": completed, "new_native_cause_credit": 0, "scope_existing_exact_join_count": scope["case_scope"]["existing_exact_join_count"], "scope_actual_join_proof_count": scope["actual_join_proof_count"]},
        "completed_cases": verified_cases, "failed_cases": failures,
        "claim_boundary": {"new_native_cause_credit": 0, "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "alias_substitution": False, "producer_proof_ids_derived": True, "summary_first_missing_checked": True, "native_obi4_pre_post_checked": True},
        "read_policy": {"h5_opened": False, "jsonl_content_opened": False, "bi4_opened": False, "obi4_content_opened": False, "obi4_stat_checked": True, "small_summary_csv_runparts_opened": True},
    }


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise GenericJoinV3Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush(); os.fsync(stream.fileno())
        if temporary.stat().st_size > MAX_REPORT:
            raise GenericJoinV3Error("output exceeds bounded size")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--scope", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)
    verify_parser.add_argument("--request", type=Path, required=True)
    verify_parser.add_argument("--report", type=Path, required=True)
    verify_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _atomic(args.output, verify(args.scope, args.manifest, args.request, args.report))
    except (GenericJoinV3Error, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"GENERIC_NATIVE_TYPED_JOIN_V3_ERROR: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

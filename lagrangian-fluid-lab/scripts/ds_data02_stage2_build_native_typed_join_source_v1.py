#!/usr/bin/env python3
"""Build a source-only manifest for the 47 actual typed/native join cases.

The V10 overlay records a count and a list of newly bound cases, but its
``actual_join_proofs`` are the authoritative per-case evidence set.  This
builder opens those small proof JSON files once, validates their declared
SHA-256 and status, extracts every case row, and reports the exact
47-case/71-case difference.  It also records the 17 exact future
ROOT274/308/309 source-prepared IDs and ROOT312's seven selected cases whose
producer proof is still unavailable.

No deferred JSONL, H5, BI4, OBI4, PartOut, or native trajectory is opened.
Existing proof/report paths are preserved as evidence edges; this manifest
does not create a new scientific result or physical mass-impact credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
MAX_INPUT = 12 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
PAYLOAD_SUFFIXES = {".jsonl", ".h5", ".hdf5", ".bi4", ".obi4", ".vtk", ".xmf"}


class JoinSourceError(ValueError):
    pass


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
        raise JoinSourceError(f"{label} is not a SHA-256 digest")
    return value.lower()


def _stat(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise JoinSourceError(f"{label} is missing: {path}")
    st = path.stat()
    return {"path": str(path.resolve()), "bytes": int(st.st_size), "mtime_ns": int(st.st_mtime_ns),
            "ctime_ns": int(st.st_ctime_ns), "st_dev": int(st.st_dev), "st_ino": int(st.st_ino)}


def _read_json(path_value: str | os.PathLike[str], label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(path_value).expanduser().resolve()
    if path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise JoinSourceError(f"{label} is a payload, not a metadata input")
    before = _stat(path, label)
    if before["bytes"] > MAX_INPUT:
        raise JoinSourceError(f"{label} exceeds bounded metadata input")
    raw = path.read_bytes()
    after = _stat(path, label)
    for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if before[field] != after[field] or len(raw) != after["bytes"]:
            raise JoinSourceError(f"{label} changed during capture")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JoinSourceError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise JoinSourceError(f"{label} must be a JSON object")
    return value, {**after, "sha256": hashlib.sha256(raw).hexdigest()}


def _case_ids(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise JoinSourceError(f"{label} is not a case-ID list")
    if len(value) != len(set(value)):
        raise JoinSourceError(f"{label} has duplicate IDs")
    return list(value)


def _edge(value: Any, label: str, *, allow_unverified_sha: bool = False) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict) and not isinstance(value.get("path"), str) and isinstance(value.get("trajectory_path"), str):
        # Some completed join proofs name the deferred trajectory edge
        # ``trajectory_path`` and keep its declared SHA/stat in a nested
        # ``trajectory_stat`` object.  Normalize that spelling without
        # opening the trajectory.
        value = {
            "path": value["trajectory_path"],
            "sha256": value.get("trajectory_sha256"),
            **(value.get("trajectory_stat") if isinstance(value.get("trajectory_stat"), dict) else {}),
            "content_opened": value.get("content_opened"),
        }
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise JoinSourceError(f"{label} is malformed")
    sha = value.get("sha256", value.get("post_sha256", value.get("pre_sha256")))
    if sha is None:
        normalized_sha = None
        hash_status = "NOT_DECLARED"
    elif isinstance(sha, str) and len(sha) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in sha):
        normalized_sha = sha.lower()
        hash_status = "DECLARED_SHA256"
    elif allow_unverified_sha:
        normalized_sha = None
        hash_status = "UNVERIFIED_SENTINEL_DECLARATION"
    else:
        raise JoinSourceError(f"{label} SHA is not a SHA-256 digest")
    return {"path": value["path"], "sha256": normalized_sha, "declared_sha256": sha,
            "bytes": value.get("bytes", value.get("post_stat", {}).get("bytes")),
            "content_opened": value.get("content_opened", value.get("content_opened_by_preparer")),
            "hash_status": hash_status}


def _inventory(inventory: dict[str, Any], label: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if inventory.get("schema") != "ds02.stage2.historical118-source-inventory.v1":
        raise JoinSourceError(f"{label} schema differs")
    rows = inventory.get("rows")
    if not isinstance(rows, list) or len(rows) != 118:
        raise JoinSourceError(f"{label} does not contain 118 rows")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str) or row.get("physical_case_id") in by_id:
            raise JoinSourceError(f"{label} case IDs are malformed or duplicated")
        if row.get("historical_118_membership") is not True:
            raise JoinSourceError(f"{label} contains a non-original case")
        by_id[row["physical_case_id"]] = row
    return by_id, {"case_count": len(by_id), "family_counts": dict(Counter(row.get("family_id") for row in by_id.values()))}


def _proof_case_rows(proof: dict[str, Any], proof_path: Path, proof_stat: dict[str, Any], inventory: dict[str, dict[str, Any]], label: str) -> list[dict[str, Any]]:
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise JoinSourceError(f"{label} is not a verified actual proof")
    rows = proof.get("case_verifications")
    if rows is None:
        rows = [proof]
    if not isinstance(rows, list) or not rows:
        raise JoinSourceError(f"{label} has no case rows")
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise JoinSourceError(f"{label} case row {index} is malformed")
        case_id = row["physical_case_id"]
        if case_id not in inventory:
            raise JoinSourceError(f"{label} case is outside original118: {case_id}")
        report_value = row.get("report", proof.get("report"))
        report_sha = row.get("report_sha256", proof.get("report_sha256"))
        if not isinstance(report_value, str) or report_sha is None:
            raise JoinSourceError(f"{label} {case_id} lacks report edge")
        typed_summary = _edge(row.get("typed_summary"), f"{label} {case_id} typed summary", allow_unverified_sha=True)
        typed_records = _edge(row.get("typed_records_stat_SHA_only", row.get("records_stat_only", proof.get("records_stat_only"))),
                              f"{label} {case_id} typed records", allow_unverified_sha=True)
        source_h5 = _edge(row.get("source_H5_stat_only"), f"{label} {case_id} source H5", allow_unverified_sha=True)
        comparisons = row.get("comparison_counts", proof.get("comparison_counts", {}))
        if not isinstance(comparisons, dict):
            raise JoinSourceError(f"{label} {case_id} comparison counts are malformed")
        exact_join_count = row.get("target_identity_count", row.get("target_fluid_identity_count", proof.get("exact_native_identity_join_count")))
        if exact_join_count is None:
            exact_join_count = comparisons.get("saved_frame_matches")
        if isinstance(exact_join_count, bool) or not isinstance(exact_join_count, int) or exact_join_count < 0:
            raise JoinSourceError(f"{label} {case_id} exact join count is malformed")
        cause = row.get("native_cause_categories", row.get("native_numerical_cause", proof.get("native_numerical_cause")))
        if cause is None:
            cause = "NUMERICAL_POSITION_OR_DENSITY_EXCLUSION_AS_REPORTED" if row.get("native_csv_evidence") else "SOURCE_BOUND_JOIN_WITHOUT_NEW_CAUSE"
        out.append({
            "physical_case_id": case_id,
            "family_id": inventory[case_id].get("family_id"),
            "current336_index": inventory[case_id].get("current336_index"),
            "current_lifecycle_declaration": {
                "path": inventory[case_id].get("identity", {}).get("current_trajectory_path"),
                "sha256": inventory[case_id].get("identity", {}).get("current_trajectory_declared_sha256"),
                "bytes": inventory[case_id].get("identity", {}).get("current_trajectory_bytes"),
                "content_opened_by_this_adapter": False,
                "status": "CURRENT_DECLARATION_ONLY",
            },
            "producer_proof": {"path": str(proof_path), "sha256": proof_stat["sha256"], "status": proof.get("status")},
            "producer_proof_case_index": index,
            "native_report": {"path": report_value, "sha256": _sha(report_sha, f"{label} {case_id} report")},
            "typed_summary": typed_summary,
            "typed_records_stat_only": typed_records,
            "source_h5_stat_only": source_h5,
            "exact_typed_native_join_count": exact_join_count,
            "comparison_counts": {key: comparisons.get(key) for key in ("saved_frame_matches", "saved_frame_mismatches", "saved_frame_unknown", "typed_times_in_native_brackets") if key in comparisons},
            "native_cause": cause,
            "mass_impact_status": "NOT_MEASURED_BY_TYPED_NATIVE_JOIN_PROOF",
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "physical_mass_flux": "UNKNOWN", "dynamics": "UNKNOWN"},
        })
    return out


def _validate_future_request(path: Path, label: str, inventory: dict[str, dict[str, Any]], expected_family: str, expected_count: int) -> tuple[dict[str, Any], dict[str, Any]]:
    request, stat = _read_json(path, label)
    if request.get("schema") != "ds02.request.v1" or request.get("family_id") != expected_family:
        raise JoinSourceError(f"{label} schema/family differs")
    ids = _case_ids(request.get("physical_case_ids"), f"{label} physical_case_ids")
    if len(ids) != expected_count or any(case_id not in inventory for case_id in ids):
        raise JoinSourceError(f"{label} does not bind the expected original118 cases")
    if request.get("launch_allowed") is not True or request.get("execution_allowed") is not True:
        raise JoinSourceError(f"{label} is not a source-prepared executable request")
    return {
        "status": "PREPARED_NOT_TERMINAL_NATIVE",
        "family_id": expected_family,
        "case_ids": ids,
        "request": {"path": stat["path"], "sha256": stat["sha256"], "bytes": stat["bytes"]},
        "estimated_deferred_read_bytes": request.get("estimated_deferred_read_bytes"),
        "estimated_storage_bytes": request.get("estimated_storage_bytes"),
        "terminal_proof_available": False,
        "mass_impact_status": "NOT_MEASURED",
        "unsupported": ["terminal producer proof unavailable", "typed/native join not yet measured", "physical fate/flux/dynamics/Q unknown"],
    }, stat


def build(args: argparse.Namespace) -> dict[str, Any]:
    inventory_doc, inventory_stat = _read_json(args.inventory, "historical118 inventory")
    inventory, inventory_summary = _inventory(inventory_doc, "historical118 inventory")
    inventory_ids = set(inventory)
    overlay, overlay_stat = _read_json(args.overlay, "V10 overlay")
    if overlay.get("schema") != "ds02.stage2.original118-native-cause-actual-overlay.v1" or overlay.get("physical_case_count") != 118:
        raise JoinSourceError("V10 overlay schema/case count differs")
    overlay_refs = overlay.get("actual_join_proofs")
    if not isinstance(overlay_refs, list) or len(overlay_refs) != 12:
        raise JoinSourceError("V10 overlay must carry the exact 12 actual_join_proofs")
    actual_rows: list[dict[str, Any]] = []
    proof_bundles: list[dict[str, Any]] = []
    seen_proof_paths: set[str] = set()
    seen_cases: set[str] = set()
    for index, ref in enumerate(overlay_refs):
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            raise JoinSourceError(f"V10 proof reference {index} is malformed")
        proof_path = Path(ref["path"]).expanduser().resolve()
        if str(proof_path) in seen_proof_paths:
            raise JoinSourceError(f"V10 proof references duplicate path: {proof_path}")
        seen_proof_paths.add(str(proof_path))
        proof, proof_stat = _read_json(proof_path, f"V10 actual proof {index}")
        if proof_stat["sha256"] != _sha(ref.get("sha256"), f"V10 actual proof {index}"):
            raise JoinSourceError(f"V10 actual proof {index} SHA differs")
        rows = _proof_case_rows(proof, proof_path, proof_stat, inventory, f"V10 actual proof {index}")
        for row in rows:
            if row["physical_case_id"] in seen_cases:
                raise JoinSourceError(f"actual proof case is duplicated: {row['physical_case_id']}")
            seen_cases.add(row["physical_case_id"])
        actual_rows.extend(rows)
        proof_bundles.append({
            "producer_proof": {"path": str(proof_path), "sha256": proof_stat["sha256"], "bytes": proof_stat["bytes"], "status": proof.get("status")},
            "case_count": len(rows),
            "case_ids": [row["physical_case_id"] for row in rows],
            "source_content_opened_by_this_adapter": False,
            "mass_impact_status": "NOT_MEASURED_BY_TYPED_NATIVE_JOIN_PROOF",
        })
    if len(actual_rows) != 47 or overlay.get("actual_typed_native_saved_frame_join_physical_cases") != 47:
        raise JoinSourceError("V10 actual proof rows do not match the declared 47-case join set")
    newly_bound = {row.get("physical_case_id") for row in overlay.get("newly_bound_cases", []) if isinstance(row, dict)}
    remaining = set(_case_ids(overlay.get("remaining_cause_not_located_case_ids"), "V10 remaining case IDs"))
    if not newly_bound <= inventory_ids or not remaining <= inventory_ids or newly_bound & remaining:
        raise JoinSourceError("V10 case-set partitions are malformed")
    if seen_cases & remaining:
        raise JoinSourceError("actual typed/native proof intersects V10 unlocated cases")
    future: dict[str, dict[str, Any]] = {}
    future_stats: dict[str, dict[str, Any]] = {}
    for key, path, family, count in (("ROOT274", args.root274_request, "F6", 7), ("ROOT308", args.root308_request, "F4", 4), ("ROOT309", args.root309_request, "F6", 6)):
        future[key], future_stats[key] = _validate_future_request(path, key + " request", inventory, family, count)
    pending, pending_stat = _read_json(args.root312_checkpoint, "ROOT312 pending intake")
    if pending.get("schema") != "ds02.stage2.root312-f4-multi-proof-intake-pending.v2" or pending.get("launch_allowed") is not False or pending.get("payload_content_opened") is not False:
        raise JoinSourceError("ROOT312 pending intake boundary differs")
    if pending.get("full_producer_case_count") != 16 or pending.get("selected_original118_case_count") != 7:
        raise JoinSourceError("ROOT312 pending selected/full counts differ")
    producers = pending.get("producer_proofs")
    if not isinstance(producers, list) or len(producers) != 2 or any(row.get("producer_proof") != "NOT_AVAILABLE" for row in producers if isinstance(row, dict)):
        raise JoinSourceError("ROOT312 pending proof rows are not unavailable as declared")
    future_ids = set().union(*(set(value["case_ids"]) for value in future.values()))
    if seen_cases & future_ids:
        raise JoinSourceError("future source-prepared IDs overlap actual proof joins")
    if not future_ids <= remaining:
        raise JoinSourceError("future source-prepared IDs are not in the V10 unlocated partition")
    inherited_bound_without_join = overlay.get("native_cause_bound_per_fluid_id_cases") - len(seen_cases)
    if inherited_bound_without_join != 47:
        raise JoinSourceError("V10 cause-bound minus actual join count is not 47")
    output = {
        "schema": "ds02.stage2.native-typed-native-join-source-entry.v1",
        "status": "ACTUAL_47_JOIN_PROOFS_PLUS_24_FUTURE_SOURCE_PREPARED_PENDING",
        "source_edges": {
            "inventory": {"role": "HISTORICAL118_SOURCE_INVENTORY", **inventory_stat},
            "overlay_v10": {"role": "ORIGINAL118_NATIVE_CAUSE_OVERLAY_V10", **overlay_stat},
            "ROOT274_request": {"role": "FUTURE_NATIVE_SOURCE_PREPARED", **future_stats["ROOT274"]},
            "ROOT308_request": {"role": "FUTURE_NATIVE_SOURCE_PREPARED", **future_stats["ROOT308"]},
            "ROOT309_request": {"role": "FUTURE_NATIVE_SOURCE_PREPARED", **future_stats["ROOT309"]},
            "ROOT312_pending": {"role": "FUTURE_PRODUCER_PROOF_PENDING", **pending_stat},
        },
        "summary": {
            "original118_cases": 118,
            "actual_join_cases_from_v10_proofs": len(seen_cases),
            "explicit_newly_bound_cases": len(newly_bound),
            "newly_bound_cases_with_actual_join_proof": len(newly_bound & seen_cases),
            "actual_join_cases_not_in_newly_bound_list": len(seen_cases - newly_bound),
            "native_cause_bound_count_from_v10": overlay.get("native_cause_bound_per_fluid_id_cases"),
            "native_cause_bound_without_precise_typed_native_join": inherited_bound_without_join,
            "cause_not_located_case_count_from_v10": len(remaining),
            "future_exact_source_prepared_cases": len(future_ids),
            "future_root312_selected_cases_without_ids": pending.get("selected_original118_case_count"),
            "future_possible_join_scope_if_all_terminal": len(future_ids) + pending.get("selected_original118_case_count"),
            "remaining_cases_without_precise_typed_native_join_after_future_scope": 47,
            "physical_fate_flux_dynamics_q": "UNKNOWN",
        },
        "actual_producer_proof_bundles": proof_bundles,
        "actual_case_rows": actual_rows,
        "future_source_prepared": {**future, "ROOT312": {
            "status": "WAITING_FULL_TERMINAL_PROOFS", "case_ids": [],
            "selected_original118_case_count": pending.get("selected_original118_case_count"),
            "full_producer_case_count": pending.get("full_producer_case_count"),
            "terminal_proof_available": False,
            "mass_impact_status": "NOT_MEASURED",
            "unsupported": ["producer proof unavailable", "selected case IDs are not exposed by the pending checkpoint", "physical fate/flux/dynamics/Q unknown"],
        }},
        "set_differences": {
            "actual_join_case_ids": sorted(seen_cases),
            "future_exact_case_ids": sorted(future_ids),
            "v10_unlocated_case_ids": sorted(remaining),
            "v10_cause_bound_without_join_case_count_only": inherited_bound_without_join,
            "v10_join_minus_newly_bound_case_ids": sorted(seen_cases - newly_bound),
        },
        "read_policy": {
            "inventory_overlay_and_proof_metadata_opened": True,
            "producer_report_content_opened": False,
            "typed_jsonl_content_opened": False,
            "h5_bi4_obi4_native_payload_content_opened": False,
            "solver_started": False,
        },
        "claim_boundary": {
            "typed_native_saved_frame_join": "VERIFIED_FOR_ACTUAL_47_CASES_ONLY",
            "mass_impact": "NOT_MEASURED_BY_JOIN_PROOFS",
            "native_cause": "SOURCE_BOUND_WHERE_PROOF_REPORTS_IT",
            "physical_fate": "UNKNOWN", "physical_mass_flux": "UNKNOWN", "dynamics": "UNKNOWN",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
    }
    output_path = args.output.expanduser().resolve()
    if output_path.exists():
        raise JoinSourceError(f"refusing to overwrite output: {output_path}")
    encoded = json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(encoded.encode("utf-8")) > MAX_OUTPUT:
        raise JoinSourceError("join source output exceeds bound")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(encoded, encoding="utf-8")
    return {"status": output["status"], "output": str(output_path), "actual_join_cases": 47, "future_exact_cases": len(future_ids), "root312_pending_cases": 7}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    build = sub.add_parser("build")
    for option, dest in (("--inventory", "inventory"), ("--overlay", "overlay"), ("--root274-request", "root274_request"),
                         ("--root308-request", "root308_request"), ("--root309-request", "root309_request"),
                         ("--root312-checkpoint", "root312_checkpoint"), ("--output", "output")):
        build.add_argument(option, dest=dest, type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = {"schema": "ds02.stage2.native-typed-native-join-source-entry.v1", "status": "PASS", "payload_content_opened": False} if args.action == "self-test" else build(args)
    except (JoinSourceError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"NATIVE_TYPED_NATIVE_JOIN_SOURCE_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

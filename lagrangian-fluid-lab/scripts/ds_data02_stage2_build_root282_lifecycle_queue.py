#!/usr/bin/env python3
"""Prepare the remaining ROOT269 lifecycle groups as source-only batches.

ROOT280 and ROOT281 already prepared ten exact CURRENT cases.  This additive
builder partitions the other 202 ``UNSCHEDULED_EXACT_CURRENT_AUDIT`` rows in
the frozen ROOT269 plan into the remaining single-family groups (ROOT282
through ROOT307).  It invokes the immutable generic V4 request builder for
each bounded group, records the selection and source closure, and never opens
trajectory, JSONL, native, BI4, or solver payload content.  A later root-owned
runner must re-check the latest actual registry before using any request.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
SCRIPTS = PRIMARY / "lagrangian-fluid-lab/scripts"
PLAN = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_ROOT269_PENDING_V4.json"
INVENTORY = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
OVERLAY = STAGE2 / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"
CURRENT = STAGE2 / "CURRENT336.json"
AUDIT = STAGE2 / "checkpoints/SCIENTIFIC_AUDIT_VERIFICATION_023.json"
ROOT280_SELECTION = STAGE2 / "requests/root280-f4-lifecycle-prepared-001/root280-selection-manifest.json"
ROOT281_SELECTION = STAGE2 / "requests/root281-f6-lifecycle-prepared-001/root281-selection-manifest.json"
ROOT280_SELECTION_SHA = "6c428f90e3541f0aa07990c3444dc5de75e305ef423c0da2cb31a5991f97ead2"
ROOT281_SELECTION_SHA = "1f77e451828e55c4ba1cdbf6971b41c0848e8f832fb479058183bf6db594edf8"
PLAN_SHA = "09727374ae7c87b56ce1ddc866cab86c270e111509c25dfe556859d6747e1541"
INVENTORY_SHA = "3d274db71d01f680b9997cc364298f9974a2cb09978acfb81f9a152622e75a00"
OVERLAY_SHA = "72683cdf4b96c334b6f6d6f2df668c9c15f30323b39fcf3473d230c5475e1224"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
AUDIT_SHA = "72fd44794443130ab129d75593a4d6689c889cf3af859cd602d11d540acf2881"
MAX_CASES = 8
MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024
MAX_SMALL_BYTES = 10 * 1024 * 1024
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4"}
QUEUE_SCHEMA = "ds02.stage2.root-lifecycle-source-queue.v1"
SELECTION_SCHEMA = "ds02.stage2.root-lifecycle-selection.v2"
REQUEST_SCHEMA = "ds02.request.v1"


class QueueError(ValueError):
    pass


def _load_root280() -> Any:
    path = SCRIPTS / "ds_data02_stage2_build_root280_lifecycle_batch.py"
    spec = importlib.util.spec_from_file_location("root280_lifecycle_builder", path)
    if spec is None or spec.loader is None:
        raise QueueError(f"cannot import immutable ROOT280 builder: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT280 = _load_root280()


def _namespace(number: int) -> str:
    if not 282 <= number <= 310:
        raise QueueError("queue namespace must be ROOT282 through ROOT310")
    return f"ROOT{number}"


def _json(path: Path, label: str) -> dict[str, Any]:
    return ROOT280._json(path, label)


def _sha_file(path: Path, label: str) -> str:
    return ROOT280._sha_file(path, label, limit=MAX_SMALL_BYTES)


def _atomic(path: Path, value: dict[str, Any]) -> None:
    ROOT280._atomic(path, value, limit=MAX_SMALL_BYTES)


def _validate_frozen_inputs() -> tuple[dict[str, Any], dict[str, dict[str, Any]], set[str], dict[str, set[str]]]:
    plan_ref = ROOT280._small_ref(PLAN, "ROOT269 pending plan", PLAN_SHA)
    inventory_ref = ROOT280._small_ref(INVENTORY, "historical 118 inventory", INVENTORY_SHA)
    overlay_ref = ROOT280._small_ref(OVERLAY, "ROOT268 V10 overlay", OVERLAY_SHA)
    plan = _json(PLAN, "ROOT269 pending plan")
    if plan.get("schema") != ROOT280.PLAN_SCHEMA or plan.get("status") != "PREPARED_METADATA_ONLY_NO_LAUNCH":
        raise QueueError("ROOT269 plan schema/status differs")
    expected_coverage = {
        "actual_saved_mask_cases": 116,
        "current_cases": 336,
        "exact_current_audit_rows": 335,
        "historical_alias_unresolved": 1,
        "incomplete_or_mismatched": 0,
        "pending_no_credit_cases": 7,
        "physical_or_scientific_credit_cases": 0,
        "remaining_exact_unscheduled_cases": 212,
    }
    coverage = plan.get("coverage")
    if not isinstance(coverage, dict) or any(coverage.get(k) != v for k, v in expected_coverage.items()):
        raise QueueError("ROOT269 coverage partition differs")
    records = plan.get("case_records")
    if not isinstance(records, list) or len(records) != 336:
        raise QueueError("ROOT269 plan lacks exactly 336 case records")
    by_id = {r.get("physical_case_id"): r for r in records if isinstance(r, dict) and isinstance(r.get("physical_case_id"), str)}
    if len(by_id) != 336:
        raise QueueError("ROOT269 physical case IDs are not unique")
    unscheduled = {cid for cid, row in by_id.items() if row.get("status") == "UNSCHEDULED_EXACT_CURRENT_AUDIT"}
    if len(unscheduled) != 212:
        raise QueueError(f"ROOT269 exact unscheduled count differs: {len(unscheduled)}")
    for cid, row in by_id.items():
        if row.get("status") == "UNSCHEDULED_EXACT_CURRENT_AUDIT" and row.get("source_join_status") != "EXACT_CURRENT_AUDIT_METADATA_JOIN":
            raise QueueError(f"{cid} is unscheduled without exact source join")
    inventory = _json(INVENTORY, "historical 118 inventory")
    rows = inventory.get("rows")
    if not isinstance(rows, list) or len(rows) != 118:
        raise QueueError("historical inventory is not exactly 118 rows")
    historical = {row.get("identity", {}).get("current_physical_case_id") for row in rows if isinstance(row, dict) and row.get("historical_118_membership") is True}
    if len(historical) != 118 or None in historical:
        raise QueueError("historical inventory membership is not exact")
    overlay = _json(OVERLAY, "ROOT268 V10 overlay")
    if overlay.get("status") != "VERIFIED_METADATA_JOIN_TO_ACTUAL_PER_ID_PROOFS":
        raise QueueError("ROOT268 V10 overlay is not verified")
    unlocated = overlay.get("remaining_cause_not_located_case_ids")
    if not isinstance(unlocated, list) or not all(isinstance(item, str) for item in unlocated):
        raise QueueError("ROOT268 V10 overlay lacks exact unlocated IDs")
    for path, expected, label in ((ROOT280_SELECTION, ROOT280_SELECTION_SHA, "ROOT280 selection manifest"), (ROOT281_SELECTION, ROOT281_SELECTION_SHA, "ROOT281 selection manifest")):
        if _sha_file(path, label) != expected:
            raise QueueError(f"{label} SHA differs")
    prepared: set[str] = set()
    for path, expected, label in ((ROOT280_SELECTION, ROOT280_SELECTION_SHA, "ROOT280 selection manifest"), (ROOT281_SELECTION, ROOT281_SELECTION_SHA, "ROOT281 selection manifest")):
        value = _json(path, label)
        if value.get("status") != "READY_SOURCE_ONLY_NO_LAUNCH" or not isinstance(value.get("selected_case_ids"), list):
            raise QueueError(f"{label} is not an immutable source-only selection")
        ids = value["selected_case_ids"]
        if len(ids) != value.get("selected_case_count") or len(set(ids)) != len(ids):
            raise QueueError(f"{label} selected IDs are not unique")
        overlap = prepared.intersection(ids)
        if overlap:
            raise QueueError(f"prepared ROOT280/281 selections overlap: {sorted(overlap)}")
        prepared.update(ids)
    if len(prepared) != 10 or not prepared.issubset(unscheduled):
        raise QueueError("prepared ROOT280/281 IDs do not form a ten-case subset of frozen unscheduled rows")
    refs = {"plan": plan_ref, "inventory": inventory_ref, "overlay": overlay_ref}
    return plan, refs, prepared, {"historical": historical, "unlocated": set(unlocated)}


def _partition(plan: dict[str, Any], prepared: set[str], scope: dict[str, set[str]]) -> list[dict[str, Any]]:
    records = {r["physical_case_id"]: r for r in plan["case_records"]}
    batches: list[dict[str, Any]] = []
    number = 282
    seen: set[str] = set()
    for group in plan["groups"]:
        if not isinstance(group, dict):
            raise QueueError("plan contains a non-object group")
        group_id = group.get("group_id")
        family = group.get("family_id")
        ids = group.get("case_ids")
        if not isinstance(group_id, str) or not isinstance(family, str) or not isinstance(ids, list):
            raise QueueError("plan group lacks identity")
        candidates = []
        for cid in ids:
            row = records.get(cid)
            if not isinstance(row, dict) or row.get("family_id") != family or row.get("status") != "UNSCHEDULED_EXACT_CURRENT_AUDIT":
                raise QueueError(f"group {group_id} contains non-unscheduled case {cid}")
            if cid in prepared:
                continue
            candidates.append(cid)
        if not candidates:
            continue
        if len(candidates) > MAX_CASES:
            raise QueueError(f"group {group_id} exceeds case bound")
        source_bytes = sum(int(records[cid].get("declared_source_bytes", -1)) for cid in candidates)
        if source_bytes <= 0 or source_bytes > MAX_GROUP_BYTES:
            raise QueueError(f"group {group_id} exceeds source bound")
        namespace = _namespace(number)
        number += 1
        overlap = seen.intersection(candidates)
        if overlap:
            raise QueueError(f"queue group overlap: {sorted(overlap)}")
        seen.update(candidates)
        original_unlocated = sorted(set(candidates).intersection(scope["historical"], scope["unlocated"]))
        historical_ids = sorted(set(candidates).intersection(scope["historical"]))
        batches.append({"namespace": namespace, "group_id": group_id, "family_id": family, "case_ids": candidates, "source_bytes": source_bytes, "plan_group_case_count": len(ids), "plan_group_declared_source_bytes": int(group.get("declared_source_bytes", 0)), "selected_original118_unlocated_case_ids": original_unlocated, "selected_historical_original118_case_ids": historical_ids})
    expected = {cid for cid, row in records.items() if row.get("status") == "UNSCHEDULED_EXACT_CURRENT_AUDIT"} - prepared
    if seen != expected or len(seen) != 202:
        raise QueueError(f"queue partition does not cover remaining exact rows: {len(seen)} vs {len(expected)}")
    if number > 310:
        raise QueueError("queue requires more than ROOT310")
    return batches


def _generic_args(family: str) -> SimpleNamespace:
    return SimpleNamespace(
        python=ROOT280.VENV,
        current=CURRENT,
        audit=AUDIT,
        family=family,
        runtime_config=ROOT280.CONFIG,
    )


def _make_batch(batch: dict[str, Any], output_root: Path, base_refs: dict[str, dict[str, Any]], plan: dict[str, Any], prepared_refs: list[dict[str, Any]]) -> dict[str, Any]:
    namespace = batch["namespace"]
    output_dir = output_root / f"{namespace.lower()}-{batch['family_id'].lower()}-lifecycle-prepared-001"
    if output_dir.exists():
        raise QueueError(f"refusing existing batch output: {output_dir}")
    generic_result, delegated_manifest, delegated_request = ROOT280._run_generic(_generic_args(batch["family_id"]), batch["case_ids"], output_dir)
    delegated = _json(delegated_request, "delegated batch request")
    delegated_manifest_value = _json(delegated_manifest, "delegated batch manifest")
    if delegated.get("schema") != REQUEST_SCHEMA or delegated.get("family_id") != batch["family_id"] or delegated.get("physical_case_ids") != batch["case_ids"]:
        raise QueueError(f"{namespace} delegated request identity differs")
    if delegated_manifest_value.get("case_count") != len(batch["case_ids"]):
        raise QueueError(f"{namespace} delegated manifest count differs")
    if int(delegated.get("estimated_deferred_source_bytes", -1)) != batch["source_bytes"]:
        raise QueueError(f"{namespace} delegated source bytes differ")
    refs: dict[str, dict[str, Any]] = {}
    for ref in base_refs.values():
        ROOT280._add_ref(refs, ref)
    for path, label in (
        (CURRENT, "CURRENT336"), (AUDIT, "scientific audit"), (INVENTORY, "historical inventory"), (OVERLAY, "cause overlay"),
        (ROOT280_SELECTION, "ROOT280 selection manifest"), (ROOT281_SELECTION, "ROOT281 selection manifest"),
        (ROOT280.GENERIC_BUILDER, "generic batch request builder"), (ROOT280.V4_WORKER, "V4 worker"),
        (ROOT280.BATCH_WORKER, "batch worker"), (SCRIPT, "ROOT282 queue builder"), (ROOT280.SCRIPT, "ROOT280 selection builder"),
        (ROOT280.VENV, "literal Python interpreter"), (ROOT280.CONFIG, "DsphConfig.xml"), (ROOT280.RUNTIME_V2, "runtime v2"),
        (ROOT280.RUNTIME_V6, "runtime v6"), (ROOT280.RUNTIME_V8, "runtime v8"), (ROOT280.DISPATCH_V8, "dispatch v8"), (ROOT280.STRICT_V8, "strict dispatch v8"),
    ):
        ROOT280._add_ref(refs, ROOT280._small_ref(path, label))
    ROOT280._add_ref(refs, ROOT280._small_ref(delegated_manifest, f"{namespace} delegated manifest"))
    ROOT280._add_ref(refs, ROOT280._small_ref(delegated_request, f"{namespace} delegated request"))
    for ref in ROOT280._delegated_refs(delegated, f"{namespace} delegated request").values():
        ROOT280._add_ref(refs, ref)
    deferred = delegated.get("deferred_input_records", delegated_manifest_value.get("deferred_trajectory_h5", []))
    if not isinstance(deferred, list) or len(deferred) != len(batch["case_ids"]):
        raise QueueError(f"{namespace} deferred records are incomplete")
    selection_path = output_dir / f"{namespace.lower()}-selection-manifest.json"
    selection = {
        "schema": SELECTION_SCHEMA,
        "status": "READY_SOURCE_ONLY_NO_LAUNCH",
        "namespace": namespace,
        "family_id": batch["family_id"],
        "group_id": batch["group_id"],
        "queue_namespace": "ROOT282_ROOT307",
        "plan": base_refs["plan"],
        "inventory": base_refs["inventory"],
        "overlay": base_refs["overlay"],
        "current_catalog": {"path": str(CURRENT), "sha256": CURRENT_SHA},
        "scientific_audit": {"path": str(AUDIT), "sha256": AUDIT_SHA},
        "selected_case_ids": batch["case_ids"],
        "selected_case_count": len(batch["case_ids"]),
        "selected_original118_unlocated_case_ids": batch["selected_original118_unlocated_case_ids"],
        "selected_original118_unlocated_count": len(batch["selected_original118_unlocated_case_ids"]),
        "selected_historical_original118_case_count": len(batch["selected_historical_original118_case_ids"]),
        "prepared_prior_cases_excluded": sorted(ref["path"] for ref in prepared_refs),
        "plan_group_case_count": batch["plan_group_case_count"],
        "plan_group_declared_source_bytes": batch["plan_group_declared_source_bytes"],
        "selected_declared_source_bytes": batch["source_bytes"],
        "delegated_batch_manifest": {"path": str(delegated_manifest), "sha256": ROOT280._sha_file(delegated_manifest, f"{namespace} delegated manifest", limit=MAX_SMALL_BYTES)},
        "delegated_batch_request": {"path": str(delegated_request), "sha256": ROOT280._sha_file(delegated_request, f"{namespace} delegated request", limit=MAX_SMALL_BYTES)},
        "deferred_trajectory_h5": deferred,
        "source_refs": sorted(refs.values(), key=lambda value: value["path"]),
        "group_policy": {"max_cases": MAX_CASES, "max_declared_source_bytes": MAX_GROUP_BYTES, "selected_source_bytes": batch["source_bytes"], "families_never_mixed": True, "one_case_at_a_time": True, "historical_alias_excluded": True, "root_guard_required": True, "request_created_by_planner": False, "launch_performed": False},
        "source_read_policy": {"plan_inventory_overlay_json_opened": True, "current_audit_json_opened_by_delegated_builder": True, "trajectory_stat_only": True, "trajectory_content_opened": False, "trajectory_content_hashed": False, "jsonl_content_opened": False, "native_or_bi4_opened": False, "solver_started": False},
        "source_read_cost": {"selected_deferred_source_bytes": batch["source_bytes"], "minimum_deferred_read_passes": 3, "minimum_deferred_read_bytes": batch["source_bytes"] * 3, "delegated_estimated_input_read_bytes": int(delegated.get("estimated_input_read_bytes", 0)), "per_case_record_cap_bytes": 512 * 1024 * 1024, "per_case_summary_cap_bytes": 2 * 1024 * 1024, "aggregate_storage_conservative": True},
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "native_exit_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }
    _atomic(selection_path, selection)
    selection_ref = ROOT280._small_ref(selection_path, f"{namespace} selection manifest")
    ROOT280._add_ref(refs, selection_ref)
    input_sha = {path: ref["sha256"] for path, ref in sorted(refs.items())}
    request_path = output_dir / f"{namespace.lower()}-request.json"
    request = {
        "schema": REQUEST_SCHEMA,
        "shared_runtime_version": "v8",
        "family_id": batch["family_id"],
        "case_id": f"{namespace}_{batch['family_id']}_TYPED_LIFECYCLE_CONTINUATION",
        "physical_case_ids": batch["case_ids"],
        "attempt_id": f"{namespace.lower()}-typed-lifecycle-{batch['family_id'].lower()}-root-forward",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 3600, "max_memory_bytes": 4 * 1024 * 1024 * 1024,
        "estimated_storage_bytes": int(delegated.get("estimated_storage_bytes", 0)),
        "estimated_cpu_core_hours": float(delegated.get("estimated_cpu_core_hours", 0.0)),
        "estimated_gpu_seconds": 0, "estimated_deferred_source_bytes": batch["source_bytes"],
        "estimated_deferred_read_passes": 3, "estimated_deferred_read_bytes": batch["source_bytes"] * 3,
        "estimated_input_read_bytes": sum(int(ref["bytes"]) for ref in refs.values()),
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY),
        "command": delegated["command"], "input_files": sorted(input_sha), "input_sha256": dict(sorted(input_sha.items())),
        "deferred_input_files": delegated.get("deferred_input_files", []), "deferred_input_records": deferred,
        "output_files": delegated.get("output_files", []), "manifest_contract": delegated["manifest_contract"],
        "selection_manifest_contract": {"path": str(selection_path), "sha256": selection_ref["sha256"]},
        "source_read_cost": selection["source_read_cost"],
        "guarded_payload_binding": {"trajectory_h5": "deferred per case after reservation pre-hash/stream/post-hash", "raw_bi4_content_read": False, "solver_started": False, "cfd_or_model_started": False},
        "claim_boundary": selection["qualification_boundary"], "launch_allowed": True, "execution_allowed": True,
        "launch_owner": "root", "shared_lease_required": True,
        "request_note": f"{namespace} source-only wrapper around immutable delegated V4 batch request. Selected exact CURRENT rows remaining after ROOT280/281 source preparation; this is not actual pending/completion evidence. Root must rebind against a fresh actual registry before launch. No payload was opened here and no scientific qualification is granted.",
    }
    _atomic(request_path, request)
    return {"namespace": namespace, "family_id": batch["family_id"], "group_id": batch["group_id"], "case_ids": batch["case_ids"], "case_count": len(batch["case_ids"]), "source_bytes": batch["source_bytes"], "minimum_deferred_read_bytes": batch["source_bytes"] * 3, "selected_original118_unlocated_case_ids": batch["selected_original118_unlocated_case_ids"], "selected_historical_original118_case_ids": batch["selected_historical_original118_case_ids"], "output_dir": str(output_dir), "selection_manifest": str(selection_path), "selection_manifest_sha256": selection_ref["sha256"], "request": str(request_path), "request_sha256": _sha_file(request_path, f"{namespace} wrapper request"), "delegated_manifest": str(delegated_manifest), "delegated_request": str(delegated_request), "trajectory_content_opened": False, "trajectory_content_hashed": False, "solver_started": False}


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    if output_root.exists():
        raise QueueError(f"refusing existing queue output: {output_root}")
    plan, base_refs, prepared, scope = _validate_frozen_inputs()
    batches = _partition(plan, prepared, scope)
    prepared_refs = [ROOT280._small_ref(ROOT280_SELECTION, "ROOT280 immutable selection", ROOT280_SELECTION_SHA), ROOT280._small_ref(ROOT281_SELECTION, "ROOT281 immutable selection", ROOT281_SELECTION_SHA)]
    results = []
    for batch in batches:
        results.append(_make_batch(batch, output_root, base_refs, plan, prepared_refs))
    output_root.mkdir(parents=True, exist_ok=True)
    queue_path = output_root / "root282-root307-source-queue.json"
    total_bytes = sum(int(result["source_bytes"]) for result in results)
    queue = {
        "schema": QUEUE_SCHEMA,
        "status": "READY_SOURCE_ONLY_NO_LAUNCH",
        "namespace_range": ["ROOT282", "ROOT307"],
        "frozen_plan": base_refs["plan"],
        "prepared_prior_selection_manifests": [{"path": str(ROOT280_SELECTION), "sha256": ROOT280_SELECTION_SHA, "case_count": 4}, {"path": str(ROOT281_SELECTION), "sha256": ROOT281_SELECTION_SHA, "case_count": 6}],
        "remaining_exact_unscheduled_case_count": 202,
        "batch_count": len(results),
        "total_declared_deferred_source_bytes": total_bytes,
        "minimum_deferred_read_bytes_three_pass": total_bytes * 3,
        "remaining_original118_unlocated_case_count": sum(len(batch["selected_original118_unlocated_case_ids"]) for batch in batches),
        "remaining_historical_original118_case_count": sum(len(batch["selected_historical_original118_case_ids"]) for batch in batches),
        "batches": results,
        "selection_policy": {"single_family_per_batch": True, "max_cases": MAX_CASES, "max_declared_source_bytes": MAX_GROUP_BYTES, "actual_running_excluded": True, "actual_completed_excluded": True, "pending_no_credit_excluded": True, "historical_alias_excluded": True, "root_recheck_latest_registry_before_launch": True},
        "source_read_policy": {"plan_inventory_overlay_json_opened": True, "trajectory_stat_only": True, "trajectory_content_opened": False, "trajectory_content_hashed": False, "jsonl_content_opened": False, "native_or_bi4_opened": False, "solver_started": False},
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "native_exit_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "source_note": "This is a source-prepared partition of the frozen ROOT269 plan. It is not a current completion or pending registry; the root runner must re-check fresh actual coverage and source hashes before any launch.",
    }
    _atomic(queue_path, queue)
    return {"status": queue["status"], "queue": str(queue_path), "queue_sha256": _sha_file(queue_path, "source queue"), "batch_count": len(results), "case_count": 202, "total_declared_deferred_source_bytes": total_bytes, "minimum_deferred_read_bytes_three_pass": total_bytes * 3, "namespaces": [result["namespace"] for result in results], "trajectory_content_opened": False, "solver_started": False}


def self_test() -> dict[str, Any]:
    for number in (282, 299, 310):
        _namespace(number)
    try:
        _namespace(281)
    except QueueError:
        pass
    else:
        raise QueueError("namespace lower bound was not enforced")
    return {"status": "PASS", "schema": QUEUE_SCHEMA, "payload_content_opened": False, "launch_performed": False, "max_cases": MAX_CASES, "max_group_bytes": MAX_GROUP_BYTES}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare-all")
    prep.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = self_test() if args.action == "self-test" else prepare(args)
    except (QueueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"ROOT_LIFECYCLE_QUEUE_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

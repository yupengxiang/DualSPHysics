#!/usr/bin/env python3
"""Prepare a source-closed continuation batch for an exact ROOT269 group.

This wrapper consumes the frozen ROOT269 pending plan, the exact CURRENT336
and audit catalogues, the 118-case source inventory, and the current V10
cause-scope overlay.  It selects only exact, non-alias, still-unscheduled
cases from one family group.  For the first F4/F6 deliveries the selection is
limited to cases that are both in the original 118 inventory and still in the
overlay's unlocated-cause set.  The reviewed V4 batch request builder then
creates the per-case manifests and deferred H5 request.  The H5 paths are
stat/declaration-only at prepare time; no payload, JSONL, native file, or
solver is opened here.

The generated ROOT280/ROOT281 request is a fresh source wrapper around the
immutable generic batch manifest.  It keeps the generic worker/request bytes
and adds the pending-plan, inventory, overlay, and selection closure so the
root runner can perform its own final rebind before any launch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
ORIGINAL = Path("/home/jade/Projects/DualSPHysics")
LAB = ORIGINAL / "lagrangian-fluid-lab"
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
SCRIPTS = PRIMARY / "lagrangian-fluid-lab/scripts"
VENV = LAB / ".venv/bin/python"
CONFIG = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"
CURRENT = STAGE2 / "CURRENT336.json"
AUDIT = STAGE2 / "checkpoints/SCIENTIFIC_AUDIT_VERIFICATION_023.json"
PLAN = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_ROOT269_PENDING_V4.json"
INVENTORY = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
OVERLAY = STAGE2 / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"
GENERIC_BUILDER = SCRIPTS / "ds_data02_stage2_typed_lifecycle_batch_request_v1.py"
V4_WORKER = SCRIPTS / "ds_data02_stage2_typed_lifecycle_sidecar_v4.py"
BATCH_WORKER = SCRIPTS / "ds_data02_stage2_typed_lifecycle_batch_worker_v1.py"
RUNTIME_V2 = SCRIPTS / "ds_data02_runtime_v2.py"
RUNTIME_V6 = SCRIPTS / "ds_data02_runtime_v6.py"
RUNTIME_V8 = SCRIPTS / "ds_data02_runtime_v8.py"
DISPATCH_V8 = SCRIPTS / "ds_data02_stage2_dispatch_v8.py"
STRICT_V8 = SCRIPTS / "ds_data02_strict_dispatch_v8.py"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
AUDIT_SHA = "72fd44794443130ab129d75593a4d6689c889cf3af859cd602d11d540acf2881"
PLAN_SHA = "09727374ae7c87b56ce1ddc866cab86c270e111509c25dfe556859d6747e1541"
INVENTORY_SHA = "3d274db71d01f680b9997cc364298f9974a2cb09978acfb81f9a152622e75a00"
OVERLAY_SHA = "72683cdf4b96c334b6f6d6f2df668c9c15f30323b39fcf3473d230c5475e1224"
MAX_SMALL_BYTES = 10 * 1024 * 1024
MAX_CASES = 8
MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4"}
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v4"
SELECTION_SCHEMA = "ds02.stage2.root-lifecycle-selection.v1"
REQUEST_SCHEMA = "ds02.request.v1"


class RootLifecycleError(ValueError):
    pass


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise RootLifecycleError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise RootLifecycleError(f"{label} is not hexadecimal")
    return value


def _file(value: Any, label: str, *, allow_deferred: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise RootLifecycleError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not allow_deferred and path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise RootLifecycleError(f"{label} is deferred payload content: {path}")
    if not path.is_file():
        raise RootLifecycleError(f"{label} is missing: {path}")
    return path


def _stat(path: Path, label: str, *, allow_deferred: bool = False) -> dict[str, Any]:
    path = _file(path, label, allow_deferred=allow_deferred)
    st = path.stat()
    return {"path": str(path), "bytes": int(st.st_size), "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns), "st_dev": int(st.st_dev), "st_ino": int(st.st_ino)}


def _sha_file(path: Path, label: str, *, limit: int | None = None) -> str:
    path = _file(path, label)
    if limit is not None and path.stat().st_size > limit:
        raise RootLifecycleError(f"{label} exceeds bounded content read")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _small_ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    value = _stat(path, label)
    if value["bytes"] > MAX_SMALL_BYTES:
        raise RootLifecycleError(f"{label} exceeds bounded source size")
    actual = _sha_file(path, label, limit=MAX_SMALL_BYTES)
    if expected is not None and actual != _sha(expected, f"{label} expected SHA"):
        raise RootLifecycleError(f"{label} SHA differs")
    value.update({"sha256": actual, "content_opened": True})
    return value


def _declared_ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    """Reference an already hashed input without reopening large metadata."""
    value = _stat(path, label)
    if expected is None:
        if value["bytes"] > MAX_SMALL_BYTES:
            raise RootLifecycleError(f"{label} needs a declared SHA for bounded preparation")
        expected = _sha_file(path, label, limit=MAX_SMALL_BYTES)
        opened = True
    else:
        expected = _sha(expected, f"{label} declared SHA")
        opened = value["bytes"] <= MAX_SMALL_BYTES and _sha_file(path, label, limit=MAX_SMALL_BYTES) == expected
        if value["bytes"] <= MAX_SMALL_BYTES and not opened:
            raise RootLifecycleError(f"{label} declared SHA differs")
    value.update({"sha256": expected, "content_opened": opened})
    return value


def _json(path: Path, label: str) -> dict[str, Any]:
    path = _file(path, label)
    if path.stat().st_size > MAX_SMALL_BYTES:
        raise RootLifecycleError(f"{label} exceeds bounded JSON size")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RootLifecycleError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise RootLifecycleError(f"{label} must be a JSON object")
    return value


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_SMALL_BYTES) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise RootLifecycleError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise RootLifecycleError(f"{path} exceeds output bound")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _add_ref(refs: dict[str, dict[str, Any]], ref: dict[str, Any]) -> None:
    path = ref["path"]
    previous = refs.get(path)
    if previous is not None and previous["sha256"] != ref["sha256"]:
        raise RootLifecycleError(f"conflicting source SHA for {path}")
    refs[path] = ref


def _namespace(value: str) -> str:
    value = str(value).upper()
    if not re.fullmatch(r"ROOT(?:28[0-9]|29[0-9]|30[0-9])", value):
        raise RootLifecycleError("namespace must be ROOT280 through ROOT309")
    return value


def _load_scope(plan_path: Path, inventory_path: Path, overlay_path: Path, family: str, group_id: str) -> tuple[dict[str, Any], dict[str, Any], list[str], dict[str, Any]]:
    plan_ref = _small_ref(plan_path, "ROOT269 pending plan", PLAN_SHA)
    plan = _json(plan_path, "ROOT269 pending plan")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("status") != "PREPARED_METADATA_ONLY_NO_LAUNCH":
        raise RootLifecycleError("ROOT269 plan schema/status differs")
    coverage = plan.get("coverage")
    expected_coverage = {"actual_saved_mask_cases": 116, "current_cases": 336, "exact_current_audit_rows": 335, "historical_alias_unresolved": 1, "incomplete_or_mismatched": 0, "pending_no_credit_cases": 7, "physical_or_scientific_credit_cases": 0, "remaining_exact_unscheduled_cases": 212}
    if not isinstance(coverage, dict) or any(coverage.get(key) != value for key, value in expected_coverage.items()):
        raise RootLifecycleError("ROOT269 plan coverage partition differs")
    inv_ref = _small_ref(inventory_path, "historical 118 inventory", INVENTORY_SHA)
    inventory = _json(inventory_path, "historical 118 inventory")
    rows = inventory.get("rows")
    if not isinstance(rows, list) or len(rows) != 118:
        raise RootLifecycleError("historical inventory is not exactly 118 rows")
    historical = {row.get("identity", {}).get("current_physical_case_id") for row in rows if isinstance(row, dict) and row.get("historical_118_membership") is True}
    if len(historical) != 118 or None in historical:
        raise RootLifecycleError("historical inventory membership is not exact")
    overlay_ref = _small_ref(overlay_path, "ROOT268 actual V10 overlay", OVERLAY_SHA)
    overlay = _json(overlay_path, "ROOT268 actual V10 overlay")
    if overlay.get("status") != "VERIFIED_METADATA_JOIN_TO_ACTUAL_PER_ID_PROOFS":
        raise RootLifecycleError("ROOT268 V10 overlay is not verified")
    unlocated = overlay.get("remaining_cause_not_located_case_ids")
    if not isinstance(unlocated, list) or not all(isinstance(item, str) for item in unlocated):
        raise RootLifecycleError("ROOT268 V10 overlay lacks exact unlocated IDs")
    groups = plan.get("groups")
    group = next((row for row in groups if isinstance(row, dict) and row.get("group_id") == group_id), None) if isinstance(groups, list) else None
    if not isinstance(group, dict) or group.get("family_id") != family:
        raise RootLifecycleError(f"{group_id} is not an exact {family} plan group")
    case_ids = group.get("case_ids")
    if not isinstance(case_ids, list) or not 0 < len(case_ids) <= MAX_CASES or len(set(case_ids)) != len(case_ids):
        raise RootLifecycleError("plan group case IDs are not bounded/unique")
    if group.get("status") != "UNSCHEDULED_METADATA_ONLY" or group.get("request_created") is not False or group.get("launch_allowed_by_planner") is not False:
        raise RootLifecycleError("plan group is already scheduled")
    case_records = {row.get("physical_case_id"): row for row in plan.get("case_records", []) if isinstance(row, dict) and isinstance(row.get("physical_case_id"), str)}
    if len(case_records) != 336:
        raise RootLifecycleError("ROOT269 plan does not contain exactly 336 case records")
    actual = {case_id for case_id, row in case_records.items() if row.get("status") == "ACTUAL_SAVED_MASK_COMPLETED"}
    aliases = {case_id for case_id, row in case_records.items() if row.get("historical_alias") != "NONE"}
    selected = []
    diagnostic_excluded = []
    for case_id in case_ids:
        row = case_records.get(case_id)
        if not isinstance(row, dict) or row.get("family_id") != family or row.get("status") != "UNSCHEDULED_EXACT_CURRENT_AUDIT":
            raise RootLifecycleError(f"{case_id} is not an unscheduled exact row")
        if row.get("source_join_status") != "EXACT_CURRENT_AUDIT_METADATA_JOIN" or case_id in actual or case_id in aliases:
            raise RootLifecycleError(f"{case_id} overlaps actual/alias scope")
        if case_id in historical and case_id in set(unlocated):
            selected.append(case_id)
        else:
            diagnostic_excluded.append(case_id)
    if not selected:
        raise RootLifecycleError(f"{group_id} contains no remaining original118 unlocated case")
    selected_bytes = sum(int(case_records[case_id].get("declared_source_bytes", -1)) for case_id in selected)
    if selected_bytes <= 0 or selected_bytes > MAX_GROUP_BYTES:
        raise RootLifecycleError("selected source bytes exceed bound")
    return plan, {"plan": plan_ref, "inventory": inv_ref, "overlay": overlay_ref}, selected, {"group": group, "case_records": case_records, "historical": sorted(historical), "unlocated": sorted(set(unlocated)), "actual": sorted(actual), "aliases": sorted(aliases), "diagnostic_excluded": diagnostic_excluded, "selected_declared_source_bytes": selected_bytes}


def _run_generic(args: argparse.Namespace, selected: list[str], output_dir: Path) -> tuple[dict[str, Any], Path, Path]:
    command = [
        str(args.python), str(GENERIC_BUILDER), "prepare",
        "--current", str(args.current), "--audit-verification", str(args.audit),
        "--expected-current-sha256", CURRENT_SHA, "--expected-audit-sha256", AUDIT_SHA,
        "--family", args.family, "--max-cases", str(MAX_CASES), "--max-group-bytes", str(MAX_GROUP_BYTES),
        "--output-dir", str(output_dir / "delegated"), "--v4-worker", str(V4_WORKER), "--batch-worker", str(BATCH_WORKER),
        "--python", str(args.python), "--runtime-config", str(args.runtime_config),
        "--runtime-v2", str(RUNTIME_V2), "--runtime-v6", str(RUNTIME_V6), "--runtime-v8", str(RUNTIME_V8),
        "--dispatch-v8", str(DISPATCH_V8), "--strict-v8", str(STRICT_V8),
        "--cwd", str(PRIMARY / "lagrangian-fluid-lab"), "--worktree-root", str(PRIMARY),
    ]
    for case_id in selected:
        command.extend(["--case-id", case_id])
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    try:
        result = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RootLifecycleError(f"generic builder did not return JSON: {completed.stdout[-1000:]}") from exc
    delegated_manifest = Path(result["manifest"]).expanduser().resolve()
    delegated_request = Path(result["request"]).expanduser().resolve()
    return result, delegated_manifest, delegated_request


def _delegated_refs(request: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    input_sha = request.get("input_sha256")
    if not isinstance(input_sha, dict) or not input_sha:
        raise RootLifecycleError(f"{label} has no input SHA closure")
    refs: dict[str, dict[str, Any]] = {}
    for path_value, expected in input_sha.items():
        path = _file(path_value, f"{label} input", allow_deferred=False)
        if path.suffix.lower() in PAYLOAD_SUFFIXES:
            raise RootLifecycleError(f"{label} input unexpectedly contains payload: {path}")
        refs[str(path)] = _declared_ref(path, f"{label} input", expected)
    return refs


def _producer_refs(plan: dict[str, Any], refs: dict[str, dict[str, Any]]) -> None:
    for producer in plan.get("producer_evidence", []):
        if not isinstance(producer, dict) or not str(producer.get("status", "")).startswith("ACTUAL"):
            continue
        evidence = producer.get("evidence")
        proof = evidence.get("proof") if isinstance(evidence, dict) else None
        if isinstance(proof, dict) and isinstance(proof.get("path"), str) and isinstance(proof.get("sha256"), str):
            path = _file(proof["path"], f"{producer.get('producer_id')} proof")
            _add_ref(refs, _small_ref(path, f"{producer.get('producer_id')} completed proof", proof["sha256"]))


def _prepare(args: argparse.Namespace) -> dict[str, Any]:
    namespace = _namespace(args.namespace)
    family = str(args.family).upper()
    if family not in {"F4", "F6"}:
        raise RootLifecycleError("first delivery supports only F4 or F6")
    plan_path = _file(args.plan, "ROOT269 pending plan")
    inventory_path = _file(args.inventory, "historical 118 inventory")
    overlay_path = _file(args.overlay, "ROOT268 V10 overlay")
    current_path = _file(args.current, "CURRENT336")
    audit_path = _file(args.audit, "scientific audit")
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.exists():
        raise RootLifecycleError(f"refusing to reuse source output directory: {output_dir}")
    plan, base_refs, selected, details = _load_scope(plan_path, inventory_path, overlay_path, family, args.group_id)
    selected_source_bytes = details["selected_declared_source_bytes"]
    generic_result, delegated_manifest, delegated_request = _run_generic(args, selected, output_dir)
    delegated = _json(delegated_request, "delegated batch request")
    delegated_manifest_value = _json(delegated_manifest, "delegated batch manifest")
    if delegated.get("schema") != REQUEST_SCHEMA or delegated.get("family_id") != family:
        raise RootLifecycleError("delegated request schema/family differs")
    if delegated.get("physical_case_ids") != selected:
        raise RootLifecycleError("delegated request selected IDs differ")
    if delegated_manifest_value.get("case_count") != len(selected):
        raise RootLifecycleError("delegated manifest case count differs")
    delegated_bytes = int(delegated.get("estimated_deferred_source_bytes", -1))
    if delegated_bytes != selected_source_bytes:
        raise RootLifecycleError(f"H5 stat bytes differ from frozen plan: plan={selected_source_bytes}, builder={delegated_bytes}")
    refs: dict[str, dict[str, Any]] = {}
    for ref in base_refs.values():
        _add_ref(refs, ref)
    for path, label in ((current_path, "CURRENT336"), (audit_path, "scientific audit"), (GENERIC_BUILDER, "generic batch request builder"), (V4_WORKER, "V4 worker"), (BATCH_WORKER, "batch worker"), (SCRIPT, "ROOT selection wrapper"), (VENV, "literal Python interpreter"), (CONFIG, "DsphConfig.xml"), (RUNTIME_V2, "runtime v2"), (RUNTIME_V6, "runtime v6"), (RUNTIME_V8, "runtime v8"), (DISPATCH_V8, "dispatch v8"), (STRICT_V8, "strict dispatch v8")):
        _add_ref(refs, _small_ref(path, label))
    _producer_refs(plan, refs)
    _add_ref(refs, _small_ref(delegated_manifest, "delegated immutable batch manifest"))
    _add_ref(refs, _small_ref(delegated_request, "delegated immutable batch request"))
    for ref in _delegated_refs(delegated, "delegated batch request").values():
        _add_ref(refs, ref)
    deferred = delegated.get("deferred_input_records", delegated_manifest_value.get("deferred_trajectory_h5", []))
    if not isinstance(deferred, list) or len(deferred) != len(selected):
        raise RootLifecycleError("delegated deferred trajectory records are incomplete")
    selection_manifest_path = output_dir / f"{namespace.lower()}-selection-manifest.json"
    selection_manifest = {
        "schema": SELECTION_SCHEMA,
        "status": "READY_SOURCE_ONLY_NO_LAUNCH",
        "namespace": namespace,
        "family_id": family,
        "group_id": args.group_id,
        "plan": base_refs["plan"],
        "inventory": base_refs["inventory"],
        "overlay": base_refs["overlay"],
        "current_catalog": {"path": str(current_path), "sha256": CURRENT_SHA},
        "scientific_audit": {"path": str(audit_path), "sha256": AUDIT_SHA},
        "selected_case_ids": selected,
        "selected_case_count": len(selected),
        "selected_original118_unlocated_count": len(selected),
        "diagnostic_cases_excluded_from_plan_group": details["diagnostic_excluded"],
        "plan_group_case_count": int(details["group"]["case_count"]),
        "plan_group_declared_source_bytes": int(details["group"]["declared_source_bytes"]),
        "selected_declared_source_bytes": selected_source_bytes,
        "delegated_batch_manifest": {"path": str(delegated_manifest), "sha256": _sha_file(delegated_manifest, "delegated manifest", limit=MAX_SMALL_BYTES)},
        "delegated_batch_request": {"path": str(delegated_request), "sha256": _sha_file(delegated_request, "delegated request", limit=MAX_SMALL_BYTES)},
        "deferred_trajectory_h5": deferred,
        "source_refs": sorted(refs.values(), key=lambda value: value["path"]),
        "group_policy": {"max_cases": MAX_CASES, "max_declared_source_bytes": MAX_GROUP_BYTES, "selected_source_bytes": selected_source_bytes, "families_never_mixed": True, "one_case_at_a_time": True, "historical_alias_excluded": True, "root_guard_required": True, "request_created_by_planner": False, "launch_performed": False},
        "source_read_policy": {"plan_inventory_overlay_json_opened": True, "current_audit_json_opened_by_delegated_builder": True, "trajectory_stat_only": True, "trajectory_content_opened": False, "trajectory_content_hashed": False, "jsonl_content_opened": False, "native_or_bi4_opened": False, "solver_started": False},
        "source_read_cost": {"selected_deferred_source_bytes": selected_source_bytes, "minimum_deferred_read_passes": 3, "minimum_deferred_read_bytes": selected_source_bytes * 3, "delegated_estimated_input_read_bytes": int(delegated.get("estimated_input_read_bytes", 0)), "per_case_record_cap_bytes": 512 * 1024 * 1024, "per_case_summary_cap_bytes": 2 * 1024 * 1024, "aggregate_storage_conservative": True},
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "native_exit_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }
    _atomic(selection_manifest_path, selection_manifest)
    selection_ref = _small_ref(selection_manifest_path, "selection manifest")
    _add_ref(refs, selection_ref)
    input_sha = {path: ref["sha256"] for path, ref in sorted(refs.items())}
    request_path = output_dir / f"{namespace.lower()}-request.json"
    request = {
        "schema": REQUEST_SCHEMA,
        "shared_runtime_version": "v8",
        "family_id": family,
        "case_id": f"{namespace}_{family}_TYPED_LIFECYCLE_CONTINUATION",
        "physical_case_ids": selected,
        "attempt_id": f"{namespace.lower()}-typed-lifecycle-{family.lower()}-root-forward",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 3600,
        "max_memory_bytes": 4 * 1024 * 1024 * 1024,
        "estimated_storage_bytes": int(delegated.get("estimated_storage_bytes", 0)),
        "estimated_cpu_core_hours": float(delegated.get("estimated_cpu_core_hours", 0.0)),
        "estimated_gpu_seconds": 0,
        "estimated_deferred_source_bytes": delegated_bytes,
        "estimated_deferred_read_passes": 3,
        "estimated_deferred_read_bytes": delegated_bytes * 3,
        "estimated_input_read_bytes": sum(int(ref["bytes"]) for ref in refs.values()),
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"),
        "worktree_root": str(PRIMARY),
        "command": delegated["command"],
        "input_files": sorted(input_sha),
        "input_sha256": dict(sorted(input_sha.items())),
        "deferred_input_files": delegated.get("deferred_input_files", []),
        "deferred_input_records": deferred,
        "output_files": delegated.get("output_files", []),
        "manifest_contract": delegated["manifest_contract"],
        "selection_manifest_contract": {"path": str(selection_manifest_path), "sha256": selection_ref["sha256"]},
        "source_read_cost": selection_manifest["source_read_cost"],
        "guarded_payload_binding": {"trajectory_h5": "deferred per case after reservation pre-hash/stream/post-hash", "raw_bi4_content_read": False, "solver_started": False, "cfd_or_model_started": False},
        "claim_boundary": selection_manifest["qualification_boundary"],
        "launch_allowed": True,
        "execution_allowed": True,
        "launch_owner": "root",
        "shared_lease_required": True,
        "request_note": f"{namespace} source-only wrapper around immutable delegated V4 batch request. Selected only remaining original118 {family} cases in the exact ROOT269 UNSCHEDULED plan group; diagnostic/non-original group members and aliases are excluded. No payload was opened here and no scientific qualification is granted.",
    }
    _atomic(request_path, request)
    return {"status": selection_manifest["status"], "namespace": namespace, "family_id": family, "group_id": args.group_id, "case_count": len(selected), "case_ids": selected, "selected_source_bytes": selected_source_bytes, "minimum_deferred_read_bytes": selected_source_bytes * 3, "delegated_manifest": str(delegated_manifest), "delegated_request": str(delegated_request), "selection_manifest": str(selection_manifest_path), "selection_manifest_sha256": selection_ref["sha256"], "request": str(request_path), "request_sha256": _sha_file(request_path, "ROOT request", limit=MAX_SMALL_BYTES), "trajectory_content_opened": False, "trajectory_content_hashed": False, "solver_started": False}


def self_test() -> dict[str, Any]:
    for value in ("ROOT280", "ROOT299", "ROOT309"):
        _namespace(value)
    try:
        _namespace("ROOT279")
    except RootLifecycleError:
        pass
    else:
        raise RootLifecycleError("namespace lower bound was not enforced")
    return {"status": "PASS", "schema": SELECTION_SCHEMA, "payload_content_opened": False, "launch_performed": False, "families_never_mixed": True, "max_cases": MAX_CASES, "max_group_bytes": MAX_GROUP_BYTES}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--namespace", required=True)
    prep.add_argument("--family", required=True)
    prep.add_argument("--group-id", required=True)
    prep.add_argument("--plan", type=Path, default=PLAN)
    prep.add_argument("--inventory", type=Path, default=INVENTORY)
    prep.add_argument("--overlay", type=Path, default=OVERLAY)
    prep.add_argument("--current", type=Path, default=CURRENT)
    prep.add_argument("--audit", type=Path, default=AUDIT)
    prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--python", type=Path, default=VENV)
    prep.add_argument("--runtime-config", type=Path, default=CONFIG)
    args = parser.parse_args(argv)
    try:
        result = self_test() if args.action == "self-test" else _prepare(args)
    except (RootLifecycleError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"ROOT_LIFECYCLE_SELECTION_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

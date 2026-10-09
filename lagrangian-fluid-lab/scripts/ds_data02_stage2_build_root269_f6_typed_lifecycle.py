#!/usr/bin/env python3
"""Prepare the next exact F6 lifecycle group after ROOT262.

This wrapper binds the latest immutable CURRENT/audit continuation plan before
delegating case-manifest construction to the reviewed V4 batch builder.  It
selects only the seven cases in the first unscheduled F6 group, verifies that
they are exact CURRENT/audit rows and historical-118 members, and binds the
plan plus all completed producer proofs into a fresh source request.  It does
not open HDF5/JSONL/BI4/OBI4 payloads, submit a job, or start a solver.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
SCRIPTS = PRIMARY / "lagrangian-fluid-lab/scripts"
GENERIC_BUILDER = SCRIPTS / "ds_data02_stage2_typed_lifecycle_batch_request_v1.py"
V4_WORKER = SCRIPTS / "ds_data02_stage2_typed_lifecycle_sidecar_v4.py"
BATCH_WORKER = SCRIPTS / "ds_data02_stage2_typed_lifecycle_batch_worker_v1.py"
CURRENT = STAGE2 / "CURRENT336.json"
AUDIT = STAGE2 / "checkpoints/SCIENTIFIC_AUDIT_VERIFICATION_023.json"
PLAN = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT262_V4.json"
INVENTORY = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
OVERLAY = STAGE2 / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT259_ACTUAL_OVERLAY_V7.json"
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
CONFIG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")
RUNTIME_V2 = SCRIPTS / "ds_data02_runtime_v2.py"
RUNTIME_V6 = SCRIPTS / "ds_data02_runtime_v6.py"
RUNTIME_V8 = SCRIPTS / "ds_data02_runtime_v8.py"
DISPATCH_V8 = SCRIPTS / "ds_data02_stage2_dispatch_v8.py"
STRICT_V8 = SCRIPTS / "ds_data02_strict_dispatch_v8.py"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
AUDIT_SHA = "72fd44794443130ab129d75593a4d6689c889cf3af859cd602d11d540acf2881"
PLAN_SHA = "143f429a205af104f89fbf2d74f6f9e9c95c363c8ba927d57af40e3d7779654a"
OVERLAY_SHA = "bc9e9e9ac3561e6b8c577aa8e98e778c80da90d6f01456077534c73c83a68d64"
GROUP_ID = "F6-typed-lifecycle-continuation-000"
MAX_CASES = 8
MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024
MAX_SMALL_BYTES = 10 * 1024 * 1024
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4"}
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v4"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
AUDIT_SCHEMA = "ds02.stage2.scientific-audit-independent-verification.v23"


class Root269Error(ValueError):
    pass


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise Root269Error(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise Root269Error(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise Root269Error(f"{label} has no path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise Root269Error(f"{label} is missing: {path}")
    return path


def _digest(path: Path, label: str, *, limit: int = MAX_SMALL_BYTES) -> str:
    path = _path(path, label)
    if path.stat().st_size > limit:
        raise Root269Error(f"{label} exceeds the bounded source limit")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    path = _path(path, label)
    stat = path.stat()
    value = {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": _digest(path, label),
        "content_opened": True,
    }
    if expected is not None and value["sha256"] != _sha(expected, f"{label} expected SHA"):
        raise Root269Error(f"{label} SHA differs")
    return value


def _json(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > MAX_SMALL_BYTES:
        raise Root269Error(f"{label} exceeds small JSON bound")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Root269Error(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise Root269Error(f"{label} must be a JSON object")
    return value


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_SMALL_BYTES) -> None:
    path = Path(path).expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise Root269Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise Root269Error(f"{path} exceeds output limit")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_scope(plan_path: Path, current_path: Path, audit_path: Path, inventory_path: Path, overlay_path: Path) -> tuple[dict[str, Any], list[str], dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan_ref = _ref(plan_path, "ROOT269 continuation plan", PLAN_SHA)
    plan = _json(plan_path, "ROOT269 continuation plan")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("status") != "PREPARED_METADATA_ONLY_NO_LAUNCH":
        raise Root269Error("latest continuation plan schema/status differs")
    coverage = plan.get("coverage")
    expected_coverage = {
        "actual_saved_mask_cases": 116,
        "current_cases": 336,
        "exact_current_audit_rows": 335,
        "historical_alias_unresolved": 1,
        "incomplete_or_mismatched": 0,
        "pending_no_credit_cases": 0,
        "physical_or_scientific_credit_cases": 0,
        "remaining_exact_unscheduled_cases": 219,
    }
    if not isinstance(coverage, dict) or any(coverage.get(k) != v for k, v in expected_coverage.items()):
        raise Root269Error("latest plan coverage partition differs")
    current_ref = _ref(current_path, "CURRENT336", CURRENT_SHA)
    audit_ref = _ref(audit_path, "scientific audit verification", AUDIT_SHA)
    inventory_ref = _ref(inventory_path, "historical 118 inventory")
    overlay_ref = _ref(overlay_path, "original118 cause overlay", OVERLAY_SHA)
    overlay = _json(overlay_path, "original118 cause overlay")
    remaining_unlocated = overlay.get("remaining_cause_not_located_case_ids")
    if not isinstance(remaining_unlocated, list) or not all(isinstance(item, str) for item in remaining_unlocated):
        raise Root269Error("latest original118 cause overlay has no exact unlocated case set")
    inventory = _json(inventory_path, "historical 118 inventory")
    rows = inventory.get("rows")
    if not isinstance(rows, list) or len(rows) != 118:
        raise Root269Error("historical inventory is not the exact 118-case inventory")
    historical = {row.get("physical_case_id") for row in rows if isinstance(row, dict) and row.get("historical_118_membership") is True}
    if len(historical) != 118:
        raise Root269Error("historical inventory membership is not exactly 118")
    groups = plan.get("groups")
    group = next((item for item in groups if isinstance(item, dict) and item.get("group_id") == GROUP_ID), None) if isinstance(groups, list) else None
    if not isinstance(group, dict) or group.get("family_id") != "F6":
        raise Root269Error("ROOT269 F6 continuation group is missing")
    case_ids = group.get("case_ids")
    if not isinstance(case_ids, list) or len(case_ids) != 7 or len(case_ids) != len(set(case_ids)):
        raise Root269Error("ROOT269 group must contain seven unique cases")
    if group.get("status") != "UNSCHEDULED_METADATA_ONLY" or group.get("request_created") is not False or group.get("launch_allowed_by_planner") is not False:
        raise Root269Error("ROOT269 group is already scheduled")
    source_bytes = int(group.get("declared_source_bytes", -1))
    if not 0 < source_bytes <= MAX_GROUP_BYTES:
        raise Root269Error("ROOT269 group exceeds the 20 GiB source bound")
    case_records = {row.get("physical_case_id"): row for row in plan.get("case_records", []) if isinstance(row, dict) and isinstance(row.get("physical_case_id"), str)}
    if len(case_records) != 336:
        raise Root269Error("latest plan does not expose exactly 336 unique case rows")
    actual = {case_id for case_id, row in case_records.items() if row.get("status") == "ACTUAL_SAVED_MASK_COMPLETED"}
    if len(actual) != 116:
        raise Root269Error("latest plan actual coverage is not 116")
    aliases = {case_id for case_id, row in case_records.items() if row.get("historical_alias") != "NONE"}
    if len(aliases) != 1:
        raise Root269Error("latest plan alias partition is not one")
    selected_rows = []
    for case_id in case_ids:
        row = case_records.get(case_id)
        if not isinstance(row, dict) or row.get("family_id") != "F6" or row.get("status") != "UNSCHEDULED_EXACT_CURRENT_AUDIT":
            raise Root269Error(f"{case_id} is not an unscheduled exact CURRENT/audit row")
        if row.get("source_join_status") != "EXACT_CURRENT_AUDIT_METADATA_JOIN" or row.get("historical_alias") != "NONE" or case_id in actual or case_id in aliases:
            raise Root269Error(f"{case_id} overlaps completed/alias scope")
        if case_id not in historical:
            raise Root269Error(f"{case_id} is outside the historical-118 inventory")
        if case_id not in set(remaining_unlocated):
            raise Root269Error(f"{case_id} is not in the remaining unlocated original118 cause scope")
        selected_rows.append(row)
    if sum(int(row.get("declared_source_bytes", -1)) for row in selected_rows) != source_bytes:
        raise Root269Error("ROOT269 source-byte sum differs from group declaration")
    producer_refs: list[dict[str, Any]] = []
    for producer in plan.get("producer_evidence", []):
        if not isinstance(producer, dict) or not str(producer.get("status", "")).startswith("ACTUAL"):
            continue
        evidence = producer.get("evidence")
        proof = evidence.get("proof") if isinstance(evidence, dict) else None
        if not isinstance(proof, dict):
            raise Root269Error(f"completed producer {producer.get('producer_id')} lacks proof")
        proof_ref = proof.get("path")
        producer_refs.append(_ref(Path(proof_ref), f"{producer.get('producer_id')} completed proof", proof.get("sha256")))
    if not producer_refs:
        raise Root269Error("no completed producer proofs in latest plan")
    refs = {"plan": plan_ref, "current": current_ref, "audit": audit_ref, "inventory": inventory_ref, "overlay": overlay_ref}
    return plan, case_ids, refs, {"actual": sorted(actual), "aliases": sorted(aliases), "historical": sorted(historical)}, {"producer_proofs": producer_refs, "source_bytes": source_bytes}


def _generic_command(output_dir: Path, case_ids: list[str], excluded: set[str], args: argparse.Namespace) -> list[str]:
    command = [
        str(args.python), str(GENERIC_BUILDER), "prepare",
        "--current", str(args.current),
        "--audit-verification", str(args.audit),
        "--expected-current-sha256", CURRENT_SHA,
        "--expected-audit-sha256", AUDIT_SHA,
        "--family", "F6", "--max-cases", str(MAX_CASES), "--max-group-bytes", str(MAX_GROUP_BYTES),
        "--output-dir", str(output_dir / "delegated"),
        "--v4-worker", str(V4_WORKER), "--batch-worker", str(BATCH_WORKER),
        "--python", str(args.python), "--runtime-config", str(args.runtime_config),
        "--runtime-v2", str(RUNTIME_V2), "--runtime-v6", str(RUNTIME_V6),
        "--runtime-v8", str(RUNTIME_V8), "--dispatch-v8", str(DISPATCH_V8), "--strict-v8", str(STRICT_V8),
        "--cwd", str(PRIMARY / "lagrangian-fluid-lab"), "--worktree-root", str(PRIMARY),
    ]
    for case_id in case_ids:
        command.extend(["--case-id", case_id])
    for case_id in sorted(excluded):
        command.extend(["--exclude-case", case_id])
    return command


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    plan, case_ids, refs, partitions, extra = _load_scope(args.plan, args.current, args.audit, args.inventory, args.overlay)
    output_root = args.output_root.expanduser().absolute()
    if output_root.exists():
        raise Root269Error(f"refusing to reuse output directory: {output_root}")
    output_root.mkdir(parents=True, exist_ok=False)
    excluded = set(partitions["actual"]) | set(partitions["aliases"])
    delegated = subprocess.run(_generic_command(output_root, case_ids, excluded, args), check=False, capture_output=True, text=True)
    if delegated.returncode != 0:
        raise Root269Error(f"generic lifecycle builder failed: {(delegated.stderr or delegated.stdout)[-3000:]}")
    try:
        result = json.loads(delegated.stdout)
    except json.JSONDecodeError as exc:
        raise Root269Error("generic lifecycle builder did not return JSON") from exc
    delegated_manifest = _path(result["manifest"], "delegated ROOT269 manifest")
    delegated_request = _path(result["request"], "delegated ROOT269 request")
    delegated_manifest_ref = _ref(delegated_manifest, "delegated ROOT269 manifest", result.get("manifest_sha256"))
    delegated_request_ref = _ref(delegated_request, "delegated ROOT269 request", result.get("request_sha256"))
    original = _json(delegated_request, "delegated ROOT269 request")
    if original.get("physical_case_ids") != case_ids or original.get("family_id") != "F6" or original.get("launch_allowed") is not True:
        raise Root269Error("delegated request did not preserve exact F6 selection")
    plan_ref = refs["plan"]
    selection = {
        "schema": "ds02.stage2.root269-selection.v1",
        "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
        "family_id": "F6",
        "group_id": GROUP_ID,
        "case_ids": case_ids,
        "selected_source_bytes": extra["source_bytes"],
        "latest_plan": plan_ref,
        "cause_overlay": refs["overlay"],
        "coverage_asserted": {"actual_saved_mask_cases": 116, "exact_current_audit_rows": 335, "historical_alias_unresolved": 1, "remaining_exact_unscheduled_cases": 219},
        "excluded_case_ids": sorted(excluded),
        "source_read_policy": {"plan_current_audit_inventory_proofs_opened": True, "trajectory_content_opened": False, "trajectory_content_hashed": False, "jsonl_content_opened": False, "native_or_bi4_opened": False, "solver_started": False, "request_submitted": False},
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "native_exit_cause": "UNKNOWN", "dynamics": "UNKNOWN"},
    }
    selection_path = output_root / "root269-selection.json"
    _atomic(selection_path, selection)
    selection_ref = _ref(selection_path, "ROOT269 selection")
    input_sha = dict(original.get("input_sha256", {}))
    input_files = set(original.get("input_files", []))
    closure_refs = [refs["plan"], refs["current"], refs["audit"], refs["inventory"], refs["overlay"], selection_ref, delegated_manifest_ref, delegated_request_ref, _ref(SCRIPT, "ROOT269 builder"), _ref(GENERIC_BUILDER, "typed lifecycle request builder")]
    closure_refs.extend(extra["producer_proofs"])
    for ref in closure_refs:
        if Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise Root269Error(f"payload entered ROOT269 static closure: {ref['path']}")
        if input_sha.get(ref["path"], ref["sha256"]) != ref["sha256"]:
            raise Root269Error(f"delegated request SHA conflict at {ref['path']}")
        input_sha[ref["path"]] = ref["sha256"]
        input_files.add(ref["path"])
    final = dict(original)
    final.update({
        "status": "READY_NOTRUN_SOURCE_ONLY",
        "case_id": "STAGE2_TYPED_LIFECYCLE_BATCH_F6_ROOT269",
        "attempt_id": "typed-lifecycle-batch-f6-root-269-001-root-forward",
        "launch_allowed": False,
        "execution_allowed": False,
        "request_submitted": False,
        "continuation_group": {"group_id": GROUP_ID, "family_id": "F6", "case_ids": case_ids, "selected_source_bytes": extra["source_bytes"], "latest_plan": plan_ref, "cause_overlay": refs["overlay"], "selected_remaining_original118_cause_not_located": True, "actual_saved_mask_cases_excluded": 116, "historical_alias_excluded": 1, "remaining_exact_unscheduled_cases": 219, "excluded_case_ids": sorted(excluded)},
        "source_closure": {"latest_plan": plan_ref, "current_catalog": refs["current"], "scientific_audit": refs["audit"], "historical_inventory": refs["inventory"], "cause_overlay": refs["overlay"], "completed_producer_proofs": extra["producer_proofs"], "selection": selection_ref, "delegated_manifest": delegated_manifest_ref, "delegated_request": delegated_request_ref, "builder": _ref(SCRIPT, "ROOT269 builder"), "delegated_request_builder": _ref(GENERIC_BUILDER, "typed lifecycle request builder")},
        "source_read_policy": selection["source_read_policy"],
        "claim_boundary": selection["qualification_boundary"],
        "request_note": "ROOT269 is source-only. It selects the first seven exact CURRENT/audit F6 cases from the immutable after-ROOT262 plan, all historical-118 members, excluding 116 actual cases and the one alias. Root must perform a fresh parent reservation and may later rebind a runnable attempt; no physical qualification is granted.",
    })
    final["input_files"] = sorted(input_files)
    final["input_sha256"] = dict(sorted(input_sha.items()))
    final_request = (args.request_output.expanduser().absolute() if args.request_output is not None else output_root / "typed-lifecycle-batch-v1-f6-root-forward-269-001.json")
    _atomic(final_request, final)
    return {"status": final["status"], "family_id": "F6", "group_id": GROUP_ID, "case_ids": case_ids, "request": str(final_request), "request_sha256": _digest(final_request, "ROOT269 final request"), "selected_source_bytes": extra["source_bytes"], "launch_allowed": False, "payload_content_opened": False}


def _self_test() -> dict[str, Any]:
    return {"schema": "ds02.stage2.root269-f6-typed-lifecycle.v1", "status": "PASS", "group_id": GROUP_ID, "case_cap": MAX_CASES, "source_cap_bytes": MAX_GROUP_BYTES, "launch_allowed": False, "payload_content_opened": False, "checks": ["latest plan SHA/coverage 116/335/219", "exact seven unscheduled F6 cases", "historical-118 membership", "producer proof closure", "fresh source-only namespace"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--plan", type=Path, default=PLAN)
    prep.add_argument("--current", type=Path, default=CURRENT)
    prep.add_argument("--audit", type=Path, default=AUDIT)
    prep.add_argument("--inventory", type=Path, default=INVENTORY)
    prep.add_argument("--overlay", type=Path, default=OVERLAY)
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path)
    prep.add_argument("--python", type=Path, default=VENV)
    prep.add_argument("--runtime-config", type=Path, default=CONFIG)
    args = parser.parse_args(argv)
    try:
        if args.action == "self-test":
            result = _self_test()
        else:
            # --request-output is retained for CLI symmetry; the immutable
            # final request lives inside output-root so all source files share
            # one namespace and cannot be accidentally overwritten.
            result = prepare(args)
    except (Root269Error, OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        print(f"ROOT269_F6_PREPARATION_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

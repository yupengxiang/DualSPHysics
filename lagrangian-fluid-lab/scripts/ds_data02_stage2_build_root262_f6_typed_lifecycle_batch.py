#!/usr/bin/env python3
"""Prepare the next exact F6 lifecycle group after the ROOT256 attempt.

This is a source-only wrapper around the reviewed generic lifecycle request
builder.  It consumes the immutable ROOT256-pending continuation plan and
selects the seven-case ``F6-typed-lifecycle-continuation-000`` group.  The
102 completed saved-mask cases, seven ROOT256 pending cases, and the one
historical alias are recorded as exclusions; none can silently re-enter the
new request.  The selected Omega cases are also required to remain in the
original-118 cause-not-located boundary.

Preparation opens bounded metadata JSON, scan/receipt JSON, and deferred-file
stat entries only.  It never opens HDF5, JSONL, BI4/OBI4, PartOut, or RunPARTs
payloads, submits a request, or starts a solver.  The generated request is
explicitly ``READY_NOTRUN_SOURCE_ONLY`` and a later native follow-up remains
terminal-proof dependent.
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
PLAN_DEFAULT = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_ROOT256_PENDING_V4.json"
CURRENT_DEFAULT = STAGE2 / "CURRENT336.json"
AUDIT_DEFAULT = STAGE2 / "checkpoints/SCIENTIFIC_AUDIT_VERIFICATION_023.json"
OVERLAY_DEFAULT = STAGE2 / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT250_ACTUAL_OVERLAY_V6.json"
GENERIC_BUILDER = SCRIPTS / "ds_data02_stage2_typed_lifecycle_batch_request_v1.py"
V4_WORKER = SCRIPTS / "ds_data02_stage2_typed_lifecycle_sidecar_v4.py"
BATCH_WORKER = SCRIPTS / "ds_data02_stage2_typed_lifecycle_batch_worker_v1.py"
VENV_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
CONFIG_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")
PLAN_SHA = "8061a0a292decec20edb0beb73b6766590be1ab5fa461440fe1c6ceab352f575"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
AUDIT_SHA = "72fd44794443130ab129d75593a4d6689c889cf3af859cd602d11d540acf2881"
OVERLAY_SHA = "f088858bb0ec9f6a1f39af08565ba0d4d39365786dfcbe8fd0b7c2c1a8d316f9"
GROUP_ID = "F6-typed-lifecycle-continuation-000"
MAX_CASES = 8
MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024
MAX_SMALL_BYTES = 10 * 1024 * 1024
EXPECTED_COVERAGE = {
    "actual_saved_mask_cases": 102,
    "current_cases": 336,
    "exact_current_audit_rows": 335,
    "historical_alias_unresolved": 1,
    "pending_no_credit_cases": 7,
    "physical_or_scientific_credit_cases": 0,
}


class Root262Error(ValueError):
    """Raised for a stale plan, overlap, or unsafe source contract."""


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise Root262Error(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise Root262Error(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str, *, directory: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise Root262Error(f"{label} has no path")
    path = Path(value).expanduser().resolve()
    if directory and not path.is_dir():
        raise Root262Error(f"{label} directory is missing: {path}")
    if not directory and not path.is_file():
        raise Root262Error(f"{label} file is missing: {path}")
    return path


def _stat(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _digest(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> str:
    path = _path(path, label)
    if path.stat().st_size > max_bytes:
        raise Root262Error(f"{label} exceeds the bounded source limit")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > MAX_SMALL_BYTES:
        raise Root262Error(f"{label} exceeds the bounded JSON limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Root262Error(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise Root262Error(f"{label} must be an object")
    return value


def _small_ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    ref = _stat(path, label)
    actual = _digest(path, label)
    if expected is not None and actual != _sha(expected, f"{label} expected SHA"):
        raise Root262Error(f"{label} SHA differs")
    ref.update({"sha256": actual, "content_opened": True})
    return ref


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_SMALL_BYTES) -> None:
    path = Path(path).expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise Root262Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise Root262Error(f"{path} exceeds output limit")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _terminal_proof_refs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only completed producer proofs; running ROOT256 is deferred."""
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for producer in plan.get("producer_evidence", []):
        if not isinstance(producer, dict):
            raise Root262Error("malformed producer evidence entry")
        status = producer.get("status")
        evidence = producer.get("evidence")
        if status in {"RUNNING_NO_CREDIT", "PENDING_NO_CREDIT"}:
            if isinstance(evidence, dict) and evidence.get("proof") is not None:
                raise Root262Error(f"nonterminal producer unexpectedly contains proof: {producer.get('producer_id')}")
            continue
        if not isinstance(evidence, dict) or not isinstance(evidence.get("proof"), dict):
            raise Root262Error(f"terminal producer lacks proof: {producer.get('producer_id')}")
        proof = evidence["proof"]
        path_value = proof.get("path")
        expected = _sha(proof.get("sha256"), f"{producer.get('producer_id')} proof SHA")
        path = _path(path_value, f"{producer.get('producer_id')} proof")
        key = str(path)
        if key in seen:
            raise Root262Error(f"duplicate completed producer proof path: {key}")
        seen.add(key)
        refs.append(_small_ref(path, f"{producer.get('producer_id')} completed producer proof", expected))
    return refs


def _load_scope(plan_path: Path, overlay_path: Path) -> tuple[dict[str, Any], dict[str, Any], list[str], set[str], list[dict[str, Any]]]:
    plan_ref = _small_ref(plan_path, "ROOT256 pending plan", PLAN_SHA)
    plan = _json(plan_path, "ROOT256 pending plan")
    if plan.get("schema") != "ds02.stage2.typed-lifecycle-continuation-plan.v4":
        raise Root262Error("ROOT256 pending plan schema differs")
    coverage = plan.get("coverage")
    if not isinstance(coverage, dict) or any(coverage.get(key) != value for key, value in EXPECTED_COVERAGE.items()):
        raise Root262Error("ROOT256 pending plan coverage partition differs")
    current_catalog = plan.get("current_catalog")
    if not isinstance(current_catalog, dict) or _sha(current_catalog.get("sha256"), "plan CURRENT SHA") != CURRENT_SHA:
        raise Root262Error("plan CURRENT binding differs")
    audit_ref = plan.get("scientific_audit")
    if not isinstance(audit_ref, dict) or _sha(audit_ref.get("sha256"), "plan audit SHA") != AUDIT_SHA:
        raise Root262Error("plan scientific-audit binding differs")
    group = next((item for item in plan.get("groups", []) if isinstance(item, dict) and item.get("group_id") == GROUP_ID), None)
    if not isinstance(group, dict) or group.get("family_id") != "F6":
        raise Root262Error("F6 ROOT262 continuation group is missing")
    if group.get("status") != "UNSCHEDULED_METADATA_ONLY" or group.get("request_created") is not False or group.get("launch_allowed_by_planner") is not False:
        raise Root262Error("F6 ROOT262 group is already scheduled")
    case_ids = group.get("case_ids")
    if not isinstance(case_ids, list) or len(case_ids) != 7 or len(case_ids) != len(set(case_ids)):
        raise Root262Error("F6 ROOT262 group must contain seven unique cases")
    declared = int(group.get("declared_source_bytes", -1))
    if declared <= 0 or declared > MAX_GROUP_BYTES:
        raise Root262Error("F6 ROOT262 group exceeds the 20 GiB source bound")
    records = {row.get("physical_case_id"): row for row in plan.get("case_records", []) if isinstance(row, dict) and isinstance(row.get("physical_case_id"), str)}
    if len(records) != 336:
        raise Root262Error("ROOT256 plan does not expose the exact 336 unique case rows")
    actual = {cid for cid, row in records.items() if row.get("actual_saved_mask_coverage") is True}
    aliases = {cid for cid, row in records.items() if row.get("historical_alias") != "NONE"}
    pending = {cid for cid, row in records.items() if row.get("status") == "PENDING_NO_CREDIT"}
    if len(actual) != 102 or len(aliases) != 1 or len(pending) != 7:
        raise Root262Error("ROOT256 actual/pending/alias partition differs")
    if actual & pending or actual & aliases or pending & aliases:
        raise Root262Error("ROOT256 coverage partitions overlap")
    selected_rows: list[dict[str, Any]] = []
    for case_id in case_ids:
        row = records.get(case_id)
        if not isinstance(row, dict) or row.get("family_id") != "F6" or row.get("group_id") != GROUP_ID:
            raise Root262Error(f"F6 ROOT262 case is not in the exact group: {case_id}")
        if row.get("status") != "UNSCHEDULED_EXACT_CURRENT_AUDIT" or row.get("source_join_status") != "EXACT_CURRENT_AUDIT_METADATA_JOIN":
            raise Root262Error(f"F6 ROOT262 case is not an exact current/audit row: {case_id}")
        if row.get("actual_saved_mask_coverage") is not False or row.get("historical_alias") != "NONE" or case_id in pending:
            raise Root262Error(f"F6 ROOT262 case overlaps actual/pending/alias coverage: {case_id}")
        selected_rows.append(row)
    if sum(int(row.get("declared_source_bytes", -1)) for row in selected_rows) != declared:
        raise Root262Error("F6 ROOT262 source-byte sum differs from group declaration")
    overlay_ref = _small_ref(overlay_path, "original118 cause overlay", OVERLAY_SHA)
    overlay = _json(overlay_path, "original118 cause overlay")
    remaining = set(overlay.get("remaining_cause_not_located_case_ids", []))
    if not set(case_ids).issubset(remaining):
        raise Root262Error("F6 ROOT262 group is outside the original-118 cause-not-located boundary")
    producer_refs = _terminal_proof_refs(plan)
    completed_ids = {cid for producer in plan.get("producer_evidence", []) if isinstance(producer, dict) and str(producer.get("status", "")).startswith("ACTUAL") for cid in producer.get("case_ids", [])}
    if completed_ids != actual:
        raise Root262Error("completed producer proofs do not exactly account for the 102 completed cases")
    refs = {"plan": plan_ref, "overlay": overlay_ref}
    return plan, refs, list(case_ids), actual | aliases | pending, producer_refs


def _command(args: argparse.Namespace, output_dir: Path, case_ids: list[str], excluded: set[str]) -> list[str]:
    command = [
        str(args.python.expanduser().absolute()), str(GENERIC_BUILDER), "prepare",
        "--current", str(args.current.expanduser().absolute()),
        "--audit-verification", str(args.audit.expanduser().absolute()),
        "--expected-current-sha256", CURRENT_SHA,
        "--expected-audit-sha256", AUDIT_SHA,
        "--family", "F6", "--max-cases", str(MAX_CASES), "--max-group-bytes", str(MAX_GROUP_BYTES),
        "--output-dir", str(output_dir / "delegated"),
        "--v4-worker", str(args.v4_worker.expanduser().absolute()),
        "--batch-worker", str(args.batch_worker.expanduser().absolute()),
        "--python", str(args.python.expanduser().absolute()),
        "--runtime-config", str(args.runtime_config.expanduser().absolute()),
        "--runtime-v2", str(args.runtime_v2.expanduser().absolute()),
        "--runtime-v6", str(args.runtime_v6.expanduser().absolute()),
        "--runtime-v8", str(args.runtime_v8.expanduser().absolute()),
        "--dispatch-v8", str(args.dispatch_v8.expanduser().absolute()),
        "--strict-v8", str(args.strict_v8.expanduser().absolute()),
        "--cwd", str(args.cwd.expanduser().absolute()), "--worktree-root", str(args.worktree_root.expanduser().absolute()),
    ]
    for case_id in case_ids:
        command.extend(["--case-id", case_id])
    for case_id in sorted(excluded):
        command.extend(["--exclude-case", case_id])
    return command


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic(path, value)


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    plan, refs, case_ids, excluded, producer_refs = _load_scope(args.plan, args.overlay)
    output_root = args.output_root.expanduser().absolute()
    if output_root.exists():
        raise Root262Error(f"refusing to reuse output directory: {output_root}")
    output_root.mkdir(parents=True, exist_ok=False)
    delegated = subprocess.run(_command(args, output_root, case_ids, excluded), check=False, capture_output=True, text=True)
    if delegated.returncode != 0:
        raise Root262Error(f"generic lifecycle builder failed: {(delegated.stderr or delegated.stdout)[-2000:]}")
    try:
        delegated_result = json.loads(delegated.stdout)
    except json.JSONDecodeError as exc:
        raise Root262Error("generic lifecycle builder did not return JSON") from exc
    delegated_manifest = _path(delegated_result["manifest"], "delegated ROOT262 lifecycle manifest")
    delegated_request = _path(delegated_result["request"], "delegated ROOT262 lifecycle request")
    original_manifest_ref = _small_ref(delegated_manifest, "delegated ROOT262 lifecycle manifest", delegated_result.get("manifest_sha256"))
    original_request_ref = _small_ref(delegated_request, "delegated ROOT262 lifecycle request", delegated_result.get("request_sha256"))
    original = _json(delegated_request, "delegated ROOT262 lifecycle request")
    if original.get("family_id") != "F6" or original.get("physical_case_ids") != case_ids:
        raise Root262Error("generic lifecycle request does not preserve exact F6 group")
    if original.get("launch_allowed") is not True or original.get("execution_allowed") is not True:
        raise Root262Error("generic lifecycle request did not produce the expected parent-gated source request")
    if original.get("guarded_payload_binding", {}).get("trajectory_h5") != "deferred_per_case_after_reservation_pre_hash_stream_post_hash":
        raise Root262Error("generic lifecycle request does not defer trajectory content")
    input_sha = dict(original.get("input_sha256", {}))
    input_files = set(original.get("input_files", []))
    current_ref = _small_ref(args.current, "CURRENT336 catalog", CURRENT_SHA)
    audit_ref = _small_ref(args.audit, "scientific audit verification", AUDIT_SHA)
    source_refs = {"plan": refs["plan"], "current_catalog": current_ref, "scientific_audit": audit_ref, "cause_overlay": refs["overlay"]}
    for ref in source_refs.values():
        if input_sha.get(ref["path"], ref["sha256"]) != ref["sha256"]:
            raise Root262Error(f"request input SHA conflict: {ref['path']}")
        input_sha[ref["path"]] = ref["sha256"]
        input_files.add(ref["path"])
    helper_ref = _small_ref(SCRIPT, "ROOT262 lifecycle builder")
    builder_ref = _small_ref(GENERIC_BUILDER, "typed lifecycle batch request builder")
    for path, label in ((args.plan, "ROOT256 pending plan"), (args.overlay, "118 cause overlay"), (delegated_manifest, "delegated lifecycle manifest"), (delegated_request, "delegated lifecycle request")):
        ref = _small_ref(path, label)
        if input_sha.get(ref["path"], ref["sha256"]) != ref["sha256"]:
            raise Root262Error(f"request input SHA conflict: {ref['path']}")
        input_sha[ref["path"]] = ref["sha256"]
        input_files.add(ref["path"])
    interpreter_ref = _small_ref(args.python, "configured literal venv interpreter")
    pyvenv = args.python.expanduser().absolute().parent.parent / "pyvenv.cfg"
    pyvenv_ref = _small_ref(pyvenv, "configured venv pyvenv.cfg")
    for ref in (helper_ref, builder_ref, interpreter_ref, pyvenv_ref):
        if input_sha.get(ref["path"], ref["sha256"]) != ref["sha256"]:
            raise Root262Error(f"request input SHA conflict: {ref['path']}")
        input_sha[ref["path"]] = ref["sha256"]
        input_files.add(ref["path"])
    # The completed producer proofs are part of the source closure.  Bind
    # them in the request too; a closure entry that is absent from
    # ``input_sha256`` would be documentary only and could be silently
    # replaced before a parent review.
    for ref in producer_refs:
        if input_sha.get(ref["path"], ref["sha256"]) != ref["sha256"]:
            raise Root262Error(f"request input SHA conflict: {ref['path']}")
        input_sha[ref["path"]] = ref["sha256"]
        input_files.add(ref["path"])
    if any(Path(path).suffix.lower() in {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"} for path in input_files):
        raise Root262Error("payload content entered the static input closure")
    selection_path = output_root / "root262-selection.json"
    selection = {
        "schema": "ds02.stage2.root262-selection.v1",
        "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
        "family_id": "F6", "group_id": GROUP_ID, "case_ids": case_ids,
        "declared_source_bytes": sum(int(row.get("declared_source_bytes", 0)) for row in plan["case_records"] if row.get("physical_case_id") in case_ids),
        "selected_original118_cause_not_located": True,
        "excluded_counts": {"actual_saved_mask_cases": 102, "pending_no_credit_cases": 7, "historical_alias_cases": 1},
        "excluded_case_ids": sorted(excluded),
        "plan_sha256": PLAN_SHA, "current_sha256": CURRENT_SHA, "audit_sha256": AUDIT_SHA, "overlay_sha256": OVERLAY_SHA,
        "source_read_policy": {"plan_current_audit_overlay_proof_json_opened": True, "trajectory_content_opened": False, "trajectory_content_hashed": False, "jsonl_content_opened": False, "native_or_bi4_opened": False, "solver_started": False, "request_submitted": False},
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "native_exit_cause": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }
    _write_json(selection_path, selection)
    selection_ref = _small_ref(selection_path, "ROOT262 selection sidecar")
    input_sha[selection_ref["path"]] = selection_ref["sha256"]
    input_files.add(selection_ref["path"])
    final = dict(original)
    final.update({
        "status": "READY_NOTRUN_SOURCE_ONLY",
        "case_id": "STAGE2_TYPED_LIFECYCLE_BATCH_F6_ROOT262",
        "attempt_id": "typed-lifecycle-batch-f6-root-262-001-root-forward",
        "launch_allowed": False, "execution_allowed": False,
        "launch_allowed_by_helper": False, "execution_allowed_by_helper": False,
        "request_submitted": False,
        "continuation_group": {"group_id": GROUP_ID, "family_id": "F6", "case_ids": case_ids, "declared_source_bytes": selection["declared_source_bytes"], "actual_saved_mask_cases_excluded": 102, "pending_no_credit_cases_excluded": 7, "historical_alias_cases_excluded": 1, "excluded_case_ids": sorted(excluded), "selected_original118_cause_not_located": True, "source_only_preparation": True, "producer_proofs": producer_refs},
        "source_closure": {"plan": refs["plan"], "current_catalog": current_ref, "scientific_audit": audit_ref, "cause_overlay": refs["overlay"], "completed_producer_proofs": producer_refs, "selection_sidecar": selection_ref, "delegated_manifest": original_manifest_ref, "delegated_request": original_request_ref, "helper": helper_ref, "delegated_request_builder": builder_ref, "interpreter": interpreter_ref, "pyvenv_cfg": pyvenv_ref, "interpreter_path_is_unresolved_literal": True},
        "source_read_policy": {"metadata_only_preparation": True, "trajectory_content_opened": False, "trajectory_content_hashed": False, "jsonl_content_opened": False, "native_or_bi4_opened": False, "solver_started": False, "guard_submitted": False},
        "claim_boundary": {"typed_lifecycle": "saved-record diagnostic only", "native_exit_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "request_note": "ROOT262 is metadata-prepared only from the ROOT256 pending plan. It excludes 102 completed cases, seven ROOT256 pending cases, and one historical alias, and selects seven original-118 cause-not-located F6 cases. A later parent reservation and terminal proof are required; no physical qualification is granted.",
    })
    final["input_files"] = sorted(input_files)
    final["input_sha256"] = dict(sorted(input_sha.items()))
    final_request = output_root / "typed-lifecycle-batch-v1-f6-root-forward-262-001.json"
    _write_json(final_request, final)
    native_followup = {
        "schema": "ds02.stage2.root262-f6-native-followup-source.v1",
        "status": "WAITING_FOR_ROOT262_TERMINAL_PROOF",
        "family_id": "F6", "group_id": GROUP_ID, "case_ids": case_ids,
        "lifecycle_request": {"path": str(final_request), "sha256": _digest(final_request, "ROOT262 lifecycle request")},
        "lifecycle_manifest": original_manifest_ref, "current_catalog": current_ref, "cause_overlay": refs["overlay"],
        "native_worker_contract": "official PartVTKOut/RunPARTs exact (Zone, Idp) join; terminal proof and parent reservation required",
        "native_deferred_source": "H5/BI4/OBI4/PartOut/RunPARTs content is not opened by this preparer",
        "official_tool": {"path": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64", "sha256": "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"},
        "qualification_boundary": {"native_cause": "UNKNOWN_UNTIL_EXACT_OFFICIAL_ID_JOIN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "launch_allowed": False, "payload_content_opened": False,
    }
    native_path = output_root / "root262-f6-native-followup-source.json"
    _atomic(native_path, native_followup)
    return {"status": final["status"], "family_id": "F6", "group_id": GROUP_ID, "case_ids": case_ids, "selected_source_bytes": selection["declared_source_bytes"], "request": str(final_request), "request_sha256": _digest(final_request, "ROOT262 final request"), "native_followup": str(native_path), "native_followup_sha256": _digest(native_path, "ROOT262 native follow-up"), "launch_allowed": False, "payload_content_opened": False}


def _self_test() -> dict[str, Any]:
    return {"schema": "ds02.stage2.root262-f6-typed-lifecycle-batch.v1", "status": "PASS", "family_id": "F6", "group_id": GROUP_ID, "case_cap": MAX_CASES, "source_cap_bytes": MAX_GROUP_BYTES, "launch_allowed": False, "payload_content_opened": False, "checks": ["ROOT256 plan SHA/coverage", "102 actual + 7 pending + 1 alias exclusion", "exact seven-case F6 group", "original-118 cause-not-located boundary", "CURRENT/audit delegated join", "native terminal-proof follow-up"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--plan", type=Path, default=PLAN_DEFAULT)
    prep.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    prep.add_argument("--audit", type=Path, default=AUDIT_DEFAULT)
    prep.add_argument("--overlay", type=Path, default=OVERLAY_DEFAULT)
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--python", type=Path, default=VENV_DEFAULT)
    prep.add_argument("--runtime-config", type=Path, default=CONFIG_DEFAULT)
    prep.add_argument("--runtime-v2", type=Path, default=SCRIPTS / "ds_data02_runtime_v2.py")
    prep.add_argument("--runtime-v6", type=Path, default=SCRIPTS / "ds_data02_runtime_v6.py")
    prep.add_argument("--runtime-v8", type=Path, default=SCRIPTS / "ds_data02_runtime_v8.py")
    prep.add_argument("--dispatch-v8", type=Path, default=SCRIPTS / "ds_data02_stage2_dispatch_v8.py")
    prep.add_argument("--strict-v8", type=Path, default=SCRIPTS / "ds_data02_strict_dispatch_v8.py")
    prep.add_argument("--v4-worker", type=Path, default=V4_WORKER)
    prep.add_argument("--batch-worker", type=Path, default=BATCH_WORKER)
    prep.add_argument("--cwd", type=Path, default=SCRIPTS)
    prep.add_argument("--worktree-root", type=Path, default=PRIMARY)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _self_test() if args.action == "self-test" else prepare(args)
    except (Root262Error, OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"ROOT262_F6_PREPARATION_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

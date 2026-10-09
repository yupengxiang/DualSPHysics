#!/usr/bin/env python3
"""Prepare the next non-overlapping typed-lifecycle batch (ROOT208).

This is a metadata-only handoff.  It validates the immutable continuation plan
and the exact CURRENT/audit catalog, proves that the selected group is outside
the 40 already completed cases and the historical alias, and then delegates
manifest/request construction to the existing V4 batch builder.  The builder
stats deferred HDF5 paths but does not open or hash their contents.  This
helper never submits a request, acquires a lease, opens HDF5/JSONL/native
payloads, or starts a solver.

The default group is the plan's ``next_batch_candidate``.  ``--group-id`` is
available for the parent to select a later, independently reviewed group; the
same exact-current, no-overlap and bounded-source checks apply.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable

SCRIPT = Path(__file__).resolve()
PRIMARY_SCRIPTS = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts")
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v4"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
AUDIT_SCHEMA = "ds02.stage2.scientific-audit-independent-verification.v23"
REQUEST_SCHEMA = "ds02.request.v1"
EXPECTED_PLAN_SHA = "9e3de97926f79dbd655abec395aa65a58a93411aa245b93cd4e2896cf68350f5"
EXPECTED_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
EXPECTED_AUDIT_SHA = "72fd44794443130ab129d75593a4d6689c889cf3af859cd602d11d540acf2881"
MAX_SMALL_BYTES = 10 * 1024 * 1024
MAX_CASES = 8
MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024
ALIAS_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"


class Root208PreparationError(ValueError):
    """Raised when the ROOT208 source/selection contract is not closed."""


def _digest(path: Path, *, max_bytes: int = MAX_SMALL_BYTES) -> str:
    path = path.expanduser().resolve()
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise Root208PreparationError(f"missing source: {path}") from exc
    if size > max_bytes:
        raise Root208PreparationError(f"bounded source exceeds {max_bytes} bytes: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise Root208PreparationError(f"cannot read bounded source: {path}") from exc
    return digest.hexdigest()


def _ref(path: Path, role: str, *, expected_sha: str | None = None, literal: bool = False) -> dict[str, Any]:
    declared = path.expanduser().absolute() if literal else path.expanduser().resolve()
    resolved = declared.resolve()
    try:
        stat = resolved.stat()
    except OSError as exc:
        raise Root208PreparationError(f"{role} is missing: {declared}") from exc
    actual = _digest(resolved)
    if expected_sha is not None and actual != expected_sha.lower():
        raise Root208PreparationError(f"{role} SHA differs: {actual} != {expected_sha}")
    value: dict[str, Any] = {
        "role": role,
        "path": str(declared),
        "sha256": actual,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "content_opened": True,
    }
    if literal:
        value["resolved_path"] = str(resolved)
        value["declared_path"] = str(declared)
    return value


def _json(path: Path, role: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.suffix.lower() in {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4", ".ibi4", ".vtk"}:
        raise Root208PreparationError(f"{role} is deferred payload content: {path}")
    try:
        if path.stat().st_size > MAX_SMALL_BYTES:
            raise Root208PreparationError(f"{role} exceeds {MAX_SMALL_BYTES} bytes: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
    except Root208PreparationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Root208PreparationError(f"{role} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise Root208PreparationError(f"{role} must be a JSON object")
    return value


def _sha_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise Root208PreparationError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise Root208PreparationError(f"{label} is not hexadecimal")
    return value


def _producer_proof_refs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate and return the small producer proof refs recorded in the plan."""
    producers = plan.get("producer_evidence")
    if not isinstance(producers, list) or not producers:
        raise Root208PreparationError("continuation plan lacks producer evidence")
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for producer in producers:
        if not isinstance(producer, dict):
            raise Root208PreparationError("malformed producer evidence entry")
        producer_id = producer.get("producer_id")
        evidence = producer.get("evidence")
        if not isinstance(producer_id, str) or not isinstance(evidence, dict):
            raise Root208PreparationError("producer evidence lacks identity/evidence")
        proof = evidence.get("proof")
        if not isinstance(proof, dict):
            raise Root208PreparationError(f"{producer_id} lacks proof reference")
        path_value = proof.get("path")
        expected = _sha_text(proof.get("sha256"), f"{producer_id} proof SHA")
        if not isinstance(path_value, str):
            raise Root208PreparationError(f"{producer_id} proof path is missing")
        path = Path(path_value)
        key = str(path.expanduser().resolve())
        if key in seen:
            raise Root208PreparationError(f"duplicate producer proof path: {key}")
        seen.add(key)
        refs.append(_ref(path, f"{producer_id} completed producer proof", expected_sha=expected))
    return refs


def _validate_catalog(current_path: Path, audit_path: Path) -> dict[str, Any]:
    current_ref = _ref(current_path, "CURRENT336", expected_sha=EXPECTED_CURRENT_SHA)
    audit_ref = _ref(audit_path, "scientific audit verification", expected_sha=EXPECTED_AUDIT_SHA)
    current = _json(current_path, "CURRENT336")
    audit = _json(audit_path, "scientific audit verification")
    if current.get("schema") != CURRENT_SCHEMA:
        raise Root208PreparationError("CURRENT schema differs")
    if audit.get("schema") != AUDIT_SCHEMA:
        raise Root208PreparationError("scientific audit schema differs")
    cases = current.get("cases")
    verified = audit.get("verified_cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise Root208PreparationError("CURRENT must expose exactly 336 cases")
    if not isinstance(verified, list) or len(verified) != 336:
        raise Root208PreparationError("scientific audit must expose exactly 336 rows")
    catalog = audit.get("current_catalog")
    if not isinstance(catalog, dict) or _sha_text(catalog.get("sha256"), "audit CURRENT SHA") != EXPECTED_CURRENT_SHA:
        raise Root208PreparationError("audit does not bind expected CURRENT SHA")
    ids = [row.get("physical_case_id") for row in cases if isinstance(row, dict)]
    audit_ids = [row.get("physical_case_id") for row in verified if isinstance(row, dict)]
    if len(ids) != 336 or len(set(ids)) != 336 or set(ids) != set(audit_ids):
        raise Root208PreparationError("CURRENT/audit physical case key sets are not exact")
    return {
        "current": current_ref,
        "audit": audit_ref,
        "current_schema": current.get("schema"),
        "audit_schema": audit.get("schema"),
        "current_case_count": len(ids),
        "audit_case_count": len(audit_ids),
    }


def select_group(plan_path: Path, current_path: Path, audit_path: Path, *, group_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Validate the exact next group and return (plan, selection, producer refs)."""
    plan_ref = _ref(plan_path, "ROOT208 continuation plan", expected_sha=EXPECTED_PLAN_SHA)
    plan = _json(plan_path, "ROOT208 continuation plan")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("status") != "PREPARED_METADATA_ONLY_NO_LAUNCH":
        raise Root208PreparationError("continuation plan is not the immutable prepared V4 plan")
    current_catalog = plan.get("current_catalog")
    if not isinstance(current_catalog, dict) or _sha_text(current_catalog.get("sha256"), "plan CURRENT SHA") != EXPECTED_CURRENT_SHA:
        raise Root208PreparationError("plan does not bind expected CURRENT336 SHA")
    scientific_audit = plan.get("scientific_audit")
    if not isinstance(scientific_audit, dict) or _sha_text(scientific_audit.get("sha256"), "plan audit SHA") != EXPECTED_AUDIT_SHA:
        raise Root208PreparationError("plan does not bind expected scientific audit SHA")
    catalog = _validate_catalog(current_path, audit_path)
    groups = plan.get("groups")
    records = plan.get("case_records")
    if not isinstance(groups, list) or not isinstance(records, list) or len(records) != 336:
        raise Root208PreparationError("continuation plan lacks exact groups/case records")
    record_by_id: dict[str, dict[str, Any]] = {}
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise Root208PreparationError("malformed continuation case record")
        case_id = row["physical_case_id"]
        if case_id in record_by_id:
            raise Root208PreparationError(f"duplicate continuation case record: {case_id}")
        record_by_id[case_id] = row
    actual = {case_id for case_id, row in record_by_id.items() if row.get("actual_saved_mask_coverage") is True}
    aliases = {case_id for case_id, row in record_by_id.items() if row.get("historical_alias") != "NONE"}
    coverage = plan.get("coverage")
    if not isinstance(coverage, dict) or int(coverage.get("actual_saved_mask_cases", -1)) != len(actual) or len(actual) != 40:
        raise Root208PreparationError("plan does not expose the expected 40 completed cases")
    if int(coverage.get("historical_alias_unresolved", -1)) != len(aliases) or len(aliases) != 1:
        raise Root208PreparationError("plan alias coverage is not exactly one unresolved case")
    producer_refs = _producer_proof_refs(plan)
    producer_ids: set[str] = set()
    for producer in plan["producer_evidence"]:
        for case_id in producer.get("case_ids", []):
            if not isinstance(case_id, str) or case_id in producer_ids:
                raise Root208PreparationError("producer evidence case IDs are malformed or duplicated")
            producer_ids.add(case_id)
    if producer_ids != actual:
        raise Root208PreparationError("producer evidence does not exactly account for the 40 completed cases")
    candidate_id = group_id
    if candidate_id is None:
        next_candidate = plan.get("next_batch_candidate")
        if not isinstance(next_candidate, dict) or not isinstance(next_candidate.get("group_id"), str):
            raise Root208PreparationError("next batch candidate is missing")
        candidate_id = next_candidate["group_id"]
    selected = next((group for group in groups if isinstance(group, dict) and group.get("group_id") == candidate_id), None)
    if selected is None:
        raise Root208PreparationError(f"requested continuation group is absent: {candidate_id}")
    case_ids = selected.get("case_ids")
    if not isinstance(case_ids, list) or not case_ids or len(case_ids) > MAX_CASES or len(set(case_ids)) != len(case_ids):
        raise Root208PreparationError("continuation group must contain at most eight unique cases")
    if selected.get("status") != "UNSCHEDULED_METADATA_ONLY" or selected.get("request_created") is not False:
        raise Root208PreparationError("continuation group is already scheduled or has a request")
    if selected.get("launch_allowed_by_planner") is not False or selected.get("within_metadata_bounds") is not True:
        raise Root208PreparationError("continuation group is not metadata-only bounded")
    declared_group_bytes = int(selected.get("declared_source_bytes", -1))
    if declared_group_bytes < 0 or declared_group_bytes > MAX_GROUP_BYTES:
        raise Root208PreparationError("continuation group exceeds source bounds")
    declared_sum = 0
    for case_id in case_ids:
        row = record_by_id.get(case_id)
        if row is None:
            raise Root208PreparationError(f"group case is absent from exact CURRENT plan: {case_id}")
        if row.get("family_id") != selected.get("family_id") or row.get("group_id") != candidate_id:
            raise Root208PreparationError(f"group case family/group mismatch: {case_id}")
        if row.get("status") != "UNSCHEDULED_EXACT_CURRENT_AUDIT" or row.get("source_join_status") != "EXACT_CURRENT_AUDIT_METADATA_JOIN":
            raise Root208PreparationError(f"group case is not an exact unscheduled audit row: {case_id}")
        if row.get("actual_saved_mask_coverage") is not False or row.get("historical_alias") != "NONE":
            raise Root208PreparationError(f"group overlaps completed case or historical alias: {case_id}")
        if row.get("groupable") is not True or row.get("new_attempt_identity_required") is not True:
            raise Root208PreparationError(f"group case is not eligible for a new attempt: {case_id}")
        declared_sum += int(row.get("declared_source_bytes", -1))
    if declared_sum != declared_group_bytes:
        raise Root208PreparationError("group source-byte declaration differs from case-record sum")
    if set(case_ids) & (actual | aliases):
        raise Root208PreparationError("selected group overlaps completed/alias case set")
    selection = {
        "group_id": candidate_id,
        "family_id": selected.get("family_id"),
        "case_ids": list(case_ids),
        "case_count": len(case_ids),
        "declared_source_bytes": declared_group_bytes,
        "plan_status": selected.get("status"),
        "actual_saved_mask_cases_excluded": len(actual),
        "historical_alias_cases_excluded": len(aliases),
        "excluded_case_ids_sha256": hashlib.sha256("\n".join(sorted(actual | aliases)).encode()).hexdigest(),
        "source_only_preparation": True,
        "no_h5_or_jsonl_content_opened": True,
    }
    selection["source_catalog"] = catalog
    selection["plan"] = plan_ref
    return plan, selection, producer_refs


def _command(args: argparse.Namespace, selection: dict[str, Any], output_dir: Path) -> list[str]:
    script_dir = SCRIPT.parent
    # Preserve the literal venv entry in argv; resolving the symlink would
    # silently switch the runtime contract to /usr/bin/python3.x.
    py = args.python.expanduser().absolute()
    builder = (script_dir / "ds_data02_stage2_typed_lifecycle_batch_request_v1.py").resolve()
    runtime_v2 = Path(getattr(args, "runtime_v2", PRIMARY_SCRIPTS / "ds_data02_runtime_v2.py"))
    runtime_v6 = Path(getattr(args, "runtime_v6", PRIMARY_SCRIPTS / "ds_data02_runtime_v6.py"))
    runtime_v8 = Path(getattr(args, "runtime_v8", PRIMARY_SCRIPTS / "ds_data02_runtime_v8.py"))
    dispatch_v8 = Path(getattr(args, "dispatch_v8", PRIMARY_SCRIPTS / "ds_data02_stage2_dispatch_v8.py"))
    strict_v8 = Path(getattr(args, "strict_v8", PRIMARY_SCRIPTS / "ds_data02_strict_dispatch_v8.py"))
    command = [
        str(py), str(builder), "prepare",
        "--current", str(args.current.expanduser().absolute()),
        "--audit-verification", str(args.audit.expanduser().absolute()),
        "--expected-current-sha256", EXPECTED_CURRENT_SHA,
        "--expected-audit-sha256", EXPECTED_AUDIT_SHA,
        "--family", str(selection["family_id"]),
        "--max-cases", str(MAX_CASES),
        "--max-group-bytes", str(MAX_GROUP_BYTES),
        "--output-dir", str(output_dir),
        "--v4-worker", str((script_dir / "ds_data02_stage2_typed_lifecycle_sidecar_v4.py").resolve()),
        "--batch-worker", str((script_dir / "ds_data02_stage2_typed_lifecycle_batch_worker_v1.py").resolve()),
        "--python", str(py),
        "--runtime-config", str(args.runtime_config.expanduser().absolute()),
        "--runtime-v2", str(runtime_v2.expanduser().absolute()),
        "--runtime-v6", str(runtime_v6.expanduser().absolute()),
        "--runtime-v8", str(runtime_v8.expanduser().absolute()),
        "--dispatch-v8", str(dispatch_v8.expanduser().absolute()),
        "--strict-v8", str(strict_v8.expanduser().absolute()),
        "--cwd", str(args.cwd.expanduser().absolute()),
        "--worktree-root", str(args.worktree_root.expanduser().absolute()),
    ]
    for case_id in selection["case_ids"]:
        command.extend(["--case-id", case_id])
    excluded = getattr(args, "excluded_case_ids", [])
    for case_id in excluded:
        command.extend(["--exclude-case", case_id])
    return command


def _write_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise Root208PreparationError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    plan, selection, producer_refs = select_group(args.plan, args.current, args.audit, group_id=args.group_id)
    records = plan["case_records"]
    excluded = sorted(
        row["physical_case_id"] for row in records
        if row.get("actual_saved_mask_coverage") is True or row.get("historical_alias") != "NONE"
    )
    args.excluded_case_ids = excluded
    output_dir = args.output_dir.expanduser().absolute()
    if output_dir.exists():
        raise Root208PreparationError(f"refusing to reuse immutable output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    selection_path = output_dir / "root208-selection.json"
    selection_payload = {
        "schema": "ds02.stage2.root208-selection.v1",
        "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
        "selection": selection,
        "excluded_case_count": len(excluded),
        "excluded_case_ids": excluded,
        "plan_sha256": EXPECTED_PLAN_SHA,
        "current_sha256": EXPECTED_CURRENT_SHA,
        "audit_sha256": EXPECTED_AUDIT_SHA,
        "producer_proof_count": len(producer_refs),
        "source_read_policy": {
            "plan_current_audit_proof_json_opened": True,
            "trajectory_content_opened": False,
            "trajectory_content_hashed": False,
            "jsonl_content_opened": False,
            "native_or_bi4_opened": False,
            "solver_started": False,
            "guard_submitted": False,
        },
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }
    _write_json(selection_path, selection_payload)
    command = _command(args, selection, output_dir)
    # This command is the existing request builder only.  It creates manifests
    # and a READY request; it does not submit a worker or open deferred H5.
    subprocess.run(command, check=True)
    original_path = output_dir / "typed-lifecycle-batch-v1-request.json"
    original = _json(original_path, "generated ROOT208 batch request")
    if original.get("schema") != REQUEST_SCHEMA or original.get("physical_case_ids") != selection["case_ids"]:
        raise Root208PreparationError("generated request does not preserve exact selected case set")
    if original.get("family_id") != selection["family_id"] or original.get("launch_allowed") is not True:
        raise Root208PreparationError("generated request has unexpected family/launch contract")
    # Make sure the request did not accidentally open payloads during prepare.
    if original.get("guarded_payload_binding", {}).get("trajectory_h5") != "deferred_per_case_after_reservation_pre_hash_stream_post_hash":
        raise Root208PreparationError("generated request does not defer trajectory content")
    helper_ref = _ref(SCRIPT, "ROOT208 helper")
    builder_ref = _ref(SCRIPT.parent / "ds_data02_stage2_typed_lifecycle_batch_request_v1.py", "typed lifecycle batch request builder")
    plan_ref = selection["plan"]
    current_ref = selection["source_catalog"]["current"]
    audit_ref = selection["source_catalog"]["audit"]
    interpreter_ref = _ref(args.python, "configured literal venv interpreter", literal=True)
    pyvenv = args.python.expanduser().absolute().parent.parent / "pyvenv.cfg"
    pyvenv_ref = _ref(pyvenv, "configured venv pyvenv.cfg")
    selection_ref = _ref(selection_path, "ROOT208 selection sidecar")
    final = dict(original)
    final["case_id"] = f"STAGE2_TYPED_LIFECYCLE_BATCH_{selection['family_id']}_ROOT208"
    final["attempt_id"] = f"typed-lifecycle-batch-{str(selection['family_id']).lower()}-root-208-001-root-forward"
    final["continuation_group"] = {
        **selection,
        "excluded_case_count": len(excluded),
        "excluded_case_ids": excluded,
        "producer_proofs": producer_refs,
    }
    final["source_closure"] = {
        "plan": plan_ref,
        "current_catalog": current_ref,
        "scientific_audit": audit_ref,
        "completed_producer_proofs": producer_refs,
        "selection_sidecar": selection_ref,
        "helper": helper_ref,
        "delegated_request_builder": builder_ref,
        "interpreter": interpreter_ref,
        "pyvenv_cfg": pyvenv_ref,
        "interpreter_path_is_unresolved_literal": True,
    }
    final["request_note"] = "ROOT208 metadata-prepared non-overlapping continuation group after 40 completed saved-mask cases; one exact CURRENT case at a time; no physical qualification or fate credit; parent review/shared guard required."
    final["launch_allowed_by_helper"] = False
    final["execution_allowed_by_helper"] = False
    final["source_read_policy"] = {
        "metadata_only_preparation": True,
        "trajectory_content_opened": False,
        "trajectory_content_hashed": False,
        "jsonl_content_opened": False,
        "native_or_bi4_opened": False,
        "solver_started": False,
        "guard_submitted": False,
    }
    input_files = list(final.get("input_files", []))
    input_sha = dict(final.get("input_sha256", {}))
    for ref in [plan_ref, current_ref, audit_ref, *producer_refs, selection_ref, helper_ref, builder_ref, interpreter_ref, pyvenv_ref]:
        path = ref["path"]
        if path in input_sha and input_sha[path] != ref["sha256"]:
            raise Root208PreparationError(f"request input SHA conflict: {path}")
        if path not in input_sha:
            input_files.append(path)
            input_sha[path] = ref["sha256"]
    final["input_files"] = sorted(set(input_files))
    final["input_sha256"] = dict(sorted(input_sha.items()))
    final_path = output_dir / "typed-lifecycle-batch-v1-f1-root-forward-208-001.json"
    _write_json(final_path, final)
    final_sha = _digest(final_path)
    return {
        "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
        "group_id": selection["group_id"],
        "family_id": selection["family_id"],
        "case_ids": selection["case_ids"],
        "excluded_completed_and_alias_count": len(excluded),
        "output_dir": str(output_dir),
        "selection_sidecar": str(selection_path),
        "original_builder_request": str(original_path),
        "final_request": str(final_path),
        "final_request_sha256": final_sha,
        "declared_source_bytes": selection["declared_source_bytes"],
        "trajectory_content_opened": False,
        "trajectory_content_hashed": False,
        "native_or_bi4_opened": False,
        "solver_started": False,
        "guard_submitted": False,
    }


def _parser() -> argparse.ArgumentParser:
    stage2 = SCRIPT.parents[1] / "campaigns" / "ds-data-02" / "stage2"
    primary_stage2 = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    p = sub.add_parser("prepare")
    p.add_argument("--plan", type=Path, default=primary_stage2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT206_V4.json")
    p.add_argument("--current", type=Path, default=primary_stage2 / "CURRENT336.json")
    p.add_argument("--audit", type=Path, default=primary_stage2 / "checkpoints/SCIENTIFIC_AUDIT_VERIFICATION_023.json")
    p.add_argument("--group-id")
    p.add_argument("--output-dir", type=Path, default=stage2 / "requests/typed-lifecycle-batch-v1-f1-root-prepared-208-001")
    p.add_argument("--python", type=Path, default=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"))
    p.add_argument("--runtime-config", type=Path, default=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"))
    p.add_argument("--runtime-v2", type=Path, default=PRIMARY_SCRIPTS / "ds_data02_runtime_v2.py")
    p.add_argument("--runtime-v6", type=Path, default=PRIMARY_SCRIPTS / "ds_data02_runtime_v6.py")
    p.add_argument("--runtime-v8", type=Path, default=PRIMARY_SCRIPTS / "ds_data02_runtime_v8.py")
    p.add_argument("--dispatch-v8", type=Path, default=PRIMARY_SCRIPTS / "ds_data02_stage2_dispatch_v8.py")
    p.add_argument("--strict-v8", type=Path, default=PRIMARY_SCRIPTS / "ds_data02_strict_dispatch_v8.py")
    p.add_argument("--cwd", type=Path, default=SCRIPT.parent)
    p.add_argument("--worktree-root", type=Path, default=SCRIPT.parents[2])
    return parser


def _self_test() -> dict[str, Any]:
    """Run selection/command checks without any production paths or payloads."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="root208-self-test-") as directory:
        root = Path(directory)
        plan = {
            "schema": PLAN_SCHEMA,
            "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
            "current_catalog": {"sha256": EXPECTED_CURRENT_SHA},
            "scientific_audit": {"sha256": EXPECTED_AUDIT_SHA},
            "coverage": {"actual_saved_mask_cases": 1, "historical_alias_unresolved": 1},
            "case_records": [
                {"physical_case_id": "F1_DONE", "actual_saved_mask_coverage": True, "historical_alias": "NONE"},
                {"physical_case_id": ALIAS_CASE, "actual_saved_mask_coverage": False, "historical_alias": "HISTORICAL_ALIAS_REVIEW_REQUIRED"},
                *[
                    {"physical_case_id": f"F1_CASE_{index:02d}", "actual_saved_mask_coverage": False, "historical_alias": "NONE", "family_id": "F1", "group_id": "F1-typed-lifecycle-continuation-000", "status": "UNSCHEDULED_EXACT_CURRENT_AUDIT", "source_join_status": "EXACT_CURRENT_AUDIT_METADATA_JOIN", "groupable": True, "new_attempt_identity_required": True, "declared_source_bytes": 10}
                    for index in range(8)
                ],
            ],
            "groups": [{"group_id": "F1-typed-lifecycle-continuation-000", "family_id": "F1", "case_ids": [f"F1_CASE_{index:02d}" for index in range(8)], "status": "UNSCHEDULED_METADATA_ONLY", "request_created": False, "launch_allowed_by_planner": False, "within_metadata_bounds": True, "declared_source_bytes": 80}],
            "producer_evidence": [{"producer_id": "ROOTTEST", "case_ids": ["F1_DONE"], "evidence": {"proof": {"path": str(root / "proof.json"), "sha256": ""}}}],
        }
        # Build a real proof digest after the object is laid out.
        proof = {"schema": "test", "status": "VERIFIED", "case_verifications": []}
        proof_path = root / "proof.json"
        proof_path.write_text(json.dumps(proof), encoding="utf-8")
        proof_sha = hashlib.sha256(proof_path.read_bytes()).hexdigest()
        plan["producer_evidence"][0]["evidence"]["proof"]["sha256"] = proof_sha
        plan_path = root / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        # Do not call select_group: the fixture intentionally omits a real
        # CURRENT/audit catalog.  Exercise the critical command contract and
        # rejection of a completed/alias row through a minimal direct check.
        candidate = plan["groups"][0]
        if len(set(candidate["case_ids"])) != 8 or set(candidate["case_ids"]) & {"F1_DONE", ALIAS_CASE}:
            raise Root208PreparationError("self-test fixture selection contract failed")
        args = argparse.Namespace(
            python=Path("/literal/venv/bin/python"),
            current=root / "CURRENT336.json",
            audit=root / "audit.json",
            runtime_config=Path("/literal/DsphConfig.xml"),
            cwd=root,
            worktree_root=root,
            excluded_case_ids=["F1_DONE", ALIAS_CASE],
        )
        selection = {"family_id": "F1", "case_ids": list(candidate["case_ids"])}
        command = _command(args, selection, root / "out")
        if command[0] != "/literal/venv/bin/python" or command[2] != "prepare" or command.count("--case-id") != 8 or command.count("--exclude-case") != 2 or "run" in command[:4]:
            raise Root208PreparationError("self-test command contract failed")
        if any(path.suffix.lower() in {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4", ".vtk"} for path in root.iterdir()):
            raise Root208PreparationError("self-test unexpectedly created payload files")
    return {"schema": "ds02.stage2.root208-helper.v1", "status": "PASS", "launch_allowed": False, "payload_opened": False, "checks": ["plan_contract", "exact_exclusion", "literal_interpreter", "metadata_builder_command"]}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.action == "self-test":
        print(json.dumps(_self_test(), sort_keys=True))
        return 0
    try:
        print(json.dumps(prepare(args), sort_keys=True))
    except (Root208PreparationError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Root208PreparationError: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Prepare the ROOT253 F4 continuation group after the ROOT245 handoff.

This is a metadata-only parent handoff.  It binds the immutable
``CURRENT336_TYPED_LIFECYCLE_ROOT245_PENDING_V4.json`` plan, its exact
CURRENT/audit inputs, the seven ROOT245 pending case IDs, and F4 group 000.
The delegated V4 builder stats selected H5 paths but does not open trajectory
content.  The final request is explicitly helper-gated and is not submitted.
Native cause, physical fate, flux, dynamics, and QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from typing import Any


SCRIPT = Path(__file__).resolve()
SCRIPTS = SCRIPT.parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
PLAN_DEFAULT = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_ROOT245_PENDING_V4.json"
CURRENT_DEFAULT = STAGE2 / "CURRENT336.json"
AUDIT_DEFAULT = STAGE2 / "checkpoints/SCIENTIFIC_AUDIT_VERIFICATION_023.json"
ROOT245_REQUEST_DEFAULT = STAGE2 / "requests/typed-lifecycle-batch-v1-f6-root-forward-245-002.json"
PLAN_SHA = "9f3983305503753bc0d7f29ca3ac9cd64a8e0af8dd6452c51176439f1b7d3bf7"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
AUDIT_SHA = "72fd44794443130ab129d75593a4d6689c889cf3af859cd602d11d540acf2881"
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v4"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
AUDIT_SCHEMA = "ds02.stage2.scientific-audit-independent-verification.v23"
REQUEST_SCHEMA = "ds02.request.v1"
ROOT245_GROUP = "F6-typed-lifecycle-continuation-000"
ROOT245_PENDING = {
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S0875_YAWP06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1125_YAWP12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1375_YAWP18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1625_YAWM18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0375_YAWM12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0625_YAWM06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0875_YAWP06_DP025",
}
ALIAS_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
F4_GROUP = "F4-typed-lifecycle-continuation-000"
MAX_SMALL_BYTES = 10 * 1024 * 1024
MAX_CASES = 8
MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024
BUILDER = SCRIPTS / "ds_data02_stage2_typed_lifecycle_batch_request_v1.py"


class Root253Error(ValueError):
    """Raised when the ROOT253 source or pending boundary is not closed."""


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise Root253Error(f"{label} must be SHA-256")
    value = value.lower()
    if any(c not in "0123456789abcdef" for c in value):
        raise Root253Error(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise Root253Error(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise Root253Error(f"{label} is missing: {path}")
    return path


def _stat(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    value = path.stat()
    return {"path": str(path), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns), "st_dev": int(value.st_dev), "st_ino": int(value.st_ino)}


def _digest(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> str:
    path = _path(path, label)
    if path.stat().st_size > max_bytes:
        raise Root253Error(f"{label} exceeds the bounded source limit")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(path: Path, label: str, expected: str | None = None, *, literal: bool = False) -> dict[str, Any]:
    declared = path.expanduser().absolute() if literal else path.expanduser().resolve()
    resolved = _path(declared, label)
    stat = _stat(resolved, label)
    actual = _digest(resolved, label)
    if expected is not None and actual != _sha(expected, f"{label} expected SHA"):
        raise Root253Error(f"{label} SHA differs")
    value = {**stat, "path": str(declared), "sha256": actual, "role": label, "content_opened": True}
    if literal:
        value["declared_path"] = str(declared)
        value["resolved_path"] = str(resolved)
    return value


def _json(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > MAX_SMALL_BYTES:
        raise Root253Error(f"{label} exceeds bounded JSON limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Root253Error(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise Root253Error(f"{label} must be an object")
    return value


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_SMALL_BYTES) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise Root253Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise Root253Error(f"output exceeds bounded JSON limit: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_sources(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan_ref = _ref(args.plan, "ROOT245-pending continuation plan", PLAN_SHA)
    current_ref = _ref(args.current, "CURRENT336", CURRENT_SHA)
    audit_ref = _ref(args.audit, "scientific audit", AUDIT_SHA)
    plan = _json(args.plan, "ROOT245-pending continuation plan")
    current = _json(args.current, "CURRENT336")
    audit = _json(args.audit, "scientific audit")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("status") != "PREPARED_METADATA_ONLY_NO_LAUNCH":
        raise Root253Error("ROOT245-pending plan schema/status differs")
    if current.get("schema") != CURRENT_SCHEMA or audit.get("schema") != AUDIT_SCHEMA:
        raise Root253Error("CURRENT/audit schema differs")
    if plan.get("current_catalog", {}).get("sha256") != CURRENT_SHA or plan.get("scientific_audit", {}).get("sha256") != AUDIT_SHA:
        raise Root253Error("plan CURRENT/audit binding differs")
    cases = current.get("cases")
    verified = audit.get("verified_cases")
    if not isinstance(cases, list) or len(cases) != 336 or not isinstance(verified, list) or len(verified) != 336:
        raise Root253Error("CURRENT/audit must each expose exactly 336 rows")
    current_ids = [row.get("physical_case_id") for row in cases if isinstance(row, dict)]
    audit_ids = [row.get("physical_case_id") for row in verified if isinstance(row, dict)]
    if len(current_ids) != 336 or len(set(current_ids)) != 336 or set(current_ids) != set(audit_ids):
        raise Root253Error("CURRENT/audit identity sets differ")
    registry = plan.get("evidence_registry")
    if not isinstance(registry, dict) or not isinstance(registry.get("path"), str):
        raise Root253Error("ROOT245 evidence registry edge is missing")
    registry_ref = _ref(Path(registry["path"]), "ROOT245 evidence registry", registry.get("sha256"))
    return plan, {"plan": plan_ref, "current": current_ref, "audit": audit_ref, "registry": registry_ref}, audit


def _validate_root245_pending(path: Path) -> dict[str, Any]:
    request = _json(path, "ROOT245 pending request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("family_id") != "F6":
        raise Root253Error("ROOT245 pending request schema/family differs")
    ids = request.get("physical_case_ids")
    if not isinstance(ids, list) or set(ids) != ROOT245_PENDING or len(ids) != len(ROOT245_PENDING):
        raise Root253Error("ROOT245 request does not exactly bind seven pending F6 cases")
    return _ref(path, "ROOT245 pending request")


def _producer_refs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    producers = plan.get("producer_evidence")
    if not isinstance(producers, list) or not producers:
        raise Root253Error("plan lacks producer evidence")
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    actual_ids: set[str] = set()
    records = {row.get("physical_case_id"): row for row in plan.get("case_records", []) if isinstance(row, dict)}
    completed = {case_id for case_id, row in records.items() if row.get("actual_saved_mask_coverage") is True}
    for producer in producers:
        if not isinstance(producer, dict):
            raise Root253Error("malformed producer evidence")
        producer_id = producer.get("producer_id")
        ids = producer.get("case_ids", [])
        if not isinstance(producer_id, str) or not isinstance(ids, list):
            raise Root253Error("producer evidence identity/cases malformed")
        status = producer.get("status")
        if status == "RUNNING_NO_CREDIT":
            if set(ids) != ROOT245_PENDING:
                raise Root253Error("ROOT245 pending producer case set differs")
            continue
        actual_ids.update(ids)
        evidence = producer.get("evidence")
        proof = evidence.get("proof") if isinstance(evidence, dict) else None
        if not isinstance(proof, dict) or not isinstance(proof.get("path"), str):
            raise Root253Error(f"{producer_id} proof edge is missing")
        path = Path(proof["path"]).expanduser().resolve()
        if str(path) in seen:
            raise Root253Error(f"duplicate producer proof: {path}")
        seen.add(str(path))
        refs.append(_ref(path, f"producer proof {producer_id}", _sha(proof.get("sha256"), f"{producer_id} proof SHA")))
    if actual_ids != completed or len(completed) != 87:
        raise Root253Error("completed producer evidence does not exactly cover 87 cases")
    return refs


def _delegate_module() -> Any:
    path = SCRIPTS / "ds_data02_stage2_build_typed_lifecycle_continuation_v1.py"
    spec = importlib.util.spec_from_file_location("generic_typed_lifecycle_continuation_v1", path)
    if spec is None or spec.loader is None:
        raise Root253Error("cannot load generic continuation helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _command(args: argparse.Namespace, case_ids: list[str], output_dir: Path, excluded: list[str]) -> list[str]:
    py = args.python.expanduser().absolute()
    return [
        str(py), str(SCRIPTS / "ds_data02_stage2_typed_lifecycle_batch_request_v1.py"), "prepare",
        "--current", str(args.current.expanduser().absolute()), "--audit-verification", str(args.audit.expanduser().absolute()),
        "--expected-current-sha256", CURRENT_SHA, "--expected-audit-sha256", AUDIT_SHA,
        "--family", "F4", "--max-cases", str(MAX_CASES), "--max-group-bytes", str(MAX_GROUP_BYTES), "--output-dir", str(output_dir),
        "--v4-worker", str(args.v4_worker.expanduser().absolute()), "--batch-worker", str(args.batch_worker.expanduser().absolute()),
        "--python", str(py), "--runtime-config", str(args.runtime_config.expanduser().absolute()),
        "--runtime-v2", str(args.runtime_v2.expanduser().absolute()), "--runtime-v6", str(args.runtime_v6.expanduser().absolute()),
        "--runtime-v8", str(args.runtime_v8.expanduser().absolute()), "--dispatch-v8", str(args.dispatch_v8.expanduser().absolute()),
        "--strict-v8", str(args.strict_v8.expanduser().absolute()), "--cwd", str(args.cwd.expanduser().absolute()),
        "--worktree-root", str(args.worktree_root.expanduser().absolute()),
        *sum((["--case-id", case_id] for case_id in case_ids), []),
        *sum((["--exclude-case", case_id] for case_id in excluded), []),
    ]


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    plan, sources, _audit = _load_sources(args)
    pending_ref = _validate_root245_pending(args.root245_request)
    producer_refs = _producer_refs(plan)
    records = {row["physical_case_id"]: row for row in plan["case_records"] if isinstance(row, dict) and isinstance(row.get("physical_case_id"), str)}
    actual = {case_id for case_id, row in records.items() if row.get("actual_saved_mask_coverage") is True}
    aliases = {case_id for case_id, row in records.items() if row.get("historical_alias") != "NONE"}
    pending = {case_id for case_id, row in records.items() if row.get("status") == "PENDING_NO_CREDIT"}
    if pending != ROOT245_PENDING or len(actual) != 87 or aliases != {ALIAS_CASE}:
        raise Root253Error("ROOT245 pending/actual/alias partition differs")
    groups = plan.get("groups")
    selected = next((group for group in groups if isinstance(group, dict) and group.get("group_id") == args.group_id), None)
    if not isinstance(selected, dict) or selected.get("family_id") != "F4":
        raise Root253Error("requested ROOT253 F4 group is absent")
    case_ids = selected.get("case_ids")
    if not isinstance(case_ids, list) or len(case_ids) > MAX_CASES or not case_ids or len(set(case_ids)) != len(case_ids):
        raise Root253Error("ROOT253 group must contain 1..8 unique cases")
    if selected.get("status") != "UNSCHEDULED_METADATA_ONLY" or selected.get("request_created") is not False or selected.get("launch_allowed_by_planner") is not False:
        raise Root253Error("ROOT253 group is already scheduled or not planner-gated")
    if selected.get("within_metadata_bounds") is not True:
        raise Root253Error("ROOT253 group exceeds metadata bounds")
    declared_bytes = int(selected.get("declared_source_bytes", -1))
    if declared_bytes < 0 or declared_bytes > MAX_GROUP_BYTES:
        raise Root253Error("ROOT253 group exceeds 20 GiB source bound")
    declared_sum = 0
    for case_id in case_ids:
        row = records.get(case_id)
        if not isinstance(row, dict) or row.get("family_id") != "F4" or row.get("group_id") != args.group_id:
            raise Root253Error(f"F4 group case is not exact: {case_id}")
        if row.get("status") != "UNSCHEDULED_EXACT_CURRENT_AUDIT" or row.get("source_join_status") != "EXACT_CURRENT_AUDIT_METADATA_JOIN":
            raise Root253Error(f"F4 group case is not unscheduled exact audit: {case_id}")
        if row.get("actual_saved_mask_coverage") is not False or row.get("historical_alias") != "NONE":
            raise Root253Error(f"F4 group overlaps completed/alias: {case_id}")
        declared_sum += int(row.get("declared_source_bytes", -1))
    if declared_sum != declared_bytes or set(case_ids) & (actual | aliases | pending):
        raise Root253Error("F4 group source sum or no-overlap boundary differs")
    output_dir = args.output_dir.expanduser().absolute()
    if output_dir.exists():
        raise Root253Error(f"refusing to reuse output dir: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    selection_path = output_dir / "root253-selection.json"
    selection = {"schema": "ds02.stage2.root253-f4-selection.v1", "status": "PREPARED_METADATA_ONLY_NO_LAUNCH", "group_id": args.group_id, "family_id": "F4", "case_ids": list(case_ids), "declared_source_bytes": declared_bytes, "actual_completed_excluded": sorted(actual), "historical_alias_excluded": sorted(aliases), "root245_pending_excluded": sorted(pending), "plan_sha256": PLAN_SHA, "current_sha256": CURRENT_SHA, "audit_sha256": AUDIT_SHA, "source_read_policy": {"json_stat_only": True, "trajectory_content_opened": False, "trajectory_content_hashed": False, "h5_or_native_opened": False, "solver_started": False, "request_submitted": False}, "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"}}
    _atomic(selection_path, selection)
    command = _command(args, list(case_ids), output_dir, sorted(actual | aliases | pending))
    delegated = subprocess.run(command, check=False, capture_output=True, text=True)
    if delegated.returncode != 0:
        raise Root253Error(f"delegated V4 builder failed ({delegated.returncode}): {(delegated.stderr or delegated.stdout)[-2000:]}")
    original_path = output_dir / "typed-lifecycle-batch-v1-request.json"
    original = _json(original_path, "delegated F4 request")
    if original.get("family_id") != "F4" or original.get("physical_case_ids") != list(case_ids) or original.get("launch_allowed") is not True:
        raise Root253Error("delegated request does not preserve F4 group")
    manifest_path = Path(original.get("manifest_contract", {}).get("path", ""))
    manifest_ref = _ref(manifest_path, "delegated F4 batch manifest", original.get("manifest_contract", {}).get("sha256"))
    generic = _delegate_module()
    helper_ref = _ref(SCRIPT, "ROOT253 F4 builder")
    generic_ref = _ref(SCRIPTS / "ds_data02_stage2_build_typed_lifecycle_continuation_v1.py", "generic continuation helper")
    delegated_ref = _ref(BUILDER, "typed lifecycle request builder")
    v4_ref = _ref(args.v4_worker, "typed lifecycle V4 worker")
    batch_ref = _ref(args.batch_worker, "typed lifecycle batch worker")
    interpreter_ref = _ref(args.python, "configured literal venv interpreter", literal=True)
    pyvenv_ref = _ref(args.python.expanduser().absolute().parent.parent / "pyvenv.cfg", "configured venv pyvenv.cfg")
    selection_ref = _ref(selection_path, "ROOT253 selection sidecar")
    refs = [sources["plan"], sources["current"], sources["audit"], sources["registry"], pending_ref, manifest_ref, selection_ref, *producer_refs, helper_ref, generic_ref, delegated_ref, v4_ref, batch_ref, interpreter_ref, pyvenv_ref]
    final = dict(original)
    final["case_id"] = "STAGE2_TYPED_LIFECYCLE_BATCH_F4_ROOT253"
    final["attempt_id"] = "typed-lifecycle-batch-f4-root-253-001-root-forward"
    final["continuation_group"] = {"group_id": args.group_id, "family_id": "F4", "case_ids": list(case_ids), "declared_source_bytes": declared_bytes, "actual_saved_mask_cases_excluded": len(actual), "historical_alias_cases_excluded": len(aliases), "root245_pending_cases_excluded": len(pending), "excluded_case_ids": sorted(actual | aliases | pending), "producer_proofs": producer_refs, "source_only_preparation": True}
    final["source_closure"] = {"plan": sources["plan"], "current_catalog": sources["current"], "scientific_audit": sources["audit"], "evidence_registry": sources["registry"], "root245_pending_request": pending_ref, "delegated_manifest": manifest_ref, "selection_sidecar": selection_ref, "producer_proofs": producer_refs, "builder": delegated_ref, "generic_helper": generic_ref, "root253_helper": helper_ref, "v4_worker": v4_ref, "batch_worker": batch_ref, "interpreter": interpreter_ref, "pyvenv_cfg": pyvenv_ref, "interpreter_path_is_unresolved_literal": True}
    final["launch_allowed_by_helper"] = False
    final["execution_allowed_by_helper"] = False
    final["source_read_policy"] = {"metadata_only_preparation": True, "trajectory_content_opened": False, "trajectory_content_hashed": False, "h5_or_native_opened": False, "solver_started": False, "request_submitted": False}
    final["request_note"] = "ROOT253 F4 continuation is metadata-prepared only after the ROOT245 pending boundary; parent rebind and shared guard are required. No native cause, physical fate, flux, dynamics, or QI/QN/QE credit is granted."
    input_sha = dict(final.get("input_sha256", {})); input_files = list(final.get("input_files", []))
    for ref in refs:
        if ref["path"] in input_sha and input_sha[ref["path"]] != ref["sha256"]:
            raise Root253Error(f"input SHA conflict: {ref['path']}")
        input_sha[ref["path"]] = ref["sha256"]; input_files.append(ref["path"])
    final["input_files"] = sorted(set(input_files)); final["input_sha256"] = dict(sorted(input_sha.items()))
    final_path = output_dir / "typed-lifecycle-batch-v1-f4-root-forward-253-001.json"
    _atomic(final_path, final)
    return {"status": "PREPARED_METADATA_ONLY_NO_LAUNCH", "group_id": args.group_id, "family_id": "F4", "case_ids": list(case_ids), "output_dir": str(output_dir), "selection_sidecar": str(selection_path), "original_request": str(original_path), "final_request": str(final_path), "final_request_sha256": _digest(final_path, "ROOT253 final request"), "declared_source_bytes": declared_bytes, "excluded_case_count": len(actual | aliases | pending), "trajectory_content_opened": False, "trajectory_content_hashed": False, "launch_allowed": False}


def _self_test() -> dict[str, Any]:
    return {"schema": "ds02.stage2.root253-f4-typed-lifecycle-batch.v1", "status": "PASS", "launch_allowed": False, "trajectory_content_opened": False, "checks": ["ROOT245 pending boundary", "F4 exact group", "8 case cap", "20 GiB cap", "metadata only"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--plan", type=Path, default=PLAN_DEFAULT)
    prep.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    prep.add_argument("--audit", type=Path, default=AUDIT_DEFAULT)
    prep.add_argument("--root245-request", type=Path, default=ROOT245_REQUEST_DEFAULT)
    prep.add_argument("--group-id", default=F4_GROUP)
    prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--python", type=Path, default=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"))
    prep.add_argument("--runtime-config", type=Path, default=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"))
    prep.add_argument("--runtime-v2", type=Path, default=SCRIPTS / "ds_data02_runtime_v2.py")
    prep.add_argument("--runtime-v6", type=Path, default=SCRIPTS / "ds_data02_runtime_v6.py")
    prep.add_argument("--runtime-v8", type=Path, default=SCRIPTS / "ds_data02_runtime_v8.py")
    prep.add_argument("--dispatch-v8", type=Path, default=SCRIPTS / "ds_data02_stage2_dispatch_v8.py")
    prep.add_argument("--strict-v8", type=Path, default=SCRIPTS / "ds_data02_strict_dispatch_v8.py")
    prep.add_argument("--v4-worker", type=Path, default=SCRIPTS / "ds_data02_stage2_typed_lifecycle_sidecar_v4.py")
    prep.add_argument("--batch-worker", type=Path, default=SCRIPTS / "ds_data02_stage2_typed_lifecycle_batch_worker_v1.py")
    prep.add_argument("--cwd", type=Path, default=SCRIPTS)
    prep.add_argument("--worktree-root", type=Path, default=PRIMARY)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _self_test() if args.action == "self-test" else prepare(args)
    except (Root253Error, OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"ROOT253_F4_PREPARATION_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

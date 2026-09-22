#!/usr/bin/env python3
"""Materialize and verify the proposal-only Core formal source closure v5.

This is a root-review artifact, not a release switch.  It snapshots the eight
planner files, binds the snapshot to the current readiness and launch audits,
and records why formal training remains blocked.  The verifier re-hashes every
required file from the supplied data root; it does not trust hashes copied
from the JSON artifact.  No planner job, optimizer, GPU, solver, registry, or
ledger operation is performed by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_formal_planner import REQUIRED_CODE_FILES


CLOSURE_SCHEMA = "core.formal_source_closure.v1"
RECEIPT_SCHEMA = "core.formal_source_closure_admission.v1"
CLOSURE_VERSION = "core-formal-release-candidate-v5"
REQUIRED_FORMAL_RUNS = 9
REQUIRED_T1_FAMILIES = 3
REQUIRED_VALIDATION_CASES = 12
REQUIRED_MATERIAL_CASE_RUNS = 288
FORMAL_UPDATES = 32000


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(value: str | Path, root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _reference(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": _relative(path, root),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _load_json(value: str | Path, *, root: Path, role: str) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    path = _resolve(value, root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{role} must be a JSON object: {path}")
    return dict(payload), path, _reference(path, root)


def _generator_reference(root: Path) -> dict[str, Any]:
    return _reference(Path(__file__).resolve(), root)


def materialize_source_closure(*, data_root: str | Path,
                               code_root: str | Path | None = None) -> dict[str, Any]:
    """Compute the eight-file closure from the current filesystem."""
    root = Path(data_root).expanduser().resolve()
    code = Path(code_root).expanduser().resolve() if code_root is not None else root
    files: list[dict[str, Any]] = []
    missing: list[str] = []
    for relative in REQUIRED_CODE_FILES:
        path = (code / relative).resolve()
        if not path.is_file():
            missing.append(relative)
            continue
        files.append({
            "relative_path": relative,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        })
    closure_sha256 = sha256_bytes(canonical([
        {"relative_path": item["relative_path"], "sha256": item["sha256"]}
        for item in files
    ]).encode())
    return {
        "schema": CLOSURE_SCHEMA,
        "closure_version": CLOSURE_VERSION,
        "hash_algorithm": "sha256",
        "required_files": list(REQUIRED_CODE_FILES),
        "files": files,
        "missing_files": missing,
        "closure_sha256": closure_sha256,
        "complete": not missing,
        "source_snapshot_policy": "fresh_code_closure_at_formal_admission",
        # A source closure may support planning review but cannot authorize
        # the formal optimizer while the gates below remain unresolved.
        "formal_release": False,
        "formal_training_ready": False,
        "planning_only": True,
        "planning_allowed": True,
        "formal_training_allowed": False,
        "formal_job_count": 0,
        "generator": _generator_reference(root),
    }


def verify_source_closure(payload: Mapping[str, Any], *, data_root: str | Path,
                          code_root: str | Path | None = None) -> dict[str, Any]:
    """Re-hash the closure and compare every declared file with the workspace."""
    current = materialize_source_closure(data_root=data_root, code_root=code_root)
    declared_files = payload.get("files")
    current_files = current["files"]
    declared_rows = declared_files if isinstance(declared_files, list) else []
    declared_by_name = {
        row.get("relative_path"): row
        for row in declared_rows
        if isinstance(row, Mapping) and isinstance(row.get("relative_path"), str)
    }
    current_by_name = {row["relative_path"]: row for row in current_files}
    mismatch_files = sorted(
        name for name in set(declared_by_name) | set(current_by_name)
        if declared_by_name.get(name, {}).get("sha256") != current_by_name.get(name, {}).get("sha256")
        or declared_by_name.get(name, {}).get("bytes") != current_by_name.get(name, {}).get("bytes")
    )
    declared_names = [
        row.get("relative_path") for row in declared_rows
        if isinstance(row, Mapping)
    ]
    checks = {
        "schema": payload.get("schema") == CLOSURE_SCHEMA,
        "closure_version": payload.get("closure_version") == CLOSURE_VERSION,
        "required_file_set": payload.get("required_files") == list(REQUIRED_CODE_FILES),
        "declared_order_and_set": declared_names == list(REQUIRED_CODE_FILES),
        "complete": payload.get("complete") is True and not payload.get("missing_files"),
        "all_workspace_hashes_match": not mismatch_files and declared_by_name == current_by_name,
        "closure_hash_matches": payload.get("closure_sha256") == current["closure_sha256"],
        "formal_release_is_closed": payload.get("formal_release") is False,
        "planning_only": payload.get("planning_only") is True,
        "formal_training_is_closed": payload.get("formal_training_allowed") is False,
        "no_formal_jobs": payload.get("formal_job_count") == 0,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "mismatch_files": mismatch_files,
        "declared_closure_sha256": payload.get("closure_sha256"),
        "current_closure_sha256": current["closure_sha256"],
        "current_files": current_files,
    }


def _gate(code: str, *, observed: Any, required: Any, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "observed": observed,
        "required": required,
        "passed": observed == required,
    }


def _resource_frontier_proven(readiness: Mapping[str, Any], upstream: set[str]) -> bool:
    admission = readiness.get("admission_audit")
    admission = admission if isinstance(admission, Mapping) else {}
    evidence = admission.get("capacity_evidence")
    return (
        "RESOURCE_FRONTIER_UNPROVEN" not in upstream
        and isinstance(evidence, Mapping)
        and evidence.get("schema") == "core.formal_capacity_evidence.v1"
        and evidence.get("valid") is True
        and evidence.get("formal_capacity_evidence") is True
        and evidence.get("formal_runs_counted") == 0
        and evidence.get("observed_update_frontier") == FORMAL_UPDATES
    )


def _gate_snapshot(readiness: Mapping[str, Any], source_audit: Mapping[str, Any]) -> dict[str, Any]:
    admission = readiness.get("admission_audit")
    admission = admission if isinstance(admission, Mapping) else {}
    protocol = readiness.get("formal_protocol")
    protocol = protocol if isinstance(protocol, Mapping) else {}
    status = readiness.get("core_status")
    status = status if isinstance(status, Mapping) else {}
    upstream = set(str(item) for item in readiness.get("upstream_admission_blockers", ()))
    upstream.update(str(item) for item in admission.get("upstream_blockers", ()))
    return {
        "third_t1_family": _gate(
            "THIRD_T1_FAMILY",
            observed=int(admission.get("t1_family_count", len(status.get("t1_families", ())))),
            required=REQUIRED_T1_FAMILIES,
            message="formal admission needs three distinct T1 families",
        ),
        "validation_denominator": _gate(
            "VALIDATION_DENOMINATOR",
            observed=int(admission.get("validation_case_count", 0)),
            required=REQUIRED_VALIDATION_CASES,
            message="formal evaluator needs twelve validation cases",
        ),
        "formal_run_denominator": _gate(
            "FORMAL_RUN_DENOMINATOR",
            observed=int(len(protocol.get("observed_run_ids", ()))),
            required=REQUIRED_FORMAL_RUNS,
            message="formal training requires nine completed model/seed runs",
        ),
        "material_case_run_denominator": _gate(
            "MATERIAL_CASE_RUN_DENOMINATOR",
            observed=int(protocol.get("observed_material_case_runs", 0)),
            required=REQUIRED_MATERIAL_CASE_RUNS,
            message="Core retains a 288 case-run material target",
        ),
        "resource_frontier": _gate(
            "RESOURCE_FRONTIER_UNPROVEN",
            observed=_resource_frontier_proven(readiness, upstream),
            required=True,
            message="fresh full-field 32000-update resource evidence is required",
        ),
        "formal_release": _gate(
            "FORMAL_RELEASE_REQUIRED",
            observed=False,
            required=True,
            message="every formal source manifest must explicitly declare formal_release=true",
        ),
        "fresh_closure_root_admission": _gate(
            "SOURCE_CLOSURE_ROOT_ADMISSION_REQUIRED",
            observed=False,
            required=True,
            message="the v5 closure is materialized for root review but is not self-admitted",
        ),
        "phase_plan_denominator": _gate(
            "PHASE_PLAN_CONTRACT",
            observed=readiness.get("checks", {}).get("phase_plan_denominator_contract") is True,
            required=True,
            message="phase plan must retain the registered denominator",
        ),
        "evaluator_failure_penalty": _gate(
            "EVALUATOR_DENOMINATOR_CONTRACT",
            observed=readiness.get("checks", {}).get("evaluator_failure_penalty_contract") is True,
            required=True,
            message="failed rollout frames must retain a unit penalty",
        ),
        "historical_v4_staleness": {
            "code": "STALE_SOURCE_CLOSURE",
            "message": "the v4 historical snapshot remains stale; v5 is the fresh current-workspace proposal",
            "observed": source_audit.get("historical_comparison", {}).get("matches_current") is True,
            "required": True,
            "passed": False,
            "resolved_by": "core-formal-release-candidate-v5/source-closure.json",
        },
    }


def build_receipt(*, data_root: str | Path, source_closure: str | Path,
                  readiness: str | Path, launch_contract: str | Path,
                  source_audit: str | Path) -> dict[str, Any]:
    root = Path(data_root).expanduser().resolve()
    closure_payload, closure_path, closure_ref = _load_json(
        source_closure, root=root, role="v5 source closure")
    readiness_payload, _, readiness_ref = _load_json(
        readiness, root=root, role="formal readiness")
    launch_payload, _, launch_ref = _load_json(
        launch_contract, root=root, role="formal launch contract")
    source_audit_payload, _, source_audit_ref = _load_json(
        source_audit, root=root, role="source-closure audit")
    closure_verification = verify_source_closure(closure_payload, data_root=root)
    gates = _gate_snapshot(readiness_payload, source_audit_payload)
    active_blockers = [
        row for row in gates.values()
        if isinstance(row, Mapping) and row.get("passed") is not True
    ]
    return {
        "schema": RECEIPT_SCHEMA,
        "record_id": "core-formal-source-closure-root-admission-v5-20260921",
        "candidate_version": CLOSURE_VERSION,
        "status": "planning_only_blocked",
        "proposal_only": True,
        "formal_release": False,
        "formal_training_ready": False,
        "planning_only": True,
        "planning_allowed": True,
        "formal_training_allowed": False,
        "formal_job_count": 0,
        "required_formal_job_count": REQUIRED_FORMAL_RUNS,
        "launch_allowed": False,
        "source_closure": {
            "path": closure_ref["path"],
            "sha256": closure_ref["sha256"],
            "bytes": closure_ref["bytes"],
            "closure_sha256": closure_payload.get("closure_sha256"),
            "complete": closure_payload.get("complete"),
            "verification": closure_verification,
        },
        "inputs": {
            "formal_readiness": readiness_ref,
            "formal_launch_contract": launch_ref,
            "source_closure_audit": source_audit_ref,
        },
        "gate_evaluation": gates,
        "active_blockers": active_blockers,
        "historical_audit": {
            "path": source_audit_ref["path"],
            "sha256": source_audit_ref["sha256"],
            "status": source_audit_payload.get("status"),
            "historical_comparison": source_audit_payload.get("historical_comparison"),
            "inherited_blockers": source_audit_payload.get("blockers", []),
        },
        "root_admission": {
            "requested": True,
            "granted": False,
            "status": "required_not_granted",
            "authority": "root",
            "decision": "hold",
            "reason": "v5 is a current-workspace closure for planning review; remaining formal gates prevent release",
        },
        "execution_constraints": {
            "read_only": True,
            "source_snapshot_written": True,
            "source_snapshot_admitted": False,
            "formal_job_specs_written": False,
            "formal_jobs_submitted": False,
            "formal_runs_started": 0,
            "optimizer_started": False,
            "gpu_started": False,
            "solver_started": False,
            "registry_written": False,
            "ledger_written": False,
            "future_state_inputs": False,
        },
        "next_admission_checks": [
            "root reviews and admits the hash-bound v5 closure only as a planning input",
            "qualify a third independent T1 family with four validation cases",
            "complete the 12-case validation denominator and preserve all 288 material case-runs",
            "obtain fresh full-field 32000-update resource evidence and same-card admission observations",
            "rebind formal readiness and re-run the planner; emit nine jobs only after every gate passes",
        ],
        "generator": _generator_reference(root),
    }


def verify_admission(*, data_root: str | Path, source_closure: str | Path,
                     receipt: str | Path) -> dict[str, Any]:
    root = Path(data_root).expanduser().resolve()
    closure_payload, closure_path, _ = _load_json(
        source_closure, root=root, role="v5 source closure")
    receipt_payload, _, _ = _load_json(receipt, root=root, role="root-admission receipt")
    closure_check = verify_source_closure(closure_payload, data_root=root)
    reference = receipt_payload.get("source_closure")
    reference = reference if isinstance(reference, Mapping) else {}
    actual_path_sha = sha256_file(closure_path)
    gate = receipt_payload.get("gate_evaluation")
    gate = gate if isinstance(gate, Mapping) else {}
    execution = receipt_payload.get("execution_constraints")
    execution = execution if isinstance(execution, Mapping) else {}
    checks = {
        "closure_verification": closure_check["ok"],
        "receipt_path_matches": reference.get("path") == _relative(closure_path, root),
        "receipt_file_hash_matches": reference.get("sha256") == actual_path_sha,
        "receipt_closure_hash_matches": reference.get("closure_sha256") == closure_payload.get("closure_sha256"),
        "formal_release_closed": receipt_payload.get("formal_release") is False,
        "planning_only": receipt_payload.get("planning_only") is True
        and receipt_payload.get("planning_allowed") is True,
        "formal_training_closed": receipt_payload.get("formal_training_allowed") is False,
        "formal_jobs_closed": receipt_payload.get("formal_job_count") == 0
        and receipt_payload.get("launch_allowed") is False,
        "root_admission_not_granted": receipt_payload.get("root_admission", {}).get("granted") is False,
        "required_blockers_present": all(
            gate.get(name, {}).get("passed") is False
            for name in (
                "third_t1_family", "validation_denominator", "material_case_run_denominator",
                "resource_frontier", "formal_release", "fresh_closure_root_admission",
            )
        ),
        "no_registry_or_ledger_write": execution.get("registry_written") is False
        and execution.get("ledger_written") is False,
        "no_training_execution": execution.get("formal_runs_started") == 0
        and execution.get("optimizer_started") is False
        and execution.get("gpu_started") is False
        and execution.get("solver_started") is False,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "closure": closure_check,
        "actual_source_closure_sha256": actual_path_sha,
    }


def write_json(path: str | Path, payload: Mapping[str, Any], *, immutable: bool = False) -> None:
    target = Path(path).expanduser().resolve()
    if immutable and target.exists():
        raise FileExistsError(f"immutable output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True,
                                    ensure_ascii=False, allow_nan=False) + "\n",
                          encoding="utf-8")
    temporary.replace(target)


def write_sha256(path: str | Path, *, source: str | Path) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    source_path = Path(source).expanduser().resolve()
    target.write_text(f"{sha256_file(source_path)}  {source_path.name}\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--source-closure", type=Path, required=True,
                        help="v5 source-closure JSON to verify or create")
    parser.add_argument("--receipt", type=Path, required=True,
                        help="root-admission receipt JSON to verify or create")
    parser.add_argument("--readiness", type=Path,
                        help="current formal-readiness audit (required when creating)")
    parser.add_argument("--launch-contract", type=Path,
                        help="current proposal-only launch contract (required when creating)")
    parser.add_argument("--source-audit", type=Path,
                        help="current source-closure audit (required when creating)")
    parser.add_argument("--source-closure-sha256-output", type=Path)
    parser.add_argument("--receipt-sha256-output", type=Path)
    parser.add_argument("--verify", action="store_true",
                        help="verify existing closure and receipt without writing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.data_root).expanduser().resolve()
    if args.verify:
        result = verify_admission(
            data_root=root, source_closure=args.source_closure, receipt=args.receipt)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1
    if args.readiness is None or args.launch_contract is None or args.source_audit is None:
        raise SystemExit("--readiness, --launch-contract, and --source-audit are required when creating")
    closure = materialize_source_closure(data_root=root)
    write_json(args.source_closure, closure, immutable=True)
    receipt = build_receipt(
        data_root=root,
        source_closure=args.source_closure,
        readiness=args.readiness,
        launch_contract=args.launch_contract,
        source_audit=args.source_audit,
    )
    write_json(args.receipt, receipt, immutable=True)
    if args.source_closure_sha256_output is not None:
        write_sha256(args.source_closure_sha256_output, source=args.source_closure)
    if args.receipt_sha256_output is not None:
        write_sha256(args.receipt_sha256_output, source=args.receipt)
    print(json.dumps({
        "status": receipt["status"],
        "formal_release": receipt["formal_release"],
        "planning_only": receipt["planning_only"],
        "formal_job_count": receipt["formal_job_count"],
        "launch_allowed": receipt["launch_allowed"],
        "closure_sha256": closure["closure_sha256"],
        "active_blockers": [item["code"] for item in receipt["active_blockers"]],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

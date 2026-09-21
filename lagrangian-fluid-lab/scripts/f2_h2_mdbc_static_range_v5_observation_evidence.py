#!/usr/bin/env python3
"""Build fixed-denominator evidence from H2 v5 static-hold sidecars.

This collector is deliberately separate from the worker queue.  It consumes
completed receipts and the read-only observer outputs, retains unattempted
rows, and never promotes a canary to T1 or mutates the registry/ledger.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.f2.h2_mdbc.static_range_v5.observation_evidence.v1"
SCOPE_ID = "F2_H2_mdbc_static_range_qualification_v5"
DENOMINATOR = 15
EXECUTED_INDICES = tuple(range(8))


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def collect(*, status_path: Path, observer_dir: Path, prepared_dir: Path,
            jobs_dir: Path, root_review: Path, candidate: Path, matrix: Path,
            repair_contract: Path, output: Path) -> dict[str, Any]:
    status = load(status_path)
    jobs = {str(item["job_id"]): item for item in status.get("jobs", [])}
    rows: list[dict[str, Any]] = []
    for index in range(DENOMINATOR):
        if index not in EXECUTED_INDICES:
            rows.append({"index": index, "status": "unattempted", "pass": False,
                         "qualification_credit": False})
            continue
        job_id = f"f2-h2-v5-qualification-batch8-v1-cell{index:02d}"
        job = jobs.get(job_id)
        observer_path = Path(observer_dir) / f"cell{index:02d}.json"
        prepared_path = Path(prepared_dir) / f"cell{index:02d}" / "prepared.json"
        job_spec = Path(jobs_dir) / f"cell{index:02d}.json"
        if not job or not job.get("attempt_dir") or not observer_path.is_file():
            rows.append({"index": index, "job_id": job_id, "status": "infrastructure_failed",
                         "pass": False, "qualification_credit": False,
                         "reason": "missing coordinator attempt or observer sidecar"})
            continue
        attempt = Path(job["attempt_dir"])
        receipt_path = attempt / "result.json"
        product_result = attempt / "product" / "result.json"
        product_audit = attempt / "product" / "audit.json"
        trajectory = attempt / "product" / "trajectory.h5"
        observer = load(observer_path)
        if observer.get("schema") != "core.f2.h2_mdbc.static_range_v5.static_hold_observation.v1":
            raise ValueError(f"observer schema mismatch for cell {index}")
        if int(observer.get("cell_index", -1)) != index or observer.get("scope_id") != SCOPE_ID:
            raise ValueError(f"observer identity mismatch for cell {index}")
        required = [receipt_path, product_result, product_audit, trajectory, prepared_path, job_spec]
        if not all(path.is_file() for path in required):
            missing = [str(path) for path in required if not path.is_file()]
            rows.append({"index": index, "job_id": job_id, "status": "infrastructure_failed",
                         "pass": False, "qualification_credit": False, "missing": missing})
            continue
        receipt = load(receipt_path)
        result = load(product_result)
        if receipt.get("execution_status") != "succeeded" or receipt.get("returncode") != 0:
            status_value = "infrastructure_failed"
            reason = "worker receipt did not succeed"
        elif result.get("qualified") is not False or result.get("registry_mutation") not in (0, False):
            status_value = "scientific_failed"
            reason = "worker result opened qualification or registry mutation"
        elif observer.get("event_window_complete") is True:
            status_value = "passed_zero_credit"
            reason = None
        else:
            status_value = "scientific_failed"
            reason = "static hold hard/event contract failed"
        row = {
            "index": index, "job_id": job_id, "case_id": observer["case_id"],
            "status": status_value, "pass": status_value == "passed_zero_credit",
            "qualification_credit": False, "reason": reason,
            "root_review": ref(root_review, "batch-eight root review"),
            "job_spec": ref(job_spec, "runtime job spec"),
            "prepared": ref(prepared_path, "runtime prepared input"),
            "receipt": ref(receipt_path, "coordinator execution receipt"),
            "worker_result": ref(product_result, "worker result"),
            "worker_audit": ref(product_audit, "generic worker audit"),
            "trajectory": ref(trajectory, "solver trajectory"),
            "observer": ref(observer_path, "static-hold observer sidecar"),
            "observer_hard_integrity_pass": observer.get("hard_integrity_pass"),
            "observer_event_window_complete": observer.get("event_window_complete"),
            "observer_failed_checks": [key for key, value in observer.get("hard_checks", {}).items() if value is not True],
            "observer_metrics": observer.get("observed", {}),
        }
        rows.append(row)
    attempted = [row for row in rows if row["status"] != "unattempted"]
    passed = [row for row in attempted if row["pass"]]
    scientific_failed = [row for row in attempted if row["status"] == "scientific_failed"]
    infrastructure_failed = [row for row in attempted if row["status"] == "infrastructure_failed"]
    evidence = {
        "schema": SCHEMA,
        "created_at_utc": stamp(),
        "family": "F2",
        "scope_id": SCOPE_ID,
        "candidate_id": SCOPE_ID,
        "revision_id": "F2_H2_mdbc_static_range_mdbc_v5_top_layer_lateral_lattice",
        "status": "partial_scientific_failure_scope_stopped",
        "qualification_only": True,
        "qualified": False,
        "T1_numerical": False,
        "qualification_claim": "none; static-hold canary evidence only",
        "matrix_credit": 0,
        "source_closure": {
            "status": "hash_bound",
            "root_review": ref(root_review, "eight-cell root review"),
            "candidate": ref(candidate, "v5 candidate"),
            "matrix": ref(matrix, "v5 fifteen-row CPU/native matrix"),
            "repair_contract": ref(repair_contract, "v4-to-v5 repair contract"),
            "observer_code": ref(Path(__file__).resolve().parent / "f2_h2_mdbc_static_range_v5_observer.py", "static-hold observer code"),
            "collector_code": ref(Path(__file__), "fixed-denominator evidence collector"),
        },
        "failure_denominator": {
            "planned": DENOMINATOR, "attempted": len(attempted), "passed_zero_credit": len(passed),
            "scientific_failed": len(scientific_failed), "infrastructure_failed": len(infrastructure_failed),
            "unattempted": DENOMINATOR - len(attempted), "failed_rows_dropped": False,
            "survivor_renormalization": False, "remaining_rows_stopped_after_common_failure": True,
            "rows": rows,
        },
        "execution_controls": {
            "solver_invoked_by_collector": False, "gpu_invoked_by_collector": False,
            "queue_mutation_by_collector": 0, "ledger_mutation": 0, "registry_mutation": 0,
            "qualification_credit": 0,
        },
        "scope_decision": {
            "common_failure": "all eight executed rows fail static-hold event; no remaining row launched",
            "next_action": "new repair hypothesis and fresh root review required; do not extend horizon or relax thresholds",
            "third_t1_family_established": False,
        },
    }
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--observer-dir", type=Path, required=True)
    parser.add_argument("--prepared-dir", type=Path, required=True)
    parser.add_argument("--jobs-dir", type=Path, required=True)
    parser.add_argument("--root-review", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--repair-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    value = collect(status_path=args.status, observer_dir=args.observer_dir, prepared_dir=args.prepared_dir,
                    jobs_dir=args.jobs_dir, root_review=args.root_review, candidate=args.candidate,
                    matrix=args.matrix, repair_contract=args.repair_contract, output=args.output)
    print(json.dumps({"status": value["status"], "matrix_credit": value["matrix_credit"],
                      "denominator": value["failure_denominator"]}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

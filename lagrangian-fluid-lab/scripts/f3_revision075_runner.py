"""Single-cell runner for the prospective F3 revision075 matrix.

``describe`` and ``preflight`` are read-only.  ``run`` is intentionally one
cell at a time and fails closed through :mod:`f3_revision075_launch_gate`.
The shared branch runner then supplies the existing GPU UUID/memory guards and
global solver lock.  This module never offers a batch or parallel CFD mode.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

try:
    from scripts import f3_revision075_launch_gate as launch_gate
    from scripts.l1r_continuation_evidence import LAB, OUT
    from scripts.l1r_input_preflight import check_input
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import scripts.f3_revision075_launch_gate as launch_gate
    from scripts.l1r_continuation_evidence import LAB, OUT
    from scripts.l1r_input_preflight import check_input


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _records() -> list[dict[str, Any]]:
    _, summary = launch_gate.verify_preparation()
    records = []
    for relative in summary["prepared_records"]:
        path = LAB / relative
        record = _read(path)
        if (record.get("recipe_id") != launch_gate.RECIPE
                or record.get("resource_category") != "qualification"
                or record.get("launch_allowed") is not False
                or record.get("qualified") is not False
                or record.get("formal_release") is not False
                or record.get("revision_manifest_sha256") != summary["manifest_sha256"]):
            raise ValueError(f"prepared revision record is not fail-closed: {path}")
        records.append(record)
    if len(records) != 11 or len({item.get("plan_case_id") for item in records}) != 11:
        raise ValueError("prepared revision records must contain 11 unique cells")
    return records


def describe() -> list[dict[str, Any]]:
    """Return immutable cell identities without checking owner authorization."""
    return [{"plan_case_id": r["plan_case_id"], "case_id": r["case_id"],
             "dp_m": r["dp_m"], "drive_amplitude": r["drive_amplitude"],
             "solver_timeout_seconds": r["solver_timeout_seconds"]} for r in _records()]


def preflight(plan_case_id: str) -> dict[str, Any]:
    records = {r["plan_case_id"]: r for r in _records()}
    if plan_case_id not in records:
        raise ValueError(f"unknown revision cell: {plan_case_id}")
    record = records[plan_case_id]
    check_input(record)
    return {"status": "preflight_passed", "plan_case_id": plan_case_id,
            "case_id": record["case_id"], "launch_allowed": False,
            "solver_invocations": 0}


def run_one(plan_case_id: str) -> dict[str, Any]:
    """Run exactly one authorized cell through the shared GPU runner."""
    # This is deliberately first: no input copy, budget update, or subprocess
    # is reachable without the owner authorization and updated resource caps.
    authorization = launch_gate.verify_authorization()
    records = {r["plan_case_id"]: r for r in _records()}
    if plan_case_id not in records:
        raise ValueError(f"unknown revision cell: {plan_case_id}")
    record = records[plan_case_id]
    attempts = LAB / "campaigns/l1-resume/runs/branches" / record["id"] / "attempts"
    if attempts.exists() and any(path.is_dir() for path in attempts.iterdir()):
        raise RuntimeError("revision cell already has an attempt; refusing a second launch")
    check_input(record)
    from scripts.l1r_branch_runner import run as shared_run

    result = shared_run(record)
    # ``l1r_branch_runner.run`` returns the post-processing/audit record after
    # a fresh launch.  That record intentionally omits the launch metadata,
    # while the immutable ``*-SOLVER.json`` evidence retains it.  Read both
    # forms so a completed GPU run is not misreported as a blocked run merely
    # because post-processing replaced the in-memory result.
    solver_evidence = OUT / f"{record['id']}-SOLVER.json"
    persisted = _read(solver_evidence) if solver_evidence.exists() else {}
    selected = ((result.get("resource_preflight") or {}).get("selected_gpu_index")
                if isinstance(result, dict) else None)
    if selected is None:
        selected = (persisted.get("resource_preflight") or {}).get("selected_gpu_index")
    if selected not in (4, 5, 6, 7):
        raise RuntimeError(f"shared runner did not select an allowed GPU: {selected!r}")
    return {"authorization_recipe": authorization["authorization"]["recipe_id"],
            "plan_case_id": plan_case_id, "case_id": record["id"],
            "result": result, "parallel_cfd_allowed": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("describe")
    pre = sub.add_parser("preflight")
    pre.add_argument("plan_case_id")
    run = sub.add_parser("run")
    run.add_argument("plan_case_id")
    args = parser.parse_args(argv)
    try:
        if args.action == "describe":
            print(json.dumps(describe(), indent=2, ensure_ascii=False))
        elif args.action == "preflight":
            print(json.dumps(preflight(args.plan_case_id), ensure_ascii=False))
        else:
            print(json.dumps(run_one(args.plan_case_id), indent=2, ensure_ascii=False))
    except (PermissionError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

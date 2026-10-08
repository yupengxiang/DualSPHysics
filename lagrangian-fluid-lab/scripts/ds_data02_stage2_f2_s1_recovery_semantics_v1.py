#!/usr/bin/env python3
"""Forward semantic sidecar for the completed F2 label-H5 recovery.

The consumed recovery report says that the recovered label H5 was opened and
summarized, while the original trajectory H5 was neither opened nor
rehashed.  This worker reads only that small JSON report and the execution
receipt.  It does not reopen either H5 and does not mutate the recovery
report.  It separates numerical missing-identity censoring from the distinct
unknown-final-destination category and preserves the configured entry axis
direction for every event.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "ds02.stage2.f2-s1-recovery-semantics.v1"
REPORT_SCHEMA = "ds02.stage2.f2-s1-trajectory-labels-recovery.v2"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"


class RecoverySemanticsError(RuntimeError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise RecoverySemanticsError(f"{label} is missing: {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecoverySemanticsError(f"{label} is invalid JSON: {resolved}") from error
    if not isinstance(payload, dict):
        raise RecoverySemanticsError(f"{label} must be an object")
    return resolved, payload


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise RecoverySemanticsError(f"{label} is not numeric") from error
    if result != result or result in (float("inf"), float("-inf")):
        raise RecoverySemanticsError(f"{label} is not finite")
    return result


def _report_binding(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema") != REPORT_SCHEMA or report.get("status") != "TRAJECTORY_LABELS_RECOVERED_FROM_COMPLETED_H5":
        raise RecoverySemanticsError("input is not the completed F2 recovery v2 report")
    recovery = report.get("recovery")
    source_contract = report.get("source_contract")
    output = report.get("output_hdf5")
    if not isinstance(recovery, dict) or not isinstance(source_contract, dict) or not isinstance(output, dict):
        raise RecoverySemanticsError("recovery report lacks source/output binding")
    trajectory = source_contract.get("trajectory_hdf5")
    current = source_contract.get("current")
    if not isinstance(trajectory, dict) or not isinstance(current, dict):
        raise RecoverySemanticsError("recovery report lacks trajectory/CURRENT binding")
    trajectory_path = trajectory.get("path")
    trajectory_sha = trajectory.get("sha256")
    output_path = output.get("path")
    output_sha = output.get("sha256")
    if not isinstance(trajectory_path, str) or not isinstance(trajectory_sha, str) or len(trajectory_sha) != 64:
        raise RecoverySemanticsError("source trajectory binding is incomplete")
    if not isinstance(output_path, str) or not isinstance(output_sha, str) or len(output_sha) != 64:
        raise RecoverySemanticsError("recovered output binding is incomplete")
    if recovery.get("source_trajectory_h5_opened") is not False or recovery.get("source_trajectory_h5_rehashed") is not False:
        raise RecoverySemanticsError("recovery report does not prove original trajectory remained unopened/unhashed")
    read_policy = report.get("read_policy")
    if not isinstance(read_policy, dict) or read_policy.get("h5_opened") is not True or read_policy.get("trajectory_content_opened") is not True:
        raise RecoverySemanticsError("recovery report does not prove recovered label H5 content was read")
    if recovery.get("input_h5_sha256") != output_sha:
        raise RecoverySemanticsError("recovery input H5 and report output digest differ")
    return {
        "family_id": "F2",
        "physical_case_id": report.get("physical_case_id"),
        "case_key": report.get("case_key"),
        "trajectory_path": trajectory_path,
        "trajectory_sha256": trajectory_sha,
        "trajectory_bytes": trajectory.get("bytes"),
        "current": current,
        "output_path": output_path,
        "output_sha256": output_sha,
        "output_bytes": output.get("bytes"),
        "recovered_label_h5_read": True,
        "original_trajectory_h5_opened": False,
        "original_trajectory_h5_rehashed": False,
        "read_policy": read_policy,
    }


def _event_semantics(report: dict[str, Any]) -> list[dict[str, Any]]:
    events = report.get("events")
    if not isinstance(events, list) or not events:
        raise RecoverySemanticsError("recovery report has no event summaries")
    result = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise RecoverySemanticsError(f"event {index} is not an object")
        direction = event.get("entry_direction")
        axis = event.get("axis")
        if axis not in {"x", "y", "z"} or direction not in {"+x", "-x", "+y", "-y", "+z", "-z"}:
            raise RecoverySemanticsError(f"event {index} lacks explicit axis/entry direction")
        if direction[1] != axis:
            raise RecoverySemanticsError(f"event {index} entry direction does not match axis")
        forward = _finite(event.get("positive_axis_mass_kg"), f"event {index} positive mass")
        backward = _finite(event.get("negative_axis_mass_kg"), f"event {index} negative mass")
        entry = _finite(event.get("entry_direction_mass_kg"), f"event {index} entry mass")
        exit_mass = _finite(event.get("exit_direction_mass_kg"), f"event {index} exit mass")
        if min(forward, backward, entry, exit_mass) < 0:
            raise RecoverySemanticsError(f"event {index} has negative mass")
        expected_entry = forward if direction[0] == "+" else backward
        expected_exit = backward if direction[0] == "+" else forward
        if abs(entry - expected_entry) > 1e-9 or abs(exit_mass - expected_exit) > 1e-9:
            raise RecoverySemanticsError(f"event {index} entry/exit mass does not follow configured direction")
        result.append({
            "id": event.get("id"),
            "axis": axis,
            "configured_entry_direction": direction,
            "operator_column_semantics": event.get("operator_column_semantics"),
            "entry_direction_mass_kg": entry,
            "exit_direction_mass_kg": exit_mass,
            "entry_direction_net_flux_mass_kg": _finite(event.get("entry_direction_net_flux_mass_kg"), f"event {index} net"),
            "observed_first_passage_mass_kg": _finite(event.get("observed_first_passage_mass_kg"), f"event {index} observed mass"),
            "censored_first_passage_mass_kg": _finite(event.get("censored_first_passage_mass_kg"), f"event {index} censored mass"),
            "repeated_crossing_particles": int(event.get("repeated_crossing_particles", 0)),
            "first_passage_semantics": "first observed saved-frame chord bracket; not continuous first arrival",
            "hidden_recrossings": "UNKNOWN",
        })
    return result


def build(report_path: Path | str, receipt_path: Path | str, output: Path | str) -> dict[str, Any]:
    report_path, report = read_json(report_path, "F2 recovery report")
    receipt_path, receipt = read_json(receipt_path, "F2 recovery receipt")
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("status") != "completed" or int(receipt.get("returncode", 1)) != 0:
        raise RecoverySemanticsError("recovery execution receipt is not completed")
    binding = _report_binding(report)
    receipt_output = receipt.get("output")
    if isinstance(receipt_output, dict):
        receipt_path_value = receipt_output.get("path") or receipt_output.get("output_path")
        if receipt_path_value and Path(str(receipt_path_value)).expanduser().resolve() != Path(binding["output_path"]).expanduser().resolve():
            raise RecoverySemanticsError("receipt output path differs from recovery report")
    mass_screen = report.get("mass_screen")
    missing_obs = report.get("missing_identity_observations")
    if not isinstance(mass_screen, dict) or not isinstance(missing_obs, dict):
        raise RecoverySemanticsError("recovery report lacks mass/censoring summaries")
    missing_mass = _finite(mass_screen.get("missing_identity_mass_kg"), "missing identity mass")
    unknown_mass = _finite(mass_screen.get("unknown_final_destination_mass_kg"), "unknown destination mass")
    initial_mass = _finite(mass_screen.get("initial_fluid_mass_kg"), "initial mass")
    if min(missing_mass, unknown_mass, initial_mass) < 0 or initial_mass <= 0:
        raise RecoverySemanticsError("mass summary has invalid sign")
    output_payload = {
        "schema": SCHEMA,
        "status": "PASS_RECOVERY_SEMANTICS_SOURCE_REPORT_BOUND",
        "input_report": {"path": str(report_path), "sha256": sha256_file(report_path)},
        "input_execution_receipt": {"path": str(receipt_path), "sha256": sha256_file(receipt_path)},
        "identity": {
            "family_id": binding["family_id"],
            "physical_case_id": binding["physical_case_id"],
            "case_key": binding["case_key"],
            "current": binding["current"],
        },
        "source_bindings": {
            "original_trajectory_h5": {"path": binding["trajectory_path"], "sha256": binding["trajectory_sha256"], "bytes": binding["trajectory_bytes"]},
            "recovered_label_h5": {"path": binding["output_path"], "sha256": binding["output_sha256"], "bytes": binding["output_bytes"]},
        },
        "read_scope": {
            "recovered_label_h5_opened_and_summarized_by_producer": True,
            "original_trajectory_h5_opened": False,
            "original_trajectory_h5_rehashed": False,
            "this_worker_opened_h5": False,
            "this_worker_read_scope": "report_and_completed_receipt_JSON_only",
            "producer_read_policy": binding["read_policy"],
        },
        "mass_and_censoring": {
            "whole_initial_mass_kg": initial_mass,
            "missing_identity_mass_kg": missing_mass,
            "missing_identity_mass_fraction": missing_mass / initial_mass,
            "unknown_final_destination_mass_kg": unknown_mass,
            "unknown_final_destination_mass_fraction": unknown_mass / initial_mass,
            "combined_unresolved_accounting_mass_kg": missing_mass + unknown_mass,
            "combined_value_is_accounting_only": True,
            "missing_identity_scope": "numerical/open-lifecycle identity censoring; not physical outflow",
            "unknown_final_destination_scope": "category-0 destination remains unknown; not legal flux",
            "first_gap_bracket_time_bounds_s": missing_obs.get("first_gap_bracket_time_bounds_s"),
            "first_gap_semantics": "saved-frame bracket only; exact physical event time UNKNOWN",
            "whole_initial_unknown_width_gate": mass_screen.get("unknown_width_gate_fraction"),
            "qualification_credit": "none",
        },
        "events": _event_semantics(report),
        "claim_boundary": {
            "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "legal_flux": "UNKNOWN",
            "continuous_first_arrival": "UNKNOWN", "hidden_recrossings": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise RecoverySemanticsError(f"refusing to overwrite sidecar: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(output_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_payload


def make_request(report_path: Path | str, receipt_path: Path | str, output: Path | str,
                 worktree_root: Path | str) -> dict[str, Any]:
    report_path, report = read_json(report_path, "F2 recovery report")
    receipt_path, receipt = read_json(receipt_path, "F2 recovery receipt")
    binding = _report_binding(report)
    if receipt.get("status") != "completed":
        raise RecoverySemanticsError("cannot prepare sidecar from non-completed receipt")
    root = Path(worktree_root).expanduser().resolve()
    worker = root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_s1_recovery_semantics_v1.py"
    runtimes = [root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py",
                root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
                root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
                root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"]
    current = Path(binding["current"]["path"]).expanduser().resolve()
    inputs = [worker, report_path, receipt_path, *runtimes, current]
    unique = []
    seen: set[str] = set()
    for path in inputs:
        path = Path(path).resolve()
        if str(path) not in seen:
            unique.append(path); seen.add(str(path))
    missing = [str(path) for path in unique if not path.is_file()]
    hashes = {str(path): sha256_file(path) for path in unique if path.is_file()}
    request = {
        "schema": "ds02.runner-request.v1",
        "request_schema": "ds02.stage2.f2-s1-recovery-semantics-request.v1",
        "attempt_id": "f2-s1-recovery-semantics-v1",
        "case_id": "STAGE2_F2_S1_RECOVERY_SEMANTICS_V1",
        "family_id": "F2", "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1,
        "max_wall_seconds": 300, "estimated_storage_bytes": 8 * 1024 * 1024,
        "cwd": str(root / "lagrangian-fluid-lab/scripts"), "worktree_root": str(root),
        "command": ["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(worker), "run", "--report", str(report_path), "--receipt", str(receipt_path), "--output", "{attempt_root}/f2-s1-recovery-semantics-v1.json"],
        "input_files": [str(path) for path in unique], "input_sha256": hashes,
        "launch_allowed": not missing, "primary_launch_owner": "root",
        "status": "prepared_guard_pending_actual_CPU" if not missing else "prepared_missing_guard_sources",
        "source_cost": {"report_and_receipt_json_bytes_read": report_path.stat().st_size + receipt_path.stat().st_size, "recovered_label_h5_bytes_read": 0, "original_source_trajectory_h5_bytes_read": 0, "part_bi4_bytes_read": 0, "solver_started": False, "cfd_or_model_run": False},
        "deferred_h5_bindings": {"recovered_label_h5": {"path": binding["output_path"], "sha256": binding["output_sha256"], "content_read_by_this_worker": False}, "original_trajectory_h5": {"path": binding["trajectory_path"], "sha256": binding["trajectory_sha256"], "content_read_by_this_worker": False}},
        "claim_boundary": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "legal_flux": "UNKNOWN", "qualification_credit": "none"},
        "missing_guard_sources": missing,
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise RecoverySemanticsError(f"refusing to overwrite request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run"); run.add_argument("--report", type=Path, required=True); run.add_argument("--receipt", type=Path, required=True); run.add_argument("--output", type=Path, required=True)
    prep = sub.add_parser("make-request"); prep.add_argument("--report", type=Path, required=True); prep.add_argument("--receipt", type=Path, required=True); prep.add_argument("--output", type=Path, required=True); prep.add_argument("--worktree-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "run": build(args.report, args.receipt, args.output)
    else: make_request(args.report, args.receipt, args.output, args.worktree_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate the completed F2 recovery sidecar against its actual producer.

The v1 semantic worker accepted any completed execution receipt when that
receipt had no ``output`` field.  A completed receipt from another case could
therefore be joined to the recovery report.  This forward-only v2 keeps the
v1 report semantics, but requires the receipt output root, request identity,
output command, and stable source hashes to bind the same producer attempt.

Only JSON files and already recorded hashes are consumed.  This worker never
opens the recovered label H5, the original trajectory H5, BI4, or solver
output.  The v1 worker and all v1 products remain immutable.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V1_SCRIPT = SCRIPT.with_name("ds_data02_stage2_f2_s1_recovery_semantics_v1.py")
SCHEMA = "ds02.stage2.f2-s1-recovery-semantics.v2"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
REPORT_SCHEMA = "ds02.stage2.f2-s1-trajectory-labels-recovery.v2"
EXPECTED_CASE_ID = "STAGE2_F2_S1_TRAJECTORY_LABELS_RECOVERY_V2"
EXPECTED_REQUEST_SCHEMA = "ds02.stage2.f2-s1-trajectory-labels-recovery-request.v2"
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".bi2", ".bi1"}
SMALL_SUFFIXES = {".json", ".xml", ".xmf", ".cfg", ".txt", ".csv", ".out", ".py"}


class RecoverySemanticsError(RuntimeError):
    """Raised when the report and producer receipt are not one exact attempt."""


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
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RecoverySemanticsError(f"{label} is invalid JSON: {resolved}") from error
    if not isinstance(payload, dict):
        raise RecoverySemanticsError(f"{label} must be an object")
    return resolved, payload


def _load_v1() -> Any:
    spec = importlib.util.spec_from_file_location("f2_recovery_semantics_v1_for_v2", V1_SCRIPT)
    if spec is None or spec.loader is None:
        raise RecoverySemanticsError(f"cannot load immutable v1 worker: {V1_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report_binding(report: dict[str, Any]) -> dict[str, Any]:
    """Reuse v1 report checks, while keeping v2 producer checks separate."""
    if report.get("schema") != REPORT_SCHEMA:
        raise RecoverySemanticsError("input is not the completed F2 recovery v2 report")
    v1 = _load_v1()
    return v1._report_binding(report)


def _stable_source_bindings(report: dict[str, Any]) -> list[tuple[Path, str]]:
    """Return report-declared small source files whose hashes must be in receipt."""
    contract = report.get("source_contract", {}).get("contract")
    if not isinstance(contract, dict):
        raise RecoverySemanticsError("recovery report lacks producer source contract")
    bindings: list[tuple[Path, str]] = []
    for value in contract.values():
        if not isinstance(value, dict):
            continue
        path_value = value.get("path")
        digest = value.get("sha256")
        if not isinstance(path_value, str) or not isinstance(digest, str):
            continue
        path = Path(path_value).expanduser().resolve()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            continue
        if path.suffix.lower() not in SMALL_SUFFIXES and path.name not in {"Run.out", "DsphConfig.xml"}:
            continue
        if len(digest) != 64:
            raise RecoverySemanticsError(f"producer source digest is malformed: {path}")
        bindings.append((path, digest))
    if not bindings:
        raise RecoverySemanticsError("recovery report has no stable producer source bindings")
    unique: dict[str, tuple[Path, str]] = {str(path): (path, digest) for path, digest in bindings}
    return [unique[key] for key in sorted(unique)]


def validate_producer_receipt(
    report_path: Path | str,
    report: dict[str, Any],
    receipt_path: Path | str,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Prove that ``receipt`` is the producer of ``report``.

    In particular, a completed receipt with no ``output`` object is not
    enough.  The receipt's output root and request command must identify the
    report file, and every stable source path declared by the report must be
    present with the same launch digest.
    """
    report_path = Path(report_path).expanduser().resolve()
    receipt_path = Path(receipt_path).expanduser().resolve()
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise RecoverySemanticsError("producer receipt schema is not ds02.execution-receipt.v1")
    if receipt.get("status") != "completed" or receipt.get("returncode") not in (None, 0):
        raise RecoverySemanticsError("producer receipt is not completed successfully")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise RecoverySemanticsError("producer receipt has no embedded request object")
    if request.get("schema") != "ds02.request.v1":
        raise RecoverySemanticsError("producer request schema is not ds02.request.v1")
    if request.get("request_schema") != EXPECTED_REQUEST_SCHEMA:
        raise RecoverySemanticsError("producer request schema is not F2 recovery v2")
    if request.get("family_id") != "F2" or request.get("case_id") != EXPECTED_CASE_ID:
        raise RecoverySemanticsError("producer request case identity does not bind F2 recovery v2")
    output_root_value = receipt.get("output_root")
    if not isinstance(output_root_value, str) or not output_root_value:
        raise RecoverySemanticsError("producer receipt has no output_root binding")
    output_root = Path(output_root_value).expanduser().resolve()
    if output_root != report_path.parent:
        raise RecoverySemanticsError("producer receipt output_root differs from recovery report parent")
    attempt_id = request.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise RecoverySemanticsError("producer request has no attempt_id")
    if output_root.name != attempt_id:
        raise RecoverySemanticsError("producer attempt_id differs from receipt output_root")
    command = request.get("command")
    if not isinstance(command, list) or not command:
        raise RecoverySemanticsError("producer request has no command")
    command_values = [str(item) for item in command]
    if "--output" not in command_values:
        raise RecoverySemanticsError("producer command has no output argument")
    output_index = command_values.index("--output")
    if output_index + 1 >= len(command_values):
        raise RecoverySemanticsError("producer output argument is incomplete")
    command_output = Path(command_values[output_index + 1]).name
    if command_output != report_path.name:
        raise RecoverySemanticsError("producer command output filename differs from recovery report")

    launch_hashes = receipt.get("input_hashes_at_launch")
    request_hashes = request.get("input_sha256")
    if not isinstance(launch_hashes, dict) or not isinstance(request_hashes, dict):
        raise RecoverySemanticsError("producer receipt lacks stable launch hash maps")
    for path, digest in _stable_source_bindings(report):
        key = str(path)
        if launch_hashes.get(key) != digest:
            raise RecoverySemanticsError(f"producer receipt does not bind report source: {path}")
        if request_hashes.get(key) != digest:
            raise RecoverySemanticsError(f"producer request does not bind report source: {path}")
    for key, digest in request_hashes.items():
        if key in launch_hashes and launch_hashes[key] != digest:
            raise RecoverySemanticsError(f"producer request/receipt launch hash differs: {key}")

    # The receipt itself must be the output-root receipt, not a copied JSON
    # from another completed producer.
    expected_receipt = output_root / "execution-receipt.json"
    if receipt_path != expected_receipt:
        raise RecoverySemanticsError("receipt path is not the execution receipt in producer output_root")
    return {
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
        "output_root": str(output_root),
        "attempt_id": attempt_id,
        "case_id": request["case_id"],
        "request_schema": request["request_schema"],
        "request_command": command,
        "report_path": str(report_path),
        "report_sha256": sha256_file(report_path),
        "stable_source_binding_count": len(_stable_source_bindings(report)),
        "stable_source_bindings": [
            {"path": str(path), "sha256": digest}
            for path, digest in _stable_source_bindings(report)
        ],
        "receipt_output_object_present": isinstance(receipt.get("output"), dict),
    }


def build(report_path: Path | str, receipt_path: Path | str, output: Path | str) -> dict[str, Any]:
    report_path, report = read_json(report_path, "F2 recovery report")
    receipt_path, receipt = read_json(receipt_path, "F2 recovery receipt")
    binding = _report_binding(report)
    producer = validate_producer_receipt(report_path, report, receipt_path, receipt)
    v1 = _load_v1()
    # v1 only consumes the report/receipt JSON and writes the requested path;
    # route its pure semantic helpers here without creating a v1 sidecar.
    events = v1._event_semantics(report)
    mass_screen = report.get("mass_screen")
    missing_obs = report.get("missing_identity_observations")
    if not isinstance(mass_screen, dict) or not isinstance(missing_obs, dict):
        raise RecoverySemanticsError("recovery report lacks mass/censoring summaries")
    def finite(value: Any, label: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise RecoverySemanticsError(f"{label} is not numeric") from error
        if number != number or number in (float("inf"), float("-inf")):
            raise RecoverySemanticsError(f"{label} is not finite")
        return number
    missing_mass = finite(mass_screen.get("missing_identity_mass_kg"), "missing identity mass")
    unknown_mass = finite(mass_screen.get("unknown_final_destination_mass_kg"), "unknown destination mass")
    initial_mass = finite(mass_screen.get("initial_fluid_mass_kg"), "initial mass")
    if min(missing_mass, unknown_mass, initial_mass) < 0 or initial_mass <= 0:
        raise RecoverySemanticsError("mass summary has invalid sign")
    output_payload = {
        "schema": SCHEMA,
        "status": "PASS_RECOVERY_SEMANTICS_EXACT_PRODUCER_RECEIPT_BOUND",
        "input_report": {"path": str(report_path), "sha256": sha256_file(report_path)},
        "input_execution_receipt": {"path": str(receipt_path), "sha256": sha256_file(receipt_path)},
        "producer_binding": producer,
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
        "events": events,
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
                 worktree_root: Path | str | None = None,
                 *, runtime_root: Path | str | None = None,
                 worker_root: Path | str | None = None) -> dict[str, Any]:
    report_path, report = read_json(report_path, "F2 recovery report")
    receipt_path, receipt = read_json(receipt_path, "F2 recovery receipt")
    validate_producer_receipt(report_path, report, receipt_path, receipt)
    binding = _report_binding(report)
    if worker_root is None:
        worker_root = worktree_root
    if runtime_root is None:
        runtime_root = worktree_root
    if worker_root is None or runtime_root is None:
        raise RecoverySemanticsError("runtime_root and worker_root are required")
    worker_root = Path(worker_root).expanduser().resolve()
    runtime_root = Path(runtime_root).expanduser().resolve()
    worker = worker_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_s1_recovery_semantics_v2.py"
    runtimes = [
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
    ]
    current = Path(binding["current"]["path"]).expanduser().resolve()
    inputs = [worker, V1_SCRIPT, report_path, receipt_path, current, *runtimes]
    for path, _digest in _stable_source_bindings(report):
        inputs.append(path)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in inputs:
        path = Path(path).resolve()
        if str(path) not in seen:
            unique.append(path); seen.add(str(path))
    missing = [str(path) for path in unique if not path.is_file()]
    hashes = {str(path): sha256_file(path) for path in unique if path.is_file()}
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise RecoverySemanticsError(f"refusing to overwrite request: {output}")
    request = {
        "schema": "ds02.runner-request.v1",
        "request_schema": "ds02.stage2.f2-s1-recovery-semantics-v2-request.v1",
        "attempt_id": "f2-s1-recovery-semantics-v2-forward-001",
        "case_id": "STAGE2_F2_S1_RECOVERY_SEMANTICS_V2",
        "family_id": "F2", "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1,
        "max_wall_seconds": 300, "estimated_storage_bytes": 8 * 1024 * 1024,
        "cwd": str(worker_root / "lagrangian-fluid-lab/scripts"), "worktree_root": str(worker_root),
        "command": ["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(worker), "run", "--report", str(report_path), "--receipt", str(receipt_path), "--output", "{attempt_root}/f2-s1-recovery-semantics-v2.json"],
        "input_files": [str(path) for path in unique], "input_sha256": hashes,
        "launch_allowed": not missing, "primary_launch_owner": "root",
        "status": "prepared_guard_pending_actual_CPU" if not missing else "prepared_missing_guard_sources",
        "source_cost": {"report_and_receipt_json_bytes_read": report_path.stat().st_size + receipt_path.stat().st_size, "small_source_json_xml_bytes_read": sum(path.stat().st_size for path in unique if path.is_file()), "recovered_label_h5_bytes_read": 0, "original_source_trajectory_h5_bytes_read": 0, "part_bi4_bytes_read": 0, "solver_started": False, "cfd_or_model_run": False},
        "deferred_h5_bindings": {"recovered_label_h5": {"path": binding["output_path"], "sha256": binding["output_sha256"], "content_read_by_this_worker": False}, "original_trajectory_h5": {"path": binding["trajectory_path"], "sha256": binding["trajectory_sha256"], "content_read_by_this_worker": False}},
        "claim_boundary": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "legal_flux": "UNKNOWN", "qualification_credit": "none"},
        "missing_guard_sources": missing,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--report", type=Path, required=True); run.add_argument("--receipt", type=Path, required=True); run.add_argument("--output", type=Path, required=True)
    prep = sub.add_parser("make-request")
    prep.add_argument("--report", type=Path, required=True); prep.add_argument("--receipt", type=Path, required=True); prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--worktree-root", type=Path, help="legacy alias for both runtime and worker roots")
    prep.add_argument("--runtime-root", type=Path)
    prep.add_argument("--worker-root", type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        build(args.report, args.receipt, args.output)
    else:
        make_request(args.report, args.receipt, args.output, args.worktree_root,
                     runtime_root=args.runtime_root, worker_root=args.worker_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

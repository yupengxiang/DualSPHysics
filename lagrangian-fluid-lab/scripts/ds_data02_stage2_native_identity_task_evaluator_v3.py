#!/usr/bin/env python3
"""Strict source-row join for the root071 finite native-motive interface.

This forward evaluator preserves the v2 interface and adds an exact ordered
join against root070 ``native_identity_records``.  It rejects key-set swaps,
including count-preserving same-family case-key swaps, as well as motive/code
mutations.  It remains a metadata integrity check with no scientific score.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Any


_V2_PATH = Path(__file__).with_name("ds_data02_stage2_native_identity_task_evaluator_v2.py")
_SPEC = importlib.util.spec_from_file_location("native_identity_task_evaluator_v2_dependency", _V2_PATH)
assert _SPEC and _SPEC.loader
_V2 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_V2)

EvaluationError = _V2.EvaluationError
CAUSE_BY_MOTIVE = _V2.CAUSE_BY_MOTIVE
FINITE_TASKS = _V2.FINITE_TASKS
EXPECTED_FAMILY_MOTIVE = _V2.EXPECTED_FAMILY_MOTIVE
bind = _V2.bind
read_object = _V2.read_object
sha256 = _V2.sha256
validate_native_motive_records = _V2.validate_native_motive_records
_unknown_boundary = _V2._unknown_boundary
_validate_task_receipt = _V2._validate_task_receipt
write_atomic = _V2.write_atomic

TASK_INPUT_SCHEMA = "ds02.stage2.native-identity-task-input.v1"
EVALUATION_SCHEMA = "ds02.stage2.native-identity-task-interface-evaluation.v3"


def join_source_records(task_records: list[dict[str, Any]], source_records: list[dict[str, Any]], *, expected_count: int = 1328) -> dict[str, Any]:
    """Require exact ordered key and cause agreement with the source rows."""
    if not isinstance(task_records, list) or not isinstance(source_records, list) or len(task_records) != expected_count or len(source_records) != expected_count:
        raise EvaluationError("task/source record counts differ")
    task_keys = [(row.get("case_key"), row.get("idp")) for row in task_records]
    source_keys = [(row.get("case_key"), row.get("idp")) for row in source_records]
    if len(set(source_keys)) != expected_count:
        raise EvaluationError("source rows contain duplicate case-qualified keys")
    if len(set(task_keys)) != expected_count:
        raise EvaluationError("task rows contain duplicate case-qualified keys")
    if set(task_keys) != set(source_keys):
        raise EvaluationError("task/source case-qualified key sets differ")
    if task_keys != source_keys:
        raise EvaluationError("task/source case-qualified row order differs; count-preserving case-key swap rejected")
    for index, (task_row, source_row) in enumerate(zip(task_records, source_records)):
        identity = (task_row.get("case_key"), task_row.get("idp"))
        for field in ("case_key", "idp", "family_id", "native_motive", "native_motive_code", "numerical_cause"):
            if task_row.get(field) != source_row.get(field):
                raise EvaluationError(f"task/source {field} mismatch at row {index}: {identity}")
    return {
        "joined_row_count": expected_count,
        "ordered_case_qualified_join": True,
        "exact_case_qualified_key_set": True,
        "family_motive_code_cause_join": True,
    }


def evaluate(task_input_path: Path, task_receipt_path: Path, expected_subset_path: Path, expected_subset_sha256: str) -> dict[str, Any]:
    task_input, task_binding = read_object(task_input_path, "root071 task input")
    task_receipt_binding = _validate_task_receipt(task_receipt_path, task_input_path)
    if task_input.get("schema") != TASK_INPUT_SCHEMA or task_input.get("status") != "ELIGIBLE_SOURCE_CLOSED_METADATA_TASK_ONLY":
        raise EvaluationError("root071 task input schema/status differs")
    task = task_input.get("task")
    if task not in FINITE_TASKS:
        raise EvaluationError(f"unsupported or UNKNOWN task cannot be evaluated: {task!r}")
    if task != "native_motive":
        raise EvaluationError("this actual v3 interface is scoped to native_motive")
    _unknown_boundary(task_input.get("qualification", {}))
    expected_subset = Path(expected_subset_path).expanduser().resolve()
    subset_binding = bind(expected_subset, "root070 source subset")
    if subset_binding["sha256"] != expected_subset_sha256:
        raise EvaluationError("root070 source subset SHA differs from request-bound actual product")
    declared_subset = task_input.get("source_subset")
    if not isinstance(declared_subset, dict) or declared_subset.get("path") != subset_binding["path"] or declared_subset.get("sha256") != subset_binding["sha256"] or declared_subset.get("bytes") != subset_binding["bytes"]:
        raise EvaluationError("root071 task input does not bind the exact root070 source subset")
    subset_report, _ = read_object(expected_subset, "root070 source subset")
    if subset_report.get("schema") != "ds02.stage2.native-source-identity-development-subset.v2" or subset_report.get("status") != "PASS_FORWARD_STATS_CORRECTION_ORIGINAL_V1_PRESERVED":
        raise EvaluationError("root070 source subset schema/status differs")
    source_records = subset_report.get("native_identity_records")
    task_records = task_input.get("records")
    source_integrity = validate_native_motive_records(source_records)
    task_integrity = validate_native_motive_records(task_records)
    if task_input.get("integrity") != task_integrity:
        raise EvaluationError("root071 task input integrity summary does not match its records")
    join_integrity = join_source_records(task_records, source_records)
    return {
        "schema": EVALUATION_SCHEMA,
        "status": "PASS_ACTUAL_SOURCE_BOUND_FINITE_TASK_INTERFACE_V3_NO_SCIENTIFIC_SCORE",
        "task": task,
        "task_input": task_binding,
        "task_receipt": task_receipt_binding,
        "source_subset": subset_binding,
        "source_integrity": source_integrity,
        "task_integrity": task_integrity,
        "source_join": join_integrity,
        "qualification": {
            "source_identity": "SOURCE_CLOSED",
            "native_numerical_cause": "SOURCE_CLOSED_MOTIVE_CODE_ONLY",
            "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN",
            "dynamical_impact": "UNKNOWN", "scientific_split_safe": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "research_score": "NOT_COMPUTED", "ranking": "NOT_COMPUTED",
        },
        "counterexample_checks": {
            "wrong_case_id": "REJECTED_BY_EXACT_ORDERED_CASE_QUALIFIED_JOIN",
            "count_preserving_case_key_swap": "REJECTED_BY_ORDERED_KEY_JOIN",
            "wrong_motive_or_code": "REJECTED_BY_SOURCE_ROW_JOIN",
            "same_family_cause_mutation": "REJECTED_BY_SOURCE_ROW_JOIN",
            "duplicate_case_qualified_id": "REJECTED",
            "global_idp_collision": "REPORTED_NOT_USED_AS_IDENTITY",
            "unsupported_physical_task": "REJECTED_AS_UNKNOWN",
        },
        "read_policy": {"root070_root071_json_opened": True, "h5_opened": False, "bi4_opened": False, "raw_partout_opened": False, "decoder_started": False, "solver_started": False, "cfd_or_model_run": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evaluate", choices=["evaluate"])
    parser.add_argument("--task-input", required=True, type=Path)
    parser.add_argument("--task-receipt", required=True, type=Path)
    parser.add_argument("--expected-subset", required=True, type=Path)
    parser.add_argument("--expected-subset-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(args.task_input, args.task_receipt, args.expected_subset, args.expected_subset_sha256)
    write_atomic(args.output, result)
    print(__import__("json").dumps({"status": result["status"], "task": result["task"], "record_count": result["source_join"]["joined_row_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

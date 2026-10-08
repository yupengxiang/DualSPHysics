#!/usr/bin/env python3
"""Evaluate the finite native-identity interface against one actual source.

This integrity evaluator binds root071 task input to the immutable root070 v2
record export by exact path, SHA, and byte count. It checks case-qualified
identity and native motive/code fields, reports the UNKNOWN boundary, and gives
no scientific score, ranking, split safety, flow, fate, or dynamics credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

TASK_INPUT_SCHEMA = "ds02.stage2.native-identity-task-input.v1"
EVALUATION_SCHEMA = "ds02.stage2.native-identity-task-interface-evaluation.v2"
FINITE_TASKS = {"native_identity", "native_motive", "source_mk", "saved_bracket_censor"}
CAUSE_BY_MOTIVE = {"position": (1, "NATIVE_PARTVTKOUT_POSITION_EXCLUSION"), "density": (2, "NATIVE_PARTVTKOUT_DENSITY_EXCLUSION"), "movement": (3, "NATIVE_PARTVTKOUT_MOVEMENT_EXCLUSION")}
EXPECTED_FAMILY_MOTIVE = {"F2:position": 1078, "F4:density": 51, "F6:position": 199}


class EvaluationError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() in {".h5", ".bi4"} or path.name.startswith("PartOut_"):
        raise EvaluationError(f"{label} points at forbidden trajectory content: {path}")
    if not path.is_file():
        raise EvaluationError(f"{label} is missing: {path}")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def read_object(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    binding = bind(path, label)
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise EvaluationError(f"{label} is not an object")
    return value, binding


def _unknown_boundary(qualification: dict[str, Any]) -> None:
    allowed = {
        "physical_fate": {"UNKNOWN"}, "legal_flux": {"UNKNOWN"},
        "continuous_event_time": {"UNKNOWN_BEYOND_SAVED_BRACKET"},
        "dynamical_impact": {"UNKNOWN"}, "scientific_split_safe": {"UNKNOWN"},
        "QI": {"UNKNOWN"}, "QN": {"UNKNOWN"}, "QE": {"UNKNOWN"},
    }
    for key, accepted in allowed.items():
        if qualification.get(key) not in accepted:
            raise EvaluationError(f"task input widens UNKNOWN boundary for {key}: {qualification.get(key)!r}")


def validate_native_motive_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(records, list) or len(records) != 1328:
        raise EvaluationError("native_motive task input must contain exactly 1328 records")
    seen: set[tuple[str, int]] = set()
    global_ids = Counter()
    family_motive = Counter()
    cause_counts = Counter()
    for row in records:
        if not isinstance(row, dict):
            raise EvaluationError("task record is not an object")
        case_key, idp, family, motive = row.get("case_key"), row.get("idp"), row.get("family_id"), row.get("native_motive")
        if not isinstance(case_key, str) or not case_key or not isinstance(idp, int):
            raise EvaluationError("task record has malformed case_key/Idp")
        identity = (case_key, idp)
        if identity in seen:
            raise EvaluationError(f"duplicate case-qualified identity: {identity}")
        seen.add(identity)
        if family not in {"F2", "F4", "F6"} or motive not in CAUSE_BY_MOTIVE:
            raise EvaluationError(f"task record has unsupported family/motive: {identity}")
        expected_code, expected_cause = CAUSE_BY_MOTIVE[motive]
        if row.get("native_motive_code") != expected_code or row.get("numerical_cause") != expected_cause:
            raise EvaluationError(f"motive/code/cause mismatch: {identity}")
        global_ids[idp] += 1
        family_motive[(family, motive)] += 1
        cause_counts[expected_cause] += 1
    actual = {f"{family}:{motive}": count for (family, motive), count in sorted(family_motive.items())}
    if actual != EXPECTED_FAMILY_MOTIVE:
        raise EvaluationError(f"native motive family counts differ: {actual}")
    return {
        "row_count": len(records), "case_qualified_unique": True,
        "global_idp_unique": len(global_ids) == len(records),
        "global_idp_collision_count": sum(count - 1 for count in global_ids.values() if count > 1),
        "family_motive_counts": actual,
        "numerical_cause_counts": dict(sorted(cause_counts.items())),
    }


def _validate_task_receipt(receipt_path: Path, task_input_path: Path) -> dict[str, Any]:
    receipt, binding = read_object(receipt_path, "root071 task receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise EvaluationError("root071 task receipt is not completed code 0")
    if Path(str(receipt.get("output_root", ""))).expanduser().resolve() != Path(task_input_path).expanduser().resolve().parent:
        raise EvaluationError("root071 task input is outside its completed receipt output root")
    guard = receipt.get("terminal_storage_guard", {})
    if guard.get("status") != "passed" or guard.get("actual_bytes") != receipt.get("bytes"):
        raise EvaluationError("root071 task receipt is not fixed-point storage guarded")
    if receipt.get("source_preflight", {}).get("status") != "PASS_AFTER_RESERVATION":
        raise EvaluationError("root071 task receipt lacks reservation-before-read preflight")
    if receipt.get("model_invoked") is not False or receipt.get("cfd_invoked") is not False:
        raise EvaluationError("root071 task receipt invokes forbidden model/CFD")
    return binding


def evaluate(task_input_path: Path, task_receipt_path: Path, expected_subset_path: Path, expected_subset_sha256: str) -> dict[str, Any]:
    task_input, task_binding = read_object(task_input_path, "root071 task input")
    task_receipt_binding = _validate_task_receipt(task_receipt_path, task_input_path)
    if task_input.get("schema") != TASK_INPUT_SCHEMA or task_input.get("status") != "ELIGIBLE_SOURCE_CLOSED_METADATA_TASK_ONLY":
        raise EvaluationError("root071 task input schema/status differs")
    task = task_input.get("task")
    if task not in FINITE_TASKS:
        raise EvaluationError(f"unsupported or UNKNOWN task cannot be evaluated: {task!r}")
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
    if task != "native_motive":
        raise EvaluationError("this actual interface request is scoped to native_motive; other finite tasks require a separately bound input")
    records = task_input.get("records")
    integrity = validate_native_motive_records(records)
    if task_input.get("integrity") != integrity:
        raise EvaluationError("root071 task input integrity summary does not match its records")
    return {
        "schema": EVALUATION_SCHEMA,
        "status": "PASS_ACTUAL_SOURCE_BOUND_FINITE_TASK_INTERFACE_NO_SCIENTIFIC_SCORE",
        "task": task, "task_input": task_binding, "task_receipt": task_receipt_binding, "source_subset": subset_binding,
        "integrity": integrity,
        "qualification": {
            "source_identity": "SOURCE_CLOSED", "native_numerical_cause": "SOURCE_CLOSED_MOTIVE_CODE_ONLY",
            "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN",
            "dynamical_impact": "UNKNOWN", "scientific_split_safe": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "research_score": "NOT_COMPUTED", "ranking": "NOT_COMPUTED",
        },
        "counterexample_checks": {
            "wrong_case_id": "REJECTED_BY_CASE_QUALIFIED_ID_CHECK", "wrong_motive_or_code": "REJECTED_BY_MOTIVE_CODE_CAUSE_CHECK",
            "duplicate_case_qualified_id": "REJECTED", "global_idp_collision": "REPORTED_NOT_USED_AS_IDENTITY",
            "unsupported_physical_task": "REJECTED_AS_UNKNOWN",
        },
        "read_policy": {"root070_and_root071_json_opened": True, "h5_opened": False, "bi4_opened": False, "raw_partout_opened": False, "decoder_started": False, "solver_started": False, "cfd_or_model_run": False},
    }


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise EvaluationError(f"preserve existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload); stream.flush(); os.fsync(fd)
        os.replace(temp, path)
    except Exception:
        try: os.unlink(temp)
        except FileNotFoundError: pass
        raise


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
    print(json.dumps({"status": result["status"], "task": result["task"], "record_count": result["integrity"]["row_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

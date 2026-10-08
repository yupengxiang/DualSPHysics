#!/usr/bin/env python3
"""Load only finite source-identity tasks from the corrected native sidecar.

The command requires an explicit task.  Identity, native motive, source-MK
bookkeeping, and saved-bracket censoring are finite metadata tasks.  Physical
fate/flux, continuous event timing, dynamics, and scientific split safety are
deliberately rejected while their evidence is UNKNOWN; they cannot become a
default pass merely because a row has a numerical motive.
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


SUBSET_SCHEMA = "ds02.stage2.native-source-identity-development-subset.v2"
INPUT_SCHEMA = "ds02.stage2.native-identity-task-input.v1"
KNOWN_TASKS = {
    "native_identity": "case-qualified identity and source binding",
    "native_motive": "native numerical motive/code only",
    "source_mk": "source MK/type bookkeeping",
    "saved_bracket_censor": "saved first-missing bracket censoring",
    "physical_fate": "physical fate",
    "legal_flux": "legal flux/outflow",
    "continuous_event": "continuous event time",
    "scientific_split": "scientific split safety",
}
FINITE_TASKS = {"native_identity", "native_motive", "source_mk", "saved_bracket_censor"}
UNKNOWN_FIELDS = ("physical_fate", "legal_outflow_or_flux", "continuous_event_time", "dynamical_impact", "QI", "QN", "QE", "scientific_split_safe")
CAUSE_BY_MOTIVE = {
    "position": (1, "NATIVE_PARTVTKOUT_POSITION_EXCLUSION"),
    "density": (2, "NATIVE_PARTVTKOUT_DENSITY_EXCLUSION"),
    "movement": (3, "NATIVE_PARTVTKOUT_MOVEMENT_EXCLUSION"),
}


class LoaderError(ValueError):
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
        raise LoaderError(f"{label} points at forbidden trajectory content: {path}")
    if not path.is_file():
        raise LoaderError(f"{label} is missing: {path}")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def read_subset(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(path).expanduser().resolve()
    binding = bind(path, "corrected native subset")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LoaderError("corrected native subset is invalid JSON") from exc
    if not isinstance(report, dict):
        raise LoaderError("corrected native subset is not an object")
    if report.get("schema") != SUBSET_SCHEMA or report.get("status") != "PASS_FORWARD_STATS_CORRECTION_ORIGINAL_V1_PRESERVED":
        raise LoaderError("corrected subset schema/status is not source-bound v2")
    boundary = report.get("claim_boundary", {})
    expected_unknown = {
        "physical_fate": {"UNKNOWN", "UNKNOWN_NOT_PROVEN"},
        "legal_outflow_or_flux": {"UNKNOWN"},
        "continuous_event_time": {"UNKNOWN beyond saved first-missing brackets"},
        "dynamical_impact": {"UNKNOWN"},
        "QI": {"UNKNOWN"},
        "QN": {"UNKNOWN"},
        "QE": {"UNKNOWN"},
        "scientific_split_safe": {"UNKNOWN"},
    }
    for key, allowed in expected_unknown.items():
        if boundary.get(key) not in allowed:
            raise LoaderError(f"subset boundary widens {key}: {boundary.get(key)!r}")
    correction = report.get("correction", {})
    if correction.get("original_v1_bytes_preserved") is not True or correction.get("actual_row_count") != 1328:
        raise LoaderError("subset correction provenance is incomplete")
    return report, binding


def validate_records(records: list[dict[str, Any]], *, expected_count: int = 1328) -> dict[str, Any]:
    if not isinstance(records, list) or len(records) != expected_count:
        raise LoaderError(f"native identity record count differs: {len(records) if isinstance(records, list) else type(records).__name__}")
    seen: set[tuple[str, int]] = set()
    global_ids = Counter()
    family_motive = Counter()
    cause_counts = Counter()
    for row in records:
        if not isinstance(row, dict):
            raise LoaderError("native identity row is not an object")
        case_key = row.get("case_key")
        idp = row.get("idp")
        if not isinstance(case_key, str) or not case_key or not isinstance(idp, int):
            raise LoaderError("case_key/Idp identity is not typed")
        identity = (case_key, idp)
        if identity in seen:
            raise LoaderError(f"duplicate case-qualified identity: {identity}")
        seen.add(identity)
        global_ids[idp] += 1
        family = row.get("family_id")
        if family not in {"F2", "F4", "F6"}:
            raise LoaderError(f"unexpected family for {identity}: {family!r}")
        mk = row.get("mk")
        if not isinstance(mk, int) or mk < 1:
            raise LoaderError(f"invalid source MK for {identity}: {mk!r}")
        motive = row.get("native_motive")
        code_cause = CAUSE_BY_MOTIVE.get(motive)
        if code_cause is None or row.get("native_motive_code") != code_cause[0] or row.get("numerical_cause") != code_cause[1]:
            raise LoaderError(f"native motive/code/cause mismatch for {identity}")
        bracket = row.get("first_missing_bracket_s")
        if not isinstance(bracket, list) or len(bracket) != 2 or not all(isinstance(value, (int, float)) for value in bracket) or not bracket[0] < bracket[1]:
            raise LoaderError(f"invalid saved bracket for {identity}")
        family_motive[(family, motive)] += 1
        cause_counts[row["numerical_cause"]] += 1
    return {
        "row_count": len(records),
        "case_qualified_unique": True,
        "global_idp_unique": len(global_ids) == len(records),
        "global_idp_collision_count": sum(count - 1 for count in global_ids.values() if count > 1),
        "family_motive_counts": {f"{family}:{motive}": count for (family, motive), count in sorted(family_motive.items())},
        "numerical_cause_counts": dict(sorted(cause_counts.items())),
    }


def task_records(records: list[dict[str, Any]], task: str) -> list[dict[str, Any]]:
    if task == "native_identity":
        fields = ("case_key", "family_id", "physical_case_id", "idp", "type")
    elif task == "native_motive":
        fields = ("case_key", "family_id", "idp", "native_motive", "native_motive_code", "numerical_cause")
    elif task == "source_mk":
        fields = ("case_key", "family_id", "idp", "mk", "type", "initial_mass_kg")
    elif task == "saved_bracket_censor":
        fields = ("case_key", "family_id", "idp", "mk", "first_missing_bracket_s")
    else:
        raise LoaderError(f"task is not an eligible finite identity task: {task}")
    return [{field: row.get(field) for field in fields} for row in records]


def load_task(subset_path: Path, task: str) -> dict[str, Any]:
    if task not in KNOWN_TASKS:
        raise LoaderError(f"unknown task: {task}")
    if task not in FINITE_TASKS:
        raise LoaderError(f"{task} remains UNKNOWN and cannot be loaded as an eligible task")
    report, subset_binding = read_subset(subset_path)
    records = report.get("native_identity_records")
    integrity = validate_records(records)
    selected = task_records(records, task)
    return {
        "schema": INPUT_SCHEMA,
        "status": "ELIGIBLE_SOURCE_CLOSED_METADATA_TASK_ONLY",
        "task": task,
        "task_description": KNOWN_TASKS[task],
        "source_subset": subset_binding,
        "source_row_count": len(records),
        "integrity": integrity,
        "records": selected,
        "qualification": {
            "source_identity": "SOURCE_CLOSED",
            "native_numerical_cause": "SOURCE_CLOSED_MOTIVE_CODE_ONLY",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "continuous_event_time": "UNKNOWN_BEYOND_SAVED_BRACKET",
            "dynamical_impact": "UNKNOWN",
            "scientific_split_safe": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "qualification_credit": "NONE",
        },
        "counterexample_policy": {
            "case_qualified_identity_required": True,
            "global_idp_collision_is_error": False,
            "global_idp_collision_must_be_reported": True,
            "motive_code_mismatch": "REJECT",
            "duplicate_case_qualified_id": "REJECT",
            "unknown_physical_or_continuous_fields": "REJECT_AS_UNAVAILABLE_TASK",
        },
        "read_policy": {"corrected_json_opened": True, "h5_opened": False, "bi4_opened": False, "raw_partout_opened": False, "solver_started": False, "cfd_or_model_run": False},
    }


def evaluate_task_input(path: Path) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    binding = bind(path, "task input")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LoaderError("task input is invalid JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != INPUT_SCHEMA or value.get("status") != "ELIGIBLE_SOURCE_CLOSED_METADATA_TASK_ONLY":
        raise LoaderError("task input schema/status differs")
    task = value.get("task")
    if task not in FINITE_TASKS:
        raise LoaderError("task input is not a finite eligible task")
    records = value.get("records")
    if not isinstance(records, list) or not records:
        raise LoaderError("task input has no records")
    qualification = value.get("qualification", {})
    if any(qualification.get(key) not in {"UNKNOWN", "UNKNOWN_BEYOND_SAVED_BRACKET", "NONE", "SOURCE_CLOSED", "SOURCE_CLOSED_MOTIVE_CODE_ONLY"} for key in ("physical_fate", "legal_flux", "continuous_event_time", "dynamical_impact", "scientific_split_safe", "QI", "QN", "QE")):
        raise LoaderError("task input widened an unknown qualification")
    return {
        "schema": "ds02.stage2.native-identity-task-evaluation.v1",
        "status": "PASS_FINITE_SOURCE_IDENTITY_TASK_INTEGRITY_ONLY",
        "task": task,
        "task_input": binding,
        "record_count": len(records),
        "source_subset": value.get("source_subset"),
        "qualification_credit": "NONE",
        "physical_fate": "UNKNOWN",
        "legal_flux": "UNKNOWN",
        "continuous_event_time": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "scientific_split_safe": "UNKNOWN",
    }


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise LoaderError(f"preserve existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except Exception:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    load = sub.add_parser("load")
    load.add_argument("--subset-report", required=True, type=Path)
    load.add_argument("--task", required=True, choices=tuple(KNOWN_TASKS))
    load.add_argument("--output", required=True, type=Path)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--task-input", required=True, type=Path)
    evaluate.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = load_task(args.subset_report, args.task) if args.command == "load" else evaluate_task_input(args.task_input)
    write_atomic(args.output, result)
    print(json.dumps({"status": result["status"], "task": result["task"], "record_count": result.get("source_row_count", result.get("record_count"))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

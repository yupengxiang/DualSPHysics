#!/usr/bin/env python3
"""Read-only formal-readiness audit for the Core phase/evaluation boundary.

The audit joins the existing phase plan, formal admission observation, and
Core completion status.  It checks the fixed evaluator penalty with the live
scoring function, but never opens a trajectory, emits a job specification, or
mutates the registry/ledger.  A readiness report is an observation of the
current gate; it cannot promote a family, a run, or a material case-run.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

# Support both ``python -m scripts.core_formal_readiness`` and direct execution
# from a worker directory outside the repository.  All input paths remain
# rooted at the caller's explicit ``--data-root``; this only makes the bundled
# Python modules importable.
LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_campaign import completion, expected_runs
from scripts.core_evaluation import PROTOCOL, score_case


SCHEMA = "core.formal_readiness.v1"
PHASE_PLAN_SCHEMA = "core.phase_plan.v1"
ADMISSION_SCHEMA = "core.formal_admission_audit.v1"
PHASE_ORDER = ("verify", "inspect", "train", "rollout", "evaluate", "reproduce")
REQUIRED_T1_FAMILIES = 3
VALIDATION_CASES_PER_FAMILY = 4
REQUIRED_VALIDATION_CASES = 12
REQUIRED_FORMAL_RUNS = 9
REQUIRED_MATERIAL_CASE_RUNS = 288


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


def _phase_observation(payload: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]:
    denominator = payload.get("denominator")
    if not isinstance(denominator, Mapping):
        denominator = {}
    cases = denominator.get("cases")
    cases = cases if isinstance(cases, Mapping) else {}
    case_ids = denominator.get("case_ids")
    expected_by_case = denominator.get("expected_frames_by_case")
    trajectory_by_case = denominator.get("trajectory_frames_by_case")

    def _positive_int(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    case_id_rows_are_unique = (
        isinstance(case_ids, list)
        and all(isinstance(case_id, str) and bool(case_id) for case_id in case_ids)
        and len(case_ids) == len(set(case_ids))
    )
    case_id_set = set(case_ids) if case_id_rows_are_unique else set()
    case_key_set = set(cases) if all(isinstance(case_id, str) for case_id in cases) else set()
    registered_count_consistent = (
        isinstance(denominator.get("registered_case_count"), int)
        and not isinstance(denominator.get("registered_case_count"), bool)
        and denominator.get("registered_case_count") == len(cases)
        and denominator.get("registered_case_count", 0) > 0
    )
    expected_map_shape = (
        isinstance(expected_by_case, Mapping)
        and set(expected_by_case) == case_key_set
        and all(_positive_int(value) for value in expected_by_case.values())
    )
    trajectory_map_shape = (
        isinstance(trajectory_by_case, Mapping)
        and set(trajectory_by_case) == case_key_set
        and all(_positive_int(value) for value in trajectory_by_case.values())
    )
    denominator_row_integrity = bool(
        registered_count_consistent
        and case_id_rows_are_unique
        and case_id_set == case_key_set
        and expected_map_shape
        and trajectory_map_shape
        and isinstance(denominator.get("missing_denominator_case_ids"), list)
        and not denominator["missing_denominator_case_ids"]
        and all(
            isinstance(row, Mapping)
            and _positive_int(row.get("expected_frames"))
            and _positive_int(row.get("trajectory_frames"))
            and row["trajectory_frames"] == row["expected_frames"] + 1
            and row["expected_frames"] == expected_by_case[case_id]
            and row["trajectory_frames"] == trajectory_by_case[case_id]
            for case_id, row in cases.items()
        )
    )
    split_counts = Counter(
        str(row.get("split"))
        for row in cases.values()
        if isinstance(row, Mapping) and row.get("split") is not None
    )
    expected_values = sorted({
        int(row["expected_frames"])
        for row in cases.values()
        if isinstance(row, Mapping) and _positive_int(row.get("expected_frames"))
    })
    phases = payload.get("phases")
    phases = phases if isinstance(phases, list) else []
    phase_names = [row.get("name") for row in phases if isinstance(row, Mapping)]
    phase_future_state_flags = {
        str(row.get("name")): row.get("future_state_inputs")
        for row in phases
        if isinstance(row, Mapping)
    }
    guards = payload.get("guards")
    guards = guards if isinstance(guards, Mapping) else {}
    formal_readiness = payload.get("formal_readiness")
    formal_readiness = formal_readiness if isinstance(formal_readiness, Mapping) else {}
    contract_checks = {
        "schema": payload.get("schema") == PHASE_PLAN_SCHEMA,
        "passed": payload.get("passed") is True,
        "phase_order": tuple(payload.get("phase_order", ())) == PHASE_ORDER,
        "phase_rows": tuple(phase_names) == PHASE_ORDER,
        "all_phases_forbid_future_state": (
            phase_future_state_flags == {name: False for name in PHASE_ORDER}
        ),
        "denominator_policy_present": (
            isinstance(denominator.get("policy"), str)
            and "registered" in denominator["policy"].lower()
            and "failure" in denominator["policy"].lower()
        ),
        "missing_execution_preserves_expected_frames": (
            denominator.get("missing_execution_preserves_expected_frames") is True
        ),
        "denominator_row_integrity": denominator_row_integrity,
        "no_future_state_inputs": (
            guards.get("future_state_inputs") is False
            and guards.get("predictor_future_state_inputs") is False
        ),
        "formal_training_not_started": (
            guards.get("formal_training_started") is False
            and formal_readiness.get("formal_training") is False
            and formal_readiness.get("formal_job_count") == 0
            and formal_readiness.get("required_formal_job_count") == REQUIRED_FORMAL_RUNS
        ),
        "no_registry_or_ledger_write": (
            guards.get("registry_written") is False
            and guards.get("ledger_written") is False
        ),
    }
    return {
        "artifact": dict(reference),
        "schema": payload.get("schema"),
        "passed": payload.get("passed"),
        "phase_order": list(payload.get("phase_order", ())),
        "registered_case_count": denominator.get("registered_case_count"),
        "split_counts": dict(sorted(split_counts.items())),
        "expected_frame_values": expected_values,
        "denominator_row_integrity": denominator_row_integrity,
        "missing_denominator_case_ids": list(denominator.get("missing_denominator_case_ids", ())),
        "missing_execution_preserves_expected_frames": denominator.get(
            "missing_execution_preserves_expected_frames"),
        "trajectory_state_frames_read": guards.get("trajectory_state_frames_read"),
        "contract_checks": contract_checks,
        "contract_passed": all(contract_checks.values()),
    }


def _admission_observation(payload: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]:
    schema = payload.get("schema")
    if type(schema) is not str or schema != ADMISSION_SCHEMA:
        # This is only a schema discriminator, not producer authentication.
        # Reject unknown/synthetic schemas before looking at any gate-shaped
        # fields so diagnostic objects cannot inflate the readiness summary.
        return {
            "artifact": dict(reference),
            "schema": schema,
            "schema_valid": False,
            "status": "invalid_schema",
            "formal_admission": False,
            "formal_job_count": None,
            "required_formal_job_count": None,
            "t1_families": [],
            "t1_family_count": 0,
            "validation_counts": {},
            "validation_case_count": 0,
            "protocol": {},
            "capacity_evidence": {},
            "upstream_blockers": [],
        }

    summary = payload.get("family_summary")
    summary = summary if isinstance(summary, Mapping) else {}
    t1_families = summary.get("t1_families")
    if isinstance(t1_families, Mapping):
        t1_names = sorted(str(name) for name, value in t1_families.items() if value is True)
    elif isinstance(t1_families, list):
        t1_names = sorted(str(name) for name in t1_families)
    else:
        t1_names = []
    validation_counts = summary.get("validation_counts")
    if not isinstance(validation_counts, Mapping):
        validation_counts = {}
    validation_counts = {
        str(name): int(value) for name, value in validation_counts.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }
    protocol = payload.get("formal_protocol")
    protocol = protocol if isinstance(protocol, Mapping) else {}
    capacity_evidence = payload.get("capacity_evidence")
    capacity_evidence = dict(capacity_evidence) if isinstance(capacity_evidence, Mapping) else {}
    return {
        "artifact": dict(reference),
        "schema": schema,
        "schema_valid": True,
        "status": payload.get("status"),
        "formal_admission": payload.get("formal_admission"),
        "formal_job_count": payload.get("formal_job_count"),
        "required_formal_job_count": payload.get("required_formal_job_count"),
        "t1_families": t1_names,
        "t1_family_count": len(t1_names),
        "validation_counts": dict(sorted(validation_counts.items())),
        "validation_case_count": sum(validation_counts.values()),
        "protocol": {
            "models": list(protocol.get("models", ())),
            "seeds": list(protocol.get("seeds", ())),
            "model_seed_product_count": protocol.get("model_seed_product_count"),
            "validation_cases_required": protocol.get("validation_cases_required"),
            "updates": protocol.get("updates"),
            "test_included": protocol.get("test_included"),
        },
        # Preserve the admission auditor's already hash-bound capacity
        # observation so the source-closure/root-admission layers can require
        # evidence rather than infer readiness from a missing blocker code.
        "capacity_evidence": capacity_evidence,
        "upstream_blockers": [
            item.get("code") for item in payload.get("blockers", ())
            if isinstance(item, Mapping) and item.get("code")
        ],
    }


def _evaluator_observation() -> dict[str, Any]:
    expected_frames = 3
    failure = score_case(
        [math.nan] * expected_frames,
        [math.nan] * expected_frames,
        expected_frames=expected_frames,
        length_m=1.0,
        speed_mps=1.0,
        executed=False,
        failure_category="rollout_setup_error",
    )
    required_protocol = {
        "case_denominator": "all registered future frames, excluding initial state",
        "missing_failed_nonfinite_frame_score": 1.0,
        "selection_split": "validation",
    }
    protocol_checks = {
        key: PROTOCOL.get(key) == value for key, value in required_protocol.items()
    }
    penalty_checks = {
        "selection_score_is_unit_penalty": failure["selection_score"] == 1.0,
        "finite_prefix_is_zero": failure["finite_prefix_frames"] == 0,
        "raw_coverage_is_zero": failure["raw_error_coverage"] == 0.0,
        "first_failure_frame_is_one": failure["first_failure_frame"] == 1,
        "case_is_incomplete": failure["complete"] is False,
        "registered_denominator_is_retained": failure["expected_frames"] == expected_frames,
    }
    return {
        "schema": PROTOCOL.get("schema"),
        "protocol": {
            key: PROTOCOL.get(key)
            for key in required_protocol
        },
        "failure_probe": failure,
        "protocol_checks": protocol_checks,
        "penalty_checks": penalty_checks,
        "contract_passed": all(protocol_checks.values()) and all(penalty_checks.values()),
    }


def build_readiness(*, data_root: str | Path, phase_plan: str | Path,
                    admission_audit: str | Path,
                    registry: str | Path | None = None,
                    record_id: str = "core-formal-readiness-audit-20260921") -> dict[str, Any]:
    """Build a portable read-only formal-readiness observation."""
    root = Path(data_root).expanduser().resolve()
    phase_payload, _, phase_reference = _load_json(phase_plan, root=root, role="phase plan")
    admission_payload, _, admission_reference = _load_json(
        admission_audit, root=root, role="formal admission audit")
    registry_value = registry if registry is not None else root / "campaigns/core-v1/registry.json"
    registry_payload, _, registry_reference = _load_json(
        registry_value, root=root, role="Core registry")
    phase = _phase_observation(phase_payload, phase_reference)
    admission = _admission_observation(admission_payload, admission_reference)
    evaluator = _evaluator_observation()
    core_status = completion(registry_payload, root)
    source_paths = {
        Path(__file__).resolve(),
        Path(completion.__code__.co_filename).resolve(),
        Path(score_case.__code__.co_filename).resolve(),
    }

    expected = list(expected_runs())
    observed_runs = sorted(str(run) for run in core_status.get("training_runs", ()))
    missing_runs = sorted(set(expected) - set(observed_runs))
    t1_families = sorted(str(name) for name in core_status.get("t1_families", ()))
    validation_case_count = admission["validation_case_count"]
    material_missing = int(core_status.get("missing_material_case_runs", REQUIRED_MATERIAL_CASE_RUNS))
    material_observed = max(0, REQUIRED_MATERIAL_CASE_RUNS - material_missing)
    formal_job_count = admission.get("formal_job_count")

    blockers: list[dict[str, Any]] = []

    def blocker(code: str, message: str, observed: Any, required: Any, *, scope: str = "formal") -> None:
        blockers.append({"code": code, "message": message, "observed": observed,
                         "required": required, "scope": scope})

    if not admission["schema_valid"]:
        blocker("ADMISSION_SCHEMA", "formal admission audit schema is not accepted",
                admission["schema"], ADMISSION_SCHEMA, scope="contract")
    if admission["t1_family_count"] < REQUIRED_T1_FAMILIES:
        blocker("THIRD_T1_FAMILY", "formal admission needs three distinct T1 families",
                admission["t1_family_count"], REQUIRED_T1_FAMILIES)
    if validation_case_count < REQUIRED_VALIDATION_CASES:
        blocker("VALIDATION_DENOMINATOR", "formal evaluator needs twelve validation cases",
                validation_case_count, REQUIRED_VALIDATION_CASES)
    if len(observed_runs) < REQUIRED_FORMAL_RUNS:
        blocker("FORMAL_RUN_DENOMINATOR", "formal training requires nine completed model/seed runs",
                len(observed_runs), REQUIRED_FORMAL_RUNS)
    if material_missing > 0:
        blocker("MATERIAL_CASE_RUN_DENOMINATOR", "Core retains a 288 case-run material target",
                material_observed, REQUIRED_MATERIAL_CASE_RUNS)
    if not phase["contract_passed"]:
        blocker("PHASE_PLAN_CONTRACT", "phase-plan denominator or causal guards failed",
                phase["contract_checks"], True, scope="contract")
    if not evaluator["contract_passed"]:
        blocker("EVALUATOR_DENOMINATOR_CONTRACT",
                "evaluator failure scoring does not retain the registered denominator",
                evaluator["penalty_checks"], True, scope="contract")
    if t1_families != admission["t1_families"]:
        blocker("STATUS_FAMILY_CROSSCHECK",
                "Core completion status and formal admission audit disagree on T1 families",
                {"completion": t1_families, "admission": admission["t1_families"]},
                admission["t1_families"], scope="contract")
    if formal_job_count != 0:
        blocker("FORMAL_JOB_EMISSION", "readiness audit must observe zero emitted formal jobs",
                formal_job_count, 0, scope="execution")

    checks = {
        "phase_plan_denominator_contract": phase["contract_passed"],
        "evaluator_failure_penalty_contract": evaluator["contract_passed"],
        "third_t1_family": admission["t1_family_count"] >= REQUIRED_T1_FAMILIES,
        "validation_denominator": validation_case_count >= REQUIRED_VALIDATION_CASES,
        "formal_run_denominator": len(observed_runs) >= REQUIRED_FORMAL_RUNS,
        "material_case_run_denominator": material_missing == 0,
        "completion_status": core_status.get("can_finalize") is True,
        "upstream_admission": admission.get("formal_admission") is True,
    }
    return {
        "schema": SCHEMA,
        "record_id": record_id,
        "status": "ready" if all(checks.values()) and not blockers else "blocked",
        "formal_admission": False,
        "formal_training": False,
        "formal_job_count": 0,
        "required_formal_job_count": REQUIRED_FORMAL_RUNS,
        "phase_plan": phase,
        "admission_audit": admission,
        "core_status": {
            "can_finalize": core_status.get("can_finalize"),
            "checks": core_status.get("checks", {}),
            "t1_families": t1_families,
            "macro_t2_families": sorted(str(name) for name in core_status.get("macro_t2_families", ())),
            "training_runs": observed_runs,
            "missing_t1_case_runs": core_status.get("missing_t1_case_runs"),
            "missing_material_case_runs": material_missing,
            "missing_registered_material_case_runs": core_status.get(
                "missing_registered_material_case_runs"),
            "unregistered_t1_case_runs": core_status.get("unregistered_t1_case_runs"),
            "unregistered_material_case_runs": core_status.get("unregistered_material_case_runs"),
            "issues": core_status.get("issues", []),
            "registry": registry_reference,
        },
        "formal_protocol": {
            "required_t1_families": REQUIRED_T1_FAMILIES,
            "validation_cases_per_family": VALIDATION_CASES_PER_FAMILY,
            "required_validation_cases": REQUIRED_VALIDATION_CASES,
            "required_formal_runs": REQUIRED_FORMAL_RUNS,
            "expected_run_ids": expected,
            "observed_run_ids": observed_runs,
            "missing_run_ids": missing_runs,
            "required_material_case_runs": REQUIRED_MATERIAL_CASE_RUNS,
            "observed_material_case_runs": material_observed,
            "missing_material_case_runs": material_missing,
        },
        "evaluator_contract": evaluator,
        "source_bindings": [
            _reference(path, root) for path in sorted(source_paths, key=str)
        ],
        "checks": checks,
        "blockers": sorted(blockers, key=lambda item: (item["scope"], item["code"])),
        "upstream_admission_blockers": admission["upstream_blockers"],
        "execution_constraints": {
            "read_only": True,
            "trajectory_files_opened": False,
            "trajectory_state_frames_read": 0,
            "predictor_future_state_inputs": False,
            "optimizer_started": False,
            "gpu_started": False,
            "solver_started": False,
            "formal_runs_started": 0,
            "registry_written": False,
            "ledger_written": False,
            "formal_specs_written": False,
        },
        "admission_next_dependency": (
            "qualify a third independent T1 family, provide four validation cases for it, "
            "complete all nine formal runs, and retain the 288 material case-run target "
            "until two macro T2 families supply it; then rerun this audit and the planner"
        ),
    }


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
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
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(f"{sha256_file(source_path)}  {source_path.name}\n", encoding="utf-8")
    temporary.replace(target)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--phase-plan", type=Path, required=True)
    parser.add_argument("--admission-audit", type=Path, required=True)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sha256-output", type=Path)
    parser.add_argument("--record-id", default="core-formal-readiness-audit-20260921",
                        help="identity for this readiness observation")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_readiness(
        data_root=args.data_root,
        phase_plan=args.phase_plan,
        admission_audit=args.admission_audit,
        registry=args.registry,
        record_id=args.record_id,
    )
    write_json(args.output, report)
    if args.sha256_output is not None:
        write_sha256(args.sha256_output, source=args.output)
    print(json.dumps({
        "status": report["status"],
        "formal_job_count": report["formal_job_count"],
        "required_formal_job_count": report["required_formal_job_count"],
        "blocker_codes": [item["code"] for item in report["blockers"]],
        "missing_material_case_runs": report["formal_protocol"]["missing_material_case_runs"],
    }, sort_keys=True))
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())

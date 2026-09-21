#!/usr/bin/env python3
"""Build and verify the read-only F6 observation-axis v4 route closure.

This audit consumes only compact JSON receipts and text reports already in the
workspace.  It intentionally has no Definition writer, GenCase/native decoder,
solver, GPU, queue, registry, ledger, or matrix-submission entry point.  The
two JSON outputs are the closure card and its hash-bound route-decision receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
CARD_OUTPUT = LAB / (
    "campaigns/core-v1/cfd/f6-observation-axis-v4-third-t1-route-closed-v1.json"
)
RECEIPT_OUTPUT = LAB / (
    "campaigns/core-v1/evidence/"
    "f6-observation-axis-v4-third-t1-route-decision-receipt-v1.json"
)

PREFLIGHT_REL = (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "qualification-preflight-v4-20260921/qualification-preflight-audit.json"
)
DESIGN_REL = (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "qualification-design-20260921/design.json"
)
CANDIDATE_REL = (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "qualification-design-20260921/candidate-card.json"
)
ADMISSION_REL = (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "qualification-design-20260921/root-admission.json"
)
PLAN_REL = (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "solver-canary-v4-20260921/plan.json"
)
CANARY_REL = (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "solver-canary-v4-20260921/canary-audit.json"
)
CANARY_DIR_REL = (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "solver-canary-v4-20260921"
)
FAILED_RECEIPT_REL = CANARY_DIR_REL + "/cell-08/attempt-001/execution-receipt.json"
FAILED_FRAME_REL = CANARY_DIR_REL + "/cell-08/attempt-001/native-frame-audit.json"
FAILED_REVIEW_REL = CANARY_DIR_REL + "/cell-08/root-review.json"
COMPLETION_REL = "campaigns/core-v1/completion.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local(relative: str) -> Path:
    path = LAB / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def load(relative: str) -> dict[str, Any]:
    value = json.loads(local(relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {relative}")
    return value


def ref(relative: str, role: str) -> dict[str, Any]:
    path = local(relative)
    return {
        "path": relative,
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def _assert_zero_controls(value: dict[str, Any], *, include_native: bool = False) -> None:
    controls = value["execution_controls"]
    for key in ("solver_invoked",):
        assert controls[key] is False, (key, controls[key])
    gpu_key = "gpu_started" if "gpu_started" in controls else "gpu_invoked"
    assert controls[gpu_key] is False, (gpu_key, controls[gpu_key])
    for key in ("queue_mutation", "registry_mutation", "ledger_mutation"):
        assert controls[key] == 0, (key, controls[key])
    if "qualification_credit" in controls:
        assert controls["qualification_credit"] == 0
    else:
        assert value.get("qualification_credit", 0) == 0
    if include_native:
        for key in (
            "definition_written",
            "gencase_invoked",
            "native_decode_invoked",
            "matrix_submission",
        ):
            if key in controls:
                assert controls[key] is False, (key, controls[key])


def _audit_inputs() -> dict[str, Any]:
    preflight = load(PREFLIGHT_REL)
    design = load(DESIGN_REL)
    candidate = load(CANDIDATE_REL)
    admission = load(ADMISSION_REL)
    plan = load(PLAN_REL)
    canary = load(CANARY_REL)
    failed = load(FAILED_RECEIPT_REL)
    failed_frame = load(FAILED_FRAME_REL)
    failed_review = load(FAILED_REVIEW_REL)
    completion = load(COMPLETION_REL)

    assert preflight["status"] == "all_15_native_preflights_passed_no_solver_authorization"
    assert preflight["scope_id"] == "F6_fluid_rigid_body_physical_anchor_aligned_sampling_v3"
    assert preflight["revision_id"] == "F6_observation_axis_13plus2_v4"
    assert preflight["cell_count"] == 15
    assert preflight["matrix_complete"] is True
    assert preflight["qualification_claim"] == "none"
    assert preflight["qualification_credit"] == 0
    assert preflight["T1"] is False
    assert preflight["solver_authorized"] is False
    assert preflight["gpu_launched"] is False
    assert preflight["queue_mutation"] == 0
    assert preflight["registry_mutation"] == 0
    assert preflight["ledger_mutation"] == 0
    assert len(preflight["cells"]) == 15
    assert all(row["pass"] is True for row in preflight["cells"])

    assert design["status"] == "root_review_only_not_submitted"
    assert design["matrix_cell_count"] == 15
    assert design["qualification_claim"] == "none"
    assert design["qualification_credit"] == 0
    assert design["T1"] is False
    _assert_zero_controls(design, include_native=True)

    assert candidate["status"] == "root_review_only_not_submitted"
    assert candidate["matrix_cell_count"] == 15
    assert candidate["qualification_claim"] == "none"
    assert candidate.get("qualification_credit", 0) == 0
    assert candidate["T1"] is False
    _assert_zero_controls(candidate, include_native=True)

    assert admission["status"] == "admitted_for_fresh_native_preflight_only"
    assert admission["static_review_pass"] is True
    assert admission["cell_count"] == 15
    assert admission["qualification_claim"] == "none"
    assert admission["qualification_credit"] == 0
    assert admission["T1"] is False
    _assert_zero_controls(admission, include_native=True)
    assert admission["admission"]["solver_authorized"] is False
    assert admission["admission"]["gpu_authorized"] is False
    assert admission["admission"]["queue_authorized"] is False
    assert admission["admission"]["registry_authorized"] is False
    assert admission["admission"]["ledger_authorized"] is False
    assert admission["admission"]["matrix_authorized"] is False

    assert plan["status"] == "root_review_authorized_not_started"
    assert plan["selected_count"] == 8
    assert plan["selected_indices"] == [0, 4, 5, 8, 9, 12, 13, 14]
    assert plan["qualification_claim"] == "none"
    assert plan["qualification_credit"] == 0
    assert plan["T1"] is False
    assert plan["queue_submission"] is False
    assert plan["gpu_started"] is False
    assert plan["registry_mutation"] == 0
    assert plan["ledger_mutation"] == 0
    assert plan["matrix_submission"] is False
    assert plan["exactly_one_attempt_per_cell"] is True
    assert plan["same_input_retry"] is False

    assert canary["status"] == "all_selected_canaries_audited"
    assert canary["selected_count"] == 8
    assert canary["audited_count"] == 8
    assert canary["scientific_pass_count"] == 7
    assert canary["hard_gate_failure_counts"] == {
        "excluded_particles_zero": 1,
        "fluid_group_count_fixed": 1,
        "native_identity_fixed": 1,
    }
    assert canary["receipt_binding_failure_counts"] == {}
    assert canary["metadata_integrity_repair_count"] == 7
    assert canary["complete"] is True
    assert canary["qualification_claim"] == "none"
    assert canary["qualification_credit"] == 0
    assert canary["T1"] is False
    assert canary["next_gate"] == (
        "close_scope_or_open_new_scientific_scope_before_remaining_cells"
    )
    rows = {row["index"]: row for row in canary["rows"]}
    assert set(rows) == {0, 4, 5, 8, 9, 12, 13, 14}
    assert sum(row["scientific_pass"] for row in rows.values()) == 7
    assert rows[8]["scientific_pass"] is False
    assert rows[8]["hard_gate_pass"] is False
    assert rows[8]["hard_gate_failures"] == [
        "excluded_particles_zero",
        "native_identity_fixed",
        "fluid_group_count_fixed",
    ]
    assert rows[4]["recovered"] is True
    assert rows[4]["metadata_integrity_repaired"] is False
    repaired_indices = sorted(
        index for index, row in rows.items() if row["metadata_integrity_repaired"]
    )
    assert repaired_indices == [0, 5, 8, 9, 12, 13, 14]

    # Validate the seven repairs through each compact execution receipt.  A
    # repair may only bind an audit hash; it cannot change scientific fields or
    # invoke the solver again.
    for index in repaired_indices:
        receipt = load(rows[index]["receipt"])
        repair = receipt["metadata_integrity_repair"]
        assert repair["solver_reinvoked"] is False
        assert repair["scientific_fields_changed"] == []
        assert repair["qualification_credit"] == 0
        assert receipt["execution_controls"]["queue_mutation"] == 0
        assert receipt["execution_controls"]["registry_mutation"] == 0
        assert receipt["execution_controls"]["ledger_mutation"] == 0
        assert receipt["execution_controls"]["matrix_submission"] is False

    assert completion["t1_families"] == ["F3", "F4"]
    assert completion["checks"]["three_t1_families"] is False
    assert completion["checks"]["t1_denominator_complete"] is False

    assert failed["status"] == "solver_completed_hard_failure"
    assert failed["scope_id"] == preflight["scope_id"]
    assert failed["revision_id"] == preflight["revision_id"]
    assert failed["cell_id"] == "F6_OBS_V10_Q1P00_DP0P015_SPATIAL"
    assert failed["attempt"] == 1
    assert failed["returncode"] == 0
    assert failed["run"]["excluded_particles"] == 1
    assert failed["run"]["reported_part_files"] == 301
    assert failed["frames"]["count"] == 301
    assert failed["qualification_claim"] == "none"
    assert failed["qualification_credit"] == 0
    assert failed["T1"] is False
    assert failed["failure_policy"] == (
        "retain this exact-one receipt; no same-input retry, resume, "
        "matrix expansion or scientific credit"
    )
    assert failed["hard_gates"]["excluded_particles_zero"] is False
    assert failed["hard_gates"]["native_identity_fixed"] is False
    assert failed["hard_gates"]["fluid_group_count_fixed"] is False
    assert failed["hard_gates"]["no_fluid_outside_open_top"] is True
    assert failed["sidecar_checks"]["open_face_mass_flux_zero"] is True
    assert failed["metadata_integrity_repair"]["solver_reinvoked"] is False
    assert failed["metadata_integrity_repair"]["scientific_fields_changed"] == []

    assert failed_frame["checks"]["native_identity_fixed"] is False
    assert failed_frame["checks"]["fluid_group_count_fixed"] is False
    assert failed_frame["checks"]["no_fluid_outside_open_top"] is True
    assert failed_frame["frames"][0]["fluid_count"] == 37696
    assert failed_frame["frames"][289]["fluid_count"] == 37696
    assert failed_frame["frames"][290]["fluid_count"] == 37695
    assert failed_frame["frames"][-1]["fluid_count"] == 37695
    assert failed_frame["frames"][-1]["particle_count"] == 60148

    assert failed_review["decision"]["authorized_solver"] is True
    assert failed_review["decision"]["authorized_cpu_solver"] is True
    assert failed_review["decision"]["authorized_gpu"] is False
    assert failed_review["decision"]["authorized_queue"] is False
    assert failed_review["decision"]["authorized_registry"] is False
    assert failed_review["decision"]["authorized_ledger"] is False
    assert failed_review["decision"]["authorized_matrix"] is False
    assert failed_review["qualification_claim"] == "none"
    assert failed_review["qualification_credit"] == 0
    assert failed_review["T1"] is False

    return {
        "preflight": preflight,
        "design": design,
        "candidate": candidate,
        "admission": admission,
        "plan": plan,
        "canary": canary,
        "failed": failed,
        "failed_frame": failed_frame,
        "failed_review": failed_review,
        "completion": completion,
        "rows": rows,
        "repaired_indices": repaired_indices,
    }


def build_card() -> dict[str, Any]:
    audited = _audit_inputs()
    preflight = audited["preflight"]
    canary = audited["canary"]
    failed = audited["failed"]
    failed_frame = audited["failed_frame"]
    repaired_indices = audited["repaired_indices"]

    evidence = {
        "core_completion": ref(COMPLETION_REL, "unchanged Core family gate"),
        "qualification_design": ref(DESIGN_REL, "F6 v4 15-cell design receipt"),
        "qualification_candidate_card": ref(
            CANDIDATE_REL, "F6 v4 qualification candidate card"
        ),
        "qualification_root_admission": ref(
            ADMISSION_REL, "F6 v4 native-preflight-only root admission"
        ),
        "qualification_preflight_audit": ref(
            PREFLIGHT_REL, "F6 v4 15-cell native preflight aggregate"
        ),
        "solver_canary_plan": ref(PLAN_REL, "F6 v4 eight-cell root-authorized plan"),
        "solver_canary_audit": ref(CANARY_REL, "F6 v4 eight-cell aggregate audit"),
        "cell08_root_review": ref(FAILED_REVIEW_REL, "cell-08 root authorization receipt"),
        "cell08_execution_receipt": ref(
            FAILED_RECEIPT_REL, "cell-08 exact-one scientific failure receipt"
        ),
        "cell08_native_frame_audit": ref(
            FAILED_FRAME_REL, "cell-08 compact native-frame hard-gate audit"
        ),
        "qualification_report": ref(
            "reports/F6-PHYSICAL-ANCHOR-OBSERVATION-AXIS-V10-QUALIFICATION-PREFLIGHT-V4-2026-09-21.zh-CN.md",
            "F6 v4 qualification preflight report",
        ),
        "canary_report": ref(
            "reports/F6-PHYSICAL-ANCHOR-OBSERVATION-AXIS-V10-SOLVER-CANARY-V4-2026-09-21.zh-CN.md",
            "F6 v4 solver-canary report",
        ),
        "implementation": {
            "path": str(Path(__file__).relative_to(LAB)),
            "sha256": sha256(Path(__file__)),
            "bytes": Path(__file__).stat().st_size,
            "role": "read-only F6 route-closure implementation",
        },
    }

    return {
        "schema": "core.f6.observation_axis.third_t1.route_closed.candidate_card.v1",
        "version": "v1",
        "status": "route_closed_no_new_hypothesis",
        "family": "F6",
        "candidate_id": "F6_observation_axis_v4_third_t1_no_new_hypothesis_v1",
        "scope_id": preflight["scope_id"],
        "revision_id": preflight["revision_id"],
        "execution_host": "Luna Max",
        "qualification_only": True,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "new_scope": {
            "status": "none_auditable",
            "independent_hypothesis_count": 0,
            "hypothesis": None,
            "reason": [
                "The only observed v4 scientific failure is one density-excluded fluid particle at q=1 and dp=0.015 m; the compact evidence does not identify a new physical mechanism.",
                "Relaxing excluded-particle, native-identity, fluid-group-count, or mass gates would be a threshold/denominator change and cannot be called a new scope.",
                "Renaming the observation window or changing the sampler to hide the missing particle would be diagnostic-only and cannot repair the scientific hard gate.",
                "A catchment, closed-top boundary, or other altered fluid topology would be a different physical problem; no independently bound Definition and falsifiable hypothesis is present in the audited receipts.",
            ],
            "diagnostic_route_rejected": True,
        },
        "existing_scope_audit": {
            "native_preflight": {
                "planned_cells": preflight["cell_count"],
                "passed_cells": sum(row["pass"] for row in preflight["cells"]),
                "matrix_complete": preflight["matrix_complete"],
                "qualification_credit": 0,
            },
            "solver_canary": {
                "selected_cells": canary["selected_count"],
                "audited_cells": canary["audited_count"],
                "scientific_pass_cells": canary["scientific_pass_count"],
                "scientific_pass_fraction": "7/8",
                "failed_cell_index": 8,
                "failed_cell_id": failed["cell_id"],
                "q": 1.0,
                "dp_m": 0.015,
                "excluded_particles": failed["run"]["excluded_particles"],
                "initial_fluid_particles": failed_frame["frames"][0]["fluid_count"],
                "terminal_fluid_particles": failed_frame["frames"][-1]["fluid_count"],
                "terminal_total_particles": failed_frame["frames"][-1]["particle_count"],
                "failure_gates": [
                    "excluded_particles_zero",
                    "native_identity_fixed",
                    "fluid_group_count_fixed",
                ],
                "failure_retained": True,
                "remaining_cells_authorized": False,
                "same_input_retry": False,
            },
            "metadata_only_repairs": {
                "count": canary["metadata_integrity_repair_count"],
                "indices": repaired_indices,
                "solver_reinvoked": False,
                "scientific_fields_changed": False,
                "qualification_credit": 0,
                "receipt_binding_failures_after_repair": 0,
            },
        },
        "route_decision": {
            "decision": "close_current_f6_observation_axis_search",
            "status": "route_closed_no_new_hypothesis",
            "root_review_only": True,
            "authorized_now": False,
            "new_physical_definition_found": False,
            "new_candidate_card_authorized": False,
            "cpu_native_preflight_authorized": False,
            "remaining_canary_cells_authorized": False,
            "solver_authorized": False,
            "gpu_authorized": False,
            "reopen_requires": (
                "a genuinely new falsifiable F6 physical/numerical mechanism, a new Definition/case/output identity, a fresh static hash gate, and independent root authorization"
            ),
            "reopen_execution_cap": (
                "at most one CPU/native preflight after the new Definition hash gate and root authorization; preflight credit remains zero"
            ),
            "forbidden_now": [
                "cell-08 same-input retry, resume, or output reinterpretation",
                "remaining seven-cell solver or GPU execution",
                "threshold relaxation, survivor renormalization, or denominator rewrite",
                "queue, registry, ledger, matrix, T1, or T2 mutation",
            ],
        },
        "core_gate": {
            "current_registered_t1_families": audited["completion"]["t1_families"],
            "third_t1_family_established": False,
            "qualification_credit_added": 0,
            "core_gate_changed": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
        },
        "denominator_policy": {
            "fifteen_cell_design_preserved": True,
            "eight_cell_canary_denominator_preserved": True,
            "cell08_failure_retained": True,
            "remaining_seven_cells_not_reclassified": True,
            "existing_denominators_changed": False,
            "scientific_denominator_changed": False,
            "survivor_renormalization": False,
            "threshold_relaxation": False,
            "same_input_retry": False,
            "preflight_zero_credit": True,
        },
        "execution_controls": {
            "read_only_audit": True,
            "large_trajectory_fields_opened": False,
            "new_definition_written": False,
            "definition_static_hash_gate": False,
            "cpu_gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
            "qualification_credit": 0,
        },
        "evidence": evidence,
    }


def build_receipt(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "core.f6.observation_axis.third_t1.route_decision_receipt.v1",
        "version": "v1",
        "status": "route_closed_no_new_hypothesis",
        "decision": "root_review_only_close_current_f6_observation_axis_search",
        "execution_host": "Luna Max",
        "candidate_card": {
            "path": str(CARD_OUTPUT.relative_to(LAB)),
            "sha256": sha256(CARD_OUTPUT),
            "bytes": CARD_OUTPUT.stat().st_size,
        },
        "root_review": {
            "root_review_only": True,
            "authorized_now": False,
            "new_definition_authorized": False,
            "fresh_definition_hash_gate_passed": False,
            "cpu_native_preflight_authorized": False,
            "solver_authorized": False,
            "gpu_authorized": False,
            "remaining_canary_cells_authorized": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
            "qualification_credit": 0,
        },
        "route_decision": {
            "new_physical_definition_found": False,
            "decision": "close_current_f6_observation_axis_search",
            "reopen_requires": "new falsifiable physical/numerical mechanism plus fresh Definition hash gate and independent root review",
            "same_input_retry": False,
            "new_preflight_cap": "at_most_one_cpu_native_after_new_hash_gate_and_root_authorization",
        },
        "failure_preservation": {
            "cell08_excluded_particles": 1,
            "cell08_failure_gates_retained": [
                "excluded_particles_zero",
                "native_identity_fixed",
                "fluid_group_count_fixed",
            ],
            "cell08_same_input_retry": False,
            "remaining_seven_cells_authorized": False,
            "metadata_only_repairs": 7,
            "metadata_repairs_reinvoked_solver": False,
            "metadata_repairs_changed_scientific_fields": False,
        },
        "denominator_preservation": {
            "fifteen_cell_design_preserved": True,
            "eight_cell_canary_denominator_preserved": True,
            "existing_denominators_changed": False,
            "survivor_renormalization": False,
            "threshold_relaxation": False,
            "preflight_zero_credit": True,
        },
        "core_gate": {
            "qualification_credit_added": 0,
            "core_gate_changed": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
        },
        "reporting": {
            "large_trajectory_fields_opened": False,
            "thresholds_modified": False,
            "new_definition_written": False,
            "solver_started_by_closure": False,
            "gpu_started_by_closure": False,
        },
        "card_status": card["status"],
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def verify() -> dict[str, Any]:
    card = json.loads(CARD_OUTPUT.read_text(encoding="utf-8"))
    receipt = json.loads(RECEIPT_OUTPUT.read_text(encoding="utf-8"))
    expected = build_card()
    assert card == expected
    assert receipt == build_receipt(card)
    return card


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify existing receipts")
    args = parser.parse_args()
    if args.check:
        card = verify()
    else:
        card = build_card()
        _write_json(CARD_OUTPUT, card)
        _write_json(RECEIPT_OUTPUT, build_receipt(card))
    print(
        f"status={card['status']} candidate={card['candidate_id']} "
        "new_definition=false runtime_calls=0 credit=0"
    )


if __name__ == "__main__":
    main()

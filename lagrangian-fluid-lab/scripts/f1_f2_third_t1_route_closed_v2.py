#!/usr/bin/env python3
"""Build a read-only, hash-bound F1/F2 third-T1 route-closure receipt.

This audit is intentionally a closure result.  It reads compact route cards,
negative-evidence summaries, and reports already present in the workspace.  It
does not open trajectories or large particle fields and has no Definition
writer, GenCase, native decoder, solver, GPU, queue, registry, ledger, or
matrix-submission entry point.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
CARD_OUTPUT = LAB / "campaigns/core-v1/cfd/f1-f2-third-t1-route-closed-v2.json"
RECEIPT_OUTPUT = LAB / (
    "campaigns/core-v1/evidence/f1-f2-third-t1-route-decision-receipt-v2.json"
)


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


def build_card() -> dict[str, Any]:
    completion = load("campaigns/core-v1/completion.json")
    f1_eval = load("campaigns/core-v1/cfd/f1-qualification-evaluation.json")
    f1_h2 = load("campaigns/core-v1/evidence/f1-h2-mdbc-summary.json")
    f1_gap = load(
        "campaigns/core-v1/evidence/"
        "f1-suspended-obstacle-gap-g1-anchor-negative-evidence-v1.json"
    )
    dynamic = load(
        "campaigns/core-v1/cfd/"
        "f2-dynamic-third-family-dbc-duration-anchor-canary-negative-evidence-v1.json"
    )
    weir = load(
        "campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/terminal-matrix-v1.json"
    )
    weir_denom = load(
        "campaigns/core-v1/cfd/"
        "f2-receiver-overflow-weir-scope-v1/terminal-failure-denominator-v1.json"
    )
    ballistic_v1 = load(
        "campaigns/core-v1/runtime/attempts/"
        "f2-static-receiver-ballistic-catch-q05-anchor-infra-retry-v1/"
        "20260921T111854-b642c199de99/product/postrun-audit.json"
    )
    ballistic_v2 = load(
        "campaigns/core-v1/cfd/"
        "f2-static-receiver-ballistic-catch-release010-v2/preflight-v2/"
        "negative-evidence-v2.json"
    )
    ballistic_v2_preflight = load(
        "campaigns/core-v1/cfd/"
        "f2-static-receiver-ballistic-catch-release010-v2/preflight-v2/"
        "preflight-v2.json"
    )
    slot_v1 = load(
        "campaigns/core-v1/evidence/f2-distributed-slot-"
        "preflight-negative-evidence-v1.json"
    )
    slot_v2 = load(
        "campaigns/core-v1/evidence/"
        "f2-distributed-slot-normal-repair-v2-negative-evidence.json"
    )
    orifice_v2 = load(
        "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/"
        "normal-remediation-v2/preflight-v4/preflight.json"
    )
    orifice_v3 = load(
        "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/"
        "normal-remediation-v3/preflight-v3/preflight.json"
    )
    orifice_v4 = load(
        "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/"
        "normal-remediation-v4/preflight-v4/preflight.json"
    )
    orifice_partition = load(
        "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/"
        "normal-remediation-v4/v4-current-failure-partition-audit-v1.json"
    )
    h2 = load(
        "campaigns/core-v1/cfd/"
        "f2-h2-mdbc-static-hold-negative-audit-root-review-contract-20260921.json"
    )

    # These assertions make a stale or tampered negative receipt fail closed.
    assert completion["t1_families"] == ["F3", "F4"]
    assert completion["checks"]["three_t1_families"] is False
    assert completion["checks"]["t1_denominator_complete"] is False
    assert f1_eval["qualified"] is False and f1_eval["T1_numerical"] is False
    assert f1_eval["canary"]["hard_integrity_pass"] is False
    assert f1_h2["hard_integrity_pass"] is False
    assert f1_gap["qualified"] is False and f1_gap["matrix_credit"] == 0
    assert f1_gap["hard_integrity"]["pass"] is False
    assert f1_gap["event_window"]["complete"] is True
    assert dynamic["scientific_result"]["hard_integrity_pass"] is True
    assert dynamic["scientific_result"]["event_window_complete"] is False
    assert dynamic["matrix_credit"]["credit"] == 0
    assert weir["terminal_row"]["hard_integrity_pass"] is False
    assert weir["terminal_row"]["event_window_complete"] is False
    assert weir["matrix_credit"] == 0
    assert weir_denom == {
        **weir_denom,
        "planned": 15,
        "executed": 1,
        "passed": 0,
        "failed": 1,
        "event_censored": 1,
        "unattempted": 14,
        "credit": 0,
    }
    assert ballistic_v1["hard_integrity_pass"] is False
    assert ballistic_v1["run_out_summary"]["excluded_particles"] == 64
    assert ballistic_v1["matrix_credit"] == 0
    assert ballistic_v2["status"] == (
        "candidate_closed_after_cpu_native_scientific_hard_failure"
    )
    assert ballistic_v2_preflight["preflight_pass"] is False
    assert ballistic_v2["matrix_credit"] == 0
    assert slot_v1["preflight"]["preflight_pass"] is False
    assert slot_v2["preflight"]["preflight_pass"] is False
    assert slot_v2["route_decision"]["normal_hypotheses_exhausted"] is True
    assert orifice_v2["preflight_pass"] is False
    assert orifice_v3["preflight_pass"] is False
    assert orifice_v4["preflight_pass"] is False
    assert orifice_partition["interpretation"]["no_route_authorization"] is True
    assert h2["status"] == "h2_static_hold_closed_after_eight_scientific_failures"
    assert h2["matrix_credit"] == 0

    evidence = {
        "core_completion": ref(
            "campaigns/core-v1/completion.json", "unchanged Core family gate"
        ),
        "f1_qualification": ref(
            "campaigns/core-v1/cfd/f1-qualification-evaluation.json",
            "F1 qualification and H1 canary negative result",
        ),
        "f1_h1_h2_stop": ref(
            "campaigns/core-v1/evidence/f1-h2-mdbc-summary.json",
            "F1 H1/H2 repair stop",
        ),
        "f1_suspended_gap_negative": ref(
            "campaigns/core-v1/evidence/"
            "f1-suspended-obstacle-gap-g1-anchor-negative-evidence-v1.json",
            "F1 G1 completed hard-integrity negative anchor",
        ),
        "f2_dynamic_negative": ref(
            "campaigns/core-v1/cfd/"
            "f2-dynamic-third-family-dbc-duration-anchor-canary-negative-evidence-v1.json",
            "F2 moving-cup DBC duration event-censored anchor",
        ),
        "f2_weir_terminal": ref(
            "campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/"
            "terminal-matrix-v1.json",
            "F2 receiver/weir terminal matrix",
        ),
        "f2_weir_denominator": ref(
            "campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/"
            "terminal-failure-denominator-v1.json",
            "F2 receiver/weir retained denominator",
        ),
        "f2_ballistic_v1_negative": ref(
            "campaigns/core-v1/runtime/attempts/"
            "f2-static-receiver-ballistic-catch-q05-anchor-infra-retry-v1/"
            "20260921T111854-b642c199de99/product/postrun-audit.json",
            "F2 receiver/ballistic v1 hard negative",
        ),
        "f2_ballistic_v2_negative": ref(
            "campaigns/core-v1/cfd/"
            "f2-static-receiver-ballistic-catch-release010-v2/preflight-v2/"
            "negative-evidence-v2.json",
            "F2 receiver/ballistic release-speed v2 hard negative",
        ),
        "f2_distributed_slot_v1_negative": ref(
            "campaigns/core-v1/evidence/"
            "f2-distributed-slot-preflight-negative-evidence-v1.json",
            "F2 distributed-slot v1 hard negative",
        ),
        "f2_distributed_slot_v2_negative": ref(
            "campaigns/core-v1/evidence/"
            "f2-distributed-slot-normal-repair-v2-negative-evidence.json",
            "F2 distributed-slot v2 hard negative and exhausted normal hypotheses",
        ),
        "f2_orifice_v2_negative": ref(
            "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/"
            "normal-remediation-v2/preflight-v4/preflight.json",
            "F2 submerged-orifice v2 hard negative",
        ),
        "f2_orifice_v3_negative": ref(
            "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/"
            "normal-remediation-v3/preflight-v3/preflight.json",
            "F2 submerged-orifice v3 hard negative",
        ),
        "f2_orifice_v4_negative": ref(
            "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/"
            "normal-remediation-v4/preflight-v4/preflight.json",
            "F2 submerged-orifice v4 hard negative",
        ),
        "f2_orifice_partition": ref(
            "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/"
            "normal-remediation-v4/v4-current-failure-partition-audit-v1.json",
            "F2 submerged-orifice route closure partition",
        ),
        "f2_h2_static_hold": ref(
            "campaigns/core-v1/cfd/"
            "f2-h2-mdbc-static-hold-negative-audit-root-review-contract-20260921.json",
            "F2 H2 static-hold eight-row scientific negative audit",
        ),
        "audit_report": ref(
            "reports/CORE-THIRD-T1-CANDIDATE-AUDIT-2026-09-21-v2.zh-CN.md",
            "latest read-only third-T1 route audit",
        ),
        "implementation": {
            "path": str(Path(__file__).relative_to(LAB)),
            "sha256": sha256(Path(__file__)),
            "bytes": Path(__file__).stat().st_size,
            "role": "read-only closure implementation",
        },
    }

    return {
        "schema": "core.third_t1.f1_f2_route_closed.candidate_card.v2",
        "version": "v2",
        "status": "route_closed_no_new_hypothesis",
        "family_scope": ["F1", "F2"],
        "candidate_id": "F1_F2_third_t1_no_new_hypothesis_v2",
        "execution_host": "Luna Max",
        "qualification_claim": "none",
        "T1_numerical": False,
        "matrix_credit": 0,
        "new_definition": {
            "status": "none_auditable",
            "hypothesis": None,
            "reason": [
                "Every reviewed F1/F2 mechanism with a materialized Definition has a retained hard failure or event censor.",
                "Remaining proposal-only entries are either the same closed topology, a normal-construction repair of it, or lack a literal Definition and static proof.",
                "No new falsifiable physical Definition can be admitted without inventing an unbound scope beyond the audited evidence.",
            ],
        },
        "route_findings": [
            {
                "route_id": "F1_H1_H2_H3_H4",
                "status": "closed_hard_negative_repair_lineage",
                "hard_integrity_pass": False,
                "matrix_credit": 0,
                "same_input_retry": False,
            },
            {
                "route_id": "F1_suspended_obstacle_gap_G1",
                "status": "closed_hard_negative_anchor",
                "hard_integrity_pass": False,
                "event_window_complete": True,
                "endpoint_frames": 84,
                "obstacle_penetration_frames": 615,
                "saved_chord_crossings": 1700,
                "matrix_credit": 0,
                "same_input_retry": False,
            },
            {
                "route_id": "F2_dynamic_DBC_duration",
                "status": "closed_event_censored",
                "hard_integrity_pass": True,
                "event_window_complete": False,
                "fixed_denominator": 15,
                "matrix_credit": 0,
                "same_input_retry": False,
            },
            {
                "route_id": "F2_receiver_overflow_weir",
                "status": "closed_terminal_anchor_negative",
                "planned": 15,
                "executed": 1,
                "failed": 1,
                "event_censored": 1,
                "unattempted": 14,
                "matrix_credit": 0,
                "same_input_retry": False,
            },
            {
                "route_id": "F2_receiver_ballistic_v1_v2",
                "status": "closed_cpu_or_solver_hard_negative",
                "v1_excluded_particles": 64,
                "v2_outer_endpoint_particles": 3840,
                "matrix_credit": 0,
                "same_input_retry": False,
            },
            {
                "route_id": "F2_distributed_slot_v1_v2",
                "status": "closed_normal_hypotheses_exhausted",
                "v1_zero_boundnor": 124608,
                "v2_zero_boundnor": 76095,
                "matrix_credit": 0,
                "same_input_retry": False,
            },
            {
                "route_id": "F2_submerged_orifice_normal_remediation_v2_v3_v4",
                "status": "closed_cpu_native_hard_negative",
                "zero_boundnor": {"v2": 64899, "v3": 83443, "v4": 29484},
                "matrix_credit": 0,
                "same_input_retry": False,
            },
            {
                "route_id": "F2_H2_static_hold",
                "status": "closed_after_eight_scientific_failures",
                "matrix_credit": 0,
                "same_input_retry": False,
            },
        ],
        "route_decision": {
            "decision": "close_current_F1_F2_third_T1_search",
            "status": "route_closed_no_new_hypothesis",
            "root_review_only": True,
            "root_review_required_to_reopen": True,
            "reopen_condition": "a genuinely new falsifiable physical Definition outside all listed closed lineages, with a new scope/case/output namespace",
            "authorized_now": False,
        },
        "core_gate": {
            "current_registered_t1_families": ["F3", "F4"],
            "third_t1_family_established": False,
            "qualification_credit_added": 0,
            "core_gate_changed": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
        },
        "execution_controls": {
            "read_only_audit": True,
            "definition_writer_invoked": False,
            "cpu_gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_launched": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
            "qualification_credit": 0,
        },
        "denominator_policy": {
            "existing_failure_denominators_unchanged": True,
            "same_input_retry": False,
            "threshold_relaxation": False,
            "survivor_renormalization": False,
            "preflight_credit": 0,
        },
        "evidence": evidence,
    }


def build_receipt(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "core.third_t1.f1_f2.route_decision_receipt.v2",
        "version": "v2",
        "status": "route_closed_no_new_hypothesis",
        "decision": "root_review_only_close_current_search",
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
            "cpu_native_preflight_authorized": False,
            "solver_authorized": False,
            "gpu_authorized": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
            "qualification_credit": 0,
        },
        "route_decision": {
            "new_physical_definition_found": False,
            "decision": "close_current_F1_F2_third_T1_search",
            "reopen_requires": "new falsifiable physical mechanism plus independent root review",
            "same_input_retry": False,
        },
        "denominator_preservation": {
            "all_prior_failures_retained": True,
            "existing_denominators_changed": False,
            "survivor_renormalization": False,
            "preflight_zero_credit": True,
        },
        "reporting": {
            "large_trajectory_fields_opened": False,
            "thresholds_modified": False,
            "new_definition_written": False,
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
    expected_receipt = build_receipt(card)
    assert receipt == expected_receipt
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

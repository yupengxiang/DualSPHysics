#!/usr/bin/env python3
"""Join current third-T1 route decisions without opening trajectories."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
OUTPUT = LAB / "campaigns/core-v1/evidence/core-third-t1-frontier-audit-20260922.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(relative: str) -> dict[str, Any]:
    path = LAB / relative
    return json.loads(path.read_text(encoding="utf-8"))


def bind(relative: str, role: str) -> dict[str, Any]:
    path = LAB / relative
    return {"path": relative, "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def build_audit() -> dict[str, Any]:
    completion = load("campaigns/core-v1/completion.json")
    f1_f2 = load("campaigns/core-v1/cfd/f1-f2-third-t1-route-closed-v2.json")
    f6 = load("campaigns/core-v1/cfd/f6-observation-axis-v4-third-t1-route-closed-v1.json")
    f7 = load("campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/root-review-receipt-v2-20260922.json")
    f8 = load("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/candidate-card-v1.json")
    f8_review = load("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/root-review/terra-high-root-review-v1.json")
    f8_contract = load("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/parameter-contract-v1.json")
    f9 = load("campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/candidate-card-v1.json")
    f9_review = load("campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/root-review/terra-high-definition-review-v3.json")
    f9_contract = load("campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/definition-contract-v1.json")
    f9_proposal = load("campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/root-review/root-admission-proposal-v1.json")
    readiness = load("campaigns/core-v1/learning/core-formal-readiness-audit-20260922.json")

    assert completion["t1_families"] == ["F3", "F4"]
    assert f1_f2["status"] == "route_closed_no_new_hypothesis"
    assert f6["status"] == "route_closed_no_new_hypothesis"
    assert f6["existing_scope_audit"]["solver_canary"]["scientific_pass_cells"] == 7
    assert f6["existing_scope_audit"]["solver_canary"]["failed_cell_index"] == 8
    assert f7["status"] == "root_review_only_no_go_missing_fresh_materialization"
    assert f7["admission_granted"] is False
    assert f8["status"] == "proposal_only_root_review_required"
    assert f8["admission_granted"] is False
    assert f8_review["decision"] == "conditional_go_static_preparation_no_admission"
    assert f8_review["admission_granted"] is False
    assert f8_contract["status"] == "pre_admission_static_contract_frozen"
    assert f8_contract["admission_granted"] is False
    assert f9["status"] == "proposal_only_root_review_required"
    assert f9["admission_granted"] is False
    assert f9_review["decision"] == "CONDITIONAL-GO"
    assert f9_review["admission_granted"] is False
    assert f9_review["reviewed_hashes"]["candidate_card_v1.json"] == sha256(LAB / "campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/candidate-card-v1.json")
    assert f9_review["reviewed_hashes"]["definition-contract-v1.json"] == sha256(LAB / "campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/definition-contract-v1.json")
    assert f9_review["reviewed_hashes"]["F9_GRAVITY_FILM_NUSSELT_R001_Def.xml"] == sha256(LAB / "campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/input/F9_GRAVITY_FILM_NUSSELT_R001_Def.xml")
    assert f9_contract["status"] == "static_definition_materialized_no_runtime_authorization"
    assert f9_contract["admission_granted"] is False
    assert f9_contract["runtime_authorization"]["solver"] is False
    assert f9_proposal["status"] == "proposal_only_waiting_for_root_decision"
    assert f9_proposal["third_t1_family_candidate"] is True
    assert f9_proposal["admission_granted"] is False
    assert f9_proposal["qualification_credit"] == 0
    assert all(value is False for key, value in f9_proposal["execution_controls"].items() if key not in {"definition_candidate_materialized"})
    assert readiness["status"] == "blocked"

    return {
        "schema": "core.third_t1.frontier_audit.v1",
        "status": "no_admissible_third_t1_candidate_at_current_state",
        "decision": "preserve_core_incomplete_and_do_not_execute_closed_routes",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "current_t1_families": completion["t1_families"],
        "third_family_established": False,
        "route_decisions": {
            "F1_F2": {
                "status": f1_f2["status"],
                "new_physical_definition_found": f1_f2["new_definition"]["status"] != "none_auditable",
                "reopen_requires": f1_f2["route_decision"]["reopen_condition"],
                "same_input_retry": False,
            },
            "F6": {
                "status": f6["status"],
                "preflight_cells_passed": f6["existing_scope_audit"]["native_preflight"]["passed_cells"],
                "solver_canary_cells_passed": f6["existing_scope_audit"]["solver_canary"]["scientific_pass_cells"],
                "solver_canary_cells_total": f6["existing_scope_audit"]["solver_canary"]["audited_cells"],
                "failed_cell_id": f6["existing_scope_audit"]["solver_canary"]["failed_cell_id"],
                "remaining_cells_authorized": f6["route_decision"]["remaining_canary_cells_authorized"],
                "reopen_requires": f6["route_decision"]["reopen_requires"],
            },
            "F7": {
                "status": f7["status"],
                "admission_granted": f7["admission_granted"],
                "fresh_definition_present": f7["fresh_artifact_integrity"]["definition"]["exists"],
                "native_integrity_receipt_present": f7["fresh_artifact_integrity"]["native_integrity_receipt"]["exists"],
                "next_allowed_action": "new root admission review only; no solver or ComputeForces execution",
            },
            "F8": {
                "status": f8["status"],
                "scope_id": f8["scope_id"],
                "admission_granted": f8["admission_granted"],
                "qualification_credit": f8["qualification_credit"],
                "terra_high_review": f8_review["decision"],
                "parameter_contract": f8_contract["status"],
                "fresh_definition_present": f8["execution_controls"]["definition_written"],
                "next_allowed_action": "root interpretation and independent admission review only; no GenCase or solver execution",
            },
            "F9": {
                "status": f9["status"],
                "scope_id": f9["scope_id"],
                "admission_granted": f9["admission_granted"],
                "qualification_credit": f9["qualification_credit"],
                "terra_high_review": f9_review["decision"],
                "definition_contract": f9_contract["status"],
                "fresh_definition_present": f9["execution_controls"]["definition_written"],
                "root_admission_proposal": f9_proposal["status"],
                "next_allowed_action": "formal root admission review only; after admission, target-specific native semantic preparation may be considered; no GenCase or solver execution",
            },
        },
        "formal_readiness": {
            "status": readiness["status"],
            "blocker_codes": [row["code"] for row in readiness["blockers"]],
            "formal_runs_observed": readiness["formal_protocol"]["observed_material_case_runs"],
            "material_case_runs_observed": readiness["formal_protocol"]["observed_material_case_runs"],
        },
        "execution_controls": {
            "trajectory_fields_opened": False,
            "definition_written": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "training_started": False,
        },
        "evidence": [
            bind("campaigns/core-v1/completion.json", "Core family gate"),
            bind("campaigns/core-v1/cfd/f1-f2-third-t1-route-closed-v2.json", "F1/F2 closure card"),
            bind("campaigns/core-v1/evidence/f1-f2-third-t1-route-decision-receipt-v2.json", "F1/F2 closure receipt"),
            bind("campaigns/core-v1/cfd/f6-observation-axis-v4-third-t1-route-closed-v1.json", "F6 closure card"),
            bind("campaigns/core-v1/evidence/f6-observation-axis-v4-third-t1-route-decision-receipt-v1.json", "F6 closure receipt"),
            bind("campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/root-review-receipt-v2-20260922.json", "F7 no-go root receipt"),
            bind("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/candidate-card-v1.json", "F8 proposal-only candidate card"),
            bind("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/root-review/terra-high-root-review-v1.json", "F8 Terra High root-style review"),
            bind("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/parameter-contract-v1.json", "F8 frozen pre-admission parameter contract"),
            bind("campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/candidate-card-v1.json", "F9 proposal-only candidate card"),
            bind("campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/root-review/terra-high-definition-review-v3.json", "F9 Terra High corrected Definition review v3"),
            bind("campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/definition-contract-v1.json", "F9 static Definition contract"),
            bind("campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/input/F9_GRAVITY_FILM_NUSSELT_R001_Def.xml", "F9 static Definition XML"),
            bind("campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/root-review/root-admission-proposal-v1.json", "F9 non-authorizing root-admission proposal"),
            bind("campaigns/core-v1/learning/core-formal-readiness-audit-20260922.json", "current formal readiness"),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("schema", "status", "current_t1_families", "execution_controls")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_submerged_orifice_boundnor_partition_audit_v1 import (
    DEFAULT_BOUND,
    audit_bound_vtk,
)
from scripts.f2_submerged_orifice_normal_remediation_v2 import (
    CASE_ID,
    DEFAULT_AUDIT,
    DEFAULT_CANDIDATE,
    DEFAULT_CONTRACT,
    DEFAULT_PROPOSAL,
    verify_contract,
)


LAB = Path(__file__).resolve().parents[1]
BASE = LAB / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_read_only_boundnor_partition_has_expected_mk_failure_split(tmp_path: Path):
    output = tmp_path / "partition.json"
    audit = audit_bound_vtk(DEFAULT_BOUND, output)
    assert audit["status"] == "read_only_generated_boundnor_partitioned"
    assert audit["input_scope"] == {
        "bound_vtk_only": True,
        "definition_read": False,
        "bi4_read": False,
        "native_decoder_invoked": False,
        "gencase_invoked": False,
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "ledger_mutation": 0,
        "registry_mutation": 0,
    }
    assert audit["generated_field_summary"]["global_zero_normal_count"] == 63161
    partitions = {row["mk"]: row for row in audit["mk_partitions"]}
    assert partitions[17]["particle_count"] == 226422
    assert partitions[17]["zero_normal_count"] == 43526
    assert partitions[18]["particle_count"] == 37806
    assert partitions[18]["zero_normal_count"] == 19635
    assert ".bi4" not in audit["source"]["path"]
    assert not audit["input_scope"]["definition_read"]


def test_v2_contract_is_root_review_only_and_full_denominator_bound():
    contract = verify_contract(DEFAULT_CONTRACT, BASE, DEFAULT_AUDIT, DEFAULT_CANDIDATE, DEFAULT_PROPOSAL)
    assert contract["status"] == "prepared_design_only_cpu_not_authorized"
    assert contract["repair_review"]["new_input_identity"] == CASE_ID
    assert contract["repair_review"]["current_anchor_modified"] is False
    assert contract["repair_review"]["current_anchor_rerun"] is False
    assert contract["repair_review"]["current_anchor_definition_reused"] is False
    assert contract["repair_review"]["current_anchor_bi4_reused"] is False
    assert contract["failure_denominator"] == {
        "planned_rows": 15,
        "executed_rows": 0,
        "passed_rows": 0,
        "failed_rows": 0,
        "unattempted_rows": 15,
        "qualification_numerator": 0,
        "threshold_relaxation": False,
        "same_input_retry": False,
        "survivor_renormalization": False,
    }
    auth = contract["authorization"]
    assert all(auth[key] is False for key in (
        "cpu_gencase", "native_decode", "solver_launch", "gpu_launch",
        "job_spec_creation", "matrix_submission",
    ))
    assert auth["queue_mutation"] == 0
    assert auth["ledger_mutation"] == 0
    assert auth["registry_mutation"] == 0


def test_v2_proposal_requires_fresh_definition_and_keeps_zero_normal_hard_gate():
    proposal = _read(DEFAULT_PROPOSAL)
    assert proposal["status"] == "root_review_only_cpu_preflight_proposal_not_run"
    assert proposal["authorized_now"] is False
    assert proposal["case_id"] == CASE_ID
    assert proposal["fresh_definition"]["required"] is True
    assert proposal["fresh_definition"]["reuse_failed_anchor_definition"] is False
    assert proposal["fresh_definition"]["reuse_failed_anchor_bi4"] is False
    assert proposal["required_hard_results"]["zero_normal_count"] == 0
    assert proposal["required_hard_results"]["zero_normal_norm_threshold_m"] == 1.0e-12
    assert proposal["denominator"]["planned"] == 15
    assert proposal["denominator"]["credit"] == 0
    assert proposal["execution_controls"]["solver_invoked"] is False
    assert proposal["execution_controls"]["gpu_invoked"] is False

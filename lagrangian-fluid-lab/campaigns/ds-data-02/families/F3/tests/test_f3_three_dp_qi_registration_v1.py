from __future__ import annotations

import hashlib
import json
from pathlib import Path


FAMILY = Path(__file__).resolve().parents[1]
HANDOFF = FAMILY / "handoff_20261003/three_dp_qi_v1"
GENERATED = HANDOFF / "generated"


def load_generated(name: str) -> dict:
    return json.loads((GENERATED / name).read_text(encoding="utf-8"))


def load_resolution(role: str, kind: str) -> dict:
    if kind == "contract":
        path = GENERATED / "source_contracts" / f"{role}.source-contract.v1.json"
    else:
        path = GENERATED / "requests" / f"{role}.bounded-audit-request.v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_three_resolution_terminal_ledgers_are_bound_without_native_loss():
    report = load_generated("three-dp-qi-bounded-audit-001.json")
    assert report["status"] == "reference_qi_evidence_registered_qn_pending"
    assert report["q_n_status"] == "not_assessed"
    assert report["frozen_budget_contract"]["macro_relative_starting_budget"] == 0.05
    assert report["frozen_budget_contract"]["event_time_relative_starting_budget"] == 0.02

    physical_hashes = set()
    for role in ("coarse", "medium", "fine"):
        contract = load_resolution(role, "contract")
        runparts = contract["actual_terminal_evidence"]["runparts"]
        assert runparts["numeric_rows"] == 4001
        assert runparts["first_time_s"] == 0.0
        assert runparts["full_window_completed"] is True
        assert runparts["excluded_all_zero"] is True
        assert all(value == 0 for value in runparts["excluded_interval_sums"].values())
        assert runparts["expected_population_match"] is True
        dimensions = contract["actual_terminal_evidence"]["solver_dimension"]
        assert dimensions["solver_dimension"] == 3
        assert dimensions["xml_data2d"] in (False, "false")
        assert contract["source_bindings"]["trajectory_h5"]["rehash_performed"] is False
        assert contract["source_bindings"]["trajectory_h5"]["sha256"]
        physical_hashes.add(contract["physical_binding"]["physical_binding_sha256"])

    assert physical_hashes == {"fdb645e24952ed2f41225ca537d067d0233c9a94746fd4af0c390205736c9b10"}


def test_surface_and_typed_label_disagreement_stays_a_gap():
    for role in ("coarse", "medium", "fine"):
        contract = load_resolution(role, "contract")
        finding = contract["audit_findings"]["surface_vs_typed_label_flux"]
        assert finding["status"] == "reconciliation_required"
        assert finding["surface_x_y_crossings_present"] is True
        assert finding["typed_label_aggregate_x_y_crossings"] == {"negative": 0, "positive": 0}
        missing = " ".join(contract["missing_or_deferred"])
        assert "Q-N numerical reference comparison is not assessed." in missing
        assert "Top-open exit has no observed crossing" in missing

    fine = load_resolution("fine", "contract")
    assert fine["audit_findings"]["native_accounting_binding"]["status"] == "gap"
    assert "Fine historical native_accounting report is cross-bound to coarse" in " ".join(fine["missing_or_deferred"])


def test_bounded_audit_requests_are_root_review_only_and_hash_bound():
    manifest = load_generated("three-dp-qi-registration-manifest.v1.json")
    assert manifest["status"] == "root_review_required_qn_pending"
    for role in ("coarse", "medium", "fine"):
        request = load_resolution(role, "request")
        assert request["runnable"] is False
        assert request["launch_allowed"] is False
        assert request["root_only"] is True
        assert request["cpu_task_kind"] == "bounded_json_csv_qi_audit"
        assert request["source_bindings"]["trajectory_h5"]["rehash_performed"] is False
        assert request["large_h5_policy"]["read_h5"] is False
        assert request["large_h5_policy"]["rehash_h5"] is False
        assert request["audit_scope"]["no_qn_grant"] is True
        assert request["input_hashes"]
        contract = load_resolution(role, "contract")
        contract_path = (GENERATED / "source_contracts" / f"{role}.source-contract.v1.json").resolve()
        assert request["source_contract"]["path"] == str(contract_path)
        expected_contract_sha = hashlib.sha256(
            json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert request["expected_contract_sha256"] == expected_contract_sha

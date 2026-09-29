"""Fail-closed regression tests for the A8 package/reproduction boundary audit."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts import a8_package_reproduction_readiness_boundary_auditor_v1 as audit
from scripts import core_product_repro_bridge_v1 as bridge


ROOT = Path(__file__).resolve().parents[1]


def test_current_a8_boundary_report_has_no_live_bridge_projection_findings() -> None:
    report = audit.build_report(ROOT)
    assert report["schema"] == audit.SCHEMA
    assert report["status"] == "blocked_open_package_reproduction_boundary_gaps"
    assert report["passed"] is False
    assert report["readiness_pass"] is False
    assert report["independent_reproduction"] is False
    assert report["credit"] == 0
    assert report["mutations"] == audit.ZERO_MUTATIONS
    assert report["execution_constraints"] == audit.EXECUTION_CONSTRAINTS
    assert {item["id"] for item in report["findings"]} == {"A8-PRB-03"}
    assert report["minimal_progress_unit"]["promotion_allowed_by_this_audit"] is False
    assert audit.validate_report(report) == []


def test_current_v2_is_reader_only_and_contracts_remain_blocked() -> None:
    report = audit.build_report(ROOT)
    bundle = report["current_reader_bundle"]
    assert bundle["schema"] == "core.reader_bundle.v2"
    assert bundle["checkpoint_count"] == 0
    assert bundle["model_reproduction_supported"] is False
    assert bundle["reader_only_current_v2"] is True
    assert report["contract_readiness"]["independent_reproduction"]["readiness_pass"] is False
    assert report["contract_readiness"]["trusted_root_external_host"]["readiness_pass"] is False
    assert report["contract_readiness"]["checkpoint_current_binding"][
        "current_ready_for_trusted_model_package"
    ] is False


def test_reader_projection_probe_is_now_fail_closed() -> None:
    probe = audit._reader_projection_probe()
    assert probe["accepted_by_current_bridge"] is False
    assert probe["expected_fail_closed"] is True
    assert probe["blockers"]
    assert probe["projection"]["passed"] is False
    assert probe["projection"]["diagnostic_only"] is True
    assert probe["projection"]["qualification_credit"] == 0


def test_pair_projection_probe_is_now_fail_closed() -> None:
    pair = json.loads(
        (ROOT / audit.INPUTS["historical_cross_host_pair"]).read_text(encoding="utf-8")
    )
    probe = audit._pair_projection_probe(pair)
    assert probe["accepted_by_current_bridge"] is False
    assert probe["expected_fail_closed"] is True
    assert probe["blockers"]
    assert probe["projection"]["rollout_passed"] is False
    assert probe["projection"]["score_passed"] is False
    assert probe["projection"]["rollout_observed_hosts"] == [
        "same-physical-host",
        "same-physical-host",
    ]


def test_pair_probe_does_not_mutate_historical_payload() -> None:
    pair = json.loads(
        (ROOT / audit.INPUTS["historical_cross_host_pair"]).read_text(encoding="utf-8")
    )
    before = copy.deepcopy(pair)
    audit._pair_projection_probe(pair)
    assert pair == before


def test_report_validator_rejects_any_authorizing_claim() -> None:
    report = audit.build_report(ROOT)
    report["independent_reproduction"] = True
    errors = audit.validate_report(report)
    assert "independent_reproduction must remain False" in errors


def test_audit_is_metadata_only_and_does_not_reference_f3_f4_write_set() -> None:
    report = audit.build_report(ROOT)
    assert report["execution_constraints"]["large_hdf5_opened"] is False
    assert report["execution_constraints"]["large_npz_opened"] is False
    assert report["execution_constraints"]["checkpoint_opened"] is False
    assert all("F3" not in path and "F4" not in path for path in report["allowed_write_set"])


def test_committed_report_remains_a_valid_historical_pre_fix_snapshot() -> None:
    report_path = ROOT / (
        "reports/A8-PACKAGE-REPRODUCTION-READINESS-BOUNDARY-AUDIT-V1-2026-09-29.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mutation_probes"]["reader_projection"]["accepted_by_current_bridge"] is True
    assert report["mutation_probes"]["diagnostic_pair_projection"]["accepted_by_current_bridge"] is True
    assert audit.validate_report(report) == []
    assert report != audit.build_report(ROOT)


def test_bridge_source_remains_disjoint_from_f3_f4_artifact_writes() -> None:
    source = (ROOT / "scripts/a8_package_reproduction_readiness_boundary_auditor_v1.py").read_text(
        encoding="utf-8"
    )
    assert "core_runtime.py" not in source
    assert "subprocess" not in source
    assert "CUDA_VISIBLE_DEVICES" not in source
    assert "h5py.File" not in source

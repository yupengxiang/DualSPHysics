"""Focused tests for the non-authorizing formal-to-observed T1 aggregate join."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import core_t1_formal_release_observed_case_run_join_v1 as join


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / (
    "campaigns/core-v1/cfd/t1-evidence/"
    "formal-release-observed-case-run-join-v1.json"
)


def _current_report() -> dict:
    return join.build_report(ROOT, CONTRACT)


def test_current_fixed_scope_joins_432_rows_without_authorizing_t1() -> None:
    report = _current_report()

    assert join.validate_report(report, ROOT) == []
    assert report["aggregate_join"]["join_valid"] is True
    assert report["aggregate_join"]["observed_case_runs"] == 0
    assert report["aggregate_join"]["missing_case_runs"] == 432
    assert report["aggregate_join"]["target_denominator"]["family_counts"] == {
        "F3": 288,
        "F4": 144,
    }
    assert set(report["aggregate_join"]["formal_run_counts"].values()) == {48}
    assert set(report["aggregate_join"]["formal_run_family_counts"]["graph_raw-seed17"].items()) == {
        ("F3", 32),
        ("F4", 16),
    }
    assert report["decision"]["formal_eligible"] is False
    assert report["decision"]["T1_numerical"] is False
    assert report["decision"]["credit"] == 0
    assert "FORMAL_RELEASE_ROOT_ADMISSION_NOT_READY" in report["missing_blockers"]
    assert "NO_OBSERVED_T1_MODEL_CASE_RUN_RECEIPTS" in report["missing_blockers"]
    assert "AGGREGATE_JOIN_IS_NON_AUTHORIZING" in report["missing_blockers"]


def _synthetic_payloads() -> tuple[dict, dict]:
    rows = []
    for model in join.MODELS:
        for seed in join.SEEDS:
            run_id = f"{model}-seed{seed}"
            for family, count in (("F3", 32), ("F4", 16)):
                for index in range(count):
                    rows.append(
                        {
                            "family": family,
                            "scope_id": f"{family}-synthetic-scope",
                            "case_id": f"{family}-case-{index:02d}",
                            "split": "evaluation",
                            "model_kind": model,
                            "seed": seed,
                            "formal_run_id": run_id,
                            "formal_updates": 32000,
                        }
                    )
    t1 = {
        "schema": join.T1_SCHEMA,
        "report_id": "t1-observed-model-case-run-evidence-binding-v1",
        "status": "typed_evidence_gap_fail_closed",
        "fail_closed": True,
        "observed_case_runs": 0,
        "required_case_runs": 432,
        "missing_case_runs": 432,
        "T1_numerical": False,
        "credit": 0,
        "formal_run_ids": sorted(join.RUN_IDS),
        "fixed_t1_projection": {"expected_row_count": 432, "rows": rows},
    }
    formal = {
        "schema": join.FORMAL_SCHEMA,
        "report_id": "core-formal-training-release-root-admission-gap-v1",
        "scope": {
            "models": list(join.MODELS),
            "seeds": list(join.SEEDS),
            "run_count": 9,
            "run_ids": list(join.RUN_IDS),
        },
        "decision": {
            "status": "blocked_fail_closed",
            "launch_allowed": False,
            "formal_eligible": False,
            "qualification_credit": 0,
            "credit": 0,
            "non_authorizing_adapter": True,
        },
        "execution_constraints": {
            "read_only": True,
            "bounded_json_only": True,
            "hdf5_opened": False,
            "checkpoint_opened": False,
            "training_started": False,
            "gpu_started": False,
            "worker_started": False,
            "queue_submitted": False,
            "registry_written": False,
            "ledger_written": False,
            "denominator_written": False,
            "gate_written": False,
            "completion_written": False,
            "plan_written": False,
            "historical_receipt_written": False,
        },
        "observations": {
            "trusted_root": {
                "trusted_root_authenticated": False,
                "admission_ready": False,
            },
            "terminal_evidence": {"complete": False},
        },
        "missing_blockers": ["SYNTHETIC_ROOT_NOT_AUTHENTICATED"],
    }
    return t1, formal


def _write_fixture(tmp_path: Path, t1: dict, formal: dict) -> Path:
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/t1.json").write_text(json.dumps(t1), encoding="utf-8")
    (tmp_path / "reports/formal.json").write_text(json.dumps(formal), encoding="utf-8")
    contract = {
        "schema": join.CONTRACT_SCHEMA,
        "contract_id": "formal-release-observed-case-run-join-v1",
        "version": 1,
        "input_reports": {
            "t1_observed_case_run_binding": {
                "path": "reports/t1.json",
                "schema": join.T1_SCHEMA,
                "report_id": "t1-observed-model-case-run-evidence-binding-v1",
            },
            "formal_release_root_admission": {
                "path": "reports/formal.json",
                "schema": join.FORMAL_SCHEMA,
                "report_id": "core-formal-training-release-root-admission-gap-v1",
            },
        },
        "fixed_scope": {
            "families": list(join.FAMILIES),
            "models": list(join.MODELS),
            "seeds": list(join.SEEDS),
            "f3_case_count": 32,
            "f4_evaluation_case_count": 16,
            "required_case_runs": 432,
        },
        "policy": {
            "bounded_json_only": True,
            "fail_closed": True,
            "external_authority_required_for_counting": True,
            "no_inventory_copy": True,
            "no_core_state_writes": True,
        },
    }
    contract_path = tmp_path / "join.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    return contract_path


def test_shape_complete_synthetic_fixture_stays_zero_credit(tmp_path: Path) -> None:
    t1, formal = _synthetic_payloads()
    contract = _write_fixture(tmp_path, t1, formal)

    report = join.build_report(tmp_path, contract)

    assert report["aggregate_join"]["join_valid"] is True
    assert report["aggregate_join"]["inventory_copied"] is False
    assert report["decision"]["launch_allowed"] is False
    assert report["decision"]["credit"] == 0
    assert report["aggregate_join"]["observed_case_runs"] == 0


def test_duplicate_projection_identity_is_fail_closed(tmp_path: Path) -> None:
    t1, formal = _synthetic_payloads()
    t1["fixed_t1_projection"]["rows"][1] = deepcopy(t1["fixed_t1_projection"]["rows"][0])
    contract = _write_fixture(tmp_path, t1, formal)

    with pytest.raises(join.JoinError, match="repeats row identity"):
        join.build_report(tmp_path, contract)


def test_formal_release_claim_cannot_open_the_aggregate(tmp_path: Path) -> None:
    t1, formal = _synthetic_payloads()
    formal["decision"]["launch_allowed"] = True
    formal["decision"]["formal_eligible"] = True
    formal["decision"]["credit"] = 1
    contract = _write_fixture(tmp_path, t1, formal)

    with pytest.raises(join.JoinError, match="must be False|must be 0"):
        join.build_report(tmp_path, contract)


def test_checked_in_gap_report_remains_closed() -> None:
    report_path = ROOT / join.DEFAULT_REPORT.relative_to(ROOT)
    if not report_path.exists():
        pytest.skip("checked-in report is generated after implementation")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert join.validate_report(report, ROOT) == []
    assert report["decision"]["credit"] == 0

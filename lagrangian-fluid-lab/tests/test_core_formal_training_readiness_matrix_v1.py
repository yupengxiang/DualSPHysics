from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys


LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT))

from scripts import core_formal_training_readiness_matrix_v1 as matrix


REPORT_PATH = LAB_ROOT / matrix.REPORT_REL


def _report() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_report_is_the_fixed_nine_run_matrix() -> None:
    report = _report()
    assert report["schema"] == matrix.SCHEMA
    assert report["scope"] == {
        "models": ["graph_raw", "graph_residual", "mlp"],
        "seeds": [17, 29, 43],
        "run_count": 9,
        "run_ids": list(matrix.RUN_IDS),
    }
    assert [row["run_id"] for row in report["runs"]] == list(matrix.RUN_IDS)


def test_all_runs_are_explicitly_blocked_without_spec_or_launch() -> None:
    report = _report()
    assert report["decision"] == {
        "status": "blocked_fail_closed",
        "all_runs_blocked": True,
        "spec_created": False,
        "launch_allowed": False,
        "no_spec_created": True,
        "no_launch": True,
        "reason": report["decision"]["reason"],
    }
    assert report["formal_spec_scan"]["formal_spec_paths"] == []
    assert all(row["status"] == "blocked_fail_closed" for row in report["runs"])
    assert all(row[key] is False for row in report["runs"] for key in (
        "formal_spec", "formal_release", "root_trust", "terminal_evidence", "credit"))


def test_current_inputs_and_campaign_status_are_fail_closed() -> None:
    report = _report()
    assert report["source_closure"]["formal_release"] is False
    assert report["source_closure"]["root_admission_granted"] is False
    assert report["source_closure"]["launch_allowed"] is False
    assert report["training_contract"]["status"] == "planning_only"
    assert report["current_manifest"]["formal_release"] is False
    assert report["core_campaign_status"]["training_runs"] == []
    assert report["core_campaign_status"]["missing_training_runs"] == list(matrix.RUN_IDS)


def test_diagnostic_current_manifest_evidence_cannot_be_promoted() -> None:
    report = _report()
    for model in matrix.MODELS:
        evidence = report["current_manifest_evidence"][model]
        assert evidence["seeds"] == list(matrix.SEEDS)
        assert evidence["diagnostic_only"] is True
        assert evidence["formal"] is False
        assert evidence["formal_eligible"] is False
        assert evidence["credit"] == 0
        assert evidence["formal_training_runs_counted"] == 0


def test_checked_in_report_validates_against_current_inputs() -> None:
    report = _report()
    assert matrix.validate_report(report, LAB_ROOT) == []


def test_validator_rejects_credit_or_spec_mutation() -> None:
    report = _report()
    mutated = deepcopy(report)
    mutated["runs"][0]["credit"] = True
    mutated["runs"][0]["credit_value"] = 1
    mutated["formal_spec_scan"]["formal_counts"][matrix.RUN_IDS[0]] = 1
    assert matrix.validate_report(mutated, LAB_ROOT)


def test_validator_rejects_input_hash_mutation() -> None:
    report = _report()
    mutated = deepcopy(report)
    mutated["inputs"]["current_manifest"]["sha256"] = "0" * 64
    errors = matrix.validate_report(mutated, LAB_ROOT)
    assert any("input current_manifest sha256 mismatch" in error for error in errors)


def test_matrix_builder_is_read_only_and_does_not_replay_seed17_auditor() -> None:
    report = matrix._build_report(LAB_ROOT, observed_at_utc="2026-09-29T00:00:00Z")
    assert matrix.validate_report(report, LAB_ROOT) == []
    source = Path(matrix.__file__).read_text(encoding="utf-8")
    assert "f3_graph_raw_seed17_formal_training_readiness" not in source
    assert report["side_effects"]["queue_submitted"] is False
    assert report["side_effects"]["gpu_started"] is False

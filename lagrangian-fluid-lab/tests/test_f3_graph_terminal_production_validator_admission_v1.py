"""Regression tests for the independent F3 validator admission sidecar."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import f3_graph_terminal_production_validator_admission_v1 as admission


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/F3-GRAPH-TERMINAL-PRODUCTION-VALIDATOR-ADMISSION-2026-09-29.json"


def _rebind(receipt: dict[str, object]) -> None:
    core = dict(receipt)
    core.pop("receipt_binding_sha256", None)
    receipt["receipt_binding_sha256"] = admission.canonical_digest(core)


def test_default_report_is_source_bound_but_never_authorizing() -> None:
    report = admission.build_report(ROOT)

    assert admission.validate_report(report, root=ROOT) == []
    assert report["status"] == "blocked_fail_closed"
    assert report["receipt_valid"] is True
    assert report["source_bound"] is True
    assert report["admission_granted"] is False
    assert report["capability_admitted"] is False
    assert report["launch_allowed"] is False
    assert report["credit"] == 0
    assert report["authority_boundary"]["token_is_formal_authority"] is False
    assert report["runtime_evidence"]["independent_process_proof_present"] is False


def test_receipt_binds_validator_source_and_its_tests_by_pinned_sha() -> None:
    receipt = admission.build_receipt(ROOT)
    source = receipt["source_binding"]
    assert source["wrapped_validator_schema"] == admission.WRAPPED_VALIDATOR_SCHEMA
    assert source["wrapped_capability_schema"] == admission.WRAPPED_CAPABILITY_SCHEMA
    assert source["validator_source"]["sha256"] == admission.EXPECTED_VALIDATOR_SOURCE_SHA256
    assert source["validator_tests"]["sha256"] == admission.EXPECTED_VALIDATOR_TEST_SHA256
    assert admission.validate_receipt(receipt, root=ROOT) == []


def test_fixed_graph_contract_covers_both_models_and_all_three_seeds() -> None:
    receipt = admission.build_receipt(ROOT)
    target = receipt["target_contract"]
    assert target == {
        "model_kinds": ["graph_raw", "graph_residual"],
        "seeds": [17, 29, 43],
        "hidden": 16,
        "updates": 500,
        "case_id": admission.CASE_ID,
        "split": "test",
        "transitions": 835,
        "frames": 836,
    }
    commands = receipt["evaluator_command_binding"]["commands"]
    assert {(row["model_kind"], row["seed"]) for row in commands} == {
        (model, seed) for model in admission.MODEL_KINDS for seed in admission.SEEDS
    }


def test_namespace_is_one_shot_32_hex_but_freshness_is_not_attested() -> None:
    receipt = admission.build_receipt(ROOT)
    namespace = receipt["namespace"]
    assert admission.NAMESPACE_RE.fullmatch(namespace["value"])
    assert int(namespace["value"], 16) != 0
    assert namespace["fresh"] is True
    assert namespace["one_shot"] is True
    assert namespace["reuse_forbidden"] is True
    assert namespace["freshness_attested"] is False
    assert namespace["materialized"] is False
    assert admission.validate_receipt(receipt, root=ROOT) == []


def test_each_evaluator_command_has_exact_digest_and_artifact_root_policy() -> None:
    receipt = admission.build_receipt(ROOT)
    binding = receipt["evaluator_command_binding"]
    for row in binding["commands"]:
        identity = {
            "argv": row["argv"],
            "cwd": row["cwd"],
            "env_overrides": row["env_overrides"],
        }
        assert row["command_sha256"] == admission.canonical_digest(identity)
        assert row["exact_command_required"] is True
        for artifact in row["artifacts"].values():
            assert artifact["root_contained"] is True
            assert artifact["symlink_components_rejected"] is True
            assert artifact["hardlink_count_required"] == 1
            assert artifact["observed_hardlink_count"] is None
            assert artifact["content_opened"] is False


def test_process_proof_is_required_but_absent_and_non_authoritative() -> None:
    receipt = admission.build_receipt(ROOT)
    proof = receipt["independent_process_proof_requirement"]
    assert proof["required"] is True
    assert proof["independent"] is True
    assert proof["producer"] == "subprocess.Popen"
    assert proof["wait_method"] == "Popen.wait"
    assert proof["proof_present"] is False
    assert proof["proof_verified"] is False
    assert proof["authoritative"] is False


def test_command_digest_drift_fails_closed_even_when_receipt_digest_is_rebound() -> None:
    receipt = deepcopy(admission.build_receipt(ROOT))
    row = receipt["evaluator_command_binding"]["commands"][0]
    row["argv"] = list(row["argv"])
    row["argv"].append("--drift")
    _rebind(receipt)
    errors = admission.validate_receipt(receipt, root=ROOT)
    assert errors
    assert any("canonical" in error or "drift" in error for error in errors)


def test_artifact_root_escape_and_hardlink_policy_fail_closed() -> None:
    receipt = deepcopy(admission.build_receipt(ROOT))
    artifact = receipt["evaluator_command_binding"]["commands"][0]["artifacts"]["trajectory"]
    artifact["path"] = "/tmp/outside-trajectory.h5"
    _rebind(receipt)
    errors = admission.validate_receipt(receipt, root=ROOT)
    assert errors
    assert any("root" in error or "exact" in error for error in errors)

    receipt = deepcopy(admission.build_receipt(ROOT))
    artifact = receipt["evaluator_command_binding"]["commands"][0]["artifacts"]["trajectory"]
    artifact["hardlink_count_required"] = 2
    _rebind(receipt)
    errors = admission.validate_receipt(receipt, root=ROOT)
    assert errors
    assert any("hardlink" in error for error in errors)


def test_forged_token_or_positive_authority_cannot_be_added() -> None:
    receipt = deepcopy(admission.build_receipt(ROOT))
    receipt["token"] = "claimed-token"
    _rebind(receipt)
    errors = admission.validate_receipt(receipt, root=ROOT)
    assert errors
    assert any("unknown" in error for error in errors)

    report = admission.build_report(ROOT)
    forged = deepcopy(report)
    forged["admission_granted"] = True
    assert admission.validate_report(forged, root=ROOT)


def test_committed_report_is_current_and_cli_verifiable(capsys: pytest.CaptureFixture[str]) -> None:
    committed = json.loads(REPORT.read_text(encoding="utf-8"))
    current = admission.build_report(ROOT)
    assert committed == current
    assert admission.validate_report(committed, root=ROOT) == []
    assert admission.main(["--verify-report", str(REPORT), "--root", str(ROOT)]) == 0
    assert '"valid":true' in capsys.readouterr().out

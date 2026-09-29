"""Independent post-fix A8 bridge security rerun.

This test set deliberately reads only bounded JSON/source inputs.  It does
not import or exercise a reader, model, scheduler, worker, GPU, or any large
bundle asset.  The mutation cases are constructed from the hardened bridge
contracts and the current bounded diagnostic pair, rather than from the
historical 2182cb6d audit fixtures.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from scripts import core_product_repro_bridge_v1 as bridge


LAB = Path(__file__).resolve().parents[1]
BRIDGE_SOURCE = LAB / "scripts/core_product_repro_bridge_v1.py"
BUNDLE = LAB / "campaigns/core-v1/reproduction/a8-full-reproduce-v2/bundle.json"
DIAGNOSTIC_PAIR = LAB / "campaigns/core-v1/reproduction/a8-cross-host-diagnostic-pair-v1.json"
BOUNDED_CONTRACTS = (
    LAB / "campaigns/core-v1/evidence/cross-host-reproduction-contract-20260920.json",
    LAB / "reports/A8-INDEPENDENT-REPRODUCTION-READINESS-CONTRACT-V1-2026-09-29.json",
    LAB / "reports/A8-TRUSTED-ROOT-EXTERNAL-HOST-ATTESTATION-CONTRACT-V1-2026-09-29.json",
)
REPORT = LAB / "reports/A8-PACKAGE-REPRO-BRIDGE-POST-FIX-SECURITY-RERUN1-2026-09-29.json"
MAX_BOUNDED_BYTES = bridge.MAX_BRIDGE_JSON_BYTES


def _read_bounded_json(path: Path) -> dict:
    assert path.is_file()
    assert path.stat().st_size <= MAX_BOUNDED_BYTES
    value = json.loads(path.read_text())
    assert isinstance(value, dict)
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ref(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(LAB.parent).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def test_post_fix_inputs_are_bounded_and_report_bindings_are_current():
    report = _read_bounded_json(REPORT)
    assert report["schema"] == "core.a8.package_repro_bridge_post_fix_security_rerun.v1"
    assert report["review_id"] == "A8-PRB-POST-FIX-RERUN1-2026-09-29"
    assert report["scope"]["historical_2182cb6d_inputs_read"] is False

    expected = [BRIDGE_SOURCE, BUNDLE, DIAGNOSTIC_PAIR, *BOUNDED_CONTRACTS]
    actual = report["input_bindings"]
    assert [item["path"] for item in actual] == [
        path.relative_to(LAB.parent).as_posix() for path in expected
    ]
    for path, item in zip(expected, actual):
        assert item["bytes"] == path.stat().st_size
        assert item["sha256"] == _sha256(path)
        assert path.stat().st_size <= MAX_BOUNDED_BYTES


def test_authority_mutation_is_rejected_by_hardened_reader_projection():
    bundle = _read_bounded_json(BUNDLE)
    mutated_reader = {
        "schema": "core.verification.v1",
        "passed": True,
        "case_count": bundle["case_count"],
        "diagnostic_only": False,
        "formal_training": True,
        "full_product_reproduction": True,
        "qualification_credit": 1,
    }

    projection, blockers = bridge._reader_report_projection(
        mutated_reader, label="post-fix authority mutation"
    )

    assert projection["passed"] is False
    assert projection["diagnostic_only"] is True
    assert projection["formal_training"] is False
    assert projection["full_product_reproduction"] is False
    assert projection["qualification_credit"] == 0
    assert any("diagnostic_only_must_be_True" in item for item in blockers)
    assert any("formal_training_must_be_False" in item for item in blockers)
    assert any("full_product_reproduction_must_be_False" in item for item in blockers)
    assert any("qualification_credit_must_be_0" in item for item in blockers)


def test_duplicate_host_mutation_is_rejected_by_hardened_pair_projection():
    pair = _read_bounded_json(DIAGNOSTIC_PAIR)
    mutated_pair = copy.deepcopy(pair)
    observed_hosts = mutated_pair["observed_hosts"]
    assert isinstance(observed_hosts, list) and len(observed_hosts) == 2
    mutated_pair["observed_hosts"] = [observed_hosts[0], observed_hosts[0]]
    mutated_pair["distinct_host_evidence"] = True

    rollout, score, blockers = bridge._diagnostic_pair_projection(
        {"path": DIAGNOSTIC_PAIR.name, "bytes": DIAGNOSTIC_PAIR.stat().st_size,
         "sha256": _sha256(DIAGNOSTIC_PAIR)},
        mutated_pair,
    )

    assert rollout["passed"] is False
    assert score["passed"] is False
    assert rollout["host_identity_contract_passed"] is False
    assert rollout["distinct_host_evidence"] is False
    assert rollout["scientific_qualification"] is False
    assert score["qualification_credit"] == 0
    assert "diagnostic_pair_host_identities_not_distinct" in blockers


def test_real_bundle_remains_reader_only_and_bounded_contracts_zero_credit():
    bundle = _read_bounded_json(BUNDLE)
    assert bundle["schema"] == "core.reader_bundle.v2"
    assert bundle["case_count"] == 32
    assert bundle["checkpoint_count"] == 0
    assert bundle["model_reproduction_supported"] is False
    assert bundle["full_core_release"] is False
    assert "scientific qualification remains separate" in bundle["scope"]

    pair = _read_bounded_json(DIAGNOSTIC_PAIR)
    evidence = pair["evidence"]
    assert evidence["diagnostic_only"] is True
    assert evidence["formal_training"] is False
    assert evidence["qualification_credit"] == 0
    assert evidence["qualification_claim"] == "none"

    cross_host, independent, trusted_root = (
        _read_bounded_json(path) for path in BOUNDED_CONTRACTS
    )
    assert cross_host["diagnostic_only"] is True
    assert cross_host["formal_training_count"] == 0
    assert cross_host["full_product_reproduction"] is False
    for contract in (independent, trusted_root):
        assert contract["diagnostic_only"] is True
        assert contract["formal_admission"] is False
        assert contract["formal_training"] is False
        assert contract["full_product_reproduction"] is False
        assert contract["independent_reproduction"] is False
        assert contract["qualification_credit"] == 0
        assert contract["credit"] == 0
        assert contract["readiness_pass"] is False


def test_post_fix_report_records_fail_closed_result_without_authority():
    report = _read_bounded_json(REPORT)
    assert report["status"] == "passed_fail_closed_post_fix"
    checks = report["checks"]
    assert checks["authority_mutation"]["rejected"] is True
    assert checks["duplicate_host_mutation"]["rejected"] is True
    assert checks["current_bundle"]["reader_only"] is True
    assert checks["current_bundle"]["qualification_credit"] == 0
    assert report["claims"] == {
        "diagnostic_only": True,
        "formal_admission": False,
        "full_product_reproduction": False,
        "independent_reproduction": False,
        "qualification_credit": 0,
        "registry_mutated": False,
        "ledger_mutated": False,
        "denominator_mutated": False,
        "gate_mutated": False,
        "completion_mutated": False,
    }

"""Synthetic-only tests for the seed29 authority projection gap inventory."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f3_graph_raw_hidden16_seed29_authority_projection_gap_v1 as gap


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _observed_report(path: Path) -> None:
    _write_json(
        path,
        {
            "schema": "core.f3.graph_raw.hidden16.seed29.diagnostic_admission.v1.report",
            "status": "blocked_fail_closed",
            "source_bound": False,
            "admission_granted": False,
            "blocked_reasons": [
                "fail-closed: scheduler-owned GPU UUID/PCI snapshot is required; implicit probing is disabled"
            ],
        },
    )


def test_inventory_is_seed29_only_and_never_reaches_popen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = tmp_path / "observed-admission.json"
    _observed_report(observed)
    monkeypatch.setattr(
        gap.admission,
        "TRUSTED_SCHEDULER_PUBLIC_KEY_PATH",
        tmp_path / "missing-trusted-key",
    )
    monkeypatch.setattr(
        gap.admission,
        "EXTERNAL_SCHEDULER_ROOT",
        tmp_path / "missing-scheduler-root",
    )

    calls: list[object] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("gap inventory must not call Popen")

    monkeypatch.setattr(gap.runner, "_REAL_POPEN", forbidden)
    report = gap.build_report(observed_admission_report=observed)

    assert report["status"] == "blocked_projection_gap"
    assert report["scope"]["seed"] == 29
    assert report["scope"]["model_kind"] == "graph_raw"
    assert report["scope"]["hidden"] == 16
    assert report["external_authority"]["verified"] is False
    assert report["resource_binding"]["verified"] is False
    assert report["projection_contract"]["safe_local_projection_implemented"] is False
    assert report["projection_contract"]["producer_reissue_required"] is True
    assert "trusted_scheduler_ed25519_public_key" in report["missing_requirements"]
    assert "external_scheduler_authority_document" in report["missing_requirements"]
    assert "scheduler_owned_resource_snapshot.gpu_uuid_pci" in report["missing_requirements"]
    assert "independently_bound_terminal_receipt" in report["missing_requirements"]
    assert report["runner_boundary"]["popen_attempted"] is False
    assert report["runner_boundary"]["terminal_receipt_present"] is False
    assert report["credit"] == 0
    assert calls == []
    assert "seed17" not in gap.canonical_json(report)
    assert gap.validate_report(report) == []


def test_supplied_legacy_receipt_is_reported_without_local_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = tmp_path / "observed-admission.json"
    source_receipt = tmp_path / "legacy-receipt.json"
    _observed_report(observed)
    _write_json(
        source_receipt,
        {
            "schema": "core.f3.graph_raw.hidden16.seed29.diagnostic_admission.v1",
            "status": "issued",
            "identity": {"seed": 29, "model_kind": "graph_raw", "hidden": 16},
        },
    )
    monkeypatch.setattr(gap.admission, "TRUSTED_SCHEDULER_PUBLIC_KEY_PATH", tmp_path / "key")
    monkeypatch.setattr(gap.admission, "EXTERNAL_SCHEDULER_ROOT", tmp_path / "scheduler")

    report = gap.build_report(
        observed_admission_report=observed,
        source_receipt=source_receipt,
    )

    assert report["source_receipt"]["present"] is True
    assert report["source_receipt"]["status"] == "missing_current_fields"
    assert "authority" in report["source_receipt"]["missing_fields"]
    assert "identity.external_authority" in report["source_receipt"]["missing_fields"]
    assert report["projection_contract"]["safe_local_repair"] is False
    assert report["projection_contract"]["durable_receipt_written"] is False
    assert report["projection_contract"]["runner_consumable"] is False
    assert report["projection_contract"]["historical_receipt_rewritten"] is False
    assert gap.validate_report(report) == []


def test_missing_source_receipt_is_an_explicit_gap(tmp_path: Path) -> None:
    observed = tmp_path / "observed-admission.json"
    _observed_report(observed)
    report = gap.build_report(
        observed_admission_report=observed,
        source_receipt=tmp_path / "does-not-exist.json",
    )

    assert report["source_receipt"]["present"] is False
    assert report["source_receipt"]["status"] == "unreadable_or_absent"
    assert "current_authority_bound_receipt" in report["missing_requirements"]
    assert report["external_authority"]["verified"] is False
    assert gap.validate_report(report) == []


def test_report_validator_rejects_credit_or_side_effect_mutation(tmp_path: Path) -> None:
    observed = tmp_path / "observed-admission.json"
    _observed_report(observed)
    report = gap.build_report(observed_admission_report=observed)

    forged_credit = copy.deepcopy(report)
    forged_credit["credit"] = 1
    assert gap.validate_report(forged_credit)

    forged_effect = copy.deepcopy(report)
    forged_effect["side_effects"]["popen_attempted"] = True
    assert gap.validate_report(forged_effect)


def test_contract_source_inventory_contains_only_seed29_paths(tmp_path: Path) -> None:
    observed = tmp_path / "observed-admission.json"
    _observed_report(observed)
    report = gap.build_report(observed_admission_report=observed)

    assert set(report["contract_sources"]) == {
        "seed29_admission",
        "seed29_runner",
        "seed29_admission_tests",
        "seed29_runner_tests",
    }
    assert all("seed29" in item["path"] for item in report["contract_sources"].values())
    assert report["admission_contract"]["signature_algorithm"] == "ed25519"
    assert report["admission_contract"]["caller_claim_can_substitute"] is False
    assert report["admission_contract"]["implicit_resource_probe_allowed"] is False
    assert report["side_effects"]["registry_writes"] == 0
    assert report["side_effects"]["plan_writes"] == 0

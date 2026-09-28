"""Synthetic and source-bound tests for the F3 coarse admission adapter."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import f3_material_coarse_host_io_admission_v1 as adapter


ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / adapter.PROPOSAL
HOST_IO = ROOT / adapter.HOST_IO_RECEIPT
REPORT = ROOT / "reports/F3-MATERIAL-COARSE-HOST-IO-ADMISSION-2026-09-28.json"
ZH_REPORT = ROOT / "reports/F3-MATERIAL-COARSE-HOST-IO-ADMISSION-2026-09-28.zh-CN.md"


@pytest.fixture(scope="module")
def current_report() -> dict:
    # The source HDF5 is hashed as bytes only; this fixture never opens it as
    # HDF5 and the adapter has no HDF5 import or reader path.
    return adapter.build_admission(ROOT)


def _tiny_source(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic-source.h5"
    path.write_bytes(b"synthetic byte-only source")
    return path


def _write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_positive_probe_is_source_bound_but_never_authorizing(current_report: dict) -> None:
    assert adapter.validate_admission(current_report) == []
    assert current_report["status"] == "diagnostic_admission_blocked"
    checks = current_report["checks"]
    assert checks["proposal_contract_valid"] is True
    assert checks["probe_pass"] is True
    assert checks["measurement_complete"] is True
    assert checks["fresh_attempt_namespace"] is True
    assert checks["normalized_argv"] is True
    assert checks["launch_cwd"] is True
    assert checks["resource_projection_shape"] is True
    assert checks["source_h5_binding"] is True
    assert checks["job_spec_binding"] is True
    assert checks["core_material_binding"] is True
    assert checks["core_runtime_binding"] is True

    decision = current_report["decision"]
    assert decision["root_authorization_present"] is False
    assert decision["scheduler_authorization_present"] is False
    assert decision["launch_admitted"] is False
    assert decision["worker_launch_authorized"] is False
    assert decision["formal"] is False
    assert decision["credit"] == 0
    assert current_report["resource_projection"]["gpu_forbidden"] is True
    assert current_report["resource_projection"]["scheduler_owned_io_verified"] is False


def test_source_hash_drift_fails_closed_without_hdf5_open(tmp_path: Path) -> None:
    report = adapter.build_admission(ROOT, source_h5_path=_tiny_source(tmp_path))

    assert report["status"] == "failed_closed"
    assert report["checks"]["source_h5_binding"] is False
    assert report["launch_admitted"] is False
    assert report["execution_controls"]["source_hdf5_hash_only"] is True
    assert report["execution_controls"]["source_hdf5_opened_as_hdf5"] is False
    assert report["execution_controls"]["production_hdf5_opened"] is False


def test_proposal_field_drift_is_rejected(tmp_path: Path) -> None:
    proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    proposal["candidate"]["substeps"] = 4
    mutated = _write_json(tmp_path / "proposal-drift.json", proposal)
    report = adapter.build_admission(
        ROOT, proposal_path=mutated, source_h5_path=_tiny_source(tmp_path)
    )

    assert report["status"] == "failed_closed"
    assert report["checks"]["proposal_candidate_fields"] is False
    assert report["checks"]["proposal_contract_valid"] is False
    assert report["launch_admitted"] is False
    assert report["credit"] == 0


def test_measurement_incomplete_receipt_is_rejected(tmp_path: Path) -> None:
    receipt = json.loads(HOST_IO.read_text(encoding="utf-8"))
    receipt["probe"]["measurement_complete"] = False
    mutated = _write_json(tmp_path / "measurement-incomplete.json", receipt)
    report = adapter.build_admission(
        ROOT, host_io_receipt_path=mutated, source_h5_path=_tiny_source(tmp_path)
    )

    assert report["status"] == "failed_closed"
    assert report["checks"]["measurement_complete"] is False
    assert report["checks"]["host_io_receipt_valid"] is False
    assert report["diagnostic_errors"]["host_io_validation"]
    assert report["worker_launch_authorized"] is False


def test_resource_policy_drift_is_rejected(tmp_path: Path) -> None:
    proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    proposal["resource_admission"]["gpu_forbidden"] = False
    mutated = _write_json(tmp_path / "resource-policy-drift.json", proposal)
    report = adapter.build_admission(
        ROOT, proposal_path=mutated, source_h5_path=_tiny_source(tmp_path)
    )

    assert report["status"] == "failed_closed"
    assert report["checks"]["proposal_resource_policy"] is False
    assert report["launch_admitted"] is False


def test_host_family_scope_drift_is_rejected(tmp_path: Path) -> None:
    receipt = json.loads(HOST_IO.read_text(encoding="utf-8"))
    receipt["request"]["family_scope"] = ["F4"]
    mutated = _write_json(tmp_path / "family-scope-drift.json", receipt)
    report = adapter.build_admission(
        ROOT, host_io_receipt_path=mutated, source_h5_path=_tiny_source(tmp_path)
    )

    assert report["status"] == "failed_closed"
    assert report["checks"]["host_family_scope"] is False
    assert report["worker_launch_authorized"] is False


def test_claimed_authorization_cannot_become_an_admission(tmp_path: Path) -> None:
    proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    proposal["authorization"]["status"] = "granted"
    mutated = _write_json(tmp_path / "untrusted-authorization.json", proposal)
    report = adapter.build_admission(
        ROOT, proposal_path=mutated, source_h5_path=_tiny_source(tmp_path)
    )

    assert report["status"] == "failed_closed"
    assert report["authorization_boundary"]["root_authorization_present"] is False
    assert report["authorization_boundary"]["scheduler_authorization_present"] is False
    assert "untrusted_authorization_claim_not_accepted" in report["blocking_reasons"]
    assert report["launch_admitted"] is False
    assert report["formal"] is False
    assert report["credit"] == 0


def test_serialized_fail_closed_markers_cannot_drift(current_report: dict) -> None:
    bad = deepcopy(current_report)
    bad["decision"]["formal"] = True
    bad["input_bindings"]["source_h5"]["hash_only"] = False
    bad["execution_controls"]["registry_mutations"] = 1

    errors = adapter.validate_admission(bad)
    assert "decision.formal" in errors
    assert "input_bindings.source_h5.hash_only" in errors
    assert "execution_controls.registry_mutations" in errors


def test_committed_machine_and_chinese_reports_are_valid(current_report: dict) -> None:
    committed = json.loads(REPORT.read_text(encoding="utf-8"))
    assert adapter.validate_admission(committed) == []
    assert committed["status"] == "diagnostic_admission_blocked"
    assert committed["input_bindings"]["source_h5"]["hash_only"] is True
    assert committed["decision"]["probe_pass"] is True
    assert committed["decision"]["measurement_complete"] is True
    assert committed["decision"]["launch_admitted"] is False
    assert committed["decision"]["worker_launch_authorized"] is False
    assert committed["decision"]["formal"] is False
    assert committed["decision"]["credit"] == 0
    assert ZH_REPORT.read_text(encoding="utf-8").startswith(
        "# F3 coarse material host-I/O diagnostic admission"
    )
    assert committed == current_report


def test_report_writers_never_overwrite(tmp_path: Path, current_report: dict) -> None:
    destination = tmp_path / "admission.json"
    zh_destination = tmp_path / "admission.zh-CN.md"
    assert adapter.write_report(current_report, destination) == destination
    assert adapter.write_zh_cn(current_report, zh_destination) == zh_destination
    with pytest.raises(FileExistsError):
        adapter.write_report(current_report, destination)
    with pytest.raises(FileExistsError):
        adapter.write_zh_cn(current_report, zh_destination)

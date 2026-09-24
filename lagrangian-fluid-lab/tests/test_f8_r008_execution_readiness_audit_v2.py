from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_execution_readiness_audit_v2 as audit


def test_r008_v2_reconciles_retained_lattice_and_keeps_zero_credit_boundary() -> None:
    value = audit.build_audit()
    geometry = value["retained_geometry"]

    assert geometry["particle_count"] == 6656
    assert (geometry["x_plane_count"], geometry["y_plane_count"], geometry["z_plane_count"]) == (32, 16, 13)
    assert geometry["nominal_2H_over_dp_intervals"] == 12
    assert geometry["contract_expected_production_layers"] == 12
    assert geometry["z_count_interpretation"] == "contract_conflict"
    assert geometry["contract_expected_particle_count"] == 6144
    assert geometry["native_particle_count_matches_contract"] is False
    assert value["status"] == "blocked_preexecution_semantics_closure"
    assert value["readiness_pass"] is False
    assert value["qualification_credit"] == 0
    assert value["execution_authority"]["solver"] is False
    assert value["execution_controls"]["queue_mutation"] == 0
    assert "profile_sampling" in value["missing_metric_definitions"]
    assert "reference_velocity" in value["missing_metric_definitions"]
    assert "transverse_rms" in value["missing_metric_definitions"]
    assert "flux_normalization" in value["missing_metric_definitions"]
    assert "cross_resolution_alignment" in value["missing_metric_definitions"]


def test_r008_v2_closes_direct_evidence_and_supersedes_v1_provenance_gap() -> None:
    value = audit.build_audit()
    paths = {item["path"] for item in value["evidence"]}
    assert audit.SCOPE.as_posix() in paths
    assert audit.FLUID_VTK.as_posix() in paths
    assert audit.V1_SCRIPT.as_posix() in paths
    assert audit.PARTICLE_COUNT_CONSUMER.as_posix() in paths
    assert audit.SCRIPT.as_posix() in paths
    assert audit.TEST.as_posix() in paths
    assert "legacy VTK decoder" in value["supersedes"]["reason"]
    assert all(len(item["sha256"]) == 64 for item in value["evidence"])


def test_r008_v2_writer_is_immutable_and_verifier_recomputes(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    assert audit.write_audit(target) == target
    assert json.loads(target.read_text(encoding="utf-8")) == audit.verify_audit(target)
    with pytest.raises(FileExistsError, match="immutable R008 execution-readiness audit v2"):
        audit.write_audit(target)

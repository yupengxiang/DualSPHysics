from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_execution_readiness_audit_v1 as audit


def test_r008_readiness_audit_reconciles_retained_planes_without_claiming_qualification() -> None:
    value = audit.build_audit()
    geometry = value["retained_geometry"]

    assert geometry["particle_count"] == 6656
    assert geometry["x_plane_count"] == 32
    assert geometry["y_plane_count"] == 16
    assert geometry["z_plane_count"] == 13
    assert geometry["nominal_2H_over_dp_intervals"] == 12
    assert geometry["contract_expected_production_layers"] == 12
    assert geometry["z_count_interpretation"] == "unresolved"
    assert value["status"] == "blocked_preexecution_semantics_closure"
    assert value["readiness_pass"] is False
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert value["execution_authority"]["solver"] is False
    assert "profile_sampling" in value["missing_metric_definitions"]
    assert "reference_velocity" in value["missing_metric_definitions"]
    assert "transverse_rms" in value["missing_metric_definitions"]
    assert "flux_normalization" in value["missing_metric_definitions"]
    assert "cross_resolution_alignment" in value["missing_metric_definitions"]


def test_r008_readiness_audit_is_bound_to_current_static_evidence() -> None:
    value = audit.build_audit()
    paths = {item["path"] for item in value["evidence"]}
    assert audit.SCOPE.as_posix() in paths
    assert audit.FLUID_VTK.as_posix() in paths
    assert audit.PARSER.as_posix() in paths
    assert audit.SCRIPT.as_posix() in paths
    assert audit.TEST.as_posix() in paths
    assert all(len(item["sha256"]) == 64 for item in value["evidence"])


def test_audit_writer_is_immutable_and_verifier_recomputes(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    assert audit.write_audit(target) == target
    persisted = json.loads(target.read_text(encoding="utf-8"))
    assert persisted == audit.verify_audit(target)
    with pytest.raises(FileExistsError, match="immutable R008 execution-readiness audit"):
        audit.write_audit(target)

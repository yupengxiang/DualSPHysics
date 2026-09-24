from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_execution_readiness_audit_v3 as audit


def test_r008_v3_distinguishes_its_native_count_from_legacy_r001_consumer() -> None:
    value = audit.build_audit()
    geometry = value["retained_geometry"]

    assert geometry["particle_count"] == 6656
    assert geometry["z_plane_count"] == 13
    assert geometry["nominal_2H_over_dp_intervals"] == 12
    assert geometry["resolution_contract_layer_value"] == 12
    assert geometry["r008_preflight_expected_particle_count"] == 6656
    assert geometry["r008_particle_count_matches_native"] is True
    assert "native_particle_count_matches_contract" not in geometry
    assert geometry["r001_legacy_computed_particle_count"] == 6144
    assert geometry["r001_legacy_consumer_scope_id"].endswith("R001")
    assert geometry["r001_legacy_consumer_is_r008_authority"] is False
    assert geometry["z_count_interpretation"] == "intervals_plausible_but_not_explicitly_frozen"
    gap = next(item for item in value["blocking_gaps"] if item["code"].startswith("production_z_plane"))
    assert "not an R008 authority" in gap["detail"]
    assert value["status"] == "blocked_preexecution_semantics_closure"
    assert value["readiness_pass"] is False
    assert value["qualification_credit"] == 0
    assert value["execution_authority"]["solver"] is False


def test_r008_v3_binds_the_actual_scope_and_count_consumers() -> None:
    value = audit.build_audit()
    evidence = {item["path"]: item for item in value["evidence"]}

    assert audit.R008_AUTHORIZATION_BUILDER.as_posix() in evidence
    assert audit.R008_SCOPE_BUILDER.as_posix() in evidence
    assert evidence[audit.R001_CONSUMER_BUILDER.as_posix()]["role"].startswith("legacy R001-only")
    assert audit.R001_CONSUMER_OWNER.as_posix() in evidence
    assert audit.V2_RECEIPT.as_posix() in evidence
    assert all(len(item["sha256"]) == 64 for item in evidence.values())
    assert "incorrectly attributed an R001-only" in value["supersedes"]["reason"]


def test_r008_v3_preserves_metric_definition_gaps_and_zero_authority() -> None:
    value = audit.build_audit()
    assert value["missing_metric_definitions"] == [
        "profile_sampling",
        "reference_velocity",
        "transverse_rms",
        "flux_normalization",
        "cross_resolution_alignment",
    ]
    assert len(value["blocking_gaps"]) == 6
    assert value["execution_authority"] == {
        "solver": False,
        "gpu": False,
        "worker": False,
        "queue": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
    }


def test_r008_v3_writer_is_immutable_and_verifier_recomputes(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    assert audit.write_audit(target) == target
    assert json.loads(target.read_text(encoding="utf-8")) == audit.verify_audit(target)
    with pytest.raises(FileExistsError, match="immutable R008 execution-readiness audit v3"):
        audit.write_audit(target)

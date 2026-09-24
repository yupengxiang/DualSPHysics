from __future__ import annotations

import json

import numpy as np
import pytest

from scripts import f8_r008_execution_readiness_audit_v4 as audit
from scripts.f8_womersley_oracle import ChannelParameters, steady_velocity


def test_v4_closes_the_six_v3_metric_semantics_gaps() -> None:
    value = audit.build_audit()
    assert value["metric_semantics"]["reviewed"] is True
    assert value["metric_semantics"]["missing_definitions"] == []
    assert "including both endpoints" in value["metric_semantics"]["profile_plane_rule"]
    assert "Uref*(2H)" in value["metric_semantics"]["cycle_flux"]
    assert "no extrapolation" in value["metric_semantics"]["cross_resolution"]
    assert "divided by case-specific Uref" in value["metric_semantics"]["transverse_rms"]
    assert "ratio <= 0.05" in value["metric_semantics"]["transverse_rms"]
    resolutions = value["metric_semantics"]["v3_gap_resolutions"]
    assert len(resolutions) == 6
    assert {item["v3_gap_code"] for item in resolutions} == set(audit.GAP_RESOLUTION_MAP)
    assert all(item["resolved"] and item["proposal_fields"]
               and item["adapter_symbols"] and item["test_symbols"] for item in resolutions)
    assert value["adapter_static_state"]["anchor_fluid_particles"] == 6656
    assert value["adapter_static_state"]["anchor_registered_nonfluid_particles"] == 4096


def test_v4_keeps_execution_and_qualification_blocked() -> None:
    value = audit.build_audit()
    assert value["status"] == "metric_semantics_closed_execution_integration_pending"
    assert value["readiness_pass"] is False
    assert value["full_t1_decision"] is False
    assert value["qualification_credit"] == 0
    assert {gap["code"] for gap in value["blocking_gaps"]} == {
        "reviewed_per_case_materialization_verifier_missing",
        "formal_15_case_t1_results_not_materialized",
    }
    assert all(item is False or item == 0 for item in value["execution_authority"].values())
    assert value["adapter_static_state"]["self_asserted_per_case_receipt_probe_rejected"] is True
    assert value["adapter_static_state"]["independent_adapter_review_pass"] is True


def test_v4_binds_the_immutable_v3_audit_and_current_adapter() -> None:
    value = audit.build_audit()
    evidence = {item["role"]: item for item in value["evidence"]}
    assert audit.V3_RECEIPT_SHA256 == evidence["immutable corrected R008 readiness audit v3"]["sha256"]
    adapter_binding = evidence["static metric adapter with fixed trust anchors"]
    assert adapter_binding["path"] == "scripts/f8_r008_t1_metric_adapter_v1.py"
    assert len(adapter_binding["sha256"]) == 64
    assert "independent Terra High PASS review archive for the static adapter" in evidence
    assert "pinned native observation-window parser dependency" in evidence
    assert "pinned Womersley reference-oracle dependency" in evidence
    assert all(len(item["sha256"]) == 64 for item in evidence.values())


def test_gap_resolution_map_requires_all_six_v3_codes_and_real_sources() -> None:
    v3 = audit._load(audit.V3_RECEIPT)
    proposal = audit._load(audit.adapter.FROZEN_METRIC_PROPOSAL.relative_to(audit.LAB))
    mapped = audit._verify_gap_resolution_map(v3, proposal)
    assert {item["v3_gap_code"] for item in mapped} == set(audit.GAP_RESOLUTION_MAP)
    for item in mapped:
        assert all(audit._lookup(proposal, field) for field in item["proposal_fields"])
        assert item["resolved"] is True
    v3["blocking_gaps"] = v3["blocking_gaps"][:-1]
    with pytest.raises(ValueError, match="exact six audited semantics blockers"):
        audit._verify_gap_resolution_map(v3, proposal)


def test_audit_executes_fail_closed_probe_for_self_asserted_receipt() -> None:
    audit._verify_generic_receipt_fails_closed()


def test_v4_transverse_rms_normalization_and_gate_are_exercised_with_nonzero_signal(tmp_path) -> None:
    scope = audit._load(audit.adapter.FROZEN_SCOPE_RECEIPT.relative_to(audit.LAB))
    row = next(item for item in scope["matrix"]["rows"] if item["case_id"] == audit.adapter.ANCHOR_CASE_ID)
    parameters = audit._load(audit.adapter.FROZEN_PARAMETER_CONTRACT.relative_to(audit.LAB))
    geometry = parameters["geometry_and_fluid"]
    forcing = parameters["parameterization"]
    half_height = float(geometry["half_height_m"])
    omega = float(row["omega_rad_s"])
    u_ref = float(forcing["acceleration_amplitude_m_s2"]) / omega
    z = np.linspace(-half_height, half_height, 13)
    fluid_ids = np.arange(1, 14, dtype=np.uint32)
    raw_ids = np.r_[np.array([99], dtype=np.uint32), fluid_ids]
    times = np.arange(row["observation_end_output_index"] + 1, dtype=np.float64) * row["native_output_dt_s"]
    channel = ChannelParameters(
        half_height, float(geometry["kinematic_viscosity_m2_s"]), omega,
        float(forcing["acceleration_amplitude_m_s2"]),
    )
    frames = []
    for time in times:
        position = np.full((len(raw_ids), 3), np.nan, dtype=np.float64)
        velocity = np.full((len(raw_ids), 3), np.nan, dtype=np.float64)
        mass = np.full(len(raw_ids), np.nan, dtype=np.float64)
        position[1:] = np.column_stack((np.full(len(z), 0.01), np.full(len(z), 0.02), z))
        velocity[1:, 0] = steady_velocity(float(time), z, channel)
        velocity[1:, 1] = 0.1 * u_ref
        velocity[1:, 2] = 0.0
        mass[1:] = 1.0
        frames.append({
            "time_s": float(time), "particle_id": raw_ids.copy(),
            "position_m": position, "velocity_m_s": velocity, "mass_kg": mass,
        })
    xml = tmp_path / "synthetic-generated.xml"
    xml.write_text(
        "<case><particles><fixed begin='99' count='1'/><fluid begin='1' count='13'/></particles></case>",
        encoding="utf-8",
    )
    table = audit.adapter.build_native_fluid_table(
        frames, generated_xml_path=xml, dp_m=float(row["dp_m"]),
        half_height_m=half_height, case_id=row["case_id"],
    )
    result = audit.adapter.evaluate_case_metrics(table, row, parameters)
    assert result["metrics"]["transverse_velocity_rms_m_s"] == pytest.approx(0.1 * u_ref, rel=1e-6)
    assert result["metrics"]["transverse_velocity_rms_ratio"] == pytest.approx(0.1, rel=1e-6)
    assert result["metric_gates"]["transverse_velocity_rms"] is False


def test_v4_writer_is_immutable_and_verifier_detects_tampering(tmp_path) -> None:
    target = tmp_path / "receipt.json"
    assert audit.write_audit(target) == target
    assert json.loads(target.read_text(encoding="utf-8")) == audit.verify_audit(target)
    with pytest.raises(FileExistsError, match="immutable R008 execution-readiness audit v4"):
        audit.write_audit(target)
    value = json.loads(target.read_text(encoding="utf-8"))
    value["readiness_pass"] = True
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="no longer matches its pinned evidence"):
        audit.verify_audit(target)


def test_v4_build_failure_leaves_no_final_receipt(tmp_path, monkeypatch) -> None:
    target = tmp_path / "receipt.json"

    def fail_build():
        raise ValueError("synthetic evidence drift")

    monkeypatch.setattr(audit, "build_audit", fail_build)
    with pytest.raises(ValueError, match="synthetic evidence drift"):
        audit.write_audit(target)
    assert not target.exists()


def test_v4_write_failure_cleans_its_partial_target(tmp_path, monkeypatch) -> None:
    target = tmp_path / "receipt.json"

    class FailingStream:
        def __init__(self, descriptor):
            self.descriptor = descriptor

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            import os
            os.close(self.descriptor)

        def write(self, _payload):
            raise OSError("synthetic disk write failure")

    monkeypatch.setattr(audit.os, "fdopen", lambda descriptor, *_args, **_kwargs: FailingStream(descriptor))
    with pytest.raises(OSError, match="synthetic disk write failure"):
        audit.write_audit(target)
    assert not target.exists()

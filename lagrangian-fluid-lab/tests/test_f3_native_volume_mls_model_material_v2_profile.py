"""Small synthetic checks for the v2 material performance profiler."""
from __future__ import annotations

import json
import sys

import pytest

from scripts import f3_native_volume_mls_model_material_v2_profile as profile_v2


def test_load_gate_refuses_oversubscribed_host():
    profile_v2.check_load_gate(8.0, 8)
    with pytest.raises(RuntimeError, match="exceeds process-visible CPU capacity"):
        profile_v2.check_load_gate(8.01, 8)
    with pytest.raises(ValueError, match="finite and nonnegative"):
        profile_v2.check_load_gate(float("nan"), 8)


def test_cli_reports_deferred_before_creating_profile_artifacts(monkeypatch, capsys):
    monkeypatch.setattr(profile_v2.os, "getloadavg", lambda: (10.0, 9.0, 8.0))
    monkeypatch.setattr(profile_v2, "_cpu_capacity", lambda: 8)
    monkeypatch.setattr(sys, "argv", ["f3-native-volume-v2-profile"])

    assert profile_v2._cli() == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "deferred_resource_gate"
    assert output["profile_started"] is False


def test_small_synthetic_profile_reports_consistent_phase_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_v2.os, "getloadavg", lambda: (0.0, 0.0, 0.0))

    result = profile_v2.run_synthetic_profile(
        seed_count=4, particle_count=64, intervals=1, substeps=1,
    )

    assert result["schema"] == profile_v2.SCHEMA
    assert result["profile_kind"] == "synthetic_only_no_qualification_credit"
    assert result["qualification_claim"] == "none"
    assert result["configuration"]["seed_count"] == 4
    assert result["configuration"]["particle_count"] == 64
    assert result["synthetic_artifacts"]["temporary_files_removed"] is True
    totals = result["timing"]["phase_totals"]
    assert totals["advance_calls"] == 1
    assert totals["reconstruct_calls"] == 5
    assert totals["field_calls"] == 5
    assert totals["append_calls"] == 2
    assert totals["provider_init_seconds"] > 0.0
    assert len(result["timing"]["intervals"]) == 1
    assert result["timing"]["intervals"][0]["field_calls"] == 4
    assert result["timing"]["intervals"][0]["reconstruct_calls"] == 4


def test_small_synthetic_profile_supports_reference_provider(monkeypatch):
    monkeypatch.setattr(profile_v2.os, "getloadavg", lambda: (0.0, 0.0, 0.0))

    result = profile_v2.run_synthetic_profile(
        seed_count=2, particle_count=32, intervals=1, substeps=1,
        role=profile_v2.material.REFERENCE_ROLE,
    )

    assert result["configuration"]["role"] == profile_v2.material.REFERENCE_ROLE
    assert result["timing"]["phase_totals"]["field_calls"] == 5
    assert result["implementation"]["profile_wrapper_sha256"]
    assert result["qualification_claim"] == "none"

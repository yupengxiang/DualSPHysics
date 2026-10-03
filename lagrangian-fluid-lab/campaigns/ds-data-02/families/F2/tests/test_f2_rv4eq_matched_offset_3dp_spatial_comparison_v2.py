"""Unit tests for F2 3DP matched offset spatial comparison v2.

Verifies:
1. Config v2 schema, parameters, and input file bindings.
2. Sidecar v2 schema, physical invariance, mass separation, and unknown loss values.
3. Runner request v2 schema, kind='cpu', cpu_task_kind='audit', and validate_request.
4. Observation parser and comparison pipeline logic using synthetic fixtures with 100% write isolation.
5. Rejection of missing/None destination masses; prevention of false pass.
6. Honest negative evidence reporting (save bracket failure).
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

FAMILIES_ROOT = Path(__file__).resolve().parents[1]
HANDOFF_V2 = FAMILIES_ROOT / "handoff_20261003/spatial_reference_3dp_audit_v2"
INTEGRATION_SCRIPTS = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts")
if str(INTEGRATION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_SCRIPTS))
if str(FAMILIES_ROOT) not in sys.path:
    sys.path.insert(0, str(FAMILIES_ROOT))

import f2_rv4eq_matched_offset_3dp_spatial_comparison_v2 as comp_v2


def test_config_v2_structure():
    cfg_path = HANDOFF_V2 / "configs/offset_3dp_spatial_comparison_config_v2.json"
    assert cfg_path.is_file(), f"Missing config v2: {cfg_path}"

    cfg = json.loads(cfg_path.read_text())
    assert cfg["schema"] == "ds02.f2.matched-offset-3dp-spatial-comparison-config.v2"
    assert cfg["family_id"] == "F2"
    assert cfg["scope"] == "F2_RV4EQ_MATCHED_OFFSET_3DP_SPATIAL_REFERENCE_STUDY"
    assert cfg["physical_condition_hash"] == "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"

    sources = cfg["sources"]
    assert set(sources.keys()) == {"coarse", "medium", "fine"}
    for res, data in sources.items():
        assert Path(data["observation_report"]).is_file()
        assert Path(data["execution_receipt"]).is_file()
        assert Path(data["labels_h5"]).is_file()


def test_sidecar_v2_provenance_and_mass():
    sidecar_path = HANDOFF_V2 / "f2_rv4eq_matched_offset_3dp_source_provenance_and_mass_sidecar_v2.json"
    assert sidecar_path.is_file(), f"Missing sidecar v2: {sidecar_path}"

    sidecar = json.loads(sidecar_path.read_text())
    assert sidecar["schema"] == "ds-data-02.f2.matched-offset-3dp-provenance-and-mass.v2"
    assert sidecar["family_id"] == "F2"

    phys = sidecar["physical_condition_invariance"]
    assert phys["physical_condition_hash"] == "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
    assert phys["motion_control_sha256"] == "ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70"
    assert phys["continuous_reference_mass_kg"] == 24.576

    # Unknown loss mass preservation
    ledger = sidecar["frozen_v6_xml_decimal_counts_ledger"]
    assert ledger["coarse"]["unknown_loss_mass_kg"] == pytest.approx(0.118, abs=1e-5)
    assert ledger["medium"]["unknown_loss_mass_kg"] == pytest.approx(0.10752, abs=1e-5)
    assert ledger["fine"]["unknown_loss_mass_kg"] == pytest.approx(0.268875, abs=1e-5)

    # Save allocation failure
    temp = sidecar["temporal_window_and_allocation"]
    assert temp["allocation_status"] == "fail_budget_exceeded"
    assert temp["effective_half_savewidth_s"] > temp["save_half_width_budget_s"]


def test_runner_request_v2_validation():
    import ds_data02_runtime_v2 as rt

    req_path = HANDOFF_V2 / "requests/offset_3dp_spatial_comparison_request_v2.json"
    assert req_path.is_file(), f"Missing request v2: {req_path}"

    req = json.loads(req_path.read_text())
    assert req["schema"] == "ds02.runner-request.v2"
    assert req["family_id"] == "F2"
    assert req["case_id"] == "F2_RV4EQ_MATCHED_OFFSET_3DP_SPATIAL_COMPARISON_V2"
    assert req["attempt_id"] == "root-offset-3dp-spatial-comparison-v2-001"
    assert req["kind"] == "cpu"
    assert req["cpu_task_kind"] == "audit"

    # Validate against frozen shared runner
    rt.validate_request(req)


def test_pipeline_with_mock_fixtures(tmp_path):
    """Synthetic test ensuring complete campaign write isolation (tmp_path only)."""
    mock_dir = tmp_path / "mock_sources"
    mock_dir.mkdir()

    resolutions = {
        "coarse": {"dp": 0.010, "fluid": 24576, "total": 421566, "unknown_mass": 0.118, "receiver_mass": 3.787, "tray_mass": 20.436, "inflight_mass": 0.235},
        "medium": {"dp": 0.008, "fluid": 48000, "total": 668673, "unknown_mass": 0.10752, "receiver_mass": 3.48416, "tray_mass": 20.712448, "inflight_mass": 0.271872},
        "fine":   {"dp": 0.005, "fluid": 196608, "total": 1667249, "unknown_mass": 0.268875, "receiver_mass": 3.051375, "tray_mass": 20.1975, "inflight_mass": 1.05825},
    }

    mock_sources = {}
    for r, p in resolutions.items():
        r_dir = mock_dir / r
        r_dir.mkdir()

        obs_file = r_dir / "f2-v6-observations.json"
        rcpt_file = r_dir / "execution-receipt.json"
        h5_file = r_dir / "f2-v6-labels.h5"

        h5_file.write_bytes(b"MOCK_H5_BYTES")
        rcpt_file.write_text(json.dumps({"status": "completed", "returncode": 0}))

        obs_content = {
            "source_population": {
                "continuous_mass_kg": 24.576,
                "h5_float32_adapter_mass_kg": 24.576001167,
                "source_mass_kg_by_layer": {"0": 8.192, "1": 8.192, "2": 8.192},
            },
            "final_mass_kg_by_destination": {
                "cup": 0.0,
                "receiver": p["receiver_mass"],
                "tray": p["tray_mass"],
                "inflight": p["inflight_mass"],
                "unknown": p["unknown_mass"],
            },
            "native_exclusion_and_boundary": {
                "native_invalid_rows": 100,
                "physical_spill_inferred_from_invalid": False,
            },
            "event_ledger": {
                "first_event_time_s_by_code": {"receiver_entry": 0.86, "cup_top_departure": 0.88, "tray_entry": 1.12},
                "first_event_bracket_half_width_s_by_code": {"receiver_entry": 0.005},
                "counts_by_code": {"receiver_entry": 1000},
                "mass_kg_by_code": {"receiver_entry": 1.0},
                "save_bracket_status_by_code": {"receiver_entry": "fail"},
                "save_half_width_budget_s": 0.0007336390799938275,
                "all_observed_save_brackets_within_budget": False,
            },
            "residence": {
                "fractional_cohort_time_by_destination": {"cup": 1.1, "receiver": 0.4, "tray": 2.0, "inflight": 0.4, "unknown": 0.02},
                "mass_time_kg_s_by_destination": {"cup": 27.0, "receiver": 10.0, "tray": 50.0, "inflight": 10.0, "unknown": 0.5},
                "time_window_s": 4.0,
            },
            "qi_evidence": {"actual_3d_coordinate_state": True},
            "q_n": {"status": "not_assessed"},
        }
        obs_file.write_text(json.dumps(obs_content))

        mock_sources[r] = {
            "case_id": f"CASE_{r.upper()}",
            "resolution": r.upper(),
            "dp_m": p["dp"],
            "fluid_particles": p["fluid"],
            "total_particles": p["total"],
            "observation_report": str(obs_file),
            "observation_sha256": comp_v2.sha256_file(obs_file),
            "execution_receipt": str(rcpt_file),
            "execution_receipt_sha256": comp_v2.sha256_file(rcpt_file),
            "labels_h5": str(h5_file),
            "labels_h5_sha256": comp_v2.sha256_file(h5_file),
        }

    mock_config = {
        "schema": "ds02.f2.matched-offset-3dp-spatial-comparison-config.v2",
        "family_id": "F2",
        "scope": "TEST_MOCK_SCOPE",
        "sources": mock_sources,
    }

    summary = comp_v2.compare_3dp_spatial_series(mock_config)
    assert summary["schema"] == "ds02.f2.matched-offset-3dp-spatial-comparison-summary.v2"
    assert summary["unknown_loss_comparison"]["all_match_expected"] is True
    assert summary["temporal_compliance"]["overall_status"] == "fail_save_bracket_budget_exceeded"

    md_report = comp_v2.generate_markdown_report(summary)
    assert "0.268875 kg" in md_report
    assert "0.118000 kg" in md_report
    assert "0.107520 kg" in md_report
    assert "FAIL" in md_report

    out_dir = tmp_path / "out"
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(mock_config))
    result = comp_v2.run_pipeline(config_file, out_dir)
    assert (out_dir / "spatial_comparison_summary.json").is_file()
    assert (out_dir / "spatial_comparison_summary.md").is_file()


def test_missing_destination_mass_rejected(tmp_path):
    mock_sources = {
        "coarse": {
            "case_id": "C", "resolution": "COARSE", "dp_m": 0.01, "fluid_particles": 24576,
            "observation_report": str(tmp_path / "obs.json"),
            "execution_receipt": str(tmp_path / "rcpt.json"),
            "labels_h5": str(tmp_path / "h5.bin"),
        },
        "medium": {},
        "fine": {},
    }
    (tmp_path / "h5.bin").write_bytes(b"123")
    (tmp_path / "rcpt.json").write_text("{}")
    # Missing unknown destination mass
    (tmp_path / "obs.json").write_text(json.dumps({
        "source_population": {"continuous_mass_kg": 24.576, "h5_float32_adapter_mass_kg": 24.576},
        "final_mass_kg_by_destination": {"cup": 0.0, "receiver": 3.787, "tray": 20.436, "inflight": 0.235}, # missing unknown
        "native_exclusion_and_boundary": {"native_invalid_rows": 0, "physical_spill_inferred_from_invalid": False},
        "event_ledger": {}, "residence": {}, "qi_evidence": {}, "q_n": {},
    }))

    mock_config = {"sources": mock_sources}
    with pytest.raises(comp_v2.ComparisonError, match="Missing or None destination mass"):
        comp_v2.compare_3dp_spatial_series(mock_config)

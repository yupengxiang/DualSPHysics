import hashlib
import json
from pathlib import Path

import pytest


LAB = Path(__file__).resolve().parents[1]
EVIDENCE = LAB / "campaigns/core-v1/evidence/f2-resting-fill-static-hold-v2-h200"
REAUDIT = EVIDENCE / "observer-reaudit-v3"


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def test_versioned_reaudit_preserves_original_evidence_and_binds_code_snapshot():
    report = json.loads((REAUDIT / "forensics.json").read_text())
    manifest = json.loads((REAUDIT / "manifest.json").read_text())
    assert report["solver_rerun"] is False
    assert report["gpu_launched"] is False
    assert report["original_evidence_preserved"] is True
    assert report["qualification_claim"].startswith("none;")
    assert report["inputs"]["prepared_sha256"] == _digest(EVIDENCE.parent.parent / "cfd/prepared/F2_resting_fill_static_hold_canary_v2/prepared.json")
    assert report["inputs"]["trajectory_sha256"] == _digest(EVIDENCE / "trajectory.h5")
    assert report["inputs"]["original_observations_sha256"] == _digest(EVIDENCE / "observations.json")
    assert report["inputs"]["original_audit_sha256"] == _digest(EVIDENCE / "audit.json")
    for key in ("observer_code_snapshot", "reaudit_code_snapshot"):
        path = Path(report["inputs"][key])
        assert path.is_file()
        assert _digest(path) == report["inputs"][key + "_sha256"]
    assert manifest["forensics_sha256"] == _digest(REAUDIT / "forensics.json")
    assert manifest["observations_sha256"] == _digest(REAUDIT / "observations.json")


def test_reaudit_locates_domain_loss_and_separates_open_spill_from_walls():
    report = json.loads((REAUDIT / "forensics.json").read_text())
    observations = report["observations"]
    missing = report["first_missing_diagnostic"]
    geometry = report["initial_geometry_and_pressure_diagnostic"]
    assert missing["first_missing_frame_index"] == 24
    assert missing["first_missing_count"] == 6
    assert missing["first_loss_is_domain_ceiling_consistent"] is True
    assert {record["source_label_initial_mk"] for record in missing["records"]} == {1, 2}
    assert observations["native_axis_exact"] is True
    assert observations["native_missing_count_max"] == 144
    assert observations["maximum_outside_cup_mass_fraction"] == pytest.approx(0.024396328967299295)
    assert observations["pre_motion_maximum_outside_cup_mass_fraction"] == pytest.approx(0.024396328967299295)
    assert observations["cup_closed_wall_endpoint_particle_frames"] == 0
    assert observations["cup_saved_chord_crossings"] == 0
    assert observations["static_settled"] is False
    assert geometry["physical_face_clearance_m"]["bottom"] == pytest.approx(0.01)
    assert geometry["physical_face_clearance_m"]["left"] == pytest.approx(0.055)
    assert geometry["physical_face_clearance_m"]["front"] == pytest.approx(0.0425)
    assert geometry["native_center_clearance_m"]["minimum_any_cup_boundary"] == pytest.approx(0.0075)
    assert geometry["initial_hydrostatic_diagnostic"]["pressure_fit_slope_pa_m"] == pytest.approx(-9810.0, abs=0.1)
    assert geometry["initial_hydrostatic_diagnostic"]["expected_pressure_residual_max_pa"] < 0.1
    assert len(report["repair_hypotheses_max_two"]) == 2

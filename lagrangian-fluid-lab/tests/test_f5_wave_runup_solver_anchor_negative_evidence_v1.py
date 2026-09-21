import json
from pathlib import Path

from scripts.f5_wave_runup_solver_anchor_negative_evidence_v1 import SCHEMA


def test_f5_anchor_sampled_geometry_failure_is_zero_credit():
    path = (Path(__file__).resolve().parents[1]
            / "campaigns/core-v1/evidence/f5-wave-runup-third-t1-anchor-negative-evidence-v1.json")
    evidence = json.loads(path.read_text())
    assert evidence["schema"] == SCHEMA
    assert evidence["status"] == "completed_scientific_negative_anchor_sampled_geometry"
    assert evidence["qualification_claim"] == "none"
    assert evidence["matrix_credit"] == 0
    assert evidence["execution"]["raw_solver_product_complete"] is True
    assert evidence["execution"]["same_input_retry"] is False
    assert evidence["hard_integrity"]["pass"] is False
    observed = evidence["hard_integrity"]["observed_sampled"]
    assert observed["entity_penetration_particle_frames"] > 0
    assert observed["saved_chord_crossing_count"] > 0
    assert observed["full_frame_coverage"] is False

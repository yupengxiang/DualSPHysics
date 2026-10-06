#!/usr/bin/env python3
"""Metadata-only validation for the fresh130 physical-visual sidecar."""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SIDECAR = HERE / "metadata" / "fresh130-physical-visual-sidecar.json"


def main() -> int:
    data = json.loads(SIDECAR.read_text())
    assert data["schema"] == "ds02.f6.fresh130.physical-visual-sidecar.v1"
    assert data["case_id"] == "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0625_YAWM06_DP025"
    evidence = data["visual_evidence"]
    assert evidence["renderer_receipt_status"] == "completed/0"
    assert evidence["source_frames"] == evidence["rendered_frames"] == 241
    assert evidence["contact_sheets_viewed"] == 11
    assert evidence["keyframes_viewed"] == 9
    assert evidence["all_requested_images_viewed"] is True
    assert evidence["report_nonfinite_active_states"] == 0
    assert evidence["report_missing_event_sum"] == 933
    assert evidence["report_maximum_missing_particles_single_frame"] == 4
    physical = data["physical_visual_observation"]
    assert physical["mechanism_discerning"] is True
    assert physical["gross_visual_screen"]["obvious_wall_or_tank_escape"] is False
    assert physical["gross_visual_screen"]["obvious_explosive_particle_cloud"] is False
    assert physical["gross_visual_screen"]["obvious_premature_termination"] is False
    policy = data["scope_policy"]
    assert policy["source_canonical_scope_separate"] is True
    assert policy["classified_actual_converter_scope_separate"] is True
    assert policy["source_plan_scope_separate"] is True
    assert policy["scientific_payload_read_or_hashed_by_agent"] is False
    assert policy["case_credit_granted_by_agent"] is False
    assert policy["global_credit_updated_by_agent"] is False
    assert policy["precision_status"] == "not accepted"
    print("fresh131 sidecar validation PASS: fresh130 physical visual sequence recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

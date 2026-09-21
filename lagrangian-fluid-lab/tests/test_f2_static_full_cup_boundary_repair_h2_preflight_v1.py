from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_static_full_cup_boundary_repair_h2_preflight_v1 import (
    CLEARANCE,
    DP,
    HDP,
    PROPOSAL_RELATIVE,
    REVIEW_RELATIVE,
    VOLUME_M3,
    _assert_review,
    _continuous_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def _receipt() -> dict:
    area = (0.425 - 2 * CLEARANCE) * (0.30 - 2 * CLEARANCE)
    height = VOLUME_M3 / area
    return {
        "continuous_fluid": {
            "low_m": [CLEARANCE, -0.15 + CLEARANCE, 0.65 + CLEARANCE],
            "size_m": [0.425 - 2 * CLEARANCE, 0.30 - 2 * CLEARANCE, height],
            "volume_m3": VOLUME_M3,
            "clearance_m": CLEARANCE,
            "hdp": HDP,
            "dp_m": DP,
            "q": 0.0,
        }
    }


def test_root_review_binds_current_proposal_and_forbids_runtime() -> None:
    review = _assert_review(ROOT)
    assert review["payload"]["status"] == "approved_for_one_fresh_cpu_native_preflight"
    assert review["payload"]["decision"]["solver_allowed"] is False
    assert review["payload"]["decision"]["gpu_allowed"] is False
    assert review["payload"]["proposal"]["path"] == PROPOSAL_RELATIVE.as_posix()
    assert (ROOT / REVIEW_RELATIVE).is_file()


def test_support_clearance_contract_requires_bottom_and_side_clearance() -> None:
    value = _continuous_contract(_receipt())
    assert value["checks"]["side_clearance_geometry"] is True
    assert value["checks"]["bottom_clearance_geometry"] is True
    assert value["checks"]["volume_matches"] is True

    bad = _receipt()
    bad["continuous_fluid"]["low_m"][2] = 0.65
    with pytest.raises(ValueError, match="support-clearance"):
        _continuous_contract(bad)


def test_proposal_keeps_zero_credit_and_fixed_denominator() -> None:
    proposal = json.loads((ROOT / PROPOSAL_RELATIVE).read_text())
    assert proposal["matrix_credit"] == 0
    assert proposal["fixed_failure_denominator"]["planned"] == 15
    assert proposal["hypothesis"]["source_box_rule"]["fluid_bottom_rule"].startswith("0.65+c")


def test_authorized_h2_cpu_native_preflight_passes_without_scientific_credit() -> None:
    artifact = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-cell0-v1/preflight.json"
    value = json.loads(artifact.read_text())
    assert value["status"] == "cpu_native_preflight_pass"
    assert value["qualification_claim"].startswith("none;")
    assert value["qualified"] is False
    assert value["T1_numerical"] is False
    assert value["matrix_credit"] == 0
    assert value["fixed_failure_denominator"] == {
        "planned": 15,
        "executed": 1,
        "passed": 1,
        "failed": 0,
        "unattempted": 14,
        "survivor_renormalization": False,
    }
    assert all(value["checks"].values())
    assert value["native"]["fluid_particles"] == 23100
    assert value["native"]["zero_boundnor_count"] == 0
    assert value["native"]["mass_error_relative"] == pytest.approx(0.006535947712418277)
    assert value["native_decode_recovery"]["decoder_invocation_count"] == 2
    assert value["native_decode_recovery"]["same_input_scientific_retry"] is False
    for key in ("solver_invoked", "gpu_invoked", "queue_mutated", "ledger_mutated", "registry_mutated"):
        assert value[key] is False

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f4_macro_t2_sidecar_preflight_v1 import (
    CADENCE_SOURCE_AUDIT,
    MATRIX_REVIEW,
    NEGATIVE_EVIDENCE,
    build_preflight,
    load_json,
    matrix_summary,
    render_report,
    sidecar_summary,
    summarize_canaries,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "campaigns/core-v1/material/evidence"


@pytest.fixture(scope="module")
def preflight() -> dict:
    return build_preflight(ROOT)


def test_retained_f4_canaries_preserve_fixed_unknown_gate_failure() -> None:
    negative = load_json(EVIDENCE_ROOT / NEGATIVE_EVIDENCE.relative_to("campaigns/core-v1/material/evidence"))
    rows = summarize_canaries(negative)
    assert [row["id"] for row in rows] == [
        "f4_real_material_baseline_s2",
        "f4_native_dense_pair_s2_s4",
        "f4_repair_canaries_ess32_and_affine_bound:f4_ess32_v2",
        "f4_repair_canaries_ess32_and_affine_bound:f4_affine_bound_v2",
        "f4_tallwall120_short_canary",
    ]
    assert [row["unknown_fraction_max"] for row in rows] == [
        0.84765625,
        0.896484375,
        0.923828125,
        0.955078125,
        1.0,
    ]
    assert all(row["mass_closed"] is True for row in rows)
    assert all(row["event_window_complete"] is False for row in rows)
    assert all(row["unknown_fraction_max"] > 0.01 for row in rows)


def test_exact_stride_sidecar_is_provenance_only() -> None:
    source = load_json(EVIDENCE_ROOT / CADENCE_SOURCE_AUDIT.relative_to("campaigns/core-v1/material/evidence"))
    summary = sidecar_summary(source)
    assert summary["sidecar_provenance_pass"] is True
    assert summary["exact_stride_view"]["exact_rows_no_interpolation"] is True
    assert summary["exact_stride_view"]["same_terminal_lineage"] is True
    assert summary["source_view_is_not_independent_cfd"] is True
    assert summary["material_reliability_status"] == "uncalibrated"
    assert summary["qualification_claim"] == "none"
    assert summary["sidecar_can_qualify_t2"] is False


def test_f4_template_keeps_missing_cadence_and_pending_material_overlays() -> None:
    matrix = load_json(EVIDENCE_ROOT / MATRIX_REVIEW.relative_to("campaigns/core-v1/material/evidence"))
    summary = matrix_summary(matrix)
    assert summary["template_total_rows"] == 33
    assert summary["exact_cadence_rows_missing"] == 4
    assert summary["resolution_material_overlays_pending"] == 24
    assert summary["seed_density_material_overlays_pending"] == 5
    assert summary["material_matrix_ready"] is False


def test_preflight_fails_closed_without_mutating_qualification_state(preflight: dict) -> None:
    assert preflight["schema"] == "core.material.f4.macro_t2_sidecar_preflight.v1"
    assert preflight["status"] == "blocked_for_qualification"
    assert preflight["qualification_claim"] == "none"
    assert preflight["T2_macro"] is False
    assert preflight["T2_path"] is False
    assert preflight["gate_evaluation"]["unknown_mass_pass"] is False
    assert preflight["gate_evaluation"]["event_window_pass"] is False
    assert preflight["gate_evaluation"]["sidecar_provenance_pass"] is True
    assert preflight["gate_evaluation"]["sidecar_independent_cfd_pass"] is False
    assert preflight["static_cfd_qualification_status"]["matrix_complete"] is False
    assert preflight["execution_constraints"]["new_job_submitted"] is False
    assert preflight["execution_constraints"]["active_h5_opened"] is False
    assert preflight["execution_constraints"]["central_ledger_mutation"] == 0
    assert preflight["execution_constraints"]["thresholds_changed"] is False
    assert len(preflight["blocking_reasons"]) >= 5


def test_report_states_block_and_repair_boundary(preflight: dict, tmp_path: Path) -> None:
    evidence_path = tmp_path / "preflight.json"
    evidence_path.write_text(json.dumps(preflight, indent=2), encoding="utf-8")
    report = render_report(preflight, evidence_path)
    assert "没有可接受的、独立于 F3 新原生 cadence 的 F4 宏观 T2 闭合路径" in report
    assert "T2_macro=false" in report
    assert "exact-stride" in report
    assert "4.34 s" in report
    assert "Thresholds, source/destination mass semantics" in report

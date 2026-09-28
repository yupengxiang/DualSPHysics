"""Synthetic contract tests for the F4 material terminal evidence intake."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import f4_tallwall120_material_terminal_evidence_intake_v1 as intake


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/F4-TALLWALL120-MATERIAL-TERMINAL-EVIDENCE-INTAKE-V1-2026-09-28.json"
ZH_REPORT = ROOT / "reports/F4-TALLWALL120-MATERIAL-TERMINAL-EVIDENCE-INTAKE-V1-2026-09-28.zh-CN.md"


def _evidence() -> dict:
    namespace = intake.DEFAULT_OUTPUT_NAMESPACE
    output_identity = {
        "result_json": f"{namespace}/product/tallwall120_material.json",
        "trace_hdf5": f"{namespace}/product/tallwall120_material.h5",
        "diagnosis_json": f"{namespace}/product/tallwall120_material_diagnosis.json",
        "checkpoint_manifest": f"{namespace}/product/tallwall120_material.h5.checkpoint.json",
    }
    return {
        "schema": intake.TERMINAL_EVIDENCE_SCHEMA,
        "status": "completed",
        "source": {
            "family": "F4",
            "scope_id": intake.SCOPE_ID,
            "case_id": intake.CASE_ID,
            "source_hdf5": intake.SOURCE_HDF5,
            "source_sha256": intake.SOURCE_SHA256,
        },
        "material_config": {
            "q": intake.EXPECTED_Q,
            "dp_m": intake.EXPECTED_DP_M,
            "seeds": intake.EXPECTED_SEEDS,
            "substeps": intake.EXPECTED_SUBSTEPS,
            "neighbour_variant": intake.EXPECTED_NEIGHBOUR_VARIANT,
            "source_frames": intake.SOURCE_FRAMES,
            "source_transitions": intake.SOURCE_TRANSITIONS,
            "required_event_window_s": intake.REQUIRED_EVENT_WINDOW_S,
        },
        "attempt": {
            "attempt_id": "f4-dev07-material-r001-20260928-abcdef",
            "fresh_attempt": True,
            "output_namespace": namespace,
            "namespace_preexisting_at_start": False,
            "historical_trace_reuse": False,
            "overwrite_allowed": False,
            "resume_from_attempt_id": None,
            "output_identity": output_identity,
            "output_identity_sha256": intake._output_identity_digest(output_identity),
        },
        "terminal": {
            "status": "completed",
            "frame_count": 435,
            "transition_count": 434,
            "committed_frame": 434,
            "committed_transition": 433,
            "committed_time_s": intake.REQUIRED_EVENT_WINDOW_S,
            "event_window_complete": True,
            "event_window_status": "complete",
        },
        "metrics": {
            "mass_closed": True,
            "mass_closure_error": 0.0,
            "unknown_fraction_max": 0.0,
            "unknown_gate_pass": True,
            "common_reliable_path_coverage": 1.0,
        },
    }


def _check(report: dict, name: str) -> dict:
    return next(item for item in report["checks"] if item["check"] == name)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_sha256", "f" * 64),
        ("case_id", "F4_resting_pool_laminar_tallwall120_x_v1_DEV_06"),
    ],
)
def test_wrong_source_or_case_binding_is_rejected(field: str, value: str) -> None:
    evidence = _evidence()
    evidence["source"][field] = value

    result = intake.evaluate_terminal_evidence(evidence)

    assert "terminal_source_and_case_binding" in result["failed_checks"]
    assert "terminal_source_or_case_binding_mismatch" in result["blocking_reasons"]


def test_partial_right_censored_terminal_is_rejected() -> None:
    evidence = _evidence()
    evidence["terminal"].update(
        {
            "committed_time_s": intake.SOURCE_END_S,
            "event_window_complete": False,
            "event_window_status": "right_censored_or_unresolved",
        }
    )

    result = intake.evaluate_terminal_evidence(evidence)

    assert "terminal_event_window_complete" in result["failed_checks"]
    assert "terminal_event_window_partial_or_right_censored" in result["blocking_reasons"]
    assert result["gate_projection"]["event_window_complete"] is False


def test_missing_terminal_is_fail_closed() -> None:
    result = intake.evaluate_terminal_evidence(None)

    assert result["present"] is False
    assert result["status"] == "missing"
    assert result["failed_checks"] == ["fresh_terminal_evidence_present"]
    assert result["blocking_reasons"] == ["missing_fresh_terminal_evidence"]


def test_unknown_gate_rejects_even_a_complete_terminal() -> None:
    evidence = _evidence()
    evidence["metrics"]["unknown_fraction_max"] = 1.0
    evidence["metrics"]["unknown_gate_pass"] = False

    result = intake.evaluate_terminal_evidence(evidence)

    assert "terminal_unknown_gate" in result["failed_checks"]
    assert "terminal_unknown_gate_missing_or_failed" in result["blocking_reasons"]
    assert result["gate_projection"]["event_window_complete"] is True


def test_output_identity_digest_rejects_tampering() -> None:
    evidence = _evidence()
    evidence["attempt"]["output_identity"]["result_json"] = (
        intake.DEFAULT_OUTPUT_NAMESPACE + "/product/tampered.json"
    )

    result = intake.evaluate_terminal_evidence(evidence)

    assert "fresh_attempt_output_identity" in result["failed_checks"]
    assert "fresh_attempt_or_output_identity_invalid" in result["blocking_reasons"]


def test_checked_in_report_recomputes_and_remains_zero_credit() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert intake.build_report(ROOT) == report
    assert report["status"] == "blocked_fail_closed"
    assert report["terminal_evidence_intake"]["status"] == "missing"
    assert report["qualification"]["diagnostic_only"] is True
    assert report["qualification"]["formal"] is False
    assert report["qualification"]["T1"] is False
    assert report["qualification"]["T2"] is False
    assert report["qualification"]["qualification"] is False
    assert report["qualification"]["credit"] == 0
    assert report["terminal_evidence_intake"]["failed_checks"] == [
        "fresh_terminal_evidence_present"
    ]
    assert _check(report, "diagnostic_negative_boundary_preserved")["passed"] is True
    assert _check(report, "collection_case_source_path_exact")["passed"] is False
    assert _check(report, "reader_ref_manifest_sha_current")["passed"] is False
    assert _check(report, "diagnostic_material_config_matches_proposal")["passed"] is False


def test_report_does_not_open_hdf5_content(monkeypatch: pytest.MonkeyPatch) -> None:
    original_open = Path.open

    def guarded_open(path: Path, *args, **kwargs):
        if path.suffix.lower() in {".h5", ".hdf5"}:
            raise AssertionError(f"intake attempted to open HDF5 content: {path}")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    report = intake.build_report(ROOT)

    assert report["input_boundary"]["hdf5_content_read"] is False
    assert report["input_boundary"]["hdf5_hash_recomputed"] is False
    assert report["source_ref_consistency"]["target_hdf5_metadata"]["metadata_only"] is True


def test_chinese_report_is_a_checked_in_companion() -> None:
    text = ZH_REPORT.read_text(encoding="utf-8")

    assert "F4 Tallwall120 material terminal evidence intake V1" in text
    assert "missing_fresh_terminal_evidence" in text
    assert "credit=0" in text

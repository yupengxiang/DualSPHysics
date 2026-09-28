from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import f4_tallwall120_material_case_sidecar_intake_v1 as intake


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/F4-TALLWALL120-MATERIAL-CASE-SIDECAR-INTAKE-V1-2026-09-28.json"
ZH_REPORT = ROOT / "reports/F4-TALLWALL120-MATERIAL-CASE-SIDECAR-INTAKE-V1-2026-09-28.zh-CN.md"


def _sidecar() -> dict:
    namespace = intake.DEFAULT_OUTPUT_NAMESPACE.as_posix()
    sidecar_path = intake.DEFAULT_SIDECAR.as_posix()
    return {
        "schema": intake.MATERIAL_CASE_SIDECAR_SCHEMA,
        "family": intake.FAMILY,
        "scope_id": intake.SCOPE_ID,
        "case_id": intake.CASE_ID,
        "split": intake.CASE_SPLIT,
        "source": {
            "hdf5": intake.SOURCE_HDF5,
            "sha256": intake.SOURCE_SHA256,
            "bytes": intake.SOURCE_BYTES,
            "archive_manifest_sha256": "a" * 64,
            "archive_manifest": {
                "path": intake.SOURCE_ARCHIVE.as_posix(),
                "sha256": "a" * 64,
            },
        },
        "material_config": {
            "q": intake.EXPECTED_Q,
            "dp_m": intake.EXPECTED_DP_M,
            "seeds": intake.EXPECTED_SEEDS,
            "substeps": intake.EXPECTED_SUBSTEPS,
            "neighbour_variant": intake.EXPECTED_NEIGHBOUR_VARIANT,
        },
        "output": {
            "namespace": namespace,
            "sidecar_path": sidecar_path,
            "fresh": True,
            "namespace_preexisting_at_start": False,
            "overwrite_allowed": False,
            "historical_trace_reuse": False,
        },
        "terminal": {
            "terminal_marker": intake.REQUIRED_TERMINAL_MARKER,
            "terminal_marker_present": True,
            "status": "complete",
            "execution_complete": True,
            "event_window_status": "complete",
            "event_window_complete": True,
            "event_window_end_s": intake.REQUIRED_EVENT_WINDOW_S,
            "right_censor_status": intake.REQUIRED_RIGHT_CENSOR_STATUS,
        },
        "metrics": {
            "mass_closed": True,
            "mass_closure_pass": True,
            "mass_closure_error": 0.0,
            "unknown_gate_pass": True,
            "unknown_fraction_max": 0.0,
            "reliable_coverage_pass": True,
            "reliable_coverage": 1.0,
            "right_censor_status": intake.REQUIRED_RIGHT_CENSOR_STATUS,
        },
        "claims": {
            "diagnostic_only": True,
            "proposal_only": False,
            "formal": False,
            "formal_eligible": False,
            "qualification": False,
            "T1": False,
            "T2": False,
            "credit": 0,
            "qualification_credit": 0,
        },
    }


def test_missing_sidecar_is_blocked_fail_closed() -> None:
    result = intake.evaluate_sidecar(None)

    assert result["present"] is False
    assert result["status"] == "missing"
    assert result["blocking_reasons"] == ["missing_material_case_sidecar"]
    assert result["credit"] == 0


def test_complete_sidecar_is_non_authorizing() -> None:
    result = intake.evaluate_sidecar(_sidecar())

    assert result["status"] == "complete"
    assert result["failed_checks"] == []
    assert result["gate_projection"] == {
        "event_window_complete": True,
        "mass_closure": True,
        "unknown_gate": True,
        "reliable_coverage": True,
        "right_censor_clear": True,
    }
    assert result["credit"] == 0


def test_archive_digest_can_be_bound_to_the_observed_manifest() -> None:
    result = intake.evaluate_sidecar(_sidecar(), expected_archive_sha256="b" * 64)

    assert result["status"] == "blocked"
    assert "archives_identity_mismatch" in result["blocking_reasons"]


@pytest.mark.parametrize(
    ("section", "field", "value", "reason"),
    [
        ("source", "sha256", "f" * 64, "dev07_source_binding_mismatch"),
        ("material_config", "q", 0.5, "case_q_or_material_config_mismatch"),
        ("terminal", "event_window_end_s", intake.SOURCE_END_S, "missing_or_incomplete_event_window_terminal"),
        ("metrics", "unknown_fraction_max", 0.5, "unknown_fraction_missing_or_failed"),
        ("terminal", "right_censor_status", "right_censored_or_unresolved", "right_censored_or_unresolved"),
    ],
)
def test_required_markers_fail_closed(section: str, field: str, value, reason: str) -> None:
    sidecar = _sidecar()
    sidecar[section][field] = value
    result = intake.evaluate_sidecar(sidecar)

    assert result["status"] == "blocked"
    assert reason in result["blocking_reasons"]
    assert result["credit"] == 0


def test_formal_or_credit_claims_are_rejected() -> None:
    sidecar = _sidecar()
    sidecar["claims"]["T2"] = True
    sidecar["claims"]["credit"] = 1

    result = intake.evaluate_sidecar(sidecar)

    assert "formal_or_credit_claim_present" in result["blocking_reasons"]
    assert result["credit"] == 0


def test_checked_in_report_is_exact_and_zero_authority() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert intake.build_report(ROOT) == report
    assert intake.validate_report(report) == []
    assert intake.verify_report(REPORT, ROOT) == report
    assert report["status"] == "blocked_fail_closed"
    assert report["case_sidecar_intake"]["present"] is False
    assert report["case_sidecar_intake"]["status"] == "missing"
    assert "missing_material_case_sidecar" in report["blocking_reasons"]
    assert report["qualification"]["diagnostic_only"] is True
    assert report["qualification"]["formal"] is False
    assert report["qualification"]["T1"] is False
    assert report["qualification"]["T2"] is False
    assert report["qualification"]["credit"] == 0
    assert report["mutation"] == 0
    assert report["scientific_boundary"]["reader_smoke_is_not_t2"] is True
    assert report["scientific_boundary"]["proposal_is_not_t2"] is True


def test_report_never_opens_hdf5(monkeypatch: pytest.MonkeyPatch) -> None:
    original_open = Path.open
    original_read_bytes = Path.read_bytes

    def guarded_open(path: Path, *args, **kwargs):
        if path.suffix.lower() in intake.HDF5_SUFFIXES:
            raise AssertionError(f"opened HDF5 content: {path}")
        return original_open(path, *args, **kwargs)

    def guarded_read_bytes(path: Path, *args, **kwargs):
        if path.suffix.lower() in intake.HDF5_SUFFIXES:
            raise AssertionError(f"read HDF5 content: {path}")
        return original_read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    report = intake.build_report(ROOT)

    assert report["input_boundary"]["hdf5_content_read"] is False
    assert report["input_boundary"]["hdf5_hash_recomputed"] is False
    assert report["source_binding"]["trajectory_hdf5"]["metadata_only"] is True


def test_report_and_chinese_companion_exist() -> None:
    text = ZH_REPORT.read_text(encoding="utf-8")

    assert "F4 Tallwall120 material case sidecar intake V1" in text
    assert "missing_material_case_sidecar" in text
    assert "credit=`0`" in text

#!/usr/bin/env python3
"""Toy-only negative tests for fresh218; no campaign or scientific payload paths."""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fresh218", HERE / "build_fresh218.py")
assert spec and spec.loader
fresh218 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fresh218)


def test_lookalike_completed_status_is_not_execution_receipt() -> None:
    row = {"family_id": "F5", "case_id": "case", "physical_case_id": "physical"}
    fake = {
        "schema": "lookalike.request.v1", "status": "completed", "returncode": 0,
        "request": {"family_id": "F5", "case_id": "case", "physical_case_id": "physical", "attempt_id": "toy"},
        "request_sha256": "0" * 64, "input_hashes_at_launch": {"toy": "1" * 64},
        "input_hashes_after_run": {"toy": "1" * 64}, "runner_source": "/toy/runner.py", "runner_sha256": "2" * 64,
    }
    ok, gaps, _ = fresh218.status_gate(fake, "native_receipt", row)
    assert not ok
    assert "native_receipt_execution_receipt_schema_missing_or_wrong" in gaps


def test_missing_n3_shapes_and_nonfinite_times_are_rejected() -> None:
    decision = {"full_native_frames": 801, "particle_count": 194427}
    typed = {"schema": "ds-data-02.bi4-direct-conversion.v1", "conversion_status": "completed", "frames": 2, "particles": 3, "lifecycle": {"frame_summary": []}}
    xmf = {"frames": 2, "particles": 3, "actual_time_s": [0.0, float("nan")], "fields": {"position": {"shape": [2, 3]}, "velocity": {"shape": [2, 3]}}}
    render = {"frame_diagnostics": [{"actual_time_s": 0.0}, {"actual_time_s": float("nan")}]}
    ok, gaps, _ = fresh218.sequence_consistency(typed, xmf, render, {"time_values": [0.0, float("nan")]}, decision, {"family_id": "F5", "case_id": "case", "physical_case_id": "physical"})
    assert not ok
    assert "typed_lifecycle_frame_summary_missing_or_wrong_count" in gaps
    assert "xmf_field_position_n3_shape_mismatch" in gaps
    assert "xmf_manifest_time_sequence_missing_or_invalid" in gaps


def test_empty_bed_frames_and_time_provenance_are_rejected() -> None:
    ok, gaps, _ = fresh218.bed_fulltime_gate(
        {"schema": "ds02.f5.c082s1.full-event-bed-footprint-audit.fresh138.v1", "diagnostic_only": True, "frame_reports": [], "time_provenance": {}},
        {"full_native_frames": 801},
        {"family_id": "F5", "case_id": "case", "physical_case_id": "physical"},
    )
    assert not ok
    assert "bed_frame_report_count_not_801" in gaps
    assert "bed_time_provenance_missing_or_invalid" in gaps


def test_primary_inventory_requires_exact_34_plus_9_and_stat_only() -> None:
    ok, gaps, summary = fresh218.primary_visual_gate([], [])
    assert not ok
    assert "primary_contact_sheet_count_not_34" in gaps
    assert "primary_keyframe_count_not_9" in gaps
    assert summary["png_content_read_or_hashed"] is False


def test_output_directory_overwrite_guard() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out"
        out.mkdir()
        (out / "old.json").write_text("{}", encoding="utf-8")
        try:
            fresh218.write_outputs({"complete": False, "status": "readiness", "accepted_count": 0, "pending_count": 48}, out)
        except fresh218.BuildError as exc:
            assert "refuse overwrite" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("nonempty output directory was overwritten")


def test_missing_required_evidence_is_reported() -> None:
    out = fresh218.evidence_map({"actual_completed_metadata_evidence": {}})
    assert out["native_receipt"] is None
    assert out["render_report"] is None


if __name__ == "__main__":
    for name in sorted(k for k in globals() if k.startswith("test_")):
        globals()[name]()
    print("fresh218 toy contract tests: PASS")

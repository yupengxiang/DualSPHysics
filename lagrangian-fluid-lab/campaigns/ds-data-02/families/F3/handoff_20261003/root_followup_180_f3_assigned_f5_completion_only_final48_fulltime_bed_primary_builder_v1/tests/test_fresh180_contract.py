#!/usr/bin/env python3
"""Toy contract tests; no DS-DATA-02 paths or scientific payloads are used."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fresh180", HERE / "build_fresh180.py")
assert spec and spec.loader
fresh180 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fresh180)


def test_pseudo_request_is_not_completed_receipt() -> None:
    row = {"family_id": "F5", "case_id": "case", "physical_case_id": "physical"}
    ok, gaps, summary = fresh180.status_gate({"status": "registered"}, "render_receipt", row)
    assert not ok
    assert any("status_not_completed" in gap for gap in gaps)
    assert any("returncode_not_zero_or_missing" in gap for gap in gaps)


def test_frame_missing_and_wrong_time_metadata_are_rejected() -> None:
    decision = {"full_native_frames": 2, "particle_count": 3, "actual_type_counts": {"fluid": 2}}
    report = {
        "frames": 2,
        "source_frames": 2,
        "frame_diagnostics": [
            {"frame": 0, "missing": 0, "active": 3, "actual_time_s": 0.0, "type_counts_active": {"fluid": 2}},
            {"frame": 3, "missing": 1, "active": 2, "actual_time_s": 9.0, "type_counts_active": {"fluid": 1}},
        ],
    }
    ok, gaps, summary = fresh180.render_fulltime(report, decision, {"family_id": "F5", "case_id": "case", "physical_case_id": "physical"})
    assert not ok
    assert any("render_frame_ids_wrong" in gap for gap in gaps)
    assert any("render_frames_missing_particles" in gap for gap in gaps)
    assert any("render_frame_counts_wrong" in gap for gap in gaps)


def test_cross_role_wrong_time_is_rejected() -> None:
    decision = {"full_native_frames": 2, "particle_count": 3}
    typed = {"frames": 2, "particles": 3, "lifecycle": {"frame_summary": [
        {"frame": 0, "active_particles": 3, "missing_particles": 0, "type_counts": {}, "time": 0.0},
        {"frame": 1, "active_particles": 3, "missing_particles": 0, "type_counts": {}, "time": 1.0},
    ]}, "time_evidence": {"strictly_increasing": True}}
    xmf = {"frames": 2, "particles": 3, "actual_time_s": [0.0, 1.0], "fields": {
        "position": {"shape": [2, 3, 3]}, "velocity": {"shape": [2, 3, 3]},
    }}
    render = {"frame_diagnostics": [
        {"actual_time_s": 0.0}, {"actual_time_s": 1.1},
    ]}
    ok, gaps, summary = fresh180.sequence_consistency(typed, xmf, render, {"time_values": [0.0, 1.0]}, decision, {"family_id": "F5", "case_id": "case", "physical_case_id": "physical"})
    assert not ok
    assert any("time_delta_over_1e-6" in gap for gap in gaps)


def test_output_directory_overwrite_guard() -> None:
    # Exercise the guard without running a campaign build.
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out"
        out.mkdir()
        (out / "old.json").write_text("{}", encoding="utf-8")
        try:
            fresh180.write_outputs({"complete": False, "status": "readiness", "accepted_count": 0, "pending_count": 48}, out)
        except fresh180.BuildError as exc:
            assert "refuse overwrite" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("nonempty output directory was overwritten")


def test_missing_required_ref_is_reported() -> None:
    out = fresh180.evidence_map({"actual_completed_metadata_evidence": {}})
    assert out["native_receipt"] is None
    assert out["render_report"] is None


if __name__ == "__main__":
    for name in sorted(k for k in globals() if k.startswith("test_")):
        globals()[name]()
    print("fresh180 toy contract tests: PASS")

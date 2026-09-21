"""Tests for the independent CPU source/window audit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.f3_f4_t2_cpu_source_window_audit_v1 import (
    CDF_LIMIT,
    UNKNOWN_LIMIT,
    audit_f3_source_h5,
    audit_f3_trace_h5,
    audit_f4_trace_h5,
    build_report,
    classify_failure_reasons,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_source(path: Path, *, bad_mass: bool = False) -> None:
    frames, particles = 3, 4
    time = np.arange(frames, dtype=float) * 0.01
    position = np.zeros((frames, particles, 3), dtype=float)
    velocity = np.zeros_like(position)
    density = np.full((frames, particles), 1000.0, dtype=np.float32)
    mass = np.full((frames, particles), 0.25, dtype=np.float32)
    if bad_mass:
        mass[-1, 0] = 0.5
    with h5py.File(path, "w") as handle:
        handle.attrs["conversion_complete"] = True
        handle.create_dataset("particle_id", data=np.arange(particles, dtype=np.uint32))
        handle.create_dataset("particle_zone", data=np.zeros(particles, dtype=np.int16))
        handle.create_dataset("source_label_initial_mk", data=np.zeros(particles, dtype=np.int16))
        handle.create_dataset("time", data=time)
        handle.create_dataset("position", data=position)
        handle.create_dataset("velocity", data=velocity)
        handle.create_dataset("density", data=density)
        handle.create_dataset("mass", data=mass)
        handle.create_dataset("pressure", data=np.zeros((frames, particles), dtype=np.float32))
        handle.create_dataset("valid", data=np.ones((frames, particles), dtype=bool))
        handle.create_dataset("type", data=np.full((frames, particles), 3, dtype=np.int16))
        handle.create_dataset("mk", data=np.zeros((frames, particles), dtype=np.int16))


def _write_checkpoint(trace_path: Path, state: dict[str, np.ndarray], schema: str, committed: int) -> None:
    npz_path = trace_path.with_name(trace_path.name + ".checkpoint.npz")
    np.savez(npz_path, **state)
    manifest = {
        "schema": schema,
        "committed_frame": committed,
        "state_sha256": _sha(npz_path),
        "fields": list(state),
    }
    trace_path.with_name(trace_path.name + ".checkpoint.json").write_text(json.dumps(manifest))


def _write_f3_trace(path: Path, source: dict, *, recovered: bool = False) -> dict:
    frames, seeds = 3, 4
    labels = np.array([0, 0, 1, 1], dtype=np.int8)
    position = np.zeros((frames, seeds, 3), dtype=float)
    reliable = np.ones((frames, seeds), dtype=bool)
    reliable[2, 0] = False
    if recovered:
        reliable[1, 0] = False
        reliable[2, 0] = True
    unknown = ~reliable
    reason = np.full((frames, seeds), b"reliable", dtype="S32")
    reason[2, 0] = b"wall_occluded"
    binding = {
        "schema": "core.material.f3.native_volume_mls.trace.v2",
        "backend": "f3_native_volume_mls_current_frame_rk4_v2",
        "qualification_claim": "none",
        "future_velocity": "forbidden",
        "future_density": "forbidden",
        "interpolation": False,
        "frame_policy": "current selected native frame only",
        "frame_selection": {
            "selection_mode": "identity_all_native_frames",
            "target_nominal_interval_s": 0.01,
        },
    }
    with h5py.File(path, "w") as handle:
        handle.attrs.update(schema=binding["schema"], trace_backend=binding["backend"], committed=2,
                            qualification_claim="none", binding=json.dumps(binding))
        handle.create_dataset("time", data=source["time"])
        handle.create_dataset("position", data=position)
        handle.create_dataset("initial_position", data=np.zeros((seeds, 3)))
        handle.create_dataset("source_label", data=labels)
        handle.create_dataset("tracer_id", data=np.asarray([b"s0", b"s1", b"s2", b"s3"], dtype="S2"))
        handle.create_dataset("reliable", data=reliable)
        handle.create_dataset("permanent_unknown", data=unknown)
        handle.create_dataset("failure_reason", data=reason)
        for name, dtype in (("first_passage", float), ("return_time", float), ("residence_opposite", float)):
            handle.create_dataset(name, data=np.zeros((frames, seeds), dtype=dtype))
        handle.create_dataset("returned", data=np.zeros((frames, seeds), dtype=bool))
        handle.create_dataset("candidate_support_pass", data=np.ones((frames, seeds), dtype=bool))
        handle.create_dataset("support_count", data=np.full((frames, seeds), 24, dtype=np.int64))
        handle.create_dataset("effective_sample_size", data=np.full((frames, seeds), 8.0))
        handle.create_dataset("geometry_rank", data=np.full((frames, seeds), 3, dtype=np.int8))
        handle.create_dataset("anisotropy", data=np.full((frames, seeds), 0.1))
        handle.create_dataset("reconstruction_error_mps", data=np.zeros((frames, seeds)))
        handle.create_dataset("native_mass_kg", data=np.full(frames, 1.0))
        handle.create_dataset("seed_mass_closure_error", data=np.zeros(frames))
    state = {
        "position": position[-1], "reliable": reliable[-1], "permanent_unknown": unknown[-1],
        "first_passage": np.zeros(seeds), "return_time": np.zeros(seeds),
        "residence_opposite": np.zeros(seeds), "residence_left": np.zeros(seeds),
        "residence_right": np.zeros(seeds), "returned": np.zeros(seeds, dtype=bool),
        "failure_reason": reason[-1],
    }
    _write_checkpoint(path, state, "core.material.f3.native_volume_mls.checkpoint.v2", 2)
    return {
        "source_rows": {
            "0": {"final_unknown_count": 1, "final_unknown_fraction": 0.5},
            "1": {"final_unknown_count": 0, "final_unknown_fraction": 0.0},
        },
        "committed_frames": frames,
    }


def _write_f4_trace(path: Path, *, recovered: bool = False) -> dict:
    frames, seeds = 3, 2
    reliable = np.ones((frames, seeds), dtype=bool)
    reliable[2, 1] = False
    if recovered:
        reliable[1, 1] = False
        reliable[2, 1] = True
    binding = {
        "schema": "core.material.f4.resting_pool.v2",
        "backend": "f3_ckdtree_visible_shepard_distance_v1",
        "provider_role": "reference",
        "qualification_claim": "none",
        "f4_definition": {"source_definition": {"stage": "qualification_only"}},
    }
    with h5py.File(path, "w") as handle:
        handle.attrs.update(schema=binding["schema"], committed=2, binding=json.dumps(binding))
        handle.create_dataset("time", data=np.arange(frames) * 0.002)
        handle.create_dataset("position", data=np.zeros((frames, seeds, 3)))
        handle.create_dataset("initial_position", data=np.zeros((seeds, 3)))
        handle.create_dataset("source_label", data=np.ones(seeds, dtype=np.int8))
        handle.create_dataset("tracer_id", data=np.asarray([b"a", b"b"], dtype="S1"))
        handle.create_dataset("weight", data=np.full(seeds, 0.5))
        handle.create_dataset("reliable", data=reliable)
        for name in ("contact_time", "upward_time", "return_time"):
            handle.create_dataset(name, data=np.full((frames, seeds), np.nan))
        handle.create_dataset("residence", data=np.zeros((frames, seeds)))
        for name in ("contacted", "upward", "returned"):
            handle.create_dataset(name, data=np.zeros((frames, seeds), dtype=bool))
        handle.create_dataset("event_status", data=np.zeros((frames, seeds), dtype=np.int8))
    state = {
        "position": np.zeros((seeds, 3)), "reliable": reliable[-1],
        "contact_time": np.full(seeds, np.nan), "upward_time": np.full(seeds, np.nan),
        "return_time": np.full(seeds, np.nan), "residence": np.zeros(seeds),
        "contacted": np.zeros(seeds, dtype=bool), "upward": np.zeros(seeds, dtype=bool),
        "returned": np.zeros(seeds, dtype=bool),
    }
    _write_checkpoint(path, state, "core.material.f4.checkpoint.v1", 2)
    return {
        "event_window_complete": False,
        "event_window_status": "right_censored_or_unresolved",
        "committed_time_s": 0.004,
        "by_source": [{"source": 1, "unknown_fraction_max": 0.5}],
    }


def test_failure_classification_keeps_nonexclusive_gate_reasons() -> None:
    reasons = classify_failure_reasons(
        unknown_fraction=0.015,
        cdf_max=0.061,
        event_window_complete=False,
        cadence_pass=True,
        text="fixed reconstruction-error gate failure",
    )
    assert reasons == [
        "unknown_mass_over_1_percent",
        "cdf_sup_difference_over_0.02",
        "event_window_right_censored_or_unresolved",
        "reconstruction_error_gate",
    ]


def test_source_audit_scans_full_time_axis_and_mass_closure(tmp_path: Path) -> None:
    source = tmp_path / "source.h5"
    _write_source(source)
    audit = audit_f3_source_h5(source, expected_sha256=_sha(source), expected_frames=3, expected_particles=4)
    assert audit["integrity_pass"] is True
    assert audit["frames_scanned"] == 3
    assert audit["mass"]["bad_frame_count"] == 0
    assert audit["cadence"]["cadence_pass"] is True
    assert audit["cadence"]["interval_max_s"] == pytest.approx(0.01)


def test_source_audit_classifies_mass_failure_without_dropping_the_case(tmp_path: Path) -> None:
    source = tmp_path / "source.h5"
    _write_source(source, bad_mass=True)
    audit = audit_f3_source_h5(source, expected_sha256=_sha(source), expected_frames=3, expected_particles=4)
    assert audit["integrity_pass"] is False
    assert "source_mass_closure_or_finiteness" in audit["errors"]
    assert audit["frames_scanned"] == 3


def test_f3_trace_recomputes_source_denominators_and_first_failure_reason(tmp_path: Path) -> None:
    source = tmp_path / "source.h5"
    trace = tmp_path / "trace.h5"
    _write_source(source)
    summary = _write_f3_trace(trace, {"time": np.arange(3) * 0.01})
    source_audit = audit_f3_source_h5(source, expected_sha256=_sha(source), expected_frames=3, expected_particles=4)
    with h5py.File(source, "r") as handle:
        source_audit["_times"] = handle["time"][:].tolist()
    audited = audit_f3_trace_h5(
        trace,
        summary=summary,
        source_audit=source_audit,
        expected_sha256=_sha(trace),
        expected_source_sha256=_sha(source),
        expected_frames=3,
        expected_seed_count=4,
    )
    assert audited["integrity_pass"] is True
    assert audited["source_rows"][0]["seed_denominator"] == 2
    assert audited["source_rows"][0]["terminal_unknown_fraction"] == pytest.approx(0.5)
    assert audited["source_rows"][0]["first_failure_reason_counts"] == {"wall_occluded": 1}
    assert audited["unknown_gate"]["pass"] is False


def test_f3_trace_rejects_permanent_unknown_recovery(tmp_path: Path) -> None:
    source = tmp_path / "source.h5"
    trace = tmp_path / "trace.h5"
    _write_source(source)
    summary = _write_f3_trace(trace, {"time": np.arange(3) * 0.01}, recovered=True)
    source_audit = audit_f3_source_h5(source, expected_sha256=_sha(source), expected_frames=3, expected_particles=4)
    with h5py.File(source, "r") as handle:
        source_audit["_times"] = handle["time"][:].tolist()
    audited = audit_f3_trace_h5(trace, summary=summary, source_audit=source_audit, expected_sha256=_sha(trace), expected_frames=3, expected_seed_count=4)
    assert audited["integrity_pass"] is False
    assert "permanent_unknown_recovered" in audited["errors"]


def test_f4_trace_preserves_seed_denominator_and_right_censoring(tmp_path: Path) -> None:
    trace = tmp_path / "f4.h5"
    result = _write_f4_trace(trace)
    audited = audit_f4_trace_h5(trace, result_json=result, expected_sha256=_sha(trace), nominal_interval_s=0.002)
    assert audited["integrity_pass"] is True
    assert audited["source_rows"][0]["seed_denominator"] == 2
    assert audited["source_rows"][0]["terminal_unknown_fraction"] == pytest.approx(0.5)
    assert audited["unknown_gate"]["pass"] is False
    assert audited["event_window"]["complete"] is False
    assert audited["gate_pass"] is False


def test_f4_trace_rejects_reliability_recovery(tmp_path: Path) -> None:
    trace = tmp_path / "f4.h5"
    result = _write_f4_trace(trace, recovered=True)
    audited = audit_f4_trace_h5(trace, result_json=result, expected_sha256=_sha(trace), nominal_interval_s=0.002)
    assert audited["integrity_pass"] is False
    assert "reliability_recovered" in audited["errors"]


def test_metadata_only_report_keeps_fixed_f3_f4_denominators_and_no_t2(tmp_path: Path) -> None:
    lab_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "audit.json"
    report = build_report(lab_root, output, scan_h5=False)
    assert report["schema"] == "core.material.t2.cpu_source_window_audit.v1"
    assert report["denominators"]["f3_rows"] == 2
    assert report["denominators"]["f4_cases"] == 6
    assert report["gate_evaluation"]["qualification_claim"] == "none"
    assert report["gate_evaluation"]["T2_macro"] is False
    assert report["gate_evaluation"]["T2_path"] is False
    assert report["registered_gates"]["unknown_fraction_per_source_max"] == UNKNOWN_LIMIT
    assert report["registered_gates"]["f3_cdf_sup_abs_difference_max"] == CDF_LIMIT
    assert output.is_file()

"""Tests for terminal-gated rho0 model/reference comparison."""
from __future__ import annotations

import hashlib
import json

import h5py
import numpy as np
import pytest

from scripts.f3_model_material_compare import (
    BACKEND,
    DENSITY_STRATEGY,
    EVENT_DEFINITION,
    MODEL_ROLE,
    REFERENCE_ROLE,
    TRACE_SCHEMA,
    compare_model_material_reports,
)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding(source_sha, seed_hash="seed-axis", intervals=2, time_end=2.0):
    return {
        "schema": "core.material.f3.native_volume_mls.model_material.v1",
        "trace_schema": TRACE_SCHEMA,
        "backend": BACKEND,
        "source_sha256": source_sha,
        "seed_hash": seed_hash,
        "intervals_requested": intervals,
        "time_start_s": 0.0,
        "time_end_s": time_end,
        "dp_m": 0.0075,
        "h_m": 0.01194127788262211,
        "substeps_per_saved_interval": 1,
        "event_definition": EVENT_DEFINITION,
        "density_estimator": {
            "strategy": DENSITY_STRATEGY,
            "rho0_kgm3": 1000.0,
        },
        "native_reference_density_used": False,
    }


def _write_trace(path, source_sha, *, unknown_seed=None, intervals=2):
    times = np.arange(intervals + 1, dtype=np.float64)
    seeds = np.asarray([
        [-0.2, 0.0, 0.0], [-0.1, 0.0, 0.0],
        [0.1, 0.0, 0.0], [0.2, 0.0, 0.0],
    ])
    labels = np.asarray([0, 0, 1, 1], dtype=np.int8)
    n = len(labels)
    position = np.repeat(seeds[None, :, :], len(times), axis=0)
    position[-1, :, 0] += 0.01
    reliable = np.ones((len(times), n), dtype=bool)
    if unknown_seed is not None:
        reliable[1:, unknown_seed] = False
    unknown = ~reliable
    first = np.full((len(times), n), np.nan)
    first[-1, [0, 2]] = [1.0, 1.2]
    returned_time = np.full((len(times), n), np.nan)
    returned_time[-1, [0, 2]] = [1.5, 1.6]
    residence = np.zeros((len(times), n), dtype=np.float64)
    residence[-1, [0, 2]] = [0.5, 0.6]
    returned = np.zeros((len(times), n), dtype=bool)
    returned[-1, [0, 2]] = True
    binding = _binding(source_sha, intervals=intervals, time_end=float(times[-1]))
    with h5py.File(path, "w") as handle:
        handle.attrs.update(
            trace_schema=TRACE_SCHEMA,
            backend=BACKEND,
            material_reliability="not_established",
            binding_json=json.dumps(binding, sort_keys=True),
        )
        handle.create_dataset("time", data=times)
        handle.create_dataset("seed_position", data=seeds)
        handle.create_dataset("source_label", data=labels)
        handle.create_dataset("position", data=position)
        handle.create_dataset("reliable", data=reliable)
        handle.create_dataset("permanent_unknown", data=unknown)
        handle.create_dataset("first_passage", data=first)
        handle.create_dataset("return_time", data=returned_time)
        handle.create_dataset("residence_opposite", data=residence)
        handle.create_dataset("returned", data=returned)


def _write_report(path, trace, source_sha, role, *, status="completed", intervals=2):
    binding = _binding(source_sha, intervals=intervals, time_end=float(intervals))
    value = {
        "status": status,
        "seed_count": 4,
        "seed_hash": "seed-axis",
        "source": {"role": role, "sha256": source_sha},
        "binding": binding,
        "output_trace_h5": str(trace),
        "trace_h5_sha256": _sha256(trace) if trace.exists() else "0" * 64,
        "mass_closure": {
            "closed": True,
            "closure_error": 0.0,
            "seed_weight_definition": "uniform 1/N independent tracer weights",
            "native_support_mass_used_for_weight": True,
        },
    }
    path.write_text(json.dumps(value), encoding="utf-8")


def _provenance(model_source="model-source", reference_source="reference-source"):
    return {
        "schema": "core.material.f3.native_volume_mls.model_material_comparison_provenance.v1",
        "comparison_mode": "model_vs_reference_same_rho0",
        "allow_source_sha_mismatch": True,
        "expected_intervals": 2,
        "expected_seed_count": 4,
        "expected_time_start_s": 0.0,
        "expected_time_end_s": 2.0,
        "endpoint_time_tolerance_s": 1e-8,
        "rho0_kgm3": 1000.0,
        "expected_seed_hash": "seed-axis",
        "expected_source_sha256": {
            MODEL_ROLE: model_source,
            REFERENCE_ROLE: reference_source,
        },
    }


def test_nonterminal_report_is_rejected_before_h5_open(tmp_path):
    report = tmp_path / "running.json"
    _write_report(report, tmp_path / "does-not-exist.h5", "model-source", MODEL_ROLE,
                  status="running")
    reference_trace = tmp_path / "reference.h5"
    _write_trace(reference_trace, "reference-source")
    reference_report = tmp_path / "reference.json"
    _write_report(reference_report, reference_trace, "reference-source", REFERENCE_ROLE)
    with pytest.raises(ValueError, match="not terminal"):
        compare_model_material_reports(
            report, reference_report, _provenance(), tmp_path / "out.json"
        )


def test_model_reference_comparison_keeps_unknown_in_source_denominator(tmp_path):
    model_trace = tmp_path / "model.h5"
    reference_trace = tmp_path / "reference.h5"
    _write_trace(model_trace, "model-source", unknown_seed=1)
    _write_trace(reference_trace, "reference-source", unknown_seed=3)
    model_report = tmp_path / "model.json"
    reference_report = tmp_path / "reference.json"
    _write_report(model_report, model_trace, "model-source", MODEL_ROLE)
    _write_report(reference_report, reference_trace, "reference-source", REFERENCE_ROLE)
    output = tmp_path / "comparison.json"
    result = compare_model_material_reports(
        model_report, reference_report, _provenance(), output
    )
    assert result["status"] == "diagnostic_only"
    assert result["qualification_claim"] == "none"
    assert result["denominator_policy"]["seed_count"] == 4
    assert result["source_comparison"]["0"]["model"]["final_unknown_fraction"] == pytest.approx(.5)
    assert result["source_comparison"]["1"]["reference"]["final_unknown_fraction"] == pytest.approx(.5)
    assert result["source_comparison"]["0"]["model"]["first_passage_event_fraction_bounds"]["upper"] > \
        result["source_comparison"]["0"]["model"]["first_passage_event_fraction_bounds"]["lower"]
    assert result["model"]["mass_closure"]["status"] == "closed"
    assert result["reference"]["mass_closure"]["status"] == "closed"
    assert output.exists()


def test_model_reference_rejects_seed_axis_mismatch(tmp_path):
    model_trace = tmp_path / "model.h5"
    reference_trace = tmp_path / "reference.h5"
    _write_trace(model_trace, "model-source")
    _write_trace(reference_trace, "reference-source")
    model_report = tmp_path / "model.json"
    reference_report = tmp_path / "reference.json"
    _write_report(model_report, model_trace, "model-source", MODEL_ROLE)
    _write_report(reference_report, reference_trace, "reference-source", REFERENCE_ROLE)
    value = _provenance()
    value["expected_seed_count"] = 8
    with pytest.raises(ValueError, match="registered seed count"):
        compare_model_material_reports(model_report, reference_report, value)

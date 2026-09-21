"""Tests for read-only recovery after a reserved result.json collision."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.f3_model_material_recover_report import recover_report
from scripts.f3_native_volume_mls_model_material import BACKEND, TRACE_SCHEMA


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_case(tmp_path, *, terminal=True):
    trace = tmp_path / "trace.h5"
    source_sha = "source-hash"
    seed_hash = "seed-hash"
    binding = {
        "source_h5": "/tmp/source.h5",
        "source_sha256": source_sha,
        "provider_role": "reference_control_rho0",
        "trace_schema": TRACE_SCHEMA,
        "backend": BACKEND,
        "seed_hash": seed_hash,
        "intervals_requested": 2,
        "event_definition": {},
        "density_estimator": {"strategy": "rho0_constant_public_current_state_v1"},
    }
    times = np.array([0.0, 1.0, 2.0])
    seeds = np.array([[-.2, 0., 0.], [-.1, 0., 0.], [.1, 0., 0.], [.2, 0., 0.]])
    labels = np.array([0, 0, 1, 1], dtype=np.int8)
    position = np.repeat(seeds[None, :, :], 3, axis=0)
    reliable = np.ones((3, 4), dtype=bool)
    unknown = ~reliable
    first = np.full((3, 4), np.nan)
    returned = np.full((3, 4), np.nan)
    residence = np.zeros((3, 4))
    did_return = np.zeros((3, 4), dtype=bool)
    with h5py.File(trace, "w") as handle:
        handle.attrs.update(trace_schema=TRACE_SCHEMA, backend=BACKEND,
                            material_reliability="not_established",
                            seed_hash=seed_hash,
                            binding_json=json.dumps(binding, sort_keys=True))
        handle.create_dataset("time", data=times)
        handle.create_dataset("seed_position", data=seeds)
        handle.create_dataset("source_label", data=labels)
        handle.create_dataset("position", data=position)
        handle.create_dataset("reliable", data=reliable)
        handle.create_dataset("permanent_unknown", data=unknown)
        handle.create_dataset("first_passage", data=first)
        handle.create_dataset("return_time", data=returned)
        handle.create_dataset("residence_opposite", data=residence)
        handle.create_dataset("returned", data=did_return)
        handle.create_dataset("failure_reason", data=np.full((3, 4), "reliable", dtype="S8"))
    spec = tmp_path / "spec.json"
    module = __import__("scripts.f3_native_volume_mls_model_material", fromlist=["__file__"])
    module_path = module.__file__
    spec_value = {
        "required_outputs": ["trace.h5", "result.json"],
        "argv": ["python", "--intervals", "2"],
        "input_files": [
            {"path": "/tmp/source.h5", "sha256": source_sha},
            {"path": module_path, "sha256": _sha(module_path)},
        ],
    }
    spec.write_text(json.dumps(spec_value))
    receipt = tmp_path / "result.json"
    receipt_value = {
        "execution_status": "succeeded" if terminal else "running",
        "returncode": 0 if terminal else None,
        "job_id": "test-recovery",
        "schema": "core.execution_receipt.v1",
        "usage": {"wall_seconds": 1.0},
        "artifact_index": [
            {"path": "trace.h5", "sha256": _sha(trace), "bytes": trace.stat().st_size},
            {"path": "result.json", "sha256": "lost-science-report", "bytes": 10},
        ],
    }
    receipt.write_text(json.dumps(receipt_value))
    return receipt, spec, trace


def test_recovery_rejects_nonterminal_before_trace_read(tmp_path):
    receipt, spec, _ = _write_case(tmp_path, terminal=False)
    with pytest.raises(ValueError, match="successful terminal"):
        recover_report(receipt, spec, tmp_path / "report.json", tmp_path / "summary.json")


def test_recovery_reconstructs_trace_and_marks_lost_report(tmp_path):
    receipt, spec, trace = _write_case(tmp_path)
    report_path = tmp_path / "report.json"
    summary_path = tmp_path / "summary.json"
    result = recover_report(receipt, spec, report_path, summary_path)
    report = result["report"]
    assert report["status"] == "completed_recovered"
    assert report["recovery_status"] == "recovered_from_terminal_trace"
    assert report["scientific_report_original_available"] is False
    assert report["trace_h5_sha256"] == _sha(trace)
    assert report["execution"]["usage"]["wall_seconds"] == 1.0
    assert report["diagnostics"]["scientific_runner_timing"] is None
    assert report["lost_scientific_report"]["hash_recreated"] is False
    assert summary_path.exists() and report_path.exists()

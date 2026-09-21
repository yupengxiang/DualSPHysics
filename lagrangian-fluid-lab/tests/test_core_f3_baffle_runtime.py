from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts import core_f3_baffle_runtime as runtime


ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / "campaigns/core-v1/cfd/f3-baffle-exchange-source-scope-v1"
CANDIDATE = SCOPE / "candidate-card-v1.json"
MATRIX = SCOPE / "qualification-matrix-v1.json"
DENOMINATOR = SCOPE / "failure-denominator-v1.json"
PREPARED = SCOPE / "anchor-q0p5-dp0p0075-v3/prepared.json"
REVIEW = SCOPE / "runtime-root-review-anchor-v1.json"


def _binding() -> dict:
    return runtime.verify_bindings(candidate_path=CANDIDATE, matrix_path=MATRIX,
                                   denominator_path=DENOMINATOR, prepared_path=PREPARED,
                                   review_path=REVIEW)


def test_dry_binding_is_one_anchor_zero_credit() -> None:
    binding = _binding()
    assert binding["row"]["row_id"] == runtime.TARGET_ROW_ID
    assert binding["row"]["status"] == "not_started"
    assert binding["review"]["execution_policy"]["matrix_credit"] == 0
    assert binding["prepared"]["case_id"] == runtime.TARGET_CASE_ID
    assert binding["geometry"]["fluid_count"] == runtime.TARGET_FLUID_PARTICLES


def test_adapter_rejects_review_that_authorizes_matrix_expansion(tmp_path: Path) -> None:
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    review["authorization"]["matrix_expansion"] = True
    changed = tmp_path / "bad-review.json"
    changed.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="matrix_expansion"):
        runtime.verify_bindings(candidate_path=CANDIDATE, matrix_path=MATRIX,
                                denominator_path=DENOMINATOR, prepared_path=PREPARED,
                                review_path=changed)


def test_baffle_audit_detects_two_way_exchange_and_preserves_zero_credit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _binding()
    monkeypatch.setattr(runtime, "TARGET_TIME_MAX_S", 0.02)
    monkeypatch.setattr(runtime, "TARGET_OUTPUT_INTERVAL_S", 0.01)
    monkeypatch.setattr(runtime, "TARGET_FLUID_PARTICLES", 2)
    trajectory = tmp_path / "trajectory.h5"
    positions = np.asarray([
        [[0.40, 0.30, 0.10], [0.59, 0.23, 0.10]],
        [[0.70, 0.30, 0.10], [0.59, 0.23, 0.10]],
        [[0.40, 0.30, 0.10], [0.59, 0.23, 0.10]],
    ], dtype=np.float64)
    nframes, nparticles = positions.shape[:2]
    with h5py.File(trajectory, "w") as handle:
        handle.attrs["conversion_complete"] = True
        handle.create_dataset("particle_id", data=np.asarray([44174, 44175], dtype=np.uint32))
        handle.create_dataset("particle_zone", data=np.zeros(nparticles, dtype=np.int16))
        handle.create_dataset("source_label_initial_mk", data=np.ones(nparticles, dtype=np.int16))
        handle.create_dataset("time", data=np.asarray([0.0, 0.01, 0.02]))
        handle.create_dataset("position", data=positions)
        handle.create_dataset("velocity", data=np.zeros_like(positions))
        handle.create_dataset("density", data=np.full((nframes, nparticles), 1000.0, dtype=np.float32))
        handle.create_dataset("mass", data=np.ones((nframes, nparticles), dtype=np.float32))
        handle.create_dataset("pressure", data=np.zeros((nframes, nparticles), dtype=np.float32))
        handle.create_dataset("valid", data=np.ones((nframes, nparticles), dtype=bool))
        handle.create_dataset("type", data=np.full((nframes, nparticles), 3, dtype=np.int16))
        handle.create_dataset("mk", data=np.ones((nframes, nparticles), dtype=np.int16))
    report, observations = runtime.audit_trajectory(binding["prepared"], binding["geometry"], trajectory,
                                                     prepared_path=PREPARED)
    assert report["hard_integrity_pass"] is True
    assert report["requested_horizon_reached"] is True
    assert report["wall"]["pass"] is True
    assert observations["event_window_complete"] is True
    assert observations["event"]["exchange"]["forward_pass"] is True
    assert observations["event"]["exchange"]["reverse_pass"] is True
    assert report["matrix_credit"] == 0


def test_job_spec_is_scheduler_valid_and_registry_free(tmp_path: Path) -> None:
    output = tmp_path / "job.json"
    spec = runtime.build_job(lab=ROOT, candidate=CANDIDATE, matrix=MATRIX,
                             denominator=DENOMINATOR, prepared=PREPARED,
                             review=REVIEW, output=output)
    assert spec["matrix_index"] == 4
    assert spec["matrix_credit"] == 0
    assert spec["queue_mutation_authorized"] is False
    assert spec["ledger_mutation_authorized"] is False
    assert spec["registry_mutation_authorized"] is False
    assert len(spec["input_files"]) >= 8

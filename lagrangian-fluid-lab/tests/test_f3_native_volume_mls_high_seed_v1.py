from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from scripts import f3_native_volume_mls_high_seed_v1 as high
from scripts import f3_native_volume_mls_v2 as base


def test_high_seed_rule_is_fixed_midpoint_geometry() -> None:
    points = high.seeds_f3_high()
    assert points.shape == (8192, 3)
    assert points.dtype == np.float64
    assert np.unique(points[:, 0]).size == 64
    assert np.unique(points[:, 1]).size == 16
    assert np.unique(points[:, 2]).size == 8
    assert np.all(points >= base.F3_SOURCE_LOW_M)
    assert np.all(points < base.F3_SOURCE_LOW_M + base.F3_SOURCE_SIZE_M)


def test_high_seed_rule_preserves_equal_source_denominators() -> None:
    binding = high.high_seed_binding()
    assert binding["seed_count"] == 8192
    assert binding["source_seed_counts"] == {"0": 4096, "1": 4096}
    assert binding["source_label_semantics"] == "x < 0 => source 0; x >= 0 => source 1"
    assert binding["semantics_inherited_from"]["interpolation"] is False
    assert binding["semantics_inherited_from"]["future_state"] == "forbidden"


def test_high_seed_rule_does_not_accept_unregistered_counts() -> None:
    with pytest.raises(ValueError, match="exactly 8192"):
        high.seeds_f3_high(16384)


def test_wrapper_restores_runner_generator_and_writes_receipt(tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "trace.h5"
    output.write_bytes(b"diagnostic-output")
    observed: dict[str, object] = {}

    def fake_run_trace(*_args, **kwargs):
        observed["generator"] = base.seeds_f3
        assert kwargs["seeds"] == 8192
        return {
            "schema": "core.material.f3.native_volume_mls.full_cadence_result.v2",
            "status": "completed",
            "seed_count": 8192,
            "source_window": {"last_frame": 4},
            "output": {"path": str(output), "sha256": "placeholder"},
        }

    original = base.seeds_f3
    monkeypatch.setattr(base, "run_trace", fake_run_trace)
    result = high.run_trace("source.h5", output, "prepared.json")
    assert callable(observed["generator"])
    np.testing.assert_array_equal(observed["generator"](8192), high.seeds_f3_high())
    assert base.seeds_f3 is original
    receipt = Path(result["high_seed_receipt"]["path"])
    assert receipt.is_file()
    persisted = json.loads(receipt.read_text())
    assert persisted["qualification_claim"] == high.QUALIFICATION_CLAIM
    assert persisted["high_seed_quadrature"]["seed_count"] == 8192


def test_wrapper_rejects_high_seed_run_that_would_change_seed_semantics(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The wrapper computes and validates the binding before entering the
    # runner, so an accidental alternate count cannot create a partial output.
    with pytest.raises(ValueError, match="exactly 8192"):
        high.run_trace("source.h5", tmp_path / "trace.h5", "prepared.json",
                       seeds=4096)

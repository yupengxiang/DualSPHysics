"""Focused regression coverage for the one-shot F4 supportcap executor."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts import f4_supportcap_affine_query_bound_cpu_canary_execute_v1 as executor
from scripts import f4_supportcap_affine_query_bound_candidate_v3 as candidate
from scripts import f4_tallwall120_material as tallwall


def test_executor_is_fixed_to_the_authorized_cpu_only_scope() -> None:
    source = Path(executor.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert executor.ATTEMPT_ID == "f4-supportcap-affine-query-bound-v3-cpu-native-canary-r001"
    assert executor.OUTPUT.name == executor.ATTEMPT_ID
    assert "subprocess" not in imports
    assert "solver" not in imports
    assert "frame_start" in source  # authorization is checked against a fixed frame contract.
    assert 'spec["mechanisms"][1]["error_estimator"]' in source
    assert "seed_denominator" in source
    assert "same_input_retry" in source
    assert candidate.CANDIDATE_ID == "f4_supportcap_affine_query_bound_v3"


def test_executor_rejects_an_unregistered_namespace_before_any_runtime_work(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="registered F4 one-shot output namespace"):
        executor.run_once(tmp_path / "wrong-namespace")


def test_two_frame_provider_reads_only_the_authorized_adjacent_rows(tmp_path: Path) -> None:
    source = tmp_path / "source.h5"
    particle_count = 8
    with h5py.File(source, "w") as handle:
        handle["time"] = np.arange(42, dtype=float) * 0.004
        position = np.zeros((42, particle_count, 3), dtype=float)
        position[..., 0] = np.arange(42, dtype=float)[:, None]
        handle["position"] = position
        handle["velocity"] = np.ones_like(position)
        handle["valid"] = np.ones((42, particle_count), dtype=bool)
        handle["particle_zone"] = np.zeros(particle_count, dtype=np.int8)
    provider = executor.TwoFrameNativeProvider(source, executor.sha256(source), start=40, stop=41)
    try:
        current = provider.field(0, 0.0)
        interpolated = provider.field(0, 0.5)
        assert current.input_count == particle_count
        assert interpolated.input_count == particle_count
        assert provider.loaded_native_indices == [40, 41]
        assert np.allclose(provider.times, [0.16, 0.164])
    finally:
        provider.close()


def test_tallwall_adapter_binds_the_fixed_v3_variant_without_changing_scope(tmp_path: Path) -> None:
    source = tmp_path / "reference.h5"
    points = np.array([[0.4, 0.2, z] for z in np.linspace(0.2, 0.6, 48)], dtype=float)
    with h5py.File(source, "w") as handle:
        handle["time"] = [0.0, 0.004]
        handle["position"] = np.tile(points, (2, 1, 1))
        handle["velocity"] = np.tile([0.0, 0.0, -0.2], (2, len(points), 1))
        handle["valid"] = np.ones((2, len(points)), dtype=bool)
        handle["type"] = np.full(len(points), 3, dtype=np.int32)
    result = tallwall.trace_tallwall120(
        source, tmp_path / "trace.h5", stop_after=1,
        neighbour_variant="f4_supportcap_affine_query_bound_v3",
    )
    assert result is not None
    binding = result["binding"]
    assert result["scope_id"] == tallwall.SCOPE_ID
    assert binding["backend"] == "f4_ckdtree_visible_shepard_ess32_affine_bound_v3"
    assert binding["neighbour_variant"] == "f4_supportcap_affine_query_bound_v3"
    assert binding["neighbours"] == 32
    assert binding["error_estimator"] == "residual_plus_local_affine_query_bias"


def test_terminal_receipt_retains_the_one_shot_negative_result() -> None:
    receipt_path = executor.OUTPUT / "acceptance-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "failed_one_attempt_zero_credit"
    assert receipt["failure"] == "one or more unchanged fixed canary gates failed"
    assert receipt["gate_evaluation"]["unknown_fraction"] == 1.0
    assert receipt["gate_evaluation"]["unknown_limit"] == 0.01
    assert receipt["native_read_provenance"]["loaded_native_indices"] == [40, 41]
    assert receipt["qualification"]["credit"] == 0
    assert receipt["execution_controls"]["solver_started"] is False
    assert receipt["execution_controls"]["gpu_started"] is False

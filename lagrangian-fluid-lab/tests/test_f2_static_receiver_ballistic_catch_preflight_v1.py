from __future__ import annotations

import numpy as np

from scripts import f2_static_receiver_ballistic_catch_preflight_v1 as preflight


def test_native_audit_passes_clean_synthetic_frame():
    counts = {"total_particles": 3, "boundary_particles": 2, "fluid_particles": 1, "fluid_begin": 2}
    ids = np.arange(3, dtype=np.uint32)
    positions = np.array([[0.0, -0.45, 0.0], [0.35, -0.18, 0.08], [0.60, 0.0, 0.66]], dtype=float)
    velocity = np.zeros((3, 3), dtype=float)
    density = np.full(3, 1000.0, dtype=float)
    result = preflight._audit_native(ids, positions, velocity, density,
                                     {"MassFluid": "7.776"}, counts)
    assert result["all_hard_gates_pass"] is True
    assert result["receiver_surface_overlap_count"] == 0


def test_native_audit_keeps_endpoint_failures_in_hard_gate():
    counts = {"total_particles": 1, "boundary_particles": 0, "fluid_particles": 1, "fluid_begin": 0}
    ids = np.array([0], dtype=np.uint32)
    positions = np.array([[-0.001, 0.0, 0.2]], dtype=float)
    velocity = np.zeros((1, 3), dtype=float)
    density = np.full(1, 1000.0, dtype=float)
    result = preflight._audit_native(ids, positions, velocity, density,
                                     {"MassFluid": "7.776"}, counts)
    assert result["all_hard_gates_pass"] is False
    assert result["outer_wall_endpoint_count"] == 1


def test_preflight_namespace_is_not_allowed_to_reuse_products(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "PREFLIGHT_DIR", tmp_path / "preflight")
    monkeypatch.setattr(preflight, "PREFLIGHT_RECEIPT", tmp_path / "preflight" / "preflight.json")
    monkeypatch.setattr(preflight, "GENERATED_PREFIX", tmp_path / "preflight" / "generated" / "case")
    preflight.PREFLIGHT_DIR.mkdir(parents=True)
    (preflight.PREFLIGHT_DIR / "old-product").write_text("old")
    try:
        preflight._fresh_guard()
    except FileExistsError:
        pass
    else:
        raise AssertionError("freshness guard allowed reused output namespace")

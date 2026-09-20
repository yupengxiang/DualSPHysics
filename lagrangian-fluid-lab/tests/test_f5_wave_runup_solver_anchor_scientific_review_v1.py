from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts/f5_wave_runup_solver_anchor_scientific_review_v1.py"
SPEC = importlib.util.spec_from_file_location("f5_anchor_scientific_review", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _cube_triangles() -> np.ndarray:
    vertices = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 0.0, 1.0],
            [1.0, 1.0, 1.0],
            [0.0, 1.0, 1.0],
        ]
    )
    faces = [
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (3, 2, 6, 7),
        (0, 3, 7, 4),
        (1, 5, 6, 2),
    ]
    return np.asarray(
        [vertices[[a, b, c]] for a, b, c, d in faces for a, b, c in ((a, b, c), (a, c, d))],
        dtype=np.float64,
    )


def test_frame_selection_never_infers_missing_or_future_frames():
    available = [0, 4, 10, 12]
    sampled = MODULE.select_frame_indices(available, sample_count=3)
    assert set(sampled).issubset(set(available))
    assert MODULE.select_frame_indices(available, all_frames=True) == available
    assert 1 not in sampled and 801 not in sampled
    assert MODULE._metadata_time({"RunTime": "0", "TimeStep": "2.0"}) == 2.0


def test_static_mesh_queries_detect_containment_and_saved_chord_crossings():
    mesh = _cube_triangles()
    points = np.asarray([[0.5, 0.2, 0.3], [1.5, 0.2, 0.3]])
    inside = MODULE.points_inside_mesh(points, mesh)
    assert inside.tolist() == [True, False]
    assert MODULE.mesh_is_watertight(mesh)

    segments = MODULE.segment_mesh_crossings(
        np.asarray([[-1.0, 0.2, 0.3], [2.0, 0.2, 0.3]]),
        np.asarray([[2.0, 0.2, 0.3], [3.0, 0.2, 0.3]]),
        mesh,
    )
    assert segments["count"] == 2


def test_frozen_f5_static_geometry_sources_are_readable_and_watertight():
    static_dir = MODULE.DEFAULT_DEFINITION.parent
    static = MODULE.build_static_geometry(
        geometry_path=MODULE.DEFAULT_GEOMETRY,
        slope_path=static_dir / "Slope.stl",
        blocks_path=static_dir / "Blocks_3D_scaled.stl",
        definition_path=MODULE.DEFAULT_DEFINITION,
        preflight=MODULE.validate_preflight(MODULE.DEFAULT_PREFLIGHT),
    )
    assert static["summary"]["boundary_triangle_count"] == 49612
    assert static["summary"]["slope"]["watertight"] is True
    assert static["summary"]["blocks"]["watertight"] is True
    assert static["summary"]["declared_bounds_m"]["min"] == [-1.0, 0.0, -0.2]


def test_incomplete_attempt_stays_pending_and_zero_credit(tmp_path):
    solver = tmp_path / "attempt" / "product" / "solver"
    (solver / "data").mkdir(parents=True)
    (solver / "Run.out").write_text("TimeMax=16\n", encoding="utf-8")
    (solver / "data" / "Part_0000.bi4").write_bytes(b"fixture")

    report = MODULE.review(tmp_path / "attempt", decoder=tmp_path / "missing-decoder")

    assert report["status"] == "scientific_review_pending_runtime_completion"
    assert report["coverage"]["frames_available"] == 1
    assert report["coverage"]["frames_decoded"] == 0
    assert report["qualification_claim"] == "none"
    assert report["qualified"] is False
    assert report["matrix_credit"] == 0
    assert report["t1_credit"] == 0
    assert report["execution_controls"]["solver_invoked_by_review"] is False
    assert report["geometry"]["status"] == "pending_runtime_completion"


def test_event_gates_remain_pending_without_bound_thresholds(tmp_path):
    solver = tmp_path / "solver"
    solver.mkdir()
    for name in MODULE.EXPECTED_GAUGES:
        (solver / f"GaugesSWL_{name}.csv").write_text(
            "0 0 0 0\n0.02 0 0 1\n", encoding="utf-8"
        )
    reference = tmp_path / "reference.txt"
    reference.write_text(
        "time WG1 WG2 WG3 WG4 RunUp\n0 0 0 0 0 0\n0.02 1 1 1 1 1\n", encoding="utf-8"
    )

    gauges = MODULE.gauge_audit(solver)
    events = MODULE.event_audit(gauges["records"], reference)

    assert events["incident_order"]["status"] == "pending_preregistered_threshold"
    assert events["runup_threshold"]["status"] == "pending_preregistered_threshold"
    assert events["return_threshold"]["status"] == "pending_preregistered_threshold"
    assert events["incident_order"]["threshold_bound"] is False
    assert events["external_gauges"]["acceptance_status"] == "pending_preregistered_reference_envelope"

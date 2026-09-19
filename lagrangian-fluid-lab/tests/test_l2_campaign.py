from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts import l2_campaign
from scripts.l2_reader import case_metadata, load_manifest, read_frame


def _write_trajectory(
    path: Path,
    *,
    valid: np.ndarray,
    positions: np.ndarray | None = None,
    velocities: np.ndarray | None = None,
    mass: np.ndarray | None = None,
    lifecycle_model: str = "closed",
) -> None:
    frames, particles = valid.shape
    positions = np.zeros((frames, particles, 3), dtype=np.float64) if positions is None else positions
    velocities = np.zeros((frames, particles, 3), dtype=np.float64) if velocities is None else velocities
    mass = np.ones((frames, particles), dtype=np.float64) if mass is None else mass
    with h5py.File(path, "w") as handle:
        handle["time"] = np.arange(frames, dtype=np.float64) * 0.1
        handle["position"] = positions
        handle["velocity"] = velocities
        handle["mass"] = mass
        handle["particle_id"] = np.arange(particles, dtype=np.int64)
        handle["valid"] = valid
        handle.attrs["lifecycle_model"] = lifecycle_model


def test_hdf5_inspection_rejects_missing_and_accepts_minimal(tmp_path: Path):
    missing = l2_campaign.inspect_hdf5(tmp_path / "missing.h5")
    assert missing["structural_pass"] is False
    path = tmp_path / "case.h5"
    with h5py.File(path, "w") as handle:
        handle["time"] = np.array([0.0, 0.1])
        handle["position"] = np.zeros((2, 2, 3), dtype=np.float32)
        handle["velocity"] = np.zeros((2, 2, 3), dtype=np.float32)
        handle["mass"] = np.ones((2, 2), dtype=np.float32)
        handle["particle_id"] = np.array([1, 2], dtype=np.uint32)
        handle["valid"] = np.ones((2, 2), dtype=bool)
    report = l2_campaign.inspect_hdf5(path, full_scan=True, wall_bounds=l2_campaign.F3_WALL_BOUNDS)
    assert report["structural_pass"] is True
    assert report["frame_count"] == 2
    assert report["particle_count"] == 2


def test_reader_resolves_case_and_frame(tmp_path: Path):
    lab_root = tmp_path / "lab"
    data = lab_root / "data"
    data.mkdir(parents=True)
    path = data / "toy.h5"
    with h5py.File(path, "w") as handle:
        handle["time"] = np.array([0.0, 0.1])
        handle["position"] = np.arange(12, dtype=np.float32).reshape(2, 2, 3)
        handle["velocity"] = np.ones((2, 2, 3), dtype=np.float32)
        handle["valid"] = np.ones((2, 2), dtype=bool)
        handle["particle_id"] = np.array([3, 4], dtype=np.uint32)
    manifest_path = lab_root / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema": "l2.f3.canonical_manifest.v1",
        "repository_root": str(lab_root),
        "cases": [{"case_id": "toy", "hdf5": "data/toy.h5", "sha256": "x"}],
    }))
    manifest = load_manifest(manifest_path)
    frame = read_frame(manifest, "toy", 1, fields=("position", "valid"))
    assert frame["time"] == 0.1
    assert frame["position"].shape == (2, 3)
    assert frame["valid"].all()
    assert case_metadata(manifest, "toy")["datasets"]["position"] == [2, 2, 3]


def test_failure_summary_separates_wall_and_runtime():
    record = l2_campaign.summarize_replay_case("run", "route", 1, {
        "case_id": "case",
        "status": "failed",
        "expected_frames": 10,
        "saved_frames": 8,
        "hard_wall_passed": False,
        "first_failure": {"kind": "hard_wall_or_crossing", "time_s": 0.2,
                           "first_crossing": {"kind": "closed_face", "face": "left"}},
        "terminal_failure": {"kind": "runtime_or_nonfinite_failure"},
        "metrics_mean": {"unmatched_support_mass": 0.5},
    })
    assert record["rollout_complete"] is False
    assert record["first_crossing_face"] == "left"
    assert record["finite_failure_observed"] is True
    assert record["unmatched_support_mass_fraction"] == 0.5


def test_hdf5_masks_inactive_nan_but_retains_closed_lifecycle_failure(tmp_path: Path):
    path = tmp_path / "masked.h5"
    valid = np.array([[True, True], [True, False]])
    positions = np.zeros((2, 2, 3), dtype=np.float64)
    velocities = np.zeros_like(positions)
    mass = np.ones((2, 2), dtype=np.float64)
    positions[1, 1] = np.nan
    velocities[1, 1] = np.nan
    mass[1, 1] = np.nan
    _write_trajectory(path, valid=valid, positions=positions, velocities=velocities, mass=mass)

    report = l2_campaign.inspect_hdf5(path, wall_bounds=l2_campaign.F3_WALL_BOUNDS)

    assert report["finite_active"]["position"] is True
    assert report["finite_active"]["velocity"] is True
    assert report["finite_active"]["mass"] is True
    assert report["inactive_nonfinite_counts"]["position"] == 1
    assert "nonfinite:position" not in report["errors"]
    assert "lifecycle:closed_transition" in report["errors"]
    assert report["initial_mass_kg"] == pytest.approx(2.0)
    assert report["final_mass_kg"] == pytest.approx(1.0)
    assert report["structural_pass"] is False


def test_hdf5_rejects_negative_active_mass(tmp_path: Path):
    path = tmp_path / "negative-mass.h5"
    _write_trajectory(
        path,
        valid=np.ones((2, 2), dtype=bool),
        mass=-np.ones((2, 2), dtype=np.float64),
    )

    report = l2_campaign.inspect_hdf5(path, wall_bounds=l2_campaign.F3_WALL_BOUNDS)

    assert report["active_mass_positive"] is False
    assert "mass:active_nonpositive_or_nonfinite" in report["errors"]
    assert report["structural_pass"] is False


def test_hdf5_rejects_temporal_active_mass_change(tmp_path: Path):
    path = tmp_path / "changing-mass.h5"
    _write_trajectory(
        path,
        valid=np.ones((2, 1), dtype=bool),
        mass=np.array([[1.0], [1.5]]),
    )

    report = l2_campaign.inspect_hdf5(path, wall_bounds=l2_campaign.F3_WALL_BOUNDS)

    assert report["mass_change_max_relative"] == pytest.approx(0.5)
    assert "mass:active_change" in report["errors"]
    assert report["structural_pass"] is False


def test_hdf5_finite_open_rim_is_not_side_wall_penetration(tmp_path: Path):
    path = tmp_path / "open-rim.h5"
    spec = {
        "xmin": 0.0, "xmax": 1.2, "ymin": 0.0, "ymax": 0.4,
        "zmin": 0.0, "zmax": 0.6,
        "closed_faces": ["bottom", "left", "right", "front", "back"],
        "open_faces": ["top"],
    }
    positions = np.array([[[1.21, 0.2, 0.601]], [[1.21, 0.2, 0.601]]])
    _write_trajectory(path, valid=np.ones((2, 1), dtype=bool), positions=positions)

    report = l2_campaign.inspect_hdf5(path, wall_bounds=spec)

    assert report["wall_status"] == "checked"
    assert report["wall_violation_count"] == 0
    assert report["structural_pass"] is True


def test_hdf5_requires_finite_geometry_and_marks_moving_geometry_unknown(tmp_path: Path):
    path = tmp_path / "geometry-unknown.h5"
    _write_trajectory(path, valid=np.ones((2, 1), dtype=bool))

    legacy = l2_campaign.inspect_hdf5(
        path, wall_bounds={"xmin": 0.0, "xmax": 1.0, "ymin": 0.0, "ymax": 1.0, "zmin": 0.0}
    )
    moving = l2_campaign.inspect_hdf5(
        path,
        wall_spec={
            "container_interior": {"xmin": 0.0, "xmax": 1.0, "ymin": 0.0, "ymax": 1.0, "zmin": 0.0, "zmax": 1.0},
            "moving_geometry_required": True,
        },
    )

    assert legacy["wall_status"] == "unknown"
    assert "wall:finite_geometry_unknown" in legacy["errors"]
    assert moving["wall_status"] == "unknown"
    assert "wall:finite_geometry_unknown" in moving["errors"]


def test_blocked_stage_does_not_release_dependents(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    campaign = tmp_path / "campaign"
    monkeypatch.setattr(l2_campaign, "CAMPAIGN", campaign)
    state = {
        "owner_adoption_status": "accepted",
        "stages": {"A0": {"status": "ready"}, "A1": {"status": "pending"}},
        "resource_usage": {},
    }
    queue = {
        "tasks": [
            {"task_id": "A0", "stage": "A0", "status": "ready", "requires": []},
            {"task_id": "A1", "stage": "A1", "status": "pending", "requires": ["A0"]},
        ]
    }
    l2_campaign.atomic_json(campaign / "state.json", state)
    l2_campaign.atomic_json(campaign / "queue.json", queue)

    l2_campaign.update_stage("A0", "blocked")
    assert json.loads((campaign / "queue.json").read_text())["tasks"][1]["status"] == "pending"

    with pytest.raises(ValueError, match="auditable blocker evidence"):
        l2_campaign.update_stage("A0", "blocked_external")
    assert json.loads((campaign / "queue.json").read_text())["tasks"][1]["status"] == "pending"

    l2_campaign.atomic_json(campaign / "reports" / "a0-blocker.json", {"evidence": "fixture"})
    l2_campaign.update_stage(
        "A0",
        "blocked_external",
        facts={
            "report": "reports/a0-blocker.json",
            "external_blocker": {
                "id": "fixture-external",
                "requirement": "owner supplied anchor",
                "evidence": {"report": "reports/a0-blocker.json"},
                "release_conditions": ["owner supplies the anchor"],
            },
        },
    )
    assert json.loads((campaign / "queue.json").read_text())["tasks"][1]["status"] == "ready"


@pytest.mark.parametrize(
    "gate_facts",
    [
        {"canary_pass": False},
        {"new_training_attempts": 0},
        {"new_qualified_t1_recipe_count": 0},
    ],
)
def test_explicit_failed_gate_cannot_be_recorded_as_complete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, gate_facts: dict,
):
    campaign = tmp_path / "campaign"
    monkeypatch.setattr(l2_campaign, "CAMPAIGN", campaign)
    state = {
        "owner_adoption_status": "accepted",
        "stages": {"A0": {"status": "ready"}},
        "resource_usage": {},
    }
    queue = {"tasks": [{"task_id": "A0", "stage": "A0", "status": "ready", "requires": []}]}
    l2_campaign.atomic_json(campaign / "state.json", state)
    l2_campaign.atomic_json(campaign / "queue.json", queue)
    l2_campaign.atomic_json(campaign / "reports" / "gate.json", {"fixture": True})

    l2_campaign.update_stage("A0", "complete", facts={"report": "reports/gate.json", **gate_facts})

    stored = json.loads((campaign / "state.json").read_text())
    assert stored["stages"]["A0"]["status"] == "complete_with_findings"
    assert stored["stages"]["A0"]["facts"]["controller_downgrade"]["requested_status"] == "complete"

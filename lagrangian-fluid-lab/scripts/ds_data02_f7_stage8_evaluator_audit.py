#!/usr/bin/env python3
"""Stage 8 Evaluator and Native Labels Audit for Family F7.

Verifies:
1. Native labels exist, are valid, complete, and match schema contracts.
2. Exact reference self-comparison evaluation yields valid=True, 0 failures, 0 wall crossings, and 0 error.
3. Explicit failure detection catches mismatched trajectories or condition bindings.
4. Generates campaigns/ds-data-02/families/F7/stage8_evaluator_summary.json.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import h5py
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from ds_data02_f7_evaluator import evaluate_f7

DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7")
CAMPAIGN_F7 = REPO_ROOT / "campaigns" / "ds-data-02" / "families" / "F7"

CASES = [
    {"case_id": "F7_PUMP_P00_FINE", "mechanism": "pump_recirculation"},
    {"case_id": "F7_PUMP_P01_FINE", "mechanism": "pump_recirculation"},
    {"case_id": "F7_PUMP_P02_FINE", "mechanism": "pump_recirculation"},
    {"case_id": "F7_PUMP_P03_FINE", "mechanism": "pump_recirculation"},
    {"case_id": "F7_OBSTACLE_P00_FINE", "mechanism": "moving_obstacle_exchange"},
    {"case_id": "F7_OBSTACLE_P01_FINE", "mechanism": "moving_obstacle_exchange"},
    {"case_id": "F7_OBSTACLE_P02_FINE", "mechanism": "moving_obstacle_exchange"},
    {"case_id": "F7_OBSTACLE_P03_FINE", "mechanism": "moving_obstacle_exchange"},
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def audit_case(case_info: dict[str, str]) -> dict[str, Any]:
    case_id = case_info["case_id"]
    mechanism = case_info["mechanism"]
    case_dir = DATA_ROOT / case_id

    traj_path = case_dir / "full-typed-native-conversion-001" / "trajectory.h5"
    labels_path = case_dir / "native-transport-labels-001" / "native-labels.h5"
    receipt_path = case_dir / "native-transport-labels-001" / "execution-receipt.json"

    if not traj_path.exists():
        raise FileNotFoundError(f"Trajectory missing for {case_id}: {traj_path}")
    if not labels_path.exists():
        raise FileNotFoundError(f"Native labels missing for {case_id}: {labels_path}")
    if not receipt_path.exists():
        raise FileNotFoundError(f"Receipt missing for {case_id}: {receipt_path}")

    traj_sha = sha256_file(traj_path)
    labels_sha = sha256_file(labels_path)
    receipt_data = json.loads(receipt_path.read_text(encoding="utf-8"))

    # Verify receipt matches
    assert receipt_data["case_id"] == case_id
    assert receipt_data["output_sha256"] == labels_sha
    assert receipt_data["source_trajectory_sha256"] == traj_sha

    # Verify labels contents
    with h5py.File(labels_path, "r") as h:
        assert bool(h.attrs["complete"]) is True
        assert bool(h.attrs["model_invoked"]) is False
        assert h.attrs["schema"] == "ds02.f7.native-event-labels.v1"
        assert h.attrs["standard_schema"] == "ds-data-02.native-labels.v1"
        assert h.attrs["physical_mechanism"] == mechanism

        num_fluid = int(h.attrs["fluid_particles"])
        num_frames = int(h["time"].shape[0])
        init_mass = float(h.attrs["initial_fluid_mass_kg"])

        # Check datasets exist
        for ds in [
            "time",
            "particle_id",
            "particle_zone",
            "source_zone",
            "destination_time_series",
            "final_category",
            "first_crossing_interval",
            "first_crossing_time_s",
            "first_passage_censor",
            "total_crossing_count",
            "cyclic_recrossing_count",
            "residence_time_s",
            "source_final_mass_kg",
        ]:
            assert ds in h, f"Missing dataset {ds} in {labels_path}"

        tot_cross = h["total_crossing_count"][:]
        recross = h["cyclic_recrossing_count"][:]
        expected_recross = np.maximum(0, tot_cross - 1)
        np.testing.assert_array_equal(recross, expected_recross)

        censor = h["first_passage_censor"][:]
        first_time = h["first_crossing_time_s"][:]
        first_int = h["first_crossing_interval"][:]

        # Censors must have NaN time and NaN interval
        censored_mask = censor == 1
        assert np.all(np.isnan(first_time[censored_mask]))
        assert np.all(np.isnan(first_int[censored_mask]))

        # Uncensored must have valid time >= 0 and interval >= 0 with t0 <= t1
        uncensored_mask = censor == 0
        assert np.all(np.isfinite(first_time[uncensored_mask]))
        assert np.all(np.isfinite(first_int[uncensored_mask]))
        assert np.all(first_int[uncensored_mask][:, 0] <= first_int[uncensored_mask][:, 1])

        # Mass conservation
        source_final_mass = h["source_final_mass_kg"][:]
        total_source_final_mass = float(np.sum(source_final_mass))
        np.testing.assert_allclose(total_source_final_mass, init_mass, rtol=1e-5)

        total_crossings = int(np.sum(tot_cross))
        total_recrossings = int(np.sum(recross))
        uncensored_count = int(np.sum(uncensored_mask))

    # Evaluate trajectory (exact reference self-comparison)
    eval_res = evaluate_f7(traj_path, traj_path, mechanism=mechanism)
    assert eval_res["valid"] is True, f"Self-eval failed for {case_id}: {eval_res['failures']}"
    assert len(eval_res["failures"]) == 0
    assert eval_res["containment_compliant"] is True
    assert eval_res["finite_wall_crossing_count"] == 0
    assert eval_res["open_top_exit_count"] == 0
    assert max(eval_res["mass_absolute_error_fraction"]) == 0.0
    assert max(eval_res["position_error_per_initial_mass"]) == 0.0
    assert max(eval_res["velocity_error_per_initial_mass"]) == 0.0

    return {
        "case_id": case_id,
        "mechanism": mechanism,
        "fluid_particles": num_fluid,
        "frames": num_frames,
        "initial_fluid_mass_kg": init_mass,
        "total_crossing_events": total_crossings,
        "total_cyclic_recrossings": total_recrossings,
        "uncensored_first_passages": uncensored_count,
        "trajectory_sha256": traj_sha,
        "native_labels_sha256": labels_sha,
        "labels_path": str(labels_path),
        "receipt_path": str(receipt_path),
        "self_evaluation": {
            "valid": eval_res["valid"],
            "failures": eval_res["failures"],
            "containment_compliant": eval_res["containment_compliant"],
            "finite_wall_crossing_count": eval_res["finite_wall_crossing_count"],
            "open_top_exit_count": eval_res["open_top_exit_count"],
            "max_mass_error_fraction": max(eval_res["mass_absolute_error_fraction"]),
            "max_position_error_per_mass": max(eval_res["position_error_per_initial_mass"]),
            "max_velocity_error_per_mass": max(eval_res["velocity_error_per_initial_mass"]),
        },
    }


def main():
    print("Running Family F7 Stage 8 Evaluator & Native Labels Audit...")
    results = []
    for c in CASES:
        print(f"Auditing {c['case_id']}...")
        res = audit_case(c)
        results.append(res)
        print(f"  [OK] {c['case_id']}: fluid={res['fluid_particles']}, crossings={res['total_crossing_events']}, recrossings={res['total_cyclic_recrossings']}, self_eval valid={res['self_evaluation']['valid']}")

    # Cross-comparison negative tests
    print("Running negative cross-comparison checks...")
    pump_ref = DATA_ROOT / "F7_PUMP_P00_FINE" / "full-typed-native-conversion-001" / "trajectory.h5"
    pump_cand = DATA_ROOT / "F7_PUMP_P01_FINE" / "full-typed-native-conversion-001" / "trajectory.h5"
    cross_res = evaluate_f7(pump_ref, pump_cand, mechanism="pump_recirculation")
    assert not cross_res["valid"], "Expected cross-comparison to fail"
    assert len(cross_res["failures"]) > 0
    print(f"  [OK] Cross-comparison detected expected failure/deviation: failures={cross_res['failures']}")

    summary_file = CAMPAIGN_F7 / "stage8_evaluator_summary.json"
    summary_file.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"\nAudit complete. Wrote {summary_file}")


if __name__ == "__main__":
    main()

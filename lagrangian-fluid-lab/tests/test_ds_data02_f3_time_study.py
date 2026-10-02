import json
from pathlib import Path

import h5py
import numpy as np

from scripts import ds_data02_f3_time_study as study


ROOT = Path(__file__).resolve().parents[1]
F3 = ROOT / "campaigns/ds-data-02/families/F3"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_DUAL_AXIS_WEAK_006G_004G")


def _minimal_h5(path: Path, offset: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    times = np.array([0.0, 5.0, 10.0])
    # Two fixed identities and two fluid identities; the fluid COM is shifted
    # by ``offset`` in the candidate so the comparison must report a difference.
    positions = np.zeros((3, 4, 3), dtype=np.float64)
    positions[:, 2, 0] = np.array([0.0, 0.5, 1.0]) + offset
    positions[:, 3, 0] = np.array([1.0, 1.5, 2.0]) + offset
    velocity = np.zeros_like(positions)
    velocity[:, 2, 0] = 0.1
    velocity[:, 3, 0] = 0.2
    valid = np.ones((3, 4), dtype=np.bool_)
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=times)
        h5.create_dataset("initial_type", data=np.array([0, 0, 3, 3], dtype=np.int8))
        h5.create_dataset("initial_mass", data=np.full(4, 0.5))
        h5.create_dataset("valid", data=valid)
        h5.create_dataset("mass", data=np.full((3, 4), 0.5))
        h5.create_dataset("position", data=positions)
        h5.create_dataset("velocity", data=velocity)
        h5.attrs["coordinate_frame"] = "fixed_tank_acceleration"


def test_real_baseline_dt_and_population_are_registered():
    result = study.measure_baseline(
        DATA / "qualification-weak-dual-scope-001/solver_output/RunPARTs.csv",
        DATA / "qualification-weak-dual-scope-001/solver_output/Run.csv",
        DATA / "qualification-weak-dual-scope-001/solver_output/Run.out",
    )
    assert result["runparts"]["saved_frames"] == 4001
    assert result["runparts"]["initial_fluid_particles"] == 34560
    assert result["runparts"]["npout_sum"] == 0
    assert result["runparts"]["native_minimum_dt_s"] == study.BASELINE_DT_MIN_S
    assert result["runparts"]["time_end_s"] > 10.0
    assert result["run_out_parameters"]["time_out_s"] == study.BASELINE_SAVE_S
    assert result["run_out_parameters"]["time_out_source_label"] == "TimePart"


def test_fixed_window_comparison_records_brackets_and_error(tmp_path):
    baseline = tmp_path / "baseline.h5"
    candidate = tmp_path / "candidate.h5"
    output = tmp_path / "comparison.json"
    _minimal_h5(baseline)
    _minimal_h5(candidate, offset=0.1)
    result = study.compare_fixed_window(
        type("Args", (), {"baseline": baseline, "variant": [candidate], "grid_step": 2.5, "output": output})()
    )
    row = result["comparisons"][candidate.stem]
    assert row["times"]["frame_count"] == 3
    assert len(row["time_brackets"]) == 5
    assert row["macro_error"]["com_x_m"]["max_abs"] > 0
    assert result["claim_boundary"].endswith("Q-N and production remain unassessed")


def test_variant_patch_preserves_physical_hash_and_changes_only_numeric_fields(tmp_path):
    owner_path = F3 / "weak_dual_scope_001/f3_weak_owner_metadata.json"
    owner = json.loads(owner_path.read_text())
    owner["_path"] = str(owner_path)
    baseline = study.measure_baseline(
        DATA / "qualification-weak-dual-scope-001/solver_output/RunPARTs.csv",
        DATA / "qualification-weak-dual-scope-001/solver_output/Run.csv",
        DATA / "qualification-weak-dual-scope-001/solver_output/Run.out",
    )
    output = tmp_path / "source"
    result = study._write_variant(
        Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/weak_dual_scope_001/F3_DUAL_AXIS_WEAK_006G_004G_Def.xml"),
        DATA / "gencase-weak-dual-scope-001/F3_DualAxisPhase_WeakControl.csv",
        output,
        "half_dt",
        baseline,
        owner,
    )
    assert result["physical_binding_sha256"] == study.PHYSICAL_BINDING_SHA
    root = study.ET.parse(result["variant_definition"]["path"]).getroot()
    assert study._parameter(root, "DtFixed").get("value") == "1.106134843353494e-05"
    assert study._parameter(root, "TimeOut").get("value") == "0.0025"

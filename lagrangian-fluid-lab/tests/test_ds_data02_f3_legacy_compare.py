from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from scripts.ds_data02_f3_legacy_compare import compare_subset


def _write_pair(tmp_path: Path) -> tuple[Path, Path]:
    direct = tmp_path / "direct.h5"
    reference = tmp_path / "reference.h5"
    frames = 3
    direct_ids = np.asarray([0, 73440, 73441, 73442], dtype="u4")
    fluid_positions = np.asarray([
        [[0.0, 0.0, 0.04], [0.1, 0.0, 0.04], [0.2, 0.0, 0.04]],
        [[0.0, 0.0, 0.05], [0.1, 0.0, 0.05], [0.2, 0.0, 0.05]],
        [[0.0, 0.0, 0.06], [0.1, 0.0, 0.06], [0.2, 0.0, 0.06]],
    ], dtype="f4")
    with h5py.File(direct, "w") as h:
        h.create_dataset("time", data=np.asarray([0.0, 1.0, 2.0]))
        h.create_dataset("particle_id", data=direct_ids)
        h.create_dataset("particle_zone", data=np.zeros(4, dtype="i2"))
        h.create_dataset("valid", data=np.ones((frames, 4), dtype=bool))
        h.create_dataset("type", data=np.asarray([[0, 3, 3, 3]] * frames, dtype="i1"))
        h.create_dataset("mk", data=np.asarray([[10, 1, 1, 1]] * frames, dtype="i2"))
        h.create_dataset("position", data=np.concatenate([np.zeros((frames, 1, 3), dtype="f4"), fluid_positions], axis=1))
        h.create_dataset("velocity", data=np.zeros((frames, 4, 3), dtype="f4"))
        h.create_dataset("density", data=np.full((frames, 4), 1000.0, dtype="f4"))
        h.create_dataset("mass", data=np.full((frames, 4), 0.1, dtype="f4"))
        h.create_dataset("pressure", data=np.zeros((frames, 4), dtype="f4"))
    with h5py.File(reference, "w") as h:
        h.create_dataset("time", data=np.asarray([0.0, 1.0, 2.0]))
        h.create_dataset("particle_id", data=direct_ids[1:])
        h.create_dataset("particle_zone", data=np.zeros(3, dtype="i2"))
        h.create_dataset("valid", data=np.ones((frames, 3), dtype=bool))
        h.create_dataset("type", data=np.full((frames, 3), 3.0, dtype="f4"))
        h.create_dataset("mk", data=np.ones((frames, 3), dtype="f4"))
        h.create_dataset("position", data=fluid_positions)
        h.create_dataset("velocity", data=np.zeros((frames, 3, 3), dtype="f4"))
        h.create_dataset("density", data=np.full((frames, 3), 1000.0, dtype="f4"))
        h.create_dataset("mass", data=np.full((frames, 3), 0.1, dtype="f4"))
        h.create_dataset("pressure", data=np.zeros((frames, 3), dtype="f4"))
    return direct, reference


def test_legacy_comparator_aligns_fluid_only_reference_by_typed_identity(tmp_path: Path) -> None:
    direct, reference = _write_pair(tmp_path)
    report = compare_subset(direct_path=direct, reference_path=reference, output_path=tmp_path / "compare.json")
    assert report["passed"] is True
    assert report["alignment"]["direct_reference_indices_contiguous"] is True
    assert report["numeric_within_tolerance"]["pressure"] is True


def test_legacy_comparator_rejects_boundary_id_in_reference(tmp_path: Path) -> None:
    direct, reference = _write_pair(tmp_path)
    with h5py.File(reference, "r+") as h:
        h["particle_id"][0] = 0
    try:
        compare_subset(direct_path=direct, reference_path=reference, output_path=tmp_path / "compare.json")
    except Exception as exc:  # exact type is part of the module's public rejection boundary
        assert "initial type=3" in str(exc) or "absent" in str(exc)
    else:
        raise AssertionError("reference boundary identity was not rejected")

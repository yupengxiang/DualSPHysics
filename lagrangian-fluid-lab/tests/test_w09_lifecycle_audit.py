from pathlib import Path

import h5py
import numpy as np

from scripts.w09_lifecycle_audit import audit_hdf5


def test_lifecycle_audit_detects_birth_death_and_compound_ids(tmp_path: Path):
    path = tmp_path / "life.h5"
    valid = np.asarray([[1, 0, 1], [1, 1, 0], [0, 1, 1]], dtype=bool)
    with h5py.File(path, "w") as h5:
        h5.attrs["case_id"] = "synthetic"
        h5.attrs["identity_key"] = "(particle_zone, particle_id)"
        h5.create_dataset("valid", data=valid)
        h5.create_dataset("time", data=[0.0, 0.1, 0.2])
        h5.create_dataset("particle_id", data=[1, 1, 2])
        h5.create_dataset("particle_zone", data=[0, 1, 1])
        h5.create_dataset("mass", data=np.ones((3, 3), dtype=np.float32))
        h5.create_dataset("type", data=np.full((3, 3), 3, dtype=np.int8))
    result = audit_hdf5(path)
    assert result["born_after_initial"] == 1
    assert result["initial_missing_at_final"] == 1
    assert result["multiple_validity_episodes"] == 1
    assert result["raw_particle_id_duplicates"] == 1
    assert result["compound_identity_duplicates"] == 0
